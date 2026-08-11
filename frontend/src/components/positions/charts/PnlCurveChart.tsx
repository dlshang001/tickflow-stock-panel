/**
 * 累积已实现盈亏折线图。
 * 双线：每日盈亏（柱状）+ 累积盈亏（折线）。
 */
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/pages/backtest/charts/useECharts'
import { useChartTheme } from '@/lib/theme'

interface Props {
  data: { date: string; pnl: number; cumulative: number }[]
  height?: number
}

export function PnlCurveChart({ data, height = 280 }: Props) {
  const theme = useChartTheme()

  const option = useMemo<EChartsOption | null>(() => {
    if (!data.length) return null
    const dates = data.map(d => d.date)
    const daily = data.map(d => d.pnl)
    const cum = data.map(d => d.cumulative)

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: any) => {
          const [d, c] = params || []
          return `<div style="font-size:11px;line-height:1.6">
            <div style="color:${theme.textStrong};margin-bottom:2px">${(d || c)?.axisValue ?? ''}</div>
            <div>日盈亏 <span style="color:${(d?.value ?? 0) >= 0 ? '#F04438' : '#12B76A'}">${Number(d?.value ?? 0).toLocaleString('zh-CN', { signDisplay: 'always', minimumFractionDigits: 2 })}</span></div>
            <div>累积 <span style="color:${(c?.value ?? 0) >= 0 ? '#F04438' : '#12B76A'}">${Number(c?.value ?? 0).toLocaleString('zh-CN', { signDisplay: 'always', minimumFractionDigits: 2 })}</span></div>
          </div>`
        },
      },
      legend: {
        data: ['日盈亏', '累积盈亏'],
        bottom: 0,
        textStyle: { color: theme.text, fontSize: 10 },
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 12, right: 20, top: 12, bottom: 32 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: theme.border } },
        axisTick: { show: false },
        axisLabel: { color: theme.text, fontSize: 9, rotate: dates.length > 30 ? 45 : 0 },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '日盈亏',
          nameTextStyle: { color: theme.text, fontSize: 9 },
          axisLabel: { color: theme.text, fontSize: 9, formatter: (v: number) => v >= 0 ? `+${v}` : `${v}` },
          splitLine: { lineStyle: { color: theme.grid } },
        },
        {
          type: 'value',
          name: '累积',
          nameTextStyle: { color: theme.text, fontSize: 9 },
          axisLabel: { color: theme.text, fontSize: 9, formatter: (v: number) => v >= 0 ? `+${v}` : `${v}` },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '日盈亏',
          type: 'bar',
          data: daily,
          yAxisIndex: 0,
          itemStyle: {
            color: (params: any) => (params.value ?? 0) >= 0 ? '#F04438' : '#12B76A',
            borderRadius: [1, 1, 0, 0],
          },
          barMaxWidth: 16,
        },
        {
          name: '累积盈亏',
          type: 'line',
          data: cum,
          yAxisIndex: 1,
          lineStyle: { color: '#7C6FF7', width: 2 },
          itemStyle: { color: '#7C6FF7' },
          symbol: 'none',
          smooth: true,
        },
      ],
    }
  }, [data, theme])

  const ref = useECharts(option, [data, theme])

  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <h3 className="mb-2 text-[11px] font-medium text-foreground">累积已实现盈亏</h3>
      {!data.length ? (
        <div className="flex items-center justify-center text-[10px] text-muted" style={{ height }}>暂无数据</div>
      ) : (
        <div ref={ref} style={{ width: '100%', height }} />
      )}
    </div>
  )
}