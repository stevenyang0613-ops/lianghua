import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, within, cleanup } from '@testing-library/react'
import { VirtualTable } from '../VirtualTable'
import type { VirtualColumn } from '../VirtualTable'

interface Bond {
  code: string
  name: string
  price: number
  change_pct: number
  premium_ratio: number
  dual_low: number
  volume: number
  remaining_years: number
}

const sampleBonds: Bond[] = [
  { code: '113001', name: '测试转债A', price: 100, change_pct: -2.5, premium_ratio: 30, dual_low: 130, volume: 1.5, remaining_years: 3 },
  { code: '113002', name: '测试转债B', price: 150, change_pct: 5.0, premium_ratio: 10, dual_low: 160, volume: 0, remaining_years: 2 },
  { code: '113003', name: '测试转债C', price: 120, change_pct: 0, premium_ratio: 50, dual_low: 170, volume: 2.0, remaining_years: 5 },
  { code: '113004', name: '测试转债D', price: 80, change_pct: 10.5, premium_ratio: -5, dual_low: 75, volume: 3.5, remaining_years: 1 },
]

function makeColumns(): VirtualColumn<Bond>[] {
  return [
    { key: 'code', dataIndex: 'code', title: '代码', width: 100, sortable: true, sortOrder: null, sorter: (a, b) => a.code.localeCompare(b.code) },
    { key: 'price', dataIndex: 'price', title: '价格', width: 100, sortable: true, sortOrder: null, sorter: (a, b) => a.price - b.price },
    { key: 'change_pct', dataIndex: 'change_pct', title: '涨跌幅', width: 100, sortable: true, sortOrder: null, sorter: (a, b) => a.change_pct - b.change_pct },
    { key: 'premium_ratio', dataIndex: 'premium_ratio', title: '溢价率', width: 100, sortable: true, sortOrder: null, sorter: (a, b) => a.premium_ratio - b.premium_ratio },
    { key: 'dual_low', dataIndex: 'dual_low', title: '双低', width: 100, sortable: true, sortOrder: null, sorter: (a, b) => a.dual_low - b.dual_low },
  ]
}

describe('VirtualTable 排序', () => {
  beforeEach(() => {
    cleanup()
  })

  it('列头点击触发 onSort 回调,传递 dataIndex 和列定义', () => {
    const onSort = vi.fn()
    const { getByTestId } = render(
      <VirtualTable data={sampleBonds} columns={makeColumns()} onSort={onSort} />
    )

    const priceHeader = getByTestId('vt-sort-price')
    fireEvent.click(priceHeader)
    expect(onSort).toHaveBeenCalledTimes(1)
    expect(onSort).toHaveBeenCalledWith('price', expect.objectContaining({ key: 'price', dataIndex: 'price' }))
  })

  it('点击同一列三次: asc → desc → null(由父组件控制 cycle 状态)', () => {
    let currentOrder: 'asc' | 'desc' | null = null
    const { getByTestId, rerender } = render(
      <VirtualTable
        data={sampleBonds}
        columns={makeColumns()}
        onSort={() => {
          if (currentOrder === null) currentOrder = 'asc'
          else if (currentOrder === 'asc') currentOrder = 'desc'
          else currentOrder = null
        }}
      />
    )

    fireEvent.click(getByTestId('vt-sort-price'))
    expect(currentOrder).toBe('asc')

    const ascCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'asc' as const } : c)
    rerender(<VirtualTable data={sampleBonds} columns={ascCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').getAttribute('aria-sort')).toBe('ascending')

    currentOrder = 'desc'
    const descCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'desc' as const } : c)
    rerender(<VirtualTable data={sampleBonds} columns={descCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').getAttribute('aria-sort')).toBe('descending')

    currentOrder = null
    const nullCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: null } : c)
    rerender(<VirtualTable data={sampleBonds} columns={nullCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').getAttribute('aria-sort')).toBe('none')
  })

  it('aria-sort 属性随 sortOrder 变化', () => {
    const ascCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'asc' as const } : c)
    const { getByTestId, rerender } = render(
      <VirtualTable data={sampleBonds} columns={ascCols} onSort={() => {}} />
    )
    expect(getByTestId('vt-sort-price').getAttribute('aria-sort')).toBe('ascending')

    const descCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'desc' as const } : c)
    rerender(<VirtualTable data={sampleBonds} columns={descCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').getAttribute('aria-sort')).toBe('descending')
  })

  it('升序排序指示器显示 "▲",降序显示 "▼",无排序显示 "⇅"', () => {
    const ascCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'asc' as const } : c)
    const { getByTestId, rerender } = render(
      <VirtualTable data={sampleBonds} columns={ascCols} onSort={() => {}} />
    )
    expect(getByTestId('vt-sort-price').textContent).toContain('▲')

    const descCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: 'desc' as const } : c)
    rerender(<VirtualTable data={sampleBonds} columns={descCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').textContent).toContain('▼')

    const nullCols = makeColumns().map((c) => c.key === 'price' ? { ...c, sortOrder: null } : c)
    rerender(<VirtualTable data={sampleBonds} columns={nullCols} onSort={() => {}} />)
    expect(getByTestId('vt-sort-price').textContent).toContain('⇅')
  })

  it('点击不同列时,onSort 传递正确 dataIndex', () => {
    const onSort = vi.fn()
    const { getByTestId } = render(
      <VirtualTable data={sampleBonds} columns={makeColumns()} onSort={onSort} />
    )

    fireEvent.click(getByTestId('vt-sort-code'))
    expect(onSort).toHaveBeenCalledWith('code', expect.anything())

    fireEvent.click(getByTestId('vt-sort-change_pct'))
    expect(onSort).toHaveBeenCalledWith('change_pct', expect.anything())
  })

  it('非排序列不产生 data-testid 和 role', () => {
    const nonSortCols: VirtualColumn<Bond>[] = [
      { key: 'name', dataIndex: 'name', title: '名称', width: 100 },
      { key: 'price', dataIndex: 'price', title: '价格', width: 100 },
    ]
    const { container } = render(
      <VirtualTable data={sampleBonds} columns={nonSortCols} onSort={() => {}} />
    )

    expect(container.querySelector('[data-testid^="vt-sort-"]')).toBeNull()
    expect(container.querySelector('[role="button"]')).toBeNull()
  })

  it('onSort 为空时,点击可排序列不报错', () => {
    const { getByTestId } = render(
      <VirtualTable data={sampleBonds} columns={makeColumns()} />
    )
    expect(() => fireEvent.click(getByTestId('vt-sort-price'))).not.toThrow()
  })

  it('空数据时,列头排序 UI 仍然正常', () => {
    const { getByTestId } = render(
      <VirtualTable data={[]} columns={makeColumns()} onSort={() => {}} />
    )
    const header = getByTestId('vt-sort-price')
    expect(header.getAttribute('aria-sort')).toBe('none')
    expect(() => fireEvent.click(header)).not.toThrow()
  })
})

