"""松岗量化可转债策略 V3.0 主策略类

整合所有模块，提供统一的策略运行入口

日志系统:
- 结构化JSON日志
- 日志级别动态调整
- 性能监控日志
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Any
import pandas as pd
import logging
import json
import time
import os

from app.sg_strategy.core.types import (
    ConvertibleBondData, StockData, SevenDimScore, CreditScore,
    TimingSignal, TradeSignal, Portfolio, Position, DailyReport,
    HedgeStatus,
)
from app.sg_strategy.config.settings import params
from app.sg_strategy.config.weights import MarketRegime, detect_market_regime

# 导入各模块
from app.sg_strategy.core.filters import VetoFilter, EnhancedVetoFilter
from app.sg_strategy.core.scoring import SevenDimScoringEngine
from app.sg_strategy.core.whitelist import WhitelistManager, EnhancedWhitelistManager
from app.sg_strategy.core.timing import TimingEngine, EnhancedTimingEngine, MarketData
from app.sg_strategy.core.credit import CreditScoringEngine, EnhancedCreditEngine
from app.sg_strategy.core.cost import TransactionCostModel, CostController
from app.sg_strategy.core.signals import SignalGenerator, HFTSignalGenerator
from app.sg_strategy.core.events import EventDrivenEngine
from app.sg_strategy.core.hedge import HedgeEngine
from app.sg_strategy.core.execution import ExecutionEngine
from app.sg_strategy.core.monitor import DailyMonitor, FactorAnalyzer, BrinsonAttributor


# ============ 结构化日志配置 ============

class StructuredLogger:
    """结构化日志记录器"""

    def __init__(self, name: str, log_level: str = "INFO"):
        """初始化

        Args:
            name: 日志名称
            log_level: 日志级别
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # 添加JSON格式handler（如果还没有）
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            self.logger.addHandler(handler)

        # 添加文件handler（可选）
        log_dir = os.environ.get('SG_STRATEGY_LOG_DIR', '/tmp/sg_strategy_logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = logging.FileHandler(
            f'{log_dir}/strategy_{datetime.now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        )
        file_handler.setFormatter(JsonFormatter())
        self.logger.addHandler(file_handler)

    def log(self, level: str, message: str, **kwargs):
        """记录结构化日志"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            **kwargs
        }
        getattr(self.logger, level.lower())(json.dumps(log_data, ensure_ascii=False))

    def info(self, message: str, **kwargs):
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs):
        self.log("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs):
        self.log("DEBUG", message, **kwargs)


class JsonFormatter(logging.Formatter):
    """JSON格式日志格式化器"""

    def format(self, record):
        try:
            # 尝试解析已有的JSON
            if record.msg.startswith('{'):
                return record.msg
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.msg,
                "module": record.module,
                "line": record.lineno,
            }
            return json.dumps(log_entry, ensure_ascii=False)
        except Exception:
            return super().format(record)


def setup_logging(log_level: str = "INFO", json_format: bool = True):
    """配置日志系统

    Args:
        log_level: 日志级别
        json_format: 是否使用JSON格式
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 清除现有handlers
    root_logger.handlers = []

    if json_format:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root_logger.addHandler(handler)
    else:
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )


# 创建策略logger
logger = StructuredLogger(__name__)


