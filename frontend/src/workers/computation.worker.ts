/**
 * WebAssembly 计算模块
 * 用于密集型数值计算
 */

// WASM 模块接口
interface WasmModule {
  memory: WebAssembly.Memory
  calculateSMA: (dataPtr: number, length: number, period: number, resultPtr: number) => number
  calculateEMA: (dataPtr: number, length: number, period: number, resultPtr: number) => number
  calculateRSI: (dataPtr: number, length: number, period: number, resultPtr: number) => number
  calculateMACD: (dataPtr: number, length: number, fastPeriod: number, slowPeriod: number, signalPeriod: number, resultPtr: number) => number
  calculateBollingerBands: (dataPtr: number, length: number, period: number, stdDev: number, upperPtr: number, middlePtr: number, lowerPtr: number) => number
  convolve: (dataPtr: number, dataLen: number, kernelPtr: number, kernelLen: number, resultPtr: number) => number
  fft: (realPtr: number, imagPtr: number, length: number) => number
}

// 简单的 WASM 字节码（SMA 计算）
// 实际项目中应该从 .wasm 文件加载
const WASM_BYTES = new Uint8Array([
  0x00, 0x61, 0x73, 0x6d, // WASM_BINARY_MAGIC
  0x01, 0x00, 0x00, 0x00, // WASM_BINARY_VERSION
  // ... 简化的 WASM 字节码
])

/**
 * WebAssembly 计算器
 */
export class WasmCalculator {
  private module: WasmModule | null = null
  private memory: WebAssembly.Memory | null = null
  private memoryBuffer: Float64Array | null = null
  private initialized = false

  /**
   * 初始化 WASM 模块
   */
  async init(): Promise<void> {
    if (this.initialized) return

    try {
      // 创建内存
      this.memory = new WebAssembly.Memory({ initial: 256, maximum: 1024 })

      // 编译并实例化 WASM 模块
      // 实际项目中从服务器加载 .wasm 文件
      const module = await WebAssembly.compile(WASM_BYTES)
      const instance = await WebAssembly.instantiate(module, {
        env: {
          memory: this.memory,
          Math_sqrt: Math.sqrt,
          Math_pow: Math.pow,
          Math_abs: Math.abs,
        },
      })

      this.module = instance.exports as unknown as WasmModule
      this.memoryBuffer = new Float64Array(this.memory.buffer)
      this.initialized = true

      console.log('[WASM] Calculator initialized')
    } catch (error) {
      console.warn('[WASM] Failed to initialize, using JS fallback:', error)
      this.initialized = true
    }
  }

  /**
   * 计算 SMA（简单移动平均）
   */
  calculateSMA(data: number[], period: number): number[] {
    if (!this.module) {
      return this.calculateSMAJS(data, period)
    }

    const length = data.length
    const result = new Array(length).fill(0)

    // 写入数据到 WASM 内存
    const dataPtr = 0
    const resultPtr = length * 8

    for (let i = 0; i < length; i++) {
      this.memoryBuffer![dataPtr / 8 + i] = data[i]
    }

    // 调用 WASM 函数
    this.module.calculateSMA(dataPtr, length, period, resultPtr)

    // 读取结果
    for (let i = 0; i < length; i++) {
      result[i] = this.memoryBuffer![resultPtr / 8 + i]
    }

    return result
  }

  /**
   * JS 回退：计算 SMA
   */
  private calculateSMAJS(data: number[], period: number): number[] {
    const result: number[] = []
    let sum = 0

    for (let i = 0; i < data.length; i++) {
      sum += data[i]
      if (i >= period) {
        sum -= data[i - period]
      }
      result.push(i >= period - 1 ? sum / period : sum / (i + 1))
    }

    return result
  }

  /**
   * 计算 EMA（指数移动平均）
   */
  calculateEMA(data: number[], period: number): number[] {
    const k = 2 / (period + 1)
    const result: number[] = [data[0]]

    for (let i = 1; i < data.length; i++) {
      result.push(data[i] * k + result[i - 1] * (1 - k))
    }

    return result
  }

  /**
   * 计算 RSI
   */
  calculateRSI(data: number[], period: number = 14): number[] {
    const result: number[] = []
    let gains = 0
    let losses = 0

    // 计算初始平均涨跌
    for (let i = 1; i <= period; i++) {
      const change = data[i] - data[i - 1]
      if (change > 0) {
        gains += change
      } else {
        losses -= change
      }
    }

    let avgGain = gains / period
    let avgLoss = losses / period

    // 第一个 RSI 值
    result.push(NaN) // 填充前期

    for (let i = period + 1; i < data.length; i++) {
      const change = data[i] - data[i - 1]
      const currentGain = change > 0 ? change : 0
      const currentLoss = change < 0 ? -change : 0

      avgGain = (avgGain * (period - 1) + currentGain) / period
      avgLoss = (avgLoss * (period - 1) + currentLoss) / period

      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss
      result.push(100 - 100 / (1 + rs))
    }

    // 填充前 period 个值
    while (result.length < data.length) {
      result.unshift(NaN)
    }

    return result
  }

