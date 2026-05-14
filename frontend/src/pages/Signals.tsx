import { useEffect } from 'react'
import { Card, Table, Tag, Button, Select, Space, Spin, Alert, Typography, Statistic, Row, Col, message } from 'antd'
import { ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined, DeploymentUnitOutlined } from '@ant-design/icons'
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
    signals, activeStrategies, availableStrategies, total, loading, error,
    loadSignals, loadAvailableStrategies, setStrategies, execute,
  } = useSignalStore()

  useEffect(() => {
    loadSignals()
    loadAvailableStrategies()
  }, [])

  // Auto refresh every 30s
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

  const columns = [
    {
      title: '代码', dataIndex: 'code', key: 'code', width: 100,
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: '名称', dataIndex: 'name', key: 'name', width: 140,
    },
    {
      title: '策略', dataIndex: 'strategy', key: 'strategy', width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '方向', dataIndex: 'action', key: 'action', width: 70,
      render: (v: string) => (
        <Tag color={actionColors[v] || 'default'}>{v === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    {
      title: '价格', dataIndex: 'price', key: 'price', width: 100,
      render: (v: number) => v.toFixed(3),
    },
    {
      title: '置信度', dataIndex: 'confidence', key: 'confidence', width: 100,
      render: (v: number) => (
        <Tag color={confidenceColor(v)}>{v >= 0.01 ? `${(v * 100).toFixed(0)}%` : '--'}</Tag>
      ),
    },
    {
      title: '原因', dataIndex: 'reason', key: 'reason',
      ellipsis: true,
    },
    {
      title: '时间', dataIndex: 'ts', key: 'ts', width: 180,
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作', key: 'action', width: 100,
      render: (_: unknown, record: TradeSignal) => (
        <Button
          type="primary"
          size="small"
          icon={<ThunderboltOutlined />}
          onClick={() => handleExecute(record.code)}
        >
          执行
        </Button>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="当前信号" value={total} prefix={<ThunderboltOutlined />} valueStyle={{ color: total > 0 ? '#faad14' : undefined }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="活跃策略" value={activeStrategies.length} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="可用策略" value={availableStrategies.length} prefix={<DeploymentUnitOutlined />} valueStyle={{ color: '#1677ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="信号状态" value={signals.length > 0 ? '等待执行' : '无信号'} prefix={signals.length > 0 ? <ThunderboltOutlined /> : <CloseCircleOutlined />} valueStyle={{ color: signals.length > 0 ? '#faad14' : '#8c8c8c' }} />
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
        <Spin spinning={loading}>
          <Table
            dataSource={signals}
            columns={columns}
            rowKey={(r) => `${r.code}-${r.strategy}`}
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          />
        </Spin>
      </Card>
    </div>
  )
}