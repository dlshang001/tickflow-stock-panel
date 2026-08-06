# damiao 分支设计方案：大喵观察票池 + 持仓页

> 分支：`damiao`（从 `main` 切出）
> 目标：追踪群主（大喵）每日提及的个股与操作逻辑，并管理个人持仓与实时盈亏。
> 约束：不对现有架构做大变动，全部为「新增文件 + 注册性追加」，完全复用自选模块成熟链路。

---

## 1. 设计原则

- **零侵入**：不改自选（watchlist）前后端、quote_service、repository、StockDataTable、list-columns 等核心。
- **复用既有模式**：`Parquet service → FastAPI router → React Query → StockDataTable`，与自选页同构。
- **薄后端**：Parquet 只存用户录入字段；行情指标、实时价、盈亏全部复用现有内存 enriched 缓存与 SSE 推送，后端不做即时计算。
- **不引入数据库、不引入新依赖**（存储用 Polars/Parquet，与 watchlist 一致）。
- **最小可用**：持仓第一版仅当前持仓清单 + 实时盈亏，不做交易台账、不做现金。

---

## 2. 总体结构

```
data/user_data/
  damiao_pool.parquet     # 大喵观察票池（新增）
  positions.parquet       # 个人持仓（新增）
  watchlist.parquet       # 现有自选，不动
```

后端每个模块一个 service + 一个 api router；前端每个模块一个 page + 一个 columns 配置。

### 文件改动清单

**新增（8 个）**

| 文件 | 作用 |
|---|---|
| `backend/app/services/damiao_pool.py` | 票池 Parquet CRUD + 锚定价填充 |
| `backend/app/services/positions.py` | 持仓 Parquet CRUD |
| `backend/app/api/damiao_pool.py` | `/api/damiao-pool` 路由 |
| `backend/app/api/positions.py` | `/api/positions` 路由 |
| `frontend/src/pages/DamiaoPool.tsx` | 大喵票池页 |
| `frontend/src/pages/Positions.tsx` | 持仓页 |
| `frontend/src/lib/damiao-columns.ts` | 票池列配置 |
| `frontend/src/lib/positions-columns.ts` | 持仓列配置 |

**追加注册（5 个，仅加行、不改原有逻辑）**

| 文件 | 追加内容 |
|---|---|
| `backend/app/main.py` | 2 行 `include_router` |
| `frontend/src/lib/api.ts` | 两组 api 方法 + TS 类型 |
| `frontend/src/lib/queryKeys.ts` | query key + SSE 失效前缀 |
| `frontend/src/router.tsx` | 2 条懒加载路由 |
| `frontend/src/components/Layout.tsx` | 侧边栏 2 个菜单项 |
| `frontend/src/lib/storage.ts` | 2 个列配置 localStorage key |

---

## 3. 数据模型

### 3.1 大喵观察票池 `damiao_pool.parquet`

追踪群主每日预案中提及的个股。**以「一次推荐事件」为一行**，而非以股票为唯一：群主在不同日期重复提及同一只票（如 8/4「同仁堂五日线可看」、8/6「同仁堂可踢」）会产生两条独立记录，各自有锚定价和入池盈亏，便于按日复盘与统计胜率。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | **主键**，新增时生成（如 `dm_<utc时间戳>_<symbol>` 或 uuid），用于编辑/收官/删除 |
| `symbol` | str | 股票/ETF 代码 |
| `added_at` | str | 入池时间（UTC ISO） |
| `source_date` | str | 群主提及日期，如 `2026-08-04`（收盘小结日期），是日期标签页的分组依据 |
| `category` | str | 分类枚举（见 3.3） |
| `strategy` | str | 策略提示原文，如“五日线可低吸”“断板横住再说” |
| `anchor_price` | float \| null | 入池锚定价（自动填充，可手改） |
| `exit_price` | float \| null | 收官价（标记为止盈/止损/已清仓时填写，可空） |
| `note` | str | 备注 |

排序：新增的记录插到最前（同 watchlist 行为）。更新/收官按 `id` 定位，不影响排序。

> **历史数据策略：全部保留，不自动删除。** Parquet 单表几百行无存储压力，而长期数据是复盘群主胜率的依据。UI 通过标签页控制可见范围（最近 5 天快捷标签 + 全部/历史归档）。如确需清理，仅提供手动「清理 N 天前已收官记录」按钮，未收官记录永不自动删除。

#### 锚定价 `anchor_price` 自动填充口径

新增票时若未显式传入 `anchor_price`，后端按以下顺序取价：

