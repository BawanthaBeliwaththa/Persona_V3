#!/usr/bin/env bash
# ===================================================
#   Persona V3 — Linux / VPS Server Startup Script
# ===================================================

set -e

# Change to script directory
cd "$(dirname "$0")"

echo "==================================================="
echo "  Starting Persona V3 API Server with Uvicorn      "
echo "==================================================="

# Export display if running headed, or use headless mode
export HEADLESS=${HEADLESS:-true}
export HOST=${HOST:-0.0.0.0}
export PORT=${PORT:-8000}

# Install Playwright browser dependencies if needed
if [ "$1" == "--install-deps" ]; then
    echo "Installing system dependencies and Chromium..."
    python3 -m pip install -r requirements.txt
    playwright install chromium
    playwright install-deps chromium
fi

# Run with Uvicorn
exec python3 -m uvicorn main:app --host "$HOST" --port "$PORT" --workers 1
