"""西部量化可转债策略 V3.0 交易信号生成器

买入信号:
- 未触发一票否决
- 进入前60名白名单
- 七维得分分级买入

卖出信号:
- 阶梯止盈
- 刚性止损
- 白名单止损
- 信用止损
- 极端止损
- 强制卖出
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
import uuid
import logging

from app.xb_strategy.core.types import (
    TradeSignal, SignalType, TradeAction, Position, Portfolio,
    SevenDimScore, CreditScore, ConvertibleBondData,
)
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class SignalContext:
    """信号上下文"""
    date: date
    position: Position
    score: SevenDimScore
    credit: Optional[CreditScore]
    cb: ConvertibleBondData
    in_whitelist: bool
    in_buffer: bool


class SignalGenerator:
    """交易信号生成器"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self._signals_today: List[TradeSignal] = []
        self._last_signal_date: Optional[date] = None

    def generate_signals(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        whitelist: List[str],
        buffer_zone: List[str],
        cb_data: Dict[str, ConvertibleBondData],
        credit_scores: Optional[Dict[str, CreditScore]] = None,
        current_date: Optional[date] = None,
    ) -> List[TradeSignal]:
        """生成交易信号

        Args:
            portfolio: 当前组合
            scores: 七维得分列表
            whitelist: 白名单
            buffer_zone: 缓冲带
            cb_data: 可转债数据
            credit_scores: 信用评分
            current_date: 当前日期

        Returns:
            交易信号列表
        """
        current_date = current_date or date.today()

        # 新的一天，清空信号
        if self._last_signal_date != current_date:
            self._signals_today = []
            self._last_signal_date = current_date

        signals = []

        # 1. 检查现有持仓的卖出信号
        sell_signals = self._check_sell_signals(
            portfolio, scores, whitelist, buffer_zone, cb_data, credit_scores, current_date
        )
        signals.extend(sell_signals)

        # 2. 检查买入信号
        buy_signals = self._check_buy_signals(
            portfolio, scores, whitelist, cb_data, current_date
        )
        signals.extend(buy_signals)

        # 3. 检查加仓信号
        add_signals = self._check_add_position_signals(
            portfolio, scores, cb_data, current_date
        )
        signals.extend(add_signals)

        self._signals_today = signals
        return signals

    def _check_sell_signals(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        whitelist: List[str],
        buffer_zone: List[str],
        cb_data: Dict[str, ConvertibleBondData],
        credit_scores: Optional[Dict[str, CreditScore]],
        current_date: date,
    ) -> List[TradeSignal]:
        """检查卖出信号"""
        signals = []

        for code, pos in portfolio.positions.items():
            score = next((s for s in scores if s.cb_code == code), None)
            cb = cb_data.get(code)
            credit = credit_scores.get(code) if credit_scores else None

            if not score or not cb:
                # 数据缺失，发出卖出信号
                signals.append(self._create_signal(
                    code=code,
                    cb_name=pos.cb_name,
                    action=TradeAction.SELL,
                    signal_type=SignalType.FORCE_EXIT,
                    price=pos.current_price,
                    reason="数据缺失",
                    urgency=2,
                ))
                continue

            context = SignalContext(
                date=current_date,
                position=pos,
                score=score,
                credit=credit,
                cb=cb,
                in_whitelist=code in whitelist,
                in_buffer=code in buffer_zone,
            )

            # 检查各类止损/卖出条件
            signal = self._check_single_position(context)
            if signal:
                signals.append(signal)

        return signals

    def _check_single_position(self, ctx: SignalContext) -> Optional[TradeSignal]:
        """检查单个持仓的卖出条件"""

        # 1. 强制卖出条件
        if ctx.cb.is_called:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.FORCE_EXIT,
                price=ctx.position.current_price,
                reason="已发布强赎公告",
                urgency=2,
            )

        if ctx.cb.remaining_years < 0.25:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.FORCE_EXIT,
                price=ctx.position.current_price,
                reason="剩余期限<3个月",
                urgency=1,
            )

        if ctx.cb.conversion_premium > 120:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.FORCE_EXIT,
                price=ctx.position.current_price,
                reason="转股溢价率>120%",
                urgency=1,
            )

        # 2. 信用止损
        if ctx.credit and ctx.credit.total_score < params.credit_stop_threshold:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.CREDIT_EXIT,
                price=ctx.position.current_price,
                reason=f"信用评分({ctx.credit.total_score:.0f})<{params.credit_stop_threshold}",
                urgency=2,
            )

        # 3. 得分止损
        if ctx.score.total_score < params.score_stop_threshold:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.SCORE_EXIT,
                price=ctx.position.current_price,
                reason=f"七维得分({ctx.score.total_score:.0f})<{params.score_stop_threshold}",
                urgency=1,
            )

        # 4. 白名单止损
        if not ctx.in_whitelist and not ctx.in_buffer:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.WHITELIST_EXIT,
                price=ctx.position.current_price,
                reason="跌出白名单且不在缓冲带",
                urgency=1,
            )

        # 5. 极端止损
        pnl_pct = ctx.position.unrealized_pnl_pct
        if pnl_pct <= -params.extreme_stop_daily:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.EXTREME_EXIT,
                price=ctx.position.current_price,
                reason=f"单日亏损{abs(pnl_pct):.1f}%>={params.extreme_stop_daily}%",
                urgency=2,
            )

        # 6. 常规止损
        if pnl_pct <= -params.stop_loss_pct:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.STOP_LOSS,
                price=ctx.position.current_price,
                reason=f"亏损{abs(pnl_pct):.1f}%>={params.stop_loss_pct}%",
                urgency=2,
            )

        # 7. 阶梯止盈
        if pnl_pct >= params.take_profit_tier3:
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.TAKE_PROFIT,
                price=ctx.position.current_price,
                reason=f"盈利{pnl_pct:.1f}%>={params.take_profit_tier3}%，全部止盈",
                quantity=ctx.position.quantity,  # 全部卖出
                urgency=0,
            )

        if pnl_pct >= params.take_profit_tier2 and not ctx.position.tp2_triggered:
            sell_qty = int(ctx.position.quantity * params.tp2_sell_ratio)
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.TAKE_PROFIT,
                price=ctx.position.current_price,
                reason=f"盈利{pnl_pct:.1f}%>={params.take_profit_tier2}%，卖出{params.tp2_sell_ratio*100:.0f}%",
                quantity=sell_qty,
                urgency=0,
            )

        if pnl_pct >= params.take_profit_tier1 and not ctx.position.tp1_triggered:
            sell_qty = int(ctx.position.quantity * params.tp1_sell_ratio)
            return self._create_signal(
                code=ctx.position.cb_code,
                cb_name=ctx.position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.TAKE_PROFIT,
                price=ctx.position.current_price,
                reason=f"盈利{pnl_pct:.1f}%>={params.take_profit_tier1}%，卖出{params.tp1_sell_ratio*100:.0f}%",
                quantity=sell_qty,
                urgency=0,
            )

        return None

    def _check_buy_signals(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        whitelist: List[str],
        cb_data: Dict[str, ConvertibleBondData],
        current_date: date,
    ) -> List[TradeSignal]:
        """检查买入信号"""
        signals = []

        # 已持有的代码
        held_codes = set(portfolio.positions.keys())

        # 遍历白名单
        for score in scores:
            if score.cb_code not in whitelist:
                continue
            if score.cb_code in held_codes:
                continue

            cb = cb_data.get(score.cb_code)
            if not cb:
                continue

            # 检查买入条件
            signal = self._check_buy_condition(score, cb, current_date)
            if signal:
                signals.append(signal)

        return signals

    def _check_buy_condition(
        self,
        score: SevenDimScore,
        cb: ConvertibleBondData,
        current_date: date,
    ) -> Optional[TradeSignal]:
        """检查买入条件"""
        # 1. 七维得分分级
        # 注意：生产环境建议阈值70分
        min_score = 70

        if score.total_score < min_score:
            return None

        # 2. 检查转债条件
        # 换手率检查 - 数据缺失时拒绝（无法评估流动性风险）
        if cb.turnover_rate is not None and 0 < cb.turnover_rate < 0.8:
            return None
        elif cb.turnover_rate is None:
            logger.warning(f"[SignalGenerator] {cb.code} 换手率数据缺失，跳过")
            return None

        if cb.conversion_premium > 50:  # 溢价率<=50%（放宽条件）
            return None

        # 3. 确定仓位
        position_limit, level = self._get_position_limit_flexible(score.total_score)
        if position_limit <= 0:
            return None

        # 计算建议数量
        suggested_amount = self.aum * 10000 * position_limit  # 元
        if not cb.close or cb.close <= 0:
            return None
        suggested_qty = int(suggested_amount / cb.close / 100) * 100  # 取整到百张

        if suggested_qty <= 0:
            return None

        return self._create_signal(
            code=cb.code,
            cb_name=cb.name,
            action=TradeAction.BUY,
            signal_type=SignalType.NEW_BUY,
            price=cb.close,
            reason=f"七维得分{score.total_score:.1f}({level}), 排名{score.rank}",
            quantity=suggested_qty,
            confidence=score.total_score / 100,
        )

    def _check_add_position_signals(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        cb_data: Dict[str, ConvertibleBondData],
        current_date: date,
    ) -> List[TradeSignal]:
        """检查加仓信号"""
        signals = []

        for code, pos in portfolio.positions.items():
            # 买入后5个交易日内
            if pos.days_held > 5:
                continue

            score = next((s for s in scores if s.cb_code == code), None)
            if score is None:
                continue

            cb = cb_data.get(code)
            if cb is None:
                continue

            # 加仓条件: 正股上涨>=5% 且 七维得分上升>=5分
            # 注: 需要历史数据支持，这里简化处理
            if score.total_score >= pos.seven_dim_score + 5:
                current_mv = pos.quantity * pos.current_price
                max_mv = self.aum * 10000 * params.max_single_position
                add_mv = max_mv * 0.8 - current_mv  # 加仓至80%

                if add_mv > 0:
                    add_qty = int(add_mv / cb.close / 100) * 100
                    signals.append(self._create_signal(
                        code=code,
                        cb_name=pos.cb_name,
                        action=TradeAction.BUY,
                        signal_type=SignalType.ADD_POSITION,
                        price=cb.close,
                        reason=f"七维得分上升，加仓至80%仓位",
                        quantity=add_qty,
                        confidence=score.total_score / 100,
                    ))

        return signals

    def _get_position_limit(self, score: float) -> Tuple[float, str]:
        """根据得分获取仓位上限"""
        if score >= 85:
            return params.max_single_position, "极品"
        elif score >= 75:
            return params.max_single_position * 0.6, "优秀"
        elif score >= 70:
            return params.max_single_position * 0.4, "良好"
        else:
            return 0.0, "禁止"

    def _get_position_limit_flexible(self, score: float) -> Tuple[float, str]:
        """根据得分获取仓位上限（灵活版本，适应数据不完整的情况）"""
        if score >= 85:
            return params.max_single_position, "极品"
        elif score >= 75:
            return params.max_single_position * 0.6, "优秀"
        elif score >= 70:
            return params.max_single_position * 0.4, "良好"
        elif score >= 50:
            return params.max_single_position * 0.3, "中等"
        elif score >= 35:
            return params.max_single_position * 0.2, "一般"
        elif score >= 20:
            return params.max_single_position * 0.1, "较低"
        else:
            return 0.0, "禁止"

    def _create_signal(
        self,
        code: str,
        cb_name: str,
        action: TradeAction,
        signal_type: SignalType,
        price: float,
        reason: str,
        quantity: int = 0,
        confidence: float = 0.0,
        urgency: int = 0,
    ) -> TradeSignal:
        """创建交易信号"""
        return TradeSignal(
            signal_id=str(uuid.uuid4())[:8],
            cb_code=code,
            cb_name=cb_name,
            action=action,
            signal_type=signal_type,
            price=price,
            quantity=quantity,
            reason=reason,
            confidence=confidence,
            timestamp=datetime.now(),
            urgency=urgency,
        )

    def get_signals_today(self) -> List[TradeSignal]:
        """获取当日信号"""
        return self._signals_today

    def clear_signals(self) -> None:
        """清空信号"""
        self._signals_today = []


