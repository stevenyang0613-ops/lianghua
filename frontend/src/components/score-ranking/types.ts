import type { ScoreRankingItem, ScoreAlert, ComboAlert, ComboCondition, AlertHistoryItem, ScoreHistoryItem, ScoreBacktestResult, TopPerformer, StrategyResult, RiskMetrics, ScorePrediction } from '../../services/api'

// Re-export API types so sub-components don't need to import from services/api directly
export type { ScoreRankingItem, ScoreAlert, ComboAlert, ComboCondition, AlertHistoryItem, ScoreHistoryItem, ScoreBacktestResult, TopPerformer, StrategyResult, RiskMetrics, ScorePrediction }

export interface ScoreFilterCardProps {
  topN: number
  maxPremium: number
  minPrice: number
  loading: boolean
  onTopNChange: (v: number) => void
  onMaxPremiumChange: (v: number) => void
  onMinPriceChange: (v: number) => void
  onApply: () => void
}

export interface WeightConfigCardProps {
  weights: Record<string, number>
  selectedFactor: string
  customFactors: Record<string, { name: string; weights: Record<string, number> }>
  onWeightChange: (key: string, value: number) => void
  onLoadFactor: (factorId: string) => void
  onResetWeights: () => void
}

export interface ScoreStatsRowProps {
  total: number
  returned: number
  items: ScoreRankingItem[]
}

export interface ScoreDistributionChartProps {
  items: ScoreRankingItem[]
}

export interface AlertManageModalProps {
  open: boolean
  alerts: ScoreAlert[]
  newAlert: { code: string; name: string; alert_type: 'score' | 'price' | 'dual_low' | 'premium'; threshold: number; direction: 'above' | 'below' }
  notificationEnabled: boolean
  notificationSoundEnabled: boolean
  onClose: () => void
  onNewAlertChange: (alert: AlertManageModalProps['newAlert']) => void
  onAddAlert: () => void
  onDeleteAlert: (id: number) => void
  onCheckAlerts: () => void
  onNotificationChange: (enabled: boolean) => void
  onSoundChange: (enabled: boolean) => void
}

export interface ComboAlertModalProps {
  open: boolean
  comboAlerts: ComboAlert[]
  newComboName: string
  newComboLogic: 'AND' | 'OR'
  newComboConditions: ComboCondition[]
  onClose: () => void
  onComboNameChange: (name: string) => void
  onComboLogicChange: (logic: 'AND' | 'OR') => void
  onConditionsChange: (conditions: ComboCondition[]) => void
  onAddComboAlert: () => void
  onDeleteComboAlert: (id: number) => void
  onCheckComboAlerts: () => void
}

export interface AlertHistoryModalProps {
  open: boolean
  alertHistory: AlertHistoryItem[]
  onClose: () => void
  onAcknowledge: (id: number) => void
}

export interface FactorConfigModalProps {
  open: boolean
  newFactorName: string
  customFactors: Record<string, { name: string; weights: Record<string, number> }>
  onClose: () => void
  onNewFactorNameChange: (name: string) => void
  onSaveCustomFactor: () => void
  onLoadFactor: (factorId: string) => void
  onDeleteFactor: (factorId: string) => void
}

export interface ScoreHistoryModalProps {
  open: boolean
  selectedCode: string
  scoreHistory: ScoreHistoryItem[]
  historyLoading: boolean
  onClose: () => void
}

export interface PredictionModalProps {
  open: boolean
  predictionCode: string
  prediction: ScorePrediction | null
  predictionLoading: boolean
  onClose: () => void
}

export interface StrategyCompareCardProps {
  strategyResults: StrategyResult[] | null
  strategyLoading: boolean
  onRunStrategyCompare: () => void
}

export interface RiskAnalysisCardProps {
  riskMetrics: RiskMetrics | null
  riskLoading: boolean
  onRunRiskAnalysis: () => void
}

export interface BacktestChartCardProps {
  chartData: { dates: string[]; returns: number[]; winRates: number[] } | null
}

export interface BacktestPanelProps {
  backtestParams: { startDate: string; endDate: string; topN: number; holdDays: number }
  backtestLoading: boolean
  backtestResults: ScoreBacktestResult[] | null
  backtestSummary: { total_periods: number; avg_return_pct: number; avg_win_rate: number } | null
  backtestChartData: { dates: string[]; returns: number[]; winRates: number[] } | null
  topPerformers: TopPerformer[] | null
  performersSummary: { total: number; winners: number; win_rate: number; avg_return_pct: number } | null
  strategyResults: StrategyResult[] | null
  strategyLoading: boolean
  riskMetrics: RiskMetrics | null
  riskLoading: boolean
  onParamsChange: (params: BacktestPanelProps['backtestParams']) => void
  onRunBacktest: () => void
  onLoadTopPerformers: () => void
  onRunStrategyCompare: () => void
  onRunRiskAnalysis: () => void
}
