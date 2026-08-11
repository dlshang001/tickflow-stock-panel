/**
 * 费用饼图。
 * 三项：佣金、印花税、过户费。
 */
import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/pages/backtest/charts/useECharts'
import { useChartTheme } from '@/lib/theme'

interface Props {
  fees: { commission: number; stamp_duty: number; transfer_fee: number; total: number }
  height?: number
}

const COLORS = ['#F79009', '#F04438', '#7C6FF7']

export function FeePieChart({ fees, height = 240 }: Props) {
  const theme = useChartTheme()
  const { commission, stamp_duty, transfer_fee, total } = fees

  const option = useMemo<EChartsOption | null>(() => {
    if (total <= 0) return null
    const items = [
      { name: '佣金', value: commission },
      { name: '印花税', value: stamp_duty },
      { name: '过户费', value: transfer_fee },
    ].filter(i => i.value > 0)

    if (!items.length) return null

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        formatter: (p: any) => {
          const pct = items.reduce((s, i) => s + i.value, 0)
          return `<div style="font-size:11px;line-height:1.6">
            <div style="color:${theme.textStrong}">${p.name}</div>
            <div>¥${Number(p.value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</div>
            <div>占比 ${(p.value / pct * 100).toFixed(1)}%</div>
          </div>`
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: theme.text, fontSize: 10 },
        itemWidth: 10,
        itemHeight: 10,
      },
      series: [
        {
          type: 'pie',
          radius: ['50%', '75%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 2,
            borderColor: 'transparent',
            borderWidth: 2,
          },
          label: {
            show: true,
            position: 'outside',
            color: theme.text,
            fontSize: 10,
            formatter: '{b}\n{d}%',
          },
          emphasis: {
            label: { fontSize: 12, fontWeight: 'bold' },
          },
          data: items.map((i, idx) => ({
            ...i,
            itemStyle: { color: COLORS[idx % COLORS.length] },
          })),
        },
      ],
    }
  }, [fees, theme])

  const ref = useECharts(option, [fees, theme])

  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <h3 className="mb-2 text-[11px] font-medium text-foreground">费用构成</h3>
      {total <= 0 ? (
        <div className="flex items-center justify-center text-[10px] text-muted" style={{ height }}>暂无费用数据</div>
      ) : (
        <div ref={ref} style={{ width: '100%', height }} />
      )}
    </div>
  )
}