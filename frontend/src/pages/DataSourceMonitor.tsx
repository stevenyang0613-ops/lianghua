import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { Card, Table, Tag, Progress, Spin, Typography, Space, Button, Tooltip, Empty } from 'antd'
import { ReloadOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, SyncOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

const { Title, Text } = Typography

// 监听 prefers-reduced-motion 偏好变化（不只在模块加载时检查）
// 用户运行时切换系统设置也能响应
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  })
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])
  return reduced
}

interface MetricEntry {
  name: string
  elapsed_s: number
  count: number
  status: 'ok' | 'pending' | 'empty' | 'error'
  error?: string
  ts: string
  bond_count?: number
  bond_total?: number
  stale?: boolean
}

interface MetricsResponse {
  metrics: Record<string, MetricEntry>
  refresh_ts: Record<string, number>
}

// SSR-safe: 改为 lazy getter，避免模块加载时立即访问 window.__API_BASE__。
// 这样在 Node 端预渲染或测试时，window 访问被推迟到实际 fetch 调用时刻。
// 同时模块级缓存避免每次 fetch 都重复 typeof 检查（~1ns × N 次）。
const UNINITIALIZED = Symbol('uninitialized')
let _baseCache: string | typeof UNINITIALIZED = UNINITIALIZED
const getBase = (): string => {
  if (_baseCache !== UNINITIALIZED) return _baseCache as string
  if (typeof window !== 'undefined') {
    _baseCache = window.__API_BASE__ || '/api/v1'
  } else {
    _baseCache = '/api/v1'
  }
  return _baseCache as string
}

// 指数退避：成功重置为该值，失败翻倍至上限
const INITIAL_RETRY_INTERVAL_MS = 30000
const MAX_RETRY_INTERVAL_MS = 120000

async function fetchMetrics(signal?: AbortSignal): Promise<MetricsResponse> {
  const token = localStorage.getItem('auth_token') || ''
  const res = await fetch(`${getBase()}/data-enrich/metrics`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

const NAME_MAP: Record<string, string> = {
  _build_industry_cache: '行业分类',
  _refresh_spot_cache: '现货行情(PE/PB)',
  _refresh_fund_flow_cache: '资金流向',
  _refresh_fin_cache: '财务数据(ROE/GPM)',
  _refresh_debt_cache: '负债率/流动比率',
  _refresh_volatility_cache: '波动率',
  _refresh_buyback_cache: '回购数据',
  _refresh_mgmt_cache: '管理层增持',
  _refresh_bond_price_cache: '债券价格',
  _build_concept_cache: '概念板块',
  _refresh_momentum_cache: '动量因子',
  _refresh_event_cache: '事件因子',
  _refresh_pledge_cache: '质押比例',
  _refresh_bond_outstanding_cache: '剩余规模',
  _refresh_call_status_cache: '强赎状态',
  _refresh_stock_name_cache: '正股名称',
  _refresh_coupon_rate_cache: '票面利率',
  // 扩展数据源
  _refresh_earnings_express_cache: '业绩快报',
  _refresh_north_cache: '北向资金',
  _refresh_margin_cache: '融资融券',
  _refresh_lhb_cache: '龙虎榜',
  _refresh_block_trade_cache: '大宗交易',
  _refresh_holder_num_cache: '股东人数',
  _refresh_earnings_forecast_cache: '业绩预告',
  _refresh_restricted_release_cache: '限售解禁',
  // 补充数据源 (6 个新增)
  _refresh_main_biz_cache: '主营业务',
  _refresh_analyst_rank_cache: '分析师排名',
  _refresh_macro_cpi_cache: '宏观 CPI',
  _refresh_macro_lpr_cache: '宏观 LPR',
  _refresh_macro_m2_cache: '宏观 M2',
  _refresh_macro_ppi_cache: '宏观 PPI',
}

function formatName(n: string): string {
  if (NAME_MAP[n]) return NAME_MAP[n]
  // 自动生成可读名：去掉前缀，转换为 Title Case
  // 例: _refresh_macro_cpi_cache → "Macro Cpi Cache"
  const stripped = n.replace(/^_refresh_|^_build_/, '').replace(/_cache$/, '')
  return stripped
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

function formatElapsed(s: number): string {
  if (s < 1) return `${(s * 1000).toFixed(0)}ms`
  if (s < 60) return `${s.toFixed(1)}s`
  return `${Math.floor(s / 60)}m${(s % 60).toFixed(0)}s`
}

function timeAgo(isoTs: string): string {
  try {
    const diff = (Date.now() - new Date(isoTs).getTime()) / 1000
    if (diff < 60) return `${diff.toFixed(0)}秒前`
    if (diff < 3600) return `${(diff / 60).toFixed(0)}分钟前`
    if (diff < 86400) return `${(diff / 3600).toFixed(1)}小时前`
    return `${(diff / 86400).toFixed(1)}天前`
  } catch { return '-' }
}

// 检测用户系统是否启用"减少动画"偏好（无障碍设置）
const STATUS_CFG_BASE = {
  ok: { color: 'green', text: '正常', Icon: CheckCircleOutlined },
  empty: { color: 'orange', text: '空数据', Icon: WarningOutlined },
  error: { color: 'red', text: '异常', Icon: CloseCircleOutlined },
  pending: { color: 'blue', text: '等待中', Icon: SyncOutlined },
} as const

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 24, fontWeight: 600, color }}>{value}</div>
      <div style={{ fontSize: 12, color: '#888' }}>{label}</div>
    </div>
  )
}

