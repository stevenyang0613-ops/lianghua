"""自动报告生成"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json


class ReportType(Enum):
    """报告类型"""
    DAILY_TRADING = "daily_trading"        # 日交易报告
    WEEKLY_SUMMARY = "weekly_summary"      # 周报告
    MONTHLY_COMPLIANCE = "monthly_compliance"  # 月度合规报告
    VIOLATION = "violation"                # 违规报告
    RISK_ASSESSMENT = "risk_assessment"    # 风险评估报告
    ANOMALY = "anomaly"                    # 异常报告
    AUDIT = "audit"                        # 审计报告


class ReportFormat(Enum):
    """报告格式"""
    JSON = "json"
    HTML = "html"
    PDF = "pdf"
    EXCEL = "excel"


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str
    data: Dict = field(default_factory=dict)
    subsections: List['ReportSection'] = field(default_factory=list)


@dataclass
class Report:
    """报告"""
    report_id: str
    report_type: ReportType
    title: str
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    sections: List[ReportSection] = field(default_factory=list)
    summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        self.templates: Dict[ReportType, str] = {}
        self._init_templates()
    
    def _init_templates(self):
        """初始化模板"""
        self.templates = {
            ReportType.DAILY_TRADING: """
# 日交易报告

## 交易概览
- 交易日期: {date}
- 总交易笔数: {total_trades}
- 总交易金额: {total_amount}
- 净收益: {net_pnl}

## 交易明细
{trade_details}

## 合规检查
{compliance_summary}

## 风险指标
{risk_metrics}
""",
            ReportType.WEEKLY_SUMMARY: """
# 周报告

## 本周概览
- 报告周期: {period}
- 累计收益率: {return_rate}
- 最大回撤: {max_drawdown}
- 夏普比率: {sharpe_ratio}

## 交易统计
{trading_stats}

## 合规状态
{compliance_status}

## 下周计划
{next_week_plan}
""",
            ReportType.MONTHLY_COMPLIANCE: """
# 月度合规报告

## 合规概览
- 报告月份: {month}
- 合规评分: {compliance_score}

## 违规记录
{violations}

## 整改措施
{actions}

