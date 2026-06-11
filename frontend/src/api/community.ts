/**
 * 后端 API 代理服务
 * 策略分享、AI分析、日志上报、告警管理
 */

import axios from 'axios'

// API 基础配置
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.message || error.message
    console.error('[API Error]', message)
    return Promise.reject(error)
  }
)

// =====================
// 策略分享 API
// =====================
export const strategyAPI = {
  /** 获取策略列表 */
  getStrategies: (params?: {
    query?: string
    type?: string
    tags?: string[]
    sortBy?: string
    page?: number
    pageSize?: number
  }) => api.get('/strategies', { params }),

  /** 获取策略详情 */
  getStrategy: (id: string) => api.get(`/strategies/${id}`),

  /** 创建策略 */
  createStrategy: (data: {
    name: string
    description: string
    type: string
    code: string
    config: Record<string, unknown>
    visibility: string
    price?: number
  }) => api.post('/strategies', data),

  /** 更新策略 */
  updateStrategy: (id: string, data: Partial<{
    name: string
    description: string
    code: string
    config: Record<string, unknown>
    status: string
  }>) => api.put(`/strategies/${id}`, data),

  /** 删除策略 */
  deleteStrategy: (id: string) => api.delete(`/strategies/${id}`),

  /** 订阅策略 */
  subscribe: (strategyId: string, settings: {
    autoSync: boolean
    notifications: boolean
    realTrading: boolean
    accounts: string[]
  }) => api.post(`/strategies/${strategyId}/subscribe`, settings),

  /** 取消订阅 */
  unsubscribe: (strategyId: string) => api.delete(`/strategies/${strategyId}/subscribe`),

  /** 点赞 */
  like: (strategyId: string) => api.post(`/strategies/${strategyId}/like`),

  /** 评分 */
  rate: (strategyId: string, rating: number, review?: string) =>
    api.post(`/strategies/${strategyId}/rate`, { rating, review }),

  /** 评论 */
  addComment: (strategyId: string, content: string, parentId?: string) =>
    api.post(`/strategies/${strategyId}/comments`, { content, parentId }),

  /** 获取评论 */
  getComments: (strategyId: string, page?: number, pageSize?: number) =>
    api.get(`/strategies/${strategyId}/comments`, { params: { page, pageSize } }),

  /** Fork 策略 */
  fork: (strategyId: string, newName?: string) =>
    api.post(`/strategies/${strategyId}/fork`, { newName }),

  /** 获取推荐策略 */
  getRecommended: (limit?: number) =>
    api.get('/strategies/recommended', { params: { limit } }),

  /** 获取热门标签 */
  getPopularTags: (limit?: number) =>
    api.get('/strategies/tags', { params: { limit } }),
}

// =====================
// AI 分析 API
// =====================
export const aiAPI = {
  /** 执行分析 */
  analyze: (data: {
    type: string
    context: Record<string, unknown>
    question?: string
    language?: string
  }) => api.post('/ai/analyze', data),

  /** 市场情绪分析 */
  analyzeSentiment: (symbols: string[], data?: Record<string, unknown>) =>
    api.post('/ai/sentiment', { symbols, data }),

  /** 信号解释 */
  explainSignal: (signalData: Record<string, unknown>) =>
    api.post('/ai/signal/explain', signalData),

  /** 策略优化建议 */
  optimizeStrategy: (strategyData: Record<string, unknown>) =>
    api.post('/ai/strategy/optimize', strategyData),

  /** 风险评估 */
  assessRisk: (portfolio: {
    positions: Array<{ symbol: string; quantity: number; value: number }>
    totalAsset: number
  }) => api.post('/ai/risk/assess', portfolio),

  /** 流式分析（SSE） */
  streamAnalyze: (data: {
    type: string
    context: Record<string, unknown>
  }, onChunk: (text: string) => void): Promise<void> => {
    return new Promise((resolve, reject) => {
      const eventSource = new EventSource(
        `/api/ai/stream?data=${encodeURIComponent(JSON.stringify(data))}`
      )

      eventSource.onmessage = (event) => {
        onChunk(event.data)
      }

      eventSource.onerror = (error) => {
        eventSource.close()
        reject(error)
      }

      eventSource.addEventListener('done', () => {
        eventSource.close()
        resolve()
      })
    })
  },
}

