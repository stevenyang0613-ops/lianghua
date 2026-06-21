import { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Statistic, Button, Tabs, Space, Modal, message, Typography, Spin, Alert, Skeleton } from 'antd'
import {
  DollarOutlined, SwapOutlined, BarChartOutlined, ReloadOutlined, DeleteOutlined, HistoryOutlined, ExportOutlined,
} from '@ant-design/icons'
import { fetchAccount, fetchPositions, fetchOrders, cancelOrder, resetAccount, fetchFundCurve, fetchSignals } from '../services/api'
import { useTradeStore } from '../stores/useTradeStore'
import { useMarketStore } from '../stores/useMarketStore'
import { exportAccountReport } from '../utils/export'
import type { TradeSignal } from '../services/api'
import TradePanel from '../components/trade/TradePanel'
import PositionTable from '../components/trade/PositionTable'
import OrderHistory from '../components/trade/OrderHistory'
import FundCurve from '../components/trade/FundCurve'

const { Title } = Typography

export default function Trade() {
  const account = useTradeStore((s) => s.account)
  const positions = useTradeStore((s) => s.positions)
  const orders = useTradeStore((s) => s.orders)
  const fundCurve = useTradeStore((s) => s.fundCurve)
  const setAccount = useTradeStore((s) => s.setAccount)
  const setPositions = useTradeStore((s) => s.setPositions)
  const setOrders = useTradeStore((s) => s.setOrders)
  const setFundCurve = useTradeStore((s) => s.setFundCurve)
  const setLoading = useTradeStore((s) => s.setLoading)
  const loading = useTradeStore((s) => s.loading)
  const allBonds = useMarketStore((s) => s.allBonds)

  const [refreshing, setRefreshing] = useState(false)
  const [activeTab, setActiveTab] = useState('trade')
  const [signalBanner, setSignalBanner] = useState<TradeSignal[]>([])

  useEffect(() => {
    let cancelled = false
    fetchSignals().then(data => { if (!cancelled) setSignalBanner(data.signals) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const loadData = useCallback(async () => {
    try {
      const [acc, pos, ords, curve] = await Promise.all([
        fetchAccount(),
        fetchPositions(),
        fetchOrders(),
        fetchFundCurve(),
      ])
      setAccount(acc)
      setPositions(pos.positions)
      setOrders(ords.orders)
      setFundCurve(curve.points)
    } catch (e: any) {
      message.error('加载交易数据失败: ' + (e.message || '未知错误'))
    }
  }, [setAccount, setPositions, setOrders, setFundCurve])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleCancelOrder = async (orderId: string) => {
    try {
      await cancelOrder(orderId)
      message.success('撤单成功')
      await loadData()
    } catch (e: any) {
      message.error('撤单失败: ' + (e.message || '未知错误'))
    }
  }

  const handleReset = () => {
    Modal.confirm({
      title: '确认重置',
      content: '重置将清空所有持仓、订单和资金记录，确定继续？',
      onOk: async () => {
        try {
          await resetAccount()
          message.success('账户已重置')
          await loadData()
        } catch (e: any) {
          message.error('重置失败: ' + (e.message || '未知错误'))
        }
      },
    })
  }

  if (loading && !account) {
    return (
      <div style={{ padding: 16 }}>
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col><Skeleton.Input active style={{ width: 160, height: 32 }} /></Col>
          <Col><Skeleton.Button active style={{ width: 200 }} /></Col>
        </Row>
        <Row gutter={16}>
          <Col span={14}>
            <Card style={{ marginBottom: 12 }}><Skeleton paragraph={{ rows: 4 }} active /></Card>
            <Card><Skeleton paragraph={{ rows: 4 }} active /></Card>
          </Col>
          <Col span={10}>
            <Card style={{ marginBottom: 12 }}><Skeleton paragraph={{ rows: 6 }} active /></Card>
            <Card><Skeleton paragraph={{ rows: 6 }} active /></Card>
          </Col>
        </Row>
      </div>
    )
  }

  return (
    <div style={{ padding: 16 }}>
      {signalBanner.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable
          message="交易信号提醒"
          description={signalBanner.slice(0, 5).map(s => `${s.name}(${s.code})`).join(', ') + (signalBanner.length > 5 ? ` 等${signalBanner.length}个` : '')}
          action={
            <Button size="small" type="primary" onClick={() => window.location.href = '/signals'}>
              查看信号
            </Button>
          }
          style={{ marginBottom: 12 }}
        />
      )}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <DollarOutlined /> 交易终端
          </Title>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => { setRefreshing(true); loadData().finally(() => setRefreshing(false)) }} loading={refreshing}>刷新</Button>
            <Button icon={<ExportOutlined />} onClick={() => exportAccountReport(account, positions, orders)}>导出报告</Button>
            <Button icon={<DeleteOutlined />} danger onClick={handleReset}>重置账户</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={14}>
          <Card size="small" style={{ marginBottom: 12 }}>
            <Tabs
              activeKey={activeTab}
              onChange={setActiveTab}
              items={[
                {
                  key: 'trade',
                  label: <span><SwapOutlined /> 下单</span>,
                  children: (
                    <TradePanel
                      allBonds={allBonds}
                      account={account}
                      loading={loading}
                      setLoading={setLoading}
                      onOrderPlaced={loadData}
                    />
                  ),
                },
                {
                  key: 'positions',
                  label: <span><BarChartOutlined /> 持仓 ({positions.length})</span>,
                  children: <PositionTable positions={positions} />,
                },
              ]}
            />
          </Card>

          <Card size="small" title={<span><HistoryOutlined /> 委托记录</span>}>
            <OrderHistory orders={orders} onCancelOrder={handleCancelOrder} />
          </Card>
        </Col>

        <Col span={10}>
          <Card title="账户概览" size="small" style={{ marginBottom: 12 }}>
            {account ? (
              <Row gutter={[12, 16]}>
                <Col span={12}><Statistic title="总资产" value={account.total_asset} precision={2} prefix="¥" valueStyle={{ fontSize: 22, fontWeight: 600 }} /></Col>
                <Col span={12}><Statistic title="可用资金" value={account.cash} precision={2} prefix="¥" /></Col>
                <Col span={12}><Statistic title="持仓市值" value={account.market_value} precision={2} prefix="¥" /></Col>
                <Col span={12}><Statistic title="冻结资金" value={account.frozen} precision={2} prefix="¥" valueStyle={{ color: '#faad14' }} /></Col>
                <Col span={12}><Statistic title="总盈亏" value={account.total_profit} precision={2} prefix="¥" valueStyle={{ color: account.total_profit >= 0 ? '#cf1322' : '#389e0d' }} /></Col>
                <Col span={12}><Statistic title="收益率" value={(() => { const base = (account.total_asset || 0) - (account.total_profit || 0); return base > 0 ? ((account.total_profit || 0) / base) * 100 : 0 })()} precision={2} suffix="%" valueStyle={{ color: (account.total_profit || 0) >= 0 ? '#cf1322' : '#389e0d' }} /></Col>
              </Row>
            ) : <Spin />}
          </Card>
          <FundCurve fundCurve={fundCurve} />
        </Col>
      </Row>
    </div>
  )
}
