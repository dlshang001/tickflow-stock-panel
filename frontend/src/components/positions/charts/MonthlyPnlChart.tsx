/**
 * 月度盈亏柱状图。
 * 双柱：买入金额 vs 卖出金额，折线：月度盈亏。
 */
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/pages/backtest/charts/useECharts'
import { useChartTheme } from '@/lib/theme'

interface Props {
  data: { month: string; pnl: number; buy_amount: number; sell_amount: number }[]
  height?: number
}

export function MonthlyPnlChart({ data, height = 260 }: Props) {
  const theme = useChartTheme()

  const option = useMemo<EChartsOption | null>(() => {
    if (!data.length) return null
    const months = data.map(d => d.month)
    const buy = data.map(d => d.buy_amount)
    const sell = data.map(d => d.sell_amount)
    const pnl = data.map(d => d.pnl)

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: any) => {
          const [b, s, p] = (params || []) as any[]
          return `<div style="font-size:11px;line-height:1.6">
            <div style="color:${theme.textStrong};margin-bottom:2px">${(b || s || p)?.axisValue ?? ''}</div>
            <div>买入 <span style="color:#F04438">${Number(b?.value ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</span></div>
            <div>卖出 <span style="color:#12B76A">${Number(s?.value ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</span></div>
            <div>盈亏 <span style="color:${(p?.value ?? 0) >= 0 ? '#F04438' : '#12B76A'}">${Number(p?.value ?? 0).toLocaleString('zh-CN', { signDisplay: 'always', minimumFractionDigits: 2 })}</span></div>
          </div>`
        },
      },
      legend: {
        data: ['买入金额', '卖出金额', '月度盈亏'],
        bottom: 0,
        textStyle: { color: theme.text, fontSize: 10 },
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 12, right: 20, top: 12, bottom: 32 },
      xAxis: {
        type: 'category',
        data: months,
        axisLine: { lineStyle: { color: theme.border } },
        axisTick: { show: false },
        axisLabel: { color: theme.text, fontSize: 9 },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '金额',
          nameTextStyle: { color: theme.text, fontSize: 9 },
          axisLabel: { color: theme.text, fontSize: 9, formatter: (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(1)}万` : `${v}`) },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        {
          type: 'value',
          name: '盈亏',
          nameTextStyle: { color: theme.text, fontSize: 9 },
          axisLabel: { color: theme.text, fontSize: 9, formatter: (v: number) => v >= 0 ? `+${v}` : `${v}` },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '买入金额',
          type: 'bar',
          data: buy,
          yAxisIndex: 0,
          itemStyle: { color: '#F04438', borderRadius: [1, 1, 0, 0] },
          barMaxWidth: 20,
          barGap: '10%',
        },
        {
          name: '卖出金额',
          type: 'bar',
          data: sell,
          yAxisIndex: 0,
          itemStyle: { color: '#12B76A', borderRadius: [1, 1, 0, 0] },
          barMaxWidth: 20,
        },
        {
          name: '月度盈亏',
          type: 'line',
          data: pnl,
          yAxisIndex: 1,
          lineStyle: { color: '#7C6FF7', width: 2 },
          itemStyle: { color: '#7C6FF7' },
          symbol: 'circle',
          symbolSize: 6,
        },
      ],
    }
  }, [data, theme])

  const ref = useECharts(option, [data, theme])

  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <h3 className="mb-2 text-[11px] font-medium text-foreground">月度盈亏</h3>
      {!data.length ? (
        <div className="flex items-center justify-center text-[10px] text-muted" style={{ height }}>暂无数据</div>
      ) : (
        <div ref={ref} style={{ width: '100%', height }} />
      )}
    </div>
  )
}