/**
 * 策略市场页面
 */

import { useEffect, useState } from 'react'
import { Card, Row, Col, Typography, Tag, Rate, Button, Space, Input, Select, Modal, Descriptions, Divider, List, Empty, message, Tabs, Popconfirm, Avatar, Statistic } from 'antd'
import { ShopOutlined, DownloadOutlined, LikeOutlined, UserOutlined, SearchOutlined, DeleteOutlined } from '@ant-design/icons'
import { getSharedStrategies, getMyStrategies, downloadStrategy, deleteMyStrategy, likeStrategy, hasLikedStrategy, CATEGORY_OPTIONS, SORT_OPTIONS, type SharedStrategy } from '../utils/strategyShare'

const { Title, Text, Paragraph } = Typography

export default function StrategyMarket() {
  const [strategies, setStrategies] = useState<SharedStrategy[]>([])
  const [myStrategies, setMyStrategies] = useState<SharedStrategy[]>([])
  const [category, setCategory] = useState('all')
  const [sortBy, setSortBy] = useState<'rating' | 'downloads' | 'returns' | 'createdAt'>('rating')
  const [search, setSearch] = useState('')
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedStrategy, setSelectedStrategy] = useState<SharedStrategy | null>(null)
  const [activeTab, setActiveTab] = useState('market')

  useEffect(() => {
    loadStrategies()
    loadMyStrategies()
  }, [category, sortBy, search])

  const loadStrategies = () => {
    const data = getSharedStrategies({ category, sortBy, search })
    setStrategies(data)
  }

  const loadMyStrategies = () => {
    setMyStrategies(getMyStrategies())
  }

  const handleDownload = (strategy: SharedStrategy) => {
    downloadStrategy(strategy.id)
    loadMyStrategies()
    message.success('策略已下载到本地')
  }

  const handleDelete = (id: string) => {
    deleteMyStrategy(id)
    loadMyStrategies()
    message.success('策略已删除')
  }

  const handleLike = (id: string) => {
    likeStrategy(id)
    message.success('感谢点赞')
  }

  const handleViewDetail = (strategy: SharedStrategy) => {
    setSelectedStrategy(strategy)
    setDetailVisible(true)
  }

  const categoryColors: Record<string, string> = {
    trend: 'blue',
    reversal: 'orange',
    arbitrage: 'green',
    quant: 'purple',
    custom: 'default',
  }

  const categoryLabels: Record<string, string> = {
    trend: '趋势',
    reversal: '反转',
    arbitrage: '套利',
    quant: '量化',
    custom: '自定义',
  }

  const renderStrategyCard = (strategy: SharedStrategy, isMyStrategy: boolean = false) => (
    <Card
      key={strategy.id || strategy.name}
      hoverable
      style={{ marginBottom: 16 }}
      onClick={() => handleViewDetail(strategy)}
    >
      <Row gutter={16} align="middle">
        <Col span={16}>
          <Space direction="vertical" size={4}>
            <Space>
              <Text strong style={{ fontSize: 16 }}>{strategy.name}</Text>
              <Tag color={categoryColors[strategy.category]}>{categoryLabels[strategy.category]}</Tag>
            </Space>
            <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
              {strategy.description}
            </Paragraph>
            <Space wrap>
              {strategy.tags.slice(0, 3).map(tag => (
                <Tag key={tag} style={{ fontSize: 11 }}>{tag}</Tag>
              ))}
            </Space>
          </Space>
        </Col>
        <Col span={8}>
          <Row gutter={8}>
            <Col span={8}>
              <Statistic
                title="收益"
                value={strategy.returns}
                suffix="%"
                valueStyle={{ fontSize: 14, color: strategy.returns >= 0 ? '#52c41a' : '#ff4d4f' }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="胜率"
                value={strategy.winRate}
                suffix="%"
                valueStyle={{ fontSize: 14 }}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="回撤"
                value={strategy.maxDrawdown}
                suffix="%"
                valueStyle={{ fontSize: 14, color: '#ff4d4f' }}
              />
            </Col>
          </Row>
          <Divider style={{ margin: '8px 0' }} />
          <Space>
            <Rate disabled value={strategy.rating} allowHalf style={{ fontSize: 12 }} />
            <Text type="secondary" style={{ fontSize: 12 }}>({strategy.rating})</Text>
          </Space>
        </Col>
      </Row>
      <Divider style={{ margin: '12px 0' }} />
      <Row justify="space-between" align="middle">
        <Col>
          <Space>
            <Avatar size="small" icon={<UserOutlined />} />
            <Text type="secondary">{strategy.author}</Text>
            <Text type="secondary">|</Text>
            <Text type="secondary"><DownloadOutlined /> {strategy.downloads}</Text>
            <Text type="secondary"><LikeOutlined /> {strategy.likes}</Text>
          </Space>
        </Col>
        <Col>
          {isMyStrategy ? (
            <Popconfirm title="确定删除此策略？" onConfirm={(e) => { e?.stopPropagation(); handleDelete(strategy.id) }}>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={(e) => e.stopPropagation()}>
                删除
              </Button>
            </Popconfirm>
          ) : (
            <Button
              type="primary"
              size="small"
              icon={<DownloadOutlined />}
              onClick={(e) => { e.stopPropagation(); handleDownload(strategy) }}
              disabled={myStrategies.some(s => s.id === strategy.id)}
            >
              {myStrategies.some(s => s.id === strategy.id) ? '已下载' : '下载'}
            </Button>
          )}
        </Col>
      </Row>
    </Card>
  )

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={4}><ShopOutlined style={{ marginRight: 8 }} />策略市场</Title>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'market', label: `策略市场 (${strategies.length})` },
          { key: 'my', label: `我的策略 (${myStrategies.length})` },
        ]}
      />

      {activeTab === 'market' && (
        <>
          {/* 筛选 */}
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={16} align="middle">
              <Col span={8}>
                <Input
                  prefix={<SearchOutlined />}
                  placeholder="搜索策略名称、标签..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  allowClear
                />
              </Col>
              <Col span={8}>
                <Select
                  style={{ width: '100%' }}
                  value={category}
                  onChange={setCategory}
                  options={CATEGORY_OPTIONS}
                />
              </Col>
              <Col span={8}>
                <Select
                  style={{ width: '100%' }}
                  value={sortBy}
                  onChange={setSortBy}
                  options={SORT_OPTIONS}
                />
              </Col>
            </Row>
          </Card>

          {/* 策略列表 */}
          {strategies.length === 0 ? (
            <Empty description="暂无策略" />
          ) : (
            strategies.map(s => renderStrategyCard(s))
          )}
        </>
      )}

      {activeTab === 'my' && (
        myStrategies.length === 0 ? (
          <Empty description="暂无已下载的策略" />
        ) : (
          myStrategies.map(s => renderStrategyCard(s, true))
        )
      )}

      {/* 策略详情弹窗 */}
      <Modal
        title={selectedStrategy?.name}
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={700}
      >
        {selectedStrategy && (
          <>
            <Descriptions column={3}>
              <Descriptions.Item label="分类">
                <Tag color={categoryColors[selectedStrategy.category]}>{categoryLabels[selectedStrategy.category]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="作者">{selectedStrategy.author}</Descriptions.Item>
              <Descriptions.Item label="评分">
                <Rate disabled value={selectedStrategy.rating} allowHalf style={{ fontSize: 12 }} />
              </Descriptions.Item>
              <Descriptions.Item label="累计收益">
                <Text style={{ color: selectedStrategy.returns >= 0 ? '#52c41a' : '#ff4d4f' }}>
                  {selectedStrategy.returns}%
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="最大回撤">
                <Text style={{ color: '#ff4d4f' }}>{selectedStrategy.maxDrawdown}%</Text>
              </Descriptions.Item>
              <Descriptions.Item label="夏普比率">{selectedStrategy.sharpe}</Descriptions.Item>
              <Descriptions.Item label="胜率">{selectedStrategy.winRate}%</Descriptions.Item>
              <Descriptions.Item label="交易次数">{selectedStrategy.tradeCount}</Descriptions.Item>
              <Descriptions.Item label="下载次数">{selectedStrategy.downloads}</Descriptions.Item>
            </Descriptions>

            <Divider />

            <Title level={5}>策略描述</Title>
            <Paragraph>{selectedStrategy.description}</Paragraph>

            <Title level={5}>参数设置</Title>
            <List
              size="small"
              dataSource={selectedStrategy.params}
              renderItem={(param) => (
                <List.Item>
                  <Text code>{param.name}</Text>: {param.description} (默认: {String(param.default)})
                </List.Item>
              )}
            />

            <Divider />

            <Space>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                onClick={() => handleDownload(selectedStrategy)}
                disabled={myStrategies.some(s => s.id === selectedStrategy.id)}
              >
                {myStrategies.some(s => s.id === selectedStrategy.id) ? '已下载' : '下载策略'}
              </Button>
              <Button
                icon={<LikeOutlined />}
                onClick={() => handleLike(selectedStrategy.id)}
                disabled={hasLikedStrategy(selectedStrategy.id)}
              >
                {hasLikedStrategy(selectedStrategy.id) ? '已点赞' : '点赞'}
              </Button>
            </Space>
          </>
        )}
      </Modal>
    </div>
  )
}
