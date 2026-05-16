import React, { useState } from 'react'
import { Card, Typography, Switch, Button, Tag, Divider, message } from 'antd'
import { requestNotificationPermission, getNotificationPermission, notificationService } from '../../utils/notifications'

const { Text } = Typography

export const NotificationSettingsCard = React.memo(function NotificationSettingsCard() {
  const [notificationEnabled, setNotificationEnabled] = useState(getNotificationPermission() === 'granted')
  const [notificationSoundEnabled, setNotificationSoundEnabled] = useState(() => {
    const saved = localStorage.getItem('notification_settings')
    return saved ? JSON.parse(saved).audioEnabled ?? true : true
  })

  const handleEnableNotification = async () => {
    const permission = await requestNotificationPermission()
    setNotificationEnabled(permission === 'granted')
    if (permission === 'granted') {
      message.success('已开启浏览器通知')
    }
  }

  return (
    <Card title="通知设置" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Text>浏览器通知</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>告警触发时发送浏览器推送通知</Text>
        </div>
        {notificationEnabled ? (
          <Tag color="success">已开启</Tag>
        ) : (
          <Button type="primary" size="small" onClick={handleEnableNotification}>
            开启通知
          </Button>
        )}
      </div>
      <Divider style={{ margin: '12px 0' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text>通知声音</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>收到通知时播放提示音</Text>
        </div>
        <Switch
          checked={notificationSoundEnabled}
          onChange={(checked) => {
            setNotificationSoundEnabled(checked)
            notificationService.setAudioEnabled(checked)
          }}
          checkedChildren="开启"
          unCheckedChildren="关闭"
        />
      </div>
    </Card>
  )
})
