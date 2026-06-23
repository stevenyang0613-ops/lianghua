/**
 * OffscreenCanvas 离屏渲染器
 * 用于复杂图表的后台渲染
 */

export interface ChartConfig {
  width: number
  height: number
  backgroundColor?: string
  padding?: { top: number; right: number; bottom: number; left: number }
}

export interface LineSeries {
  data: number[]
  color: string
  lineWidth?: number
  name?: string
}

export interface CandleData {
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

/**
 * 离屏渲染器
 */
export class OffscreenRenderer {
  private canvas: OffscreenCanvas | HTMLCanvasElement | null = null
  private ctx: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D | null = null
  protected config: ChartConfig
  private worker: Worker | null = null

  constructor(config: ChartConfig) {
    this.config = config
    this.initCanvas()
  }

  /**
   * Safe ctx accessor — throws if canvas context is not initialized.
   */
  private getCtx(): CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D {
    if (!this.ctx) throw new Error('Canvas context not initialized')
    return this.ctx
  }

  /**
   * 初始化画布
   */
  private initCanvas(): void {
    if (typeof OffscreenCanvas !== 'undefined') {
      // 使用 OffscreenCanvas
      this.canvas = new OffscreenCanvas(this.config.width, this.config.height)
      this.ctx = this.canvas.getContext('2d')
    } else {
      // 回退到普通 Canvas
      this.canvas = document.createElement('canvas')
      this.canvas.width = this.config.width
      this.canvas.height = this.config.height
      this.ctx = this.canvas.getContext('2d')
    }

    // 设置背景
    if (this.ctx) {
      this.ctx.fillStyle = this.config.backgroundColor || '#1a1a2e'
      this.ctx.fillRect(0, 0, this.config.width, this.config.height)
    }
  }

  /**
   * 克隆 OffscreenCanvas 内容，避免 transferToImageBitmap 销毁原画布
   */
  private cloneOffscreenCanvas(): OffscreenCanvas {
    if (!this.canvas || !(this.canvas instanceof OffscreenCanvas)) {
      throw new Error('Canvas is not an OffscreenCanvas')
    }
    const clone = new OffscreenCanvas(this.config.width, this.config.height)
    const cloneCtx = clone.getContext('2d')!
    cloneCtx.drawImage(this.canvas as OffscreenCanvas, 0, 0)
    return clone
  }

  /**
   * 渲染折线图
   */
  renderLineChart(series: LineSeries[], options?: {
    showGrid?: boolean
    showAxis?: boolean
    title?: string
  }): ImageBitmap | HTMLCanvasElement {
    const padding = this.config.padding || { top: 40, right: 40, bottom: 40, left: 60 }
    const chartWidth = this.config.width - padding.left - padding.right
    const chartHeight = this.config.height - padding.top - padding.bottom

    // 清除画布
    this.getCtx().fillStyle = this.config.backgroundColor || '#1a1a2e'
    this.getCtx().fillRect(0, 0, this.config.width, this.config.height)

    // 计算数据范围
    let minVal = Infinity
    let maxVal = -Infinity

    for (const s of series) {
      const validData = s.data.filter(v => !isNaN(v))
      minVal = Math.min(minVal, ...validData)
      maxVal = Math.max(maxVal, ...validData)
    }

    const range = maxVal - minVal || 1

    // 绘制网格
    if (options?.showGrid !== false) {
      this.drawGrid(padding, chartWidth, chartHeight, minVal, maxVal)
    }

    // 绘制坐标轴
    if (options?.showAxis !== false) {
      this.drawAxis(padding, chartWidth, chartHeight, minVal, maxVal)
    }

    // 绘制标题
    if (options?.title) {
      this.getCtx().font = '14px sans-serif'
      this.getCtx().fillStyle = '#ffffff'
      this.getCtx().textAlign = 'center'
      this.getCtx().fillText(options.title, this.config.width / 2, 20)
    }

    // 绘制每条线
    for (const s of series) {
      this.drawLine(s, padding, chartWidth, chartHeight, minVal, range)
    }

    // 返回结果（克隆后 transfer，避免销毁原画布）
    if (this.canvas instanceof OffscreenCanvas) {
      return this.cloneOffscreenCanvas().transferToImageBitmap()
    }
    return this.canvas!
  }

  /**
   * 绘制网格
   */
  private drawGrid(
    padding: { top: number; right: number; bottom: number; left: number },
    chartWidth: number,
    chartHeight: number,
    minVal: number,
    maxVal: number
  ): void {
    this.getCtx().strokeStyle = '#2a2a4a'
    this.getCtx().lineWidth = 1

    // 水平网格线
    const hLines = 5
    for (let i = 0; i <= hLines; i++) {
      const y = padding.top + (chartHeight / hLines) * i
      this.getCtx().beginPath()
      this.getCtx().moveTo(padding.left, y)
      this.getCtx().lineTo(padding.left + chartWidth, y)
      this.getCtx().stroke()
    }

    // 垂直网格线
    const vLines = 6
    for (let i = 0; i <= vLines; i++) {
      const x = padding.left + (chartWidth / vLines) * i
      this.getCtx().beginPath()
      this.getCtx().moveTo(x, padding.top)
      this.getCtx().lineTo(x, padding.top + chartHeight)
      this.getCtx().stroke()
    }
  }

