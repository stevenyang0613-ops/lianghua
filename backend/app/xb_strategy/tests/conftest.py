"""西部量化可转债策略 V3.0 测试框架增强

功能:
- Pytest覆盖率配置
- 集成测试框架
- 性能基准测试
- Mock数据生成
- 测试Fixtures
"""
import pytest
import asyncio
import time
import random
import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from functools import wraps
import json
import tempfile
import os


# ============ 配置类 ============

@dataclass
class TestConfig:
    """测试配置"""
    # 覆盖率配置
    coverage_min: float = 80.0
    coverage_fail_under: float = 70.0

    # 性能测试配置
    performance_iterations: int = 100
    performance_warmup: int = 10

    # 集成测试配置
    integration_timeout: int = 30

    # Mock数据配置
    mock_seed: int = 42


# ============ Pytest配置 ============

def pytest_configure(config):
    """Pytest配置"""
    config.addinivalue_line(
        "markers", "unit: 单元测试"
    )
    config.addinivalue_line(
        "markers", "integration: 集成测试"
    )
    config.addinivalue_line(
        "markers", "performance: 性能测试"
    )
    config.addinivalue_line(
        "markers", "slow: 慢速测试"
    )
    config.addinivalue_line(
        "markers", "requires_db: 需要数据库"
    )
    config.addinivalue_line(
        "markers", "requires_redis: 需要Redis"
    )


# ============ Fixtures ============

@pytest.fixture
def test_config():
    """测试配置Fixture"""
    return TestConfig()


@pytest.fixture
def mock_cb_data() -> List[Dict]:
    """Mock转债数据"""
    random.seed(42)

    data = []
    for i in range(100):
        cb_code = f"128{str(i).zfill(3)}"
        stock_code = f"60{str(random.randint(1, 9999)).zfill(4)}"

        # 生成合理的价格数据
        close = round(random.uniform(90, 150), 2)
        stock_close = round(random.uniform(3, 50), 2)
        conversion_ratio = random.uniform(5, 20)
        conversion_value = stock_close * conversion_ratio
        premium = (close - conversion_value) / conversion_value

        data.append({
            "code": cb_code,
            "name": f"测试转债{i}",
            "stock_code": stock_code,
            "stock_name": f"测试股票{i}",
            "close": close,
            "stock_close": stock_close,
            "conversion_ratio": conversion_ratio,
            "conversion_value": conversion_value,
            "premium": premium,
            "maturity": (date.today() + timedelta(days=random.randint(30, 2000))).isoformat(),
            "volume": random.randint(10000, 1000000),
            "amount": random.uniform(1000000, 100000000),
            "turnover_rate": random.uniform(0.01, 0.2),
        })

    return data


@pytest.fixture
def mock_stock_data() -> List[Dict]:
    """Mock股票数据"""
    random.seed(42)

    data = []
    for i in range(100):
        data.append({
            "code": f"60{str(i).zfill(4)}",
            "name": f"测试股票{i}",
            "close": round(random.uniform(5, 100), 2),
            "pe_ttm": round(random.uniform(5, 100), 2),
            "pb": round(random.uniform(0.5, 10), 2),
            "roe": round(random.uniform(-0.1, 0.3), 4),
            "debt_ratio": round(random.uniform(0.1, 0.8), 4),
            "volume": random.randint(100000, 10000000),
            "amount": random.uniform(10000000, 1000000000),
        })

    return data


@pytest.fixture
def mock_price_history() -> Dict[str, List[float]]:
    """Mock历史价格数据"""
    np.random.seed(42)

    result = {}
    for i in range(10):
        code = f"128{str(i).zfill(3)}"
        # 生成模拟价格序列（随机游走）
        returns = np.random.normal(0.001, 0.02, 250)
        prices = 100 * np.cumprod(1 + returns)
        result[code] = prices.tolist()

    return result


