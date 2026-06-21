"""
4框架自动触发器 - 集成到 lianghua 业务流

自动调用场景:
1. 新闻触发: 检测到行业新闻时,自动调用 Serenity Alpha
2. 候选标的入池: 新标的进入观察池时,自动调用 TAM-PEG + DMA + Bayesian
3. 每日定时: 每日收盘后自动批量分析持仓
4. 风险预警: 走势异常时自动调用 DMA 检查

集成方式:
- 监听新闻事件 → 自动 Serenity
- 监听股票入池事件 → 自动多框架
- 定时任务 → 每日自动扫描
"""

import logging
import asyncio
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass

from app.framework.api import (
    analyze_news, analyze_valuation, analyze_trend, analyze_pricing,
    full_research, health_check
)

logger = logging.getLogger(__name__)


@dataclass
class AutoTriggerConfig:
    """自动触发配置"""
    enable_news_trigger: bool = True
    enable_pool_trigger: bool = True
    enable_daily_scan: bool = True
    enable_risk_alert: bool = True

    # 触发阈值
    news_keywords: List[str] = None
    dma_alert_threshold: float = 40.0  # DMA健康度低于此值触发预警
    bayesian_overprice_threshold: float = 50.0  # Bayesian定价偏差超过此值触发

    def __post_init__(self):
        if self.news_keywords is None:
            self.news_keywords = [
                "AI", "数据中心", "液冷", "半导体", "新能源", "机器人",
                "创新药", "储能", "光伏", "订单", "突破", "放量", "增长"
            ]


