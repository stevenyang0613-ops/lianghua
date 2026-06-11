import React, { useMemo } from 'react'
import { Modal, Table, Tag, Button } from 'antd'
import { HistoryOutlined, CheckOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { AlertHistoryItem, AlertHistoryModalProps } from './types'

export default React.memo(function AlertHistoryModal({
  open, alertHistory, onClose, onAcknowledge,
}: AlertHistoryModalProps) {
  const columns = useMemo(() => [
    { title: '时间', dataIndex: 'triggered_at', width: 160, render: (v: string) => dayjs(v).format('MM-DD HH:mm') },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 120, ellipsis: true },
    { title: '类型', dataIndex: 'alert_type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: '阈值', dataIndex: 'threshold', width: 80 },
    { title: '实际值', dataIndex: 'current_value', width: 90, render: (v: number) => v?.toFixed(2) },
    { title: '状态', dataIndex: 'acknowledged', width: 80, render: (v: boolean) => <Tag color={v ? 'green' : 'orange'}>{v ? '已确认' : '待处理'}</Tag> },
    { title: '操作', key: 'action', width: 80, render: (_: unknown, record: AlertHistoryItem) => !record.acknowledged && (
      <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => onAcknowledge(record.id)}>确认</Button>
    )},
  ], [onAcknowledge])

  return (
    <Modal title={<span><HistoryOutlined /> 预警历史</span>} open={open} onCancel={onClose} footer={null} width={800}>
      <Table
        dataSource={alertHistory}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 15 }}
        columns={columns}
        scroll={{ x: 700 }}
      />
    </Modal>
  )
})
