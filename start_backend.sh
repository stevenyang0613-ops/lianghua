#!/bin/bash
# LiangHua backend startup script
# Kills stale processes, starts backend, survives terminal disconnect.
#
# 使用 setsid + nohup + 重定向 std 三件套让后端进程完全脱离启动 session,
# 关闭终端/断开 SSH 不会发送 SIGHUP 杀死它;父进程退出后由 init (PID 1) 收养。
#
# 关键点:
#   setsid   - 创建新会话 (脱离 controlling tty)
#   nohup    - 忽略 SIGHUP
#   < /dev/null + > log 2>&1 - 关掉 stdin/重定向 stdout/stderr,防止子进程持有任何 fd

set -e

PORT=${1:-8765}
PIDFILE="$HOME/.lianghua/pids/backend.pid"
LOGFILE="/tmp/lianghua_backend.log"

echo "[start] LiangHua Backend Launcher"
echo "[start] Port: $PORT, PID file: $PIDFILE"

# Helper: find PID listening on a port (cross-platform, lsof fallback)
_port_pid() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti :"$port" 2>/dev/null || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | awk -v p=":$port " '$4 ~ p {split($6,a,","); print a[1]}' | head -1
    return
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -tlnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {split($7,a,"/"); print a[1]}' | head -1
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser "$port/tcp" 2>/dev/null | awk '{print $1}' | head -1
    return
  fi
  echo ""
}

_port_listen() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -i :"$port" 2>/dev/null | grep -q LISTEN
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep -q ":$port "
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -tlnp 2>/dev/null | grep -q ":$port "
    return $?
  fi
  # Final fallback: try to connect
  (echo >/dev/tcp/127.0.0.1/"$port") 2>/dev/null
  return $?
}

# Kill stale process on this port
STALE_PID=$(_port_pid "$PORT")
if [ -n "$STALE_PID" ]; then
    echo "[start] Killing stale PID $STALE_PID on port $PORT"
    kill -9 $STALE_PID 2>/dev/null || true
    sleep 1
fi

# Create directories
mkdir -p "$HOME/.lianghua/pids"

cd "$(dirname "$0")/backend"

VENV_PYTHON="$(dirname "$0")/backend/.venv/bin/python3"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    PYTHON="python3"
fi

echo "[start] Python: $PYTHON ($($PYTHON --version 2>&1))"

# macOS 没有 setsid，使用条件判断
if command -v setsid >/dev/null 2>&1; then
    echo "[start] Starting backend (setsid + nohup)..."
    setsid nohup "$PYTHON" run_app.py --host 127.0.0.1 --port $PORT \
        < /dev/null > "$LOGFILE" 2>&1 &
else
    echo "[start] Starting backend (nohup, macOS)..."
    nohup "$PYTHON" run_app.py --host 127.0.0.1 --port $PORT \
        < /dev/null > "$LOGFILE" 2>&1 &
fi
BPID=$!
echo $BPID > "$PIDFILE"
echo "[start] Backend started (PID=$BPID, session detached)"

# Wait for startup
for i in $(seq 1 30); do
    if _port_listen "$PORT"; then
        echo "[start] ✅ Backend ready on port $PORT (${i}s)"
        break
    fi
    sleep 1
done
if ! _port_listen "$PORT"; then
    echo "[start] ❌ Backend failed to start within 30s. Check $LOGFILE"
    cat "$LOGFILE"
    exit 1
fi

echo "[start] Done."
