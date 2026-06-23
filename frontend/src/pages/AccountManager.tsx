/**
 * 账户管理页面
 */

import { useState } from 'react'
import { Card, Table, Button, Space, Modal, Form, Input, Select, Tag, Typography, Row, Col, Statistic, Popconfirm, Empty, Descriptions, Divider, message } from 'antd'
import { PlusOutlined, DeleteOutlined, EditOutlined, SyncOutlined, BankOutlined } from '@ant-design/icons'
import { useAccountStore, BROKERS, type BrokerAccount, type Position } from '../stores/useAccountStore'
import type { ColumnsType } from 'antd/es/table'

const { Title, Text } = Typography

export default function AccountManager() {
  const {
    accounts,
    currentAccountId,
    isLoading,
    addAccount,
    removeAccount,
    updateAccount,
    setCurrentAccount,
    syncAccount,
    syncAllAccounts,
  } = useAccountStore()

  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingAccount, setEditingAccount] = useState<BrokerAccount | null>(null)
  const [form] = Form.useForm()

  const currentAccount = accounts.find((a) => a.id === currentAccountId)

  const handleCreate = () => {
    form.validateFields().then((values) => {
      addAccount({
        name: values.name,
        broker: values.broker,
        type: values.type,
        accountId: values.accountId,
        balance: 1000000,
        available: 1000000,
        frozen: 0,
        marketValue: 0,
        totalProfit: 0,
        todayProfit: 0,
        positions: [],
      })
      setCreateModalVisible(false)
      form.resetFields()
      message.success('账户添加成功')
    })
  }

  const handleEdit = () => {
    if (!editingAccount) return
    form.validateFields().then((values) => {
      updateAccount(editingAccount.id, {
        name: values.name,
        broker: values.broker,
        accountId: values.accountId,
      })
      setEditModalVisible(false)
      setEditingAccount(null)
      form.resetFields()
      message.success('账户更新成功')
    })
  }

  const handleDelete = (id: string) => {
    removeAccount(id)
    message.success('账户已删除')
  }

  const positionColumns: ColumnsType<Position> = [
    { title: '代码', dataIndex: 'code', width: 80 },
    { title: '名称', dataIndex: 'name', width: 100 },
    { title: '持仓', dataIndex: 'volume', width: 80 },
    { title: '可用', dataIndex: 'available', width: 80 },
    { title: '成本', dataIndex: 'costPrice', width: 80, render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '现价', dataIndex: 'currentPrice', width: 80, render: (v: number) => v != null ? v.toFixed(2) : '-' },
    { title: '市值', dataIndex: 'marketValue', width: 100, render: (v: number) => v != null ? v.toLocaleString() : '-' },
    {
      title: '盈亏',
      dataIndex: 'profitPct',
      width: 80,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) : '-'}%
        </Text>
      ),
    },
  ]

  const accountColumns: ColumnsType<BrokerAccount> = [
    {
      title: '账户名称',
      dataIndex: 'name',
      width: 150,
      render: (name: string, record) => (
        <Space>
          <BankOutlined />
          <a onClick={() => setCurrentAccount(record.id)}>{name}</a>
          {currentAccountId === record.id && <Tag color="blue">当前</Tag>}
        </Space>
      ),
    },
    {
      title: '券商',
      dataIndex: 'broker',
      width: 120,
      render: (broker: string) => BROKERS.find((b) => b.value === broker)?.label || broker,
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 80,
      render: (type: string) => (
        <Tag color={type === 'real' ? 'green' : 'orange'}>
          {type === 'real' ? '实盘' : '模拟'}
        </Tag>
      ),
    },
    {
      title: '总资产',
      dataIndex: 'balance',
      width: 120,
      render: (v: number, record) => {
        const balance = v ?? 0
        const mv = record.marketValue ?? 0
        return `¥${(balance + mv).toLocaleString()}`
      },
    },
    {
      title: '可用资金',
      dataIndex: 'available',
      width: 120,
      render: (v: number) => `¥${v == null ? '-' : v.toLocaleString()}`,
    },
    {
      title: '市值',
      dataIndex: 'marketValue',
      width: 120,
      render: (v: number) => `¥${v == null ? '-' : v.toLocaleString()}`,
    },
    {
      title: '今日盈亏',
      dataIndex: 'todayProfit',
      width: 100,
      render: (v: number) => (
        <Text style={{ color: v == null ? undefined : (v >= 0 ? '#52c41a' : '#ff4d4f') }}>
          {v == null ? '-' : (v >= 0 ? '+' : '')}¥{v == null ? '-' : v.toLocaleString()}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (status: string) => (
        <Tag color={status === 'active' ? 'success' : status === 'error' ? 'error' : 'default'}>
          {status === 'active' ? '正常' : status === 'error' ? '异常' : '未连接'}
        </Tag>
      ),
    },
    {
      title: '最后同步',
      dataIndex: 'lastSync',
      width: 150,
      render: (v: number | null) => (v ? new Date(v).toLocaleString('zh-CN') : '未同步'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<SyncOutlined />}
            onClick={() => syncAccount(record.id)}
            loading={isLoading}
          >
            同步
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditingAccount(record)
              form.setFieldsValue(record)
              setEditModalVisible(true)
            }}
          >
            编辑
          </Button>
          <Popconfirm title="确定删除此账户？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><BankOutlined style={{ marginRight: 8 }} />账户管理</Title>

      {/* 总览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="账户总数"
              value={accounts.length}
              suffix="个"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总资产"
              value={accounts.reduce((sum, a) => sum + a.balance + a.marketValue, 0)}
              precision={2}
              prefix="¥"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总市值"
              value={accounts.reduce((sum, a) => sum + a.marketValue, 0)}
              precision={2}
              prefix="¥"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日总盈亏"
              value={accounts.reduce((sum, a) => sum + a.todayProfit, 0)}
              precision={2}
              prefix="¥"
              valueStyle={{ color: accounts.reduce((sum, a) => sum + a.todayProfit, 0) >= 0 ? '#52c41a' : '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 账户列表 */}
      <Card
        title="账户列表"
        extra={
          <Space>
            <Button icon={<SyncOutlined />} onClick={() => syncAllAccounts()} loading={isLoading}>
              同步全部
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
              添加账户
            </Button>
          </Space>
        }
      >
        {accounts.length === 0 ? (
          <Empty description="暂无账户，请添加账户" />
        ) : (
          <Table
            dataSource={accounts}
            columns={accountColumns}
            rowKey="id"
            pagination={false}
            size="small"
            scroll={{ x: 1300 }}
          />
        )}
      </Card>

      {/* 当前账户详情 */}
      {currentAccount && (
        <Card title={`账户详情: ${currentAccount.name}`} style={{ marginTop: 16 }}>
          <Descriptions column={4}>
            <Descriptions.Item label="账户ID">{currentAccount.accountId}</Descriptions.Item>
            <Descriptions.Item label="券商">{BROKERS.find((b) => b.value === currentAccount.broker)?.label}</Descriptions.Item>
            <Descriptions.Item label="类型">
              <Tag color={currentAccount.type === 'real' ? 'green' : 'orange'}>
                {currentAccount.type === 'real' ? '实盘' : '模拟'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {new Date(currentAccount.createdAt).toLocaleDateString()}
            </Descriptions.Item>
          </Descriptions>

          <Divider />

          <Title level={5}>持仓明细</Title>
          {currentAccount.positions.length === 0 ? (
            <Empty description="暂无持仓" />
          ) : (
            <Table
              dataSource={currentAccount.positions}
              columns={positionColumns}
              rowKey="code"
              pagination={false}
              size="small"
            />
          )}
        </Card>
      )}

      {/* 创建账户弹窗 */}
      <Modal
        title="添加账户"
        open={createModalVisible}
        onOk={handleCreate}
        onCancel={() => {
          setCreateModalVisible(false)
          form.resetFields()
        }}
        okText="添加"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="账户名称" rules={[{ required: true, message: '请输入账户名称' }]}>
            <Input placeholder="例如：主力账户" />
          </Form.Item>
          <Form.Item name="broker" label="券商" rules={[{ required: true, message: '请选择券商' }]}>
            <Select options={BROKERS} placeholder="选择券商" />
          </Form.Item>
          <Form.Item name="type" label="账户类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'real', label: '实盘账户' },
                { value: 'simulate', label: '模拟账户' },
              ]}
            />
          </Form.Item>
          <Form.Item name="accountId" label="资金账号" rules={[{ required: true, message: '请输入资金账号' }]}>
            <Input placeholder="资金账号" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑账户弹窗 */}
      <Modal
        title="编辑账户"
        open={editModalVisible}
        onOk={handleEdit}
        onCancel={() => {
          setEditModalVisible(false)
          setEditingAccount(null)
          form.resetFields()
        }}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="账户名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="broker" label="券商" rules={[{ required: true }]}>
            <Select options={BROKERS} />
          </Form.Item>
          <Form.Item name="accountId" label="资金账号" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
