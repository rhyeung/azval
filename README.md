# azval: Azure DevOps YAML Validator

A high-performance, zero-config tool to validate, expand, and analyze Azure DevOps YAML pipelines directly from your terminal.

## 🚀 Key Features

1.  **Zero-Config Detection:** Automatically extracts your Organization, Project, and Branch from your `git remote origin`.
2.  **The Flattener (`--write`):** Export the fully resolved YAML (post-template expansion) to a local file. Perfect for Neovim search and LSP validation.
3.  **Expanded YAML (`--expand`):** See the final result of your pipeline in the terminal after all templates and parameters are resolved.
4.  **Bottleneck Analysis (`--timeline`):** Identifies the Top 10 slowest tasks in your last run using the official `7.1-preview.2` Build Timeline API.
5.  **Rich Diagnostics:** Provides colorized context and a pointer `^` to the exact line/column where a validation error occurred.

## 🛠 Usage

### Setup
Ensure you have an Azure DevOps PAT exported:
```bash
export ADO_TOKEN="your-token-here"
```

### Examples

**Flatten your pipeline for Neovim:**
```bash
azval --write
# Opens .expanded-pipeline.yml in IDE
```

**Show fully expanded YAML with parameters:**
```bash
azval --expand --param service_type=ECS --param env=dev
```

**Find bottlenecks in the last pipeline run:**
```bash
azval --timeline
```

**Validate a specific file against a specific pipeline ID:**
```bash
azval --file build.yml --id 1234
```

## 🏗 Tips and Tricks
- **Pipelines Preview API:** Uses the specialized `/preview` endpoint for high-fidelity YAML expansion.
- **Project GUID Persistence:** Discovers the Project's unique ID (`99885995-...`) at startup to bypass naming mismatch issues.
- **Context Fallback:** If your local branch isn't pushed, `azval` automatically falls back to `master` to resolve remote templates.

## ⚠️ Important: The "First Push" Rule

While `azval` allows you to validate local logic without pushing, there is one technical limitation of the Azure DevOps API to keep in mind:

1.  **Main File is Local:** Your main pipeline file (the one passed to `--file`) is sent directly to the API. You can change this as much as you want without pushing.
2.  **Templates must exist on Remote:** Azure DevOps resolves `template:` calls by looking at the git repository in the cloud. 
    *   **New Files:** If you create a **brand new** template file or a new folder (like `.azdo/`), you must `git push` it to your branch at least once.
    *   **Iterating:** Once the file exists on the remote, you can change its content locally and use `azval` to validate it (provided the main pipeline file calls it).

**Rule of Thumb:** If the API says `File not found`, it means you haven't pushed that specific template file to the remote yet!
