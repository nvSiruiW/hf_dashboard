#!/bin/bash
# Start the HF Dashboard in PROD mode.
#
# Looks for an env file at $HF_DASHBOARD_ENV (default ~/.hf_dashboard/env),
# sources it (so ANTHROPIC_API_KEY etc. are exported), then launches reflex
# from the venv.
#
# Usage:
#   ./start.sh                  # default ports 18083 / 18084
#   FRONTEND_PORT=3000 ./start.sh
#   BACKEND_PORT=4000 FRONTEND_PORT=3000 ./start.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${HF_DASHBOARD_VENV:-/localhome/local-siruiw/.hf_dashboard_venv}"
ENV_FILE="${HF_DASHBOARD_ENV:-$HOME/.hf_dashboard/env}"

FRONTEND_PORT="${FRONTEND_PORT:-18083}"
BACKEND_PORT="${BACKEND_PORT:-18084}"

# ---- sanity checks --------------------------------------------------------
if [ ! -x "$VENV_DIR/bin/reflex" ]; then
  echo "ERROR: reflex not found at $VENV_DIR/bin/reflex"
  echo "Did you install the venv? See README.md."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "WARN: env file not found at $ENV_FILE — AI Analyzer will not work."
  echo "      Copy your ANTHROPIC_API_KEY into that file, then re-run."
fi

# ---- load env file --------------------------------------------------------
if [ -f "$ENV_FILE" ]; then
  set -a            # auto-export every variable that gets set
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  if [ -z "$NVIDIA_API_KEY" ] || [ "$NVIDIA_API_KEY" = "PASTE_YOUR_NVIDIA_KEY_HERE" ]; then
    echo "WARN: NVIDIA_API_KEY is not set in $ENV_FILE."
    echo "      AI Analyzer will fail until you paste your real key into that file."
  else
    echo "OK: NVIDIA_API_KEY loaded from $ENV_FILE."
  fi
fi

# ---- launch ---------------------------------------------------------------
cd "$PROJECT_DIR"
export PATH="$VENV_DIR/bin:$PATH"
echo "Starting reflex (PROD) on frontend=$FRONTEND_PORT backend=$BACKEND_PORT ..."
exec "$VENV_DIR/bin/reflex" run \
  --env prod \
  --frontend-port "$FRONTEND_PORT" \
  --backend-port "$BACKEND_PORT"
