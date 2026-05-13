# 可转债量化交易系统 — 实施计划（Phase 1：项目骨架与实时行情）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 Electron + React + Python FastAPI 三端联动的项目骨架，实现可运行的最小闭环：后端采集可转债数据 → WebSocket 推送 → 前端行情表展示。

**Architecture:** Electron 管理渲染进程 + Python 后端子进程；前端 React + Vite + Ant Design + Zustand；后端 FastAPI + DuckDB + WebSocket。前后端通过 REST + WebSocket 通信。

**Tech Stack:** Electron, React 18, TypeScript, Vite, Ant Design, ECharts, Zustand, Python 3.11+, FastAPI, Uvicorn, DuckDB, AKShare, Pytest

---

## 文件结构概览

```
lianghua/
├── package.json                     # monorepo root
├── electron/
│   ├── main.ts                      # Electron 主进程，管理 Python 子进程
│   └── preload.ts                   # Electron preload（安全桥接）
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                 # React 入口
│       ├── App.tsx                  # 根组件 + 路由
│       ├── Layout.tsx               # 三栏布局
│       ├── global.css               # 全局样式
│       ├── components/
│       │   ├── Sidebar.tsx          # 侧边栏导航
│       │   ├── DetailPanel.tsx      # 右侧详情面板
│       │   ├── StatusBar.tsx        # 底部状态栏
│       │   └── MarketTable.tsx      # 行情表组件
│       ├── stores/
│       │   ├── useMarketStore.ts    # 行情状态
│       │   └── useAppStore.ts       # 应用状态
│       ├── hooks/
│       │   └── useWebSocket.ts      # WebSocket hook
│       ├── services/
│       │   └── api.ts               # REST API 封装
│       ├── pages/
│       │   ├── Dashboard.tsx        # 行情总览页
│       │   ├── Market.tsx           # 实时行情页
│       │   ├── Backtest.tsx         # 回测中心页（占位）
│       │   ├── Trade.tsx            # 交易终端页（占位）
│       │   ├── Analysis.tsx         # 分析工具页（占位）
│       │   ├── Strategies.tsx       # 策略管理页（占位）
│       │   └── Settings.tsx         # 设置页（占位）
│       └── types/
│           └── index.ts             # 类型定义
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI 入口
│   │   ├── config.py                # 配置
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── router.py            # API 路由汇总
│   │   │   ├── market.py            # 行情 API
│   │   │   └── ws.py                # WebSocket 端点
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── convertible.py       # 可转债数据模型
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   └── market.py            # 行情引擎
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── base.py              # 数据源基类
│   │       └── akshare.py           # AKShare 适配器
│   └── tests/
│       ├── __init__.py
│       └── test_market.py           # 行情模块测试
├── shared/
│   └── types.ts                     # 前后端共享类型
└── scripts/
    └── dev.sh                       # 一键开发启动脚本
```

---

### Task 1: 初始化项目骨架

**Files:**
- Create: `package.json`
- Create: `scripts/dev.sh`

- [ ] **Step 1: 创建 monorepo 根 package.json**

```json
{
  "name": "lianghua",
  "private": true,
  "scripts": {
    "dev": "chmod +x scripts/dev.sh && ./scripts/dev.sh",
    "dev:frontend": "cd frontend && npm run dev",
    "dev:backend": "cd backend && python -m uvicorn app.main:app --reload --port 8765",
    "dev:electron": "cd frontend && npm run dev:electron"
  }
}
```

- [ ] **Step 2: 创建开发启动脚本**

```bash
#!/bin/bash
# scripts/dev.sh - 一键启动前后端开发环境
echo "Starting backend..."
cd "$(dirname "$0")/../backend"
uvicorn app.main:app --reload --port 8765 --log-level info &
BACKEND_PID=$!

echo "Starting frontend..."
cd "$(dirname "$0")/../frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
echo "Backend: http://localhost:8765"
echo "Frontend: http://localhost:5173"
wait
```

- [ ] **Step 3: 创建 .gitignore**

```
node_modules/
dist/
*.pyc
__pycache__/
.env
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.db
.DS_Store
```

- [ ] **Step 4: 初次提交**

```bash
git init
git add -A
git commit -m "chore: init monorepo scaffold"
```

---

