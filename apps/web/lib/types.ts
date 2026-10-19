/** Response shapes of the FastAPI backend (subset used by the UI). */

export type RiskLevel = "low" | "medium" | "high" | "critical"

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Reason {
  code: string
  label: string
  points: number
  source: "crm_data" | "llm_analysis" | "keyword_heuristic" | "none"
  evidence: Record<string, unknown> & { excerpt?: string }
}

export interface RiskItem {
  risk_id: string
  opportunity_id: string
  opportunity_name: string
  customer_id: string
  customer_name: string
  industry: string
  owner: string | null
  stage: string
  deal_value: number
  risk_score: number
  risk_level: RiskLevel
  revenue_at_risk: number
  weighted_revenue_at_risk: number
  purchase_probability: number
  reasons: Reason[]
  recommended_next_step: string
  computed_at: string
  latest_recommendation_status: string | null
}

export interface DashboardSummary {
  data_provenance: "synthetic_demo" | "observed"
  currency: string
  risk_computed_at: string | null
  cache?: string
  kpis: {
    revenue_at_risk: number
    weighted_revenue_at_risk: number
    revenue_recovered: number
    recovered_deals: number
    high_risk_opportunities: number
    critical_opportunities: number
    overdue_followups: number
    unanswered_leads: number
    open_pipeline_value: number
    ai_recommendations: number
    ai_actions: number
    automation_success_rate: number | null
    pending_approvals: number
  }
  risk_distribution: Record<RiskLevel, { count: number; revenue_at_risk: number; deal_value: number }>
  risk_reasons: Record<string, { count: number; revenue_at_risk: number }>
  reps: { owner: string; at_risk_deals: number; revenue_at_risk: number; overdue_followups: number }[]
  top_risks: RiskItem[]
  actions: { total: number; by_status: Record<string, number>; automation_success_rate: number | null }
}

export interface Me {
  user_id: string
  name: string
  role: string
  company: { id: string; name: string; currency: string; is_demo: boolean }
}

export interface Objection {
  type: string
  detail: string
  quote: string
}

export interface ConversationInsight {
  intent: "high" | "medium" | "low"
  buying_stage: string
  urgency: string
  budget_signal: string
  objections: Objection[]
  competitor_mentions: { name: string; context: string }[]
  decision_maker_status: string
  customer_waiting_on: string | null
  next_action: string
  sentiment: string
  summary: string
  evidence_quotes: string[]
  confidence: number
  _dropped_quotes?: string[]
}

export interface EvidenceItem {
  kind: "risk_engine" | "conversation" | "knowledge"
  label: string
  quote?: string | null
  points?: number
  source?: string
  evidence_id?: string
  source_document?: string
  source_section?: string
  version?: string
  retrieval_score?: number
  cited?: boolean
}

export interface PolicyReason {
  rule: string
  message: string
  required_role: string | null
  blocking: boolean
}

export interface Recommendation {
  id: string
  opportunity_id: string
  customer_id: string
  customer_name?: string
  deal_value?: number
  risk_level?: RiskLevel | null
  risk_score?: number | null
  agent_run_id: string | null
  action_type: string
  status: string
  title: string
  what_happened: string
  why_risky: string
  recommendation: string
  expected_outcome: string
  evidence: EvidenceItem[]
  proposed_action: {
    primary?: { action_type: string; discount_pct?: number | null; email_subject?: string | null; email_body?: string | null; to?: string | null }
    internal?: { action_type: string; title: string; due_in_hours: number }[]
  }
  draft_subject: string | null
  draft_body: string | null
  confidence: number
  requires_approval: boolean
  approval_reasons: PolicyReason[]
  grounding: {
    claims?: { claim: string; supported: boolean; source_document: string | null; source_section: string | null; support_score: number; problems: string[] }[]
    supported?: number
    total?: number
    unverified_count?: number
    unsupported_numbers_in_email?: string[]
    grounding_score?: number | null
  }
  limitations: string[]
  generated_by: string
  model: string | null
  trace_id: string | null
  created_at: string
  approval?: Approval | null
  actions?: { id: string; action_type: string; status: string; automated: boolean; result: Record<string, unknown>; executed_at: string | null; error: string | null }[]
}

export interface Approval {
  id: string
  recommendation_id: string
  status: "pending" | "approved" | "rejected"
  reasons: PolicyReason[]
  risk_summary: string
  required_role: string
  decided_by: string | null
  decided_by_name?: string | null
  decided_at: string | null
  decision_note: string | null
  edited_payload: Record<string, unknown> | null
  created_at: string
  customer_name?: string
  deal_value?: number
  recommendation?: Recommendation
}

export interface RunStep {
  node: string
  status: "running" | "completed" | "failed"
  started_at: string
  latency_ms?: number
  summary?: string | null
  error?: string
}

export interface RunState {
  risk_analysis?: { risk_level: RiskLevel; risk_score: number; revenue_at_risk: number; reasons: Reason[] }
  retrieval_queries?: { query: string; reason: string; doc_types: string[] }[]
  withheld_evidence?: { document: string; section: string; reason: string }[]
  execution_result?: { ok: boolean; results: { tool: string; ok: boolean; data?: { detail?: Record<string, unknown> }; error?: { message?: string } | null }[] }
  verification_result?: { all_passed: boolean; checks: { check: string; passed: boolean }[] }
  limitations?: string[]
  [key: string]: unknown
}

