#!/bin/bash
# start-lianghua.sh - 一键启动 LiangHua 量化交易系统
# 用法: ./start-lianghua.sh [--prod|--dev]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:---prod}"

cleanup() {
  echo ""
  echo "[launcher] Shutting down..."
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

case "$MODE" in
  --prod)
    echo "[launcher] Starting LiangHua (production mode)..."
    # 优先找已构建的 app
    if [ -d "$SCRIPT_DIR/release/mac-arm64/LiangHua.app" ]; then
      open "$SCRIPT_DIR/release/mac-arm64/LiangHua.app"
      echo "[launcher] ✓ LiangHua.app launched"
    elif [ -d "/Applications/LiangHua.app" ]; then
      open "/Applications/LiangHua.app"
    else
      echo "[launcher] ERROR: 未找到已构建的 LiangHua.app"
      echo "[launcher] 请先运行: npm run build:mac"
      echo "[launcher] 或使用开发模式: ./start-lianghua.sh --dev"
      echo "[launcher] 或双击项目根目录的 LiangHua.app"
      exit 1
    fi
    ;;

  --dev)
    echo "[launcher] Starting LiangHua (development mode)..."
    # 启动后端
    echo "[launcher] Starting backend..."
    cd "$SCRIPT_DIR/backend"
    python3 -m uvicorn app.main:app --reload --port 8765 --log-level info &
    BACKEND_PID=$!

    # 等待后端就绪
    echo -n "[launcher] Waiting for backend..."
    for i in $(seq 1 30); do
      if curl -s http://localhost:8765/health > /dev/null 2>&1; then
        echo " ready!"
        break
      fi
      echo -n "."
      sleep 1
    done

    # 启动前端
    echo "[launcher] Starting frontend..."
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