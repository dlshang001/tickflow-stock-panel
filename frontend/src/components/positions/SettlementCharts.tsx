/**
 * 交割单图表容器：获取 stats 数据并渲染 4 个图表。
 */
import { useQuery } from '@tanstack/react-query'
import { Loader2, BarChart3 } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { PnlCurveChart } from './charts/PnlCurveChart'
import { MonthlyPnlChart } from './charts/MonthlyPnlChart'
import { SymbolPnlChart } from './charts/SymbolPnlChart'
import { FeePieChart } from './charts/FeePieChart'

export function SettlementCharts() {
  const q = useQuery({
    queryKey: QK.settlementStats,
    queryFn: api.settlementStats,
  })

  const data = q.data

  if (q.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-muted">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span className="text-xs">加载统计…</span>
      </div>
    )
  }

  if (!data || data.records_count === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-muted">
        <BarChart3 className="h-8 w-8 opacity-30" strokeWidth={1.5} />
        <span className="text-xs">暂无交割单数据</span>
        <span className="text-[10px] text-muted/60">导入交割单后自动生成图表</span>
      </div>
    )
  }

  return (
    <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
      <PnlCurveChart data={data.realized_pnl_curve} />
      <MonthlyPnlChart data={data.monthly} />
      <SymbolPnlChart data={data.by_symbol} />
      <FeePieChart fees={data.fees} />
    </div>
  )
}