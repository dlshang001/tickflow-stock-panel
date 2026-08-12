/**
 * 复盘生成状态的全局单例 store —— 脱离 Review 组件生命周期,支持多 tab。
 *
 * 三种 tab 各自独立状态,互不干扰:
 *  - market:     大盘复盘 (api.reviewStream, 支持 SSE 定时推送)
 *  - holdings:   持仓分析 (api.positionAnalyzeStream)
 *  - settlement: 交割单分析 (api.settlementAnalyzeStream)
 *
 * 每个 tab:
 *  - 独立 state(phase/content/meta/focus)
 *  - 独立 AbortController(组件卸载不中断流)
 *  - 同一 tab 同时只允许一个生成实例
 *  - 切换 tab 不中断后台流(状态保留,切回来恢复)
 *
 * SSE 定时推送仅 market tab 支持(feedReviewEvent)。
 */
import { api } from '@/lib/api'

export type ReviewTab = 'market' | 'holdings' | 'settlement'

export type ReviewPhase = 'idle' | 'loading' | 'streaming' | 'done' | 'error'

export interface ReviewMeta {
  as_of?: string
  emotion_score?: number
  emotion_label?: string
  summary?: string | Record<string, any>
  // 持仓/交割单 tab 的 meta 字段
  count?: number
  total_market_value?: number
  total_pnl_pct?: number
  total_trades?: number
  buy_count?: number
  sell_count?: number
  total_realized_pnl?: number
  records_count?: number
  // Skill 信息(三 tab 通用)
  skill_id?: string | null
  skill_name?: string | null
  skill_params?: Record<string, any> | null
}

export interface ReviewState {
  phase: ReviewPhase
  content: string
  error: string
  meta: ReviewMeta | null
  focus: string
}

const INITIAL: ReviewState = { phase: 'idle', content: '', error: '', meta: null, focus: '' }

const TABS: ReviewTab[] = ['market', 'holdings', 'settlement']

// ===== 各 tab 独立状态 =====
const states: Record<ReviewTab, ReviewState> = {
  market: { ...INITIAL },
  holdings: { ...INITIAL },
  settlement: { ...INITIAL },
}

const abortCtrls: Record<ReviewTab, AbortController | null> = {
  market: null, holdings: null, settlement: null,
}

// market tab 的生成来源(用于 SSE 并发控制)
let marketGeneratingSource: 'manual' | 'sse' | null = null

// ===== 订阅机制 =====
type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  for (const l of listeners) l()
}

export function getReviewState(tab: ReviewTab = 'market'): ReviewState {
  return states[tab]
}

