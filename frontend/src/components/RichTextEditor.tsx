/**
 * 富文本编辑器组件
 * 基于浏览器的 contentEditable 实现
 */

import { useRef, useState, useCallback, useEffect } from 'react'
import { Button, Tooltip, Space, Divider, Select, Input, Popover } from 'antd'
import {
  BoldOutlined,
  ItalicOutlined,
  UnderlineOutlined,
  StrikethroughOutlined,
  OrderedListOutlined,
  UnorderedListOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
  LinkOutlined,
  PictureOutlined,
  CodeOutlined,
  ClearOutlined,
  UndoOutlined,
  RedoOutlined,
  FontColorsOutlined,
  BgColorsOutlined,
} from '@ant-design/icons'

export interface RichTextEditorProps {
  value?: string
  onChange?: (html: string) => void
  placeholder?: string
  height?: number
  minHeight?: number
  maxHeight?: number
  disabled?: boolean
  toolbar?: string[]
  onImageUpload?: (file: File) => Promise<string>
}

const defaultToolbar = [
  'bold', 'italic', 'underline', 'strikeThrough',
  '|', 'formatBlock', 'fontSize', 'foreColor', 'hiliteColor',
  '|', 'justifyLeft', 'justifyCenter', 'justifyRight',
  '|', 'insertOrderedList', 'insertUnorderedList',
  '|', 'link', 'image', 'code',
  '|', 'removeFormat', 'undo', 'redo',
]

const fontSizes = ['1', '2', '3', '4', '5', '6', '7']
const headings = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const colors = [
  '#000000', '#333333', '#666666', '#999999', '#cccccc', '#ffffff',
  '#ff0000', '#ff6600', '#ffcc00', '#ffff00', '#99cc00', '#339966',
  '#00cccc', '#0066ff', '#9900ff', '#ff00ff', '#cc0066', '#ff3399',
]

/**
 * 简单 HTML 消毒器（DOMPurify 不可用时回退）
 * 移除 script 标签、javascript: 协议、以及 on* 事件处理器
 */
function simpleSanitize(html: string): string {
  if (!html) return html
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/javascript:/gi, 'javascript-blocked:')
    .replace(/\s+on\w+\s*=\s*["']?[^"'>]*["']?/gi, '')
    .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
    .replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '')
    .replace(/<embed\b[^<]*>/gi, '')
}

