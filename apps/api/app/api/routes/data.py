"""Demo dataset loading and CSV/JSON import."""

from __future__ import annotations

import hmac
from typing import Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlalchemy import func, select

from app.api.deps import AdminDep, PageDep, PrincipalDep, SessionDep, paginated
from app.core.cache import invalidate_company
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db import models as m
from app.services.company import get_company_settings
from app.services.demo import load_demo
from app.services.ingestion import ingest_file, sample_headers
from app.services.risk_service import recompute_risks

router = APIRouter(tags=["data"])


@router.post("/demo/bootstrap")
async def demo_bootstrap(request: Request, session: SessionDep) -> dict:
    """First-run only: create the demo tenant when no company exists yet.

    Authorised by the configured DEMO_API_TOKEN (there are no users to authenticate against yet).
    """
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    expected = get_settings().demo_api_token.get_secret_value()
    if not token or not hmac.compare_digest(token, expected):
        raise AppError(ErrorCode.UNAUTHENTICATED, "Bootstrap requires the configured DEMO_API_TOKEN")
    if await session.scalar(select(func.count()).select_from(m.Company)):
        raise AppError(ErrorCode.CONFLICT, "A tenant already exists; use /demo/load as an admin instead")
    return await load_demo(session)


@router.get("/demo/status")
async def demo_status(session: SessionDep) -> dict:
    """Unauthenticated: tells the UI whether first-run bootstrap is needed (no data is exposed)."""
    return {"tenant_exists": bool(await session.scalar(select(func.count()).select_from(m.Company)))}


@router.post("/demo/load")
async def demo_load(principal: AdminDep, session: SessionDep) -> dict:
    """Replace the demo tenant with fresh synthetic data. Tokens stay valid (demo owner is re-created with the same token)."""
    company = await session.get(m.Company, principal.company_id)
    if company is None or not company.is_demo:
        raise AppError(ErrorCode.FORBIDDEN, "Demo data can only be (re)loaded into the demo tenant")
    result = await load_demo(session)
    await invalidate_company(principal.company_id)
    await invalidate_company(result["company_id"])
    return result


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(ErrorCode.VALIDATION_FAILED, f"File exceeds {limit // (1024 * 1024)} MB")
    return data


@router.get("/ingest/templates")
async def templates(principal: PrincipalDep) -> dict:
    return {"entities": sample_headers()}


@router.post("/ingest/{entity}")
async def ingest(
    entity: Literal["customers", "leads", "quotes", "sales_activities"],
    principal: PrincipalDep,
    session: SessionDep,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
) -> dict:
    data = await _read_upload(file)
    job = await ingest_file(
        session,
        company_id=principal.company_id,
        entity=entity,
        filename=file.filename or "upload.csv",
        data=data,
        actor_id=principal.user_id,
    )
    result = {
        "job_id": str(job.id),
        "entity": entity,
        "status": job.status.value,
        "rows_total": job.rows_total,
        "inserted": job.rows_inserted,
        "updated": job.rows_updated,
        "duplicates": job.rows_duplicate,
        "rejected": job.rows_rejected,
        "errors": job.errors,
        "dry_run": dry_run,
    }
    if dry_run:
        await session.rollback()
        return result
    if entity == "quotes" and job.rows_inserted:
        await recompute_risks(session, principal.company_id, await get_company_settings(session, principal.company_id))
    await session.commit()
    await invalidate_company(principal.company_id)
    return result


@router.get("/ingest/jobs")
async def jobs(principal: PrincipalDep, session: SessionDep, page: PageDep) -> dict:
    q = select(m.IngestionJob).where(m.IngestionJob.company_id == principal.company_id)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = (
        await session.scalars(q.order_by(m.IngestionJob.created_at.desc()).limit(page.limit).offset(page.offset))
    ).all()
    return paginated(
        [
            {
                "id": str(j.id),
                "entity": j.entity,
                "filename": j.filename,
                "status": j.status.value,
                "rows_total": j.rows_total,
                "inserted": j.rows_inserted,
                "updated": j.rows_updated,
                "duplicates": j.rows_duplicate,
                "rejected": j.rows_rejected,
                "errors": j.errors[:20],
                "created_at": j.created_at,
            }
            for j in rows
        ],
        int(total or 0),
        page,
    )
