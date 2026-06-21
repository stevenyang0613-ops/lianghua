# LiangHua (量化) 可转债量化分析终端

> 桌面端 + 后端的可转债 (Convertible Bond) 量化分析系统，覆盖行情、回测、评分、风控、自动交易等全流程。

## 🚀 快速开始

### 用户（双击启动）
```bash
# 已打包版本（推荐）
open ~/Desktop/LiangHua.app
```

### 开发（从源码启动）
```bash
# 1. 后端
cd backend
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# 2. 前端
cd frontend
npm install
npm run dev

# 3. Electron (新终端)
cd electron
npm install
npm run start
```

## 📐 架构

```
┌─────────────────────┐
│  Electron 主进程     │ ← 端口 8766 (前端 HTTP server)
│  (TypeScript)        │ ← 端口 8765 (后端 HTTP proxy)
└──────────┬──────────┘
           │ spawn()
           ▼
┌─────────────────────┐
│  Python 后端        │ ← 端口 8765 (uvicorn)
│  (FastAPI + akshare)│
│  DuckDB 存储        │
└──────────┬──────────┘
           │ HTTP/WS
           ▼
┌─────────────────────┐
│  Vue 3 + Vite 前端  │ ← http://127.0.0.1:8766
│  (Ant Design + ECharts)│
└─────────────────────┘
```

## 📊 数据源（全部真实，按可靠性排序）

| 优先级 | 名称 | 用途 | 备注 |
|-------|------|------|------|
| ① | **THS (同花顺)** `ak.bond_zh_cov_info_ths()` | 转债列表、转股价、到期时间 | 主力数据源 |
| ② | **Sina (新浪)** `ak.bond_zh_hs_cov_spot()` | 实时行情、涨跌幅、成交额 | 速度极快 |
| ③ | **Tencent (腾讯)** `ak.stock_zh_a_hist_tx()` | A 股日 K 线 | 备用 K 线源 |
| ④ | **Baidu (百度)** `ak.stock_zh_valuation_baidu()` | PE/PB 估值 | 多线程 ~0.4s/只 |
| ⑤ | **THS 财务摘要** `ak.stock_financial_abstract_ths()` | EPS/BPS 财务数据 | 最后兜底 |
| ⑥ | **Jisilu (集思录)** `ak.bond_cb_jsl()` | 溢价率、双低、评级 | 双低策略核心 |
| ⑦ | **AKShare 基金 ETF** `ak.fund_etf_hist_em()` | 行业 ETF 历史 | 行业轮动 |
| ⑧ | **EastMoney (东方财富)** 直连 API | 财务数据、公告 | 通过代理访问 |

> ⚠ **架构原则**：所有回测/行情数据均来自上述 8 类公开 API, 不使用任何合成/假数据。  
> 当所有源都失败时, 回测会返回空结果并在 `data-freshness` 接口中报告 `stale: true`。

## 🛠 技术栈

- **桌面端**: Electron 42 + electron-builder
- **后端**: Python 3.12 + FastAPI + uvicorn + DuckDB + akshare
- **前端**: Vue 3 + TypeScript + Vite + Ant Design 5 + ECharts 5
- **数据**: DuckDB (行情) + SQLite (AI/认证) + 内存缓存

## 📦 构建

```bash
# 后端二进制 (PyInstaller)
cd backend
.venv/bin/pyinstaller lianghua-backend.spec
# 产物: backend/dist/lianghua-backend/lianghua-backend

# 前端
cd frontend
npm run build
# 产物: frontend/dist/

# Electron 桌面应用
cd electron
npm run dist
# 产物: electron/release/mac-arm64/LiangHua.app + .dmg
```

## ⚙ 配置

通过环境变量（`LH_` 前缀）覆盖默认值。完整列表见 `backend/app/config.py`:

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LH_AKSHARE_PROXY_GATEWAY` | `101.201.173.125` | AKShare 代理网关（解锁东财 API） |
| `LH_AKSHARE_PROXY_ENABLED` | `1` | 是否启用代理 |
| `LH_AKSHARE_PROXY_RETRY` | `15` | 代理重试次数 |
| `LH_LOG_DIR` | `~/Library/Logs/LiangHua` | 后端日志目录 |
| `LH_LOG_LEVEL` | `INFO` | 日志级别 |
| `LH_DUCKDB_VACUUM_INTERVAL_HOURS` | `24` | DuckDB VACUUM 间隔 |
| `LH_DISABLE_UPDATER` | `1` | 禁用自动更新 |

## 🐛 故障排查

### 双击 `LiangHua.app` 无反应
1. 打开 `~/Library/Logs/LiangHua/lianghua.log` 查看后端日志
2. 确认 `~/Library/Logs/LiangHua/` 目录可写
3. 终端运行 `~/Desktop/LiangHua.app/Contents/MacOS/LiangHua` 看实时输出

### 后端启动失败
```bash
# 端口 8765 被占用
lsof -i :8765
pkill -9 -f lianghua-backend

# DuckDB 锁冲突
pkill -9 -f lianghua-backend
# 删 WAL 文件
rm -f ~/.lianghua/market.db.wal
```

### 回测中心无数据
检查 `data-freshness` 接口:
```bash
curl http://127.0.0.1:8765/api/v1/backtest/data-freshness
# 期望: available: true, latest_date: <今天>
```

如果 `stale: true`, 需要等待 6-10 分钟（AKShare 多源数据首次加载完成）。

## 📂 目录结构

```
lianghua/
├── backend/                 # Python 后端
│   ├── app/                # 应用代码
│   │   ├── adapters/       # 数据适配器 (akshare, broker_sim)
│   │   ├── api/            # FastAPI 路由
│   │   ├── engine/         # 业务引擎 (market, storage, scheduler)
│   │   ├── models/         # 数据模型
│   │   ├── strategies/     # 策略实现 (7 种)
│   │   └── xb_strategy/    # 高级策略 (西部七维、璇玑十二因子)
│   ├── data/               # 数据适配器 (eastmoney, cninfo, ths, wind)
│   ├── lianghua-backend.spec
│   └── dist/               # PyInstaller 输出
├── frontend/               # Vue 3 前端
│   ├── src/
│   │   ├── pages/          # 页面 (Backtest, Market, ScoreRanking, ...)
│   │   ├── components/     # 组件
│   │   ├── services/       # API 客户端
│   │   └── stores/         # Pinia 状态
│   └── dist/               # Vite 输出
├── electron/               # Electron 桌面
│   ├── main.ts             # 主进程
│   ├── preload.ts          # preload 脚本
│   └── dist/               # TS 编译输出
├── release/                # electron-builder 输出
│   ├── mac-arm64/LiangHua.app
│   └── LiangHua-1.0.0.dmg
└── AGENTS.md               # AI 代理协作规范
```

## 📜 许可

仅供学习和研究使用。投资有风险，决策需谨慎。
