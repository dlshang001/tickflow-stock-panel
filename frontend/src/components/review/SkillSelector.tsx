/**
 * Skill 下拉选择器 — 在 Review 页面标签页旁渲染。
 *
 * 显示当前 category 下所有可用的 Skill,支持切换。
 * 默认 Skill 带星标,选中后触发 store 更新。
 */
import { useEffect, useState, useRef } from 'react'
import { Check, ChevronDown, Settings2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import {
  type SkillTab,
  getSkillState,
  selectSkill,
  ensureSkillsLoaded,
  subscribeSkill,
} from '@/lib/aiSkillStore'

interface Props {
  tab: SkillTab
  onToggleParams?: () => void
  paramsOpen?: boolean
}

export function SkillSelector({ tab, onToggleParams, paramsOpen }: Props) {
  const [, setTick] = useState(0)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // 订阅 store 变化
  useEffect(() => subscribeSkill(() => setTick(t => t + 1)), [])

  // 懒加载 skill 列表
  useEffect(() => {
    ensureSkillsLoaded(tab)
  }, [tab])

  // 点击外部关闭下拉
  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const state = getSkillState(tab)
  const selected = state.skills.find(s => s.id === state.selectedId)
  const hasParams = (selected?.params?.length ?? 0) > 0

  if (state.loading) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-secondary">
        <span className="animate-pulse">加载 Skill...</span>
      </div>
    )
  }

  if (state.skills.length === 0) return null

  return (
    <div ref={ref} className="relative flex items-center gap-1">
      {/* Skill 下拉 */}
      <button
        onClick={() => setOpen(o => !o)}
        className="inline-flex items-center gap-1.5 rounded-btn border border-border bg-surface px-2.5 py-1 text-[11px] font-medium text-foreground transition-colors hover:bg-elevated"
      >
        <span className="text-sm leading-none">{selected?.emoji ?? '📊'}</span>
        <span className="max-w-[120px] truncate">{selected?.name ?? '选择 Skill'}</span>
        <ChevronDown className="h-3 w-3 text-secondary" />
      </button>

      {/* 参数按钮 */}
      {hasParams && onToggleParams && (
        <button
          onClick={onToggleParams}
          className={cn(
            'grid h-6 w-6 place-items-center rounded border border-border transition-colors',
            paramsOpen ? 'bg-accent/15 text-accent' : 'bg-surface text-secondary hover:text-foreground',
          )}
          title="Skill 参数"
        >
          <Settings2 className="h-3 w-3" />
        </button>
      )}

      {/* 下拉列表 */}
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 min-w-[220px] rounded-card border border-border bg-surface shadow-lg">
          {state.skills.map(skill => (
            <button
              key={skill.id}
              onClick={() => {
                selectSkill(tab, skill.id)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] transition-colors first:rounded-t-card last:rounded-b-card',
                skill.id === state.selectedId
                  ? 'bg-accent/10 text-accent'
                  : 'text-foreground hover:bg-elevated',
              )}
            >
              <span className="text-sm leading-none">{skill.emoji ?? '📊'}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1">
                  <span className="font-medium truncate">{skill.name}</span>
                  {skill.default_for_category && (
                    <span className="text-[9px] text-secondary">默认</span>
                  )}
                </div>
                {skill.description && (
                  <div className="text-[9px] text-secondary truncate">{skill.description}</div>
                )}
              </div>
              {skill.id === state.selectedId && (
                <Check className="h-3 w-3 flex-shrink-0" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
