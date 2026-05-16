"""松岗量化可转债策略 V3.0 白名单轮换引擎

核心规则:
- 每日收盘后，对所有通过一票否决制的转债计算七维综合得分
- 严格按得分从高到低排序，提取前60名作为次日唯一可持仓白名单
- 任何时候，组合持仓只能包含白名单内的转债
- 轮换缓冲带: 排名55-65名的标的享有3个交易日观察期
- AUM分级轮换频率
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Dict, Optional, Set, Tuple
import logging

from app.sg_strategy.core.types import SevenDimScore, Position, Portfolio
from app.sg_strategy.config.settings import params, AUMTier
from app.sg_strategy.config.weights import MarketRegime

logger = logging.getLogger(__name__)


@dataclass
class WhitelistState:
    """白名单状态"""
    date: date
    whitelist: List[str]              # 当前白名单(前N名)
    buffer_zone: List[str]            # 缓冲带(55-65名)
    buffer_days: Dict[str, int]       # 转债在缓冲带的天数 {code: days}
    regime: MarketRegime
    whitelist_size: int

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "whitelist": self.whitelist,
            "buffer_zone": self.buffer_zone,
            "buffer_days": self.buffer_days,
            "regime": self.regime.value,
            "whitelist_size": self.whitelist_size,
        }


@dataclass
class RebalanceSignal:
    """调仓信号"""
    date: date
    to_sell: List[str]                # 需要卖出的转债
    to_buy: List[str]                 # 需要买入的转债
    sell_reasons: Dict[str, str]      # 卖出原因
    buy_reasons: Dict[str, str]       # 买入原因
    urgency: str = "normal"           # normal/urgent/immediate

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "to_sell": self.to_sell,
            "to_buy": self.to_buy,
            "sell_reasons": self.sell_reasons,
            "buy_reasons": self.buy_reasons,
            "urgency": self.urgency,
        }


class WhitelistManager:
    """白名单管理器"""

    def __init__(
        self,
        aum: float = 10000.0,
        regime: MarketRegime = MarketRegime.RANGE,
    ):
        """初始化

        Args:
            aum: 资产规模(万元)
            regime: 市场环境
        """
        self.aum = aum
        self.regime = regime
        self.whitelist_size = params.get_whitelist_size(regime.value)

        # 缓冲带配置
        self.buffer_start = params.buffer_zone_start
        self.buffer_end = params.buffer_zone_end
        self.buffer_days_max = self._get_buffer_days_max()

        # 状态
        self._current_whitelist: List[str] = []
        self._buffer_zone: List[str] = []
        self._buffer_days: Dict[str, int] = {}
        self._last_update: Optional[date] = None
        self._rebalance_count: int = 0

    def _get_buffer_days_max(self) -> int:
        """获取缓冲带最大天数(根据AUM)"""
        if self.aum >= 50000:  # > 5亿
            return params.buffer_days_max_large_aum
        return params.buffer_days_max

    def _get_aum_tier(self) -> AUMTier:
        """获取AUM分档"""
        if self.aum < 10000:
            return AUMTier.SMALL
        elif self.aum < 50000:
            return AUMTier.MEDIUM
        elif self.aum < 100000:
            return AUMTier.LARGE
        else:
            return AUMTier.VERY_LARGE

    def get_rebalance_frequency(self) -> str:
        """获取调仓频率(根据AUM)"""
        tier = self._get_aum_tier()
        if tier == AUMTier.SMALL:
            return "daily"
        elif tier == AUMTier.MEDIUM:
            return "daily"  # 隔日在上层逻辑控制
        else:
            return "weekly"  # 每周两次

    def update_whitelist(
        self,
        scores: List[SevenDimScore],
        current_date: date,
    ) -> WhitelistState:
        """更新白名单

        Args:
            scores: 七维得分列表(已排序)
            current_date: 当前日期

        Returns:
            WhitelistState: 新的白名单状态
        """
        # 获取白名单大小
        self.whitelist_size = params.get_whitelist_size(self.regime.value)

        # 按排名划分
        new_whitelist = [s.cb_code for s in scores[:self.whitelist_size]]

        # 缓冲带(排名55-65)
        buffer_start = min(self.buffer_start, self.whitelist_size)
        buffer_end = min(self.buffer_end, len(scores))
        new_buffer_zone = [s.cb_code for s in scores[buffer_start:buffer_end]]

        # 更新缓冲带天数
        new_buffer_days = {}
        for code in new_buffer_zone:
            if code in self._buffer_days:
                new_buffer_days[code] = self._buffer_days[code] + 1
            else:
                new_buffer_days[code] = 1

        # 更新状态
        self._current_whitelist = new_whitelist
        self._buffer_zone = new_buffer_zone
        self._buffer_days = new_buffer_days
        self._last_update = current_date

        return WhitelistState(
            date=current_date,
            whitelist=new_whitelist,
            buffer_zone=new_buffer_zone,
            buffer_days=new_buffer_days,
            regime=self.regime,
            whitelist_size=self.whitelist_size,
        )

    def check_position(
        self,
        position: Position,
        score: SevenDimScore,
    ) -> Tuple[bool, str]:
        """检查持仓是否需要调整

        Args:
            position: 持仓信息
            score: 当前七维得分

        Returns:
            (是否保留, 原因)
        """
        code = position.cb_code

        # 1. 在白名单内 - 保留
        if code in self._current_whitelist:
            return True, "在白名单内"

        # 2. 在缓冲带内 - 检查观察天数
        if code in self._buffer_zone:
            days = self._buffer_days.get(code, 0)
            if days >= self.buffer_days_max:
                return False, f"缓冲带观察期结束({days}天)"
            return True, f"缓冲带观察中({days}/{self.buffer_days_max}天)"

        # 3. 不在白名单且不在缓冲带 - 卖出
        return False, "跌出白名单且不在缓冲带"

    def generate_rebalance_signals(
        self,
        portfolio: Portfolio,
        scores: List[SevenDimScore],
        current_date: date,
    ) -> RebalanceSignal:
        """生成调仓信号

        Args:
            portfolio: 当前组合
            scores: 七维得分列表
            current_date: 当前日期

        Returns:
            RebalanceSignal: 调仓信号
        """
        # 先更新白名单
        whitelist_state = self.update_whitelist(scores, current_date)

        to_sell = []
        to_buy = []
        sell_reasons = {}
        buy_reasons = {}

        # 检查现有持仓
        for code, pos in portfolio.positions.items():
            score = next((s for s in scores if s.cb_code == code), None)
            if score is None:
                to_sell.append(code)
                sell_reasons[code] = "无法获取得分数据"
                continue

            should_keep, reason = self.check_position(pos, score)
            if not should_keep:
                to_sell.append(code)
                sell_reasons[code] = reason

        # 计算可用资金(卖出后)
        sell_value = sum(
            portfolio.positions[code].market_value
            for code in to_sell
            if code in portfolio.positions
        )
        available_cash = portfolio.cash + sell_value

        # 选择买入标的
        for score in scores[:self.whitelist_size]:
            code = score.cb_code

            # 已持仓则跳过
            if code in portfolio.positions and code not in to_sell:
                continue

            # 检查是否达到持仓上限
            current_positions = len(portfolio.positions) - len(to_sell) + len(to_buy)
            if current_positions >= params.max_total_positions:
                break

            to_buy.append(code)
            buy_reasons[code] = f"七维得分{score.total_score:.1f}分，排名{score.rank}"

        # 确定紧急程度
        urgency = "normal"
        if len(to_sell) > 10:
            urgency = "urgent"
        if any("缓冲带观察期结束" in r for r in sell_reasons.values()):
            urgency = "urgent"

        self._rebalance_count += 1

        logger.info(
            f"[Whitelist] 调仓信号: 卖出{len(to_sell)}只, 买入{len(to_buy)}只, "
            f"紧急程度: {urgency}"
        )

        return RebalanceSignal(
            date=current_date,
            to_sell=to_sell,
            to_buy=to_buy,
            sell_reasons=sell_reasons,
            buy_reasons=buy_reasons,
            urgency=urgency,
        )

    def is_rebalance_day(self, current_date: date) -> bool:
        """判断今天是否为调仓日(根据AUM分级)

        Args:
            current_date: 当前日期

        Returns:
            是否为调仓日
        """
        tier = self._get_aum_tier()

        if tier == AUMTier.SMALL:
            return True  # 每日调仓

        elif tier == AUMTier.MEDIUM:
            # 隔日调仓(检查是否为间隔日)
            if self._last_update is None:
                return True
            return (current_date - self._last_update).days >= 2

        else:  # LARGE, VERY_LARGE
            # 每周两次(周一和周四)
            weekday = current_date.weekday()
            return weekday == 0 or weekday == 3  # 周一或周四

    def get_position_limit(
        self,
        score: SevenDimScore,
    ) -> Tuple[float, str]:
        """获取单只转债仓位上限

        Args:
            score: 七维得分

        Returns:
            (仓位上限比例, 分级描述)
        """
        total = score.total_score

        if total >= 85:
            return params.max_single_position, "极品"
        elif total >= 75:
            return params.max_single_position * 0.6, "优秀"
        elif total >= 70:
            return params.max_single_position * 0.4, "良好"
        else:
            return 0.0, "禁止买入"

    def check_sector_limit(
        self,
        portfolio: Portfolio,
        sector: str,
        additional_position: float = 0,
    ) -> bool:
        """检查行业仓位限制

        Args:
            portfolio: 当前组合
            sector: 行业
            additional_position: 额外仓位

        Returns:
            是否可以增加仓位
        """
        current_sector_position = portfolio.sector_positions.get(sector, 0)
        new_sector_position = current_sector_position + additional_position

        return new_sector_position <= params.max_sector_position

    def get_whitelist_state(self) -> WhitelistState:
        """获取当前白名单状态"""
        return WhitelistState(
            date=self._last_update or date.today(),
            whitelist=self._current_whitelist,
            buffer_zone=self._buffer_zone,
            buffer_days=self._buffer_days.copy(),
            regime=self.regime,
            whitelist_size=self.whitelist_size,
        )

    def update_aum(self, aum: float) -> None:
        """更新AUM"""
        self.aum = aum
        self.buffer_days_max = self._get_buffer_days_max()
        logger.info(f"[Whitelist] AUM更新: {aum}万, 缓冲天数: {self.buffer_days_max}")

    def update_regime(self, regime: MarketRegime) -> None:
        """更新市场环境"""
        self.regime = regime
        self.whitelist_size = params.get_whitelist_size(regime.value)
        logger.info(
            f"[Whitelist] 市场环境更新: {regime.value}, "
            f"白名单大小: {self.whitelist_size}"
        )


class EnhancedWhitelistManager(WhitelistManager):
    """增强版白名单管理器 - 包含更多功能"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: List[WhitelistState] = []

    def update_whitelist(
        self,
        scores: List[SevenDimScore],
        current_date: date,
    ) -> WhitelistState:
        """更新白名单(含历史记录)"""
        state = super().update_whitelist(scores, current_date)

        # 保存历史
        self._history.append(state)

        # 只保留最近30天
        if len(self._history) > 30:
            self._history = self._history[-30:]

        return state

    def get_turnover_stats(self, days: int = 5) -> dict:
        """获取换手统计

        Args:
            days: 统计天数

        Returns:
            统计结果
        """
        if len(self._history) < 2:
            return {"avg_turnover": 0, "max_turnover": 0}

        recent = self._history[-days:] if len(self._history) >= days else self._history

        turnovers = []
        for i in range(1, len(recent)):
            prev_set = set(recent[i - 1].whitelist)
            curr_set = set(recent[i].whitelist)
            turnover = len(prev_set.symmetric_difference(curr_set)) / 2
            turnovers.append(turnover)

        return {
            "avg_turnover": sum(turnovers) / len(turnovers) if turnovers else 0,
            "max_turnover": max(turnovers) if turnovers else 0,
            "total_changes": sum(turnovers),
        }

    def get_stable_bonds(self, min_days: int = 5) -> List[str]:
        """获取稳定持仓(连续多日在白名单内)

        Args:
            min_days: 最小连续天数

        Returns:
            稳定持仓代码列表
        """
        if len(self._history) < min_days:
            return []

        # 计算每个转债在白名单内的连续天数
        bond_days: Dict[str, int] = {}

        for state in reversed(self._history):
            for code in state.whitelist:
                bond_days[code] = bond_days.get(code, 0) + 1

        # 返回连续天数足够的转债
        return [code for code, days in bond_days.items() if days >= min_days]
