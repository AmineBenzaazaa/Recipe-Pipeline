#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"

mkdir -p "$LOG_DIR"
cd "$REPO_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

exec python sheet_image_worker.py \
  --all-tabs \
  --watch \
  --poll-seconds "${SHEET_POLL_SECONDS:-20}" \
  --log-level "${SHEET_LOG_LEVEL:-INFO}" \
  "$@"
