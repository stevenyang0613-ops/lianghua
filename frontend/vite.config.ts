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
      name: 'remove-crossorigin-and-module',
      transformIndexHtml(html: string) {
        // 去掉crossorigin和type="module"（IIFE格式不需要，file://下会导致CORS错误）
        let result = html.replace(/\s+crossorigin/g, '').replace(/ type="module"/g, '')
        // 将head中的script移到body末尾：去掉type="module"后普通script在head中同步执行，
        // 此时body未解析，React createRoot找不到root元素（error #299）
        const scriptMatch = result.match(/<script (src="[^"]*")><\/script>/)
        if (scriptMatch) {
          result = result.replace(/<script src="[^"]*"><\/script>/, '')
          result = result.replace('</body>', `<script ${scriptMatch[1]}></script>\n</body>`)
        }
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
    // Electron file:// 协议下 ES module code splitting 会引发循环依赖问题
    // 使用 IIFE 格式打包为单个文件，彻底避免所有模块加载问题
    modulePreload: false,
    rollupOptions: {
      output: {
        format: 'iife',
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
        // IIFE 格式不支持 code splitting，所有代码打包到单个入口
        inlineDynamicImports: true,
      },
    },
    chunkSizeWarningLimit: 3000,
    minify: 'esbuild',
    cssCodeSplit: false,
  },
})
