/**
 * 图片懒加载 Hook
 * IntersectionObserver 实现懒加载，支持占位符和渐进加载
 */

import { useEffect, useRef, useState, useCallback } from 'react'

interface UseLazyImageOptions {
  threshold?: number
  rootMargin?: string
  placeholder?: string
  fadeIn?: boolean
  fadeInDuration?: number
  onError?: (error: Error) => void
}

interface LazyImageState {
  src: string | null
  isLoading: boolean
  hasError: boolean
  isIntersecting: boolean
}

/**
 * 懒加载图片 Hook
 */
export function useLazyImage(
  src: string,
  options: UseLazyImageOptions = {}
): {
  ref: React.RefObject<HTMLImageElement>
  state: LazyImageState
  onLoad: () => void
  onError: () => void
} {
  const {
    threshold = 0.1,
    rootMargin = '50px',
    placeholder,
    fadeIn = true,
    fadeInDuration = 300,
    onError: onErrorCallback,
  } = options

  const imgRef = useRef<HTMLImageElement>(null)
  const observerRef = useRef<IntersectionObserver | null>(null)

  const [state, setState] = useState<LazyImageState>({
    src: placeholder || null,
    isLoading: false,
    hasError: false,
    isIntersecting: false,
  })

  // 加载图片
  const loadImage = useCallback(() => {
    if (state.isLoading || state.src === src) return

    setState(prev => ({ ...prev, isLoading: true }))

    const img = new Image()
    img.src = src

    img.onload = () => {
      setState(prev => ({
        ...prev,
        src,
        isLoading: false,
        hasError: false,
      }))

      // 淡入效果
      if (fadeIn && imgRef.current) {
        imgRef.current.style.opacity = '0'
        imgRef.current.style.transition = `opacity ${fadeInDuration}ms ease-in-out`
        requestAnimationFrame(() => {
          if (imgRef.current) {
            imgRef.current.style.opacity = '1'
          }
        })
      }
    }

    img.onerror = () => {
      setState(prev => ({
        ...prev,
        isLoading: false,
        hasError: true,
      }))
      onErrorCallback?.(new Error(`Failed to load image: ${src}`))
    }
  }, [src, state.isLoading, state.src, fadeIn, fadeInDuration, onErrorCallback])

  // 设置 IntersectionObserver
  useEffect(() => {
    const element = imgRef.current
    if (!element) return

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setState(prev => ({ ...prev, isIntersecting: true }))
            loadImage()
            observerRef.current?.disconnect()
          }
        }
      },
      {
        threshold,
        rootMargin,
      }
    )

    observerRef.current.observe(element)

    return () => {
      observerRef.current?.disconnect()
    }
  }, [threshold, rootMargin, loadImage])

  const handleLoad = useCallback(() => {
    // 图片加载完成回调
  }, [])

  const handleError = useCallback(() => {
    onErrorCallback?.(new Error(`Failed to load image: ${src}`))
  }, [src, onErrorCallback])

  return {
    ref: imgRef,
    state,
    onLoad: handleLoad,
    onError: handleError,
  }
}

/**
 * 批量懒加载图片 Hook
 */
export function useLazyImages(
  images: Array<{ src: string; id: string }>,
  options: UseLazyImageOptions = {}
): Map<string, LazyImageState> {
  const [states, setStates] = useState<Map<string, LazyImageState>>(new Map())
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const img = entry.target as HTMLImageElement
            const src = img.dataset.src
            const id = img.dataset.id

            if (src && id) {
              const actualImg = new Image()
              actualImg.src = src
              actualImg.onload = () => {
                setStates(prev => {
                  const newStates = new Map(prev)
                  newStates.set(id, {
                    src,
                    isLoading: false,
                    hasError: false,
                    isIntersecting: true,
                  })
                  return newStates
                })
              }
            }
            observer.unobserve(img)
          }
        }
      },
      {
        threshold: options.threshold || 0.1,
        rootMargin: options.rootMargin || '50px',
      }
    )

    const imgElements = container.querySelectorAll('img[data-src]')
    imgElements.forEach(img => observer.observe(img))

    return () => observer.disconnect()
  }, [images, options.threshold, options.rootMargin])

  return states
}

/**
 * 渐进式图片加载组件
 */
export interface ProgressiveImageProps {
  src: string
  thumbnail?: string
  alt?: string
  width?: number | string
  height?: number | string
  className?: string
  style?: React.CSSProperties
  blur?: boolean
}

export function useProgressiveImage(src: string, thumbnail?: string): {
  currentSrc: string | null
  isLoading: boolean
  blur: boolean
} {
  const [currentSrc, setCurrentSrc] = useState<string | null>(thumbnail || null)
  const [isLoading, setIsLoading] = useState(false)
  const [blur, setBlur] = useState(!!thumbnail)

  useEffect(() => {
    if (!src) return

    let blurTimer: ReturnType<typeof setTimeout> | null = null
    const isMounted = { current: true }

    setIsLoading(true)

    const img = new Image()
    img.src = src

    img.onload = () => {
      if (!isMounted.current) return
      setCurrentSrc(src)
      setIsLoading(false)
      // 渐进淡出模糊效果
      if (thumbnail) {
        blurTimer = setTimeout(() => {
          if (isMounted.current) setBlur(false)
        }, 100)
      }
    }

    img.onerror = () => {
      if (!isMounted.current) return
      setIsLoading(false)
    }

    return () => {
      isMounted.current = false
      if (blurTimer) clearTimeout(blurTimer)
    }
  }, [src, thumbnail])

  return { currentSrc, isLoading, blur }
}

export default useLazyImage