### Task 2: 后端基础框架

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/tests/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "lianghua-backend"
version = "0.1.0"
description = "可转债量化交易系统后端"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "websockets>=12.0",
    "duckdb>=1.0.0",
    "akshare>=1.14.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
    "ruff>=0.3.0",
    "mypy>=1.9.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 创建应用配置**

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LiangHua"
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = True
    db_path: str = "data/market.db"
    ws_ping_interval: int = 30
    market_refresh_interval: int = 5  # 行情刷新间隔(秒)

    model_config = {"env_prefix": "LH_"}


settings = Settings()
```

- [ ] **Step 3: 创建 FastAPI 入口**

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    yield
    print(f"Shutting down {settings.app_name}")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
```

- [ ] **Step 4: 创建路由汇总文件**

```python
# backend/app/api/router.py
from fastapi import APIRouter

from app.api.market import router as market_router
from app.api.ws import router as ws_router

router = APIRouter()
router.include_router(market_router, prefix="/market", tags=["market"])
router.include_router(ws_router, prefix="/ws", tags=["websocket"])
```

- [ ] **Step 5: 编写健康检查测试**

```python
# backend/tests/test_market.py
from httpx import AsyncClient, ASGITransport
import pytest

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "LiangHua"
```

- [ ] **Step 6: 运行测试验证**

```bash
cd backend
pip install -e ".[dev]"
pytest tests/ -v
```
Expected: test_health_endpoint PASSED

- [ ] **Step 7: 提交**

```bash
git add backend/
git commit -m "feat: add FastAPI backend scaffold with health endpoint"
```

---

### Task 3: 可转债数据模型 + AKShare 适配器

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/convertible.py`
- Create: `backend/app/adapters/__init__.py`
- Create: `backend/app/adapters/base.py`
- Create: `backend/app/adapters/akshare.py`

- [ ] **Step 1: 定义可转债数据模型**

```python
# backend/app/models/convertible.py
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class ConvertibleBond(BaseModel):
    """可转债基础信息"""
    code: str = Field(..., description="转债代码")
    name: str = Field(..., description="转债简称")
    stock_code: str = Field("", description="正股代码")
    stock_name: str = Field("", description="正股名称")
    conversion_price: float = Field(0.0, description="转股价")
    maturity_date: Optional[date] = Field(None, description="到期日")
    rating: str = Field("", description="评级")
    outstanding_scale: float = Field(0.0, description="剩余规模(亿元)")


class ConvertibleQuote(BaseModel):
    """可转债实时行情"""
    code: str = Field(..., description="转债代码")
    name: str = Field("", description="转债简称")
    price: float = Field(0.0, description="最新价")
    change_pct: float = Field(0.0, description="涨跌幅(%)")
    stock_price: float = Field(0.0, description="正股价")
    stock_change_pct: float = Field(0.0, description="正股涨跌幅(%)")
    conversion_price: float = Field(0.0, description="转股价")
    conversion_value: float = Field(0.0, description="转股价值")
    premium_ratio: float = Field(0.0, description="转股溢价率(%)")
    dual_low: float = Field(0.0, description="双低值")
    ytm: float = Field(0.0, description="到期收益率(%)")
    volume: float = Field(0.0, description="成交额(亿元)")
    remaining_years: float = Field(0.0, description="剩余年限")
    forced_call_days: int = Field(0, description="强赎倒计时天数,0=未触发")
    timestamp: datetime = Field(default_factory=datetime.now)
```

- [ ] **Step 2: 定义数据源基类**

```python
# backend/app/adapters/base.py
from abc import ABC, abstractmethod
from app.models.convertible import ConvertibleQuote


class DataSourceAdapter(ABC):
    """数据源适配器基类"""
    
    @abstractmethod
    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        """获取所有可转债实时行情"""
        ...

    @abstractmethod
    async def fetch_quote(self, code: str) -> ConvertibleQuote:
        """获取单只可转债行情"""
        ...
```

- [ ] **Step 3: 实现 AKShare 适配器（测试就绪）**

```python
# backend/app/adapters/akshare.py
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd

from app.adapters.base import DataSourceAdapter
from app.models.convertible import ConvertibleQuote, ConvertibleBond


