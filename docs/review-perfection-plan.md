# AI 复盘三方向（大盘/持仓/交割单）功能完善方案

> 状态：待评审
> 编写日期：2026-08-12
> 承接文档：`docs/ai-skill-plugin-design.md` · `docs/review-tabs-design.md`

本方案覆盖大盘复盘、持仓分析、交割单分析三方向共 **9 项** 待完善点，按优先级分为 P0 / P1 / P2 三批。每批尽量保持增量兼容，不破坏现有 API 与数据文件。

---

## 一、现状速览（基线）

### 1.1 已完成核心链路

| 层 | 大盘 (market) | 持仓 (holdings) | 交割单 (settlement) |
|---|---|---|---|
| 内置 Skill 数量 | 5 个（standard / fundamental / hot_sector / risk_control / technical） | 5 个（standard / concentration / performance / rebalancing / risk） | 5 个（wyckoff / cost_efficiency / discipline / monthly_rhythm / timing_quality） |
| 流式 analyzer | `recap_market_stream(skill_id, skill_params)` ✅ | `analyze_positions_stream(skill_id, skill_params)` ✅ | `analyze_settlement_stream(skill_id, skill_params)` ✅ |
| 非流式 analyzer | `recap_market_once()` 仅 focus（无 skill） | `analyze_positions_once()` 仅 focus（无 skill） | ❌ **缺失** |
| 分析 API 契约 | `/api/market-recap/analyze` 含 `skill_id/skill_params` ✅ | `/api/positions/analyze` 含 `skill_id/skill_params` ✅ | `/api/settlement/analyze` 含 `skill_id/skill_params` ✅ |
| Skill 委托日志 | 7 节点详细日志 ✅ | 7 节点详细日志 ✅ | 7 节点详细日志 ✅ |
| 报告存储 JSON | `ai_market_recaps.json` | `ai_position_recaps.json` | `ai_settlement_recaps.json` |
| 报告后端自动归档 | ❌ 前端 `onGenerationDone` 保存 | ✅ stream 结束 `position_reports.save_report` | ✅ stream 结束 `settlement_reports.save_report` |
| 前端 Review Tab | 3 Tab + Skill 选择器 + 参数面板 + 历史独立列表 ✅ | 同左 ✅ | 同左 ✅ |
| 定时复盘 job | `_run_scheduled_review` + 工作日 APScheduler | `_run_scheduled_position_review` + 工作日 APScheduler | ❌ **缺失** |
| 定时偏好字段 | `review_schedule / review_push_channels` | `position_review_schedule / position_review_push_channels` | ❌ **缺失** |
| 设置面板入口 | Review.market Tab 定时弹窗 | Positions 页面单独一个定时弹窗（独立 UI 风格） | ❌ **缺失** |

### 1.2 待完善点总览与依赖

```
  P0 (硬缺口)
    A. analyze_positions_once 补 skill_id/skill_params
    B. daily_pipeline 定时持仓 job 透传 skill
    C. 新增 analyze_settlement_once 非流式版本
   
  P1 (体验/一致性)
    D. meta 事件携带 skill_id/skill_params 字段
    E. 3 份 reports_store 扩展 schema 保存 skill 元信息
    F. 历史报告查看时主区域 meta 条跟随 viewing（而非当前流）
   
  P2 (健壮性/增强)
    G. API 层 pre-validate：skill_id 不存在或 category 不匹配 → 400（非静默 fallback）
    H. Review 定时设置弹窗按 activeTab 切换类型；新增持仓 Tab、交割单 Tab
    I. 交割单定时复盘 job + 偏好字段 + 推送
   
  依赖：B → A；I → C
```

---

## 二、P0：硬缺口——不可用的功能补齐

### 2.1 A. `analyze_positions_once` 扩展 skill 参数

**涉及文件**：`backend/app/services/position_analyzer.py`

**当前签名**：
```ts
analyze_positions_once(repo, quote_service, pos_rows, focus="")
```

**改造后签名**：
```ts
analyze_positions_once(repo, quote_service, pos_rows, focus="", skill_id=None, skill_params=None)
```

**实现要点**：
1. 在 `async for chunk in analyze_positions_stream(...)` 调用中补传 `skill_id` 与 `skill_params`
2. 保持 `analyze_positions_stream` 内部 fallback 逻辑（skill 失败降级硬编码 prompt），外层 once 不做额外处理
3. 对返回的 `meta` 字典**不改变**外部结构（保持向后兼容），后续 D 点再扩展 skill 字段

