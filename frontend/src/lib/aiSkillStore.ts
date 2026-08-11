/**
 * AI Skill 全局状态管理 — 每个 tab 独立的 Skill 选择状态。
 *
 * 职责:
 *  - 按 tab(market/holdings/settlement)加载该 category 的 skill 列表
 *  - 记住每个 tab 选中的 skill_id 和参数
 *  - 切换 skill 时自动补默认参数
 *  - 供 Review 页面和 reviewStore 读取
 *
 * 设计:
 *  - 纯 JS 单例(不依赖 React),用 useSyncExternalStore 订阅
 *  - 切换 tab 时自动加载该 category 的 skill 列表(懒加载,只首次)
 *  - 未选中时默认取 default_for_category=true 的 skill
 */
import { api, type SkillMeta } from '@/lib/api'

export type SkillTab = 'market' | 'holdings' | 'settlement'

export interface SkillState {
  skills: SkillMeta[]        // 该 category 可用的 skill 列表
  selectedId: string | null  // 当前选中的 skill id
  params: Record<string, any> // 当前 skill 的参数
  loading: boolean
  loaded: boolean            // 是否已加载过
}

const INITIAL: SkillState = {
  skills: [], selectedId: null, params: {}, loading: false, loaded: false,
}

// 各 tab 独立状态
const states: Record<SkillTab, SkillState> = {
  market: { ...INITIAL },
  holdings: { ...INITIAL },
  settlement: { ...INITIAL },
}

// ===== 订阅机制 =====
type Listener = () => void
const listeners = new Set<Listener>()

function notify() {
  for (const l of listeners) listeners.has(l) && l()
}

export function subscribeSkill(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function getSkillState(tab: SkillTab): SkillState {
  return states[tab]
}

// ===== 加载 skill 列表 =====

/** 确保指定 tab 的 skill 列表已加载(懒加载,只首次)。 */
export async function ensureSkillsLoaded(tab: SkillTab): Promise<void> {
  const s = states[tab]
  if (s.loaded || s.loading) return

  s.loading = true
  notify()

  try {
    const res = await api.aiSkillList(tab)
    const skills = res.skills ?? []
    // 找默认 skill
    const defaultSkill = skills.find(m => m.default_for_category) ?? skills[0]
    states[tab] = {
      skills,
      selectedId: defaultSkill?.id ?? null,
      params: buildDefaultParams(defaultSkill),
      loading: false,
      loaded: true,
    }
  } catch {
    states[tab] = { ...INITIAL, loaded: true }
  }
  notify()
}

// ===== 选择 skill =====

/** 切换当前 tab 选中的 skill,自动补默认参数。 */
export function selectSkill(tab: SkillTab, skillId: string): void {
  const s = states[tab]
  const meta = s.skills.find(m => m.id === skillId)
  if (!meta) return

  states[tab] = {
    ...s,
    selectedId: skillId,
    params: buildDefaultParams(meta),
  }
  notify()
}

/** 修改当前 skill 的某个参数。 */
export function updateParam(tab: SkillTab, paramId: string, value: any): void {
  states[tab] = {
    ...states[tab],
    params: { ...states[tab].params, [paramId]: value },
  }
  notify()
}

/** 获取当前 tab 选中的 skill meta。 */
export function getSelectedSkill(tab: SkillTab): SkillMeta | null {
  const s = states[tab]
  return s.skills.find(m => m.id === s.selectedId) ?? null
}

// ===== 工具函数 =====

/** 从 META.params 构建默认参数字典。 */
function buildDefaultParams(meta: SkillMeta | undefined): Record<string, any> {
  if (!meta) return {}
  const result: Record<string, any> = {}
  for (const p of meta.params ?? []) {
    const pid = p.id || p.key || ''
    if (pid) result[pid] = p.default
  }
  return result
}
