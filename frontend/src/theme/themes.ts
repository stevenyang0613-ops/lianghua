/**
 * 主题系统
 * 支持多种预设主题和自定义主题
 */

export interface ThemeColors {
  primary: string
  success: string
  warning: string
  error: string
  info: string
  background: string
  backgroundSecondary: string
  text: string
  textSecondary: string
  border: string
  card: string
  cardHover: string
  chartColors: string[]
}

export interface Theme {
  id: string
  name: string
  description: string
  author: string
  version: string
  colors: ThemeColors
  isDark: boolean
  isBuiltIn: boolean
  preview?: string
}

// 预设主题
export const builtInThemes: Theme[] = [
  {
    id: 'light',
    name: '默认浅色',
    description: '清爽明亮的默认浅色主题',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: false,
    isBuiltIn: true,
    colors: {
      primary: '#1890ff',
      success: '#52c41a',
      warning: '#faad14',
      error: '#ff4d4f',
      info: '#1890ff',
      background: '#f0f2f5',
      backgroundSecondary: '#ffffff',
      text: '#000000d9',
      textSecondary: '#00000073',
      border: '#d9d9d9',
      card: '#ffffff',
      cardHover: '#fafafa',
      chartColors: ['#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16'],
    },
  },
  {
    id: 'dark',
    name: '暗黑模式',
    description: '护眼暗黑主题，适合夜间使用',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: true,
    isBuiltIn: true,
    colors: {
      primary: '#177ddc',
      success: '#49aa19',
      warning: '#d89614',
      error: '#a61d24',
      info: '#177ddc',
      background: '#141414',
      backgroundSecondary: '#1f1f1f',
      text: '#ffffffd9',
      textSecondary: '#ffffff73',
      border: '#434343',
      card: '#1f1f1f',
      cardHover: '#2a2a2a',
      chartColors: ['#177ddc', '#49aa19', '#d89614', '#a61d24', '#642ab5', '#13a8a8', '#d4237e', '#d87a16'],
    },
  },
  {
    id: 'compact',
    name: '紧凑模式',
    description: '紧凑布局，适合小屏幕设备',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: false,
    isBuiltIn: true,
    colors: {
      primary: '#1890ff',
      success: '#52c41a',
      warning: '#faad14',
      error: '#ff4d4f',
      info: '#1890ff',
      background: '#f5f5f5',
      backgroundSecondary: '#fafafa',
      text: '#000000d9',
      textSecondary: '#00000073',
      border: '#e8e8e8',
      card: '#ffffff',
      cardHover: '#fafafa',
      chartColors: ['#1890ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2'],
    },
  },
  {
    id: 'finance',
    name: '金融专业',
    description: '专业金融配色，红涨绿跌',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: true,
    isBuiltIn: true,
    colors: {
      primary: '#0066cc',
      success: '#ef5350', // 红涨
      warning: '#ffa726',
      error: '#26a69a', // 绿跌
      info: '#0066cc',
      background: '#0d1117',
      backgroundSecondary: '#161b22',
      text: '#c9d1d9',
      textSecondary: '#8b949e',
      border: '#30363d',
      card: '#161b22',
      cardHover: '#21262d',
      chartColors: ['#0066cc', '#ef5350', '#26a69a', '#ffa726', '#a371f7', '#58a6ff'],
    },
  },
  {
    id: 'ocean',
    name: '海洋蓝',
    description: '清新海洋蓝色主题',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: false,
    isBuiltIn: true,
    colors: {
      primary: '#00bcd4',
      success: '#4caf50',
      warning: '#ff9800',
      error: '#f44336',
      info: '#2196f3',
      background: '#e3f2fd',
      backgroundSecondary: '#ffffff',
      text: '#0d47a1',
      textSecondary: '#1976d2',
      border: '#90caf9',
      card: '#ffffff',
      cardHover: '#e1f5fe',
      chartColors: ['#00bcd4', '#2196f3', '#4caf50', '#ff9800', '#9c27b0', '#009688'],
    },
  },
  {
    id: 'forest',
    name: '森林绿',
    description: '自然森林绿色主题',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: true,
    isBuiltIn: true,
    colors: {
      primary: '#4caf50',
      success: '#8bc34a',
      warning: '#ffeb3b',
      error: '#f44336',
      info: '#00bcd4',
      background: '#1b2e1b',
      backgroundSecondary: '#2d4a2d',
      text: '#c8e6c9',
      textSecondary: '#81c784',
      border: '#4caf50',
      card: '#2d4a2d',
      cardHover: '#3d6a3d',
      chartColors: ['#4caf50', '#8bc34a', '#00bcd4', '#ffeb3b', '#ff9800', '#9c27b0'],
    },
  },
  {
    id: 'sunset',
    name: '日落橙',
    description: '温暖日落橙色主题',
    author: 'LiangHua',
    version: '1.0.0',
    isDark: false,
    isBuiltIn: true,
    colors: {
      primary: '#ff6f00',
      success: '#66bb6a',
      warning: '#ffa726',
      error: '#ef5350',
      info: '#42a5f5',
      background: '#fff3e0',
      backgroundSecondary: '#ffffff',
      text: '#4e342e',
      textSecondary: '#795548',
      border: '#ffcc80',
      card: '#ffffff',
      cardHover: '#fff8e1',
      chartColors: ['#ff6f00', '#ffa726', '#66bb6a', '#42a5f5', '#ab47bc', '#26a69a'],
    },
  },
]

