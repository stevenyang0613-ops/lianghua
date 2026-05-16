import { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, Table, Tag, Button, Select, Space, Spin, Alert, Typography, Statistic, Row, Col, message, Tabs, Tooltip, Switch, Skeleton } from 'antd'
import { ThunderboltOutlined, CheckCircleOutlined, DownloadOutlined, HistoryOutlined, BarChartOutlined, WifiOutlined, CloudDownloadOutlined, DeleteOutlined } from '@ant-design/icons'
import { useSignalStore } from '../stores/useSignalStore'
import { setAutoExecuteConfig, cleanupSignalHistory, getSignalExportCsvUrl } from '../services/api'
import type { TradeSignal } from '../services/api'

const { Title, Text } = Typography

const actionColors: Record<string, string> = { buy: 'green', sell: 'red' }

const confidenceColor = (v: number) => {
  if (v >= 0.7) return 'green'
  if (v >= 0.4) return 'orange'
  return 'red'
}

export default function Signals() {
  const signals = useSignalStore((s) => s.signals)
  const activeStrategies = useSignalStore((s) => s.activeStrategies)
  const availableStrategies = useSignalStore((s) => s.availableStrategies)
  const history = useSignalStore((s) => s.history)
  const stats = useSignalStore((s) => s.stats)
  const total = useSignalStore((s) => s.total)
  const loading = useSignalStore((s) => s.loading)
  const error = useSignalStore((s) => s.error)
  const wsConnected = useSignalStore((s) => s.wsConnected)
  const loadSignals = useSignalStore((s) => s.loadSignals)
  const loadAvailableStrategies = useSignalStore((s) => s.loadAvailableStrategies)
  const loadHistory = useSignalStore((s) => s.loadHistory)
  const loadStats = useSignalStore((s) => s.loadStats)
  const setStrategies = useSignalStore((s) => s.setStrategies)
  const execute = useSignalStore((s) => s.execute)
  const batchExecute = useSignalStore((s) => s.batchExecute)
  const connectWs = useSignalStore((s) => s.connectWs)
  const disconnectWs = useSignalStore((s) => s.disconnectWs)
  const [tab, setTab] = useState('current')
  const [autoExecEnabled, setAutoExecEnabled] = useState(() => localStorage.getItem('signal_auto_execute') === 'true')
  const [autoExecThreshold] = useState(() => Number(localStorage.getItem('signal_auto_execute_threshold') || '0.85'))

  useEffect(() => {
    loadSignals()
    loadAvailableStrategies()
    loadHistory()
    loadStats()
    const disconnect = connectWs()
    return () => {
      disconnect()
      disconnectWs()
    }
  }, [])

  const handleExecute = useCallback(async (code: string) => {
    try {
      await execute(code)
      message.success(`信号 ${code} 已执行`)
    } catch (e) {
      message.error(`执行失败: ${e}`)
    }
  }, [execute])

  const handleBatchExecute = async () => {
    try {
      const count = await batchExecute()
      message.success(`批量执行完成: ${count} 个信号`)
    } catch (e) {
      message.error(`批量执行失败: ${e}`)
    }
  }

  const handleAutoExecToggle = async (enabled: boolean) => {
    setAutoExecEnabled(enabled)
    localStorage.setItem('signal_auto_execute', String(enabled))
    try {
      await setAutoExecuteConfig(enabled ? autoExecThreshold : 0)
      message.success(enabled ? '自动执行已开启' : '自动执行已关闭')
    } catch (e) {
      message.error(`设置失败: ${e}`)
    }
  }

  const handleCleanup = async () => {
    try {
      await cleanupSignalHistory(30)
      message.success('历史信号已清理')
      loadStats()
      loadHistory()
    } catch (e) {
      message.error(`清理失败: ${e}`)
    }
  }

  if (loading && signals.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
            <Col span={3} key={i}><Card size="small"><Skeleton active title={false} paragraph={{ rows: 2, width: ['60%', '40%'] }} /></Card></Col>
          ))}
        </Row>
        <Card>
          <Skeleton paragraph={{ rows: 8 }} active />
        </Card>
      </div>
    )
  }

  const currentColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 140 },
    { title: '策略', dataIndex: 'strategy', key: 'strategy', width: 100, render: (v: string) => <Tag>{v}</Tag> },
    { title: '方向', dataIndex: 'action', key: 'action', width: 70, render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 100, render: (v: number) => v.toFixed(3) },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100, render: (v: number) => <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag> },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 180, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, record: TradeSignal) => (
        <Button type="primary" size="small" icon={<ThunderboltOutlined />} onClick={() => handleExecute(record.code)}>执行</Button>
      ),
    },
  ], [handleExecute])

  const historyColumns = useMemo(() => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 130 },
    { title: '策略', dataIndex: 'strategy', key: 'strategy', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    { title: '方向', dataIndex: 'action', key: 'action', width: 60, render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, render: (v: number) => v.toFixed(3) },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 80, render: (v: number) => <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag> },
    { title: '已执行', dataIndex: 'executed', key: 'executed', width: 80, render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag color="default">否</Tag> },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 170, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
  ], [])

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={3}><Card size="small"><Statistic title="当前信号" value={total} prefix={<ThunderboltOutlined />} valueStyle={{ color: total > 0 ? '#faad14' : undefined }} /></Card></Col>
        <Col span={3}><Card size="small"><Statistic title="活跃策略" value={activeStrategies.length} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={3}><Card size="small"><Statistic title="可用策略" value={availableStrategies.length} prefix={<BarChartOutlined />} valueStyle={{ color: '#1677ff' }} /></Card></Col>
        <Col span={3}><Card size="small"><Statistic title="历史信号" value={stats?.total ?? '-'} prefix={<HistoryOutlined />} /></Card></Col>
        <Col span={3}><Card size="small"><Statistic title="已执行" value={stats?.executed ?? '-'} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={3}><Card size="small"><Statistic title="执行率" value={stats && stats.total > 0 ? `${((stats.executed / stats.total) * 100).toFixed(1)}%` : '-'} prefix={<BarChartOutlined />} /></Card></Col>
        <Col span={3}>
          <Card size="small">
            <Statistic title="自动执行" value={autoExecEnabled ? '开启' : '关闭'} prefix={
              <Switch size="small" checked={autoExecEnabled} onChange={handleAutoExecToggle} />
            } valueStyle={{ color: autoExecEnabled ? '#52c41a' : '#8c8c8c', fontSize: 14 }} />
          </Card>
        </Col>
        <Col span={3}>
          <Card size="small">
            <Statistic title="WS 状态" value={wsConnected ? '已连接' : '未连接'} prefix={<WifiOutlined />} valueStyle={{ color: wsConnected ? '#52c41a' : '#ff4d4f', fontSize: 14 }} />
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>交易信号</Title>
            <Button size="small" onClick={loadSignals} loading={loading}>刷新</Button>
          </Space>
        }
        extra={
          <Space>
            <Tooltip title="导出 CSV">
              <Button icon={<CloudDownloadOutlined />} onClick={() => window.open(getSignalExportCsvUrl(), '_blank')}>导出</Button>
            </Tooltip>
            <Tooltip title="清理30天前的历史">
              <Button icon={<DeleteOutlined />} onClick={handleCleanup}>清理</Button>
            </Tooltip>
            <Button type="primary" icon={<DownloadOutlined />} onClick={handleBatchExecute} loading={loading} disabled={total === 0}>
              一键批量执行
            </Button>
            <Text>活跃策略:</Text>
            <Select
              mode="multiple"
              style={{ minWidth: 200 }}
              value={activeStrategies}
              onChange={setStrategies}
              options={availableStrategies.map((s) => ({ label: s.name, value: s.id }))}
              loading={loading}
            />
          </Space>
        }
      >
        {error && <Alert message={error} type="error" style={{ marginBottom: 12 }} closable />}
        <Tabs activeKey={tab} onChange={setTab} items={[
          {
            key: 'current', label: '当前信号',
            children: (
              <Spin spinning={loading}>
                <Table dataSource={signals} columns={currentColumns} rowKey={(r) => `${r.code}-${r.strategy}`} size="small" scroll={{ y: 400 }} virtual pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }} />
              </Spin>
            ),
          },
          {
            key: 'history', label: '历史记录',
            children: (
              <Table dataSource={history} columns={historyColumns} rowKey="id" size="small" scroll={{ y: 400 }} virtual pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }} />
            ),
          },
        ]} />
      </Card>
    </div>
  )
}