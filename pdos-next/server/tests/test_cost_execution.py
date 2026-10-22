"""Fixed Build cost sources -> common T1 snapshot -> canonical T0 estimate.

Only the root thread runs this candidate against its verified isolated PG.
Synthetic estimates are not supplier commitments, ERP actuals or approval.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from security_fixture import ensure_scanned, secured_runtime  # noqa: F401 - local fixture
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_demand import demand_work  # noqa: F401 - imported fixed-demand fixture
from test_builds import configuration, definition, project  # noqa: F401 - fixture dependencies
from test_project_first_plan import accepted, cmd, post
from test_supply_execution import confirmation_consumed, count, expire_grant, withdraw

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.cost_execution.models import (
    CostCapture,
    CostCurrent,
    CostEstimate,
    CostInputSnapshot,
)
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    OriginalSecurity,
    Outbox,
    Receipt,
    RequestKey,
    UploadedOriginal,
    now,
)
from pdos_next.service import Context, digest, execute

INPUTS = "cost.inputs.record"
ESTIMATE = "cost.estimate.compute"
TEXT = (
    "Synthetic unverified costs: motor 0.10 USD per ea; assembly 2 USD per hour; "
    "NRE tooling 100 USD per whole item. Prices exclude tax and include freight."
)


@pytest.fixture
def cost_work(setup, demand_work):  # noqa: F811 - imported fixture
    observed_at = now() - timedelta(seconds=1)
    source_text = TEXT + f" Synthetic budget EUR/USD rate 1.25 at {observed_at.isoformat()}."
    registered = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic unverified cost assumptions",
                "content": source_text,
                "source_label": "Synthetic isolated cost fixture",
                "visibility": "private",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    return {
        **demand_work,
        "cost_source": registered.json()["subject_id"],
        "source_text": source_text,
        "rate_observed_at": observed_at.isoformat(),
    }


def reference(work):
    return {
        "artifact_id": work["cost_source"],
        "expected_revision": 1,
        "line": 1,
        "quote": work["source_text"],
    }


def prepare(setup, work, payload, *, headers=None, product=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/products/{product or setup.product}/cost-captures",
        headers=headers or setup.headers,
        json=payload,
    )


def captured(setup, work, payload):
    response = prepare(setup, work, payload)
    assert response.status_code == 200, response.text
    return response.json()


def inputs_command(setup, capture):
    command = cmd(setup, INPUTS, capture["inputs_record_payload"])
    command["source_read_set"] = capture["required_source_read_set"]
    return command


def recorded(setup, work, payload):
    capture = captured(setup, work, payload)
    receipt, prepared = accepted(setup, inputs_command(setup, capture))
    return capture, receipt, prepared


def estimate_command(setup, work, receipt, capture):
    command = cmd(
        setup,
        ESTIMATE,
        {
            "build_id": work["build_id"],
            "expected_build_revision": 1,
            "cost_input_id": receipt["subject_id"],
            "expected_cost_input_revision": receipt["subject_revision"],
        },
    )
    command["source_read_set"] = capture["required_source_read_set"]
    return command


def estimated(setup, work, payload):
    capture, inputs, _ = recorded(setup, work, payload)
    command = estimate_command(setup, work, inputs, capture)
    response = post(setup, command)
    assert response.status_code == 200, response.text
    return capture, inputs, response.json(), command


def listed(setup, *, headers=None):
    response = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/costs",
        headers=headers or setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def price_input(
    work, *, price_id="motor-price", subject_kind="material", subject_id=None, **changes
):
    material = next(row for row in work["result"]["demands"] if row["item_id"] == "motor")
    return {
        "price_id": price_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id or material["material_id"],
        "stage": "estimate",
        "basis": "unit",
        "amount": "0.10",
        "price_quantity": "1",
        "unit": "ea",
        "currency": "USD",
        "tax_basis": "exclusive",
        "freight_basis": "included",
        "scope_assumption": "Synthetic sourced assumption, not an approved supplier decision",
        "sources": [reference(work)],
        **changes,
    }


def capture_input(work, **changes):
    return {
        "capture_key": str(uuid4()),
        "expected_product_revision": 1,
        "build_id": work["build_id"],
        "expected_build_revision": 1,
        "reason": "Synthetic sourced cost assumptions",
        "sources": [reference(work)],
        "cost_scope": {
            "currency": "USD",
            "tax_basis": "exclusive",
            "freight_basis": "included",
            "coverage": "materials_only",
            "rate_purpose": "budget",
            "max_rate_age_days": 7,
            "nre_policy": "excluded",
            "nre_volume": None,
            "assumptions": ["Synthetic selected scope; housing quantity remains unknown"],
        },
        "prices": [price_input(work)],
        "material_prices": [{"bom_item_id": "motor", "price_id": "motor-price"}],
        "process": None,
        "rates": [],
        "nre_price_ids": [],
        **changes,
    }


def rate_input(work, **changes):
    return {
        "rate_id": "synthetic-budget-rate",
        "from_currency": "EUR",
        "to_currency": "USD",
        "rate": "1.25",
        "purpose": "budget",
        "observed_at": work["rate_observed_at"],
        "sources": [reference(work)],
        **changes,
    }


def quote_input(work, **changes):
    return price_input(
        work,
        stage="quote",
        valid_from=(now() - timedelta(hours=1)).isoformat(),
        valid_until=(now() + timedelta(minutes=5)).isoformat(),
        minimum_quantity="22",
        maximum_quantity="22",
        **changes,
    )


def result_for(setup, receipt):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(CostEstimate, UUID(receipt["subject_id"]))
        return deepcopy(row.projection["result"])


def calculate(setup, work, payload):
    capture, inputs, result, command = estimated(setup, work, payload)
    return result_for(setup, result), capture, inputs, result, command


def cost_codes(result):
    return {issue["code"] for issue in result["issues"]}


def set_clock(patch, instant):
    # Both services receive the same synthetic trusted server clock; using a
    # later command time alone would correctly fail the demand future-time guard.
    patch.setattr("pdos_next.domain.cost_execution.service.now", lambda: instant)
    patch.setattr("pdos_next.domain.builds.demand.now", lambda: instant)


def test_capture_normalized_retry_keeps_fixed_inputs_and_never_applies_cost(setup, cost_work):
    unknown = next(row for row in cost_work["result"]["demands"] if row["item_id"] == "unknown")
    payload = capture_input(cost_work)
    payload["prices"].append(
        price_input(
            cost_work, price_id="housing-price", subject_id=unknown["material_id"], amount=None
        )
    )
    payload["material_prices"].append({"bom_item_id": "unknown", "price_id": "housing-price"})
    first = captured(setup, cost_work, payload)
    reordered = deepcopy(payload)
    reordered["prices"].reverse()
    reordered["material_prices"].reverse()
    next(price for price in reordered["prices"] if price["price_id"] == "motor-price")["amount"] = (
        "0.1000"
    )
    replay = captured(setup, cost_work, reordered)
    assert replay == first
    assert first["capture"]["status"] == "unapplied"
    assert first["capture"]["applied_input_id"] is None
    assert {ref["artifact_id"] for ref in first["required_source_read_set"]} == {
        cost_work["source"],
        cost_work["cost_source"],
    }
    assert count(setup, CostCapture) == 1
    for model in (CostInputSnapshot, CostCurrent, CostEstimate):
        assert count(setup, model) == 0
    conflicting = deepcopy(payload)
    conflicting["prices"][0]["amount"] = "0.20"
    refused = prepare(setup, cost_work, conflicting)
    assert refused.status_code == 409 and refused.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert count(setup, CostCapture) == 1


def test_common_t1_and_canonical_t0_reuse_fixed_basis_and_keep_unknown_total(setup, cost_work):
    capture = captured(setup, cost_work, capture_input(cost_work))
    command = inputs_command(setup, capture)
    assert post(setup, command).json()["code"] == "CONFIRMATION_REQUIRED"
    receipt, prepared = accepted(setup, command)
    assert receipt["subject_type"] == "cost_inputs" and receipt["subject_revision"] == 1
    assert post(setup, prepared).json()["id"] == receipt["id"]
    duplicate = {**prepared, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    assert post(setup, duplicate).json()["id"] == receipt["id"]
    assert count(setup, Confirmation, operation=INPUTS) == 1
    assert confirmation_consumed(setup, prepared) is True
    compute = estimate_command(setup, cost_work, receipt, capture)
    assert post(setup, compute, True).status_code == 403
    before = count(setup, Confirmation)
    computed = post(setup, compute)
    assert computed.status_code == 200, computed.text
    estimate = computed.json()
    assert estimate["subject_type"] == "cost_estimate"
    assert post(setup, compute).json()["id"] == estimate["id"]
    assert (
        post(
            setup, {**compute, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
        ).json()["id"]
        == estimate["id"]
    )
    assert count(setup, Confirmation) == before
    assert (
        count(setup, CostInputSnapshot)
        == count(setup, CostCurrent)
        == count(setup, CostEstimate)
        == 1
    )
    result = result_for(setup, estimate)
    assert Decimal(result["known_build_subtotal"]) == Decimal("2.2")
    assert result["build_candidate"] is result["per_product_candidate"] is None
    assert result["complete_in_selected_scope"] is False
    assert "unpriced_bom_item" in cost_codes(result)
    assert (
        result["input_snapshot"]["basis"]
        == cost_work["result"]["coverage"]["input_snapshot"]["basis"]
    )
    motor = next(line for line in result["lines"] if line["line_id"] == "material:motor")
    assert Decimal(motor["quantity_for_build"]) == Decimal(22)
    assert Decimal(motor["quantity_per_product"]) == Decimal("2.2")
    assert Decimal(motor["build_candidate"]) == Decimal("2.2")
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        draft = session.get(CostCapture, UUID(capture["capture"]["id"]))
        saved = session.get(CostInputSnapshot, UUID(receipt["subject_id"]))
        projected = session.get(CostEstimate, UUID(estimate["subject_id"]))
        assert saved.id == draft.input_id
        assert saved.inputs == draft.proposed_inputs["inputs"]
        assert datetime.fromisoformat(saved.inputs["ref"]["captured_at"]) == draft.created_at
        assert saved.bound_demand == draft.bound_demand == projected.bound_demand
        assert saved.bound_demand["demand"]["lines"] == cost_work["result"]["demands"]
        assert saved.bound_demand["manufacturing_operation_ids"] == ["assembly"]
        for value in (receipt, estimate):
            for model in (Audit, Outbox):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.receipt_id == UUID(value["id"]))
                    )
                    == 1
                )


@pytest.mark.parametrize(
    "case,code,subtotal",
    [
        ("tier_exact", None, "2.2"),
        ("tier_outside", "quote_quantity_not_applicable", "0"),
        ("expired", "quote_not_valid", "0"),
        ("unit", "price_unit_incomparable", "0"),
        ("freight", "freight_basis_mismatch", "0"),
    ],
)
def test_price_applicability_is_explicit_and_does_not_invent_known_money(
    setup, cost_work, case, code, subtotal
):
    price = quote_input(cost_work)
    if case == "tier_outside":
        price["minimum_quantity"] = "23"
        price["maximum_quantity"] = None
    elif case == "expired":
        price["valid_until"] = (now() - timedelta(seconds=1)).isoformat()
    elif case == "unit":
        price["unit"] = "kg"
    elif case == "freight":
        price["freight_basis"] = "excluded"
    result, *_ = calculate(setup, cost_work, capture_input(cost_work, prices=[price]))
    assert Decimal(result["known_build_subtotal"]) == Decimal(subtotal)
    assert result["build_candidate"] is None
    if code:
        assert code in cost_codes(result)
    else:
        line = next(line for line in result["lines"] if line["line_id"] == "material:motor")
        assert Decimal(line["quantity_in_price_unit"]) == Decimal(22)
        assert line["issues"] == []


def test_tax_conversion_and_budget_fx_keep_original_money_and_real_observation_time(
    setup, cost_work
):
    payload = capture_input(cost_work)
    payload["prices"][0].update(
        amount="0.12", currency="EUR", tax_basis="inclusive", tax_rate="0.2"
    )
    payload["rates"] = [rate_input(cost_work)]
    result, _, inputs, _, _ = calculate(setup, cost_work, payload)
    assert Decimal(result["known_build_subtotal"]) == Decimal("2.75")
    line = next(line for line in result["lines"] if line["line_id"] == "material:motor")
    assert Decimal(line["original_build_amount"]) == Decimal("2.64")
    assert line["original_currency"] == "EUR" and line["rate_id"] == "synthetic-budget-rate"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        saved = session.get(CostInputSnapshot, UUID(inputs["subject_id"]))
        observed = datetime.fromisoformat(saved.inputs["rates"][0]["ref"]["captured_at"])
        assert observed == datetime.fromisoformat(cost_work["rate_observed_at"])
        assert observed < saved.created_at
        assert saved.inputs["rates"][0]["ref"]["sha256"]


@pytest.mark.parametrize(
    "case,code",
    [
        ("purpose", "exchange_rate_not_applicable"),
        ("age", "exchange_rate_not_applicable"),
        ("inverse", "exchange_rate_missing_or_ambiguous"),
    ],
)
def test_fx_requires_current_age_purpose_and_explicit_direct_pair(setup, cost_work, case, code):
    payload = capture_input(cost_work)
    payload["prices"][0]["currency"] = "EUR"
    rate = rate_input(cost_work)
    if case == "purpose":
        rate["purpose"] = "spot"
    elif case == "age":
        rate["observed_at"] = (now() - timedelta(days=8)).isoformat()
    else:
        rate.update(from_currency="USD", to_currency="EUR")
    payload["rates"] = [rate]
    result, *_ = calculate(setup, cost_work, payload)
    assert Decimal(result["known_build_subtotal"]) == 0
    assert result["build_candidate"] is None and code in cost_codes(result)


@pytest.mark.parametrize("case", ["known", "loss_unknown", "wrong_operation"])
def test_process_cost_consumes_exact_manufacturing_keys_and_explicit_good_product_quantity(
    setup, cost_work, case
):
    payload = capture_input(cost_work)
    payload["cost_scope"]["coverage"] = "materials_and_process"
    payload["prices"].append(
        price_input(
            cost_work,
            price_id="assembly-price",
            subject_kind="process",
            subject_id="assembly",
            amount="2",
            unit="h",
        )
    )
    payload["process"] = {
        "assumption": "Synthetic explicit minutes per good product; no cycle-time inference",
        "sources": [reference(cost_work)],
        "operations": [
            {
                "operation_id": "assembly",
                "quantity_per_product": "30",
                "unit": "min",
                "loss_rate": "0.1",
                "price_id": "assembly-price",
                "sources": [reference(cost_work)],
            }
        ],
    }
    if case == "wrong_operation":
        payload["process"]["operations"][0]["operation_id"] = "unrelated-operation"
        refused = prepare(setup, cost_work, payload)
        assert refused.status_code in {403, 409}, refused.text
        assert count(setup, CostCapture) == 0
        return
    if case == "loss_unknown":
        payload["process"]["operations"][0]["loss_rate"] = None
    result, *_ = calculate(setup, cost_work, payload)
    assert Decimal(result["known_build_subtotal"]) == Decimal("13.2" if case == "known" else "2.2")
    line = next(line for line in result["lines"] if line["line_id"] == "process:assembly")
    if case == "known":
        assert result["decimal_precision"] == 38
        assert result["rounding"] == (
            "ROUND_HALF_EVEN at precision 38; no currency display quantization"
        )
        # min -> h first rounds the repeating 1/60 factor at the declared
        # precision. Allow only that tiny unit-conversion tail, not money drift.
        assert abs(Decimal(line["quantity_in_price_unit"]) - Decimal("5.5")) <= Decimal("1e-36")
        assert Decimal(line["build_candidate"]) == 11
    else:
        assert line["build_candidate"] is None
        assert "process_quantity_unknown" in cost_codes(result)
    assert result["build_candidate"] is None


@pytest.mark.parametrize(
    "policy,volume", [("separate", None), ("amortize", None), ("amortize", "100")]
)
def test_nre_preserves_whole_fee_and_explicit_volume_without_completing_unknown_materials(
    setup, cost_work, policy, volume
):
    payload = capture_input(cost_work)
    payload["cost_scope"].update(nre_policy=policy, nre_volume=volume)
    payload["prices"].append(
        price_input(
            cost_work,
            price_id="tooling-price",
            subject_kind="nre",
            subject_id="synthetic-tooling-fee",
            basis="nre",
            amount="100",
            unit="item",
        )
    )
    payload["nre_price_ids"] = ["tooling-price"]
    result, *_ = calculate(setup, cost_work, payload)
    assert Decimal(result["known_build_subtotal"]) == Decimal("2.2")
    assert Decimal(result["known_nre_subtotal"]) == 100
    assert (
        result["build_candidate"]
        is result["nre_candidate"]
        is result["including_amortized_nre"]
        is None
    )
    nre = next(line for line in result["lines"] if line["category"] == "nre")
    assert Decimal(nre["quantity_for_build"]) == 1 and Decimal(nre["build_candidate"]) == 100
    if policy == "amortize" and volume is None:
        assert "nre_volume_missing" in cost_codes(result)


@pytest.mark.parametrize("field", ["scope", "ref", "visibility"])
def test_client_cannot_inject_trusted_scope_price_ref_or_wider_audience(setup, cost_work, field):
    payload = capture_input(cost_work)
    if field == "scope":
        payload["scope"] = {"audience": f"product:{setup.product}"}
    elif field == "ref":
        payload["prices"][0]["ref"] = {"state": "current", "sha256": "0" * 64}
    else:
        payload["visibility"] = "product"
    refused = prepare(setup, cost_work, payload)
    assert refused.status_code == 422, refused.text
    assert count(setup, CostCapture) == 0


@pytest.mark.parametrize("binding", ["build", "material"])
def test_typed_ids_still_require_the_server_fixed_build_and_material_scope(
    setup, cost_work, binding
):
    payload = capture_input(cost_work)
    if binding == "build":
        payload["build_id"] = str(uuid4())
    else:
        payload["prices"][0]["subject_id"] = str(uuid4())
    refused = prepare(setup, cost_work, payload)
    assert refused.status_code == 403 and refused.json()["code"] == "FORBIDDEN_SCOPE"
    assert count(setup, CostCapture) == 0


@pytest.mark.parametrize("actor", ["peer", "other_human"])
def test_private_cost_sources_and_results_do_not_leak_to_peer_or_other_tenant(
    setup, cost_work, actor
):
    calculate(setup, cost_work, capture_input(cost_work))
    headers = {"Authorization": f"Bearer {setup.tokens[getattr(setup, actor)]}"}
    refused = prepare(setup, cost_work, capture_input(cost_work), headers=headers)
    assert refused.status_code == 403, refused.text
    read = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/costs", headers=headers
    )
    if actor == "peer":
        assert read.status_code == 200
        assert read.json()["captures"] == read.json()["inputs"] == read.json()["estimates"] == []
        assert read.json()["current_by_build"] == {}
    else:
        assert read.status_code == 403


@pytest.mark.parametrize("change", ["revision", "withdraw", "grant"])
def test_capture_and_committed_estimate_replays_recheck_current_sources_and_rights(
    setup, cost_work, change
):
    payload = capture_input(cost_work)
    _, _, _, _, command = calculate(setup, cost_work, payload)
    if change == "grant":
        expire_grant(setup)
    elif change == "withdraw":
        withdraw(setup, cost_work["cost_source"])
    else:
        with Session(setup.admin) as session, session.begin():
            session.execute(
                update(Artifact)
                .where(Artifact.id == UUID(cost_work["cost_source"]))
                .values(revision=2)
            )
    responses = (prepare(setup, cost_work, payload), post(setup, command))
    if change == "grant":
        assert all(response.status_code == 403 for response in responses)
        assert count(setup, CostEstimate) == 0
    else:
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json()["capture"]["source_status"] == "needs_recheck"
        fresh = {**payload, "capture_key": str(uuid4())}
        denied = prepare(setup, cost_work, fresh)
        assert denied.status_code == 409
        assert denied.json()["code"] == (
            "SOURCE_UNAVAILABLE" if change == "withdraw" else "SOURCE_STALE"
        )
    assert all(
        count(setup, model, physical=True) == 1
        for model in (CostCapture, CostInputSnapshot, CostEstimate)
    )


@pytest.mark.parametrize("state", ["private_peer", "failed"])
@pytest.mark.usefixtures("secured_runtime")
def test_original_acl_and_parse_state_are_rechecked_even_with_readable_derived_price_text(
    setup, cost_work, state
):
    original_id, artifact_id = uuid4(), uuid4()
    blob = b"Synthetic original cost evidence"
    object_hash = hashlib.sha256(blob).hexdigest()
    with Session(setup.admin) as session, session.begin():
        session.add(
            UploadedOriginal(
                id=original_id,
                tenant_id=setup.tenant,
                product_id=setup.product,
                owner_id=setup.peer if state == "private_peer" else setup.human,
                title="Synthetic cost original",
                filename="synthetic-cost.txt",
                source_label="Synthetic",
                visibility="private",
                media_type="text/plain",
                byte_count=len(blob),
                content_hash=object_hash,
                storage_key=f"originals/{original_id.hex}/v1/{object_hash}",
                revision=2,
                status="failed" if state == "failed" else "parsed",
                scan_status="not_scanned",
            )
        )
        session.flush()
        session.add(
            OriginalSecurity(
                tenant_id=setup.tenant,
                product_id=setup.product,
                original_id=original_id,
                epoch=1,
                source_state="active",
                disposition="active",
            )
        )
        session.add(
            Artifact(
                id=artifact_id,
                tenant_id=setup.tenant,
                product_id=setup.product,
                owner_id=setup.human,
                title="Synthetic derived cost text",
                source_label="Synthetic",
                visibility="private",
                content=cost_work["source_text"],
                content_hash=digest(cost_work["source_text"]),
                original_id=original_id,
            )
        )
    if state == "failed":
        # Reach the explicit parsed-state guard, rather than failing merely
        # because the hand-built original has no scan/security fixture facts.
        ensure_scanned(
            setup.engine,
            {
                "category_id": str(setup.category),
                "actor_id": str(setup.human),
                "requester_id": str(setup.human),
                "tenant_id": str(setup.tenant),
                "product_id": str(setup.product),
                "subject_id": str(original_id),
            },
        )
    original_work = {**cost_work, "cost_source": str(artifact_id)}
    refused = prepare(setup, original_work, capture_input(original_work))
    assert refused.status_code in {403, 409}, refused.text
    assert refused.json()["code"] in {"SOURCE_UNAVAILABLE", "FORBIDDEN_SCOPE"}
    assert count(setup, CostCapture) == 0


@pytest.mark.parametrize("change", ["reason", "source_reads"])
def test_common_confirmation_does_not_cover_changed_cost_material(setup, cost_work, change):
    capture = captured(setup, cost_work, capture_input(cost_work))
    preview = post(setup, inputs_command(setup, capture), True)
    assert preview.status_code == 200, preview.text
    command = preview.json()["command"]
    original = deepcopy(command)
    if change == "reason":
        command["payload"]["reason"] = "Different unreviewed cost reason"
    else:
        command["source_read_set"] = []
    refused = post(setup, command)
    assert refused.status_code == 409, refused.text
    assert count(setup, CostInputSnapshot) == count(setup, CostCurrent) == 0
    assert confirmation_consumed(setup, original) is False


def test_quote_end_drift_requires_new_review_then_can_save_explicit_unknown(
    setup, cost_work, monkeypatch
):
    price = quote_input(cost_work)
    capture = captured(setup, cost_work, capture_input(cost_work, prices=[price]))
    original_capture = deepcopy(capture["capture"]["input_snapshot"])
    preview = post(setup, inputs_command(setup, capture), True)
    assert preview.status_code == 200, preview.text
    command = preview.json()["command"]
    expiry = datetime.fromisoformat(price["valid_until"])
    with monkeypatch.context() as patch:
        set_clock(patch, expiry)
        refused = post(setup, command)
        assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
        assert confirmation_consumed(setup, command) is False
        assert count(setup, CostInputSnapshot) == 0
        saved, renewed = accepted(setup, inputs_command(setup, capture))
        assert renewed["payload"]["confirmation_token"] != command["payload"]["confirmation_token"]
        computed = post(setup, estimate_command(setup, cost_work, saved, capture))
        assert computed.status_code == 200, computed.text
        result = result_for(setup, computed.json())
        assert "quote_not_valid" in cost_codes(result)
        assert Decimal(result["known_build_subtotal"]) == 0 and result["build_candidate"] is None
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(CostCapture, UUID(capture["capture"]["id"]))
        assert row.input_snapshot == original_capture


@pytest.mark.parametrize("operation", [INPUTS, ESTIMATE])
def test_final_receipt_failure_rolls_back_cost_pointer_confirmation_and_outbox(
    setup, cost_work, monkeypatch, operation
):
    from pdos_next import service

    if operation == INPUTS:
        capture = captured(setup, cost_work, capture_input(cost_work))
        preview = post(setup, inputs_command(setup, capture), True)
        assert preview.status_code == 200, preview.text
        command = preview.json()["command"]
    else:
        capture, inputs, _ = recorded(setup, cost_work, capture_input(cost_work))
        command = estimate_command(setup, cost_work, inputs, capture)
    tables = (CostInputSnapshot, CostCurrent, CostEstimate, Receipt, Audit, Outbox, RequestKey)
    before = {model: count(setup, model) for model in tables}
    original = service.append_receipt

    def fail(*args, **kwargs):
        receipt = original(*args, **kwargs)
        if args[2].operation == operation:
            raise DomainError("SYNTHETIC_COST_RECEIPT_FAILURE", "Synthetic final-stage rollback")
        return receipt

    with monkeypatch.context() as patch:
        patch.setattr(service, "append_receipt", fail)
        refused = post(setup, command)
    assert refused.json()["code"] == "INTERNAL_ERROR", refused.text
    assert {model: count(setup, model) for model in tables} == before
    if operation == INPUTS:
        assert confirmation_consumed(setup, command) is False
    assert count(setup, CostCapture) == 1
    assert post(setup, command).status_code == 200
    assert count(setup, Receipt, operation=operation) == 1


def test_competing_successors_preserve_fixed_history_and_only_one_current_pointer(setup, cost_work):
    _, first, _ = recorded(setup, cost_work, capture_input(cost_work))
    commands = []
    for amount in ("0.20", "0.30"):
        payload = capture_input(cost_work)
        payload["prices"][0]["amount"] = amount
        capture = captured(setup, cost_work, payload)
        command = inputs_command(setup, capture)
        assert command["payload"]["expected_previous_input_id"] == first["subject_id"]
        preview = post(setup, command, True)
        assert preview.status_code == 200, preview.text
        commands.append(preview.json()["command"])
    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda value: post(setup, value), commands))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    loser = next(
        command
        for command, response in zip(commands, responses, strict=True)
        if response.status_code == 409
    )
    assert winner["subject_revision"] == 2
    assert confirmation_consumed(setup, loser) is False
    assert count(setup, CostCurrent) == 1
    assert count(setup, CostInputSnapshot) == count(setup, Receipt, operation=INPUTS) == 2
    data = listed(setup)
    assert data["current_by_build"][cost_work["build_id"]] == {
        "input_id": winner["subject_id"],
        "revision": 2,
    }
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        assert Decimal(
            session.get(CostInputSnapshot, UUID(first["subject_id"])).inputs["prices"][0]["amount"]
        ) == Decimal("0.10")


def test_estimate_history_is_unchanged_after_new_input_and_old_receipt_replays(setup, cost_work):
    _, first_inputs, first_estimate, command = estimated(setup, cost_work, capture_input(cost_work))
    original = result_for(setup, first_estimate)
    next_payload = capture_input(cost_work)
    next_payload["prices"][0]["amount"] = "0.20"
    _, newer, new_estimate, _ = estimated(setup, cost_work, next_payload)
    assert newer["subject_revision"] == 2
    assert Decimal(result_for(setup, new_estimate)["known_build_subtotal"]) == Decimal("4.4")
    assert post(setup, command).json()["id"] == first_estimate["id"]
    assert result_for(setup, first_estimate) == original
    data = listed(setup)
    previous = next(row for row in data["estimates"] if row["id"] == first_estimate["subject_id"])
    assert previous["freshness"] == "requires_recalculation"
    assert previous["cost_input_id"] == first_inputs["subject_id"]
    assert count(setup, CostEstimate) == 2


def test_cost_history_is_immutable_rls_scoped_and_agent_has_no_direct_or_qualified_write(
    setup, cost_work
):
    capture, inputs, result, command = estimated(setup, cost_work, capture_input(cost_work))
    for model, identity in (
        (CostCapture, capture["capture"]["id"]),
        (CostInputSnapshot, inputs["subject_id"]),
        (CostEstimate, result["subject_id"]),
    ):
        with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
            session.execute(
                update(model)
                .where(model.id == UUID(identity))
                .values(reason="Invalid cost history overwrite")
            )
    with Session(setup.engine) as session:
        for model in (CostCapture, CostInputSnapshot, CostCurrent, CostEstimate):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with Session(setup.admin) as session:
        for model in (CostCapture, CostInputSnapshot, CostCurrent, CostEstimate):
            assert session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = CAST(:name AS regclass)"
                ),
                {"name": model.__tablename__},
            ).one() == (True, True)
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )
    with (
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
        pytest.raises(DomainError) as refused,
    ):
        execute(
            session,
            Context(setup.tenant, setup.agent, setup.human, category_id=setup.category),
            Command.model_validate(command),
        )
    assert refused.value.code == "FORBIDDEN_SCOPE"
    assert count(setup, CostEstimate) == 1
