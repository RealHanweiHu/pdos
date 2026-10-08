"""Real scoped T1 configuration transactions. Root runs these against its verified test DB."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.configurations import service
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.configurations.schemas import (
    EngineeringBomRevisePayload,
    NpiProcessRevisePayload,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Grant, Outbox, Product, Receipt, now
from pdos_next.service import Context

OPERATIONS = {"engineering.bom.revise", "engineering.configuration.create", "npi.process.revise"}
TEXT = "Synthetic component and operation are unverified."


def command(setup, operation, payload, reads):
    return {
        "command_id": str(uuid4()), "idempotency_key": str(uuid4()), "operation": operation,
        "product_id": str(setup.product), "expected_revision": 1,
        "source_read_set": deepcopy(reads), "payload": deepcopy(payload),
    }


def post(setup, request, preview=False, headers=None):
    return setup.client.post(
        "/v1/commands" + ("/preview" if preview else ""),
        headers=headers or setup.headers, json=request,
    )


def accepted(setup, request):
    reviewed = post(setup, request, True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    saved = post(setup, prepared)
    assert saved.status_code == 200, saved.text
    return saved.json(), prepared, reviewed.json()["review"]


def source_definition(setup):
    source = post(setup, command(setup, "evidence.artifact.register", {
        "title": "Synthetic configuration input", "content": TEXT,
        "source_label": "Unverified isolated fixture", "visibility": "private",
    }, []))
    assert source.status_code == 200, source.text
    artifact = source.json()["subject_id"]
    reference = {"artifact_id": artifact, "expected_revision": 1, "line": 1, "quote": TEXT}
    reads = [{"artifact_id": artifact, "expected_revision": 1}]
    defined = post(setup, command(setup, "product.definition.draft", {
        "title": "Synthetic definition", "purpose": "Verify fixed engineering configuration",
        "use_cases": ["Synthetic development only"], "sources": [reference],
        "change_reason": "First synthetic draft",
    }, reads))
    assert defined.status_code == 200, defined.text
    return {"artifact_id": artifact, "definition_id": defined.json()["subject_id"],
            "reads": reads, "reference": reference}


def bom_payload(reference, number=None):
    return {
        "name": "Synthetic BOM", "reason": "Preserve material identity and unknown quantity",
        "sources": [reference], "visibility": "private",
        "previous_id": None, "expected_previous_revision": None,
        "lines": [{"key": "housing", "part": {
            "name": "Synthetic housing", "internal_number": number or f"RD-{uuid4()}",
            "erp_number": None, "customer_number": None, "mapping_version": None,
            "external_design_refs": [],
        }, "part_id": None, "expected_part_revision": None, "quantity": None,
            "unit": "piece", "loss_rate": None, "critical": True, "notes": None}],
    }


def configuration_chain(setup):
    """Reusable real source→definition→BOM→engineering→manufacturing T1 fixture chain."""
    chain = source_definition(setup)
    receipts, requests = {}, {}
    bom, requests["bom"], _ = accepted(setup, command(
        setup, "engineering.bom.revise", bom_payload(chain["reference"]), chain["reads"],
    ))
    chain["bom_id"] = bom["subject_id"]
    receipts["bom"] = bom
    engineering, requests["engineering"], _ = accepted(setup, command(
        setup, "engineering.configuration.create", {
            "name": "Synthetic engineering draft", "reason": "Pin unapproved definition and BOM",
            "sources": [chain["reference"]], "definition_id": chain["definition_id"],
            "expected_definition_revision": 1, "bom_id": chain["bom_id"],
            "expected_bom_revision": 1, "mechanical": None, "electronic": None, "firmware": None,
        }, chain["reads"],
    ))
    chain["engineering_id"] = engineering["subject_id"]
    receipts["engineering"] = engineering
    process, requests["process"], _ = accepted(setup, command(
        setup, "npi.process.revise", {
            "name": "Synthetic independent manufacturing draft",
            "reason": "Preserve unverified process requirements",
            "sources": [chain["reference"]],
            "engineering_configuration_id": chain["engineering_id"],
            "expected_engineering_revision": 1, "site": None, "line": None,
            "operations": [{"key": "assemble", "name": "Synthetic assembly", "kind": "assembly",
                            "bom_line_keys": ["housing"], "sop": None,
                            "resource_requirements": [{"kind": "equipment",
                                                       "name": "Unspecified synthetic fixture",
                                                       "external_id": None,
                                                       "qualification": None}],
                            "cycle_time_minutes": None, "acceptance_criterion": None}],
        }, chain["reads"],
    ))
    chain["process_id"] = process["subject_id"]
    receipts["process"] = process
    chain.update({"receipts": receipts, "requests": requests})
    return chain


def listed(setup):
    response = setup.client.get(
        f"/v1/products/{setup.product}/configurations", headers=setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def revision_payload(bom, reference, quantity="2"):
    line = bom["lines"][0]
    return {
        "name": bom["name"], "visibility": bom["visibility"],
        "previous_id": bom["id"], "expected_previous_revision": bom["revision"],
        "reason": f"Synthetic revised quantity {quantity}", "sources": [reference],
        "lines": [{"key": line["key"], "part_id": line["part_id"],
                   "expected_part_revision": line["expected_part_revision"], "part": None,
                   "quantity": quantity, "unit": line["unit"], "loss_rate": "0.05",
                   "critical": True}],
    }


def test_real_chain_preserves_two_configurations_unknowns_and_audit_outbox(setup):
    chain = configuration_chain(setup)
    values = listed(setup)
    assert values["unavailable_count"] == 0
    bom, engineering, process = (values[key][0] for key in ("boms", "engineering", "processes"))
    assert bom["lines"][0]["quantity"] is None and bom["lines"][0]["loss_rate"] is None
    assert bom["lines"][0]["part_id"] == bom["lines"][0]["part"]["id"]
    assert bom["lines"][0]["part"]["erp_number"] is None
    assert engineering["definition_id"] == chain["definition_id"]
    assert engineering["bom"]["id"] == chain["bom_id"]
    assert engineering["design_versions"] == {"mechanical": None, "electronic": None,
                                                "firmware": None}
    assert process["engineering_configuration_id"] == engineering["id"]
    assert process["site"] is process["line"] is None
    assert process["qualification_status"] == "unknown"
    operation = process["operations"][0]
    assert operation["sop"] is operation["cycle_time_minutes"] is None
    assert operation["resource_requirements"][0]["qualification"] is None
    for value in (bom, engineering, process):
        assert value["status"] == "draft" and value["source_status"] == "current"
        assert value["required_source_read_set"] == chain["reads"]
        assert value["previous_id"] is None and value["revision"] == 1
    with tenant_session(setup.engine, setup.tenant) as s:
        for receipt in chain["receipts"].values():
            assert s.scalar(select(Audit.id).where(Audit.receipt_id == UUID(receipt["id"])))
            assert s.scalar(select(Outbox.id).where(Outbox.receipt_id == UUID(receipt["id"])))
        assert s.scalar(select(func.count()).select_from(PartIdentity)) == 1


def test_t1_review_rejects_unconfirmed_or_changed_quantity(setup):
    chain = source_definition(setup)
    request = command(setup, "engineering.bom.revise", bom_payload(chain["reference"]),
                      chain["reads"])
    refused = post(setup, request)
    assert refused.status_code == 409 and refused.json()["code"] == "CONFIRMATION_REQUIRED"
    reviewed = post(setup, request, True)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["after"]["lines"][0]["quantity"] is None
    prepared = reviewed.json()["command"]
    prepared["payload"]["lines"][0]["quantity"] = "2"
    response = post(setup, prepared)
    assert response.status_code == 409 and response.json()["code"] == "CONFIRMATION_SCOPE_CHANGED"
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(BomRevision)) == 0
        assert s.scalar(select(Confirmation)).consumed is False


def test_append_reuses_exact_part_and_prior_receipt_survives_new_head_and_product_revision(setup):
    chain = configuration_chain(setup)
    old_bom = listed(setup)["boms"][0]
    receipt, prepared, review = accepted(setup, command(
        setup, "engineering.bom.revise", revision_payload(old_bom, chain["reference"]),
        chain["reads"],
    ))
    assert review["before"]["id"] == old_bom["id"]
    revised = next(value for value in listed(setup)["boms"] if value["id"] == receipt["subject_id"])
    assert revised["series_id"] == old_bom["series_id"] and revised["revision"] == 2
    assert revised["previous_id"] == old_bom["id"]
    assert revised["lines"][0]["part_id"] == old_bom["lines"][0]["part_id"]
    assert revised["lines"][0]["quantity"] == "2"
    assert next(value for value in listed(setup)["boms"] if value["id"] == old_bom["id"])[
        "lines"][0]["quantity"] is None
    with Session(setup.admin) as s, s.begin():
        s.execute(update(Product).where(Product.id == setup.product).values(revision=2))
    for request, original in ((prepared, receipt),
                              (chain["requests"]["bom"], chain["receipts"]["bom"])):
        replay = post(setup, request)
        assert replay.status_code == 200 and replay.json()["id"] == original["id"]
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(PartIdentity)) == 1
        assert s.scalar(select(func.count()).select_from(BomRevision)) == 2


def test_concurrent_append_only_advances_one_child(setup):
    chain = configuration_chain(setup)
    original = listed(setup)["boms"][0]
    prepared = []
    for quantity in ("2", "3"):
        preview = post(setup, command(
            setup, "engineering.bom.revise",
            revision_payload(original, chain["reference"], quantity),
            chain["reads"],
        ), True)
        assert preview.status_code == 200, preview.text
        prepared.append(preview.json()["command"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda request: post(setup, request), prepared))
    assert sorted(response.status_code for response in responses) == [200, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["code"] == "VERSION_CONFLICT"
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(BomRevision)) == 2


def test_engineering_can_pin_legal_old_bom_without_requiring_latest_or_publication(setup):
    chain = configuration_chain(setup)
    accepted(setup, command(setup, "engineering.bom.revise", revision_payload(
        listed(setup)["boms"][0], chain["reference"]), chain["reads"]))
    payload = deepcopy(chain["requests"]["engineering"]["payload"])
    payload.pop("confirmation_token")
    payload["name"] = "Independent configuration using original fixed BOM"
    payload["reason"] = "Keep original still-valid design and BOM versions"
    receipt, _, _ = accepted(setup, command(
        setup, "engineering.configuration.create", payload, chain["reads"],
    ))
    engineered = next(value for value in listed(setup)["engineering"]
                      if value["id"] == receipt["subject_id"])
    assert engineered["bom_id"] == chain["bom_id"] and engineered["bom_revision"] == 1
    assert engineered["definition"]["status"] == "draft"


@pytest.mark.parametrize("condition", ["withdrawn", "stale", "invisible", "expired_grant"])
def test_current_sources_and_grants_guard_even_receipt_replay(setup, condition):
    chain = configuration_chain(setup)
    if condition == "invisible":
        with pytest.raises(DBAPIError), Session(setup.admin) as s, s.begin():
            s.execute(update(Artifact).where(Artifact.id == UUID(chain["artifact_id"])).values(
                owner_id=setup.peer))
        with Session(setup.admin) as s:
            assert s.get(Artifact, UUID(chain["artifact_id"])).owner_id == setup.human
        peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
        replay = post(setup, chain["requests"]["process"], headers=peer_headers)
        assert replay.status_code == 403
        response = setup.client.get(f"/v1/products/{setup.product}/configurations",
                                    headers=peer_headers)
        assert response.status_code == 200, response.text
        values = response.json()
        assert values["boms"] == values["engineering"] == values["processes"] == []
        with tenant_session(setup.engine, setup.tenant) as s:
            peer = Context(setup.tenant, setup.peer, setup.peer)
            with pytest.raises(DomainError) as refused:
                service.get_engineering(s, peer, setup.product, UUID(chain["engineering_id"]))
            assert refused.value.code == "FORBIDDEN_SCOPE"
        return
    with Session(setup.admin) as s, s.begin():
        if condition == "withdrawn":
            s.execute(update(Artifact).where(Artifact.id == UUID(chain["artifact_id"])).values(
                status="withdrawn"))
        elif condition == "stale":
            s.execute(update(Artifact).where(Artifact.id == UUID(chain["artifact_id"])).values(
                revision=2))
        else:
            s.execute(update(Grant).where(Grant.product_id == setup.product,
                                         Grant.principal_id == setup.human).values(
                expires_at=now() - timedelta(seconds=1)))
    replay = post(setup, chain["requests"]["process"])
    assert replay.status_code in {403, 409}
    if condition in {"withdrawn", "stale"}:
        values = listed(setup)
        assert all(value["source_status"] == "needs_recheck"
                   for key in ("boms", "engineering", "processes") for value in values[key])


def test_same_number_cannot_create_new_part_instead_of_reuse(setup):
    chain = configuration_chain(setup)
    original = listed(setup)["boms"][0]
    number = original["lines"][0]["part"]["internal_number"]
    request = command(setup, "engineering.bom.revise", bom_payload(chain["reference"], number),
                      chain["reads"])
    response = post(setup, request, True)
    assert response.status_code == 409 and response.json()["code"] == "DUPLICATE_PART_IDENTITY"
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(PartIdentity)) == 1


def test_part_identity_cannot_cross_product_in_command_or_database(setup):
    configuration_chain(setup)
    original = listed(setup)["boms"][0]
    second_product = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(Product(id=second_product, tenant_id=setup.tenant, owner_id=setup.human,
                      name="Another synthetic product", purpose="Cross product guard"))
        s.flush()
        s.add(Grant(tenant_id=setup.tenant, product_id=second_product,
                    principal_id=setup.human, can_write=True,
                    expires_at=now() + timedelta(hours=1)))
    source = command(setup, "evidence.artifact.register", {
        "title": "Other source", "content": TEXT, "source_label": "Other synthetic scope",
        "visibility": "private",
    }, [])
    source["product_id"] = str(second_product)
    artifact = post(setup, source).json()["subject_id"]
    reference = {"artifact_id": artifact, "expected_revision": 1, "line": 1, "quote": TEXT}
    payload = revision_payload(original, reference)
    payload.update({"previous_id": None, "expected_previous_revision": None})
    request = command(setup, "engineering.bom.revise", payload,
                      [{"artifact_id": artifact, "expected_revision": 1}])
    request["product_id"] = str(second_product)
    response = post(setup, request, True)
    assert response.status_code == 403
    with pytest.raises(DBAPIError), Session(setup.admin) as s, s.begin():
        s.add(BomLine(tenant_id=setup.tenant, product_id=second_product,
                      bom_id=UUID(original["id"]), key="illegal", part_id=UUID(
                          original["lines"][0]["part_id"]), part_revision=1,
                      quantity=None, unit=None, loss_rate=None, critical=False))
        s.flush()


def test_external_reference_requires_exact_basis_and_all_inherited_read_versions(setup):
    chain = configuration_chain(setup)
    payload = deepcopy(chain["requests"]["engineering"]["payload"])
    payload.pop("confirmation_token")
    payload["name"] = "Synthetic sourced mechanical revision"
    payload["mechanical"] = {"system": "Synthetic PLM", "external_id": "CAD-1",
                             "basis": {**chain["reference"], "quote": "Invented line fragment"}}
    request = command(setup, "engineering.configuration.create", payload, chain["reads"])
    response = post(setup, request, True)
    assert response.status_code == 409 and response.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    payload["mechanical"]["basis"] = chain["reference"]
    request = command(setup, "engineering.configuration.create", payload, [])
    missing = post(setup, request, True)
    assert missing.status_code == 409 and missing.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    request["source_read_set"] = chain["reads"]
    receipt, _, _ = accepted(setup, request)
    configured = next(value for value in listed(setup)["engineering"]
                      if value["id"] == receipt["subject_id"])
    assert configured["design_versions"]["mechanical"]["basis"] == chain["reference"]
    assert configured["external_verification"] == "not_checked"


def test_process_cannot_bind_foreign_bom_line_or_invent_approval(setup):
    chain = configuration_chain(setup)
    payload = deepcopy(chain["requests"]["process"]["payload"])
    payload.pop("confirmation_token")
    payload["name"] = "Independent synthetic manufacturing"
    payload["operations"][0]["bom_line_keys"] = ["foreign-line"]
    response = post(setup, command(setup, "npi.process.revise", payload, chain["reads"]), True)
    assert response.status_code == 422 and response.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    payload["operations"][0]["bom_line_keys"] = ["housing"]
    payload["approved_deviation"] = True
    response = post(setup, command(setup, "npi.process.revise", payload, chain["reads"]), True)
    assert response.status_code == 422


@pytest.mark.parametrize("actor,run", [("agent", False), ("human", True)])
def test_named_current_human_only_no_run(setup, actor, run):
    chain = source_definition(setup)
    request = Command.model_validate(command(
        setup, "engineering.bom.revise", bom_payload(chain["reference"]), chain["reads"],
    ))
    context = Context(setup.tenant, getattr(setup, actor), setup.human, uuid4() if run else None)
    with tenant_session(setup.engine, setup.tenant) as s:
        product = s.get(Product, setup.product)
        with pytest.raises(DomainError) as refused:
            service.validate(s, context, request, product,
                             EngineeringBomRevisePayload.model_validate(request.payload))
        assert refused.value.code == "NAMED_DECISION_REQUIRED"


def test_config_drafts_are_database_immutable(setup):
    configuration_chain(setup)
    for model, patch in ((PartIdentity, {"name": "changed"}),
                         (BomRevision, {"name": "changed"}),
                         (BomLine, {"quantity": "2"}),
                         (EngineeringConfiguration, {"name": "changed"}),
                         (ProcessRevision, {"line": "changed"})):
        with pytest.raises(DBAPIError), Session(setup.admin) as s, s.begin():
            s.execute(update(model).where(model.tenant_id == setup.tenant).values(**patch))


def test_receipt_failure_rolls_back_bom_material_and_confirmation(setup, monkeypatch):
    chain = source_definition(setup)
    reviewed = post(setup, command(setup, "engineering.bom.revise", bom_payload(
        chain["reference"]), chain["reads"]), True)
    assert reviewed.status_code == 200, reviewed.text

    def fail(*args, **kwargs):
        raise DomainError("SYNTHETIC_RECEIPT_FAILURE", "Injected transaction failure")

    monkeypatch.setattr("pdos_next.service.append_receipt", fail)
    response = post(setup, reviewed.json()["command"])
    assert response.status_code == 409
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(BomRevision)) == 0
        assert s.scalar(select(func.count()).select_from(PartIdentity)) == 0
        assert s.scalar(select(func.count()).select_from(BomLine)) == 0
        assert s.scalar(select(Confirmation)).consumed is False
        assert s.scalar(select(func.count()).select_from(Receipt).where(
            Receipt.operation.in_(OPERATIONS))) == 0


def test_twenty_source_limit_is_checked_after_inheriting_previous_pin(setup):
    chain = configuration_chain(setup)
    refs, reads = [], []
    for index in range(20):
        created = post(setup, command(setup, "evidence.artifact.register", {
            "title": f"Independent source {index}", "content": TEXT,
            "source_label": "Unverified limit fixture", "visibility": "private",
        }, []))
        assert created.status_code == 200, created.text
        identity = created.json()["subject_id"]
        refs.append({"artifact_id": identity, "expected_revision": 1, "line": 1, "quote": TEXT})
        reads.append({"artifact_id": identity, "expected_revision": 1})
    payload = revision_payload(listed(setup)["boms"][0], chain["reference"])
    payload["sources"] = refs
    response = post(setup, command(setup, "engineering.bom.revise", payload, reads), True)
    assert response.status_code == 422 and response.json()["code"] == "TOO_MANY_REQUIRED_EVIDENCE"


@pytest.mark.parametrize("quantity", [0, True, 0.5, "NaN", "1e99", "0.123456789"])
def test_quantity_rejects_zero_binary_float_bool_and_outside_precision(quantity):
    payload = bom_payload({"artifact_id": str(uuid4()), "expected_revision": 1,
                           "line": 1, "quote": TEXT})
    payload["lines"][0]["quantity"] = quantity
    with pytest.raises(ValidationError):
        EngineeringBomRevisePayload.model_validate(payload)


def test_typed_process_unknowns_do_not_create_qualification_or_cycle():
    process = NpiProcessRevisePayload.model_validate({
        "name": "Unknown process", "reason": "Keep unconfirmed fields explicitly unknown",
        "engineering_configuration_id": uuid4(), "expected_engineering_revision": 1,
        "sources": [{"artifact_id": uuid4(), "expected_revision": 1, "line": 1, "quote": TEXT}],
        "operations": [{"key": "step", "name": "Unconfirmed assembly", "kind": "assembly"}],
    })
    operation = process.operations[0]
    assert operation.sop is operation.cycle_time_minutes is operation.acceptance_criterion is None
    assert process.site is process.line is None
    assert operation.resource_requirements == []
