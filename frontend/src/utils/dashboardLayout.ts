/**
 * 仪表盘布局存储服务
 */

export interface DashboardWidget {
  id: string
  type: 'chart' | 'statistic' | 'table' | 'list' | 'custom' | 'market-summary' | 'top-dual-low' | 'forced-call-alert'
  title: string
  size: 'small' | 'medium' | 'large'
  x: number
  y: number
  w: number
  h: number
  config: Record<string, unknown>
  visible: boolean
}

export interface DashboardLayout {
  id: string
  name: string
  widgets: DashboardWidget[]
  columns: number
  rowHeight: number
  gap: number
  isDefault: boolean
  createdAt: number
  updatedAt: number
}

const LAYOUTS_KEY = 'dashboard_layouts'
const CURRENT_LAYOUT_KEY = 'current_dashboard_layout'

// 默认布局
const DEFAULT_LAYOUT: DashboardLayout = {
  id: 'default',
  name: '默认布局',
  columns: 12,
  rowHeight: 80,
  gap: 16,
  isDefault: true,
  createdAt: Date.now(),
  updatedAt: Date.now(),
  widgets: [
    {
      id: 'widget_1',
      type: 'statistic',
      title: '总资产',
      size: 'small',
      x: 0,
      y: 0,
      w: 3,
      h: 1,
      config: { field: 'totalAsset' },
      visible: true,
    },
    {
      id: 'widget_2',
      type: 'statistic',
      title: '今日盈亏',
      size: 'small',
      x: 3,
      y: 0,
      w: 3,
      h: 1,
      config: { field: 'todayProfit' },
      visible: true,
    },
    {
      id: 'widget_3',
      type: 'statistic',
      title: '持仓数量',
      size: 'small',
      x: 6,
      y: 0,
      w: 3,
      h: 1,
      config: { field: 'positionCount' },
      visible: true,
    },
    {
      id: 'widget_4',
      type: 'statistic',
      title: '预警数量',
      size: 'small',
      x: 9,
      y: 0,
      w: 3,
      h: 1,
      config: { field: 'alertCount' },
      visible: true,
    },
    {
      id: 'widget_5',
      type: 'chart',
      title: '收益曲线',
      size: 'large',
      x: 0,
      y: 1,
      w: 8,
      h: 3,
      config: { chartType: 'line', field: 'profitCurve' },
      visible: true,
    },
    {
      id: 'widget_6',
      type: 'list',
      title: '交易信号',
      size: 'medium',
      x: 8,
      y: 1,
      w: 4,
      h: 3,
      config: { maxItems: 5 },
      visible: true,
    },
    {
      id: 'widget_7',
      type: 'table',
      title: '持仓明细',
      size: 'large',
      x: 0,
      y: 4,
      w: 12,
      h: 4,
      config: {},
      visible: true,
    },
  ],
}

// 获取所有布局
export function getLayouts(): DashboardLayout[] {
  const saved = localStorage.getItem(LAYOUTS_KEY)
  if (saved) {
    try {
      const layouts = JSON.parse(saved)
      if (!Array.isArray(layouts)) throw new Error('not array')
      // 确保有默认布局
      if (!layouts.find((l: DashboardLayout) => l.isDefault)) {
        layouts.unshift(DEFAULT_LAYOUT)
      }
      return layouts
    } catch {
      // localStorage 数据损坏，重置为默认
      console.warn('[dashboardLayout] Corrupted layout data, resetting to default')
      localStorage.setItem(LAYOUTS_KEY, JSON.stringify([DEFAULT_LAYOUT]))
    }
  }
  return [DEFAULT_LAYOUT]
}

// 获取当前布局
export function getCurrentLayout(): DashboardLayout {
  const currentId = localStorage.getItem(CURRENT_LAYOUT_KEY)
  const layouts = getLayouts()
  return layouts.find(l => l.id === currentId) || layouts.find(l => l.isDefault) || layouts[0]
}

// 设置当前布局
export function setCurrentLayout(id: string): void {
  localStorage.setItem(CURRENT_LAYOUT_KEY, id)
}

// 创建新布局
export function createLayout(name: string): DashboardLayout {
  const layouts = getLayouts()
  const newLayout: DashboardLayout = {
    id: `layout_${Date.now()}`,
    name,
    widgets: [],
    columns: 12,
    rowHeight: 80,
    gap: 16,
    isDefault: false,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }
  layouts.push(newLayout)
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))
  return newLayout
}