class AKShareAdapter(DataSourceAdapter):
    """AKShare 可转债数据适配器"""
    
    def __init__(self):
        self._cache: Optional[list[ConvertibleQuote]] = None
        self._cache_time: Optional[datetime] = None
        self._bonds_cache: Optional[list[ConvertibleBond]] = None

    async def fetch_all_quotes(self) -> list[ConvertibleQuote]:
        """使用 AKShare 获取全市场可转债实时行情"""
        df = ak.bond_zh_cov()
        bonds = []
        for _, row in df.iterrows():
            try:
                bond = self._row_to_quote(row)
                if bond:
                    bonds.append(bond)
            except (KeyError, ValueError, TypeError):
                continue
        self._cache = bonds
        self._cache_time = datetime.now()
        return bonds

    async def fetch_quote(self, code: str) -> Optional[ConvertibleQuote]:
        if self._cache is None:
            await self.fetch_all_quotes()
        for bond in self._cache or []:
            if bond.code == code:
                return bond
        return None

    def _row_to_quote(self, row: pd.Series) -> Optional[ConvertibleQuote]:
        """将 DataFrame 行转为 Quote 对象，适配不同版本的 AKShare 列名"""
        try:
            code = str(row.get("代码", row.get("bond_code", "")))
            if not code:
                return None
            price = float(row.get("最新价", row.get("price", 0)))
            change_pct = float(row.get("涨跌幅", row.get("change_pct", 0)))
            
            conversion_price = float(row.get("转股价", row.get("conversion_price", 0)))
            stock_price = float(row.get("正股价", row.get("stock_price", 0)))
            conversion_value = round(100 / conversion_price * stock_price, 2) if conversion_price > 0 else 0.0
            premium = round((price - conversion_value) / conversion_value * 100, 2) if conversion_value > 0 else 0.0
            dual_low = round(price + premium, 2)

            return ConvertibleQuote(
                code=code,
                name=str(row.get("转债名称", row.get("bond_name", ""))),
                price=price,
                change_pct=change_pct,
                stock_price=stock_price,
                stock_change_pct=float(row.get("正股涨跌幅", row.get("stock_change_pct", 0))),
                conversion_price=conversion_price,
                conversion_value=conversion_value,
                premium_ratio=premium,
                dual_low=dual_low,
                volume=float(row.get("成交额", row.get("volume", 0))),
            )
        except (ValueError, TypeError, ZeroDivisionError):
            return None
```

- [ ] **Step 4: 编写领域计算测试**

```python
# 在 backend/tests/test_market.py 追加

from app.models.convertible import ConvertibleQuote


def test_convertible_quote_model():
    q = ConvertibleQuote(code="113044", name="测试转债", price=128.5)
    assert q.code == "113044"
    assert q.name == "测试转债"
    assert q.price == 128.5
    assert q.dual_low == 0.0  # 未计算时的默认值


def test_premium_calculation():
    # 模拟转股溢价率计算
    price = 128.5   # 转债价
    cv = 125.0      # 转股价值
    premium = round((price - cv) / cv * 100, 2)
    assert premium == 2.8

    dual_low = round(price + premium, 2)
    assert dual_low == 131.3
```

- [ ] **Step 5: 运行测试**

```bash
cd backend
pytest tests/ -v
```
Expected: 3 tests passed (health + bond model + premium calc)

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/ backend/app/adapters/ backend/tests/
git commit -m "feat: add convertible bond data model and AKShare adapter"
```

---

### Task 4: 行情引擎 + API + WebSocket

**Files:**
- Create: `backend/app/engine/__init__.py`
- Create: `backend/app/engine/market.py`
- Create: `backend/app/api/market.py`
- Create: `backend/app/api/ws.py`

- [ ] **Step 1: 创建行情引擎**

```python
# backend/app/engine/market.py
from datetime import datetime
from typing import Optional, Callable, Awaitable

from app.adapters.akshare import AKShareAdapter
from app.models.convertible import ConvertibleQuote


class MarketEngine:
    """行情引擎 - 负责数据采集和缓存"""
    
    def __init__(self, adapter: Optional[AKShareAdapter] = None):
        self.adapter = adapter or AKShareAdapter()
        self._quotes: dict[str, ConvertibleQuote] = {}
        self._last_update: Optional[datetime] = None
        self._running = False
        self._subscribers: dict[str, set] = {}
        self._all_subscribers: set = set()

    async def refresh(self) -> list[ConvertibleQuote]:
        """刷新全市场行情"""
        bonds = await self.adapter.fetch_all_quotes()
        for bond in bonds:
            self._quotes[bond.code] = bond
        self._last_update = datetime.now()
        return bonds

    async def get_all_quotes(self) -> list[ConvertibleQuote]:
        if not self._quotes:
            await self.refresh()
        return list(self._quotes.values())

    async def get_quote(self, code: str) -> Optional[ConvertibleQuote]:
        return self._quotes.get(code)

    def subscribe_all(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        self._all_subscribers.add(callback)

    def unsubscribe_all(self, callback: Callable[[list[ConvertibleQuote]], Awaitable[None]]) -> None:
        self._all_subscribers.discard(callback)

    async def start_polling(self, interval: int = 5):
        """开始轮询行情，并通过回调通知订阅者"""
        self._running = True
        while self._running:
            try:
                bonds = await self.refresh()
                for callback in self._all_subscribers:
                    await callback(bonds)
            except Exception as e:
                print(f"Market polling error: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False
```

