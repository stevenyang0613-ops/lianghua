/**
 * 高级数据表格组件
 * 行选择、排序、筛选、固定列、可编辑单元格
 */

import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { Table, Input, Select, Button, Space, Dropdown, Tag, Popconfirm } from 'antd'
import {
  EditOutlined,
  DeleteOutlined,
  PlusOutlined,
  DownloadOutlined,
  MoreOutlined,
} from '@ant-design/icons'
import type {
  TableProps,
  ColumnsType,
  TablePaginationConfig,
} from 'antd/es/table'

type FilterValue = (string | number | boolean)[]
type SorterResult<T> = {
  column?: import('antd/es/table').ColumnType<T>
  columnKey?: string
  field?: string
  order?: 'ascend' | 'descend' | null
}

export interface AdvancedTableColumn<T> {
  key: string
  title: string
  dataIndex: string
  width?: number
  fixed?: 'left' | 'right'
  sortable?: boolean
  filterable?: boolean
  editable?: boolean
  render?: (value: unknown, record: T, index: number) => React.ReactNode
  editor?: 'input' | 'select' | 'number'
  editorOptions?: { options?: Array<{ label: string; value: unknown }> }
}

export interface AdvancedTableProps<T extends Record<string, unknown>> {
  columns: AdvancedTableColumn<T>[]
  dataSource: T[]
  rowKey: string | ((record: T) => string)
  loading?: boolean
  pagination?: TablePaginationConfig | false
  selectable?: boolean
  onSelectionChange?: (selectedRowKeys: React.Key[], selectedRows: T[]) => void
  onRowEdit?: (key: React.Key, field: string, value: unknown) => void
  onRowDelete?: (key: React.Key) => void
  onRowAdd?: () => void
  onExport?: (data: T[]) => void
  scroll?: { x?: number; y?: number }
  size?: 'small' | 'middle' | 'large'
  bordered?: boolean
}

