import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Progress, Statistic, Table, Tag, Switch, Space, Button } from 'antd';
import {
  RiseOutlined,
  FallOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  WarningOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../utils/echarts'
import { fetchTimingSignal } from '../services/api';

interface TimingFactor {
  name: string;
  score: number;
  maxScore: number;
  weight: number;
  status: 'good' | 'warning' | 'danger';
  description: string;
}

interface TimingSignal {
  totalScore: number;
  positionLimit: number;
  marketEnv: 'bull' | 'bear' | 'neutral';
  factors: TimingFactor[];
  recommendation: string;
  timestamp: string;
}

const TimingSignal: React.FC = () => {
  const [signal, setSignal] = useState<TimingSignal | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    loadSignal();
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(loadSignal, 60000); // 每分钟刷新
    return () => clearInterval(timer);
  }, [autoRefresh]);

  const loadSignal = async () => {
    setLoading(true);
    try {
      const data = await fetchTimingSignal();
      setSignal(data);
    } catch (error) {
      // 使用模拟数据
      setSignal({
        totalScore: 62,
        positionLimit: 0.55,
        marketEnv: 'neutral',
        factors: [
          { name: '估值因子', score: 32, maxScore: 40, weight: 0.4, status: 'good', description: '转债溢价率中位数处于合理区间' },
          { name: '情绪因子', score: 18, maxScore: 25, weight: 0.25, status: 'warning', description: '市场成交量有所回升' },
          { name: '流动性因子', score: 15, maxScore: 20, weight: 0.2, status: 'good', description: '资金面相对宽松' },
          { name: '宏观因子', score: 10, maxScore: 15, weight: 0.15, status: 'warning', description: 'PMI处于荣枯线附近' },
        ],
        recommendation: '建议仓位55%，关注低估值品种',
        timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 70) return '#52c41a';
    if (score >= 50) return '#1890ff';
    if (score >= 30) return '#faad14';
    return '#ff4d4f';
  };

  const getEnvTag = (env: string) => {
    const config: Record<string, { color: string; icon: React.ReactNode; text: string }> = {
      bull: { color: 'green', icon: <RiseOutlined />, text: '牛市' },
      bear: { color: 'red', icon: <FallOutlined />, text: '熊市' },
      neutral: { color: 'blue', icon: <DashboardOutlined />, text: '震荡' },
    };
    const c = config[env] || config.neutral;
    return (
      <Tag color={c.color} icon={c.icon} style={{ fontSize: 14, padding: '4px 12px' }}>
        {c.text}
      </Tag>
    );
  };

  const getStatusTag = (status: string) => {
    const config: Record<string, { color: string; text: string }> = {
      good: { color: 'success', text: '良好' },
      warning: { color: 'warning', text: '警示' },
      danger: { color: 'error', text: '危险' },
    };
    const c = config[status] || config.warning;
    return <Tag color={c.color}>{c.text}</Tag>;
  };

  // 仪表盘图表配置
  const gaugeOption = {
    series: [
      {
        type: 'gauge',
        startAngle: 180,
        endAngle: 0,
        min: 0,
        max: 100,
        splitNumber: 10,
        radius: '100%',
        center: ['50%', '70%'],
        axisLine: {
          lineStyle: {
            width: 20,
            color: [
              [0.3, '#ff4d4f'],
              [0.5, '#faad14'],
              [0.7, '#1890ff'],
              [1, '#52c41a'],
            ],
          },
        },
        pointer: {
          icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
          length: '60%',
          width: 10,
          offsetCenter: [0, '-10%'],
          itemStyle: { color: 'auto' },
        },
        axisTick: { length: 8, lineStyle: { color: 'auto', width: 2 } },
        splitLine: { length: 15, lineStyle: { color: 'auto', width: 3 } },
        axisLabel: { color: '#666', fontSize: 12, distance: -50 },
        title: { offsetCenter: [0, '30%'], fontSize: 16 },
        detail: {
          valueAnimation: true,
          formatter: '{value}分',
          fontSize: 32,
          offsetCenter: [0, '0%'],
        },
        data: [{ value: signal?.totalScore || 0, name: '择时评分' }],
      },
    ],
  };

  // 因子雷达图配置
  const radarOption = {
    radar: {
      indicator: signal?.factors.map(f => ({
        name: f.name,
        max: f.maxScore,
      })) || [],
      axisName: { color: '#333', fontSize: 12 },
      splitArea: { areaStyle: { color: ['rgba(24, 144, 255, 0.1)', 'rgba(24, 144, 255, 0.05)'] } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: signal?.factors.map(f => f.score) || [],
            name: '当前得分',
            areaStyle: { color: 'rgba(24, 144, 255, 0.3)' },
            lineStyle: { color: '#1890ff', width: 2 },
            itemStyle: { color: '#1890ff' },
          },
        ],
      },
    ],
  };

  // 仓位建议条
  const positionPercent = (signal?.positionLimit || 0) * 100;

  const factorColumns = [
    {
      title: '因子名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: TimingFactor) => (
        <Space>
          <span style={{ fontWeight: 500 }}>{text}</span>
          <Tag color="blue">{(record.weight * 100).toFixed(0)}%权重</Tag>
        </Space>
      ),
    },
    {
      title: '得分',
      key: 'score',
      render: (_: any, record: TimingFactor) => (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Progress
            percent={(record.score / record.maxScore) * 100}
            format={() => `${record.score}/${record.maxScore}`}
            strokeColor={getScoreColor((record.score / record.maxScore) * 100)}
            size="small"
          />
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => getStatusTag(status),
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 头部操作栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <ThunderboltOutlined style={{ fontSize: 24, color: '#1890ff' }} />
              <span style={{ fontSize: 20, fontWeight: 'bold' }}>四因子择时信号</span>
              {signal && getEnvTag(signal.marketEnv)}
            </Space>
          </Col>
          <Col>
            <Space>
              <span>自动刷新</span>
              <Switch checked={autoRefresh} onChange={setAutoRefresh} />
              <Button icon={<SyncOutlined spin={loading} />} onClick={loadSignal}>
                刷新
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 核心指标 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="择时评分"
              value={signal?.totalScore || 0}
              suffix="/ 100分"
              valueStyle={{ color: getScoreColor(signal?.totalScore || 0) }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="建议仓位"
              value={positionPercent}
              suffix="%"
              precision={1}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="市场环境"
              value={
                signal?.marketEnv === 'bull' ? '牛市' :
                signal?.marketEnv === 'bear' ? '熊市' : '震荡市'
              }
              valueStyle={{
                color: signal?.marketEnv === 'bull' ? '#52c41a' :
                       signal?.marketEnv === 'bear' ? '#ff4d4f' : '#1890ff',
              }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="更新时间"
              value={signal?.timestamp ? new Date(signal.timestamp).toLocaleTimeString() : '--'}
              valueStyle={{ fontSize: 16 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title="择时评分仪表">
            <ReactEChartsCore echarts={echarts} option={gaugeOption} style={{ height: 300 }} />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="因子得分雷达">
            <ReactEChartsCore echarts={echarts} option={radarOption} style={{ height: 300 }} />
          </Card>
        </Col>
      </Row>

      {/* 仓位建议条 */}
      <Card title="仓位建议" style={{ marginBottom: 16 }}>
        <div style={{ padding: '20px 0' }}>
          <Progress
            percent={positionPercent}
            strokeColor={{
              '0%': '#ff4d4f',
              '30%': '#faad14',
              '70%': '#1890ff',
              '100%': '#52c41a',
            }}
            strokeWidth={20}
          />
          <div style={{ marginTop: 16, fontSize: 16, color: '#666' }}>
            <WarningOutlined style={{ marginRight: 8, color: '#faad14' }} />
            {signal?.recommendation || '暂无建议'}
          </div>
        </div>
      </Card>

      {/* 因子详情表 */}
      <Card title="因子详情">
        <Table
          columns={factorColumns}
          dataSource={signal?.factors || []}
          rowKey="name"
          pagination={false}
          loading={loading}
        />
      </Card>
    </div>
  );
};

export default TimingSignal;
