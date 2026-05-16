import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface ShortcutConfig {
  navigateHome: string
  navigateMarket: string
  navigateStrategies: string
  navigateBacktest: string
  navigateTrade: string
  navigateSignals: string
  refreshData: string
  exportReport: string
  toggleFullscreen: string
  openDevTools: string
}

const defaultShortcuts: ShortcutConfig = {
  navigateHome: 'CmdOrCtrl+1',
  navigateMarket: 'CmdOrCtrl+2',
  navigateStrategies: 'CmdOrCtrl+3',
  navigateBacktest: 'CmdOrCtrl+4',
  navigateTrade: 'CmdOrCtrl+5',
  navigateSignals: 'CmdOrCtrl+6',
  refreshData: 'CmdOrCtrl+R',
  exportReport: 'CmdOrCtrl+E',
  toggleFullscreen: 'F11',
  openDevTools: 'F12',
}

interface ShortcutStore {
  shortcuts: ShortcutConfig
  isEditing: boolean
  updateShortcut: (key: keyof ShortcutConfig, value: string) => void
  resetToDefaults: () => void
  setIsEditing: (value: boolean) => void
  getShortcutLabel: (action: keyof ShortcutConfig) => string
}

const shortcutLabels: Record<keyof ShortcutConfig, string> = {
  navigateHome: '首页',
  navigateMarket: '市场行情',
  navigateStrategies: '交易策略',
  navigateBacktest: '回测分析',
  navigateTrade: '交易终端',
  navigateSignals: '信号监控',
  refreshData: '刷新数据',
  exportReport: '导出报告',
  toggleFullscreen: '全屏切换',
  openDevTools: '开发者工具',
}

export const useShortcutStore = create<ShortcutStore>()(
  persist(
    (set) => ({
      shortcuts: defaultShortcuts,
      isEditing: false,
      updateShortcut: (key, value) =>
        set((state) => ({
          shortcuts: { ...state.shortcuts, [key]: value },
        })),
      resetToDefaults: () => set({ shortcuts: defaultShortcuts }),
      setIsEditing: (value) => set({ isEditing: value }),
      getShortcutLabel: (action) => shortcutLabels[action],
    }),
    {
      name: 'lianghua-shortcuts',
    }
  )
)

export { defaultShortcuts, shortcutLabels }
