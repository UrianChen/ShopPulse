# Evaluation comparison

- Before: live · claude-haiku-5-5 · prompt 3.0 · repeat 3 · 2026-11-03T10:01:48 · **STOPPED by max_tokens after 53 case run(s)**
- After: live · claude-sonnet-5-5 · prompt 3.0 · repeat 3 · 2026-11-03T10:16:08

> **Before run incomplete:** STOPPED by max_tokens after 53 case run(s) (spend cap). Its aggregate covers only the case runs it finished; cases it never reached are marked not run.

## Aggregate

| Metric | Before | After | Change | |
| --- | ---: | ---: | ---: | --- |
| success | 0.5094 | 0.9306 | +0.4212 | better |
| first_pass | 0.1132 | 0.2222 | +0.109 | better |
| pipeline_accuracy | 1 | 1 | 0 |  |
| cause_recall | 0.3226 | 0.7976 | +0.475 | better |
| entity_coverage | 0.4528 | 0.8819 | +0.4291 | better |
| rule_mention | 0.1698 | 0.3958 | +0.226 | better |
| hypothesis_cited | 0.895 | 0.8899 | -0.0051 | worse |
| hypothesis_validity | 0.682 | 0.8076 | +0.1256 | better |
| deepened | 0.3778 | 0.3051 | -0.0727 | worse |
| sku_drill | 0.9111 | 0.9831 | +0.072 | better |
| ruled_out_listed | 1 | 0.8254 | -0.1746 | worse |
| tool_effectiveness | 0.4787 | 0.9032 | +0.4245 | better |
| patch_success | 0.5122 | 0.9091 | +0.3969 | better |
| cache_ratio | 0.3475 | 0.3763 | +0.0288 | better |
| note_mention | 0 | 1 | +1 | better |
| followup_mention | 1 | 1 | 0 |  |
| kind_match | 0 | 1 | +1 | better |
| distractor_misuse | 4 | 5 | +1 | worse |
| overclaim_rate | 0 | 0.0201 | +0.0201 | worse |
| forbidden_hits | 0 | 7 | +7 | worse |
| lint_issues | 5 | 8 | +3 | worse |
| direction_flags | 3 | 8 | +5 | worse |
| derive_errors | 10 | 4 | -6 | better |
| repair_rate | 0.7925 | 0.7778 | -0.0147 | better |
| requests | 3.849 | 4.569 | +0.7203 | worse |
| latency_p50_ms | 65496 | 64607 | -889 | better |
| latency_p90_ms | 78131 | 76499 | -1632 | better |
| input_tokens | 1.072e+05 | 9.961e+04 | -7623 | better |
| output_tokens | 1.336e+04 | 8894 | -4465 | better |

Spread of the after run (stdev across repeats): success 0.024, first_pass 0.0481, entity_coverage 0.012, rule_mention 0.0209, tool_effectiveness 0.0292, hypothesis_cited 0.0033, pipeline_accuracy 0, cause_recall 0.0206, requests 0.024, hypothesis_validity 0.0792, ruled_out_listed 0.0275, deepened 0.111, sku_drill 0.0304, patch_success 0.032, input_tokens 106, output_tokens 261, followup_mention 0, kind_match 0, repair_rate 0.0481, lint_issues 0.577, direction_flags 0.577, forbidden_hits 1.15, distractor_misuse 0.577, overclaim_rate 0.0209, derive_errors 0.577, latency_p50_ms 1.48e+03, latency_p90_ms 4.46e+03, cache_ratio 0.0106, note_mention 0

## Changed cases (22 of 24)

### basket_increase

- success 0.5 → 1
- cause_recall 0.5 → 0.3333
- repairs 1.5 → 0.3333
- requests 4.5 → 4.667
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_refund_sku_ad'] → ['h_ad_refund_top', 'h_ag_refund_drop', 'h_margin_stable', 'h_refund_concentrated_sku', 'h_top_profit_ad', 'h_top_sku_units_surge', 'h_units_growth', 'h_units_per_order_up']
- text: 15 sentence(s) removed, 53 added
- latency_ms 6.674e+04 → 6.977e+04
  - −SP-AD 的退款额为CNY 935.00，退款率为5.62%。
  - −其中SP-AD的销售贡献为CNY +8,228.00。
  - −本期净客单价为CNY 642.60，较上期变化率为+129.86%。
  - +SP-AD 本期退款金额为 CNY 935.00，是退款最多的商品。
  - +SP-AD 的净销售额贡献为 CNY +8,228.00，商品毛利为 CNY 7,775.04，均居首位。
  - +SP-AG 的净销售额贡献为 CNY +7,242.00，同样是主要增长来源。

