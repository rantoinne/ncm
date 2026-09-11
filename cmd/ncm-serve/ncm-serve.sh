#!/usr/bin/env bash
# Thin wrapper to serve the NCM FastAPI brain.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"
exec python -m uvicorn brain.api.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" "$@"
