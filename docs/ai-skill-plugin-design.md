# AI 复盘 Skill 插件化设计方案

## 一、背景与目标

### 现状

- `/review` 页面已支持三种分析域（大盘复盘 / 持仓分析 / 交割单分析），但每个域只有一个固定的 System Prompt
- 分析视角单一，无法在不同分析风格间切换
- 扩展新视角需要直接修改 `*_analyzer.py` 的硬编码 Prompt

### 目标

将 AI 复盘 Skill 做成 **插件化架构**，参考内置策略的 `META + 类` 注册模式：

- 每个分析域（market / holdings / settlement）内置多个 Skill
- 每个 Skill 有独立的 System Prompt、User Prompt 组装逻辑、以及可选的 skill 专属参数
- 前端在 Review 页面通过下拉框切换 Skill，动态渲染参数面板
- 未指定 Skill 时，自动使用该域的默认 Skill（保持现有行为不变）

### 不做的事

- 不删除任何现有 Analyzer 文件
- 历史报告不需要兼容（用户会直接清除旧报告）
- 一期不支持用户自定义 Skill（仅内置）

---

## 二、Skill 分类体系

### Category 定义

| Category | 分析域 | 注入的上下文数据 |
|----------|--------|----------------|
| `market` | 大盘复盘 | 情绪分 / 指数 / 涨跌 / 涨停统计 / 成交额 / 行业概览 |
| `holdings` | 持仓分析 | 持仓列表 / 市值 / 浮盈亏 / 行业分布 / 概念热力图 |
| `settlement` | 交割单分析 | 交易笔数 / 买卖金额 / FIFO 盈亏 / 费用明细 / 对账异常 |

### Skill 清单（一期 15 个）

#### Market 域（5 个）

| Skill ID | 名称 | 定位 | System Prompt 侧重 |
|----------|------|------|-------------------|
| `market_standard` | 标准大盘复盘 | **默认**，现有逻辑 | 情绪定调 + 板块梳理 + 明日计划 |
| `market_technical` | 技术派复盘 | 纯技术面视角 | 均线系统 / 量能配合 / 支撑压力 / 背离判断 |
| `market_fundamental` | 消息面复盘 | 宏观政策视角 | 央行动向 / 产业政策 / 行业新闻影响 |
| `market_hot_sector` | 热点轮动复盘 | 板块轮动视角 | 涨停统计 / 连板梯队 / 板块持续性分析 |
| `market_risk_control` | 风控视角复盘 | 风险优先视角 | 仓位建议 / 止损位 / 风险预警信号 |

#### Holdings 域（5 个）

| Skill ID | 名称 | 定位 | System Prompt 侧重 |
|----------|------|------|-------------------|
| `holdings_standard` | 标准持仓复盘 | **默认**，现有逻辑 | 结构 / 集中度 / 风险 / 调整建议 |
| `holdings_concentration` | 集中度深度分析 | 仓位视角 | 行业 / 概念 / 个股集中度与暴露 |
| `holdings_risk` | 风险敞口分析 | 风控视角 | 最大回撤 / 贝塔 / 相关性 / 流动性风险 |
| `holdings_performance` | 绩效归因分析 | 收益视角 | 行业 / 概念 / 单票收益贡献拆解 |
| `holdings_rebalancing` | 调仓建议专家 | 调仓视角 | 买入 / 卖出 / 减仓 / 加仓 / 置换建议 |

#### Settlement 域（5 个）

| Skill ID | 名称 | 定位 | System Prompt 侧重 |
|----------|------|------|-------------------|
| `settlement_wyckoff` | 威科夫交易行为分析 | **默认**，现有逻辑 | 交易风格 / 买卖时机 / 盈亏 / 费用 |
| `settlement_discipline` | 交易纪律审计 | 纪律视角 | 计划执行率 / 情绪化交易识别 / 偏离度 |
| `settlement_cost_efficiency` | 费用效率专家 | 成本视角 | 佣金 / 印花税 / 过户费 / 高频侵蚀 |
| `settlement_timing_quality` | 买卖时机质量 | 时机视角 | 追涨杀跌模式 / 高抛低吸质量评分 |
| `settlement_monthly_rhythm` | 月度节奏诊断 | 节奏视角 | 月度盈亏 / 季节性规律 / 节奏优化建议 |