export function subscribeReview(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 指定 tab 是否正在生成 */
export function isTabGenerating(tab: ReviewTab = 'market'): boolean {
  return states[tab].phase === 'loading' || states[tab].phase === 'streaming'
}

/** 任意 tab 是否正在生成 */
export function isAnyGenerating(): boolean {
  return TABS.some(t => isTabGenerating(t))
}

// ===== 向后兼容(默认 market tab)=====
export function getReviewMeta(): ReviewMeta | null {
  return states.market.meta
}

export function isReviewGenerating(): boolean {
  return isTabGenerating('market')
}

// ===== 流式 API 选择 =====
type StreamEvent = {
  type: 'meta' | 'delta' | 'error' | 'done'
  content?: string
  message?: string
  [key: string]: any
}

async function* getStream(
  tab: ReviewTab,
  focus: string,
  skillId?: string,
  skillParams?: Record<string, any>,
): AsyncGenerator<StreamEvent> {
  switch (tab) {
    case 'market':
      yield* api.reviewStream(undefined, focus, skillId, skillParams)
      break
    case 'holdings':
      yield* api.positionAnalyzeStream(focus, skillId, skillParams)
      break
    case 'settlement':
      yield* api.settlementAnalyzeStream(focus, skillId, skillParams)
      break
  }
}

/**
 * 启动指定 tab 的生成。返回后流在后台独立运行,组件卸载不影响。
 * @param tab 分析类型
 * @param focus 用户追加的关注点
 * @param options 可选配置 { skillId, skillParams, onDone }
 */
export async function startGeneration(
  tab: ReviewTab,
  focus: string,
  options?: {
    skillId?: string
    skillParams?: Record<string, any>
    onDone?: (fullContent: string, meta: ReviewMeta | null) => void
  },
): Promise<void> {
  const { skillId, skillParams, onDone } = options ?? {}

  // 同一 tab 已在生成中,不重复启动
  if (isTabGenerating(tab)) return

  if (tab === 'market') marketGeneratingSource = 'manual'
  states[tab] = { phase: 'loading', content: '', error: '', meta: null, focus }
  notify()

  abortCtrls[tab] = new AbortController()
  let buf = ''
  let failed = false
  let doneMeta: ReviewMeta | null = null

  try {
    for await (const evt of getStream(tab, focus, skillId, skillParams)) {
      if (abortCtrls[tab]?.signal.aborted) break
      if (evt.type === 'meta') {
        const metaEvt = evt as unknown as ReviewMeta
        doneMeta = metaEvt
        states[tab] = { ...states[tab], meta: metaEvt }
        notify()
      } else if (evt.type === 'delta' && evt.content) {
        buf += evt.content
        states[tab] = { ...states[tab], content: buf, phase: 'streaming' }
        notify()
      } else if (evt.type === 'error') {
        failed = true
        states[tab] = { ...states[tab], error: evt.message ?? '分析失败', phase: 'error' }
        notify()
        return
      } else if (evt.type === 'done') {
        states[tab] = { ...states[tab], phase: 'done' }
        notify()
      }
    }
    // 流正常结束但无 done 事件,按 done 处理
    if (buf && !failed) {
      states[tab] = { ...states[tab], phase: 'done' }
      notify()
      // 自动归档回调(仅 market tab 需要,holdings/settlement 后端已归档)
      if (tab === 'market') {
        onDone?.(buf, doneMeta)
      }
    }
  } catch (e: any) {
    if (!abortCtrls[tab]?.signal.aborted) {
      states[tab] = { ...states[tab], error: e?.message ?? '分析失败', phase: 'error' }
      notify()
    }
  } finally {
    abortCtrls[tab] = null
    if (tab === 'market') marketGeneratingSource = null
  }
}

/** 中断指定 tab 的生成。 */
export function abortGeneration(tab: ReviewTab = 'market'): void {
  abortCtrls[tab]?.abort()
  abortCtrls[tab] = null
}

/** 重置指定 tab 到 idle。 */
export function resetTab(tab: ReviewTab = 'market'): void {
  states[tab] = { ...INITIAL }
  notify()
}

/** 设置指定 tab 的查看历史报告状态。 */
export function setViewingReport(tab: ReviewTab, report: {
  content: string
  as_of?: string
  emotion_score?: number | null
  emotion_label?: string
  summary?: string
  [key: string]: any
}): void {
  abortCtrls[tab]?.abort()
  abortCtrls[tab] = null
  states[tab] = {
    phase: 'done',
    content: report.content,
    error: '',
    meta: {
      as_of: report.as_of,
      emotion_score: report.emotion_score ?? undefined,
      emotion_label: report.emotion_label,
      summary: report.summary,
    },
    focus: states[tab].focus,
  }
  notify()
}

// ===== 向后兼容: market tab 的旧 API =====
export async function startReviewGeneration(
  _asOf: string | undefined,
  focus: string,
  onDone?: (fullContent: string, meta: ReviewMeta | null) => void,
): Promise<void> {
  return startGeneration('market', focus, { onDone })
}

export function abortReviewGeneration(): void {
  abortGeneration('market')
}

export function resetReview(): void {
  resetTab('market')
}

// ===== SSE 定时推送(仅 market tab)=====
/**
 * 喂入一条来自 SSE 的复盘事件(定时生成时后端推来的)。
 * 仅对 market tab 生效。
 */
export function feedReviewEvent(evt: any): void {
  if (!evt || typeof evt !== 'object') return
  const t = evt.type

  // 并发控制: 手动流进行中时, SSE 事件一律忽略
  if (marketGeneratingSource === 'manual') return

  if (t === 'meta') {
    marketGeneratingSource = 'sse'
    states.market = { phase: 'streaming', content: '', error: '', meta: evt, focus: '' }
    notify()
  } else if (t === 'delta' && evt.content) {
    if (marketGeneratingSource !== 'sse') return
    states.market = { ...states.market, content: states.market.content + evt.content, phase: 'streaming' }
    notify()
  } else if (t === 'retry') {
    if (marketGeneratingSource !== 'sse') return
    states.market = { ...states.market, content: '', phase: 'streaming' }
    notify()
  } else if (t === 'error') {
    if (marketGeneratingSource !== 'sse') return
    states.market = { ...states.market, error: evt.message ?? '复盘生成失败', phase: 'error' }
    notify()
    marketGeneratingSource = null
  } else if (t === 'done') {
    if (marketGeneratingSource !== 'sse') return
    states.market = { ...states.market, phase: 'done' }
    notify()
    marketGeneratingSource = null
  }
}
