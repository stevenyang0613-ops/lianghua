/**
 * 策略分享社区工具
 * 支持策略发布、订阅、评分、讨论
 */

import { z } from 'zod'

// 策略类型
export type StrategyType = 'trend' | 'meanReversion' | 'arbitrage' | 'marketMaking' | 'custom'
export type StrategyStatus = 'draft' | 'published' | 'archived' | 'deprecated'
export type StrategyVisibility = 'public' | 'private' | 'paid'

// 策略定义
export interface StrategyDefinition {
  id: string
  name: string
  description: string
  type: StrategyType
  tags: string[]
  author: {
    id: string
    name: string
    avatar?: string
  }
  version: string
  status: StrategyStatus
  visibility: StrategyVisibility
  price: number        // 付费策略价格
  code: string         // 策略代码（加密存储）
  config: Record<string, unknown>
  backtestResult?: {
    totalReturn: number
    annualizedReturn: number
    maxDrawdown: number
    sharpeRatio: number
    winRate: number
    profitFactor: number
    tradesCount: number
    period: string
  }
  stats: {
    views: number
    likes: number
    subscribers: number
    forks: number
    comments: number
  }
  ratings: {
    average: number
    count: number
    distribution: Record<1 | 2 | 3 | 4 | 5, number>
  }
  createdAt: number
  updatedAt: number
  publishedAt?: number
}

// 用户订阅
export interface StrategySubscription {
  id: string
  strategyId: string
  userId: string
  status: 'active' | 'paused' | 'cancelled'
  subscribedAt: number
  expiresAt?: number
  settings: {
    autoSync: boolean
    notifications: boolean
    realTrading: boolean
    accounts: string[]
  }
}

// 评论
export interface StrategyComment {
  id: string
  strategyId: string
  userId: string
  userName: string
  userAvatar?: string
  content: string
  parentId?: string    // 回复的评论ID
  likes: number
  likedBy: string[]
  createdAt: number
  updatedAt?: number
}

// 讨论
export interface StrategyDiscussion {
  id: string
  strategyId: string
  title: string
  content: string
  author: {
    id: string
    name: string
    avatar?: string
  }
  tags: string[]
  replies: number
  views: number
  lastReplyAt: number
  createdAt: number
}

// 策略市场搜索参数
export interface StrategySearchParams {
  query?: string
  type?: StrategyType
  tags?: string[]
  sortBy?: 'popularity' | 'rating' | 'return' | 'sharpe' | 'newest' | 'trending'
  priceRange?: { min: number; max: number }
  visibility?: StrategyVisibility[]
  page?: number
  pageSize?: number
}

/**
 * 策略分享服务
 */
export class StrategySharingService {
  private strategies: Map<string, StrategyDefinition> = new Map()
  private subscriptions: Map<string, StrategySubscription[]> = new Map()
  private comments: Map<string, StrategyComment[]> = new Map()
  private discussions: Map<string, StrategyDiscussion[]> = new Map()
  private userLikes: Set<string> = new Set()  // 用户点赞的策略ID
  private apiEndpoint: string = '/api/community'

  /**
   * 设置 API 端点
   */
  setApiEndpoint(endpoint: string): void {
    this.apiEndpoint = endpoint
  }

  /**
   * 发布策略
   */
  async publishStrategy(strategy: Omit<StrategyDefinition, 'id' | 'createdAt' | 'updatedAt' | 'publishedAt' | 'stats' | 'ratings'>): Promise<StrategyDefinition> {
    const id = this.generateId()
    const now = Date.now()

    const newStrategy: StrategyDefinition = {
      ...strategy,
      id,
      status: 'published',
      stats: {
        views: 0,
        likes: 0,
        subscribers: 0,
        forks: 0,
        comments: 0,
      },
      ratings: {
        average: 0,
        count: 0,
        distribution: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 },
      },
      createdAt: now,
      updatedAt: now,
      publishedAt: now,
    }

