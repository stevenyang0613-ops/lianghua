# LiangHua Codex Development Rules

## Critical Build Rules (must follow every build)

### Pre-build checklist
1. Verify `build.files` is NOT set in package.json (or includes node_modules)
2. Verify `asarUnpack` includes `node_modules/ws/**` and `node_modules/electron-updater/**`
3. Verify `extraResources` backend filter excludes `dist/`, `wheels/`, `tests/`, and other dev artifacts
4. Verify `electron/resources/icons/` has `tray-icon.png` and `icon.png`

### Post-build validation
5. Extract and check asar: `dist/main.js` and `node_modules/ws/` files must exist
6. Check .app bundle: `Resources/frontend/index.html` and `Resources/backend/lianghua-backend` must exist
7. DMG size should be ~170MB (clean) not ~250MB (with dev artifacts)

## Runtime Rules (main.ts)

1. ALL paths to extraResources must use `process.resourcesPath`, never `__dirname`
2. Python backend restart must have MAX_RETRIES=5 with periodic counter reset
3. Always use `app.requestSingleInstanceLock()` before `app.whenReady()`
4. Register `uncaughtException` and `unhandledRejection` global handlers
5. Add `did-fail-load` handler on BrowserWindow for frontend error recovery
6. Detect EADDRINUSE when spawning Python backend
7. Dynamic import for electron-updater with try/catch fallback
