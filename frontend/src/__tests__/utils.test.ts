/**
 * 工具函数单元测试
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { validators, compose, createFormValidator } from '../utils/formValidation'

describe('表单验证工具', () => {
  describe('validators.required', () => {
    const validator = validators.required('此字段必填')

    it('应该对空值返回错误', () => {
      expect(validator('')).toBe('此字段必填')
      expect(validator(null)).toBe('此字段必填')
      expect(validator(undefined)).toBe('此字段必填')
    })

    it('应该对非空值返回 null', () => {
      expect(validator('test')).toBeNull()
      expect(validator(123)).toBeNull()
    })

    it('应该对空数组返回错误', () => {
      expect(validator([])).toBe('此字段必填')
    })
  })

  describe('validators.email', () => {
    const validator = validators.email()

    it('应该验证正确的邮箱格式', () => {
      expect(validator('test@example.com')).toBeNull()
      expect(validator('user.name@domain.co')).toBeNull()
    })

    it('应该拒绝错误的邮箱格式', () => {
      expect(validator('invalid')).toBe('请输入有效的邮箱地址')
      expect(validator('test@')).toBe('请输入有效的邮箱地址')
      expect(validator('@domain.com')).toBe('请输入有效的邮箱地址')
    })

    it('应该对空值返回 null', () => {
      expect(validator('')).toBeNull()
    })
  })

  describe('validators.phone', () => {
    const validator = validators.phone()

    it('应该验证正确的手机号', () => {
      expect(validator('13812345678')).toBeNull()
      expect(validator('15900001111')).toBeNull()
    })

    it('应该拒绝错误的手机号', () => {
      expect(validator('12345678901')).toBe('请输入有效的手机号码')
      expect(validator('1381234567')).toBe('请输入有效的手机号码')
    })
  })

  describe('validators.minLength', () => {
    const validator = validators.minLength(3)

    it('应该验证最小长度', () => {
      expect(validator('ab')).toBe('最少输入 3 个字符')
      expect(validator('abc')).toBeNull()
      expect(validator('abcd')).toBeNull()
    })
  })

  describe('validators.maxLength', () => {
    const validator = validators.maxLength(5)

    it('应该验证最大长度', () => {
      expect(validator('abc')).toBeNull()
      expect(validator('abcde')).toBeNull()
      expect(validator('abcdef')).toBe('最多输入 5 个字符')
    })
  })

  describe('validators.range', () => {
    const validator = validators.range(1, 100)

    it('应该验证数值范围', () => {
      expect(validator(50)).toBeNull()
      expect(validator(1)).toBeNull()
      expect(validator(100)).toBeNull()
      expect(validator(0)).toBe('值应在 1 到 100 之间')
      expect(validator(101)).toBe('值应在 1 到 100 之间')
    })
  })

  describe('compose', () => {
    it('应该组合多个验证器', async () => {
      const validator = compose(
        validators.required('必填'),
        validators.minLength(3)
      )

      expect(await validator('')).toBe('必填')
      expect(await validator('ab')).toBe('最少输入 3 个字符')
      expect(await validator('abc')).toBeNull()
    })
  })

  describe('createFormValidator', () => {
    it('应该验证整个表单', async () => {
      const validate = createFormValidator({
        name: [{ required: true, message: '姓名必填' }],
        email: [{ validator: validators.email() }],
      })

      const errors = await validate({ name: '', email: 'invalid' })

      expect(errors.name).toBe('姓名必填')
      expect(errors.email).toBe('请输入有效的邮箱地址')
    })

    it('应该对有效数据返回空错误', async () => {
      const validate = createFormValidator({
        name: [{ required: true, message: '姓名必填' }],
      })

      const errors = await validate({ name: 'test' })

      expect(errors).toEqual({})
    })
  })
})

describe('validators.password', () => {
  const validator = validators.password()

  it('应该验证密码强度', () => {
    expect(validator('abc123')).toBeNull()
    expect(validator('Abc123')).toBeNull()
    expect(validator('abcdef')).toBe('密码需包含字母和数字，至少6位')
    expect(validator('123456')).toBe('密码需包含字母和数字，至少6位')
    expect(validator('ab1')).toBe('密码需包含字母和数字，至少6位')
  })
})
