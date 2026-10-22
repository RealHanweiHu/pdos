"""Pure RR reuse boundaries; all IO seams are explicit and no database is used."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_start import service as starts
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.test_resources import service as resources
from pdos_next.service import Context

AT = datetime(2026, 10, 9, 12, tzinfo=UTC)


@pytest.fixture
def signature(monkeypatch):
    tenant, category, product, project, subject = (uuid4() for _ in range(5))
    engine = SimpleNamespace()
    issuer = authority.configure_issuer(
        engine,
        key="rr-signature",
        version="v1",
        tenant_id=tenant,
        product_id=product,
        project_id=project,
    )
    pointers, references, facts = [], [], {}
    for kind in ("duty", "qualification"):
        identity = uuid4()
        summary = {
            "id": str(identity),
            "tenant_id": str(tenant),
            "category_id": str(category),
            "product_id": str(product),
            "project_id": str(project),
            "subject_id": str(subject),
            "owner_id": str(subject),
            "series_id": str(identity),
            "revision": 1,
            "kind": kind,
            "role": "manufacturing",
            "nature": "real",
            "issuer_key": issuer.key,
            "issuer_version": issuer.version,
            "external_id": kind,
            "operations": ["build.sample.readiness.record"],
            "purposes": ["Exact purpose"],
            "state": "active",
            "valid_from": (AT - timedelta(hours=1)).isoformat(),
            "valid_until": (AT + timedelta(hours=1)).isoformat(),
            "fact_sha256": ("a" if kind == "duty" else "b") * 64,
            "required_source_read_set": [],
        }
        pointer = SimpleNamespace(
            fact_id=identity,
            fact_revision=1,
            epoch=1,
            series_id=identity,
            kind=kind,
            issuer_key=issuer.key,
            external_id=kind,
            summary=summary,
        )
        pointers.append(pointer)
        facts[identity] = authority._summary_row(pointer)
        references.append({**deepcopy(summary), "epoch": 1, "issuer_epoch": issuer.epoch})
    snapshot = {
        "scope": {
            "tenant_id": str(tenant),
            "product_id": str(product),
            "project_id": str(project),
        },
        "subject_id": str(subject),
        "operation": "build.sample.readiness.record",
        "purpose": "Exact purpose",
        "authorized": True,
        "qualified": True,
        "roles": ["manufacturing"],
        "fact_refs": references,
        "synthetic": False,
    }
    calls = []

    def historical(_s, _ctx, _product, _project, _subject, identities):
        calls.append(set(identities))
        return {key: facts[key] for key in identities if key in facts}

    monkeypatch.setattr(authority, "_project", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(authority, "_signature_currents", lambda *_args, **_kwargs: pointers)
    monkeypatch.setattr(authority, "_historical_facts", historical)
    with Session() as session, session.begin():
        session.info["read_snapshot"] = True
        monkeypatch.setattr(session, "get_bind", lambda: engine)
        yield SimpleNamespace(
            session=session,
            ctx=Context(tenant, subject, subject, category_id=category),
            product=product,
            project=project,
            engine=engine,
            pointers=pointers,
            facts=facts,
            snapshot=snapshot,
            calls=calls,
        )


def recheck(work, **kwargs):
    return authority.recheck_snapshot(
        work.session,
        work.ctx,
        work.product,
        work.project,
        work.snapshot,
        kwargs.pop("at", AT),
        **kwargs,
    )


def test_rr_exact_current_signature_keeps_all_ref_checks_without_history_io(signature):
    value = recheck(signature)
    assert value["current"] and value["historical_valid"] and not value["needs_review"]
    assert signature.calls == []
    signature.snapshot["fact_refs"][0]["fact_sha256"] = "f" * 64
    assert recheck(signature)["historical_valid"] is False
    assert signature.calls == []


@pytest.mark.parametrize("change", ["subject_id", "series_id", "revision", "epoch"])
def test_rr_corrupt_current_summary_cannot_grant_a_signature(signature, change):
    pointer = signature.pointers[0]
    if change == "epoch":
        pointer.epoch += 1
    else:
        pointer.summary[change] = 2 if change == "revision" else str(uuid4())
    value = recheck(signature)
    assert value["historical_valid"] is False and value["current"] is False
    assert signature.calls == []


@pytest.mark.parametrize("change", ["replaced", "inaccessible", "inaccessible_history"])
def test_rr_old_or_missing_current_uses_exact_history_fallback(signature, change):
    frozen = signature.pointers[1].fact_id
    if change == "replaced":
        signature.pointers[1].fact_id = uuid4()
        signature.pointers[1].fact_revision = signature.pointers[1].epoch = 2
    else:
        signature.pointers.pop()
        if change == "inaccessible_history":
            signature.facts.pop(frozen)
    value = recheck(signature)
    assert signature.calls == [{frozen}]
    assert value["current"] is False
    assert value["historical_valid"] is (change != "inaccessible_history")
    if change != "inaccessible_history":
        assert value["needs_review"] is True
        retained = recheck(signature, retained=True)
        assert retained["current"] and retained["historical_valid"] and retained["needs_review"]


@pytest.mark.parametrize("change", ["issuer", "deadline"])
def test_rr_summary_reuse_still_checks_current_issuer_and_actual_deadline(signature, change):
    if change == "issuer":
        authority.configure_issuer(
            signature.engine,
            key="rr-signature",
            version="v2",
            tenant_id=signature.ctx.tenant_id,
            product_id=signature.product,
            project_id=signature.project,
        )
    value = recheck(signature, at=AT + timedelta(hours=1) if change == "deadline" else AT)
    assert value["current"] is False and value["historical_valid"] and value["needs_review"]
    assert signature.calls == []


@pytest.mark.parametrize("write", [False, True])
def test_non_snapshot_or_writer_keeps_real_history_reads(signature, write):
    signature.session.info["read_snapshot"] = write
    assert recheck(signature, write=write)["current"]
    assert signature.calls == [set(signature.facts)]


def test_rr_current_projection_reads_start_once_outside_current_join(monkeypatch):
    tenant, product, build_id = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, uuid4(), uuid4())
    build = SimpleNamespace(tenant_id=tenant, product_id=product, id=build_id)
    saved = SimpleNamespace(id=uuid4())
    queries, guards = [], []
    with Session() as session, session.begin():
        session.info["read_snapshot"] = True
        monkeypatch.setattr(starts, "_start", lambda *_: saved)
        monkeypatch.setattr(
            starts,
            "_row",
            lambda _s, _ctx, _product, model, identity: guards.append((model, identity)) or saved,
        )

        def execute(query):
            queries.append(str(query.compile()))
            return SimpleNamespace(one=lambda: (None,) * 6)

        monkeypatch.setattr(session, "execute", execute)
        assert starts._projection_current(session, ctx, product, build) == (None, {}, saved)
        assert starts._projection_current(session, ctx, product, build) == (None, {}, saved)
    assert len(queries) == 1
    assert "build_starts" not in queries[0]
    assert guards == [(starts.BuildStart, saved.id)] * 2


def test_rr_test_and_build_projection_share_one_operational_pointer_query(monkeypatch):
    tenant, product, project, build_id = (uuid4() for _ in range(4))
    ctx = Context(tenant, uuid4(), uuid4())
    binding = SimpleNamespace(project_id=project, build_id=build_id)
    pointer = SimpleNamespace(fact_id=uuid4())
    fact = SimpleNamespace(
        tenant_id=tenant,
        product_id=product,
        project_id=project,
        build_id=build_id,
        visibility="category",
        data={},
    )
    queries = []
    monkeypatch.setattr(resources, "_specs", lambda _: [])
    monkeypatch.setattr(resources.BuildFactInput, "model_validate", lambda _: SimpleNamespace())
    monkeypatch.setattr(resources, "build_asset_specs", lambda *_: [])
    monkeypatch.setattr(resources, "_locked_assets", lambda *_args, **_kwargs: {})
    with Session() as session, session.begin():
        session.info["read_snapshot"] = True
        monkeypatch.setattr(session, "scalar", lambda _: fact)

        def scalars(query):
            queries.append(query)
            return [pointer]

        monkeypatch.setattr(session, "scalars", scalars)
        resources._lock_union(session, ctx, product, binding, SimpleNamespace(), lock=False)
        assert operational._pointer(session, ctx, product, build_id) is pointer
    assert len(queries) == 1
    assert queries[0].column_descriptions[0]["entity"] is resources.BuildOperationalCurrent
