import { useState, useEffect } from 'react'
import { Modal, Form, InputNumber, Select, Button, Space, Table, Tag, Badge, message, Popconfirm, Empty, Typography } from 'antd'
import { BellOutlined, PlusOutlined, DeleteOutlined, NotificationOutlined } from '@ant-design/icons'
import { useAlertStore, type AlertCondition, type AlertType } from '../stores/useAlertStore'

const { Text } = Typography

interface AlertPanelProps {
  visible: boolean
  onClose: () => void
  selectedCode?: string
  selectedName?: string
}

const alertTypeLabels: Record<AlertType, string> = {
  price_above: '价格高于',
  price_below: '价格低于',
  premium_above: '溢价率高于',
  premium_below: '溢价率低于',
  dual_low_below: '双低值低于',
  ytm_above: 'YTM高于',
}

const alertTypeUnits: Record<AlertType, string> = {
  price_above: '元',
  price_below: '元',
  premium_above: '%',
  premium_below: '%',
  dual_low_below: '',
  ytm_above: '%',
}

export default function AlertPanel({ visible, onClose, selectedCode, selectedName }: AlertPanelProps) {
  const [form] = Form.useForm()
  const { alerts, triggers, setAlerts, addAlert, removeAlert, clearTriggers } = useAlertStore()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (visible) {
      fetchAlerts()
    }
  }, [visible])

  useEffect(() => {
    if (selectedCode) {
      form.setFieldsValue({ code: selectedCode, name: selectedName })
    }
  }, [selectedCode, selectedName])

  const fetchAlerts = async () => {
    try {
      const resp = await fetch('/api/v1/alerts')
      const data = await resp.json()
      setAlerts(data.alerts || [])
    } catch (e) {
      console.error('Failed to fetch alerts:', e)
    }
  }

  const handleAddAlert = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)

      const alert: AlertCondition = {
        code: values.code,
        name: values.name || '',
        alert_type: values.alert_type,
        threshold: values.threshold,
        enabled: true,
        created_at: new Date().toISOString(),
      }

      const resp = await fetch('/api/v1/alerts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(alert),
      })

      if (resp.ok) {
        addAlert(alert)
        form.resetFields()
        message.success('告警已添加')
      } else {
        message.error('添加失败')
      }
    } catch (e) {
      console.error('Failed to add alert:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteAlert = async (alertId: string) => {
    try {
      const resp = await fetch(`/api/v1/alerts/${alertId}`, { method: 'DELETE' })
      if (resp.ok) {
        removeAlert(alertId)
        message.success('已删除')
      }
    } catch (e) {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 80,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 80,
    },
    {
      title: '条件',
      key: 'condition',
      render: (_: unknown, record: AlertCondition) => (
        <span>
          {alertTypeLabels[record.alert_type]} {record.threshold}{alertTypeUnits[record.alert_type]}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '禁用'}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: AlertCondition) => (
        <Popconfirm title="确定删除?" onConfirm={() => handleDeleteAlert(`${record.code}_${record.alert_type}`)}>
          <Button type="link" danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Modal
      title={
        <Space>
          <BellOutlined />
          价格告警
          {triggers.length > 0 && <Badge count={triggers.length} />}
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={700}
    >
      {triggers.length > 0 && (
        <div style={{ marginBottom: 16, padding: 12, background: '#fff2e8', borderRadius: 4 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            <Space>
              <NotificationOutlined style={{ color: '#fa8c16' }} />
              <Text strong>触发告警</Text>
              <Button size="small" onClick={clearTriggers}>全部清除</Button>
            </Space>
            {triggers.slice(0, 5).map((t, i) => (
              <Tag key={i} color="orange">
                {t.name} {alertTypeLabels[t.alert_type]} {t.threshold} (当前: {t.current_value.toFixed(2)})
              </Tag>
            ))}
          </Space>
        </div>
      )}

      <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
        <Form.Item name="code" rules={[{ required: true, message: '请输入代码' }]}>
          <InputNumber placeholder="代码" style={{ width: 100 }} />
        </Form.Item>
        <Form.Item name="name">
          <input type="text" placeholder="名称" style={{ width: 80, padding: '4px 11px', border: '1px solid #d9d9d9', borderRadius: 6 }} />
        </Form.Item>
        <Form.Item name="alert_type" rules={[{ required: true }]}>
          <Select placeholder="条件" style={{ width: 120 }}>
            {Object.entries(alertTypeLabels).map(([value, label]) => (
              <Select.Option key={value} value={value}>{label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="threshold" rules={[{ required: true }]}>
          <InputNumber placeholder="阈值" style={{ width: 100 }} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" icon={<PlusOutlined />} loading={loading} onClick={handleAddAlert}>
            添加
          </Button>
        </Form.Item>
      </Form>

      {alerts.length === 0 ? (
        <Empty description="暂无告警" />
      ) : (
        <Table
          dataSource={alerts}
          columns={columns}
          rowKey={(r) => `${r.code}_${r.alert_type}`}
          size="small"
          pagination={false}
        />
      )}
    </Modal>
  )
}
