# The business problem

## How revenue leaks

```
lead arrives → rep contacts customer → quotation sent → customer asks a question
→ rep gets busy → follow-up forgotten → customer goes quiet → customer buys from a competitor
```

Nothing in this chain fails loudly. The CRM still shows the deal as "Proposal". The owner learns about it at
quarter-end, if at all.

## Who has the problem

SMB and mid-market B2B sellers with inbound leads and quotations: industrial suppliers, agencies, contractors,
service businesses, SaaS with sales-led onboarding. Typically 3–30 sales reps, one sales manager, an owner who wants
to know where money is slipping.

## Questions the product answers

| Question | Where it is answered | How |
|---|---|---|
| Which opportunities are at risk, why, how much? | Dashboard, Revenue Risks | Deterministic risk engine with reason codes |
| Which quotes are going cold? | Risk reasons `QUOTE_UNANSWERED`, `QUOTE_EXPIRING`, `QUOTE_EXPIRED` | Quote dates from CRM |
| Which customers showed strong buying intent? | Customer intelligence, `HIGH_INTENT_STALLED` | LLM conversation analysis (heuristic fallback) |
| Which customers are waiting on us? | `CUSTOMER_AWAITING_REPLY` | Last customer message after last rep touch |
| Which reps are missing follow-ups? | Dashboard rep table | Overdue tasks + at-risk revenue per owner |
| What should happen next, and what should we say? | Recommendations | Agent: grounded recommendation + draft |
| What can be automated, what needs approval? | Approval Center | Deterministic policy engine |
| Did it work? | ROI, Evaluations | Observed recovered revenue; measured eval metrics |

## The demo company

**Arcline Systems** (fictional) sells industrial monitoring hardware (gateways, energy meters, vibration and
temperature sensors), the Pulse SaaS platform, installation and AMC to manufacturers, hospitals, hotels, warehouses
and others across India, priced in INR. The engines are domain-agnostic; only the synthetic dataset and the policy
documents are specific to Arcline.

## Primary scenario — Vertex Industrial Solutions

| Day | Event |
|---|---|
| 1 | Inbound lead: monitoring for 3 plants |
| 2 | Discovery call with the plant head |
| 3 | Quotation ₹4,80,000 sent (valid 21 days) |
| 5 | "Can you do better on the price? Our approved budget is around ₹4,30,000." |
| 6 | "Voltrix Systems has quoted ₹4,10,000… we prefer your dashboard… finalise by month end." |
| 9 | No reply from sales; follow-up task overdue |

The risk engine scores it **94/100 CRITICAL**: customer waiting (+20), no contact for 7 days (+18), overdue follow-up
(+12), quote unanswered (+10), competitor (+10), high intent stalled (+10), price objection (+8), late stage (+6).
The agent retrieves the discount authority and competitor-objection policies, recommends a value-based reply with a
discount request, and routes it to the sales manager because 12% exceeds the rep's 10% limit and the deal is
high-value. The manager approves at 10%; the revised quote (₹4,32,000) is computed by software.