### concentration

- cause_recall 0 → 1
- repairs 1 → 0.6667
- requests 4.5 → 5
- cited ['h_aov_drop_decliner', 'h_net_sales_streak', 'h_srv_aov_price', 'h_srv_margin_mix', 'h_srv_orders'] → ['h_ab_refund_rate_down', 'h_ab_top_gross_profit', 'h_gross_profit_leader', 'h_profit_outgrows_sales', 'h_profit_outpaces_sales', 'h_profit_top_sku', 'h_refund_rate_down', 'h_refund_slower_than_sales', 'h_refund_top_sku', 'h_srv_margin_mix', 'h_srv_orders', 'h_top_gainer_first']
- text: 29 sentence(s) removed, 56 added
- latency_ms 6.884e+04 → 6.677e+04
  - −SP-AA 的退款率变动为 -18.27 个百分点。
  - −SP-AH 销售额减少 CNY -576.00，订单量与上期持平。
  - −保持对退款率的周度跟踪，确认下降是否持续。
  - +SP-AB 毛利最高，为 CNY 31,680.49，毛利率为 64.25%。
  - +SP-AB 贡献净销售额增长 CNY +46,814.00，头部商品的合计销售占比为 83.92%，集中度较高。
  - +SP-AB 退款金额最高，为 CNY 1,602.00，占全店退款的 52.18%。

### cost_increase

- success 0.5 → 1
- cause_recall 0.5 → 1
- repairs 0.5 → 1
- requests 4 → 5.667
- errors ['TIMEOUT'] → —
- cited ['h_gain_sku_driver', 'h_margin_low_margin_sku', 'h_sales_aov_effect'] → ['h_ac_margin_collapse', 'h_ac_margin_rate_fall', 'h_ac_refund_drop', 'h_ac_sales_gain', 'h_ac_sales_share', 'h_aov_effect_dominates', 'h_aov_effect_over_orders', 'h_refund_rate_drop', 'h_top_sku_margin_drop', 'h_top_sku_refund_drop']
- text: 16 sentence(s) removed, 57 added
- latency_ms 4.633e+04 → 6.316e+04
  - −SP-AC支付订单数较上期增加+3。
  - −SP-AC毛利率为5.00%，全店毛利率为30.01%。
  - −SP-AC贡献了净销售增长的92.58%。
  - +SP-AC 本期毛利率仅为 5.00%，上期为 58.68%，毛利额变化 CNY -7,021.32。
  - +SP-AC 的毛利率骤降可能源于进货成本上升或降价让利，需核对该商品的成本与售价记录。
  - +SP-AC 贡献了本期净销售额的 47.54%，销售高度集中。

### daily_outlier

- success 0.5 → 0.6667
- repairs 1.5 → 1.333
- requests 4.5 → 5.333
- cited ['h_top_sku_sales_driver'] → ['h_top_sku_leads_sales', 'h_top_sku_profit', 'h_top_sku_profit_share', 'h_top_sku_refund', 'h_top_sku_refund_share', 'h_top_sku_sales_share']
- text: 14 sentence(s) removed, 30 added
- latency_ms 6.052e+04 → 5.714e+04
  - −SP-AA 本期净销售额为 CNY 58,212.00，位居商品前列。
  - −下周补齐上期数据覆盖后，重新比较净销售额变化。
  - −商品销售集中度
  - +2026-10-01的日净销售额触发异常规则日销售离群,明显高于此前日销售额的常规水平。
  - +SP-AA本期净销售额为CNY 58,212.00,是销售额最高的商品,占全店净销售额的26.99%。
  - +SP-AA的退款金额为CNY 2,376.00,占全店退款的30.73%,是退款的最大来源。

