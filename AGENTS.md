# LiangHua — AGENTS.md

This file captures lessons learned and best practices discovered during development.
Every agent working on this project MUST follow these rules.

## Electron Build Configuration

### 1. `asar` and `files` field
- NEVER set `build.files` unless you intend to EXCLUDE node_modules from the asar.
- The `files` field overrides electron-builder defaults — without it, node_modules is included automatically.
- If you must filter asar contents, use `asarUnpack` instead of `files`.

### 2. `asarUnpack` for native modules
- Always add `node_modules/ws/**` and `node_modules/electron-updater/**` to `asarUnpack`.
- These modules are loaded at runtime via filesystem (not from within the asar archive).
- Failing to do so causes "Cannot find module" errors at runtime, even though the build succeeds.

### 3. Dynamic imports for optional dependencies
- NEVER use static `import { autoUpdater } from 'electron-updater'` for modules that might not be installed.
- Use dynamic `require()` wrapped in `try/catch` instead.
- Pattern:
  ```js
  let autoUpdater: any = null
  try {
    autoUpdater = require('electron-updater').autoUpdater
  } catch {
    console.log('[Electron] electron-updater not available, skipping auto-update')
  }
  ```

### 4. `extraResources` filter minimisation
- Always add comprehensive filters for `extraResources` to exclude dev and unnecessary files.
- The backend directory especially accumulates large files: `dist/`, `wheels/`, `tests/`, `sdk/`, `.venv/`, etc.
- Required backend exclusions:
  ```
  !dist/**, !wheels/**, !tests/**, !.github/**, !.pytest_cache/**
  !notebooks/**, !performance/**, !grafana/**, !deploy/**, !sdk/**
  !lianghua_backend.egg-info/**, !.env.example, !Dockerfile, !docker-compose.yml
  !pyproject.toml, !requirements.txt, !run_app.py, !prometheus.yml, !alembic.ini
  ```

## Electron Runtime (main.ts)

### 5. Production resource paths
- In production, `__dirname` points to `app.asar/dist/`.
- Resources placed via `extraResources` live at `process.resourcesPath`, NOT inside the asar.
- NEVER use `path.join(__dirname, '..', 'frontend', ...)` for production paths.
- ALWAYS use `path.join(process.resourcesPath, 'frontend', ...)` for extraResources.
- The correct production frontend path is:
  ```ts
  path.join(process.resourcesPath, 'frontend', 'index.html')
  ```

### 6. Python backend restart safety
- ALWAYS add a retry limit to Python backend restarts to prevent infinite crash loops.
- Pattern:
  ```ts
  let pythonRestartCount = 0
  const MAX_PYTHON_RESTARTS = 5
  ```
- Reset the counter periodically (e.g., every 60 seconds) to allow self-recovery.

### 7. Port conflict detection
- When spawning the Python backend, check for EADDRINUSE errors in the `error` event handler.
- Notify the frontend via IPC when the port is occupied, rather than failing silently.

### 8. Single instance lock
- ALWAYS call `app.requestSingleInstanceLock()` at startup.
- If the lock is not acquired, call `app.quit()` to prevent multiple instances.

### 9. Global error handlers
- ALWAYS register `process.on('uncaughtException')` and `process.on('unhandledRejection')` handlers.
- These should log errors and record crash reports, not just silently ignore.

### 10. Frontend loading errors
- ALWAYS add a `did-fail-load` event handler on the main BrowserWindow.
- In production, show an inline error page with a retry button instead of a blank white screen.

### 11. Icon files
- PNG tray/system icons (`tray-icon.png`, `icon.png`) must exist under `electron/resources/icons/`.
- The project root `/resources/icons/` contains source PNGs; they must be copied to `electron/resources/icons/` for the build.

### 12. Type annotations for event callbacks
- When TypeScript `strict: true` is enabled, event callback parameters must have explicit types.
- For `electron-updater` callbacks, use `: any` for callback parameters:
  ```ts
  autoUpdater.on('update-available', (info: any) => { ... })
  ```

## Testing and Validation

### 13. After any change to build config
- Delete `release/` directory before rebuilding.
- After build, verify asar contents with `@electron/asar`:
  - Check `/dist/main.js` exists
  - Check `node_modules/ws/` files exist (not just the unpacked directory)
  - Verify `Resources/frontend/index.html` exists in the .app bundle
  - Verify `Resources/backend/lianghua-backend` exists

### 14. After any change to main.ts
- Run `npm run build` (tsc) to verify TypeScript compilation.
- Run `npm test` if test script is configured.
- Verify the asar contains the updated `dist/main.js`.
