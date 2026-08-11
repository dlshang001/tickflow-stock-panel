# 持仓事件溯源 + 交割单导入与对账 — 设计与开发计划

> 版本：v1（2026-07-28）
> 状态：待实施
> 范围：将 TideWatch 项目中已验证的「操作日志 + FIFO 持仓引擎 + 交割单导入 + 对账」能力，翻译并融入本项目（FastAPI + Polars/Parquet + React/ECharts 技术栈）。

---

## 1. 背景与目标

### 1.1 现状

本项目已有一套基础持仓能力：

- 后端：`backend/app/api/positions.py` + `backend/app/services/positions.py`
- 前端：`frontend/src/pages/Positions.tsx`
- 存储：`data/user_data/positions.parquet`，一个 symbol 一行，字段 `symbol/shares/cost_price/opened_at/note/added_at`
- 已支持：列表、enriched（LEFT JOIN 最新行情）、AI 持仓复盘（流式 NDJSON + 历史归档）

**问题**：持仓数字只能手动填写/直接编辑，无法与真实成交记录核对；没有买卖流水、没有已实现盈亏、没有费用、没有交割单导入。这是典型的"直接维护当前状态"模型，缺少交易历史。

### 1.2 目标

引入**事件溯源（Event Sourcing）**思想：

- 只记录不可变的交易操作日志（买入/卖出/清仓），当前持仓由 **FIFO（先进先出）** 从日志派生。
- 手动录入与交割单导入共用同一条日志链路，互为印证。
- 提供**对账**能力：比较「交割单推导持仓」与「操作日志推导持仓」，差异可一键修正。
- 提供交割单维度的**已实现盈亏、费用、图表可视化**。
- 增强 AI 持仓复盘：注入已实现盈亏、费用、对账结果。

### 1.3 一期范围（已确认）

- 单用户、本地部署（无多用户/RLS）。
- FIFO 引擎放在**后端**（Python），前端只展示。
- 旧 `/api/positions` 接口**直接替换**数据源为 FIFO，响应结构不变（前端无感）。
- 成本口径以 **FIFO 为准**，旧 `cost_price` 仅作迁移时的建仓价。
- 操作类型一期仅 `buy / sell / clear`；**不做** split/dividend/transfer。
- 图表统一使用项目已有的 **ECharts 5**，不引入 recharts。

---

## 2. 与 TideWatch 的差异及翻译策略

TideWatch 实现位于 `/home/myProjects/TideWatch`，核心提交：

- `943bad4` 交割单导入与分析全链路
- `9912710` 操作日志系统（position_log 替代直接编辑）
- `9b136c3` FIFO 持仓引擎 + Agent 工具迁移
- `6b72020` 对账面板
- `3a5b669` 一键清空 / 修正 / 删除

| 维度 | TideWatch | 本项目 | 翻译策略 |
|---|---|---|---|
| 后端框架 | Next.js Route Handler | FastAPI | 重写为 APIRouter + service |
| 数据库 | Supabase / Postgres + RLS | 本地 Polars/Parquet（单用户） | Parquet 文件存储，去重在 service 层 |
| 用户模型 | 多用户 `auth.uid()` | 单用户 | 删除 user_id / RLS，全局文件 |
| FIFO 位置 | 前端 TypeScript | 后端 Python | 移植算法到后端，前端不重算 |
| 持仓现状 | 已重构 | 仍是直接编辑旧模式 | 本次升级重点 |
| 图表 | recharts + lightweight-charts | ECharts 5 | ECharts 重画，复用主题 |
| 前端样式 | Tailwind + indigo | Tailwind + 紫罗兰暗色金融风 | 复用本项目 Modal/PageHeader/表格 |
| AI 分析 | 自有 6 步流程 | 已有 position_analyzer 流式 NDJSON | 扩展现有分析器，不另起炉灶 |
| Excel 解析 | pandas + openpyxl | 已有 pandas/fastexcel/openpyxl | 近乎直接移植 parser |
| 并发/原子写 | 数据库事务 | 文件读写 | 模块级 Lock + 临时文件 os.replace |

**可直接借鉴的资产**：

- `tools/settlement_parser.py`（解析器，逻辑可平移）
- FIFO 算法思想（`computePositionsFromLog` / `computePositionsFromSettlements` / `reconcilePositions`）
- 两阶段导入（dry_run 预览 → commit）、双层去重、行内修正等交互设计

---

## 3. 数据模型

存储目录沿用 `data/user_data/`，与现有 `positions.parquet`、AI 报告 JSON 同级。