---

## 三、后端架构

### 3.1 文件结构

```
backend/app/
├── ai_skills/
│   ├── __init__.py              # 包入口
│   ├── base.py                  # SkillMeta 类型 + AiSkillProtocol
│   ├── registry.py              # 注册表: list_skills() / get_skill() / validate_params()
│   └── builtin/
│       ├── market_standard.py
│       ├── market_technical.py
│       ├── market_fundamental.py
│       ├── market_hot_sector.py
│       ├── market_risk_control.py
│       ├── holdings_standard.py
│       ├── holdings_concentration.py
│       ├── holdings_risk.py
│       ├── holdings_performance.py
│       ├── holdings_rebalancing.py
│       ├── settlement_wyckoff.py
│       ├── settlement_discipline.py
│       ├── settlement_cost_efficiency.py
│       ├── settlement_timing_quality.py
│       └── settlement_monthly_rhythm.py
├── services/
│   ├── market_recap_analyzer.py  # 改造: Skill 委托
│   ├── position_analyzer.py       # 改造: Skill 委托
│   └── settlement_analyzer.py     # 改造: Skill 委托
└── api/
    ├── ai_skills.py              # 新增: Skill 列表端点
    ├── market_recap.py            # analyze 端点增加 skill_id / skill_params
    ├── positions.py               # analyze 端点增加 skill_id / skill_params
    └── settlement.py              # analyze 端点增加 skill_id / skill_params
```

### 3.2 基础类型（base.py）

```python
"""AI Skill 基础类型定义。"""
from __future__ import annotations
from typing import Any, Protocol


class AiSkillProtocol(Protocol):
    """所有 AI Skill 必须实现的协议。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        """组装 System Prompt。

        Args:
            params: Skill 专属参数（已通过 validate_params 校验）
            context: 各域注入的数据
                market:     { market_overview, indices, sentiment, ... }
                holdings:   { snapshot, heatmap, concentration, ... }
                settlement: { stats, reconcile, position_summary, ... }

        Returns:
            完整的 System Prompt 字符串
        """
        ...

    def build_user_prompt(self, params: dict, context: dict) -> str:
        """组装 User Prompt。

        Args:
            params: Skill 专属参数
            context: 各域注入的数据

        Returns:
            完整的 User Prompt 字符串
        """
        ...
```

### 3.3 Skill 文件模板

参考内置策略的 `META + 类` 模式：

