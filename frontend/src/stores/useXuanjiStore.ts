import { create } from 'zustand'
import {
  fetchXuanjiRanking, fetchXuanjiGreeks, fetchXuanjiMarketWeights,
  fetchXuanjiAlphaSources, fetchXuanjiStressTest, fetchXuanjiFactorContribution,
  fetchXuanjiFactorCorrelation, fetchXuanjiComparison, fetchXuanjiSingle,
  fetchXuanjiDeltaCandidates,
  type XuanjiItem, type XuanjiGreeksSummary, type XuanjiMarketWeightsResponse,
  type XuanjiAlphaResponse, type XuanjiStressResponse, type XuanjiFactorContributionResponse,
  type XuanjiFactorCorrelationResponse, type XuanjiComparisonResponse,
  type XuanjiSingleResponse, type XuanjiDeltaResponse,
} from '../services/api'
import { marketWs } from '../utils/wsInstances'

interface RankingInfo {
  total: number
  market_state_detected: string
  total_unfiltered?: number
}

interface RankingParams {
  topN: number
  marketState: string
  maxPremium: number
  minPrice: number
  maxPrice: number
  volAdjust: number
}

interface XuanjiState {
  // Ranking data
  rankingData: XuanjiItem[]
  rankingInfo: RankingInfo | null
  rankingLoading: boolean
  rankingParams: RankingParams | null
  rankingLoadedAt: number

  // Static data (rarely changes)
  greeks: XuanjiGreeksSummary | null
  marketWeights: XuanjiMarketWeightsResponse | null
  alphaSources: XuanjiAlphaResponse | null
  staticDataLoadedAt: number

  // Computed data (changes with params)
  stressTest: XuanjiStressResponse | null
  factorContribution: XuanjiFactorContributionResponse | null
  factorCorrelation: XuanjiFactorCorrelationResponse | null
  comparison: XuanjiComparisonResponse | null
  deltaCandidates: XuanjiDeltaResponse | null

  // Detail modal
  selectedDetail: XuanjiSingleResponse | null
  detailLoading: boolean

  // WS-driven auto-refresh
  lastWsRefreshAt: number
  wsRefreshTimer: ReturnType<typeof setTimeout> | null

  // Actions
  loadRanking: (params: { topN: number; marketState: string; maxPremium: number; minPrice: number; maxPrice: number; volAdjust: number }) => Promise<void>
  loadStaticData: () => Promise<void>
  loadComputedData: (params: { topN: number; marketState: string }) => Promise<void>
  loadSingleDetail: (code: string, params: { marketState: string; maxPremium: number; minPrice: number; maxPrice: number; volAdjust: number }) => Promise<void>
  loadDeltaCandidates: (params: { minIvHv: number; premiumLow: number; premiumHigh: number; topN: number }) => Promise<void>
  onWsTick: () => void
  invalidate: () => void
}

const STALE_MS = 3 * 60 * 1000 // 3 minutes stale threshold
const STATIC_STALE_MS = 10 * 60 * 1000 // 10 minutes for static data

// User-configurable WS refresh interval (default 30s, stored in localStorage)
function getWsRefreshInterval(): number {
  try {
    const saved = localStorage.getItem('xuanji_ws_refresh_sec')
    if (saved) {
      const parsed = parseInt(saved, 10)
      return Number.isFinite(parsed) && parsed > 0 ? parsed * 1000 : 30 * 1000
    }
  } catch { /* ignore */ }
  return 30 * 1000
}

