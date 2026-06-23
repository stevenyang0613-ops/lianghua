"""西部量化可转债策略 V3.0 数据适配器

支持多种数据源:
- Akshare (免费)
- Wind (万得)
- JoinQuant (聚宽)
- RiceQuant (米筐)
- Tushare (掘金)
"""
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Callable, Any
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
import logging
import json

from app.xb_strategy.core.types import ConvertibleBondData, StockData

logger = logging.getLogger(__name__)


# ============ 数据源抽象接口 ============

class DataSourceInterface(ABC):
    """数据源抽象接口"""

    @abstractmethod
    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        pass

    @abstractmethod
    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        pass

    @abstractmethod
    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """获取数据源名称"""
        pass


# ============ Akshare数据源 ============

class AkshareDataSource(DataSourceInterface):
    """Akshare数据源 (免费)"""

    def get_source_name(self) -> str:
        return "akshare"

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare未安装，返回模拟数据")
            return self._generate_mock_cb_data()

        try:
            df = ak.bond_zh_cov()
            bonds = []
            for _, row in df.iterrows():
                try:
                    cb = ConvertibleBondData(
                        code=str(row.get('债券代码', '')),
                        name=str(row.get('债券简称', '')),
                        stock_code=str(row.get('正股代码', '')),
                        stock_name=str(row.get('正股简称', '')),
                        date=date.today(),
                        close=float(row.get('最新价', 0)),
                        change_pct=float(row.get('涨跌幅', 0)),
                        conversion_price=float(row.get('转股价', 0)),
                        conversion_value=float(row.get('转股价值', 0)),
                        conversion_premium=self._parse_premium(row.get('溢价率', 0)),
                        remaining_years=self._calc_remaining_years(row.get('到期日', '')),
                        volume=float(row.get('成交额', 0)),
                        daily_amount_20d=float(row.get('成交额', 0)),
                    )
                    bonds.append(cb)
                except Exception as e:
                    logger.debug(f"解析转债数据跳过: {e}")
                    continue

            logger.info(f"[Akshare] 获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"[Akshare] 获取可转债数据失败: {e}")
            return self._generate_mock_cb_data()

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        try:
            import akshare as ak
        except ImportError:
            return self._generate_mock_stock_data(stock_codes)

        stocks = {}
        try:
            df = ak.stock_zh_a_spot_em()
            for code in stock_codes:
                stock_row = df[df['代码'] == code]
                if not stock_row.empty:
                    row = stock_row.iloc[0]
                    stocks[code] = StockData(
                        code=code,
                        date=date.today(),
                        close=float(row.get('最新价', 0)),
                        change_pct=float(row.get('涨跌幅', 0)),
                        volume=float(row.get('成交量', 0)),
                        amount=float(row.get('成交额', 0)),
                        turnover_rate=float(row.get('换手率', 0)),
                    )
        except Exception as e:
            logger.warning(f"[Akshare] 获取正股数据失败: {e}")
            return self._generate_mock_stock_data(stock_codes)

        return stocks

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        try:
            import akshare as ak
            index_df = ak.index_zh_a_hist(symbol="000832", period="daily", adjust="qfq")
            latest = index_df.iloc[-1]
            return {
                'cb_index_close': float(latest['收盘']),
                'cb_index_change': float(latest['涨跌幅']),
                'cb_index_ma20': float(index_df['收盘'].rolling(20).mean().iloc[-1]),
            }
        except Exception as e:
            logger.debug(f"[DataAdapter] fetch_market_data failed: {e}")
            return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}

    def _parse_premium(self, val) -> float:
        """解析溢价率"""
        if isinstance(val, str):
            return float(val.replace('%', ''))
        return float(val) if val else 0.0

    def _calc_remaining_years(self, maturity_date: str) -> float:
        """计算剩余年限"""
        if maturity_date is None:
            return 3.0
        try:
            if isinstance(maturity_date, str):
                maturity = datetime.strptime(maturity_date, '%Y-%m-%d')
            else:
                maturity = maturity_date
            delta = maturity - datetime.now()
            return max(0, delta.days / 365)
        except Exception as e:
            logger.debug(f"[DataAdapter] _calc_remaining_years failed: {e}")
            return 3.0

    def _generate_mock_cb_data(self, n: int = 100) -> List[ConvertibleBondData]:
        """生成模拟数据"""
        np.random.seed(42)
        bonds = []
        for i in range(n):
            code = f"110{i+1:03d}"
            bonds.append(ConvertibleBondData(
                code=code,
                name=f"模拟转债{i+1}",
                stock_code=code.replace("110", "000"),
                stock_name=f"模拟股票{i+1}",
                date=date.today(),
                close=round(90 + np.random.random() * 40, 2),
                conversion_premium=round(5 + np.random.random() * 35, 2),
                remaining_years=round(0.5 + np.random.random() * 5, 2),
                daily_amount_20d=round(1000 + np.random.random() * 10000, 0),
                turnover_rate=round(0.5 + np.random.random() * 3, 2),
                conversion_price=round(10 + np.random.random() * 10, 2),
                stock_price=round(10 + np.random.random() * 20, 2),
            ))
        return bonds

    def _generate_mock_stock_data(self, codes: List[str]) -> Dict[str, StockData]:
        """生成模拟正股数据"""
        np.random.seed(42)
        return {
            code: StockData(
                code=code,
                date=date.today(),
                close=round(10 + np.random.random() * 20, 2),
                change_pct=round(np.random.randn() * 3, 2),
                turnover_rate=round(np.random.random() * 5, 2),
                volume_ratio=round(0.5 + np.random.random() * 2, 2),
            )
            for code in codes
        }


