import React, { useMemo, useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2, Sparkles, X, Copy, RefreshCw, History, CalendarClock, Plus, Settings2, TrendingDown, Eraser, Check } from 'lucide-react'
import { api, type KlineRow, type MinuteKlineRow } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtPrice, priceColorClass, fmtBigNum } from '@/lib/format'
import { boardTag, renderBuiltinDataCell } from '@/components/stock-table/primitives'
import { getSignals, signalCls } from '@/lib/stock-table'
import { MiniCandlestick } from '@/components/stock-table/MiniCandlestick'
import { MiniIntraday } from '@/components/stock-table/MiniIntraday'
import { resolveCandleConfig, resolveIntradayConfig } from '@/lib/list-columns'
import { useCapabilities, usePreferences } from '@/lib/useSharedQueries'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'
import { toast } from '@/components/Toast'
import { cn } from '@/lib/cn'
import { startAnalysis as startStockAnalysis } from '@/lib/stockAnalysisStore'
import { ListColumnCustomizer } from '@/components/ListColumnCustomizer'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { COLUMN_GROUPS, BUILTIN_COLUMNS, loadColumnConfig, saveColumnConfig, type ColumnConfig } from '@/lib/positions-columns'
import { TradeDialog, type TradeMode } from '@/components/positions/TradeDialog'
import { CashOverview } from '@/components/positions/CashOverview'
import { OperationTimeline } from '@/components/positions/OperationTimeline'
import { SettlementImport } from '@/components/positions/SettlementImport'
import { SettlementRecords } from '@/components/positions/SettlementRecords'
import { ReconcilePanel } from '@/components/positions/ReconcilePanel'

const btnPrimary = 'inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-40 transition-colors'
const btnGhost = 'inline-flex items-center h-9 px-3 rounded-lg border border-border text-sm text-secondary hover:text-foreground transition-colors'

function priceOf(r: any) { return r.close }

