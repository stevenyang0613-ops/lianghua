import React from 'react'
import { Card, Row, Col, InputNumber, Button, Typography } from 'antd'
import { FilterOutlined } from '@ant-design/icons'
import type { ScoreFilterCardProps } from './types'

const { Text } = Typography

export default React.memo(function ScoreFilterCard({
  topN, maxPremium, minPrice, loading,
  onTopNChange, onMaxPremiumChange, onMinPriceChange, onApply,
}: ScoreFilterCardProps) {
  return (
    <Card title={<span><FilterOutlined /> 筛选条件</span>} size="small" style={{ marginBottom: 16 }}>
      <Row gutter={24}>
        <Col span={6}>
          <Text>返回数量 (Top N)</Text>
          <InputNumber min={10} max={200} value={topN} onChange={v => onTopNChange(v ?? 60)} style={{ width: '100%' }} />
        </Col>
        <Col span={6}>
          <Text>溢价率上限 (%)</Text>
          <InputNumber min={10} max={100} value={maxPremium} onChange={v => onMaxPremiumChange(v ?? 50)} style={{ width: '100%' }} />
        </Col>
        <Col span={6}>
          <Text>最低价格</Text>
          <InputNumber min={50} max={150} value={minPrice} onChange={v => onMinPriceChange(v ?? 80)} style={{ width: '100%' }} />
        </Col>
        <Col span={6}>
          <Button type="primary" onClick={onApply} loading={loading} style={{ marginTop: 22 }}>应用筛选</Button>
        </Col>
      </Row>
    </Card>
  )
})