# ============ Wind数据源 ============

class WindDataSource(DataSourceInterface):
    """Wind数据源 (万得金融终端)"""

    def __init__(self, username: str = "", password: str = ""):
        """初始化Wind连接"""
        self.username = username
        self.password = password
        self._connected = False
        self._wind = None

    def get_source_name(self) -> str:
        return "wind"

    def connect(self) -> bool:
        """连接Wind"""
        try:
            from WindPy import w
            w.start()
            self._wind = w
            self._connected = True
            logger.info("[Wind] 连接成功")
            return True
        except ImportError:
            logger.warning("[Wind] WindPy未安装")
            return False
        except Exception as e:
            logger.error(f"[Wind] 连接失败: {e}")
            return False

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        if not self._connected:
            if not self.connect():
                return []

        try:
            # 获取可转债列表
            codes = self._wind.wset("sectorconstituent", "date=" + date.today().strftime("%Y-%m-%d") + ";sectorid=a001010100000000").Data[0]

            # 获取行情数据
            fields = "close,chg,pct_chg,conv_prc,conv_value,conv_prem,matu_dt,volume"
            data = self._wind.wsd(codes, fields, date.today().strftime("%Y-%m-%d"), "")

            bonds = []
            for i, code in enumerate(codes):
                bonds.append(ConvertibleBondData(
                    code=code,
                    name=f"转债{code[-3:]}",
                    stock_code=code.replace("11", "00"),
                    stock_name=f"股票{code[-3:]}",
                    date=date.today(),
                    close=data.Data[0][i] if data.Data[0] else 100,
                    conversion_premium=data.Data[5][i] if len(data.Data) > 5 else 20,
                    remaining_years=self._calc_remaining_years(data.Data[6][i]) if len(data.Data) > 6 else 3,
                    daily_amount_20d=data.Data[7][i] * 100 if len(data.Data) > 7 else 5000,
                ))

            logger.info(f"[Wind] 获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"[Wind] 获取数据失败: {e}")
            return []

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        if not self._connected:
            if not self.connect():
                return {}

        try:
            fields = "close,pct_chg,volume,amt,turn,vol_ratio"
            data = self._wind.wsd(stock_codes, fields, date.today().strftime("%Y-%m-%d"), "")

            stocks = {}
            for i, code in enumerate(stock_codes):
                stocks[code] = StockData(
                    code=code,
                    date=date.today(),
                    close=data.Data[0][i] if data.Data[0] else 10,
                    change_pct=data.Data[1][i] if len(data.Data) > 1 else 0,
                    volume=data.Data[2][i] if len(data.Data) > 2 else 0,
                    amount=data.Data[3][i] if len(data.Data) > 3 else 0,
                    turnover_rate=data.Data[4][i] if len(data.Data) > 4 else 0,
                    volume_ratio=data.Data[5][i] if len(data.Data) > 5 else 1,
                )
            return stocks

        except Exception as e:
            logger.error(f"[Wind] 获取正股数据失败: {e}")
            return {}

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        if not self._connected:
            if not self.connect():
                return {}

        try:
            data = self._wind.wsd("000832.CSI", "close,pct_chg", "ED-20D", date.today().strftime("%Y-%m-%d"), "")
            return {
                'cb_index_close': data.Data[0][-1] if data.Data[0] else 400,
                'cb_index_change': data.Data[1][-1] if len(data.Data) > 1 else 0,
                'cb_index_ma20': np.mean(data.Data[0]) if data.Data[0] else 400,
            }
        except Exception as e:
            logger.debug(f"[DataAdapter] WindDataSource fetch failed: {e}")
            return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}

    def _calc_remaining_years(self, maturity_date) -> float:
        """计算剩余年限"""
        if maturity_date is None:
            return 3.0
        try:
            delta = maturity_date - datetime.now()
            return max(0, delta.days / 365)
        except Exception as e:
            logger.debug(f"[DataAdapter] WindDataSource _calc_remaining_years failed: {e}")
            return 3.0


