/**
 * 插件系统
 * 支持插件的加载、卸载、启用、禁用
 */

export interface Plugin {
  id: string
  name: string
  version: string
  description: string
  author: string
  enabled: boolean
  installed: boolean
  hasUpdate: boolean
  latestVersion?: string
  icon?: string
  homepage?: string
  repository?: string
  permissions: string[]
  main: string
  createdAt: number
  updatedAt: number
}

export interface PluginManifest {
  id: string
  name: string
  version: string
  description: string
  author: string
  icon?: string
  homepage?: string
  repository?: string
  permissions: string[]
  main: string
  contributes?: {
    commands?: PluginCommand[]
    menus?: PluginMenu[]
    views?: PluginView[]
    settings?: PluginSetting[]
  }
}

export interface PluginCommand {
  id: string
  title: string
  category?: string
  icon?: string
  handler: () => void
}

export interface PluginMenu {
  id: string
  location: 'sidebar' | 'toolbar' | 'context' | 'statusbar'
  command: string
  when?: string
  group?: string
}

export interface PluginView {
  id: string
  title: string
  location: 'sidebar' | 'panel' | 'editor'
  when?: string
}

export interface PluginSetting {
  key: string
  type: 'string' | 'number' | 'boolean' | 'select'
  title: string
  description?: string
  default: unknown
  options?: { label: string; value: unknown }[]
}

interface PluginInstance {
  plugin: Plugin
  manifest: PluginManifest
  activate?: () => void
  deactivate?: () => void
  commands: Map<string, () => void>
}

const PLUGINS_KEY = 'lianghua_plugins'
const PLUGIN_SETTINGS_KEY = 'lianghua_plugin_settings'