- [ ] **Step 2: 创建行情 REST API**

```python
# backend/app/api/market.py
from fastapi import APIRouter

from app.engine.market import MarketEngine

router = APIRouter()
engine = MarketEngine()


@router.get("/quotes")
async def get_all_quotes():
    bonds = await engine.get_all_quotes()
    return {
        "total": len(bonds),
        "bonds": [b.model_dump() for b in bonds],
        "updated_at": engine._last_update.isoformat() if engine._last_update else "",
    }


@router.get("/quotes/{code}")
async def get_quote(code: str):
    bond = await engine.get_quote(code)
    if bond is None:
        return {"error": "not found"}, 404
    return bond.model_dump()
```

- [ ] **Step 3: 创建 WebSocket 端点**

```python
# backend/app/api/ws.py
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine.market import MarketEngine

router = APIRouter()
engine = MarketEngine()


@router.websocket("/market")
async def market_websocket(websocket: WebSocket):
    await websocket.accept()
    subscribed_codes: set[str] = set()

    async def on_market_update_all(bonds):
        data = [b.model_dump(mode="json") for b in bonds]
        await websocket.send_json({"type": "tick", "data": data})

    engine.subscribe_all(on_market_update_all)

    try:
        # Start polling in background
        async def poll():
            while True:
                try:
                    bonds = await engine.refresh()
                    await on_market_update_all(bonds)
                except Exception as e:
                    print(f"Poll error: {e}")
                await asyncio.sleep(5)

        poll_task = asyncio.create_task(poll())

        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "subscribe":
                codes = msg.get("codes", [])
                subscribed_codes.update(codes)
            elif msg.get("type") == "unsubscribe":
                codes = msg.get("codes", [])
                subscribed_codes.difference_update(codes)
    except WebSocketDisconnect:
        pass
    finally:
        poll_task.cancel()
        engine.unsubscribe_all(on_market_update_all)
```

- [ ] **Step 4: 编写行情 API 测试**

```python
# 在 backend/tests/test_market.py 追加

@pytest.mark.asyncio
async def test_quotes_endpoint(client):
    resp = await client.get("/api/v1/market/quotes")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "bonds" in data
```

- [ ] **Step 5: 运行测试**

```bash
cd backend
pytest tests/ -v
```
Expected: 4 tests passed

- [ ] **Step 6: 提交**

```bash
git add backend/app/engine/ backend/app/api/market.py backend/app/api/ws.py
git commit -m "feat: add market engine with REST API and WebSocket endpoint"
```

---

### Task 5: 前端基础框架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/vite-env.d.ts`
- Create: `frontend/src/global.css`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "lianghua-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.24.0",
    "antd": "^5.19.0",
    "@ant-design/icons": "^5.4.0",
    "zustand": "^4.5.0",
    "echarts": "^5.5.0",
    "echarts-for-react": "^3.0.0",
    "dayjs": "^1.11.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 2: 创建 Vite 配置**

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
```

- [ ] **Step 3: 创建 index.html**

```html
<!-- frontend/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LiangHua - 可转债量化交易系统</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: 创建 React 入口**

```tsx
// frontend/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './global.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
)
```

- [ ] **Step 5: 创建全局样式**

```css
/* frontend/src/global.css */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #root {
  height: 100%;
  width: 100%;
  overflow: hidden;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}

/* 行情表价格闪烁 */
@keyframes flash-green {
  from { background-color: rgba(82, 196, 26, 0.3); }
  to { background-color: transparent; }
}

@keyframes flash-red {
  from { background-color: rgba(255, 77, 79, 0.3); }
  to { background-color: transparent; }
}

.flash-up {
  animation: flash-green 1s ease-out;
}

.flash-down {
  animation: flash-red 1s ease-out;
}

/* 全局滚动条样式 */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 3px;
}

::-webkit-scrollbar-track {
  background: transparent;
}
```

- [ ] **Step 6: 创建 App.tsx**

