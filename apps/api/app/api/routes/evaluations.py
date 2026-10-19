"""Evaluation results (produced by `python -m evals.run`). Only measured values are returned."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import PrincipalDep, SessionDep
from app.core.errors import NotFoundError
from app.db import models as m
from app.domain.enums import EvalSuite

router = APIRouter(tags=["evaluations"])


def _run(r: m.EvaluationRun) -> dict:
    return {
        "id": str(r.id),
        "suite": r.suite.value,
        "mode": r.mode.value,
        "dataset_version": r.dataset_version,
        "model": r.model,
        "status": r.status,
        "metrics": r.metrics,
        "cases_total": r.cases_total,
        "cases_passed": r.cases_passed,
        "report_path": r.report_path,
        "notes": r.notes,
        "is_demo_data": r.is_demo_data,
        "created_at": r.created_at,
        "finished_at": r.finished_at,
    }


@router.get("/evaluations/summary")
async def summary(principal: PrincipalDep, session: SessionDep) -> dict:
    """Latest completed run per suite; `null` means 'Not evaluated yet'."""
    out: dict[str, dict | None] = {}
    for suite in EvalSuite:
        run = await session.scalar(
            select(m.EvaluationRun)
            .where(
                m.EvaluationRun.suite == suite,
                m.EvaluationRun.status == "completed",
                (m.EvaluationRun.company_id == principal.company_id) | m.EvaluationRun.company_id.is_(None),
            )
            .order_by(m.EvaluationRun.created_at.desc())
            .limit(1)
        )
        out[suite.value] = _run(run) if run else None
    return {"suites": out}


@router.get("/evaluations/runs")
async def runs(principal: PrincipalDep, session: SessionDep) -> dict:
    rows = (
        await session.scalars(
            select(m.EvaluationRun)
            .where((m.EvaluationRun.company_id == principal.company_id) | m.EvaluationRun.company_id.is_(None))
            .order_by(m.EvaluationRun.created_at.desc())
            .limit(50)
        )
    ).all()
    return {"items": [_run(r) for r in rows]}


@router.get("/evaluations/runs/{run_id}")
async def run_detail(run_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict:
    run = await session.get(m.EvaluationRun, run_id)
    if run is None or (run.company_id and run.company_id != principal.company_id):
        raise NotFoundError("evaluation run", run_id)
    rows = (
        await session.execute(
            select(m.EvaluationResult, m.EvaluationCase)
            .join(m.EvaluationCase, m.EvaluationCase.id == m.EvaluationResult.case_id)
            .where(m.EvaluationResult.run_id == run.id)
            .order_by(m.EvaluationCase.case_key)
        )
    ).all()
    return _run(run) | {
        "results": [
            {
                "case_key": c.case_key,
                "description": c.description,
                "tags": c.tags,
                "passed": r.passed,
                "scores": r.scores,
                "expected": c.expected,
                "output": r.output,
                "error": r.error,
                "latency_ms": r.latency_ms,
            }
            for r, c in rows
        ]
    }
