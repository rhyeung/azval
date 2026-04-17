# azval: Azure DevOps YAML Validator

A high-performance, zero-config tool to validate, expand, and analyze Azure DevOps YAML pipelines directly from your terminal.

## 🚀 Key Features

1.  **Zero-Config Detection:** Automatically extracts your Organization, Project, and Branch from your `git remote origin`.
2.  **Hierarchical Timeline (`--timeline`):** Rich, tree-style visualization of your pipeline performance (Stage ➔ Phase ➔ Job ➔ Step).
3.  **Discovery (`--list`):** Quickly list all pipelines and their IDs in your project.
4.  **The Flattener (`--write`):** Export fully resolved YAML (post-template expansion) to a local file.
5.  **Expanded YAML (`--expand`):** View the final result of your pipeline in the terminal after all templates and parameters are resolved.
6.  **Rich Diagnostics:** Provides colorized context and pointers to the exact line/column where a validation error occurred.

## 🛠 Usage

### Setup
Ensure you have an Azure DevOps PAT exported:
```bash
export ADO_TOKEN="your-token-here"
```

### Examples

**List all pipelines in the current project:**
```bash
azval --list
```

**Show hierarchical performance analysis for the last run:**
```bash
azval --timeline
```

**View performance for a specific Build ID:**
```bash
azval --timeline --run-id 12345
```

**Flatten your pipeline for local inspection:**
```bash
azval --write
# Opens .expanded-pipeline.yml in IDE
```

**Show expanded YAML with parameters:**
```bash
azval --expand --param service_type=ECS --param env=dev
```

## 🏗 Performance X-Ray
The `--timeline` feature provides a detailed tree view including:
- Stage, Phase, and Job durations.
- Parallel job slot/worker names.
- Individual task durations for bottleneck identification.
- Automatic duration summation for parent containers.

## ⚠️ Important: The "First Push" Rule

Azure DevOps uses a **Hybrid Validator**:
1.  **Main File is Local:** Your main pipeline file (passed to `--file`) is sent directly to the API. 
2.  **Templates must exist on Remote:** Azure DevOps resolves `template:` calls by looking at the git repository in the cloud. 
    *   **New Templates:** If you create a **brand new** template, you must `git push` it once so the server can "see" it.
    *   **Iterating:** Once the file exists remotely, you can change its content locally and validate it (as long as the main file calls it).