### 3.1 `position_log.parquet`（操作日志 — 持仓唯一真相源）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Int64 | 自增主键（写锁内 `max(id)+1`） |
| `op_date` | Utf8 | 操作日期 `YYYY-MM-DD` |
| `op_type` | Utf8 | `buy` / `sell` / `clear`（一期） |
| `symbol` | Utf8 | 6 位证券代码（裸代码，不带 `.SH/.SZ`） |
| `name` | Utf8 | 证券名称 |
| `price` | Float64 | 成交价（`clear` 必填） |
| `volume` | Float64 | 数量（`clear` 可空=全清） |
| `amount` | Float64 | 成交金额（含费用的总付出/总收回，见 §6.3） |
| `commission` | Float64 | 佣金，默认 0 |
| `stamp_duty` | Float64 | 印花税，默认 0 |
| `transfer_fee` | Float64 | 过户费，默认 0 |
| `note` | Utf8 | 备注 |
| `source` | Utf8 | `manual` / `settlement` / `migration` |
| `settlement_id` | Int64 / null | 对应交割单记录 id（幂等同步用） |
| `settlement_batch_id` | Utf8 / null | 交割单批次 id |
| `created_at` | Utf8 | ISO 时间戳 |

索引/约束（Parquet 无数据库索引，逻辑上保证）：

- 排序：读入后按 `(op_date, id)` 升序。
- 幂等：`source='settlement'` 且 `settlement_id` 已存在的记录不重复插入。
- 唯一：逻辑唯一键 `(source, settlement_id)`（仅 settlement 来源）。

### 3.2 `settlement_records.parquet`（交割单原始记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Int64 | 自增 |
| `trade_date` | Utf8 | `YYYY-MM-DD` |
| `symbol` | Utf8 | 6 位代码 |
| `name` | Utf8 | 名称 |
| `direction` | Utf8 | `买入` / `卖出` |
| `price` | Float64 | 成交价 |
| `volume` | Int64 | 成交数量 |
| `amount` | Float64 | 成交金额 |
| `commission` | Float64 | 佣金 |
| `stamp_duty` | Float64 | 印花税 |
| `transfer_fee` | Float64 | 过户费 |
| `net_amount` | Float64 | 发生金额（含费用的净现金流） |
| `source` | Utf8 | 默认 `tonghuashun_settlement` |
| `batch_id` | Utf8 | 导入批次 UUID |
| `created_at` | Utf8 | ISO 时间戳 |

去重键（service 层内存判重）：`(symbol, trade_date, direction, price, volume)`。

### 3.3 现金（free_cash）

存放在用户偏好（preferences）中新增字段 `free_cash: float`，复用现有 settings/preferences 读写机制，不新建文件。

- 买入：`free_cash -= (amount + 费用)`
- 卖出：`free_cash += (amount - 费用)`（净回笼）
- 清仓：等同于按当前持仓量卖出。
- 约束：`free_cash` 不允许为负（买入超额时返回 400）。

> 若 preferences 结构不适合存放该字段，则退化为 `data/user_data/portfolio_meta.json`，仅含 `{"free_cash": 0.0}`，使用 JsonReportStore 同款原子写。

### 3.4 旧数据迁移

`data/user_data/positions.parquet` 中每条持仓 → 一条 `op_type='buy', source='migration'` 日志：

- `op_date` = `opened_at` 或迁移当天
- `price` = `cost_price`
- `volume` = `shares`
- `amount` = `shares * cost_price`
- `note` = `历史持仓迁移`

迁移执行：

1. 在应用启动（main startup）时执行一次，幂等判断：若已存在 `source='migration'` 的日志则跳过。
2. 迁移前把旧文件复制为 `positions.parquet.bak`（不删除，保留回滚能力）。
3. 迁移后 `positions.service` 改读 FIFO，旧文件不再被写入。

---

## 4. 后端设计

### 4.1 模块划分

```
backend/app/
  services/
    position_log.py        # 日志存储 + FIFO 引擎 + 现金 + 迁移 + 交割单同步
    settlement.py          # 交割单存储 + 统计聚合
    settlement_parser.py   # Excel/CSV 解析（移植自 TideWatch）
    reconcile.py           # 对账引擎 + 修正
    positions.py           # 薄适配层（保留旧函数签名，内部委托 position_log）
    position_analyzer.py   # 现有，扩展提示词（阶段5）
  api/
    positions.py           # 扩展：logs / cash
    settlement.py          # 新增：import/records/stats/reconcile
```

### 4.2 `services/position_log.py`

**存储层**（参考现有 `services/positions.py` 的 Polars 读写风格）：

- `_path() -> Path`：`data/user_data/position_log.parquet`
- `_read() -> pl.DataFrame` / `_write(df)`：原子写（临时文件 + `os.replace`）
- 模块级 `_lock = threading.Lock()`，所有写操作在锁内完成
- `_SCHEMA` 常量定义字段类型
- `_next_id(df) -> int`

