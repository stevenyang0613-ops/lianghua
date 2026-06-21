"""璇玑v7.0 回测 — 3年完整版 + 训练/验证分拆
回测区间: 2022-01-01 ~ 2025-06-14 (3.5年)
训练期: 2022-2023 (ICIR权重学习)
验证期: 2024-2025 (样本外验证)
"""
import sys,os,gc,time,logging,random,sqlite3
sys.path.insert(0,"."); os.chdir("/Users/mac/lianghua/backend")
import tqdm as _tq
_orig_tq=_tq.tqdm; _tq.tqdm=lambda *a,**kw:_orig_tq(*a,**{'disable':True,**kw})
logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
logger=logging.getLogger("xuanji_3yr")
import pandas as pd,numpy as np
import akshare as ak
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date
from app.strategies.xuanji_twelve_factor import XuanjiTwelveFactorStrategy
from app.engine.backtest import BacktestEngine, BacktestConfig
from app.api.kline_cache import batch_fetch_stock_kline
from app.api.industry import get_industry as get_industry_v2
from app.api.valuation_cache import get_cached_valuations
from app.api.data_enrich import fetch_ths_financial_single

TRAIN_START,TRAIN_END = date(2022,1,1), date(2023,12,31)
TEST_START,TEST_END = date(2024,1,2), date(2025,6,14)
CB_DB = "data/cb_hist_cache.db"

def load_cb(bc):
    conn=sqlite3.connect(CB_DB)
    ph=",".join("?" for _ in bc)
    df=pd.read_sql_query(f"SELECT bond_code,trade_date,close,volume FROM cb_daily "
        f"WHERE bond_code IN ({ph}) AND close>0 AND close<1000 "
        f"ORDER BY bond_code,trade_date", conn, params=list(bc))
    conn.close(); return df

def ytm_est(bp,ry,cpn=0.01):
    if bp<=0 or ry<=0: return 0.0
    tr=cpn*100*ry+100-bp; return round(max(-5,min(20,tr/bp/ry*100)),2)

def calc_hv(ps):
    if len(ps)<5: return 25.0
    a=np.array(ps[-20:],dtype=float); r=a[1:]/a[:-1]-1; r=r[~np.isnan(r)]
    return float(min(80,max(10,np.std(r)*np.sqrt(250)*100))) if len(r)>=3 else 25.0

def build_dataset(start,end,bonds,cb_all,jisilu,sprices,valuations,enrich):
    """构建指定时间段的数据集"""
    cb_idx={}
    for code in bonds:
        s=cb_all[cb_all["bond_code"]==code].sort_values("trade_date").set_index("trade_date")
        if not s.empty: cb_idx[code]=s
    dr=list(pd.bdate_range(start,end))
    buf=[]
    for i,(bc,info) in enumerate(bonds.items()):
        if (i+1)%200==0: logger.info(f"  构建: {i+1}/{len(bonds)}")
        sc=info["stock_code"]; cp=info["conversion_price"]
        ji=jisilu.get(bc,{}); rating=ji.get("rating","未评级"); ry=ji.get("remaining_years",3.0); yt=ji.get("ytm",None)
        val=valuations.get(sc,{}); pe=val.get("pe"); pb=val.get("pb")
        en=enrich.get(sc,{}); roe=en.get("roe"); gpm=en.get("gpm")
        drr=en.get("debt_ratio"); cagr=en.get("cagr"); ind=en.get("industry") or get_industry_v2(sc)
        cd=cb_idx.get(bc); spd=sprices.get(sc,{})
        if cd is None: continue
        for j,d in enumerate(dr):
            ds=d.date().isoformat()
            if ds not in cd.index: continue
            bp=float(cd.loc[ds,"close"])
            spx=spd.get(d.date(), np.nan)
            if np.isnan(spx):
                pv=[dd for x in range(j-1,-1,-1) if dr[x].date() in spd]
                spx=spd[pv[0]] if pv else np.nan
            if np.isnan(spx): continue
            cv=round(100.0/cp*spx,2) if cp>0 and spx>0 else 80.0
            dp=round((bp/cv-1)*100,2) if cv>0 and bp>0 else 25.0
            hp=cd.loc[:ds,"close"].tolist(); hv=calc_hv(hp); iv=hv*1.2+3.0
            chg=0
            if j>0:
                pd_=dr[j-1].date().isoformat()
                if pd_ in cd.index:
                    pb_=float(cd.loc[pd_,"close"]); chg=round((bp/pb_-1)*100,2) if pb_>0 else 0
            ry_=max(0,ry-j/250)
            yt_=yt if yt and yt>0 else ytm_est(bp,max(0.1,ry_),0.015 if "AAA" in rating else (0.01 if "AA" in rating else 0.005))
            vol=float(cd.loc[ds,"volume"])
            es=0.70 if rating in ("AAA","AA+") else (0.55 if rating in ("AA","AA-") else 0.50)
            if ry_<1: es+=0.10
            elif ry_>4: es-=0.10
            buf.append({"code":bc,"name":info["name"],"stock_code":sc,"date":d.date(),
                "price":round(bp,2),"premium_ratio":round(dp,2),"change_pct":chg,"volume":vol,
                "ytm":round(yt_,2),"remaining_years":round(ry_,2),"conversion_value":round(cv,2),
                "stock_price":round(spx,2),"industry":ind,"rating":rating,
                "pe":pe,"pb":pb,"roe":roe,"gpm":gpm,"cagr":cagr,"debt_ratio":drr,
                "iv":round(iv,1),"hv":round(hv,1),
                "buyback_amount":0,"mgmt_buy_price":0,"event_score":round(min(1,max(0,es)),2)})
    df=pd.DataFrame(buf)
    gc.collect()

    # 修复 (2025-06-15): 数据缺失时用行业均值填充，避免固定默认值削弱因子有效性
    # 先计算每个行业的均值（排除缺失值）
    for col in ["pe","pb","roe","gpm","cagr","debt_ratio"]:
        if col not in df.columns:
            continue
        # 按行业分组计算均值
        industry_means = df.groupby("industry")[col].transform(lambda x: x.mean() if not x.isna().all() else np.nan)
        # 用行业均值填充缺失值
        df[col] = df[col].fillna(industry_means)
        # 剩余仍缺失的（该行业全缺失），用全局中位数填充
        global_median = df[col].median()
        df[col] = df[col].fillna(global_median)

    # 记录数据质量
    for col in ["pe","pb","roe","gpm","cagr","debt_ratio"]:
        if col in df.columns:
            coverage = df[col].notna().sum() / len(df) * 100
            logger.info(f"  数据质量 {col}: {coverage:.1f}% 覆盖")

    return df

