/**
 * 插件热加载系统
 * 支持运行时动态加载和卸载插件
 */

import type { Plugin, PluginCommand } from './pluginSystem'

export interface HotPlugin extends Plugin {
  status: 'unloaded' | 'loading' | 'loaded' | 'error'
  error?: string
  module?: unknown
  loadedAt?: number
}

export interface PluginLifecycle {
  activate?: (context: PluginContext) => void | Promise<void>
  deactivate?: () => void | Promise<void>
  commands?: PluginCommand[]
}

export interface PluginContext {
  pluginId: string
  subscriptions: Array<() => void>
  registerCommand: (command: PluginCommand) => void
  registerView: (view: { id: string; component: React.ComponentType }) => void
  showNotification: (message: string, type?: 'info' | 'success' | 'warning' | 'error') => void
  getSetting: <T>(key: string, defaultValue: T) => T
  setSetting: (key: string, value: unknown) => void
}

type PluginEventListener = (event: string, plugin: HotPlugin) => void

class HotPluginLoader {
  private plugins: Map<string, HotPlugin> = new Map()
  private lifecycles: Map<string, PluginLifecycle> = new Map()
  private contexts: Map<string, PluginContext> = new Map()
  private listeners: Set<PluginEventListener> = new Set()
  private commandRegistry: Map<string, PluginCommand> = new Map()
  private viewRegistry: Map<string, React.ComponentType> = new Map()

  // 注册插件
  registerPlugin(plugin: Plugin): void {
    const hotPlugin: HotPlugin = {
      ...plugin,
      status: 'unloaded',
    }
    this.plugins.set(plugin.id, hotPlugin)
    this.emit('registered', hotPlugin)
  }

  // 加载插件
  async loadPlugin(id: string): Promise<boolean> {
    const plugin = this.plugins.get(id)
    if (!plugin || plugin.status === 'loaded') return false

    plugin.status = 'loading'
    plugin.error = undefined
    this.emit('loading', plugin)

    try {
      // 创建插件上下文
      const context = this.createContext(plugin)
      this.contexts.set(id, context)

      // 模拟加载插件模块（实际应用中从文件系统或网络加载）
      const lifecycle = await this.loadPluginModule(plugin)
      this.lifecycles.set(id, lifecycle)

      // 执行激活函数
      if (lifecycle.activate) {
        await lifecycle.activate(context)
      }

      // 注册命令
      if (lifecycle.commands) {
        lifecycle.commands.forEach(cmd => {
          this.commandRegistry.set(`${id}.${cmd.id}`, cmd)
        })
      }

      plugin.status = 'loaded'
      plugin.loadedAt = Date.now()
      this.emit('loaded', plugin)

      return true
    } catch (error) {
      plugin.status = 'error'
      plugin.error = String(error)
      this.emit('error', plugin)
      return false
    }
  }

  // 卸载插件
  async unloadPlugin(id: string): Promise<boolean> {
    const plugin = this.plugins.get(id)
    if (!plugin || plugin.status !== 'loaded') return false

    try {
      const lifecycle = this.lifecycles.get(id)
      const context = this.contexts.get(id)

      // 执行停用函数
      if (lifecycle?.deactivate) {
        await lifecycle.deactivate()
      }

      // 清理订阅
      if (context) {
        context.subscriptions.forEach(unsub => unsub())
      }

      // 移除命令
      for (const [key] of this.commandRegistry) {
        if (key.startsWith(`${id}.`)) {
          this.commandRegistry.delete(key)
        }
      }

      // 移除视图
      for (const [key] of this.viewRegistry) {
        if (key.startsWith(`${id}.`)) {
          this.viewRegistry.delete(key)
        }
      }

      this.lifecycles.delete(id)
      this.contexts.delete(id)

      plugin.status = 'unloaded'
      plugin.module = undefined
      plugin.loadedAt = undefined
      this.emit('unloaded', plugin)

      return true
    } catch (error) {
      plugin.status = 'error'
      plugin.error = String(error)
      this.emit('error', plugin)
      return false
    }
  }

