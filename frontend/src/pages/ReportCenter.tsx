/**
 * 报告中心页面
 */

import { useEffect, useState } from 'react'
import { Card, Table, Button, Space, Modal, Form, Select, Input, Tag, Typography, Row, Col, Statistic, Popconfirm, Empty, message, DatePicker, Checkbox } from 'antd'
import { FileTextOutlined, DownloadOutlined, DeleteOutlined, PlusOutlined, FileExcelOutlined, FilePdfOutlined, FileUnknownOutlined, ReloadOutlined } from '@ant-design/icons'
import { generateReport, getReports, deleteReport, clearReports, downloadReport, REPORT_TYPE_OPTIONS, REPORT_FORMAT_OPTIONS, type GeneratedReport, type ReportConfig } from '../utils/reportGenerator'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

export default function ReportCenter() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [reports, setReports] = useState<GeneratedReport[]>([])
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [generating, setGenerating] = useState(false)

  const loadReports = () => {
    setReports(getReports())
  }

  useEffect(() => {
    loadReports()
  }, [])

  const handleCreate = () => {
    form.validateFields().then(async (values) => {
      setGenerating(true)

      try {
        message.warning('报告生成需要真实数据支持，请等待数据源就绪后重试')
        return

        const config: ReportConfig = {
          title: values.title,
          type: values.type,
          format: values.format,
          data: [],
          includeCharts: values.includeCharts || false,
          dateRange: values.dateRange?.map((d: dayjs.Dayjs) => d.format('YYYY-MM-DD')) as [string, string],
        }

        const report = generateReport(config)

        setCreateModalVisible(false)
        form.resetFields()
        loadReports()
        message.success('报告生成成功')

        // 自动下载
        downloadReport(report)
      } catch (err) {
        message.error('报告生成失败: ' + String(err))
      } finally {
        setGenerating(false)
      }
    })
  }

  const handleDownload = (report: GeneratedReport) => {
    downloadReport(report)
    message.success('报告下载中...')
  }

  const handleDelete = (id: string) => {
    deleteReport(id)
    loadReports()
    message.success('报告已删除')
  }

  const handleClearAll = () => {
    clearReports()
    loadReports()
    message.success('所有报告已清除')
  }

  const columns: ColumnsType<GeneratedReport> = [
    {
      title: '报告名称',
      dataIndex: 'title',
      width: 200,
      render: (title: string, record) => (
        <Space>
          {record.format === 'excel' ? (
            <FileExcelOutlined style={{ color: '#52c41a' }} />
          ) : record.format === 'pdf' ? (
            <FilePdfOutlined style={{ color: '#ff4d4f' }} />
          ) : (
            <FileUnknownOutlined style={{ color: '#1890ff' }} />
          )}
          <Text>{title}</Text>
        </Space>
      ),
    },
    {
      title: '报告类型',
      dataIndex: 'type',
      width: 100,
      render: (type: string) => {
        const labels: Record<string, string> = {
          trade: '交易报告',
          performance: '绩效报告',
          position: '持仓报告',
          signal: '信号报告',
          backtest: '回测报告',
          custom: '自定义',
        }
        return <Tag>{labels[type] || type}</Tag>
      },
    },
    {
      title: '格式',
      dataIndex: 'format',
      width: 80,
      render: (format: string) => (
        <Tag color={format === 'excel' ? 'green' : format === 'pdf' ? 'red' : 'blue'}>
          {format.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      width: 80,
    },
    {
      title: '生成时间',
      dataIndex: 'createdAt',
      width: 160,
      render: (v: number) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, record) => (
        <Space>
          <Button size="small" icon={<DownloadOutlined />} onClick={() => handleDownload(record)}>
            下载
          </Button>
          <Popconfirm title="确定删除此报告？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // 统计
  const totalReports = reports.length
  const totalSize = reports.reduce((sum, r) => {
    const match = r.size.match(/([\d.]+)\s*(KB|MB|B)/)
    if (match) {
      let size = parseFloat(match[1])
      if (match[2] === 'MB') size *= 1024
      return sum + size
    }
    return sum
  }, 0)

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><FileTextOutlined style={{ marginRight: 8 }} />报告中心</Title>

      {/* 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="报告总数" value={totalReports} suffix="份" prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="总大小" value={totalSize.toFixed(1)} suffix="KB" />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="最近生成" value={reports[0] ? new Date(reports[0].createdAt).toLocaleDateString('zh-CN') : '无'} />
          </Card>
        </Col>
      </Row>

      {/* 报告列表 */}
      <Card
        title="已生成报告"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadReports}>
              刷新
            </Button>
            <Popconfirm title="确定清除所有报告？" onConfirm={handleClearAll}>
              <Button danger icon={<DeleteOutlined />} disabled={reports.length === 0}>
                清除全部
              </Button>
            </Popconfirm>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
              生成报告
            </Button>
          </Space>
        }
      >
        {reports.length === 0 ? (
          <Empty description="暂无报告，点击「生成报告」创建" />
        ) : (
          <Table
            dataSource={reports}
            columns={columns}
            rowKey="id"
            pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }}
            size="small"
          />
        )}
      </Card>

      {/* 生成报告弹窗 */}
      <Modal
        title="生成报告"
        open={createModalVisible}
        onOk={handleCreate}
        onCancel={() => {
          setCreateModalVisible(false)
          form.resetFields()
        }}
        okText="生成并下载"
        cancelText="取消"
        confirmLoading={generating}
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="报告名称" rules={[{ required: true, message: '请输入报告名称' }]}>
            <Input placeholder="如：2024年1月交易报告" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="type" label="报告类型" rules={[{ required: true }]}>
                <Select options={REPORT_TYPE_OPTIONS} placeholder="选择类型" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="format" label="导出格式" rules={[{ required: true }]} initialValue="excel">
                <Select options={REPORT_FORMAT_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="dateRange" label="时间范围">
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="includeCharts" valuePropName="checked" initialValue={false}>
            <Checkbox>包含图表（仅PDF格式）</Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
