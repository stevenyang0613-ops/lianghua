import React from 'react'
import { Modal, Input, Button, List, Space, Popconfirm, Divider, Typography } from 'antd'
import { SettingOutlined, DeleteOutlined } from '@ant-design/icons'
import type { FactorConfigModalProps } from './types'

const { Text } = Typography

export default React.memo(function FactorConfigModal({
  open, newFactorName, customFactors,
  onClose, onNewFactorNameChange, onSaveCustomFactor, onLoadFactor, onDeleteFactor,
}: FactorConfigModalProps) {
  return (
    <Modal title={<span><SettingOutlined /> 因子配置管理</span>} open={open} onCancel={onClose} footer={null} width={600}>
      <div style={{ marginBottom: 16 }}>
        <Text>保存当前权重配置</Text>
        <Space style={{ width: '100%', marginTop: 8 }}>
          <Input placeholder="配置名称" value={newFactorName} onChange={e => onNewFactorNameChange(e.target.value)} style={{ width: 200 }} />
          <Button type="primary" onClick={onSaveCustomFactor}>保存</Button>
        </Space>
      </div>
      <Divider />
      <List
        header={<Text strong>已保存的配置</Text>}
        dataSource={[{ id: 'default', name: '默认配置' }, ...Object.entries(customFactors).map(([id, f]) => ({ id, name: f.name }))]}
        renderItem={(item) => (
          <List.Item actions={item.id !== 'default' ? [
            <Button key="load" type="link" onClick={() => onLoadFactor(item.id)}>加载</Button>,
            <Popconfirm key="delete" title="确定删除？" onConfirm={() => onDeleteFactor(item.id)}>
              <Button type="link" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          ] : [<Button key="load" type="link" onClick={() => onLoadFactor('default')}>加载</Button>]}>
            <Text>{item.name}</Text>
          </List.Item>
        )}
      />
    </Modal>
  )
})
