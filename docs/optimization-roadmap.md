# TickFlow Stock Panel 功能优化路线图

> 编写日期：2026-08-12
> 状态：规划中
> 承接文档：`docs/review-perfection-plan.md` · `docs/ai-skill-plugin-design.md` · `docs/features.md`

本文档基于对项目全量代码的深度审查，梳理各模块现状、识别功能缺口、给出可执行的优化方案。每一项优化均标注涉及文件、具体代码位置、改动方案、验收标准和风险评估，便于后续逐项实施。

---

## 目录

- [一、项目整体架构认知](#一项目整体架构认知)
- [二、各模块现状总结](#二各模块现状总结)
  - [2.1 AI 复盘模块](#21-ai-复盘模块)
  - [2.2 选股模块](#22-选股模块)
  - [2.3 回测模块](#23-回测模块)
  - [2.4 监控模块](#24-监控模块)
  - [2.5 数据管理与同步](#25-数据管理与同步)
  - [2.6 个股/财务/板块分析](#26-个股财务板块分析)
- [三、优化建议清单（按批次）](#三优化建议清单按批次)
  - [3.1 第一批：快赢——小而实的改进](#31-第一批快赢小而实的改进)
  - [3.2 第二批：闭环——三大模块联动](#32-第二批闭环三大模块联动)
  - [3.3 第三批：健壮——数据安全与运维](#33-第三批健壮数据安全与运维)
- [四、风险与降级策略](#四风险与降级策略)
- [五、验收总清单](#五验收总清单)

---

## 一、项目整体架构认知

### 1.1 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · Pydantic v2 · APScheduler · sse-starlette |
| 数据计算 | Polars（表达式向量化）· DuckDB（SQL 查询）· Parquet（存储） |
| 回测 | vectorbt（唯一 pandas 边界）· 原生信号矩阵引擎 |
| 数据源 | TickFlow SDK · 自定义 HTTP/CSV/JSON 数据源插件 |
| AI | OpenAI 兼容接口（DeepSeek/通义/Ollama）· Skill 插件化 |
| 前端 | React 18 · TypeScript · Tailwind · TanStack Query · ECharts · Lightweight Charts |
| 部署 | Docker 单容器（前端 dist 拷入后端镜像） |

### 1.2 模块架构

```
┌─────────────────────────────────────────────────────────────┐
│                    前端 React 应用                           │
│  Dashboard │ Screener │ Backtest │ Monitor │ Review │ ...   │
│  api.ts (类型契约) │ reviewStore.ts (状态管理)               │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP / SSE / NDJSON
┌────────────────────▼────────────────────────────────────────┐
│                   后端 FastAPI 服务                          │
│  api/ (薄层: 参数校验 + 响应映射)                             │
│    ├── market_recap.py │ positions.py │ settlement.py       │
│    ├── strategy.py │ backtest.py │ monitor.py               │
│    └── data.py │ settings.py │ alerts.py                    │
│                                                             │
│  services/ (业务编排)                                        │
│    ├── market_recap.py │ position_analyzer.py               │
│    ├── settlement_analyzer.py │ ai_provider.py              │
│    ├── json_report_store.py │ market_recap_reports.py       │
│    ├── position_reports.py │ settlement_reports.py          │
│    ├── quote_service.py │ webhook_adapter.py                │
│    └── preferences.py                                        │
│                                                             │
│  ai_skills/ (Skill 插件化 AI 分析)                           │
│    ├── registry.py (自动扫描注册)                            │
│    └── builtin/ (15 个内置 Skill,三方向各 5 个)              │
│                                                             │
│  strategy/ (选股与回测)                                      │
│    ├── engine.py │ composite.py │ ai_generator.py           │
│    ├── backtest/ (原生矩阵引擎 + vectorbt 兼容层)            │
│    └── signals/ (自定义信号库)                               │
│                                                             │
│  jobs/ (定时任务)                                           │
│    └── daily_pipeline.py (盘后管道 + 定时复盘)               │
│                                                             │
│  data/ (持久化)                                             │
│    ├── user_data/ (偏好、AI 报告、监控规则)                  │
│    └── parquet/ (日K、enriched、指数、ETF)                   │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 数据流主链路

```
数据源插件 (TickFlow/自定义)
  → services 同步 + 校验 + 标准化
  → DataStore / KlineRepository / Parquet
  → indicators pipeline 生成 enriched 数据
  → 策略 / 监控 / 回测 / AI 分析服务
  → FastAPI API / SSE
  → 前端 API 类型 + TanStack Query
  → 页面和共享组件
```

### 1.4 核心设计原则

1. **插件化**：数据源、Skill、策略、信号均通过统一接口插件化，禁止硬编码单一供应商
2. **最小范围修改**：改动追溯到当前问题，不顺手重构
3. **金融口径正确**：单位、复权、交易日、时区必须有证据
4. **向后兼容**：新增字段补默认值，读取历史数据允许缺失

---

## 二、各模块现状总结

### 2.1 AI 复盘模块

#### 2.1.1 三方向 Skill 清单

| 方向 | Skill ID | 文件 | 参数 |
|---|---|---|---|
| 大盘 | `market_standard` | `ai_skills/builtin/market_standard.py` | `include_watch_points`(bool), `max_sectors`(int) |
| 大盘 | `market_fundamental` | `ai_skills/builtin/market_fundamental.py` | `news_lookback_days`(int), `include_policy_analysis`(bool) |
| 大盘 | `market_hot_sector` | `ai_skills/builtin/market_hot_sector.py` | `max_boards_analysis`(int), `include_sector_sustainability`(bool) |
| 大盘 | `market_risk_control` | `ai_skills/builtin/market_risk_control.py` | `risk_tolerance`(select), `include_stoploss_suggestions`(bool) |
| 大盘 | `market_technical` | `ai_skills/builtin/market_technical.py` | `include_divergence_analysis`(bool), `timeframe`(select) |
| 持仓 | `holdings_standard` | `ai_skills/builtin/holdings_standard.py` | `include_risk_warnings`(bool), `max_holdings_detail`(int) |
| 持仓 | `holdings_concentration` | `ai_skills/builtin/holdings_concentration.py` | `concentration_threshold_pct`(float), `include_concept_analysis`(bool) |
| 持仓 | `holdings_performance` | `ai_skills/builtin/holdings_performance.py` | `attribution_period`(select), `show_benchmark`(bool) |
| 持仓 | `holdings_rebalancing` | `ai_skills/builtin/holdings_rebalancing.py` | `deviation_threshold_pct`(float), `max_single_position_pct`(float) |
| 持仓 | `holdings_risk` | `ai_skills/builtin/holdings_risk.py` | `risk_free_rate`(float), `include_stress_test`(bool) |
| 交割单 | `settlement_wyckoff` | `ai_skills/builtin/settlement_wyckoff.py` | `include_followup_plan`(bool), `risk_level`(select) |
| 交割单 | `settlement_cost_efficiency` | `ai_skills/builtin/settlement_cost_efficiency.py` | `fee_warning_threshold`(float), `show_top_cost_drivers`(bool) |
| 交割单 | `settlement_discipline` | `ai_skills/builtin/settlement_discipline.py` | `discipline_threshold`(float), `include_warning_examples`(bool) |
| 交割单 | `settlement_monthly_rhythm` | `ai_skills/builtin/settlement_monthly_rhythm.py` | `include_seasonal_analysis`(bool), `show_weekly_distribution`(bool) |
| 交割单 | `settlement_timing_quality` | `ai_skills/builtin/settlement_timing_quality.py` | `timing_lookback_days`(int), `quality_threshold`(select) |

#### 2.1.2 已完成的规划项（review-perfection-plan.md）

| 规划项 | 状态 | 证据 |
|---|---|---|
| A. analyze_positions_once 补 skill 参数 | ✅ 已完成 | `position_analyzer.py` L913-930 |
| B. 定时持仓 job 透传 skill | ✅ 已完成 | `daily_pipeline.py` 持仓 job 已传 skill |
| C. 新增 analyze_settlement_once | ✅ 已完成 | `settlement_analyzer.py` L529-557 |
| D. meta 事件携带 skill 字段 | ✅ 已完成 | market L344-347, holdings L882-884, settlement 均已携带 |
| E. 报告存储保存 skill 信息 | ✅ 已完成 | `json_report_store.py` 读路径补默认值 |
| F. 历史查看时 meta 条跟随 viewing | ✅ 已完成 | `reviewStore.ts` L218-241 |
| G. API 层 skill_id 预校验 | ✅ 已完成 | positions.py L304-314 |
| H. 定时设置弹窗按 Tab 切换 | ✅ 已完成 | `Review.tsx` 三 Tab 独立配置 |
| I. 交割单定时 job + 偏好 + 推送 | ✅ 已完成 | `daily_pipeline.py` L973, 偏好字段已定义 |

#### 2.1.3 报告存储配置

| 方向 | 文件 | MAX_REPORTS | ID 前缀 |
|---|---|---|---|
| 大盘 | `ai_market_recaps.json` | 20 | mkr |
| 持仓 | `ai_position_recaps.json` | 30 | pos |
| 交割单 | `ai_settlement_recaps.json` | 30 | set |

报告 schema 已扩展支持 `skill_id/skill_name/skill_params/model` 字段。

---

### 2.2 选股模块

#### 2.2.1 已实现

- **18 个内置策略**：趋势突破、均线多头、MA/MACD 金叉、布林突破、连板股、断板反包、超跌反转、量价齐升、低波动龙头等
- **策略组合（composite）**：`composite.py` 支持 union/intersect 两种合并模式，子策略 score 归一化加权融合
- **AI 生成策略**：`ai_generator.py` 含 AST 安全沙箱 + 一次自动修复 + META 结构校验
- **ETF 支持**：股票/ETF 切换，ETF 复用 enriched 技术指标
- **一键加自选/加监控**：选股页批量操作

#### 2.2.2 功能缺口

- AI 策略无"历史成功率"统计
- composite 不支持实时监控（`monitor.py` L972-977 fail-closed 跳过）
- 选股结果不能直接发起回测
- 部分策略参数声明但未在 prompt 中消费（装饰性参数）

---

### 2.3 回测模块

#### 2.3.1 已实现

- **三种模式**：个股回测、策略组合回测、自由信号组合回测
- **因子回测**：16 个内置因子，Rank IC/IR/分层收益/多空组合
- **参数优化**：14 种目标函数，网格搜索
- **步进优化（Walk-forward）**：滚动窗口，IS 网格优化 → OOS 回测，防过拟合
- **交易约束**：T+1、佣金、印花税、滑点、止损、止盈、移动止损、最大持仓天数
- **SSE 流式**：进度推送 + 任务缓存 + 重连恢复
- **ETF 支持**：三模式均支持 `asset_type=etf`

#### 2.3.2 功能缺口

- 回测结果无持久化（`get_result()` 返回 None），无法历史对比
- 无对冲机制、无分批建仓/加仓、无动态仓位调整
- 参数优化仅网格搜索且串行执行（`effective_workers=1`）
- Walk-forward 仅限 matrix_native 策略
- 旧 vectorbt 引擎依赖 pandas，与新引擎并存
- 回测结果无法叠加对比

---

### 2.4 监控模块

#### 2.4.1 已实现

- **六类规则**：策略信号、个股信号、价格涨跌、全市场异动、连板封单、板块异动
- **多条件 AND/OR**：单层最多 8 条条件
- **通知渠道**：应用内 SSE、飞书 Webhook、企业微信 Webhook、企业微信智能机器人、系统原生通知
- **冷却去重**：按 (rule_id, symbol, event_type) 3600s 冷却
- **触发记录**：JSONL 追加写，保留 7 天/5000 条
- **sector 监控**：板块成分股异动检测

#### 2.4.2 功能缺口

- AND/OR 不支持嵌套（如 (A且B) 或 (C且D)）
- 通知无邮件/Telegram/钉钉
- 无命中率/误报率统计
- 无规则模板/导入导出
- composite 策略不能实时监控
- sector scope 未实现（fail-closed 禁用）

---

### 2.5 数据管理与同步

#### 2.5.1 已实现

- 盘后管道：15:30 CST 自动拉日 K → 重算 enriched → 跑监控规则
- 数据画像卡片：个股维表、日K、除权、Enriched、指数、ETF、分钟K、财务
- 扩展历史：向更早日期扩展日K
- 数据修正：重新获取或修复指定范围异常数据
- 财务换手率重算：按历史股本/最新维表分级使用
- 令牌桶限流：适配各档位 rpm/batch 限制

#### 2.5.2 功能缺口

- 无断点续传：chunk 级别失败不重试
- 无数据质量校验：不检查缺失交易日、异常价格
- 无备份恢复 UI：仅手动拷目录
- 无精确删除重算范围
- 财务数据全量覆盖写入，非增量

---

### 2.6 个股/财务/板块分析

#### 2.6.1 已实现

- **个股分析**：专用日K + 9 类关键价位 + AI 四维分析（技术/基本面/财务/消息面）
- **财务分析**：利润表/资负表/现金流/关键指标 + AI 解读 + 历史报告
- **概念/行业分析**：涨幅轮动矩阵 + 龙头评分 + 成分股穿透
- **连板梯队**：实时连板层级统计 + 封单监控 + 五档修正
- **看板**：市场情绪 + 涨跌榜单 + 概念领涨 + 异动事件流

#### 2.6.2 功能缺口

- AI 个股分析不支持多轮追问
- 无龙虎榜/资金流向数据
- 财务无同行对比、无自定义公式、无暴雷预警
- 看板布局固定，不可自定义
- 板块分析无历史回溯（某概念过去 N 日轮动规律）

---

## 三、优化建议清单（按批次）

### 3.1 第一批：快赢——小而实的改进

#### 优化项 1：流式生成"取消"按钮

**现状**：底层 `abortGeneration(tab)` 已在 `reviewStore.ts` L206 实现，前端有 `AbortController`，生成中按钮仅禁用变"生成中…"，无停止入口。

**涉及文件**：
- `frontend/src/lib/reviewStore.ts`（已就绪，无需改动）
- `frontend/src/pages/Review.tsx` L455-470（生成按钮区域）
- `backend/app/services/ai_provider.py` L210-232（后端需感知取消）
- `backend/app/services/market_recap.py` L350-370（analyzer 流循环）
- `backend/app/services/position_analyzer.py` L890-910
- `backend/app/services/settlement_analyzer.py` L490-510

**改动方案**：

1. **前端 Review.tsx**：生成中按钮旁加"停止"按钮，点击调用 `abortGeneration(activeTab)`
2. **后端 ai_provider.py**：`stream_ai_text` 接受可选 `CancellationToken`，在 `_stream_openai` 的 `async for chunk in response` 循环中检查取消
3. **三个 analyzer**：在 `async for delta in stream_ai_text(...)` 循环中检查 `await request.is_disconnected()`，中断 LLM 流

**验收标准**：
- 点击"停止"后前端流式输出立即停止，报告保存为已生成的部分内容
- 后端 LLM 请求被正确中断（不浪费 token）
- 已消耗的 token 能统计到 usage 中

**风险**：低。前端 abort 已有基础；后端取消检查需确保不产生僵尸请求。

---

#### 优化项 2：Token 用量与耗时统计

**现状**：全项目无 token 用量统计。settlement 有 5 阶段耗时统计但仅写日志。

**涉及文件**：
- `backend/app/services/ai_provider.py` L274-322（`_stream_openai` 解析 usage）
- `backend/app/services/settlement_analyzer.py` L457-471（meta 事件加 usage/duration）
- `backend/app/services/market_recap.py` L337-348
- `backend/app/services/position_analyzer.py` L874-886
- `frontend/src/pages/Review.tsx` L340-360（报告底部展示）
- `frontend/src/lib/reviewStore.ts` L42（ReviewMeta 类型扩展）

**改动方案**：

1. **ai_provider.py**：OpenAI 流式调用加 `stream_options={"include_usage": True}`，解析 `response.usage` 中的 `prompt_tokens/completion_tokens/total_tokens`
2. **三个 analyzer**：在 meta 事件中加 `{"usage": {"prompt": N, "completion": N, "total": N}, "duration_ms": N}`
3. **前端**：ReviewMeta 类型扩展 `usage`/`duration_ms`，报告底部展示"耗时 12s · 约 1.2k tokens"
4. **报告存储**：usage/duration 字段随 save_report 落盘

**验收标准**：
- 新生成报告的 meta 事件含 usage/duration 字段
- 前端报告底部显示耗时和 token 数
- 老报告无该字段时不显示（兼容）

**风险**：低。流式响应的 usage 需要 `include_usage=True` 参数，需确认所选模型支持。

---

#### 优化项 3：定时复盘三件套

**3a. 数据就绪检查**

**涉及文件**：`backend/app/jobs/daily_pipeline.py` L671,862,973

**改动方案**：三个 job 开头增加检查：
```python
async def _check_data_ready():
    """检查当日日K是否已同步完成"""
    latest_date = await kline_repo.get_latest_date()
    if latest_date < date.today():
        logger.warning("当日日K未就绪(最新=%s, 今日=%s), 跳过复盘", latest_date, date.today())
        return False
    return True
```

**3b. 节假日跳过**

**涉及文件**：`backend/app/jobs/daily_pipeline.py`（CronTrigger 注册处）

**改动方案**：接入 `chinese_calendar` 库，在 job 开头判断是否为法定节假日：
```python
from chinese_calendar import is_workday
if not is_workday(date.today()):
    logger.info("今日非交易日, 跳过复盘")
    return
```

**3c. 重试统一**

**涉及文件**：`backend/app/jobs/daily_pipeline.py`

**改动方案**：将大盘的 `_stream_review_with_retry` 逻辑抽象为三个 job 共用的装饰器，持仓和交割单也加入 3 次重试。

**验收标准**：
- 数据未就绪时 job 跳过并写日志，不生成错误报告
- 国庆/春节等法定节假日不触发复盘
- 持仓/交割单定时复盘有 3 次重试机制
- 重启后补跑（misfire_grace_time=7200）正常

**风险**：中。`chinese_calendar` 需新增依赖；数据就绪检查需处理数据源延迟场景。

---

#### 优化项 4：Skill 参数完善

**现状**：15 个 Skill 的参数均无 description，后端无 min/max 校验，3 个 Skill 存在装饰性参数。

**涉及文件**：
- `backend/app/ai_skills/builtin/*.py`（15 个 Skill 文件的 META.params 定义）
- `backend/app/ai_skills/registry.py` L30-80（`validate_params` 函数）
- `frontend/src/components/review/SkillParamsPanel.tsx`（参数面板渲染）

**改动方案**：

1. **META.params 每个参数加 `description` 字段**：
```python
"params": {
    "include_watch_points": {
        "key": "include_watch_points",
        "label": "包含观察点",
        "type": "bool",
        "default": True,
        "description": "是否在分析中包含关键价位观察点(压力/支撑/整数关口等)"
    }
}
```

2. **registry.py validate_params 加 min/max 校验**：
```python
elif ptype in ("int", "float", "number"):
    value = float(v)
    if "min" in pmeta and value < pmeta["min"]:
        return pmeta.get("default", v)
    if "max" in pmeta and value > pmeta["max"]:
        return pmeta.get("default", v)
```

3. **SkillParamsPanel.tsx**：参数控件下方渲染 description tooltip

4. **清理装饰性参数**：
   - `market_standard.py`：移除 `include_watch_points`（未消费），保留 `max_sectors`
   - `settlement_wyckoff.py`：移除 `include_followup_plan` 和 `risk_level`，或在 prompt 中实际消费
   - `holdings_standard.py`：移除 `include_risk_warnings`，或在 prompt 中实际消费

**验收标准**：
- 所有参数有中文 description
- 前端参数控件悬停显示说明
- API 传入非法值（如 max_sectors=-1）被静默修正为默认值
- 装饰性参数清理后 prompt 逻辑简化

**风险**：低。装饰性参数清理需同步更新前端 UI（SkillParamsPanel 动态渲染）。

---

### 3.2 第二批：闭环——三大模块联动

#### 优化项 5：回测结果持久化与对比

**现状**：旧 `services/backtest.py` L369-372 `get_result()` 返回 None（"暂不实现"）；新引擎结果通过 SSE 一次性返回，不落盘。

**涉及文件**：
- `backend/app/services/backtest.py`（旧引擎持久化实现）
- `backend/app/backtest/strategy.py`（新引擎结果落盘）
- `backend/app/services/json_report_store.py`（扩展支持回测结果存储）
- `backend/app/api/backtest.py`（回测结果列表 API）
- `frontend/src/pages/StrategyBacktest.tsx`（结果对比 UI）

**改动方案**：

1. **扩展 JsonReportStore** 支持回测结果存储（复用基类，新增 `BacktestReportStore`）
2. **新回测引擎**：回测结束后自动 `save_report`，存储 run_id、策略 ID、参数、净值曲线、交易明细统计
3. **前端**：回测结果页增加"历史结果"面板，可选择多次结果叠加对比
4. **API**：`GET /api/backtest/reports` 返回历史列表，`POST /api/backtest/reports/{id}/compare` 返回对比数据

**验收标准**：
- 回测完成后结果自动保存
- 可选择两次回测结果叠加对比（净值曲线叠加、指标差值表格）
- 历史结果可按策略/日期/参数筛选

**风险**：中。回测结果数据量较大（含交易明细），需考虑存储上限和裁剪策略。

---

#### 优化项 6：选股→回测→监控联动

**现状**：三模块各自为政，无联动闭环。

**涉及文件**：
- `frontend/src/pages/Screener.tsx`（选股页加"回测此策略"按钮）
- `frontend/src/pages/StrategyBacktest.tsx`（回测页加"上线监控"按钮）
- `frontend/src/pages/Monitor.tsx`（监控页加"导入策略"入口）
- `backend/app/api/monitor_rules.py`（新增"从回测结果创建监控"端点）

**改动方案**：

1. **选股页**：策略卡片加"回测"按钮，点击跳转回测页并预选该策略
2. **回测页**：结果页加"上线监控"按钮，一键创建 `type=strategy` 监控规则并启用
3. **后端**：新增 `POST /api/monitor-rules/from-backtest` 端点，接收回测 run_id 自动创建监控

**验收标准**：
- 选股 → 回测 → 监控 三步操作可在 3 次点击内完成
- 监控规则自动关联回测 run_id，便于追溯
- 回测参数变更后监控规则参数同步更新

**风险**：低。主要是前端 UI 接线 + 少量后端端点。

---

#### 优化项 7：策略信号绩效追踪（Paper Trading）

**现状**：`alert_store` 记录了触发事件但无后续收益回填，无法评估信号质量。

**涉及文件**：
- `backend/app/services/alert_store.py`（扩展收益回填方法）
- `backend/app/jobs/daily_pipeline.py`（新增"信号绩效回测"定时任务）
- `backend/app/api/alerts.py`（新增绩效统计端点）
- `frontend/src/pages/Monitor.tsx`（绩效展示面板）

**改动方案**：

1. **每日盘后任务**：对历史 N 日触发的信号（N=1/3/5/10/20），回填后续行情收益
2. **新增字段**：alert_store 每条记录加 `tracked_pnl_1d/3d/5d/10d/20d` 及 `hit_max_profit`/`hit_max_loss`
3. **统计 API**：`GET /api/alerts/stats` 返回命中率、平均收益、最大回撤、信号衰减曲线
4. **前端**：监控页新增"绩效"Tab，展示信号质量图表

**验收标准**：
- 每条信号触发后 1/3/5/10/20 日收益自动回填
- 监控页可查看"近 30 日信号命中率 62%，平均收益 +3.2%"
- 可按策略/类型/标的筛选绩效

**风险**：中。需要历史行情数据支持回填，回测计算量需控制。

---

### 3.3 第三批：健壮——数据安全与运维

#### 优化项 8：数据同步断点续传与失败重试

**现状**：chunk 级别失败不重试，大区间同步中断需重来。

**涉及文件**：
- `backend/app/services/tickflow_sync.py`（同步主逻辑）
- `backend/app/tickflow/client.py`（TickFlow 客户端）

**改动方案**：

1. **chunk 重试**：每个 chunk 失败后指数退避重试 3 次
2. **断点记录**：同步进度持久化到 `data/sync_state.json`，记录已完成的日期范围
3. **续传**：同步前检查 `sync_state.json`，跳过已完成的日期，从断点继续
4. **完整性校验**：同步完成后检查日期连续性，标记缺失日期

**验收标准**：
- 中途中断后重新同步可从断点继续
- 完整同步后校验日期连续性
- 每个 chunk 失败有 3 次重试 + 日志

**风险**：中。需确保断点记录的原子性（避免部分写入导致状态不一致）。

---

#### 优化项 9：数据质量校验

**现状**：同步后不检查数据质量，异常值可能静默存在。

**涉及文件**：
- `backend/app/services/tickflow_sync.py`（同步完成回调）
- `backend/app/services/enriched_pipeline.py`（enriched 计算完成回调）
- `frontend/src/pages/Data.tsx`（数据质量面板）

**改动方案**：

1. **同步后自动校验**：
   - 检查交易日连续性（不应有缺失）
   - 检查价格合理性（涨跌幅 >20% 标记异常）
   - 检查除权因子连续性
   - 检查成交量/额非负
2. **数据画像卡片**：增加"缺失率"、"异常值数"指标
3. **前端**：异常数据标红，点击查看详情

**验收标准**：
- 数据异常在数据页清晰可见
- 可一键定位异常日期和标的
- 异常数据不影响正常功能（fail-soft）

**风险**：低。校验是只读的，不修改数据。

---

#### 优化项 10：备份恢复 UI

**现状**：仅操作说明书教用户手动拷目录，无一键备份/恢复。

**涉及文件**：
- `backend/app/services/backup_service.py`（新增备份服务）
- `backend/app/api/settings.py`（备份 API 端点）
- `frontend/src/pages/Settings.tsx`（备份/恢复 UI）

**改动方案**：

1. **备份 API**：`POST /api/settings/backup` 打包 `data/user_data/` 下的 JSON 报告和配置
2. **恢复 API**：`POST /api/settings/restore` 从备份文件恢复
3. **前端**：设置页加"备份与恢复"区域，支持手动备份 + 定时备份配置 + 恢复
4. **定时备份**：APScheduler 每日凌晨自动备份

**验收标准**：
- 一键备份生成带时间戳的 zip 文件
- 恢复后数据完整，功能正常
- 定时备份可配置开关和时间
- 备份文件大小可控（增量备份或压缩）

**风险**：低。需确保恢复时服务暂停，避免并发写入。

---

## 四、风险与降级策略

| 优化项 | 影响范围 | 降级策略 |
|---|---|---|
| 取消按钮 | 前端 UI + 后端流循环 | 后端取消检查失败时不影响正常生成；前端可关闭页面终止 |
| Token 统计 | ai_provider.py | 模型不支持 usage 时字段为 null，不影响报告 |
| 定时复盘就绪检查 | daily_pipeline.py | 检查失败时回退到原逻辑（无条件跑） |
| 节假日跳过 | daily_pipeline.py | `chinese_calendar` 未安装时回退到原 mon-fri Cron |
| Skill 参数校验 | registry.py | 校验失败时回退 default 值，不阻塞生成 |
| 回测持久化 | backtest.py + json_report_store.py | 存储失败时回测结果仍通过 SSE 返回 |
| 信号绩效追踪 | alert_store.py + 新增定时任务 | 回填计算失败时不影响原有监控功能 |
| 断点续传 | tickflow_sync.py | 断点状态文件损坏时回退到全量同步 |
| 数据质量校验 | sync.py + Data.tsx | 校验失败不阻塞已有数据使用 |
| 备份恢复 | backup_service.py | 恢复失败时保留现有数据不变 |

---

## 五、验收总清单

### 第一批验收

- [ ] 复盘生成中有"停止"按钮，点击后流式输出立即停止
- [ ] 后端 LLM 请求被正确中断（不浪费 token）
- [ ] 报告 meta 事件含 `usage`（prompt/completion/total）和 `duration_ms`
- [ ] 前端报告底部显示"耗时 Xs · 约 X.Xk tokens"
- [ ] 老报告无 usage/duration 字段时不显示（兼容）
- [ ] 定时复盘在日K未就绪时跳过并写日志
- [ ] 定时复盘在法定节假日跳过
- [ ] 持仓/交割单定时复盘有 3 次重试
- [ ] 所有 Skill 参数有中文 description
- [ ] 前端参数控件悬停显示说明 tooltip
- [ ] API 传入非法值被静默修正为默认值
- [ ] 装饰性参数清理后 prompt 逻辑正确

### 第二批验收

- [ ] 回测完成后结果自动保存到历史列表
- [ ] 可选择两次回测结果叠加对比
- [ ] 选股 → 回测 → 监控 三步操作 ≤3 次点击
- [ ] 回测结果页有"上线监控"按钮
- [ ] 信号触发后 1/3/5/10/20 日收益自动回填
- [ ] 监控页可查看信号绩效统计

### 第三批验收

- [ ] 数据同步中断后可从断点继续
- [ ] 数据缺失/异常在数据页标红
- [ ] 一键备份生成 zip 文件
- [ ] 恢复后数据完整，功能正常
- [ ] 定时备份可配置开关和时间

---

**下一步**：按批次逐项实施，每完成一项执行对应验收清单。建议从优化项 1（取消按钮）和优化项 2（Token 统计）开始——改动量小、见效快、风险低。