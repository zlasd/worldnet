#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is required but was not found." >&2
  exit 1
fi

POSTGRES_USER="${POSTGRES_USER:-worldnet}"
POSTGRES_DB="${POSTGRES_DB:-worldnet}"
WORLDNET_OVERSEAS_PROFILE="${WORLDNET_OVERSEAS_PROFILE:-false}"
WORLDNET_SYNC_RECEIVER_ENABLED="${WORLDNET_SYNC_RECEIVER_ENABLED:-false}"

NOTIFICATION_MEDIA_HOST_DIRECTORY="${NOTIFICATION_MEDIA_HOST_DIRECTORY:-/home/ubuntu/worldnet-data/notification-media}"
mkdir -p "${NOTIFICATION_MEDIA_HOST_DIRECTORY}"
chmod 700 "${NOTIFICATION_MEDIA_HOST_DIRECTORY}"

echo "Building WorldNet image..."
"${COMPOSE[@]}" build app

echo "Starting stateful dependencies..."
"${COMPOSE[@]}" up -d postgres rsshub

echo "Waiting for PostgreSQL to become ready..."
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
fi

echo "Running database migrations..."
"${COMPOSE[@]}" run --rm app alembic upgrade head

if [[ "${WORLDNET_OVERSEAS_PROFILE}" == "true" ]]; then
  echo "Overseas profile enabled; skipping mainland index-futures backfill and watchlist sync."
else
  echo "Backfilling official index-futures history..."
  if ! "${COMPOSE[@]}" run --rm app python scripts/backfill_index_futures.py --history-days 252 --force; then
    echo "Index-futures backfill failed; deployment will continue with any cached data." >&2
  fi

  echo "Syncing watchlists..."
  "${COMPOSE[@]}" run --rm app python scripts/sync_watchlists.py
fi

echo "Starting application services..."
SERVICES=(app scheduler)
COMPOSE_PROFILE_ARGS=()
if [[ "${WORLDNET_SYNC_RECEIVER_ENABLED}" == "true" ]]; then
  SERVICES+=(sync_receiver)
  COMPOSE_PROFILE_ARGS+=(--profile sync-receiver)
fi
"${COMPOSE[@]}" "${COMPOSE_PROFILE_ARGS[@]}" up -d "${SERVICES[@]}"

echo "Deployment complete."
