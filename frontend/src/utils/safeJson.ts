/**
 * 安全 JSON 解析工具
 * 防止 corrupted localStorage 数据导致页面崩溃
 */

export function safeJsonParse<T>(json: string | null | undefined, fallback: T): T {
  if (!json) return fallback
  try {
    return JSON.parse(json) as T
  } catch (e) {
    console.warn('[safeJsonParse] Failed to parse JSON, using fallback:', e)
    return fallback
  }
}

export function safeGetStorage<T>(key: string, fallback: T): T {
  try {
    const saved = localStorage.getItem(key)
    return safeJsonParse<T>(saved, fallback)
  } catch {
    return fallback
  }
}

export function safeGetStorageItem(key: string, fallback: string = ''): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
