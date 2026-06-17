/**
 * ECharts 按需导入配置
 * 所有需要echarts的组件都应从此模块导入，避免全量导入
 */
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart, RadarChart, GaugeChart, CandlestickChart, ScatterChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, DataZoomComponent, ToolboxComponent,
  MarkLineComponent, MarkPointComponent, VisualMapComponent,
} from 'echarts/components'
import { HeatmapChart } from 'echarts/charts'

echarts.use([
  CanvasRenderer,
  BarChart, LineChart, PieChart, RadarChart, GaugeChart, CandlestickChart, ScatterChart, HeatmapChart,
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, DataZoomComponent, ToolboxComponent,
  MarkLineComponent, MarkPointComponent, VisualMapComponent,
])

export default echarts
