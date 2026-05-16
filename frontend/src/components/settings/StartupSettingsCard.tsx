import React, { useState } from 'react'
import { Card, Typography, Switch, message } from 'antd'
import { RocketOutlined } from '@ant-design/icons'

const { Text } = Typography

export const StartupSettingsCard = React.memo(function StartupSettingsCard() {
  const [preloadData, setPreloadData] = useState(() => localStorage.getItem('preload_data') === 'true')

  const togglePreloadData = (checked: boolean) => {
    setPreloadData(checked)
    localStorage.setItem('preload_data', String(checked))
    message.success(checked ? '已开启启动预加载' : '已关闭启动预加载')
  }

  return (
    <Card title={<span><RocketOutlined style={{ marginRight: 8 }} />启动设置</span>} style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text>启动预加载数据</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>应用启动时自动加载常用数据到缓存</Text>
        </div>
        <Switch
          checked={preloadData}
          onChange={togglePreloadData}
          checkedChildren="开启"
          unCheckedChildren="关闭"
        />
      </div>
    </Card>
  )
})