export function Positions() {
  const qc = useQueryClient()

  const [columns, setColumns] = useState<ColumnConfig[]>(() => [...BUILTIN_COLUMNS])
  const columnsLoaded = useRef(false)
  useEffect(() => {
    if (columnsLoaded.current) return
    columnsLoaded.current = true
    loadColumnConfig().then(setColumns)
  }, [])
  const [customizerOpen, setCustomizerOpen] = useState(false)

  // Tab：持仓 / 交割单 / 对账
  const [tab, setTab] = useState<'holdings' | 'settlement' | 'reconcile'>('holdings')

  // 交易弹窗
  const [trade, setTrade] = useState<{
    mode: TradeMode
    symbol?: string
    name?: string
    shares?: number
    cost?: number
  } | null>(null)
  const openTrade = (
    mode: TradeMode,
    row?: { symbol: string; name?: string | null; shares?: number; cost_price?: number },
  ) => {
    setTrade({
      mode,
      symbol: row?.symbol,
      name: row?.name ?? '',
      shares: row?.shares,
      cost: row?.cost_price,
    })
  }

  // 个股预览弹窗
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [previewName, setPreviewName] = useState<string>('')
  const openPreview = (sym: string, name?: string | null) => {
    setPreviewSymbol(sym); setPreviewName(name ?? '')
  }
  const closePreview = () => { setPreviewSymbol(null); setPreviewName('') }

  const list = useQuery({ queryKey: QK.positions, queryFn: api.positionsList })
  const enriched = useQuery({
    queryKey: QK.positionsEnriched(),
    queryFn: () => api.positionsEnriched(),
    enabled: (list.data?.rows.length ?? 0) > 0,
  })

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

  const clearMut = useMutation({
    mutationFn: api.positionsClear,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: ['positions-enriched'] })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
    },
  })

  // 快速移除：按成本价写入一条清仓记录（实现旧"删除"语义，不产生实际盈亏）
  const removeMut = useMutation({
    mutationFn: (r: { symbol: string; shares: number; cost_price: number; name?: string }) =>
      api.positionAddTrade({
        op_type: 'clear',
        symbol: r.symbol,
        name: r.name,
        price: r.cost_price,
        volume: r.shares,
        note: '移除持仓',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      qc.invalidateQueries({ queryKey: QK.positionCash })
      toast('持仓已移除', 'success')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  // 汇总
  const summary = useMemo(() => {
    let marketValue = 0, cost = 0, pnl = 0, dayPnl = 0
    for (const r of rows) {
      const price = priceOf(r)
      const shares = Number(r.shares) || 0
      const costPrice = Number(r.cost_price) || 0
      if (price != null) marketValue += price * shares
      cost += costPrice * shares
      if (price != null) pnl += (price - costPrice) * shares
      // 今日盈亏:优先用每股涨跌额;其次现价-昨收;最后用涨跌幅反推昨收
      const chgAmt = Number(r.change_amount)
      const prevClose = Number(r.prev_close)
      if (shares > 0 && price != null) {
        if (Number.isFinite(chgAmt) && chgAmt !== 0) {
          dayPnl += chgAmt * shares
        } else if (Number.isFinite(prevClose) && prevClose > 0) {
          dayPnl += (price - prevClose) * shares
        } else {
          const pct = Number(r.change_pct)
          if (Number.isFinite(pct) && pct !== 0 && pct > -1) {
            const pc = price / (1 + pct)
            dayPnl += (price - pc) * shares
          }
        }
      }
    }
    const pnlPct = cost > 0 ? pnl / cost : null
    return { marketValue, cost, pnl, pnlPct, dayPnl, count: rows.length }
  }, [rows])

  const totalMv = summary.marketValue

  // ===== AI 持仓复盘 =====
  type AiMode = 'holdings' | 'settlement' | 'reconcile'
  const [aiMode, setAiMode] = useState<AiMode>('holdings')
  const [aiOpen, setAiOpen] = useState(false)
  const [aiStarted, setAiStarted] = useState(false) // 是否已发起过本轮复盘(区分"刚打开"与"分析中")
  const [aiLoading, setAiLoading] = useState(false)
  const [aiContent, setAiContent] = useState('')
  const [aiError, setAiError] = useState('')
  const [aiMeta, setAiMeta] = useState<any>(null)
  const [aiFocus, setAiFocus] = useState('')
  const aiAbortRef = useRef<boolean>(false)
  // 历史报告
  const [historyReports, setHistoryReports] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [viewing, setViewing] = useState<any | null>(null)

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

  // 查看历史报告:不覆盖后台流式内容,用 viewing 单独承载;点"返回当前"清空。
  const openHistoryReport = (report: any) => {
    setViewing(report)
  }
  const backToCurrent = () => setViewing(null)

  const deleteHistoryReport = async (id: string) => {
    setHistoryReports(prev => prev.filter(r => r.id !== id))
    if (viewing?.id === id) setViewing(null)
    try { await api.positionReportDelete(id) } catch { /* 静默 */ }
  }

  // ===== 定时复盘设置 =====
  const prefs = usePreferences()
  const posSched = prefs.data?.position_review_schedule ?? { enabled: false, hour: 15, minute: 15 }
  const posPushChannels = prefs.data?.position_review_push_channels ?? []
  const feishuConfigured = !!(prefs.data?.feishu_webhook_url)
  const wecomConfigured = !!(prefs.data?.wecom_webhook_url)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [schedDraft, setSchedDraft] = useState<{ enabled: boolean; hour: number; minute: number }>(posSched)
  const openSchedule = () => { setSchedDraft(posSched); setScheduleOpen(true) }
  const schedMut = useMutation({
    mutationFn: (v: { enabled: boolean; hour: number; minute: number }) =>
      api.updatePositionReviewSchedule(v.enabled, v.hour, v.minute),
    onSuccess: (_d, v) => {
      qc.invalidateQueries({ queryKey: QK.preferences })
      setScheduleOpen(false)
      toast(v.enabled ? '已开启每日持仓复盘' : '已关闭每日持仓复盘', 'success')
    },
  })
  const pushMut = useMutation({
    mutationFn: (channels: string[]) => api.updatePositionReviewPush(channels),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.preferences }),
  })
  const togglePush = (ch: string) => {
    const next = posPushChannels.includes(ch) ? posPushChannels.filter((c: string) => c !== ch) : [...posPushChannels, ch]
    pushMut.mutate(next)
  }

  const runAiReview = async (focus = '') => {
    // settlement/reconcile 模式使用独立的交割单分析 skill
    const useSettlementSkill = aiMode === 'settlement' || aiMode === 'reconcile'
    if (!useSettlementSkill && rows.length === 0) return
    setAiOpen(true)
    setViewing(null)
    setAiLoading(true)
    setAiContent('')
    setAiError('')
    setAiMeta(null)
    setAiStarted(true)
    aiAbortRef.current = false
    loadHistory()
    try {
      let first = true
      const streamFn = useSettlementSkill
        ? (f: string) => api.settlementAnalyzeStream(f)
        : (f: string) => api.positionAnalyzeStream(f)
      for await (const chunk of streamFn(focus)) {
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
            setAiError(chunk.message ?? '分析失败')
            return
          case 'done':
            setAiLoading(false)
            break
        }
      }
      if (first && !aiAbortRef.current) { setAiLoading(false); setAiError('未返回内容,请重试') }
      loadHistory()
    } catch (e: any) {
      setAiLoading(false)
      setAiError(String(e?.message ?? '分析失败'))
    }
  }

  const closeAi = () => {
    aiAbortRef.current = true
    setAiOpen(false)
  }

  // ===== AI 模式配置 =====
  const aiModeConfig: Record<AiMode, {
    title: string
    subtitle: string
    desc: string
    placeholder: string
    defaultFocus: string
    loadingText: string
    buttonText: string
  }> = {
    holdings: {
      title: 'AI 持仓复盘',
      subtitle: '客观复盘持仓结构、集中度与风险',
      desc: '综合持仓盈亏、行业/概念集中度、当日板块强弱与大盘环境，生成客观组合复盘。',
      placeholder: '想重点看什么？如：医药仓位、风险点（可选，回车重新复盘）',
      defaultFocus: '',
      loadingText: 'AI 正在复盘持仓…',
      buttonText: '开始复盘',
    },
    settlement: {
      title: 'AI 交割单分析',
      subtitle: '基于交割单的交易盈亏与费用回顾',
      desc: '综合交割单已实现盈亏、月度交易节奏、单票盈亏排行与费用构成，结合持仓上下文生成交易复盘。',
      placeholder: '想重点看什么？如：本月盈亏、佣金占比、某标的交易得失（可选）',
      defaultFocus: '交割单盈亏回顾、交易节奏与费用分析',
      loadingText: 'AI 正在分析交割单…',
      buttonText: '开始分析',
    },
    reconcile: {
      title: 'AI 对账分析',
      subtitle: '对账差异复盘与持仓一致性检查',
      desc: '对比交割单与操作日志的持仓差异，分析异常标的并给出修正建议，同时回顾已实现盈亏。',
      placeholder: '想重点看什么？如：对账异常原因、某标的持仓差异（可选）',
      defaultFocus: '对账异常分析、持仓一致性检查与交割单盈亏回顾',
      loadingText: 'AI 正在分析对账…',
      buttonText: '开始分析',
    },
  }

  // 仅打开弹窗(不自动复盘):让用户能先看历史,或手动点"开始复盘"
  const openAi = (mode: AiMode = 'holdings') => {
    setAiMode(mode)
    setAiOpen(true)
    setViewing(null)
    setAiStarted(false)
    setAiLoading(false)
    setAiError('')
    setAiContent('')
    setAiMeta(null)
    // 首次打开时用模式默认 focus,用户未修改过则自动填入
    if (!aiFocus) {
      setAiFocus(aiModeConfig[mode].defaultFocus)
    }
    loadHistory()
  }

  // 主区域显示内容:查看历史优先于流式内容(不覆盖后台生成)
  const displayContent = viewing?.content ?? aiContent

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
              onClick={() => openTrade('buy')}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-bull text-white text-xs font-medium hover:bg-bull/90 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" /> 买入
            </button>
            <button
              onClick={() => openAi('holdings')}
              disabled={rows.length === 0}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white text-xs font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
              title="AI 复盘当前全部持仓"
            >
              <Sparkles className="h-3.5 w-3.5" /> AI 复盘
            </button>
            <button
              onClick={openSchedule}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border text-xs transition-colors",
                posSched.enabled
                  ? "border-violet-400/50 text-violet-300 bg-violet-500/10"
                  : "border-border text-secondary hover:text-foreground",
              )}
              title="每日收盘自动持仓复盘与推送设置"
            >
              <CalendarClock className="h-3.5 w-3.5" />
              {posSched.enabled ? `定时 ${String(posSched.hour).padStart(2, '0')}:${String(posSched.minute).padStart(2, '0')}` : '定时复盘'}
            </button>
            <button onClick={() => setCustomizerOpen(true)} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors">
              <Settings2 className="h-3.5 w-3.5" /> 列
            </button>
          </div>
        }
      />

      {/* Tab 切换 */}
      <div className="mt-4 flex items-center gap-1 border-b border-border">
        {([
          { key: 'holdings', label: '持仓' },
          { key: 'settlement', label: '交割单' },
          { key: 'reconcile', label: '对账' },
        ] as const).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'relative -mb-px px-4 py-2 text-xs font-medium transition-colors',
              tab === t.key ? 'text-foreground' : 'text-muted hover:text-secondary',
            )}
          >
            {t.label}
            {tab === t.key && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      {tab === 'holdings' && (
      <>
      {/* 现金 / 总资产概览 */}
      <div className="mt-4">
        <CashOverview marketValue={summary.marketValue} />
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
          label="今日盈亏"
          value={`${summary.dayPnl >= 0 ? '+' : ''}${summary.dayPnl.toFixed(0)}`}
          valueClass={priceColorClass(summary.dayPnl)}
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
        <EmptyState title="还没有持仓" hint="点击右上角「买入」记录一笔建仓交易，实时查看盈亏。" />
      ) : (
        <div className="mt-3 rounded-card border border-border overflow-x-auto bg-panel">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {visibleColumns.map(col => (
                  <th key={col.id} className={`px-3 py-2.5 font-medium text-muted text-xs whitespace-nowrap ${col.align === 'left' ? 'text-left' : col.align === 'right' ? 'text-right' : 'text-center'}`}>{col.label}</th>
                ))}
                <th className="px-3 py-2.5 text-right text-muted text-xs w-28">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.symbol} className="border-t border-border hover:bg-elevated/40 transition-colors">
                  {visibleColumns.map(col => <React.Fragment key={col.id}>{renderCell(r, col)}</React.Fragment>)}
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-0.5 text-xs">
                      <button className="p-1 text-muted hover:text-violet-400" title="AI 个股分析(带入持仓上下文)" onClick={() => analyzeOne(r)}><Sparkles className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-bull" title="加仓" onClick={() => openTrade('buy', r)}><Plus className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-bear" title="减仓" onClick={() => openTrade('sell', r)}><TrendingDown className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-warning" title="清仓" onClick={() => openTrade('clear', r)}><Eraser className="h-3.5 w-3.5" /></button>
                      <button className="p-1 text-muted hover:text-danger disabled:opacity-40" disabled={removeMut.isPending} title="移除持仓" onClick={() => { if (confirm(`移除 ${r.symbol} 的持仓？将按成本价写入一条清仓记录。`)) removeMut.mutate({ symbol: r.symbol, name: r.name, shares: Number(r.shares), cost_price: Number(r.cost_price) }) }}><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 操作历史时间线 */}
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <OperationTimeline />
        </div>
      </div>
      </>
      )}

      {tab === 'settlement' && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1">
            <SettlementImport />
          </div>
          <div className="lg:col-span-2">
            <SettlementRecords onAnalyze={() => openAi('settlement')} />
          </div>
        </div>
      )}

      {tab === 'reconcile' && (
        <div className="mt-4">
          <ReconcilePanel onAnalyze={() => openAi('reconcile')} />
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

      {scheduleOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => !schedMut.isPending && setScheduleOpen(false)} />
          <div className="relative w-full max-w-md rounded-card border border-border bg-base shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
              <div className="flex items-center gap-2">
                <CalendarClock className="h-4 w-4 text-violet-400" />
                <span className="text-sm font-medium text-foreground">每日持仓复盘</span>
              </div>
              <button className="p-1 text-muted hover:text-foreground" onClick={() => setScheduleOpen(false)}><X className="h-4 w-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <label className="flex items-center justify-between cursor-pointer">
                <div>
                  <div className="text-sm text-foreground">启用每日自动复盘</div>
                  <div className="text-[11px] text-muted mt-0.5">交易日收盘后自动生成持仓复盘并归档</div>
                </div>
                <button
                  type="button"
                  onClick={() => setSchedDraft(d => ({ ...d, enabled: !d.enabled }))}
                  className={cn("relative h-5 w-9 rounded-full transition-colors", schedDraft.enabled ? "bg-violet-500" : "bg-border")}
                >
                  <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform", schedDraft.enabled ? "translate-x-4" : "translate-x-0.5")} />
                </button>
              </label>

              {schedDraft.enabled && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-secondary">触发时间</span>
                  <select
                    value={schedDraft.hour}
                    onChange={e => setSchedDraft(d => ({ ...d, hour: Number(e.target.value) }))}
                    className="h-8 rounded-md border border-border bg-elevated px-2 text-xs text-foreground"
                  >
                    {Array.from({ length: 9 }, (_, i) => i + 15).map(h => <option key={h} value={h}>{String(h).padStart(2, '0')}</option>)}
                  </select>
                  <span className="text-xs text-muted">:</span>
                  <select
                    value={schedDraft.minute}
                    onChange={e => setSchedDraft(d => ({ ...d, minute: Number(e.target.value) }))}
                    className="h-8 rounded-md border border-border bg-elevated px-2 text-xs text-foreground"
                  >
                    {[0, 5, 10, 15, 20, 30, 45].map(m => <option key={m} value={m}>{String(m).padStart(2, '0')}</option>)}
                  </select>
                  <span className="text-[11px] text-muted">收盘后(≥15:00)</span>
                </div>
              )}

              <div className="border-t border-border pt-3">
                <div className="text-xs text-secondary mb-2">复盘后推送到</div>
                <div className="space-y-2">
                  {[
                    { id: 'feishu', label: '飞书', configured: feishuConfigured },
                    { id: 'wecom', label: '企业微信', configured: wecomConfigured },
                  ].map(ch => {
                    const on = posPushChannels.includes(ch.id)
                    return (
                      <label key={ch.id} className="flex items-center gap-2 cursor-pointer" onClick={() => togglePush(ch.id)}>
                        <span className={cn("flex h-4 w-4 items-center justify-center rounded border", on ? "border-violet-500 bg-violet-500 text-white" : "border-border")}>
                          {on && <Check className="h-3 w-3" />}
                        </span>
                        <span className="text-xs text-foreground">{ch.label}</span>
                        {!ch.configured && <span className="text-[10px] text-muted">(未配置 webhook)</span>}
                      </label>
                    )
                  })}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 px-5 py-3 border-t border-border">
              <button className="h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground" onClick={() => setScheduleOpen(false)}>取消</button>
              <button
                className="h-8 px-4 rounded-lg bg-violet-500 text-white text-xs font-medium hover:bg-violet-500/90 disabled:opacity-50"
                disabled={schedMut.isPending}
                onClick={() => schedMut.mutate({ enabled: schedDraft.enabled, hour: schedDraft.hour, minute: schedDraft.minute })}
              >
                {schedMut.isPending ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      <StockPreviewDialog
        symbol={previewSymbol}
        name={previewName}
        onClose={closePreview}
      />

      {trade && (
        <TradeDialog
          open={!!trade}
          mode={trade.mode}
          initialSymbol={trade.symbol}
          initialName={trade.name}
          initialShares={trade.shares}
          initialCost={trade.cost}
          existingSymbols={rows.map(r => r.symbol)}
          onClose={() => setTrade(null)}
        />
      )}

      {aiOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={closeAi} />
          <div className="relative w-full max-w-5xl max-h-[92vh] flex flex-col rounded-card border border-border bg-base shadow-2xl">
            {/* 头部 */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
              <div className="flex items-center gap-2.5">
                <span className="inline-flex items-center justify-center h-8 w-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
                  <Sparkles className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-semibold text-foreground">{aiModeConfig[aiMode].title}</div>
                  <div className="text-[11px] text-muted">
                    {viewing
                      ? `查看历史 · ${viewing.as_of || ''}`
                      : aiMeta
                        ? `${aiMeta.count ?? 0} 只持仓 · 总市值 ${fmtBigNum(aiMeta.total_market_value ?? 0)} · 浮盈亏 ${aiMeta.total_pnl_pct != null ? (aiMeta.total_pnl_pct > 0 ? '+' : '') + aiMeta.total_pnl_pct + '%' : '—'}`
                        : aiModeConfig[aiMode].subtitle}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-1">
                {!aiLoading && displayContent && (
                  <>
                    <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" title="重新生成" onClick={() => runAiReview(aiFocus)}>
                      <RefreshCw className="h-4 w-4" />
                    </button>
                    <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" title="复制" onClick={() => navigator.clipboard?.writeText(displayContent)}>
                      <Copy className="h-4 w-4" />
                    </button>
                  </>
                )}
                <button className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-elevated" onClick={closeAi}>
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* 关注点输入 */}
            <form
              className="flex items-center gap-2 px-5 py-3 border-b border-border shrink-0"
              onSubmit={(e) => { e.preventDefault(); if (!viewing) runAiReview(aiFocus) }}
            >
              <Sparkles className="h-3.5 w-3.5 shrink-0 text-violet-400" />
              <input
                className="flex-1 h-9 px-3 rounded-lg border border-border bg-elevated text-sm text-foreground outline-none focus:border-violet-400/50 transition-colors"
                placeholder={aiModeConfig[aiMode].placeholder}
                value={aiFocus}
                onChange={e => setAiFocus(e.target.value)}
              />
              <button type="submit" className={btnPrimary} disabled={aiLoading}>
                {aiLoading ? '分析中…' : (viewing ? '返回并重新复盘' : '重新复盘')}
              </button>
            </form>

            {/* 双栏:报告 + 历史 */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_18rem] gap-3 p-3 overflow-hidden">
              {/* 左:报告主体 */}
              <div className="overflow-hidden rounded-lg border border-border bg-surface/80 flex flex-col min-h-0">
                <div className="flex items-center justify-between border-b border-border px-4 py-2 shrink-0">
                  <div className="flex items-center gap-1.5">
                    {aiLoading && !viewing
                      ? <RefreshCw className="h-3.5 w-3.5 animate-spin text-violet-400" />
                      : <Sparkles className="h-3.5 w-3.5 text-violet-400" />}
                    <span className="text-xs font-medium text-foreground">
                      {viewing ? '历史报告' : aiLoading ? aiModeConfig[aiMode].loadingText.replace('…', '') + '…' : '分析报告'}
                    </span>
                  </div>
                  {viewing && (
                    <button className="text-[11px] text-violet-400 hover:text-violet-300" onClick={backToCurrent}>← 返回当前</button>
                  )}
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-5 py-4 thin-scrollbar ai-review-body text-sm text-secondary leading-relaxed">
                  {viewing ? (
                    <MarkdownRenderer content={viewing.content ?? ''} />
                  ) : aiError ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-center">
                      <div className="text-sm text-danger">{aiError}</div>
                      {aiError.includes('未配置') || aiError.includes('API Key') || aiError.includes('AI') ? (
                        <a href="/settings?tab=ai" className="text-xs text-accent hover:underline">去设置 → AI 中配置</a>
                      ) : (
                        <button className={btnGhost} onClick={() => runAiReview(aiFocus)}>重试</button>
                      )}
                    </div>
                  ) : aiLoading && !aiContent ? (
                    <div className="flex flex-col items-center justify-center gap-3 py-16">
                      <div className="relative">
                        <span className="grid h-11 w-11 place-items-center rounded-full bg-violet-500/15 border border-violet-500/30">
                          <Sparkles className="h-5 w-5 animate-pulse text-violet-400" />
                        </span>
                      </div>
                      <div className="text-sm text-foreground">{aiModeConfig[aiMode].loadingText}</div>
                      <div className="text-xs text-secondary">分析盈亏结构 · 行业集中度 · 板块强弱 · 风险点</div>
                    </div>
                  ) : !aiStarted && !aiContent ? (
                    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
                      <div className="relative">
                        <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/15 border border-violet-500/30">
                          <Sparkles className="h-6 w-6 text-violet-400" />
                        </span>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-foreground">{aiModeConfig[aiMode].title}</div>
                        <p className="mx-auto mt-1.5 max-w-xs text-xs leading-relaxed text-secondary">
                          {aiModeConfig[aiMode].desc}
                        </p>
                      </div>
                      <button
                        className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white text-xs font-medium hover:opacity-90 transition-opacity"
                        onClick={() => runAiReview(aiFocus)}
                      >
                        <Sparkles className="h-3.5 w-3.5" /> {aiModeConfig[aiMode].buttonText}
                      </button>
                      <p className="text-[11px] text-muted">也可直接在右侧查看历史复盘报告</p>
                    </div>
                  ) : (
                    <>
                      <MarkdownRenderer content={aiContent} />
                      {aiLoading && <span className="inline-block w-1.5 h-4 ml-0.5 bg-violet-400 animate-pulse align-middle" />}
                    </>
                  )}
                </div>
              </div>

              {/* 右:历史(常驻) */}
              <div className="hidden lg:flex overflow-hidden rounded-lg border border-border bg-surface/80 flex-col min-h-0">
                <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 shrink-0">
                  <History className="h-3.5 w-3.5 text-violet-400" />
                  <span className="text-xs font-medium text-foreground">历史复盘</span>
                  <span className="font-mono text-[10px] text-muted">({historyReports.length})</span>
                  <button className="ml-auto p-1 text-muted hover:text-foreground" title="刷新" onClick={loadHistory}>
                    <RefreshCw className={cn("h-3 w-3", historyLoading && "animate-spin")} />
                  </button>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto p-2 thin-scrollbar">
                  {historyLoading && historyReports.length === 0 ? (
                    <div className="grid h-20 place-items-center"><RefreshCw className="h-4 w-4 animate-spin text-muted" /></div>
                  ) : historyReports.length === 0 ? (
                    <div className="flex flex-col items-center justify-center gap-2 px-3 py-10 text-center">
                      <History className="h-7 w-7 text-muted/40" strokeWidth={1.5} />
                      <div className="text-[11px] text-muted">暂无历史复盘</div>
                      <div className="text-[10px] text-muted/60">复盘完成后自动归档</div>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {aiLoading && !viewing && (
                        <div className="flex items-center gap-2 rounded px-2 py-2 bg-violet-500/10 ring-1 ring-violet-500/20">
                          <div className="grid h-8 w-8 shrink-0 place-items-center rounded bg-violet-500/15">
                            <RefreshCw className="h-3.5 w-3.5 animate-spin text-violet-400" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-[11px] font-medium text-violet-300">生成中…</div>
                            <div className="mt-0.5 text-[10px] text-secondary">{aiModeConfig[aiMode].loadingText}</div>
                          </div>
                        </div>
                      )}
                      {historyReports.map((r: any) => {
                        const s = r.summary || {}
                        const pnl = s.total_pnl_pct
                        const active = viewing?.id === r.id
                        return (
                          <div
                            key={r.id}
                            className={cn(
                              "group flex items-center gap-2 rounded px-2 py-2 cursor-pointer transition-colors",
                              active ? "bg-violet-500/10 ring-1 ring-violet-500/20" : "hover:bg-elevated/60",
                            )}
                            onClick={() => openHistoryReport(r)}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <span className="text-[11px] font-medium text-foreground">{r.as_of || (r.created_at || '').slice(0, 10)}</span>
                                <span className="text-[10px] text-muted">{r.count ?? s.count ?? 0} 只</span>
                                {pnl != null && (
                                  <span className={cn("font-mono text-[10px] font-medium tabular-nums", pnl > 0 ? "text-up" : pnl < 0 ? "text-down" : "text-secondary")}>
                                    {pnl > 0 ? '+' : ''}{pnl}%
                                  </span>
                                )}
                              </div>
                              <div className="mt-0.5 truncate text-[10px] text-secondary">
                                市值 {fmtBigNum(s.total_market_value ?? 0)} · {new Date(r.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                              </div>
                            </div>
                            <button
                              onClick={(e) => { e.stopPropagation(); deleteHistoryReport(r.id) }}
                              className="shrink-0 p-1 text-muted opacity-0 group-hover:opacity-100 hover:text-danger transition-all"
                              title="删除"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
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
