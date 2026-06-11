import React, { useState, useEffect } from 'react'
import { Card, Typography, Row, Col, Statistic, Divider } from 'antd'
import { ThunderboltOutlined } from '@ant-design/icons'
import { isElectron } from '../../utils/electron'

const { Text } = Typography

interface PerformanceMetrics {
  startupTime: number | null
  avgApiTime: number
  cacheHitRate: number
  lastSyncTime: string | null
  apiHistory: { time: number; timestamp: number }[]
}

interface PerformanceMonitorCardProps {
  avgApiTime: number
  lastSyncTime: string | null
  cacheHitRate: number
  apiHistory: { time: number; timestamp: number }[]
}

export const PerformanceMonitorCard = React.memo(function PerformanceMonitorCard({ avgApiTime, lastSyncTime, cacheHitRate, apiHistory }: PerformanceMonitorCardProps) {
  const [startupTime, setStartupTime] = useState<number | null>(null)

  useEffect(() => {
    const saved = localStorage.getItem('perf_metrics')
    if (saved) {
      try {
        const metrics: PerformanceMetrics = JSON.parse(saved)
        if (metrics.startupTime) setStartupTime(metrics.startupTime)
      } catch { /* ignore corrupt data */ }
    }
  }, [])

  const hasData = avgApiTime > 0 || lastSyncTime

  return (
    <Card title={<span><ThunderboltOutlined style={{ marginRight: 8 }} />性能监控</span>} style={{ marginBottom: 16 }}>
      {!hasData ? (
        <div style={{ textAlign: 'center', padding: '24px 0', color: '#999' }}>
          <ThunderboltOutlined style={{ fontSize: 32, marginBottom: 8 }} />
          <div style={{ fontSize: 13 }}>同步数据后将显示性能指标</div>
          <div style={{ fontSize: 12, marginTop: 4 }}>点击「立即同步数据」开始采集</div>
        </div>
      ) : (
        <>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="平均API响应"
                value={avgApiTime > 0 ? Math.round(avgApiTime) : 0}
                suffix="ms"
                valueStyle={{ fontSize: 18, color: avgApiTime > 1000 ? '#ff4d4f' : '#52c41a' }}
              />
            </Col>
            <Col span={8}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>上次同步</Text>
                <br />
                <Text style={{ fontSize: 13 }}>{lastSyncTime || '未同步'}</Text>
              </div>
            </Col>
            <Col span={8}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>缓存命中</Text>
                <br />
                <Text style={{ fontSize: 13 }}>{cacheHitRate > 0 ? `${cacheHitRate.toFixed(1)}%` : '暂无数据'}</Text>
              </div>
            </Col>
          </Row>
          {apiHistory && apiHistory.length > 1 && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              <Text type="secondary" style={{ fontSize: 12 }}>最近 {apiHistory.length} 次响应趋势</Text>
              <div style={{ display: 'flex', alignItems: 'flex-end', height: 60, marginTop: 8, gap: 4 }}>
                {apiHistory.map((item, i) => (
                  <div
                    key={i}
                    style={{
                      flex: 1,
                      height: `${Math.min(100, (item.time / Math.max(...apiHistory.map(h => h.time))) * 100)}%`,
                      minHeight: 8,
                      background: item.time > 1000 ? '#ff4d4f' : item.time > 500 ? '#faad14' : '#52c41a',
                      borderRadius: 2,
                    }}
                    title={`${item.time}ms`}
                  />
                ))}
              </div>
            </>
          )}
          {isElectron() && startupTime && (
            <>
              <Divider style={{ margin: '12px 0' }} />
              <Text type="secondary">启动耗时: <Text code>{startupTime}ms</Text></Text>
            </>
          )}
        </>
      )}
    </Card>
  )
})
