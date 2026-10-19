"""Evaluation runner.

    uv run --project apps/api python -m evals.run                      # all suites; live where an LLM is configured
    uv run --project apps/api python -m evals.run --suite agent --mode offline
    uv run --project apps/api python -m evals.run --suite rag --mode live --limit 10

Modes
  offline  no LLM calls. RAG: retrieval metrics. Agent: scripted LLM (tests orchestration/guardrails/DB effects).
  live     real Groq calls. RAG: grounded answers + Ragas judge. Agent: real model. Copilot: real tool calling.
  auto     live if GROQ_API_KEY/GROQ_MODEL are set, otherwise offline (copilot is skipped offline).

Results go to evals/experiments/*.json, evals/reports/latest_<suite>_<mode>.md, the evaluation_* tables
(shown in the app's Evaluations page) and, if configured, Langfuse scores. Numbers are only ever measured.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import models as m
from app.db.session import get_engine, get_sessionmaker
from app.domain.enums import EvalMode, EvalSuite, UserRole
from app.domain.settings import CompanySettings
from app.evaluation import agent_eval, copilot_eval, rag_eval
from app.evaluation.sandbox import create_sandbox
from app.evaluation.store import save_run
from app.llm.factory import get_llm_provider
from app.rag.models import get_embedder, get_reranker
from app.rag.retriever import HybridRetriever
from app.security.auth import Principal

DATASETS = Path(__file__).resolve().parent / "datasets"
log = logging.getLogger("evals")


def _print(title: str, metrics: dict, saved: dict) -> None:
    print(f"\n== {title} ==")
    for name, metric in metrics.items():
        print(f"  {name:32} {metric['value']:.3f}  (n={metric['n']})")
    print(f"  report: {saved['report']}")


async def run_agent(mode: EvalMode, limit: int | None) -> None:
    version, cases = agent_eval.load_cases(DATASETS / "agent_scenarios_v1.json")
    cases = cases[:limit] if limit else cases
    live_provider = get_llm_provider() if mode == EvalMode.LIVE else None
    async with get_sessionmaker()() as s:
        sandbox = await create_sandbox(s, get_embedder())
    results = []
    for i, case in enumerate(cases, start=1):
        try:
            results.append(await agent_eval.run_case(case, sandbox, live_provider=live_provider, settings=CompanySettings()))
        except Exception as exc:  # noqa: BLE001 - an evaluator crash is a failed case, never a skipped one
            log.exception("case crashed", extra={"case": case["key"]})
            results.append({"case_key": case["key"], "description": case["description"], "tags": case["tags"], "passed": False,
                            "scores": {"workflow_completion": False}, "output": {"error": f"{exc.__class__.__name__}: {exc}"},
                            "expected": case["expected"], "latency_ms": None})
        mark = "PASS" if results[-1]["passed"] else "FAIL"
        print(f"  [{i:02d}/{len(cases)}] {mark} {case['key']}", flush=True)
    metrics = agent_eval.aggregate(results, live=mode == EvalMode.LIVE)
    note = ("Scripted LLM outputs per scenario; measures workflow, guardrails, tool use and DB effects deterministically."
            if mode == EvalMode.OFFLINE else "Real model outputs; approval compliance checked by independent policy re-evaluation.")
    saved = await save_run(suite=EvalSuite.AGENT, mode=mode, dataset_version=version,
                           model=None if mode == EvalMode.OFFLINE else get_settings().groq_model, results=results, metrics=metrics, notes=note)
    _print(f"agent ({mode.value})", metrics, saved)


async def run_rag(mode: EvalMode, limit: int | None, use_ragas: bool) -> None:
    questions = rag_eval.load_questions(DATASETS / "rag_v1.jsonl")
    questions = questions[:limit] if limit else questions
    async with get_sessionmaker()() as s:
        sandbox = await create_sandbox(s, get_embedder())
    retriever = HybridRetriever(get_embedder(), get_reranker())
    results = []
    if mode == EvalMode.OFFLINE:
        for q in questions:
            results.append(await rag_eval.run_offline_case(q, retriever, sandbox.company_id))
        note = "Retrieval-only metrics (no LLM). BM25 + pgvector + RRF + cross-encoder rerank."
    else:
        provider = get_llm_provider()
        ragas = rag_eval.build_ragas_metrics() if use_ragas else None
        for i, q in enumerate(questions, start=1):
            results.append(await rag_eval.run_live_case(q, retriever, sandbox.company_id, provider, ragas))
            print(f"  [{i:02d}/{len(questions)}] {q['key']}: {results[-1]['output']['status']}", flush=True)
        note = "Groq grounded answers with verified citations" + ("; Ragas judge = same Groq model." if ragas else "; Ragas disabled.")
    metrics = rag_eval.aggregate(results)
    saved = await save_run(suite=EvalSuite.RAG, mode=mode, dataset_version="rag-v1",
                           model=None if mode == EvalMode.OFFLINE else get_settings().groq_model, results=results, metrics=metrics, notes=note)
    _print(f"rag ({mode.value})", metrics, saved)


async def run_copilot(limit: int | None) -> None:
    cases = copilot_eval.load_cases(DATASETS / "copilot_v1.jsonl")
    cases = cases[:limit] if limit else cases
    async with get_sessionmaker()() as s:
        company = await s.scalar(select(m.Company).where(m.Company.is_demo.is_(True)))
        if company is None:
            print("copilot eval needs the demo tenant: run `python -m app.cli load-demo` first", file=sys.stderr)
            return
        owner = await s.scalar(select(m.User).where(m.User.company_id == company.id, m.User.role == UserRole.OWNER))
    principal = Principal(owner.id, company.id, owner.role, owner.full_name)
    provider = get_llm_provider()
    results = []
    for i, case in enumerate(cases, start=1):
        results.append(await copilot_eval.run_case(case, principal, provider, company.id))
        print(f"  [{i:02d}/{len(cases)}] {'PASS' if results[-1]['passed'] else 'FAIL'} {case['key']}", flush=True)
    metrics = agent_eval.aggregate(results, live=False)
    saved = await save_run(suite=EvalSuite.COPILOT, mode=EvalMode.LIVE, dataset_version="copilot-v1", model=get_settings().groq_model,
                           results=results, metrics=metrics, notes="Real Groq tool calling over read-only tools on the demo tenant.")
    _print("copilot (live)", metrics, saved)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=["rag", "agent", "copilot", "all"], default="all")
    parser.add_argument("--mode", choices=["auto", "live", "offline"], default="auto")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases of each suite")
    parser.add_argument("--no-ragas", action="store_true", help="Skip the Ragas judge in live RAG evaluation")
    args = parser.parse_args()
    configure_logging("WARNING")
    llm = get_settings().llm_configured
    if args.mode == "live" and not llm:
        sys.exit("--mode live needs GROQ_API_KEY and GROQ_MODEL in .env")
    mode = EvalMode.LIVE if args.mode == "live" or (args.mode == "auto" and llm) else EvalMode.OFFLINE
    print(f"Evaluation mode: {mode.value}")
    try:
        if args.suite in ("agent", "all"):
            await run_agent(mode, args.limit)
        if args.suite in ("rag", "all"):
            await run_rag(mode, args.limit, use_ragas=not args.no_ragas)
        if args.suite in ("copilot", "all"):
            if mode == EvalMode.LIVE:
                await run_copilot(args.limit)
            else:
                print("\n== copilot == skipped: tool-selection accuracy is only meaningful with a real model (live mode)")
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
