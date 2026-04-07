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

def generate_diff_summary(base_branch: str) -> str:
    diff_files = run_command(["git", "diff", "--name-only", f"origin/{base_branch}...HEAD"]).splitlines()
    summary_lines = []
    
    for file_path in diff_files:
        if not file_path.endswith('.sql'): continue
            
        old_content = get_git_file_content(base_branch, file_path)
        new_content = get_local_file_content(file_path)
        
        old_lines = [l.strip() for l in old_content.splitlines() if l.strip()]
        new_lines = [l.strip() for l in new_content.splitlines() if l.strip()]
        
        diff = list(difflib.ndiff(old_lines, new_lines))
        added = [l[2:] for l in diff if l.startswith('+ ')]
        removed = [l[2:] for l in diff if l.startswith('- ')]
        
        if not added and not removed: continue
            
        summary_lines.append(f"### 📄 `{file_path}`")
        if added:
            summary_lines.append("**🟢 Added/Modified Lines:**")
            for item in added: summary_lines.append(f"- `{item.rstrip(',')}`")
        if removed:
            summary_lines.append("**🔴 Removed/Old Lines:**")
            for item in removed: summary_lines.append(f"- `{item.rstrip(',')}`")
        summary_lines.append("")
        
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
