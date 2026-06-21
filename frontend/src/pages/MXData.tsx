/**
 * 妙想MX金融数据 — 东方财富官方API数据查询
 */
import { useState } from 'react'
import {
  Card, Input, Button, Table, Tag, message, Typography, Spin,
  Tabs, Alert, Space, Descriptions, Empty, Divider,
} from 'antd'
import {
  ApiOutlined, SearchOutlined, FileTextOutlined,
  LineChartOutlined, CheckCircleOutlined, CloseCircleOutlined,
  DatabaseOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { queryMXData, getMXStatus } from '../services/api'

const { Title, Text } = Typography
const { TextArea } = Input

export default function MXData() {
  const [query, setQuery] = useState('')
  const [queryType, setQueryType] = useState<'financial' | 'news'>('financial')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<any>(null)

  const tabs = [
    { key: 'query', label: <span><SearchOutlined /> 数据查询</span> },
    { key: 'status', label: <span><ApiOutlined /> 连接状态</span> },
    { key: 'help', label: <span><FileTextOutlined /> 使用说明</span> },
  ]

  const doQuery = async () => {
    if (!query.trim()) {
      message.warning('请输入查询内容')
      return
    }
    setLoading(true); setError(null); setResult(null)
    try {
      const res = await queryMXData({ query: query.trim(), data_type: queryType })
      if (res.success) {
        setResult(res)
        message.success(`查询成功: ${res.total_rows} 条结果`)
      } else {
        setError(res.message || '查询失败')
      }
    } catch (e: any) {
      setError(e?.message || '网络错误')
    } finally { setLoading(false) }
  }

  const checkStatus = async () => {
    try {
      const s = await getMXStatus()
      setStatus(s)
    } catch (e: any) {
      message.error(e?.message || '无法获取状态')
    }
  }

  const queryExamples = [
    '上证指数最新价',
    '贵州茅台近三年净利润 营业收入',
    '宁德时代主力资金流向',
    '半导体板块最新行情',
    '东方财富最新公告',
    '美联储加息对A股影响分析',
  ]

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}><ThunderboltOutlined /> 妙想MX金融数据</Title>
      <Text type="secondary">基于东方财富官方API的金融数据查询，支持行情/财务/资讯</Text>

      <Divider />

      <Tabs defaultActiveKey="query" items={tabs.map(t => ({
        key: t.key,
        label: t.label,
        children: t.key === 'query' ? (
          <div>
            <Space style={{ marginBottom: 12 }}>
              <Button
                type={queryType === 'financial' ? 'primary' : 'default'}
                icon={<DatabaseOutlined />}
                onClick={() => setQueryType('financial')}
              >金融数据</Button>
              <Button
                type={queryType === 'news' ? 'primary' : 'default'}
                icon={<FileTextOutlined />}
                onClick={() => setQueryType('news')}
              >资讯搜索</Button>
            </Space>

            <TextArea
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="输入自然语言查询，如: 贵州茅台最新价"
              rows={3}
              style={{ marginBottom: 12 }}
            />

            <Space style={{ marginBottom: 16, flexWrap: 'wrap' }}>
              {queryExamples.map(q => (
                <Tag
                  key={q}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setQuery(q)}
                >{q}</Tag>
              ))}
            </Space>

            <Button
              type="primary"
              icon={<SearchOutlined />}
              onClick={doQuery}
              loading={loading}
            >查询</Button>

            <Divider />

            {error && <Alert type="error" message={error} closable style={{ marginBottom: 12 }} />}

            {loading && <Spin tip="查询中..." style={{ display: 'block', margin: '40px auto' }} />}

            {result && !loading && (
              <>
                <Alert
                  type="success"
                  message={`查询成功: ${result.total_rows} 条结果 (来自 ${result.source})`}
                  style={{ marginBottom: 12 }}
                />

                {result.data?.length > 0 && (
                  <Card size="small" title="查询结果">
                    <Table
                      dataSource={result.data.slice(0, 50).map((r: any, i: number) => ({ ...r, key: i }))}
                      columns={Object.keys(result.data[0] || {}).map(k => ({
                        title: k,
                        dataIndex: k,
                        key: k,
                        ellipsis: true,
                      }))}
                      size="small"
                      scroll={{ x: 'max-content', y: 400 }}
                      pagination={{ pageSize: 20 }}
                    />
                  </Card>
                )}

                {result.tables?.filter((t: any) => t.rows?.length > 0).map((table: any, idx: number) => (
                  <Card key={idx} size="small" title={table.sheet_name} style={{ marginTop: 12 }}>
                    <Table
                      dataSource={table.rows.slice(0, 100).map((r: any, i: number) => ({ ...r, key: i }))}
                      columns={(table.fieldnames || []).map((f: string) => ({
                        title: f, dataIndex: f, key: f, ellipsis: true,
                      }))}
                      size="small"
                      scroll={{ x: 'max-content', y: 400 }}
                      pagination={{ pageSize: 20 }}
                    />
                  </Card>
                ))}
              </>
            )}

            {!result && !loading && !error && (
              <Empty description="输入查询内容后点击「查询」" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>
        ) : t.key === 'status' ? (
          <div>
            <Button onClick={checkStatus} icon={<ApiOutlined />} style={{ marginBottom: 16 }}>
              检查连接状态
            </Button>
            {status && (
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="API Key 已配置">
                  {status.configured
                    ? <Tag icon={<CheckCircleOutlined />} color="success">已配置</Tag>
                    : <Tag icon={<CloseCircleOutlined />} color="error">未配置</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="API Key">{status.api_key_prefix || '-'}</Descriptions.Item>
                <Descriptions.Item label="mx-data skill">
                  {status.skills_installed?.['mx-data']
                    ? <Tag color="success">已安装</Tag> : <Tag color="error">未安装</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="mx-search skill">
                  {status.skills_installed?.['mx-search']
                    ? <Tag color="success">已安装</Tag> : <Tag color="error">未安装</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="mx-xuangu skill">
                  {status.skills_installed?.['mx-xuangu']
                    ? <Tag color="success">已安装</Tag> : <Tag color="error">未安装</Tag>}
                </Descriptions.Item>
              </Descriptions>
            )}
          </div>
        ) : (
          <div>
            <Title level={5}>使用说明</Title>
            <ul>
              <li><b>金融数据</b> — 查询行情、财务、股东等数据</li>
              <li><b>资讯搜索</b> — 搜索新闻、公告、研报、政策</li>
              <li>支持自然语言查询，如"贵州茅台最新价 涨跌幅"</li>
              <li>数据来源: 东方财富(MX API) — 同花顺/新浪/AKShare备选</li>
            </ul>
            <Title level={5} style={{ marginTop: 16 }}>数据源优先级</Title>
            <pre style={{ fontSize: 12 }}>
              MX API (东方财富官方) → AKShare → DuckDB缓存 →  
              THS转债列表 → Sina实时 → Jisilu → Baidu → 腾讯K线 →  
              BaoStock → Yahoo Finance → HTTP 503(不用假数据)
            </pre>
          </div>
        )
      }))} />
    </div>
  )
}