```python
"""威科夫交易行为分析 — 分析交易风格、买卖时机、盈亏与费用。"""

META = {
    "id": "settlement_wyckoff",
    "name": "威科夫交易行为分析",
    "category": "settlement",
    "description": "威科夫派交易诊断视角，关注交易风格、买卖时机与情绪模式",
    "tags": ["威科夫", "交易行为", "诊断"],
    "emoji": "🎯",
    "default_for_category": True,
    "params": [
        {
            "id": "include_followup_plan",
            "label": "包含下月改进计划",
            "type": "bool",
            "default": True,
        },
        {
            "id": "risk_level",
            "label": "风险敏感度",
            "type": "select",
            "options": ["保守", "均衡", "激进"],
            "default": "均衡",
        },
    ],
}

SETTLEMENT_BASE_PROMPT = """你是**威科夫交易行为分析专家**。基于用户的真实交割单数据，做交易行为诊断，输出包含以下维度的报告：
1. 整体交易风格评估
2. 各标的交易时机分析
3. 交易盈亏回顾
4. 费用效率分析
5. 月度交易节奏
6. 对账异常分析
7. 关键风险点与改进建议
"""

SETTLEMENT_EXTRA = """
## 你采用威科夫派分析框架
- 积累/派发阶段识别
- 因果关系验证
- 执行力评估
"""


class SettlementWyckoffSkill:
    """交割单分析 — 威科夫视角（默认 Skill）。"""

    def build_system_prompt(self, params: dict, context: dict) -> str:
        prompt = SETTLEMENT_BASE_PROMPT + SETTLEMENT_EXTRA
        if params.get("include_followup_plan", True):
            prompt += "\n## 必须包含：7. 下月具体改进计划（3-5 条，可执行）"
        if params.get("risk_level") == "保守":
            prompt += "\n整体风格偏保守派，强调风险控制优先。"
        return prompt

    def build_user_prompt(self, params: dict, context: dict) -> str:
        stats = context.get("stats", {})
        # 通用数据注入
        lines = [
            f"## 交割单概况",
            f"交易期间: {stats.get('date_range', {}).get('first', '?')} ~ {stats.get('date_range', {}).get('last', '?')}",
            f"总交易 {stats.get('total_trades', 0)} 笔",
            f"买入 {stats.get('buy_count', 0)} 笔 ¥{stats.get('total_buy_amount', 0):,.0f}",
            f"卖出 {stats.get('sell_count', 0)} 笔 ¥{stats.get('total_sell_amount', 0):,.0f}",
            f"FIFO 已实现盈亏 ¥{stats.get('total_realized_pnl', 0):,.0f}",
            f"费用合计 ¥{stats.get('fees', {}).get('total', 0):,.0f}",
            "",
            "## 各标的汇总",
        ]
        for s in stats.get("by_symbol", [])[:15]:
            pnl = s.get("realized_pnl", 0)
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"{s.get('symbol')} {s.get('name', '')} | "
                f"买{s.get('buy_count', 0)}笔 ¥{s.get('total_buy', 0):,.0f} | "
                f"卖{s.get('sell_count', 0)}笔 ¥{s.get('total_sell', 0):,.0f} | "
                f"已实现 ¥{sign}{pnl:,.0f}"
            )
        # 威科夫专属数据
        lines.extend([
            "",
            "### 威科夫专属诊断数据",
            f"胜率: {stats.get('win_count', 0)}胜 / {stats.get('loss_count', 0)}负",
            f"盈亏比: {stats.get('profit_loss_ratio', 0):.2f}",
            f"费用占比: {stats.get('fee_ratio', 0):.3f}%",
        ])
        return "\n".join(lines)
```

### 3.4 注册表（registry.py）

