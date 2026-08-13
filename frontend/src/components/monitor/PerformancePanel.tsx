import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import { Activity, TrendingUp, TrendingDown, Target, Gauge } from 'lucide-react'
import { api, type AlertStats, type AlertEvent } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { useChartTheme } from '@/lib/theme'
import { Skeleton } from '@/components/data/Skeleton'
import { EmptyState } from '@/components/EmptyState'
import { cn } from '@/lib/cn'

const HORIZONS = [1, 3, 5, 10, 20] as const
const DAYS_OPTIONS = [7, 14, 30] as const
const SOURCE_OPTIONS = [
  { value: '', label: '全部来源' },
  { value: 'signal', label: '信号' },
  { value: 'price', label: '价格/涨跌' },
  { value: 'market', label: '市场异动' },
  { value: 'strategy', label: '策略监控' },
  { value: 'sector', label: '板块监控' },
] as const

/** 后端返回的 pct 已是百分比 (如 2.35 = +2.35%), 直接格式化即可 */
function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

function pnlColor(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v) || v === 0) return 'text-muted'
  return v > 0 ? 'text-bull' : 'text-bear'
}

interface Props {
  days: number
  source: string
  onDaysChange: (d: number) => void
  onSourceChange: (s: string) => void
}

export function PerformancePanel({ days, source, onDaysChange, onSourceChange }: Props) {
  const statsQuery = useQuery({
    queryKey: QK.alertStats(days, source || undefined),
    queryFn: () => api.alertStats({ days, source: source || undefined }),
    refetchInterval: 30000,
  })

  // 触发记录明细 (用于表格)
  const alertsQuery = useQuery({
    queryKey: [...QK.alerts(source || undefined), 'perf-detail', String(days)],
    queryFn: () => api.alertsList({ days, limit: 500, source: source || undefined }),
    refetchInterval: 30000,
  })

  const stats = statsQuery.data
  const allAlerts: AlertEvent[] = (alertsQuery.data as any)?.alerts ?? []
  // 仅展示有 symbol 且有任意 pnl 字段的记录
  const trackedAlerts = useMemo(
    () => allAlerts.filter((a: AlertEvent) => a.symbol && HORIZONS.some(h => (a as any)[`pnl_${h}d`] != null)),
    [allAlerts],
  )

  return (
    <div className="flex h-full flex-col gap-3">
      {/* 筛选条 */}
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        <div className="flex items-center gap-1">
          {DAYS_OPTIONS.map(d => (
            <button
              key={d}
              onClick={() => onDaysChange(d)}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-medium transition-all cursor-pointer',
                days === d ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-elevated/60 hover:text-secondary',
              )}
            >
              近{d}天
            </button>
          ))}
        </div>
        <div className="h-3 w-px bg-border/60" />
        <div className="flex items-center gap-1">
          {SOURCE_OPTIONS.map(o => (
            <button
              key={o.value}
              onClick={() => onSourceChange(o.value)}
              className={cn(
                'rounded-md px-2 py-1 text-xs font-medium transition-all cursor-pointer',
                source === o.value ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-elevated/60 hover:text-secondary',
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {statsQuery.isLoading ? (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} h="h-20" rounded="rounded-card" />)}
          </div>
          <Skeleton h="h-64" rounded="rounded-card" />
        </div>
      ) : !stats || stats.tracked === 0 ? (
        <EmptyState
          icon={Activity}
          title="暂无绩效数据"
          hint="监控信号触发后, 盘后管道会自动回填触发后 1/3/5/10/20 日收益。等待交易日收盘后数据逐步生成。"
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
          {/* 汇总卡片 */}
          <SummaryCards stats={stats} />

          {/* 命中率柱状图 */}
          <HitRateChart stats={stats} />

          {/* 视野指标表 */}
          <HorizonTable stats={stats} />

          {/* 绩效明细表 */}
          <DetailTable alerts={trackedAlerts} />
        </div>
      )}
    </div>
  )
}