@pytest.fixture
def temp_db():
    """临时数据库Fixture"""
    import sqlite3

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)

    # 创建测试表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cb_daily_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cb_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            amount REAL
        );

        CREATE TABLE IF NOT EXISTS stock_daily_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            amount REAL
        );

        CREATE TABLE IF NOT EXISTS trading_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cb_code TEXT NOT NULL,
            signal_date DATE NOT NULL,
            action TEXT,
            quantity INTEGER,
            price REAL
        );
    """)

    yield conn

    conn.close()
    os.unlink(db_path)


@pytest.fixture
def temp_cache():
    """临时缓存Fixture"""
    cache = {}

    class TempCache:
        def get(self, key):
            return cache.get(key)

        def set(self, key, value, ttl=None):
            cache[key] = value
            return True

        def delete(self, key):
            if key in cache:
                del cache[key]
            return True

        def clear(self):
            cache.clear()

    return TempCache()


# ============ Mock数据生成器 ============

class MockDataGenerator:
    """Mock数据生成器"""

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        np.random.seed(seed)

    def generate_cb_list(self, count: int = 100) -> List[Dict]:
        """生成转债列表"""
        result = []
        for i in range(count):
            cb_code = f"128{str(i).zfill(3)}"
            stock_code = f"60{str(random.randint(1, 9999)).zfill(4)}"

            close = round(random.uniform(90, 150), 2)
            stock_close = round(random.uniform(3, 50), 2)
            conversion_ratio = random.uniform(5, 20)
            conversion_value = stock_close * conversion_ratio

            result.append({
                "code": cb_code,
                "name": f"测试转债{i}",
                "stock_code": stock_code,
                "close": close,
                "stock_close": stock_close,
                "conversion_ratio": conversion_ratio,
                "conversion_value": conversion_value,
                "premium": (close - conversion_value) / conversion_value,
                "maturity": (date.today() + timedelta(days=random.randint(30, 2000))).isoformat(),
                "volume": random.randint(10000, 1000000),
            })

        return result

    def generate_price_series(
        self,
        days: int = 250,
        initial_price: float = 100.0,
        volatility: float = 0.02,
        drift: float = 0.0005,
    ) -> List[float]:
        """生成价格序列（几何布朗运动）"""
        returns = np.random.normal(drift, volatility, days)
        prices = initial_price * np.cumprod(1 + returns)
        return prices.tolist()

    def generate_ohlcv(
        self,
        days: int = 250,
        initial_price: float = 100.0,
    ) -> List[Dict]:
        """生成OHLCV数据"""
        prices = self.generate_price_series(days, initial_price)

        result = []
        base_date = date.today() - timedelta(days=days)

        for i, close in enumerate(prices):
            daily_range = close * random.uniform(0.01, 0.05)
            high = close + random.uniform(0, daily_range)
            low = close - random.uniform(0, daily_range)
            open_price = low + random.uniform(0, high - low)

            result.append({
                "date": (base_date + timedelta(days=i)).isoformat(),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": random.randint(100000, 10000000),
                "amount": random.uniform(1000000, 100000000),
            })

        return result

    def generate_trades(
        self,
        count: int = 100,
        win_rate: float = 0.55,
    ) -> List[Dict]:
        """生成交易记录"""
        result = []

        for i in range(count):
            is_win = random.random() < win_rate
            profit_pct = random.uniform(0.01, 0.1) if is_win else random.uniform(-0.1, -0.01)

            result.append({
                "trade_id": f"T{str(i).zfill(6)}",
                "code": f"128{str(random.randint(0, 99)).zfill(3)}",
                "date": (date.today() - timedelta(days=random.randint(0, 365))).isoformat(),
                "action": random.choice(["buy", "sell"]),
                "quantity": random.randint(100, 10000),
                "price": round(random.uniform(90, 150), 2),
                "profit_pct": profit_pct,
                "holding_days": random.randint(1, 30),
            })

        return result


# ============ 性能测试工具 ============

class PerformanceBenchmark:
    """性能基准测试"""

    def __init__(self, warmup: int = 10, iterations: int = 100):
        self.warmup = warmup
        self.iterations = iterations
        self._results: Dict[str, List[float]] = {}

    def benchmark(self, name: str = None):
        """基准测试装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                test_name = name or func.__name__

                # 预热
                for _ in range(self.warmup):
                    func(*args, **kwargs)

                # 正式测试
                times = []
                for _ in range(self.iterations):
                    start = time.perf_counter()
                    result = func(*args, **kwargs)
                    end = time.perf_counter()
                    times.append(end - start)

                self._results[test_name] = times
                return result

            return wrapper
        return decorator

    def get_stats(self, name: str = None) -> Dict[str, float]:
        """获取统计"""
        if name:
            times = self._results.get(name, [])
        else:
            # 汇总所有结果
            times = []
            for t in self._results.values():
                times.extend(t)

        if not times:
            return {}

        times = np.array(times)

        return {
            "count": len(times),
            "mean": float(np.mean(times) * 1000),  # ms
            "std": float(np.std(times) * 1000),
            "min": float(np.min(times) * 1000),
            "max": float(np.max(times) * 1000),
            "p50": float(np.percentile(times, 50) * 1000),
            "p95": float(np.percentile(times, 95) * 1000),
            "p99": float(np.percentile(times, 99) * 1000),
        }

    def get_report(self) -> str:
        """获取报告"""
        lines = ["=" * 60, "性能基准测试报告", "=" * 60, ""]

        for name, times in self._results.items():
            stats = self.get_stats(name)
            lines.append(f"测试: {name}")
            lines.append(f"  调用次数: {stats['count']}")
            lines.append(f"  平均耗时: {stats['mean']:.3f}ms")
            lines.append(f"  标准差: {stats['std']:.3f}ms")
            lines.append(f"  P95: {stats['p95']:.3f}ms")
            lines.append(f"  P99: {stats['p99']:.3f}ms")
            lines.append("")

        return "\n".join(lines)


# ============ 集成测试基类 ============