const THEME_STORAGE_KEY = 'lianghua_theme'
const CUSTOM_THEMES_KEY = 'lianghua_custom_themes'

// 获取当前主题
export function getCurrentTheme(): Theme {
  const savedId = localStorage.getItem(THEME_STORAGE_KEY)
  const allThemes = getAllThemes()
  return allThemes.find(t => t.id === savedId) || builtInThemes[0]
}

// 设置当前主题
export function setCurrentTheme(id: string): void {
  const theme = getAllThemes().find(t => t.id === id)
  if (!theme) return

  localStorage.setItem(THEME_STORAGE_KEY, id)
  applyTheme(theme)
}

// 应用主题
export function applyTheme(theme: Theme): void {
  const root = document.documentElement

  // 设置暗色模式标记
  if (theme.isDark) {
    root.setAttribute('data-theme', 'dark')
  } else {
    root.removeAttribute('data-theme')
  }

  // 设置 CSS 变量
  Object.entries(theme.colors).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((color, index) => {
        root.style.setProperty(`--${key}-${index + 1}`, color)
      })
    } else {
      // 转换驼峰命名为 kebab-case
      const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase()
      root.style.setProperty(`--${cssKey}`, value)
    }
  })

  // 设置 Ant Design 主题
  root.style.setProperty('--ant-primary-color', theme.colors.primary)
  root.style.setProperty('--ant-success-color', theme.colors.success)
  root.style.setProperty('--ant-warning-color', theme.colors.warning)
  root.style.setProperty('--ant-error-color', theme.colors.error)
  root.style.setProperty('--ant-info-color', theme.colors.info)
}

// 获取所有主题
export function getAllThemes(): Theme[] {
  const customThemes = getCustomThemes()
  return [...builtInThemes, ...customThemes]
}

// 获取自定义主题
export function getCustomThemes(): Theme[] {
  const saved = localStorage.getItem(CUSTOM_THEMES_KEY)
  try {
    return saved ? JSON.parse(saved) : []
  } catch {
    console.warn('[themes] Corrupted custom themes data, resetting')
    return []
  }
}

// 添加自定义主题
export function addCustomTheme(theme: Omit<Theme, 'id' | 'isBuiltIn'>): Theme {
  const customThemes = getCustomThemes()
  const newTheme: Theme = {
    ...theme,
    id: `custom_${Date.now()}`,
    isBuiltIn: false,
  }

  customThemes.push(newTheme)
  localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(customThemes))

  return newTheme
}

