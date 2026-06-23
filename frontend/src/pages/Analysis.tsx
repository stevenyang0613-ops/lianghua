import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Card, Table, Tabs, Tag, Row, Col, Statistic, Typography, Empty, message, Space, Progress, Button, InputNumber, DatePicker, Select, notification, Skeleton } from 'antd'
import { FundProjectionScreenOutlined, AlertOutlined, RiseOutlined, FallOutlined, LinkOutlined, OrderedListOutlined, DownloadOutlined, FilterOutlined, ReloadOutlined } from '@ant-design/icons'
import { fetchForcedRedemption, fetchDualLowRanking, fetchPulseScan, fetchRevisionProbability, fetchStockCorrelation, fetchCacheStats, clearCache, getAnalysisExportUrl } from '../services/api'
import type { ForcedRedemptionItem, DualLowItem, PulseItem, RevisionItem, StockCorrelationItem } from '../services/api'
import type { Dayjs } from 'dayjs'
import { marketWs } from '../utils/wsInstances'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

const riskColor: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue', watch: 'default', none: 'default' }
const riskLabel: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', watch: '关注', none: '安全' }
const severityColor: Record<string, string> = { high: 'red', medium: 'orange' }
const severityLabel: Record<string, string> = { high: '严重', medium: '一般' }

function useAutoRefresh(callback: () => void, ms: number = 30000) {
  const savedCb = useRef(callback)
  savedCb.current = callback
  useEffect(() => {
    const id = setInterval(() => savedCb.current(), ms)
    return () => clearInterval(id)
  }, [ms])
}

function MinVolumeFilter({ value, onChange }: { value: number | null, onChange: (v: number | null) => void }) {
  return (
    <Space size={4}>
      <FilterOutlined />
      <span style={{ fontSize: 12, color: '#888' }}>最低成交额(亿)</span>
      <InputNumber size="small" min={0} step={0.1} value={value} onChange={onChange} style={{ width: 80 }} placeholder="不限" />
    </Space>
  )
}

function DateRangeFilter({ value, onChange }: { value: [Dayjs, Dayjs] | null, onChange: (v: [Dayjs, Dayjs] | null) => void }) {
  return (
    <RangePicker size="small" value={value} onChange={(dates) => {
      if (dates && dates[0] && dates[1]) onChange([dates[0], dates[1]])
      else onChange(null)
    }} style={{ width: 220 }} />
  )
}

function combinedSortBy(f1: string, f2: string): string {
  if (f1 && f2) return `${f1},${f2}`
  return f1 || f2
}

const numSort = (k: string) => (a: any, b: any) => (a[k] ?? 0) - (b[k] ?? 0)
const strSort = (k: string) => (a: any, b: any) => (a[k] ?? '').toString().localeCompare((b[k] ?? '').toString())

function Toolbar({ minVolume, onMinVolumeChange, dateRange, onDateRangeChange, sortField, sortField2, sortOrder, onSortChange, sortOptions, onExport, onRefresh }: {
  minVolume: number | null, onMinVolumeChange: (v: number | null) => void,
  dateRange: [Dayjs, Dayjs] | null, onDateRangeChange: (v: [Dayjs, Dayjs] | null) => void,
  sortField: string, sortField2: string, sortOrder: string, onSortChange: (field: string, field2: string, order: string) => void,
  sortOptions: { label: string, value: string }[],
  onExport: () => void,
  onRefresh: () => void,
}) {
  return (
    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
      <Space>
        <MinVolumeFilter value={minVolume} onChange={onMinVolumeChange} />
        <DateRangeFilter value={dateRange} onChange={onDateRangeChange} />
        {sortOptions.length > 0 && (
          <>
            <Select size="small" value={sortField || undefined} onChange={(v) => onSortChange(v ?? '', sortField2, sortOrder)} style={{ width: 100 }} placeholder="主排序" options={sortOptions} allowClear />
            <Select size="small" value={sortField2 || undefined} onChange={(v) => onSortChange(sortField, v ?? '', sortOrder)} style={{ width: 100 }} placeholder="次排序" options={sortOptions} allowClear />
            <Select size="small" value={sortOrder} onChange={(v) => onSortChange(sortField, sortField2, v)} style={{ width: 70 }} options={[{ label: '升序', value: 'asc' }, { label: '降序', value: 'desc' }]} />
          </>
        )}
      </Space>
      <Button icon={<DownloadOutlined />} size="small" onClick={onExport}>导出CSV</Button>
      <Button icon={<ReloadOutlined />} size="small" onClick={onRefresh} />
    </div>
  )
}

function ForcedRedemptionTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_risk_count: number; items: ForcedRedemptionItem[] } | null>(null)
  const [minVolume, setMinVolume] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [sortField, setSortField] = useState('')
  const [sortField2, setSortField2] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const loadSeqRef = useRef(0)
  const isMountedRef = useRef(true)

  const sortOptions = [
    { label: '风险等级', value: 'risk_level' },
    { label: '触发天数', value: 'trigger_days' },
    { label: '剩余年限', value: 'remaining_years' },
    { label: '占比', value: 'ratio' },
  ]

  const loadData = useCallback((mv?: number, sb?: string, so?: string, sd?: string, ed?: string) => {
    if (!isMountedRef.current) return
    const seq = ++loadSeqRef.current
    setLoading(true)
    const opts: any = {}
    if (mv != null && mv > 0) opts.min_volume = mv
    if (sb) opts.sort_by = sb
    if (so) opts.sort_order = so
    if (sd) opts.start_date = sd
    if (ed) opts.end_date = ed
    fetchForcedRedemption(Object.keys(opts).length > 0 ? opts : undefined).then(d => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setData(d) }).catch(e => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; message.error('加载强赎数据失败: ' + e.message) }).finally(() => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setLoading(false) })
  }, [])

  const dateStr = dateRange ? [dateRange[0].format('YYYY-MM-DD'), dateRange[1].format('YYYY-MM-DD')] : [undefined, undefined]

  useEffect(() => {
    isMountedRef.current = true
    loadData()
    return () => { isMountedRef.current = false }
  }, [])
  useAutoRefresh(() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1]), 60000)

  const handleMinVolumeChange = (v: number | null) => {
    setMinVolume(v)
    setPage(1)
    loadData(v ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])
  }

  const handleSortChange = (field: string, field2: string, order: string) => {
    setSortField(field)
    setSortField2(field2)
    setSortOrder(order)
    setPage(1)
    loadData(minVolume ?? undefined, combinedSortBy(field, field2) || undefined, order !== 'asc' ? order : undefined, dateStr[0], dateStr[1])
  }

  if (loading) return <Card size="small"><Skeleton active paragraph={{ rows: 8 }} /></Card>
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90, sorter: strSort('code') },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true, sorter: strSort('name') },
    { title: '正股价', dataIndex: 'stock_price', width: 80, sorter: numSort('stock_price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '转股价', dataIndex: 'conversion_price', width: 80, sorter: numSort('conversion_price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '占比', dataIndex: 'ratio', width: 80, sorter: numSort('ratio'), render: (v: number) => v != null ? `${v.toFixed(1)}%` : '-' },
    { title: '转股价值', dataIndex: 'conversion_value', width: 90, ellipsis: { showTitle: true }, sorter: numSort('conversion_value'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, sorter: numSort('premium_ratio'), render: (v: number) => v != null ? <Text style={{ color: v < 0 ? '#cf1322' : '#389e0d' }}>{v.toFixed(2)}%</Text> : '-' },
    { title: '触发天数', dataIndex: 'trigger_days', width: 80, ellipsis: { showTitle: true }, sorter: numSort('trigger_days'), render: (v: number | null) => v !== null ? `${v}天` : '-' },
    { title: '已计天数', dataIndex: 'forced_call_days', width: 80, ellipsis: { showTitle: true }, sorter: numSort('forced_call_days'), render: (v: number) => v != null ? v : '-' },
    { title: '风险等级', dataIndex: 'risk_level', width: 80, sorter: strSort('risk_level'), render: (v: string) => <Tag color={riskColor[v]}>{riskLabel[v] || v}</Tag> },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 80, ellipsis: { showTitle: true }, sorter: numSort('remaining_years'), render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
    { title: '回售压力', dataIndex: 'put_back_pressure', width: 80, sorter: (a: any, b: any) => (a.put_back_pressure ? 1 : 0) - (b.put_back_pressure ? 1 : 0), render: (v: boolean) => v ? <Tag color="purple">回售压力</Tag> : '-' },
  ]

  const handleExport = () => {
    const opts: any = {}
    if (minVolume && minVolume > 0) opts.min_volume = minVolume
    const sb = combinedSortBy(sortField, sortField2)
    if (sb) opts.sort_by = sb
    if (sortOrder !== 'asc') opts.sort_order = sortOrder
    if (dateRange) { opts.start_date = dateRange[0].format('YYYY-MM-DD'); opts.end_date = dateRange[1].format('YYYY-MM-DD') }
    window.open(getAnalysisExportUrl('forced-redemption', opts), '_blank')
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="高风险" value={data.high_risk_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Toolbar minVolume={minVolume} onMinVolumeChange={handleMinVolumeChange} dateRange={dateRange} onDateRangeChange={(v) => { setDateRange(v); setPage(1); const sd = v ? v[0].format('YYYY-MM-DD') : undefined; const ed = v ? v[1].format('YYYY-MM-DD') : undefined; loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, sd, ed) }} sortField={sortField} sortField2={sortField2} sortOrder={sortOrder} onSortChange={handleSortChange} sortOptions={sortOptions} onExport={handleExport} onRefresh={() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])} />
      <Table dataSource={data.items} rowKey={(r) => r.code} columns={columns} size="small" pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }} scroll={{ x: 950 }} />
    </div>
  )
}

function DualLowRankingTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; items: DualLowItem[] } | null>(null)
  const [minVolume, setMinVolume] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [sortField, setSortField] = useState('')
  const [sortField2, setSortField2] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(30)
  const loadSeqRef = useRef(0)
  const isMountedRef = useRef(true)

  const sortOptions = [
    { label: '双低值', value: 'dual_low' },
    { label: '价格', value: 'price' },
    { label: '溢价率', value: 'premium_ratio' },
    { label: '到期收益', value: 'ytm' },
  ]

  const loadData = useCallback((mv?: number, sb?: string, so?: string, sd?: string, ed?: string) => {
    if (!isMountedRef.current) return
    const seq = ++loadSeqRef.current
    setLoading(true)
    const opts: any = {}
    if (mv != null && mv > 0) opts.min_volume = mv
    if (sb) opts.sort_by = sb
    if (so) opts.sort_order = so
    if (sd) opts.start_date = sd
    if (ed) opts.end_date = ed
    fetchDualLowRanking(Object.keys(opts).length > 0 ? opts : undefined).then(d => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setData(d) }).catch(e => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; message.error('加载双低排名失败: ' + e.message) }).finally(() => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setLoading(false) })
  }, [])

  const dateStr = dateRange ? [dateRange[0].format('YYYY-MM-DD'), dateRange[1].format('YYYY-MM-DD')] : [undefined, undefined]

  useEffect(() => {
    isMountedRef.current = true
    loadData()
    return () => { isMountedRef.current = false }
  }, [])
  useAutoRefresh(() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1]), 60000)

  const handleMinVolumeChange = (v: number | null) => {
    setMinVolume(v)
    setPage(1)
    loadData(v ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])
  }

  const handleSortChange = (field: string, field2: string, order: string) => {
    setSortField(field)
    setSortField2(field2)
    setSortOrder(order)
    setPage(1)
    loadData(minVolume ?? undefined, combinedSortBy(field, field2) || undefined, order !== 'asc' ? order : undefined, dateStr[0], dateStr[1])
  }

  if (loading) return <Card size="small"><Skeleton active paragraph={{ rows: 8 }} /></Card>
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '排名', dataIndex: 'rank', width: 60, sorter: numSort('rank') },
    { title: '代码', dataIndex: 'code', width: 90, sorter: strSort('code') },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true, sorter: strSort('name') },
    { title: '价格', dataIndex: 'price', width: 80, sorter: numSort('price'), render: (v: number) => v != null ? <Text strong>{v.toFixed(2)}</Text> : '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, sorter: numSort('premium_ratio'), render: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '双低值', dataIndex: 'dual_low', width: 80, sorter: numSort('dual_low'), render: (v: number) => v != null ? <Text strong style={{ color: v < 130 ? '#389e0d' : v > 180 ? '#faad14' : undefined }}>{v.toFixed(2)}</Text> : '-' },
    { title: '到期税后收益', dataIndex: 'ytm', width: 100, ellipsis: { showTitle: true }, sorter: numSort('ytm'), render: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '成交量', dataIndex: 'volume', width: 90, sorter: numSort('volume'), render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 70, ellipsis: { showTitle: true }, sorter: numSort('remaining_years'), render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
    { title: '转股价值', dataIndex: 'conversion_value', width: 80, ellipsis: { showTitle: true }, sorter: numSort('conversion_value'), render: (v: number) => v?.toFixed(2) ?? '-' },
  ]

  const handleExport = () => {
    const opts: any = {}
    if (minVolume && minVolume > 0) opts.min_volume = minVolume
    const sb = combinedSortBy(sortField, sortField2)
    if (sb) opts.sort_by = sb
    if (sortOrder !== 'asc') opts.sort_order = sortOrder
    if (dateRange) { opts.start_date = dateRange[0].format('YYYY-MM-DD'); opts.end_date = dateRange[1].format('YYYY-MM-DD') }
    window.open(getAnalysisExportUrl('dual-low-ranking', opts), '_blank')
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
      </Row>
      <Toolbar minVolume={minVolume} onMinVolumeChange={handleMinVolumeChange} dateRange={dateRange} onDateRangeChange={(v) => { setDateRange(v); setPage(1); const sd = v ? v[0].format('YYYY-MM-DD') : undefined; const ed = v ? v[1].format('YYYY-MM-DD') : undefined; loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, sd, ed) }} sortField={sortField} sortField2={sortField2} sortOrder={sortOrder} onSortChange={handleSortChange} sortOptions={sortOptions} onExport={handleExport} onRefresh={() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])} />
      <Table dataSource={data.items} rowKey={(r) => `${r.code}`} columns={columns} size="small" pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }} scroll={{ x: 850 }} />
    </div>
  )
}

function PulseScanTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_severity_count: number; items: PulseItem[] } | null>(null)
  const [minVolume, setMinVolume] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [sortField, setSortField] = useState('')
  const [sortField2, setSortField2] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const loadSeqRef = useRef(0)
  const isMountedRef = useRef(true)

  const sortOptions = [
    { label: '涨跌幅', value: 'change_pct' },
    { label: '放量倍数', value: 'volume_ratio' },
    { label: '溢价率', value: 'premium_ratio' },
    { label: '双低值', value: 'dual_low' },
  ]

  const loadData = useCallback((mv?: number, sb?: string, so?: string, sd?: string, ed?: string) => {
    if (!isMountedRef.current) return
    const seq = ++loadSeqRef.current
    setLoading(true)
    const opts: any = {}
    if (mv != null && mv > 0) opts.min_volume = mv
    if (sb) opts.sort_by = sb
    if (so) opts.sort_order = so
    if (sd) opts.start_date = sd
    if (ed) opts.end_date = ed
    fetchPulseScan(Object.keys(opts).length > 0 ? opts : undefined).then(d => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setData(d) }).catch(e => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; message.error('加载脉冲扫描失败: ' + e.message) }).finally(() => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setLoading(false) })
  }, [])

  const dateStr = dateRange ? [dateRange[0].format('YYYY-MM-DD'), dateRange[1].format('YYYY-MM-DD')] : [undefined, undefined]

  useEffect(() => {
    isMountedRef.current = true
    loadData()
    return () => { isMountedRef.current = false }
  }, [])
  useAutoRefresh(() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1]), 10000)

  const handleMinVolumeChange = (v: number | null) => {
    setMinVolume(v)
    setPage(1)
    loadData(v ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])
  }

  const handleSortChange = (field: string, field2: string, order: string) => {
    setSortField(field)
    setSortField2(field2)
    setSortOrder(order)
    setPage(1)
    loadData(minVolume ?? undefined, combinedSortBy(field, field2) || undefined, order !== 'asc' ? order : undefined, dateStr[0], dateStr[1])
  }

  if (loading) return <Card size="small"><Skeleton active paragraph={{ rows: 8 }} /></Card>
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90, sorter: strSort('code') },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true, sorter: strSort('name') },
    { title: '脉冲类型', dataIndex: 'pulse_type', width: 90, sorter: strSort('pulse_type'), render: (v: string) => {
      const colorMap: Record<string, string> = { '价格大涨': 'red', '价格大跌': 'green', '放量': 'volcano', '异动': 'orange', '低双低': 'lime', '高溢价': 'blue', '临近到期': 'purple', '价背离': 'magenta' }
      return <Tag color={colorMap[v] || 'default'}>{v}</Tag>
    }},
    { title: '涨跌幅', dataIndex: 'change_pct', width: 80, sorter: numSort('change_pct'), render: (v: number) => (
      <span style={{ color: v != null && v >= 0 ? '#cf1322' : '#389e0d' }}>
        {v != null && v >= 0 ? <RiseOutlined /> : <FallOutlined />} {v != null ? Math.abs(v).toFixed(2) : '-'}%
      </span>
    )},
    { title: '价格', dataIndex: 'price', width: 70, sorter: numSort('price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '成交量', dataIndex: 'volume', width: 90, sorter: numSort('volume'), render: (v: number) => v != null ? v.toLocaleString() : '-' },
    { title: '放量倍数', dataIndex: 'volume_ratio', width: 70, ellipsis: { showTitle: true }, sorter: numSort('volume_ratio'), render: (v: number) => v != null ? `${v.toFixed(1)}x` : '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, ellipsis: { showTitle: true }, sorter: numSort('premium_ratio'), render: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '双低值', dataIndex: 'dual_low', width: 70, ellipsis: { showTitle: true }, sorter: numSort('dual_low'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 70, ellipsis: { showTitle: true }, sorter: numSort('remaining_years'), render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
    { title: '严重程度', dataIndex: 'severity', width: 70, sorter: strSort('severity'), render: (v: string) => <Tag color={severityColor[v]}>{severityLabel[v] || v}</Tag> },
  ]

  const handleExport = () => {
    const opts: any = {}
    if (minVolume && minVolume > 0) opts.min_volume = minVolume
    const sb = combinedSortBy(sortField, sortField2)
    if (sb) opts.sort_by = sb
    if (sortOrder !== 'asc') opts.sort_order = sortOrder
    if (dateRange) { opts.start_date = dateRange[0].format('YYYY-MM-DD'); opts.end_date = dateRange[1].format('YYYY-MM-DD') }
    window.open(getAnalysisExportUrl('pulse-scan', opts), '_blank')
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="告警总数" value={data.total} /></Card></Col>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="严重" value={data.high_severity_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Toolbar minVolume={minVolume} onMinVolumeChange={handleMinVolumeChange} dateRange={dateRange} onDateRangeChange={(v) => { setDateRange(v); setPage(1); const sd = v ? v[0].format('YYYY-MM-DD') : undefined; const ed = v ? v[1].format('YYYY-MM-DD') : undefined; loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, sd, ed) }} sortField={sortField} sortField2={sortField2} sortOrder={sortOrder} onSortChange={handleSortChange} sortOptions={sortOptions} onExport={handleExport} onRefresh={() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])} />
      <Table dataSource={data.items} rowKey={(r) => `${r.code}-${r.pulse_type}`} columns={columns} size="small" pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }} scroll={{ x: 800 }} />
    </div>
  )
}

function RevisionProbabilityTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_probability_count: number; items: RevisionItem[] } | null>(null)
  const [minVolume, setMinVolume] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [sortField, setSortField] = useState('')
  const [sortField2, setSortField2] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const loadSeqRef = useRef(0)
  const isMountedRef = useRef(true)

  const sortOptions = [
    { label: '概率', value: 'probability' },
    { label: '价差', value: 'price_distance' },
    { label: '溢价率', value: 'premium_ratio' },
    { label: '剩余年限', value: 'remaining_years' },
  ]

  const loadData = useCallback((mv?: number, sb?: string, so?: string, sd?: string, ed?: string) => {
    if (!isMountedRef.current) return
    const seq = ++loadSeqRef.current
    setLoading(true)
    const opts: any = {}
    if (mv != null && mv > 0) opts.min_volume = mv
    if (sb) opts.sort_by = sb
    if (so) opts.sort_order = so
    if (sd) opts.start_date = sd
    if (ed) opts.end_date = ed
    fetchRevisionProbability(Object.keys(opts).length > 0 ? opts : undefined).then(d => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setData(d) }).catch(e => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; message.error('加载下修概率失败: ' + e.message) }).finally(() => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setLoading(false) })
  }, [])

  const dateStr = dateRange ? [dateRange[0].format('YYYY-MM-DD'), dateRange[1].format('YYYY-MM-DD')] : [undefined, undefined]

  useEffect(() => {
    isMountedRef.current = true
    loadData()
    return () => { isMountedRef.current = false }
  }, [])
  useAutoRefresh(() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1]))

  const handleMinVolumeChange = (v: number | null) => {
    setMinVolume(v)
    setPage(1)
    loadData(v ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])
  }

  const handleSortChange = (field: string, field2: string, order: string) => {
    setSortField(field)
    setSortField2(field2)
    setSortOrder(order)
    setPage(1)
    loadData(minVolume ?? undefined, combinedSortBy(field, field2) || undefined, order !== 'asc' ? order : undefined, dateStr[0], dateStr[1])
  }

  if (loading) return <Card size="small"><Skeleton active paragraph={{ rows: 8 }} /></Card>
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90, sorter: strSort('code') },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true, sorter: strSort('name') },
    { title: '正股价', dataIndex: 'stock_price', width: 70, ellipsis: { showTitle: true }, sorter: numSort('stock_price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '转股价', dataIndex: 'conversion_price', width: 70, ellipsis: { showTitle: true }, sorter: numSort('conversion_price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '价差', dataIndex: 'price_distance', width: 60, ellipsis: { showTitle: true }, sorter: numSort('price_distance'), render: (v: number) => v != null ? `${v.toFixed(1)}%` : '-' },
    { title: '概率', dataIndex: 'probability', width: 120, sorter: numSort('probability'), render: (v: number, record: RevisionItem) => (
      <Space>
        <Progress percent={v} size="small" style={{ width: 80 }} strokeColor={v >= 60 ? '#cf1322' : v >= 30 ? '#faad14' : '#52c41a'} />
        <Tag color={riskColor[record.level]}>{riskLabel[record.level] || record.level}</Tag>
      </Space>
    )},
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, ellipsis: { showTitle: true }, sorter: numSort('premium_ratio'), render: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 70, ellipsis: { showTitle: true }, sorter: numSort('remaining_years'), render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
  ]

  const handleExport = () => {
    const opts: any = {}
    if (minVolume && minVolume > 0) opts.min_volume = minVolume
    const sb = combinedSortBy(sortField, sortField2)
    if (sb) opts.sort_by = sb
    if (sortOrder !== 'asc') opts.sort_order = sortOrder
    if (dateRange) { opts.start_date = dateRange[0].format('YYYY-MM-DD'); opts.end_date = dateRange[1].format('YYYY-MM-DD') }
    window.open(getAnalysisExportUrl('revision-probability', opts), '_blank')
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="高概率下修" value={data.high_probability_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Toolbar minVolume={minVolume} onMinVolumeChange={handleMinVolumeChange} dateRange={dateRange} onDateRangeChange={(v) => { setDateRange(v); setPage(1); const sd = v ? v[0].format('YYYY-MM-DD') : undefined; const ed = v ? v[1].format('YYYY-MM-DD') : undefined; loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, sd, ed) }} sortField={sortField} sortField2={sortField2} sortOrder={sortOrder} onSortChange={handleSortChange} sortOptions={sortOptions} onExport={handleExport} onRefresh={() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])} />
      <Table dataSource={data.items} rowKey={(r) => r.code} columns={columns} size="small" pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }} scroll={{ x: 700 }} />
    </div>
  )
}

function StockCorrelationTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; strong_correlation_count: number; items: StockCorrelationItem[] } | null>(null)
  const [minVolume, setMinVolume] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null)
  const [sortField, setSortField] = useState('')
  const [sortField2, setSortField2] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const loadSeqRef = useRef(0)
  const isMountedRef = useRef(true)

  const sortOptions = [
    { label: '弹性系数', value: 'elasticity' },
    { label: '相关系数', value: 'pearson_correlation' },
    { label: '溢价率', value: 'premium_ratio' },
    { label: '双低值', value: 'dual_low' },
  ]

  const loadData = useCallback((mv?: number, sb?: string, so?: string, sd?: string, ed?: string) => {
    if (!isMountedRef.current) return
    const seq = ++loadSeqRef.current
    setLoading(true)
    const opts: any = {}
    if (mv != null && mv > 0) opts.min_volume = mv
    if (sb) opts.sort_by = sb
    if (so) opts.sort_order = so
    if (sd) opts.start_date = sd
    if (ed) opts.end_date = ed
    fetchStockCorrelation(Object.keys(opts).length > 0 ? opts : undefined).then(d => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setData(d) }).catch(e => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; message.error('加载正股关联失败: ' + e.message) }).finally(() => { if (!isMountedRef.current || seq !== loadSeqRef.current) return; setLoading(false) })
  }, [])

  const dateStr = dateRange ? [dateRange[0].format('YYYY-MM-DD'), dateRange[1].format('YYYY-MM-DD')] : [undefined, undefined]

  useEffect(() => {
    isMountedRef.current = true
    loadData()
    return () => { isMountedRef.current = false }
  }, [])
  useAutoRefresh(() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1]))

  const handleMinVolumeChange = (v: number | null) => {
    setMinVolume(v)
    setPage(1)
    loadData(v ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])
  }

  const handleSortChange = (field: string, field2: string, order: string) => {
    setSortField(field)
    setSortField2(field2)
    setSortOrder(order)
    setPage(1)
    loadData(minVolume ?? undefined, combinedSortBy(field, field2) || undefined, order !== 'asc' ? order : undefined, dateStr[0], dateStr[1])
  }

  if (loading) return <Card size="small"><Skeleton active paragraph={{ rows: 8 }} /></Card>
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90, sorter: strSort('code') },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true, sorter: strSort('name') },
    { title: '转债涨跌', dataIndex: 'bond_change', width: 80, sorter: numSort('bond_change'), render: (v: number) => <span style={{ color: v == null ? undefined : (v >= 0 ? '#cf1322' : '#389e0d') }}>{v != null ? v.toFixed(2) : '-'}%</span> },
    { title: '正股涨跌', dataIndex: 'stock_change', width: 80, sorter: numSort('stock_change'), render: (v: number) => <span style={{ color: v == null ? undefined : (v >= 0 ? '#cf1322' : '#389e0d') }}>{v != null ? v.toFixed(2) : '-'}%</span> },
    { title: '弹性系数', dataIndex: 'elasticity', width: 80, ellipsis: { showTitle: true }, sorter: numSort('elasticity'), render: (v: number) => <Text strong>{v != null ? v.toFixed(4) : '-'}</Text> },
    { title: '关联度', dataIndex: 'correlation', width: 70, sorter: strSort('correlation'), render: (v: string) => {
      const colorMap: Record<string, string> = { '强关联': 'red', '中关联': 'orange', '弱关联': 'blue', '待观察': 'default' }
      return <Tag color={colorMap[v] || 'default'}>{v || '-'}</Tag>
    }},
    { title: '相关系数', dataIndex: 'pearson_correlation', width: 80, ellipsis: { showTitle: true }, sorter: numSort('pearson_correlation'), render: (v: number | null) => v != null ? <Text style={{ color: v >= 0.5 ? '#389e0d' : v <= -0.5 ? '#cf1322' : undefined }}>{v.toFixed(3)}</Text> : '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, ellipsis: { showTitle: true }, sorter: numSort('premium_ratio'), render: (v: number) => v != null ? `${v.toFixed(2)}%` : '-' },
    { title: '转股价值', dataIndex: 'conversion_value', width: 80, ellipsis: { showTitle: true }, sorter: numSort('conversion_value'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '价格', dataIndex: 'price', width: 70, sorter: numSort('price'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '双低值', dataIndex: 'dual_low', width: 70, ellipsis: { showTitle: true }, sorter: numSort('dual_low'), render: (v: number) => v != null ? v.toFixed(2) : '-' },
  ]

  const handleExport = () => {
    const opts: any = {}
    if (minVolume && minVolume > 0) opts.min_volume = minVolume
    const sb = combinedSortBy(sortField, sortField2)
    if (sb) opts.sort_by = sb
    if (sortOrder !== 'asc') opts.sort_order = sortOrder
    if (dateRange) { opts.start_date = dateRange[0].format('YYYY-MM-DD'); opts.end_date = dateRange[1].format('YYYY-MM-DD') }
    window.open(getAnalysisExportUrl('stock-correlation', opts), '_blank')
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
        <Col xs={24} sm={12} md={6}><Card size="small"><Statistic title="强关联" value={data.strong_correlation_count ?? 0} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Toolbar minVolume={minVolume} onMinVolumeChange={handleMinVolumeChange} dateRange={dateRange} onDateRangeChange={(v) => { setDateRange(v); setPage(1); const sd = v ? v[0].format('YYYY-MM-DD') : undefined; const ed = v ? v[1].format('YYYY-MM-DD') : undefined; loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, sd, ed) }} sortField={sortField} sortField2={sortField2} sortOrder={sortOrder} onSortChange={handleSortChange} sortOptions={sortOptions} onExport={handleExport} onRefresh={() => loadData(minVolume ?? undefined, combinedSortBy(sortField, sortField2) || undefined, sortOrder !== 'asc' ? sortOrder : undefined, dateStr[0], dateStr[1])} />
      <Table dataSource={data.items} rowKey={(r) => r.code} columns={columns} size="small" pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }} scroll={{ x: 750 }} />
    </div>
  )
}

