/**
 * 桌面通知服务
 * 集成 Electron 和浏览器通知 API
 */

export interface NotificationOptions {
  title: string
  body: string
  icon?: string
  silent?: boolean
  urgency?: 'normal' | 'low' | 'critical'
  category?: string
  actions?: NotificationAction[]
  data?: Record<string, unknown>
}

export interface NotificationAction {
  type: 'button'
  title: string
  icon?: string
}

// NotificationListener type reserved for future extensibility

const NOTIFICATION_SETTINGS_KEY = 'notification_settings'
const NOTIFICATION_HISTORY_KEY = 'notification_history'
const MAX_HISTORY = 100

export interface NotificationSettings {
  enabled: boolean
  sound: boolean
  desktop: boolean
  trade: boolean
  signal: boolean
  alert: boolean
  system: boolean
  quietHours: {
    enabled: boolean
    start: string
    end: string
  }
}

const defaultSettings: NotificationSettings = {
  enabled: true,
  sound: true,
  desktop: true,
  trade: true,
  signal: true,
  alert: true,
  system: true,
  quietHours: {
    enabled: false,
    start: '22:00',
    end: '08:00',
  },
}

// 获取通知设置
export function getNotificationSettings(): NotificationSettings {
  try {
    const saved = localStorage.getItem(NOTIFICATION_SETTINGS_KEY)
    if (saved) {
      try { return { ...defaultSettings, ...JSON.parse(saved) } } catch { /* fall through */ }
    }
  } catch { /* localStorage unavailable */ }
  return defaultSettings
}

// 更新通知设置
export function updateNotificationSettings(settings: Partial<NotificationSettings>): void {
  const current = getNotificationSettings()
  localStorage.setItem(NOTIFICATION_SETTINGS_KEY, JSON.stringify({ ...current, ...settings }))
}

// 检查是否在静默时段
function isInQuietHours(): boolean {
  const settings = getNotificationSettings()
  if (!settings.quietHours.enabled) return false

  const now = new Date()
  const currentTime = now.getHours() * 60 + now.getMinutes()

  const [startH, startM] = settings.quietHours.start.split(':').map(Number)
  const [endH, endM] = settings.quietHours.end.split(':').map(Number)

  const startTime = startH * 60 + startM
  const endTime = endH * 60 + endM

  if (startTime < endTime) {
    return currentTime >= startTime && currentTime < endTime
  } else {
    return currentTime >= startTime || currentTime < endTime
  }
}

// 检查权限
export async function requestNotificationPermission(): Promise<boolean> {
  if (!('Notification' in window)) {
    console.warn('浏览器不支持通知')
    return false
  }

  if (Notification.permission === 'granted') {
    return true
  }

  if (Notification.permission === 'denied') {
    console.warn('通知权限被拒绝')
    return false
  }

  const permission = await Notification.requestPermission()
  return permission === 'granted'
}

// 检查是否允许发送通知
function shouldNotify(category: 'trade' | 'signal' | 'alert' | 'system'): boolean {
  const settings = getNotificationSettings()

  if (!settings.enabled || !settings.desktop) return false
  if (isInQuietHours()) return false

  switch (category) {
    case 'trade': return settings.trade
    case 'signal': return settings.signal
    case 'alert': return settings.alert
    case 'system': return settings.system
    default: return true
  }
}

// 发送桌面通知
export async function sendDesktopNotification(
  options: NotificationOptions,
  category: 'trade' | 'signal' | 'alert' | 'system' = 'system'
): Promise<Notification | null> {
  if (!shouldNotify(category)) return null

  const hasPermission = await requestNotificationPermission()
  if (!hasPermission) return null

  const notification = new Notification(options.title, {
    body: options.body,
    icon: options.icon || '/icon.png',
    silent: options.silent ?? !getNotificationSettings().sound,
    data: options.data,
  })

  // 播放提示音
  if (!options.silent && getNotificationSettings().sound) {
    playNotificationSound(category)
  }

  // 记录历史
  addToHistory(options)

  return notification
}

// 播放提示音
function playNotificationSound(category: 'trade' | 'signal' | 'alert' | 'system'): void {
  const sounds: Record<string, string> = {
    trade: '/sounds/trade.mp3',
    signal: '/sounds/signal.mp3',
    alert: '/sounds/alert.mp3',
    system: '/sounds/notification.mp3',
  }

  try {
    const audio = new Audio(sounds[category] || sounds.system)
    audio.volume = 0.5
    void audio.play()
  } catch (e) {
    console.warn('播放提示音失败:', e)
  }
}

// 添加到历史记录
function addToHistory(options: NotificationOptions): void {
  const saved = localStorage.getItem(NOTIFICATION_HISTORY_KEY)
  let history: any[] = []
  if (saved) {
    try { history = JSON.parse(saved) } catch { history = [] }
  }

  history.unshift({
    ...options,
    timestamp: Date.now(),
  })

  // 限制历史记录数量
  if (history.length > MAX_HISTORY) {
    history.splice(MAX_HISTORY)
  }

  localStorage.setItem(NOTIFICATION_HISTORY_KEY, JSON.stringify(history))
}

// 获取通知历史
export function getNotificationHistory(): Array<NotificationOptions & { timestamp: number }> {
  const saved = localStorage.getItem(NOTIFICATION_HISTORY_KEY)
  if (saved) {
    try { return JSON.parse(saved) } catch { /* ignore corrupt data */ }
  }
  return []
}

// 清空通知历史
export function clearNotificationHistory(): void {
  localStorage.removeItem(NOTIFICATION_HISTORY_KEY)
}

// 快捷方法
export function notifyTrade(title: string, body: string, data?: Record<string, unknown>): Promise<Notification | null> {
  return sendDesktopNotification({ title, body, data }, 'trade')
}

export function notifySignal(title: string, body: string, data?: Record<string, unknown>): Promise<Notification | null> {
  return sendDesktopNotification({ title, body, data }, 'signal')
}

export function notifyAlert(title: string, body: string, data?: Record<string, unknown>): Promise<Notification | null> {
  return sendDesktopNotification({ title, body, urgency: 'critical', data }, 'alert')
}

export function notifySystem(title: string, body: string, data?: Record<string, unknown>): Promise<Notification | null> {
  return sendDesktopNotification({ title, body, data }, 'system')
}

// Electron IPC 通知（如果运行在 Electron 中）
export async function sendElectronNotification(options: NotificationOptions): Promise<void> {
  if (window.electronAPI?.showNotification) {
    await window.electronAPI.showNotification(options.title ?? '', options.body ?? '')
  } else {
    await sendDesktopNotification(options)
  }
}

export default {
  getNotificationSettings,
  updateNotificationSettings,
  requestNotificationPermission,
  sendDesktopNotification,
  sendElectronNotification,
  getNotificationHistory,
  clearNotificationHistory,
  notifyTrade,
  notifySignal,
  notifyAlert,
  notifySystem,
}
