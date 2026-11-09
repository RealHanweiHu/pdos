"""D98/D282 BOM import, difference page and rule card over the real command chain.

Originals go through the real upload, a synthetic scan port and the isolated
parser; the import is a READ conversion and the save is `engineering.bom.revise`
with one confirmation. Synthetic data only.
"""

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from originals.test_durable_evidence import upload_input
from security_fixture import SyntheticScanner, synthetic_runtime
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.api import create_app
from pdos_next.core.models import Artifact
from pdos_next.domain.builds.configurations.models import BomLine, BomRevision
from pdos_next.originals.access import parse_uploaded
from pdos_next.originals.object_journal import JournaledLocalObjectStore
from pdos_next.originals.security import configure, scan_requested
from tests.exports.test_export_pg import auth, book, data_rows, reader

HEADER = ["料号", "名称", "用量", "单位", "位号", "ERP料号", "供应商"]
V1 = [
    ["RD-100", "Housing", 1, "pcs", "", "ERP-100", "ACME"],
    ["RD-200", "Resistor 10k", 3, "pcs", "R1-R3", "ERP-200", ""],
    ["RD-300", "Capacitor", 2, "pcs", "C1,C1", "", ""],
    ["RD-400", "Broken", -2, "pcs", "", "", ""],
]


@pytest.fixture
def bom_work(setup, tmp_path):
    prior = getattr(setup.engine, "_pdos_security_runtime", None)
    store = JournaledLocalObjectStore(tmp_path / "synthetic-bom-originals")
    runtime = synthetic_runtime(SyntheticScanner())
    client = TestClient(
        create_app(setup.engine, setup.auth, object_store=store, security_runtime=runtime)
    )
    try:
        yield SimpleNamespace(setup=setup, store=store, client=client)
    finally:
        client.close()
        configure(setup.engine, prior)
        store.close()


def root(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}"


def xlsx(rows, header=HEADER):
    book_ = Workbook()
    sheet = book_.active
    sheet.title = "BOM"
    sheet.append(["Synthetic BOM export, unverified"])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book_.save(buffer)
    return buffer.getvalue()


def parsed_original(work, content, filename="bom.xlsx", visibility="private"):
    setup = work.setup
    uploaded = work.client.post(
        f"{root(work)}/originals",
        headers=setup.headers,
        json=upload_input(
            content, filename=filename, title=filename, visibility=visibility
        ).model_dump(mode="json"),
    )
    assert uploaded.status_code == 200, uploaded.text
    original_id = UUID(uploaded.json()["subject_id"])
    scan = work.client.post(
        f"{root(work)}/originals/{original_id}/scan",
        headers=setup.headers,
        json={"expected_epoch": 1, "idempotency_key": str(uuid4())},
    )
    assert scan.status_code == 200, scan.text
    reference = {
        "category_id": str(setup.category),
        "actor_id": str(setup.human),
        "requester_id": str(setup.human),
        "tenant_id": str(setup.tenant),
        "product_id": str(setup.product),
    }
    assert (
        scan_requested(setup.engine, {**reference, "subject_id": scan.json()["subject_id"]})[
            "status"
        ]
        == "clean"
    )
    result = parse_uploaded(setup.engine, {**reference, "subject_id": str(original_id)}, work.store)
    assert result["status"] == "parsed", result
    with Session(setup.admin) as s:
        artifact = s.scalar(select(Artifact).where(Artifact.original_id == original_id))
        return {"artifact_id": str(artifact.id), "expected_revision": artifact.revision}


def convert(work, source, headers=None, **request):
    response = work.client.post(
        f"{root(work)}/configurations/bom-import/inputs",
        headers=headers or work.setup.headers,
        json={**source, **request},
    )
    return response