1. **实时价**：调用既有 `watchlist.fetch_quotes([symbol], capset)`（带 8s 超时保护），取 `price`；
2. **当日收盘价**：实时价取不到（盘后 / 免费档无实时行情）时，从 repo 的 enriched 缓存取当日 `close`；
3. 都取不到则存 `null`，前端显示“—”，**不阻断入池**，用户可后续手改。

`anchor_price` 始终可在前端编辑（点单元格或编辑对话框修改）。

### 3.2 持仓 `positions.parquet`

仅当前持仓清单。一个 symbol 一行。

| 字段 | 类型 | 说明 |
|---|---|---|
| `symbol` | str | 代码 |
| `shares` | float | 持股数量 |
| `cost_price` | float | 成本价（手动输入，可从票池锚定价快捷带入） |
| `opened_at` | str \| null | 建仓日期（可空） |
| `note` | str | 备注，如“低吸”“尾盘埋伏” |
| `added_at` | str | 记录创建时间（UTC ISO） |

重复录入同一 `symbol` 执行 **upsert（覆盖更新）** 股数/成本/备注，不做分批台账（第一版最简）。

### 3.3 分类枚举 `category`

固定枚举，前端渲染为彩色标签，可按分类筛选。分两组：

**观察类（入池时选择）**

| 值 | 标签 | 对应群主话术举例 |
|---|---|---|
| `new_watch` | 新观察 | “同仁堂、恩华药业，医药低位趋势，五日线可看” |
| `new_open` | 新开仓 | “浪潮信息低吸，尾盘四会富士埋伏” |
| `holding_todo` | 持仓处理 | “药明康德上板留，利欧不上板离场” |
| `old_deng` | 老登票 | 科技对手盘，多看几天 |
| `t_add` | 可踢（做T） | “蓝色光标今日可踢” |

**收官类（标记结果，归档用）**

| 值 | 标签 | 行为 |
|---|---|---|
| `take_profit` | 止盈 | 提示填写 `exit_price`，计算收官收益 |
| `stop_loss` | 止损 | 提示填写 `exit_price`，计算收官收益 |
| `closed` | 已清仓 | 提示填写 `exit_price`（可空） |

> 设计说明：把“已清仓/止盈/止损”作为分类枚举的收官组，而非额外加 `status` 字段，保持单字段、与现有自选同构。标记为收官类时，前端弹出收官价输入框写入 `exit_price`，用于统计这只票从入池到收官的完整涨跌幅。收官类票默认仍显示，但可在筛选里勾选“隐藏已收官”。

枚举集中定义在前后端两处（后端 `damiao_pool.py` 常量、前端 `damiao-columns.ts` 常量），值字符串保持一致。后续增删分类只需改这两处常量。

---

## 4. 后端设计

### 4.1 `services/damiao_pool.py`

仿 `services/watchlist.py`：

- `_path()` → `data/user_data/damiao_pool.parquet`
- `list_rows() -> list[dict]`（按 `added_at` 倒序）
- `add(symbol, source_date, category, strategy, note, anchor_price=None, repo=None, capset=None)`：
  - 生成唯一 `id`（`dm_<utc时间戳>_<symbol>`），插到最前；
  - 同一 `source_date` 下相同 `symbol` **不去重、不覆盖**（保留多次推荐事件）；
  - `anchor_price` 为空时按 3.1 口径自动填充（需要 `repo` 与 capset，由 api 层传入）；
- `update(row_id, **fields)`：按 `id` 修改 category/strategy/note/anchor_price/exit_price/source_date 等；
- `mark_exit(row_id, category, exit_price=None)`：按 `id` 标记为止盈/止损/已清仓；
- `remove(row_id)`、`clear()`

schema 含 `id` 列（Utf8），在首次写入时建立。

### 4.2 `services/positions.py`

- `_path()` → `data/user_data/positions.parquet`
- `list_rows() -> list[dict]`
- `upsert(symbol, shares, cost_price, opened_at=None, note="")`（按 symbol 存在则覆盖更新）
- `remove(symbol)`、`clear()`

### 4.3 `api/damiao_pool.py`（前缀 `/api/damiao-pool`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `""` | 列表（附带名称，复用 `repo.get_name_map`） |
| POST | `""` | 新增一条推荐事件（body 含各字段；自动填充 anchor_price） |
| PATCH | `/{row_id}` | 按 id 修改字段（分类/策略/备注/锚定价/收官价） |
| POST | `/{row_id}/exit` | 按 id 标记收官（body: category, exit_price） |
| DELETE | `/{row_id}` | 按 id 删除单条 |
| DELETE | `""` | 清空 |
| GET | `/enriched` | **核心**：以票池为主表 LEFT JOIN 内存 enriched 缓存 |

