# LLMOps

## Provider abstraction

`LLMProvider.complete(messages, purpose, response_model?, tools?, temperature?, max_tokens?) → LLMResponse`.
`GroqProvider` (the only module importing `groq`) adds: SDK retries with backoff for 429/5xx/timeouts, a concurrency
semaphore, exception → error-code mapping (`LLM_TIMEOUT`, `LLM_RATE_LIMITED`, `LLM_UNAVAILABLE`,
`LLM_INVALID_OUTPUT`, `LLM_NOT_CONFIGURED`), reasoning settings for gpt-oss models, and a Langfuse generation per call.

Configuration: `GROQ_API_KEY`, `GROQ_MODEL` (e.g. `openai/gpt-oss-120b`), `GROQ_STRUCTURED_MODE`
(`json_schema` strict or `json_object`), `GROQ_REASONING_EFFORT`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`.

## Structured outputs

Pydantic models → strict JSON Schema (all properties required, `additionalProperties: false`, unsupported keywords
stripped) → Groq constrained decoding → Pydantic validation → on failure, re-ask with the validation errors (up to two
repairs) → labelled fallback. Every attempt is recorded (`ok`, `repaired`, `fallback`, `error`).

## Cost and latency

- Local ledger `llm_calls`: purpose, model, status, input/output tokens, latency, attempts, **estimated** cost
  (published per-million-token prices, overridable via env), trace id, agent run.
- `agent_runs` aggregates calls, tokens, cost and latency per run.
- Observability page: totals, failure/fallback rate, p50/p95 latency per purpose, daily tokens, recent runs.

Cost controls: conversation analysis cached by transcript hash + prompt version; retrieval queries planned
deterministically (no LLM call to decide what to search); risk and policy never call the LLM; prompts send only the
fields a step needs; dashboard aggregate cached 30 s; per-user rate limits on LLM endpoints.

## Prompts

Versioned in `app/prompts/` (`conv-v1`, `rec-v1`, `grounded-v1`). A prompt-version change invalidates the analysis
cache automatically. Every prompt includes the same security rules and separates trusted blocks (CRM facts,
risk assessment, enforced policy) from untrusted blocks (customer text, retrieved documents).

## Tracing (Langfuse v3+ OTel SDK)

Root `RevenueRecovery` trace per run (user, session = run id, tags), child spans per node (`chain`), tool spans
(`tool`), retrieval spans (`retriever`), generations with model, parameters, usage and cost, and scores
(`grounding_score`, `recommendation_confidence`, `human_approved`, `eval_*_passed`). The `Tracer` facade swallows
every SDK error; a unit test drives it with a client whose every method raises.

## Model choice

Default suggestion `openai/gpt-oss-120b`: production model on Groq with strict JSON-schema support. `gpt-oss-20b` is
cheaper for conversation analysis at volume. Groq does not combine structured output with tool calling in one request;
the copilot uses plain tool calling and the extraction steps use strict schemas.