t0=time.time()

# [1] THS
print("[1] THS...")
df=ak.bond_zh_cov_info_ths()
bonds={}
for _,r in df.iterrows():
    c=str(r.get("债券代码","")).strip()
    if c and len(c)==6:
        bonds[c]={"name":str(r.get("债券简称","")).strip(),"stock_code":str(r.get("正股代码","")).strip(),"conversion_price":float(r.get("转股价格",0) or 0)}
ustocks=list(set(v["stock_code"] for v in bonds.values() if v["stock_code"] and len(v["stock_code"])==6))
print(f"  {len(bonds)}只"); del df; gc.collect()

# [2] CB历史  
print("[2] CB历史K线...")
cb_all=load_cb(list(bonds.keys()))
print(f"  {cb_all['bond_code'].nunique()}只, {len(cb_all)}行")

# [3] Jisilu
print("[3] Jisilu...")
df=ak.bond_cb_jsl()
jisilu={}
for _,r in df.iterrows():
    c=str(r.get("代码","")).strip()
    if not c or len(c)!=6: continue
    jisilu[c]={"ytm":float(r.get("到期税前收益",0) or 0),"rating":str(r.get("债券评级","")).strip(),
               "remaining_years":float(r.get("剩余年限",3) or 3),"stock_pb":float(r.get("正股PB",np.nan) or np.nan)}
print(f"  {len(jisilu)}只"); del df; gc.collect()

# [4] 正股K线(覆盖全范围)
print("[4] 正股K线...")
kdf=batch_fetch_stock_kline(ustocks, TRAIN_START, TEST_END, max_workers=6)
sprices={}
for sc in ustocks:
    if sc in kdf and not kdf[sc].empty:
        sub=kdf[sc].copy()
        for dc in ['trade_date','date']:
            if dc in sub.columns:
                sub[dc]=pd.to_datetime(sub[dc]); sub['__d__']=sub[dc].dt.date
                sub=sub.set_index('__d__'); sprices[sc]=sub['close'].to_dict(); break
print(f"  {len(sprices)}只")

# [5] PE/PB
print("[5] PE/PB...")
valuations={}
try:
    vc=get_cached_valuations(ustocks)
    if vc: valuations={k:v for k,v in vc.items() if v.get("pe") or v.get("pb")}
except: pass
for bc,ji in jisilu.items():
    info=bonds.get(bc,{}); sc=info.get("stock_code","")
    if sc and ji.get("stock_pb"):
        if sc not in valuations: valuations[sc]={"pb":ji["stock_pb"]}
        elif not valuations[sc].get("pb"): valuations[sc]["pb"]=ji["stock_pb"]
print(f"  PE={sum(1 for v in valuations.values() if v.get('pe'))}, PB={sum(1 for v in valuations.values() if v.get('pb'))}")

