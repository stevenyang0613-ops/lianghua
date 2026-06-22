/**
 * 离线模式指示器组件
 * 在页面顶部显示缓存数据过期时间和状态
 */

import { useEffect, useState } from 'react'
import { Badge, Space, Typography, Tooltip } from 'antd'
import { WifiOutlined, DisconnectOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { getCacheStatus } from '../services/api'

const { Text } = Typography

interface OfflineIndicatorProps {
  style?: React.CSSProperties
}

export default function OfflineIndicator({ style }: OfflineIndicatorProps) {
  const [isOffline, setIsOffline] = useState(() => localStorage.getItem('offline_mode') === 'true')
  const [cacheStatus, setCacheStatus] = useState<{ key: string; status: Awaited<ReturnType<typeof getCacheStatus>> }[]>([])

  useEffect(() => {
    const checkStatus = async () => {
      setIsOffline(localStorage.getItem('offline_mode') === 'true')

      // 检查主要缓存的过期状态
      const mainCaches = ['market_quotes', 'analysis_dual-low-ranking', 'analysis_forced-redemption']
      const statusPromises = mainCaches.map(async key => ({
        key,
        status: await getCacheStatus(key)
      }))
      const statuses = await Promise.all(statusPromises)
      setCacheStatus(statuses)
    }

    checkStatus()
    const interval = setInterval(checkStatus, 30000) // 每30秒检查一次
    return () => clearInterval(interval)
  }, [])

  if (!isOffline) {
    // 在线模式：极简指示器，不占用大量垂直空间
    return (
      <div style={{ ...style, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', padding: '2px 12px', background: 'transparent', borderBottom: 'none' }}>
        <Space size={4}>
          <WifiOutlined style={{ color: '#52c41a', fontSize: 11 }} />
          <Text type="secondary" style={{ fontSize: 11 }}>在线</Text>
        </Space>
      </div>
    )
  }

  // 找到最早过期的缓存
  const oldestCache = cacheStatus
    .filter((c): c is typeof c & { status: NonNullable<typeof c.status> } => !!c.status)
    .sort((a, b) => {
      if (a.status.isExpired && !b.status.isExpired) return -1
      if (!a.status.isExpired && b.status.isExpired) return 1
      return 0
    })[0]

  const hasExpiredCache = cacheStatus.some(c => c.status?.isExpired)

  return (
    <div style={{ ...style, padding: '8px 16px', background: hasExpiredCache ? '#fff2f0' : '#fffbe6', borderBottom: `1px solid ${hasExpiredCache ? '#ffccc7' : '#ffe58f'}` }}>
      <Space split={<Text type="secondary">|</Text>}>
        <Space>
          {hasExpiredCache ? (
            <Badge status="error" />
          ) : (
            <Badge status="warning" />
          )}
          <DisconnectOutlined style={{ color: hasExpiredCache ? '#ff4d4f' : '#faad14' }} />
          <Text type={hasExpiredCache ? 'danger' : 'warning'}>离线模式</Text>
        </Space>

        {oldestCache?.status && (
          <Tooltip title={`缓存: ${oldestCache.key}`}>
            <Space size={4}>
              <ClockCircleOutlined />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {oldestCache.status.isExpired
                  ? oldestCache.status.expiredAgo
                  : `剩余 ${oldestCache.status.remainingTime}`
                }
              </Text>
            </Space>
          </Tooltip>
        )}

        <Text type="secondary" style={{ fontSize: 12 }}>
          上次同步: {localStorage.getItem('cache_time') || '未知'}
        </Text>
      </Space>
    </div>
  )
}
