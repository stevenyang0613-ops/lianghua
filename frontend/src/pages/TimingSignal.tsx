import React, { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Progress, Statistic, Table, Tag, Switch, Space, Button, Alert, Collapse, Spin, Empty } from 'antd';
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
      } else if (data && data.marketEnv === 'unknown' && (data.totalScore === 0 || data.totalScore === null)) {
        // 缓存尚未准备好，后端正在后台刷新，前端显示加载中而非错误
        setSignal(null);
        setLoadError(null);
      } else {
        setLoadError('API返回数据为空，请检查数据源');
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : '网络请求失败';
      setLoadError(`数据加载失败: ${msg}`);
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
      missing: { color: 'default', text: '数据缺失' },
    };
    const c = config[status] || config.missing;
    return <Tag color={c.color}>{c.text}</Tag>;
  };

  const getSignalTag = (signal: string) => {
    const config: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
      bullish: { color: 'green', text: '看多', icon: <RiseOutlined /> },
      bearish: { color: 'red', text: '看空', icon: <FallOutlined /> },
      neutral: { color: 'blue', text: '中性', icon: <DashboardOutlined /> },
      missing: { color: 'default', text: '数据不足', icon: <ExclamationCircleOutlined /> },
    };
    const c = config[signal] || config.missing;
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
  const hasFactors = factors.length > 0;

  const displayTotalScore = signal?.totalScore != null ? signal.totalScore : null;
  const gaugeValue = displayTotalScore ?? 0;

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
      pointer: displayTotalScore != null ? {
        icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z',
        length: '60%', width: 10, offsetCenter: [0, '-10%'],
        itemStyle: { color: 'auto' },
      } : undefined,
      axisTick: { length: 8, lineStyle: { color: 'auto', width: 2 } },
      splitLine: { length: 15, lineStyle: { color: 'auto', width: 3 } },
      axisLabel: { color: '#666', fontSize: 12, distance: -50 },
      title: { offsetCenter: [0, '30%'], fontSize: 16 },
      detail: {
        valueAnimation: true,
        formatter: displayTotalScore != null ? '{value}分' : 'N/A',
        fontSize: 32, offsetCenter: [0, '0%'],
        color: displayTotalScore != null ? 'auto' : '#999',
      },
      data: [{ value: gaugeValue, name: '择时评分' }],
    }],
  };

  // 雷达图配置（无有效因子时隐藏，避免 ECharts 空数据崩溃）
  const radarOption = hasFactors ? {
    tooltip: {},
    legend: { data: ['当前得分'], bottom: 0 },
    radar: {
      indicator: factors.map(f => ({
        name: f.name,
        max: f.maxScore || 100,
      })),
      center: ['50%', '55%'],
      radius: '65%',
      axisName: { color: '#333', fontSize: 11 },
      splitArea: { areaStyle: { color: ['rgba(24, 144, 255, 0.05)', 'rgba(24, 144, 255, 0.1)'] } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: factors.map(f => f.score ?? 0),
	        name: '当前得分',
        areaStyle: { color: 'rgba(24, 144, 255, 0.25)' },
        lineStyle: { color: '#1890ff', width: 2 },
        itemStyle: { color: '#1890ff' },
      }],
    }],
  } : null;

  const positionPercent = (signal?.positionLimit || 0) * 100;

  // 加载中占位
  if (!signal && !loadError) {
    return (
      <div style={{ padding: 24 }}>
        <Spin tip="择时信号加载中，首次启动约需 1-2 分钟..." style={{ width: '100%', marginTop: 100 }}>
          <div style={{ height: 300 }} />
        </Spin>
      </div>
    );
  }

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
              value={signal?.totalScore != null ? signal.totalScore : 'N/A'}
              suffix={signal?.totalScore != null ? '/ 100分' : undefined}
              valueStyle={{ color: signal?.totalScore != null ? getScoreColor(signal.totalScore) : '#999' }}
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
            {signal ? (
              <ReactEChartsCore echarts={echarts} option={gaugeOption} style={{ height: 300 }} />
            ) : (
              <Empty description="等待数据" style={{ height: 300, paddingTop: 80 }} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="因子得分雷达">
            {radarOption ? (
              <ReactEChartsCore echarts={echarts} option={radarOption} style={{ height: 300 }} />
            ) : (
              <Empty description="等待因子数据" style={{ height: 300, paddingTop: 80 }} />
            )}
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
	            const subFactors = factor.subFactors;
	            const hasSub = subFactors != null && subFactors.length > 0;
	            const factorScoreVal = factor.score ?? 0;
	            const factorMaxVal = factor.maxScore || 1;
	            const factorPct = factor.score != null ? (factorScoreVal / factorMaxVal) * 100 : 0;

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
	                        percent={factorPct}
	                        format={() => `${factorScoreVal}/${factorMaxVal}`}
	                        strokeColor={getScoreColor(factorPct)}
	                        size="small"
	                        style={{ marginBottom: 0 }}
	                      />
	                    </Col>
	                    <Col span={4}>
	                      {getStatusTag(factor.status)}
	                    </Col>
	                    <Col span={3}>
	                      {hasSub && (
	                        <Tag style={{ fontSize: 11 }}>{subFactors.length}个子因子</Tag>
	                      )}
	                    </Col>
	                  </Row>
	                }
              >
                <div style={{ padding: '0 16px' }}>
                  <p style={{ color: '#666', marginBottom: 12 }}>{factor.description}</p>
                  {hasSub && (
	                    <Table
	                      dataSource={subFactors.map((sf, i) => ({ ...sf, key: i }))}
	                      columns={[
	                        { title: '子因子', dataIndex: 'name', key: 'name', width: 160 },
	                        {
	                          title: '得分',
	                          key: 'score',
	                          width: 180,
	                          render: (_: any, r: any) => (
	                            <Progress
	                              percent={r.score != null ? r.score : 0}
	                              format={() => r.score != null ? `${r.score}分` : 'N/A'}
	                              strokeColor={r.score != null ? getScoreColor(r.score) : '#d9d9d9'}
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
