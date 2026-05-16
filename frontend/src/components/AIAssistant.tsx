/**
 * AI 智能助手组件
 */

import { useState, useRef, useEffect } from 'react'
import { Modal, Input, Button, Space, Typography, List, Avatar, Tag, Spin, Dropdown, Popconfirm, message, Tooltip } from 'antd'
import { RobotOutlined, SendOutlined, UserOutlined, DeleteOutlined, PlusOutlined, SettingOutlined, ThunderboltOutlined, BulbOutlined } from '@ant-design/icons'
import { getConversations, createConversation, deleteConversation, addMessage, callAI, PRESET_PROMPTS, parseQuickCommand, type AIConversation, type AIMessage, getAPIKey, setAPIKey } from '../utils/aiService'

const { TextArea } = Input
const { Text, Paragraph } = Typography

interface AIAssistantProps {
  visible: boolean
  onClose: () => void
  context?: {
    currentCode?: string
    currentPrice?: number
  }
}

export default function AIAssistant({ visible, onClose, context }: AIAssistantProps) {
  const [conversations, setConversations] = useState<AIConversation[]>([])
  const [currentConversation, setCurrentConversation] = useState<AIConversation | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [settingsVisible, setSettingsVisible] = useState(false)
  const [apiKey, setApiKeyState] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (visible) {
      setConversations(getConversations())
      void getAPIKey().then((key: string | null) => setApiKeyState(key || ''))
    }
  }, [visible])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [currentConversation?.messages])

  const handleNewConversation = () => {
    const conv = createConversation()
    setConversations(getConversations())
    setCurrentConversation(conv)
  }

  const handleSelectConversation = (conv: AIConversation) => {
    setCurrentConversation(conv)
  }

  const handleDeleteConversation = (id: string) => {
    deleteConversation(id)
    const updated = getConversations()
    setConversations(updated)
    if (currentConversation?.id === id) {
      setCurrentConversation(updated[0] || null)
    }
    message.success('对话已删除')
  }

  const handleSend = async () => {
    if (!input.trim() || loading) return

    // 检查 API Key
    const currentKey = await getAPIKey()
    if (!currentKey) {
      message.warning('请先配置 API Key')
      setSettingsVisible(true)
      return
    }

    // 确保有对话
    let conversation = currentConversation
    if (!conversation) {
      conversation = createConversation(input.slice(0, 20))
      setConversations(getConversations())
      setCurrentConversation(conversation)
    }

    // 解析快捷命令
    const command = parseQuickCommand(input)
    if (command) {
      const commandMessage: AIMessage = {
        role: 'user',
        content: input,
        timestamp: Date.now(),
      }
      addMessage(conversation.id, commandMessage)
      setCurrentConversation(conversation)
      setInput('')

      // 处理命令
      const response = await handleCommand(command)
      addMessage(conversation.id, { role: 'assistant', content: response })
      setCurrentConversation(conversation)
      return
    }

    // 添加用户消息
    const userMessage: AIMessage = {
      role: 'user',
      content: input,
      timestamp: Date.now(),
    }
    addMessage(conversation.id, userMessage)
    setCurrentConversation(conversation)
    setInput('')
    setLoading(true)

    try {
      // 调用 AI
      const messages = [...(conversation.messages || []), userMessage]
      const response = await callAI(messages, context)

      // 添加 AI 回复
      addMessage(conversation.id, { role: 'assistant', content: response })
      setCurrentConversation(conversation)
    } catch (err) {
      message.error(String(err))
    } finally {
      setLoading(false)
    }
  }

  const handleCommand = async (command: { type: string; params: Record<string, string> }): Promise<string> => {
    switch (command.type) {
      case 'query':
        return `正在查询 ${command.params.code} 的信息...\n\n该功能需要连接实时数据源，当前为模拟回复。`
      case 'analyze':
        return '正在分析当前标的的技术指标...\n\n基于 MACD、RSI、KDJ 等指标的综合分析结果将在实际接入数据后显示。'
      case 'alert':
        return `已设置预警：当价格${command.params.type === 'above' ? '高于' : '低于'} ${command.params.value} 时提醒您。`
      case 'buy':
        return `模拟买入指令：${command.params.code} 数量 ${command.params.quantity}\n\n此功能需要连接交易接口，当前为模拟回复。`
      case 'sell':
        return `模拟卖出指令：${command.params.code} 数量 ${command.params.quantity}\n\n此功能需要连接交易接口，当前为模拟回复。`
      default:
        return '未知命令，请使用 /查询、/分析、/预警、/买入、/卖出 等命令。'
    }
  }

  const handlePresetPrompt = (prompt: string) => {
    setInput(prompt)
  }

  const handleSaveApiKey = async () => {
    await setAPIKey(apiKey)
    setSettingsVisible(false)
    message.success('API Key 已保存')
  }

  return (
    <Modal
      title={
        <Space>
          <RobotOutlined />
          <span>AI 智能助手</span>
          <Tag color="blue">GPT-4o</Tag>
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      style={{ top: 20 }}
    >
      <div style={{ display: 'flex', height: 500 }}>
        {/* 对话列表 */}
        <div style={{ width: 200, borderRight: '1px solid #f0f0f0', padding: 8, overflow: 'auto' }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleNewConversation} style={{ width: '100%', marginBottom: 8 }}>
            新对话
          </Button>
          <List
            dataSource={conversations}
            renderItem={(conv) => (
              <List.Item
                style={{ padding: '4px 8px', cursor: 'pointer', borderRadius: 4, background: currentConversation?.id === conv.id ? '#f0f0f0' : 'transparent' }}
                onClick={() => handleSelectConversation(conv)}
              >
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <Text ellipsis style={{ fontSize: 13 }}>{conv.title}</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 11 }}>{new Date(conv.updatedAt).toLocaleDateString()}</Text>
                </div>
                <Popconfirm title="删除此对话？" onConfirm={(e) => { e?.stopPropagation(); handleDeleteConversation(conv.id) }}>
                  <Button type="text" size="small" icon={<DeleteOutlined />} danger onClick={(e) => e.stopPropagation()} />
                </Popconfirm>
              </List.Item>
            )}
          />
        </div>

        {/* 对话内容 */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {/* 消息列表 */}
          <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
            {!currentConversation || currentConversation.messages.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <RobotOutlined style={{ fontSize: 48, color: '#1890ff', marginBottom: 16 }} />
                <Paragraph>你好！我是 LiangHua AI 助手，有什么可以帮你的？</Paragraph>
                <Space wrap>
                  {PRESET_PROMPTS.map((p, i) => (
                    <Tag
                      key={i}
                      style={{ cursor: 'pointer', margin: 4 }}
                      onClick={() => handlePresetPrompt(p.prompt)}
                    >
                      {p.label}
                    </Tag>
                  ))}
                </Space>
              </div>
            ) : (
              <>
                {currentConversation.messages.map((msg) => (
                  <div
                    key={msg.timestamp}
                    style={{
                      display: 'flex',
                      marginBottom: 16,
                      flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
                    }}
                  >
                    <Avatar
                      icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                      style={{ background: msg.role === 'user' ? '#1890ff' : '#52c41a' }}
                    />
                    <div
                      style={{
                        maxWidth: '70%',
                        marginLeft: msg.role === 'user' ? 0 : 12,
                        marginRight: msg.role === 'user' ? 12 : 0,
                        padding: 12,
                        borderRadius: 8,
                        background: msg.role === 'user' ? '#1890ff' : '#f5f5f5',
                        color: msg.role === 'user' ? '#fff' : 'inherit',
                      }}
                    >
                      <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{msg.content}</Paragraph>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </Text>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div style={{ textAlign: 'center', padding: 16 }}>
                    <Spin tip="思考中..." />
                  </div>
                )}
                <div ref={messagesEndRef} />
              </>
            )}
          </div>

          {/* 输入区域 */}
          <div style={{ padding: 16, borderTop: '1px solid #f0f0f0' }}>
            <Space.Compact style={{ width: '100%' }}>
              <TextArea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="输入问题或使用 /命令（如 /查询 110001）"
                autoSize={{ minRows: 1, maxRows: 4 }}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                style={{ borderRadius: '8px 0 0 8px' }}
              />
              <Dropdown
                menu={{
                  items: PRESET_PROMPTS.map((p, i) => ({
                    key: i,
                    label: p.label,
                    icon: <BulbOutlined />,
                    onClick: () => handlePresetPrompt(p.prompt),
                  })),
                }}
              >
                <Button icon={<ThunderboltOutlined />} />
              </Dropdown>
              <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>
                发送
              </Button>
              <Tooltip title="设置 API Key">
                <Button icon={<SettingOutlined />} onClick={() => setSettingsVisible(true)} />
              </Tooltip>
            </Space.Compact>
          </div>
        </div>
      </div>

      {/* 设置弹窗 */}
      <Modal
        title="API 设置"
        open={settingsVisible}
        onOk={handleSaveApiKey}
        onCancel={() => setSettingsVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Paragraph type="secondary">
          请输入您的 OpenAI API Key 或兼容的 API Key。密钥将安全存储在本地。
        </Paragraph>
        <Input.Password
          value={apiKey}
          onChange={(e) => setApiKeyState(e.target.value)}
          placeholder="sk-..."
        />
      </Modal>
    </Modal>
  )
}
