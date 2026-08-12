/**
 * Skill 参数面板 — 根据 META.params 动态渲染配置控件。
 *
 * 支持的参数类型:
 *  - bool   → 开关
 *  - select → 下拉选择
 *  - int    → 数字输入(整数)
 *  - float  → 数字输入(小数)
 *  - text   → 文本输入
 */
import { useState, useEffect } from 'react'
import { cn } from '@/lib/cn'
import {
  type SkillTab,
  getSkillState,
  updateParam,
  subscribeSkill,
} from '@/lib/aiSkillStore'

interface Props {
  tab: SkillTab
}

export function SkillParamsPanel({ tab }: Props) {
  const [, setTick] = useState(0)

  useEffect(() => subscribeSkill(() => setTick(t => t + 1)), [])

  const state = getSkillState(tab)
  const selected = state.skills.find(s => s.id === state.selectedId)

  if (!selected || !selected.params || selected.params.length === 0) {
    return null
  }

  return (
    <div className="rounded-card border border-border bg-surface/80 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <span className="text-sm">{selected.emoji}</span>
        <span className="text-sm font-medium text-foreground">{selected.name}</span>
        <span className="text-xs text-secondary">参数配置</span>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {selected.params.map(param => {
          const pid = param.id || param.key || ''
          const value = state.params[pid]
          return (
            <div key={pid} className="flex items-center justify-between gap-2">
              <label className="text-xs text-secondary">{param.label}</label>
              <ParamControl
                param={param}
                value={value}
                onChange={(v) => updateParam(tab, pid, v)}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** 单个参数控件。 */
function ParamControl({
  param,
  value,
  onChange,
}: {
  param: any
  value: any
  onChange: (v: any) => void
}) {
  const type = param.type

  if (type === 'bool') {
    return (
      <button
        onClick={() => onChange(!value)}
        className={cn(
          'relative h-4 w-7 rounded-full transition-colors',
          value ? 'bg-accent' : 'bg-muted',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 h-3 w-3 rounded-full bg-white transition-transform',
            value ? 'translate-x-3' : 'translate-x-0.5',
          )}
        />
      </button>
    )
  }

  if (type === 'select') {
    const options = param.options ?? []
    return (
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        className="h-7 rounded border border-border bg-surface px-2 text-xs text-foreground"
      >
        {options.map((opt: string) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    )
  }

  if (type === 'int' || type === 'float' || type === 'number') {
    return (
      <input
        type="number"
        value={value ?? 0}
        min={param.min}
        max={param.max}
        step={param.step ?? (type === 'int' ? 1 : 0.1)}
        onChange={(e) => {
          const v = type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value)
          onChange(isNaN(v) ? 0 : v)
        }}
        className="h-7 w-16 rounded border border-border bg-surface px-2 text-xs font-mono text-foreground"
      />
    )
  }

  // text / string
  return (
    <input
      type="text"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 w-24 rounded border border-border bg-surface px-2 text-xs text-foreground"
    />
  )
}
