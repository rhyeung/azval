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
import webbrowser
import tempfile
import time
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
            try:
                return json.loads(content), response.status
            except json.JSONDecodeError:
                return content, response.status
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

def format_duration(seconds):
    if seconds <= 0: return "N/A"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m > 0 else f"{s}s"

def strip_ansi(text):
    return re.sub(r'\033\[[0-9;]*m', '', text).replace('\ufe0f', '')

def get_visible_width(text):
    stripped = strip_ansi(text)
    emoji_count = len(re.findall(r'[🎭📂⚙🔹▪️]', stripped))
    return len(stripped) + emoji_count

def get_agent_info(args, pat, project_id, run_id, log_id):
    if not log_id: return None
    res, status = call_ado_api(args.org, project_id, f"build/builds/{run_id}/logs/{log_id}?api-version=7.1", pat=pat)
    if status != 200: return None
    log_text = ""
    if isinstance(res, dict) and "value" in res: log_text = "\n".join(str(l) for l in res["value"])
    elif isinstance(res, list): log_text = "\n".join(str(l) for l in res)
    else: log_text = str(res)
    
    info = {}
    vm = re.search(r"Agent machine name:\s*['\"]([^'\"]+)['\"]", log_text)
    img = re.search(r"Image:\s*([^\s\n\r]+)", log_text)
    if vm: info["vm"] = vm.group(1)
    if img: info["img"] = img.group(1)
    wid = re.search(r"Worker ID:\s*\{?([a-f0-9-]+)\}?", log_text, re.IGNORECASE)
    if wid: info["wid"] = wid.group(1)[:8]
    reg = re.search(r"Azure Region:\s*([^\s\n\r]+)", log_text)
    if reg: info["region"] = reg.group(1)
    return info

def print_timeline_tree(node, nodes_by_parent, prefix="", is_last=True, is_root=False, agent_map=None):
    dur = calculate_duration(node.get("startTime"), node.get("finishTime"))
    if node["type"] in ["Checkpoint"]: return
    result = node.get("result", "unknown")
    res_color = GREEN if result == "succeeded" else RED if result == "failed" else YELLOW
    icons = {"Stage": "🎭", "Phase": "📂", "Job": "⚙️", "Task": "🔹"}
    icon = icons.get(node["type"], "▪️")
    name = node["name"]
    
    if node["type"] == "Job":
        worker = node.get("workerName", "")
        info = agent_map.get(node["id"]) if agent_map else None
        if info:
            parts = [worker]
            if "vm" in info: parts.append(info["vm"])
            if "wid" in info: parts.append(f"WID:{info['wid']}")
            if "img" in info: parts.append(info["img"])
            if "region" in info: parts.append(info["region"])
            name = f"{name} ({' | '.join(parts)})"
        elif worker:
            name = f"{name} ({worker})"

    tree_marker = "" if is_root else ("└── " if is_last else "├── ")
    display_text = f"{prefix}{tree_marker}{icon} {name}"
    visible_len = get_visible_width(display_text)
    limit = 110
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
        print_timeline_tree(child, nodes_by_parent, new_prefix, i == len(visible_children) - 1, agent_map=agent_map)

def get_full_build_data(args, pat, project_id, run_id):
    data = {"build": None, "timeline": None, "agent_map": {}}
    res, status = call_ado_api(args.org, project_id, f"build/builds/{run_id}?api-version=7.1", pat=pat)
    if status == 200: data["build"] = res
    else: return None

    res, status = call_ado_api(args.org, project_id, f"build/builds/{run_id}/timeline?api-version=7.1-preview.2", pat=pat)
    if status == 200 and "records" in res:
        data["timeline"] = res["records"]
        if args.deep_scan:
            for r in res["records"]:
                if r["name"] == "Initialize job":
                    log_id = r.get("log", {}).get("id")
                    if log_id:
                        info = get_agent_info(args, pat, project_id, run_id, log_id)
                        if info: data["agent_map"][r["parentId"]] = info
    return data

