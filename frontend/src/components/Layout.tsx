import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { useQuoteStream } from '@/lib/useQuoteStream'
import { ToastContainer } from '@/components/Toast'
import { AlertToastContainer } from '@/components/AlertToast'
import { AiAnalysisHost } from '@/components/financials/AiAnalysisHost'
import { AiReportBubble } from '@/components/financials/AiReportBubble'
import {
  useCapabilities,
  useSettings,
  usePreferences,
  useQuoteStatus,
  useVersion,
} from '@/lib/useSharedQueries'
import {
  useToggleRealtimeQuotes,
} from '@/lib/useSharedMutations'
import { QK } from '@/lib/queryKeys'
import { tierRank } from '@/lib/capability-labels'
import {
  Star,
  ScanSearch,
  History,
  FileText,
  Settings,
  Key,
  Database,
  Timer,
  Loader2,
  LayoutDashboard,
  Tags,
  TrendingUp,
  Flame,
  BarChart3,
  Sparkles,
  Layers3,
  Landmark,
  Cable,
  RadioTower,
  CheckCircle2,
  Sun,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Logo } from './Logo'
import { useTheme } from '@/lib/theme'
import { api, type IndexQuote } from '@/lib/api'
import { cn } from '@/lib/cn'
import { setCurrentTotal as setAlertTotal, useUnreadAlerts } from '@/lib/monitorBadge'

// 品牌色 — 只用于 logo / brand 区域,不影响功能语义色
const BRAND = '#8B5CF6'

const CORE_INDEXES = [
  { symbol: '000001.SH', name: '上证指数' },
  { symbol: '399001.SZ', name: '深证成指' },
  { symbol: '399006.SZ', name: '创业板指' },
  { symbol: '000680.SH', name: '科创综指' },
] as const

type CoreIndex = (typeof CORE_INDEXES)[number]

const nav = [
  { to: '/',                label: '看板',     icon: LayoutDashboard },
  { to: '/watchlist',  label: '自选',   icon: Star },
  { to: '/screener',   label: '策略',   icon: ScanSearch },
  { to: '/backtest',   label: '回测',   icon: History },
  { to: '/limit-ladder', label: '连板梯队', icon: Flame },
  { to: '/concept-analysis', label: '概念分析', icon: Layers3 },
  { to: '/industry-analysis', label: '行业分析', icon: Landmark },
  { to: '/stock-analysis',    label: '个股分析', icon: TrendingUp },
  { to: '/financials', label: '财务分析', icon: FileText },
  { to: '/indices', label: '指数', icon: BarChart3 },
  { to: '/trading', label: '交易', icon: Cable },
  { to: '/monitor', label: '监控中心', icon: RadioTower },
  { to: '/data',       label: '数据',   icon: Database },
] as const

function fmtIndexValue(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return Number(v).toFixed(2)
}

function fmtIndexPct(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
}

function indexPctClass(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return 'text-muted'
  const n = Number(v)
  if (n === 0) return 'text-foreground'
  return n > 0 ? 'text-bull' : 'text-bear'
}

/** 监控中心未读徽标 — 仅在非监控页且有未读时显示。 */
function MonitorBadge({ active }: { active: boolean }) {
  const unread = useUnreadAlerts()
  // 尊重用户设置: 可在菜单设置里关闭数字提示
  const badgeEnabled = (() => {
    try { return localStorage.getItem('monitor_badge_enabled') !== '0' } catch { return true }
  })()
  if (active || unread <= 0 || !badgeEnabled) return null
  return (
    <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-bold text-white animate-pulse">
      {unread > 99 ? '99+' : unread}
    </span>
  )
}

function SidebarIndexQuotes({ rows, items }: { rows: IndexQuote[] | undefined; items: CoreIndex[] }) {
  if (items.length === 0) return null
  const quoteBySymbol = new Map((rows ?? []).map(q => [q.symbol, q]))
  return (
    <div className="mt-2 grid grid-cols-2 gap-1.5">
      {items.map(item => {
        const q = quoteBySymbol.get(item.symbol)
        const value = q?.last_price ?? q?.close
        const pct = q?.change_pct
        return (
          <NavLink
            key={item.symbol}
            to={`/indices?symbol=${encodeURIComponent(item.symbol)}`}
            className="block rounded bg-elevated/60 px-2 py-1.5 transition-colors hover:bg-elevated"
            title={`${item.name} ${item.symbol}`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="text-[10px] text-secondary">{item.name}</span>
              <span className={`text-[10px] font-mono ${indexPctClass(pct)}`}>{fmtIndexPct(pct)}</span>
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] text-foreground/80">
              {fmtIndexValue(value)}
            </div>
          </NavLink>
        )
      })}
    </div>
  )
}

