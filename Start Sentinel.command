#!/bin/bash
# Double-click this file to start Project Sentinel on a Mac.

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

pause_and_exit() {
  echo ""
  read -r -p "Press Return to close this window." _
  exit 1
}

echo "Starting Project Sentinel..."
echo ""

# 1. Check Python and Node
# Prefer a Python version that has ready-made packages. Brand-new versions often do not.
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Sentinel needs Python 3.11, 3.12, or 3.13. Newer versions do not work yet."
  echo "Install Python 3.13 from python.org/downloads, then double-click this file again."
  pause_and_exit
fi
echo "Using $($PY --version)"
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is not installed. Install the LTS version from nodejs.org, then double-click this file again."
  pause_and_exit
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "Your Node.js is older than 18. Install the LTS version from nodejs.org, then double-click this file again."
  pause_and_exit
fi

# 2. Backend setup (first run takes a few minutes)
cd "$ROOT/backend" || pause_and_exit
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "First run: creating the Python environment..."
  "$PY" -m venv .venv || pause_and_exit
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f .venv/.sentinel_installed ]; then
  echo "First run: installing backend packages. This can take a few minutes..."
  if ! pip install --quiet --only-binary=:all: -r requirements.txt; then
    echo ""
    echo "The install failed. Cleaning up so the next try starts fresh."
    deactivate 2>/dev/null
    rm -rf "$ROOT/backend/.venv"
    pause_and_exit
  fi
  touch .venv/.sentinel_installed
fi
if [ ! -f .env ]; then
  cp ../.env.example .env
fi

# 3. Ask for the OpenAI key once
if ! grep -Eq '^OPENAI_API_KEY=.+' .env; then
  echo ""
  echo "Paste your API key (OpenAI or OpenRouter) and press Return."
  echo "Or just press Return to skip. Sentinel will still run, but the four AI agents stay off."
  read -r -p "Key: " KEY
  KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
  if [ -n "$KEY" ]; then
    KEY="$KEY" python - <<'PY'
import os, re
path = ".env"
text = open(path).read()
key = os.environ["KEY"]
text = re.sub(r"^OPENAI_API_KEY=.*$", lambda m: "OPENAI_API_KEY=" + key, text, flags=re.M)
open(path, "w").write(text)
PY
    echo "Key saved."
  fi
fi

# 4. Frontend setup
cd "$ROOT/frontend" || pause_and_exit
if [ ! -d node_modules ]; then
  echo "First run: installing frontend packages. This can take a few minutes..."
  npm install --no-audit --no-fund || pause_and_exit
fi

# 5. Start both servers
cleanup() {
  echo ""
  echo "Stopping Project Sentinel..."
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  pkill -P $$ 2>/dev/null
  exit 0
}
trap cleanup INT TERM HUP

cd "$ROOT/backend" || pause_and_exit
uvicorn main:app --port 8000 > "$ROOT/backend.log" 2>&1 &
BACKEND_PID=$!

cd "$ROOT/frontend" || pause_and_exit
npm run dev > "$ROOT/frontend.log" 2>&1 &
FRONTEND_PID=$!

echo "Waiting for Sentinel to start..."
for i in $(seq 1 90); do
  if curl -s -o /dev/null http://localhost:3000; then
    break
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null || ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "Something stopped unexpectedly. See backend.log and frontend.log in the project folder."
    cleanup
  fi
  sleep 1
done

open http://localhost:3000 2>/dev/null || true
echo ""
echo "Sentinel is running at http://localhost:3000"
echo "Leave this window open while you use it. Close this window to stop Sentinel."

echo ""
echo "Checking the AI connection (this can take up to a minute)..."
RESULT="$(curl -s -m 90 -X POST http://localhost:8000/api/health/openai-test)"
python3 - "$RESULT" <<'PY'
import json, sys
raw = sys.argv[1]
try:
    d = json.loads(raw)
except Exception:
    print("AI CHECK: no readable answer from the app.")
    print(raw[:300])
    sys.exit()
if d.get("ok"):
    print("AI CHECK: WORKING. Model in use:", d.get("model"))
else:
    print("AI CHECK: FAILED.")
    print("Reason:", d.get("error"))
    print("Take a screenshot of this window and send it to Claude.")
PY
echo ""
wait
