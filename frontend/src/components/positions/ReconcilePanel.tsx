/**
 * 对账面板：比较交割单推导持仓与操作日志推导持仓。
 *
 * 差异类型：
 *   matched           两边一致
 *   mismatch          两边都有但股数/成本不符
 *   only_settlement   交割单有、日志没有
 *   only_position_log 日志有、交割单没有
 *
 * 操作：
 *   fix    — only_settlement → 补 buy 日志；mismatch → clear + buy 重建
 *   delete — 删除该标的全部日志
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw, Check, Trash2, Scale, AlertTriangle, CircleCheck, CircleAlert, CircleOff, Sparkles } from 'lucide-react'
import { api, type ReconItem, type ReconDiffType } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

// ===== 差异类型标签配置 =====
const DIFF_CONFIG: Record<ReconDiffType, { label: string; icon: React.FC<{ className?: string }>; cls: string }> = {
  matched: {
    label: '一致',
    icon: ({ className }) => <CircleCheck className={className ?? ''} />,
    cls: 'bg-up/10 text-up border-up/30',
  },
  mismatch: {
    label: '不符',
    icon: ({ className }) => <AlertTriangle className={className ?? ''} />,
    cls: 'bg-warning/10 text-warning border-warning/30',
  },
  only_settlement: {
    label: '仅交割单',
    icon: ({ className }) => <CircleAlert className={className ?? ''} />,
    cls: 'bg-accent/10 text-accent border-accent/30',
  },
  only_position_log: {
    label: '仅日志',
    icon: ({ className }) => <CircleOff className={className ?? ''} />,
    cls: 'bg-muted/20 text-muted border-muted/30',
  },
}

function num(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function deltaNum(v: number): string {
  if (Math.abs(v) < 1e-6) return '0'
  return `${v > 0 ? '+' : ''}${v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function deltaCls(v: number): string {
  if (Math.abs(v) < 1e-6) return 'text-secondary'
  return v > 0 ? 'text-up' : 'text-down'
}

interface Props {
  onAnalyze?: () => void
}

export function ReconcilePanel({ onAnalyze }: Props) {
  const qc = useQueryClient()
  const [fixing, setFixing] = useState<string | null>(null)

  const q = useQuery({
    queryKey: QK.reconcile,
    queryFn: api.reconcileList,
  })

  const items = q.data?.items ?? []
  const summary = q.data?.summary

  const fixMut = useMutation({
    mutationFn: ({ symbol, action }: { symbol: string; action: 'fix' | 'delete' }) =>
      api.reconcileFix(symbol, action),
    onMutate: ({ symbol }) => setFixing(symbol),
    onSettled: () => setFixing(null),
    onSuccess: (data, { action }) => {
      qc.invalidateQueries({ queryKey: QK.reconcile })
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      const label = action === 'fix' ? '修正' : '删除'
      toast(`${data.symbol} ${label}成功`, 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const handleFix = (symbol: string) => {
    if (!confirm(`确认按交割单修正 ${symbol} 的持仓？`)) return
    fixMut.mutate({ symbol, action: 'fix' })
  }

  const handleDelete = (symbol: string) => {
    if (!confirm(`确认删除 ${symbol} 的全部操作日志？此操作不可撤销。`)) return
    fixMut.mutate({ symbol, action: 'delete' })
  }

  const handleRefresh = () => {
    qc.invalidateQueries({ queryKey: QK.reconcile })
  }

  // ===== 渲染 =====
  return (
    <div className="rounded-card border border-border bg-panel">
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Scale className="h-3.5 w-3.5 text-muted" />
        <span className="text-xs font-medium text-foreground">对账</span>
        <span className="font-mono text-[10px] text-muted">
          ({summary?.total ?? 0})
        </span>
        <button
          onClick={handleRefresh}
          disabled={q.isFetching}
          className="ml-auto p-1 text-muted hover:text-foreground transition-colors"
          title="刷新"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', q.isFetching && 'animate-spin')} />
        </button>
        {onAnalyze && (
          <button
            onClick={onAnalyze}
            className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white text-[11px] font-medium hover:opacity-90 transition-opacity"
            title="AI 分析当前对账与持仓"
          >
            <Sparkles className="h-3 w-3" />
            AI 分析
          </button>
        )}
      </div>

      {/* 汇总卡片 */}
      {summary && (
        <div className="grid grid-cols-4 gap-2 px-4 py-3 border-b border-border bg-surface/40">
          <SummaryBadge label="一致" count={summary.matched} cls="text-up bg-up/5" />
          <SummaryBadge label="不符" count={summary.mismatch} cls="text-warning bg-warning/5" />
          <SummaryBadge label="仅交割单" count={summary.only_settlement} cls="text-accent bg-accent/5" />
          <SummaryBadge label="仅日志" count={summary.only_position_log} cls="text-muted bg-muted/5" />
        </div>
      )}

      {/* 加载中 */}
      {q.isLoading && (
        <div className="flex items-center justify-center gap-2 py-12 text-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-xs">正在对账…</span>
        </div>
      )}

      {/* 空状态 */}
      {!q.isLoading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted">
          <Scale className="h-8 w-8 opacity-30" strokeWidth={1.5} />
          <span className="text-xs">暂无对账数据</span>
          <span className="text-[10px] text-muted/60">导入交割单后自动对账</span>
        </div>
      )}

      {/* 对账表格 */}
      {!q.isLoading && items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted">
                <th className="px-3 py-2 text-left font-medium">标的</th>
                <th className="px-3 py-2 text-right font-medium">交割单持仓</th>
                <th className="px-3 py-2 text-right font-medium">日志持仓</th>
                <th className="px-3 py-2 text-right font-medium">股数差</th>
                <th className="px-3 py-2 text-right font-medium">成本差</th>
                <th className="px-3 py-2 text-center font-medium">状态</th>
                <th className="px-3 py-2 text-right font-medium w-28">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <ReconRow
                  key={item.symbol}
                  item={item}
                  fixing={fixing === item.symbol}
                  onFix={() => handleFix(item.symbol)}
                  onDelete={() => handleDelete(item.symbol)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SummaryBadge({ label, count, cls }: { label: string; count: number; cls: string }) {
  return (
    <div className={cn('flex flex-col items-center rounded-lg px-2 py-1.5', cls)}>
      <span className="text-[10px] opacity-70">{label}</span>
      <span className="font-mono text-sm font-bold tabular-nums">{count}</span>
    </div>
  )
}

function ReconRow({
  item,
  fixing,
  onFix,
  onDelete,
}: {
  item: ReconItem
  fixing: boolean
  onFix: () => void
  onDelete: () => void
}) {
  const cfg = DIFF_CONFIG[item.diff_type]
  const Icon = cfg.icon
  const canFix = item.diff_type === 'only_settlement' || item.diff_type === 'mismatch'
  const canDelete = item.diff_type !== 'matched'

  return (
    <tr className="border-t border-border/50 hover:bg-elevated/30 transition-colors">
      {/* 标的 */}
      <td className="px-3 py-2">
        <div className="flex flex-col">
          <span className="font-mono text-xs text-foreground">{item.symbol}</span>
          {item.name && item.name !== item.symbol && (
            <span className="text-[10px] text-secondary">{item.name}</span>
          )}
        </div>
      </td>
      {/* 交割单持仓 */}
      <td className="px-3 py-2 text-right tabular-nums">
        {item.settlement_pos ? (
          <div className="flex flex-col items-end">
            <span className="text-foreground">{num(item.settlement_pos.shares)} 股</span>
            <span className="text-[10px] text-secondary">{num(item.settlement_pos.cost_price)}</span>
          </div>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      {/* 日志持仓 */}
      <td className="px-3 py-2 text-right tabular-nums">
        {item.log_pos ? (
          <div className="flex flex-col items-end">
            <span className="text-foreground">{num(item.log_pos.shares)} 股</span>
            <span className="text-[10px] text-secondary">{num(item.log_pos.cost_price)}</span>
          </div>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
      {/* 股数差 */}
      <td className={cn('px-3 py-2 text-right tabular-nums font-medium', deltaCls(item.shares_delta))}>
        {deltaNum(item.shares_delta)}
      </td>
      {/* 成本差 */}
      <td className={cn('px-3 py-2 text-right tabular-nums font-medium', deltaCls(item.cost_delta))}>
        {deltaNum(item.cost_delta)}
      </td>
      {/* 状态 */}
      <td className="px-3 py-2 text-center">
        <span className={cn(
          'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
          cfg.cls,
        )}>
          <Icon className="h-3 w-3" />
          {cfg.label}
        </span>
      </td>
      {/* 操作 */}
      <td className="px-3 py-2">
        <div className="flex items-center justify-end gap-1">
          {canFix && (
            <button
              disabled={fixing}
              onClick={onFix}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-accent hover:bg-accent/10 disabled:opacity-40 transition-colors"
              title="按交割单修正"
            >
              {fixing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
              修正
            </button>
          )}
          {canDelete && (
            <button
              disabled={fixing}
              onClick={onDelete}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted hover:text-danger hover:bg-danger/5 disabled:opacity-40 transition-colors"
              title="删除日志"
            >
              <Trash2 className="h-3 w-3" />
              删除
            </button>
          )}
          {!canFix && !canDelete && (
            <span className="text-[10px] text-muted">—</span>
          )}
        </div>
      </td>
    </tr>
  )
}