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
      const merged: ConvertibleQuote = (existing && !('name' in q && q.name))
        ? { ...existing, ...q, name: q.name || existing.name }
        : q
      // 比较所有字段，避免 volume、stock_price 等字段更新被静默丢失
      let differs = !existing
      if (existing && !differs) {
        for (const key of Object.keys(merged) as (keyof typeof merged)[]) {
          if (merged[key] !== existing[key]) {
            differs = true
            break
          }
        }
      }
      if (differs) {
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
    bondsCache.clear()
  },
}))
