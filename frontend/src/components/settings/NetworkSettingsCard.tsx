import React, { useState } from 'react'
import { Card, Typography, Switch, Divider, Button, Slider, message } from 'antd'
import { WifiOutlined, DisconnectOutlined, SyncOutlined } from '@ant-design/icons'
import {
  startBackgroundSync,
  stopBackgroundSync,
  triggerManualSync,
  getSyncInterval,
  setSyncInterval,
} from '../../utils/backgroundSync'

const { Text } = Typography

interface NetworkSettingsCardProps {
  onSyncComplete: (syncTime: number) => void
}

export const NetworkSettingsCard = React.memo(function NetworkSettingsCard({ onSyncComplete }: NetworkSettingsCardProps) {
  const [offlineMode, setOfflineMode] = useState(() => localStorage.getItem('offline_mode') === 'true')
  const [autoSync, setAutoSync] = useState(() => localStorage.getItem('auto_sync') === 'true')
  const [syncing, setSyncing] = useState(false)
  const [syncIntervalMin, setSyncIntervalMin] = useState(() => getSyncInterval() / 60000)

  const toggleOfflineMode = (checked: boolean) => {
    setOfflineMode(checked)
    localStorage.setItem('offline_mode', String(checked))
    message.success(checked ? '已启用离线模式，将使用缓存数据' : '已切换到在线模式')
  }

  const toggleAutoSync = (checked: boolean) => {
    setAutoSync(checked)
    localStorage.setItem('auto_sync', String(checked))
    if (checked) {
      startBackgroundSync()
    } else {
      stopBackgroundSync()
    }
    message.success(checked ? '已开启自动同步' : '已关闭自动同步')
  }

  const handleSyncIntervalChange = (value: number) => {
    setSyncIntervalMin(value)
    setSyncInterval(value * 60 * 1000)
  }

  const handleSyncData = async () => {
    if (offlineMode) {
      message.warning('离线模式下无法同步数据')
      return
    }
    setSyncing(true)
    const startTime = Date.now()
    try {
      await triggerManualSync()
      const syncTime = Date.now() - startTime
      onSyncComplete(syncTime)
      message.success(`数据同步成功，耗时 ${syncTime}ms`)
    } catch (err) {
      message.error('同步失败: ' + String(err))
    } finally {
      setSyncing(false)
    }
  }

  return (
    <Card title={<span>{offlineMode ? <DisconnectOutlined style={{ marginRight: 8 }} /> : <WifiOutlined style={{ marginRight: 8 }} />}网络设置</span>} style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text>离线模式</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>启用后使用缓存数据，不请求实时数据</Text>
        </div>
        <Switch
          checked={offlineMode}
          onChange={toggleOfflineMode}
          checkedChildren="离线"
          unCheckedChildren="在线"
        />
      </div>
      {offlineMode && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text type="warning" style={{ fontSize: 12 }}>
            离线模式下，行情数据可能不是最新的。上次缓存时间：{localStorage.getItem('cache_time') || '无缓存'}
          </Text>
        </>
      )}
      <Divider style={{ margin: '12px 0' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text>自动后台同步</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>定期同步数据保持缓存新鲜度</Text>
        </div>
        <Switch
          checked={autoSync}
          onChange={toggleAutoSync}
          checkedChildren="开启"
          unCheckedChildren="关闭"
        />
      </div>
      {autoSync && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <Text>同步间隔</Text>
              <Text type="secondary">{syncIntervalMin} 分钟</Text>
            </div>
            <Slider
              min={1}
              max={30}
              value={syncIntervalMin}
              onChange={handleSyncIntervalChange}
              marks={{ 1: '1分', 5: '5分', 10: '10分', 15: '15分', 30: '30分' }}
            />
          </div>
        </>
      )}
      <Divider style={{ margin: '12px 0' }} />
      <Button
        icon={syncing ? <SyncOutlined spin /> : <SyncOutlined />}
        onClick={handleSyncData}
        loading={syncing}
        disabled={offlineMode}
        block
      >
        立即同步数据
      </Button>
    </Card>
  )
})
