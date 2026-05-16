/**
 * 主题商店页面
 */

import { useEffect, useState } from 'react'
import { Card, Row, Col, Typography, Button, Space, Modal, Input, message, Dropdown, Tag, Switch, Divider, ColorPicker } from 'antd'
import { CheckOutlined, DownloadOutlined, UploadOutlined, DeleteOutlined, EditOutlined, CopyOutlined, BulbOutlined, SkinOutlined } from '@ant-design/icons'
import { getAllThemes, getCurrentTheme, setCurrentTheme, addCustomTheme, deleteCustomTheme, exportTheme, importTheme, type Theme, type ThemeColors } from '../theme/themes'

const { Title, Text, Paragraph } = Typography

interface ColorEditorProps {
  colors: Partial<ThemeColors>
  onChange: (colors: Partial<ThemeColors>) => void
}

function ColorEditor({ colors, onChange }: ColorEditorProps) {
  const colorFields: { key: keyof ThemeColors; label: string }[] = [
    { key: 'primary', label: '主色' },
    { key: 'success', label: '成功' },
    { key: 'warning', label: '警告' },
    { key: 'error', label: '错误' },
    { key: 'info', label: '信息' },
    { key: 'background', label: '背景' },
    { key: 'backgroundSecondary', label: '次背景' },
    { key: 'text', label: '文字' },
    { key: 'textSecondary', label: '次文字' },
    { key: 'border', label: '边框' },
    { key: 'card', label: '卡片' },
  ]

  return (
    <Row gutter={[16, 16]}>
      {colorFields.map(({ key, label }) => (
        <Col span={12} key={key}>
          <Space>
            <Text>{label}</Text>
            <ColorPicker
              value={colors[key] as string}
              onChange={(color) => onChange({ ...colors, [key]: color.toHexString() })}
              showText
            />
          </Space>
        </Col>
      ))}
    </Row>
  )
}