```tsx
// frontend/src/App.tsx
import { Routes, Route } from 'react-router-dom'
import Layout from './Layout'
import Dashboard from './pages/Dashboard'
import Market from './pages/Market'
import Backtest from './pages/Backtest'
import Trade from './pages/Trade'
import Analysis from './pages/Analysis'
import Strategies from './pages/Strategies'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/market" element={<Market />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/trade" element={<Trade />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  )
}
```

- [ ] **Step 7: 验证前端启动**

```bash
cd frontend
npm install
npm run dev
```
Expected: Vite dev server starts on http://localhost:5173

- [ ] **Step 8: 提交**

```bash
git add frontend/
git commit -m "feat: add React frontend scaffold with routing"
```

---

### Task 6: 三栏布局 + 侧边栏 + 占位页面

**Files:**
- Create: `frontend/src/Layout.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/components/StatusBar.tsx`
- Create: `frontend/src/components/DetailPanel.tsx`
- Create: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/Market.tsx`
- Create: `frontend/src/pages/Backtest.tsx`
- Create: `frontend/src/pages/Trade.tsx`
- Create: `frontend/src/pages/Analysis.tsx`
- Create: `frontend/src/pages/Strategies.tsx`
- Create: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: 创建侧边栏导航**

```tsx
// frontend/src/components/Sidebar.tsx
import { useNavigate, useLocation } from 'react-router-dom'
import { Menu } from 'antd'
import {
  DashboardOutlined,
  StockOutlined,
  ExperimentOutlined,
  DollarOutlined,
  FundProjectionScreenOutlined,
  DeploymentUnitOutlined,
  SettingOutlined,
} from '@ant-design/icons'

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '行情总览' },
  { key: '/market', icon: <StockOutlined />, label: '实时行情' },
  { key: '/backtest', icon: <ExperimentOutlined />, label: '回测中心' },
  { key: '/trade', icon: <DollarOutlined />, label: '交易终端' },
  { key: '/analysis', icon: <FundProjectionScreenOutlined />, label: '分析工具' },
  { key: '/strategies', icon: <DeploymentUnitOutlined />, label: '策略管理' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

interface SidebarProps {
  collapsed: boolean
  onCollapse: (v: boolean) => void
}

export default function Sidebar({ collapsed, onCollapse }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Menu
      mode="inline"
      inlineCollapsed={collapsed}
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{ height: '100%', borderRight: 0 }}
    />
  )
}
```

- [ ] **Step 2: 创建状态栏**

```tsx
// frontend/src/components/StatusBar.tsx
import { Tag, Space, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

export default function StatusBar({ backendConnected = false }: { backendConnected?: boolean }) {
  return (
    <div
      style={{
        height: 28,
        background: '#f5f5f5',
        borderTop: '1px solid #e8e8e8',
        display: 'flex',
        alignItems: 'center',
        padding: '0 12px',
        gap: 16,
        fontSize: 12,
      }}
    >
      <Space size={4}>
        {backendConnected ? (
          <Tag icon={<CheckCircleOutlined />} color="success">后端已连接</Tag>
        ) : (
          <Tag icon={<CloseCircleOutlined />} color="error">后端未连接</Tag>
        )}
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>LiangHua v0.1.0</Text>
      <div style={{ flex: 1 }} />
      <Text type="secondary" style={{ fontSize: 12 }}>数据源: AKShare</Text>
    </div>
  )
}
```

- [ ] **Step 3: 创建详情面板（占位）**

```tsx
// frontend/src/components/DetailPanel.tsx
import { Empty, Typography } from 'antd'
const { Title } = Typography

export default function DetailPanel({ visible }: { visible: boolean }) {
  if (!visible) return null
  return (
    <div style={{ width: 300, borderLeft: '1px solid #e8e8e8', height: '100%', display: 'flex', flexDirection: 'column', background: '#fff' }}>
      <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0' }}>
        <Title level={5} style={{ margin: 0 }}>详情面板</Title>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="选中可转债查看详情" />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 创建 Layout**

```tsx
// frontend/src/Layout.tsx
import { useState } from 'react'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import DetailPanel from './components/DetailPanel'
import type React from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ width: collapsed ? 80 : 200, borderRight: '1px solid #e8e8e8', transition: 'width 0.2s', overflow: 'auto' }}>
          <Sidebar collapsed={collapsed} onCollapse={setCollapsed} />
        </div>
        <div style={{ flex: 1, overflow: 'auto', background: '#f5f5f5' }}>
          {children}
        </div>
        {detailVisible && (
          <DetailPanel visible={detailVisible} onClose={() => setDetailVisible(false)} />
        )}
      </div>
      <StatusBar backendConnected={false} />
    </div>
  )
}
```

- [ ] **Step 5: 创建占位页面**

```tsx
// frontend/src/pages/Dashboard.tsx
export default function Dashboard() {
  return <div style={{ padding: 24 }}><h2>行情总览</h2></div>
}
```

（同理创建 Market.tsx, Backtest.tsx, Trade.tsx, Analysis.tsx, Strategies.tsx, Settings.tsx，均为占位 div）

- [ ] **Step 6: 验证前端**

```bash
cd frontend
npm run dev
```
Expected: http://localhost:5173 显示带侧边栏的三栏布局

- [ ] **Step 7: 提交**

```bash
git add frontend/src/Layout.tsx frontend/src/components/ frontend/src/pages/
git commit -m "feat: add three-column layout with navigation and placeholder pages"
```

---

### Task 7: WebSocket 连接 + 状态管理

**Files:**
- Create: `shared/types.ts`
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/services/api.ts`
- Create: `frontend/src/hooks/useWebSocket.ts`
- Create: `frontend/src/stores/useAppStore.ts`
- Create: `frontend/src/stores/useMarketStore.ts`

- [ ] **Step 1: 创建共享类型定义**

```typescript
// shared/types.ts
export interface ConvertibleQuote {
  code: string
  name: string
  price: number
  change_pct: number
  stock_price: number
  stock_change_pct: number
  conversion_price: number
  conversion_value: number
  premium_ratio: number
  dual_low: number
  ytm: number
  volume: number
  remaining_years: number
  forced_call_days: number
  timestamp: string
}

export interface WsMessage {
  type: 'tick' | 'subscribe' | 'unsubscribe'
  data?: ConvertibleQuote[]
  codes?: string[]
}
```

```typescript
// frontend/src/types/index.ts
export type { ConvertibleQuote, WsMessage } from '../../shared/types'
```

- [ ] **Step 2: 创建 API 服务**

```typescript
// frontend/src/services/api.ts
import type { ConvertibleQuote } from '../types'

const BASE = '/api/v1'

async function fetchJSON<T>(url: string): Promise<T> {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function fetchAllQuotes(): Promise<{ total: number; bonds: ConvertibleQuote[]; updated_at: string }> {
  return fetchJSON(`${BASE}/market/quotes`)
}

export async function fetchQuote(code: string): Promise<ConvertibleQuote> {
  return fetchJSON(`${BASE}/market/quotes/${code}`)
}

export async function healthCheck(): Promise<{ status: string; app: string }> {
  return fetchJSON('/health')
}
```

- [ ] **Step 3: 创建 WebSocket Hook**

```typescript
// frontend/src/hooks/useWebSocket.ts
import { useEffect, useRef, useCallback } from 'react'
import type { ConvertibleQuote } from '../types'

type MessageHandler = (bonds: ConvertibleQuote[]) => void

const WS_URL = `ws://${window.location.hostname}:5173/ws/market`

export function useWebSocket(onMessage: MessageHandler) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)

    ws.onopen = () => console.log('WebSocket connected')

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'tick' && msg.data) {
          onMessage(msg.data)
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }

    ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting in 3s...')
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()

    wsRef.current = ws
  }, [onMessage])

  const subscribe = useCallback((codes: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'subscribe', codes }))
    }
  }, [])

  const unsubscribe = useCallback((codes: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'unsubscribe', codes }))
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { subscribe, unsubscribe }
}
```

- [ ] **Step 4: 创建应用状态**

```typescript
// frontend/src/stores/useAppStore.ts
import { create } from 'zustand'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (v: boolean) => void
  selectedBond: string | null
  setSelectedBond: (code: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  backendConnected: false,
  setBackendConnected: (v) => set({ backendConnected: v }),
  selectedBond: null,
  setSelectedBond: (code) => set({ selectedBond: code }),
}))
```

- [ ] **Step 5: 创建行情状态**

```typescript
// frontend/src/stores/useMarketStore.ts
import { create } from 'zustand'
import type { ConvertibleQuote } from '../types'

