import { create } from 'zustand'
import { fetchExchangeableBonds } from '../services/api'
import type { ConvertibleQuote } from '../types'

interface ExchangeableState {
  data: ConvertibleQuote[]
  total: number
  loading: boolean
  loadedAt: number

  loadData: () => Promise<void>
  invalidate: () => void
}

const STALE_MS = 5 * 60 * 1000 // 5 minutes

export const useExchangeableStore = create<ExchangeableState>((set, get) => ({
  data: [],
  total: 0,
  loading: false,
  loadedAt: 0,

  loadData: async () => {
    const state = get()
    if (state.loading) return
    if (state.data.length > 0 && Date.now() - state.loadedAt < STALE_MS) return

    set({ loading: true })
    try {
      const res = await fetchExchangeableBonds()
      const bonds = Array.isArray(res) ? res : res?.bonds || []
      set({ data: bonds, total: bonds.length, loading: false, loadedAt: Date.now() })
    } catch {
      set({ loading: false })
    }
  },

  invalidate: () => {
    set({ loadedAt: 0 })
  },
}))
