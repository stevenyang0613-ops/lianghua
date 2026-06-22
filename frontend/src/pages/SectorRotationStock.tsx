/**
 * 行业轮动-股票版 — 正股维度的行业轮动分析
 *
 * 7大Tab完整展示:
 *   1. 行业概览 — 申万行业股票分布，柱状图+饼图+概览表
 *   2. 动量排名 — 多周期动量热力图+动量排名+动量分散度
 *   3. 资金流向 — 超大单/大单/主力资金流向+换手率
 *   4. 估值质量 — PE/PB/ROE/毛利率/CAGR/负债率多维估值
 *   5. 波动风险 — IV/换手率/质押率/动量分散度
 *   6. 行业个股 — 点击行业展开个股明细表
 *   7. 综合排名 — 多因子综合评分排名
 */

import { useState, useEffect, useMemo } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Select, Space, Button, Tabs, Badge, Modal,
  Skeleton, Input, InputNumber, Divider, theme as antTheme, Slider, Tooltip,
} from 'antd'
import {
  SwapOutlined, LineChartOutlined, RiseOutlined, FallOutlined,
  DatabaseOutlined, ReloadOutlined, StockOutlined, DollarOutlined,
  FilterOutlined, ArrowUpOutlined, ArrowDownOutlined, MinusOutlined,
  HeatMapOutlined, DashboardOutlined, DownloadOutlined,
  AppstoreOutlined, ThunderboltOutlined, FundOutlined,
  BarChartOutlined, PieChartOutlined, TeamOutlined,
  SafetyCertificateOutlined, PercentageOutlined,
  CheckCircleOutlined, StarOutlined, ClusterOutlined,
  TrophyOutlined, SearchOutlined, ExpandOutlined,
  SettingOutlined, NodeIndexOutlined, TagsOutlined, AimOutlined,
  BankOutlined, FireOutlined, CalendarOutlined,
  RocketOutlined, FieldTimeOutlined, BulbOutlined, CrownOutlined,
} from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import RecHistoryTable from '../components/RecHistoryTable'
import echarts from '../utils/echarts'
import {
  fetchStockIndustries,
  fetchStockConcepts,
  fetchNorthCapital,
  fetchMarginStocks,
  fetchLhb,
  fetchBlockTrade,
  fetchHolderNum,
  fetchEarningsForecast,
  fetchEarningsExpress,
  fetchRestrictedRelease,
  fetchIndividualFundFlow,
  fetchIndustryFundFlow,
  fetchMainFundFlow,
  fetchTurnoverRank,
  fetchHsgtFundFlow,
  type StockIndustryAgg, type StockIndustryItem, type StockIndustriesResponse,
  type StockConceptsResponse, type StockConceptAgg, type StockConceptSource,
  type NorthResponse,
  type MarginResponse,
  type LhbResponse,
  type BlockTradeResponse,
  type HolderNumResponse,
  type EarningsForecastResponse,
  type EarningsExpressResponse,
  type RestrictedReleaseResponse,
  type IndividualFundFlowResponse,
  type IndustryFundFlowResponse,
  type MainFundFlowResponse,
  type TurnoverRankResponse,
  type HsgtFundFlowResponse,
  type IndustryRecommendations, type IndustryRecommendation,
  fetchIndustryRecommendations,
  fetchAIInsight,
  fetchRecHistory, type RecHistoryResponse, type RecHistoryEntry,
  fetchRecAccuracy, type RecAccuracyResponse, type HorizonAccuracy,
} from '../services/api'
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
{ layer:3, title:'东方财富', desc:'概念板块 + 行业行情 + 资金流向', source:'EastMoney', color:'#722ed1' },
{ layer:4, title:'同花顺', desc:'概念板块 + 财务摘要', source:'THS', color:'#13c2c2' },
{ layer:5, title:'Sina实时', desc:'正股价格/涨跌/成交额', source:'Sina', color:'#fa8c16' },
{ layer:6, title:'Baidu估值', desc:'PE/PB 5线程并发', source:'Baidu', color:'#2f54eb' },
{ layer:7, title:'Tencent K线', desc:'正股日K 10线程', source:'Tencent', color:'#f5222d' },
{ layer:8, title:'东方财富资金', desc:'个股/行业资金流向+沪深港通', source:'EM Fund', color:'#eb2f96' },
]

// 细粒度概念快选标签 — 点击 Tab 8 时可一键筛选
// Synonyms: 智能驾驶→自动驾驶/无人驾驶/车联网/智能座舱；钠电池→钠离子电池；
//           GPU/CPU→算力概念/AI芯片/存储芯片
const FINE_GRAINED_CONCEPTS = [
  { label: 'CPO', keys: ['CPO', '光模块'] },
  { label: '机器人', keys: ['机器人'] },
  { label: '人形机器人', keys: ['人形机器人'] },
  { label: '减速器', keys: ['减速器'] },
  { label: '固态电池', keys: ['固态电池'] },
  { label: '钠离子电池', keys: ['钠离子'] },
  { label: 'PCB', keys: ['PCB'] },
  { label: 'PEEK材料', keys: ['PEEK'] },
  { label: '算力', keys: ['算力'] },
  { label: 'AI芯片', keys: ['AI芯片', '国产芯片'] },
  { label: '存储芯片', keys: ['存储芯片'] },
  { label: '先进封装', keys: ['先进封装'] },
  { label: '光刻机', keys: ['光刻'] },
  { label: '液冷', keys: ['液冷'] },
  { label: '低空经济', keys: ['低空'] },
  { label: '智能驾驶', keys: ['自动驾驶', '无人驾驶', '车联网', '智能座舱'] },
  { label: '储能', keys: ['储能', '钒电池', '熔盐储能'] },
  { label: '虚拟电厂', keys: ['虚拟电厂'] },
  { label: 'BC/HJT/TOPCon', keys: ['BC电池', 'HJT电池', 'TOPCon电池'] },
  { label: '一体化压铸', keys: ['一体化压铸'] },
  { label: 'AI眼镜', keys: ['AI眼镜'] },
  { label: '数据要素', keys: ['数据要素'] },
] as const

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

function renderSkeleton() {
  return <div style={{padding:24}}><Skeleton active paragraph={{rows:8}}/></div>
}

// ═══════════════════════════════════════════════════════════════════════════════
//  综合评分计算
// ═══════════════════════════════════════════════════════════════════════════════

function computeCompositeScore(ind: StockIndustryAgg, weights: {mom:number; flow:number; quality:number; val:number}): number {
  // Normalized weighted score (0-100)
  const wSum = weights.mom + weights.flow + weights.quality + weights.val
  const wm = weights.mom / wSum, wf = weights.flow / wSum, wq = weights.quality / wSum, wv = weights.val / wSum
  const momScore = Math.min(100, Math.max(0, ((ind.avg_momentum_20d ?? 0) + 10) * 5))
  const flowScore = Math.min(100, Math.max(0, ((ind.net_capital_flow_pct ?? 0) + 0.05) * 1000))
  const qualityScore = Math.min(100, Math.max(0, ((ind.avg_roe ?? 0) + (ind.avg_gpm ?? 0) / 5) * 4))
  const valScore = Math.min(100, Math.max(0, 100 - (ind.avg_pe ?? 50)))
  return Math.round(momScore * wm + flowScore * wf + qualityScore * wq + valScore * wv)
}

// ═══════════════════════════════════════════════════════════════════════════════
//  主组件
// ═══════════════════════════════════════════════════════════════════════════════

