import { useState, useMemo } from 'react'
import { Card, Descriptions, Tag, Typography, Space, Statistic, Row, Col, Button, Drawer, Tabs } from 'antd'
import { CloseOutlined, ArrowUpOutlined, ArrowDownOutlined, StarOutlined, StarFilled, BellOutlined } from '@ant-design/icons'
import { useAppStore } from '../stores/useAppStore'
import { useMarketStore } from '../stores/useMarketStore'
import { useWatchlistStore } from '../stores/useWatchlistStore'
import { useResponsive } from '../hooks/useResponsive'
import ChartPanel from './ChartPanel'
import AlertPanel from './AlertPanel'
import { fmt } from '../utils/format'

const { Title, Text } = Typography




export default function DetailPanel() {
  const selectedBond = useAppStore((s) => s.selectedBond)
  const setSelectedBond = useAppStore((s) => s.setSelectedBond)
  const allBonds = useMarketStore((s) => s.allBonds)
  const bondsMap = useMemo(() => new Map(allBonds.map(b => [b.code, b])), [allBonds])
  const bond = selectedBond ? bondsMap.get(selectedBond) ?? null : null
  const { isMobile } = useResponsive()
  const [alertVisible, setAlertVisible] = useState(false)

  const addWatch = useWatchlistStore((s) => s.addWatch)
  const removeWatch = useWatchlistStore((s) => s.removeWatch)
  const isInWatchlist = useWatchlistStore((s) => s.isInWatchlist)
  const isWatched = selectedBond ? isInWatchlist(selectedBond) : false


  if (!bond) {
    if (isMobile) return null
    return (
      <div style={{ width: 320, borderLeft: '1px solid var(--border-color, #e8e8e8)', height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--card-bg, #fff)' }}>
        <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Title level={5} style={{ margin: 0 }}>详情面板</Title>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Text type="secondary">选中可转债查看详情</Text>
        </div>
      </div>
    )
  }

  const priceColor = (bond.change_pct ?? 0) > 0 ? '#cf1322' : (bond.change_pct ?? 0) < 0 ? '#389e0d' : undefined
  const premiumColor = (bond.premium_ratio ?? 0) < 0 ? '#52c41a' : (bond.premium_ratio ?? 0) > 50 ? '#faad14' : undefined
  const dualLowColor = (bond.dual_low ?? 0) < 130 ? '#52c41a' : (bond.dual_low ?? 0) > 180 ? '#f5222d' : '#faad14'

  const handleToggleWatch = () => {
    if (isWatched) {
      removeWatch(bond.code)
    } else {
      addWatch({ code: bond.code, name: bond.name, addedAt: Date.now() })
    }
  }

  const tabItems = useMemo(() => [
    {
      key: 'info',
      label: '详情',
      children: (
        <>
          <Card size="small" title="转股信息" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="正股价">{fmt(bond.stock_price)} 元</Descriptions.Item>
              <Descriptions.Item label="正股涨跌">
                <Tag color={(bond.stock_change_pct ?? 0) > 0 ? 'red' : (bond.stock_change_pct ?? 0) < 0 ? 'green' : undefined}>
                  {(bond.stock_change_pct ?? 0) > 0 ? '+' : ''}{fmt(bond.stock_change_pct)}%
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="转股价">{fmt(bond.conversion_price)} 元</Descriptions.Item>
              <Descriptions.Item label="转股价值">{fmt(bond.conversion_value)} 元</Descriptions.Item>
              <Descriptions.Item label="溢价率">
                <Text style={{ color: premiumColor, fontWeight: 600 }}>{fmt(bond.premium_ratio)}%</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card size="small" title="估值指标" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="双低值">
                <Tag color={dualLowColor}>{fmt(bond.dual_low)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="到期收益率">
                <Text type={(bond.ytm ?? 0) > 0 ? 'success' : 'danger'}>{fmt(bond.ytm)}%</Text>
              </Descriptions.Item>
              <Descriptions.Item label="剩余年限">{fmt(bond.remaining_years, 1)} 年</Descriptions.Item>
              <Descriptions.Item label="强赎倒计时">
                {(bond.forced_call_days ?? 0) > 0 ? `${bond.forced_call_days} 天` : '未触发'}
              </Descriptions.Item>
              {bond.is_called && (
                <Descriptions.Item label="强赎公告">
                  <Tag color="red">已公告强赎</Tag>
                </Descriptions.Item>
              )}
              {bond.call_status && (
                <Descriptions.Item label="强赎状态">{bond.call_status}</Descriptions.Item>
              )}
              {bond.last_trade_date && (
                <Descriptions.Item label="最后交易日">{bond.last_trade_date}</Descriptions.Item>
              )}
              {bond.maturity_date && (
                <Descriptions.Item label="到期日">{bond.maturity_date}</Descriptions.Item>
              )}
              {(bond.redemption_price ?? 0) > 0 && (
                <Descriptions.Item label="强赎价格">{fmt(bond.redemption_price)} 元</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card size="small" title="交易数据" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="成交额">{fmt(bond.volume)} 亿元</Descriptions.Item>
            </Descriptions>
          </Card>
        </>
      ),
    },
    {
      key: 'chart',
      label: '图表',
      children: (
        <div style={{ padding: '0 16px' }}>
          <ChartPanel code={bond.code} name={bond.name} />
        </div>
      ),
    },
  ], [bond, premiumColor, dualLowColor])

  const content = (
    <>
      <div style={{ padding: 16 }}>
        <Row gutter={16}>
          <Col span={12}>
            <Statistic
              title="最新价"
              value={bond.price}
              precision={2}
              valueStyle={{ color: priceColor, fontWeight: 600 }}
              prefix={(bond.change_pct ?? 0) > 0 ? <ArrowUpOutlined /> : (bond.change_pct ?? 0) < 0 ? <ArrowDownOutlined /> : null}
              suffix="元"
            />
          </Col>
          <Col span={12}>
            <Statistic
              title="涨跌幅"
              value={bond.change_pct}
              precision={2}
              valueStyle={{ color: priceColor, fontWeight: 600 }}
              suffix="%"
            />
          </Col>
        </Row>
      </div>

      <Tabs
        defaultActiveKey="info"
        items={tabItems}
        size="small"
        style={{ paddingLeft: 16, paddingRight: 16 }}
      />
    </>
  )

  if (isMobile) {
    return (
      <>
        <Drawer
          title={
            <Space>
              <Text strong>{bond.name}</Text>
              <Text type="secondary">{bond.code}</Text>
            </Space>
          }
          placement="bottom"
          height="70%"
          open={!!bond}
          onClose={() => setSelectedBond(null)}
          extra={
            <Space>
              <Button
                type="text"
                icon={isWatched ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                onClick={handleToggleWatch}
              />
              <Button type="text" icon={<BellOutlined />} onClick={() => setAlertVisible(true)} />
            </Space>
          }
        >
          {content}
        </Drawer>
        <AlertPanel visible={alertVisible} onClose={() => setAlertVisible(false)} selectedCode={bond.code} selectedName={bond.name} />
      </>
    )
  }

  return (
    <>
      <div style={{ width: 320, borderLeft: '1px solid var(--border-color, #e8e8e8)', height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--card-bg, #fff)', overflow: 'auto' }}>
        <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0', background: 'var(--bg-color, #fafafa)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Space direction="vertical" size={4}>
            <Title level={5} style={{ margin: 0 }}>{bond.name}</Title>
            <Text type="secondary">{bond.code}</Text>
          </Space>
          <Space>
            <Button
              type="text"
              size="small"
              icon={isWatched ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
              onClick={handleToggleWatch}
              title={isWatched ? '取消自选' : '加入自选'}
            />
            <Button type="text" size="small" icon={<BellOutlined />} onClick={() => setAlertVisible(true)} title="设置告警" />
            <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => setSelectedBond(null)} />
          </Space>
        </div>
        {content}
      </div>
      <AlertPanel visible={alertVisible} onClose={() => setAlertVisible(false)} selectedCode={bond.code} selectedName={bond.name} />
    </>
  )
}
