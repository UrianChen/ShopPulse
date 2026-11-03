## Task: weekly report

`analysis_goals` lists the checks this report should cover. When `phase` is present the report follows hypothesis phases; otherwise use tools as offered and reply with the final report.

### Phase "plan" and "refine": hypotheses

Reply with {"hypotheses": [Hypothesis]}, at most `hypothesis_budget.per_wave` (refine: at most three; an empty list goes straight to writing). Do not repeat hypotheses already in `hypotheses`.

Hypothesis: {"id": "h_<lowercase_words>", "statement": Sentence (bindings optional; the same sentence rules apply, so a SKU, number or date in a statement must be a binding, never typed), "test": {"tool": "<tool from tool_catalog>", "arguments": {all argument fields, null when unused}}, "expect": Expectation}.

The server runs the test tool once and evaluates the expectation on its result:

- Operand: {"source": "test" | "<evidence id>", "path": "<path>", "select": null | {"list": "items" | "gainers" | "decliners" | "checks" | "points" | "windows" | "trend", "key": "sku" | "start" | "code" | "date", "value": "<key value>"}}. `source` "test" is the result of this hypothesis's test. With `select`, the element whose key equals the value is used and `path` continues inside it (`metrics.refund_amount`); prefer `select` over list positions when you mean a specific SKU or day.
- Expectation: {"op": ..., "a": Operand, "b": Operand or null, "threshold": "<decimal string>" or null, "k": integer or null}, at least one operand from "test":
  - "gt" / "lt": a is greater / less than b, or than `threshold` (default zero; comparing a level such as sales with zero is rejected as trivial);
  - "abs_ge": |a| ≥ threshold; "abs_gt": |a| > |b| (for example the mix effect outweighs the rate effect);
  - "share_ge": a ÷ b ≥ threshold, threshold in (0, 1], a part of the total b;
  - "rank_le": the element selected by a (`select` with empty path) is among the first k of its list;
  - "same_sign": a and b move in the same direction.
- Values come from the server: the expectation can fail ("refuted") or lack data ("inconclusive", e.g. a small-sample change, an unavailable value).

Good hypotheses are specific and falsifiable: which products, days, refunds, costs or mix effects drive a change; whether a merchant note's promotion or stockout lines up with the products and dates involved; whether a movement continues earlier periods. In "refine", build on supported hypotheses (from a store-level driver to the SKU or day behind it).

### Phase "write": the report

Return one JSON object:

{"summary": [Sentence], "findings": [Finding], "recommendations": [Recommendation], "ruled_out": [RuledOut]}

- summary: one to three sentences with bindings.
- Finding: {"id": "f_<lowercase_words>", "topic": "sales" | "refund" | "cost" | "product" | "period" | "quality" | "followup", "title": short heading without values, "observation": Sentence with bindings, "supporting": up to two Sentences with bindings, "hypotheses": up to two untested hypothesis Sentences, "hypothesis_ids": ids of supported hypotheses this finding rests on (up to three, may be empty)}. Two or three findings.
- `hypothesis_ids` may only name hypotheses whose state is supported. Bind values from their test evidence in the observation or supporting sentences; you may bind a hypothesis state with path `state` of its verdict evidence.
- RuledOut: {"hypothesis_id": a refuted hypothesis, "sentence": Sentence saying in one clause what the data rules out}. Up to three; skip inconclusive hypotheses.
- Recommendation: {"action": Sentence, "rationale_finding_ids": [finding ids], "priority": "high" | "medium" | "low", "effort": "small" | "medium" | "large", "verification_metric": "net_sales" | "gross_profit" | "refund_amount_rate" | "paid_orders", "suggested_review_window": "next_week" | "next_month"}. Two or three recommendations.
- Be concise: one clause per template, no repetition between sentences. The whole reply should stay well under eight thousand characters.
- When earlier recommendations are due for review (`check_recommendation`), say in a finding with topic "followup" whether their verification metric moved as intended. When earlier hypotheses were re-checked (`recheck_hypotheses`), you may say which still hold.
