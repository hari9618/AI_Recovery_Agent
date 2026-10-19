"""Operator CLI.

uv run --project apps/api python -m app.cli load-demo
uv run --project apps/api python -m app.cli recompute-risks
uv run --project apps/api python -m app.cli analyze-conversations --limit 25     # needs GROQ_API_KEY
uv run --project apps/api python -m app.cli run-agent --customer "Vertex Industrial"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import models as m
from app.db.session import get_engine, get_sessionmaker
from app.domain.conversation import PROMPT_VERSION
from app.domain.enums import OPEN_STAGES
from app.llm.factory import get_llm_provider
from app.llm.ledger import llm_call_context
from app.security.auth import Principal, resolve_principal
from app.services.company import get_company_settings
from app.services.conversation_intelligence import analyze_conversation
from app.services.demo import load_demo
from app.services.risk_service import recompute_risks
from app.services.transcripts import transcript_hash


async def _principal() -> Principal:
    async with get_sessionmaker()() as s:
        return await resolve_principal(s, get_settings().demo_api_token.get_secret_value())


async def cmd_load_demo(_: argparse.Namespace) -> None:
    async with get_sessionmaker()() as s:
        print(json.dumps(await load_demo(s), indent=1, default=str))


async def cmd_recompute(_: argparse.Namespace) -> None:
    p = await _principal()
    async with get_sessionmaker()() as s:
        rows = await recompute_risks(s, p.company_id, await get_company_settings(s, p.company_id))
        await s.commit()
    levels: dict[str, int] = {}
    for r in rows:
        levels[r.risk_level.value] = levels.get(r.risk_level.value, 0) + 1
    print(f"assessed {len(rows)} open opportunities: {levels}")


async def cmd_analyze(args: argparse.Namespace) -> None:
    p = await _principal()
    provider = get_llm_provider()
    async with get_sessionmaker()() as s:
        convs = (
            await s.scalars(
                select(m.Conversation)
                .options(selectinload(m.Conversation.messages))
                .join(m.Opportunity, m.Opportunity.id == m.Conversation.opportunity_id)
                .join(
                    m.RevenueRisk,
                    (m.RevenueRisk.opportunity_id == m.Opportunity.id) & m.RevenueRisk.is_current.is_(True),
                )
                .where(m.Conversation.company_id == p.company_id, m.Opportunity.stage.in_(OPEN_STAGES))
                .order_by(m.RevenueRisk.risk_score.desc())
            )
        ).all()
        done = {
            (c, h)
            for c, h in (
                await s.execute(
                    select(m.ConversationAnalysis.conversation_id, m.ConversationAnalysis.content_hash).where(
                        m.ConversationAnalysis.prompt_version == PROMPT_VERSION
                    )
                )
            ).all()
        }
        todo = [c for c in convs if c.messages and (c.id, transcript_hash(c.messages)) not in done][: args.limit]
        opp_ids = []
        with llm_call_context(company_id=p.company_id):
            for i, conv in enumerate(todo, start=1):
                out = await analyze_conversation(s, provider, company_id=p.company_id, conversation_id=conv.id)
                await s.commit()
                opp_ids.append(conv.opportunity_id)
                intent = out.insight.intent if out.insight else "-"
                print(f"[{i}/{len(todo)}] {out.status.value:9} intent={intent:6} {conv.subject}")
        if opp_ids:
            await recompute_risks(s, p.company_id, await get_company_settings(s, p.company_id), opportunity_ids=opp_ids)
            await s.commit()


async def cmd_run_agent(args: argparse.Namespace) -> None:
    from app.services.agent_runner import run_recovery  # noqa: PLC0415

    p = await _principal()
    async with get_sessionmaker()() as s:
        q = (
            select(m.Opportunity)
            .join(m.Customer, m.Customer.id == m.Opportunity.customer_id)
            .where(m.Opportunity.company_id == p.company_id, m.Opportunity.stage.in_(OPEN_STAGES))
        )
        q = (
            q.where(m.Opportunity.id == args.opportunity)
            if args.opportunity
            else q.where(m.Customer.name.ilike(f"%{args.customer}%"))
        )
        opp = await s.scalar(q.limit(1))
    if opp is None:
        sys.exit("No open opportunity found")
    result = await run_recovery(p, opp.id, force=args.force)
    async with get_sessionmaker()() as s:
        run = await s.get(m.AgentRun, opp.id.__class__(result["run_id"]))
        for step in run.steps:
            print(
                f"  {step['node']:24} {step['status']:9} {step.get('latency_ms', 0):>6}ms  {step.get('summary') or ''}"
            )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "status": run.status.value,
                    "trace_url": run.trace_url,
                    "llm_calls": run.llm_calls,
                    "tokens": run.input_tokens + run.output_tokens,
                    "cost_usd": run.cost_usd,
                },
                indent=1,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("load-demo", help="(Re)load the synthetic demo tenant").set_defaults(fn=cmd_load_demo)
    sub.add_parser("recompute-risks", help="Run the risk engine over all open deals").set_defaults(fn=cmd_recompute)
    a = sub.add_parser("analyze-conversations", help="LLM-analyse conversations of the riskiest open deals")
    a.add_argument("--limit", type=int, default=20)
    a.set_defaults(fn=cmd_analyze)
    r = sub.add_parser("run-agent", help="Run the recovery workflow for one deal")
    r.add_argument("--customer", default="Vertex Industrial")
    r.add_argument("--opportunity", default=None)
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_run_agent)
    args = parser.parse_args()
    configure_logging("WARNING")

    async def runner() -> None:
        try:
            await args.fn(args)
        finally:
            await get_engine().dispose()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
