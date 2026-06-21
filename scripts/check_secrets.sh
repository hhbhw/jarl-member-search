#!/usr/bin/env bash
# Charter §6 secrets gate. Run before every commit and inside CI.
# Exits non-zero if anything that looks like a real credential appears
# in tracked files.

set -euo pipefail
cd "$(dirname "$0")/.."

# Files we will scan: everything tracked by git (so .gitignore'd files like
# .env and data/ are inherently skipped). When run before `git init` exists
# we fall back to scanning the working tree minus known dirs.
if git rev-parse --git-dir >/dev/null 2>&1; then
  file_list=$(git ls-files)
else
  file_list=$(find . \
      -type f \
      -not -path './.venv/*' \
      -not -path './data/*' \
      -not -path './.git/*' \
      -not -path './__pycache__/*' \
      -not -name '.env')
fi

if [[ -z "$file_list" ]]; then
  echo "check_secrets: no files to scan"
  exit 0
fi

violations=0

# QRZ Logbook API keys are XXXX-XXXX-XXXX-XXXX hex blocks. Match conservatively
# (only 4 hex blocks separated by dashes — not a random ID).
qrz_pattern='[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}'
# Generic high-signal markers.
markers=(
  "AKIA[0-9A-Z]{16}"            # AWS access key
  "aws_secret_access_key"
  "BEGIN RSA PRIVATE KEY"
  "BEGIN OPENSSH PRIVATE KEY"
  "BEGIN EC PRIVATE KEY"
  "ghp_[A-Za-z0-9]{30,}"        # GitHub PAT
  "xoxb-[0-9A-Za-z-]+"          # Slack bot token
)

while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  # Skip this script itself (the patterns above are literal in here).
  if [[ "$f" == "scripts/check_secrets.sh" || "$f" == "./scripts/check_secrets.sh" ]]; then
    continue
  fi
  # Skip docs/verification screenshots and binary blobs.
  case "$f" in
    *.png|*.jpg|*.jpeg|*.gif|*.pdf|*.zip) continue ;;
  esac

  if grep -EHn "$qrz_pattern" "$f" 2>/dev/null; then
    echo "  ↑ looks like a QRZ-style key in $f"
    violations=$((violations + 1))
  fi
  for pat in "${markers[@]}"; do
    if grep -EHn "$pat" "$f" 2>/dev/null; then
      echo "  ↑ secret marker '$pat' in $f"
      violations=$((violations + 1))
    fi
  done
done <<< "$file_list"

if [[ $violations -gt 0 ]]; then
  echo
  echo "check_secrets: $violations potential leak(s). Investigate above before committing."
  exit 1
fi
echo "check_secrets: clean."
