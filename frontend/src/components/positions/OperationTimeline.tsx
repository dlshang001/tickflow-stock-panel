/**
 * 操作历史时间线 —— 展示 position_log 中的买卖/清仓记录。
 * 按日期倒序分组，可删除单条日志（删除后后端按剩余日志重算持仓）。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  TrendingUp, TrendingDown, Eraser, Trash2, History, Loader2,
} from 'lucide-react'
import { api, type PositionLog } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

const OP_META = {
  buy: { label: '买入', icon: TrendingUp, dot: 'bg-bull', text: 'text-bull' },
  sell: { label: '卖出', icon: TrendingDown, dot: 'bg-bear', text: 'text-bear' },
  clear: { label: '清仓', icon: Eraser, dot: 'bg-warning', text: 'text-warning' },
  initial: { label: '建仓', icon: TrendingUp, dot: 'bg-accent', text: 'text-accent' },
} as const

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动',
  settlement: '交割单',
  migration: '历史迁移',
}

function money(v: number | null | undefined) {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function OperationTimeline() {
  const qc = useQueryClient()
  const logsQuery = useQuery({
    queryKey: QK.positionLogs(),
    queryFn: () => api.positionLogs(),
  })

  const deleteMut = useMutation({
    mutationFn: api.positionDeleteLog,
    onSuccess: (data) => {
      qc.setQueryData(QK.positions, { rows: data.rows })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      toast('记录已删除', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const logs = logsQuery.data?.logs ?? []

  // 按日期倒序分组
  const grouped = (() => {
    const map = new Map<string, PositionLog[]>()
    for (const log of [...logs].sort((a, b) =>
      (b.op_date + b.id).localeCompare(a.op_date + a.id),
    )) {
      const arr = map.get(log.op_date) ?? []
      arr.push(log)
      map.set(log.op_date, arr)
    }
    return [...map.entries()]
  })()

  return (
    <div className="rounded-card border border-border bg-panel">
      <div className="flex items-center gap-1.5 border-b border-border px-4 py-2.5">
        <History className="h-3.5 w-3.5 text-muted" />
        <span className="text-xs font-medium text-foreground">操作历史</span>
        <span className="font-mono text-[10px] text-muted">({logs.length})</span>
      </div>

      {logsQuery.isLoading ? (
        <div className="grid h-20 place-items-center"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : logs.length === 0 ? (
        <div className="px-4 py-8 text-center text-xs text-muted">暂无交易记录</div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto thin-scrollbar px-4 py-3">
          {grouped.map(([date, items]) => (
            <div key={date} className="relative pb-3 last:pb-0">
              <div className="sticky top-0 z-[1] mb-2 inline-block bg-panel/90 backdrop-blur-sm text-[10px] text-muted px-1.5 py-0.5 rounded">
                {date}
              </div>
              <div className="space-y-1.5">
                {items.map(log => {
                  const meta = OP_META[log.op_type] ?? OP_META.buy
                  const Icon = meta.icon
                  const isSettlement = log.source === 'settlement'
                  return (
                    <div
                      key={log.id}
                      className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-elevated/50 transition-colors"
                    >
                      <span className={cn('grid h-6 w-6 shrink-0 place-items-center rounded-md bg-elevated', meta.text)}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 text-xs">
                          <span className="font-mono text-foreground">{log.symbol}</span>
                          {log.name && <span className="text-secondary truncate">{log.name}</span>}
                          <span className={cn('text-[10px] font-medium', meta.text)}>{meta.label}</span>
                          {log.volume != null && (
                            <span className="font-mono text-[10px] text-muted">{log.volume.toLocaleString()}股</span>
                          )}
                          {log.price != null && (
                            <span className="font-mono text-[10px] text-muted">@{log.price.toFixed(3)}</span>
                          )}
                        </div>
                        {log.amount != null && (
                          <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted">
                            <span className="font-mono">¥{money(log.amount)}</span>
                            {(log.commission || log.stamp_duty || log.transfer_fee) > 0 && (
                              <span className="font-mono">
                                费 {(log.commission + log.stamp_duty + log.transfer_fee).toFixed(2)}
                              </span>
                            )}
                            <span className="rounded bg-elevated px-1 text-[9px]">{SOURCE_LABEL[log.source] ?? log.source}</span>
                            {log.note && <span className="truncate">· {log.note}</span>}
                          </div>
                        )}
                      </div>
                      <button
                        disabled={deleteMut.isPending}
                        onClick={() => {
                          const msg = isSettlement
                            ? '该记录来自交割单，删除后持仓将重算。确定删除？'
                            : `删除这条${meta.label}记录？持仓将按剩余记录重算。`
                          if (confirm(msg)) deleteMut.mutate(log.id)
                        }}
                        className="shrink-0 p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-danger transition-all disabled:opacity-40"
                        title="删除记录"
                      >
                        {deleteMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
