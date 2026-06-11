import React, { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Progress, Statistic, Table, Tag, Switch, Space, Button, Alert, Collapse } from 'antd';
import {
  RiseOutlined,
  FallOutlined,
  DashboardOutlined,
  ThunderboltOutlined,
  WarningOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  PieChartOutlined,
  FundOutlined,
  DollarOutlined,
  BankOutlined,
  LineChartOutlined,
  SmileOutlined,
  BellOutlined,
  GlobalOutlined,
} from '@ant-design/icons';
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../utils/echarts'
import { fetchEnhancedTimingSignal, fetchTimingSignal, TimingSignal, TimingFactor } from '../services/api';

interface TimingSignalProps {
  enhanced?: boolean
}

const TimingSignalPage: React.FC<TimingSignalProps> = ({ enhanced = true }) => {
  const [signal, setSignal] = useState<TimingSignal | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const getMockSignal = (): TimingSignal => ({
    totalScore: 62,
    positionLimit: 0.55,
    marketEnv: 'neutral',
    modelVersion: 'v4.0-enhanced',
    quality: 'good',
    confidence: 0.72,
    consensusScore: 65,
    hedgeRecommended: false,
    riskAlerts: [],
    crossValidation: { bullishCount: 3, bearishCount: 1, totalCount: 6 },
    factors: [
      { name: '估值面', score: 65, maxScore: 100, weight: 0.14, status: 'good', description: '转股溢价率中位数合理偏低', icon: 'valuation', subFactors: [{ name: '转股溢价率中位数', score: 70, weight: 0.35, signal: 'bullish', description: '溢价率中位数25%' }, { name: '纯债YTM中位数', score: 60, weight: 0.20, signal: 'neutral', description: 'YTM 1.5%' }, { name: '转债价格中位数', score: 55, weight: 0.15, signal: 'neutral', description: '中位数价位118元' }, { name: 'PE历史分位数', score: 65, weight: 0.15, signal: 'bullish', description: 'PE 45%分位' }, { name: 'PB历史分位数', score: 70, weight: 0.15, signal: 'bullish', description: 'PB 35%分位' }] },
      { name: '基本面', score: 58, maxScore: 100, weight: 0.10, status: 'warning', description: '经济增长平稳，企业盈利温和改善', icon: 'fundamental', subFactors: [{ name: '盈利超预期比例', score: 60, weight: 0.25, signal: 'bullish', description: '55%公司超预期' }, { name: 'GDP增速', score: 50, weight: 0.20, signal: 'neutral', description: 'GDP同比5.0%' }, { name: '工业增加值增速', score: 55, weight: 0.20, signal: 'neutral', description: '工业增加值同比5.2%' }, { name: 'PE/PB综合估值', score: 65, weight: 0.15, signal: 'bullish', description: 'PE/PB合理' }, { name: '股息吸引力', score: 55, weight: 0.10, signal: 'neutral', description: 'PE=18' }, { name: '社零增速', score: 52, weight: 0.10, signal: 'neutral', description: '社零同比4.8%' }] },
      { name: '筹码面', score: 52, maxScore: 100, weight: 0.08, status: 'warning', description: '机构持仓稳定，筹码结构均衡', icon: 'chip', subFactors: [{ name: '机构持仓变化', score: 50, weight: 0.30, signal: 'neutral', description: '机构持仓+0.3%' }, { name: '融资余额占比', score: 55, weight: 0.20, signal: 'neutral', description: '融资买入占比8.5%' }, { name: '转债破面比例', score: 50, weight: 0.25, signal: 'neutral', description: '低于面值占比4.2%' }, { name: '供给压力评估', score: 55, weight: 0.25, signal: 'neutral', description: 'PE分位45%供给适中' }] },
      { name: '资金面', score: 60, maxScore: 100, weight: 0.12, status: 'good', description: '转债成交活跃，主力小幅流入', icon: 'capital', subFactors: [{ name: '转债日均成交额', score: 65, weight: 0.20, signal: 'bullish', description: '日均成交550亿' }, { name: '主力资金净流入', score: 58, weight: 0.18, signal: 'neutral', description: '主力净流入+25亿' }, { name: '北向资金净流入', score: 55, weight: 0.18, signal: 'neutral', description: '北向资金+15亿' }, { name: '融资余额变化', score: 52, weight: 0.16, signal: 'neutral', description: '融资余额+8亿' }, { name: '全市场换手率', score: 60, weight: 0.14, signal: 'neutral', description: '换手率2.8%' }, { name: '行业资金流向', score: 55, weight: 0.14, signal: 'neutral', description: '多数行业均衡' }] },
      { name: '流动性面', score: 72, maxScore: 100, weight: 0.10, status: 'good', description: '流动性整体充裕', icon: 'liquidity', subFactors: [{ name: 'Shibor隔夜', score: 75, weight: 0.18, signal: 'bullish', description: 'Shibor隔夜1.1%' }, { name: '10年国债收益率', score: 70, weight: 0.18, signal: 'bullish', description: '10年国债2.3%' }, { name: '2年国债收益率', score: 65, weight: 0.12, signal: 'bullish', description: '2年国债1.9%' }, { name: '期限利差', score: 60, weight: 0.15, signal: 'neutral', description: '利差100bp' }, { name: '信用利差', score: 55, weight: 0.15, signal: 'neutral', description: '信用利差95bp' }, { name: 'M2增速', score: 80, weight: 0.12, signal: 'bullish', description: 'M2同比11.5%' }, { name: '社融增速', score: 75, weight: 0.10, signal: 'bullish', description: '社融同比12%' }] },
      { name: '技术面', score: 48, maxScore: 100, weight: 0.16, status: 'warning', description: '指数横盘整理，MACD中性', icon: 'technical', subFactors: [{ name: '均线排列', score: 45, weight: 0.20, signal: 'neutral', description: '均线交叉排列' }, { name: 'MACD信号', score: 50, weight: 0.18, signal: 'neutral', description: 'MACD中性' }, { name: 'RSI(14)', score: 48, weight: 0.15, signal: 'neutral', description: 'RSI=48' }, { name: '布林带位置', score: 50, weight: 0.12, signal: 'neutral', description: '布林带中轨' }, { name: '量价关系', score: 52, weight: 0.15, signal: 'neutral', description: '量比1.0' }, { name: '指数均线关系', score: 45, weight: 0.10, signal: 'neutral', description: '指数vs均线' }, { name: '转债指数均线', score: 50, weight: 0.10, signal: 'neutral', description: '转债指数中性' }] },
      { name: '情绪面', score: 55, maxScore: 100, weight: 0.10, status: 'warning', description: '市场情绪中性，局部活跃', icon: 'sentiment', subFactors: [{ name: '涨跌比', score: 60, weight: 0.20, signal: 'neutral', description: '涨跌比1.2' }, { name: '涨停/跌停比', score: 55, weight: 0.18, signal: 'neutral', description: '涨停50/跌停15' }, { name: '新高/新低比', score: 58, weight: 0.15, signal: 'neutral', description: '新高80/新低25' }, { name: '认沽/认购比', score: 55, weight: 0.15, signal: 'neutral', description: 'PCR=0.95' }, { name: '波动率指数', score: 60, weight: 0.12, signal: 'neutral', description: 'VIX=22' }, { name: '融资买入占比', score: 50, weight: 0.10, signal: 'neutral', description: '融资占比8.5%' }, { name: '市场换手率', score: 52, weight: 0.10, signal: 'neutral', description: '换手率2.5%' }] },
      { name: '消息面', score: 55, maxScore: 100, weight: 0.07, status: 'warning', description: '政策信号中性，产业链平稳', icon: 'news', subFactors: [{ name: '政策信号', score: 55, weight: 0.40, signal: 'neutral', description: '政策中性' }, { name: '事件冲击', score: 50, weight: 0.30, signal: 'neutral', description: '无重大事件' }, { name: '产业链景气', score: 58, weight: 0.30, signal: 'neutral', description: '景气度平稳' }] },
      { name: '宏观面', score: 52, maxScore: 100, weight: 0.15, status: 'warning', description: 'PMI在荣枯线附近，经济复苏待确认', icon: 'macro', subFactors: [{ name: 'PMI', score: 50, weight: 0.25, signal: 'neutral', description: 'PMI=50.5/50.2' }, { name: 'CPI-PPI剪刀差', score: 55, weight: 0.15, signal: 'neutral', description: 'CPI 2.0/PPI 0.5' }, { name: '出口增速', score: 50, weight: 0.15, signal: 'neutral', description: '出口同比5.8%' }, { name: 'GDP增速', score: 50, weight: 0.20, signal: 'neutral', description: 'GDP 5.0%' }, { name: '工业增加值', score: 52, weight: 0.15, signal: 'neutral', description: '工业增加值5.2%' }, { name: '社零增速', score: 55, weight: 0.10, signal: 'neutral', description: '社零4.8%' }] },
    ],
    recommendation: '多维度信号偏中性，建议仓位55%，均衡配置低估值+高评级品种',
    timestamp: new Date().toISOString(),
  });

  const getScoreColor = (score: number) => {
    if (score >= 70) return '#52c41a';
    if (score >= 50) return '#1890ff';
    if (score >= 30) return '#faad14';
    return '#ff4d4f';
  };

  const getCategoryColor = (category: string) => {
    const colors: Record<string, string> = {
      valuation: '#722ed1', fundamental: '#13c2c2', chip: '#2f54eb',
      capital: '#fa8c16', liquidity: '#52c41a', technical: '#eb2f96',
      sentiment: '#f5222d', news: '#faad14', macro: '#1890ff',
    };
    return colors[category] || '#1890ff';
  };

  const getCategoryIcon = (icon?: string) => {
    const icons: Record<string, React.ReactNode> = {
      valuation: <PieChartOutlined />, fundamental: <FundOutlined />,
      chip: <DollarOutlined />, capital: <BankOutlined />,
      liquidity: <CheckCircleOutlined />, technical: <LineChartOutlined />,
      sentiment: <SmileOutlined />, news: <BellOutlined />,
      macro: <GlobalOutlined />,
    };
    return icons[icon || ''] || <DashboardOutlined />;
  };

  const loadSignal = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = enhanced
        ? await fetchEnhancedTimingSignal()
        : (await fetchTimingSignal() as TimingSignal);
      if (data && data.factors && data.factors.length > 0) {
        setSignal(data);
        setLoadError(null);
      } else {
        setLoadError('API返回数据为空，显示示例数据');
        if (!signal) {
          setSignal(getMockSignal());
        }
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : '网络请求失败';
      setLoadError(`数据加载失败: ${msg}，显示缓存数据`);
      if (!signal) {
        setSignal(getMockSignal());
      }
    } finally {
      setLoading(false);
    }
  }, [enhanced]);

  useEffect(() => {
    loadSignal();
  }, [loadSignal]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(loadSignal, 60000);
    return () => clearInterval(timer);
  }, [autoRefresh, loadSignal]);

  const getEnvTag = (env: string) => {
    const config: Record<string, { color: string; icon: React.ReactNode; text: string }> = {
      bull: { color: 'green', icon: <RiseOutlined />, text: '牛市' },
      bear: { color: 'red', icon: <FallOutlined />, text: '熊市' },
      neutral: { color: 'blue', icon: <DashboardOutlined />, text: '震荡' },
    };
    const c = config[env] || { color: 'default', icon: null, text: env };
    return <Tag color={c.color} icon={c.icon} style={{ fontSize: 14, padding: '4px 12px' }}>{c.text}</Tag>;
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

  const getSignalTag = (signal: string) => {
    const config: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
      bullish: { color: 'green', text: '看多', icon: <RiseOutlined /> },
      bearish: { color: 'red', text: '看空', icon: <FallOutlined /> },
      neutral: { color: 'blue', text: '中性', icon: <DashboardOutlined /> },
    };
    const c = config[signal] || config.neutral;
    return <Tag color={c.color} icon={c.icon}>{c.text}</Tag>;
  };

  const getQualityTag = (quality?: string) => {
    const config: Record<string, { color: string; text: string }> = {
      excellent: { color: 'purple', text: '极高置信度' },
      good: { color: 'green', text: '高置信度' },
      fair: { color: 'blue', text: '中等置信度' },
      weak: { color: 'orange', text: '低置信度' },
      unreliable: { color: 'red', text: '不可靠' },
    };
    const c = config[quality || 'fair'] || config.fair;
    return <Tag color={c.color}>{c.text}</Tag>;
  };

  const factors = signal?.factors || [];
  const isEnhanced = signal?.modelVersion === 'v4.0-enhanced' || (signal?.factors?.length ?? 0) > 4;

  // 仪表盘图表配置
  const gaugeOption = {
    series: [{
      type: 'gauge',
      startAngle: 180, endAngle: 0,
      min: 0, max: 100, splitNumber: 10,
      radius: '100%', center: ['50%', '70%'],
      axisLine: {
        lineStyle: {
          width: 20,
          color: [[0.3, '#ff4d4f'], [0.5, '#faad14'], [0.7, '#1890ff'], [1, '#52c41a']],
        },
      },
      pointer: {
        icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
        length: '60%', width: 10, offsetCenter: [0, '-10%'],
        itemStyle: { color: 'auto' },
      },
      axisTick: { length: 8, lineStyle: { color: 'auto', width: 2 } },
      splitLine: { length: 15, lineStyle: { color: 'auto', width: 3 } },
      axisLabel: { color: '#666', fontSize: 12, distance: -50 },
      title: { offsetCenter: [0, '30%'], fontSize: 16 },
      detail: {
        valueAnimation: true,
        formatter: '{value}分',
        fontSize: 32, offsetCenter: [0, '0%'],
      },
      data: [{ value: signal?.totalScore || 0, name: '择时评分' }],
    }],
  };

  // 雷达图配置
  const radarOption = {
    tooltip: {},
    legend: { data: ['当前得分'], bottom: 0 },
    radar: {
      indicator: factors.map(f => ({
        name: f.name,
        max: f.maxScore,
      })),
      center: ['50%', '55%'],
      radius: '65%',
      axisName: { color: '#333', fontSize: 11 },
      splitArea: { areaStyle: { color: ['rgba(24, 144, 255, 0.05)', 'rgba(24, 144, 255, 0.1)'] } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: factors.map(f => f.score),
        name: '当前得分',
        areaStyle: { color: 'rgba(24, 144, 255, 0.25)' },
        lineStyle: { color: '#1890ff', width: 2 },
        itemStyle: { color: '#1890ff' },
      }],
    }],
  };

  const positionPercent = (signal?.positionLimit || 0) * 100;

  return (
    <div style={{ padding: 24 }}>
      {/* 数据加载错误提示 */}
      {loadError && (
        <Alert
          message={loadError}
          type="warning"
          showIcon
          closable
          style={{ marginBottom: 12 }}
          onClose={() => setLoadError(null)}
        />
      )}
      {/* 头部 */}
      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <ThunderboltOutlined style={{ fontSize: 24, color: '#1890ff' }} />
              <span style={{ fontSize: 20, fontWeight: 'bold' }}>
                {isEnhanced ? '多维度综合择时信号' : '多因子择时信号 (V3)'}
              </span>
              {signal && getEnvTag(signal.marketEnv)}
              {isEnhanced && signal && getQualityTag(signal.quality)}
              {isEnhanced && (
                <Tag color="purple" style={{ fontSize: 12 }}>V4.0</Tag>
              )}
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
        <Col span={5}>
          <Card>
            <Statistic
              title="择时评分"
              value={signal?.totalScore || 0}
              suffix="/ 100分"
              valueStyle={{ color: getScoreColor(signal?.totalScore || 0) }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="建议仓位"
              value={positionPercent}
              suffix="%"
              precision={0}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="市场环境"
      value={
        signal?.marketEnv === 'bull' || signal?.marketEnv === 'strong_bull' ? '牛市' :
        signal?.marketEnv === 'bear' || signal?.marketEnv === 'strong_bear' ? '熊市' :
        signal?.marketEnv === 'neutral' ? '震荡市' : '未知'
      }
              valueStyle={{
                color: signal?.marketEnv === 'bull' ? '#52c41a' :
                       signal?.marketEnv === 'bear' ? '#ff4d4f' : '#1890ff',
              }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="信号置信度"
              value={signal?.confidence ? (signal.confidence * 100).toFixed(0) : '--'}
              suffix="%"
              valueStyle={{ color: (signal?.confidence || 0) > 0.6 ? '#52c41a' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="更新时间"
              value={signal?.timestamp ? new Date(signal.timestamp).toLocaleTimeString() : '--'}
              valueStyle={{ fontSize: 14 }}
            />
          </Card>
        </Col>
      </Row>

      {/* 风险预警 */}
      {signal?.riskAlerts && signal.riskAlerts.length > 0 && (
        <Card style={{ marginBottom: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {signal.riskAlerts.map((alert, idx) => (
              <Alert
                key={idx}
                message={alert}
                type={
                  alert.includes('极度低估') || alert.includes('历史性') ? 'success' :
                  alert.includes('对冲') ? 'error' :
                  'warning'
                }
                icon={
                  alert.includes('极度低估') || alert.includes('历史性') ?
                    <CheckCircleOutlined /> :
                    <ExclamationCircleOutlined />
                }
                showIcon
              />
            ))}
          </Space>
        </Card>
      )}

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
              '20%': '#fa8c16',
              '40%': '#faad14',
              '60%': '#1890ff',
              '80%': '#52c41a',
              '100%': '#237804',
            }}
            strokeWidth={20}
          />
          <div style={{ marginTop: 16, fontSize: 16, color: '#666', display: 'flex', alignItems: 'center', gap: 8 }}>
            <WarningOutlined style={{ color: '#faad14' }} />
            {signal?.recommendation || '暂无建议'}
            {signal?.hedgeRecommended && (
              <Tag color="error">建议对冲</Tag>
            )}
          </div>
        </div>
      </Card>

      {/* 交叉验证摘要 */}
      {isEnhanced && signal?.crossValidation && (
        <Card title="交叉验证摘要" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="看多验证"
                value={signal.crossValidation.bullishCount}
                suffix={`/ ${signal.crossValidation.totalCount}`}
                valueStyle={{ color: '#52c41a' }}
                prefix={<RiseOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="看空验证"
                value={signal.crossValidation.bearishCount}
                suffix={`/ ${signal.crossValidation.totalCount}`}
                valueStyle={{ color: '#ff4d4f' }}
                prefix={<FallOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="一致性评分"
                value={signal.consensusScore || 0}
                suffix="/ 100"
                valueStyle={{ color: getScoreColor(signal.consensusScore || 50) }}
                prefix={<DashboardOutlined />}
              />
            </Col>
          </Row>
        </Card>
      )}

      {/* 因子详情 - 使用折叠面板展开子因子 */}
      <Card title="因子详情" bodyStyle={{ padding: 0 }}>
        <Collapse
          defaultActiveKey={isEnhanced ? ['valuation'] : undefined}
          expandIconPosition="end"
          style={{ border: 'none' }}
        >
          {factors.map((factor: TimingFactor, idx: number) => {
            const icon = factor.icon || '';
            const catColor = getCategoryColor(icon);
            const hasSub = factor.subFactors && factor.subFactors.length > 0;

            return (
              <Collapse.Panel
                key={icon || `factor-${idx}`}
                header={
                  <Row align="middle" style={{ width: '100%' }}>
                    <Col span={4}>
                      <Space>
                        <span style={{ color: catColor, fontSize: 16 }}>{getCategoryIcon(icon)}</span>
                        <span style={{ fontWeight: 600, fontSize: 14 }}>{factor.name}</span>
                      </Space>
                    </Col>
                    <Col span={5}>
                      <Tag color="blue">{((factor.weight ?? 0) * 100).toFixed(0)}%权重</Tag>
                    </Col>
                    <Col span={8}>
                      <Progress
                        percent={(factor.score / (factor.maxScore || 1)) * 100}
                        format={() => `${factor.score}/${factor.maxScore}`}
                        strokeColor={getScoreColor((factor.score / (factor.maxScore || 1)) * 100)}
                        size="small"
                        style={{ marginBottom: 0 }}
                      />
                    </Col>
                    <Col span={4}>
                      {getStatusTag(factor.status)}
                    </Col>
                    <Col span={3}>
                      {hasSub && (
                        <Tag style={{ fontSize: 11 }}>{factor.subFactors!.length}个子因子</Tag>
                      )}
                    </Col>
                  </Row>
                }
              >
                <div style={{ padding: '0 16px' }}>
                  <p style={{ color: '#666', marginBottom: 12 }}>{factor.description}</p>
                  {hasSub && (
                    <Table
                      dataSource={factor.subFactors!.map((sf, i) => ({ ...sf, key: i }))}
                      columns={[
                        { title: '子因子', dataIndex: 'name', key: 'name', width: 160 },
                        {
                          title: '得分',
                          key: 'score',
                          width: 180,
                          render: (_: any, r: any) => (
                            <Progress
                              percent={r.score}
                              format={() => `${r.score}分`}
                              strokeColor={getScoreColor(r.score)}
                              size="small"
                              style={{ marginBottom: 0 }}
                            />
                          ),
                        },
                        { title: '权重', key: 'weight', width: 80, render: (_: any, r: any) => `${(r.weight * 100).toFixed(0)}%` },
                        {
                          title: '方向',
                          dataIndex: 'signal',
                          key: 'signal',
                          width: 90,
                          render: (s: string) => getSignalTag(s),
                        },
                        { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
                      ]}
                      pagination={false}
                      size="small"
                    />
                  )}
                </div>
              </Collapse.Panel>
            );
          })}
        </Collapse>
      </Card>
    </div>
  );
};

export default TimingSignalPage;