# [6] THS财务
print("[6] THS财务...")
scodes=sorted(ustocks); enrich={}
for bs in range(0,len(scodes),15):
    batch=scodes[bs:bs+15]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs={ex.submit(fetch_ths_financial_single,c):c for c in batch}
        for f in as_completed(futs):
            c=futs[f]
            try: d=f.result(timeout=15)
            except: d=None
            if d: enrich[c]=d
    gc.collect(); time.sleep(0.3)
for c in scodes:
    if c not in enrich: enrich[c]={}
    enrich[c]["industry"]=get_industry_v2(c)
print(f"  ROE={sum(1 for v in enrich.values() if v.get('roe'))}, GPM={sum(1 for v in enrich.values() if v.get('gpm'))}")
gc.collect()

# [7] 构建3年数据集 → 再按时间拆分
print("[7] 构建全量数据...")
data_all=build_dataset(TRAIN_START,TEST_END,bonds,cb_all,jisilu,sprices,valuations,enrich)
print(f"  全量: {len(data_all)}行, {data_all['code'].nunique()}只, {data_all['date'].nunique()}天")

# 按时间拆分
data_train=data_all[(data_all['date']>=TRAIN_START)&(data_all['date']<=TRAIN_END)]
data_test=data_all[(data_all['date']>=TEST_START)&(data_all['date']<=TEST_END)]
print(f"  训练: {len(data_train)}行, {data_train['date'].nunique()}天")
print(f"  验证: {len(data_test)}行, {data_test['date'].nunique()}天")

# 数据质量
print(f"\n{'='*60}")
print("📊 数据质量 (3年)")
print(f"{'='*60}")
for c in ["price","premium_ratio","pe","pb","stock_price","roe","gpm","ytm","volume","industry"]:
    if c in data_test.columns:
        print(f"  {c:15s}: {data_test[c].notna().sum()/len(data_test)*100:5.1f}%")

# [8] 回测
print(f"\n{'='*60}")
print("🚀 回测 (3年)")
print(f"{'='*60}")

cfgs=[
    ("TRN_2022-23_全期训练",data_train,data_test,"训练期权重->验证期"),
]
# Also run full-period
cfgs.append(("FULL_2022-25_全期",data_all,data_all,"全周期"))

for cname,train_data,test_data,desc in cfgs:
    print(f"\n--- {cname}: {desc} ---")
    
    # 策略1: 训练期回测(ICIR学习) 
    if train_data is not test_data:
        engine1=BacktestEngine(config=BacktestConfig(
            initial_capital=1000000, max_positions=15,
            commission=0.001, slippage=0.001, min_commission=5.0))
        strat1=XuanjiTwelveFactorStrategy(
            hold_count=15, rebalance_days=15, stop_loss_pct=-5.0,
            portfolio_stop_loss=-15.0, max_premium=50, min_price=90,
            max_price=150, delta_hedge_pct=10, vol_adjust=0.80, icir_lookback=120)
        t1=time.time()
        r1=engine1.run(strat1, train_data)
        m1=r1.metrics
        print(f"  训练期收益:{m1.total_return_pct:+.2f}% Sharpe:{m1.sharpe_ratio:.2f} 交易:{len(r1.trades)}笔 ({time.time()-t1:.0f}s)")
    
    # 策略2: 验证期回测
    engine2=BacktestEngine(config=BacktestConfig(
        initial_capital=1000000, max_positions=15,
        commission=0.001, slippage=0.001, min_commission=5.0))
    strat2=XuanjiTwelveFactorStrategy(
        hold_count=15, rebalance_days=15, stop_loss_pct=-5.0,
        portfolio_stop_loss=-15.0, max_premium=50, min_price=90,
        max_price=150, delta_hedge_pct=10, vol_adjust=0.80, icir_lookback=120)
    t2=time.time()
    r2=engine2.run(strat2, test_data)
    m2=r2.metrics
    wins=[t.profit_pct for t in r2.trades if t.profit_pct and t.profit_pct>0]
    losses=[t.profit_pct for t in r2.trades if t.profit_pct and t.profit_pct<=0]
    hd=[t.hold_days for t in r2.trades]
    print(f"  {'测试' if train_data is not test_data else '全期'}收益:{m2.total_return_pct:+.2f}% 年化:{m2.annual_return_pct:+.2f}%")
    print(f"  夏普:{m2.sharpe_ratio:.2f} 回撤:{m2.max_drawdown_pct:.2f}% 胜率:{m2.win_rate:.1f}%")
    print(f"  交易:{len(r2.trades)}笔 持仓:{np.mean(hd):.1f}天", end="")
    if wins: print(f" 均盈:+{np.mean(wins):.2f}%", end="")
    if losses: print(f" 均亏:{np.mean(losses):.2f}%", end="")
    print(f" ({time.time()-t2:.0f}s)")

elapsed=time.time()-t0
print(f"\n总耗时: {elapsed:.0f}s")
print("OK")
