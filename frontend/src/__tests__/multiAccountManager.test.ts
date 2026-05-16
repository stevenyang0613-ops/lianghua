/**
 * 多账户管理单元测试
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { multiAccountManager, type AccountConfig } from '../utils/multiAccountManager'

describe('MultiAccountManager', () => {
  beforeEach(() => {
    // 清空所有账户
    const accounts = multiAccountManager.getAllAccounts()
    accounts.forEach(acc => multiAccountManager.removeAccount(acc.id))
    localStorage.clear()
  })

  describe('Account Management', () => {
    it('should add account correctly', () => {
      const account = multiAccountManager.addAccount({
        name: 'Test Account',
        broker: 'eastmoney',
        account: '12345678',
        status: 'active',
        tags: ['test'],
      })

      expect(account.id).toBeDefined()
      expect(account.name).toBe('Test Account')
      expect(account.broker).toBe('eastmoney')
      expect(account.createdAt).toBeDefined()
    })

    it('should get account by id', () => {
      const created = multiAccountManager.addAccount({
        name: 'Test Account',
        broker: 'huatai',
        account: '87654321',
        status: 'active',
        tags: [],
      })

      const found = multiAccountManager.getAccount(created.id)
      expect(found).toEqual(created)
    })

    it('should update account', () => {
      const account = multiAccountManager.addAccount({
        name: 'Original Name',
        broker: 'cicc',
        account: '11111111',
        status: 'active',
        tags: [],
      })

      const updated = multiAccountManager.updateAccount(account.id, {
        name: 'Updated Name',
        status: 'inactive',
      })

      expect(updated?.name).toBe('Updated Name')
      expect(updated?.status).toBe('inactive')
    })

    it('should remove account', () => {
      const account = multiAccountManager.addAccount({
        name: 'To Remove',
        broker: 'guotaijunan',
        account: '22222222',
        status: 'active',
        tags: [],
      })

      const result = multiAccountManager.removeAccount(account.id)
      expect(result).toBe(true)
      expect(multiAccountManager.getAccount(account.id)).toBeUndefined()
    })

    it('should filter accounts by broker', () => {
      multiAccountManager.addAccount({
        name: 'Account 1',
        broker: 'eastmoney',
        account: '111',
        status: 'active',
        tags: [],
      })
      multiAccountManager.addAccount({
        name: 'Account 2',
        broker: 'huatai',
        account: '222',
        status: 'active',
        tags: [],
      })
      multiAccountManager.addAccount({
        name: 'Account 3',
        broker: 'eastmoney',
        account: '333',
        status: 'active',
        tags: [],
      })

      const eastmoneyAccounts = multiAccountManager.getAccountsByBroker('eastmoney')
      expect(eastmoneyAccounts.length).toBe(2)
    })

    it('should filter accounts by tag', () => {
      multiAccountManager.addAccount({
        name: 'Account 1',
        broker: 'eastmoney',
        account: '111',
        status: 'active',
        tags: ['production'],
      })
      multiAccountManager.addAccount({
        name: 'Account 2',
        broker: 'huatai',
        account: '222',
        status: 'active',
        tags: ['test'],
      })

      const prodAccounts = multiAccountManager.getAccountsByTag('production')
      expect(prodAccounts.length).toBe(1)
      expect(prodAccounts[0].name).toBe('Account 1')
    })
  })

  describe('Active Account', () => {
    it('should set and get active account', () => {
      const account = multiAccountManager.addAccount({
        name: 'Active Test',
        broker: 'zhongxin',
        account: '12345',
        status: 'active',
        tags: [],
      })

      multiAccountManager.setActiveAccount(account.id)
      expect(multiAccountManager.getActiveAccount()?.id).toBe(account.id)
    })
  })

  describe('Balance Management', () => {
    it('should update and get balance', () => {
      const account = multiAccountManager.addAccount({
        name: 'Balance Test',
        broker: 'eastmoney',
        account: '99999',
        status: 'active',
        tags: [],
      })

      multiAccountManager.updateBalance(account.id, {
        totalAsset: 100000,
        availableCash: 50000,
        marketValue: 40000,
        frozenCash: 10000,
        marginUsed: 0,
        marginAvailable: 50000,
        profitToday: 1000,
        profitTotal: 5000,
      })

      const balance = multiAccountManager.getBalance(account.id)
      expect(balance?.totalAsset).toBe(100000)
      expect(balance?.availableCash).toBe(50000)
    })

    it('should calculate total balance', () => {
      const account1 = multiAccountManager.addAccount({
        name: 'Account 1',
        broker: 'eastmoney',
        account: '111',
        status: 'active',
        tags: [],
      })
      const account2 = multiAccountManager.addAccount({
        name: 'Account 2',
        broker: 'huatai',
        account: '222',
        status: 'active',
        tags: [],
      })

      multiAccountManager.updateBalance(account1.id, {
        totalAsset: 100000,
        availableCash: 50000,
        marketValue: 40000,
        frozenCash: 10000,
        marginUsed: 0,
        marginAvailable: 50000,
        profitToday: 1000,
        profitTotal: 5000,
      })

      multiAccountManager.updateBalance(account2.id, {
        totalAsset: 200000,
        availableCash: 100000,
        marketValue: 80000,
        frozenCash: 20000,
        marginUsed: 0,
        marginAvailable: 100000,
        profitToday: 2000,
        profitTotal: 10000,
      })

      const total = multiAccountManager.getTotalBalance()
      expect(total.totalAsset).toBe(300000)
      expect(total.availableCash).toBe(150000)
      expect(total.profitToday).toBe(3000)
    })
  })

  describe('Account Groups', () => {
    it('should create group', () => {
      const account = multiAccountManager.addAccount({
        name: 'Group Test',
        broker: 'eastmoney',
        account: '111',
        status: 'active',
        tags: [],
      })

      const group = multiAccountManager.createGroup({
        name: 'Test Group',
        accountIds: [account.id],
        riskConfig: {
          maxPosition: 100000,
          maxSingleTrade: 10000,
          maxDailyLoss: 5000,
          maxDrawdown: 20,
        },
        allocationStrategy: 'equal',
      })

      expect(group.id).toBeDefined()
      expect(group.name).toBe('Test Group')
      expect(group.accountIds.length).toBe(1)
    })

    it('should check group risk', () => {
      const account = multiAccountManager.addAccount({
        name: 'Risk Test',
        broker: 'eastmoney',
        account: '111',
        status: 'active',
        tags: [],
      })

      const group = multiAccountManager.createGroup({
        name: 'Risk Group',
        accountIds: [account.id],
        riskConfig: {
          maxPosition: 100000,
          maxSingleTrade: 10000,
          maxDailyLoss: 5000,
          maxDrawdown: 20,
        },
        allocationStrategy: 'equal',
      })

      // 应该允许的交易
      const allowedTrade = multiAccountManager.checkGroupRisk(group.id, {
        symbol: '128001',
        amount: 1000,
        price: 10,
      })
      expect(allowedTrade.allowed).toBe(true)

      // 超过单笔限制的交易
      const blockedTrade = multiAccountManager.checkGroupRisk(group.id, {
        symbol: '128001',
        amount: 2000,
        price: 10,
      })
      expect(blockedTrade.allowed).toBe(false)
      expect(blockedTrade.reason).toContain('单笔交易限制')
    })
  })

  describe('Encryption', () => {
    it('should encrypt sensitive data when key is set', () => {
      multiAccountManager.setEncryptionKey('test-encryption-key')

      const account = multiAccountManager.addAccount({
        name: 'Encryption Test',
        broker: 'eastmoney',
        account: '111',
        apiKey: 'test-api-key',
        apiSecret: 'test-secret',
        tradingPassword: 'test-password',
        status: 'active',
        tags: [],
      })

      // 存储的应该是加密后的值
      expect(account.apiSecret).not.toBe('test-secret')
      expect(account.tradingPassword).not.toBe('test-password')
    })

    it('should decrypt data when retrieving', () => {
      multiAccountManager.setEncryptionKey('test-encryption-key')

      const account = multiAccountManager.addAccount({
        name: 'Decryption Test',
        broker: 'eastmoney',
        account: '111',
        apiSecret: 'my-secret',
        status: 'active',
        tags: [],
      })

      const decrypted = multiAccountManager.decrypt(account.apiSecret || '')
      expect(decrypted).toBe('my-secret')
    })
  })

  describe('Import/Export', () => {
    it('should export config without sensitive data', () => {
      multiAccountManager.addAccount({
        name: 'Export Test',
        broker: 'eastmoney',
        account: '111',
        apiKey: 'sensitive-key',
        apiSecret: 'sensitive-secret',
        status: 'active',
        tags: [],
      })

      const exported = multiAccountManager.exportConfig()
      const parsed = JSON.parse(exported)

      expect(parsed.accounts[0].apiKey).toBeUndefined()
      expect(parsed.accounts[0].apiSecret).toBeUndefined()
    })

    it('should import config correctly', () => {
      const config = JSON.stringify({
        accounts: [{
          id: 'imported-1',
          name: 'Imported Account',
          broker: 'eastmoney',
          account: '99999',
          status: 'active',
          tags: ['imported'],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        }],
        groups: [],
      })

      const result = multiAccountManager.importConfig(config)
      expect(result.success).toBe(1)
      expect(result.failed).toBe(0)

      const imported = multiAccountManager.getAccount('imported-1')
      expect(imported?.name).toBe('Imported Account')
    })
  })
})
