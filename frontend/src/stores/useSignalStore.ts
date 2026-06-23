import { create } from 'zustand'
import { fetchSignals, fetchAvailableSignalsStrategies, setActiveStrategies, executeSignal, batchExecuteSignals, fetchSignalHistory, fetchSignalStats, type TradeSignal, type StrategyInfoItem, type SignalHistoryItem, type SignalStats } from '../services/api'
import { signalsWs } from '../utils/wsInstances'
import { useAppStore } from './useAppStore'

interface SignalState {
  signals: TradeSignal[]
  activeStrategies: string[]
  availableStrategies: StrategyInfoItem[]
  history: SignalHistoryItem[]
  stats: SignalStats | null
  total: number
  loading: boolean
  error: string | null
  loadSignals: () => Promise<void>
  loadAvailableStrategies: () => Promise<void>
  loadHistory: (strategy?: string, code?: string) => Promise<void>
  loadStats: () => Promise<void>
  setStrategies: (strategies: string[]) => Promise<void>
  execute: (code: string) => Promise<void>
  batchExecute: () => Promise<number>
  subscribeWs: () => () => void
}

let wsSubCleanups: (() => void)[] = []
let wsRefCount = 0
// Request deduplication: stale loadSignals responses are discarded
let _loadSignalsSeq = 0
// Debounce WS reconnect → loadSignals to prevent flood during reconnection cycles
let _reconnectLoadTimer: ReturnType<typeof setTimeout> | null = null

export const useSignalStore = create<SignalState>((set, get) => ({
  signals: [],
  activeStrategies: ['dual_low'],
  availableStrategies: [],
  history: [],
  stats: null,
  total: 0,
  loading: false,
  error: null,

  loadSignals: async () => {
    const seq = ++_loadSignalsSeq
    set({ loading: true, error: null })
    try {
      const data = await fetchSignals()
      // Discard stale responses — only the latest request updates state
      if (seq !== _loadSignalsSeq) return
      set({ signals: data.signals, activeStrategies: data.active_strategies, total: data.total, loading: false })
    } catch (e) {
      if (seq !== _loadSignalsSeq) return
      set({ error: String(e), loading: false })
    }
  },

  loadAvailableStrategies: async () => {
    set({ loading: true, error: null })
    try {
      const data = await fetchAvailableSignalsStrategies()
      set({ availableStrategies: data.strategies, loading: false })
    } catch (e) {
      console.error('[SignalStore] loadAvailableStrategies failed:', e)
      set({ error: String(e), loading: false })
    }
  },

  loadHistory: async (strategy?, code?) => {
    set({ loading: true, error: null })
    try {
      const data = await fetchSignalHistory(strategy, code, 200)
      set({ history: data.signals, loading: false })
    } catch (e) {
      console.error('[SignalStore] loadHistory failed:', e)
      set({ error: String(e), loading: false })
    }
  },

  loadStats: async () => {
    set({ loading: true, error: null })
    try {
      const data = await fetchSignalStats()
      set({ stats: data, loading: false })
    } catch (e) {
      console.error('[SignalStore] loadStats failed:', e)
      set({ error: String(e), loading: false })
    }
  },

  setStrategies: async (strategies) => {
    set({ loading: true, error: null })
    try {
      const data = await setActiveStrategies(strategies)
      const sigData = await fetchSignals()
      // Atomic update: single set() to avoid race with WS message handler
      set({ activeStrategies: data.active_strategies, signals: sigData.signals, total: sigData.total, loading: false })
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

  subscribeWs: () => {
    wsRefCount++

    if (wsRefCount === 1) {
      const unsubMsg = signalsWs.subscribe('signals', (data) => {
        try {
          // Handle both array and { signals: [...] } formats defensively
          let all: TradeSignal[]
          if (Array.isArray(data)) {
            all = data
          } else if (data && typeof data === 'object' && Array.isArray((data as Record<string, unknown>).signals)) {
            all = (data as Record<string, unknown>).signals as TradeSignal[]
          } else {
            return
          }
          const signals = all.filter((s: TradeSignal) => !s.executed)
          queueMicrotask(() => {
            try { set({ signals, total: all.length }) } catch (e) { console.error('[SignalStore] setState error:', e) }
          })
        } catch (e) {
          console.error('[SignalStore] WS message handler error:', e)
        }
      })

      // WS state change: debounced loadSignals on reconnect, auto-reconnect guard.
      // Does NOT track wsConnected here — use useAppStore.signalWsConnected instead.
      const unsubState = signalsWs.onStateChange((state) => {
        if (state === 'connected') {
          // Debounce: coalesce rapid reconnection cycles into a single loadSignals
          if (_reconnectLoadTimer) clearTimeout(_reconnectLoadTimer)
          _reconnectLoadTimer = setTimeout(() => {
            _reconnectLoadTimer = null
            // Only loadSignals if backend is connected (prevents API calls during backend outage)
            if (useAppStore.getState().backendConnected) {
              get().loadSignals().catch(() => {})
            }
          }, 2000)
        }
        // Auto-reconnect guard — only if backend is up
        if (!signalsWs.isConnected() && signalsWs.getState() === 'disconnected' && useAppStore.getState().backendConnected) {
          signalsWs.connect()
        }
      })

      wsSubCleanups = [unsubMsg, unsubState]
    }

    return () => {
      wsRefCount = Math.max(0, wsRefCount - 1)
      if (wsRefCount === 0) {
        wsSubCleanups.forEach(fn => { try { fn() } catch { /* ignore */ } })
        wsSubCleanups = []
        if (_reconnectLoadTimer) { clearTimeout(_reconnectLoadTimer); _reconnectLoadTimer = null }
      }
    }
  },
}))
