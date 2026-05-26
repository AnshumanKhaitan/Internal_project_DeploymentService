#!/usr/bin/env bash
# Run Anti Gravity locally (no Docker for the UI/API).
# Deployments still need Docker Desktop/daemon installed to build containers.

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

mkdir -p "$ROOT/backend/data/uploads"

if ! command -v docker >/dev/null 2>&1; then
  echo "Warning: docker not in PATH — upload/deploy will fail until Docker is installed."
fi

# ── Backend ─────────────────────────────────────────────────────────────────
setup_backend() {
  cd "$ROOT/backend"
  if [[ -d .venv/bin ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  elif python3 -m venv .venv 2>/dev/null; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    echo "No venv (install python3-venv) — using system/python3 --user packages"
  fi
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    pip install -q -r requirements.txt
  else
    pip3 install --break-system-packages -q -r requirements.txt
  fi
  if [[ ! -f .env ]]; then
    cp .env.example .env 2>/dev/null || true
  fi
  export UPLOAD_DIR="${UPLOAD_DIR:-$ROOT/backend/data/uploads}"
  export ORCHESTRATOR_PUBLIC_API_URL="${ORCHESTRATOR_PUBLIC_API_URL:-http://localhost:8000}"
  unset DATABASE_URL
  echo "Backend → http://localhost:$BACKEND_PORT (docs: /docs)"
  exec uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT"
}

# ── Frontend ─────────────────────────────────────────────────────────────────
setup_frontend() {
  cd "$ROOT/frontend"
  if [[ ! -d node_modules ]]; then
    echo "Installing frontend dependencies..."
    npm ci
  fi
  if [[ ! -f .env.local ]]; then
    echo "NEXT_PUBLIC_API_URL=http://localhost:$BACKEND_PORT" > .env.local
  fi
  echo "Frontend → http://localhost:$FRONTEND_PORT"
  exec npm run dev -- --port "$FRONTEND_PORT"
}

case "${1:-}" in
  backend)  setup_backend ;;
  frontend) setup_frontend ;;
  *)
    echo "Starting backend and frontend (Ctrl+C to stop)..."
    trap 'kill 0' EXIT
    "$0" backend &
    sleep 2
    "$0" frontend &
    wait
    ;;
esac
