/**
 * 数据导入/导出页面
 * 支持导出市场数据、自选股、策略配置等
 */

import { useState } from 'react'
import {
  Card, Row, Col, Typography, Button, Space, Upload, message, Modal,
  List, Checkbox, Divider, Alert, Progress, Tag, Tooltip, Empty
} from 'antd'
import {
  DownloadOutlined, UploadOutlined, FileTextOutlined,
  TableOutlined, FileExcelOutlined, DeleteOutlined,
  CheckCircleOutlined, WarningOutlined, InfoCircleOutlined
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import {
  exportToJson,
  exportToCsv,
  exportToExcel,
  importFromJson,
  importFromCsv,
  validateImportData,
  exportAllUserData,
  importAllUserData,
} from '../utils/dataImportExport'
import { useWatchlistStore } from '../stores/useWatchlistStore'
import { useAnalyticsStore } from '../stores/useAnalyticsStore'

const { Title, Text, Paragraph } = Typography

export default function DataImportExportPage() {
  const { watchlist, addWatch, clearWatchlist } = useWatchlistStore()
  const { exportData: exportAnalytics, clearData: clearAnalytics } = useAnalyticsStore()
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importPreview, setImportPreview] = useState<{
    type: 'json' | 'csv'
    data: any
    warnings: string[]
    errors: string[]
  } | null>(null)
  const [exportOptions, setExportOptions] = useState({
    watchlist: true,
    alerts: true,
    strategies: true,
    analytics: false,
    settings: true,
  })

  // 导出全部数据
  const handleExportAll = async () => {
    setExporting(true)
    try {
      await exportAllUserData()
      message.success('数据已导出')
    } catch (error) {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 导出自选股
  const handleExportWatchlist = async (format: 'json' | 'csv' | 'excel') => {
    if (watchlist.length === 0) {
      message.warning('自选股列表为空')
      return
    }

    setExporting(true)
    try {
      switch (format) {
        case 'json':
          await exportToJson({ watchlist: watchlist as any }, 'watchlist')
          break
        case 'csv':
          await exportToCsv(watchlist as any, 'watchlist')
          break
        case 'excel':
          await exportToExcel(watchlist as any, 'watchlist')
          break
      }
      message.success(`已导出 ${watchlist.length} 条自选股数据`)
    } catch (error) {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 导出统计数据
  const handleExportAnalytics = async () => {
    setExporting(true)
    try {
      const analyticsJson = exportAnalytics()
      const blob = new Blob([analyticsJson], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `lianghua-analytics-${new Date().toISOString().split('T')[0]}.json`
      a.click()
      URL.revokeObjectURL(url)
      message.success('统计数据已导出')
    } catch (error) {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 导入文件处理
  const handleImport: UploadProps['customRequest'] = async (options) => {
    const { file } = options
    setImporting(true)

    try {
      const fileObj = file as File
      const extension = fileObj.name.split('.').pop()?.toLowerCase()

      if (extension === 'json') {
        const data = await importFromJson(fileObj)
        if (data) {
          const validation = validateImportData(data)
          setImportPreview({
            type: 'json',
            data,
            warnings: validation.warnings,
            errors: validation.errors,
          })
        } else {
          message.error('无法解析 JSON 文件')
        }
      } else if (extension === 'csv') {
        const codes = await importFromCsv(fileObj)
        if (codes) {
          setImportPreview({
            type: 'csv',
            data: codes,
            warnings: [],
            errors: [],
          })
        } else {
          message.error('无法解析 CSV 文件')
        }
      } else {
        message.error('不支持的文件格式')
      }
    } catch (error) {
      message.error('导入失败')
    } finally {
      setImporting(false)
    }
  }

  // 确认导入
  const handleConfirmImport = async () => {
    if (!importPreview) return

    setImporting(true)
    try {
      if (importPreview.type === 'json') {
        const result = await importAllUserData(importPreview.data.data)
        if (result.success) {
          message.success(`已导入: ${result.imported.join(', ')}`)
        } else {
          message.error(`导入失败: ${result.errors.join(', ')}`)
        }
      } else if (importPreview.type === 'csv') {
        const codes = importPreview.data as string[]
        // 导入自选股代码
        for (const code of codes) {
          addWatch({ code, name: '' } as any)
        }
        message.success(`已导入 ${codes.length} 个自选股代码`)
      }

      setImportPreview(null)
    } catch (error) {
      message.error('导入失败')
    } finally {
      setImporting(false)
    }
  }

  // 清除所有数据
  const handleClearAll = () => {
    Modal.confirm({
      title: '确认清除',
      content: '此操作将清除所有本地存储的数据，包括自选股、预警配置、统计数据等。确定要继续吗？',
      okText: '确认清除',
      okButtonProps: { danger: true },
      onOk: () => {
        localStorage.clear()
        clearWatchlist()
        clearAnalytics()
        message.success('所有数据已清除')
      },
    })
  }

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <Title level={4}>
        <FileTextOutlined /> 数据导入/导出
      </Title>
      <Paragraph type="secondary">
        管理您的数据，支持导出备份和从备份恢复
      </Paragraph>

      {/* 快捷操作 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              size="large"
              block
              onClick={handleExportAll}
              loading={exporting}
            >
              一键导出全部数据
            </Button>
          </Col>
          <Col span={12}>
            <Upload
              accept=".json,.csv"
              showUploadList={false}
              customRequest={handleImport}
            >
              <Button
                icon={<UploadOutlined />}
                size="large"
                block
                loading={importing}
              >
                导入数据
              </Button>
            </Upload>
          </Col>
        </Row>
      </Card>

      {/* 导出选项 */}
      <Card title="导出选项" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Title level={5}>自选股 ({watchlist.length} 条)</Title>
            <Space>
              <Button onClick={() => handleExportWatchlist('json')}>
                <FileTextOutlined /> JSON
              </Button>
              <Button onClick={() => handleExportWatchlist('csv')}>
                <TableOutlined /> CSV
              </Button>
              <Button onClick={() => handleExportWatchlist('excel')}>
                <FileExcelOutlined /> Excel
              </Button>
            </Space>
          </Col>

          <Col span={24}>
            <Divider />
            <Title level={5}>使用统计</Title>
            <Button icon={<DownloadOutlined />} onClick={handleExportAnalytics}>
              导出统计数据
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 导入预览 */}
      {importPreview && (
        <Modal
          title="导入预览"
          open={!!importPreview}
          onOk={handleConfirmImport}
          onCancel={() => setImportPreview(null)}
          okText="确认导入"
          width={600}
        >
          {importPreview.errors.length > 0 && (
            <Alert
              type="error"
              message="导入错误"
              description={
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {importPreview.errors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              }
              style={{ marginBottom: 16 }}
            />
          )}

          {importPreview.warnings.length > 0 && (
            <Alert
              type="warning"
              message="注意事项"
              description={
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {importPreview.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              }
              style={{ marginBottom: 16 }}
            />
          )}

          {importPreview.type === 'json' && (
            <div>
              <Title level={5}>将要导入的数据：</Title>
              <List
                size="small"
                dataSource={Object.entries(importPreview.data.data || {})}
                renderItem={([key, value]) => (
                  <List.Item>
                    <Tag>{key}</Tag>
                    <Text>
                      {Array.isArray(value) ? `${value.length} 条记录` : '已配置'}
                    </Text>
                  </List.Item>
                )}
              />
            </div>
          )}

          {importPreview.type === 'csv' && (
            <div>
              <Title level={5}>
                将要导入 {(importPreview.data as string[]).length} 个自选股代码
              </Title>
              <Text type="secondary">
                {(importPreview.data as string[]).slice(0, 10).join(', ')}
                {(importPreview.data as string[]).length > 10 && '...'}
              </Text>
            </div>
          )}
        </Modal>
      )}

      {/* 数据管理 */}
      <Card title="数据管理" extra={<Tag color="red">危险操作</Tag>}>
        <Alert
          type="warning"
          message="清除数据将删除所有本地存储的信息，包括自选股、预警配置、主题设置等。此操作不可恢复。"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Button danger icon={<DeleteOutlined />} onClick={handleClearAll}>
          清除所有数据
        </Button>
      </Card>

      {/* 使用说明 */}
      <Card title="使用说明" style={{ marginTop: 16 }}>
        <List
          size="small"
          dataSource={[
            '导出的 JSON 文件可用于备份和恢复所有用户数据',
            'CSV 文件可用于在 Excel 中查看和编辑自选股',
            '导入数据时会自动合并，不会覆盖现有数据',
            '建议定期备份数据，以防数据丢失',
          ]}
          renderItem={(item) => (
            <List.Item>
              <InfoCircleOutlined style={{ color: '#1890ff', marginRight: 8 }} />
              {item}
            </List.Item>
          )}
        />
      </Card>
    </div>
  )
}