### 2.2 B. 定时持仓复盘 job 透传默认 skill

**涉及文件**：`backend/app/jobs/daily_pipeline.py` · `backend/app/services/preferences.py` / 偏好存储 schema

**目标**：定时生成优先使用用户偏好的默认 skill；无偏好时使用 `registry.default_skill("holdings")`

**实现步骤**：

1. **偏好 schema 扩展**（如果已有字段可复用则跳过）：
   - 在 `preferences.get()` 返回 dict 中新增可选键：
     ```json
     {
       "position_review_default_skill": "holdings_risk",
       "position_review_default_skill_params": { "focus_risk": "drawdown" }
     }
     ```
   - 两键均可选，缺省 fallback 到 registry

2. **`_run_scheduled_position_review` 改造**：
   ```python
   async def _run_scheduled_position_review(repo) -> None:
       from app.ai_skills import registry
       from app.services import preferences
       # ... 原有 AI key / 持仓空检查
       default = preferences.get_position_default_skill()
       skill_id = default.get("id")
       skill_params = default.get("params") or {}
       content, meta = await analyze_positions_once(
           repo, quote_service, pos_rows,
           focus="", skill_id=skill_id, skill_params=skill_params,
       )
       # ... 保存/推送不变
   ```

3. **辅助函数 `preferences.get_position_default_skill()`**：
   - 优先读偏好 `position_review_default_skill`（再带 `_params`）
   - 回落到 `registry.default_skill("holdings")["id"]`，params 为 `{}`
   - 无论走哪条，最终返回 `{"id": str, "params": dict}` 统一结构

### 2.3 C. 新增 `analyze_settlement_once` 非流式版本

**涉及文件**：`backend/app/services/settlement_analyzer.py`

**对齐参考**：`position_analyzer.analyze_positions_once` · `market_recap.recap_market_once`

**函数签名**：
```python
async def analyze_settlement_once(
    focus: str = "",
    skill_id: str | None = None,
    skill_params: dict | None = None,
) -> tuple[str | None, dict]:
```

**返回约定**（与 holdings/market once 对齐）：
- `(content, meta)`，失败为 `(None, meta)`
- `meta` 至少含 `{"as_of", "summary"}`，与 `analyze_settlement_stream` 中 meta 事件 yield 的结构完全一致

**实现要点**：
1. 在 `settlement_analyzer.py` 末尾（与流式函数相邻）追加 once 版本
2. 流式 yield 的 `meta` / `delta` / `error` / `done` 累积方式与兄弟 once 函数完全同构
3. **不**触发报告归档（归档由后续 job 的 `settlement_reports.save_report` 显式调）

---

## 三、P1：体验与一致性——技能信息贯穿与历史展示

### 3.1 D. meta 事件携带 skill 标识

**涉及文件**：
- `backend/app/services/market_recap.py`
- `backend/app/services/position_analyzer.py`
- `backend/app/services/settlement_analyzer.py`

**变更点**：在三处 analyzer 的 `{"type": "meta"}` yield 中，统一加入：
```json
{
  "skill_id":  "market_standard" | null,
  "skill_name": "大盘标准复盘"   | null,
  "skill_params": { /* ... */ }
}
```

字段约定：
- 三字段**永远存在**，值为 `null` 表示走默认硬编码 prompt（便于前端无需判断 key 存不存在）
- `skill_params` 始终是 dict（空则 `{}`）

**注入时机**：在 Skill 委托块内赋值 `_skill_id/_skill_name/_skill_params` 三个局部变量；无 skill 路径则三个均为 `null/{}`；拼 meta 事件时统一写入。

### 3.2 E. 报告存储 schema 扩展——保存 skill 信息

**涉及文件**：
- `backend/app/services/market_recap_reports.py`
- `backend/app/services/position_reports.py`
- `backend/app/services/settlement_reports.py`
- 三者复用的 `backend/app/services/json_report_store.py`（如存在）

**schema 扩展（3 份独立存储，字段结构相同）**：

```typescript
interface AiReportV2 {
  id: string
  as_of: string            // 复盘日期（market 有；持仓/交割单为生成日）
  archived_at: string      // 归档时刻 ISO
  focus: string
  content: string

  // 新增:生成时用的 skill 信息
  skill_id: string | null       // null = 走硬编码默认 prompt
  skill_name: string | null     // 中文 name,用于历史列表徽章
  skill_params: Record<string, any> | null  // 传了才落,默认{}

  // 各 tab 原有字段,保持不变
  // market:     summary(str) · emotion_score · emotion_label
  // holdings:   summary(dict) · count
  // settlement: summary(dict) · count
}
```