  /**
   * 绘制坐标轴
   */
  private drawAxis(
    padding: { top: number; right: number; bottom: number; left: number },
    chartWidth: number,
    chartHeight: number,
    minVal: number,
    maxVal: number
  ): void {
    this.getCtx().font = '10px sans-serif'
    this.getCtx().fillStyle = '#888888'
    this.getCtx().textAlign = 'right'

    // Y 轴标签
    const yLabels = 5
    for (let i = 0; i <= yLabels; i++) {
      const value = maxVal - (maxVal - minVal) * (i / yLabels)
      const y = padding.top + (chartHeight / yLabels) * i
      this.getCtx().fillText(value.toFixed(2), padding.left - 5, y + 3)
    }

    // X 轴标签（时间）
    this.getCtx().textAlign = 'center'
    const xLabels = 6
    for (let i = 0; i <= xLabels; i++) {
      const x = padding.left + (chartWidth / xLabels) * i
      this.getCtx().fillText(`${i}`, x, padding.top + chartHeight + 15)
    }
  }

  /**
   * 绘制线条
   */
  private drawLine(
    series: LineSeries,
    padding: { top: number; right: number; bottom: number; left: number },
    chartWidth: number,
    chartHeight: number,
    minVal: number,
    range: number
  ): void {
    const data = series.data.filter(v => !isNaN(v))
    const xStep = chartWidth / (data.length - 1 || 1)

    this.getCtx().beginPath()
    this.getCtx().strokeStyle = series.color
    this.getCtx().lineWidth = series.lineWidth || 1.5

    for (let i = 0; i < data.length; i++) {
      const x = padding.left + i * xStep
      const y = padding.top + chartHeight - ((data[i] - minVal) / range) * chartHeight

      if (i === 0) {
        this.getCtx().moveTo(x, y)
      } else {
        this.getCtx().lineTo(x, y)
      }
    }

    this.getCtx().stroke()
  }

  /**
   * 渲染 K 线图
   */
  renderCandleChart(
    candles: CandleData[],
    options?: {
      showVolume?: boolean
      volumeHeight?: number
    }
  ): ImageBitmap | HTMLCanvasElement {
    const padding = this.config.padding || { top: 40, right: 40, bottom: 40, left: 60 }
    const volumeHeight = options?.volumeHeight || 80
    const chartHeight = options?.showVolume !== false
      ? this.config.height - padding.top - padding.bottom - volumeHeight - 20
      : this.config.height - padding.top - padding.bottom
    const chartWidth = this.config.width - padding.left - padding.right

    // 清除画布
    this.getCtx().fillStyle = this.config.backgroundColor || '#1a1a2e'
    this.getCtx().fillRect(0, 0, this.config.width, this.config.height)

    // 计算价格范围
    let minPrice = Infinity
    let maxPrice = -Infinity
    let maxVolume = 0

    for (const candle of candles) {
      minPrice = Math.min(minPrice, candle.low)
      maxPrice = Math.max(maxPrice, candle.high)
      if (candle.volume) {
        maxVolume = Math.max(maxVolume, candle.volume)
      }
    }

    const priceRange = maxPrice - minPrice || 1

    // 绘制网格
    this.drawGrid(padding, chartWidth, chartHeight, minPrice, maxPrice)

    // 绘制 K 线
    const candleWidth = Math.max(1, (chartWidth / candles.length) * 0.8)
    const gap = chartWidth / candles.length

    for (let i = 0; i < candles.length; i++) {
      const candle = candles[i]
      const x = padding.left + i * gap + gap / 2

      const isUp = candle.close >= candle.open
      const color = isUp ? '#ef5350' : '#26a69a'

      // 绘制影线
      const highY = padding.top + chartHeight - ((candle.high - minPrice) / priceRange) * chartHeight
      const lowY = padding.top + chartHeight - ((candle.low - minPrice) / priceRange) * chartHeight
      const openY = padding.top + chartHeight - ((candle.open - minPrice) / priceRange) * chartHeight
      const closeY = padding.top + chartHeight - ((candle.close - minPrice) / priceRange) * chartHeight

      this.getCtx().strokeStyle = color
      this.getCtx().lineWidth = 1
      this.getCtx().beginPath()
      this.getCtx().moveTo(x, highY)
      this.getCtx().lineTo(x, lowY)
      this.getCtx().stroke()

      // 绘制实体
      const bodyTop = Math.min(openY, closeY)
      const bodyHeight = Math.abs(closeY - openY) || 1

      this.getCtx().fillStyle = color
      this.getCtx().fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight)

      // 绘制成交量
      if (options?.showVolume !== false && candle.volume && maxVolume > 0) {
        const volY = padding.top + chartHeight + volumeHeight
        const volBarHeight = (candle.volume / maxVolume) * (volumeHeight - 10)

        this.getCtx().fillStyle = isUp ? 'rgba(239, 83, 80, 0.5)' : 'rgba(38, 166, 154, 0.5)'
        this.getCtx().fillRect(x - candleWidth / 2, volY - volBarHeight, candleWidth, volBarHeight)
      }
    }

