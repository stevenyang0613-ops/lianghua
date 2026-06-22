#!/bin/bash
# stop-lianghua.sh - 停止 LiangHua 进程（PID 文件 + 端口双重检测）
#
# 历史问题：之前用 `pkill -f "LiangHua"`，会误杀命令行中包含 "LiangHua"
# 字样的其他进程（IDE、文档、其他 app 实例）。改为：
#   1. 先读 PID 文件精确停止
#   2. 再用端口号（8765 后端）兜底检测

set -e

PID_DIR="$HOME/.lianghua/pids"
BACKEND_PORT="${BACKEND_PORT:-8765}"

stopped=0

# 1. 从 PID 文件精确停止 desktop（Electron）
if [ -f "$PID_DIR/desktop.pid" ]; then
    PID=$(cat "$PID_DIR/desktop.pid" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "[stop] Killing desktop process PID=$PID"
        kill -TERM "$PID" 2>/dev/null || true
        sleep 1
        # 1.5s 后仍存活则强杀
        if kill -0 "$PID" 2>/dev/null; then
            kill -KILL "$PID" 2>/dev/null || true
        fi
        stopped=1
    fi
    rm -f "$PID_DIR/desktop.pid" "$PID_DIR/desktop.ts"
fi

# 2. 从 PID 文件精确停止 backend（Python）
if [ -f "$PID_DIR/backend.pid" ]; then
    PID=$(cat "$PID_DIR/backend.pid" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "[stop] Killing backend process PID=$PID"
        # Python 进程组（macOS 用负 PID 杀整组）
        kill -TERM "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            kill -KILL "-$PID" 2>/dev/null || kill -KILL "$PID" 2>/dev/null || true
        fi
        stopped=1
    fi
    rm -f "$PID_DIR/backend.pid" "$PID_DIR/backend.ts"
fi

# 3. 端口兜底：如果 PID 文件没记录但端口被占，尝试找出占用进程并杀掉
#    注意：只在 PID 目录存在（说明曾经跑过 LiangHua）时才做端口兜底，
#    避免误杀恰好占用 8765 的其他服务。
if [ -d "$PID_DIR" ]; then
    PORT_PIDS=$(lsof -ti :$BACKEND_PORT 2>/dev/null || true)
    if [ -n "$PORT_PIDS" ]; then
        for P in $PORT_PIDS; do
            if kill -0 "$P" 2>/dev/null; then
                # 只杀本用户拥有的进程，避免误杀
                OWNER=$(ps -o user= -p "$P" 2>/dev/null | tr -d ' ' || true)
                CURRENT_USER=$(id -un)
                if [ "$OWNER" = "$CURRENT_USER" ] || [ -z "$OWNER" ]; then
                    echo "[stop] Killing port $BACKEND_PORT holder PID=$P"
                    kill -TERM "-$P" 2>/dev/null || kill -TERM "$P" 2>/dev/null || true
                    sleep 1
                    if kill -0 "$P" 2>/dev/null; then
                        kill -KILL "-$P" 2>/dev/null || kill -KILL "$P" 2>/dev/null || true
                    fi
                    stopped=1
                else
                    echo "[stop] Port $BACKEND_PORT held by other user ($OWNER), skipping"
                fi
            fi
        done
    fi
fi

if [ "$stopped" -eq 0 ]; then
    echo "[stop] 未发现运行中的 LiangHua 进程"
else
    echo "[stop] Done."
fi