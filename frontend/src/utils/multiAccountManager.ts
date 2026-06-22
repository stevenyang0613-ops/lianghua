/**
 * 多账户管理工具
 * 支持多券商账户、账户组、统一风控
 */

import { z } from 'zod'

// 账户类型
export type BrokerType = 'eastmoney' | 'huatai' | 'cicc' | 'guotaijunan' | 'zhongxin' | 'custom'
export type AccountStatus = 'active' | 'inactive' | 'error' | 'maintenance'

// 账户配置 Schema
export const AccountConfigSchema = z.object({
  id: z.string(),
  name: z.string().min(1, '账户名称不能为空'),
  broker: z.enum(['eastmoney', 'huatai', 'cicc', 'guotaijunan', 'zhongxin', 'custom']),
  brokerName: z.string().optional(),
  account: z.string().min(1, '账户号不能为空'),
  apiKey: z.string().optional(),
  apiSecret: z.string().optional(),
  apiHost: z.string().optional(),
  tradingPassword: z.string().optional(),
  status: z.enum(['active', 'inactive', 'error', 'maintenance']),
  tags: z.array(z.string()),
  group: z.string().optional(),
  riskConfig: z.object({
    maxPosition: z.number().min(0),
    maxSingleTrade: z.number().min(0),
    maxDailyLoss: z.number().min(0),
    maxDrawdown: z.number().min(0).max(100),
    allowedSymbols: z.array(z.string()).optional(),
    blockedSymbols: z.array(z.string()).optional(),
  }).optional(),
  createdAt: z.number(),
  updatedAt: z.number(),
  lastSyncAt: z.number().optional(),
})

export type AccountConfig = z.infer<typeof AccountConfigSchema>

// 账户资金信息
export interface AccountBalance {
  accountId: string
  totalAsset: number        // 总资产
  availableCash: number     // 可用资金
  marketValue: number       // 持仓市值
  frozenCash: number        // 冻结资金
  marginUsed: number        // 已用保证金
  marginAvailable: number   // 可用保证金
  profitToday: number       // 当日盈亏
  profitTotal: number       // 累计盈亏
  updatedAt: number
}

// 账户持仓
export interface AccountPosition {
  accountId: string
  symbol: string
  name: string
  quantity: number
  availableQuantity: number
  costPrice: number
  currentPrice: number
  marketValue: number
  profit: number
  profitPercent: number
  updatedAt: number
}

// 账户组配置
export interface AccountGroup {
  id: string
  name: string
  description?: string
  accountIds: string[]
  riskConfig: AccountConfig['riskConfig']
  allocationStrategy: 'equal' | 'weighted' | 'custom'
  weights?: Record<string, number>
  createdAt: number
  updatedAt: number
}

/**
 * 多账户管理器
 */
export class MultiAccountManager {
  private accounts: Map<string, AccountConfig> = new Map()
  private balances: Map<string, AccountBalance> = new Map()
  private positions: Map<string, AccountPosition[]> = new Map()
  private groups: Map<string, AccountGroup> = new Map()
  private activeAccountId: string | null = null
  private encryptionKey: string | null = null

  /**
   * 设置加密密钥
   */
  setEncryptionKey(key: string): void {
    this.encryptionKey = key
  }

  /**
   * 添加账户
   */
  addAccount(config: Omit<AccountConfig, 'id' | 'createdAt' | 'updatedAt'>): AccountConfig {
    const id = this.generateId()
    const now = Date.now()

    const account: AccountConfig = {
      ...config,
      id,
      createdAt: now,
      updatedAt: now,
      status: config.status || 'active',
      tags: config.tags || [],
    }

    // 加密敏感信息
    if (this.encryptionKey) {
      account.apiSecret = this.encrypt(account.apiSecret || '')
      account.tradingPassword = this.encrypt(account.tradingPassword || '')
    }

    this.accounts.set(id, account)
    this.saveToStorage()

    return account
  }

  /**
   * 更新账户
   */
  updateAccount(id: string, updates: Partial<AccountConfig>): AccountConfig | null {
    const account = this.accounts.get(id)
    if (!account) return null

    const updated: AccountConfig = {
      ...account,
      ...updates,
      id: account.id,
      createdAt: account.createdAt,
      updatedAt: Date.now(),
    }

    // 加密敏感信息
    if (this.encryptionKey && updates.apiSecret) {
      updated.apiSecret = this.encrypt(updates.apiSecret)
    }
    if (this.encryptionKey && updates.tradingPassword) {
      updated.tradingPassword = this.encrypt(updates.tradingPassword)
    }

    this.accounts.set(id, updated)
    this.saveToStorage()

    return updated
  }

  /**
   * 删除账户
   */
  removeAccount(id: string): boolean {
    const result = this.accounts.delete(id)
    this.balances.delete(id)
    this.positions.delete(id)

    // 从所有组中移除
    for (const [, group] of this.groups) {
      const index = group.accountIds.indexOf(id)
      if (index !== -1) {
        group.accountIds.splice(index, 1)
        if (group.weights) {
          delete group.weights[id]
        }
      }
    }

    if (result) {
      this.saveToStorage()
    }

    return result
  }