# ============ 聚宽数据源 ============

class JoinQuantDataSource(DataSourceInterface):
    """聚宽数据源"""

    def __init__(self, account: str = "", password: str = ""):
        self.account = account
        self.password = password
        self._auth = False

    def get_source_name(self) -> str:
        return "joinquant"

    def authenticate(self) -> bool:
        """认证聚宽账号"""
        try:
            import jqdatasdk as jq
            jq.auth(self.account, self.password)
            self._auth = True
            logger.info("[JoinQuant] 认证成功")
            return True
        except ImportError:
            logger.warning("[JoinQuant] jqdatasdk未安装")
            return False
        except Exception as e:
            logger.error(f"[JoinQuant] 认证失败: {e}")
            return False

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        if not self._auth:
            if not self.authenticate():
                return []

        try:
            import jqdatasdk as jq

            # 获取可转债列表
            q = jq.query(jq.bond.RUNNING).filter(jq.bond.RUNNING.list_status_cd == 'L')
            df = jq.get_bonds(q)

            bonds = []
            for _, row in df.iterrows():
                bonds.append(ConvertibleBondData(
                    code=row['code'],
                    name=row['display_name'],
                    stock_code=row['stock_code'],
                    stock_name=row['stock_display_name'],
                    date=date.today(),
                    close=row['close'],
                    conversion_premium=row['bond_premium'],
                    remaining_years=row['maturity_date'].year - date.today().year,
                    daily_amount_20d=row.get('money', 5000),
                ))

            logger.info(f"[JoinQuant] 获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"[JoinQuant] 获取数据失败: {e}")
            return []

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        if not self._auth:
            if not self.authenticate():
                return {}

        try:
            import jqdatasdk as jq
            df = jq.get_price(stock_codes, end_date=date.today(), count=1, frequency='daily')

            stocks = {}
            for code in stock_codes:
                if code in df:
                    row = df[code].iloc[0]
                    stocks[code] = StockData(
                        code=code,
                        date=date.today(),
                        close=row['close'],
                        volume=row['volume'],
                        amount=row['money'],
                    )
            return stocks

        except Exception as e:
            logger.error(f"[JoinQuant] 获取正股数据失败: {e}")
            return {}

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}


# ============ 米筐数据源 ============

