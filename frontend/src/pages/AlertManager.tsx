/**
 * 预警管理页面
 */

import { useEffect, useState } from 'react'
import { Card, Table, Button, Space, Modal, Form, Input, InputNumber, Select, Switch, Tag, Typography, Row, Col, Statistic, Popconfirm, Empty, message } from 'antd'
import { BellOutlined, PlusOutlined, DeleteOutlined, EditOutlined, WarningOutlined, ClearOutlined } from '@ant-design/icons'
import { getAlerts, addAlert, updateAlert, deleteAlert, clearAlerts, clearTriggeredAlerts, getAlertStats, getAlertLabel, ALERT_TYPE_OPTIONS, type PriceAlert } from '../utils/priceAlert'
import type { ColumnsType } from 'antd/es/table'
import { fmt } from '../utils/format'

const { Title } = Typography




export default function AlertManager() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [alerts, setAlerts] = useState<PriceAlert[]>([])
  const [stats, setStats] = useState(getAlertStats())
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingAlert, setEditingAlert] = useState<PriceAlert | null>(null)
  const [form] = Form.useForm()

  const loadData = () => {
    setAlerts(getAlerts())
    setStats(getAlertStats())
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleCreate = () => {
    form.validateFields().then((values) => {
      addAlert({
        code: values.code,
        name: values.name,
        type: values.type,
        target: values.target,
        current: 0,
        expiresAt: values.expiresAt ? Date.now() + values.expiresAt * 24 * 60 * 60 * 1000 : null,
        repeat: values.repeat || false,
        sound: values.sound ?? true,
        notify: values.notify ?? true,
        message: values.message || '',
      })

      setCreateModalVisible(false)
      form.resetFields()
      loadData()
      message.success('预警已添加')
    })
  }

  const handleEdit = () => {
    if (!editingAlert) return
    form.validateFields().then((values) => {
      updateAlert(editingAlert.id, {
        code: values.code,
        name: values.name,
        type: values.type,
        target: values.target,
        repeat: values.repeat,
        sound: values.sound,
        notify: values.notify,
        message: values.message,
      })

      setEditModalVisible(false)
      setEditingAlert(null)
      form.resetFields()
      loadData()
      message.success('预警已更新')
    })
  }

  const handleDelete = (id: string) => {
    deleteAlert(id)
    loadData()
    message.success('预警已删除')
  }

  const handleClearAll = () => {
    clearAlerts()
    loadData()
    message.success('所有预警已清除')
  }

  const handleClearTriggered = () => {
    const removed = clearTriggeredAlerts()
    loadData()
    message.success(`已清除 ${removed} 条已触发预警`)
  }

  const handleToggle = (id: string, field: 'repeat' | 'sound' | 'notify', value: boolean) => {
    updateAlert(id, { [field]: value })
    loadData()
  }

  const columns: ColumnsType<PriceAlert> = [
    {
      title: '代码',
      dataIndex: 'code',
      width: 80,
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 100,
    },
    {
      title: '条件',
      key: 'condition',
      width: 150,
      render: (_, record) => getAlertLabel(record),
    },
    {
      title: '目标值',
      dataIndex: 'target',
      width: 100,
      render: (v: number, record) => {
        if (record.type.includes('change')) {
          return `${v >= 0 ? '+' : ''}${fmt(v)}%`
        } else if (record.type.includes('volume')) {
          return `${fmt((v ?? 0) / 10000, 0)}万`
        }
        return `¥${fmt(v)}`
      },
    },
    {
      title: '状态',
      dataIndex: 'triggered',
      width: 80,
      render: (triggered: boolean) => (
        <Tag color={triggered ? 'warning' : 'processing'} icon={triggered ? <WarningOutlined /> : <BellOutlined />}>
          {triggered ? '已触发' : '监控中'}
        </Tag>
      ),
    },
    {
      title: '触发时间',
      dataIndex: 'triggeredAt',
      width: 150,
      render: (v: number | null) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '重复',
      dataIndex: 'repeat',
      width: 60,
      render: (v: boolean, record) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(record.id, 'repeat', checked)} />
      ),
    },
    {
      title: '声音',
      dataIndex: 'sound',
      width: 60,
      render: (v: boolean, record) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(record.id, 'sound', checked)} />
      ),
    },
    {
      title: '通知',
      dataIndex: 'notify',
      width: 60,
      render: (v: boolean, record) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggle(record.id, 'notify', checked)} />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => {
              setEditingAlert(record)
              form.setFieldsValue(record)
              setEditModalVisible(true)
            }}
          />
          <Popconfirm title="确定删除此预警？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><BellOutlined style={{ marginRight: 8 }} />预警管理</Title>

      {/* 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="预警总数" value={stats.total} prefix={<BellOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="监控中" value={stats.active} valueStyle={{ color: '#1890ff' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="已触发" value={stats.triggered} valueStyle={{ color: '#faad14' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="价格预警"
              value={(stats.byType.price_above || 0) + (stats.byType.price_below || 0)}
            />
          </Card>
        </Col>
      </Row>

      {/* 预警列表 */}
      <Card
        title="预警列表"
        extra={
          <Space>
            <Button icon={<ClearOutlined />} onClick={handleClearTriggered} disabled={stats.triggered === 0}>
              清除已触发
            </Button>
            <Popconfirm title="确定清除所有预警？" onConfirm={handleClearAll}>
              <Button danger icon={<DeleteOutlined />}>
                清除全部
              </Button>
            </Popconfirm>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
              添加预警
            </Button>
          </Space>
        }
      >
        {alerts.length === 0 ? (
          <Empty description="暂无预警" />
        ) : (
          <Table
            dataSource={alerts}
            columns={columns}
            rowKey="id"
            pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }}
            size="small"
            scroll={{ x: 1000 }}
          />
        )}
      </Card>

      {/* 创建预警弹窗 */}
      <Modal
        title="添加预警"
        open={createModalVisible}
        onOk={handleCreate}
        onCancel={() => {
          setCreateModalVisible(false)
          form.resetFields()
        }}
        okText="添加"
        cancelText="取消"
        width={500}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="code" label="债券代码" rules={[{ required: true, message: '请输入代码' }]}>
                <Input placeholder="如：110001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="债券名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input placeholder="如：示例转债" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="type" label="预警类型" rules={[{ required: true }]}>
                <Select options={ALERT_TYPE_OPTIONS} placeholder="选择类型" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="target" label="目标值" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} placeholder="输入目标值" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="repeat" label="重复预警" valuePropName="checked" initialValue={false}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="sound" label="声音提醒" valuePropName="checked" initialValue={true}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="notify" label="推送通知" valuePropName="checked" initialValue={true}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="expiresAt" label="有效期（天）">
            <InputNumber style={{ width: '100%' }} placeholder="留空表示永久有效" min={1} max={365} />
          </Form.Item>
          <Form.Item name="message" label="备注">
            <Input.TextArea placeholder="预警触发时显示的消息" rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑预警弹窗 */}
      <Modal
        title="编辑预警"
        open={editModalVisible}
        onOk={handleEdit}
        onCancel={() => {
          setEditModalVisible(false)
          setEditingAlert(null)
          form.resetFields()
        }}
        okText="保存"
        cancelText="取消"
        width={500}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="code" label="债券代码" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="债券名称" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="type" label="预警类型" rules={[{ required: true }]}>
                <Select options={ALERT_TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="target" label="目标值" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="repeat" label="重复预警" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="sound" label="声音提醒" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="notify" label="推送通知" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="message" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
