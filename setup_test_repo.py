import os
import subprocess
import sys
import shutil

def run_command(cmd, cwd=None):
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}\nError: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

def main():
    repo_dir = "test_sql_repo"
    
    if os.path.exists(repo_dir):
        print(f"Removing existing {repo_dir} directory...")
        shutil.rmtree(repo_dir)
        
    os.makedirs(repo_dir)
    print("\n--- 1. Initializing Git Repository ---")
    run_command(["git", "init"], cwd=repo_dir)
    
    # Needs some config otherwise commit fails in some fresh environments
    run_command(["git", "config", "user.name", "Test User"], cwd=repo_dir)
    run_command(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    # create a dummy remote so pushing doesn't immediately yell (it will fail anyway unless you config gh)
    # But we will only simulate up to the push part.
    
    # Create the scripts folder inside the test repo
    os.makedirs(os.path.join(repo_dir, "scripts"))
    
    # Copy our python scripts there
    shutil.copy("scripts/check_sql_syntax.py", os.path.join(repo_dir, "scripts", "check_sql_syntax.py"))
    shutil.copy("scripts/create_pr_with_summary.py", os.path.join(repo_dir, "scripts", "create_pr_with_summary.py"))

    print("\n--- 2. Creating base employee_view in Main Branch ---")
    # Initial main branch commit
    sql_file = os.path.join(repo_dir, "employee_view.sql")
    old_sql_content = """CREATE VIEW employee_view AS
SELECT
    id,
    first_name,
    last_name,
    email
FROM employees;
"""
    with open(sql_file, 'w') as f:
        f.write(old_sql_content)
        
    run_command(["git", "add", "."], cwd=repo_dir)
    run_command(["git", "commit", "-m", "Initial commit on main"], cwd=repo_dir)
    # make branch main (some gits default to master)
    run_command(["git", "checkout", "-B", "main"], cwd=repo_dir)
    
    print("\n--- 3. Creating Feature Branch and making changes ---")
    run_command(["git", "checkout", "-b", "feature/add-employee-columns"], cwd=repo_dir)
    
    new_sql_content = """CREATE VIEW employee_view AS
SELECT
    id,
    first_name,
    last_name,
    email,
    department_id,
    hire_date
FROM employees;
"""
    with open(sql_file, 'w') as f:
        f.write(new_sql_content)
        
    print("\n--- 4. Modifying file and testing missing semicolon error ---")
    # Let's create another sql file with missing semicolon
    bad_sql_file = os.path.join(repo_dir, "bad_syntax.sql")
    bad_sql_content = """CREATE TABLE A (id INT)
CREATE VIEW B AS SELECT * FROM A;
"""
    with open(bad_sql_file, 'w') as f:
        f.write(bad_sql_content)
        
    print("\n--- 5. First try: should fail on bad syntax ---")
    result = subprocess.run([sys.executable, "scripts/create_pr_with_summary.py", "-t", "Add new columns"], cwd=repo_dir, capture_output=True, text=True)
    print(result.stdout)
    if "Syntax check failed" in result.stdout:
        print("✅ Correctly rejected the bad syntax!")
    else:
        print("❌ Did not reject bad syntax!")
        
    print("\n--- 6. Fixing syntax and running normally ---")
    os.remove(bad_sql_file) # fix by removing the bad file entirely
    
    # Since we can't push to a remote origin dynamically unless the user connects it to github, 
    # the script test stops at point of creating PR because PyGithub/gh needs a real remote.
    # We will just run the summary portion by calling check script.
    print(f"You can now cd into '{repo_dir}' and run:")
    print("python scripts/create_pr_with_summary.py -t 'My PR Title'")
    print("\nNote: Make sure your test_sql_repo is backed by a Github repository to see the PR creation action work.")
        
if __name__ == "__main__":
    main()
