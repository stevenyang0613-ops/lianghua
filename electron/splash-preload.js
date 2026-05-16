const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  getAppInfo: () => ({
    version: process.env.npm_package_version || '1.0.0',
    platform: process.platform,
  }),
})
