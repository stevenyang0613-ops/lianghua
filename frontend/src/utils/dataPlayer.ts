/**
 * 数据播放器
 * 历史数据模拟交易
 */

export interface DataPlayerConfig {
  dataType: 'day' | 'minute' | 'tick'
  startDate: string
  endDate: string
  speed: number
  autoPlay: boolean
  showIndicators: boolean
  initialCash: number
  code: string   // 要回放的转债代码，'' 表示让用户选择
}

export interface PlayerState {
  isPlaying: boolean
  isPaused: boolean
  currentIndex: number
  totalFrames: number
  currentDate: string
  currentTime: string
  progress: number
}

export interface MarketFrame {
  index: number
  date: string
  time: string
  code: string
  name: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  bids: { price: number; volume: number }[]
  asks: { price: number; volume: number }[]
}

class DataPlayerEngine {
  private frames: MarketFrame[] = []
  private currentIndex = 0
  private playInterval: number | null = null
  private listeners: Set<(frame: MarketFrame, state: PlayerState) => void> = new Set()
  private stateListeners: Set<(state: PlayerState) => void> = new Set()
  private config: DataPlayerConfig = {
    dataType: 'day',
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    speed: 1,
    autoPlay: false,
    showIndicators: true,
    initialCash: 1000000,
    code: '',   // 空字符串表示让用户选择
  }

  loadFrames(frames: MarketFrame[]): void {
    this.frames = frames
    this.currentIndex = 0
    this.notifyStateListeners()
  }

  setConfig(config: Partial<DataPlayerConfig>): void {
    this.config = { ...this.config, ...config }
  }

  play(speed: number = 1): void {
    if (this.playInterval) return

    const baseDelay = 1000 / speed

    this.playInterval = window.setInterval(() => {
      if (this.currentIndex < this.frames.length - 1) {
        this.currentIndex++
        this.notifyListeners()
        this.notifyStateListeners()
      } else {
        this.stop()
      }
    }, baseDelay)

    this.notifyStateListeners()
  }

  pause(): void {
    if (this.playInterval) {
      clearInterval(this.playInterval)
      this.playInterval = null
    }
    this.notifyStateListeners()
  }

  stop(): void {
    if (this.playInterval) {
      clearInterval(this.playInterval)
      this.playInterval = null
    }
    this.currentIndex = 0
    this.notifyListeners()
    this.notifyStateListeners()
  }