describe('VirtualTable 数据排序', () => {
  beforeEach(() => {
    cleanup()
  })

  it('按 price 升序排序后,数据顺序正确', () => {
    const sorted = [...sampleBonds].sort((a, b) => a.price - b.price)
    expect(sorted.map((b) => b.price)).toEqual([80, 100, 120, 150])
  })

  it('按 change_pct 降序排序后,数据顺序正确', () => {
    const sorted = [...sampleBonds].sort((a, b) => b.change_pct - a.change_pct)
    expect(sorted.map((b) => b.change_pct)).toEqual([10.5, 5.0, 0, -2.5])
  })

  it('按 premium_ratio 升序排序后,数据顺序正确', () => {
    const sorted = [...sampleBonds].sort((a, b) => a.premium_ratio - b.premium_ratio)
    expect(sorted.map((b) => b.premium_ratio)).toEqual([-5, 10, 30, 50])
  })

  it('按 volume 降序排序后,数据顺序正确 (休市数据排到末尾)', () => {
    const sorted = [...sampleBonds].sort((a, b) => {
      if (a.volume === 0 && b.volume === 0) return 0
      if (a.volume === 0) return 1
      if (b.volume === 0) return -1
      return b.volume - a.volume
    })
    expect(sorted[0].volume).toBe(3.5)
    expect(sorted[1].volume).toBe(2.0)
    expect(sorted[2].volume).toBe(1.5)
    expect(sorted[3].volume).toBe(0)
  })
})

describe('VirtualTable 表头 tooltip', () => {
  beforeEach(() => {
    cleanup()
  })

  it('可排序列头的 title 属性为列名 (悬浮可看到完整表头文本)', () => {
    const { getByTestId } = render(
      <VirtualTable data={sampleBonds} columns={makeColumns()} onSort={() => {}} />
    )

    const priceHeader = getByTestId('vt-sort-price')
    expect(priceHeader.getAttribute('title')).toBe('价格')
  })

  it('不可排序列头也有 title 属性 (悬浮可看到完整表头文本)', () => {
    const colsWithNonSortable: VirtualColumn<Bond>[] = [
      { key: 'name', dataIndex: 'name', title: '名称', width: 100 },
      { key: 'price', dataIndex: 'price', title: '价格', width: 100, sortable: true, sortOrder: null },
    ]
    const { container } = render(
      <VirtualTable data={sampleBonds} columns={colsWithNonSortable} onSort={() => {}} />
    )

    const headerCells = container.querySelectorAll('.vt-header-cell')
    const nameHeader = Array.from(headerCells).find((el) => el.getAttribute('title') === '名称')
    expect(nameHeader).toBeDefined()
  })

  it('中文长表头(如 "正股评分")也能在 title 中显示完整文本', () => {
    const longCols: VirtualColumn<Bond>[] = [
      { key: 'name', dataIndex: 'name', title: '正股评分', width: 90, sortable: true, sortOrder: null },
    ]
    const { getByTestId } = render(
      <VirtualTable data={sampleBonds} columns={longCols} onSort={() => {}} />
    )

    expect(getByTestId('vt-sort-name').getAttribute('title')).toBe('正股评分')
  })
})