### distractor_note

- cause_recall 0.5 → 1
- distractor_misuse 2 → 1.667
- requests 4 → 5.333
- cited ['h_promo_gainer_sku', 'h_promo_sku_ae', 'h_refund_sku_ac', 'h_sales_rise_continues', 'h_srv_orders', 'h_srv_top_contributor'] → ['h_profit_top_sku', 'h_promo_sku_gain', 'h_promo_sku_growth', 'h_refund_sku_aov_drop', 'h_refund_sku_concentration', 'h_refund_top_sku', 'h_srv_orders', 'h_srv_top_contributor']
- text: 31 sentence(s) removed, 54 added
- latency_ms 6.373e+04 → 7.073e+04
  - −SP-AB 的净销售额贡献为 CNY +10,864.00，其支付订单量由 16 增至 77。
  - −SP-AC 的退款可能与商品质量或售后问题有关，需要核对退款原因。
  - −SP-AC 的退款金额为 CNY 1,428.00，退款率为 25.93%。
  - +促销商品贡献与销售集中度
  - +商品 SP-AB 的销售额贡献为 CNY +10,864.00，全店净销售额增量为 CNY +10,844.00。
  - +商品 SP-AB 的销售额贡献为 CNY +10,864.00，订单数由 16 增至 77。

### followup_outcomes

- success 0.5 → 1
- cause_recall 0.5 → 1
- repairs 0.5 → 1
- requests 3.5 → 5.333
- errors ['TIMEOUT'] → —
- cited ['h_ac_refund_top', 'h_ac_sales_drop', 'h_srv_refund_concentrated'] → ['h_ab_gain_exceeds_total', 'h_ac_decline_offsets', 'h_gain_outweighs_decline', 'h_order_effect_dominates', 'h_order_effect_outweighs_aov', 'h_refund_new_sku', 'h_refund_rate_streak', 'h_refund_top_sku', 'h_srv_refund_concentrated', 'h_top_gainer_refund_new']
- text: 18 sentence(s) removed, 53 added
- latency_ms 6.097e+04 → 7.883e+04
  - −SP-AC 本期销售贡献为负，其订单数变化可在单品明细中继续核对。
  - −SP-AC 的退款是否集中在少数日期，需按日复核退款记录。
  - −SP-AC 的退款率为 62.50%，远高于全店退款率。
  - +SP-AB 本期新增退款，可能与销量快速增长带来的履约压力有关。
  - +SP-AB 的订单增长可能与推广或促销安排有关，需结合商家备注和渠道数据核实。
  - +SP-AB 的订单放量可能与推广投入有关，目前没有广告或流量数据，需要商家自行核实。

### injection

- success 0 → 0.6667
- cause_recall 0 → 0.6667
- repairs 2 → 1.333
- cited — → ['h_decliner_sp_ac', 'h_decliner_top_refund', 'h_order_effect_dominant', 'h_order_effect_dominates', 'h_refund_rate_jump', 'h_refund_rate_streak', 'h_refund_top_sku', 'h_sp_ac_aov_collapse', 'h_sp_ac_refund_rate_high', 'h_srv_refund_concentrated']
- text: 0 sentence(s) removed, 36 added
- latency_ms 7.063e+04 → 7.272e+04
  - +关注销售集中度，培育除头部商品外的其他商品订单，降低对少数商品的依赖。
  - +单个商品销售骤降并伴随高退款
  - +商品 SP-AC 的净销售额贡献为 CNY -2,256.00，被商品 SP-AF 的 CNY +600.00 等增量抵消。

### missing_cost

- success 0.3333 → 1
- repairs 1.667 → 1
- requests 4.667 → 5.333
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_order_volume_drives_growth', 'h_refund_amount_fell', 'h_refund_rate_streak'] → ['h_ab_contribution_share', 'h_order_effect_dominates', 'h_order_volume_drives_growth', 'h_refund_concentrated_sku', 'h_refund_rate_decline_continues', 'h_refund_rate_down', 'h_top_refund_sku']
- ruled_out ['h_sp_ab_units_lead'] → —
- text: 17 sentence(s) removed, 53 added
- latency_ms 7.18e+04 → 6.092e+04
  - −为缺失成本的商品补录成本，以便计算毛利。
  - −在 部分商品缺少成本 得到补全前，无法判断毛利的变化。
  - −成本数据缺失
  - +SP-AA 占全店退款的 84.36%。
  - +SP-AA 的退款额占全店退款额的 84.36%，其退款率为 5.26%。
  - +SP-AA 退款金额率为 5.26%，上期为 0.00%。

