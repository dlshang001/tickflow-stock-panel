# Review 页面标签页扩展方案

## 一、背景与目标

### 当前问题

- `/review` 页面仅有"大盘复盘"功能，持仓分析和交割单分析的 AI 复盘散落在 `Positions.tsx` 的弹窗中
- 弹窗内的历史复盘列表混合显示持仓和交割单报告，无法按类型过滤
- 持仓和交割单报告共用 `ai_position_recaps.json` 存储，查询时无法区分

### 目标

在现有 `/review` 页面增加标签页，将三种 AI 复盘统一到一个页面：

```
/review                     → 默认大盘复盘
/review?tab=market          → 大盘复盘（现有）
/review?tab=holdings         → 持仓分析（从 Positions 弹窗迁入）
/review?tab=settlement       → 交割单分析（从 Positions 弹窗迁入）
```

从持仓/交割单页面点击 AI 分析按钮可跳转到对应标签页。

## 二、存储拆分

### 现状

| 分析类型 | 服务模块 | 存储文件 | 上限 |
|---------|---------|---------|------|
| 大盘复盘 | `market_recap_reports.py` | `ai_market_recaps.json` | 30 条 |
| 持仓复盘 | `position_reports.py` | `ai_position_recaps.json` | 30 条 |
| 交割单分析 | （当前复用 `position_reports`） | `ai_position_recaps.json` | 共用 |

### 目标

| 分析类型 | 服务模块 | 存储文件 | 上限 |
|---------|---------|---------|------|
| 大盘复盘 | `market_recap_reports.py`（不变） | `ai_market_recaps.json` | 30 条 |
| 持仓复盘 | `position_reports.py`（不变） | `ai_position_recaps.json` | 30 条 |
| 交割单分析 | `settlement_reports.py`（**新建**） | `ai_settlement_recaps.json` | 30 条 |

三套存储完全独立，各自管理上限、id 前缀，查询零过滤。

### 拆分优势

1. **查询零过滤** — 各自调 `list_reports()`，不需要 `report_type` 参数
2. **上限独立** — 持仓 30 条、交割单 30 条互不挤占
3. **API 独立** — `/api/positions/reports` 和 `/api/settlement/reports` 各管各的
4. **无需兼容旧数据** — 不用给历史记录补 `report_type` 字段

## 三、后端变更

### 3.1 新建 `settlement_reports.py`

文件：`backend/app/services/settlement_reports.py`

结构复刻 `position_reports.py`，用不同的文件名和 id 前缀实例化 `JsonReportStore`：

```python
"""AI 交割单分析报告持久化存储。

与 position_reports 完全独立 —— 单独文件、上限、id 前缀。
存储位置: data/user_data/ai_settlement_recaps.json (数组, 按 created_at 降序)
保留最近 MAX_REPORTS 条; 超出自动裁剪最旧的。

每条报告结构:
{
  "id": "set_xxx",
  "as_of": "2026-08-11",
  "focus": "",
  "content": "# ...markdown",
  "summary": {
    "total_trades": 2800,
    "buy_count": 1500,
    "sell_count": 1300,
    "total_realized_pnl": 12345.67,
    "records_count": 3297
  },
  "count": 3297,
  "created_at": "2026-08-11T15:35:00"
}
"""
from __future__ import annotations

from app.services.json_report_store import JsonReportStore

MAX_REPORTS = 30

_store = JsonReportStore(
    "ai_settlement_recaps.json", MAX_REPORTS,
    id_prefix="set", id_with_symbol=False,
)


def list_reports() -> list[dict]:
    """返回全部报告(按 created_at 降序)。"""
    return _store.list_reports()


def save_report(report: dict) -> dict:
    """新增一条报告并持久化。返回保存后的报告(含 id / created_at)。"""
    return _store.save_report(report)


def delete_report(report_id: str) -> bool:
    """删除指定报告。返回是否删除成功。"""
    return _store.delete_report(report_id)
```

### 3.2 修改 `settlement.py` — 保存改调独立存储

文件：`backend/app/api/settlement.py`

`POST /api/settlement/analyze` 流结束后的自动归档，从 `position_reports.save_report()` 改为 `settlement_reports.save_report()`：

```python
# stream_gen() 内部，流结束后：
content = "".join(content_parts).strip()
if content:
    try:
        from app.services import settlement_reports
        settlement_reports.save_report({
            "as_of": meta.get("as_of") or "",
            "focus": req.focus or "",
            "content": content,
            "summary": meta.get("summary") or {},
            "count": meta.get("summary", {}).get("records_count", 0),
        })
    except Exception as e:
        logger.warning("auto-save settlement report failed: %s", e)
```

### 3.3 新增交割单报告查询/删除 API

文件：`backend/app/api/settlement.py`

```python
@router.get("/reports")
def list_settlement_reports():
    """获取全部历史交割单分析报告(按时间降序)。"""
    from app.services import settlement_reports
    return {"reports": settlement_reports.list_reports()}


@router.delete("/reports/{report_id}")
def delete_settlement_report(report_id: str):
    """删除一条交割单分析报告。"""
    from app.services import settlement_reports
    ok = settlement_reports.delete_report(report_id)
    return {"ok": ok}
```

