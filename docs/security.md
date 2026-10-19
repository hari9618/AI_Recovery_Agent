# Security

## Authentication and authorisation

- `Authorization: Bearer <token>`; the SHA-256 of the token is looked up in `users.api_token_hash` and resolved to a
  `Principal(user_id, company_id, role)`. Raw tokens are never stored. Swapping in OIDC/JWT changes one function.
- Roles: sales_rep < manager < admin < owner. Settings changes need admin+; approvals need the role the policy engine
  assigned to the request (a rep cannot approve a manager-level request; a manager cannot raise a discount to an
  owner-level value).
- First-run bootstrap (`/demo/bootstrap`) only works while no tenant exists and only with the configured
  `DEMO_API_TOKEN`, compared in constant time.

## Tenant isolation

Every top-level business table carries `company_id` (line-item tables such as `quote_items` and
`conversation_messages` are only reached through their tenant-scoped parent); every service and tool query filters on
the principal's company. Integration
tests verify a second tenant gets 404 / empty results for the demo tenant's customers, conversations and risks.

## Secrets

Environment variables only (`.env`, git-ignored). The frontend calls the API through a Next.js server route that adds
the token, so the token never reaches the browser bundle or network tab. Secrets are never logged, never placed in
prompts, never returned by `/settings`.

## Input validation

- All request bodies and query parameters are Pydantic-validated; errors use the closed error contract.
- SQLAlchemy expressions only (parameterised); no string-built SQL from user input.
- Uploads: allow-list of extensions **and** content signature (`%PDF-`), size cap, UTF-8 enforcement, no binary
  in text files, encrypted/malformed PDFs rejected, filenames sanitised.
- CSV/JSON imports: per-row validation with row/field errors, row cap.

## Prompt-injection defences

1. **Separation** — prompts are built from labelled blocks: SYSTEM INSTRUCTIONS, USER REQUEST, BUSINESS POLICY
   (enforced by software), RETRIEVED EVIDENCE and UNTRUSTED CONTENT. Untrusted text is wrapped in
   `<untrusted_*>` delimiters; look-alike tags inside the text are neutralised so it cannot close its own block.
2. **Detection** — a pattern scanner (override instructions, role hijack, mode switch, prompt probing, approval bypass,
   data exfiltration, delimiter spoofing) flags documents and chunks at ingestion and conversations at analysis.
   Flagged chunks are withheld from model context and shown with a warning.
3. **Capability limits** — the model only proposes. The copilot has read-only tools. Writes go through tools; the
   policy engine decides approval; customer-facing tools verify an approved approval in the database.
4. **Output checks** — claims must be supported by cited passages; email figures must exist in sources; the model can
   set `injection_suspected`, which forces human review.

The demo knowledge base includes a poisoned document to demonstrate this; tests assert it is flagged, retrieved,
withheld, and never reaches a prompt.

## Audit

Append-only `audit_logs`: timestamp, actor (user/agent/system), action, entity, customer, agent, tool, bounded input
and output, approval, result (success/failure/blocked), agent run, trace id, latency. Audit rows are written in the same
transaction as the change they describe.

## Rate limiting

Per-user fixed-window limits (Redis when configured, in-process otherwise) on agent runs, copilot questions and
conversation analysis. Failures fail open: rate limiting protects cost, it must not break the product.

## Not covered (production backlog)

SSO/OIDC, token rotation and expiry, row-level security in Postgres as a second isolation layer, malware scanning of
uploads, data-retention policies, PII redaction before LLM calls.
