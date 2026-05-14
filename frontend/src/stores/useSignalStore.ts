import { create } from 'zustand'
import { fetchSignals, fetchAvailableSignalsStrategies, setActiveStrategies, executeSignal, batchExecuteSignals, fetchSignalHistory, fetchSignalStats, type TradeSignal, type StrategyInfoItem, type SignalHistoryItem, type SignalStats } from '../services/api'

const WS_URL = `ws://${window.location.hostname}:8000/api/v1/ws/signals`

interface SignalState {
  signals: TradeSignal[]
  activeStrategies: string[]
  availableStrategies: StrategyInfoItem[]
  history: SignalHistoryItem[]
  stats: SignalStats | null
  total: number
  loading: boolean
  error: string | null
  wsConnected: boolean
  loadSignals: () => Promise<void>
  loadAvailableStrategies: () => Promise<void>
  loadHistory: (strategy?: string, code?: string) => Promise<void>
  loadStats: () => Promise<void>
  setStrategies: (strategies: string[]) => Promise<void>
  execute: (code: string) => Promise<void>
  batchExecute: () => Promise<number>
  connectWs: () => () => void
}

export const useSignalStore = create<SignalState>((set, get) => ({
  signals: [],
  activeStrategies: ['dual_low'],
  availableStrategies: [],
  history: [],
  stats: null,
  total: 0,
  loading: false,
  error: null,
  wsConnected: false,

  loadSignals: async () => {
    set({ loading: true, error: null })
    try {
      const data = await fetchSignals()
      set({ signals: data.signals, activeStrategies: data.active_strategies, total: data.total, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  loadAvailableStrategies: async () => {
    try {
      const data = await fetchAvailableSignalsStrategies()
      set({ availableStrategies: data.strategies })
    } catch { /* ignore */ }
  },

  loadHistory: async (strategy?, code?) => {
    try {
      const data = await fetchSignalHistory(strategy, code, 200)
      set({ history: data.signals })
    } catch { /* ignore */ }
  },

  loadStats: async () => {
    try {
      const data = await fetchSignalStats()
      set({ stats: data })
    } catch { /* ignore */ }
  },

  setStrategies: async (strategies) => {
    set({ loading: true, error: null })
    try {
      const data = await setActiveStrategies(strategies)
      set({ activeStrategies: data.active_strategies, loading: false })
      const sigData = await fetchSignals()
      set({ signals: sigData.signals, total: sigData.total })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  execute: async (code) => {
    set({ loading: true, error: null })
    try {
      await executeSignal(code)
      const data = await fetchSignals()
      set({ signals: data.signals, total: data.total, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  batchExecute: async () => {
    set({ loading: true, error: null })
    try {
      const result = await batchExecuteSignals()
      const data = await fetchSignals()
      set({ signals: data.signals, total: data.total, loading: false })
      return result.executed
    } catch (e) {
      set({ error: String(e), loading: false })
      return 0
    }
  },

  connectWs: () => {
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      ws = new WebSocket(WS_URL)
      ws.onopen = () => set({ wsConnected: true })
      ws.onclose = () => {
        set({ wsConnected: false })
        reconnectTimer = setTimeout(connect, 5000)
      }
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'signals' && msg.signals) {
            set({ signals: msg.signals.filter((s: TradeSignal) => !s.executed), total: msg.signals.length })
          }
        } catch { /* ignore */ }
      }
    }

    connect()
    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (ws) ws.close()
    }
  },
}))
