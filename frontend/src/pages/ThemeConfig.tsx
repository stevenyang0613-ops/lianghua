/**
 * 主题配置页面
 * 支持主题色、字体大小、布局模式等自定义
 */

import { useEffect, useState } from 'react'
import {
  Card, Row, Col, Typography, Radio, Switch, Slider, Button, Space,
  ColorPicker, Divider, message, Modal, Input, List, Tag, Tooltip, Alert
} from 'antd'
import {
  SunOutlined, MoonOutlined, DesktopOutlined,
  LayoutOutlined, FontSizeOutlined, BgColorsOutlined,
  DownloadOutlined, UploadOutlined, ReloadOutlined,
  CheckOutlined, CopyOutlined
} from '@ant-design/icons'
import {
  useThemeConfigStore,
  presetThemes,
  applyThemeToDOM,
  type ThemeMode,
  type LayoutMode,
  type FontSize,
} from '../stores/useThemeConfigStore'

const { Title, Text, Paragraph } = Typography

const PRESET_COLORS = [
  { label: '默认蓝', color: '#1890ff' },
  { label: '海洋蓝', color: '#0052cc' },
  { label: '日落橙', color: '#fa8c16' },
  { label: '森林绿', color: '#52c41a' },
  { label: '优雅紫', color: '#722ed1' },
  { label: '活力红', color: '#f5222d' },
  { label: '青色', color: '#13c2c2' },
  { label: '金色', color: '#faad14' },
]

