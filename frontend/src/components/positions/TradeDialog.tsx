/**
 * 交易操作弹窗 —— 买入 / 卖出 / 清仓。
 *
 * 写入 position_log（事件溯源），由后端 FIFO 重新计算持仓并联动可用资金。
 * - 买入：StockSearchSelect 选标的 + 价格 + 数量
 * - 卖出：标的锁定为当前持仓行，数量默认当前持仓
 * - 清仓：价格必填，数量一次性填入当前持仓，需二次确认复选框
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { TrendingUp, TrendingDown, Eraser, Loader2 } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { StockSearchSelect } from '@/components/StockSearchSelect'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

export type TradeMode = 'buy' | 'sell' | 'clear'

interface Props {
  open: boolean
  mode: TradeMode
  onClose: () => void
  /** 卖出/清仓时传入当前持仓；买入时可不传 */
  initialSymbol?: string
  initialName?: string
  initialShares?: number
  initialCost?: number
  existingSymbols?: string[]
}

const MODE_META = {
  buy: {
    title: '买入',
    icon: TrendingUp,
    accent: 'text-bull',
    ring: 'focus:ring-bull/30',
    btn: 'bg-bull hover:bg-bull/90',
    headerBg: 'from-red-500/[0.06] via-red-500/[0.03] to-transparent',
  },
  sell: {
    title: '卖出',
    icon: TrendingDown,
    accent: 'text-bear',
    ring: 'focus:ring-bear/30',
    btn: 'bg-bear hover:bg-bear/90',
    headerBg: 'from-emerald-500/[0.06] via-emerald-500/[0.03] to-transparent',
  },
  clear: {
    title: '清仓',
    icon: Eraser,
    accent: 'text-warning',
    ring: 'focus:ring-warning/30',
    btn: 'bg-warning hover:bg-warning/90',
    headerBg: 'from-amber-500/[0.06] via-amber-500/[0.03] to-transparent',
  },
} as const

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export function TradeDialog({
  open, mode, onClose,
  initialSymbol = '', initialName = '', initialShares = 0, initialCost,
  existingSymbols = [],
}: Props) {
  const qc = useQueryClient()
  const meta = MODE_META[mode]
  const Icon = meta.icon

  const [symbol, setSymbol] = useState(initialSymbol)
  const [name, setName] = useState(initialName)
  const [price, setPrice] = useState('')
  const [volume, setVolume] = useState('')
  const [opDate, setOpDate] = useState(todayStr())
  const [commission, setCommission] = useState('')
  const [confirmClear, setConfirmClear] = useState(false)
  const [error, setError] = useState('')

  // 每次打开重置
  useEffect(() => {
    if (open) {
      setSymbol(initialSymbol)
      setName(initialName)
      setPrice('')
      setVolume(mode === 'sell' && initialShares ? String(initialShares) : '')
      setOpDate(todayStr())
      setCommission('')
      setConfirmClear(false)
      setError('')
    }
  }, [open, initialSymbol, initialName, initialShares, mode])

  const numPrice = parseFloat(price)
  const numVolume = parseFloat(volume)
  const numCommission = parseFloat(commission) || 0

  const amount = useMemo(() => {
    if (Number.isFinite(numPrice) && Number.isFinite(numVolume) && numVolume > 0) {
      return numPrice * numVolume
    }
    return 0
  }, [numPrice, numVolume])

  const canSubmit = useMemo(() => {
    if (!symbol) return false
    if (!(numPrice > 0)) return false
    if (mode === 'clear') return confirmClear
    return numVolume > 0
  }, [symbol, numPrice, numVolume, mode, confirmClear])

  const mutation = useMutation({
    mutationFn: () => {
      const submitVolume = mode === 'clear' ? initialShares || numVolume : numVolume
      return api.positionAddTrade({
        op_type: mode,
        symbol,
        name,
        price: numPrice,
        volume: submitVolume,
        op_date: opDate,
        commission: numCommission,
      })
    },
    onSuccess: () => {
      toast(`${meta.title}已记录`, 'success')
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      qc.invalidateQueries({ queryKey: QK.positionCash })
      onClose()
    },
    onError: (e: Error) => {
      setError(e.message)
    },
  })

  function submit() {
    setError('')
    mutation.mutate()
  }

  const fieldCls = cn(
    'h-9 px-3 rounded-lg border border-border bg-elevated text-sm text-foreground',
    'outline-none transition-colors focus:border-accent',
  )

  return (
    <Modal
      onClose={onClose}
      labelledBy="trade-dialog-title"
      panelClassName="w-[92vw] max-w-md bg-surface border border-border rounded-dialog shadow-2xl overflow-hidden"
    >
      {/* 头部 */}
      <div className={cn('relative px-5 py-3.5 border-b border-border/50 bg-gradient-to-r', meta.headerBg)}>
        <div className="flex items-center gap-3">
          <div className={cn('flex h-9 w-9 items-center justify-center rounded-xl bg-elevated border border-border/60 shrink-0', meta.accent)}>
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div id="trade-dialog-title" className="text-sm font-semibold text-foreground">
              {meta.title}
            </div>
            <div className="text-[11px] text-muted truncate">
              {symbol ? `${name || ''} ${symbol}` : '选择标的并填写成交信息'}
            </div>
          </div>
        </div>
      </div>

      {/* 表单 */}
      <div className="px-5 py-4 space-y-3">
        {/* 标的 */}
        <div>
          <label className="block text-[11px] text-muted mb-1.5">标的</label>
          {mode === 'buy' ? (
            <StockSearchSelect
              value={symbol}
              onSelect={(s, n) => { setSymbol(s); setName(n) }}
              existingSymbols={existingSymbols}
              widthClass="w-full"
            />
          ) : (
            <div className="flex items-center gap-2 h-9 px-3 rounded-lg bg-elevated border border-border text-sm">
              <span className="font-mono text-foreground">{symbol}</span>
              <span className="text-secondary truncate">{name}</span>
              {initialShares > 0 && (
                <span className="ml-auto text-[11px] text-muted">
                  持仓 <span className="font-mono text-foreground">{initialShares}</span>
                </span>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] text-muted mb-1.5">价格</label>
            <input
              type="number"
              step="0.001"
              inputMode="decimal"
              value={price}
              onChange={e => setPrice(e.target.value)}
              placeholder={initialCost != null ? String(initialCost) : '0.00'}
              className={cn(fieldCls, 'w-full', meta.ring)}
            />
          </div>
          <div>
            <label className="block text-[11px] text-muted mb-1.5">
              {mode === 'clear' ? '数量（自动全清）' : '数量'}
            </label>
            <input
              type="number"
              step="100"
              inputMode="decimal"
              value={volume}
              disabled={mode === 'clear'}
              onChange={e => setVolume(e.target.value)}
              placeholder={mode === 'clear' && initialShares ? String(initialShares) : '0'}
              className={cn(fieldCls, 'w-full disabled:opacity-60', meta.ring)}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] text-muted mb-1.5">日期</label>
            <input
              type="date"
              value={opDate}
              onChange={e => setOpDate(e.target.value)}
              className={cn(fieldCls, 'w-full')}
            />
          </div>
          <div>
            <label className="block text-[11px] text-muted mb-1.5">佣金（可选）</label>
            <input
              type="number"
              step="0.01"
              inputMode="decimal"
              value={commission}
              onChange={e => setCommission(e.target.value)}
              placeholder="0.00"
              className={cn(fieldCls, 'w-full')}
            />
          </div>
        </div>

        {/* 成交金额 */}
        {amount > 0 && (
          <div className="flex items-center justify-between rounded-lg bg-elevated/60 px-3 py-2 text-xs">
            <span className="text-muted">成交金额</span>
            <span className="font-mono text-foreground tabular-nums">
              ¥{amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        )}

        {/* 清仓二次确认 */}
        {mode === 'clear' && (
          <label className="flex items-start gap-2 text-[11px] text-secondary cursor-pointer select-none">
            <input
              type="checkbox"
              checked={confirmClear}
              onChange={e => setConfirmClear(e.target.checked)}
              className="mt-0.5 accent-warning"
            />
            <span>我确认以该价格全部卖出 <span className="font-mono text-foreground">{symbol}</span>（{initialShares} 股），此操作不可撤销。</span>
          </label>
        )}

        {error && (
          <div className="rounded-lg bg-danger/10 border border-danger/30 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}
      </div>

      {/* 底部按钮 */}
      <div className="px-5 py-3 border-t border-border/50 flex items-center justify-end gap-2">
        <button
          onClick={onClose}
          className="inline-flex h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors"
        >
          取消
        </button>
        <button
          onClick={submit}
          disabled={!canSubmit || mutation.isPending}
          className={cn(
            'inline-flex items-center gap-1.5 h-8 px-4 rounded-lg text-xs font-medium text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
            meta.btn,
          )}
        >
          {mutation.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          确认{meta.title}
        </button>
      </div>
    </Modal>
  )
}
