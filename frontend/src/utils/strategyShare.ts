/**
 * 策略分享服务
 */

import { safeJsonParse } from './safeJson'

export interface SharedStrategy {
  id: string
  name: string
  description: string
  author: string
  avatar: string
  category: 'trend' | 'reversal' | 'arbitrage' | 'quant' | 'custom'
  tags: string[]
  rating: number
  downloads: number
  likes: number
  returns: number
  maxDrawdown: number
  sharpe: number
  winRate: number
  tradeCount: number
  createdAt: number
  updatedAt: number
  code?: string
  params: { name: string; type: string; default: unknown; description: string }[]
}

export interface StrategyReview {
  id: string
  strategyId: string
  author: string
  rating: number
  content: string
  createdAt: number
}

const MY_STRATEGIES_KEY = 'my_strategies'
const REVIEWS_KEY = 'strategy_reviews'

// 获取社区策略
export function getSharedStrategies(options?: {
  category?: string
  sortBy?: 'rating' | 'downloads' | 'returns' | 'createdAt'
  search?: string
}): SharedStrategy[] {
  console.warn('[StrategyShare] getSharedStrategies: 需要接入后端 API 获取真实社区策略数据')
  return []
}

// 获取单个策略
export function getSharedStrategy(id: string): SharedStrategy | null {
  return null
}

// 下载策略
export function downloadStrategy(id: string): SharedStrategy | null {
  const strategy = getSharedStrategy(id)
  if (!strategy) return null

  // 添加到我的策略
  const myStrategies = getMyStrategies()
  if (!myStrategies.find(s => s.id === id)) {
    myStrategies.push(strategy)
    localStorage.setItem(MY_STRATEGIES_KEY, JSON.stringify(myStrategies))
  }

  return strategy
}

// 获取我的策略
export function getMyStrategies(): SharedStrategy[] {
  const saved = localStorage.getItem(MY_STRATEGIES_KEY)
  return safeJsonParse<SharedStrategy[]>(saved, [])
}

// 删除我的策略
export function deleteMyStrategy(id: string): boolean {
  const strategies = getMyStrategies()
  const filtered = strategies.filter(s => s.id !== id)
  localStorage.setItem(MY_STRATEGIES_KEY, JSON.stringify(filtered))
  return true
}

// 点赞策略
export function likeStrategy(id: string): void {
  const key = `liked_${id}`
  if (localStorage.getItem(key)) return
  localStorage.setItem(key, 'true')
}

// 检查是否已点赞
export function hasLikedStrategy(id: string): boolean {
  return localStorage.getItem(`liked_${id}`) === 'true'
}

// 获取策略评价
export function getStrategyReviews(strategyId: string): StrategyReview[] {
  const saved = localStorage.getItem(REVIEWS_KEY)
  const allReviews: StrategyReview[] = safeJsonParse<StrategyReview[]>(saved, [])
  return allReviews.filter(r => r.strategyId === strategyId)
}

// 添加评价
export function addStrategyReview(strategyId: string, rating: number, content: string): StrategyReview {
  const saved = localStorage.getItem(REVIEWS_KEY)
  const reviews: StrategyReview[] = safeJsonParse<StrategyReview[]>(saved, [])

  const review: StrategyReview = {
    id: `review_${Date.now()}`,
    strategyId,
    author: '匿名用户',
    rating,
    content,
    createdAt: Date.now(),
  }

  reviews.push(review)
  localStorage.setItem(REVIEWS_KEY, JSON.stringify(reviews))

  return review
}

// 策略分类选项
export const CATEGORY_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'trend', label: '趋势策略' },
  { value: 'reversal', label: '反转策略' },
  { value: 'arbitrage', label: '套利策略' },
  { value: 'quant', label: '量化策略' },
  { value: 'custom', label: '自定义' },
]

// 排序选项
export const SORT_OPTIONS = [
  { value: 'rating', label: '评分最高' },
  { value: 'downloads', label: '下载最多' },
  { value: 'returns', label: '收益最高' },
  { value: 'createdAt', label: '最新发布' },
]

export default {
  getSharedStrategies,
  getSharedStrategy,
  downloadStrategy,
  getMyStrategies,
  deleteMyStrategy,
  likeStrategy,
  hasLikedStrategy,
  getStrategyReviews,
  addStrategyReview,
  CATEGORY_OPTIONS,
  SORT_OPTIONS,
}
