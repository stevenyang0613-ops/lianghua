import { useState, useMemo } from 'react'
import { Card, Descriptions, Tag, Typography, Space, Statistic, Row, Col, Button, Drawer, Tabs } from 'antd'
import { CloseOutlined, ArrowUpOutlined, ArrowDownOutlined, StarOutlined, StarFilled, BellOutlined } from '@ant-design/icons'
import { useAppStore } from '../stores/useAppStore'
import { useMarketStore } from '../stores/useMarketStore'
import { useWatchlistStore } from '../stores/useWatchlistStore'
import { useResponsive } from '../hooks/useResponsive'
import ChartPanel from './ChartPanel'
import AlertPanel from './AlertPanel'

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

  const priceColor = bond.change_pct > 0 ? '#cf1322' : bond.change_pct < 0 ? '#389e0d' : undefined
  const premiumColor = bond.premium_ratio < 0 ? '#52c41a' : bond.premium_ratio > 50 ? '#faad14' : undefined
  const dualLowColor = bond.dual_low < 130 ? '#52c41a' : bond.dual_low > 180 ? '#f5222d' : '#faad14'

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
              <Descriptions.Item label="正股价">{bond.stock_price.toFixed(2)} 元</Descriptions.Item>
              <Descriptions.Item label="正股涨跌">
                <Tag color={bond.stock_change_pct > 0 ? 'red' : bond.stock_change_pct < 0 ? 'green' : undefined}>
                  {bond.stock_change_pct > 0 ? '+' : ''}{bond.stock_change_pct.toFixed(2)}%
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="转股价">{bond.conversion_price.toFixed(2)} 元</Descriptions.Item>
              <Descriptions.Item label="转股价值">{bond.conversion_value.toFixed(2)} 元</Descriptions.Item>
              <Descriptions.Item label="溢价率">
                <Text style={{ color: premiumColor, fontWeight: 600 }}>{bond.premium_ratio.toFixed(2)}%</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card size="small" title="估值指标" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="双低值">
                <Tag color={dualLowColor}>{bond.dual_low.toFixed(2)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="到期收益率">
                <Text type={bond.ytm > 0 ? 'success' : 'danger'}>{bond.ytm.toFixed(2)}%</Text>
              </Descriptions.Item>
              <Descriptions.Item label="剩余年限">{bond.remaining_years.toFixed(1)} 年</Descriptions.Item>
              <Descriptions.Item label="强赎倒计时">
                {bond.forced_call_days > 0 ? `${bond.forced_call_days} 天` : '未触发'}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card size="small" title="交易数据" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="成交额">{bond.volume.toFixed(2)} 亿元</Descriptions.Item>
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
              prefix={bond.change_pct > 0 ? <ArrowUpOutlined /> : bond.change_pct < 0 ? <ArrowDownOutlined /> : null}
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
