import React, { useMemo, useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Pencil, Check, Crosshair, Settings2, Sparkles, X, Copy, RefreshCw, History } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { api, type PositionEntry, type KlineRow, type MinuteKlineRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtPrice, priceColorClass, fmtBigNum } from '@/lib/format'
import { boardTag, renderBuiltinDataCell } from '@/components/stock-table/primitives'
import { getSignals, signalCls } from '@/lib/stock-table'
import { MiniCandlestick } from '@/components/stock-table/MiniCandlestick'
import { MiniIntraday } from '@/components/stock-table/MiniIntraday'
import { resolveCandleConfig, resolveIntradayConfig } from '@/lib/list-columns'
import { useCapabilities } from '@/lib/useSharedQueries'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'
import { startAnalysis as startStockAnalysis } from '@/lib/stockAnalysisStore'
import { ListColumnCustomizer } from '@/components/ListColumnCustomizer'
import { StockSearchSelect } from '@/components/StockSearchSelect'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { COLUMN_GROUPS, loadColumnConfig, saveColumnConfig, type ColumnConfig } from '@/lib/positions-columns'

const inputCls = 'h-9 px-3 rounded-lg border border-border bg-elevated text-sm text-foreground outline-none focus:border-accent transition-colors'
const btnPrimary = 'inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-40 transition-colors'
const btnGhost = 'inline-flex items-center h-9 px-3 rounded-lg border border-border text-sm text-secondary hover:text-foreground transition-colors'

function priceOf(r: any) { return r.close }

