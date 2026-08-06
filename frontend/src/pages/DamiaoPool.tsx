import React, { useMemo, useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Pencil, Flag, ArrowRightLeft, X, Settings2, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, type DamiaoCategory, type DamiaoPoolEntry, type KlineRow, type MinuteKlineRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtPrice, priceColorClass } from '@/lib/format'
import { boardTag, renderBuiltinDataCell } from '@/components/stock-table/primitives'
import { getSignals, signalCls } from '@/lib/stock-table'
import { MiniCandlestick } from '@/components/stock-table/MiniCandlestick'
import { MiniIntraday } from '@/components/stock-table/MiniIntraday'
import { resolveCandleConfig, resolveIntradayConfig } from '@/lib/list-columns'
import { useCapabilities } from '@/lib/useSharedQueries'
import { ListColumnCustomizer } from '@/components/ListColumnCustomizer'
import { StockSearchSelect } from '@/components/StockSearchSelect'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import {
  COLUMN_GROUPS, loadColumnConfig, saveColumnConfig,
  type ColumnConfig,
} from '@/lib/damiao-columns'

const inputCls = 'h-9 px-3 rounded-lg border border-border bg-elevated text-sm text-foreground outline-none focus:border-accent transition-colors'
const btnPrimary = 'inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-40 transition-colors'
const btnGhost = 'inline-flex items-center h-9 px-3 rounded-lg border border-border text-sm text-secondary hover:text-foreground transition-colors'

// 分类标签定义
const CATEGORY_LABEL: Record<string, string> = {
  new_watch: '新观察',
  new_open: '新开仓',
  holding_todo: '持仓处理',
  old_deng: '老登票',
  t_add: '可踢',
  take_profit: '止盈',
  stop_loss: '止损',
  closed: '已清仓',
}
const CATEGORY_CLASS: Record<string, string> = {
  new_watch: 'text-blue-400 bg-blue-400/12',
  new_open: 'text-rose-400 bg-rose-400/12',
  holding_todo: 'text-amber-400 bg-amber-400/12',
  old_deng: 'text-slate-400 bg-slate-400/15',
  t_add: 'text-cyan-400 bg-cyan-400/12',
  take_profit: 'text-rose-400 bg-rose-400/15',
  stop_loss: 'text-green-400 bg-green-400/15',
  closed: 'text-slate-400 bg-slate-400/20',
}
const EXIT_CATEGORIES = new Set(['take_profit', 'stop_loss', 'closed'])
const WATCH_CATEGORIES = ['new_watch', 'new_open', 'holding_todo', 'old_deng', 't_add'] as const

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 从一行取现价
function priceOf(r: any) { return r.close }