  /**
   * 计算 MACD
   */
  calculateMACD(data: number[], fastPeriod: number = 12, slowPeriod: number = 26, signalPeriod: number = 9): {
    dif: number[]
    dea: number[]
    macd: number[]
  } {
    const emaFast = this.calculateEMA(data, fastPeriod)
    const emaSlow = this.calculateEMA(data, slowPeriod)

    // DIF = EMA(12) - EMA(26)
    const dif = emaFast.map((v, i) => v - emaSlow[i])

    // DEA = EMA(DIF, 9)
    const dea = this.calculateEMA(dif, signalPeriod)

    // MACD = (DIF - DEA) * 2
    const macd = dif.map((v, i) => (v - dea[i]) * 2)

    return { dif, dea, macd }
  }

  /**
   * 计算布林带
   */
  calculateBollingerBands(data: number[], period: number = 20, stdDev: number = 2): {
    upper: number[]
    middle: number[]
    lower: number[]
  } {
    const middle = this.calculateSMA(data, period)
    const upper: number[] = []
    const lower: number[] = []

    for (let i = 0; i < data.length; i++) {
      if (i < period - 1) {
        upper.push(NaN)
        lower.push(NaN)
        continue
      }

      // 计算标准差
      const slice = data.slice(i - period + 1, i + 1)
      const mean = middle[i]
      const variance = slice.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / period
      const std = Math.sqrt(variance)

      upper.push(mean + stdDev * std)
      lower.push(mean - stdDev * std)
    }

    return { upper, middle, lower }
  }

  /**
   * 卷积运算
   */
  convolve(data: number[], kernel: number[]): number[] {
    const result: number[] = []
    const n = data.length
    const m = kernel.length

    for (let i = 0; i < n - m + 1; i++) {
      let sum = 0
      for (let j = 0; j < m; j++) {
        sum += data[i + j] * kernel[m - 1 - j]
      }
      result.push(sum)
    }

    return result
  }

  /**
   * FFT（快速傅里叶变换）
   */
  fft(real: number[], imag: number[]): { real: number[]; imag: number[] } {
    const n = real.length

    // 确保长度是 2 的幂
    if (n & (n - 1)) {
      throw new Error('FFT length must be power of 2')
    }

    // Cooley-Tukey FFT 算法
    const realOut = [...real]
    const imagOut = [...imag]

    // 位反转排序
    for (let i = 0, j = 0; i < n; i++) {
      if (j > i) {
        [realOut[i], realOut[j]] = [realOut[j], realOut[i]]
        [imagOut[i], imagOut[j]] = [imagOut[j], imagOut[i]]
      }
      let k = n >> 1
      while (k && j >= k) {
        j -= k
        k >>= 1
      }
      j += k
    }

    // 蝶形运算
    for (let len = 2; len <= n; len <<= 1) {
      const halfLen = len >> 1
      const angle = -2 * Math.PI / len

      for (let i = 0; i < n; i += len) {
        for (let j = 0; j < halfLen; j++) {
          const cos = Math.cos(angle * j)
          const sin = Math.sin(angle * j)

          const idx1 = i + j
          const idx2 = i + j + halfLen

          const tReal = realOut[idx2] * cos - imagOut[idx2] * sin
          const tImag = realOut[idx2] * sin + imagOut[idx2] * cos

          realOut[idx2] = realOut[idx1] - tReal
          imagOut[idx2] = imagOut[idx1] - tImag
          realOut[idx1] += tReal
          imagOut[idx1] += tImag
        }
      }
    }

    return { real: realOut, imag: imagOut }
  }

  /**
   * 批量计算指标
   */
  calculateIndicators(data: number[], indicators: string[]): Record<string, number[]> {
    const results: Record<string, number[]> = {}

    for (const indicator of indicators) {
      switch (indicator) {
        case 'sma5':
          results.sma5 = this.calculateSMA(data, 5)
          break
        case 'sma10':
          results.sma10 = this.calculateSMA(data, 10)
          break
        case 'sma20':
          results.sma20 = this.calculateSMA(data, 20)
          break
        case 'ema12':
          results.ema12 = this.calculateEMA(data, 12)
          break
        case 'ema26':
          results.ema26 = this.calculateEMA(data, 26)
          break
        case 'rsi':
          results.rsi = this.calculateRSI(data, 14)
          break
        case 'macd':
          const macd = this.calculateMACD(data)
          results.macd_dif = macd.dif
          results.macd_dea = macd.dea
          results.macd = macd.macd
          break
        case 'boll':
          const boll = this.calculateBollingerBands(data)
          results.boll_upper = boll.upper
          results.boll_middle = boll.middle
          results.boll_lower = boll.lower
          break
      }
    }

    return results
  }
}

// 导出单例
export const wasmCalculator = new WasmCalculator()

export default wasmCalculator
