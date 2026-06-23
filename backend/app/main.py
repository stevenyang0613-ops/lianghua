"""
LiangHua Backend - FastAPI Application
"""

import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# SSL 证书修复：必须在所有网络库 import 之前设置
# PyInstaller 打包后 Python 找不到系统 CA 证书
def _fix_ssl_certs():
    try:
        import certifi
        cert_path = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', cert_path)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', cert_path)
        return
    except ImportError:
        pass
    macos_cert = '/etc/ssl/cert.pem'
    if os.path.isfile(macos_cert):
        os.environ.setdefault('SSL_CERT_FILE', macos_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', macos_cert)
        return
    brew_cert = '/opt/homebrew/etc/openssl@3/cert.pem'
    if os.path.isfile(brew_cert):
        os.environ.setdefault('SSL_CERT_FILE', brew_cert)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', brew_cert)

_fix_ssl_certs()

# 安装AKShare代理补丁(解锁东方财富API) — 必须在任何akshare/requests调用之前
# 配置从 Settings 读取, 可通过环境变量 LH_AKSHARE_PROXY_GATEWAY 等覆盖
from app.config import settings as _settings
_AKSHARE_PROXY_GATEWAY = _settings.AKSHARE_PROXY_GATEWAY
_AKSHARE_PROXY_TOKEN = _settings.AKSHARE_PROXY_TOKEN
_AKSHARE_PROXY_ENABLED = _settings.AKSHARE_PROXY_ENABLED
_AKSHARE_PROXY_RETRY = _settings.AKSHARE_PROXY_RETRY
_HOOK_DOMAINS = [
    "push2.eastmoney.com",
    "push2his.eastmoney.com",
    "emweb.securities.eastmoney.com",
    "datacenter.eastmoney.com",
    "82.push2.eastmoney.com",
    "17.push2.eastmoney.com",
    "np-anotice.eastmoney.com",
    "push1.eastmoney.com",
    "push1his.eastmoney.com",
]
if _AKSHARE_PROXY_ENABLED:
    try:
        import akshare_proxy_patch
        akshare_proxy_patch.install_patch(
            _AKSHARE_PROXY_GATEWAY,
            auth_token=_AKSHARE_PROXY_TOKEN,
            retry=_AKSHARE_PROXY_RETRY,
            hook_domains=_HOOK_DOMAINS,
        )
        print(f"[Main] AKShare proxy patch installed (gateway={_AKSHARE_PROXY_GATEWAY}, retry={_AKSHARE_PROXY_RETRY})")
        # 提示用户：若使用硬编码/demo token，East Money 接口可能授权失败
        if not _AKSHARE_PROXY_TOKEN or len(_AKSHARE_PROXY_TOKEN) < 12:
            print("[Main] WARNING: AKSHARE_PROXY_TOKEN looks empty/demo; East Money APIs may fail. Set LH_AKSHARE_PROXY_TOKEN to a valid token.")
    except Exception as e:
        print(f"[Main] AKShare proxy patch install failed: {e}")
else:
    if _settings.debug:
        print("[Main] AKShare proxy patch DISABLED via LH_AKSHARE_PROXY_ENABLED=0")

# 模块级引用 — 供 factor_data_source 等模块导入
market_engine = None  # type: ignore

# ===== DuckDB 单实例检查 =====
def _check_duckdb_lock(db_path: str) -> None:
    """
    启动前检查 DuckDB 是否被其他进程占用。
    自动尝试清理锁冲突，全部失败才 exit 1。
    """
    import sys as _sys
    import subprocess as _sb
    import time as _tm
    lock_path = db_path + ".lock"
    wal_path = db_path + ".wal"
    
    if not Path(db_path).exists():
        return  # 数据库不存在, 无需检查
    
    def _try_auto_cleanup():
        """自动查找并杀死持有DuckDB锁的进程"""
        print(f"[Main] 🔍 尝试自动清理DuckDB锁...")
        try:
            import shutil as _shutil
            # 防御性检查：lsof 在 Linux 上可能未安装
            if not _shutil.which('lsof'):
                print("[Main] ⚠️ lsof 未安装，尝试 fuser 回退...")
                # 回退：尝试使用 fuser（Linux 上更常见）
                if _shutil.which('fuser'):
                    try:
                        fuser_result = _sb.run(
                            ['fuser', '-k', '-9', db_path],
                            capture_output=True, text=True, timeout=10
                        )
                        if fuser_result.returncode == 0:
                            print(f"[Main] fuser killed processes holding {db_path}")
                            _tm.sleep(2)
                            if Path(wal_path).exists():
                                try:
                                    Path(wal_path).unlink()
                                except Exception as e:
                                    logger.warning(f"[Main] 删除 WAL 文件失败: {e}")
                            return True
                    except Exception as e:
                        print(f"[Main] fuser 回退失败: {e}")
                # 如果 fuser 也不可用，跳过自动清理
                print("[Main] ⚠️ lsof 和 fuser 均不可用，跳过自动清理")
                return False

            result = _sb.run(
                ['lsof', '-F', 'p', db_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = []
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('p'):
                        pid = line[1:].strip()
                        if pid and pid != str(_sb.pid if hasattr(_sb, 'pid') else _sys.maxsize):
                            pids.append(pid)
                if pids:
                    print(f"[Main] Killing lock-holding processes: {pids}")
                    for pid in pids:
                        try:
                            _sb.run(['kill', '-9', pid], capture_output=True, timeout=5)
                        except Exception as e:
                            logger.warning(f"[Main] 杀死进程 {pid} 失败: {e}")
                    _tm.sleep(2)
                    # 删除WAL文件
                    if Path(wal_path).exists():
                        try:
                            Path(wal_path).unlink()
                        except Exception as e:
                            logger.warning(f"[Main] 删除 WAL 文件失败: {e}")
                    return True
            else:
                # lsof 返回非零退出码，可能没有进程持有锁
                print(f"[Main] lsof 未找到持有锁的进程 (returncode={result.returncode})")
        except Exception as ex:
            print(f"[Main] Auto-cleanup failed: {ex}")
        return False
    
    # 尝试以只读方式连接, 这是最快的 lock 检测
    for attempt in range(3):
        try:
            import duckdb
            test_conn = duckdb.connect(db_path, read_only=True)
            test_conn.execute("SELECT 1").fetchone()
            test_conn.close()
            print(f"[Main] DuckDB lock check: ✅ Available ({db_path})")
            return
        except Exception as e:
            if "lock" in str(e).lower() or "IO Error" in str(e):
                if attempt < 2:
                    print(f"[Main] ⚠ DuckDB lock conflict (attempt {attempt+1}/3)")
                    # 删除WAL
                    if Path(wal_path).exists():
                        try:
                            Path(wal_path).unlink()
                            print(f"[Main] Deleted WAL: {wal_path}")
                            continue
                        except Exception as e:
                            logger.debug(f"Suppressed: {e}")
                            pass
                    if not _try_auto_cleanup():
                        continue
                else:
                    print(f"[Main] ❌ DuckDB is LOCKED by another process!")
                    print(f"[Main]   Database: {db_path}")
                    print(f"[Main]   Error: {e}")
                    print(f"[Main]   All auto-cleanup attempts failed")
                    print(f"[Main]   Try: pkill -9 -f python3")
                    _sys.exit(1)
            else:
                print(f"[Main] DuckDB lock check warning: {e}")

import datetime
import math
import asyncio
import logging
import logging.handlers  # 用于 RotatingFileHandler (见 setup_logging())
import signal
import threading
import time
from pathlib import Path
from contextlib import asynccontextmanager

# 抑制 py_mini_racer (cninfo 数据源) 的 mr_free_context GC 错误
# 该错误在 macOS Electron 沙盒中频繁触发但不影响功能
# sys.excepthook 无法拦截 GC __del__ 中的异常，需直接 patch 类方法
# 扩展异常列表以覆盖 FATAL Check failed 类型的 C 级别 abort
try:
    import py_mini_racer
    _original_del = py_mini_racer.MiniRacer.__del__
    def _quiet_del(self):
        try:
            _original_del(self)
        except (AttributeError, TypeError, RuntimeError, Exception):
            pass  # 静默处理 mr_free_context / address_pool_manager 等清理错误
    py_mini_racer.MiniRacer.__del__ = _quiet_del
    # 同时 patch mini_racer 的 addresses 属性，确保 IsInitialized 错误被捕获
    if hasattr(py_mini_racer, 'MiniRacer'):
        _original_mr_init = getattr(py_mini_racer.MiniRacer, '__init__', None)
        if _original_mr_init:
            def _safe_init(self, *args, **kwargs):
                try:
                    return _original_mr_init(self, *args, **kwargs)
                except Exception as e:
                    if 'IsInitialized' in str(e) or 'pool' in str(e).lower():
                        raise RuntimeError(f"mini_racer init blocked (sandbox): {e}")
                    raise
            py_mini_racer.MiniRacer.__init__ = _safe_init
except (ImportError, AttributeError):
    pass  # py_mini_racer 不可用或已更新，跳过
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from typing import Any


class SafeJSONResponse(JSONResponse):
    """自动将 NaN/Infinity 转为 None 的 JSON 响应"""
    def render(self, content: Any) -> bytes:
        import json
        cleaned = _clean_nan(content)
        return json.dumps(cleaned, ensure_ascii=False, allow_nan=False).encode(self.charset)


def _clean_nan(obj):
    import numpy as np
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [_clean_nan(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    return obj

from app.config import settings
from app.api.router import router
from app.engine.market import MarketEngine
from app.engine.storage import DataStorage
from app.engine.analysis import AnalysisEngine
from app.engine.scheduler import Scheduler
from app.engine.signals import SignalEngine
from app.engine.trade import TradeEngine
from app.services.macro_data import MacroDataService

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.middleware import SlowAPIMiddleware
    limiter = Limiter(key_func=get_remote_address)
    HAS_RATE_LIMIT = True
except ImportError:
    limiter = None
    HAS_RATE_LIMIT = False


def setup_logging():
    level = logging.DEBUG if _settings.debug else logging.INFO

    # 日志目录：优先使用 _settings.LOG_DIR, 回退到 ~/.lianghua/logs
    log_dir = Path(_settings.LOG_DIR) if _settings.LOG_DIR else (Path.home() / ".lianghua" / "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[Logging] 无法创建 {log_dir}, 回退到 ~/.lianghua/logs: {e}")
        log_dir = Path.home() / ".lianghua" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "lianghua.log"

    # 文件handler（自动轮转：50MB，保留5个备份）
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=50_000_000, backupCount=5, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    logging.basicConfig(
        level=level,
        handlers=[file_handler, console_handler],
    )

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DuckDB 单实例检查: 启动时而非导入时,避免阻塞测试导入
    import sys as _sys
    _check_duckdb_lock(_settings.db_path)

    # 快速初始化 - 不等待数据加载

    def on_revision(record: dict):
        """回调：检测到转股价下修时通过WebSocket广播 + 精确失效该code的缓存"""
        try:
            ae = getattr(app.state, "analysis_engine", None)
            if ae is not None:
                code = record.get("code", "")
                if code:
                    ae.invalidate_by_code(code)
        except Exception as e:
            logger.warning(f"[Revision callback] Cache invalidation error: {e}")
        try:
            # 使用 ws.py 模块中的 WebSocket 广播机制
            from app.api.ws import broadcast_revision
            broadcast_revision(record)
        except Exception as e:
            logger.warning(f"[Revision callback] Failed to broadcast: {e}")

    # ===== 启动阶段进度报告 =====
    print(f"[Startup 1/5] {_settings.app_name} backend init...")
    print(f"[Startup 2/5] Connecting to DuckDB at {_settings.db_path}...")
    storage = DataStorage(_settings.db_path, on_revision=on_revision)
    print(f"[Startup 2/5] ✅ DuckDB connected: {Path(_settings.db_path).stat().st_size/1024/1024:.1f}MB")
    print(f"[Startup 3/5] Initializing engines...")

    # 配置线程池：后台刷新用独立 executor，不阻塞 asyncio.to_thread
    # default_executor 留给 asyncio.to_thread / run_in_executor (API请求用)
    bg_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="bg_refresh")
    app.state.bg_executor = bg_executor
    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="compute")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(executor)
    app.state.executor = executor
    engine = MarketEngine(refresh_interval=_settings.market_refresh_interval, storage=storage)
    global market_engine
    market_engine = engine
    try:
        signal_engine = SignalEngine()
        signal_engine.set_storage(storage)
        trade_engine = TradeEngine()
        signal_engine.set_trade_engine(trade_engine)
        app.state.signal_engine = signal_engine
        app.state.trade_engine = trade_engine
    except Exception as e:
        logger.error(f"[Startup] SignalEngine init failed: {e}")
        signal_engine = None
        trade_engine = None
        app.state.signal_engine = None
        app.state.trade_engine = None
    scheduler = Scheduler()

    app.state.engine = engine
    app.state.storage = storage
    app.state.scheduler = scheduler
    app.state.analysis_engine = AnalysisEngine(cache_ttl=30, max_entries=100)
    print(f"[Startup 3/5] ✅ Engines ready (market, signal, trade, analysis)")

    # 初始化数据源管理器（东方财富+巨潮资讯，免费数据源）
    print(f"[Startup 4/5] Initializing data source manager...")
    try:
        from app.data.manager import init_data_sources
        data_source_manager = await init_data_sources({
            'eastmoney': {'enabled': True},
            'cninfo': {'enabled': True},
            'mx': {'enabled': True, 'api_key': _settings.MX_APIKEY},
            'wind': {'enabled': False},
            'tonghuashun': {'enabled': False},
        })
        app.state.data_source_manager = data_source_manager
        print(f"[Startup 4/5] ✅ Data source manager initialized (eastmoney+cninfo)")
        # 启动配置状态自检
        print(f"[Config] MX: {'✅ configured' if settings.MX_APIKEY else '⚠️  not configured'}")
        print(f"[Config] TAVILY: {'✅ configured' if settings.TAVILY_API_KEY else '⚠️  not configured'}")
        print(f"[Config] MINIMAX: {'✅ configured' if settings.MINIMAX_API_KEY else '⚠️  not configured'}")
        print(f"[Config] GITHUB: {'✅ configured' if settings.GITHUB_TOKEN else '⚠️  not configured'}")
        print(f"[Config] DEEPSEEK: {'✅ configured' if settings.DEEPSEEK_API_KEY else '⚠️  not configured'}")
        print(f"[Config] AKShare proxy: {'✅ enabled' if settings.AKSHARE_PROXY_ENABLED else '⚠️  disabled (direct)'}")
        print(f"[Config] JWT secret: {'✅ persistent' if settings.JWT_SECRET_KEY else '⚠️  auto-generated'}")
    except Exception as e:
        print(f"[Startup 4/5] ⚠ Data source init failed (non-fatal): {e}")

    # 初始化宏观市场数据服务
    print(f"[Startup 5/5] Loading macro data service...")
    macro_data_service = MacroDataService(cache_ttl=1800)  # 宏观数据缓存30分钟
    print(f"[Startup 5/5] ✅ Macro data service ready")
    app.state.macro_data_service = macro_data_service

    # 初始化告警引擎（使用简单的内存实现）
    try:
        from app.engine.alert import AlertEngine
        app.state.alert_engine = AlertEngine()
    except ImportError:
        # 如果 AlertEngine 不存在，使用轻量级内存实现
        from app.api.alert import AlertCondition, AlertTrigger
        class _SimpleAlertEngine:
            def __init__(self):
                self._alerts: dict[str, AlertCondition] = {}
                self._triggers: list[AlertTrigger] = []
            def get_alerts(self) -> list[AlertCondition]:
                return list(self._alerts.values())
            def add_alert(self, alert: AlertCondition):
                self._alerts[alert.id] = alert
            def remove_alert(self, alert_id: str):
                self._alerts.pop(alert_id, None)
        app.state.alert_engine = _SimpleAlertEngine()

    # 绑定 WebSocket manager 到 app.state
    try:
        from app.api.ws import ws_manager
        app.state.ws_manager = ws_manager
    except ImportError:
        pass

    # Connect signal engine to market engine for real-time signal generation
    if signal_engine is not None:
        engine.subscribe(signal_engine.process_quotes)
    else:
        logger.warning("[Startup] signal_engine is None, skipping real-time signal subscription")

    # Initialize PaperTradeManager for simulated trading
    try:
        from app.engine.paper_trade_manager import PaperTradeManager
        paper_trade_manager = PaperTradeManager(storage=storage, market_engine=engine)
        paper_trade_manager.load_accounts()
        paper_trade_manager.ensure_default_accounts()
        app.state.paper_trade_manager = paper_trade_manager
        engine.subscribe(paper_trade_manager.on_quotes)
        print(f"[Startup] ✅ PaperTradeManager initialized ({len(paper_trade_manager._accounts)} accounts)")
    except Exception as e:
        print(f"[Startup] ⚠ PaperTradeManager init failed (non-fatal): {e}")

    # 注册择时信号定时刷新任务（每5分钟刷新一次宏观数据+择时信号）
    async def _refresh_timing_signal():
        try:
            from app.api.xb_strategy import refresh_timing_signal_caches
            await refresh_timing_signal_caches(engine, macro_data_service)
            logger.info("[Scheduler] Timing signal refreshed")
        except Exception as e:
            logger.warning(f"[Scheduler] Timing signal refresh failed: {e}")

    scheduler.add_interval_task("timing_signal_refresh", _refresh_timing_signal, 300)

    # 注册 DuckDB 定期 VACUUM 任务（压缩 WAL + 释放空间）
    async def _duckdb_vacuum():
        """压缩 DuckDB 数据库, 防止长期运行后文件膨胀"""
        try:
            import time
            t0 = time.time()
            size_before = Path(_settings.db_path).stat().st_size if Path(_settings.db_path).exists() else 0
            storage.conn.execute("VACUUM")
            storage.conn.execute("CHECKPOINT")
            size_after = Path(_settings.db_path).stat().st_size if Path(_settings.db_path).exists() else 0
            freed_mb = (size_before - size_after) / 1024 / 1024
            logger.info(f"[Scheduler] DuckDB VACUUM done: {size_before/1024/1024:.1f}MB -> {size_after/1024/1024:.1f}MB (freed {freed_mb:.1f}MB in {time.time()-t0:.1f}s)")
        except Exception as e:
            logger.warning(f"[Scheduler] DuckDB VACUUM failed: {e}")

    vacuum_interval = max(1, _settings.DUCKDB_VACUUM_INTERVAL_HOURS) * 3600
    scheduler.add_interval_task("duckdb_vacuum", _duckdb_vacuum, vacuum_interval)

    # 注册评分历史定时刷新任务（每日收盘后自动保存一次评分快照）
    async def _refresh_score_history():
        """保存当日评分快照到 score_history 表"""
        try:
            import pandas as pd
            from app.api.score import _compute_scores

            bonds = await engine.get_all_quotes()
            if not bonds:
                logger.warning("[Scheduler] No bonds for score snapshot")
                return

            rows = []
            for b in bonds:
                rows.append({
                    "code": b.code,
                    "name": b.name,
                    "price": b.price,
                    "premium_ratio": b.premium_ratio,
                    "volume": b.volume or 0,
                    "dual_low": b.dual_low,
                    "change_pct": b.change_pct or 0,
                })

            df = pd.DataFrame(rows)
            df = df[(df['price'] > 0) & (df['dual_low'] > 0)]
            if df.empty:
                logger.warning("[Scheduler] No valid bonds after filtering for score snapshot")
                return

            weights = {'dual_low': 0.4, 'premium': 0.2, 'momentum': 0.2, 'volume': 0.1, 'price': 0.1}
            df = _compute_scores(df, weights)

            scores = []
            for _, row in df.iterrows():
                scores.append({
                    'code': row['code'],
                    'name': row['name'],
                    'score': row['score'],
                    'score_dual_low': row['score_dual_low'],
                    'score_premium': row['score_premium'],
                    'score_momentum': row['score_momentum'],
                    'score_volume': row['score_volume'],
                    'score_price': row['score_price'],
                    'price': row['price'],
                    'premium_ratio': row['premium_ratio'],
                    'dual_low': row['dual_low'],
                    'volume': row['volume'],
                })

            storage.save_score_snapshot(scores)
            logger.info(f"[Scheduler] Score history snapshot saved: {len(scores)} bonds")
        except Exception as e:
            logger.warning(f"[Scheduler] Score snapshot refresh failed: {e}")

    scheduler.add_daily_task("refresh_score_history", _refresh_score_history, datetime.time(16, 0))

    # 注册七维评分历史每日刷新
    async def _refresh_seven_dim_history():
        """保存当日七维评分快照到 seven_dim_history 表"""
        try:
            import numpy as np
            import pandas as pd
            from app.strategies.xibu_seven_dimension import XibuSevenDimensionStrategy

            bonds = await engine.get_all_quotes()
            if not bonds:
                logger.warning("[Scheduler] No bonds for seven_dim snapshot")
                return

            rows = []
            for b in bonds:
                rows.append({
                    'code': b.code, 'name': b.name, 'price': b.price,
                    'premium_ratio': b.premium_ratio, 'volume': b.volume or 0,
                    'dual_low': b.dual_low, 'change_pct': b.change_pct or 0,
                    'ytm': b.ytm or 0, 'remaining_years': b.remaining_years or 0,
                    'conversion_value': b.conversion_value or 0,
                    'stock_price': b.stock_price or 0, 'stock_change_pct': b.stock_change_pct or 0,
                    'forced_call_days': b.forced_call_days or 0,
                    'date': datetime.datetime.now().date(),
                })

            df = pd.DataFrame(rows)
            strategy = XibuSevenDimensionStrategy()
            strategy.on_init(df)

            scores = []
            for _, row in df.iterrows():
                veto = strategy._check_veto(row)
                if not veto.passed:
                    continue
                score_dict = strategy._calc_total_score(row, df)
                score_dict['code'] = row['code']
                score_dict['name'] = row.get('name', '')
                score_dict['price'] = row['price']
                score_dict['premium_ratio'] = row['premium_ratio']
                score_dict['dual_low'] = row['dual_low']
                scores.append(score_dict)

            storage.save_seven_dim_snapshot(scores)
            logger.info(f"[Scheduler] Seven-dim history snapshot saved: {len(scores)} bonds")
        except Exception as e:
            logger.warning(f"[Scheduler] Seven-dim snapshot refresh failed: {e}")

    scheduler.add_daily_task("refresh_seven_dim_history", _refresh_seven_dim_history, datetime.time(16, 30))

    # 启动调度器（此前只添加了任务但未启动，导致所有定时任务从未执行）
    try:
        await scheduler.start()
        logger.info("[Startup] Scheduler started")
    except Exception as e:
        logger.warning(f"[Startup] Scheduler start failed: {e}")

    logger.info(f"Starting {_settings.app_name} on {_settings.host}:{_settings.port}")

    # 后台启动数据加载 - 不阻塞服务器就绪
    # 注意：AKShare C扩展的segfault会杀死整个Python进程(无Python回溯)
    # 所有 AKShare 调用必须在子进程中执行（C扩展 segfault 会杀死整个进程）
    async def background_start():
        try:
            # 第0步：从磁盘加载所有数据增强缓存到内存
            # 这样即使子进程还没写完，enrich_quotes 也能用旧缓存数据
            try:
                from app.engine.data_enrich import start_background_refresh, set_event_source_instance
                from app.strategies.event_data_source import EventDataSource
                await start_background_refresh()
                # Register EventDataSource for event-score enrichment in enrich_quotes
                _event_src = EventDataSource()
                set_event_source_instance(_event_src)
                logger.info("[Startup] Data enrichment caches loaded from disk + EventDataSource registered")
            except Exception as e:
                logger.warning(f"[Startup] Cache loading failed: {e}")

            # 引擎启动：不调用 refresh()，仅设置 _running 标志 + 启动 refresh_loop
            # refresh_loop 首次 tick 会从 DuckDB 缓存加载，不调用 AKShare
            try:
                await engine.start()
                logger.info("[Startup] Engine started (deferred load)")
            except Exception as e:
                logger.error(f"[Startup] Engine start failed: {e}")

            # 数据增强在子进程中运行（AKShare C扩展 segfault 不杀死主进程）
            # 仅把最高风险的 spot / vol / fund_flow / bond_price 放在 runner 中，
            # 其余缓存由主进程 start_background_refresh 负责，避免重复刷新和 metrics 丢失。
            _enrich_procs: list[subprocess.Popen] = []
            _enrich_log = None
            try:
                import subprocess, sys
                runner_script = str(Path(__file__).parent / "engine" / "data_enrich_runner.py")
                _enrich_log_dir = Path.home() / ".lianghua" / "logs"
                _enrich_log_dir.mkdir(parents=True, exist_ok=True)
                # bond-price 由主进程扩展执行器负责（避免双重执行）
                # 只把最高 segfault 风险的 spot/vol/fund-flow 留给 runner 子进程
                cmd = [sys.executable, runner_script, "--spot", "--vol", "--fund-flow"]
                _enrich_log = open(_enrich_log_dir / "enrich_runner.log", "w")
                p = subprocess.Popen(
                    cmd,
                    cwd=str(Path(__file__).parent.parent),
                    stdout=_enrich_log,
                    stderr=_enrich_log,
                    stdin=subprocess.DEVNULL,
                    # start_new_session=True is the Python equivalent of setsid(2).
                    # This detaches the child from the parent's session/PGID so
                    # closing the terminal (SIGHUP) does not kill the runner.
                    # See AGENTS.md #49.
                    start_new_session=True,
                )
                _enrich_procs.append(p)
                app.state.enrich_procs = _enrich_procs
                app.state.enrich_log = _enrich_log
                logger.info("[Startup] DataEnrich runner subprocess started (spot/vol/fund-flow/bond-price)")
            except Exception as e:
                if _enrich_log is not None and not _enrich_log.closed:
                    _enrich_log.close()
                logger.warning(f"[Startup] DataEnrich runner subprocess start failed: {e}")

            # 延迟刷新模拟盘持仓价格（轮询等待 MarketEngine 有行情数据后再刷新）
            async def _delayed_refresh_paper_positions():
                max_attempts = 10  # 最多尝试10次（5分钟）
                for attempt in range(max_attempts):
                    await asyncio.sleep(30)
                    try:
                        ptm = getattr(app.state, 'paper_trade_manager', None)
                        if ptm is None:
                            break
                        # 检查 MarketEngine 是否已有行情数据
                        me = getattr(app.state, 'engine', None)
                        has_quotes = False
                        if me is not None:
                            # 如果 MarketEngine 明确标记 is_running=False（已停止），跳过本次等待
                            # 注意：is_running 为 None 或不存在时，不跳过（引擎可能正在初始化）
                            if getattr(me, 'is_running', None) is False:
                                logger.debug("[Startup] PaperTrade waiting: MarketEngine not running yet (attempt %d/%d)" % (attempt + 1, max_attempts))
                                continue
                            lq = getattr(me, 'latest_quotes', None)
                            if lq is None:
                                gf = getattr(me, 'get_latest_quotes', None)
                                if gf:
                                    lq = gf()
                            has_quotes = lq is not None and len(lq) > 0
                        if has_quotes:
                            ptm._refresh_position_prices()
                            logger.info("[Startup] PaperTrade position prices refreshed (attempt %d)" % (attempt + 1))
                            break
                        else:
                            logger.debug("[Startup] PaperTrade waiting for MarketEngine quotes (attempt %d/%d)" % (attempt + 1, max_attempts))
                    except Exception as e:
                        logger.debug(f"[Startup] Delayed position price refresh failed: {e}")
            asyncio.create_task(_delayed_refresh_paper_positions())

            # 评分快照：直接从主进程运行（不再创建子进程，避免 DuckDB 锁冲突）
            try:
                await scheduler.run_now("refresh_score_history")
                logger.info("[Startup] Score history snapshot completed")
            except Exception as e:
                logger.warning(f"[Startup] Score history snapshot failed (will retry at 16:00): {e}")

            logger.info("Background data loading completed")
            # 后台预计算回测：启动后检查缓存，如缺失则预热三大策略回测结果
            async def _precompute_backtests():
                import json as _json
                from datetime import datetime as _dt
                _status_path = os.path.join(os.path.expanduser("~"), ".lianghua", "backtest_cache", ".precompute_status.json")
                os.makedirs(os.path.dirname(_status_path), exist_ok=True)
                def _write_status(status: str, current: str = "", completed: list = None, failed: list = None, total_est: int = 0):
                    try:
                        with open(_status_path, "w", encoding="utf-8") as f:
                            _json.dump({
                                "status": status,
                                "started_at": _dt.now().isoformat(),
                                "current_strategy": current,
                                "completed_strategies": completed or [],
                                "failed_strategies": failed or [],
                                "total_strategies": len(_STRATEGY_KEYS),
                                "estimated_seconds_remaining": total_est,
                            }, f, ensure_ascii=False, default=str)
                    except Exception as e:
                        logger.debug(f"[Precompute] status write failed: {e}")
                try:
                    from app.api.backtest_results import _load_cache, _save_cache, _STRATEGY_KEYS, _STRATEGY_NAMES
                    from app.strategies import get_strategy
                    from app.engine.backtest import BacktestEngine
                    from app.models.backtest import BacktestConfig
                    from datetime import date
                    import asyncio
                    end = date.today()
                    start = date(2020, 1, 1)
                    _completed = []
                    _failed = []
                    _write_status("running", current=_STRATEGY_KEYS[0] if _STRATEGY_KEYS else "", completed=_completed, failed=_failed, total_est=8*60)
                    for key in _STRATEGY_KEYS:
                        try:
                            # 先检查缓存是否已存在，避免重复计算
                            cached = _load_cache(key, start, end)
                            if cached:
                                logger.info(f"[Precompute] Cache hit for {key}, skipping")
                                continue
                            logger.info(f"[Precompute] Cache miss for {key}, running backtest...")
                            # 获取策略类和最优参数
                            strategy_cls = get_strategy(key)
                            from app.engine.paper_trade_manager import PaperTradeManager
                            optimal_params = PaperTradeManager.get_optimal_params(key)
                            strategy = strategy_cls(**optimal_params)
                            # 使用 HistoricalDataLoader 从 storage 获取历史数据（无需 Request 对象）
                            from app.engine.historical import HistoricalDataLoader
                            loader = HistoricalDataLoader(storage)
                            full_data = await asyncio.to_thread(loader.get_cached_history, start, end)
                            if full_data is None or full_data.empty:
                                logger.warning(f"[Precompute] No historical data for {key}, skipping")
                                continue
                            # 运行回测
                            config = BacktestConfig(
                                initial_cash=100_000_000.0,
                                commission_pct=0.0001,
                                slippage_pct=0.001,
                            )
                            engine = BacktestEngine(config=config)
                            result = await asyncio.to_thread(engine.run, strategy, full_data)
                            # 转换为前端需要的格式并缓存
                            raw_dict = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.to_dict()
                            metrics = raw_dict.get("metrics", {}) or {}
                            bm_metrics = raw_dict.get("benchmark_metrics", {}) or {}
                            ex_metrics = raw_dict.get("excess_metrics", {}) or {}
                            result_dict = {
                                "returns": metrics.get("total_return_pct", 0),
                                "benchmark_returns": bm_metrics.get("total_return_pct", 0),
                                "excess_returns": ex_metrics.get("total_return_pct", 0),
                                "max_drawdown": metrics.get("max_drawdown_pct", 0),
                                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                                "win_rate": metrics.get("win_rate", 0),
                                "trade_count": metrics.get("total_trades", 0),
                                "total_cost": raw_dict.get("total_cost", 0),
                                "turnover_rate": 0,
                                "daily_values": [],
                                "trades": [],
                                "_raw": raw_dict,
                            }
                            cache_data = {
                                "strategy_id": key,
                                "strategy_name": _STRATEGY_NAMES[key],
                                "optimal_params": optimal_params,
                                "data_source": "precomputed_at_startup",
                                "total_rows": len(full_data),
                                "n_dates": full_data["date"].nunique() if "date" in full_data.columns else 0,
                                "result": result_dict,
                            }
                            _save_cache(key, start, end, cache_data)
                            logger.info(f"[Precompute] Backtest {key} completed and cached")
                        except Exception as e:
                            logger.warning(f"[Precompute] Backtest {key} failed: {e}")
                except Exception as e:
                    logger.warning(f"[Precompute] Backtest precompute failed: {e}")
            asyncio.create_task(_precompute_backtests())

        except Exception as e:
            import traceback
            logger.error(f"[Startup] Background start failed: {e}")

    background_task = asyncio.create_task(background_start())

    # Signal handling for graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler(sig: int, frame):
        sig_name = signal.Signals(sig).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        shutdown_event.set()

    # Register signal handlers (only in main thread)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

    yield

    # Graceful shutdown
    logger.info(f"Shutting down {_settings.app_name}...")

    # Cancel background task
    background_task.cancel()
    try:
        await background_task
    except asyncio.CancelledError:
        pass

    # Stop engines
    try:
        await engine.stop()
        logger.info("Market engine stopped")
    except Exception as e:
        logger.error(f"Error stopping market engine: {e}")

    try:
        await scheduler.stop()
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")

    # Shutdown ThreadPoolExecutors to prevent resource leaks
    try:
        executor.shutdown(wait=False)
        logger.info("Executor shut down")
    except Exception as e:
        logger.error(f"Error shutting down executor: {e}")
    try:
        bg_executor.shutdown(wait=False)
        logger.info("Background executor shut down")
    except Exception as e:
        logger.error(f"Error shutting down background executor: {e}")

    # Cleanup enrich subprocesses
    try:
        enrich_procs = getattr(app.state, "enrich_procs", None)
        if enrich_procs:
            for p in enrich_procs:
                try:
                    p.terminate()
                    logger.info(f"Terminated enrich subprocess {p.pid}")
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                    pass
            # 等待 3 秒让子进程完成缓存写入（原来 0.5s 太短，可能导致 JSON 截断）
            await asyncio.sleep(3.0)
            for p in enrich_procs:
                if p.poll() is None:
                    try:
                        p.kill()
                        logger.info(f"Killed enrich subprocess {p.pid}")
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass
    except Exception as e:
        logger.error(f"Error cleaning up enrich subprocesses: {e}")
    try:
        enrich_log = getattr(app.state, "enrich_log", None)
        if enrich_log and not enrich_log.closed:
            enrich_log.close()
            logger.info("Enrich log file closed")
    except Exception as e:
        logger.error(f"Error closing enrich log: {e}")

    try:
        storage.close()
        logger.info("Storage closed")
    except Exception as e:
        logger.error(f"Error closing storage: {e}")

    logger.info(f"{_settings.app_name} shutdown complete")


app = FastAPI(title=_settings.app_name, lifespan=lifespan, default_response_class=SafeJSONResponse)

if HAS_RATE_LIMIT and limiter:
    app.state.limiter = limiter
    app.add_exception_handler(429, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} {response.status_code} {duration*1000:.1f}ms")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(router, prefix="/api/v1")

# ---- 挂载前端静态文件 ----
# 使用中间件方式：为所有未匹配的 GET 请求返回前端 SPA
# 兼容多种打包布局: frontend/dist/ (dev) 或 frontend/ (release)
_frontend_candidates = [
    Path(__file__).parent.parent.parent / "frontend" / "dist",
    Path(__file__).parent.parent.parent / "frontend",
]
_frontend_dist = None
for _p in _frontend_candidates:
    if _p.is_dir() and (_p / "index.html").exists():
        _frontend_dist = _p
        break
_has_frontend = _frontend_dist is not None

from fastapi.responses import FileResponse

if _has_frontend:
    from fastapi.staticfiles import StaticFiles
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")
    logger.info(f"前端静态文件已挂载: {_frontend_dist}")
else:
    logger.info(f"前端静态文件不存在: {_frontend_dist}, SPA 将使用动态回退")


@app.middleware("http")
async def spa_fallback(request: Request, call_next):
    """动态 SPA 回退中间件：优先返回真实静态文件，否则回退到 index.html"""
    if (
        request.method == "GET"
        and not request.url.path.startswith("/api/")
        and not request.url.path.startswith("/health")
        and _frontend_dist is not None
    ):
        rel_path = request.url.path.lstrip('/')
        if rel_path:
            static_path = _frontend_dist / rel_path
            if static_path.exists() and static_path.is_file():
                return FileResponse(static_path)
    response = await call_next(request)
    if response.status_code == 404 and request.method == "GET":
        if request.url.path.startswith("/api/") or request.url.path.startswith("/health"):
            return response
        # 动态检查 frontend dist 是否存在（支持热构建场景）
        dist_dir = _frontend_dist
        index_path = dist_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
    return response


def _health_response(request: Request | None = None) -> dict:
    engine_running = False
    db_ok = False
    signal_engine_available = False
    try:
        engine_running = getattr(app.state, "engine", None) and app.state.engine.is_running
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
        pass
    try:
        storage = getattr(app.state, "storage", None)
        if storage is not None:
            storage.ensure_connection()
            storage.conn.execute("SELECT 1")
            db_ok = True
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
        pass
    try:
        signal_engine_available = getattr(app.state, "signal_engine", None) is not None
    except Exception as e:
        logger.debug(f"Suppressed: {e}")
        pass
    result = {
        "status": "ok",
        "app": _settings.app_name,
        "version": _settings.app_version,
        "market_running": engine_running,
        "db_ok": db_ok,
        "signal_engine_available": signal_engine_available,
        "data_sources": {
            "mx": {"configured": bool(_settings.MX_APIKEY)},
            "tavily": {"configured": bool(_settings.TAVILY_API_KEY)},
            "minimax": {"configured": bool(_settings.MINIMAX_API_KEY)},
            "deepseek": {"configured": bool(_settings.DEEPSEEK_API_KEY)},
            "github": {"configured": bool(_settings.GITHUB_TOKEN)},
            "akshare_proxy": {"enabled": _settings.AKSHARE_PROXY_ENABLED},
        },
    }
    # ws_auth_token 仅在本地请求中返回，避免 SSRF 窃取
    if request is not None:
        client = request.client
        if client and client.host in ("127.0.0.1", "::1", "localhost"):
            result["ws_auth_token"] = _settings.ws_auth_token
    return result


@app.get("/health")
@app.get("/api/v1/health")
async def health_v1(request: Request):
    return _health_response(request)