```python
"""AI Skill 注册表 — 管理所有内置 Skill 的发现与查询。"""
from __future__ import annotations
from typing import Any

from app.ai_skills.base import AiSkillProtocol

# === 导入所有内置 Skill ===
# Market 域
from app.ai_skills.builtin.market_standard import (
    MarketStandardSkill, META as _MARKET_STANDARD_META,
)
from app.ai_skills.builtin.market_technical import (
    MarketTechnicalSkill, META as _MARKET_TECHNICAL_META,
)
from app.ai_skills.builtin.market_fundamental import (
    MarketFundamentalSkill, META as _MARKET_FUNDAMENTAL_META,
)
from app.ai_skills.builtin.market_hot_sector import (
    MarketHotSectorSkill, META as _MARKET_HOT_SECTOR_META,
)
from app.ai_skills.builtin.market_risk_control import (
    MarketRiskControlSkill, META as _MARKET_RISK_CONTROL_META,
)

# Holdings 域
from app.ai_skills.builtin.holdings_standard import (
    HoldingsStandardSkill, META as _HOLDINGS_STANDARD_META,
)
from app.ai_skills.builtin.holdings_concentration import (
    HoldingsConcentrationSkill, META as _HOLDINGS_CONCENTRATION_META,
)
from app.ai_skills.builtin.holdings_risk import (
    HoldingsRiskSkill, META as _HOLDINGS_RISK_META,
)
from app.ai_skills.builtin.holdings_performance import (
    HoldingsPerformanceSkill, META as _HOLDINGS_PERFORMANCE_META,
)
from app.ai_skills.builtin.holdings_rebalancing import (
    HoldingsRebalancingSkill, META as _HOLDINGS_REBALANCING_META,
)

# Settlement 域
from app.ai_skills.builtin.settlement_wyckoff import (
    SettlementWyckoffSkill, META as _SETTLEMENT_WYCKOFF_META,
)
from app.ai_skills.builtin.settlement_discipline import (
    SettlementDisciplineSkill, META as _SETTLEMENT_DISCIPLINE_META,
)
from app.ai_skills.builtin.settlement_cost_efficiency import (
    SettlementCostEfficiencySkill, META as _SETTLEMENT_COST_EFFICIENCY_META,
)
from app.ai_skills.builtin.settlement_timing_quality import (
    SettlementTimingQualitySkill, META as _SETTLEMENT_TIMING_QUALITY_META,
)
from app.ai_skills.builtin.settlement_monthly_rhythm import (
    SettlementMonthlyRhythmSkill, META as _SETTLEMENT_MONTHLY_RHYTHM_META,
)


class _RegisteredSkill:
    """一个已注册 Skill 的容器。"""

    def __init__(self, meta: dict, instance: AiSkillProtocol):
        self.meta = meta
        self.instance = instance

    def run(self, params: dict, context: dict) -> tuple[str, str]:
        """执行 Skill：返回 (system_prompt, user_prompt)。"""
        return (
            self.instance.build_system_prompt(params, context),
            self.instance.build_user_prompt(params, context),
        )


SKILLS: dict[str, _RegisteredSkill] = {
    _MARKET_STANDARD_META["id"]: _RegisteredSkill(_MARKET_STANDARD_META, MarketStandardSkill()),
    _MARKET_TECHNICAL_META["id"]: _RegisteredSkill(_MARKET_TECHNICAL_META, MarketTechnicalSkill()),
    # ... 其余 13 个
}


# === 查询 API ===

def list_skills(category: str | None = None) -> list[dict]:
    """列出所有 Skill 的 META（可按 category 过滤）。

    返回: [{id, name, category, description, tags, emoji, params, default_for_category}, ...]
    """
    items = [r.meta for r in SKILLS.values()]
    if category:
        items = [m for m in items if m["category"] == category]
    # 默认 Skill 排在最前
    return sorted(items, key=lambda m: not m.get("default_for_category", False))


def get_skill(skill_id: str) -> _RegisteredSkill:
    """按 id 获取 Skill。找不到抛 ValueError。"""
    if skill_id not in SKILLS:
        raise ValueError(f"未知 Skill: {skill_id}")
    return SKILLS[skill_id]


def default_skill(category: str) -> dict:
    """返回指定 category 的默认 Skill META。"""
    for m in list_skills(category):
        if m.get("default_for_category"):
            return m
    # 兜底：第一个
    return list_skills(category)[0]


def validate_params(meta: dict, raw_params: dict) -> dict:
    """用 META.params 校验用户传入的参数，缺失的补默认值。"""
    result: dict = {}
    for p in meta.get("params", []):
        pid = p["id"]
        val = raw_params.get(pid, p.get("default"))
        result[pid] = val
    return result
```

### 3.5 Analyzer 改造

每个 Analyzer 的核心改动：将硬编码的 `_SYSTEM_PROMPT` 和 `_build_*_user_prompt` 替换为 Skill 委托。

#### settlement_analyzer.py 改造示例

