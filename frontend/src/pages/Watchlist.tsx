import { useEffect, useMemo } from 'react'
import { Typography, Space, Table, Button, Empty, Tag, Popconfirm } from 'antd'
import { StarFilled, DeleteOutlined } from '@ant-design/icons'
import { useWatchlistStore } from '../stores/useWatchlistStore'
import { useMarketStore } from '../stores/useMarketStore'
import { useAppStore } from '../stores/useAppStore'
import type { ConvertibleQuote } from '../types'

const { Title, Text } = Typography

export default function Watchlist() {
  const watchlist = useWatchlistStore((s) => s.watchlist)
  const removeWatch = useWatchlistStore((s) => s.removeWatch)
  const clearWatchlist = useWatchlistStore((s) => s.clearWatchlist)
  const bonds = useMarketStore((s) => s.bonds)
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)

  const watchlistBonds = useMemo(() => {
    return watchlist
      .map((w) => bonds.get(w.code))
      .filter((b): b is ConvertibleQuote => b !== undefined)
  }, [watchlist, bonds])

  const columns = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 80,
      render: (code: string) => (
        <Space>
          <StarFilled style={{ color: '#faad14', fontSize: 12 }} />
          <span style={{ fontFamily: 'monospace' }}>{code}</span>
        </Space>
      ),
    },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    {
      title: '最新价',
      dataIndex: 'price',
      key: 'price',
      width: 90,
      render: (v: number, r: ConvertibleQuote) => (
        <span style={{ color: r.change_pct > 0 ? '#cf1322' : r.change_pct < 0 ? '#389e0d' : undefined, fontWeight: 600 }}>
          {v.toFixed(2)}
        </span>
      ),
    },
    {
      title: '涨跌幅',
      dataIndex: 'change_pct',
      key: 'change_pct',
      width: 90,
      render: (v: number) => (
        <Tag color={v > 0 ? 'red' : v < 0 ? 'green' : undefined}>
          {v > 0 ? '+' : ''}{v.toFixed(2)}%
        </Tag>
      ),
    },
    {
      title: '溢价率',
      dataIndex: 'premium_ratio',
      key: 'premium_ratio',
      width: 90,
      render: (v: number) => <span>{v.toFixed(2)}%</span>,
    },
    {
      title: '双低',
      dataIndex: 'dual_low',
      key: 'dual_low',
      width: 80,
      render: (v: number) => (
        <Tag color={v < 130 ? 'green' : v > 180 ? 'red' : 'orange'}>
          {v.toFixed(2)}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 60,
      render: (_: unknown, record: ConvertibleQuote) => (
        <Button
          type="text"
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={(e) => {
            e.stopPropagation()
            removeWatch(record.code)
          }}
        />
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>自选列表</Title>
          <Text type="secondary">({watchlistBonds.length} 只)</Text>
        </Space>
        {watchlist.length > 0 && (
          <Popconfirm title="确定清空自选列表?" onConfirm={clearWatchlist}>
            <Button danger size="small">清空</Button>
          </Popconfirm>
        )}
      </div>

      {watchlistBonds.length === 0 ? (
        <Empty description="暂无自选，在行情页面点击星标添加" style={{ marginTop: 60 }} />
      ) : (
        <Table
          dataSource={watchlistBonds}
          columns={columns}
          rowKey="code"
          size="small"
          pagination={false}
          onRow={(record) => ({
            onClick: () => setSelectedBond(record.code),
            style: { cursor: 'pointer' },
          })}
        />
      )}
    </div>
  )
}
