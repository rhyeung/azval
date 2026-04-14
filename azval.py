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
from datetime import datetime

# ANSI Color Codes
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

def get_git_info():
    info = {"org": None, "project": None, "branch": "main"}
    try:
        info["branch"] = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
                                               stderr=subprocess.DEVNULL).decode().strip()
        url = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], 
                                    stderr=subprocess.DEVNULL).decode().strip()
        match = re.search(r"dev\.azure\.com[:/](?:v3/)?([^/]+)/([^/]+)", url)
        if match:
            info["org"] = match.group(1)
            info["project"] = match.group(2)
    except: pass
    return info

def check_remote_branch(branch):
    try:
        subprocess.check_output(['git', 'ls-remote', '--exit-code', 'origin', f'refs/heads/{branch}'], 
                                stderr=subprocess.DEVNULL)
        return True
    except: return False

def get_default_remote_branch():
    for b in ["main", "master", "develop"]:
        if check_remote_branch(b): return b
    return "main"

def call_ado_api(org, project, endpoint, method="GET", body=None, pat=None):
    prefix = f"{org}/{project}/" if project else f"{org}/"
    url = f"https://dev.azure.com/{prefix}_apis/{endpoint}"
    if "api-version=" not in endpoint:
        connector = "&" if "?" in endpoint else "?"
        url += f"{connector}api-version=7.1-preview.1"
    auth = base64.b64encode(f":{pat}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}", "Content-Type": "application/json",
        "vsts-pipeline-diagnostics": "true", "X-TFS-FedAuthRedirect": "Suppress"
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    if body: req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode()), response.status
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode()), e.code
        except: return {"message": str(e)}, e.code
    except Exception as e: return {"message": str(e)}, 500

def highlight_error(file_path, message):
    match = re.search(r"\(Line:\s*(\d+),\s*Col:\s*(\d+)\)", message)
    if not match or not os.path.exists(file_path): return
    line_num, col_num = int(match.group(1)), int(match.group(2))
    with open(file_path, 'r') as f: lines = f.readlines()
    if 1 <= line_num <= len(lines):
        start, end = max(0, line_num - 3), min(len(lines), line_num + 2)
        print(f"\n{BOLD}Context from {file_path}:{RESET}")
        for i in range(start, end):
            curr_line, content = i + 1, lines[i].rstrip()
            if curr_line == line_num:
                print(f"{RED}{curr_line:4} | {content}{RESET}")
                print(f"{RED}{' ' * (col_num + 6)}^{RESET}")
            else: print(f"{curr_line:4} | {content}")
        print()

def get_timeline(args, pat, project_id, pipeline_id, run_id=None):
    if not run_id:
        res, status = call_ado_api(args.org, project_id, f"pipelines/{pipeline_id}/runs", pat=pat)
        if status == 200 and res.get("value"): run_id = res["value"][0]["id"]
        else: return
    res, status = call_ado_api(args.org, project_id, f"build/builds/{run_id}/timeline?api-version=7.1-preview.2", pat=pat)
    if status != 200 or "records" not in res: return
    tasks = []
    for r in res["records"]:
        if r.get("type") == "Task" and r.get("startTime") and r.get("finishTime"):
            try:
                start = datetime.fromisoformat(r["startTime"].replace("Z", "+00:00"))
                finish = datetime.fromisoformat(r["finishTime"].replace("Z", "+00:00"))
                tasks.append({"name": r["name"], "duration": (finish - start).total_seconds(), "result": r.get("result")})
            except: continue
    tasks.sort(key=lambda x: x["duration"], reverse=True)
    print(f"\n{BOLD}--- Timeline Analysis (Build ID: {run_id}) ---{RESET}")
    print(f"{BLUE}{'Task Name':<50} | {'Duration':<10} | {'Result'}{RESET}")
    print("-" * 75)
    for t in tasks[:10]:
        color = GREEN if t["result"] == "succeeded" else RED
        print(f"{t['name']:<50} | {t['duration']:>8.1f}s | {color}{t['result']}{RESET}")

