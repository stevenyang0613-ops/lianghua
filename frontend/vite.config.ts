import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
// import { echartsSafePlugin } from './vite-plugin-echarts-safe'

export default defineConfig({
  base: './',
  plugins: [
    react(),
    // echartsSafePlugin(),
    {
      name: 'remove-crossorigin',
      transformIndexHtml(html: string) {
        // Remove crossorigin attributes (not needed for same-origin HTTP server)
        let result = html.replace(/\s+crossorigin/g, '')
        return result
      },
    },
  ],
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
    // When served via local HTTP server (port 8766), we can use ES module code splitting.
    // Electron file:// protocol doesn't support ES modules, so we keep IIFE as fallback.
    // The frontend server in main.ts serves the dist output over HTTP.
    modulePreload: false,
    rollupOptions: {
      output: {
        format: 'es',
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
        manualChunks(id) {
          // Split large dependencies into separate chunks for parallel loading
          // IMPORTANT: DO NOT split packages that import from each other into separate
          // chunks — this creates circular ES module dependencies that cause runtime
          // 'undefined' errors (e.g. React.createContext on undefined).
          // vendor-misc, vendor-react, and vendor-antd all import from each other
          // (circular deps), so they must stay in the SAME chunk: vendor-core.
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
            return 'vendor-echarts'
          }
          // Merge all packages that have mutual imports into a single chunk
          // to avoid circular ES module dependency issues at runtime
          if (id.includes('node_modules/antd') || id.includes('node_modules/@ant-design') ||
              id.includes('node_modules/react') || id.includes('node_modules/react-dom') || id.includes('node_modules/scheduler') ||
              id.includes('node_modules/@reduxjs') || id.includes('node_modules/redux') || id.includes('node_modules/zustand') ||
              id.includes('node_modules/echarts-for-react') ||
              id.includes('node_modules')) {
            return 'vendor-core'
          }
          if (id.includes('node_modules/dayjs')) {
            return 'vendor-dayjs'
          }
        },
      },
    },
    chunkSizeWarningLimit: 1000,
    minify: 'esbuild',
    cssCodeSplit: true,
  },
})
