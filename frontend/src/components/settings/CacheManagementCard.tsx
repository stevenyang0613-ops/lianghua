import React, { useState, useEffect } from 'react'
import { Card, Typography, Row, Col, Slider, Space, Button, Popconfirm, Statistic, Divider, message } from 'antd'
import { DeleteOutlined, ClearOutlined, ClockCircleOutlined, DatabaseOutlined } from '@ant-design/icons'
import { getCacheStats, clearAllCache, clearExpiredCache } from '../../utils/dataCache'

const { Text } = Typography

export const CacheManagementCard = React.memo(function CacheManagementCard() {
  const [cacheStats, setCacheStats] = useState<{ count: number; oldestTime: string | null }>({ count: 0, oldestTime: null })
  const [cacheLoading, setCacheLoading] = useState(false)
  const [cacheExpiryHours, setCacheExpiryHours] = useState(() => {
    const saved = localStorage.getItem('cache_expiry_hours')
    return saved ? parseInt(saved, 10) : 24
  })

  useEffect(() => {
    loadCacheStats()
  }, [])

  const loadCacheStats = async () => {
    const stats = await getCacheStats()
    setCacheStats(stats)
  }

  const handleClearAllCache = async () => {
    setCacheLoading(true)
    await clearAllCache()
    await loadCacheStats()
    setCacheLoading(false)
    message.success('缓存已清除')
  }

  const handleClearExpiredCache = async () => {
    setCacheLoading(true)
    await clearExpiredCache()
    await loadCacheStats()
    setCacheLoading(false)
    message.success('过期缓存已清除')
  }

  const handleCacheExpiryChange = (value: number) => {
    setCacheExpiryHours(value)
    localStorage.setItem('cache_expiry_hours', String(value))
    message.success(`缓存过期时间已设置为 ${value} 小时`)
  }

  return (
    <Card title={<span><DatabaseOutlined style={{ marginRight: 8 }} />缓存管理</span>} style={{ marginBottom: 16 }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Statistic
            title="缓存条目"
            value={cacheStats.count}
            suffix="条"
            valueStyle={{ fontSize: 20 }}
          />
        </Col>
        <Col span={12}>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>最早缓存时间</Text>
            <br />
            <Text>{cacheStats.oldestTime || '无缓存'}</Text>
          </div>
        </Col>
      </Row>
      <Divider style={{ margin: '12px 0' }} />
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text><ClockCircleOutlined style={{ marginRight: 4 }} />缓存过期时间</Text>
          <Text type="secondary">{cacheExpiryHours} 小时</Text>
        </div>
        <Slider
          min={1}
          max={168}
          value={cacheExpiryHours}
          onChange={handleCacheExpiryChange}
          marks={{ 1: '1时', 24: '1天', 72: '3天', 168: '7天' }}
        />
      </div>
      <Divider style={{ margin: '12px 0' }} />
      <Space style={{ width: '100%' }}>
        <Button
          icon={<ClearOutlined />}
          size="small"
          onClick={handleClearExpiredCache}
          loading={cacheLoading}
        >
          清除过期缓存
        </Button>
        <Popconfirm
          title="确定清除所有缓存？"
          description="这将删除所有离线数据"
          onConfirm={handleClearAllCache}
        >
          <Button
            icon={<DeleteOutlined />}
            size="small"
            danger
            loading={cacheLoading}
          >
            清除全部缓存
          </Button>
        </Popconfirm>
      </Space>
    </Card>
  )
})
