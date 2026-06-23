import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Table, Tag, Button, Select, Space, Spin, Alert, Typography, Statistic, Row, Col, message, Tabs, Badge, Empty, Skeleton } from 'antd'
import { ThunderboltOutlined, CheckCircleOutlined, DownloadOutlined, HistoryOutlined, BarChartOutlined, WifiOutlined, DisconnectOutlined, ReloadOutlined } from '@ant-design/icons'
import { useSignalStore } from '../stores/useSignalStore'
import { useAppStore } from '../stores/useAppStore'
import { signalsWs, refreshWsToken } from '../utils/wsInstances'
import type { TradeSignal, SignalHistoryItem } from '../services/api'
import { fmt } from '../utils/format'

const { Title, Text } = Typography

const actionColors: Record<string, string> = {
  buy: 'green',
  sell: 'red',
}

const confidenceColor = (v: number) => {
  if (v >= 0.7) return 'green'
  if (v >= 0.4) return 'orange'
  return 'red'
}

export default function Signals() {
  const [signalsPage, setSignalsPage] = useState(1)
  const [signalsPageSize, setSignalsPageSize] = useState(20)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyPageSize, setHistoryPageSize] = useState(20)
  const signals = useSignalStore((s) => s.signals)
  const activeStrategies = useSignalStore((s) => s.activeStrategies)
  const availableStrategies = useSignalStore((s) => s.availableStrategies)
  const history = useSignalStore((s) => s.history)
  const stats = useSignalStore((s) => s.stats)
  const total = useSignalStore((s) => s.total)
  const loading = useSignalStore((s) => s.loading)
  const error = useSignalStore((s) => s.error)
  const wsConnected = useAppStore((s) => s.signalWsConnected)
  const loadSignals = useSignalStore((s) => s.loadSignals)
  const loadAvailableStrategies = useSignalStore((s) => s.loadAvailableStrategies)
  const loadHistory = useSignalStore((s) => s.loadHistory)
  const loadStats = useSignalStore((s) => s.loadStats)
  const setStrategies = useSignalStore((s) => s.setStrategies)
  const execute = useSignalStore((s) => s.execute)
  const batchExecute = useSignalStore((s) => s.batchExecute)
  const subscribeWs = useSignalStore((s) => s.subscribeWs)

  const [tab, setTab] = useState('current')
  const [wsLastError, setWsLastError] = useState<string>('')
  const loadingRef = useRef(false)
  // Track initial load to show skeleton instead of empty state
  const [initialLoading, setInitialLoading] = useState(true)

  // Sync loadingRef for interval guard
  useEffect(() => { loadingRef.current = loading }, [loading])

  const handleWsReconnect = useCallback(() => {
    // 只重连 signals WS，避免 refreshWsToken 同时重置 market 连接
    signalsWs.reset()
    signalsWs.connect()
  }, [])

  useEffect(() => {
    loadSignals().then(() => setInitialLoading(false)).catch(() => setInitialLoading(false))
    loadAvailableStrategies().catch(() => {})
    loadHistory().catch(() => {})
    loadStats().catch(() => {})
    const unsub = subscribeWs()

    // Single WS state listener for error display only (wsConnected tracked by useAppStore)
    const unsubState = signalsWs.onStateChange((state) => {
      if (state === 'disconnected' || state === 'reconnecting') {
        const err = signalsWs.getLastError()
        setWsLastError(err ? `${err.reason || '连接断开'} (${err.code})` : '')
      } else if (state === 'connected') {
        setWsLastError('')
      }
    })

    return () => { unsub(); unsubState() }
  }, [])

  // 60s fallback refresh (not 30s — WS provides real-time updates, this is just a safety net)
  useEffect(() => {
    const timer = setInterval(() => {
      if (!loadingRef.current) loadSignals().catch(() => {})
    }, 60000)
    return () => clearInterval(timer)
  }, [])

  const handleExecute = async (code: string) => {
    try {
      await execute(code)
      message.success(`信号 ${code} 已执行`)
    } catch (e) {
      message.error(`执行失败: ${e}`)
    }
  }

  const handleBatchExecute = async () => {
    try {
      const count = await batchExecute()
      message.success(`批量执行完成: ${count} 个信号`)
    } catch (e) {
      message.error(`批量执行失败: ${e}`)
    }
  }

  const currentColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, sorter: (a: TradeSignal, b: TradeSignal) => String(a.code ?? '').localeCompare(String(b.code ?? '')), render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 140, sorter: (a: TradeSignal, b: TradeSignal) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
    { title: '策略', dataIndex: 'strategy', key: 'strategy', width: 100, sorter: (a: TradeSignal, b: TradeSignal) => String(a.strategy ?? '').localeCompare(String(b.strategy ?? '')), render: (v: string) => <Tag>{v}</Tag> },
    { title: '方向', dataIndex: 'action', key: 'action', width: 70, sorter: (a: TradeSignal, b: TradeSignal) => String(a.action ?? '').localeCompare(String(b.action ?? '')), render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 100, sorter: (a: TradeSignal, b: TradeSignal) => (a.price ?? 0) - (b.price ?? 0), render: (v: number) => { const s = fmt(v, 3); return <Text>{s === '-' ? '--' : s}</Text> } },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100, sorter: (a: TradeSignal, b: TradeSignal) => (a.confidence ?? 0) - (b.confidence ?? 0), render: (v: number) => <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag> },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true, sorter: (a: TradeSignal, b: TradeSignal) => String(a.reason ?? '').localeCompare(String(b.reason ?? '')) },
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 180, sorter: (a: TradeSignal, b: TradeSignal) => new Date(a.ts ?? 0).getTime() - new Date(b.ts ?? 0).getTime(), render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '--' },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, record: TradeSignal) => (
        <Button type="primary" size="small" icon={<ThunderboltOutlined />} onClick={() => handleExecute(record.code)}>执行</Button>
      ),
    },
  ]

  const historyColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => String(a.code ?? '').localeCompare(String(b.code ?? '')), render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 130, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
    { title: '策略', dataIndex: 'strategy', key: 'strategy', width: 90, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => String(a.strategy ?? '').localeCompare(String(b.strategy ?? '')), render: (v: string) => <Tag>{v}</Tag> },
    { title: '方向', dataIndex: 'action', key: 'action', width: 60, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => String(a.action ?? '').localeCompare(String(b.action ?? '')), render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => (a.price ?? 0) - (b.price ?? 0), render: (v: number) => { const s = fmt(v, 3); return <Text>{s === '-' ? '--' : s}</Text> } },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 80, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => (a.confidence ?? 0) - (b.confidence ?? 0), render: (v: number) => <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag> },
    { title: '已执行', dataIndex: 'executed', key: 'executed', width: 80, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => Number(a.executed ?? 0) - Number(b.executed ?? 0), render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag color="default">否</Tag> },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => String(a.reason ?? '').localeCompare(String(b.reason ?? '')) },
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 170, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => new Date(a.ts ?? 0).getTime() - new Date(b.ts ?? 0).getTime(), render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '--' },
  ]

  // Initial loading skeleton
  if (initialLoading) {
    return (
      <div style={{ padding: 24 }}>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Col span={4} key={i}>
              <Card size="small"><Skeleton.Input active style={{ width: '100%' }} /></Card>
            </Col>
          ))}
        </Row>
        <Card>
          <Skeleton paragraph={{ rows: 8 }} active />
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card size="small"><Statistic title="当前信号" value={total} prefix={<ThunderboltOutlined />} valueStyle={{ color: total > 0 ? '#faad14' : undefined }} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="活跃策略" value={activeStrategies.length} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="可用策略" value={availableStrategies.length} prefix={<BarChartOutlined />} valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="历史信号" value={stats?.total ?? '-'} prefix={<HistoryOutlined />} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="已执行" value={stats?.executed ?? '-'} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="WS 状态"
              value={wsConnected ? '已连接' : '未连接'}
              prefix={<WifiOutlined />}
              valueStyle={{ color: wsConnected ? '#52c41a' : '#ff4d4f', fontSize: 14 }}
            />
            {!wsConnected && (
              <div style={{ marginTop: 4 }}>
                <Button type="link" size="small" icon={<ReloadOutlined />} onClick={handleWsReconnect} style={{ padding: 0, fontSize: 12 }}>
                  重连
                </Button>
                {wsLastError && <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{wsLastError}</div>}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>交易信号</Title>
            <Button size="small" onClick={() => loadSignals().catch(() => {})} loading={loading}>刷新</Button>
          </Space>
        }
        extra={
          <Space>
            <Button type="primary" icon={<DownloadOutlined />} onClick={handleBatchExecute} loading={loading} disabled={total === 0}>
              一键批量执行
            </Button>
            <Text>活跃策略:</Text>
            <Select
              mode="multiple"
              style={{ minWidth: 200 }}
              value={activeStrategies}
              onChange={(v: string[]) => setStrategies(v).catch(() => {})}
              options={availableStrategies.map((s) => ({ label: s.name, value: s.id }))}
              loading={loading}
            />
          </Space>
        }
      >
        {error && <Alert message={error} type="error" style={{ marginBottom: 12 }} closable />}
        <Tabs activeKey={tab} onChange={setTab} items={[
          {
            key: 'current',
            label: '当前信号',
            children: (
              <Spin spinning={loading}>
                {signals.length === 0 && !loading ? (
                  <Empty
                    description={
                      <span>
                        {wsConnected ? '暂无信号' : '信号服务未连接'}
                        {!wsConnected && (
                          <Button type="link" size="small" onClick={handleWsReconnect}>点击重连</Button>
                        )}
                      </span>
                    }
                    style={{ marginTop: 40 }}
                  />
                ) : (
                <Table
                  dataSource={signals}
                  columns={currentColumns}
                  rowKey={(r) => `${r.code}-${r.strategy}`}
                  size="small"
                  pagination={{ current: signalsPage, pageSize: signalsPageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setSignalsPage(p); setSignalsPageSize(ps) } }}
                />
                )}
              </Spin>
            ),
          },
          {
            key: 'history',
            label: '历史记录',
            children: (
              <Table
                dataSource={history}
                columns={historyColumns}
                rowKey="id"
                size="small"
                pagination={{ current: historyPage, pageSize: historyPageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setHistoryPage(p); setHistoryPageSize(ps) } }}
              />
            ),
          },
        ]} />
      </Card>
    </div>
  )
}