export function RichTextEditor({
  value = '',
  onChange,
  placeholder = '请输入内容...',
  height = 300,
  minHeight = 100,
  maxHeight = 600,
  disabled = false,
  toolbar = defaultToolbar,
  onImageUpload,
}: RichTextEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const [focused, setFocused] = useState(false)
  const [linkUrl, setLinkUrl] = useState('')
  const [showLinkPopover, setShowLinkPopover] = useState(false)

  // 初始化内容
  useEffect(() => {
    if (editorRef.current && value && !editorRef.current.innerHTML) {
      editorRef.current.innerHTML = simpleSanitize(value)
    }
  }, [value])

  // 执行命令
  const execCommand = useCallback((command: string, value?: string) => {
    document.execCommand(command, false, value)
    editorRef.current?.focus()
    triggerChange()
  }, [])

  // 触发变更
  const triggerChange = useCallback(() => {
    if (editorRef.current && onChange) {
      onChange(simpleSanitize(editorRef.current.innerHTML))
    }
  }, [onChange])

  // 输入处理
  const handleInput = useCallback(() => {
    triggerChange()
  }, [triggerChange])

  // 插入链接
  const insertLink = useCallback(() => {
    if (linkUrl) {
      execCommand('createLink', linkUrl)
      setLinkUrl('')
      setShowLinkPopover(false)
    }
  }, [linkUrl, execCommand])

  // 插入图片
  const insertImage = useCallback(async () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'

    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (file) {
        let imageUrl = URL.createObjectURL(file)

        if (onImageUpload) {
          imageUrl = await onImageUpload(file)
        }

        execCommand('insertImage', imageUrl)
      }
    }

    input.click()
  }, [execCommand, onImageUpload])

  // 插入代码块
  const insertCode = useCallback(() => {
    const selection = window.getSelection()
    if (selection && selection.toString()) {
      const code = document.createElement('code')
      code.style.backgroundColor = '#f5f5f5'
      code.style.padding = '2px 6px'
      code.style.borderRadius = '4px'
      code.style.fontFamily = 'monospace'
      code.textContent = selection.toString()

      const range = selection.getRangeAt(0)
      range.deleteContents()
      range.insertNode(code)
    }
  }, [])

  // 渲染工具栏按钮
  const renderToolbarButton = (command: string, icon?: React.ReactNode, tooltip?: string) => {
    if (command === '|') {
      return <Divider type="vertical" key={Math.random()} />
    }

    const handleClick = () => {
      switch (command) {
        case 'link':
          setShowLinkPopover(true)
          break
        case 'image':
          insertImage()
          break
        case 'code':
          insertCode()
          break
        case 'undo':
          execCommand('undo')
          break
        case 'redo':
          execCommand('redo')
          break
        default:
          execCommand(command)
      }
    }

    return (
      <Tooltip key={command} title={tooltip || command}>
        <Button
          type="text"
          size="small"
          icon={icon}
          onClick={handleClick}
          disabled={disabled}
        />
      </Tooltip>
    )
  }

  // 渲染颜色选择器
  const renderColorPicker = (command: string, icon: React.ReactNode, tooltip: string) => (
    <Popover
      key={command}
      content={
        <div style={{ width: 180 }}>
          {colors.map(color => (
            <div
              key={color}
              style={{
                width: 24,
                height: 24,
                backgroundColor: color,
                display: 'inline-block',
                margin: 2,
                cursor: 'pointer',
                border: '1px solid #ddd',
              }}
              onClick={() => execCommand(command, color)}
            />
          ))}
        </div>
      }
      trigger="click"
    >
      <Tooltip title={tooltip}>
        <Button type="text" size="small" icon={icon} disabled={disabled} />
      </Tooltip>
    </Popover>
  )

  // 渲染下拉选择器
  const renderSelect = (command: string, options: string[], tooltip: string) => (
    <Select
      key={command}
      size="small"
      style={{ width: 80 }}
      placeholder={tooltip}
      onChange={(value) => execCommand(command, value)}
      disabled={disabled}
      options={options.map(opt => ({ label: opt, value: opt }))}
    />
  )

  // 渲染工具栏
  const renderToolbar = () => {
    const buttons: React.ReactNode[] = []

    for (const item of toolbar) {
      switch (item) {
        case 'bold':
          buttons.push(renderToolbarButton('bold', <BoldOutlined />, '粗体'))
          break
        case 'italic':
          buttons.push(renderToolbarButton('italic', <ItalicOutlined />, '斜体'))
          break
        case 'underline':
          buttons.push(renderToolbarButton('underline', <UnderlineOutlined />, '下划线'))
          break
        case 'strikeThrough':
          buttons.push(renderToolbarButton('strikeThrough', <StrikethroughOutlined />, '删除线'))
          break
        case 'justifyLeft':
          buttons.push(renderToolbarButton('justifyLeft', <AlignLeftOutlined />, '左对齐'))
          break
        case 'justifyCenter':
          buttons.push(renderToolbarButton('justifyCenter', <AlignCenterOutlined />, '居中'))
          break
        case 'justifyRight':
          buttons.push(renderToolbarButton('justifyRight', <AlignRightOutlined />, '右对齐'))
          break
        case 'insertOrderedList':
          buttons.push(renderToolbarButton('insertOrderedList', <OrderedListOutlined />, '有序列表'))
          break
        case 'insertUnorderedList':
          buttons.push(renderToolbarButton('insertUnorderedList', <UnorderedListOutlined />, '无序列表'))
          break
        case 'foreColor':
          buttons.push(renderColorPicker('foreColor', <FontColorsOutlined />, '文字颜色'))
          break
        case 'hiliteColor':
          buttons.push(renderColorPicker('hiliteColor', <BgColorsOutlined />, '背景色'))
          break
        case 'formatBlock':
          buttons.push(renderSelect('formatBlock', headings, '标题'))
          break
        case 'fontSize':
          buttons.push(renderSelect('fontSize', fontSizes, '字号'))
          break
        case 'link':
          buttons.push(
            <Popover
              key="link"
              content={
                <Space.Compact>
                  <Input
                    placeholder="输入链接地址"
                    value={linkUrl}
                    onChange={e => setLinkUrl(e.target.value)}
                    style={{ width: 200 }}
                  />
                  <Button type="primary" onClick={insertLink}>确定</Button>
                </Space.Compact>
              }
              open={showLinkPopover}
              onOpenChange={setShowLinkPopover}
            >
              <Tooltip title="插入链接">
                <Button type="text" size="small" icon={<LinkOutlined />} disabled={disabled} />
              </Tooltip>
            </Popover>
          )
          break
        case 'image':
          buttons.push(renderToolbarButton('image', <PictureOutlined />, '插入图片'))
          break
        case 'code':
          buttons.push(renderToolbarButton('code', <CodeOutlined />, '代码'))
          break
        case 'removeFormat':
          buttons.push(renderToolbarButton('removeFormat', <ClearOutlined />, '清除格式'))
          break
        case 'undo':
          buttons.push(renderToolbarButton('undo', <UndoOutlined />, '撤销'))
          break
        case 'redo':
          buttons.push(renderToolbarButton('redo', <RedoOutlined />, '重做'))
          break
        case '|':
          buttons.push(<Divider key="divider" type="vertical" />)
          break
        default:
          buttons.push(renderToolbarButton(item))
      }
    }

    return buttons
  }

  return (
    <div
      style={{
        border: `1px solid ${focused ? '#1890ff' : '#d9d9d9'}`,
        borderRadius: 6,
        overflow: 'hidden',
      }}
    >
      {/* 工具栏 */}
      <div
        style={{
          padding: '4px 8px',
          borderBottom: '1px solid #f0f0f0',
          background: '#fafafa',
        }}
      >
        <Space size={0}>{renderToolbar()}</Space>
      </div>

      {/* 编辑区域 */}
      <div
        ref={editorRef}
        contentEditable={!disabled}
        onInput={handleInput}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          padding: 12,
          minHeight,
          maxHeight,
          height,
          overflow: 'auto',
          outline: 'none',
          lineHeight: 1.6,
        }}
        data-placeholder={placeholder}
        suppressContentEditableWarning
      >
        {value}
      </div>

      {/* 样式 */}
      <style>{`
        [data-placeholder]:empty:before {
          content: attr(data-placeholder);
          color: #bfbfbf;
          pointer-events: none;
        }
      `}</style>
    </div>
  )
}

export default RichTextEditor
