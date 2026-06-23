#!/usr/bin/env bash
# AGENTS.md #67 实战工具: 强制终止挂死的 backtest 进程
#
# 当 backtest 进程 CPU time 不变、状态为 S (sleeping) 时使用
# 默认查找 timing_backtest_*.py 或 macro_data.py 相关进程
#
# Usage:
#   ./scripts/kill-stuck-backtest.sh              # 查找并杀死
#   ./scripts/kill-stuck-backtest.sh --dry-run    # 仅显示，不杀
#   ./scripts/kill-stuck-backtest.sh --older 300  # 进程运行 >300s 才杀

set -e

DRY_RUN=0
OLDER_SECS=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --older) OLDER_SECS=$2; shift 2 ;;
        -h|--help) echo "Usage: $0 [--dry-run] [--older SECS]"; exit 0 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# 查找挂死的 backtest 进程
# 只匹配正在运行脚本文件 (timing_backtest_*.py)，避免误杀 opencode 等辅助进程
echo "🔍 查找 Python 进程（timing_backtest）..."
PIDS=$(ps -axo pid,etime,stat,command 2>/dev/null | \
    grep -E "python.*timing_backtest" | \
    grep -v grep | \
    awk '{print $1, $2, $3, $4, $5, $6, $7, $8}' | head -20)

if [ -z "$PIDS" ]; then
    echo "✅ 没有挂死的进程"
    exit 0
fi

echo "$PIDS"
echo ""

# 检查 --older 过滤
KILL_PIDS=""
while read -r line; do
    if [ -z "$line" ]; then continue; fi
    PID=$(echo "$line" | awk '{print $1}')
    ETIME=$(echo "$line" | awk '{print $2}')
    STAT=$(echo "$line" | awk '{print $3}')
    # 转换 etime 到秒
    if [[ "$ETIME" =~ ^[0-9]+$ ]]; then
        SECS=$ETIME
    elif [[ "$ETIME" =~ ^([0-9]+):([0-9]+)$ ]]; then
        SECS=$((${BASH_REMATCH[1]} * 60 + ${BASH_REMATCH[2]}))
    elif [[ "$ETIME" =~ ^([0-9]+):([0-9]+):([0-9]+)$ ]]; then
        SECS=$((${BASH_REMATCH[1]} * 3600 + ${BASH_REMATCH[2]} * 60 + ${BASH_REMATCH[3]}))
    else
        SECS=0
    fi
    if [ $SECS -ge $OLDER_SECS ]; then
        KILL_PIDS="$KILL_PIDS $PID"
        echo "  PID=$PID 状态=$STAT 运行时长=$ETIME  标记: 挂死"
    else
        echo "  PID=$PID 状态=$STAT 运行时长=$ETIME  标记: 正常"
    fi
done <<< "$PIDS"

if [ -z "$KILL_PIDS" ]; then
    echo ""
    echo "✅ 没有超过 ${OLDER_SECS}s 的挂死进程（可用 --older 0 强制检查）"
    exit 0
fi

echo ""
if [ $DRY_RUN -eq 1 ]; then
    echo "[DRY-RUN] 将要 kill:$KILL_PIDS"
    echo "  重新执行去掉 --dry-run 真正执行"
    exit 0
fi

echo "🛑 强制 kill:$KILL_PIDS"
for PID in $KILL_PIDS; do
    kill -9 $PID 2>/dev/null && echo "  ✓ killed $PID" || echo "  ✗ failed to kill $PID"
done

echo ""
echo "✅ 完成"
