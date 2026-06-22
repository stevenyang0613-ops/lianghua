/**
 * 行业轮动 — 璇玑十二风格全面重写
 *
 * 8大Tab完整展示:
 *   1. 行业分布 — 申万行业分类，柱状图+饼图+详情表
 *   2. 概念板块 — 东方财富+同花顺概念，双源对比
 *   3. 资金动量 — 热力图+资金流向+动量排名
 *   4. 估值对比 — ROE/PE/PB/IV 多维估值
 *   5. 质量分析 — 负债率/毛利率/CAGR/回购/质押
 *   6. 波动风险 — IV/换手率/动量分散度
 *   7. 事件驱动 — 事件评分+强赎/下修/回售
 *   8. 行业回测 — ETF轮动回测引擎
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Alert, Descriptions, Tooltip,
  Tabs, Radio, Divider, InputNumber, Badge, Modal, theme as antTheme,
  Skeleton, Switch, Segmented,
} from 'antd'
import {
  SwapOutlined, ThunderboltOutlined,
  LineChartOutlined, RiseOutlined, FallOutlined,
  TrophyOutlined, PlayCircleOutlined,
  DatabaseOutlined, ApiOutlined, WarningOutlined,
  CloudServerOutlined, GlobalOutlined, SyncOutlined, CheckCircleOutlined,
  FundOutlined, PieChartOutlined, BarChartOutlined,
  StockOutlined, DollarOutlined, GoldOutlined,
  TeamOutlined, SafetyCertificateOutlined, PercentageOutlined,
  ReloadOutlined, InfoCircleOutlined, ExperimentOutlined,
  EyeOutlined, StarOutlined, DashboardOutlined,
  ExportOutlined, DownloadOutlined, FilterOutlined,
  ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
  HeatMapOutlined, CalendarOutlined, ControlOutlined,
  ClusterOutlined, NodeIndexOutlined, AppstoreOutlined,
  SafetyOutlined, AlertOutlined, FireOutlined,
  BankOutlined, RocketOutlined, SettingOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import echarts from '../utils/echarts'
import {
  fetchStrategies, runBacktest,
  type StrategyInfo, type BacktestResult, type BacktestMetrics,
  fetchIndustries, type IndustryAgg, type IndustriesResponse,
  fetchConcepts, type ConceptAgg, type ConceptsResponse,
  fetchDataSources, type DataSourceInfo, type DataSourcesResponse,
  fetchNorthCapital, type NorthResponse, type NorthStock,
  fetchMarginStocks, type MarginResponse, type MarginStock,
  fetchLhb, type LhbResponse, type LhbStock,
  fetchBlockTrade, type BlockTradeResponse, type BlockTradeStock,
  fetchHolderNum, type HolderNumResponse, type HolderNumStock,
  fetchEarningsForecast, type EarningsForecastResponse, type EarningsForecastStock,
  fetchEarningsExpress, type EarningsExpressResponse, type EarningsExpressStock,
  fetchRestrictedRelease, type RestrictedReleaseResponse, type RestrictedReleaseEvent,
  SECTOR_ETF_MAP,
} from '../services/api'
import { useThemeStore } from '../stores/useThemeStore'
import dayjs from 'dayjs'

const { Title, Text } = Typography

// ═══════════════════════════════════════════════════════════════════════════════
//  常量 & 颜色
// ═══════════════════════════════════════════════════════════════════════════════

const IND_COLORS: Record<string, string> = {
  '银行':'#1677ff','非银金融':'#2f54eb','证券':'#0958d9','保险':'#4096ff',
  '房地产':'#fa8c16','建筑装饰':'#d46b08',
  '医药生物':'#eb2f96','食品饮料':'#f5222d',
  '电子':'#722ed1','计算机':'#531dab','通信':'#391063',
  '电力设备':'#52c41a','新能源':'#389e0d','公用事业':'#13c2c2',
  '汽车':'#faad14','交通运输':'#d4b106',
  '机械设备':'#a0d911','基础化工':'#5cdbd3','有色金属':'#08979c',
  '国防军工':'#f5222d','钢铁':'#595959','煤炭':'#434343','石油石化':'#614700',
  '纺织服装':'#ff85c0','家用电器':'#ff7a45','轻工制造':'#95de64',
  '传媒':'#9254de','社会服务':'#36cfc9','商贸零售':'#ffa940',
  '农林牧渔':'#73d13d','环保':'#5cdbd3','美容护理':'#ffadd2',
  '建筑材料':'#ffe58f','制造业':'#8c8c8c',
  '半导体':'#b37feb','光伏设备':'#95de64','电池':'#ffc53d',
  '汽车零部件':'#69b1ff','环境治理':'#87e8de','医疗器械':'#ff85c0',
  '软件开发':'#9254de','化学制品':'#87e8de','其他':'#8c8c8c',
}

const DATA_LAYERS = [
  { layer:1, title:'DuckDB缓存', desc:'daily_snapshots + K线，10ms', source:'Storage', color:'#52c41a' },
  { layer:2, title:'AKShare引擎', desc:'bond_zh_cov + Sina + THS', source:'AKShare', color:'#1890ff' },
  { layer:3, title:'东方财富', desc:'概念板块成分 + 行业行情', source:'EastMoney', color:'#722ed1' },
  { layer:4, title:'同花顺', desc:'概念板块 + 财务摘要', source:'THS', color:'#13c2c2' },
  { layer:5, title:'Sina实时', desc:'价格/涨跌/成交额', source:'Sina', color:'#fa8c16' },
  { layer:6, title:'集思录', desc:'溢价率/双低/评级/YTM', source:'Jisilu', color:'#eb2f96' },
  { layer:7, title:'Baidu估值', desc:'PE/PB 5线程并发', source:'Baidu', color:'#2f54eb' },
  { layer:8, title:'Tencent K线', desc:'转债日K 10线程', source:'Tencent', color:'#f5222d' },
]

const DS_NAMES: Record<string, string> = {
  'industry':'申万行业分类',
  'spot':'Sina 实时行情',
  'fin':'东方财富 财务摘要',
  'fund_flow':'腾讯/EM 资金流向',
  'debt':'东方财富 资产负债',
  'vol':'Tencent K线波动率',
  'buyback':'东方财富 回购',
  'mgmt':'管理层增持 (3源)',
  'outstanding':'集思录 剩余规模',
  'call_status':'集思录 强赎状态',
  'pledge':'东方财富 质押比例',
  'momentum':'Sina K线多周期动量',
  'event':'东方财富 事件',
  'stock_names':'股票名称',
  'concept':'概念板块(EM+THS)',
  'north':'北向资金 (EM)',
  'margin':'融资融券 (SZSE/SSE)',
  'lhb':'龙虎榜 (EM)',
  'block_trade':'大宗交易 (EM)',
  'holder_num':'股东户数 (EM)',
  'earnings_forecast':'业绩预告 (EM)',
  'earnings_express':'业绩快报 (EM)',
  'restricted_release':'限售解禁 (EM)',
}

// ═══════════════════════════════════════════════════════════════════════════════
//  Helpers
// ═══════════════════════════════════════════════════════════════════════════════

function indColor(ind: string): string { return IND_COLORS[ind] || '#8c8c8c' }
function fmt(v: number|null|undefined, d=2): string { if(v==null||!isFinite(v)) return '-'; return v.toFixed(d) }
function fmtPct(v: number|null|undefined): string { if(v==null||!isFinite(v)) return '-'; return (v>=0?'+':'')+v.toFixed(2)+'%' }
function fmtFlow(v: number|null|undefined): string {
  // 数据单位：万元
  if(v==null||!isFinite(v)) return '-'
  const a=Math.abs(v); let s:string
  if(a>=10000) s=(v/10000).toFixed(2)+'亿'  // 10000万 = 1亿
  else if(a>=1) s=v.toFixed(2)+'万'          // 万元
  else s=(v*10000).toFixed(0)+'元'            // 不足1万 = 元
  return (v>=0?'+':'')+s
}
function trendIcon(v: number|undefined|null) {
  if(v==null||!isFinite(v)) return <MinusOutlined style={{color:'#8c8c8c'}}/>
  return v>0.5?<ArrowUpOutlined style={{color:'#ff4d4f'}}/>:v<-0.5?<ArrowDownOutlined style={{color:'#52c41a'}}/>:<MinusOutlined style={{color:'#faad14'}}/>
}
function exportCSV(data: any[], filename: string) {
  if(!data?.length) return message.warning('无数据可导出')
  const keys=Object.keys(data[0])
  const csv=[keys.join(','), ...data.map(r=>keys.map(k=>{const v=r[k];if(v==null) return'';const s=String(v).replace(/"/g,'""');return /[,"\n]/.test(s)?`"${s}"`:s}).join(','))].join('\n')
  const blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'})
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();document.body.removeChild(a);setTimeout(()=>URL.revokeObjectURL(url),0)
  message.success(`已导出 ${data.length} 条记录`)
}

// ═══════════════════════════════════════════════════════════════════════════════
//  渐变统计卡片
// ═══════════════════════════════════════════════════════════════════════════════

function StatCard({ title, value, suffix, color, icon, loading }: {
  title:string; value:string|number; suffix?:string; color:string; icon?:React.ReactNode; loading?:boolean
}) {
  const { token } = antTheme.useToken()
  return (
    <Card size='small' styles={{ body:{ padding:'12px 16px', background:`linear-gradient(135deg, ${color}18, ${color}06)` } }}
      style={{ borderLeft:`3px solid ${color}`, borderRadius:8 }}>
      {loading?<Skeleton active paragraph={{rows:1}} title={{width:'60%'}}/>:(
        <>
          <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:4}}>
            {icon&&<span style={{color,fontSize:16}}>{icon}</span>}
            <Text type='secondary' style={{fontSize:12}}>{title}</Text>
          </div>
          <div style={{fontSize:20,fontWeight:700,color,letterSpacing:'-0.5px'}}>
            {value}{suffix&&<span style={{fontSize:13,fontWeight:400,color:token.colorTextSecondary}}>{suffix}</span>}
          </div>
        </>
      )}
    </Card>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
//  骨架加载
// ═══════════════════════════════════════════════════════════════════════════════

function renderSkeleton() {
  return <div style={{padding:24}}><Skeleton active paragraph={{rows:8}}/></div>
}

// ═══════════════════════════════════════════════════════════════════════════════
//  主组件
// ═══════════════════════════════════════════════════════════════════════════════

export default function SectorRotation() {
  const { token: themeToken } = antTheme.useToken()
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
  const chartText = isDark ? '#e0e0e0' : '#333'
  const chartAxis = isDark ? '#444' : '#e0e0e0'

  const [activeTab, setActiveTab] = useState('distribution')
  const [indData, setIndData] = useState<IndustriesResponse|null>(null)
  const [indLoading, setIndLoading] = useState(false)
  const [indError, setIndError] = useState<string|null>(null)
  const [conceptData, setConceptData] = useState<ConceptsResponse|null>(null)
  const [conceptLoading, setConceptLoading] = useState(false)
  const [conceptError, setConceptError] = useState<string|null>(null)
  const [strategyInfo, setStrategyInfo] = useState<StrategyInfo|null>(null)
  const [result, setResult] = useState<BacktestResult|null>(null)
  const [running, setRunning] = useState(false)
  const [btError, setBtError] = useState<string|null>(null)

  // 筛选/排序状态
  const [indSort, setIndSort] = useState<string>('bond_count')
  const [indTopK, setIndTopK] = useState(30)
  const [conceptSort, setConceptSort] = useState<string>('bond_count')
  const [conceptTopK, setConceptTopK] = useState(30)
  const [detailInd, setDetailInd] = useState<IndustryAgg|null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [showDataLayer, setShowDataLayer] = useState(false)

  // 回测参数
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([dayjs('2024-01-01'), dayjs('2026-06-01')])
  const [holdCount, setHoldCount] = useState(5)
  const [rebalanceDays, setRebalanceDays] = useState(20)
  const [momentumWindow, setMomentumWindow] = useState(60)
  const [bullFactor, setBullFactor] = useState('momentum_1m')
  const [bearFactor, setBearFactor] = useState('sharpe_63d')
  const [useEtf, setUseEtf] = useState(true)
  const [dsInfo, setDsInfo] = useState<DataSourcesResponse|null>(null)
  const [dsLoading, setDsLoading] = useState(false)
  const [dsError, setDsError] = useState<string|null>(null)
  const [northData, setNorthData] = useState<NorthResponse|null>(null)
  const [northLoading, setNorthLoading] = useState(false)
  const [marginData, setMarginData] = useState<MarginResponse|null>(null)
  const [marginLoading, setMarginLoading] = useState(false)
  const [lhbData, setLhbData] = useState<LhbResponse|null>(null)
  const [lhbLoading, setLhbLoading] = useState(false)
  const [blockData, setBlockData] = useState<BlockTradeResponse|null>(null)
  const [blockLoading, setBlockLoading] = useState(false)
  const [holderData, setHolderData] = useState<HolderNumResponse|null>(null)
  const [holderLoading, setHolderLoading] = useState(false)
  const [forecastData, setForecastData] = useState<EarningsForecastResponse|null>(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [expressData, setExpressData] = useState<EarningsExpressResponse|null>(null)
  const [expressLoading, setExpressLoading] = useState(false)
  const [releaseData, setReleaseData] = useState<RestrictedReleaseResponse|null>(null)
  const [releaseLoading, setReleaseLoading] = useState(false)
  const [dsTab, setDsTab] = useState('overview')

  // ── 数据加载 ──
  useEffect(()=>{loadStrategyInfo()},[])

  const loadStrategyInfo=async()=>{
    try{const list=await fetchStrategies();setStrategyInfo(list.find(s=>s.id==='sector_rotation')||null)}
    catch(e:any){}
  }

  useEffect(()=>{
    if(!indData&&!indLoading) loadIndustries()
    if((activeTab==='concepts'||activeTab==='distribution')&&!conceptData&&!conceptLoading) loadConcepts()
  },[activeTab])

  const loadIndustries=async()=>{
    setIndLoading(true);setIndError(null)
    try{const data=await fetchIndustries();setIndData(data)}
    catch(e:any){setIndError(e?.message||'无法加载行业数据')}
    finally{setIndLoading(false)}
  }

  const loadConcepts=async()=>{
    setConceptLoading(true);setConceptError(null)
    try{const data=await fetchConcepts();setConceptData(data)}
    catch(e:any){setConceptError(e?.message||'无法加载概念数据')}
    finally{setConceptLoading(false)}
  }

  const loadDataSources=async()=>{
    setDsLoading(true);setDsError(null)
    try{const data=await fetchDataSources();setDsInfo(data)}
    catch(e:any){setDsError(e?.message||'无法加载数据源状态')}
    finally{setDsLoading(false)}
  }

  const loadNorth=async()=>{setNorthLoading(true);try{setNorthData(await fetchNorthCapital())}catch(e:any){message.error('北向资金: '+e?.message)}finally{setNorthLoading(false)}}
  const loadMargin=async()=>{setMarginLoading(true);try{setMarginData(await fetchMarginStocks())}catch(e:any){message.error('融资融券: '+e?.message)}finally{setMarginLoading(false)}}
  const loadLhb=async()=>{setLhbLoading(true);try{setLhbData(await fetchLhb())}catch(e:any){message.error('龙虎榜: '+e?.message)}finally{setLhbLoading(false)}}
  const loadBlock=async()=>{setBlockLoading(true);try{setBlockData(await fetchBlockTrade())}catch(e:any){message.error('大宗交易: '+e?.message)}finally{setBlockLoading(false)}}
  const loadHolder=async()=>{setHolderLoading(true);try{setHolderData(await fetchHolderNum())}catch(e:any){message.error('股东户数: '+e?.message)}finally{setHolderLoading(false)}}
  const loadForecast=async()=>{setForecastLoading(true);try{setForecastData(await fetchEarningsForecast())}catch(e:any){message.error('业绩预告: '+e?.message)}finally{setForecastLoading(false)}}
  const loadExpress=async()=>{setExpressLoading(true);try{setExpressData(await fetchEarningsExpress())}catch(e:any){message.error('业绩快报: '+e?.message)}finally{setExpressLoading(false)}}
  const loadRelease=async()=>{setReleaseLoading(true);try{setReleaseData(await fetchRestrictedRelease())}catch(e:any){message.error('限售解禁: '+e?.message)}finally{setReleaseLoading(false)}}

  useEffect(()=>{
    if(activeTab==='sources'&&!dsInfo&&!dsLoading) loadDataSources()
    if(activeTab==='sources'&&dsTab==='north'&&!northData&&!northLoading) loadNorth()
    if(activeTab==='sources'&&dsTab==='margin'&&!marginData&&!marginLoading) loadMargin()
    if(activeTab==='sources'&&dsTab==='lhb'&&!lhbData&&!lhbLoading) loadLhb()
    if(activeTab==='sources'&&dsTab==='block'&&!blockData&&!blockLoading) loadBlock()
    if(activeTab==='sources'&&dsTab==='holder'&&!holderData&&!holderLoading) loadHolder()
    if(activeTab==='sources'&&dsTab==='forecast'&&!forecastData&&!forecastLoading) loadForecast()
    if(activeTab==='sources'&&dsTab==='express'&&!expressData&&!expressLoading) loadExpress()
    if(activeTab==='sources'&&dsTab==='release'&&!releaseData&&!releaseLoading) loadRelease()
  },[activeTab,dsTab])

  const doBacktest=useCallback(async()=>{
    setRunning(true);setBtError(null);setResult(null)
    try{
      const data=await runBacktest({
        strategy:'sector_rotation',
        params:{hold_count:holdCount,rebalance_days:rebalanceDays,momentum_window:momentumWindow,bull_factor:bullFactor,bear_factor:bearFactor,use_etf:useEtf?1:0},
        start_date:dateRange[0].format('YYYY-MM-DD'),end_date:dateRange[1].format('YYYY-MM-DD'),
      })
      if(data.type==='result'&&'metrics' in data.result) setResult(data.result as BacktestResult)
      else setBtError('返回结果类型不匹配')
    }catch(e:any){setBtError(e?.message||'回测执行失败')}
    finally{setRunning(false)}
  },[holdCount,rebalanceDays,momentumWindow,bullFactor,bearFactor,useEtf,dateRange])

  // ── 计算属性 ──
  const metrics=result?.metrics
  const benchmarkReturn=useMemo(()=>{
    if(!result?.benchmark_curve?.length) return null
    return result.benchmark_curve[result.benchmark_curve.length-1].value/result.benchmark_curve[0].value-1
  },[result])
  const excessReturn=useMemo(()=>metrics&&benchmarkReturn!=null?metrics.total_return_pct/100-benchmarkReturn:null,[metrics,benchmarkReturn])

  const sortedIndustries=useMemo(()=>{
    if(!indData?.industries) return[]
    const list=[...indData.industries]
    list.sort((a,b)=>((b[indSort as keyof typeof b] as number)??0)-((a[indSort as keyof typeof a] as number)??0))
    return list.slice(0,indTopK)
  },[indData,indSort,indTopK])

  const sortedConcepts=useMemo(()=>{
    if(!conceptData?.concepts) return[]
    const list=[...conceptData.concepts]
    list.sort((a,b)=>((b[conceptSort as keyof typeof b] as number)??0)-((a[conceptSort as keyof typeof a] as number)??0))
    return list.slice(0,conceptTopK)
  },[conceptData,conceptSort,conceptTopK])

  const avgChange=useMemo(()=>{
    const list=indData?.industries??[];if(!list.length) return 0
    return list.reduce((s,i)=>s+(i.avg_change_pct||0),0)/list.length
  },[indData])

  // ═════════════════════════════════════════════════════════════════════════════
  //  图表配置
  // ═════════════════════════════════════════════════════════════════════════════

  // 1. 行业分布柱状图
  const bondCountChartOption=useMemo(()=>{
    const items=sortedIndustries.slice(0,25)
    return {
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      grid:{left:90,right:20,top:8,bottom:60},
      xAxis:{type:'category',data:items.map(i=>i.industry),axisLabel:{rotate:50,fontSize:10,color:chartText}},
      yAxis:{type:'value',name:'转债数量',splitLine:{lineStyle:{color:chartAxis}}},
      series:[{type:'bar',data:items.map(i=>({value:i.bond_count,itemStyle:{color:indColor(i.industry),borderRadius:[4,4,0,0]}})),barWidth:'55%',
        label:{show:true,position:'top',fontSize:10,formatter:(p:any)=>p.value}
      }]
    }
  },[sortedIndustries,chartText,chartAxis])

  // 2. 行业饼图
  const industryPieOption=useMemo(()=>{
    const items=sortedIndustries.slice(0,12)
    const others=sortedIndustries.slice(12)
    const data=[...items.map(i=>({name:i.industry,value:i.bond_count}))]
    if(others.length) data.push({name:'其他行业',value:others.reduce((s,i)=>s+i.bond_count,0)})
    return {
      tooltip:{trigger:'item',formatter:'{b}: {c}只 ({d}%)'},
      legend:{type:'scroll',orient:'vertical',right:10,top:10,bottom:10,textStyle:{color:chartText,fontSize:11}},
      series:[{type:'pie',radius:['35%','70%'],center:['40%','55%'],data,
        label:{color:chartText,fontSize:10,formatter:'{b}\n{d}%'},
        emphasis:{itemStyle:{shadowBlur:10,shadowOffsetX:0,shadowColor:'rgba(0,0,0,0.3)'}},
        itemStyle:{borderRadius:6,borderColor:isDark?'#1f1f1f':'#fff',borderWidth:2}
      }]
    }
  },[sortedIndustries,chartText,isDark])

  // 3. 概念板块柱状图
  const conceptBarOption=useMemo(()=>{
    const items=sortedConcepts.slice(0,25)
    return {
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      grid:{left:100,right:20,top:8,bottom:60},
      xAxis:{type:'category',data:items.map(i=>i.concept),axisLabel:{rotate:50,fontSize:9,color:chartText}},
      yAxis:{type:'value',name:'转债数',splitLine:{lineStyle:{color:chartAxis}}},
      series:[{type:'bar',data:items.map((i,idx)=>({value:i.bond_count,itemStyle:{color:`hsl(${(idx*17)%360},65%,55%)`,borderRadius:[4,4,0,0]}})),barWidth:'50%',
        label:{show:true,position:'top',fontSize:9,formatter:(p:any)=>p.value}
      }]
    }
  },[sortedConcepts,chartText,chartAxis])

  // 3a. 概念板块分布柱状图 (用于行业分布Tab)
  const conceptDistChartOption=useMemo(()=>{
    const items=sortedConcepts.slice(0,15)
    return {
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      grid:{left:120,right:20,top:8,bottom:60},
      xAxis:{type:'value',splitLine:{lineStyle:{color:chartAxis}}},
      yAxis:{type:'category',data:items.map(i=>i.concept).reverse(),axisLabel:{fontSize:10,color:chartText}},
      series:[{type:'bar',data:items.map((i,idx)=>({value:i.bond_count,itemStyle:{color:`hsl(${(idx*24)%360},65%,55%)`,borderRadius:[0,4,4,0]}})),barWidth:'60%',
        label:{show:true,position:'right',fontSize:10,formatter:(p:any)=>p.value+'只'}
      }]
    }
  },[sortedConcepts,chartText,chartAxis])

  // 3b. 概念动量热度图 (用于行业分布Tab) — 4周期
  const conceptMomentumChartOption=useMemo(()=>{
    const items=sortedConcepts.slice(0,12)
    return {
      tooltip:{formatter:(p:any)=>`${p.value[1]}: ${['5日','10日','20日','60日'][p.value[0]]}动量 = ${p.value[2].toFixed(1)}%`},
      grid:{left:100,right:60,top:8,bottom:50},
      xAxis:{type:'category',data:['5日','10日','20日','60日'],axisLabel:{color:chartText}},
      yAxis:{type:'category',data:items.map(i=>i.concept).reverse(),axisLabel:{fontSize:10,color:chartText}},
      visualMap:{min:-8,max:8,calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#52c41a','#fafafa','#ff4d4f']},textStyle:{color:chartText}},
      series:[{type:'heatmap',data:items.flatMap((i,idy)=>[[0,idy,i.avg_momentum_5d??0],[1,idy,i.avg_momentum_10d??0],[2,idy,i.avg_momentum_20d??0],[3,idy,i.avg_momentum_60d??0]]),
        label:{show:true,fontSize:9,formatter:(p:any)=>(p.value[2]>0?'+':'')+p.value[2].toFixed(1)},emphasis:{itemStyle:{shadowBlur:8}}}]
    }
  },[sortedConcepts,chartText])

  // 4. 动量热力图
  const momentumHeatmapOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].sort((a,b)=>(b.avg_momentum_20d??0)-(a.avg_momentum_20d??0)).slice(0,18)
    return {
      tooltip:{formatter:(p:any)=>`${p.value[1]}: ${['5日','10日','20日','60日'][p.value[0]]}动量 = ${p.value[2].toFixed(1)}%`},
      grid:{left:90,right:60,top:8,bottom:50},
      xAxis:{type:'category',data:['5日','10日','20日','60日'],axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      visualMap:{min:-10,max:10,calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#52c41a','#fafafa','#ff4d4f']},textStyle:{color:chartText}},
      series:[{type:'heatmap',data:top.flatMap((i,idx)=>[[0,idx,i.avg_momentum_5d??0],[1,idx,i.avg_momentum_10d??0],[2,idx,i.avg_momentum_20d??0],[3,idx,i.avg_momentum_60d??0]]),
        label:{show:true,fontSize:9,formatter:(p:any)=>(p.value[2]>0?'+':'')+p.value[2].toFixed(1)},emphasis:{itemStyle:{shadowBlur:8}}}]
    }
  },[indData,chartText])

  // 5. 资金流向
  const flowChartOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].sort((a,b)=>Math.abs(b.net_capital_flow??0)-Math.abs(a.net_capital_flow??0)).slice(0,15)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>{const val=v?.value??v;const n=Array.isArray(val)?val[0]:val;return fmtFlow(typeof n==='number'?n:0)}},
      grid:{left:100,right:40,top:8,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
      series:[{type:'bar',data:top.map(i=>({value:i.net_capital_flow,itemStyle:{color:(i.net_capital_flow??0)>=0?'#ff4d4f':'#52c41a',borderRadius:4}})),barWidth:'55%'}]
    }
  },[indData,chartText])

  // 6. ROE分布图

  // 6a. GPM + 负债率组合图
  const gpmChartOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].filter(i=>i.bond_count>=2).sort((a,b)=>(b.avg_gpm??0)-(a.avg_gpm??0)).slice(0,15)
    return {
      tooltip:{trigger:'axis'},
      legend:{data:['毛利率(%)','负债率(%)'],textStyle:{color:chartText}},
      grid:{left:100,right:20,top:30,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[
        {name:'毛利率(%)',type:'bar',data:top.map(i=>i.avg_gpm??0).reverse(),itemStyle:{color:'#52c41a',borderRadius:4}},
        {name:'负债率(%)',type:'bar',data:top.map(i=>i.avg_debt_ratio??0).reverse(),itemStyle:{color:'#ff4d4f',borderRadius:4}},
      ]
    }
  },[indData,chartText])

  // 6b. 超大单/大单拆分
  const flowBreakdownOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].sort((a,b)=>Math.abs(b.net_capital_flow??0)-Math.abs(a.net_capital_flow??0)).slice(0,12)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>{const val=v?.value??v;const n=Array.isArray(val)?val[0]:val;return fmtFlow(typeof n==='number'?n:0)}},
      legend:{data:['超大单','大单'],textStyle:{color:chartText}},
      grid:{left:100,right:40,top:30,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[
        {name:'超大单',type:'bar',stack:'flow',data:top.map(i=>i.net_super_flow??0).reverse(),itemStyle:{color:'#ff4d4f'}},
        {name:'大单',type:'bar',stack:'flow',data:top.map(i=>i.net_big_flow??0).reverse(),itemStyle:{color:'#fa8c16'}},
      ]
    }
  },[indData,chartText])

  const roeChartOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].filter(i=>i.bond_count>=2).sort((a,b)=>(b.avg_roe??0)-(a.avg_roe??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'ROE(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_roe,itemStyle:{color:i.avg_roe>=12?'#52c41a':i.avg_roe>=6?'#faad14':'#ff4d4f',borderRadius:4}})),barWidth:'50%',
        markLine:{data:[{name:'市场均值',xAxis:8,lineStyle:{color:'#722ed1',type:'dashed'},label:{formatter:'8%',color:'#722ed1'}}]}
      }]
    }
  },[indData,chartText])

  // 7. 估值散点图 (PE vs PB, 大小=债券数)
  const valuationScatterOption=useMemo(()=>{
    const items=(indData?.industries??[]).filter(i=>i.avg_pe>0&&i.avg_pb>0&&i.bond_count>=2)
    return {
      tooltip:{formatter:(p:any)=>`${p.data[3]}<br/>PE: ${p.data[0].toFixed(1)}<br/>PB: ${p.data[1].toFixed(1)}<br/>转债: ${p.data[2]}只`},
      grid:{left:60,right:30,top:30,bottom:40},
      xAxis:{type:'value',name:'PE(TTM)',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
      yAxis:{type:'value',name:'PB',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
      series:[{type:'scatter',symbolSize:(d:any)=>Math.max(8,Math.min(40,d[2]*1.5)),
        data:items.map(i=>[i.avg_pe,i.avg_pb,i.bond_count,i.industry]),
        label:{show:true,formatter:(p:any)=>p.data[3],position:'right',fontSize:9,color:chartText},
        itemStyle:{color:(p:any)=>indColor(p.data[3])+'cc',borderRadius:4}
      }]
    }
  },[indData,chartText,chartAxis])

  // 8. IV/波动率图
  const ivChartOption=useMemo(()=>{
    const top=[...(indData?.industries??[])].filter(i=>i.avg_iv>0).sort((a,b)=>(b.avg_iv??0)-(a.avg_iv??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'隐含波动率(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_iv,itemStyle:{color:i.avg_iv>=40?'#ff4d4f':i.avg_iv>=25?'#faad14':'#52c41a',borderRadius:4}})),barWidth:'50%'}]
    }
  },[indData,chartText])

  // 9. 行业雷达图 (Top5行业多维度对比)
  const radarOption=useMemo(()=>{
    const top5=sortedIndustries.slice(0,5)
    if(top5.length<2) return {}
    const maxBond=Math.max(...top5.map(i=>i.bond_count))
    const maxChg=Math.max(...top5.map(i=>Math.abs(i.avg_change_pct||0)),1)
    const maxPrem=Math.max(...top5.map(i=>Math.abs(i.avg_premium_ratio||0)),1)
    const maxRoe=Math.max(...top5.map(i=>Math.abs(i.avg_roe||0)),1)
    const maxMom=Math.max(...top5.map(i=>Math.abs(i.avg_momentum_20d||0)),1)
    return {
      tooltip:{},
      legend:{data:top5.map(i=>i.industry),textStyle:{color:chartText,fontSize:11}},
      radar:{indicator:[
        {name:'转债数',max:maxBond},{name:'涨跌幅',max:maxChg},{name:'溢价率',max:maxPrem},
        {name:'ROE',max:maxRoe},{name:'20日动量',max:maxMom}
      ],axisName:{color:chartText},splitArea:{areaStyle:{color:isDark?['#1f1f1f22','#2a2a2a22']:['#ffffff22','#f5f5f522']}}},
      series:[{type:'radar',data:top5.map(i=>({name:i.industry,value:[
        i.bond_count,Math.abs(i.avg_change_pct||0),Math.abs(i.avg_premium_ratio||0),
        Math.abs(i.avg_roe||0),Math.abs(i.avg_momentum_20d||0)
      ],lineStyle:{color:indColor(i.industry)},areaStyle:{color:indColor(i.industry)+'22'},itemStyle:{color:indColor(i.industry)}}))}]
    }
  },[sortedIndustries,chartText,isDark])

  // 10. 净值走势图
  const navChartOption=useCallback(()=>{
    if(!result?.equity_curve) return {}
    const dates=result.equity_curve.map(e=>e.date)
    const values=result.equity_curve.map(e=>(e.value*100).toFixed(2))
    const bench=result.benchmark_curve?.map(e=>((e.value)*100).toFixed(2))??[]
    const series:any[]=[{name:'策略',type:'line',data:values,smooth:true,symbol:'none',lineStyle:{width:2,color:'#1890ff'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(24,144,255,0.15)'},{offset:1,color:'rgba(24,144,255,0)'}]}}}]
    if(bench.length) series.push({name:'基准',type:'line',data:bench,smooth:true,symbol:'none',lineStyle:{width:1.5,color:'#faad14',type:'dashed'}})
    return {tooltip:{trigger:'axis'},legend:{data:['策略','基准'],textStyle:{color:chartText}},grid:{left:50,right:20,top:30,bottom:30},xAxis:{type:'category',data:dates,axisLabel:{color:chartText,fontSize:10}},yAxis:{type:'value',name:'净值(%)',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},series}
  },[result,chartText,chartAxis])

  // ═════════════════════════════════════════════════════════════════════════════
  //  表格列定义
  // ═════════════════════════════════════════════════════════════════════════════

  const indColumns = [
    { title:'行业', dataIndex:'industry', fixed:'left' as const, width:100, render:(v:string)=><Tag color={indColor(v)} style={{margin:0}}>{v}</Tag> },
    { title:'转债数', dataIndex:'bond_count', width:70, sorter:(a:IndustryAgg,b:IndustryAgg)=>a.bond_count-b.bond_count, defaultSortOrder:'descend' as const },
    { title:'涨跌幅', dataIndex:'avg_change_pct', width:80, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_change_pct||0)-(b.avg_change_pct||0), render:(v:number)=><Text style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</Text> },
    { title:'正股涨跌', dataIndex:'avg_stock_change_pct', width:80, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_stock_change_pct||0)-(b.avg_stock_change_pct||0), render:(v:number)=><Text style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'溢价率', dataIndex:'avg_premium_ratio', width:75, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_premium_ratio||0)-(b.avg_premium_ratio||0), render:(v:number)=><Text style={{color:v>50?'#ff4d4f':v>30?'#faad14':'#52c41a'}}>{fmt(v)}%</Text> },
    { title:'双低', dataIndex:'avg_dual_low', width:65, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_dual_low||0)-(b.avg_dual_low||0), render:(v:number)=><Text style={{color:v<150?'#52c41a':v<170?'#faad14':'#ff4d4f',fontWeight:v<150?600:400}}>{fmt(v)}</Text> },
    { title:'YTM', dataIndex:'avg_ytm', width:65, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_ytm||0)-(b.avg_ytm||0), render:(v:number)=><Text style={{color:v>=0?'#52c41a':'#8c8c8c'}}>{fmt(v)}%</Text> },
    { title:'ROE', dataIndex:'avg_roe', width:65, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_roe||0)-(b.avg_roe||0), render:(v:number)=><Text style={{color:v>=10?'#52c41a':v>=5?'#faad14':'#ff4d4f'}}>{fmt(v)}%</Text> },
    { title:'PE', dataIndex:'avg_pe', width:60, render:(v:number)=>v?fmt(v):'-' },
    { title:'PB', dataIndex:'avg_pb', width:60, render:(v:number)=>v?fmt(v):'-' },
    { title:'5日动量', dataIndex:'avg_momentum_5d', width:80, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'20日动量', dataIndex:'avg_momentum_20d', width:80, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_momentum_20d||0)-(b.avg_momentum_20d||0), render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</Text> },
    { title:'60日动量', dataIndex:'avg_momentum_60d', width:80, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'净资金流', dataIndex:'net_capital_flow', width:95, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.net_capital_flow||0)-(b.net_capital_flow||0), render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtFlow(v)}</Text> },
    { title:'IV', dataIndex:'avg_iv', width:55, render:(v:number)=>v?fmt(v)+'%':'-' },
    { title:'涨/跌', width:70, render:(_:any,r:IndustryAgg)=><span><Text style={{color:'#ff4d4f'}}>{r.up_count}</Text>/<Text style={{color:'#52c41a'}}>{r.down_count}</Text></span> },
  ]

  const conceptColumns = [
    { title:'概念', dataIndex:'concept', fixed:'left' as const, width:120, render:(v:string)=><Tag color='#722ed1' style={{margin:0}}>{v}</Tag> },
    { title:'转债数', dataIndex:'bond_count', width:70, sorter:(a:ConceptAgg,b:ConceptAgg)=>a.bond_count-b.bond_count, defaultSortOrder:'descend' as const },
    { title:'涨跌幅', dataIndex:'avg_change_pct', width:80, render:(v:number)=><Text style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</Text> },
    { title:'正股涨跌', dataIndex:'avg_stock_change_pct', width:80, render:(v:number)=><Text style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'溢价率', dataIndex:'avg_premium_ratio', width:75, render:(v:number)=><Text style={{color:v>50?'#ff4d4f':v>30?'#faad14':'#52c41a'}}>{fmt(v)}%</Text> },
    { title:'双低', dataIndex:'avg_dual_low', width:65, render:(v:number)=><Text style={{color:v<150?'#52c41a':v<170?'#faad14':'#ff4d4f'}}>{fmt(v)}</Text> },
    { title:'YTM', dataIndex:'avg_ytm', width:60, render:(v:number)=><Text style={{color:v>=0?'#52c41a':'#8c8c8c'}}>{v?fmt(v)+'%':'-'}</Text> },
    { title:'ROE', dataIndex:'avg_roe', width:60, render:(v:number)=><Text style={{color:v>=10?'#52c41a':'#faad14'}}>{v?fmt(v)+'%':'-'}</Text> },
    { title:'20日动量', dataIndex:'avg_momentum_20d', width:80, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{v?fmtPct(v):'-'}</Text> },
    { title:'净资金流', dataIndex:'net_capital_flow', width:90, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{v?fmtFlow(v):'-'}</Text> },
    { title:'IV', dataIndex:'avg_iv', width:55, render:(v:number)=>v?fmt(v)+'%':'-' },
    { title:'涨/跌', width:70, render:(_:any,r:ConceptAgg)=><span><Text style={{color:'#ff4d4f'}}>{r.up_count}</Text>/<Text style={{color:'#52c41a'}}>{r.down_count}</Text></span> },
  ]

  const momentumColumns = [
    { title:'行业', dataIndex:'industry', fixed:'left' as const, width:100, render:(v:string)=><Tag color={indColor(v)} style={{margin:0}}>{v}</Tag> },
    { title:'转债', dataIndex:'bond_count', width:60 },
    { title:'5日', dataIndex:'avg_momentum_5d', width:75, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'10日', dataIndex:'avg_momentum_10d', width:75, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'20日', dataIndex:'avg_momentum_20d', width:75, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</Text> },
    { title:'60日', dataIndex:'avg_momentum_60d', width:75, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text> },
    { title:'分散度', dataIndex:'momentum_dispersion', width:70, render:(v:number)=><Text style={{color:v>=8?'#ff4d4f':v>=4?'#faad14':'#52c41a'}}>{fmt(v)}</Text> },
    { title:'净资金流', dataIndex:'net_capital_flow', width:95, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</Text> },
    { title:'超大单', dataIndex:'net_super_flow', width:85, render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtFlow(v)}</Text> },
    { title:'IV', dataIndex:'avg_iv', width:55, render:(v:number)=>v?fmt(v)+'%':'-' },
  ]

  const valColumns = [
    { title:'行业', dataIndex:'industry', fixed:'left' as const, width:100, render:(v:string)=><Tag color={indColor(v)} style={{margin:0}}>{v}</Tag> },
    { title:'转债', dataIndex:'bond_count', width:60 },
    { title:'ROE', dataIndex:'avg_roe', width:70, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_roe||0)-(b.avg_roe||0), render:(v:number)=><Text style={{color:v>=10?'#52c41a':v>=5?'#faad14':'#ff4d4f',fontWeight:600}}>{fmt(v)}%</Text> },
    { title:'PE', dataIndex:'avg_pe', width:65, sorter:(a:IndustryAgg,b:IndustryAgg)=>(a.avg_pe||0)-(b.avg_pe||0), render:(v:number)=><Text style={{color:v>40?'#ff4d4f':v>20?'#faad14':'#52c41a'}}>{v?fmt(v):'-'}</Text> },
    { title:'PB', dataIndex:'avg_pb', width:60, render:(v:number)=><Text>{v?fmt(v):'-'}</Text> },
    { title:'毛利率', dataIndex:'avg_gpm', width:70, render:(v:number)=><Text style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</Text> },
    { title:'负债率', dataIndex:'avg_debt_ratio', width:70, render:(v:number)=><Text style={{color:v>=60?'#ff4d4f':v>=40?'#faad14':'#52c41a'}}>{fmt(v)}%</Text> },
    { title:'CAGR', dataIndex:'avg_cagr', width:65, render:(v:number)=><Text style={{color:v>=10?'#52c41a':v>=0?'#faad14':'#ff4d4f'}}>{fmt(v)}%</Text> },
    { title:'换手率', dataIndex:'avg_turnover_rate', width:70, render:(v:number)=><Text>{fmt(v)}%</Text> },
    { title:'质押率', dataIndex:'avg_pledge_ratio', width:70, render:(v:number)=><Text style={{color:v>=30?'#ff4d4f':v>=15?'#faad14':'#52c41a'}}>{fmt(v)}%</Text> },
    { title:'IV', dataIndex:'avg_iv', width:55, render:(v:number)=><Text style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a'}}>{v?fmt(v)+'%':'-'}</Text> },
    { title:'溢价率', dataIndex:'avg_premium_ratio', width:75, render:(v:number)=><Text style={{color:v>50?'#ff4d4f':v>30?'#faad14':'#52c41a'}}>{fmt(v)}%</Text> },
    { title:'双低', dataIndex:'avg_dual_low', width:60, render:(v:number)=><Text style={{color:v<150?'#52c41a':v<170?'#faad14':'#ff4d4f'}}>{fmt(v)}</Text> },
    { title:'YTM', dataIndex:'avg_ytm', width:60, render:(v:number)=><Text style={{color:v>=0?'#52c41a':'#8c8c8c'}}>{fmt(v)}%</Text> },
  ]

  const tradeColumns = [
    {title:'日期',dataIndex:'date',width:100},
    {title:'操作',dataIndex:'action',width:60,render:(v:string)=><Tag color={v==='buy'?'#ff4d4f':'#52c41a'}>{v==='buy'?'买入':'卖出'}</Tag>},
    {title:'行业',dataIndex:'sector',width:100},
    {title:'ETF代码',dataIndex:'etf_code',width:80},
    {title:'价格',dataIndex:'price',width:70,render:(v:number)=>v?.toFixed(3)},
    {title:'收益',dataIndex:'return_pct',width:70,render:(v:number)=><Text style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v?.toFixed(2)}%</Text>},
  ]

  // ── 详情模态框 ──
  const renderDetailModal = () => (
    <Modal open={detailOpen} onCancel={()=>setDetailOpen(false)} title={detailInd?<span><Tag color={indColor(detailInd.industry)}>{detailInd.industry}</Tag> 行业详情</span>:'详情'}
      width={720} footer={null}>
      {detailInd&&<div>
        <Row gutter={[12,12]} style={{marginBottom:16}}>
          <Col span={6}><Statistic title='转债数量' value={detailInd.bond_count} suffix='只' valueStyle={{color:'#1890ff',fontWeight:700}}/></Col>
          <Col span={6}><Statistic title='平均涨跌幅' value={fmt(detailInd.avg_change_pct)} suffix='%' valueStyle={{color:detailInd.avg_change_pct>=0?'#ff4d4f':'#52c41a',fontWeight:700}} prefix={detailInd.avg_change_pct>=0?<RiseOutlined/>:<FallOutlined/>}/></Col>
          <Col span={6}><Statistic title='平均溢价率' value={fmt(detailInd.avg_premium_ratio)} suffix='%' valueStyle={{color:detailInd.avg_premium_ratio>50?'#ff4d4f':'#faad14',fontWeight:600}}/></Col>
          <Col span={6}><Statistic title='平均ROE' value={fmt(detailInd.avg_roe)} suffix='%' valueStyle={{color:detailInd.avg_roe>=10?'#52c41a':'#faad14',fontWeight:600}}/></Col>
        </Row>
        <Row gutter={[12,12]} style={{marginBottom:16}}>
          <Col span={6}><Statistic title='平均双低' value={fmt(detailInd.avg_dual_low)} valueStyle={{fontWeight:600}}/></Col>
          <Col span={6}><Statistic title='平均YTM' value={fmt(detailInd.avg_ytm)} suffix='%' valueStyle={{fontWeight:600}}/></Col>
          <Col span={6}><Statistic title='平均PE' value={detailInd.avg_pe?fmt(detailInd.avg_pe):'-'} valueStyle={{fontWeight:600}}/></Col>
          <Col span={6}><Statistic title='平均PB' value={detailInd.avg_pb?fmt(detailInd.avg_pb):'-'} valueStyle={{fontWeight:600}}/></Col>
        </Row>
        <Row gutter={[12,12]} style={{marginBottom:16}}>
          <Col span={8}><Statistic title='5日动量' value={fmtPct(detailInd.avg_momentum_5d)} valueStyle={{color:(detailInd.avg_momentum_5d||0)>=0?'#ff4d4f':'#52c41a'}} prefix={trendIcon(detailInd.avg_momentum_5d)}/></Col>
          <Col span={8}><Statistic title='20日动量' value={fmtPct(detailInd.avg_momentum_20d)} valueStyle={{color:(detailInd.avg_momentum_20d||0)>=0?'#ff4d4f':'#52c41a'}} prefix={trendIcon(detailInd.avg_momentum_20d)}/></Col>
          <Col span={8}><Statistic title='60日动量' value={fmtPct(detailInd.avg_momentum_60d)} valueStyle={{color:(detailInd.avg_momentum_60d||0)>=0?'#ff4d4f':'#52c41a'}} prefix={trendIcon(detailInd.avg_momentum_60d)}/></Col>
        </Row>
        <Row gutter={[12,12]}>
          <Col span={8}><Statistic title='净资金流' value={fmtFlow(detailInd.net_capital_flow)} valueStyle={{color:(detailInd.net_capital_flow||0)>=0?'#ff4d4f':'#52c41a',fontWeight:700}}/></Col>
          <Col span={8}><Statistic title='隐含波动率' value={detailInd.avg_iv?fmt(detailInd.avg_iv)+'%':'-'} valueStyle={{fontWeight:600}}/></Col>
          <Col span={8}><Statistic title='涨/跌' value={`${detailInd.up_count} / ${detailInd.down_count}`} valueStyle={{fontWeight:600}}/></Col>
        </Row>
      </div>}
    </Modal>
  )

  // ── 数据源展示 ──
  const renderDataSources = () => (
    <Card size='small' title={<span><DatabaseOutlined/> 数据源架构 (8层)</span>}
      styles={{body:{padding:'8px 16px'}}} style={{marginBottom:12,borderRadius:8}}>
      <Row gutter={[8,8]}>
        {DATA_LAYERS.map(l=>(
          <Col span={6} key={l.layer}>
            <div style={{display:'flex',alignItems:'center',gap:8,padding:'6px 8px',borderRadius:6,background:`${l.color}10`,borderLeft:`3px solid ${l.color}`}}>
              <Badge color={l.color} style={{marginTop:4}}/>
              <div><Text strong style={{fontSize:12,color:l.color}}>{l.title}</Text><br/><Text type='secondary' style={{fontSize:10}}>{l.desc}</Text></div>
            </div>
          </Col>
        ))}
      </Row>
    </Card>
  )

  // ── 错误/空状态 ──
  const renderEmpty = (msg:string, onRetry:()=>void) => (
    <Empty description={msg} style={{padding:80}}><Button type='primary' onClick={onRetry}>加载数据</Button></Empty>
  )

  // ═════════════════════════════════════════════════════════════════════════════
  //  Render
  // ═════════════════════════════════════════════════════════════════════════════

  return (
    <div style={{height:'100%',display:'flex',flexDirection:'column',padding:'0 16px 16px'}}>
      {/* ── 顶部概览 ── */}
      <Card size='small' style={{marginBottom:12,borderRadius:10,
        background:isDark?'linear-gradient(135deg,#1a1a2e,#16213e)':'linear-gradient(135deg,#e8f4f8,#f0f5ff)'}}
        styles={{body:{padding:'12px 20px',display:'flex',alignItems:'center',justifyContent:'space-between'}}}>
        <div>
          <Title level={4} style={{margin:0,background:isDark?'linear-gradient(90deg,#4096ff,#95de64)':'linear-gradient(90deg,#1677ff,#52c41a)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent'}}>
            🔄 行业轮动
          </Title>
          <Text type='secondary' style={{fontSize:12}}>申万行业 + 东方财富/同花顺概念板块 · 多维数据驱动</Text>
        </div>
        <Space>
          <Button size='small' icon={<ReloadOutlined/>} onClick={()=>{loadIndustries();loadConcepts()}}>刷新</Button>
          <Button size='small' icon={<DatabaseOutlined/>} onClick={()=>setShowDataLayer(!showDataLayer)}>{showDataLayer?'隐藏':'查看'}数据源</Button>
        </Space>
      </Card>

      {showDataLayer && renderDataSources()}

      <Tabs activeKey={activeTab} onChange={setActiveTab}
        style={{flex:1,display:'flex',flexDirection:'column'}}
        tabBarStyle={{marginBottom:0,padding:'0 8px'}}
        items={[

          // ════════════════════════════════════════════════════════
          //  TAB 1 — 行业分布
          // ════════════════════════════════════════════════════════
          {key:'distribution', label:<span><AppstoreOutlined/> 行业分布</span>, children: indLoading?renderSkeleton():indError?<Alert type='error' message={indError} description={<Button onClick={loadIndustries}>重试</Button>}/>:!indData?renderEmpty('暂无行业数据',loadIndustries):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={4}><StatCard title='行业数量' value={indData.total_industries} suffix='个' color='#1890ff' icon={<AppstoreOutlined/>}/></Col>
                <Col span={4}><StatCard title='转债总数' value={indData.total_bonds} suffix='只' color='#52c41a' icon={<TeamOutlined/>}/></Col>
                <Col span={4}><StatCard title='最大行业' value={sortedIndustries[0]?.industry||'-'} color={indColor(sortedIndustries[0]?.industry||'')} icon={<StarOutlined/>}/></Col>
                <Col span={4}><StatCard title='最大行业债券数' value={sortedIndustries[0]?.bond_count||0} suffix='只' color='#722ed1'/></Col>
                <Col span={4}><StatCard title='平均涨跌幅' value={fmt(avgChange)} suffix='%' color={avgChange>=0?'#ff4d4f':'#52c41a'} icon={trendIcon(avgChange)}/></Col>
                <Col span={4}><StatCard title='行业覆盖率' value={Math.round((indData.total_industries/85)*100)} suffix='%' color='#13c2c2' icon={<CheckCircleOutlined/>}/></Col>
              </Row>
              <Row gutter={[12,12]} style={{flex:1}}>
                <Col xs={24} lg={5}>
                  <Card size='small' title={<span><FilterOutlined/> 筛选</span>} styles={{body:{padding:'8px 12px'}}}>
                    <div style={{marginBottom:10}}><Text type='secondary' style={{fontSize:11}}>排序方式</Text>
                      <Select value={indSort} onChange={setIndSort} size='small' style={{width:'100%',marginTop:2}}>
                        <Select.Option value='bond_count'>📊 债券数量</Select.Option>
                        <Select.Option value='avg_change_pct'>📈 涨跌幅</Select.Option>
                        <Select.Option value='avg_premium_ratio'>💹 溢价率</Select.Option>
                        <Select.Option value='avg_dual_low'>🎯 双低值</Select.Option>
                        <Select.Option value='avg_momentum_20d'>🚀 20日动量</Select.Option>
                        <Select.Option value='avg_roe'>💰 ROE</Select.Option>
                        <Select.Option value='net_capital_flow'>💵 资金净流入</Select.Option>
                      </Select></div>
                    <div><Text type='secondary' style={{fontSize:11}}>显示数量</Text>
                      <Select value={indTopK} onChange={setIndTopK} size='small' style={{width:'100%',marginTop:2}}>
                        {[10,20,30,50,100].map(n=><Select.Option key={n} value={n}>Top {n}</Select.Option>)}
                      </Select></div>
                  </Card>
                  <Card size='small' title={<span><DashboardOutlined/> 雷达对比 Top5</span>} styles={{body:{padding:8}}} style={{marginTop:8}}>
                    {Object.keys(radarOption).length>0?
                      <ReactEChartsCore echarts={echarts} option={radarOption} style={{height:260}} notMerge/>:
                      <Empty description='数据不足' image={Empty.PRESENTED_IMAGE_SIMPLE}/>}
                  </Card>
                </Col>
                <Col xs={24} lg={19}>
                  <Row gutter={[12,12]}>
                    <Col span={14}>
                      <Card size='small' title={<span><BarChartOutlined/> 行业转债分布 (Top 25)</span>} styles={{body:{padding:8}}}>
                        <ReactEChartsCore echarts={echarts} option={bondCountChartOption} style={{height:320}} notMerge/>
                      </Card>
                    </Col>
                    <Col span={10}>
                      <Card size='small' title={<span><PieChartOutlined/> 行业占比</span>} styles={{body:{padding:8}}}>
                        <ReactEChartsCore echarts={echarts} option={industryPieOption} style={{height:320}} notMerge/>
                      </Card>
                    </Col>
                  </Row>
                  <Card size='small' title={<span><ClusterOutlined/> 各行业详细数据</span>} extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(sortedIndustries,'industries-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>} styles={{body:{padding:0}}}>
                    <Table dataSource={sortedIndustries.map((i,idx)=>({...i,key:idx}))} columns={indColumns} size='small'
                      pagination={{pageSize:15,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:1200,y:380}} showSorterTooltip={false}
                      onRow={r=>({style:{cursor:'pointer'},onClick:()=>{setDetailInd(r);setDetailOpen(true)}})}/>
                  </Card>
                  {/* ── 概念板块分布 (东方财富+同花顺) ── */}
                  {conceptData?.concepts && conceptData.concepts.length>0 && (
                    <>
                    <Divider orientation="left" style={{margin:'4px 0',fontSize:13}}>
                      <Space size={4}>
                        <NodeIndexOutlined style={{color:'#722ed1'}}/>
                        <Text strong style={{fontSize:13}}>概念板块分布</Text>
                        <Tag color="purple" style={{fontSize:10}}>东方财富+同花顺</Tag>
                      </Space>
                    </Divider>
                    <Row gutter={[12,12]}>
                      <Col xs={24} lg={14}>
                        <Card size='small' title={<span><BarChartOutlined/> 概念板块转债分布 Top15</span>} styles={{body:{padding:8}}}>
                          <ReactEChartsCore echarts={echarts} option={conceptDistChartOption} style={{height:320}} notMerge/>
                        </Card>
                      </Col>
                      <Col xs={24} lg={10}>
                        <Card size='small' title={<span><HeatMapOutlined/> 概念动量热度</span>} styles={{body:{padding:8}}}>
                          <ReactEChartsCore echarts={echarts} option={conceptMomentumChartOption} style={{height:320}} notMerge/>
                        </Card>
                      </Col>
                    </Row>
                    </>
                  )}
                  {/* ── 数据源说明 ── */}
                  <Card size='small' styles={{body:{padding:'6px 12px'}}} style={{border:'1px dashed #d9d9d9',background:'#fafafa'}}>
                    <Row gutter={16}>
                      <Col span={8}>
                        <Space size={4}><Tag color="blue">申万行业</Tag><Text type="secondary" style={{fontSize:11}}>行业分类 + 聚合指标</Text></Space>
                      </Col>
                      <Col span={8}>
                        <Space size={4}><Tag color="purple">东方财富</Tag><Text type="secondary" style={{fontSize:11}}>概念板块成分股</Text></Space>
                      </Col>
                      <Col span={8}>
                        <Space size={4}><Tag color="cyan">同花顺</Tag><Text type="secondary" style={{fontSize:11}}>概念板块 + 财务摘要</Text></Space>
                      </Col>
                    </Row>
                  </Card>
                </Col>
              </Row>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 2 — 概念板块 (东方财富+同花顺)
          // ════════════════════════════════════════════════════════
          {key:'concepts', label:<span><NodeIndexOutlined/> 概念板块</span>, children: conceptLoading?renderSkeleton():conceptError?<Alert type='error' message={conceptError} description={<Button onClick={loadConcepts}>重试</Button>}/>:!conceptData?renderEmpty('暂无概念板块数据 (需后台构建缓存)',loadConcepts):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={4}><StatCard title='概念板块数' value={conceptData.total_concepts} suffix='个' color='#722ed1' icon={<NodeIndexOutlined/>}/></Col>
                <Col span={4}><StatCard title='涉及转债数' value={conceptData.total_bonds} suffix='只' color='#52c41a' icon={<TeamOutlined/>}/></Col>
                <Col span={4}><StatCard title='最热门概念' value={sortedConcepts[0]?.concept||'-'} color='#eb2f96' icon={<FireOutlined/>}/></Col>
                <Col span={4}><StatCard title='最热概念转债数' value={sortedConcepts[0]?.bond_count||0} suffix='只' color='#fa8c16'/></Col>
                <Col span={4}><StatCard title='数据来源' value='东方财富+同花顺' color='#13c2c2' icon={<CloudServerOutlined/>}/></Col>
                <Col span={4}><StatCard title='覆盖率' value={conceptData.total_concepts>0?Math.round(conceptData.total_bonds/(indData?.total_bonds||1)*100)+'%':'-'} color='#1677ff' icon={<CheckCircleOutlined/>}/></Col>
              </Row>
              <Row gutter={[12,12]}>
                <Col xs={24} lg={14}>
                  <Card size='small' title={<span><BarChartOutlined/> 概念板块转债分布 (Top 25)</span>}
                    extra={<Space><Select value={conceptSort} onChange={setConceptSort} size='small' style={{width:120}}>
                      <Select.Option value='bond_count'>转债数量</Select.Option>
                      <Select.Option value='avg_change_pct'>涨跌幅</Select.Option>
                      <Select.Option value='avg_premium_ratio'>溢价率</Select.Option>
                      <Select.Option value='avg_dual_low'>双低值</Select.Option>
                    </Select>
                    <Select value={conceptTopK} onChange={setConceptTopK} size='small' style={{width:80}}>
                      {[15,25,50,100].map(n=><Select.Option key={n} value={n}>Top {n}</Select.Option>)}
                    </Select></Space>}
                    styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={conceptBarOption} style={{height:340}} notMerge/>
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card size='small' title={<span><PieChartOutlined/> 概念占比</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={{
                      tooltip:{trigger:'item',formatter:'{b}: {c}只 ({d}%)'},
                      legend:{type:'scroll',orient:'vertical',right:0,top:5,bottom:5,textStyle:{color:chartText,fontSize:10}},
                      series:[{type:'pie',radius:['30%','65%'],center:['35%','55%'],
                        data:sortedConcepts.slice(0,15).map(i=>({name:i.concept,value:i.bond_count})),
                        label:{color:chartText,fontSize:9,formatter:'{b}\n{d}%'},
                        itemStyle:{borderRadius:5,borderColor:isDark?'#1f1f1f':'#fff',borderWidth:2}
                      }]
                    }} style={{height:340}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><ClusterOutlined/> 概念板块详细数据</span>}
                extra={<Space>
                  <Tag color='#722ed1'>东方财富</Tag><Tag color='#13c2c2'>同花顺</Tag>
                  <Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(sortedConcepts,'concepts-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>
                </Space>}
                styles={{body:{padding:0}}}>
                <Table dataSource={sortedConcepts.map((i,idx)=>({...i,key:idx}))} columns={conceptColumns} size='small'
                  pagination={{pageSize:20,showTotal:t=>`共 ${t} 个概念`}} scroll={{x:800,y:420}} showSorterTooltip={false}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 3 — 资金动量
          // ════════════════════════════════════════════════════════
          {key:'momentum', label:<span><FundOutlined/> 资金动量</span>, children: indLoading?renderSkeleton():!indData?renderEmpty('暂无数据',loadIndustries):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                {(()=>{const s5=[...indData.industries].sort((a,b)=>(b.avg_momentum_5d??0)-(a.avg_momentum_5d??0));const s20=[...indData.industries].sort((a,b)=>(b.avg_momentum_20d??0)-(a.avg_momentum_20d??0));const s60=[...indData.industries].sort((a,b)=>(b.avg_momentum_60d??0)-(a.avg_momentum_60d??0));const sf=[...indData.industries].sort((a,b)=>(b.net_capital_flow??0)-(a.net_capital_flow??0));return(<>
                  <Col span={6}><StatCard title='🚀 最高5日动量' value={`${s5[0]?.industry} ${fmtPct(s5[0]?.avg_momentum_5d)}`} color='#eb2f96'/></Col>
                  <Col span={6}><StatCard title='🔥 最高20日动量' value={`${s20[0]?.industry} ${fmtPct(s20[0]?.avg_momentum_20d)}`} color='#f5222d'/></Col>
                  <Col span={6}><StatCard title='📈 最高60日动量' value={`${s60[0]?.industry} ${fmtPct(s60[0]?.avg_momentum_60d)}`} color='#fa8c16'/></Col>
                  <Col span={6}><StatCard title='💵 最大净流入' value={`${sf[0]?.industry} ${fmtFlow(sf[0]?.net_capital_flow)}`} color='#52c41a'/></Col>
                </>)})()}
              </Row>
              <Row gutter={[12,12]}>
                <Col xs={24} lg={12}><Card size='small' title={<span><HeatMapOutlined/> 动量热力图 (Top 18)</span>} styles={{body:{padding:8}}}><ReactEChartsCore echarts={echarts} option={momentumHeatmapOption} style={{height:380}} notMerge/></Card></Col>
                <Col xs={24} lg={12}><Card size='small' title={<span><DollarOutlined/> 资金流向 (Top 15)</span>} styles={{body:{padding:8}}}><ReactEChartsCore echarts={echarts} option={flowChartOption} style={{height:380}} notMerge/></Card></Col>
                <Col xs={24} lg={12}><Card size='small' title={<span><BarChartOutlined/> 超大单/大单拆分</span>} styles={{body:{padding:8}}}><ReactEChartsCore echarts={echarts} option={flowBreakdownOption} style={{height:380}} notMerge/></Card></Col>
              </Row>
              <Card size='small' title={<span><ThunderboltOutlined/> 动量与资金排名</span>} extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(indData.industries,'momentum-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>} styles={{body:{padding:0}}}>
                <Table dataSource={[...indData.industries].sort((a,b)=>(b.avg_momentum_20d??0)-(a.avg_momentum_20d??0)).map((i,idx)=>({...i,key:idx,rank:idx+1}))}
                  columns={[{title:'#',dataIndex:'rank',width:40,render:(v:number)=><Badge count={v<=3?v:0} offset={[8,0]} style={{backgroundColor:v===1?'#f5222d':v===2?'#fa8c16':'#faad14'}}><span>{v}</span></Badge>},...momentumColumns]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:1100,y:420}} showSorterTooltip={false}
                  onRow={r=>({style:{cursor:'pointer'},onClick:()=>{setDetailInd(r);setDetailOpen(true)}})}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 4 — 估值对比
          // ════════════════════════════════════════════════════════
          {key:'valuation', label:<span><SafetyOutlined/> 估值对比</span>, children: indLoading?renderSkeleton():!indData?renderEmpty('暂无数据',loadIndustries):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                {(()=>{const byRoe=[...indData.industries].sort((a,b)=>(b.avg_roe??0)-(a.avg_roe??0));const byPe=[...indData.industries].filter(i=>i.avg_pe>0).sort((a,b)=>a.avg_pe-b.avg_pe);const byPrem=[...indData.industries].sort((a,b)=>a.avg_premium_ratio-b.avg_premium_ratio);return(<>
                  <Col span={6}><StatCard title='💰 最高ROE' value={`${byRoe[0]?.industry} ${fmt(byRoe[0]?.avg_roe)}%`} color='#52c41a'/></Col>
                  <Col span={6}><StatCard title='📉 最低PE' value={`${byPe[0]?.industry} ${fmt(byPe[0]?.avg_pe)}`} color='#1890ff'/></Col>
                  <Col span={6}><StatCard title='🎯 最低溢价率' value={`${byPrem[0]?.industry} ${fmt(byPrem[0]?.avg_premium_ratio)}%`} color='#fa8c16'/></Col>
                  <Col span={6}><StatCard title='📊 估值维度' value='PE/PB/ROE/IV' color='#722ed1' icon={<DashboardOutlined/>}/></Col>
                </>)})()}
              </Row>
              <Row gutter={[12,12]}>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><BarChartOutlined/> ROE分布 (Top 20)</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={roeChartOption} style={{height:360}} notMerge/>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><GoldOutlined/> PE-PB 散点图</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={valuationScatterOption} style={{height:360}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Row gutter={[12,12]} style={{marginTop:12}}>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><PercentageOutlined/> 毛利率 vs 负债率</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={gpmChartOption} style={{height:360}} notMerge/>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><SafetyCertificateOutlined/> 换手率/质押率排名</span>} styles={{body:{padding:0}}}>
                    <Table dataSource={[...(indData?.industries??[])].filter(i=>i.bond_count>=2).sort((a,b)=>(b.avg_turnover_rate??0)-(a.avg_turnover_rate??0)).slice(0,15).map((i,idx)=>({...i,key:idx}))}
                      columns={[
                        {title:'行业',dataIndex:'industry',key:'ind',width:90,render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                        {title:'换手率',dataIndex:'avg_turnover_rate',key:'tr',width:70,render:(v:number)=><span>{fmt(v)}%</span>},
                        {title:'质押率',dataIndex:'avg_pledge_ratio',key:'pr',width:70,render:(v:number)=><span style={{color:v>=30?'#ff4d4f':v>=15?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
                        {title:'ROE',dataIndex:'avg_roe',key:'roe',width:65,render:(v:number)=><span>{fmt(v)}%</span>},
                        {title:'毛利率',dataIndex:'avg_gpm',key:'gpm',width:70,render:(v:number)=><span style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
                      ]}
                      size='small' pagination={false} scroll={{y:340}}/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><SafetyCertificateOutlined/> 估值详细数据</span>} extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(sortedIndustries,'valuation-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>} styles={{body:{padding:0}}}>
                <Table dataSource={sortedIndustries.map((i,idx)=>({...i,key:idx}))} columns={valColumns} size='small'
                  pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:1400,y:400}} showSorterTooltip={false}
                  onRow={r=>({style:{cursor:'pointer'},onClick:()=>{setDetailInd(r);setDetailOpen(true)}})}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 5 — 质量分析
          // ════════════════════════════════════════════════════════
          {key:'quality', label:<span><SafetyCertificateOutlined/> 质量分析</span>, children: indLoading?renderSkeleton():!indData?renderEmpty('暂无数据',loadIndustries):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={6}><StatCard title='高质量行业' value={indData.industries.filter(i=>(i.avg_roe??0)>=10).length} suffix='个' color='#52c41a' icon={<CheckCircleOutlined/>}/></Col>
                <Col span={6}><StatCard title='低估值行业' value={indData.industries.filter(i=>(i.avg_pe??0)>0&&(i.avg_pe??0)<20).length} suffix='个' color='#1890ff' icon={<StockOutlined/>}/></Col>
                <Col span={6}><StatCard title='低溢价行业' value={indData.industries.filter(i=>(i.avg_premium_ratio??0)<20).length} suffix='个' color='#fa8c16' icon={<GoldOutlined/>}/></Col>
                <Col span={6}><StatCard title='正YTM行业' value={indData.industries.filter(i=>(i.avg_ytm??0)>0).length} suffix='个' color='#722ed1' icon={<PercentageOutlined/>}/></Col>
              </Row>
              <Row gutter={[12,12]}>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><BarChartOutlined/> YTM分布 (Top 20)</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={{
                      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
                      grid:{left:100,right:20,top:8,bottom:24},
                      xAxis:{type:'value',name:'YTM(%)',axisLabel:{color:chartText}},
                      yAxis:{type:'category',data:[...indData.industries].filter(i=>i.avg_ytm>0).sort((a,b)=>(b.avg_ytm??0)-(a.avg_ytm??0)).slice(0,20).map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
                      series:[{type:'bar',data:[...indData.industries].filter(i=>i.avg_ytm>0).sort((a,b)=>(b.avg_ytm??0)-(a.avg_ytm??0)).slice(0,20).map(i=>({value:i.avg_ytm,itemStyle:{color:i.avg_ytm>=0?'#52c41a':'#ff4d4f',borderRadius:4}})),barWidth:'50%'}]
                    }} style={{height:360}} notMerge/>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><BarChartOutlined/> 溢价率分布 (最低 20)</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={{
                      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
                      grid:{left:100,right:20,top:8,bottom:24},
                      xAxis:{type:'value',name:'溢价率(%)',axisLabel:{color:chartText}},
                      yAxis:{type:'category',data:[...indData.industries].sort((a,b)=>a.avg_premium_ratio-b.avg_premium_ratio).slice(0,20).map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
                      series:[{type:'bar',data:[...indData.industries].sort((a,b)=>a.avg_premium_ratio-b.avg_premium_ratio).slice(0,20).map(i=>({value:i.avg_premium_ratio,itemStyle:{color:i.avg_premium_ratio<20?'#52c41a':i.avg_premium_ratio<40?'#faad14':'#ff4d4f',borderRadius:4}})),barWidth:'50%'}]
                    }} style={{height:360}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><SafetyCertificateOutlined/> 质量综合排名 (ROE+YTM+低溢价)</span>} styles={{body:{padding:0}}}>
                <Table dataSource={[...indData.industries].map(i=>({...i,quality_score:((i.avg_roe||0)*0.4+(i.avg_ytm||0)*30-(i.avg_premium_ratio||0)*0.3)})).sort((a,b)=>b.quality_score-a.quality_score).map((i,idx)=>({...i,key:idx,rank:idx+1}))}
                  columns={[
                    {title:'#',dataIndex:'rank',width:40,render:(v:number)=><Badge count={v<=3?v:0} offset={[8,0]} style={{backgroundColor:v===1?'#f5222d':v===2?'#fa8c16':'#faad14'}}><span>{v}</span></Badge>},
                    {title:'行业',dataIndex:'industry',width:100,render:(v:string)=><Tag color={indColor(v)} style={{margin:0}}>{v}</Tag>},
                    {title:'质量分',dataIndex:'quality_score',width:80,sorter:(a:any,b:any)=>a.quality_score-b.quality_score,render:(v:number)=><Text style={{color:v>=0?'#52c41a':'#ff4d4f',fontWeight:700}}>{fmt(v)}</Text>},
                    {title:'ROE',dataIndex:'avg_roe',width:70,render:(v:number)=><Text style={{color:v>=10?'#52c41a':'#faad14'}}>{fmt(v)}%</Text>},
                    {title:'YTM',dataIndex:'avg_ytm',width:65,render:(v:number)=><Text style={{color:v>=0?'#52c41a':'#8c8c8c'}}>{fmt(v)}%</Text>},
                    {title:'溢价率',dataIndex:'avg_premium_ratio',width:75,render:(v:number)=><Text style={{color:v<20?'#52c41a':v<40?'#faad14':'#ff4d4f'}}>{fmt(v)}%</Text>},
                    {title:'双低',dataIndex:'avg_dual_low',width:60,render:(v:number)=><Text style={{color:v<150?'#52c41a':'#faad14'}}>{fmt(v)}</Text>},
                    {title:'PE',dataIndex:'avg_pe',width:55,render:(v:number)=>v?fmt(v):'-'},
                    {title:'转债数',dataIndex:'bond_count',width:60},
                  ]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:800,y:420}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 6 — 波动风险
          // ════════════════════════════════════════════════════════
          {key:'risk', label:<span><AlertOutlined/> 波动风险</span>, children: indLoading?renderSkeleton():!indData?renderEmpty('暂无数据',loadIndustries):(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={6}><StatCard title='高波动行业' value={indData.industries.filter(i=>(i.avg_iv??0)>=40).length} suffix='个' color='#ff4d4f' icon={<AlertOutlined/>}/></Col>
                <Col span={6}><StatCard title='中波动行业' value={indData.industries.filter(i=>(i.avg_iv??0)>=20&&(i.avg_iv??0)<40).length} suffix='个' color='#faad14' icon={<ThunderboltOutlined/>}/></Col>
                <Col span={6}><StatCard title='低波动行业' value={indData.industries.filter(i=>(i.avg_iv??0)>0&&(i.avg_iv??0)<20).length} suffix='个' color='#52c41a' icon={<SafetyOutlined/>}/></Col>
                <Col span={6}><StatCard title='波动率最高' value={(()=>{const t=[...indData.industries].sort((a,b)=>(b.avg_iv??0)-(a.avg_iv??0));return t[0]?.industry||'-'})()} color='#ff4d4f'/></Col>
              </Row>
              <Row gutter={[12,12]}>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><BarChartOutlined/> 隐含波动率 (Top 20)</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={ivChartOption} style={{height:380}} notMerge/>
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card size='small' title={<span><BarChartOutlined/> 溢价率 vs 波动率</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={{
                      tooltip:{formatter:(p:any)=>`${p.data[3]}<br/>溢价率: ${p.data[0].toFixed(1)}%<br/>IV: ${p.data[1].toFixed(1)}%<br/>转债: ${p.data[2]}只`},
                      grid:{left:60,right:30,top:30,bottom:40},
                      xAxis:{type:'value',name:'溢价率(%)',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
                      yAxis:{type:'value',name:'IV(%)',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
                      series:[{type:'scatter',symbolSize:(d:any)=>Math.max(8,Math.min(40,d[2]*1.5)),
                        data:(indData.industries??[]).filter(i=>i.avg_iv>0&&i.avg_premium_ratio>0&&i.bond_count>=2).map(i=>[i.avg_premium_ratio,i.avg_iv,i.bond_count,i.industry]),
                        label:{show:true,formatter:(p:any)=>p.data[3],position:'right',fontSize:9,color:chartText},
                        itemStyle:{color:'rgba(114,46,209,0.7)',borderRadius:4}
                      }]
                    }} style={{height:380}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><AlertOutlined/> 波动风险排名</span>} styles={{body:{padding:0}}}>
                <Table dataSource={[...indData.industries].filter(i=>i.avg_iv>0).sort((a,b)=>(b.avg_iv??0)-(a.avg_iv??0)).map((i,idx)=>({...i,key:idx,rank:idx+1}))}
                  columns={[
                    {title:'#',dataIndex:'rank',width:40},
                    {title:'行业',dataIndex:'industry',width:100,render:(v:string)=><Tag color={indColor(v)} style={{margin:0}}>{v}</Tag>},
                    {title:'IV(%)',dataIndex:'avg_iv',width:70,sorter:(a:any,b:any)=>(a.avg_iv||0)-(b.avg_iv||0),render:(v:number)=><Text style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a',fontWeight:600}}>{fmt(v)}</Text>},
                    {title:'溢价率',dataIndex:'avg_premium_ratio',width:75,render:(v:number)=><Text>{fmt(v)}%</Text>},
                    {title:'双低',dataIndex:'avg_dual_low',width:60,render:(v:number)=>fmt(v)},
                    {title:'20日动量',dataIndex:'avg_momentum_20d',width:80,render:(v:number)=><Text style={{color:(v||0)>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</Text>},
                    {title:'ROE',dataIndex:'avg_roe',width:65,render:(v:number)=>fmt(v)+'%'},
                    {title:'转债数',dataIndex:'bond_count',width:60},
                  ]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:800,y:420}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 7 — ETF映射
          // ════════════════════════════════════════════════════════
          {key:'etf', label:<span><StockOutlined/> ETF映射</span>, children: (
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={6}><StatCard title='ETF数量' value={SECTOR_ETF_MAP.length} suffix='只' color='#1890ff' icon={<StockOutlined/>}/></Col>
                <Col span={6}><StatCard title='覆盖行业' value={[...new Set(SECTOR_ETF_MAP.map(e=>e.sector))].length} suffix='个' color='#52c41a'/></Col>
                <Col span={6}><StatCard title='数据来源' value='申万行业' color='#722ed1' icon={<DatabaseOutlined/>}/></Col>
                <Col span={6}><StatCard title='回测支持' value='已就绪' color='#13c2c2' icon={<CheckCircleOutlined/>}/></Col>
              </Row>
              <Card size='small' title={<span><StockOutlined/> 行业ETF映射表</span>} extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(SECTOR_ETF_MAP,'etf-map-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>} styles={{body:{padding:0}}}>
                <Table dataSource={SECTOR_ETF_MAP.map((e,i)=>({...e,key:i}))}
                  columns={[
                    {title:'申万代码',dataIndex:'sw_code',width:100},
                    {title:'ETF代码',dataIndex:'etf_code',width:100,render:(v:string)=><Text style={{color:'#1677ff',fontWeight:600}}>{v}</Text>},
                    {title:'ETF名称',dataIndex:'etf_name',width:160},
                    {title:'行业',dataIndex:'sector',width:120,render:(v:string)=><Tag color={indColor(v)}>{v}</Tag>},
                  ]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 只ETF`}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 8 — 行业回测
          // ════════════════════════════════════════════════════════
          {key:'backtest', label:<span><ExperimentOutlined/> 行业回测</span>, children: (
            <Row gutter={[16,16]}>
              <Col xs={24} lg={6}>
                <Card size='small' title={<span><SettingOutlined/> 回测参数</span>} styles={{body:{padding:'12px 16px'}}}>
                  {strategyInfo?(
                    <Space direction='vertical' style={{width:'100%'}} size={8}>
                      <div><Text type='secondary' style={{fontSize:11}}>持仓行业: <b style={{color:themeToken.colorPrimary}}>{holdCount}个</b></Text><Slider min={2} max={10} value={holdCount} onChange={setHoldCount}/></div>
                      <div><Text type='secondary' style={{fontSize:11}}>调仓间隔: <b style={{color:themeToken.colorPrimary}}>{rebalanceDays}天</b></Text><Slider min={5} max={60} value={rebalanceDays} onChange={setRebalanceDays}/></div>
                      <div><Text type='secondary' style={{fontSize:11}}>动量窗口: <b style={{color:themeToken.colorPrimary}}>{momentumWindow}天</b></Text><Slider min={10} max={120} value={momentumWindow} onChange={setMomentumWindow}/></div>
                      <div><Text type='secondary' style={{fontSize:11}}>多头因子</Text><Select value={bullFactor} onChange={setBullFactor} style={{width:'100%'}} size='small'><Select.Option value='momentum_1m'>🚀 1月动量</Select.Option><Select.Option value='momentum_3m'>🚀 3月动量</Select.Option><Select.Option value='sharpe_63d'>📐 63日夏普</Select.Option><Select.Option value='volatility'>📉 波动率倒数</Select.Option></Select></div>
                      <div><Text type='secondary' style={{fontSize:11}}>空头因子</Text><Select value={bearFactor} onChange={setBearFactor} style={{width:'100%'}} size='small'><Select.Option value='sharpe_63d'>📐 63日夏普(倒序)</Select.Option><Select.Option value='momentum_1m'>🚀 1月动量(倒序)</Select.Option><Select.Option value='volatility'>📉 波动率</Select.Option></Select></div>
                      <div style={{display:'flex',alignItems:'center',gap:8}}><Text type='secondary' style={{fontSize:11}}>使用ETF数据</Text><Switch checked={useEtf} onChange={setUseEtf} size='small'/></div>
                      <Divider style={{margin:'10px 0'}}/>
                      <Button type='primary' icon={<PlayCircleOutlined/>} onClick={doBacktest} loading={running} block size='large' style={{fontWeight:600,borderRadius:8}}>{running?'⏳ 执行中...':'▶ 开始回测'}</Button>
                    </Space>
                  ):<Empty description='策略信息加载中' image={Empty.PRESENTED_IMAGE_SIMPLE}/>}
                </Card>
              </Col>
              <Col xs={24} lg={18}>
                {btError&&<Alert type='error' message={btError} closable onClose={()=>setBtError(null)} style={{marginBottom:12}}/>}
                {running&&!result&&<Card style={{height:400,display:'flex',justifyContent:'center',alignItems:'center',flexDirection:'column',gap:16}}><Spin size='large'/><Text type='secondary'>执行行业轮动回测...</Text><Progress percent={Math.min(90,Date.now()%90)} style={{width:200}}/></Card>}
                {!result&&!running&&!btError&&<Card style={{height:400,display:'flex',justifyContent:'center',alignItems:'center',background:themeToken.colorFillAlter,borderRadius:10}}><Empty description='配置参数后点击【开始回测】' image={Empty.PRESENTED_IMAGE_SIMPLE}/></Card>}
                {result&&metrics&&(<>
                  <Card size='small' title={<span><TrophyOutlined/> 回测绩效</span>} styles={{body:{padding:'10px 16px',background:`linear-gradient(135deg,${themeToken.colorPrimary+'08'},transparent)`}}} style={{marginBottom:12,borderRadius:10}}>
                    <Row gutter={[8,12]}>
                      <Col span={4}><Statistic title='累计收益' value={fmt(metrics.total_return_pct)} suffix='%' valueStyle={{color:metrics.total_return_pct>=0?'#ff4d4f':'#52c41a',fontSize:22,fontWeight:700}} prefix={metrics.total_return_pct>=0?<RiseOutlined/>:<FallOutlined/>}/></Col>
                      <Col span={4}><Statistic title='年化收益' value={fmt(metrics.annual_return_pct)} suffix='%' valueStyle={{color:metrics.annual_return_pct>=0?'#ff4d4f':'#52c41a',fontWeight:600}}/></Col>
                      <Col span={4}><Statistic title='最大回撤' value={fmt(metrics.max_drawdown_pct)} suffix='%' valueStyle={{color:'#ff4d4f',fontWeight:600}}/></Col>
                      <Col span={4}><Statistic title='夏普比率' value={fmt(metrics.sharpe_ratio)} valueStyle={{color:metrics.sharpe_ratio>=1?'#52c41a':'#faad14',fontWeight:600}}/></Col>
                      <Col span={4}><Statistic title='胜率' value={(metrics.win_rate*100).toFixed(1)} suffix='%' valueStyle={{color:metrics.win_rate>=0.5?'#52c41a':'#faad14',fontWeight:600}}/></Col>
                      <Col span={4}><Statistic title='交易次数' value={metrics.total_trades} suffix='笔' valueStyle={{fontWeight:600}}/></Col>
                      {benchmarkReturn!=null&&<Col span={4}><Statistic title='基准收益' value={(benchmarkReturn*100).toFixed(2)} suffix='%' valueStyle={{fontWeight:600}}/></Col>}
                      {excessReturn!=null&&<Col span={4}><Statistic title='超额收益' value={(excessReturn*100).toFixed(2)} suffix='%' valueStyle={{color:excessReturn>=0?'#52c41a':'#ff4d4f',fontWeight:700}}/></Col>}
                    </Row>
                  </Card>
                  {result.equity_curve?.length>0&&<Card size='small' title={<span><LineChartOutlined/> 净值走势</span>} styles={{body:{padding:8}}} style={{marginBottom:12}}><ReactEChartsCore echarts={echarts} option={navChartOption()} style={{height:280}} notMerge/></Card>}
                  {result.trades?.length>0&&<Card size='small' title={<span><SwapOutlined/> 交易记录</span>} extra={<Badge count={result.trades.length} style={{backgroundColor:'#722ed1'}}/>} styles={{body:{padding:0}}}><Table dataSource={result.trades.map((t,i)=>({...t,key:i}))} columns={tradeColumns} size='small' pagination={{pageSize:15,showTotal:t=>`共 ${t} 笔`}} scroll={{y:380}}/></Card>}
                </>)}
              </Col>
            </Row>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 9 — 数据源 (北向/融资融券/龙虎榜/大宗/股东/业绩/解禁)
          // ════════════════════════════════════════════════════════
          {key:'sources', label:<span><DatabaseOutlined/> 数据源</span>, children: (
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Tabs activeKey={dsTab} onChange={setDsTab} size='small'
                items={[
                  {key:'overview', label:<span><DashboardOutlined/> 概览</span>, children: dsLoading?renderSkeleton():dsError?<Alert type='error' message={dsError}/>:!dsInfo?<Empty/>:(
                    <div>
                      <Row gutter={[8,8]}>
                        <Col span={6}><StatCard title='已接入数据源' value={Object.values(dsInfo.sources).filter(s=>s.exists).length} suffix={`/ ${Object.keys(dsInfo.sources).length}`} color='#52c41a' icon={<CheckCircleOutlined/>}/></Col>
                        <Col span={6}><StatCard title='总记录数' value={Object.values(dsInfo.sources).reduce((sum,s)=>sum+(s.entries||0),0).toLocaleString()} suffix='条' color='#1890ff' icon={<DatabaseOutlined/>}/></Col>
                        <Col span={6}><StatCard title='缓存大小' value={fmt(Object.values(dsInfo.sources).reduce((sum,s)=>sum+(s.size||0),0)/1024/1024,2)} suffix='MB' color='#722ed1' icon={<CloudServerOutlined/>}/></Col>
                        <Col span={6}><StatCard title='缓存目录' value={(dsInfo.cache_dir||'').split('/').pop()||'-'} color='#13c2c2' icon={<ApiOutlined/>}/></Col>
                      </Row>
                      <Card size='small' title={<span><ApiOutlined/> 所有数据源状态</span>} style={{marginTop:12,borderRadius:10}} styles={{body:{padding:0}}}>
                        <Table
                          size='small'
                          pagination={false}
                          dataSource={Object.entries(dsInfo.sources).map(([k,v])=>({key:k,name:DS_NAMES[k]||k,...v}))}
                          columns={[
                            {title:'数据源',dataIndex:'name',width:140,render:(v,r)=><Space><Tag color={r.exists?(r.entries&&r.entries>0?'green':'orange'):'red'}>{r.exists?'✓':'✗'}</Tag><Text strong>{v}</Text></Space>},
                            {title:'记录数',dataIndex:'entries',width:100,align:'right',render:(v)=>v!=null?v.toLocaleString():'-'},
                            {title:'大小',dataIndex:'size',width:100,align:'right',render:(v)=>v!=null?fmt(v/1024,1)+'KB':'-'},
                            {title:'刷新于',dataIndex:'age_seconds',width:160,render:(v)=>v!=null?(v<60?v.toFixed(0)+'秒前':v<3600?(v/60).toFixed(1)+'分钟前':v<86400?(v/3600).toFixed(1)+'小时前':(v/86400).toFixed(1)+'天前'):'-'},
                            {title:'路径',dataIndex:'path',render:(v)=><Text type='secondary' style={{fontSize:11}}>{v}</Text>},
                          ]}
                        />
                      </Card>
                    </div>
                  )},
                  {key:'north', label:<span><GlobalOutlined/> 北向资金</span>, children: northLoading?renderSkeleton():!northData?renderEmpty('暂无北向资金数据',loadNorth):(
                    <div>
                      <Row gutter={[8,8]}>
                        <Col span={6}><StatCard title='北向个股数' value={northData.stocks.length} suffix='只' color='#1890ff'/></Col>
                        <Col span={6}><StatCard title='汇总类型' value={northData.summary.length} suffix='种' color='#722ed1'/></Col>
                        <Col span={6}><StatCard title='数据总计' value={northData.total} suffix='条' color='#52c41a'/></Col>
                      </Row>
                      <Card size='small' title='个股北向持仓 TOP 50' style={{marginTop:12,borderRadius:10}} styles={{body:{padding:0}}}>
                        <Table size='small' dataSource={(northData.stocks||[]).slice(0,50).map((s,i)=>({...s,key:i}))} pagination={false} scroll={{y:400}} columns={[
                          {title:'代码',dataIndex:'code',width:80},
                          {title:'名称',dataIndex:'name',width:100},
                          {title:'涨跌幅',dataIndex:'change_pct',width:90,render:(v)=>fmtPct(v)},
                          {title:'持股数(万)',dataIndex:'hold_shares',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                          {title:'持股市值(亿)',dataIndex:'hold_market_cap',width:120,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                          {title:'持股比例(%)',dataIndex:'hold_ratio',width:110,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                          {title:'增减仓市值(万)',dataIndex:'add_market_cap',width:140,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        ]}/>
                      </Card>
                    </div>
                  )},
                  {key:'margin', label:<span><BankOutlined/> 融资融券</span>, children: marginLoading?renderSkeleton():!marginData?renderEmpty('暂无融资融券数据',loadMargin):(
                    <div>
                      <Row gutter={[8,8]}>
                        <Col span={6}><StatCard title='融资融券股数' value={marginData.stocks.length} suffix='只' color='#1890ff'/></Col>
                        <Col span={6}><StatCard title='交易所汇总' value={marginData.summary.length} suffix='条' color='#722ed1'/></Col>
                      </Row>
                      <Card size='small' title='融资融券 TOP 50 (按融资余额)' style={{marginTop:12,borderRadius:10}} styles={{body:{padding:0}}}>
                        <Table size='small' dataSource={(marginData.stocks||[]).slice(0,50).map((s,i)=>({...s,key:i}))} pagination={false} scroll={{y:400}} columns={[
                          {title:'代码',dataIndex:'code',width:80},
                          {title:'名称',dataIndex:'name',width:100},
                          {title:'融资余额(亿)',dataIndex:'rzye',width:120,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                          {title:'融资买入额(亿)',dataIndex:'rzmre',width:130,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                          {title:'融券余量(万)',dataIndex:'rqyl',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        ]}/>
                      </Card>
                    </div>
                  )},
                  {key:'lhb', label:<span><FireOutlined/> 龙虎榜</span>, children: lhbLoading?renderSkeleton():!lhbData?renderEmpty('暂无龙虎榜数据',loadLhb):(
                    <Card size='small' title={`龙虎榜个股 TOP 50 (净买额排序) — ${lhbData.stocks.length} 只`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(lhbData.stocks||[]).slice(0,50).map((s,i)=>({...s,key:i}))} pagination={false} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'上榜次数',dataIndex:'times',width:90,align:'right'},
                        {title:'净买额(万)',dataIndex:'net_buy_amt',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        {title:'买入额(万)',dataIndex:'buy_amt',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        {title:'卖出额(万)',dataIndex:'sell_amt',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                      ]}/>
                    </Card>
                  )},
                  {key:'block', label:<span><DollarOutlined/> 大宗交易</span>, children: blockLoading?renderSkeleton():!blockData?renderEmpty('暂无大宗交易数据',loadBlock):(
                    <Card size='small' title={`大宗交易 TOP 50 (按总成交额) — ${blockData.stocks.length} 只`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(blockData.stocks||[]).slice(0,50).map((s,i)=>({...s,key:i}))} pagination={false} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'总成交额(亿)',dataIndex:'total_amt',width:130,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                        {title:'交易笔数',dataIndex:'trade_count',width:90,align:'right'},
                        {title:'最高价',dataIndex:'max_price',width:90,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                        {title:'最低价',dataIndex:'min_price',width:90,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                      ]}/>
                    </Card>
                  )},
                  {key:'holder', label:<span><TeamOutlined/> 股东户数</span>, children: holderLoading?renderSkeleton():!holderData?renderEmpty('暂无股东户数数据',loadHolder):(
                    <Card size='small' title={`股东户数 (${holderData.stocks.length} 只)`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(holderData.stocks||[]).slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'股东户数',dataIndex:'holder_num',width:130,align:'right',render:(v)=>v!=null?v.toLocaleString():'-'},
                        {title:'较上期变化',dataIndex:'change_pct',width:120,align:'right',render:(v)=>fmtPct(v)},
                        {title:'平均持股(万)',dataIndex:'avg_hold_shares',width:120,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        {title:'统计日期',dataIndex:'stat_date',width:120},
                      ]}/>
                    </Card>
                  )},
                  {key:'forecast', label:<span><RiseOutlined/> 业绩预告</span>, children: forecastLoading?renderSkeleton():!forecastData?renderEmpty('暂无业绩预告数据',loadForecast):(
                    <Card size='small' title={`业绩预告 (${forecastData.stocks.length} 条)`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(forecastData.stocks||[]).slice(0,200).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'报告期',dataIndex:'period',width:100},
                        {title:'预告类型',dataIndex:'forecast_type',width:120,render:(v)=><Tag color={v?.includes('增')?'green':v?.includes('减')?'red':'orange'}>{v||'-'}</Tag>},
                        {title:'变动下限(%)',dataIndex:'change_pct_min',width:120,align:'right',render:(v)=>fmtPct(v)},
                        {title:'变动上限(%)',dataIndex:'change_pct_max',width:120,align:'right',render:(v)=>fmtPct(v)},
                        {title:'摘要',dataIndex:'summary',ellipsis:true,render:(v)=><Tooltip title={v}><Text style={{fontSize:11}}>{(v||'').slice(0,50)}{v&&v.length>50?'...':''}</Text></Tooltip>},
                      ]}/>
                    </Card>
                  )},
                  {key:'express', label:<span><TrophyOutlined/> 业绩快报</span>, children: expressLoading?renderSkeleton():!expressData?renderEmpty('暂无业绩快报数据',loadExpress):(
                    <Card size='small' title={`业绩快报 (${expressData.stocks.length} 条)`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(expressData.stocks||[]).slice(0,200).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'报告期',dataIndex:'period',width:100},
                        {title:'营收(亿)',dataIndex:'revenue',width:110,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                        {title:'营收同比增长',dataIndex:'revenue_yoy',width:130,align:'right',render:(v)=>fmtPct(v)},
                        {title:'净利润(亿)',dataIndex:'net_profit',width:110,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                        {title:'净利润增长',dataIndex:'net_profit_yoy',width:130,align:'right',render:(v)=>fmtPct(v)},
                        {title:'EPS',dataIndex:'eps',width:80,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                        {title:'ROE(%)',dataIndex:'roe',width:80,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                      ]}/>
                    </Card>
                  )},
                  {key:'release', label:<span><CalendarOutlined/> 限售解禁</span>, children: releaseLoading?renderSkeleton():!releaseData?renderEmpty('暂无限售解禁数据',loadRelease):(
                    <Card size='small' title={`未来 90 天限售解禁 TOP 100 (${releaseData.events.length} 条)`} style={{borderRadius:10}} styles={{body:{padding:0}}}>
                      <Table size='small' dataSource={(releaseData.events||[]).slice(0,100).map((e,i)=>({...e,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                        {title:'代码',dataIndex:'code',width:80},
                        {title:'名称',dataIndex:'name',width:100},
                        {title:'解禁日期',dataIndex:'release_date',width:120},
                        {title:'解禁股数(万)',dataIndex:'release_shares',width:130,align:'right',render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                        {title:'解禁市值(亿)',dataIndex:'release_market_cap',width:130,align:'right',render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                        {title:'占流通比(%)',dataIndex:'release_ratio',width:120,align:'right',render:(v)=>v!=null?v.toFixed(2):'-'},
                        {title:'性质',dataIndex:'release_type',width:120,render:(v)=><Tag color='orange'>{v||'-'}</Tag>},
                        {title:'股东数',dataIndex:'shareholder_count',width:90,align:'right'},
                      ]}/>
                    </Card>
                  )},
                ]}
              />
            </div>
          )},
        ]}
      />

      {renderDetailModal()}
    </div>
  )
}
