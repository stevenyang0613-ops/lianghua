/**
 * 主题编辑器组件
 * 可视化主题编辑，实时预览，导出配置
 */

import { useState, useCallback, useEffect } from 'react'
import { Modal, Form, Input, ColorPicker, Select, Slider, Button, Space, Card, Row, Col, Divider, message, Tabs } from 'antd'
import { PaletteOutlined, DownloadOutlined, UploadOutlined, UndoOutlined, SaveOutlined } from '@ant-design/icons'
import type { Color } from 'antd/es/color-picker'

export interface ThemeConfig {
  name: string
  primaryColor: string
  successColor: string
  warningColor: string
  errorColor: string
  infoColor: string
  textColor: string
  textColorSecondary: string
  backgroundColor: string
  backgroundColorSecondary: string
  borderColor: string
  borderRadius: number
  fontSize: number
  fontFamily: string
}

const defaultTheme: ThemeConfig = {
  name: '默认主题',
  primaryColor: '#1890ff',
  successColor: '#52c41a',
  warningColor: '#faad14',
  errorColor: '#ff4d4f',
  infoColor: '#1890ff',
  textColor: '#000000d9',
  textColorSecondary: '#00000073',
  backgroundColor: '#ffffff',
  backgroundColorSecondary: '#fafafa',
  borderColor: '#d9d9d9',
  borderRadius: 6,
  fontSize: 14,
  fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial',
}

const presetThemes: Record<string, Partial<ThemeConfig>> = {
  default: {},
  dark: {
    name: '暗色主题',
    textColor: '#ffffffd9',
    textColorSecondary: '#ffffff73',
    backgroundColor: '#141414',
    backgroundColorSecondary: '#1f1f1f',
    borderColor: '#434343',
  },
  compact: {
    name: '紧凑主题',
    borderRadius: 2,
    fontSize: 12,
  },
  green: {
    name: '绿色主题',
    primaryColor: '#52c41a',
  },
  purple: {
    name: '紫色主题',
    primaryColor: '#722ed1',
  },
}

export interface ThemeEditorProps {
  open: boolean
  onClose: () => void
  value?: ThemeConfig
  onChange?: (theme: ThemeConfig) => void
  onSave?: (theme: ThemeConfig) => void
}

