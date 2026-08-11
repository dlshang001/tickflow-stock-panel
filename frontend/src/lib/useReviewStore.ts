/**
 * 订阅 reviewStore 的 React hook —— 支持多 tab。
 *
 * mount 时订阅,store 变化触发 re-render;unmount 时退订(但 store 流继续跑)。
 * 用 useSyncExternalStore 保证与 React 18 并发模式兼容。
 */
import { useSyncExternalStore } from 'react'
import {
  getReviewState, subscribeReview, type ReviewState, type ReviewTab,
} from '@/lib/reviewStore'

export function useReviewState(tab: ReviewTab = 'market'): ReviewState {
  return useSyncExternalStore(
    subscribeReview,
    () => getReviewState(tab),
    () => getReviewState(tab),
  )
}
