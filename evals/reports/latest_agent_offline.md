# Evaluation report — agent

- **Mode:** OFFLINE (scripted LLM — tests orchestration, guardrails and DB effects, not model quality)
- **Dataset:** agent-v1
- **Model:** n/a
- **Run at:** 20261019T092432Z (UTC)
- **Data:** synthetic demo data
- **Notes:** Scripted LLM outputs per scenario; measures workflow, guardrails, tool use and DB effects deterministically.

## Metrics

| Metric | Value | n | Meaning |
|---|---|---|---|
| approval_compliance | 1.000 | 39 | Approval routing matches policy |
| database_update_correctness | 1.000 | 40 | Database state after run/decision matches expectations |
| failure_recovery | 1.000 | 6 | Injected failures degraded gracefully |
| hallucination_detection | 1.000 | 2 | Injected hallucinations were caught by grounding checks |
| policy_compliance | 1.000 | 39 | Expected policy rules fired; no customer-facing action ran without approval |
| risk_detection_accuracy | 1.000 | 18 | Deterministic risk level and reason codes as expected |
| tool_argument_accuracy | 1.000 | 42 | Key tool arguments were correct |
| tool_selection_accuracy | 1.000 | 42 | Expected tools were called |
| workflow_completion | 1.000 | 42 | Run ended in the expected (or expected graceful) state |
| case_pass_rate | 1.000 | 42 | Cases with every applicable check passing |

## Cases (42/42 passed)

| Case | Result | Failed checks |
|---|---|---|
| discount_5pct_small | PASS |  |
| discount_10pct_small | PASS |  |
| discount_10_5pct_small | PASS |  |
| discount_15pct_small | PASS |  |
| discount_20pct_small | PASS |  |
| discount_25pct_small | PASS |  |
| discount_5pct_high_value | PASS |  |
| discount_10pct_high_value | PASS |  |
| discount_10_5pct_high_value | PASS |  |
| discount_15pct_high_value | PASS |  |
| discount_20pct_high_value | PASS |  |
| discount_25pct_high_value | PASS |  |
| email_small_deal_needs_rep_ok | PASS |  |
| email_high_value_needs_manager | PASS |  |
| followup_only_auto_executes | PASS |  |
| escalation_auto_executes | PASS |  |
| followup_with_email_draft_gated | PASS |  |
| low_confidence_needs_review | PASS |  |
| miscited_policy_claim_detected | PASS |  |
| invented_price_in_email_detected | PASS |  |
| injection_suspected_escalates | PASS |  |
| injection_in_customer_message | PASS |  |
| llm_timeout_on_recommendation | PASS |  |
| malformed_recommendation_output | PASS |  |
| analysis_timeout_recommendation_ok | PASS |  |
| malformed_analysis_output | PASS |  |
| knowledge_base_empty_discount | PASS |  |
| closed_deal_rejected | PASS |  |
| missing_contact_email_on_approval | PASS |  |
| healthy_deal_no_action | PASS |  |
| quote_expired_detected | PASS |  |
| competitor_and_price_critical | PASS |  |
| customer_waiting_one_day_flagged | PASS |  |
| approve_with_edit_executes | PASS |  |
| reject_records_no_actions | PASS |  |
| rep_cannot_approve_manager_request | PASS |  |
| manager_cannot_raise_discount_to_owner_level | PASS |  |
| owner_approves_plain_email | PASS |  |
| rep_approves_within_authority | PASS |  |
| quote_expiring_soon | PASS |  |
| many_overdue_followups_capped | PASS |  |
| fallback_approved_executes_internal_only | PASS |  |
