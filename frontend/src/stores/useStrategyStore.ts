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

  loadStrategies: () => Promise<void>
  selectStrategy: (strategy: StrategyInfo) => void
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

  loadStrategies: async () => {
    const state = get()
    if (state.loading) return
    if (state.strategies.length > 0 && Date.now() - state.loadedAt < STALE_MS) return

    set({ loading: true })
    try {
      const list = await fetchStrategies()
      const selected = state.selectedStrategy || (list.length > 0 ? list[0] : null)
      set({ strategies: list, selectedStrategy: selected, loading: false, loadedAt: Date.now() })
    } catch {
      set({ loading: false })
    }
  },

  selectStrategy: (strategy) => {
    set({ selectedStrategy: strategy })
    // Load history for the selected strategy
    get().loadSignalHistory(strategy.id, 50)
  },

  loadSignalHistory: async (strategyId, limit = 50) => {
    set({ signalHistoryLoading: true })
    try {
      const data = await fetchSignalHistory(strategyId, undefined, limit)
      set({ signalHistory: data.signals || [], signalHistoryLoading: false })
    } catch {
      set({ signalHistoryLoading: false })
    }
  },

  loadStats: async () => {
    const state = get()
    if (state.signalStats && Date.now() - state.statsLoadedAt < STALE_MS) return
    try {
      const data = await fetchSignalStats()
      set({ signalStats: data, statsLoadedAt: Date.now() })
    } catch { /* non-critical */ }
  },

  invalidate: () => {
    set({ loadedAt: 0, statsLoadedAt: 0 })
  },
}))
