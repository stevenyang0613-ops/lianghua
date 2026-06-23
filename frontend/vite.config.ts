import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'
// import { echartsSafePlugin } from './vite-plugin-echarts-safe'

// 从 tsconfig.json 读取 target，确保 vite build.target 与 tsc 一致
// 支持 JSONC（带注释的 tsconfig）：先剥离单行/多行注释，再 JSON.parse
// 注意：简单正则剥离不支持字符串内含 "//" 或 "/*" 的罕见场景，
// 但 tsconfig 的 key/value 不会出现这种情况
function stripJsonComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')   // 多行注释 /* ... */
    .replace(/\/\/.*$/gm, '')            // 单行注释 //
}
const tsconfigRaw = readFileSync(path.resolve(__dirname, 'tsconfig.json'), 'utf-8')
const tsconfig = JSON.parse(stripJsonComments(tsconfigRaw))
if (tsconfig.extends) {
  console.warn('[vite.config] tsconfig.json uses "extends" — target may not be resolved correctly. Consider using typescript.readConfigFile() instead.')
}
const tsTarget = tsconfig.compilerOptions?.target?.toLowerCase() || 'es2021'

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
      '/health': 'http://127.0.0.1:8765',
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
      '/api/v1/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
  build: {
    // Build target synced from tsconfig.json (currently ES2021 for Promise.any support).
    // Required: Chrome 85+, Firefox 79+, Safari 14+, Edge 85+
    target: tsTarget,
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
    // vendor-echarts ~1MB 也已经按需加载：ECharts 的所有使用方（TimingSignal、
    // SectorRotation、AnalyticsDashboard 等）都通过 React.lazy 路由进入，
    // 不会出现在首屏下载中。
    chunkSizeWarningLimit: 1000, // KB (Vite/Rollup 文档约定单位为 KB)
    // vendor-core ~1.5MB 是有意为之：拆分 antd/react/zustand 会引发 ES module 循环
    // 依赖错误（详见 manualChunks 注释）。已通过 HTTP chunked delivery + browser cache
    // 缓解首屏加载问题；若未来用户量增长，可考虑 SSR 或动态 import 重型页面。
    // 进一步缩减：107 个文件使用 `from 'antd'`，antd 5+ ESM 已原生支持 tree-shaking，
    // 但 vendor-core 仍包含整个 antd 的 CSS reset/全局样式。若想进一步拆分，
    // 可考虑 antd-style 或 unplugin-vue-components 的按需编译方案。
    minify: 'esbuild',
    cssCodeSplit: true,
  },
})
