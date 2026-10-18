"""Knowledge publication has its own bounded professional authority.

These checks exercise the existing reducer and import preflight, without a
database or a simulated import transaction. Real source verification stays with
the existing evidence owner; a preflight reaching it does not prove an import.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.professional_authority.schemas import FactInput
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.service import Context

AT = datetime(2026, 10, 18, 12, tzinfo=UTC)
OPERATION = "knowledge.rule.publish"
PURPOSE = "Publish one applicable internal knowledge rule"
OLD_ROLES = ("engineering", "quality", "manufacturing")


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Knowledge authority checks must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def fact(kind="duty", **changes):
    return ProfessionalFact(
        **{
            "kind": kind,
            "role": "knowledge",
            "nature": "real",
            "state": "active",
            "operations": [OPERATION],
            "purposes": [PURPOSE],
            "valid_from": AT - timedelta(hours=1),
            "valid_until": AT + timedelta(hours=1),
            **changes,
        }
    )


def reduce(facts, *, operation=OPERATION, purpose=PURPOSE, at=AT):
    return authority._reduce(facts, operation, purpose, at, synthetic_enabled=False)


def test_knowledge_role_never_expands_the_existing_operation_matrix():
    assert authority.OPERATION_ROLES[OPERATION] == frozenset({"knowledge"})
    assert all(
        "knowledge" not in roles
        for operation, roles in authority.OPERATION_ROLES.items()
        if operation != OPERATION
    )


@pytest.mark.parametrize("role", OLD_ROLES)
def test_existing_professional_pair_cannot_publish_knowledge_even_if_it_claims_operation(role):
    roles, qualified, reasons = reduce([fact(role=role), fact("qualification", role=role)])
    assert roles == [] and qualified is not True
    assert "PROFESSIONAL_DUTY_REQUIRED" in reasons
    assert "PROFESSIONAL_QUALIFICATION_REQUIRED" in reasons


def test_knowledge_pair_cannot_execute_any_existing_professional_operation():
    operations = list(authority.OPERATION_ROLES)
    facts = [fact(operations=operations), fact("qualification", operations=operations)]
    for operation in operations:
        if operation == OPERATION:
            continue
        roles, qualified, reasons = reduce(facts, operation=operation)
        assert roles == [] and qualified is not True, operation
        assert "PROFESSIONAL_DUTY_REQUIRED" in reasons, operation


def test_knowledge_requires_both_current_duty_and_matching_qualification():
    assert reduce([fact(), fact("qualification")]) == (["knowledge"], True, [])
    assert reduce([fact()]) == (["knowledge"], None, ["PROFESSIONAL_QUALIFICATION_REQUIRED"])
    roles, qualified, reasons = reduce([fact("qualification")])
    assert roles == [] and "PROFESSIONAL_DUTY_REQUIRED" in reasons
    assert not (roles and qualified is True)
    roles, qualified, reasons = reduce([fact(), fact("qualification", role="quality")])
    assert roles == ["knowledge"] and qualified is not True
    assert "PROFESSIONAL_QUALIFICATION_REQUIRED" in reasons


def test_knowledge_uses_exact_purpose_and_existing_finite_validity():
    facts = [fact(), fact("qualification")]
    assert reduce(facts, at=AT - timedelta(hours=1)) == (["knowledge"], True, [])
    for changes in (
        {"at": AT + timedelta(hours=1)},
        {"at": AT - timedelta(hours=1, seconds=1)},
        {"purpose": PURPOSE + " for another use"},
    ):
        roles, qualified, _ = reduce(facts, **changes)
        assert roles == [] and qualified is not True


def body():
    return {
        "product_id": str(uuid4()),
        "project_id": str(uuid4()),
        "subject_id": str(uuid4()),
        "external_id": "knowledge-duty-1",
        "kind": "duty",
        "role": "knowledge",
        "operations": [OPERATION],
        "purposes": [PURPOSE],
        "valid_from": (AT - timedelta(hours=1)).isoformat(),
        "valid_until": (AT + timedelta(hours=1)).isoformat(),
        "approval": {
            "system": "Offline fixed issuer material",
            "external_id": "knowledge-approval-1",
            "version": "v1",
            "approved_by": "Named knowledge authority",
            "issued_at": AT.isoformat(),
        },
        "sources": [
            {
                "artifact_id": str(uuid4()),
                "expected_revision": 1,
                "line": 1,
                "quote": "Exact named knowledge publication authority",
            }
        ],
        "reason": "Explicit bounded professional role, not an inherited engineering role",
    }


@pytest.mark.parametrize("kind", ["duty", "qualification"])
def test_dto_and_storage_declaration_accept_the_exact_knowledge_role(kind):
    value = FactInput.model_validate({**body(), "kind": kind})
    assert value.role == "knowledge" and value.kind == kind
    role_checks = [
        str(constraint.sqltext)
        for constraint in ProfessionalFact.__table__.constraints
        if isinstance(constraint, CheckConstraint) and "role IN" in str(constraint.sqltext)
    ]
    assert len(role_checks) == 1
    assert "role IN ('engineering','quality','manufacturing','knowledge')" in role_checks[0]
    declaration = str(CreateTable(ProfessionalFact.__table__).compile(dialect=dialect()))
    assert role_checks[0] in declaration


def test_dto_preserves_strict_source_approval_and_bounded_validity_for_knowledge():
    original = body()
    for invalid in (
        {"role": "knowledge_admin"},
        {"valid_until": original["valid_from"]},
        {"valid_until": None},
        {"sources": []},
        {"approved": True},
    ):
        with pytest.raises(ValidationError):
            FactInput.model_validate({**original, **invalid})


class EvidenceBoundary(Exception):
    """The actual import reached its existing source-verification boundary."""


@pytest.fixture
def import_preflight(monkeypatch):
    value = FactInput.model_validate(body())
    tenant, actor = uuid4(), uuid4()
    ctx = Context(tenant, actor, actor)
    engine = SimpleNamespace()
    issuer = authority.configure_issuer(
        engine,
        key="offline-knowledge-issuer",
        version="v1",
        tenant_id=tenant,
        product_id=value.product_id,
        project_id=value.project_id,
    )
    principal = Principal(id=value.subject_id, tenant_id=tenant, kind="human", active=True)

    class PreflightSession:
        def get_bind(self):
            return engine

        def get(self, model, identity):
            assert model is Principal and identity == value.subject_id
            return principal

    def evidence(session, context, product_id, sources):
        assert context is ctx and product_id == value.product_id
        assert sources == [ref.model_dump(mode="json") for ref in value.sources]
        raise EvidenceBoundary()

    monkeypatch.setattr(authority, "now", lambda: AT)
    monkeypatch.setattr(
        authority,
        "_project",
        lambda *_args, **_kwargs: (object(), SimpleNamespace(visibility="category")),
    )
    monkeypatch.setattr(authority, "_evidence", evidence)
    return SimpleNamespace(session=PreflightSession(), ctx=ctx, issuer=issuer, value=value)


def test_trusted_import_accepts_knowledge_preflight_and_still_requires_real_evidence(
    import_preflight,
):
    c = import_preflight
    with pytest.raises(EvidenceBoundary):
        authority.trusted_import(c.session, c.ctx, c.issuer, c.value)


@pytest.mark.parametrize(
    "role,operation",
    [
        *((role, OPERATION) for role in OLD_ROLES),
        ("knowledge", "release.engineering.approve"),
        ("knowledge", "test.run.review"),
        ("knowledge", "release.manufacturing.approve"),
    ],
)
def test_trusted_import_rejects_cross_role_claims_before_source_or_fact_writes(
    import_preflight,
    role,
    operation,
):
    c = import_preflight
    value = c.value.model_copy(update={"role": role, "operations": [operation]})
    with pytest.raises(DomainError) as raised:
        authority.trusted_import(c.session, c.ctx, c.issuer, value)
    assert raised.value.reason == "AUTHORITY_OPERATION_MISMATCH"
