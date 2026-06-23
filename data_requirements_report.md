# 量化转债回测平台 — 数据需求清单

> 生成时间：2026-06-23
> 项目路径：/Users/mac/lianghua
> 技术栈：Python (FastAPI) + TypeScript (React) + Electron

---

## 一、项目概述

本项目是一个**可转债量化回测与实时交易平台**，核心策略包括：
- **璇玑十二因子**（xuanji_twelve_factor）
- **松岗七维打分**（xibu_seven_dimension）
- **多因子择时模型**（enhanced_timing_model）
- **回测引擎**（BacktestEngine）

数据需求覆盖：可转债行情、正股行情、财务数据、宏观数据、资金流向、行业数据、事件公告等。

---

## 二、数据类型总览

| 数据类型 | 核心用途 | 更新频率 | 数据量级 |
|---------|---------|---------|---------|
| 可转债实时行情 | 策略计算、WebSocket 推送 | 5-60 秒 | 500+ 只转债 |
| 正股实时行情 | 转股价值计算、PE/PB 估值 | 5-60 秒 | 5000+ 只 A 股 |
| 转债历史K线 | 回测、波动率计算 | 日频 | 3.5+ 年/只 |
| 正股历史K线 | 回测、动量计算 | 日频 | 90 天~3 年/只 |
| 财务数据 | 基本面评分（ROE/GPM/资产负债率） | 日/季度 | 5000+ 只 |
| 行业数据 | 行业轮动、行业景气度 | 日/周 | 100+ 行业 |
| 宏观数据 | 择时信号、政策评分 | 日/月 | 20+ 指标 |
| 资金流向 | 主力净流入、北向资金 | 日频 | 全市场 |
| 事件数据 | 强赎/下修/回售公告 | 实时 | 公告级 |
| 评级数据 | 信用风险评分 | 日频 | 500+ 只 |

---

## 三、核心数据模型字段定义

### 3.1 ConvertibleQuote（可转债实时行情）

**基础字段（16个）**
| 字段名 | 类型 | 说明 | 数据来源 |
|-------|------|------|---------|
| `code` | string | 转债代码（6位，11/12/13开头） | bond_zh_cov |
| `name` | string | 转债简称 | bond_zh_cov |
| `stock_code` | string | 正股代码（6位） | bond_zh_cov |
| `stock_name` | string | 正股简称 | bond_zh_cov |
| `price` | float | 最新价（元） | Sina spot / JSL / EM |
| `change_pct` | float | 涨跌幅(%) | Sina spot |
| `stock_price` | float | 正股价（元） | Sina spot |
| `stock_change_pct` | float | 正股涨跌幅(%) | Sina spot |
| `conversion_price` | float | 转股价（元） | bond_zh_cov |
| `conversion_value` | float | 转股价值 = 正股价/转股价×100 | 计算 |
| `premium_ratio` | float | 转股溢价率(%) | JSL / EM |
| `dual_low` | float | 双低值 = 价格 + 溢价率 | 计算 |
| `ytm` | float | 到期收益率(%) | 计算（阶梯利率） |
| `volume` | float | 成交额（亿元） | Sina spot |
| `remaining_years` | float | 剩余年限（年） | THS 到期日 / 上市日+6年 |
| `forced_call_days` | int | 强赎倒计时天数 | JSL bond_cb_redeem_jsl |

**强赎/状态字段（5个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `is_called` | bool | 是否已公告强赎/将强赎 |
| `call_status` | string | 强赎状态原文（已公告强赎/公告要强赎/已满足强赎条件/公告不强赎） |
| `last_trade_date` | date | 最后交易日 |
| `maturity_date` | date | 到期日 |
| `redemption_price` | float | 强赎价格（元/张） |

**基本面字段（8个）**
| 字段名 | 类型 | 说明 | 数据来源 |
|-------|------|------|---------|
| `industry` | string | 正股所属行业 | EM F10 / THS / Sina / yfinance |
| `roe` | float | 净资产收益率(%) | THS 财务摘要 |
| `gpm` | float | 毛利率(%) | THS 财务摘要 |
| `cagr` | float | 复合增长率(%) | 计算 |
| `debt_ratio` | float | 资产负债率(%) | THS 财务摘要 |
| `current_ratio` | float | 流动比率 | THS 财务摘要 |
| `pe` | float | 市盈率(TTM) | Baidu / THS / MX |
| `pb` | float | 市净率 | Baidu / THS / MX |

**波动率/期权字段（4个）**
| 字段名 | 类型 | 说明 | 数据来源 |
|-------|------|------|---------|
| `iv` | float | 隐含波动率(%) | 历史价格计算（Black-Scholes） |
| `iv_source` | string | IV来源：actual, hv_proxy, estimated | - |
| `hv` | float | 历史波动率(%) | 历史价格计算 |
| `pure_bond_premium_ratio` | float | 纯债溢价率(%) | bond_zh_cov_value_analysis |
| `bond_value` | float | 纯债价值（元） | bond_zh_cov_value_analysis |