```python
async def analyze_settlement_stream(
    focus: str = "",
    skill_id: str | None = None,
    skill_params: dict | None = None,
) -> AsyncIterator[str]:
    from app.ai_skills import registry

    # Stage 0: 解析 Skill
    if not skill_id:
        skill_id = registry.default_skill("settlement")["id"]
    try:
        skill = registry.get_skill(skill_id)
    except ValueError as e:
        yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        return

    params = registry.validate_params(skill.meta, skill_params or {})
    logger.info("[stream] skill=%s, params=%s", skill_id, params)

    # Stage 1-3: 数据注入（保留现有逻辑，不变）
    stats = _build_stats_for_settlement()
    if not stats or stats.get("records_count", 0) == 0:
        yield json.dumps({"type": "error", "message": "暂无交割单数据"}, ensure_ascii=False)
        return
    # ... reconcile, position_summary 加载 ...

    # Stage 4: 委托 Skill 组装 Prompt（替代硬编码）
    context = {"stats": stats, "reconcile": reconcile_ctx, "position_summary": position_summary}
    system_prompt, user_prompt = skill.run(params, context)

    # Stage 5: LLM 调用（不变）
    # ... async for chunk in llm.stream(system_prompt, user_prompt) ...
```

#### 改造前后对比

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| System Prompt | `_SYSTEM_PROMPT` 常量硬编码 | `skill.build_system_prompt(params, context)` |
| User Prompt | `_build_settlement_user_prompt(stats, reconcile, pos, focus)` | `skill.build_user_prompt(params, context)` |
| Skill 切换 | 不支持 | `analyze_settlement_stream(focus, skill_id, skill_params)` |
| 默认行为 | N/A | 调用 `registry.default_skill("settlement")`，结果与改造前完全一致 |

### 3.6 API 变更

#### 新增 Skill 列表端点

```
GET /api/ai-skills/list?category=settlement
```

返回：
```json
{
  "skills": [
    {
      "id": "settlement_wyckoff",
      "name": "威科夫交易行为分析",
      "category": "settlement",
      "description": "威科夫派交易诊断视角",
      "tags": ["威科夫", "交易行为"],
      "emoji": "🎯",
      "default_for_category": true,
      "params": [
        {"id": "include_followup_plan", "label": "包含下月改进计划", "type": "bool", "default": true},
        {"id": "risk_level", "label": "风险敏感度", "type": "select", "options": ["保守","均衡","激进"], "default": "均衡"}
      ]
    }
  ]
}
```

#### analyze 端点增加参数

| 端点 | 新增参数 | 类型 | 说明 |
|------|---------|------|------|
| `POST /api/market-recap/analyze` | `skill_id` | `string \| null` | 未指定则用默认 |
| | `skill_params` | `object \| null` | Skill 专属参数 |
| `POST /api/positions/analyze` | `skill_id` | `string \| null` | 同上 |
| | `skill_params` | `object \| null` | 同上 |
| `POST /api/settlement/analyze` | `skill_id` | `string \| null` | 同上 |
| | `skill_params` | `object \| null` | 同上 |

#### 报告存储扩展

每条报告增加两个字段：
```json
{
  "id": "set_xxx",
  "skill_id": "settlement_wyckoff",
  "skill_params": {"include_followup_plan": true, "risk_level": "均衡"},
  "as_of": "2026-08-11",
  "content": "# ...",
  "summary": { ... },
  "created_at": "2026-08-11T15:35:00"
}
```

---

## 四、前端变更

### 4.1 新增文件

```
frontend/src/
├── lib/
│   ├── aiSkills.ts              # API 客户端：listSkills()
│   └── skillStore.ts            # 全局 Skill 状态（当前 tab 选中的 skill + 参数）
└── components/
    └── review/
        ├── SkillSelector.tsx    # Skill 下拉选择器
        └── SkillParamsPanel.tsx # Skill 参数配置面板
```

### 4.2 aiSkills.ts — API 客户端

