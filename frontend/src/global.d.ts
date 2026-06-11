interface Window {
  electronAPI: any
}

interface ElectronAPI {
  httpRequest(method: string, url: string, body?: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  showNotification(title: string, body: string): Promise<void>
  platform: string
  encryptString(plainText: string): Promise<string>
  decryptString(cipherText: string): Promise<string>
  wsConnect(wsId: string, url: string): Promise<{ ok: boolean; state: string; error?: string }>
  wsClose(wsId: string): Promise<{ ok: boolean }>
  checkForUpdates(): Promise<{ available: boolean; version?: string; error?: string }>
  [key: string]: any
}