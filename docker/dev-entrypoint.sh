#!/usr/bin/env bash
set -euo pipefail

cd /home/devuser/app

echo "[finsight] Waiting for Postgres…"
until pg_isready -h postgres -p 5432 -U "${POSTGRES_USER:-finsight}" >/dev/null 2>&1; do
  sleep 1
done
echo "[finsight] Postgres is ready."

echo "[finsight] Ensuring Python deps…"
pip install -q -r backend/requirements.txt

echo "[finsight] Running Alembic migrations…"
cd backend
python3 -m alembic upgrade head
cd ..

if [ -f frontend/package.json ]; then
  echo "[finsight] Fixing frontend/node_modules ownership (named volume is often root-owned)…"
  mkdir -p frontend/node_modules "${HOME}/.npm"
  # Named Docker volumes default to root:root; the container runs as the host UID.
  if ! sudo -n chown -R "$(id -u):$(id -g)" frontend/node_modules "${HOME}/.npm"; then
    echo "[finsight] ERROR: cannot chown node_modules. Try:"
    echo "  docker compose -f docker-compose-dev.yml down"
    echo "  docker volume rm finsight-dev_node-modules-dev"
    exit 1
  fi

  echo "[finsight] npm ci (frontend)…"
  cd frontend
  npm ci
  cd ..
fi

echo "[finsight] Starting backend (:${API_PORT:-8080}) and Vite (:5173)…"
cd backend
python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8080}" --reload &
BACKEND_PID=$!
cd ../frontend
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Keep the container up; if a child exits, restart it instead of killing the whole stack.
while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[finsight] Backend exited — restarting…"
    cd /home/devuser/app/backend
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8080}" --reload &
    BACKEND_PID=$!
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "[finsight] Vite exited — restarting…"
    cd /home/devuser/app/frontend
    npm run dev -- --host 0.0.0.0 --port 5173 &
    FRONTEND_PID=$!
  fi
  sleep 2
done
