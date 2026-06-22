/**
 * 打印服务
 * 打印样式优化，分页控制，打印预览
 */

interface PrintOptions {
  title?: string
  orientation?: 'portrait' | 'landscape'
  paperSize?: 'A4' | 'A3' | 'Letter'
  margins?: {
    top?: string
    right?: string
    bottom?: string
    left?: string
  }
  header?: string
  footer?: string
  includeStyles?: boolean
  beforePrint?: () => void
  afterPrint?: () => void
}

const defaultOptions: PrintOptions = {
  title: document.title,
  orientation: 'portrait',
  paperSize: 'A4',
  margins: { top: '10mm', right: '10mm', bottom: '10mm', left: '10mm' },
  includeStyles: true,
}

/**
 * 打印 HTML 元素
 */
export async function printElement(
  element: HTMLElement | string,
  options: PrintOptions = {}
): Promise<void> {
  const opts = { ...defaultOptions, ...options }

  // 获取要打印的元素
  const targetElement = typeof element === 'string' 
    ? document.querySelector(element) as HTMLElement 
    : element

  if (!targetElement) {
    throw new Error('打印目标元素不存在')
  }

  // 执行打印前回调
  opts.beforePrint?.()

  // 创建打印窗口
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    throw new Error('无法打开打印窗口，请检查浏览器弹窗设置')
  }

  // 生成打印样式
  const printStyles = generatePrintStyles(opts)

  // 构建打印内容
  const printContent = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>${opts.title}</title>
  ${opts.includeStyles ? extractStyles() : ''}
  <style>
    ${printStyles}
  </style>
</head>
<body>
  ${opts.header ? `<div class="print-header">${opts.header}</div>` : ''}
  <div class="print-content">
    ${targetElement.outerHTML}
  </div>
  ${opts.footer ? `<div class="print-footer">${opts.footer}</div>` : ''}
  <script>
    window.onload = function() {
      window.print();
      window.onafterprint = function() {
        window.close();
      };
    };
  </script>
</body>
</html>
`

  printWindow.document.write(printContent)
  printWindow.document.close()

  // 监听打印完成（最多等待 60 秒，避免 interval 无限堆积）
  let elapsed = 0
  const CHECK_INTERVAL = 500
  const MAX_PRINT_WAIT_MS = 60_000
  const checkClosed = setInterval(() => {
    elapsed += CHECK_INTERVAL
    if (printWindow.closed || elapsed >= MAX_PRINT_WAIT_MS) {
      clearInterval(checkClosed)
      opts.afterPrint?.()
    }
  }, CHECK_INTERVAL)
}

/**
 * 生成打印样式
 */
function generatePrintStyles(options: PrintOptions): string {
  const pageSize = {
    'A4': '210mm 297mm',
    'A3': '297mm 420mm',
    'Letter': '8.5in 11in',
  }[options.paperSize || 'A4']

  return `
@page {
  size: ${pageSize} ${options.orientation};
  margin: ${options.margins?.top || '10mm'} ${options.margins?.right || '10mm'} ${options.margins?.bottom || '10mm'} ${options.margins?.left || '10mm'};
}

@media print {
  * {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  body {
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000;
  }

  .print-header {
    text-align: center;
    padding-bottom: 10px;
    margin-bottom: 10px;
    border-bottom: 1px solid #ddd;
    font-size: 14pt;
    font-weight: bold;
  }

  .print-content {
    clear: both;
  }

  .print-footer {
    text-align: center;
    padding-top: 10px;
    margin-top: 10px;
    border-top: 1px solid #ddd;
    font-size: 10pt;
    color: #666;
  }

  /* 避免分页断开 */
  table, figure, img {
    page-break-inside: avoid;
  }

  h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
  }

  /* 隐藏不需要打印的元素 */
  .no-print, .ant-btn, .ant-pagination, .ant-modal-close {
    display: none !important;
  }

  /* 表格样式 */
  table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1em;
  }

  th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: left;
  }

  th {
    background-color: #f5f5f5;
    font-weight: bold;
  }

  tr:nth-child(even) {
    background-color: #fafafa;
  }
}

@media screen {
  body {
    background: #f0f0f0;
    padding: 20px;
  }

  .print-content {
    background: #fff;
    padding: 20px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    max-width: 210mm;
    margin: 0 auto;
  }
}
`
}

/**
 * 提取页面样式
 */
function extractStyles(): string {
  const styles: string[] = []

  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) {
        styles.push(rule.cssText)
      }
    } catch (e) {
      // 跨域样式表会报错，忽略
    }
  }

  return `<style>${styles.join('\n')}</style>`
}

/**
 * 打印数据表格
 */
export function printTable<T extends Record<string, unknown>>(
  data: T[],
  columns: Array<{ key: string; title: string; render?: (value: unknown, row: T) => string }>,
  options: PrintOptions = {}
): void {
  const tableHtml = `
<table>
  <thead>
    <tr>
      ${columns.map(col => `<th>${col.title}</th>`).join('')}
    </tr>
  </thead>
  <tbody>
    ${data.map(row => `
      <tr>
        ${columns.map(col => {
          const value = row[col.key]
          const displayValue = col.render ? col.render(value, row) : String(value ?? '')
          return `<td>${displayValue}</td>`
        }).join('')}
      </tr>
    `).join('')}
  </tbody>
</table>
`

  const container = document.createElement('div')
  container.innerHTML = tableHtml
  document.body.appendChild(container)

  printElement(container, options).finally(() => {
    document.body.removeChild(container)
  })
}

/**
 * 打印预览
 */
export function printPreview(element: HTMLElement | string, options: PrintOptions = {}): void {
  printElement(element, { ...options, orientation: 'portrait' })
}

/**
 * 快速打印整个页面
 */
export function quickPrint(): void {
  window.print()
}

export default {
  printElement,
  printTable,
  printPreview,
  quickPrint,
}