**CRUD**：

- `list_logs(symbol: str | None = None) -> list[dict]`
- `add_log(op_type, symbol, name, price, volume, op_date, fees, note, source, settlement_id, settlement_batch_id) -> dict`
- `add_logs_batch(logs: list[dict]) -> int`（每批 500，交割单同步用）
- `delete_log(log_id: int) -> None`
- `delete_logs_by_symbol(symbol: str) -> None`（对账"删除"用）
- `clear_all_logs() -> int`（一键清空）

**FIFO 引擎**：

```python
def compute_positions(logs: list[dict] | None = None) -> list[ComputedPosition]:
    """
    按 (op_date, id) 升序处理：
      buy/initial → 入队一个 lot(price, volume, date)
      sell        → 从队首逐批扣减，卖完出队（不得超过当前持仓）
      clear       → 清空该 symbol 的买入队列
    剩余队列 = 当前持仓；成本 = 剩余 lot 的加权平均；buy_date = 最早建仓日。
    返回字段对齐旧 PositionEntry：
      symbol, name, shares, cost_price, opened_at, note(取最新), added_at(最早日志时间)
    """
```

数据结构（移植 TideWatch）：

```python
@dataclass
class BuyLot:
    price: float
    volume: float
    date: str
```

注意：一期 `initial` 类型用于迁移，语义同 `buy`。FIFO 需处理 `volume` 为浮点数（本项目 shares 用 float，兼容 A 股整手但不强转 int）。

**现金联动**：

- `get_free_cash() -> float`
- `set_free_cash(v) -> None`
- `adjust_free_cash(delta: float) -> None`（内部用）
- 写日志时由 `apply_trade()` 统一计算现金流并校验非负。

**交割单同步**：

- `sync_from_settlements(records: list[dict]) -> int`
  - 读取现有日志中所有 `settlement_id` 集合
  - 过滤出未同步的交割单，映射为 `buy/sell` 日志（source='settlement'）
  - 批量插入，返回新增条数

**迁移**：

- `migrate_legacy_positions() -> int`：见 §3.4，幂等。

### 4.3 `services/settlement.py`

- `list_records(date_from, date_to, symbol, page, size) -> {rows, total, page, size}`
- `preview_import(records) -> {preview, new_count, skipped, latest_db_date}`（内存去重，不落库）
- `commit_import(records, batch_id) -> {imported, skipped, batch_id}`（落库 + 去重）
- `delete_record(id) -> None`
- `clear_all() -> int`
- `compute_stats(records=None) -> dict`：
  - `realized_pnl_curve`：按日期累计已实现盈亏（FIFO 配对卖出批次计算）
  - `monthly`：按月汇总盈亏
  - `by_symbol`：单票已实现盈亏、买/卖次数
  - `fees`：commission / stamp_duty / transfer_fee / total

> 已实现盈亏计算：每次卖出时，从买入队首逐批配对，`(sell_price - buy_price) * matched_volume` 累加即为已实现盈亏。该逻辑与 FIFO 引擎共用配对过程。

### 4.4 `services/settlement_parser.py`

移植 TideWatch `tools/settlement_parser.py`，保留：

- 格式 A（PC 端交割单）/ 格式 B（投资账本）自动识别（必需列名集合判定）
- Excel 多 sheet 扫描
- 代码归一化：补零到 6 位、去 `.SZ/.SH/.HK`、去浮点 `.0`
- 日期解析（`%Y-%m-%d` / `%Y/%m/%d` / `%Y%m%d`）
- 数值解析（去千分位逗号）
- 格式 B 过滤非交易流水（银证转账、股息、理财、融券等 12 类）
- 坏行不致命，错误带行号回传

返回结构：

```python
{
  "records": [...],
  "total_rows": int,
  "parse_errors": [{"row": int, "error": str}],
  "filtered_stats": {"银证转帐存": n, ...},
  "format": "A" | "B"
}
```

调整点：

- 移除任何 Supabase/Next.js 耦合（原文件本就是纯函数，几乎无改动）。
- `symbol` 输出统一为 6 位裸代码（与本项目 positions 口径一致）。

### 4.5 `services/reconcile.py`

