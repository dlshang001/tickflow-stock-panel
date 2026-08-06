/**
 * 持仓列配置。
 *
 * 盈亏/市值/仓位占比为前端 computed 列,由 Positions 页面渲染。
 */
import { storage } from '@/lib/storage'
import {
  mergeColumns as mergeColumnsBase,
  type ColumnConfig,
  type ColumnGroup,
} from '@/lib/list-columns'

export type { ColumnConfig, ColumnGroup }

export const COLUMN_GROUPS: ColumnGroup[] = [
  { id: 'position', label: '持仓', icon: '👛', keys: ['cost_price', 'shares', 'market_value', 'pnl_amount', 'pnl_pct', 'weight', 'opened_at', 'note'] },
  { id: 'price', label: '价格', icon: '💰', keys: ['price', 'pct', 'change_amount', 'amplitude'] },
  { id: 'volume', label: '成交', icon: '📊', keys: ['turnover', 'amount', 'float_val', 'vol_ratio', 'annual_vol'] },
  { id: 'ma', label: '均线', icon: '📈', keys: ['ma5', 'ma10', 'ma20', 'ma60'] },
  { id: 'range', label: '区间', icon: '📏', keys: ['high_60d', 'low_60d'] },
  { id: 'tech', label: '技术指标', icon: '🔬', keys: ['rsi6', 'rsi14', 'rsi24', 'macd_dif', 'macd_dea', 'macd_hist', 'kdj_k', 'kdj_d', 'kdj_j', 'boll_upper', 'boll_lower', 'atr14', 'vol_ma5', 'vol_ma10'] },
  { id: 'momentum', label: '动量', icon: '🚀', keys: ['momentum_5d', 'momentum_10d', 'momentum_20d', 'momentum_30d', 'momentum_60d'] },
  { id: 'limit', label: '连板', icon: '🔥', keys: ['limit_ups', 'limit_downs'] },
  { id: 'signal', label: '信号/图表', icon: '📡', keys: ['signals', 'candle', 'intraday'] },
  { id: 'finance', label: '财务', icon: '📋', keys: ['eps', 'bps', 'roe', 'pe_ttm', 'pb', 'gross_margin', 'net_margin', 'revenue_yoy', 'net_income_yoy', 'debt_ratio'] },
]