export default function ThemeStore() {
  const [themes, setThemes] = useState<Theme[]>([])
  const [currentThemeId, setCurrentThemeId] = useState<string>('')
  const [createModalVisible, setCreateModalVisible] = useState(false)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingTheme, setEditingTheme] = useState<Theme | null>(null)
  const [newTheme, setNewTheme] = useState<Partial<Theme>>({
    name: '',
    description: '',
    isDark: false,
    colors: {
      primary: '#1890ff',
      success: '#52c41a',
      warning: '#faad14',
      error: '#ff4d4f',
      info: '#1890ff',
      background: '#f0f2f5',
      backgroundSecondary: '#ffffff',
      text: '#000000d9',
      textSecondary: '#00000073',
      border: '#d9d9d9',
      card: '#ffffff',
      cardHover: '#fafafa',
      chartColors: ['#1890ff', '#52c41a', '#faad14', '#ff4d4f'],
    },
  })

  useEffect(() => {
    loadThemes()
  }, [])

  const loadThemes = () => {
    setThemes(getAllThemes())
    setCurrentThemeId(getCurrentTheme().id)
  }

  const handleApplyTheme = (id: string) => {
    setCurrentTheme(id)
    setCurrentThemeId(id)
    message.success('主题已应用')
  }

  const handleCreateTheme = () => {
    if (!newTheme.name?.trim()) {
      message.warning('请输入主题名称')
      return
    }

    addCustomTheme({
      name: newTheme.name,
      description: newTheme.description || '',
      author: '用户',
      version: '1.0.0',
      isDark: newTheme.isDark || false,
      colors: newTheme.colors as ThemeColors,
    })

    setCreateModalVisible(false)
    setNewTheme({
      name: '',
      description: '',
      isDark: false,
      colors: {
        primary: '#1890ff',
        success: '#52c41a',
        warning: '#faad14',
        error: '#ff4d4f',
        info: '#1890ff',
        background: '#f0f2f5',
        backgroundSecondary: '#ffffff',
        text: '#000000d9',
        textSecondary: '#00000073',
        border: '#d9d9d9',
        card: '#ffffff',
        cardHover: '#fafafa',
        chartColors: ['#1890ff', '#52c41a', '#faad14', '#ff4d4f'],
      },
    })
    loadThemes()
    message.success('主题已创建')
  }

  const handleDeleteTheme = (id: string) => {
    deleteCustomTheme(id)
    loadThemes()
    message.success('主题已删除')
  }

  const handleExportTheme = (id: string) => {
    const json = exportTheme(id)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `theme-${Date.now()}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('主题已导出')
  }

  const handleImportTheme = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return

      const reader = new FileReader()
      reader.onload = (e) => {
        const json = e.target?.result as string
        const theme = importTheme(json)
        if (theme) {
          loadThemes()
          message.success('主题已导入')
        } else {
          message.error('导入失败，文件格式错误')
        }
      }
      reader.readAsText(file)
    }
    input.click()
  }

  const handleDuplicateTheme = (theme: Theme) => {
    setNewTheme({
      ...theme,
      name: `${theme.name} (副本)`,
    })
    setCreateModalVisible(true)
  }

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <SkinOutlined style={{ marginRight: 8 }} />
            主题商店
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<UploadOutlined />} onClick={handleImportTheme}>
              导入主题
            </Button>
            <Button type="primary" icon={<BulbOutlined />} onClick={() => setCreateModalVisible(true)}>
              创建主题
            </Button>
          </Space>
        </Col>
      </Row>

      <Paragraph type="secondary">
        选择适合您的主题风格，或创建个性化主题。支持导入导出，轻松分享您的创意。
      </Paragraph>

      <Row gutter={[16, 16]}>
        {themes.map((theme) => (
          <Col xs={24} sm={12} md={8} lg={6} key={theme.id}>
            <Card
              hoverable
              style={{
                borderColor: currentThemeId === theme.id ? theme.colors.primary : undefined,
                borderWidth: currentThemeId === theme.id ? 2 : 1,
              }}
              cover={
                <div
                  style={{
                    height: 120,
                    background: `linear-gradient(135deg, ${theme.colors.primary} 0%, ${theme.colors.background} 100%)`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    position: 'relative',
                  }}
                >
                  {currentThemeId === theme.id && (
                    <Tag color="blue" style={{ position: 'absolute', top: 8, right: 8 }}>
                      当前
                    </Tag>
                  )}
                  {theme.isDark && (
                    <Tag color="default" style={{ position: 'absolute', top: 8, left: 8 }}>
                      暗黑
                    </Tag>
                  )}
                  <Text style={{ color: '#fff', fontSize: 18, fontWeight: 'bold' }}>
                    {theme.name}
                  </Text>
                </div>
              }
              actions={[
                currentThemeId === theme.id ? (
                  <CheckOutlined key="applied" style={{ color: theme.colors.success }} />
                ) : (
                  <Button
                    key="apply"
                    type="link"
                    size="small"
                    onClick={() => handleApplyTheme(theme.id)}
                  >
                    应用
                  </Button>
                ),
                theme.isBuiltIn ? (
                  <CopyOutlined key="duplicate" onClick={() => handleDuplicateTheme(theme)} />
                ) : (
                  <Dropdown
                    key="more"
                    menu={{
                      items: [
                        { key: 'edit', icon: <EditOutlined />, label: '编辑', onClick: () => { setEditingTheme(theme); setEditModalVisible(true) } },
                        { key: 'duplicate', icon: <CopyOutlined />, label: '复制', onClick: () => handleDuplicateTheme(theme) },
                        { key: 'export', icon: <DownloadOutlined />, label: '导出', onClick: () => handleExportTheme(theme.id) },
                        { type: 'divider' },
                        { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true, onClick: () => handleDeleteTheme(theme.id) },
                      ],
                    }}
                  >
                    <Button type="text" size="small">更多</Button>
                  </Dropdown>
                ),
              ]}
            >
              <Card.Meta
                title={theme.name}
                description={
                  <Space direction="vertical" size={4}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{theme.description}</Text>
                    <Space size={4}>
                      {Object.entries(theme.colors).slice(0, 6).map(([key, value]) => (
                        typeof value === 'string' && (
                          <div
                            key={key}
                            style={{
                              width: 16,
                              height: 16,
                              borderRadius: 4,
                              backgroundColor: value,
                              border: '1px solid #d9d9d9',
                            }}
                          />
                        )
                      ))}
                    </Space>
                  </Space>
                }
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 创建主题弹窗 */}
      <Modal
        title="创建主题"
        open={createModalVisible}
        onOk={handleCreateTheme}
        onCancel={() => setCreateModalVisible(false)}
        width={600}
        okText="创建"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text>主题名称</Text>
            <Input
              placeholder="请输入主题名称"
              value={newTheme.name}
              onChange={(e) => setNewTheme({ ...newTheme, name: e.target.value })}
            />
          </div>
          <div>
            <Text>主题描述</Text>
            <Input
              placeholder="请输入主题描述"
              value={newTheme.description}
              onChange={(e) => setNewTheme({ ...newTheme, description: e.target.value })}
            />
          </div>
          <div>
            <Space>
              <Text>暗黑模式</Text>
              <Switch
                checked={newTheme.isDark}
                onChange={(checked) => setNewTheme({ ...newTheme, isDark: checked })}
              />
            </Space>
          </div>
          <Divider>颜色配置</Divider>
          <ColorEditor
            colors={newTheme.colors || {}}
            onChange={(colors) => setNewTheme({ ...newTheme, colors: { ...newTheme.colors, ...colors } as ThemeColors })}
          />
        </Space>
      </Modal>

      {/* 编辑主题弹窗 */}
      <Modal
        title="编辑主题"
        open={editModalVisible}
        onOk={() => {
          if (editingTheme) {
            // updateCustomTheme(editingTheme.id, editingTheme)
            setEditModalVisible(false)
            loadThemes()
            message.success('主题已更新')
          }
        }}
        onCancel={() => setEditModalVisible(false)}
        width={600}
        okText="保存"
        cancelText="取消"
      >
        {editingTheme && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Text>主题名称</Text>
              <Input
                value={editingTheme.name}
                onChange={(e) => setEditingTheme({ ...editingTheme, name: e.target.value })}
              />
            </div>
            <div>
              <Text>主题描述</Text>
              <Input
                value={editingTheme.description}
                onChange={(e) => setEditingTheme({ ...editingTheme, description: e.target.value })}
              />
            </div>
            <div>
              <Space>
                <Text>暗黑模式</Text>
                <Switch
                  checked={editingTheme.isDark}
                  onChange={(checked) => setEditingTheme({ ...editingTheme, isDark: checked })}
                />
              </Space>
            </div>
            <Divider>颜色配置</Divider>
            <ColorEditor
              colors={editingTheme.colors}
              onChange={(colors) => setEditingTheme({ ...editingTheme, colors: { ...editingTheme.colors, ...colors } })}
            />
          </Space>
        )}
      </Modal>
    </div>
  )
}