export default function DataSourceMonitor() {
  const prefersReducedMotion = usePrefersReducedMotion()
  // 动态构建 STATUS_CFG：根据 reduced-motion 偏好决定 pending 图标是否旋转
  // useMemo 避免每次 render 重新创建对象，降低 reconciliation 开销
  const STATUS_CFG = useMemo((): Record<string, { color: string; icon: React.ReactNode; text: string }> => ({
    ok: { color: STATUS_CFG_BASE.ok.color, icon: <STATUS_CFG_BASE.ok.Icon />, text: STATUS_CFG_BASE.ok.text },
    pending: {
      color: STATUS_CFG_BASE.pending.color,
      icon: <STATUS_CFG_BASE.pending.Icon spin={!prefersReducedMotion} />,
      text: STATUS_CFG_BASE.pending.text,
    },
    empty: { color: STATUS_CFG_BASE.empty.color, icon: <STATUS_CFG_BASE.empty.Icon />, text: STATUS_CFG_BASE.empty.text },
    error: { color: STATUS_CFG_BASE.error.color, icon: <STATUS_CFG_BASE.error.Icon />, text: STATUS_CFG_BASE.error.text },
  }), [prefersReducedMotion])
  const [data, setData] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [errMsg, setErrMsg] = useState<string | null>(null)
  const [retryIn, setRetryIn] = useState<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const mountedRef = useRef(true)
  // AbortController 用于在 unmount 或新一轮请求时取消挂起的 fetch，
  // 避免组件已卸载但网络往返仍发生，或并发请求竞态。
  const abortRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    // 取消上一轮挂起的请求
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setErrMsg(null)
    try {
      const res = await fetchMetrics(ctrl.signal)
      if (mountedRef.current) {
        setData(res)
        // 成功后标记成功状态，重置轮询间隔为初始值
        isSuccessRef.current = true
        scheduleNext(INITIAL_RETRY_INTERVAL_MS)
      }
    } catch (e: any) {
      // 主动取消的请求不视为错误（兼容 DOMException/AbortError 类）
      if (ctrl.signal.aborted || e?.name === 'AbortError') return
      if (mountedRef.current) {
        // 先同步设置 ref，再异步 setState，确保倒计时 effect 触发时已是最新的失败状态
        isSuccessRef.current = false
        setErrMsg(e.message || '加载失败')
        // 失败后指数退避：30s → 60s → 120s（上限）
        scheduleNext(Math.min((lastInterval.current || INITIAL_RETRY_INTERVAL_MS) * 2, MAX_RETRY_INTERVAL_MS))
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  const lastInterval = useRef(INITIAL_RETRY_INTERVAL_MS)
  // 显式标志替代 lastInterval === INITIAL 的隐式比较，避免未来初始值变化引入 bug
  const isSuccessRef = useRef(true)
  const scheduleNext = useCallback((interval: number) => {
    lastInterval.current = interval
    if (timerRef.current) clearTimeout(timerRef.current)
    // unmount 后不再调度下一次，避免组件已卸载但仍触发网络请求
    if (!mountedRef.current) return
    timerRef.current = setTimeout(load, interval)
  }, [load])

  // 错误状态下显示自动重试倒计时（直接读 lastInterval.current，单一真相）
  // 注意：lastInterval 本身由 scheduleNext 的 setTimeout 计时，此处仅做展示
  useEffect(() => {
    if (!errMsg || isSuccessRef.current) {
      setRetryIn(null)
      return
    }
    setRetryIn(Math.ceil(lastInterval.current / 1000))
    const tick = setInterval(() => {
      if (!mountedRef.current) return
      setRetryIn(prev => (prev && prev > 1 ? prev - 1 : null))
    }, 1000)
    return () => clearInterval(tick)
  }, [errMsg])

  useEffect(() => {
    mountedRef.current = true
    // 注意：isSuccessRef 不需要重置。useRef 在 mount 时创建新实例，
    // 重新 mount 时会得到全新 ref，旧值不可访问。cleanup 中只需清理 timer/fetch。
    load()
    return () => {
      mountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
      // 取消挂起的 fetch 请求
      if (abortRef.current) abortRef.current.abort()
    }
  }, [load])

  const rows: (MetricEntry & { key: string })[] = data
    ? Object.entries(data.metrics).map(([key, m]) => ({ ...m, key }))
    : []

  const columns: ColumnsType<MetricEntry & { key: string }> = [
    {
      title: '数据源',
      dataIndex: 'name',
      key: 'name',
      render: (n: string) => <Text strong>{formatName(n)}</Text>,
      sorter: (a, b) => a.name.localeCompare(b.name),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: MetricEntry['status'], row) => {
        const cfg = STATUS_CFG_BASE[status] || STATUS_CFG_BASE.empty
        return (
          <Tooltip title={row.error || undefined}>
            <Tag color={row.stale ? 'default' : cfg.color} icon={<cfg.Icon />}>
              {row.stale ? '过期' : cfg.text}
            </Tag>
          </Tooltip>
        )
      },
      filters: [
        { text: '正常', value: 'ok' },
        { text: '空数据', value: 'empty' },
        { text: '异常', value: 'error' },
      ],
      onFilter: (value: React.Key | boolean, record: MetricEntry & { key: string }) => record.status === value,
    },
    {
      title: '总条数',
      dataIndex: 'count',
      key: 'count',
      width: 90,
      render: (v: number) => v?.toLocaleString() ?? '-',
      sorter: (a, b) => (a.count ?? 0) - (b.count ?? 0),
    },
    {
      title: 'Bond 覆盖率',
      key: 'bond_coverage',
      width: 180,
      render: (_: any, row) => {
        if (!row.bond_total) return <Text type="secondary">N/A</Text>
        const pct = Math.round(((row.bond_count ?? 0) / row.bond_total) * 100)
        return (
          <Progress
            percent={pct}
            size="small"
            status={pct >= 95 ? 'success' : pct >= 70 ? 'normal' : 'exception'}
            format={() => `${row.bond_count ?? 0}/${row.bond_total}`}
          />
        )
      },
      sorter: (a, b) => {
        const pa = a.bond_total ? (a.bond_count ?? 0) / a.bond_total : 0
        const pb = b.bond_total ? (b.bond_count ?? 0) / b.bond_total : 0
        return pa - pb
      },
    },
    {
      title: '耗时',
      dataIndex: 'elapsed_s',
      key: 'elapsed_s',
      width: 90,
      render: (v: number) => formatElapsed(v),
      sorter: (a, b) => a.elapsed_s - b.elapsed_s,
    },
    {
      title: '上次刷新',
      dataIndex: 'ts',
      key: 'ts',
      width: 120,
      render: (ts: string) => ts ? timeAgo(ts) : '-',
      sorter: (a, b) => (a.ts || '').localeCompare(b.ts || ''),
    },
  ]

  const totalSources = rows.length
  const okCount = rows.filter(r => r.status === 'ok' && !r.stale).length
  const pendingCount = rows.filter((r: any) => r.status === 'pending').length
  const emptyCount = rows.filter(r => r.status === 'empty').length
  const errorCount = rows.filter(r => r.status === 'error').length
  const staleCount = rows.filter(r => r.stale).length

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>数据源监控</Title>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        </Space>
        <Space size="middle">
          <Card size="small"><Stat label="数据源" value={totalSources} /></Card>
          <Card size="small"><Stat label="正常" value={okCount} color="#52c41a" /></Card>
          {pendingCount > 0 && (
            <Card size="small"><Stat label="等待中" value={pendingCount} color="#1890ff" /></Card>
          )}
          <Card size="small"><Stat label="空数据" value={emptyCount} color="#fa8c16" /></Card>
          <Card size="small"><Stat label="异常" value={errorCount} color="#ff4d4f" /></Card>
          {staleCount > 0 && (
            <Card size="small"><Stat label="过期" value={staleCount} color="#999" /></Card>
          )}
        </Space>
        {errMsg && (
          <Text type="danger">
            加载失败: {errMsg}
            {retryIn !== null && `（${retryIn}秒后自动重试）`}
          </Text>
        )}
        <Card>
          <Spin spinning={loading}>
            {rows.length === 0 && !loading && !errMsg ? (
<div
                className="data-source-monitor-empty"
                style={{
                  // fallback 给不支持 max/min/calc 的旧浏览器。
                  // 旧浏览器还会被 global.css 的 @supports not 规则覆盖回 300px，
                  // 此 inline 仅作为防御性最小值，避免被全局规则意外覆盖。
                  minHeight: 200,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                <Empty description="暂无数据源监控数据" />
              </div>
            ) : (
            <Table
              dataSource={rows}
              columns={columns}
              rowKey="key"
              size="small"
              pagination={false}
              scroll={{ y: 600 }}
            />
            )}
          </Spin>
        </Card>
      </Space>
    </div>
  )
}