```typescript
import { api } from '@/lib/api'

export interface SkillMeta {
  id: string
  name: string
  category: 'market' | 'holdings' | 'settlement'
  description: string
  tags: string[]
  emoji?: string
  default_for_category?: boolean
  params: SkillParamDef[]
}

export interface SkillParamDef {
  id: string
  label: string
  type: 'bool' | 'select' | 'number' | 'text'
  default?: any
  options?: string[]
  min?: number
  max?: number
  step?: number
}

export async function listSkills(category?: string): Promise<SkillMeta[]> {
  const url = category ? `/api/ai-skills/list?category=${category}` : '/api/ai-skills/list'
  const res = await fetch(url)
  const data = await res.json()
  return data.skills ?? []
}
```

### 4.3 skillStore.ts — 全局 Skill 状态

```typescript
/**
 * 每个 tab 独立的 Skill 选择状态。
 * 切换 tab 时自动加载该 category 的 skill 列表并选中默认 skill。
 */
type SkillTab = 'market' | 'holdings' | 'settlement'

interface SkillState {
  skills: SkillMeta[]       // 该 category 可用的 skill 列表
  selectedId: string | null // 当前选中的 skill id
  params: Record<string, any> // 当前 skill 的参数
  loading: boolean
}

// 各 tab 独立状态
const states: Record<SkillTab, SkillState> = {
  market:     { skills: [], selectedId: null, params: {}, loading: false },
  holdings:   { skills: [], selectedId: null, params: {}, loading: false },
  settlement: { skills: [], selectedId: null, params: {}, loading: false },
}

// 查询: 按 tab 加载 skill 列表
async function loadSkills(tab: SkillTab): Promise<void> { ... }
// 选择: 切换当前 skill（自动补默认参数）
function selectSkill(tab: SkillTab, skillId: string): void { ... }
// 修改参数
function updateParam(tab: SkillTab, paramId: string, value: any): void { ... }
```

### 4.4 SkillSelector.tsx — Skill 选择器

在 Review 页面的标签页右侧添加：

```
┌─────────────────────────────────────────────────────────────┐
│ [大盘复盘] [持仓分析] [交割单分析]          🎯 Skill: [威科夫 ▾] │
└─────────────────────────────────────────────────────────────┘
```

下拉框内容（以 settlement 为例）：
```
┌─────────────────────────────────┐
│ 🎯 威科夫交易行为分析      ✓ 默认 │
│ 💪 交易纪律审计                  │
│ 💰 费用效率专家                  │
│ ⏱️ 买卖时机质量                  │
│ 📅 月度节奏诊断                  │
└─────────────────────────────────┘
```

### 4.5 SkillParamsPanel.tsx — 参数面板

点击 Skill 选择器右侧的 ⚙️ 图标可折叠展开：

```
┌─ Skill 参数 ───────────────────────┐
│ ▢ 包含下月改进计划          [✓]   │
│ 风险敏感度            [均衡 ▾]    │
└────────────────────────────────────┘
```

根据 `SkillMeta.params` 动态渲染控件：
- `bool` → Switch 开关
- `select` → Select 下拉
- `number` → Number Input（带 min/max/step）
- `text` → Text Input

### 4.6 Review.tsx 集成

#### 分析请求携带 Skill 信息

```typescript
const generate = useCallback(() => {
  const skillState = skillStore.getState(activeTab)
  const { selectedId, params } = skillState
  startGeneration(activeTab, focus, {
    skill_id: selectedId ?? undefined,
    skill_params: params,
  }, onDone)
}, [activeTab, focus, onDone])
```

#### 历史报告显示 Skill 标记

```
2026-08-11  🎯 威科夫交易行为分析  2770笔  +11万
2026-08-06  💪 交易纪律审计        2800笔  纪律评分 72
```

历史列表项增加 `emoji + skill name` 副标题。

### 4.7 api.ts 扩展

