#!/usr/bin/env python3
import os
import sys
import base64
import json
import argparse
import subprocess
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ANSI Color Codes
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
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
    safe_org = urllib.parse.quote(org)
    safe_project = urllib.parse.quote(project) if project else ""
    prefix = f"{safe_org}/{safe_project}/" if safe_project else f"{safe_org}/"
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
    if body: req.data = json.dumps(body).encode('utf-8')
    try:
        with urllib.request.urlopen(req) as response:
            content = response.read().decode('utf-8', errors='ignore')
            return json.loads(content), response.status
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

def calculate_duration(start_str, finish_str):
    if not start_str or not finish_str: return 0.0
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finish_str.replace("Z", "+00:00"))
        return (finish - start).total_seconds()
    except: return 0.0

def strip_ansi(text):
    return re.sub(r'\033\[[0-9;]*m', '', text).replace('\ufe0f', '')

def get_visible_width(text):
    stripped = strip_ansi(text)
    emoji_count = len(re.findall(r'[🎭📂⚙🔹]', stripped))
    return len(stripped) + emoji_count

def print_timeline_tree(node, nodes_by_parent, prefix="", is_last=True, is_root=False):
    dur = calculate_duration(node.get("startTime"), node.get("finishTime"))
    if node["type"] in ["Checkpoint"]: return
    result = node.get("result", "unknown")
    res_color = GREEN if result == "succeeded" else RED if result == "failed" else YELLOW
    icons = {"Stage": "🎭", "Phase": "📂", "Job": "⚙️", "Task": "🔹"}
    icon = icons.get(node["type"], "▪️")
    name = node["name"]
    if node["type"] == "Job" and node.get("workerName"):
        name = f"{name} ({node['workerName']})"
    tree_marker = "" if is_root else ("└── " if is_last else "├── ")
    display_text = f"{prefix}{tree_marker}{icon} {name}"
    visible_len = get_visible_width(display_text)
    limit = 80
    if visible_len > limit:
        display_text = display_text[:(len(display_text) - (visible_len - limit) - 3)] + "..."
        visible_len = limit
    padding = " " * (limit - visible_len)
    print(f"{display_text}{padding} | {dur:>8.1f}s | {res_color}{result}{RESET}")
    new_prefix = prefix if is_root else (prefix + ("    " if is_last else "│   "))
    children = nodes_by_parent.get(node["id"], [])
    children.sort(key=lambda x: x.get("order", 0))
    visible_children = [c for c in children if c["type"] not in ["Checkpoint"]]
    for i, child in enumerate(visible_children):
        print_timeline_tree(child, nodes_by_parent, new_prefix, i == len(visible_children) - 1)

def get_timeline(args, pat, project_id, pipeline_id, run_id=None):
    if not run_id:
        res, status = call_ado_api(args.org, project_id, f"pipelines/{pipeline_id}/runs", pat=pat)
        if status == 200 and res.get("value"): run_id = res["value"][0]["id"]
        else: return
    print(f"Fetching Timeline for Build ID: {run_id}...", end="", flush=True)
    res, status = call_ado_api(args.org, project_id, f"build/builds/{run_id}/timeline?api-version=7.1-preview.2", pat=pat)
    if status != 200 or "records" not in res:
        print(f" {RED}FAILED{RESET}"); return
    print(f" {GREEN}OK{RESET}")
    records = res["records"]
    nodes_by_parent = {}
    roots = []
    for r in records:
        pid = r.get("parentId")
        if not pid: roots.append(r)
        else:
            if pid not in nodes_by_parent: nodes_by_parent[pid] = []
            nodes_by_parent[pid].append(r)
    print(f"\n{BOLD}--- Hierarchical Timeline (Build ID: {run_id}) ---{RESET}")
    print(f"{BLUE}{'Name':<80} | {'Duration':<10} | {'Result'}{RESET}")
    print("-" * 105)
    roots.sort(key=lambda x: x.get("order", 0))
    for i, root in enumerate(roots):
        print_timeline_tree(root, nodes_by_parent, is_root=True)

def list_pipelines(args, pat, project_id):
    res, status = call_ado_api(args.org, project_id, "pipelines", pat=pat)
    if status != 200: return
    pipelines = res.get("value", [])
    print(f"\n{BOLD}--- Available Pipelines ---{RESET}")
    print(f"{BLUE}{'ID':<10} | {'Pipeline Name'}{RESET}")
    print("-" * 40)
    for p in sorted(pipelines, key=lambda x: x["name"]):
        print(f"{YELLOW}{p['id']:<10}{RESET} | {p['name']}")

def main():
    git_info = get_git_info()
    parser = argparse.ArgumentParser(description=f"{BOLD}azval: Advanced Azure DevOps YAML Validator {RESET}", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--org", default=git_info["org"] or "YOUR_ORG_NAME")
    parser.add_argument("--project", default=git_info["project"])
    parser.add_argument("--id", type=int, help="Pipeline ID override")
    parser.add_argument("--file", help="Local YAML file")
    parser.add_argument("--branch", default=git_info["branch"])
    parser.add_argument("--param", action="append", help="k=v parameters")
    parser.add_argument("--expand", action="store_true", help="Show fully expanded YAML in terminal")
    parser.add_argument("--write", nargs="?", const=".expanded-pipeline.yml", help="Write expanded YAML to file (default: .expanded-pipeline.yml)")
    parser.add_argument("--timeline", action="store_true", help="Show bottleneck analysis")
    parser.add_argument("--run-id", type=int, help="Specific Run ID for timeline")
    parser.add_argument("--list", action="store_true", help="List all pipelines in the project")
    
    args = parser.parse_args()
    if not args.project: print(f"{RED}Error: Project not detected.{RESET}"); sys.exit(1)
    pat = os.getenv("ADO_PAT") or os.getenv("ADO_TOKEN")
    if not pat: print(f"{RED}Error: ADO_PAT/TOKEN not set.{RESET}"); sys.exit(1)
    if not args.file and os.path.exists("azure-pipelines.yml"): args.file = "azure-pipelines.yml"

    print(f"{BOLD}--- azval ---{RESET}")
    res, status = call_ado_api(args.org, None, f"projects/{args.project}", pat=pat)
    if status != 200: print(f"{RED}Error: Project '{args.project}' not found.{RESET}"); sys.exit(1)
    project_id = res["id"]

    if args.list:
        list_pipelines(args, pat, project_id)
        sys.exit(0)

    res, status = call_ado_api(args.org, project_id, "pipelines", pat=pat)
    pipeline_id = args.id
    if not pipeline_id and status == 200:
        pipelines = res.get("value", [])
        pipeline_id = next((p["id"] for p in pipelines if args.project.lower() in p["name"].lower()), pipelines[0]["id"] if pipelines else None)
    if not pipeline_id: print(f"{RED}Error: No pipelines found.{RESET}"); sys.exit(1)

    if not args.timeline:
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
    sys.exit(0 if (args.timeline or success) else 1)

if __name__ == "__main__": main()
