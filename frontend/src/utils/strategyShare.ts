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

// 模拟社区策略数据
const MOCK_STRATEGIES: SharedStrategy[] = [
  {
    id: 'strategy_1',
    name: 'MACD金叉策略',
    description: '基于MACD指标的金叉买入、死叉卖出策略，适合趋势行情',
    author: '量化小明',
    avatar: '',
    category: 'trend',
    tags: ['MACD', '趋势', '中长线'],
    rating: 4.8,
    downloads: 1234,
    likes: 567,
    returns: 45.2,
    maxDrawdown: 12.3,
    sharpe: 1.85,
    winRate: 62.5,
    tradeCount: 89,
    createdAt: Date.now() - 90 * 24 * 60 * 60 * 1000,
    updatedAt: Date.now() - 10 * 24 * 60 * 60 * 1000,
    params: [
      { name: 'fastPeriod', type: 'number', default: 12, description: '快线周期' },
      { name: 'slowPeriod', type: 'number', default: 26, description: '慢线周期' },
      { name: 'signalPeriod', type: 'number', default: 9, description: '信号线周期' },
    ],
  },
  {
    id: 'strategy_2',
    name: '双低轮动策略',
    description: '选择价格和溢价率双低的转债进行轮动，低风险稳健策略',
    author: '稳健投资者',
    avatar: '',
    category: 'arbitrage',
    tags: ['双低', '轮动', '低风险'],
    rating: 4.5,
    downloads: 2345,
    likes: 890,
    returns: 28.6,
    maxDrawdown: 5.2,
    sharpe: 2.35,
    winRate: 71.2,
    tradeCount: 156,
    createdAt: Date.now() - 180 * 24 * 60 * 60 * 1000,
    updatedAt: Date.now() - 5 * 24 * 60 * 60 * 1000,
    params: [
      { name: 'dualLowThreshold', type: 'number', default: 150, description: '双低值阈值' },
      { name: 'rebalanceDays', type: 'number', default: 5, description: '轮动周期(天)' },
    ],
  },
  {
    id: 'strategy_3',
    name: 'RSI超卖反弹',
    description: '捕捉RSI超卖后的反弹机会，适合震荡市场',
    author: '波段高手',
    avatar: '',
    category: 'reversal',
    tags: ['RSI', '反弹', '短线'],
    rating: 4.2,
    downloads: 876,
    likes: 345,
    returns: 32.1,
    maxDrawdown: 18.5,
    sharpe: 1.42,
    winRate: 55.8,
    tradeCount: 234,
    createdAt: Date.now() - 60 * 24 * 60 * 60 * 1000,
    updatedAt: Date.now() - 3 * 24 * 60 * 60 * 1000,
    params: [
      { name: 'rsiPeriod', type: 'number', default: 14, description: 'RSI周期' },
      { name: 'oversoldThreshold', type: 'number', default: 30, description: '超卖阈值' },
      { name: 'overboughtThreshold', type: 'number', default: 70, description: '超买阈值' },
    ],
  },
  {
    id: 'strategy_4',
    name: '均线多因子策略',
    description: '多均线组合判断趋势，结合成交量确认信号',
    author: '多因子研究员',
    avatar: '',
    category: 'quant',
    tags: ['均线', '多因子', '量化'],
    rating: 4.6,
    downloads: 1567,
    likes: 678,
    returns: 38.9,
    maxDrawdown: 15.2,
    sharpe: 1.95,
    winRate: 58.3,
    tradeCount: 112,
    createdAt: Date.now() - 120 * 24 * 60 * 60 * 1000,
    updatedAt: Date.now() - 7 * 24 * 60 * 60 * 1000,
    params: [
      { name: 'shortMA', type: 'number', default: 5, description: '短期均线' },
      { name: 'midMA', type: 'number', default: 20, description: '中期均线' },
      { name: 'longMA', type: 'number', default: 60, description: '长期均线' },
    ],
  },
  {
    id: 'strategy_5',
    name: '网格交易策略',
    description: '在设定价格区间内进行网格买卖，适合震荡行情',
    author: '网格大师',
    avatar: '',
    category: 'custom',
    tags: ['网格', '震荡', '自动化'],
    rating: 4.3,
    downloads: 3456,
    likes: 1234,
    returns: 25.8,
    maxDrawdown: 8.9,
    sharpe: 2.12,
    winRate: 68.5,
    tradeCount: 567,
    createdAt: Date.now() - 200 * 24 * 60 * 60 * 1000,
    updatedAt: Date.now() - 2 * 24 * 60 * 60 * 1000,
    params: [
      { name: 'gridCount', type: 'number', default: 10, description: '网格数量' },
      { name: 'gridRange', type: 'number', default: 10, description: '网格范围(%)' },
    ],
  },
]

// 获取社区策略
export function getSharedStrategies(options?: {
  category?: string
  sortBy?: 'rating' | 'downloads' | 'returns' | 'createdAt'
  search?: string
}): SharedStrategy[] {
  let strategies = [...MOCK_STRATEGIES]

  if (options?.category && options.category !== 'all') {
    strategies = strategies.filter(s => s.category === options.category)
  }

  if (options?.search) {
    const search = options.search.toLowerCase()
    strategies = strategies.filter(s =>
      s.name.toLowerCase().includes(search) ||
      s.description.toLowerCase().includes(search) ||
      s.tags.some(t => t.toLowerCase().includes(search))
    )
  }

  if (options?.sortBy) {
    strategies.sort((a, b) => {
      switch (options.sortBy) {
        case 'rating': return b.rating - a.rating
        case 'downloads': return b.downloads - a.downloads
        case 'returns': return b.returns - a.returns
        case 'createdAt': return b.createdAt - a.createdAt
        default: return 0
      }
    })
  }

  return strategies
}

// 获取单个策略
export function getSharedStrategy(id: string): SharedStrategy | null {
  return MOCK_STRATEGIES.find(s => s.id === id) || null
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
