# 组件文档

## 基础组件

### BaseChart

图表基础组件，封装 ECharts 通用功能。

**Props**:
| 属性 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| option | EChartsOption | 是 | - | 图表配置 |
| style | CSSProperties | 否 | - | 容器样式 |
| loading | boolean | 否 | false | 加载状态 |
| theme | string | 否 | 'light' | 主题 |
| onChartReady | function | 否 | - | 图表就绪回调 |

**使用示例**:
```tsx
import { BaseChart } from '@/components/charts'

function MyChart() {
  const option = {
    xAxis: { type: 'category', data: ['Mon', 'Tue', 'Wed'] },
    yAxis: { type: 'value' },
    series: [{ type: 'line', data: [120, 200, 150] }]
  }

  return <BaseChart option={option} style={{ height: 300 }} />
}
```

### KlineChart

K线图组件，专门用于展示股票/债券K线数据。

**Props**:
| 属性 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| data | KlineData[] | 是 | - | K线数据 |
| showVolume | boolean | 否 | true | 显示成交量 |
| showMA | number[] | 否 | [5,10,20] | MA均线周期 |
| height | number/string | 否 | 400 | 图表高度 |

**数据格式**:
```typescript
interface KlineData {
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
}
```

## 表格组件

### AdvancedTable

高级数据表格，支持筛选、排序、编辑等功能。

**Props**:
| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| columns | AdvancedTableColumn[] | 是 | 列配置 |
| dataSource | T[] | 是 | 数据源 |
| rowKey | string/function | 是 | 行唯一标识 |
| selectable | boolean | 否 | 是否可选择 |
| onSelectionChange | function | 否 | 选择变化回调 |
| onRowEdit | function | 否 | 行编辑回调 |
| onRowDelete | function | 否 | 行删除回调 |

**使用示例**:
```tsx
import { AdvancedTable } from '@/components/AdvancedTable'

const columns = [
  { key: 'code', title: '代码', dataIndex: 'code', sortable: true },
  { key: 'name', title: '名称', dataIndex: 'name', filterable: true },
  { key: 'price', title: '价格', dataIndex: 'price', editable: true }
]

function BondTable() {
  return (
    <AdvancedTable
      columns={columns}
      dataSource={bonds}
      rowKey="code"
      selectable
      onRowEdit={(key, field, value) => console.log(key, field, value)}
    />
  )
}
```

### VirtualTable

虚拟滚动表格，适用于大数据量场景。

**Props**:
| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| data | T[] | - | 数据 |
| rowHeight | number | 48 | 行高 |
| visibleRows | number | 20 | 可见行数 |
| overscan | number | 5 | 缓冲行数 |

## 编辑器组件

### RichTextEditor

富文本编辑器，支持常见格式化操作。

**Props**:
| 属性 | 类型 | 说明 |
|------|------|------|
| value | string | HTML 内容 |
| onChange | function | 内容变化回调 |
| height | number | 编辑器高度 |
| toolbar | string[] | 工具栏配置 |
| onImageUpload | function | 图片上传处理 |

**工具栏配置**:
```tsx
const toolbar = [
  'bold', 'italic', 'underline', 'strikeThrough',
  '|', 'formatBlock', 'fontSize',
  '|', 'justifyLeft', 'justifyCenter', 'justifyRight',
  '|', 'insertOrderedList', 'insertUnorderedList',
  '|', 'link', 'image', 'code',
]
```

### ThemeEditor

主题编辑器，可视化配置应用主题。

**Props**:
| 属性 | 类型 | 说明 |
|------|------|------|
| open | boolean | 是否显示 |
| onClose | function | 关闭回调 |
| value | ThemeConfig | 当前主题配置 |
| onChange | function | 主题变化回调 |
| onSave | function | 保存回调 |

## 功能组件

### PerformanceMonitor

性能监控面板，实时展示 FPS、内存、网络状态。

**特性**:
- FPS 实时监控
- 内存使用趋势
- 网络请求追踪
- 可折叠详情面板

**配置**:
```tsx
import { usePerformanceStore } from '@/stores/usePerformanceStore'

// 启用/禁用监控
usePerformanceStore.getState().setEnabled(true)

// 设置警告阈值
usePerformanceStore.getState().setFpsWarningThreshold(30)
```

### ErrorBoundary

错误边界组件，捕获子组件错误并显示友好提示。

**Props**:
| 属性 | 类型 | 说明 |
|------|------|------|
| fallback | ReactNode | 自定义错误 UI |
| onError | function | 错误回调 |
| onRetry | function | 重试回调 |
| maxRetries | number | 最大重试次数 |
| showReport | boolean | 显示上报按钮 |

**使用示例**:
```tsx
import ErrorBoundary from '@/components/ErrorBoundary'

function App() {
  return (
    <ErrorBoundary
      fallback={<div>出错了</div>}
      maxRetries={3}
      onRetry={() => window.location.reload()}
    >
      <MyComponent />
    </ErrorBoundary>
  )
}
```

## Hooks

### useDragSort

拖拽排序 Hook。

**返回值**:
| 属性 | 类型 | 说明 |
|------|------|------|
| getItemProps | function | 获取项目属性 |
| getHandleProps | function | 获取拖拽手柄属性 |
| moveItem | function | 移动项目 |
| isDragging | boolean | 是否正在拖拽 |

**使用示例**:
```tsx
import { useDragSort } from '@/hooks/useDragSort'

function SortableList({ items, onReorder }) {
  const { getItemProps, isDragging } = useDragSort({
    items,
    onReorder
  })

  return (
    <div>
      {items.map(item => (
        <div key={item.id} {...getItemProps(item)}>
          {item.name}
        </div>
      ))}
    </div>
  )
}
```

### useLazyImage

图片懒加载 Hook。

**返回值**:
| 属性 | 类型 | 说明 |
|------|------|------|
| ref | RefObject | 图片元素引用 |
| state | object | 加载状态 |
| onLoad | function | 加载完成回调 |

### useFileDrop

文件拖放 Hook。

**返回值**:
| 属性 | 类型 | 说明 |
|------|------|------|
| dropRef | RefObject | 放置区域引用 |
| isDragging | boolean | 是否正在拖拽 |
| files | DroppedFile[] | 已放置文件 |
| openFileDialog | function | 打开文件选择 |
| removeFile | function | 移除文件 |

## 工具函数

### validators

表单验证规则集合。

**内置验证器**:
- `required` - 必填验证
- `email` - 邮箱验证
- `phone` - 手机号验证
- `minLength` / `maxLength` - 长度验证
- `min` / `max` / `range` - 数值范围验证
- `password` - 密码强度验证
- `stockCode` / `bondCode` - 股票/债券代码验证

**使用示例**:
```tsx
import { validators, compose } from '@/utils/formValidation'

const validateName = compose(
  validators.required('请输入名称'),
  validators.minLength(2),
  validators.maxLength(20)
)

const result = validateName('test')
```

### clipboard

剪贴板工具。

**方法**:
- `copyText(text)` - 复制文本
- `copyHTML(html)` - 复制富文本
- `copyImage(url)` - 复制图片
- `readText()` - 读取文本
- `getHistory()` - 获取历史记录
