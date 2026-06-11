import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('splashAPI', {
  onProgress: (callback: (data: { percent: number; message: string }) => void) => {
    ipcRenderer.on('startup-progress', (_event, data: { percent: number; message: string }) => {
      callback(data)
    })
  },
  onError: (callback: (data: { message: string }) => void) => {
    ipcRenderer.on('startup-error', (_event, data: { message: string }) => {
      callback(data)
    })
  },
})