class FrameworkAutoTrigger:
    """4框架自动触发器"""

    def __init__(self, config: Optional[AutoTriggerConfig] = None):
        self.config = config or AutoTriggerConfig()
        self.trigger_log: List[Dict[str, Any]] = []
        self.callbacks: Dict[str, List[Callable]] = {
            "on_news_analysis": [],
            "on_pool_analysis": [],
            "on_daily_scan": [],
            "on_risk_alert": [],
        }

    # ============================================================
    # 触发器1: 新闻触发
    # ============================================================

    def on_news(self, news_text: str, candidates: List[Dict[str, Any]]) -> Optional[List]:
        """
        新闻事件触发: 自动调用 Serenity Alpha

        用法:
            trigger = FrameworkAutoTrigger()
            # 当检测到新闻时
            trigger.on_news("AI液冷需求爆发", candidates)
        """
        if not self.config.enable_news_trigger:
            return None

        # 关键词过滤
        if not any(kw in news_text for kw in self.config.news_keywords):
            logger.debug(f"News doesn't match keywords, skip Serenity: {news_text[:50]}")
            return None

        try:
            logger.info(f"🔔 新闻触发 Serenity Alpha: {news_text[:50]}...")
            hypotheses = analyze_news(news_text, candidates)

            # 记录
            self.trigger_log.append({
                "type": "news",
                "timestamp": datetime.now().isoformat(),
                "input_summary": news_text[:100],
                "output_count": len(hypotheses),
                "top_hypothesis": {
                    "code": hypotheses[0].code,
                    "name": hypotheses[0].name,
                    "strength": hypotheses[0].hypothesis_strength
                } if hypotheses else None
            })

            # 触发回调
            for cb in self.callbacks["on_news_analysis"]:
                try:
                    cb(news_text, hypotheses)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

            return hypotheses
        except Exception as e:
            logger.error(f"Serenity auto-trigger failed: {e}")
            return None

    # ============================================================
    # 触发器2: 入池触发
    # ============================================================

    def on_stock_added_to_pool(self, stock: Dict[str, Any]) -> Optional[Any]:
        """
        标的入池触发: 自动调用3框架(不含Serenity)

        用法:
            # 当新标的进入观察池时
            trigger.on_stock_added_to_pool({
                "code": "002335", "name": "英维克",
                "industry": "AI数据中心液冷", ...
            })
        """
        if not self.config.enable_pool_trigger:
            return None

        try:
            logger.info(f"🔔 入池触发多框架分析: {stock.get('code')}")

            results = {}

            # TAM-PEG
            try:
                results["tam_peg"] = analyze_valuation(stock)
            except Exception as e:
                logger.warning(f"TAM-PEG failed for {stock.get('code')}: {e}")

            # DMA
            try:
                results["dma"] = analyze_trend(stock)
            except Exception as e:
                logger.warning(f"DMA failed for {stock.get('code')}: {e}")

            # Bayesian
            try:
                results["bayesian"] = analyze_pricing(stock)
            except Exception as e:
                logger.warning(f"Bayesian failed for {stock.get('code')}: {e}")

            # 风险检查
            risk_alerts = self._check_risk_alerts(results, stock)

            # 记录
            self.trigger_log.append({
                "type": "pool",
                "timestamp": datetime.now().isoformat(),
                "code": stock.get("code"),
                "results_available": list(results.keys()),
                "risk_alerts": risk_alerts
            })

            # 触发回调
            for cb in self.callbacks["on_pool_analysis"]:
                try:
                    cb(stock, results)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

            return {"stock": stock, "results": results, "risk_alerts": risk_alerts}

        except Exception as e:
            logger.error(f"Pool trigger failed: {e}")
            return None

    # ============================================================
    # 触发器3: 每日扫描
    # ============================================================

    def daily_scan(self, holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        每日扫描: 对持仓进行批量多框架分析

        用法:
            # 每日收盘后定时执行
            report = trigger.daily_scan(current_holdings)
        """
        if not self.config.enable_daily_scan:
            return {}

        try:
            logger.info(f"🔔 每日扫描: {len(holdings)} 只持仓")

            summary = {
                "total": len(holdings),
                "strong_buy": [],
                "buy": [],
                "hold": [],
                "trim": [],
                "sell": [],
                "risk_alerts": []
            }

            for stock in holdings:
                result = self.on_stock_added_to_pool(stock)
                if result and "results" in result:
                    results = result["results"]

                    # 综合判定
                    if results.get("bayesian") and results.get("tam_peg"):
                        verdict = self._aggregate_verdict(results)
                        stock_id = f"{stock.get('name')}({stock.get('code')})"
                        if verdict in summary:
                            summary[verdict].append(stock_id)

                    # 风险预警
                    if result.get("risk_alerts"):
                        summary["risk_alerts"].extend(result["risk_alerts"])

            # 触发回调
            for cb in self.callbacks["on_daily_scan"]:
                try:
                    cb(summary)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

            logger.info(f"扫描完成: 强买{len(summary['strong_buy'])} 买{len(summary['buy'])} "
                       f"持有{len(summary['hold'])} 减仓{len(summary['trim'])} 卖{len(summary['sell'])}")
            return summary

        except Exception as e:
            logger.error(f"Daily scan failed: {e}")
            return {}

    # ============================================================
    # 触发器4: 风险预警
    # ============================================================

    def _check_risk_alerts(self, results: Dict[str, Any], stock: Dict[str, Any]) -> List[Dict[str, Any]]:
        """检查风险预警"""
        alerts = []
        code = stock.get('code', '')
        name = stock.get('name', '')

        # DMA健康度过低
        if "dma" in results and hasattr(results["dma"], "health_score"):
            if results["dma"].health_score < self.config.dma_alert_threshold:
                alerts.append({
                    "type": "dma_unhealthy",
                    "code": code, "name": name,
                    "score": results["dma"].health_score,
                    "message": f"DMA健康度过低({results['dma'].health_score:.0f}/100), 走势异常"
                })

        # Bayesian过度定价
        if "bayesian" in results and hasattr(results["bayesian"], "mispricing_score"):
            if results["bayesian"].mispricing_score > self.config.bayesian_overprice_threshold:
                alerts.append({
                    "type": "overprice",
                    "code": code, "name": name,
                    "score": results["bayesian"].mispricing_score,
                    "message": f"市场过度定价({results['bayesian'].mispricing_score:+.0f}/100), 警惕回调"
                })

        # TAM-PEG估值泡沫
        if "tam_peg" in results and hasattr(results["tam_peg"], "valuation_verdict"):
            if results["tam_peg"].valuation_verdict == "bubble":
                alerts.append({
                    "type": "valuation_bubble",
                    "code": code, "name": name,
                    "message": "估值泡沫,强烈回避"
                })

        # 触发风险预警回调
        if alerts and self.config.enable_risk_alert:
            for cb in self.callbacks["on_risk_alert"]:
                try:
                    cb(alerts)
                except Exception as e:
                    logger.error(f"Risk callback error: {e}")

        return alerts

    def _aggregate_verdict(self, results: Dict[str, Any]) -> str:
        """综合判定"""
        scores = []

        if "bayesian" in results:
            mispricing = results["bayesian"].mispricing_score
            bayes_score = 100 - mispricing
            scores.append(bayes_score)

        if "tam_peg" in results:
            verdict_map = {"cheap": 90, "fair": 65, "expensive": 35, "bubble": 10}
            scores.append(verdict_map.get(results["tam_peg"].valuation_verdict, 50))

        if "dma" in results:
            scores.append(results["dma"].health_score)

        if not scores:
            return "hold"

        avg = sum(scores) / len(scores)

        if avg >= 75:
            return "strong_buy"
        elif avg >= 60:
            return "buy"
        elif avg >= 40:
            return "hold"
        elif avg >= 25:
            return "trim"
        else:
            return "sell"

    # ============================================================
    # 回调注册
    # ============================================================

    def register_callback(self, event: str, callback: Callable):
        """注册回调函数"""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
            logger.info(f"Registered callback for {event}")
        else:
            raise ValueError(f"Unknown event: {event}. Available: {list(self.callbacks.keys())}")

    # ============================================================
    # 查询接口
    # ============================================================

    def get_trigger_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取触发日志"""
        return self.trigger_log[-limit:]


# ============================================================
# 全局单例
# ============================================================

_global_trigger: Optional[FrameworkAutoTrigger] = None


def get_trigger() -> FrameworkAutoTrigger:
    """获取全局触发器单例"""
    global _global_trigger
    if _global_trigger is None:
        _global_trigger = FrameworkAutoTrigger()
    return _global_trigger


# ============================================================
# 示例回调
# ============================================================

def example_news_logger(news_text: str, hypotheses: List):
    """示例: 新闻分析日志回调"""
    print(f"\n📰 [回调] 新闻触发 Serenity Alpha:")
    print(f"   新闻: {news_text[:80]}")
    if hypotheses:
        print(f"   Top假设: {hypotheses[0].name} (强度{hypotheses[0].hypothesis_strength})")


def example_risk_logger(alerts: List[Dict[str, Any]]):
    """示例: 风险预警回调"""
    for alert in alerts:
        print(f"⚠️ [风险预警] {alert['type']}: {alert.get('name', '')} - {alert.get('message', '')}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("🚀 4框架自动触发器测试\n")

    # 1. 健康检查
    print("=" * 60)
    print("1️⃣ 健康检查")
    print("=" * 60)
    health = health_check()
    for name, state in health["frameworks"].items():
        print(f"  {'✅' if state == 'available' else '❌'} {name}: {state}")

    # 2. 创建触发器
    print("\n" + "=" * 60)
    print("2️⃣ 创建触发器 + 注册回调")
    print("=" * 60)
    trigger = get_trigger()
    trigger.register_callback("on_news_analysis", example_news_logger)
    trigger.register_callback("on_risk_alert", example_risk_logger)
    print("✅ 触发器已创建, 2个回调已注册")

    # 3. 模拟新闻事件
    print("\n" + "=" * 60)
    print("3️⃣ 模拟新闻事件触发")
    print("=" * 60)
    candidates = [
        {"code": "002335", "name": "英维克", "industry": "AI数据中心液冷",
         "market_cap": 180, "keywords": ["液冷", "数据中心"]},
        {"code": "300442", "name": "润泽科技", "industry": "AI",
         "market_cap": 350, "keywords": ["IDC"]},
    ]
    trigger.on_news("AI液冷需求加速,订单大幅增长", candidates)

    # 4. 模拟入池事件
    print("\n" + "=" * 60)
    print("4️⃣ 模拟入池事件触发")
    print("=" * 60)
    prices = [10.0 + i*0.05 for i in range(250)]
    new_stock = {
        "code": "002335", "name": "英维克", "industry": "AI数据中心液冷",
        "pe": 35, "growth_rate": 50, "market_cap": 180,
        "gross_margin": 32, "operating_margin": 18,
        "market_share": 0.15, "moat_indicators": {"brand": 7, "tech": 8, "scale": 6, "network": 6},
        "prices": prices, "current_price": prices[-1],
        "ma_20": prices[-20], "ma_50": prices[-50], "ma_100": prices[-100], "ma_200": prices[-200],
        "eps_growth": 45, "revenue_growth": 50, "analyst_rating_change": "upgraded",
        "eps_ttm": 1.5, "forward_eps": 2.0, "analyst_target_price": 60.0,
        "new_info": {"order_book_growth": 0.4}, "sentiment_score": 0.4,
    }
    result = trigger.on_stock_added_to_pool(new_stock)
    print(f"分析结果: {len(result['results'])} 个框架完成")
    if result['risk_alerts']:
        print(f"风险预警: {len(result['risk_alerts'])} 条")

    # 5. 模拟每日扫描
    print("\n" + "=" * 60)
    print("5️⃣ 模拟每日扫描")
    print("=" * 60)
    summary = trigger.daily_scan([new_stock])
    print(f"扫描报告: {summary}")

    # 6. 触发日志
    print("\n" + "=" * 60)
    print("6️⃣ 触发日志")
    print("=" * 60)
    for log in trigger.get_trigger_log():
        print(f"  [{log['timestamp']}] {log['type']}: {log.get('code') or log.get('input_summary', '')[:40]}")

    print("\n✅ 自动触发器测试完成!")