class HFTSignalGenerator:
    """高频交易信号生成器"""

    def __init__(self, aum: float = 10000.0):
        """初始化"""
        self.aum = aum
        self._daily_trade_count = 0
        self._hft_position_value = 0.0

    def check_hft_entry(
        self,
        score: SevenDimScore,
        cb: ConvertibleBondData,
        minute_volume_ratio: float,
        minute_change: float,
        in_whitelist: bool,
    ) -> Optional[TradeSignal]:
        """检查高频入场条件

        Args:
            score: 七维得分
            cb: 可转债数据
            minute_volume_ratio: 1分钟量/20日均值
            minute_change: 1分钟涨跌幅(%)
            in_whitelist: 是否在白名单

        Returns:
            入场信号，不满足条件返回None
        """
        # 检查基本条件
        if not in_whitelist:
            return None
        if score.total_score < params.hft_min_score:
            return None
        if minute_volume_ratio < params.hft_volume_ratio:
            return None
        if minute_change < params.hft_price_up_pct:
            return None

        # 检查当日交易次数
        if self._daily_trade_count >= params.hft_max_daily_trades:
            return None

        # 检查高频仓位上限
        hft_max_value = self.aum * 10000 * params.hft_max_position_ratio
        if self._hft_position_value >= hft_max_value:
            return None

        # 计算交易数量
        trade_amount = min(
            self.aum * 10000 * 0.02,  # 单笔不超过AUM的2%
            hft_max_value - self._hft_position_value,
        )
        trade_qty = int(trade_amount / cb.close / 100) * 100

        self._daily_trade_count += 1
        self._hft_position_value += trade_amount

        return TradeSignal(
            signal_id=str(uuid.uuid4())[:8],
            cb_code=cb.code,
            cb_name=cb.name,
            action=TradeAction.BUY,
            signal_type=SignalType.NEW_BUY,
            price=cb.close,
            quantity=trade_qty,
            reason=f"HFT: 七维{score.total_score:.0f}, 量比{minute_volume_ratio:.1f}, 涨幅{minute_change:.2f}%",
            confidence=score.total_score / 100,
            urgency=0,
        )

    def check_hft_exit(
        self,
        position: Position,
        current_price: float,
        entry_price: float,
    ) -> Optional[TradeSignal]:
        """检查高频出场条件

        Args:
            position: 持仓
            current_price: 当前价格
            entry_price: 入场价格

        Returns:
            出场信号
        """
        pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price and entry_price > 0 else 0.0

        # 止盈
        if pnl_pct >= params.hft_profit_target:
            return TradeSignal(
                signal_id=str(uuid.uuid4())[:8],
                cb_code=position.cb_code,
                cb_name=position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.TAKE_PROFIT,
                price=current_price,
                quantity=position.quantity,
                reason=f"HFT止盈: +{pnl_pct:.2f}%",
                urgency=0,
            )

        # 止损
        if pnl_pct <= -params.hft_stop_loss:
            return TradeSignal(
                signal_id=str(uuid.uuid4())[:8],
                cb_code=position.cb_code,
                cb_name=position.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.STOP_LOSS,
                price=current_price,
                quantity=position.quantity,
                reason=f"HFT止损: {pnl_pct:.2f}%",
                urgency=1,
            )

        return None

    def force_close_all(self, positions: List[Position]) -> List[TradeSignal]:
        """14:50强制清仓所有高频持仓

        Args:
            positions: 高频持仓列表

        Returns:
            清仓信号列表
        """
        signals = []
        for pos in positions:
            signals.append(TradeSignal(
                signal_id=str(uuid.uuid4())[:8],
                cb_code=pos.cb_code,
                cb_name=pos.cb_name,
                action=TradeAction.SELL,
                signal_type=SignalType.FORCE_EXIT,
                price=pos.current_price,
                quantity=pos.quantity,
                reason="HFT 14:50强制清仓",
                urgency=1,
            ))
        self._hft_position_value = 0.0
        return signals

    def reset_daily(self) -> None:
        """每日重置"""
        self._daily_trade_count = 0
        self._hft_position_value = 0.0