```typescript
// ===== AI Skill =====
aiSkillList: (category?: string) =>
  request<{ skills: SkillMeta[] }>(
    category ? `/api/ai-skills/list?category=${encodeURIComponent(category)}` : '/api/ai-skills/list'
  ),

// ===== 已修改: analyze 端点增加 skill_id + skill_params =====
settlementAnalyzeStream: async function*(focus?, skillId?, skillParams?) {
  const res = await fetch('/api/settlement/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ focus: focus ?? '', skill_id: skillId, skill_params: skillParams }),
  })
  // ... 流式处理
}
```

---

## 五、实施计划

### 阶段 A — 基础设施（核心改造）

| 步骤 | 内容 | 文件 |
|------|------|------|
| A1 | 创建 `app/ai_skills/base.py` — AiSkillProtocol 类型 | `backend/app/ai_skills/base.py` |
| A2 | 创建 15 个 Skill 骨架（META + 类 + 核心逻辑 = 从现有 Analyzer 迁移） | `backend/app/ai_skills/builtin/*.py` |
| A3 | 创建 `app/ai_skills/registry.py` — 注册表 | `backend/app/ai_skills/registry.py` |
| A4 | 新建 `POST /api/ai-skills/list` 端点 | `backend/app/api/ai_skills.py` |
| A5 | 改造 `settlement_analyzer.py` — Skill 委托 | `backend/app/services/settlement_analyzer.py` |
| A6 | 改造 `position_analyzer.py` — Skill 委托 | `backend/app/services/position_analyzer.py` |
| A7 | 改造 `market_recap_analyzer.py` — Skill 委托 | `backend/app/services/market_recap_analyzer.py` |
| A8 | 3 个 analyze API 增加 `skill_id` / `skill_params` 参数 | `backend/api/{settlement,positions,market_recap}.py` |
| A9 | 报告保存增加 `skill_id` / `skill_params` 字段 | `backend/app/services/{settlement,position,market_recap}_reports.py` |

### 阶段 B — 前端集成

| 步骤 | 内容 | 文件 |
|------|------|------|
| B1 | `api.ts` 增加 `aiSkillList` | `frontend/src/lib/api.ts` |
| B2 | 新建 `aiSkillStore.ts` — 全局 Skill 状态管理 | `frontend/src/lib/aiSkillStore.ts` |
| B3 | 新建 `SkillSelector.tsx` — Skill 下拉选择器 | `frontend/src/components/review/SkillSelector.tsx` |
| B4 | 新建 `SkillParamsPanel.tsx` — 参数面板 | `frontend/src/components/review/SkillParamsPanel.tsx` |
| B5 | `Review.tsx` 集成 Skill 选择器 + 参数面板 + 历史标记 | `frontend/src/pages/Review.tsx` |
| B6 | analyze 流式调用携带 `skill_id` / `skill_params` | `frontend/src/lib/api.ts` |

### 阶段 C — 内容丰富（差异化 Prompt）

| 步骤 | 内容 |
|------|------|
| C1 | 为 15 个 Skill 编写差异化 System Prompt（不是简单复制默认） |
| C2 | 为非默认 Skill 添加专属派生指标计算（如 `settlement_timing_quality` 计算追涨杀跌指数） |
| C3 | 各 Skill 编写专属 User Prompt 切片 |
| C4 | 端到端验证：每个 Skill 能正常生成报告 |

### 开发顺序建议

```
A1 → A2(5个默认skill) → A3 → A4 → A5 → A8(settlement) → A9(settlement)
   → B1 → B2 → B3 → B4 → B5 → B6
   → A2(剩余10个skill) → A6 → A7 → A8 → A9
   → C1-C4
```

优先完成 settlement 域的 Skill 链路，因为当前用户最关注交割单分析。

---

## 六、Skill 差异化 Prompt 编写指南

### 6.1 通用原则

