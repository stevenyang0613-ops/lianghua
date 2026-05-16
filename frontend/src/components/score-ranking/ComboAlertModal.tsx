import React from 'react'
import { Modal, Card, Row, Col, Input, Select, InputNumber, Button, List, Tag, Space, Popconfirm, Radio, Divider, Typography } from 'antd'
import { AlertOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ComboCondition, ComboAlertModalProps } from './types'

const { Text } = Typography

const fieldOptions = [
  { value: 'price', label: '价格' },
  { value: 'dual_low', label: '双低值' },
  { value: 'premium', label: '溢价率' },
  { value: 'volume', label: '成交量' },
]

const operatorOptions = [
  { value: 'gt', label: '大于' },
  { value: 'lt', label: '小于' },
  { value: 'gte', label: '大于等于' },
  { value: 'lte', label: '小于等于' },
  { value: 'eq', label: '等于' },
]

export default React.memo(function ComboAlertModal({
  open, comboAlerts, newComboName, newComboLogic, newComboConditions,
  onClose, onComboNameChange, onComboLogicChange, onConditionsChange,
  onAddComboAlert, onDeleteComboAlert, onCheckComboAlerts,
}: ComboAlertModalProps) {
  return (
    <Modal title={<span><AlertOutlined /> 组合预警管理</span>} open={open} onCancel={onClose} footer={null} width={700}>
      <Card size="small" title="添加组合预警" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Text>预警名称</Text>
            <Input value={newComboName} onChange={e => onComboNameChange(e.target.value)} placeholder="如：双低+溢价组合" />
          </Col>
          <Col span={12}>
            <Text>逻辑关系</Text>
            <Radio.Group value={newComboLogic} onChange={e => onComboLogicChange(e.target.value)}>
              <Radio value="AND">全部满足 (AND)</Radio>
              <Radio value="OR">任一满足 (OR)</Radio>
            </Radio.Group>
          </Col>
        </Row>
        <Divider>条件设置</Divider>
        {newComboConditions.map((cond, idx) => (
          <Row gutter={8} key={idx} style={{ marginBottom: 8 }}>
            <Col span={6}>
              <Select value={cond.field} onChange={v => {
                const newConds = [...newComboConditions]
                newConds[idx] = { ...newConds[idx], field: v as ComboCondition['field'] }
                onConditionsChange(newConds)
              }} options={fieldOptions} style={{ width: '100%' }} />
            </Col>
            <Col span={5}>
              <Select value={cond.operator} onChange={v => {
                const newConds = [...newComboConditions]
                newConds[idx] = { ...newConds[idx], operator: v as ComboCondition['operator'] }
                onConditionsChange(newConds)
              }} options={operatorOptions} style={{ width: '100%' }} />
            </Col>
            <Col span={6}>
              <InputNumber value={cond.value} onChange={v => {
                const newConds = [...newComboConditions]
                newConds[idx] = { ...newConds[idx], value: v ?? 0 }
                onConditionsChange(newConds)
              }} style={{ width: '100%' }} />
            </Col>
            <Col span={4}>
              {newComboConditions.length > 1 && (
                <Button danger onClick={() => onConditionsChange(newComboConditions.filter((_, i) => i !== idx))}>删除</Button>
              )}
            </Col>
          </Row>
        ))}
        <Space style={{ marginTop: 8 }}>
          <Button onClick={() => onConditionsChange([...newComboConditions, { field: 'dual_low', operator: 'lte' as const, value: 130 }])}>添加条件</Button>
          <Button type="primary" onClick={onAddComboAlert}>保存预警</Button>
        </Space>
      </Card>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<AlertOutlined />} onClick={onCheckComboAlerts}>检查组合预警</Button>
      </Space>
      <List
        header={<Text strong>当前组合预警 ({comboAlerts.length})</Text>}
        dataSource={comboAlerts}
        renderItem={(alert) => (
          <List.Item actions={[
            <Popconfirm key="delete" title="确定删除？" onConfirm={() => onDeleteComboAlert(alert.id)}>
              <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          ]}>
            <List.Item.Meta
              title={<span>{alert.name} <Tag color={alert.logic === 'AND' ? 'blue' : 'orange'}>{alert.logic}</Tag></span>}
              description={<Space wrap>
                {alert.conditions.map((c, i) => (
                  <Tag key={i}>{c.field} {c.operator} {c.value}</Tag>
                ))}
              </Space>}
            />
          </List.Item>
        )}
      />
    </Modal>
  )
})
