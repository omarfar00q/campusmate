#!/usr/bin/env bash
# CampusMate One-Command Runner (Bash)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

export PYTHONPATH="$(dirname "$SCRIPT_DIR"):$SCRIPT_DIR:${PYTHONPATH:-}"

echo "============================================================"
echo " Starting CampusMate (MCP Server + Agent API + Frontend)"
echo "============================================================"

# 1. Seed database
echo "[1/4] Ensuring database seed data is initialized..."
$PYTHON_BIN -m campusmate.data.seed_data

# 2. Launch MCP Server
echo "[2/4] Starting Standalone MCP Server on port 8000..."
$PYTHON_BIN -m campusmate.server.app.main --port 8000 &
MCP_PID=$!

sleep 1

# 3. Launch Agent SSE API
echo "[3/4] Starting Agent SSE Service on port 8001..."
$PYTHON_BIN -m campusmate.agent.api --port 8001 &
AGENT_PID=$!

sleep 1

# 4. Launch Vite Frontend
echo "[4/4] Starting Vite Frontend on port 5173..."
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $MCP_PID $AGENT_PID $FRONTEND_PID 2>/dev/null || true" EXIT

echo ""
echo "============================================================"
echo " All CampusMate services are active:"
echo " - Frontend UI:   http://127.0.0.1:5173"
echo " - MCP Server:    http://127.0.0.1:8000/mcp (Health: /health)"
echo " - Agent SSE API: http://127.0.0.1:8001/api/chat"
echo "============================================================"
echo "Press Ctrl+C to stop all services."

wait
