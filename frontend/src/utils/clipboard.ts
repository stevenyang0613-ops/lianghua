/**
 * 剪贴板增强工具
 * 富文本复制，图片复制，历史记录
 */

interface ClipboardHistoryItem {
  id: string
  type: 'text' | 'image' | 'html'
  content: string
  timestamp: number
}

class ClipboardManager {
  private history: ClipboardHistoryItem[] = []
  private maxHistory = 20

  /**
   * 复制文本
   */
  async copyText(text: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(text)
      this.addToHistory('text', text)
      return true
    } catch (error) {
      // 降级方案
      return this.fallbackCopy(text)
    }
  }

  /**
   * 复制富文本 HTML
   */
  async copyHTML(html: string, plainText?: string): Promise<boolean> {
    try {
      const blob = new Blob([html], { type: 'text/html' })
      const plainBlob = new Blob([plainText || this.stripHtml(html)], { type: 'text/plain' })
      const data = [new ClipboardItem({ 'text/html': blob, 'text/plain': plainBlob })]
      await navigator.clipboard.write(data)
      this.addToHistory('html', html)
      return true
    } catch (error) {
      // 降级到纯文本
      return this.copyText(plainText || this.stripHtml(html))
    }
  }

  /**
   * 复制图片
   */
  async copyImage(imageUrl: string): Promise<boolean> {
    try {
      const response = await fetch(imageUrl)
      if (!response.ok) {
        console.error('Failed to fetch image:', response.status)
        return false
      }
      const blob = await response.blob()

      if (blob.type.startsWith('image/')) {
        const data = [new ClipboardItem({ [blob.type]: blob })]
        await navigator.clipboard.write(data)
        this.addToHistory('image', imageUrl)
        return true
      }
      return false
    } catch (error) {
      console.error('Failed to copy image:', error)
      return false
    }
  }

  /**
   * 复制 Canvas 图片
   */
  async copyCanvas(canvas: HTMLCanvasElement): Promise<boolean> {
    return new Promise((resolve) => {
      canvas.toBlob(async (blob) => {
        if (blob) {
          try {
            const data = [new ClipboardItem({ 'image/png': blob })]
            await navigator.clipboard.write(data)
            this.addToHistory('image', canvas.toDataURL())
            resolve(true)
          } catch (error) {
            resolve(false)
          }
        } else {
          resolve(false)
        }
      })
    })
  }

  /**
   * 读取剪贴板文本
   */
  async readText(): Promise<string> {
    try {
      return await navigator.clipboard.readText()
    } catch (error) {
      console.error('Failed to read clipboard:', error)
      return ''
    }
  }

  /**
   * 读取剪贴板图片
   */
  async readImage(): Promise<HTMLImageElement | null> {
    try {
      const items = await navigator.clipboard.read()
      for (const item of items) {
        const imageType = item.types.find(type => type.startsWith('image/'))
        if (imageType) {
          const blob = await item.getType(imageType)
          const url = URL.createObjectURL(blob)
          const img = new Image()
          img.src = url
          await new Promise((resolve, reject) => {
            img.onload = resolve
            img.onerror = reject
          })
          return img
        }
      }
      return null
    } catch (error) {
      console.error('Failed to read image from clipboard:', error)
      return null
    }
  }

  /**
   * 降级复制方案
   */
  private fallbackCopy(text: string): boolean {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()

    try {
      document.execCommand('copy')
      this.addToHistory('text', text)
      return true
    } catch (error) {
      return false
    } finally {
      document.body.removeChild(textarea)
    }
  }

  /**
   * 去除 HTML 标签
   */
  private stripHtml(html: string): string {
    const tmp = document.createElement('div')
    tmp.innerHTML = html
    return tmp.textContent || tmp.innerText || ''
  }

  /**
   * 添加到历史记录
   */
  private addToHistory(type: ClipboardHistoryItem['type'], content: string): void {
    const item: ClipboardHistoryItem = {
      id: `clip_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      type,
      content,
      timestamp: Date.now(),
    }

    this.history.unshift(item)

    if (this.history.length > this.maxHistory) {
      this.history.pop()
    }
  }

  /**
   * 获取历史记录
   */
  getHistory(): ClipboardHistoryItem[] {
    return [...this.history]
  }

  /**
   * 清除历史记录
   */
  clearHistory(): void {
    this.history = []
  }

  /**
   * 从历史记录粘贴
   */
  async pasteFromHistory(id: string): Promise<boolean> {
    const item = this.history.find(h => h.id === id)
    if (!item) return false

    switch (item.type) {
      case 'text':
        return this.copyText(item.content)
      case 'html':
        return this.copyHTML(item.content)
      case 'image':
        return this.copyImage(item.content)
      default:
        return false
    }
  }

  /**
   * 复制表格数据（Excel 格式）
   */
  copyTable(data: Array<Array<string | number>>): Promise<boolean> {
    const tsv = data.map(row => row.join('\t')).join('\n')
    return this.copyText(tsv)
  }

  /**
   * 复制 JSON 对象
   */
  copyJSON(obj: unknown, pretty = true): Promise<boolean> {
    const json = JSON.stringify(obj, null, pretty ? 2 : undefined)
    return this.copyText(json)
  }
}

// 导出单例
export const clipboard = new ClipboardManager()

/**
 * 复制文本快捷方法
 */
export const copyToClipboard = (text: string): Promise<boolean> => clipboard.copyText(text)

/**
 * 复制富文本
 */
export const copyHTML = (html: string, plainText?: string): Promise<boolean> => 
  clipboard.copyHTML(html, plainText)

/**
 * 复制图片
 */
export const copyImage = (imageUrl: string): Promise<boolean> => clipboard.copyImage(imageUrl)

export default clipboard
