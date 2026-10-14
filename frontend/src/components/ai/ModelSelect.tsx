import { Cpu } from 'lucide-react'
import { useAiModels } from '@/lib/aiModelStore'
import { cn } from '@/lib/cn'

/** Shared per-request model selector for AI analysis entry points. */
export function ModelSelect({ className, disabled }: { className?: string; disabled?: boolean }) {
  const { models, selected, select } = useAiModels()
  if (models.length === 0 || (models.length === 1 && (!selected || selected === models[0]))) return null

  const selectedIsUnlisted = !!selected && !models.includes(selected)
  const value = selectedIsUnlisted
    ? selected
    : selected && models.includes(selected) && selected !== models[0]
      ? selected
      : ''
  return (
    <div className={cn('flex items-center gap-1.5 shrink-0', className)} title="选择本次分析使用的模型">
      <Cpu className="h-3 w-3 text-muted" />
      <select
        value={value}
        disabled={disabled}
        onChange={event => select(event.target.value)}
        className={cn(
          'h-8 max-w-[180px] bg-base ring-1 ring-border/30 rounded-lg text-xs text-secondary px-2',
          'focus:outline-none focus:ring-2 focus:ring-sky-400/30 transition-shadow cursor-pointer',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
      >
        {selectedIsUnlisted && <option value={selected}>{selected}（当前选择，目录未列出）</option>}
        {models.map((model, index) => (
          <option key={model} value={index === 0 ? '' : model}>
            {index === 0 ? `默认（${model}）` : model}
          </option>
        ))}
      </select>
    </div>
  )
}

export function ModelBadge({ model, className }: { model?: string | null; className?: string }) {
  if (!model) return null
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-mono',
        'bg-sky-500/10 text-sky-300/90 border border-sky-400/20', className)}
      title={`本次请求模型：${model}（以 Codex CLI/上游实际执行结果为准）`}
    >
      <Cpu className="h-2.5 w-2.5" />{model}
    </span>
  )
}
