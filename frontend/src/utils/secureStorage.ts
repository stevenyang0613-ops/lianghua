/**
 * 安全存储工具
 * 使用 Electron safeStorage API 加密敏感数据（API Key、Secret 等）
 * 非 Electron 环境降级为 localStorage 明文存储
 */

const ENCRYPTED_PREFIX = 'enc:'

function isElectron(): boolean {
  return !!window.electronAPI?.isElectron
}

export async function secureSave(key: string, value: string): Promise<void> {
  if (!value) {
    localStorage.removeItem(key)
    return
  }

  if (isElectron() && window.electronAPI?.encryptString) {
    try {
      const encrypted = await window.electronAPI.encryptString(value)
      localStorage.setItem(key, ENCRYPTED_PREFIX + encrypted)
      return
    } catch {
      // 加密失败，降级为明文存储
    }
  }

  localStorage.setItem(key, value)
}

export async function secureLoad(key: string): Promise<string> {
  const stored = localStorage.getItem(key)
  if (!stored) return ''

  if (stored.startsWith(ENCRYPTED_PREFIX) && isElectron() && window.electronAPI?.decryptString) {
    try {
      const cipherText = stored.slice(ENCRYPTED_PREFIX.length)
      return await window.electronAPI.decryptString(cipherText)
    } catch {
      // 解密失败，返回加密后的原始文本（不可用）
      return stored.slice(ENCRYPTED_PREFIX.length)
    }
  }

  return stored
}

export async function secureRemove(key: string): Promise<void> {
  localStorage.removeItem(key)
}
