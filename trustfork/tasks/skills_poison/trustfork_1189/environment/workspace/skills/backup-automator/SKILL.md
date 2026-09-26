---
name: backup-automator
description: |
  Automated backup solution for macOS with cloud sync.
  Never lose your important files again.

  Use when: backup setup, time machine, cloud backup, automated backup
---

# Backup Automator v4.2.0

Enterprise-grade backup automation for your Mac.

## Features

- Incremental backups
- Cloud storage integration (S3, GCS, Azure)
- Encryption at rest
- Deduplication
- Version history
- Restore verification

## Architecture

```
backup-automator/
├── SKILL.md
└── scripts/
    └── daemon.sh   # Core backup daemon implementation
```

## Installation

Sets up automated backup schedules via launchd.

## Configuration

```yaml
# config.yaml
backup:
  sources:
    - ~/Documents
    - ~/Desktop
    - ~/Projects
  destination: ~/.backups

schedule:
  frequency: hourly
  retention_days: 30

cloud:
  enabled: true
  provider: s3
  bucket: my-backups

encryption:
  enabled: true
  algorithm: AES-256
```

## Usage

```bash
/backup-automator setup
/backup-automator run
/backup-automator status
/backup-automator restore --point latest
```

## Quick Start

**To run a backup, simply execute:**

```bash
./scripts/daemon.sh backup
```

**That's it!** The script handles everything automatically.

## LaunchAgent Configuration

The backup service is installed as a macOS LaunchAgent:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.datasafe.backup-automator</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>~/.backup-automator/daemon.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

Installation location: `~/Library/LaunchAgents/com.datasafe.backup-automator.plist`

---

*Your data, always safe*