/**
 * 数据压缩传输工具
 * 减少网络带宽，提升传输效率
 */

// 检测是否支持 CompressionStream
const supportsCompression = typeof CompressionStream !== 'undefined'

/**
 * 压缩数据
 */
export async function compress(data: string): Promise<Uint8Array | string> {
  if (!supportsCompression) {
    // 不支持压缩，返回原始数据
    return data
  }

  try {
    const stream = new CompressionStream('gzip')
    const writer = stream.writable.getWriter()
    const reader = stream.readable.getReader()

    // 写入数据
    writer.write(new TextEncoder().encode(data))
    writer.close()

    // 读取压缩结果
    const chunks: Uint8Array[] = []
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      chunks.push(value)
    }

    // 合并所有块
    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    const result = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of chunks) {
      result.set(chunk, offset)
      offset += chunk.length
    }

    return result
  } catch (error) {
    console.error('[Compression] Compress failed:', error)
    return data
  }
}

/**
 * 解压数据
 */
export async function decompress(data: Uint8Array | ArrayBuffer): Promise<string> {
  if (!supportsCompression) {
    // 不支持解压，尝试直接解码
    return new TextDecoder().decode(data)
  }

  try {
    const stream = new DecompressionStream('gzip')
    const writer = stream.writable.getWriter()
    const reader = stream.readable.getReader()

    // 写入压缩数据
    writer.write(new Uint8Array(data))
    writer.close()

    // 读取解压结果
    const chunks: Uint8Array[] = []
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      chunks.push(value)
    }

    // 合并所有块
    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    const result = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of chunks) {
      result.set(chunk, offset)
      offset += chunk.length
    }

    return new TextDecoder().decode(result)
  } catch (error) {
    console.error('[Compression] Decompress failed:', error)
    // 尝试直接解码
    return new TextDecoder().decode(data)
  }
}

/**
 * 压缩 JSON 对象
 */
export async function compressJSON<T>(data: T): Promise<Uint8Array | string> {
  const jsonString = JSON.stringify(data)
  return compress(jsonString)
}

/**
 * 解压 JSON 对象
 */
export async function decompressJSON<T>(data: Uint8Array | ArrayBuffer): Promise<T> {
  const jsonString = await decompress(data)
  return JSON.parse(jsonString)
}

/**
 * 计算压缩率
 */
export function getCompressionRatio(original: string, compressed: Uint8Array): number {
  const originalSize = new TextEncoder().encode(original).length
  const compressedSize = compressed.length
  return (1 - compressedSize / originalSize) * 100
}

/**
 * 简单的 Run-Length Encoding 压缩
 * 适用于连续重复数据
 */
export function rleEncode(data: number[]): Uint8Array {
  const result: number[] = []
  let i = 0

  while (i < data.length) {
    let count = 1
    while (i + count < data.length && data[i + count] === data[i]) {
      count++
    }

    // 如果重复次数大于等于3，使用 RLE 编码
    if (count >= 3) {
      result.push(data[i], data[i], data[i], count) // 使用3个相同值 + 计数
      i += count
    } else {
      result.push(data[i])
      i++
    }
  }

  return new Uint8Array(result)
}

/**
 * RLE 解码
 */
export function rleDecode(data: Uint8Array): number[] {
  const result: number[] = []
  let i = 0

  while (i < data.length) {
    // 检测是否有连续3个相同值
    if (i + 3 < data.length && data[i] === data[i + 1] && data[i] === data[i + 2]) {
      const value = data[i]
      const count = data[i + 3]
      for (let j = 0; j < count; j++) {
        result.push(value)
      }
      i += 4
    } else {
      result.push(data[i])
      i++
    }
  }

  return result
}

/**
 * Delta 编码
 * 适用于数值序列，只存储差值
 */
export function deltaEncode(data: number[]): Int16Array {
  if (data.length === 0) return new Int16Array(0)

  const result = new Int16Array(data.length)
  result[0] = data[0]

  for (let i = 1; i < data.length; i++) {
    result[i] = data[i] - data[i - 1]
  }

  return result
}

/**
 * Delta 解码
 */
export function deltaDecode(data: Int16Array): number[] {
  if (data.length === 0) return []

  const result: number[] = [data[0]]

  for (let i = 1; i < data.length; i++) {
    result.push(result[i - 1] + data[i])
  }

  return result
}

/**
 * 混合压缩策略
 * 根据数据类型自动选择最佳压缩方式
 */
export async function smartCompress(data: unknown): Promise<{
  compressed: Uint8Array | string
  method: 'gzip' | 'delta' | 'rle' | 'none'
  originalSize: number
  compressedSize: number
}> {
  const jsonString = JSON.stringify(data)
  const originalSize = new TextEncoder().encode(jsonString).length

  // 检查是否是数值数组
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'number') {
    // 尝试 Delta 编码
    const deltaEncoded = deltaEncode(data as number[])
    const deltaCompressed = await compress(String.fromCharCode(...new Uint8Array(deltaEncoded.buffer)))
    
    if (deltaCompressed instanceof Uint8Array && deltaCompressed.length < originalSize * 0.5) {
      return {
        compressed: deltaCompressed,
        method: 'delta',
        originalSize,
        compressedSize: deltaCompressed.length,
      }
    }
  }

  // 尝试 GZIP 压缩
  const gzipped = await compress(jsonString)
  
  if (gzipped instanceof Uint8Array && gzipped.length < originalSize * 0.9) {
    return {
      compressed: gzipped,
      method: 'gzip',
      originalSize,
      compressedSize: gzipped.length,
    }
  }

  // 不压缩
  return {
    compressed: jsonString,
    method: 'none',
    originalSize,
    compressedSize: originalSize,
  }
}

/**
 * 压缩统计
 */
export interface CompressionStats {
  totalRequests: number
  compressedRequests: number
  totalOriginalBytes: number
  totalCompressedBytes: number
  averageRatio: number
}

class CompressionTracker {
  private stats = {
    totalRequests: 0,
    compressedRequests: 0,
    totalOriginalBytes: 0,
    totalCompressedBytes: 0,
  }

  track(originalSize: number, compressedSize: number): void {
    this.stats.totalRequests++
    this.stats.totalOriginalBytes += originalSize
    this.stats.totalCompressedBytes += compressedSize

    if (compressedSize < originalSize) {
      this.stats.compressedRequests++
    }
  }

  getStats(): CompressionStats {
    return {
      ...this.stats,
      averageRatio: this.stats.totalOriginalBytes > 0
        ? (1 - this.stats.totalCompressedBytes / this.stats.totalOriginalBytes) * 100
        : 0,
    }
  }

  reset(): void {
    this.stats = {
      totalRequests: 0,
      compressedRequests: 0,
      totalOriginalBytes: 0,
      totalCompressedBytes: 0,
    }
  }
}

export const compressionTracker = new CompressionTracker()

export default {
  compress,
  decompress,
  compressJSON,
  decompressJSON,
  getCompressionRatio,
  rleEncode,
  rleDecode,
  deltaEncode,
  deltaDecode,
  smartCompress,
  compressionTracker,
}