// ===== 档位卡片 =====
function TierBadge({ label, hasKey }: { label: string; hasKey?: boolean }) {
  const base = label.split(' ')[0].split('+')[0].toLowerCase()
  const isNone = base === 'none'

  const tierConfig: Record<string, {
    desc: string
    tagBg: React.CSSProperties
    dotStyle: React.CSSProperties
    labelTextStyle: React.CSSProperties
  }> = {
    none: {
      desc: '未配置 Key · 仅历史日K',
      tagBg: { background: 'rgba(113,113,122,0.15)' },
      dotStyle: { background: '#52525b' },
      labelTextStyle: { color: '#71717a' },
    },
    free: {
      desc: '基础日K · 单股查询',
      tagBg: { background: 'rgba(113,113,122,0.3)' },
      dotStyle: { background: '#71717a' },
      labelTextStyle: { color: '#a1a1aa' },
    },
    starter: {
      desc: '批量同步 · 行情池',
      tagBg: { background: 'rgba(59,130,246,0.2)' },
      dotStyle: { background: '#3b82f6' },
      labelTextStyle: { color: '#60a5fa' },
    },
    pro: {
      desc: '分钟K · 实时行情 · 盘口',
      tagBg: { background: 'linear-gradient(135deg, rgba(168,85,247,0.2), rgba(124,58,237,0.15))' },
      dotStyle: { background: 'linear-gradient(135deg, #a855f7, #7c3aed)' },
      labelTextStyle: { background: 'linear-gradient(135deg, #c084fc, #a855f7)', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' },
    },
    expert: {
      desc: 'WebSocket · 财务数据',
      tagBg: { background: 'linear-gradient(135deg, rgba(59,130,246,0.2), rgba(168,85,247,0.2), rgba(245,158,11,0.2))' },
      dotStyle: { background: 'linear-gradient(135deg, #3b82f6, #a855f7, #f59e0b)' },
      labelTextStyle: { background: 'linear-gradient(135deg, #60a5fa, #c084fc, #fbbf24)', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' },
    },
  }

  const t = tierConfig[base] || tierConfig.none
  // none 档显示中文「无」,无 label 时显示「无档」
  const displayLabel = isNone ? '无' : (label || '无')

  return (
    <NavLink
      to="/settings?tab=account"
      className="mt-2.5 group block -mx-2.5"
      title="API 设置"
    >
      <div className="relative overflow-hidden rounded-lg border border-blue-400/20 bg-gradient-to-br from-blue-500/[0.12] via-surface to-surface px-3 py-2 transition-all hover:border-blue-400/35 hover:from-blue-500/[0.16]">
        <div className="absolute -right-5 -top-6 h-14 w-14 rounded-full bg-blue-500/10 blur-2xl" />
        <div className="relative flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-400/10 text-blue-300 ring-1 ring-blue-400/20">
            <Key className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-foreground">Tide Watch</span>
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ ...t.dotStyle, ...(base === 'expert' ? { animation: 'pulse 2s infinite' } : {}) }}
              />
            </div>
            <div className="mt-0.5 truncate text-[10px] leading-tight text-muted">
              {isNone && !hasKey ? '配置 Key 解锁更多能力' : t.desc}
            </div>
          </div>
          <span
            className="inline-flex h-[18px] max-w-[68px] shrink-0 items-center overflow-hidden rounded px-1.5 text-[10px] font-bold font-mono leading-none"
            style={t.tagBg}
          >
            <span className="truncate" style={t.labelTextStyle}>{displayLabel}</span>
          </span>
          <Settings className="h-3 w-3 shrink-0 text-muted group-hover:text-blue-300 transition-colors" />
        </div>

      </div>
    </NavLink>
  )
}

