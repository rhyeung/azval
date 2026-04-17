# azval: Azure DevOps YAML Validator & Performance Forensic Tool

A high-performance, zero-config tool to validate, expand, and analyze Azure DevOps YAML pipelines directly from your terminal.

## 🚀 Key Features

1.  **Zero-Config Detection:** Automatically extracts your Organization, Project, and Branch from your `git remote origin`.
2.  **Hierarchical Timeline (`-t`, `--timeline`):** Rich, tree-style visualization of pipeline performance (Stage ➔ Phase ➔ Job ➔ Step).
3.  **Run History (`-R`, `--runs`):** Quickly list the last 15 execution runs for your pipeline, including **Total Run Times**, Build Numbers, Results, and Commits.
4.  **Forensic Build Diff (`--diff`):** Compare two runs side-by-side to identify code changes, parameter shifts, and performance regressions.
5.  **Bottleneck Predictor (`-a`, `--analyze`):** Automatically identifies the slowest tasks and calculates **Agent Starvation** (Build Start Latency).
6.  **Failure Deep-Dive (`-E`, `--errors`):** Extracts error messages and log line numbers directly into the terminal for failed builds.
7.  **Deep Agent Scan (`-d`, `--deep-scan`):** Peeks into logs to extract unique **Worker IDs**, **Azure Regions**, and **Runner Images**.
8.  **Build Blame (`-B`, `--blame`):** Displays build metadata including the requesting user, trigger reason, and commit message.
9.  **Attempt History (`-H`, `--attempts`):** Compares multiple attempts (retries) for the same job to identify flaky infrastructure.
10. **The Flattener (`-w`, `--write`):** Export fully resolved YAML (post-template expansion) to a local file.

## 🛠 Usage

### Setup
Ensure you have an Azure DevOps PAT exported:
```bash
export ADO_TOKEN="your-token-here"
```

### Auto-Detection vs Manual Override
By default, `azval` looks at your current directory's Git metadata (`git remote get-url origin`) to determine which Organization and Project to target.

*   **If you are in a Git repo:** Simply run `azval -t`.
*   **If you are NOT in a repo (or detection fails):** Use the manual flags:
    ```bash
    azval -o YOUR_ORG -p YOUR_PROJECT -t
    ```

### Examples

**List the recent run history to find Build IDs and durations:**
```bash
azval -R
```

**Compare two builds for performance regressions:**
```bash
azval -r 1001 1002 --diff -a
```

**Perform a forensic deep-dive into a failed build:**
```bash
azval -t -r 1005 -B -E -d
```

**List all pipelines in a specific project:**
```bash
azval -o YOUR_ORG -p YOUR_PROJECT -l
```

**Validate local YAML with parameters and expand it:**
```bash
azval -e -v env=prod -v service=api
```

## 🏗 Performance & Diagnostics

### Bottleneck Analysis (`-a`)
Reports critical metrics to help optimize your CI/CD:
- **Build Start Latency:** Shows how long your build waited in the queue (Agent Starvation).
- **Top 3 Slowest Tasks:** Instantly highlights which steps are delaying your deployment.

### Deep Scan Metadata (`-d`)
When enabled, the tool performs additional API calls to resolve:
- **Worker ID:** The unique GUID of the specific runner instance (crucial for parallel jobs sharing the same machine name).
- **Azure Region:** The physical location of the runner.
- **Runner Image:** The specific OS image version used.

### Failure Deep-Dive (`-E`)
Aggregates errors from the build timeline so you don't have to scroll through logs:
- **Error Message:** The exact reason the task failed.
- **Log Line:** The specific line number in the console output to investigate.

## ⚠️ Important: The "First Push" Rule

Azure DevOps uses a **Hybrid Validator**:
1.  **Main File is Local:** Your main pipeline file (passed to `--file`) is sent directly to the API. 
2.  **Templates must exist on Remote:** Azure DevOps resolves `template:` calls by looking at the git repository in the cloud. 
    *   **New Templates:** If you create a **brand new** template, you must `git push` it once so the server can "see" it.
    *   **Iterating:** Once the file exists remotely, you can change its content locally and validate it (as long as the main file calls it).