**兼容性策略**：
- 老 JSON 文件读入时，若缺 `skill_id/skill_name/skill_params` 则补默认 `null/null/null`（读路径做兼容性），不再写回旧结构
- 新写入一律带新字段（即使为 null）
- 无需迁移脚本：JSON 追加字段是兼容演进

**保存调用链补参**：
- `market_recap_reports.save_report(payload)`：payload 允许 `skill_id/skill_name/skill_params`
  - 调用方：Review 页前端 `reviewReportSave`（API `POST /api/market-recap/reports`）——需要**前端一起改**，从最后一条 meta 里取 skill 字段一并带上
  - 调用方：`daily_pipeline._run_scheduled_review`——从 `meta` 中取 skill 字段
- `position_reports.save_report(payload)`：已有后端 `position_analyzer_stream` 流结束后保存——从 `meta` 中取 skill 字段补齐
- `settlement_reports.save_report(payload)`：同上

### 3.3 F. 历史报告查看时 meta 条跟随 viewing

**涉及文件**：`frontend/src/pages/Review.tsx`

**现状问题**：
- `meta` 变量来自 `getReviewState(activeTab).meta`（反映"正在生成/最后一次生成"的 meta）
- `viewReport(r)` 仅把 `r.content` 覆盖进主区域，但**页面顶部摘要条（情绪灯/涨跌家数/持仓 KPI/交割单数字）** 和 meta 事件驱动的二级展示仍然显示"当前"而非"这条历史"

**改造**：
1. 新增派生变量 `displayMeta`：
   ```ts
   const storeMeta = getReviewState(activeTab).meta
   const displayMeta = useMemo(() => {
     if (viewing) {
       // 历史报告里的 summary / emotion_* / count 等扁平化成 ReviewMeta 结构
       return { ...storeMeta, ...viewing }
     }
     return storeMeta
   }, [viewing, storeMeta])
   ```
2. 原代码所有引用 `meta.xxx` 处（除 `content/phase` 外）全部改为 `displayMeta.xxx`
   - 典型：顶部情绪灯 `displayMeta.emotion_score`、持仓摘要条 `displayMeta.summary?.count`、交割单 `displayMeta.summary?.records_count`
3. 历史列表每一项 UI（HistoryPanel）追加"Skill 徽章"，值为 `report.skill_name ?? report.skill_id ?? "默认 Prompt"`；无 skill 信息的老报告显示"默认 Prompt"灰色徽章

---

## 四、P2：健壮性与增强

### 4.1 G. API 层 skill_id 预校验

**涉及文件**：
- `backend/app/api/market_recap.py` · `AnalyzeRequest` handler
- `backend/app/api/positions.py`
- `backend/app/api/settlement.py`

**目标**：skill_id 不存在或类别不匹配时，**前端收到明确 400**，而不是 analyzer 静默 fallback 成默认 prompt。

**改造逻辑（三处 handler 结构一致）**：
```python
@router.post("/analyze")
async def analyze_settlement(request: Request, req: AnalyzeRequest):
    if req.skill_id:
        from app.ai_skills import registry
        try:
            skill = registry.get_skill(req.skill_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        # 类别强校验
        if skill.meta.get("category") != "settlement":
            raise HTTPException(
                400,
                f"Skill {req.skill_id}(类别 {skill.meta.get('category')}) 不适用于交割单分析,期望 category=settlement",
            )
    # ... 原有 handler 流程不变
```

对 `positions` / `market` 两个端点，类比校验 `category == "holdings"` 和 `category == "market"`。

**为什么仍然保留 analyzer 内部 fallback？**
- analyzer 内部 fallback 面向"定时 job、非 HTTP 上下文、以及调用链中间环节"的健壮性
- API 层的预校验是面向"前端用户期望明确"的快速失败
- 两层并存不冲突：经过 API 层的都已合法，analyzer 内的 try/catch 基本走不到

### 4.2 H. Review 定时设置弹窗按 Tab 切换三类型

**涉及文件**：
- `frontend/src/pages/Review.tsx`
- `backend/app/api/settings.py` / `api.preferences` · 偏好字段扩展（见 I 点）
- `backend/app/services/preferences.py`

**现状**：
- 定时设置弹窗（`showSchedule`）只在 `activeTab === 'market'` 时才渲染按钮
- Positions 页面另写了**一套独立 UI**（另一个本地草稿 + 独立 mutation），风格与 Review 不一致