### 3.4 API 总览

| 端点 | 方法 | 说明 | 服务模块 |
|------|------|------|---------|
| `/api/market-recap/reports` | GET | 大盘复盘历史 | `market_recap_reports` |
| `/api/market-recap/reports/{id}` | DELETE | 删除大盘复盘 | `market_recap_reports` |
| `/api/positions/reports` | GET | 持仓复盘历史 | `position_reports` |
| `/api/positions/reports/{id}` | DELETE | 删除持仓复盘 | `position_reports` |
| `/api/settlement/reports` | GET | 交割单分析历史（**新增**） | `settlement_reports` |
| `/api/settlement/reports/{id}` | DELETE | 删除交割单分析（**新增**） | `settlement_reports` |

## 四、前端变更

### 4.1 `api.ts` — 新增交割单报告 API

```typescript
// ===== 交割单分析报告 =====
settlementReportsList: () =>
  request<{ reports: any[] }>('/api/settlement/reports'),

settlementReportDelete: (id: string) =>
  request<{ ok: boolean }>(`/api/settlement/reports/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  }),
```

### 4.2 `reviewStore.ts` — 泛化为多模式

现有 `reviewStore` 硬编码只服务大盘复盘（调用 `api.reviewStream()`）。
改为按 tab 隔离状态，支持三种流式 API：

```typescript
type ReviewTab = 'market' | 'holdings' | 'settlement'

// 各 tab 独立状态
let states: Record<ReviewTab, ReviewState> = {
  market:     { ...INITIAL },
  holdings:   { ...INITIAL },
  settlement: { ...INITIAL },
}

let abortCtrls: Record<ReviewTab, AbortController | null> = {
  market: null, holdings: null, settlement: null,
}

// 启动生成时根据 tab 选择流式 API
async function startGeneration(
  tab: ReviewTab,
  focus: string,
  onDone?: (content: string, meta: ReviewMeta | null) => void,
): Promise<void> {
  const streamFn = {
    market:     (f: string) => api.reviewStream(undefined, f),
    holdings:   (f: string) => api.positionAnalyzeStream(f),
    settlement: (f: string) => api.settlementAnalyzeStream(f),
  }[tab]
  // ... 流式处理逻辑（与现有 startReviewGeneration 相同）
}
```

`useReviewState(tab)` hook 改为接收 tab 参数，订阅对应 tab 的状态。

### 4.3 `Review.tsx` — 标签页改造

#### 页面布局

```
┌──────────────────────────────────────────────────────┐
│  AI 复盘                               [刷新][定时][生成] │
├──────────────────────────────────────────────────────┤
│ [📊 大盘复盘] [📈 持仓分析] [📋 交割单分析]   ← 标签页    │
├──────────────────────────────────────────────────────┤
│                                                      │
│  上下文摘要条          │  历史复盘 (N)               │
│  (各 tab 各自的摘要)   │  (调对应 tab 的历史 API)     │
│                        │                             │
│  关注点输入框           │  2026-08-11  6只 +4.7%      │
│                        │  2026-08-06  2800笔 +12k   │
│  AI 报告（流式）        │  ...                        │
│                        │                             │
└──────────────────────────────────────────────────────┘
```

#### Tab 配置

```typescript
const TAB_CONFIG: Record<ReviewTab, {
  label: string
  icon: React.ReactNode
  placeholder: string
  emptyTitle: string
  emptyDesc: string
  loadingText: string
  generateText: string
}> = {
  market: {
    label: '大盘复盘',
    icon: <BarChart3 className="h-3.5 w-3.5" />,
    placeholder: '可选:补充复盘关注点,如「半导体板块持续性如何」',
    emptyTitle: 'AI 大盘复盘',
    emptyDesc: '一键生成今日盘后复盘报告 —— 从一句话定调到明日交易计划',
    loadingText: 'AI 正在复盘今日盘面…',
    generateText: '生成复盘',
  },
  holdings: {
    label: '持仓分析',
    icon: <Wallet className="h-3.5 w-3.5" />,
    placeholder: '可选:如「医药仓位」「风险点」',
    emptyTitle: 'AI 持仓复盘',
    emptyDesc: '综合持仓盈亏、行业集中度、板块强弱与大盘环境,生成客观组合复盘',
    loadingText: 'AI 正在复盘持仓…',
    generateText: '开始复盘',
  },
  settlement: {
    label: '交割单分析',
    icon: <Receipt className="h-3.5 w-3.5" />,
    placeholder: '可选:如「本月盈亏」「佣金占比」「某标的交易得失」',
    emptyTitle: 'AI 交割单分析',
    emptyDesc: '基于交割单的交易盈亏、费用回顾、月度节奏与威科夫交易行为诊断',
    loadingText: 'AI 正在分析交割单…',
    generateText: '开始分析',
  },
}
```

#### 各 Tab 的上下文摘要条

| Tab | 摘要条组件 | 数据来源 | 展示内容 |
|-----|----------|---------|---------|
| market | `MarketSummaryBar`（现有） | `GET /api/overview/market` | 情绪分/指数/涨跌/涨停/成交额 |
| holdings | `HoldingsSummaryBar`（**新建**） | `GET /api/positions` | 持仓只数/总市值/浮盈亏/盈亏分布 |
| settlement | `SettlementSummaryBar`（**新建**） | `GET /api/settlement/stats` | 交易笔数/买卖/已实现盈亏/费用 |

#### 各 Tab 的历史面板

| Tab | 历史 API | 报告字段差异 |
|-----|---------|------------|
| market | `reviewReportsList()` | emotion_score / emotion_label / summary |
| holdings | `positionReportsList()` | count / total_market_value / total_pnl_pct |
| settlement | `settlementReportsList()` | records_count / total_realized_pnl / total_trades |

历史列表项根据 tab 类型渲染不同的摘要信息（盈亏百分比 vs 交易笔数 vs 情绪分）。

#### URL 同步

```typescript
// 从 URL 读取初始 tab
const [searchParams, setSearchParams] = useSearchParams()
const initialTab = (searchParams.get('tab') as ReviewTab) || 'market'
const [activeTab, setActiveTab] = useState<ReviewTab>(initialTab)