**评级/信用字段（3个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `rating` | string | 信用评级（AAA/AA+/AA/AA-...） |
| `rating_score` | float | 评级评分（0-100，AAA=95, AA=85） |
| `outstanding_scale` | float | 剩余规模（亿元） |

**动量字段（5个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `momentum_5d` | float | 5日动量(%) |
| `momentum_10d` | float | 10日动量(%) |
| `momentum_20d` | float | 20日动量(%) |
| `momentum_60d` | float | 60日动量(%) |
| `turnover_rate` | float | 正股换手率(%) |

**资金流向字段（5个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `net_capital_flow` | float | 主力资金净流入（万元） |
| `net_capital_flow_pct` | float | 主力资金净流入占比(%) |
| `net_super_flow` | float | 超大单净流入（万元） |
| `net_big_flow` | float | 大单净流入（万元） |
| `margin_balance` | float | 融资余额（亿元） |

**事件/特殊字段（10个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `event_score` | float | 事件因子评分（0-1） |
| `event_detail` | string | 最近事件摘要 |
| `concepts` | string[] | 正股所属概念板块 |
| `north_net` | float | 北向资金持股（万股） |
| `lhb_count` | int | 近5日龙虎榜次数 |
| `block_trade_amount` | float | 近5日大宗交易额（万元） |
| `holder_num_change` | float | 股东户数变化率(%) |
| `buyback_amount` | float | 回购金额（亿元） |
| `mgmt_buy_price` | float | 管理层增持价 |
| `pledge_ratio` | float | 大股东质押比例(%) |

**宏观关联字段（6个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `sentiment_score` | float | 新闻情绪得分（-1到1） |
| `macro_cpi` | float | 最新CPI同比(%) |
| `macro_ppi` | float | 最新PPI同比(%) |
| `macro_m2` | float | 最新M2同比(%) |
| `macro_lpr` | float | 最新LPR(%) |
| `macro_policy_score` | float | 宏观政策信号评分（0-100） |
| `macro_event_score` | float | 宏观事件冲击评分（0-100） |

**财务预测字段（5个）**
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `eps_forecast` | float | 一致预期EPS |
| `eps` | float | 每股收益 |
| `bps` | float | 每股净资产 |
| `revenue_yoy` | float | 营业总收入同比增长(%) |
| `profit_yoy` | float | 净利润同比增长(%) |
| `restricted_release_amount` | float | 近期解禁金额（亿元） |

---

### 3.2 BacktestResult（回测结果）

| 字段名 | 类型 | 说明 |
|-------|------|------|
| `total_return_pct` | float | 总收益率(%) |
| `annual_return_pct` | float | 年化收益率(%) |
| `max_drawdown_pct` | float | 最大回撤(%) |
| `sharpe_ratio` | float | 夏普比率 |
| `sortino_ratio` | float | 索提诺比率 |
| `calmar_ratio` | float | 卡尔玛比率 |
| `win_rate` | float | 胜率(%) |
| `total_trades` | int | 总交易笔数 |
| `avg_holding_days` | float | 平均持仓天数 |
| `trades` | TradeRecord[] | 交易记录列表 |
| `monthly_returns` | MonthlyReturn[] | 月度收益列表 |
| `portfolio_values` | dict | 每日组合净值 |

### 3.3 MacroData（宏观数据）

| 字段名 | 类型 | 说明 | 数据来源 |
|-------|------|------|---------|
| `treasury_10y_yield` | float | 10年期国债收益率 | 中国债券信息网 |
| `treasury_5y_yield` | float | 5年期国债收益率 | 中国债券信息网 |
| `treasury_2y_yield` | float | 2年期国债收益率 | 中国债券信息网 |
| `credit_spread_aa` | float | AA企业债-国债信用利差 | 计算 |
| `shibor_overnight` | float | Shibor隔夜利率 | 上海银行间同业拆放利率 |
| `shibor_1w` | float | Shibor 1周利率 | 上海银行间同业拆放利率 |
| `shibor_1m` | float | Shibor 1月利率 | 上海银行间同业拆放利率 |
| `lpr_1y` | float | 1年期LPR | 中国人民银行 |
| `lpr_5y` | float | 5年期LPR | 中国人民银行 |
| `pmi_current` | float | 制造业PMI | 国家统计局 |
| `cpi` | float | CPI同比 | 国家统计局 |
| `ppi` | float | PPI同比 | 国家统计局 |
| `m2_growth` | float | M2同比增速 | 中国人民银行 |
| `social_financing_growth` | float | 社融增量增速 | 中国人民银行 |
| `gdp_growth` | float | GDP增速 | 国家统计局 |
| `cb_median_premium` | float | 转债溢价率中位数 | 计算 |
| `cb_median_price` | float | 转债价格中位数 | 计算 |
| `cb_below_par_count` | float | 破面转债数量 | 计算 |
| `stock_index_current` | float | 沪深300当前点位 | 新浪/东方财富 |
| `stock_pe_median` | float | A股PE中位数 | 计算 |
| `stock_pb_median` | float | A股PB中位数 | 计算 |
| `stock_pe_percentile` | float | A股PE历史分位数 | 计算 |
| `north_bound_net_flow` | float | 北向资金净流入 | 东方财富 |
| `margin_balance` | float | 融资融券余额 | 东方财富 |
| `limit_up_count` | float | 涨停数 | 计算 |
| `limit_down_count` | float | 跌停数 | 计算 |
| `pcr_ratio` | float | 认沽/认购比(PCR) | 期权市场 |
| `vix_index` | float | 波动率指数(VIX) | 期权市场 |
| `rsi_14` | float | 14日RSI | 计算 |
| `macd_signal` | str | MACD信号（bullish/bearish/neutral） | 计算 |

