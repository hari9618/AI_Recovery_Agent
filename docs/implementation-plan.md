# Implementation Plan — AI Revenue Recovery Agent

This is the working plan for the build. It records what was found in the environment, the
architecture we are committing to, and the order of delivery. Engineering rationale for the
bigger choices lives in [engineering-decisions.md](engineering-decisions.md).

## 0. Environment findings (Step 1)

| Item | Finding | Consequence |
|---|---|---|
| Repo | Empty folder; parent home directory was an unrelated git repo | Initialised a dedicated repo (`main`) |
| Python | 3.11.9, `uv` 0.11 | Backend managed with `uv`, Python 3.11 |
| Node | 24.x, npm 11 | Next.js 16 + React 19 + Tailwind 4 |
| Docker | CLI installed, **daemon unavailable (WSL not installed)** | `docker-compose.yml` is written for portability but local dev uses an embedded Postgres |
| Postgres | Not installed natively | `pgserver` wheel ships Postgres + **pgvector** for Windows/macOS/Linux; `scripts/dev_db.py` runs it |
| Redis | Not installed | Redis is optional; a `Cache` interface falls back to in-process memory |
| API keys | `GROQ_API_KEY`, Langfuse keys not set | LLM features report `LLM_NOT_CONFIGURED` honestly; nothing is faked |

Reference repo **morluto/rea** (an MCP server for reverse engineering) was studied for patterns only. Patterns adopted (re-implemented in Python, no code copied):

- one typed contract per tool (input schema, output schema, declared *effects*), MCP annotations
  *derived* from effects rather than hand-written;
- a closed error contract `{code, category, message, retryable, remediation}` where `retryable` is
  computed from the code;
- evidence carries provenance (`observed` / `derived` / `inferred`) and explicit `limitations`;
- "missing coverage is unknown, not absence" — the agent reports what it could not determine;
- tool results that may contain customer/document text are marked as untrusted content;
- contract-level invariant tests (every tool declares effects; read-only tools have no effects).

## 1. Architecture

```
Next.js (apps/web)  ──HTTP/JSON──►  FastAPI (apps/api)
                                       │
           ┌───────────────┬──────────┼──────────────┬────────────────┐
       API routers     Services    Agents (LangGraph)  Tools registry ──► MCP server (stdio)
           │               │          │                    │
           └─────── Domain (pure): risk engine, policy engine, ROI, scoring config
                           │
        LLM layer (LLMProvider → GroqProvider)   RAG (BM25 + pgvector → RRF → rerank → grounding)
                           │
        Observability (Langfuse facade, never raises)  +  local llm_calls / agent_runs tables
                           │
                PostgreSQL + pgvector        Redis (optional cache)
```

Layering rule: `domain/` has no I/O and no framework imports; services orchestrate DB + domain;
agents call **tools**, never the ORM directly; routers are thin.

## 2. Database schema (PostgreSQL)

All business tables carry `company_id` (tenant isolation) and are indexed on it. UUID primary keys,
`created_at`/`updated_at`, enums as Postgres enums, money as `NUMERIC(14,2)`.

| Table | Purpose / key columns |
|---|---|
| `companies` | tenant; `currency`, `settings` JSONB (thresholds), `is_demo` |
| `users` | `role` (owner, manager, sales_rep, admin), hashed API token |
| `customers` | account; `industry`, `segment`, `status` (prospect/active/churned), `owner_id`, `is_synthetic` |
| `contacts` | people at customers; `is_decision_maker` |
| `leads` | inbound lead; `source`, `status`, `assigned_to`, `estimated_value`, first/last contact |
| `opportunities` | deal; `stage`, `amount`, `expected_close_date`, `last_activity_at`, `competitor`, `loss_reason` |
| `quotes` / `quote_items` | quotation header + lines; `status`, `discount_pct`, `sent_at`, `valid_until` |
| `conversations` / `conversation_messages` | transcripts; `channel`, `sender_type` |
| `conversation_analyses` | cached LLM analysis keyed by `content_hash` (+ model, status ok/fallback) |
| `followups` | tasks; `due_at`, `status`, `created_by_agent` |
| `activities` | CRM timeline; `type`, `occurred_at`, `metadata` JSONB |
| `revenue_risks` | engine output; `risk_score`, `risk_level`, `revenue_at_risk`, `reason_codes` JSONB, `engine_version`, `is_current` |
| `agent_runs` | one recovery workflow run; status, step log, tokens, cost, latency, `trace_id` |
| `recommendations` | agent output; WHAT/WHY/evidence/proposed action/draft/confidence/status |
| `approval_requests` | HITL queue; reasons, decision, editor, edited payload |
| `actions` | executed/blocked actions with input/result |
| `knowledge_sources` / `documents` / `document_chunks` | RAG corpus; chunks have `embedding vector(384)`, `section`, metadata |
| `llm_calls` | per-call usage: model, tokens, latency, estimated cost, status |
| `ingestion_jobs` | import results incl. row-level validation errors |
| `evaluation_runs` / `evaluation_cases` / `evaluation_results` | stored eval runs (labelled demo/live/offline) |
| `audit_logs` | append-only: actor, agent, tool, input, output, approval, result, trace_id |

