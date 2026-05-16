/**
 * 键盘快捷键系统
 * 全局快捷键管理，支持组合键、冲突检测
 */

import { useEffect } from 'react'

type KeyHandler = (event: KeyboardEvent) => void

interface HotkeyDefinition {
  id: string
  keys: string[]
  handler: KeyHandler
  description?: string
  scope?: string
  preventDefault?: boolean
  stopPropagation?: boolean
  enabled?: () => boolean
}

interface HotkeyConflict {
  existingId: string
  newId: string
  keys: string[]
}

class HotkeyManager {
  private hotkeys: Map<string, HotkeyDefinition> = new Map()
  private enabled: boolean = true
  private currentScope: string = 'global'

  constructor() {
    this.setupListener()
  }

  /**
   * 设置键盘监听
   */
  private setupListener(): void {
    document.addEventListener('keydown', this.handleKeyDown.bind(this))
  }

  /**
   * 处理键盘事件
   */
  private handleKeyDown(event: KeyboardEvent): void {
    if (!this.enabled) return

    // 忽略输入框内的快捷键（除非明确允许）
    const target = event.target as HTMLElement
    const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable

    // 构建按键字符串
    const pressedKeys = this.getPressedKeys(event)
    const pressedKey = pressedKeys.join('+')

    // 查找匹配的快捷键
    for (const [, definition] of this.hotkeys) {
      // 检查作用域
      if (definition.scope && definition.scope !== this.currentScope && definition.scope !== 'global') {
        continue
      }

      // 检查是否启用
      if (definition.enabled && !definition.enabled()) {
        continue
      }

      // 检查按键匹配
      const definitionKey = definition.keys.join('+')
      if (definitionKey.toLowerCase() === pressedKey.toLowerCase()) {
        // 输入框内的快捷键需要特殊处理
        if (isInput && !definition.id.startsWith('input-')) {
          continue
        }

        if (definition.preventDefault !== false) {
          event.preventDefault()
        }
        if (definition.stopPropagation) {
          event.stopPropagation()
        }

        definition.handler(event)
        return
      }
    }
  }

  /**
   * 获取按下的键
   */
  private getPressedKeys(event: KeyboardEvent): string[] {
    const keys: string[] = []

    if (event.ctrlKey) keys.push('Ctrl')
    if (event.altKey) keys.push('Alt')
    if (event.shiftKey) keys.push('Shift')
    if (event.metaKey) keys.push('Meta')

    // 主键
    let key = event.key
    // 标准化特殊键名称
    const keyMap: Record<string, string> = {
      ' ': 'Space',
      'Escape': 'Esc',
      'ArrowUp': 'Up',
      'ArrowDown': 'Down',
      'ArrowLeft': 'Left',
      'ArrowRight': 'Right',
      'Delete': 'Del',
    }
    key = keyMap[key] || key

    if (key.length === 1) {
      key = key.toUpperCase()
    }

    keys.push(key)

    return keys
  }

  /**
   * 注册快捷键
   */
  register(definition: HotkeyDefinition): HotkeyConflict | null {
    // 检查冲突
    const conflict = this.checkConflict(definition)
    if (conflict) {
      console.warn(`[Hotkeys] Conflict detected: ${conflict.existingId} vs ${conflict.newId}`, conflict.keys)
      return conflict
    }

    this.hotkeys.set(definition.id, definition)
    return null
  }

  /**
   * 批量注册
   */
  registerAll(definitions: HotkeyDefinition[]): HotkeyConflict[] {
    const conflicts: HotkeyConflict[] = []

    for (const definition of definitions) {
      const conflict = this.register(definition)
      if (conflict) {
        conflicts.push(conflict)
      }
    }

    return conflicts
  }

  /**
   * 检查冲突
   */
  private checkConflict(definition: HotkeyDefinition): HotkeyConflict | null {
    const newKey = definition.keys.join('+').toLowerCase()

    for (const [id, existing] of this.hotkeys) {
      const existingKey = existing.keys.join('+').toLowerCase()
      if (existingKey === newKey) {
        return {
          existingId: id,
          newId: definition.id,
          keys: definition.keys,
        }
      }
    }

    return null
  }

