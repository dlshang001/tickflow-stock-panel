/**
 * 单票盈亏排行横向柱状图。
 * 按盈亏绝对值排序，正值红色（盈利），负值绿色（亏损）。
 */
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/pages/backtest/charts/useECharts'
import { useChartTheme } from '@/lib/theme'

interface Props {
  data: { symbol: string; name: string; pnl: number; buy_count: number; sell_count: number }[]
  height?: number
}

export function SymbolPnlChart({ data, height = 280 }: Props) {
  const theme = useChartTheme()

  const option = useMemo<EChartsOption | null>(() => {
    if (!data.length) return null
    // 反转 Y 轴：最大值在上
    const labels = data.map(d => `${d.name || d.symbol}`).reverse()
    const values = [...data.map(d => d.pnl)].reverse()

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (params: any) => {
          const p = (params || [])[0]
          if (!p) return ''
          const idx = data.length - 1 - (p.dataIndex ?? 0)
          const d = data[idx]
          return `<div style="font-size:11px;line-height:1.6">
            <div style="color:${theme.textStrong};margin-bottom:2px">${d.name || d.symbol}（${d.symbol}）</div>
            <div>盈亏 <span style="color:${d.pnl >= 0 ? '#F04438' : '#12B76A'}">${d.pnl.toLocaleString('zh-CN', { signDisplay: 'always', minimumFractionDigits: 2 })}</span></div>
            <div>买入 ${d.buy_count} 笔 / 卖出 ${d.sell_count} 笔</div>
          </div>`
        },
      },
      grid: { left: 8, right: 20, top: 8, bottom: 8 },
      xAxis: {
        type: 'value',
        axisLabel: { color: theme.text, fontSize: 9, formatter: (v: number) => v >= 0 ? `+${v}` : `${v}` },
        splitLine: { lineStyle: { color: theme.grid } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLine: { lineStyle: { color: theme.border } },
        axisTick: { show: false },
        axisLabel: { color: theme.textStrong, fontSize: 10, width: 80, overflow: 'truncate' },
        inverse: false,
      },
      series: [
        {
          type: 'bar',
          data: values.map(v => ({
            value: v,
            itemStyle: {
              color: v >= 0 ? '#F04438' : '#12B76A',
              borderRadius: v >= 0 ? [0, 2, 2, 0] : [2, 0, 0, 2],
            },
          })),
          barMaxWidth: 20,
          label: {
            show: true,
            position: 'right',
            color: theme.text,
            fontSize: 9,
            formatter: (p: any) => (p.value ?? 0) >= 0 ? `+${Number(p.value).toFixed(0)}` : `${Number(p.value).toFixed(0)}`,
          },
        },
      ],
    }
  }, [data, theme])

  const ref = useECharts(option, [data, theme])

  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <h3 className="mb-2 text-[11px] font-medium text-foreground">单票盈亏排行</h3>
      {!data.length ? (
        <div className="flex items-center justify-center text-[10px] text-muted" style={{ height }}>暂无数据</div>
      ) : (
        <div ref={ref} style={{ width: '100%', height }} />
      )}
    </div>
  )
}