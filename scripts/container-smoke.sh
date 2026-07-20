#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:?usage: scripts/container-smoke.sh IMAGE}"
NAME="sadar-smoke-${RANDOM}-$$"
HOST_PORT="${SADAR_SMOKE_PORT:-17860}"
MAX_COMPRESSED_IMAGE_BYTES=$((1536 * 1024 * 1024))
MAX_IDLE_MEMORY_BYTES=$((1024 * 1024 * 1024))
MAX_PEAK_MEMORY_BYTES=$((1536 * 1024 * 1024))

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

test "$(docker image inspect "$IMAGE" --format '{{.Architecture}}')" = "amd64"
test "$(docker image inspect "$IMAGE" --format '{{.Config.User}}')" = "1000:1000"
image_bytes="$(docker image inspect "$IMAGE" --format '{{.Size}}')"
compressed_image_bytes="$(docker save "$IMAGE" | gzip -1 -c | wc -c | tr -d '[:space:]')"
if [ "$compressed_image_bytes" -gt "$MAX_COMPRESSED_IMAGE_BYTES" ]; then
  echo "container smoke: compressed image exceeds 1.5 GiB gate (${compressed_image_bytes} bytes; ${image_bytes} uncompressed)" >&2
  exit 1
fi

if docker image inspect "$IMAGE" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -Eq '^(HF_TOKEN|HUGGING_FACE_HUB_TOKEN)='; then
  echo "container smoke: publisher token leaked into image environment" >&2
  exit 1
fi
if docker history --no-trunc "$IMAGE" | grep -Eq '(HF_TOKEN|HUGGING_FACE_HUB_TOKEN)'; then
  echo "container smoke: publisher token name leaked into image history" >&2
  exit 1
fi

started_at="$(python3 -c 'import time; print(time.time())')"
docker run --detach --rm \
  --name "$NAME" \
  --memory 2g \
  --memory-swap 2g \
  --env SADAR_ENABLE_EVALUATION=true \
  --env SADAR_EVALUATION_GLOBAL_LIMIT=100 \
  --env SADAR_EVALUATION_CLIENT_LIMIT=100 \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp/sadar:rw,noexec,nosuid,size=128m,mode=1777 \
  --publish "127.0.0.1:${HOST_PORT}:7860" \
  "$IMAGE" >/dev/null

SADAR_SMOKE_BASE_URL="http://127.0.0.1:${HOST_PORT}" \
SADAR_SMOKE_HEALTH_ONLY=1 \
  python3 "$ROOT/scripts/smoke-http.py"

test "$(docker exec "$NAME" printenv TMPDIR)" = "/tmp/sadar"
docker exec "$NAME" test -d /tmp/sadar
temp_entry="$(docker exec "$NAME" find /tmp/sadar -mindepth 1 -print -quit)"
if [ -n "$temp_entry" ]; then
  echo "container smoke: temporary directory was not empty before evaluation" >&2
  exit 1
fi

idle_memory_bytes="$(docker exec "$NAME" cat /sys/fs/cgroup/memory.current)"
if [ -z "$idle_memory_bytes" ] || [ "$idle_memory_bytes" -gt "$MAX_IDLE_MEMORY_BYTES" ]; then
  echo "container smoke: idle cgroup memory exceeds 1 GiB gate (${idle_memory_bytes:-unknown} bytes)" >&2
  exit 1
fi

SADAR_SMOKE_BASE_URL="http://127.0.0.1:${HOST_PORT}" \
SADAR_SMOKE_STARTED_AT="$started_at" \
  python3 "$ROOT/scripts/smoke-http.py" &
smoke_pid=$!
peak_memory_bytes="$idle_memory_bytes"
while kill -0 "$smoke_pid" >/dev/null 2>&1; do
  current_memory_bytes="$(docker exec "$NAME" cat /sys/fs/cgroup/memory.current)"
  if [ -n "$current_memory_bytes" ] && [ "$current_memory_bytes" -gt "$peak_memory_bytes" ]; then
    peak_memory_bytes="$current_memory_bytes"
  fi
  sleep 0.1
done
wait "$smoke_pid"
cgroup_peak_bytes="$(docker exec "$NAME" cat /sys/fs/cgroup/memory.peak)"
if [ -n "$cgroup_peak_bytes" ] && [ "$cgroup_peak_bytes" -gt "$peak_memory_bytes" ]; then
  peak_memory_bytes="$cgroup_peak_bytes"
fi
if [ "$peak_memory_bytes" -gt "$MAX_PEAK_MEMORY_BYTES" ]; then
  echo "container smoke: peak cgroup memory exceeds 1.5 GiB gate (${peak_memory_bytes} bytes)" >&2
  exit 1
fi

cleaned=0
for _attempt in $(seq 1 10); do
  temp_entry="$(docker exec "$NAME" find /tmp/sadar -mindepth 1 -print -quit)"
  if [ -z "$temp_entry" ]; then
    cleaned=1
    break
  fi
  sleep 0.1
done
if [ "$cleaned" -ne 1 ]; then
  echo "container smoke: temporary evaluation data remained beyond the 1s cleanup gate" >&2
  exit 1
fi

echo "container resource gates: compressed_image_bytes=${compressed_image_bytes} idle_memory_bytes=${idle_memory_bytes} peak_memory_bytes=${peak_memory_bytes}"
