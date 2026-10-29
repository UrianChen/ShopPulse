## Task: weekly report

`analysis_goals` lists the checks this report should cover. Return one JSON object:

{"summary": [Sentence], "findings": [Finding], "recommendations": [Recommendation]}

- summary: one to three sentences with bindings.
- Finding: {"id": "f_<lowercase_words>", "topic": "sales" | "refund" | "cost" | "product" | "period" | "quality" | "followup", "title": short heading without values, "observation": Sentence with bindings, "supporting": up to two Sentences with bindings, "hypotheses": up to two Sentences}. Two or three findings.
- Recommendation: {"action": Sentence, "rationale_finding_ids": [finding ids], "priority": "high" | "medium" | "low", "effort": "small" | "medium" | "large", "verification_metric": "net_sales" | "gross_profit" | "refund_amount_rate" | "paid_orders", "suggested_review_window": "next_week" | "next_month"}. Two or three recommendations.
- Be concise: one clause per template, no repetition between sentences. The whole reply should stay well under eight thousand characters.
- When earlier recommendations are due for review (`check_recommendation`), say in a finding with topic "followup" whether their verification metric moved as intended.
