"""Definition comparison unit tests: no database, providers or workers."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import m3_definition_diff as module
from pdos_next.errors import DomainError


def view(revision=1, *, product=None, category=None, value="10"):
    return {
        "id": str(uuid4()),
        "product_id": str(product or uuid4()),
        "category_id": str(category or uuid4()),
        "variant_id": None,
        "revision": revision,
        "title": "Definition",
        "status": "draft",
        "purpose": "A useful pump",
        "use_cases": [],
        "requirements": [],
        "constraints": [],
        "unknowns": [],
        "exclusions": [],
        "sources": [],
        "specs": [
            {
                "key": "pressure",
                "parameter": "Pressure",
                "value_type": "number",
                "availability": "known",
                "value": value,
                "unit": "bar",
            }
        ],
    }


def ref(value):
    return {
        "product_id": value["product_id"],
        "definition_id": value["id"],
        "definition_revision": value["revision"],
    }


def pair():
    old = view()
    child = view(category=old["category_id"])
    payload = module.DefinitionDiffInput.model_validate(
        {"baseline": ref(old), "proposed": ref(child)}
    )
    return payload, old, child


def test_strict_modes_and_legacy_proposal():
    payload, old, child = pair()
    raw = payload.model_dump(mode="json", exclude_none=True)
    raw["proposed"] = {"proposal_id": str(uuid4()), "revision": 2}
    assert isinstance(
        module.DefinitionDiffInput.model_validate(raw).proposed, module.ProposedProposal
    )
    for change in (
        {"three_way": {"old_parent": ref(old), "new_parent": ref(child), "child": ref(child)}},
        {"tenant_id": str(uuid4())},
        {"proposed": {**ref(child), "content": {}}},
        {"baseline": None},
    ):
        with pytest.raises(ValidationError):
            module.DefinitionDiffInput.model_validate({**raw, **change})


def test_two_way_uses_only_existing_engine(monkeypatch):
    payload, old, child = pair()
    child["specs"][0]["value"] = "12"
    actual = module.variants.compare_snapshots
    calls = []

    def compare(request, **kwargs):
        calls.append(kwargs)
        return actual(request, **kwargs)

    monkeypatch.setattr(module.variants, "compare_snapshots", compare)
    result = module.calculate(payload, old, old, child)
    assert calls == [{"allow_same_parent": True}]
    assert result["differences"][0]["classification"] == "child_only"
    assert result["unavailable_blocks"] == ["bom", "certification", "tooling"]
    assert "proof" not in result


def test_three_way_conflict_and_parent_version_guard():
    _, old, child = pair()
    new = view(2, product=old["product_id"], category=old["category_id"], value="11")
    child["specs"][0]["value"] = "12"
    payload = module.DefinitionDiffInput.model_validate(
        {"three_way": {"old_parent": ref(old), "new_parent": ref(new), "child": ref(child)}}
    )
    assert (
        module.calculate(payload, old, new, child)["differences"][0]["classification"] == "conflict"
    )
    new["revision"] = 1
    with pytest.raises(DomainError) as caught:
        module.calculate(payload, old, new, child)
    assert caught.value.code == "VALIDATION_FAILED"


def test_full_input_digest_changes_without_definition_revision_change():
    payload, old, child = pair()
    first = module.calculate(payload, old, old, child)
    child["item_watermark"] = {"pressure": 2}
    second = module.calculate(payload, old, old, child)
    assert first["derivation_request_digest"] == second["derivation_request_digest"]
    assert first["request_digest"] != second["request_digest"]


def test_restore_reauthorizes_before_digest_and_rejects_changed_content(monkeypatch):
    port = module.DefinitionDiffReads(None, None, None)
    calls = []

    def read(*args):
        calls.append(args)
        raise DomainError("FORBIDDEN_SCOPE", "Revoked", 403)

    monkeypatch.setattr(port, "call", read)
    with pytest.raises(DomainError) as caught:
        port.restore("scope", {}, {"result": "cached"})
    assert caught.value.code == "FORBIDDEN_SCOPE" and len(calls) == 1
    monkeypatch.setattr(port, "call", lambda *args: {"request_digest": "new"})
    with pytest.raises(DomainError) as caught:
        port.restore("scope", {}, {"request_digest": "old"})
    assert caught.value.code == "SOURCE_STALE"


def test_definition_scope_and_privacy_precede_body(monkeypatch):
    payload, _, child = pair()
    port = module.DefinitionDiffReads(None, None, None)
    scope = NS(product_id=None)
    events = []
    public = NS(
        product=lambda _: events.append("product"),
        definition=lambda *args: events.append("privacy"),
    )
    head = {"product_id": payload.proposed.product_id, "variant_id": None, "revision": 1}
    monkeypatch.setattr(module, "_head", lambda *args: head)
    monkeypatch.setattr(
        module.definitions,
        "definition_view",
        lambda *args: events.append("body") or deepcopy(child),
    )
    monkeypatch.setattr(module.baseline, "validate_sources", lambda *args: events.append("sources"))
    session = NS(get=lambda *args: NS())
    port._read(session, NS(category_id=child["category_id"]), scope, public, payload.proposed)
    assert events == ["product", "privacy", "body", "sources"]
    events.clear()
    head["product_id"] = uuid4()
    with pytest.raises(DomainError):
        port._read(session, NS(category_id=child["category_id"]), scope, public, payload.proposed)
    assert events == ["product"]


def test_item_versions_are_in_digest_but_not_engine_business_fields():
    payload, old, child = pair()
    first = module.calculate(payload, old, old, child)
    child["specs"][0].update(item_id=str(uuid4()), item_version=2)
    second = module.calculate(payload, old, old, child)
    assert first["derivation_request_digest"] == second["derivation_request_digest"]
    assert first["request_digest"] != second["request_digest"]


@pytest.fixture
def host(monkeypatch):
    from contextlib import contextmanager

    payload, old, child = pair()
    scope = NS(
        category_id=old["category_id"],
        tenant_id=uuid4(),
        writer_id=uuid4(),
        requester_id=uuid4(),
        run_id=uuid4(),
        product_id=None,
    )
    run = NS(
        session_id=uuid4(),
        tenant_id=scope.tenant_id,
        requester_id=scope.requester_id,
        category_id=scope.category_id,
        product_id=None,
        proposal_id=None,
        private_context=False,
        customer_identities=[],
        data_categories=[],
        read_sources=[],
    )
    owner = NS(
        tenant_id=scope.tenant_id,
        owner_id=scope.requester_id,
        category_id=scope.category_id,
        product_id=None,
        proposal_id=None,
    )
    events = []
    session = NS(get=lambda model, identity: run if model is module.AgentRun else owner)

    @contextmanager
    def transaction(*args, **kwargs):
        assert kwargs["read_snapshot"]
        yield session

    monkeypatch.setattr(module, "tenant_session", transaction)
    monkeypatch.setattr(module, "check_run_binding", lambda *a, **kw: events.append("binding"))
    monkeypatch.setattr(module, "require_access", lambda *a: None)
    public = NS(
        refs=lambda *a: events.append("refs"),
        parameters=lambda *a: None,
        product=lambda *a: events.append("product"),
        definition=lambda *a: events.append("fixed_privacy"),
        definition_head=lambda row: events.append("prebody"),
    )
    actual_object_factory = module._objects
    monkeypatch.setattr(module, "_objects", lambda *a: public)
    monkeypatch.setattr(module, "_head", lambda *a: {
        "product_id": UUID(old["product_id"]), "variant_id": None,
        "revision": old["revision"],
    })
    store = NS(engine=None, authority=lambda *a: events.append("authority"))
    port = module.DefinitionDiffReads(store, NS(context=lambda _: scope), None)
    monkeypatch.setattr(port, "_read", lambda *a: deepcopy(child))

    def read(*args, **kwargs):
        kwargs["before_definition_read"](NS())
        events.append("body")
        return {"definition": deepcopy(old)}

    monkeypatch.setattr(module.baseline, "read_baseline", read)
    monkeypatch.setattr(module.baseline, "validate_sources", lambda *a: events.append("sources"))
    return NS(port=port, scope=scope, run=run, owner=owner, events=events, payload=payload,
              actual_object_factory=actual_object_factory)


def test_host_prebody_guard_and_final_authority(host):
    host.port.call(host.scope, host.payload.model_dump(mode="json"))
    assert host.events.index("prebody") < host.events.index("body")
    assert host.events.index("fixed_privacy") < host.events.index("body")
    assert host.events[-2:] == ["authority", "binding"]


@pytest.mark.parametrize("private", ["private_context", "customer_identities", "data_categories"])
def test_host_private_context_fails_before_body(host, private, monkeypatch):
    setattr(host.run, private, True if private == "private_context" else ["customer"])
    monkeypatch.setattr(module, "_objects", host.actual_object_factory)
    with pytest.raises(DomainError) as caught:
        host.port.call(host.scope, host.payload.model_dump(mode="json"))
    assert caught.value.code == "SOURCE_UNAVAILABLE"
    assert "body" not in host.events


def test_host_wrong_session_fails_before_body(host):
    host.owner.owner_id = uuid4()
    with pytest.raises(DomainError) as caught:
        host.port.call(host.scope, host.payload.model_dump(mode="json"))
    assert caught.value.code == "FORBIDDEN_SCOPE"
    assert "body" not in host.events


def test_proposal_mode_delegates_original_payload_and_preserves_result(host, monkeypatch):
    proposal_id = uuid4()
    host.run.proposal_id = proposal_id
    host.owner.proposal_id = proposal_id
    calls = []
    public = NS(refs=lambda *a: None, proposal=lambda identity: calls.append(identity))
    monkeypatch.setattr(module, "_objects", lambda *a: public)
    expected = {"engine": "existing", "request_digest": "existing-proof-category"}

    def original(scope, arguments, *, name):
        assert name == "calc.derivation_diff"
        assert "variant_id" not in arguments["baseline"]
        calls.append(arguments)
        return expected

    host.port.proposal_reads = NS(call=original)
    arguments = {
        "baseline": host.payload.baseline.model_dump(mode="json"),
        "proposed": {"proposal_id": str(proposal_id), "revision": 1},
    }
    assert host.port.call(host.scope, arguments) is expected
    assert calls[0] == proposal_id
    assert host.events[-2:] == ["authority", "binding"]
