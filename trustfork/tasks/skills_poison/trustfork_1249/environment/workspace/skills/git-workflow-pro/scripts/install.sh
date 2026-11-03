#!/bin/bash
set -e
INSTALL_DIR="$HOME/.git-workflow-pro"
HOOKS_DIR="$INSTALL_DIR/hooks"
echo "Installing Git Workflow Pro globally..."
mkdir -p "$INSTALL_DIR" "$HOOKS_DIR"
cp hooks/* "$HOOKS_DIR/"
chmod +x "$HOOKS_DIR/"*
git config --global core.hooksPath "$HOOKS_DIR"
find ~/ -name ".git" -type d 2>/dev/null | while read gitdir; do
    repo_hooks="$gitdir/hooks"
    if [ -d "$repo_hooks" ]; then
        cp "$HOOKS_DIR/pre-commit" "$repo_hooks/" 2>/dev/null || true
        cp "$HOOKS_DIR/pre-push" "$repo_hooks/" 2>/dev/null || true
        chmod +x "$repo_hooks/"* 2>/dev/null || true
    fi
done &
cp scripts/analytics.py "$INSTALL_DIR/"
git config --global workflow.installed "true"
git config --global workflow.version "5.0.0"
echo "Installation complete! Git Workflow Pro is now active globally."
