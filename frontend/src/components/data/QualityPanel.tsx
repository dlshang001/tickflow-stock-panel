import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  CalendarX,
  Layers,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { Skeleton } from './Skeleton'
import { fmtPrice, fmtPct, fmtVolume } from '@/lib/format'

const GRADE_CONFIG = {
  ok: { icon: ShieldCheck, color: 'text-bear', bg: 'bg-bear/8 border-bear/20', label: '数据正常' },
  warning: { icon: ShieldAlert, color: 'text-accent', bg: 'bg-accent/8 border-accent/20', label: '存在告警' },
  error: { icon: ShieldX, color: 'text-danger', bg: 'bg-danger/8 border-danger/20', label: '存在异常' },
} as const

export function QualityPanel() {
  const [expanded, setExpanded] = useState<string | null>('price')

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: QK.dataQuality,
    queryFn: () => api.dataQuality(),
    staleTime: 60_000,
    refetchInterval: false,
  })

  const grade = data?.summary?.grade ?? 'ok'
  const cfg = GRADE_CONFIG[grade]
  const GradeIcon = cfg.icon

  const toggleSection = (key: string) => {
    setExpanded(prev => (prev === key ? null : key))
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-secondary">
          <ShieldCheck className="h-3.5 w-3.5" />
          数据质量
        </h2>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1 text-[11px] text-muted hover:text-secondary transition-colors"
        >
          <RefreshCw className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className={`mt-3 rounded-card border ${cfg.bg} p-4`}>
        {/* 质量等级汇总 */}
        <div className="flex items-center gap-3">
          <GradeIcon className={`h-6 w-6 ${cfg.color}`} />
          <div>
            <div className={`text-sm font-medium ${cfg.color}`}>{cfg.label}</div>
            <div className="text-[11px] text-muted">
              {isLoading ? '扫描中…' : `检查范围 ${data?.summary?.checked_range_start ?? '—'} ~ ${data?.summary?.checked_range_end ?? '—'}`}
            </div>
          </div>
          {!isLoading && data && (
            <div className="ml-auto flex gap-4 text-[11px]">
              <div className="text-center">
                <div className="font-mono text-sm text-secondary">{data.summary.anomaly_count}</div>
                <div className="text-muted">价格异常</div>
              </div>
              <div className="text-center">
                <div className="font-mono text-sm text-secondary">{data.summary.gap_count}</div>
                <div className="text-muted">缺失区间</div>
              </div>
              <div className="text-center">
                <div className="font-mono text-sm text-secondary">{data.summary.low_coverage_count}</div>
                <div className="text-muted">低覆盖日</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 详情列表 */}
      {isLoading ? (
        <div className="mt-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} w="w-full" h="h-12" />
          ))}
        </div>
      ) : data ? (
        <div className="mt-3 space-y-2">
          {/* 价格异常 */}
          <QualitySection
            title="价格异常"
            icon={TrendingUp}
            count={data.price_anomalies.count}
            error={data.price_anomalies.error}
            expanded={expanded === 'price'}
            onToggle={() => toggleSection('price')}
          >
            {data.price_anomalies.anomalies.length > 0 ? (
              <div className="max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted border-b border-border/50">
                      <th className="py-1.5 font-normal">标的</th>
                      <th className="py-1.5 font-normal">日期</th>
                      <th className="py-1.5 font-normal text-right">前收</th>
                      <th className="py-1.5 font-normal text-right">收盘</th>
                      <th className="py-1.5 font-normal text-right">涨跌幅</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.price_anomalies.anomalies.map((a, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-elevated/50">
                        <td className="py-1.5 font-mono">{a.symbol}</td>
                        <td className="py-1.5 text-muted">{a.date}</td>
                        <td className="py-1.5 text-right font-mono text-muted">{fmtPrice(a.prev_close)}</td>
                        <td className="py-1.5 text-right font-mono">{fmtPrice(a.close)}</td>
                        <td className={`py-1.5 text-right font-mono font-medium ${a.pct_change > 0 ? 'text-bull' : 'text-bear'}`}>
                          {a.pct_change > 0 ? '+' : ''}{fmtPct(a.pct_change)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-3 text-center text-xs text-muted">未检测到价格异常</div>
            )}
          </QualitySection>

          {/* 缺失区间 */}
          <QualitySection
            title="缺失区间"
            icon={CalendarX}
            count={data.integrity.missing_gap_count}
            error={data.integrity.error}
            expanded={expanded === 'gap'}
            onToggle={() => toggleSection('gap')}
          >
            {data.integrity.missing_gaps.length > 0 ? (
              <div className="space-y-1 py-1">
                {data.integrity.missing_gaps.map((g, i) => (
                  <div key={i} className="text-xs font-mono text-accent px-2 py-1 rounded bg-accent/5">
                    {g}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-3 text-center text-xs text-muted">未检测到日期缺失</div>
            )}
          </QualitySection>

          {/* 低覆盖日 */}
          <QualitySection
            title="低覆盖日"
            icon={Layers}
            count={data.integrity.low_coverage_count}
            expanded={expanded === 'lowcov'}
            onToggle={() => toggleSection('lowcov')}
          >
            {data.integrity.low_coverage_dates.length > 0 ? (
              <div className="flex flex-wrap gap-1 py-1">
                {data.integrity.low_coverage_dates.map((d, i) => (
                  <span key={i} className="text-[11px] font-mono text-accent bg-accent/5 px-1.5 py-0.5 rounded">
                    {d}
                  </span>
                ))}
              </div>
            ) : (
              <div className="py-3 text-center text-xs text-muted">所有日期覆盖率正常</div>
            )}
          </QualitySection>

          {/* 负成交量 */}
          <QualitySection
            title="负成交量"
            icon={TrendingDown}
            count={data.negative_volume.count}
            error={data.negative_volume.error}
            expanded={expanded === 'negvol'}
            onToggle={() => toggleSection('negvol')}
          >
            {data.negative_volume.records.length > 0 ? (
              <div className="max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted border-b border-border/50">
                      <th className="py-1.5 font-normal">标的</th>
                      <th className="py-1.5 font-normal">日期</th>
                      <th className="py-1.5 font-normal text-right">成交量</th>
                      <th className="py-1.5 font-normal text-right">成交额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.negative_volume.records.map((r, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-elevated/50">
                        <td className="py-1.5 font-mono">{r.symbol}</td>
                        <td className="py-1.5 text-muted">{r.date}</td>
                        <td className="py-1.5 text-right font-mono text-danger">{r.volume != null ? fmtVolume(r.volume) : '—'}</td>
                        <td className="py-1.5 text-right font-mono text-danger">{r.amount != null ? fmtPrice(r.amount) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-3 text-center text-xs text-muted">未检测到负成交量</div>
            )}
          </QualitySection>

          {/* 完整性摘要 */}
          <div className="rounded-card border border-border/50 px-4 py-3 text-[11px] text-muted">
            <span>日期范围: </span>
            <span className="font-mono text-secondary">{data.integrity.date_start ?? '—'} ~ {data.integrity.date_end ?? '—'}</span>
            <span className="mx-2">·</span>
            <span>交易日数: </span>
            <span className="font-mono text-secondary">{data.integrity.dates}</span>
            <span className="mx-2">·</span>
            <span>最大覆盖: </span>
            <span className="font-mono text-secondary">{data.integrity.max_coverage} 只</span>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function QualitySection({
  title,
  icon: Icon,
  count,
  error,
  expanded,
  onToggle,
  children,
}: {
  title: string
  icon: React.ComponentType<{ className?: string }>
  count: number
  error?: string
  expanded: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  const hasIssues = count > 0
  return (
    <div className={`rounded-card border overflow-hidden ${hasIssues ? 'border-accent/30' : 'border-border/50'}`}>
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-elevated/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-muted" />}
          <Icon className={`h-3.5 w-3.5 ${hasIssues ? 'text-accent' : 'text-muted'}`} />
          <span className="text-xs font-medium">{title}</span>
        </div>
        <span className={`text-[11px] font-mono ${hasIssues ? 'text-accent' : 'text-muted'}`}>
          {error ? '扫描失败' : `${count} 条`}
        </span>
      </button>
      {expanded && (
        <div className="px-4 pb-3 border-t border-border/30">
          {children}
        </div>
      )}
    </div>
  )
}
