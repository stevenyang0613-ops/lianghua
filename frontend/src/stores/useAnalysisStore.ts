import { create } from 'zustand'
import {
  fetchForcedRedemption, fetchDualLowRanking, fetchPulseScan,
  fetchRevisionProbability, fetchStockCorrelation,
  type ForcedRedemptionItem, type DualLowItem, type PulseItem, type RevisionItem, type StockCorrelationItem,
} from '../services/api'

interface AnalysisState {
  // Forced redemption data
  forcedRedemption: { total: number; high_risk_count: number; items: ForcedRedemptionItem[] } | null
  forcedRedemptionLoading: boolean
  forcedRedemptionLoadedAt: number

  // Dual low ranking
  dualLowRanking: { total: number; items: DualLowItem[] } | null
  dualLowLoading: boolean
  dualLowLoadedAt: number

  // Pulse scan
  pulseScan: { total: number; items: PulseItem[] } | null
  pulseLoading: boolean
  pulseLoadedAt: number

  // Revision probability
  revision: { total: number; items: RevisionItem[] } | null
  revisionLoading: boolean
  revisionLoadedAt: number

  // Stock correlation
  stockCorrelation: { total: number; strong_correlation_count: number; items: StockCorrelationItem[] } | null
  correlationLoading: boolean
  correlationLoadedAt: number

  // Actions
  loadForcedRedemption: (opts?: Record<string, any>) => Promise<void>
  loadDualLowRanking: (opts?: Record<string, any>) => Promise<void>
  loadPulseScan: (opts?: Record<string, any>) => Promise<void>
  loadRevision: (opts?: Record<string, any>) => Promise<void>
  loadStockCorrelation: (opts?: Record<string, any>) => Promise<void>
  loadAllTabs: () => Promise<void>
  invalidate: () => void
}

const STALE_MS = 3 * 60 * 1000 // 3 minutes

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  forcedRedemption: null,
  forcedRedemptionLoading: false,
  forcedRedemptionLoadedAt: 0,

  dualLowRanking: null,
  dualLowLoading: false,
  dualLowLoadedAt: 0,

  pulseScan: null,
  pulseLoading: false,
  pulseLoadedAt: 0,

  revision: null,
  revisionLoading: false,
  revisionLoadedAt: 0,

  stockCorrelation: null,
  correlationLoading: false,
  correlationLoadedAt: 0,

  loadForcedRedemption: async (opts) => {
    const state = get()
    if (state.forcedRedemptionLoading) return
    if (state.forcedRedemption && Date.now() - state.forcedRedemptionLoadedAt < STALE_MS && !opts) return

    set({ forcedRedemptionLoading: true })
    try {
      const data = await fetchForcedRedemption(opts)
      set({ forcedRedemption: data, forcedRedemptionLoading: false, forcedRedemptionLoadedAt: Date.now() })
    } catch {
      set({ forcedRedemptionLoading: false })
    }
  },

  loadDualLowRanking: async (opts) => {
    const state = get()
    if (state.dualLowLoading) return
    if (state.dualLowRanking && Date.now() - state.dualLowLoadedAt < STALE_MS && !opts) return

    set({ dualLowLoading: true })
    try {
      const data = await fetchDualLowRanking(opts)
      set({ dualLowRanking: data, dualLowLoading: false, dualLowLoadedAt: Date.now() })
    } catch {
      set({ dualLowLoading: false })
    }
  },

  loadPulseScan: async (opts) => {
    const state = get()
    if (state.pulseLoading) return
    if (state.pulseScan && Date.now() - state.pulseLoadedAt < STALE_MS && !opts) return

    set({ pulseLoading: true })
    try {
      const data = await fetchPulseScan(opts)
      set({ pulseScan: data, pulseLoading: false, pulseLoadedAt: Date.now() })
    } catch {
      set({ pulseLoading: false })
    }
  },

  loadRevision: async (opts) => {
    const state = get()
    if (state.revisionLoading) return
    if (state.revision && Date.now() - state.revisionLoadedAt < STALE_MS && !opts) return

    set({ revisionLoading: true })
    try {
      const data = await fetchRevisionProbability(opts)
      set({ revision: data, revisionLoading: false, revisionLoadedAt: Date.now() })
    } catch {
      set({ revisionLoading: false })
    }
  },

  loadStockCorrelation: async (opts) => {
    const state = get()
    if (state.correlationLoading) return
    if (state.stockCorrelation && Date.now() - state.correlationLoadedAt < STALE_MS && !opts) return

    set({ correlationLoading: true })
    try {
      const data = await fetchStockCorrelation(opts)
      set({ stockCorrelation: data, correlationLoading: false, correlationLoadedAt: Date.now() })
    } catch {
      set({ correlationLoading: false })
    }
  },

  loadAllTabs: async () => {
    const state = get()
    const now = Date.now()
    // Load all tabs in parallel, but only if stale
    const promises: Promise<void>[] = []
    if (!state.forcedRedemption || now - state.forcedRedemptionLoadedAt >= STALE_MS) {
      promises.push(state.loadForcedRedemption())
    }
    if (!state.dualLowRanking || now - state.dualLowLoadedAt >= STALE_MS) {
      promises.push(state.loadDualLowRanking())
    }
    if (!state.pulseScan || now - state.pulseLoadedAt >= STALE_MS) {
      promises.push(state.loadPulseScan())
    }
    if (!state.revision || now - state.revisionLoadedAt >= STALE_MS) {
      promises.push(state.loadRevision())
    }
    if (!state.stockCorrelation || now - state.correlationLoadedAt >= STALE_MS) {
      promises.push(state.loadStockCorrelation())
    }
    await Promise.allSettled(promises)
  },

  invalidate: () => {
    set({
      forcedRedemptionLoadedAt: 0,
      dualLowLoadedAt: 0,
      pulseLoadedAt: 0,
      revisionLoadedAt: 0,
      correlationLoadedAt: 0,
    })
  },
}))
