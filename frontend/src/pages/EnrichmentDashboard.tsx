import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Row, Col, Table, Tag, Progress, Spin, Typography, Space, Button, Tooltip, Statistic, Collapse, Descriptions } from 'antd'
import { ReloadOutlined, CheckCircleOutlined, WarningOutlined, CloseCircleOutlined, SyncOutlined, DatabaseOutlined, BarChartOutlined, ApiOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

const { Title, Text } = Typography

// ── API helpers ──

const UNINITIALIZED = Symbol('uninitialized')
let _baseCache: string | typeof UNINITIALIZED = UNINITIALIZED
const getBase = (): string => {
  if (_baseCache !== UNINITIALIZED) return _baseCache as string
  if (typeof window !== 'undefined') {
    _baseCache = (window as any).__API_BASE__ || '/api/v1'
  } else {
    _baseCache = '/api/v1'
  }
  return _baseCache as string
}

async function fetchJSON<T>(url: string): Promise<T> {
  const token = localStorage.getItem('auth_token') || ''
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── Types ──

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

interface SelfCheckData {
  coverage: Record<string, number>
  bond_count: number
  caches: Record<string, { status: string; memory_entries: number }>
}

// ── Helpers ──

const CACHE_LABELS: Record<string, string> = {
  north: '北向资金',
  margin: '融资融券',
  lhb: '龙虎榜',
  block_trade: '大宗交易',
  holder_num: '股东人数',
  earnings_forecast: '业绩预告',
  earnings_express: '业绩快报',
  restricted_release: '限售解禁',
  fin: '财务数据(ROE/GPM)',
  spot: '现货行情(PE/PB)',
}

const CACHE_ICONS: Record<string, React.ReactNode> = {
  fresh: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  stale: <WarningOutlined style={{ color: '#faad14' }} />,
  missing: <CloseCircleOutlined style={{ color: '#ff4d4f' }} />,
  unknown: <SyncOutlined style={{ color: '#1890ff' }} />,
}

const CACHE_STATUS_LABEL: Record<string, string> = {
  fresh: '正常',
  stale: '过期',
  missing: '缺失',
  unknown: '未知',
}

const FIELD_LABELS: Record<string, string> = {
  north_net: '北向资金',
  margin_balance: '融资余额',
  lhb_count: '龙虎榜',
  block_trade_amount: '大宗交易',
  restricted_release_amount: '限售解禁',
  holder_num_change: '股东变化',
  bond_value: '纯债价值',
  call_status: '强赎状态',
  pledge_ratio: '质押比例',
  concepts: '概念板块',
  ytm: '到期收益率',
  remaining_years: '剩余年限',
  industry: '行业',
  pe: '市盈率',
  pb: '市净率',
  roe: '净资产收益率',
  gpm: '毛利率',
  dual_low: '双低值',
  premium_ratio: '转股溢价率',
  conversion_value: '转股价值',
  turnover_rate: '换手率',
  eps_forecast: '一致预期EPS',
  mgmt_buy_price: '管理层增持',
  buyback_amount: '回购金额',
  iv: '隐含波动率',
  net_capital_flow: '主力资金',
  momentum_5d: '5日动量',
  momentum_10d: '10日动量',
  momentum_20d: '20日动量',
  momentum_60d: '60日动量',
  event_score: '事件评分',
  debt_ratio: '资产负债率',
  current_ratio: '流动比率',
  stock_name: '正股名称',
}

const NAME_MAP: Record<string, string> = {
  _build_industry_cache: '行业分类',
  _refresh_spot_cache: '现货行情(PE/PB)',
  _refresh_fund_flow_cache: '资金流向',
  _refresh_fin_cache: '财务数据',
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
  _refresh_north_cache: '北向资金',
  _refresh_margin_cache: '融资融券',
  _refresh_lhb_cache: '龙虎榜',
  _refresh_block_trade_cache: '大宗交易',
  _refresh_holder_num_cache: '股东人数',
  _refresh_earnings_forecast_cache: '业绩预告',
  _refresh_restricted_release_cache: '限售解禁',
}

function formatName(n: string): string {
  return NAME_MAP[n] || n.replace(/^_refresh_|^_build_/, '').replace(/_/g, ' ')
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

// ── Component ──

export default function EnrichmentDashboard() {
  const [metricsData, setMetricsData] = useState<any>(null)
  const [selfCheckData, setSelfCheckData] = useState<SelfCheckData | null>(null)
  const [loading, setLoading] = useState(false)
  const [errMsg, setErrMsg] = useState<string | null>(null)
  const [retryIn, setRetryIn] = useState<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const mountedRef = useRef(true)
  const abortRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setErrMsg(null)
    try {
      const [metrics, selfCheck] = await Promise.all([
        fetchJSON<any>(`${getBase()}/data-enrich/metrics`),
        fetchJSON<SelfCheckData>(`${getBase()}/data-enrich/self-check`),
      ])
      if (mountedRef.current) {
        setMetricsData(metrics)
        setSelfCheckData(selfCheck)
      }
    } catch (e: any) {
      if (ctrl.signal.aborted || e?.name === 'AbortError') return
      if (mountedRef.current) {
        setErrMsg(e.message || '加载失败')
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    load()
    const interval = setInterval(load, 60000)
    return () => {
      mountedRef.current = false
      clearInterval(interval)
      if (timerRef.current) clearTimeout(timerRef.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [load])

  // ── Data source rows ──
  const metricRows: (MetricEntry & { key: string })[] = metricsData
    ? Object.entries(metricsData.metrics).map(([key, m]: any) => ({ ...m, key }))
    : []

  const okCount = metricRows.filter(r => r.status === 'ok' && !r.stale).length
  const pendingCount = metricRows.filter(r => r.status === 'pending').length
  const emptyCount = metricRows.filter(r => r.status === 'empty').length
  const errorCount = metricRows.filter(r => r.status === 'error').length

  // ── Coverage rows ──
  const coverageRows = selfCheckData
    ? Object.entries(selfCheckData.coverage).map(([field, pct], i) => ({
        key: i.toString(),
        field,
        label: FIELD_LABELS[field] || field,
        pct,
      }))
    : []

  // ── Cache rows ──
  const cacheRows = selfCheckData
    ? Object.entries(selfCheckData.caches).map(([name, info], i) => ({
        key: i.toString(),
        name,
        label: CACHE_LABELS[name] || name,
        status: info.status,
        memory_entries: info.memory_entries,
      }))
    : []

  const metricColumns: ColumnsType<MetricEntry & { key: string }> = [
    { title: '数据源', dataIndex: 'name', key: 'name', render: (n: string) => <Text strong>{formatName(n)}</Text>, sorter: (a, b) => a.name.localeCompare(b.name) },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (status: string, row) => {
        const Icon = status === 'ok' ? CheckCircleOutlined : status === 'pending' ? SyncOutlined : status === 'error' ? CloseCircleOutlined : WarningOutlined
        const color = status === 'ok' ? '#52c41a' : status === 'pending' ? '#1890ff' : status === 'error' ? '#ff4d4f' : '#faad14'
        return (
          <Tooltip title={row.error || undefined}>
            <Tag color={row.stale ? 'default' : color} icon={<Icon spin={status === 'pending'} />}>
              {row.stale ? '过期' : status === 'ok' ? '正常' : status === 'pending' ? '等待中' : status === 'error' ? '异常' : '空数据'}
            </Tag>
          </Tooltip>
        )
      },
      filters: [
        { text: '正常', value: 'ok' },
        { text: '空数据', value: 'empty' },
        { text: '异常', value: 'error' },
      ],
      onFilter: (value: any, record: any) => record.status === value,
    },
    { title: '数据条数', dataIndex: 'count', key: 'count', width: 90, render: (v: number) => v?.toLocaleString() ?? '-', sorter: (a, b) => (a.count ?? 0) - (b.count ?? 0) },
    { title: 'Bond覆盖率', key: 'bond_coverage', width: 180,
      render: (_: any, row) => {
        if (!row.bond_total) return <Text type="secondary">N/A</Text>
        const pct = Math.round(((row.bond_count ?? 0) / row.bond_total) * 100)
        return (
          <Progress percent={pct} size="small" status={pct >= 95 ? 'success' : pct >= 70 ? 'normal' : 'exception'} format={() => `${row.bond_count ?? 0}/${row.bond_total}`} />
        )
      },
    },
    { title: '耗时', dataIndex: 'elapsed_s', key: 'elapsed_s', width: 90, render: (v: number) => formatElapsed(v), sorter: (a, b) => a.elapsed_s - b.elapsed_s },
    { title: '上次刷新', dataIndex: 'ts', key: 'ts', width: 120, render: (ts: string) => ts ? timeAgo(ts) : '-', sorter: (a, b) => (a.ts || '').localeCompare(b.ts || '') },
  ]

  const coverageColumns: ColumnsType<any> = [
    { title: '字段', dataIndex: 'label', key: 'label', render: (l: string, row: any) => <Text strong>{l}</Text> },
    { title: '字段名', dataIndex: 'field', key: 'field', render: (f: string) => <Text code style={{ fontSize: 11 }}>{f}</Text> },
    { title: '覆盖率', dataIndex: 'pct', key: 'pct', width: 280,
      render: (pct: number) => (
        <Progress
          percent={Math.round(pct)}
          size="small"
          status={pct >= 95 ? 'success' : pct >= 80 ? 'normal' : 'exception'}
          format={() => `${pct.toFixed(1)}%`}
        />
      ),
      sorter: (a: any, b: any) => a.pct - b.pct,
    },
    { title: '状态', key: 'status', width: 80,
      render: (_: any, row: any) => {
        if (row.pct >= 95) return <Tag color="green">良好</Tag>
        if (row.pct >= 80) return <Tag color="orange">警告</Tag>
        if (row.pct > 0) return <Tag color="red">危险</Tag>
        return <Tag color="default">暂无</Tag>
      },
    },
  ]

  const cacheColumns: ColumnsType<any> = [
    { title: '缓存', dataIndex: 'label', key: 'label', render: (l: string) => <Text strong>{l}</Text> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (status: string) => (
        <Tag icon={CACHE_ICONS[status] || null} color={status === 'fresh' ? 'green' : status === 'stale' ? 'orange' : status === 'missing' ? 'red' : 'default'}>
          {CACHE_STATUS_LABEL[status] || status}
        </Tag>
      ),
    },
    { title: '内存条数', dataIndex: 'memory_entries', key: 'memory_entries', width: 100, render: (v: number) => v.toLocaleString() },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* ── Header ── */}
        <Row justify="space-between" align="middle">
          <Col>
            <Title level={4} style={{ margin: 0 }}>数据富化看板</Title>
            <Text type="secondary">缓存状态 · 字段覆盖率 · 数据源健康</Text>
          </Col>
          <Col>
            <Space>
              <Text type="secondary">{selfCheckData?.bond_count ?? '-'} 只债券</Text>
              <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
            </Space>
          </Col>
        </Row>

        {/* ── 错误提示 ── */}
        {errMsg && <Text type="danger">加载失败: {errMsg}</Text>}

        {/* ── 1. 缓存状态 ── */}
        <Card title={<Space><DatabaseOutlined /> 缓存健康度</Space>} size="small">
          <Spin spinning={loading}>
            {cacheRows.length > 0 ? (
              <Table dataSource={cacheRows} columns={cacheColumns} rowKey="key" size="small" pagination={false} />
            ) : !loading ? (
              <Text type="secondary">暂无数据</Text>
            ) : null}
          </Spin>
        </Card>

        {/* ── 2. 数据源指标 ── */}
        <Card title={<Space><ApiOutlined /> 数据源刷新指标</Space>} size="small"
          extra={
            <Space size="middle">
              <Tag color="green">{okCount} 正常</Tag>
              {pendingCount > 0 && <Tag color="blue">{pendingCount} 等待中</Tag>}
              {emptyCount > 0 && <Tag color="orange">{emptyCount} 空</Tag>}
              {errorCount > 0 && <Tag color="red">{errorCount} 异常</Tag>}
            </Space>
          }
        >
          <Spin spinning={loading}>
            {metricRows.length > 0 ? (
              <Table dataSource={metricRows} columns={metricColumns} rowKey="key" size="small" pagination={false} scroll={{ y: 400 }} />
            ) : !loading ? (
              <Text type="secondary">暂无数据源指标</Text>
            ) : null}
          </Spin>
        </Card>

        {/* ── 3. 字段覆盖率 ── */}
        <Card title={<Space><BarChartOutlined /> 字段覆盖率自检</Space>} size="small"
          extra={
            <Space>
              <Tag color="green">{coverageRows.filter(r => r.pct >= 95).length} 良好</Tag>
              <Tag color="orange">{coverageRows.filter(r => r.pct >= 80 && r.pct < 95).length} 警告</Tag>
              <Tag color="red">{coverageRows.filter(r => r.pct > 0 && r.pct < 80).length} 危险</Tag>
              <Tag color="default">{coverageRows.filter(r => r.pct === 0).length} 缺失</Tag>
            </Space>
          }
        >
          <Spin spinning={loading}>
            {coverageRows.length > 0 ? (
              <Table dataSource={coverageRows} columns={coverageColumns} rowKey="key" size="small" pagination={false} scroll={{ y: 500 }} />
            ) : !loading ? (
              <Text type="secondary">暂无覆盖率数据（自检需要至少 5 分钟）</Text>
            ) : null}
          </Spin>
        </Card>
      </Space>
    </div>
  )
}
