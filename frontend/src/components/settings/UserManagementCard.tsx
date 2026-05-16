import React, { useState } from 'react'
import { Card, Typography, List, Avatar, Button, Popconfirm, Modal, Input, message } from 'antd'
import { UserOutlined, PlusOutlined, DeleteOutlined, CheckOutlined } from '@ant-design/icons'
import { useUserStore, type User } from '../../stores/useUserStore'

const { Text } = Typography

export const UserManagementCard = React.memo(function UserManagementCard() {
  const users = useUserStore((s) => s.users)
  const currentUser = useUserStore((s) => s.currentUser)
  const createUser = useUserStore((s) => s.createUser)
  const deleteUser = useUserStore((s) => s.deleteUser)
  const switchUser = useUserStore((s) => s.switchUser)

  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [newUserName, setNewUserName] = useState('')

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

  const handleDeleteUser = (userId: string) => {
    if (users.length === 1) {
      message.warning('至少保留一个用户')
      return
    }
    deleteUser(userId)
    message.success('用户已删除')
  }

  return (
    <>
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
    </>
  )
})
