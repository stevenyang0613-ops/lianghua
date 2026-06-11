/**
 * 消息中心页面
 */

import { useEffect, useState } from 'react'
import { Card, List, Tag, Button, Space, Typography, Empty, Badge, Popconfirm, Input, Select, message as antMessage, Tooltip, Avatar } from 'antd'
import { BellOutlined, StarOutlined, StarFilled, DeleteOutlined, CheckOutlined, CheckCircleOutlined, SearchOutlined, SettingOutlined, AppstoreOutlined, DollarOutlined, AlertOutlined, ReloadOutlined } from '@ant-design/icons'
import { getMessages, markAsRead, markAllAsRead, toggleStar, deleteMessage, clearMessages, getUnreadCount, getCategories, type Message, type MessageCategory } from '../utils/messageCenter'

const { Title, Text, Paragraph } = Typography

const typeColors: Record<string, string> = {
  system: 'blue',
  trade: 'green',
  signal: 'purple',
  alert: 'orange',
  update: 'cyan',
  notification: 'default',
}

const typeLabels: Record<string, string> = {
  system: '系统',
  trade: '交易',
  signal: '信号',
  alert: '预警',
  update: '更新',
  notification: '通知',
}

const levelColors: Record<string, string> = {
  info: '#1890ff',
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
}

export default function MessageCenter() {
  const [messages, setMessages] = useState<Message[]>([])
  const [categories, setCategories] = useState<MessageCategory[]>([])
  const [activeCategory, setActiveCategory] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [filter, setFilter] = useState<'all' | 'unread' | 'starred'>('all')

  useEffect(() => {
    loadData()
  }, [activeCategory, filter])

  const loadData = () => {
    let filteredMessages = getMessages()

    // 分类过滤
    if (activeCategory !== 'all') {
      filteredMessages = filteredMessages.filter(m => m.type === activeCategory)
    }

    // 状态过滤
    if (filter === 'unread') {
      filteredMessages = filteredMessages.filter(m => !m.read)
    } else if (filter === 'starred') {
      filteredMessages = filteredMessages.filter(m => m.starred)
    }

    // 搜索过滤
    if (searchText) {
      const search = searchText.toLowerCase()
      filteredMessages = filteredMessages.filter(m =>
        m.title.toLowerCase().includes(search) ||
        m.content.toLowerCase().includes(search)
      )
    }

    setMessages(filteredMessages)
    setCategories(getCategories())
  }

  const handleMarkAsRead = (id: string) => {
    markAsRead(id)
    loadData()
  }

  const handleMarkAllAsRead = () => {
    const count = markAllAsRead(activeCategory === 'all' ? undefined : activeCategory as any)
    loadData()
    antMessage.success(`已标记 ${count} 条消息为已读`)
  }

  const handleToggleStar = (id: string) => {
    toggleStar(id)
    loadData()
  }

  const handleDelete = (id: string) => {
    deleteMessage(id)
    loadData()
    antMessage.success('消息已删除')
  }

  const handleClearAll = () => {
    const count = clearMessages(activeCategory === 'all' ? undefined : activeCategory as any)
    loadData()
    antMessage.success(`已清除 ${count} 条消息`)
  }

  const getIcon = (key: string) => {
    switch (key) {
      case 'system': return <SettingOutlined />
      case 'trade': return <DollarOutlined />
      case 'signal': return <AlertOutlined />
      case 'alert': return <BellOutlined />
      case 'update': return <ReloadOutlined />
      default: return <AppstoreOutlined />
    }
  }

  return (
    <div style={{ padding: 16, maxWidth: 900, margin: '0 auto' }}>
      <Title level={4}>
        <Badge count={getUnreadCount()} offset={[10, 0]}>
          <BellOutlined style={{ marginRight: 8 }} />
        </Badge>
        消息中心
      </Title>

      {/* 分类标签 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          {categories.map(cat => (
            <Tag
              key={cat.key}
              color={activeCategory === cat.key ? 'blue' : 'default'}
              style={{ cursor: 'pointer', padding: '4px 12px' }}
              onClick={() => setActiveCategory(cat.key)}
            >
              {getIcon(cat.key)}
              <span style={{ marginLeft: 4 }}>{cat.label}</span>
              {cat.unreadCount > 0 && (
                <Badge count={cat.unreadCount} style={{ marginLeft: 8 }} />
              )}
            </Tag>
          ))}
        </Space>
      </Card>

      {/* 筛选和操作 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            prefix={<SearchOutlined />}
            placeholder="搜索消息..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            value={filter}
            onChange={setFilter}
            style={{ width: 120 }}
            options={[
              { value: 'all', label: '全部' },
              { value: 'unread', label: '未读' },
              { value: 'starred', label: '星标' },
            ]}
          />
          <Button icon={<CheckOutlined />} onClick={handleMarkAllAsRead}>
            全部已读
          </Button>
          <Popconfirm title="确定清空所有消息？" onConfirm={handleClearAll}>
            <Button danger icon={<DeleteOutlined />}>
              清空消息
            </Button>
          </Popconfirm>
        </Space>
      </Card>

      {/* 消息列表 */}
      <Card>
        {messages.length === 0 ? (
          <Empty description="暂无消息" />
        ) : (
          <List
            itemLayout="vertical"
            dataSource={messages}
            renderItem={(msg) => (
              <List.Item
                style={{
                  background: msg.read ? 'transparent' : '#f6ffed',
                  padding: 16,
                  borderRadius: 4,
                  marginBottom: 8,
                }}
                actions={[
                  <Tooltip title={msg.starred ? '取消星标' : '添加星标'} key="star">
                    <Button
                      type="text"
                      icon={msg.starred ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                      onClick={() => handleToggleStar(msg.id)}
                    />
                  </Tooltip>,
                  !msg.read && (
                    <Tooltip title="标记已读" key="read">
                      <Button
                        type="text"
                        icon={<CheckCircleOutlined />}
                        onClick={() => handleMarkAsRead(msg.id)}
                      />
                    </Tooltip>
                  ),
                  <Popconfirm
                    key="delete"
                    title="确定删除此消息？"
                    onConfirm={() => handleDelete(msg.id)}
                  >
                    <Button type="text" danger icon={<DeleteOutlined />} />
                  </Popconfirm>,
                ].filter(Boolean)}
              >
                <List.Item.Meta
                  avatar={
                    <Badge dot={!msg.read}>
                      <Avatar
                        style={{ backgroundColor: levelColors[msg.level] }}
                        icon={getIcon(msg.type)}
                      />
                    </Badge>
                  }
                  title={
                    <Space>
                      <Text strong={!msg.read}>{msg.title}</Text>
                      <Tag color={typeColors[msg.type]}>{typeLabels[msg.type]}</Tag>
                      {msg.starred && <StarFilled style={{ color: '#faad14' }} />}
                    </Space>
                  }
                  description={new Date(msg.createdAt).toLocaleString('zh-CN')}
                />
                <Paragraph style={{ marginBottom: 0, marginLeft: 40 }}>
                  {msg.content}
                </Paragraph>
                {msg.actionUrl && (
                  <Button type="link" style={{ marginLeft: 40, padding: 0 }}>
                    {msg.actionText || '查看详情'}
                  </Button>
                )}
              </List.Item>
            )}
          />
        )}
      </Card>
    </div>
  )
}