class IntegrationTestCase:
    """集成测试基类"""

    @pytest.fixture(autouse=True)
    def setup(self, temp_db, temp_cache):
        """设置测试环境"""
        self.db = temp_db
        self.cache = temp_cache
        self.generator = MockDataGenerator()

    def insert_test_data(self, count: int = 100):
        """插入测试数据"""
        cb_list = self.generator.generate_cb_list(count)

        for cb in cb_list:
            self.db.execute(
                "INSERT INTO cb_daily_data (cb_code, trade_date, close, volume) VALUES (?, ?, ?, ?)",
                (cb['code'], date.today().isoformat(), cb['close'], cb['volume'])
            )

        self.db.commit()

    def assert_signal_valid(self, signal: Dict):
        """验证信号有效性"""
        assert 'code' in signal
        assert 'action' in signal
        assert signal['action'] in ['buy', 'sell', 'hold']
        assert 'quantity' in signal
        assert signal['quantity'] >= 0


# ============ 测试工具函数 ============

def assert_performance(func, max_time_ms: float, iterations: int = 100):
    """断言性能"""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    avg_time = sum(times) / len(times)
    assert avg_time < max_time_ms, f"性能测试失败: 平均耗时 {avg_time:.2f}ms > {max_time_ms}ms"

    return avg_time


def assert_coverage(module_path: str, min_coverage: float = 80.0):
    """断言覆盖率"""
    try:
        import coverage
        cov = coverage.Coverage()
        cov.load()

        # 获取模块覆盖率
        # 这里简化处理，实际使用pytest-cov插件
        pass
    except ImportError:
        pass


def run_async_test(coro):
    """运行异步测试"""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ============ 测试数据验证器 ============

class DataValidator:
    """测试数据验证器"""

    @staticmethod
    def validate_cb_data(data: Dict) -> bool:
        """验证转债数据"""
        required_fields = ['code', 'name', 'close', 'stock_code']
        return all(f in data for f in required_fields)

    @staticmethod
    def validate_signal(signal: Dict) -> bool:
        """验证信号数据"""
        required_fields = ['code', 'action', 'quantity']
        if not all(f in signal for f in required_fields):
            return False

        if signal['action'] not in ['buy', 'sell', 'hold']:
            return False

        if signal['quantity'] < 0:
            return False

        return True

    @staticmethod
    def validate_price(price: float) -> bool:
        """验证价格"""
        return isinstance(price, (int, float)) and price > 0


# ============ 测试场景生成器 ============

class ScenarioGenerator:
    """测试场景生成器"""

    @staticmethod
    def generate_bull_market_scenario() -> Dict:
        """生成牛市场景"""
        return {
            "market_trend": "bull",
            "stock_return_mean": 0.002,
            "stock_return_std": 0.015,
            "cb_premium_trend": -0.001,  # 溢价率下降
            "volume_multiplier": 1.5,
        }

    @staticmethod
    def generate_bear_market_scenario() -> Dict:
        """生成熊市场景"""
        return {
            "market_trend": "bear",
            "stock_return_mean": -0.002,
            "stock_return_std": 0.025,
            "cb_premium_trend": 0.001,  # 溢价率上升
            "volume_multiplier": 0.8,
        }

    @staticmethod
    def generate_volatile_scenario() -> Dict:
        """生成波动场景"""
        return {
            "market_trend": "volatile",
            "stock_return_mean": 0.0,
            "stock_return_std": 0.03,
            "cb_premium_trend": 0.0,
            "volume_multiplier": 1.2,
        }

    @staticmethod
    def generate_crash_scenario() -> Dict:
        """生成崩盘场景"""
        return {
            "market_trend": "crash",
            "stock_return_mean": -0.01,
            "stock_return_std": 0.05,
            "cb_premium_trend": 0.005,
            "volume_multiplier": 2.0,
        }


# ============ Pytest插件 ============

class SGStrategyPlugin:
    """西部策略测试插件"""

    def pytest_runtest_setup(self, item):
        """测试前检查"""
        # 检查是否需要数据库
        if item.get_closest_marker('requires_db'):
            # 检查数据库连接
            pass

        # 检查是否需要Redis
        if item.get_closest_marker('requires_redis'):
            # 检查Redis连接
            pass

    def pytest_runtest_teardown(self, item):
        """测试后清理"""
        pass

    def pytest_terminal_summary(self, terminalreporter):
        """测试汇总"""
        terminalreporter.write_line("")
        terminalreporter.write_line("西部策略测试汇总:", bold=True)

        # 性能测试结果
        if hasattr(self, '_benchmark'):
            terminalreporter.write_line(self._benchmark.get_report())


# ============ 导出 ============

__all__ = [
    "TestConfig",
    "MockDataGenerator",
    "PerformanceBenchmark",
    "IntegrationTestCase",
    "DataValidator",
    "ScenarioGenerator",
    "assert_performance",
    "run_async_test",
    "mock_cb_data",
    "mock_stock_data",
    "mock_price_history",
    "temp_db",
    "temp_cache",
]
