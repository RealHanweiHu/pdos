"""Real HTTP view drafts; only the root runs these against its verified test DB."""
# ruff: noqa: F811 -- pytest injects the shared real G0 fixture.

from copy import deepcopy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from pdos_next.domain.preproject.spec_compare import compare
from tests.preproject.test_category_context_pg import add_knowledge, publish
from tests.preproject.test_evidence_commands_pg import artifact, record_claim, withdraw_request
from tests.preproject.test_g0 import create, decide_request, payload, read, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_proofs_pg import human_session

VIEWS = ("positioning", "spec-benchmark", "feature-config", "definition-maturity")
IDENTITY = ("proposal_id", "revision", "document_digest", "submission_id", "document_mode")


def view(work, name, proposal_id, *, actor=None, category=None, parameter_ids=()):
    return work.client.get(
        f"/v1/categories/{category or work.category}/views/{name}",
        params=[("proposal_id", proposal_id), *[("parameter_ids", item) for item in parameter_ids]],
        headers={"Authorization": f"Bearer {work.tokens[actor or work.human]}"},
    )


def named_source(work):
    return {
        "type": "human",
        "id": str(work.human),
        "version": 1,
        "statement": "Synthetic named target and measurement statement",
    }


def proposal_body(work, parameter_id, *, refs=None):
    refs = deepcopy(refs if refs is not None else [named_source(work)])
    body = payload(work)
    body["groups"]["items"][3] = {
        "kind": "spec",
        "content": {
            "key": "noise",
            "parameter": "Noise",
            "parameter_id": parameter_id,
            "parameter_version": 1,
            "value_type": "number",
            "value": "0",
            "unit": "dB",
            "condition_note": "one meter",
            "availability": "known",
            "nature": "decided",
            "item_status": "confirmed",
        },
        "source_refs": refs,
    }
    body["groups"]["items"].append(
        {
            "kind": "commercial_target",
            "content": {
                "target_price": {
                    "amount": "15",
                    "currency": "USD",
                    "basis": "retail",
                    "as_of": "2026-10-10",
                    "includes_tax": False,
                    "source": named_source(work),
                }
            },
        }
    )
    return body


def other_category(work):
    body = {
        "key": "view-scope-" + uuid4().hex,
        "name": "Other view scope",
        "purpose": "Synthetic unrelated category",
        "deidentified_confirmed": True,
        "idempotency_key": str(uuid4()),
    }
    preview = work.client.post("/v1/categories/preview", headers=work.headers, json=body)
    assert preview.status_code == 200, preview.text
    body["confirmation_token"] = preview.json()["confirmation_token"]
    created = work.client.post("/v1/categories", headers=work.headers, json=body)
    assert created.status_code == 201, created.text
    return created.json()["subject_id"]


@pytest.mark.parametrize("name", VIEWS)
def test_private_view_rechecks_actual_audience_tenant_and_category(work, name):
    proposal_id, _ = create(work)
    own = view(work, name, proposal_id)
    assert own.status_code == 200, own.text
    assert own.json()["proposal_id"] == proposal_id
    denied = view(work, name, proposal_id, actor=work.peer)
    assert denied.status_code == 404, denied.text
    foreign = view(work, name, proposal_id, actor=work.other_human)
    assert foreign.status_code == 403, foreign.text
    cross_category = view(work, name, proposal_id, category=other_category(work))
    assert cross_category.status_code == 404, cross_category.text


def test_http_comparison_preserves_parameter_versions_conditions_nature_and_zero(work):
    registered = publish(work, standard_condition="one meter")
    identity = registered["parameter_id"]
    proposal_id, _ = create(work, proposal_body(work, identity))
    publish(
        work,
        parameter_id=identity,
        expected_current_version=1,
        unit="dB(A)",
        standard_condition="three meters",
    )
    ref = named_source(work)
    common = {
        "parameter_id": identity,
        "parameter_version": 1,
        "unit": "dB",
        "condition_note": "one meter",
        "value": "0",
        "source_ref": ref,
    }
    entry = add_knowledge(
        work,
        kind="competitor",
        content={
            "brand": "Synthetic",
            "model": "Observed pump",
            "metrics": [
                {**common, "nature": "measured"},
                {**common, "value": "4", "nature": "claimed"},
                {**common, "condition_note": "two meters", "value": "5", "nature": "inferred"},
                {
                    **common,
                    "parameter_version": 2,
                    "unit": "dB(A)",
                    "condition_note": "three meters",
                    "value": "6",
                    "nature": "claimed",
                },
                {**common, "value": None, "nature": "unknown"},
            ],
            "prices": [
                {
                    "amount": "20",
                    "currency": "USD",
                    "price_type": "retail",
                    "observed_on": "2026-10-10",
                    "includes_tax": False,
                    "source_ref": ref,
                }
            ],
        },
    )
    response = view(work, "spec-benchmark", proposal_id, parameter_ids=[identity])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    groups = data["groups"]
    assert {(g["parameter_version"], g["unit"], g["condition_note"]) for g in groups} == {
        (1, "dB", "one meter"),
        (1, "dB", "two meters"),
        (2, "dB(A)", "three meters"),
    }
    observations = [row for group in groups for row in group["observations"]]
    competitor_rows = [row for row in observations if row["subject"]["type"] == "competitor"]
    assert len(competitor_rows) == 5
    assert {row["subject"]["id"] for row in competitor_rows} == {entry["entry_id"]}
    assert {row["evidence_kind"] for row in competitor_rows} == {
        "observed",
        "claimed",
        "inferred",
        "unknown",
    }
    target = next(row for row in observations if row["subject"]["type"] == "proposal")
    assert target["value"] == "0" and target["evidence_kind"] == "target"
    assert data["unknown_count"] == 1
    positioned = view(work, "positioning", proposal_id, parameter_ids=[identity])
    assert positioned.status_code == 200, positioned.text
    points = [p for group in positioned.json()["data"]["groups"] for p in group["points"]]
    assert any(point["subject"]["type"] == "proposal" and point["y"] == "0" for point in points)
    assert all(point["evidence_kind"] != "unknown" for point in points)
    assert all(point["source_refs"] for point in points)


