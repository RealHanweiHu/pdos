from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pdos_next.domain.build_operational_facts.models import OperationalAsset
from pdos_next.domain.test_resources import service
from pdos_next.domain.test_resources.schemas import TestPlanBinding as Binding
from pdos_next.domain.test_resources.schemas import TestResourceFactInput as FactInput
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


def reference():
    return {
        "artifact_id": str(uuid4()),
        "expected_revision": 1,
        "line": 1,
        "quote": "fixed evidence",
    }


@pytest.fixture
def binding_data():
    bid, sid, aid = uuid4(), uuid4(), uuid4()
    return {
        "run_id": str(uuid4()),
        "request_id": str(uuid4()),
        "accepted_request_id": str(uuid4()),
        "accepted_request_revision": 4,
        "build_id": str(bid),
        "project_id": str(uuid4()),
        "purpose": "Specific test purpose",
        "executor_id": str(uuid4()),
        "window": {
            "start": "2026-10-02T12:00:00Z",
            "finish": "2026-10-02T13:00:00Z",
            "original_timezone": "UTC",
        },
        "equipment": reference(),
        "calibration": reference(),
        "environment": "Synthetic controlled room",
        "conditions": "Explicit fixed conditions",
        "pairs": [
            {
                "sample": {
                    "id": str(sid),
                    "revision": 1,
                    "build_id": str(bid),
                    "actual_configuration": {"id": str(aid), "revision": 1},
                },
                "item_id": "strength",
                "method_id": str(uuid4()),
                "method_revision": 1,
                "method_sha256": "a" * 64,
                "destructive": True,
            }
        ],
    }


@pytest.fixture
def fact_data(binding_data):
    equipment = {"id": str(uuid4()), "revision": 1, "kind": "equipment"}
    person = {"id": binding_data["executor_id"], "revision": 1, "kind": "person"}
    return {
        "binding": binding_data,
        "external_id": "specific-method-resource-declaration-v1",
        "valid_from": "2026-10-02T11:00:00Z",
        "valid_until": "2026-10-02T14:00:00Z",
        "resources": [
            {
                "resource": ref,
                "purposes": [binding_data["purpose"]],
                "operation_ids": ["test.run.start"],
                "lifecycle": "active",
                "facts": [],
                "maintenance": [],
                "calendar": None,
                "capacity": "1",
                "sources": [reference()],
            }
            for ref in [equipment, person]
        ],
        "required_uses": [{"resource": deepcopy(ref), "units": "1"} for ref in [equipment, person]],
        "requirements_sources": [reference()],
        "sources": [reference()],
        "reason": "Controlled method declaration; absent qualification stays unknown",
    }


def test_unknown_facts_save_without_qualifying(fact_data):
    value = FactInput.model_validate(fact_data)
    assert all(not r.facts and not r.external_occupancies_complete for r in value.resources)
    assert value.resources[0].calendar is None


@pytest.mark.parametrize("value", [True, 1.5, "NaN", "Infinity"])
def test_required_units_refuse_non_exact_numbers(fact_data, value):
    fact_data["required_uses"][0]["units"] = value
    with pytest.raises(ValidationError):
        FactInput.model_validate(fact_data)


@pytest.mark.parametrize("mutation", ["scope", "synthetic", "approved", "qualified"])
def test_client_policy_facts_rejected(fact_data, mutation):
    fact_data[mutation] = True
    with pytest.raises(ValidationError):
        FactInput.model_validate(fact_data)


@pytest.mark.parametrize("mutation", ["repeat", "wrong_version", "wrong_executor", "empty_uses"])
def test_trusted_requirements_require_exact_whole_bundle(fact_data, mutation):
    if mutation == "repeat":
        fact_data["required_uses"].append(deepcopy(fact_data["required_uses"][0]))
    elif mutation == "wrong_version":
        fact_data["required_uses"][0]["resource"]["revision"] = 2
    elif mutation == "wrong_executor":
        fact_data["binding"]["executor_id"] = str(uuid4())
    else:
        fact_data["required_uses"] = []
    with pytest.raises(ValidationError):
        FactInput.model_validate(fact_data)


def test_sample_one_identity_cannot_serve_two_destructive_items(binding_data):
    second = deepcopy(binding_data["pairs"][0])
    second["item_id"] = "another destructive item"
    binding_data["pairs"].append(second)
    with pytest.raises(ValidationError):
        Binding.model_validate(binding_data)


@pytest.mark.parametrize("key", ["expected_previous_id", "expected_previous_revision"])
def test_fact_cas_pair_is_explicit(fact_data, key):
    fact_data[key] = str(uuid4()) if key.endswith("id") else 1
    with pytest.raises(ValidationError):
        FactInput.model_validate(fact_data)


