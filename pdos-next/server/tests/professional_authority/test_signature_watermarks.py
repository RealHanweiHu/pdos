"""Pure SQL-boundary substitutes; no database or historical qualification reads."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.professional_authority import service
from pdos_next.domain.professional_authority import signature_watermarks as watermarks
from pdos_next.domain.professional_authority.models import ProfessionalCurrent
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 17, 12, tzinfo=UTC)
OP = "npi.manufacturing_baseline.publish"


class CurrentSession:
    def __init__(self, ctx, engine, pointers):
        self.info = {"scope": (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)}
        self.engine, self.pointers, self.queries = engine, pointers, []

    def get_bind(self):
        return self.engine

    def scalars(self, query):
        assert query.column_descriptions[0]["entity"] is ProfessionalCurrent
        assert query._for_update_arg is None
        self.queries.append(query)
        return self.pointers

    def get(self, *_args, **_kwargs):
        raise AssertionError("The historical Fact, signer and common group must not be loaded")


@pytest.fixture
def case(monkeypatch):
    tenant, category, product, project, reader, signer = (uuid4() for _ in range(6))
    ctx = Context(tenant, reader, reader, category_id=category)
    engine = SimpleNamespace()
    issuer = service.configure_issuer(
        engine,
        key="fixed-issuer",
        version="v1",
        tenant_id=tenant,
        product_id=product,
        project_id=project,
    )
    references, pointers = [], []
    for kind in ("duty", "qualification"):
        identity = uuid4()
        references.append(
            {
                "id": str(identity),
                "series_id": str(identity),
                "revision": 1,
                "epoch": 1,
                "issuer_key": issuer.key,
                "issuer_version": issuer.version,
                "issuer_epoch": issuer.epoch,
                "kind": kind,
                "state": "active",
                "role": "manufacturing",
                "operations": [OP],
                "purposes": ["fixed purpose"],
                "valid_from": (AT - timedelta(days=1)).isoformat(),
                "valid_until": (AT + timedelta(days=1)).isoformat(),
            }
        )
        pointers.append(
            ProfessionalCurrent(
                id=uuid4(),
                tenant_id=tenant,
                category_id=category,
                product_id=product,
                project_id=project,
                subject_id=signer,
                kind=kind,
                issuer_key=issuer.key,
                external_id=kind,
                series_id=identity,
                fact_id=identity,
                fact_revision=1,
                epoch=1,
            )
        )
    snapshot = {
        "scope": {"tenant_id": str(tenant), "product_id": str(product), "project_id": str(project)},
        "subject_id": str(signer),
        "operation": OP,
        "purpose": "fixed purpose",
        "roles": ["manufacturing"],
        "authorized": True,
        "qualified": True,
        "fact_refs": references,
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A sealed signature's qualification must not be reassessed")

    for name in ("assess", "_reduce", "authority_time_current", "_historical_facts"):
        monkeypatch.setattr(service, name, forbidden)
    monkeypatch.setattr(watermarks, "now", lambda: AT)
    return SimpleNamespace(
        ctx=ctx,
        product=product,
        project=project,
        signer=signer,
        engine=engine,
        issuer=issuer,
        pointers=pointers,
        snapshot=snapshot,
        session=CurrentSession(ctx, engine, pointers),
    )


def current(case):
    return watermarks.signature_current(
        case.session, case.ctx, case.product, case.project, case.snapshot
    )


def test_real_current_query_keeps_reader_and_exact_signer_scope_without_reproof(case):
    before = deepcopy(case.snapshot)
    assert current(case) is True
    assert case.snapshot == before
    assert len(case.session.queries) == 1
    params = set(case.session.queries[0].compile().params.values())
    assert {case.ctx.tenant_id, case.product, case.project, case.signer} <= params
    assert case.ctx.actor_id != case.signer
    assert case.session.info["scope"][1] == case.ctx.actor_id


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("fact_id", uuid4()),
        ("fact_revision", 2),
        ("epoch", 2),
        ("project_id", uuid4()),
        ("subject_id", uuid4()),
        ("tenant_id", uuid4()),
        ("product_id", uuid4()),
        ("category_id", uuid4()),
    ],
)
def test_changed_or_cross_scope_current_only_marks_signature_for_review(case, attribute, value):
    setattr(case.pointers[0], attribute, value)
    before = deepcopy(case.snapshot)
    assert current(case) is False
    assert case.snapshot == before


def test_missing_current_cannot_be_replaced_by_a_snapshot_or_unrelated_new_fact(case):
    missing = case.pointers.pop()
    assert current(case) is False
    missing.series_id = uuid4()
    case.pointers.append(missing)
    assert current(case) is False


def test_unrelated_new_current_does_not_reassess_a_frozen_positive_signature(case):
    extra = ProfessionalCurrent(
        tenant_id=case.ctx.tenant_id,
        category_id=case.ctx.category_id,
        product_id=case.product,
        project_id=case.project,
        subject_id=case.signer,
        series_id=uuid4(),
        fact_id=uuid4(),
        fact_revision=1,
        epoch=1,
    )
    case.pointers.append(extra)
    assert current(case) is True


@pytest.mark.parametrize("change", ["missing", "copied_dto", "version", "epoch", "scope"])
def test_actual_trusted_issuer_watermark_must_still_match(case, change):
    registry = case.engine._pdos_professional_issuers
    if change == "missing":
        registry.clear()
    elif change == "copied_dto":
        registry[case.issuer.key] = SimpleNamespace(version="v1", epoch=case.issuer.epoch)
    elif change == "epoch":
        service.disable_issuer(case.engine, case.issuer.key)
        service.configure_issuer(
            case.engine,
            key=case.issuer.key,
            version="v1",
            tenant_id=case.ctx.tenant_id,
            product_id=case.product,
            project_id=case.project,
        )
    elif change == "scope":
        other_engine = SimpleNamespace()
        registry[case.issuer.key] = service.configure_issuer(
            other_engine,
            key=case.issuer.key,
            version="v1",
            tenant_id=case.ctx.tenant_id,
            product_id=case.product,
            project_id=uuid4(),
        )
    else:
        service.configure_issuer(
            case.engine,
            key=case.issuer.key,
            version="v2",
            tenant_id=case.ctx.tenant_id,
            product_id=case.product,
            project_id=case.project,
        )
    assert current(case) is False


@pytest.mark.parametrize(
    "name,value,expected",
    [
        ("valid_from", AT.isoformat(), True),
        ("valid_from", (AT + timedelta(microseconds=1)).isoformat(), False),
        ("valid_until", AT.isoformat(), False),
        ("valid_until", (AT + timedelta(microseconds=1)).isoformat(), True),
        ("valid_until", None, True),
        ("valid_from", None, True),
        ("valid_until", AT.replace(tzinfo=None).isoformat(), False),
        ("valid_until", "not-a-date", False),
    ],
)
def test_only_actual_declared_time_bounds_apply_without_new_ttl(case, name, value, expected):
    case.snapshot["fact_refs"][0][name] = value
    assert current(case) is expected


@pytest.mark.parametrize(
    "change",
    [
        {"role": "quality"},
        {"state": "withdrawn"},
        {"kind": "other"},
        {"operations": ["other.operation"]},
        {"purposes": ["other purpose"]},
    ],
)
def test_irrelevant_fact_expiry_does_not_create_a_whole_chain_deadline(case, change):
    case.snapshot["fact_refs"][0].update(change, valid_until=(AT - timedelta(days=1)).isoformat())
    assert current(case) is True
    # A superseded dependency is still a changed watermark even when its time is irrelevant.
    case.pointers[0].epoch = 2
    assert current(case) is False


def test_minimal_snapshot_uses_explicit_time_only_and_never_adds_absent_bounds(case):
    reference = case.snapshot["fact_refs"][0]
    for key in ("kind", "state", "operations", "purposes", "valid_from", "valid_until"):
        reference.pop(key)
    assert current(case) is True
    reference["valid_until"] = AT.isoformat()
    assert current(case) is False


@pytest.mark.parametrize("change", ["scope", "subject", "empty", "duplicate", "bool_revision"])
def test_malformed_or_wrong_scope_snapshot_never_reaches_current_query(case, change):
    if change == "scope":
        case.snapshot["scope"]["project_id"] = str(uuid4())
    elif change == "subject":
        case.snapshot["subject_id"] = "invalid"
    elif change == "empty":
        case.snapshot["fact_refs"] = []
    elif change == "duplicate":
        case.snapshot["fact_refs"].append(deepcopy(case.snapshot["fact_refs"][0]))
    else:
        case.snapshot["fact_refs"][0]["revision"] = True
    assert current(case) is False
    assert not case.session.queries


def test_another_callers_transaction_remains_forbidden(case):
    case.session.info["scope"] = (
        case.ctx.tenant_id,
        case.signer,
        case.signer,
        case.ctx.category_id,
    )
    with pytest.raises(DomainError, match="请求身份与事务范围不符"):
        current(case)
    assert not case.session.queries
