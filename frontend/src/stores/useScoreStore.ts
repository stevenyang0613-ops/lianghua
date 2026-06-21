import { create } from 'zustand'
import {
  fetchScoreRanking, fetchFullScoreRanking, fetchScoreAlerts, fetchComboAlerts,
  fetchAlertHistory, fetchScoreBacktestAccuracy, fetchTopPerformers,
  compareStrategies, fetchRiskMetrics, fetchScorePrediction,
  type ScoreRankingItem, type ScoreAlert, type ComboAlert,
  type AlertHistoryItem, type ScoreBacktestResult, type TopPerformer,
  type StrategyResult, type RiskMetrics, type ScorePrediction,
  type ScoreRankingParams,
} from '../services/api'
import { marketWs } from '../utils/wsInstances'

interface ScoreState {
  // Filtered ranking
  filteredData: { total: number; returned: number; items: ScoreRankingItem[] } | null
  filteredLoading: boolean
  filteredLoadedAt: number

  // Full ranking
  fullData: { total: number; items: ScoreRankingItem[] } | null
  fullLoading: boolean
  fullLoadedAt: number

  // Alerts
  alerts: ScoreAlert[]
  comboAlerts: ComboAlert[]
  alertHistory: AlertHistoryItem[]
  alertsLoadedAt: number

  // Backtest
  backtestResults: ScoreBacktestResult[] | null
  backtestSummary: { total_periods: number; avg_return_pct: number; avg_win_rate: number } | null
  topPerformers: TopPerformer[] | null
  strategyResults: StrategyResult[] | null
  riskMetrics: RiskMetrics | null
  prediction: ScorePrediction | null
  predictionCode: string
  backtestLoading: boolean
  strategyLoading: boolean
  riskLoading: boolean

  // WS-driven auto-refresh
  lastWsRefreshAt: number
  wsRefreshTimer: ReturnType<typeof setTimeout> | null

  // Actions
  loadFilteredRanking: (params: ScoreRankingParams) => Promise<void>
  loadFullRanking: () => Promise<void>
  loadAlerts: () => Promise<void>
  loadComboAlerts: () => Promise<void>
  loadAlertHistory: () => Promise<void>
  onWsTick: () => void
  setBacktestResults: (results: ScoreBacktestResult[] | null, summary: { total_periods: number; avg_return_pct: number; avg_win_rate: number } | null) => void
  setTopPerformers: (performers: TopPerformer[] | null) => void
  setStrategyResults: (results: StrategyResult[] | null) => void
  setRiskMetrics: (metrics: RiskMetrics | null) => void
  setPrediction: (code: string, prediction: ScorePrediction | null) => void
  setLoadingStates: (states: Partial<Pick<ScoreState, 'backtestLoading' | 'strategyLoading' | 'riskLoading'>>) => void
  invalidate: () => void
}

const STALE_MS = 3 * 60 * 1000 // 3 minutes

// User-configurable WS refresh interval (default 60s, stored in localStorage)
function getScoreWsRefreshInterval(): number {
  try {
    const saved = localStorage.getItem('score_ws_refresh_sec')
    if (saved) return parseInt(saved, 10) * 1000
  } catch { /* ignore */ }
  return 60 * 1000
}