// 更新自定义主题
export function updateCustomTheme(id: string, updates: Partial<Theme>): Theme | null {
  const customThemes = getCustomThemes()
  const index = customThemes.findIndex(t => t.id === id)
  if (index === -1) return null

  customThemes[index] = { ...customThemes[index], ...updates }
  localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(customThemes))

  return customThemes[index]
}

// 删除自定义主题
export function deleteCustomTheme(id: string): boolean {
  const customThemes = getCustomThemes()
  const filtered = customThemes.filter(t => t.id !== id)

  if (filtered.length === customThemes.length) return false

  localStorage.setItem(CUSTOM_THEMES_KEY, JSON.stringify(filtered))
  return true
}

// 导出主题
export function exportTheme(id: string): string {
  const theme = getAllThemes().find(t => t.id === id)
  if (!theme) return ''
  return JSON.stringify(theme, null, 2)
}

// 导入主题
export function importTheme(json: string): Theme | null {
  try {
    const theme = JSON.parse(json) as Theme
    const { isBuiltIn: _isBuiltIn, ...rest } = theme
    return addCustomTheme(rest)
  } catch {
    return null
  }
}

// 重置主题
export function resetTheme(): void {
  setCurrentTheme('light')
}

// 动态加载主题 - 只加载需要的主题数据
const themeCache: Map<string, Theme> = new Map()

// 动态加载单个主题（用于减少初始包大小）
export async function loadThemeAsync(id: string): Promise<Theme | null> {
  // 检查缓存
  if (themeCache.has(id)) {
    return themeCache.get(id)!
  }

  // 先从本地存储查找
  const allThemes = getAllThemes()
  const theme = allThemes.find(t => t.id === id)
  if (theme) {
    themeCache.set(id, theme)
    return theme
  }

  // 模拟从远程加载主题（实际应用中可以从 CDN 加载）
  try {
    // 模拟网络延迟
    await new Promise(resolve => setTimeout(resolve, 100))

    // 返回默认主题
    const defaultTheme = builtInThemes[0]
    themeCache.set(id, defaultTheme)
    return defaultTheme
  } catch {
    return null
  }
}

// 预加载主题（提前加载可能使用的主题）
export function preloadThemes(ids: string[]): void {
  ids.forEach(id => {
    void loadThemeAsync(id)
  })
}

// 获取主题列表（轻量级，只返回基本信息）
export interface ThemeInfo {
  id: string
  name: string
  isDark: boolean
  isBuiltIn: boolean
}

export function getThemeList(): ThemeInfo[] {
  const allThemes = getAllThemes()
  return allThemes.map(t => ({
    id: t.id,
    name: t.name,
    isDark: t.isDark,
    isBuiltIn: t.isBuiltIn,
  }))
}

// 切换主题（带动画效果）
export function switchTheme(id: string, animate = true): void {
  const theme = getAllThemes().find(t => t.id === id)
  if (!theme) return

  if (animate) {
    // 添加淡出效果
    document.documentElement.style.transition = 'background-color 0.3s ease'
  }

  setCurrentTheme(id)

  if (animate) {
    // 移除过渡效果
    setTimeout(() => {
      document.documentElement.style.transition = ''
    }, 300)
  }
}

// 导出当前主题 CSS 变量
export function exportThemeCSS(theme?: Theme): string {
  const t = theme || getCurrentTheme()
  const cssVars = Object.entries(t.colors)
    .filter(([_, value]) => !Array.isArray(value))
    .map(([key, value]) => {
      const cssKey = key.replace(/([A-Z])/g, '-$1').toLowerCase()
      return `  --${cssKey}: ${value};`
    })
    .join('\n')

  return `:root {\n${cssVars}\n}`
}

export default {
  builtInThemes,
  getCurrentTheme,
  setCurrentTheme,
  applyTheme,
  getAllThemes,
  getCustomThemes,
  addCustomTheme,
  updateCustomTheme,
  deleteCustomTheme,
  exportTheme,
  importTheme,
  resetTheme,
}
