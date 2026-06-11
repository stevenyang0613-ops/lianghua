/**
 * 国际化配置
 * i18n 框架，支持中英文切换
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import zhCN from './zh-CN'
import enUS from './en-US'

type Locale = 'zh-CN' | 'en-US'
type Messages = typeof zhCN

const messages: Record<Locale, Messages> = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

interface I18nState {
  locale: Locale
  messages: Messages
  setLocale: (locale: Locale) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

/**
 * 获取嵌套对象的值
 */
function getNestedValue(obj: Record<string, unknown>, path: string): string | undefined {
  const keys = path.split('.')
  let result: unknown = obj

  for (const key of keys) {
    if (result && typeof result === 'object' && key in result) {
      result = (result as Record<string, unknown>)[key]
    } else {
      return undefined
    }
  }

  return typeof result === 'string' ? result : undefined
}

/**
 * 替换模板参数
 */
function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template

  return template.replace(/\{(\w+)\}/g, (match, key) => {
    return params[key] !== undefined ? String(params[key]) : match
  })
}

/**
 * i18n Store
 */
export const useI18n = create<I18nState>()(
  persist(
    (set, get) => ({
      locale: 'zh-CN',
      messages: zhCN,

      setLocale: (locale) => {
        set({
          locale,
          messages: messages[locale],
        })
        // 更新 HTML lang 属性
        document.documentElement.lang = locale
      },

      t: (key, params) => {
        const { messages } = get()
        const template = getNestedValue(messages as unknown as Record<string, unknown>, key)

        if (template === undefined) {
          console.warn(`[i18n] Missing translation: ${key}`)
          return key
        }

        return interpolate(template, params)
      },
    }),
    {
      name: 'lianghua-locale',
      partialize: (state) => ({ locale: state.locale }),
    }
  )
)

/**
 * 翻译函数
 */
export function t(key: string, params?: Record<string, string | number>): string {
  return useI18n.getState().t(key, params)
}

/**
 * 获取当前语言
 */
export function getLocale(): Locale {
  return useI18n.getState().locale
}

/**
 * 设置语言
 */
export function setLocale(locale: Locale): void {
  useI18n.getState().setLocale(locale)
}

/**
 * 获取支持的语言列表
 */
export function getSupportedLocales(): Array<{ code: Locale; name: string }> {
  return [
    { code: 'zh-CN', name: '简体中文' },
    { code: 'en-US', name: 'English' },
  ]
}

/**
 * 检测浏览器语言
 */
export function detectBrowserLocale(): Locale {
  const browserLang = navigator.language || (navigator as any).userLanguage

  if (browserLang.startsWith('zh')) {
    return 'zh-CN'
  }

  return 'en-US'
}

/**
 * 初始化语言
 */
export function initLocale(): void {
  const savedLocale = useI18n.getState().locale

  if (!savedLocale) {
    const detectedLocale = detectBrowserLocale()
    useI18n.getState().setLocale(detectedLocale)
  } else {
    document.documentElement.lang = savedLocale
  }
}

export { zhCN, enUS }
export default useI18n