export default function SectorRotationStock() {
  const { token: themeToken } = antTheme.useToken()
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
  const chartText = isDark ? '#e0e0e0' : '#333'
  const chartAxis = isDark ? '#444' : '#e0e0e0'

  const [activeTab, setActiveTab] = useState('overview')
  const [data, setData] = useState<StockIndustriesResponse|null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string|null>(null)
  const [sortKey, setSortKey] = useState<string>('stock_count')
  const [topK, setTopK] = useState(30)
  const [searchText, setSearchText] = useState('')
  const [detailInd, setDetailInd] = useState<StockIndustryAgg|null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [showDataLayer, setShowDataLayer] = useState(false)
  // ── Concept tab (Tab 8) state ──
  const [conceptData, setConceptData] = useState<StockConceptsResponse|null>(null)
  const [conceptLoading, setConceptLoading] = useState(false)
  const [conceptSource, setConceptSource] = useState<StockConceptSource>('all')
  const [conceptMinCount, setConceptMinCount] = useState(5)
  const [conceptKeyword, setConceptKeyword] = useState('')
  const [conceptActiveChip, setConceptActiveChip] = useState<string>('all')
  const [detailConcept, setDetailConcept] = useState<StockConceptAgg|null>(null)
  const [detailConceptOpen, setDetailConceptOpen] = useState(false)
  // ── Event-driven data (Tab 8) ──
  const [northData, setNorthData] = useState<NorthResponse|null>(null)
  const [northLoading, setNorthLoading] = useState(false)
  const [marginData, setMarginData] = useState<MarginResponse|null>(null)
  const [marginLoading, setMarginLoading] = useState(false)
  const [lhbData, setLhbData] = useState<LhbResponse|null>(null)
  const [lhbLoading, setLhbLoading] = useState(false)
  const [blockTradeData, setBlockTradeData] = useState<BlockTradeResponse|null>(null)
  const [blockTradeLoading, setBlockTradeLoading] = useState(false)
  const [holderData, setHolderData] = useState<HolderNumResponse|null>(null)
  const [holderLoading, setHolderLoading] = useState(false)
  const [forecastData, setForecastData] = useState<EarningsForecastResponse|null>(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [expressData, setExpressData] = useState<EarningsExpressResponse|null>(null)
  const [expressLoading, setExpressLoading] = useState(false)
  const [releaseData, setReleaseData] = useState<RestrictedReleaseResponse|null>(null)
  const [releaseLoading, setReleaseLoading] = useState(false)
  // ── Fund flow data (Tab 3) ──
  const [individualFundFlowData, setIndividualFundFlowData] = useState<IndividualFundFlowResponse|null>(null)
  const [individualFundFlowLoading, setIndividualFundFlowLoading] = useState(false)
  const [industryFundFlowData, setIndustryFundFlowData] = useState<IndustryFundFlowResponse|null>(null)
  const [industryFundFlowLoading, setIndustryFundFlowLoading] = useState(false)
  const [mainFundFlowData, setMainFundFlowData] = useState<MainFundFlowResponse|null>(null)
  const [mainFundFlowLoading, setMainFundFlowLoading] = useState(false)
  const [turnoverRankData, setTurnoverRankData] = useState<TurnoverRankResponse|null>(null)
  const [turnoverRankLoading, setTurnoverRankLoading] = useState(false)
  const [hsgtFundFlowData, setHsgtFundFlowData] = useState<HsgtFundFlowResponse|null>(null)
  const [hsgtFundFlowLoading, setHsgtFundFlowLoading] = useState(false)
  // Configurable composite score weights
  const [weights, setWeights] = useState({mom:40, flow:25, quality:20, val:15})
  // Track momentum table sort for export sync
  const [momentumSorter, setMomentumSorter] = useState<{field:string; order:'ascend'|'descend'}>({field:'avg_momentum_20d', order:'descend'})
  // ── Recommendation tab state ──
  const [recommendData, setRecommendData] = useState<IndustryRecommendations|null>(null)
  const [recLoading, setRecLoading] = useState(false)
  const [aiLoading, setAiLoading] = useState<string|null>(null)  // 'industry:horizon'
  const [aiInsight, setAiInsight] = useState<Record<string,string>>({})
  const [historyData, setHistoryData] = useState<RecHistoryResponse|null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [accuracyData, setAccuracyData] = useState<RecAccuracyResponse|null>(null)
  const [accuracyLoading, setAccuracyLoading] = useState(false)
  const [recSubTab, setRecSubTab] = useState('current')
  // Horizon-specific factor weights (percentages, will be normalized to sum=1)
  const [horizonWeights, setHorizonWeights] = useState({
    short_term: { momentum: 60, flow: 25, turnover: 15 },
    mid_term:   { momentum: 50, trend_confirm: 20, flow: 20, quality: 10 },
    long_term:  { momentum: 40, long_trend: 25, quality: 20, gpm: 10, valuation: 5 },
  })

  // Memoized industry table data
  const industryTableData = useMemo(() => (data?.industries??[]).map((i,idx)=>({...i,key:idx})), [data])

  useEffect(()=>{
    if(!data && !loading) loadData()
  },[])

  // Lazy-load concept data only when the user opens Tab 8
  useEffect(()=>{
    if(activeTab==='concepts' && !conceptData && !conceptLoading) loadConcepts()
  },[activeTab])

  // Lazy-load recommendations when user opens the tab
  useEffect(()=>{
    if(activeTab==='recommend' && !recommendData && !recLoading) loadRecommendations()
    if(activeTab==='recommend' && !historyData && !historyLoading) loadHistory()
    if(activeTab==='recommend' && !accuracyData && !accuracyLoading) loadAccuracy()
  },[activeTab])

  const loadHistory=async()=>{
    setHistoryLoading(true)
    try{
      const resp = await fetchRecHistory(30)
      setHistoryData(resp)
    }catch(e:any){message.error('历史数据加载失败')}
    finally{setHistoryLoading(false)}
  }

  const loadAccuracy=async()=>{
    setAccuracyLoading(true)
    try{
      const resp = await fetchRecAccuracy(30)
      setAccuracyData(resp)
    }catch(e:any){message.error('准确率加载失败')}
    finally{setAccuracyLoading(false)}
  }

  const loadRecommendations=async()=>{
    if(data?.recommendations && !recLoading){
      setRecommendData(data.recommendations)
      return
    }
    setRecLoading(true)
    try{
      // Build weights_json from current horizonWeights (normalize each horizon to sum=1)
      const normalizedWeights: Record<string,Record<string,number>> = {}
      for (const [h, factors] of Object.entries(horizonWeights)) {
        const sum = Object.values(factors).reduce((a,b)=>a+b, 0)
        if (sum === 0) {
          message.warning(h==='short_term'?'短期权重全为0，已跳过':h==='mid_term'?'中期权重全为0，已跳过':'长期权重全为0，已跳过')
          continue
        }
        normalizedWeights[h] = {}
        for (const [k, v] of Object.entries(factors)) {
          normalizedWeights[h][k] = v / sum
        }
      }
      const weightsJson = JSON.stringify(normalizedWeights)
      const resp = await fetchIndustryRecommendations('all', 5, weightsJson)
      setRecommendData({short_term:resp.short_term??[],mid_term:resp.mid_term??[],long_term:resp.long_term??[],generated_at:resp.generated_at})
    }catch(e:any){message.error('推荐数据加载失败: '+e.message)}
    finally{setRecLoading(false)}
  }

  const handleAIInsight=async(industry:string, horizon:string, metrics:IndustryRecommendation['metrics'])=>{
    const key = industry+':'+horizon
    if(aiInsight[key]) return
    setAiLoading(key)
    try{
      const horizonLabel = horizon==='short_term'?'短期(1周内)':horizon==='mid_term'?'中期(2周)':'长期(1月)'
      const question = '请用2-3句简洁中文分析"'+industry+'"行业在'+horizonLabel+'的投资机会和风险。'
      const resp = await fetchAIInsight({type:'market',context:{industry,horizon,metrics},question,language:'zh'})
      const text = resp.summary || (resp.insights||[]).join('；') || (resp.recommendations||[]).join('；') || JSON.stringify(resp)
      setAiInsight(prev=>({...prev,[key]:text}))
    }catch(e:any){setAiInsight(prev=>({...prev,[key]:'AI解读暂不可用: '+e.message}))}
    finally{setAiLoading(null)}
  }

  const loadData=async()=>{
    setLoading(true); setError(null)
    try{
      const d=await fetchStockIndustries(); setData(d)
    }catch(e:any){setError(e.message||'加载失败')}
    finally{setLoading(false)}
  }

  const loadConcepts=async()=>{
    setConceptLoading(true)
    try{
      const d=await fetchStockConcepts({ source: conceptSource, minCount: conceptMinCount })
      setConceptData(d)
    }catch(e:any){message.error(`加载概念失败: ${e?.message||e}`)}
    finally{setConceptLoading(false)}
  }

  // Lazy-load event-driven data when user opens Tab 8
  useEffect(() => {
    if (activeTab !== 'events') return
    if (!northData && !northLoading) loadNorth()
    if (!marginData && !marginLoading) loadMargin()
    if (!lhbData && !lhbLoading) loadLhb()
    if (!blockTradeData && !blockTradeLoading) loadBlockTrade()
    if (!holderData && !holderLoading) loadHolder()
    if (!forecastData && !forecastLoading) loadForecast()
    if (!expressData && !expressLoading) loadExpress()
    if (!releaseData && !releaseLoading) loadRelease()
  }, [activeTab])

  // Lazy-load fund flow data when user opens Tab 3
  useEffect(() => {
    if (activeTab !== 'flow') return
    if (!individualFundFlowData && !individualFundFlowLoading) loadIndividualFundFlow()
    if (!industryFundFlowData && !industryFundFlowLoading) loadIndustryFundFlow()
    if (!mainFundFlowData && !mainFundFlowLoading) loadMainFundFlow()
    if (!turnoverRankData && !turnoverRankLoading) loadTurnoverRank()
    if (!hsgtFundFlowData && !hsgtFundFlowLoading) loadHsgtFundFlow()
  }, [activeTab])

  // Auto-refresh fund flow data every 30s while Tab 3 is active
  useEffect(() => {
    if (activeTab !== 'flow') return
    const id = setInterval(() => {
      loadIndividualFundFlow()
      loadIndustryFundFlow()
      loadMainFundFlow()
      loadTurnoverRank()
      loadHsgtFundFlow()
    }, 30000)
    return () => clearInterval(id)
  }, [activeTab])

  // Refetch when source or min_count changes
  useEffect(()=>{
    if(activeTab==='concepts') loadConcepts()
  },[conceptSource, conceptMinCount])

  // ── Event-driven data loaders ──
  const loadNorth = async () => {
    setNorthLoading(true)
    try { const d = await fetchNorthCapital(); setNorthData(d) }
    catch(e:any){ message.error(`北向资金加载失败: ${e?.message||e}`) }
    finally{ setNorthLoading(false) }
  }
  const loadMargin = async () => {
    setMarginLoading(true)
    try { const d = await fetchMarginStocks(); setMarginData(d) }
    catch(e:any){ message.error(`融资融券加载失败: ${e?.message||e}`) }
    finally{ setMarginLoading(false) }
  }
  const loadLhb = async () => {
    setLhbLoading(true)
    try { const d = await fetchLhb(); setLhbData(d) }
    catch(e:any){ message.error(`龙虎榜加载失败: ${e?.message||e}`) }
    finally{ setLhbLoading(false) }
  }
  const loadBlockTrade = async () => {
    setBlockTradeLoading(true)
    try { const d = await fetchBlockTrade(); setBlockTradeData(d) }
    catch(e:any){ message.error(`大宗交易加载失败: ${e?.message||e}`) }
    finally{ setBlockTradeLoading(false) }
  }
  const loadHolder = async () => {
    setHolderLoading(true)
    try { const d = await fetchHolderNum(); setHolderData(d) }
    catch(e:any){ message.error(`股东户数加载失败: ${e?.message||e}`) }
    finally{ setHolderLoading(false) }
  }
  const loadForecast = async () => {
    setForecastLoading(true)
    try { const d = await fetchEarningsForecast(); setForecastData(d) }
    catch(e:any){ message.error(`业绩预告加载失败: ${e?.message||e}`) }
    finally{ setForecastLoading(false) }
  }
  const loadExpress = async () => {
    setExpressLoading(true)
    try { const d = await fetchEarningsExpress(); setExpressData(d) }
    catch(e:any){ message.error(`业绩快报加载失败: ${e?.message||e}`) }
    finally{ setExpressLoading(false) }
  }
  const loadRelease = async () => {
    setReleaseLoading(true)
    try { const d = await fetchRestrictedRelease(); setReleaseData(d) }
    catch(e:any){ message.error(`限售解禁加载失败: ${e?.message||e}`) }
    finally{ setReleaseLoading(false) }
  }

  // ── Fund flow data loaders ──
  const loadIndividualFundFlow = async () => {
    setIndividualFundFlowLoading(true)
    try { const d = await fetchIndividualFundFlow('今日', 200); setIndividualFundFlowData(d) }
    catch(e:any){ message.error(`个股资金流向加载失败: ${e?.message||e}`) }
    finally{ setIndividualFundFlowLoading(false) }
  }
  const loadIndustryFundFlow = async () => {
    setIndustryFundFlowLoading(true)
    try { const d = await fetchIndustryFundFlow('今日'); setIndustryFundFlowData(d) }
    catch(e:any){ message.error(`行业资金流向加载失败: ${e?.message||e}`) }
    finally{ setIndustryFundFlowLoading(false) }
  }
  const loadMainFundFlow = async () => {
    setMainFundFlowLoading(true)
    try { const d = await fetchMainFundFlow(200); setMainFundFlowData(d) }
    catch(e:any){ message.error(`主力资金流向加载失败: ${e?.message||e}`) }
    finally{ setMainFundFlowLoading(false) }
  }
  const loadTurnoverRank = async () => {
    setTurnoverRankLoading(true)
    try { const d = await fetchTurnoverRank(100); setTurnoverRankData(d) }
    catch(e:any){ message.error(`换手率排名加载失败: ${e?.message||e}`) }
    finally{ setTurnoverRankLoading(false) }
  }
  const loadHsgtFundFlow = async () => {
    setHsgtFundFlowLoading(true)
    try { const d = await fetchHsgtFundFlow(); setHsgtFundFlowData(d) }
    catch(e:any){ message.error(`沪深港通资金流向加载失败: ${e?.message||e}`) }
    finally{ setHsgtFundFlowLoading(false) }
  }

  // ── Sorted & filtered industries ──
  const sortedIndustries = useMemo(()=>{
    let list = [...(data?.industries??[])]
    if(searchText){
      const kw=searchText.toLowerCase()
      list=list.filter(i=>i.industry.toLowerCase().includes(kw))
    }
    const isDescKey = ['stock_count','avg_momentum_20d','avg_roe','net_capital_flow','avg_gpm','avg_turnover_rate','composite'].includes(sortKey)
    if(sortKey==='composite'){
      list.sort((a,b)=>isDescKey
        ? computeCompositeScore(b,weights)-computeCompositeScore(a,weights)
        : computeCompositeScore(a,weights)-computeCompositeScore(b,weights))
    }else{
      list.sort((a,b)=>{
        const va=(a[sortKey as keyof StockIndustryAgg] as number)||0
        const vb=(b[sortKey as keyof StockIndustryAgg] as number)||0
        return isDescKey ? vb-va : va-vb
      })
    }
    return list.slice(0, topK)
  },[data, sortKey, topK, searchText, weights])

  const avgChange = useMemo(()=>{
    const all=sortedIndustries.filter(i=>i.avg_stock_change_pct!=null)
    return all.length?all.reduce((s,i)=>s+i.avg_stock_change_pct,0)/all.length:0
  },[sortedIndustries])

  // ═════════════════════════════════════════════════════════════════════════════
  //  Chart Options
  // ═════════════════════════════════════════════════════════════════════════════

  // 1. Stock count by industry
  const stockCountChartOption=useMemo(()=>{
    const items=sortedIndustries.slice(0,25)
    return {
      tooltip:{trigger:'axis',axisPointer:{type:'shadow'}},
      grid:{left:100,right:30,top:8,bottom:24},
      xAxis:{type:'value',splitLine:{lineStyle:{color:chartAxis}}},
      yAxis:{type:'category',data:items.map(i=>i.industry).reverse(),axisLabel:{fontSize:10,color:chartText}},
      series:[{type:'bar',data:items.map((i,idx)=>({value:i.stock_count,itemStyle:{color:indColor(i.industry),borderRadius:[0,4,4,0]}})),barWidth:'60%',
        label:{show:true,position:'right',fontSize:10,formatter:(p:any)=>p.value+'只'}
      }]
    }
  },[sortedIndustries,chartText,chartAxis])

  // 2. Industry pie chart
  const industryPieOption=useMemo(()=>{
    const items=sortedIndustries.slice(0,12)
    return {
      tooltip:{trigger:'item',formatter:'{b}: {c}只 ({d}%)'},
      series:[{type:'pie',radius:['35%','70%'],itemStyle:{borderRadius:6,borderColor:isDark?'#1f1f1f':'#fff',borderWidth:2},
        label:{show:true,fontSize:10,color:chartText,formatter:'{b}\\n{d}%'},
        data:items.map(i=>({name:i.industry,value:i.stock_count,itemStyle:{color:indColor(i.industry)}}))
      }]
    }
  },[sortedIndustries,chartText,isDark])

  // 3. Momentum heatmap (4 periods)
  const momentumHeatmapOption=useMemo(()=>{
    const top=[...sortedIndustries].sort((a,b)=>(b.avg_momentum_20d??0)-(a.avg_momentum_20d??0)).slice(0,18)
    return {
      tooltip:{formatter:(p:any)=>`${p.value[1]}: ${['5日','10日','20日','60日'][p.value[0]]}动量 = ${p.value[2].toFixed(1)}%`},
      grid:{left:90,right:60,top:8,bottom:50},
      xAxis:{type:'category',data:['5日','10日','20日','60日'],axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      visualMap:{min:-10,max:10,calculable:true,orient:'horizontal',left:'center',bottom:0,inRange:{color:['#52c41a','#fafafa','#ff4d4f']},textStyle:{color:chartText}},
      series:[{type:'heatmap',data:top.flatMap((i,idx)=>[[0,idx,i.avg_momentum_5d??0],[1,idx,i.avg_momentum_10d??0],[2,idx,i.avg_momentum_20d??0],[3,idx,i.avg_momentum_60d??0]]),
        label:{show:true,fontSize:9,formatter:(p:any)=>(p.value[2]>0?'+':'')+p.value[2].toFixed(1)},emphasis:{itemStyle:{shadowBlur:8}}}]
    }
  },[sortedIndustries,chartText])

  // 4. Momentum dispersion chart
  const dispersionChartOption=useMemo(()=>{
    const top=[...sortedIndustries].filter(i=>i.momentum_dispersion>0).sort((a,b)=>b.momentum_dispersion-a.momentum_dispersion).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'动量分散度',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[{type:'bar',data:top.map(i=>({value:i.momentum_dispersion,itemStyle:{color:i.momentum_dispersion>=8?'#ff4d4f':i.momentum_dispersion>=4?'#faad14':'#52c41a',borderRadius:4}})),barWidth:'55%'}]
    }
  },[sortedIndustries,chartText])

  // 5. Capital flow chart
  // 5. Fund flow chart — prefer AKShare industry fund flow API data
  const flowChartOption=useMemo(()=>{
    // Use industry fund flow API data if available (real-time from 东方财富)
    if(industryFundFlowData && industryFundFlowData.industries.length>0){
      const top=[...industryFundFlowData.industries].sort((a,b)=>Math.abs(b.net_inflow??0)-Math.abs(a.net_inflow??0)).slice(0,15)
      return {
        tooltip:{trigger:'axis',valueFormatter:(v:any)=>{const val=v?.value??v;return fmtFlow(typeof val==='number'?val:0)}},
        title:{text:'实时行业资金净流入',subtext:'数据源: 东方财富',textStyle:{fontSize:13,color:chartText},subtextStyle:{fontSize:10,color:'#999'},left:'center',top:0},
        grid:{left:100,right:40,top:36,bottom:24},
        xAxis:{type:'value',axisLabel:{color:chartText}},
        yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
        series:[{type:'bar',data:top.map(i=>({value:i.net_inflow,itemStyle:{color:(i.net_inflow??0)>=0?'#ff4d4f':'#52c41a',borderRadius:4}})),barWidth:'55%'}]
      }
    }
    // Fallback to aggregated data from stock industries
    const top=[...sortedIndustries].sort((a,b)=>Math.abs(b.net_capital_flow??0)-Math.abs(a.net_capital_flow??0)).slice(0,15)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>{const val=v?.value??v;return fmtFlow(typeof val==='number'?val:0)}},
      grid:{left:100,right:40,top:8,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:11}},
      series:[{type:'bar',data:top.map(i=>({value:i.net_capital_flow,itemStyle:{color:(i.net_capital_flow??0)>=0?'#ff4d4f':'#52c41a',borderRadius:4}})),barWidth:'55%'}]
    }
  },[sortedIndustries,industryFundFlowData,chartText])

  // 6. Super/Big flow breakdown — prefer AKShare main fund flow API
  const flowBreakdownOption=useMemo(()=>{
    // Use industry fund flow API data if available
    if(industryFundFlowData && industryFundFlowData.industries.length>0){
      const top=[...industryFundFlowData.industries].sort((a,b)=>Math.abs(b.net_inflow??0)-Math.abs(a.net_inflow??0)).slice(0,12)
      return {
        tooltip:{trigger:'axis',valueFormatter:(v:any)=>fmtFlow(v)},
        title:{text:'行业资金流入/流出拆分',subtext:'数据源: 东方财富',textStyle:{fontSize:13,color:chartText},subtextStyle:{fontSize:10,color:'#999'},left:'center',top:0},
        grid:{left:100,right:40,top:36,bottom:24},
        xAxis:{type:'value',axisLabel:{color:chartText}},
        yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
        series:[
          {name:'流入资金',type:'bar',stack:'flow',data:top.map(i=>i.inflow??0).reverse(),itemStyle:{color:'#ff4d4f',borderRadius:0}},
          {name:'流出资金',type:'bar',stack:'flow',data:top.map(i=>-(i.outflow??0)).reverse(),itemStyle:{color:'#52c41a',borderRadius:0}},
        ]
      }
    }
    // Fallback to aggregated data
    const top=[...sortedIndustries].sort((a,b)=>Math.abs(b.net_capital_flow??0)-Math.abs(a.net_capital_flow??0)).slice(0,12)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>fmtFlow(v)},
      grid:{left:100,right:40,top:8,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[
        {name:'超大单',type:'bar',stack:'flow',data:top.map(i=>i.net_super_flow??0).reverse(),itemStyle:{color:'#ff4d4f',borderRadius:0}},
        {name:'大单',type:'bar',stack:'flow',data:top.map(i=>i.net_big_flow??0).reverse(),itemStyle:{color:'#fa8c16',borderRadius:0}},
      ]
    }
  },[sortedIndustries,industryFundFlowData,chartText])

  // 6b. Main fund flow chart (主力资金拆分 — 超大单/大单/中单/小单)
  const mainFundFlowChartOption=useMemo(()=>{
    if(!mainFundFlowData || mainFundFlowData.stocks.length===0) return null
    const top20=mainFundFlowData.stocks.slice(0,20)
    const isEstimated = mainFundFlowData.stocks[0]?.is_estimated !== false
    const subtext = isEstimated ? '数据源: 东方财富 (比例估算)' : '数据源: 东方财富 (真实拆分)'
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>fmtFlow(v)},
      title:{text:'个股主力资金拆分 TOP20',subtext,textStyle:{fontSize:13,color:chartText},subtextStyle:{fontSize:10,color:isEstimated?'#faad14':'#52c41a'},left:'center',top:0},
      legend:{data:['超大单','大单','中单','小单'],top:22,textStyle:{color:chartText,fontSize:10}},
      grid:{left:80,right:20,top:50,bottom:24},
      xAxis:{type:'value',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top20.map(i=>i.name).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[
        {name:'超大单',type:'bar',stack:'flow',data:top20.map(i=>i.super_large_net??0).reverse(),itemStyle:{color:'#ff4d4f'}},
        {name:'大单',type:'bar',stack:'flow',data:top20.map(i=>i.large_net??0).reverse(),itemStyle:{color:'#fa8c16'}},
        {name:'中单',type:'bar',stack:'flow',data:top20.map(i=>i.medium_net??0).reverse(),itemStyle:{color:'#1890ff'}},
        {name:'小单',type:'bar',stack:'flow',data:top20.map(i=>i.small_net??0).reverse(),itemStyle:{color:'#52c41a'}},
      ]
    }
  },[mainFundFlowData,chartText])

  // 7. Turnover rate chart — prefer AKShare individual fund flow API
  const turnoverChartOption=useMemo(()=>{
    // Use turnover rank API data if available (individual stock level)
    if(turnoverRankData && turnoverRankData.stocks.length>0){
      const top=turnoverRankData.stocks.slice(0,25)
      return {
        tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
        title:{text:'个股换手率排名 TOP25',subtext:'数据源: 东方财富',textStyle:{fontSize:13,color:chartText},subtextStyle:{fontSize:10,color:'#999'},left:'center',top:0},
        grid:{left:80,right:20,top:36,bottom:24},
        xAxis:{type:'value',name:'换手率(%)',axisLabel:{color:chartText}},
        yAxis:{type:'category',data:top.map(i=>i.name).reverse(),axisLabel:{color:chartText,fontSize:10}},
        series:[{type:'bar',data:top.map(i=>({value:i.turnover_rate,itemStyle:{color:i.turnover_rate>=20?'#ff4d4f':i.turnover_rate>=10?'#faad14':i.turnover_rate>=5?'#1890ff':'#52c41a',borderRadius:4}})),barWidth:'50%'}]
      }
    }
    // Fallback to aggregated data
    const top=[...sortedIndustries].sort((a,b)=>(b.avg_turnover_rate??0)-(a.avg_turnover_rate??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'换手率(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_turnover_rate,itemStyle:{color:i.avg_turnover_rate>=5?'#ff4d4f':i.avg_turnover_rate>=3?'#faad14':'#52c41a',borderRadius:4}})),barWidth:'50%'}]
    }
  },[sortedIndustries,turnoverRankData,chartText])

  // 8. Valuation scatter (PE vs PB)
  const valuationScatterOption=useMemo(()=>{
    const items=sortedIndustries.filter(i=>i.avg_pe>0&&i.avg_pb>0)
    return {
      tooltip:{formatter:(p:any)=>`${p.data[3]}<br/>PE: ${p.data[0].toFixed(1)}<br/>PB: ${p.data[1].toFixed(1)}<br/>股票: ${p.data[2]}只`},
      grid:{left:60,right:30,top:30,bottom:40},
      xAxis:{type:'value',name:'PE(TTM)',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
      yAxis:{type:'value',name:'PB',axisLabel:{color:chartText},splitLine:{lineStyle:{color:chartAxis}}},
      series:[{type:'scatter',symbolSize:(d:any)=>Math.max(8,Math.min(40,d[2]*1.5)),
        data:items.map(i=>[i.avg_pe,i.avg_pb,i.stock_count,i.industry]),
        label:{show:true,formatter:(p:any)=>p.data[3],position:'right',fontSize:9,color:chartText},
        itemStyle:{color:(p:any)=>indColor(p.data[3])+'cc',borderRadius:4}
      }]
    }
  },[sortedIndustries,chartText,chartAxis])

  // 9. ROE chart
  const roeChartOption=useMemo(()=>{
    const top=[...sortedIndustries].filter(i=>i.stock_count>=2).sort((a,b)=>(b.avg_roe??0)-(a.avg_roe??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'ROE(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_roe,itemStyle:{color:i.avg_roe>=12?'#52c41a':i.avg_roe>=6?'#faad14':'#ff4d4f',borderRadius:4}})),barWidth:'50%',
        markLine:{data:[{name:'市场均值',xAxis:8,lineStyle:{color:'#722ed1',type:'dashed'},label:{formatter:'8%',color:'#722ed1'}}]}
      }]
    }
  },[sortedIndustries,chartText])

  // 10. GPM + CAGR chart
  const qualityChartOption=useMemo(()=>{
    const top=[...sortedIndustries].filter(i=>i.stock_count>=2).slice(0,15)
    return {
      tooltip:{trigger:'axis'},
      legend:{data:['毛利率(%)','CAGR(%)'],textStyle:{color:chartText}},
      grid:{left:100,right:20,top:30,bottom:24},
      xAxis:{type:'category',data:top.map(i=>i.industry),axisLabel:{color:chartText,fontSize:9,rotate:30}},
      yAxis:{type:'value',axisLabel:{color:chartText}},
      series:[
        {name:'毛利率(%)',type:'bar',data:top.map(i=>i.avg_gpm??0),itemStyle:{color:'#52c41a',borderRadius:4}},
        {name:'CAGR(%)',type:'line',data:top.map(i=>i.avg_cagr??0),lineStyle:{color:'#722ed1'},itemStyle:{color:'#722ed1'}},
      ]
    }
  },[sortedIndustries,chartText])

  // 11. IV chart
  const ivChartOption=useMemo(()=>{
    const top=[...sortedIndustries].filter(i=>i.avg_iv>0).sort((a,b)=>(b.avg_iv??0)-(a.avg_iv??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'隐含波动率(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_iv,itemStyle:{color:i.avg_iv>=40?'#ff4d4f':i.avg_iv>=25?'#faad14':'#52c41a',borderRadius:4}})),barWidth:'50%'}]
    }
  },[sortedIndustries,chartText])

  // 12. Pledge ratio chart
  const pledgeChartOption=useMemo(()=>{
    const top=[...sortedIndustries].filter(i=>i.avg_pledge_ratio>0).sort((a,b)=>(b.avg_pledge_ratio??0)-(a.avg_pledge_ratio??0)).slice(0,20)
    return {
      tooltip:{trigger:'axis',valueFormatter:(v:any)=>v+'%'},
      grid:{left:100,right:20,top:8,bottom:24},
      xAxis:{type:'value',name:'质押比例(%)',axisLabel:{color:chartText}},
      yAxis:{type:'category',data:top.map(i=>i.industry).reverse(),axisLabel:{color:chartText,fontSize:10}},
      series:[{type:'bar',data:top.map(i=>({value:i.avg_pledge_ratio,itemStyle:{color:i.avg_pledge_ratio>=30?'#ff4d4f':i.avg_pledge_ratio>=15?'#faad14':'#52c41a',borderRadius:4}})),barWidth:'50%'}]
    }
  },[sortedIndustries,chartText])

  // ═════════════════════════════════════════════════════════════════════════════
  //  Table Columns
  // ═════════════════════════════════════════════════════════════════════════════

  const indColumns = [
    { title:'行业', dataIndex:'industry', key:'industry', width:100, fixed:'left' as const,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>a.industry.localeCompare(b.industry,'zh'),
      render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
    { title:'股票数', dataIndex:'stock_count', key:'stock_count', width:70, sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>a.stock_count-b.stock_count},
    { title:'涨跌幅', dataIndex:'avg_stock_change_pct', key:'avg_stock_change_pct', width:90,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_stock_change_pct??0)-(b.avg_stock_change_pct??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'5日动量', dataIndex:'avg_momentum_5d', key:'avg_momentum_5d', width:85,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_5d??0)-(b.avg_momentum_5d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'10日动量', dataIndex:'avg_momentum_10d', key:'avg_momentum_10d', width:85,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_10d??0)-(b.avg_momentum_10d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'20日动量', dataIndex:'avg_momentum_20d', key:'avg_momentum_20d', width:85,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'60日动量', dataIndex:'avg_momentum_60d', key:'avg_momentum_60d', width:85,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_60d??0)-(b.avg_momentum_60d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'动量分散度', dataIndex:'momentum_dispersion', key:'momentum_dispersion', width:100,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.momentum_dispersion??0)-(b.momentum_dispersion??0),
      render:(v:number)=><span style={{color:v>=8?'#ff4d4f':v>=4?'#faad14':'#52c41a'}}>{fmt(v)}</span>},
    { title:'ROE', dataIndex:'avg_roe', key:'avg_roe', width:70,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_roe??0)-(b.avg_roe??0),
      render:(v:number)=><span style={{color:v>=12?'#52c41a':v>=6?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'PE', dataIndex:'avg_pe', key:'avg_pe', width:70,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_pe??0)-(b.avg_pe??0),
      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
    { title:'PB', dataIndex:'avg_pb', key:'avg_pb', width:70,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_pb??0)-(b.avg_pb??0),
      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
    { title:'毛利率', dataIndex:'avg_gpm', key:'avg_gpm', width:75,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_gpm??0)-(b.avg_gpm??0),
      render:(v:number)=><span style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'CAGR', dataIndex:'avg_cagr', key:'avg_cagr', width:70,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_cagr??0)-(b.avg_cagr??0),
      render:(v:number)=><span style={{color:v>=10?'#52c41a':v>=0?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'负债率', dataIndex:'avg_debt_ratio', key:'avg_debt_ratio', width:75,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_debt_ratio??0)-(b.avg_debt_ratio??0),
      render:(v:number)=><span style={{color:v>=60?'#ff4d4f':v>=40?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'换手率', dataIndex:'avg_turnover_rate', key:'avg_turnover_rate', width:75,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),
      render:(v:number)=><span>{fmt(v)}%</span>},
    { title:'主力资金', dataIndex:'net_capital_flow', key:'net_capital_flow', width:100,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.net_capital_flow??0)-(b.net_capital_flow??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</span>},
    { title:'IV', dataIndex:'avg_iv', key:'avg_iv', width:70,
      render:(v:number)=><span style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'质押率', dataIndex:'avg_pledge_ratio', key:'avg_pledge_ratio', width:75,
      render:(v:number)=><span style={{color:v>=30?'#ff4d4f':v>=15?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'综合评分', key:'composite', width:90, fixed:'right' as const,
      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>computeCompositeScore(a,weights)-computeCompositeScore(b,weights),
      render:(_:any,r:StockIndustryAgg)=>{
        const score=computeCompositeScore(r,weights)
        return <Tag color={score>=70?'#52c41a':score>=40?'#faad14':'#ff4d4f'} style={{fontWeight:700,minWidth:48,textAlign:'center'}}>{score}</Tag>
      }},
    { title:'涨/跌', key:'ud', width:70, fixed:'right' as const,
      sorter:(a:any,b:any)=>(a.up_count??0)-(b.up_count??0),
      render:(_:any,r:StockIndustryAgg)=><span><span style={{color:'#ff4d4f'}}>{r.up_count}</span>/<span style={{color:'#52c41a'}}>{r.down_count}</span></span>},
  ]

  // Stock detail columns (for Modal)
  const stockColumns = [
    { title:'代码', dataIndex:'stock_code', key:'stock_code', width:80,
      sorter:(a:any,b:any)=>a.stock_code?.localeCompare?.(b.stock_code,'zh')??0},
    { title:'名称', dataIndex:'stock_name', key:'stock_name', width:80,
      sorter:(a:any,b:any)=>a.stock_name?.localeCompare?.(b.stock_name,'zh')??0},
    { title:'股价', dataIndex:'stock_price', key:'stock_price', width:70,
      sorter:(a:any,b:any)=>(a.stock_price??0)-(b.stock_price??0),
      render:(v:number)=><span style={{fontWeight:600}}>{fmt(v)}</span>},
    { title:'涨跌幅', dataIndex:'stock_change_pct', key:'stock_change_pct', width:80,
      sorter:(a:any,b:any)=>(a.stock_change_pct??0)-(b.stock_change_pct??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'PE', dataIndex:'pe', key:'pe', width:60,
      sorter:(a:any,b:any)=>(a.pe??0)-(b.pe??0),
      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
    { title:'PB', dataIndex:'pb', key:'pb', width:60,
      sorter:(a:any,b:any)=>(a.pb??0)-(b.pb??0),
      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
    { title:'ROE', dataIndex:'roe', key:'roe', width:60,
      sorter:(a:any,b:any)=>(a.roe??0)-(b.roe??0),
      render:(v:number)=><span style={{color:v>=12?'#52c41a':v>=6?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'毛利率', dataIndex:'gpm', key:'gpm', width:65,
      sorter:(a:any,b:any)=>(a.gpm??0)-(b.gpm??0),
      render:(v:number)=><span style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'5日动量', dataIndex:'momentum_5d', key:'momentum_5d', width:80,
      sorter:(a:any,b:any)=>(a.momentum_5d??0)-(b.momentum_5d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'10日动量', dataIndex:'momentum_10d', key:'momentum_10d', width:80,
      sorter:(a:any,b:any)=>(a.momentum_10d??0)-(b.momentum_10d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'20日动量', dataIndex:'momentum_20d', key:'momentum_20d', width:80,
      sorter:(a:any,b:any)=>(a.momentum_20d??0)-(b.momentum_20d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'60日动量', dataIndex:'momentum_60d', key:'momentum_60d', width:80,
      sorter:(a:any,b:any)=>(a.momentum_60d??0)-(b.momentum_60d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'换手率', dataIndex:'turnover_rate', key:'turnover_rate', width:70,
      sorter:(a:any,b:any)=>(a.turnover_rate??0)-(b.turnover_rate??0),
      render:(v:number)=><span>{fmt(v)}%</span>},
    { title:'主力资金', dataIndex:'net_capital_flow', key:'net_capital_flow', width:90,
      sorter:(a:any,b:any)=>(a.net_capital_flow??0)-(b.net_capital_flow??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtFlow(v)}</span>},
    { title:'资金占比', dataIndex:'net_capital_flow_pct', key:'net_capital_flow_pct', width:75,
      sorter:(a:any,b:any)=>(a.net_capital_flow_pct??0)-(b.net_capital_flow_pct??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'负债率', dataIndex:'debt_ratio', key:'debt_ratio', width:70,
      sorter:(a:any,b:any)=>(a.debt_ratio??0)-(b.debt_ratio??0),
      render:(v:number)=><span style={{color:v>=60?'#ff4d4f':v>=40?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'质押率', dataIndex:'pledge_ratio', key:'pledge_ratio', width:70,
      sorter:(a:any,b:any)=>(a.pledge_ratio??0)-(b.pledge_ratio??0),
      render:(v:number)=><span style={{color:v>=30?'#ff4d4f':v>=15?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'CAGR', dataIndex:'cagr', key:'cagr', width:65,
      sorter:(a:any,b:any)=>(a.cagr??0)-(b.cagr??0),
      render:(v:number)=><span style={{color:v>=10?'#52c41a':v>=0?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'IV', dataIndex:'iv', key:'iv', width:60,
      sorter:(a:any,b:any)=>(a.iv??0)-(b.iv??0),
      render:(v:number)=><span style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
  ]

  // ── Recommendation history sub-tab ──
  const renderRecHistoryTab = () => (
  <RecHistoryTable
    historyLoading={historyLoading}
    accuracyLoading={accuracyLoading}
    historyData={historyData}
    accuracyData={accuracyData}
    onLoadHistory={loadHistory}
    onLoadAccuracy={loadAccuracy}
  />
)
  // ── Detail modal ──
  const renderDetailModal = () => (
    <Modal title={detailInd?`${detailInd.industry} — 个股明细`:'行业个股明细'}
      open={detailOpen} onCancel={()=>setDetailOpen(false)} width={1100} footer={null}
      styles={{body:{padding:'12px 16px'}}}>
      {detailInd && (
        <div>
          <Row gutter={[12,12]} style={{marginBottom:12}}>
            <Col span={4}><Statistic title='股票数' value={detailInd.stock_count} suffix='只' valueStyle={{fontWeight:600}}/></Col>
            <Col span={4}><Statistic title='平均涨跌' value={fmtPct(detailInd.avg_stock_change_pct)} valueStyle={{color:(detailInd.avg_stock_change_pct??0)>=0?'#ff4d4f':'#52c41a'}} prefix={trendIcon(detailInd.avg_stock_change_pct)}/></Col>
            <Col span={4}><Statistic title='20日动量' value={fmtPct(detailInd.avg_momentum_20d)} valueStyle={{color:(detailInd.avg_momentum_20d??0)>=0?'#ff4d4f':'#52c41a'}}/></Col>
            <Col span={4}><Statistic title='ROE' value={fmt(detailInd.avg_roe)} suffix='%' valueStyle={{fontWeight:600}}/></Col>
            <Col span={4}><Statistic title='主力资金' value={fmtFlow(detailInd.net_capital_flow)} valueStyle={{color:(detailInd.net_capital_flow??0)>=0?'#ff4d4f':'#52c41a',fontWeight:700}}/></Col>
            <Col span={4}><Statistic title='综合评分' value={computeCompositeScore(detailInd,weights)} valueStyle={{fontWeight:700,color:computeCompositeScore(detailInd,weights)>=70?'#52c41a':'#faad14'}}/></Col>
          </Row>
          <Table dataSource={detailInd.stocks.map((s,i)=>({...s,key:i}))} columns={stockColumns}
            size='small' pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{x:1600,y:480}}/>
        </div>
      )}
    </Modal>
  )

  // ── Concept detail modal ──
  const renderConceptDetailModal = () => (
    <Modal title={detailConcept?`${detailConcept.concept} — 涵盖正股 (${detailConcept.sources.map(s=>s==='eastmoney'?'东财':'同花顺').join('+')})`:'概念正股明细'}
      open={detailConceptOpen} onCancel={()=>setDetailConceptOpen(false)} width={1200} footer={null}
      styles={{body:{padding:'12px 16px'}}}>
      {detailConcept && (
        <div>
          <Row gutter={[12,12]} style={{marginBottom:12}}>
            <Col span={4}><Statistic title='正股数' value={detailConcept.stock_count} suffix='只' valueStyle={{fontWeight:600,color:'#722ed1'}}/></Col>
            <Col span={4}><Statistic title='平均涨跌' value={fmtPct(detailConcept.avg_stock_change_pct)} valueStyle={{color:(detailConcept.avg_stock_change_pct??0)>=0?'#ff4d4f':'#52c41a'}} prefix={trendIcon(detailConcept.avg_stock_change_pct)}/></Col>
            <Col span={4}><Statistic title='20日动量' value={fmtPct(detailConcept.avg_momentum_20d)} valueStyle={{color:(detailConcept.avg_momentum_20d??0)>=0?'#ff4d4f':'#52c41a'}}/></Col>
            <Col span={4}><Statistic title='ROE' value={fmt(detailConcept.avg_roe)} suffix='%' valueStyle={{fontWeight:600}}/></Col>
            <Col span={4}><Statistic title='平均PE' value={detailConcept.avg_pe>0?fmt(detailConcept.avg_pe):'-'} valueStyle={{fontWeight:600}}/></Col>
            <Col span={4}><Statistic title='主力资金' value={fmtFlow(detailConcept.net_capital_flow)} valueStyle={{color:(detailConcept.net_capital_flow??0)>=0?'#ff4d4f':'#52c41a',fontWeight:700}}/></Col>
          </Row>
          <Table dataSource={(detailConcept.top_stocks ?? []).map((s,i)=>({...s,key:i}))} columns={stockColumns}
            size='small' pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{x:1600,y:360}}/>
        </div>
      )}
    </Modal>
  )

  // ── Composite ranking table ──
  const compositeData = useMemo(()=>{
    return [...(data?.industries??[])].map(i=>({
      ...i,
      composite: computeCompositeScore(i,weights),
      rank: 0,
    })).sort((a,b)=>b.composite-a.composite).map((i,idx)=>({...i,rank:idx+1}))
  },[data,weights])

  // ═════════════════════════════════════════════════════════════════════════════
  //  Concept tab (Tab 8) — filtered lists + chart options
  // ═════════════════════════════════════════════════════════════════════════════

  const filteredConcepts = useMemo(() => {
    let list = [...(conceptData?.concepts ?? [])]
    // 1. chip filter (细粒度概念快选)
    if (conceptActiveChip !== 'all') {
      const chip = FINE_GRAINED_CONCEPTS.find(c => c.label === conceptActiveChip)
      if (chip) {
        list = list.filter(c => chip.keys.some(k => c.concept.includes(k)))
      }
    }
    // 2. keyword filter
    if (conceptKeyword.trim()) {
      const kw = conceptKeyword.trim().toLowerCase()
      list = list.filter(c => c.concept.toLowerCase().includes(kw))
    }
    return list.sort((a, b) => b.stock_count - a.stock_count)
  }, [conceptData, conceptActiveChip, conceptKeyword])

  const conceptChartOption = useMemo(() => {
    // 按正股数排序，正股数相同时按20日动量排序
    const sorted = [...filteredConcepts].sort((a, b) => {
      if (b.stock_count !== a.stock_count) return b.stock_count - a.stock_count
      return Math.abs(b.avg_momentum_20d ?? 0) - Math.abs(a.avg_momentum_20d ?? 0)
    })
    const items = sorted.slice(0, 200)
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: 140, right: 60, top: 8, bottom: 24 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: chartAxis } } },
      yAxis: {
        type: 'category',
        data: items.map(i => i.concept).reverse(),
        axisLabel: { fontSize: 10, color: chartText },
      },
      series: [{
        type: 'bar',
        data: items.map(i => ({
          value: i.stock_count,
          itemStyle: {
            color: i.sources.includes('eastmoney') && i.sources.includes('ths')
              ? '#722ed1'
              : i.sources.includes('eastmoney')
                ? '#13c2c2'
                : '#fa8c16',
            borderRadius: [0, 4, 4, 0],
          },
        })).reverse(),
        barWidth: '60%',
        label: { show: true, position: 'right', fontSize: 10, formatter: (p: any) => p.value + '只' },
      }],
    }
  }, [filteredConcepts, chartText, chartAxis])

  const sourceCoverage = useMemo(() => {
    const list = conceptData?.concepts ?? []
    const emOnly = list.filter(c => c.sources.length === 1 && c.sources[0] === 'eastmoney').length
    const thsOnly = list.filter(c => c.sources.length === 1 && c.sources[0] === 'ths').length
    const both = list.filter(c => c.sources.length === 2).length
    return { emOnly, thsOnly, both, total: list.length }
  }, [conceptData])


  const compositeColumns = [
    { title:'排名', dataIndex:'rank', key:'rank', width:60,
      render:(v:number)=><Tag color={v<=3?'#ff4d4f':v<=10?'#fa8c16':'#8c8c8c'} style={{fontWeight:700,minWidth:32,textAlign:'center'}}>{v}</Tag>},
    { title:'行业', dataIndex:'industry', key:'industry', width:100,
      sorter:(a:any,b:any)=>a.industry?.localeCompare?.(b.industry,'zh')??0,
      render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
    { title:'综合评分', dataIndex:'composite', key:'composite', width:90,
      sorter:(a:any,b:any)=>a.composite-b.composite,
      render:(v:number)=><Tag color={v>=70?'#52c41a':v>=40?'#faad14':'#ff4d4f'} style={{fontWeight:700,minWidth:48,textAlign:'center'}}>{v}</Tag>},
    { title:'股票数', dataIndex:'stock_count', key:'stock_count', width:70,
      sorter:(a:any,b:any)=>a.stock_count-b.stock_count},
    { title:'涨跌幅', dataIndex:'avg_stock_change_pct', key:'avg_stock_change_pct', width:85,
      sorter:(a:any,b:any)=>(a.avg_stock_change_pct??0)-(b.avg_stock_change_pct??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'5日动量', dataIndex:'avg_momentum_5d', key:'m5', width:80,
      sorter:(a:any,b:any)=>(a.avg_momentum_5d??0)-(b.avg_momentum_5d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'10日动量', dataIndex:'avg_momentum_10d', key:'m10', width:80,
      sorter:(a:any,b:any)=>(a.avg_momentum_10d??0)-(b.avg_momentum_10d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
    { title:'20日动量', dataIndex:'avg_momentum_20d', key:'avg_momentum_20d', width:85,
      sorter:(a:any,b:any)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
    { title:'ROE', dataIndex:'avg_roe', key:'avg_roe', width:70,
      sorter:(a:any,b:any)=>(a.avg_roe??0)-(b.avg_roe??0),
      render:(v:number)=><span style={{color:v>=12?'#52c41a':v>=6?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'毛利率', dataIndex:'avg_gpm', key:'avg_gpm', width:75,
      sorter:(a:any,b:any)=>(a.avg_gpm??0)-(b.avg_gpm??0),
      render:(v:number)=><span style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
    { title:'PE', dataIndex:'avg_pe', key:'avg_pe', width:70,
      sorter:(a:any,b:any)=>(a.avg_pe??0)-(b.avg_pe??0),
      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
    { title:'主力资金', dataIndex:'net_capital_flow', key:'net_capital_flow', width:100,
      sorter:(a:any,b:any)=>(a.net_capital_flow??0)-(b.net_capital_flow??0),
      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</span>},
    { title:'动量分散度', dataIndex:'momentum_dispersion', key:'momentum_dispersion', width:95,
      sorter:(a:any,b:any)=>(a.momentum_dispersion??0)-(b.momentum_dispersion??0),
      render:(v:number)=><span style={{color:v>=8?'#ff4d4f':v>=4?'#faad14':'#52c41a'}}>{fmt(v)}</span>},
    { title:'IV', dataIndex:'avg_iv', key:'avg_iv', width:65,
      sorter:(a:any,b:any)=>(a.avg_iv??0)-(b.avg_iv??0),
      render:(v:number)=><span style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
    { title:'换手率', dataIndex:'avg_turnover_rate', key:'avg_turnover_rate', width:75,
      sorter:(a:any,b:any)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),
      render:(v:number)=><span>{fmt(v)}%</span>},
    { title:'操作', key:'action', width:70, fixed:'right' as const,
      render:(_:any,r:StockIndustryAgg)=><Button type='link' size='small' icon={<ExpandOutlined/>} onClick={()=>{setDetailInd(r);setDetailOpen(true)}}>个股</Button>},
  ]

  // ═════════════════════════════════════════════════════════════════════════════
  //  Render
  // ═════════════════════════════════════════════════════════════════════════════

  return (
    <div style={{height:'100%',display:'flex',flexDirection:'column',padding:'0 16px 16px'}}>
      {/* ── 顶部概览 ── */}
      <Card size='small' style={{marginBottom:12,borderRadius:10,
        background:isDark?'linear-gradient(135deg,#1a1a2e,#16213e)':'linear-gradient(135deg,#f0e8f8,#f0f5ff)'}}
        styles={{body:{padding:'12px 20px',display:'flex',alignItems:'center',justifyContent:'space-between'}}}>
        <div>
          <Title level={4} style={{margin:0,background:isDark?'linear-gradient(90deg,#9254de,#69b1ff)':'linear-gradient(90deg,#722ed1,#1677ff)',WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent'}}>
            📊 行业轮动 · 股票版
          </Title>
          <Text type='secondary' style={{fontSize:12}}>正股维度行业轮动 · 多周期动量 + 资金流向 + 估值质量 + 综合评分</Text>
        </div>
        <Space>
          <Input placeholder='搜索行业' size='small' prefix={<SearchOutlined/>} style={{width:140}} value={searchText} onChange={e=>setSearchText(e.target.value)} allowClear/>
          <Button size='small' icon={<DatabaseOutlined/>} onClick={()=>setShowDataLayer(!showDataLayer)}>{showDataLayer?'隐藏':'查看'}数据源</Button>
          <Button size='small' icon={<ReloadOutlined/>} onClick={loadData}>刷新</Button>
        </Space>
      </Card>

      {showDataLayer && (
        <Card size='small' title={<span><DatabaseOutlined/> 数据源架构 (7层)</span>}
          styles={{body:{padding:'8px 16px'}}} style={{marginBottom:12,borderRadius:8}}>
          <Row gutter={[8,8]}>
            {DATA_LAYERS.map(l=>(
              <Col span={3} key={l.layer}>
                <div style={{display:'flex',alignItems:'center',gap:8,padding:'6px 8px',borderRadius:6,background:`${l.color}10`,borderLeft:`3px solid ${l.color}`}}>
                  <div><Text strong style={{fontSize:11,color:l.color}}>{l.title}</Text><br/><Text type='secondary' style={{fontSize:9}}>{l.desc}</Text></div>
                </div>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      <Tabs activeKey={activeTab} onChange={setActiveTab}
        style={{flex:1,display:'flex',flexDirection:'column'}}
        tabBarStyle={{marginBottom:0,padding:'0 8px'}}
        items={[

          // ════════════════════════════════════════════════════════
          //  TAB 1 — 行业概览
          // ════════════════════════════════════════════════════════
          {key:'overview', label:<span><AppstoreOutlined/> 行业概览</span>, children: loading?renderSkeleton():error?<Card style={{padding:40}}><Empty description={error}><Button type='primary' onClick={loadData}>重试</Button></Empty></Card>:!data?<Empty description='暂无数据'/>:(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[8,8]}>
                <Col span={4}><StatCard title='行业数量' value={data.total_industries} suffix='个' color='#722ed1' icon={<AppstoreOutlined/>}/></Col>
                <Col span={4}><StatCard title='正股总数' value={data.total_stocks} suffix='只' color='#1677ff' icon={<StockOutlined/>}/></Col>
                <Col span={4}><StatCard title='最大行业' value={sortedIndustries[0]?.industry||'-'} color={indColor(sortedIndustries[0]?.industry||'')} icon={<StarOutlined/>}/></Col>
                <Col span={4}><StatCard title='最大行业股票数' value={sortedIndustries[0]?.stock_count||0} suffix='只' color='#52c41a'/></Col>
                <Col span={4}><StatCard title='平均涨跌幅' value={fmt(avgChange)} suffix='%' color={avgChange>=0?'#ff4d4f':'#52c41a'} icon={trendIcon(avgChange)}/></Col>
                <Col span={4}><StatCard title='行业覆盖率' value={Math.round((data.total_industries/85)*100)} suffix='%' color='#13c2c2' icon={<CheckCircleOutlined/>}/></Col>
              </Row>
              <Row gutter={[12,12]} style={{flex:1}}>
                <Col xs={24} lg={5}>
                  <Card size='small' title={<span><FilterOutlined/> 筛选</span>} styles={{body:{padding:'8px 12px'}}}>
                    <div style={{marginBottom:8}}><Text type='secondary' style={{fontSize:11}}>排序方式</Text>
                      <Select value={sortKey} onChange={setSortKey} size='small' style={{width:'100%',marginTop:2}}>
                        <Select.Option value='stock_count'>📊 股票数量</Select.Option>
                        <Select.Option value='avg_stock_change_pct'>📈 涨跌幅</Select.Option>
                        <Select.Option value='avg_momentum_20d'>🚀 20日动量</Select.Option>
                        <Select.Option value='avg_roe'>💰 ROE</Select.Option>
                        <Select.Option value='avg_gpm'>📐 毛利率</Select.Option>
                        <Select.Option value='net_capital_flow'>💵 资金净流入</Select.Option>
                        <Select.Option value='avg_turnover_rate'>🔄 换手率</Select.Option>
                        <Select.Option value='composite'>🏆 综合评分</Select.Option>
                      </Select></div>
                    <div><Text type='secondary' style={{fontSize:11}}>显示数量</Text>
                      <Select value={topK} onChange={setTopK} size='small' style={{width:'100%',marginTop:2}}>
                        {[10,20,30,50,100].map(n=><Select.Option key={n} value={n}>Top {n}</Select.Option>)}
                      </Select></div>
                  </Card>
                </Col>
                <Col xs={24} lg={19}>
                  <Row gutter={[12,12]}>
                    <Col span={14}>
                      <Card size='small' title={<span><BarChartOutlined/> 行业股票分布 (Top 25)</span>} styles={{body:{padding:8}}}>
                        <ReactEChartsCore echarts={echarts} option={stockCountChartOption} style={{height:320}} notMerge/>
                      </Card>
                    </Col>
                    <Col span={10}>
                      <Card size='small' title={<span><PieChartOutlined/> 行业占比</span>} styles={{body:{padding:8}}}>
                        <ReactEChartsCore echarts={echarts} option={industryPieOption} style={{height:320}} notMerge/>
                      </Card>
                    </Col>
                  </Row>
                  <Card size='small' title={<span><ClusterOutlined/> 各行业详细数据</span>}
                    extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(sortedIndustries,'stock-industries-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>}
                    styles={{body:{padding:0}}}>
                    <Table dataSource={sortedIndustries.map((i,idx)=>({...i,key:idx}))} columns={indColumns} size='small'
                      pagination={{pageSize:15,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:1800,y:380}} showSorterTooltip={false}
                      onRow={r=>({style:{cursor:'pointer'},onClick:()=>{setDetailInd(r);setDetailOpen(true)}})}/>
                  </Card>
                </Col>
              </Row>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 2 — 动量排名
          // ════════════════════════════════════════════════════════
          {key:'momentum', label:<span><ThunderboltOutlined/> 动量排名</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[12,12]}>
                <Col span={12}>
                  <Card size='small' title={<span><HeatMapOutlined/> 多周期动量热力图</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={momentumHeatmapOption} style={{height:450}} notMerge/>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size='small' title={<span><LineChartOutlined/> 动量分散度 (行业内个股动量标准差)</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={dispersionChartOption} style={{height:450}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><ThunderboltOutlined/> 动量排名详情</span>}
                extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>{
                  const {field:sF,order:sO}=momentumSorter
                  const momData=[...(data?.industries??[])].sort((a,b)=>{
                    const va=(a[sF as keyof typeof a] as number)??0, vb=(b[sF as keyof typeof b] as number)??0
                    return sO==='ascend'?va-vb:vb-va
                  })
                  exportCSV(momData,'stock-momentum-ranking-'+dayjs().format('YYYYMMDD')+'.csv')
                }}>导出</Button>}
                styles={{body:{padding:0}}}>
                <Table dataSource={industryTableData}
                  onChange={(_pagination,_filters,sorter)=>{
                    const s=Array.isArray(sorter)?sorter[0]:sorter
                    if(s?.field) setMomentumSorter({field:s.field as string,order:(s.order as 'ascend'|'descend')||'descend'})
                  }}
                  columns={[
                    {title:'排名',key:'rank',width:60,render:(_:any,__:any,idx:number)=><Tag color={idx<3?'#ff4d4f':idx<10?'#fa8c16':'#8c8c8c'} style={{fontWeight:700}}>{idx+1}</Tag>},
                    {title:'行业',dataIndex:'industry',key:'industry',width:100,
                      sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>a.industry.localeCompare(b.industry,'zh'),
                      render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                    {title:'股票数',dataIndex:'stock_count',key:'stock_count',width:70,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.stock_count??0)-(b.stock_count??0)},
                    {title:'5日',dataIndex:'avg_momentum_5d',key:'m5',width:80,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_5d??0)-(b.avg_momentum_5d??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    {title:'10日',dataIndex:'avg_momentum_10d',key:'m10',width:80,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_10d??0)-(b.avg_momentum_10d??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    {title:'20日',dataIndex:'avg_momentum_20d',key:'m20',width:80,defaultSortOrder:'descend',sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
                    {title:'60日',dataIndex:'avg_momentum_60d',key:'m60',width:80,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_momentum_60d??0)-(b.avg_momentum_60d??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    {title:'分散度',dataIndex:'momentum_dispersion',key:'disp',width:80,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.momentum_dispersion??0)-(b.momentum_dispersion??0),render:(v:number)=><span style={{color:v>=8?'#ff4d4f':v>=4?'#faad14':'#52c41a'}}>{fmt(v)}</span>},
                    {title:'涨跌幅',dataIndex:'avg_stock_change_pct',key:'chg',width:85,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_stock_change_pct??0)-(b.avg_stock_change_pct??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    {title:'换手率',dataIndex:'avg_turnover_rate',key:'turn',width:75,sorter:(a:StockIndustryAgg,b:StockIndustryAgg)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),render:(v:number)=><span>{fmt(v)}%</span>},
                    {title:'操作',key:'action',width:70,render:(_:any,r:StockIndustryAgg)=><Button type='link' size='small' icon={<ExpandOutlined/>} onClick={()=>{setDetailInd(r);setDetailOpen(true)}}>个股</Button>},
                  ]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{y:400}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 3 — 资金流向 (增强版 — 多数据源)
          // ════════════════════════════════════════════════════════
          {key:'flow', label:<span><DollarOutlined/> 资金流向</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[12,12]}>
                <Col span={14}>
                  <Card size='small' title={<span><FundOutlined/> 主力资金净流入 <Tag color='blue' style={{marginLeft:8}}>东方财富实时</Tag></span>} extra={<Button size='small' icon={<ReloadOutlined/>} loading={industryFundFlowLoading} onClick={()=>{loadIndustryFundFlow();loadIndividualFundFlow()}}>刷新</Button>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={flowChartOption} style={{height:400}} notMerge/>
                  </Card>
                </Col>
                <Col span={10}>
                  <Card size='small' title={<span><BarChartOutlined/> 超大单/大单拆分 <Tag color='blue'>东方财富实时</Tag></span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={flowBreakdownOption} style={{height:400}} notMerge/>
                  </Card>
                </Col>
              </Row>
              {mainFundFlowChartOption && (
              <Row gutter={[12,12]}>
                <Col span={24}>
                  <Card size='small' title={<span><ThunderboltOutlined/> 个股主力资金拆分 TOP20 <Tag color='purple'>超大单/大单/中单/小单</Tag></span>} extra={<Button size='small' icon={<ReloadOutlined/>} loading={mainFundFlowLoading} onClick={loadMainFundFlow}>刷新</Button>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={mainFundFlowChartOption} style={{height:450}} notMerge/>
                  </Card>
                </Col>
              </Row>
              )}
              <Row gutter={[12,12]}>
                <Col span={12}>
                  <Card size='small' title={<span><PercentageOutlined/> 换手率排名 <Tag color='blue'>东方财富实时</Tag></span>} extra={<Button size='small' icon={<ReloadOutlined/>} loading={turnoverRankLoading} onClick={loadTurnoverRank}>刷新</Button>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={turnoverChartOption} style={{height:380}} notMerge/>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size='small' title={<span><TeamOutlined/> 行业资金流向详情 <Tag color='blue'>东方财富</Tag></span>} styles={{body:{padding:0}}}>
                    {industryFundFlowData ? (
                    <Table dataSource={industryFundFlowData.industries.sort((a,b)=>Math.abs(b.net_inflow??0)-Math.abs(a.net_inflow??0)).map((i,idx)=>({...i,key:idx}))}
                      columns={[
                        {title:'行业',dataIndex:'industry',key:'industry',width:100,
                          sorter:(a:any,b:any)=>a.industry?.localeCompare?.(b.industry,'zh')??0,
                          render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                        {title:'涨跌幅',dataIndex:'change_pct',key:'cp',width:80,sorter:(a:any,b:any)=>(a.change_pct??0)-(b.change_pct??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v?.toFixed(2)}%</span>},
                        {title:'净流入',dataIndex:'net_inflow',key:'ni',width:100,sorter:(a:any,b:any)=>(a.net_inflow??0)-(b.net_inflow??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</span>},
                        {title:'流入',dataIndex:'inflow',key:'inf',width:90,sorter:(a:any,b:any)=>(a.inflow??0)-(b.inflow??0),render:(v:number)=>fmtFlow(v)},
                        {title:'流出',dataIndex:'outflow',key:'outf',width:90,sorter:(a:any,b:any)=>(a.outflow??0)-(b.outflow??0),render:(v:number)=>fmtFlow(v)},
                        {title:'公司数',dataIndex:'company_count',key:'cc',width:65,sorter:(a:any,b:any)=>a.company_count-b.company_count},
                        {title:'领涨股',dataIndex:'leading_stock',key:'ls',width:80,sorter:(a:any,b:any)=>(a.leading_stock??'').localeCompare(b.leading_stock??'','zh'),render:(v:string)=><Text style={{fontSize:11}}>{v||'-'}</Text>},
                        {title:'领涨涨幅',dataIndex:'leading_change',key:'lc',width:80,sorter:(a:any,b:any)=>(a.leading_change??0)-(b.leading_change??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v?.toFixed(2)}%</span>},
                      ]}
                      size='small' pagination={false} scroll={{y:340}}/>
                    ) : (
                    <Table dataSource={[...(data?.industries??[])].sort((a,b)=>Math.abs(b.net_capital_flow??0)-Math.abs(a.net_capital_flow??0)).map((i,idx)=>({...i,key:idx}))}
                      columns={[
                        {title:'行业',dataIndex:'industry',key:'industry',width:100,sorter:(a:any,b:any)=>a.industry?.localeCompare?.(b.industry,'zh')??0,render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                        {title:'股票数',dataIndex:'stock_count',key:'sc',width:70,sorter:(a:any,b:any)=>a.stock_count-b.stock_count},
                        {title:'主力净流入',dataIndex:'net_capital_flow',key:'ncf',width:110,sorter:(a:any,b:any)=>(a.net_capital_flow??0)-(b.net_capital_flow??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</span>},
                        {title:'超大单',dataIndex:'net_super_flow',key:'nsf',width:100,sorter:(a:any,b:any)=>(a.net_super_flow??0)-(b.net_super_flow??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtFlow(v)}</span>},
                        {title:'大单',dataIndex:'net_big_flow',key:'nbf',width:100,sorter:(a:any,b:any)=>(a.net_big_flow??0)-(b.net_big_flow??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtFlow(v)}</span>},
                        {title:'换手率',dataIndex:'avg_turnover_rate',key:'atr',width:75,sorter:(a:any,b:any)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),render:(v:number)=><span>{fmt(v)}%</span>},
                      ]}
                      size='small' pagination={false} scroll={{y:340}}/>
                    )}
                  </Card>
                </Col>
              </Row>
              {individualFundFlowData && individualFundFlowData.stocks.length>0 && (
              <Row gutter={[12,12]}>
                <Col span={24}>
                  <Card size='small' title={<span><StockOutlined/> 个股资金流向 TOP100 <Tag color='blue'>东方财富</Tag></span>} extra={<Button size='small' icon={<ReloadOutlined/>} loading={individualFundFlowLoading} onClick={loadIndividualFundFlow}>刷新</Button>} styles={{body:{padding:0}}}>
                    <Table dataSource={individualFundFlowData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))}
                      columns={[
                        {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code)??0},
                        {title:'名称',dataIndex:'name',width:90,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                        {title:'最新价',dataIndex:'price',width:75,align:'right',sorter:(a:any,b:any)=>(a.price??0)-(b.price??0),render:(v:number)=>v?.toFixed(2)},
                        {title:'涨跌幅',dataIndex:'change_pct',width:80,align:'right',sorter:(a:any,b:any)=>a.change_pct-b.change_pct,render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v?.toFixed(2)}%</span>},
                        {title:'换手率',dataIndex:'turnover_rate',width:75,align:'right',sorter:(a:any,b:any)=>a.turnover_rate-b.turnover_rate,render:(v:number)=><span style={{color:v>=10?'#ff4d4f':v>=5?'#faad14':'#333'}}>{v?.toFixed(2)}%</span>},
                        {title:'流入(亿)',dataIndex:'inflow',width:90,align:'right',sorter:(a:any,b:any)=>a.inflow-b.inflow,render:(v:number)=>v?.toFixed(2)},
                        {title:'流出(亿)',dataIndex:'outflow',width:90,align:'right',sorter:(a:any,b:any)=>a.outflow-b.outflow,render:(v:number)=>v?.toFixed(2)},
                        {title:'净流入(亿)',dataIndex:'net_inflow',width:100,align:'right',sorter:(a:any,b:any)=>a.net_inflow-b.net_inflow,render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{v?.toFixed(2)}</span>},
                        {title:'成交额(亿)',dataIndex:'amount',width:100,align:'right',sorter:(a:any,b:any)=>a.amount-b.amount,render:(v:number)=>v?.toFixed(2)},
                      ]}
                      size='small' pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:400}}/>
                  </Card>
                </Col>
              </Row>
              )}
              {hsgtFundFlowData && hsgtFundFlowData.flows.length>0 && (
              <Row gutter={[12,12]}>
                <Col span={24}>
                  <Card size='small' title={<span><BankOutlined/> 沪深港通资金流向 <Tag color='green'>实时</Tag></span>} extra={<Button size='small' icon={<ReloadOutlined/>} loading={hsgtFundFlowLoading} onClick={loadHsgtFundFlow}>刷新</Button>} styles={{body:{padding:0}}}>
                    <Table dataSource={hsgtFundFlowData.flows.map((f,i)=>({...f,key:i}))}
                      columns={[
                        {title:'交易日',dataIndex:'date',width:100,sorter:(a:any,b:any)=>a.date?.localeCompare?.(b.date)??0},
                        {title:'状态',dataIndex:'status_text',width:70,sorter:(a:any,b:any)=>(a.status??0)-(b.status??0),render:(v:string)=><Tag color={v==='交易中'?'green':v==='已收盘'?'orange':'default'}>{v||'-'}</Tag>},
                        {title:'板块',dataIndex:'plate',width:100,sorter:(a:any,b:any)=>a.plate?.localeCompare?.(b.plate,'zh')??0},
                        {title:'方向',dataIndex:'direction',width:60,sorter:(a:any,b:any)=>(a.direction??'').localeCompare(b.direction??''),render:(v:string)=><Tag color={v==='北向'?'red':'green'}>{v}</Tag>},
                        {title:'净买入(亿)',dataIndex:'net_buy',width:110,align:'right',sorter:(a:any,b:any)=>(a.net_buy??0)-(b.net_buy??0),render:(v:number|null)=>v!=null?<span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{v.toFixed(2)}</span>:<Text type='secondary'>-</Text>},
                        {title:'净流入(亿)',dataIndex:'net_inflow',width:110,align:'right',sorter:(a:any,b:any)=>(a.net_inflow??0)-(b.net_inflow??0),render:(v:number|null)=>v!=null?<span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v.toFixed(2)}</span>:<Text type='secondary'>-</Text>},
                        {title:'余额(亿)',dataIndex:'balance',width:110,align:'right',sorter:(a:any,b:any)=>(a.balance??0)-(b.balance??0),render:(v:number|null)=>v!=null?v.toFixed(2):<Text type='secondary'>-</Text>},
                        {title:'上涨/下跌',key:'ud',width:100,sorter:(a:any,b:any)=>(a.up_count??0)-(b.up_count??0),render:(_:any,r:any)=>r.up_count!=null?<span style={{fontSize:11}}><span style={{color:'#ff4d4f'}}>{r.up_count}</span>/<span style={{color:'#52c41a'}}>{r.down_count}</span></span>:<Text type='secondary'>-</Text>},
                        {title:'相关指数',dataIndex:'index_name',width:100,sorter:(a:any,b:any)=>(a.index_name??'').localeCompare(b.index_name??'')},
                        {title:'指数涨跌',dataIndex:'index_change',width:90,sorter:(a:any,b:any)=>(a.index_change??0)-(b.index_change??0),render:(v:number|null)=>v!=null?<span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{v.toFixed(2)}%</span>:<Text type='secondary'>-</Text>},
                      ]}
                      size='small' pagination={false} />
                  </Card>
                </Col>
              </Row>
              )}
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 4 — 估值质量
          // ════════════════════════════════════════════════════════
          {key:'valuation', label:<span><SafetyCertificateOutlined/> 估值质量</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[12,12]}>
                <Col span={12}>
                  <Card size='small' title={<span><BarChartOutlined/> ROE排名</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={roeChartOption} style={{height:380}} notMerge/>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size='small' title={<span><BarChartOutlined/> PE/PB散点</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={valuationScatterOption} style={{height:380}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Row gutter={[12,12]}>
                <Col span={16}>
                  <Card size='small' title={<span><LineChartOutlined/> 毛利率 + CAGR</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={qualityChartOption} style={{height:340}} notMerge/>
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size='small' title={<span><DatabaseOutlined/> 负债率排名</span>} styles={{body:{padding:0}}}>
                    <Table dataSource={[...(data?.industries??[])].sort((a,b)=>(b.avg_debt_ratio??0)-(a.avg_debt_ratio??0)).map((i,idx)=>({...i,key:idx}))}
                      columns={[
                        {title:'行业',dataIndex:'industry',key:'ind',width:90,
                          sorter:(a:any,b:any)=>a.industry?.localeCompare?.(b.industry,'zh')??0,
                          render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                        {title:'负债率',dataIndex:'avg_debt_ratio',key:'dr',width:80,sorter:(a:any,b:any)=>(a.avg_debt_ratio??0)-(b.avg_debt_ratio??0),render:(v:number)=><span style={{color:v>=60?'#ff4d4f':v>=40?'#faad14':'#52c41a',fontWeight:600}}>{fmt(v)}%</span>},
                        {title:'ROE',dataIndex:'avg_roe',key:'roe',width:65,sorter:(a:any,b:any)=>(a.avg_roe??0)-(b.avg_roe??0),render:(v:number)=><span>{fmt(v)}%</span>},
                        {title:'CAGR',dataIndex:'avg_cagr',key:'cagr',width:65,sorter:(a:any,b:any)=>(a.avg_cagr??0)-(b.avg_cagr??0),render:(v:number)=><span style={{color:v>=10?'#52c41a':v>=0?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
                      ]}
                      size='small' pagination={false} scroll={{y:300}}/>
                  </Card>
                </Col>
              </Row>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 5 — 波动风险
          // ════════════════════════════════════════════════════════
          {key:'risk', label:<span><SafetyCertificateOutlined/> 波动风险</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Row gutter={[12,12]}>
                <Col span={12}>
                  <Card size='small' title={<span><BarChartOutlined/> 隐含波动率</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={ivChartOption} style={{height:400}} notMerge/>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card size='small' title={<span><BarChartOutlined/> 质押比例</span>} styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={pledgeChartOption} style={{height:400}} notMerge/>
                  </Card>
                </Col>
              </Row>
              <Card size='small' title={<span><ClusterOutlined/> 风险指标详情</span>} styles={{body:{padding:0}}}>
                <Table dataSource={industryTableData}
                  columns={[
                    {title:'行业',dataIndex:'industry',key:'ind',width:100,
                      sorter:(a:any,b:any)=>a.industry?.localeCompare?.(b.industry,'zh')??0,
                      render:(v:string)=><span style={{color:indColor(v),fontWeight:600}}>{v}</span>},
                    {title:'股票数',dataIndex:'stock_count',key:'sc',width:70,sorter:(a:any,b:any)=>a.stock_count-b.stock_count},
                    {title:'IV',dataIndex:'avg_iv',key:'iv',width:70,sorter:(a:any,b:any)=>(a.avg_iv??0)-(b.avg_iv??0),render:(v:number)=><span style={{color:v>=40?'#ff4d4f':v>=25?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
                    {title:'换手率',dataIndex:'avg_turnover_rate',key:'tr',width:75,sorter:(a:any,b:any)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),render:(v:number)=><span>{fmt(v)}%</span>},
                    {title:'质押率',dataIndex:'avg_pledge_ratio',key:'pr',width:75,sorter:(a:any,b:any)=>(a.avg_pledge_ratio??0)-(b.avg_pledge_ratio??0),render:(v:number)=><span style={{color:v>=30?'#ff4d4f':v>=15?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
                    {title:'动量分散度',dataIndex:'momentum_dispersion',key:'md',width:95,sorter:(a:any,b:any)=>(a.momentum_dispersion??0)-(b.momentum_dispersion??0),render:(v:number)=><span style={{color:v>=8?'#ff4d4f':v>=4?'#faad14':'#52c41a'}}>{fmt(v)}</span>},
                    {title:'负债率',dataIndex:'avg_debt_ratio',key:'dr',width:75,sorter:(a:any,b:any)=>(a.avg_debt_ratio??0)-(b.avg_debt_ratio??0),render:(v:number)=><span style={{color:v>=60?'#ff4d4f':v>=40?'#faad14':'#52c41a'}}>{fmt(v)}%</span>},
                    {title:'20日动量',dataIndex:'avg_momentum_20d',key:'m20',width:85,sorter:(a:any,b:any)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                  ]}
                  size='small' pagination={{pageSize:15,showTotal:t=>`共 ${t} 个行业`}} scroll={{y:380}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 6 — 行业个股
          // ════════════════════════════════════════════════════════
          {key:'stocks', label:<span><StockOutlined/> 行业个股</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Card size='small' styles={{body:{padding:'8px 16px'}}}>
                <Space wrap>
                  <Text strong>选择行业:</Text>
                  <Input placeholder='搜索行业...' size='small' style={{width:120}} allowClear
                    onChange={e=>{const kw=e.target.value.toLowerCase(); if(!kw){setDetailInd(null);return} const found=(data?.industries??[]).find(i=>i.industry.toLowerCase().includes(kw)); if(found) setDetailInd(found)}}/>
                  {(data?.industries??[]).slice(0,50).map(ind=>(
                    <Button key={ind.industry} size='small'
                      type={detailInd?.industry===ind.industry?'primary':'default'}
                      style={{borderColor:indColor(ind.industry),color:detailInd?.industry===ind.industry?'#fff':indColor(ind.industry),fontSize:11}}
                      onClick={()=>{setDetailInd(ind)}}>
                      {ind.industry} ({ind.stock_count})
                    </Button>
                  ))}
                  {(data?.industries??[]).length > 50 && <Text type='secondary' style={{fontSize:11}}>...共{(data?.industries??[]).length}个行业</Text>}
                </Space>
              </Card>
              {detailInd?(
                <div>
                  <Card size='small' title={<span style={{color:indColor(detailInd.industry),fontWeight:700}}>{detailInd.industry} — 个股明细</span>}
                    extra={<Badge count={detailInd.stocks.length} style={{backgroundColor:'#722ed1'}}/>}
                    styles={{body:{padding:0}}}>
                    <Table dataSource={detailInd.stocks.map((s,i)=>({...s,key:i}))} columns={stockColumns}
                      size='small' pagination={{pageSize:15,showTotal:t=>`共 ${t} 只`}} scroll={{x:1600,y:400}}/>
                  </Card>
                </div>
              ):<Empty description='请选择一个行业查看个股明细' style={{padding:60}}/>}
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 7 — 综合排名
          // ════════════════════════════════════════════════════════
          {key:'composite', label:<span><TrophyOutlined/> 综合排名</span>, children: loading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Card size='small' title={<span><SettingOutlined/> 评分权重配置</span>} styles={{body:{padding:'8px 16px'}}} style={{borderRadius:8}}>
                <Row gutter={[16,8]}>
                  <Col span={6}><Text type='secondary' style={{fontSize:11}}>动量权重: <b style={{color:'#ff4d4f'}}>{weights.mom}%</b></Text><Slider min={0} max={100} value={weights.mom} onChange={v=>setWeights(w=>({...w,mom:v}))}/></Col>
                  <Col span={6}><Text type='secondary' style={{fontSize:11}}>资金权重: <b style={{color:'#fa8c16'}}>{weights.flow}%</b></Text><Slider min={0} max={100} value={weights.flow} onChange={v=>setWeights(w=>({...w,flow:v}))}/></Col>
                  <Col span={6}><Text type='secondary' style={{fontSize:11}}>质量权重: <b style={{color:'#52c41a'}}>{weights.quality}%</b></Text><Slider min={0} max={100} value={weights.quality} onChange={v=>setWeights(w=>({...w,quality:v}))}/></Col>
                  <Col span={6}><Text type='secondary' style={{fontSize:11}}>估值权重: <b style={{color:'#722ed1'}}>{weights.val}%</b></Text><Slider min={0} max={100} value={weights.val} onChange={v=>setWeights(w=>({...w,val:v}))}/></Col>
                </Row>
              </Card>
              <Row gutter={[8,8]}>
                <Col span={4}><StatCard title='🥇 最强行业' value={compositeData[0]?.industry||'-'} color='#ff4d4f'/></Col>
                <Col span={4}><StatCard title='🥈 次强行业' value={compositeData[1]?.industry||'-'} color='#fa8c16'/></Col>
                <Col span={4}><StatCard title='🥉 第三行业' value={compositeData[2]?.industry||'-'} color='#faad14'/></Col>
                <Col span={4}><StatCard title='最弱行业' value={compositeData[compositeData.length-1]?.industry||'-'} color='#52c41a'/></Col>
                <Col span={4}><StatCard title='平均评分' value={compositeData.length?Math.round(compositeData.reduce((s,i)=>s+i.composite,0)/compositeData.length):0} color='#722ed1' icon={<DashboardOutlined/>}/></Col>
                <Col span={4}><StatCard title='评分≥60' value={compositeData.filter(i=>i.composite>=60).length} suffix='个' color='#13c2c2' icon={<CheckCircleOutlined/>}/></Col>
              </Row>
              <Card size='small' title={<span><TrophyOutlined/> 综合评分排名 (动量40% + 资金25% + 质量20% + 估值15%)</span>}
                extra={<Button size='small' icon={<DownloadOutlined/>} onClick={()=>exportCSV(compositeData,'stock-composite-ranking-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>}
                styles={{body:{padding:0}}}>
                <Table dataSource={compositeData.map((i,idx)=>({...i,key:idx}))} columns={compositeColumns} size='small'
                  pagination={{pageSize:20,showTotal:t=>`共 ${t} 个行业`}} scroll={{x:1200,y:500}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 8 — 概念板块 (东方财富 + 同花顺)
          // ════════════════════════════════════════════════════════
          {key:'concepts', label:<span><NodeIndexOutlined/> 概念板块</span>, children: conceptLoading?renderSkeleton():(
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              {/* Row 1 — top stats */}
              <Row gutter={[8,8]}>
                <Col span={4}><StatCard title='概念板块数' value={conceptData?.total_concepts??0} suffix='个' color='#722ed1' icon={<NodeIndexOutlined/>}/></Col>
                <Col span={4}><StatCard title='覆盖正股数' value={conceptData?.total_stocks??0} suffix='只' color='#1677ff' icon={<StockOutlined/>}/></Col>
                <Col span={4}><StatCard title='最热门概念' value={conceptData?.concepts?.[0]?.concept??'-'} color='#eb2f96' icon={<ThunderboltOutlined/>}/></Col>
                <Col span={4}><StatCard title='双源重叠' value={sourceCoverage.both} suffix='个' color='#13c2c2' icon={<CheckCircleOutlined/>}/></Col>
                <Col span={4}><StatCard title='EM独享' value={sourceCoverage.emOnly} suffix='个' color='#fa8c16' icon={<Tag color='#13c2c2' style={{margin:0,padding:'0 4px'}}>东财</Tag>}/></Col>
                <Col span={4}><StatCard title='THS独享' value={sourceCoverage.thsOnly} suffix='个' color='#9254de' icon={<Tag color='#9254de' style={{margin:0,padding:'0 4px'}}>同花顺</Tag>}/></Col>
              </Row>

              {/* Row 2 — filters + fine-grained chips */}
              <Card size='small' styles={{body:{padding:'8px 16px'}}} style={{borderRadius:8}}>
                <Space size={[12,8]} wrap>
                  <Space size={4}>
                    <Text type='secondary' style={{fontSize:12}}>来源:</Text>
                    <Select
                      value={conceptSource}
                      onChange={setConceptSource}
                      size='small' style={{width:130}}
                      options={[
                        { value: 'all', label: '全部来源' },
                        { value: 'both', label: '双源重叠' },
                        { value: 'em', label: '东方财富' },
                        { value: 'ths', label: '同花顺' },
                        { value: 'em_only', label: '仅东财' },
                        { value: 'ths_only', label: '仅同花顺' },
                      ]}
                    />
                  </Space>
                  <Space size={4}>
                    <Text type='secondary' style={{fontSize:12}}>最少股票数:</Text>
                    <InputNumber size='small' min={2} max={200} value={conceptMinCount}
                      onChange={(v)=>v && setConceptMinCount(v as number)} style={{width:80}}/>
                  </Space>
                  <Input size='small' placeholder='搜索概念名称...' prefix={<SearchOutlined/>}
                    style={{width:200}} value={conceptKeyword} onChange={e=>setConceptKeyword(e.target.value)} allowClear/>
                  <Button size='small' icon={<ReloadOutlined/>} onClick={loadConcepts}>刷新</Button>
                  <Button size='small' icon={<DownloadOutlined/>}
                    onClick={()=>exportCSV(filteredConcepts,'stock-concepts-'+dayjs().format('YYYYMMDD')+'.csv')}>导出</Button>
                  <Text type='secondary' style={{fontSize:11}}>当前过滤后: <b style={{color:'#722ed1'}}>{filteredConcepts.length}</b> 个概念</Text>
                </Space>
                <Divider style={{margin:'8px 0'}}/>
                <Space size={[6,6]} wrap>
                  <Tag.CheckableTag checked={conceptActiveChip==='all'} onChange={()=>setConceptActiveChip('all')}
                    style={{border:'1px solid #d9d9d9',padding:'2px 10px',borderRadius:14,fontSize:12}}>
                    🔥 全部
                  </Tag.CheckableTag>
                  {FINE_GRAINED_CONCEPTS.map(chip=>(
                    <Tag.CheckableTag key={chip.label} checked={conceptActiveChip===chip.label}
                      onChange={()=>setConceptActiveChip(chip.label)}
                      style={{border:'1px solid #722ed1',padding:'2px 10px',borderRadius:14,fontSize:12}}>
                      <AimOutlined style={{marginRight:2}}/>{chip.label}
                    </Tag.CheckableTag>
                  ))}
                </Space>
              </Card>

              {/* Row 3 — chart + quick lookup */}
              <Row gutter={[12,12]}>
                <Col span={14}>
                  <Card size='small' title={<span><BarChartOutlined/> 概念板块正股分布 Top 200 (紫色=双源·青色=东财·橙色=同花顺, 同股数时按动量排序)</span>}
                    styles={{body:{padding:8}}}>
                    <ReactEChartsCore echarts={echarts} option={conceptChartOption} style={{height:520}} notMerge/>
                  </Card>
                </Col>
                <Col span={10}>
                  <Card size='small' title={<span><TagsOutlined/> 快查列表 (按股票数)</span>}
                    extra={<Badge count={filteredConcepts.length} style={{backgroundColor:'#722ed1'}}/>}
                    styles={{body:{padding:0, maxHeight:520, overflow:'auto'}}}>
                    <Table dataSource={filteredConcepts.map((c,i)=>({...c,key:i}))}
                      columns={[
                        { title:'概念', dataIndex:'concept', key:'concept', width:130,
                          sorter:(a:any,b:any)=>(a.concept??'').localeCompare(b.concept??'','zh'),
                          render:(v:string,r:StockConceptAgg)=>(
                            <Space size={2} wrap>
                              <Text style={{fontWeight:600}}>{v}</Text>
                              {r.sources.map(s=>(
                                <Tag key={s} color={s==='eastmoney'?'#13c2c2':'#9254de'}
                                  style={{margin:0,fontSize:9,padding:'0 4px',lineHeight:'14px'}}>
                                  {s==='eastmoney'?'东财':'同花顺'}
                                </Tag>
                              ))}
                            </Space>
                          )},
                        { title:'正股数', dataIndex:'stock_count', key:'stock_count', width:70,
                          sorter:(a:any,b:any)=>a.stock_count-b.stock_count, defaultSortOrder:'descend' as const,
                          render:(v:number)=><Tag color='#722ed1' style={{margin:0,fontWeight:600}}>{v}</Tag>},
                        { title:'5日动量', dataIndex:'avg_momentum_5d', key:'m5', width:80,
                          sorter:(a:any,b:any)=>(a.avg_momentum_5d??0)-(b.avg_momentum_5d??0),
                          render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontSize:12}}>{fmtPct(v)}</span>},
                        { title:'10日动量', dataIndex:'avg_momentum_10d', key:'m10', width:80,
                          sorter:(a:any,b:any)=>(a.avg_momentum_10d??0)-(b.avg_momentum_10d??0),
                          render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontSize:12}}>{fmtPct(v)}</span>},
                        { title:'20日动量', dataIndex:'avg_momentum_20d', key:'m20', width:90,
                          sorter:(a:any,b:any)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),
                          render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
                        { title:'操作', key:'op', width:60,
                          render:(_:any,r:StockConceptAgg)=>(
                            <Button size='small' type='link' icon={<ExpandOutlined/>}
                              onClick={()=>{setDetailConcept(r);setDetailConceptOpen(true)}}>展开</Button>
                          )},
                      ]}
                      size='small' pagination={false} scroll={{y:460}}/>
                  </Card>
                </Col>
              </Row>

              {/* Row 4 — full sortable table */}
              <Card size='small' title={<span><DashboardOutlined/> 概念板块全量排行 (动量+估值+资金+质量)</span>}
                styles={{body:{padding:0}}}>
                <Table dataSource={filteredConcepts.map((c,i)=>({...c,key:i}))}
                  columns={[
                    { title:'概念', dataIndex:'concept', key:'concept', width:160, fixed:'left' as const,
                      render:(v:string,r:StockConceptAgg)=>(
                        <Space size={4} wrap>
                          <Text strong style={{color:'#722ed1'}}>{v}</Text>
                          {r.sources.map(s=>(
                            <Tag key={s} color={s==='eastmoney'?'#13c2c2':'#9254de'}
                              style={{margin:0,fontSize:10,padding:'0 5px'}}>
                              {s==='eastmoney'?'东财':'同花顺'}
                            </Tag>
                          ))}
                        </Space>
                      ),
                      sorter:(a:any,b:any)=>a.concept.localeCompare(b.concept,'zh')},
                    { title:'正股数', dataIndex:'stock_count', key:'sc', width:75,
                      sorter:(a:any,b:any)=>a.stock_count-b.stock_count, defaultSortOrder:'descend' as const,
                      render:(v:number)=><Tag color='#722ed1' style={{margin:0,fontWeight:600,minWidth:36,textAlign:'center'}}>{v}</Tag>},
                    { title:'涨跌幅', dataIndex:'avg_stock_change_pct', key:'chg', width:80,
                      sorter:(a:any,b:any)=>(a.avg_stock_change_pct??0)-(b.avg_stock_change_pct??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
                    { title:'5日动量', dataIndex:'avg_momentum_5d', key:'m5', width:80,
                      sorter:(a:any,b:any)=>(a.avg_momentum_5d??0)-(b.avg_momentum_5d??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    { title:'10日动量', dataIndex:'avg_momentum_10d', key:'m10', width:80,
                      sorter:(a:any,b:any)=>(a.avg_momentum_10d??0)-(b.avg_momentum_10d??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    { title:'20日动量', dataIndex:'avg_momentum_20d', key:'m20', width:85,
                      sorter:(a:any,b:any)=>(a.avg_momentum_20d??0)-(b.avg_momentum_20d??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtPct(v)}</span>},
                    { title:'60日动量', dataIndex:'avg_momentum_60d', key:'m60', width:85,
                      sorter:(a:any,b:any)=>(a.avg_momentum_60d??0)-(b.avg_momentum_60d??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a'}}>{fmtPct(v)}</span>},
                    { title:'ROE', dataIndex:'avg_roe', key:'roe', width:70,
                      sorter:(a:any,b:any)=>(a.avg_roe??0)-(b.avg_roe??0),
                      render:(v:number)=><span style={{color:v>=12?'#52c41a':v>=6?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
                    { title:'PE', dataIndex:'avg_pe', key:'pe', width:65,
                      sorter:(a:any,b:any)=>(a.avg_pe??0)-(b.avg_pe??0),
                      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
                    { title:'PB', dataIndex:'avg_pb', key:'pb', width:65,
                      sorter:(a:any,b:any)=>(a.avg_pb??0)-(b.avg_pb??0),
                      render:(v:number)=><span>{v>0?fmt(v):'-'}</span>},
                    { title:'毛利率', dataIndex:'avg_gpm', key:'gpm', width:75,
                      sorter:(a:any,b:any)=>(a.avg_gpm??0)-(b.avg_gpm??0),
                      render:(v:number)=><span style={{color:v>=30?'#52c41a':v>=15?'#faad14':'#ff4d4f'}}>{fmt(v)}%</span>},
                    { title:'主力资金', dataIndex:'net_capital_flow', key:'flow', width:100,
                      sorter:(a:any,b:any)=>(a.net_capital_flow??0)-(b.net_capital_flow??0),
                      render:(v:number)=><span style={{color:v>=0?'#ff4d4f':'#52c41a',fontWeight:600}}>{fmtFlow(v)}</span>},
                    { title:'换手率', dataIndex:'avg_turnover_rate', key:'tr', width:75,
                      sorter:(a:any,b:any)=>(a.avg_turnover_rate??0)-(b.avg_turnover_rate??0),
                      render:(v:number)=><span>{fmt(v)}%</span>},
                    { title:'涨/跌', key:'ud', width:75,
                      sorter:(a:any,b:any)=>(a.up_count??0)-(b.up_count??0),
                      render:(_:any,r:StockConceptAgg)=><span><span style={{color:'#ff4d4f'}}>{r.up_count}</span>/<span style={{color:'#52c41a'}}>{r.down_count}</span></span>},
                    { title:'操作', key:'op', width:70, fixed:'right' as const,
                      render:(_:any,r:StockConceptAgg)=><Button type='link' size='small' icon={<ExpandOutlined/>}
                        onClick={()=>{setDetailConcept(r);setDetailConceptOpen(true)}}>正股</Button>},
                  ]}
                  size='small' pagination={{pageSize:20,showTotal:t=>`共 ${t} 个概念`}} scroll={{x:1500,y:500}}/>
              </Card>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 9 — 事件驱动 (北向/融资/龙虎榜/大宗/股东/业绩/解禁)
          // ════════════════════════════════════════════════════════
          {key:'events', label:<span><ThunderboltOutlined/> 事件驱动</span>, children: (
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Tabs type='card' size='small' items={[
                {key:'north', label:<span><TeamOutlined/> 北向资金</span>, children: northLoading?renderSkeleton():!northData?<Empty description='暂无北向资金数据'><Button size='small' onClick={loadNorth}>加载</Button></Empty>:(
                  <Card size='small' title={`北向资金 (${northData.stocks.length} 只)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={northData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'持仓市值(亿)',dataIndex:'hold_market_cap',width:130,align:'right',sorter:(a:any,b:any)=>(a.hold_market_cap??0)-(b.hold_market_cap??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'持股占比(%)',dataIndex:'hold_ratio',width:120,align:'right',sorter:(a:any,b:any)=>(a.hold_ratio??0)-(b.hold_ratio??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                      {title:'当日净买入(万)',dataIndex:'net_buy_amt',width:130,align:'right',sorter:(a:any,b:any)=>(a.net_buy_amt??0)-(b.net_buy_amt??0),render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                      {title:'占流通比(%)',dataIndex:'net_buy_ratio',width:120,align:'right',sorter:(a:any,b:any)=>(a.net_buy_ratio??0)-(b.net_buy_ratio??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                      {title:'统计日期',dataIndex:'stat_date',width:120},
                    ]}/>
                  </Card>
                )},
                {key:'margin', label:<span><BankOutlined/> 融资融券</span>, children: marginLoading?renderSkeleton():!marginData?<Empty description='暂无融资融券数据'><Button size='small' onClick={loadMargin}>加载</Button></Empty>:(
                  <Card size='small' title={`融资融券 (${marginData.stocks.length} 只)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={marginData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'融资余额(亿)',dataIndex:'rzye',width:130,align:'right',sorter:(a:any,b:any)=>(a.rzye??0)-(b.rzye??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'融资买入额(亿)',dataIndex:'rzmre',width:130,align:'right',sorter:(a:any,b:any)=>(a.rzmre??0)-(b.rzmre??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'融券余量(万)',dataIndex:'rqyl',width:120,align:'right',sorter:(a:any,b:any)=>(a.rqyl??0)-(b.rqyl??0),render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                      {title:'融资融券余额(亿)',dataIndex:'rzrqye',width:140,align:'right',sorter:(a:any,b:any)=>(a.rzrqye??0)-(b.rzrqye??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                    ]}/>
                  </Card>
                )},
                {key:'lhb', label:<span><FireOutlined/> 龙虎榜</span>, children: lhbLoading?renderSkeleton():!lhbData?<Empty description='暂无龙虎榜数据'><Button size='small' onClick={loadLhb}>加载</Button></Empty>:(
                  <Card size='small' title={`龙虎榜 (${lhbData.stocks.length} 只)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={lhbData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'上榜次数',dataIndex:'times',width:100,align:'right',sorter:(a:any,b:any)=>(a.times??0)-(b.times??0)},
                      {title:'买入总额(亿)',dataIndex:'buy_amt',width:130,align:'right',sorter:(a:any,b:any)=>(a.buy_amt??0)-(b.buy_amt??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'卖出总额(亿)',dataIndex:'sell_amt',width:130,align:'right',sorter:(a:any,b:any)=>(a.sell_amt??0)-(b.sell_amt??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'净买入(亿)',dataIndex:'net_buy_amt',width:130,align:'right',sorter:(a:any,b:any)=>(a.net_buy_amt??0)-(b.net_buy_amt??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                    ]}/>
                  </Card>
                )},
                {key:'blocktrade', label:<span><DollarOutlined/> 大宗交易</span>, children: blockTradeLoading?renderSkeleton():!blockTradeData?<Empty description='暂无大宗交易数据'><Button size='small' onClick={loadBlockTrade}>加载</Button></Empty>:(
                  <Card size='small' title={`大宗交易 (${blockTradeData.stocks.length} 只)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={blockTradeData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'成交总额(亿)',dataIndex:'total_amt',width:130,align:'right',sorter:(a:any,b:any)=>(a.total_amt??0)-(b.total_amt??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'成交次数',dataIndex:'trade_count',width:100,align:'right',sorter:(a:any,b:any)=>(a.trade_count??0)-(b.trade_count??0)},
                      {title:'平均折价率',dataIndex:'avg_discount',width:120,align:'right',sorter:(a:any,b:any)=>(a.avg_discount??0)-(b.avg_discount??0),render:(v)=>v!=null?(v*100).toFixed(2)+'%':'-'},
                      {title:'最高价',dataIndex:'max_price',width:100,align:'right',sorter:(a:any,b:any)=>(a.max_price??0)-(b.max_price??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                      {title:'最低价',dataIndex:'min_price',width:100,align:'right',sorter:(a:any,b:any)=>(a.min_price??0)-(b.min_price??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                    ]}/>
                  </Card>
                )},
                {key:'holder', label:<span><TeamOutlined/> 股东户数</span>, children: holderLoading?renderSkeleton():!holderData?<Empty description='暂无股东户数数据'><Button size='small' onClick={loadHolder}>加载</Button></Empty>:(
                  <Card size='small' title={`股东户数 (${holderData.stocks.length} 只)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={holderData.stocks.slice(0,100).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 只`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'股东户数',dataIndex:'holder_num',width:130,align:'right',sorter:(a:any,b:any)=>(a.holder_num??0)-(b.holder_num??0),render:(v)=>v!=null?v.toLocaleString():'-'},
                      {title:'较上期变化',dataIndex:'change_pct',width:120,align:'right',sorter:(a:any,b:any)=>(a.change_pct??0)-(b.change_pct??0),render:(v)=>fmtPct(v)},
                      {title:'平均持股(万)',dataIndex:'avg_hold_shares',width:120,align:'right',sorter:(a:any,b:any)=>(a.avg_hold_shares??0)-(b.avg_hold_shares??0),render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                      {title:'统计日期',dataIndex:'stat_date',width:120},
                    ]}/>
                  </Card>
                )},
                {key:'forecast', label:<span><RiseOutlined/> 业绩预告</span>, children: forecastLoading?renderSkeleton():!forecastData?<Empty description='暂无业绩预告数据'><Button size='small' onClick={loadForecast}>加载</Button></Empty>:(
                  <Card size='small' title={`业绩预告 (${forecastData.stocks.length} 条)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={forecastData.stocks.slice(0,200).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'报告期',dataIndex:'period',width:100},
                      {title:'预告类型',dataIndex:'forecast_type',width:120,render:(v)=><Tag color={v?.includes('增')?'green':v?.includes('减')?'red':'orange'}>{v||'-'}</Tag>},
                      {title:'变动下限(%)',dataIndex:'change_pct_min',width:120,align:'right',sorter:(a:any,b:any)=>(a.change_pct_min??0)-(b.change_pct_min??0),render:(v)=>fmtPct(v)},
                      {title:'变动上限(%)',dataIndex:'change_pct_max',width:120,align:'right',sorter:(a:any,b:any)=>(a.change_pct_max??0)-(b.change_pct_max??0),render:(v)=>fmtPct(v)},
                      {title:'摘要',dataIndex:'summary',ellipsis:true,render:(v)=><Tooltip title={v}><Text style={{fontSize:11}}>{(v||'').slice(0,50)}{v&&v.length>50?'...':''}</Text></Tooltip>},
                    ]}/>
                  </Card>
                )},
                {key:'express', label:<span><TrophyOutlined/> 业绩快报</span>, children: expressLoading?renderSkeleton():!expressData?<Empty description='暂无业绩快报数据'><Button size='small' onClick={loadExpress}>加载</Button></Empty>:(
                  <Card size='small' title={`业绩快报 (${expressData.stocks.length} 条)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={expressData.stocks.slice(0,200).map((s,i)=>({...s,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'报告期',dataIndex:'period',width:100},
                      {title:'营收(亿)',dataIndex:'revenue',width:110,align:'right',sorter:(a:any,b:any)=>(a.revenue??0)-(b.revenue??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'营收同比增长',dataIndex:'revenue_yoy',width:130,align:'right',sorter:(a:any,b:any)=>(a.revenue_yoy??0)-(b.revenue_yoy??0),render:(v)=>fmtPct(v)},
                      {title:'净利润(亿)',dataIndex:'net_profit',width:110,align:'right',sorter:(a:any,b:any)=>(a.net_profit??0)-(b.net_profit??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'净利润增长',dataIndex:'net_profit_yoy',width:130,align:'right',sorter:(a:any,b:any)=>(a.net_profit_yoy??0)-(b.net_profit_yoy??0),render:(v)=>fmtPct(v)},
                      {title:'EPS',dataIndex:'eps',width:80,align:'right',sorter:(a:any,b:any)=>(a.eps??0)-(b.eps??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                      {title:'ROE(%)',dataIndex:'roe',width:80,align:'right',sorter:(a:any,b:any)=>(a.roe??0)-(b.roe??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                    ]}/>
                  </Card>
                )},
                {key:'release', label:<span><CalendarOutlined/> 限售解禁</span>, children: releaseLoading?renderSkeleton():!releaseData?<Empty description='暂无限售解禁数据'><Button size='small' onClick={loadRelease}>加载</Button></Empty>:(
                  <Card size='small' title={`未来 90 天限售解禁 TOP 100 (${releaseData.events.length} 条)`} styles={{body:{padding:0}}}>
                    <Table size='small' dataSource={releaseData.events.slice(0,100).map((e,i)=>({...e,key:i}))} pagination={{pageSize:50,showTotal:t=>`共 ${t} 条`}} scroll={{y:500}} columns={[
                      {title:'代码',dataIndex:'code',width:80,sorter:(a:any,b:any)=>a.code?.localeCompare?.(b.code,'zh')??0},
                      {title:'名称',dataIndex:'name',width:100,sorter:(a:any,b:any)=>a.name?.localeCompare?.(b.name,'zh')??0},
                      {title:'解禁日期',dataIndex:'release_date',width:120},
                      {title:'解禁股数(万)',dataIndex:'release_shares',width:130,align:'right',sorter:(a:any,b:any)=>(a.release_shares??0)-(b.release_shares??0),render:(v)=>v!=null?(v/10000).toFixed(2):'-'},
                      {title:'解禁市值(亿)',dataIndex:'release_market_cap',width:130,align:'right',sorter:(a:any,b:any)=>(a.release_market_cap??0)-(b.release_market_cap??0),render:(v)=>v!=null?(v/1e8).toFixed(2):'-'},
                      {title:'占流通比(%)',dataIndex:'release_ratio',width:120,align:'right',sorter:(a:any,b:any)=>(a.release_ratio??0)-(b.release_ratio??0),render:(v)=>v!=null?v.toFixed(2):'-'},
                      {title:'性质',dataIndex:'release_type',width:120,render:(v)=><Tag color='orange'>{v||'-'}</Tag>},
                      {title:'股东数',dataIndex:'shareholder_count',width:90,align:'right',sorter:(a:any,b:any)=>(a.shareholder_count??0)-(b.shareholder_count??0)},
                    ]}/>
                  </Card>
                )},
              ]}/>
            </div>
          )},

          // ════════════════════════════════════════════════════════
          //  TAB 10 — 布局推荐 (短期/中期/长期)
          // ════════════════════════════════════════════════════════
          {key:'recommend', label:<span><StarOutlined/> 布局推荐</span>, children: (
            <div style={{flex:1,display:'flex',flexDirection:'column',gap:12,overflow:'auto'}}>
              <Tabs type='card' size='small' activeKey={recSubTab} onChange={setRecSubTab} items={[
                {key:'current', label:<span><StarOutlined/> 当前推荐</span>, children: (
                  recLoading ? renderSkeleton() : !recommendData ? <Empty description='暂无推荐数据'><Button size='small' onClick={loadRecommendations}>加载推荐</Button></Empty> : (
                  <>
                  {recommendData.generated_at && <div style={{textAlign:'right',color:themeToken.colorTextSecondary,fontSize:12}}>生成时间: {recommendData.generated_at}</div>}
                  {/* Weight adjustment panel */}
                  <Card size='small' title={<span><SettingOutlined/> 因子权重调节</span>}
                    style={{borderRadius:8,border:'1px dashed '+themeToken.colorBorder}}
                    styles={{body:{padding:'8px 16px'}}}
                    extra={<span><Button size='small' style={{marginRight:8}} onClick={()=>setHorizonWeights({short_term:{momentum:60,flow:25,turnover:15},mid_term:{momentum:50,trend_confirm:20,flow:20,quality:10},long_term:{momentum:40,long_trend:25,quality:20,gpm:10,valuation:5}})}>重置默认</Button><Button size='small' type='primary' loading={recLoading} onClick={loadRecommendations}>应用权重</Button></span>}>
                    <Row gutter={[12,8]}>
                      <Col xs={24} sm={8}>
                        <Text strong style={{color:'#ff4d4f',fontSize:12}}>短期权重</Text>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>动量</Text>
                          <Slider min={0} max={100} value={horizonWeights.short_term.momentum} onChange={v=>setHorizonWeights(w=>({...w,short_term:{...w.short_term,momentum:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.short_term.momentum}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>资金</Text>
                          <Slider min={0} max={100} value={horizonWeights.short_term.flow} onChange={v=>setHorizonWeights(w=>({...w,short_term:{...w.short_term,flow:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.short_term.flow}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>换手</Text>
                          <Slider min={0} max={100} value={horizonWeights.short_term.turnover} onChange={v=>setHorizonWeights(w=>({...w,short_term:{...w.short_term,turnover:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.short_term.turnover}%</Text>
                        </div>
                      </Col>
                      <Col xs={24} sm={8}>
                        <Text strong style={{color:'#fa8c16',fontSize:12}}>中期权重</Text>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>动量</Text>
                          <Slider min={0} max={100} value={horizonWeights.mid_term.momentum} onChange={v=>setHorizonWeights(w=>({...w,mid_term:{...w.mid_term,momentum:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.mid_term.momentum}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>趋势</Text>
                          <Slider min={0} max={100} value={horizonWeights.mid_term.trend_confirm} onChange={v=>setHorizonWeights(w=>({...w,mid_term:{...w.mid_term,trend_confirm:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.mid_term.trend_confirm}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>资金</Text>
                          <Slider min={0} max={100} value={horizonWeights.mid_term.flow} onChange={v=>setHorizonWeights(w=>({...w,mid_term:{...w.mid_term,flow:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.mid_term.flow}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>质地</Text>
                          <Slider min={0} max={100} value={horizonWeights.mid_term.quality} onChange={v=>setHorizonWeights(w=>({...w,mid_term:{...w.mid_term,quality:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.mid_term.quality}%</Text>
                        </div>
                      </Col>
                      <Col xs={24} sm={8}>
                        <Text strong style={{color:'#722ed1',fontSize:12}}>长期权重</Text>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>动量</Text>
                          <Slider min={0} max={100} value={horizonWeights.long_term.momentum} onChange={v=>setHorizonWeights(w=>({...w,long_term:{...w.long_term,momentum:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.long_term.momentum}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>长趋势</Text>
                          <Slider min={0} max={100} value={horizonWeights.long_term.long_trend} onChange={v=>setHorizonWeights(w=>({...w,long_term:{...w.long_term,long_trend:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.long_term.long_trend}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>质地</Text>
                          <Slider min={0} max={100} value={horizonWeights.long_term.quality} onChange={v=>setHorizonWeights(w=>({...w,long_term:{...w.long_term,quality:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.long_term.quality}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>毛利</Text>
                          <Slider min={0} max={100} value={horizonWeights.long_term.gpm} onChange={v=>setHorizonWeights(w=>({...w,long_term:{...w.long_term,gpm:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.long_term.gpm}%</Text>
                        </div>
                        <div style={{display:'flex',alignItems:'center',gap:8}}>
                          <Text type='secondary' style={{fontSize:11,width:48}}>估值</Text>
                          <Slider min={0} max={100} value={horizonWeights.long_term.valuation} onChange={v=>setHorizonWeights(w=>({...w,long_term:{...w.long_term,valuation:v}}))} style={{flex:1,margin:0}}/>
                          <Text style={{fontSize:11,width:28}}>{horizonWeights.long_term.valuation}%</Text>
                        </div>
                      </Col>
                    </Row>
                  </Card>
                  <Row gutter={[16,16]}>
                    {/* ── 短期推荐 (≤1周) ── */}
                    <Col xs={24} sm={8}>
                      <Card size='small' title={<span><RocketOutlined style={{color:'#ff4d4f'}}/> 短期布局 (≤1周)</span>}
                        extra={<Tag color='red'>5日动量驱动</Tag>}
                        styles={{body:{padding:8,maxHeight:"min(600px, 50vh)",overflow:'auto',overscrollBehavior:'contain'}}}>
                        {recommendData.short_term.length === 0 ? <Empty description='当前无短期强势行业' image={Empty.PRESENTED_IMAGE_SIMPLE}/> : recommendData.short_term.map((rec,idx)=>(
                          <Card key={rec.industry} size='small' style={{marginBottom:8,borderLeft:'3px solid '+indColor(rec.industry)}}
                            styles={{body:{padding:'8px 12px'}}}>
                            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                              <span style={{fontWeight:700,color:indColor(rec.industry),fontSize:14}}>
                                <Tag color={idx===0?'red':idx<3?'orange':'blue'} style={{marginRight:4}}>#{idx+1}</Tag>
                                {rec.industry}
                              </span>
                              <Tag color={rec.score>=70?'#52c41a':rec.score>=55?'#faad14':'#8c8c8c'} style={{fontWeight:700}}>
                                {rec.score}分
                              </Tag>
                            </div>
                            <div style={{fontSize:11,color:themeToken.colorTextSecondary,marginBottom:4}}>
                              5日动量 {fmtPct(rec.metrics.momentum_5d)} · 10日 {fmtPct(rec.metrics.momentum_10d)} · ROE {fmt(rec.metrics.avg_roe)}%
                            </div>
                            <div style={{display:'flex',flexDirection:'column',gap:2}}>
                              {rec.reasons.map((r,i)=><span key={i} style={{fontSize:12}}><CheckCircleOutlined style={{color:'#52c41a',marginRight:4}}/>{r}</span>)}
                            </div>
                            <div style={{marginTop:6,textAlign:'right'}}>
                              {aiInsight[rec.industry+':short_term']
                                ? <div style={{fontSize:12,color:themeToken.colorTextSecondary,background:isDark?'#1a1a2e':'#f6ffed',padding:6,borderRadius:6,marginTop:4,textAlign:'left'}}><BulbOutlined style={{color:'#faad14',marginRight:4}}/>{aiInsight[rec.industry+':short_term']}</div>
                                : <Button size='small' type='link' loading={aiLoading===rec.industry+':short_term'} onClick={()=>handleAIInsight(rec.industry,'short_term',rec.metrics)}><BulbOutlined/> AI解读</Button>
                              }
                            </div>
                          </Card>
                        ))}
                      </Card>
                    </Col>
                    {/* ── 中期推荐 (2周) ── */}
                    <Col xs={24} sm={8}>
                      <Card size='small' title={<span><FieldTimeOutlined style={{color:'#fa8c16'}}/> 中期布局 (2周)</span>}
                        extra={<Tag color='orange'>10日动量+趋势确认</Tag>}
                        styles={{body:{padding:8,maxHeight:"min(600px, 50vh)",overflow:'auto',overscrollBehavior:'contain'}}}>
                        {recommendData.mid_term.length === 0 ? <Empty description='当前无中期看多行业' image={Empty.PRESENTED_IMAGE_SIMPLE}/> : recommendData.mid_term.map((rec,idx)=>(
                          <Card key={rec.industry} size='small' style={{marginBottom:8,borderLeft:'3px solid '+indColor(rec.industry)}}
                            styles={{body:{padding:'8px 12px'}}}>
                            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                              <span style={{fontWeight:700,color:indColor(rec.industry),fontSize:14}}>
                                <Tag color={idx===0?'red':idx<3?'orange':'blue'} style={{marginRight:4}}>#{idx+1}</Tag>
                                {rec.industry}
                              </span>
                              <Tag color={rec.score>=70?'#52c41a':rec.score>=50?'#faad14':'#8c8c8c'} style={{fontWeight:700}}>
                                {rec.score}分
                              </Tag>
                            </div>
                            <div style={{fontSize:11,color:themeToken.colorTextSecondary,marginBottom:4}}>
                              10日动量 {fmtPct(rec.metrics.momentum_10d)} · 20日 {fmtPct(rec.metrics.momentum_20d)} · 资金占比 {(rec.metrics.net_capital_flow_pct*100).toFixed(2)}%
                            </div>
                            <div style={{display:'flex',flexDirection:'column',gap:2}}>
                              {rec.reasons.map((r,i)=><span key={i} style={{fontSize:12}}><CheckCircleOutlined style={{color:'#52c41a',marginRight:4}}/>{r}</span>)}
                            </div>
                            <div style={{marginTop:6,textAlign:'right'}}>
                              {aiInsight[rec.industry+':mid_term']
                                ? <div style={{fontSize:12,color:themeToken.colorTextSecondary,background:isDark?'#1a1a2e':'#f6ffed',padding:6,borderRadius:6,marginTop:4,textAlign:'left'}}><BulbOutlined style={{color:'#faad14',marginRight:4}}/>{aiInsight[rec.industry+':mid_term']}</div>
                                : <Button size='small' type='link' loading={aiLoading===rec.industry+':mid_term'} onClick={()=>handleAIInsight(rec.industry,'mid_term',rec.metrics)}><BulbOutlined/> AI解读</Button>
                              }
                            </div>
                          </Card>
                        ))}
                      </Card>
                    </Col>
                    {/* ── 长期推荐 (1月) ── */}
                    <Col xs={24} sm={8}>
                      <Card size='small' title={<span><CrownOutlined style={{color:'#722ed1'}}/> 长期布局 (1月)</span>}
                        extra={<Tag color='purple'>20日+60日趋势+质地</Tag>}
                        styles={{body:{padding:8,maxHeight:"min(600px, 50vh)",overflow:'auto',overscrollBehavior:'contain'}}}>
                        {recommendData.long_term.length === 0 ? <Empty description='当前无长期看多行业' image={Empty.PRESENTED_IMAGE_SIMPLE}/> : recommendData.long_term.map((rec,idx)=>(
                          <Card key={rec.industry} size='small' style={{marginBottom:8,borderLeft:'3px solid '+indColor(rec.industry)}}
                            styles={{body:{padding:'8px 12px'}}}>
                            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                              <span style={{fontWeight:700,color:indColor(rec.industry),fontSize:14}}>
                                <Tag color={idx===0?'red':idx<3?'orange':'blue'} style={{marginRight:4}}>#{idx+1}</Tag>
                                {rec.industry}
                              </span>
                              <Tag color={rec.score>=70?'#52c41a':rec.score>=45?'#faad14':'#8c8c8c'} style={{fontWeight:700}}>
                                {rec.score}分
                              </Tag>
                            </div>
                            <div style={{fontSize:11,color:themeToken.colorTextSecondary,marginBottom:4}}>
                              20日动量 {fmtPct(rec.metrics.momentum_20d)} · 60日 {fmtPct(rec.metrics.momentum_60d)} · ROE {fmt(rec.metrics.avg_roe)}% · PE {rec.metrics.avg_pe>0?fmt(rec.metrics.avg_pe):'-'}
                            </div>
                            <div style={{display:'flex',flexDirection:'column',gap:2}}>
                              {rec.reasons.map((r,i)=><span key={i} style={{fontSize:12}}><CheckCircleOutlined style={{color:'#52c41a',marginRight:4}}/>{r}</span>)}
                            </div>
                            <div style={{marginTop:6,textAlign:'right'}}>
                              {aiInsight[rec.industry+':long_term']
                                ? <div style={{fontSize:12,color:themeToken.colorTextSecondary,background:isDark?'#1a1a2e':'#f6ffed',padding:6,borderRadius:6,marginTop:4,textAlign:'left'}}><BulbOutlined style={{color:'#faad14',marginRight:4}}/>{aiInsight[rec.industry+':long_term']}</div>
                                : <Button size='small' type='link' loading={aiLoading===rec.industry+':long_term'} onClick={()=>handleAIInsight(rec.industry,'long_term',rec.metrics)}><BulbOutlined/> AI解读</Button>
                              }
                            </div>
                          </Card>
                        ))}
                      </Card>
                    </Col>
                  </Row>
                </>
                  )
                )},
                  {key:'history', label:<span><CalendarOutlined/> 历史回测</span>, children: renderRecHistoryTab()},
                ]}/>
            </div>
          )},
        ]}
      />

      {renderDetailModal()}
      {renderConceptDetailModal()}
    </div>
  )
}
