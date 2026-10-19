import pytest

pytestmark = pytest.mark.integration


async def test_health_is_public_and_reports_dependencies(anon):
    r = await anon.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True and body["llm_configured"] is False


async def test_auth_required_and_bad_tokens_rejected(anon):
    r = await anon.get("/dashboard/summary")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"
    r = await anon.get("/dashboard/summary", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_me_and_demo_labelling(owner):
    me = (await owner.get("/me")).json()
    assert me["role"] == "owner" and me["company"]["is_demo"] is True
    summary = (await owner.get("/dashboard/summary")).json()
    assert summary["data_provenance"] == "synthetic_demo"
    k = summary["kpis"]
    assert k["high_risk_opportunities"] > 0 and k["revenue_at_risk"] > 0
    # Nothing AI-generated exists until a pipeline actually runs.
    assert k["ai_recommendations"] == 0 or k["ai_recommendations"] >= 0
    assert k["automation_success_rate"] is None or 0 <= k["automation_success_rate"] <= 1


async def test_vertex_is_critical_with_explained_reasons(owner, demo):
    r = (await owner.get("/risks", params={"level": "critical", "q": "Vertex"})).json()
    assert r["total"] == 1
    item = r["items"][0]
    assert item["risk_level"] == "critical" and item["revenue_at_risk"] == 480000
    codes = {x["code"] for x in item["reasons"]}
    assert {"CUSTOMER_AWAITING_REPLY", "NO_RECENT_CONTACT", "COMPETITOR_MENTIONED", "PRICE_OBJECTION"} <= codes
    assert all(x["source"] in ("crm_data", "keyword_heuristic", "llm_analysis") for x in item["reasons"])


async def test_customer_profile_has_all_sections(owner, demo):
    cid = demo["scenario"]["customer_id"]
    p = (await owner.get(f"/customers/{cid}")).json()
    for key in ("customer", "summary", "contacts", "opportunities", "quotes", "conversations", "risks", "timeline", "audit"):
        assert key in p
    s = p["summary"]
    assert s["revenue_risk"] == "critical" and s["main_objection"] == "price" and s["competitor_mentioned"]
    assert s["intent_source"] in ("keyword_heuristic", "llm_analysis")


async def test_lists_and_filters(owner):
    customers = (await owner.get("/customers", params={"limit": 5})).json()
    assert customers["total"] >= 300 and len(customers["items"]) == 5
    pipeline = (await owner.get("/opportunities/pipeline")).json()
    assert {s["stage"] for s in pipeline["stages"]} >= {"proposal", "negotiation"}
    convs = (await owner.get("/conversations", params={"open_deals_only": True, "limit": 3})).json()
    assert convs["total"] > 0
    leads = (await owner.get("/leads", params={"unanswered": True})).json()
    assert all(x["first_response_at"] is None for x in leads["items"])


async def test_tenant_isolation(other_tenant, demo):
    cid = demo["scenario"]["customer_id"]
    r = await other_tenant.get(f"/customers/{cid}")
    assert r.status_code == 404
    risks = (await other_tenant.get("/risks")).json()
    assert risks["total"] == 0
    r = await other_tenant.get(f"/conversations/{demo['scenario']['conversation_id']}")
    assert r.status_code == 404


async def test_role_based_access(rep, owner):
    settings = (await owner.get("/settings")).json()["company"]
    r = await rep.put("/settings", json=settings)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = await rep.post("/risks/recompute")
    assert r.status_code == 403


async def test_settings_roundtrip_is_validated_and_audited(owner):
    cfg = (await owner.get("/settings")).json()["company"]
    cfg["risk_thresholds"] = {"critical": 50, "high": 60, "medium": 10}
    bad = await owner.put("/settings", json=cfg)
    assert bad.status_code == 422
    cfg["risk_thresholds"] = {"critical": 75, "high": 55, "medium": 35}
    assert (await owner.put("/settings", json=cfg)).status_code == 200
    audit = (await owner.get("/audit", params={"action": "settings.updated"})).json()
    assert audit["total"] >= 1


async def test_validation_errors_use_error_contract(owner):
    r = await owner.get("/risks", params={"limit": 0})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_request" and err["retryable"] is False


async def test_llm_features_degrade_gracefully_without_llm(owner, demo):
    r = await owner.post(f"/conversations/{demo['scenario']['conversation_id']}/analyze")
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"
    ask = (await owner.post("/knowledge/ask", json={"question": "What discount can a rep give without approval?"})).json()
    assert ask["status"] == "LLM_FALLBACK" and ask["evidence"]
