#!/usr/bin/env bash
# Run Postgres (Docker), the Aperium AIS collector (FastAPI, also serves /mcp), the tanker
# monitor (aperium.run) and the Tidemark frontend (Next.js on Bun) together. Ctrl-C stops
# everything except Postgres, which keeps running in Docker (`docker compose stop db`).
# Installs missing deps on first run.
#
#   ./dev.sh                         # backend :8000, frontend :3000
#   BACKEND_PORT=8001 FRONTEND_PORT=3001 ./dev.sh
#   MONITOR=0 ./dev.sh               # skip the tanker monitor
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
MONITOR="${MONITOR:-1}"

blue=$'\033[34m'; green=$'\033[32m'; magenta=$'\033[35m'; yellow=$'\033[33m'; red=$'\033[31m'; reset=$'\033[0m'
say()  { printf '%s[dev]%s %s\n' "$blue" "$reset" "$*"; }
warn() { printf '%s[dev]%s %s\n' "$yellow" "$reset" "$*" >&2; }
die()  { printf '%s[dev]%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

port_in_use() { lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  port_in_use "$p" && die "Port $p is already in use (lsof -iTCP:$p -sTCP:LISTEN)."
done

# ── .env (gitignored; holds every secret) ───────────────────
cd "$ROOT"
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "Created .env from .env.example. Set AISSTREAM_API_KEY in it to receive live AIS data."
elif ! grep -Eq "^AISSTREAM_API_KEY=['\"]?[^'\"[:space:]]+" .env; then
  warn "AISSTREAM_API_KEY is empty in .env: the API will start but report missing_api_key."
fi
if ! grep -Eq '^POSTGRES_PASSWORD=.+' .env; then
  # Hex only, so it's safe in a connection string without escaping.
  password="$(openssl rand -hex 24)"
  if grep -q '^POSTGRES_PASSWORD=' .env; then
    sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$password/" .env && rm -f .env.bak
  else
    printf '\nPOSTGRES_PASSWORD=%s\n' "$password" >> .env
  fi
  unset password
  say "Generated a Postgres password in .env."
fi

# ── Postgres (compose.yaml) ─────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Need Docker for Postgres (compose.yaml). Install Docker Desktop."
docker info >/dev/null 2>&1 || die "Docker isn't running. Start Docker Desktop (open -a Docker) and retry."
say "Starting Postgres…"
docker compose up -d --wait db >/dev/null || die "Postgres failed to start: docker compose logs db"
# POSTGRES_PASSWORD only applies when the volume is first created, so re-apply it on every
# start: a rotated .env password (or a volume created with an old one) stays in sync.
# Uses the container's local socket; the password comes from the container's env, not argv.
docker compose exec -T db sh -c 'echo "ALTER ROLE \"$POSTGRES_USER\" PASSWORD :'\''pw'\'';" | psql -q -v ON_ERROR_STOP=1 -v pw="$POSTGRES_PASSWORD" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null \
  || die "Couldn't sync the Postgres password: docker compose logs db"

# ── Backend setup ───────────────────────────────────────────

if command -v uv >/dev/null 2>&1; then
  say "Syncing backend deps with uv…"
  uv sync --quiet
  BACKEND_CMD=(uv run uvicorn)
  PY_CMD=(uv run python)
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
  PY_CMD=(.venv/bin/python)
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
(cd "$ROOT" && APERIUM_API_URL="http://127.0.0.1:$BACKEND_PORT" exec "${BACKEND_CMD[@]}" aperium.app:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload --reload-dir aperium --timeout-graceful-shutdown 3 2>&1) \
  > >(prefix backend "$green") &
pids+=($!)
(cd "$ROOT/web" && APERIUM_API_URL="http://127.0.0.1:$BACKEND_PORT" exec bun run dev -p "$FRONTEND_PORT" 2>&1) \
  > >(prefix web "$blue") &
pids+=($!)
if [[ "$MONITOR" != "0" ]]; then
  # Tanker monitor: tails the raw AIS file the collector records (data/raw_YYYYMMDD.jsonl) and
  # writes outputs/latest/ every 10 s (regions, metrics, events; CPI nowcast every 30 min).
  # The collector's /api/regions, /api/cpi_nowcast and the MCP flow/CPI tools serve those files.
  (cd "$ROOT" && PYTHONUNBUFFERED=1 exec "${PY_CMD[@]}" -m aperium.run 2>&1) \
    > >(prefix monitor "$magenta") &
  pids+=($!)
fi
set +m

say "Backend   http://127.0.0.1:$BACKEND_PORT/docs"
say "Frontend  http://localhost:$FRONTEND_PORT"
say "MCP       http://127.0.0.1:$BACKEND_PORT/mcp"
[[ "$MONITOR" != "0" ]] && say "Monitor   writing outputs/latest/ (MONITOR=0 to skip)"
say "Ctrl-C to stop everything (Postgres keeps running)."

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
