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
    if (!Array.isArray(quotes) || quotes.length === 0) return
    let changed = false
    for (const q of quotes) {
      if (!q || !q.code) continue
      const existing = bondsCache.get(q.code)
      // 增量数据合并：如果缺少 name 字段说明是增量 tick，从 cache 合并
      const merged = (existing && !('name' in q && q.name))
        ? { ...existing, ...q }
        : q
      if (!existing || existing.price !== merged.price || existing.change_pct !== merged.change_pct || existing.is_called !== merged.is_called || existing.call_status !== merged.call_status || existing.forced_call_days !== merged.forced_call_days || existing.last_trade_date !== merged.last_trade_date || existing.maturity_date !== merged.maturity_date) {
        bondsCache.set(merged.code, merged)
        changed = true
      }
    }
    if (!changed) return
    // Content changed: debounce both allBonds and updatedAt together
    // to avoid triggering multiple re-renders per tick
    pendingBondsUpdate = Array.from(bondsCache.values())
    if (!bondsUpdateTimer) {
      bondsUpdateTimer = setTimeout(() => {
        bondsUpdateTimer = null
        if (pendingBondsUpdate) {
          set({ allBonds: pendingBondsUpdate, updatedAt: new Date().toLocaleTimeString() })
          pendingBondsUpdate = null
        }
      }, BONDS_DEBOUNCE_MS)
    }
  },

  setAllBonds: (bonds) => {
    if (!Array.isArray(bonds)) {
      bondsCache.clear()
      set({ allBonds: [] })
      return
    }
    bondsCache.clear()
    for (const b of bonds) {
      if (b && b.code) {
        bondsCache.set(b.code, b)
      }
    }
    // Flush any pending debounced update
    if (bondsUpdateTimer) {
      clearTimeout(bondsUpdateTimer)
      bondsUpdateTimer = null
      pendingBondsUpdate = null
    }
    set({ allBonds: Array.from(bondsCache.values()) })
  },

  destroy: () => {
    if (bondsUpdateTimer) {
      clearTimeout(bondsUpdateTimer)
      bondsUpdateTimer = null
      pendingBondsUpdate = null
    }
  },
}))
