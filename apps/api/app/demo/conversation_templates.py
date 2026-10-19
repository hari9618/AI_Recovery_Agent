"""Conversation scripts for the synthetic dataset.

Each archetype has several variants. A turn is (sender, day_offset, text). Text placeholders:
{c} contact first name · {r} rep first name · {company} customer short name · {line} product line
{amount} quote value · {quote_no} · {competitor} · {comp_amount} · {target_amount} · {sites} · {city}

The archetype is ground truth only for the generator; the application never reads it. Signals are
re-derived from the text (by the LLM, or the labelled keyword heuristic).
"""

from __future__ import annotations

Turn = tuple[str, float, str]

ARCHETYPES: dict[str, list[list[Turn]]] = {
    "engaged": [
        [
            (
                "customer",
                0,
                "Hi {r}, thanks for the walkthrough yesterday. The team liked the live energy dashboard. Could you share the reference list of plants similar to ours?",
            ),
            (
                "rep",
                0.3,
                "Hi {c}, glad it was useful. Sharing three references in the auto-components space, two of them in {city}. Happy to set up a call with their maintenance heads.",
            ),
            (
                "customer",
                1.2,
                "Perfect. Let's do the reference call next week. Also please include the AMC terms in the proposal.",
            ),
            (
                "rep",
                1.4,
                "Noted — AMC terms will be in the proposal. I'll send two slots for the reference call by tomorrow.",
            ),
        ],
        [
            (
                "rep",
                0,
                "Hi {c}, following up on the site survey at your {city} facility. Our engineer has mapped {sites} panels for metering.",
            ),
            (
                "customer",
                0.5,
                "Thanks {r}. The survey was thorough. Can the gateway work on our existing Wi-Fi or does it need a separate network?",
            ),
            (
                "rep",
                0.7,
                "It supports both. Most customers use a separate VLAN for security; our team can guide your IT.",
            ),
            ("customer", 1.5, "Good. Please go ahead and prepare the proposal for {sites} sites."),
        ],
    ],
    "quote_question": [
        [
            (
                "rep",
                0,
                "Hi {c}, please find attached quotation {quote_no} for {line} at {amount}. Happy to walk you through it.",
            ),
            (
                "customer",
                2,
                "Hi {r}, received the quote. Could you clarify whether installation includes cabling to the panels, and what the payment terms are?",
            ),
            (
                "customer",
                4,
                "Hi {r}, any update on my question about cabling and payment terms? We need to put this up for approval.",
            ),
        ],
        [
            (
                "rep",
                0,
                "Dear {c}, sharing quotation {quote_no} ({amount}) as discussed. The quote is valid for 30 days.",
            ),
            (
                "customer",
                1.5,
                "Thanks. Is the Pulse platform licence per site or per user? And can we start with one site and expand?",
            ),
        ],
    ],
    "price_objection": [
        [
            ("rep", 0, "Hi {c}, attaching quotation {quote_no} for {amount}. Let me know if you have any questions."),
            (
                "customer",
                2,
                "Hi {r}, we went through the quote internally. Honestly the price is higher than what we budgeted. Our approved budget is around {target_amount}. Is there any flexibility?",
            ),
            ("rep", 2.5, "Understood {c}. Let me check internally what we can do and get back to you."),
            (
                "customer",
                5,
                "Hi {r}, just checking — were you able to look at the pricing? Management wants a revised number before the review.",
            ),
        ],
        [
            (
                "customer",
                0,
                "Hi {r}, the proposal looks good technically but the cost is too high for us right now. Can you revise it?",
            ),
            ("rep", 0.4, "Hi {c}, thanks for being upfront. Could you share which line items are the concern?"),
            (
                "customer",
                1.0,
                "Mainly the platform subscription. {amount} is a stretch; we were expecting something closer to {target_amount}.",
            ),
        ],
    ],
    "competitor": [
        [
            ("rep", 0, "Hi {c}, sharing quotation {quote_no} at {amount} for {sites} sites."),
            (
                "customer",
                2,
                "Hi {r}, thanks. Can you help us understand why your quote is higher than others? We need to justify it to management.",
            ),
            (
                "customer",
                3,
                "Also to be transparent, {competitor} has quoted {comp_amount} for a similar scope. We actually prefer your dashboard and the alerts, but the gap is significant. We'd like to close this by month end.",
            ),
        ],
        [
            (
                "customer",
                0,
                "{r}, we are evaluating {competitor} as well. Their sales team offered free installation. What can you offer?",
            ),
            (
                "rep",
                0.5,
                "Thanks for sharing, {c}. Our installation includes commissioning and operator training, which is different from a basic install. Can we set up a call to compare scopes?",
            ),
            ("customer", 2.0, "Sure, but we need the comparison by Friday. Decision meeting is next week."),
        ],
    ],
    "unanswered": [
        [
            ("rep", 0, "Hi {c}, it was great meeting you at the plant. I'll share the proposal shortly."),
            (
                "customer",
                1,
                "Hi {r}, we're keen to move ahead. Could you send the proposal and a tentative installation timeline? We'd like to complete installation before the next quarter.",
            ),
        ],
        [
            (
                "customer",
                0,
                "Hi, we got your details from our sister plant in {city}. We need energy monitoring for {sites} sites. Who can we talk to?",
            ),
            ("rep", 0.2, "Hi {c}, this is {r} from Arcline. Happy to help — could we do a 30-minute call this week?"),
            (
                "customer",
                0.9,
                "Thursday 3 pm works. Please also send a rough budgetary estimate before the call if possible.",
            ),
        ],
    ],
    "ghosting": [
        [
            (
                "rep",
                0,
                "Hi {c}, sharing the proposal for {line} ({amount}). Would you have 20 minutes this week to discuss?",
            ),
            ("rep", 5, "Hi {c}, just following up on the proposal. Let me know a convenient time."),
            (
                "customer",
                9,
                "Hi {r}, sorry for the delay. This is not a priority right now. We will get back if things change.",
            ),
        ],
        [
            ("rep", 0, "Hi {c}, checking in on the monitoring project we discussed."),
            ("customer", 3, "We are still evaluating internally. No timeline yet."),
            ("rep", 8, "Thanks {c}. Shall I check back next month?"),
        ],
    ],
    "high_intent": [
        [
            (
                "customer",
                0,
                "Hi {r}, we had a breakdown on one of our compressors last week and management wants condition monitoring installed urgently. Can you share the final quote and the PO format?",
            ),
            (
                "rep",
                0.3,
                "Hi {c}, sorry to hear about the breakdown. Sending the final quote {quote_no} for {amount} today along with our PO details.",
            ),
            (
                "customer",
                1.0,
                "Received. We'd like to go ahead. Please confirm the earliest installation date — we are ready to raise the PO this week.",
            ),
        ],
    ],
    "timing_delay": [
        [
            ("rep", 0, "Hi {c}, following up on quotation {quote_no} for {amount}."),
            (
                "customer",
                2,
                "Hi {r}, the proposal is fine but our capex budget for this year is exhausted. We may take it up in the next quarter.",
            ),
            (
                "rep",
                2.4,
                "Understood, {c}. Would a phased rollout starting with one site help within the current budget?",
            ),
        ],
    ],
    "won": [
        [
            ("rep", 0, "Hi {c}, sharing the revised quotation {quote_no} for {amount} as agreed."),
            ("customer", 1, "Thanks {r}. Approved. PO will be issued today."),
            ("rep", 1.2, "Thank you {c}! Our projects team will reach out to schedule installation."),
        ],
    ],
    "lost": [
        [
            ("rep", 0, "Hi {c}, any update on the proposal for {line}?"),
            (
                "customer",
                4,
                "Hi {r}, we have decided to go with {competitor} as their price was lower. Thanks for your time.",
            ),
        ],
        [
            ("rep", 0, "Hi {c}, checking in on the monitoring proposal."),
            ("rep", 7, "Hi {c}, following up again — let me know if the requirement is still active."),
            ("customer", 20, "The project has been put on hold indefinitely. We'll reach out if it restarts."),
        ],
    ],
    "account_management": [
        [
            (
                "customer",
                0,
                "Hi {r}, our AMC is due for renewal next month. Can you send the renewal quote? Also, two TH-05 sensors are showing intermittent readings.",
            ),
            ("rep", 0.5, "Hi {c}, I'll share the renewal quote today and have support check the sensors remotely."),
            ("customer", 1.5, "Thanks, support has fixed the issue. Waiting for the renewal quote."),
        ],
    ],
}

