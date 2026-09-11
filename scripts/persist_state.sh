#!/usr/bin/env bash
set -euo pipefail

branch="${GITHUB_REF_NAME:-$(git branch --show-current)}"
if [[ -z "$branch" ]]; then
  echo "::error::Cannot persist state from a detached HEAD without a target branch."
  exit 1
fi
git config user.name "AC Screener Bot"
git config user.email "screener@noreply.github.com"

# Quarterly review updates configuration as well as data.
git add -- data universe_config.json
if git diff --cached --quiet; then
  echo "No state changes to commit."
  exit 0
fi
git commit -m "Auto: ${1:-screener state} $(date -u +'%Y-%m-%d')"

for attempt in 1 2 3; do
  # Preserve unrelated generated files without committing them.
  if ! git pull --rebase --autostash origin "$branch"; then
    echo "::error::State rebase failed; refusing to overwrite remote changes."
    exit 1
  fi
  if git push origin "HEAD:refs/heads/$branch"; then
    echo "State pushed successfully on attempt $attempt."
    exit 0
  fi
  echo "Push attempt $attempt failed."
done

echo "::error::State was NOT persisted after three push attempts."
exit 1
