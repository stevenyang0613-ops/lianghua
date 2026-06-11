import { useEffect, type ReactNode } from 'react'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useThemeStore, getEffectiveTheme } from '../stores/useThemeStore'

interface ThemeProviderProps {
  children: ReactNode
}

export default function ThemeProvider({ children }: ThemeProviderProps) {
  const mode = useThemeStore((s) => s.mode)

  useEffect(() => {
    const effectiveTheme = getEffectiveTheme()
    document.documentElement.setAttribute('data-theme', effectiveTheme)
    document.body.style.colorScheme = effectiveTheme
  }, [mode])

  const isDark = getEffectiveTheme() === 'dark'

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1890ff',
          borderRadius: 6,
        },
        components: {
          Table: {
            headerBg: isDark ? '#1f1f1f' : '#fafafa',
          },
        },
      }}
    >
      {children}
    </ConfigProvider>
  )
}
