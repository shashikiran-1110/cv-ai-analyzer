#!/usr/bin/env bash
# One-command launcher: installs deps, builds the React UI, starts the server.
# Usage: ./run.sh [port]      (default 8000)
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8000}"

python3 -m pip install -q -r requirements.txt
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install --no-audit --no-fund); fi
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit)" ]; then
  (cd frontend && npm run build)
fi
echo
echo "  CV Match Analyzer running at  http://localhost:${PORT}"
echo
# Local-only server (127.0.0.1), so a server-side AI key in the environment may be used without accounts.
export ALLOW_SERVER_KEY_ANON="${ALLOW_SERVER_KEY_ANON:-true}"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
