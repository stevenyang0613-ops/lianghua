import React from 'react'
import { Card, Row, Col, Table, Tag, Empty, Button, Spin, theme as antTheme } from 'antd'
import { AimOutlined, LineChartOutlined } from '@ant-design/icons'

import type { AccuracyDetail, HorizonAccuracy, RecAccuracyResponse, RecHistoryEntry } from '../services/api'

interface Props {
  historyLoading: boolean
  accuracyLoading: boolean
  historyData: { history: RecHistoryEntry[] } | null
  accuracyData: RecAccuracyResponse | null
  onLoadHistory: () => void
  onLoadAccuracy: () => void
}

const RecHistoryTable: React.FC<Props> = ({
  historyLoading, accuracyLoading,
  historyData, accuracyData,
  onLoadHistory, onLoadAccuracy,
}) => {
  const { token: themeToken } = antTheme.useToken()

  if (historyLoading && accuracyLoading) {
    return <Spin style={{ display: 'block', margin: '40px auto' }} />
  }

  if (!historyData || historyData.history.length === 0) {
    return (
      <Empty description='暂无历史推荐数据'>
        <Button size='small' onClick={onLoadHistory}>加载历史</Button>
      </Empty>
    )
  }

  const acc = accuracyData?.accuracy || {}

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {accuracyData && Object.keys(acc).length > 0 && (
        <Card
          size='small'
          title={<span><AimOutlined /> 推荐准确率回测 (最近{accuracyData.days_analyzed}天)</span>}
          styles={{ body: { padding: '8px 16px' } }}
        >
          <Row gutter={[12, 8]}>
            {[['short_term', '短期', '#ff4d4f'], ['mid_term', '中期', '#fa8c16'], ['long_term', '长期', '#722ed1']].map(([key, label, color]) => {
              const h = acc[key] as HorizonAccuracy | undefined
              if (!h || h.total === 0) return null
              return (
                <Col xs={24} sm={8} key={key}>
                  <div style={{ textAlign: 'center', padding: '8px 0' }}>
                    <div style={{ fontSize: 24, fontWeight: 700, color }}>{h.hit_rate}%</div>
                    <div style={{ fontSize: 12, color: themeToken.colorTextSecondary }}>{label}命中率</div>
                    <div style={{ fontSize: 11, color: themeToken.colorTextSecondary }}>命中 {h.hits}/{h.total} 次</div>
                    {accuracyData?.random_baseline?.[key] != null && (
                      <>
                        <div style={{ fontSize: 10, color: themeToken.colorTextTertiary, marginTop: 2 }}>
                          随机基线 {accuracyData.random_baseline[key]}%
                        </div>
                        <div style={{
                          fontSize: 11, fontWeight: 600, marginTop: 2,
                          color: h.alpha > 0 ? '#52c41a' : '#ff4d4f'
                        }}>
                          α {h.alpha > 0 ? '+' : ''}{h.alpha}% {h.alpha > 0 ? '✓优于随机' : '✗劣于随机'}
                        </div>
                      </>
                    )}
                  </div>
                </Col>
              )
            })}
          </Row>
        </Card>
      )}

      {accuracyData?.daily_alpha && Object.keys(accuracyData.daily_alpha).length > 0 && (
        <Card
          size='small'
          title={<span><LineChartOutlined /> α趋势 (逐日)</span>}
          styles={{ body: { padding: 0 } }}
        >
          <Table
            size='small'
            dataSource={Object.entries(accuracyData.daily_alpha)
              .sort(([a], [b]) => b.localeCompare(a))
              .slice(0, 30)
              .map(([date, vals], idx) => ({ date, ...vals, key: idx }))}
            pagination={false}
            scroll={{ x: 400 }}
            columns={[
              { title: '日期', dataIndex: 'date', width: 90 },
              {
                title: '短期α', dataIndex: 'short_term', width: 80,
                render: (v: number) => (
                  <span style={{ color: v > 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
                    {v > 0 ? '+' : ''}{v}%
                  </span>
                ),
              },
              {
                title: '中期α', dataIndex: 'mid_term', width: 80,
                render: (v: number) => (
                  <span style={{ color: v > 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
                    {v > 0 ? '+' : ''}{v}%
                  </span>
                ),
              },
              {
                title: '长期α', dataIndex: 'long_term', width: 80,
                render: (v: number) => (
                  <span style={{ color: v > 0 ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
                    {v > 0 ? '+' : ''}{v}%
                  </span>
                ),
              },
            ]}
          />
        </Card>
      )}

      {!accuracyData && (
        <Button size='small' loading={accuracyLoading} onClick={onLoadAccuracy}>
          加载准确率
        </Button>
      )}

      <Table
        size='small'
        dataSource={historyData.history.map((h, idx) => ({ ...h, key: idx }))}
        pagination={{ pageSize: 10, showTotal: t => `共 ${t} 天` }}
        scroll={{ x: 1200, y: 400 }}
        columns={[
          { title: '日期', dataIndex: 'date', width: 100, sorter: (a: any, b: any) => a.date.localeCompare(b.date), defaultSortOrder: 'descend' as const },
          { title: '短期推荐', key: 'short', width: 220, render: (_: any, r: RecHistoryEntry) => (r.short_term || []).map(s => <Tag key={s.industry} color='red' style={{ marginBottom: 2 }}>{s.industry} {s.score}分</Tag>) },
          { title: '中期推荐', key: 'mid', width: 220, render: (_: any, r: RecHistoryEntry) => (r.mid_term || []).map(s => <Tag key={s.industry} color='orange' style={{ marginBottom: 2 }}>{s.industry} {s.score}分</Tag>) },
          { title: '长期推荐', key: 'long', width: 220, render: (_: any, r: RecHistoryEntry) => (r.long_term || []).map(s => <Tag key={s.industry} color='purple' style={{ marginBottom: 2 }}>{s.industry} {s.score}分</Tag>) },
        ]}
      />
    </div>
  )
}

export default RecHistoryTable