import { Modal, Table, Typography, Divider, Tag } from 'antd'
import { isElectron } from '../utils/electron'

const { Text, Title } = Typography

interface ShortcutHelpProps {
  visible: boolean
  onClose: () => void
}

const shortcuts = [
  { category: '页面导航', keys: [
    { key: 'Cmd/Ctrl + 1', action: '首页' },
    { key: 'Cmd/Ctrl + 2', action: '市场行情' },
    { key: 'Cmd/Ctrl + 3', action: '交易策略' },
    { key: 'Cmd/Ctrl + 4', action: '回测分析' },
    { key: 'Cmd/Ctrl + 5', action: '交易终端' },
    { key: 'Cmd/Ctrl + 6', action: '信号监控' },
  ]},
  { category: '常用操作', keys: [
    { key: 'Cmd/Ctrl + R', action: '刷新数据' },
    { key: 'Cmd/Ctrl + E', action: '导出报告' },
    { key: 'Cmd/Ctrl + D', action: '自选股' },
    { key: 'Cmd/Ctrl + P', action: '盈亏分析' },
    { key: 'Cmd/Ctrl + ,', action: '打开设置' },
  ]},
  { category: '窗口控制', keys: [
    { key: 'Cmd/Ctrl + W', action: '关闭窗口（隐藏到托盘）' },
    { key: 'Cmd/Ctrl + M', action: '最小化窗口' },
    { key: 'Cmd/Ctrl + Q', action: '退出应用' },
    { key: 'F11', action: '全屏切换' },
    { key: 'F12', action: '开发者工具' },
  ]},
  { category: '视图控制', keys: [
    { key: 'Cmd/Ctrl + 0', action: '重置缩放' },
    { key: 'Cmd/Ctrl + +', action: '放大' },
    { key: 'Cmd/Ctrl + -', action: '缩小' },
  ]},
  { category: '全局快捷键', keys: [
    { key: 'Alt + Cmd/Ctrl + L', action: '显示/隐藏窗口' },
    { key: 'Cmd/Ctrl + Shift + R', action: '快速刷新' },
  ]},
]

export default function ShortcutHelp({ visible, onClose }: ShortcutHelpProps) {
  const columns = [
    {
      title: '快捷键',
      dataIndex: 'key',
      key: 'key',
      width: 180,
      render: (key: string) => (
        <Tag style={{ fontFamily: 'monospace', fontSize: 12 }}>{key}</Tag>
      ),
    },
    {
      title: '功能',
      dataIndex: 'action',
      key: 'action',
    },
  ]

  return (
    <Modal
      title="快捷键帮助"
      open={visible}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      {!isElectron() && (
        <Text type="warning" style={{ display: 'block', marginBottom: 16 }}>
          部分快捷键仅在桌面端应用中生效
        </Text>
      )}

      {shortcuts.map((group) => (
        <div key={group.category} style={{ marginBottom: 16 }}>
          <Title level={5} style={{ marginBottom: 8 }}>{group.category}</Title>
          <Table
            dataSource={group.keys}
            columns={columns}
            size="small"
            pagination={false}
            showHeader={false}
            rowKey="key"
          />
        </div>
      ))}

      <Divider />
      <Text type="secondary" style={{ fontSize: 12 }}>
        提示：Mac 用户使用 Cmd 键，Windows/Linux 用户使用 Ctrl 键
      </Text>
    </Modal>
  )
}