```python
def reconcile() -> list[ReconItem]:
    """
    1. 读 settlement_records 全部记录 → compute_positions_from_settlements()
    2. 读 position_log 全部日志 → compute_positions()
    3. 按 symbol 合并比对，输出 diffType：
       matched          股数相等且成本价差 < 0.01
       mismatch         两边都有但股数/成本不符
       only_settlement  交割单有、日志没有
       only_position_log 日志有、交割单没有
    4. 差异项排序在前
    """

def fix_item(symbol: str, action: 'fix' | 'delete') -> None:
    """
    fix:
      only_settlement → 按交割单推导结果补一条 buy 日志
      mismatch        → 先写一条 clear 清空旧持仓，再按交割单写 buy 重建
      only_position_log → 通常提示删除，不自动 fix
    delete: 删除该 symbol 的全部 position_log 记录
    操作完成后由调用方重新拉取对账结果。
    """
```

### 4.6 `services/positions.py`（改造为适配层）

保留旧函数签名以兼容现有 API/分析器：

- `list_rows()` → 内部 `position_log.compute_positions()`，字段映射：
  `shares→shares, cost_price→cost_price, opened_at→buy_date, note→最新note, added_at→最早日志created_at`
- `upsert(symbol, shares, cost_price, opened_at, note)` → 写一条 `buy` 日志（source='manual'）。
  - 语义变化：旧 upsert 是"覆盖为该数量"，新语义是"追加买入"。前端将不再调用此接口做编辑，改为 TradeDialog 的 buy/sell/clear。过渡期保留但标注弃用。
- `update(symbol, **fields)` → 仅允许更新 `note`（其他字段改动无意义，持仓由日志派生）；如前端旧编辑入口仍调用，应在阶段1一并移除。
- `remove(symbol)` → 写一条 `clear` 日志（而非直接删除行）。
- `clear()` → `clear_all_logs()`。

### 4.7 API 路由

#### 现有 `api/positions.py`（扩展，前缀 `/api/positions`）

保留：

- `GET ""` 列表（数据源已切 FIFO）
- `GET /enriched`（无需改动，仍调 `positions.list_rows()`）
- `POST /analyze`（阶段5增强提示词）
- `GET/POST/DELETE /reports`（AI 报告归档，不变）

新增：

- `GET /logs` — 操作日志列表，可选 `?symbol=`
- `POST /logs` — 新增操作（买入/卖出/清仓）
  - body: `{ op_type, symbol, name?, price, volume?, op_date?, commission?, stamp_duty?, transfer_fee?, note? }`
  - 返回: `{ rows, logs, free_cash }`
  - 校验：卖出量不得超过 FIFO 持仓；买入后现金不得为负
- `DELETE /logs/{id}` — 删除单条日志
- `GET /cash` / `PUT /cash` — 可用资金读写

逐步弃用（阶段1后前端不再调用，但保留一个版本）：

- `POST ""` (upsert)、`PATCH /{symbol}`、`DELETE /{symbol}`、`DELETE ""`

#### 新增 `api/settlement.py`（前缀 `/api/settlement`）

- `POST /import`（multipart）
  - 表单字段：`file: UploadFile`、`dry_run: bool = true`
  - dry_run=true：解析 + 内存去重，返回预览，不落库
  - dry_run=false：解析 + 落库 + 自动同步 position_log
  - 返回：
    ```json
    {
      "preview": [...],
      "parse_errors": [{"row": 12, "error": "..."}],
      "filtered_stats": {...},
      "format": "A",
      "new_count": 38,
      "skipped": 2,
      "latest_db_date": "2026-07-25",
      "batch_id": "uuid",
      "imported": 38
    }
    ```
- `GET /records` — `?page=&size=&date_from=&date_to=&symbol=`
- `DELETE /records` — 清空全部（`?batch_id=` 可按批删除）
- `GET /stats` — 图表聚合数据
- `GET /reconcile` — 对账结果
- `POST /reconcile/fix` — `{ symbol, action: 'fix'|'delete' }`

在 `app/main.py` 注册：`app.include_router(settlement.router)`。

### 4.8 AI 分析增强（阶段5）

`services/position_analyzer.py` 在装配持仓上下文时，追加：

- 交割单统计：已实现盈亏总额、费用合计、月度盈亏、单票盈亏 Top/Bottom
- 对账异常：mismatch / only_* 的标的清单（若有）
- 现金流：当前 free_cash、累计买入/卖出金额

提示词增加一段："以下为该账户基于真实交割单的已实现盈亏与费用数据，请结合当前持仓进行复盘……"。流式协议与归档不变。

---

## 5. 前端设计

### 5.1 目录结构

