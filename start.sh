#!/usr/bin/env sh
set -eu
PORT="${PORT:-8000}"
exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --workers 1 --no-server-header
