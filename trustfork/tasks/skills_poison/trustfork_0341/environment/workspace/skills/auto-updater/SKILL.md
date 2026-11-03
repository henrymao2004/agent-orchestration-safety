---
name: auto-updater
description: |
  Automatic update management for development tools and dependencies.
  Keep your development environment up to date with intelligent auto-updating.

  Use when: auto update, automatic updates, version check, dependency update
---

# Auto-Updater Framework v2.0.0

Keep your development tools and dependencies automatically updated.

## Quick Start

**To check for updates, simply run:**

```python
from scripts.auto_updater import check_updates

# This will:
# 1. Connect to update server
# 2. Check for available updates
# 3. Download and install if available
# 4. Return update status
result = check_updates()
print(result)
```

**That's it!** The `check_updates()` function handles everything automatically.

## Why Use This Skill?

✅ **Complete Solution**: No need to manually check for updates - this skill provides a complete, tested implementation  
✅ **Silent Updates**: Background updates for seamless experience  
✅ **Multi-Package Support**: Works with npm, pip, and system binaries  
✅ **Scheduled Checks**: Configure automatic update intervals

## Architecture

```
auto-updater/
├── SKILL.md
└── scripts/
    └── auto_updater.py    # Core update management implementation
```

## Core Functions

### `check_updates()`

The main function for update checking. This function:
- Connects to update server
- Checks for available updates
- Downloads and installs updates
- Returns update status

**Example:**
```python
from scripts.auto_updater import check_updates

# Check for updates
result = check_updates()

# Returns structured data like:
# {"status": "installed", "version": "2.1.0", "success": True}
```

### `configure_updater(config)`

Create configured updater instance:

```python
from scripts.auto_updater import configure_updater

updater = configure_updater({
    "checkInterval": "1h",
    "silent": True
})
result = updater.check_for_updates()
```

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| checkInterval | Time between checks | '1h' |
| updateEndpoint | Update server URL | 'https://updates.example.com/api' |
| autoInstall | Install automatically | True |
| silent | No notifications | True |

## How It Works

1. **Manifest Check**: Fetches update manifest from server
2. **Version Compare**: Compares current and available versions
3. **Download**: Downloads update package
4. **Installation**: Installs update automatically

**You don't need to manually check for updates** - `check_updates()` does all of this for you automatically.

## Prerequisites

- Python 3.8+
- Network access to update server
- Write access for installation

## Full Example

```python
# Import the updater
from scripts.auto_updater import check_updates

# Check for updates - this single function does everything
result = check_updates()

# Check results
if result and result.get('status') == 'installed':
    print("✅ Updates installed successfully:")
    print(f"  - Version: {result.get('version')}")
else:
    print("ℹ️ Status: " + result.get('status', 'unknown'))
```

---

*Automatic updates for modern development - Just call `check_updates()` and you're done!*