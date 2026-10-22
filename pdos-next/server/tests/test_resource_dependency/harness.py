"""Fixed complete data from actual tests, with explicit IO substitutes and no DB owner proof."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from pdos_next.domain.test_resources import service as resources
from pdos_next.service import Context


@pytest.fixture
def h(monkeypatch, materials):
    original, _, fixed = materials
    binding = original["binding"]
    at = binding.window.start - timedelta(minutes=30)
    ctx = Context(fixed.tenant_id, UUID(int=41), UUID(int=41))
    pid = fixed.product_id
    specs = [
        {"id": original["assets"][0]["id"], "revision": 1, "kind": "equipment"},
        {"id": binding.executor_id, "revision": 1, "kind": "person"},
    ]
    reference = binding.equipment.model_dump(mode="json")
    data = resources.TestResourceFactInput.model_validate(
        {
            "binding": binding,
            "external_id": "complete-pure-owner-fixture",
            "valid_from": at - timedelta(hours=1),
            "valid_until": at + timedelta(hours=3),
            "resources": [
                {
                    "resource": spec,
                    "purposes": [binding.purpose],
                    "operation_ids": [resources.OPERATION],
                    "lifecycle": "active",
                    "facts": [
                        {
                            "kind": "qualification",
                            "purpose": binding.purpose,
                            "operation_id": resources.OPERATION,
                            "status": "unknown",
                            "sources": [reference],
                        }
                    ],
                    "maintenance": [],
                    "capacity": "1.000",
                    "external_occupancies_complete": False,
                    "sources": [reference],
                }
                for spec in specs
            ],
            "required_uses": [{"resource": spec, "units": "1"} for spec in specs],
            "requirements_sources": [reference],
            "sources": [reference],
            "reason": "Complete fixture retains unknown qualification and all producer fields",
        }
    )
    engine = SimpleNamespace()
    issuer = resources.configure_issuer(
        engine,
        key="fixed-test-issuer",
        version="v1",
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=binding.project_id,
    )
    engine._pdos_test_resource_issuer_epochs["unrelated-other-scope"] = 9
    basis = deepcopy(original["source_basis"])
    basis["access"]["principal_id"] = str(ctx.requester_id)
    for row in basis["refs"]:
        row["state"] = "unknown"
        row["valid_until"] = None
    for row in basis["security"]:
        row.update(security_epoch=None, source_state=None, disposition=None)
    for row in basis["fixed_readset_security"]:
        row.update(epoch=None, source_state=None, disposition=None)
    fact = SimpleNamespace(
        id=fixed.fact_id,
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=binding.project_id,
        revision=1,
        binding=binding.model_dump(mode="json"),
        data=data.model_dump(mode="json"),
        required_source_read_set=[],
        sources=[],
        owner_id=ctx.requester_id,
        source_basis=deepcopy(basis),
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature=issuer.nature,
        state="active",
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        fact_sha256=fixed.fact_sha256,
    )
    pointer = SimpleNamespace(epoch=2)
    sample_id = binding.pairs[0].sample.id
    samples = {
        sample_id: {
            "availability": "ready",
            "facts_revision": "c" * 64,
            "valid_until": data.valid_until,
        }
    }
    assets = {
        spec["id"]: SimpleNamespace(
            id=spec["id"], revision=1, data_sha256="d" * 64, occupancy_epoch=5
        )
        for spec in specs
    }
    sentinels = {sample_id: SimpleNamespace(epoch=4)}
    authority = deepcopy(original["authority"])
    authority.update(
        qualified=None,
        reason_codes=["QUALIFICATION_UNKNOWN"],
        valid_until=data.valid_until.isoformat(),
        required_source_read_set=[],
    )
    fixture = SimpleNamespace(
        binding=binding,
        data=data,
        engine=engine,
        ctx=ctx,
        pid=pid,
        fact=fact,
        pointer=pointer,
        samples=samples,
        assets=assets,
        sentinels=sentinels,
        authority=authority,
        basis=basis,
        at=at,
        clock=at,
        calls=[],
        existing=None,
        after_hash=None,
        source_failure=False,
    )

    class ReadOwner:
        def get_bind(self):
            return engine

        def scalars(self, statement):
            fixture.calls.append("sample-usages")
            return []

    fixture.session = ReadOwner()

    def gate(name, result=None):
        def call(*args, **kwargs):
            fixture.calls.append(name)
            if name == "consumer-source" and fixture.source_failure:
                raise resources.DomainError("SOURCE_STALE", "Fixture current Source withdrew")
            return result

        return call

    def occupancies(*args, **kwargs):
        fixture.calls.append("occupancies-after-fingerprint")
        if fixture.after_hash:
            fixture.after_hash()
        return ()

    from pdos_next.domain.build_operational_facts import physical_summary

    monkeypatch.setattr(physical_summary, "capacity_summary", gate("foreign-capacity", []))
    monkeypatch.setattr(resources, "now", lambda: fixture.clock)
    monkeypatch.setattr(resources, "lock_binding_assets", gate("complete-union-assets"))
    monkeypatch.setattr(resources, "_current", lambda *args: (pointer, fact))
    monkeypatch.setattr(
        resources, "_scope", lambda *args, **kwargs: (binding, object(), samples, ())
    )
    monkeypatch.setattr(resources, "_visible", lambda *args: True)
    monkeypatch.setattr(resources, "_sources", gate("consumer-source"))
    monkeypatch.setattr(resources, "_human", gate("original-importer-human"))
    monkeypatch.setattr(resources, "_evidence_basis", gate("original-basis", (None, None, basis)))
    monkeypatch.setattr(resources, "_assets", gate("physical-assets", assets))
    monkeypatch.setattr(resources, "_reservation", lambda *args: fixture.existing)
    monkeypatch.setattr(resources, "_own_proof", gate("complete-own-effects"))
    monkeypatch.setattr(resources, "_sample_sentinels", lambda *args, **kwargs: sentinels)
    monkeypatch.setattr(resources, "_occupancies", occupancies)
    monkeypatch.setattr(
        resources.professional, "assess", gate("exact-executor-authority", authority)
    )
    monkeypatch.setattr(
        resources.professional,
        "recheck_snapshot",
        lambda *args, **kwargs: {"current": True, "assessment": authority},
    )
    return fixture


def load(h, **kwargs):
    return resources._load(
        h.session, h.ctx, h.pid, h.binding, h.fact.id, h.fact.revision, at=h.at, **kwargs
    )


def v2(h, **kwargs):
    collector = []
    result = load(
        h,
        _fingerprint_version=resources._FINGERPRINT_V2,
        _fingerprint_collector=collector,
        **kwargs,
    )
    return result, collector[0]
