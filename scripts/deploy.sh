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

echo "Backfilling official index-futures history..."
if ! "${COMPOSE[@]}" run --rm app python scripts/backfill_index_futures.py --history-days 252 --force; then
  echo "Index-futures backfill failed; deployment will continue with any cached data." >&2
fi

echo "Syncing watchlists..."
"${COMPOSE[@]}" run --rm app python scripts/sync_watchlists.py

echo "Starting application services..."
"${COMPOSE[@]}" up -d app scheduler

echo "Deployment complete."