  /**
   * 获取账户
   */
  getAccount(id: string): AccountConfig | undefined {
    return this.accounts.get(id)
  }

  /**
   * 获取所有账户
   */
  getAllAccounts(): AccountConfig[] {
    return Array.from(this.accounts.values())
  }

  /**
   * 获取活跃账户
   */
  getActiveAccounts(): AccountConfig[] {
    return this.getAllAccounts().filter(a => a.status === 'active')
  }

  /**
   * 设置当前活跃账户
   */
  setActiveAccount(id: string): void {
    if (this.accounts.has(id)) {
      this.activeAccountId = id
      localStorage.setItem('activeAccountId', id)
    }
  }

  /**
   * 获取当前活跃账户
   */
  getActiveAccount(): AccountConfig | null {
    if (this.activeAccountId) {
      return this.accounts.get(this.activeAccountId) || null
    }
    return null
  }

  /**
   * 按标签筛选账户
   */
  getAccountsByTag(tag: string): AccountConfig[] {
    return this.getAllAccounts().filter(a => a.tags.includes(tag))
  }

  /**
   * 按券商筛选账户
   */
  getAccountsByBroker(broker: BrokerType): AccountConfig[] {
    return this.getAllAccounts().filter(a => a.broker === broker)
  }

  /**
   * 更新账户资金
   */
  updateBalance(accountId: string, balance: Omit<AccountBalance, 'accountId' | 'updatedAt'>): void {
    this.balances.set(accountId, {
      ...balance,
      accountId,
      updatedAt: Date.now(),
    })
  }

  /**
   * 获取账户资金
   */
  getBalance(accountId: string): AccountBalance | undefined {
    return this.balances.get(accountId)
  }

  /**
   * 获取所有账户资金汇总
   */
  getTotalBalance(): { totalAsset: number; availableCash: number; marketValue: number; profitToday: number } {
    let totalAsset = 0
    let availableCash = 0
    let marketValue = 0
    let profitToday = 0

    for (const balance of this.balances.values()) {
      totalAsset += balance.totalAsset
      availableCash += balance.availableCash
      marketValue += balance.marketValue
      profitToday += balance.profitToday
    }

    return { totalAsset, availableCash, marketValue, profitToday }
  }

  /**
   * 更新账户持仓
   */
  updatePositions(accountId: string, positions: Omit<AccountPosition, 'accountId' | 'updatedAt'>[]): void {
    this.positions.set(accountId, positions.map(p => ({
      ...p,
      accountId,
      updatedAt: Date.now(),
    })))
  }

  /**
   * 获取账户持仓
   */
  getPositions(accountId: string): AccountPosition[] {
    return this.positions.get(accountId) || []
  }

  /**
   * 创建账户组
   */
  createGroup(config: Omit<AccountGroup, 'id' | 'createdAt' | 'updatedAt'>): AccountGroup {
    const id = this.generateId()
    const now = Date.now()

    const group: AccountGroup = {
      ...config,
      id,
      createdAt: now,
      updatedAt: now,
    }

    this.groups.set(id, group)
    this.saveToStorage()

    return group
  }

  /**
   * 获取账户组
   */
  getGroup(id: string): AccountGroup | undefined {
    return this.groups.get(id)
  }

  /**
   * 获取账户所属的组
   */
  getGroupsForAccount(accountId: string): AccountGroup[] {
    return Array.from(this.groups.values()).filter(g => g.accountIds.includes(accountId))
  }

  /**
   * 账户组风控检查
   */
  checkGroupRisk(groupId: string, trade: { symbol: string; amount: number; price: number }): {
    allowed: boolean
    reason?: string
  } {
    const group = this.groups.get(groupId)
    if (!group) {
      return { allowed: false, reason: '账户组不存在' }
    }

    const config = group.riskConfig
    if (!config) return { allowed: true }

    // 检查最大持仓
    if (config.maxPosition > 0) {
      const totalValue = this.calculateGroupPositionValue(groupId)
      if (totalValue + trade.amount * trade.price > config.maxPosition) {
        return { allowed: false, reason: '超过最大持仓限制' }
      }
    }

    // 检查单笔交易限制
    if (config.maxSingleTrade > 0) {
      if (trade.amount * trade.price > config.maxSingleTrade) {
        return { allowed: false, reason: '超过单笔交易限制' }
      }
    }

    // 检查允许交易的标的
    if (config.allowedSymbols && config.allowedSymbols.length > 0) {
      if (!config.allowedSymbols.includes(trade.symbol)) {
        return { allowed: false, reason: '该标的不在允许交易列表中' }
      }
    }

    // 检查禁止交易的标的
    if (config.blockedSymbols && config.blockedSymbols.length > 0) {
      if (config.blockedSymbols.includes(trade.symbol)) {
        return { allowed: false, reason: '该标的在禁止交易列表中' }
      }
    }

    // 检查当日亏损限制
    if (config.maxDailyLoss > 0) {
      const todayLoss = this.calculateGroupTodayLoss(groupId)
      if (todayLoss < -config.maxDailyLoss) {
        return { allowed: false, reason: '超过当日亏损限制' }
      }
    }

    return { allowed: true }
  }

