# Agent workflow

## Graphs

```mermaid
flowchart TD
  start([start]) --> load[load_context<br/>tool: get_opportunity]
  load -->|closed / missing| stop1([end: failed])
  load --> conv[analyze_conversation<br/>tool: analyze_conversation (LLM, cached)]
  conv --> risk[assess_risk<br/>tool: calculate_revenue_risk (deterministic)]
  risk -->|LOW and not forced| stop2([end: no action needed])
  risk --> rag[retrieve_knowledge<br/>queries planned from reason codes<br/>tool: search_knowledge_base ×≤4]
  rag --> rec[recommend<br/>LLM structured output · rules fallback]
  rec --> ground[ground_check<br/>claims · citations · numbers]
  ground --> policy[policy_check<br/>deterministic policy engine]
  policy --> persist[persist_recommendation<br/>draft · auto follow-up · activity · approval request]
  persist -->|approval required / blocked| stop3([end: awaiting approval])
  persist -->|auto-executable| exec[execute_action]
  exec --> verify[verify<br/>re-read DB]
  verify --> stop4([end])
```

After a human approves, the **execution graph** (`execute_action → verify`) runs with the saved state plus any human
edits. Splitting the graphs keeps approvals durable across restarts without a checkpoint store.

## State

`RevenueRecoveryState` (TypedDict): ids, `crm_context`, `conversation_context`, `risk_analysis`,
`retrieval_queries`, `retrieved_context`, `withheld_evidence`, `recommendation`, `grounding`, `proposed_action`,
`policy_check`, `approval_required`, `recommendation_id`, `approval_request_id`, `internal_actions`,
`execution_result`, `verification_result`, `status`, and append-only `limitations` / `errors`. The final state is
saved on the `agent_runs` row.

## Where the LLM is used — and where it is not

| Step | LLM? | Why |
|---|---|---|
| Load CRM context | No | Exact data from SQL |
| Conversation analysis | Yes | Intent, objections, competitor mentions require reading language |
| Risk score | No | Must be reproducible and explainable |
| Choosing what to retrieve | No | Follows from reason codes via a lookup table |
| Recommendation + draft | Yes | Synthesis and writing |
| Grounding | No (cross-encoder model, deterministic thresholds) | Verification must not trust the generator |
| Policy / approval routing | No | Business rules |
| Execution & verification | No | Tools + DB checks |

## Failure handling

| Failure | Behaviour |
|---|---|
| Groq timeout / rate limit / outage | Conversation step: keyword heuristics (labelled). Recommendation: deterministic rules fallback, needs review. |
| Invalid structured output | Re-ask with validation errors (×2) → labelled fallback; never accepted |
| Missing customer / closed deal | Run ends `failed` with a clear error, nothing written |
| Empty retrieval | `INSUFFICIENT_EVIDENCE`; commercial actions then require manager approval |
| Tool failure | Closed error contract back to the node; run records the error |
| Database failure | Transaction rolled back, run marked failed in a separate session |
| Langfuse failure | Ignored by the tracer facade |
| Missing contact email on an approved email | Execution reports an explicit failure (never a silent skip) |
| Suspected prompt injection | Flagged chunks withheld; model-reported injection forces human review |

## Copilot (open-ended Q&A)

A separate, bounded tool-calling loop (≤ 4 model turns) over read-only tools: at-risk list, customer intelligence,
recovery report, sales policy thresholds, knowledge search. Tool arguments are validated by the same Pydantic models;
results are passed back as untrusted data; the full trace is returned to the UI.
