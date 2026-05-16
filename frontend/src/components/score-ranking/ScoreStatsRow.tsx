import React from 'react'
import { Row, Col, Card, Statistic } from 'antd'
import { StarOutlined } from '@ant-design/icons'
import type { ScoreStatsRowProps } from './types'

export default React.memo(function ScoreStatsRow({ total, returned, items }: ScoreStatsRowProps) {
  const avgScore = items.length > 0
    ? (items.reduce((sum, item) => sum + item.score, 0) / items.length).toFixed(3)
    : '-'

  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={6}><Card size="small"><Statistic title="符合条件总数" value={total} suffix="只" /></Card></Col>
      <Col span={6}><Card size="small"><Statistic title="返回数量" value={returned} suffix="只" valueStyle={{ color: '#1677ff' }} /></Card></Col>
      <Col span={6}><Card size="small"><Statistic title="最高评分" value={items[0]?.score?.toFixed(3) || '-'} prefix={<StarOutlined style={{ color: '#faad14' }} />} /></Card></Col>
      <Col span={6}><Card size="small"><Statistic title="平均评分" value={avgScore} /></Card></Col>
    </Row>
  )
})