@pytest.mark.parametrize("name", VIEWS)
def test_reviewer_views_bind_actual_frozen_submission_identity(work, name):
    registered = publish(work, standard_condition="one meter")
    identity = registered["parameter_id"]
    proposal_id, _ = create(work, proposal_body(work, identity))
    submit(work, proposal_id)
    submitted = read(work, proposal_id, work.peer).json()["submission"]
    publish(
        work,
        parameter_id=identity,
        expected_current_version=1,
        unit="dB(A)",
        standard_condition="changed current standard",
    )
    response = view(work, name, proposal_id, actor=work.peer)
    assert response.status_code == 200, response.text
    result = response.json()
    assert {key: result[key] for key in IDENTITY} == {
        "proposal_id": proposal_id,
        "revision": submitted["revision"],
        "document_digest": submitted["document_digest"],
        "submission_id": submitted["id"],
        "document_mode": "frozen",
    }
    if name == "spec-benchmark":
        group = next(g for g in result["data"]["groups"] if g["parameter_id"] == identity)
        assert group["parameter_version"] == 1 and group["unit"] == "dB"
        subject = next(s for s in result["data"]["subjects"] if s["type"] == "proposal")
        assert subject["document_identity"] == {key: result[key] for key in IDENTITY}
    owner = view(work, name, proposal_id)
    assert owner.status_code == 200, owner.text
    assert owner.json()["document_mode"] == "current"
    assert owner.json()["submission_id"] is None


def test_withdrawn_claim_disables_comparison_and_redacts_unmapped_feature_text(work):
    registered = publish(work, standard_condition="one meter")
    marker = "SYNTHETIC_PRIVATE_FEATURE_MARKER"
    source = artifact(work, body=marker)
    claim = record_claim(work, source, quote=marker, text=marker)
    reference = {
        "type": "claim",
        "id": claim["subject_id"],
        "version": 1,
        "line": 1,
        "quote": marker,
    }
    body = proposal_body(work, registered["parameter_id"], refs=[reference])
    body["groups"]["items"].append(
        {
            "kind": "section",
            "content": {"key": "features_in_out", "text": marker},
            "source_refs": [reference],
        }
    )
    proposal_id, _ = create(work, body)
    before = view(work, "spec-benchmark", proposal_id)
    assert before.status_code == 200, before.text
    assert marker in before.text
    save(work, withdraw_request(work, claim["subject_id"]))
    for name in ("spec-benchmark", "positioning", "feature-config"):
        response = view(work, name, proposal_id)
        assert response.status_code == 200, response.text
        assert marker not in response.text
        if name == "spec-benchmark":
            rows = [
                row for group in response.json()["data"]["groups"] for row in group["observations"]
            ]
            assert rows and all(not row["comparable"] and row["value"] is None for row in rows)
            feature = response.json()["data"]["subjects"][0]["unmapped_features"][0]
            assert feature["text"] is None and feature["availability"] == "unknown"


def test_real_g0_product_retains_honest_fixed_baseline_and_target_price_uncertainty(work):
    registered = publish(work, standard_condition="one meter")
    proposal_id, _ = create(work, proposal_body(work, registered["parameter_id"]))
    submit(work, proposal_id)
    approved, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    result = approved["result"]
    response = view(work, "spec-benchmark", proposal_id)
    assert response.status_code == 200, response.text
    target = response.json()["data"]["subjects"][0]
    assert target["type"] == "proposal" and target["id"] == proposal_id
    fixed = work.client.get(
        f"/v1/categories/{work.category}/products/{result['product_id']}/baseline",
        headers=work.headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["baseline_kind"] == "g0"
    assert fixed.json()["definition"]["id"] == result["definition_id"]
    with human_session(work) as session:
        compared = compare(
            session,
            work.ctx,
            {
                "subjects": [{"type": "product", "id": UUID(result["product_id"])}],
                "parameter_ids": [registered["parameter_id"]],
            },
        )
    product = compared["subjects"][0]
    assert product["baseline_kind"] == "g0"
    assert product["definition_id"] == result["definition_id"]
    assert product["definition_revision"] == 1
    price = product["prices"][0]
    assert Decimal(price["amount"]) == Decimal("15") and price["availability"] == "unknown"
    assert price["comparable"] is False and "price_source_unavailable" in price["reasons"]