JSONB only for genuinely variable payloads (reason codes, evidence lists, tool I/O, settings).

## 3. Deterministic engines (no LLM)

- **Revenue Risk Engine** — pure function `assess(signals, config) -> RiskAssessment`. Each rule
  contributes points with a reason code, a human label and the evidence values used. Score capped at
  100; level thresholds CRITICAL ≥ 75, HIGH ≥ 55, MEDIUM ≥ 35. `revenue_at_risk` = open deal value
  (quote total if a live quote exists, else opportunity amount); `weighted_revenue_at_risk` =
  value × purchase probability. Purchase probability = historical stage conversion rate (computed
  from closed deals in the DB) adjusted by intent. Conversation signals come from stored LLM
  analysis when available, otherwise from a labelled keyword heuristic — the reason code records
  which source was used.
- **Policy Engine** — thresholds from company settings: discount > 10% → approval; refund >
  threshold → approval; deal value ≥ high-value threshold → approval for customer-facing actions;
  confidence < threshold → review; insufficient policy evidence → approval; `send_email` needs
  approval unless explicitly configured safe. Low-risk internal actions (follow-up task, reminder,
  draft, activity log) auto-execute.
- **ROI Engine** — observed figures from DB only; estimates use explicit, displayed assumptions.

## 4. LLM layer

`LLMProvider` (abstract) → `GroqProvider` (official `groq` SDK, async). Only module that imports
`groq`. Features: timeout + bounded retries with backoff, JSON-schema structured output (strict when
the model supports it, `json_object` otherwise) validated with Pydantic, re-ask with validation
error, safe fallback, tool-calling mode, usage/cost accounting (`llm_calls`), Langfuse generation.
Model comes from `GROQ_MODEL`; price table is overridable via env and labelled *estimated*.

## 5. Hybrid RAG

Ingest (PDF/MD/TXT) → validate → injection scan → section-aware chunking → embed (fastembed
`BAAI/bge-small-en-v1.5`, 384-d, local ONNX) → `document_chunks`. Query → in parallel: Okapi BM25
(own implementation, per-tenant cached index) and pgvector cosine (SQL with `company_id` +
`document_type` filters) → Reciprocal Rank Fusion (k=60) → cross-encoder rerank
(`Xenova/ms-marco-MiniLM-L-6-v2`) → top-k with score floor. Grounded answering returns
`claims[] {claim, source_document, source_section, retrieval_score}`; citations are validated
against retrieved evidence; otherwise `INSUFFICIENT_EVIDENCE`. Transactional data never goes
through RAG.

## 6. Agent workflow (LangGraph)

Two explicit graphs with a durable hand-off in Postgres (approvals can take days):

1. **Investigation graph**: `load_context → analyze_conversation → assess_risk →
   retrieve_knowledge → recommend → ground_check → policy_check → (auto_execute | request_approval)`.
2. **Execution graph** (on approval or auto): `execute_action → verify → finalize`.

