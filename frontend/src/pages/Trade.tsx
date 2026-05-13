import { useState, useEffect, useCallback } from 'react'
import { Card, Form, Select, InputNumber, Button, Row, Col, Statistic, Table, Tabs, Tag, message, Typography, Space, Modal, Empty, Spin, Divider } from 'antd'
import { DollarOutlined, ShoppingCartOutlined, SwapOutlined, BarChartOutlined, ReloadOutlined, DeleteOutlined, LineChartOutlined, HistoryOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import { fetchAccount, fetchPositions, fetchOrders, placeOrder, cancelOrder, resetAccount, fetchFundCurve } from '../services/api'
import { useTradeStore } from '../stores/useTradeStore'
import { useMarketStore } from '../stores/useMarketStore'
import type { Account, Position, TradeOrder, PlaceOrderRequest, FundPoint } from '../services/api'

const { Title, Text } = Typography

const sideOptions = [
  { value: 'buy', label: '买入' },
  { value: 'sell', label: '卖出' },
]

const statusColors: Record<string, string> = {
  filled: 'green',
  pending: 'orange',
  cancelled: 'default',
  rejected: 'red',
}

const statusLabels: Record<string, string> = {
  filled: '已成交',
  pending: '待成交',
  cancelled: '已撤单',
  rejected: '已拒绝',
}

export default function Trade() {
  const { account, positions, orders, fundCurve, setAccount, setPositions, setOrders, setFundCurve, setLoading, loading } = useTradeStore()
  const allBonds = useMarketStore((s) => s.allBonds)

  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [price, setPrice] = useState<number>(0)
  const [volume, setVolume] = useState<number>(10)
  const [refreshing, setRefreshing] = useState(false)
  const [activeTab, setActiveTab] = useState('trade')

  // Load trade data
  const loadData = useCallback(async () => {
    try {
      const [acc, pos, ords, curve] = await Promise.all([
        fetchAccount(),
        fetchPositions(),
        fetchOrders(),
        fetchFundCurve(),
      ])
      setAccount(acc)
      setPositions(pos.positions)
      setOrders(ords.orders)
      setFundCurve(curve.points)
    } catch (e: any) {
      message.error('加载交易数据失败: ' + (e.message || '未知错误'))
    }
  }, [setAccount, setPositions, setOrders, setFundCurve])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Auto-fill price when bond selected
  const handleBondSelect = (code: string) => {
    setSelectedCode(code)
    const bond = allBonds.find((b: { code: string }) => b.code === code)
    if (bond) {
      setPrice(bond.price)
    }
  }

  // Place order
  const handlePlaceOrder = async () => {
    if (!selectedCode) {
      message.warning('请选择可转债')
      return
    }
    if (price <= 0 || volume <= 0) {
      message.warning('请输入有效的价格和数量')
      return
    }

    const bond = allBonds.find((b: { code: string }) => b.code === selectedCode)
    const req: PlaceOrderRequest = {
      code: selectedCode,
      name: bond?.name || '',
      side,
      price,
      volume,
    }

    setLoading(true)
    try {
      const result = await placeOrder(req)
      if (result.status === 'rejected') {
        message.error(`下单被拒绝: ${result.reject_reason}`)
      } else {
        message.success(`${side === 'buy' ? '买入' : '卖出'} ${selectedCode} ${volume} 张成功`)
      }
      await loadData()
    } catch (e: any) {
      message.error('下单失败: ' + (e.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  // Cancel order
  const handleCancelOrder = async (orderId: string) => {
    try {
      await cancelOrder(orderId)
      message.success('撤单成功')
      await loadData()
    } catch (e: any) {
      message.error('撤单失败: ' + (e.message || '未知错误'))
    }
  }

  // Reset account
  const handleReset = () => {
    Modal.confirm({
      title: '确认重置',
      content: '重置将清空所有持仓、订单和资金记录，确定继续？',
      onOk: async () => {
        try {
          await resetAccount()
          message.success('账户已重置')
          await loadData()
        } catch (e: any) {
          message.error('重置失败: ' + (e.message || '未知错误'))
        }
      },
    })
  }

  // Fund curve chart option
  const fundCurveOption = fundCurve.length > 0 ? {
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const p = params[0]
        const point = fundCurve[p.dataIndex]
        if (!point) return ''
        return `
          <div>时间: ${point.ts}</div>
          <div>总资产: ${point.total_asset.toFixed(2)}</div>
          <div>现金: ${point.cash.toFixed(2)}</div>
          <div>市值: ${point.market_value.toFixed(2)}</div>
          <div>总盈亏: ${point.total_profit >= 0 ? '+' : ''}${point.total_profit.toFixed(2)}</div>
        `
      },
    },
    legend: { data: ['总资产', '现金'], top: 0 },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: fundCurve.map((p: FundPoint) => p.ts.slice(5, 16)),
      axisLabel: { fontSize: 10, rotate: 30 },
    },
    yAxis: { type: 'value' as const, name: '金额' },
    series: [
      {
        name: '总资产',
        type: 'line',
        data: fundCurve.map((p: FundPoint) => p.total_asset),
        smooth: true,
        lineStyle: { color: '#1890ff', width: 2 },
        areaStyle: { color: 'rgba(24,144,255,0.1)' },
        showSymbol: false,
      },
      {
        name: '现金',
        type: 'line',
        data: fundCurve.map((p: FundPoint) => p.cash),
        smooth: true,
        lineStyle: { color: '#52c41a', width: 1.5, type: 'dashed' },
        showSymbol: false,
      },
    ],
  } : null

  // Order columns
  const orderColumns = [
    { title: 'ID', dataIndex: 'id', width: 120, ellipsis: true },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    {
      title: '方向',
      dataIndex: 'side',
      width: 60,
      render: (v: string) => (
        <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买' : '卖'}</Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      width: 80,
      render: (v: number) => v.toFixed(2),
    },
    { title: '数量', dataIndex: 'volume', width: 60 },
    { title: '成交', dataIndex: 'filled_volume', width: 60 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: string) => <Tag color={statusColors[v]}>{statusLabels[v] || v}</Tag>,
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, record: TradeOrder) =>
        record.status === 'pending' ? (
          <Button size="small" danger onClick={() => handleCancelOrder(record.id)}>
            撤单
          </Button>
        ) : null,
    },
  ]

  // Position columns
  const positionColumns = [
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
    { title: '持仓', dataIndex: 'volume', width: 60 },
    { title: '可用', dataIndex: 'available_volume', width: 60 },
    {
      title: '成本价',
      dataIndex: 'cost_price',
      width: 80,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '现价',
      dataIndex: 'current_price',
      width: 80,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '市值',
      dataIndex: 'market_value',
      width: 90,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '盈亏',
      dataIndex: 'profit_amount',
      width: 90,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}
        </Text>
      ),
    },
    {
      title: '收益率',
      dataIndex: 'profit_pct',
      width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#cf1322' : '#389e0d' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}%
        </span>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <DollarOutlined /> 交易终端
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => { setRefreshing(true); loadData().finally(() => setRefreshing(false)) }} loading={refreshing}>刷新</Button>
            <Button icon={<DeleteOutlined />} danger onClick={handleReset}>重置账户</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* Left: Order Form + Positions */}
        <Col span={14}>
          <Card size="small" style={{ marginBottom: 12 }}>
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                {
                  key: 'trade',
                  label: <span><SwapOutlined /> 下单</span>,
                  children: (
                    <Form layout="vertical" size="small">
                      <Row gutter={16}>
                        <Col span={12}>
                          <Form.Item label="交易方向">
                            <Select value={side} onChange={(v) => setSide(v)}>
                              <Select.Option value="buy">买入</Select.Option>
                              <Select.Option value="sell">卖出</Select.Option>
                            </Select>
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="可转债">
                            <Select
                              showSearch
                              value={selectedCode || undefined}
                              onChange={handleBondSelect}
                              placeholder="搜索代码/名称"
                              filterOption={(input, option) =>
                                (option?.label as string || '').toLowerCase().includes(input.toLowerCase())
                              }
                              options={allBonds.map((b: any) => ({
                                value: b.code,
                                label: `${b.code} - ${b.name}`,
                              }))}
                            />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Row gutter={16}>
                        <Col span={12}>
                          <Form.Item label="价格">
                            <InputNumber
                              style={{ width: '100%' }}
                              value={price}
                              onChange={(v) => setPrice(v || 0)}
                              min={0}
                              step={0.001}
                              precision={3}
                              placeholder="输入价格"
                            />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="数量 (张)">
                            <InputNumber
                              style={{ width: '100%' }}
                              value={volume}
                              onChange={(v) => setVolume(v || 0)}
                              min={1}
                              step={10}
                              placeholder="输入数量"
                            />
                          </Form.Item>
                        </Col>
                      </Row>
                      {selectedCode && (
                        <Row gutter={16} style={{ marginBottom: 12 }}>
                          <Col span={12}>
                            <Text type="secondary">
                              估算金额: <Text strong>¥{(price * volume).toFixed(2)}</Text>
                            </Text>
                          </Col>
                          <Col span={12}>
                            <Text type="secondary">
                              可用资金: <Text strong>¥{account?.cash.toFixed(2) || '0.00'}</Text>
                            </Text>
                          </Col>
                        </Row>
                      )}
                      <Button
                        type="primary"
                        icon={<ShoppingCartOutlined />}
                        onClick={handlePlaceOrder}
                        loading={loading}
                        block
                        size="large"
                        style={{
                          backgroundColor: side === 'buy' ? '#cf1322' : '#389e0d',
                          borderColor: side === 'buy' ? '#cf1322' : '#389e0d',
                        }}
                      >
                        {side === 'buy' ? '买入' : '卖出'}
                      </Button>
                    </Form>
                  ),
                },
                {
                  key: 'positions',
                  label: <span><BarChartOutlined /> 持仓 ({positions.length})</span>,
                  children: positions.length === 0 ? (
                    <Empty description="暂无持仓" style={{ margin: '40px 0' }} />
                  ) : (
                    <Table
                      dataSource={positions}
                      rowKey="code"
                      columns={positionColumns}
                      size="small"
                      pagination={false}
                      scroll={{ x: 800, y: 300 }}
                    />
                  ),
                },
              ]}
            />
          </Card>

          {/* Order History */}
          <Card
            size="small"
            title={<span><HistoryOutlined /> 委托记录</span>}
            extra={<Text type="secondary">共 {orders.length} 笔</Text>}
          >
            {orders.length === 0 ? (
              <Empty description="暂无委托记录" style={{ margin: '20px 0' }} />
            ) : (
              <Table
                dataSource={[...orders].reverse().slice(0, 100)}
                rowKey="id"
                columns={orderColumns}
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: false }}
                scroll={{ x: 700, y: 250 }}
              />
            )}
          </Card>
        </Col>

        {/* Right: Account Overview + Fund Curve */}
        <Col span={10}>
          <Card title="账户概览" size="small" style={{ marginBottom: 12 }}>
            {account ? (
              <Row gutter={[12, 16]}>
                <Col span={12}>
                  <Statistic
                    title="总资产"
                    value={account.total_asset}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ fontSize: 22, fontWeight: 600 }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="可用资金"
                    value={account.cash}
                    precision={2}
                    prefix="¥"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="持仓市值"
                    value={account.market_value}
                    precision={2}
                    prefix="¥"
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="冻结资金"
                    value={account.frozen}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ color: '#faad14' }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="总盈亏"
                    value={account.total_profit}
                    precision={2}
                    prefix="¥"
                    valueStyle={{ color: account.total_profit >= 0 ? '#cf1322' : '#389e0d' }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="收益率"
                    value={account.total_asset > 0 ? (account.total_profit / (account.total_asset - account.total_profit)) * 100 : 0}
                    precision={2}
                    suffix="%"
                    valueStyle={{ color: account.total_profit >= 0 ? '#cf1322' : '#389e0d' }}
                  />
                </Col>
              </Row>
            ) : (
              <Spin />
            )}
          </Card>

          <Card
            size="small"
            title={<span><LineChartOutlined /> 资金曲线</span>}
          >
            {fundCurve.length > 1 ? (
              fundCurveOption && (
                <ReactEChartsCore
                  option={fundCurveOption}
                  style={{ height: 280 }}
                />
              )
            ) : (
              <Empty description="暂无资金曲线数据" style={{ margin: '40px 0' }} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
