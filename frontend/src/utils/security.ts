/**
 * 安全工具
 * CSP 配置、XSS 防护、敏感数据加密存储
 */

import CryptoJS from 'crypto-js'

// 加密密钥（实际应用中应从安全存储获取）
const getEncryptionKey = (): string => {
  try {
    let key = localStorage.getItem('app_key')
    if (!key) {
      key = CryptoJS.lib.WordArray.random(32).toString()
      localStorage.setItem('app_key', key)
    }
    return key ?? ''
  } catch {
    // localStorage 不可用（隐私模式、浏览器限制等），每次生成新密钥
    return CryptoJS.lib.WordArray.random(32).toString()
  }
}

/**
 * 数据加密
 */
export function encrypt(data: string): string {
  const key = getEncryptionKey()
  return CryptoJS.AES.encrypt(data, key).toString()
}

/**
 * 数据解密
 */
export function decrypt(encryptedData: string): string {
  const key = getEncryptionKey()
  const bytes = CryptoJS.AES.decrypt(encryptedData, key)
  return bytes.toString(CryptoJS.enc.Utf8)
}

/**
 * 加密对象
 */
export function encryptObject<T>(obj: T): string {
  return encrypt(JSON.stringify(obj))
}

/**
 * 解密对象
 */
export function decryptObject<T>(encryptedData: string): T | null {
  try {
    const decrypted = decrypt(encryptedData)
    return JSON.parse(decrypted) as T
  } catch {
    return null
  }
}

/**
 * 安全存储
 */
export const secureStorage = {
  setItem: (key: string, value: unknown): void => {
    const encrypted = encrypt(JSON.stringify(value))
    localStorage.setItem(`secure_${key}`, encrypted)
  },

  getItem: <T>(key: string): T | null => {
    const encrypted = localStorage.getItem(`secure_${key}`)
    if (!encrypted) return null
    try {
      return JSON.parse(decrypt(encrypted)) as T
    } catch {
      return null
    }
  },

  removeItem: (key: string): void => {
    localStorage.removeItem(`secure_${key}`)
  },

  clear: (): void => {
    const keys = Object.keys(localStorage)
    keys.filter(k => k.startsWith('secure_')).forEach(k => localStorage.removeItem(k))
  },
}

/**
 * XSS 防护 - 转义 HTML
 */
export function escapeHtml(str: string): string {
  const escapeMap: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#x27;',
    '/': '&#x2F;',
  }
  return str.replace(/[&<>"'/]/g, char => escapeMap[char])
}

/**
 * XSS 防护 - 移除危险标签
 * 保留白名单安全标签，剥离危险属性，非白名单标签用文本内容替换。
 * For production use with untrusted HTML, use a dedicated library like DOMPurify.
 */
export function sanitizeHtml(html: string): string {
  if (typeof window === 'undefined') {
    return escapeHtml(html)
  }
  try {
    const parser = new DOMParser()
    const doc = parser.parseFromString(html, 'text/html')
    const body = doc.body
    if (!body) return ''

    // 1. 移除危险元素
    const dangerous = doc.querySelectorAll('script, style, iframe, object, embed, form, input, textarea')
    dangerous.forEach(el => el.remove())

    // Safe tag whitelist
    const SAFE_TAGS = new Set([
      'p', 'strong', 'em', 'b', 'i', 'u', 'span', 'br', 'h1', 'h2', 'h3',
      'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre',
      'div', 'a', 'table', 'thead', 'tbody', 'tr', 'td', 'th',
    ])

    // 2. 遍历所有元素：清理危险属性，非白名单标签替换为文本
    const allElements = body.querySelectorAll('*')
    allElements.forEach(el => {
      const tag = el.tagName.toLowerCase()

      // 清理危险属性
      const attrs = Array.from(el.attributes)
      attrs.forEach(attr => {
        const name = attr.name.toLowerCase()
        const value = attr.value
        if (/^on\w+/i.test(name)) {
          el.removeAttribute(attr.name)
        }
        if (/^\s*javascript:/i.test(value)) {
          el.removeAttribute(attr.name)
        }
        if (/^\s*data:text\/html/i.test(value)) {
          el.removeAttribute(attr.name)
        }
        if (tag === 'a' && name === 'href') {
          if (/^\s*javascript:/i.test(value) || /^\s*data:/i.test(value)) {
            el.removeAttribute(attr.name)
          }
        }
      })

      // 非白名单标签：替换为文本内容（保留子文本）
      if (!SAFE_TAGS.has(tag) && el.parentNode) {
        const text = doc.createTextNode(el.textContent || '')
        el.parentNode.replaceChild(text, el)
      }
    })

    return body.innerHTML
  } catch {
    return escapeHtml(html)
  }
}

/**
 * 内容安全策略检查
 */
export function checkCSP(): {
  isSupported: boolean
  violations: string[]
} {
  const violations: string[] = []
  let isSupported = false

  try {
    // 检查是否支持 CSP
    const meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]')
    if (meta) {
      isSupported = true
      const policy = meta.getAttribute('content') || ''

      // 检查不安全的配置
      if (policy.includes("'unsafe-inline'")) {
        violations.push("使用 'unsafe-inline' 存在 XSS 风险")
      }
      if (policy.includes("'unsafe-eval'")) {
        violations.push("使用 'unsafe-eval' 存在代码注入风险")
      }
      if (policy.includes('data:')) {
        violations.push("允许 data: URI 可能存在风险")
      }
    }
  } catch (e) {
    violations.push('无法检查 CSP 配置')
  }

  return { isSupported, violations }
}

