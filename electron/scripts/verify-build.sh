#!/usr/bin/env bash
# LiangHua build verification script.
# Run after `electron-builder` to confirm the .app bundle is complete
# and won't break at runtime. AGENTS.md improvement: catch missing
# node_modules / truncated asar / unbuilt backend before shipping.
#
# Usage: ./scripts/verify-build.sh [path/to/LiangHua.app]

set -e

APP_PATH="${1:-release/mac-arm64/LiangHua.app}"
ASAR_PATH="$APP_PATH/Contents/Resources/app.asar"
BACKEND_BIN="$APP_PATH/Contents/Resources/backend/dist/lianghua-backend/lianghua-backend"
FRONTEND_INDEX="$APP_PATH/Contents/Resources/frontend/index.html"
ELECTRON_FW="$APP_PATH/Contents/Frameworks/Electron Framework.framework/Electron Framework"

ERRORS=0
WARNINGS=0
pass() { echo "  ✓ $*"; }
fail() { echo "  ✗ $*"; ERRORS=$((ERRORS+1)); }
warn() { echo "  ! $*"; WARNINGS=$((WARNINGS+1)); }

echo "=== LiangHua build verification ==="
echo "Target: $APP_PATH"
echo ""

# 1. App bundle exists
echo "[1] App bundle structure"
if [ -d "$APP_PATH/Contents" ]; then
  pass "Contents/ exists"
else
  fail "Contents/ missing — $APP_PATH is not a valid .app"
  exit 1
fi

if [ -f "$APP_PATH/Contents/Info.plist" ]; then
  pass "Info.plist exists"
else
  fail "Info.plist missing"
fi

# 2. Electron framework
echo ""
echo "[2] Electron runtime"
if [ -f "$ELECTRON_FW" ]; then
  pass "Electron Framework binary present"
else
  fail "Electron Framework binary missing — $ELECTRON_FW"
fi

# 3. Main process asar
echo ""
echo "[3] App asar"
if [ -f "$ASAR_PATH" ]; then
  ASAR_SIZE=$(stat -f%z "$ASAR_PATH")
  pass "app.asar exists ($ASAR_SIZE bytes)"
  
  # Check asar contains minimum required files
  ASAR_FILES=$(npx --no-install asar list "$ASAR_PATH" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$ASAR_FILES" -gt 30 ]; then
    pass "asar contains $ASAR_FILES files (>30, looks complete)"
  else
    fail "asar only has $ASAR_FILES files (expected >30, likely incomplete)"
  fi
  
  # Check for required main process files
  for f in dist/main.js dist/preload.js package.json node_modules/ws; do
    if npx --no-install asar list "$ASAR_PATH" 2>/dev/null | grep -q "^/$f"; then
      pass "asar has /$f"
    else
      fail "asar missing /$f"
    fi
  done
else
  fail "app.asar missing — main process code is not bundled"
fi

# 4. Backend binary
echo ""
echo "[4] Python backend (PyInstaller)"
if [ -f "$BACKEND_BIN" ]; then
  BIN_SIZE=$(stat -f%z "$BACKEND_BIN")
  if [ "$BIN_SIZE" -gt 10000000 ]; then
    pass "lianghua-backend binary present ($BIN_SIZE bytes, looks complete)"
  else
    warn "lianghua-backend binary is only $BIN_SIZE bytes (expected >10MB)"
  fi
  if [ -x "$BACKEND_BIN" ]; then
    pass "lianghua-backend is executable"
  else
    fail "lianghua-backend is NOT executable"
  fi
else
  fail "Backend binary missing: $BACKEND_BIN"
fi

# 5. Frontend
echo ""
echo "[5] Frontend dist"
if [ -f "$FRONTEND_INDEX" ]; then
  pass "frontend/index.html exists"
else
  fail "frontend/index.html missing"
fi

if [ -d "$APP_PATH/Contents/Resources/frontend/assets" ]; then
  ASSET_COUNT=$(ls -1 "$APP_PATH/Contents/Resources/frontend/assets" | wc -l | tr -d ' ')
  pass "frontend/assets/ has $ASSET_COUNT files"
else
  warn "frontend/assets/ missing"
fi

# 6. Code signature (ad-hoc is OK for dev)
echo ""
echo "[6] Code signature"
if codesign -d "$APP_PATH" 2>&1 | grep -q "Signature=adhoc"; then
  pass "Ad-hoc signature (OK for dev builds)"
elif codesign -d "$APP_PATH" 2>&1 | grep -q "Authority=Apple"; then
  pass "Apple Developer ID signature"
else
  warn "Unrecognized signature — Gatekeeper will REJECT"
fi

# 7. Gatekeeper
echo ""
echo "[7] Gatekeeper assessment"
GK_OUT=$(spctl --assess --verbose "$APP_PATH" 2>&1 || true)
if echo "$GK_OUT" | grep -q "accepted"; then
  pass "Gatekeeper accepted"
else
  warn "Gatekeeper rejected (expected for dev builds)"
fi

# Summary
echo ""
echo "=== Summary ==="
echo "  Errors:   $ERRORS"
echo "  Warnings: $WARNINGS"
echo ""

if [ "$ERRORS" -gt 0 ]; then
  echo "✗ Build verification FAILED"
  exit 1
fi

if [ "$WARNINGS" -gt 0 ]; then
  echo "⚠ Build verification PASSED with $WARNINGS warning(s)"
else
  echo "✓ Build verification PASSED"
fi
