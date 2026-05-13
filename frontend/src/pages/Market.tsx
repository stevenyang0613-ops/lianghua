import { useEffect, useState, useCallback, useMemo } from 'react'
import { Typography, Space, message, Switch, Input, Row, Col, Pagination, Empty, Spin, Button, Badge, Dropdown, type MenuProps } from 'antd'
import { SearchOutlined, BellOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined } from '@ant-design/icons'
import VirtualTable from '../components/VirtualTable'
import MarketTable from '../components/MarketTable'
import FilterPanel from '../components/FilterPanel'
import AlertPanel from '../components/AlertPanel'
import { useMarketStore } from '../stores/useMarketStore'
import { useAppStore } from '../stores/useAppStore'
import { useAlertStore } from '../stores/useAlertStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { fetchAllQuotes } from '../services/api'
import { exportToCSV, exportToExcel, formatDateForFilename } from '../utils/export'
import type { ConvertibleQuote } from '../types'

const { Title } = Typography

interface FilterValues {
  priceMin?: number
  priceMax?: number
  premiumMin?: number
  premiumMax?: number
  dualLowMin?: number
  dualLowMax?: number
  volumeMin?: number
  remainingYearsMin?: number
  remainingYearsMax?: number
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

const PAGE_SIZE = 50

export default function Market() {
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<FilterValues>({})
  const [searchText, setSearchText] = useState('')
  const [useVirtual, setUseVirtual] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [alertVisible, setAlertVisible] = useState(false)
  const [selectedForAlert, setSelectedForAlert] = useState<{ code: string; name: string } | null>(null)

  const { allBonds, setAllBonds, updateQuotes } = useMarketStore()
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const triggers = useAlertStore((s) => s.triggers)

  const onWsMessage = useCallback((quotes: ConvertibleQuote[]) => {
    updateQuotes(quotes)
    setBackendConnected(true)
  }, [updateQuotes, setBackendConnected])

  useWebSocket(onWsMessage)

  useEffect(() => {
    fetchAllQuotes()
      .then((res) => {
        setAllBonds(res.bonds)
        setLoading(false)
        setBackendConnected(true)
      })
      .catch((err) => {
        console.error('Failed to fetch quotes:', err)
        setLoading(false)
        setBackendConnected(false)
        message.error('连接后端失败，请检查服务是否启动')
      })
  }, [setAllBonds, setBackendConnected])

  useEffect(() => {
    return () => setSelectedBond(null)
  }, [setSelectedBond])

  const filteredBonds = useMemo(() => {
    let result = [...allBonds]

    if (searchText) {
      const search = searchText.toLowerCase()
      result = result.filter(b => b.code.includes(search) || b.name.toLowerCase().includes(search))
    }

    if (filters.priceMin !== undefined) result = result.filter(b => b.price >= filters.priceMin!)
    if (filters.priceMax !== undefined) result = result.filter(b => b.price <= filters.priceMax!)
    if (filters.premiumMin !== undefined) result = result.filter(b => b.premium_ratio >= filters.premiumMin!)
    if (filters.premiumMax !== undefined) result = result.filter(b => b.premium_ratio <= filters.premiumMax!)
    if (filters.dualLowMin !== undefined) result = result.filter(b => b.dual_low >= filters.dualLowMin!)
    if (filters.dualLowMax !== undefined) result = result.filter(b => b.dual_low <= filters.dualLowMax!)
    if (filters.volumeMin !== undefined) result = result.filter(b => b.volume >= filters.volumeMin!)
    if (filters.remainingYearsMin !== undefined) result = result.filter(b => b.remaining_years >= filters.remainingYearsMin!)
    if (filters.remainingYearsMax !== undefined) result = result.filter(b => b.remaining_years <= filters.remainingYearsMax!)

    if (filters.sortBy && filters.sortOrder) {
      const key = filters.sortBy as keyof ConvertibleQuote
      result.sort((a, b) => {
        const aVal = a[key] ?? 0
        const bVal = b[key] ?? 0
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return filters.sortOrder === 'asc' ? aVal - bVal : bVal - aVal
        }
        return 0
      })
    }

    return result
  }, [allBonds, filters, searchText])

  const paginatedBonds = useMemo(() => {
    if (useVirtual) return filteredBonds
    const start = (currentPage - 1) * PAGE_SIZE
    return filteredBonds.slice(start, start + PAGE_SIZE)
  }, [filteredBonds, useVirtual, currentPage])

  const handleFilterChange = useCallback((newFilters: FilterValues) => {
    setFilters(newFilters)
    setCurrentPage(1)
  }, [])

  const handleOpenAlert = (code?: string, name?: string) => {
    if (code) {
      setSelectedForAlert({ code, name: name || '' })
    } else {
      setSelectedForAlert(null)
    }
    setAlertVisible(true)
  }

  const handleExport = (type: 'csv' | 'excel') => {
    if (filteredBonds.length === 0) {
      message.warning('无数据可导出')
      return
    }
    const filename = `可转债行情_${formatDateForFilename()}`
    if (type === 'csv') {
      exportToCSV(filteredBonds, filename)
    } else {
      exportToExcel(filteredBonds, filename)
    }
    message.success(`已导出 ${filteredBonds.length} 条数据`)
  }

  const exportMenuItems: MenuProps['items'] = [
    {
      key: 'csv',
      icon: <FileTextOutlined />,
      label: '导出 CSV',
      onClick: () => handleExport('csv'),
    },
    {
      key: 'excel',
      icon: <FileExcelOutlined />,
      label: '导出 Excel',
      onClick: () => handleExport('excel'),
    },
  ]

  if (loading) {
    return (
      <div style={{ height: 'calc(100vh - 200px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>实时行情</Title>
        </Col>
        <Col>
          <Space>
            <span style={{ color: '#888' }}>共 {filteredBonds.length} 只可转债</span>
            <Switch checkedChildren="虚拟滚动" unCheckedChildren="分页" checked={useVirtual} onChange={setUseVirtual} />
            <Dropdown menu={{ items: exportMenuItems }} trigger={['click']}>
              <Button icon={<DownloadOutlined />}>导出</Button>
            </Dropdown>
            <Badge count={triggers.length} size="small">
              <Button icon={<BellOutlined />} onClick={() => handleOpenAlert()}>
                告警
              </Button>
            </Badge>
          </Space>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Input
            placeholder="搜索代码或名称..."
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            allowClear
          />
        </Col>
      </Row>

      <FilterPanel onChange={handleFilterChange} />

      {filteredBonds.length === 0 ? (
        <Empty description="无匹配数据" style={{ marginTop: 60 }} />
      ) : useVirtual ? (
        <VirtualTable
          bonds={filteredBonds}
          loading={false}
          onRowClick={(code) => setSelectedBond(code)}
          height={600}
        />
      ) : (
        <>
          <MarketTable bonds={paginatedBonds} loading={false} onRowClick={(code) => setSelectedBond(code)} />
          <div style={{ marginTop: 16, textAlign: 'right' }}>
            <Pagination
              current={currentPage}
              pageSize={PAGE_SIZE}
              total={filteredBonds.length}
              onChange={setCurrentPage}
              showSizeChanger={false}
              showTotal={(total) => `第 ${currentPage} 页，共 ${total} 条`}
            />
          </div>
        </>
      )}

      <AlertPanel
        visible={alertVisible}
        onClose={() => setAlertVisible(false)}
        selectedCode={selectedForAlert?.code}
        selectedName={selectedForAlert?.name}
      />
    </div>
  )
}
