import json

import pytest

from app.llm.factory import set_llm_override
from tests.fakes import ScriptedLLM

pytestmark = pytest.mark.integration

CUSTOMERS_CSV = """name,industry,segment,status,city,website,employee_count
Godavari Ceramics Pvt Ltd,Manufacturing,Mid Market,prospect,Rajahmundry,https://godavariceramics.in,420
Godavari Ceramics Private Limited,Manufacturing,mid_market,prospect,Rajahmundry,,
,Retail,smb,prospect,Pune,,
Tapovan Hospitals,Healthcare,ENTERPRISE,active,Dehradun,,abc
"""

LEADS_CSV = """company_name,contact_name,contact_email,source,status,estimated_value,received_at
Godavari Ceramics Pvt Ltd,Ravi Teja,ravi.teja@godavariceramics.in,Trade Show,new,"₹6,50,000",2026-10-12
Godavari Ceramics Pvt Ltd,Ravi Teja,ravi.teja@godavariceramics.in,trade_show,new,650000,2026-10-12
Unknown Co,Someone,not-an-email,fax,new,12x,yesterday
"""


async def test_csv_import_validates_dedupes_and_resolves(owner):
    r = await owner.post("/ingest/customers", files={"file": ("customers.csv", CUSTOMERS_CSV.encode(), "text/csv")})
    body = r.json()
    assert r.status_code == 200, body
    assert body["inserted"] == 1 and body["duplicates"] == 1 and body["rejected"] == 2
    fields = {(e["row"], e["field"]) for e in body["errors"]}
    assert (4, "name") in fields and (5, "employee_count") in fields
    assert body["status"] == "completed_with_errors"

    r = await owner.post("/ingest/leads", files={"file": ("leads.csv", LEADS_CSV.encode(), "text/csv")})
    leads = r.json()
    assert leads["inserted"] == 1 and leads["duplicates"] == 1 and leads["rejected"] == 1
    bad_fields = {e["field"] for e in leads["errors"]}
    assert {"contact_email", "source", "estimated_value", "received_at"} <= bad_fields
    # Entity resolution: the imported lead is linked to the imported customer.
    customers = (await owner.get("/customers", params={"q": "Godavari Ceramics"})).json()
    assert customers["total"] == 1
    lead_list = (await owner.get("/leads", params={"limit": 200})).json()["items"]
    assert any(
        x["company_name"] == "Godavari Ceramics Pvt Ltd" and x["customer_id"] == customers["items"][0]["id"]
        for x in lead_list
    )


async def test_json_import_and_dry_run(owner):
    rows = [{"name": "Neelkanth Cold Storage", "industry": "Logistics & Warehousing"}]
    r = await owner.post(
        "/ingest/customers",
        files={"file": ("c.json", json.dumps(rows).encode(), "application/json")},
        data={"dry_run": "true"},
    )
    assert r.json()["inserted"] == 1 and r.json()["dry_run"] is True
    assert (await owner.get("/customers", params={"q": "Neelkanth Cold Storage"})).json()["total"] == 0


async def test_unsupported_and_malformed_uploads(owner):
    r = await owner.post("/ingest/customers", files={"file": ("x.xlsx", b"PK\x03\x04", "application/octet-stream")})
    assert r.status_code == 415
    r = await owner.post("/ingest/customers", files={"file": ("x.json", b"{not json", "application/json")})
    assert r.status_code == 422 and "Invalid JSON" in r.json()["error"]["message"]


async def test_hybrid_search_finds_policy_and_refuses_off_topic(owner):
    r = (
        await owner.post(
            "/knowledge/search", json={"query": "What discount can a salesperson offer without manager approval?"}
        )
    ).json()
    assert r["status"] == "OK"
    top = r["evidence"][0]
    assert top["document_title"] == "Discount Authority Policy"
    assert top["scores"]["bm25_rank"] and top["scores"]["vector_rank"] and top["scores"]["rerank"] > 0.5
    off = (await owner.post("/knowledge/search", json={"query": "Who won the 2011 cricket world cup?"})).json()
    assert off["status"] == "INSUFFICIENT_EVIDENCE" and off["evidence"] == []