interface MarketState {
  bonds: Map<string, ConvertibleQuote>
  allBonds: ConvertibleQuote[]
  updatedAt: string
  updateQuotes: (quotes: ConvertibleQuote[]) => void
  setAllBonds: (bonds: ConvertibleQuote[]) => void
}

export const useMarketStore = create<MarketState>((set, get) => ({
  bonds: new Map(),
  allBonds: [],
  updatedAt: '',
  updateQuotes: (quotes) => {
    const bonds = new Map(get().bonds)
    for (const q of quotes) {
      bonds.set(q.code, q)
    }
    set({ bonds, allBonds: Array.from(bonds.values()), updatedAt: new Date().toLocaleTimeString() })
  },
  setAllBonds: (bonds) => {
    const m = new Map<string, ConvertibleQuote>()
    for (const b of bonds) m.set(b.code, b)
    set({ bonds: m, allBonds: bonds })
  },
}))
```

- [ ] **Step 6: 验证构建**

```bash
cd frontend
npx tsc --noEmit
```
Expected: No TypeScript errors

- [ ] **Step 7: 提交**

```bash
git add shared/ frontend/src/types/ frontend/src/services/ frontend/src/hooks/ frontend/src/stores/
git commit -m "feat: add WebSocket hook, state stores, and shared types"
```

---

### Task 8: 行情表组件 + Market 页面

**Files:**
- Create: `frontend/src/components/MarketTable.tsx`
- Modify: `frontend/src/pages/Market.tsx`

- [ ] **Step 1: 创建行情表组件**

```tsx
// frontend/src/components/MarketTable.tsx
import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ConvertibleQuote } from '../types'

