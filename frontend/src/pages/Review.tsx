/**
 * AI 复盘页 —— 以流式 LLM 报告为主体的盘后复盘工作台。
 *
 * 支持三种分析类型(tab 切换,与 URL `?tab=` 同步):
 *  - market:     大盘复盘(GET /api/overview/market + POST /api/market-recap/analyze)
 *  - holdings:   持仓分析(POST /api/positions/analyze)
 *  - settlement: 交割单分析(POST /api/settlement/analyze)
 *
 * 设计定位:极简专注型。不复刻 Dashboard 的看板(KPI/雷达/板块排名),
 * 仅保留一行「摘要条」作为报告上下文参照;AI 报告 + 历史归档是页面主体。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpenCheck, RefreshCw, Sparkles, Trash2, History, ChevronRight, AlertTriangle,
  Database, Wand2, Copy, Download, Clock, X, Check,
  BarChart3, Wallet, Receipt,
} from 'lucide-react'

import { api, type OverviewMarket, type AiReviewReport, type SettlementStats } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { fmtBigNum } from '@/lib/format'
import { PageHeader } from '@/components/PageHeader'
import { MarkdownRenderer } from '@/components/financials/MarkdownRenderer'
import { toast } from '@/components/Toast'
import { usePreferences } from '@/lib/useSharedQueries'
import { useReviewState } from '@/lib/useReviewStore'
import {
  startGeneration, abortGeneration, resetTab, isTabGenerating,
  type ReviewTab, type ReviewPhase, type ReviewMeta,
} from '@/lib/reviewStore'
import { getSkillState } from '@/lib/aiSkillStore'
import { SkillSelector } from '@/components/review/SkillSelector'
import { SkillParamsPanel } from '@/components/review/SkillParamsPanel'

// ================================================================
// 涨跌幅格式化(注意单位差异)
// overview 的 indices.change_pct / breadth.up_pct / seal_rate / *_pct / emotion.score
//   都是【已是百分比值】(如 1.2 表示 1.2%),直接 toFixed 即可,不要 *100。
// ================================================================
function fmtPctAlready(v: number | null | undefined, digits = 2, withSign = false): string {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = withSign && v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}
function pctClass(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v) || v === 0) return 'text-muted'
  return v > 0 ? 'text-bull' : 'text-bear'
}
// A 股惯例: 强势=红, 弱式=绿(对齐 Dashboard scoreColor)
function scoreColor(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '#71717A'
  if (v >= 70) return '#F04438'
  if (v >= 55) return '#FB923C'
  if (v >= 45) return '#F59E0B'
  if (v >= 30) return '#84CC16'
  return '#12B76A'
}

// 归档时刻格式化:ISO → "MM-DD HH:mm"(用于历史列表显示复盘时间)
function fmtArchivedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

// Phase 类型复用 store 的定义(单一来源)

// ================================================================
// Tab 配置 —— 三种分析类型的文案 / 图标 / 提示
// ================================================================
const TAB_CONFIG: Record<ReviewTab, {
  label: string
  icon: React.ReactNode
  placeholder: string
  emptyTitle: string
  emptyDesc: string
  loadingText: string
  generateText: string
  historyLabel: string
}> = {
  market: {
    label: '大盘复盘',
    icon: <BarChart3 className="h-3.5 w-3.5" />,
    placeholder: '可选:补充复盘关注点,如「半导体板块持续性如何」「量能是否持续」',
    emptyTitle: 'AI 大盘复盘',
    emptyDesc: '一键生成今日盘后复盘报告 —— 从一句话定调到明日交易计划,结构化输出可直接指导次日仓位与节奏。',
    loadingText: 'AI 正在复盘今日盘面…',
    generateText: '生成复盘',
    historyLabel: '历史复盘',
  },
  holdings: {
    label: '持仓分析',
    icon: <Wallet className="h-3.5 w-3.5" />,
    placeholder: '可选:如「医药仓位」「风险点」「仓位集中度」',
    emptyTitle: 'AI 持仓复盘',
    emptyDesc: '综合持仓盈亏、行业集中度、板块强弱与大盘环境,生成客观组合复盘。',
    loadingText: 'AI 正在复盘持仓…',
    generateText: '开始复盘',
    historyLabel: '历史持仓复盘',
  },
  settlement: {
    label: '交割单分析',
    icon: <Receipt className="h-3.5 w-3.5" />,
    placeholder: '可选:如「本月盈亏」「佣金占比」「某标的交易得失」',
    emptyTitle: 'AI 交割单分析',
    emptyDesc: '基于交割单的交易盈亏、费用回顾、月度节奏与威科夫交易行为诊断。',
    loadingText: 'AI 正在分析交割单…',
    generateText: '开始分析',
    historyLabel: '历史交割单分析',
  },
}

const VALID_TABS: ReviewTab[] = ['market', 'holdings', 'settlement']

export function Review() {
  const qc = useQueryClient()
  // ===== Tab 与 URL 同步 =====
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab') as ReviewTab | null
  const activeTab: ReviewTab = tabParam && VALID_TABS.includes(tabParam) ? tabParam : 'market'
  const switchTab = useCallback((tab: ReviewTab) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('tab', tab)
      return next
    }, { replace: true })
  }, [setSearchParams])

  // 复盘日期:当前固定取最新交易日(后续如需日期选择可改回 useState)
  const asOf: string | undefined = undefined
  const [focus, setFocus] = useState('')
  // 生成状态走全局 store:切走页面流不中断,回来可恢复
  const { phase, content, error, meta } = useReviewState(activeTab)
  const [viewing, setViewing] = useState<any | null>(null)  // 查看历史报告(各 tab 报告结构不同,用 any)
  const [skillParamsOpen, setSkillParamsOpen] = useState(false)
  const reportEndRef = useRef<HTMLDivElement>(null)

  // 查看历史报告时,顶部摘要条 / meta 信息跟随 viewing(而不是当前流)。
  // 老报告可能没有 skill_* 字段,用 ?? 兜底,不覆盖 storeMeta 已有的字段。
  const displayMeta: any = viewing
    ? {
        ...meta,
        ...viewing,
        summary: viewing.summary ?? meta?.summary,
        emotion_score: viewing.emotion_score ?? meta?.emotion_score,
        emotion_label: viewing.emotion_label ?? meta?.emotion_label,
        count: viewing.count ?? meta?.count,
        skill_id: viewing.skill_id ?? meta?.skill_id ?? null,
        skill_name: viewing.skill_name ?? meta?.skill_name ?? null,
        skill_params: viewing.skill_params ?? meta?.skill_params ?? {},
        usage: viewing.usage ?? meta?.usage ?? null,
        duration_ms: viewing.duration_ms ?? meta?.duration_ms ?? null,
      }
    : meta

  // 切换 tab 时清掉 viewing(避免上一个 tab 的历史报告内容残留到新 tab 主区域)
  useEffect(() => {
    setViewing(null)
  }, [activeTab])

  // ===== 看板数据(market tab 专用)=====
  const marketQuery = useQuery<OverviewMarket>({
    queryKey: QK.overviewMarket(asOf),
    queryFn: () => api.overviewMarket(asOf),
    staleTime: 5_000,
    placeholderData: (prev) => prev,
    enabled: activeTab === 'market',
  })

  // ===== 历史报告(各 tab 独立查询,按需启用)=====
  const historyQueryMarket = useQuery<{ reports: AiReviewReport[] }>({
    queryKey: QK.reviewReports,
    queryFn: () => api.reviewReportsList(),
    enabled: activeTab === 'market',
  })
  const deleteMutMarket = useMutation({
    mutationFn: (id: string) => api.reviewReportDelete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.reviewReports })
      toast('已删除', 'success')
    },
    onError: () => { /* request() 已 toast */ },
  })

  const historyQueryHoldings = useQuery<{ reports: any[] }>({
    queryKey: QK.positionReports,
    queryFn: () => api.positionReportsList(),
    enabled: activeTab === 'holdings',
  })
  const deleteMutHoldings = useMutation({
    mutationFn: (id: string) => api.positionReportDelete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.positionReports })
      toast('已删除', 'success')
    },
    onError: () => { /* request() 已 toast */ },
  })

  const historyQuerySettlement = useQuery<{ reports: any[] }>({
    queryKey: QK.settlementReports,
    queryFn: () => api.settlementReportsList(),
    enabled: activeTab === 'settlement',
  })
  const deleteMutSettlement = useMutation({
    mutationFn: (id: string) => api.settlementReportDelete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.settlementReports })
      toast('已删除', 'success')
    },
    onError: () => { /* request() 已 toast */ },
  })

  // 按 activeTab 选择当前历史数据 / 删除处理
  const historyReports = activeTab === 'market'
    ? (historyQueryMarket.data?.reports ?? [])
    : activeTab === 'holdings'
      ? (historyQueryHoldings.data?.reports ?? [])
      : (historyQuerySettlement.data?.reports ?? [])
  const historyLoading = activeTab === 'market'
    ? historyQueryMarket.isLoading
    : activeTab === 'holdings'
      ? historyQueryHoldings.isLoading
      : historyQuerySettlement.isLoading
  const handleDelete = useCallback((id: string) => {
    if (activeTab === 'market') deleteMutMarket.mutate(id)
    else if (activeTab === 'holdings') deleteMutHoldings.mutate(id)
    else deleteMutSettlement.mutate(id)
  }, [activeTab, deleteMutMarket, deleteMutHoldings, deleteMutSettlement])

  // ===== 刷新按钮:按 tab 刷新对应查询 =====
  const refreshData = useCallback(() => {
    if (activeTab === 'market') marketQuery.refetch()
    else if (activeTab === 'holdings') qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
    else qc.invalidateQueries({ queryKey: QK.settlementStats })
  }, [activeTab, marketQuery, qc])
  const refreshFetching = activeTab === 'market' ? marketQuery.isFetching : false

  // ===== 定时复盘(三 tab 独立配置) =====
  const [showSchedule, setShowSchedule] = useState(false)
  const [scheduleTab, setScheduleTab] = useState<ReviewTab>('market')
  const prefs = usePreferences()
  const reviewSched = prefs.data?.review_schedule ?? { enabled: false, hour: 15, minute: 10 }
  const posReviewSched = prefs.data?.position_review_schedule ?? { enabled: false, hour: 15, minute: 15 }
  const setReviewSched = prefs.data?.settlement_review_schedule ?? { enabled: false, hour: 15, minute: 40 }
  const feishuConfigured = !!(prefs.data?.feishu_webhook_url)
  const wecomConfigured = !!(prefs.data?.wecom_webhook_url)
  // 各 tab 推送渠道(独立多选,与定时开关解耦)
  const reviewPushChannels = prefs.data?.review_push_channels ?? []
  const posReviewPushChannels = prefs.data?.position_review_push_channels ?? []
  const setReviewPushChannels = prefs.data?.settlement_review_push_channels ?? []

  // 各 tab 独立草稿(开关+时间),切换 tab 不串扰
  const [draftMarket, setDraftMarket] = useState(reviewSched)
  const [draftHoldings, setDraftHoldings] = useState(posReviewSched)
  const [draftSettlement, setDraftSettlement] = useState(setReviewSched)
  const draftFor = (t: ReviewTab) =>
    t === 'market' ? draftMarket : t === 'holdings' ? draftHoldings : draftSettlement
  const setDraftFor = (t: ReviewTab, patch: Partial<{ enabled: boolean; hour: number; minute: number }>) => {
    if (t === 'market') setDraftMarket((d: { enabled: boolean; hour: number; minute: number }) => ({ ...d, ...patch }))
    else if (t === 'holdings') setDraftHoldings((d: { enabled: boolean; hour: number; minute: number }) => ({ ...d, ...patch }))
    else setDraftSettlement((d: { enabled: boolean; hour: number; minute: number }) => ({ ...d, ...patch }))
  }
  const schedFor = (t: ReviewTab) =>
    t === 'market' ? reviewSched : t === 'holdings' ? posReviewSched : setReviewSched

  const openSchedule = useCallback(() => {
    // 每次打开同步最新服务端值,并默认定位到当前 activeTab
    setDraftMarket(reviewSched)
    setDraftHoldings(posReviewSched)
    setDraftSettlement(setReviewSched)
    setScheduleTab(activeTab)
    setShowSchedule(true)
  }, [reviewSched, posReviewSched, setReviewSched, activeTab])

  const reviewMut = useMutation({
    mutationFn: ({ tab, enabled, hour, minute }: { tab: ReviewTab; enabled: boolean; hour: number; minute: number }) => {
      if (tab === 'market') return api.updateReviewSchedule(enabled, hour, minute)
      if (tab === 'holdings') return api.updatePositionReviewSchedule(enabled, hour, minute)
      return api.updateSettlementReviewSchedule(enabled, hour, minute)
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: QK.preferences })
      setShowSchedule(false)
      const label = vars.tab === 'market' ? '复盘' : vars.tab === 'holdings' ? '持仓分析' : '交割单分析'
      toast(vars.enabled ? `已开启定时${label}` : `已关闭定时${label}`, 'success')
    },
    onError: () => { /* request() 已 toast */ },
  })

  const pushMut = useMutation({
    mutationFn: ({ tab, channels }: { tab: ReviewTab; channels: string[] }): Promise<Record<string, string[]>> => {
      if (tab === 'market') return api.updateReviewPush(channels)
      if (tab === 'holdings') return api.updatePositionReviewPush(channels)
      return api.updateSettlementReviewPush(channels)
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: QK.preferences })
      toast(vars.channels.length === 0 ? '已关闭推送' : '已更新推送渠道', 'success')
    },
    onError: () => { /* request() 已 toast */ },
  })
  const pushChannelsFor = (t: ReviewTab) =>
    t === 'market' ? reviewPushChannels : t === 'holdings' ? posReviewPushChannels : setReviewPushChannels
  const togglePushChannel = useCallback((tab: ReviewTab, ch: string) => {
    const current = pushChannelsFor(tab)
    const next = current.includes(ch) ? current.filter((c: string) => c !== ch) : [...current, ch]
    pushMut.mutate({ tab, channels: next })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewPushChannels, posReviewPushChannels, setReviewPushChannels, pushMut])

  // 顶部"定时"按钮的激活态/标题(按当前 activeTab)
  const activeSched = schedFor(activeTab)


  // 自动滚动到报告底部(streaming 时)
  useEffect(() => {
    if (phase === 'streaming') {
      reportEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [content, phase])

  // 当进入生成中(streaming)时, 清掉「查看历史」状态, 让主区域显示流内容。
  // 手动 generate 已自带 setViewing(null), 这里主要补定时 SSE 流的场景:
  // 用户若正看着历史报告, 定时触发生成时也要切回主区域显示流式内容。
  useEffect(() => {
    if (phase === 'streaming' && viewing) {
      setViewing(null)
    }
  }, [phase, viewing])

  // 自动归档(生成完成后台静默保存)—— 仅 market tab 需要,
  // 通过回调注入 store,避免 store 直接依赖 qc/marketQuery。
  // holdings / settlement tab 由后端自动归档,无需前端再调保存接口。
  const onGenerationDone = useCallback(async (fullContent: string, doneMeta: ReviewMeta | null) => {
    const reportAsOf = doneMeta?.as_of ?? marketQuery.data?.as_of ?? asOf ?? new Date().toISOString().slice(0, 10)
    // market tab 的 summary 恒为字符串;holdings/settlement 的 dict 结构不会进入此回调(后端自动归档)
    const summaryStr = typeof doneMeta?.summary === 'string' ? doneMeta.summary : undefined
    try {
      await api.reviewReportSave({
        as_of: reportAsOf,
        focus,
        content: fullContent,
        summary: summaryStr,
        emotion_score: doneMeta?.emotion_score ?? null,
        emotion_label: doneMeta?.emotion_label ?? '',
        skill_id: doneMeta?.skill_id ?? null,
        skill_name: doneMeta?.skill_name ?? null,
        skill_params: doneMeta?.skill_params ?? null,
        model: doneMeta?.model ?? null,
        usage: doneMeta?.usage ?? null,
        duration_ms: doneMeta?.duration_ms ?? null,
      })
      qc.invalidateQueries({ queryKey: QK.reviewReports })
    } catch { /* 静默 */ }
  }, [focus, asOf, marketQuery.data, qc])

  // 主流程:生成复盘(委托给全局 store,流在后台独立运行)
  const generate = useCallback(() => {
    if (isTabGenerating(activeTab)) return
    setViewing(null)
    resetTab(activeTab)
    // 从 skillStore 读取当前选中的 skill 和参数
    const skillState = getSkillState(activeTab)
    startGeneration(activeTab, focus, {
      skillId: skillState.selectedId ?? undefined,
      skillParams: skillState.params,
      onDone: (full, doneMeta) => {
        // 自动归档仅 market tab 触发(holdings/settlement 由后端归档)
        if (activeTab === 'market') {
          onGenerationDone(full, doneMeta).catch(() => { /* 静默 */ })
        }
      },
    })
  }, [activeTab, focus, onGenerationDone])

  // 复制全文到剪贴板(viewing 优先,与主区域显示一致)
  const copyContent = useCallback(async () => {
    const text = viewing?.content ?? content
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast('已复制到剪贴板', 'success')
    } catch {
      toast('复制失败,请手动选择文本', 'error')
    }
  }, [content, viewing])

  // 下载为 .md 文件(viewing 优先)
  const downloadContent = useCallback(() => {
    const text = viewing?.content ?? content
    if (!text) return
    const reportDate = viewing?.as_of ?? displayMeta?.as_of ?? asOf ?? new Date().toISOString().slice(0, 10)
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `复盘_${reportDate}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [content, viewing, meta, asOf])

  // 查看历史报告(不中断后台生成:仅临时把 viewing 覆盖到主区域,
  // 生成中的流仍在 store 里继续跑,点"生成中"项即可切回)
  const viewReport = useCallback((r: any) => {
    setViewing(r)
  }, [])

  const isGenerating = phase === 'loading' || phase === 'streaming'
  const displayDate = viewing?.as_of ?? displayMeta?.as_of ?? (activeTab === 'market' ? marketQuery.data?.as_of : undefined) ?? asOf ?? '最新'
  const marketData = marketQuery.data
  // 主区域显示的内容:viewing(查看历史)优先于 store 的生成 content,
  // 这样点历史报告不会覆盖后台生成中的流。
  const displayContent = viewing?.content ?? content
  const tabConfig = TAB_CONFIG[activeTab]

  // market tab 的数据门控:无数据时显示引导;holdings/settlement 始终渲染主区域
  const marketBlocked = activeTab === 'market' && (marketQuery.isLoading && !marketData || !marketData || !marketData.as_of)

  return (
    <>
      <PageHeader
        title="AI 复盘"
        titleExtra={<Sparkles className="h-4 w-4 text-accent" />}
        subtitle={
          activeTab === 'market' && marketData?.emotion
            ? `${displayDate} · 情绪 ${marketData.emotion.label}`
            : displayDate
        }
        right={
          <div className="flex items-center gap-1">
            <button
              onClick={refreshData}
              disabled={refreshFetching}
              className="inline-flex items-center gap-1 rounded-btn border border-border bg-elevated px-2 py-1 text-sm text-secondary transition-colors hover:text-foreground disabled:opacity-50"
              title="刷新数据"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', refreshFetching && 'animate-spin')} />刷新
            </button>
            <button
              onClick={openSchedule}
              className={cn(
                'inline-flex items-center gap-1 rounded-btn border px-2 py-1 text-sm transition-colors',
                activeSched.enabled
                  ? 'border-accent/40 bg-accent/10 text-accent hover:bg-accent/20'
                  : 'border-border bg-elevated text-secondary hover:text-foreground',
              )}
              title={activeSched.enabled ? `定时${TAB_CONFIG[activeTab].label}已开启 · 每日 ${String(activeSched.hour).padStart(2,'0')}:${String(activeSched.minute).padStart(2,'0')}` : `定时${TAB_CONFIG[activeTab].label}`}
            >
              <Clock className="h-3.5 w-3.5" />定时
            </button>
            <button
              onClick={generate}
              disabled={isGenerating}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-btn px-3.5 py-1.5 text-xs font-medium transition-all',
                isGenerating
                  ? 'border border-accent/40 bg-accent/10 text-accent cursor-not-allowed'
                  : 'bg-accent text-white shadow-sm shadow-accent/25 hover:bg-accent/90 hover:shadow hover:shadow-accent/30',
              )}
            >
              {isGenerating ? (
                <><RefreshCw className="h-3.5 w-3.5 animate-spin" />生成中…</>
              ) : (
                <><Sparkles className="h-3.5 w-3.5" />{tabConfig.generateText}</>
              )}
            </button>
            {isGenerating && (
              <button
                onClick={() => abortGeneration(activeTab)}
                className="inline-flex items-center gap-1.5 rounded-btn border border-border bg-elevated px-3 py-1.5 text-xs font-medium text-secondary transition-colors hover:bg-danger/10 hover:text-danger"
                title="停止当前生成(保留已生成内容)"
              >
                <X className="h-3.5 w-3.5" />停止
              </button>
            )}
          </div>
        }
      />

      <div className="min-h-full bg-[radial-gradient(circle_at_15%_-5%,rgba(59,130,246,0.10),transparent_30%),radial-gradient(circle_at_85%_5%,rgba(139,92,246,0.08),transparent_30%)] px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-[1280px] space-y-3">

          {/* ===== Tab 切换条 + Skill 选择器 ===== */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1 rounded-card border border-border bg-surface/80 p-1">
              {(Object.keys(TAB_CONFIG) as ReviewTab[]).map(tab => (
                <button
                  key={tab}
                  onClick={() => switchTab(tab)}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-btn px-3 py-1.5 text-xs font-medium transition-colors',
                    activeTab === tab
                      ? 'bg-accent/15 text-accent'
                      : 'text-secondary hover:text-foreground hover:bg-elevated/60',
                  )}
                >
                  {TAB_CONFIG[tab].icon}
                  {TAB_CONFIG[tab].label}
                </button>
              ))}
            </div>
            <SkillSelector
              tab={activeTab}
              paramsOpen={skillParamsOpen}
              onToggleParams={() => setSkillParamsOpen(o => !o)}
            />
          </div>

          {/* ===== Skill 参数面板(可折叠) ===== */}
          {skillParamsOpen && (
            <SkillParamsPanel tab={activeTab} />
          )}

          {marketBlocked ? (
            activeTab === 'market' && marketQuery.isLoading && !marketData ? (
              <div className="flex h-40 items-center justify-center">
                <div className="flex items-center gap-2 text-sm text-muted">
                  <RefreshCw className="h-4 w-4 animate-spin" /> 加载市场数据…
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center gap-4 rounded-card border border-border bg-surface/80 px-6 py-16">
                <div className="relative">
                  <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-accent/20 to-purple-500/15 border border-accent/30">
                    <Database className="h-6 w-6 text-accent" strokeWidth={1.8} />
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-sm font-medium text-foreground">暂无市场数据</div>
                  <p className="mt-1 text-xs text-muted">复盘需要日 K 与指数,请先前往「数据」页同步</p>
                </div>
                <Link
                  to="/data"
                  className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-4 py-2 text-xs font-medium text-white shadow-sm transition-all hover:bg-accent/90 hover:shadow"
                >
                  <Database className="h-3.5 w-3.5" />前往数据页同步
                  <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            )
          ) : (
            <>
              {/* ===== 摘要条(各 tab 不同)===== */}
              {activeTab === 'market' && marketData && <MarketSummaryBar data={marketData} />}
              {activeTab === 'holdings' && <HoldingsSummaryBar />}
              {activeTab === 'settlement' && <SettlementSummaryBar />}

              {/* ===== 关注点输入 ===== */}
              <div className="flex items-center gap-2 rounded-card border border-border bg-surface/80 px-3.5 py-2.5 transition-colors focus-within:border-accent/40">
                <Wand2 className="h-3.5 w-3.5 shrink-0 text-accent" />
                <input
                  value={focus}
                  onChange={(e) => setFocus(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !isGenerating) generate() }}
                  placeholder={tabConfig.placeholder}
                  className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted/60"
                />
                {focus && (
                  <button onClick={() => setFocus('')} className="text-xs text-muted transition-colors hover:text-foreground">清除</button>
                )}
              </div>

              {/* ===== 报告 + 历史 双栏(报告为主体)===== */}
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_22rem]">
                <ReportPanel
                  tab={activeTab}
                  tabConfig={tabConfig}
                  phase={phase}
                  content={displayContent}
                  error={error}
                  isGenerating={isGenerating}
                  viewing={viewing}
                  stats={displayMeta}
                  onCopy={copyContent}
                  onDownload={downloadContent}
                  onRegenerate={generate}
                  reportEndRef={reportEndRef}
                />
                <HistoryPanel
                  tab={activeTab}
                  reports={historyReports}
                  loading={historyLoading}
                  viewingId={viewing?.id ?? null}
                  generating={isGenerating}
                  onView={viewReport}
                  onBackToGenerating={() => setViewing(null)}
                  onDelete={handleDelete}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* ===== 定时复盘设置弹窗(三 tab 独立配置)===== */}
      <AnimatePresence>
        {showSchedule && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => setShowSchedule(false)}
          >
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.96, opacity: 0 }}
              className="w-full max-w-md rounded-card border border-border bg-surface p-5 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-accent" />
                  <h3 className="text-sm font-medium text-foreground">定时复盘设置</h3>
                </div>
                <button
                  onClick={() => setShowSchedule(false)}
                  className="rounded p-1 text-muted transition-colors hover:bg-elevated hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* 类型切换器:大盘 / 持仓 / 交割单 */}
              <div className="mb-4 grid grid-cols-3 gap-1 rounded-btn bg-elevated/50 p-1">
                {(['market', 'holdings', 'settlement'] as ReviewTab[]).map(t => (
                  <button
                    key={t}
                    onClick={() => setScheduleTab(t)}
                    className={cn(
                      'flex items-center justify-center gap-1 rounded px-2 py-1.5 text-sm font-medium transition-colors',
                      scheduleTab === t ? 'bg-surface text-accent shadow-sm' : 'text-muted hover:text-foreground',
                    )}
                  >
                    {TAB_CONFIG[t].icon}
                    {TAB_CONFIG[t].label.replace('复盘', '').replace('分析', '')}
                  </button>
                ))}
              </div>

              {(() => {
                const d = draftFor(scheduleTab)
                const channels = pushChannelsFor(scheduleTab)
                const tabLabel = TAB_CONFIG[scheduleTab].label
                return (
                  <>
                    <p className="mb-4 text-sm leading-relaxed text-muted">
                      开启后,每个交易日到点自动生成{scheduleTab === 'market' ? '大盘复盘' : scheduleTab === 'holdings' ? '持仓分析' : '交割单分析'}报告并归档,静默执行。
                      下次打开本页即可在历史列表看到新报告;也可选推送到飞书/企业微信。
                    </p>

                    {/* 开关(只改本地草稿) */}
                    <label className="flex items-center justify-between rounded-btn bg-elevated/40 px-3 py-2.5">
                      <span className="text-sm text-foreground">启用定时{tabLabel}</span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={d.enabled}
                        onClick={() => setDraftFor(scheduleTab, { enabled: !d.enabled })}
                        className={cn(
                          'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                          d.enabled ? 'bg-accent' : 'bg-border',
                        )}
                      >
                        <span className={cn('inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform', d.enabled ? 'translate-x-[18px]' : 'translate-x-1')} />
                      </button>
                    </label>

                    {/* 时间设置(仅开启时可编辑) */}
                    {d.enabled && (
                      <div className="mt-3 flex items-center gap-2 rounded-btn bg-elevated/40 px-3 py-2.5">
                        <span className="text-sm text-muted">每日</span>
                        <input
                          type="number" min={0} max={23} value={d.hour}
                          onChange={e => setDraftFor(scheduleTab, { hour: Math.max(0, Math.min(23, Number(e.target.value))) })}
                          className="w-12 px-1.5 py-1 rounded-btn bg-base border border-border text-xs font-mono text-foreground text-center focus:outline-none focus:border-accent/50"
                        />
                        <span className="text-sm text-muted">:</span>
                        <input
                          type="number" min={0} max={59} value={d.minute}
                          onChange={e => setDraftFor(scheduleTab, { minute: Math.max(0, Math.min(59, Number(e.target.value))) })}
                          className="w-12 px-1.5 py-1 rounded-btn bg-base border border-border text-xs font-mono text-foreground text-center focus:outline-none focus:border-accent/50"
                        />
                        <span className="text-sm text-muted/70">不早于 15:00 · 工作日执行</span>
                      </div>
                    )}

                    {/* 推送渠道(独立常驻) */}
                    <div className="mt-3 rounded-btn bg-elevated/40 px-3 py-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-foreground">生成后推送完整报告</span>
                        <span className="text-sm text-muted/70">{channels.length === 0 ? '未开启' : `${channels.length} 个渠道`}</span>
                      </div>
                      <div className="mt-2 space-y-1.5">
                        <button
                          type="button"
                          disabled={pushMut.isPending}
                          onClick={() => togglePushChannel(scheduleTab, 'feishu')}
                          className={cn(
                            'flex w-full items-center gap-2 rounded-btn border px-2.5 py-1.5 text-left transition-colors disabled:opacity-50',
                            channels.includes('feishu')
                              ? 'border-accent/40 bg-accent/10'
                              : 'border-border/60 bg-base/40 hover:bg-base/60',
                          )}
                        >
                          <span className={cn('flex h-3 w-3 shrink-0 items-center justify-center rounded border', channels.includes('feishu') ? 'border-accent bg-accent text-white' : 'border-border')}>
                            {channels.includes('feishu') && <Check className="h-2.5 w-2.5" />}
                          </span>
                          <span className="text-sm text-foreground">飞书</span>
                          <span className="text-xs text-muted">群推送 Webhook</span>
                          <span className={cn('ml-auto text-xs', feishuConfigured ? 'text-emerald-500' : 'text-warning')}>
                            {feishuConfigured ? '已配置' : '未配置'}
                          </span>
                        </button>
                        <button
                          type="button"
                          disabled={pushMut.isPending}
                          onClick={() => togglePushChannel(scheduleTab, 'wecom')}
                          className={cn(
                            'flex w-full items-center gap-2 rounded-btn border px-2.5 py-1.5 text-left transition-colors disabled:opacity-50',
                            channels.includes('wecom')
                              ? 'border-accent/40 bg-accent/10'
                              : 'border-border/60 bg-base/40 hover:bg-base/60',
                          )}
                        >
                          <span className={cn('flex h-3 w-3 shrink-0 items-center justify-center rounded border', channels.includes('wecom') ? 'border-accent bg-accent text-white' : 'border-border')}>
                            {channels.includes('wecom') && <Check className="h-2.5 w-2.5" />}
                          </span>
                          <span className="text-sm text-foreground">企业微信</span>
                          <span className="text-xs text-muted">群推送 Webhook</span>
                          <span className={cn('ml-auto text-xs', wecomConfigured ? 'text-emerald-500' : 'text-warning')}>
                            {wecomConfigured ? '已配置' : '未配置'}
                          </span>
                        </button>
                      </div>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted/70">
                        手动或定时生成的{scheduleTab === 'market' ? '复盘' : '分析'}都会推送完整报告。复用「设置 → 实时监控」的 Webhook 配置。
                        {((channels.includes('feishu') && !feishuConfigured) || (channels.includes('wecom') && !wecomConfigured)) && (
                          <Link to="/settings?tab=monitoring" className="ml-1 text-accent hover:underline" onClick={() => setShowSchedule(false)}>
                            前往配置 →
                          </Link>
                        )}
                      </p>
                    </div>

                    {!d.enabled && (
                      <p className="mt-3 text-sm text-muted/70">
                        当前: 已关闭。开启后将按设定时间自动{tabLabel}。
                      </p>
                    )}

                    {/* 操作区 */}
                    <div className="mt-5 flex justify-end gap-2">
                      <button
                        onClick={() => setShowSchedule(false)}
                        className="rounded-btn bg-elevated px-4 py-1.5 text-sm text-secondary transition-colors hover:text-foreground"
                      >
                        取消
                      </button>
                      <button
                        onClick={() => reviewMut.mutate({ tab: scheduleTab, enabled: d.enabled, hour: d.hour, minute: d.minute })}
                        disabled={reviewMut.isPending}
                        className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
                      >
                        {reviewMut.isPending ? '保存中…' : '保存'}
                      </button>
                    </div>
                  </>
                )
              })()}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}

// ================================================================
// 市场摘要条 —— 复盘页的轻量上下文(非重复看板)
// 仅一行:三大指数涨跌 · 情绪分 · 涨停结构 · 成交额
// 详细数据请去 Dashboard 看,这里只给 AI 报告提供背景参照
// ================================================================
// 指数简称映射:全称太长(上证指数/深证成指/创业板指/科创综指)摘要条放不下,统一缩成单字
const INDEX_SHORT: Record<string, string> = {
  '上证指数': '上', '深证成指': '深', '创业板指': '创', '科创综指': '科', '科创50': '科',
}
function indexShort(name?: string | null, symbol?: string): string {
  if (!name) return symbol ?? '—'
  return INDEX_SHORT[name] ?? (name.replace(/指数|成指|A股|综指|50/g, '').slice(0, 2) || name.slice(0, 1))
}

// 批量替换文本中的指数全称为简称(用于历史列表 summary 显示,
// 兼容存量旧报告 —— 它们存盘时 summary 还是全称)。
const _INDEX_FULL_RE = /上证指数|深证成指|创业板指|科创综指|科创50/g
function shortenIndexNames(text: string): string {
  return text.replace(_INDEX_FULL_RE, (m) => INDEX_SHORT[m] ?? m)
}

// 从 summary 的指数段(如「上-2.26%、深-3.44%、创-4.07%、科-2.02%」)
// 解析出 [{name, pctStr, pctNum}],供列表项按涨跌染色渲染。
const _INDEX_PCT_RE = /([上深创科])([+-]?\d+\.\d+%)/g
function parseIndexPcts(indexSegment: string): { name: string; pctStr: string; pctNum: number }[] {
  const out: { name: string; pctStr: string; pctNum: number }[] = []
  for (const m of indexSegment.matchAll(_INDEX_PCT_RE)) {
    out.push({ name: m[1], pctStr: m[2], pctNum: parseFloat(m[2]) })
  }
  return out
}

function MarketSummaryBar({ data }: { data: OverviewMarket }) {
  const score = data.emotion?.score ?? null
  const emoColor = scoreColor(score)
  const indices = (data.indices ?? []).slice(0, 4)

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-border bg-surface/80 px-4 py-2.5">
      {/* 情绪分(带色徽章)—— 复盘的核心定调 */}
      <div className="flex items-center gap-2">
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded font-mono text-xs font-bold tabular-nums"
          style={{ color: emoColor, backgroundColor: `${emoColor}1a` }}
        >
          {score ?? '—'}
        </span>
        <div className="leading-tight">
          <div className="text-sm font-medium text-foreground">{data.emotion?.label ?? '情绪'}</div>
          <div className="text-xs text-secondary">情绪温度</div>
        </div>
      </div>

      <div className="hidden h-7 w-px bg-border sm:block" />

      {/* 四大指数(简称:上深创科)*/}
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        {indices.map(idx => (
          <div key={idx.symbol} className="flex items-center gap-1">
            <span className="text-sm text-secondary">{indexShort(idx.name, idx.symbol)}</span>
            <span className={cn('font-mono text-sm font-semibold tabular-nums', pctClass(idx.change_pct))}>
              {fmtPctAlready(idx.change_pct, 2, true)}
            </span>
          </div>
        ))}
      </div>

      <div className="hidden h-7 w-px bg-border sm:block" />

      {/* 涨跌结构 */}
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">涨跌</span>
        <span className="font-mono font-semibold text-bull">{data.breadth?.up ?? 0}</span>
        <span className="text-muted">/</span>
        <span className="font-mono font-semibold text-bear">{data.breadth?.down ?? 0}</span>
      </div>

      {/* 涨停结构 */}
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">涨停</span>
        <span className="font-mono font-semibold text-bull">{data.limit?.limit_up ?? 0}</span>
        <span className="text-secondary">封板 {(data.limit?.seal_rate ?? 0).toFixed(0)}%</span>
      </div>

      {/* 成交额 */}
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">成交</span>
        <span className="font-mono font-semibold text-foreground">{fmtBigNum(data.amount?.total)}</span>
      </div>
    </div>
  )
}

// ================================================================
// 持仓摘要条 —— holdings tab 的轻量上下文
// 汇总持仓数量、总市值、浮盈亏(从 positionsEnriched 聚合)
// ================================================================
function HoldingsSummaryBar() {
  const { data, isLoading } = useQuery({
    queryKey: QK.positionsEnriched(),
    queryFn: () => api.positionsEnriched(),
  })

  const rows = data?.rows ?? []
  let mv = 0
  let pnl = 0
  const count = rows.length
  for (const r of rows) {
    const price = Number(r.close)
    const shares = Number(r.shares) || 0
    const costPrice = Number(r.cost_price) || 0
    if (Number.isFinite(price) && price > 0) {
      mv += price * shares
      if (costPrice > 0) pnl += (price - costPrice) * shares
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-border bg-surface/80 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded bg-accent/15 text-accent">
          <Wallet className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <div className="text-sm font-medium text-foreground">
            {isLoading ? '…' : `${count} 只持仓`}
          </div>
          <div className="text-xs text-secondary">持仓概览</div>
        </div>
      </div>
      <div className="hidden h-7 w-px bg-border sm:block" />
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">总市值</span>
        <span className="font-mono font-semibold text-foreground">{fmtBigNum(mv)}</span>
      </div>
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">浮盈亏</span>
        <span className={cn('font-mono font-semibold', pnl > 0 ? 'text-bull' : pnl < 0 ? 'text-bear' : 'text-muted')}>
          {pnl >= 0 ? '+' : ''}{fmtBigNum(Math.abs(pnl))}
        </span>
      </div>
    </div>
  )
}

// ================================================================
// 交割单摘要条 —— settlement tab 的轻量上下文
// 展示记录数、买入/卖出笔数、已实现盈亏、费用
// ================================================================
function SettlementSummaryBar() {
  const { data, isLoading } = useQuery<SettlementStats>({
    queryKey: QK.settlementStats,
    queryFn: () => api.settlementStats(),
  })
  const s = data?.summary
  const realized = data?.realized_pnl_curve?.at(-1)?.cumulative ?? 0

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-card border border-border bg-surface/80 px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded bg-accent/15 text-accent">
          <Receipt className="h-4 w-4" />
        </span>
        <div className="leading-tight">
          <div className="text-sm font-medium text-foreground">
            {isLoading ? '…' : `${data?.records_count ?? 0} 条记录`}
          </div>
          <div className="text-xs text-secondary">交割单概览</div>
        </div>
      </div>
      <div className="hidden h-7 w-px bg-border sm:block" />
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">买入</span>
        <span className="font-mono font-semibold text-bull">{s?.buy_count ?? 0}</span>
        <span className="text-secondary ml-2">卖出</span>
        <span className="font-mono font-semibold text-bear">{s?.sell_count ?? 0}</span>
      </div>
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">已实现盈亏</span>
        <span className={cn('font-mono font-semibold', realized > 0 ? 'text-bull' : realized < 0 ? 'text-bear' : 'text-muted')}>
          {realized >= 0 ? '+' : ''}{fmtBigNum(Math.abs(realized))}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-secondary">费用</span>
        <span className="font-mono font-semibold text-muted">{fmtBigNum(s?.total_fees ?? 0)}</span>
      </div>
    </div>
  )
}

// ================================================================
// 报告面板(流式 + 错误 + 历史/完成态)
// ================================================================
function ReportPanel({
  tab, tabConfig, phase, content, error, isGenerating, viewing, stats, onCopy, onDownload, onRegenerate, reportEndRef,
}: {
  tab: ReviewTab
  tabConfig: typeof TAB_CONFIG[ReviewTab]
  phase: ReviewPhase
  content: string
  error: string
  isGenerating: boolean
  viewing: any | null
  stats: any | null
  onCopy: () => void
  onDownload: () => void
  onRegenerate: () => void
  reportEndRef: React.RefObject<HTMLDivElement>
}) {
  if (phase === 'error') {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-card border border-border bg-surface/80 px-6 py-14">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-danger/10">
          <AlertTriangle className="h-5 w-5 text-danger" />
        </div>
        <div className="text-sm font-medium text-foreground">复盘失败</div>
        <div className="max-w-md text-center text-sm text-secondary">{error || '请检查 AI 配置后重试'}</div>
        <button
          onClick={onRegenerate}
          className="mt-1 inline-flex items-center gap-1.5 rounded-btn bg-accent/15 px-3 py-1.5 text-sm text-accent transition-colors hover:bg-accent/20"
        >
          <RefreshCw className="h-3.5 w-3.5" />重新生成
        </button>
      </div>
    )
  }

  if (phase === 'idle' && !content) {
    return (
      <div className="flex min-h-[28rem] flex-col items-center justify-center gap-5 rounded-card border border-border bg-surface/80 px-6 py-16">
        <div className="relative">
          <div className="grid h-20 w-20 place-items-center rounded-2xl bg-gradient-to-br from-accent/20 to-purple-500/15 border border-accent/30">
            <BookOpenCheck className="h-9 w-9 text-accent" strokeWidth={1.8} />
          </div>
          <Sparkles className="absolute -right-1 -top-1 h-5 w-5 text-accent" />
        </div>
        <div className="text-center">
          <div className="text-base font-semibold text-foreground">{tabConfig.emptyTitle}</div>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-secondary">
            {tabConfig.emptyDesc}
          </p>
        </div>
        {/* 报告七节预览 —— 仅 market tab 显示,空状态也有内容感,暗示报告结构 */}
        {tab === 'market' && (
          <div className="mt-2 grid w-full max-w-md grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { icon: '🎯', label: '一句话定调' },
              { icon: '📊', label: '盘面总览' },
              { icon: '🔥', label: '板块主线' },
              { icon: '💰', label: '资金情绪' },
              { icon: '📰', label: '消息催化' },
              { icon: '🎯', label: '明日计划' },
              { icon: '⚠️', label: '风险提示' },
            ].map((s) => (
              <div key={s.label} className="flex flex-col items-center gap-1 rounded-btn bg-elevated/40 px-2 py-2">
                <span className="text-base">{s.icon}</span>
                <span className="text-sm text-secondary">{s.label}</span>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 flex items-center gap-1.5 text-sm text-muted">
          <Sparkles className="h-3.5 w-3.5 text-accent" />
          点击右上角「{tabConfig.generateText}」开始
        </div>
      </div>
    )
  }

  // 仅当显示生成内容(非查看历史)且正在生成时,才显示流式光标
  const showCursor = isGenerating && !viewing
  // 查看历史时(即使后台在生成)也能复制/下载该历史报告
  const showActions = !!content && (!isGenerating || !!viewing)
  const showViewingTag = !!viewing
  const isLoading = phase === 'loading' && !content

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="overflow-hidden rounded-card border border-border bg-surface/80"
    >
      <div className="flex items-center justify-between border-b border-border bg-gradient-to-r from-accent/5 to-transparent px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          {isGenerating ? <RefreshCw className="h-3.5 w-3.5 animate-spin text-accent" /> : <BookOpenCheck className="h-3.5 w-3.5 text-accent" />}
          <span className="text-sm font-medium text-foreground">
            {showViewingTag ? `历史 · ${viewing!.as_of}` : isGenerating ? tabConfig.loadingText : '报告'}
          </span>
        </div>
        {showActions && (
          <div className="flex items-center gap-1">
            <button onClick={onCopy} className="inline-flex items-center gap-1 rounded-btn bg-elevated px-2 py-1 text-sm text-secondary transition-colors hover:text-foreground hover:bg-elevated/70" title="复制全文">
              <Copy className="h-3.5 w-3.5" />复制
            </button>
            <button onClick={onDownload} className="inline-flex items-center gap-1 rounded-btn bg-elevated px-2 py-1 text-sm text-secondary transition-colors hover:text-foreground hover:bg-elevated/70" title="下载为 Markdown">
              <Download className="h-3.5 w-3.5" />下载
            </button>
          </div>
        )}
      </div>
      <div className="max-h-[calc(100vh-22rem)] overflow-y-auto px-5 py-4">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <div className="relative">
              <div className="grid h-11 w-11 place-items-center rounded-full bg-gradient-to-br from-accent/20 to-purple-500/15 border border-accent/30">
                <Sparkles className="h-5 w-5 animate-pulse text-accent" />
              </div>
              <RefreshCw className="absolute -inset-1 h-13 w-13 animate-spin text-accent/30" style={{ animationDuration: '3s' }} />
            </div>
            <div className="text-sm text-foreground">{tabConfig.loadingText}</div>
            <div className="text-sm text-secondary">分析指数结构 · 连板梯队 · 板块轮动 · 资金情绪</div>
          </div>
        ) : (
          <div className="prose prose-invert max-w-none">
            <MarkdownRenderer content={content} />
            {showCursor && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-accent align-middle" />
            )}
          </div>
        )}
        <div ref={reportEndRef} />
      </div>
      {stats && (stats.duration_ms != null || stats.usage?.total_tokens) && (
        <div className="flex items-center gap-3 border-t border-border px-5 py-2 text-xs text-muted">
          {stats.duration_ms != null && (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />耗时 {(stats.duration_ms / 1000).toFixed(1)}s
            </span>
          )}
          {stats.usage?.total_tokens != null && stats.usage.total_tokens > 0 && (
            <span>约 {stats.usage.total_tokens.toLocaleString()} tokens</span>
          )}
        </div>
      )}
    </motion.div>
  )
}

// ================================================================
// 历史面板 —— 按 tab 渲染不同结构的报告条目
//  - market:     情绪分徽章 + 情绪标签 + 指数涨跌 summary
//  - holdings:   持仓数徽章 + 总市值/浮盈亏
//  - settlement: 记录数徽章 + 交易笔数/已实现盈亏
// ================================================================
function HistoryPanel({
  tab, reports, loading, viewingId, generating, onView, onBackToGenerating, onDelete,
}: {
  tab: ReviewTab
  reports: any[]
  loading: boolean
  viewingId: string | null
  generating: boolean
  onView: (r: any) => void
  onBackToGenerating: () => void
  onDelete: (id: string) => void
}) {
  const tabConfig = TAB_CONFIG[tab]
  const empty = !generating && reports.length === 0
  return (
    <div className="overflow-hidden rounded-card border border-border bg-surface/80">
      <div className="flex items-center gap-1.5 border-b border-border bg-gradient-to-r from-accent/5 to-transparent px-3 py-2.5">
        <History className="h-4 w-4 text-accent" />
        <span className="text-sm font-medium text-foreground">{tabConfig.historyLabel}</span>
        <span className="font-mono text-sm text-muted">({reports.length})</span>
      </div>
      <div className="max-h-[calc(100vh-26rem)] overflow-y-auto p-2">
        {loading ? (
          <div className="grid h-20 place-items-center"><RefreshCw className="h-4 w-4 animate-spin text-muted" /></div>
        ) : empty ? (
          <div className="flex flex-col items-center justify-center gap-2 px-3 py-10 text-center">
            <History className="h-7 w-7 text-muted/40" strokeWidth={1.5} />
            <div className="text-sm text-muted">暂无{tabConfig.historyLabel}</div>
            <div className="text-sm text-muted/60">生成完成后自动归档</div>
          </div>
        ) : (
          <div className="space-y-1.5">
            {/* 生成中占位项:列表顶部,点击回到正在生成的流式内容 */}
            {generating && (
              <div
                className={cn(
                  'flex items-start gap-2.5 rounded px-2 py-2.5 cursor-pointer transition-colors',
                  viewingId === null ? 'bg-accent/10 ring-1 ring-accent/20' : 'hover:bg-elevated/60',
                )}
                onClick={onBackToGenerating}
              >
                <div className="grid h-9 w-9 shrink-0 place-items-center rounded bg-accent/15">
                  <RefreshCw className="h-4 w-4 animate-spin text-accent" />
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="truncate text-sm font-medium text-accent">生成中…</div>
                  <div className="text-sm text-secondary">{tabConfig.loadingText}</div>
                </div>
              </div>
            )}
            {reports.map((r) => {
              // 各 tab 徽章 / 副信息不同
              let badge: React.ReactNode = null
              let primary: React.ReactNode = null
              let secondary: React.ReactNode = null

              if (tab === 'market') {
                const color = scoreColor(r.emotion_score)
                badge = (
                  <div
                    className="grid h-9 w-9 shrink-0 place-items-center rounded font-mono text-xs font-bold tabular-nums"
                    style={{ color, backgroundColor: `${color}1a` }}
                  >
                    {r.emotion_score ?? '—'}
                  </div>
                )
                primary = (
                  <>
                    <span className="truncate text-sm font-medium text-foreground">{r.emotion_label ?? '—'}</span>
                    <span className="font-mono text-sm text-secondary">{r.as_of}</span>
                  </>
                )
                secondary = r.summary
                  ? (() => {
                      const pcts = parseIndexPcts(shortenIndexNames(r.summary).split('|')[0])
                      if (pcts.length === 0) {
                        return <span className="truncate text-sm text-secondary">{r.content.slice(0, 40)}</span>
                      }
                      return (
                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                          {pcts.map((p) => (
                            <span key={p.name} className="inline-flex items-center gap-0.5 text-sm">
                              <span className="text-secondary">{p.name}</span>
                              <span className={cn('font-mono font-medium tabular-nums', pctClass(p.pctNum))}>{p.pctStr}</span>
                            </span>
                          ))}
                        </div>
                      )
                    })()
                  : <span className="truncate text-sm text-secondary">{r.content.slice(0, 40)}</span>
              } else if (tab === 'holdings') {
                const countVal = r.summary?.count ?? r.count ?? 0
                const totalMv = r.summary?.total_market_value
                const pnlPct = r.summary?.total_pnl_pct
                badge = (
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded bg-accent/15 font-mono text-xs font-bold tabular-nums text-accent">
                    {countVal}
                  </div>
                )
                primary = (
                  <>
                    <span className="truncate text-sm font-medium text-foreground">{r.as_of}</span>
                    <span className="text-sm text-secondary">持仓复盘</span>
                  </>
                )
                secondary = (
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    {totalMv != null && (
                      <span className="inline-flex items-center gap-0.5 text-sm">
                        <span className="text-secondary">市值</span>
                        <span className="font-mono font-medium text-foreground">{fmtBigNum(totalMv)}</span>
                      </span>
                    )}
                    {pnlPct != null && (
                      <span className="inline-flex items-center gap-0.5 text-sm">
                        <span className="text-secondary">盈亏</span>
                        <span className={cn('font-mono font-medium tabular-nums', pctClass(pnlPct))}>{fmtPctAlready(pnlPct, 2, true)}</span>
                      </span>
                    )}
                  </div>
                )
              } else {
                // settlement
                const recordsCount = r.summary?.records_count ?? r.count ?? 0
                const totalTrades = r.summary?.total_trades ?? 0
                const realized = r.summary?.total_realized_pnl
                badge = (
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded bg-accent/15 font-mono text-xs font-bold tabular-nums text-accent">
                    {recordsCount}
                  </div>
                )
                primary = (
                  <>
                    <span className="truncate text-sm font-medium text-foreground">{r.as_of}</span>
                    <span className="text-sm text-secondary">交割单分析</span>
                  </>
                )
                secondary = (
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    {totalTrades != null && totalTrades > 0 && (
                      <span className="inline-flex items-center gap-0.5 text-sm">
                        <span className="text-secondary">交易</span>
                        <span className="font-mono font-medium text-foreground">{totalTrades}</span>
                      </span>
                    )}
                    {realized != null && (
                      <span className="inline-flex items-center gap-0.5 text-sm">
                        <span className="text-secondary">盈亏</span>
                        <span className={cn('font-mono font-medium tabular-nums', realized > 0 ? 'text-bull' : realized < 0 ? 'text-bear' : 'text-muted')}>
                          {realized >= 0 ? '+' : ''}{fmtBigNum(Math.abs(realized))}
                        </span>
                      </span>
                    )}
                  </div>
                )
              }

              return (
                <div
                  key={r.id}
                  className={cn(
                    'group flex items-start gap-2.5 rounded px-2 py-2.5 cursor-pointer transition-colors',
                    viewingId === r.id ? 'bg-accent/10 ring-1 ring-accent/20' : 'hover:bg-elevated/60',
                  )}
                  onClick={() => onView(r)}
                >
                  {badge}
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-1.5">
                      {primary}
                    </div>
                    {(() => {
                      const badgeText = r.skill_name ?? r.skill_id ?? '默认 Prompt'
                      const hasSkill = !!(r.skill_name || r.skill_id)
                      return (
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={cn(
                              'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                              hasSkill
                                ? 'bg-accent/10 text-accent'
                                : 'bg-elevated text-muted',
                            )}
                            title={hasSkill ? `Skill: ${r.skill_id ?? r.skill_name}` : '使用默认硬编码 Prompt 生成'}
                          >
                            {badgeText}
                          </span>
                          {r.model && (
                            <span
                              className="inline-flex items-center rounded-full bg-bear/15 px-2.5 py-0.5 text-xs font-medium text-bear"
                              title={`AI 模型: ${r.model}`}
                            >
                              {r.model}
                            </span>
                          )}
                        </div>
                      )
                    })()}
                    <div className="text-sm">{secondary}</div>
                    {r.created_at && (
                      <div className="font-mono text-xs text-muted">{fmtArchivedAt(r.created_at)}</div>
                    )}
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDelete(r.id) }}
                    className="mt-0.5 shrink-0 p-1 text-muted opacity-0 transition-all hover:text-bear group-hover:opacity-100"
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
  )
}
