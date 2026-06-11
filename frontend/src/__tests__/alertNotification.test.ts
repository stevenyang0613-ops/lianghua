/**
 * 告警通知系统单元测试
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { AlertManager, type AlertRule, type AlertLevel } from '../utils/alertNotification'

// Mock notification
vi.mock('antd', () => ({
  notification: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
  },
}))

describe('AlertManager', () => {
  let manager: AlertManager

  beforeEach(() => {
    manager = new AlertManager()
    localStorage.clear()
  })

  describe('Rule Management', () => {
    it('should add alert rule', () => {
      const rule = manager.addRule({
        name: 'Test Rule',
        level: 'warning',
        enabled: true,
        condition: {
          metric: 'cpu.usage',
          operator: '>',
          threshold: 80,
        },
        channels: ['inApp'],
        suppressDuration: 300,
      })

      expect(rule.id).toBeDefined()
      expect(rule.name).toBe('Test Rule')
      expect(rule.enabled).toBe(true)
    })

    it('should update rule', () => {
      const rule = manager.addRule({
        name: 'Original',
        level: 'warning',
        enabled: true,
        condition: {
          metric: 'memory.usage',
          operator: '>',
          threshold: 70,
        },
        channels: ['inApp'],
        suppressDuration: 300,
      })

      const updated = manager.updateRule(rule.id, {
        condition: { metric: 'memory.usage', operator: '>', threshold: 90 },
        level: 'error',
      })

      expect(updated?.condition.threshold).toBe(90)
      expect(updated?.level).toBe('error')
    })

    it('should delete rule', () => {
      const rule = manager.addRule({
        name: 'To Delete',
        level: 'info',
        enabled: true,
        condition: {
          metric: 'test.metric',
          operator: '>',
          threshold: 0,
        },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      const result = manager.deleteRule(rule.id)
      expect(result).toBe(true)

      const rules = manager.getRules()
      expect(rules.find(r => r.id === rule.id)).toBeUndefined()
    })

    it('should get all rules', () => {
      manager.addRule({
        name: 'Rule 1',
        level: 'info',
        enabled: true,
        condition: { metric: 'm1', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })
      manager.addRule({
        name: 'Rule 2',
        level: 'warning',
        enabled: false,
        condition: { metric: 'm2', operator: '<', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      const rules = manager.getRules()
      expect(rules.length).toBe(2)
    })
  })

  describe('Alert Triggering', () => {
    it('should trigger alert when condition met', () => {
      manager.addRule({
        name: 'CPU Alert',
        level: 'warning',
        enabled: true,
        condition: {
          metric: 'cpu.usage',
          operator: '>',
          threshold: 80,
        },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      // 更新指标值触发告警
      manager.updateMetric('cpu.usage', 90)

      const activeAlerts = manager.getActiveAlerts()
      expect(activeAlerts.length).toBeGreaterThan(0)
      expect(activeAlerts[0].ruleName).toBe('CPU Alert')
    })

    it('should not trigger alert when condition not met', () => {
      manager.addRule({
        name: 'CPU Alert',
        level: 'warning',
        enabled: true,
        condition: {
          metric: 'cpu.usage',
          operator: '>',
          threshold: 80,
        },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('cpu.usage', 50)

      const activeAlerts = manager.getActiveAlerts()
      expect(activeAlerts.length).toBe(0)
    })

    it('should not trigger disabled rule', () => {
      manager.addRule({
        name: 'Disabled Rule',
        level: 'warning',
        enabled: false,
        condition: {
          metric: 'test.metric',
          operator: '>',
          threshold: 0,
        },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('test.metric', 100)

      const activeAlerts = manager.getActiveAlerts()
      expect(activeAlerts.length).toBe(0)
    })
  })

  describe('Alert Suppression', () => {
    it('should suppress duplicate alerts', () => {
      manager.addRule({
        name: 'Suppressed Alert',
        level: 'warning',
        enabled: true,
        condition: {
          metric: 'test.suppress',
          operator: '>',
          threshold: 0,
        },
        channels: ['inApp'],
        suppressDuration: 60, // 60秒抑制
      })

      // 第一次触发
      manager.updateMetric('test.suppress', 100)
      let alerts = manager.getActiveAlerts()
      const firstCount = alerts.length

      // 短时间内再次触发（应该被抑制）
      manager.updateMetric('test.suppress', 200)
      alerts = manager.getActiveAlerts()

      // 应该还是同一个告警，没有新增
      expect(alerts.length).toBe(firstCount)
    })
  })

  describe('Alert Lifecycle', () => {
    it('should acknowledge alert', () => {
      manager.addRule({
        name: 'Test',
        level: 'warning',
        enabled: true,
        condition: { metric: 'test.ack', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('test.ack', 100)

      const alert = manager.getActiveAlerts()[0]
      const acknowledged = manager.acknowledgeAlert(alert.id, 'test-user')

      expect(acknowledged?.acknowledgedBy).toBe('test-user')
      expect(acknowledged?.acknowledgedAt).toBeDefined()
    })

    it('should resolve alert', () => {
      manager.addRule({
        name: 'Test',
        level: 'warning',
        enabled: true,
        condition: { metric: 'test.resolve', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('test.resolve', 100)

      const alert = manager.getActiveAlerts()[0]
      const resolved = manager.resolveAlert(alert.id)

      expect(resolved?.status).toBe('resolved')
      expect(resolved?.resolvedAt).toBeDefined()

      // 活动告警应该减少
      const activeAlerts = manager.getActiveAlerts()
      expect(activeAlerts.find(a => a.id === alert.id)).toBeUndefined()
    })
  })

  describe('Alert History', () => {
    it('should get alert history', () => {
      manager.addRule({
        name: 'History Test',
        level: 'info',
        enabled: true,
        condition: { metric: 'test.history', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('test.history', 100)

      const history = manager.getAlertHistory()
      expect(history.length).toBeGreaterThan(0)
    })

    it('should filter history by level', () => {
      manager.addRule({
        name: 'Error Alert',
        level: 'error',
        enabled: true,
        condition: { metric: 'test.error', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })
      manager.addRule({
        name: 'Info Alert',
        level: 'info',
        enabled: true,
        condition: { metric: 'test.info', operator: '>', threshold: 0 },
        channels: ['inApp'],
        suppressDuration: 0,
      })

      manager.updateMetric('test.error', 100)
      manager.updateMetric('test.info', 100)

      const errorHistory = manager.getAlertHistory({ level: 'error' })
      expect(errorHistory.every(a => a.level === 'error')).toBe(true)
    })
  })

  describe('Manual Alert', () => {
    it('should create manual alert', () => {
      const alert = manager.manualAlert(
        'Manual Test',
        'warning',
        'This is a manual test alert',
        { source: 'unit-test' }
      )

      expect(alert.ruleName).toBe('Manual Test')
      expect(alert.level).toBe('warning')
      expect(alert.message).toContain('manual test alert')
      expect(alert.status).toBe('firing')
    })
  })

  describe('Condition Operators', () => {
    const testCases = [
      { operator: '>' as const, value: 10, threshold: 5, expected: true },
      { operator: '>' as const, value: 5, threshold: 10, expected: false },
      { operator: '<' as const, value: 5, threshold: 10, expected: true },
      { operator: '<' as const, value: 10, threshold: 5, expected: false },
      { operator: '>=' as const, value: 10, threshold: 10, expected: true },
      { operator: '<=' as const, value: 10, threshold: 10, expected: true },
      { operator: '==' as const, value: 10, threshold: 10, expected: true },
      { operator: '!=' as const, value: 10, threshold: 5, expected: true },
    ]

    testCases.forEach(({ operator, value, threshold, expected }) => {
      it(`should evaluate ${operator} correctly: ${value} ${operator} ${threshold}`, () => {
        manager.addRule({
          name: `Operator Test ${operator}`,
          level: 'info',
          enabled: true,
          condition: {
            metric: `test.operator.${operator}`,
            operator,
            threshold,
          },
          channels: ['inApp'],
          suppressDuration: 0,
        })

        manager.updateMetric(`test.operator.${operator}`, value)

        const alerts = manager.getActiveAlerts()
        if (expected) {
          expect(alerts.find(a => a.ruleName === `Operator Test ${operator}`)).toBeDefined()
        } else {
          expect(alerts.find(a => a.ruleName === `Operator Test ${operator}`)).toBeUndefined()
        }
      })
    })
  })
})