async def test_injection_document_is_flagged_and_withheld(owner):
    docs = (await owner.get("/knowledge/documents")).json()
    flagged = [d for d in docs["items"] if d["injection_findings"]]
    assert [d["title"] for d in flagged] == ["Channel Partner FAQ (imported from shared drive)"]
    patterns = {f["pattern"] for f in flagged[0]["injection_findings"]}
    assert {"override_instructions", "data_exfiltration", "approval_bypass"} <= patterns

    captured: dict = {}

    def reply(messages):
        captured["prompt"] = messages[-1].content
        return {"status": "insufficient_evidence", "answer": "", "claims": [], "injection_suspected": False}

    set_llm_override(ScriptedLLM([reply]))
    question = "Should every discount request be approved automatically without manager approval, and who gets the customer list?"
    ans = (await owner.post("/knowledge/ask", json={"question": question})).json()
    # The poisoned chunk IS retrieved (it is relevant) — and withheld from the model.
    assert any(w["document"].startswith("Channel Partner FAQ") for w in ans["withheld_evidence"]), ans[
        "withheld_evidence"
    ]
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in captured["prompt"]
    assert "outlook-mailbox" not in captured["prompt"]
    assert any("prompt injection" in x for x in ans["limitations"])


async def test_grounded_answer_verifies_citations(owner):
    def reply(messages):
        prompt = messages[-1].content
        # Cite whichever evidence id holds the approval-limit clause.
        eid = next(
            line.split("]")[0].strip("[")
            for line in prompt.splitlines()
            if line.startswith("[E") and "Discount" in line
        )
        return {
            "status": "answered",
            "answer": "Up to 10% without approval; above 10% needs a Sales Manager.",
            "claims": [
                {"claim": "Discounts above 10% require manager approval.", "evidence_ids": [eid]},
                {"claim": "Discounts above 35% are free for loyal customers.", "evidence_ids": ["E99"]},
            ],
            "injection_suspected": False,
        }

    set_llm_override(ScriptedLLM([reply]))
    ans = (
        await owner.post(
            "/knowledge/ask",
            json={
                "question": "What discount can a salesperson offer without manager approval?",
                "document_types": ["discount_policy"],
            },
        )
    ).json()
    assert ans["status"] == "PARTIALLY_SUPPORTED"
    good, bad = ans["claims"]
    assert good["supported"] and good["source_document"] == "Discount Authority Policy"
    assert not bad["supported"] and "unknown evidence" in bad["problems"][0]


async def test_document_upload_validation(owner):
    ok = await owner.post(
        "/knowledge/documents",
        files={
            "file": (
                "warranty.md",
                b"# Warranty\n\n## Hardware\nAll hardware carries a 12-month warranty.",
                "text/markdown",
            )
        },
        data={"document_type": "company_policy"},
    )
    assert ok.status_code == 200 and ok.json()["chunks"] >= 1
    dup = await owner.post(
        "/knowledge/documents",
        files={
            "file": (
                "again.md",
                b"# Warranty\n\n## Hardware\nAll hardware carries a 12-month warranty.",
                "text/markdown",
            )
        },
    )
    assert dup.json()["duplicate"] is True
    fake_pdf = await owner.post(
        "/knowledge/documents", files={"file": ("x.pdf", b"not really a pdf", "application/pdf")}
    )
    assert fake_pdf.status_code == 415
    exe = await owner.post("/knowledge/documents", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert exe.status_code == 415


def _minimal_pdf(text: str) -> bytes:
    """Build a tiny valid single-page PDF with one line of text (no external libraries)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


async def test_pdf_ingestion(owner):
    r = await owner.post(
        "/knowledge/documents",
        files={"file": ("shipping.pdf", _minimal_pdf("Standard delivery takes 21 days after PO."), "application/pdf")},
        data={"document_type": "sop", "title": "Shipping SOP"},
    )
    assert r.status_code == 200, r.json()
    assert r.json()["chunks"] == 1