// =====================
// 日志 API
// =====================
export const logAPI = {
  /** 上报日志 */
  report: (data: {
    logs: Array<{
      level: string
      category: string
      message: string
      timestamp: number
      context?: Record<string, unknown>
    }>
    metadata?: Record<string, unknown>
  }) => api.post('/logs/report', data),

  /** 查询日志 */
  query: (params: {
    level?: string
    category?: string
    startTime?: number
    endTime?: number
    page?: number
    pageSize?: number
  }) => api.get('/logs/query', { params }),

  /** 获取日志统计 */
  getStats: (startTime?: number, endTime?: number) =>
    api.get('/logs/stats', { params: { startTime, endTime } }),

  /** 导出日志 */
  export: (format: 'json' | 'csv', params: {
    startTime?: number
    endTime?: number
    level?: string
  }) => api.get('/logs/export', { params: { ...params, format }, responseType: 'blob' }),
}

// =====================
// 告警 API
// =====================
export const alertAPI = {
  /** 获取告警规则 */
  getRules: () => api.get('/alerts/rules'),

  /** 创建规则 */
  createRule: (data: {
    name: string
    description?: string
    level: string
    condition: {
      metric: string
      operator: string
      threshold: number | string
      duration?: number
    }
    channels: string[]
    suppressDuration: number
    recipients?: string[]
  }) => api.post('/alerts/rules', data),

  /** 更新规则 */
  updateRule: (id: string, data: Partial<{
    name: string
    enabled: boolean
    condition: Record<string, unknown>
    channels: string[]
  }>) => api.put(`/alerts/rules/${id}`, data),

  /** 删除规则 */
  deleteRule: (id: string) => api.delete(`/alerts/rules/${id}`),

  /** 获取活动告警 */
  getActiveAlerts: () => api.get('/alerts/active'),

  /** 获取告警历史 */
  getHistory: (params?: {
    level?: string
    ruleId?: string
    startTime?: number
    endTime?: number
    page?: number
    pageSize?: number
  }) => api.get('/alerts/history', { params }),

  /** 确认告警 */
  acknowledge: (alertId: string) => api.post(`/alerts/${alertId}/acknowledge`),

  /** 解决告警 */
  resolve: (alertId: string) => api.post(`/alerts/${alertId}/resolve`),

  /** 配置 Webhook */
  setWebhook: (ruleId: string, config: {
    url: string
    method: string
    headers?: Record<string, string>
    template?: string
  }) => api.post(`/alerts/rules/${ruleId}/webhook`, config),

  /** 测试通知渠道 */
  testChannel: (channel: string, config?: Record<string, unknown>) =>
    api.post('/alerts/test', { channel, config }),
}

// =====================
// 用户 API
// =====================
export const userAPI = {
  /** 登录 */
  login: (username: string, password: string) =>
    api.post('/auth/login', { username, password }),

  /** 注册 */
  register: (data: {
    username: string
    email: string
    password: string
  }) => api.post('/auth/register', data),

  /** 获取用户信息 */
  getProfile: () => api.get('/user/profile'),

  /** 更新用户信息 */
  updateProfile: (data: Partial<{
    nickname: string
    avatar: string
    email: string
  }>) => api.put('/user/profile', data),

  /** 修改密码 */
  changePassword: (oldPassword: string, newPassword: string) =>
    api.put('/user/password', { oldPassword, newPassword }),

  /** 获取用户订阅的策略 */
  getSubscriptions: () => api.get('/user/subscriptions'),

  /** 获取用户发布的策略 */
  getMyStrategies: () => api.get('/user/strategies'),
}

// =====================
// 账户 API
// =====================
export const accountAPI = {
  /** 获取所有账户 */
  getAccounts: () => api.get('/accounts'),

  /** 添加账户 */
  addAccount: (data: {
    name: string
    broker: string
    account: string
    apiKey?: string
    apiSecret?: string
    tradingPassword?: string
  }) => api.post('/accounts', data),

  /** 更新账户 */
  updateAccount: (id: string, data: Partial<{
    name: string
    apiKey: string
    apiSecret: string
    status: string
  }>) => api.put(`/accounts/${id}`, data),

  /** 删除账户 */
  deleteAccount: (id: string) => api.delete(`/accounts/${id}`),

  /** 同步账户资金 */
  syncBalance: (accountId: string) => api.post(`/accounts/${accountId}/sync`),

  /** 获取账户持仓 */
  getPositions: (accountId: string) => api.get(`/accounts/${accountId}/positions`),

  /** 创建账户组 */
  createGroup: (data: {
    name: string
    description?: string
    accountIds: string[]
    riskConfig: Record<string, unknown>
    allocationStrategy: string
  }) => api.post('/accounts/groups', data),

  /** 获取账户组 */
  getGroups: () => api.get('/accounts/groups'),

  /** 删除账户组 */
  deleteGroup: (groupId: string) => api.delete(`/accounts/groups/${groupId}`),
}

export default api
