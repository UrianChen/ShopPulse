# ShopPulse 技术文档

本文对应当前源码版本 `1.0.0`。安装入口见 [README](../README.md)，本文面向开发、部署和维护。

[系统实现](#系统实现) · [本地开发](#本地开发) · [运维与排障](#运维与排障) · [示例数据与复现](#示例数据与复现)

当前交付为桌面 Web、单店铺默认工作空间；窗口宽度至少 1024px。未提供 Windows 一键安装包，前文讨论的安装包只是方案，不属于已实现功能。数据库必须使用 PostgreSQL，不能直接替换成 SQLite。

实现基准：数据库迁移 `0001_initial`、指标引擎 `2.0.0`、指标定义 `1.0`、异常规则 `1.0`、提示词 `1.1`。依赖以 `backend/uv.lock` 和 `frontend/package-lock.json` 为准。

## 系统实现

### 架构与目录

React 19 + TypeScript + Vite + TanStack Query；FastAPI + Pydantic + SQLAlchemy + PostgreSQL 17；Pandas 分组筛选，整数与 Decimal 计算金额。单 Worker 使用 PostgreSQL 持久队列，前端轮询任务，无 Redis / Celery 依赖。

```mermaid
flowchart LR
    UI[React] --> Web[Nginx / Vite]
    Web --> API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> Files[(私有文件存储)]
    Worker[Worker] --> DB
    Worker --> Files
    Worker --> Compute[解析 / 指标 / 导出子进程]
    Worker --> Agent[受限 Agent]
    Agent --> Model[模型服务]
```

| 目录 | 内容 |
| --- | --- |
| `backend/app/api`、`core`、`db` | HTTP、配置、日志、ORM |
| `backend/app/ingestion`、`metrics` | 解析、校验、发布、指标与缓存 |
| `backend/app/providers`、`reports` | 模型适配、凭证、Agent、证据与追问 |
| `backend/app/jobs`、`exports`、`ops` | 队列、导出、运行管理 |
| `backend/migrations`、`tests` | 初始迁移与后续升级、回归测试 |
| `frontend/src/features`、`lib` | 功能页面、API、中英文消息 |
| `samples`、`scripts`、`docs/images` | 示例数据、维护工具、文档截图 |
| `licenses`、`deploy`、`compose*.yaml` | 第三方许可、Nginx、部署配置 |

### 数据与任务

业务记录按服务端确定的 `workspace_id` 限定范围。核心表包括 `uploads`、`imports`、`validation_issues`、`cost_versions/cost_rows`、`dataset_versions/order_lines`、`metric_snapshots/metric_products`、`model_configs`、`reports/agent_runs`、`tool_results/report_messages`、`jobs/worker_pulses`、`exports`、`audit_events`。

表定义见 [models.py](../backend/app/db/models.py)。主要关系和约束如下：

| 表 | 用途与约束 |
| --- | --- |
| `workspaces` | 默认店铺、币种、时区、保留策略及修订号 |
| `uploads` | 源文件哈希、解析状态、私有存储引用 |
| `imports` / `validation_issues` | 字段配置、用户处理决定、源行号与规则码 |
| `cost_versions` / `cost_rows` | 成本版本与 SKU 有效区间；工作空间内 fingerprint 唯一 |
| `dataset_versions` / `order_lines` | 订单版本与标准明细；版本内 line_id 唯一，按版本/时间、版本/SKU 建索引 |
| `metric_snapshots` / `metric_products` | 查询缓存、商品分页；工作空间内 cache_key 唯一，快照内 group_key 唯一 |
| `model_configs` | 加密凭证、授权范围、能力结果；每个工作空间最多一个默认配置 |
| `reports` / `agent_runs` | 报告修订与执行记录；series_id/revision、job_id/attempt 分别唯一 |
| `tool_results` / `report_messages` | 冻结工具证据与追问；报告内 sequence 唯一 |
| `jobs` / `worker_pulses` | 队列、幂等键、租约、心跳；按 status/available_at 索引领取 |
| `exports` / `audit_events` | 导出文件状态、有效期及操作摘要 |

发布冻结字段映射、口径和成本；报告冻结查询、规则、证据及模型配置。新文件不会改写旧报告，新修订保留系列 ID 并递增 revision。编辑使用 `expected_revision` 防覆盖，相同输入指纹复用数据版本。初始迁移 `0001_initial` 创建 19 张业务表，使用固定的建表定义；后续结构变更追加新迁移。

```text
导入：mapping_required → validating → review_required / ready → publishing → published
报告：queued → computing → analyzing → ready / ready_with_warnings / failed
作业：queued → running → succeeded / failed / cancelled
```

Worker 通过行锁领取任务，独立心跳续租；结果提交校验租约及 fencing token，拒绝过期进程写入。默认租约 90 秒、心跳 15 秒、最多领取 3 次。取消会终止受控子进程，已发送的模型请求仍可能计费；无法确认已消费预算时不重放外部请求。

任务类型包括 `parse_upload`、`validate_import`、`publish_dataset`、`build_metrics`、`test_model`、`build_report`、`report_question`、`export_report`。API 在短事务中创建任务，Worker 在独立进程中完成耗时工作，再用有效租约原子提交结果。重试沿用任务 ID，不清零尝试次数；配置或资源已变化时拒绝过期重试。

发布事务同时提交标准化明细、数据版本、草稿状态和任务结果。订单中的成本快照来自发布时匹配的成本版本，后续成本更新不追溯改写它。数据版本不是源文件副本：即使按保留策略删除原文件，标准化数据和已冻结报告仍可保留。

### 导入与指标口径

支持普通 XLSX、UTF-8/BOM 或 GB18030 CSV，不支持 XLS、宏、加密工作簿。标题行 1–100；默认文件 20 MiB、10 万行、100 列、单元格 4096 字符。XLSX 最多 50 表、1000 ZIP 条目、解压合计 200 MiB；解析预算 120 秒 / 768 MiB。

字段与配置定义见 [ingestion/schema.py](../backend/app/ingestion/schema.py)，规则实现见 [normalize.py](../backend/app/ingestion/normalize.py)。

| 字段组 | 标准字段 | 说明 |
| --- | --- | --- |
| 标识 | `order_id`、`order_line_id`、`sku` | 按文本处理，保留前导零；Excel 已损失精度的长编号需回源修正 |
| 时间与数量 | `paid_at`、`quantity`、`restocked_quantity` | 支付归期、购买件数、已回库件数 |
| 实付与退款 | `line_paid_minor`、`line_refund_minor` | 源文件可用元或分，按选定单位转换；标准字段名不决定源列单位 |
| 分摊/派生 | `allocation_weight`、`shipping_minor`、`unit_price`、`discount_minor` | 订单级金额分摊、剔除运费、单价和优惠派生 |
| 状态与展示 | `payment_state`、`currency`、`product_name` | 支付状态映射、币种一致性、展示名称 |
| 成本 | `sku`、`unit_cost`、`currency`、`effective_from`、`effective_to` | 单位成本为主货币单位，同 SKU 成本区间不能重叠 |

`columns` 为“标准字段 → 源列名”，同一源列不可重复映射。别名识别只提供建议，仍需确认以下口径：

| 配置 | 可选值 / 约束 |
| --- | --- |
| `input_money_unit` / `currency_exponent` | `major` 或 `minor`；币种小数位 0–4 |
| `amount_scope` | 明细商品实付、订单商品实付、含运费订单实付、单价派生 |
| `payment_state_mode` | `mapped` 或 `confirmed_all_paid`；状态映射到 paid/unpaid/cancelled_unpaid |
| `refund_mode` / `refund_scope` | `provided`、`unknown`、`confirmed_none`；明细或订单级 |
| `coverage_start` / `coverage_end_exclusive` | 声明完整覆盖的时间区间，不由第一条/最后一条交易推断 |
| `source_as_of` | 退款数据截止时点，独立于支付周期 |
| `cost_effective_from/to` | 无成本时间列时填写静态成本适用范围 |
| `semantics_confirmed` / `coverage_confirmed` | 显式确认统计口径与覆盖范围 |

解析预览最多 10 行，未识别列的内容不回显。质量问题记录源行号；行号 0 表示文件或配置问题。文件位于私有存储，业务 API 不提供服务器物理路径或原文件公开链接。

冲突明细、超额退款、非法数量、混币种、关键字段公式和成本区间重叠阻断发布。重复、缺成本、未知退款等需确认，不静默去重、不计算公式、不把未知值补零。排除行及警告确认须记录原因，重新映射后旧决策失效。

订单级金额按优惠前金额权重使用最大余数法分摊，保持总额守恒；含运费时先扣除明确的运费。退款分摊至商品时标为估算。

| 指标 | 计算规则 |
| --- | --- |
| 商品实付 / 累计退款 | 实付合计 / 本期支付订单截至数据截止时间的退款 |
| 净销售额 | 商品实付 − 累计退款 |
| 支付订单量 / 件数 | 去重订单数 / 购买件数，包含后续全额退款订单 |
| 净客单价 | 净销售额 ÷ 支付订单量 |
| 净商品成本 | 每行成本 ×（购买数 − 已知回库数），转最小货币单位后四舍五入，再求和 |
| 商品毛利 / 毛利率 | 毛利 = 净销售额 − 成本；毛利率 = 毛利 ÷ 正的净销售额 |
| 退款金额占比 | 累计退款 ÷ 商品实付 |
| 成本覆盖率 | 匹配成本的行数占比、实付金额占比 |

毛利未扣佣金、广告、运费、人工和税费；累计退款归原支付周期，不是期间现金退款；各 SKU 的订单数不可直接相加。缺成本时整体毛利不可用，回库未知时成本不回转并标为估算；退款未知时净销售与毛利不可用。分母为零不返回 Infinity，覆盖不足时禁用完整周期比较。

API 数值用十进制字符串传输，例如 `{"value":"55000","unit":"minor_currency","quality":"confirmed","unavailable_reason":null}` 表示 CNY 550 元。质量为 `confirmed`、`estimated` 或 `unavailable`；不可用值为 null 并给出原因。

查询采用 `[start, end_exclusive)`，页面结束日包含当天；按数据版本时区划分自然日和周一，范围 1–366 天、最多 100 个 SKU。指标缓存包含数据/成本版本、口径、查询和引擎版本；计算预算 120 秒 / 1536 MiB。算法或口径变化须更新对应版本，商品分页不改变总体指标。

比较方式为 `previous`、`custom`、`none`：previous 自动计算上一等长周期，custom 必须同时指定比较起止日期。SKU 会排序去重后参与缓存键。完整覆盖且没有交易时金额和订单为零；没有记录且覆盖未知时不能将其解释为零销售。比率采用 Decimal，比较先计算后格式化；上期为零或负基期时提供差额和不可计算增长率的原因。销售贡献是描述性分解，不构成广告或促销效果的因果结论。

### Agent 与模型边界

先运行七个核心工具保存确定性结果，再调用模型分析：

| 工具 | 输出 |
| --- | --- |
| `get_data_quality` | 覆盖、警告、排除摘要 |
| `calculate_metrics` | 本期与比较期指标 |
| `get_sales_trend` | 日/周趋势 |
| `rank_products` | 商品排名，最多 50 项 |
| `compare_periods` | 差额、增长率及不可比较原因 |
| `decompose_sales_change` | 商品、订单量与客单价的描述性贡献 |
| `detect_anomalies` | 规则、阈值、触发项和限制 |

工具只读当前报告上下文，无任意代码、SQL、文件或网络执行权限。证据记录 ID、范围、参数/结果哈希及版本。模型返回严格 JSON，事实绑定证据路径，数字由服务端填入；校验失败最多修复一次，再失败保留确定性结果。原因只作为待验证假设，建议不自动执行。

默认规则：销售变化 ≥20%、退款占比 ≥10%、毛利率下降 ≥5 个百分点、确认的负毛利商品、前三 SKU 集中度 ≥70%、前置 28 个完整日的 MAD 离群值 ≥3.5。规则分别检查样本、覆盖、成本等前提，缺依据时显示不足；常规最低样本为 20 单，集中度至少 5 个活跃 SKU。MAD 不扩大查询范围，历史不足、MAD 为零或周粒度时不计算。

每次报告/追问最多 **8 次工具、4 次模型请求**；累计输入/输出 **12000/8000 UTF-8 字节**，供应商提供 usage 时另限输入/输出 **12000/4000 token**。模型阶段内部截止约 165 秒，父进程约 175 秒；180 秒预算不含排队和独立指标计算。提供方附加消息字段也计入输出预算。

提示词版本 `1.1` 要求摘要、观察、建议三个数组。能力策略依次为 `native_tools`、`restricted_json`、`narrative`；工具与 JSON 均可用时附带 `response_format=json_object`，组合被拒绝时在剩余预算内回退一次。单次 socket 超时 5–60 秒，默认 45 秒；响应上限 1 MiB，仅限流/服务异常允许受预算约束的重试。

输出结构见 [reports/schema.py](../backend/app/reports/schema.py)，校验见 [evidence.py](../backend/app/reports/evidence.py)，调用循环见 [workflow.py](../backend/app/reports/workflow.py)：

| 输出 | 必要内容 |
| --- | --- |
| `summary[]` | 允许的事实模板及 bindings；绑定包含 evidence_id、path、format |
| `findings[]` | 观察 ID、标题、绑定事实、证据引用；原因放入 hypotheses |
| `recommendations[]` | action、关联观察 ID、priority、effort、验证指标、复查周期 |

校验范围包括 schema、报告/数据版本、查询范围、结果哈希、允许模板、事实绑定及建议对应的观察。哈希用于一致性检查，不是数字签名。自由文本不得自带数字、百分比、SKU、HTML 或 URL；模型完整回复和内部推理不会作为报告内容直接保存。提示词要求各数组一个条目以控制长度，schema 的上限不等于每次必须生成该数量。

连接测试最多 6 次合成请求，分别探测基础响应、工具调用及回传、JSON 能力；约 85 秒适配预算、90 秒子进程截止。长度参数由配置明确选择 `none`、`max_tokens` 或 `max_completion_tokens`，不自行猜测服务支持情况。探测通过不代表实际报告一定通过。

模型配置修改会递增 revision 并清除旧能力结果；活动测试、报告、追问期间不可编辑。被报告引用的配置不能删除，但空闲时可以编辑或清除 Key。默认输入投影去除订单 ID、源行号、商品名；允许后才包含商品名，商品列表最多五项、单字符串最多 160 字符，完整证据保留在本地。

追问最长 2000 字符，每份报告同时一条。服务端将问题归类为销售、退款、成本、商品或范围外，只发送固定主题及授权汇总，不发送原问题和完整聊天历史；跨周期问题需新建修订。历史报告发现模型配置 revision 改变时降级追问。

Key 使用 AES-256-GCM、HKDF-SHA256 和 secret 主密钥保护，经 stdin 传入模型子进程。模型默认仅允许公网 HTTPS 443，校验 DNS、固定 IP、验证 TLS、拒绝重定向和环境代理；精确内网来源通过 `MODEL_ALLOWED_ORIGINS` 授权。日志不记录请求正文、凭证或供应商完整回复。

### API 与前端

接口前缀 `/api/v1`。成功返回 `{"data":...,"meta":{"request_id":"..."}}`，错误返回 `{"error":{"code":"...","message":"...","retryable":false},"meta":...}`；204 和下载除外。写请求需准确 Origin；报告、追问、导出使用 8–128 字符 `Idempotency-Key`，同键不同参数返回 409。

| 资源 | 主要路径 |
| --- | --- |
| 健康、店铺、任务 | `/health/live`、`/health/ready`、`/workspace`、`/jobs` |
| 上传与导入 | `/uploads`、`/imports/{id}`，子路径 `/mapping`、`/resolutions`、`/validate`、`/publish`、`/issues` |
| 版本与指标 | `/datasets`、`/cost-versions`、`/metrics/query`、`/metrics/{id}/products` |
| 模型 | `/model-configs`、`/model-configs/{id}/test` |
| 报告 | `/reports/{id}`，子路径 `/runs`、`/evidence/{evidence_id}`、`/messages`、`/exports` |
| 下载、运行管理 | `/exports/{id}/download`、`/operations/status`、`/operations/settings`、`/operations/audit` |
| 任务与清理 | `/operations/jobs/{id}/cancel`、`/retry`；`/operations/cleanup`、`/operations/deletion/{kind}/{id}` |

具体方法与字段见开发 API 的 [Swagger](http://127.0.0.1:8000/docs)。创建报告的 `model_config_id: null` 明确选择无模型；新修订需提供 `parent_id` 和完整查询。

常用请求顺序：

1. `POST /uploads` 使用 multipart 提交 `kind=orders/costs` 和文件；轮询 `GET /uploads/{id}`。
2. `POST /imports` 创建草稿；`PUT /imports/{id}/mapping` 提交 `expected_revision` 和 config。
3. `POST /imports/{id}/validate` 发起校验；必要时 PUT resolutions，再校验。
4. `POST /imports/{id}/publish` 发布；轮询草稿直至 published，取得版本 ID。
5. `POST /metrics/query` 获取或触发指标快照；用返回的快照 ID 轮询指标和商品分页。
6. `POST /reports`、`POST /reports/{id}/messages`、`POST /reports/{id}/exports` 创建异步工作，分别轮询报告、消息或导出列表。

创建报告示例（`POST /api/v1/reports`，另带 Origin 和唯一 Idempotency-Key）：

```json
{
  "title": "经营周报",
  "query": {
    "dataset_id": "替换为已发布订单版本的 UUID",
    "start": "2024-01-01",
    "end_exclusive": "2024-01-08",
    "comparison": "previous",
    "skus": [],
    "granularity": "day"
  },
  "model_config_id": null,
  "parent_id": null,
  "rules": {"min_orders": 20}
}
```

追问请求为 `{"question":"这期退款需要关注什么？"}`，导出请求为 `{"format":"html"}`（也可 markdown/pdf）。清理或关联删除需先 GET 预览，再 POST `{"token":"预览返回值","confirmation":"确认删除"}`；关联或配置变化会使旧 token 失效。HTTP 202 只表示任务已提交，不能当作业务成功；最终以资源状态和错误码为准。

前端 `lib/api.ts` 统一请求，URL 保留看板筛选；`lib/i18n.ts` 与消息字典管理中英文。localStorage 只保存 `shoppulse.language`，切换语言不重挂载页面、不丢表单、不翻译用户数据和历史报告。样式按 `styles.css`、功能 CSS、`visual.css` 分层。

页面通过 TanStack Query 轮询，没有 SSE/WebSocket 推送。React 负责格式化和绘图，不重新计算权威金额；桌面固定侧栏、可见键盘焦点、表单标签及证据对话框属于现有交互约定。新增状态或错误提示需同步中英文消息，避免在模块初始化时冻结翻译。

## 本地开发

需要 Python 3.12、uv、Node.js 24（最低 22.12）及 PostgreSQL 17。可使用 Docker 只启动开发数据库，也可完全原生运行。

以下命令默认 Windows PowerShell。先在根目录初始化配置，已有配置和密钥保留：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python scripts/init_secrets.py
```

使用 Docker 开发数据库时继续执行：

```powershell
docker compose -f compose.dev.yaml up -d --wait
Set-Location backend
uv sync --frozen
uv run playwright install chromium
uv run alembic upgrade head
Set-Location ../frontend
npm ci
```

Linux 安装 Chromium 用 `uv run playwright install --with-deps chromium`。开发数据库为 `127.0.0.1:5433`，与完整 Compose 数据库独立。

分别在三个终端启动：

```powershell
# backend 目录：API
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log --no-proxy-headers
# backend 目录：Worker（另一终端）
uv run python -m app.jobs.worker
# frontend 目录：页面（另一终端）
npm run dev
```

访问 [http://localhost:5173](http://localhost:5173)，Vite 代理 `/api`。完整 Docker Web 不代理 Swagger。虚拟环境可能依赖 `.cache/python`，清理前检查 `backend/.venv/pyvenv.cfg`。

### 无 Docker 运行

1. 安装并启动本机 PostgreSQL 17，确认实际监听端口（一般为 5432）。Python、uv、Node.js 需在 PATH 可用。
2. 完成上述 `.env`、密钥初始化。通过数据库管理工具创建可登录角色 `shoppulse`，将其密码设为本机 `secrets/database_password` 的内容；创建由该角色拥有的 `shoppulse` 数据库。密码文件至少 32 字符，不在文档或命令行中硬编码真实密码。
3. 在 `.env` 设置以下内容；端口按实际安装修改：

```dotenv
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_NAME=shoppulse
DATABASE_USER=shoppulse
DATABASE_PASSWORD_FILE=secrets/database_password
CREDENTIAL_MASTER_KEY_FILE=secrets/credential_master_key
APP_PUBLIC_URL=http://localhost:5173
STORAGE_ROOT=data
```

4. 在 backend 运行 `uv sync --frozen`、`uv run playwright install chromium`、`uv run alembic upgrade head`；在 frontend 运行 `npm ci`。Linux 的 Chromium 安装使用 `--with-deps`。
5. 按前面的三个终端命令启动 API、Worker、前端，访问 `http://localhost:5173`。检查 `http://127.0.0.1:8000/api/v1/health/ready`，并在运行管理确认 Worker 在线。

此方案是原生开发运行方式，停止用各终端的 Ctrl+C；尚无自动安装器或 Windows 服务管理。不要将已有 Docker 数据卷理解为本机 PostgreSQL 的数据，两套实例独立。`scripts/backup.py` 当前仅服务于 Compose 实例；原生部署需在停止应用写入后配套备份数据库、STORAGE_ROOT 和密钥，不能直接套用 Compose 恢复命令。

### 模拟模型与测试

```powershell
# 项目根目录；使用独立测试实例，浏览器测试会写入样例数据
docker compose -f compose.yaml -f compose.mock.yaml up -d --build
```

模型页填 `http://mock-provider:8099/v1`，Key 留空，模型名 `full`。其他模式：`no-tools` / `text-json`、`narrative`、`auth-fail`、`rate-limit`、`bad-number`、`foreign-evidence`、`unsafe-tool`、`repair-once`。

原生模拟需设置 `MODEL_ALLOWED_ORIGINS=["http://127.0.0.1:8099"]` 并重启 API/Worker，在 backend 运行 `uv run python -m app.providers.mock_server`，模型根地址改为 `http://127.0.0.1:8099/v1`。

```powershell
# backend 目录；先启动开发数据库
uv run ruff check .
uv run ruff format --check .
uv run alembic check
uv run pytest -q --cov=app.metrics --cov=app.ingestion.normalize --cov-branch --cov-report=json:coverage.json
uv run python ../scripts/check_coverage.py coverage.json

# frontend 目录
npm test
npm run build
npx playwright install chromium
$env:E2E_BASE_URL = 'http://localhost:8080'
$env:E2E_MODEL_BASE_URL = 'http://mock-provider:8099/v1'
npm run test:e2e
```

后端测试在随机 PostgreSQL schema 中执行真实迁移；指标与标准化行/分支覆盖门槛均为 90%。浏览器测试覆盖导入、看板、模型、报告、导出、运维和双语；不配置 `E2E_MODEL_BASE_URL` 时跳过模型流程。

主要回归范围：金额精度与分摊守恒、CSV/XLSX 等价、字段与资源边界、版本冻结、出站策略、凭证加密、伪造证据、任务租约/取消、关联清理和离线导出。测试角色需要创建/删除 schema 权限，PDF 测试需要 Chromium；浏览器测试关闭 trace，避免采集配置表单里的凭证。

源码交付检查在根目录运行：

```powershell
backend/.venv/Scripts/python.exe scripts/check_versions.py
python scripts/test_release.py
python scripts/check_secrets.py --compose
backend/.venv/Scripts/python.exe scripts/dependency_inventory.py
python scripts/release.py
```

Linux/macOS 将解释器路径改为 `backend/.venv/bin/python`。打包按白名单排除密钥、运行数据、依赖和缓存，生成源码 ZIP、MANIFEST、SHA256SUMS；不自动发布 GitHub 或镜像。

CI 定义在 [.github/workflows/ci.yml](../.github/workflows/ci.yml)，包含后端、前端和 Compose 浏览器三组检查，使用 pip-audit / npm audit 检查依赖。Release 工作流生成源码包。增加数据库字段需新增 Alembic 迁移，变更金额算法、缓存语义、提示词或规则时更新对应版本和独立期望值。

## 运维与排障

### 配置

原生进程读取根目录 `.env`，环境变量优先；容器以 `compose.yaml` 的 environment 为准，额外参数需 Compose override。修改后重启 API/Worker。

| 配置 | 默认值 / 用途 |
| --- | --- |
| `APP_PUBLIC_URL` | 原生 `http://localhost:5173`，允许的写请求 Origin |
| `COMPOSE_PORT` / `COMPOSE_PUBLIC_URL` | `8080` / `http://localhost:8080`，须配套修改 |
| `DATABASE_HOST/PORT/NAME/USER` | 原生 `127.0.0.1:5433`、`shoppulse`；容器 `db:5432` |
| `DATABASE_PASSWORD_FILE` / `CREDENTIAL_MASTER_KEY_FILE` | 数据库密码 / 模型凭证主密钥文件 |
| `CREDENTIAL_KEY_VERSION` / `CREDENTIAL_OLD_KEYS` | 当前密钥版本 / 旧版本到文件路径映射 |
| `MODEL_ALLOWED_ORIGINS` | 精确模型来源白名单，默认空数组 |
| `STORAGE_ROOT` | 原生 `data`；容器 `/data/shoppulse` |
| `MAX_UPLOAD_MIB` / `MAX_IMPORT_ROWS` | `20` / `100000` |
| `JOB_LEASE_SECONDS` / `JOB_HEARTBEAT_SECONDS` | `90` / `15`，心跳小于租约一半 |
| `JOB_POLL_SECONDS` / `JOB_MAX_ATTEMPTS` | `2` / `3` |
| `APP_ENV` / `APP_TIMEZONE` | 原生 development / 初始店铺 Asia/Shanghai |
| `PARSE_TIMEOUT_SECONDS` / `LOG_LEVEL` | `120` / `INFO` |
| `PDF_CHROMIUM_PATH` | 可选，自定义 PDF Chromium 可执行文件位置 |

Compose 按 db → migrate → API/Worker/Web 启动，migrate 以 0 退出正常。默认仅 Web 监听 `127.0.0.1:8080`；远程部署需 HTTPS 和部署层访问控制，Origin 校验不代替权限控制。第二实例需独立目录、密钥、project 名和端口。

配置实现见 [core/config.py](../backend/app/core/config.py)，容器参数见 [compose.yaml](../compose.yaml)。API readiness 同时检查数据库与迁移版本；API/Worker 采用非 root 用户、只读根文件系统和专用可写卷。相对 secret、存储路径相对于仓库根目录，不能依赖调用终端的当前目录。

### 导出、清理与备份

导出共用冻结报告，不重新调用模型。HTML 内嵌 SVG 和中文字体，Markdown ZIP 包含 `evidence.json`，PDF 离线打印为 A4 并阻断网络请求。默认保留 30 天，过期下载返回 410；原文件默认不按天数清理。

删除前先预览关联影响，再用预览 token 确认。删除成本会连带引用的订单版本，删除订单会连带指标、报告、证据和导出；只删除报告保留数据。存在活动任务时不执行破坏性清理。

```powershell
# 根目录；备份目录必须全新
python scripts/backup.py backup --directory backups/my-backup
python scripts/backup.py restore --directory backups/my-backup --project shoppulse-restore-drill
```

备份短暂停止 Web/API/Worker，保存数据库、存储和哈希后恢复服务；**不包含 secrets，也不加密压缩包**，密钥需独立保管。恢复仅允许全新 `shoppulse-restore-` 实例，不覆盖已有容器或卷；演练不发布端口，Worker 保持停止。保留 `.cache/restore-image.json`，用于管理恢复实例：

该文件由恢复工具自动生成。恢复工具会检查备份哈希、归档路径和文件类型、数据摘要及凭证解密；跨机器恢复需要同版本镜像/源码和原密钥。单独保管数据库密码、凭证主密钥以及仍有备份依赖的旧主密钥。

```powershell
docker compose -f compose.yaml -f .cache/restore-image.json -p shoppulse-restore-drill ps
docker compose -f compose.yaml -f .cache/restore-image.json -p shoppulse-restore-drill down
```

密钥轮换：备份后停 API/Worker，新增主密钥文件及版本，通过 `CREDENTIAL_OLD_KEYS` 保留旧文件；在 backend 执行 `uv run python -m app.cli rotate-credentials --dry-run`，确认后去掉 `--dry-run`。Docker 需 override 挂载新旧 secret。勿覆盖旧密钥，旧备份仍可能需要它。

升级前备份并记录镜像/密钥版本，再执行 `docker compose up -d --build`；回退使用匹配的旧镜像和备份，不让旧代码连接不兼容的新 schema。

### 常见问题

| 问题 | 处理 |
| --- | --- |
| 页面打不开 | 检查 Docker 与 `docker compose ps`；日志用 `docker compose logs --tail 50 api worker` |
| 任务一直排队 | 运行管理检查 Worker 心跳；执行 `python scripts/smoke_test.py` |
| 无法发布数据 | 修正阻断、确认警告、保存最新字段及口径后重新校验 |
| CSV/XLSX 解析不对 | 检查编码、分隔符、工作表和标题行 |
| 模型连接通过但报告降级 | 查看错误码，检查超时、输出预算和证据校验；计算结果仍保留 |
| 请求来源不受信任 | 地址须与 public URL 完全一致，localhost 与 127.0.0.1 不等价 |
| 下载过期 | 重新生成导出 |
| 上传超限 | 同步调整 API、Nginx `client_max_body_size`（默认 21 MiB）及界面提示 |

| 模型错误码 | 排查方向 |
| --- | --- |
| `AUTH_FAILED` / `MODEL_NOT_FOUND` | Key、权限、模型 ID、API 根路径 |
| `EGRESS_BLOCKED` / `REDIRECT_BLOCKED` | 精确来源白名单、最终服务地址 |
| `TIMEOUT` / `RATE_LIMITED` | 服务响应时间、限流或配额 |
| `BUDGET_EXCEEDED` | 整次执行的请求、字节、token、工具或时间预算 |
| `EVIDENCE_VALIDATION_FAILED` / `MODEL_OUTPUT_INVALID` | 输出结构、允许模板和证据绑定 |
| `CREDENTIAL_UNAVAILABLE` | secret 主密钥是否匹配保存时版本 |
| `MODEL_RETRY_SUPPRESSED` | 上次外部调用消费量不确定，系统避免重复调用 |

排障使用请求 ID、公开错误码及报告运行记录，勿记录或粘贴 API Key、完整配置环境、模型内部推理。原文件、报告导出及备份的访问权限由部署者控制；密钥泄露后需在服务商处撤销并轮换。

## 许可

项目自有代码与文档采用 [MIT License](../LICENSE)，版权声明为 `Copyright (c) 2026 陈实当 CHEN SHIDANG (UrianChen)`。使用、修改和分发时遵守 LICENSE，保留版权和许可声明；软件按原样提供。

第三方组件、字体及外部演示数据不属于本项目 MIT 授权范围，仍按各自原始许可处理。完整组件声明见 [licenses](../licenses/)，字体许可见 [OFL.txt](../backend/assets/fonts/OFL.txt)。TheLook 镜像数据的再分发授权尚未核实，不能凭代码许可证推定可再分发。

源码包包含根目录 LICENSE、第三方声明和文档。生产镜像仅打包运行所需内容，测试、文档截图和 TheLook 演示数据不进入镜像；内置小样例仍可从数据中心下载。后端 Docker 镜像保留 `/app/LICENSE` 与 `/app/licenses/`，前端镜像保留 `/usr/share/doc/shoppulse/LICENSE` 与 `licenses/`。语言依赖清单不替代容器系统组件的完整许可清单；对外分发镜像或未来的 Windows 安装包时，仍需核对其中数据库、浏览器等运行环境的许可要求。

## 示例数据与复现

### 轻量样例

[成本 CSV](../samples/costs.csv)、[订单 CSV](../samples/orders.csv) 与 [订单 XLSX](../samples/orders.xlsx) 用于快速验证；订单含相同的 6 条明细，XLSX 工作表为“订单明细”。配置 `CNY`、`Asia/Shanghai`、元、明细商品实付、不含运费、全部已支付、已提供明细累计退款；覆盖 `[2026-09-21T00:00:00+08:00, 2026-10-05T00:00:00+08:00)`，截止 `2026-10-07T00:00:00+08:00`。

分析 2026-09-28 至 10-04，比较上一等长周期：

| 指标 | 本期 | 上期 |
| --- | ---: | ---: |
| 商品实付 / 累计退款 | 650 / 100 | 500 / 0 |
| 净销售额 | 550 | 500 |
| 支付订单量 / 净客单价 | 3 / 183.33 | 2 / 250 |
| 商品毛利 / 毛利率 | 230 / 41.82% | 200 / 40.00% |

金额单位 CNY。本期不足 20 单，部分规则显示样本不足属于预期结果。独立期望值保存在 [expected_metrics.json](../samples/expected_metrics.json)，用 `python scripts/generate_demo.py` 重建轻量样例。

### TheLook 来源

数据来自 [Google TheLook eCommerce](https://console.cloud.google.com/marketplace/product/bigquery-public-data/thelook-ecommerce)，这是虚构服装电商的合成数据。本次下载使用 [公开 CSV 镜像的固定版本](https://github.com/marcelFRO/ecommerce-analytics/tree/bb74707d5ab31c35795e017d2dc7f98895efb0af/data/raw)，没有下载客户或访问日志表。原始文件 SHA-256、转换假设和独立核算值记录在 [provenance.json](../samples/thelook/provenance.json)。镜像数据不自动适用本项目代码许可。

### 数据与口径

准备好的文件为 [商品成本](../samples/thelook/costs.csv) 和 [订单明细](../samples/thelook/orders.csv)。共 **9,812 笔订单、14,208 条明细、11,248 个 SKU**，覆盖 2023-11-13 至 2024-01-07。重新下载并转换同一份源数据，可运行 `python scripts/prepare_thelook.py`；脚本先验证源文件哈希，再检查唯一键、关联和订单明细完整性。

**演示口径不等于源数据中的真实支付流水：**

- 纳入 `Complete`、`Shipped`、`Returned`，假设这些订单已支付；不纳入 `Processing`、`Cancelled`。完整覆盖仅指这个筛选集合。
- 以订单创建时间代替支付时间；每条商品明细按一件计，SKU 映射为 `TL-商品 ID`。
- `Returned` 按全额退款演示，其他纳入状态按无退款演示。源数据没有实际退款金额，相关净值与退款占比均依赖这个假设。
- 回库数量保持未知，应用按不回转成本计算并标记毛利为**估算**；商品静态成本用于整个演示周期。
- 使用 UTC、USD；金额四舍五入到美分，单位成本保留六位小数。数据截止时间约定为 2024-01-28，晚于所选退货记录，不能当作官方数据抽取时间。

先导入成本文件，再导入订单文件并关联该成本版本。字段自动识别后，确认以下设置：

| 配置 | TheLook 演示值 |
| --- | --- |
| 时区 / 币种 / 小数位 | `UTC` / `USD` / `2` |
| 金额单位 / 层级 | 主货币单位 / 明细商品实付，不含运费 |
| 支付 / 退款口径 | 确认全部已支付 / 已提供累计商品退款 / 明细退款 |
| 覆盖开始 | `2023-11-13T00:00:00+00:00` |
| 覆盖结束（不含） | `2024-01-08T00:00:00+00:00` |
| 数据截止时间 | `2024-01-28T00:00:00+00:00` |

校验会提示 **2,245 条 `RESTOCK_UNKNOWN` 警告、0 条阻断**。核对上述演示假设，填写接受警告的原因，不排除任何行，再校验并发布。看板和周报选择 **2024-01-01 至 2024-01-07**，对比上一等长周期 **2023-12-25 至 2023-12-31**，分析模型选择已测试的真实服务。

| 本周指标 | 实际计算结果 |
| --- | ---: |
| 退款前商品实付 | USD 140,141.09 |
| 累计退款（演示假设） | USD 23,780.74 |
| 净销售额 | USD 116,360.35 |
| 支付订单量 / 件数 | 1,607 / 2,377 |
| 净客单价 | USD 72.41 |
| 净商品成本（估算） | USD 67,450.26 |
| 商品毛利（估算） | USD 48,910.09 |

### 实际运行截图

**2026-10-11 实测**：真实服务配置 `qwen3.8-max`，超时 60 秒；周报与退款追问通过证据校验，三种导出通过哈希检查，7 项指标独立核算一致。以下为实际页面，金额为 USD。

![TheLook 经营看板](images/thelook-dashboard.png)

#### 数据上传、字段映射与质量检查

数据中心管理成本和订单的独立版本。映射与校验截图使用同一源文件创建的检查草稿；已发布的数据版本用于看板和报告。

![数据中心与 TheLook 数据版本](images/thelook-data.png)

![订单字段自动识别与口径确认](images/thelook-mapping.png)

![质量校验：完整纳入 14208 行，提示回库未知](images/thelook-validation.png)

#### 经营趋势、周期对比与商品表现

每日趋势、周期对比与商品排名，支持日期、SKU 和退款商品筛选。

![每日经营趋势与销售变动贡献](images/thelook-trends.png)

![商品排名与筛选](images/thelook-products.png)

#### 真实模型连接测试

基础连接、工具调用、JSON 模式均通过。模型名为服务配置 ID；API 地址已遮挡，Key 不回显。

![真实模型连接与能力测试](images/thelook-model.png)

#### 智能周报、异常检查与经营建议

报告冻结计算结果与证据，区分规则触发、数据不足和模型提出的待验证假设。

![TheLook 智能周报](images/thelook-report.png)

![异常规则与数据限制](images/thelook-anomalies.png)

![有证据关联的经营观察与行动建议](images/thelook-advice.png)

#### 证据追溯与报告追问

点击计算依据可查看冻结的指标、范围和证据哈希。追问围绕本报告继续分析，不改写历史结果。

![净销售额的计算证据](images/thelook-evidence.png)

![追问本周退款的分析结果](images/thelook-followup.png)

#### 报告导出

同一份报告可生成 HTML、Markdown ZIP 和 PDF，导出包含图表与证据。

![三种报告导出结果](images/thelook-exports.png)

![离线 HTML 报告预览](images/thelook-export-preview.png)

#### 工作台、运行管理与英文界面

工作台和运行管理显示整个本地实例的资源及任务，包含已有历史数据。英文界面切换保留当前筛选条件和业务结果。

![工作台](images/thelook-home.png)

![后台任务与 Worker 运行状态](images/thelook-operations.png)

![英文经营看板](images/thelook-english.png)