// 更新布局
export function updateLayout(id: string, updates: Partial<DashboardLayout>): DashboardLayout | null {
  const layouts = getLayouts()
  const index = layouts.findIndex(l => l.id === id)
  if (index === -1) return null

  layouts[index] = {
    ...layouts[index],
    ...updates,
    updatedAt: Date.now(),
  }
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))
  return layouts[index]
}

// 删除布局
export function deleteLayout(id: string): boolean {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === id)
  if (!layout || layout.isDefault) return false

  const filtered = layouts.filter(l => l.id !== id)
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(filtered))

  // 如果删除的是当前布局，切换到默认布局
  if (getCurrentLayout().id === id) {
    setCurrentLayout('default')
  }

  return true
}

// 添加小组件
export function addWidget(layoutId: string, widget: Omit<DashboardWidget, 'id'>): DashboardWidget | null {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === layoutId)
  if (!layout) return null

  const newWidget: DashboardWidget = {
    ...widget,
    id: `widget_${Date.now()}`,
  }

  layout.widgets.push(newWidget)
  layout.updatedAt = Date.now()
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))

  return newWidget
}

// 更新小组件
export function updateWidget(layoutId: string, widgetId: string, updates: Partial<DashboardWidget>): DashboardWidget | null {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === layoutId)
  if (!layout) return null

  const index = layout.widgets.findIndex(w => w.id === widgetId)
  if (index === -1) return null

  layout.widgets[index] = { ...layout.widgets[index], ...updates }
  layout.updatedAt = Date.now()
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))

  return layout.widgets[index]
}

// 删除小组件
export function deleteWidget(layoutId: string, widgetId: string): boolean {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === layoutId)
  if (!layout) return false

  layout.widgets = layout.widgets.filter(w => w.id !== widgetId)
  layout.updatedAt = Date.now()
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))

  return true
}

// 更新小组件位置
export function updateWidgetPositions(layoutId: string, widgets: { id: string; x: number; y: number; w: number; h: number }[]): void {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === layoutId)
  if (!layout) return

  widgets.forEach(update => {
    const widget = layout.widgets.find(w => w.id === update.id)
    if (widget) {
      widget.x = update.x
      widget.y = update.y
      widget.w = update.w
      widget.h = update.h
    }
  })

  layout.updatedAt = Date.now()
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))
}

// 复制布局
export function duplicateLayout(id: string): DashboardLayout | null {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === id)
  if (!layout) return null

  const newLayout: DashboardLayout = {
    ...layout,
    id: `layout_${Date.now()}`,
    name: `${layout.name} (副本)`,
    isDefault: false,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    widgets: layout.widgets.map(w => ({
      ...w,
      id: `widget_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`,
    })),
  }

  layouts.push(newLayout)
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))

  return newLayout
}

// 导出布局
export function exportLayout(id: string): string {
  const layouts = getLayouts()
  const layout = layouts.find(l => l.id === id)
  if (!layout) return ''
  return JSON.stringify(layout, null, 2)
}

// 导入布局
export function importLayout(json: string): DashboardLayout | null {
  try {
    const layout = JSON.parse(json) as DashboardLayout
    layout.id = `layout_${Date.now()}`
    layout.isDefault = false
    layout.createdAt = Date.now()
    layout.updatedAt = Date.now()

    const layouts = getLayouts()
    layouts.push(layout)
    localStorage.setItem(LAYOUTS_KEY, JSON.stringify(layouts))

    return layout
  } catch {
    return null
  }
}

// 重置为默认布局
export function resetToDefault(): void {
  localStorage.setItem(LAYOUTS_KEY, JSON.stringify([DEFAULT_LAYOUT]))
  localStorage.removeItem(CURRENT_LAYOUT_KEY)
}

export default {
  getLayouts,
  getCurrentLayout,
  setCurrentLayout,
  createLayout,
  updateLayout,
  deleteLayout,
  addWidget,
  updateWidget,
  deleteWidget,
  updateWidgetPositions,
  duplicateLayout,
  exportLayout,
  importLayout,
  resetToDefault,
}
