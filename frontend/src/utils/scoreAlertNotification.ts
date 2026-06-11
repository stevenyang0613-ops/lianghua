import { notificationService } from './notifications'

export interface AlertNotification {
  code: string
  name: string
  alert_type: 'score' | 'price' | 'dual_low' | 'premium'
  direction: 'above' | 'below'
  threshold: number
  current_value: number
  triggered_at: string
}

class ScoreAlertNotificationService {
  private lastTriggeredCodes: Set<string> = new Set()
  private enabled: boolean = true
  private soundEnabled: boolean = true

  constructor() {
    this.loadSettings()
  }

  private loadSettings() {
    try {
      const saved = localStorage.getItem('score_alert_notification_settings')
      if (saved) {
        const settings = JSON.parse(saved)
        this.enabled = settings.enabled ?? true
        this.soundEnabled = settings.soundEnabled ?? true
      }
    } catch { /* ignore */ }
  }

  private saveSettings() {
    try {
      localStorage.setItem('score_alert_notification_settings', JSON.stringify({
        enabled: this.enabled,
        soundEnabled: this.soundEnabled,
      }))
    } catch { /* ignore */ }
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled
    this.saveSettings()
  }

  setSoundEnabled(enabled: boolean) {
    this.soundEnabled = enabled
    this.saveSettings()
  }

  isEnabled(): boolean {
    return this.enabled
  }

  isSoundEnabled(): boolean {
    return this.soundEnabled
  }

  async notify(triggeredAlerts: AlertNotification[]): Promise<void> {
    if (!this.enabled || triggeredAlerts.length === 0) return

    // 过滤掉已经通知过的
    const newAlerts = triggeredAlerts.filter(a => !this.lastTriggeredCodes.has(a.code))
    if (newAlerts.length === 0) return

    // 更新已触发列表
    triggeredAlerts.forEach(a => this.lastTriggeredCodes.add(a.code))

    // 清理过期的已触发记录（保留最近100个）
    if (this.lastTriggeredCodes.size > 100) {
      const arr = Array.from(this.lastTriggeredCodes)
      this.lastTriggeredCodes = new Set(arr.slice(-100))
    }

    // 发送通知
    const titles = {
      score: '评分预警',
      price: '价格预警',
      dual_low: '双低预警',
      premium: '溢价预警',
    }

    const directions = {
      above: '高于',
      below: '低于',
    }

    if (newAlerts.length === 1) {
      const alert = newAlerts[0]
      notificationService.show({
        title: `${titles[alert.alert_type]}: ${alert.code}`,
        body: `${alert.name} ${alert.alert_type} ${Number.isFinite(alert.current_value) ? alert.current_value.toFixed(2) : '-'} ${directions[alert.direction]} 阈值 ${alert.threshold}`,
        tag: `score-alert-${alert.code}`,
      })
    } else {
      notificationService.show({
        title: `评分预警: ${newAlerts.length}个预警触发`,
        body: newAlerts.slice(0, 3).map(a => `${a.code}: ${a.alert_type}=${Number.isFinite(a.current_value) ? a.current_value.toFixed(2) : '-'}`).join('\n') +
          (newAlerts.length > 3 ? `\n... 还有 ${newAlerts.length - 3} 个` : ''),
        tag: 'score-alerts-batch',
      })
    }

    // 播放提示音
    if (this.soundEnabled) {
      this.playAlertSound()
    }

    // 同时在控制台输出
    console.log('[ScoreAlert] Triggered alerts:', newAlerts)
  }

  private playAlertSound() {
    try {
      // 使用Web Audio API播放简单提示音
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)()
      const oscillator = audioContext.createOscillator()
      const gainNode = audioContext.createGain()

      oscillator.connect(gainNode)
      gainNode.connect(audioContext.destination)

      oscillator.frequency.value = 800
      oscillator.type = 'sine'

      gainNode.gain.setValueAtTime(0.3, audioContext.currentTime)
      gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3)

      oscillator.start(audioContext.currentTime)
      oscillator.stop(audioContext.currentTime + 0.3)
    } catch (e) {
      console.warn('[ScoreAlert] Failed to play sound:', e)
    }
  }

  clearTriggered() {
    this.lastTriggeredCodes.clear()
  }

  getTriggeredCount(): number {
    return this.lastTriggeredCodes.size
  }
}

export const scoreAlertNotificationService = new ScoreAlertNotificationService()
