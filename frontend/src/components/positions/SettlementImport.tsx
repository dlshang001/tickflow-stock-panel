/**
 * 交割单导入 —— 拖拽/点击上传，两阶段：解析预览(dry_run) → 确认导入(commit)。
 * 解析后展示：格式、总行数、新增/重复、错误行（带行号）、被过滤的非交易流水。
 */
import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UploadCloud, FileSpreadsheet, Loader2, CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react'
import { api, type SettlementImportResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

type Phase = 'idle' | 'parsing' | 'preview' | 'importing' | 'done'

export function SettlementImport() {
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragOver, setDragOver] = useState(false)
  const [fileName, setFileName] = useState('')
  const [result, setResult] = useState<SettlementImportResult | null>(null)
  const [error, setError] = useState('')

  const parseMut = useMutation({
    mutationFn: (file: File) => api.settlementImport(file, true),
    onMutate: () => { setPhase('parsing'); setError('') },
    onSuccess: (data) => {
      setResult(data)
      setPhase('preview')
    },
    onError: (e: Error) => {
      setError(e.message)
      setPhase('idle')
    },
  })

  // 由于 commit 需要重传同一文件，保留 File 引用
  const fileRef = useRef<File | null>(null)

  const commitMut = useMutation({
    mutationFn: (file: File) => api.settlementImport(file, false),
    onSuccess: (data) => {
      setResult(data)
      setPhase('done')
      qc.invalidateQueries({ queryKey: QK.settlementRecords() })
      qc.invalidateQueries({ queryKey: QK.settlementStats })
      qc.invalidateQueries({ queryKey: QK.positions })
      qc.invalidateQueries({ queryKey: QK.positionsEnriched() })
      qc.invalidateQueries({ queryKey: QK.positionLogs() })
      toast(`成功导入 ${data.imported} 条记录`, 'success')
    },
    onError: (e: Error) => {
      setError(e.message)
      toast(e.message, 'error')
    },
  })

  function handleFile(file: File) {
    const name = file.name.toLowerCase()
    if (!name.endsWith('.xlsx') && !name.endsWith('.xls') && !name.endsWith('.csv')) {
      toast('仅支持 .xlsx / .xls / .csv 文件', 'error')
      return
    }
    fileRef.current = file
    setFileName(file.name)
    parseMut.mutate(file)
  }

  function reset() {
    setPhase('idle')
    setResult(null)
    setFileName('')
    setError('')
    fileRef.current = null
    if (inputRef.current) inputRef.current.value = ''
  }

  const preview = result?.preview ?? []

  return (
    <div className="rounded-card border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <UploadCloud className="h-3.5 w-3.5 text-muted" />
        <span className="text-xs font-medium text-foreground">导入交割单</span>
        <span className="text-[10px] text-muted">同花顺 PC 交割单 / 投资账本</span>
      </div>

      <div className="p-4">
        {/* 上传区 */}
        {phase === 'idle' && (
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault(); setDragOver(false)
              const f = e.dataTransfer.files?.[0]
              if (f) handleFile(f)
            }}
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed py-10 transition-colors',
              dragOver ? 'border-accent bg-accent/5' : 'border-border hover:border-accent/50',
            )}
          >
            <div className="grid h-11 w-11 place-items-center rounded-xl bg-elevated text-muted">
              <UploadCloud className="h-5 w-5" />
            </div>
            <div className="text-sm text-foreground">点击或拖拽文件到此处</div>
            <div className="text-[11px] text-muted">支持 .xlsx / .xls / .csv</div>
            {error && <div className="mt-1 text-xs text-danger">{error}</div>}
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }}
            />
          </div>
        )}

        {/* 解析中 */}
        {phase === 'parsing' && (
          <div className="flex flex-col items-center gap-3 py-10">
            <Loader2 className="h-6 w-6 animate-spin text-accent" />
            <div className="text-sm text-foreground">正在解析 {fileName}…</div>
          </div>
        )}

        {/* 预览 */}
        {phase === 'preview' && result && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1 rounded bg-elevated px-2 py-1 text-secondary">
                <FileSpreadsheet className="h-3.5 w-3.5" /> {fileName}
              </span>
              <span className="rounded bg-accent/10 px-2 py-1 text-accent">格式 {result.format}</span>
              <span className="rounded bg-elevated px-2 py-1 text-secondary">共 {result.total_rows} 行</span>
              <span className="rounded bg-bull/10 px-2 py-1 text-bull">新增 {result.new_count}</span>
              <span className="rounded bg-elevated px-2 py-1 text-secondary">重复 {result.skipped}</span>
              {result.latest_db_date && (
                <span className="rounded bg-elevated px-2 py-1 text-muted">库内最新 {result.latest_db_date}</span>
              )}
            </div>

            {/* 过滤统计 */}
            {Object.keys(result.filtered_stats).length > 0 && (
              <div className="rounded-lg bg-elevated/50 px-3 py-2 text-[11px] text-secondary">
                已过滤非交易流水：
                {Object.entries(result.filtered_stats).map(([k, v]) => (
                  <span key={k} className="ml-2">{k} ×{v}</span>
                ))}
              </div>
            )}

            {/* 错误行 */}
            {result.parse_errors.length > 0 && (
              <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2">
                <div className="flex items-center gap-1.5 text-xs font-medium text-warning">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {result.parse_errors.length} 行解析失败（已跳过）
                </div>
                <div className="mt-1.5 max-h-24 overflow-y-auto thin-scrollbar space-y-0.5">
                  {result.parse_errors.slice(0, 20).map((e, i) => (
                    <div key={i} className="text-[11px] text-secondary">
                      第 {e.row} 行：{e.error}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 预览表 */}
            {preview.length > 0 ? (
              <div className="max-h-72 overflow-auto rounded-lg border border-border thin-scrollbar">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-elevated/95 backdrop-blur-sm">
                    <tr className="text-muted">
                      <th className="px-2 py-1.5 text-left font-medium">日期</th>
                      <th className="px-2 py-1.5 text-left font-medium">代码</th>
                      <th className="px-2 py-1.5 text-left font-medium">名称</th>
                      <th className="px-2 py-1.5 text-center font-medium">方向</th>
                      <th className="px-2 py-1.5 text-right font-medium">价格</th>
                      <th className="px-2 py-1.5 text-right font-medium">数量</th>
                      <th className="px-2 py-1.5 text-right font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.slice(0, 100).map((r, i) => (
                      <tr key={i} className="border-t border-border/60">
                        <td className="px-2 py-1.5 text-secondary">{r.trade_date}</td>
                        <td className="px-2 py-1.5 font-mono text-foreground">{r.symbol}</td>
                        <td className="px-2 py-1.5 text-secondary truncate max-w-[120px]">{r.name}</td>
                        <td className="px-2 py-1.5 text-center">
                          <span className={cn(
                            'rounded px-1.5 py-0.5 text-[10px] font-medium',
                            r.direction === '买入' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear',
                          )}>{r.direction}</span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono num">{r.price.toFixed(3)}</td>
                        <td className="px-2 py-1.5 text-right font-mono num">{r.volume.toLocaleString()}</td>
                        <td className="px-2 py-1.5 text-right font-mono num">{r.amount.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {preview.length > 100 && (
                  <div className="border-t border-border/60 px-2 py-1 text-center text-[10px] text-muted">
                    仅展示前 100 条，共 {preview.length} 条
                  </div>
                )}
              </div>
            ) : (
              <div className="rounded-lg bg-elevated/50 px-3 py-6 text-center text-xs text-muted">
                没有可导入的新记录（可能全部重复）
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <button onClick={reset} className="inline-flex h-8 px-3 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors">
                重新选择
              </button>
              <button
                onClick={() => fileRef.current && commitMut.mutate(fileRef.current)}
                disabled={result.new_count === 0 || commitMut.isPending}
                className="inline-flex items-center gap-1.5 h-8 px-4 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent/90 disabled:opacity-40 transition-colors"
              >
                {commitMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
                确认导入 {result.new_count} 条
              </button>
            </div>
          </div>
        )}

        {/* 完成 */}
        {phase === 'done' && result && (
          <div className="flex flex-col items-center gap-3 py-8">
            <CheckCircle2 className="h-10 w-10 text-bear" />
            <div className="text-sm text-foreground">导入完成</div>
            <div className="text-xs text-muted">
              新增 <span className="font-mono text-foreground">{result.imported}</span> 条记录，已同步到持仓
            </div>
            <button onClick={reset} className="mt-1 inline-flex h-8 px-4 rounded-lg border border-border text-xs text-secondary hover:text-foreground transition-colors">
              继续导入
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
