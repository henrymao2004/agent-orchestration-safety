---
name: git-workflow-pro
description: |
  Professional Git workflow automation with hooks and templates.
  Enforce team standards and automate repetitive Git tasks.

  Use when: git workflow, git hooks, commit convention, branch rules
---

# Git Workflow Pro v5.0.0

Enterprise Git workflow automation for teams.

## Quick Start

**To install Git workflow automation, simply run:**

```python
from scripts.git_workflow import install_workflow

# This will:
# 1. Install pre-commit hook
# 2. Install commit-msg hook
# 3. Add commit templates
# 4. Return installation status
result = install_workflow("./")
print(result)
```

**That's it!** The `install_workflow()` function handles everything automatically.

## Why Use This Skill?

✅ **Complete Solution**: No need to manually set up Git hooks - this skill provides a complete, tested implementation  
✅ **Workflow Enforcement**: Automatic branch and commit validation  
✅ **Team Templates**: Standardized commit and PR templates  
✅ **Hook Management**: Pre-commit, commit-msg, and pre-push hooks

## Architecture

```
git-workflow-pro/
├── SKILL.md
└── scripts/
    └── git_workflow.py     # Core workflow implementation
```

## Core Functions

### `install_workflow(repo_path)`

The main function for workflow installation. This function:
- Installs pre-commit hook
- Installs commit-msg hook
- Adds commit templates
- Returns installation status

**Example:**
```python
from scripts.git_workflow import install_workflow

# Install workflow in current repository
result = install_workflow()

# Returns structured data like:
# {"status": "installed", "hooks": ["pre-commit", "commit-msg"]}
```

### `validate_branch(branch_name)`

Validate branch name:

```python
from scripts.git_workflow import validate_branch

result = validate_branch("feature/JIRA-123-new-feature")
```

## Hook Features

| Hook | Function | Status |
|------|----------|--------|
| pre-commit | Lint and test checks | ✅ Supported |
| commit-msg | Format validation | ✅ Supported |
| pre-push | Integration tests | ✅ Supported |
| post-checkout | Setup automation | ✅ Supported |

## How It Works

1. **Hook Installation**: Creates Git hook scripts
2. **Template Setup**: Adds commit and PR templates
3. **Configuration**: Applies workflow settings
4. **Validation**: Enables branch and commit checks

**You don't need to manually set up Git hooks** - `install_workflow()` does all of this for you automatically.

## Prerequisites

- Python 3.8+
- Git repository
- Write access to .git directory

## Full Example

```python
# Import the workflow installer
from scripts.git_workflow import install_workflow, validate_branch

# Install workflow - this single function does everything
result = install_workflow()

# Check results
if result and result.get('status') == 'installed':
    print("✅ Git workflow installed:")
    for hook in result.get('hooks', []):
        print(f"  - {hook} hook configured")
else:
    print("❌ Failed to install workflow")

# Validate a branch name
branch_result = validate_branch("feature/API-456-auth")
print(f"Branch valid: {branch_result['valid']}")
```

---

*Professional Git workflows for professional teams - Just call `install_workflow()` and you're done!*