/**
 * 桌面通知服务
 * 支持系统通知和 Electron 原生通知
 */

export type NotificationPermissionState = 'granted' | 'denied' | 'default'

export function requestNotificationPermission(): Promise<NotificationPermissionState> {
  if (!('Notification' in window)) {
    console.warn('[Notification] Browser does not support notifications')
    return Promise.resolve('denied')
  }

  return Notification.requestPermission().then((permission) => {
    notificationService.permissionGranted = permission === 'granted'
    if (permission === 'granted') {
      notificationService.flushQueue()
    }
    return permission
  })
}

export function getNotificationPermission(): NotificationPermissionState {
  if (!('Notification' in window)) return 'denied'
  return Notification.permission as NotificationPermissionState
}

export function canSendNotification(): boolean {
  return getNotificationPermission() === 'granted'
}

export function sendAlertNotification(code: string, name: string, alertType: string, value: number, threshold: number): void {
  const typeLabels: Record<string, string> = {
    price_above: '价格高于',
    price_below: '价格低于',
    premium_above: '溢价率高于',
    premium_below: '溢价率低于',
    dual_low_below: '双低值低于',
    ytm_above: 'YTM高于',
  }

  const label = typeLabels[alertType] || alertType

  notificationService.show({
    title: `告警: ${name} (${code})`,
    body: `${label}阈值 ${threshold}，当前值: ${Number.isFinite(value) ? value.toFixed(2) : value}`,
    tag: `alert-${code}-${alertType}`,
    data: { code, alertType },
  })
}

export interface NotificationOptions {
  title: string
  body: string
  icon?: string
  tag?: string
  requireInteraction?: boolean
  onClick?: () => void
  onClose?: () => void
  data?: unknown
}

interface NotificationPermission {
  granted: boolean
  denied: boolean
  default: boolean
}

class NotificationService {
  enabled = true
  permissionGranted = false
  private notificationQueue: NotificationOptions[] = []
  private audioEnabled = true
  private audioSrc = '/notification.mp3'

  async init(): Promise<void> {
    if (!('Notification' in window)) {
      console.warn('This browser does not support notifications')
      return
    }

    if (Notification.permission === 'granted') {
      this.permissionGranted = true
      this.flushQueue()
    } else if (Notification.permission !== 'denied') {
      await requestNotificationPermission()
    }

    this.loadSettings()
  }

  flushQueue(): void {
    while (this.notificationQueue.length > 0) {
      const options = this.notificationQueue.shift()
      if (options) this.show(options)
    }
  }

  private loadSettings(): void {
    const saved = localStorage.getItem('notification_settings')
    if (saved) {
      try {
        const settings = JSON.parse(saved)
        this.enabled = settings.enabled ?? true
        this.audioEnabled = settings.audioEnabled ?? true
      } catch {
        console.warn('[Notifications] Corrupted settings, using defaults')
      }
    }
  }

  saveSettings(settings: { enabled?: boolean; audioEnabled?: boolean }): void {
    this.enabled = settings.enabled ?? this.enabled
    this.audioEnabled = settings.audioEnabled ?? this.audioEnabled
    localStorage.setItem('notification_settings', JSON.stringify({
      enabled: this.enabled,
      audioEnabled: this.audioEnabled,
    }))
  }

  show(options: NotificationOptions): Notification | null {
    if (!this.enabled) return null

    // Use Electron IPC if available
    try {
      if (window.electronAPI?.showNotification) {
        window.electronAPI.showNotification(options.title, options.body)
        return null
      }
    } catch {
      // Fall through to browser notification
    }

    if (!this.permissionGranted) {
      if (Notification.permission === 'default') {
        this.notificationQueue.push(options)
        requestNotificationPermission()
      }
      return null
    }

    try {
      const notification = new Notification(options.title, {
        body: options.body,
        icon: options.icon || '/icon-192.png',
        tag: options.tag,
        requireInteraction: options.requireInteraction,
      })

      if (options.onClick) {
        notification.onclick = () => {
          options.onClick?.()
          notification.close()
          window.focus()
        }
      }

      if (options.onClose) {
        notification.onclose = options.onClose
      }

      notification.onclick = notification.onclick || (() => {
        window.focus()
        notification.close()
      })

      this.playSound()

      return notification
    } catch (error) {
      console.error('Failed to show notification:', error)
      return null
    }
  }

  private playSound(): void {
    if (!this.audioEnabled) return

    try {
      const audio = new Audio(this.audioSrc)
      audio.volume = 0.5
      audio.play().catch(() => {})
    } catch {
      // Ignore audio errors
    }
  }

  // 交易信号通知
  signal(signal: { code: string; name: string; type: string; confidence: number }): void {
    const typeMap: Record<string, string> = {
      buy: '买入',
      sell: '卖出',
      hold: '持有',
    }

    this.show({
      title: `交易信号: ${signal.name} (${signal.code})`,
      body: `建议${typeMap[signal.type] || signal.type}，置信度 ${Math.round(signal.confidence * 100)}%`,
      tag: `signal-${signal.code}`,
      requireInteraction: true,
    })
  }

  // 价格预警通知
  priceAlert(data: { code: string; name: string; price: number; change: number; target: number }): void {
    const direction = data.change > 0 ? '上涨' : '下跌'

    this.show({
      title: `价格预警: ${data.name} (${data.code})`,
      body: `${direction}至 ${data.price}，目标价 ${data.target}`,
      tag: `price-${data.code}`,
    })
  }

  // 系统通知
  system(title: string, body: string): void {
    this.show({
      title,
      body,
      tag: 'system',
    })
  }

  // 成功通知
  success(title: string, body: string): void {
    this.show({
      title: `✓ ${title}`,
      body,
      tag: 'success',
    })
  }

  // 警告通知
  warning(title: string, body: string): void {
    this.show({
      title: `⚠ ${title}`,
      body,
      tag: 'warning',
      requireInteraction: true,
    })
  }

  // 错误通知
  error(title: string, body: string): void {
    this.show({
      title: `✗ ${title}`,
      body,
      tag: 'error',
      requireInteraction: true,
    })
  }

  getPermissionStatus(): NotificationPermission {
    if (!('Notification' in window)) {
      return { granted: false, denied: true, default: false }
    }

    return {
      granted: Notification.permission === 'granted',
      denied: Notification.permission === 'denied',
      default: Notification.permission === 'default',
    }
  }

  isEnabled(): boolean {
    return this.enabled && this.permissionGranted
  }

  setEnabled(enabled: boolean): void {
    this.saveSettings({ enabled })
  }

  setAudioEnabled(enabled: boolean): void {
    this.saveSettings({ audioEnabled: enabled })
  }
}

export const notificationService = new NotificationService()

export default notificationService
