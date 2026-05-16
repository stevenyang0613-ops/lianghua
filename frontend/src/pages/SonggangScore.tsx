/**
 * 松岗七维打分排名页面
 *
 * 七维评分体系：
 * - 正股七维（55分）：短期动量、板块情绪、技术面、筹码面、波动率、消息面、基本面
 * - 转债自身（45分）：估值指标、条款价值、流动性、信用评分
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Spin, Empty, message, Typography,
  Slider, Select, Space, Button, Progress, Modal, Descriptions,
  Alert, Divider
} from 'antd'
import {
  TrophyOutlined, ReloadOutlined, StarOutlined,
  AlertOutlined, CloseCircleOutlined, InfoCircleOutlined
} from '@ant-design/icons'
import {
  fetchSonggangRanking, fetchSonggangSingleScore,
  type SonggangScoreItem, type SonggangVetoedItem, type BufferStatusItem,
  type SonggangSingleScore
} from '../services/api'

const { Title, Text } = Typography

const STORAGE_KEY = 'songgang_score_config'

// 七维评分颜色映射
const scoreColor = (v: number, max: number = 100) => {
  const ratio = v / max
  if (ratio >= 0.8) return '#52c41a'
  if (ratio >= 0.6) return '#1677ff'
  if (ratio >= 0.4) return '#faad14'
  return '#ff4d4f'
}

// 维度名称映射
const STOCK_DIMENSION_NAMES: Record<string, string> = {
  momentum: '短期动量',
  sector: '板块情绪',
  technical: '技术面',
  chip: '筹码面',
  volatility: '波动率',
  news: '消息面',
  fundamental: '基本面',
}

const BOND_DIMENSION_NAMES: Record<string, string> = {
  valuation: '估值指标',
  clause: '条款价值',
  liquidity: '流动性',
  credit: '信用评分',
}

// 加载配置
function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return { topN: 60, aumLevel: 'small', marketEnv: 'neutral' }
}

function saveConfig(config: { topN: number; aumLevel: string; marketEnv: string }) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(config)) } catch { /* ignore */ }
}

