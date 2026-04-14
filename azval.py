#!/usr/bin/env python3
import os
import sys
import base64
import json
import argparse
import subprocess
import re
import urllib.request
import urllib.error

# ANSI Color Codes for terminal output
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

def get_git_info():
    """Extracts org, project, and branch from git"""
    info = {"org": None, "project": None, "branch": "main"}
    try:
        # Branch
        info["branch"] = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
                                               stderr=subprocess.DEVNULL).decode().strip()
        
        # Remote URL (to get Org and Project)
        url = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], 
                                    stderr=subprocess.DEVNULL).decode().strip()
        
        # Regex for AzDO URLs (HTTPS and SSH)
        # Matches: dev.azure.com/org/project  OR  ssh.dev.azure.com:v3/org/project
        match = re.search(r"dev\.azure\.com[:/](?:v3/)?([^/]+)/([^/]+)", url)
        if match:
            info["org"] = match.group(1)
            info["project"] = match.group(2)
    except:
        pass
    return info

def check_remote_branch(branch):
    """Checks if the branch exists on the remote 'origin'"""
    try:
        subprocess.check_output(['git', 'ls-remote', '--exit-code', 'origin', f'refs/heads/{branch}'], 
                                stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def get_default_remote_branch():
    """Tries to find the default branch on origin"""
    for b in ["main", "master", "develop"]:
        if check_remote_branch(b):
            return b
    return "main"

def parse_params(params_list):
    params = {}
    if not params_list:
        return params
    for p in params_list:
        if '=' in p:
            k, v = p.split('=', 1)
            params[k] = v
    return params

def call_ado_api(org, project, endpoint, method="GET", body=None, pat=None):
    url = f"https://dev.azure.com/{org}/{project}/_apis/{endpoint}"
    url += "?api-version=7.1-preview.1"

    auth = base64.b64encode(f":{pat}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    if body:
        req.data = json.dumps(body).encode()

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode()), response.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode()), e.code
        except:
            return {"message": str(e)}, e.code
    except Exception as e:
        return {"message": str(e)}, 500

def highlight_error(file_path, message):
    match = re.search(r"\(Line:\s*(\d+),\s*Col:\s*(\d+)\)", message)
    if not match or not os.path.exists(file_path):
        return

    line_num = int(match.group(1))
    col_num = int(match.group(2))

    with open(file_path, 'r') as f:
        lines = f.readlines()

    if 1 <= line_num <= len(lines):
        start = max(0, line_num - 3)
        end = min(len(lines), line_num + 2)
        
        print(f"\n{BOLD}Context from {file_path}:{RESET}")
        for i in range(start, end):
            curr_line = i + 1
            content = lines[i].rstrip()
            if curr_line == line_num:
                print(f"{RED}{curr_line:4} | {content}{RESET}")
                padding = " " * (col_num + 6)
                print(f"{RED}{padding}^{RESET}")
            else:
                print(f"{curr_line:4} | {content}")
        print()

def validate_pipeline(args, pat, pipeline_id=None, yaml_content=None):
    if not pipeline_id:
        res, status = call_ado_api(args.org, args.project, "pipelines", pat=pat)
        if status == 200 and res.get("value"):
            # Try to find a pipeline that matches the file name or repo name
            pipelines = res["value"]
            # Default to the first one
            pipeline_id = pipelines[0]["id"]
            name = pipelines[0]["name"]
            
            # Better heuristic: match pipeline name to current project/folder
            for p in pipelines:
                if args.project.lower() in p["name"].lower():
                    pipeline_id = p["id"]
                    name = p["name"]
                    break
            
            print(f"Using pipeline '{name}' (ID: {pipeline_id}) as context.")
        else:
            print(f"{RED}Error: Could not find any pipelines in project '{args.project}' to use as context.{RESET}")
            return False

    context_branch = args.branch
    if not check_remote_branch(context_branch):
        fallback = get_default_remote_branch()
        print(f"{YELLOW}Branch '{context_branch}' not found on remote. Falling back to '{fallback}' for context.{RESET}")
        context_branch = fallback

    endpoint = f"pipelines/{pipeline_id}/runs"
    body = {
        "previewRun": True,
        "templateParameters": parse_params(args.param),
        "resources": {
            "repositories": {
                "self": {
                    "refName": f"refs/heads/{context_branch}"
                }
            }
        }
    }

    if yaml_content:
        body["yamlOverride"] = yaml_content

    print(f"Validating... ", end="", flush=True)
    res, status = call_ado_api(args.org, args.project, endpoint, method="POST", body=body, pat=pat)
    
    if status in [200, 201]:
        print(f"{GREEN}PASSED{RESET}")
        return True
    else:
        print(f"{RED}FAILED{RESET}")
        msg = res.get("message", "Unknown error")
        print(f"{BOLD}Error:{RESET} {msg}")
        if yaml_content and args.file:
            highlight_error(args.file, msg)
        return False

def main():
    git_info = get_git_info()
    
    parser = argparse.ArgumentParser(description="azval: Azure DevOps YAML Validator")
    parser.add_argument("--org", default=git_info["org"] or "EACustomerManagement", help="ADO Organization")
    parser.add_argument("--project", default=git_info["project"], help="ADO Project")
    parser.add_argument("--id", help="Pipeline ID to validate against")
    parser.add_argument("--file", help="Local YAML file to validate")
    parser.add_argument("--branch", default=git_info["branch"], help="Git branch (default: current)")
    parser.add_argument("--param", action="append", help="Runtime parameters (e.g. --param name=value)")
    
    args = parser.parse_args()
    
    if not args.project:
        print(f"{RED}Error: Could not detect AzDO project from git remote. Please provide --project.{RESET}")
        sys.exit(1)

    if not args.file and os.path.exists("azure-pipelines.yml"):
        args.file = "azure-pipelines.yml"

    pat = os.getenv("ADO_PAT") or os.getenv("ADO_TOKEN")
    if not pat:
        print(f"{RED}Error: ADO_PAT or ADO_TOKEN environment variable is not set.{RESET}")
        sys.exit(1)

    print(f"{BOLD}--- azval v1.2 ---{RESET}")
    print(f"Org:      {args.org}")
    print(f"Project:  {args.project}")
    print(f"Branch:   {args.branch}")
    if args.file:
        print(f"File:     {args.file}")
    print("-" * 18)

    yaml_content = None
    if args.file:
        if not os.path.exists(args.file):
            print(f"{RED}Error: File '{args.file}' not found.{RESET}")
            sys.exit(1)
        with open(args.file, 'r') as f:
            yaml_content = f.read()

    success = validate_pipeline(args, pat, pipeline_id=args.id, yaml_content=yaml_content)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
