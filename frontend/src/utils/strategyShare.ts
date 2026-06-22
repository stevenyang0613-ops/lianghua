/**
 * 策略分享服务
 *
 * 已实现：
 * - 从后端 /api/v1/strategies-share/ 拉取真实社区策略数据
 * - 本地 localStorage 缓存「我的策略」「点赞」「评价」状态
 * - 下载/点赞同步后端并持久化
 *
 * 种子数据来源：
 * - 方正证券《可转债投资策略系列二：经典双低与轮动策略》
 * - 集思录社区（双低改进版、多因子平衡型策略）
 * - 雪球《可转债的回售博弈》
 * - GitHub: paulhybryant/convertible_bond / tanish35/Momentum-Investing / je-suis-tm/quant-trading
 * - 学术文献（ScienceDirect / Tilburg / JFE）
 * - BigQuant 研报库（华泰金工、广发证券、中信建投）
 */

import { getApiBase } from './config'
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

export interface SharedStrategyFilter {
  category?: string
  sortBy?: 'rating' | 'downloads' | 'returns' | 'createdAt'
  search?: string
  page?: number
  pageSize?: number
}

export interface SharedStrategyPage {
  strategies: SharedStrategy[]
  total: number
  page: number
  pageSize: number
}

const MY_STRATEGIES_KEY = 'my_strategies'
const REVIEWS_KEY = 'strategy_reviews'
const LIKED_SET_KEY = 'liked_strategy_ids'
const CACHE_KEY = 'strategy_market_cache'
const CACHE_TTL = 5 * 60 * 1000 // 5 分钟

function getBase(): string {
  return getApiBase() + '/api/v1/strategies-share'
}

async function fetchJSON<T>(url: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('ws_auth_token')
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(url, { headers })
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

async function postJSON<T>(url: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('ws_auth_token')
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(url, {
    method: 'POST',
    headers,
  })
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

function toTimestamp(value: string | number | undefined): number {
  if (!value) return Date.now()
  if (typeof value === 'number') return value
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? Date.now() : d.getTime()
}

function backendTypeToCategory(type: string): SharedStrategy['category'] {
  switch (type) {
    case 'trend':
      return 'trend'
    case 'meanReversion':
      return 'reversal'
    case 'arbitrage':
      return 'arbitrage'
    case 'quant':
    case 'marketMaking':
      return 'quant'
    case 'custom':
    default:
      return 'custom'
  }
}

function mapBackendToShared(item: any): SharedStrategy | null {
  if (!item || !item.id) return null
  const bt = item.backtestResult || {}
  const stats = item.stats || {}
  const ratings = item.ratings || {}
  return {
    id: item.id,
    name: item.name || '',
    description: item.description || '',
    author: item.author?.name || item.author?.id || '社区作者',
    avatar: item.author?.avatar || '',
    category: backendTypeToCategory(item.type),
    tags: Array.isArray(item.tags) ? item.tags : [],
    rating: typeof ratings.average === 'number' ? ratings.average : 0,
    downloads: typeof stats.downloads === 'number' ? stats.downloads : 0,
    likes: typeof stats.likes === 'number' ? stats.likes : 0,
    returns: typeof bt.totalReturn === 'number' ? bt.totalReturn : 0,
    maxDrawdown: typeof bt.maxDrawdown === 'number' ? bt.maxDrawdown : 0,
    sharpe: typeof bt.sharpeRatio === 'number' ? bt.sharpeRatio : 0,
    winRate: typeof bt.winRate === 'number' ? bt.winRate : 0,
    tradeCount: typeof bt.tradesCount === 'number' ? bt.tradesCount : 0,
    createdAt: toTimestamp(item.createdAt),
    updatedAt: toTimestamp(item.updatedAt),
    code: item.code || '',
    params: Array.isArray(item.params)
      ? item.params.map((p: any) => ({
          name: p.name || '',
          type: p.type || 'str',
          default: p.default,
          description: p.description || '',
        }))
      : [],
  }
}

function loadLocalCache(): SharedStrategy[] {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return []
    const parsed = safeJsonParse<{ data: SharedStrategy[]; ts: number }>(raw, { data: [], ts: 0 })
    if (Date.now() - parsed.ts > CACHE_TTL) return []
    return parsed.data
  } catch {
    return []
  }
}

function saveLocalCache(data: SharedStrategy[]): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ data, ts: Date.now() }))
  } catch {
    // localStorage 可能已满，静默失败
  }
}

