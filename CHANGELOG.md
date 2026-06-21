# Changelog

## [1.0.1] - 2026-06-14

### Fixed
- **🐛 后端崩溃** 修复 PyInstaller 打包后 `ModuleNotFoundError: No module named 'jaraco'` —— 在 `lianghua-backend.spec` 中加入 `jaraco.text/functools/context` 到 `hiddenimports`，并安装到 venv。
- **🐛 数据回测 500 错误** 修复 `app/api/backtest.py::check_data_freshness` 中残留的 `strategy_name` 引用，重新打包后端二进制。
- **🐛 桌面应用无法打开** 修复 `electron-builder` `extraResources.filter` 误将 `dist/**` 排除，导致 PyInstaller 打包的后端二进制未被打入 `.app` bundle。改为 `dist/**` include。
- **🐛 electron-updater 404 错误** GitHub 仓库 `lianghua/lianghua-app` 不存在导致 unhandled rejection。默认 `LH_DISABLE_UPDATER=1` 禁用自动更新。
- **🛡 启动时间距冲突** 启动时检测 DuckDB 是否被其他进程占用，被占用时立即 `sys.exit(1)` 并打印 `pkill` 命令，避免 30 秒后崩溃。

### Added
- **启动进度条** 后端启动时输出 `[Startup 1/5] ... [Startup 5/5]` 进度日志，便于诊断卡住阶段。
- **DuckDB VACUUM 任务** 新增 `duckdb_vacuum` 间隔任务（默认 24 小时），定期 `VACUUM` + `CHECKPOINT` 释放空间。
- **日志目录** 日志写入 `~/Library/Logs/LiangHua/lianghua.log`（macOS 标准路径），失败时回退 `~/.lianghua/logs`。
- **配置项** 新增 `LH_AKSHARE_PROXY_GATEWAY`、`LH_LOG_DIR`、`LH_DUCKDB_VACUUM_INTERVAL_HOURS` 等环境变量。
- **README** 新增项目架构、数据源、故障排查文档。

### Changed
- **AKShare 代理配置** 从硬编码 `101.201.173.125` 改为通过 `Settings` 类读取，可通过 `LH_AKSHARE_PROXY_GATEWAY` 覆盖。

## [1.0.0] - 2026-06-13

### Added
- 首次构建：Electron 42 + Vue 3 + FastAPI 完整桌面应用
- 7 种回测策略：双低、低溢价、动量、多因子、松冈七维、玄机十二因子、行业轮动
- 8 类公开数据源：THS、Sina、Tencent、Baidu、THS 财务摘要、Jisilu、ETF、EastMoney
- WebSocket 实时行情 + 选股信号推送
- 自动交易引擎（券商模拟）
- AI 助手集成（OpenAI/DeepSeek/Anthropic）
