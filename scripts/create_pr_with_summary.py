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

def get_git_file_content(branch: str, file_path: str) -> str:
    """Gets the content of a file from a specific git branch. If it fails, assumes file is new/empty."""
    try:
        # Use git show to get the file at the target branch
        # format: branch:filepath
        cmd = ["git", "show", f"{branch}:{file_path}"]
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

def get_sql_diff_summary(base_branch: str, changed_files: List[str]) -> str:
    """Generates a human-readable summary of what changed in the SQL files."""
    summary_lines = []
    
    for file_path in changed_files:
        if not file_path.endswith('.sql'):
            continue
            
        old_content = get_git_file_content(base_branch, file_path)
        new_content = get_local_file_content(file_path)
        
        # Split into lines
        old_lines = [l.strip() for l in old_content.splitlines() if l.strip()]
        new_lines = [l.strip() for l in new_content.splitlines() if l.strip()]
        
        # We use difflib to find what lines specifically changed
        # Since SQL typically has commas, types, etc, we'll try to present the added/removed lines
        diff = list(difflib.ndiff(old_lines, new_lines))
        
        added = [l[2:] for l in diff if l.startswith('+ ')]
        removed = [l[2:] for l in diff if l.startswith('- ')]
        
        if not added and not removed:
            continue
            
        summary_lines.append(f"### 📄 `{file_path}`")
        if not old_content and new_content:
            summary_lines.append("✨ **New File Created**")
            # If it's short, list elements
            summary_lines.append(f"- Contains {len(new_lines)} lines of SQL/DDL definition.")
        else:
            if added:
                summary_lines.append("**🟢 Added/Modified Lines (e.g. Columns, Types):**")
                for item in added:
                    # Strip trailing commas for cleaner view
                    clean_item = item.rstrip(',')
                    summary_lines.append(f"- `{clean_item}`")
            if removed:
                summary_lines.append("**🔴 Removed/Old Lines:**")
                for item in removed:
                    clean_item = item.rstrip(',')
                    summary_lines.append(f"- `{clean_item}`")
        summary_lines.append("")
        
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
    # To find all files that diverged from base branch
    diff_files = run_command(["git", "diff", "--name-only", f"{args.base}...{current_branch}"]).splitlines()
    
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
