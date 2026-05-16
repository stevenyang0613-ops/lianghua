import React from 'react'
import { Card, Row, Col, Slider, Button, Select, Space, Typography } from 'antd'
import { StarOutlined } from '@ant-design/icons'
import type { WeightConfigCardProps } from './types'

const { Text } = Typography

const weightLabels: Record<string, string> = {
  dual_low: '双低权重',
  premium: '溢价权重',
  momentum: '动量权重',
  volume: '成交量权重',
  price: '价格权重',
}

export default React.memo(function WeightConfigCard({
  weights, selectedFactor, customFactors,
  onWeightChange, onLoadFactor, onResetWeights,
}: WeightConfigCardProps) {
  return (
    <Card title={<span><StarOutlined /> 因子权重</span>} size="small" style={{ marginBottom: 16 }}
      extra={<Space>
        <Select value={selectedFactor} onChange={onLoadFactor} style={{ width: 150 }} options={[
          { value: 'default', label: '默认配置' },
          ...Object.entries(customFactors).map(([id, f]) => ({ value: id, label: f.name }))
        ]} />
      </Space>}>
      <Row gutter={24}>
        {Object.entries(weightLabels).map(([key, label]) => (
          <Col span={4} key={key}>
            <Text>{label} ({(weights[key] ?? 0).toFixed(1)})</Text>
            <Slider min={0} max={1} step={0.1} value={weights[key] ?? 0} onChange={v => onWeightChange(key, v)} />
          </Col>
        ))}
        <Col span={4}>
          <Button onClick={onResetWeights}>重置权重</Button>
        </Col>
      </Row>
    </Card>
  )
})
