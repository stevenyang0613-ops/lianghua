#!/bin/bash
# scripts/dev.sh - 一键启动前后端开发环境
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# 清理函数：退出时杀死所有子进程
cleanup() {
  echo ""
  echo "[dev] Shutting down..."
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
    echo "[dev] Backend (PID $BACKEND_PID) stopped"
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null
    echo "[dev] Frontend (PID $FRONTEND_PID) stopped"
  fi
}
trap cleanup EXIT INT TERM

echo "[dev] === LiangHua Development Environment ==="
echo ""

# 启动后端
echo "[dev] Starting backend on http://localhost:8765 ..."
cd "$ROOT_DIR/backend"
python3 -m uvicorn app.main:app --reload --port 8765 --log-level info &
BACKEND_PID=$!

# 等待后端就绪（最多30秒）
echo -n "[dev] Waiting for backend..."
for i in $(seq 1 30); do
  if curl -s http://localhost:8765/health > /dev/null 2>&1; then
    echo " ready!"
    break
  fi
  echo -n "."
  sleep 1
done
if [ $i -eq 30 ]; then
  echo " timeout!"
  echo "[dev] WARNING: Backend may not be ready. Starting frontend anyway..."
  echo "[dev] TIP: If the backend needs more time, increase the loop"
  echo "[dev]      limit in scripts/dev.sh (i in seq 1 60) or start the"
  echo "[dev]      backend separately with: cd backend && python3 -m uvicorn app.main:app --reload --port 8765"
fi

# 启动前端
echo "[dev] Starting frontend on http://localhost:5173 ..."
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "[dev] ==============================="
echo "[dev] Backend:  http://localhost:8765"
echo "[dev] Frontend: http://localhost:5173"
echo "[dev] Press Ctrl+C to stop all"
echo "[dev] ==============================="
echo ""

wait