export function AdvancedTable<T extends Record<string, unknown>>({
  columns,
  dataSource,
  rowKey,
  loading,
  pagination,
  selectable,
  onSelectionChange,
  onRowEdit,
  onRowDelete,
  onRowAdd,
  onExport,
  scroll,
  size = 'middle',
  bordered = true,
}: AdvancedTableProps<T>) {
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [editingKey, setEditingKey] = useState<React.Key | null>(null)
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editingValue, setEditingValue] = useState<unknown>(null)
  const [filters, setFilters] = useState<Record<string, FilterValue | null>>({})
  const [sorter, setSorter] = useState<{ field?: string; order?: 'ascend' | 'descend' }>({})
  const inputRef = useRef<InstanceType<typeof Input>>(null)

  // 处理筛选后的数据
  const filteredData = useMemo(() => {
    let result = [...dataSource]

    // 应用筛选
    for (const [key, value] of Object.entries(filters)) {
      if (value && value.length > 0) {
        result = result.filter(item => value.includes(item[key] as FilterValue[number]))
      }
    }

    // 应用排序
    if (sorter.field && sorter.order) {
      result.sort((a, b) => {
        const aVal = a[sorter.field!] as string | number
        const bVal = b[sorter.field!] as string | number
        const comparison = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
        return sorter.order === 'ascend' ? comparison : -comparison
      })
    }

    return result
  }, [dataSource, filters, sorter])

  // 选择变化
  const handleSelectionChange = useCallback(
    (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys)
      const selectedRows = dataSource.filter(item =>
        newSelectedRowKeys.includes(typeof rowKey === 'function' ? rowKey(item) : (item[rowKey] as React.Key))
      )
      onSelectionChange?.(newSelectedRowKeys, selectedRows)
    },
    [dataSource, rowKey, onSelectionChange]
  )

  // 开始编辑
  const startEdit = useCallback((record: T, field: string) => {
    const key = typeof rowKey === 'function' ? rowKey(record) : (record[rowKey] as React.Key)
    setEditingKey(key)
    setEditingField(field)
    setEditingValue(record[field])
  }, [rowKey])

  // 保存编辑
  const saveEdit = useCallback(() => {
    if (editingKey !== null && editingField !== null) {
      onRowEdit?.(editingKey, editingField, editingValue)
      setEditingKey(null)
      setEditingField(null)
      setEditingValue(null)
    }
  }, [editingKey, editingField, editingValue, onRowEdit])

  // 取消编辑
  const cancelEdit = useCallback(() => {
    setEditingKey(null)
    setEditingField(null)
    setEditingValue(null)
  }, [])

  // 获取行 key
  const getKey = useCallback(
    (record: T): React.Key => {
      return typeof rowKey === 'function' ? rowKey(record) : (record[rowKey] as React.Key)
    },
    [rowKey]
  )

  // 自动聚焦输入框
  useEffect(() => {
    if (editingKey !== null && inputRef.current) {
      inputRef.current.focus()
    }
  }, [editingKey])

  // 转换列配置
  const tableColumns: ColumnsType<T> = useMemo(() => {
    return columns.map(col => {
      const isEditing = editingKey !== null && editingField === col.dataIndex

      return {
        key: col.key,
        title: col.title,
        dataIndex: col.dataIndex,
        width: col.width,
        fixed: col.fixed,
        sorter: col.sortable ? true : undefined,
        filterDropdown: col.filterable ? (
          <div style={{ padding: 8 }}>
            <Select
              style={{ width: 188 }}
              placeholder={`筛选 ${col.title}`}
              value={filters[col.dataIndex] as string[]}
              onChange={value => setFilters(prev => ({ ...prev, [col.dataIndex]: value }))}
              allowClear
              mode="multiple"
              options={Array.from(new Set(dataSource.map(d => d[col.dataIndex]))).map(v => ({
                label: String(v),
                value: v,
              }))}
            />
          </div>
        ) : undefined,
        render: (value, record, index) => {
          const recordKey = getKey(record)
          const isCurrentEditing = editingKey === recordKey && editingField === col.dataIndex

          if (isCurrentEditing && col.editable) {
            if (col.editor === 'select' && col.editorOptions?.options) {
              return (
                <Select
                  value={editingValue as string}
                  onChange={v => setEditingValue(v)}
                  onBlur={saveEdit}
                  style={{ width: '100%' }}
                  options={col.editorOptions.options}
                  autoFocus
                />
              )
            }

            return (
              <Input
                ref={inputRef as any}
                value={editingValue as string}
                onChange={e => setEditingValue(e.target.value)}
                onPressEnter={saveEdit}
                onBlur={saveEdit}
                onKeyDown={e => e.key === 'Escape' && cancelEdit()}
              />
            )
          }

          if (col.render) {
            return col.render(value, record, index)
          }

          return value
        },
        onCell: col.editable
          ? (record) => ({
              onClick: () => !editingKey && startEdit(record, col.dataIndex),
              style: { cursor: 'pointer' },
            })
          : undefined,
      }
    })
  }, [columns, editingKey, editingField, editingValue, filters, dataSource, getKey, startEdit, saveEdit, cancelEdit])

  // 操作列
  const actionColumn = onRowDelete
    ? [
        {
          key: 'action',
          title: '操作',
          dataIndex: 'action',
          fixed: 'right' as const,
          width: 120,
          render: (_: unknown, record: T) => {
            const key = getKey(record)
            return (
              <Space size="small">
                {onRowEdit && (
                  <Button
                    type="link"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => startEdit(record, columns[0]?.dataIndex)}
                  />
                )}
                {onRowDelete && (
                  <Popconfirm
                    title="确定删除？"
                    onConfirm={() => onRowDelete(key)}
                    okText="确定"
                    cancelText="取消"
                  >
                    <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                )}
              </Space>
            )
          },
        },
      ]
    : []

  // 表格变化
  const handleTableChange: TableProps<T>['onChange'] = (
    _pagination,
    newFilters,
    newSorter
  ) => {
    setFilters(newFilters as Record<string, FilterValue | null>)

    if (Array.isArray(newSorter)) {
      const first = newSorter[0]
      setSorter({ field: first.field as string, order: first.order })
    } else {
      setSorter({
        field: (newSorter as SorterResult<T>).field as string,
        order: (newSorter as SorterResult<T>).order,
      })
    }
  }

  // 行选择配置
  const rowSelection = selectable
    ? {
        selectedRowKeys,
        onChange: handleSelectionChange,
        selections: [Table.SELECTION_ALL, Table.SELECTION_INVERT, Table.SELECTION_NONE],
      }
    : undefined

  return (
    <div>
      {/* 工具栏 */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Space>
          {onRowAdd && (
            <Button type="primary" icon={<PlusOutlined />} onClick={onRowAdd}>
              新增
            </Button>
          )}
          {selectedRowKeys.length > 0 && (
            <Tag color="blue">已选 {selectedRowKeys.length} 项</Tag>
          )}
        </Space>
        <Space>
          {onExport && (
            <Button icon={<DownloadOutlined />} onClick={() => onExport(filteredData)}>
              导出
            </Button>
          )}
          <Dropdown
            menu={{
              items: [
                { key: 'clearFilters', label: '清除筛选', onClick: () => setFilters({}) },
                { key: 'clearSorter', label: '清除排序', onClick: () => setSorter({}) },
                { key: 'reset', label: '重置', onClick: () => { setFilters({}); setSorter({}) } },
              ],
            }}
          >
            <Button icon={<MoreOutlined />} />
          </Dropdown>
        </Space>
      </div>

      {/* 表格 */}
      <Table<T>
        columns={[...tableColumns, ...actionColumn] as ColumnsType<T>}
        dataSource={filteredData}
        rowKey={rowKey}
        loading={loading}
        pagination={pagination}
        rowSelection={rowSelection}
        onChange={handleTableChange}
        scroll={scroll}
        size={size}
        bordered={bordered}
      />
    </div>
  )
}

export default AdvancedTable