---

## 四、数据源详细清单

### 4.1 主数据源：AKShare（Python 金融数据接口库）

AKShare 是项目最主要的数据来源，覆盖东方财富、同花顺、新浪财经、百度股市通等多个数据提供商。

**可转债行情**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.bond_zh_cov()` | 东方财富 | 可转债基础列表 | 债券代码/简称/转股价/转股价值/溢价率/到期日/评级/正股代码 |
| `ak.bond_zh_hs_cov_spot()` | 新浪财经 | 实时行情 | 最新价/涨跌幅/成交额/成交量/开盘价/最高价/最低价 |
| `ak.bond_zh_cov_info_ths()` | 同花顺 | 到期时间/上市日期 | 到期时间/债券代码 |
| `ak.bond_cb_redeem_jsl()` | 集思录 | 强赎状态/可交换债 | 强赎状态/最后交易日/到期日/强赎价/剩余规模/正股价 |
| `ak.bond_zh_cov_value_analysis()` | 东方财富数据中心 | 纯债价值/转股价值历史 | 日期/收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率 |

**正股行情**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.stock_zh_a_spot()` | 新浪财经 | 全A股实时行情 | 最新价/涨跌幅/成交额/成交量/换手率/PE/PB |
| `ak.stock_zh_a_hist_tx()` | 腾讯财经 | 正股历史K线 | 日期/开盘/收盘/最高/最低/成交量/成交额（90天+） |
| `ak.stock_zh_a_hist()` | 东方财富 | 正股历史K线（备用） | 日期/收盘/成交量（IP可能被封） |

**估值数据**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.stock_zh_valuation_baidu()` | 百度股市通 | PE/PB(TTM) | 近1年每日估值数据（PE+PB分别调用） |
| `ak.stock_financial_abstract_ths()` | 同花顺 | 财务摘要 | EPS/BPS/ROE/毛利率/净利率/资产负债率/营业收入 |
| `ak.stock_individual_info_ths()` | 同花顺 | 个股信息 | 行业/所属行业 |

**资金流向**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.stock_individual_fund_flow_rank()` | 东方财富 | 个股资金流向排名 | 主力净流入/净占比/超大单/大单/中单/小单 |
| `ak.stock_fund_flow_individual()` | 东方财富 | 个股资金流向 | 净流入/流出/净额/换手率 |
| `ak.stock_fund_flow_industry()` | 东方财富 | 行业资金流向 | 行业净流入/领涨股 |
| `ak.stock_hsgt_fund_flow_summary_em()` | 东方财富 | 沪深港通资金 | 北向资金净流入/余额/交易状态 |

