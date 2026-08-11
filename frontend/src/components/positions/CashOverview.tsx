/**
 * 现金概览 —— 展示可用资金、持仓市值、总资产，并支持内联编辑可用资金。
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Wallet, Pencil, Check, X } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtBigNum } from '@/lib/format'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

interface Props {
  marketValue: number
}

function money(v: number) {
  return `¥${fmtBigNum(v)}`
}

export function CashOverview({ marketValue }: Props) {
  const qc = useQueryClient()
  const cashQuery = useQuery({
    queryKey: QK.positionCash,
    queryFn: api.positionGetCash,
  })
  const cash = cashQuery.data?.free_cash ?? 0
  const totalAssets = cash + marketValue

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(cash))

  const saveMut = useMutation({
    mutationFn: (v: number) => api.positionSetCash(v),
    onSuccess: (d) => {
      qc.setQueryData(QK.positionCash, { free_cash: d.free_cash })
      setEditing(false)
      toast('可用资金已更新', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const startEdit = () => { setDraft(String(cash)); setEditing(true) }
  const commit = () => {
    const v = Number(draft)
    if (!Number.isFinite(v) || v < 0) {
      toast('请输入有效的金额', 'error')
      return
    }
    saveMut.mutate(v)
  }

  return (
    <div className="flex flex-wrap items-center gap-6 rounded-card border border-border bg-gradient-to-r from-sky-500/[0.08] via-accent/5 to-transparent p-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-sky-500/15 border border-sky-500/30 text-sky-400">
          <Wallet className="h-4 w-4" />
        </span>
        <div>
          <div className="text-[11px] text-muted">可用资金</div>
          {editing ? (
            <div className="flex items-center gap-1">
              <input
                autoFocus
                type="number"
                step="0.01"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
                className="h-7 w-32 rounded border border-border bg-elevated px-2 text-sm font-mono tabular-nums outline-none focus:border-accent"
              />
              <button onClick={commit} className="p-1 text-bear hover:opacity-80"><Check className="h-3.5 w-3.5" /></button>
              <button onClick={() => setEditing(false)} className="p-1 text-muted hover:text-foreground"><X className="h-3.5 w-3.5" /></button>
            </div>
          ) : (
            <button
              onClick={startEdit}
              className="group flex items-center gap-1 text-lg font-bold tabular-nums text-foreground"
              title="点击修改可用资金"
            >
              {money(cash)}
              <Pencil className="h-3 w-3 text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
          )}
        </div>
      </div>

      <div className="h-8 w-px bg-border" />
      <Stat label="持仓市值" value={money(marketValue)} />
      <div className="h-8 w-px bg-border" />
      <Stat label="总资产" value={money(totalAssets)} accent />
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className={cn('mt-0.5 text-lg font-bold tabular-nums', accent && 'text-accent')}>{value}</div>
    </div>
  )
}
