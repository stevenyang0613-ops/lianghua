import React from 'react'
import { Modal, Card, Row, Col, Input, Select, InputNumber, Button, List, Tag, Space, Popconfirm, Switch, Divider, Typography } from 'antd'
import { BellOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import type { AlertManageModalProps } from './types'

const { Text } = Typography

export default React.memo(function AlertManageModal({
  open, alerts, newAlert, notificationEnabled, notificationSoundEnabled,
  onClose, onNewAlertChange, onAddAlert, onDeleteAlert, onCheckAlerts,
  onNotificationChange, onSoundChange,
}: AlertManageModalProps) {
  return (
    <Modal title={<span><BellOutlined /> 评分预警管理</span>} open={open} onCancel={onClose} footer={null} width={600}>
      <Card size="small" title="添加预警" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Text>代码</Text>
            <Input value={newAlert.code} onChange={e => onNewAlertChange({ ...newAlert, code: e.target.value })} />
          </Col>
          <Col span={6}>
            <Text>名称</Text>
            <Input value={newAlert.name} onChange={e => onNewAlertChange({ ...newAlert, name: e.target.value })} />
          </Col>
          <Col span={6}>
            <Text>类型</Text>
            <Select value={newAlert.alert_type} onChange={v => onNewAlertChange({ ...newAlert, alert_type: v })} style={{ width: '100%' }} options={[
              { value: 'score', label: '评分' },
              { value: 'price', label: '价格' },
              { value: 'dual_low', label: '双低' },
              { value: 'premium', label: '溢价' },
            ]} />
          </Col>
          <Col span={6}>
            <Text>方向</Text>
            <Select value={newAlert.direction} onChange={v => onNewAlertChange({ ...newAlert, direction: v })} style={{ width: '100%' }} options={[
              { value: 'above', label: '高于' },
              { value: 'below', label: '低于' },
            ]} />
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={12}>
            <Text>阈值</Text>
            <InputNumber value={newAlert.threshold} onChange={v => onNewAlertChange({ ...newAlert, threshold: v ?? 0 })} style={{ width: '100%' }} step={0.01} />
          </Col>
          <Col span={12} style={{ display: 'flex', alignItems: 'flex-end' }}>
            <Button type="primary" onClick={onAddAlert} icon={<PlusOutlined />}>添加预警</Button>
          </Col>
        </Row>
      </Card>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<BellOutlined />} onClick={onCheckAlerts}>检查预警</Button>
        <Divider type="vertical" />
        <Text>通知：</Text>
        <Switch checked={notificationEnabled} onChange={onNotificationChange} checkedChildren="开" unCheckedChildren="关" />
        <Text>声音：</Text>
        <Switch checked={notificationSoundEnabled} onChange={onSoundChange} checkedChildren="开" unCheckedChildren="关" />
      </Space>
      <List
        header={<Text strong>当前预警 ({alerts.length})</Text>}
        dataSource={alerts}
        renderItem={(alert) => (
          <List.Item actions={[
            <Popconfirm key="delete" title="确定删除？" onConfirm={() => onDeleteAlert(alert.id)}>
              <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          ]}>
            <List.Item.Meta
              title={<span>{alert.code} - {alert.name}</span>}
              description={<Space>
                <Tag>{alert.alert_type}</Tag>
                <Tag color={alert.direction === 'above' ? 'green' : 'red'}>{alert.direction === 'above' ? '≥' : '≤'} {alert.threshold}</Tag>
                <Tag color={alert.enabled ? 'blue' : 'default'}>{alert.enabled ? '启用' : '禁用'}</Tag>
              </Space>}
            />
          </List.Item>
        )}
      />
    </Modal>
  )
})