    // 绘制坐标轴
    this.drawAxis(padding, chartWidth, chartHeight, minPrice, maxPrice)

    // 返回结果（克隆后 transfer，避免销毁原画布）
    if (this.canvas instanceof OffscreenCanvas) {
      return this.cloneOffscreenCanvas().transferToImageBitmap()
    }
    return this.canvas!
  }

  /**
   * 渲染热力图
   */
  renderHeatmap(
    data: number[][],
    options?: {
      colorScale?: (value: number) => string
      min?: number
      max?: number
    }
  ): ImageBitmap | HTMLCanvasElement {
    const rows = data.length
    const cols = data[0]?.length || 0

    const cellWidth = this.config.width / cols
    const cellHeight = this.config.height / rows

    // 计算范围
    let min = options?.min ?? Infinity
    let max = options?.max ?? -Infinity

    if (!options?.min || !options?.max) {
      for (const row of data) {
        for (const val of row) {
          min = Math.min(min, val)
          max = Math.max(max, val)
        }
      }
    }

    const range = max - min || 1

    // 默认颜色映射
    const colorScale = options?.colorScale || ((value: number) => {
      const t = (value - min) / range
      const r = Math.floor(255 * t)
      const b = Math.floor(255 * (1 - t))
      return `rgb(${r}, 50, ${b})`
    })

    // 清除画布
    this.getCtx().fillStyle = this.config.backgroundColor || '#1a1a2e'
    this.getCtx().fillRect(0, 0, this.config.width, this.config.height)

    // 绘制每个单元格
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const value = data[i][j]
        this.getCtx().fillStyle = colorScale(value)
        this.getCtx().fillRect(j * cellWidth, i * cellHeight, cellWidth, cellHeight)
      }
    }

    // 返回结果（克隆后 transfer，避免销毁原画布）
    if (this.canvas instanceof OffscreenCanvas) {
      return this.cloneOffscreenCanvas().transferToImageBitmap()
    }
    return this.canvas!
  }

  /**
   * 转换为 DataURL
   */
  toDataURL(format: 'png' | 'jpeg' = 'png', quality = 0.92): string {
    if (this.canvas instanceof OffscreenCanvas) {
      // OffscreenCanvas 需要先克隆再转换为 ImageBitmap，避免销毁原画布
      const bitmap = this.cloneOffscreenCanvas().transferToImageBitmap()
      const tempCanvas = document.createElement('canvas')
      tempCanvas.width = this.config.width
      tempCanvas.height = this.config.height
      const tempCtx = tempCanvas.getContext('2d')!
      tempCtx.drawImage(bitmap, 0, 0)
      return tempCanvas.toDataURL(`image/${format}`, quality)
    }
    return (this.canvas as HTMLCanvasElement).toDataURL(`image/${format}`, quality)
  }

  /**
   * 获取 ImageData
   */
  getImageData(): ImageData {
    if (this.canvas instanceof OffscreenCanvas) {
      return this.getCtx().getImageData(0, 0, this.config.width, this.config.height)
    }
    return this.getCtx().getImageData(0, 0, this.config.width, this.config.height)
  }

  /**
   * 销毁
   */
  destroy(): void {
    this.canvas = null
    this.ctx = null
    if (this.worker) {
      this.worker.terminate()
      this.worker = null
    }
  }
}

/**
 * 渲染器池（用于批量渲染）
 */
export class RendererPool {
  private entries: { renderer: OffscreenRenderer; inUse: boolean }[] = []
  private maxSize: number

  constructor(maxSize = 4) {
    this.maxSize = maxSize
  }

  /**
   * 获取渲染器
   */
  acquire(config: ChartConfig): OffscreenRenderer {
    // 尝试复用空闲的
    const freeEntry = this.entries.find(
      e => !e.inUse && e.renderer['config'].width === config.width && e.renderer['config'].height === config.height
    )

    if (freeEntry) {
      freeEntry.inUse = true
      return freeEntry.renderer
    }

    // 创建新的
    const renderer = new OffscreenRenderer(config)
    if (this.entries.length < this.maxSize) {
      this.entries.push({ renderer, inUse: true })
    }
    return renderer
  }

  /**
   * 释放渲染器
   */
  release(renderer: OffscreenRenderer): void {
    const entry = this.entries.find(e => e.renderer === renderer)
    if (entry) {
      entry.inUse = false
    }
  }

  /**
   * 清空池
   */
  clear(): void {
    this.entries.forEach(e => e.renderer.destroy())
    this.entries = []
  }
}

// 导出
export const rendererPool = new RendererPool()

export default OffscreenRenderer
