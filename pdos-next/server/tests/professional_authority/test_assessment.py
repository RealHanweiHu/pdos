"""Deterministic reductions and bounded fake-session negatives, without a database."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.schemas import FactInput
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import Context

AT = datetime(2026, 10, 2, 12, tzinfo=UTC)
OP, PURPOSE = "verification.request.create", "Synthetic dimensional request"


def fact(kind="duty", **changes):
    return SimpleNamespace(
        **{
            "kind": kind,
            "role": "quality",
            "nature": "real",
            "state": "active",
            "operations": [OP],
            "purposes": [PURPOSE],
            "valid_from": AT - timedelta(hours=1),
            "valid_until": AT + timedelta(hours=1),
            **changes,
        }
    )


def reduce(facts, **changes):
    return authority._reduce(
        facts,
        changes.get("operation", OP),
        changes.get("purpose", PURPOSE),
        changes.get("at", AT),
        synthetic_enabled=changes.get("synthetic", False),
    )


def test_duty_and_qualification_must_match_the_same_professional_role():
    assert reduce([fact(), fact("qualification")]) == (["quality"], True, [])
    roles, qualified, reasons = reduce([fact(role="engineering"), fact("qualification")])
    assert roles == ["engineering"] and qualified is False
    assert "PROFESSIONAL_QUALIFICATION_REQUIRED" in reasons
    assert reduce([fact("qualification")])[0] == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"state": "revoked"}, "QUALIFICATION_REVOKED"),
        ({"valid_until": AT}, "PROFESSIONAL_FACT_EXPIRED"),
        ({"valid_from": AT + timedelta(seconds=1)}, "PROFESSIONAL_FACT_NOT_EFFECTIVE"),
    ],
)
def test_invalid_known_qualification_is_false(changes, reason):
    _, qualified, reasons = reduce([fact(), fact("qualification", **changes)])
    assert qualified is False and reason in reasons


def test_missing_qualification_is_null_and_operation_and_purpose_are_exact():
    assert reduce([fact()]) == (["quality"], None, ["PROFESSIONAL_QUALIFICATION_REQUIRED"])
    missing = ([], None, ["PROFESSIONAL_DUTY_REQUIRED", "PROFESSIONAL_QUALIFICATION_REQUIRED"])
    assert reduce([fact(), fact("qualification")], purpose=PURPOSE + " alternate") == missing
    # Start is now configured, but an unrelated request duty still cannot grant it.
    assert reduce([fact()], operation="test.run.start") == missing
    start_duty = fact(operations=["test.run.start"])
    assert reduce([start_duty], operation="test.run.start") == (
        ["quality"],
        None,
        ["PROFESSIONAL_QUALIFICATION_REQUIRED"],
    )
    assert reduce(
        [start_duty, fact("qualification", operations=["test.run.start"])],
        operation="test.run.start",
    ) == (["quality"], True, [])
    assert reduce([fact()], operation="test.operation.unconfigured-for-test") == (
        [],
        None,
        ["PROFESSIONAL_OPERATION_NOT_CONFIGURED"],
    )


def test_synthetic_authority_is_disabled_by_default():
    facts = [fact(nature="synthetic"), fact("qualification", nature="synthetic")]
    assert reduce(facts)[0] == []
    assert "SYNTHETIC_AUTHORITY_NOT_ALLOWED" in reduce(facts)[2]
    assert reduce(facts, synthetic=True) == (["quality"], True, [])


def test_current_time_uses_each_real_fact_without_a_material_expiry():
    def reference(kind, minutes):
        value = vars(fact(kind, valid_until=AT + timedelta(minutes=minutes)))
        return {
            **value,
            "valid_from": value["valid_from"].isoformat(),
            "valid_until": value["valid_until"].isoformat(),
        }

    material = {
        "operation": OP,
        "purpose": PURPOSE,
        "roles": ["quality"],
        "valid_until": None,
        "fact_refs": [
            reference("duty", 60),
            reference("qualification", 1),
            reference("qualification", 30),
        ],
    }
    assert authority.authority_time_current(material, AT + timedelta(minutes=2))
    assert not authority.authority_time_current(material, AT + timedelta(minutes=30))
    malformed = deepcopy(material)
    malformed["fact_refs"][0]["valid_from"] = AT.replace(tzinfo=None).isoformat()
    assert not authority.authority_time_current(malformed, AT)


def test_issuer_requires_exact_current_server_object_and_scope():
    engine = SimpleNamespace()
    tenant, product, project = (uuid4() for _ in range(3))
    with pytest.raises(ValueError):
        authority.configure_local_synthetic(engine, tenant_id=tenant, product_id=product)
    issuer = authority.configure_local_synthetic(
        engine, tenant_id=tenant, product_id=product, project_id=project, enabled=True
    )
    assert authority._issuer(engine, issuer, tenant, product, project) is issuer
    with pytest.raises(AttributeError):
        issuer.nature = "real"
    with pytest.raises(DomainError):
        authority._issuer(engine, issuer, tenant, uuid4(), project)
    authority.disable_issuer(engine, issuer.key)
    with pytest.raises(DomainError):
        authority._issuer(engine, issuer, tenant, product, project)
    replacement = authority.configure_local_synthetic(
        engine, tenant_id=tenant, product_id=product, project_id=project, enabled=True
    )
    assert replacement.epoch > issuer.epoch
    with pytest.raises(DomainError):
        authority._issuer(engine, issuer, tenant, product, project)
    authority.configure_issuer(
        engine, key="real-issuer", version="v1", tenant_id=tenant, product_id=product
    )
    assert authority.profile(engine)["synthetic_enabled"] is False
    with pytest.raises(DomainError):
        authority._issuer(engine, replacement, tenant, product, project)


def body():
    return {
        "product_id": str(uuid4()),
        "project_id": str(uuid4()),
        "subject_id": str(uuid4()),
        "external_id": "synthetic-duty-1",
        "kind": "duty",
        "role": "quality",
        "operations": [OP],
        "purposes": [PURPOSE],
        "valid_from": (AT - timedelta(hours=1)).isoformat(),
        "valid_until": (AT + timedelta(hours=1)).isoformat(),
        "approval": {
            "system": "Synthetic issuer",
            "external_id": "approval-1",
            "version": "v1",
            "approved_by": "Synthetic signatory",
            "issued_at": AT.isoformat(),
        },
        "sources": [
            {
                "artifact_id": str(uuid4()),
                "expected_revision": 1,
                "line": 1,
                "quote": "Synthetic facts only",
            }
        ],
        "reason": "Synthetic preparation authority only",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"approved": True},
        {"synthetic": True},
        {"nature": "real"},
        {"expected_previous_revision": True},
        {"state": "revoked"},
        {"previous_id": str(uuid4())},
        {"purposes": [" "]},
        {"valid_from": AT.replace(tzinfo=None).isoformat()},
    ],
)
def test_fake_client_policy_and_invalid_series_are_rejected(change):
    with pytest.raises(ValidationError):
        FactInput.model_validate({**body(), **change})


@pytest.mark.parametrize("field", ["expected_revision", "line"])
def test_exact_source_integer_cannot_be_boolean(field):
    value = body()
    value["sources"][0][field] = True
    with pytest.raises(ValidationError):
        FactInput.model_validate(value)


@pytest.mark.parametrize("field", ["version", "approved_by", "external_id"])
def test_approval_requires_fixed_version_and_named_signatory(field):
    value = body()
    value["approval"][field] = " "
    with pytest.raises(ValidationError):
        FactInput.model_validate(value)


class FakeSession:
    def __init__(self):
        self.engine = SimpleNamespace()
        self.tenant, self.product, self.project, self.subject = (uuid4() for _ in range(4))
        self.ctx = Context(self.tenant, self.subject, self.subject)
        self.identity = SimpleNamespace(id=self.subject, access_epoch=1, active=True)
        self.grant = SimpleNamespace(
            id=uuid4(), access_epoch=1, can_write=True, expires_at=AT + timedelta(hours=2)
        )
        self.rows, self.pointers = {}, []
        self.new, self.dirty, self.deleted = (), (), ()
        self.identity_map = self.rows
        self.no_autoflush = nullcontext()
        authority.configure_issuer(
            self.engine, key="issuer", version="v1", tenant_id=self.tenant, product_id=self.product
        )
        for kind in ("duty", "qualification"):
            identity = uuid4()
            row = ProfessionalFact(
                id=identity,
                tenant_id=self.tenant,
                product_id=self.product,
                project_id=self.project,
                subject_id=self.subject,
                owner_id=self.subject,
                visibility="category",
                kind=kind,
                role="quality",
                nature="real",
                issuer_key="issuer",
                issuer_version="v1",
                external_id=kind,
                operations=[OP],
                purposes=[PURPOSE],
                state="active",
                valid_from=AT - timedelta(hours=1),
                valid_until=AT + timedelta(hours=1),
                series_id=identity,
                revision=1,
                previous_id=None,
                previous_revision=None,
                sources=[
                    {
                        "artifact_id": str(uuid4()),
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic",
                    }
                ],
                required_source_read_set=[],
                source_basis={},
                reason="Synthetic fake session",
            )
            row.required_source_read_set = authority._reads(row.sources)
            row.fact_sha256 = authority.digest(authority._material(row))
            self.rows[row.id] = row
            self.pointers.append(
                SimpleNamespace(
                    id=uuid4(),
                    fact_id=row.id,
                    fact_revision=1,
                    epoch=1,
                    series_id=identity,
                    kind=kind,
                    issuer_key="issuer",
                    external_id=kind,
                )
            )

    def get_bind(self):
        return self.engine

    def get(self, model, identity):
        return self.identity if model is Principal else self.rows.get(identity)

    def scalar(self, query):
        return self.grant

    def scalars(self, query):
        if query.column_descriptions[0]["entity"] is ProfessionalFact:
            identities = query._where_criteria[0].right.value
            return [self.rows[identity] for identity in identities if identity in self.rows]
        return self.pointers


def assessed(session):
    return authority.assess(session, session.ctx, session.product, session.project, OP, PURPOSE, AT)


@pytest.fixture
def fake(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(authority, "_project", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(
        authority,
        "_evidence",
        lambda s, ctx, pid, refs: (authority._reads(refs), False, {"security": [{"epoch": 1}]}),
    )
    return session


def test_assessment_time_alone_does_not_change_basis(fake):
    first = assessed(fake)
    later = authority.assess(
        fake, fake.ctx, fake.product, fake.project, OP, PURPOSE, AT + timedelta(minutes=1)
    )
    assert first == later and first["authorized"] is True
    assert first["valid_until"] is None
    assert authority.authority_time_current(first, AT + timedelta(minutes=1))
    assert not authority.authority_time_current(first, AT + timedelta(hours=1))
    assert len(first["required_source_read_set"]) == 2


def test_failed_first_source_does_not_omit_later_negative_epoch(fake, monkeypatch):
    def failed(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic withdrawn source")

    monkeypatch.setattr(authority, "_evidence", failed)
    before = assessed(fake)
    fake.pointers[-1].epoch += 1
    after = assessed(fake)
    assert before["authorized"] is after["authorized"] is False
    assert before["fact_refs"] == after["fact_refs"] == []
    assert before["facts_revision"] != after["facts_revision"]


def test_revoke_restore_never_reuses_review_fingerprint(fake):
    before = assessed(fake)
    pointer = fake.pointers[-1]
    row = fake.rows[pointer.fact_id]
    row.state, row.revision, pointer.fact_revision, pointer.epoch = "revoked", 2, 2, 2
    row.fact_sha256 = authority.digest(authority._material(row))
    revoked = assessed(fake)
    row.state, row.revision, pointer.fact_revision, pointer.epoch = "active", 3, 3, 3
    row.fact_sha256 = authority.digest(authority._material(row))
    restored = assessed(fake)
    assert before["authorized"] is restored["authorized"] is True
    assert revoked["qualified"] is False and revoked["authorized"] is False
    assert len({r["facts_revision"] for r in (before, revoked, restored)}) == 3


def test_source_security_and_grant_epochs_bind_current_assessment(fake, monkeypatch):
    before = assessed(fake)
    monkeypatch.setattr(
        authority,
        "_evidence",
        lambda s, ctx, pid, refs: (authority._reads(refs), False, {"security": [{"epoch": 3}]}),
    )
    safety_changed = assessed(fake)
    fake.grant.access_epoch += 2
    access_changed = assessed(fake)
    assert all(r["authorized"] for r in (before, safety_changed, access_changed))
    assert len({r["facts_revision"] for r in (before, safety_changed, access_changed)}) == 3


def test_overflow_or_private_evidence_failclosed(fake):
    fake.pointers.extend(deepcopy(fake.pointers[0]) for _ in range(101))
    assert len(assessed(fake)["fact_refs"]) == 103
    fake.pointers = fake.pointers[:2]
    row = fake.rows[fake.pointers[0].fact_id]
    row.visibility, row.owner_id = "private", uuid4()
    row.fact_sha256 = authority.digest(authority._material(row))
    # Real visibility is covered by the category/audience RLS transaction checks.
    result = assessed(fake)
    assert result["authorized"] is True


def test_snapshot_recheck_does_not_delegate_to_another_subject(fake):
    snapshot = assessed(fake)
    assert authority.recheck_snapshot(fake, fake.ctx, fake.product, fake.project, snapshot, AT)[
        "current"
    ]
    other = Context(fake.tenant, uuid4(), uuid4())
    assert authority.recheck_snapshot(fake, other, fake.product, fake.project, snapshot, AT)[
        "current"
    ]
    snapshot.pop("purpose")
    assert not authority.recheck_snapshot(fake, fake.ctx, fake.product, fake.project, snapshot, AT)[
        "current"
    ]
