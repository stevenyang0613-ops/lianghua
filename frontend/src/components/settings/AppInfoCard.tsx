import React, { useState, useEffect } from 'react'
import { Card, Typography, Space, Button, Tag, Divider, message } from 'antd'
import { ReloadOutlined, SyncOutlined, CloudDownloadOutlined } from '@ant-design/icons'
import { isElectron, getAppInfo, restartBackend, checkForUpdates, onUpdateStatus } from '../../utils/electron'
import type { UpdateStatus } from '../../types/electron'

const { Text } = Typography

export const AppInfoCard = React.memo(function AppInfoCard() {
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null)
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [appInfo, setAppInfo] = useState<{ version: string; platform: string; isDev: boolean } | null>(null)

  useEffect(() => {
    if (isElectron()) {
      getAppInfo().then(info => {
        if (info) setAppInfo(info)
      })
      const unsubscribe = onUpdateStatus((status) => {
        setUpdateStatus(status)
        if (status.status === 'available') {
          message.info(`发现新版本 ${status.version}`)
        } else if (status.status === 'downloaded') {
          message.success(`新版本 ${status.version} 已下载，重启应用以安装`)
        } else if (status.status === 'error') {
          message.error('更新检查失败: ' + status.error)
        }
      })
      return unsubscribe
    }
  }, [])

  const handleRestartBackend = async () => {
    try {
      await restartBackend()
      message.success('后端服务重启中...')
    } catch {
      message.error('重启失败，此功能仅在桌面端可用')
    }
  }

  const handleCheckUpdates = async () => {
    if (!isElectron()) return
    setCheckingUpdate(true)
    try {
      const result = await checkForUpdates()
      if (result.available) {
        message.info(`发现新版本 ${result.version}`)
      } else if (result.error) {
        message.error('检查更新失败: ' + result.error)
      } else {
        message.success('已是最新版本')
      }
    } catch {
      message.error('检查更新失败')
    } finally {
      setCheckingUpdate(false)
    }
  }

  if (!isElectron() || !appInfo) return null

  return (
    <Card title="应用信息" style={{ marginBottom: 16 }} size="small">
      <Space direction="vertical" style={{ width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Text type="secondary">版本</Text>
          <Text code>{appInfo.version}</Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Text type="secondary">平台</Text>
          <Text code>{appInfo.platform}</Text>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Text type="secondary">运行模式</Text>
          <Tag color={appInfo.isDev ? 'orange' : 'green'}>{appInfo.isDev ? '开发模式' : '生产模式'}</Tag>
        </div>
        <Divider style={{ margin: '8px 0' }} />
        <Space style={{ width: '100%' }} direction="vertical">
          <Button icon={<ReloadOutlined />} onClick={handleRestartBackend} block>
            重启后端服务
          </Button>
          <Button
            icon={checkingUpdate ? <SyncOutlined spin /> : <CloudDownloadOutlined />}
            onClick={handleCheckUpdates}
            loading={checkingUpdate}
            block
          >
            检查更新
          </Button>
          {updateStatus && updateStatus.status === 'downloading' && (
            <Text type="secondary" style={{ fontSize: 12, textAlign: 'center', display: 'block' }}>
              下载中... {updateStatus.percent}%
            </Text>
          )}
          {updateStatus && updateStatus.status === 'downloaded' && (
            <Text type="success" style={{ fontSize: 12, textAlign: 'center', display: 'block' }}>
              新版本已就绪，重启应用以安装
            </Text>
          )}
        </Space>
      </Space>
    </Card>
  )
})
