import React from 'react'
import { Card, Typography, Select } from 'antd'
import { useThemeStore } from '../../stores/useThemeStore'

const { Text } = Typography

export const DisplaySettingsCard = React.memo(function DisplaySettingsCard() {
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)

  return (
    <Card title="显示设置" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Text>主题模式</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>选择浅色或深色主题</Text>
        </div>
        <Select value={mode} onChange={setMode} style={{ width: 120 }}>
          <Select.Option value="light">浅色</Select.Option>
          <Select.Option value="dark">深色</Select.Option>
          <Select.Option value="system">跟随系统</Select.Option>
        </Select>
      </div>
    </Card>
  )
})
