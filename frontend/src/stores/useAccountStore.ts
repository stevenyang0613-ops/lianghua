/**
 * 多账户状态管理
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { secureSave, secureLoad, secureRemove } from '../utils/secureStorage'
import { message } from 'antd'

export interface BrokerAccount {
  id: string
  name: string
  broker: string
  type: 'real' | 'simulate'
  accountId: string
  balance: number
  available: number
  frozen: number
  marketValue: number
  totalProfit: number
  todayProfit: number
  positions: Position[]
  createdAt: number
  lastSync: number | null
  status: 'active' | 'inactive' | 'error'
  apiKey?: string
  apiSecret?: string
}

export interface Position {
  code: string
  name: string
  volume: number
  available: number
  costPrice: number
  currentPrice: number
  marketValue: number
  profit: number
  profitPct: number
}

interface AccountState {
  accounts: BrokerAccount[]
  currentAccountId: string | null
  isLoading: boolean
  error: string | null

  // Actions
  addAccount: (account: Omit<BrokerAccount, 'id' | 'createdAt' | 'lastSync' | 'status'>) => void
  removeAccount: (id: string) => void
  updateAccount: (id: string, updates: Partial<BrokerAccount>) => void
  setCurrentAccount: (id: string | null) => void
  syncAccount: (id: string) => Promise<void>
  syncAllAccounts: () => Promise<void>
  clearError: () => void
  loadSecureFields: () => Promise<void>
}

const generateId = () => `acc_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

export const useAccountStore = create<AccountState>()(
  persist(
    (set, get) => ({
      accounts: [],
      currentAccountId: null,
      isLoading: false,
      error: null,

      addAccount: (account) => {
        const id = generateId()
        // 将 apiKey/apiSecret 从明文状态中移出，存入加密存储
        const { apiKey, apiSecret, ...safeAccount } = account

        const newAccount: BrokerAccount = {
          ...safeAccount,
          id,
          createdAt: Date.now(),
          lastSync: null,
          status: 'active',
        }

        // 异步保存加密字段
        const securePromises: Promise<void>[] = []
        if (apiKey) securePromises.push(secureSave(`broker_${id}_apiKey`, apiKey))
        if (apiSecret) securePromises.push(secureSave(`broker_${id}_apiSecret`, apiSecret))
        if (securePromises.length > 0) {
          Promise.all(securePromises).catch(() => {/* 加密存储失败静默处理 */})
        }

        set((state) => ({
          accounts: [...state.accounts, newAccount],
          currentAccountId: state.currentAccountId || newAccount.id,
        }))
      },

      removeAccount: (id) => {
        // 清除该账户的加密存储密钥
        Promise.all([
          secureRemove(`broker_${id}_apiKey`),
          secureRemove(`broker_${id}_apiSecret`),
        ]).catch(() => {/* 静默处理 */})

        set((state) => {
          const newAccounts = state.accounts.filter((a) => a.id !== id)
          return {
            accounts: newAccounts,
            currentAccountId: state.currentAccountId === id ? (newAccounts[0]?.id || null) : state.currentAccountId,
          }
        })
      },

      updateAccount: (id, updates) => {
        // 将 apiKey/apiSecret 存入加密存储，不留在 Zustand 状态中
        const secureKeys: (keyof BrokerAccount)[] = ['apiKey', 'apiSecret']
        const secureUpdates: Record<string, string> = {}
        const safeUpdates: Partial<BrokerAccount> = {}

        for (const [key, value] of Object.entries(updates)) {
          if (secureKeys.includes(key as keyof BrokerAccount) && typeof value === 'string') {
            secureUpdates[key] = value
          } else {
            (safeUpdates as Record<string, unknown>)[key] = value
          }
        }

        // 异步保存加密字段
        if (Object.keys(secureUpdates).length > 0) {
          Promise.all(
            Object.entries(secureUpdates).map(([key, value]) =>
              secureSave(`broker_${id}_${key}`, value)
            )
          ).catch(() => {/* 加密存储失败静默处理 */})
        }

        set((state) => ({
          accounts: state.accounts.map((a) =>
            a.id === id ? { ...a, ...safeUpdates, lastSync: Date.now() } : a
          ),
        }))
      },

      setCurrentAccount: (id) => {
        set({ currentAccountId: id })
      },

      syncAccount: async (id) => {
        set({ isLoading: true, error: null })
        try {
          if (!window.electronAPI?.httpRequest) {
            message.warning('账户同步需要连接真实交易接口，当前无可用接口')
            set({ isLoading: false })
            return
          }

          const account = get().accounts.find((a) => a.id === id)
          if (!account) throw new Error('账户不存在')

          set((state) => ({
            accounts: state.accounts.map((a) =>
              a.id === id ? { ...a, lastSync: Date.now(), status: 'active' } : a
            ),
            isLoading: false,
          }))
        } catch (err) {
          set({
            error: String(err),
            isLoading: false,
          })
        }
      },

      syncAllAccounts: async () => {
        const { accounts, syncAccount } = get()
        set({ isLoading: true })
        for (const account of accounts) {
          await syncAccount(account.id)
        }
        set({ isLoading: false })
      },

      clearError: () => set({ error: null }),

      loadSecureFields: async () => {
        const { accounts } = get()
        const updatedAccounts = await Promise.all(
          accounts.map(async (account) => {
            const [apiKey, apiSecret] = await Promise.all([
              secureLoad(`broker_${account.id}_apiKey`),
              secureLoad(`broker_${account.id}_apiSecret`),
            ])
            return {
              ...account,
              ...(apiKey ? { apiKey } : {}),
              ...(apiSecret ? { apiSecret } : {}),
            }
          })
        )
        set({ accounts: updatedAccounts })
      },
    }),
    {
      name: 'broker-accounts',
      version: 1,
      partialize: (state) => ({
        accounts: state.accounts.map(({ apiKey, apiSecret, ...rest }) => rest),
        currentAccountId: state.currentAccountId,
      }),
      migrate: (persistedState: unknown, _version: number) => {
        if (persistedState && typeof persistedState === 'object') {
          const s = persistedState as { accounts?: unknown; currentAccountId?: unknown }
          if (Array.isArray(s.accounts)) {
            return {
              accounts: s.accounts.filter((a: unknown) => a && typeof a === 'object' && 'id' in (a as object)),
              currentAccountId: typeof s.currentAccountId === 'string' ? s.currentAccountId : null,
            }
          }
        }
        return persistedState as { accounts: []; currentAccountId: null }
      },
    }
  )
)

// 券商列表
export const BROKERS = [
  { value: 'ht', label: '华泰证券' },
  { value: 'gtja', label: '国泰君安' },
  { value: 'cicc', label: '中金公司' },
  { value: 'xyzq', label: '兴业证券' },
  { value: 'gf', label: '广发证券' },
  { value: 'ms', label: '民生证券' },
  { value: 'simulate', label: '模拟账户' },
]

// 获取当前账户
export function getCurrentAccount(): BrokerAccount | null {
  const state = useAccountStore.getState()
  return state.accounts.find((a) => a.id === state.currentAccountId) || null
}

// 获取所有活跃账户
export function getActiveAccounts(): BrokerAccount[] {
  return useAccountStore.getState().accounts.filter((a) => a.status === 'active')
}

// 计算总资产
export function getTotalAssets(): number {
  return useAccountStore.getState().accounts.reduce((sum, a) => sum + a.balance + a.marketValue, 0)
}

export default useAccountStore
