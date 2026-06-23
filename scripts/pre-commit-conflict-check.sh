#!/usr/bin/env bash
# Multi-agent conflict detection: check if files being committed overlap
# with origin/main (another agent may have committed the same files).
#
# Usage: Called automatically by .git/hooks/pre-commit
#   Or manually: ./scripts/pre-commit-conflict-check.sh
#
# Exit codes:
#   0 = no conflict (proceed)
#   1 = conflict detected (commit blocked)

set -e

# 颜色
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

# 检查 git 仓库
if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Not in a git repository"
    exit 1
fi

# 获取远程 main 的最新 commit hash
REMOTE_MAIN=$(git rev-parse origin/main 2>/dev/null || echo "")
if [ -z "$REMOTE_MAIN" ]; then
    echo -e "${YELLOW}[WARN]${NC} origin/main not found, skipping conflict check"
    exit 0
fi

# 获取远程 main 与 HEAD 的分叉点
MERGE_BASE=$(git merge-base HEAD origin/main 2>/dev/null || echo "")
if [ -z "$MERGE_BASE" ]; then
    echo -e "${YELLOW}[WARN]${NC} No merge-base found, skipping conflict check"
    exit 0
fi

# 获取本次 commit 涉及的文件 (已 staged)
STAGED_FILES=$(git diff --cached --name-only)
if [ -z "$STAGED_FILES" ]; then
    exit 0
fi

# 找出 origin/main 自 merge-base 之后修改过的文件
REMOTE_CHANGED=$(git diff --name-only "$MERGE_BASE" origin/main)

# 计算交集
OVERLAPPING=()
for f in $STAGED_FILES; do
    for rf in $REMOTE_CHANGED; do
        if [ "$f" = "$rf" ]; then
            OVERLAPPING+=("$f")
            break
        fi
    done
done

# 输出结果
if [ ${#OVERLAPPING[@]} -eq 0 ]; then
    echo -e "${GREEN}[OK]${NC} No file overlap with origin/main"
    exit 0
fi

echo -e "${YELLOW}[WARN]${NC} 多 agent 冲突检测：以下文件在 origin/main 上也已被修改"
echo ""
for f in "${OVERLAPPING[@]}"; do
    echo "  - $f"
done
echo ""
echo -e "${YELLOW}建议：${NC}"
echo "  1. 先 git fetch origin main"
echo "  2. 运行 git rebase origin/main 合并另一 agent 的修改"
echo "  3. 解决可能的冲突后再 commit"
echo ""
echo -e "如确认无需处理，可加 --no-verify 跳过此检查："
echo -e "  ${GREEN}git commit --no-verify -m '... '${NC}"
echo ""

# 不强制 block，只是警告
exit 0