`/enriched` 实现照搬 `api/watchlist.py` 的 `watchlist_enriched`（第 161–258 行）：

- 以票池记录为主表（保留 `id`，可能含重复 symbol，JOIN key 仍是 `symbol`）；按 ETF / 股票拆分，分别 LEFT JOIN `repo.get_enriched_latest()` 与 `get_enriched_latest_asset("etf")`；
- 复用 watchlist 的 `_WATCHLIST_COLS` 列清单（close/change_pct/ma5/量比/RSI/MACD/信号等），不重复定义；
- JOIN 名称与 `float_shares`；
- 最后把票池自身字段（`id/category/strategy/source_date/anchor_price/exit_price/note/added_at`）拼回每行；
- 返回 `{ rows, as_of, elapsed_ms }`，契约与自选 enriched 一致。
- **注意**：因为主表可能含同一 symbol 的多条记录（不同 source_date），JOIN 后每条记录都会拿到该 symbol 当前同一份行情，各自独立算入池盈亏——这正是「按推荐事件追踪」所需。

### 4.4 `api/positions.py`（前缀 `/api/positions`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `""` | 列表（附带名称） |
| POST | `""` | upsert 持仓 |
| PATCH | `/{symbol}` | 修改股数/成本/建仓日/备注 |
| DELETE | `/{symbol}` | 删除 |
| DELETE | `""` | 清空 |
| GET | `/enriched` | 以持仓为主表 LEFT JOIN enriched，返回行情 + shares/cost_price |

### 4.5 `main.py` 注册

在 router 注册区（约 329–350 行）追加：

```python
from app.api import damiao_pool, positions
app.include_router(damiao_pool.router)
app.include_router(positions.router)
```

---

## 5. 前端设计

### 5.1 API 层 `lib/api.ts`

追加方法（与 watchlist 方法同构）：

```ts
// 大喵票池
damiaoPoolList / damiaoPoolAdd / damiaoPoolUpdate /
damiaoPoolMarkExit / damiaoPoolRemove / damiaoPoolClear / damiaoPoolEnriched
// 持仓
positionsList / positionsUpsert / positionsUpdate /
positionsRemove / positionsClear / positionsEnriched
```

新增 TS 类型：

```ts
interface DamiaoPoolEntry {
  id: string; symbol: string; name?: string; added_at: string;
  source_date: string; category: DamiaoCategory;
  strategy: string; anchor_price: number | null;
  exit_price: number | null; note: string;
}
interface PositionEntry {
  symbol: string; name?: string; shares: number;
  cost_price: number; opened_at: string | null;
  note: string; added_at: string;
}
```

### 5.2 Query Keys 与实时刷新 `lib/queryKeys.ts`

新增 key：

```ts
damiaoPool:         ['damiao-pool'] as const,
damiaoPoolEnriched: (ext?: string) => ['damiao-pool-enriched', ext] as const,
positions:          ['positions'] as const,
positionsEnriched:  ['positions-enriched'] as const,
```

在 `SSE_INVALIDATE_PREFIXES` 追加 `'damiao-pool'`、`'positions'`。

> 效果：盘中行情 SSE 推送 `quotes_updated` 时，两个新页面的 enriched 查询**自动失效重拉**，无需写额外轮询。注意 key 首字段必须是这两个前缀字符串才能命中前缀失效。

### 5.3 列配置

#### `lib/damiao-columns.ts`

复用 `list-columns` 的 `ColumnConfig` 体系。默认可见列：

- 代码/名称（固定 pinned）
- **分类**（`category`，彩色标签，新增内置列）
- 提及日期（`source_date`）
- 现价、今涨跌幅
- **入池盈亏**（`entry_pct`，前端 computed，**核心列**：从入池锚定价到当前价的涨跌幅，红涨绿跌；anchor 为空显示“—”；已收官则显示收官收益 `exit_pct` 并加收官标记）
- **距MA5**（`dist_ma5`，前端 computed，群主常说“五日线可低吸”）
- **锚定价**（`anchor_price`）
- 量比、RSI14
- **策略**（`strategy`）
- 信号

默认隐藏：收官价、涨跌额、振幅、换手率、成交额、均线组、MACD、KDJ、布林、动量、连板、日K/分时、财务列等（沿用自选内置列，可通过列自定义开启）。

列分组在自选分组基础上新增一组「大喵」：`category / strategy / source_date / anchor_price / entry_pct / dist_ma5 / exit_price / exit_pct`。

