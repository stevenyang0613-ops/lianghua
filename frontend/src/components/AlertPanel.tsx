import { useState, useEffect, useMemo, useCallback } from 'react'
import { Modal, Form, InputNumber, Select, Button, Space, Table, Tag, Badge, message, Popconfirm, Empty, Typography, Alert } from 'antd'
import { BellOutlined, PlusOutlined, DeleteOutlined, NotificationOutlined } from '@ant-design/icons'
import { useAlertStore, type AlertCondition, type AlertType } from '../stores/useAlertStore'
import { getApiBase } from '../utils/config'
import { requestNotificationPermission, getNotificationPermission, sendAlertNotification } from '../utils/notifications'

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
  const alerts = useAlertStore((s) => s.alerts)
  const triggers = useAlertStore((s) => s.triggers)
  const setAlerts = useAlertStore((s) => s.setAlerts)
  const addAlert = useAlertStore((s) => s.addAlert)
  const removeAlert = useAlertStore((s) => s.removeAlert)
  const clearTriggers = useAlertStore((s) => s.clearTriggers)
  const [loading, setLoading] = useState(false)
  const [notificationEnabled, setNotificationEnabled] = useState(getNotificationPermission() === 'granted')

  useEffect(() => {
    if (visible) {
      fetchAlerts()
      setNotificationEnabled(getNotificationPermission() === 'granted')
    }
  }, [visible])

  useEffect(() => {
    if (selectedCode) {
      form.setFieldsValue({ code: selectedCode, name: selectedName })
    }
  }, [selectedCode, selectedName])

  useEffect(() => {
    triggers.forEach((t) => {
      if (notificationEnabled) {
        sendAlertNotification(t.code, t.name, t.alert_type, t.current_value, t.threshold)
      }
    })
  }, [triggers, notificationEnabled])

  const handleEnableNotification = async () => {
    const permission = await requestNotificationPermission()
    setNotificationEnabled(permission === 'granted')
    if (permission === 'granted') {
      message.success('已开启浏览器通知')
    } else {
      message.warning('请在浏览器设置中允许通知')
    }
  }

  const fetchAlerts = async () => {
    try {
      const baseUrl = getApiBase()
      if (window.electronAPI?.httpRequest) {
        const result = await window.electronAPI.httpRequest('GET', `${baseUrl}/api/v1/alerts`)
        if (result.ok) setAlerts(result.data?.alerts || [])
      } else {
        const resp = await fetch(`${baseUrl}/api/v1/alerts`)
        const data = await resp.json()
        setAlerts(data.alerts || [])
      }
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

      const baseUrl = getApiBase()
      let ok = false
      if (window.electronAPI?.httpRequest) {
        const result = await window.electronAPI.httpRequest('POST', `${baseUrl}/api/v1/alerts`, alert)
        ok = result.ok
      } else {
        const resp = await fetch(`${baseUrl}/api/v1/alerts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(alert),
        })
        ok = resp.ok
      }

      if (ok) {
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

  const handleDeleteAlert = useCallback(async (alertId: string) => {
    try {
      const baseUrl = getApiBase()
      let ok = false
      if (window.electronAPI?.httpRequest) {
        const result = await window.electronAPI.httpRequest('DELETE', `${baseUrl}/api/v1/alerts/${alertId}`)
        ok = result.ok
      } else {
        const resp = await fetch(`${baseUrl}/api/v1/alerts/${alertId}`, { method: 'DELETE' })
        ok = resp.ok
      }
      if (ok) {
        removeAlert(alertId)
        message.success('已删除')
      }
    } catch (e) {
      message.error('删除失败')
    }
  }, [removeAlert])

  const columns = useMemo(() => [
    { title: '代码', dataIndex: 'code', key: 'code', width: 80 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 80 },
    {
      title: '条件',
      key: 'condition',
      render: (_: unknown, record: AlertCondition) => (
        <span>{alertTypeLabels[record.alert_type]} {record.threshold}{alertTypeUnits[record.alert_type]}</span>
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
  ], [handleDeleteAlert])

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
      {!notificationEnabled && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="开启浏览器通知可在告警触发时收到提醒"
          action={
            <Button size="small" type="primary" onClick={handleEnableNotification}>
              开启通知
            </Button>
          }
        />
      )}

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
                {t.name} {alertTypeLabels[t.alert_type]} {t.threshold} (当前: {Number.isFinite(t.current_value) ? t.current_value.toFixed(2) : '-'})
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
