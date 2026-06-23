/**
 * AI 智能助手服务
 * 集成大语言模型进行自然语言交互
 */

import { secureSave, secureLoad, secureRemove } from './secureStorage'
import { safeJsonParse } from './safeJson'

export interface AIMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
}

export interface AIConversation {
  id: string
  title: string
  messages: AIMessage[]
  createdAt: number
  updatedAt: number
}

export interface AIContext {
  currentCode?: string
  currentPrice?: number
  portfolio?: Record<string, unknown>
  marketData?: Record<string, unknown>
}

const CONVERSATIONS_KEY = 'ai_conversations'
const API_KEY_KEY = 'ai_api_key'
const API_ENDPOINT_KEY = 'ai_api_endpoint'

// Debounced localStorage write for conversations
let _pendingConversations: AIConversation[] | null = null
let _aiFlushTimer: ReturnType<typeof setTimeout> | null = null
const AI_FLUSH_DELAY = 500

function _flushConversations(): void {
  if (_aiFlushTimer) {
    clearTimeout(_aiFlushTimer)
    _aiFlushTimer = null
  }
  if (_pendingConversations === null) return
  try {
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(_pendingConversations))
  } catch (e) {
    console.warn('[AIService] localStorage write failed:', e)
  }
  _pendingConversations = null
}

function _scheduleConversationsSave(conversations: AIConversation[]): void {
  _pendingConversations = conversations
  if (_aiFlushTimer) return
  _aiFlushTimer = setTimeout(_flushConversations, AI_FLUSH_DELAY)
}

// 默认 API 配置
const DEFAULT_ENDPOINT = 'https://api.openai.com/v1/chat/completions'

// 获取 API Key（异步，从加密存储读取）
export async function getAPIKey(): Promise<string | null> {
  const value = await secureLoad(API_KEY_KEY)
  return value || null
}

// 设置 API Key（异步，加密存储）
export async function setAPIKey(key: string): Promise<void> {
  if (!key) {
    await secureRemove(API_KEY_KEY)
    return
  }
  await secureSave(API_KEY_KEY, key)
}

// 获取 API 端点
export function getAPIEndpoint(): string {
  return localStorage.getItem(API_ENDPOINT_KEY) || DEFAULT_ENDPOINT
}

// 设置 API 端点
export function setAPIEndpoint(endpoint: string): void {
  localStorage.setItem(API_ENDPOINT_KEY, endpoint)
}