  goToFrame(index: number): void {
    if (index >= 0 && index < this.frames.length) {
      this.currentIndex = index
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  nextFrame(): void {
    if (this.currentIndex < this.frames.length - 1) {
      this.currentIndex++
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  prevFrame(): void {
    if (this.currentIndex > 0) {
      this.currentIndex--
      this.notifyListeners()
      this.notifyStateListeners()
    }
  }

  fastForward(count: number = 10): void {
    this.currentIndex = Math.min(this.currentIndex + count, this.frames.length - 1)
    this.notifyListeners()
    this.notifyStateListeners()
  }

  rewind(count: number = 10): void {
    this.currentIndex = Math.max(this.currentIndex - count, 0)
    this.notifyListeners()
    this.notifyStateListeners()
  }

  getCurrentFrame(): MarketFrame | null {
    return this.frames[this.currentIndex] || null
  }

  getState(): PlayerState {
    const frame = this.getCurrentFrame()
    return {
      isPlaying: this.playInterval !== null,
      isPaused: this.playInterval === null && this.currentIndex > 0,
      currentIndex: this.currentIndex,
      totalFrames: this.frames.length,
      currentDate: frame?.date || '',
      currentTime: frame?.time || '',
      progress: this.frames.length > 0 ? (this.currentIndex / (this.frames.length - 1)) * 100 : 0,
    }
  }

  getAllFrames(): MarketFrame[] {
    return this.frames
  }

  onFrame(listener: (frame: MarketFrame, state: PlayerState) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onStateChange(listener: (state: PlayerState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  private notifyListeners(): void {
    const frame = this.getCurrentFrame()
    const state = this.getState()
    if (frame) {
      this.listeners.forEach(l => l(frame, state))
    }
  }

  private notifyStateListeners(): void {
    const state = this.getState()
    this.stateListeners.forEach(l => l(state))
  }

  destroy(): void {
    this.stop()
    this.listeners.clear()
    this.stateListeners.clear()
    this.frames = []
    this.currentIndex = 0
  }
}

export const dataPlayer = new DataPlayerEngine()

/**
 * 从后端 /api/v1/history/daily/{code} 拉取真实历史 K 线
 * 后端 storage.get_daily_history 返回 daily_snapshots 表的真实数据（来自 AKShare 抓取）
 *
 * 失败时返回空数组（不生成 mock 数据），由调用方决定是否回退到 mock
 */
export async function fetchRealFrames(code: string, days: number = 365): Promise<MarketFrame[]> {
  try {
    const base = (typeof window !== 'undefined' && (window as any).__LH_API_BASE__) || ''
    const url = `${base}/api/v1/history/daily/${encodeURIComponent(code)}?days=${days}`
    const resp = await fetch(url, { headers: { 'Accept': 'application/json' } })
    if (!resp.ok) return []
    const json: any = await resp.json()
    const records: any[] = Array.isArray(json?.history) ? json.history : []
    if (records.length === 0) return []
    return records
      .filter((r) => r && r.snapshot_date)
      .map((r, idx) => {
        const open = Number(r.open_price ?? r.price ?? 0)
        const close = Number(r.close_price ?? r.price ?? 0)
        const high = Number(r.high_price ?? close ?? 0)
        const low = Number(r.low_price ?? close ?? 0)
        const vol = Number(r.volume ?? 0)
        const amt = Number(r.amount ?? vol * close)
        return {
          index: idx,
          date: String(r.snapshot_date).slice(0, 10),
          time: '15:00',
          code: String(r.code ?? code),
          name: String(r.name ?? ''),
          open,
          high,
          low,
          close,
          volume: vol,
          amount: amt,
          bids: [
            { price: close - 0.01, volume: 0 },
            { price: close - 0.02, volume: 0 },
            { price: close - 0.03, volume: 0 },
          ],
          asks: [
            { price: close + 0.01, volume: 0 },
            { price: close + 0.02, volume: 0 },
            { price: close + 0.03, volume: 0 },
          ],
        } as MarketFrame
      })
  } catch {
    return []
  }
}

// 生成模拟数据（仅作为 API 失败时的兜底，不进入真实交易/回测路径）
export function generateMockFrames(config: DataPlayerConfig, code: string = '110001'): MarketFrame[] {
  const frames: MarketFrame[] = []
  const startDate = new Date(config.startDate)
  const endDate = new Date(config.endDate)
  const currentDate = new Date(startDate)

  let index = 0
  let basePrice = 100

  while (currentDate <= endDate) {
    // 跳过周末
    if (currentDate.getDay() !== 0 && currentDate.getDay() !== 6) {
      const change = (Math.random() - 0.5) * 4
      basePrice = Math.max(50, basePrice + change)

      const open = basePrice
      const high = open + Math.random() * 2
      const low = open - Math.random() * 2
      const close = low + Math.random() * (high - low)

      frames.push({
        index: index++,
        date: currentDate.toISOString().slice(0, 10),
        time: '15:00',
        code,
        name: '示例转债',
        open: +open.toFixed(2),
        high: +high.toFixed(2),
        low: +low.toFixed(2),
        close: +close.toFixed(2),
        volume: Math.floor(Math.random() * 100000),
        amount: Math.floor(Math.random() * 10000000),
        bids: [
          { price: close - 0.01, volume: Math.floor(Math.random() * 1000) },
          { price: close - 0.02, volume: Math.floor(Math.random() * 1000) },
          { price: close - 0.03, volume: Math.floor(Math.random() * 1000) },
        ],
        asks: [
          { price: close + 0.01, volume: Math.floor(Math.random() * 1000) },
          { price: close + 0.02, volume: Math.floor(Math.random() * 1000) },
          { price: close + 0.03, volume: Math.floor(Math.random() * 1000) },
        ],
      })
    }

    currentDate.setDate(currentDate.getDate() + 1)
  }

  return frames
}

export default dataPlayer
