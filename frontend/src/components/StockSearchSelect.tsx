/**
 * 个股搜索选择框（复用 instrumentSearch 真实搜索）。
 *
 * 用于大喵票池/持仓等需要"选一只股票"的表单。输入代码或名称模糊搜索,
 * 键盘上下键/回车选择,外部点击关闭。选中后回调 onSelect(symbol, name)。
 */
import { useRef, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Check } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

interface Result {
  symbol: string
  name: string
  code: string
  asset_type?: string
}

interface Props {
  /** 受控显示值（通常是已选 symbol，或空串） */
  value: string
  /** 选中某只股票时回调 */
  onSelect: (symbol: string, name: string) => void
  /** 已存在的 symbol 列表，命中时显示"已添加"勾选（可选） */
  existingSymbols?: string[]
  /** 输入框占位符 */
  placeholder?: string
  /** 自定义宽度 class，默认 w-44 */
  widthClass?: string
  disabled?: boolean
}

export function StockSearchSelect({
  value, onSelect, existingSymbols = [], placeholder = '搜索代码/名称',
  widthClass = 'w-52', disabled = false,
}: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)

  const search = useQuery({
    queryKey: QK.instrumentSearch(query, 'stock,etf'),
    queryFn: () => api.instrumentSearch(query, 20, 'stock,etf'),
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  })
  const results = search.data?.results ?? []

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { setOpen(false); return }
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIdx >= 0) handleSelect(results[activeIdx])
      else if (results.length > 0) handleSelect(results[0])
    }
  }

  function handleSelect(r: Result) {
    onSelect(r.symbol, r.name)
    setQuery('')
    setOpen(false)
    setActiveIdx(-1)
  }

  return (
    <div ref={containerRef} className={`relative ${widthClass}`}>
      <div className="relative flex items-center">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted pointer-events-none" />
        <input
          type="text"
          placeholder={value ? value : placeholder}
          value={query}
          disabled={disabled}
          onChange={e => { setQuery(e.target.value); setOpen(true); setActiveIdx(-1) }}
          onFocus={() => { if (query.trim()) setOpen(true) }}
          onKeyDown={handleKeyDown}
          className={`w-full h-9 pl-8 pr-2.5 rounded-lg border border-border bg-elevated text-sm text-foreground placeholder:text-muted outline-none focus:border-accent transition-colors ${disabled ? 'opacity-60 cursor-not-allowed' : ''}`}
        />
      </div>

      {open && results.length > 0 && (
        <div className="absolute left-0 top-full mt-1 z-50 w-72 max-h-[320px] overflow-y-auto rounded-card border border-border bg-base shadow-xl">
          {results.map((r, i) => {
            const exists = existingSymbols.includes(r.symbol)
            return (
              <div
                key={r.symbol}
                className={`flex items-center gap-2.5 px-3 py-2 text-xs transition-colors ${
                  i === activeIdx ? 'bg-accent/10 text-accent' : 'hover:bg-elevated text-foreground'
                }`}
              >
                <button
                  type="button"
                  onClick={() => handleSelect(r)}
                  className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
                >
                  <span className="font-mono shrink-0 w-[82px]">{r.symbol}</span>
                  <span className="truncate text-secondary flex-1">{r.name}</span>
                  {r.asset_type === 'etf' && (
                    <span className="shrink-0 px-1 py-0.5 rounded text-[10px] leading-none bg-accent/10 text-accent">ETF</span>
                  )}
                </button>
                {exists && <Check className="h-3.5 w-3.5 shrink-0 text-accent" />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