// 生成唯一 ID
function generateId(): string {
  return `conv_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 获取所有对话
export function getConversations(): AIConversation[] {
  const saved = localStorage.getItem(CONVERSATIONS_KEY)
  return safeJsonParse<AIConversation[]>(saved, [])
}

// 获取单个对话
export function getConversation(id: string): AIConversation | null {
  const conversations = getConversations()
  return conversations.find(c => c.id === id) || null
}

// 创建新对话
export function createConversation(title: string = '新对话'): AIConversation {
  const conversations = getConversations()
  const conversation: AIConversation = {
    id: generateId(),
    title,
    messages: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  conversations.unshift(conversation)
  _scheduleConversationsSave(conversations)
  return conversation
}

// 更新对话
export function updateConversation(id: string, updates: Partial<AIConversation>): AIConversation | null {
  const conversations = getConversations()
  const index = conversations.findIndex(c => c.id === id)
  if (index === -1) return null

  conversations[index] = {
    ...conversations[index],
    ...updates,
    updatedAt: Date.now(),
  }
  _scheduleConversationsSave(conversations)
  return conversations[index]
}

// 删除对话
export function deleteConversation(id: string): boolean {
  const conversations = getConversations()
  const filtered = conversations.filter(c => c.id !== id)
  if (filtered.length === conversations.length) return false
  _scheduleConversationsSave(filtered)
  return true
}

// 清空所有对话
export function clearConversations(): void {
  if (_aiFlushTimer) {
    clearTimeout(_aiFlushTimer)
    _aiFlushTimer = null
  }
  _pendingConversations = null
  localStorage.removeItem(CONVERSATIONS_KEY)
}

// 添加消息到对话
export function addMessage(conversationId: string, message: Omit<AIMessage, 'timestamp'>): AIMessage | null {
  const conversation = getConversation(conversationId)
  if (!conversation) return null

  const fullMessage: AIMessage = {
    ...message,
    timestamp: Date.now(),
  }

  conversation.messages.push(fullMessage)
  updateConversation(conversationId, { messages: conversation.messages })

  return fullMessage
}

// 构建系统提示
function buildSystemPrompt(context?: AIContext): string {
  let prompt = `你是 LiangHua 可转债量化交易系统的智能助手。你可以帮助用户：
1. 分析可转债市场数据和投资机会
2. 解读技术指标和交易信号
3. 提供投资建议和风险提示
4. 回答量化交易相关问题
5. 协助设置策略参数和预警规则

请用专业但易懂的中文回答用户问题。`

  if (context) {
    prompt += '\n\n当前上下文信息：'
    if (context.currentCode) {
      prompt += `\n- 当前关注标的: ${context.currentCode}`
    }
    if (context.currentPrice) {
      prompt += `\n- 当前价格: ${context.currentPrice}`
    }
    if (context.portfolio) {
      prompt += `\n- 持仓信息: ${JSON.stringify(context.portfolio)}`
    }
    if (context.marketData) {
      prompt += `\n- 市场数据: ${JSON.stringify(context.marketData)}`
    }
  }

  return prompt
}

// 调用 AI API
export async function callAI(
  messages: AIMessage[],
  context?: AIContext
): Promise<string> {
  const apiKey = await getAPIKey()
  if (!apiKey) {
    throw new Error('请先配置 API Key')
  }

  const endpoint = getAPIEndpoint()

  const systemPrompt = buildSystemPrompt(context)

  const apiMessages = [
    { role: 'system', content: systemPrompt },
    ...messages.map(m => ({ role: m.role, content: m.content })),
  ]

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: 'gpt-4o-mini',
      messages: apiMessages,
      temperature: 0.7,
      max_tokens: 2000,
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`API 调用失败: ${error}`)
  }

  const data = await response.json()
  return data.choices[0]?.message?.content || '抱歉，我无法生成回复。'
}

// 预设提示词
export const PRESET_PROMPTS = [
  { label: '分析当前标的', prompt: '请分析当前关注标的的投资价值' },
  { label: '技术指标解读', prompt: '请解读当前标的的技术指标和交易信号' },
  { label: '风险提示', prompt: '请分析当前持仓的风险点' },
  { label: '策略建议', prompt: '请给出适合当前市场环境的交易策略建议' },
  { label: '市场概况', prompt: '请概括当前可转债市场的整体情况' },
  { label: '止损建议', prompt: '请给出当前持仓的止损建议' },
]

// 快捷命令
export function parseQuickCommand(input: string): { type: string; params: Record<string, string> } | null {
  const trimmed = input.trim()

  // 查询命令: /查询 110001
  if (trimmed.startsWith('/查询 ') || trimmed.startsWith('/query ')) {
    const code = trimmed.split(/\s+/)[1]
    return { type: 'query', params: { code } }
  }

  // 分析命令: /分析
  if (trimmed === '/分析' || trimmed === '/analyze') {
    return { type: 'analyze', params: {} }
  }

  // 预警命令: /预警 价格 120
  if (trimmed.startsWith('/预警 ')) {
    const parts = trimmed.split(/\s+/)
    return { type: 'alert', params: { type: parts[1], value: parts[2] } }
  }

  // 下单命令: /买入 110001 100
  if (trimmed.startsWith('/买入 ') || trimmed.startsWith('/buy ')) {
    const parts = trimmed.split(/\s+/)
    return { type: 'buy', params: { code: parts[1], quantity: parts[2] } }
  }

  if (trimmed.startsWith('/卖出 ') || trimmed.startsWith('/sell ')) {
    const parts = trimmed.split(/\s+/)
    return { type: 'sell', params: { code: parts[1], quantity: parts[2] } }
  }

  return null
}

export default {
  getAPIKey,
  setAPIKey,
  getAPIEndpoint,
  setAPIEndpoint,
  getConversations,
  getConversation,
  createConversation,
  updateConversation,
  deleteConversation,
  clearConversations,
  addMessage,
  callAI,
  PRESET_PROMPTS,
  parseQuickCommand,
}
