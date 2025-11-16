#!/usr/bin/env bash
# Gunicorn deployment script for swglogin
# This script starts the Flask app using gunicorn with production settings.
# Can be run manually or invoked by systemd.

set -euo pipefail

# Configuration (override via environment variables)
APP_DIR="${APP_DIR:-/srv/swglogin}"
VENV_PATH="${VENV_PATH:-$APP_DIR/venv}"
BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1:8000}"
WORKERS="${WORKERS:-4}"
WORKER_CLASS="${WORKER_CLASS:-sync}"
TIMEOUT="${TIMEOUT:-120}"
ACCESS_LOG="${ACCESS_LOG:-$APP_DIR/logs/gunicorn-access.log}"
ERROR_LOG="${ERROR_LOG:-$APP_DIR/logs/gunicorn-error.log}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Ensure we're in the app directory
cd "$APP_DIR"

# Create logs directory if it doesn't exist
mkdir -p "$APP_DIR/logs"

# Activate virtualenv if it exists
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    GUNICORN="$VENV_PATH/bin/gunicorn"
else
    # Fall back to system gunicorn
    GUNICORN="gunicorn"
fi

# Check if gunicorn is installed
if ! command -v "$GUNICORN" &> /dev/null; then
    echo "ERROR: gunicorn not found. Install it with: pip install gunicorn"
    exit 1
fi

# Start gunicorn
echo "Starting gunicorn for swglogin..."
echo "  App directory: $APP_DIR"
echo "  Bind address: $BIND_ADDRESS"
echo "  Workers: $WORKERS"
echo "  Worker class: $WORKER_CLASS"
echo "  Access log: $ACCESS_LOG"
echo "  Error log: $ERROR_LOG"

exec "$GUNICORN" \
    --bind "$BIND_ADDRESS" \
    --workers "$WORKERS" \
    --worker-class "$WORKER_CLASS" \
    --timeout "$TIMEOUT" \
    --access-logfile "$ACCESS_LOG" \
    --error-logfile "$ERROR_LOG" \
    --log-level "$LOG_LEVEL" \
    --chdir "$APP_DIR" \
    "app:app"