**改造目标**：**统一**在 Review 页面按当前 Tab 渲染对应类型的定时设置。

**弹窗 UI 分块**：
```
 ┌─ 定时复盘设置 ─────────────────────────────┐
 │ 类型（按当前 Tab 固定显示）:                │
 │   [☑] 大盘复盘   [☑] 持仓分析   [☑] 交割单  │
 │                                              │
 │ 启用开关 + 时刻选择                          │
 │   ☐ 启用（按 Tab 类型分别独立开关）          │
 │   ⏰ 时间 HH:MM                              │
 │                                              │
 │ 推送渠道（独立多选,和定时开关解耦）:          │
 │   ☑ 飞书   ☐ 企业微信                        │
 │                                              │
 │                           [取消] [保存设置]  │
 └──────────────────────────────────────────────┘
```

**实现要点**：
1. 弹窗**取消** `activeTab === 'market'` 的按钮渲染限制，三 Tab 均显示时钟按钮
2. 弹窗内增加一个 **Tab 内联切换器**（大盘 / 持仓 / 交割单），默认选中当前 activeTab；各 Tab 草稿状态独立保存（`draftMarket / draftHoldings / draftSettlement`），避免串扰
3. 推送渠道**独立展示**，显示"复盘推送到..." 说明，与市场定时的 `review_push_channels` 分开：
   - 持仓推送：`position_review_push_channels`
   - 交割单推送：`settlement_review_push_channels`（新字段，见 I）
4. 保存接口分类型调用：market → 已存在；holdings → 复用现有 `updatePositionReviewSchedule` + `updatePositionReviewPush`；settlement → 新增（见 I）
5. Positions 页面原有独立定时面板：标记为"冗余"并改路由到 `/review?tab=holdings`，避免双份 UI

### 4.3 I. 交割单定时复盘：Job + 偏好 + 推送

**涉及文件**：
- `backend/app/jobs/daily_pipeline.py`
- `backend/app/services/preferences.py`
- `backend/app/api/settings.py`（或独立 preferences API）
- 前端 Review.tsx 定时弹窗（见 H）

#### 4.3.1 新增偏好字段

```json
{
  "settlement_review_schedule":  { "enabled": false, "hour": 15, "minute": 40 },
  "settlement_review_push_channels": [],
  "settlement_review_default_skill": "settlement_wyckoff",
  "settlement_review_default_skill_params": {}
}
```

字段与 market / holdings 的命名规则完全对齐（前缀 `settlement_review_`）。

#### 4.3.2 新增后端 job：`_run_scheduled_settlement_review`

**对齐** holdings 定时 job 的结构：

```python
async def _run_scheduled_settlement_review(repo) -> None:
    from app.ai_skills import registry
    from app.services import settlement_reports, preferences
    from app.services.settlement_analyzer import analyze_settlement_once

    if not ss.get_ai_key(): return
    records = settlement.all_records()
    if not records: return  # 没交割单跳过

    default = preferences.get_settlement_default_skill()
    content, meta = await analyze_settlement_once(
        focus="", skill_id=default["id"], skill_params=default.get("params") or {},
    )
    if not content: return

    settlement_reports.save_report({
        "as_of": meta.get("as_of") or date.today().isoformat(),
        "focus": "",
        "content": content,
        "summary": meta.get("summary") or {},
        "count": meta.get("summary", {}).get("records_count", 0),
        "skill_id": meta.get("skill_id"),
        "skill_name": meta.get("skill_name"),
        "skill_params": meta.get("skill_params"),
    })
    _maybe_push_settlement_review(content, meta)
```

#### 4.3.3 注册 APScheduler 触发器

```python
def _register_settlement_review_job(sched):
    pref = preferences.get_settlement_review_schedule()
    cron = CronTrigger(
        day_of_week="mon-fri",
        hour=pref.get("hour", 15),
        minute=pref.get("minute", 40),
        timezone="Asia/Shanghai",
    )
    sched.add_job(
        _run_scheduled_settlement_review_wrapper,
        trigger=cron,
        id="settlement_review_scheduled",
        replace_existing=True,
    )
```

与 market / holdings 两个触发器注册点同构，都放在 `daily_pipeline.py` 的 job 注册总入口里。

#### 4.3.4 推送 `_maybe_push_settlement_review`