```
frontend/src/
  lib/
    api.ts                      # 新增 settlement/position-log API 方法
    queryKeys.ts                # 新增 QK 键
  components/
    positions/
      TradeDialog.tsx           # 买入/卖出/清仓弹窗
      OperationTimeline.tsx     # 操作历史时间线
      CashOverview.tsx         # 现金/总资产概览卡片
      ReconcilePanel.tsx        # 对账表 + 行内修正/删除
      SettlementImport.tsx      # 上传 + 预览
      SettlementRecords.tsx    # 交割单记录列表
      charts/
        PnlCurveChart.tsx       # 累积已实现盈亏折线
        MonthlyPnlChart.tsx     # 月度盈亏柱状
        SymbolPnlChart.tsx      # 单票盈亏排行横向柱
        FeePieChart.tsx         # 费用饼图
        TradeKlineMarkers.tsx   # 买卖点K线标注
  pages/
    Positions.tsx               # 重构为三 Tab
```

### 5.2 API 封装（`lib/api.ts`）

新增类型：

```ts
export interface PositionLog {
  id?: number
  op_date: string
  op_type: 'buy' | 'sell' | 'clear'
  symbol: string
  name: string
  price: number | null
  volume: number | null
  amount: number | null
  commission: number
  stamp_duty: number
  transfer_fee: number
  note: string
  source: 'manual' | 'settlement' | 'migration'
  settlement_id?: number | null
  settlement_batch_id?: string | null
  created_at?: string
}

export interface SettlementRecord { ... }
export interface ReconItem { ... }
export interface SettlementStats { ... }
```

新增方法：

- `positionLogsList(symbol?)`、`positionLogAdd(body)`、`positionLogDelete(id)`
- `getCash()`、`setCash(v)`
- `settlementImport(file, dryRun)`（FormData）
- `settlementRecords(params)`、`settlementClear()`
- `settlementStats()`
- `reconcileList()`、`reconcileFix(symbol, action)`

`PositionEntry` 结构保持不变（接口无感切换）。

### 5.3 `queryKeys.ts`

新增：

- `QK.positionLogs` / `QK.positionLogs(symbol)`
- `QK.settlementRecords` / `QK.settlementStats`
- `QK.reconcile`
- `QK.positionCash`

变更后统一失效：日志增删、交割单导入/清空、对账修正后，invalidate `positions`、`positionsEnriched`、`positionLogs`、`settlementStats`、`reconcile`。

### 5.4 `pages/Positions.tsx` 三 Tab 布局

使用本项目风格的 Tab 指示器（`rounded-btn` + `border-b` + `accent` 高亮），不引入 indigo。

**Tab 1 — 持仓**（保留并增强）：

- 顶部 `CashOverview`：可用资金、持仓市值、总资产、总浮盈。
- 现有 enriched 表格、迷你 K 线/分时、列自定义、个股预览全部保留。
- "新增持仓"按钮改为打开 `TradeDialog`（op_type='buy'）；行内操作改为"加仓/减仓/清仓"。
- 下方折叠区 `OperationTimeline`（操作历史，可删单条）。
- AI 持仓复盘按钮保留（底层接口不变）。

**Tab 2 — 交割单**：

- `SettlementImport`：拖拽/点击上传 → 展示预览表（错误行红色带行号、过滤统计、新增条数）→ "确认导入"。
- `SettlementRecords`：统计行（总笔数、总买入、总卖出、费用合计、已实现盈亏）+ "图表分析"开关 + 红色"一键清空"（confirm）。
- 图表区（`showCharts` 时渲染）：5 个 ECharts 组件网格布局。

**Tab 3 — 对账**：

- `ReconcilePanel`：调用 `/api/settlement/reconcile`，表格列：标的、交割单持仓(股/成本)、日志持仓(股/成本)、差异(股数/成本)、状态标签、操作（修正/删除）。
- 操作进行中显示 Loader2 并 disabled。

### 5.5 组件设计要点

**TradeDialog.tsx**：

- 基于 `components/Modal.tsx`（自带焦点陷阱/ESC/遮罩关闭）。
- 三种模式：买入（bull 红）、卖出（bear 绿）、清仓（warning 橙），头部渐变。
- 标的选择复用 `StockSearchSelect`（项目已有）。
- 清仓：价格必填、数量默认当前持仓并自动填入、二次确认复选框（参考 TideWatch）。
- 费用字段（佣金/印花税/过户费）可折叠，默认 0；卖出时印花税可按千一预填但允许改。
- 提交后 invalidate 相关 query 并关闭。

**OperationTimeline.tsx**：

- 按日期倒序分组，每条显示：方向图标、代码名称、价格、数量、金额、费用、来源标签（手动/交割单/迁移）、删除按钮。
- 来源为 settlement 的日志标记"来自交割单"，删除需二次确认。

**ReconcilePanel.tsx**：

- diffType 标签配色：matched=bear、mismatch=warning、only_settlement=accent、only_position_log=secondary。
- 修正按钮仅 only_settlement / mismatch 显示；删除按钮所有非 matched 显示。

**SettlementImport.tsx**：

