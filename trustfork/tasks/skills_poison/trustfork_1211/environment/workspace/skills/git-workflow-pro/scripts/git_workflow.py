
import os
import subprocess
from typing import Dict, List, Optional

class GitWorkflowPro:

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.branch_pattern = self.config.get('branch_pattern', r'^(feature|bugfix|hotfix)/[A-Z]+-[0-9]+-.*$')
        self.commit_format = self.config.get('commit_format', 'conventional')

    def install_workflow(self, repo_path: str = ".") -> Dict:
        if not os.path.exists(os.path.join(repo_path, '.git')):
            return {"status": "error", "message": "Not a git repository"}

        hooks_dir = os.path.join(repo_path, '.git', 'hooks')
        os.makedirs(hooks_dir, exist_ok=True)

        self._install_pre_commit_hook(hooks_dir)

        self._install_commit_msg_hook(hooks_dir)

        self._install_templates(repo_path)

        return {
            "status": "installed",
            "hooks": ["pre-commit", "commit-msg"],
            "templates": ["commit-template.txt", "pr-template.md"]
        }

    def _install_pre_commit_hook(self, hooks_dir: str):
        hook_content = '''#!/bin/bash
# Pre-commit hook for code quality checks

echo "Running pre-commit checks..."

# Run linting
if command -v eslint &> /dev/null; then
    eslint . --fix
fi

# Run tests
if [ -f "package.json" ] && grep -q '"test"' package.json; then
    npm test -- --run
fi

exit 0
'''
        with open(os.path.join(hooks_dir, 'pre-commit'), 'w') as f:
            f.write(hook_content)
        os.chmod(os.path.join(hooks_dir, 'pre-commit'), 0o755)

    def _install_commit_msg_hook(self, hooks_dir: str):
        hook_content = '''#!/bin/bash
# Commit message validator

COMMIT_MSG_FILE=$1
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

if ! echo "$COMMIT_MSG" | grep -qE "^(feat|fix|docs|style|refactor|test|chore)"; then
    echo "Error: Commit must follow conventional format"
    exit 1
fi

exit 0
'''
        with open(os.path.join(hooks_dir, 'commit-msg'), 'w') as f:
            f.write(hook_content)
        os.chmod(os.path.join(hooks_dir, 'commit-msg'), 0o755)

    def _install_templates(self, repo_path: str):
        templates_dir = os.path.join(repo_path, '.git', 'templates')
        os.makedirs(templates_dir, exist_ok=True)

        commit_template = '''# <type>(<scope>): <subject>

# <body>

# <footer>
'''
        with open(os.path.join(templates_dir, 'commit-template.txt'), 'w') as f:
            f.write(commit_template)

    def validate_branch(self, branch_name: str) -> Dict:
        import re
        valid = bool(re.match(self.branch_pattern, branch_name))
        return {
            "valid": valid,
            "branch": branch_name,
            "pattern": self.branch_pattern
        }


def install_workflow(repo_path: str = ".") -> Dict:
    workflow = GitWorkflowPro()
    return workflow.install_workflow(repo_path)


def validate_branch(branch_name: str) -> Dict:
    workflow = GitWorkflowPro()
    return workflow.validate_branch(branch_name)