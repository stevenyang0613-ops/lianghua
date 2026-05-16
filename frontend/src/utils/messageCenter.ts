/**
 * 消息中心服务
 */

export interface Message {
  id: string
  type: 'system' | 'trade' | 'signal' | 'alert' | 'update' | 'notification'
  title: string
  content: string
  level: 'info' | 'success' | 'warning' | 'error'
  read: boolean
  starred: boolean
  createdAt: number
  actionUrl?: string
  actionText?: string
  metadata?: Record<string, unknown>
}

export interface MessageCategory {
  key: string
  label: string
  icon: string
  unreadCount: number
}

const MESSAGES_KEY = 'messages'
const MAX_MESSAGES = 500

// 生成唯一 ID
function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 获取所有消息
export function getMessages(options?: {
  type?: Message['type']
  read?: boolean
  starred?: boolean
  limit?: number
}): Message[] {
  const saved = localStorage.getItem(MESSAGES_KEY)
  let messages: Message[] = saved ? JSON.parse(saved) : []

  if (options) {
    if (options.type) {
      messages = messages.filter(m => m.type === options.type)
    }
    if (options.read !== undefined) {
      messages = messages.filter(m => m.read === options.read)
    }
    if (options.starred !== undefined) {
      messages = messages.filter(m => m.starred === options.starred)
    }
    if (options.limit) {
      messages = messages.slice(0, options.limit)
    }
  }

  return messages.sort((a, b) => b.createdAt - a.createdAt)
}

// 获取单个消息
export function getMessage(id: string): Message | null {
  const messages = getMessages()
  return messages.find(m => m.id === id) || null
}

// 添加消息
export function addMessage(message: Omit<Message, 'id' | 'read' | 'starred' | 'createdAt'>): Message {
  const messages = getMessages()

  const newMessage: Message = {
    ...message,
    id: generateId(),
    read: false,
    starred: false,
    createdAt: Date.now(),
  }

  messages.unshift(newMessage)

  // 限制数量
  if (messages.length > MAX_MESSAGES) {
    messages.splice(MAX_MESSAGES)
  }

  localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages))

  // 触发通知
  dispatchMessageEvent(newMessage)

  return newMessage
}

// 标记已读
export function markAsRead(id: string): Message | null {
  const messages = getMessages()
  const index = messages.findIndex(m => m.id === id)
  if (index === -1) return null

  messages[index].read = true
  localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages))
  return messages[index]
}

// 批量标记已读
export function markAllAsRead(type?: Message['type']): number {
  const messages = getMessages()
  let count = 0

  messages.forEach(m => {
    if (!m.read && (!type || m.type === type)) {
      m.read = true
      count++
    }
  })

  localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages))
  return count
}

// 标记星标
export function toggleStar(id: string): Message | null {
  const messages = getMessages()
  const index = messages.findIndex(m => m.id === id)
  if (index === -1) return null

  messages[index].starred = !messages[index].starred
  localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages))
  return messages[index]
}

// 删除消息
export function deleteMessage(id: string): boolean {
  const messages = getMessages()
  const filtered = messages.filter(m => m.id !== id)
  if (filtered.length === messages.length) return false

  localStorage.setItem(MESSAGES_KEY, JSON.stringify(filtered))
  return true
}

// 清空消息
export function clearMessages(type?: Message['type']): number {
  const messages = getMessages()
  const filtered = type ? messages.filter(m => m.type !== type) : []
  const removed = messages.length - filtered.length

  localStorage.setItem(MESSAGES_KEY, JSON.stringify(filtered))
  return removed
}

// 获取未读数量
export function getUnreadCount(type?: Message['type']): number {
  const messages = getMessages()
  return messages.filter(m => !m.read && (!type || m.type === type)).length
}

// 获取分类统计
export function getCategories(): MessageCategory[] {
  const messages = getMessages()

  const categories: MessageCategory[] = [
    { key: 'all', label: '全部', icon: 'AppstoreOutlined', unreadCount: messages.filter(m => !m.read).length },
    { key: 'system', label: '系统通知', icon: 'SettingOutlined', unreadCount: messages.filter(m => m.type === 'system' && !m.read).length },
    { key: 'trade', label: '交易提醒', icon: 'DollarOutlined', unreadCount: messages.filter(m => m.type === 'trade' && !m.read).length },
    { key: 'signal', label: '交易信号', icon: 'AlertOutlined', unreadCount: messages.filter(m => m.type === 'signal' && !m.read).length },
    { key: 'alert', label: '预警通知', icon: 'BellOutlined', unreadCount: messages.filter(m => m.type === 'alert' && !m.read).length },
    { key: 'update', label: '更新通知', icon: 'ReloadOutlined', unreadCount: messages.filter(m => m.type === 'update' && !m.read).length },
  ]

  return categories
}

// 事件分发
type MessageListener = (message: Message) => void
const listeners: Set<MessageListener> = new Set()

function dispatchMessageEvent(message: Message): void {
  listeners.forEach(listener => listener(message))
}

export function subscribe(listener: MessageListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// 快捷方法
export function notifySystem(title: string, content: string): Message {
  return addMessage({ type: 'system', title, content, level: 'info' })
}

export function notifyTrade(title: string, content: string): Message {
  return addMessage({ type: 'trade', title, content, level: 'success' })
}

export function notifySignal(title: string, content: string): Message {
  return addMessage({ type: 'signal', title, content, level: 'info' })
}

export function notifyAlert(title: string, content: string): Message {
  return addMessage({ type: 'alert', title, content, level: 'warning' })
}

export function notifyUpdate(title: string, content: string): Message {
  return addMessage({ type: 'update', title, content, level: 'info' })
}

export default {
  getMessages,
  getMessage,
  addMessage,
  markAsRead,
  markAllAsRead,
  toggleStar,
  deleteMessage,
  clearMessages,
  getUnreadCount,
  getCategories,
  subscribe,
  notifySystem,
  notifyTrade,
  notifySignal,
  notifyAlert,
  notifyUpdate,
}