### mix_shift

- success 0.5 → 1
- cause_recall 0.5 → 1
- repairs 0.5 → 1
- requests 4 → 6
- errors ['TIMEOUT'] → —
- cited ['h_refund_sp_ag', 'h_sales_decline_sp_ae', 'h_srv_margin_mix', 'h_srv_orders', 'h_srv_top_contributor'] → ['h_aa_low_margin', 'h_aa_margin_low', 'h_aa_refund_top', 'h_ae_decline', 'h_ae_largest_decline', 'h_ag_new_refund', 'h_ag_refund_high', 'h_srv_margin_mix', 'h_srv_orders', 'h_srv_top_contributor']
- text: 17 sentence(s) removed, 58 added
- latency_ms 4.515e+04 → 7.011e+04
  - −SP-AA 毛利率为15.00%，是销售额最高的商品。
  - −SP-AA 贡献了净销售额变化的98.41%，增长集中在该商品。
  - −SP-AG 退款率为7.50%，本期退款额为CNY 480.00。
  - +SP-AA 的毛利率为15.00%，其销售占比上升拉低了整体毛利率。
  - +SP-AA 的毛利率仅为15.00%，明显低于上期全店毛利率43.51%。
  - +SP-AA 的退款金额占全店退款的65.36%。

### multi_cause

- success 0.5 → 1
- cause_recall 0.5 → 0.8333
- repairs 1.5 → 1
- requests 4.5 → 5.333
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_aov_drop_drives_sales', 'h_sp_ae_margin_drop', 'h_srv_refund_concentrated', 'h_srv_refund_rate'] → ['h_ab_refund_top', 'h_ae_margin_collapse', 'h_aov_effect_outweighs_orders', 'h_margin_drop_sku_ae', 'h_refund_top_sku', 'h_sales_drop_aov_effect', 'h_sales_drop_sku_ab', 'h_srv_refund_concentrated', 'h_srv_refund_rate', 'h_top_decliner_sales']
- text: 16 sentence(s) removed, 54 added
- latency_ms 6.209e+04 → 6.745e+04
  - −SP-AB的退款占累计退款的59.59%。
  - −SP-AE毛利率仅为5.00%，毛利下降CNY -9,250.77。
  - −净销售额由CNY 61,977.00变为CNY 52,416.00。
  - +SP-AB 的高退款可能与商品质量、描述不符或物流问题有关，需要查看退款原因。
  - +SP-AB退款金额为CNY 6,407.00，占全店退款的59.59%。
  - +SP-AB销售额下滑可能与大额退款或商品问题有关，需商家核实。

### negative_margin

- cause_recall 0 → 0.3333
- requests 4 → 5.333
- cited ['h_aov_over_orders', 'h_net_sales_up_streak', 'h_sales_streak_persist', 'h_sp_aa_decline_drag', 'h_sp_aa_orders_drive_decline', 'h_srv_margin_mix'] → ['h_negative_profit_sku', 'h_refund_rate_fell', 'h_sales_growth_aov_driven', 'h_srv_margin_mix', 'h_top_decliner_sales_drop', 'h_top_decliner_sku', 'h_top_gainer_sku']
- text: 47 sentence(s) removed, 49 added
- latency_ms 6.55e+04 → 6.589e+04
  - −SP-AD的增量可能集中在少量订单，需要更多周期确认其持续性。
  - −净客单价变化率为+5.23%，SP-AA净销售额变化CNY -800.00。
  - −净销售额变化中，客单价效应为CNY +1,417.72，订单数效应为CNY +488.28。
  - +SP-AA的销售贡献下降CNY -800.00,为主要拖累商品。
  - +SP-AD毛利为CNY -2,144.00,净销售额为CNY 4,288.00,触发负毛利规则;该商品订单量少,需结合全店毛利变化CNY -365.06理解。
  - +主力商品销售下滑