export function DamiaoPool() {
  const qc = useQueryClient()
  const navigate = useNavigate()

  const [columns, setColumns] = useState<ColumnConfig[]>(() => loadColumnConfig())
  const [customizerOpen, setCustomizerOpen] = useState(false)
  const [hideExited, setHideExited] = useState(true)
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [activeTab, setActiveTab] = useState<string>('all') // 'all' | date | 'exited'

  // 新增表单
  const [form, setForm] = useState({
    symbol: '', source_date: todayStr(), category: 'new_watch' as DamiaoCategory,
    strategy: '', note: '', anchor_price: '' as string | number,
  })

  // 编辑/收官弹层
  const [editing, setEditing] = useState<DamiaoPoolEntry | null>(null)
  const [exiting, setExiting] = useState<DamiaoPoolEntry | null>(null)

  // 个股预览弹窗(复用自选页 StockPreviewDialog)
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [previewName, setPreviewName] = useState<string>('')
  const openPreview = (sym: string, name?: string | null) => {
    setPreviewSymbol(sym); setPreviewName(name ?? '')
  }
  const closePreview = () => { setPreviewSymbol(null); setPreviewName('') }

  const list = useQuery({ queryKey: QK.damiaoPool, queryFn: api.damiaoPoolList })
  const enriched = useQuery({
    queryKey: QK.damiaoPoolEnriched(),
    queryFn: () => api.damiaoPoolEnriched(),
    enabled: (list.data?.rows.length ?? 0) > 0,
  })

  const rows = useMemo(() => {
    const poolRows = list.data?.rows ?? []
    const quoteRows = enriched.data?.rows ?? []
    // 后端 enriched 已按 pool 顺序返回并拼回了 pool 字段
    if (quoteRows.length === poolRows.length) {
      return quoteRows
    }
    // 回退:仅 pool 元数据
    return poolRows
  }, [list.data, enriched.data])

  // ===== 日K / 分时图表列(复用自选页口径) =====
  const candleColumn = useMemo(() =>
    columns.find(c => c.source.type === 'builtin' && c.source.key === 'candle' && c.visible),
    [columns])
  const candleResolved = useMemo(() => resolveCandleConfig(candleColumn?.candleConfig), [candleColumn])
  const candleDays = candleResolved.days
  const candleSize = { width: candleResolved.enabledWidth, height: candleResolved.enabledHeight }
  const dailyKVisible = !!candleColumn

  const intradayColumn = useMemo(() =>
    columns.find(c => c.source.type === 'builtin' && c.source.key === 'intraday' && c.visible),
    [columns])
  const intradayResolved = useMemo(() => resolveIntradayConfig(intradayColumn?.intradayConfig), [intradayColumn])
  const caps = useCapabilities()
  const hasMinuteBatch = !!caps.data?.capabilities?.['kline.minute.batch']
  const intradayVisible = !!intradayColumn && hasMinuteBatch

  const chartSymbols = useMemo(() => {
    const set = new Set<string>()
    if (dailyKVisible || intradayVisible) rows.forEach(r => set.add(r.symbol))
    return [...set]
  }, [rows, dailyKVisible, intradayVisible])
  const chartSymbolsKey = chartSymbols.join(',')

  const klineBatch = useQuery({
    queryKey: QK.watchlistKlineBatch(`${chartSymbolsKey}|${candleDays}`),
    queryFn: () => api.klineDailyBatch(chartSymbols, candleDays),
    enabled: dailyKVisible && chartSymbols.length > 0,
    staleTime: 5 * 60_000,
  })
  const klineData: Record<string, KlineRow[]> = dailyKVisible ? (klineBatch.data?.data ?? {}) : {}

  const minuteBatch = useQuery({
    queryKey: QK.minuteBatch(chartSymbolsKey),
    queryFn: () => api.klineMinuteBatch(chartSymbols),
    enabled: intradayVisible && chartSymbols.length > 0,
    staleTime: 60_000,
  })
  const minuteData: Record<string, MinuteKlineRow[]> = intradayVisible ? (minuteBatch.data?.data ?? {}) : {}

  const addMut = useMutation({
    mutationFn: () => api.damiaoPoolAdd({
      symbol: form.symbol.trim(),
      source_date: form.source_date,
      category: form.category,
      strategy: form.strategy.trim(),
      note: form.note.trim(),
      anchor_price: form.anchor_price === '' ? undefined : Number(form.anchor_price),
    }),
    onSuccess: (data) => {
      qc.setQueryData(QK.damiaoPool, { rows: data.rows })
      qc.invalidateQueries({ queryKey: QK.damiaoPool })
      qc.invalidateQueries({ queryKey: ['damiao-pool-enriched'] })
      setForm(f => ({ ...f, symbol: '', strategy: '', note: '', anchor_price: '' }))
    },
  })

  const updateMut = useMutation({
    mutationFn: (vars: { id: string; body: any }) => api.damiaoPoolUpdate(vars.id, vars.body),
    onSuccess: (data) => {
      qc.setQueryData(QK.damiaoPool, { rows: data.rows })
      qc.invalidateQueries({ queryKey: ['damiao-pool-enriched'] })
      setEditing(null)
    },
  })

  const exitMut = useMutation({
    mutationFn: (vars: { id: string; category: string; exit_price: number | null }) =>
      api.damiaoPoolMarkExit(vars.id, vars.category, vars.exit_price),
    onSuccess: (data) => {
      qc.setQueryData(QK.damiaoPool, { rows: data.rows })
      qc.invalidateQueries({ queryKey: ['damiao-pool-enriched'] })
      setExiting(null)
    },
  })

  const removeMut = useMutation({
    mutationFn: (id: string) => api.damiaoPoolRemove(id),
    onSuccess: (data) => {
      qc.setQueryData(QK.damiaoPool, { rows: data.rows })
      qc.invalidateQueries({ queryKey: ['damiao-pool-enriched'] })
    },
  })

  const clearMut = useMutation({
    mutationFn: api.damiaoPoolClear,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.damiaoPool })
      qc.invalidateQueries({ queryKey: ['damiao-pool-enriched'] })
    },
  })

  // 日期标签: distinct source_date 倒序,取最近5个
  const dateTabs = useMemo(() => {
    const dates = Array.from(new Set(rows.map(r => r.source_date).filter(Boolean))) as string[]
    return dates.sort((a, b) => b.localeCompare(a)).slice(0, 5)
  }, [rows])

  const countByDate = useMemo(() => {
    const m: Record<string, number> = {}
    for (const r of rows) {
      if (r.source_date) m[r.source_date] = (m[r.source_date] ?? 0) + 1
    }
    return m
  }, [rows])

  // 过滤后的行
  const filtered = useMemo(() => {
    let out = rows
    if (activeTab === 'exited') {
      out = out.filter(r => EXIT_CATEGORIES.has(r.category))
    } else if (activeTab === 'all') {
      if (hideExited) out = out.filter(r => !EXIT_CATEGORIES.has(r.category))
    } else {
      // 具体日期
      out = out.filter(r => r.source_date === activeTab)
      if (hideExited) out = out.filter(r => !EXIT_CATEGORIES.has(r.category))
    }
    if (categoryFilter !== 'all') {
      out = out.filter(r => r.category === categoryFilter)
    }
    return out
  }, [rows, activeTab, hideExited, categoryFilter])

  // 统计条数据
  const stats = useMemo(() => {
    const valid = filtered.filter(r => {
      const anchor = r.anchor_price
      return anchor != null && !Number.isNaN(anchor)
    })
    const pnls = valid.map(r => {
      const isExit = EXIT_CATEGORIES.has(r.category)
      const exitPrice = r.exit_price
      const ref = isExit && exitPrice != null ? exitPrice : priceOf(r)
      if (ref == null || ref === 0) return null
      return (ref - r.anchor_price) / r.anchor_price
    }).filter((v): v is number => v != null && !Number.isNaN(v))
    const up = pnls.filter(v => v > 0).length
    const down = pnls.filter(v => v < 0).length
    const mean = pnls.length ? pnls.reduce((a, b) => a + b, 0) / pnls.length : null
    let best: { sym?: string; pnl: number } = { pnl: -Infinity }
    let worst: { sym?: string; pnl: number } = { pnl: Infinity }
    valid.forEach(r => {
      const isExit = EXIT_CATEGORIES.has(r.category)
      const ref = isExit && r.exit_price != null ? r.exit_price : priceOf(r)
      if (ref == null || ref === 0 || r.anchor_price == null) return
      const pnl = (ref - r.anchor_price) / r.anchor_price
      if (pnl > best.pnl) best = { sym: r.name || r.symbol, pnl }
      if (pnl < worst.pnl) worst = { sym: r.name || r.symbol, pnl }
    })
    return {
      count: filtered.length,
      mean, up, down,
      winRate: pnls.length ? up / pnls.length : null,
      best: isFinite(best.pnl) ? best : null,
      worst: isFinite(worst.pnl) ? worst : null,
    }
  }, [filtered])

  const visibleColumns = useMemo(() => columns.filter(c => c.visible), [columns])

  const handleColumnsChange = useCallback((next: ColumnConfig[]) => {
    setColumns(next)
    saveColumnConfig(next)
  }, [])

  const entryPct = (r: any): number | null => {
    if (r.anchor_price == null || Number.isNaN(r.anchor_price)) return null
    const isExit = EXIT_CATEGORIES.has(r.category)
    const ref = isExit && r.exit_price != null ? r.exit_price : priceOf(r)
    if (ref == null || ref === 0) return null
    return (ref - r.anchor_price) / r.anchor_price
  }
  const distMa5 = (r: any): number | null => {
    const p = priceOf(r)
    if (p == null || r.ma5 == null || r.ma5 === 0) return null
    return (p - r.ma5) / r.ma5
  }

  // 渲染单元格
  const renderCell = (r: any, col: ColumnConfig) => {
    const key = col.source.type === 'builtin' ? col.source.key : ''
    const numCls = 'px-3 py-2 text-right num tabular-nums'
    if (key === 'symbol') {
      const board = boardTag(r.symbol)
      const isExit = EXIT_CATEGORIES.has(r.category)
      return (
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => openPreview(r.symbol, r.name)}
              className="flex items-center gap-1.5 text-left group"
              title="点击查看个股预览"
            >
              <span className={`font-mono text-xs group-hover:text-accent transition-colors ${isExit ? 'text-muted' : 'text-foreground'}`}>{r.symbol}</span>
              {r.name && <span className={`text-xs truncate group-hover:text-foreground transition-colors ${isExit ? 'text-muted/70' : 'text-secondary'}`}>{r.name}</span>}
              {board && <span className={`shrink-0 inline-flex items-center justify-center w-[18px] h-[18px] rounded text-[9px] font-bold leading-none border ${board.color}`}>{board.label}</span>}
            </button>
          </div>
        </td>
      )
    }
    if (key === 'category') {
      return (
        <td className="px-3 py-2 text-center">
          <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-medium ${CATEGORY_CLASS[r.category] ?? 'text-muted bg-elevated'}`}>
            {CATEGORY_LABEL[r.category] ?? r.category}
          </span>
        </td>
      )
    }
    if (key === 'source_date') return <td className="px-3 py-2 text-center text-xs text-secondary">{r.source_date ?? '—'}</td>
    if (key === 'entry_pct') {
      const v = entryPct(r)
      return <td className={`${numCls} font-semibold ${priceColorClass(v)}`}>{v == null ? '—' : <span>{(v > 0 ? '+' : '') + (v * 100).toFixed(2)}%{EXIT_CATEGORIES.has(r.category) ? ' (收官)' : ''}</span>}</td>
    }
    if (key === 'dist_ma5') {
      const v = distMa5(r)
      return <td className={`${numCls} ${priceColorClass(v)}`}>{v == null ? '—' : `${(v > 0 ? '+' : '') + (v * 100).toFixed(2)}%`}</td>
    }
    if (key === 'anchor_price') return <td className={numCls}>{r.anchor_price != null ? fmtPrice(r.anchor_price) : <span className="text-muted">—</span>}</td>
    if (key === 'exit_price') return <td className={numCls}>{r.exit_price != null ? fmtPrice(r.exit_price) : '—'}</td>
    if (key === 'strategy') return <td className="px-3 py-2 text-xs text-secondary max-w-[220px] truncate" title={r.strategy}>{r.strategy || '—'}</td>
    if (key === 'candle') {
      return (
        <td className="pl-2 pr-3 py-1.5" style={{ width: candleSize.width + 4, minWidth: candleSize.width + 4, maxWidth: candleSize.width + 4, height: candleSize.height }}>
          <MiniCandlestick rows={klineData[r.symbol] ?? []} width={candleSize.width} height={candleSize.height} />
        </td>
      )
    }
    if (key === 'intraday') {
      const mRows: MinuteKlineRow[] = minuteData[r.symbol] ?? []
      const iw = intradayResolved.width
      const ih = intradayResolved.height
      return (
        <td className="pl-3 pr-2 py-1.5" style={{ width: iw + 4, minWidth: iw + 4, maxWidth: iw + 4, height: ih }}>
          <div className="flex items-center justify-center">
            {intradayVisible
              ? <MiniIntraday rows={mRows} prevClose={r.prev_close} changePct={r.change_pct} width={iw - 4} height={ih} />
              : <span className="text-[10px] text-muted">分时</span>}
          </div>
        </td>
      )
    }
    if (key === 'note') return <td className="px-3 py-2 text-xs text-secondary max-w-[160px] truncate" title={r.note}>{r.note || '—'}</td>
    if (key === 'signals') {
      const signals = getSignals(r)
      return (
        <td className="px-3 py-2">
          {signals.length > 0 ? (
            <div className="flex flex-wrap gap-0.5">
              {signals.slice(0, 3).map(s => <span key={s.label} className={`inline-block px-1.5 py-px rounded text-[10px] font-medium leading-tight ${signalCls(s.type)}`}>{s.label}</span>)}
            </div>
          ) : <span className="text-muted">—</span>}
        </td>
      )
    }
    // 其余通用内置列复用自选页渲染口径
    const builtin = renderBuiltinDataCell(r, col)
    if (builtin) return builtin
    return <td className="px-3 py-2 text-muted text-center">—</td>
  }

  return (
    <div className="p-4 md:p-5">
      <PageHeader
        title="大喵观察票池"
        subtitle="追踪群主每日预案 · 按推荐事件记录 · 自动锚定入池价"
        right={
          <button onClick={() => setCustomizerOpen(true)} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors">
            <Settings2 className="h-3.5 w-3.5" /> 列
          </button>
        }
      />

      {/* 新增表单 */}
      <div className="mt-4 p-3 rounded-card border border-border bg-panel flex flex-wrap items-center gap-2">
        <StockSearchSelect
          value={form.symbol}
          onSelect={(sym) => setForm(f => ({ ...f, symbol: sym }))}
          existingSymbols={rows.map(r => r.symbol)}
          placeholder="搜索代码/名称"
          widthClass="w-56"
        />
        <input type="date" className={`${inputCls} w-36`} value={form.source_date} onChange={e => setForm(f => ({ ...f, source_date: e.target.value }))} />
        <select className={`${inputCls} w-28`} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value as DamiaoCategory }))}>
          {WATCH_CATEGORIES.map(c => <option key={c} value={c}>{CATEGORY_LABEL[c]}</option>)}
        </select>
        <input className={`${inputCls} flex-1 min-w-[180px]`} placeholder="策略提示，如 五日线可低吸" value={form.strategy} onChange={e => setForm(f => ({ ...f, strategy: e.target.value }))} />
        <input className={`${inputCls} w-24`} type="number" step="0.01" placeholder="锚定价(可空)" value={form.anchor_price} onChange={e => setForm(f => ({ ...f, anchor_price: e.target.value }))} />
        <button
          className={btnPrimary}
          disabled={addMut.isPending || !form.symbol.trim()}
          onClick={() => addMut.mutate()}
        >
          <Plus className="h-4 w-4" /> 加入票池
        </button>
      </div>

      {/* 标签页 */}
      <div className="mt-4 flex items-center gap-1 border-b border-border overflow-x-auto">
        <TabButton active={activeTab === 'all'} onClick={() => setActiveTab('all')}>全部 <Count n={rows.filter(r => !EXIT_CATEGORIES.has(r.category)).length} /></TabButton>
        {dateTabs.map(d => (
          <TabButton key={d} active={activeTab === d} onClick={() => setActiveTab(d)}>
            {d.slice(5)} <Count n={countByDate[d] ?? 0} />
          </TabButton>
        ))}
        <TabButton active={activeTab === 'exited'} onClick={() => setActiveTab('exited')}>已收官 <Count n={rows.filter(r => EXIT_CATEGORIES.has(r.category)).length} /></TabButton>
      </div>

      {/* 统计条 */}
      <div className="mt-3 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Stat label="只数" value={String(stats.count)} sub={`${stats.up + stats.down > 0 ? `涨${stats.up} 跌${stats.down}` : '—'}`} />
        <Stat label="平均入池盈亏" value={stats.mean == null ? '—' : `${(stats.mean > 0 ? '+' : '') + (stats.mean * 100).toFixed(2)}%`} valueClass={priceColorClass(stats.mean)} />
        <Stat label="胜率" value={stats.winRate == null ? '—' : `${(stats.winRate * 100).toFixed(1)}%`} valueClass={stats.winRate != null && stats.winRate >= 0.5 ? 'text-bull' : 'text-bear'} sub={`${stats.up} / ${stats.up + stats.down}`} />
        <Stat label="上涨/下跌" value={<span><span className="text-bull">{stats.up}</span><span className="text-muted"> / </span><span className="text-bear">{stats.down}</span></span>} />
        <Stat label="最佳" value={stats.best ? stats.best.sym ?? '—' : '—'} valueClass="text-bull" sub={stats.best ? `+${(stats.best.pnl * 100).toFixed(2)}%` : ''} />
        <Stat label="最差" value={stats.worst ? stats.worst.sym ?? '—' : '—'} valueClass="text-bear" sub={stats.worst ? `${(stats.worst.pnl * 100).toFixed(2)}%` : ''} />
      </div>

      {/* 分类筛选 */}
      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <span className="text-xs text-muted">分类：</span>
        <FilterChip active={categoryFilter === 'all'} onClick={() => setCategoryFilter('all')}>全部</FilterChip>
        {WATCH_CATEGORIES.map(c => (
          <FilterChip key={c} active={categoryFilter === c} onClick={() => setCategoryFilter(c)}>{CATEGORY_LABEL[c]}</FilterChip>
        ))}
        <label className="ml-auto inline-flex items-center gap-1.5 text-xs text-secondary cursor-pointer">
          <input type="checkbox" checked={hideExited} onChange={e => setHideExited(e.target.checked)} /> 隐藏已收官
        </label>
        {rows.length > 0 && (
          <button className="text-xs text-muted hover:text-danger transition-colors" onClick={() => { if (confirm('确认清空票池？此操作不可恢复。')) clearMut.mutate() }}>清空</button>
        )}
      </div>

      {/* 表格 */}
      {filtered.length === 0 ? (
        <EmptyState title="票池是空的" hint="在上方输入代码，把群主提及的个股加入观察。" />
      ) : (
        <div className="mt-3 rounded-card border border-border overflow-x-auto bg-panel">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {visibleColumns.map(col => (
                  <th key={col.id} className={`px-3 py-2.5 font-medium text-muted text-xs whitespace-nowrap ${col.align === 'left' ? 'text-left' : col.align === 'right' ? 'text-right' : 'text-center'}`}>{col.label}</th>
                ))}
                <th className="px-3 py-2.5 text-right text-muted text-xs w-32">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => {
                const isExit = EXIT_CATEGORIES.has(r.category)
                return (
                  <tr key={r.id} className={`border-t border-border hover:bg-elevated/40 transition-colors ${isExit ? 'opacity-60' : ''}`}>
                    {visibleColumns.map(col => <React.Fragment key={col.id}>{renderCell(r, col)}</React.Fragment>)}
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1 text-xs">
                        <button className="p-1 text-muted hover:text-accent" title="编辑" onClick={() => setEditing(r)}><Pencil className="h-3.5 w-3.5" /></button>
                        {!isExit && <button className="p-1 text-muted hover:text-amber-400" title="收官" onClick={() => setExiting(r)}><Flag className="h-3.5 w-3.5" /></button>}
                        <button className="p-1 text-muted hover:text-accent" title="转入持仓" onClick={() => navigate('/positions', { state: { symbol: r.symbol, anchor_price: r.anchor_price } })}><ArrowRightLeft className="h-3.5 w-3.5" /></button>
                        <button className="p-1 text-muted hover:text-danger" title="删除" onClick={() => { if (confirm('删除这条记录？')) removeMut.mutate(r.id) }}><Trash2 className="h-3.5 w-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 列自定义 */}
      <ListColumnCustomizer
        columns={columns}
        groups={COLUMN_GROUPS}
        onChange={handleColumnsChange}
        open={customizerOpen}
        onClose={() => setCustomizerOpen(false)}
        title="自定义列"
        showExtColumns={false}
      />

      {/* 编辑弹层 */}
      {editing && (
        <Modal title="编辑记录" onClose={() => setEditing(null)}>
          <EditForm
            entry={editing}
            onCancel={() => setEditing(null)}
            onSave={(body) => updateMut.mutate({ id: editing.id, body })}
            saving={updateMut.isPending}
          />
        </Modal>
      )}

      {/* 收官弹层 */}
      {exiting && (
        <Modal title="标记收官" onClose={() => setExiting(null)}>
          <ExitForm
            entry={exiting}
            onCancel={() => setExiting(null)}
            onConfirm={(cat, price) => exitMut.mutate({ id: exiting.id, category: cat, exit_price: price })}
            saving={exitMut.isPending}
          />
        </Modal>
      )}

      <StockPreviewDialog
        symbol={previewSymbol}
        name={previewName}
        onClose={closePreview}
      />
    </div>
  )
}

// ===== 小组件 =====

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3.5 py-2 text-sm border-b-2 -mb-px transition-colors whitespace-nowrap flex items-center gap-1.5 ${active ? 'border-accent text-accent font-medium' : 'border-transparent text-muted hover:text-foreground'}`}
    >
      {children}
    </button>
  )
}

