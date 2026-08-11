/**
 * TradeKlineMarkers：把某标的的操作日志/交割单记录转换为 ChartMarker[]。
 *
 * 本组件不渲染 K 线，由父组件（StockPanel / StockPreviewDialog）：
 *   1. 读取 <TradeKlineMarkers markers=[]> 通过 render prop 或 ref 透传
 *   2. 将 markers 传给 <StockDailyKChart markers={...}/> 渲染到 EChartsCandlestick 上
 *   3. 将底部摘要信息栏（买卖笔数/已实现盈亏）展示在 K 线下。
 *
 * 设计说明：
 * - 操作日志（position_log）是唯一真相源，交割单已通过 sync_from_settlements 写入日志，
 *   所以此处只加载 positionLogs(symbol) 即可覆盖 手动 + 交割单 两种来源。
 * - 日志 op_type='clear' 拆成"卖出当前全部数量"一条 marker 展示。
 * - kind='buy' 在蜡烛下方用↑红箭头，'sell' 在蜡烛上方用↓绿箭头。
 */
import { useMemo, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ChartMarker } from '@/components/EChartsCandlestick'
import { api, type PositionLog } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

const TAG = '[TradeKlineMarkers]'
/**
 * 控制台过滤关键词：在 Chrome DevTools Console → Filter 输入下列任一字符串，可只看该层日志：
 *   [TKM:query]     — 接口请求状态（symbol / status / fetchStatus / error）
 *   [TKM:transform] — 数据转换（原始条数、排序、日期范围、op_type 分布、markers 数、剩余 netVol）
 *   [TKM:warnings]  — 转换过程中的异常（缺日期 / 超卖 / 未知 op_type / netVol 变负）
 *   [TKM:summary]   — 最终 summary 产出（传入 StockPanel 的 markers/买卖清计数）
 *   [TradeKlineMarkers] — 全部三层日志
 */
const SUB = {
  query:     `${TAG} [TKM:query]`,
  transform: `${TAG} [TKM:transform]`,
  warnings:  `${TAG} [TKM:warnings]`,
  summary:   `${TAG} [TKM:summary]`,
} as const

export interface TradeMarkerSummary {
  markers: ChartMarker[]
  buyCount: number
  sellCount: number
  clearCount: number
  buyVolume: number
  sellVolume: number
  lastOp: PositionLog | null
  logs: PositionLog[]
}

interface Props {
  symbol?: string | null
  children: (s: TradeMarkerSummary) => React.ReactNode
}

export function TradeKlineMarkers({ symbol, children }: Props) {
  const q = useQuery({
    queryKey: QK.positionLogs(symbol ?? undefined),
    queryFn: () => (symbol ? api.positionLogs(symbol) : Promise.resolve({ logs: [] as PositionLog[] })),
    enabled: !!symbol,
  })

  // 查询状态日志（仅在关键状态变化时打印）
  useEffect(() => {
    console.debug(`${SUB.query} symbol=${symbol} status=${q.status} fetchStatus=${q.fetchStatus} enabled=${!!symbol}`)
    if (q.isError) {
      console.error(`${SUB.query} FAILED symbol=${symbol}`, (q.error as any)?.message ?? q.error)
    }
  }, [symbol, q.status, q.fetchStatus, q.isError, q.error])

  const summary = useMemo<TradeMarkerSummary>(() => {
    const rawLogs = q.data?.logs ?? []
    // 显式排序：后端理论升序，但前端自行保障，防止 API 变动或缓存脏数据导致 netVol/clear 错算
    const logs = [...rawLogs].sort((a, b) => {
      const d = (a.op_date ?? '').localeCompare(b.op_date ?? '')
      if (d !== 0) return d
      return (a.id ?? 0) - (b.id ?? 0)
    })
    if (logs.length > 0 && logs.length !== rawLogs.length) {
      // 不会发生，但防御一下
      console.warn(`${TAG} sort length mismatch raw=${rawLogs.length} sorted=${logs.length}`)
    }

    const markers: ChartMarker[] = []
    let buyCount = 0, sellCount = 0, clearCount = 0, buyVolume = 0, sellVolume = 0
    let netVol = 0

    // op_type 分布用于调试日志
    const opCounts: Record<string, number> = {}
    // 异常事件集合
    const warnings: string[] = []

    for (let i = 0; i < logs.length; i++) {
      const log = logs[i]
      opCounts[log.op_type] = (opCounts[log.op_type] ?? 0) + 1

      const t = log.op_type
      const vol = Number(log.volume ?? 0)
      const date = (log.op_date || '').slice(0, 10)
      if (!date) {
        warnings.push(`log#${log.id ?? i} 缺少 op_date`)
        continue
      }

      const sourceCh = log.source === 'settlement' ? '交' : log.source === 'migration' ? '迁' : '手'
      const label = [
        log.price != null ? `¥${log.price.toFixed(2)}` : '',
        log.volume != null && log.volume > 0 ? `${vol}` : '',
        sourceCh,
      ].filter(Boolean).join('/')

      if (t === 'buy' || t === 'initial') {
        markers.push({ date, kind: 'buy', label: label || '买' })
        buyCount++
        buyVolume += vol
        netVol += vol
      } else if (t === 'sell') {
        markers.push({ date, kind: 'sell', label: label || '卖' })
        sellCount++
        const matched = Math.min(netVol, vol)
        sellVolume += matched
        netVol -= matched
        if (vol > matched) {
          warnings.push(`log#${log.id ?? i} ${date} 卖出 ${vol} 超过净持仓 ${matched}（超卖 ${vol - matched}）`)
        }
      } else if (t === 'clear') {
        const clearVol = Math.max(0, netVol)
        markers.push({
          date,
          kind: 'sell',
          label: log.price != null
            ? `清仓/¥${log.price.toFixed(2)}/${clearVol.toFixed(0)}`
            : '清仓',
        })
        clearCount++
        sellCount++
        sellVolume += clearVol
        netVol = 0
      } else {
        warnings.push(`log#${log.id ?? i} ${date} 未知 op_type=${t} 已忽略`)
        // 非交易类 op 不改 netVol；如需真实 FIFO 需按 position_log 服务端算法扩展
      }

      if (netVol < -1e-6) {
        warnings.push(`log#${log.id ?? i} ${date} netVol 变负=${netVol.toFixed(2)}，后续 clear 量将按 0 处理`)
        netVol = 0
      }
    }

    const firstDate = logs[0]?.op_date?.slice?.(0, 10)
    const lastDate = logs[logs.length - 1]?.op_date?.slice?.(0, 10)
    console.debug(`${SUB.transform} symbol=${symbol} rawLogs=${rawLogs.length} sorted=${logs.length} dateRange=${firstDate ?? '-'}~${lastDate ?? '-'}`, { opCounts, markers: markers.length, netVol })
    if (warnings.length > 0) {
      console.warn(`${SUB.warnings} symbol=${symbol}: ${warnings.join(' | ')}`)
    }

    return {
      markers,
      buyCount,
      sellCount,
      clearCount,
      buyVolume,
      sellVolume,
      lastOp: logs.length ? logs[logs.length - 1] : null,
      logs,
    }
  }, [symbol, q.data?.logs])

  // 最终 summary 产出日志（供 StockPreviewDialog 联调时核对）
  useEffect(() => {
    console.debug(`${SUB.summary} symbol=${symbol} markers=${summary.markers.length} buy=${summary.buyCount}/${summary.buyVolume} sell=${summary.sellCount}/${summary.sellVolume} clear=${summary.clearCount}`)
  }, [symbol, summary])

  return <>{children(summary)}</>
}