export const useScoreStore = create<ScoreState>((set, get) => ({
  filteredData: null,
  filteredLoading: false,
  filteredLoadedAt: 0,

  fullData: null,
  fullLoading: false,
  fullLoadedAt: 0,

  alerts: [],
  comboAlerts: [],
  alertHistory: [],
  alertsLoadedAt: 0,

  backtestResults: null,
  backtestSummary: null,
  topPerformers: null,
  strategyResults: null,
  riskMetrics: null,
  prediction: null,
  predictionCode: '',
  backtestLoading: false,
  strategyLoading: false,
  riskLoading: false,

  lastWsRefreshAt: 0,
  wsRefreshTimer: null,

  loadFilteredRanking: async (params) => {
    const state = get()
    if (state.filteredLoading) return
    if (state.filteredData && state.filteredData.items.length > 0 && Date.now() - state.filteredLoadedAt < STALE_MS) {
      return
    }

    set({ filteredLoading: true })
    try {
      const data = await fetchScoreRanking(params)
      set({ filteredData: data, filteredLoading: false, filteredLoadedAt: Date.now() })
    } catch {
      set({ filteredLoading: false })
    }
  },

  loadFullRanking: async () => {
    const state = get()
    if (state.fullLoading) return
    if (state.fullData && state.fullData.items.length > 0 && Date.now() - state.fullLoadedAt < STALE_MS) {
      return
    }

    set({ fullLoading: true })
    try {
      const data = await fetchFullScoreRanking()
      set({ fullData: data, fullLoading: false, fullLoadedAt: Date.now() })
    } catch {
      set({ fullLoading: false })
    }
  },

  loadAlerts: async () => {
    const state = get()
    if (state.alerts.length > 0 && Date.now() - state.alertsLoadedAt < STALE_MS) return
    try {
      const data = await fetchScoreAlerts()
      set({ alerts: Array.isArray(data) ? data : data?.alerts || [], alertsLoadedAt: Date.now() })
    } catch { /* non-critical */ }
  },

  loadComboAlerts: async () => {
    try {
      const data = await fetchComboAlerts()
      set({ comboAlerts: Array.isArray(data) ? data : data?.alerts || [] })
    } catch { /* non-critical */ }
  },

  loadAlertHistory: async () => {
    try {
      const data = await fetchAlertHistory()
      set({ alertHistory: Array.isArray(data) ? data : data?.history || [] })
    } catch { /* non-critical */ }
  },

  setBacktestResults: (results, summary) => set({ backtestResults: results, backtestSummary: summary }),
  setTopPerformers: (performers) => set({ topPerformers: performers }),
  setStrategyResults: (results) => set({ strategyResults: results }),
  setRiskMetrics: (metrics) => set({ riskMetrics: metrics }),
  setPrediction: (code, prediction) => set({ predictionCode: code, prediction }),
  setLoadingStates: (states) => set(states),

  invalidate: () => {
    set({ filteredLoadedAt: 0, fullLoadedAt: 0, alertsLoadedAt: 0 })
  },

  // WS-driven auto-refresh for score ranking
  onWsTick: () => {
    const state = get()
    if (state.filteredLoading) return
    if (!state.filteredData) return

    const now = Date.now()
    const WS_REFRESH_INTERVAL = getScoreWsRefreshInterval()

    if (now - state.lastWsRefreshAt < WS_REFRESH_INTERVAL) {
      if (!state.wsRefreshTimer) {
        const delay = WS_REFRESH_INTERVAL - (now - state.lastWsRefreshAt)
        const timer = setTimeout(() => {
          set({ wsRefreshTimer: null, filteredLoadedAt: 0, lastWsRefreshAt: Date.now() })
        }, delay)
        set({ wsRefreshTimer: timer })
      }
      return
    }

    // Just mark as stale — next page visit will refresh
    set({ lastWsRefreshAt: now, filteredLoadedAt: 0, fullLoadedAt: 0 })
  },
}))

// Subscribe to market WS for auto-refresh
let _scoreWsUnsub: (() => void) | null = null
let _scoreWsRefCount = 0

export function subscribeScoreWs() {
  _scoreWsRefCount++
  if (_scoreWsRefCount === 1) {
    _scoreWsUnsub = marketWs.subscribe('tick', () => {
      useScoreStore.getState().onWsTick()
    })
  }
  return () => {
    _scoreWsRefCount = Math.max(0, _scoreWsRefCount - 1)
    if (_scoreWsRefCount === 0 && _scoreWsUnsub) {
      _scoreWsUnsub()
      _scoreWsUnsub = null
      const timer = useScoreStore.getState().wsRefreshTimer
      if (timer) {
        clearTimeout(timer)
        useScoreStore.setState({ wsRefreshTimer: null })
      }
    }
  }
}
