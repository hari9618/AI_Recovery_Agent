# Interview guide

Short, honest answers you can give out loud. Numbers quoted here were measured in this repository.

---

**1. Explain the project in one minute.**
It's an AI revenue-recovery product for B2B sellers. A deterministic risk engine scores every open deal 0–100 with
explained reasons: customer waiting, quote unanswered, competitor mentioned, and so on. For risky deals, a LangGraph
agent reads the conversation, retrieves the relevant company policy with hybrid RAG, and drafts a grounded
recommendation and follow-up email. A policy engine then decides whether a human must approve it. Anything
customer-facing goes to an approval centre. Everything is traced in Langfuse, evaluated with Ragas plus a 42-scenario
agent suite, and exposed over MCP.

**2. What business problem does it solve?**
Deals die quietly when follow-ups slip. The customer asks a question, nobody answers for five days, and they buy from a
competitor. The owner has no single view of where money is leaking, why, and what to do today. This gives them that
view and does the preparation work: analysis, the policy lookup, the draft. A human keeps the decision.

**3. Walk me through the architecture.**
Next.js frontend, with a server-side proxy that holds the API token. FastAPI backend with clear layers: a pure domain
(risk and policy engines), services, a typed tool registry, LangGraph agents, RAG, and a provider-agnostic LLM layer
backed by Groq. Data lives in PostgreSQL with pgvector for knowledge embeddings, and Redis handles caching and rate
limits. The same tool contracts are used by the agent, the copilot and an MCP server.

**4. Why is the risk score deterministic and not from the LLM?**
An owner has to trust and question the number. "+20 because the customer has waited 4 days" is reproducible,
testable and tunable. A number an LLM invents is none of those things. The LLM is used where language understanding is
needed: intent, objections and competitors in the conversation. Those become inputs to the engine, and each reason
records whether it came from the LLM or from a keyword heuristic.

**5. Why hybrid RAG instead of plain vector search?**
Policy questions hinge on exact tokens like "10%", "₹50,000" or a SKU, and dense embeddings blur those. BM25 catches
them, while dense search catches paraphrases. RRF fuses the two by rank, and a cross-encoder reranks the results and
enforces a relevance floor. Offline, it finds the right section for 20 of 20 policy questions, with an MRR of 0.967.

**6. How do you stop hallucinated policy?**
The model must answer as claims that cite evidence IDs. Each claim is then checked in code: the cited ID has to exist,
a cross-encoder must agree the passage supports the claim, and every number in the claim must appear in the cited
text. Unsupported claims are flagged and push the recommendation to human review. If nothing relevant is retrieved,
the answer is INSUFFICIENT_EVIDENCE.

**7. Why did you use a cross-encoder for claim verification?**
I measured it. With bi-encoder cosine, a wrong passage from the same policy corpus scored 0.57 and the right one 0.75,
which is too close for a safe threshold. The cross-encoder gave about 0.00 against about 1.00. It caught a mis-cited
claim that cosine had passed.

**8. Why LangGraph, and why two graphs?**
The process is known: gather, assess, retrieve, recommend, verify, check policy, approve, execute, verify. Explicit
edges give predictability and testability, and each step is traceable. Approvals can wait days, so the investigation
graph ends at "awaiting approval" and the state is persisted in Postgres. A second graph runs execution after the
human decision. It survives restarts and needs no checkpoint store.

**9. Where does the LLM call tools?**
In the Revenue Copilot. It runs a bounded loop of at most four turns over read-only tools: at-risk deals, customer
intelligence, the recovery report, policy thresholds and knowledge search. Arguments are validated by Pydantic, results
go back as untrusted data, and the whole trace is shown. The main agent calls tools from explicit nodes rather than
letting the model choose, because the steps are known in advance.

**10. How does human-in-the-loop work?**
A deterministic policy engine evaluates the proposed action. It checks the discount authority matrix, refunds,
customer-facing actions on high-value deals, low confidence, unverified claims, suspected injection, and whether the
LLM fell back. Internal tasks run automatically, everything else opens an approval request with the exact rules that
fired, and the approver can approve, edit or reject. The approval is enforced twice: the `send_email` and
`offer_discount` tools check the database for an approved request themselves. Edits are re-checked too, so a manager
raising a discount to 25% gets "forbidden" because that needs the owner.

