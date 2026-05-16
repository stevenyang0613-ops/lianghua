import React, { useMemo } from 'react'
import { Modal, Spin, Empty, Typography } from 'antd'
import { LineChartOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'
import type { ScoreHistoryModalProps } from './types'

const { Text } = Typography

export default React.memo(function ScoreHistoryModal({
  open, selectedCode, scoreHistory, historyLoading, onClose,
}: ScoreHistoryModalProps) {
  const trendChartOption = useMemo(() => {
    if (scoreHistory.length === 0) return {}
    return {
      tooltip: { trigger: 'axis' as const },
      legend: { data: ['综合评分', '双低因子', '溢价因子'], top: 0, right: 20 },
      grid: { left: 50, right: 20, top: 40, bottom: 40 },
      xAxis: { type: 'category' as const, data: scoreHistory.map(h => h.snapshot_date), axisLabel: { rotate: 45, fontSize: 10 } },
      yAxis: { type: 'value' as const, name: '评分', min: 0, max: 1 },
      series: [
        { name: '综合评分', type: 'line' as const, data: scoreHistory.map(h => h.score), smooth: true, lineStyle: { width: 2 } },
        { name: '双低因子', type: 'line' as const, data: scoreHistory.map(h => h.score_dual_low), smooth: true, lineStyle: { type: 'dashed' } },
        { name: '溢价因子', type: 'line' as const, data: scoreHistory.map(h => h.score_premium), smooth: true, lineStyle: { type: 'dashed' } },
      ],
    }
  }, [scoreHistory])

  return (
    <Modal title={<span><LineChartOutlined /> 评分历史 - {selectedCode}</span>} open={open} onCancel={onClose} footer={null} width={800}>
      {historyLoading ? <Spin /> : scoreHistory.length > 0 ? (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">最近 {scoreHistory.length} 天评分趋势</Text>
          </div>
          <ReactEChartsCore echarts={echarts} option={trendChartOption} style={{ height: 300 }} opts={{ renderer: 'svg' }} />
        </div>
      ) : <Empty description="暂无历史数据" />}
    </Modal>
  )
})
