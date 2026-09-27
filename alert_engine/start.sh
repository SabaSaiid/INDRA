#!/usr/bin/env bash
# INDRA Alert Engine — Startup Script
# Usage: ./alert_engine/start.sh [demo|live]
#
# demo: Uses GET /api/events polling (works even without a database)
# live: Uses WS /ws/events with API polling fallback

set -euo pipefail

MODE=${1:-demo}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "╔══════════════════════════════════════════════════════╗"
echo "║   INDRA Alert Engine — Starting in ${MODE^^} mode       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

cd "$ROOT_DIR"

# Install dependencies if not already present
if ! python -c "import aiosqlite" 2>/dev/null; then
    echo "[*] Installing Alert Engine dependencies..."
    pip install -r alert_engine/requirements.txt
fi

# Set environment
export ALERT_ENGINE_MODE="$MODE"
export ALERT_ENGINE_PORT="${ALERT_ENGINE_PORT:-8001}"
export ALERT_ENGINE_HOST="${ALERT_ENGINE_HOST:-0.0.0.0}"
export INDRA_API_BASE="${INDRA_API_BASE:-http://localhost:8000}"
export INDRA_WS_URL="${INDRA_WS_URL:-ws://localhost:8000/ws/events}"
export ALERT_DB_PATH="${ALERT_DB_PATH:-alert_engine.db}"
export ALERT_LOG_LEVEL="${ALERT_LOG_LEVEL:-INFO}"
export ALERT_POLL_INTERVAL_SECONDS="${ALERT_POLL_INTERVAL_SECONDS:-15}"
export ALERT_MIN_CONFIDENCE="${ALERT_MIN_CONFIDENCE:-0.70}"
export ALERT_MIN_SOURCE_COUNT="${ALERT_MIN_SOURCE_COUNT:-2}"
export ALERT_DEFAULT_COOLDOWN_SECONDS="${ALERT_DEFAULT_COOLDOWN_SECONDS:-300}"
export ALERT_DEFAULT_TTL_SECONDS="${ALERT_DEFAULT_TTL_SECONDS:-3600}"
export ALERT_CRITICAL_CONFIDENCE="${ALERT_CRITICAL_CONFIDENCE:-0.90}"

echo "[*] Configuration:"
echo "    Mode          : $ALERT_ENGINE_MODE"
echo "    Port          : $ALERT_ENGINE_PORT"
echo "    INDRA API     : $INDRA_API_BASE"
echo "    DB Path       : $ALERT_DB_PATH"
echo "    Min Confidence: $ALERT_MIN_CONFIDENCE"
echo "    Poll Interval : ${ALERT_POLL_INTERVAL_SECONDS}s"
echo ""
echo "[*] API Documentation: http://localhost:${ALERT_ENGINE_PORT}/docs"
echo "[*] WebSocket        : ws://localhost:${ALERT_ENGINE_PORT}/api/ws/alerts"
echo ""

python -m alert_engine.main
