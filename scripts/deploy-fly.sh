#!/bin/sh
set -eu

root="$(git rev-parse --show-toplevel)"
cd "$root"

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing to deploy a dirty Git worktree" >&2
  exit 1
fi

app="${FLY_APP:-sadar-analyst-console}"
source_commit="$(git rev-parse HEAD)"

exec fly deploy \
  --remote-only \
  --ha=false \
  --app "$app" \
  --build-arg "SOURCE_COMMIT=$source_commit"
