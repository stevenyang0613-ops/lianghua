import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Select, Space, Spin, Alert, Typography, Statistic, Row, Col, message, Tabs } from 'antd'
import { ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined, DownloadOutlined, HistoryOutlined, BarChartOutlined, WifiOutlined } from '@ant-design/icons'
import { useSignalStore } from '../stores/useSignalStore'
import type { TradeSignal } from '../services/api'

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
  const {
    signals, activeStrategies, availableStrategies, history, stats, total, loading, error, wsConnected,
    loadSignals, loadAvailableStrategies, loadHistory, loadStats, setStrategies, execute, batchExecute, connectWs,
  } = useSignalStore()
  const [tab, setTab] = useState('current')

  useEffect(() => {
    loadSignals()
    loadAvailableStrategies()
    loadHistory()
    loadStats()
    const disconnect = connectWs()
    return disconnect
  }, [])

  useEffect(() => {
    const timer = setInterval(loadSignals, 30000)
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
  ]

  const historyColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 100, render: (v: string) => <Text code>{v}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name', width: 130 },
    { title: '策略', dataIndex: 'strategy', key: 'strategy', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    { title: '方向', dataIndex: 'action', key: 'action', width: 60, render: (v: string) => <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 90, render: (v: number) => v.toFixed(3) },
    { title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 80, render: (v: number) => <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag> },
    { title: '已执行', dataIndex: 'executed', key: 'executed', width: 80, render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag color="default">否</Tag> },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 170, render: (v: string) => new Date(v).toLocaleString('zh-CN') },
  ]

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
            key: 'current',
            label: '当前信号',
            children: (
              <Spin spinning={loading}>
                <Table
                  dataSource={signals}
                  columns={currentColumns}
                  rowKey={(r) => `${r.code}-${r.strategy}`}
                  size="small"
                  pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
                />
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
                pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
              />
            ),
          },
        ]} />
      </Card>
    </div>
  )
}