export const useXuanjiStore = create<XuanjiState>((set, get) => ({
  rankingData: [],
  rankingInfo: null,
  rankingLoading: false,
  rankingParams: null,
  rankingLoadedAt: 0,

  greeks: null,
  marketWeights: null,
  alphaSources: null,
  staticDataLoadedAt: 0,

  stressTest: null,
  factorContribution: null,
  factorCorrelation: null,
  comparison: null,
  deltaCandidates: null,

  selectedDetail: null,
  detailLoading: false,

  lastWsRefreshAt: 0,
  wsRefreshTimer: null,

  loadRanking: async (params) => {
    const state = get()
    // Skip if already loading
    if (state.rankingLoading) return

    // Return cached data if fresh enough and params match
    const paramsMatch = JSON.stringify(state.rankingParams) === JSON.stringify(params)
    if (paramsMatch && state.rankingData.length > 0 && Date.now() - state.rankingLoadedAt < STALE_MS) {
      return
    }

    set({ rankingLoading: true })
    try {
      const result = await fetchXuanjiRanking(params.topN, params.marketState, params.maxPremium, params.minPrice, params.maxPrice, params.volAdjust)
      set({
        rankingData: result.items || [],
        rankingInfo: { total: result.total, market_state_detected: result.market_state_detected, total_unfiltered: result.total_unfiltered },
        rankingParams: params,
        rankingLoadedAt: Date.now(),
        rankingLoading: false,
      })
    } catch (e) {
      console.error('[XuanjiStore] loadRanking failed:', e)
      set({ rankingLoading: false })
    }
  },

  loadStaticData: async () => {
    const state = get()
    // Skip if fresh enough
    if (state.staticDataLoadedAt > 0 && Date.now() - state.staticDataLoadedAt < STATIC_STALE_MS) {
      return
    }

    try {
      const [greeks, marketWeights, alphaSources] = await Promise.allSettled([
        state.greeks ? Promise.resolve(state.greeks) : fetchXuanjiGreeks(),
        state.marketWeights ? Promise.resolve(state.marketWeights) : fetchXuanjiMarketWeights(),
        state.alphaSources ? Promise.resolve(state.alphaSources) : fetchXuanjiAlphaSources(),
      ])

      set({
        greeks: greeks.status === 'fulfilled' ? greeks.value : state.greeks,
        marketWeights: marketWeights.status === 'fulfilled' ? marketWeights.value : state.marketWeights,
        alphaSources: alphaSources.status === 'fulfilled' ? alphaSources.value : state.alphaSources,
        staticDataLoadedAt: Date.now(),
      })
    } catch (e) {
      console.error('[XuanjiStore] loadStaticData failed:', e)
    }
  },

  loadComputedData: async (params) => {
    try {
      const [stressTest, factorContribution, factorCorrelation, comparison] = await Promise.allSettled([
        fetchXuanjiStressTest(params.topN, params.marketState),
        fetchXuanjiFactorContribution(Math.min(params.topN, 20), params.marketState),
        fetchXuanjiFactorCorrelation(params.topN, params.marketState),
        fetchXuanjiComparison(params.topN, params.marketState),
      ])

      set({
        stressTest: stressTest.status === 'fulfilled' ? stressTest.value : null,
        factorContribution: factorContribution.status === 'fulfilled' ? factorContribution.value : null,
        factorCorrelation: factorCorrelation.status === 'fulfilled' ? factorCorrelation.value : null,
        comparison: comparison.status === 'fulfilled' ? comparison.value : null,
      })
    } catch (e) {
      console.error('[XuanjiStore] loadComputedData failed:', e)
    }
  },

  loadSingleDetail: async (code, params) => {
    set({ detailLoading: true })
    try {
      const detail = await fetchXuanjiSingle(code, params.marketState, params.maxPremium, params.minPrice, params.maxPrice, params.volAdjust)
      set({ selectedDetail: detail, detailLoading: false })
    } catch (e) {
      console.error('[XuanjiStore] loadSingleDetail failed:', e)
      set({ detailLoading: false })
    }
  },

  loadDeltaCandidates: async (params) => {
    try {
      const result = await fetchXuanjiDeltaCandidates(params.minIvHv, params.premiumLow, params.premiumHigh, params.topN)
      set({ deltaCandidates: result })
    } catch (e) {
      console.error('[XuanjiStore] loadDeltaCandidates failed:', e)
    }
  },

  invalidate: () => {
    set({ rankingLoadedAt: 0, staticDataLoadedAt: 0 })
  },

  // WS-driven auto-refresh: when market tick arrives, schedule a ranking refresh
  // Throttled to max once per 30 seconds to avoid excessive API calls
  onWsTick: () => {
    const state = get()
    if (state.rankingLoading) return
    if (!state.rankingParams) return // No initial load yet

    const now = Date.now()
    const WS_REFRESH_INTERVAL = getWsRefreshInterval()

    if (now - state.lastWsRefreshAt < WS_REFRESH_INTERVAL) {
      // Too soon, schedule a delayed refresh if not already scheduled
      if (!state.wsRefreshTimer) {
        const delay = Math.max(0, WS_REFRESH_INTERVAL - (now - state.lastWsRefreshAt))
        if (Number.isFinite(delay)) {
          const timer = setTimeout(() => {
            set({ wsRefreshTimer: null })
            const currentState = get()
            if (currentState.rankingParams && !currentState.rankingLoading) {
              // Force refresh by resetting loadedAt
              set({ rankingLoadedAt: 0, lastWsRefreshAt: Date.now() })
              get().loadRanking(currentState.rankingParams as RankingParams)
            }
          }, delay)
          set({ wsRefreshTimer: timer })
        }
      }
      return
    }

    // Refresh immediately
    set({ lastWsRefreshAt: now, rankingLoadedAt: 0 })
    if (state.rankingParams) {
      get().loadRanking(state.rankingParams)
    }
  },
}))

// Subscribe to market WS for auto-refresh
let _wsUnsub: (() => void) | null = null
let _wsRefCount = 0

export function destroyXuanjiStore(): void {
  if (_wsUnsub) {
    _wsUnsub()
    _wsUnsub = null
  }
  _wsRefCount = 0
  const timer = useXuanjiStore.getState().wsRefreshTimer
  if (timer) {
    clearTimeout(timer)
    useXuanjiStore.setState({ wsRefreshTimer: null })
  }
}

export function subscribeXuanjiWs() {
  _wsRefCount++
  if (_wsRefCount === 1) {
    _wsUnsub = marketWs.subscribe('tick', () => {
      useXuanjiStore.getState().onWsTick()
    })
  }
  return () => {
    _wsRefCount = Math.max(0, _wsRefCount - 1)
    if (_wsRefCount === 0 && _wsUnsub) {
      _wsUnsub()
      _wsUnsub = null
      const timer = useXuanjiStore.getState().wsRefreshTimer
      if (timer) {
        clearTimeout(timer)
        useXuanjiStore.setState({ wsRefreshTimer: null })
      }
    }
  }
}
