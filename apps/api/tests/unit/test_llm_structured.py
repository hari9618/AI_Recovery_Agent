import json

import pytest

from app.core.errors import ErrorCode, LLMError
from app.domain.conversation import ConversationInsight
from app.domain.enums import LLMCallStatus
from app.llm.base import ChatMessage
from app.llm.schema import strict_json_schema
from app.llm.structured import generate_structured, parse_json_object
from tests.fakes import ScriptedLLM

VALID = {
    "intent": "high",
    "buying_stage": "decision",
    "urgency": "medium",
    "budget_signal": "constrained",
    "objections": [{"type": "price", "detail": "Wants a lower price", "quote": "can you do better on the price?"}],
    "competitor_mentions": [{"name": "Voltrix Systems", "context": "quoted 4.1L"}],
    "decision_maker_status": "engaged",
    "customer_waiting_on": "revised price",
    "next_action": "send_revised_quote",
    "sentiment": "positive",
    "summary": "Customer wants to buy but needs a better price.",
    "evidence_quotes": ["can you do better on the price?"],
    "confidence": 0.9,
}
MSGS = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="transcript")]
FENCE = "`" * 3


async def test_valid_first_attempt_is_ok():
    llm = ScriptedLLM([VALID])
    res = await generate_structured(llm, MSGS, ConversationInsight, purpose="t")
    assert res.ok and res.status == LLMCallStatus.OK and res.attempts == 1
    assert res.value.has_price_objection and res.value.competitor_names == ["Voltrix Systems"]


async def test_invalid_output_is_repaired_with_error_feedback():
    bad = dict(VALID, intent="very high", confidence=3)
    fenced = f"{FENCE}json\n{json.dumps(VALID)}\n{FENCE}"
    llm = ScriptedLLM([bad, fenced])
    res = await generate_structured(llm, MSGS, ConversationInsight, purpose="t")
    assert res.status == LLMCallStatus.REPAIRED and res.attempts == 2
    repair_msg = llm.calls[1]["messages"][-1].content
    assert "intent" in repair_msg and "confidence" in repair_msg
    assert res.usage.input_tokens == 200


async def test_persistent_garbage_falls_back_never_accepts_malformed():
    llm = ScriptedLLM(["not json", "{}", '{"intent": "high"}'])
    fb = ConversationInsight.model_validate(dict(VALID, summary="FALLBACK", confidence=0.0))
    res = await generate_structured(llm, MSGS, ConversationInsight, purpose="t", fallback=lambda: fb)
    assert res.status == LLMCallStatus.FALLBACK and not res.ok
    assert res.value.summary == "FALLBACK"
    assert len(res.errors) == 3


async def test_fallback_without_factory_returns_none():
    res = await generate_structured(ScriptedLLM(["x", "y", "z"]), MSGS, ConversationInsight, purpose="t")
    assert res.value is None and res.status == LLMCallStatus.FALLBACK


async def test_transport_errors_propagate():
    llm = ScriptedLLM([LLMError(ErrorCode.LLM_TIMEOUT, "slow")])
    with pytest.raises(LLMError) as exc:
        await generate_structured(llm, MSGS, ConversationInsight, purpose="t")
    assert exc.value.retryable


async def test_provider_side_schema_rejection_is_repaired():
    llm = ScriptedLLM([LLMError(ErrorCode.LLM_INVALID_OUTPUT, "json_validate_failed"), VALID])
    res = await generate_structured(llm, MSGS, ConversationInsight, purpose="t")
    assert res.status == LLMCallStatus.REPAIRED


def test_parse_json_object_strips_prose_and_fences():
    assert parse_json_object(f'Sure! {FENCE}json\n{{"a": 1}}\n{FENCE}') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("[1,2]")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_strict_schema_meets_strict_mode_rules():
    schema = strict_json_schema(ConversationInsight)
    for node in _walk(schema):
        assert "$ref" not in node and "minimum" not in node and "title" not in node
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