// ── 汇总卡片 ──────────────────────────────────────────
function SummaryCards({ stats }: { stats: AlertStats }) {
  const cards = [
    {
      icon: Target,
      label: '已追踪',
      value: String(stats.tracked),
      hint: `共 ${stats.total} 条`,
      color: 'text-accent',
    },
    {
      icon: Gauge,
      label: '1日命中率',
      value: stats.horizons['1']?.hit_rate != null ? `${stats.horizons['1'].hit_rate}%` : '—',
      hint: `${stats.horizons['1']?.count ?? 0} 个样本`,
      color: 'text-bull',
    },
    {
      icon: TrendingUp,
      label: '1日均收益',
      value: pct(stats.horizons['1']?.avg_pnl),
      hint: stats.horizons['1']?.max_gain != null ? `最大盈利 ${pct(stats.horizons['1'].max_gain)}` : '',
      color: pnlColor(stats.horizons['1']?.avg_pnl),
    },
    {
      icon: TrendingDown,
      label: '1日最大亏损',
      value: pct(stats.horizons['1']?.max_loss),
      hint: stats.horizons['1']?.count ? `${stats.horizons['1'].count} 个样本` : '',
      color: 'text-bear',
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cards.map(c => (
        <div key={c.label} className="rounded-card border border-border/60 bg-surface/60 p-3">
          <div className="flex items-center gap-1.5 text-muted">
            <c.icon className="h-3.5 w-3.5" />
            <span className="text-xs">{c.label}</span>
          </div>
          <div className={cn('mt-1.5 text-xl font-bold tabular-nums', c.color)}>{c.value}</div>
          {c.hint && <div className="mt-0.5 text-[11px] text-muted">{c.hint}</div>}
        </div>
      ))}
    </div>
  )
}

// ── 命中率柱状图 ──────────────────────────────────────
function HitRateChart({ stats }: { stats: AlertStats }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ECharts | null>(null)
  const roRef = useRef<ResizeObserver | null>(null)
  const ct = useChartTheme()

  const data = useMemo(
    () => HORIZONS.map(h => {
      const s = stats.horizons[String(h)]
      return { horizon: `${h}日`, hitRate: s?.hit_rate ?? null, count: s?.count ?? 0 }
    }),
    [stats],
  )

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    let chart = chartRef.current
    if (!chart) {
      chart = echarts.init(el, undefined, { renderer: 'canvas' })
      chartRef.current = chart
      roRef.current = new ResizeObserver(() => chart!.resize())
      roRef.current.observe(el)
    }
    const option: EChartsOption = {
      backgroundColor: 'transparent',
      grid: { top: 36, right: 16, bottom: 28, left: 40 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: ct.tooltipBg,
        borderColor: ct.tooltipBorder,
        textStyle: { color: ct.tooltipText, fontSize: 13 },
        formatter: (params: any) => {
          const p = Array.isArray(params) ? params[0] : params
          const idx = p.dataIndex
          const d = data[idx]
          return `${d.horizon}<br/>命中率: <b>${d.hitRate != null ? d.hitRate + '%' : '—'}</b><br/>样本: ${d.count}`
        },
      },
      xAxis: {
        type: 'category',
        data: data.map(d => d.horizon),
        axisLine: { lineStyle: { color: ct.border } },
        axisLabel: { color: ct.text, fontSize: 13 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        max: 100,
        axisLine: { show: false },
        axisLabel: { color: ct.text, fontSize: 12, formatter: '{value}%' },
        splitLine: { lineStyle: { color: ct.grid } },
      },
      series: [
        {
          type: 'bar',
          data: data.map(d => ({
            value: d.hitRate,
            itemStyle: {
              color: d.hitRate == null ? 'rgba(161,161,170,0.2)' : d.hitRate >= 60 ? '#22C55E' : d.hitRate >= 40 ? '#F59E0B' : '#EF4444',
            },
          })),
          barWidth: '40%',
          label: {
            show: true,
            position: 'top',
            color: ct.textStrong,
            fontSize: 13,
            formatter: (p: any) => (p.value != null ? p.value + '%' : ''),
          },
        },
      ],
    }
    chart.setOption(option, true)
    return () => {
      if (roRef.current) {
        roRef.current.disconnect()
        roRef.current = null
      }
    }
  }, [data, ct])

  useEffect(() => {
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <div className="rounded-card border border-border/60 bg-surface/60 p-3">
      <div className="mb-1 text-sm font-semibold text-foreground">命中率分布</div>
      <div ref={containerRef} className="h-56 w-full" />
    </div>
  )
}

