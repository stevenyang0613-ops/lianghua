import { useState, useEffect } from 'react'
import { Card, Table, Tag, Typography, Spin, Empty, message, Tabs, Row, Col, Statistic, Descriptions, Button, Space, Divider } from 'antd'
import { DeploymentUnitOutlined, ExperimentOutlined, BarChartOutlined, ReloadOutlined, InfoCircleOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react'
import { fetchStrategies } from '../services/api'
import type { StrategyInfo } from '../services/api'

const { Title, Text, Paragraph } = Typography

export default function Strategies() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyInfo | null>(null)

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list)
        if (list.length > 0) setSelectedStrategy(list[0])
      })
      .catch(e => message.error('加载策略失败: ' + e.message))
      .finally(() => setLoading(false))
  }, [])

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
      title: '操作',
      width: 100,
      render: (_: any, record: StrategyInfo) => (
        <Button type="link" onClick={() => setSelectedStrategy(record)}>查看详情</Button>
      ),
    },
  ]

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '60px auto' }} />
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
            </Card>
          ) : (
            <Empty description="请选择一个策略查看详情" />
          )}
        </Col>
      </Row>
    </div>
  )
}
