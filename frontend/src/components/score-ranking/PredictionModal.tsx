import React from 'react'
import { Modal, Row, Col, Card, Statistic, Progress, Empty, Spin } from 'antd'
import { LineChartOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { PredictionModalProps } from './types'

const scoreColor = (v: number) => {
  if (v >= 0.7) return '#52c41a'
  if (v >= 0.5) return '#1677ff'
  if (v >= 0.3) return '#faad14'
  return '#ff4d4f'
}

export default React.memo(function PredictionModal({
  open, predictionCode, prediction, predictionLoading, onClose,
}: PredictionModalProps) {
  return (
    <Modal title={<span><LineChartOutlined /> 评分趋势预测 - {predictionCode}</span>} open={open} onCancel={onClose} footer={null} width={700}>
      {predictionLoading ? <Spin /> : prediction ? (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}>
              <Card size="small">
                <Statistic
                  title="当前评分"
                  value={prediction.current_score?.toFixed(3)}
                  prefix={prediction.trend === '上升' ? <RiseOutlined style={{ color: '#52c41a' }} /> : prediction.trend === '下降' ? <FallOutlined style={{ color: '#ff4d4f' }} /> : null}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="趋势方向" value={prediction.trend} valueStyle={{ color: prediction.trend === '上升' ? '#52c41a' : prediction.trend === '下降' ? '#ff4d4f' : '#1677ff' }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="预测置信度" value={prediction.confidence} suffix="%" valueStyle={{ color: prediction.confidence >= 70 ? '#52c41a' : prediction.confidence >= 50 ? '#faad14' : '#ff4d4f' }} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="波动率" value={prediction.volatility?.toFixed(4)} />
              </Card>
            </Col>
          </Row>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={8}>
              <Card size="small"><Statistic title="5日变化" value={prediction.change_5d?.toFixed(4)} valueStyle={{ color: prediction.change_5d >= 0 ? '#52c41a' : '#ff4d4f' }} /></Card>
            </Col>
            <Col span={8}>
              <Card size="small"><Statistic title="10日变化" value={prediction.change_10d?.toFixed(4)} valueStyle={{ color: prediction.change_10d >= 0 ? '#52c41a' : '#ff4d4f' }} /></Card>
            </Col>
            <Col span={8}>
              <Card size="small">
                <Statistic title="趋势斜率" value={prediction.slope?.toExponential(2)} valueStyle={{ color: prediction.slope > 0 ? '#52c41a' : '#ff4d4f' }} />
              </Card>
            </Col>
          </Row>
          <Card size="small" title="未来5日预测" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              {prediction.predictions.map((p, i) => (
                <Col span={4.8} key={i} style={{ textAlign: 'center' }}>
                  <div style={{ fontWeight: 'bold' }}>第{p.day}天</div>
                  <Progress type="circle" percent={Math.round(p.predicted_score * 100)} size={60} strokeColor={scoreColor(p.predicted_score)} />
                  <div style={{ color: scoreColor(p.predicted_score) }}>{p.predicted_score.toFixed(3)}</div>
                </Col>
              ))}
            </Row>
          </Card>
          {prediction.historical_data && prediction.historical_data.length > 0 && (
            <Card size="small" title="历史评分趋势">
              <ReactEChartsCore
                echarts={echarts}
                option={{
                  tooltip: { trigger: 'axis' as const },
                  grid: { left: 40, right: 20, top: 20, bottom: 40 },
                  xAxis: { type: 'category' as const, data: prediction.historical_data.map(h => h.date.slice(5)), axisLabel: { rotate: 45, fontSize: 10 } },
                  yAxis: { type: 'value' as const, name: '评分', min: 0, max: 1 },
                  series: [
                    { name: '历史评分', type: 'line' as const, data: prediction.historical_data.map(h => h.score), smooth: true, lineStyle: { width: 2 } },
                  ],
                }}
                style={{ height: 200 }}
                opts={{ renderer: 'svg' }}
              />
            </Card>
          )}
        </div>
      ) : <Empty description="暂无预测数据" />}
    </Modal>
  )
})