export default function Analysis() {
  const [cacheInfo, setCacheInfo] = useState<{ hits: number; misses: number; size: number; ttl: number; hit_rate: number } | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const unsub = marketWs.subscribe('revision', (data: any) => {
      if (data?.code) {
        notification.info({
          message: '转股价下修',
          description: `${data.code} 转股价由 ${data.old_price ?? '?'} 下调至 ${data.new_price ?? '?'}`,
          duration: 8,
        })
      }
    })
    return unsub
  }, [])

  const isMountedRef = useRef(true)

  useEffect(() => {
    isMountedRef.current = true
    const load = async () => {
      try {
        const info = await fetchCacheStats()
        if (!isMountedRef.current) return
        setCacheInfo(info)
      } catch {}
    }
    load()
    const id = setInterval(() => {
      if (!isMountedRef.current) return
      load()
    }, 30000)
    return () => { isMountedRef.current = false; clearInterval(id) }
  }, [])

  const hitRate = cacheInfo?.hit_rate != null
    ? `${(cacheInfo.hit_rate * 100).toFixed(0)}%`
    : '-'
  const hitRateColor = cacheInfo?.hit_rate != null
    ? cacheInfo.hit_rate >= 0.7 ? '#389e0d'
      : cacheInfo.hit_rate >= 0.3 ? '#faad14'
      : '#cf1322'
    : undefined

  const tabItems = useMemo(() => [
    { key: 'forced-redemption', label: <span><AlertOutlined /> 强赎日历</span>, children: <ForcedRedemptionTab /> },
    { key: 'dual-low', label: <span><OrderedListOutlined /> 双低排名</span>, children: <DualLowRankingTab /> },
    { key: 'pulse', label: <span><RiseOutlined /> 脉冲扫描</span>, children: <PulseScanTab /> },
    { key: 'revision', label: <span><FallOutlined /> 下修概率</span>, children: <RevisionProbabilityTab /> },
    { key: 'correlation', label: <span><LinkOutlined /> 正股关联</span>, children: <StockCorrelationTab /> },
  ], [])

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          <FundProjectionScreenOutlined /> 分析工具
        </Title>
        {cacheInfo && (
          <Space size={8}>
            <Text style={{ fontSize: 12 }}>
              缓存命中率: <span style={{ color: hitRateColor }}>{hitRate}</span> | 条目: {cacheInfo.size} | TTL: {cacheInfo.ttl}s
            </Text>
            <Button size="small" type="link" onClick={() => {
              clearCache().then((r: any) => {
                message.success(`已清除 ${r.cleared_entries} 条缓存`)
                fetchCacheStats().then(setCacheInfo)
                setRefreshKey(k => k + 1)
              }).catch(() => message.error('清除缓存失败'))
            }}>清除缓存</Button>
          </Space>
        )}
      </div>

      <Card size="small" key={refreshKey}>
        <Tabs
          defaultActiveKey="forced-redemption"
          destroyInactiveTabPane
          items={tabItems}
        />
      </Card>
    </div>
  )
}