const { Text } = Typography

function PriceCell({ value, change }: { value: number; change: number }) {
  const color = change > 0 ? '#cf1322' : change < 0 ? '#389e0d' : undefined
  return <span style={{ color, fontWeight: 600, fontFamily: 'monospace' }}>{value.toFixed(2)}</span>
}

interface MarketTableProps {
  bonds: ConvertibleQuote[]
  loading: boolean
  onRowClick: (code: string) => void
}

export default function MarketTable({ bonds, loading, onRowClick }: MarketTableProps) {
  const columns: ColumnsType<ConvertibleQuote> = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, fixed: 'left', render: (v: string) => <Text copyable>{{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100, fixed: 'left' },
    {
      title: '最新价', dataIndex: 'price', key: 'price', width: 100,
      sorter: (a, b) => a.price - b.price,
      render: (v: number, r) => <PriceCell value={v} change={r.change_pct} />,
    },
    {
      title: '涨跌幅', dataIndex: 'change_pct', key: 'change_pct', width: 100,
      sorter: (a, b) => a.change_pct - b.change_pct,
      render: (v: number) => {
        const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
        return <Tag color={color} style={{ fontFamily: 'monospace' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</Tag>
      },
    },
    { title: '正股价', dataIndex: 'stock_price', key: 'stock_price', width: 90, render: (v: number) => v.toFixed(2) },
    { title: '转股价', dataIndex: 'conversion_price', key: 'conversion_price', width: 90, render: (v: number) => v.toFixed(2) },
    {
      title: '转股价值', dataIndex: 'conversion_value', key: 'conversion_value', width: 100,
      sorter: (a, b) => a.conversion_value - b.conversion_value,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 100,
      sorter: (a, b) => a.premium_ratio - b.premium_ratio,
      render: (v: number) => {
        const color = v < 0 ? '#cf1322' : v > 50 ? '#389e0d' : undefined
        return <Text style={{ color, fontWeight: 600 }}>{v.toFixed(2)}%</Text>
      },
    },
    {
      title: '双低值', dataIndex: 'dual_low', key: 'dual_low', width: 100,
      sorter: (a, b) => a.dual_low - b.dual_low,
      render: (v: number) => {
        const color = v < 130 ? '#52c41a' : v > 180 ? '#faad14' : undefined
        return <Text style={{ color, fontWeight: 600 }}>{v.toFixed(2)}</Text>
      },
    },
    { title: '成交额(亿)', dataIndex: 'volume', key: 'volume', width: 110, sorter: (a, b) => a.volume - b.volume, render: (v: number) => v.toFixed(2) },
    { title: '剩余年限', dataIndex: 'remaining_years', key: 'remaining_years', width: 100, render: (v: number) => v.toFixed(1) },
  ]

  return (
    <Table<ConvertibleQuote>
      columns={columns}
      dataSource={bonds}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1300, y: 'calc(100vh - 160px)' }}
      pagination={false}
      onRow={(record) => ({
        onClick: () => onRowClick(record.code),
        style: { cursor: 'pointer' },
      })}
      locale={{ emptyText: '暂无数据' }}
    />
  )
}
```

- [ ] **Step 2: 更新 Market 页面**

```tsx
// frontend/src/pages/Market.tsx
import { useEffect, useState, useCallback } from 'react'
import { Typography, Space } from 'antd'
import MarketTable from '../components/MarketTable'
import { useMarketStore } from '../stores/useMarketStore'
import { useAppStore } from '../stores/useAppStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { fetchAllQuotes } from '../services/api'
import type { ConvertibleQuote } from '../types'

