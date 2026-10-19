import type { CodexModelCatalog, CodexModelItem } from './api'

export type CodexModelOption = {
  label: string
  value: string
  model: string
  effort: string
  hint: string
}

export const FOLLOW_CODEX_DEFAULT_OPTION: CodexModelOption = {
  label: '跟随本机 Codex 默认',
  value: '',
  model: '',
  effort: '',
  hint: '使用本机 Codex CLI 配置的默认模型与推理强度',
}

const REASONING_LABELS: Record<string, string> = {
  minimal: '极低',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '极高',
  very_high: '极高',
}

function modelOptions(item: CodexModelItem): CodexModelOption[] {
  const efforts = item.supported_reasoning_efforts.length
    ? item.supported_reasoning_efforts
    : item.default_reasoning_effort
      ? [{ reasoning_effort: item.default_reasoning_effort, description: '' }]
      : [{ reasoning_effort: '', description: '' }]

  return efforts.map(({ reasoning_effort: effort, description }) => {
    const isDefault = item.is_default && effort === item.default_reasoning_effort
    const effortLabel = effort ? REASONING_LABELS[effort] ?? effort : ''
    const label = effortLabel ? `${item.display_name} · ${effortLabel}` : item.display_name
    const hint = [item.description, description, isDefault ? '本机默认模型与推理档' : '']
      .filter(Boolean)
      .join(' · ')
    return {
      label: isDefault ? `${label}（推荐）` : label,
      value: `${item.model}:${effort}`,
      model: item.model,
      effort,
      hint: hint || item.model,
    }
  })
}

export function buildCodexModelOptions(
  catalog: CodexModelCatalog | null,
  savedModel: string,
  savedEffort: string,
): CodexModelOption[] {
  const discovered = (catalog?.models ?? []).flatMap(modelOptions)
  const savedIsListed = discovered.some(option =>
    option.model === savedModel && option.effort === savedEffort,
  )
  const savedOption: CodexModelOption | null = savedModel && !savedIsListed
    ? {
        label: `${savedModel}${savedEffort ? ` · ${REASONING_LABELS[savedEffort] ?? savedEffort}` : ''}（当前配置）`,
        value: `__saved_codex_config__:${savedModel}:${savedEffort}`,
        model: savedModel,
        effort: savedEffort,
        hint: '保留当前已保存的模型与推理档；目录中未列出此配置',
      }
    : null

  return [
    FOLLOW_CODEX_DEFAULT_OPTION,
    ...(savedOption ? [savedOption] : []),
    ...discovered,
  ]
}

export function codexCatalogStatus(
  catalog: CodexModelCatalog | null,
  loading: boolean,
): string {
  const count = catalog?.models.length ?? 0
  if (loading) {
    return count ? `正在刷新，暂用 ${count} 个缓存模型` : '正在读取 Codex 模型目录'
  }
  if (!catalog) return 'Codex 模型目录尚未读取'
  if (catalog.error) {
    return catalog.stale
      ? `读取失败，暂用 ${count} 个缓存模型`
      : 'Codex 模型目录读取失败'
  }
  if (!count) return '未发现可用的 Codex 模型'
  return `${catalog.stale ? '缓存目录' : '已发现'} ${count} 个 Codex 模型`
}