**宏观数据**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.macro_china_pmi()` | 国家统计局 | 制造业PMI | 今值/前值 |
| `ak.macro_china_cpi()` | 国家统计局 | CPI | 同比/环比 |
| `ak.macro_china_ppi()` | 国家统计局 | PPI | 同比/环比 |
| `ak.macro_china_m2()` | 中国人民银行 | M2 | 同比增速 |
| `ak.macro_china_gdp()` | 国家统计局 | GDP | 季度增速 |
| `ak.bond_china_yield()` | 中国债券信息网 | 国债收益率 | 2年/5年/10年收益率 |
| `ak.macro_china_shibor_all()` | Shibor | 同业拆放利率 | 隔夜/1周/1月利率 |
| `ak.stock_zh_index_daily()` | 新浪 | 指数日线 | 中证转债指数/沪深300 |

**特殊数据**
| 接口 | 来源 | 用途 | 字段 |
|------|------|------|------|
| `ak.stock_gpzy_pledge_ratio_em()` | 东方财富 | 大股东质押率 | 质押比例 |
| `ak.stock_ggcg_em()` | 东方财富 | 高管增减持 | 增减持金额/价格 |
| `ak.stock_dzjy_mrmx()` | 东方财富 | 大宗交易 | 成交价/成交量/买卖营业部 |
| `ak.stock_lhb_em()` | 东方财富 | 龙虎榜 | 上榜次数/营业部 |
| `ak.stock_zh_a_gdhs_detail_em()` | 东方财富 | 股东户数 | 股东户数/变化率 |
| `ak.stock_margin_detail_em()` | 东方财富 | 融资融券 | 融资余额/融券余额 |
| `ak.stock_zyjs_ths()` | 同花顺 | 个股主要指标 | 综合财务指标 |
| `ak.stock_market_activity_legu()` | 乐咕 | 市场情绪 | 涨停/跌停/涨跌比 |
| `ak.stock_zt_pool_em()` | 东方财富 | 涨停池 | 涨停股数量 |

### 4.2 专业数据源：Tushare Pro

| 接口 | 用途 | 字段 |
|------|------|------|
| `pro.cb_daily()` | 可转债日线 | 收盘价/纯债价值/转股价值/纯债溢价率/转股溢价率/成交量/成交额 |
| `pro.cb_basic()` | 可转债基本信息 | 到期日/转股价/票面利率/补偿利率/剩余规模/上市日/退市日 |
| `pro.cb_rate()` | 可转债票息表 | 逐年票息率 |
| `pro.cb_share()` | 可转债股本变动 | 剩余规模变动 |

### 4.3 第三方/备用数据源

| 数据源 | 用途 | 接口方式 |
|-------|------|---------|
| **妙想 MX** | 自然语言查询 PE/PB（兜底） | REST API（`mx_adapter.py`） |
| **TDX 通达信** | 补充缺失的转债价格/正股行情 | 本地二进制协议（`tdx_adapter.py`） |
| **巨潮资讯 cninfo** | 高管增减持/解禁/股东户数（默认禁用） | `ak.stock_hold_management_detail_cninfo()`（macOS Electron 沙盒中可能失败） |
| **yfinance** | 行业数据兜底（美股接口） | Yahoo Finance API |
| **东方财富数据中心 Web API** | 转债日K线（push2his 被封时备用） | `https://datacenter-web.eastmoney.com/api/data/v1/get` |
| **新浪财经 F10** | 行业数据兜底 | `https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/` |

---

## 五、数据流完整路径