function Count({ n }: { n: number }) {
  return <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-elevated text-[11px] text-muted tabular-nums">{n}</span>
}

function Stat({ label, value, sub, valueClass = '' }: { label: string; value: React.ReactNode; sub?: string; valueClass?: string }) {
  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${valueClass}`}>{value}</div>
      {sub && <div className="text-[11px] text-muted mt-0.5">{sub}</div>}
    </div>
  )
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${active ? 'bg-accent/15 border-accent text-accent' : 'border-border text-muted hover:text-foreground'}`}>{children}</button>
  )
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-card border border-border bg-panel p-5 shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="p-1 text-muted hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>
        {children}
      </div>
    </div>
  )
}

function EditForm({ entry, onSave, onCancel, saving }: { entry: DamiaoPoolEntry; onSave: (b: any) => void; onCancel: () => void; saving: boolean }) {
  const [source_date, setSourceDate] = useState(entry.source_date)
  const [category, setCategory] = useState(entry.category)
  const [strategy, setStrategy] = useState(entry.strategy)
  const [anchor, setAnchor] = useState(entry.anchor_price ?? '')
  const [note, setNote] = useState(entry.note)
  return (
    <div className="space-y-3">
      <Field label="代码"><input className={`${inputCls} w-full`} value={`${entry.symbol} ${entry.name ?? ''}`} disabled /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="提及日期"><input type="date" className={`${inputCls} w-full`} value={source_date} onChange={e => setSourceDate(e.target.value)} /></Field>
        <Field label="分类">
          <select className={`${inputCls} w-full`} value={category} onChange={e => setCategory(e.target.value as DamiaoCategory)}>
            {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
      </div>
      <Field label="锚定价"><input type="number" step="0.01" className={`${inputCls} w-full`} value={anchor} onChange={e => setAnchor(e.target.value)} placeholder="入池价" /></Field>
      <Field label="策略提示"><input className={`${inputCls} w-full`} value={strategy} onChange={e => setStrategy(e.target.value)} /></Field>
      <Field label="备注"><input className={`${inputCls} w-full`} value={note} onChange={e => setNote(e.target.value)} /></Field>
      <div className="flex justify-end gap-2 pt-2">
        <button className={btnGhost} onClick={onCancel}>取消</button>
        <button className={btnPrimary} disabled={saving} onClick={() => onSave({ source_date, category, strategy, note, anchor_price: anchor === '' ? null : Number(anchor) })}><Check className="h-4 w-4" /> 保存</button>
      </div>
    </div>
  )
}

function ExitForm({ entry, onConfirm, onCancel, saving }: { entry: DamiaoPoolEntry; onConfirm: (cat: string, price: number | null) => void; onCancel: () => void; saving: boolean }) {
  const [category, setCategory] = useState('take_profit')
  const [price, setPrice] = useState(entry.anchor_price ?? '')
  return (
    <div className="space-y-3">
      <div className="text-sm text-secondary">
        {entry.symbol} {entry.name ?? ''} · 锚定价 <span className="text-foreground font-medium">{entry.anchor_price != null ? fmtPrice(entry.anchor_price) : '—'}</span>
      </div>
      <Field label="收官类型">
        <select className={`${inputCls} w-full`} value={category} onChange={e => setCategory(e.target.value)}>
          <option value="take_profit">止盈</option>
          <option value="stop_loss">止损</option>
          <option value="closed">已清仓</option>
        </select>
      </Field>
      <Field label="收官价（可空）"><input type="number" step="0.01" className={`${inputCls} w-full`} value={price} onChange={e => setPrice(e.target.value)} placeholder="卖出价" /></Field>
      <div className="flex justify-end gap-2 pt-2">
        <button className={btnGhost} onClick={onCancel}>取消</button>
        <button className={btnPrimary} disabled={saving} onClick={() => onConfirm(category, price === '' ? null : Number(price))}>确认收官</button>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs text-muted mb-1">{label}</span>
      {children}
    </label>
  )
}
