import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  // 使用相对路径，支持 Electron 打包
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
      '@shared': path.resolve(__dirname, '../shared'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
  build: {
    // 代码分割配置
    rollupOptions: {
      output: {
      },
    },
    // 降低警告阈值以持续监控 chunk 大小
    chunkSizeWarningLimit: 600,
    // 启用压缩
    minify: 'esbuild',
    // 分离 CSS
    cssCodeSplit: true,
  },
})
