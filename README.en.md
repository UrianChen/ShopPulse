# ShopPulse

[简体中文](README.md) | English

**Turn Excel / CSV order sheets into a business dashboard and verifiable AI weekly reports.** Code computes the numbers and the model explains them: every amount, ratio, product and date in a report is bound to a computed evidence record, and every cause the model proposes is judged by a test the server runs. The model cannot write a number that was not computed, and it cannot put a cause that failed its test into a conclusion.

Current version `3.0.0` · Desktop web · Single-store local deployment · Chinese and English UI and reports · MIT

[How it works](#how-it-works) · [Quick start](#quick-start) · [Walkthrough](#walkthrough) · [Evaluation](#evaluation) · [Architecture](#architecture) · [Design decisions](#design-decisions) · [Release history](#release-history) · [Technical documentation](docs/TECHNICAL.en.md)

![Business dashboard](docs/images/en/thelook-dashboard.png)

## How it works

Most "AI business analytics" feeds computed results to a model and then trusts the numbers and causes the model writes. ShopPulse takes control back in two places:

**1. Evidence binding: the model writes templates, the server fills in the values.**
Each sentence the model outputs is a template with `{{placeholders}}` plus a set of bindings, and each binding points to an allow-listed path in an evidence record. The server reads the value, checks its type and renders it. Once the placeholders are removed, the remaining free text may not contain any number (including Chinese numerals and words like "翻倍" (doubled) or "一半" (half)), percent signs, SKUs, or certainty claims such as "必然导致" (inevitably causes).

```json
{"template": "The top SKU by net sales is {{sku}}, with net sales of {{sales}}.",
 "bindings": [
   {"name": "sku",   "evidence_id": "ev_…", "path": "items.0.sku", "format": "entity"},
   {"name": "sales", "evidence_id": "ev_…", "path": "items.0.current.metrics.net_sales", "format": "money"}]}
```

**2. The server judges hypotheses: the model asks, the code answers.**
The model does not write "refunds rose because of product A". It proposes a hypothesis instead: a statement, one read-only tool call as the test, and a machine-checkable expectation (greater than / share at least / in the top k / both moving the same way …). The server runs the test and rules it **supported / refuted / inconclusive**. Findings in the final report can cite only supported hypotheses, and "ruled-out causes" can list only refuted ones. The next period's report re-checks the previous hypotheses with the same test conditions.

```mermaid
sequenceDiagram
    participant W as Worker (holds data and evidence)
    participant M as Model subprocess (holds only the key)
    participant LLM as Model provider
    W->>W: Run core tools, freeze evidence (metrics, trends, rankings, decompositions, anomalies, history)
    W->>M: Evidence projection + tool catalog (over a pipe)
    M->>LLM: ① Plan: propose up to 5 hypotheses (test + expectation)
    LLM-->>M: hypotheses[]
    M->>W: Request test runs (read-only tools)
    W-->>M: Verdicts: supported / refuted / inconclusive
    M->>LLM: ② Refine (optional): drill into SKUs / dates from supported hypotheses
    M->>LLM: ③ Write: templates + bindings
    LLM-->>M: Report JSON
    M-->>W: Raw output
    W->>W: Validate bindings, paths, free text → on failure up to 2 targeted patches → deterministic review
    W->>W: Render the text, save the run record and evidence
```

Every value, tool call, round, byte, token and second has a budget. When the model fails, the report falls back to deterministic results (rules, decompositions, verdicts on the server's candidate hypotheses) instead of coming back blank.

## Quick start

Requires **Python 3.12** and **Docker Desktop or Docker Engine + Compose v2**.

```bash
# Linux / macOS
test -f .env || cp .env.example .env
python3 scripts/init_secrets.py
docker compose up -d --build
```

```powershell
# Windows PowerShell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python scripts/init_secrets.py
docker compose up -d --build
```

Open [http://localhost:8080](http://localhost:8080). Data lives in Docker volumes and keys in `secrets/`, so do not add `--volumes` when stopping. To run without Docker, follow the [native install](docs/TECHNICAL.en.md#running-without-docker); for upgrades and backups see [operations](docs/TECHNICAL.en.md#cleanup-backup-and-upgrade).

**Five steps to get going:**

1. **Import costs**: upload a cost sheet, confirm the fields, currency and effective dates, then publish.
2. **Import orders**: link a cost version, confirm payment, refunds, time zone and coverage, resolve validation issues, then publish.
3. **Dashboard**: choose a data version, dates and a comparison period.
4. **Weekly report**: choose a model (or the deterministic summary with no model) and the report language; review evidence and the run history, ask follow-ups, export HTML / Markdown ZIP / PDF.
5. **Automation**: record merchant notes such as promotions and holidays; mark recommendations done or dismissed; create scheduled reports and push them to group chat bots.

**Connecting a model**: in Model settings choose a protocol (OpenAI Chat Completions / OpenAI Responses / Anthropic Messages), enter the API base URL, model ID and key, and test the connection. The key is stored encrypted, never echoed and never logged. You can also enter a cheaper review model on the same service. Import, dashboards, deterministic reports and scheduled reports all work with no model configured.

To see it working first: the repository ships [TheLook synthetic e-commerce data](samples/thelook/) (9,812 orders, 14,208 lines); the import settings are in the [reproduction steps](docs/TECHNICAL.en.md#sample-data-and-reproduction).

## Walkthrough

These are real pages from a local 3.0.0 instance, using TheLook data for 2024-01-01 to 01-07 (net sales USD 116,360.35, 1,607 orders). Report pages use Claude Sonnet 5.5 (review model Claude Haiku 5.5).

**The model proposes hypotheses and the server judges them.** Here the server's candidate "the rise in refund rate comes from per-SKU refund rates" was ruled out: the decomposition shows it came mostly from product mix (+0.98 vs +0.12 percentage points).

![Hypothesis tests](docs/images/en/thelook-hypotheses.png)

**Insights can cite only supported hypotheses.** Amounts, ratios, SKUs and dates are all rendered from evidence. Causes that were not tested are labelled as hypotheses. Recommendations carry a verification metric and a review window, and automatically become action items.

![Insights and recommendations](docs/images/en/thelook-advice.png)

**Every number is traceable.** The evidence drawer shows the data version, time range, tool arguments and result hash; a hypothesis test shows the condition and where both operands came from.

![Hypothesis test evidence](docs/images/en/thelook-evidence.png)

**The process is visible.** Planning, tests, writing, repairs and review are each written to the run history as they happen.

![Run history](docs/images/en/thelook-runs.png)

**Follow-ups are a conversation.** The model can call more tools and cite hypotheses already judged. When a question is unclear it asks back with options; when a question is out of scope it suggests a range and generates a pre-filled new analysis.

![Refund follow-up](docs/images/en/thelook-followup.png)

<details>
<summary><b>More pages</b>: import and validation, dashboard, model connection test, recommendation follow-up, automation, exports, Chinese UI, operations</summary>

<br>

After upload, field mappings are suggested automatically, and you confirm currency, amount level, payment and refund conventions, and coverage.

![Order field mapping](docs/images/en/thelook-mapping.png)

Validation lists problem rows and how to handle them. Here: 14,208 lines, 0 blocking, 2,245 "restocked quantity unknown" warnings.

![Data quality check](docs/images/en/thelook-validation.png)

The dashboard shows daily trends, contributions to sales change and product performance, filterable by date and SKU and comparable with the previous period.

![Trends and contributions to sales change](docs/images/en/thelook-trends.png)

![Product performance and ranking](docs/images/en/thelook-products.png)

The connection test probes the basic response, tool calls, JSON mode, JSON Schema structured output and the review model, and sets the capability strategy from the results.

![Model connection test](docs/images/en/thelook-model.png)

Recommendations from the previous report are reviewed this period against their verification metrics; merchant notes enter the report as analysis context.

![Recommendation follow-up and merchant notes](docs/images/en/thelook-actions.png)

Scheduled reports generate the next period when new data arrives and push it to group chat bots (generic webhook, Slack, Feishu, WeCom, DingTalk).

![Automation](docs/images/en/thelook-automation.png)

The same report exports as offline HTML, Markdown ZIP (with evidence JSON) and A4 PDF.

![HTML, Markdown and PDF exports](docs/images/en/thelook-exports.png)

Switch the interface between Chinese and English at any time, keeping filters and forms; the report language is chosen separately when a report is created.

![Dashboard in the Chinese UI](docs/images/en/thelook-chinese.png)

Operations shows the queue, Worker, storage and retention policy; cleanup previews its impact first.

![Operations](docs/images/en/thelook-operations.png)

![Data center](docs/images/en/thelook-data.png)

</details>

## Evaluation

Evaluation has two layers, because they answer different questions.

**Offline gate (CI, no model calls)**: 24 synthetic cases, each generating 56 days of orders from a fixed seed with labelled business changes injected (refund spike, negative margin, mix shift, single-SKU cost increase, sustained decline, small-sample swings, distractor notes, instruction injection in product names and notes, cross-period rechecks …). A scripted policy drives the real tools, hypothesis tests, loop and validation; **missing a single deterministic answer** (server verdicts, decomposition direction, streak lengths …) fails the gate. It measures the pipeline, not the model.

**Real-model baseline (`--suite live`)**: the same cases run 3 times against each real model, measuring pass rate, recall of injected causes, distractor misuse, overclaimed causation, repairs, latency, tokens and cache hits. First baseline (2026-11-03, details in [docs/evals](docs/evals/README.en.md)):

| | Claude Sonnet 5.5 | Claude Haiku 5.5 |
| --- | ---: | ---: |
| Passes evidence validation | **93.1%** (±2.4) | 50.9% (±17.7) |
| First draft needs no repair | 22.2% | 11.3% |
| Injected-cause recall | **79.8%** (±2.1) | 32.3% |
| Drills down to a specific SKU | 98.3% | 91.1% |
| Overclaimed causation | 2.0% | 0% |
| Requests per report / P50 latency | 4.6 / 65 s | 3.9 / 66 s |
| Cost per report (estimated) | $0.20–0.23 | about 1/15 of Sonnet |

**Known weaknesses, being worked on:** the first-draft pass rate is only 22%, and nearly all remaining failures are exhausted repair budgets (`PATH_NOT_ALLOWED`, `UNBOUND_NUMBER_OR_CLAIM`), which means the evidence grammar still costs models too much to learn. Haiku currently suits only the review-model role. The three stages use different output formats, which holds the prompt cache hit rate at 37%. The direction-consistency check has 81% precision and recall on 44 hand-labelled sentences, so it is a review hint rather than a hard validation.

```bash
cd backend
uv run python -m app.evals run --gate                                   # offline gate
uv run python -m app.evals run --suite live --model-config <id> --repeat 3 --max-tokens 15000000
uv run python -m app.evals compare before.json after.json --out diff.md  # per-case comparison around a prompt change
```

## Architecture

React single-page app → FastAPI (short transactions and job creation only) → PostgreSQL tables as a durable queue → a single Worker doing parsing, metrics, exports and model calls in subprocesses. No Redis / Celery, no vendor SDKs.

| Layer | Choice |
| --- | --- |
| Frontend | React 19 + TypeScript, TanStack Query polling + SSE run traces, hand-drawn SVG charts, request types generated from OpenAPI |
| Backend | FastAPI, Pydantic `extra="forbid"`, SQLAlchemy 2 + Alembic |
| Computation | Pandas only for grouping and filtering; money is integer minor units + Decimal throughout, with largest-remainder allocation to conserve totals |
| Queue | Claimed with `SELECT … FOR UPDATE SKIP LOCKED`, heartbeat lease renewal, fencing tokens reject writes from stale processes |
| Model | One message format across three protocols; strict JSON Schema output preferred; Anthropic prompt-cache breakpoints; budgets: 8 tools / 5 rounds / 8 requests / 2 repairs / 600 s |
| Isolation | The model subprocess holds the key and can reach the network but not the database; tool requests go back to the Worker over an anonymous pipe; the parent re-validates with its own evidence |
| Egress | Hardened in-house HTTP client: DNS validation, pinned IPs, rejects private networks, redirects and environment proxies; exact-origin allow list |
| Credentials | AES-256-GCM + HKDF with key-version rotation; the key reaches the subprocess over stdin, never echoed or logged |
| Tests | 273 pytest cases (real PostgreSQL schemas), 24 Vitest, 24 visual regression screenshots + axe, 7 Playwright end-to-end; 90% coverage threshold for the metrics and normalisation modules |
| Observability | Optional OpenTelemetry (OTLP/HTTP): `agent.run → agent.workflow → gen_ai.chat / tool.*`, with no prompts or data in attributes |

The full data model, metric definitions, tool list, evidence grammar, hypothesis test rules, API and operations are in the [technical documentation](docs/TECHNICAL.en.md).

## Design decisions

- **Why constrain the model this tightly?** In business data, one wrong number is enough for a merchant to stop trusting the whole report. 1.x only let the model repeat whole sentences of server facts, so it could never get specific about products. 2.0 moved to evidence binding: the model composes its own sentences but cannot write an uncomputed value. 3.0 hands "causes" to the code as well. Each step widens what the model can express without giving up control of the facts.
- **Why not LangGraph or an Agents SDK?** The loop itself is just plan → test → write, which is cheaper to write than to adapt to a framework's abstractions. The real complexity is in evidence validation, budgets, subprocess isolation and the differences between three protocols, none of which those frameworks handle. The cost is maintaining the protocol adapters ourselves.
- **Why a subprocess rather than a thread?** It physically separates "the process that can reach the network" from "the process that can read the database": the key lives only in the former, the data only in the latter, and tool calls pass through a pipe between them. It also makes hard kills on memory and timeout straightforward.
- **Why PostgreSQL as the queue?** A single-store local deployment has few jobs, so one less Redis matters more than extra throughput. Leases plus fencing tokens already cover crash recovery and duplicate claims.
- **Why separate offline and online evaluation?** The offline gate ensures code changes do not break the pipeline, runs in seconds and must pass in CI. Model quality is random and costs money, so it runs separately, three times to show the spread, and goes into a baseline. Mixing the two makes CI flaky or hides model regressions.

## Release history

**3.0.0 · 2026-11-03** — The server judges hypotheses and re-checks them across periods; gross margin and refund rate decompose into mix and rate, average order value into unit price and units per order; up to 8 history windows support "N periods in a row"; computed bindings express multiples, shares and differences; small-sample SKU changes cannot stand alone in a sentence; validation failures send back patches for only the failing sentences; deterministic review + optional review model; Anthropic prompt caching; frontend engineering (ESLint / Prettier, OpenAPI types, CSS Modules, lazy loading, visual regression); evaluation cases 10 → 24, deterministic answers gated in CI, first real-model baseline. Migration `0003_agent_v3`.

**2.0.0 · 2026-10-28** — Evidence-binding grammar replaces whole-sentence repetition, so the model composes its own sentences and drills into SKUs / dates / refunds / costs; multi-round tool loop and targeted repair; model subprocess isolation and a pipe tool protocol; follow-ups become a conversation (asking back, suggesting a range); action items, merchant notes, scheduled reports and five kinds of chat bot push; three protocols; OpenTelemetry; ten synthetic evaluation cases in CI. Migration `0002_agent_v2`.

**1.0.0 · 2026-10-11** — Import and field mapping, quality validation and frozen data versions, dashboard and period comparison, deterministic anomaly rules, evidence-based reports and follow-ups, three export formats, OpenAI-compatible APIs, Chinese and English UI, Docker Compose deployment.

Back up before upgrading (`python scripts/backup.py backup --directory backups/<name>`). Upgrading from 1.x requires confirming the new consent scope on the model page. After upgrading from 2.x, re-test the model connection to enable the review model, and raise any request timeout still at 45 seconds.

## Notes

- Gross profit excludes advertising, commissions, shipping, labour and tax. Cumulative refunds are attributed to the original payment period, so they are not cash refunds within the period.
- Missing costs, unknown refunds or insufficient coverage mark the affected metrics as unavailable; unknown restocking marks gross profit as estimated. Nothing is filled with zero or guessed.
- "Supported" means only that the data is consistent with the hypothesis, not that causation is proven. Recommendations are never executed automatically.
- Local access only by default, with no built-in accounts. For remote deployment, add HTTPS and access control yourself.
- Real model calls cost money; a model with reasoning often takes over a minute to write a report.

## License

The project's own code and documentation are under the [MIT License](LICENSE), copyright **陈实当 CHEN SHIDANG (UrianChen)**. Third-party components, fonts and external demo data follow their own licenses; see [licenses](licenses/) and [OFL.txt](backend/assets/fonts/OFL.txt). Redistribution rights for the TheLook mirror data are still to be verified.
