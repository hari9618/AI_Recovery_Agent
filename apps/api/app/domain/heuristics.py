"""Keyword heuristics for conversation signals — the *fallback* when no LLM analysis exists.

These are deliberately simple, deterministic and labelled `keyword_heuristic` wherever they surface,
so nobody mistakes them for model output. They let the risk engine run on a fresh dataset (or with
no LLM configured) and they give the evaluation suite a baseline to compare the LLM against.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_PRICE = re.compile(
    r"(price is (?:too )?high|higher than (?:what )?(?:we|our|others)|too expensive|cost is too high|"
    r"better on (?:the )?price|flexibility|revised (?:number|price|pricing)|over (?:our )?budget|"
    r"budget(?:ed)? (?:is )?(?:around|only)|approved budget|a stretch|reduce the (?:price|cost))",
    re.I,
)
_COMPETITOR = re.compile(
    r"(competitor|another vendor|other vendors?|(?:has|have) quoted|quoted us|evaluating [A-Z][\w]+|"
    r"decided to go with|go(?:ing)? with [A-Z][\w]+|their (?:price|sales team|quote))",
    re.I,
)
_HIGH_INTENT = re.compile(
    r"(go ahead|raise the PO|PO (?:format|details|will be issued)|ready to|keen to|urgent(?:ly)?|"
    r"installation (?:date|timeline)|close this|finali[sz]e|decision meeting|want(?:s)? this live|move ahead)",
    re.I,
)
_LOW_INTENT = re.compile(
    r"(not a priority|on hold|no timeline|budget (?:for this year )?is exhausted|next quarter|"
    r"get back if|still evaluating internally|deprioriti[sz]ed)",
    re.I,
)
_NEGATIVE = re.compile(r"(disappointed|not happy|frustrat|unacceptable|poor service|still waiting|any update)", re.I)
_POSITIVE = re.compile(r"(thanks|great|perfect|liked|looks good|glad|prefer your)", re.I)


@dataclass
class HeuristicSignals:
    intent: str = "unknown"
    price_objection: bool = False
    competitor_mentioned: bool = False
    competitors: list[str] = field(default_factory=list)
    sentiment: str = "unknown"
    evidence: dict[str, str] = field(default_factory=dict)


def _excerpt(text: str, match: re.Match[str], width: int = 90) -> str:
    start = max(match.start() - width // 2, 0)
    snippet = text[start : match.end() + width // 2].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if match.end() + width // 2 < len(text) else "")


def analyze_customer_messages(messages: Iterable[str], known_competitors: Iterable[str] = ()) -> HeuristicSignals:
    """Derive signals from the customer's own messages (rep messages are ignored)."""
    out = HeuristicSignals()
    texts = [t for t in messages if t]
    if not texts:
        return out
    competitor_names = list(known_competitors)
    high = low = neg = pos = 0
    for text in texts:
        if m := _PRICE.search(text):
            out.price_objection = True
            out.evidence.setdefault("PRICE_OBJECTION", _excerpt(text, m))
        if m := _COMPETITOR.search(text):
            out.competitor_mentioned = True
            out.evidence.setdefault("COMPETITOR_MENTIONED", _excerpt(text, m))
        for name in competitor_names:
            if name.lower() in text.lower():
                out.competitor_mentioned = True
                if name not in out.competitors:
                    out.competitors.append(name)
        high += len(_HIGH_INTENT.findall(text))
        low += len(_LOW_INTENT.findall(text))
        neg += len(_NEGATIVE.findall(text))
        pos += len(_POSITIVE.findall(text))
    if high > low:
        out.intent = "high"
    elif low > 0:
        out.intent = "low"
    else:
        out.intent = "medium"
    if neg > pos:
        out.sentiment = "negative"
    elif pos > 0:
        out.sentiment = "positive"
    else:
        out.sentiment = "neutral"
    return out