#### `lib/positions-columns.ts`

默认可见列：

- 代码/名称（固定 pinned）
- 现价、今日涨跌
- 成本价、持股数
- **市值**（`market_value`，前端 computed）
- **盈亏额**（`pnl_amount`，前端 computed）
- **盈亏比例**（`pnl_pct`，前端 computed，红涨绿跌）
- **仓位占比**（`weight`，前端 computed）
- 建仓日期、备注

### 5.4 计算口径（全部前端，基于 `rt_price ?? close`）

与自选页实时价回退逻辑一致：

| 指标 | 公式 |
|---|---|
| 现价 | `rt_price ?? close` |
| 入池涨跌 | `(现价 - anchor_price) / anchor_price * 100`，anchor 为空显示“—” |
| 距五日线 | `(现价 - ma5) / ma5 * 100` |
| 收官涨跌 | `(exit_price - anchor_price) / anchor_price * 100` |
| 市值 | `现价 * shares` |
| 盈亏额 | `(现价 - cost_price) * shares` |
| 盈亏比例 | `(现价 - cost_price) / cost_price * 100` |
| 仓位占比 | `个股市值 / 持仓总市值 * 100`（持仓内部相对占比，无现金字段） |

红涨绿跌，复用自选页现有的颜色/格式化工具函数。

### 5.5 页面

#### `pages/DamiaoPool.tsx`

- 复用 `components/stock-table/StockDataTable`（`columns / rows / renderCell / renderExtraCol`）。
- 两个 query：`damiaoPoolList` + `damiaoPoolEnriched`（结构同 `Watchlist.tsx` 第 659–669 行），在前端把 list 记录与 enriched 行情按 `symbol` 合并成行（同 symbol 多条记录各自合并一份行情）。

**日期标签页（解决每日预案累积问题，不删除数据）：**

页面顶部是一排按 `source_date` 自动生成的标签，从 enriched/list 数据中聚合 distinct source_date 并倒序：

- `全部`（默认）：所有**未收官**记录，按入池时间倒序；
- 最近 5 个 `source_date` 做成快捷标签（标签上带当日只数角标，如 `08-04 · 6`）；
- `已收官`：所有止盈/止损/已清仓记录（灰显，展示 `exit_pct`）；
- 超过 5 天的更早记录通过「全部」或「已收官」查看，数据始终保留。
- 标签页内可再叠加分类筛选（新观察/新开仓/持仓处理/老登票/可踢）。

**每个标签页的统计条（前端聚合当前标签下的行）：**

- 只数；
- 平均入池盈亏（mean `entry_pct`，未收官用 entry_pct，已收官用 exit_pct）；
- 上涨/下跌只数与**胜率**（盈亏 > 0 的占比，已收官记录按 exit_pct 计入）；
- 最佳/最差个股。
- 统计条随实时行情 SSE 自动刷新。

- 顶部工具条：
  - 添加票：代码输入 + 分类下拉（默认“新观察”）+ 提及日期（默认今天）+ 策略文本 + 备注；
  - 分类筛选、列自定义、手动「清理 N 天前已收官」入口（可选）。
- 行操作（`renderExtraCol`，全部按行 `id`）：
  - **编辑**（改分类/策略/锚定价/备注）；
  - **收官**（弹出止盈/止损/已清仓选择 + 收官价输入，写 `exit_price` 与收官分类）；
  - **转入持仓**（携带 `symbol` 与 `anchor_price` 跳转/打开持仓新增对话框，成本价预填为 anchor_price）；
  - **删除**。
- 实时价：SSE 自动失效 enriched，单元格用 `rt_price ?? close`、`rt_pct ?? change_pct` 显示，入池盈亏列随之实时跳动。
- 列自定义持久化：localStorage key `damiaoColumns`（第一版不接后端偏好，减少改动面）。
- v1 不做按日批量录入/OCR 导入（后续可参考自选页 batch/OCR 模式补充）。

#### `pages/Positions.tsx`

- 同样复用 `StockDataTable` + list/enriched 两个 query。
- 顶部工具条：
  - 添加/编辑持仓：代码 + 持股数 + 成本价 + 建仓日期 + 备注；
  - 成本价输入框旁加按钮 **「带入票池锚定价」**：若该 symbol 在大喵票池且有 `anchor_price`，一键填入成本价（从 `damiaoPoolList` 缓存读取，无需额外请求）；
  - 清空。
- 顶部**汇总条**（前端对 rows 聚合）：
  - 总市值、总成本、总盈亏额、总盈亏比例（红涨绿跌）；
  - 持仓只数。
