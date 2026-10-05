#!/usr/bin/env bash
set -euo pipefail

echo "[finsight-backend] Running migrations…"
python -m alembic upgrade head

echo "[finsight-backend] Starting API on :${API_PORT:-8080}"
exec python -m uvicorn app.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips='*'