/**
 * 生成 CSP 头
 */
export function generateCSP(): string {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' ws: wss: https:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
}

/**
 * 输入验证
 */
export function validateInput(input: string, type: 'text' | 'number' | 'email' | 'url' | 'code'): {
  valid: boolean
  sanitized: string
  error?: string
} {
  // 基本清理
  let sanitized = input.trim()

  // 根据类型验证
  switch (type) {
    case 'text':
      // 限制长度
      if (sanitized.length > 1000) {
        return { valid: false, sanitized: sanitized.slice(0, 1000), error: '输入过长' }
      }
      break

    case 'number':
      if (!/^-?\d*\.?\d+$/.test(sanitized)) {
        return { valid: false, sanitized: '0', error: '请输入有效数字' }
      }
      break

    case 'email':
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(sanitized)) {
        return { valid: false, sanitized, error: '请输入有效邮箱' }
      }
      break

    case 'url':
      try {
        new URL(sanitized)
      } catch {
        return { valid: false, sanitized, error: '请输入有效 URL' }
      }
      break

    case 'code':
      // 股票/债券代码格式
      if (!/^[0-9]{6}$/.test(sanitized)) {
        return { valid: false, sanitized, error: '请输入6位数字代码' }
      }
      break
  }

  // XSS 检查
  const dangerousPatterns = [
    /<script/i,
    /javascript:/i,
    /on\w+\s*=/i,
    /<iframe/i,
    /<object/i,
    /<embed/i,
  ]

  for (const pattern of dangerousPatterns) {
    if (pattern.test(sanitized)) {
      return { valid: false, sanitized: escapeHtml(sanitized), error: '输入包含危险内容' }
    }
  }

  return { valid: true, sanitized }
}

/**
 * 敏感数据脱敏
 */
export function maskSensitiveData(data: string, type: 'phone' | 'email' | 'idcard' | 'bankcard'): string {
  switch (type) {
    case 'phone':
      return data.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2')
    case 'email':
      return data.replace(/(.{2}).*@/, '$1***@')
    case 'idcard':
      return data.replace(/(\d{4})\d{10}(\d{4})/, '$1**********$2')
    case 'bankcard':
      return data.replace(/(\d{4})\d+(\d{4})/, '$1****$2')
    default:
      return data
  }
}

/**
 * 密码强度检查
 */
export function checkPasswordStrength(password: string): {
  score: number
  level: 'weak' | 'medium' | 'strong'
  suggestions: string[]
} {
  let score = 0
  const suggestions: string[] = []

  if (password.length >= 8) score += 1
  else suggestions.push('密码至少8位')

  if (password.length >= 12) score += 1
  if (/[a-z]/.test(password)) score += 1
  else suggestions.push('包含小写字母')

  if (/[A-Z]/.test(password)) score += 1
  else suggestions.push('包含大写字母')

  if (/[0-9]/.test(password)) score += 1
  else suggestions.push('包含数字')

  if (/[^a-zA-Z0-9]/.test(password)) score += 1
  else suggestions.push('包含特殊字符')

  const level: 'weak' | 'medium' | 'strong' =
    score <= 2 ? 'weak' : score <= 4 ? 'medium' : 'strong'

  return { score, level, suggestions }
}

/**
 * 生成安全随机字符串
 */
export function generateSecureToken(length = 32): string {
  const array = new Uint8Array(length)
  crypto.getRandomValues(array)
  return Array.from(array, byte => byte.toString(16).padStart(2, '0')).join('')
}

/**
 * 会话管理
 */
class SessionManager {
  private sessionId: string | null = null
  private expiresAt: number = 0
  private readonly SESSION_TIMEOUT = 30 * 60 * 1000 // 30分钟

  create(): string {
    this.sessionId = generateSecureToken()
    this.expiresAt = Date.now() + this.SESSION_TIMEOUT
    secureStorage.setItem('session', {
      id: this.sessionId,
      expiresAt: this.expiresAt,
    })
    return this.sessionId
  }

  get(): string | null {
    const session = secureStorage.getItem<{ id: string; expiresAt: number }>('session')
    if (!session) return null

    if (Date.now() > session.expiresAt) {
      this.destroy()
      return null
    }

    this.sessionId = session.id
    this.expiresAt = session.expiresAt
    return this.sessionId
  }

  refresh(): void {
    if (this.sessionId) {
      this.expiresAt = Date.now() + this.SESSION_TIMEOUT
      secureStorage.setItem('session', {
        id: this.sessionId,
        expiresAt: this.expiresAt,
      })
    }
  }

  destroy(): void {
    this.sessionId = null
    this.expiresAt = 0
    secureStorage.removeItem('session')
  }

  isValid(): boolean {
    return this.get() !== null
  }
}

export const sessionManager = new SessionManager()

export default {
  encrypt,
  decrypt,
  encryptObject,
  decryptObject,
  secureStorage,
  escapeHtml,
  sanitizeHtml,
  checkCSP,
  generateCSP,
  validateInput,
  maskSensitiveData,
  checkPasswordStrength,
  generateSecureToken,
  sessionManager,
}
