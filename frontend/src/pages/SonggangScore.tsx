/**
 * 七维详情分析页面
 *
 * 七维评分体系：
 * - 正股七维（55分）：短期动量、板块情绪、技术面、筹码面、波动率、消息面、基本面
 * - 转债自身（45分）：估值指标、条款价值、流动性、信用评分
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Modal, Descriptions,
  Alert, Divider, DatePicker, InputNumber, Tooltip
} from 'antd'
import {
  TrophyOutlined, ReloadOutlined, StarOutlined,
  AlertOutlined, CloseCircleOutlined, InfoCircleOutlined, SaveOutlined,
  ThunderboltOutlined, LineChartOutlined
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import VirtualTable from '../components/VirtualTable'
import type { VirtualColumn } from '../components/VirtualTable'
import {
  fetchSonggangRanking, fetchSonggangSingleScore, fetchSonggangHistory, saveSonggangSnapshot,
  streamSonggangRanking, runBacktest,
  type SonggangScoreItem, type SonggangVetoedItem, type BufferStatusItem,
  type SonggangSingleScore, type SevenDimHistoryItem, type BacktestResult,
  type MarketChangeStats
} from '../services/api'
import { fmt } from '../utils/format'
import dayjs from 'dayjs'

const { Title, Text } = Typography

const STORAGE_KEY = 'songgang_score_config'

type AumLevel = 'small' | 'medium' | 'large'
type MarketEnv = 'bull' | 'bear' | 'neutral'

// 七维评分颜色映射
const scoreColor = (v: number, max: number = 100) => {
  const ratio = v / max
  if (ratio >= 0.8) return '#52c41a'
  if (ratio >= 0.6) return '#1677ff'
  if (ratio >= 0.4) return '#faad14'
  return '#ff4d4f'
}

// 涨跌幅颜色：A 股惯例 红涨绿跌
const changeColor = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '#999'
  if (v > 0) return '#ff4d4f'
  if (v < 0) return '#52c41a'
  return '#666'
}

// 涨跌幅单元格渲染：null 显示 "数据不足"
const renderChangeCell = (v: number | null | undefined, suffix = '%') => {
  if (v == null || !Number.isFinite(v)) {
    return <span style={{ color: '#bbb', fontSize: 12 }}>数据不足</span>
  }
  return (
    <span style={{ color: changeColor(v), fontWeight: 500 }}>
      {v > 0 ? '+' : ''}{v.toFixed(2)}{suffix}
    </span>
  )
}

// 维度名称映射
const STOCK_DIMENSION_NAMES: Record<string, string> = {
  momentum: '短期动量',
  sector: '板块情绪',
  technical: '技术面',
  chip: '筹码面',
  volatility: '波动率',
  news: '消息面',
  fundamental: '基本面',
}

const BOND_DIMENSION_NAMES: Record<string, string> = {
  valuation: '估值指标',
  clause: '条款价值',
  liquidity: '流动性',
  credit: '信用评分',
}

const VALID_AUM_LEVELS = new Set<string>(['small', 'medium', 'large'])
const VALID_MARKET_ENVS = new Set<string>(['bull', 'bear', 'neutral'])

// 加载配置（带验证）
function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      return {
        topN: typeof parsed.topN === 'number' && parsed.topN >= 10 && parsed.topN <= 100 ? parsed.topN : 60,
        aumLevel: VALID_AUM_LEVELS.has(parsed.aumLevel) ? parsed.aumLevel as AumLevel : 'small' as AumLevel,
        marketEnv: VALID_MARKET_ENVS.has(parsed.marketEnv) ? parsed.marketEnv as MarketEnv : 'neutral' as MarketEnv,
      }
    }
  } catch { /* ignore corrupt data */ }
  return { topN: 60, aumLevel: 'small' as AumLevel, marketEnv: 'neutral' as MarketEnv }
}

function saveConfig(config: { topN: number; aumLevel: AumLevel; marketEnv: MarketEnv }) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

// 安全提取错误信息
function getErrorMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  if (typeof e === 'string') return e
  return '未知错误'
}

