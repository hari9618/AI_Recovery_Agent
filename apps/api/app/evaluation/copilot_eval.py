"""Copilot tool-use evaluation (live only: it measures the real model's tool selection).

Runs against the demo tenant; every copilot tool is read-only, so the evaluation cannot change data.
  tool_selection_accuracy   expected tools were called (or any-of set), forbidden tools were not
  tool_argument_accuracy    argument constraints satisfied (e.g. levels include 'critical', owner filter)
  answer_contains           answer mentions expected facts
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.db.session import get_sessionmaker
from app.llm.base import LLMProvider
from app.security.auth import Principal
from app.services.copilot import ask_copilot


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _args_ok(calls: list[dict[str, Any]], checks: dict[str, dict[str, str]]) -> bool:
    for tool, rules in checks.items():
        matching = [c for c in calls if c["tool"] == tool and c.get("arguments") is not None]
        if not matching:
            return False
        ok_any = False
        for c in matching:
            a = c["arguments"]
            ok = True
            if "levels_include" in rules:
                ok &= rules["levels_include"] in (a.get("levels") or ["critical", "high"])
            if "owner_name_contains" in rules:
                ok &= rules["owner_name_contains"] in (a.get("owner_name") or "").lower()
            if "query_contains" in rules:
                ok &= rules["query_contains"] in (a.get("query") or "").lower()
            ok_any |= ok
        if not ok_any:
            return False
    return True


async def run_case(
    case: dict[str, Any], principal: Principal, provider: LLMProvider, company_id: uuid.UUID
) -> dict[str, Any]:
    started = time.perf_counter()
    async with get_sessionmaker()() as s:
        out = await ask_copilot(
            s,
            provider,
            company_id=company_id,
            actor_id=str(principal.user_id),
            actor_name="eval",
            question=case["question"],
        )
        await s.rollback()
    calls = out["tool_calls"]
    called = {c["tool"] for c in calls if c.get("ok")}
    scores: dict[str, Any] = {}
    if case.get("expected_tools_any"):
        selection = bool(called & set(case["expected_tools_any"]))
    else:
        selection = set(case.get("expected_tools", [])) <= called
        if not case.get("expected_tools") and case["key"] in ("out_of_scope",):
            selection = not called
    selection &= not (called & set(case.get("forbidden_tools", [])))
    scores["tool_selection_accuracy"] = selection
    if case.get("arg_checks"):
        scores["tool_argument_accuracy"] = _args_ok(calls, case["arg_checks"])
    if case.get("answer_mentions"):
        scores["answer_contains"] = all(x.lower() in out["answer"].lower() for x in case["answer_mentions"])
    return {
        "case_key": case["key"],
        "description": case["question"],
        "tags": case["tags"],
        "passed": all(scores.values()),
        "scores": scores,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "output": {"answer": out["answer"], "tool_calls": calls, "trace_id": out["trace_id"]},
        "expected": case,
    }