class RiceQuantDataSource(DataSourceInterface):
    """米筐数据源"""

    def __init__(self, token: str = ""):
        self.token = token
        self._auth = False

    def get_source_name(self) -> str:
        return "ricequant"

    def authenticate(self) -> bool:
        """认证米筐"""
        try:
            import rqdatac as rq
            rq.init(self.token)
            self._auth = True
            logger.info("[RiceQuant] 认证成功")
            return True
        except ImportError:
            logger.warning("[RiceQuant] rqdatac未安装")
            return False
        except Exception as e:
            logger.error(f"[RiceQuant] 认证失败: {e}")
            return False

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        if not self._auth:
            if not self.authenticate():
                return []

        try:
            import rqdatac as rq
            df = rq.get_all_convertibles(date.today())

            bonds = []
            for _, row in df.iterrows():
                bonds.append(ConvertibleBondData(
                    code=row['order_book_id'],
                    name=row['symbol'],
                    stock_code=row['stock_order_book_id'],
                    stock_name=row['stock_symbol'],
                    date=date.today(),
                    close=row['close'],
                    conversion_premium=row.get('conversion_premium', 20),
                ))

            logger.info(f"[RiceQuant] 获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"[RiceQuant] 获取数据失败: {e}")
            return []

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        if not self._auth:
            if not self.authenticate():
                return {}

        try:
            import rqdatac as rq
            df = rq.get_price(stock_codes, end_date=date.today(), count=1, frequency='1d')

            stocks = {}
            for code in stock_codes:
                if code in df:
                    row = df[code].iloc[0]
                    stocks[code] = StockData(
                        code=code,
                        date=date.today(),
                        close=row['close'],
                        volume=row['volume'],
                    )
            return stocks

        except Exception as e:
            logger.error(f"[RiceQuant] 获取正股数据失败: {e}")
            return {}

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}


# ============ Tushare数据源 ============

class TushareDataSource(DataSourceInterface):
    """Tushare数据源"""

    def __init__(self, token: str = ""):
        self.token = token
        self._pro = None

    def get_source_name(self) -> str:
        return "tushare"

    def authenticate(self) -> bool:
        """认证Tushare"""
        try:
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()
            logger.info("[Tushare] 认证成功")
            return True
        except ImportError:
            logger.warning("[Tushare] tushare未安装")
            return False
        except Exception as e:
            logger.error(f"[Tushare] 认证失败: {e}")
            return False

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        if not self._pro:
            if not self.authenticate():
                return []

        try:
            df = self._pro.cb_daily(trade_date=date.today().strftime("%Y%m%d"))

            bonds = []
            for _, row in df.iterrows():
                bonds.append(ConvertibleBondData(
                    code=row['ts_code'].split('.')[0],
                    name=row['name'],
                    stock_code=row['stk_code'],
                    stock_name=row['stk_name'],
                    date=date.today(),
                    close=row['close'],
                    change_pct=row['pct_chg'],
                    volume=row['vol'],
                ))

            logger.info(f"[Tushare] 获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"[Tushare] 获取数据失败: {e}")
            return []

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        if not self._pro:
            if not self.authenticate():
                return {}

        try:
            df = self._pro.daily(ts_code=','.join(stock_codes), trade_date=date.today().strftime("%Y%m%d"))

            stocks = {}
            for _, row in df.iterrows():
                code = row['ts_code'].split('.')[0]
                stocks[code] = StockData(
                    code=code,
                    date=date.today(),
                    close=row['close'],
                    change_pct=row['pct_chg'],
                    volume=row['vol'],
                    amount=row['amount'],
                )
            return stocks

        except Exception as e:
            logger.error(f"[Tushare] 获取正股数据失败: {e}")
            return {}

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}


# ============ 统一数据适配器 ============