## 改进建议
{recommendations}
""",
        }
    
    def generate_daily_trading_report(
        self,
        date: datetime,
        trades: List[Dict],
        compliance_results: List[Dict],
        risk_metrics: Dict
    ) -> Report:
        """生成日交易报告"""
        report_id = f"daily_{date.strftime('%Y%m%d')}"
        
        # 计算统计数据
        total_trades = len(trades)
        total_amount = sum(t.get('quantity', 0) * t.get('price', 0) for t in trades)
        net_pnl = sum(t.get('pnl', 0) for t in trades)
        
        # 创建章节
        sections = [
            ReportSection(
                title="交易概览",
                content=f"本日共完成{total_trades}笔交易，总金额{total_amount:,.2f}元，净收益{net_pnl:,.2f}元",
                data={
                    'total_trades': total_trades,
                    'total_amount': total_amount,
                    'net_pnl': net_pnl
                }
            ),
            ReportSection(
                title="交易明细",
                content=self._format_trade_details(trades),
                data={'trades': trades[:100]}  # 最多100笔
            ),
            ReportSection(
                title="合规检查",
                content=self._format_compliance_summary(compliance_results),
                data={'violations': compliance_results}
            ),
            ReportSection(
                title="风险指标",
                content=self._format_risk_metrics(risk_metrics),
                data=risk_metrics
            )
        ]
        
        # 生成摘要
        summary = f"{date.strftime('%Y年%m月%d日')}交易报告：{total_trades}笔交易，金额{total_amount:,.2f}元"
        
        # 生成建议
        recommendations = []
        if compliance_results:
            recommendations.append("请关注合规问题并及时处理")
        if risk_metrics.get('var', 0) > 0.05:
            recommendations.append("VaR偏高，建议降低仓位")
        
        return Report(
            report_id=report_id,
            report_type=ReportType.DAILY_TRADING,
            title=f"日交易报告 - {date.strftime('%Y年%m月%d日')}",
            generated_at=datetime.now(),
            period_start=date,
            period_end=date,
            sections=sections,
            summary=summary,
            recommendations=recommendations
        )
    
    def generate_weekly_summary(
        self,
        start_date: datetime,
        end_date: datetime,
        trading_stats: Dict,
        compliance_status: Dict,
        performance: Dict
    ) -> Report:
        """生成周报告"""
        report_id = f"weekly_{start_date.strftime('%Y%m%d')}"
        
        sections = [
            ReportSection(
                title="本周概览",
                content=f"报告周期：{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}",
                data={
                    'period': f"{start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}",
                    'return_rate': performance.get('return_rate', 0),
                    'max_drawdown': performance.get('max_drawdown', 0),
                    'sharpe_ratio': performance.get('sharpe_ratio', 0)
                }
            ),
            ReportSection(
                title="交易统计",
                content=self._format_weekly_trading_stats(trading_stats),
                data=trading_stats
            ),
            ReportSection(
                title="合规状态",
                content=self._format_compliance_status(compliance_status),
                data=compliance_status
            ),
            ReportSection(
                title="下周计划",
                content="根据本周表现调整策略，继续监控风险指标",
                data={}
            )
        ]
        
        summary = f"本周收益率：{performance.get('return_rate', 0):.2%}，最大回撤：{performance.get('max_drawdown', 0):.2%}"
        
        return Report(
            report_id=report_id,
            report_type=ReportType.WEEKLY_SUMMARY,
            title=f"周报告 - {start_date.strftime('%Y年%m月%d日')}至{end_date.strftime('%Y年%m月%d日')}",
            generated_at=datetime.now(),
            period_start=start_date,
            period_end=end_date,
            sections=sections,
            summary=summary,
            recommendations=self._generate_weekly_recommendations(trading_stats, compliance_status, performance)
        )
    
    def generate_monthly_compliance_report(
        self,
        month: datetime,
        violations: List[Dict],
        compliance_score: float,
        actions_taken: List[Dict]
    ) -> Report:
        """生成月度合规报告"""
        report_id = f"compliance_{month.strftime('%Y%m')}"
        
        start_date = month.replace(day=1)
        end_date = (month.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        sections = [
            ReportSection(
                title="合规概览",
                content=f"报告月份：{month.strftime('%Y年%m月')}，合规评分：{compliance_score:.1f}分",
                data={
                    'month': month.strftime('%Y年%m月'),
                    'compliance_score': compliance_score
                }
            ),
            ReportSection(
                title="违规记录",
                content=self._format_violations(violations),
                data={'violations': violations, 'count': len(violations)}
            ),
            ReportSection(
                title="整改措施",
                content=self._format_actions(actions_taken),
                data={'actions': actions_taken}
            ),
            ReportSection(
                title="改进建议",
                content=self._generate_compliance_recommendations(violations),
                data={}
            )
        ]
        
        summary = f"{month.strftime('%Y年%m月')}合规报告：合规评分{compliance_score:.1f}分，违规{len(violations)}起"
        
        return Report(
            report_id=report_id,
            report_type=ReportType.MONTHLY_COMPLIANCE,
            title=f"月度合规报告 - {month.strftime('%Y年%m月')}",
            generated_at=datetime.now(),
            period_start=start_date,
            period_end=end_date,
            sections=sections,
            summary=summary,
            recommendations=self._generate_compliance_recommendations(violations)
        )
    
    def generate_violation_report(
        self,
        violation: Dict,
        investigation: Dict,
        resolution: str
    ) -> Report:
        """生成违规报告"""
        report_id = f"violation_{violation.get('violation_id', int(datetime.now().timestamp()))}"
        
        sections = [
            ReportSection(
                title="违规详情",
                content=f"违规类型：{violation.get('type', '')}\n严重程度：{violation.get('severity', '')}\n描述：{violation.get('description', '')}",
                data=violation
            ),
            ReportSection(
                title="调查结果",
                content=self._format_investigation(investigation),
                data=investigation
            ),
            ReportSection(
                title="处理意见",
                content=resolution,
                data={'resolution': resolution}
            )
        ]
        
        return Report(
            report_id=report_id,
            report_type=ReportType.VIOLATION,
            title=f"违规报告 - {violation.get('type', '')}",
            generated_at=datetime.now(),
            period_start=datetime.now(),
            period_end=datetime.now(),
            sections=sections,
            summary=f"违规类型：{violation.get('type', '')}，处理结果：{resolution}",
            recommendations=[]
        )
    
    def generate_risk_assessment_report(
        self,
        portfolio_data: Dict,
        risk_metrics: Dict,
        stress_test_results: Dict
    ) -> Report:
        """生成风险评估报告"""
        report_id = f"risk_{datetime.now().strftime('%Y%m%d')}"
        
        sections = [
            ReportSection(
                title="组合概览",
                content=f"组合规模：{portfolio_data.get('value', 0):,.2f}元\n持仓数量：{portfolio_data.get('position_count', 0)}",
                data=portfolio_data
            ),
            ReportSection(
                title="风险指标",
                content=self._format_risk_metrics(risk_metrics),
                data=risk_metrics
            ),
            ReportSection(
                title="压力测试",
                content=self._format_stress_test(stress_test_results),
                data=stress_test_results
            ),
            ReportSection(
                title="风险建议",
                content=self._generate_risk_recommendations(risk_metrics),
                data={}
            )
        ]
        
        summary = f"组合VaR(95%)：{risk_metrics.get('var_95', 0):.2%}，最大回撤：{risk_metrics.get('max_drawdown', 0):.2%}"
        
        return Report(
            report_id=report_id,
            report_type=ReportType.RISK_ASSESSMENT,
            title=f"风险评估报告 - {datetime.now().strftime('%Y年%m月%d日')}",
            generated_at=datetime.now(),
            period_start=datetime.now(),
            period_end=datetime.now(),
            sections=sections,
            summary=summary,
            recommendations=self._generate_risk_recommendations(risk_metrics)
        )
    
    def _format_trade_details(self, trades: List[Dict]) -> str:
        """格式化交易明细"""
        if not trades:
            return "无交易记录"
        
        lines = []
        for trade in trades[:20]:  # 最多显示20笔
            lines.append(f"- {trade.get('symbol', '')}: {trade.get('side', '')} {trade.get('quantity', 0)}@{trade.get('price', 0)}")
        
        if len(trades) > 20:
            lines.append(f"... 共{len(trades)}笔交易")
        
        return "\n".join(lines)
    
    def _format_compliance_summary(self, results: List[Dict]) -> str:
        """格式化合规摘要"""
        if not results:
            return "无违规记录"
        
        return f"发现{len(results)}项合规问题，请及时处理"
    
    def _format_risk_metrics(self, metrics: Dict) -> str:
        """格式化风险指标"""
        lines = [
            f"- VaR(95%): {metrics.get('var_95', 0):.2%}",
            f"- 最大回撤: {metrics.get('max_drawdown', 0):.2%}",
            f"- 夏普比率: {metrics.get('sharpe_ratio', 0):.2f}",
            f"- Beta: {metrics.get('beta', 0):.2f}",
        ]
        return "\n".join(lines)
    
    def _format_weekly_trading_stats(self, stats: Dict) -> str:
        """格式化周交易统计"""
        return f"总交易笔数：{stats.get('total_trades', 0)}\n总交易金额：{stats.get('total_amount', 0):,.2f}元"
    
    def _format_compliance_status(self, status: Dict) -> str:
        """格式化合规状态"""
        return f"合规评分：{status.get('score', 0):.1f}\n违规次数：{status.get('violations', 0)}"
    
    def _format_violations(self, violations: List[Dict]) -> str:
        """格式化违规记录"""
        if not violations:
            return "无违规记录"
        
        lines = []
        for v in violations:
            lines.append(f"- [{v.get('severity', '')}] {v.get('type', '')}: {v.get('description', '')}")
        
        return "\n".join(lines)
    
    def _format_actions(self, actions: List[Dict]) -> str:
        """格式化整改措施"""
        if not actions:
            return "无需整改"
        
        lines = []
        for action in actions:
            lines.append(f"- {action.get('description', '')} ({action.get('status', '')})")
        
        return "\n".join(lines)
    
    def _format_investigation(self, investigation: Dict) -> str:
        """格式化调查结果"""
        return investigation.get('summary', '无调查结果')
    
    def _format_stress_test(self, results: Dict) -> str:
        """格式化压力测试结果"""
        lines = [
            f"- 1σ情景损失: {results.get('stress_1sigma', 0):.2%}",
            f"- 2σ情景损失: {results.get('stress_2sigma', 0):.2%}",
        ]
        return "\n".join(lines)
    
    def _generate_weekly_recommendations(
        self,
        trading_stats: Dict,
        compliance_status: Dict,
        performance: Dict
    ) -> List[str]:
        """生成周建议"""
        recommendations = []
        
        if performance.get('return_rate', 0) < 0:
            recommendations.append("本周收益为负，建议检视策略有效性")
        
        if compliance_status.get('violations', 0) > 0:
            recommendations.append("存在合规问题，请加强合规管理")
        
        return recommendations
    
    def _generate_compliance_recommendations(self, violations: List[Dict]) -> List[str]:
        """生成合规建议"""
        recommendations = []
        
        if not violations:
            recommendations.append("继续保持良好的合规状态")
            return recommendations
        
        # 根据违规类型生成建议
        violation_types = set(v.get('type', '') for v in violations)
        
        if 'position_limit' in violation_types:
            recommendations.append("优化持仓管理，避免超过限额")
        
        if 'trading_limit' in violation_types:
            recommendations.append("加强交易频率监控")
        
        return recommendations
    
    def _generate_risk_recommendations(self, metrics: Dict) -> List[str]:
        """生成风险建议"""
        recommendations = []
        
        if metrics.get('var_95', 0) > 0.05:
            recommendations.append("VaR偏高，建议降低整体仓位")
        
        if metrics.get('max_drawdown', 0) > 0.1:
            recommendations.append("最大回撤过大，建议优化止损策略")
        
        if metrics.get('sharpe_ratio', 0) < 1:
            recommendations.append("夏普比率偏低，建议优化收益风险比")
        
        return recommendations
    
    def export_report(self, report: Report, format: ReportFormat = ReportFormat.JSON) -> str:
        """导出报告"""
        if format == ReportFormat.JSON:
            return self._export_json(report)
        elif format == ReportFormat.HTML:
            return self._export_html(report)
        
        return self._export_json(report)
    
    def _export_json(self, report: Report) -> str:
        """导出JSON"""
        data = {
            'report_id': report.report_id,
            'report_type': report.report_type.value,
            'title': report.title,
            'generated_at': report.generated_at.isoformat(),
            'period_start': report.period_start.isoformat(),
            'period_end': report.period_end.isoformat(),
            'summary': report.summary,
            'recommendations': report.recommendations,
            'sections': [
                {
                    'title': s.title,
                    'content': s.content,
                    'data': s.data
                }
                for s in report.sections
            ]
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def _export_html(self, report: Report) -> str:
        """导出HTML"""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report.title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
        .summary {{ background: #f5f5f5; padding: 10px; margin: 10px 0; }}
        .recommendations {{ background: #fff3cd; padding: 10px; margin: 10px 0; }}
        .section {{ margin: 20px 0; }}
        .metadata {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{report.title}</h1>
    <div class="metadata">
        生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}<br>
        报告周期: {report.period_start.strftime('%Y-%m-%d')} 至 {report.period_end.strftime('%Y-%m-%d')}
    </div>
    
    <div class="summary">
        <h2>摘要</h2>
        <p>{report.summary}</p>
    </div>
"""
        
        for section in report.sections:
            html += f"""
    <div class="section">
        <h2>{section.title}</h2>
        <pre>{section.content}</pre>
    </div>
"""
        
        if report.recommendations:
            html += """
    <div class="recommendations">
        <h2>建议</h2>
        <ul>
"""
            for rec in report.recommendations:
                html += f"        <li>{rec}</li>\n"
            html += """        </ul>
    </div>
"""
        
        html += """
</body>
</html>
"""
        return html
