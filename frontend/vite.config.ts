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
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return;
          // React 核心
          if (id.includes('/react-dom/') || id.includes('/react-router-dom/')) return 'react-vendor';
          if (id.includes('/react/')) return 'react-vendor';
          // Ant Design 拆分：图标与核心基础设施
          if (id.includes('/@ant-design/icons/')) return 'antd-icons';
          if (id.includes('/@ant-design/cssinjs/') || id.includes('/@ant-design/static-function/')) return 'antd-core';
          // rc-* 组件单独成块（antd 底层依赖）
          if (id.includes('/rc-')) return 'antd-rc';
          // antd 重型组件拆分
          if (id.includes('/antd/es/date-picker/') || id.includes('/antd/es/calendar/') || id.includes('/antd/es/time-picker/')) return 'antd-date';
          if (id.includes('/antd/es/table/') || id.includes('/antd/es/list/')) return 'antd-table';
          if (id.includes('/antd/es/form/') || id.includes('/antd/es/input/') || id.includes('/antd/es/input-number/')) return 'antd-form';
          if (id.includes('/antd/es/select/') || id.includes('/antd/es/cascader/') || id.includes('/antd/es/tree-select/') || id.includes('/antd/es/mentions/')) return 'antd-select';
          if (id.includes('/antd/es/tree/') || id.includes('/antd/es/upload/') || id.includes('/antd/es/transfer/')) return 'antd-tree';
          if (id.includes('/antd/es/modal/') || id.includes('/antd/es/drawer/') || id.includes('/antd/es/popover/') || id.includes('/antd/es/popconfirm/')) return 'antd-overlay';
          if (id.includes('/antd/es/tabs/') || id.includes('/antd/es/menu/') || id.includes('/antd/es/dropdown/')) return 'antd-nav';
          if (id.includes('/antd/es/typography/')) return 'antd-typography';
          if (id.includes('/antd/es/color-picker/')) return 'antd-color';
          if (id.includes('/antd/es/theme/') || id.includes('/antd/es/config-provider/') || id.includes('/antd/es/style/')) return 'antd-theme';
          // antd 中型组件拆分
          if (id.includes('/antd/es/skeleton/') || id.includes('/antd/es/spin/') || id.includes('/antd/es/progress/') || id.includes('/antd/es/statistic/')) return 'antd-feedback';
          if (id.includes('/antd/es/checkbox/') || id.includes('/antd/es/radio/') || id.includes('/antd/es/switch/') || id.includes('/antd/es/slider/') || id.includes('/antd/es/rate/')) return 'antd-controls';
          if (id.includes('/antd/es/button/') || id.includes('/antd/es/badge/') || id.includes('/antd/es/tag/') || id.includes('/antd/es/avatar/') || id.includes('/antd/es/tooltip/')) return 'antd-basic';
          if (id.includes('/antd/es/collapse/') || id.includes('/antd/es/card/') || id.includes('/antd/es/descriptions/') || id.includes('/antd/es/pagination/')) return 'antd-display';
          if (id.includes('/antd/es/alert/') || id.includes('/antd/es/result/') || id.includes('/antd/es/empty/') || id.includes('/antd/es/watermark/')) return 'antd-status';
          if (id.includes('/antd/es/message/') || id.includes('/antd/es/notification/')) return 'antd-notify';
          if (id.includes('/antd/es/layout/') || id.includes('/antd/es/grid/') || id.includes('/antd/es/space/') || id.includes('/antd/es/divider/') || id.includes('/antd/es/flex/')) return 'antd-layout';
          if (id.includes('/antd/es/anchor/') || id.includes('/antd/es/breadcrumb/') || id.includes('/antd/es/steps/') || id.includes('/antd/es/segmented/')) return 'antd-nav-extra';
          if (id.includes('/antd/es/image/') || id.includes('/antd/es/float-button/')) return 'antd-media';
          if (id.includes('/antd/') || id.includes('/@ant-design/')) return 'antd';
          // ECharts 拆分：chart 按常用/高级分组，避免单块过大
          if (id.includes('/echarts/lib/chart/bar/') || id.includes('/echarts/lib/chart/line/') || id.includes('/echarts/lib/chart/pie/') || id.includes('/echarts/lib/chart/scatter/') || id.includes('/echarts/lib/chart/candlestick/') || id.includes('/echarts/lib/chart/helper/')) return 'echarts-basic';
          if (id.includes('/echarts/lib/chart/treemap/') || id.includes('/echarts/lib/chart/tree/') || id.includes('/echarts/lib/chart/sunburst/') || id.includes('/echarts/lib/chart/graph/')) return 'echarts-hierarchy';
          if (id.includes('/echarts/lib/chart/')) return 'echarts-special';
          if (id.includes('/echarts/lib/component/')) return 'echarts-components';
          if (id.includes('/echarts/')) return 'echarts-core';
          if (id.includes('/zrender/')) return 'zrender';
          // 其他库
          if (id.includes('/zustand/')) return 'zustand';
          if (id.includes('/dayjs/')) return 'utils';
          if (id.includes('/lodash/')) return 'vendor';
          // 兜底：其余 node_modules 统一归入 vendor
          return 'vendor';
        },
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
