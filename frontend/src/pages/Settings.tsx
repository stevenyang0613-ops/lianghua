import { useEffect, useState } from 'react'
import { Card, Typography, Space, Button, Modal, Input, List, Avatar, Popconfirm, message, Select, Tag, InputNumber } from 'antd'
import { UserOutlined, PlusOutlined, DeleteOutlined, CheckOutlined } from '@ant-design/icons'
import { useUserStore, type User } from '../stores/useUserStore'
import { useThemeStore } from '../stores/useThemeStore'
import { requestNotificationPermission, getNotificationPermission } from '../utils/notification'

const { Title, Text } = Typography

export default function Settings() {
  const { users, currentUser, createUser, deleteUser, switchUser } = useUserStore()
  const { mode, setMode } = useThemeStore()
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [newUserName, setNewUserName] = useState('')
  const [notificationEnabled, setNotificationEnabled] = useState(getNotificationPermission() === 'granted')
  const [minConfidence, setMinConfidence] = useState(() => Number(localStorage.getItem('signal_min_confidence') || '0'))
  const [maxSignals, setMaxSignals] = useState(() => Number(localStorage.getItem('signal_max_signals') || '20'))

  useEffect(() => {
    setNotificationEnabled(getNotificationPermission() === 'granted')
  }, [])

  const handleCreateUser = () => {
    if (!newUserName.trim()) {
      message.warning('请输入用户名')
      return
    }
    createUser(newUserName.trim())
    setNewUserName('')
    setCreateModalVisible(false)
    message.success('用户已创建')
  }

  const handleEnableNotification = async () => {
    const permission = await requestNotificationPermission()
    setNotificationEnabled(permission === 'granted')
    if (permission === 'granted') {
      message.success('已开启浏览器通知')
    }
  }

  const handleDeleteUser = (userId: string) => {
    if (users.length === 1) {
      message.warning('至少保留一个用户')
      return
    }
    deleteUser(userId)
    message.success('用户已删除')
  }

  return (
    <div style={{ padding: 16, maxWidth: 800, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 24 }}>系统设置</Title>

      <Card title="用户管理" style={{ marginBottom: 16 }}>
        <List
          dataSource={users}
          renderItem={(user: User) => (
            <List.Item
              actions={[
                currentUser?.id === user.id ? (
                  <Text type="success"><CheckOutlined /> 当前</Text>
                ) : (
                  <Button type="link" size="small" onClick={() => switchUser(user.id)}>
                    切换
                  </Button>
                ),
                users.length > 1 && (
                  <Popconfirm title="确定删除此用户?" onConfirm={() => handleDeleteUser(user.id)}>
                    <Button type="link" danger size="small" icon={<DeleteOutlined />} />
                  </Popconfirm>
                ),
              ].filter(Boolean)}
            >
              <List.Item.Meta
                avatar={<Avatar icon={<UserOutlined />} style={{ backgroundColor: currentUser?.id === user.id ? '#1890ff' : '#87d068' }} />}
                title={user.name}
                description={`创建于 ${new Date(user.createdAt).toLocaleDateString()}`}
              />
            </List.Item>
          )}
        />
        <Button type="dashed" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)} style={{ width: '100%', marginTop: 12 }}>
          添加用户
        </Button>
      </Card>

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

      <Card title="信号配置" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <Text>最小置信度阈值</Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>低于此值的信号不显示 (0.0 ~ 1.0)</Text>
          </div>
          <InputNumber min={0} max={1} step={0.05} value={minConfidence} onChange={v => { const val = v ?? 0; setMinConfidence(val); localStorage.setItem('signal_min_confidence', String(val)) }} style={{ width: 120 }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <Text>最大信号数量</Text>
            <br />
            <Text type="secondary" style={{ fontSize: 12 }}>单次刷新显示的最大信号数</Text>
          </div>
          <InputNumber min={5} max={100} step={5} value={maxSignals} onChange={v => { const val = v ?? 20; setMaxSignals(val); localStorage.setItem('signal_max_signals', String(val)) }} style={{ width: 120 }} />
        </div>
      </Card>

      <Card title="通知设置">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
      </Card>

      <Modal
        title="创建新用户"
        open={createModalVisible}
        onOk={handleCreateUser}
        onCancel={() => setCreateModalVisible(false)}
        okText="创建"
        cancelText="取消"
      >
        <Input
          placeholder="请输入用户名"
          value={newUserName}
          onChange={(e) => setNewUserName(e.target.value)}
          onPressEnter={handleCreateUser}
          prefix={<UserOutlined />}
          style={{ marginTop: 12 }}
        />
      </Modal>
    </div>
  )
}