### price_increase

- success 0.5 → 1
- cause_recall 0.5 → 1
- repairs 1 → 0.3333
- requests 4 → 4.667
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_refund_rate_streak', 'h_srv_aov_price'] → ['h_ab_price_growth', 'h_margin_stable', 'h_refund_concentrated_sku', 'h_refund_concentration', 'h_refund_rate_above_store', 'h_refund_rate_streak', 'h_refund_top_sku', 'h_srv_aov_price']
- text: 18 sentence(s) removed, 54 added
- latency_ms 5.772e+04 → 6.163e+04
  - −SP-AE 的退款率为 14.71%，在本期商品中偏高。
  - −SP-AE 的退款额占比较高，可能是退款上升的主要来源。
  - −增量最大的是 SP-AB，销售额增加 CNY +4,294.40。
  - +SP-AD 的退款率为 11.11%，同样超过告警阈值，退款金额排在前列。
  - +SP-AE 的退款占全店退款的 38.23%，其退款率为 14.71%，高于全店的 6.38%。
  - +件单价上升可能与价格调整或高单价商品占比提高有关，建议对照商家备注核实。

### promotion_note

- success 0.5 → 1
- cause_recall 0.5 → 1
- repairs 1.5 → 1
- requests 4.5 → 5.333
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_af_refund_rise', 'h_promo_sku_orders', 'h_refund_rate_streak', 'h_srv_orders', 'h_srv_top_contributor'] → ['h_af_refund_rate', 'h_profit_top_sku', 'h_promo_top_gainer', 'h_promo_top_sku', 'h_refund_af_second', 'h_refund_top_sku', 'h_srv_aov_price', 'h_srv_orders', 'h_srv_top_contributor']
- text: 16 sentence(s) removed, 55 added
- latency_ms 6.816e+04 → 6.701e+04
  - −SP-AB 的支付订单增加 +72 单，与国庆满减活动相符。
  - −SP-AF 的退款金额较上期增加 CNY +693.00，退款率增加 +8.48 个百分点。
  - −净销售额增长集中在单个商品
  - +SP-AB 的支付订单量由 18 增至 90，其增长时间与促销备注重合。
  - +SP-AB 的毛利占全店毛利的 66.06%。
  - +SP-AB 的退款金额为 CNY 1,184.00，占全店退款的 49.92%。

### question_ambiguous

- success 0 → 1
- repairs 1 → 0.3333
- requests 2 → 1.333
- errors ['EVIDENCE_VALIDATION_FAILED'] → —
- text: 0 sentence(s) removed, 3 added
- latency_ms 4.92e+04 → 5670
  - +你说的“它”具体指哪项指标？本期净销售额、退款率和毛利率都有明显变化，我确认后再针对性解释原因。
  - +你说的“它”指的是哪个指标？本期净销售额、毛利率和退款占比都有变化，请告诉我你想了解哪个。
  - +您说的“它”具体指哪项指标？本期净销售额、退款占比和毛利率的变化幅度都比较大，原因各不相同，我想先确认后再分析。

### question_refunds

- success 0 → 1
- errors ['EVIDENCE_VALIDATION_FAILED'] → —
- cited — → ['h_srv_refund_concentrated', 'h_srv_refund_rate']
- text: 0 sentence(s) removed, 27 added
- latency_ms 3.883e+04 → 2.97e+04
  - +SP-AB 上期净销售额为 CNY 2,889.00，本期净销售额变化 CNY -2,889.00，是全店销售下滑的最大来源。
  - +SP-AB 本周退款占比为 100.00%，净销售额为 CNY 0.00。
  - +SP-AB 本期退款率为 100.00%，净销售额降至 CNY 0.00，上期净销售额为 CNY 2,889.00。

### recheck_refund

