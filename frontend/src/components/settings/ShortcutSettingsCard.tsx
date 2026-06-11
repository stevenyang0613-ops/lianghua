import React, { useState } from 'react'
import { Card, Typography, List, Button, Space, Tooltip, Tag, message } from 'antd'
import { KeyOutlined, QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { isElectron } from '../../utils/electron'
import { useShortcutStore, shortcutLabels, type ShortcutConfig } from '../../stores/useShortcutStore'
import ShortcutHelp from '../ShortcutHelp'

const { Text } = Typography

export const ShortcutSettingsCard = React.memo(function ShortcutSettingsCard() {
  const shortcuts = useShortcutStore((s) => s.shortcuts)
  const resetToDefaults = useShortcutStore((s) => s.resetToDefaults)
  const [shortcutHelpVisible, setShortcutHelpVisible] = useState(false)

  if (!isElectron()) return null

  return (
    <>
      <Card title={<span><KeyOutlined /> 快捷键设置</span>} style={{ marginBottom: 16 }}>
        <List
          dataSource={Object.entries(shortcutLabels).map(([key, label]) => ({
            action: key as keyof ShortcutConfig,
            label,
            shortcut: shortcuts[key as keyof ShortcutConfig],
          }))}
          size="small"
          renderItem={(item) => (
            <List.Item
              actions={[
                <Tooltip title="当前快捷键" key="shortcut">
                  <Tag style={{ fontFamily: 'monospace', cursor: 'pointer' }}>{item.shortcut}</Tag>
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={item.label}
                description={item.action}
              />
            </List.Item>
          )}
        />
        <Space style={{ marginTop: 8, width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>快捷键仅在桌面端应用内生效</Text>
          <Space>
            <Button icon={<QuestionCircleOutlined />} size="small" onClick={() => setShortcutHelpVisible(true)}>
              查看所有快捷键
            </Button>
            <Button icon={<ReloadOutlined />} size="small" onClick={() => { resetToDefaults(); message.success('已恢复默认快捷键') }}>
              恢复默认
            </Button>
          </Space>
        </Space>
      </Card>

      <ShortcutHelp visible={shortcutHelpVisible} onClose={() => setShortcutHelpVisible(false)} />
    </>
  )
})
