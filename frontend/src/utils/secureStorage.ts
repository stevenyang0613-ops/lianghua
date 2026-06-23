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
    try { localStorage.removeItem(key) } catch { /* silent fail */ }
    return
  }

  if (isElectron() && window.electronAPI?.encryptString) {
    try {
      const encrypted = await window.electronAPI.encryptString(value)
      try { localStorage.setItem(key, ENCRYPTED_PREFIX + encrypted) } catch { /* silent fail */ }
      return
    } catch {
      // 加密失败，不降级为明文存储，抛出错误让调用者处理
      throw new Error(`secureSave failed: encryption unavailable for key "${key}"`)
    }
  }

  // 非 Electron 环境：如果未配置加密，拒绝存储敏感数据
  throw new Error(`secureSave failed: no encryption available for key "${key}"`)
}

export async function secureLoad(key: string): Promise<string> {
  try {
    const stored = localStorage.getItem(key)
    if (!stored) return ''

    if (stored.startsWith(ENCRYPTED_PREFIX) && isElectron() && window.electronAPI?.decryptString) {
      try {
        const cipherText = stored.slice(ENCRYPTED_PREFIX.length)
        return await window.electronAPI.decryptString(cipherText)
      } catch {
        // 解密失败时不返回密文，避免调用者误用
        console.error('[SecureStorage] Decrypt failed for key:', key)
        return ''
      }
    }

    return stored
  } catch { return '' }
}

export async function secureRemove(key: string): Promise<void> {
  try { localStorage.removeItem(key) } catch { /* silent fail */ }
}
