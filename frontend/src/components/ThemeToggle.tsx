import { Button, Dropdown, type MenuProps } from 'antd'
import { SunOutlined, MoonOutlined, DesktopOutlined } from '@ant-design/icons'
import { useThemeStore } from '../stores/useThemeStore'

const themeOptions = [
  { key: 'light', label: '浅色', icon: <SunOutlined /> },
  { key: 'dark', label: '深色', icon: <MoonOutlined /> },
  { key: 'system', label: '跟随系统', icon: <DesktopOutlined /> },
]

export default function ThemeToggle() {
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)

  const currentOption = themeOptions.find((o) => o.key === mode) || themeOptions[2]

  const items: MenuProps['items'] = themeOptions.map((opt) => ({
    key: opt.key,
    label: opt.label,
    icon: opt.icon,
    onClick: () => setMode(opt.key as 'light' | 'dark' | 'system'),
  }))

  return (
    <Dropdown menu={{ items, selectedKeys: [mode] }} trigger={['click']}>
      <Button icon={currentOption.icon} />
    </Dropdown>
  )
}