完全镜像 `_maybe_push_position_review`：
```python
def _maybe_push_settlement_review(content, meta):
    channels = preferences.get_settlement_review_push_channels()
    if not channels: return
    title = f"交割单 AI 分析 · {meta.get('as_of','')}"
    summary = meta.get("summary") or {}
    summary_md = (
        f"- 交易笔数: {summary.get('total_trades', 0)}\n"
        f"- 已实现盈亏: ¥{summary.get('total_realized_pnl', 0):,.0f}\n"
        f"- 交易费用: ¥{summary.get('total_fee', 0):,.0f}"
    )
    body = f"{summary_md}\n\n---\n{content[:2500]}"
    webhook_adapter.dispatch(channels, title, body, fail_silent=True)
```

#### 4.3.5 前端 Settings API 补齐（如不存在）

新增或扩展偏好接口：
- 读取：在 `GET /api/preferences` 返回值中带上上面 4 个新键
- 更新：
  - `PUT /api/preferences/settlement-review-schedule` 或复用统一偏好更新接口
  - `PUT /api/preferences/settlement-review-push` 用于推送渠道多选即时保存

---

## 五、实施阶段与风险

### 5.1 推荐阶段划分

```
阶段 1 (P0)     A + B + C      共 3 项 — 补齐不可用功能,无前端改动,最快落地
阶段 2 (P1)     D + E + F      共 3 项 — 前后端联动,skill 信息贯穿 UI
阶段 3 (P2)     G + H + I      共 3 项 — 含定时设置 UI 重构 + 交割单定时,量最大
```

每阶段**独立可验证**：阶段 1 结束即可在"定时持仓复盘"中验证 skill 生效；阶段 3 独立不依赖 P1 部分字段（但若 E 先落盘，I 的 save_report 更完整，建议阶段顺序执行）。

### 5.2 风险与降级

| 风险 | 影响 | 降级策略 |
|---|---|---|
| 老报告 JSON 混入新字段后读取崩 | P1-E 点 | 读取路径对缺字段补 null，`json_report_store.py` 增加兼容单元 |
| 前端 Review meta 改动导致 market 以外 tab 的 summary bar 崩 | P1-F 点 | `displayMeta` 每层用 `??` 兜底，缺省 `—` 展示 |
| 交割单定时 job 在无交割单日期反复跑 | P2-I | all_records() 判空已加；可再加"今日是否新导入交割单"判断避免重复推送 |
| 三类型设置 UI 草稿串扰 | P2-H | 三草稿独立保存，本地用对象 key 隔离 |
| Skill registry 无 settlement 类 skill 时定时 job 崩 | B / I 点 | registry.get_skill 外层 try/catch + fallback 到默认 prompt；外层 job 再吞异常保调度器不死 |

---

## 六、验收清单（每阶段执行后勾选）

### 阶段 1（P0）
- [ ] `analyze_positions_once("holdings_risk", {...})` 生成内容的 system/user prompt 长度明显不同于默认（后端 log `[skill] run ok` 可见）
- [ ] 开启持仓定时 → 手动触发 → 保存的报告 content 风格与 holdings_risk Skill 匹配
- [ ] 代码直接 import `analyze_settlement_once` 调一次能拿到 `(content, meta)` 元组，meta 里有 records_count / total_trades

### 阶段 2（P1）
- [ ] 三 analyze 流的 NDJSON 首条 `meta` 事件含 `skill_id/skill_name/skill_params`
- [ ] 用某个 Skill 生成一份报告 → 查看历史 → 顶部情绪灯/数字是该报告的数据（不是"当前流"）
- [ ] 历史列表每项右上角有 Skill 徽章（例：「威科夫交易行为分析」）
- [ ] 读老报告（无 skill_* 字段）不会崩，徽章显示"默认 Prompt"

### 阶段 3（P2）
- [ ] `POST /api/positions/analyze` 传 `{ skill_id: "market_standard" }` 返回 400，消息含"不适用于持仓分析"字样
- [ ] Review 三 Tab 均有"定时复盘"按钮 → 打开弹窗可分别切换三类型
- [ ] 切换到交割单 Tab → 设置定时 15:40 → 偏好里 `settlement_review_schedule.enabled=true` 且调度器可见该 job
- [ ] 交割单定时 job 跑完 → 报告自动归档 + 配置的推送渠道收到卡片
- [ ] Positions 页面原有定时面板位置改为 navigate 跳转到 `/review?tab=holdings`

---

**下一步**：评审通过后按阶段 1/2/3 顺序实施，每阶段结束用上面清单验证。
