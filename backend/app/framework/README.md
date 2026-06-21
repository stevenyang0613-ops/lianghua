# LiangHua 4框架投资研究系统

> AI 不应该只是帮你找答案,而应该帮你建立研究框架。

## 🎯 4个研究框架

| 框架 | 用途 | 何时使用 |
|------|------|---------|
| **Serenity Alpha** | 找线索 | 看到新闻,想找产业链投资线索 |
| **TAM-Adj-PEG** | 看估值 | 判断成长股估值是否合理 |
| **GF-DMA Health Index** | 看走势 | 判断上涨是否健康,是否过热 |
| **Bayesian Intrinsic Growth** | 看定价 | 判断市场是否过度,上涨是基本面驱动还是FOMO |

## 📦 安装验证

```bash
# 验证框架可用
python3 -m app.framework.api

# 验证自动触发
python3 -m app.framework.auto_trigger

# 运行全部测试
python3 -m app.framework.test_frameworks
```

输出 `✅ 所有框架可用` 表示安装成功。

## 🚀 自动调用方式

### 方式1: 编程调用 (推荐)

```python
from app.framework.api import (
    analyze_news,        # Serenity Alpha
    analyze_valuation,   # TAM-Adj-PEG
    analyze_trend,       # GF-DMA
    analyze_pricing,     # Bayesian
    full_research,       # 集成
    health_check,
)

# 健康检查
print(health_check())

# 单框架调用
hypotheses = analyze_news("AI液冷需求加速", candidates)
valuation = analyze_valuation(stock_data)
health = analyze_trend(stock_data)
pricing = analyze_pricing(stock_data)

# 集成调用
results = full_research(news="AI需求加速", candidates=candidates)
```

### 方式2: 自动触发器 (推荐集成到业务)

```python
from app.framework.auto_trigger import get_trigger, FrameworkAutoTrigger

# 1. 获取全局触发器
trigger = get_trigger()

# 2. 注册回调
def my_news_callback(news, hypotheses):
    print(f"Top假设: {hypotheses[0].name}")

trigger.register_callback("on_news_analysis", my_news_callback)

# 3. 在业务事件中触发
# - 检测到新闻时
trigger.on_news("AI数据中心需求爆发", candidates)

# - 新标的入池时
trigger.on_stock_added_to_pool(stock_data)

# - 每日定时扫描
report = trigger.daily_scan(holdings)
```

### 方式3: CLI 命令

```bash
# 新闻分析
python3 -m app.framework.cli news "AI数据中心需求爆发,液冷加速"

# 集成研究
python3 -m app.framework.cli full --news "AI液冷需求加速"

# 全部测试
python3 -m app.framework.cli test
```

## 🔌 业务集成示例

### 集成到新闻爬虫
```python
# 在 src/crawler/tasks.py 中
from app.framework.auto_trigger import get_trigger

async def process_news_item(news):
    trigger = get_trigger()
    candidates = await get_all_stock_candidates()
    hypotheses = trigger.on_news(news.text, candidates)

    if hypotheses:
        # 持久化分析结果
        await save_hypotheses(hypotheses)
        # 推送通知
        await notify_top_hypothesis(hypotheses[0])
```

### 集成到每日报告
```python
# 在 src/reporting/daily_report.py 中
from app.framework.auto_trigger import get_trigger

async def generate_daily_report():
    trigger = get_trigger()
    holdings = await get_today_holdings()
    report = trigger.daily_scan(holdings)

    # 添加到日报
    daily_report.add_section("4框架分析", report)
```

### 集成到观察池入池逻辑
```python
# 在 src/strategy/service.py 中
from app.framework.auto_trigger import get_trigger

async def add_to_pool(stock):
    trigger = get_trigger()
    result = trigger.on_stock_added_to_pool(stock)

    # 检查是否触发风险预警
    if result and result.get("risk_alerts"):
        await send_risk_alert(result["risk_alerts"])
```