function AIConfigBadge({ configured, model }: { configured?: boolean; model?: string }) {
  return (
    <NavLink
      to="/settings?tab=ai"
      className="mt-2 group block -mx-2.5"
      title="AI 配置"
    >
      <div className="relative overflow-hidden rounded-lg border border-purple-400/20 bg-gradient-to-br from-purple-500/[0.12] via-surface to-surface px-3 py-2 transition-all hover:border-purple-400/35 hover:from-purple-500/[0.16]">
        <div className="absolute -right-5 -top-6 h-14 w-14 rounded-full bg-purple-500/10 blur-2xl" />
        <div className="relative flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-purple-400/10 text-purple-300 ring-1 ring-purple-400/20">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-foreground">AI 配置</span>
              <span className={`h-1.5 w-1.5 rounded-full ${configured ? 'bg-bear' : 'bg-warning'}`} />
            </div>
            <div className="mt-0.5 truncate text-[10px] leading-tight text-muted">
              {configured ? (model || '已接入模型') : '接入策略生成模型'}
            </div>
          </div>
          <Settings className="h-3 w-3 text-muted group-hover:text-purple-300 transition-colors" />
        </div>
      </div>
    </NavLink>
  )
}

export function Layout() {
  const { theme, toggleTheme } = useTheme()

  // 侧边栏折叠状态 (持久化到 localStorage)
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('tickflow-sidebar-collapsed') === '1' } catch { return false }
  })
  const toggleCollapsed = () => {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('tickflow-sidebar-collapsed', next ? '1' : '0') } catch { /* */ }
      return next
    })
  }

  // ===== 共享 hooks (替代内联 useQuery) =====
  const { data: caps } = useCapabilities()
  const { data: settingsState } = useSettings()
  const { data: versionData } = useVersion()
  const { data: prefs } = usePreferences()
  const { data: quoteStatus } = useQuoteStatus()
  const { data: analysisMenus } = useQuery({
    queryKey: QK.analysisMenus,
    queryFn: api.analysisMenus,
  })

  // 数据同步状态轮询: 有活跃 job 时「数据」菜单项显示转圈
  const { data: pipelineJobs } = useQuery({
    queryKey: QK.pipelineJobs,
    queryFn: () => api.pipelineJobs(1),
    refetchInterval: (query) => (query.state.data?.active_id ? 2000 : 15000),
    refetchIntervalInBackground: true,
  })
  const isDataSyncing = !!pipelineJobs?.active_id

  // 数据同步完成的"瞬时反馈": isDataSyncing 从 true→false 时显示绿色对勾,
  // 闪烁约 3 秒后自动消失。
  const [dataSyncJustDone, setDataSyncJustDone] = useState(false)
  const prevSyncingRef = useRef(false)
  useEffect(() => {
    // 仅在"刚结束"(true→false)且非首次挂载时触发
    if (prevSyncingRef.current && !isDataSyncing) {
      setDataSyncJustDone(true)
      const t = setTimeout(() => setDataSyncJustDone(false), 3000)
      prevSyncingRef.current = isDataSyncing
      return () => clearTimeout(t)
    }
    prevSyncingRef.current = isDataSyncing
  }, [isDataSyncing])

  const qc = useQueryClient()
  const navigate = useNavigate()
  const version = versionData?.version
  const realtimeEnabled = prefs?.realtime_quotes_enabled ?? false
  const indicesPinned = prefs?.indices_nav_pinned ?? true
  const sidebarIndexSymbols = prefs?.sidebar_index_symbols ?? CORE_INDEXES.map(p => p.symbol)
  const sidebarIndexes = CORE_INDEXES.filter(item => sidebarIndexSymbols.includes(item.symbol))
  // 卡片数据：固定显示时也拉取（即使实时行情关闭）
  const showSidebarQuotes = indicesPinned || realtimeEnabled
  const { data: sidebarIndexQuotes } = useQuery({
    queryKey: [...QK.indexQuotes, 'sidebar', sidebarIndexSymbols.join(',')] as const,
    queryFn: () => api.indexQuotes(sidebarIndexes.map(p => p.symbol)),
    enabled: showSidebarQuotes && sidebarIndexes.length > 0,
    placeholderData: (prev) => prev,
  })

  // SSE: 行情更新时自动刷新相关 queries + 告警通知
  useQuoteStream(realtimeEnabled, prefs?.sse_refresh_pages)

  const toggleQuote = useToggleRealtimeQuotes()
  const isRunning = quoteStatus?.running ?? false
  const isTrading = quoteStatus?.is_trading_hours ?? false
  // none/free 档(无实时行情权限)→ rank < starter(1)
  const isFreeTier = tierRank(caps?.label ?? '') < 1

  // 轮询触发记录总数 → 更新监控中心徽标 (每 15 秒)
  const alertsTotalQuery = useQuery({
    queryKey: ['alerts-total'],
    queryFn: () => api.alertsList({ days: 7, limit: 1 }),
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
    select: (data) => data.total,
  })
  // 只在拿到真实总数时同步徽标 (避免 data=undefined 时传 0 重置 lastSeen)
  const alertsTotal = alertsTotalQuery.data
  useEffect(() => {
    if (alertsTotal != null) setAlertTotal(alertsTotal)
  }, [alertsTotal])

  // 合并内置页面 + 可见的扩展分析菜单
  const analysisNav = (analysisMenus?.items ?? [])
    .filter(m => m.visible)
    .map(m => ({ to: `/analysis/${m.id}`, label: m.label, icon: m.icon === 'tags' ? Tags : BarChart3 }))

  const allNav = [...nav, ...analysisNav]
  const savedOrder = prefs?.nav_order ?? []

  const navItems = savedOrder.length > 0
    ? (() => {
        const byTo = new Map(allNav.map(n => [n.to, n]))
        const ordered = savedOrder
          .map(id => byTo.get(id) ?? byTo.get(`/analysis/${id}`))
          .filter(Boolean)
        const seen = new Set(ordered.map(n => n!.to))
        return [...ordered as typeof allNav, ...allNav.filter(n => !seen.has(n.to))]
      })()
    : allNav

  const hiddenIds = new Set(prefs?.nav_hidden ?? [])
  const visibleNavItems = navItems.filter(n => !hiddenIds.has(n.to) && !hiddenIds.has(n.to.replace(/^\/analysis\//, '')))

  const handleToggle = async (enabled: boolean) => {
    // 开启时重新校验档位
    if (enabled) {
      const fresh = await qc.fetchQuery({
        queryKey: QK.capabilities,
        queryFn: api.capabilities,
      })
      if (tierRank(fresh.label ?? '') < 1) return
    }
    await toggleQuote.mutateAsync(enabled)
    // 仅在交易时段立即获取一次行情
    if (enabled && isTrading) {
      api.intradayRefresh().catch(() => {})
    }
  }

  return (
    <div className="h-screen flex flex-col bg-base text-foreground overflow-hidden">
      {/* ===== 顶部指数行情栏 ===== */}
      <header className="h-10 shrink-0 border-b border-border bg-surface/80 backdrop-blur-sm flex items-center gap-1 px-4 overflow-x-auto">
        <span className="text-[10px] text-muted font-medium mr-1 shrink-0">行情</span>
        {sidebarIndexQuotes?.rows
          ?.filter(q => CORE_INDEXES.some(ci => ci.symbol === q.symbol))
          .map((q) => {
            const name = CORE_INDEXES.find(ci => ci.symbol === q.symbol)?.name ?? q.symbol
            const value = q.last_price ?? q.close
            const pct = q.change_pct
            return (
              <button
                key={q.symbol}
                onClick={() => navigate(`/indices?symbol=${encodeURIComponent(q.symbol)}`)}
                className="flex items-center gap-2 px-2.5 py-1 rounded hover:bg-elevated transition-colors shrink-0"
              >
                <span className="text-[10px] font-medium text-secondary whitespace-nowrap">{name}</span>
                <span className="num text-[11px] tabular text-foreground">{fmtIndexValue(value)}</span>
                <span className={`num text-[10px] tabular font-medium ${indexPctClass(pct)}`}>
                  {fmtIndexPct(pct)}
                </span>
              </button>
            )
          })}
        <div className="flex-1" />
        {/* 实时行情指示灯 */}
        {!isFreeTier && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${
              realtimeEnabled && isRunning && isTrading
                ? 'bg-bull animate-pulse'
                : realtimeEnabled
                  ? 'bg-warning/60'
                  : 'bg-muted'
            }`} />
            <span className="text-[10px] text-muted whitespace-nowrap">
              {realtimeEnabled ? '实时' : '延时'}
            </span>
          </div>
        )}
      </header>

      {/* ===== 主体: 侧边栏 + 内容区 ===== */}
      <div
        className="flex-1 grid overflow-hidden transition-[grid-template-columns] duration-300 ease-smooth"
        style={{ gridTemplateColumns: collapsed ? '3.5rem 1fr' : '14rem 1fr' }}
      >
        <aside className="border-r border-border bg-surface flex flex-col h-full min-h-0 overflow-hidden">
          {/* 折叠模式: 仅显示 Logo + 图标导航 */}
          {collapsed ? (
            <>
              <div className="px-2 py-3 shrink-0 flex flex-col items-center gap-2">
                <button
                  onClick={toggleCollapsed}
                  className="p-1 rounded hover:bg-elevated transition-colors text-muted hover:text-foreground"
                  title="展开侧边栏"
                >
                  <PanelLeftOpen className="h-3.5 w-3.5" />
                </button>
                <Logo
                  size={24}
                  className="shrink-0 drop-shadow-[0_0_8px_rgba(139,92,246,0.5)]"
                  style={{ color: BRAND }}
                />
              </div>
              <nav className="flex-1 min-h-0 overflow-y-auto px-1.5 py-2 space-y-1">
                {visibleNavItems.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    title={label}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center justify-center h-9 w-9 mx-auto rounded-btn transition-all duration-150 ease-smooth',
                        isActive
                          ? 'bg-accent/10 text-accent'
                          : 'text-secondary hover:bg-elevated hover:text-foreground',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <div className="relative inline-flex">
                        <Icon className={cn('h-4 w-4', isActive && 'text-accent')} />
                        {to === '/data' && isDataSyncing && (
                          <Loader2 className="absolute -right-1 -top-1 h-2.5 w-2.5 animate-spin text-accent" />
                        )}
                        {to === '/data' && !isDataSyncing && dataSyncJustDone && (
                          <CheckCircle2 className="absolute -right-1 -top-1 h-2.5 w-2.5 text-bull animate-pulse" />
                        )}
                        {to === '/monitor' && <MonitorBadge active={isActive} />}
                      </div>
                    )}
                  </NavLink>
                ))}
              </nav>
              {/* 折叠模式底部: 仅主题 + 设置 */}
              <div className="border-t border-border px-1.5 py-2 space-y-1.5 shrink-0">
                <button
                  onClick={toggleTheme}
                  className="flex items-center justify-center h-8 w-8 mx-auto rounded-btn text-secondary hover:bg-elevated hover:text-foreground transition-colors"
                  title={theme === 'dark' ? '切换浅色' : '切换深色'}
                >
                  {theme === 'dark' ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </button>
                <NavLink
                  to="/settings"
                  title="设置"
                  className={({ isActive }) =>
                    cn(
                      'flex items-center justify-center h-8 w-8 mx-auto rounded-btn transition-colors',
                      isActive ? 'bg-accent/10 text-accent' : 'text-secondary hover:bg-elevated hover:text-foreground',
                    )
                  }
                >
                  <Settings className="h-4 w-4" />
                </NavLink>
              </div>
            </>
          ) : (
            <>
              {/* 展开模式: Brand 区域 */}
              <div className="px-5 py-4 shrink-0">
                <div className="flex items-center gap-2.5">
                  <Logo
                    size={28}
                    className="shrink-0 drop-shadow-[0_0_8px_rgba(139,92,246,0.5)]"
                    style={{ color: BRAND }}
                  />
                  <div
                    className="font-mono font-bold text-[13px] tracking-[0.06em] text-foreground leading-tight"
                    style={{ textShadow: `0 0 10px ${BRAND}44` }}
                  >
                    Tide Watch
                  </div>
                  <button
                    onClick={toggleCollapsed}
                    className="ml-auto shrink-0 p-1 rounded hover:bg-elevated transition-colors text-muted hover:text-foreground"
                    title="折叠侧边栏"
                  >
                    <PanelLeftClose className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div
                  className="mt-3 h-px"
                  style={{ background: `linear-gradient(90deg, ${BRAND}88, transparent 80%)` }}
                />

                <TierBadge
                  label={caps?.label ?? ''}
                  hasKey={settingsState?.mode !== 'none'}
                />
                <AIConfigBadge
                  configured={settingsState?.has_ai_key}
                  model={settingsState?.ai_model}
                />
              </div>

              {/* 展开模式: 导航菜单 */}
              <nav className="flex-1 min-h-0 overflow-y-auto px-2.5 py-2 space-y-0.5">
                {visibleNavItems.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-3 px-3 py-2 rounded-btn text-sm transition-all duration-150 ease-smooth',
                        isActive
                          ? 'bg-accent/10 text-accent font-medium border-l-[3px] border-accent -ml-[5px] pl-[10px]'
                          : 'text-secondary hover:bg-elevated hover:text-foreground border-l-[3px] border-transparent -ml-[5px] pl-[10px]',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <Icon className={cn('h-4 w-4 shrink-0', isActive && 'text-accent')} />
                        <span className="flex-1">{label}</span>
                        {to === '/data' && isDataSyncing && (
                          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
                        )}
                        {to === '/data' && !isDataSyncing && dataSyncJustDone && (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-bull animate-pulse" />
                        )}
                        {to === '/monitor' && <MonitorBadge active={isActive} />}
                      </>
                    )}
                  </NavLink>
                ))}
              </nav>

              {/* 展开模式: 底部控件 */}
              <div className="border-t border-border px-3 py-2.5 space-y-2 shrink-0">
                {!isFreeTier && (
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[11px] text-secondary">实时行情</span>
                      <button
                        onClick={() => navigate('/settings?tab=monitoring')}
                        className="text-muted hover:text-foreground transition-colors shrink-0"
                        title="实时监控设置"
                      >
                        <Timer className="h-3 w-3" />
                      </button>
                    </div>
                    <button
                      onClick={() => handleToggle(!realtimeEnabled)}
                      disabled={toggleQuote.isPending}
                      className={`relative inline-flex h-4 w-7 items-center rounded-full shrink-0 transition-colors duration-200 ${
                        realtimeEnabled
                          ? 'bg-accent shadow-[0_0_6px_rgba(59,130,246,0.3)]'
                          : 'bg-elevated border border-border'
                      } ${toggleQuote.isPending ? 'opacity-50' : 'cursor-pointer'}`}
                    >
                      <span className={`inline-block h-3 w-3 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                        realtimeEnabled ? 'translate-x-[14px]' : 'translate-x-0.5'
                      }`} />
                    </button>
                  </div>
                )}

                {/* 主题切换 */}
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-secondary">
                    {theme === 'dark' ? '深色' : '浅色'}
                  </span>
                  <button
                    onClick={toggleTheme}
                    className="relative inline-flex h-5 w-9 items-center rounded-full shrink-0 transition-all duration-300 bg-elevated border border-border hover:border-accent/30"
                    title={theme === 'dark' ? '切换浅色' : '切换深色'}
                  >
                    <span
                      className={`inline-flex h-4 w-4 items-center justify-center rounded-full shadow-sm transition-all duration-300 ${
                        theme === 'dark'
                          ? 'translate-x-[16px] bg-accent text-white'
                          : 'translate-x-0.5 bg-warning/80 text-white'
                      }`}
                    >
                      {theme === 'dark' ? (
                        <Moon className="h-2.5 w-2.5" />
                      ) : (
                        <Sun className="h-2.5 w-2.5" />
                      )}
                    </span>
                  </button>
                </div>

                {/* 设置 */}
                <NavLink
                  to="/settings"
                  className={({ isActive }) =>
                    cn(
                      'flex items-center justify-between gap-3 px-2 py-1.5 rounded-btn text-sm transition-colors duration-150 ease-smooth',
                      isActive
                        ? 'bg-accent/10 text-accent font-medium'
                        : 'text-secondary hover:text-foreground',
                    )
                  }
                >
                  <span className="flex items-center gap-2.5">
                    <Settings className="h-3.5 w-3.5 shrink-0" />
                    <span>设置</span>
                  </span>
                  <span className="font-mono text-[10px] text-muted/50 select-none">
                    {version ?? ''}
                  </span>
                </NavLink>
              </div>
            </>
          )}
        </aside>

        <motion.main
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="h-full overflow-auto scrollbar-gutter-stable"
        >
          <Outlet />
        </motion.main>
        <ToastContainer />
        <AlertToastContainer />
        <AiAnalysisHost />
        <AiReportBubble />
      </div>
    </div>
  )
}