def print_blame_header(build):
    user = build.get("requestedFor", {}).get("displayName", "Unknown")
    reason = build.get("reason", "Unknown")
    branch = build.get("sourceBranch", "").replace("refs/heads/", "")
    commit = build.get("sourceVersion", "")[:8]
    
    print(f"\n{BOLD}{BLUE}--- Build Blame ---{RESET}")
    print(f"{BOLD}Requested By:{RESET} {CYAN}{user}{RESET}")
    print(f"{BOLD}Trigger Reason:{RESET} {YELLOW}{reason}{RESET}")
    print(f"{BOLD}Source:{RESET} {GREEN}{branch}{RESET} @ {YELLOW}{commit}{RESET}")
    print("-" * 25)

def perform_analysis(data):
    build, records = data["build"], data["timeline"]
    print(f"\n{BOLD}{CYAN}--- Bottleneck Analysis: Build {build['id']} ---{RESET}")
    
    queue_time = build.get("queueTime")
    start_time = build.get("startTime")
    if queue_time and start_time:
        latency = calculate_duration(queue_time, start_time)
        color = RED if latency > 30 else YELLOW if latency > 10 else GREEN
        print(f"{BOLD}Build Start Latency (Agent Starvation):{RESET} {color}{latency:.1f}s{RESET}")

    tasks = []
    for r in records:
        if r["type"] == "Task":
            dur = calculate_duration(r.get("startTime"), r.get("finishTime"))
            tasks.append((r["name"], dur))
    
    tasks.sort(key=lambda x: x[1], reverse=True)
    print(f"\n{BOLD}Top 3 Slowest Tasks:{RESET}")
    for i, (name, dur) in enumerate(tasks[:3]):
        print(f"  {i+1}. {name:<50} | {RED}{dur:>6.1f}s{RESET}")
    print("-" * 25)

def print_failure_details(records):
    failed_nodes = [r for r in records if r.get("result") == "failed" and r.get("issues")]
    if not failed_nodes: return

    print(f"\n{BOLD}{RED}--- Failure Deep-Dive ---{RESET}")
    for node in failed_nodes:
        print(f"\n{BOLD}[{node['type']}] {node['name']}{RESET}")
        for issue in node["issues"]:
            msg = issue.get("message", "No message")
            msg = re.sub(r'##\[error\]', '', msg)
            print(f"  {RED}✖{RESET} {msg}")
            if "logFileLineNumber" in issue.get("data", {}):
                print(f"    {YELLOW}Log Line:{RESET} {issue['data']['logFileLineNumber']}")
    print("-" * 25)

def print_attempt_history(records):
    retry_nodes = [r for r in records if r.get("attempt", 1) > 1 or r.get("previousAttempts")]
    if not retry_nodes: return

    print(f"\n{BOLD}{YELLOW}--- Attempt History (Retries) ---{RESET}")
    for node in retry_nodes:
        print(f"\n{BOLD}[{node['type']}] {node['name']}{RESET}")
        attempts = []
        curr_dur = calculate_duration(node.get("startTime"), node.get("finishTime"))
        attempts.append({"num": node.get("attempt", 1), "dur": curr_dur, "res": node.get("result")})
        for prev in node.get("previousAttempts", []):
            prev_dur = calculate_duration(prev.get("startTime"), prev.get("finishTime"))
            attempts.append({"num": prev.get("attempt"), "dur": prev_dur, "res": prev.get("result")})
        attempts.sort(key=lambda x: x["num"])
        for a in attempts:
            res_color = GREEN if a["res"] == "succeeded" else RED if a["res"] == "failed" else YELLOW
            print(f"  Attempt {a['num']}: {a['dur']:>6.1f}s | {res_color}{a['res']}{RESET}")
    print("-" * 25)