- **默认 Skill**：System Prompt = 现有 Analyzer 的 `_SYSTEM_PROMPT`，确保行为不变
- **差异化 Skill**：System Prompt 在默认基础上增加特定视角的分析框架
- **避免过长**：System Prompt 控制在 500-1500 字，过长会影响 Token 预算
- **结构化输出**：要求 AI 按固定章节输出，便于前端渲染

### 6.2 差异化示例

#### `settlement_discipline` — 交易纪律审计

```
## 你采用交易纪律审计框架

核心审计维度：
1. 计划一致性：实际交易是否符合用户预设的交易计划
2. 情绪化交易识别：识别追涨杀跌、恐慌性抛售等非理性行为
3. 纪律评分：0-100 分，基于偏离交易计划的程度
4. 改进建议：3-5 条具体可执行的纪律改进措施

输出格式：
- 纪律评分: XX/100
- 计划一致性: XX%
- 情绪化交易: [列出具体案例]
- 改进建议: [3-5 条]
```

#### `settlement_timing_quality` — 买卖时机质量

```
## 你采用买卖时机质量评估框架

评估维度：
1. 买入质量：买入价相对后续走势的位置（低买/追高）
2. 卖出质量：卖出价相对后续走势的位置（高卖/杀跌）
3. 追涨杀跌指数：量化追涨杀跌倾向
4. 时机评分：0-100 分

数据注入要求：
- 每个标的的买入价与后续 5/10/20 日高点对比
- 每个标的的卖出价与后续 5/10/20 日低点对比
```

### 6.3 User Prompt 差异化

不同 Skill 的 `build_user_prompt` 可以注入不同的数据切片：

| Skill | 额外注入数据 |
|-------|------------|
| `settlement_discipline` | 每笔交易的买入/卖出时机与后续价格对比 |
| `settlement_cost_efficiency` | 按费用类型分解的成本明细、高频交易侵蚀测算 |
| `settlement_timing_quality` | 买入位置分布（低买/追高比例）、卖出位置分布 |
| `settlement_monthly_rhythm` | 月度盈亏节律、周内分布、日内分布 |

---

## 七、风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| Skill Prompt 质量参差不齐 | 生成报告质量不稳定 | 一期只做结构差异化，不做内容差异化（阶段 C） |
| 部分 Skill 需要额外派生指标 | 开发量增加 | 可在 `build_user_prompt` 内部按需计算，不阻塞核心框架 |
| 用户切换 Skill 后报告历史混在一起 | 历史列表信息混乱 | 历史列表项显示 Skill 名称，用户可按 Skill 过滤（未来增强） |
| 默认 Skill 行为回归 | 破坏现有体验 | 默认 Skill 的 System Prompt 和 User Prompt 1:1 复制现有 Analyzer |

---

## 八、验收标准

### 阶段 A 完成标准

- [ ] `GET /api/ai-skills/list?category=settlement` 返回 5 个 skill
- [ ] `POST /api/settlement/analyze` 支持 `skill_id` 和 `skill_params` 参数
- [ ] 不传 `skill_id` 时，行为与改造前完全一致（Prompt 和输出格式）
- [ ] 报告保存包含 `skill_id` 字段
- [ ] 每个 skill 的 META 完整（id / name / description / params / default_for_category）

### 阶段 B 完成标准

- [ ] Review 页面显示 Skill 选择器（当前 tab 对应的 skill 列表）
- [ ] 切换 Skill 后，"开始分析" 使用新 Skill 的 Prompt
- [ ] Skill 参数面板动态渲染（bool / select / number / text）
- [ ] 历史报告列表显示 Skill 名称和 emoji

### 阶段 C 完成标准

- [ ] 15 个 Skill 的 System Prompt 有差异化（不是完全复制默认）
- [ ] 至少 3 个 Skill 有专属派生指标计算
- [ ] 每个 Skill 端到端生成报告成功
- [ ] 默认 Skill 的报告质量与改造前一致