export function Positions() {
  const qc = useQueryClient()
  const location = useLocation() as { state?: { symbol?: string; anchor_price?: number | null } }

  const [columns, setColumns] = useState<ColumnConfig[]>(() => loadColumnConfig())
  const [customizerOpen, setCustomizerOpen] = useState(false)
  const [editing, setEditing] = useState<PositionEntry | null>(null)

  // 个股预览弹窗
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [previewName, setPreviewName] = useState<string>('')
  const openPreview = (sym: string, name?: string | null) => {
    setPreviewSymbol(sym); setPreviewName(name ?? '')
  }
  const closePreview = () => { setPreviewSymbol(null); setPreviewName('') }

  const [form, setForm] = useState({
    symbol: '', shares: '', cost_price: '', opened_at: '', note: '',
  })

  // 从大喵票池「转入持仓」带入
  useEffect(() => {
    const s = location.state
    if (s?.symbol) {
      const sym = s.symbol
      setForm(f => ({
        ...f,
        symbol: sym,
        cost_price: s.anchor_price != null ? String(s.anchor_price) : f.cost_price,
      }))
      window.history.replaceState(null, '')
    }
  }, [location.state])

  const list = useQuery({ queryKey: QK.positions, queryFn: api.positionsList })
  const enriched = useQuery({
    queryKey: QK.positionsEnriched(),
    queryFn: () => api.positionsEnriched(),
    enabled: (list.data?.rows.length ?? 0) > 0,
  })
  const damiaoList = useQuery({ queryKey: QK.damiaoPool, queryFn: api.damiaoPoolList })

  const rows = useMemo(() => {
    const posRows = list.data?.rows ?? []
    const quoteRows = enriched.data?.rows ?? []
    if (quoteRows.length === posRows.length) return quoteRows
    return posRows
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

  const upsertMut = useMutation({
    mutationFn: api.positionsUpsert,
    onSuccess: (data) => {
      qc.setQueryData(QK.positions, { rows: data.rows })
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: ['positions-enriched'] })
      setForm({ symbol: '', shares: '', cost_price: '', opened_at: '', note: '' })
      setEditing(null)
    },
  })
  const updateMut = useMutation({
    mutationFn: (vars: { symbol: string; body: any }) => api.positionsUpdate(vars.symbol, vars.body),
    onSuccess: (data) => {
      qc.setQueryData(QK.positions, { rows: data.rows })
      qc.invalidateQueries({ queryKey: ['positions-enriched'] })
      setEditing(null)
    },
  })
  const removeMut = useMutation({
    mutationFn: api.positionsRemove,
    onSuccess: (data) => {
      qc.setQueryData(QK.positions, { rows: data.rows })
      qc.invalidateQueries({ queryKey: ['positions-enriched'] })
    },
  })
  const clearMut = useMutation({
    mutationFn: api.positionsClear,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: ['positions-enriched'] })
    },
  })

  // 汇总
  const summary = useMemo(() => {
    let marketValue = 0, cost = 0, pnl = 0
    for (const r of rows) {
      const price = priceOf(r)
      const shares = Number(r.shares) || 0
      const costPrice = Number(r.cost_price) || 0
      if (price != null) marketValue += price * shares
      cost += costPrice * shares
      if (price != null) pnl += (price - costPrice) * shares
    }
    const pnlPct = cost > 0 ? pnl / cost : null
    return { marketValue, cost, pnl, pnlPct, count: rows.length }
  }, [rows])

  const totalMv = summary.marketValue

  const bringAnchor = () => {
    const sym = form.symbol.trim()
    if (!sym) return
    const rec = damiaoList.data?.rows.find(r => r.symbol === sym)
    if (rec?.anchor_price != null) {
      setForm(f => ({ ...f, cost_price: String(rec.anchor_price) }))
    }
  }

  // ===== AI 持仓复盘 =====
  const [aiOpen, setAiOpen] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)
  const [aiContent, setAiContent] = useState('')
  const [aiError, setAiError] = useState('')
  const [aiMeta, setAiMeta] = useState<any>(null)
  const [aiFocus, setAiFocus] = useState('')
  const aiAbortRef = useRef<boolean>(false)
  // 历史报告
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyReports, setHistoryReports] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  const loadHistory = async () => {
    setHistoryLoading(true)
    try {
      const res = await api.positionReportsList()
      setHistoryReports(res.reports ?? [])
    } catch {
      setHistoryReports([])
    } finally {
      setHistoryLoading(false)
    }
  }

  const openHistory = () => {
    setHistoryOpen(true)
    loadHistory()
  }

  const openHistoryReport = (report: any) => {
    setAiContent(report.content ?? '')
    setAiMeta(report.summary ?? null)
    setAiFocus(report.focus ?? '')
    setAiError('')
    setAiLoading(false)
    setHistoryOpen(false)
  }

  const deleteHistoryReport = async (id: string) => {
    setHistoryReports(prev => prev.filter(r => r.id !== id))
    try { await api.positionReportDelete(id) } catch { /* 静默 */ }
  }

  const runAiReview = async (focus = '') => {
    if (rows.length === 0) return
    setAiOpen(true)
    setHistoryOpen(false)
    setAiLoading(true)
    setAiContent('')
    setAiError('')
    setAiMeta(null)
    aiAbortRef.current = false
    try {
      let first = true
      for await (const chunk of api.positionAnalyzeStream(focus)) {
        if (aiAbortRef.current) return
        switch (chunk.type) {
          case 'meta':
            setAiMeta(chunk.summary ?? null)
            break
          case 'delta':
            if (first) { setAiLoading(false); first = false }
            setAiContent(c => c + (chunk.content ?? ''))
            break
          case 'error':
            setAiLoading(false)
            setAiError(chunk.message ?? '复盘失败')
            return
          case 'done':
            setAiLoading(false)
            break
        }
      }
      if (first && !aiAbortRef.current) { setAiLoading(false); setAiError('未返回内容,请重试') }
    } catch (e: any) {
      setAiLoading(false)
      setAiError(String(e?.message ?? '复盘失败'))
    }
  }

  const closeAi = () => {
    aiAbortRef.current = true
    setAiOpen(false)
  }

  const analyzeOne = (r: any) => {
    const price = priceOf(r)
    const cost = Number(r.cost_price) || 0
    const shares = Number(r.shares) || 0
    const pnlPct = price != null && cost ? (price - cost) / cost * 100 : null
    const pnlAmt = price != null ? (price - cost) * shares : null
    const context = `我持有该标的,持股${shares}股,成本价${cost.toFixed(2)},` +
      `现价${price != null ? price.toFixed(2) : '—'},` +
      `浮动盈亏${pnlPct != null ? pnlPct.toFixed(2) + '%' : '—'}` +
      `${pnlAmt != null ? '(' + (pnlAmt > 0 ? '+' : '') + pnlAmt.toFixed(0) + '元)' : ''},` +
      `${r.opened_at ? '建仓日' + r.opened_at : ''}。请在分析时客观对照我的持仓成本。`
    startStockAnalysis(r.symbol, r.name || '', context)
  }

  const handleSubmit = () => {
    if (!form.symbol.trim() || form.shares === '' || form.cost_price === '') return
    if (editing) {
      updateMut.mutate({
        symbol: editing.symbol,
        body: {
          shares: Number(form.shares),
          cost_price: Number(form.cost_price),
          opened_at: form.opened_at || '',
          note: form.note,
        },
      })
    } else {
      upsertMut.mutate({
        symbol: form.symbol.trim(),
        shares: Number(form.shares),
        cost_price: Number(form.cost_price),
        opened_at: form.opened_at || '',
        note: form.note,
      })
    }
  }

  const startEdit = (r: PositionEntry) => {
    setEditing(r)
    setForm({
      symbol: r.symbol, shares: String(r.shares), cost_price: String(r.cost_price),
      opened_at: r.opened_at ?? '', note: r.note ?? '',
    })
  }
  const cancelEdit = () => {
    setEditing(null)
    setForm({ symbol: '', shares: '', cost_price: '', opened_at: '', note: '' })
  }

  const visibleColumns = useMemo(() => columns.filter(c => c.visible), [columns])
  const handleColumnsChange = (next: ColumnConfig[]) => { setColumns(next); saveColumnConfig(next) }

  const renderCell = (r: any, col: ColumnConfig) => {
    const key = col.source.type === 'builtin' ? col.source.key : ''
    const numCls = 'px-3 py-2 text-right num tabular-nums'
    const price = priceOf(r)
    const shares = Number(r.shares) || 0
    const costPrice = Number(r.cost_price) || 0
    const mv = price != null ? price * shares : null
    const pnlAmt = price != null ? (price - costPrice) * shares : null
    const pnlPct = costPrice > 0 && price != null ? (price - costPrice) / costPrice : null
    const weight = totalMv > 0 && mv != null ? mv / totalMv : null

    if (key === 'symbol') {
      const board = boardTag(r.symbol)
      return (
        <td className="px-3 py-2">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => openPreview(r.symbol, r.name)}
              className="flex items-center gap-1.5 text-left group"
              title="点击查看个股预览"
            >
              <span className="font-mono text-xs text-foreground group-hover:text-accent transition-colors">{r.symbol}</span>
              {r.name && <span className="text-xs text-secondary truncate group-hover:text-foreground transition-colors">{r.name}</span>}
              {board && <span className={`shrink-0 inline-flex items-center justify-center w-[18px] h-[18px] rounded text-[9px] font-bold leading-none border ${board.color}`}>{board.label}</span>}
            </button>
          </div>
        </td>
      )
    }
    if (key === 'cost_price') return <td className={numCls}>{fmtPrice(costPrice)}</td>
    if (key === 'shares') return <td className={numCls}>{shares.toLocaleString()}</td>
    if (key === 'market_value') return <td className={numCls}>{mv != null ? fmtBigNum(mv) : '—'}</td>
    if (key === 'pnl_amount') return <td className={`${numCls} font-semibold ${priceColorClass(pnlAmt)}`}>{pnlAmt != null ? `${pnlAmt > 0 ? '+' : ''}${pnlAmt.toFixed(0)}` : '—'}</td>
    if (key === 'pnl_pct') return <td className={`${numCls} font-semibold ${priceColorClass(pnlPct)}`}>{pnlPct != null ? `${pnlPct > 0 ? '+' : ''}${(pnlPct * 100).toFixed(2)}%` : '—'}</td>
    if (key === 'weight') return <td className={numCls}>{weight != null ? `${(weight * 100).toFixed(1)}%` : '—'}</td>
    if (key === 'opened_at') return <td className="px-3 py-2 text-center text-xs text-secondary">{r.opened_at || '—'}</td>
    if (key === 'note') return <td className="px-3 py-2 text-xs text-secondary max-w-[180px] truncate" title={r.note}>{r.note || '—'}</td>
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
    // 其余通用内置列(现价/今涨跌/量比/换手/均线/RSI等)复用自选页口径
    const builtin = renderBuiltinDataCell(r, col)
    if (builtin) return builtin
    return <td className="px-3 py-2 text-muted text-center">—</td>
  }

  return (
    <div className="p-4 md:p-5">
      <PageHeader
        title="持仓"
        subtitle="当前持仓清单 · 实时盈亏 · 成本价可从大喵票池锚定价带入"
        right={
          <div className="flex items-center gap-2">
            <button
              onClick={() => runAiReview('')}
              disabled={rows.length === 0}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white text-xs font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
              title="AI 复盘当前全部持仓"
            >
              <Sparkles className="h-3.5 w-3.5" /> AI 复盘
            </button>
            <button onClick={() => setCustomizerOpen(true)} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors">
              <Settings2 className="h-3.5 w-3.5" /> 列
            </button>
          </div>
        }
      />

      {/* 录入表单 */}
      <div className="mt-4 p-3 rounded-card border border-border bg-panel flex flex-wrap items-center gap-2">
        {editing && <span className="text-xs text-accent">正在编辑 {editing.symbol}</span>}
        <StockSearchSelect
          value={form.symbol}
          onSelect={(sym) => setForm(f => ({ ...f, symbol: sym }))}
          existingSymbols={rows.map(r => r.symbol)}
          placeholder="搜索代码/名称"
          widthClass="w-56"
          disabled={!!editing}
        />
        <input className={`${inputCls} w-24`} type="number" step="100" placeholder="持股数" value={form.shares} onChange={e => setForm(f => ({ ...f, shares: e.target.value }))} />
        <div className="flex items-center gap-1">
          <input className={`${inputCls} w-28`} type="number" step="0.01" placeholder="成本价" value={form.cost_price} onChange={e => setForm(f => ({ ...f, cost_price: e.target.value }))} />
          <button type="button" onClick={bringAnchor} title="从大喵票池带入该代码的锚定价" className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-border text-secondary hover:text-accent transition-colors">
            <Crosshair className="h-4 w-4" />
          </button>
        </div>
        <input type="date" className={`${inputCls} w-36`} value={form.opened_at} onChange={e => setForm(f => ({ ...f, opened_at: e.target.value }))} />
        <input className={`${inputCls} flex-1 min-w-[160px]`} placeholder="备注，如 低吸/尾盘埋伏" value={form.note} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} />
        <button className={btnPrimary} disabled={upsertMut.isPending || updateMut.isPending || !form.symbol.trim() || form.shares === '' || form.cost_price === ''} onClick={handleSubmit}>
          {editing ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
          {editing ? '保存' : '加入持仓'}
        </button>
        {editing && <button className={btnGhost} onClick={cancelEdit}>取消</button>}
      </div>

      {/* 汇总条 */}
      <div className="mt-4 flex flex-wrap items-center gap-6 rounded-card border border-border bg-gradient-to-r from-accent/10 to-transparent p-4">
        <SummaryItem label="总市值" value={fmtBigNum(summary.marketValue)} />
        <div className="h-8 w-px bg-border" />
        <SummaryItem label="总成本" value={fmtBigNum(summary.cost)} />
        <div className="h-8 w-px bg-border" />
        <SummaryItem
          label="总盈亏"
          value={`${summary.pnl >= 0 ? '+' : ''}${summary.pnl.toFixed(0)}`}
          valueClass={priceColorClass(summary.pnl)}
        />
        <div className="h-8 w-px bg-border" />
        <SummaryItem
          label="总收益率"
          value={summary.pnlPct != null ? `${summary.pnlPct > 0 ? '+' : ''}${(summary.pnlPct * 100).toFixed(2)}%` : '—'}
          valueClass={priceColorClass(summary.pnlPct)}
        />
        <div className="h-8 w-px bg-border" />
        <SummaryItem label="持仓只数" value={String(summary.count)} />
        {summary.count > 0 && (
          <button className="ml-auto text-xs text-muted hover:text-danger transition-colors" onClick={() => { if (confirm('确认清空全部持仓？')) clearMut.mutate() }}>清空</button>
        )}
      </div>

      {/* 表格 */}
      {rows.length === 0 ? (
        <EmptyState title="还没有持仓" hint="录入代码、股数和成本价，实时查看盈亏。" />
      ) : (
        <div className="mt-3 rounded-card border border-border overflow-x-auto bg-panel">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {visibleColumns.map(col => (
                  <th key={col.id} className={`px-3 py-2.5 font-medium text-muted text-xs whitespace-nowrap ${col.align === 'left' ? 'text-left' : col.align === 'right' ? 'text-right' : 'text-center'}`}>{col.label}</th>
                ))}
                <th className="px-3 py-2.5 text-right text-muted text-xs w-24">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.symbol} className="border-t border-border hover:bg-elevated/40 transition-colors">
                  {visibleColumns.map(col => <React.Fragment key={col.id}>{renderCell(r, col)}</React.Fragment>)}
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1 text-xs">
                      <button className="p-1 text-muted hover:text-violet-400" title="AI 个股分析(带入持仓上下文)" onClick={() => analyzeOne(r)}><Sparkles className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-accent" title="编辑" onClick={() => startEdit(r)}><Pencil className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-danger" title="删除" onClick={() => { if (confirm(`删除 ${r.symbol} 的持仓？`)) removeMut.mutate(r.symbol) }}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ListColumnCustomizer
        columns={columns}
        groups={COLUMN_GROUPS}
        onChange={handleColumnsChange}
        open={customizerOpen}
        onClose={() => setCustomizerOpen(false)}
        title="自定义列"
        showExtColumns={false}
      />

      <StockPreviewDialog
        symbol={previewSymbol}
        name={previewName}
        onClose={closePreview}
      />

      {aiOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={closeAi} />
          <div className="relative w-full max-w-2xl max-h-[85vh] flex flex-col rounded-card border border-border bg-base shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center justify-center h-7 w-7 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
                  <Sparkles className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-medium text-foreground">AI 持仓复盘</div>
                  {aiMeta && (
                    <div className="text-[11px] text-muted">
                      {aiMeta.count} 只持仓 · 总市值 {fmtBigNum(aiMeta.total_market_value)} · 浮盈亏 {aiMeta.total_pnl_pct != null ? (aiMeta.total_pnl_pct > 0 ? '+' : '') + aiMeta.total_pnl_pct + '%' : '—'}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" title="历史报告" onClick={openHistory}>
                  <History className="h-4 w-4" />
                </button>
                {!aiLoading && aiContent && (
                  <>
                    <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" title="重新生成" onClick={() => runAiReview(aiFocus)}>
                      <RefreshCw className="h-4 w-4" />
                    </button>
                    <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" title="复制" onClick={() => navigator.clipboard?.writeText(aiContent)}>
                      <Copy className="h-4 w-4" />
                    </button>
                  </>
                )}
                <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" onClick={closeAi}>
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="relative flex-1 overflow-hidden">
              {historyOpen ? (
                <div className="absolute inset-0 overflow-y-auto px-5 py-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="text-sm font-medium text-foreground">历史复盘报告</div>
                    <button className="text-xs text-muted hover:text-foreground" onClick={() => setHistoryOpen(false)}>返回当前</button>
                  </div>
                  {historyLoading ? (
                    <div className="py-10 text-center text-xs text-muted">加载中…</div>
                  ) : historyReports.length === 0 ? (
                    <div className="py-10 text-center text-xs text-muted">还没有历史报告，复盘完成后会自动归档。</div>
                  ) : (
                    <div className="space-y-2">
                      {historyReports.map((r: any) => {
                        const s = r.summary || {}
                        const pnlPct = s.total_pnl_pct
                        return (
                          <div key={r.id} className="group flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-elevated/50 transition-colors cursor-pointer" onClick={() => openHistoryReport(r)}>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 text-xs">
                                <span className="text-foreground font-medium">{r.as_of || (r.created_at || '').slice(0, 10)}</span>
                                <span className="text-muted">{r.count ?? s.count ?? 0} 只</span>
                                {r.focus && <span className="text-accent truncate">· {r.focus}</span>}
                              </div>
                              <div className="mt-1 text-[11px] text-muted truncate">
                                总市值 {fmtBigNum(s.total_market_value ?? 0)} · 浮盈亏 {pnlPct != null ? (pnlPct > 0 ? '+' : '') + pnlPct + '%' : '—'} · {new Date(r.created_at).toLocaleString()}
                              </div>
                            </div>
                            <button
                              className="opacity-0 group-hover:opacity-100 p-1 text-muted hover:text-danger transition-opacity"
                              title="删除"
                              onClick={(e) => { e.stopPropagation(); deleteHistoryReport(r.id) }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full overflow-y-auto px-5 py-4 text-sm text-secondary leading-relaxed">
                  {aiError ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-center">
                      <div className="text-sm text-danger">{aiError}</div>
                      {aiError.includes('未配置') || aiError.includes('API Key') || aiError.includes('AI') ? (
                        <a href="/settings?tab=ai" className="text-xs text-accent hover:underline">去设置 → AI 中配置</a>
                      ) : (
                        <button className={btnGhost} onClick={() => runAiReview(aiFocus)}>重试</button>
                      )}
                    </div>
                  ) : aiLoading && !aiContent ? (
                    <div className="flex items-center gap-2 text-muted py-10">
                      <span className="h-2 w-2 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="h-2 w-2 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="h-2 w-2 rounded-full bg-violet-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                      <span className="ml-2">正在分析持仓与大盘环境…</span>
                    </div>
                  ) : (
                    <>
                      <MarkdownRenderer content={aiContent} />
                      {aiLoading && <span className="inline-block w-1.5 h-4 ml-0.5 bg-violet-400 animate-pulse align-middle" />}
                    </>
                  )}
                </div>
              )}
            </div>

            <form
              className="flex items-center gap-2 px-5 py-3 border-t border-border"
              onSubmit={(e) => { e.preventDefault(); runAiReview(aiFocus) }}
            >
              <input
                className="flex-1 h-9 px-3 rounded-lg border border-border bg-elevated text-sm text-foreground outline-none focus:border-accent transition-colors"
                placeholder="想重点看什么？如：医药仓位、风险点（可选）"
                value={aiFocus}
                onChange={e => setAiFocus(e.target.value)}
              />
              <button type="submit" className={btnPrimary} disabled={aiLoading}>
                {aiLoading ? '分析中…' : '重新复盘'}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryItem({ label, value, valueClass = '' }: { label: string; value: React.ReactNode; valueClass?: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${valueClass}`}>{value}</div>
    </div>
  )
}
