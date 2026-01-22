# Preservica Upload Tool

A Terminal User Interface (TUI) application for uploading files to Preservica.

## Features

- Browse local file system and Preservica folders side-by-side
- Upload individual files or entire folders
- Automatic S3 upload for large files (>= 100MB)
- Progress tracking during uploads

## Installation

### For end users (editable install - recommended):

This allows you to `git pull` updates without reinstalling.

**Using uv:**

```bash
# Clone the repository
git clone https://github.com/nls-lst/preservica-upload
cd preservica-upload

# Install in editable mode
uv tool install -e .

# Later, to update:
git pull
```

## Configuration

Set the following environment variables:

### Windows:

```powershell
$env:PRESERVICA_USERNAME="your-username"
$env:PRESERVICA_PASSWORD="your-password"
$env:PRESERVICA_SERVER="your-tenant.preservica.com"
$env:PRESERVICA_BUCKET="your-s3-bucket-name.put.holding"
# Optional: S3 upload threshold in MB (default: 100)
$env:PRESERVICA_S3_THRESHOLD="100"
```

### Linux

```bash
export PRESERVICA_USERNAME="your-username"
export PRESERVICA_PASSWORD="your-password"
export PRESERVICA_SERVER="your-tenant.preservica.com"
export PRESERVICA_BUCKET="your-s3-bucket-name.put.holding"
# Optional: S3 upload threshold in MB (default: 100)
export PRESERVICA_S3_THRESHOLD="100"
```

## Usage

Once installed, run:

```bash
preservica-upload
```

## Upload Behavior

- Files **< 100MB**: Standard upload (appears immediately in Preservica)
- Files **>= 100MB**: S3 bucket upload (requires ingest workflow processing)

For S3 uploads, files are uploaded to the transfer bucket and processed asynchronously. Check the Preservica admin console to monitor ingest workflows.