  /**
   * 注销快捷键
   */
  unregister(id: string): boolean {
    return this.hotkeys.delete(id)
  }

  /**
   * 注销所有快捷键
   */
  clear(): void {
    this.hotkeys.clear()
  }

  /**
   * 启用/禁用
   */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled
  }

  /**
   * 设置当前作用域
   */
  setScope(scope: string): void {
    this.currentScope = scope
  }

  /**
   * 获取所有快捷键
   */
  getAll(): HotkeyDefinition[] {
    return Array.from(this.hotkeys.values())
  }

  /**
   * 按作用域获取快捷键
   */
  getByScope(scope: string): HotkeyDefinition[] {
    return this.getAll().filter(h => h.scope === scope || !h.scope)
  }

  /**
   * 导出快捷键配置
   */
  export(): string {
    const config = this.getAll().map(h => ({
      id: h.id,
      keys: h.keys,
      description: h.description,
    }))
    return JSON.stringify(config, null, 2)
  }
}

// 导出单例
export const hotkeyManager = new HotkeyManager()

/**
 * 默认快捷键配置
 */
export const defaultHotkeys: HotkeyDefinition[] = [
  {
    id: 'nav-market',
    keys: ['Ctrl', '1'],
    handler: () => { window.location.hash = '#/market' },
    description: '跳转到市场',
    scope: 'global',
  },
  {
    id: 'nav-watchlist',
    keys: ['Ctrl', '2'],
    handler: () => { window.location.hash = '#/watchlist' },
    description: '跳转到自选',
    scope: 'global',
  },
  {
    id: 'nav-backtest',
    keys: ['Ctrl', '3'],
    handler: () => { window.location.hash = '#/backtest' },
    description: '跳转到回测',
    scope: 'global',
  },
  {
    id: 'nav-trade',
    keys: ['Ctrl', '4'],
    handler: () => { window.location.hash = '#/trade' },
    description: '跳转到交易',
    scope: 'global',
  },
  {
    id: 'nav-signals',
    keys: ['Ctrl', '5'],
    handler: () => { window.location.hash = '#/signals' },
    description: '跳转到信号',
    scope: 'global',
  },
  {
    id: 'search',
    keys: ['Ctrl', 'K'],
    handler: () => {
      const event = new CustomEvent('open-search')
      window.dispatchEvent(event)
    },
    description: '打开搜索',
    scope: 'global',
  },
  {
    id: 'refresh',
    keys: ['Ctrl', 'R'],
    handler: () => {
      const event = new CustomEvent('refresh-data')
      window.dispatchEvent(event)
    },
    description: '刷新数据',
    scope: 'global',
    preventDefault: true,
  },
  {
    id: 'fullscreen',
    keys: ['F11'],
    handler: () => {
      if (document.fullscreenElement) {
        document.exitFullscreen()
      } else {
        document.documentElement.requestFullscreen()
      }
    },
    description: '全屏切换',
    scope: 'global',
    preventDefault: true,
  },
  {
    id: 'escape',
    keys: ['Esc'],
    handler: () => {
      const event = new CustomEvent('close-modal')
      window.dispatchEvent(event)
    },
    description: '关闭弹窗',
    scope: 'global',
  },
  {
    id: 'input-select-all',
    keys: ['Ctrl', 'A'],
    handler: (e) => {
      const target = e.target as HTMLInputElement
      target.select()
    },
    description: '全选',
    scope: 'input',
    preventDefault: true,
  },
]

/**
 * 初始化快捷键
 */
export function initHotkeys(): void {
  hotkeyManager.registerAll(defaultHotkeys)
}

/**
 * React Hook: 使用快捷键
 */
export function useHotkey(
  id: string,
  keys: string[],
  handler: KeyHandler,
  options?: {
    description?: string
    scope?: string
    enabled?: () => boolean
  }
): void {
  useEffect(() => {
    const definition: HotkeyDefinition = {
      id,
      keys,
      handler,
      description: options?.description,
      scope: options?.scope,
      enabled: options?.enabled,
    }

    hotkeyManager.register(definition)

    return () => {
      hotkeyManager.unregister(id)
    }
  }, [id, keys, handler, options])
}

export default hotkeyManager
