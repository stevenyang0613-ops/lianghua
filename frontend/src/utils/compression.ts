/**
 * 数据压缩工具
 * 使用LZString压缩缓存数据以节省存储空间
 */

// 简单的LZ风格压缩实现（轻量级，无需外部依赖）
const LZString = {
  compress: function (input: string): string {
    if (!input || input.length === 0) return ''

    const dictionary: { [key: string]: number } = {}
    const data = (input + '').split('')
    const result: string[] = []
    const currentChar = data[0]
    let phrase = currentChar
    let code = 256

    for (let i = 1; i < data.length; i++) {
      const nextChar = data[i]
      if (dictionary[phrase + nextChar] !== undefined) {
        phrase += nextChar
      } else {
        result.push(phrase.length > 1 ? String.fromCharCode(dictionary[phrase]) : String(phrase.charCodeAt(0)))
        dictionary[phrase + nextChar] = code++
        phrase = nextChar
      }
    }

    result.push(phrase.length > 1 ? String.fromCharCode(dictionary[phrase]) : String(phrase.charCodeAt(0)))

    return result.join('')
  },

  decompress: function (compressed: string): string {
    if (!compressed || compressed.length === 0) return ''

    const dictionary: { [key: number]: string } = {}
    const data = (compressed + '').split('')
    let currentChar = data[0]
    let oldPhrase = currentChar
    const result: string[] = [currentChar]
    let code = 256
    let phrase: string

    for (let i = 1; i < data.length; i++) {
      const currCode = data[i].charCodeAt(0)
      if (currCode < 256) {
        phrase = data[i]
      } else {
        phrase = dictionary[currCode] ? dictionary[currCode] : oldPhrase + currentChar
      }

      result.push(phrase)
      currentChar = phrase.charAt(0)
      dictionary[code++] = oldPhrase + currentChar
      oldPhrase = phrase
    }

    return result.join('')
  }
}

// 压缩JSON数据
export function compressJSON(data: unknown): string {
  try {
    const jsonString = JSON.stringify(data)
    return LZString.compress(jsonString)
  } catch (error) {
    console.error('[Compression] Failed to compress:', error)
    return JSON.stringify(data)
  }
}

// 解压JSON数据
export function decompressJSON<T>(compressed: string): T | null {
  try {
    const decompressed = LZString.decompress(compressed)
    if (!decompressed) return null
    return JSON.parse(decompressed) as T
  } catch (error) {
    // 尝试直接解析（可能未压缩）
    try {
      return JSON.parse(compressed) as T
    } catch {
      console.error('[Compression] Failed to decompress:', error)
      return null
    }
  }
}

// 计算压缩率
export function getCompressionRatio(original: unknown): {
  originalSize: number
  compressedSize: number
  ratio: number
} {
  const jsonString = JSON.stringify(original)
  const compressed = LZString.compress(jsonString)

  return {
    originalSize: new Blob([jsonString]).size,
    compressedSize: new Blob([compressed]).size,
    ratio: Math.round((1 - (new Blob([compressed]).size / new Blob([jsonString]).size)) * 100),
  }
}

// 检查数据是否需要压缩
export function shouldCompress(data: unknown): boolean {
  const jsonString = JSON.stringify(data)
  const size = new Blob([jsonString]).size
  return size > 1024 // 大于1KB才压缩
}

// 带压缩的存储
export function setCompressedItem(key: string, data: unknown): void {
  try {
    if (shouldCompress(data)) {
      const compressed = compressJSON(data)
      localStorage.setItem(`compressed_${key}`, compressed)
    } else {
      localStorage.setItem(key, JSON.stringify(data))
    }
  } catch (error) {
    console.error('[Compression] Failed to store:', error)
  }
}

// 带解压的读取
export function getCompressedItem<T>(key: string): T | null {
  try {
    // 先尝试读取压缩数据
    const compressed = localStorage.getItem(`compressed_${key}`)
    if (compressed) {
      return decompressJSON<T>(compressed)
    }

    // 回退到普通数据
    const normal = localStorage.getItem(key)
    if (normal) {
      return JSON.parse(normal) as T
    }

    return null
  } catch (error) {
    console.error('[Compression] Failed to read:', error)
    return null
  }
}

// 获取存储统计
export function getStorageStats(): {
  totalKeys: number
  compressedKeys: number
  estimatedSize: number
  estimatedSavings: number
} {
  let totalKeys = 0
  let compressedKeys = 0
  let estimatedSize = 0
  let estimatedSavings = 0

  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key) continue

    totalKeys++
    const value = localStorage.getItem(key) || ''
    estimatedSize += value.length

    if (key.startsWith('compressed_')) {
      compressedKeys++
      // 估算节省的空间（压缩数据大约是原大小的60-70%）
      estimatedSavings += value.length * 0.4
    }
  }

  return {
    totalKeys,
    compressedKeys,
    estimatedSize: Math.round(estimatedSize / 1024), // KB
    estimatedSavings: Math.round(estimatedSavings / 1024), // KB
  }
}

export default {
  compressJSON,
  decompressJSON,
  getCompressionRatio,
  shouldCompress,
  setCompressedItem,
  getCompressedItem,
  getStorageStats,
}
