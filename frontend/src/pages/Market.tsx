import { useEffect, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Typography, Space, message, Switch, Input, Row, Col, Pagination, Empty, Button, Badge, Dropdown, Skeleton, Card, type MenuProps, Modal, Descriptions, Tag } from 'antd'
import { SearchOutlined, BellOutlined, DownloadOutlined, FileExcelOutlined, FileTextOutlined, WifiOutlined, DisconnectOutlined, ReloadOutlined, SwapOutlined, WarningOutlined } from '@ant-design/icons'
import VirtualTable from '../components/VirtualTable'
import type { VirtualColumn, SortOrder } from '../components/VirtualTable'
import MarketTable from '../components/MarketTable'
import { fmt } from '../utils/format'
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
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState<FilterValues>({})
  const [searchText, setSearchText] = useState('')
  const [useVirtual, setUseVirtual] = useState(true)
  const [currentPage, setCurrentPage] = useState(1)
  const [refreshing, setRefreshing] = useState(false)
  const [forcedCallVisible, setForcedCallVisible] = useState(false)
  const [forcedCallBond, setForcedCallBond] = useState<ConvertibleQuote | null>(null)
  const [alertVisible, setAlertVisible] = useState(false)
  const [selectedForAlert, setSelectedForAlert] = useState<{ code: string; name: string } | null>(null)

  const allBonds = useMarketStore((s) => s.allBonds)
  const setAllBonds = useMarketStore((s) => s.setAllBonds)
  const updateQuotes = useMarketStore((s) => s.updateQuotes)
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const triggers = useAlertStore((s) => s.triggers)

  // 实时行情列头点击排序状态 — key 为列 dataIndex,value 为排序方向
  const [columnSort, setColumnSort] = useState<{ key: string; order: SortOrder }>({ key: '', order: null })

  const onWsMessage = useCallback((quotes: ConvertibleQuote[]) => {
    try {
      updateQuotes(quotes)
      setBackendConnected(true)
    } catch (e) {
      console.error('[Market] WS message handler error:', e)
    }
  }, [updateQuotes, setBackendConnected])

  const { isConnected: wsConnected } = useWebSocket(onWsMessage, () => {
    fetchAllQuotes().then(res => {
      const bonds = Array.isArray(res?.bonds) ? res.bonds : []
      if (bonds.length > 0) setAllBonds(bonds)
      setBackendConnected(true)
    }).catch(() => {})
  })

  const handleRefresh = useCallback(() => {
    setRefreshing(true)
    // 清除缓存强制重新请求
    try { localStorage.removeItem('cache_market_quotes') } catch {}
    fetchAllQuotes()
      .then((res) => {
        const bonds = Array.isArray(res?.bonds) ? res.bonds : []
        setAllBonds(bonds)
        setBackendConnected(true)
        message.success(`已刷新，共 ${bonds.length} 只可转债`)
      })
      .catch(() => message.error('刷新失败'))
      .finally(() => setRefreshing(false))
  }, [setAllBonds, setBackendConnected])

  useEffect(() => {
    fetchAllQuotes()
      .then((res) => {
        const bonds = Array.isArray(res?.bonds) ? res.bonds : []
        setAllBonds(bonds)
        setLoading(false)
        setBackendConnected(true)
      })
      .catch((err) => {
        console.error('Failed to fetch quotes:', err)
        setLoading(false)
        message.error('行情数据加载失败，请稍后重试')
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

    if (filters.priceMin !== undefined) result = result.filter(b => (b.price ?? 0) >= filters.priceMin!)
    if (filters.priceMax !== undefined) result = result.filter(b => (b.price ?? 0) <= filters.priceMax!)
    if (filters.premiumMin !== undefined) result = result.filter(b => (b.premium_ratio ?? 0) >= filters.premiumMin!)
    if (filters.premiumMax !== undefined) result = result.filter(b => (b.premium_ratio ?? 0) <= filters.premiumMax!)
    if (filters.dualLowMin !== undefined) result = result.filter(b => (b.dual_low ?? 0) >= filters.dualLowMin!)
    if (filters.dualLowMax !== undefined) result = result.filter(b => (b.dual_low ?? 0) <= filters.dualLowMax!)
    if (filters.volumeMin !== undefined) result = result.filter(b => (b.volume ?? 0) >= filters.volumeMin!)
    if (filters.remainingYearsMin !== undefined) result = result.filter(b => (b.remaining_years ?? 0) >= filters.remainingYearsMin!)
    if (filters.remainingYearsMax !== undefined) result = result.filter(b => (b.remaining_years ?? 0) <= filters.remainingYearsMax!)

    // 排序:列头点击排序(columnSort)优先,其次 FilterPanel 排序
    const effectiveSort = columnSort.order && columnSort.key
      ? { key: columnSort.key, order: columnSort.order }
      : (filters.sortBy && filters.sortOrder
          ? { key: filters.sortBy, order: filters.sortOrder }
          : null)

    if (effectiveSort) {
      const sortKey = effectiveSort.key as keyof ConvertibleQuote
      const sortOrder = effectiveSort.order
      // 安全读取数值;null/undefined/非数字按 -Infinity 处理使其排到末尾
      const numOf = (rec: ConvertibleQuote): number => {
        const raw = (rec as unknown as Record<string, unknown>)[sortKey as string]
        return typeof raw === 'number' && Number.isFinite(raw) ? raw : Number.NEGATIVE_INFINITY
      }
      result.sort((a, b) => {
        const aVal = numOf(a)
        const bVal = numOf(b)
        if (aVal === bVal) return 0
        return sortOrder === 'asc' ? aVal - bVal : bVal - aVal
      })
    }

    return result
  }, [allBonds, filters, searchText, columnSort])

  // 列头点击排序回调:同一列循环 null → asc → desc → null;切换列时从 asc 开始
  const handleColumnSort = useCallback((dataIndex: string | number | undefined) => {
    const key = String(dataIndex ?? '')
    setColumnSort((prev) => {
      if (prev.key !== key) return { key, order: 'asc' }
      if (prev.order === 'asc') return { key, order: 'desc' }
      if (prev.order === 'desc') return { key: '', order: null }
      return { key, order: 'asc' }
    })
    setCurrentPage(1)
  }, [])

  const paginatedBonds = useMemo(() => {
    if (useVirtual) return filteredBonds
    const start = (currentPage - 1) * PAGE_SIZE
    return filteredBonds.slice(start, start + PAGE_SIZE)
  }, [filteredBonds, useVirtual, currentPage])

  const virtualColumns: VirtualColumn<ConvertibleQuote>[] = useMemo(() => {
    const orderOf = (key: string): SortOrder => columnSort.key === key ? columnSort.order : null
    const numSorter = (key: keyof ConvertibleQuote) => (a: ConvertibleQuote, b: ConvertibleQuote) => {
      const av = (a[key] as number | null | undefined) ?? 0
      const bv = (b[key] as number | null | undefined) ?? 0
      return (typeof av === 'number' ? av : 0) - (typeof bv === 'number' ? bv : 0)
    }
    return [
      { key: 'code', dataIndex: 'code', title: '代码', width: 110, sortable: true, sortOrder: orderOf('code'), sorter: (a, b) => String(a.code ?? '').localeCompare(String(b.code ?? '')) },
      { key: 'name', dataIndex: 'name', title: '名称', width: 100, sortable: true, sortOrder: orderOf('name'), sorter: (a, b) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
      { key: 'price', dataIndex: 'price', title: '最新价', width: 100, sortable: true, sortOrder: orderOf('price'), sorter: numSorter('price'), render: (v: unknown, r: ConvertibleQuote) => {
        const color = (r.change_pct ?? 0) > 0 ? '#cf1322' : (r.change_pct ?? 0) < 0 ? '#389e0d' : undefined
        return <span style={{ color, fontWeight: 600, fontFamily: 'SF Mono, Monaco, Consolas, monospace', fontSize: 13 }}>{fmt(v as number)}</span>
      }},
      { key: 'change_pct', dataIndex: 'change_pct', title: '涨跌幅', width: 95, sortable: true, sortOrder: orderOf('change_pct'), sorter: numSorter('change_pct'), render: (v: unknown) => {
        const n = v as number ?? 0
        const color = n > 0 ? '#cf1322' : n < 0 ? '#389e0d' : undefined
        return <span style={{ color, fontWeight: 600, fontFamily: 'SF Mono, Monaco, Consolas, monospace', fontSize: 13 }}>{n > 0 ? '+' : ''}{fmt(n)}%</span>
      }},
      { key: 'premium_ratio', dataIndex: 'premium_ratio', title: '溢价率', width: 85, sortable: true, sortOrder: orderOf('premium_ratio'), sorter: numSorter('premium_ratio'), render: (v: unknown) => {
        const n = v as number ?? 0
        const color = n < 0 ? '#cf1322' : n > 50 ? '#389e0d' : undefined
        return <span style={{ color, fontWeight: 600, fontSize: 13 }}>{fmt(n)}%</span>
      }},
      { key: 'dual_low', dataIndex: 'dual_low', title: '双低', width: 75, sortable: true, sortOrder: orderOf('dual_low'), sorter: numSorter('dual_low'), render: (v: unknown) => {
        const n = v as number ?? 0
        const color = n < 130 ? '#52c41a' : n > 180 ? '#faad14' : undefined
        return <span style={{ color, fontWeight: 600, fontSize: 13 }}>{fmt(n)}</span>
      }},
      { key: 'volume', dataIndex: 'volume', title: '成交额(亿)', width: 95, sortable: true, sortOrder: orderOf('volume'), sorter: numSorter('volume'), render: (v: unknown) => {
        const n = v as number ?? 0
        return n > 0
          ? <span style={{ fontFamily: 'SF Mono, Monaco, Consolas, monospace', fontSize: 13 }}>{fmt(n)}</span>
          : <span style={{ color: '#bbb', fontSize: 13 }}>休市</span>
      }},
      { key: 'remaining_years', dataIndex: 'remaining_years', title: '剩余年限', width: 80, sortable: true, sortOrder: orderOf('remaining_years'), sorter: numSorter('remaining_years'), render: (v: unknown) => {
        const n = v as number ?? 0
        return n > 0
          ? <span style={{ fontFamily: 'SF Mono, Monaco, Consolas, monospace', fontSize: 13 }}>{fmt(n, 1)}</span>
          : <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      }},
      { key: 'forced_call_days', dataIndex: 'forced_call_days', title: '强赎', width: 60, sortable: true, sortOrder: orderOf('forced_call_days'), sorter: numSorter('forced_call_days'), render: (v: unknown, r: ConvertibleQuote) => {
        const n = v as number ?? 0
        if (n <= 0) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
        const color = n >= 10 ? '#ff4d4f' : n >= 5 ? '#faad14' : '#1677ff'
        return <a style={{ color, fontWeight: 600, fontSize: 13 }} onClick={() => { setForcedCallBond(r); setForcedCallVisible(true) }}>{n}/15</a>
      }},
      { key: 'redemption_countdown', dataIndex: 'last_trade_date', title: '赎回倒计时', width: 95, sortable: true, sortOrder: orderOf('last_trade_date'), render: (_v: unknown, r: ConvertibleQuote) => {
        if (!r.is_called || !r.last_trade_date) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
        const now = new Date()
        const lastTrade = new Date(r.last_trade_date)
        const daysLeft = Math.ceil((lastTrade.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
        if (daysLeft < 0) return <Tag color="red" style={{ fontSize: 12 }}>已退市</Tag>
        if (daysLeft <= 3) return <Tag color="red" style={{ fontSize: 12 }}>{daysLeft}天</Tag>
        if (daysLeft <= 10) return <Tag color="orange" style={{ fontSize: 12 }}>{daysLeft}天</Tag>
        return <span style={{ fontFamily: 'SF Mono, Monaco, Consolas, monospace', fontSize: 13 }}>{daysLeft}天</span>
      }},
      { key: 'call_status', dataIndex: 'call_status', title: '强赎状态', width: 80, sortable: true, sortOrder: orderOf('call_status'), sorter: (a, b) => String(a.call_status ?? '').localeCompare(String(b.call_status ?? '')), render: (v: unknown, r: ConvertibleQuote) => {
        if (r.is_called) return <Tag color="red" style={{ fontSize: 12 }}>已公告强赎</Tag>
        if (v) return <Tag color="orange" style={{ fontSize: 12 }}>{String(v)}</Tag>
        return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      }},
    ]
  }, [columnSort])

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
      <div style={{ padding: 16 }}>
        <Title level={4} style={{ margin: '0 0 16px' }}>实时行情</Title>
        <Card>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Skeleton.Input active style={{ width: 200, height: 32 }} />
            <Skeleton paragraph={{ rows: 10 }} active />
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 12, flexShrink: 0 }}>
        <Col>
          <Space>
            <Title level={4} style={{ margin: 0 }}>实时行情</Title>
            <Badge status={wsConnected ? 'success' : 'error'} text={
              <span style={{ fontSize: 12, color: wsConnected ? '#52c41a' : '#ff4d4f' }}>
                {wsConnected ? <><WifiOutlined /> 实时</> : (
                  <>
                    <DisconnectOutlined /> 离线
                    <Button type="link" size="small" style={{ padding: 0, marginLeft: 4, fontSize: 11 }} onClick={() => { import('../utils/wsInstances').then(m => m.marketWs.connect()) }}>重连</Button>
                  </>
                )}
              </span>
            } />
          </Space>
        </Col>
        <Col>
          <Space>
            <span style={{ color: '#888' }}>共 {filteredBonds.length} 只可转债</span>
            <Switch checkedChildren="虚拟滚动" unCheckedChildren="分页" checked={useVirtual} onChange={(v) => { setUseVirtual(v); setCurrentPage(1) }} />
            <Button icon={<ReloadOutlined spin={refreshing} />} onClick={handleRefresh} loading={refreshing}>刷新</Button>
            <Button icon={<SwapOutlined />} onClick={() => navigate('/exchangeable')}>可交换债</Button>
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

      <Row gutter={16} style={{ marginBottom: 12, flexShrink: 0 }}>
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

      <div style={{ flexShrink: 0 }}>
        <FilterPanel onChange={handleFilterChange} />
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        {filteredBonds.length === 0 ? (
          <Empty description="无匹配数据" style={{ marginTop: 60 }} />
        ) : useVirtual ? (
          <VirtualTable
            data={filteredBonds}
            columns={virtualColumns}
            loading={false}
            onSort={(dataIndex) => handleColumnSort(dataIndex)}
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
      </div>

      <AlertPanel
        visible={alertVisible}
        onClose={() => setAlertVisible(false)}
        selectedCode={selectedForAlert?.code}
        selectedName={selectedForAlert?.name}
      />

      <Modal
        title={<span><WarningOutlined style={{ color: '#faad14', marginRight: 8 }} />强赎风险详情</span>}
        open={forcedCallVisible}
        onCancel={() => { setForcedCallVisible(false); setForcedCallBond(null) }}
        footer={null}
        width={520}
      >
        {forcedCallBond && (
          <>
            <div style={{ marginBottom: 12 }}>
              <Tag color={(forcedCallBond.forced_call_days ?? 0) >= 10 ? 'red' : (forcedCallBond.forced_call_days ?? 0) >= 5 ? 'orange' : 'blue'}>
                {forcedCallBond.forced_call_days ?? 0}/15 天
              </Tag>
              <span style={{ marginLeft: 8 }}>{forcedCallBond.code} {forcedCallBond.name}</span>
            </div>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="正股价">{fmt(forcedCallBond.stock_price)}</Descriptions.Item>
              <Descriptions.Item label="转股价">{fmt(forcedCallBond.conversion_price)}</Descriptions.Item>
              <Descriptions.Item label="转股价值">{fmt(forcedCallBond.conversion_value)}</Descriptions.Item>
              <Descriptions.Item label="溢价率">{fmt(forcedCallBond.premium_ratio)}%</Descriptions.Item>
              <Descriptions.Item label="最新价">{fmt(forcedCallBond.price)}</Descriptions.Item>
              <Descriptions.Item label="剩余年限">{(forcedCallBond.remaining_years ?? 0) > 0 ? fmt(forcedCallBond.remaining_years, 1) + '年' : '-'}</Descriptions.Item>
              <Descriptions.Item label="强赎进度" span={2}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, height: 8, background: '#f0f0f0', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      width: `${Math.min(100, ((forcedCallBond.forced_call_days ?? 0) / 15) * 100)}%`,
                      height: '100%',
                      background: (forcedCallBond.forced_call_days ?? 0) >= 10 ? '#ff4d4f' : (forcedCallBond.forced_call_days ?? 0) >= 5 ? '#faad14' : '#1677ff',
                      borderRadius: 4,
                    }} />
                  </div>
                  <span style={{ fontSize: 12, color: '#666' }}>{forcedCallBond.forced_call_days ?? 0}/15天</span>
                </div>
              </Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 12, padding: '8px 12px', background: '#fffbe6', borderRadius: 4, fontSize: 12, color: '#8c6900' }}>
              {forcedCallBond.is_called || forcedCallBond.call_status ? (
                <>
                  <Tag color="red" style={{ marginBottom: 4 }}>已公告强赎</Tag>
                  {forcedCallBond.call_status && <span> 状态: {forcedCallBond.call_status}</span>}
                  {forcedCallBond.last_trade_date && <div style={{ marginTop: 4 }}>
                    最后交易日: {forcedCallBond.last_trade_date}
                    {' '}(距赎回 {Math.ceil((new Date(forcedCallBond.last_trade_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24))}天)
                  </div>}
                </>
              ) : (
                <>强赎条款：正股收盘价连续15个交易日不低于转股价的130%（含），发行人有权按面值+应计利息赎回全部未转股可转债。
                已满足{(forcedCallBond.forced_call_days ?? 0)}天，还需{15 - (forcedCallBond.forced_call_days ?? 0)}天即触发强赎。</>
              )}
            </div>
            <Descriptions bordered size="small" column={2} style={{ marginTop: 12 }}>
              {forcedCallBond.last_trade_date && <Descriptions.Item label="最后交易日">{forcedCallBond.last_trade_date}</Descriptions.Item>}
              {forcedCallBond.maturity_date && <Descriptions.Item label="到期日">{forcedCallBond.maturity_date}</Descriptions.Item>}
              {(forcedCallBond.redemption_price ?? 0) > 0 && <Descriptions.Item label="强赎价格">{fmt(forcedCallBond.redemption_price)} 元</Descriptions.Item>}
            </Descriptions>
          </>
        )}
      </Modal>
    </div>
  )
}