// 切换 tab 时更新 URL
const switchTab = (tab: ReviewTab) => {
  setActiveTab(tab)
  setSearchParams({ tab })
}
```

### 4.4 `Positions.tsx` — AI 按钮改为跳转

#### 持仓 AI 按钮

```typescript
import { useNavigate } from 'react-router-dom'
const navigate = useNavigate()

// 原 openAi('holdings') 改为：
const goHoldingsReview = () => navigate('/review?tab=holdings')
```

#### 交割单 AI 按钮

```typescript
// 原 openAi('settlement') 改为：
const goSettlementReview = () => navigate('/review?tab=settlement')
```

#### 弹窗处理

- **方案 A（推荐）**：保留弹窗，但"开始复盘"按钮改为跳转链接，弹窗内历史列表调对应 tab 的过滤 API 做预览
- **方案 B**：直接删除弹窗，AI 按钮改为纯跳转

推荐方案 A，保留弹窗内的历史预览能力，完整分析在 Review 页面。

## 五、reviewStore 泛化细节

### 现有架构

```
reviewStore.ts (全局单例)
  ├── state: { phase, content, error, meta, focus }
  ├── startReviewGeneration(asOf, focus, onDone)
  │     └── 调 api.reviewStream()
  ├── abortReviewGeneration()
  ├── resetReview()
  └── feedReviewEvent(evt)  ← SSE 定时复盘推送
```

### 泛化后

```
reviewStore.ts (多 tab 单例)
  ├── states: Record<ReviewTab, ReviewState>
  ├── startGeneration(tab, focus, onDone)
  │     ├── market     → api.reviewStream()
  │     ├── holdings   → api.positionAnalyzeStream()
  │     └── settlement → api.settlementAnalyzeStream()
  ├── abortGeneration(tab)
  ├── resetTab(tab)
  └── feedReviewEvent(evt)  ← 仅 market tab 接收 SSE
```

### 并发控制

- 每个 tab 独立生成，互不干扰
- 同一 tab 同时只允许一个生成实例
- 切换 tab 不中断后台流（状态保留在 store 中，切回来可恢复）

### 自动归档

| Tab | 归档 API |
|-----|---------|
| market | `api.reviewReportSave()` |
| holdings | （后端 `/api/positions/analyze` 流结束时自动归档） |
| settlement | （后端 `/api/settlement/analyze` 流结束时自动归档） |

持仓和交割单的归档由后端 stream_gen 自动完成，前端不需要调 save API（与现有逻辑一致）。

## 六、实施计划

| 阶段 | 内容 | 涉及文件 |
|------|------|---------|
| **1** | 新建 `settlement_reports.py` | `backend/app/services/settlement_reports.py` |
| **2** | `settlement.py` 保存改调独立存储 + 新增 reports 查询/删除 API | `backend/app/api/settlement.py` |
| **3** | `api.ts` 新增 `settlementReportsList` / `settlementReportDelete` | `frontend/src/lib/api.ts` |
| **4** | `reviewStore.ts` 泛化为多 tab | `frontend/src/lib/reviewStore.ts`, `useReviewStore.ts` |
| **5** | `Review.tsx` 增加标签页 + 各 tab 摘要条/流式/历史 | `frontend/src/pages/Review.tsx` |
| **6** | `Positions.tsx` AI 按钮改为跳转 | `frontend/src/pages/Positions.tsx` |

## 七、不做的事

- 不新建独立页面，复用现有 `/review`
- 不动大盘复盘现有逻辑，仅用标签页包裹
- 不合并存储文件，三套存储各自独立
- 不需要给历史记录补 `report_type` 字段做兼容
- 不改动后端分析逻辑（`position_analyzer.py` / `settlement_analyzer.py` 的 System Prompt 和数据组装不变）

## 八、数据迁移

无需迁移。现有的 `ai_position_recaps.json` 中已保存的报告全部归属持仓复盘（因为之前只有持仓复盘使用此文件）。交割单分析报告从新文件 `ai_settlement_recaps.json` 开始累积。
