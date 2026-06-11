/**
 * 自定义仪表盘页面
 */

import { useEffect, useMemo, useState } from 'react'
import { Card, Button, Space, Typography, Row, Col, Statistic, Table, List, Tag, Select, Modal, Input, message, Dropdown, Empty } from 'antd'
import { SettingOutlined, PlusOutlined, DeleteOutlined, CopyOutlined, DownloadOutlined, UploadOutlined, SaveOutlined } from '@ant-design/icons'
import { getLayouts, getCurrentLayout, setCurrentLayout, createLayout, deleteLayout, addWidget, deleteWidget, duplicateLayout, exportLayout, importLayout, type DashboardLayout, type DashboardWidget } from '../utils/dashboardLayout'
import { fmt } from '../utils/format'

const { Title, Text } = Typography

interface WidgetRendererProps {
  widget: DashboardWidget
  data?: Record<string, unknown>
}

// 小组件渲染器
function WidgetRenderer({ widget, data }: WidgetRendererProps) {
  switch (widget.type) {
    case 'statistic': {
      const value = data?.[widget.config.field as string] || 0
      return (
        <Card size="small" style={{ height: '100%' }}>
          <Statistic title={widget.title} value={value as number} />
        </Card>
      )
    }

    case 'chart':
      return (
        <Card size="small" title={widget.title} style={{ height: '100%' }}>
          <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#fafafa', borderRadius: 4 }}>
            <Text type="secondary">图表区域 (需要集成 ECharts)</Text>
          </div>
        </Card>
      )

    case 'list': {
      const items = data?.signals || []
      return (
        <Card size="small" title={widget.title} style={{ height: '100%' }}>
          <List
            size="small"
            dataSource={(items as any[]).slice(0, (widget.config.maxItems as number) || 5)}
            renderItem={(item: any) => (
              <List.Item>
                <Text>{item.code} - {item.name}</Text>
                <Tag color={item.action === 'buy' ? 'green' : 'red'}>{item.action}</Tag>
              </List.Item>
            )}
          />
        </Card>
      )
    }

    case 'table': {
      const positions = data?.positions || []
      return (
        <Card size="small" title={widget.title} style={{ height: '100%' }}>
          <Table
            size="small"
            dataSource={positions as any[]}
            columns={[
              { title: '代码', dataIndex: 'code', width: 80 },
              { title: '名称', dataIndex: 'name', width: 100 },
              { title: '持仓', dataIndex: 'volume', width: 80 },
              { title: '盈亏', dataIndex: 'profit', width: 100, render: (v: number) => <Text style={{ color: (v ?? 0) >= 0 ? '#52c41a' : '#ff4d4f' }}>{fmt(v)}%</Text> },
            ]}
            pagination={false}
            scroll={{ y: 200 }}
          />
        </Card>
      )
    }

    default:
      return (
        <Card size="small" style={{ height: '100%' }}>
          <Empty description="未知组件类型" />
        </Card>
      )
  }
}

