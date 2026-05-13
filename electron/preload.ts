import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  isElectron: true,
  showNotification: (title: string, body: string) =>
    ipcRenderer.invoke('show-notification', { title, body }),
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
})
