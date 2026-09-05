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

SYNC_HOST_DIRECTORY="${WORLDNET_SYNC_HOST_DIRECTORY:-/home/ubuntu/worldnet-data/sync}"
SYNC_CONTAINER_DIRECTORY="${WORLDNET_SYNC_CONTAINER_DIRECTORY:-/var/lib/worldnet-sync}"
EXPECTED_SOURCE_INSTANCE="${WORLDNET_SYNC_SOURCE_INSTANCE:-oci-overseas}"
INBOX="${SYNC_HOST_DIRECTORY}/inbox"
PROCESSED="${SYNC_HOST_DIRECTORY}/processed"

mkdir -p "${INBOX}" "${PROCESSED}"
LOCK_FILE="${WORLDNET_SYNC_LOCK_FILE:-${PROCESSED}/.import.lock}"
exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

shopt -s nullglob
files=("${INBOX}"/*.json.gz)
shopt -u nullglob
if (( ${#files[@]} == 0 )); then
  exit 0
fi

container_files=()
for file in "${files[@]}"; do
  container_files+=("${SYNC_CONTAINER_DIRECTORY}/inbox/$(basename "${file}")")
done

sudo -n docker compose run --rm -T app python scripts/import_sync_batch.py \
  "${container_files[@]}" \
  --expected-source-instance "${EXPECTED_SOURCE_INSTANCE}" \
  --archive-dir "${SYNC_CONTAINER_DIRECTORY}/processed"
