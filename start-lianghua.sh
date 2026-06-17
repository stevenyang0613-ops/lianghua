#!/bin/bash
# start-lianghua.sh - 一键启动 LiangHua 量化交易系统
# 用法: ./start-lianghua.sh [--prod|--dev]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---prod}"

# Kill any process holding our backend port
kill_stale_processes() {
  local port=${1:-8765}
  local pids
  pids=$(lsof -ti:"$port" 2>/dev/null) || true
  if [ -n "$pids" ]; then
    echo "[launcher] Killing stale process(es) on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
}

start_backend() {
  echo "[launcher] Starting backend..."
  cd "$SCRIPT_DIR/backend"

  # Try run_app.py first (handles config, port detection, SSL certs)
  if [ -f "run_app.py" ]; then
    python3 run_app.py --host 127.0.0.1 --port 8765 &
  else
    python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --log-level info &
  fi
  BACKEND_PID=$!

  # Wait for backend to be ready
  echo -n "[launcher] Waiting for backend..."
  for i in $(seq 1 60); do
    if curl -s http://localhost:8765/health > /dev/null 2>&1; then
      echo " ready!"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo ""
  echo "[launcher] WARNING: Backend did not respond in 60s, continuing anyway..."
  return 1
}

cleanup() {
  echo ""
  echo "[launcher] Shutting down..."
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[launcher] Stopping backend (PID $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null
    sleep 1
    # Force kill if still alive
    if kill -0 "$BACKEND_PID" 2>/dev/null; then
      kill -9 "$BACKEND_PID" 2>/dev/null || true
    fi
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  echo "[launcher] Done."
}
trap cleanup EXIT INT TERM

case "$MODE" in
  --prod)
    echo "[launcher] Starting LiangHua (production mode)..."
    echo "[launcher] Python: $(which python3) ($(python3 --version 2>&1))"

    # Kill stale processes first
    kill_stale_processes 8765

    # Start backend independently so the Electron app doesn't need to
    BACKEND_PID=""
    start_backend

    # Open the packaged app
    if [ -d "$SCRIPT_DIR/release/mac-arm64/LiangHua.app" ]; then
      echo "[launcher] Opening LiangHua.app..."
      open "$SCRIPT_DIR/release/mac-arm64/LiangHua.app"
      echo "[launcher] ✓ LiangHua.app launched (backend PID $BACKEND_PID)"
    elif [ -d "/Applications/LiangHua.app" ]; then
      echo "[launcher] Opening /Applications/LiangHua.app..."
      open "/Applications/LiangHua.app"
    else
      echo "[launcher] ERROR: 未找到已构建的 LiangHua.app"
      echo "[launcher] 请先运行: npm run build:mac"
      echo "[launcher] 或使用开发模式: ./start-lianghua.sh --dev"
      exit 1
    fi

    echo ""
    echo "[launcher] ==============================="
    echo "[launcher] Backend:  http://localhost:8765"
    echo "[launcher] App:      LiangHua.app (running)"
    echo "[launcher] Press Ctrl+C to stop all"
    echo "[launcher] ==============================="

    # Wait for user to press Ctrl+C
    wait
    ;;

  --dev)
    echo "[launcher] Starting LiangHua (development mode)..."
    echo "[launcher] Python: $(which python3) ($(python3 --version 2>&1))"

    # Kill stale processes
    kill_stale_processes 8765

    # Start backend
    start_backend

    # Start frontend dev server
    echo "[launcher] Starting frontend dev server..."
    cd "$SCRIPT_DIR/frontend"
    npm run dev &
    FRONTEND_PID=$!

    echo ""
    echo "[launcher] ==============================="
    echo "[launcher] Backend:  http://localhost:8765"
    echo "[launcher] Frontend: http://localhost:5173"
    echo "[launcher] Press Ctrl+C to stop"
    echo "[launcher] ==============================="
    echo ""
    wait
    ;;

  *)
    echo "用法: ./start-lianghua.sh [--prod|--dev]"
    echo "  --prod  启动已构建的生产版本 (默认)"
    echo "  --dev   启动开发模式 (后端 + 前端)"
    exit 1
    ;;
esac
