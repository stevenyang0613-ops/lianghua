/**
 * 应用使用统计分析 Store
 * 记录用户行为、页面访问、功能使用等
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface PageVisit {
  path: string
  title: string
  timestamp: number
  duration: number
}

interface FeatureUsage {
  feature: string
  count: number
  lastUsed: number
}

interface DailyStats {
  date: string
  sessions: number
  pageViews: number
  featuresUsed: string[]
  totalDuration: number
}

interface AnalyticsState {
  // 会话统计
  sessionId: string | null
  sessionStart: number | null

  // 页面访问记录
  pageVisits: PageVisit[]
  currentPage: string | null
  pageEnterTime: number | null

  // 功能使用统计
  featureUsage: Record<string, FeatureUsage>

  // 每日统计
  dailyStats: Record<string, DailyStats>

  // 总体统计
  totalSessions: number
  totalPagesViews: number
  totalDuration: number

  // Actions
  startSession: () => void
  endSession: () => void
  trackPageView: (path: string, title: string) => void
  trackFeature: (feature: string) => void
  getStats: () => AnalyticsSummary
  getTopPages: (limit?: number) => { path: string; count: number }[]
  getTopFeatures: (limit?: number) => { feature: string; count: number }[]
  getDailyStats: (days?: number) => DailyStats[]
  exportData: () => string
  clearData: () => void
}

interface AnalyticsSummary {
  totalSessions: number
  totalPagesViews: number
  totalDuration: number
  avgSessionDuration: number
  avgPageViewsPerSession: number
  topPages: { path: string; count: number }[]
  topFeatures: { feature: string; count: number }[]
  recentActivity: PageVisit[]
}

const generateSessionId = () => `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

export const useAnalyticsStore = create<AnalyticsState>()(
  persist(
    (set, get) => ({
      sessionId: null,
      sessionStart: null,
      pageVisits: [],
      currentPage: null,
      pageEnterTime: null,
      featureUsage: {},
      dailyStats: {},
      totalSessions: 0,
      totalPagesViews: 0,
      totalDuration: 0,

      startSession: () => {
        const sessionId = generateSessionId()
        const today = new Date().toISOString().split('T')[0]

        set((state) => {
          const dailyStats = { ...state.dailyStats }
          if (!dailyStats[today]) {
            dailyStats[today] = {
              date: today,
              sessions: 0,
              pageViews: 0,
              featuresUsed: [],
              totalDuration: 0,
            }
          }
          dailyStats[today].sessions++

          return {
            sessionId,
            sessionStart: Date.now(),
            totalSessions: state.totalSessions + 1,
            dailyStats,
          }
        })
      },

      endSession: () => {
        const { sessionStart, currentPage, pageEnterTime } = get()
        const duration = sessionStart ? Date.now() - sessionStart : 0
        const today = new Date().toISOString().split('T')[0]

        // 记录最后一个页面的停留时间
        if (currentPage && pageEnterTime) {
          const pageDuration = Date.now() - pageEnterTime
          set((state) => ({
            pageVisits: state.pageVisits.map((visit, index) =>
              index === state.pageVisits.length - 1
                ? { ...visit, duration: pageDuration }
                : visit
            ),
          }))
        }

        set((state) => {
          const dailyStats = { ...state.dailyStats }
          if (dailyStats[today]) {
            dailyStats[today].totalDuration += duration
          }

          return {
            sessionId: null,
            sessionStart: null,
            totalDuration: state.totalDuration + duration,
            currentPage: null,
            pageEnterTime: null,
            dailyStats,
          }
        })
      },

      trackPageView: (path: string, title: string) => {
        const { currentPage, pageEnterTime, pageVisits } = get()
        const now = Date.now()
        const today = new Date().toISOString().split('T')[0]

        // 记录上一个页面的停留时间
        const updatedVisits = [...pageVisits]
        if (currentPage && pageEnterTime) {
          const lastVisit = updatedVisits[updatedVisits.length - 1]
          if (lastVisit && lastVisit.path === currentPage) {
            lastVisit.duration = now - pageEnterTime
          }
        }

        // 添加新页面访问
        updatedVisits.push({
          path,
          title,
          timestamp: now,
          duration: 0,
        })

        // 只保留最近 1000 条记录
        const trimmedVisits = updatedVisits.slice(-1000)

        set((state) => {
          const dailyStats = { ...state.dailyStats }
          if (!dailyStats[today]) {
            dailyStats[today] = {
              date: today,
              sessions: 0,
              pageViews: 0,
              featuresUsed: [],
              totalDuration: 0,
            }
          }
          dailyStats[today].pageViews++

          return {
            pageVisits: trimmedVisits,
            currentPage: path,
            pageEnterTime: now,
            totalPagesViews: state.totalPagesViews + 1,
            dailyStats,
          }
        })
      },

      trackFeature: (feature: string) => {
        const today = new Date().toISOString().split('T')[0]

        set((state) => {
          const featureUsage = { ...state.featureUsage }
          if (featureUsage[feature]) {
            featureUsage[feature].count++
            featureUsage[feature].lastUsed = Date.now()
          } else {
            featureUsage[feature] = {
              feature,
              count: 1,
              lastUsed: Date.now(),
            }
          }

          const dailyStats = { ...state.dailyStats }
          if (!dailyStats[today]) {
            dailyStats[today] = {
              date: today,
              sessions: 0,
              pageViews: 0,
              featuresUsed: [],
              totalDuration: 0,
            }
          }
          if (!dailyStats[today].featuresUsed.includes(feature)) {
            dailyStats[today].featuresUsed.push(feature)
          }

          return { featureUsage, dailyStats }
        })
      },

      getStats: (): AnalyticsSummary => {
        const state = get()
        const avgSessionDuration = state.totalSessions > 0
          ? state.totalDuration / state.totalSessions
          : 0
        const avgPageViewsPerSession = state.totalSessions > 0
          ? state.totalPagesViews / state.totalSessions
          : 0

        return {
          totalSessions: state.totalSessions,
          totalPagesViews: state.totalPagesViews,
          totalDuration: state.totalDuration,
          avgSessionDuration,
          avgPageViewsPerSession,
          topPages: get().getTopPages(5),
          topFeatures: get().getTopFeatures(5),
          recentActivity: state.pageVisits.slice(-10).reverse(),
        }
      },

      getTopPages: (limit = 5) => {
        const { pageVisits } = get()
        const pageCounts: Record<string, number> = {}

        pageVisits.forEach((visit) => {
          pageCounts[visit.path] = (pageCounts[visit.path] || 0) + 1
        })

        return Object.entries(pageCounts)
          .map(([path, count]) => ({ path, count }))
          .sort((a, b) => b.count - a.count)
          .slice(0, limit)
      },

      getTopFeatures: (limit = 5) => {
        const { featureUsage } = get()

        return Object.values(featureUsage)
          .sort((a, b) => b.count - a.count)
          .slice(0, limit)
      },

      getDailyStats: (days = 7) => {
        const { dailyStats } = get()
        const result: DailyStats[] = []
        const today = new Date()

        for (let i = 0; i < days; i++) {
          const date = new Date(today)
          date.setDate(date.getDate() - i)
          const dateStr = date.toISOString().split('T')[0]
          result.push(dailyStats[dateStr] || {
            date: dateStr,
            sessions: 0,
            pageViews: 0,
            featuresUsed: [],
            totalDuration: 0,
          })
        }

        return result.reverse()
      },

      exportData: () => {
        const state = get()
        return JSON.stringify({
          exportedAt: new Date().toISOString(),
          summary: {
            totalSessions: state.totalSessions,
            totalPagesViews: state.totalPagesViews,
            totalDuration: state.totalDuration,
          },
          pageVisits: state.pageVisits,
          featureUsage: state.featureUsage,
          dailyStats: state.dailyStats,
        }, null, 2)
      },

      clearData: () => {
        set({
          sessionId: null,
          sessionStart: null,
          pageVisits: [],
          currentPage: null,
          pageEnterTime: null,
          featureUsage: {},
          dailyStats: {},
          totalSessions: 0,
          totalPagesViews: 0,
          totalDuration: 0,
        })
      },
    }),
    {
      name: 'lianghua-analytics',
    }
  )
)

// 自动追踪页面访问
export function initAnalyticsTracking(): () => void {
  const store = useAnalyticsStore.getState()
  store.startSession()

  // 监听页面卸载
  const beforeUnloadHandler = () => { store.endSession() }
  window.addEventListener('beforeunload', beforeUnloadHandler)

  // 监听页面可见性变化
  const visibilityHandler = () => {
    if (document.visibilityState === 'hidden') {
      store.endSession()
    } else {
      store.startSession()
    }
  }
  document.addEventListener('visibilitychange', visibilityHandler)

  return () => {
    window.removeEventListener('beforeunload', beforeUnloadHandler)
    document.removeEventListener('visibilitychange', visibilityHandler)
  }
}

export default useAnalyticsStore
