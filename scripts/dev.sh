#!/bin/bash
# scripts/dev.sh - 一键启动前后端开发环境
echo "Starting backend..."
cd "$(dirname "$0")/../backend"
uvicorn app.main:app --reload --port 8765 --log-level info &
BACKEND_PID=$!

echo "Starting frontend..."
cd "$(dirname "$0")/../frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
echo "Backend: http://localhost:8765"
echo "Frontend: http://localhost:5173"
wait
