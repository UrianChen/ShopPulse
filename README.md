# ShopPulse

ShopPulse 是一款开源的电商经营分析应用，将 Excel / CSV 订单与商品成本表转化为可视化看板和智能周报。上传数据后，可确认字段映射、检查缺失与异常，按时间查看销售额、订单量、客单价、毛利及商品表现，并通过周期对比定位经营变化。**数字由代码计算，模型负责分析与解释**：Agent 基于计算结果生成异常说明和经营建议，每份报告保留数据版本与计算证据，支持查看依据、继续追问，以及导出 HTML、Markdown ZIP 和 PDF。应用支持本地部署、中英文界面和自定义兼容 OpenAI API 的模型服务，让商家从整理表格到复盘经营，在一个界面内完成。

`1.0.0` · 桌面 Web（至少 1024px）· 单店铺本地部署 · 中英文界面

[安装](#安装) · [使用](#使用) · [功能展示](#运行示例) · [技术文档](docs/TECHNICAL.md)

![经营看板](docs/images/thelook-dashboard.png)

## 功能

- **导入与校验**：字段映射、缺失与异常检查、成本关联、数据版本。
- **经营看板**：销售、订单、客单价、毛利、商品排名和周期对比。
- **智能周报**：图表、异常说明、经营建议、计算证据与追问。
- **导出与模型**：HTML / Markdown ZIP / PDF；配置兼容 OpenAI Chat Completions 的模型并测试连接。
- **运行管理**：任务状态、Worker、数据保留与清理。

不配置模型也可使用导入、看板和确定性周报；模型失败时保留计算结果。

## 安装

需要 **Python 3.12** 和 **Docker Desktop（Linux containers）或 Docker Engine + Compose v2**。

在项目根目录执行：

```powershell
# Windows PowerShell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python scripts/init_secrets.py
docker compose up -d --build
```

Linux / macOS：

```bash
test -f .env || cp .env.example .env
python3 scripts/init_secrets.py
docker compose up -d --build
```

打开 [http://localhost:8080](http://localhost:8080)。日常启动用 `docker compose up -d`，停止用 `docker compose down`。数据位于 Docker 卷，密钥位于 `secrets/`，请保留；停止时不要加 `--volumes`。

不用 Docker 可按[原生安装步骤](docs/TECHNICAL.md#无-docker-运行)运行。目前没有 Windows 一键安装包。

## 使用

1. **导入成本**：数据中心上传成本表，确认字段、币种和生效时间，校验后发布。
2. **导入订单**：关联成本版本，确认支付、退款、时区和覆盖范围，处理校验问题后发布。
3. **查看看板**：选择数据版本、日期及比较周期，查看指标、趋势和商品表现。
4. **生成周报**：选择模型或确定性摘要；查看证据、追问、导出。更换分析范围时创建新修订。

模型设置中填写 API 根地址（如 `https://provider.example/v1`）、模型 ID 和 API Key，保存后测试连接。Key 仅在后端加密保存，不回显、不写入日志；真实模型调用可能产生费用。

## 运行示例

演示使用 [Google TheLook 合成电商数据](https://console.cloud.google.com/marketplace/product/bigquery-public-data/thelook-ecommerce)：9,812 笔订单、14,208 条明细。文件：[成本](samples/thelook/costs.csv)、[订单](samples/thelook/orders.csv)。详细导入设置和转换口径见[复现步骤](docs/TECHNICAL.md#示例数据与复现)。

2024-01-01 至 01-07：净销售额 **USD 116,360.35**，支付订单 **1,607**，估算毛利 **USD 48,910.09**。演示以创建时间代替支付时间、退货按全额退款、回库数量未知；这些是转换假设，不能视为真实支付流水。

以下均为本地应用实际页面。2026-10-11 使用真实服务配置 `qwen3.8-max` 完成周报与追问，结果通过证据校验；模型名称为所配置服务的 ID。

### 导入表格，确认字段与数据质量

上传后自动建议字段映射，可调整订单编号、SKU、实付、退款等字段。校验会列出问题所在行和处理建议，确认后再发布数据版本。

![订单字段映射](docs/images/thelook-mapping.png)

本例纳入全部 14,208 条明细，0 条阻断；2,245 条警告提示回库数量未知。截图为同一文件的检查草稿，正式分析使用已发布版本。

![数据质量检查](docs/images/thelook-validation.png)

### 查看趋势与商品表现

首页看板汇总销售、订单、客单价与毛利；下方展示每日趋势和销售变化贡献。可按日期、SKU 筛选，并与上一周期或指定周期比较。

![经营趋势与销售变化贡献](docs/images/thelook-trends.png)

商品表可按指标排序，查看销量、退款、毛利和销售变化，帮助定位值得进一步核查的商品。

![商品表现与排名](docs/images/thelook-products.png)

### 连接自己的模型

模型设置支持自定义服务地址、模型名称和 Key。连接测试展示基础响应、工具调用和 JSON 能力，方便判断服务是否兼容。截图中的地址已遮挡。

![真实模型连接测试](docs/images/thelook-model.png)

### 生成有依据的经营周报

报告保存本次数据版本、分析周期和计算结果，集中展示经营概览、图表与异常检查。更新数据或调整周期时创建新修订，原报告保持不变。

![智能周报](docs/images/thelook-report.png)

模型根据计算证据提出观察和行动建议，并将可能原因标为“待验证假设”。建议同时给出验证指标和复查周期，便于后续跟进。

![经营观察与行动建议](docs/images/thelook-advice.png)

### 查看证据，继续追问

点击“计算依据”或“查看证据”，可追溯指标对应的数据版本、时间范围和计算结果。

![指标计算证据](docs/images/thelook-evidence.png)

可围绕当前报告追问销售、退款、成本和商品。本例展示退款分析，包含退款指标、待核查原因与行动建议。

![退款追问与经营建议](docs/images/thelook-followup.png)

### 导出报告

同一份报告支持三种格式：HTML 可离线浏览，Markdown ZIP 包含正文、图表与证据 JSON，PDF 用于分享和打印。本例三种导出均已生成并核对文件哈希。

![HTML、Markdown 与 PDF 导出](docs/images/thelook-exports.png)

### 中英文切换与运行管理

右上角可切换中文或英文，保留当前筛选和未提交表单；商品名称、用户输入及已保存报告保持原文。

![英文经营看板](docs/images/thelook-english.png)

运行管理可查看队列、Worker、存储状态和保留策略。清理前会预览影响范围，确认后执行；截图展示整个本地实例的状态。

![运行管理](docs/images/thelook-operations.png)

## 注意事项

- 毛利未扣广告、佣金、运费、人工和税费；累计退款归原支付周期。
- 缺成本、未知退款或覆盖不足可能使指标不可用；未知回库时毛利标为估算。
- 默认服务仅本机访问，无内建账号权限；远程部署需自行控制访问范围。
- 排队、模型降级、备份恢复及部署配置见[技术文档](docs/TECHNICAL.md#运维与排障)。

## 开发与许可

React + TypeScript、FastAPI、PostgreSQL、Pandas。[技术文档](docs/TECHNICAL.md)包含架构、数据模型、指标口径、Agent、API、开发和测试步骤。

项目自有代码与文档采用 [MIT License](LICENSE)，版权归 **陈实当 CHEN SHIDANG (UrianChen)** 所有。允许使用、修改和商用，分发时保留版权及许可声明。

第三方组件、字体和外部演示数据遵循各自许可，不包含在本项目的 MIT 授权范围内。第三方声明见 [licenses](licenses/)，字体许可见 [OFL.txt](backend/assets/fonts/OFL.txt)；TheLook 镜像数据的再分发授权尚待核实。
