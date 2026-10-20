# Engineering decisions

Each entry: the decision, why, what we gave up, and how you would know if it were wrong.

---

## 1. PostgreSQL as the system of record, not a vector database

**Decision.** All business data (customers, deals, quotes, timestamps, approvals, audit) lives in normalised
PostgreSQL tables. Embeddings live in the same database via `pgvector`, but only for knowledge documents.

**Why.** "How much revenue is at risk?" or "which quotes expire this week?" are exact questions with exact answers.
SQL gives correctness, joins, constraints (`CHECK discount_pct BETWEEN 0 AND 100`), transactions and indexes.
A vector store answers *similarity* questions; using it for transactional data would trade exactness for fuzziness.
Keeping vectors in Postgres also means one backup, one permission model, and tenant filtering (`company_id`) in
the same query as the similarity search.

**Trade-off.** pgvector's HNSW index is not as tunable as a dedicated vector DB at very large scale (tens of
millions of chunks). Not a concern for a per-tenant policy corpus.

**Would be wrong if** the knowledge corpus grew to millions of chunks per tenant with strict latency SLOs.

## 2. Hybrid RAG (BM25 + dense + RRF + cross-encoder) — and RAG only where it helps

**Decision.** Knowledge retrieval runs Okapi BM25 and pgvector cosine search, fuses them with Reciprocal Rank
Fusion, reranks with a cross-encoder, and applies a relevance floor. RAG is used only for unstructured policy and
playbook text; CRM facts never go through RAG.

**Why.** Policy questions hinge on exact tokens ("10%", "SVC-AMC", "₹50,000") that dense embeddings blur, while
paraphrased questions ("can a rep give a discount on their own?") need semantic matching. RRF combines both without
needing comparable scores. The cross-encoder then separates "on-topic" from "actually answers it". Measured on the
demo corpus: retrieval hit-rate 1.00 and MRR 0.967 over 20 answerable questions (offline eval).

**Trade-off.** Reranking costs ~1 s on CPU for 12 candidates. We cap candidates at 12 and run query embedding on a
worker thread in parallel with BM25.

## 3. Deterministic risk scoring, policy checks and ROI

**Decision.** The Revenue Risk Engine, Policy Engine and ROI calculations are pure Python functions with
configurable weights. The LLM never produces a score, a threshold decision or a money figure.