def test_manufacturing_purpose_is_not_test_qualification(fact_data):
    value = deepcopy(fact_data["resources"][0])
    changed = deepcopy(value)
    changed["purposes"] = ["Manufacturing purpose"]
    changed["operation_ids"] = ["build.start"]
    changed["facts"] = [{"arbitrary manufacturing fact": True}]
    assert service.physical_projection(value) == service.physical_projection(changed)
    # This equality is physical identity only; the test fact still retains all
    # its own purpose, operation and named qualification evidence.


@pytest.mark.parametrize(
    "key,value",
    [
        ("capacity", "2"),
        ("lifecycle", "withdrawn"),
        ("maintenance", None),
        ("calendar", {"version": "different"}),
    ],
)
def test_same_revision_physical_drift_is_detectable(fact_data, key, value):
    original = fact_data["resources"][0]
    changed = deepcopy(original)
    changed[key] = value
    assert service.physical_projection(original) != service.physical_projection(changed)


def usage(binding, *, run_id=None, destructive=False, start=None, finish=None, intent="same"):
    return SimpleNamespace(
        sample_id=binding.pairs[0].sample.id,
        run_id=run_id or uuid4(),
        destructive=destructive,
        window_start=start or binding.window.start,
        window_finish=finish or binding.window.finish,
        intent_digest=intent,
        state="consumed" if destructive else "reserved",
        revision=1,
    )


def test_consumed_sample_never_becomes_available_after_window(binding_data):
    binding = Binding.model_validate(binding_data)
    old = usage(
        binding,
        destructive=True,
        start=binding.window.start - timedelta(days=10),
        finish=binding.window.finish - timedelta(days=10),
    )
    views, checks = service.sample_usage_checks(binding, [old])
    assert views[0].state == "consumed" and views[0].owner_run_id is None
    assert checks[0].status == "BLOCKED"


def test_foreign_occupancy_is_sanitized_but_blocks(binding_data):
    binding = Binding.model_validate(binding_data)
    views, checks = service.sample_usage_checks(binding, [usage(binding)])
    assert views[0].state == "reserved" and views[0].owner_run_id is None
    assert checks[0].code == "sample_usage_conflict"


def test_half_open_sample_windows_can_touch(binding_data):
    binding = Binding.model_validate(binding_data)
    old = usage(
        binding, start=binding.window.start - timedelta(hours=1), finish=binding.window.start
    )
    views, checks = service.sample_usage_checks(binding, [old])
    assert views[0].state == "available" and not checks


def test_only_exact_owned_run_intent_excludes_consumption(binding_data):
    binding = Binding.model_validate(binding_data)
    own = usage(binding, run_id=binding.run_id, destructive=True)
    assert service.sample_usage_checks(binding, [own], owned_intent="same")[1] == ()
    assert service.sample_usage_checks(binding, [own], owned_intent="different")[1]


def test_synthetic_profile_is_explicit_and_cannot_be_spoofed():
    engine = SimpleNamespace()
    tenant, product, project = uuid4(), uuid4(), uuid4()
    with pytest.raises(ValueError):
        service.configure_local_synthetic(engine, tenant_id=tenant, product_id=product)
    issuer = service.configure_local_synthetic(
        engine,
        tenant_id=tenant,
        product_id=product,
        project_id=project,
        enabled=True,
        test_marker_verified=True,
    )
    ctx, session = Context(tenant, uuid4(), uuid4()), SimpleNamespace(get_bind=lambda: engine)
    assert service._issuer(session, ctx, product, project, issuer) is issuer
    counterfeit = service.IssuerContext(**issuer.__dict__)
    with pytest.raises(DomainError, match="可信测试事实"):
        service._issuer(session, ctx, product, project, counterfeit)


def test_revoke_restore_issuer_epoch_cannot_reuse_old_context():
    engine, tenant, product = SimpleNamespace(), uuid4(), uuid4()
    kwargs = {"key": "real-issuer", "version": "v1", "tenant_id": tenant, "product_id": product}
    old = service.configure_issuer(engine, **kwargs)
    service.disable_issuer(engine, old.key)
    new = service.configure_issuer(engine, **kwargs)
    assert new.epoch == old.epoch + 2
    ctx, session = Context(tenant, uuid4(), uuid4()), SimpleNamespace(get_bind=lambda: engine)
    with pytest.raises(DomainError):
        service._issuer(session, ctx, product, None, old)
    assert service._issuer(session, ctx, product, None, new) is new


