/**
 * 技术指标面板组件
 */

import { useMemo } from 'react'
import { Card, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { fmt } from '../utils/format'

const { Text } = Typography




interface TechIndicatorsProps {
  data: {
    code: string
    name: string
    price: number
    change: number
    volume: number
    turnover: number
    ma5?: number
    ma10?: number
    ma20?: number
    macd?: { dif: number; dea: number; macd: number }
    rsi?: { rsi6: number; rsi12: number; rsi24: number }
    kdj?: { k: number; d: number; j: number }
    boll?: { upper: number; middle: number; lower: number }
    volumeRatio?: number
    pe?: number
    pb?: number
  }
}

export default function TechIndicators({ data }: TechIndicatorsProps) {
  const indicators = useMemo(() => {
    const list: { name: string; value: string | number; signal: 'buy' | 'sell' | 'neutral'; description: string }[] = []

    // 均线分析
    if (data.ma5 && data.ma10 && data.ma20) {
      const maTrend = data.ma5 > data.ma10 && data.ma10 > data.ma20
      list.push({
        name: '均线趋势',
        value: maTrend ? '多头排列' : '空头排列',
        signal: maTrend ? 'buy' : 'sell',
        description: `MA5=${fmt(data.ma5)}, MA10=${fmt(data.ma10)}, MA20=${fmt(data.ma20)}`,
      })

      // 金叉死叉
      if (data.ma5 > data.ma10) {
        list.push({
          name: 'MA金叉',
          value: 'MA5上穿MA10',
          signal: 'buy',
          description: '短期均线向上突破中期均线',
        })
      } else if (data.ma5 < data.ma10) {
        list.push({
          name: 'MA死叉',
          value: 'MA5下穿MA10',
          signal: 'sell',
          description: '短期均线向下跌破中期均线',
        })
      }
    }

    // MACD分析
    if (data.macd) {
      const { dif, dea, macd } = data.macd
      list.push({
        name: 'MACD',
        value: `DIF:${fmt(dif)} DEA:${fmt(dea)} MACD:${fmt(macd)}`,
        signal: macd > 0 ? 'buy' : 'sell',
        description: macd > 0 ? 'MACD柱状图为正，多头动能' : 'MACD柱状图为负，空头动能',
      })

      if (dif > dea) {
        list.push({
          name: 'MACD金叉',
          value: 'DIF上穿DEA',
          signal: 'buy',
          description: 'MACD出现金叉信号',
        })
      } else if (dif < dea) {
        list.push({
          name: 'MACD死叉',
          value: 'DIF下穿DEA',
          signal: 'sell',
          description: 'MACD出现死叉信号',
        })
      }
    }

    // RSI分析
    if (data.rsi) {
      const { rsi6, rsi12, rsi24 } = data.rsi
      let rsiSignal: 'buy' | 'sell' | 'neutral' = 'neutral'
      let rsiDesc = ''

      if (rsi6 < 20) {
        rsiSignal = 'buy'
        rsiDesc = 'RSI超卖，可能反弹'
      } else if (rsi6 > 80) {
        rsiSignal = 'sell'
        rsiDesc = 'RSI超买，可能回调'
      } else if (rsi6 < 30) {
        rsiSignal = 'buy'
        rsiDesc = 'RSI偏低，接近超卖'
      } else if (rsi6 > 70) {
        rsiSignal = 'sell'
        rsiDesc = 'RSI偏高，接近超买'
      }

      list.push({
        name: 'RSI',
        value: `RSI(6):${fmt(rsi6, 1)} RSI(12):${fmt(rsi12, 1)} RSI(24):${fmt(rsi24, 1)}`,
        signal: rsiSignal,
        description: rsiDesc || 'RSI处于正常区间',
      })
    }

    // KDJ分析
    if (data.kdj) {
      const { k, d, j } = data.kdj
      let kdjSignal: 'buy' | 'sell' | 'neutral' = 'neutral'
      let kdjDesc = ''

      if (k < 20 && d < 20) {
        kdjSignal = 'buy'
        kdjDesc = 'KDJ超卖，可能反弹'
      } else if (k > 80 && d > 80) {
        kdjSignal = 'sell'
        kdjDesc = 'KDJ超买，可能回调'
      } else if (k > d && k < 50) {
        kdjSignal = 'buy'
        kdjDesc = 'KDJ金叉且处于低位'
      } else if (k < d && k > 50) {
        kdjSignal = 'sell'
        kdjDesc = 'KDJ死叉且处于高位'
      }

      list.push({
        name: 'KDJ',
        value: `K:${fmt(k, 1)} D:${fmt(d, 1)} J:${fmt(j, 1)}`,
        signal: kdjSignal,
        description: kdjDesc || 'KDJ正常波动',
      })
    }

    // 布林带分析
    if (data.boll) {
      const { upper, middle, lower } = data.boll
      let bollSignal: 'buy' | 'sell' | 'neutral' = 'neutral'

      if (data.price <= lower) {
        bollSignal = 'buy'
      } else if (data.price >= upper) {
        bollSignal = 'sell'
      }

      list.push({
        name: '布林带',
        value: `上轨:${fmt(upper)} 中轨:${fmt(middle)} 下轨:${fmt(lower)}`,
        signal: bollSignal,
        description: data.price <= lower
          ? '价格触及下轨，可能反弹'
          : data.price >= upper
            ? '价格触及上轨，可能回调'
            : data.price < middle
              ? '价格在布林带中轨下方'
              : '价格在布林带中轨上方',
      })
    }

    // 量比分析
    if (data.volumeRatio) {
      let volumeSignal: 'buy' | 'sell' | 'neutral' = 'neutral'

      if (data.volumeRatio > 2) {
        volumeSignal = data.change > 0 ? 'buy' : 'sell'
      }

      list.push({
        name: '量比',
        value: fmt(data.volumeRatio),
        signal: volumeSignal,
        description: data.volumeRatio > 2 ? '放量明显' : data.volumeRatio < 0.5 ? '缩量明显' : '量能正常',
      })
    }

    return list
  }, [data])

  const columns: ColumnsType<typeof indicators[0]> = [
    {
      title: '指标名称',
      dataIndex: 'name',
      width: 100,
    },
    {
      title: '指标值',
      dataIndex: 'value',
      width: 200,
    },
    {
      title: '信号',
      dataIndex: 'signal',
      width: 80,
      render: (signal: string) => (
        <Tag color={signal === 'buy' ? 'green' : signal === 'sell' ? 'red' : 'default'}>
          {signal === 'buy' ? '买入' : signal === 'sell' ? '卖出' : '中性'}
        </Tag>
      ),
    },
    {
      title: '解读',
      dataIndex: 'description',
    },
  ]

  // 综合评分
  const buyCount = indicators.filter(i => i.signal === 'buy').length
  const sellCount = indicators.filter(i => i.signal === 'sell').length
  const overallSignal = buyCount > sellCount ? 'buy' : sellCount > buyCount ? 'sell' : 'neutral'

  return (
    <Card
      title={`${data.name} (${data.code}) 技术分析`}
      extra={
        <Tag color={overallSignal === 'buy' ? 'green' : overallSignal === 'sell' ? 'red' : 'default'}>
          综合信号: {overallSignal === 'buy' ? '偏多' : overallSignal === 'sell' ? '偏空' : '中性'}
          <Text style={{ marginLeft: 8 }} type="secondary">
            ({buyCount}买/{sellCount}卖)
          </Text>
        </Tag>
      }
    >
      <Table
        dataSource={indicators}
        columns={columns}
        rowKey="name"
        pagination={false}
        size="small"
      />
    </Card>
  )
}