def perform_diff(data1, data2):
    b1, b2 = data1["build"], data2["build"]
    print(f"\n{BOLD}{MAGENTA}=== Forensic Build Diff: {b1['id']} vs {b2['id']} ==={RESET}")
    print(f"\n{BOLD}{BLUE}[1. Source Code]{RESET}")
    print(f"Build {b1['id']}: {CYAN}{b1['sourceBranch']}{RESET} @ {YELLOW}{b1['sourceVersion'][:8]}{RESET}")
    print(f"Build {b2['id']}: {CYAN}{b2['sourceBranch']}{RESET} @ {YELLOW}{b2['sourceVersion'][:8]}{RESET}")
    if b1['sourceVersion'] == b2['sourceVersion']:
        print(f"{GREEN}Identical commit.{RESET}")
    else:
        print(f"{RED}Code changed.{RESET}")

    print(f"\n{BOLD}{BLUE}[2. Parameters & Variables]{RESET}")
    p1 = json.loads(b1.get("parameters", "{}"))
    p2 = json.loads(b2.get("parameters", "{}"))
    all_params = sorted(set(p1.keys()) | set(p2.keys()))
    changes = False
    for p in all_params:
        v1, v2 = p1.get(p), p2.get(p)
        if v1 != v2:
            changes = True
            print(f"{YELLOW}{p:<20}{RESET} | {RED}{str(v1):<20}{RESET} -> {GREEN}{str(v2)}{RESET}")
    if not changes: print(f"{GREEN}No parameter changes detected.{RESET}")

    print(f"\n{BOLD}{BLUE}[3. Performance Regression (Duration)]{RESET}")
    t1 = {r["name"]: calculate_duration(r.get("startTime"), r.get("finishTime")) for r in data1["timeline"] if r["type"] in ["Stage", "Job", "Task"]}
    t2 = {r["name"]: calculate_duration(r.get("startTime"), r.get("finishTime")) for r in data2["timeline"] if r["type"] in ["Stage", "Job", "Task"]}
    print(f"{'Node Name':<60} | {'Build '+str(b1['id']):<15} | {'Build '+str(b2['id']):<15} | {'Delta'}")
    print("-" * 105)
    all_nodes = sorted(set(t1.keys()) | set(t2.keys()))
    for node in all_nodes:
        d1, d2 = t1.get(node, 0.0), t2.get(node, 0.0)
        delta = d2 - d1
        if abs(delta) > 1.0:
            color = RED if delta > 5.0 else YELLOW if delta > 2.0 else RESET
            delta_str = f"{'+' if delta > 0 else ''}{delta:.1f}s"
            print(f"{node:<60} | {d1:>14.1f}s | {d2:>14.1f}s | {color}{delta_str}{RESET}")

