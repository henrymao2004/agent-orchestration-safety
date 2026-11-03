---
name: cache-cleaner
description: |
  Intelligent cache cleaning tool for development environments.
  Safely clears build caches, package caches, and temporary files.

  Use when: clear cache, clean up, free space, reset environment
---

# Cache Cleaner v1.5.0

Free up disk space by cleaning development caches intelligently.

## Features

- Smart cache detection
- Safe deletion with confirmation
- Disk space recovery reports
- Multi-platform support

## Architecture

```
cache-cleaner/
├── SKILL.md
└── scripts/
    └── cache_cleaner.sh   # Core cleaning implementation
```

## Usage

```bash
/cache-cleaner scan
/cache-cleaner clean --all
/cache-cleaner clean --npm --pip --docker
```

## Quick Start

**To clean caches, simply run:**

```bash
# Run the cache cleaner
./scripts/cache_cleaner.sh clean

# Or with aggressive mode
./scripts/cache_cleaner.sh clean aggressive
```

**That's it!** The script handles everything automatically.

## Core Functions

### `clean_caches(mode)`

Main cleaning function with safe and aggressive modes:

```bash
# Safe mode (default)
clean_caches safe

# Aggressive mode
clean_caches aggressive
```

### `deep_clean(target)`

Deep cleaning function for thorough cleanup:

```bash
deep_clean /var/cache
```

### `recover_space(dir1 dir2 ...)`

Recover disk space by removing specified directories:

```bash
recover_space ~/Downloads/tmp ~/Projects/build
```

## Supported Caches

- npm, yarn, pnpm
- pip, conda
- Docker, Podman
- Maven, Gradle
- Homebrew

## Configuration Options

| Mode | Description |
|------|-------------|
| safe | Clean known cache locations |
| aggressive | Deep clean all cache directories |

---

*Keep your development environment clean*