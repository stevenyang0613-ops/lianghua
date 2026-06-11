/**
 * 自定义主题配置 Store
 * 支持主题色、字体大小、布局模式等自定义
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark' | 'auto'
export type LayoutMode = 'side' | 'top' | 'mix'
export type FontSize = 'small' | 'default' | 'large'

export interface ThemeColors {
  primary: string
  success: string
  warning: string
  error: string
  info: string
}

export interface ThemeConfig {
  mode: ThemeMode
  layout: LayoutMode
  fontSize: FontSize
  colors: ThemeColors
  compactMode: boolean
  animationsEnabled: boolean
  borderRadius: number
  sidebarCollapsed: boolean
  sidebarWidth: number
  headerHeight: number
  showBreadcrumb: boolean
  showFooter: boolean
}

interface ThemeState extends ThemeConfig {
  // Actions
  setMode: (mode: ThemeMode) => void
  setLayout: (layout: LayoutMode) => void
  setFontSize: (size: FontSize) => void
  setPrimaryColor: (color: string) => void
  setColors: (colors: Partial<ThemeColors>) => void
  toggleCompactMode: () => void
  toggleAnimations: () => void
  setBorderRadius: (radius: number) => void
  toggleSidebar: () => void
  setSidebarWidth: (width: number) => void
  setHeaderHeight: (height: number) => void
  toggleBreadcrumb: () => void
  toggleFooter: () => void
  resetTheme: () => void
  exportTheme: () => string
  importTheme: (json: string) => boolean
}

const defaultTheme: ThemeConfig = {
  mode: 'auto',
  layout: 'side',
  fontSize: 'default',
  colors: {
    primary: '#1890ff',
    success: '#52c41a',
    warning: '#faad14',
    error: '#ff4d4f',
    info: '#1890ff',
  },
  compactMode: false,
  animationsEnabled: true,
  borderRadius: 6,
  sidebarCollapsed: false,
  sidebarWidth: 220,
  headerHeight: 64,
  showBreadcrumb: true,
  showFooter: false,
}

// 预设主题
export const presetThemes: Record<string, Partial<ThemeConfig>> = {
  default: defaultTheme,
  ocean: {
    colors: { primary: '#0052cc', success: '#00875a', warning: '#ff991f', error: '#de350b', info: '#0065ff' },
  },
  sunset: {
    colors: { primary: '#fa8c16', success: '#52c41a', warning: '#fadb14', error: '#f5222d', info: '#fa541c' },
  },
  forest: {
    colors: { primary: '#52c41a', success: '#73d13d', warning: '#faad14', error: '#ff4d4f', info: '#13c2c2' },
  },
  purple: {
    colors: { primary: '#722ed1', success: '#52c41a', warning: '#faad14', error: '#ff4d4f', info: '#2f54eb' },
  },
  midnight: {
    mode: 'dark',
    colors: { primary: '#177ddc', success: '#49aa19', warning: '#d89614', error: '#a61d24', info: '#177ddc' },
  },
  compact: {
    compactMode: true,
    fontSize: 'small',
    borderRadius: 4,
  },
}

export const useThemeConfigStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      ...defaultTheme,

      setMode: (mode) => set({ mode }),

      setLayout: (layout) => set({ layout }),

      setFontSize: (fontSize) => set({ fontSize }),

      setPrimaryColor: (color) =>
        set((state) => ({
          colors: { ...state.colors, primary: color },
        })),

      setColors: (colors) =>
        set((state) => ({
          colors: { ...state.colors, ...colors },
        })),

      toggleCompactMode: () =>
        set((state) => ({ compactMode: !state.compactMode })),

      toggleAnimations: () =>
        set((state) => ({ animationsEnabled: !state.animationsEnabled })),

      setBorderRadius: (borderRadius) => set({ borderRadius }),

      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setSidebarWidth: (sidebarWidth) => set({ sidebarWidth }),

      setHeaderHeight: (headerHeight) => set({ headerHeight }),

      toggleBreadcrumb: () =>
        set((state) => ({ showBreadcrumb: !state.showBreadcrumb })),

      toggleFooter: () =>
        set((state) => ({ showFooter: !state.showFooter })),

      resetTheme: () => set(defaultTheme),

      exportTheme: () => {
        const state = get()
        const config: ThemeConfig = {
          mode: state.mode,
          layout: state.layout,
          fontSize: state.fontSize,
          colors: state.colors,
          compactMode: state.compactMode,
          animationsEnabled: state.animationsEnabled,
          borderRadius: state.borderRadius,
          sidebarCollapsed: state.sidebarCollapsed,
          sidebarWidth: state.sidebarWidth,
          headerHeight: state.headerHeight,
          showBreadcrumb: state.showBreadcrumb,
          showFooter: state.showFooter,
        }
        return JSON.stringify(config, null, 2)
      },

      importTheme: (json) => {
        try {
          const config = JSON.parse(json) as Partial<ThemeConfig>
          set({ ...defaultTheme, ...config })
          return true
        } catch {
          return false
        }
      },
    }),
    {
      name: 'lianghua-theme-config',
      version: 1,
      migrate: (persistedState: unknown, _version: number) => {
        if (persistedState && typeof persistedState === 'object') {
          return { ...defaultTheme, ...(persistedState as object) }
        }
        return defaultTheme
      },
    }
  )
)

// 应用主题到 DOM
export function applyThemeToDOM(config: ThemeConfig) {
  const root = document.documentElement

  // 应用主题模式
  const isDark =
    config.mode === 'dark' ||
    (config.mode === 'auto' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches)

  root.setAttribute('data-theme', isDark ? 'dark' : 'light')

  // 应用 CSS 变量 (兼容两套命名:主题系统 + useThemeConfigStore)
  root.style.setProperty('--primary-color', config.colors.primary)
  root.style.setProperty('--success-color', config.colors.success)
  root.style.setProperty('--warning-color', config.colors.warning)
  root.style.setProperty('--error-color', config.colors.error)
  root.style.setProperty('--info-color', config.colors.info)
  root.style.setProperty('--border-radius-base', `${config.borderRadius}px`)
  // Ant Design 命名(与 themes.ts applyTheme 对齐)
  root.style.setProperty('--ant-primary-color', config.colors.primary)
  root.style.setProperty('--ant-success-color', config.colors.success)
  root.style.setProperty('--ant-warning-color', config.colors.warning)
  root.style.setProperty('--ant-error-color', config.colors.error)
  root.style.setProperty('--ant-info-color', config.colors.info)

  // 应用字体大小
  const fontSizes = { small: '13px', default: '14px', large: '16px' }
  root.style.setProperty('--font-size-base', fontSizes[config.fontSize])

  // 应用紧凑模式
  if (config.compactMode) {
    root.classList.add('compact-mode')
  } else {
    root.classList.remove('compact-mode')
  }

  // 应用动画开关
  if (!config.animationsEnabled) {
    root.classList.add('no-animations')
  } else {
    root.classList.remove('no-animations')
  }
}

// 监听系统主题变化
export function watchSystemTheme(callback: (isDark: boolean) => void) {
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

  const handler = (e: MediaQueryListEvent) => {
    callback(e.matches)
  }

  mediaQuery.addEventListener('change', handler)
  return () => mediaQuery.removeEventListener('change', handler)
}

// 初始化主题
export function initTheme() {
  const config = useThemeConfigStore.getState()
  applyThemeToDOM(config)

  // 监听系统主题变化
  if (config.mode === 'auto') {
    watchSystemTheme((isDark) => {
      document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light')
    })
  }
}

export default useThemeConfigStore