export function ThemeEditor({ open, onClose, value, onChange, onSave }: ThemeEditorProps) {
  const [theme, setTheme] = useState<ThemeConfig>(value || defaultTheme)
  const [originalTheme, setOriginalTheme] = useState<ThemeConfig>(value || defaultTheme)
  const [activeTab, setActiveTab] = useState('colors')

  // 同步外部值
  useEffect(() => {
    if (value) {
      setTheme(value)
      setOriginalTheme(value)
    }
  }, [value])

  // 更新主题
  const updateTheme = useCallback(<K extends keyof ThemeConfig>(key: K, value: ThemeConfig[K]) => {
    const newTheme = { ...theme, [key]: value }
    setTheme(newTheme)
    onChange?.(newTheme)
  }, [theme, onChange])

  // 应用预设主题
  const applyPreset = useCallback((presetName: string) => {
    const preset = presetThemes[presetName]
    if (preset) {
      const newTheme = { ...defaultTheme, ...preset }
      setTheme(newTheme)
      onChange?.(newTheme)
    }
  }, [onChange])

  // 重置主题
  const resetTheme = useCallback(() => {
    setTheme(originalTheme)
    onChange?.(originalTheme)
  }, [originalTheme, onChange])

  // 导出配置
  const exportTheme = useCallback(() => {
    const json = JSON.stringify(theme, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `theme-${theme.name}.json`
    link.click()
    URL.revokeObjectURL(url)
    message.success('主题已导出')
  }, [theme])

  // 导入配置
  const importTheme = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'

    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (file) {
        const reader = new FileReader()
        reader.onload = (event) => {
          try {
            const imported = JSON.parse(event.target?.result as string) as ThemeConfig
            setTheme(imported)
            onChange?.(imported)
            message.success('主题已导入')
          } catch {
            message.error('导入失败：无效的主题文件')
          }
        }
        reader.readAsText(file)
      }
    }

    input.click()
  }, [onChange])

  // 生成 CSS 变量
  const generateCSS = useCallback(() => {
    return `
:root {
  --primary-color: ${theme.primaryColor};
  --success-color: ${theme.successColor};
  --warning-color: ${theme.warningColor};
  --error-color: ${theme.errorColor};
  --info-color: ${theme.infoColor};
  --text-color: ${theme.textColor};
  --text-color-secondary: ${theme.textColorSecondary};
  --background-color: ${theme.backgroundColor};
  --background-color-secondary: ${theme.backgroundColorSecondary};
  --border-color: ${theme.borderColor};
  --border-radius: ${theme.borderRadius}px;
  --font-size: ${theme.fontSize}px;
  --font-family: ${theme.fontFamily};
}
`
  }, [theme])

  // 应用预览样式
  const previewStyle = {
    '--primary-color': theme.primaryColor,
    '--success-color': theme.successColor,
    '--warning-color': theme.warningColor,
    '--error-color': theme.errorColor,
    '--background-color': theme.backgroundColor,
    '--text-color': theme.textColor,
    '--border-radius': `${theme.borderRadius}px`,
    fontSize: theme.fontSize,
  } as React.CSSProperties

  return (
    <Modal
      title={
        <Space>
          <PaletteOutlined />
          主题编辑器
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={800}
      footer={[
        <Button key="reset" icon={<UndoOutlined />} onClick={resetTheme}>
          重置
        </Button>,
        <Button key="export" icon={<DownloadOutlined />} onClick={exportTheme}>
          导出
        </Button>,
        <Button key="import" icon={<UploadOutlined />} onClick={importTheme}>
          导入
        </Button>,
        <Button
          key="save"
          type="primary"
          icon={<SaveOutlined />}
          onClick={() => {
            onSave?.(theme)
            setOriginalTheme(theme)
            message.success('主题已保存')
          }}
        >
          保存
        </Button>,
      ]}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'colors',
            label: '颜色配置',
            children: (
              <div>
                {/* 预设主题 */}
                <Form.Item label="预设主题">
                  <Select
                    style={{ width: '100%' }}
                    placeholder="选择预设主题"
                    onChange={applyPreset}
                    options={Object.entries(presetThemes).map(([key, val]) => ({
                      label: val.name || key,
                      value: key,
                    }))}
                  />
                </Form.Item>

                <Divider />

                {/* 主要颜色 */}
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="主色调">
                      <ColorPicker
                        value={theme.primaryColor}
                        onChange={(color: Color) => updateTheme('primaryColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item label="成功色">
                      <ColorPicker
                        value={theme.successColor}
                        onChange={(color: Color) => updateTheme('successColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="警告色">
                      <ColorPicker
                        value={theme.warningColor}
                        onChange={(color: Color) => updateTheme('warningColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item label="错误色">
                      <ColorPicker
                        value={theme.errorColor}
                        onChange={(color: Color) => updateTheme('errorColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Divider />

                {/* 文字和背景 */}
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="文字颜色">
                      <ColorPicker
                        value={theme.textColor}
                        onChange={(color: Color) => updateTheme('textColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item label="次要文字">
                      <ColorPicker
                        value={theme.textColorSecondary}
                        onChange={(color: Color) => updateTheme('textColorSecondary', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="背景色">
                      <ColorPicker
                        value={theme.backgroundColor}
                        onChange={(color: Color) => updateTheme('backgroundColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item label="次要背景">
                      <ColorPicker
                        value={theme.backgroundColorSecondary}
                        onChange={(color: Color) => updateTheme('backgroundColorSecondary', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item label="边框颜色">
                      <ColorPicker
                        value={theme.borderColor}
                        onChange={(color: Color) => updateTheme('borderColor', color.toHexString())}
                        showText
                      />
                    </Form.Item>
                  </Col>
                </Row>
              </div>
            ),
          },
          {
            key: 'typography',
            label: '排版设置',
            children: (
              <div>
                <Form.Item label="字体大小">
                  <Slider
                    min={12}
                    max={20}
                    value={theme.fontSize}
                    onChange={(value) => updateTheme('fontSize', value)}
                    marks={{ 12: '12px', 14: '14px', 16: '16px', 18: '18px', 20: '20px' }}
                  />
                </Form.Item>

                <Form.Item label="圆角大小">
                  <Slider
                    min={0}
                    max={16}
                    value={theme.borderRadius}
                    onChange={(value) => updateTheme('borderRadius', value)}
                    marks={{ 0: '0px', 4: '4px', 8: '8px', 12: '12px', 16: '16px' }}
                  />
                </Form.Item>

                <Form.Item label="字体">
                  <Select
                    value={theme.fontFamily}
                    onChange={(value) => updateTheme('fontFamily', value)}
                    options={[
                      { label: '系统默认', value: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial' },
                      { label: '微软雅黑', value: '"Microsoft YaHei", "微软雅黑"' },
                      { label: '宋体', value: 'SimSun, "宋体"' },
                      { label: '黑体', value: 'SimHei, "黑体"' },
                      { label: '等宽字体', value: '"SF Mono", "Monaco", "Inconsolata", "Fira Mono", monospace' },
                    ]}
                  />
                </Form.Item>
              </div>
            ),
          },
          {
            key: 'preview',
            label: '预览',
            children: (
              <Card
                title="实时预览"
                style={{
                  ...previewStyle,
                  backgroundColor: theme.backgroundColor,
                  color: theme.textColor,
                  borderColor: theme.borderColor,
                }}
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div>
                    <Button type="primary" style={{ borderRadius: theme.borderRadius }}>
                      主要按钮
                    </Button>
                    <Button style={{ marginLeft: 8, borderRadius: theme.borderRadius }}>默认按钮</Button>
                    <Button type="dashed" style={{ marginLeft: 8, borderRadius: theme.borderRadius }}>
                      虚线按钮
                    </Button>
                  </div>
                  <div>
                    <span style={{ color: theme.primaryColor }}>主色文字</span>
                    <span style={{ color: theme.successColor, marginLeft: 16 }}>成功文字</span>
                    <span style={{ color: theme.warningColor, marginLeft: 16 }}>警告文字</span>
                    <span style={{ color: theme.errorColor, marginLeft: 16 }}>错误文字</span>
                  </div>
                  <div style={{ padding: 16, backgroundColor: theme.backgroundColorSecondary, borderRadius: theme.borderRadius }}>
                    次要背景区域
                  </div>
                </Space>
              </Card>
            ),
          },
          {
            key: 'code',
            label: 'CSS 代码',
            children: (
              <div>
                <Form.Item label="主题名称">
                  <Input
                    value={theme.name}
                    onChange={(e) => updateTheme('name', e.target.value)}
                    placeholder="输入主题名称"
                  />
                </Form.Item>
                <Form.Item label="CSS 变量">
                  <Input.TextArea
                    value={generateCSS()}
                    rows={15}
                    readOnly
                    style={{ fontFamily: 'monospace' }}
                  />
                </Form.Item>
              </div>
            ),
          },
        ]}
      />
    </Modal>
  )
}

export default ThemeEditor