export const BUILTIN_COLUMNS: ColumnConfig[] = [
  { id: 'builtin:symbol', source: { type: 'builtin', key: 'symbol' }, label: '代码/名称', visible: true, pinned: true, align: 'left' },
  { id: 'builtin:price', source: { type: 'builtin', key: 'price' }, label: '现价', visible: true, align: 'center' },
  { id: 'builtin:pct', source: { type: 'builtin', key: 'pct' }, label: '今涨跌', visible: true, align: 'center' },
  { id: 'pos:cost_price', source: { type: 'builtin', key: 'cost_price' }, label: '成本价', visible: true, align: 'center' },
  { id: 'pos:shares', source: { type: 'builtin', key: 'shares' }, label: '持股数', visible: true, align: 'center' },
  { id: 'pos:market_value', source: { type: 'builtin', key: 'market_value' }, label: '市值', visible: true, align: 'center' },
  { id: 'pos:pnl_amount', source: { type: 'builtin', key: 'pnl_amount' }, label: '盈亏额', visible: true, align: 'center' },
  { id: 'pos:pnl_pct', source: { type: 'builtin', key: 'pnl_pct' }, label: '盈亏比例', visible: true, align: 'center' },
  { id: 'pos:weight', source: { type: 'builtin', key: 'weight' }, label: '仓位占比', visible: true, align: 'center' },
  { id: 'pos:opened_at', source: { type: 'builtin', key: 'opened_at' }, label: '建仓日期', visible: true, align: 'center' },
  { id: 'pos:note', source: { type: 'builtin', key: 'note' }, label: '备注', visible: true, align: 'left' },
  // 通用行情列(默认隐藏,可在列自定义里开启)
  { id: 'builtin:change_amount', source: { type: 'builtin', key: 'change_amount' }, label: '涨跌额', visible: false, align: 'center' },
  { id: 'builtin:amplitude', source: { type: 'builtin', key: 'amplitude' }, label: '振幅', visible: false, align: 'center' },
  { id: 'builtin:turnover', source: { type: 'builtin', key: 'turnover' }, label: '换手率', visible: false, align: 'center' },
  { id: 'builtin:amount', source: { type: 'builtin', key: 'amount' }, label: '成交额', visible: false, align: 'center' },
  { id: 'builtin:float_val', source: { type: 'builtin', key: 'float_val' }, label: '流通值', visible: false, align: 'center' },
  { id: 'builtin:vol_ratio', source: { type: 'builtin', key: 'vol_ratio' }, label: '量比', visible: false, align: 'center' },
  { id: 'builtin:annual_vol', source: { type: 'builtin', key: 'annual_vol' }, label: '年化波动', visible: false, align: 'center' },
  { id: 'builtin:ma5', source: { type: 'builtin', key: 'ma5' }, label: 'MA5', visible: false, align: 'center' },
  { id: 'builtin:ma10', source: { type: 'builtin', key: 'ma10' }, label: 'MA10', visible: false, align: 'center' },
  { id: 'builtin:ma20', source: { type: 'builtin', key: 'ma20' }, label: 'MA20', visible: false, align: 'center' },
  { id: 'builtin:ma60', source: { type: 'builtin', key: 'ma60' }, label: 'MA60', visible: false, align: 'center' },
  { id: 'builtin:high_60d', source: { type: 'builtin', key: 'high_60d' }, label: '60日高', visible: false, align: 'center' },
  { id: 'builtin:low_60d', source: { type: 'builtin', key: 'low_60d' }, label: '60日低', visible: false, align: 'center' },
  { id: 'builtin:rsi6', source: { type: 'builtin', key: 'rsi6' }, label: 'RSI6', visible: false, align: 'center' },
  { id: 'builtin:rsi14', source: { type: 'builtin', key: 'rsi14' }, label: 'RSI14', visible: false, align: 'center' },
  { id: 'builtin:rsi24', source: { type: 'builtin', key: 'rsi24' }, label: 'RSI24', visible: false, align: 'center' },
  { id: 'builtin:macd_dif', source: { type: 'builtin', key: 'macd_dif' }, label: 'MACD-DIF', visible: false, align: 'center' },
  { id: 'builtin:macd_dea', source: { type: 'builtin', key: 'macd_dea' }, label: 'MACD-DEA', visible: false, align: 'center' },
  { id: 'builtin:macd_hist', source: { type: 'builtin', key: 'macd_hist' }, label: 'MACD柱', visible: false, align: 'center' },
  { id: 'builtin:kdj_k', source: { type: 'builtin', key: 'kdj_k' }, label: 'KDJ-K', visible: false, align: 'center' },
  { id: 'builtin:kdj_d', source: { type: 'builtin', key: 'kdj_d' }, label: 'KDJ-D', visible: false, align: 'center' },
  { id: 'builtin:kdj_j', source: { type: 'builtin', key: 'kdj_j' }, label: 'KDJ-J', visible: false, align: 'center' },
  { id: 'builtin:boll_upper', source: { type: 'builtin', key: 'boll_upper' }, label: '布林上轨', visible: false, align: 'center' },
  { id: 'builtin:boll_lower', source: { type: 'builtin', key: 'boll_lower' }, label: '布林下轨', visible: false, align: 'center' },
  { id: 'builtin:atr14', source: { type: 'builtin', key: 'atr14' }, label: 'ATR14', visible: false, align: 'center' },
  { id: 'builtin:vol_ma5', source: { type: 'builtin', key: 'vol_ma5' }, label: '量MA5', visible: false, align: 'center' },
  { id: 'builtin:vol_ma10', source: { type: 'builtin', key: 'vol_ma10' }, label: '量MA10', visible: false, align: 'center' },
  { id: 'builtin:momentum_5d', source: { type: 'builtin', key: 'momentum_5d' }, label: '5D 动量', visible: false, align: 'center' },
  { id: 'builtin:momentum_10d', source: { type: 'builtin', key: 'momentum_10d' }, label: '10D 动量', visible: false, align: 'center' },
  { id: 'builtin:momentum_20d', source: { type: 'builtin', key: 'momentum_20d' }, label: '20D 动量', visible: false, align: 'center' },
  { id: 'builtin:momentum_30d', source: { type: 'builtin', key: 'momentum_30d' }, label: '30D 动量', visible: false, align: 'center' },
  { id: 'builtin:momentum_60d', source: { type: 'builtin', key: 'momentum' }, label: '60D 动量', visible: false, align: 'center' },
  { id: 'builtin:limit_ups', source: { type: 'builtin', key: 'limit_ups' }, label: '连板', visible: false, align: 'center' },
  { id: 'builtin:limit_downs', source: { type: 'builtin', key: 'limit_downs' }, label: '连跌', visible: false, align: 'center' },
  { id: 'builtin:eps', source: { type: 'builtin', key: 'eps' }, label: 'EPS', visible: false, align: 'center' },
  { id: 'builtin:bps', source: { type: 'builtin', key: 'bps' }, label: 'BPS', visible: false, align: 'center' },
  { id: 'builtin:roe', source: { type: 'builtin', key: 'roe' }, label: 'ROE', visible: false, align: 'center' },
  { id: 'builtin:pe_ttm', source: { type: 'builtin', key: 'pe_ttm' }, label: 'PE(TTM)', visible: false, align: 'center' },
  { id: 'builtin:pb', source: { type: 'builtin', key: 'pb' }, label: 'PB', visible: false, align: 'center' },
  { id: 'builtin:gross_margin', source: { type: 'builtin', key: 'gross_margin' }, label: '毛利率', visible: false, align: 'center' },
  { id: 'builtin:net_margin', source: { type: 'builtin', key: 'net_margin' }, label: '净利率', visible: false, align: 'center' },
  { id: 'builtin:revenue_yoy', source: { type: 'builtin', key: 'revenue_yoy' }, label: '营收增速', visible: false, align: 'center' },
  { id: 'builtin:net_income_yoy', source: { type: 'builtin', key: 'net_income_yoy' }, label: '净利增速', visible: false, align: 'center' },
  { id: 'builtin:debt_ratio', source: { type: 'builtin', key: 'debt_ratio' }, label: '负债率', visible: false, align: 'center' },
  { id: 'builtin:signals', source: { type: 'builtin', key: 'signals' }, label: '信号', visible: false, align: 'center' },
  { id: 'builtin:candle', source: { type: 'builtin', key: 'candle' }, label: '日k', visible: false, align: 'center' },
  { id: 'builtin:intraday', source: { type: 'builtin', key: 'intraday' }, label: '分时', visible: false, align: 'center' },
]

export const ACTION_COLUMN_ID = 'pos:action'

export function loadColumnConfig(): ColumnConfig[] {
  const saved = storage.positionsColumns.get([]) as ColumnConfig[]
  if (saved.length > 0) {
    return mergeColumnsBase(saved, BUILTIN_COLUMNS, { actionColumnId: ACTION_COLUMN_ID })
  }
  return [...BUILTIN_COLUMNS]
}

export function saveColumnConfig(columns: ColumnConfig[]): void {
  storage.positionsColumns.set(columns.filter(c => c.id !== ACTION_COLUMN_ID))
}