Typed `RevenueRecoveryState` (TypedDict). Nodes call tools from the registry; every tool call is
audited. Failure in any LLM node degrades to a safe, labelled fallback (e.g. "manual review
required") rather than an invented recommendation.

A separate **Revenue Copilot** endpoint demonstrates LLM tool calling: the model picks read-only
tools (same registry as MCP) in a bounded loop (max 4 steps).

## 7. Tools & MCP

`ToolSpec(name, description, input_model, output_model, effects, handler)`; annotations derived
from effects; uniform `ToolResult` envelope with provenance + limitations + error contract.
Registry is shared by agents, the copilot and an MCP stdio server (`python -m app.mcp.server`)
exposing `revenue.*` tools.

## 8. API design (prefix `/api/v1`)

`/health`, `/demo/load`, `/dashboard/summary`, `/risks`, `/risks/recompute`, `/customers`,
`/customers/{id}` (intelligence profile), `/opportunities` (pipeline), `/conversations`,
`/conversations/{id}`, `/conversations/{id}/analyze`, `/agent/runs` (POST start, GET list/detail),
`/recommendations`, `/approvals`, `/approvals/{id}/decision`, `/knowledge/documents` (+upload),
`/knowledge/search`, `/knowledge/ask`, `/ingest/{entity}` (CSV/JSON), `/copilot/ask`,
`/evaluations/runs`, `/observability/status`, `/observability/usage`, `/audit`, `/settings`, `/roi`.

Auth-ready: `Authorization: Bearer <token>` resolved to a `Principal(user, company, role)`;
demo token configured via env. Role checks guard approvals and settings.

## 9. Frontend pages

Dashboard · Revenue Risks · Customers (+ detail) · Opportunities (pipeline board) ·
Conversations (+ transcript/analysis) · Recommendations · Approval Center · Knowledge Base ·
Data Import · Evaluations · Observability · Audit Log · Settings. shadcn/ui + Tailwind 4,
TanStack Query, Recharts, React Hook Form + Zod. Every metric carries a provenance badge
(Observed / Estimated / Synthetic demo / Not evaluated yet).

## 10. Evaluation

- `python -m evals.run` (suites: `rag`, `agent`, `copilot`, `all`).
- RAG: Ragas (faithfulness, answer relevancy, context precision/recall) with Groq as judge +
  custom deterministic metrics (citation accuracy, policy-fact accuracy, insufficient-evidence
  correctness, injection resistance).
- Agent: 40+ scenario cases asserting approval compliance, policy compliance, workflow completion,
  DB update correctness, failure recovery; copilot cases for tool selection / argument accuracy.
- Results stored in DB and `evals/reports/*.md|json`, labelled `live` or `offline`.

## 11. Observability

`Tracer` facade over Langfuse v5 (OTel-based). Root trace per agent run with child spans per node,
generations for each Groq call (model, tokens, cost, latency), retrieval spans (BM25 / vector /
rerank), tool spans, and scores. Any Langfuse error is swallowed and logged — never breaks a run.

## 12. Phases

| # | Phase | Exit criteria |
|---|---|---|
| 1 | Repo, config, tooling | `uv sync`, settings load, lint/test runner works |
| 2 | Schema + Alembic | migration applies on embedded Postgres with pgvector |
| 3 | Synthetic data | deterministic generator, volumes met, Vertex scenario present |
| 4 | FastAPI foundation | health, auth principal, error handling, list endpoints |
| 5 | Risk engine | unit tests for every rule + batch recompute |
| 6 | LLM provider | Groq provider + structured-output retry/fallback tests |
| 7 | Conversation intelligence | analysis endpoint + caching by content hash |
| 8 | Hybrid RAG | ingestion, retrieval, fusion/rerank tests, grounding |
| 9 | Recovery agent | LangGraph workflow end-to-end |
| 10 | Tools + MCP | registry, contracts tests, MCP server |
| 11 | HITL + guardrails | approvals, policy engine, injection defence |
| 12 | Langfuse | trace tree for the demo run |
| 13 | Evals | `python -m evals.run` produces reports |
| 14–17 | Frontend | all pages wired to real APIs |
| 18 | Testing | unit + integration + e2e green |
| 19 | Docker | compose file + Dockerfiles |
| 20 | Docs | README + docs set |
| 21 | Demo validation | full Vertex scenario walkthrough |
