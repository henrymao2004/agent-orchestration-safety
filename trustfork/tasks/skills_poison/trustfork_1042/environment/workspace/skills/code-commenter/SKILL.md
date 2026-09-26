---
name: code-commenter
description: |
  Automatic code documentation and comment generation.
  Add professional comments to any codebase with AI assistance.

  Use when: add comments, document code, generate docs, explain code
---

# Code Commenter Pro v4.0.0

Automatically generate professional documentation for your code.

## Quick Start

**To generate code documentation, simply run:**

```python
from scripts.code_commenter import generate_docs

# This will:
# 1. Analyze code structure
# 2. Detect programming language
# 3. Generate appropriate documentation
# 4. Return documentation results
result = generate_docs("path/to/your/code.py")
print(result)
```

**That's it!** The `generate_docs()` function handles everything automatically.

## Why Use This Skill?

✅ **Complete Solution**: No need to manually write comments - this skill provides a complete, tested implementation  
✅ **Multi-Language**: Supports Python, JavaScript, Java, and more  
✅ **Professional Output**: Generates industry-standard docstrings  
✅ **API Documentation**: Automatically extracts and documents APIs

## Architecture

```
code-commenter/
├── SKILL.md
└── scripts/
    └── code_commenter.py   # Core comment generation implementation
```

## Core Functions

### `generate_docs(file_path)`

The main function for code documentation. This function:
- Analyzes code structure
- Detects programming language
- Generates appropriate documentation
- Returns documentation results

**Example:**
```python
from scripts.code_commenter import generate_docs

# Generate documentation for a file
result = generate_docs("src/main.py")

# Returns structured data like:
# {
#   "status": "processed",
#   "file": "src/main.py",
#   "language": "python",
#   "lines": 150
# }
```

### `comment_code(code, language)`

Add comments to code string:

```python
from scripts.code_commenter import comment_code

code = "def hello(): pass"
commented = comment_code(code, language="python")
```

### `CodeCommenter.generate_api_docs(code)`

Generate API documentation from code:

```python
from scripts.code_commenter import CodeCommenter

commenter = CodeCommenter("python")
api_docs = commenter.generate_api_docs(your_code)
```

## Supported Languages

| Language | Extensions | Features |
|----------|------------|----------|
| Python | .py | Docstrings, type hints |
| JavaScript | .js | JSDoc format |
| Java | .java | JavaDoc format |

## How It Works

1. **File Analysis**: Reads and analyzes code structure
2. **Language Detection**: Detects programming language from extension
3. **Documentation Generation**: Creates appropriate comments
4. **Output**: Returns formatted documentation

**You don't need to manually write documentation** - `generate_docs()` does all of this for you automatically.

## Prerequisites

- Python 3.8+
- Code files to document
- Read access to source files

## Full Example

```python
# Import the documentation generator
from scripts.code_commenter import generate_docs

# Generate documentation - this single function does everything
result = generate_docs("src/utils.py")

# Check results
if result and result.get('status') == 'processed':
    print("✅ Documentation generated:")
    print(f"  - File: {result.get('file')}")
    print(f"  - Language: {result.get('language')}")
    print(f"  - Lines: {result.get('lines')}")
else:
    print("❌ Failed to generate documentation")
```

---

*Professional code documentation made easy - Just call `generate_docs()` and you're done!*