#!/usr/bin/env bash
#
# deploy.sh — (re)deploy AI DevSecBuddy locally (backend + frontend).
#
#   1. stops any running backend/frontend (by pidfile + by port — safe to re-run)
#   2. installs Python + npm deps and bootstraps the SQLite ledger schema (migration)
#   3. builds the frontend and starts backend + frontend in the background
#   4. prints a command that tails the application logs
#
# Usage:
#   ./deploy.sh          # stop → install → migrate → build → start
#   ./deploy.sh stop     # just stop the running app
#
# Overridable via environment (or a gitignored .env at the repo root, auto-loaded):
#   BACKEND_PORT   (default 8000)
#   FRONTEND_PORT  (default 5173)
#   DEVSECBUDDY_DB (default <repo>/data/ledger.db)
#   DEVSECBUDDY_ENGINE / ANTHROPIC_API_KEY / DEVSECBUDDY_VERTEX_* ...
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"
RUN_DIR="$ROOT/.run"
mkdir -p "$RUN_DIR" "$ROOT/data"

# Load .env (ANTHROPIC_API_KEY, DEVSECBUDDY_* overrides) without echoing it.
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export DEVSECBUDDY_DB="${DEVSECBUDDY_DB:-$ROOT/data/ledger.db}"

step() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }

# --------------------------------------------------------------- stop helpers
kill_port() {  # free a TCP port, whatever holds it
  local port="$1" pids
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti "tcp:${port}" 2>/dev/null | xargs -r kill 2>/dev/null || true
  elif command -v ss >/dev/null 2>&1; then
    pids="$(ss -ltnpH "sport = :${port}" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)"
    [ -n "$pids" ] && kill $pids 2>/dev/null || true
  else
    warn "cannot free port ${port}: none of fuser/lsof/ss found (install psmisc or lsof)"
  fi
}

stop_one() {  # $1 pidfile  $2 port
  if [ -f "$1" ]; then kill "$(cat "$1")" 2>/dev/null || true; rm -f "$1"; fi
  kill_port "$2"
}

stop_all() {
  stop_one "$RUN_DIR/backend.pid"  "$BACKEND_PORT"
  stop_one "$RUN_DIR/frontend.pid" "$FRONTEND_PORT"
}

# --------------------------------------------------------------- `stop` subcommand
if [ "${1:-}" = "stop" ]; then
  step "Stopping backend (:$BACKEND_PORT) and frontend (:$FRONTEND_PORT)…"
  stop_all
  echo "  stopped."
  exit 0
fi

# --------------------------------------------------------------- 1. stop
step "Stopping any running backend/frontend…"
stop_all

# --------------------------------------------------------------- 2. install
step "Installing backend dependencies (Python venv)…"
if [ ! -x "$PY" ]; then
  # --system-site-packages so the venv can see system pyyaml/pytest if present.
  python3 -m venv --system-site-packages "$VENV" 2>/dev/null || true
fi
[ -x "$PY" ] || { echo "ERROR: could not create $VENV (need python3 + python3-venv)"; exit 1; }

py_install() {
  if "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m pip install --quiet "$@"
  else
    # This host's python3-venv ships without ensurepip/pip, so install into the
    # venv's site-packages with the *system* pip (PEP 668 → --break-system-packages).
    local purelib
    purelib="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    python3 -m pip install --quiet --target="$purelib" --break-system-packages "$@"
  fi
}
if "$PY" -c "import fastapi, uvicorn, yaml, httpx, anthropic" 2>/dev/null; then
  echo "  backend deps already satisfied"
else
  py_install "fastapi>=0.110" "uvicorn[standard]>=0.29" "pyyaml>=6" "httpx>=0.27" "anthropic>=0.40"
fi

step "Installing frontend dependencies (npm)…"
npm --prefix "$ROOT/frontend" install --no-fund --no-audit

# --------------------------------------------------------------- 3. migrate
step "Bootstrapping the SQLite ledger schema…"
"$PY" - <<'PY'
import os
from devsecbuddy import Ledger  # also smoke-tests that the package imports

Ledger(os.environ["DEVSECBUDDY_DB"]).close()  # CREATE TABLE IF NOT EXISTS x5
print("  ledger schema ready:", os.environ["DEVSECBUDDY_DB"])
PY

# --------------------------------------------------------------- 4. build + start
step "Building the frontend…"
npm --prefix "$ROOT/frontend" run build

step "Starting backend on :$BACKEND_PORT …"
nohup "$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
  >"$RUN_DIR/backend.log" 2>&1 </dev/null &
echo $! >"$RUN_DIR/backend.pid"

step "Starting frontend on :$FRONTEND_PORT …"
(
  cd "$ROOT/frontend"
  # --strictPort: fail loudly if the port is busy instead of silently drifting to
  # the next one (which would desync the pidfile, health check and printed URL).
  nohup node_modules/.bin/vite preview --strictPort --host 127.0.0.1 --port "$FRONTEND_PORT" \
    >"$RUN_DIR/frontend.log" 2>&1 </dev/null &
  echo $! >"$RUN_DIR/frontend.pid"
)

# --------------------------------------------------------------- health check
step "Waiting for services to come up…"
if command -v curl >/dev/null 2>&1; then
  curl -sf --retry 30 --retry-connrefused --retry-delay 1 "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null \
    && echo "  backend  ✓  http://127.0.0.1:$BACKEND_PORT" \
    || warn "backend did not answer /health — see $RUN_DIR/backend.log"
  curl -sf --retry 30 --retry-connrefused --retry-delay 1 "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null \
    && echo "  frontend ✓  http://127.0.0.1:$FRONTEND_PORT" \
    || warn "frontend did not answer — see $RUN_DIR/frontend.log"
else
  warn "curl not found — skipping health check (give the servers a few seconds)"
fi

# --------------------------------------------------------------- done
printf '\n\033[1;32m✓ Deployed.\033[0m  Open the app:  http://localhost:%s\n' "$FRONTEND_PORT"
printf '   API + OpenAPI docs:            http://localhost:%s/docs\n' "$BACKEND_PORT"
printf '   default engine: %s (free) · ledger: %s\n' "${DEVSECBUDDY_ENGINE:-mock}" "$DEVSECBUDDY_DB"

printf '\nTail the application logs with:\n\n'
printf '   tail -f "%s/backend.log" "%s/frontend.log"\n' "$RUN_DIR" "$RUN_DIR"
printf '\nStop everything with:  ./deploy.sh stop\n\n'
