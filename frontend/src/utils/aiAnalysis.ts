/**
 * AI 辅助分析工具
 * 集成多种 AI 模型进行市场分析、信号解释、策略建议
 */

// AI 模型配置
export interface AIModelConfig {
  provider: 'openai' | 'anthropic' | 'deepseek' | 'local' | 'custom'
  model: string
  apiKey?: string
  apiEndpoint?: string
  maxTokens?: number
  temperature?: number
}

// 分析请求
export interface AnalysisRequest {
  type: 'market' | 'signal' | 'strategy' | 'risk' | 'sentiment' | 'custom'
  context: {
    symbols?: string[]
    timeframe?: string
    data?: Record<string, unknown>
    indicators?: string[]
  }
  question?: string
  language?: 'zh' | 'en'
}

// 分析结果
export interface AnalysisResult {
  id: string
  type: AnalysisRequest['type']
  summary: string
  insights: string[]
  recommendations: string[]
  confidence: number  // 0-100
  warnings?: string[]
  data?: Record<string, unknown>
  generatedAt: number
  model: string
  tokens?: {
    prompt: number
    completion: number
    total: number
  }
}

// 市场情绪分析
export interface SentimentAnalysis {
  overall: 'bullish' | 'bearish' | 'neutral'
  score: number  // -100 to 100
  factors: {
    name: string
    impact: 'positive' | 'negative' | 'neutral'
    weight: number
    description: string
  }[]
  news?: {
    title: string
    sentiment: 'positive' | 'negative' | 'neutral'
    relevance: number
    source: string
    publishedAt: string
  }[]
}

// 信号解释
export interface SignalExplanation {
  signalId: string
  signalType: string
  explanation: string
  reasoning: string[]
  supportingIndicators: string[]
  riskFactors: string[]
  suggestedActions: {
    action: 'buy' | 'sell' | 'hold' | 'wait'
    confidence: number
    reason: string
  }[]
}

/**
 * AI 分析服务
 */
export class AIAnalysisService {
  private config: AIModelConfig = {
    provider: 'openai',
    model: 'gpt-4',
    maxTokens: 2000,
    temperature: 0.7,
  }
  private cache: Map<string, { result: AnalysisResult; timestamp: number }> = new Map()
  private cacheTimeout = 300000 // 5分钟缓存

  /**
   * 设置模型配置
   */
  setConfig(config: Partial<AIModelConfig>): void {
    this.config = { ...this.config, ...config }
  }

  /**
   * 执行分析
   */
  async analyze(request: AnalysisRequest): Promise<AnalysisResult> {
    // 检查缓存
    const cacheKey = this.getCacheKey(request)
    const cached = this.cache.get(cacheKey)
    if (cached && Date.now() - cached.timestamp < this.cacheTimeout) {
      return cached.result
    }

    const result = await this.executeAnalysis(request)

    // 缓存结果
    this.cache.set(cacheKey, { result, timestamp: Date.now() })

    return result
  }

  /**
   * 执行分析（内部方法）
   */
  private async executeAnalysis(request: AnalysisRequest): Promise<AnalysisResult> {
    const prompt = this.buildPrompt(request)

    try {
      const response = await this.callModel(prompt)
      const parsed = this.parseResponse(response, request)

      return {
        id: `analysis_${Date.now()}`,
        type: request.type,
        ...parsed,
        generatedAt: Date.now(),
        model: this.config.model,
      }
    } catch (error) {
      console.error('[AI] Analysis failed:', error)
      throw error
    }
  }

  /**
   * 构建提示词
   */
  private buildPrompt(request: AnalysisRequest): string {
    const language = request.language === 'en' ? 'English' : '中文'

    const systemPrompt = `你是一个专业的可转债量化交易分析师。请用${language}回答。你的分析应该：
1. 基于数据和逻辑
2. 提供明确的推理过程
3. 给出可操作的建议
4. 指出潜在风险
5. 量化置信度（0-100%）`

    let userPrompt = ''

    switch (request.type) {
      case 'market':
        userPrompt = this.buildMarketPrompt(request)
        break
      case 'signal':
        userPrompt = this.buildSignalPrompt(request)
        break
      case 'strategy':
        userPrompt = this.buildStrategyPrompt(request)
        break
      case 'risk':
        userPrompt = this.buildRiskPrompt(request)
        break
      case 'sentiment':
        userPrompt = this.buildSentimentPrompt(request)
        break
      default:
        userPrompt = request.question || '请分析当前市场情况'
    }

    return `${systemPrompt}\n\n${userPrompt}`
  }

  /**
   * 构建市场分析提示词
   */
  private buildMarketPrompt(request: AnalysisRequest): string {
    const { symbols, timeframe, data, indicators } = request.context

    return `请分析以下市场情况：

标的：${symbols?.join(', ') || '全市场'}
时间周期：${timeframe || '日线'}
技术指标：${indicators?.join(', ') || 'MACD, KDJ, RSI'}

市场数据：
${JSON.stringify(data, null, 2)}

请提供：
1. 市场趋势分析
2. 关键支撑阻力位
3. 技术指标解读
4. 交易建议
5. 风险提示`
  }