function loadLikedIds(): Set<string> {
  try {
    const raw = localStorage.getItem(LIKED_SET_KEY)
    return new Set(safeJsonParse<string[]>(raw, []))
  } catch {
    return new Set()
  }
}

function saveLikedIds(ids: Set<string>): void {
  try {
    localStorage.setItem(LIKED_SET_KEY, JSON.stringify(Array.from(ids)))
  } catch {
    // ignore
  }
}

// 获取社区策略
export async function getSharedStrategies(options?: SharedStrategyFilter): Promise<SharedStrategyPage> {
  const base = getBase()

  const params = new URLSearchParams()
  if (options?.search) params.set('query', options.search)
  if (options?.category && options.category !== 'all') {
    const mapping: Record<string, string> = {
      trend: 'trend',
      reversal: 'meanReversion',
      arbitrage: 'arbitrage',
      quant: 'quant',
      custom: 'custom',
    }
    params.set('type', mapping[options.category] || options.category)
  }
  if (options?.sortBy) {
    const sortMapping: Record<string, string> = {
      rating: 'rating',
      downloads: 'popularity',
      returns: 'returns',
      createdAt: 'newest',
    }
    params.set('sortBy', sortMapping[options.sortBy] || 'newest')
  }
  params.set('page', String(options?.page || 1))
  params.set('pageSize', String(options?.pageSize || 20))

  try {
    const url = `${base}/?${params.toString()}`
    const pageData = await fetchJSON<{ strategies?: any[]; total?: number; page?: number; pageSize?: number }>(url)
    const rawStrategies = Array.isArray(pageData.strategies) ? pageData.strategies : []
    const mapped = rawStrategies.map(mapBackendToShared).filter((s): s is SharedStrategy => s !== null)
    saveLocalCache(mapped)
    return {
      strategies: mapped,
      total: pageData.total ?? mapped.length,
      page: pageData.page ?? options?.page ?? 1,
      pageSize: pageData.pageSize ?? options?.pageSize ?? 20,
    }
  } catch (error) {
    console.warn('[StrategyShare] 后端策略市场不可用，使用本地缓存:', error)
    const cached = loadLocalCache()
    return {
      strategies: cached,
      total: cached.length,
      page: options?.page || 1,
      pageSize: options?.pageSize || 20,
    }
  }
}

// 获取单个策略
export async function getSharedStrategy(id: string): Promise<SharedStrategy | null> {
  const base = getBase()
  try {
    const item = await fetchJSON<any>(`${base}/${id}`)
    return mapBackendToShared(item)
  } catch (error) {
    console.warn('[StrategyShare] 获取策略详情失败:', error)
    const cached = loadLocalCache()
    return cached.find(s => s.id === id) || null
  }
}

// 下载策略
export async function downloadStrategy(id: string): Promise<SharedStrategy | null> {
  const strategy = await getSharedStrategy(id)
  if (!strategy) return null

  // 同步后端下载计数
  try {
    await postJSON<{ downloads: number }>(`${getBase()}/${id}/download`)
  } catch (error) {
    console.warn('[StrategyShare] 同步后端下载计数失败:', error)
  }

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
export async function likeStrategy(id: string): Promise<void> {
  const liked = loadLikedIds()
  if (liked.has(id)) return

  try {
    await postJSON<{ likes: number }>(`${getBase()}/${id}/like`)
  } catch (error) {
    console.warn('[StrategyShare] 同步后端点赞失败:', error)
  }

  liked.add(id)
  saveLikedIds(liked)
}

// 检查是否已点赞
export function hasLikedStrategy(id: string): boolean {
  return loadLikedIds().has(id)
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
