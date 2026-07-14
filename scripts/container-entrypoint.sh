#!/bin/sh
set -eu

port="${PORT:-7860}"
case "$port" in
  ""|*[!0-9]*)
    echo "PORT must be an integer from 1 to 65535" >&2
    exit 64
    ;;
esac
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  echo "PORT must be an integer from 1 to 65535" >&2
  exit 64
fi

exec uvicorn backend.serve.app:app \
  --host 0.0.0.0 \
  --port "$port" \
  --workers 1 \
  --no-access-log
