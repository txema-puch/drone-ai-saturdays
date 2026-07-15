#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="$ROOT/backend/serve/requirements.in"
OUTPUT="$ROOT/backend/serve/requirements-linux-x86_64.lock"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/sadar-uv-cache}"

command -v uv >/dev/null 2>&1 || {
  echo "uv is required to regenerate the serving lock" >&2
  exit 1
}

uv pip compile "$INPUT" \
  --output-file "$OUTPUT" \
  --python-version 3.11 \
  --python-platform x86_64-manylinux_2_28 \
  --torch-backend cpu \
  --only-binary :all: \
  --generate-hashes \
  --no-emit-package setuptools \
  --no-emit-package wheel \
  --custom-compile-command scripts/compile-serving-lock.sh