export default function SonggangScore() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{
    total: number
    returned: number
    market_env: string
    aum_level: string
    items: SonggangScoreItem[]
    vetoed: SonggangVetoedItem[]
    vetoed_count: number
    buffer_status: BufferStatusItem[]
  } | null>(null)

  const savedConfig = useMemo(() => loadConfig(), [])

  const [topN, setTopN] = useState(savedConfig.topN)
  const [aumLevel, setAumLevel] = useState<'small' | 'medium' | 'large'>(savedConfig.aumLevel)
  const [marketEnv, setMarketEnv] = useState<'bull' | 'bear' | 'neutral'>(savedConfig.marketEnv)

  // 详情弹窗
  const [detailVisible, setDetailVisible] = useState(false)
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [selectedDetail, setSelectedDetail] = useState<SonggangSingleScore | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // 被否决列表
  const [vetoedVisible, setVetoedVisible] = useState(false)

  // 缓冲带状态
  const [bufferVisible, setBufferVisible] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const result = await fetchSonggangRanking(topN, aumLevel, marketEnv)
      setData(result)
      saveConfig({ topN, aumLevel, marketEnv })
    } catch (e: any) {
      message.error(`加载失败: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }, [topN, aumLevel, marketEnv])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // 查看详情
  const handleViewDetail = async (code: string) => {
    setSelectedCode(code)
    setDetailVisible(true)
    setDetailLoading(true)
    try {
      const detail = await fetchSonggangSingleScore(code, aumLevel)
      setSelectedDetail(detail)
    } catch (e: any) {
      message.error(`加载详情失败: ${e.message}`)
    } finally {
      setDetailLoading(false)
    }
  }

  // 市场环境标签
  const getMarketEnvTag = (env: string) => {
    const config: Record<string, { color: string; text: string }> = {
      bull: { color: 'red', text: '牛市' },
      bear: { color: 'green', text: '熊市' },
      neutral: { color: 'blue', text: '震荡市' },
    }
    const c = config[env] || config.neutral
    return <Tag color={c.color}>{c.text}</Tag>
  }

  // AUM等级标签
  const getAumLevelTag = (level: string) => {
    const config: Record<string, { color: string; text: string }> = {
      small: { color: 'blue', text: '<1亿' },
      medium: { color: 'orange', text: '1-5亿' },
      large: { color: 'red', text: '5-10亿' },
    }
    const c = config[level] || config.small
    return <Tag color={c.color}>{c.text}</Tag>
  }

  // 表格列定义
  const columns = [
    {
      title: '排名',
      dataIndex: 'rank',
      key: 'rank',
      width: 60,
      render: (rank: number) => (
        <span style={{ fontWeight: 'bold', color: rank <= 10 ? '#faad14' : undefined }}>
          {rank <= 3 ? <TrophyOutlined style={{ color: '#faad14', marginRight: 4 }} /> : null}
          {rank}
        </span>
      ),
    },
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 90,
      render: (code: string) => (
        <a onClick={() => handleViewDetail(code)} style={{ color: '#1677ff' }}>{code}</a>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 100,
    },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 80,
      render: (v: number) => <Text style={{ color: v < 100 ? '#52c41a' : v > 130 ? '#ff4d4f' : undefined }}>{v.toFixed(2)}</Text>,
    },
    {
      title: '溢价率',
      dataIndex: 'premium_ratio',
      key: 'premium_ratio',
      width: 80,
      render: (v: number) => (
        <Text style={{ color: v < 20 ? '#52c41a' : v > 50 ? '#ff4d4f' : undefined }}>
          {v.toFixed(1)}%
        </Text>
      ),
    },
    {
      title: '双低值',
      dataIndex: 'dual_low',
      key: 'dual_low',
      width: 80,
      render: (v: number) => (
        <Text style={{ color: v < 130 ? '#52c41a' : v > 160 ? '#ff4d4f' : undefined }}>
          {v.toFixed(1)}
        </Text>
      ),
    },
    {
      title: '综合评分',
      dataIndex: 'total_score',
      key: 'total_score',
      width: 100,
      sorter: (a: SonggangScoreItem, b: SonggangScoreItem) => a.total_score - b.total_score,
      render: (v: number) => (
        <Progress
          percent={v}
          size="small"
          strokeColor={scoreColor(v)}
          format={(p) => p?.toFixed(1)}
        />
      ),
    },
    {
      title: '正股评分',
      dataIndex: 'stock_score',
      key: 'stock_score',
      width: 90,
      render: (v: number) => <Text style={{ color: scoreColor(v, 55) }}>{v.toFixed(1)}</Text>,
    },
    {
      title: '转债评分',
      dataIndex: 'bond_score',
      key: 'bond_score',
      width: 90,
      render: (v: number) => <Text style={{ color: scoreColor(v, 45) }}>{v.toFixed(1)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: any, record: SonggangScoreItem) => (
        <Space>
          <Button size="small" type="link" onClick={() => handleViewDetail(record.code)}>
            详情
          </Button>
        </Space>
      ),
    },
  ]

  // 被否决表格列
  const vetoedColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    {
      title: '信用评分',
      dataIndex: 'credit_score',
      key: 'credit_score',
      width: 100,
      render: (v: number) => <Text style={{ color: v < 50 ? '#ff4d4f' : '#faad14' }}>{v.toFixed(1)}</Text>,
    },
    {
      title: '否决原因',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (reasons: string[]) => (
        <Space direction="vertical" size="small">
          {reasons.map((r, i) => (
            <Tag key={i} color="red">{r}</Tag>
          ))}
        </Space>
      ),
    },
  ]

  // 缓冲带状态表格列
  const bufferColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 60 },
    {
      title: '评分',
      dataIndex: 'score',
      key: 'score',
      width: 80,
      render: (v: number) => v.toFixed(1),
    },
    {
      title: '缓冲状态',
      dataIndex: 'in_buffer',
      key: 'in_buffer',
      width: 100,
      render: (v: boolean) => v ? <Tag color="orange">缓冲带内</Tag> : <Tag color="blue">白名单内</Tag>,
    },
    {
      title: '连续在60名内',
      dataIndex: 'days_above_60',
      key: 'days_above_60',
      width: 100,
    },
    {
      title: '连续在60名外',
      dataIndex: 'days_below_60',
      key: 'days_below_60',
      width: 100,
      render: (v: number) => v > 0 ? <Text type="danger">{v}天</Text> : '-',
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Card>
        <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
          <Col>
            <Title level={4} style={{ margin: 0 }}>
              <StarOutlined style={{ marginRight: 8 }} />
              松岗七维打分排名 V3.0
            </Title>
          </Col>
          <Col>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
                刷新
              </Button>
              <Button icon={<AlertOutlined />} onClick={() => setVetoedVisible(true)}>
                一票否决 ({data?.vetoed_count || 0})
              </Button>
              <Button icon={<InfoCircleOutlined />} onClick={() => setBufferVisible(true)}>
                缓冲带状态
              </Button>
            </Space>
          </Col>
        </Row>

        {/* 参数设置 */}
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={24}>
            <Col span={6}>
              <Text>返回前N名</Text>
              <Slider
                min={10}
                max={100}
                value={topN}
                onChange={setTopN}
                marks={{ 10: '10', 60: '60', 100: '100' }}
              />
            </Col>
            <Col span={6}>
              <Text>AUM规模</Text>
              <Select
                style={{ width: '100%' }}
                value={aumLevel}
                onChange={setAumLevel}
                options={[
                  { value: 'small', label: '<1亿' },
                  { value: 'medium', label: '1-5亿' },
                  { value: 'large', label: '5-10亿' },
                ]}
              />
            </Col>
            <Col span={6}>
              <Text>市场环境</Text>
              <Select
                style={{ width: '100%' }}
                value={marketEnv}
                onChange={setMarketEnv}
                options={[
                  { value: 'bull', label: '牛市（动量权重高）' },
                  { value: 'neutral', label: '震荡市（均衡权重）' },
                  { value: 'bear', label: '熊市（防御权重高）' },
                ]}
              />
            </Col>
            <Col span={6}>
              <Space direction="vertical" size="small">
                <Text>当前市场: {getMarketEnvTag(data?.market_env || marketEnv)}</Text>
                <Text>AUM等级: {getAumLevelTag(data?.aum_level || aumLevel)}</Text>
              </Space>
            </Col>
          </Row>
        </Card>

        {/* 统计信息 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Statistic title="通过筛选" value={data?.total || 0} suffix="只" />
          </Col>
          <Col span={4}>
            <Statistic title="返回数量" value={data?.returned || 0} suffix="只" />
          </Col>
          <Col span={4}>
            <Statistic title="一票否决" value={data?.vetoed_count || 0} suffix="只" valueStyle={{ color: '#ff4d4f' }} />
          </Col>
          <Col span={4}>
            <Statistic
              title="缓冲带内"
              value={data?.buffer_status?.filter(b => b.in_buffer).length || 0}
              suffix="只"
              valueStyle={{ color: '#faad14' }}
            />
          </Col>
          <Col span={8}>
            <Alert
              message="七维评分：正股55分 + 转债45分 = 满分100分"
              description="包含一票否决制、缓冲带机制、动态权重调整"
              type="info"
              showIcon
            />
          </Col>
        </Row>

        {/* 排名表格 */}
        <Spin spinning={loading}>
          {data?.items?.length ? (
            <Table
              dataSource={data.items}
              columns={columns}
              rowKey="code"
              size="small"
              pagination={{ pageSize: 20, showSizeChanger: true, showQuickJumper: true }}
              scroll={{ x: 1000 }}
            />
          ) : (
            <Empty description="暂无数据" />
          )}
        </Spin>
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title={<span><StarOutlined /> {selectedCode} 七维详细评分</span>}
        open={detailVisible}
        onCancel={() => { setDetailVisible(false); setSelectedDetail(null) }}
        footer={null}
        width={800}
      >
        <Spin spinning={detailLoading}>
          {selectedDetail && (
            <>
              <Alert
                message={selectedDetail.veto_check.passed ? '通过一票否决检查' : '触发一票否决'}
                description={selectedDetail.veto_check.reasons.length > 0 ? selectedDetail.veto_check.reasons.join('；') : '该转债通过所有一票否决检查'}
                type={selectedDetail.veto_check.passed ? 'success' : 'error'}
                showIcon
                style={{ marginBottom: 16 }}
              />

              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Statistic title="综合评分" value={selectedDetail.total_score} suffix="/ 100" />
                </Col>
                <Col span={8}>
                  <Statistic title="正股评分" value={selectedDetail.stock_score} suffix="/ 55" />
                </Col>
                <Col span={8}>
                  <Statistic title="转债评分" value={selectedDetail.bond_score} suffix="/ 45" />
                </Col>
              </Row>

              <Divider>正股七维评分（满分55分）</Divider>
              <Row gutter={[16, 16]}>
                {Object.entries(selectedDetail.stock_details).map(([key, value]) => (
                  <Col span={6} key={key}>
                    <Card size="small">
                      <Statistic
                        title={STOCK_DIMENSION_NAMES[key] || key}
                        value={value}
                        suffix={`/ ${(selectedDetail.weights.stock_weights[key] * 55).toFixed(1)}`}
                        valueStyle={{ color: scoreColor(value, selectedDetail.weights.stock_weights[key] * 55) }}
                      />
                    </Card>
                  </Col>
                ))}
              </Row>

              <Divider>转债自身评分（满分45分）</Divider>
              <Row gutter={[16, 16]}>
                {Object.entries(selectedDetail.bond_details).map(([key, value]) => (
                  <Col span={6} key={key}>
                    <Card size="small">
                      <Statistic
                        title={BOND_DIMENSION_NAMES[key] || key}
                        value={value}
                        suffix={`/ ${(selectedDetail.weights.bond_weights[key] * 45).toFixed(1)}`}
                        valueStyle={{ color: scoreColor(value, selectedDetail.weights.bond_weights[key] * 45) }}
                      />
                    </Card>
                  </Col>
                ))}
              </Row>

              <Divider>基本信息</Divider>
              <Descriptions bordered size="small" column={4}>
                <Descriptions.Item label="价格">{selectedDetail.price.toFixed(2)}</Descriptions.Item>
                <Descriptions.Item label="溢价率">{selectedDetail.premium_ratio.toFixed(2)}%</Descriptions.Item>
                <Descriptions.Item label="双低值">{selectedDetail.dual_low.toFixed(2)}</Descriptions.Item>
                <Descriptions.Item label="剩余年限">{selectedDetail.remaining_years?.toFixed(2) || '-'}年</Descriptions.Item>
                <Descriptions.Item label="成交额">{(selectedDetail.volume || 0).toFixed(2)}亿</Descriptions.Item>
                <Descriptions.Item label="YTM">{selectedDetail.ytm?.toFixed(2) || '-'}%</Descriptions.Item>
                <Descriptions.Item label="信用评分">{selectedDetail.veto_check.credit_score.toFixed(1)}</Descriptions.Item>
              </Descriptions>
            </>
          )}
        </Spin>
      </Modal>

      {/* 一票否决弹窗 */}
      <Modal
        title={<span><CloseCircleOutlined /> 一票否决列表</span>}
        open={vetoedVisible}
        onCancel={() => setVetoedVisible(false)}
        footer={null}
        width={900}
      >
        <Alert
          message="一票否决制"
          description="满足任意一条直接排除：信用评分<60、溢价率>100%、剩余期限<6个月、强赎公告、流动性不足"
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Table
          dataSource={data?.vetoed || []}
          columns={vetoedColumns}
          rowKey="code"
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Modal>

      {/* 缓冲带状态弹窗 */}
      <Modal
        title={<span><InfoCircleOutlined /> 缓冲带状态</span>}
        open={bufferVisible}
        onCancel={() => setBufferVisible(false)}
        footer={null}
        width={900}
      >
        <Alert
          message="缓冲带机制"
          description="排名55-65名享有3日观察期。连续3日在60名外必须卖出，减少约40%的边缘换手。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Table
          dataSource={data?.buffer_status || []}
          columns={bufferColumns}
          rowKey="code"
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Modal>
    </div>
  )
}
