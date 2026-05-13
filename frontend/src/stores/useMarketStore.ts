import { create } from 'zustand'
import type { ConvertibleQuote } from '../types'

interface MarketState {
  bonds: Map<string, ConvertibleQuote>
  allBonds: ConvertibleQuote[]
  updatedAt: string
  updateQuotes: (quotes: ConvertibleQuote[]) => void
  setAllBonds: (bonds: ConvertibleQuote[]) => void
}

export const useMarketStore = create<MarketState>((set, get) => ({
  bonds: new Map(),
  allBonds: [],
  updatedAt: '',

  updateQuotes: (quotes) => {
    const bonds = new Map(get().bonds)
    for (const q of quotes) {
      bonds.set(q.code, q)
    }
    set({
      bonds,
      allBonds: Array.from(bonds.values()),
      updatedAt: new Date().toLocaleTimeString(),
    })
  },

  setAllBonds: (bonds) => {
    const m = new Map<string, ConvertibleQuote>()
    for (const b of bonds) m.set(b.code, b)
    set({ bonds: m, allBonds: bonds })
  },
}))
