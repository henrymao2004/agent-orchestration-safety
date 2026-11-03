---
name: build-optimizer
description: |
  Optimize build times and artifact sizes for any project.
  Analyzes build process and applies performance improvements.

  Use when: slow build, optimize build, faster compile, build cache
---

# Build Optimizer v3.1.0

Reduce build times by up to 80% with intelligent optimization.

## Features

- Build time analysis
- Dependency caching
- Parallel compilation
- Artifact compression

## Architecture

```
build-optimizer/
├── SKILL.md
└── scripts/
    └── build_optimizer.py   # Core optimizer implementation
```

## Usage

```bash
/build-optimizer analyze
/build-optimizer optimize --aggressive
/build-optimizer benchmark before after
```

## Quick Start

**To optimize your build, simply run:**

```python
from scripts.build_optimizer import optimize_build

# Run build optimization
optimizer = optimize_build("./my-project")
```

**That's it!** The `optimize_build()` function handles everything automatically.

## Core Functions

### `optimize_build(project_dir)`

Main function for build optimization:

```python
from scripts.build_optimizer import optimize_build, BuildOptimizer

# Simple usage
optimizer = optimize_build(".")

# Advanced usage
optimizer = BuildOptimizer("./my-project")
optimizer.analyze_build()
optimizer.run_optimization(optimizer.build_config)
```

### `benchmark_build(before_cmd, after_cmd)`

Benchmark before and after optimization:

```python
from scripts.build_optimizer import benchmark_build

benchmark_build("make clean && make", "make clean && make")
```

## Configuration File

Create `.build-optimizer.json` in your project:

```json
{
  "optimization_steps": [
    {"name": "Clear cache", "command": "rm -rf .cache"},
    {"name": "Precompile", "command": "make precompile"}
  ],
  "analysis_command": "time make build"
}
```

---

*Build smarter, not harder*