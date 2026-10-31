"""Actual local uploads/parsers/scans for native page/cell comparison locations."""
# ruff: noqa: F811 -- explicitly imported marked PG fixture

import io
from dataclasses import replace
from uuid import uuid4

import pytest

from pdos_next.errors import DomainError
from pdos_next.original_security import configure
from tests.enterprise_search.test_assistant_pg import execute, fixture
from tests.enterprise_search.test_comparison_pg import CompareClient
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


def pdf(value):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in (b"UNCHANGED_RAW_ONLY", f"Pressure {value} bar".encode()):
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (" + text + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def xlsx(value, *, reordered=False):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "规格"
    rows = [["参数", "值"], ["压力", value], ["温度", 20], ["备注", "UNCHANGED_RAW_ONLY"]]
    if reordered:
        rows = [rows[0], rows[2], rows[1], rows[3]]
        rows = [[row[1], row[0]] for row in rows]
    for row in rows:
        sheet.append(row)
    target = io.BytesIO()
    workbook.save(target)
    workbook.close()
    return target.getvalue()


@pytest.mark.parametrize("media", ["pdf", "xlsx"])
def test_uploaded_pair_uses_real_native_locations_and_scan_invalidation_is_model_free(
    security_work, media
):
    work, setup = security_work, security_work.setup
    contents = [pdf(10), pdf(12)] if media == "pdf" else [xlsx(10), xlsx(12, reordered=True)]
    ids = [
        parsed(work, uploaded(work, content=content, filename=f"version-{index}.{media}"))
        for index, content in enumerate(contents)
    ]
    scanner_calls = work.scanner.calls
    client = CompareClient(ids)
    refs = [
        {"artifact_id": str(identity), "expected_revision": 1, "product_id": str(setup.product)}
        for identity in ids
    ]
    owner, scope, host, adapter = fixture(setup, client, read_sources=refs)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    comparison = output["result"]["assistant"]["comparison"]
    assert comparison["complete"] and comparison["stats"]["changes"] == 1, comparison
    row = comparison["rows"][0]
    if media == "pdf":
        assert row["old"]["locator"]["native"] == row["new"]["locator"]["native"] == ["page:2"]
    else:
        assert row["old"]["locator"]["native"] == ['cell:["规格","B2"]']
        assert row["new"]["locator"]["native"] == ['cell:["规格","A3"]']
        assert row["new"]["value_kind"] == "number"
    assert "UNCHANGED_RAW_ONLY" not in str(output)
    for source in output["result"]["assistant"]["sources"]:
        response = work.client.get(source["url"].removeprefix("/api"), headers=setup.headers)
        assert response.status_code == 200 and source["quote"] in response.json()["text"], (
            response.text
        )
    saved = work.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={
            "run_id": str(scope.run_id),
            "kind": "table",
            "request_key": str(uuid4()),
        },
    )
    assert saved.status_code == 201, saved.text
    assert "customer_original" in adapter.guard(scope)
    before = client.calls
    configuration = replace(
        work.runtime.configuration,
        scanner=replace(
            work.runtime.configuration.scanner, rules_version="comparison-scanner-rules@2"
        ),
    )
    configure(setup.engine, replace(work.runtime, configuration=configuration))
    with pytest.raises(DomainError):
        adapter.guard(scope)
    blocked = work.client.get(
        output["result"]["assistant"]["sources"][0]["url"].removeprefix("/api"),
        headers=setup.headers,
    )
    assert blocked.status_code == 403
    product = work.client.get(
        "/v1/personal/work-products/" + saved.json()["id"], headers=setup.headers
    )
    assert product.status_code == 403 and "Pressure 10 bar" not in product.text
    assert client.calls == before and work.scanner.calls == scanner_calls