export default function SonggangScore() {
  const [vetoedPage, setVetoedPage] = useState(1)
  const [vetoedPageSize, setVetoedPageSize] = useState(10)
  const [bufferPage, setBufferPage] = useState(1)
  const [bufferPageSize, setBufferPageSize] = useState(10)
  const [tradesPage, setTradesPage] = useState(1)
  const [tradesPageSize, setTradesPageSize] = useState(10)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [data, setData] = useState<{
    total: number
    returned: number
    market_env: string
    aum_level: string
    items: SonggangScoreItem[]
    vetoed: SonggangVetoedItem[]
    vetoed_count: number
    buffer_status: BufferStatusItem[]
    market_stats?: MarketChangeStats
  } | null>(null)

  // [Fix #4] useState 惰性初始化替代 useMemo 副作用
  const [topN, setTopN] = useState(() => loadConfig().topN)
  const [aumLevel, setAumLevel] = useState<AumLevel>(() => loadConfig().aumLevel)
  const [marketEnv, setMarketEnv] = useState<MarketEnv>(() => loadConfig().marketEnv)

  // [Fix #1] SSE 连接引用，用于清理
  const sseRef = useRef<EventSource | null>(null)
  // [Fix #9] 请求序号，防止过期响应覆盖新数据
  const fetchSeqRef = useRef(0)

  // 客户端排序
  type SortKey = 'rank' | 'code' | 'name' | 'price' | 'premium_ratio' | 'dual_low'
    | 'volume' | 'change_pct' | 'ytm' | 'remaining_years'
    | 'total_score' | 'stock_score' | 'bond_score'
    | 'change_1d' | 'change_3d' | 'change_5d' | 'change_10d' | 'change_30d'
  const [sortKey, setSortKey] = useState<SortKey>('rank')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  // 排序后的数据：null 排到末尾
  const sortedItems = useMemo(() => {
    const items = data?.items || []
    if (items.length === 0) return items
    const dir = sortDir === 'asc' ? 1 : -1
    return [...items].sort((a, b) => {
      const av = (a as any)[sortKey]
      const bv = (b as any)[sortKey]
      // null/undefined 排到末尾
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number' && typeof bv === 'number') {
        return (av - bv) * dir
      }
      return String(av).localeCompare(String(bv), 'zh-CN') * dir
    })
  }, [data, sortKey, sortDir])

  const handleSort = useCallback((key: string | number | undefined) => {
    if (!key) return
    const k = String(key) as SortKey
    if (sortKey === k) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(k)
      // 涨跌幅默认降序（看涨幅大的），其他默认升序
      setSortDir(k.startsWith('change_') ? 'desc' : 'asc')
    }
  }, [sortKey, sortDir])

  // 详情弹窗
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [selectedDetail, setSelectedDetail] = useState<SonggangSingleScore | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [historyData, setHistoryData] = useState<SevenDimHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // 被否决列表
  const [vetoedVisible, setVetoedVisible] = useState(false)

  // 缓冲带状态
  const [bufferVisible, setBufferVisible] = useState(false)

  // 回测弹窗
  const [backtestVisible, setBacktestVisible] = useState(false)
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null)
  const [backtestDateRange, setBacktestDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(6, 'month'), dayjs()
  ])

  // [Fix #1] 关闭当前 SSE 连接
  const closeSSE = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close()
      sseRef.current = null
    }
  }, [])

  const fetchData = useCallback(async () => {
    // [Fix #1] 关闭上一次 SSE 连接，防止多个并存
    closeSSE()
    // [Fix #9] 递增请求序号，忽略过期响应
    const seq = ++fetchSeqRef.current
    setLoading(true)
    try {
      const result = await fetchSonggangRanking(topN, aumLevel, marketEnv)
      if (seq !== fetchSeqRef.current) return // 过期响应，丢弃
      setData(result)
      saveConfig({ topN, aumLevel, marketEnv })
    } catch {
      if (seq !== fetchSeqRef.current) return // 过期响应，丢弃
      // 普通API失败时，尝试SSE流式
      const es = streamSonggangRanking(
        { topN, aumLevel, marketEnv },
        () => {}, // progress不再触发
        (doneData) => {
          if (seq !== fetchSeqRef.current) return // 过期响应
          setData(doneData)
          saveConfig({ topN, aumLevel, marketEnv })
          setLoading(false)
          sseRef.current = null
        },
        (err) => {
          if (seq !== fetchSeqRef.current) return // 过期响应
          // SSE失败，降级重试REST API
          message.warning('SSE超时，正在降级重试...')
          fetchSonggangRanking(topN, aumLevel, marketEnv)
            .then((r) => {
              if (seq !== fetchSeqRef.current) return
              setData(r)
              saveConfig({ topN, aumLevel, marketEnv })
            })
            .catch((e) => {
              console.error('[SonggangScore] REST fallback failed:', e)
              const msg = getErrorMessage(e)
              setErrorMsg(msg)
              message.error(`加载失败: ${msg}`)
            })
            .finally(() => {
              if (seq === fetchSeqRef.current) setLoading(false)
              sseRef.current = null
            })
        },
      )
      sseRef.current = es
      // SSE模式：由回调负责关闭loading
      return
    }
    setLoading(false)
  }, [topN, aumLevel, marketEnv, closeSSE])

  // [Fix #1] 组件卸载时清理 SSE 连接
  useEffect(() => {
    fetchData()
    return () => { closeSSE() }
  }, [fetchData, closeSSE])

  // [Fix #3] handleViewDetail 使用 useCallback，使 virtualColumns useMemo 生效
  const handleViewDetail = useCallback(async (code: string) => {
    setSelectedCode(code)
    setDetailVisible(true)
    setDetailLoading(true)
    setHistoryLoading(true)
    try {
      const [detail, hist] = await Promise.all([
        fetchSonggangSingleScore(code, aumLevel),
        fetchSonggangHistory(code, 30).catch(() => ({ items: [] })),
      ])
      setSelectedDetail(detail)
      setHistoryData(hist.items || [])
    } catch (e) {
      console.error('[SonggangScore] load detail failed:', e)
      message.error(`加载详情失败: ${getErrorMessage(e)}`)
    } finally {
      setDetailLoading(false)
      setHistoryLoading(false)
    }
  }, [aumLevel])

  // 市场环境标签
  const getMarketEnvTag = (env: string) => {
    const config: Record<string, { color: string; text: string }> = {
      bull: { color: 'red', text: '牛市' },
      bear: { color: 'green', text: '熊市' },
      neutral: { color: 'blue', text: '震荡市' },
    }
    const c = config[env] || config.neutral
    return <Tag color={c.color}>{c.text}</Tag>
  }

  // AUM等级标签
  const getAumLevelTag = (level: string) => {
    const config: Record<string, { color: string; text: string }> = {
      small: { color: 'blue', text: '<1亿' },
      medium: { color: 'orange', text: '1-5亿' },
      large: { color: 'red', text: '5-10亿' },
    }
    const c = config[level] || config.small
    return <Tag color={c.color}>{c.text}</Tag>
  }

  // [Fix #3] virtualColumns 现在可以正确 memoize（handleViewDetail 是 useCallback）
  const virtualColumns: VirtualColumn<SonggangScoreItem>[] = useMemo(() => [
    { key: 'rank', dataIndex: 'rank', title: '排名', width: 60, sortable: true, sortOrder: sortKey === 'rank' ? sortDir : null, render: (v: unknown) => {
      const rank = v as number
      return <span style={{ fontWeight: 'bold', color: rank <= 10 ? '#faad14' : undefined }}>
        {rank <= 3 ? <TrophyOutlined style={{ color: '#faad14', marginRight: 4 }} /> : null}{rank}
      </span>
    }},
    { key: 'code', dataIndex: 'code', title: '代码', width: 90, sortable: true, sortOrder: sortKey === 'code' ? sortDir : null, render: (v: unknown) => (
      <a onClick={() => handleViewDetail(v as string)} style={{ color: '#1677ff' }}>{v as string}</a>
    )},
    { key: 'name', dataIndex: 'name', title: '名称', width: 100, sortable: true, sortOrder: sortKey === 'name' ? sortDir : null },
    { key: 'price', dataIndex: 'price', title: '价格', width: 80, sortable: true, sortOrder: sortKey === 'price' ? sortDir : null, render: (v: unknown) => {
      const p = v as number
      return <span style={{ color: p < 100 ? '#52c41a' : p > 130 ? '#ff4d4f' : undefined }}>{fmt(p)}</span>
    }},
    { key: 'premium_ratio', dataIndex: 'premium_ratio', title: '溢价率', width: 80, sortable: true, sortOrder: sortKey === 'premium_ratio' ? sortDir : null, render: (v: unknown) => {
      const p = v as number
      return <span style={{ color: p < 20 ? '#52c41a' : p > 50 ? '#ff4d4f' : undefined }}>{fmt(p, 1)}%</span>
    }},
    { key: 'dual_low', dataIndex: 'dual_low', title: '双低值', width: 80, sortable: true, sortOrder: sortKey === 'dual_low' ? sortDir : null, render: (v: unknown) => {
      const d = v as number
      return <span style={{ color: d < 130 ? '#52c41a' : d > 160 ? '#ff4d4f' : undefined }}>{fmt(d, 1)}</span>
    }},
    { key: 'change_1d', dataIndex: 'change_1d', title: '今日', width: 90, sortable: true, sortOrder: sortKey === 'change_1d' ? sortDir : null, render: (v: unknown) => renderChangeCell(v as number | null) },
    { key: 'change_3d', dataIndex: 'change_3d', title: '3日', width: 90, sortable: true, sortOrder: sortKey === 'change_3d' ? sortDir : null, render: (v: unknown) => renderChangeCell(v as number | null) },
    { key: 'change_5d', dataIndex: 'change_5d', title: '5日', width: 90, sortable: true, sortOrder: sortKey === 'change_5d' ? sortDir : null, render: (v: unknown) => renderChangeCell(v as number | null) },
    { key: 'change_10d', dataIndex: 'change_10d', title: '10日', width: 90, sortable: true, sortOrder: sortKey === 'change_10d' ? sortDir : null, render: (v: unknown) => renderChangeCell(v as number | null) },
    { key: 'change_30d', dataIndex: 'change_30d', title: '30日', width: 90, sortable: true, sortOrder: sortKey === 'change_30d' ? sortDir : null, render: (v: unknown) => renderChangeCell(v as number | null) },
    { key: 'total_score', dataIndex: 'total_score', title: '综合评分', width: 100, sortable: true, sortOrder: sortKey === 'total_score' ? sortDir : null, render: (v: unknown) => {
      const s = Math.min(Math.max(v as number, 0), 100)
      return <Progress percent={s} size="small" strokeColor={scoreColor(s)} format={(p) => fmt(p, 1)} />
    }},
    { key: 'stock_score', dataIndex: 'stock_score', title: '正股评分', width: 90, sortable: true, sortOrder: sortKey === 'stock_score' ? sortDir : null, render: (v: unknown) => {
      const s = v as number
      return <span style={{ color: scoreColor(s, 55) }}>{fmt(s, 1)}</span>
    }},
    { key: 'bond_score', dataIndex: 'bond_score', title: '转债评分', width: 90, sortable: true, sortOrder: sortKey === 'bond_score' ? sortDir : null, render: (v: unknown) => {
      const s = v as number
      return <span style={{ color: scoreColor(s, 45) }}>{fmt(s, 1)}</span>
    }},
  ], [handleViewDetail, sortKey, sortDir])

  // 被否决表格列
  const vetoedColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    {
      title: '信用评分',
      dataIndex: 'credit_score',
      key: 'credit_score',
      width: 100,
      render: (v: number) => <Text style={{ color: v < 50 ? '#ff4d4f' : '#faad14' }}>{fmt(v, 1)}</Text>,
    },
    {
      title: '否决原因',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (reasons: string[]) => (
        <Space direction="vertical" size="small">
          {reasons.map((r, i) => (
            <Tag key={i} color="red">{r}</Tag>
          ))}
        </Space>
      ),
    },
  ], [])

  // 缓冲带状态表格列
  const bufferColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 60 },
    {
      title: '评分',
      dataIndex: 'score',
      key: 'score',
      width: 80,
      render: (v: number) => fmt(v, 1),
    },
    {
      title: '缓冲状态',
      dataIndex: 'in_buffer',
      key: 'in_buffer',
      width: 100,
      render: (v: boolean) => v ? <Tag color="orange">缓冲带内</Tag> : <Tag color="blue">白名单内</Tag>,
    },
    {
      title: '连续在60名内',
      dataIndex: 'days_above_60',
      key: 'days_above_60',
      width: 100,
      ellipsis: { showTitle: true },
    },
    {
      title: '连续在60名外',
      dataIndex: 'days_below_60',
      key: 'days_below_60',
      width: 100,
      ellipsis: { showTitle: true },
      render: (v: number) => v > 0 ? <Text type="danger">{v}天</Text> : '-',
    },
  ], [])

  // 回测运行
  const handleRunBacktest = useCallback(async () => {
    // [Fix #6] 日期校验
    if (!backtestDateRange[0] || !backtestDateRange[1]) {
      message.warning('请选择日期范围')
      return
    }
    if (backtestDateRange[0].isAfter(backtestDateRange[1])) {
      message.warning('开始日期不能晚于结束日期')
      return
    }
    if (backtestDateRange[1].isAfter(dayjs())) {
      message.warning('结束日期不能晚于今天')
      return
    }

    setBacktestLoading(true)
    // [Fix #10] 不清空旧结果，避免闪烁
    try {
      const res = await runBacktest({
        strategy: 'songgang_seven',
        params: {
          hold_count: topN,
          buffer_size: 5,
          buffer_days: 3,
          min_credit_score: 60,
          max_premium: 100,
          min_remaining_months: 6,
        },
        start_date: backtestDateRange[0].format('YYYY-MM-DD'),
        end_date: backtestDateRange[1].format('YYYY-MM-DD'),
      })
      // [Fix #8] 安全类型断言：检查 type 字段
      if (res.type === 'backtest' && res.result && 'metrics' in res.result) {
        setBacktestResult(res.result as BacktestResult)
        message.success('回测完成')
      } else {
        message.error('回测返回了非预期的结果类型')
        console.error('[SonggangScore] unexpected backtest response type:', res.type)
      }
    } catch (e) {
      console.error('[SonggangScore] backtest failed:', e)
      message.error(`回测失败: ${getErrorMessage(e)}`)
    } finally {
      setBacktestLoading(false)
    }
  }, [backtestDateRange, topN])

  // 回测指标安全取值
  const m = backtestResult?.metrics

  return (
    <div style={{ padding: 16 }}>
      <Card>
        {errorMsg && (
          <Alert
            type="error"
            message="数据加载失败"
            description={errorMsg}
            closable
            onClose={() => setErrorMsg(null)}
            style={{ marginBottom: 16 }}
            action={
              <Button size="small" onClick={fetchData}>重试</Button>
            }
          />
        )}
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>
            <Title level={4} style={{ margin: 0 }}>
              <StarOutlined style={{ marginRight: 8 }} />
              七维详情分析 V3.0
            </Title>
          </Col>
          <Col>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
                刷新
              </Button>
              <Button icon={<SaveOutlined />} onClick={async () => {
                try {
                  const res = await saveSonggangSnapshot()
                  message.success(`快照已保存，共 ${res.saved} 条`)
                } catch (e) {
                  console.error('[SonggangScore] save snapshot failed:', e)
                  message.error('保存快照失败')
                }
              }}>保存快照</Button>
              <Button icon={<AlertOutlined />} onClick={() => setVetoedVisible(true)}>
                一票否决 ({data?.vetoed_count || 0})
              </Button>
              <Button icon={<InfoCircleOutlined />} onClick={() => setBufferVisible(true)}>
                缓冲带状态
              </Button>
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => {
                setBacktestResult(null)
                setBacktestVisible(true)
              }}>
                回测此策略
              </Button>
            </Space>
          </Col>
        </Row>

        {/* 参数设置 */}
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={24}>
            <Col span={6}>
              <Text>返回前N名</Text>
              <Slider
                min={10}
                max={100}
                value={topN}
                onChange={setTopN}
                marks={{ 10: '10', 60: '60', 100: '100' }}
              />
            </Col>
            <Col span={6}>
              <Text>AUM规模</Text>
              <Select
                style={{ width: '100%' }}
                value={aumLevel}
                onChange={setAumLevel}
                options={[
                  { value: 'small', label: '<1亿' },
                  { value: 'medium', label: '1-5亿' },
                  { value: 'large', label: '5-10亿' },
                ]}
              />
            </Col>
            <Col span={6}>
              <Text>市场环境</Text>
              <Select
                style={{ width: '100%' }}
                value={marketEnv}
                onChange={setMarketEnv}
                options={[
                  { value: 'bull', label: '牛市（动量权重高）' },
                  { value: 'neutral', label: '震荡市（均衡权重）' },
                  { value: 'bear', label: '熊市（防御权重高）' },
                ]}
              />
            </Col>
            <Col span={6}>
              <Space direction="vertical" size="small">
                <Text>实际市场: {getMarketEnvTag(data?.market_env || marketEnv)}
                  {data?.market_env && data.market_env !== marketEnv && (
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>（服务端检测）</Text>
                  )}
                </Text>
                <Text>AUM等级: {getAumLevelTag(data?.aum_level || aumLevel)}</Text>
              </Space>
            </Col>
          </Row>
        </Card>

        {/* 统计信息 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={3}>
            <Statistic title="通过筛选" value={data?.total || 0} suffix="只" />
          </Col>
          <Col span={3}>
            <Statistic title="返回数量" value={data?.returned || 0} suffix="只" />
          </Col>
          <Col span={3}>
            <Statistic title="一票否决" value={data?.vetoed_count || 0} suffix="只" valueStyle={{ color: '#ff4d4f' }} />
          </Col>
          <Col span={3}>
            <Statistic
              title="缓冲带内"
              value={data?.buffer_status?.filter(b => b.in_buffer).length || 0}
              suffix="只"
              valueStyle={{ color: '#faad14' }}
            />
          </Col>
          {(() => {
            const ms = data?.market_stats
            if (!ms) {
              return (
                <Col span={6}>
                  <Card size="small" style={{ background: '#fafafa' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>当日涨跌统计</Text>
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>暂无数据</div>
                  </Card>
                </Col>
              )
            }
            const upColor = '#cf1322'   // A股惯例：红涨
            const downColor = '#389e0d' // 绿跌
            const flatColor = '#8c8c8c'
            return (
              <Col span={6}>
                <Card size="small" style={{ background: '#fafafa' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    当日涨跌 · 共 {ms.total} 只
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
                      均 {ms.avg_change > 0 ? '+' : ''}{(ms.avg_change ?? 0).toFixed(2)}%
                    </Text>
                  </Text>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 4 }}>
                    <Tooltip title="今日上涨可转债数量（涨幅>0）">
                      <span style={{ color: upColor, fontWeight: 600, fontSize: 18 }}>
                        涨 {ms.up}
                      </span>
                    </Tooltip>
                    <Tooltip title="今日下跌可转债数量（跌幅<0）">
                      <span style={{ color: downColor, fontWeight: 600, fontSize: 18 }}>
                        跌 {ms.down}
                      </span>
                    </Tooltip>
                    {ms.flat > 0 && (
                      <Tooltip title="今日价格不变的可转债数量">
                        <span style={{ color: flatColor, fontSize: 14 }}>
                          平 {ms.flat}
                        </span>
                      </Tooltip>
                    )}
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
                      涨跌幅 {(ms.up_ratio ?? 0).toFixed(1)}% / {(ms.down_ratio ?? 0).toFixed(1)}%
                    </Text>
                  </div>
                  {/* 涨/跌比例条 */}
                  <div style={{ display: 'flex', height: 4, borderRadius: 2, overflow: 'hidden', marginTop: 6, background: '#f0f0f0' }}>
                    <div style={{ width: `${ms.up_ratio}%`, background: upColor, transition: 'width 0.3s' }} />
                    <div style={{ width: `${ms.total > 0 ? ms.flat / ms.total * 100 : 0}%`, background: flatColor }} />
                    <div style={{ width: `${ms.down_ratio}%`, background: downColor, transition: 'width 0.3s' }} />
                  </div>
                </Card>
              </Col>
            )
          })()}
          <Col span={6}>
            <Alert
              message="七维评分：正股55分 + 转债45分 = 满分100分"
              description="包含一票否决制、缓冲带机制、动态权重调整"
              type="info"
              showIcon
            />
          </Col>
        </Row>

        {/* 排名表格 - 支持水平滚动查看所有列 */}
        {sortedItems.length ? (
          <div style={{ overflowX: 'auto', overflowY: 'hidden', maxWidth: '100%' }}>
            <div style={{ minWidth: virtualColumns.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 100), 0) }}>
              <VirtualTable
                data={sortedItems}
                columns={virtualColumns}
                loading={loading}
                onRowClick={(record) => handleViewDetail(record.code)}
                onSort={(_key, col) => handleSort(col.dataIndex || col.key)}
              />
            </div>
          </div>
        ) : (
          <Spin spinning={loading}>
            <Empty description="暂无数据" />
          </Spin>
        )}
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title={<span><StarOutlined /> {selectedCode} 七维详细评分</span>}
        open={detailVisible}
        onCancel={() => { setDetailVisible(false); setSelectedDetail(null) }}
        footer={null}
        width={800}
      >
        <Spin spinning={detailLoading}>
          {selectedDetail && (
            <>
              <Alert
                message={selectedDetail.veto_check.passed ? '通过一票否决检查' : '触发一票否决'}
                description={selectedDetail.veto_check.reasons.length > 0 ? selectedDetail.veto_check.reasons.join('；') : '该转债通过所有一票否决检查'}
                type={selectedDetail.veto_check.passed ? 'success' : 'error'}
                showIcon
                style={{ marginBottom: 16 }}
              />

              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Statistic title="综合评分" value={selectedDetail.total_score} suffix="/ 100" />
                </Col>
                <Col span={8}>
                  <Statistic title="正股评分" value={selectedDetail.stock_score} suffix="/ 55" />
                </Col>
                <Col span={8}>
                  <Statistic title="转债评分" value={selectedDetail.bond_score} suffix="/ 45" />
                </Col>
              </Row>

              {/* 七维雷达图 */}
              {(() => {
                const stockKeys = Object.keys(selectedDetail.stock_details)
                const bondKeys = Object.keys(selectedDetail.bond_details)
                const allNames = [...stockKeys.map(k => STOCK_DIMENSION_NAMES[k] || k), ...bondKeys.map(k => BOND_DIMENSION_NAMES[k] || k)]
                const allValues = [...stockKeys.map((k) => {
                  const maxVal = (selectedDetail.weights?.stock_weights?.[k] ?? 0) * 55
                  const val = selectedDetail.stock_details[k] ?? 0
                  return maxVal > 0 ? Math.round((val / maxVal) * 100) : 0
                }), ...bondKeys.map((k) => {
                  const maxVal = (selectedDetail.weights?.bond_weights?.[k] ?? 0) * 45
                  const val = selectedDetail.bond_details[k] ?? 0
                  return maxVal > 0 ? Math.round((val / maxVal) * 100) : 0
                })]
                const items = data?.items || []
                const avgValues = [...stockKeys.map(k => {
                  const maxVal = (selectedDetail.weights?.stock_weights?.[k] ?? 0) * 55
                  if (maxVal <= 0 || items.length === 0) return 0
                  const sum = items.reduce((acc, it) => acc + (it.score_details?.[k] ?? 0), 0)
                  return Math.round((sum / items.length / maxVal) * 100)
                }), ...bondKeys.map(k => {
                  const maxVal = (selectedDetail.weights?.bond_weights?.[k] ?? 0) * 45
                  if (maxVal <= 0 || items.length === 0) return 0
                  const sum = items.reduce((acc, it) => acc + (it.bond_details?.[k] ?? 0), 0)
                  return Math.round((sum / items.length / maxVal) * 100)
                })]
                const radarOption = {
                  tooltip: { trigger: 'item' },
                  legend: { data: [selectedDetail.code, '均值'], bottom: 0, textStyle: { fontSize: 11 } },
                  radar: {
                    indicator: allNames.map(name => ({ name, max: 100 })),
                    shape: 'polygon' as const,
                    radius: '60%',
                    axisName: { color: '#666', fontSize: 11 },
                  },
                  series: [{
                    type: 'radar',
                    data: [
                      {
                        value: allValues,
                        name: selectedDetail.code,
                        areaStyle: { color: 'rgba(22, 119, 255, 0.2)' },
                        lineStyle: { color: '#1677ff', width: 2 },
                        itemStyle: { color: '#1677ff' },
                      },
                      {
                        value: avgValues,
                        name: '均值',
                        areaStyle: { color: 'rgba(250, 173, 20, 0.1)' },
                        lineStyle: { color: '#faad14', width: 1, type: 'dashed' as const },
                        itemStyle: { color: '#faad14' },
                      },
                    ],
                  }],
                }
                return <ReactECharts option={radarOption} style={{ height: 300, marginBottom: 8 }} />
              })()}

              {/* 历史趋势折线图 */}
              {historyData.length > 1 && (
                <>
                  <Divider>评分历史趋势</Divider>
                  {(() => {
                    const sorted = [...historyData].sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
                    const dates = sorted.map(h => h.snapshot_date)
                    const dimFields = [
                      { key: 'total_score', name: '综合', color: '#1677ff' },
                      { key: 'stock_score', name: '正股', color: '#52c41a' },
                      { key: 'bond_score', name: '转债', color: '#faad14' },
                      { key: 'momentum', name: '动量', color: '#722ed1' },
                      { key: 'sector', name: '板块', color: '#eb2f96' },
                      { key: 'technical', name: '技术', color: '#13c2c2' },
                      { key: 'chip', name: '筹码', color: '#fa541c' },
                      { key: 'volatility', name: '波动', color: '#2f54eb' },
                      { key: 'news', name: '消息', color: '#a0d911' },
                      { key: 'fundamental', name: '基本面', color: '#f5222d' },
                      { key: 'valuation', name: '估值', color: '#1890ff' },
                      { key: 'clause', name: '条款', color: '#52c41a' },
                      { key: 'liquidity', name: '流动', color: '#faad14' },
                      { key: 'credit', name: '信用', color: '#ff4d4f' },
                    ]
                    const series = dimFields.map((d, i) => ({
                      name: d.name, type: 'line' as const,
                      data: sorted.map(h => (h as unknown as Record<string, unknown>)[d.key] as number ?? 0),
                      smooth: true, lineStyle: { width: d.key === 'total_score' ? 2.5 : 1.5 },
                      itemStyle: { color: d.color },
                      emphasis: { lineStyle: { width: 3 } },
                      ...(i >= 3 ? { lineStyle: { width: 1.5, opacity: 0.3 }, areaStyle: { opacity: 0 } } : {}),
                    }))
                    const selected: Record<string, boolean> = {}
                    dimFields.forEach((d, i) => { selected[d.name] = i < 3 })
                    const trendOption = {
                      tooltip: { trigger: 'axis' },
                      legend: {
                        data: dimFields.map(d => d.name),
                        bottom: 0, type: 'scroll' as const, textStyle: { fontSize: 10 },
                        selected,
                      },
                      grid: { left: 40, right: 20, top: 20, bottom: 50 },
                      xAxis: { type: 'category' as const, data: dates, axisLabel: { fontSize: 10, rotate: 30 } },
                      yAxis: { type: 'value' as const, name: '评分', min: 0 },
                      series,
                    }
                    return <ReactECharts option={trendOption} style={{ height: 280 }} />
                  })()}
                </>
              )}
              {historyData.length <= 1 && !historyLoading && (
                <div style={{ textAlign: 'center', padding: '8px 0', color: '#999', fontSize: 12 }}>
                  暂无历史评分数据，请先保存快照
                </div>
              )}

              <Divider>正股七维评分（满分55分）</Divider>
              <Row gutter={[16, 16]}>
                {Object.entries(selectedDetail.stock_details).map(([key, value]) => (
                  <Col span={6} key={key}>
                    <Card size="small">
                      <Statistic
                        title={STOCK_DIMENSION_NAMES[key] || key}
                        value={value}
                        suffix={`/ ${fmt((selectedDetail.weights?.stock_weights?.[key] ?? 0) * 55, 1)}`}
                        valueStyle={{ color: scoreColor(value, selectedDetail.weights.stock_weights[key] * 55) }}
                      />
                    </Card>
                  </Col>
                ))}
              </Row>

              <Divider>转债自身评分（满分45分）</Divider>
              <Row gutter={[16, 16]}>
                {Object.entries(selectedDetail.bond_details).map(([key, value]) => (
                  <Col span={6} key={key}>
                    <Card size="small">
                      <Statistic
                        title={BOND_DIMENSION_NAMES[key] || key}
                        value={value}
                        suffix={`/ ${fmt((selectedDetail.weights?.bond_weights?.[key] ?? 0) * 45, 1)}`}
                        valueStyle={{ color: scoreColor(value, selectedDetail.weights.bond_weights[key] * 45) }}
                      />
                    </Card>
                  </Col>
                ))}
              </Row>

              <Divider>基本信息</Divider>
              <Descriptions bordered size="small" column={4}>
                <Descriptions.Item label="价格">{fmt(selectedDetail.price)}</Descriptions.Item>
                <Descriptions.Item label="溢价率">{fmt(selectedDetail.premium_ratio)}%</Descriptions.Item>
                <Descriptions.Item label="双低值">{fmt(selectedDetail.dual_low)}</Descriptions.Item>
                <Descriptions.Item label="剩余年限">{selectedDetail?.remaining_years != null ? selectedDetail.remaining_years.toFixed(2) : '-'}年</Descriptions.Item>
                <Descriptions.Item label="成交额">{fmt(selectedDetail.volume)}亿</Descriptions.Item>
                <Descriptions.Item label="YTM">{selectedDetail?.ytm != null ? selectedDetail.ytm.toFixed(2) : '-'}%</Descriptions.Item>
                <Descriptions.Item label="信用评分">{fmt(selectedDetail.veto_check?.credit_score, 1)}</Descriptions.Item>
              </Descriptions>
            </>
          )}
        </Spin>
      </Modal>

      {/* 一票否决弹窗 */}
      <Modal
        title={<span><CloseCircleOutlined /> 一票否决列表</span>}
        open={vetoedVisible}
        onCancel={() => setVetoedVisible(false)}
        footer={null}
        width={900}
      >
        <Alert
          message="一票否决制"
          description="满足任意一条直接排除：信用评分<60、溢价率>100%、剩余期限<6个月、强赎公告、流动性不足"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Table
          dataSource={data?.vetoed || []}
          columns={vetoedColumns}
          rowKey="code"
          size="small"
          pagination={{ current: vetoedPage, pageSize: vetoedPageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setVetoedPage(p); setVetoedPageSize(ps) } }}
        />
      </Modal>

      {/* 缓冲带状态弹窗 */}
      <Modal
        title={<span><InfoCircleOutlined /> 缓冲带状态</span>}
        open={bufferVisible}
        onCancel={() => setBufferVisible(false)}
        footer={null}
        width={900}
      >
        <Alert
          message="缓冲带机制"
          description="排名55-65名享有3日观察期。连续3日在60名外必须卖出，减少约40%的边缘换手。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Table
          dataSource={data?.buffer_status || []}
          columns={bufferColumns}
          rowKey="code"
          size="small"
          pagination={{ current: bufferPage, pageSize: bufferPageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setBufferPage(p); setBufferPageSize(ps) } }}
        />
      </Modal>

      {/* 回测弹窗 */}
      <Modal
        title={<span><ThunderboltOutlined /> 回测「前{topN}名轮换」策略</span>}
        open={backtestVisible}
        onCancel={() => setBacktestVisible(false)}
        footer={null}
        width={1000}
      >
        <Alert
          message="回测说明"
          description={`将使用松岗七维打分策略，持有前${topN}名标的进行轮换回测。当前AUM等级: ${aumLevel}，市场环境: ${marketEnv}。`}
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={16} align="middle">
            <Col span={5}>
              <Text>开始日期</Text>
              <DatePicker
                value={backtestDateRange[0]}
                onChange={d => d && setBacktestDateRange([d, backtestDateRange[1]])}
                disabledDate={d => d.isAfter(dayjs())}
                style={{ width: '100%' }}
              />
            </Col>
            <Col span={5}>
              <Text>结束日期</Text>
              <DatePicker
                value={backtestDateRange[1]}
                onChange={d => d && setBacktestDateRange([backtestDateRange[0], d])}
                disabledDate={d => d.isAfter(dayjs())}
                style={{ width: '100%' }}
              />
            </Col>
            <Col span={4}>
              <Text>持有数量</Text>
              <InputNumber
                min={10} max={100} value={topN}
                style={{ width: '100%' }}
                disabled
              />
            </Col>
            <Col span={4}>
              <Text>AUM等级</Text>
              <Select style={{ width: '100%' }} value={aumLevel} disabled options={[
                { value: 'small', label: '<1亿' },
                { value: 'medium', label: '1-5亿' },
                { value: 'large', label: '5-10亿' },
              ]} />
            </Col>
            <Col span={6} style={{ textAlign: 'right' }}>
              <Button
                type="primary"
                icon={<LineChartOutlined />}
                loading={backtestLoading}
                onClick={handleRunBacktest}
              >
                运行回测
              </Button>
            </Col>
          </Row>
        </Card>

        {backtestLoading && !backtestResult && (
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" tip="正在运行回测..." />
          </div>
        )}

        {backtestResult && (
          <div style={{ opacity: backtestLoading ? 0.5 : 1, pointerEvents: backtestLoading ? 'none' : 'auto' }}>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}><Card size="small"><Statistic title="总收益率" value={m?.total_return_pct?.toFixed(2) ?? '-'} suffix="%" valueStyle={{ color: (m?.total_return_pct ?? 0) >= 0 ? '#cf1322' : '#3f8600' }} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="年化收益" value={m?.annual_return_pct?.toFixed(2) ?? '-'} suffix="%" valueStyle={{ color: (m?.annual_return_pct ?? 0) >= 0 ? '#cf1322' : '#3f8600' }} /></Card></Col>
              <Col span={4}><Card size="small"><Statistic title="最大回撤" value={m?.max_drawdown_pct?.toFixed(2) ?? '-'} suffix="%" valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
              <Col span={3}><Card size="small"><Statistic title="夏普比率" value={m?.sharpe_ratio?.toFixed(3) ?? '-'} /></Card></Col>
              <Col span={3}><Card size="small"><Statistic title="胜率" value={m?.win_rate?.toFixed(1) ?? '-'} suffix="%" /></Card></Col>
              <Col span={3}><Card size="small"><Statistic title="总交易" value={m?.total_trades ?? 0} suffix="笔" /></Card></Col>
              <Col span={3}><Card size="small"><Statistic title="均持天数" value={m?.avg_hold_days?.toFixed(1) ?? '-'} suffix="天" /></Card></Col>
            </Row>

            {backtestResult.equity_curve?.length > 1 && (
              <Card size="small" title="净值曲线" style={{ marginBottom: 16 }}>
                <ReactECharts option={{
                  tooltip: { trigger: 'axis' },
                  grid: { left: 50, right: 20, top: 20, bottom: 30 },
                  xAxis: { type: 'category', data: backtestResult.equity_curve.map(p => p.date), axisLabel: { fontSize: 10, rotate: 30 } },
                  yAxis: { type: 'value', name: '净值' },
                  series: [{
                    type: 'line', data: backtestResult.equity_curve.map(p => p.value),
                    smooth: true, lineStyle: { width: 2, color: '#1677ff' },
                    areaStyle: { color: 'rgba(22, 119, 255, 0.1)' },
                  }],
                }} style={{ height: 250 }} />
              </Card>
            )}

            {backtestResult.trades?.length > 0 && (
              <Card size="small" title={`交易记录（共${backtestResult.trades.length}笔）`}>
                <Table
                  dataSource={backtestResult.trades.slice(0, 50)}
                  rowKey={(r, i) => `${r.code}-${r.buy_date}-${i}`}
                  size="small"
                  pagination={{ current: tradesPage, pageSize: tradesPageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setTradesPage(p); setTradesPageSize(ps) } }}
                  scroll={{ x: 700 }}
                  columns={[
                    { title: '代码', dataIndex: 'code', width: 80 },
                    { title: '名称', dataIndex: 'name', width: 80 },
                    { title: '买入日', dataIndex: 'buy_date', width: 100 },
                    { title: '卖出日', dataIndex: 'sell_date', width: 100 },
                    { title: '买价', dataIndex: 'buy_price', width: 70, render: (v: number) => v?.toFixed(3) },
                    { title: '卖价', dataIndex: 'sell_price', width: 70, render: (v: number) => v?.toFixed(3) },
                    { title: '收益%', dataIndex: 'profit_pct', width: 80, render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v?.toFixed(2)}%</span> },
                    { title: '持天数', dataIndex: 'hold_days', width: 60 },
                    { title: '原因', dataIndex: 'reason', width: 120, ellipsis: true },
                  ]}
                />
              </Card>
            )}
          </div>
        )}

        {!backtestResult && !backtestLoading && (
          <Empty description="设置日期范围后点击「运行回测」" style={{ padding: 40 }} />
        )}
      </Modal>
    </div>
  )
}