def test_union_locks_complete_assets_in_one_global_id_order(monkeypatch, binding_data, fact_data):
    binding = Binding.model_validate(binding_data)
    data = FactInput.model_validate(fact_data)
    material, small, large = UUID(int=10), UUID(int=1), UUID(int=100)
    test_specs = [("resource", small, "s", {}, 1, {}), ("resource", large, "l", {}, 1, {})]
    build_specs = [("material", material, "m", {}, 1, {}), ("resource", large, "l", {}, 1, {})]
    manufacturing = SimpleNamespace(
        tenant_id=UUID(int=5),
        product_id=UUID(int=6),
        project_id=binding.project_id,
        build_id=binding.build_id,
        visibility="category",
        data={},
    )
    ctx = Context(manufacturing.tenant_id, uuid4(), uuid4())
    calls = []
    monkeypatch.setattr(service, "_specs", lambda _: test_specs)
    monkeypatch.setattr(service.BuildFactInput, "model_validate", lambda _: SimpleNamespace())
    monkeypatch.setattr(service, "build_asset_specs", lambda *_: build_specs)

    def scalars(query):
        assert list(query._order_by_clauses) == [OperationalAsset.id]
        assert query._for_update_arg is not None
        identities = set(query.compile().params["id_1"])
        calls.append(identities)
        return [
            OperationalAsset(
                id=aid,
                tenant_id=ctx.tenant_id,
                kind=kind,
                external_key=key,
                identity=identity,
                revision=revision,
                data={"value": data, "state": "active"},
                data_sha256=digest(data),
            )
            for kind, aid, key, identity, revision, data in [test_specs[0], *build_specs]
        ]

    # A real unbound Session supplies request-proof state; all IO methods are
    # replaced explicitly, and the actual shared asset selector is inspected.
    with Session() as session, session.begin():
        monkeypatch.setattr(
            session,
            "scalar",
            lambda query: (
                manufacturing
                if query.column_descriptions[0]["entity"] is service.BuildOperationalFact
                else SimpleNamespace(fact_id=uuid4())
            ),
        )
        monkeypatch.setattr(session, "scalars", scalars)
        service._lock_union(session, ctx, manufacturing.product_id, binding, data)
    assert calls == [{small, material, large}]


def test_at_refuses_naive_future_and_accepts_exact_current(monkeypatch):
    at = datetime(2026, 10, 2, tzinfo=UTC)
    monkeypatch.setattr(service, "now", lambda: at)
    assert service._at(at) == at
    for value in [at.replace(tzinfo=None), at + timedelta(microseconds=1)]:
        with pytest.raises(DomainError):
            service._at(value)


def physical_sample(reference):
    return {
        "sample": {
            "id": str(reference.id),
            "revision": reference.revision,
            "actual_configuration_id": str(reference.actual_configuration.id),
            "cavity": reference.cavity,
        },
        "actual_configuration": reference.actual_configuration.model_dump(mode="json"),
        "build": {"id": str(reference.build_id)},
        "required_source_read_set": [],
    }


def test_scope_uses_narrow_sample_port_and_retains_full_binding(monkeypatch, binding_data):
    from pdos_next.domain.sample_handoff.schemas import SampleRef as NarrowSampleRef

    binding = Binding.model_validate(binding_data)
    pair = binding.pairs[0]
    request = SimpleNamespace(
        id=binding.request_id,
        items=[SimpleNamespace(id=pair.item_id, destructive=pair.destructive)],
    )
    method = SimpleNamespace(
        id=pair.method_id,
        revision=pair.method_revision,
        snapshot_sha256=pair.method_sha256,
        authority_snapshot={},
        required_source_read_set=[],
    )
    calls = []

    def inspect(_s, _ctx, _product, ref, purpose, *, write, at=None, retained_at=None):
        assert at is None and retained_at is None
        exact = NarrowSampleRef.model_validate(ref)
        calls.append((exact.id, exact.revision, purpose, write))
        return physical_sample(pair.sample)

    monkeypatch.setattr(
        service, "_parent_locks", lambda *_args, **_kw: (binding, None, request, [])
    )
    monkeypatch.setattr(service, "inspect_sample", inspect)
    monkeypatch.setattr(service.handoff, "_method_pointer", lambda *_args: (None, method))

    def actual_check(*_args, retained_at=None):
        assert retained_at is None

    monkeypatch.setattr(service.handoff, "_actual_check", actual_check)
    _, _, samples, _ = service._scope(None, None, uuid4(), binding)
    assert calls == [(pair.sample.id, pair.sample.revision, binding.purpose, False)]
    assert samples[pair.sample.id][
        "actual_configuration"
    ] == pair.sample.actual_configuration.model_dump(mode="json")


@pytest.mark.parametrize(
    "field",
    ["id", "revision", "build_id", "actual_id", "actual_revision", "cavity", "link_id"],
)
def test_port_result_cannot_substitute_fixed_physical_sample(binding_data, field):
    reference = Binding.model_validate(binding_data).pairs[0].sample
    value = physical_sample(reference)
    if field in {"id", "revision", "cavity"}:
        value["sample"][field] = (
            2 if field == "revision" else "unexpected-cavity" if field == "cavity" else str(uuid4())
        )
    elif field == "build_id":
        value["build"]["id"] = str(uuid4())
    elif field == "link_id":
        value["sample"]["actual_configuration_id"] = str(uuid4())
    else:
        value["actual_configuration"]["id" if field == "actual_id" else "revision"] = (
            str(uuid4()) if field == "actual_id" else 2
        )
    with pytest.raises(DomainError) as failure:
        service._require_sample_binding(reference, value)
    assert failure.value.reason == "TEST_PLAN_SCOPE_MISMATCH"