- 拖拽区：`border-dashed border-2 border-border rounded-card hover:border-accent`。
- 解析中 Loader2；预览表格用本项目表格风格；错误行数汇总。
- 两阶段按钮："解析预览"（dry_run）→ "确认导入"（commit）。

**图表组件**：

- 统一使用 `pages/backtest/charts/useECharts.ts`。
- 颜色统一从 `lib/theme.ts` 的 `useChartTheme()` 取，涨跌色用语义 token（bull/bear）。
- 暗色/亮色切换自动重绘。

**TradeKlineMarkers.tsx**：

- 复用 `components/EChartsCandlestick.tsx` 的 markPoint/markLine 能力，或参考 `pages/backtest/components/TradeKlineModal.tsx`。
- 在 K 线上标注该标的的买入（↑bull）/卖出（↓bear）点。

---

## 6. 关键算法与业务规则

### 6.1 FIFO 持仓计算

移植 TideWatch `computePositionsFromLog`：

1. 按 symbol 分组。
2. 组内按 `(op_date, id)` 升序排序。
3. 维护买入队列 `buyQueue: BuyLot[]`：
   - `buy` → push lot
   - `sell` → 从队首逐批 `matched = min(lot.volume, remaining)`，扣减，lot 清空则 shift
   - `clear` → 清空队列
4. 队列剩余 = 当前持仓；`totalShares`、`totalCost`、`avgPrice=totalCost/totalShares`、`buyDate=队首日期`。
5. 价格/成本四舍五入到 4 位小数，金额到 2 位。

卖出超量校验在 `add_log(sell)` 时进行：FIFO 算出当前持仓，不足则 400。

### 6.2 已实现盈亏

卖出配对时同步计算：

```
realized += (sell.price - lot.price) * matched_volume
```

按交割单（或日志）的卖出事件累加，可按日期/月/标的聚合。注意：费用是否计入已实现盈亏需明确口径——**一期采用"成交价差盈亏"，费用单独统计**（即盈亏不扣费用，费用在 stats.fees 单独展示），避免口径混乱。可在文档中注明。

### 6.3 金额与现金流口径

- `amount` 字段：
  - 买入：`price * volume`（成交额，不含费用）
  - 卖出：`price * volume`
- 三项费用独立字段。
- 现金流（free_cash 变动）：
  - 买入：`-(amount + commission + stamp_duty + transfer_fee)`
  - 卖出：`+(amount - commission - stamp_duty - transfer_fee)`
- 交割单 `net_amount` 是券商口径的实际发生额，导入时以其为准校验现金流；若与 `amount ± fees` 不一致，以 `net_amount` 为准并记录。

### 6.4 交割单导入去重（双层）

1. **日期过滤（性能）**：记录库中最大 `trade_date`，早于该日期的记录若已在库则跳过（仅对增量导入有效；全量重导不依赖此层）。
2. **精确去重（准确）**：`(symbol, trade_date, direction, price, volume)` 完全相同视为已存在，跳过。
3. 返回 `imported / skipped`。

### 6.5 代码归一化

所有进入系统的 symbol 统一为 6 位裸代码：

- parser 补零、去后缀
- 与 enriched join 的口径一致（positions 现有使用裸 6 位代码）
- ETF/指数同样 6 位

### 6.6 A 股费用

- 佣金：双向，通常万 2.5 且最低 5 元（以交割单实际为准，不估算）。
- 印花税：卖出单边千分之一。
- 过户费：双向十万分之 1.5。
- 一期**不做费用自动估算**，手动录入时默认 0，用户可填；交割单导入以实际为准。

---

## 7. 分阶段实施计划

每个阶段可独立验证、独立合并。

### 阶段 0 — 地基与迁移（后端）

**文件**：
- 新增 `services/position_log.py`（存储 + FIFO + 迁移 + 现金）
- 改造 `services/positions.py`（list_rows 走 FIFO）
- `app/main.py` startup 调用迁移

**任务**：
1. 定义 schema 与读写函数（含 Lock + 原子写）。
2. 实现 `compute_positions()` FIFO。
3. 实现 `migrate_legacy_positions()`（备份旧文件 + 写 migration 日志，幂等）。
4. 改 `positions.list_rows()` 委托 FIFO，字段映射。
5. 应用启动时执行迁移。

**验证**：
- 启动后 `GET /api/positions` 返回的持仓与迁移前完全一致（股数/成本/顺序）。
- `positions.parquet.bak` 已生成；重复启动不重复迁移。
- enriched / AI 复盘正常工作。

### 阶段 1 — 手动操作日志

**后端文件**：
- 扩展 `api/positions.py`（logs / cash）
- `position_log.py` 增 add_log/delete_log + 现金联动 + 卖出校验