  /**
   * 构建信号解释提示词
   */
  private buildSignalPrompt(request: AnalysisRequest): string {
    const { data } = request.context

    return `请解释以下交易信号：

信号数据：
${JSON.stringify(data, null, 2)}

请提供：
1. 信号含义解释
2. 触发原因分析
3. 历史胜率（如有）
4. 建议的操作策略
5. 止损止盈建议
6. 潜在风险因素`
  }

  /**
   * 构建策略分析提示词
   */
  private buildStrategyPrompt(request: AnalysisRequest): string {
    const { data } = request.context

    return `请评估以下交易策略：

策略详情：
${JSON.stringify(data, null, 2)}

请提供：
1. 策略优势分析
2. 策略劣势分析
3. 适用市场环境
4. 参数优化建议
5. 风险管理建议
6. 改进方向`
  }

  /**
   * 构建风险分析提示词
   */
  private buildRiskPrompt(request: AnalysisRequest): string {
    const { symbols, data } = request.context

    return `请分析以下投资组合的风险：

标的：${symbols?.join(', ') || '当前持仓'}
持仓数据：
${JSON.stringify(data, null, 2)}

请提供：
1. 主要风险因素
2. 风险敞口分析
3. 相关性风险
4. 极端情景压力测试
5. 风险对冲建议
6. 仓位管理建议`
  }

  /**
   * 构建情绪分析提示词
   */
  private buildSentimentPrompt(request: AnalysisRequest): string {
    const { symbols, data } = request.context

    return `请分析以下市场情绪：

标的：${symbols?.join(', ') || '全市场'}
市场数据：
${JSON.stringify(data, null, 2)}

请提供：
1. 整体市场情绪判断
2. 情绪驱动因素
3. 资金流向分析
4. 市场预期分析
5. 反转信号识别`
  }

  /**
   * 调用 AI 模型
   */
  private async callModel(prompt: string): Promise<string> {
    switch (this.config.provider) {
      case 'openai':
        return this.callOpenAI(prompt)
      case 'anthropic':
        return this.callAnthropic(prompt)
      case 'deepseek':
        return this.callDeepSeek(prompt)
      case 'local':
        return this.callLocalModel(prompt)
      default:
        throw new Error(`Unknown provider: ${this.config.provider}`)
    }
  }