def save(work, result, *, name="Synthetic imported BOM", previous=None, tamper=None):
    payload = result["payload"]
    command = {
        "category_id": str(work.setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "engineering.bom.revise",
        "product_id": str(work.setup.product),
        "expected_revision": 1,
        "source_read_set": payload["required_source_read_set"],
        "payload": {
            "name": name,
            "reason": "Imported from a synthetic spreadsheet",
            "visibility": "private",
            "previous_id": previous["id"] if previous else None,
            "expected_previous_revision": previous["revision"] if previous else None,
            "sources": payload["sources"],
            "lines": tamper(payload["lines"]) if tamper else payload["lines"],
            "import_basis": payload["import_basis"],
        },
    }
    if previous:
        reads = {r["artifact_id"]: r for r in previous["required_source_read_set"]}
        reads.update({r["artifact_id"]: r for r in payload["required_source_read_set"]})
        command["source_read_set"] = list(reads.values())
    reviewed = work.client.post(
        f"/v1/categories/{work.setup.category}/commands/preview",
        headers=work.setup.headers,
        json=command,
    )
    if tamper:
        return reviewed
    assert reviewed.status_code == 200, reviewed.text
    saved = work.client.post(
        f"/v1/categories/{work.setup.category}/commands",
        headers=work.setup.headers,
        json=reviewed.json()["command"],
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["subject_id"], reviewed.json()["review"]


def boms(work):
    listed = work.client.get(f"{root(work)}/configurations", headers=work.setup.headers)
    assert listed.status_code == 200, listed.text
    return {bom["id"]: bom for bom in listed.json()["boms"]}


def test_import_converts_by_code_waits_for_dispositions_and_saves_one_confirmed_version(bom_work):
    work = bom_work
    source = parsed_original(work, xlsx(V1))

    first = convert(work, source)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["format"] == "xlsx" and body["sheet"] == "BOM" and body["header_row"] == 2
    assert body["suggested"] is True and body["complete"] is False and body["payload"] is None
    assert [c["field"] for c in body["columns"]] == [
        "internal_number",
        "name",
        "quantity",
        "unit",
        "reference_designators",
        "erp_number",
    ]
    assert body["unmapped_columns"] == [{"column": 7, "header": "供应商"}]
    rows = {row["row"]: row for row in body["rows"]}
    assert rows[6]["status"] == "needs_disposition"
    assert [i["code"] for i in rows[6]["issues"]] == ["quantity_non_positive"]
    rules = {rule["code"]: rule for rule in body["rules"]["rules"]}
    assert rules["duplicate_designator"]["status"] == "fail"
    assert rules["quantity"]["status"] == "fail"

    decided = convert(
        work,
        source,
        columns=[{"field": c["field"], "column": c["column"]} for c in body["columns"]],
        dispositions=[{"row": 6, "action": "skip", "reason": "Quantity is wrong in the file"}],
    ).json()
    assert decided["complete"] is True, decided
    assert decided["counts"] == {"ready": 3, "skipped": 1, "needs_disposition": 0, "ignored": 0}
    assert decided["diff"]["summary"]["added"] == 3

    # The server converts again at confirmation: changed lines are refused.
    def tampered(lines):
        return [{**line, "quantity": "9"} if line["key"] == "RD-100" else line for line in lines]

    refused = save(work, decided, tamper=tampered)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "VALIDATION_FAILED"

    bom_id, review = save(work, decided)
    assert review["diff"]["summary"] == {"added": 3, "removed": 0, "changed": 0, "unchanged": 0}
    assert review["rules"]["status"] == "fail"
    saved = boms(work)[bom_id]
    lines = {line["key"]: line for line in saved["lines"]}
    assert lines["RD-200"]["reference_designators"] == ["R1", "R2", "R3"]
    assert lines["RD-300"]["reference_designators"] == ["C1", "C1"]
    record = saved["import_basis"]
    assert record["converter"] == "bom-import.v1" and record["artifact_id"] == source["artifact_id"]
    assert record["rows"] == {"RD-100": 3, "RD-200": 4, "RD-300": 5}
    assert record["skipped"] == [{"row": 6, "reason": "Quantity is wrong in the file"}]
    assert record["unmapped_columns"] == [{"column": 7, "header": "供应商"}]
    assert source in saved["required_source_read_set"]

    page = work.client.get(
        f"{root(work)}/configurations/boms/{bom_id}/review", headers=work.setup.headers
    )
    assert page.status_code == 200, page.text
    assert page.json()["previous"] is None and page.json()["diff"]["summary"]["added"] == 3
    duplicate = next(
        r for r in page.json()["rules"]["rules"] if r["code"] == "duplicate_designator"
    )
    assert duplicate["items"] == [
        {"designator": "C1", "lines": [{"key": "RD-300"}, {"key": "RD-300"}], "level": "fail"}
    ]

    # Version 2: one quantity and designators change, one line goes, one comes, and a
    # row whose ERP number equals an existing part waits for a named choice.
    v2 = [
        ["RD-100", "Housing", 1, "pcs", "", "ERP-100", ""],
        ["RD-200", "Resistor 10k", 4, "pcs", "R1-R4", "ERP-200", ""],
        ["RD-500", "Spring", 2, "pcs", "", "ERP-100", ""],
    ]
    second_source = parsed_original(work, xlsx(v2), filename="bom-v2.xlsx")
    previous = boms(work)[bom_id]
    pending = convert(
        work,
        second_source,
        previous_id=bom_id,
        expected_previous_revision=1,
    ).json()
    hint = {row["row"]: row for row in pending["rows"]}[5]
    assert hint["status"] == "needs_disposition" and len(hint["hints"]) == 1
    housing = lines["RD-100"]["part_id"]
    assert hint["hints"][0]["part_id"] == housing
    resolved = convert(
        work,
        second_source,
        previous_id=bom_id,
        expected_previous_revision=1,
        dispositions=[{"row": 5, "action": "new_part"}],
    ).json()
    assert resolved["complete"] is True
    # Same internal number reuses the existing part and keeps the predecessor's key.
    reused = {line["key"]: line for line in resolved["payload"]["lines"]}
    assert reused["RD-100"]["part_id"] == housing and reused["RD-100"]["part"] is None
    second_id, second_review = save(
        work, resolved, name="Synthetic imported BOM", previous=previous
    )
    assert second_review["diff"]["summary"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 1,
    }
    page = work.client.get(
        f"{root(work)}/configurations/boms/{second_id}/review", headers=work.setup.headers
    ).json()
    changed = {row["key"]: row for row in page["diff"]["lines"]}
    assert changed["RD-200"]["fields"] == ["quantity", "reference_designators"]
    assert changed["RD-200"]["designators"] == {"added": ["R4"], "removed": []}
    assert changed["RD-300"]["change"] == "removed" and changed["RD-500"]["change"] == "added"
    assert page["previous"]["revision"] == 1 and page["bom"]["revision"] == 2

    # The export reads the same difference (D282).
    exported = book(
        work.client.get(
            f"{root(work)}/exports/bom-diff",
            params={"bom_id": second_id},
            headers=work.setup.headers,
        )
    )
    header = [c.value for c in exported["BOM 差异"][1]]
    row = next(
        dict(zip(header, values, strict=True))
        for values in data_rows(exported["BOM 差异"])
        if values[header.index("行号")] == "RD-200"
    )
    assert row["上一版位号"] == "R1、R2、R3" and row["本版位号"] == "R1、R2、R3、R4"
    assert "位号" in row["变化字段"] and row["本版用量"] == "4"

    # Saved versions are immutable rows; the new version did not touch the first.
    with Session(work.setup.admin) as s:
        assert s.get(BomRevision, UUID(bom_id)).import_basis["rows"]["RD-300"] == 5
        assert s.scalar(
            select(BomLine.reference_designators).where(
                BomLine.bom_id == UUID(bom_id), BomLine.key == "RD-200"
            )
        ) == ["R1", "R2", "R3"]


def test_csv_import_and_access_follow_the_original(bom_work):
    work = bom_work
    content = '﻿料号,名称,用量,单位,位号\nRD-1,"Board, main",1,pcs,U1\nRD-2,Screw,4,pcs,\n'
    source = parsed_original(work, content.encode(), filename="bom.csv")
    result = convert(work, source).json()
    assert result["format"] == "csv" and result["sheets"] == [] and result["complete"] is True
    lines = {line["key"]: line for line in result["payload"]["lines"]}
    assert lines["RD-1"]["part"]["name"] == "Board, main"
    assert lines["RD-2"]["quantity"] == "4"

    # A private original stays private: another member cannot convert it.
    member = reader(work.setup, write=True)
    refused = convert(work, source, headers=auth(work.setup, member))
    assert refused.status_code in {403, 404}, refused.text

    # A text original that is not CSV is not a BOM source.
    text = parsed_original(work, b"Notes only\n", filename="notes.txt")
    unsupported = convert(work, text)
    # Error codes converge (§08.7): the specific reason stays in the detail.
    assert unsupported.status_code == 422 and unsupported.json()["code"] == "VALIDATION_FAILED"
    assert "XLSX 或 CSV" in unsupported.json()["message"]
