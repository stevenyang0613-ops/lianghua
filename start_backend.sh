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

# Kill stale process on this port
STALE_PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    echo "[start] Killing stale PID $STALE_PID on port $PORT"
    kill -9 $STALE_PID 2>/dev/null || true
    sleep 1
fi

# Create directories
mkdir -p "$HOME/.lianghua/pids"

cd "$(dirname "$0")/backend"

echo "[start] Starting backend (setsid + nohup)..."

# setsid 必须直接执行目标命令,所以用 bash -c 包装一层
# std 三件套:
#   < /dev/null  - 关 stdin,不持有任何 tty fd
#   > $LOGFILE   - 重定向 stdout 到日志
#   2>&1         - stderr 也走同一日志
setsid nohup python3 run_app.py --host 127.0.0.1 --port $PORT \
    < /dev/null > "$LOGFILE" 2>&1 &
BPID=$!
echo $BPID > "$PIDFILE"
echo "[start] Backend started (PID=$BPID, session detached)"

# Wait for startup
for i in $(seq 1 30); do
    if lsof -i :$PORT 2>/dev/null | grep -q LISTEN; then
        echo "[start] ✅ Backend ready on port $PORT (${i}s)"
        break
    fi
    sleep 1
done
if ! lsof -i :$PORT 2>/dev/null | grep -q LISTEN; then
    echo "[start] ❌ Backend failed to start within 30s. Check $LOGFILE"
    cat "$LOGFILE"
    exit 1
fi

echo "[start] Done."
