#!/bin/bash
# scripts/build.sh - 一键构建 LiangHua 生产发布版本
# 按顺序执行: 验证 → 前端构建 → PyInstaller → Electron TypeScript → electron-builder

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PIP="pip3"
PYTHON="python3"

# Step 0: 前置验证
echo "[1/6] Build validation..."
bash "$REPO_DIR/scripts/validate-build.sh" || { echo "[FAIL] Validation failed"; exit 1; }
echo ""

# Step 1: Build frontend
cd "$REPO_DIR/frontend"
echo "[2/6] Building frontend..."
npm run build
echo "  [OK] Frontend built"
cd "$REPO_DIR"
echo ""

# Step 2: PyInstaller backend binary
cd "$REPO_DIR/backend"
echo "[3/6] Building PyInstaller binary..."

if ! command -v pyinstaller &>/dev/null; then
  echo "  Installing PyInstaller..."
  $PIP install pyinstaller
fi

EXCLUDES=()
for m in matplotlib scipy IPython ipykernel PIL mypy pytest lxml pyarrow zmq setuptools wheel tkinter tornado jinja2 jsonschema aiohttp fsspec sqlalchemy openpyxl numba cryptography; do
  EXCLUDES+=(--exclude-module "$m")
done

pyinstaller --onefile --optimize=2 --strip --name lianghua-backend \
  --add-data 'app:app' \
  --hidden-import uvicorn --hidden-import uvicorn.loggers \
  --hidden-import uvicorn.loops --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols --hidden-import uvicorn.protocols.http \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.middleware \
  --hidden-import app.engine --hidden-import app.api \
  --hidden-import app.models --hidden-import app.adapters \
  --hidden-import app.strategies --hidden-import app.sg_strategy \
  --hidden-import akshare --hidden-import duckdb \
  --hidden-import pandas --hidden-import httpx \
  --hidden-import websockets --hidden-import numpy \
  --hidden-import pydantic --collect-data akshare \
  "${EXCLUDES[@]}" \
  --distpath dist --workpath build/pyinstaller run_app.py

BUNDLE_SIZE=$(du -sh dist/lianghua-backend 2>/dev/null | cut -f1)
echo "  [OK] PyInstaller binary built (${BUNDLE_SIZE:-unknown})"
cd "$REPO_DIR"
echo ""

# Step 3: Compile Electron TypeScript
cd "$REPO_DIR/electron"
echo "[4/6] Compiling Electron TypeScript..."
npm run build
echo "  [OK] TypeScript compiled"
cd "$REPO_DIR"
echo ""

# Step 4: Electron packaging
cd "$REPO_DIR/electron"
echo "[5/6] Electron Builder packaging..."
npx electron-builder --mac --publish=never

DMG_PATH=$(ls -t release/*.dmg 2>/dev/null | head -1)
if [ -n "$DMG_PATH" ]; then
  DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
  echo "  [OK] DMG built: $DMG_PATH ($DMG_SIZE)"
fi
cd "$REPO_DIR"
echo ""

# Step 5: Done
APP_VERSION=$(node -e "console.log(require('./electron/package.json').version)" 2>/dev/null || echo "?")
echo "========================================"
echo "  Build complete! Version: v${APP_VERSION}"
echo "========================================"
echo ""
echo "Artifacts:"
echo "  - backend/dist/lianghua-backend (PyInstaller)"
echo "  - electron/release/*.dmg (Electron DMG)"
