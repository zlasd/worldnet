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
SYNC_CONTAINER_DIRECTORY="${WORLDNET_SYNC_CONTAINER_DIRECTORY:-/var/lib/worldnet-sync}"
SOURCE_INSTANCE="${WORLDNET_SYNC_SOURCE_INSTANCE:-oci-overseas}"
OUTBOX="${SYNC_HOST_DIRECTORY}/outbox"
SENT="${SYNC_HOST_DIRECTORY}/sent"
STATE_FILE="${SYNC_HOST_DIRECTORY}/last_successful_export"

mkdir -p "${OUTBOX}" "${SENT}"
exec 9>"${SYNC_HOST_DIRECTORY}/push.lock"
flock -n 9 || exit 0

until="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
filename="batch-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n').json.gz"
output_path="${OUTBOX}/${filename}"
export_args=(
  --output "${SYNC_CONTAINER_DIRECTORY}/outbox/${filename}"
  --source-instance "${SOURCE_INSTANCE}"
  --until "${until}"
)
if [[ -s "${STATE_FILE}" ]]; then
  export_args+=(--since "$(<"${STATE_FILE}")")
fi

sudo -n docker compose run --rm -T app python scripts/export_sync_batch.py "${export_args[@]}"
if [[ ! -s "${output_path}" ]]; then
  echo "sync export did not create ${output_path}" >&2
  exit 1
fi

header_file=""
trap 'rm -f "${header_file}"' EXIT
umask 077
header_file="$(mktemp "${SYNC_HOST_DIRECTORY}/.sync-upload-headers.XXXXXX")"
cat >"${header_file}" <<EOF
Authorization: Bearer ${WORLDNET_SYNC_SECRET}
Content-Type: application/gzip
X-WorldNet-Source-Instance: ${SOURCE_INSTANCE}
EOF

# The receiver uses a self-signed certificate, so curl skips CA-chain
# validation but still pins the exact server public key.  The pin is a
# non-secret sha256//... value stored in .env.
response="$(curl \
  --fail-with-body \
  --silent \
  --show-error \
  --max-time "${WORLDNET_SYNC_HTTP_TIMEOUT_SECONDS:-120}" \
  --retry 3 \
  --retry-delay 2 \
  --retry-connrefused \
  --insecure \
  --pinnedpubkey "${WORLDNET_SYNC_TLS_PIN}" \
  --header "@${header_file}" \
  --data-binary "@${output_path}" \
  "${WORLDNET_SYNC_URL}")"
printf '%s\n' "${response}"

printf '%s\n' "${until}" > "${STATE_FILE}.tmp"
mv -f "${STATE_FILE}.tmp" "${STATE_FILE}"
mv -f "${output_path}" "${SENT}/${filename}"
echo "pushed sync batch ${filename}"