class DataAdapter:
    """数据适配器 - 对接akshare"""

    def __init__(self):
        """初始化"""
        self._cb_cache: Dict[str, ConvertibleBondData] = {}
        self._stock_cache: Dict[str, StockData] = {}
        self._last_update: Optional[datetime] = None

    def fetch_all_cb_data(self) -> List[ConvertibleBondData]:
        """获取所有可转债数据"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare未安装，返回模拟数据")
            return self._generate_mock_cb_data()

        try:
            # 获取可转债实时行情
            df = ak.bond_zh_cov()

            bonds = []
            for _, row in df.iterrows():
                try:
                    cb = ConvertibleBondData(
                        code=str(row.get('债券代码', '')),
                        name=str(row.get('债券简称', '')),
                        stock_code=str(row.get('正股代码', '')),
                        stock_name=str(row.get('正股简称', '')),
                        date=date.today(),
                        close=float(row.get('最新价', 0)),
                        change_pct=float(row.get('涨跌幅', 0)),
                        conversion_price=float(row.get('转股价', 0)),
                        conversion_value=float(row.get('转股价值', 0)),
                        conversion_premium=float(row.get('溢价率', 0).replace('%', '') if isinstance(row.get('溢价率'), str) else row.get('溢价率', 0)),
                        remaining_years=self._calc_remaining_years(row.get('到期日', '')),
                        volume=float(row.get('成交额', 0)),
                    )
                    bonds.append(cb)
                except Exception as e:
                    logger.warning(f"解析转债数据失败: {e}")
                    continue

            logger.info(f"获取到{len(bonds)}只可转债数据")
            return bonds

        except Exception as e:
            logger.error(f"获取可转债数据失败: {e}")
            return self._generate_mock_cb_data()

    def fetch_stock_data(self, stock_codes: List[str]) -> Dict[str, StockData]:
        """获取正股数据"""
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare未安装，返回模拟数据")
            return self._generate_mock_stock_data(stock_codes)

        stocks = {}
        for code in stock_codes:
            try:
                # 获取个股行情
                df = ak.stock_zh_a_spot_em()
                stock_row = df[df['代码'] == code]

                if not stock_row.empty:
                    row = stock_row.iloc[0]
                    stocks[code] = StockData(
                        code=code,
                        date=date.today(),
                        close=float(row.get('最新价', 0)),
                        change_pct=float(row.get('涨跌幅', 0)),
                        volume=float(row.get('成交量', 0)),
                        amount=float(row.get('成交额', 0)),
                        turnover_rate=float(row.get('换手率', 0)),
                    )
            except Exception as e:
                logger.warning(f"获取正股{code}数据失败: {e}")
                continue

        return stocks

    def fetch_market_data(self) -> Dict:
        """获取市场数据"""
        try:
            import akshare as ak

            # 转债指数
            index_df = ak.index_zh_a_hist(symbol="000832", period="daily", adjust="qfq")
            latest = index_df.iloc[-1]

            return {
                'cb_index_close': float(latest['收盘']),
                'cb_index_change': float(latest['涨跌幅']),
                'cb_index_ma20': float(index_df['收盘'].rolling(20).mean().iloc[-1]),
            }
        except Exception as e:
            logger.warning(f"获取市场数据失败: {e}")
            return {
                'cb_index_close': 400.0,
                'cb_index_change': 0.0,
                'cb_index_ma20': 400.0,
            }

    def _calc_remaining_years(self, maturity_date: str) -> float:
        """计算剩余年限"""
        if maturity_date is None:
            return 3.0

        try:
            if isinstance(maturity_date, str):
                maturity = datetime.strptime(maturity_date, '%Y-%m-%d')
            else:
                maturity = maturity_date

            delta = maturity - datetime.now()
            return max(0, delta.days / 365)
        except Exception as e:
            logger.debug(f"[DataAdapter] RiceQuantDataSource _calc_remaining_years failed: {e}")
            return 3.0

    def _generate_mock_cb_data(self, n: int = 100) -> List[ConvertibleBondData]:
        """生成模拟可转债数据"""
        np.random.seed(42)

        bonds = []
        for i in range(n):
            code = f"110{i+1:03d}"
            bonds.append(ConvertibleBondData(
                code=code,
                name=f"模拟转债{i+1}",
                stock_code=code.replace("110", "000"),
                stock_name=f"模拟股票{i+1}",
                date=date.today(),
                close=round(90 + np.random.random() * 40, 2),
                change_pct=round(np.random.randn() * 3, 2),
                conversion_price=round(10 + np.random.random() * 10, 2),
                conversion_value=round(80 + np.random.random() * 40, 2),
                conversion_premium=round(5 + np.random.random() * 35, 2),
                remaining_years=round(0.5 + np.random.random() * 5, 2),
                volume=round(1000 + np.random.random() * 10000, 0),
                daily_amount_20d=round(1000 + np.random.random() * 10000, 0),
                issuer_rating=np.random.choice(['AAA', 'AA+', 'AA', 'AA-', 'A+']),
            ))

        return bonds

    def _generate_mock_stock_data(self, codes: List[str]) -> Dict[str, StockData]:
        """生成模拟正股数据"""
        np.random.seed(42)

        stocks = {}
        for code in codes:
            stocks[code] = StockData(
                code=code,
                date=date.today(),
                close=round(10 + np.random.random() * 20, 2),
                change_pct=round(np.random.randn() * 3, 2),
                turnover_rate=round(np.random.random() * 5, 2),
                volume_ratio=round(0.5 + np.random.random() * 2, 2),
                debt_ratio=round(30 + np.random.random() * 40, 1),
            )

        return stocks


class DataCache:
    """数据缓存"""

    def __init__(self, ttl_seconds: int = 60):
        """初始化

        Args:
            ttl_seconds: 缓存有效期(秒)
        """
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple] = {}  # {key: (data, timestamp)}

    def get(self, key: str) -> Optional[any]:
        """获取缓存"""
        if key not in self._cache:
            return None

        data, timestamp = self._cache[key]
        if (datetime.now() - timestamp).total_seconds() > self.ttl:
            del self._cache[key]
            return None

        return data

    def set(self, key: str, data: any) -> None:
        """设置缓存"""
        self._cache[key] = (data, datetime.now())

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


class RealTimeQuoteProvider:
    """实时行情提供者"""

    def __init__(self, adapter: DataAdapter, cache_ttl: int = 30):
        """初始化

        Args:
            adapter: 数据适配器
            cache_ttl: 缓存有效期(秒)
        """
        self.adapter = adapter
        self.cache = DataCache(cache_ttl)

    def get_all_quotes(self) -> List[ConvertibleBondData]:
        """获取所有实时行情"""
        cache_key = "all_quotes"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        quotes = self.adapter.fetch_all_cb_data()
        self.cache.set(cache_key, quotes)
        return quotes

    def get_quote(self, code: str) -> Optional[ConvertibleBondData]:
        """获取单只行情"""
        quotes = self.get_all_quotes()
        for q in quotes:
            if q.code == code:
                return q
        return None

    def get_quotes_by_codes(self, codes: List[str]) -> List[ConvertibleBondData]:
        """获取多只行情"""
        quotes = self.get_all_quotes()
        code_set = set(codes)
        return [q for q in quotes if q.code in code_set]


class HistoricalDataProvider:
    """历史数据提供者"""

    def get_cb_history(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """获取可转债历史数据"""
        try:
            import akshare as ak

            df = ak.bond_zh_hs_daily(symbol=code)
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            return df

        except Exception as e:
            logger.warning(f"获取历史数据失败: {e}")
            return pd.DataFrame()

    def get_stock_history(
        self,
        code: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """获取正股历史数据"""
        try:
            import akshare as ak

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq"
            )
            return df

        except Exception as e:
            logger.warning(f"获取正股历史数据失败: {e}")
            return pd.DataFrame()


# ============ 统一数据源管理器 ============

class DataSourceManager:
    """数据源管理器 - 统一管理多个数据源"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._sources: Dict[str, DataSourceInterface] = {}
        self._default_source: str = "akshare"
        self._fallback_order: List[str] = ["akshare"]

        # 注册默认数据源
        self.register_source("akshare", AkshareDataSource())

    def register_source(self, name: str, source: DataSourceInterface) -> None:
        """注册数据源

        Args:
            name: 数据源名称
            source: 数据源实例
        """
        self._sources[name] = source
        logger.info(f"[DataSourceManager] 注册数据源: {name}")

    def set_default_source(self, name: str) -> bool:
        """设置默认数据源

        Args:
            name: 数据源名称

        Returns:
            是否设置成功
        """
        if name in self._sources:
            self._default_source = name
            logger.info(f"[DataSourceManager] 默认数据源设置为: {name}")
            return True
        logger.warning(f"[DataSourceManager] 数据源不存在: {name}")
        return False

    def set_fallback_order(self, sources: List[str]) -> None:
        """设置数据源降级顺序

        Args:
            sources: 数据源名称列表（按优先级排序）
        """
        self._fallback_order = [s for s in sources if s in self._sources]
        logger.info(f"[DataSourceManager] 降级顺序: {self._fallback_order}")

    def get_source(self, name: Optional[str] = None) -> Optional[DataSourceInterface]:
        """获取数据源

        Args:
            name: 数据源名称（None则返回默认）

        Returns:
            数据源实例
        """
        source_name = name or self._default_source
        return self._sources.get(source_name)

    def fetch_all_cb_data(self, source: Optional[str] = None) -> List[ConvertibleBondData]:
        """获取所有可转债数据（支持降级）

        Args:
            source: 指定数据源（None则使用默认和降级）

        Returns:
            可转债数据列表
        """
        if source:
            src = self._sources.get(source)
            if src:
                data = src.fetch_all_cb_data()
                if data:
                    return data
            return []

        # 按降级顺序尝试
        for src_name in self._fallback_order:
            src = self._sources.get(src_name)
            if src:
                try:
                    data = src.fetch_all_cb_data()
                    if data:
                        logger.info(f"[DataSourceManager] 使用数据源: {src_name}")
                        return data
                except Exception as e:
                    logger.warning(f"[DataSourceManager] 数据源{src_name}失败: {e}")
                    continue

        return []

    def fetch_stock_data(self, stock_codes: List[str], source: Optional[str] = None) -> Dict[str, StockData]:
        """获取正股数据（支持降级）"""
        if source:
            src = self._sources.get(source)
            if src:
                return src.fetch_stock_data(stock_codes)
            return {}

        for src_name in self._fallback_order:
            src = self._sources.get(src_name)
            if src:
                try:
                    data = src.fetch_stock_data(stock_codes)
                    if data:
                        return data
                except Exception as e:
                    logger.debug(f"[DataAdapter] Fallback fetch_stock_data from {src_name} failed: {e}")
                    continue

        return {}

    def fetch_market_data(self, source: Optional[str] = None) -> Dict:
        """获取市场数据"""
        if source:
            src = self._sources.get(source)
            if src:
                return src.fetch_market_data()
            return {}

        for src_name in self._fallback_order:
            src = self._sources.get(src_name)
            if src:
                try:
                    data = src.fetch_market_data()
                    if data:
                        return data
                except Exception as e:
                    logger.debug(f"[DataAdapter] Fallback fetch_market_data from {src_name} failed: {e}")
                    continue

        return {'cb_index_close': 400.0, 'cb_index_change': 0.0, 'cb_index_ma20': 400.0}

    def list_sources(self) -> List[str]:
        """列出所有已注册数据源"""
        return list(self._sources.keys())

    def get_source_status(self) -> Dict[str, bool]:
        """获取所有数据源状态"""
        status = {}
        for name, source in self._sources.items():
            try:
                # 尝试获取少量数据测试连通性
                data = source.fetch_all_cb_data()
                status[name] = len(data) > 0
            except Exception as e:
                logger.debug(f"[DataAdapter] get_source_status for {name} failed: {e}")
                status[name] = False
        return status


# 便捷函数
def get_data_manager() -> DataSourceManager:
    """获取数据源管理器单例"""
    return DataSourceManager()


def setup_data_sources(
    akshare: bool = True,
    wind: Optional[Dict] = None,
    joinquant: Optional[Dict] = None,
    ricequant: Optional[Dict] = None,
    tushare: Optional[Dict] = None,
    default: str = "akshare",
) -> DataSourceManager:
    """配置数据源

    Args:
        akshare: 是否启用Akshare
        wind: Wind配置 {"username": "", "password": ""}
        joinquant: 聚宽配置 {"account": "", "password": ""}
        ricequant: 米筐配置 {"token": ""}
        tushare: Tushare配置 {"token": ""}
        default: 默认数据源

    Returns:
        数据源管理器
    """
    manager = get_data_manager()

    if akshare:
        manager.register_source("akshare", AkshareDataSource())

    if wind:
        manager.register_source("wind", WindDataSource(**wind))

    if joinquant:
        manager.register_source("joinquant", JoinQuantDataSource(**joinquant))

    if ricequant:
        manager.register_source("ricequant", RiceQuantDataSource(**ricequant))

    if tushare:
        manager.register_source("tushare", TushareDataSource(**tushare))

    manager.set_default_source(default)

    return manager
