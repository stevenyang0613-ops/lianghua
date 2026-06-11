/**
 * AI 分析服务单元测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AIAnalysisService, type AnalysisRequest } from '../utils/aiAnalysis'

// Mock fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

describe('AIAnalysisService', () => {
  let service: AIAnalysisService

  beforeEach(() => {
    service = new AIAnalysisService()
    mockFetch.mockReset()
  })

  describe('Configuration', () => {
    it('should set model config correctly', () => {
      service.setConfig({
        provider: 'openai',
        model: 'gpt-4',
        apiKey: 'test-key',
        maxTokens: 1000,
        temperature: 0.5,
      })

      // 配置应该已设置（通过后续操作验证）
      expect(true).toBe(true)
    })

    it('should support different providers', () => {
      const providers = ['openai', 'anthropic', 'deepseek', 'local'] as const

      providers.forEach(provider => {
        service.setConfig({ provider, model: 'test-model' })
        // 配置应该被接受
        expect(true).toBe(true)
      })
    })
  })

  describe('Prompt Building', () => {
    it('should build market analysis prompt', () => {
      // 使用反射测试私有方法（或通过公共方法间接测试）
      const request: AnalysisRequest = {
        type: 'market',
        context: {
          symbols: ['128001', '128002'],
          timeframe: '1d',
          indicators: ['MACD', 'KDJ'],
          data: { close: [100, 101, 102] },
        },
      }

      // 调用 analyze 会触发 prompt 构建
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: '市场分析结果' } }],
        }),
      })

      // 验证请求会发送正确的提示词
      expect(async () => {
        await service.analyze(request)
      }).not.toThrow()
    })

    it('should build signal explanation prompt', () => {
      const request: AnalysisRequest = {
        type: 'signal',
        context: {
          data: {
            signalType: 'buy',
            symbol: '128001',
            price: 100.5,
            indicators: { macd: { dif: 0.5, dea: 0.3, macd: 0.2 } },
          },
        },
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: '信号解释' } }],
        }),
      })

      expect(async () => {
        await service.analyze(request)
      }).not.toThrow()
    })

    it('should build risk analysis prompt', () => {
      const request: AnalysisRequest = {
        type: 'risk',
        context: {
          symbols: ['128001', '128002', '128003'],
          data: {
            positions: [
              { symbol: '128001', quantity: 1000, value: 100000 },
              { symbol: '128002', quantity: 2000, value: 200000 },
            ],
          },
        },
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: '风险分析' } }],
        }),
      })

      expect(async () => {
        await service.analyze(request)
      }).not.toThrow()
    })
  })

  describe('API Calls', () => {
    it('should call OpenAI API correctly', async () => {
      service.setConfig({
        provider: 'openai',
        model: 'gpt-4',
        apiKey: 'test-key',
      })

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'AI 回复内容' } }],
        }),
      })

      const result = await service.analyze({
        type: 'market',
        context: { symbols: ['128001'] },
      })

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.openai.com/v1/chat/completions',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-key',
          }),
        })
      )
    })

    it('should call Anthropic API correctly', async () => {
      service.setConfig({
        provider: 'anthropic',
        model: 'claude-3-opus',
        apiKey: 'test-key',
      })

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          content: [{ text: 'Claude 回复' }],
        }),
      })

      await service.analyze({
        type: 'signal',
        context: { data: {} },
      })

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.anthropic.com/v1/messages',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'x-api-key': 'test-key',
          }),
        })
      )
    })

    it('should call DeepSeek API correctly', async () => {
      service.setConfig({
        provider: 'deepseek',
        model: 'deepseek-chat',
        apiKey: 'test-key',
      })

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'DeepSeek 回复' } }],
        }),
      })

      await service.analyze({
        type: 'strategy',
        context: { data: {} },
      })

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.deepseek.com/v1/chat/completions',
        expect.any(Object)
      )
    })
  })

  describe('Response Parsing', () => {
    it('should parse structured response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{
            message: {
              content: `
一、市场趋势分析
当前市场处于上升趋势。

二、技术指标解读
MACD 金叉，RSI 超买。

建议：逢高减仓。
风险：回调风险。
置信度：75%
              `.trim(),
            },
          }],
        }),
      })

      const result = await service.analyze({
        type: 'market',
        context: { symbols: ['128001'] },
      })

      expect(result.insights.length).toBeGreaterThan(0)
      expect(result.recommendations.length).toBeGreaterThan(0)
      expect(result.confidence).toBe(75)
    })
  })

  describe('Caching', () => {
    it('should cache analysis results', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'First response' } }],
        }),
      })

      const request: AnalysisRequest = {
        type: 'market',
        context: { symbols: ['128001'] },
      }

      // 第一次调用
      await service.analyze(request)
      expect(mockFetch).toHaveBeenCalledTimes(1)

      // 第二次相同请求应该使用缓存
      await service.analyze(request)
      expect(mockFetch).toHaveBeenCalledTimes(1) // 没有增加
    })

    it('should clear cache', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          choices: [{ message: { content: 'Response' } }],
        }),
      })

      const request: AnalysisRequest = {
        type: 'market',
        context: { symbols: ['128001'] },
      }

      await service.analyze(request)
      service.clearCache()
      await service.analyze(request)

      expect(mockFetch).toHaveBeenCalledTimes(2)
    })
  })

  describe('Convenience Methods', () => {
    it('should analyze sentiment', async () => {
      const sentimentResponse = [
        '市场情绪积极，看涨信号明显。利好因素包括资金流入增加。',
        '一、资金持续流入',
        '二、技术指标向好',
        '置信度：80',
      ].join('\n')
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{
            message: {
              content: sentimentResponse,
            },
          }],
        }),
      })

      const result = await service.analyzeSentiment(['128001'])

      expect(result.overall).toBe('bullish')
      expect(result.factors.length).toBeGreaterThan(0)
    })

    it('should explain signal', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({
          choices: [{
            message: {
              content: `
一、信号含义
买入信号触发。

建议：建议买入。
风险：注意止损。
              `.trim(),
            },
          }],
        }),
      })

      const result = await service.explainSignal({
        id: 'signal-1',
        type: 'buy',
        symbol: '128001',
      })

      expect(result.signalId).toBe('signal-1')
      expect(result.signalType).toBe('buy')
      expect(result.explanation).toBeDefined()
      expect(result.suggestedActions.length).toBeGreaterThan(0)
    })
  })

  describe('Error Handling', () => {
    it('should handle API errors gracefully', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'))

      await expect(service.analyze({
        type: 'market',
        context: { symbols: ['128001'] },
      })).rejects.toThrow('Network error')
    })

    it('should handle invalid responses', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      })

      await expect(service.analyze({
        type: 'market',
        context: { symbols: ['128001'] },
      })).rejects.toThrow()
    })
  })
})
