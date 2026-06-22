/**
 * 自定义仪表盘页面
 */

import { useEffect, useMemo, useState } from 'react'
import { Card, Button, Space, Typography, Row, Col, Statistic, Table, List, Tag, Select, Modal, Input, message, Dropdown, Empty, Spin } from 'antd'
import { SettingOutlined, PlusOutlined, DeleteOutlined, CopyOutlined, DownloadOutlined, UploadOutlined, SaveOutlined, RiseOutlined, FallOutlined, DashboardOutlined, AlertOutlined } from '@ant-design/icons'
import { getLayouts, getCurrentLayout, setCurrentLayout, createLayout, deleteLayout, addWidget, deleteWidget, duplicateLayout, exportLayout, importLayout, type DashboardLayout, type DashboardWidget } from '../utils/dashboardLayout'
import { useMarketStore } from '../stores/useMarketStore'
import { useAppStore } from '../stores/useAppStore'
import { fmt } from '../utils/format'

const { Title, Text } = Typography

interface WidgetRendererProps {
  widget: DashboardWidget
}

// Market summary widget
function MarketSummaryWidget() {
  const allBonds = useMarketStore((s) => s.allBonds)
  const updatedAt = useMarketStore((s) => s.updatedAt)

  const stats = useMemo(() => {
    if (!allBonds.length) return { total: 0, avgPrice: 0, avgPremium: 0, avgDualLow: 0, riseCount: 0, fallCount: 0 }
    const total = allBonds.length
    const avgPrice = allBonds.reduce((s, b) => s + (b.price || 0), 0) / total
    const avgPremium = allBonds.reduce((s, b) => s + (b.premium_ratio || 0), 0) / total
    const avgDualLow = allBonds.reduce((s, b) => s + (b.dual_low || 0), 0) / total
    const riseCount = allBonds.filter(b => (b.change_pct ?? 0) > 0).length
    const fallCount = allBonds.filter(b => (b.change_pct ?? 0) < 0).length
    return { total, avgPrice, avgPremium, avgDualLow, riseCount, fallCount }
  }, [allBonds])

  return (
    <Card size="small" style={{ height: '100%' }}>
      <Row gutter={8}>
        <Col span={8}><Statistic title="可转债总数" value={stats.total} prefix={<DashboardOutlined />} /></Col>
        <Col span={8}><Statistic title="上涨" value={stats.riseCount} valueStyle={{ color: '#cf1322' }} prefix={<RiseOutlined />} /></Col>
        <Col span={8}><Statistic title="下跌" value={stats.fallCount} valueStyle={{ color: '#3f8600' }} prefix={<FallOutlined />} /></Col>
      </Row>
      <Row gutter={8} style={{ marginTop: 12 }}>
        <Col span={8}><Statistic title="均价" value={stats.avgPrice} precision={2} /></Col>
        <Col span={8}><Statistic title="均溢价率" value={stats.avgPremium} precision={1} suffix="%" /></Col>
        <Col span={8}><Statistic title="均双低" value={stats.avgDualLow} precision={1} /></Col>
      </Row>
      {updatedAt && <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>更新: {updatedAt}</div>}
    </Card>
  )
}

// Top dual-low bonds widget
function TopDualLowWidget() {
  const allBonds = useMarketStore((s) => s.allBonds)

  const topBonds = useMemo(() => {
    return [...allBonds]
      .filter(b => (b.dual_low ?? 0) > 0 && (b.price ?? 0) > 0)
      .sort((a, b) => (a.dual_low ?? 0) - (b.dual_low ?? 0))
      .slice(0, 5)
  }, [allBonds])

  return (
    <Card size="small" title="双低TOP5" style={{ height: '100%' }}>
      {topBonds.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          dataSource={topBonds}
          renderItem={(item) => (
            <List.Item>
              <span>{item.code} {item.name}</span>
              <Tag color={(item.dual_low ?? 0) < 130 ? 'green' : (item.dual_low ?? 0) < 150 ? 'blue' : 'orange'}>{fmt(item.dual_low)}</Tag>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

// Forced call alert widget
function ForcedCallAlertWidget() {
  const allBonds = useMarketStore((s) => s.allBonds)

  const forcedCallBonds = useMemo(() => {
    return allBonds
      .filter(b => (b.forced_call_days ?? 0) >= 5 || b.is_called)
      .sort((a, b) => (b.forced_call_days ?? 0) - (a.forced_call_days ?? 0))
      .slice(0, 5)
  }, [allBonds])

  return (
    <Card size="small" title={<span><AlertOutlined style={{ color: '#faad14' }} /> 强赎预警</span>} style={{ height: '100%' }}>
      {forcedCallBonds.length === 0 ? (
        <Empty description="暂无强赎预警" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          size="small"
          dataSource={forcedCallBonds}
          renderItem={(item) => (
            <List.Item>
              <span>{item.code} {item.name}</span>
              <Tag color={item.is_called ? 'red' : (item.forced_call_days ?? 0) >= 10 ? 'red' : 'orange'}>
                {item.is_called ? '已公告' : `${item.forced_call_days}/15天`}
              </Tag>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

// 小组件渲染器
function WidgetRenderer({ widget }: WidgetRendererProps) {
  // Built-in data-driven widgets
  if (widget.type === 'market-summary') return <MarketSummaryWidget />
  if (widget.type === 'top-dual-low') return <TopDualLowWidget />
  if (widget.type === 'forced-call-alert') return <ForcedCallAlertWidget />

  // Legacy static widgets
  switch (widget.type) {
    case 'statistic': {
      return (
        <Card size="small" style={{ height: '100%' }}>
          <Statistic title={widget.title} value={0} />
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
      return (
        <Card size="small" title={widget.title} style={{ height: '100%' }}>
          <Empty description="请使用市场概览组件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </Card>
      )
    }

    case 'table': {
      return (
        <Card size="small" title={widget.title} style={{ height: '100%' }}>
          <Empty description="请使用双低TOP5或强赎预警组件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
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

// Default dashboard layout with real data widgets
function getDefaultWidgets(): DashboardWidget[] {
  return [
    { id: 'w-market', type: 'market-summary', title: '市场概览', size: 'large', visible: true, x: 0, y: 0, w: 12, h: 2, config: {} },
    { id: 'w-dual-low', type: 'top-dual-low', title: '双低TOP5', size: 'small', visible: true, x: 0, y: 2, w: 6, h: 1, config: {} },
    { id: 'w-forced-call', type: 'forced-call-alert', title: '强赎预警', size: 'small', visible: true, x: 6, y: 2, w: 6, h: 1, config: {} },
  ]
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
    if (!currentLayout || !newWidget.title || !newWidget.type || !newWidget.size) {
      message.warning('请填写组件标题/类型/尺寸')
      return
    }
    addWidget(currentLayout.id, {
      type: newWidget.type,
      title: newWidget.title || '',
      size: newWidget.size,
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
                ].filter((item): item is NonNullable<typeof item> => item !== null),
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
                  <WidgetRenderer widget={widget} />
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
                { value: 'market-summary', label: '市场概览' },
                { value: 'top-dual-low', label: '双低TOP5' },
                { value: 'forced-call-alert', label: '强赎预警' },
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