    this.strategies.set(id, newStrategy)
    await this.syncToServer('create', newStrategy)

    return newStrategy
  }

  /**
   * 更新策略
   */
  async updateStrategy(id: string, updates: Partial<StrategyDefinition>): Promise<StrategyDefinition | null> {
    const strategy = this.strategies.get(id)
    if (!strategy) return null

    const updated: StrategyDefinition = {
      ...strategy,
      ...updates,
      id: strategy.id,
      createdAt: strategy.createdAt,
      updatedAt: Date.now(),
    }

    this.strategies.set(id, updated)
    await this.syncToServer('update', updated)

    return updated
  }

  /**
   * 获取策略详情
   */
  async getStrategy(id: string): Promise<StrategyDefinition | null> {
    let strategy = this.strategies.get(id)

    if (!strategy) {
      // 从服务器获取
      strategy = await this.fetchFromServer(id)
      if (strategy) {
        this.strategies.set(id, strategy)
      }
    }

    // 增加浏览量
    if (strategy) {
      strategy.stats.views++
    }

    return strategy || null
  }

  /**
   * 搜索策略
   */
  async searchStrategies(params: StrategySearchParams): Promise<{
    strategies: StrategyDefinition[]
    total: number
    page: number
    pageSize: number
  }> {
    let results = Array.from(this.strategies.values())
      .filter(s => s.status === 'published')

    // 关键词搜索
    if (params.query) {
      const query = params.query.toLowerCase()
      results = results.filter(s =>
        s.name.toLowerCase().includes(query) ||
        s.description.toLowerCase().includes(query) ||
        s.tags.some(t => t.toLowerCase().includes(query))
      )
    }

    // 类型筛选
    if (params.type) {
      results = results.filter(s => s.type === params.type)
    }

    // 标签筛选
    if (params.tags && params.tags.length > 0) {
      results = results.filter(s =>
        params.tags!.some(t => s.tags.includes(t))
      )
    }

    // 价格范围筛选
    if (params.priceRange) {
      results = results.filter(s =>
        s.price >= params.priceRange!.min &&
        s.price <= params.priceRange!.max
      )
    }

    // 可见性筛选
    if (params.visibility && params.visibility.length > 0) {
      results = results.filter(s =>
        params.visibility!.includes(s.visibility)
      )
    }

    // 排序
    switch (params.sortBy) {
      case 'popularity':
        results.sort((a, b) => b.stats.subscribers - a.stats.subscribers)
        break
      case 'rating':
        results.sort((a, b) => b.ratings.average - a.ratings.average)
        break
      case 'return':
        results.sort((a, b) =>
          (b.backtestResult?.totalReturn || 0) - (a.backtestResult?.totalReturn || 0)
        )
        break
      case 'sharpe':
        results.sort((a, b) =>
          (b.backtestResult?.sharpeRatio || 0) - (a.backtestResult?.sharpeRatio || 0)
        )
        break
      case 'trending':
        // 近7天订阅数
        results.sort((a, b) => b.stats.views - a.stats.views)
        break
      case 'newest':
      default:
        results.sort((a, b) => (b.publishedAt || 0) - (a.publishedAt || 0))
    }

    // 分页
    const page = params.page || 1
    const pageSize = params.pageSize || 20
    const total = results.length
    const start = (page - 1) * pageSize
    const end = start + pageSize

    return {
      strategies: results.slice(start, end),
      total,
      page,
      pageSize,
    }
  }

  /**
   * 订阅策略
   */
  async subscribeStrategy(strategyId: string, settings: StrategySubscription['settings']): Promise<StrategySubscription> {
    const subscription: StrategySubscription = {
      id: this.generateId(),
      strategyId,
      userId: this.getCurrentUserId(),
      status: 'active',
      subscribedAt: Date.now(),
      settings,
    }

    const userSubs = this.subscriptions.get(subscription.userId) || []
    userSubs.push(subscription)
    this.subscriptions.set(subscription.userId, userSubs)

    // 更新策略订阅数
    const strategy = this.strategies.get(strategyId)
    if (strategy) {
      strategy.stats.subscribers++
    }

    await this.syncToServer('subscribe', subscription)

    return subscription
  }

  /**
   * 取消订阅
   */
  async unsubscribeStrategy(strategyId: string): Promise<boolean> {
    const userId = this.getCurrentUserId()
    const userSubs = this.subscriptions.get(userId) || []

    const index = userSubs.findIndex(s => s.strategyId === strategyId)
    if (index === -1) return false

    userSubs.splice(index, 1)

    // 更新策略订阅数
    const strategy = this.strategies.get(strategyId)
    if (strategy) {
      strategy.stats.subscribers--
    }

    await this.syncToServer('unsubscribe', { strategyId, userId })

    return true
  }

  /**
   * 获取用户订阅的策略
   */
  getUserSubscriptions(): StrategySubscription[] {
    const userId = this.getCurrentUserId()
    return this.subscriptions.get(userId) || []
  }

  /**
   * 点赞策略
   */
  async likeStrategy(strategyId: string): Promise<boolean> {
    const key = `${this.getCurrentUserId()}_${strategyId}`

    if (this.userLikes.has(key)) {
      // 取消点赞
      this.userLikes.delete(key)
      const strategy = this.strategies.get(strategyId)
      if (strategy) {
        strategy.stats.likes--
      }
      await this.syncToServer('unlike', { strategyId })
      return false
    } else {
      // 点赞
      this.userLikes.add(key)
      const strategy = this.strategies.get(strategyId)
      if (strategy) {
        strategy.stats.likes++
      }
      await this.syncToServer('like', { strategyId })
      return true
    }
  }

  /**
   * 评分策略
   */
  async rateStrategy(strategyId: string, rating: 1 | 2 | 3 | 4 | 5, review?: string): Promise<void> {
    const strategy = this.strategies.get(strategyId)
    if (!strategy) return

    strategy.ratings.distribution[rating]++
    strategy.ratings.count++

    // 计算平均分
    let total = 0
    for (let i = 1; i <= 5; i++) {
      total += i * strategy.ratings.distribution[i as keyof typeof strategy.ratings.distribution]
    }
    strategy.ratings.average = total / strategy.ratings.count

    await this.syncToServer('rate', { strategyId, rating, review })
  }

  /**
   * 添加评论
   */
  async addComment(strategyId: string, content: string, parentId?: string): Promise<StrategyComment> {
    const comment: StrategyComment = {
      id: this.generateId(),
      strategyId,
      userId: this.getCurrentUserId(),
      userName: this.getCurrentUserName(),
      content,
      parentId,
      likes: 0,
      likedBy: [],
      createdAt: Date.now(),
    }

    const strategyComments = this.comments.get(strategyId) || []
    strategyComments.unshift(comment)
    this.comments.set(strategyId, strategyComments)

    // 更新评论数
    const strategy = this.strategies.get(strategyId)
    if (strategy) {
      strategy.stats.comments++
    }

    await this.syncToServer('comment', comment)

    return comment
  }

  /**
   * 获取策略评论
   */
  getComments(strategyId: string, page = 1, pageSize = 20): {
    comments: StrategyComment[]
    total: number
  } {
    const allComments = this.comments.get(strategyId) || []
    const start = (page - 1) * pageSize
    const end = start + pageSize

    return {
      comments: allComments.slice(start, end),
      total: allComments.length,
    }
  }

  /**
   * 发起讨论
   */
  async createDiscussion(strategyId: string, title: string, content: string, tags: string[]): Promise<StrategyDiscussion> {
    const discussion: StrategyDiscussion = {
      id: this.generateId(),
      strategyId,
      title,
      content,
      author: {
        id: this.getCurrentUserId(),
        name: this.getCurrentUserName(),
      },
      tags,
      replies: 0,
      views: 0,
      lastReplyAt: Date.now(),
      createdAt: Date.now(),
    }

    const strategyDiscussions = this.discussions.get(strategyId) || []
    strategyDiscussions.unshift(discussion)
    this.discussions.set(strategyId, strategyDiscussions)

    await this.syncToServer('discussion', discussion)

    return discussion
  }

  /**
   * 获取策略讨论
   */
  getDiscussions(strategyId: string, page = 1, pageSize = 20): {
    discussions: StrategyDiscussion[]
    total: number
  } {
    const allDiscussions = this.discussions.get(strategyId) || []
    const start = (page - 1) * pageSize
    const end = start + pageSize

    return {
      discussions: allDiscussions.slice(start, end),
      total: allDiscussions.length,
    }
  }

  /**
   * Fork 策略
   */
  async forkStrategy(strategyId: string, newName?: string): Promise<StrategyDefinition> {
    const original = this.strategies.get(strategyId)
    if (!original) throw new Error('Strategy not found')

    const forked: StrategyDefinition = {
      ...original,
      id: this.generateId(),
      name: newName || `${original.name} (Fork)`,
      author: {
        id: this.getCurrentUserId(),
        name: this.getCurrentUserName(),
      },
      status: 'draft',
      stats: {
        views: 0,
        likes: 0,
        subscribers: 0,
        forks: 0,
        comments: 0,
      },
      ratings: {
        average: 0,
        count: 0,
        distribution: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 },
      },
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }

    this.strategies.set(forked.id, forked)

    // 更新原始策略的 fork 数
    original.stats.forks++

    await this.syncToServer('fork', { originalId: strategyId, forked })

    return forked
  }

  /**
   * 获取推荐策略
   */
  async getRecommendedStrategies(limit = 10): Promise<StrategyDefinition[]> {
    // 基于用户订阅历史、评分、热门策略推荐
    const all = Array.from(this.strategies.values())
      .filter(s => s.status === 'published')

    // 简单的推荐算法：综合评分
    return all
      .sort((a, b) => {
        const scoreA = this.calculateRecommendScore(a)
        const scoreB = this.calculateRecommendScore(b)
        return scoreB - scoreA
      })
      .slice(0, limit)
  }

  /**
   * 计算推荐分数
   */
  private calculateRecommendScore(strategy: StrategyDefinition): number {
    const ratingScore = strategy.ratings.average * 20
    const popularScore = Math.min(strategy.stats.subscribers / 10, 30)
    const returnScore = Math.min((strategy.backtestResult?.totalReturn || 0) / 10, 30)
    const sharpeScore = Math.min((strategy.backtestResult?.sharpeRatio || 0) * 5, 20)

    return ratingScore + popularScore + returnScore + sharpeScore
  }

  /**
   * 获取热门标签
   */
  getPopularTags(limit = 20): { tag: string; count: number }[] {
    const tagCounts = new Map<string, number>()

    for (const strategy of this.strategies.values()) {
      for (const tag of strategy.tags) {
        tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1)
      }
    }

    return Array.from(tagCounts.entries())
      .map(([tag, count]) => ({ tag, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, limit)
  }

  // 私有方法

  private generateId(): string {
    return `str_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  private getCurrentUserId(): string {
    return localStorage.getItem('userId') || 'anonymous'
  }

  private getCurrentUserName(): string {
    return localStorage.getItem('userName') || 'Anonymous'
  }

  private async syncToServer(action: string, data: unknown): Promise<void> {
    try {
      await fetch(`${this.apiEndpoint}/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, data }),
      })
    } catch (error) {
      console.warn('[StrategySharing] Sync failed:', error)
    }
  }

  private async fetchFromServer(id: string): Promise<StrategyDefinition | null> {
    try {
      const response = await fetch(`${this.apiEndpoint}/strategies/${id}`)
      if (response.ok) {
        return response.json()
      }
    } catch (error) {
      console.warn('[StrategySharing] Fetch failed:', error)
    }
    return null
  }
}

// 导出单例
export const strategySharingService = new StrategySharingService()

export default strategySharingService