- 行操作：编辑、删除。
- 列自定义持久化：localStorage key `positionsColumns`。

### 5.6 路由与菜单

`router.tsx`：顶部 lazy import，children 加两条：

```tsx
{ path: 'damiao-pool', element: <DamiaoPool /> }
{ path: 'positions',    element: <Positions /> }
```

`components/Layout.tsx` 的 `nav` 数组（第 72–86 行），在「自选」下方加：

```ts
{ to: '/damiao-pool', label: '大喵票池', icon: Cat },     // lucide-react Cat
{ to: '/positions',    label: '持仓',     icon: Wallet },  // lucide-react Wallet
```

---

## 6. 交互联动（两页打通）

1. **票池 → 持仓**：DamiaoPool 行操作「转入持仓」，把 `symbol` 与 `anchor_price` 带入 Positions 新增对话框，成本价预填锚定价（用户可改）。
2. **持仓 → 票池锚定价**：Positions 新增对话框的「带入票池锚定价」按钮，按 symbol 从票池缓存读取 `anchor_price` 填入成本价。
3. 两页各自独立 Parquet，互不写对方数据；联动只发生在前端对话框预填层面。

---

## 7. 已确认的决策

| 项 | 决策 |
|---|---|
| 票池与自选关系 | 独立新页面、独立 Parquet，与自选完全隔离 |
| 票池主键 | **按推荐事件存**：每条记录一个唯一 `id`，同一只票不同日期可重复出现，各自追踪锚定价与盈亏 |
| 历史数据 | **全部保留、不自动删除**；UI 用日期标签页归档（最近5天快捷标签 + 全部/已收官），可选手动清理已收官 |
| 日期标签页 | 按 `source_date` 自动生成；`全部`(默认,未收官) + 最近5天快捷标签(带只数角标) + `已收官` |
| 标签统计条 | 每个标签显示只数、平均入池盈亏、上涨/下跌只数、胜率、最佳/最差个股，随实时行情刷新 |
| 入池盈亏列 | `entry_pct` 为核心默认列：(现价−anchor_price)/anchor_price，已收官显示 exit_pct，红涨绿跌 |
| 持仓第一版范围 | 仅当前持仓清单 + 实时盈亏 + 汇总，不做台账/现金 |
| 入池锚定价 | 自动取实时价 → 回退当日收盘价 → 都没有则 null，且允许手改 |
| 分类 | 固定枚举，含观察类 5 项 + 收官类 3 项（止盈/止损/已清仓），后续可增删 |
| 收官记录 | 标记收官类时填写 `exit_price`，计算入池到收官的完整涨跌幅 |
| 持仓成本价 | 纯手动输入，提供「带入票池锚定价」快捷填充 |
| 重复持仓录入 | 同 symbol 执行 upsert 覆盖，不累加分批 |
| 批量录入 | v1 不做按日批量录入，后续可参考自选页 batch/OCR 补充 |
| 实时刷新 | 复用 SSE，在 `SSE_INVALIDATE_PREFIXES` 加前缀，无需额外轮询 |
| 列自定义持久化 | 第一版仅 localStorage，不接后端偏好 |

---

## 8. 验证方式

实现完成后逐项验证：

1. 后端启动无报错，`/api/damiao-pool`、`/api/positions` 可访问，Swagger 文档可见。
2. 大喵票池：新增（含自动锚定价）、按 `id` 编辑分类/策略、标记止盈/止损并填收官价、删除、清空均生效；刷新页面数据仍在（Parquet 持久化）。
3. 同一只票不同 `source_date` 可各存一条记录，各自独立显示入池盈亏，不互相覆盖。
4. `/enriched` 返回行情指标；同 symbol 多条记录各自拿到行情；盘中 SSE 推送时现价/涨跌幅/入池盈亏/统计条自动刷新。
5. 日期标签页：全部/最近5天/已收官切换正常，标签只数角标正确，分类筛选在标签内生效；历史数据刷新后仍在。
6. 统计条：只数、平均盈亏、胜率、最佳/最差计算正确，收官记录按 exit_pct 计入胜率。
7. 持仓：新增/编辑/删除；成本价「带入票池锚定价」可用；汇总条市值/盈亏随实时价变动。
8. 票池「转入持仓」能把 symbol + anchor_price 预填到持仓新增对话框。
9. 侧边栏两个菜单项可跳转，路由正常。
10. 现有自选页、策略页等功能不受影响（回归验证）。
11. 前端 `pnpm build`（或 tsc 类型检查）通过；后端无导入错误。
