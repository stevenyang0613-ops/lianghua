/**
 * 图表懒加载工具
 */

import { useMemo, useState, useCallback, useRef } from 'react'

export interface KlineDataPoint {
  date: string
  open: number
  close: number
  low: number
  high: number
  volume: number
}

export interface LazyChartConfig {
  visibleCount: number
  preloadCount: number
  minRenderCount: number
}

const defaultConfig: LazyChartConfig = {
  visibleCount: 200,
  preloadCount: 50,
  minRenderCount: 100,
}

export function useLazyKlineData(
  allData: KlineDataPoint[],
  config: Partial<LazyChartConfig> = {}
) {
  const cfg = { ...defaultConfig, ...config }
  const [startIndex, setStartIndex] = useState(0)
  const [zoomLevel, setZoomLevel] = useState(1)
  const containerRef = useRef<HTMLDivElement>(null)

  const visibleData = useMemo(() => {
    if (!allData.length) return []
    const visibleCount = Math.floor(cfg.visibleCount / zoomLevel)
    const endIndex = Math.min(startIndex + visibleCount + cfg.preloadCount, allData.length)
    const actualStartIndex = Math.max(0, startIndex - cfg.preloadCount)
    return allData.slice(actualStartIndex, endIndex)
  }, [allData, startIndex, zoomLevel, cfg])

  const totalCount = allData.length
  const currentStartIndex = Math.max(0, startIndex - cfg.preloadCount)

  const scrollToIndex = useCallback((index: number) => {
    const maxStart = Math.max(0, totalCount - Math.floor(cfg.visibleCount / zoomLevel))
    setStartIndex(Math.min(Math.max(0, index), maxStart))
  }, [totalCount, cfg.visibleCount, zoomLevel])

  const scrollToLatest = useCallback(() => {
    const visibleCount = Math.floor(cfg.visibleCount / zoomLevel)
    scrollToIndex(totalCount - visibleCount)
  }, [scrollToIndex, totalCount, cfg.visibleCount, zoomLevel])

  const zoom = useCallback((direction: 'in' | 'out') => {
    setZoomLevel(prev => direction === 'in' ? Math.min(prev * 1.2, 5) : Math.max(prev / 1.2, 0.5))
  }, [])

  const handleDataZoom = useCallback((params: { start: number; end: number }) => {
    const newStartIndex = Math.floor((params.start / 100) * totalCount)
    setStartIndex(newStartIndex)
  }, [totalCount])

  const progress = totalCount > 0 ? (startIndex / totalCount) * 100 : 0

  return {
    visibleData,
    totalCount,
    currentStartIndex,
    zoomLevel,
    progress,
    scrollToIndex,
    scrollToLatest,
    zoom,
    handleDataZoom,
    containerRef,
  }
}

export function useVirtualScroll<T>(items: T[], itemHeight: number, containerHeight: number) {
  const [scrollTop, setScrollTop] = useState(0)

  const visibleRange = useMemo(() => {
    const start = Math.floor(scrollTop / itemHeight)
    const visibleCount = Math.ceil(containerHeight / itemHeight)
    const end = Math.min(start + visibleCount + 2, items.length)
    return { start, end }
  }, [scrollTop, itemHeight, containerHeight, items.length])

  const visibleItems = useMemo(() => {
    return items.slice(visibleRange.start, visibleRange.end).map((item, i) => ({
      item,
      index: visibleRange.start + i,
    }))
  }, [items, visibleRange])

  const totalHeight = items.length * itemHeight
  const offsetY = visibleRange.start * itemHeight

  const handleScroll = useCallback((e: React.UIEvent<HTMLElement>) => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  const scrollToIndex = useCallback((index: number) => {
    const element = document.querySelector(`[data-index="${index}"]`)
    element?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [])

  return { visibleItems, totalHeight, offsetY, handleScroll, scrollToIndex, visibleRange }
}

export function useChartPerformance() {
  const frameCount = useRef(0)
  const lastTime = useRef(performance.now())
  const fps = useRef(60)

  // Note: FPS monitoring is informational only, no side effects needed
  void frameCount
  void lastTime
  void fps

  const getFPS = useCallback(() => fps.current, [])
  return { getFPS }
}

export function sampleData<T>(data: T[], maxPoints: number): T[] {
  if (data.length <= maxPoints) return data
  const step = data.length / maxPoints
  const result: T[] = []
  for (let i = 0; i < maxPoints; i++) {
    const index = Math.floor(i * step)
    result.push(data[index])
  }
  return result
}

export function aggregateKlineData(data: KlineDataPoint[], targetCount: number): KlineDataPoint[] {
  if (data.length <= targetCount) return data
  const groupSize = Math.ceil(data.length / targetCount)
  const result: KlineDataPoint[] = []

  for (let i = 0; i < data.length; i += groupSize) {
    const group = data.slice(i, i + groupSize)
    if (group.length > 0) {
      result.push({
        date: group[0].date,
        open: group[0].open,
        close: group[group.length - 1].close,
        low: Math.min(...group.map(d => d.low)),
        high: Math.max(...group.map(d => d.high)),
        volume: group.reduce((sum, d) => sum + d.volume, 0),
      })
    }
  }
  return result
}

export default { useLazyKlineData, useVirtualScroll, useChartPerformance, sampleData, aggregateKlineData }
