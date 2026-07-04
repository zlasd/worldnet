#!/usr/bin/env bash
set -euo pipefail

HERMES_BIN="${HERMES_BIN:-/home/ubuntu/.local/bin/hermes}"
TARGET="${HERMES_WEIXIN_TARGET:-}"
JSON=false
MESSAGE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --to)
      TARGET="${2:-}"
      shift 2
      ;;
    --json)
      JSON=true
      shift
      ;;
    --)
      shift
      MESSAGE_ARGS+=("$@")
      break
      ;;
    *)
      MESSAGE_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${TARGET}" ]]; then
  echo '{"error":"HERMES_WEIXIN_TARGET is not configured"}'
  exit 1
fi

if [[ ${#MESSAGE_ARGS[@]} -gt 0 ]]; then
  MESSAGE="${MESSAGE_ARGS[*]}"
else
  MESSAGE="$(cat)"
fi

if [[ -z "${MESSAGE//[[:space:]]/}" ]]; then
  echo '{"error":"message is empty"}'
  exit 2
fi

ARGS=(send --to "${TARGET}")
if [[ "${JSON}" == true ]]; then
  ARGS+=(--json)
fi
ARGS+=("${MESSAGE}")

exec "${HERMES_BIN}" "${ARGS[@]}"
