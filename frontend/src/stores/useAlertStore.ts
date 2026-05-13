import { create } from 'zustand'

export type AlertType = 'price_above' | 'price_below' | 'premium_above' | 'premium_below' | 'dual_low_below' | 'ytm_above'

export interface AlertCondition {
  code: string
  name: string
  alert_type: AlertType
  threshold: number
  enabled: boolean
  created_at: string
}

export interface AlertTrigger {
  code: string
  name: string
  alert_type: AlertType
  threshold: number
  current_value: number
  triggered_at: string
  acknowledged: boolean
}

interface AlertState {
  alerts: AlertCondition[]
  triggers: AlertTrigger[]
  setAlerts: (alerts: AlertCondition[]) => void
  addAlert: (alert: AlertCondition) => void
  removeAlert: (alertId: string) => void
  addTrigger: (trigger: AlertTrigger) => void
  clearTriggers: () => void
}

export const useAlertStore = create<AlertState>((set) => ({
  alerts: [],
  triggers: [],

  setAlerts: (alerts) => set({ alerts }),

  addAlert: (alert) => set((state) => ({ alerts: [...state.alerts, alert] })),

  removeAlert: (alertId) => set((state) => ({
    alerts: state.alerts.filter((a) => `${a.code}_${a.alert_type}` !== alertId),
  })),

  addTrigger: (trigger) => set((state) => ({ triggers: [...state.triggers, trigger] })),

  clearTriggers: () => set({ triggers: [] }),
}))