class SGConvertibleStrategy:
    """松岗量化可转债策略 V3.0 主类"""

    def __init__(
        self,
        aum: float = 10000.0,
        regime: MarketRegime = MarketRegime.RANGE,
        log_level: str = "INFO",
    ):
        """初始化策略

        Args:
            aum: 资产规模(万元)
            regime: 市场环境
            log_level: 日志级别
        """
        self.aum = aum
        self.regime = regime
        self.log_level = log_level

        # 初始化各模块
        self.veto_filter = EnhancedVetoFilter(aum)
        self.scoring_engine = SevenDimScoringEngine(regime, aum)
        self.whitelist_manager = EnhancedWhitelistManager(aum, regime)
        self.timing_engine = EnhancedTimingEngine()
        self.credit_engine = EnhancedCreditEngine()
        self.signal_generator = SignalGenerator(aum)
        self.hft_generator = HFTSignalGenerator(aum)
        self.event_engine = EventDrivenEngine()
        self.hedge_engine = HedgeEngine(aum)
        self.execution_engine = ExecutionEngine(aum)
        self.daily_monitor = DailyMonitor(aum)
        self.factor_analyzer = FactorAnalyzer()
        self.brison_attributor = BrinsonAttributor()

        # 组合状态
        self.portfolio = Portfolio(date=date.today(), aum=aum, cash=aum)
        self.whitelist: List[str] = []
        self.buffer_zone: List[str] = []
        self.scores: List[SevenDimScore] = []
        self.timing_signal: Optional[TimingSignal] = None
        self.credit_scores: Dict[str, CreditScore] = {}

        # 每日报告
        self._daily_reports: List[DailyReport] = []

        logger.info(f"[Strategy] 初始化完成: AUM={aum}万, 环境={regime.value}")

    def run_daily(
        self,
        cb_data: List[ConvertibleBondData],
        stock_data: Optional[Dict[str, StockData]] = None,
        market_data: Optional[MarketData] = None,
        current_date: Optional[date] = None,
    ) -> DailyReport:
        """运行每日策略

        Args:
            cb_data: 可转债数据列表
            stock_data: 正股数据字典
            market_data: 市场数据
            current_date: 当前日期

        Returns:
            DailyReport: 每日报告
        """
        current_date = current_date or date.today()
        start_time = time.time()

        logger.info("策略开始运行", date=str(current_date), aum=self.aum, regime=self.regime.value)

        # 1. 一票否决过滤
        step_start = time.time()
        passed_bonds, veto_results = self.veto_filter.filter_bonds(
            cb_data, stock_data, self.credit_scores
        )
        logger.info("一票否决过滤完成",
                    passed_count=len(passed_bonds),
                    total_count=len(cb_data),
                    duration_ms=round((time.time() - step_start) * 1000, 2))

        if not passed_bonds:
            logger.warning("无通过过滤的转债", total_count=len(cb_data))
            return self._create_empty_report(current_date)

        # 2. 计算信用评分
        step_start = time.time()
        for cb in passed_bonds:
            stock = stock_data.get(cb.stock_code) if stock_data else None
            self.credit_scores[cb.code] = self.credit_engine.calculate_credit_score(
                cb, stock
            )
        logger.debug("信用评分计算完成", count=len(passed_bonds))

        # 3. 计算七维得分
        step_start = time.time()
        self.scores = self.scoring_engine.score_all_bonds(
            passed_bonds, stock_data, self.credit_scores
        )
        logger.info("七维得分计算完成",
                    max_score=round(self.scores[0].total_score, 1) if self.scores else 0,
                    min_score=round(self.scores[-1].total_score, 1) if self.scores else 0,
                    duration_ms=round((time.time() - step_start) * 1000, 2))

        # 4. 多维度综合择时
        if market_data:
            step_start = time.time()
            self.timing_signal = self.timing_engine.calculate_timing(market_data)
            self.regime, confirmed = self.timing_engine.get_regime_with_confirmation(market_data)
            if confirmed:
                self.scoring_engine.update_regime(self.regime)
                self.whitelist_manager.update_regime(self.regime)
            logger.info("择时信号计算完成",
                        timing_score=round(self.timing_signal.total_score, 1),
                        position_ratio=round(self.timing_signal.position_ratio * 100, 1),
                        regime=self.regime.value,
                        confirmed=confirmed,
                        duration_ms=round((time.time() - step_start) * 1000, 2))

        # 5. 更新白名单
        step_start = time.time()
        whitelist_state = self.whitelist_manager.update_whitelist(self.scores, current_date)
        self.whitelist = whitelist_state.whitelist
        self.buffer_zone = whitelist_state.buffer_zone
        logger.info("白名单更新完成",
                    whitelist_count=len(self.whitelist),
                    buffer_count=len(self.buffer_zone),
                    duration_ms=round((time.time() - step_start) * 1000, 2))

        # 6. 生成交易信号
        step_start = time.time()
        cb_dict = {cb.code: cb for cb in cb_data}
        signals = self.signal_generator.generate_signals(
            self.portfolio,
            self.scores,
            self.whitelist,
            self.buffer_zone,
            cb_dict,
            self.credit_scores,
            current_date,
        )
        logger.info("交易信号生成完成",
                    signal_count=len(signals),
                    buy_count=sum(1 for s in signals if 'BUY' in s.action.value),
                    sell_count=sum(1 for s in signals if 'SELL' in s.action.value),
                    duration_ms=round((time.time() - step_start) * 1000, 2))

        # 7. 执行交易
        step_start = time.time()
        prices = {cb.code: cb.close for cb in cb_data}
        daily_amounts = {cb.code: cb.daily_amount_20d for cb in cb_data}
        execution_results = self.execution_engine.process_signals(
            signals, self.portfolio, prices, daily_amounts
        )
        success_count = sum(1 for r in execution_results if r.success)
        logger.info("交易执行完成",
                    success_count=success_count,
                    fail_count=len(execution_results) - success_count,
                    duration_ms=round((time.time() - step_start) * 1000, 2))

        # 8. 更新组合市值
        self._update_portfolio_values(cb_dict)

        # 9. 事件驱动策略扫描
        event_opportunities = self.event_engine.scan_opportunities(cb_data, stock_data)

        # 10. 更新对冲状态
        if market_data and self.timing_signal:
            # 简化的对冲检查
            hedge_status = self.hedge_engine.get_status()

        # 11. 生成每日报告
        report = self._create_daily_report(
            current_date, signals, execution_results
        )
        self._daily_reports.append(report)

        # 总耗时
        total_duration = time.time() - start_time

        logger.info("策略日终完成",
                    aum=round(self.portfolio.aum, 2),
                    cash=round(self.portfolio.cash, 2),
                    position_count=len(self.portfolio.positions),
                    market_value=round(self.portfolio.total_market_value, 2),
                    total_duration_ms=round(total_duration * 1000, 2))

        return report

    def _update_portfolio_values(self, cb_dict: Dict[str, ConvertibleBondData]):
        """更新组合市值"""
        total_mv_yuan = 0  # 总市值(元)
        sector_mv: Dict[str, float] = {}

        for code, pos in self.portfolio.positions.items():
            cb = cb_dict.get(code)
            if cb:
                pos.current_price = cb.close
                pos.market_value = pos.current_price * pos.quantity  # 元
                pos.unrealized_pnl = pos.market_value - pos.cost_basis
                pos.unrealized_pnl_pct = pos.unrealized_pnl / pos.cost_basis if pos.cost_basis > 0 else 0

                total_mv_yuan += pos.market_value

                # 行业统计
                sector = getattr(cb, 'sector', 'unknown')
                sector_mv[sector] = sector_mv.get(sector, 0) + pos.market_value

        # 转换为万元
        total_mv_wan = total_mv_yuan / 10000
        self.portfolio.total_market_value = total_mv_wan
        self.portfolio.aum = self.portfolio.cash + total_mv_wan
        self.portfolio.position_count = len(self.portfolio.positions)

        # 更新行业仓位比例
        if total_mv_yuan > 0:
            self.portfolio.sector_positions = {
                sector: mv / total_mv_yuan for sector, mv in sector_mv.items()
            }

    def _create_daily_report(
        self,
        current_date: date,
        signals: List[TradeSignal],
        execution_results: List[dict],
    ) -> DailyReport:
        """创建每日报告"""
        return DailyReport(
            date=current_date,
            portfolio=self.portfolio,
            timing=self.timing_signal or TimingSignal(date=current_date),
            signals=signals,
            costs={r.order.cb_code: r.cost for r in execution_results if hasattr(r, 'cost')},
            whitelist=self.whitelist,
            hedge=self.hedge_engine.get_status(),
            performance={
                "aum": self.portfolio.aum,
                "cash": self.portfolio.cash,
                "positions": len(self.portfolio.positions),
                "total_pnl": self.portfolio.total_unrealized_pnl,
            },
        )

    def _create_empty_report(self, current_date: date) -> DailyReport:
        """创建空报告"""
        return DailyReport(
            date=current_date,
            portfolio=self.portfolio,
            timing=TimingSignal(date=current_date),
            signals=[],
            costs={},
            whitelist=[],
            hedge=HedgeStatus(),
            performance={},
        )

    def get_whitelist(self) -> List[str]:
        """获取当前白名单"""
        return self.whitelist

    def get_positions(self) -> Dict[str, Position]:
        """获取当前持仓"""
        return self.portfolio.positions

    def get_performance_summary(self) -> dict:
        """获取绩效汇总"""
        return {
            "aum": round(self.portfolio.aum, 2),
            "cash": round(self.portfolio.cash, 2),
            "position_count": len(self.portfolio.positions),
            "total_market_value": round(self.portfolio.total_market_value, 2),
            "total_unrealized_pnl": round(self.portfolio.total_unrealized_pnl, 2),
            "whitelist_size": len(self.whitelist),
            "buffer_zone_size": len(self.buffer_zone),
        }

    def update_aum(self, new_aum: float):
        """更新资产规模"""
        self.aum = new_aum
        self.veto_filter.update_aum(new_aum)
        self.whitelist_manager.update_aum(new_aum)
        self.hedge_engine.aum = new_aum
        self.execution_engine.aum = new_aum
        self.signal_generator.aum = new_aum
        logger.info(f"[Strategy] AUM更新: {new_aum}万")

    def get_report_history(self, days: int = 30) -> List[DailyReport]:
        """获取历史报告"""
        return self._daily_reports[-days:]


# 导出
__all__ = [
    "SGConvertibleStrategy",
    "VetoFilter",
    "SevenDimScoringEngine",
    "WhitelistManager",
    "TimingEngine",
    "CreditScoringEngine",
    "TransactionCostModel",
    "SignalGenerator",
    "EventDrivenEngine",
    "HedgeEngine",
    "ExecutionEngine",
    "DailyMonitor",
    "FactorAnalyzer",
    "BrinsonAttributor",
]
