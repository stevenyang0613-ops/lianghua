# backend/app 运行时风险与性能问题扫描报告

> 扫描范围：`/Users/mac/lianghua/backend/app` 全部 Python 文件  
> 扫描时间：当前会话  
> 按优先级排序：高 → 中 → 低

---

## 高优先级（会阻塞事件循环或导致竞态条件）

### 1. `api/backtest.py:1147` — async 阻塞调用
- **问题**：`async def _fetch_real_fallback_data` 中直接使用 `_time.sleep(0.1)`，阻塞事件循环
- **修复**：改用 `await asyncio.sleep(0.1)`

### 2. `api/backtest.py:1207` — async 阻塞调用
- **问题**：`async def _fetch_real_fallback_data` 中直接使用 `_time.sleep(2)`，阻塞事件循环
- **修复**：改用 `await asyncio.sleep(2)`

### 3. `api/ws.py:232` — 竞态条件
- **问题**：`async def market_websocket` 中 `active_market_connections += 1` 不是原子操作，多个并发连接同时修改全局变量可能导致计数漂移
- **修复**：使用 `asyncio.Lock` 保护 `active_market_connections` 的读写，或改用 `asyncio.Queue` 管理连接计数

### 4. `api/ws.py:328` — 竞态条件
- **问题**：`async def market_websocket` 的 `finally` 中 `active_market_connections -= 1` 同上，非原子操作
- **修复**：同上，使用 `asyncio.Lock` 保护

### 5. `api/ws.py:347` — 竞态条件
- **问题**：`async def signals_websocket` 中 `active_signal_connections += 1` 同上
- **修复**：同上

### 6. `api/ws.py:399` — 竞态条件
- **问题**：`async def signals_websocket` 的 `finally` 中 `active_signal_connections -= 1` 同上
- **修复**：同上

---

## 中优先级（资源泄漏或长期运行内存增长）

### 7. `adapters/tdx_adapter.py:43` — 线程池资源泄漏
- **问题**：模块级 `_POOL = ThreadPoolExecutor(max_workers=4)` 没有调用 `shutdown()`，进程退出时线程可能泄漏
- **修复**：在模块末尾注册 `atexit.register(lambda: _POOL.shutdown(wait=True))`

### 8. `engine/fallback_sources.py:21` — 线程池资源泄漏
- **问题**：模块级 `_POOL = ThreadPoolExecutor(max_workers=5)` 没有调用 `shutdown()`，进程退出时线程可能泄漏
- **修复**：同上，注册 `atexit.register(lambda: _POOL.shutdown(wait=True))`

### 9. `api/ws.py` — 统计字典只增不减（内存缓慢增长）
- **问题**：`_ws_stats` 字典中的 `disconnect_reasons` 等计数器只增不减，长期运行内存持续累积（虽然每次增量很小，但永不清理）
- **修复**：定期重置或截断统计值（如每天重置），或使用 `deque(maxlen=...)` 替代无限增长的字典

### 10. `engine/data_enrich.py:171` — 指标缓存只增不减
- **问题**：`_refresh_metrics: dict[str, dict] = {}` 每次刷新都会新增记录，虽然会定期 flush 到文件，但内存中保留所有历史条目。若字段名动态变化或频繁失败，字典会无限增长
- **修复**：添加上限（如最多保留 1000 条），超过时清理最旧的 stale 条目

---

## 低优先级（影响较小，但可优化）

### 11. `main.py:718` — 清理阶段阻塞调用
- **问题**：`lifespan` 的 `yield` 之后（cleanup 阶段）使用 `time.sleep(0.5)` 等待子进程终止。虽然这是进程退出时，但严格来说仍会阻塞事件循环
- **修复**：改为 `await asyncio.sleep(0.5)`

---

## 已排除的误报（确认安全）

| 位置 | 原因 |
|------|------|
| `engine/historical.py:498` | `time.sleep` 在同步函数 `_fetch_baidu_valuation` 内部，通过 `asyncio.to_thread` 调用，不会阻塞事件循环 |
| `engine/data_enrich.py:4795` | `subprocess.run` 在 `loop.run_in_executor` 中执行，不会阻塞事件循环 |
| `main.py:588` | `_enrich_log = open(...)` 在 `lifespan` 启动阶段一次性操作，且 `yield` 之后有 `close()` |
| `engine/data_enrich.py:4850` | `_log = open(...)` 在 `finally` 块中有 `_log.close()`，结构安全 |
| `main.py` 的 `lifespan` 赋值 | `lifespan` 仅在启动时执行一次，不会并发调用，局部变量赋值不是竞态条件 |
| `engine/data_enrich.py` 的 `_cache_lock` | `threading.RLock()` 在 `ThreadPoolExecutor` 的线程中获取（通过 `run_in_executor`），不阻塞事件循环 |
| `backtest.py` 的 `_THREAD_POOL` | 有 `_shutdown_thread_pool()` 函数负责关闭，结构安全 |

---

## 优化建议（非 bug，但值得改进）

1. **`api/ws.py` WebSocket 关闭**：`market_websocket` 和 `signals_websocket` 的 `finally` 块中没有 `await websocket.close()`。虽然 `WebSocketDisconnect` 意味着客户端已关闭，但如果是其他异常，连接可能未正确关闭。建议在 `finally` 中添加 `await websocket.close()`（需处理已关闭的情况）。

2. **`api/ws.py` 统计持久化**：`_ws_stats` 虽然会定期保存到文件，但没有限制内存中统计数据的累积速度。如果进程长期运行（如数周），`_ws_stats` 中的各个字段（如 `disconnect_reasons`）会持续增长。建议添加定时重置机制。

3. **`engine/data_enrich.py` 日志轮换**：`_log_path` 的日志轮换逻辑（截断到 512KB）在 `try/except` 块中，如果文件被其他进程占用，可能导致日志丢失。建议添加文件锁保护或直接使用 `logging.handlers.RotatingFileHandler`。

4. **`engine/data_enrich.py` `_extended_executor` 的优雅关闭**：虽然注册了 `atexit` 处理，但如果进程被 `SIGKILL` 终止，`atexit` 不会执行。对于生产环境，建议在外部进程管理器（如 systemd）中处理资源清理。

5. **全局 `threading.Thread` 使用**：虽然所有 `threading.Thread` 都设置了 `daemon=True`，但 `daemon` 线程在进程退出时会被强制终止，可能导致资源清理不完整（如未 flush 的日志）。建议确保关键线程在退出前有明确的清理机制。