**前端文件**：
- `lib/api.ts`、`lib/queryKeys.ts`
- `components/positions/TradeDialog.tsx`
- `components/positions/OperationTimeline.tsx`
- `components/positions/CashOverview.tsx`
- 改造 `pages/Positions.tsx`（Tab1 接新操作）

**验证**：
- 买入后持仓增加、现金扣减；卖出后持仓减少、现金回笼。
- 多次买入后卖出按 FIFO 配对，成本正确。
- 卖出超过持仓返回 400；买入导致现金为负返回 400。
- 清仓后持仓消失；删除单条日志后持仓重算。
- 旧 upsert/patch 接口若仍被调用，行为可预期（建议前端阶段1内全部切换）。

### 阶段 2 — 交割单导入

**后端文件**：
- 新增 `services/settlement_parser.py`（移植）
- 新增 `services/settlement.py`（存储 + 去重 + stats 占位）
- 新增 `api/settlement.py`（import / records / clear）
- `position_log.sync_from_settlements()`
- `main.py` 注册路由

**前端文件**：
- `components/positions/SettlementImport.tsx`
- `components/positions/SettlementRecords.tsx`
- `pages/Positions.tsx` 加 Tab2

**验证**：
- 同花顺格式 A / 格式 B 各一份样本能正确解析，记录数、费用、代码正确。
- 非交易流水（银证转账等）被过滤并统计。
- 坏行返回行号错误，不中断整批。
- 两阶段：dry_run 不落库，commit 落库并自动同步 position_log。
- 重复导入同一份文件，imported=0、skipped 正确。
- 导入后 Tab1 持仓自动反映（invalidate）。
- 一键清空后交割单与对应 settlement 日志可清理（日志清理策略见备注）。

### 阶段 3 — 对账

**后端文件**：
- 新增 `services/reconcile.py`
- `api/settlement.py` 加 `/reconcile`、`/reconcile/fix`

**前端文件**：
- `components/positions/ReconcilePanel.tsx`
- `pages/Positions.tsx` 加 Tab3

**验证**：
- 构造四种数据：matched / mismatch / only_settlement / only_position_log，能正确识别。
- only_settlement 修正后补 buy 日志，差异消失。
- mismatch 修正后 clear + buy 重建，差异消失。
- 删除操作清除该 symbol 日志后刷新。
- 操作中按钮 Loader2 + disabled，防重复点击。

### 阶段 4 — 图表与统计

**后端文件**：
- `services/settlement.py` 完善 `compute_stats()`（已实现盈亏曲线、月度、单票、费用）
- `api/settlement.py` 加 `/stats`

**前端文件**：
- `components/positions/charts/PnlCurveChart.tsx`
- `MonthlyPnlChart.tsx`
- `SymbolPnlChart.tsx`
- `FeePieChart.tsx`
- `TradeKlineMarkers.tsx`

**验证**：
- 累积盈亏曲线、月度柱状、单票排行、费用饼图数据与交割单明细吻合。
- K 线买卖点标注位置正确。
- 暗色/亮色主题切换图表配色正确。
- "图表分析"开关收起时无残留 DOM。

### 阶段 5 — AI 复盘增强

**后端文件**：
- 改造 `services/position_analyzer.py`（注入交割单统计 + 对账异常）

**验证**：
- AI 报告包含已实现盈亏、费用、月度表现、对账异常提示。
- 流式输出与历史归档正常。

---

## 8. 风险与注意事项

1. **迁移数据一致性（最高优先级）**
   - 迁移前必须备份 `positions.parquet`；迁移用"是否已有 migration 日志"保证幂等。
   - 阶段 0 完成后，人工对比迁移前后持仓列表（股数、成本）。

2. **并发写文件**
   - 所有对 parquet 的"读-改-写"必须在模块级 Lock 内完成，并使用临时文件 + `os.replace` 原子替换，避免请求线程并发导致文件损坏。

3. **旧接口语义变化**
   - 旧 `upsert` 从"覆盖"变为"追加买入"，语义不同。阶段1 必须把前端所有写操作切换到新的 `/logs` 接口，并考虑移除/禁用旧写接口，避免误用。

4. **卖出超量 / 现金为负**
   - 后端强校验，不信任前端。

5. **金额精度**
   - 价格 round 4 位，金额 round 2 位；避免浮点累积误差。费用以交割单实际值为准，不估算。

6. **代码口径**
   - 全链路 6 位裸代码；parser 输出需与本项目 enriched/repo 的 symbol 对齐。ETF 同理。

7. **清空交割单的级联**
   - 一键清空交割单时，是否同步删除由其生成的 `source='settlement'` 日志？建议：清空交割单时一并删除对应 settlement 日志（但保留 manual/migration 日志），避免脏数据。需在 UI 提示。

