import React from 'react'
import { Card, Row, Col, Statistic, Empty, Button } from 'antd'
import { DashboardOutlined } from '@ant-design/icons'
import type { RiskAnalysisCardProps } from './types'

export default React.memo(function RiskAnalysisCard({
  riskMetrics, riskLoading, onRunRiskAnalysis,
}: RiskAnalysisCardProps) {
  return (
    <Card size="small" title="风险指标分析" style={{ marginTop: 16 }} extra={
      <Button type="primary" size="small" icon={<DashboardOutlined />} onClick={onRunRiskAnalysis} loading={riskLoading}>计算风险指标</Button>
    }>
      {riskMetrics ? (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Card size="small"><Statistic title="累计收益" value={riskMetrics.return_metrics.total_return} suffix="%" valueStyle={{ color: riskMetrics.return_metrics.total_return >= 0 ? '#cf1322' : '#3f8600' }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="年化收益" value={riskMetrics.return_metrics.annualized_return} suffix="%" /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="最大回撤" value={riskMetrics.risk_metrics.max_drawdown} suffix="%" valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="年化波动率" value={riskMetrics.risk_metrics.annualized_volatility} suffix="%" /></Card></Col>
          </Row>
          <Row gutter={16}>
            <Col span={6}><Card size="small"><Statistic title="夏普比率" value={riskMetrics.risk_adjusted_metrics.sharpe_ratio} valueStyle={{ color: riskMetrics.risk_adjusted_metrics.sharpe_ratio >= 1 ? '#52c41a' : '#faad14' }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="卡玛比率" value={riskMetrics.risk_adjusted_metrics.calmar_ratio} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="胜率" value={riskMetrics.trade_metrics.win_rate} suffix="%" /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="盈亏比" value={riskMetrics.trade_metrics.profit_loss_ratio} /></Card></Col>
          </Row>
        </div>
      ) : <Empty description="点击【计算风险指标】查看详细分析" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
    </Card>
  )
})