  /**
   * 计算账户组持仓市值
   */
  private calculateGroupPositionValue(groupId: string): number {
    const group = this.groups.get(groupId)
    if (!group) return 0

    let total = 0
    for (const accountId of group.accountIds) {
      const balance = this.balances.get(accountId)
      if (balance) {
        total += balance.marketValue
      }
    }

    return total
  }

  /**
   * 计算账户组当日亏损
   */
  private calculateGroupTodayLoss(groupId: string): number {
    const group = this.groups.get(groupId)
    if (!group) return 0

    let total = 0
    for (const accountId of group.accountIds) {
      const balance = this.balances.get(accountId)
      if (balance) {
        total += balance.profitToday
      }
    }

    return total
  }

  /**
   * 按权重分配交易量
   */
  allocateTradeByWeight(groupId: string, totalAmount: number): Map<string, number> {
    const group = this.groups.get(groupId)
    if (!group) return new Map()

    const allocations = new Map<string, number>()

    if (group.allocationStrategy === 'equal') {
      const perAccount = Math.floor(totalAmount / group.accountIds.length)
      group.accountIds.forEach(id => allocations.set(id, perAccount))
    } else if (group.allocationStrategy === 'weighted' && group.weights) {
      const totalWeight = Object.values(group.weights).reduce((sum, w) => sum + w, 0)
      for (const accountId of group.accountIds) {
        const weight = group.weights[accountId] || 0
        allocations.set(accountId, Math.floor(totalAmount * (weight / totalWeight)))
      }
    } else {
      // custom - 需要手动分配
      group.accountIds.forEach(id => allocations.set(id, 0))
    }

    return allocations
  }

  /**
   * 加密
   */
  private encrypt(text: string): string {
    if (!this.encryptionKey || !text) return text
    // 简单的 XOR 加密（生产环境应使用 AES）
    const key = this.encryptionKey
    let result = ''
    for (let i = 0; i < text.length; i++) {
      result += String.fromCharCode(text.charCodeAt(i) ^ key.charCodeAt(i % key.length))
    }
    return btoa(result)
  }

  /**
   * 解密
   */
  decrypt(encrypted: string): string {
    if (!this.encryptionKey || !encrypted) return encrypted
    try {
      const text = atob(encrypted)
      const key = this.encryptionKey
      let result = ''
      for (let i = 0; i < text.length; i++) {
        result += String.fromCharCode(text.charCodeAt(i) ^ key.charCodeAt(i % key.length))
      }
      return result
    } catch {
      return encrypted
    }
  }

  /**
   * 生成 ID
   */
  private generateId(): string {
    return `acc_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  /**
   * 保存到存储
   */
  private saveToStorage(): void {
    const data = {
      accounts: Array.from(this.accounts.entries()),
      groups: Array.from(this.groups.entries()),
    }
    localStorage.setItem('multiAccountData', JSON.stringify(data))
  }

  /**
   * 从存储加载
   */
  loadFromStorage(): void {
    try {
      const data = JSON.parse(localStorage.getItem('multiAccountData') || '{}')

      if (data.accounts) {
        this.accounts = new Map(data.accounts)
      }

      if (data.groups) {
        this.groups = new Map(data.groups)
      }

      // 恢复活跃账户
      this.activeAccountId = localStorage.getItem('activeAccountId')
    } catch (error) {
      console.error('[MultiAccount] Failed to load from storage:', error)
    }
  }

  /**
   * 导出账户配置（不包含敏感信息）
   */
  exportConfig(): string {
    const accounts = this.getAllAccounts().map(a => ({
      ...a,
      apiKey: undefined,
      apiSecret: undefined,
      tradingPassword: undefined,
    }))

    return JSON.stringify({ accounts, groups: Array.from(this.groups.values()) }, null, 2)
  }

  /**
   * 导入账户配置
   */
  importConfig(config: string): { success: number; failed: number } {
    try {
      const data = JSON.parse(config)
      let success = 0
      let failed = 0

      if (data.accounts) {
        for (const account of data.accounts) {
          try {
            AccountConfigSchema.parse(account)
            this.accounts.set(account.id, account)
            success++
          } catch {
            failed++
          }
        }
      }

      if (data.groups) {
        for (const group of data.groups) {
          this.groups.set(group.id, group)
        }
      }

      this.saveToStorage()

      return { success, failed }
    } catch (error) {
      console.error('[MultiAccount] Import failed:', error)
      return { success: 0, failed: 0 }
    }
  }
}

// 导出单例
export const multiAccountManager = new MultiAccountManager()

// 初始化
multiAccountManager.loadFromStorage()

export default multiAccountManager
