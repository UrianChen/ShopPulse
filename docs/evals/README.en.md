# Real-model evaluation baseline

[简体中文](README.md) | English

The offline CI gate (`python -m app.evals run --gate`) checks only the pipeline and server verdicts: a scripted policy drives the real tools, hypothesis tests and validation without calling a model, so it does not measure model quality. Model quality is measured separately with `--suite live` against real models, and the results are archived here.

## 2026-11-03 · Prompt 3.0 · Grammar 3.0

[Run results](2026-11-03-live/): [Sonnet](2026-11-03-live/live-sonnet.json), [Haiku](2026-11-03-live/live-haiku.json), [per-case comparison](2026-11-03-live/compare.md). The files hold only metrics, report text and step summaries, with no credentials or endpoint addresses. The report text in them is in the language of each case, mostly Chinese.

```bash
python -m app.evals run --suite live --model-config <id> --repeat 3 --max-tokens <cap> --out <file>
```

- 24 cases × 3 runs. Anthropic Messages protocol, each model's default thinking settings, output ceiling 16,000, request timeout 45 seconds (the model config default at the time).
- The Sonnet config used Haiku as its review model; the Haiku config had no review model.
- The two models ran in parallel on an isolated Compose instance. No LLM judge was enabled; text metrics are heuristic scores.
- **Haiku did not finish**: it stopped before its 6-million-token cap with 53 of 72 runs done (2 full repeats and 5 cases of the third), so its spread covers only the 2 full repeats.
- `forbidden_hits` was rescored with the corrected rule: sentences stating which data is missing (such as "当前没有流量和广告数据，需商家自行核对", "no traffic or ad data is available; the merchant needs to check") no longer count. Sonnet's value fell from 7 to 1; the remaining hit is a recommendation to "check the ad schedule". The JSON still holds the old value.

### Summary

| Metric | Sonnet 5.5 | Haiku 5.5 |
| --- | ---: | ---: |
| Pass rate (stdev across repeats) | **93.1%** (±2.4) | 50.9% (±17.7) |
| First pass (no repair needed) | 22.2% | 11.3% |
| Cause recall | **79.8%** (±2.1) | 32.3% |
| Hypothesis validity (test could run) | 80.8% | 68.2% |
| Supported hypotheses cited | 89.0% | 89.5% |
| Ruled-out causes written to the report | 82.5% | 100% |
| Deepened (second refinement round) | 30.5% | 37.8% |
| Drilled down to a SKU | 98.3% | 91.1% |
| Distractor misuse (count) | 5 | 4 |
| Overclaimed causation | 2.0% | 0% |
| Forbidden terms (count, rescored) | 1 | 0 |
| Direction-mismatch hints (count) | 8 | 3 |
| Repairs: patch / full rewrite (per run) | 0.91 / 0.08 | 1.18 / 0.02 |
| Patch success rate | 90.9% | 51.2% |
| Review patch applied | 23.8% | — |
| Follow-up reply type correct | 100% | 0% |
| Deterministic answers (pipeline) | 100% | 100% |
| Requests per run | 4.57 | 3.85 |
| Latency P50 / P90 | 64.6 / 76.5 s | 65.5 / 78.1 s |
| Input / output tokens (per run) | 99.6K / 8.9K | 107.2K / 13.4K |
| Cache hits (share of input) | 37.6% | 34.8% |
| Actual cost | $14.6–16.6 | $0.7–0.8 |

Cost is computed at Anthropic's list prices (Sonnet 5.5: input $2, output $10, cache write $2.50, cache read $0.20 per million tokens; Haiku 5.5: $0.10 / $0.50 / $0.125 / $0.01). Cache writes are not recorded separately in the usage data, so the lower bound prices them as normal input and the upper bound at the cache-write rate. Sonnet's review calls actually went to Haiku but are priced as Sonnet here, so the figure is an overestimate.

### Failure breakdown

| Case | Sonnet | Haiku |
| --- | --- | --- |
| stable_week | 3/3 | 1/3 (budget exhausted ×2) |
| refund_spike | 2/3 (budget exhausted) | 1/3 (budget exhausted, timeout) |
| sales_drop | 3/3 | 0/3 (budget exhausted ×2, timeout) |
| refund_spike_en | **1/3 (budget exhausted ×2)** | 1/2 (budget exhausted) |
| daily_outlier | 2/3 (budget exhausted) | 1/2 (budget exhausted) |
| injection | 2/3 (budget exhausted) | 0/2 (budget exhausted ×2) |
| question_refunds, question_ambiguous | 3/3, 3/3 | 0/2, 0/2 (evidence validation failed) |
| The other 17 cases | all passed | see the [per-case comparison](2026-11-03-live/compare.md) |

### Conclusions

1. **Sonnet is the default recommendation.** It has a 93% pass rate and 80% cause recall, with spread across repeats within 2.5 percentage points, at about $0.20–0.23 per report and a median latency of about 65 seconds. Haiku is about 15 times cheaper, but only half of its reports pass validation and every question-type case failed, so it does not currently suit the main model role. It can continue as the review model.
2. **Nearly all remaining failures are exhausted repair budgets.** First-draft grammar problems are mostly `PATH_NOT_ALLOWED` and `UNBOUND_NUMBER_OR_CLAIM`, and some remain after two patches. The English case `refund_spike_en` failed 2 of 3 runs on Sonnet and is the clearest target for improvement. The next step is to record the rejected paths in the repair step and find out whether they are gaps in the grammar's allow list or something the prompt fails to explain.
3. **Timeouts came from the 45-second default request timeout.** With the output ceiling raised to 16,000 (adaptive thinking counts toward it), long write calls exceed 45 seconds; all 5 Haiku timeouts happened on write calls. 3.0.0 raised the default for new configs to 120 seconds; existing configs need changing by hand.
4. **The direction-consistency check stays a review hint rather than a hard validation for now.** Sonnet's 72 runs produced 8 direction hints, and patches usually fix them. On 44 labelled sentences the check has 81% precision and recall (`python -m app.evals direction`), with false positives concentrated in negated sentences. That precision is not enough to make it a blocking condition.
5. **Cache hits are about 37%.** Planning, writing and patching use different output formats, and every format switch creates a new cache entry. Lowering cost further means unifying the request prefix across these steps.

### TheLook run

The same version generated a weekly report with Sonnet on TheLook data (2024-01-01 to 01-07). The deterministic metrics match the [reproduction document](../TECHNICAL.en.md#sample-data-and-reproduction) (net sales USD 116,360.35, 1,607 orders). The model proposed 4 hypotheses and the server's tests ruled them all "supported". The server proposed 2 more, both ruled out; one was "the change in refund rate comes from per-SKU refund rates", where the test showed it came mainly from product mix (+0.98 vs +0.12 percentage points). The review raised issues, but the patch generated from them did not reduce the issues, so the original draft was kept.

By `scripts/agent_latency.py`, including 1 follow-up there were 9 model calls totalling 98.7 seconds: writing 54%, repairs 14%, planning 13%, tools 11%, review 7%. The server's hypothesis tests took only about 40 milliseconds. Cache hits were 38.5% of input.

This run found and fixed two problems with the "estimated" marker: confirmed values are no longer marked as estimated, and hypothesis sentences no longer repeat "(estimated)" at the end.
