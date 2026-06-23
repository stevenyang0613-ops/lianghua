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

## Backend Configuration

### 15. `.env` location for the Python backend
- The root `.env` file (with `LH_*` variables) lives at the project root, not in `backend/`.
- pydantic-settings' default `env_file` is `.env` in the CWD — when the backend is started from `backend/`, the root `.env` is **not** loaded by default, causing `LH_TAVILY_API_KEY`, `LH_GITHUB_TOKEN` and similar to silently come up empty.
- ALWAYS set `env_file` in `Settings.model_config` to the project-root `.env` (resolved via `Path(__file__).parent.parent / ".env"`), and make it conditional on `exists()` so the test suite is unaffected.
- Pattern used in `backend/app/config.py`:
  ```python
  _BACKEND_DIR = Path(__file__).resolve().parent.parent
  _PROJECT_ROOT = _BACKEND_DIR.parent
  _DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"
  class Settings(BaseSettings):
      ...
      model_config = {
          "env_prefix": "LH_",
          "env_file": str(_DEFAULT_ENV_FILE) if _DEFAULT_ENV_FILE.exists() else None,
          "env_file_encoding": "utf-8",
          "extra": "ignore",
      }
  ```
- Verify with: `from app.config import settings; print(settings.TAVILY_API_KEY)` — should not be empty.

## Electron Runtime — Lessons Learned (2026-06-13 audit)

### 16. Single-instance lock — the `else` block must own the rest of the file
- `app.quit()` is **asynchronous**. If you write `if (!gotTheLock) { app.quit() }` without returning, the rest of the module (including `app.whenReady().then(...)`) executes in the second instance too — duplicate Python process, duplicate tray icon, window flash, port conflict.
- Pattern: put every `app.on(...)` listener, error handler, and `app.whenReady().then(...)` inside the `else { ... }` branch. Use a leading `// NOTE:` comment so future edits don't lift them out.