- requests 4 → 5.667
- cited ['h_ab_decline_follows_store_drop', 'h_aov_drives_sales_decline', 'h_aov_drop_over_order_volume', 'h_decline_concentrated_in_sku', 'h_net_sales_decline_continues', 'h_refund_rate_up_in_sku_af', 'h_sku_decline_outweighs_total', 'h_srv_refund_concentrated', 'h_srv_refund_rate'] → ['h_ab_drives_sales_drop', 'h_ab_sales_decline_clear', 'h_aov_effect_dominates', 'h_aov_effect_outweighs_orders', 'h_refund_top_sku', 'h_refund_top_sku_rank', 'h_sales_decline_streak', 'h_srv_refund_concentrated', 'h_srv_refund_rate', 'h_top_decliner_sku']
- text: 32 sentence(s) removed, 57 added
- latency_ms 6.7e+04 → 7.374e+04
  - −SP-AB 的下降主要体现在单笔金额，而非订单数量。
  - −SP-AB 贡献的净销售额变化为 CNY -2,889.00，超过本期整体变化 CNY -1,996.00。
  - −其退款金额占全店退款的81.23%。
  - +SP-AB的净销售额降幅可能与集中退款有关，需核对订单状态与商家备注。
  - +SP-AB的退款率为100.00%，其净销售额为CNY 0.00。
  - +SP-AB的退款金额为CNY 2,354.00，占全店退款的81.23%。

### refund_spike

- success 0.3333 → 0.6667
- cause_recall 0.3333 → 0.6667
- requests 4 → 5
- errors ['BUDGET_EXCEEDED', 'TIMEOUT'] → ['BUDGET_EXCEEDED']
- cited ['h_aov_drives_sales', 'h_refund_sku_af', 'h_sku_decline_ab', 'h_srv_refund_concentrated', 'h_srv_refund_rate'] → ['h_aov_effect_dominates', 'h_aov_effect_outweighs_orders', 'h_srv_refund_concentrated', 'h_srv_refund_rate', 'h_top_decliner_drives_drop', 'h_top_decliner_refund_largest', 'h_top_decliner_sku']
- text: 18 sentence(s) removed, 38 added
- latency_ms 6.05e+04 → 6.804e+04
  - −SP-AB 的支付订单数变化不大，销售贡献下降并非主要来自订单量减少。
  - −SP-AB 的退款额为 CNY 2,354.00，占全店退款的 81.23%。
  - −SP-AB 的销售贡献为 CNY -2,889.00，超过全店净销售额变化 CNY -1,996.00。
  - +SP-AB 本期净销售额为 CNY 0.00，上期为 CNY 2,889.00。
  - +SP-AB 本期净销售额为 CNY 0.00，退款为 CNY 2,354.00，对全店净销售额变化的贡献为 CNY -2,889.00。
  - +SP-AB 的退款可能与商品质量、发货或描述不符有关，需查看退款原因。

### refund_spike_en

- success 0.5 → 0.3333
- cause_recall 0.5 → 0.3333
- repairs 1.5 → 1.667
- requests 5 → 5.333
- cited ['h_aov_mix_drives_drop', 'h_sales_decline_persists', 'h_sp_ab_refund_link', 'h_sp_ab_top_decliner', 'h_srv_refund_concentrated', 'h_srv_refund_rate'] → ['h_order_value_outweighs_orders', 'h_refund_top_sku', 'h_srv_refund_concentrated', 'h_srv_refund_rate', 'h_top_decliner_drives_drop']
- text: 16 sentence(s) removed, 19 added
- latency_ms 6.904e+04 → 6.88e+04
  - −Average order value has declined for 4 consecutive periods, and gross margin changed by -1.60 pp.
  - −Compare order value and order count for the next period to see whether price or mix is driving revenue.
  - −Net sales have moved down for 3 consecutive periods.
  - +Check refund reasons for SP-AF, whose refund rate is now 13.79%, to see whether the problem is likely to repeat.
  - +Gross profit fell with sales; sales are concentrated
  - +Gross profit was CNY 8,220.95 against CNY 9,590.13 in the previous week, and gross margin moved by -1.60 pp.

### sales_drop

