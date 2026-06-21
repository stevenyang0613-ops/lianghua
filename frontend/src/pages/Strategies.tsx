import { useState, useEffect } from 'react'
import { Card, Table, Tag, Typography, Spin, Empty, message, Row, Col, Descriptions, Button, Divider, Skeleton } from 'antd'
import { DeploymentUnitOutlined, InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useStrategyStore } from '../stores/useStrategyStore'
import type { StrategyInfo, SignalHistoryItem, SignalStats } from '../services/api'
import { fmt } from '../utils/format'

const { Title, Text } = Typography




export default function Strategies() {
  const strategies = useStrategyStore((s) => s.strategies)
  const loading = useStrategyStore((s) => s.loading)
  const selectedStrategy = useStrategyStore((s) => s.selectedStrategy)
  const signalHistory = useStrategyStore((s) => s.signalHistory)
  const signalHistoryLoading = useStrategyStore((s) => s.signalHistoryLoading)
  const signalStats = useStrategyStore((s) => s.signalStats)
  const loadStrategies = useStrategyStore((s) => s.loadStrategies)
  const selectStrategy = useStrategyStore((s) => s.selectStrategy)
  const loadStats = useStrategyStore((s) => s.loadStats)

  useEffect(() => {
    loadStrategies()
    loadStats()
  }, [loadStrategies, loadStats])

  const strategyColumns = [
    { title: 'ID', dataIndex: 'id', width: 100 },
    { title: '策略名称', dataIndex: 'name', width: 150 },
    { title: '描述', dataIndex: 'description', width: 300, ellipsis: true },
    {
      title: '参数数量',
      width: 100,
      render: (_: any, record: StrategyInfo) => <Tag>{record.params.length} 个</Tag>,
    },
    {
      title: '信号次数',
      width: 100,
      render: (_: any, record: StrategyInfo) => {
        const stat = signalStats?.strategy_stats?.find(s => s.strategy === record.id)
        return stat ? <Tag color="blue">{stat.count} 次</Tag> : <Tag>--</Tag>
      },
    },
    {
      title: '操作',
      width: 100,
      render: (_: any, record: StrategyInfo) => (
        <Button type="link" onClick={() => selectStrategy(record)}>查看详情</Button>
      ),
    },
  ]

  const actionColors: Record<string, string> = { buy: 'green', sell: 'red' }

  if (loading && strategies.length === 0) {
    return (
      <div style={{ padding: 16 }}>
        <Skeleton paragraph={{ rows: 6 }} active />
      </div>
    )
  }
  if (strategies.length === 0) return <Empty description="暂无已注册策略" />

  return (
    <div style={{ padding: 16 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <DeploymentUnitOutlined /> 策略管理
      </Title>

      <Row gutter={16}>
        <Col span={10}>
          <Card title="已注册策略" size="small" extra={<Text type="secondary">共 {strategies.length} 个</Text>}>
            <Table
              dataSource={strategies}
              rowKey="id"
              columns={strategyColumns}
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
            />
          </Card>
        </Col>

        <Col span={14}>
          {selectedStrategy ? (
            <Card
              title={<span><InfoCircleOutlined /> {selectedStrategy.name}</span>}
              size="small"
            >
              <Descriptions column={1} size="small">
                <Descriptions.Item label="策略 ID">{selectedStrategy.id}</Descriptions.Item>
                <Descriptions.Item label="策略名称">{selectedStrategy.name}</Descriptions.Item>
                <Descriptions.Item label="描述">{selectedStrategy.description}</Descriptions.Item>
              </Descriptions>

              <Divider orientation="left" plain>参数配置</Divider>
              <Table
                dataSource={selectedStrategy.params}
                rowKey="name"
                size="small"
                pagination={false}
                columns={[
                  { title: '参数名', dataIndex: 'name', width: 100 },
                  { title: '标签', dataIndex: 'label', width: 120 },
                  { title: '类型', dataIndex: 'type', width: 60, render: (v: string) => <Tag>{v}</Tag> },
                  { title: '默认值', dataIndex: 'default', width: 80 },
                  { title: '最小值', dataIndex: 'min_val', width: 80, render: (v?: number) => v ?? '-' },
                  { title: '最大值', dataIndex: 'max_val', width: 80, render: (v?: number) => v ?? '-' },
                ]}
              />

              <Divider orientation="left" plain><ThunderboltOutlined /> 历史信号</Divider>
              <Table
                dataSource={signalHistory}
                rowKey="id"
                size="small"
                loading={signalHistoryLoading}
                pagination={{ pageSize: 5, showTotal: (t) => `共 ${t} 条` }}
                columns={[
                  { title: '代码', dataIndex: 'code', width: 80, render: (v: string) => <Text code>{v}</Text> },
                  { title: '名称', dataIndex: 'name', width: 120 },
                  { title: '方向', dataIndex: 'action', width: 60, render: (v: string) => <Tag color={actionColors[v]}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
                  { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => fmt(v, 3) },
                  { title: '置信度', dataIndex: 'confidence', width: 70, render: (v: number) => `${fmt((v ?? 0) * 100, 0)}%` },
                  { title: '已执行', dataIndex: 'executed', width: 60, render: (v: boolean) => v ? <Tag color="green">是</Tag> : <Tag color="default">否</Tag> },
                  { title: '原因', dataIndex: 'reason', ellipsis: true },
                  { title: '时间', dataIndex: 'ts', width: 160, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
                ]}
              />
            </Card>
          ) : (
            <Empty description="请选择一个策略查看详情" />
          )}
        </Col>
      </Row>
    </div>
  )
}