/**
 * 交割单记录列表 —— 统计行 + 分页明细 + 一键清空。
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, Loader2, FileText, ChevronLeft, ChevronRight, BarChart3, Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { SettlementCharts } from './SettlementCharts'

const PAGE_SIZE = 50

function money(v: number) {
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface Props {
  /** 点击 AI 分析按钮时的回调（由父组件触发持仓/交割单复盘） */
  onAnalyze?: () => void
}

export function SettlementRecords({ onAnalyze }: Props) {
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [showCharts, setShowCharts] = useState(false)

  const q = useQuery({
    queryKey: QK.settlementRecords({ page, size: PAGE_SIZE }),
    queryFn: () => api.settlementRecords({ page, size: PAGE_SIZE }),
  })

  const clearMut = useMutation({
    mutationFn: () => api.settlementClear(),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: QK.settlementRecords() })
      qc.invalidateQueries({ queryKey: QK.settlementStats })
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      toast(`已清空 ${d.removed} 条交割单`, 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const rows = q.data?.rows ?? []
  const total = q.data?.total ?? 0
  const summary = q.data?.summary
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="rounded-card border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <FileText className="h-3.5 w-3.5 text-muted" />
        <span className="text-xs font-medium text-foreground">交割单记录</span>
        <span className="font-mono text-[10px] text-muted">({total})</span>
        {total > 0 && (
          <>
            {onAnalyze && (
              <button
                onClick={onAnalyze}
                className="ml-auto inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white text-[11px] font-medium hover:opacity-90 transition-opacity"
                title="AI 分析交易记录（基于交割单+持仓的完整复盘）"
              >
                <Sparkles className="h-3 w-3" />
                AI 分析
              </button>
            )}
            <button
              onClick={() => setShowCharts(v => !v)}
              className="ml-auto inline-flex items-center gap-1 text-xs text-muted hover:text-foreground transition-colors"
              title="图表分析"
            >
              <BarChart3 className="h-3.5 w-3.5" />
              图表
            </button>
            <button
              disabled={clearMut.isPending}
              onClick={() => {
                if (confirm('确认清空全部交割单？将同时删除由交割单生成的持仓记录，此操作不可撤销。')) {
                  clearMut.mutate()
                }
              }}
              className="inline-flex items-center gap-1 text-xs text-muted hover:text-danger transition-colors disabled:opacity-40"
            >
              {clearMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              一键清空
            </button>
          </>
        )}
      </div>

      {/* 统计 */}
      {summary && summary.count > 0 && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-b border-border/60 px-4 py-2.5 text-[11px]">
          <Stat label="买入" value={`${summary.buy_count} 笔 / ¥${money(summary.buy_amount)}`} cls="text-bull" />
          <Stat label="卖出" value={`${summary.sell_count} 笔 / ¥${money(summary.sell_amount)}`} cls="text-bear" />
          <Stat label="佣金" value={`¥${money(summary.commission)}`} />
          <Stat label="印花税" value={`¥${money(summary.stamp_duty)}`} />
          <Stat label="过户费" value={`¥${money(summary.transfer_fee)}`} />
          <Stat label="费用合计" value={`¥${money(summary.total_fees)}`} cls="text-warning" />
        </div>
      )}

      {/* 图表 */}
      {showCharts && <SettlementCharts />}

      {/* 列表 */}
      {q.isLoading ? (
        <div className="grid h-24 place-items-center"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
      ) : rows.length === 0 ? (
        <div className="px-4 py-10 text-center text-xs text-muted">暂无交割单，请先在上方导入</div>
      ) : (
        <>
          <div className="max-h-[480px] overflow-auto thin-scrollbar">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-elevated/95 backdrop-blur-sm">
                <tr className="text-muted">
                  <th className="px-3 py-2 text-left font-medium">日期</th>
                  <th className="px-3 py-2 text-left font-medium">代码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-center font-medium">方向</th>
                  <th className="px-3 py-2 text-right font-medium">价格</th>
                  <th className="px-3 py-2 text-right font-medium">数量</th>
                  <th className="px-3 py-2 text-right font-medium">成交额</th>
                  <th className="px-3 py-2 text-right font-medium">费用</th>
                  <th className="px-3 py-2 text-right font-medium">发生额</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const fees = r.commission + r.stamp_duty + r.transfer_fee
                  return (
                    <tr key={r.id} className="border-t border-border/60 hover:bg-elevated/40 transition-colors">
                      <td className="px-3 py-1.5 text-secondary">{r.trade_date}</td>
                      <td className="px-3 py-1.5 font-mono text-foreground">{r.symbol}</td>
                      <td className="px-3 py-1.5 text-secondary truncate max-w-[120px]">{r.name}</td>
                      <td className="px-3 py-1.5 text-center">
                        <span className={cn(
                          'rounded px-1.5 py-0.5 text-[10px] font-medium',
                          r.direction === '买入' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear',
                        )}>{r.direction}</span>
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono num">{r.price.toFixed(3)}</td>
                      <td className="px-3 py-1.5 text-right font-mono num">{r.volume.toLocaleString()}</td>
                      <td className="px-3 py-1.5 text-right font-mono num">{money(r.amount)}</td>
                      <td className="px-3 py-1.5 text-right font-mono num text-secondary">{money(fees)}</td>
                      <td className={cn('px-3 py-1.5 text-right font-mono num', r.net_amount >= 0 ? 'text-bull' : 'text-bear')}>
                        {r.net_amount > 0 ? '+' : ''}{money(r.net_amount)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-end gap-3 border-t border-border/60 px-4 py-2 text-xs text-secondary">
              <span className="font-mono text-[10px] text-muted">{page}/{totalPages}</span>
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="p-1 rounded hover:text-foreground disabled:opacity-30"
              ><ChevronLeft className="h-4 w-4" /></button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => p + 1)}
                className="p-1 rounded hover:text-foreground disabled:opacity-30"
              ><ChevronRight className="h-4 w-4" /></button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, cls = '' }: { label: string; value: string; cls?: string }) {
  return (
    <div>
      <span className="text-muted">{label} </span>
      <span className={cn('font-mono num', cls)}>{value}</span>
    </div>
  )
}
