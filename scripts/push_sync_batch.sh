#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

: "${WORLDNET_SYNC_URL:?WORLDNET_SYNC_URL is required}"
: "${WORLDNET_SYNC_TLS_PIN:?WORLDNET_SYNC_TLS_PIN is required}"
: "${WORLDNET_SYNC_SECRET:?WORLDNET_SYNC_SECRET is required}"

SYNC_HOST_DIRECTORY="${WORLDNET_SYNC_HOST_DIRECTORY:-/home/ubuntu/worldnet-data/sync}"
mkdir -p "${SYNC_HOST_DIRECTORY}"
exec 9>"${SYNC_HOST_DIRECTORY}/push.lock"
flock -n 9 || exit 0

sudo -n docker compose run --rm -T app python scripts/push_sync_batch.py
