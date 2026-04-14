# azval: Azure DevOps YAML Validator (v1.7)

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
# Opens .expanded-pipeline.yml in Neovim
nvim .expanded-pipeline.yml
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

## 🏗 Architecture (DevOps Pro Tips)
- **Pipelines Preview API:** Uses the specialized `/preview` endpoint for high-fidelity YAML expansion.
- **Project GUID Persistence:** Discovers the Project's unique ID (`99885995-...`) at startup to bypass naming mismatch issues.
- **Context Fallback:** If your local branch isn't pushed, `azval` automatically falls back to `master` to resolve remote templates.
