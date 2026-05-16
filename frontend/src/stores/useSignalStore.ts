import { create } from 'zustand'
import { fetchSignals, fetchAvailableSignalsStrategies, setActiveStrategies, executeSignal, batchExecuteSignals, fetchSignalHistory, fetchSignalStats, type TradeSignal, type StrategyInfoItem, type SignalHistoryItem, type SignalStats } from '../services/api'
import { signalsWs } from '../utils/wsInstances'
import { notification } from 'antd'

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
  disconnectWs: () => void
}

let wsSubCleanups: (() => void)[] = []
let reconnectNotifyCount = 0

export const useSignalStore = create<SignalState>((set, get) => ({
  signals: [],
  activeStrategies: ['dual_low'],
  availableStrategies: [],
  history: [],
  stats: null,
  total: 0,
  loading: false,
  error: null,
  wsConnected: signalsWs.isConnected(),

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
    // Clean up any existing subscriptions
    get().disconnectWs()

    const unsubMsg = signalsWs.subscribe('signals', (data) => {
      const signals = (data as TradeSignal[]).filter((s: TradeSignal) => !s.executed)
      set({ signals, total: (data as TradeSignal[]).length })
    })

    const unsubState = signalsWs.onStateChange((state) => {
      set({ wsConnected: state === 'connected' })
      if (state === 'connected') {
        if (reconnectNotifyCount >= 3) {
          notification.success({ message: 'WebSocket 已重连', description: `经过 ${reconnectNotifyCount} 次重试后恢复连接`, duration: 5 })
        }
        reconnectNotifyCount = 0
        get().loadSignals()
      } else if (state === 'reconnecting') {
        reconnectNotifyCount = signalsWs.getAttemptCount()
        if (reconnectNotifyCount >= 3 && reconnectNotifyCount % 3 === 0) {
          notification.warning({ message: 'WebSocket 连接异常', description: `已重试 ${reconnectNotifyCount} 次，请检查后端服务是否正常运行`, duration: 8 })
        }
      }
    })

    const unsubLatency = signalsWs.onLatencyWarning((latency, consecutiveHigh) => {
      if (consecutiveHigh >= 3 && consecutiveHigh % 3 === 0) {
        notification.warning({ message: 'WS 延迟过高', description: `连续 ${consecutiveHigh} 次延迟 >500ms，当前 ${latency}ms，请检查网络状况`, duration: 8 })
      }
    })

    wsSubCleanups = [unsubMsg, unsubState, unsubLatency]

    if (!signalsWs.isConnected() && signalsWs.getState() === 'disconnected') {
      signalsWs.connect()
    }

    return () => get().disconnectWs()
  },

  disconnectWs: () => {
    wsSubCleanups.forEach(fn => fn())
    wsSubCleanups = []
    signalsWs.disconnect()
    set({ wsConnected: false })
  },
}))