  /**
   * 调用 OpenAI API
   */
  private async callOpenAI(prompt: string): Promise<string> {
    const response = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify({
        model: this.config.model,
        messages: [{ role: 'user', content: prompt }],
        max_tokens: this.config.maxTokens,
        temperature: this.config.temperature,
      }),
    })

    const data = await response.json()
    return data.choices[0].message.content
  }

  /**
   * 调用 Anthropic API
   */
  private async callAnthropic(prompt: string): Promise<string> {
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': this.config.apiKey || '',
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: this.config.model,
        max_tokens: this.config.maxTokens,
        messages: [{ role: 'user', content: prompt }],
      }),
    })

    const data = await response.json()
    return data.content[0].text
  }

  /**
   * 调用 DeepSeek API
   */
  private async callDeepSeek(prompt: string): Promise<string> {
    const response = await fetch('https://api.deepseek.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.config.apiKey}`,
      },
      body: JSON.stringify({
        model: this.config.model,
        messages: [{ role: 'user', content: prompt }],
        max_tokens: this.config.maxTokens,
        temperature: this.config.temperature,
      }),
    })

    const data = await response.json()
    return data.choices[0].message.content
  }

  /**
   * 调用本地模型
   */
  private async callLocalModel(prompt: string): Promise<string> {
    const endpoint = this.config.apiEndpoint || 'http://localhost:11434/api/generate'

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.config.model,
        prompt,
        stream: false,
      }),
    })

    const data = await response.json()
    return data.response
  }

  /**
   * 解析响应
   */
  private parseResponse(response: string, request: AnalysisRequest): Omit<AnalysisResult, 'id' | 'type' | 'generatedAt' | 'model'> {
    // 尝试从响应中提取结构化信息
    const sections = this.extractSections(response)

    return {
      summary: sections.summary || response.substring(0, 200),
      insights: sections.insights || [],
      recommendations: sections.recommendations || [],
      confidence: sections.confidence || 70,
      warnings: sections.warnings,
      data: { raw: response },
    }
  }

  /**
   * 提取结构化章节
   */
  private extractSections(text: string): {
    summary: string
    insights: string[]
    recommendations: string[]
    confidence: number
    warnings?: string[]
  } {
    const insights: string[] = []
    const recommendations: string[] = []
    const warnings: string[] = []
    let summary = ''
    let confidence = 70

    // 简单的文本解析（实际应用中可以使用更复杂的 NLP）
    const lines = text.split('\n')

    for (const line of lines) {
      const trimmed = line.trim()

      if (trimmed.match(/^[一二三四五六七八九十\d]+[.、]/)) {
        insights.push(trimmed.replace(/^[一二三四五六七八九十\d]+[.、]\s*/, ''))
      } else if (trimmed.match(/^建议[：:]/) || trimmed.match(/^[•·]\s*建议/)) {
        recommendations.push(trimmed.replace(/^建议[：:]?\s*/, '').replace(/^[•·]\s*/, ''))
      } else if (trimmed.match(/^风险[：:]/) || trimmed.match(/警告/)) {
        warnings.push(trimmed.replace(/^风险[：:]?\s*/, ''))
      } else if (trimmed.match(/置信度[：:]\s*(\d+)/)) {
        const match = trimmed.match(/置信度[：:]\s*(\d+)/)
        if (match) {
          confidence = parseInt(match[1], 10)
        }
      }
    }

    // 提取摘要（第一段）
    const paragraphs = text.split('\n\n')
    if (paragraphs.length > 0) {
      summary = paragraphs[0].substring(0, 200)
    }

    return { summary, insights, recommendations, confidence, warnings: warnings.length > 0 ? warnings : undefined }
  }

  /**
   * 获取缓存键
   */
  private getCacheKey(request: AnalysisRequest): string {
    return JSON.stringify(request)
  }

  /**
   * 清除缓存
   */
  clearCache(): void {
    this.cache.clear()
  }

  /**
   * 市场情绪分析（快捷方法）
   */
  async analyzeSentiment(symbols: string[], data?: Record<string, unknown>): Promise<SentimentAnalysis> {
    const result = await this.analyze({
      type: 'sentiment',
      context: { symbols, data },
    })

    // 解析情绪结果
    const score = this.extractSentimentScore(result.summary)
    const overall = score > 20 ? 'bullish' : score < -20 ? 'bearish' : 'neutral'

    return {
      overall,
      score,
      factors: result.insights.map((insight, index) => ({
        name: `因素${index + 1}`,
        impact: insight.includes('积极') || insight.includes('利好') ? 'positive' :
                insight.includes('消极') || insight.includes('利空') ? 'negative' : 'neutral',
        weight: 1 / result.insights.length,
        description: insight,
      })),
    }
  }

  /**
   * 提取情绪分数
   */
  private extractSentimentScore(text: string): number {
    const positiveWords = ['上涨', '看涨', '积极', '利好', '强势', '突破']
    const negativeWords = ['下跌', '看跌', '消极', '利空', '弱势', '跌破']

    let score = 0

    for (const word of positiveWords) {
      const matches = text.match(new RegExp(word, 'g'))
      if (matches) score += matches.length * 10
    }

    for (const word of negativeWords) {
      const matches = text.match(new RegExp(word, 'g'))
      if (matches) score -= matches.length * 10
    }

    return Math.max(-100, Math.min(100, score))
  }

  /**
   * 解释信号（快捷方法）
   */
  async explainSignal(signalData: Record<string, unknown>): Promise<SignalExplanation> {
    const result = await this.analyze({
      type: 'signal',
      context: { data: signalData },
    })

    return {
      signalId: (signalData.id as string) || '',
      signalType: (signalData.type as string) || 'unknown',
      explanation: result.summary,
      reasoning: result.insights,
      supportingIndicators: [],
      riskFactors: result.warnings || [],
      suggestedActions: result.recommendations.map(rec => ({
        action: rec.includes('买入') ? 'buy' : rec.includes('卖出') ? 'sell' : 'hold',
        confidence: result.confidence,
        reason: rec,
      })),
    }
  }

  /**
   * 策略优化建议
   */
  async optimizeStrategy(strategyData: Record<string, unknown>): Promise<{
    improvements: string[]
    parameterSuggestions: Record<string, { current: unknown; suggested: unknown; reason: string }>
    riskWarnings: string[]
  }> {
    const result = await this.analyze({
      type: 'strategy',
      context: { data: strategyData },
    })

    return {
      improvements: result.recommendations,
      parameterSuggestions: {},
      riskWarnings: result.warnings || [],
    }
  }

  /**
   * 流式分析（用于实时显示）
   */
  async *analyzeStream(request: AnalysisRequest): AsyncGenerator<string> {
    const prompt = this.buildPrompt(request)

    // 对于支持流式输出的 API
    if (this.config.provider === 'openai') {
      const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({
          model: this.config.model,
          messages: [{ role: 'user', content: prompt }],
          max_tokens: this.config.maxTokens,
          temperature: this.config.temperature,
          stream: true,
        }),
      })

      const reader = response.body?.getReader()
      if (!reader) return

      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n').filter(line => line.startsWith('data: '))

        for (const line of lines) {
          const data = line.replace('data: ', '')
          if (data === '[DONE]') continue

          try {
            const parsed = JSON.parse(data)
            const content = parsed.choices[0]?.delta?.content
            if (content) {
              yield content
            }
          } catch {
            // 忽略解析错误
          }
        }
      }
    } else {
      // 不支持流式的模型，直接返回完整结果
      const result = await this.callModel(prompt)
      yield result
    }
  }
}

// 导出单例
export const aiAnalysisService = new AIAnalysisService()

export default aiAnalysisService