### 5.1 实时行情数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据采集层                                     │
├─────────────────────────────────────────────────────────────────────┤
│  AKShare (bond_zh_cov) ──→ 转债基础信息（转股价/溢价率/到期日）          │
│  AKShare (bond_zh_hs_cov_spot) ──→ 实时价格/涨跌幅/成交额              │
│  AKShare (bond_zh_cov_info_ths) ──→ 到期时间/剩余年限                  │
│  AKShare (bond_cb_redeem_jsl) ──→ 强赎状态/可交换债                   │
│  AKShare (stock_zh_a_spot) ──→ 正股价格/涨跌幅/PE/PB                  │
│  AKShare (stock_individual_fund_flow_rank) ──→ 主力资金流向             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        数据增强层（data_enrich）                       │
├─────────────────────────────────────────────────────────────────────┤
│  行业数据 ──→ _refresh_industry_cache → EM F10 / THS / Sina / yfinance │
│  财务数据 ──→ _refresh_fin_cache → THS 财务摘要（EPS/ROE/毛利率）        │
│  波动率数据 ──→ _refresh_volatility_cache → 历史价格计算 HV/IV         │
│  动量数据 ──→ _refresh_momentum_cache → 历史价格计算 5/10/20/60日动量  │
│  宏观数据 ──→ _refresh_macro_cache → CPI/PPI/M2/LPR/PMI               │
│  事件数据 ──→ _refresh_event_cache → 公告解析（下修/强赎/回售）         │
│  北向资金 ──→ _refresh_north_cache → 东方财富北向资金明细               │
│  股东户数 ──→ _refresh_holder_cache → 东方财富股东户数详情             │
│  大宗交易 ──→ _refresh_block_trade_cache → 东方财富大宗交易明细         │
│  龙虎榜 ──→ _refresh_lhb_cache → 东方财富龙虎榜                        │
│  回购 ──→ _refresh_buyback_cache → 东方财富回购数据                     │
│  概念板块 ──→ _refresh_concept_cache → 东方财富概念板块                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        数据存储层                                     │
├─────────────────────────────────────────────────────────────────────┤
│  内存缓存 ──→ _spot_map / _fin_map / _vol_map 等（线程安全 RLock）     │
│  文件缓存 ──→ ~/.lianghua/data_cache/*.json（TTL 控制）               │
│  DuckDB ──→ market.db / kline_cache.db（历史行情/回测数据）            │
│  SQLite ──→ lianghua.db（回测结果/交易记录/用户数据）                    │
│  估值缓存 ──→ valuations_cache.db（PE/PB 估值）                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        API 服务层                                     │
├─────────────────────────────────────────────────────────────────────┤
│  /api/v1/market/quotes ──→ 全量转债行情（GET）                        │
│  /api/v1/market/quotes/{code} ──→ 单只转债行情（GET）                 │
│  /api/v1/market/exchangeable ──→ 可交换债行情（GET）                   │
│  /api/v1/market/industries ──→ 行业聚合数据（GET）                     │
│  /api/v1/market/concepts ──→ 概念板块聚合（GET）                        │
│  /api/v1/score/ranking ──→ 评分排名（GET/POST）                       │
│  /api/v1/fund_flow/* ──→ 资金流向数据（GET）                           │
│  /api/v1/backtest/* ──→ 回测引擎接口（POST/GET）                        │
│  /api/v1/strategies/* ──→ 策略配置与运行（POST/GET）                     │
│  /api/v1/data-sources/* ──→ 数据源管理（POST/GET）                      │
│  /api/v1/extra/* ──→ 额外数据批量获取（POST）                           │
│  /api/v1/macro/* ──→ 宏观数据（GET）                                   │
│  /api/v1/timing/* ──→ 择时信号（GET）                                   │
│  /api/v1/paper-trade/* ──→ 模拟交易（POST/GET）                         │
│  /api/v1/ai/* ──→ AI 分析接口（POST/GET）                              │
│  /ws/market ──→ WebSocket 实时行情推送（增量压缩）                       │
│  /ws/signals ──→ WebSocket 择时信号推送                                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        前端展示层                                     │
├─────────────────────────────────────────────────────────────────────┤
│  React + TypeScript + Electron                                        │
│  ├── 行情列表页（ConvertibleQuote[]）                                  │
│  ├── 转债详情页（单只转债全量字段）                                    │
│  ├── 评分排名页（score/ranking）                                       │
│  ├── 回测分析页（backtest/optimization）                               │
│  ├── 择时信号页（timing/signals）                                      │
│  ├── 宏观仪表盘（macro/dashboard）                                     │
│  ├── 资金流向页（fund_flow）                                           │
│  ├── 模拟交易页（paper_trade）                                         │
│  └── 策略配置页（strategies）                                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 回测数据流

```
回测请求（BacktestRequest）
  ├── strategy: string（策略名称）
  ├── params: Record<string, number|string>（策略参数）
  ├── start_date: string（开始日期）
  ├── end_date: string（结束日期）
  ├── config: BacktestConfig（佣金/滑点/冲击成本/初始资金）
  └── optimization: OptimizationConfig（参数优化配置）
           │
           ▼
    ┌────────────────────────────┐
    │  BacktestEngine.run()      │
    └────────────────────────────┘
           │
           ├──→ _build_data() → 从 DuckDB/SQLite 加载历史行情
           │       ├── 转债日行情（price/premium_ratio/bond_value/conversion_value）
           │       ├── 正股日行情（stock_price/change_pct）
           │       ├── 估值数据（PE/PB/ROE/GPM）
           │       └── 宏观数据（CPI/PPI/M2/LPR/PMI）
           │
           ├──→ strategy.generate_signals(df) → 生成买卖信号
           │
           ├──→ portfolio.execute() → 执行交易（含成本模型）
           │
           └──→ 计算 PerformanceMetrics（夏普/索提诺/卡尔玛/最大回撤等）
```

---

## 六、API 端点与数据接口

### 6.1 市场数据 API

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/market/quotes` | GET | 全量转债行情 | `fields`（可选字段过滤） | `{total, bonds[], updated_at}` |
| `/market/quotes/{code}` | GET | 单只转债行情 | `code` | `ConvertibleQuote` |
| `/market/exchangeable` | GET | 可交换债行情 | - | `{total, bonds[], updated_at}` |
| `/market/industries` | GET | 行业聚合 | `fields`, `horizon` | `{industries[]}` |
| `/market/concepts` | GET | 概念板块聚合 | `fields`, `top_n` | `{concepts[]}` |
| `/market/stock-industries` | GET | 正股行业聚合 | `fields` | `{industries[]}` |
| `/market/macro` | GET | 宏观数据 | - | `MacroData` |
| `/market/timing-signal` | GET | 择时信号 | `horizon` | `{signal, score, recommendation}` |

### 6.2 评分 API

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/score/ranking` | GET | 评分排名 | `strategy`, `weights`, `filters` | `{bonds[], scores[]}` |
| `/score/xuanji` | GET | 璇玑十二因子评分 | `weights`, `top_n` | `{bonds[], factor_scores[]}` |
| `/score/xibu` | GET | 松岗七维评分 | `weights`, `top_n` | `{bonds[], dimension_scores[]}` |
| `/score/backtest` | POST | 评分回测 | `strategy`, `params`, `start_date`, `end_date` | `ScoreBacktestResponse` |

### 6.3 回测 API

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/backtest/run` | POST | 运行回测 | `BacktestRequest` | `BacktestResult` |
| `/backtest/optimize` | POST | 参数优化 | `BacktestRequest` + `OptimizationConfig` | `OptimizationResult` |
| `/backtest/history` | GET | 回测历史 | `limit`, `offset` | `BacktestHistoryResponse` |
| `/backtest/{id}` | GET | 回测详情 | `id` | `BacktestResult` |
| `/backtest/walk-forward` | POST | Walk-Forward 验证 | `BacktestRequest` + `window_config` | `{results[]}` |

### 6.4 数据源 API

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/data-sources/valuations` | POST | 批量获取PE/PB | `stock_codes`, `max_workers`, `async_task` | `{code: {pe, pb}}` |
| `/data-sources/hist-prices` | POST | 正股历史K线 | `stock_code`, `start_date`, `end_date` | `DataFrame` |
| `/data-sources/cb-daily-tushare` | GET | Tushare 转债日线 | `trade_date`, `start_date`, `end_date` | `DataFrame` |
| `/data-sources/cb-basic-tushare` | GET | Tushare 转债基本信息 | - | `{code: {...}}` |
| `/data-sources/connect` | POST | 连接所有数据源 | - | `{status, results}` |
| `/data-sources/tasks/{id}` | GET | 查询后台任务 | `task_id` | `TaskInfo` |

### 6.5 额外数据源 API（后台任务支持）

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/extra/value-analysis` | POST | 转债纯债价值/转股价值历史 | `bond_codes`, `max_workers`, `async_task` | `DataFrame` |
| `/extra/bond-daily-em` | POST | 转债日K线（东方财富） | `bond_codes`, `start_date`, `end_date` | `DataFrame` |
| `/extra/industry` | POST | 正股行业归属 | `stock_codes`, `max_workers` | `{code: industry}` |
| `/extra/csi-index` | POST | 中证转债指数历史 | `start_date`, `end_date` | `DataFrame` |
| `/extra/financial-ths` | POST | THS 财务摘要 | `stock_codes`, `max_workers` | `{code: {roe, gpm, eps, bps}}` |
| `/extra/bond-kline-em` | POST | 转债K线（EM数据中心） | `bond_codes`, `start_date`, `end_date` | `DataFrame` |

### 6.6 资金流向 API

| 端点 | 方法 | 说明 | 请求参数 | 响应数据 |
|------|------|------|---------|---------|
| `/fund_flow/individual` | GET | 个股资金流向 | `limit`, `sort_by` | `IndividualFundFlowResponse` |
| `/fund_flow/industry` | GET | 行业资金流向 | `limit` | `IndustryFundFlowResponse` |
| `/fund_flow/main` | GET | 主力资金流向 | `limit`, `sort_by` | `MainFundFlowResponse` |
| `/fund_flow/turnover-rank` | GET | 换手率排名 | `limit`, `period` | `TurnoverRankResponse` |
| `/fund_flow/hsgt` | GET | 沪深港通资金流向 | `limit` | `HsgtFundFlowResponse` |

---

## 七、数据缓存策略

### 7.1 缓存层级

| 层级 | 存储介质 | TTL | 用途 |
|------|---------|-----|------|
| L1 | 内存字典（Python globals） | 300s（spot）~ 86400s（industry） | 高频读取（enrich_quotes） |
| L2 | JSON 文件（~/.lianghua/data_cache/） | 同上 | 进程重启恢复 |
| L3 | DuckDB（market.db） | 日级 | 历史行情/每日快照 |
| L4 | SQLite（lianghua.db） | 持久 | 回测结果/交易记录/用户配置 |
| L5 | IndexedDB（前端） | 5分钟~1小时 | 前端离线缓存 |

### 7.2 各缓存文件说明

| 缓存文件 | 内容 | TTL | 更新方式 |
|---------|------|-----|---------|
| `stock_spot.json` | 正股实时行情（price/change_pct/pe/pb/turnover_rate） | 300s | 后台刷新 |
| `stock_fin.json` | 财务数据（roe/gpm/eps/bps/debt_ratio/revenue） | 86400s | 后台刷新 |
| `stock_industry.json` | 行业映射（code → industry） | 604800s | 后台刷新 |
| `stock_volatility.json` | 波动率（code → hv/iv） | 86400s | 后台刷新 |
| `stock_momentum.json` | 动量（code → 5/10/20/60日动量） | 86400s | 后台刷新 |
| `stock_fund_flow.json` | 资金流向（code → net_main/net_main_pct） | 300s | 后台刷新 |
| `stock_debt.json` | 债务数据（code → debt_ratio） | 86400s | 后台刷新 |
| `bond_event.json` | 事件数据（code → event_score/event_detail） | 86400s | 后台刷新 |
| `stock_concept.json` | 概念板块（code → concepts[]） | 604800s | 后台刷新 |
| `stock_buyback.json` | 回购数据（code → buyback_amount） | 259200s | 后台刷新 |
| `stock_pledge.json` | 质押数据（code → pledge_ratio） | 86400s | 后台刷新 |
| `macro_cpi.json` | CPI数据 | 86400s | 后台刷新 |
| `macro_ppi.json` | PPI数据 | 86400s | 后台刷新 |
| `macro_m2.json` | M2数据 | 86400s | 后台刷新 |
| `macro_lpr.json` | LPR数据 | 86400s | 后台刷新 |
| `bond_outstanding.json` | 剩余规模 | 86400s | 后台刷新 |
| `bond_price.json` | 转债历史价格 | 300s | 后台刷新 |
| `bond_coupon_rate.json` | 票面利率 | 86400s | 后台刷新 |
| `stock_names.json` | 股票名称映射 | 86400s | 后台刷新 |
| `stock_analyst_rank.json` | 分析师评级 | 86400s | 后台刷新 |
| `stock_main_biz.json` | 主营业务 | 86400s | 后台刷新 |
| `stock_mgmt.json` | 高管增减持 | 86400s | 后台刷新 |

---

## 八、配置与依赖

### 8.1 环境变量配置（.env）

| 变量名 | 说明 | 默认值 |
|-------|------|-------|
| `LH_TUSHARE_TOKEN` | Tushare Pro API Token | 空 |
| `LH_AKSHARE_PROXY_TOKEN` | AKShare 代理 Token | 空 |
| `LH_AKSHARE_PROXY_ENABLED` | 是否启用 AKShare 代理 | False |
| `LH_MX_APIKEY` | 妙想 MX API Key | 空 |
| `LH_OPENAI_API_KEY` | OpenAI API Key | 空 |
| `LH_DEEPSEEK_API_KEY` | DeepSeek API Key | 空 |
| `LH_MINIMAX_API_KEY` | MiniMax API Key | 空 |
| `LH_TAVILY_API_KEY` | Tavily 搜索 API Key | 空 |
| `LH_GITHUB_TOKEN` | GitHub Token | 空 |
| `LH_CNINFO_ENABLED` | 是否启用巨潮资讯 | False |
| `LH_NORTH_MAX_PER_RUN` | 北向资金每轮最大尝试数 | 1500 |
| `LH_AKSHARE_MAX_CONCURRENCY` | AKShare 最大并发数 | 16 |
| `LH_DISABLE_NUMBA` | 是否禁用 Numba JIT | 0 |
| `LH_MGMT_TRY_CNINFO` | 是否尝试 cninfo 接口 | 0 |

### 8.2 数据库配置

| 数据库 | 路径 | 用途 |
|-------|------|------|
| DuckDB | `~/.lianghua/market.db` | 历史行情/每日快照/回测数据 |
| DuckDB | `~/.lianghua/kline_cache.db` | K线缓存（229MB） |
| SQLite | `~/.lianghua/valuations_cache.db` | 估值缓存（77KB） |
| SQLite | `./lianghua.db` | 用户数据/回测结果/AI对话 |

---

## 九、数据质量与兜底机制

### 9.1 多层兜底策略

**PE/PB 估值**
1. **Baidu 估值**（逐股查询，15线程，~0.85s/只，主力）
2. **THS 财务摘要**（EPS/BPS 推算，最后备选，限100只）
3. **妙想 MX**（自然语言查询，最后兜底，限50只）

**正股历史K线**
1. **Tencent K线**（`stock_zh_a_hist_tx`，90天+，主力）
2. **East Money K线**（`stock_zh_a_hist`，备选，IP可能被封）

**转债历史K线**
1. **东方财富数据中心**（`bond_zh_cov_value_analysis`，300-1500天，主力）
2. **EM datacenter Web API**（`RPTA_WEB_KZZ_MRHQ`，3.5+年，push2his被封时备用）
3. **Tushare Pro cb_daily**（需 Token，专业数据）

**行业数据**
1. **东方财富 F10**（`CompanySurveyAjax`，申万行业）
2. **同花顺个股信息**（`stock_individual_info_ths`）
3. **新浪 F10**（`corp/go.php/vCI_CorpInfo`）
4. **yfinance**（`Ticker.info.sector`，最后兜底）

### 9.2 数据可用性监控

- **缓存过期检测**：`_fresh()` 函数检查文件修改时间
- **数据完整性评分**：`data_completeness` 字段（0-1）
- **后台任务注册表**：`TaskRegistry` 管理耗时批量任务，支持轮询结果
- **刷新指标持久化**：`refresh_metrics.json` 记录各缓存最后刷新时间/成功率
- **数据源健康检查**：`/health` 端点返回各数据源连接状态

---

## 十、前端数据接口定义

### 10.1 TypeScript 类型（shared/types.ts）

```typescript
interface ConvertibleQuote {
  code: string
  name: string
  stock_code?: string
  stock_name?: string
  price: number | undefined
  change_pct: number | undefined
  stock_price: number | undefined
  stock_change_pct: number | undefined
  conversion_price: number | undefined
  conversion_value: number | undefined
  premium_ratio: number | undefined
  dual_low: number | undefined
  ytm: number | undefined
  volume: number | undefined
  remaining_years: number | undefined
  forced_call_days: number | undefined
  is_called: boolean | undefined
  call_status: string | undefined
  last_trade_date: string | undefined
  maturity_date: string | undefined
  redemption_price: number | undefined
  industry?: string
  roe?: number
  gpm?: number
  cagr?: number
  debt_ratio?: number
  current_ratio?: number
  pe?: number
  pb?: number
  iv?: number
  iv_source?: string
  hv?: number
  rating?: string
  rating_score?: number
  pure_bond_premium_ratio?: number
  bond_value?: number
  buyback_amount?: number
  mgmt_buy_price?: number
  turnover_rate?: number
  net_capital_flow?: number
  net_capital_flow_pct?: number
  net_super_flow?: number
  net_big_flow?: number
  outstanding_scale?: number
  pledge_ratio?: number
  momentum_5d?: number
  momentum_10d?: number
  momentum_20d?: number
  momentum_60d?: number
  event_score?: number
  event_detail?: string
  concepts?: string[]
  north_net?: number
  margin_balance?: number
  lhb_count?: number
  block_trade_amount?: number
  holder_num_change?: number
  eps_forecast?: number
  eps?: number
  bps?: number
  revenue_yoy?: number
  profit_yoy?: number
  restricted_release_amount?: number
  sentiment_score?: number
  macro_cpi?: number
  macro_ppi?: number
  macro_m2?: number
  macro_lpr?: number
  macro_policy_score?: number
  macro_event_score?: number
  timestamp: string
}
```

### 10.2 WebSocket 消息格式

```typescript
interface WsMessage {
  type: 'tick' | 'subscribe' | 'unsubscribe'
  data?: ConvertibleQuote[]
  codes?: string[]
}
```

**增量更新机制**：
- 首次连接发送全量 `tick` 数据（所有转债完整字段）
- 后续发送增量 `tick`（仅变化字段 + code）
- 消息超过 1KB 时使用 gzip 压缩
- 最大连接数限制：50 个并发

---

## 十一、潜在优化建议与风险

### 11.1 数据质量风险

1. **AKShare IP 封禁**：东方财富接口（`stock_zh_a_spot`, `stock_zh_a_hist`）在频繁调用时可能触发 IP 临时封禁，需确保代理配置或降级到备用源。
2. **Baidu 估值接口限速**：`stock_zh_valuation_baidu` 约 0.4s/次，250只×2次≈3.3min（15线程），但实际可能因网络波动超时。
3. **THS 财务数据滞后**：年报数据滞后6-12个月，仅作最后备选，可能导致 PE/PB 计算偏差。
4. **宏观数据天然滞后**：PMI/CPI/PPI/GDP 等月度/季度数据发布滞后1-2个月，无法反映最新市场变化。
5. **北向资金接口不稳定**：部分环境下已失效，返回中性值，需监控实际覆盖情况。

### 11.2 性能优化建议

1. **回测数据充足性检查**：`_is_data_sufficient` 应捕获双峰分布（大量债券仅1天数据拉低平均值），需检查 `well_covered_bonds >= 30`。
2. **后台任务超时保护**：长耗时批量接口（`value-analysis`, `bond-daily-em`, `industry`）已支持 `async_task` 模式，但前端轮询间隔可优化为指数退避。
3. **DuckDB 并发写入**：market.db 在高频回测时可能出现并发锁定，建议回测时复制到 `/tmp/` 绕过。
4. **WebSocket 增量压缩**：当前阈值 1KB，对于 500+ 只转债的全量推送仍较大，可考虑按关注度分片推送。
5. **Numba 缓存管理**：`numba_cache` 可能膨胀到数 GB，已有 1GB 阈值清理，但 Electron 环境下目录权限问题仍需关注。

### 11.3 架构改进建议

1. **数据湖标准化**：当前缓存分散在 JSON 文件、DuckDB、SQLite 中，建议统一数据湖接口（`data_lake.py` 已有初步实现）。
2. **特征存储（Feature Store）**：`feature_store.py` 已存在但未充分使用，建议将 `data_enrich` 的各字段统一注册为特征，支持版本管理和回溯。
3. **实时流处理**：当前为拉模式（定时刷新），可考虑接入 Flink 或 Kafka 实现推模式实时行情。
4. **数据血缘追踪**：`data_lineage.py` 已存在，建议将各字段的数据来源、转换逻辑、刷新时间统一记录，便于排查数据质量问题。
5. **离线模式完善**：前端已有 IndexedDB 缓存和离线模式检测，但后端缺乏离线数据包预加载机制。