# Which archetypes can apply to which open stage (generator picks from these).
STAGE_ARCHETYPES: dict[str, tuple[str, ...]] = {
    "prospecting": ("engaged", "unanswered", "ghosting"),
    "qualification": ("engaged", "unanswered", "ghosting", "timing_delay"),
    "proposal": (
        "quote_question",
        "price_objection",
        "competitor",
        "ghosting",
        "high_intent",
        "timing_delay",
        "engaged",
    ),
    "negotiation": ("price_objection", "competitor", "quote_question", "high_intent", "engaged", "timing_delay"),
}

SUBJECTS: dict[str, tuple[str, ...]] = {
    "engaged": ("Monitoring rollout — next steps", "Site survey follow-up"),
    "quote_question": ("Clarification on quotation", "Questions on proposal"),
    "price_objection": ("Revised pricing request", "Budget for monitoring project"),
    "competitor": ("Quote comparison", "Vendor evaluation"),
    "unanswered": ("Proposal and installation timeline", "New enquiry — energy monitoring"),
    "ghosting": ("Following up on proposal", "Monitoring project check-in"),
    "high_intent": ("URGENT: condition monitoring", "PO and installation date"),
    "timing_delay": ("Budget timing", "Proposal status"),
    "won": ("Purchase order", "Approved — PO"),
    "lost": ("Proposal status", "Update on evaluation"),
    "account_management": ("AMC renewal", "Renewal and support"),
}
