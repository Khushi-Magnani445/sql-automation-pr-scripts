import os
import sys
import subprocess
import difflib
import re
import argparse
from typing import List, Dict

def run_command(cmd: List[str], check=True) -> str:
    """Helper to run shell commands and return output."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}")
        if result.stdout:
            print(f"Output: {result.stdout.strip()}")
        if result.stderr:
            print(f"Error: {result.stderr.strip()}")
        sys.exit(result.returncode)
    return result.stdout.strip()

def get_git_file_content(base_branch: str, file_path: str) -> str:
    """Gets the content of a file from a specific git branch. If it fails, assumes file is new/empty."""
    try:
        # Use git show to get the file at the target branch (using origin)
        cmd = ["git", "show", f"origin/{base_branch}:{file_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        return ""
    except Exception:
        return ""

def get_local_file_content(file_path: str) -> str:
    """Gets the current local file content."""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def parse_sql_view(sql_text: str):
    """Attempt to extract View Name and the SELECT column mappings from SQL text."""
    import re
    # Find all View Names
    view_matches = list(re.finditer(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:SECURE\s+)?VIEW\s+([a-zA-Z0-9_\.]+)', sql_text, re.IGNORECASE))
    
    if not view_matches:
        return "Unknown View", []
        
    # Use the first view name found as the primary identifier
    view_name = view_matches[0].group(1) 
    
    columns = []
    select_matches = re.finditer(r'\bSELECT\b(.*?)\bFROM\b', sql_text, re.IGNORECASE | re.DOTALL)
    for select_match in select_matches:
        select_block = select_match.group(1).strip()
        paren_level = 0
        current_col = []
        for char in select_block:
            if char == '(': paren_level += 1
            elif char == ')': paren_level -= 1
            elif char == ',' and paren_level == 0:
                col_str = "".join(current_col).strip()
                if col_str: columns.append(col_str)
                current_col = []
                continue
            current_col.append(char)
        if current_col:
            col_str = "".join(current_col).strip()
            if col_str: columns.append(col_str)
            
    return view_name, columns

def get_sql_diff_summary(base_branch: str, changed_files: List[str]) -> str:
    """Generates a highly intelligent SQL mapping difference summary."""
    summary_lines = []
    
    for file_path in changed_files:
        if not file_path.endswith('.sql'):
            continue
            
        old_content = get_git_file_content(base_branch, file_path)
        new_content = get_local_file_content(file_path)
        
        old_view, old_cols = parse_sql_view(old_content)
        new_view, new_cols = parse_sql_view(new_content)
        
        summary_lines.append(f"### 📄 `{file_path}`")
        if old_view != new_view and "Unknown" not in old_view:
            summary_lines.append(f"**📝 View Name Changed:** `{old_view}` ➔ `{new_view}`")
        else:
            summary_lines.append(f"**🔗 Object:** `{new_view}`")
            
        added_cols = []
        removed_cols = []
        modified_mappings = []
        
        old_col_map = {c.split()[-1].lower(): c for c in old_cols} if old_cols else {}
        new_col_map = {c.split()[-1].lower(): c for c in new_cols} if new_cols else {}
        
        for alias, complete_def in new_col_map.items():
            if alias not in old_col_map:
                added_cols.append(complete_def)
            elif old_col_map[alias] != complete_def:
                modified_mappings.append(f"`{old_col_map[alias]}` ➔ `{complete_def}`")
                
        for alias, complete_def in old_col_map.items():
            if alias not in new_col_map:
                removed_cols.append(complete_def)
                
        if added_cols:
            summary_lines.append("\n**🟢 Added Columns:**")
            for c in added_cols: summary_lines.append(f"- `{c}`")
            
        if modified_mappings:
            summary_lines.append("\n**🟡 Modified Mappings:**")
            for c in modified_mappings: summary_lines.append(f"- {c}")
            
        if removed_cols:
            summary_lines.append("\n**🔴 Removed Columns:**")
            for c in removed_cols: summary_lines.append(f"- `{c}`")
            
        if not old_cols and not new_cols:
            # Fallback
            old_lines = [l.strip() for l in old_content.splitlines() if l.strip()]
            new_lines = [l.strip() for l in new_content.splitlines() if l.strip()]
            diff = list(difflib.ndiff(old_lines, new_lines))
            added = [l[2:] for l in diff if l.startswith('+ ')]
            removed = [l[2:] for l in diff if l.startswith('- ')]
            if added:
                summary_lines.append("\n**🟢 Added/Modified Lines:**")
                for item in added: summary_lines.append(f"- `{item.rstrip(',')}`")
            if removed:
                summary_lines.append("\n**🔴 Removed/Old Lines:**")
                for item in removed: summary_lines.append(f"- `{item.rstrip(',')}`")
                
        summary_lines.append("\n---")
        
    return "\n".join(summary_lines)

def main():
    parser = argparse.ArgumentParser(description="Automate Committing, Diffing, and PR creation for SQL scripts.")
    parser.add_argument("-b", "--base", default="main", help="Base branch (target environment) to compare against.")
    parser.add_argument("-t", "--title", required=True, help="PR Title.")
    parser.add_argument("-m", "--commit-msg", help="Commit message (defaults to PR title).")
    args = parser.parse_args()

    commit_msg = args.commit_msg if args.commit_msg else args.title
    
    # 1. Check if git status has changes
    status = run_command(["git", "status", "--porcelain"])
    
    if status:
        print("\n--- 📝 Pushing Local Changes ---")
        # Extract changed sql files to run syntax check
        changed_sql_files = []
        for line in status.splitlines():
            # line could be " M file.sql" or "?? file.sql" etc.
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                filepath = parts[1]
                if filepath.endswith(".sql"):
                    changed_sql_files.append(filepath)
                
        # 2. Run the syntax checker before allowing commit
        if changed_sql_files:
            syntax_checker_path = os.path.join(os.path.dirname(__file__), "check_sql_syntax.py")
            if os.path.exists(syntax_checker_path):
                print("\n--- 🔍 Validating SQL Syntax ---")
                try:
                    run_command([sys.executable, syntax_checker_path] + changed_sql_files)
                except SystemExit as e:
                    print("❌ Syntax check failed! Please fix the errors above before the PR can be raised.")
                    sys.exit(1)
            
        # 3. Stage and commit
        print("Staging and committing files...")
        run_command(["git", "add", "."])
        run_command(["git", "commit", "-m", commit_msg])

    # 4. Push to origin (assuming current branch)
    current_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if current_branch == args.base:
        print("❌ Cannot create a PR from the base branch to itself. Please checkout a new branch.")
        sys.exit(1)

    print(f"\n--- ☁️ Pushing branch '{current_branch}' to origin ---")
    run_command(["git", "push", "-u", "origin", current_branch])

    # 5. Get Diff Summary
    print(f"\n--- 📊 Generating SQL Definitions Diff vs '{args.base}' ---")
    
    # Pre-fetch the base branch from origin so local git knows about it
    run_command(["git", "fetch", "origin", args.base], check=False)
    
    # To find all files that diverged from base branch
    diff_files = run_command(["git", "diff", "--name-only", f"origin/{args.base}...{current_branch}"]).splitlines()
    
    if not diff_files:
        print("No differences found between branches.")
        sys.exit(0)

    summary_text = get_sql_diff_summary(args.base, diff_files)
    
    pr_body = (
        "## SQL Schema Updates Summary\n\n"
        "Automatically generated comparison of SQL definitions (from previously deployed branch to the new changes).\n\n"
        + (summary_text if summary_text else "No structural SQL changes detected.")
        + "\n\n_Do you approve these changes to the schema/views?_"
    )
    
    # 6. Create PR using GitHub CLI (`gh`)
    print("\n--- 🚀 Raising Pull Request ---")
    
    # We use absolute path to gh to avoid path cache issues on Windows
    gh_cmd = "C:/Program Files/GitHub CLI/gh.exe" if os.path.exists("C:/Program Files/GitHub CLI/gh.exe") else "gh"
    
    # Check if gh cli exists
    gh_check = subprocess.run([gh_cmd, "--version"], capture_output=True)
    if gh_check.returncode != 0:
        print("❌ GitHub CLI (`gh`) is not installed or not in PATH. Cannot automatically raise PR.")
        sys.exit(1)
        
    # Check if a PR already exists
    existing_pr = subprocess.run([gh_cmd, "pr", "view"], capture_output=True)
    if existing_pr.returncode == 0:
        print("A PR already exists for this branch. Updating the description instead.")
        with open("pr_body.txt", 'w', encoding='utf-8') as f:
            f.write(pr_body)
        run_command([gh_cmd, "pr", "edit", "--body-file", "pr_body.txt"])
        os.remove("pr_body.txt")
        print("✅ PR Updated!")
    else:
        # Create new
        with open("pr_body.txt", 'w', encoding='utf-8') as f:
            f.write(pr_body)
        gh_pr_cmd = [gh_cmd, "pr", "create", "--base", args.base, "--title", args.title, "--body-file", "pr_body.txt"]
        run_command(gh_pr_cmd)
        os.remove("pr_body.txt")
        print("✅ Pull Request successfully created!")

if __name__ == "__main__":
    main()
