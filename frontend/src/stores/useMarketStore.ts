import { create } from 'zustand'
import type { ConvertibleQuote } from '../types'

// Module-level mutable cache — never cloned, updated in-place
const bondsCache = new Map<string, ConvertibleQuote>()

// Debounce state: allBonds updates are deferred so rapid ticks don't
// cause excessive re-renders. updatedAt still fires immediately.
let bondsUpdateTimer: ReturnType<typeof setTimeout> | null = null
let pendingBondsUpdate: ConvertibleQuote[] | null = null

const BONDS_DEBOUNCE_MS = 150

interface MarketState {
  allBonds: ConvertibleQuote[]
  updatedAt: string
  updateQuotes: (quotes: ConvertibleQuote[]) => void
  setAllBonds: (bonds: ConvertibleQuote[]) => void
  destroy: () => void
}

export const useMarketStore = create<MarketState>((set, _get) => ({
  allBonds: [],
  updatedAt: '',

  updateQuotes: (quotes) => {
    let changed = false
    for (const q of quotes) {
      const existing = bondsCache.get(q.code)
      // 增量数据合并：如果缺少 name 字段说明是增量 tick，从 cache 合并
      const merged = (existing && !('name' in q && q.name))
        ? { ...existing, ...q }
        : q
      if (!existing || existing.price !== merged.price || existing.change_pct !== merged.change_pct) {
        bondsCache.set(merged.code, merged)
        changed = true
      }
    }
    if (!changed) {
      // No actual content change — only update timestamp
      set({ updatedAt: new Date().toLocaleTimeString() })
      return
    }
    // Content changed: debounce allBonds to avoid rapid re-renders,
    // but update updatedAt immediately for UI freshness indicators.
    pendingBondsUpdate = Array.from(bondsCache.values())
    set({ updatedAt: new Date().toLocaleTimeString() })
    if (!bondsUpdateTimer) {
      bondsUpdateTimer = setTimeout(() => {
        bondsUpdateTimer = null
        if (pendingBondsUpdate) {
          set({ allBonds: pendingBondsUpdate })
          pendingBondsUpdate = null
        }
      }, BONDS_DEBOUNCE_MS)
    }
  },

  setAllBonds: (bonds) => {
    bondsCache.clear()
    for (const b of bonds) bondsCache.set(b.code, b)
    // Flush any pending debounced update
    if (bondsUpdateTimer) {
      clearTimeout(bondsUpdateTimer)
      bondsUpdateTimer = null
      pendingBondsUpdate = null
    }
    set({ allBonds: bonds })
  },

  destroy: () => {
    if (bondsUpdateTimer) {
      clearTimeout(bondsUpdateTimer)
      bondsUpdateTimer = null
      pendingBondsUpdate = null
    }
  },
}))
