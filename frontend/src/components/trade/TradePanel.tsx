import { useState } from 'react'
import { Form, Select, InputNumber, Button, Row, Col, Typography, message } from 'antd'
import { ShoppingCartOutlined } from '@ant-design/icons'
import type { Account } from '../../stores/useTradeStore'
import { placeOrder } from '../../services/api'

const { Text } = Typography

interface TradePanelProps {
  allBonds: { code: string; name: string; price: number }[]
  account: Account | null
  loading: boolean
  setLoading: (v: boolean) => void
  onOrderPlaced: () => void
}

interface BondOption {
  code: string
  name: string
  price: number
}

export default function TradePanel({ allBonds, account, loading, setLoading, onOrderPlaced }: TradePanelProps) {
  const [side, setSide] = useState<'buy' | 'sell'>('buy')
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [price, setPrice] = useState<number>(0)
  const [volume, setVolume] = useState<number>(10)

  const handleBondSelect = (code: string) => {
    setSelectedCode(code)
    const bond = allBonds.find((b: BondOption) => b.code === code)
    if (bond) setPrice(bond.price)
  }

  const handlePlaceOrder = async () => {
    if (!selectedCode) { message.warning('请选择可转债'); return }
    if (price <= 0 || volume <= 0) { message.warning('请输入有效的价格和数量'); return }

    const bond = allBonds.find((b: BondOption) => b.code === selectedCode)
    setLoading(true)
    try {
      const result = await placeOrder({ code: selectedCode, name: bond?.name || '', side, price, volume })
      if (result.status === 'rejected') {
        message.error(`下单被拒绝: ${result.reject_reason}`)
      } else {
        message.success(`${side === 'buy' ? '买入' : '卖出'} ${selectedCode} ${volume} 张成功`)
      }
      onOrderPlaced()
    } catch (e: any) {
      message.error('下单失败: ' + (e.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  return (
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
              options={allBonds.map((b: BondOption) => ({
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
            <InputNumber style={{ width: '100%' }} value={price} onChange={(v) => setPrice(v || 0)} min={0} step={0.001} precision={3} placeholder="输入价格" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item label="数量 (张)">
            <InputNumber style={{ width: '100%' }} value={volume} onChange={(v) => setVolume(v || 0)} min={1} step={10} placeholder="输入数量" />
          </Form.Item>
        </Col>
      </Row>
      {selectedCode && (
        <Row gutter={16} style={{ marginBottom: 12 }}>
          <Col span={12}><Text type="secondary">估算金额: <Text strong>¥{(price * volume).toFixed(2)}</Text></Text></Col>
          <Col span={12}><Text type="secondary">可用资金: <Text strong>¥{account?.cash.toFixed(2) || '0.00'}</Text></Text></Col>
        </Row>
      )}
      <Button
        type="primary"
        icon={<ShoppingCartOutlined />}
        onClick={handlePlaceOrder}
        loading={loading}
        block
        size="large"
        style={{ backgroundColor: side === 'buy' ? '#cf1322' : '#389e0d', borderColor: side === 'buy' ? '#cf1322' : '#389e0d' }}
      >
        {side === 'buy' ? '买入' : '卖出'}
      </Button>
    </Form>
  )
}