- success 0 → 1
- cause_recall 0 → 1
- requests 4.333 → 5.333
- errors ['BUDGET_EXCEEDED', 'TIMEOUT'] → —
- cited — → ['h_aa_largest_decliner', 'h_aa_orders_drop', 'h_aa_top_decliner', 'h_margin_up_despite_sales', 'h_prev_refund_concentrated', 'h_sales_decline_streak', 'h_srv_orders', 'h_srv_top_contributor', 'h_top_decliner_sku']
- ruled_out — → ['h_srv_aov_price']
- text: 0 sentence(s) removed, 52 added
- latency_ms 5.524e+04 → 6.345e+04
  - +SP-AA 本期净销售额仅为 CNY 453.00，支付订单数为 2。
  - +SP-AA 的销售贡献为 CNY -3,322.00，占整体净销售额变化的 57.47%。
  - +上期 SP-AD 的退款占店铺上期退款总额的 83.44%。

### small_sample_swing

- success 0.5 → 1
- repairs 1.5 → 0.3333
- requests 5 → 5.333
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_order_count_vs_order_value', 'h_refund_sku_concentration'] → ['h_margin_down_streak', 'h_margin_slightly_down', 'h_order_effect_dominates', 'h_refund_concentrated_sku', 'h_refund_rate_jump_ae', 'h_refund_rate_up', 'h_refund_rate_up_ae', 'h_refund_sku_driver']
- text: 17 sentence(s) removed, 53 added
- latency_ms 6.592e+04 → 5.982e+04
  - −全店退款金额较上期增加 CNY +344.00。
  - −商品 SP-AE 退款金额为 CNY 714.00，退款率为 20.00%，较上期上升 +13.55 个百分点。
  - −商品毛利为 CNY 9,856.17，较上期变化 +6.41%。
  - +2026-09-29 当日该商品退款额为 CNY 306.00，退款集中在周初。
  - +SP-AE 退款额为 CNY 714.00,占全店退款额的 95.20%。
  - +SP-AE 退款额为 CNY 714.00，占全店退款的 95.20%。

### stable_week

- success 0.3333 → 1
- repairs 1.667 → 1.333
- requests 4.667 → 5.333
- errors ['BUDGET_EXCEEDED'] → —
- cited ['h_order_count_drives_drop', 'h_sp_ab_refund_new'] → ['h_decliner_explains_most_drop', 'h_decliner_main_share', 'h_order_count_drives_decline', 'h_order_effect_dominates', 'h_profit_falls_faster_than_sales', 'h_refund_concentrated_in_one_sku', 'h_refund_concentrated_sku', 'h_refund_concentrated_sp_ab', 'h_sp_ab_refund_newly_appeared', 'h_sp_ac_main_sales_decliner']
- text: 11 sentence(s) removed, 52 added
- latency_ms 6.495e+04 → 6.233e+04
  - −SP-AB 本期退款率为 7.89%，上期无退款记录。
  - −SP-AH 样本较少，相关假设暂无法确认。
  - −下滑更多来自订单数减少
  - +SP-AB 本期退款为 CNY 804.00，上期为 CNY 0.00。
  - +SP-AB 本期退款额为 CNY 804.00，是全店退款的全部来源，该商品退款率为 7.89%。
  - +SP-AB 的退款可能与商品质量、描述不符或物流问题有关，需查看退款原因后确认。

### sustained_decline

- success 0.5 → 1
- requests 3.5 → 5
- errors ['BUDGET_EXCEEDED'] → —
- cited — → ['h_ag_refund_new', 'h_decline_streak', 'h_margin_stable', 'h_order_effect', 'h_order_volume_drives_decline', 'h_refund_rate_rise', 'h_refund_rate_up', 'h_sales_decline_continues', 'h_top_decliner_share', 'h_top_decliner_sku']
- ruled_out ['h_refund_concentration'] → —
- text: 17 sentence(s) removed, 57 added
- latency_ms 6.45e+04 → 6.029e+04
  - −下降可能在多个周期中持续，需要持续跟踪商品结构变化。
  - −净销售额方向为 下降，已连续 7 个周期变动。
  - −净销售额连续下降
  - +优先复查 SP-AF 与 SP-AG 的价格、促销和库存变化，确认订单减少的原因。
  - +依次排查降幅最大的商品，核对价格、库存、主图与曝光变化，争取恢复订单量。
  - +保持当前定价和商品结构，持续观察销售回落对毛利的影响。

