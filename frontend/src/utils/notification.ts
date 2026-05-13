const NOTIFICATION_PERMISSION_KEY = 'lianghua-notification-permission'

export type NotificationPermissionState = 'granted' | 'denied' | 'default'

export function requestNotificationPermission(): Promise<NotificationPermissionState> {
  if (!('Notification' in window)) {
    console.warn('[Notification] Browser does not support notifications')
    return Promise.resolve('denied')
  }

  return Notification.requestPermission().then((permission) => {
    localStorage.setItem(NOTIFICATION_PERMISSION_KEY, permission)
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

export interface NotificationOptions {
  title: string
  body: string
  icon?: string
  tag?: string
  data?: unknown
}

export function sendNotification(options: NotificationOptions): Notification | null {
  // Use Electron IPC if available
  try {
    if (window.electronAPI?.showNotification) {
      window.electronAPI.showNotification(options.title, options.body)
      return null
    }
  } catch {
    // Fall through to browser notification
  }

  if (!canSendNotification()) {
    console.warn('[Notification] Permission not granted')
    return null
  }

  const notification = new Notification(options.title, {
    body: options.body,
    icon: options.icon || '/favicon.ico',
    tag: options.tag,
    data: options.data,
    requireInteraction: false,
  })

  notification.onclick = () => {
    window.focus()
    notification.close()
  }

  return notification
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

  sendNotification({
    title: `告警: ${name} (${code})`,
    body: `${label}阈值 ${threshold}，当前值: ${value.toFixed(2)}`,
    tag: `alert-${code}-${alertType}`,
    data: { code, alertType },
  })
}
