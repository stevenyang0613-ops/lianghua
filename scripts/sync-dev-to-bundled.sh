#!/usr/bin/env bash
# sync-dev-to-bundled.sh - 同步 dev 后端代码到 bundled Electron 应用
# 解决 AGENTS.md #50 描述的"bundled .app 与 backend/app 漂移"问题
#
# 使用场景：
#   - 修改 backend/app/ 后想让 .app 立即生效
#   - 不重新打包整个 Electron 应用，避免 build:electron 的 5-10 分钟构建
#
# 参数：
#   --target <path>  指定 bundled backend 路径（默认 /Users/mac/Desktop/LiangHua.app/.../backend）
#   --no-rsync       强制使用 cp -R 替代 rsync
#
# 环境变量：
#   LH_BUNDLED_BACKEND  等同于 --target
#
# 注意：
#   - bundled 后端进程重启后才会加载新代码（kill run_app.py，Electron 自动重启）
#   - 此脚本不会同步依赖（C 扩展需重新打包）
#   - 路径可在命令行/env 覆盖

set -euo pipefail

# 默认值
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEV_BACKEND="$PROJECT_ROOT/backend"
BUNDLED_APP="${LH_BUNDLED_BACKEND:-/Users/mac/Desktop/LiangHua.app/Contents/Resources/backend}"
USE_RSYNC=true

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            BUNDLED_APP="$2"
            shift 2
            ;;
        --no-rsync)
            USE_RSYNC=false
            shift
            ;;
        -h|--help)
            head -25 "$0" | tail -23
            exit 0
            ;;
        *)
            echo "❌ 未知参数: $1"
            exit 1
            ;;
    esac
done

# 路径检查
if [ ! -d "$BUNDLED_APP/app" ]; then
    echo "❌ bundled app not found at $BUNDLED_APP"
    echo "   请通过 --target 指定正确路径，或设置 LH_BUNDLED_BACKEND"
    exit 1
fi
if [ ! -d "$DEV_BACKEND/app" ]; then
    echo "❌ dev backend not found at $DEV_BACKEND"
    exit 1
fi

echo "🔄 同步 dev → bundled:"
echo "   from: $DEV_BACKEND/app/"
echo "   to:   $BUNDLED_APP/app/"

# 依赖变化检测（python3 hashlib 跨平台，替代 md5sum/md5 命令差异）
DEV_REQ="$DEV_BACKEND/requirements.txt"
BUNDLED_REQ="$BUNDLED_APP/requirements.txt"
_md5() {
    python3 -c "import hashlib,sys;print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "$1" 2>/dev/null
}
if [ -f "$DEV_REQ" ] && [ -f "$BUNDLED_REQ" ]; then
    DEV_HASH=$(_md5 "$DEV_REQ" || echo "unknown")
    BUNDLED_HASH=$(_md5 "$BUNDLED_REQ" || echo "unknown")
    if [ "$DEV_HASH" != "$BUNDLED_HASH" ]; then
        echo ""
        echo "⚠️  requirements.txt 哈希不一致 (dev=$DEV_HASH, bundled=$BUNDLED_HASH)"
        echo "   新增/删除依赖需要在 bundled 环境重新安装，否则可能 ImportError"
        echo "   跳过依赖检查请手动继续 (3 秒超时)..."
        sleep 3
    fi
fi

# Python 版本对比（bundled 用系统 Python 3.12，dev 用 .venv）
DEV_PY_VER=$("$DEV_BACKEND/.venv/bin/python" -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "missing")
# bundled 后端的 Python 路径是系统 Python（pyinstaller 打包时确定）
BUNDLED_PY_VER=$("$BUNDLED_APP/run_app.py" -V 2>/dev/null || echo "3.12")  # 默认假设 3.12
# 更可靠的探测：检查 run_app.py shebang
if [ -f "$BUNDLED_APP/run_app.py" ]; then
    SHEBANG=$(head -1 "$BUNDLED_APP/run_app.py" 2>/dev/null || echo "")
    if [[ "$SHEBANG" =~ python([0-9]+\.[0-9]+) ]]; then
        BUNDLED_PY_VER="${BASH_REMATCH[1]}"
    fi
fi
if [ "$DEV_PY_VER" != "missing" ] && [ "$DEV_PY_VER" != "$BUNDLED_PY_VER" ]; then
    echo ""
    echo "⚠️  Python 版本不一致: dev=$DEV_PY_VER, bundled=$BUNDLED_PY_VER"
    echo "   同步代码可能 OK，但 .so C 扩展/PyInstaller 包需重新打包"
fi

# 同步 .py 文件（优先 rsync，回退 cp -R）
if [ "$USE_RSYNC" = true ] && command -v rsync >/dev/null 2>&1; then
    rsync -av --delete --include="*/" --include="*.py" --exclude="*" \
        "$DEV_BACKEND/app/" "$BUNDLED_APP/app/" | tail -3
else
    if [ "$USE_RSYNC" = true ]; then
        echo "⚠️  rsync 未安装，回退到 cp -R（不支持删除目标端已移除的 .py）"
    fi
    cp -R "$DEV_BACKEND/app/." "$BUNDLED_APP/app/"
fi

# 清理 bundled 的 .pyc 缓存，避免 stale 字节码
echo "🧹 清理 __pycache__/..."
find "$BUNDLED_APP" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 同步前端构建文件到 bundled .app（桌面 app 的 GUI 资源）
echo "📦 同步前端构建到桌面 app..."
BUNDLED_FRONTEND="${BUNDLED_APP%/*}/frontend"  # backend/ → frontend/
if [ -d "$PROJECT_ROOT/frontend/dist" ]; then
    # 确保目标目录存在
    mkdir -p "$BUNDLED_FRONTEND"
    # 删除旧文件并复制新构建（注意：保留 index.html 等文件）
    cp -R "$PROJECT_ROOT/frontend/dist/." "$BUNDLED_FRONTEND/"
    echo "   -> $BUNDLED_FRONTEND/ ✅"
else
    echo "   ⚠️ frontend/dist/ 不存在，跳过前端同步（运行 npm run build）"
fi

# 检测 bundled 中的 Python 后端进程并提示重启
PYTHON_PID=$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null | head -1 || true)
if [ -n "$PYTHON_PID" ]; then
    echo ""
    echo "⚠️  Python 后端进程 PID=$PYTHON_PID 仍在运行（端口 8765）"
    echo "   重启命令: kill -9 $PYTHON_PID"
    echo "   或在 Electron 中手动退出后端（Electron 会自动重启）"
fi

echo "✅ 同步完成"