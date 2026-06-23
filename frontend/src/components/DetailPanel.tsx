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
              {bond.turnover_rate !== undefined && (
                <Descriptions.Item label="换手率">{fmt(bond.turnover_rate)}%</Descriptions.Item>
              )}
              {bond.outstanding_scale !== undefined && (
                <Descriptions.Item label="剩余规模">{fmt(bond.outstanding_scale)} 亿</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card size="small" title="正股财务" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              {bond.pe !== undefined && (
                <Descriptions.Item label="PE">{fmt(bond.pe)}</Descriptions.Item>
              )}
              {bond.pb !== undefined && (
                <Descriptions.Item label="PB">{fmt(bond.pb)}</Descriptions.Item>
              )}
              {bond.roe !== undefined && (
                <Descriptions.Item label="ROE">{fmt(bond.roe)}%</Descriptions.Item>
              )}
  // 从已缓存的 bond 中解析 gpm（避免每次重渲染重新计算）
  const gpmRender = useMemo(() => {
    const gpm = Number(bond.gpm)
    const isBankNoGPM = Math.abs(gpm - (-1)) < 0.01
    if (isBankNoGPM) return null
    const gpmVal = isNaN(gpm) ? null : gpm
    if (gpmVal === null || gpmVal === undefined) return null
    return (
      <Descriptions.Item label="毛利率">
        {gpmVal > 0 ? `${fmt(gpmVal)}%` : gpmVal === 0 ? '0%' : gpmVal < 0 ? '数据异常' : '银行(无毛利率)'}
      </Descriptions.Item>
    )
  }, [bond.gpm])
              {bond.debt_ratio !== undefined && (
                <Descriptions.Item label="资产负债率">{fmt(bond.debt_ratio)}%</Descriptions.Item>
              )}
              {bond.current_ratio !== undefined && (
                <Descriptions.Item label="流动比率">{fmt(bond.current_ratio)}</Descriptions.Item>
              )}
              {bond.eps !== undefined && (
                <Descriptions.Item label="EPS">{fmt(bond.eps)}</Descriptions.Item>
              )}
              {bond.bps !== undefined && (
                <Descriptions.Item label="BPS">{fmt(bond.bps)}</Descriptions.Item>
              )}
              {bond.revenue_yoy !== undefined && (
                <Descriptions.Item label="营收增速">
                  <Tag color={(bond.revenue_yoy ?? 0) > 0 ? 'green' : 'red'}>
                    {(bond.revenue_yoy ?? 0) > 0 ? '+' : ''}{fmt(bond.revenue_yoy)}%
                  </Tag>
                </Descriptions.Item>
              )}
              {bond.profit_yoy !== undefined && (
                <Descriptions.Item label="利润增速">
                  <Tag color={(bond.profit_yoy ?? 0) > 0 ? 'green' : 'red'}>
                    {(bond.profit_yoy ?? 0) > 0 ? '+' : ''}{fmt(bond.profit_yoy)}%
                  </Tag>
                </Descriptions.Item>
              )}
              {bond.industry && (
                <Descriptions.Item label="行业">{bond.industry}</Descriptions.Item>
              )}
              {bond.concepts && bond.concepts.length > 0 && (
                <Descriptions.Item label="概念">
                  {bond.concepts.map(c => <Tag key={c}>{c}</Tag>)}
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card size="small" title="资金与情绪" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              {bond.north_net !== undefined && (
                <Descriptions.Item label="北向资金">{fmt(bond.north_net)} 亿</Descriptions.Item>
              )}
              {bond.margin_balance !== undefined && (
                <Descriptions.Item label="融资余额">{fmt(bond.margin_balance)} 亿</Descriptions.Item>
              )}
              {bond.net_capital_flow !== undefined && (
                <Descriptions.Item label="主力净流入">
                  <Tag color={(bond.net_capital_flow ?? 0) > 0 ? 'red' : 'green'}>
                    {(bond.net_capital_flow ?? 0) > 0 ? '+' : ''}{fmt(bond.net_capital_flow)} 万
                  </Tag>
                </Descriptions.Item>
              )}
              {bond.sentiment_score !== undefined && (
                <Descriptions.Item label="新闻情绪">
                  <Tag color={
                    (bond.sentiment_score ?? 0) > 0.3 ? 'green' :
                    (bond.sentiment_score ?? 0) < -0.3 ? 'red' : 'default'
                  }>
                    {(bond.sentiment_score ?? 0) > 0.3 ? '正面' :
                     (bond.sentiment_score ?? 0) < -0.3 ? '负面' : '中性'}
                    ({fmt(bond.sentiment_score)})
                  </Tag>
                </Descriptions.Item>
              )}
              {bond.lhb_count !== undefined && bond.lhb_count > 0 && (
                <Descriptions.Item label="龙虎榜">近5日 {bond.lhb_count} 次</Descriptions.Item>
              )}
              {bond.block_trade_amount !== undefined && bond.block_trade_amount > 0 && (
                <Descriptions.Item label="大宗交易">{fmt(bond.block_trade_amount)} 万</Descriptions.Item>
              )}
              {bond.pledge_ratio !== undefined && (
                <Descriptions.Item label="质押率">{fmt(bond.pledge_ratio)}%</Descriptions.Item>
              )}
              {bond.holder_num_change !== undefined && (
                <Descriptions.Item label="股东户数变化">
                  <Tag color={(bond.holder_num_change ?? 0) > 0 ? 'red' : 'green'}>
                    {(bond.holder_num_change ?? 0) > 0 ? '+' : ''}{fmt(bond.holder_num_change)}%
                  </Tag>
                </Descriptions.Item>
              )}
              {bond.buyback_amount !== undefined && bond.buyback_amount > 0 && (
                <Descriptions.Item label="回购金额">{fmt(bond.buyback_amount)} 亿</Descriptions.Item>
              )}
              {bond.mgmt_buy_price !== undefined && bond.mgmt_buy_price > 0 && (
                <Descriptions.Item label="管理层增持">{fmt(bond.mgmt_buy_price)} 元</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card size="small" title="动量与事件" style={{ margin: '0 16px 16px' }}>
            <Descriptions column={1} size="small">
              {bond.momentum_5d !== undefined && (
                <Descriptions.Item label="5日动量">{fmt(bond.momentum_5d)}%</Descriptions.Item>
              )}
              {bond.momentum_20d !== undefined && (
                <Descriptions.Item label="20日动量">{fmt(bond.momentum_20d)}%</Descriptions.Item>
              )}
              {bond.momentum_60d !== undefined && (
                <Descriptions.Item label="60日动量">{fmt(bond.momentum_60d)}%</Descriptions.Item>
              )}
              {bond.event_score !== undefined && (
                <Descriptions.Item label="事件评分">{fmt(bond.event_score)}</Descriptions.Item>
              )}
              {bond.event_detail && (
                <Descriptions.Item label="最近事件">{bond.event_detail}</Descriptions.Item>
              )}
              {bond.hv !== undefined && (
                <Descriptions.Item label="历史波动率">{fmt(bond.hv)}%</Descriptions.Item>
              )}
              {bond.iv !== undefined && (
                <Descriptions.Item label="隐含波动率">{fmt(bond.iv)}%</Descriptions.Item>
              )}
              {bond.rating_score !== undefined && (
                <Descriptions.Item label="评级评分">{fmt(bond.rating_score)}</Descriptions.Item>
              )}
              {bond.pure_bond_premium_ratio !== undefined && (
                <Descriptions.Item label="纯债溢价率">{fmt(bond.pure_bond_premium_ratio)}%</Descriptions.Item>
              )}
              {bond.bond_value !== undefined && (
                <Descriptions.Item label="纯债价值">{fmt(bond.bond_value)} 元</Descriptions.Item>
              )}
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