  // 重新加载插件
  async reloadPlugin(id: string): Promise<boolean> {
    const plugin = this.plugins.get(id)
    if (!plugin) return false

    if (plugin.status === 'loaded') {
      const unloaded = await this.unloadPlugin(id)
      if (!unloaded) return false
    }

    return this.loadPlugin(id)
  }

  // 获取插件状态
  getPlugin(id: string): HotPlugin | undefined {
    return this.plugins.get(id)
  }

  // 获取所有插件
  getAllPlugins(): HotPlugin[] {
    return Array.from(this.plugins.values())
  }

  // 执行命令
  executeCommand(commandId: string, ...args: unknown[]): void {
    const command = this.commandRegistry.get(commandId)
    if (command?.handler) {
      (command.handler as (...a: unknown[]) => void)(...args)
    }
  }

  // 获取所有命令
  getAllCommands(): Array<PluginCommand & { pluginId: string }> {
    return Array.from(this.commandRegistry.entries()).map(([key, cmd]) => ({
      ...cmd,
      pluginId: key.split('.')[0],
    }))
  }

  // 获取视图
  getView(viewId: string): React.ComponentType | undefined {
    return this.viewRegistry.get(viewId)
  }

  // 监听事件
  on(_event: string, listener: PluginEventListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  // 创建插件上下文
  private createContext(plugin: HotPlugin): PluginContext {
    const subscriptions: Array<() => void> = []

    return {
      pluginId: plugin.id,
      subscriptions,
      registerCommand: (command: PluginCommand) => {
        this.commandRegistry.set(`${plugin.id}.${command.id}`, command)
      },
      registerView: (view: { id: string; component: React.ComponentType }) => {
        this.viewRegistry.set(`${plugin.id}.${view.id}`, view.component)
      },
      showNotification: (message: string, type = 'info') => {
        console.log(`[${plugin.name}] ${type}: ${message}`)
      },
      getSetting: <T,>(key: string, defaultValue: T): T => {
        const settings = JSON.parse(localStorage.getItem(`plugin_settings_${plugin.id}`) || '{}')
        return settings[key] ?? defaultValue
      },
      setSetting: (key: string, value: unknown) => {
        const settings = JSON.parse(localStorage.getItem(`plugin_settings_${plugin.id}`) || '{}')
        settings[key] = value
        localStorage.setItem(`plugin_settings_${plugin.id}`, JSON.stringify(settings))
      },
    }
  }

  // 模拟加载插件模块
  private async loadPluginModule(plugin: HotPlugin): Promise<PluginLifecycle> {
    // 模拟网络延迟
    await new Promise(resolve => setTimeout(resolve, 100))

    // 返回模拟的生命周期
    return {
      activate: () => {
        console.log(`[HotLoader] 插件 ${plugin.name} 已激活`)
      },
      deactivate: () => {
        console.log(`[HotLoader] 插件 ${plugin.name} 已停用`)
      },
      commands: [
        {
          id: 'main',
          title: plugin.name,
          handler: () => console.log(`执行 ${plugin.name} 主命令`),
        },
      ],
    }
  }

  // 触发事件
  private emit(event: string, plugin: HotPlugin): void {
    this.listeners.forEach(listener => listener(event, plugin))
  }
}

// 单例
export const hotPluginLoader = new HotPluginLoader()

// 导出便捷方法
export const registerPlugin = (plugin: Plugin) => hotPluginLoader.registerPlugin(plugin)
export const loadPlugin = (id: string) => hotPluginLoader.loadPlugin(id)
export const unloadPlugin = (id: string) => hotPluginLoader.unloadPlugin(id)
export const reloadPlugin = (id: string) => hotPluginLoader.reloadPlugin(id)
export const getPlugin = (id: string) => hotPluginLoader.getPlugin(id)
export const getAllPlugins = () => hotPluginLoader.getAllPlugins()
export const executeCommand = (id: string, ...args: unknown[]) => hotPluginLoader.executeCommand(id, ...args)
export const getAllCommands = () => hotPluginLoader.getAllCommands()

export default hotPluginLoader
