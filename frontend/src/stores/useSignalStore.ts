import { create } from 'zustand'
import { fetchSignals, fetchAvailableSignalsStrategies, setActiveStrategies, executeSignal, type TradeSignal, type StrategyInfoItem } from '../services/api'

interface SignalState {
  signals: TradeSignal[]
  activeStrategies: string[]
  availableStrategies: StrategyInfoItem[]
  total: number
  loading: boolean
  error: string | null
  loadSignals: () => Promise<void>
  loadAvailableStrategies: () => Promise<void>
  setStrategies: (strategies: string[]) => Promise<void>
  execute: (code: string) => Promise<void>
}

export const useSignalStore = create<SignalState>((set) => ({
  signals: [],
  activeStrategies: ['dual_low'],
  availableStrategies: [],
  total: 0,
  loading: false,
  error: null,

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
}))