def generate_html_report(args, project_id, run_ids, pat):
    print(f"Generating task-grouped report for {len(run_ids)} runs... ", end="", flush=True)
    report_data = []
    task_start_times = {} # Track earliest start time per task name for sequencing
    
    for rid in sorted(run_ids):
        data = get_full_build_data(args, pat, project_id, rid)
        if not data: continue
        
        build = data["build"]
        records = data["timeline"]
        
        run_entry = {
            "id": rid,
            "total_duration": calculate_duration(build.get("startTime"), build.get("finishTime")),
            "result": build.get("result", "unknown"),
            "tasks": {},
            "task_results": {}
        }
        
        for r in records:
            if r["type"] == "Task":
                task_name = r["name"]
                start_time = r.get("startTime")
                duration = calculate_duration(start_time, r.get("finishTime"))
                run_entry["tasks"][task_name] = duration
                run_entry["task_results"][task_name] = r.get("result", "unknown")
                
                # Track the earliest time we've seen this task name start
                if start_time:
                    if task_name not in task_start_times or start_time < task_start_times[task_name]:
                        task_start_times[task_name] = start_time
        
        report_data.append(run_entry)
    
    # Sort task names chronologically based on their earliest recorded start time
    sorted_tasks = sorted(task_start_times.keys(), key=lambda x: task_start_times[x])
    
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>azval Performance Report</title>
    <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 40px; background-color: #f8f9fa; }
        .container { max-width: 1400px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; }
        .header-flex { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .info { color: #666; }
        .controls { display: flex; gap: 8px; }
        .btn { 
            background-color: #f1f3f5; color: #495057; border: 1px solid #dee2e6; padding: 8px 16px; 
            border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s;
        }
        .btn:hover { background-color: #e9ecef; }
        .btn.active { background-color: #007bff; color: white; border-color: #007bff; }
        .chart-container { min-height: 75vh; width: 100%; }
        .footer { margin-top: 20px; font-size: 12px; color: #999; text-align: center; }
        #chart { width: 100%; margin: 0 auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>azval Performance Report</h1>
        <div class="header-flex">
            <div class="info">Project: <b>{{PROJECT}}</b> | Runs Analyzed: <b>{{COUNT}}</b></div>
            <div class="controls">
                <button class="btn active" id="btn-heatmap" onclick="setView('heatmap')">Heatmap</button>
                <button class="btn" id="btn-stacked" onclick="setView('stacked')">Stacked Bar</button>
                <button class="btn" id="btn-grouped" onclick="setView('grouped')">Grouped Bar</button>
            </div>
        </div>
        <div class="chart-container">
            <div id="chart"></div>
        </div>
        <div class="footer">Generated by azval on {{DATE}}</div>
    </div>

    <script>
        const reportData = {{DATA}};
        const taskNames = {{TASK_NAMES}};
        let chart = null;
        let currentView = 'heatmap';

        const getTaskColor = (i) => `hsla(${(i * 360 / taskNames.length) % 360}, 70%, 50%, 0.8)`;
        const getRunColor = (i) => `hsla(${(i * 360 / reportData.length) % 360}, 70%, 50%, 0.8)`;

        function getHeatmapSeries() {
            // Heatmap: Rows = Tasks, Columns = Runs
            return taskNames.slice().reverse().map((taskName, i) => {
                return {
                    name: taskName,
                    data: reportData.map(run => ({
                        x: `Run ${run.id}`,
                        y: run.tasks[taskName] || 0,
                        result: run.task_results[taskName] || 'unknown'
                    }))
                };
            });
        }

        function getStackedSeries() {
            return taskNames.map((taskName, i) => {
                return {
                    name: taskName,
                    data: reportData.map((run, idx) => ({
                        x: idx,
                        y: run.tasks[taskName] || 0,
                        result: run.task_results[taskName] || 'unknown'
                    }))
                };
            });
        }

        function getGroupedSeries() {
            return reportData.map((run, i) => {
                return {
                    name: `Run ${run.id}`,
                    data: taskNames.map((taskName, idx) => ({
                        x: idx,
                        y: run.tasks[taskName] || 0,
                        result: run.task_results[taskName] || 'unknown'
                    }))
                };
            });
        }

        function getChartOptions(viewType) {
            const isHeatmap = viewType === 'heatmap';
            const isStacked = viewType === 'stacked';
            const isGrouped = viewType === 'grouped';

            let series = [];
            if (isHeatmap) series = getHeatmapSeries();
            else if (isStacked) series = getStackedSeries();
            else series = getGroupedSeries();

            const taskCount = taskNames.length;
            const runCount = reportData.length;

            return {
                series: series,
                chart: {
                    type: isHeatmap ? 'heatmap' : 'bar',
                    height: '100%',
                    stacked: isStacked,
                    toolbar: { 
                        show: true,
                        autoSelected: 'zoom',
                        tools: {
                            download: true,
                            selection: true,
                            zoom: true,
                            zoomin: true,
                            zoomout: true,
                            pan: true,
                            reset: true
                        }
                    },
                    zoom: {
                        enabled: true,
                        type: 'x',
                        autoScaleYaxis: true
                    },
                    animations: { enabled: true, speed: 400 }
                },
                dataLabels: { enabled: false },
                stroke: { width: isHeatmap ? 1 : 0 },
                colors: isGrouped ? reportData.map((_, i) => getRunColor(i)) : taskNames.map((_, i) => getTaskColor(i)),
                plotOptions: {
                    heatmap: {
                        shadeIntensity: 0.5,
                        radius: 2,
                        useFillColorAsStroke: false,
                        colorScale: {
                            ranges: [
                                { from: -1, to: -1, color: '#333', name: 'failed' },
                                { from: 0, to: 10, color: '#00E396', name: 'low' },
                                { from: 10.1, to: 60, color: '#FEB019', name: 'medium' },
                                { from: 60.1, to: 10000, color: '#FF4560', name: 'high' }
                            ]
                        }
                    },
                    bar: {
                        horizontal: false,
                        columnWidth: '80%',
                    }
                },
                xaxis: {
                    type: isHeatmap ? 'category' : 'numeric',
                    title: { text: isGrouped ? 'Tasks (Chronological)' : (isHeatmap ? 'Pipeline Runs' : 'Pipeline Runs (Index)') },
                    labels: { 
                        rotate: -45, 
                        rotateAlways: true,
                        formatter: function(val) {
                            if (isHeatmap) return val;
                            if (val % 1 !== 0) return ''; // Only show labels for integer ticks
                            const idx = Math.round(val);
                            if (isGrouped) return taskNames[idx] || '';
                            const run = reportData[idx];
                            return run ? `Run ${run.id}` : '';
                        }
                    },
                    tickAmount: isHeatmap ? undefined : (isGrouped ? taskCount - 1 : runCount - 1)
                },
                yaxis: {
                    title: { text: isHeatmap ? 'Tasks' : 'Duration (seconds)' }
                },
                tooltip: {
                    shared: false,
                    intersect: true,
                    followCursor: true,
                    x: {
                        formatter: function(val) {
                            if (isHeatmap) return val;
                            const idx = Math.round(val);
                            if (isGrouped) return taskNames[idx] || '';
                            const run = reportData[idx];
                            return run ? `Run ${run.id}` : '';
                        }
                    },
                    y: {
                        formatter: function(val, { series, seriesIndex, dataPointIndex, w }) {
                            const point = w.config.series[seriesIndex].data[dataPointIndex];
                            let status = point.result === 'failed' ? ' ✖ (FAILED)' : '';
                            const displayVal = val === -1 ? 0 : val;
                            return displayVal.toFixed(1) + 's' + status;
                        }
                    }
                },
                legend: {
                    position: 'right',
                    offsetY: 40
                }
            };
        }

        // Apply "Black Hole" logic to bar charts by overriding individual data point colors
        function applyCustomColors(options, viewType) {
            if (viewType === 'heatmap') {
                // For heatmap, we use colorScale ranges. 
                // To force failed tasks to #333, we temporarily set their value to -1
                options.series.forEach(s => {
                    s.data.forEach(d => {
                        if (d.result === 'failed') d.y = -1;
                    });
                });
            } else {
                // For Bar charts, we can use distributed colors or item-level colors if supported, 
                // but ApexCharts is easiest with series-level colors. 
                // For the "black hole" effect, we'll use fill.colors callback.
                options.fill = {
                    colors: [function({ value, seriesIndex, dataPointIndex, w }) {
                        const point = w.config.series[seriesIndex].data[dataPointIndex];
                        if (point && point.result === 'failed') return '#333';
                        
                        if (viewType === 'grouped') return getRunColor(seriesIndex);
                        return getTaskColor(seriesIndex);
                    }]
                };
            }
            return options;
        }

        function setView(viewType) {
            currentView = viewType;
            
            // Update buttons
            document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            document.getElementById(`btn-${viewType}`).classList.add('active');

            const options = applyCustomColors(getChartOptions(viewType), viewType);
            
            if (chart) {
                chart.updateOptions(options, true);
            } else {
                chart = new ApexCharts(document.querySelector("#chart"), options);
                chart.render();
            }
        }

        // Initialize
        setView('heatmap');
    </script>
</body>
</html>
"""
    # Replace placeholders
    html = html_template.replace("{{PROJECT}}", args.project)
    html = html.replace("{{COUNT}}", str(len(report_data)))
    html = html.replace("{{DATE}}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    html = html.replace("{{DATA}}", json.dumps(report_data))
    html = html.replace("{{TASK_NAMES}}", json.dumps(sorted_tasks))
    
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html') as f:
        f.write(html)
        temp_path = f.name
    
    print(f"{GREEN}DONE{RESET}")
    print(f"Report saved to: {temp_path}")
    webbrowser.open('file://' + os.path.realpath(temp_path))

def list_pipelines(args, pat, project_id):
    print(f"{BOLD}Organization:{RESET} {CYAN}{args.org}{RESET}")
    print(f"{BOLD}Project:{RESET}      {YELLOW}{args.project}{RESET}")
    print("-" * 40)
    res, status = call_ado_api(args.org, project_id, "pipelines", pat=pat)
    if status != 200: return
    pipelines = res.get("value", [])
    print(f"\n{BOLD}--- Available Pipelines ---{RESET}")
    print(f"{BLUE}{'ID':<10} | {'Pipeline Name'}{RESET}")
    print("-" * 40)
    for p in sorted(pipelines, key=lambda x: x["name"]):
        print(f"{YELLOW}{p['id']:<10}{RESET} | {p['name']}")

def list_runs(args, pat, project_id, pipeline_id):
    print(f"{BOLD}Organization:{RESET} {CYAN}{args.org}{RESET}")
    print(f"{BOLD}Project:{RESET}      {YELLOW}{args.project}{RESET}")
    print("-" * 40)
    res, status = call_ado_api(args.org, project_id, f"build/builds?definitions={pipeline_id}&$top=15&queryOrder=queueTimeDescending&api-version=7.1&t={int(time.time())}", pat=pat)
    if status != 200: return
    builds = res.get("value", [])
    print(f"\n{BOLD}--- Recent Runs for Pipeline {pipeline_id} ---{RESET}")
    print(f"{BLUE}{'Run ID':<10} | {'Duration':<10} | {'Result':<12} | {'Branch':<25} | {'Commit'}{RESET}")
    print("-" * 95)
    for b in builds:
        rid = b['id']
        dur_raw = calculate_duration(b.get('startTime'), b.get('finishTime'))
        dur = format_duration(dur_raw)
        res = b.get('result', 'inProgress')
        res_color = GREEN if res == 'succeeded' else RED if res == 'failed' else YELLOW
        ref = b.get('sourceBranch', 'N/A').replace('refs/heads/', '')
        sha = b.get('sourceVersion', 'N/A')[:8]
        print(f"{YELLOW}{rid:<10}{RESET} | {dur:<10} | {res_color}{res:<12}{RESET} | {ref:<25} | {sha}")

def main():
    git_info = get_git_info()
    parser = argparse.ArgumentParser(description=f"{BOLD}azval: Advanced Azure DevOps YAML Validator {RESET}", formatter_class=argparse.RawTextHelpFormatter)
    
    # 1. Project Context Group
    ctx_group = parser.add_argument_group("Project Context")
    ctx_group.add_argument("-o", "--org", default=git_info["org"] or "YOUR_ORG_NAME", help="Azure DevOps Organization")
    ctx_group.add_argument("-p", "--project", default=git_info["project"], help="Azure DevOps Project")
    ctx_group.add_argument("-i", "--id", type=int, help="Pipeline ID override")
    ctx_group.add_argument("-b", "--branch", default=git_info["branch"], help="Branch name")

    # 2. Pipeline Validation Group
    val_group = parser.add_argument_group("Pipeline Validation")
    val_group.add_argument("-f", "--file", help="Local YAML file (default: azure-pipelines.yml)")
    val_group.add_argument("-v", "--param", action="append", help="k=v parameters for template expansion")
    val_group.add_argument("-e", "--expand", action="store_true", help="Show fully expanded YAML in terminal")
    val_group.add_argument("-w", "--write", nargs="?", const=".expanded-pipeline.yml", help="Write expanded YAML to file")

    # 3. Forensics & Analysis Group
    anal_group = parser.add_argument_group("Forensics & Analysis")
    anal_group.add_argument("-t", "--timeline", action="store_true", help="Show hierarchical performance timeline")
    anal_group.add_argument("-r", "--run-id", type=str, nargs="+", help="Run ID(s). Supports ranges (e.g. 3600..3650)")
    anal_group.add_argument("-d", "--deep-scan", action="store_true", help="Extract detailed agent metadata (Worker ID, Region)")
    anal_group.add_argument("-B", "--blame", action="store_true", help="Show build metadata (User, Reason, Commit)")
    anal_group.add_argument("-a", "--analyze", action="store_true", help="Identify slowest tasks and agent starvation")
    anal_group.add_argument("-E", "--errors", action="store_true", help="Show detailed failure messages and log lines")
    anal_group.add_argument("-H", "--attempts", action="store_true", help="Show comparison of job retries/attempts")
    anal_group.add_argument("--diff", action="store_true", help="Compare two run IDs side-by-side")
    
    # 4. Discovery Group
    disc_group = parser.add_argument_group("Discovery")
    disc_group.add_argument("-l", "--list", action="store_true", help="List all pipelines in the project")
    disc_group.add_argument("-R", "--runs", action="store_true", help="List recent run history for the pipeline")
    disc_group.add_argument("--report", action="store_true", help="Generate interactive HTML performance report")
    
    args = parser.parse_args()
    if not args.project: print(f"{RED}Error: Project not detected.{RESET}"); sys.exit(1)
    pat = os.getenv("ADO_PAT") or os.getenv("ADO_TOKEN")
    if not pat: print(f"{RED}Error: ADO_PAT/TOKEN not set.{RESET}"); sys.exit(1)

    # Resolve Run IDs (Support ranges and commas)
    resolved_run_ids = []
    if args.run_id:
        for rid in args.run_id:
            for part in rid.split(","):
                if not part: continue
                if ".." in part:
                    try:
                        start, end = map(int, part.split(".."))
                        resolved_run_ids.extend(range(start, end + 1))
                    except ValueError:
                        print(f"{RED}Error: Invalid range format '{part}'. Use START..END (e.g. 3600..3650){RESET}")
                        sys.exit(1)
                else:
                    try: resolved_run_ids.append(int(part))
                    except ValueError:
                        print(f"{RED}Error: Invalid Run ID '{part}'.{RESET}")
                        sys.exit(1)
    args.run_id = resolved_run_ids

    # Dependency Logic & Branch Fallback Fix
    if not args.timeline and not args.diff:
        context_branch = args.branch
        if args.branch == git_info["branch"] and not check_remote_branch(context_branch):
            context_branch = get_default_remote_branch()
            print(f"{YELLOW}Branch fallback to '{context_branch}'{RESET}")
    else:
        context_branch = args.branch

    forensic_flags = [args.analyze, args.blame, args.deep_scan, args.errors, args.attempts]
    if any(forensic_flags) and not (args.timeline or args.diff):
        if args.run_id: args.timeline = True
        else: print(f"{RED}Error: Analysis flags require -t/--timeline or --diff.{RESET}"); sys.exit(1)
    if args.run_id and not (args.timeline or args.diff):
        args.timeline = True
    if args.list and (args.timeline or args.diff or args.expand or args.write or args.runs):
        print(f"{RED}Error: --list (-l) is mutually exclusive with other modes.{RESET}"); sys.exit(1)

    print(f"{BOLD}--- azval ---{RESET}")
    res, status = call_ado_api(args.org, None, f"projects/{args.project}", pat=pat)
    if status != 200: print(f"{RED}Error: Project '{args.project}' not found.{RESET}"); sys.exit(1)
    project_id = res["id"]

    if args.list:
        list_pipelines(args, pat, project_id)
        sys.exit(0)

    # Resolve Pipeline ID
    res, status = call_ado_api(args.org, project_id, "pipelines", pat=pat)
    pipeline_id = args.id
    if not pipeline_id and status == 200:
        pipelines = res.get("value", [])
        pipeline_id = next((p["id"] for p in pipelines if args.project.lower() in p["name"].lower()), pipelines[0]["id"] if pipelines else None)
    if not pipeline_id: print(f"{RED}Error: No pipelines found.{RESET}"); sys.exit(1)

    if args.report:
        if not args.run_id:
            # Fetch recent runs if no specific IDs or ranges provided
            res, status = call_ado_api(args.org, project_id, f"build/builds?definitions={pipeline_id}&$top=30&queryOrder=queueTimeDescending&api-version=7.1", pat=pat)
            if status == 200:
                args.run_id = [b["id"] for b in res.get("value", [])]
        
        if not args.run_id:
            print(f"{RED}Error: No runs found for report.{RESET}")
            sys.exit(1)
            
        generate_html_report(args, project_id, args.run_id, pat)
        sys.exit(0)

    if args.runs:
        list_runs(args, pat, project_id, pipeline_id)
        sys.exit(0)

    if args.diff:
        if not args.run_id or len(args.run_id) < 2:
            print(f"{RED}Error: --diff requires two IDs.{RESET}")
            sys.exit(1)
        data1 = get_full_build_data(args, pat, project_id, args.run_id[0])
        data2 = get_full_build_data(args, pat, project_id, args.run_id[1])
        if data1 and data2:
            if args.blame:
                print(f"\n{BOLD}[Build 1 Context]{RESET}")
                print_blame_header(data1["build"])
                print(f"\n{BOLD}[Build 2 Context]{RESET}")
                print_blame_header(data2["build"])
            if args.analyze: perform_analysis(data1); perform_analysis(data2)
            if args.errors: print_failure_details(data1["timeline"]); print_failure_details(data2["timeline"])
            if args.attempts: print_attempt_history(data1["timeline"]); print_attempt_history(data2["timeline"])
            perform_diff(data1, data2)
        else: print(f"{RED}Error: Could not fetch data.{RESET}")
        sys.exit(0)

    if args.timeline:
        run_id = args.run_id[0] if args.run_id else None
        data = get_full_build_data(args, pat, project_id, run_id)
        if not data: print(f"{RED}Error: Could not fetch build data.{RESET}"); sys.exit(1)
        build, records, agent_map = data["build"], data["timeline"], data["agent_map"]
        if args.blame: print_blame_header(build)
        if args.analyze: perform_analysis(data)
        if args.errors: print_failure_details(records)
        if args.attempts: print_attempt_history(records)
        pool_name = build.get("queue", {}).get("name", "Unknown")
        print(f"Timeline for Build ID: {build['id']} (Pool: {pool_name})")
        nodes_by_parent = {}
        roots = []
        for r in records:
            pid = r.get("parentId")
            if not pid: roots.append(r)
            else:
                if pid not in nodes_by_parent: nodes_by_parent[pid] = []
                nodes_by_parent[pid].append(r)
        print(f"\n{BOLD}--- Hierarchical Timeline (Build ID: {build['id']}) ---{RESET}")
        print(f"{BLUE}{'Name':<110} | {'Duration':<10} | {'Result'}{RESET}")
        print("-" * 135)
        roots.sort(key=lambda x: x.get("order", 0))
        for i, root in enumerate(roots):
            print_timeline_tree(root, nodes_by_parent, is_root=True, agent_map=agent_map)
        sys.exit(0)

    print(f"Org: {args.org} | Proj: {args.project} | Branch: {args.branch} | ID: {pipeline_id}")
    print("-" * 25)
    params = {}
    if args.param:
        for p in args.param:
            if '=' in p: k, v = p.split('=', 1); params[k] = v
    body = { "templateParameters": params, "resources": {"repositories": {"self": {"refName": f"refs/heads/{context_branch}"}}} }
    if args.file and os.path.exists(args.file):
        with open(args.file, 'r') as f: body["yamlOverride"] = f.read()
    print(f"Validating (Preview API)... ", end="", flush=True)
    res, status = call_ado_api(args.org, project_id, f"pipelines/{pipeline_id}/preview", method="POST", body=body, pat=pat)
    if status in [200, 201]:
        print(f"{GREEN}PASSED{RESET}")
        if args.expand and "finalYaml" in res:
            print(f"\n{BOLD}--- Fully Expanded YAML ---{RESET}\n{res['finalYaml']}\n{'-' * 25}")
        if args.write and "finalYaml" in res:
            with open(args.write, 'w') as f: f.write(res["finalYaml"])
            print(f"{BLUE}Expanded YAML written to: {args.write}{RESET}")
    else:
        print(f"{RED}FAILED{RESET}")
        msg = res.get("message", "Unknown error")
        print(f"{BOLD}Error:{RESET} {msg}")
        if any(kw in msg for kw in ["not found in repository", "Unexpected parameter", "Unable to resolve the reference"]):
            print(f"\n{BOLD}{CYAN}💡 [First Push Rule]:{RESET} This error likely occurred because your local changes haven't been pushed to the remote repository yet. ADO resolves templates and references from the cloud, not your local disk.")
        if args.file: highlight_error(args.file, msg)

if __name__ == "__main__": main()
