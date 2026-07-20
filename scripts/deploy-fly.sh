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
release_source="${SADAR_RELEASE_SOURCE:-locked-public}"
lock="backend/src/sadar/releases/approach_bundle.lock.json"

if [ "$release_source" != "locked-public" ]; then
  echo "refusing to deploy without the locked-public release source" >&2
  exit 1
fi

schema_version="$(python3 - "$lock" <<'PY'
import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
schema = value.get("schema_version")
if not isinstance(schema, int) or isinstance(schema, bool):
    raise SystemExit(1)
print(schema)
PY
)" || {
  echo "refusing to deploy with an unreadable product release lock" >&2
  exit 1
}

if [ "$schema_version" != "4" ]; then
  echo "refusing to deploy until the committed product lock is schema 4" >&2
  exit 1
fi

exec fly deploy \
  --remote-only \
  --ha=false \
  --app "$app" \
  --build-arg "SADAR_RELEASE_SOURCE=locked-public" \
  --build-arg "SOURCE_COMMIT=$source_commit"