export interface AgentRun {
  id: string
  opportunity_id: string | null
  customer_id: string | null
  customer_name: string | null
  workflow: string
  status: "running" | "awaiting_approval" | "completed" | "needs_review" | "failed"
  steps: RunStep[]
  error: string | null
  trace_id: string | null
  trace_url: string | null
  llm_calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  latency_ms: number | null
  created_at: string
  finished_at: string | null
  state?: RunState
  recommendation?: Recommendation | null
  approval?: Approval | null
}

export interface ConversationAnalysisSummary {
  source: "llm_analysis" | "keyword_heuristic"
  status: string | null
  intent?: string
  summary?: string
  [key: string]: unknown
}

export interface RiskSignals {
  probability_breakdown?: { stage_base: number; historical_calibration: number; intent_multiplier: number }
  [key: string]: unknown
}

export interface CustomerProfile {
  customer: {
    id: string
    name: string
    industry: string
    segment: string
    status: string
    city: string | null
    state: string | null
    website: string | null
    employee_count: number | null
    lifetime_value: number | null
    owner: string | null
    is_synthetic: boolean
  }
  summary: {
    deal_value: number | null
    open_pipeline_value: number
    lead_stage: string | null
    intent: string
    intent_source: string
    purchase_probability: number | null
    revenue_risk: RiskLevel | null
    risk_score: number | null
    revenue_at_risk: number
    last_contact_days: number | null
    last_quote_value: number | null
    last_quote_status: string | null
    main_objection: string | null
    competitor_mentioned: boolean
    competitors: { name: string; context: string }[]
    objections: Objection[]
    ai_summary: string | null
    recommended_action: string | null
  }
  contacts: { id: string; name: string; title: string | null; email: string | null; phone: string | null; is_decision_maker: boolean }[]
  opportunities: { id: string; name: string; stage: string; amount: number; expected_close_date: string | null; last_activity_at: string | null; competitor: string | null; loss_reason: string | null }[]
  quotes: { id: string; quote_number: string; version: number; status: string; subtotal: number; discount_pct: number; total: number; sent_at: string | null; valid_until: string | null; opportunity_id: string; items: { sku: string; description: string; quantity: number; unit_price: number; line_total: number }[] }[]
  conversations: { id: string; channel: string; subject: string | null; opportunity_id: string | null; started_at: string; last_message_at: string; last_sender: string; message_count: number; analysis: ConversationAnalysisSummary }[]
  risks: { id: string; opportunity_id: string; risk_score: number; risk_level: RiskLevel; revenue_at_risk: number; weighted_revenue_at_risk: number; purchase_probability: number; reason_codes: Reason[]; recommended_next_step: string; signals: RiskSignals; computed_at: string; engine_version: string }[]
  recommendations: Recommendation[]
  followups: { id: string; title: string; due_at: string; status: string; overdue: boolean; created_by_agent: boolean }[]
  timeline: { id: string; type: string; description: string; occurred_at: string }[]
  audit: AuditEntry[]
}

export interface AuditEntry {
  id: string
  occurred_at: string
  actor_type: "user" | "agent" | "system"
  actor_id: string | null
  actor_name: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  customer_id: string | null
  customer_name?: string | null
  agent: string | null
  tool: string | null
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  approval_request_id: string | null
  result: "success" | "failure" | "blocked" | "pending"
  agent_run_id: string | null
  trace_id: string | null
  latency_ms: number | null
}

export interface KnowledgeDoc {
  id: string
  title: string
  document_type: string
  version: string
  source: string
  mime_type: string
  status: string
  chunk_count: number
  char_count: number
  injection_findings: { pattern: string; excerpt: string }[]
  is_active: boolean
  created_at: string
  error: string | null
}

export interface RetrievedEvidence {
  evidence_id: string
  chunk_id: string
  document_title: string
  document_type: string
  section: string
  version: string
  content: string
  flagged_injection: boolean
  scores: { rrf: number; bm25_rank: number | null; vector_rank: number | null; rerank: number | null }
  retrieval_score: number
}

export interface GroundedAnswer {
  question: string
  status: "ANSWERED" | "PARTIALLY_SUPPORTED" | "INSUFFICIENT_EVIDENCE" | "LLM_FALLBACK"
  answer: string
  claims: { claim: string; supported: boolean; evidence_id: string | null; source_document: string | null; source_section: string | null; retrieval_score: number | null; support_score: number; problems: string[] }[]
  grounding_score: number
  evidence: RetrievedEvidence[]
  withheld_evidence: { evidence_id: string; document: string; section: string; reason: string }[]
  limitations: string[]
  model: string | null
}

export interface EvalRun {
  id: string
  suite: "rag" | "agent" | "copilot"
  mode: "live" | "offline"
  dataset_version: string
  model: string | null
  status: string
  metrics: Record<string, { value: number; n: number; description?: string }>
  cases_total: number
  cases_passed: number
  report_path: string | null
  notes: string | null
  is_demo_data: boolean
  created_at: string
  finished_at: string | null
  results?: { case_key: string; description: string; tags: string[]; passed: boolean | null; scores: Record<string, unknown>; expected: Record<string, unknown>; output: Record<string, unknown>; error: string | null; latency_ms: number | null }[]
}
