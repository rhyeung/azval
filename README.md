# azval: Azure DevOps YAML Validator

A lightweight, zero-dependency Python script to validate Azure DevOps YAML pipelines via the REST API (v7.1-preview).

## Features

1.  **Local Validation:** Validates your local `azure-pipelines.yml` (using `yamlOverride`) before you commit or push.
2.  **Rich Diagnostics:** If validation fails, it extracts the line and column number from the error message and prints the context from your local file.
3.  **Runtime Parameters:** Supports passing parameters via `--param key=value` to test how your pipeline expands.
4.  **Automatic Detection:** Detects your current project name (from folder name), git branch, and local pipeline file.

## Usage

### Prerequisites
Set your Azure DevOps Personal Access Token (PAT) as an environment variable:
```bash
export ADO_PAT="your-token-here"
```

### Examples

**Validate local changes:**
```bash
azval
```

**Validate a specific pipeline by ID:**
```bash
azval --id 1234
```

**Pass runtime parameters:**
```bash
azval --param environment=dev --param deploy_infra=true
```

**Override project or branch:**
```bash
azval --project MyProject --branch feature/xyz
```

## How it works
The script uses the `POST .../_apis/pipelines/{id}/runs?previewRun=true` endpoint. Even for local validation, it requires a "reference" pipeline ID to provide the context (repository, service connections, etc.). If you don't provide an `--id`, it will automatically try to find one in your project to use as a template.
