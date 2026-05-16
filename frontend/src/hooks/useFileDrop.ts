/**
 * 文件拖放 Hook
 * 拖放上传，文件类型验证，拖放预览
 */

import { useEffect, useRef, useState, useCallback } from 'react'

export interface DroppedFile {
  file: File
  id: string
  preview?: string
  progress?: number
  error?: string
}

export interface UseFileDropOptions {
  accept?: string[] // 接受的文件类型，如 ['image/*', '.pdf']
  maxSize?: number // 最大文件大小（字节）
  maxFiles?: number // 最大文件数量
  multiple?: boolean // 是否允许多文件
  onDrop?: (files: DroppedFile[]) => void
  onError?: (error: string) => void
  onDragEnter?: () => void
  onDragLeave?: () => void
}

export function useFileDrop(options: UseFileDropOptions = {}) {
  const {
    accept = [],
    maxSize = 10 * 1024 * 1024, // 10MB
    maxFiles = 10,
    multiple = true,
    onDrop,
    onError,
    onDragEnter,
    onDragLeave,
  } = options

  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState<DroppedFile[]>([])
  const dropRef = useRef<HTMLDivElement>(null)
  const dragCounterRef = useRef(0)

  /**
   * 验证文件类型
   */
  const validateFileType = useCallback((file: File): boolean => {
    if (accept.length === 0) return true

    const fileType = file.type
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase()

    return accept.some(accepted => {
      if (accepted.startsWith('.')) {
        return fileExtension === accepted.toLowerCase()
      }
      if (accepted.endsWith('/*')) {
        const baseType = accepted.slice(0, -2)
        return fileType.startsWith(baseType)
      }
      return fileType === accepted
    })
  }, [accept])

  /**
   * 验证文件大小
   */
  const validateFileSize = useCallback((file: File): boolean => {
    return file.size <= maxSize
  }, [maxSize])

  /**
   * 生成文件预览
   */
  const generatePreview = useCallback((file: File): string | undefined => {
    if (file.type.startsWith('image/')) {
      return URL.createObjectURL(file)
    }
    return undefined
  }, [])

  /**
   * 处理文件
   */
  const processFiles = useCallback((fileList: FileList): DroppedFile[] => {
    const validFiles: DroppedFile[] = []
    const errors: string[] = []

    const filesToProcess = multiple ? Array.from(fileList) : [fileList[0]]

    for (const file of filesToProcess) {
      // 验证文件数量
      if (validFiles.length >= maxFiles) {
        errors.push(`最多只能上传 ${maxFiles} 个文件`)
        break
      }

      // 验证文件类型
      if (!validateFileType(file)) {
        errors.push(`文件 "${file.name}" 类型不支持`)
        continue
      }

      // 验证文件大小
      if (!validateFileSize(file)) {
        errors.push(`文件 "${file.name}" 超过 ${maxSize / 1024 / 1024}MB 限制`)
        continue
      }

      validFiles.push({
        file,
        id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
        preview: generatePreview(file),
        progress: 0,
      })
    }

    if (errors.length > 0) {
      onError?.(errors.join('\n'))
    }

    return validFiles
  }, [multiple, maxFiles, validateFileType, validateFileSize, maxSize, generatePreview, onError])

  /**
   * 拖拽进入
   */
  const handleDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()

    dragCounterRef.current++
    if (dragCounterRef.current === 1) {
      setIsDragging(true)
      onDragEnter?.()
    }
  }, [onDragEnter])

  /**
   * 拖拽离开
   */
  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()

    dragCounterRef.current--
    if (dragCounterRef.current === 0) {
      setIsDragging(false)
      onDragLeave?.()
    }
  }, [onDragLeave])

  /**
   * 拖拽悬停
   */
  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }, [])

  /**
   * 放下文件
   */
  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()

    dragCounterRef.current = 0
    setIsDragging(false)

    const droppedFiles = e.dataTransfer?.files
    if (!droppedFiles || droppedFiles.length === 0) return

    const processedFiles = processFiles(droppedFiles)
    if (processedFiles.length > 0) {
      setFiles(prev => [...prev, ...processedFiles])
      onDrop?.(processedFiles)
    }
  }, [processFiles, onDrop])

  /**
   * 点击选择文件
   */
  const openFileDialog = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = multiple
    if (accept.length > 0) {
      input.accept = accept.join(',')
    }

    input.onchange = (e) => {
      const target = e.target as HTMLInputElement
      if (target.files && target.files.length > 0) {
        const processedFiles = processFiles(target.files)
        if (processedFiles.length > 0) {
          setFiles(prev => [...prev, ...processedFiles])
          onDrop?.(processedFiles)
        }
      }
    }

    input.click()
  }, [multiple, accept, processFiles, onDrop])

  /**
   * 移除文件
   */
  const removeFile = useCallback((id: string) => {
    setFiles(prev => {
      const file = prev.find(f => f.id === id)
      if (file?.preview) {
        URL.revokeObjectURL(file.preview)
      }
      return prev.filter(f => f.id !== id)
    })
  }, [])

  /**
   * 清空所有文件
   */
  const clearFiles = useCallback(() => {
    files.forEach(file => {
      if (file.preview) {
        URL.revokeObjectURL(file.preview)
      }
    })
    setFiles([])
  }, [files])

  /**
   * 更新文件进度
   */
  const updateProgress = useCallback((id: string, progress: number) => {
    setFiles(prev => prev.map(f => f.id === id ? { ...f, progress } : f))
  }, [])

  /**
   * 设置文件错误
   */
  const setFileError = useCallback((id: string, error: string) => {
    setFiles(prev => prev.map(f => f.id === id ? { ...f, error } : f))
  }, [])

  // 绑定事件
  useEffect(() => {
    const element = dropRef.current
    if (!element) return

    element.addEventListener('dragenter', handleDragEnter)
    element.addEventListener('dragleave', handleDragLeave)
    element.addEventListener('dragover', handleDragOver)
    element.addEventListener('drop', handleDrop)

    return () => {
      element.removeEventListener('dragenter', handleDragEnter)
      element.removeEventListener('dragleave', handleDragLeave)
      element.removeEventListener('dragover', handleDragOver)
      element.removeEventListener('drop', handleDrop)
    }
  }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop])

  // 清理预览 URL
  useEffect(() => {
    return () => {
      files.forEach(file => {
        if (file.preview) {
          URL.revokeObjectURL(file.preview)
        }
      })
    }
  }, [])

  return {
    dropRef,
    isDragging,
    files,
    openFileDialog,
    removeFile,
    clearFiles,
    updateProgress,
    setFileError,
  }
}

export default useFileDrop