export default function ThemeConfigPage() {
  const {
    mode, setMode,
    layout, setLayout,
    fontSize, setFontSize,
    colors, setPrimaryColor, setColors,
    compactMode, toggleCompactMode,
    animationsEnabled, toggleAnimations,
    borderRadius, setBorderRadius,
    sidebarWidth, setSidebarWidth,
    headerHeight, setHeaderHeight,
    showBreadcrumb, toggleBreadcrumb,
    resetTheme, exportTheme, importTheme,
  } = useThemeConfigStore()

  const [importModalVisible, setImportModalVisible] = useState(false)
  const [importValue, setImportValue] = useState('')
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null)

  // 实时预览
  useEffect(() => {
    applyThemeToDOM(useThemeConfigStore.getState())
  }, [mode, colors, compactMode, animationsEnabled, borderRadius, fontSize])

  const handleApplyPreset = (presetName: string) => {
    const preset = presetThemes[presetName]
    if (preset) {
      Object.entries(preset).forEach(([key, value]) => {
        if (key === 'colors' && value) {
          setColors(value as Partial<typeof colors>)
        } else if (key === 'mode') {
          setMode(value as ThemeMode)
        } else if (key === 'layout') {
          setLayout(value as LayoutMode)
        } else if (key === 'fontSize') {
          setFontSize(value as FontSize)
        }
      })
      setSelectedPreset(presetName)
      message.success(`已应用「${presetName}」主题`)
    }
  }

  const handleExport = () => {
    const json = exportTheme()
    navigator.clipboard.writeText(json)
    message.success('主题配置已复制到剪贴板')
  }

  const handleImport = () => {
    if (importValue.trim()) {
      const success = importTheme(importValue)
      if (success) {
        message.success('主题配置已导入')
        setImportModalVisible(false)
        setImportValue('')
      } else {
        message.error('导入失败，请检查 JSON 格式')
      }
    }
  }

  const handleReset = () => {
    Modal.confirm({
      title: '确认重置',
      content: '确定要重置为默认主题吗？',
      onOk: () => {
        resetTheme()
        setSelectedPreset(null)
        message.success('已重置为默认主题')
      },
    })
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={4}>
        <BgColorsOutlined /> 主题配置
      </Title>
      <Paragraph type="secondary">
        自定义应用外观，包括主题色、字体大小、布局模式等
      </Paragraph>

      {/* 预设主题 */}
      <Card title="预设主题" style={{ marginBottom: 16 }}>
        <List
          grid={{ gutter: 16, xs: 2, sm: 3, md: 4, lg: 6 }}
          dataSource={Object.entries(presetThemes)}
          renderItem={([name, config]) => (
            <List.Item>
              <Card
                hoverable
                size="small"
                style={{
                  textAlign: 'center',
                  border: selectedPreset === name ? '2px solid #1890ff' : undefined,
                }}
                onClick={() => handleApplyPreset(name)}
              >
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    background: config.colors?.primary || '#1890ff',
                    margin: '0 auto 8px',
                  }}
                />
                <Text>{name}</Text>
                {selectedPreset === name && (
                  <CheckOutlined style={{ color: '#1890ff', marginLeft: 4 }} />
                )}
              </Card>
            </List.Item>
          )}
        />
      </Card>

      <Row gutter={16}>
        {/* 基础设置 */}
        <Col span={12}>
          <Card title="基础设置" style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 24 }}>
              <Text strong>主题模式</Text>
              <Radio.Group
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                style={{ marginTop: 8 }}
              >
                <Radio.Button value="light"><SunOutlined /> 浅色</Radio.Button>
                <Radio.Button value="dark"><MoonOutlined /> 深色</Radio.Button>
                <Radio.Button value="auto"><DesktopOutlined /> 跟随系统</Radio.Button>
              </Radio.Group>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Text strong>布局模式</Text>
              <Radio.Group
                value={layout}
                onChange={(e) => setLayout(e.target.value)}
                style={{ marginTop: 8 }}
              >
                <Radio.Button value="side">侧边栏</Radio.Button>
                <Radio.Button value="top">顶部导航</Radio.Button>
                <Radio.Button value="mix">混合模式</Radio.Button>
              </Radio.Group>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Text strong>字体大小</Text>
              <Radio.Group
                value={fontSize}
                onChange={(e) => setFontSize(e.target.value)}
                style={{ marginTop: 8 }}
              >
                <Radio.Button value="small"><FontSizeOutlined /> 小</Radio.Button>
                <Radio.Button value="default">默认</Radio.Button>
                <Radio.Button value="large"><FontSizeOutlined /> 大</Radio.Button>
              </Radio.Group>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Text strong>圆角大小: {borderRadius}px</Text>
              <Slider
                min={0}
                max={16}
                value={borderRadius}
                onChange={setBorderRadius}
                style={{ marginTop: 8 }}
              />
            </div>
          </Card>
        </Col>

        {/* 主题色 */}
        <Col span={12}>
          <Card title="主题色" style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 24 }}>
              <Text strong>预设颜色</Text>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {PRESET_COLORS.map((item) => (
                  <Tooltip key={item.color} title={item.label}>
                    <div
                      onClick={() => setPrimaryColor(item.color)}
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 4,
                        background: item.color,
                        cursor: 'pointer',
                        border: colors.primary === item.color ? '2px solid #000' : '2px solid transparent',
                      }}
                    />
                  </Tooltip>
                ))}
              </div>
            </div>

            <div style={{ marginBottom: 24 }}>
              <Text strong>自定义颜色</Text>
              <div style={{ marginTop: 8, display: 'flex', gap: 16 }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>主色</Text>
                  <ColorPicker
                    value={colors.primary}
                    onChange={(color) => setPrimaryColor(color.toHexString())}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>成功</Text>
                  <ColorPicker
                    value={colors.success}
                    onChange={(color) => setColors({ success: color.toHexString() })}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>警告</Text>
                  <ColorPicker
                    value={colors.warning}
                    onChange={(color) => setColors({ warning: color.toHexString() })}
                  />
                </div>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>错误</Text>
                  <ColorPicker
                    value={colors.error}
                    onChange={(color) => setColors({ error: color.toHexString() })}
                  />
                </div>
              </div>
            </div>

            <Alert
              type="info"
              message="主题色会应用到按钮、链接、选中状态等元素"
              showIcon
              style={{ marginTop: 16 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 高级设置 */}
      <Card title="高级设置" style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col span={8}>
            <div style={{ marginBottom: 16 }}>
              <Text strong>紧凑模式</Text>
              <div style={{ marginTop: 8 }}>
                <Switch checked={compactMode} onChange={toggleCompactMode} />
                <Text type="secondary" style={{ marginLeft: 8 }}>减小元素间距</Text>
              </div>
            </div>
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 16 }}>
              <Text strong>动画效果</Text>
              <div style={{ marginTop: 8 }}>
                <Switch checked={animationsEnabled} onChange={toggleAnimations} />
                <Text type="secondary" style={{ marginLeft: 8 }}>启用过渡动画</Text>
              </div>
            </div>
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 16 }}>
              <Text strong>显示面包屑</Text>
              <div style={{ marginTop: 8 }}>
                <Switch checked={showBreadcrumb} onChange={toggleBreadcrumb} />
              </div>
            </div>
          </Col>
        </Row>

        <Divider />

        <Row gutter={24}>
          <Col span={12}>
            <div>
              <Text strong>侧边栏宽度: {sidebarWidth}px</Text>
              <Slider
                min={180}
                max={300}
                value={sidebarWidth}
                onChange={setSidebarWidth}
                style={{ marginTop: 8 }}
              />
            </div>
          </Col>
          <Col span={12}>
            <div>
              <Text strong>头部高度: {headerHeight}px</Text>
              <Slider
                min={48}
                max={80}
                value={headerHeight}
                onChange={setHeaderHeight}
                style={{ marginTop: 8 }}
              />
            </div>
          </Col>
        </Row>
      </Card>

      {/* 导入导出 */}
      <Card title="导入/导出">
        <Space>
          <Button icon={<DownloadOutlined />} onClick={handleExport}>
            导出配置
          </Button>
          <Button icon={<UploadOutlined />} onClick={() => setImportModalVisible(true)}>
            导入配置
          </Button>
          <Button icon={<ReloadOutlined />} danger onClick={handleReset}>
            重置默认
          </Button>
        </Space>
      </Card>

      {/* 导入 Modal */}
      <Modal
        title="导入主题配置"
        open={importModalVisible}
        onOk={handleImport}
        onCancel={() => setImportModalVisible(false)}
        width={600}
      >
        <Paragraph type="secondary">
          请粘贴导出的 JSON 配置：
        </Paragraph>
        <Input.TextArea
          value={importValue}
          onChange={(e) => setImportValue(e.target.value)}
          rows={10}
          placeholder='{"mode":"light","colors":{"primary":"#1890ff"}}'
        />
      </Modal>
    </div>
  )
}
