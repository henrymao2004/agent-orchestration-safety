#!/usr/bin/env bash
# Publish site/ to the gallery remote listed in site/.publish-remote (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_FILE="$ROOT/site/.publish-remote"
if [ ! -f "$REMOTE_FILE" ]; then
  echo "Create site/.publish-remote with the gallery git remote URL." >&2
  exit 1
fi
REMOTE="$(sed -e 's/[[:space:]]*$//' -e '/^#/d' -e '/^$/d' "$REMOTE_FILE" | head -1)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git clone --depth 1 "$REMOTE" "$TMP"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'publish.sh' \
  --exclude '.publish-remote' \
  --exclude 'cases' \
  "$ROOT/site/" "$TMP/"
if [ -d "$ROOT/site/cases" ]; then
  rsync -a --copy-links --exclude '.DS_Store' "$ROOT/site/cases/" "$TMP/cases/"
fi
if [ -f "$ROOT/LICENSE" ]; then cp "$ROOT/LICENSE" "$TMP/LICENSE"; fi
if [ -f "$ROOT/NOTICE" ]; then cp "$ROOT/NOTICE" "$TMP/NOTICE"; fi
: > "$TMP/.nojekyll"
cd "$TMP"
git add -A
if git diff --cached --quiet; then
  echo "No gallery changes to publish."
  exit 0
fi
git commit -m "Publish gallery from site/"
git push
echo "Published."