**11. How do you handle structured-output failures?**
Pydantic models become strict JSON schemas for Groq's constrained decoding, and the output is still validated by
Pydantic afterwards. If validation fails, I re-ask with the specific errors, up to twice. If it still fails, the step
falls back to a clearly labelled deterministic result. Malformed output is never accepted, and every attempt is
recorded with its status.

**12. How do you defend against prompt injection?**
There are four layers. Prompts separate trusted blocks from untrusted ones, with delimiters the content can't close. A
scanner flags instruction-like text, and flagged chunks are withheld from the model. The model can only propose
(customer-facing tools need approval in the database), and outputs are verified. The demo knowledge base includes a
poisoned document. Tests prove it's retrieved but never reaches a prompt.

**13. How did you evaluate it?**
There are three suites, run with `python -m evals.run`. The agent suite has 42 scenarios, scored on approval and policy
compliance, tool selection and arguments, database correctness, hallucination detection and failure recovery. The RAG
suite has 26 questions: retrieval metrics offline, plus Ragas and citation and policy-fact accuracy live. The copilot
suite is 12 tool-selection cases, live only. Offline runs use a scripted LLM, and I say clearly that they measure
orchestration, not model quality. The first offline run surfaced a calibration question (a one-day wait scored LOW),
which I documented rather than hid.

**14. Why Ragas plus custom metrics?**
Ragas measures answer quality with an LLM judge, but it doesn't know my policies or workflow. Business guarantees like
"no customer email without approval" or "revised quote total is correct" need deterministic checks.

**15. How is it observable?**
Langfuse traces every run: a span per node, generations with prompt, model, tokens and cost, retrieval spans with
reranker scores, tool spans and scores. A tracer facade makes Langfuse failures harmless. A local `llm_calls` ledger
keeps cost and latency dashboards working without Langfuse.

**16. How do you control cost and latency?**
I keep the LLM off everything deterministic, such as scoring, policy and deciding what to retrieve. Conversation
analysis is cached by transcript hash and prompt version. Prompts are small, query embedding runs in parallel with
BM25, dashboard aggregates are cached, LLM endpoints are rate-limited, and cost is tracked per call and per run.

**17. Why Groq? What if it goes away?**
Low latency for an interactive workflow, plus strict JSON-schema support on the gpt-oss models. Everything depends on
the `LLMProvider` interface; switching vendors is one new class and an environment variable. Tests already run
through a scripted provider.

**18. Why PostgreSQL instead of a vector database?**
Revenue questions are exact and relational, so they need transactions, constraints and joins. pgvector keeps
embeddings next to the data, inside the same tenant filter and backup. A dedicated vector DB would only make sense at
millions of chunks per tenant.

**19. What is MCP doing here?**
It exposes `revenue.*` tools such as at-risk deals, customer intelligence, knowledge search, risk calculation,
follow-ups and approval requests to any MCP client, using the same Pydantic contracts. Annotations are derived from
declared effects, and customer-facing tools are deliberately not exposed. I borrowed architectural patterns from the
open-source REA project (effect-derived annotations, a closed error contract, evidence and limitations in results)
without copying code.

**20. How do you measure ROI without lying?**
Three labels. *Observed*: counts from the database, such as revenue recovered from deals won after an executed recovery
action. *Estimated*: observed counts times displayed, editable assumptions. *Synthetic demo*: anything computed on demo
data. Nothing estimated is shown as a result.

**21. What was hard?**
- Keeping the AI honest end to end, from claim verification to the email-number check. The model once computed a
  discounted price itself; the guard flagged it, and now arithmetic happens in code.
- Durable human-in-the-loop across restarts.
- Making Langfuse impossible to break the product.
- Building local infrastructure without Docker, using embedded Postgres with pgvector.

**22. What are the limitations?**
- Synthetic data, so the risk weights are reasoned defaults, not learned.
- No CRM or email connectors (emails go to an outbox).
- Live Ragas numbers need a Groq key.
- The injection scanner is pattern-based.
- Auth is token-based, with OIDC next.

**23. What would you do next?**
CRM connectors with webhook-driven re-scoring, risk weights learned from won and lost outcomes, nightly digests, real
email and WhatsApp delivery, OIDC, and online evaluation sampled from production traces.

**24. How do you know it works?**
- 160 automated tests, including an HTTP end-to-end flow from lead import to recovered revenue.
- 42/42 offline agent scenarios.
- Retrieval hit-rate 1.0 on the policy set.
- Every claim in the UI is traceable to a database row, a reason code, a cited passage or a Langfuse span.
