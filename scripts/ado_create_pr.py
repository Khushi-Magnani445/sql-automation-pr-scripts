import os
import sys
import subprocess
import difflib
import json
import urllib.request
import urllib.error
from typing import List

def run_command(cmd: List[str], check=True) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}")
        if result.stderr: print(f"Error: {result.stderr.strip()}")
        sys.exit(result.returncode)
    return result.stdout.strip()

def get_git_file_content(base_branch: str, file_path: str) -> str:
    try:
        cmd = ["git", "show", f"origin/{base_branch}:{file_path}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0: return result.stdout
    except Exception: pass
    return ""

def get_local_file_content(file_path: str) -> str:
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f: return f.read()
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

def generate_diff_summary(base_branch: str) -> str:
    diff_files = run_command(["git", "diff", "--name-only", f"origin/{base_branch}...HEAD"]).splitlines()
    summary_lines = []
    
    for file_path in diff_files:
        if not file_path.endswith('.sql'): continue
            
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
        
        # Compare columns
        # To determine mapping changes, we can look at the base column name or alias
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
            summary_lines.append("\n**🟡 Modified Mappings/Logic:**")
            for c in modified_mappings: summary_lines.append(f"- {c}")
            
        if removed_cols:
            summary_lines.append("\n**🔴 Removed Columns:**")
            for c in removed_cols: summary_lines.append(f"- `{c}`")
            
        # Fallback to standard line diff if regex failed to extract anything meaningful
        if not old_cols and not new_cols:
            old_lines = [l.strip() for l in old_content.splitlines() if l.strip()]
            new_lines = [l.strip() for l in new_content.splitlines() if l.strip()]
            diff = list(difflib.ndiff(old_lines, new_lines))
            add = [l[2:] for l in diff if l.startswith('+ ')]
            rem = [l[2:] for l in diff if l.startswith('- ')]
            if add:
                summary_lines.append("**🟢 Added/Modified Lines:**")
                for item in add: summary_lines.append(f"- `{item.rstrip(',')}`")
            if rem:
                summary_lines.append("**🔴 Removed/Old Lines:**")
                for item in rem: summary_lines.append(f"- `{item.rstrip(',')}`")
                
        summary_lines.append("\n---")
        
    return "\n".join(summary_lines)

def create_ado_pr(base_branch: str, pr_title: str, pr_body: str):
    """Hits the Azure DevOps REST API to create a PR."""
    # ADO Pipelines automatically inject these environment variables
    ado_org_uri = os.environ.get("SYSTEM_TEAMFOUNDATIONCOLLECTIONURI")
    project_id = os.environ.get("SYSTEM_TEAMPROJECTID")
    repo_id = os.environ.get("BUILD_REPOSITORY_ID")
    source_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    
    ado_pat = os.environ.get("ADO_PAT")
    if not ado_pat or not ado_org_uri:
        print("❌ Missing ADO pipeline environment variables. Ensure ADO_PAT is mapped!")
        print("Fallback Summary Text:\n====================\n" + pr_body)
        sys.exit(0)

    url = f"{ado_org_uri}{project_id}/_apis/git/repositories/{repo_id}/pullrequests?api-version=7.0"
    
    payload = {
        "sourceRefName": f"refs/heads/{source_branch}",
        "targetRefName": f"refs/heads/{base_branch}",
        "title": pr_title,
        "description": pr_body
    }
    
    import base64
    b64_auth = base64.b64encode(f":{ado_pat}".encode("ascii")).decode("ascii")
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json"
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f"✅ Auto-Generated Azure DevOps Pull Request: {data['url']}")
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        if "TF401179" in err_msg or "already exists" in err_msg:
            print("✅ A PR for this branch already exists! (Summary logic can be updated via a PATCH request to edit it).")
        else:
            print(f"❌ Failed to create ADO PR: {e.code} - {err_msg}")
            sys.exit(1)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--base", default="master", help="Base branch")
    args = parser.parse_args()

    # We assume git status is fully committed by Snowflake and pushed to trigger the pipeline
    summary = generate_diff_summary(args.base)
    
    if not summary.strip():
        print("No structural changes detected. No PR update needed.")
        sys.exit(0)
        
    pr_body = "## SQL Schema Updates Summary\n\nAutomatically generated comparison of SQL definitions via ADO Pipeline.\n\n" + summary
    source_branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    pr_title = f"SQL Automation: Review changes from {source_branch}"
    
    create_ado_pr(args.base, pr_title, pr_body)

if __name__ == "__main__":
    main()