// ── 视野指标表 ────────────────────────────────────────
function HorizonTable({ stats }: { stats: AlertStats }) {
  return (
    <div className="rounded-card border border-border/60 bg-surface/60">
      <div className="border-b border-border/60 px-3 py-2 text-sm font-semibold text-foreground">
        各视野绩效指标
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-xs text-muted">
              <th className="px-3 py-2 text-left font-medium">视野</th>
              <th className="px-3 py-2 text-right font-medium">样本</th>
              <th className="px-3 py-2 text-right font-medium">命中率</th>
              <th className="px-3 py-2 text-right font-medium">平均收益</th>
              <th className="px-3 py-2 text-right font-medium">最大盈利</th>
              <th className="px-3 py-2 text-right font-medium">最大亏损</th>
            </tr>
          </thead>
          <tbody>
            {HORIZONS.map(h => {
              const s = stats.horizons[String(h)]
              return (
                <tr key={h} className="border-b border-border/40 last:border-0">
                  <td className="px-3 py-2 font-medium text-foreground">触发后 {h} 日</td>
                  <td className="px-3 py-2 text-right tabular-nums text-secondary">{s?.count ?? 0}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {s?.hit_rate != null ? (
                      <span className={cn('font-medium', s.hit_rate >= 60 ? 'text-bull' : s.hit_rate >= 40 ? 'text-warning' : 'text-bear')}>
                        {s.hit_rate}%
                      </span>
                    ) : '—'}
                  </td>
                  <td className={cn('px-3 py-2 text-right tabular-nums font-medium', pnlColor(s?.avg_pnl))}>
                    {pct(s?.avg_pnl)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-bull">{pct(s?.max_gain)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-bear">{pct(s?.max_loss)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── 绩效明细表 ────────────────────────────────────────
function DetailTable({ alerts }: { alerts: AlertEvent[] }) {
  if (alerts.length === 0) {
    return (
      <div className="rounded-card border border-border/60 bg-surface/60 p-4 text-center text-sm text-muted">
        暂无已回填收益的明细记录
      </div>
    )
  }
  return (
    <div className="rounded-card border border-border/60 bg-surface/60">
      <div className="border-b border-border/60 px-3 py-2 text-sm font-semibold text-foreground">
        触发明细 ({alerts.length} 条)
      </div>
      <div className="max-h-80 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-border/60 text-xs text-muted">
              <th className="px-3 py-2 text-left font-medium">时间 / 标的</th>
              <th className="px-3 py-2 text-left font-medium">来源</th>
              <th className="px-3 py-2 text-right font-medium">触发价</th>
              {HORIZONS.map(h => (
                <th key={h} className="px-3 py-2 text-right font-medium">{h}日</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {alerts.map(ev => {
              const ts = ev.ts
              const d = new Date(ts)
              const dateStr = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
              return (
                <tr key={ts} className="border-b border-border/40 last:border-0 hover:bg-elevated/30">
                  <td className="px-3 py-1.5">
                    <div className="text-xs text-muted">{dateStr}</div>
                    <div className="font-medium text-foreground">
                      {ev.symbol}
                      {ev.name ? <span className="ml-1 text-muted">{ev.name}</span> : null}
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="rounded bg-elevated/50 px-1.5 py-0.5 text-[11px] text-secondary">{ev.source}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-secondary">
                    {ev.price != null ? ev.price.toFixed(2) : '—'}
                  </td>
                  {HORIZONS.map(h => {
                    const v = (ev as any)[`pnl_${h}d`] as number | null | undefined
                    return (
                      <td key={h} className={cn('px-3 py-1.5 text-right tabular-nums', pnlColor(v))}>
                        {pct(v)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