// 内置插件列表（模拟市场）
const availablePlugins: Plugin[] = [
  {
    id: 'trading-calendar',
    name: '交易日历',
    version: '1.0.0',
    description: '显示交易日历，包括休市日、节假日信息',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: [],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: 'bond-compare',
    name: '转债对比',
    version: '1.2.0',
    description: '多只转债对比分析，支持自定义对比指标',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: ['data:read'],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: 'alert-notifier',
    name: '智能预警',
    version: '2.0.0',
    description: '高级预警功能，支持自定义预警条件和通知方式',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: ['notification', 'data:read'],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: 'portfolio-analysis',
    name: '组合分析',
    version: '1.5.0',
    description: '投资组合深度分析，包括相关性、风险收益分析',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: ['data:read'],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: 'shortcut-manager',
    name: '快捷键管理',
    version: '1.0.0',
    description: '自定义快捷键，提高操作效率',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: ['keyboard'],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
  {
    id: 'data-export',
    name: '数据导出',
    version: '1.3.0',
    description: '支持多种格式导出数据，包括 Excel、CSV、JSON',
    author: 'LiangHua',
    enabled: false,
    installed: false,
    hasUpdate: false,
    permissions: ['data:read', 'file:write'],
    main: 'index.js',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  },
]

class PluginManager {
  private plugins: Map<string, PluginInstance> = new Map()
  private installedPlugins: Plugin[] = []
  private settings: Record<string, Record<string, unknown>> = {}

  constructor() {
    this.loadInstalledPlugins()
    this.loadSettings()
  }

  // 获取可用插件列表（市场）
  getAvailablePlugins(): Plugin[] {
    return availablePlugins.map(p => {
      const installed = this.installedPlugins.find(i => i.id === p.id)
      return installed ? { ...p, ...installed, installed: true } : { ...p, installed: false }
    })
  }

  // 获取已安装插件
  getInstalledPlugins(): Plugin[] {
    return this.installedPlugins
  }

  // 安装插件
  async installPlugin(id: string): Promise<boolean> {
    const plugin = availablePlugins.find(p => p.id === id)
    if (!plugin) return false

    // 检查权限
    if (plugin.permissions.length > 0) {
      const granted = await this.requestPermissions(plugin.permissions)
      if (!granted) return false
    }

    const installedPlugin: Plugin = {
      ...plugin,
      installed: true,
      enabled: true,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }

    this.installedPlugins.push(installedPlugin)
    this.saveInstalledPlugins()

    // 激活插件
    this.activatePlugin(installedPlugin)

    return true
  }

  // 卸载插件
  uninstallPlugin(id: string): boolean {
    const index = this.installedPlugins.findIndex(p => p.id === id)
    if (index === -1) return false

    // 停用插件
    const plugin = this.installedPlugins[index]
    if (plugin.enabled) {
      this.deactivatePlugin(id)
    }

    this.installedPlugins.splice(index, 1)
    this.saveInstalledPlugins()

    // 删除设置
    delete this.settings[id]
    this.saveSettings()

    return true
  }

  // 启用插件
  enablePlugin(id: string): boolean {
    const plugin = this.installedPlugins.find(p => p.id === id)
    if (!plugin) return false

    plugin.enabled = true
    this.saveInstalledPlugins()

    this.activatePlugin(plugin)

    return true
  }

  // 禁用插件
  disablePlugin(id: string): boolean {
    const plugin = this.installedPlugins.find(p => p.id === id)
    if (!plugin || !plugin.enabled) return false

    plugin.enabled = false
    this.saveInstalledPlugins()

    this.deactivatePlugin(id)

    return true
  }

  // 更新插件
  async updatePlugin(id: string): Promise<boolean> {
    const plugin = this.installedPlugins.find(p => p.id === id)
    const available = availablePlugins.find(p => p.id === id)

    if (!plugin || !available) return false

    plugin.version = available.version
    plugin.hasUpdate = false
    plugin.updatedAt = Date.now()
    this.saveInstalledPlugins()

    return true
  }

  // 获取插件设置
  getPluginSettings(id: string): Record<string, unknown> {
    return this.settings[id] || {}
  }

  // 更新插件设置
  updatePluginSettings(id: string, settings: Record<string, unknown>): void {
    this.settings[id] = { ...this.settings[id], ...settings }
    this.saveSettings()
  }

  // 导出插件配置
  exportPluginConfig(id: string): string {
    const plugin = this.installedPlugins.find(p => p.id === id)
    const settings = this.settings[id]

    if (!plugin) return ''

    return JSON.stringify({ plugin, settings }, null, 2)
  }

  // 导入插件配置
  importPluginConfig(json: string): boolean {
    try {
      const { plugin, settings } = JSON.parse(json)
      const index = this.installedPlugins.findIndex(p => p.id === plugin.id)

      if (index !== -1) {
        this.installedPlugins[index] = plugin
        this.settings[plugin.id] = settings
        this.saveInstalledPlugins()
        this.saveSettings()
        return true
      }

      return false
    } catch {
      return false
    }
  }

  // 执行插件命令
  executeCommand(commandId: string): void {
    const [pluginId, cmdId] = commandId.split('.')
    const instance = this.plugins.get(pluginId)

    if (instance && instance.commands.has(cmdId)) {
      instance.commands.get(cmdId)?.()
    }
  }

  // 获取所有命令
  getAllCommands(): PluginCommand[] {
    const commands: PluginCommand[] = []

    this.plugins.forEach(instance => {
      instance.manifest.contributes?.commands?.forEach(cmd => {
        commands.push({
          ...cmd,
          id: `${instance.plugin.id}.${cmd.id}`,
        })
      })
    })

    return commands
  }

  // 私有方法
  private loadInstalledPlugins(): void {
    const saved = localStorage.getItem(PLUGINS_KEY)
    this.installedPlugins = saved ? JSON.parse(saved) : []
  }

  private saveInstalledPlugins(): void {
    localStorage.setItem(PLUGINS_KEY, JSON.stringify(this.installedPlugins))
  }

  private loadSettings(): void {
    const saved = localStorage.getItem(PLUGIN_SETTINGS_KEY)
    this.settings = saved ? JSON.parse(saved) : {}
  }

  private saveSettings(): void {
    localStorage.setItem(PLUGIN_SETTINGS_KEY, JSON.stringify(this.settings))
  }

  private async requestPermissions(permissions: string[]): Promise<boolean> {
    // 实际应用中应该弹出权限请求对话框
    console.log('请求权限:', permissions)
    return true
  }

  private activatePlugin(plugin: Plugin): void {
    // 创建插件实例
    const instance: PluginInstance = {
      plugin,
      manifest: {
        id: plugin.id,
        name: plugin.name,
        version: plugin.version,
        description: plugin.description,
        author: plugin.author,
        permissions: plugin.permissions,
        main: plugin.main,
      },
      commands: new Map(),
    }

    this.plugins.set(plugin.id, instance)

    // 执行激活逻辑
    console.log(`插件 ${plugin.name} 已激活`)
  }

  private deactivatePlugin(id: string): void {
    const instance = this.plugins.get(id)
    if (instance) {
      // 执行停用逻辑
      console.log(`插件 ${instance.plugin.name} 已停用`)
      this.plugins.delete(id)
    }
  }
}

// 单例
export const pluginManager = new PluginManager()

// 导出便捷方法
export const getAvailablePlugins = () => pluginManager.getAvailablePlugins()
export const getInstalledPlugins = () => pluginManager.getInstalledPlugins()
export const installPlugin = (id: string) => pluginManager.installPlugin(id)
export const uninstallPlugin = (id: string) => pluginManager.uninstallPlugin(id)
export const enablePlugin = (id: string) => pluginManager.enablePlugin(id)
export const disablePlugin = (id: string) => pluginManager.disablePlugin(id)
export const updatePlugin = (id: string) => pluginManager.updatePlugin(id)
export const getPluginSettings = (id: string) => pluginManager.getPluginSettings(id)
export const updatePluginSettings = (id: string, settings: Record<string, unknown>) => pluginManager.updatePluginSettings(id, settings)

export default pluginManager