**Why.** A risk score shown to a business owner must be reproducible and explainable ("+20: customer waiting
4 days"). LLM-generated numbers are neither. Determinism also makes them unit-testable (the engine has ~30 tests) and
lets the business tune weights in Settings without retraining anything.

**Where the LLM still helps.** It reads the conversation (intent, objections, competitor mentions). Those become
*inputs* to the engine, and every reason records its source (`llm_analysis` vs `keyword_heuristic`).

**Evidence it matters.** In development the LLM drafted an email quoting "₹4,22,400" (its own arithmetic for a 12%
discount). The grounding check flagged it as a figure not present in any source, and the prompt now tells the model
to state percentages only — the revised total is computed by `offer_discount` in code (₹4,80,000 × 0.9 = ₹4,32,000).

**Calibration choice surfaced by evaluation.** A customer waiting ~1 day on an otherwise fresh deal scores LOW
(15 + 6 late-stage = 21) while still showing the reason and "reply today". We kept it: the level expresses revenue at
risk, not the urgency of one reply. The weights are tenant-configurable.

## 4. LangGraph with explicit edges, not an autonomous loop

**Decision.** The recovery workflow is a LangGraph `StateGraph` with named nodes and deterministic conditional
edges, and a typed `RevenueRecoveryState`. Two graphs: *investigation* (ends at approval) and *execution* (after a
human decision). The hand-off between them is durable in PostgreSQL.

**Why.** The business process is known: gather facts → assess → retrieve policy → recommend → verify → policy-check →
approve → execute → verify. An open "agent decides what to do next" loop adds variance, cost and failure modes
without adding value here. Splitting the graphs means approvals can wait days and survive restarts without
needing a checkpoint store; the saved state plus the approval row is enough to resume.

**Where open-ended tool use is appropriate.** The Revenue Copilot (Q&A) lets the model choose among read-only tools
in a bounded loop (≤4 steps) — the questions are open-ended, the tools cannot change anything.

## 5. Groq behind a provider interface

**Decision.** `LLMProvider` → `GroqProvider`; the model comes from `GROQ_MODEL`. Only `groq_provider.py` imports
the vendor SDK.

**Why Groq.** Low latency matters for an interactive "investigate this deal" flow, and Groq's `gpt-oss` models
support strict JSON-schema structured output. **Why the interface.** Providers change prices, deprecate models and
have outages. Swapping vendors means one new class; tests use a scripted provider through the same interface.

**Structured-output detail.** Groq does not allow structured output and tool calling in the same request, so the
provider uses `json_schema` (strict) for extraction steps and plain tool calling for the copilot. Strict schemas are
generated from Pydantic (all properties required, `additionalProperties: false`, unsupported keywords removed) and
Pydantic validation still runs afterwards. Invalid output is repaired by re-asking with the validation errors, and
after two repairs the step falls back to a labelled deterministic result — never silently accepted.

## 6. Langfuse for tracing, plus a local usage ledger

**Decision.** Langfuse (v3+ OpenTelemetry SDK) traces agent runs, node spans, generations, retrieval, tool calls and
scores, through a `Tracer` facade whose every call swallows errors. Token usage, latency and estimated cost are also
written to a local `llm_calls` table.

**Why.** Tracing is how you debug "why did the agent recommend that?". But observability must never break the
product: a unit test runs the full trace API against a client whose every method raises. The local ledger keeps cost
and latency dashboards working when Langfuse is not configured.

## 7. Ragas *and* custom evaluation

**Decision.** Ragas (faithfulness, answer relevancy, context precision/recall) for RAG answer quality in live mode,
plus deterministic custom metrics (retrieval hit rate, MRR, citation accuracy, policy-fact accuracy,
insufficient-evidence accuracy, injection resistance) and a 42-case agent workflow suite.

**Why.** Ragas measures text quality with an LLM judge; it does not know our policies or our workflow. The agent
suite checks business guarantees (approval routing, no unapproved customer-facing action, correct DB effects,
graceful failure). Offline mode runs without any API key so CI can gate on it; live mode measures the real model.
Every report states its mode, and the app shows "Not evaluated yet" until a run exists.

## 8. Human approval for risky actions, enforced twice

**Decision.** The deterministic Policy Engine decides what needs approval (discount authority matrix, refunds,
high-value customer-facing actions, low confidence, unverified claims, suspected injection, LLM fallback). Separately,
the `send_email` and `offer_discount` tools verify inside their handlers that an APPROVED approval exists in the
database.

**Why twice.** The graph routing could have a bug, and an injected instruction could try to call a tool directly.
The tool-level check doesn't depend on either behaving correctly. Approval also re-checks human edits: a manager who
raises a discount to 25% gets `forbidden`, because 25% needs the owner.

## 9. MCP for interoperability, from the same tool contracts

**Decision.** The tool registry (typed Pydantic input/output, declared effects) is projected into an MCP stdio server
exposing `revenue.*` tools. Annotations (`readOnlyHint`, `destructiveHint`…) are derived from declared effects;
results carry provenance and an `untrusted_content` flag.

**Why.** It lets other agents (Claude Desktop, IDE agents, internal tools) use the same capabilities without new
APIs, while keeping one contract per tool. Customer-facing tools are deliberately *not* exposed over MCP.
Patterns (effect-derived annotations, closed error contract with computed `retryable`, evidence and limitations in
results, contract invariant tests) were inspired by studying the open-source `morluto/rea` project; no code was copied.

## 10. Why not make everything autonomous?

Because the expensive failures in revenue work are customer-facing: a wrong discount, a promise outside policy, an
email to the wrong person. Automation is applied where mistakes are cheap and reversible (internal follow-up tasks,
drafts, activity logs, escalations); everything that reaches a customer or changes money goes through a person, with
the evidence and the reasons in front of them. The ROI comes from finding and prioritising at-risk deals and doing
the preparation work; the human keeps the decision.

## 11. Smaller decisions

| Decision | Reason |
|---|---|
| Embedded Postgres (`pgserver`) for local dev | Docker/WSL unavailable on the build machine; the wheel ships Postgres **with pgvector**. Docker Compose is provided for other environments. |
| Local ONNX embeddings (fastembed, bge-small) | No embedding API cost/latency, no data leaves the machine, deterministic in tests. Groq has no embedding endpoint. |
| Own BM25 implementation | ~60 lines, tenant-scoped cache keyed on corpus version, exact control over tokenisation of "10%", "₹50,000". |
| Cross-encoder for claim support | Bi-encoder cosine gave 0.57 for an unrelated same-domain passage vs 0.75 for the right one; the cross-encoder gives ~0.00 vs ~1.00. |
| Withhold flagged chunks from LLM context | Defence in depth: the injection scanner's hits are visible in search, never fed to the model. |
| Outbox email transport | No email provider is integrated; the UI and API state "recorded in outbox, not delivered". Nothing pretends to send. |
| Next.js server-side proxy for the API | The API token never reaches the browser. |
| Redis optional | Nothing in the critical path needs it at demo scale; the code keeps caches in-process (BM25 per tenant). |
| Chat memory replays only visible text | The copilot gets the last 8 turns (each capped at 1,500 chars); earlier answers are neutralised like tool data and a client cannot inject a `system` turn. Facts still come from tools on every turn. |
| Model markdown rendered without raw HTML | Answers render through `react-markdown` with no HTML pass-through; stray `<br>` in table cells becomes a real line break via a marker, never via HTML. |
| Strict-schema keyword stripping skips `properties` | The schema cleaner dropped a field literally named `title`, so every live recommendation failed validation. Field names are now never treated as keywords (regression test added). The scripted test LLM could not catch it; the first live run did. |
| `useHydrated()` gate for shared queries | Suspense boundaries hydrate separately, so a query started by the header can resolve before the sidebar/page hydrate; data is rendered only after hydration to keep server and client HTML identical. |
| Design system: warm white, ink and copper | Bricolage Grotesque headlines, Geist text and Geist Mono figures; copper as the single brand colour with blue and mint accents; navy "data" panels for live numbers. Motion is limited to reveals, count-ups and layout transitions, all disabled under `prefers-reduced-motion`. |
