#!/bin/bash
# stop-lianghua.sh - 停止 LiangHua 进程

pkill -f "LiangHua" 2>/dev/null && echo "[stop] LiangHua 进程已停止" || echo "[stop] 未发现运行中的 LiangHua 进程"