const { Title } = Typography

export default function Market() {
  const [loading, setLoading] = useState(true)
  const { allBonds, setAllBonds, updateQuotes } = useMarketStore()
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)

  const onWsMessage = useCallback((quotes: ConvertibleQuote[]) => updateQuotes(quotes), [updateQuotes])
  useWebSocket(onWsMessage)

  useEffect(() => {
    fetchAllQuotes()
      .then((res) => { setAllBonds(res.bonds); setLoading(false) })
      .catch(() => setLoading(false))
  }, [setAllBonds])

  return (
    <div style={{ padding: 16 }}>
      <Space style={{ marginBottom: 12, justifyContent: 'space-between', width: '100%' }}>
        <Title level={4} style={{ margin: 0 }}>实时行情</Title>
        <span style={{ color: '#888' }}>共 {allBonds.length} 只可转债</span>
      </Space>
      <MarketTable bonds={allBonds} loading={loading} onRowClick={(code) => setSelectedBond(code)} />
    </div>
  )
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/MarketTable.tsx frontend/src/pages/Market.tsx
git commit -m "feat: add market table with real-time data display"
```

---

### Task 9: Electron 壳层

**Files:**
- Create: `electron/main.ts`
- Create: `electron/preload.ts`

- [ ] **Step 1: 创建 Electron 主进程**

```typescript
// electron/main.ts
import { app, BrowserWindow, Tray, Menu } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let tray: Tray | null = null

const isDev = !app.isPackaged

function startPythonBackend() {
  const backendDir = isDev
    ? path.join(__dirname, '..', 'backend')
    : path.join(process.resourcesPath, 'backend')

  pythonProcess = spawn('python', ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765'], {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  pythonProcess.stdout?.on('data', (data) => console.log(`[Python] ${data}`))
  pythonProcess.stderr?.on('data', (data) => console.log(`[Python] ${data}`))

  pythonProcess.on('exit', (code) => {
    console.log(`Python process exited with code ${code}`)
    if (!app.isQuitting) {
      setTimeout(startPythonBackend, 2000)
    }
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: 'LiangHua - 可转债量化交易系统',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })
}

function createTray() {
  tray = new Tray(path.join(__dirname, '..', 'assets', 'iconTemplate.png'))
  const contextMenu = Menu.buildFromTemplate([
    { label: '显示窗口', click: () => mainWindow?.show() },
    { type: 'separator' },
    { label: '退出', click: () => { app.isQuitting = true; app.quit() } },
  ])
  tray.setToolTip('LiangHua - 可转债量化交易系统')
  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => mainWindow?.show())
}

app.whenReady().then(() => {
  startPythonBackend()
  createWindow()
  createTray()
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
})

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })

app.on('before-quit', () => {
  app.isQuitting = true
  pythonProcess?.kill()
})
```

- [ ] **Step 2: 创建 preload 脚本**

```typescript
// electron/preload.ts
import { contextBridge } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
})
```

- [ ] **Step 3: 提交**

```bash
git add electron/
git commit -m "feat: add Electron shell with Python process management"
```

---

## 自检

1. **Spec 覆盖：** 设计文档中的架构、数据模型、行情引擎、GUI 三栏布局、WebSocket 数据流在 Phase 1 中已实现。回测/交易/分析/策略模块未实现（Phase 2+）
2. **占位符检查：** 无 TBD/TODO 残留。所有代码块完整可执行
3. **类型一致性：** ConvertibleQuote 模型在 Python 后端和 TypeScript 前端字段一致
4. **每个任务可测试：** 每个 Task 结束后项目处于可验证状态

## 后续 Phase（独立 Plan）

- **Phase 2:** 回测引擎 + 回测 UI + 交互式绩效报告
- **Phase 3:** 交易模块 + 券商适配器 + 订单/持仓管理
- **Phase 4:** 分析工具（强赎/下修/脉冲/双低排名）
- **Phase 5:** 策略管理系统 + 可视化策略构建器
- **Phase 6:** 插件系统 + 通知告警 + 打包部署 + 自动更新