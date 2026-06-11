/**
 * 多账户资金归集分析组件
 * 展示多账户资金汇总、归集建议、资金调拨方案
 */

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Card, Row, Col, Table, Button, Space, Typography, Tag, Progress,
  Statistic, Empty, Tabs, Select, Modal, Form,
  message, Descriptions, Alert
} from 'antd'
import {
  BankOutlined, SwapOutlined, AccountBookOutlined,
  HistoryOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import ReactECharts from 'echarts-for-react'
import { multiAccountManager, type AccountBalance, type AccountConfig } from '../utils/multiAccountManager'

const { Title, Text } = Typography
const { TabPane } = Tabs

// 资金归集方案
interface AggregationPlan {
  id: string
  name: string
  type: 'concentrate' | 'distribute' | 'rebalance'
  sourceAccounts: string[]
  targetAccounts: string[]
  transfers: Array<{
    fromAccountId: string
    fromAccountName: string
    toAccountId: string
    toAccountName: string
    amount: number
    reason: string
  }>
  totalAmount: number
  estimatedTime: number
  risk: 'low' | 'medium' | 'high'
  createdAt: number
}

// 资金调拨记录
interface TransferRecord {
  id: string
  fromAccountId: string
  fromAccountName: string
  toAccountId: string
  toAccountName: string
  amount: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
  createdAt: number
  completedAt?: number
  error?: string
}

// 账户资金状态
interface AccountFundStatus {
  account: AccountConfig
  balance: AccountBalance | null
  utilization: number       // 资金利用率
  efficiency: number        // 资金效率评分
  suggestion: string        // 优化建议
}

interface Props {
  onTransfer?: (transfer: { from: string; to: string; amount: number }) => Promise<boolean>
}

export default function FundAggregation({ onTransfer }: Props) {
  const [loading, setLoading] = useState(false)
  const [accounts, setAccounts] = useState<AccountFundStatus[]>([])
  const [aggregationPlans, setAggregationPlans] = useState<AggregationPlan[]>([])
  const [transferHistory, setTransferHistory] = useState<TransferRecord[]>([])
  const [selectedPlan, setSelectedPlan] = useState<AggregationPlan | null>(null)
  const [planModalVisible, setPlanModalVisible] = useState(false)
  const [executeModalVisible, setExecuteModalVisible] = useState(false)
  const [form] = Form.useForm()

  // 加载数据
  useEffect(() => {
    loadData()
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)

    // 获取所有账户
    const allAccounts = multiAccountManager.getAllAccounts()

    // 获取每个账户的资金状态
    const fundStatuses = allAccounts.map(account => {
      const balance = multiAccountManager.getBalance(account.id)
      const utilization = balance ? (balance.totalAsset > 0 ? (balance.marketValue / balance.totalAsset) * 100 : 0) : 0
      const efficiency = calculateEfficiency(balance ?? null)

      return {
        account,
        balance,
        utilization,
        efficiency,
        suggestion: generateSuggestion(utilization, efficiency),
      }
    })

    setAccounts(fundStatuses as any)

    // 生成归集建议
    generateAggregationPlans(fundStatuses as any)

    setLoading(false)
  }, [])

  // 计算资金效率
  const calculateEfficiency = (balance: AccountBalance | null): number => {
    if (!balance) return 0

    // 效率 = (可用资金 / 总资产) * 收益率因子
    const liquidityRatio = balance.totalAsset > 0 ? balance.availableCash / balance.totalAsset : 0
    const profitFactor = balance.profitTotal > 0 ? 1.2 : balance.profitTotal < 0 ? 0.8 : 1.0

    return Math.min(100, liquidityRatio * 100 * profitFactor)
  }

  // 生成优化建议
  const generateSuggestion = (utilization: number, efficiency: number): string => {
    if (utilization > 90) {
      return '资金利用率过高，建议减仓或追加资金'
    } else if (utilization < 30) {
      return '资金利用率较低，建议增加投资或调出闲置资金'
    } else if (efficiency < 50) {
      return '资金效率偏低，建议优化持仓结构'
    } else if (efficiency > 80) {
      return '资金配置良好，继续保持'
    }
    return '资金配置合理，可考虑小幅优化'
  }

  // 生成归集方案
  const generateAggregationPlans = (fundStatuses: AccountFundStatus[]) => {
    const plans: AggregationPlan[] = []

    // 方案1: 集中闲置资金
    const idleAccounts = fundStatuses.filter(s =>
      s.balance && s.balance.totalAsset > 0 && s.balance.availableCash / s.balance.totalAsset > 0.5
    )

    if (idleAccounts.length > 1) {
      const targetAccount = fundStatuses.find(s =>
        s.balance && s.efficiency > 70
      )?.account || idleAccounts[0]?.account

      if (targetAccount) {
        plans.push({
          id: 'plan_concentrate',
          name: '闲置资金集中',
          type: 'concentrate',
          sourceAccounts: idleAccounts.map(s => s.account.id).filter(id => id !== targetAccount.id),
          targetAccounts: [targetAccount.id],
          transfers: idleAccounts
            .filter(s => s.account.id !== targetAccount.id && s.balance)
            .map(s => ({
              fromAccountId: s.account.id,
              fromAccountName: s.account.name,
              toAccountId: targetAccount.id,
              toAccountName: targetAccount.name,
              amount: s.balance!.availableCash * 0.5,  // 转出一半闲置资金
              reason: '闲置资金归集',
            })),
          totalAmount: idleAccounts.reduce((sum, s) =>
            sum + (s.balance?.availableCash || 0) * 0.5, 0
          ),
          estimatedTime: 5,
          risk: 'low',
          createdAt: Date.now(),
        })
      }
    }

    // 方案2: 风险账户资金调出
    const riskAccounts = fundStatuses.filter(s =>
      s.balance && s.balance.profitToday < 0 && Math.abs(s.balance.profitToday) > s.balance.totalAsset * 0.02
    )

    if (riskAccounts.length > 0) {
      const safeAccounts = fundStatuses.filter(s =>
        s.balance && s.efficiency > 60 && !riskAccounts.includes(s)
      )

      if (safeAccounts.length > 0) {
        plans.push({
          id: 'plan_risk_reduce',
          name: '风险账户减仓',
          type: 'rebalance',
          sourceAccounts: riskAccounts.map(s => s.account.id),
          targetAccounts: safeAccounts.map(s => s.account.id),
          transfers: riskAccounts.flatMap(risk =>
            safeAccounts.slice(0, 1).map(safe => ({
              fromAccountId: risk.account.id,
              fromAccountName: risk.account.name,
              toAccountId: safe.account.id,
              toAccountName: safe.account.name,
              amount: risk.balance!.availableCash * 0.3,
              reason: '风险账户资金调出',
            }))
          ),
          totalAmount: riskAccounts.reduce((sum, s) =>
            sum + (s.balance?.availableCash || 0) * 0.3, 0
          ),
          estimatedTime: 10,
          risk: 'medium',
          createdAt: Date.now(),
        })
      }
    }

    // 方案3: 资金均衡分配
    const totalFunds = fundStatuses.reduce((sum, s) =>
      sum + (s.balance?.availableCash || 0), 0
    )
    const avgFunds = totalFunds / fundStatuses.length || 0

    const lowFundsAccounts = fundStatuses.filter(s =>
      s.balance && s.balance.availableCash < avgFunds * 0.8
    )
    const highFundsAccounts = fundStatuses.filter(s =>
      s.balance && s.balance.availableCash > avgFunds * 1.2
    )

    if (lowFundsAccounts.length > 0 && highFundsAccounts.length > 0) {
      plans.push({
        id: 'plan_balance',
        name: '资金均衡分配',
        type: 'distribute',
        sourceAccounts: highFundsAccounts.map(s => s.account.id),
        targetAccounts: lowFundsAccounts.map(s => s.account.id),
        transfers: highFundsAccounts.flatMap(high =>
          lowFundsAccounts.slice(0, 1).map(low => ({
            fromAccountId: high.account.id,
            fromAccountName: high.account.name,
            toAccountId: low.account.id,
            toAccountName: low.account.name,
            amount: Math.min(
              high.balance!.availableCash - avgFunds,
              avgFunds - low.balance!.availableCash
            ),
            reason: '资金均衡化',
          }))
        ),
        totalAmount: highFundsAccounts.reduce((sum, s) =>
          sum + Math.max(0, (s.balance?.availableCash || 0) - avgFunds), 0
        ),
        estimatedTime: 15,
        risk: 'low',
        createdAt: Date.now(),
      })
    }

    setAggregationPlans(plans)
  }

  // 汇总统计
  const summary = useMemo(() => {
    const totalAsset = accounts.reduce((sum, s) =>
      sum + (s.balance?.totalAsset || 0), 0
    )
    const totalAvailableCash = accounts.reduce((sum, s) =>
      sum + (s.balance?.availableCash || 0), 0
    )
    const totalMarketValue = accounts.reduce((sum, s) =>
      sum + (s.balance?.marketValue || 0), 0
    )
    const totalProfitToday = accounts.reduce((sum, s) =>
      sum + (s.balance?.profitToday || 0), 0
    )
    const avgUtilization = accounts.reduce((sum, s) =>
      sum + s.utilization, 0
    ) / (accounts.length || 1)
    const avgEfficiency = accounts.reduce((sum, s) =>
      sum + s.efficiency, 0
    ) / (accounts.length || 1)

    return {
      totalAsset,
      totalAvailableCash,
      totalMarketValue,
      totalProfitToday,
      avgUtilization,
      avgEfficiency,
      accountCount: accounts.length,
    }
  }, [accounts])

  // 账户表格列
  const accountColumns: ColumnsType<AccountFundStatus> = [
    {
      title: '账户名称',
      key: 'name',
      render: (_, record) => (
        <Space>
          <BankOutlined />
          <Text strong>{record.account.name}</Text>
          <Tag>{record.account.broker}</Tag>
        </Space>
      ),
    },
    {
      title: '总资产',
      key: 'totalAsset',
      align: 'right',
      render: (_, record) => (
        <Text>¥{(record.balance?.totalAsset || 0).toLocaleString()}</Text>
      ),
      sorter: (a, b) => (a.balance?.totalAsset || 0) - (b.balance?.totalAsset || 0),
    },
    {
      title: '可用资金',
      key: 'availableCash',
      align: 'right',
      render: (_, record) => (
        <Text type="success">¥{(record.balance?.availableCash || 0).toLocaleString()}</Text>
      ),
      sorter: (a, b) => (a.balance?.availableCash || 0) - (b.balance?.availableCash || 0),
    },
    {
      title: '持仓市值',
      key: 'marketValue',
      align: 'right',
      render: (_, record) => (
        <Text>¥{(record.balance?.marketValue || 0).toLocaleString()}</Text>
      ),
    },
    {
      title: '今日盈亏',
      key: 'profitToday',
      align: 'right',
      render: (_, record) => {
        const profit = record.balance?.profitToday || 0
        return (
          <Text style={{ color: profit >= 0 ? '#52c41a' : '#ff4d4f' }}>
            {profit >= 0 ? '+' : ''}¥{profit.toLocaleString()}
          </Text>
        )
      },
      sorter: (a, b) => (a.balance?.profitToday || 0) - (b.balance?.profitToday || 0),
    },
    {
      title: '资金利用率',
      key: 'utilization',
      width: 120,
      render: (_, record) => (
        <Progress
          percent={record.utilization}
          size="small"
          strokeColor={record.utilization > 90 ? '#ff4d4f' : record.utilization > 70 ? '#faad14' : '#52c41a'}
        />
      ),
    },
    {
      title: '效率评分',
      key: 'efficiency',
      width: 80,
      render: (_, record) => (
        <Tag color={record.efficiency > 70 ? 'green' : record.efficiency > 50 ? 'orange' : 'red'}>
          {(record.efficiency ?? 0).toFixed(0)}
        </Tag>
      ),
    },
    {
      title: '优化建议',
      dataIndex: 'suggestion',
      key: 'suggestion',
      ellipsis: true,
      width: 200,
    },
  ]

  // 资金分布饼图配置
  const fundDistributionOption = useMemo(() => ({
    title: {
      text: '资金分布',
      left: 'center',
      textStyle: { color: '#fff', fontSize: 14 },
    },
    tooltip: {
      trigger: 'item',
      formatter: '{b}: ¥{c} ({d}%)',
      backgroundColor: 'rgba(0,0,0,0.8)',
      textStyle: { color: '#fff' },
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 10,
      top: 20,
      bottom: 20,
      textStyle: { color: '#888' },
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['40%', '50%'],
      data: accounts.map(s => ({
        name: s.account.name,
        value: s.balance?.totalAsset || 0,
      })),
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)',
        },
      },
      label: {
        show: false,
      },
    }],
  }), [accounts])

  // 执行资金调拨
  const executePlan = useCallback(async (plan: AggregationPlan) => {
    setSelectedPlan(plan)
    setExecuteModalVisible(true)
  }, [])

  // 确认执行
  const handleConfirmExecute = useCallback(async () => {
    if (!selectedPlan) return

    let successCount = 0
    let failCount = 0

    for (const transfer of selectedPlan.transfers) {
      try {
        const result = onTransfer
          ? await onTransfer({
              from: transfer.fromAccountId,
              to: transfer.toAccountId,
              amount: transfer.amount,
            })
          : true

        if (result) {
          successCount++
          // 添加到历史记录
          setTransferHistory(prev => [{
            id: `transfer_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            ...transfer,
            status: 'completed',
            createdAt: Date.now(),
            completedAt: Date.now(),
          }, ...prev])
        } else {
          failCount++
        }
      } catch (error) {
        failCount++
      }
    }

    setExecuteModalVisible(false)

    if (successCount === selectedPlan.transfers.length) {
      message.success('资金调拨完成')
    } else if (successCount > 0) {
      message.warning(`部分调拨成功，${failCount} 笔失败`)
    } else {
      message.error('资金调拨失败')
    }

    loadData()
  }, [selectedPlan, onTransfer, loadData])

  return (
    <div style={{ padding: 24 }}>
      {/* 汇总概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Card>
            <Statistic
              title="账户总数"
              value={summary.accountCount}
              prefix={<AccountBookOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="总资产"
              value={summary.totalAsset}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#fff' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="可用资金"
              value={summary.totalAvailableCash}
              precision={2}
              prefix="¥"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="今日盈亏"
              value={summary.totalProfitToday}
              precision={2}
              prefix="¥"
              valueStyle={{
                color: summary.totalProfitToday >= 0 ? '#52c41a' : '#ff4d4f',
              }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="平均利用率"
              value={summary.avgUtilization}
              precision={1}
              suffix="%"
              valueStyle={{
                color: summary.avgUtilization > 80 ? '#ff4d4f' : '#52c41a',
              }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="平均效率"
              value={summary.avgEfficiency}
              precision={1}
              suffix="/ 100"
            />
          </Card>
        </Col>
      </Row>

      {/* 主要内容 */}
      <Tabs defaultActiveKey="accounts">
        <TabPane tab={<span><BankOutlined />账户资金</span>} key="accounts">
          <Row gutter={16}>
            <Col span={16}>
              <Card title="账户资金明细">
                <Table
                  columns={accountColumns}
                  dataSource={accounts}
                  rowKey="account.id"
                  pagination={false}
                  size="small"
                  loading={loading}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card title="资金分布">
                <ReactECharts
                  option={fundDistributionOption}
                  style={{ height: 300 }}
                  notMerge
                />
              </Card>
            </Col>
          </Row>
        </TabPane>

        <TabPane tab={<span><SwapOutlined />归集方案</span>} key="plans">
          <Row gutter={16}>
            {aggregationPlans.length === 0 ? (
              <Col span={24}>
                <Empty description="暂无归集建议" />
              </Col>
            ) : (
              aggregationPlans.map(plan => (
                <Col span={8} key={plan.id}>
                  <Card
                    title={plan.name}
                    extra={
                      <Tag color={plan.risk === 'low' ? 'green' : plan.risk === 'medium' ? 'orange' : 'red'}>
                        {plan.risk === 'low' ? '低风险' : plan.risk === 'medium' ? '中风险' : '高风险'}
                      </Tag>
                    }
                  >
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="涉及账户">
                        {plan.sourceAccounts.length + plan.targetAccounts.length} 个
                      </Descriptions.Item>
                      <Descriptions.Item label="调拨笔数">
                        {plan.transfers.length} 笔
                      </Descriptions.Item>
                      <Descriptions.Item label="调拨金额">
                        ¥{(plan.totalAmount ?? 0).toLocaleString()}
                      </Descriptions.Item>
                      <Descriptions.Item label="预计耗时">
                        {plan.estimatedTime} 分钟
                      </Descriptions.Item>
                    </Descriptions>
                    <Button
                      type="primary"
                      block
                      style={{ marginTop: 16 }}
                      onClick={() => executePlan(plan)}
                    >
                      执行方案
                    </Button>
                  </Card>
                </Col>
              ))
            )}
          </Row>
        </TabPane>

        <TabPane tab={<span><HistoryOutlined />调拨记录</span>} key="history">
          <Card>
            <Table
              dataSource={transferHistory}
              rowKey="id"
              pagination={{ pageSize: 20 }}
              columns={[
                {
                  title: '转出账户',
                  dataIndex: 'fromAccountName',
                  key: 'fromAccountName',
                },
                {
                  title: '转入账户',
                  dataIndex: 'toAccountName',
                  key: 'toAccountName',
                },
                {
                  title: '金额',
                  dataIndex: 'amount',
                  key: 'amount',
                  render: (v: number) => `¥${(v ?? 0).toLocaleString()}`,
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  key: 'status',
                  render: (status: string) => (
                    <Tag color={
                      status === 'completed' ? 'green' :
                      status === 'processing' ? 'blue' :
                      status === 'pending' ? 'default' : 'red'
                    }>
                      {status === 'completed' ? '已完成' :
                       status === 'processing' ? '处理中' :
                       status === 'pending' ? '待处理' : '失败'}
                    </Tag>
                  ),
                },
                {
                  title: '时间',
                  dataIndex: 'createdAt',
                  key: 'createdAt',
                  render: (v: number) => new Date(v).toLocaleString(),
                },
              ]}
            />
          </Card>
        </TabPane>
      </Tabs>

      {/* 执行确认弹窗 */}
      <Modal
        title="确认执行资金调拨"
        open={executeModalVisible}
        onOk={handleConfirmExecute}
        onCancel={() => setExecuteModalVisible(false)}
        okText="确认执行"
        cancelText="取消"
      >
        {selectedPlan && (
          <>
            <Alert
              message={`即将执行 "${selectedPlan.name}" 方案`}
              description={`共 ${selectedPlan.transfers.length} 笔调拨，总金额 ¥${(selectedPlan.totalAmount ?? 0).toLocaleString()}`}
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
            />
            <Table
              dataSource={selectedPlan.transfers}
              rowKey="fromAccountId"
              size="small"
              pagination={false}
              columns={[
                { title: '转出', dataIndex: 'fromAccountName' },
                { title: '转入', dataIndex: 'toAccountName' },
                {
                  title: '金额',
                  dataIndex: 'amount',
                  render: (v: number) => `¥${(v ?? 0).toLocaleString()}`,
                },
                { title: '原因', dataIndex: 'reason' },
              ]}
            />
          </>
        )}
      </Modal>
    </div>
  )
}
