# Preservica Upload Tool

A Terminal User Interface (TUI) application for uploading files to Preservica.

## Features

- Browse local file system and Preservica folders side-by-side
- Upload individual files or entire folders
- Automatic S3 upload for large files (>= 100MB)
- Progress tracking during uploads

## Requirements

### git

```bash
# Windows
winget install --id Git.Git -e --source winget

# Linux (Fedora/RHEL/Rocky)
sudo dnf install git
```

### uv

```bash
# Windows
winget install --id=astral-sh.uv  -e

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Installation

```bash
# Clone the repository
git clone https://github.com/nls-lst/preservica-upload
cd preservica-upload

# Install in editable mode
uv tool install -e .

# Later, to update:
preservica-upload --update
```

## Configuration

Set the following environment variables:

### Windows (PowerShell)

**Permanent (saved to user environment):**

```powershell
[System.Environment]::SetEnvironmentVariable("PRESERVICA_USERNAME", "your-username", "User")
[System.Environment]::SetEnvironmentVariable("PRESERVICA_PASSWORD", "your-password", "User")
[System.Environment]::SetEnvironmentVariable("PRESERVICA_SERVER", "your-tenant.preservica.com", "User")
[System.Environment]::SetEnvironmentVariable("PRESERVICA_BUCKET", "your-s3-bucket-name.put.holding", "User")
[System.Environment]::SetEnvironmentVariable("PRESERVICA_S3_THRESHOLD", "100", "User")
```

### Linux

**Add to ~/.bashrc or ~/.zshrc (or in an .env file that you source):**

```bash
# Add these lines to ~/.bashrc or ~/.zshrc
export PRESERVICA_USERNAME="your-username"
export PRESERVICA_PASSWORD="your-password"
export PRESERVICA_SERVER="your-tenant.preservica.com"
export PRESERVICA_BUCKET="your-s3-bucket-name.put.holding"
export PRESERVICA_S3_THRESHOLD="100"
```

Then reload your shell config: `source ~/.bashrc` or `source ~/.zshrc`

## Usage

Once installed, run:

```bash
preservica-upload
```

## Upload Behavior

- Files **< 100MB**: Standard upload (appears immediately in Preservica)
- Files **>= 100MB**: S3 bucket upload (requires ingest workflow processing)

For S3 uploads, files are uploaded to the transfer bucket and processed asynchronously. Check the Preservica admin console to monitor ingest workflows.
