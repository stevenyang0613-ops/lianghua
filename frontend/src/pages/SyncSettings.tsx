/**
 * 同步设置页面
 * 支持云端同步、数据导入导出
 */

import { useEffect, useState } from 'react'
import { Card, Button, Space, Typography, Row, Col, Statistic, Alert, Divider, Upload, message, Modal, Switch, Input, List, Tag, Descriptions, Empty } from 'antd'
import { CloudSyncOutlined, CloudUploadOutlined, CloudDownloadOutlined, ExportOutlined, ImportOutlined, SyncOutlined, HistoryOutlined, DeleteOutlined } from '@ant-design/icons'
import { uploadToCloud, downloadFromCloud, fullSync, getSyncStatus, exportData, importData, type SyncResult } from '../utils/cloudSync'
import { getNotificationSettings, updateNotificationSettings, requestNotificationPermission, getNotificationHistory, clearNotificationHistory, type NotificationSettings } from '../utils/desktopNotifications'

const { Title, Text, Paragraph } = Typography

export default function SyncSettings() {
  const [syncing, setSyncing] = useState(false)
  const [syncStatus, setSyncStatus] = useState<ReturnType<typeof getSyncStatus> | null>(null)
  const [lastResult, setLastResult] = useState<SyncResult | null>(null)
  const [notificationSettings, setNotificationSettingsState] = useState<NotificationSettings | null>(null)
  const [historyVisible, setHistoryVisible] = useState(false)

  useEffect(() => {
    loadSyncStatus()
    loadNotificationSettings()
  }, [])

  const loadSyncStatus = () => {
    setSyncStatus(getSyncStatus())
  }

  const loadNotificationSettings = () => {
    setNotificationSettingsState(getNotificationSettings())
  }

  const handleUpload = async () => {
    setSyncing(true)
    setLastResult(null)

    try {
      const result = await uploadToCloud()
      setLastResult(result)
      if (result.success) {
        message.success(result.message)
        loadSyncStatus()
      } else {
        message.error(result.message)
      }
    } finally {
      setSyncing(false)
    }
  }

  const handleDownload = async () => {
    setSyncing(true)
    setLastResult(null)

    try {
      const result = await downloadFromCloud()
      setLastResult(result)
      if (result.success) {
        message.success(result.message)
        loadSyncStatus()
        // 通知页面刷新
        window.dispatchEvent(new CustomEvent('settings-changed'))
      } else {
        message.error(result.message)
      }
    } finally {
      setSyncing(false)
    }
  }

  const handleFullSync = async () => {
    setSyncing(true)
    setLastResult(null)

    try {
      const result = await fullSync()
      setLastResult(result)
      if (result.success) {
        message.success(result.message)
        loadSyncStatus()
        window.dispatchEvent(new CustomEvent('settings-changed'))
      } else {
        message.error(result.message)
      }
    } finally {
      setSyncing(false)
    }
  }

  const handleExport = () => {
    exportData()
    message.success('数据已导出')
  }

  const handleImport = async (file: File) => {
    const result = await importData(file)
    setLastResult(result)

    if (result.success) {
      message.success(result.message)
      loadSyncStatus()
      window.dispatchEvent(new CustomEvent('settings-changed'))
    } else {
      message.error(result.message)
    }

    return false
  }

  const handleNotificationChange = (key: keyof NotificationSettings, value: boolean | string | object) => {
    if (!notificationSettings) return
    updateNotificationSettings({ [key]: value })
    loadNotificationSettings()
  }

  const handleRequestPermission = async () => {
    const granted = await requestNotificationPermission()
    if (granted) {
      message.success('通知权限已获取')
    } else {
      message.error('通知权限被拒绝')
    }
  }

  const notificationHistory = getNotificationHistory()

  return (
    <div style={{ padding: 16, maxWidth: 1000, margin: '0 auto' }}>
      <Title level={4}>
        <CloudSyncOutlined style={{ marginRight: 8 }} />
        数据同步与通知
      </Title>

      <Row gutter={16}>
        <Col span={16}>
          {/* 云端同步 */}
          <Card title="云端同步" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Alert
                message="数据同步功能"
                description="将您的设置、自选股、快捷键等数据同步到云端，实现多设备数据一致。"
                type="info"
                showIcon
              />

              <Row gutter={16}>
                <Col span={8}>
                  <Button
                    type="primary"
                    icon={<CloudUploadOutlined />}
                    onClick={handleUpload}
                    loading={syncing}
                    block
                  >
                    上传到云端
                  </Button>
                </Col>
                <Col span={8}>
                  <Button
                    icon={<CloudDownloadOutlined />}
                    onClick={handleDownload}
                    loading={syncing}
                    block
                  >
                    从云端下载
                  </Button>
                </Col>
                <Col span={8}>
                  <Button
                    icon={<SyncOutlined />}
                    onClick={handleFullSync}
                    loading={syncing}
                    block
                  >
                    完整同步
                  </Button>
                </Col>
              </Row>

              {lastResult && (
                <Alert
                  message={lastResult.success ? '同步成功' : '同步失败'}
                  description={lastResult.message}
                  type={lastResult.success ? 'success' : 'error'}
                  showIcon
                />
              )}
            </Space>
          </Card>

          {/* 本地备份 */}
          <Card title="本地备份" style={{ marginBottom: 16 }}>
            <Space>
              <Button icon={<ExportOutlined />} onClick={handleExport}>
                导出数据
              </Button>
              <Upload
                accept=".json"
                beforeUpload={handleImport}
                showUploadList={false}
              >
                <Button icon={<ImportOutlined />}>导入数据</Button>
              </Upload>
            </Space>
            <Paragraph type="secondary" style={{ marginTop: 8 }}>
              导出的数据文件可用于备份或迁移到其他设备
            </Paragraph>
          </Card>

          {/* 通知设置 */}
          <Card title="桌面通知" extra={<Button size="small" onClick={handleRequestPermission}>请求权限</Button>}>
            {notificationSettings && (
              <Space direction="vertical" style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>启用桌面通知</Text>
                  <Switch
                    checked={notificationSettings.enabled}
                    onChange={(checked) => handleNotificationChange('enabled', checked)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>播放提示音</Text>
                  <Switch
                    checked={notificationSettings.sound}
                    onChange={(checked) => handleNotificationChange('sound', checked)}
                  />
                </div>

                <Divider orientation="left">通知类型</Divider>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>交易通知</Text>
                  <Switch
                    checked={notificationSettings.trade}
                    onChange={(checked) => handleNotificationChange('trade', checked)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>信号通知</Text>
                  <Switch
                    checked={notificationSettings.signal}
                    onChange={(checked) => handleNotificationChange('signal', checked)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>预警通知</Text>
                  <Switch
                    checked={notificationSettings.alert}
                    onChange={(checked) => handleNotificationChange('alert', checked)}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>系统通知</Text>
                  <Switch
                    checked={notificationSettings.system}
                    onChange={(checked) => handleNotificationChange('system', checked)}
                  />
                </div>

                <Divider orientation="left">静默时段</Divider>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text>启用静默时段</Text>
                  <Switch
                    checked={notificationSettings.quietHours.enabled}
                    onChange={(checked) => handleNotificationChange('quietHours', { ...notificationSettings.quietHours, enabled: checked })}
                  />
                </div>
                {notificationSettings.quietHours.enabled && (
                  <Row gutter={16}>
                    <Col span={12}>
                      <Text>开始时间</Text>
                      <Input
                        type="time"
                        value={notificationSettings.quietHours.start}
                        onChange={(e) => handleNotificationChange('quietHours', { ...notificationSettings.quietHours, start: e.target.value })}
                      />
                    </Col>
                    <Col span={12}>
                      <Text>结束时间</Text>
                      <Input
                        type="time"
                        value={notificationSettings.quietHours.end}
                        onChange={(e) => handleNotificationChange('quietHours', { ...notificationSettings.quietHours, end: e.target.value })}
                      />
                    </Col>
                  </Row>
                )}

                <Button icon={<HistoryOutlined />} onClick={() => setHistoryVisible(true)}>
                  查看通知历史
                </Button>
              </Space>
            )}
          </Card>
        </Col>

        <Col span={8}>
          {/* 同步状态 */}
          <Card title="同步状态" style={{ marginBottom: 16 }}>
            {syncStatus ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="设备ID">
                  <Text code style={{ fontSize: 10 }}>{syncStatus.deviceId.slice(0, 20)}...</Text>
                </Descriptions.Item>
                <Descriptions.Item label="上次同步">
                  {syncStatus.lastSyncTime || '从未同步'}
                </Descriptions.Item>
                <Descriptions.Item label="本地更改">
                  {syncStatus.hasLocalChanges ? (
                    <Tag color="orange">有待同步更改</Tag>
                  ) : (
                    <Tag color="green">已同步</Tag>
                  )}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description="加载中..." />
            )}
          </Card>

          {/* 统计 */}
          <Card title="数据统计">
            <Row gutter={[0, 16]}>
              <Col span={24}>
                <Statistic title="自选股数量" value={(() => { try { return JSON.parse(localStorage.getItem('watchlist') || '[]').length } catch { return 0 } })()} />
              </Col>
              <Col span={24}>
                <Statistic title="通知历史" value={notificationHistory.length} suffix="条" />
              </Col>
              <Col span={24}>
                <Statistic title="自定义主题" value={(() => { try { return JSON.parse(localStorage.getItem('lianghua_custom_themes') || '[]').length } catch { return 0 } })()} suffix="个" />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* 通知历史弹窗 */}
      <Modal
        title="通知历史"
        open={historyVisible}
        onCancel={() => setHistoryVisible(false)}
        footer={[
          <Button key="clear" danger icon={<DeleteOutlined />} onClick={() => { clearNotificationHistory(); loadNotificationSettings(); }}>
            清空历史
          </Button>,
          <Button key="close" onClick={() => setHistoryVisible(false)}>
            关闭
          </Button>,
        ]}
        width={600}
      >
        <List
          dataSource={notificationHistory.slice(0, 50)}
          renderItem={(item: { title: string; body: string; timestamp: number }) => (
            <List.Item>
              <List.Item.Meta
                title={item.title}
                description={
                  <Space direction="vertical" size={0}>
                    <Text>{item.body}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {new Date(item.timestamp).toLocaleString('zh-CN')}
                    </Text>
                  </Space>
                }
              />
            </List.Item>
          )}
          locale={{ emptyText: '暂无通知记录' }}
        />
      </Modal>
    </div>
  )
}