export default function Dashboard() {
  const [layouts, setLayouts] = useState<DashboardLayout[]>([])
  const [currentLayout, setCurrentLayoutState] = useState<DashboardLayout | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [addWidgetModalVisible, setAddWidgetModalVisible] = useState(false)
  const [newLayoutName, setNewLayoutName] = useState('')
  const [newWidget, setNewWidget] = useState<Partial<DashboardWidget>>({
    type: 'statistic',
    title: '',
    size: 'small',
    w: 3,
    h: 1,
  })
  const mockData = useMemo(() => ({
    totalAsset: 1256789.56,
    todayProfit: 12345.67,
    positionCount: 15,
    alertCount: 3,
    signals: [
      { code: '110001', name: '示例转债1', action: 'buy' },
      { code: '110002', name: '示例转债2', action: 'sell' },
      { code: '110003', name: '示例转债3', action: 'buy' },
    ],
    positions: [
      { code: '110001', name: '示例转债1', volume: 100, profit: 2.5 },
      { code: '110002', name: '示例转债2', volume: 200, profit: -1.2 },
    ],
  }), [])

  useEffect(() => {
    loadLayouts()
  }, [])

  const loadLayouts = () => {
    setLayouts(getLayouts())
    setCurrentLayoutState(getCurrentLayout())
  }

  const handleLayoutChange = (id: string) => {
    setCurrentLayout(id)
    setCurrentLayoutState(getCurrentLayout())
  }

  const handleCreateLayout = () => {
    if (!newLayoutName.trim()) {
      message.warning('请输入布局名称')
      return
    }
    createLayout(newLayoutName.trim())
    setNewLayoutName('')
    setCreateModalVisible(false)
    loadLayouts()
    message.success('布局已创建')
  }

  const handleDeleteLayout = (id: string) => {
    deleteLayout(id)
    loadLayouts()
    message.success('布局已删除')
  }

  const handleDuplicateLayout = (id: string) => {
    duplicateLayout(id)
    loadLayouts()
    message.success('布局已复制')
  }

  const handleExportLayout = (id: string) => {
    const json = exportLayout(id)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `dashboard-layout-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('布局已导出')
  }

  const handleImportLayout = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return

      const reader = new FileReader()
      reader.onload = (e) => {
        const json = e.target?.result as string
        const layout = importLayout(json)
        if (layout) {
          loadLayouts()
          message.success('布局已导入')
        } else {
          message.error('导入失败，文件格式错误')
        }
      }
      reader.readAsText(file)
    }
    input.click()
  }

  const handleAddWidget = () => {
    if (!currentLayout || !newWidget.title) {
      message.warning('请填写组件标题')
      return
    }
    addWidget(currentLayout.id, {
      type: newWidget.type as any,
      title: newWidget.title || '',
      size: newWidget.size as any,
      x: 0,
      y: currentLayout.widgets.length,
      w: newWidget.w || 3,
      h: newWidget.h || 1,
      config: {},
      visible: true,
    })
    setAddWidgetModalVisible(false)
    setNewWidget({ type: 'statistic', title: '', size: 'small', w: 3, h: 1 })
    loadLayouts()
    message.success('组件已添加')
  }

  const handleDeleteWidget = (widgetId: string) => {
    if (!currentLayout) return
    deleteWidget(currentLayout.id, widgetId)
    loadLayouts()
    message.success('组件已删除')
  }

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <Title level={4} style={{ margin: 0 }}>数据看板</Title>
            <Select
              style={{ width: 150 }}
              value={currentLayout?.id}
              onChange={handleLayoutChange}
              options={layouts.map(l => ({ value: l.id, label: l.name }))}
            />
          </Space>
        </Col>
        <Col>
          <Space>
            <Button
              icon={editMode ? <SaveOutlined /> : <SettingOutlined />}
              onClick={() => setEditMode(!editMode)}
            >
              {editMode ? '保存' : '编辑'}
            </Button>
            <Dropdown
              menu={{
                items: [
                  { key: 'create', icon: <PlusOutlined />, label: '新建布局', onClick: () => setCreateModalVisible(true) },
                  { key: 'import', icon: <UploadOutlined />, label: '导入布局', onClick: handleImportLayout },
                  currentLayout && !currentLayout.isDefault ? { key: 'export', icon: <DownloadOutlined />, label: '导出布局', onClick: () => handleExportLayout(currentLayout.id) } : null,
                  currentLayout && !currentLayout.isDefault ? { key: 'duplicate', icon: <CopyOutlined />, label: '复制布局', onClick: () => handleDuplicateLayout(currentLayout.id) } : null,
                  currentLayout && !currentLayout.isDefault ? { key: 'delete', icon: <DeleteOutlined />, label: '删除布局', onClick: () => handleDeleteLayout(currentLayout.id), danger: true } : null,
                ].filter(Boolean) as any[],
              }}
            >
              <Button>布局管理</Button>
            </Dropdown>
          </Space>
        </Col>
      </Row>

      {/* 组件网格 */}
      {currentLayout && currentLayout.widgets.length > 0 ? (
        <div style={{ position: 'relative' }}>
          {editMode && (
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => setAddWidgetModalVisible(true)}
              style={{ width: '100%', marginBottom: 16 }}
            >
              添加组件
            </Button>
          )}

          <Row gutter={[16, 16]}>
            {currentLayout.widgets.filter(w => w.visible).map(widget => (
              <Col
                key={widget.id}
                xs={24}
                sm={12}
                md={widget.w >= 6 ? 24 : 12}
                lg={widget.w >= 8 ? 24 : widget.w >= 4 ? 12 : 8}
                xl={Math.min(widget.w * 2, 24)}
              >
                <div style={{ position: 'relative' }}>
                  {editMode && (
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => handleDeleteWidget(widget.id)}
                      style={{ position: 'absolute', top: 8, right: 8, zIndex: 10 }}
                    />
                  )}
                  <WidgetRenderer widget={widget} data={mockData} />
                </div>
              </Col>
            ))}
          </Row>
        </div>
      ) : (
        <Card>
          <Empty description="暂无组件，请添加组件或选择其他布局">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddWidgetModalVisible(true)}>
              添加组件
            </Button>
          </Empty>
        </Card>
      )}

      {/* 创建布局弹窗 */}
      <Modal
        title="新建布局"
        open={createModalVisible}
        onOk={handleCreateLayout}
        onCancel={() => setCreateModalVisible(false)}
        okText="创建"
        cancelText="取消"
      >
        <Input
          placeholder="请输入布局名称"
          value={newLayoutName}
          onChange={(e) => setNewLayoutName(e.target.value)}
        />
      </Modal>

      {/* 添加组件弹窗 */}
      <Modal
        title="添加组件"
        open={addWidgetModalVisible}
        onOk={handleAddWidget}
        onCancel={() => setAddWidgetModalVisible(false)}
        okText="添加"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <Text>组件类型</Text>
            <Select
              style={{ width: '100%' }}
              value={newWidget.type}
              onChange={(v) => setNewWidget({ ...newWidget, type: v })}
              options={[
                { value: 'statistic', label: '统计卡片' },
                { value: 'chart', label: '图表' },
                { value: 'list', label: '列表' },
                { value: 'table', label: '表格' },
              ]}
            />
          </div>
          <div>
            <Text>组件标题</Text>
            <Input
              placeholder="请输入组件标题"
              value={newWidget.title}
              onChange={(e) => setNewWidget({ ...newWidget, title: e.target.value })}
            />
          </div>
          <div>
            <Text>组件大小</Text>
            <Select
              style={{ width: '100%' }}
              value={newWidget.size}
              onChange={(v) => setNewWidget({ ...newWidget, size: v })}
              options={[
                { value: 'small', label: '小' },
                { value: 'medium', label: '中' },
                { value: 'large', label: '大' },
              ]}
            />
          </div>
        </Space>
      </Modal>
    </div>
  )
}
