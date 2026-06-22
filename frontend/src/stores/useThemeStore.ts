import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type ThemeMode = 'light' | 'dark' | 'system'

interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  /** 用于触发系统主题变化的响应式更新 */
  _systemDark: boolean
  _setSystemDark: (v: boolean) => void
}

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      mode: 'system',
      _systemDark: false,
      setMode: (mode) => set({ mode }),
      _setSystemDark: (v) => set({ _systemDark: v }),
    }),
    {
      name: 'lianghua-theme',
      // 不持久化内部状态
      partialize: (state) => ({ mode: state.mode }),
    }
  )
)

export function getEffectiveTheme(): 'light' | 'dark' {
  const { mode, _systemDark } = useThemeStore.getState()
  if (mode === 'system') {
    return _systemDark ? 'dark' : 'light'
  }
  return mode
}

// 模块级：监听 OS 主题变化，自动更新
if (typeof window !== 'undefined') {
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = (e: MediaQueryListEvent) => {
    useThemeStore.getState()._setSystemDark(e.matches)
  }
  // 初始化
  useThemeStore.getState()._setSystemDark(mq.matches)
  mq.addEventListener('change', handler)
}
