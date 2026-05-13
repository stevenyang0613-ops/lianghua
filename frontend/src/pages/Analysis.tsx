import { useState, useEffect, useCallback } from 'react'
import { Card, Table, Tabs, Tag, Row, Col, Statistic, Typography, Spin, Empty, message, Space, Progress } from 'antd'
import { FundProjectionScreenOutlined, AlertOutlined, RiseOutlined, FallOutlined, LinkOutlined, OrderedListOutlined } from '@ant-design/icons'
import { fetchForcedRedemption, fetchDualLowRanking, fetchPulseScan, fetchRevisionProbability, fetchStockCorrelation } from '../services/api'
import type { ForcedRedemptionItem, DualLowItem, PulseItem, RevisionItem, StockCorrelationItem } from '../services/api'

const { Title, Text } = Typography

const riskColor: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue', watch: 'default', none: 'default' }
const riskLabel: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', watch: '关注', none: '安全' }
const severityColor: Record<string, string> = { high: 'red', medium: 'orange' }
const severityLabel: Record<string, string> = { high: '严重', medium: '一般' }

function ForcedRedemptionTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_risk_count: number; items: ForcedRedemptionItem[] } | null>(null)

  useEffect(() => {
    fetchForcedRedemption().then(setData).catch(e => message.error('加载强赎数据失败: ' + e.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    { title: '正股价', dataIndex: 'stock_price', width: 80, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '转股价', dataIndex: 'conversion_price', width: 80, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '占比', dataIndex: 'ratio', width: 80, render: (v: number) => `${v.toFixed(1)}%` },
    { title: '转股价值', dataIndex: 'conversion_value', width: 90, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, render: (v: number) => <Text style={{ color: v < 0 ? '#cf1322' : '#389e0d' }}>{v.toFixed(2)}%</Text> },
    { title: '触发天数', dataIndex: 'trigger_days', width: 80, render: (v: number | null) => v !== null ? `${v}天` : '-' },
    { title: '已计天数', dataIndex: 'forced_call_days', width: 80 },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      width: 80,
      render: (v: string) => <Tag color={riskColor[v]}>{riskLabel[v] || v}</Tag>,
    },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 80, render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="高风险" value={data.high_risk_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Table dataSource={data.items} rowKey="code" columns={columns} size="small" pagination={{ pageSize: 20 }} scroll={{ x: 950 }} />
    </div>
  )
}

function DualLowRankingTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; items: DualLowItem[] } | null>(null)

  useEffect(() => {
    fetchDualLowRanking().then(setData).catch(e => message.error('加载双低排名失败: ' + e.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '排名', dataIndex: 'rank', width: 60 },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => <Text strong>{v.toFixed(2)}</Text> },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 80, render: (v: number) => `${v.toFixed(2)}%` },
    { title: '双低值', dataIndex: 'dual_low', width: 80, render: (v: number) => <Text strong style={{ color: v < 130 ? '#389e0d' : v > 180 ? '#faad14' : undefined }}>{v.toFixed(2)}</Text> },
    { title: '到期税后收益', dataIndex: 'ytm', width: 100, render: (v: number) => v ? `${v.toFixed(2)}%` : '-' },
    { title: '成交量', dataIndex: 'volume', width: 90, render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 70, render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
    { title: '转股价值', dataIndex: 'conversion_value', width: 80, render: (v: number) => v?.toFixed(2) ?? '-' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
      </Row>
      <Table dataSource={data.items} rowKey="rank" columns={columns} size="small" pagination={{ pageSize: 30 }} scroll={{ x: 850 }} />
    </div>
  )
}

function PulseScanTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_severity_count: number; items: PulseItem[] } | null>(null)

  useEffect(() => {
    fetchPulseScan().then(setData).catch(e => message.error('加载脉冲扫描失败: ' + e.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    { title: '脉冲类型', dataIndex: 'pulse_type', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    {
      title: '涨跌幅',
      dataIndex: 'change_pct',
      width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>
          {v >= 0 ? <RiseOutlined /> : <FallOutlined />} {Math.abs(v).toFixed(2)}%
        </span>
      ),
    },
    { title: '价格', dataIndex: 'price', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '成交量', dataIndex: 'volume', width: 90, render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, render: (v: number) => v ? `${v.toFixed(2)}%` : '-' },
    { title: '双低值', dataIndex: 'dual_low', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
    {
      title: '严重程度',
      dataIndex: 'severity',
      width: 70,
      render: (v: string) => <Tag color={severityColor[v]}>{severityLabel[v]}</Tag>,
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="告警总数" value={data.total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="严重" value={data.high_severity_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Table dataSource={data.items} rowKey={(_, i) => String(i)} columns={columns} size="small" pagination={{ pageSize: 20 }} scroll={{ x: 800 }} />
    </div>
  )
}

function RevisionProbabilityTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; high_probability_count: number; items: RevisionItem[] } | null>(null)

  useEffect(() => {
    fetchRevisionProbability().then(setData).catch(e => message.error('加载下修概率失败: ' + e.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    { title: '正股价', dataIndex: 'stock_price', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '转股价', dataIndex: 'conversion_price', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '价差', dataIndex: 'price_distance', width: 60, render: (v: number) => `${v.toFixed(1)}%` },
    {
      title: '概率',
      dataIndex: 'probability',
      width: 120,
      render: (v: number, record: RevisionItem) => (
        <Space>
          <Progress percent={v} size="small" style={{ width: 80 }} strokeColor={v >= 60 ? '#cf1322' : v >= 30 ? '#faad14' : '#52c41a'} />
          <Tag color={riskColor[record.level]}>{riskLabel[record.level]}</Tag>
        </Space>
      ),
    },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, render: (v: number) => `${v.toFixed(2)}%` },
    { title: '剩余年限', dataIndex: 'remaining_years', width: 70, render: (v: number) => v != null ? v.toFixed(1) + '年' : '-' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="高概率下修" value={data.high_probability_count} valueStyle={{ color: '#cf1322' }} /></Card></Col>
      </Row>
      <Table dataSource={data.items} rowKey="code" columns={columns} size="small" pagination={{ pageSize: 20 }} scroll={{ x: 700 }} />
    </div>
  )
}

function StockCorrelationTab() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ total: number; items: StockCorrelationItem[] } | null>(null)

  useEffect(() => {
    fetchStockCorrelation().then(setData).catch(e => message.error('加载正股关联失败: ' + e.message)).finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
  if (!data) return <Empty description="暂无数据" />

  const columns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    {
      title: '转债涨跌',
      dataIndex: 'bond_change',
      width: 80,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>{v?.toFixed(2)}%</span>,
    },
    {
      title: '正股涨跌',
      dataIndex: 'stock_change',
      width: 80,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>{v?.toFixed(2)}%</span>,
    },
    {
      title: '弹性系数',
      dataIndex: 'elasticity',
      width: 80,
      render: (v: number) => <Text strong>{v?.toFixed(4) ?? '-'}</Text>,
    },
    { title: '溢价率', dataIndex: 'premium_ratio', width: 70, render: (v: number) => `${v.toFixed(2)}%` },
    { title: '转股价值', dataIndex: 'conversion_value', width: 80, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '价格', dataIndex: 'price', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
    { title: '双低值', dataIndex: 'dual_low', width: 70, render: (v: number) => v?.toFixed(2) ?? '-' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="总计" value={data.total} /></Card></Col>
      </Row>
      <Table dataSource={data.items} rowKey="code" columns={columns} size="small" pagination={{ pageSize: 20 }} scroll={{ x: 750 }} />
    </div>
  )
}

export default function Analysis() {
  return (
    <div style={{ padding: 16 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <FundProjectionScreenOutlined /> 分析工具
      </Title>

      <Card size="small">
        <Tabs
          defaultActiveKey="forced-redemption"
          items={[
            {
              key: 'forced-redemption',
              label: <span><AlertOutlined /> 强赎日历</span>,
              children: <ForcedRedemptionTab />,
            },
            {
              key: 'dual-low',
              label: <span><OrderedListOutlined /> 双低排名</span>,
              children: <DualLowRankingTab />,
            },
            {
              key: 'pulse',
              label: <span><RiseOutlined /> 脉冲扫描</span>,
              children: <PulseScanTab />,
            },
            {
              key: 'revision',
              label: <span><FallOutlined /> 下修概率</span>,
              children: <RevisionProbabilityTab />,
            },
            {
              key: 'correlation',
              label: <span><LinkOutlined /> 正股关联</span>,
              children: <StockCorrelationTab />,
            },
          ]}
        />
      </Card>
    </div>
  )
}