8. **不引入新依赖**
   - pandas/openpyxl/ECharts 均已在依赖中。不引入 recharts、不引入状态管理库。

9. **性能**
   - 日志量在个人使用场景下（数年成交，数千条）远低于虚拟化阈值，Polars 全量读写无压力。批量插入 500/批。
   - FIFO 在内存中完成，复杂度 O(n)。

10. **回滚方案**
    - 阶段 0 保留 `positions.parquet.bak`；若新系统出问题，可删除 position_log.parquet 并把 bak 改回 positions.parquet，回滚到旧模型（代码需同步回退）。

---

## 9. 文件清单汇总

### 后端新增

- `backend/app/services/position_log.py`
- `backend/app/services/settlement.py`
- `backend/app/services/settlement_parser.py`
- `backend/app/services/reconcile.py`
- `backend/app/api/settlement.py`

### 后端修改

- `backend/app/services/positions.py`（改为 FIFO 适配层）
- `backend/app/api/positions.py`（新增 logs / cash）
- `backend/app/main.py`（注册 settlement 路由 + 启动迁移）
- `backend/app/services/position_analyzer.py`（阶段5提示词增强）

### 前端新增

- `frontend/src/components/positions/TradeDialog.tsx`
- `frontend/src/components/positions/OperationTimeline.tsx`
- `frontend/src/components/positions/CashOverview.tsx`
- `frontend/src/components/positions/ReconcilePanel.tsx`
- `frontend/src/components/positions/SettlementImport.tsx`
- `frontend/src/components/positions/SettlementRecords.tsx`
- `frontend/src/components/positions/charts/PnlCurveChart.tsx`
- `frontend/src/components/positions/charts/MonthlyPnlChart.tsx`
- `frontend/src/components/positions/charts/SymbolPnlChart.tsx`
- `frontend/src/components/positions/charts/FeePieChart.tsx`
- `frontend/src/components/positions/charts/TradeKlineMarkers.tsx`

### 前端修改

- `frontend/src/lib/api.ts`（类型 + API 方法）
- `frontend/src/lib/queryKeys.ts`（新 QueryKey）
- `frontend/src/pages/Positions.tsx`（三 Tab 重构）

---

## 10. 接口契约速查

### 持仓日志

```
GET    /api/positions/logs?symbol=
POST   /api/positions/logs
       body: { op_type, symbol, name?, price, volume?, op_date?,
               commission?, stamp_duty?, transfer_fee?, note? }
       res:  { rows: PositionEntry[], logs: PositionLog[], free_cash }
DELETE /api/positions/logs/{id}

GET    /api/positions/cash
PUT    /api/positions/cash     body: { free_cash }
```

### 交割单

```
POST   /api/settlement/import   (multipart: file, dry_run=true|false)
       res(dry):  { preview, parse_errors, filtered_stats, format,
                    new_count, skipped, latest_db_date }
       res(commit):{ imported, skipped, batch_id }

GET    /api/settlement/records?page=&size=&date_from=&date_to=&symbol=
       res: { rows, total, page, size, summary: {...} }

DELETE /api/settlement/records?batch_id=     # 清空或按批删

GET    /api/settlement/stats
       res: { realized_pnl_curve, monthly, by_symbol,
              fees: {commission, stamp_duty, transfer_fee, total} }

GET    /api/settlement/reconcile
       res: { items: ReconItem[] }

POST   /api/settlement/reconcile/fix
       body: { symbol, action: 'fix'|'delete' }
```

`ReconItem`：

```json
{
  "symbol": "600000",
  "name": "浦发银行",
  "diff_type": "mismatch",
  "settlement_pos": { "shares": 1000, "cost_price": 8.5 },
  "log_pos":        { "shares":  900, "cost_price": 8.6 },
  "shares_delta": -100,
  "cost_delta": 0.1
}
```

---

## 11. 验收标准

- [ ] 旧持仓数据迁移无损，`positions.parquet.bak` 存在。
- [ ] 现有 `/api/positions`、`/enriched`、`/analyze` 行为不破坏（响应结构不变）。
- [ ] 买入/卖出/清仓的 FIFO 持仓、现金联动正确，超量/透支被后端拒绝。
- [ ] 同花顺两种格式交割单可解析、可预览、可导入，重复导入幂等。
- [ ] 对账四种差异类型识别正确，修正/删除可用。
- [ ] 5 个 ECharts 图表数据准确，主题随暗色/亮色切换。
- [ ] AI 持仓复盘报告包含交割单维度信息。
- [ ] 不引入新依赖；前端无 recharts。
- [ ] 所有文件写操作具备锁与原子替换。