### 集成到 FastAPI
```python
# 在 api/main.py 中
from fastapi import FastAPI
from app.framework.api import (
    analyze_news, analyze_valuation, analyze_trend,
    analyze_pricing, full_research, health_check
)

app = FastAPI()

@app.get("/api/frameworks/health")
async def health():
    return health_check()

@app.post("/api/frameworks/news")
async def news_analysis(news: str, candidates: list):
    return analyze_news(news, candidates)

@app.post("/api/frameworks/valuation")
async def valuation_analysis(stock: dict):
    return analyze_valuation(stock).__dict__

@app.post("/api/frameworks/trend")
async def trend_analysis(stock: dict):
    return analyze_trend(stock).__dict__

@app.post("/api/frameworks/pricing")
async def pricing_analysis(stock: dict):
    return analyze_pricing(stock).__dict__

@app.post("/api/frameworks/full")
async def full_research_endpoint(news: str = None, candidates: list = []):
    results = full_research(news, candidates)
    return [r.__dict__ for r in results]
```

## 📊 自动触发场景

| 场景 | 触发器 | 调用框架 |
|------|--------|----------|
| 检测到行业新闻 | `on_news()` | Serenity Alpha |
| 新标的入观察池 | `on_stock_added_to_pool()` | TAM-PEG + DMA + Bayesian |
| 每日收盘后 | `daily_scan()` | 全部3个评分框架 |
| DMA健康度过低 | `_check_risk_alerts()` | 风险回调 |
| Bayesian定价偏差>50 | `_check_risk_alerts()` | 风险回调 |
| 估值判定为bubble | `_check_risk_alerts()` | 风险回调 |

## 🎓 4个框架的核心思想

### Serenity Alpha (找线索)
```
新闻 → 真实需求 → 财务传导 → 小市值弹性 → 验证路径
"AI数据中心带动液冷需求上升"
  ↓ 不只说"利好液冷"
  拆: 谁真正受益? → 英维克(液冷直接供应商)
  拆: 需求进入哪家公司的收入项? → 订单/出货
  拆: 市值够不够小? → 180亿,弹性足
  拆: 几个季度能验证? → Q2订单环比
```

### TAM-Adj-PEG (看估值)
```
传统 PEG = PE / 增速
TAM-Adj-PEG = (PE / 增速) / 质量因子
质量因子 = f(TAM空间, 渗透率, 定价权, 利润率, 护城河)
高质量公司允许PEG更高
```

### GF-DMA Health Index (看走势)
```
健康度 = f(均线排列, 偏离度, 基本面, 预期, FOMO)
完美多头 + 轻度偏离 + 基本面支撑 = 健康上涨
极端偏离 + 弱基本面 + 高FOMO = 短线见顶
```

### Bayesian Intrinsic Growth (看定价)
```
先验: 历史EPS增长 12%
似然: 新信息(订单+40%, 指引+30%) → 调整 +5%
后验: 真实增长 = 17%
市场隐含增长: 反推DCF → 25%
定价偏差: 25% - 17% = +8% (偏贵)
```

## 📈 综合研究流程

```
新闻输入
   ↓
[Serenity Alpha] 找出受益标的 → 假设强度排序
   ↓
[TAM-Adj-PEG] 评估估值 → 估值判定
   ↓
[GF-DMA Health] 检查走势 → 健康度评分
   ↓
[Bayesian] 计算内在价值 → 定价偏差
   ↓
[ResearchOrchestrator] 加权综合 → 最终建议
```

## 🔧 文件清单

| 文件 | 作用 |
|------|------|
| `serenity_alpha.py` | 框架1: 新闻→假设 |
| `tam_adj_peg.py` | 框架2: 成长股估值 |
| `gf_dma_health.py` | 框架3: 走势健康度 |
| `bayesian_intrinsic_growth.py` | 框架4: 定价合理性 |
| `orchestrator.py` | 4框架调度器 |
| `api.py` | 编程API入口 |
| `auto_trigger.py` | 自动触发器(业务集成) |
| `cli.py` | CLI命令 |
| `test_frameworks.py` | 测试套件 |
| `__init__.py` | 模块导出 |
