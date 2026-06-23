import { create } from 'zustand'
import { fetchStrategies, fetchSignalHistory, fetchSignalStats, type StrategyInfo, type SignalHistoryItem, type SignalStats } from '../services/api'

interface StrategyState {
  strategies: StrategyInfo[]
  loading: boolean
  loadedAt: number

  selectedStrategy: StrategyInfo | null
  signalHistory: SignalHistoryItem[]
  signalHistoryLoading: boolean

  signalStats: SignalStats | null
  statsLoadedAt: number

  // 全局错误状态
  error: string | null

  loadStrategies: () => Promise<void>
  selectStrategy: (strategy: StrategyInfo) => Promise<void>
  loadSignalHistory: (strategyId: string, limit?: number) => Promise<void>
  loadStats: () => Promise<void>
  invalidate: () => void
}

const STALE_MS = 5 * 60 * 1000 // 5 minutes

export const useStrategyStore = create<StrategyState>((set, get) => ({
  strategies: [],
  loading: false,
  loadedAt: 0,

  selectedStrategy: null,
  signalHistory: [],
  signalHistoryLoading: false,

  signalStats: null,
  statsLoadedAt: 0,

  error: null,

  loadStrategies: async () => {
    const state = get()
    if (state.loading) return
    if (state.strategies.length > 0 && Date.now() - state.loadedAt < STALE_MS) return

    set({ loading: true, error: null })
    try {
      const list = await fetchStrategies()
      const selected = state.selectedStrategy || (list.length > 0 ? list[0] : null)
      set({ strategies: list, selectedStrategy: selected, loading: false, loadedAt: Date.now(), error: null })
    } catch (e) {
      console.error('[StrategyStore] loadStrategies failed:', e)
      set({ loading: false, error: String(e) })
    }
  },

  selectStrategy: async (strategy) => {
    set({ selectedStrategy: strategy, error: null })
    // Load history for the selected strategy
    await get().loadSignalHistory(strategy.id, 50)
  },

  loadSignalHistory: async (strategyId, limit = 50) => {
    set({ signalHistoryLoading: true, error: null })
    try {
      const data = await fetchSignalHistory(strategyId, undefined, limit)
      set({ signalHistory: data.signals || [], signalHistoryLoading: false, error: null })
    } catch (e) {
      console.error('[StrategyStore] loadSignalHistory failed:', e)
      set({ signalHistoryLoading: false, error: String(e) })
    }
  },

  loadStats: async () => {
    const state = get()
    if (state.signalStats && Date.now() - state.statsLoadedAt < STALE_MS) return
    try {
      const data = await fetchSignalStats()
      set({ signalStats: data, statsLoadedAt: Date.now(), error: null })
    } catch (e) {
      console.error('[StrategyStore] loadStats failed:', e)
      set({ error: String(e) })
    }
  },

  invalidate: () => {
    set({ loadedAt: 0, statsLoadedAt: 0, error: null })
  },
}))