def main():
    git_info = get_git_info()
    parser = argparse.ArgumentParser(description=f"{BOLD}azval: Advanced Azure DevOps YAML Validator (v1.7){RESET}", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--org", default=git_info["org"] or "EACustomerManagement")
    parser.add_argument("--project", default=git_info["project"])
    parser.add_argument("--id", type=int, help="Pipeline ID override")
    parser.add_argument("--file", help="Local YAML file")
    parser.add_argument("--branch", default=git_info["branch"])
    parser.add_argument("--param", action="append", help="k=v parameters")
    parser.add_argument("--expand", action="store_true", help="Show fully expanded YAML in terminal")
    parser.add_argument("--write", nargs="?", const=".expanded-pipeline.yml", help="Write expanded YAML to file (default: .expanded-pipeline.yml)")
    parser.add_argument("--timeline", action="store_true", help="Show bottleneck analysis")
    parser.add_argument("--run-id", type=int, help="Specific Run ID for timeline")
    
    args = parser.parse_args()
    if not args.project: print(f"{RED}Error: Project not detected.{RESET}"); sys.exit(1)
    pat = os.getenv("ADO_PAT") or os.getenv("ADO_TOKEN")
    if not pat: print(f"{RED}Error: ADO_PAT/TOKEN not set.{RESET}"); sys.exit(1)
    if not args.file and os.path.exists("azure-pipelines.yml"): args.file = "azure-pipelines.yml"

    print(f"{BOLD}--- azval v1.7 ---{RESET}")
    res, status = call_ado_api(args.org, None, f"projects/{args.project}", pat=pat)
    if status != 200: print(f"{RED}Error: Project '{args.project}' not found.{RESET}"); sys.exit(1)
    project_id = res["id"]
    res, status = call_ado_api(args.org, project_id, "pipelines", pat=pat)
    pipeline_id = args.id
    if not pipeline_id and status == 200:
        pipelines = res.get("value", [])
        pipeline_id = next((p["id"] for p in pipelines if args.project.lower() in p["name"].lower()), pipelines[0]["id"] if pipelines else None)
    if not pipeline_id: print(f"{RED}Error: No pipelines found.{RESET}"); sys.exit(1)

    print(f"Org: {args.org} | Proj: {args.project} ({project_id}) | Branch: {args.branch} | ID: {pipeline_id}")
    print("-" * 25)

    context_branch = args.branch
    if not check_remote_branch(context_branch):
        context_branch = get_default_remote_branch()
        print(f"{YELLOW}Branch fallback to '{context_branch}'{RESET}")

    params = {}
    if args.param:
        for p in args.param:
            if '=' in p: k, v = p.split('=', 1); params[k] = v
    body = { "templateParameters": params, "resources": {"repositories": {"self": {"refName": f"refs/heads/{context_branch}"}}} }
    if args.file and os.path.exists(args.file):
        with open(args.file, 'r') as f: body["yamlOverride"] = f.read()

    print(f"Validating (Preview API)... ", end="", flush=True)
    res, status = call_ado_api(args.org, project_id, f"pipelines/{pipeline_id}/preview", method="POST", body=body, pat=pat)
    
    success = False
    if status in [200, 201]:
        print(f"{GREEN}PASSED{RESET}")
        if args.expand and "finalYaml" in res:
            print(f"\n{BOLD}--- Fully Expanded YAML ---{RESET}\n{res['finalYaml']}\n{'-' * 25}")
        if args.write and "finalYaml" in res:
            with open(args.write, 'w') as f: f.write(res["finalYaml"])
            print(f"{BLUE}Expanded YAML written to: {args.write}{RESET}")
        success = True
    else:
        print(f"{RED}FAILED{RESET}")
        msg = res.get("message", "Unknown error")
        print(f"{BOLD}Error:{RESET} {msg}")
        if args.file: highlight_error(args.file, msg)

    if args.timeline: get_timeline(args, pat, project_id, pipeline_id, run_id=args.run_id)
    sys.exit(0 if success else 1)

if __name__ == "__main__": main()
