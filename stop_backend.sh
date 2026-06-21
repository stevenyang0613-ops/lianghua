#!/bin/bash
# Stop LiangHua backend

PORT=${1:-8765}
echo "[stop] Stopping LiangHua backend on port $PORT"

STALE_PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "[stop] Killing PID $STALE_PID"
    kill -9 $STALE_PID 2>/dev/null || true
    sleep 1
    echo "[stop] Done."
else
    echo "[stop] No process on port $PORT"
fi

rm -f "$HOME/.lianghua/pids/backend.pid"
