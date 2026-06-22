import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Card, Table, Empty, Space, Button, Drawer, Descriptions, Statistic, Row, Col, message, Popconfirm, InputNumber, Checkbox } from 'antd'
import { HistoryOutlined, EyeOutlined, DeleteOutlined, ReloadOutlined, ClearOutlined, SwapOutlined, DownloadOutlined, PrinterOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import {
  fetchBacktestHistory, fetchBacktestDetail, deleteBacktestResult, cleanupBacktestHistory,
  type BacktestHistoryItem, type BacktestHistoryDetail,
} from '../../services/api'

export default React.memo(function BacktestHistoryTab() {
  const [history, setHistory] = useState<BacktestHistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [detailVisible, setDetailVisible] = useState(false)
  const [detailSummary, setDetailSummary] = useState<BacktestHistoryItem | null>(null)
  const [detailRows, setDetailRows] = useState<BacktestHistoryDetail[]>([])
  const [cleanupDays, setCleanupDays] = useState(90)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [compareVisible, setCompareVisible] = useState(false)
  const [compareData, setCompareData] = useState<{ items: { summary: BacktestHistoryItem; details: BacktestHistoryDetail[] }[] } | null>(null)

  const loadHistory = useCallback(async (p?: number, ps?: number) => {
    setLoading(true)
    const currentPage = p ?? page
    const currentPageSize = ps ?? pageSize
    try {
      const offset = (currentPage - 1) * currentPageSize
      const res = await fetchBacktestHistory(currentPageSize, offset)
      setHistory(res.results)
      setTotal(res.total)
    } catch {
      message.error('加载回测历史失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { loadHistory() }, [loadHistory])

  const viewDetail = useCallback(async (item: BacktestHistoryItem) => {
    try {
      const res = await fetchBacktestDetail(item.id)
      setDetailSummary(res.summary)
      setDetailRows(res.details)
      setDetailVisible(true)
    } catch {
      message.error('加载详情失败')
    }
  }, [])

  const handleDelete = useCallback(async (id: number) => {
    try {
      await deleteBacktestResult(id)
      message.success('已删除')
      setSelectedIds(prev => prev.filter(x => x !== id))
      loadHistory()
    } catch {
      message.error('删除失败')
    }
  }, [loadHistory])

  const handleCleanup = useCallback(async () => {
    try {
      const res = await cleanupBacktestHistory(cleanupDays)
      message.success(`已清理 ${res.deleted_count} 条过期记录`)
      loadHistory()
    } catch {
      message.error('清理失败')
    }
  }, [cleanupDays, loadHistory])

  const handleCompare = useCallback(async () => {
    if (selectedIds.length < 2) { message.warning('请至少选择两条记录进行对比'); return }
    try {
      const results = await Promise.all(selectedIds.map(id => fetchBacktestDetail(id)))
      setCompareData({ items: results.map(r => ({ summary: r.summary, details: r.details })) })
      setCompareVisible(true)
    } catch {
      message.error('加载对比数据失败')
    }
  }, [selectedIds])

  const returnColor = (v: number) => v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : undefined

  const columns = [
    {
      title: '', width: 40,
      render: (_: unknown, r: BacktestHistoryItem) => (
        <Checkbox checked={selectedIds.includes(r.id)} onChange={e => {
          setSelectedIds(prev => e.target.checked ? [...prev, r.id].slice(-5) : prev.filter(x => x !== r.id))
        }} />
      ),
    },
    { title: '运行时间', dataIndex: 'run_ts', width: 130, render: (v: string) => dayjs(v).format('MM-DD HH:mm') },
    { title: '区间', width: 150, render: (_: unknown, r: BacktestHistoryItem) => `${r.start_date} ~ ${r.end_date}` },
    { title: 'TopN', dataIndex: 'top_n', width: 55, align: 'center' as const },
    { title: '持有', dataIndex: 'hold_days', width: 55, align: 'center' as const },
    { title: '平均收益', dataIndex: 'avg_return_pct', width: 90, render: (v: number) => <span style={{ color: returnColor(v) }}>{v?.toFixed(2)}%</span> },
    { title: '胜率', dataIndex: 'win_rate', width: 70, render: (v: number) => <span style={{ color: v >= 50 ? '#3f8600' : '#cf1322' }}>{v?.toFixed(1)}%</span> },
    { title: '期数', dataIndex: 'total_periods', width: 50, align: 'center' as const },
    {
      title: '操作', width: 120, render: (_: unknown, r: BacktestHistoryItem) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r)}>详情</Button>
          <Popconfirm title="确认删除此回测记录？" onConfirm={() => handleDelete(r.id)} okText="删除" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const detailColumns = [
    { title: '日期', dataIndex: 'date', width: 100 },
    { title: '结束日', dataIndex: 'end_date', width: 100 },
    { title: 'TopN', dataIndex: 'top_n', width: 60, align: 'center' as const },
    { title: '平均收益', dataIndex: 'avg_return_pct', width: 100, render: (v: number) => <span style={{ color: returnColor(v) }}>{v?.toFixed(2)}%</span> },
    { title: '胜率', dataIndex: 'win_rate', width: 80, render: (v: number) => `${v?.toFixed(1)}%` },
    { title: '最大收益', dataIndex: 'max_return', width: 90, render: (v: number) => <span style={{ color: v > 0 ? '#cf1322' : undefined }}>{v?.toFixed(2)}%</span> },
    { title: '最大亏损', dataIndex: 'min_return', width: 90, render: (v: number) => <span style={{ color: v < 0 ? '#3f8600' : undefined }}>{v?.toFixed(2)}%</span> },
    { title: '最大回撤', dataIndex: 'max_drawdown', width: 90, render: (v: number) => <span style={{ color: v > 0 ? '#3f8600' : undefined }}>-{v?.toFixed(2)}%</span> },
  ]

  const COMPARE_COLORS = ['#1677ff', '#52c41a', '#faad14', '#722ed1', '#eb2f96']
  const COMPARE_LABELS = ['A', 'B', 'C', 'D', 'E']

  const compareColumns = useMemo(() => {
    if (!compareData) return []
    const n = compareData.items.length
    const cols: any[] = [{ title: '日期', dataIndex: 'date', width: 90, fixed: 'left' as const }]
    for (let i = 0; i < n; i++) {
      cols.push({ title: `#${compareData.items[i].summary.id} 收益`, width: 90, render: (_: unknown, r: any) => {
        const d = r.details?.[i]
        return d ? <span style={{ color: returnColor(d.avg_return_pct) }}>{(d.avg_return_pct ?? 0).toFixed(2)}%</span> : '-'
      }})
      cols.push({ title: `#${compareData.items[i].summary.id} 胜率`, width: 70, render: (_: unknown, r: any) => {
        const d = r.details?.[i]
        return d ? `${(d.win_rate ?? 0).toFixed(1)}%` : '-'
      }})
    }
    return cols
  }, [compareData])

  const compareTableData = useMemo(() => {
    if (!compareData) return []
    const dateMap = new Map<string, { details: (BacktestHistoryDetail | undefined)[] }>()
    for (let i = 0; i < compareData.items.length; i++) {
      for (const d of compareData.items[i].details) {
        const existing = dateMap.get(d.date)
        if (existing) { existing.details[i] = d }
        else { const arr: (BacktestHistoryDetail | undefined)[] = new Array(compareData.items.length); arr[i] = d; dateMap.set(d.date, { details: arr }) }
      }
    }
    return Array.from(dateMap.entries()).map(([date, val]) => ({ date, ...val }))
  }, [compareData])

  return (
    <div style={{ padding: 16 }}>
      <Card
        size="small"
        title={<Space><HistoryOutlined />回测历史记录</Space>}
        extra={
          <Space size="small">
            <Button size="small" icon={<SwapOutlined />} onClick={handleCompare}
              disabled={selectedIds.length < 2}
              type={selectedIds.length >= 2 ? 'primary' : 'default'}
            >对比 ({selectedIds.length}/5)</Button>
            <Popconfirm title={`确认删除选中的 ${selectedIds.length} 条记录？`} onConfirm={async () => {
              let ok = 0, fail = 0
              for (const id of selectedIds) {
                try { await deleteBacktestResult(id); ok++ } catch { fail++ }
              }
              message.success(`删除完成: ${ok} 成功${fail > 0 ? `, ${fail} 失败` : ''}`)
              setSelectedIds([])
              loadHistory()
            }} disabled={selectedIds.length === 0} okText="删除" cancelText="取消">
              <Button size="small" danger icon={<DeleteOutlined />} disabled={selectedIds.length === 0}>删除 ({selectedIds.length})</Button>
            </Popconfirm>
            <span style={{ fontSize: 12, color: '#666' }}>保留</span>
            <InputNumber size="small" min={1} max={365} value={cleanupDays} onChange={v => v && setCleanupDays(v)} style={{ width: 60 }} />
            <span style={{ fontSize: 12, color: '#666' }}>天</span>
            <Popconfirm title={`确认清理 ${cleanupDays} 天前的回测记录？`} onConfirm={handleCleanup} okText="清理" cancelText="取消">
              <Button size="small" icon={<ClearOutlined />}>批量清理</Button>
            </Popconfirm>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadHistory()} loading={loading}>刷新</Button>
          </Space>
        }
      >
        {history.length > 0 ? (
          <Table
            dataSource={history}
            rowKey="id"
            size="small"
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => { setPage(p); setPageSize(ps); loadHistory(p, ps) },
            }}
            columns={columns}
          />
        ) : <Empty description="暂无回测历史，执行评分回测后自动保存" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>

      <Drawer
        title={detailSummary ? `回测详情 #${detailSummary.id}` : '回测详情'}
        placement="right"
        width={640}
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
        extra={detailSummary ? (
          <Button size="small" icon={<DownloadOutlined />} onClick={() => {
            if (!detailSummary) return
            const header = '日期,结束日,TopN,平均收益%,胜率%,最大收益%,最大亏损%,最大回撤%'
            const rows = detailRows.map(d => `${d.date},${d.end_date},${d.top_n},${d.avg_return_pct},${d.win_rate},${d.max_return},${d.min_return},${d.max_drawdown}`)
            const summaryLine = `# 汇总: 区间=${detailSummary.start_date}~${detailSummary.end_date}, TopN=${detailSummary.top_n}, 持有=${detailSummary.hold_days}天, 平均收益=${detailSummary.avg_return_pct}%, 胜率=${detailSummary.win_rate}%`
            const csv = [summaryLine, header, ...rows].join('\n')
            const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `backtest_${detailSummary.id}_${dayjs().format('YYYYMMDD')}.csv`
            a.click()
            URL.revokeObjectURL(url)
          }}>导出 CSV</Button>
        ) : undefined}
      >
        {detailSummary && (
          <>
            <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="运行时间">{dayjs(detailSummary.run_ts).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
              <Descriptions.Item label="区间">{detailSummary.start_date} ~ {detailSummary.end_date}</Descriptions.Item>
              <Descriptions.Item label="TopN">{detailSummary.top_n}</Descriptions.Item>
              <Descriptions.Item label="持有天数">{detailSummary.hold_days}</Descriptions.Item>
            </Descriptions>
            <Row gutter={8} style={{ marginBottom: 16 }}>
              <Col span={3}><Statistic title="平均收益" value={detailSummary.avg_return_pct} precision={2} suffix="%" valueStyle={{ color: returnColor(detailSummary.avg_return_pct) }} /></Col>
              <Col span={3}><Statistic title="胜率" value={detailSummary.win_rate} precision={1} suffix="%" valueStyle={{ color: detailSummary.win_rate >= 50 ? '#3f8600' : '#cf1322' }} /></Col>
              <Col span={2}><Statistic title="期数" value={detailSummary.total_periods} /></Col>
              <Col span={3}>{(() => {
                const lastDD = detailRows.length > 0 ? detailRows[detailRows.length - 1].max_drawdown : 0
                const maxDD = lastDD > 0 ? lastDD : (() => {
                  let cum = 0, peak = 0, dd = 0
                  for (const d of detailRows) { cum += d.avg_return_pct; if (cum > peak) peak = cum; const v = peak - cum; if (v > dd) dd = v }
                  return dd
                })()
                return <Statistic title="最大回撤" value={-maxDD} precision={2} suffix="%" valueStyle={{ color: maxDD > 0 ? '#3f8600' : undefined }} />
              })()}</Col>
              <Col span={3}>{(() => {
                const returns = detailRows.map(d => d.avg_return_pct)
                const mean = returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : 0
                const std = returns.length > 1 ? Math.sqrt(returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (returns.length - 1)) : 0
                const riskFreePerPeriod = 0.01 / 12
                const sharpe = std > 0 ? (mean - riskFreePerPeriod) / std : 0
                return <Statistic title="Sharpe" value={sharpe} precision={2} valueStyle={{ color: sharpe >= 2 ? '#3f8600' : sharpe >= 1 ? '#52c41a' : sharpe >= 0 ? '#faad14' : '#cf1322' }} />
              })()}</Col>
              <Col span={3}>{(() => {
                const returns = detailRows.map(d => d.avg_return_pct)
                const mean = returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : 0
                const riskFreePerPeriod = 0.01 / 12
                const downReturns = returns.filter(r => r < riskFreePerPeriod).map(r => (r - riskFreePerPeriod) ** 2)
                const downStd = downReturns.length > 0 ? Math.sqrt(downReturns.reduce((a, b) => a + b, 0) / downReturns.length) : 0
                const sortino = downStd > 0 ? (mean - riskFreePerPeriod) / downStd : 0
                return <Statistic title="Sortino" value={sortino} precision={2} valueStyle={{ color: sortino >= 2 ? '#3f8600' : sortino >= 1 ? '#52c41a' : sortino >= 0 ? '#faad14' : '#cf1322' }} />
              })()}</Col>
              <Col span={3}>{(() => {
                const lastDD = detailRows.length > 0 ? detailRows[detailRows.length - 1].max_drawdown : 0
                const maxDD = lastDD > 0 ? lastDD : (() => {
                  let cum = 0, peak = 0, dd = 0
                  for (const d of detailRows) { cum += d.avg_return_pct; if (cum > peak) peak = cum; const v = peak - cum; if (v > dd) dd = v }
                  return dd
                })()
                const totalReturn = detailRows.reduce((s, d) => s + d.avg_return_pct, 0)
                const calmar = maxDD > 0 ? totalReturn / maxDD : 0
                return <Statistic title="Calmar" value={calmar} precision={2} valueStyle={{ color: calmar >= 1 ? '#3f8600' : calmar > 0 ? '#faad14' : '#cf1322' }} />
              })()}</Col>
              <Col span={3}>{(() => {
                const wins = detailRows.filter(d => d.avg_return_pct > 0)
                const losses = detailRows.filter(d => d.avg_return_pct < 0)
                const avgWin = wins.length > 0 ? wins.reduce((s, d) => s + d.avg_return_pct, 0) / wins.length : 0
                const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((s, d) => s + d.avg_return_pct, 0) / losses.length) : 0
                const plRatio = avgLoss > 0 ? avgWin / avgLoss : wins.length > 0 ? 99 : 0
                return <Statistic title="盈亏比" value={plRatio > 50 ? 99 : plRatio} precision={2} valueStyle={{ color: plRatio >= 2 ? '#3f8600' : plRatio >= 1 ? '#faad14' : '#cf1322' }} />
              })()}</Col>
              <Col span={3}>{(() => {
                let maxStreak = 0, streak = 0
                for (const d of detailRows) { if (d.avg_return_pct < 0) { streak++; if (streak > maxStreak) maxStreak = streak } else streak = 0 }
                return <Statistic title="连续亏损" value={maxStreak} suffix="期" valueStyle={{ color: maxStreak <= 2 ? '#3f8600' : maxStreak <= 4 ? '#faad14' : '#cf1322' }} />
              })()}</Col>
              <Col span={3}>{(() => {
                const wins = detailRows.filter(d => d.avg_return_pct > 0).length
                const total = detailRows.length || 1
                return <Statistic title="盈利期数" value={`${wins}/${total}`} valueStyle={{ fontSize: 16 }} />
              })()}</Col>
            </Row>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}>
                <Card size="small" title="胜率分布">
                  {(() => {
                    const win = detailRows.filter(d => d.avg_return_pct > 0).length
                    const lose = detailRows.filter(d => d.avg_return_pct < 0).length
                    const flat = detailRows.filter(d => d.avg_return_pct === 0).length
                    return <ReactEChartsCore echarts={echarts} option={{
                      tooltip: { trigger: 'item' as const },
                      series: [{ type: 'pie', radius: ['40%', '70%'], data: [
                        { value: win, name: '盈利', itemStyle: { color: '#cf1322' } },
                        { value: lose, name: '亏损', itemStyle: { color: '#3f8600' } },
                        ...(flat > 0 ? [{ value: flat, name: '持平', itemStyle: { color: '#d9d9d9' } }] : []),
                      ], label: { fontSize: 11 } }],
                    }} style={{ height: 160 }} />
                  })()}
                </Card>
              </Col>
              <Col span={10}>
                <Card size="small" title="收益走势">
                  {(() => {
                    const dates = detailRows.map(d => d.date.slice(5))
                    const returns = detailRows.map(d => d.avg_return_pct)
                    let cum = 0
                    const cumReturns = returns.map(r => { cum += r; return Math.round(cum * 100) / 100 })
                    const option = {
                      tooltip: { trigger: 'axis' as const },
                      legend: { data: ['各期收益', '累计收益'] },
                      grid: { left: 50, right: 20, top: 30, bottom: 30 },
                      xAxis: { type: 'category' as const, data: dates },
                      yAxis: { type: 'value' as const, name: '%' },
                      series: [
                        { name: '各期收益', type: 'bar', data: returns, itemStyle: { color: (p: any) => p.value >= 0 ? '#cf1322' : '#3f8600' } },
                        { name: '累计收益', type: 'line', data: cumReturns, smooth: true, itemStyle: { color: '#1677ff' } },
                      ],
                    }
                    return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 160 }} />
                  })()}
                </Card>
              </Col>
              <Col span={8}>
                <Card size="small" title="回撤曲线">
                  {(() => {
                    const dates = detailRows.map(d => d.date.slice(5))
                    const drawdowns = detailRows.map(d => -d.max_drawdown)
                    const option = {
                      tooltip: { trigger: 'axis' as const, formatter: (ps: any) => `${ps[0].name}<br/>回撤: ${(ps[0].value ?? 0).toFixed(2)}%` },
                      grid: { left: 50, right: 20, top: 20, bottom: 30 },
                      xAxis: { type: 'category' as const, data: dates, axisLabel: { fontSize: 9 } },
                      yAxis: { type: 'value' as const, name: '%', max: 0 },
                      series: [{ type: 'line', data: drawdowns, smooth: true, itemStyle: { color: '#3f8600' },
                        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(63,134,0,0.3)' }, { offset: 1, color: 'rgba(63,134,0,0.05)' }] } },
                      }],
                    }
                    return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 160 }} />
                  })()}
                </Card>
              </Col>
            </Row>
            <Card size="small" title="收益分布" style={{ marginBottom: 16 }}>
              {(() => {
                const returns = detailRows.map(d => d.avg_return_pct)
                const min = Math.floor(Math.min(...returns))
                const max = Math.ceil(Math.max(...returns))
                const step = Math.max(1, Math.ceil((max - min) / 10))
                const bins: { range: string; count: number; mid: number }[] = []
                for (let i = min; i < max; i += step) {
                  const lo = i, hi = Math.min(i + step, max)
                  bins.push({ range: `${lo}~${hi}`, count: returns.filter(r => r >= lo && r < hi).length, mid: (lo + hi) / 2 })
                }
                const option = {
                  tooltip: { trigger: 'axis' as const, formatter: (p: any) => `${p[0].name}%<br/>频次: ${p[0].value}` },
                  grid: { left: 50, right: 20, top: 20, bottom: 30 },
                  xAxis: { type: 'category' as const, data: bins.map(b => b.range), name: '收益(%)', axisLabel: { fontSize: 10 } },
                  yAxis: { type: 'value' as const, name: '频次', minInterval: 1 },
                  series: [{ type: 'bar', data: bins.map(b => ({ value: b.count, itemStyle: { color: b.mid >= 0 ? '#cf1322' : '#3f8600' } })) }],
                }
                return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 140 }} />
              })()}
            </Card>
            <Card size="small" title="月度收益" style={{ marginBottom: 16 }}>
              {(() => {
                const monthMap = new Map<string, { sum: number; count: number }>()
                for (const d of detailRows) {
                  const m = d.date.slice(0, 7)
                  const existing = monthMap.get(m)
                  if (existing) { existing.sum += d.avg_return_pct; existing.count++ }
                  else monthMap.set(m, { sum: d.avg_return_pct, count: 1 })
                }
                const months = Array.from(monthMap.entries()).sort(([a], [b]) => a.localeCompare(b))
                const monthLabels = months.map(([m]) => m.slice(2))
                const avgReturns = months.map(([, v]) => Math.round(v.sum / v.count * 100) / 100)
                const maxAbs = Math.max(1, ...avgReturns.map(Math.abs))
                const option = {
                  tooltip: { trigger: 'axis' as const, formatter: (ps: any) => `${ps[0].name}<br/>平均收益: ${ps[0].value}%` },
                  grid: { left: 50, right: 20, top: 10, bottom: 24 },
                  xAxis: { type: 'category' as const, data: monthLabels, axisLabel: { fontSize: 10 } },
                  yAxis: { type: 'value' as const, name: '%' },
                  series: [{ type: 'bar', data: avgReturns.map(v => ({
                    value: v,
                    itemStyle: { color: v >= 0 ? `rgba(207,19,34,${0.3 + Math.abs(v) / maxAbs * 0.7})` : `rgba(63,134,0,${0.3 + Math.abs(v) / maxAbs * 0.7})` }
                  })) }],
                }
                return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 120 }} />
              })()}
            </Card>
            <Card size="small" title="风险收益分布" style={{ marginBottom: 16 }}>
              {(() => {
                const data = detailRows.map(d => [d.max_drawdown, d.avg_return_pct, d.date.slice(5)])
                const option = {
                  tooltip: { formatter: (p: any) => `${p.data[2]}<br/>回撤: -${(p.data[0] ?? 0).toFixed(2)}%<br/>收益: ${(p.data[1] ?? 0).toFixed(2)}%` },
                  grid: { left: 50, right: 20, top: 20, bottom: 30 },
                  xAxis: { type: 'value' as const, name: '回撤%', inverse: true, axisLabel: { formatter: (v: number) => `-${v}%` } },
                  yAxis: { type: 'value' as const, name: '收益%', axisLabel: { formatter: (v: number) => `${v}%` } },
                  series: [{ type: 'scatter', symbolSize: 8, data,
                    itemStyle: { color: (p: any) => p.data[1] >= 0 ? '#cf1322' : '#3f8600' } }],
                }
                return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 160 }} />
              })()}
            </Card>
            <Card size="small" title="各期明细">
              <Table
                dataSource={detailRows}
                rowKey="date"
                size="small"
                pagination={{ pageSize: 10 }}
                columns={detailColumns}
                scroll={{ y: 400 }}
              />
            </Card>
          </>
        )}
      </Drawer>

      <Drawer
        title="回测对比"
        placement="right"
        width={780}
        open={compareVisible}
        onClose={() => setCompareVisible(false)}
        extra={compareData ? (
          <Space size="small">
            <Button size="small" icon={<PrinterOutlined />} onClick={() => {
              if (!compareData) return
              const cardHtml = compareData.items.map((item, i) => {
                const s = item.summary
                return `<div class="card" style="border-left:3px solid ${COMPARE_COLORS[i % COMPARE_COLORS.length]}"><h3>${COMPARE_LABELS[i]} #${s.id}</h3>
                  <p>区间: ${s.start_date} ~ ${s.end_date}</p><p>参数: TopN=${s.top_n}, 持有=${s.hold_days}天</p>
                  <div class="stat"><div><div class="val ${(s.avg_return_pct ?? 0) > 0 ? 'pos' : 'neg'}">${(s.avg_return_pct ?? 0).toFixed(2)}%</div><div>平均收益</div></div>
                  <div><div class="val">${(s.win_rate ?? 0).toFixed(1)}%</div><div>胜率</div></div>
                  <div><div class="val">${s.total_periods}</div><div>期数</div></div></div></div>`
              }).join('\n')
              const thCells = compareData.items.map((_, i) => `<th>${COMPARE_LABELS[i]}收益</th><th>${COMPARE_LABELS[i]}胜率</th>`).join('')
              const rows = compareTableData.map((r: any) => {
                const cells = r.details.map((d: any) => d ? `<td>${(d.avg_return_pct ?? 0).toFixed(2)}%</td><td>${(d.win_rate ?? 0).toFixed(1)}%</td>` : '<td>-</td><td>-</td>').join('')
                return `<tr><td>${r.date}</td>${cells}</tr>`
              }).join('')
              const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>回测对比报告</title>
              <style>body{font-family:-apple-system,sans-serif;padding:24px;color:#333}h1{font-size:18px}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{border:1px solid #ddd;padding:6px 10px;text-align:center;font-size:13px}th{background:#f5f5f5;font-weight:600}.summary{display:flex;gap:24px;margin:12px 0;flex-wrap:wrap}.card{border:1px solid #ddd;border-radius:6px;padding:12px;flex:1;min-width:200px}.card h3{margin:0 0 8px;font-size:14px}.stat{display:flex;gap:16px}.stat div{text-align:center}.stat .val{font-size:18px;font-weight:700}.pos{color:#cf1322}.neg{color:#3f8600}</style></head>
              <body><h1>回测对比报告 - ${dayjs().format('YYYY-MM-DD HH:mm')}</h1>
              <div class="summary">${cardHtml}</div>
              <h2>逐期对比</h2>
              <table><thead><tr><th>日期</th>${thCells}</tr></thead><tbody>${rows}</tbody></table>
              </body></html>`
              const win = window.open('', '_blank')
              if (win) { win.document.write(html); win.document.close(); win.print() }
            }}>打印报告</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => {
              if (!compareData) return
              const headerParts = compareData.items.map((_, i) => `${COMPARE_LABELS[i]}收益%,${COMPARE_LABELS[i]}胜率%`)
              const header = `日期,${headerParts.join(',')}`
              const rows = compareTableData.map((r: any) => {
                const cells = r.details.map((d: any) => d ? `${(d.avg_return_pct ?? 0).toFixed(2)},${(d.win_rate ?? 0).toFixed(1)}` : ',').join(',')
                return `${r.date},${cells}`
              })
              const summaryLines = compareData.items.map((item, i) =>
                `${COMPARE_LABELS[i]} #${item.summary.id}: 区间=${item.summary.start_date}~${item.summary.end_date}, TopN=${item.summary.top_n}, 持有=${item.summary.hold_days}天, 平均收益=${item.summary.avg_return_pct}%, 胜率=${item.summary.win_rate}%`
              )
              const csv = [...summaryLines, header, ...rows].join('\n')
              const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              const ids = compareData.items.map(item => item.summary.id).join('_')
              a.download = `backtest_compare_${ids}_${dayjs().format('YYYYMMDD')}.csv`
              a.click()
              URL.revokeObjectURL(url)
            }}>导出对比 CSV</Button>
          </Space>
        ) : undefined}
      >
        {compareData && (() => {
          const colSpan = Math.max(4, Math.floor(24 / compareData.items.length))
          return (
            <>
              <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                {compareData.items.map((item, i) => (
                  <Col span={colSpan} key={item.summary.id}>
                    <Card size="small" title={`${COMPARE_LABELS[i]}: #${item.summary.id}`} style={{ borderColor: COMPARE_COLORS[i % COMPARE_COLORS.length] }}>
                      <Descriptions size="small" column={1}>
                        <Descriptions.Item label="区间">{item.summary.start_date} ~ {item.summary.end_date}</Descriptions.Item>
                        <Descriptions.Item label="参数">TopN={item.summary.top_n}, 持有={item.summary.hold_days}天</Descriptions.Item>
                      </Descriptions>
                      <Row gutter={8}>
                        <Col span={8}><Statistic title="平均收益" value={item.summary.avg_return_pct} precision={2} suffix="%" valueStyle={{ color: returnColor(item.summary.avg_return_pct) }} /></Col>
                        <Col span={8}><Statistic title="胜率" value={item.summary.win_rate} precision={1} suffix="%" /></Col>
                        <Col span={8}><Statistic title="期数" value={item.summary.total_periods} /></Col>
                      </Row>
                    </Card>
                  </Col>
                ))}
              </Row>
              {compareData.items.length >= 2 && (() => {
                const base = compareData.items[0].summary
                const baseDetails = compareData.items[0].details
                const baseDD = baseDetails.length > 0 ? baseDetails[baseDetails.length - 1].max_drawdown : 0
                const baseTotalRet = baseDetails.reduce((s, d) => s + d.avg_return_pct, 0)
                const baseCalmar = baseDD > 0 ? baseTotalRet / baseDD : 0
                const baseWins = baseDetails.filter(d => d.avg_return_pct > 0)
                const baseLosses = baseDetails.filter(d => d.avg_return_pct < 0)
                const baseAvgWin = baseWins.length > 0 ? baseWins.reduce((s, d) => s + d.avg_return_pct, 0) / baseWins.length : 0
                const baseAvgLoss = baseLosses.length > 0 ? Math.abs(baseLosses.reduce((s, d) => s + d.avg_return_pct, 0) / baseLosses.length) : 0
                const baseReturns = baseDetails.map(d => d.avg_return_pct)
                const baseMean = baseReturns.length > 0 ? baseReturns.reduce((a, b) => a + b, 0) / baseReturns.length : 0
                const baseStd = baseReturns.length > 1 ? Math.sqrt(baseReturns.reduce((s, r) => s + (r - baseMean) ** 2, 0) / (baseReturns.length - 1)) : 0
                const basePLR = baseAvgLoss > 0 ? baseAvgWin / baseAvgLoss : baseWins.length > 0 ? 99 : 0
                const baseSharpe = baseStd > 0 ? (baseMean - 0.01 / 12) / baseStd : 0
                const diffs = compareData.items.slice(1).map((item, i) => {
                  const s = item.summary
                  const det = item.details
                  const dd = det.length > 0 ? det[det.length - 1].max_drawdown : 0
                  const totalRet = det.reduce((s2, d) => s2 + d.avg_return_pct, 0)
                  const calmar = dd > 0 ? totalRet / dd : 0
                  const wins = det.filter(d => d.avg_return_pct > 0)
                  const losses = det.filter(d => d.avg_return_pct < 0)
                  const avgWin = wins.length > 0 ? wins.reduce((s2, d) => s2 + d.avg_return_pct, 0) / wins.length : 0
                  const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((s2, d) => s2 + d.avg_return_pct, 0) / losses.length) : 0
                  const plr = avgLoss > 0 ? avgWin / avgLoss : wins.length > 0 ? 99 : 0
                  const returns = det.map(d => d.avg_return_pct)
                  const mean = returns.length > 0 ? returns.reduce((a, b) => a + b, 0) / returns.length : 0
                  const std = returns.length > 1 ? Math.sqrt(returns.reduce((s2, r) => s2 + (r - mean) ** 2, 0) / (returns.length - 1)) : 0
                  const sharpe = std > 0 ? (mean - 0.01 / 12) / std : 0
                  return { label: `${COMPARE_LABELS[i + 1]}-A`, avgDiff: s.avg_return_pct - base.avg_return_pct, winDiff: s.win_rate - base.win_rate,
                    ddDiff: dd - baseDD, calmarDiff: calmar - baseCalmar, plrDiff: plr - basePLR, sharpeDiff: sharpe - baseSharpe }
                })
                return (
                  <Row gutter={[12, 8]} style={{ marginBottom: 16 }}>
                    {diffs.map((d, i) => (
                      <Col span={Math.floor(24 / diffs.length)} key={i}>
                        <Card size="small" style={{ borderColor: COMPARE_COLORS[(i + 1) % COMPARE_COLORS.length], borderWidth: 1, borderStyle: 'dashed' }}>
                          <Row gutter={8}>
                            <Col span={4}><Statistic title={`${d.label} 收益差`} value={d.avgDiff} precision={2} suffix="%" valueStyle={{ color: returnColor(d.avgDiff), fontSize: 14 }} /></Col>
                            <Col span={4}><Statistic title={`${d.label} 胜率差`} value={d.winDiff} precision={1} suffix="%" valueStyle={{ color: d.winDiff > 0 ? '#3f8600' : d.winDiff < 0 ? '#cf1322' : undefined, fontSize: 14 }} /></Col>
                            <Col span={4}><Statistic title={`${d.label} 回撤差`} value={d.ddDiff} precision={2} suffix="%" valueStyle={{ color: d.ddDiff < 0 ? '#3f8600' : d.ddDiff > 0 ? '#cf1322' : undefined, fontSize: 14 }} /></Col>
                            <Col span={4}><Statistic title={`${d.label} Calmar差`} value={d.calmarDiff} precision={2} valueStyle={{ color: d.calmarDiff > 0 ? '#3f8600' : d.calmarDiff < 0 ? '#cf1322' : undefined, fontSize: 14 }} /></Col>
                            <Col span={4}><Statistic title={`${d.label} 盈亏比差`} value={d.plrDiff} precision={2} valueStyle={{ color: d.plrDiff > 0 ? '#3f8600' : d.plrDiff < 0 ? '#cf1322' : undefined, fontSize: 14 }} /></Col>
                            <Col span={4}><Statistic title={`${d.label} Sharpe差`} value={d.sharpeDiff} precision={2} valueStyle={{ color: d.sharpeDiff > 0 ? '#3f8600' : d.sharpeDiff < 0 ? '#cf1322' : undefined, fontSize: 14 }} /></Col>
                          </Row>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                )
              })()}
              <Card size="small" title="收益曲线对比" style={{ marginBottom: 16 }}>
                {(() => {
                  const allDates = [...new Set(compareData.items.flatMap(item => item.details.map(d => d.date)))].sort()
                  const dateMaps = compareData.items.map(item => new Map(item.details.map(d => [d.date, d.avg_return_pct])))
                  const cumDataArrays = dateMaps.map(dm => {
                    let cum = 0
                    return allDates.map(d => { cum += dm.get(d) ?? 0; return Math.round(cum * 100) / 100 })
                  })
                  const option = {
                    tooltip: { trigger: 'axis' as const },
                    legend: { data: compareData.items.map((item, i) => `${COMPARE_LABELS[i]} #${item.summary.id}`) },
                    grid: { left: 50, right: 20, top: 30, bottom: 30 },
                    xAxis: { type: 'category' as const, data: allDates.map(d => d.slice(5)) },
                    yAxis: { type: 'value' as const, name: '累计收益%' },
                    series: compareData.items.map((item, i) => ({
                      name: `${COMPARE_LABELS[i]} #${item.summary.id}`, type: 'line', data: cumDataArrays[i], smooth: true,
                      itemStyle: { color: COMPARE_COLORS[i % COMPARE_COLORS.length] },
                    })),
                  }
                  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 250 }} />
                })()}
              </Card>
              <Card size="small" title="回撤曲线对比" style={{ marginBottom: 16 }}>
                {(() => {
                  const allDates = [...new Set(compareData.items.flatMap(item => item.details.map(d => d.date)))].sort()
                  const ddMaps = compareData.items.map(item => new Map(item.details.map(d => [d.date, d.max_drawdown])))
                  const option = {
                    tooltip: { trigger: 'axis' as const, formatter: (ps: any) => {
                      let s = ps[0].axisValue
                      for (const p of ps) s += `<br/>${p.seriesName}: -${(p.value ?? 0).toFixed(2)}%`
                      return s
                    } },
                    legend: { data: compareData.items.map((item, i) => `${COMPARE_LABELS[i]} #${item.summary.id}`) },
                    grid: { left: 50, right: 20, top: 30, bottom: 30 },
                    xAxis: { type: 'category' as const, data: allDates.map(d => d.slice(5)) },
                    yAxis: { type: 'value' as const, name: '回撤%', max: 0 },
                    series: compareData.items.map((item, i) => ({
                      name: `${COMPARE_LABELS[i]} #${item.summary.id}`, type: 'line', smooth: true,
                      data: allDates.map(d => -(ddMaps[i].get(d) ?? 0)),
                      itemStyle: { color: COMPARE_COLORS[i % COMPARE_COLORS.length] },
                      areaStyle: { color: COMPARE_COLORS[i % COMPARE_COLORS.length], opacity: 0.08 },
                    })),
                  }
                  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 200 }} />
                })()}
              </Card>
              {compareData.items.length >= 2 && (
                <Card size="small" title="收益差值 (以 A 为基准)" style={{ marginBottom: 16 }}>
                  {(() => {
                    const allDates = [...new Set(compareData.items.flatMap(item => item.details.map(d => d.date)))].sort()
                    const dateMaps = compareData.items.map(item => new Map(item.details.map(d => [d.date, d.avg_return_pct])))
                    const baseCum: number[] = []
                    let bc = 0
                    for (const d of allDates) { bc += dateMaps[0].get(d) ?? 0; baseCum.push(Math.round(bc * 100) / 100) }
                    const diffSeries = compareData.items.slice(1).map((_, idx) => {
                      let cum = 0
                      const data = allDates.map((d, di) => {
                        cum += (dateMaps[idx + 1].get(d) ?? 0) - (dateMaps[0].get(d) ?? 0)
                        return Math.round(cum * 100) / 100
                      })
                      return {
                        name: `${COMPARE_LABELS[idx + 1]}-A`, type: 'line', data, smooth: true,
                        itemStyle: { color: COMPARE_COLORS[(idx + 1) % COMPARE_COLORS.length] },
                        areaStyle: { color: COMPARE_COLORS[(idx + 1) % COMPARE_COLORS.length], opacity: 0.1 },
                      }
                    })
                    const option = {
                      tooltip: { trigger: 'axis' as const },
                      legend: { data: compareData.items.slice(1).map((_, i) => `${COMPARE_LABELS[i + 1]}-A`) },
                      grid: { left: 50, right: 20, top: 30, bottom: 30 },
                      xAxis: { type: 'category' as const, data: allDates.map(d => d.slice(5)) },
                      yAxis: { type: 'value' as const, name: '累计差值%' },
                      series: diffSeries,
                    }
                    return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 200 }} />
                  })()}
                </Card>
              )}
              {compareData.items.length >= 2 && (() => {
                const allDates = [...new Set(compareData.items.flatMap(item => item.details.map(d => d.date)))].sort()
                const returns = compareData.items.map(item => {
                  const dm = new Map(item.details.map(d => [d.date, d.avg_return_pct]))
                  return allDates.map(d => dm.get(d) ?? 0)
                })
                const corr = (x: number[], y: number[]) => {
                  const n = x.length
                  const mx = x.reduce((a, b) => a + b, 0) / n
                  const my = y.reduce((a, b) => a + b, 0) / n
                  let num = 0, dx = 0, dy = 0
                  for (let i = 0; i < n; i++) { num += (x[i] - mx) * (y[i] - my); dx += (x[i] - mx) ** 2; dy += (y[i] - my) ** 2 }
                  return dx > 0 && dy > 0 ? num / Math.sqrt(dx * dy) : 0
                }
                const n = compareData.items.length
                const labels = compareData.items.map((_, i) => `${COMPARE_LABELS[i]} #${compareData.items[i].summary.id}`)
                const data: [number, number, number][] = []
                for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) data.push([i, j, Math.round(corr(returns[i], returns[j]) * 100) / 100])
                return (
                  <Card size="small" title="收益相关性矩阵" style={{ marginBottom: 16 }}>
                    <ReactEChartsCore echarts={echarts} option={{
                      tooltip: { formatter: (p: any) => `${labels[p.data[0]]} vs ${labels[p.data[1]]}<br/>相关系数: ${(p.data[2] ?? 0).toFixed(2)}` },
                      grid: { left: 80, right: 30, top: 10, bottom: 40 },
                      xAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 10 } },
                      yAxis: { type: 'category' as const, data: labels, axisLabel: { fontSize: 10 } },
                      visualMap: { min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: ['#3f8600', '#f0f0f0', '#cf1322'] }, textStyle: { fontSize: 10 } },
                      series: [{ type: 'heatmap', data, label: { show: true, formatter: (p: any) => (p.data[2] ?? 0).toFixed(2), fontSize: 10 } }],
                    }} style={{ height: 180 }} />
                  </Card>
                )
              })()}
              <Card size="small" title="收益分布箱线图" style={{ marginBottom: 16 }}>
                {(() => {
                  const boxplotData = compareData.items.map(item => {
                    const returns = item.details.map(d => d.avg_return_pct).sort((a, b) => a - b)
                    if (returns.length === 0) return null
                    const q1Idx = Math.floor(returns.length * 0.25)
                    const q2Idx = Math.floor(returns.length * 0.5)
                    const q3Idx = Math.floor(returns.length * 0.75)
                    const q1 = returns[q1Idx]
                    const q2 = returns[q2Idx]
                    const q3 = returns[q3Idx]
                    const iqr = q3 - q1
                    const whiskerLow = Math.min(returns[0], q1 - 1.5 * iqr)
                    const whiskerHigh = Math.max(returns[returns.length - 1], q3 + 1.5 * iqr)
                    const outliers = returns.filter(r => r < whiskerLow || r > whiskerHigh)
                    return { label: `${COMPARE_LABELS[compareData.items.indexOf(item)]}`, boxplot: [whiskerLow, q1, q2, q3, whiskerHigh], outliers, color: COMPARE_COLORS[compareData.items.indexOf(item) % COMPARE_COLORS.length] }
                  }).filter(Boolean) as { label: string; boxplot: number[]; outliers: number[]; color: string }[]
                  const option = {
                    tooltip: { trigger: 'item' as const, formatter: (p: any) => {
                      if (p.seriesType === 'boxplot') {
                        const d = p.data
                        return `${p.name}<br/>最大: ${d[5]?.toFixed(2)}%<br/>Q3: ${d[4]?.toFixed(2)}%<br/>中位数: ${d[3]?.toFixed(2)}%<br/>Q1: ${d[2]?.toFixed(2)}%<br/>最小: ${d[1]?.toFixed(2)}%`
                      }
                      return `${p.name}: ${p.data[1]?.toFixed(2)}%`
                    }},
                    grid: { left: 60, right: 20, top: 20, bottom: 30 },
                    xAxis: { type: 'category' as const, data: boxplotData.map(b => b.label) },
                    yAxis: { type: 'value' as const, name: '收益%' },
                    series: [
                      {
                        type: 'boxplot', data: boxplotData.map(b => b.boxplot),
                        itemStyle: { color: '#fff', borderColor: '#333', borderWidth: 1 },
                      },
                      {
                        type: 'scatter', data: boxplotData.flatMap((b, i) => b.outliers.map(o => [i, o])),
                        symbolSize: 6, itemStyle: { color: '#ff4d4f' },
                      },
                    ],
                  }
                  return <ReactEChartsCore echarts={echarts} option={option} style={{ height: 200 }} />
                })()}
              </Card>
              <Card size="small" title="逐期对比">
                <Table
                  dataSource={compareTableData}
                  rowKey="date"
                  size="small"
                  pagination={{ pageSize: 15 }}
                  columns={compareColumns}
                  scroll={{ y: 400, x: compareData.items.length * 160 + 90 }}
                />
              </Card>
            </>
          )
        })()}
      </Drawer>
    </div>
  )
})
