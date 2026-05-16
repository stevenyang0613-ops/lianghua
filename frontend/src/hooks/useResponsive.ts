import { useState, useEffect, useCallback, useRef } from 'react'

const breakpoints = { xs: 480, sm: 576, md: 768, lg: 992, xl: 1200 }

export function useResponsive() {
  const [windowSize, setWindowSize] = useState({
    width: typeof window !== 'undefined' ? window.innerWidth : 1200,
    height: typeof window !== 'undefined' ? window.innerHeight : 800,
  })

  useEffect(() => {
    const handleResize = () => {
      setWindowSize({ width: window.innerWidth, height: window.innerHeight })
    }
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  return {
    ...windowSize,
    isMobile: windowSize.width < breakpoints.md,
    isTablet: windowSize.width >= breakpoints.sm && windowSize.width < breakpoints.lg,
    isDesktop: windowSize.width >= breakpoints.lg,
  }
}

export function useTouch() {
  const [isTouch, setIsTouch] = useState(false)
  useEffect(() => {
    setIsTouch('ontouchstart' in window || navigator.maxTouchPoints > 0)
  }, [])
  return { isTouch }
}

export function useHapticFeedback() {
  const isSupported = typeof navigator !== 'undefined' && 'vibrate' in navigator
  const vibrate = useCallback((pattern: number | number[] = 10) => {
    if (isSupported) navigator.vibrate(pattern)
  }, [isSupported])
  const light = useCallback(() => vibrate(10), [vibrate])
  return { isSupported, vibrate, light }
}

export function useLongPress(callback: () => void, options: { delay?: number } = {}) {
  const timeoutRef = useRef<NodeJS.Timeout>()
  const delay = options.delay || 500
  const start = useCallback(() => {
    timeoutRef.current = setTimeout(callback, delay)
  }, [callback, delay])
  const clear = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
  }, [])
  return {
    onMouseDown: start, onMouseUp: clear, onMouseLeave: clear,
    onTouchStart: start, onTouchEnd: clear,
  }
}
