import sys
import re
import os

def check_sql_syntax(file_path):
    print(f"Checking syntax for: {file_path}")
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
        
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
        
    # Split the content by semicolons to evaluate statements
    # A single chunk between semicolons should not contain multiple
    # top-level DDL commands like CREATE, ALTER, DROP
    chunks = sql_content.split(';')
    
    # Regex to match top-level DDL objects
    ddl_pattern = re.compile(
        r'\b(CREATE|ALTER|DROP)\s+(OR\s+REPLACE\s+)?(VIEW|TABLE|PROCEDURE|FUNCTION|TRIGGER|DATABASE|SCHEMA)\b', 
        re.IGNORECASE
    )
    
    errors = []
    
    # We ignore comments with basic string replacement just for this validation
    # This is a naive way to remove single line comments
    content_no_comments = re.sub(r'--.*', '', sql_content)
    # Remove block comments
    content_no_comments = re.sub(r'/\*.*?\*/', '', content_no_comments, flags=re.DOTALL)
    
    chunks_no_comments = content_no_comments.split(';')
    
    for idx, chunk in enumerate(chunks_no_comments):
        # We only care if we see more than one match in a chunk without a semicolon
        matches = ddl_pattern.findall(chunk)
        if len(matches) > 1:
            # Reconstruct what was found to report user-friendly error
            found_statements = [f"{m[0]} {m[-1]}" for m in matches]
            error_msg = (f"Missing semicolon between statements. "
                         f"Found multiple DDL statements without separation in one block: "
                         f"{', '.join(found_statements)}")
            errors.append(error_msg)
            
    if errors:
        print(f"\n[ERROR] Syntax discrepancies found in {file_path}:")
        for err in errors:
            print(f"  - {err}")
        return False
        
    print(f"[OK] Syntax check passed for {file_path}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_sql_syntax.py <file1.sql> <file2.sql> ...")
        sys.exit(1)
        
    # First argument is script name
    files_to_check = sys.argv[1:]
    
    all_passed = True
    for f_path in files_to_check:
        if f_path.endswith('.sql'):
            passed = check_sql_syntax(f_path)
            if not passed:
                all_passed = False
                
    if not all_passed:
        # Exit with error code to fail the CI/CD pipeline
        sys.exit(1)
    else:
        sys.exit(0)
