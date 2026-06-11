/**
 * 风控管理页面
 */

import { useEffect, useState } from 'react'
import { Card, Table, Switch, Button, Space, Typography, Row, Col, Statistic, Tag, Progress, Alert, Modal, InputNumber, Select, Divider, Empty, message } from 'antd'
import { SafetyOutlined, SettingOutlined, ReloadOutlined, HistoryOutlined } from '@ant-design/icons'
import { getRiskRules, updateRiskRule, resetRiskRules, getRiskHistory, type RiskRule } from '../utils/riskManager'
import type { ColumnsType } from 'antd/es/table'
import { fmt } from '../utils/format'

const { Title, Text, Paragraph } = Typography




export default function RiskControl() {
  const [rules, setRules] = useState<RiskRule[]>([])
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingRule, setEditingRule] = useState<RiskRule | null>(null)
  const [historyVisible, setHistoryVisible] = useState(false)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = () => {
    setRules(getRiskRules())
  }

  const handleToggleRule = (id: string, enabled: boolean) => {
    updateRiskRule(id, { enabled, triggered: false, triggeredAt: null })
    loadData()
    message.success(enabled ? '规则已启用' : '规则已禁用')
  }

  const handleEditRule = () => {
    if (!editingRule) return
    updateRiskRule(editingRule.id, {
      threshold: editingRule.threshold,
      level: editingRule.level,
      action: editingRule.action,
    })
    loadData()
    setEditModalVisible(false)
    setEditingRule(null)
    message.success('规则已更新')
  }

  const handleReset = () => {
    resetRiskRules()
    loadData()
    message.success('已重置为默认规则')
  }

  const levelColors: Record<string, string> = {
    info: 'default',
    warning: 'warning',
    critical: 'error',
  }

  const actionLabels: Record<string, string> = {
    alert: '预警通知',
    block: '禁止交易',
    auto_close: '自动平仓',
  }

  const columns: ColumnsType<RiskRule> = [
    {
      title: '规则名称',
      dataIndex: 'name',
      width: 150,
      render: (name: string, record) => (
        <Space>
          <Text strong>{name}</Text>
          {record.triggered && <Tag color="warning">已触发</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 80,
      render: (enabled: boolean, record) => (
        <Switch
          size="small"
          checked={enabled}
          onChange={(checked) => handleToggleRule(record.id, checked)}
        />
      ),
    },
    {
      title: '阈值',
      dataIndex: 'threshold',
      width: 100,
      render: (v: number) => `${v}%`,
    },
    {
      title: '当前值',
      dataIndex: 'current',
      width: 100,
      render: (v: number, record) => {
        const exceeded = record.type === 'drawdown' || record.type === 'loss_limit'
          ? v < record.threshold
          : v > record.threshold
        return (
          <Text style={{ color: exceeded ? '#ff4d4f' : '#52c41a' }}>
            {fmt(v, 1)}%
          </Text>
        )
      },
    },
    {
      title: '风险等级',
      dataIndex: 'level',
      width: 100,
      render: (level: string) => (
        <Tag color={levelColors[level]}>{level === 'info' ? '信息' : level === 'warning' ? '警告' : '严重'}</Tag>
      ),
    },
    {
      title: '触发动作',
      dataIndex: 'action',
      width: 100,
      render: (action: string) => actionLabels[action] || action,
    },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_, record) => (
        <Button
          size="small"
          icon={<SettingOutlined />}
          onClick={() => {
            setEditingRule(record)
            setEditModalVisible(true)
          }}
        >
          设置
        </Button>
      ),
    },
  ]

  // 模拟风险状态
  const mockStatus = {
    overallLevel: 'safe',
    rules,
    lastCheck: Date.now(),
    recommendations: rules.filter(r => r.triggered).map(r => `【${r.name}】规则已触发`),
  }

  const overallColor = mockStatus.overallLevel === 'safe' ? '#52c41a'
    : mockStatus.overallLevel === 'warning' ? '#faad14'
    : mockStatus.overallLevel === 'danger' ? '#ff7875'
    : '#ff4d4f'

  const history = getRiskHistory().slice(-10).reverse()

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><SafetyOutlined style={{ marginRight: 8 }} />风控管理</Title>

      {/* 风险概览 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={6}>
            <div style={{ textAlign: 'center' }}>
              <Progress
                type="circle"
                percent={100}
                strokeColor={overallColor}
                format={() => (
                  <span style={{ fontSize: 16 }}>
                    {mockStatus.overallLevel === 'safe' ? '安全'
                      : mockStatus.overallLevel === 'warning' ? '警告'
                      : mockStatus.overallLevel === 'danger' ? '危险' : '危急'}
                  </span>
                )}
                size={100}
              />
              <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>整体风险</Paragraph>
            </div>
          </Col>
          <Col span={18}>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic
                  title="启用规则"
                  value={rules.filter(r => r.enabled).length}
                  suffix={`/ ${rules.length}`}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="已触发"
                  value={rules.filter(r => r.triggered).length}
                  valueStyle={{ color: rules.filter(r => r.triggered).length > 0 ? '#ff4d4f' : '#52c41a' }}
                />
              </Col>
              <Col span={6}>
                <Statistic
                  title="最后检查"
                  value={new Date().toLocaleTimeString()}
                  valueStyle={{ fontSize: 14 }}
                />
              </Col>
              <Col span={6}>
                <Space direction="vertical">
                  <Button icon={<HistoryOutlined />} onClick={() => setHistoryVisible(true)}>
                    查看历史
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={handleReset}>
                    重置规则
                  </Button>
                </Space>
              </Col>
            </Row>
          </Col>
        </Row>
      </Card>

      {/* 风控建议 */}
      {mockStatus.recommendations.length > 0 && (
        <Alert
          type={mockStatus.overallLevel === 'safe' ? 'success' : mockStatus.overallLevel === 'warning' ? 'warning' : 'error'}
          message="风控建议"
          description={
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {mockStatus.recommendations.map((rec: string, i: number) => (
                <li key={i}>{rec}</li>
              ))}
            </ul>
          }
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 风控规则 */}
      <Card title="风控规则">
        <Table
          dataSource={rules}
          columns={columns}
          rowKey="id"
          pagination={false}
          size="small"
        />
      </Card>

      {/* 编辑规则弹窗 */}
      <Modal
        title={`编辑规则: ${editingRule?.name}`}
        open={editModalVisible}
        onOk={handleEditRule}
        onCancel={() => {
          setEditModalVisible(false)
          setEditingRule(null)
        }}
        okText="保存"
        cancelText="取消"
      >
        {editingRule && (
          <div>
            <Paragraph type="secondary">{editingRule.description}</Paragraph>
            <Divider />
            <Row gutter={16}>
              <Col span={12}>
                <div style={{ marginBottom: 8 }}>
                  <Text>阈值 (%)</Text>
                </div>
                <InputNumber
                  style={{ width: '100%' }}
                  value={editingRule.threshold}
                  onChange={(v) => setEditingRule({ ...editingRule, threshold: v || 0 })}
                />
              </Col>
              <Col span={12}>
                <div style={{ marginBottom: 8 }}>
                  <Text>风险等级</Text>
                </div>
                <Select
                  style={{ width: '100%' }}
                  value={editingRule.level}
                  onChange={(v) => setEditingRule({ ...editingRule, level: v })}
                  options={[
                    { value: 'info', label: '信息' },
                    { value: 'warning', label: '警告' },
                    { value: 'critical', label: '严重' },
                  ]}
                />
              </Col>
            </Row>
            <Divider />
            <div style={{ marginBottom: 8 }}>
              <Text>触发动作</Text>
            </div>
            <Select
              style={{ width: '100%' }}
              value={editingRule.action}
              onChange={(v) => setEditingRule({ ...editingRule, action: v })}
              options={[
                { value: 'alert', label: '预警通知' },
                { value: 'block', label: '禁止交易' },
                { value: 'auto_close', label: '自动平仓' },
              ]}
            />
          </div>
        )}
      </Modal>

      {/* 历史记录弹窗 */}
      <Modal
        title="风控历史"
        open={historyVisible}
        onCancel={() => setHistoryVisible(false)}
        footer={null}
        width={600}
      >
        {history.length === 0 ? (
          <Empty description="暂无历史记录" />
        ) : (
          <Table
            dataSource={history}
            columns={[
              { title: '时间', dataIndex: 'timestamp', width: 160, render: (v) => new Date(v).toLocaleString('zh-CN') },
              {
                title: '风险等级',
                dataIndex: 'level',
                width: 100,
                render: (v) => (
                  <Tag color={v === 'safe' ? 'green' : v === 'warning' ? 'orange' : 'red'}>
                    {v === 'safe' ? '安全' : v === 'warning' ? '警告' : '危险'}
                  </Tag>
                ),
              },
              { title: '触发规则', dataIndex: 'rules', render: (v: string[]) => (v ?? []).join(', ') || '-' },
            ]}
            rowKey="timestamp"
            pagination={false}
            size="small"
          />
        )}
      </Modal>
    </div>
  )
}
