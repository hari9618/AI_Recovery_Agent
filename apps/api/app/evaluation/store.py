"""Persist evaluation runs (DB + JSON experiment + Markdown report) and push scores to Langfuse."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import REPO_ROOT
from app.db import models as m
from app.db.session import get_sessionmaker
from app.domain.enums import EvalMode, EvalSuite
from app.observability.tracing import get_tracer

EXPERIMENTS = REPO_ROOT / "evals" / "experiments"
REPORTS = REPO_ROOT / "evals" / "reports"

DESCRIPTIONS = {
    "workflow_completion": "Run ended in the expected (or expected graceful) state",
    "risk_detection_accuracy": "Deterministic risk level and reason codes as expected",
    "approval_compliance": "Approval routing matches policy",
    "policy_compliance": "Expected policy rules fired; no customer-facing action ran without approval",
    "tool_selection_accuracy": "Expected tools were called",
    "tool_argument_accuracy": "Key tool arguments were correct",
    "database_update_correctness": "Database state after run/decision matches expectations",
    "hallucination_detection": "Injected hallucinations were caught by grounding checks",
    "hallucination_rate": "Unverified claims / total policy claims (lower is better)",
    "failure_recovery": "Injected failures degraded gracefully",
    "case_pass_rate": "Cases with every applicable check passing",
    "retrieval_hit_rate": "Expected source passage retrieved in top-k",
    "retrieval_mrr": "Mean reciprocal rank of the expected passage",
    "insufficient_evidence_accuracy": "Unanswerable questions answered with INSUFFICIENT_EVIDENCE",
    "injection_withholding": "Poisoned passages withheld from the LLM when retrieved",
    "injection_resistance": "Answers never repeat injected instructions",
    "policy_fact_accuracy": "Answer contains the required policy facts",
    "citation_accuracy": "Supported claims cite the expected source documents",
    "grounding_score": "Share of claims verified against cited passages",
    "answered_rate": "Answerable questions that received an answer",
    "ragas_faithfulness": "Ragas: claims in the answer supported by retrieved context",
    "ragas_answer_relevancy": "Ragas: answer addresses the question",
    "ragas_context_precision": "Ragas: relevant passages ranked above irrelevant ones (vs reference)",
    "ragas_context_recall": "Ragas: reference facts covered by retrieved context",
    "answer_contains": "Copilot answer mentions expected facts",
}


async def save_run(*, suite: EvalSuite, mode: EvalMode, dataset_version: str, model: str | None, results: list[dict[str, Any]],
                   metrics: dict[str, Any], notes: str, company_id: Any = None) -> dict[str, Any]:
    for name, metric in metrics.items():
        metric.setdefault("description", DESCRIPTIONS.get(name, ""))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    EXPERIMENTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    experiment = EXPERIMENTS / f"{stamp}_{suite.value}_{mode.value}.json"
    experiment.write_text(json.dumps({"suite": suite.value, "mode": mode.value, "dataset_version": dataset_version, "model": model,
                                      "metrics": metrics, "results": results}, indent=1, default=str), encoding="utf-8")
    report = REPORTS / f"latest_{suite.value}_{mode.value}.md"
    report.write_text(render_markdown(suite, mode, dataset_version, model, metrics, results, notes, stamp), encoding="utf-8")

    async with get_sessionmaker()() as s:
        run = m.EvaluationRun(company_id=company_id, suite=suite, mode=mode, dataset_version=dataset_version, model=model,
                              status="completed", metrics=metrics, cases_total=len(results),
                              cases_passed=sum(1 for r in results if r.get("passed")), report_path=str(report.relative_to(REPO_ROOT)),
                              notes=notes, is_demo_data=True, finished_at=datetime.now(UTC))
        s.add(run)
        await s.flush()
        for r in results:
            case = await s.scalar(select(m.EvaluationCase).where(m.EvaluationCase.suite == suite, m.EvaluationCase.case_key == r["case_key"]))
            if case is None:
                case = m.EvaluationCase(suite=suite, case_key=r["case_key"], description=r["description"],
                                        input={}, expected=json.loads(json.dumps(r.get("expected", {}), default=str)), tags=r.get("tags", []))
                s.add(case)
                await s.flush()
            s.add(m.EvaluationResult(run_id=run.id, case_id=case.id, passed=r.get("passed"), scores=json.loads(json.dumps(r["scores"], default=str)),
                                     output=json.loads(json.dumps(r["output"], default=str)), latency_ms=r.get("latency_ms")))
        await s.commit()
        run_id = str(run.id)

    tracer = get_tracer()
    for r in results:
        trace_id = (r.get("output") or {}).get("trace_id")
        if trace_id and r.get("passed") is not None:
            tracer.score_trace(trace_id, f"eval_{suite.value}_passed", 1.0 if r["passed"] else 0.0, comment=r["case_key"])
    tracer.flush()
    return {"run_id": run_id, "report": str(report), "experiment": str(experiment)}


def render_markdown(suite: EvalSuite, mode: EvalMode, version: str, model: str | None, metrics: dict[str, Any],
                    results: list[dict[str, Any]], notes: str, stamp: str) -> str:
    label = "LIVE (real Groq calls)" if mode == EvalMode.LIVE else "OFFLINE (scripted LLM — tests orchestration, guardrails and DB effects, not model quality)"
    lines = [f"# Evaluation report — {suite.value}", "", f"- **Mode:** {label}", f"- **Dataset:** {version}",
             f"- **Model:** {model or 'n/a'}", f"- **Run at:** {stamp} (UTC)", "- **Data:** synthetic demo data", f"- **Notes:** {notes}", "",
             "## Metrics", "", "| Metric | Value | n | Meaning |", "|---|---|---|---|"]
    for name, metric in metrics.items():
        lines.append(f"| {name} | {metric['value']:.3f} | {metric['n']} | {metric.get('description', '')} |")
    passed = sum(1 for r in results if r.get("passed"))
    lines += ["", f"## Cases ({passed}/{len(results)} passed)", "", "| Case | Result | Failed checks |", "|---|---|---|"]
    for r in results:
        failed = [k for k, v in r["scores"].items() if v is False]
        mark = "PASS" if r.get("passed") else ("n/a" if r.get("passed") is None else "FAIL")
        lines.append(f"| {r['case_key']} | {mark} | {', '.join(failed)} |")
    return "\n".join(lines) + "\n"
