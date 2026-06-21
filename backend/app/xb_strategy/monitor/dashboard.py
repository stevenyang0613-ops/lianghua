"""监控仪表板

支持可视化图表生成:
- 净值曲线
- 回撤分析
- 持仓分布
- 收益归因
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Dict, Optional, Any
import json
import os

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


@dataclass
class DashboardWidget:
    """仪表板组件"""
    title: str
    value: any
    unit: str = ""
    status: str = "normal"  # normal/warning/danger
    trend: str = "flat"  # up/down/flat

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "trend": self.trend,
        }


class ChartGenerator:
    """图表生成器"""

    def __init__(self, output_dir: str = "/tmp/xb_strategy_charts"):
        """初始化

        Args:
            output_dir: 图表输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def plot_equity_curve(
        self,
        dates: List[date],
        equity: List[float],
        benchmark: Optional[List[float]] = None,
        title: str = "净值曲线",
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """绘制净值曲线

        Args:
            dates: 日期列表
            equity: 净值列表
            benchmark: 基准净值列表
            title: 图表标题
            save_path: 保存路径

        Returns:
            图表文件路径
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(dates, equity, label='策略净值', linewidth=2, color='#2196F3')
        if benchmark:
            ax.plot(dates, benchmark, label='基准', linewidth=1.5, color='#9E9E9E', linestyle='--')

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('净值(万)', fontsize=12)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)

        # 格式化x轴日期
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.xticks(rotation=45)

        plt.tight_layout()

        path = save_path or f"{self.output_dir}/equity_curve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()

        return path

    def plot_drawdown(
        self,
        dates: List[date],
        drawdown: List[float],
        title: str = "回撤分析",
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """绘制回撤曲线

        Args:
            dates: 日期列表
            drawdown: 回撤列表(百分比)
            title: 图表标题
            save_path: 保存路径

        Returns:
            图表文件路径
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        fig, ax = plt.subplots(figsize=(12, 4))

        ax.fill_between(dates, drawdown, 0, alpha=0.3, color='#F44336')
        ax.plot(dates, drawdown, linewidth=1.5, color='#F44336')

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('回撤(%)', fontsize=12)
        ax.grid(True, alpha=0.3)

        # 标注最大回撤
        max_dd = min(drawdown)
        max_dd_idx = drawdown.index(max_dd)
        ax.annotate(f'最大回撤: {max_dd:.2f}%',
                    xy=(dates[max_dd_idx], max_dd),
                    xytext=(dates[max_dd_idx], max_dd + 2),
                    fontsize=10, color='red')

        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45)

        plt.tight_layout()

        path = save_path or f"{self.output_dir}/drawdown_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()

        return path

    def plot_position_distribution(
        self,
        positions: Dict[str, float],
        title: str = "持仓分布",
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """绘制持仓分布饼图

        Args:
            positions: 持仓字典 {名称: 市值}
            title: 图表标题
            save_path: 保存路径

        Returns:
            图表文件路径
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        fig, ax = plt.subplots(figsize=(10, 8))

        labels = list(positions.keys())[:10]  # 只显示前10个
        sizes = list(positions.values())[:10]

        # 如果有更多持仓，合并为"其他"
        if len(positions) > 10:
            other_value = sum(list(positions.values())[10:])
            labels.append('其他')
            sizes.append(other_value)

        colors = plt.cm.Set3(range(len(labels)))

        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, autopct='%1.1f%%',
            colors=colors, startangle=90
        )

        ax.set_title(title, fontsize=14, fontweight='bold')

        plt.tight_layout()

        path = save_path or f"{self.output_dir}/position_dist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()

        return path

    def plot_monthly_returns(
        self,
        monthly_returns: Dict[str, float],
        title: str = "月度收益",
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """绘制月度收益柱状图

        Args:
            monthly_returns: 月度收益字典 {月份: 收益率}
            title: 图表标题
            save_path: 保存路径

        Returns:
            图表文件路径
        """
        if not MATPLOTLIB_AVAILABLE:
            return None

        fig, ax = plt.subplots(figsize=(14, 6))

        months = list(monthly_returns.keys())
        returns = list(monthly_returns.values())
        colors = ['#4CAF50' if r >= 0 else '#F44336' for r in returns]

        bars = ax.bar(months, returns, color=colors, alpha=0.8)

        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel('月份', fontsize=12)
        ax.set_ylabel('收益率(%)', fontsize=12)
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.grid(True, alpha=0.3, axis='y')

        # 添加数值标签
        for bar, ret in zip(bars, returns):
            height = bar.get_height()
            ax.annotate(f'{ret:.1f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3 if height >= 0 else -12),
                        textcoords="offset points",
                        ha='center', va='bottom' if height >= 0 else 'top',
                        fontsize=8)

        plt.xticks(rotation=45)
        plt.tight_layout()

        path = save_path or f"{self.output_dir}/monthly_returns_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        plt.savefig(path, dpi=150, bbox_inches='tight')
        plt.close()

        return path

    def plot_interactive_equity(
        self,
        dates: List[date],
        equity: List[float],
        benchmark: Optional[List[float]] = None,
        title: str = "净值曲线(交互)",
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """绘制交互式净值曲线(Plotly)

        Args:
            dates: 日期列表
            equity: 净值列表
            benchmark: 基准净值列表
            title: 图表标题
            save_path: 保存路径

        Returns:
            图表文件路径
        """
        if not PLOTLY_AVAILABLE:
            return None

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=dates, y=equity,
            name='策略净值',
            line=dict(color='#2196F3', width=2),
            hovertemplate='%{x}<br>净值: %{y:.2f}万<extra></extra>'
        ))

        if benchmark:
            fig.add_trace(go.Scatter(
                x=dates, y=benchmark,
                name='基准',
                line=dict(color='#9E9E9E', width=1.5, dash='dash'),
                hovertemplate='%{x}<br>基准: %{y:.2f}万<extra></extra>'
            ))

        fig.update_layout(
            title=title,
            xaxis_title='日期',
            yaxis_title='净值(万)',
            hovermode='x unified',
            template='plotly_white',
            width=1200,
            height=600
        )

        path = save_path or f"{self.output_dir}/equity_interactive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        fig.write_html(path)

        return path


class StrategyDashboard:
    """策略监控仪表板"""

    def __init__(self, output_dir: str = "/tmp/xb_strategy_charts"):
        """初始化"""
        self.widgets: Dict[str, DashboardWidget] = {}
        self.chart_generator = ChartGenerator(output_dir)
        self._charts: List[str] = []

    def update_from_strategy(self, strategy) -> None:
        """从策略更新仪表板

        Args:
            strategy: XBConvertibleStrategy实例
        """
        perf = strategy.get_performance_summary()

        # AUM
        self.widgets["aum"] = DashboardWidget(
            title="总资产",
            value=round(perf["aum"], 2),
            unit="万元",
            status="normal",
        )

        # 持仓数
        self.widgets["positions"] = DashboardWidget(
            title="持仓数量",
            value=perf["position_count"],
            unit="只",
            status="normal",
        )

        # 白名单
        self.widgets["whitelist"] = DashboardWidget(
            title="白名单",
            value=perf["whitelist_size"],
            unit="只",
            status="normal",
        )

        # 择时得分
        if strategy.timing_signal:
            score = strategy.timing_signal.total_score
            status = "normal" if score >= 50 else "warning" if score >= 30 else "danger"
            self.widgets["timing"] = DashboardWidget(
                title="择时得分",
                value=round(score, 1),
                unit="分",
                status=status,
            )

        # 市场环境
        self.widgets["regime"] = DashboardWidget(
            title="市场环境",
            value=strategy.regime.value,
            unit="",
            status="normal",
        )

        # 对冲状态
        hedge = strategy.hedge_engine.get_status()
        self.widgets["hedge"] = DashboardWidget(
            title="对冲状态",
            value="开启" if hedge.active else "关闭",
            unit="",
            status="warning" if hedge.active else "normal",
        )

    def add_alert(self, message: str, level: str = "warning") -> None:
        """添加告警

        Args:
            message: 告警信息
            level: 告警级别
        """
        key = f"alert_{datetime.now().strftime('%H%M%S')}"
        self.widgets[key] = DashboardWidget(
            title="告警",
            value=message,
            unit="",
            status=level,
        )

    def generate_equity_chart(
        self,
        reports: List[Any],
        benchmark: Optional[List[float]] = None,
    ) -> Optional[str]:
        """生成净值曲线图

        Args:
            reports: 每日报告列表
            benchmark: 基准净值列表

        Returns:
            图表文件路径
        """
        dates = [r.date for r in reports]
        equity = [r.portfolio.aum for r in reports]

        return self.chart_generator.plot_equity_curve(dates, equity, benchmark)

    def generate_position_chart(self, positions: Dict[str, float]) -> Optional[str]:
        """生成持仓分布图

        Args:
            positions: 持仓字典 {名称: 市值}

        Returns:
            图表文件路径
        """
        return self.chart_generator.plot_position_distribution(positions)

    def to_json(self) -> str:
        """导出为JSON"""
        return json.dumps({
            "timestamp": datetime.now().isoformat(),
            "widgets": {k: v.to_dict() for k, v in self.widgets.items()},
            "charts": self._charts,
        }, ensure_ascii=False)

    def render_text(self) -> str:
        """渲染为文本"""
        lines = []
        lines.append("=" * 50)
        lines.append("西部量化可转债策略 V3.0 监控仪表板")
        lines.append(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 50)

        for key, widget in self.widgets.items():
            if key.startswith("alert_"):
                continue
            status_icon = {"normal": "✓", "warning": "⚠", "danger": "✗"}.get(widget.status, "•")
            lines.append(f"\n{status_icon} {widget.title}: {widget.value} {widget.unit}")

        if self._charts:
            lines.append("\n" + "-" * 50)
            lines.append("已生成图表:")
            for chart in self._charts:
                lines.append(f"  • {chart}")

        return "\n".join(lines)
