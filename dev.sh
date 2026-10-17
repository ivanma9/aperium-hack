#!/usr/bin/env bash
# Run the Aperium AIS collector (FastAPI) and the Tidemark frontend (Next.js on Bun) together.
# Ctrl-C stops both. Installs missing dependencies on first run.
#
#   ./dev.sh                         # backend :8000, frontend :3000
#   BACKEND_PORT=8001 FRONTEND_PORT=3001 ./dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

blue=$'\033[34m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; reset=$'\033[0m'
say()  { printf '%s[dev]%s %s\n' "$blue" "$reset" "$*"; }
warn() { printf '%s[dev]%s %s\n' "$yellow" "$reset" "$*" >&2; }
die()  { printf '%s[dev]%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

port_in_use() { lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  port_in_use "$p" && die "Port $p is already in use (lsof -iTCP:$p -sTCP:LISTEN)."
done

# ── Backend setup ───────────────────────────────────────────
cd "$ROOT"
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "Created .env from .env.example. Set AISSTREAM_API_KEY in it to receive live AIS data."
elif ! grep -Eq "^AISSTREAM_API_KEY=['\"]?[^'\"[:space:]]+" .env; then
  warn "AISSTREAM_API_KEY is empty in .env: the API will start but report missing_api_key."
fi

if command -v uv >/dev/null 2>&1; then
  say "Syncing backend deps with uv…"
  uv sync --quiet
  BACKEND_CMD=(uv run uvicorn)
else
  PY="${PYTHON:-python3}"
  command -v "$PY" >/dev/null 2>&1 || die "Need uv or python3 (3.9+) for the backend."
  if [[ ! -x .venv/bin/python ]]; then
    say "Creating .venv…"
    "$PY" -m venv .venv
  fi
  # Reinstall only when pyproject.toml changes.
  stamp=.venv/.aperium-installed
  if [[ ! -f $stamp || pyproject.toml -nt $stamp ]]; then
    say "Installing backend deps into .venv…"
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e .
    touch "$stamp"
  fi
  BACKEND_CMD=(.venv/bin/python -m uvicorn)
fi

# ── Frontend setup ──────────────────────────────────────────
command -v bun >/dev/null 2>&1 || die "Need Bun for the frontend: curl -fsSL https://bun.sh/install | bash"
if [[ ! -d web/node_modules || web/bun.lock -nt web/node_modules ]]; then
  say "Installing frontend deps with bun…"
  (cd web && bun install)
  touch web/node_modules
fi

# ── Run ─────────────────────────────────────────────────────
pids=()
cleanup() {
  trap - INT TERM EXIT
  say "Stopping…"
  for pid in ${pids[@]+"${pids[@]}"}; do
    # Kill the whole process group (bun → next, uvicorn reloader → worker).
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

# Prefix each line of a service's output with its name.
prefix() { local tag="$1" color="$2"; while IFS= read -r line; do printf '%s%-8s%s %s\n' "$color" "$tag" "$reset" "$line"; done; }

set -m  # give each background job its own process group so cleanup reaches children
(cd "$ROOT" && exec "${BACKEND_CMD[@]}" aperium.app:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload --reload-dir aperium 2>&1) \
  > >(prefix backend "$green") &
pids+=($!)
(cd "$ROOT/web" && exec bun --bun next dev -p "$FRONTEND_PORT" 2>&1) \
  > >(prefix web "$blue") &
pids+=($!)
set +m

say "Backend   http://127.0.0.1:$BACKEND_PORT/docs"
say "Frontend  http://localhost:$FRONTEND_PORT"
say "Ctrl-C to stop both."

# Exit (and stop the other) as soon as either service dies.
while true; do
  for pid in ${pids[@]+"${pids[@]}"}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      warn "A service exited; shutting down."
      exit 1
    fi
  done
  sleep 1
done
