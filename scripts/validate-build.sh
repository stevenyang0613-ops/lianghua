#!/bin/bash
# 构建前验证脚本
# 在 electron-builder 打包前运行，检查常见问题

set -e

PASS=0
FAIL=0

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "================================"
echo "  LiangHua 构建前验证"
echo "================================"
echo

# 1. Python 语法检查
echo "[1/6] Python 语法检查..."
PY_ERRORS=0
while IFS= read -r f; do
  if ! python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
    echo "  语法错误: $f"
    PY_ERRORS=$((PY_ERRORS + 1))
  fi
done < <(find backend -name '*.py' -not -path '*/__pycache__/*' -not -path '*/.venv/*')
if [ "$PY_ERRORS" -eq 0 ]; then
  echo "  [PASS] 所有 Python 文件语法正确"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] 发现 $PY_ERRORS 个 Python 语法错误"
  FAIL=$((FAIL + 1))
fi

# 2. Electron TypeScript 编译检查
echo
echo "[2/6] Electron TypeScript 编译..."
if node node_modules/.bin/tsc -p electron/tsconfig.json --noEmit 2>/dev/null; then
  echo "  [PASS] TypeScript 编译正常"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] TypeScript 编译有错误"
  FAIL=$((FAIL + 1))
fi

# 3. 前端构建检查
# 使用 vite build（忽略测试文件的 TS 错误，与生产构建一致）
echo
echo "[3/6] 前端构建检查..."
cd frontend
if npm run build 1>/dev/null 2>&1; then
  echo "  [PASS] 前端构建成功"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] 前端构建失败"
  FAIL=$((FAIL + 1))
fi
cd "$REPO_DIR"

# 4. 前端构建产出检查
echo
echo "[4/6] 前端构建产出检查..."
if [ -f frontend/dist/index.html ]; then
  echo "  [PASS] index.html 存在"
  PASS=$((PASS + 1))
else
  echo "  [FAIL] frontend/dist/index.html 未找到"
  FAIL=$((FAIL + 1))
fi

# 5. PyInstaller 打包检查
echo
echo "[5/6] PyInstaller 后端二进制检查..."
if [ -f backend/dist/lianghua-backend ]; then
  BUNDLE_SIZE=$(du -sh backend/dist/lianghua-backend | cut -f1)
  echo "  [PASS] lianghua-backend 存在 ($BUNDLE_SIZE)"
  PASS=$((PASS + 1))
else
  echo "  [WARN] backend/dist/lianghua-backend 未找到（非必需，将回退到 Python venv）"
  PASS=$((PASS + 1))
fi

# 5. CORS 配置检查
echo
echo "[6/6] 后端 CORS 配置检查..."
if grep -q 'allowed_origins.*\*' backend/app/config.py 2>/dev/null; then
  echo "  [WARN] CORS 使用通配符 '*'，不允许在生产环境使用"
  FAIL=$((FAIL + 1))
else
  echo "  [PASS] CORS 未使用通配符"
  PASS=$((PASS + 1))
fi

echo
echo "================================"
echo "  结果: $PASS 通过, $FAIL 失败"
echo "================================"

exit $FAIL
