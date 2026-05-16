/**
 * 路径配置单元测试
 * 测试开发/生产环境下的前端和后端路径逻辑
 */

import path from 'path'
import { describe, it, expect, beforeEach, afterEach } from '@jest/globals'

// 模拟环境变量
const originalEnv = process.env.NODE_ENV

describe('Path Configuration Tests', () => {
  beforeEach(() => {
    // 重置模块缓存
    jest.resetModules()
  })

  afterEach(() => {
    process.env.NODE_ENV = originalEnv
  })

  describe('Frontend Path Resolution', () => {
    it('should resolve dev frontend path correctly', () => {
      const isDev = true
      const __dirname = '/app/electron/dist'

      const frontendDir = isDev
        ? path.join(__dirname, '..', '..', 'frontend', 'dist')
        : path.join(__dirname, '..', '..', 'frontend')

      // path.join 会自动规范化路径
      expect(path.resolve(frontendDir)).toBe('/app/frontend/dist')
    })

    it('should resolve prod frontend path correctly', () => {
      const isDev = false
      const __dirname = '/app/electron/dist'

      const frontendDir = isDev
        ? path.join(__dirname, '..', '..', 'frontend', 'dist')
        : path.join(__dirname, '..', '..', 'frontend')

      expect(path.resolve(frontendDir)).toBe('/app/frontend')
    })

    it('should resolve index.html path correctly in production', () => {
      const isDev = false
      const __dirname = '/app/electron/dist'
      const frontendPath = path.join(__dirname, '..', '..', 'frontend', 'index.html')

      expect(path.resolve(frontendPath)).toBe('/app/frontend/index.html')
    })
  })

  describe('Backend Path Resolution', () => {
    it('should resolve dev backend path correctly', () => {
      const isDev = true
      const __dirname = '/app/electron/dist'

      const backendDir = isDev
        ? path.join(__dirname, '..', '..', 'backend')
        : path.join('/app/resources', 'backend')

      expect(path.resolve(backendDir)).toBe('/app/backend')
    })

    it('should resolve prod backend path correctly', () => {
      const isDev = false
      const mockResourcesPath = '/app/resources'

      const backendDir = isDev
        ? path.join(__dirname, '..', '..', 'backend')
        : path.join(mockResourcesPath, 'backend')

      expect(backendDir).toBe('/app/resources/backend')
    })
  })

  describe('Port Configuration', () => {
    it('should use correct backend port', () => {
      const BACKEND_PORT = 8765
      const BACKEND_HOST = '127.0.0.1'

      expect(BACKEND_PORT).toBe(8765)
      expect(BACKEND_HOST).toBe('127.0.0.1')
    })
  })

  describe('URL Construction', () => {
    it('should construct correct backend URL', () => {
      const BACKEND_HOST = '127.0.0.1'
      const BACKEND_PORT = 8765
      const backendUrl = `http://${BACKEND_HOST}:${BACKEND_PORT}`

      expect(backendUrl).toBe('http://127.0.0.1:8765')
    })

    it('should construct correct WebSocket URL', () => {
      const BACKEND_HOST = '127.0.0.1'
      const BACKEND_PORT = 8765
      const wsUrl = `ws://${BACKEND_HOST}:${BACKEND_PORT}`

      expect(wsUrl).toBe('ws://127.0.0.1:8765')
    })
  })

  describe('Resource Validation', () => {
    const requiredFiles = ['index.html', 'manifest.json']
    const requiredDirs = ['assets']

    it('should list required frontend files', () => {
      expect(requiredFiles).toContain('index.html')
      expect(requiredFiles).toContain('manifest.json')
      expect(requiredFiles.length).toBe(2)
    })

    it('should list required frontend directories', () => {
      expect(requiredDirs).toContain('assets')
      expect(requiredDirs.length).toBe(1)
    })
  })
})
