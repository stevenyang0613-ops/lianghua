/**
 * 交易日志页面
 */

import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, DatePicker, Select, Typography, Row, Col, Statistic, Modal, Descriptions, Empty, Spin, Popconfirm } from 'antd'
import { HistoryOutlined, DownloadOutlined, DeleteOutlined, EyeOutlined, FilterOutlined } from '@ant-design/icons'
import { getTradeLogs, getTradeStats, clearTradeLogs, exportTradeLogs, type TradeLog } from '../utils/tradeLogger'
import type { ColumnsType } from 'antd/es/table'

const { Title } = Typography
const { RangePicker } = DatePicker

const actionColors: Record<string, string> = {
  buy: 'green',
  sell: 'red',
  cancel: 'orange',
  modify: 'blue',
  signal: 'purple',
  view: 'default',
}

const statusColors: Record<string, string> = {
  pending: 'processing',
  success: 'success',
  failed: 'error',
  cancelled: 'default',
}

const actionLabels: Record<string, string> = {
  buy: '买入',
  sell: '卖出',
  cancel: '撤销',
  modify: '修改',
  signal: '信号',
  view: '查看',
}

export default function TradeLogPage() {
  const [logs, setLogs] = useState<TradeLog[]>([])
  const [stats, setStats] = useState(getTradeStats())
  const [loading, setLoading] = useState(false)
  const [selectedLog, setSelectedLog] = useState<TradeLog | null>(null)
  const [filters, setFilters] = useState<{
    action?: TradeLog['action']
    status?: TradeLog['status']
    dateRange?: [number, number]
  }>({})

  useEffect(() => {
    loadData()
  }, [filters])

  const loadData = () => {
    setLoading(true)
    const options: Parameters<typeof getTradeLogs>[0] = {}

    if (filters.action) options.action = filters.action
    if (filters.status) options.status = filters.status
    if (filters.dateRange) {
      options.startDate = filters.dateRange[0]
      options.endDate = filters.dateRange[1]
    }

    setLogs(getTradeLogs(options))
    setStats(getTradeStats({
      startDate: filters.dateRange?.[0],
      endDate: filters.dateRange?.[1],
    }))
    setLoading(false)
  }

  const handleExport = (format: 'json' | 'csv') => {
    const content = exportTradeLogs(format)
    const blob = new Blob([content], { type: format === 'json' ? 'application/json' : 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trade-logs-${new Date().toISOString().slice(0, 10)}.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleClear = () => {
    clearTradeLogs()
    loadData()
  }

  const columns: ColumnsType<TradeLog> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 160,
      render: (ts: number) => new Date(ts).toLocaleString('zh-CN'),
      sorter: (a, b) => a.timestamp - b.timestamp,
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: 80,
      render: (action: string) => (
        <Tag color={actionColors[action]}>{actionLabels[action] || action}</Tag>
      ),
      filters: [
        { text: '买入', value: 'buy' },
        { text: '卖出', value: 'sell' },
        { text: '撤销', value: 'cancel' },
        { text: '信号', value: 'signal' },
      ],
      onFilter: (value, record) => record.action === value,
    },
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 100,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 120,
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      render: (price?: number) => price?.toFixed(2) || '-',
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
      render: (q?: number) => q || '-',
    },
    {
      title: '金额',
      dataIndex: 'amount',
      key: 'amount',
      width: 120,
      render: (amount?: number) => amount?.toFixed(2) || '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => (
        <Tag color={statusColors[status]}>{status.toUpperCase()}</Tag>
      ),
    },
    {
      title: '策略',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 100,
      render: (s?: string) => s || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Button size="small" icon={<EyeOutlined />} onClick={() => setSelectedLog(record)} />
      ),
    },
  ]

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><HistoryOutlined style={{ marginRight: 8 }} />交易日志</Title>

      {/* 统计概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="总记录数" value={stats.total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="交易金额" value={stats.totalAmount} precision={2} suffix="元" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="成功率" value={stats.successRate * 100} precision={1} suffix="%" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="买入/卖出"
              value={`${stats.byAction.buy || 0} / ${stats.byAction.sell || 0}`}
            />
          </Card>
        </Col>
      </Row>

      {/* 筛选和操作 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <FilterOutlined />
          <Select
            placeholder="操作类型"
            allowClear
            style={{ width: 120 }}
            onChange={(v) => setFilters({ ...filters, action: v })}
            options={[
              { value: 'buy', label: '买入' },
              { value: 'sell', label: '卖出' },
              { value: 'cancel', label: '撤销' },
              { value: 'signal', label: '信号' },
            ]}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 120 }}
            onChange={(v) => setFilters({ ...filters, status: v })}
            options={[
              { value: 'success', label: '成功' },
              { value: 'pending', label: '处理中' },
              { value: 'failed', label: '失败' },
              { value: 'cancelled', label: '已撤销' },
            ]}
          />
          <RangePicker
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setFilters({
                  ...filters,
                  dateRange: [dates[0].valueOf(), dates[1].endOf('day').valueOf()],
                })
              } else {
                setFilters({ ...filters, dateRange: undefined })
              }
            }}
          />
          <Button onClick={loadData}>刷新</Button>
          <Button icon={<DownloadOutlined />} onClick={() => handleExport('csv')}>导出 CSV</Button>
          <Button icon={<DownloadOutlined />} onClick={() => handleExport('json')}>导出 JSON</Button>
          <Popconfirm title="确定清除所有日志？" onConfirm={handleClear}>
            <Button icon={<DeleteOutlined />} danger>清除日志</Button>
          </Popconfirm>
        </Space>
      </Card>

      {/* 日志表格 */}
      <Card>
        {loading ? (
          <Spin />
        ) : logs.length === 0 ? (
          <Empty description="暂无交易日志" />
        ) : (
          <Table
            dataSource={logs}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
            size="small"
            scroll={{ x: 1200 }}
          />
        )}
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title="交易详情"
        open={!!selectedLog}
        onCancel={() => setSelectedLog(null)}
        footer={null}
        width={600}
      >
        {selectedLog && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="ID" span={2}>{selectedLog.id}</Descriptions.Item>
            <Descriptions.Item label="时间">{new Date(selectedLog.timestamp).toLocaleString('zh-CN')}</Descriptions.Item>
            <Descriptions.Item label="操作">
              <Tag color={actionColors[selectedLog.action]}>{actionLabels[selectedLog.action]}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="代码">{selectedLog.code}</Descriptions.Item>
            <Descriptions.Item label="名称">{selectedLog.name}</Descriptions.Item>
            <Descriptions.Item label="价格">{selectedLog.price?.toFixed(2) || '-'}</Descriptions.Item>
            <Descriptions.Item label="数量">{selectedLog.quantity || '-'}</Descriptions.Item>
            <Descriptions.Item label="金额">{selectedLog.amount?.toFixed(2) || '-'}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={statusColors[selectedLog.status]}>{selectedLog.status.toUpperCase()}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="策略">{selectedLog.strategy || '-'}</Descriptions.Item>
            <Descriptions.Item label="信号ID">{selectedLog.signalId || '-'}</Descriptions.Item>
            <Descriptions.Item label="备注" span={2}>{selectedLog.notes || '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
