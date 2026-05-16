/**
 * 表单验证工具
 * 统一验证规则，支持异步验证、自定义规则
 */

export type ValidationResult = string | null | Promise<string | null>
export type Validator = (value: unknown, formData?: Record<string, unknown>) => ValidationResult

interface ValidationRule {
  required?: boolean
  message?: string
  validator?: Validator
  trigger?: 'blur' | 'change'
}

/**
 * 内置验证规则
 */
export const validators = {
  required: (message = '此字段必填'): Validator => (value) => {
    if (value === null || value === undefined || value === '') {
      return message
    }
    if (Array.isArray(value) && value.length === 0) {
      return message
    }
    return null
  },

  email: (message = '请输入有效的邮箱地址'): Validator => (value) => {
    if (!value) return null
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    return emailRegex.test(String(value)) ? null : message
  },

  phone: (message = '请输入有效的手机号码'): Validator => (value) => {
    if (!value) return null
    const phoneRegex = /^1[3-9]\d{9}$/
    return phoneRegex.test(String(value)) ? null : message
  },

  url: (message = '请输入有效的URL'): Validator => (value) => {
    if (!value) return null
    try {
      new URL(String(value))
      return null
    } catch {
      return message
    }
  },

  number: (message = '请输入有效的数字'): Validator => (value) => {
    if (!value && value !== 0) return null
    return !isNaN(Number(value)) ? null : message
  },

  integer: (message = '请输入整数'): Validator => (value) => {
    if (!value && value !== 0) return null
    return Number.isInteger(Number(value)) ? null : message
  },

  positiveNumber: (message = '请输入正数'): Validator => (value) => {
    if (!value && value !== 0) return null
    const num = Number(value)
    return !isNaN(num) && num > 0 ? null : message
  },

  minLength: (min: number, message?: string): Validator => (value) => {
    if (!value) return null
    const len = String(value).length
    return len >= min ? null : message || `最少输入 ${min} 个字符`
  },

  maxLength: (max: number, message?: string): Validator => (value) => {
    if (!value) return null
    const len = String(value).length
    return len <= max ? null : message || `最多输入 ${max} 个字符`
  },

  min: (minValue: number, message?: string): Validator => (value) => {
    if (!value && value !== 0) return null
    return Number(value) >= minValue ? null : message || `最小值为 ${minValue}`
  },

  max: (maxValue: number, message?: string): Validator => (value) => {
    if (!value && value !== 0) return null
    return Number(value) <= maxValue ? null : message || `最大值为 ${maxValue}`
  },

  range: (min: number, max: number, message?: string): Validator => (value) => {
    if (!value && value !== 0) return null
    const num = Number(value)
    return num >= min && num <= max ? null : message || `值应在 ${min} 到 ${max} 之间`
  },

  pattern: (regex: RegExp, message = '格式不正确'): Validator => (value) => {
    if (!value) return null
    return regex.test(String(value)) ? null : message
  },

  date: (message = '请输入有效的日期'): Validator => (value) => {
    if (!value) return null
    const date = new Date(String(value))
    return !isNaN(date.getTime()) ? null : message
  },

  dateRange: (startField: string, endField: string, message = '结束日期不能早于开始日期'): Validator => {
    return (_value, formData) => {
      if (!formData) return null
      const start = formData[startField]
      const end = formData[endField]
      if (!start || !end) return null
      return new Date(String(start)) <= new Date(String(end)) ? null : message
    }
  },

  sameAs: (otherField: string, message?: string): Validator => {
    return (value, formData) => {
      if (!formData) return null
      return value === formData[otherField] ? null : message || `两次输入不一致`
    }
  },

  password: (message = '密码需包含字母和数字，至少6位'): Validator => (value) => {
    if (!value) return null
    const passwordRegex = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$/
    return passwordRegex.test(String(value)) ? null : message
  },

  idCard: (message = '请输入有效的身份证号码'): Validator => (value) => {
    if (!value) return null
    const idCardRegex = /(^\d{15}$)|(^\d{18}$)|(^\d{17}(\d|X|x)$)/
    return idCardRegex.test(String(value)) ? null : message
  },

  bankCard: (message = '请输入有效的银行卡号'): Validator => (value) => {
    if (!value) return null
    const bankCardRegex = /^\d{16,19}$/
    return bankCardRegex.test(String(value)) ? null : message
  },

  stockCode: (message = '请输入有效的股票代码'): Validator => (value) => {
    if (!value) return null
    const codeRegex = /^[0-9]{6}$/
    return codeRegex.test(String(value)) ? null : message
  },

  bondCode: (message = '请输入有效的债券代码'): Validator => (value) => {
    if (!value) return null
    const codeRegex = /^(sh|sz|11|12|13|11)?\d{6}$/i
    return codeRegex.test(String(value)) ? null : message
  },
}

/**
 * 组合多个验证器
 */
export function compose(...validators: Validator[]): Validator {
  return async (value, formData) => {
    for (const validator of validators) {
      const result = await validator(value, formData)
      if (result) return result
    }
    return null
  }
}

/**
 * 创建表单验证器
 */
export function createFormValidator(rules: Record<string, ValidationRule[]>) {
  return async (formData: Record<string, unknown>): Promise<Record<string, string>> => {
    const errors: Record<string, string> = {}

    for (const [field, fieldRules] of Object.entries(rules)) {
      const value = formData[field]

      for (const rule of fieldRules) {
        if (rule.required && !value) {
          errors[field] = rule.message || '此字段必填'
          break
        }

        if (rule.validator) {
          const result = await rule.validator(value, formData)
          if (result) {
            errors[field] = result
            break
          }
        }
      }
    }

    return errors
  }
}

/**
 * 异步验证（如检查用户名是否存在）
 */
export function asyncValidator(
  checkFn: (value: unknown) => Promise<boolean>,
  message: string
): Validator {
  return async (value) => {
    if (!value) return null
    const isValid = await checkFn(value)
    return isValid ? null : message
  }
}

/**
 * 防抖验证
 */
export function debounceValidator(
  validator: Validator,
  delay = 300
): Validator {
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  return (value, formData) => {
    return new Promise((resolve) => {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }

      timeoutId = setTimeout(async () => {
        const result = await validator(value, formData)
        resolve(result)
      }, delay)
    })
  }
}

export default validators