### 17. `restartBackend` is not reentrant-safe and is not quit-safe
- Concurrent triggers (health monitor + manual IPC click) caused 2–3 `startPythonBackend()` calls.
- `oldProcess.on('exit', ...)` + `setTimeout(..., 3000)` racing the same start → multiple Python processes fighting for port 8765.
- Pattern (in `electron/main.ts`):
  - `let restartInFlight = false` guard at the top
  - `if (isQuitting) return` at the top
  - `oldProcess.removeAllListeners('exit')` before adding a one-shot `oldProcess.once('exit', ...)`
  - Always call `killPythonProcessGroup(oldProcess)` instead of `oldProcess.kill()` (see #18)
  - Use a single `setTimeout(..., 3000)` fallback that resolves the `restartInFlight` flag

### 18. Python child process — kill the whole process group, not just the leader
- `child.kill()` only sends SIGTERM to the top-level Python process. Uvicorn workers, multiprocessing pools, and Celery workers remain alive.
- macOS / Linux: spawn with `detached: true`; kill via `process.kill(-pid, 'SIGTERM')` (negative pid = process group), then `SIGKILL` after a 1.5 s grace period.
- Windows: `taskkill /pid <pid> /T /F`.
- Helper: `killPythonProcessGroup(child: ChildProcess)` in `main.ts`.

### 19. `did-fail-load` only acts on the main frame
- `event.isMainFrame` is FALSE for sub-resource failures (favicons, JS chunks, CSS). Without this guard, any 404 in production assets replaces the whole app with an error page.
- The error page's "Retry" button must call an IPC method (e.g. `retry-frontend-load`), NOT `window.location.reload()` — that just reloads the `data:` URL of the error page itself.
- Pattern: add `ipcMain.handle('retry-frontend-load', ...)` and expose `retryFrontendLoad: () => ipcRenderer.invoke('retry-frontend-load')` in preload.

### 20. `safeStorage` does not silently fall back to plaintext
- `safeStorage.isEncryptionAvailable() === false` happens on Linux without a keychain, sandboxed environments, or in headless CI. Returning `Buffer.from(plainText).toString('base64')` is **not encryption** — it's a 1:1 reversible encoding that any caller will treat as ciphertext.
- Pattern: throw a hard error so the caller (typically the renderer) can fall back to a different persistence strategy or surface the problem to the user.

### 21. IPC-driven HTTP requests need a host allowlist
- `httpRequestHandler` accepting any URL is an SSRF vector. The desktop auth token is auto-injected, so any compromised renderer can hit `http://169.254.169.254/...`, internal services, etc.
- Pattern: only allow `127.0.0.1`, `localhost`, `::1` via a `Set`. Reject everything else with `{ ok: false, error: 'Host not allowed' }`.

### 22. `loadWindowState` must validate numeric ranges AND on-screen position
- `if (state.width && state.height)` accepts negative numbers, huge numbers, off-screen coordinates, and non-numeric values if JSON parses.
- Always: `Number.isFinite(...) && >= min && <= max`, and check `x/y` against `screen.getAllDisplays()` to avoid spawning off-screen after a monitor disconnect.

### 23. WebSocket connect-timeout must reconcile late `open` events
- The persistent `ws.on('open', ...)` listener (registered before the IPC Promise) is gated by `ipcResolved`. If the WS opens AFTER the 5 s timeout, the renderer would never receive `ws-state:connected`.
- Pattern: track `wsAccepted`. On timeout, if `ws.readyState === WebSocket.OPEN`, manually send `ws-state:connected` to the renderer.

### 24. `child-process-gone` reports the actual `details.type`, not `'gpu'`
- Electron can fire this for `renderer | gpu | utility | plugin | sandbox | service-worker | injected | flash | v8-sandbox | network`.
- Only 4 of those map to `CrashReport['type']`. Map the rest to `'main'` to avoid corrupting crash analytics.

### 25. `dialog.showMessageBox(mainWindow!, ...)` can crash
- The `!` is a lie when the user closes the window before a menu click fires.
- Pattern: `dialog.showMessageBox(mainWindow as any, ...)` — passing `null` to the underlying C++ is a no-op (no parent window). The `as any` silences TS without changing behavior.

### 26. WebSocket connection pool needs a cap
- A buggy or hostile renderer can call `ws-connect` thousands of times. Each entry holds an open WS (fd, buffers, listeners).
- Pattern: `MAX_WS_CONNECTIONS = 64`, reject new `wsId`s when the map is full.

### 27. Backend spawn failure must surface immediately
- `pythonProcess.on('error', ...)` runs as soon as `ENOENT` or similar happens. Without an immediate `mainWindow.webContents.send('backend-error', ...)`, the user stares at a loading screen for the full 60 s `waitForBackend` timeout.

### 28. preload's `as ElectronAPI` cast hides missing interface members
- Adding a method to the `exposeInMainWorld` object without adding it to the `ElectronAPI` interface is silently allowed by the cast. Renderer TypeScript can't reference the new method, but it works at runtime — leading to drift.
- Pattern: keep the interface in sync with the implementation. Drop the `as` cast entirely and let TS enforce it.

### 29. Process-cleanup completeness in `before-quit` / `will-quit`
- `pythonRestartTimer` (60 s reset of `pythonRestartCount`) was never cleared on quit — clear it in `before-quit`.
- `killPythonProcessGroup` must be called instead of `pythonProcess.kill()`.

## Bug-fixing discipline

### 30. Verification before claiming a fix
- After every change to a file, run the relevant test/lint/build BEFORE reporting "no more bugs".
- Specifically for this project:
  - `cd electron && npx tsc --noEmit` (TypeScript compile)
  - `cd electron && npx jest` (electron unit tests)
  - `cd backend && .venv/bin/python -m pytest tests/ -p no:cacheprovider --tb=line -q --maxfail=20` (full pytest)
- If a test was previously passing and now fails after a fix, the fix is wrong — investigate, do not skip.
- Do not call something "complete" until ALL THREE checks pass in one batch.

### 31. When asked to find bugs, actually run code
- A static "I read it and it looks fine" pass is not bug-finding. Run `tsc`, `jest`, `pytest`, `mypy`. Look at runtime behavior, not just types.
- For Electron main process code, mentally trace the lifecycle: who can call this, can `mainWindow` be null here, can `pythonProcess` be null here, can `isQuitting` be true here.
- Ask the reverse question: "what input would break this code?"

### 32. End-to-end verification: read the actual data the user sees
- After any data-pipeline change, do not declare success based on logs showing "X stocks processed" — connect to the actual WebSocket, parse real messages, and tabulate field coverage across the live data.
- Pattern: `asyncio` + `websockets` + gzip + collect N messages, then per-field count non-None/non-empty values.
- For backend startup, the right wait time is **at least 6-10 minutes**, not 30 seconds — because Baidu fallback for 250 stocks + Tencent hist for 300 stocks runs serially in a single thread.

## Backend Data Enrichment (2026-06-13 audit)

### 33. Indentation bug: `if entry: result[code] = entry` outside `for` loop
- In `_refresh_debt_cache` (and other iterrows-based refresh functions), the assignment to `result[code]` MUST be inside the `for _, r in df.iterrows():` block. The historical bug had it dedented by one level, so only the last row was actually committed.
- Pattern: always verify by counting — `len(result)` should equal `len(df) - rows_with_missing_key`. If it doesn't, check indentation.
- Symptom in logs: `Debt: 2 stocks, 1 dr, 1 cr` when fetching 5214 rows = 100% data loss.

### 34. Volatility scheduling: `asyncio.sleep(30)` then call is race-prone
- `_refresh_spot_cache` can take 5-10 minutes (Baidu fallback for 250 stocks + Tencent hist for 300 stocks).
- The original `start_background_refresh` scheduled `_refresh_volatility_cache` only 30 s after spot started, so volatility always found empty spot map and returned 0 stocks.
- Pattern: chain them in a single executor task: `def _spot_then_vol(): _refresh_spot_cache(); _refresh_volatility_cache()`.

### 35. Tencent hist as East Money hist fallback
- `ak.stock_zh_a_hist` is IP-banned on East Money's CDN.
- `ak.stock_zh_a_hist_tx(symbol='sh{code}', adjust='hfq')` returns the full 90-day daily K-line and works reliably.
- Column names differ: TX uses `close` (lowercase), EM uses `收盘`.
- Pattern: try TX first, fall back to EM with try/except. Filter TX closes > 0 (some rows have negative "adjusted" values).

### 36. threading.RLock in async code blocks the event loop
- `_set_global_map` uses `threading.RLock()` to protect global map mutations. This is fine in executor threads.
- But `enrich_quotes` is an `async def` that calls `with _cache_lock:`. Holding a sync lock inside async code can deadlock if the same lock is later acquired from another thread that the event loop is waiting on.
- Pattern: in `enrich_quotes`, drop the lock and just snapshot the dicts directly. The dict.copy() is < 1ms; a stale snapshot for 1ms is harmless.

### 37. Duplicate `with _cache_lock:` wraps subsequent code
- Indentation error introduced nested `with _cache_lock:` blocks, leaving the first one empty and putting everything inside the second.
- `vol_snapshot = _vol_map.copy()` ended up OUTSIDE the lock because of this.
- Pattern: when editing locks, always verify the lock scope visually with a `git diff`.

### 38. EM `stock/get` fast-fail detection
- When `push2.eastmoney.com` is IP-banned, the `ulist.np/get` batch call fails immediately. Then the per-stock `stock/get` fallback also fails. Without detection, this wastes 20+ minutes looping through 5000 stocks.
- Pattern: sample 5 stocks first; if all fail, skip the individual fallback entirely.

### 39. Baidu valuation as PE/PB primary fallback when East Money is banned
- `ak.stock_zh_valuation_baidu(symbol, indicator='市盈率(TTM)', period='近一年')` returns the latest day's value, ~0.4 s/call.
- 3-thread pool, 250 stocks ≈ 2-3 min. Returns 99%+ coverage for bond stock codes.
- Limitation: each call is one indicator. Need 2 calls (PE + PB) per stock.

### 40. THS financial abstract as PE/PB tertiary fallback
- `ak.stock_financial_abstract_ths(symbol, indicator='按年度')` returns multi-year data with EPS and BPS.
- Compute `PE = price / EPS`, `PB = price / BPS` as last-resort fallback when both EM and Baidu fail.
- Note: annual EPS is stale (last fiscal year-end), so this gives 6-12 month-old data — only use as last resort.

### 41. Dead code in adapter: `_is_expired_bond` defined but never called
- `app/adapters/akshare.py` had `_is_expired_bond` (line 444) that was never referenced.
- The actual filter logic was already inlined into `_is_stopped_trading`.
- Pattern: use `grep -n 'def _is_expired_bond\|self._is_expired_bond' file.py` to find dead code before editing.

### 42. Worker data collection: only collect for bond underlying stocks, not all 5000 A-shares
- The original fallback called Baidu/THS for all 5000 A-shares = 30+ minutes.
- After restricting to `_bond_stock_codes` (set by `market.refresh()` from `bond.stock_code`), the scope drops to 250 stocks = 2-3 minutes.
- Pattern: maintain a `set[str]` of codes that the user actually needs, not the whole universe.

### 43. Auto-load bond stock codes from THS at startup
- `_bond_stock_codes` was set only by `market.refresh()` after the first WS push. But `_refresh_spot_cache` starts earlier as a background task.
- Pattern: if `_bond_stock_codes` is empty when needed, auto-load from `ak.bond_zh_cov_info_ths()` (THS 主列表).
- This decouples the spot refresh from the first market refresh.

### 44. `sorted` with missing field — what if dict has no key?
- `_refresh_volatility_cache` used `sorted(source.items(), key=lambda x: x[1].get("circ_mv", 0) or 0)`.
- `_spot_map` values DO NOT have `circ_mv` — it's not in any cache fill path. So `x[1].get(...)` always returns 0 → all stocks have equal weight → iteration order is arbitrary.
- Even with the default 0, this is wasteful. Better: defend against non-dict values with `isinstance(v, dict) and v.get("circ_mv")`.

## 最高准则

### 0. 每次输出结束后必须提供优化改进建议
- 每次对话输出结束后（回答完用户问题后），必须附带提出新的优化改进建议和潜在bug
- 建议应包括：性能优化、代码质量、数据准确性、架构改进等
- 潜在bug应基于对代码的理解，指出可能出问题的边界情况
- 即使所有测试通过，也要分析运行时的潜在风险
- 该规则优先于所有其他规则

### 0.1 全部输出必须使用中文（2026-06-23 固化）
- **所有 prompt 的输出内容必须使用中文**（包括思考、解释、注释、错误信息、commit message、日志分析、TodoList 等）
- 英文仅在以下情况允许：代码标识符（变量名、函数名、类名）、技术专有名词（API 名称、库名）、文件路径、URL、commit hash
- 避免在中文文本中夹杂英文整句
- commit message 必须用中文（参考 `feat(数据源): 添加 6 个新数据源` 而非 `feat(data-sources): add 6 new sources`）
- 用户明确要求时除外（如用户主动写英文提问时）
- 该规则优先于所有其他规则

### 45. Don't declare "no bugs" prematurely
- The user complained about repeated cycles of "fixed everything" → new bug found.
- Root cause: stopping at first successful log line, not running the actual user-facing flow.
- Mandatory end-to-end check after ANY data-pipeline change:
  1. Kill backend, clear all caches, restart
  2. Wait at least 6-10 minutes (Baidu + Tencent hist are slow)
  3. Connect WebSocket, collect 30+ messages
  4. Tabulate per-field coverage (X/N bonds, X%)
  5. Cross-check against expected: PE/PB/industry/ROE all should be >95%
- If ANY critical field is 0%, you have a bug. Don't claim success.

### 46. Per-stock enrichment caches need broad coverage, not just bond underlying stocks
- `_refresh_north_cache`, `_refresh_block_trade_cache`, `_refresh_restricted_release_cache`
  originally restricted per-stock calls to a small subset (e.g. 80 bond stocks), giving
  single-digit coverage of A-shares.
- Rule: when extending these caches, ALWAYS pull from a full A-share code list (spot cache,
  `ak.stock_info_a_code_name()`, or `bond_zh_cov()` union'd with all A-share codes).
- Parallelism: 10-15 workers is the sweet spot (more triggers EM rate-limit at scale).
- Save progress every 200 entries via `_save_cache` so partial runs aren't lost.
- Pattern: `missing_codes = [c for c in all_a_codes if c not in result]` then thread-pool fetch.

### 47. AKShare 1.18.x has no `stock_block_trade_em` — use `stock_dzjy_mrmx`
- `ak.stock_block_trade_em()` does NOT exist in akshare 1.18.x.
- The correct per-trade detail interface is `ak.stock_dzjy_mrmx(start_date, end_date)`,
  which returns columns: 证券代码/简称/成交价/成交量/成交额/买方营业部/卖方营业部/...
- For broker rankings use `ak.stock_dzjy_yybph(symbol="近一月")`.
- For market stats use `ak.stock_dzjy_sctj(start_date, end_date)` (by date) and
  `ak.stock_dzjy_mrtj(start_date, end_date)` (daily summary).
- Verify with: `dir(ak)` and grep for `block`/`dzjy` before assuming an API exists.

### 48. cninfo data sources fail in macOS Electron sandbox — skip by default
- `ak.stock_hold_management_detail_cninfo()` and other cninfo APIs require py_mini_racer,
  which raises `dlsym(...)` on macOS sandbox and Electron-bundled apps.
- Rule: skip cninfo as Source 1, put it last as opt-in via env var
  (`LH_MGMT_TRY_CNINFO=1`) for dev environments only.
- Use EM (East Money) equivalents as primary: `ak.stock_hold_management_detail_em()`,
  `ak.stock_ggcg_em(symbol="全部")`, `ak.stock_restricted_release_detail_em(...)`.
- Defensive: keep `result.update(cached)` at the start so a single failed source doesn't
  wipe out previous data.

### 49. start_backend.sh needs `setsid` + std 3-piece for full session detachment
- `nohup` alone ignores SIGHUP but the child still belongs to the parent's session/PGID.
- Closing the terminal sends SIGHUP to the whole process group → backend dies.
- Pattern: `setsid nohup CMD < /dev/null > LOG 2>&1 &` (session detached, no tty, no fd leak).
- After this, the parent can exit cleanly and init (PID 1) adopts the backend.

### 50. Sync bundled `.app` when source changes — don't trust build artifacts
- The dev bundle at `electron/release-dev/.../LiangHua.app/Contents/Resources/backend/`
  contains a stale copy of `app/` that diverges from `backend/app/` after edits.
- Symptom: source fix works in `pytest` but production Electron app still shows old bug.
- Fix: `cp backend/app/<file>.py electron/release-dev/.../Resources/backend/app/<file>.py`
  AND `rm -rf electron/release-dev/.../Resources/backend/app/**/__pycache__/` to clear stale
  `.pyc` bytecode.
- Better long-term fix: wire a pre-build step in `npm run build:dev` that copies
  `backend/app/` into the asar payload before electron-builder runs.

### 51. Async coroutines that "look like work" need explicit await
- `RuntimeWarning: coroutine 'X' was never awaited` fires from CPython's GC, often late
  (at interpreter shutdown or asyncio loop teardown), making it hard to trace.
- Defensive pattern in long-running coroutines: add `if not asyncio.iscoroutinefunction(fn): raise`
  at entry — converts silent warning into a fast-fail AttributeError at the actual call site.
- Audit: `grep -rn "start_background_refresh\b" backend/app/` to find every call site.
  Check the BUNDLED .app, not just `backend/`, because #50's drift can leave stale sync stubs.

## Scoring & Data Serialization Patterns

### 52. `safe_score` with `treat_zero_as_missing` and `has_data` priority
- `safe_score(value, score_fn, neutral=50.0, has_data=None, treat_zero_as_missing=True)`
  provides NaN/zero/missing data handling for financial indicator scoring.
- **Priority rule**: `has_data` takes precedence over `treat_zero_as_missing`.
  - `has_data=False` → always returns `neutral`, regardless of `value` or `treat_zero_as_missing`.
  - `has_data=True` → `value=0` is treated as valid data (not missing).
  - `has_data=None` (default) → falls back to `treat_zero_as_missing` logic.
- **Three-state pattern for boolean availability fields**: Use `Optional[bool]` (`None`=unknown,
  `True`=confirmed present, `False`=confirmed absent) instead of `bool` defaults.
  - When `None`, fall back to value inference (e.g., `ytm != 0` implies data exists).
  - When `True`, treat 0 as valid (e.g., YTM=0% is a real observation).
  - When `False`, always return neutral (data source confirmed unavailable).
- Example: `cb_ytm_available: Optional[bool] = None` in `EnhancedMarketData`.

### 53. `clean_numpy_types` — recursive JSON serialization safety net
- Recursively converts numpy types → Python native types for JSON serialization.
- Handles Python `float` NaN/Inf → `None` (JSON spec forbids NaN/Inf).
- Handles `numpy.bool_`, `numpy.integer`, `numpy.floating`, `numpy.ndarray`, `numpy.generic`.
- Supports `set`/`frozenset` → `list` conversion.
- Supports `__float__`/`__int__` protocol objects (e.g., `Decimal` wrappers) → `float`/`int`.
- **Ordering matters**: `isinstance(obj, bool)` MUST come before `__int__` check, because
  `bool` has `__int__` but should be serialized as `true`/`false`, not `1`/`0`.
- Call sites: `EnhancedMarketData.to_dict()`, `_enhanced_signal_to_frontend()`.
- **Performance note**: Called on every WebSocket push message; for high-frequency paths
  with known schema, consider flat-field processing instead of recursive traversal.

### 54. Bayesian optimizer `np.errstate` pattern for GP numerical instability
- GP regression can produce `std=0` or `std<0` (numerical noise) → `z=inf` or `z=NaN`.
- Pattern: early return `np.zeros_like(mu)` when ALL std values are 0 or NaN.
- Wrap acquisition function computation in `with np.errstate(invalid='ignore', divide='ignore')`
  to suppress RuntimeWarning from `0/0` or `inf/0`.
- After computing `z`, always apply `np.where(np.isfinite(result), result, 0.0)` to convert
  inf/NaN → 0 (argmax will ignore these positions).
- When only SOME std values are 0: `z = (mu - best) / std` produces inf at those positions,
  which is mathematically correct (deterministic points have no improvement). The `np.where`
  fallback handles this case; no additional logic needed.
- This pattern applies to all three acquisition types: EI, UCB, PI.

### 55. `_enhanced_signal_to_frontend` NaN score → 'missing' status pattern
- When `total_score` or category scores are NaN (data unavailable), the frontend signal
  must use `status: 'missing'` instead of inferring from score thresholds.
- Sub-factor NaN scores → `score: null` (JSON null), `signal: "missing"`.
- Recommendation text: `if math.isnan(total_score): recommendation = "数据不足，无法评估择时信号"`.
- This ensures the frontend can render gray/"数据缺失" labels instead of blank or 0.
- Also applies to `_get_recommendation()` (non-enhanced signal path).

### 56. 兜底归档代码 — `_archive/` 目录管理
- 删除大段不再使用的代码文件时，不要直接删除（git 历史保留不代表 IDE/新人可发现）。
- 移到 `_archive/` 目录下，保留文件名和顶部 docstring 以便 grep 可回溯。
- 避免在归档文件中保留会被自动导入的模块级代码（如 `from ... import`），以防 Python 动态导入链意外激活。

### 57. 长耗时批量 API 使用后台任务模式
- `/data-sources-v2/*` 和 `/extra/*` 中的批量接口（行业、股东户数、北向资金、转债历史 K 线等）可能阻塞事件循环 30 秒以上。
- 提供一个 `async_task: bool` 参数，为 `True` 时立即返回 `{task_id, status}`，通过 `GET /tasks/{task_id}` 轮询结果。
- 使用 `app/services/task_registry.py` 中的 `TaskRegistry` 轻量后台任务注册表（线程池 + 内存状态字典），不引入 Redis/Celery。
- 前端封装 `submitTask()` / `getTask()` / `listTasks()` / `pollTaskUntilDone()` 位于 `frontend/src/services/api.ts` 末尾。
- 配置 `async_task: True` 提交后台任务，`pollTaskUntilDone()` 轮询 2s 间隔、300s 超时，支持 `onProgress` 回调更新 UI。

### 58. 北向资金 individual_detail_em 分批处理 + 提前退出
- `_refresh_north_cache` 中的逐股补齐（source 4）改为 200 只股票一批（chunk），每批 180 秒超时。
- 达到 1500 只个股后提前退出，避免遍历全 A 股（~5000 只）耗时过长。
- `LH_NORTH_MAX_PER_RUN` 环境变量可控制每轮最大尝试数（默认 1500）。

### 59. 股东户数备选接口使用 `stock_zh_a_gdhs_detail_em` 而非 `stock_zh_a_gdhs`
- `stock_zh_a_gdhs(symbol=code)` 参数含义是季度（如 `"20230930"`），不是个股代码，无法用于单股查询。
- 正确的单股接口是 `stock_zh_a_gdhs_detail_em(symbol="000001")`，返回该股的全部历史股东户数变更记录。
- 字段映射：`股东户数-本次` → `holder_num`，`股东户数-增减比例` → `change_pct`。
- 在 `_fetch_alt` 和 source 3 fallback 中均已修复。

### 60. AKShare `stock_zh_a_gdhs` 签名是季度而非个股
- `stock_zh_a_gdhs(symbol="20230930")` 返回该季度的全市场股东户数（含 tqdm 进度条），不是单只股票。
- 如果看到 tqdm 进度条 "858/858" 耗时 1-2 分钟，说明误用了该接口。
- 前端需要该数据的场景应使用 `stock_zh_a_gdhs_detail_em(symbol=code)`。
