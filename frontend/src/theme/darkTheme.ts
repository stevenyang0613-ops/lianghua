/**
 * 深色主题配置
 */

import type { ThemeConfig } from 'antd'

export const darkTheme: ThemeConfig = {
  token: {
    colorPrimary: '#177ddc',
    colorSuccess: '#49aa19',
    colorWarning: '#d89614',
    colorError: '#a61d24',
    colorInfo: '#177ddc',
    colorBgBase: '#141414',
    colorTextBase: '#ffffff',
    colorBgContainer: '#1f1f1f',
    colorBgElevated: '#262626',
    colorBorder: '#434343',
    colorBorderSecondary: '#303030',
    colorText: 'rgba(255, 255, 255, 0.85)',
    colorTextSecondary: 'rgba(255, 255, 255, 0.65)',
    colorTextTertiary: 'rgba(255, 255, 255, 0.45)',
    colorTextQuaternary: 'rgba(255, 255, 255, 0.25)',
    colorFill: 'rgba(255, 255, 255, 0.08)',
    colorFillSecondary: 'rgba(255, 255, 255, 0.06)',
    colorFillTertiary: 'rgba(255, 255, 255, 0.04)',
    colorFillQuaternary: 'rgba(255, 255, 255, 0.02)',
  },
  components: {
    Menu: {
      darkItemBg: '#1f1f1f',
      darkItemSelectedBg: '#177ddc',
      darkItemHoverBg: 'rgba(255, 255, 255, 0.08)',
    },
    Table: {
      headerBg: '#1f1f1f',
      rowHoverBg: 'rgba(255, 255, 255, 0.04)',
    },
    Card: {
      colorBgContainer: '#1f1f1f',
    },
    Modal: {
      contentBg: '#1f1f1f',
      headerBg: '#1f1f1f',
    },
    Drawer: {
      colorBgElevated: '#1f1f1f',
    },
    Layout: {
      bodyBg: '#141414',
      headerBg: '#1f1f1f',
      siderBg: '#1f1f1f',
    },
    Input: {
      colorBgContainer: '#141414',
    },
    Select: {
      colorBgContainer: '#141414',
    },
  },
}

export const lightTheme: ThemeConfig = {
  token: {
    colorPrimary: '#1890ff',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#ff4d4f',
    colorInfo: '#1890ff',
    colorBgBase: '#ffffff',
    colorTextBase: '#000000',
  },
}

export default { darkTheme, lightTheme }
