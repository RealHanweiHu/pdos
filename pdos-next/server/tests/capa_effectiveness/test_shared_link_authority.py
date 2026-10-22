"""Current consumer and original signer are separate; no target DB connection.

Real SQLAlchemy Session/UOW and exact ORM query shapes are used, while the
original failure/output/authority/policy ports are explicit saved-row fakes.
These checks do not attest actual professional qualification or PG guards.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_effectiveness.test_participants_owner import work as work
from capa_verification.test_pure import basis as original_basis  # noqa: F401 - pytest fixture
from capa_verification.test_pure import output

from pdos_next import service as common
from pdos_next.domain.capa_verification import service
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.capa_verification.schemas import FixedRef
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution import policy
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal


@pytest.fixture
def shared(work, original_basis, monkeypatch):  # noqa: F811 - imported pytest fixture
    basis = original_basis.model_copy(update={"scope": work.scope})
    basis = basis.model_copy(update={"basis_sha256": service._basis_digest(basis)})
    signer = uuid4()
    signer_ctx = common.Context(
        work.ctx.tenant_id, signer, signer, category_id=work.ctx.category_id
    )
    expires = datetime.now(UTC) + timedelta(hours=1)
    person = work.s.seed(
        Principal,
        id=signer,
        tenant_id=work.ctx.tenant_id,
        kind="human",
        active=True,
        access_epoch=1,
    )
    grant = work.s.seed(
        Grant,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        principal_id=signer,
        can_write=True,
        access_epoch=1,
        expires_at=expires,
    )
    fact = work.s.seed(
        ProfessionalFact,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        subject_id=signer,
        revision=1,
        state="active",
        valid_from=datetime.now(UTC) - timedelta(hours=1),
        valid_until=expires,
    )
    assessment = {
        "scope": work.scope.model_dump(mode="json"),
        "subject_id": str(signer),
        "operation": "quality.capa.followup.link",
        "purpose": basis.purpose,
        "authorized": True,
        "qualified": True,
        "roles": ["quality"],
        "fact_refs": [{"id": str(fact["id"]), "revision": 1, "epoch": 1}],
        "facts_revision": "a" * 64,
        "valid_until": None,
        "required_source_read_set": [],
        "synthetic": True,
    }
    published = {
        "id": "policy-id",
        "revision": 1,
        "risk": "low",
        "independent_verification": True,
        "nature": "synthetic",
        "valid_until": None,
        "facts_revision": "b" * 64,
        "sources": [],
        "required_source_read_set": [],
        "source_basis": [
            {
                "id": "policy-id",
                "revision": 1,
                "state": "active",
                "valid_from": (expires - timedelta(hours=2)).isoformat(),
                "valid_until": expires.isoformat(),
            }
        ],
        "private": False,
    }
    selected = output(basis)
    value = SimpleNamespace(
        work=work,
        basis=basis,
        signer=signer,
        signer_ctx=signer_ctx,
        person=person,
        grant=grant,
        fact=fact,
        assessment=assessment,
        policy=published,
        source_epoch=1,
        source_calls=[],
        source_hook=None,
        authority_calls=[],
        authority_current=True,
        human_calls=[],
    )
    monkeypatch.setattr(service, "recheck_followup_basis", lambda *args, **kw: basis)
    monkeypatch.setattr(service, "_reading", lambda *args, **kw: selected)

    def human(_s, ctx, pid, **kwargs):
        value.human_calls.append(ctx)
        assert pid == work.pid

    def sources(_s, ctx, pid, reads):
        value.source_calls.append(ctx)
        if value.source_hook:
            value.source_hook(len(value.source_calls))
        return [
            {
                "id": str(reads[0].artifact_id)
                if hasattr(reads[0], "artifact_id")
                else reads[0]["artifact_id"],
                "revision": 1,
                "epoch": value.source_epoch,
            }
        ], False

    def recheck(_s, ctx, pid, project_id, snapshot, at, **kwargs):
        value.authority_calls.append((ctx, at, kwargs))
        assert ctx is work.ctx and ctx.requester_id != signer and ctx.run_id is None
        assert snapshot == value.assessment
        assert pid == work.pid and project_id == work.scope.project_id
        assert kwargs == {"write": False, "retained": True}
        return {
            "current": value.authority_current,
            "assessment": deepcopy(value.assessment),
            "reason_codes": [] if value.authority_current else ["PROFESSIONAL_AUTHORITY_CHANGED"],
        }

    monkeypatch.setattr(service.quality, "_human", human)
    monkeypatch.setattr(service, "source_basis", sources)
    monkeypatch.setattr(professional, "recheck_snapshot", recheck)
    monkeypatch.setattr(
        policy,
        "assess",
        lambda _s, ctx, pid, project, purpose: (
            deepcopy(value.policy) if ctx is work.ctx else pytest.fail("borrowed signer policy ACL")
        ),
    )
    resolved = service.resolve_followup_outputs(
        work.s, signer_ctx, work.pid, basis, basis.actions[0].action_id, (selected.ref,)
    )
    evidence, _ = sources(work.s, signer_ctx, work.pid, resolved.required_source_read_set)
    row = work.s.seed(
        RemediationLinkRecord,
        id=uuid4(),
        revision=1,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        issue_id=basis.issue_id,
        purpose=basis.purpose,
        owner_id=signer,
        writer_id=signer,
        visibility="category",
        basis_snapshot=basis.model_dump(mode="json"),
        basis_sha256=basis.basis_sha256,
        output_snapshot=resolved.model_dump(mode="json"),
        resolution_sha256=resolved.resolution_sha256,
        action_id=resolved.action_id,
        required_source_read_set=[
            r.model_dump(mode="json") for r in resolved.required_source_read_set
        ],
        source_basis={"artifact_sources": evidence},
        authority_snapshot=deepcopy(assessment),
        policy_snapshot=deepcopy(published),
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    value.row, value.ref = row, FixedRef(id=row["id"], revision=1)
    value.source_calls.clear()
    value.human_calls.clear()
    return value


def read(v):
    return service._link(v.work.s, v.work.ctx, v.work.pid, v.basis, v.ref)


def test_shared_consumer_reads_original_signer_without_borrowing_output_or_policy_acl(shared):
    v = shared
    before = deepcopy(v.row)
    result = read(v)
    assert result.outputs and result.owner_id == v.work.actor
    assert v.authority_calls and all(c is v.work.ctx for c, _, _ in v.authority_calls)
    assert all(c is v.work.ctx for c in v.source_calls + v.human_calls)
    assert v.row == before
    assert "paired" not in str(result.model_dump(mode="json"))
    statements = v.work.s.queries
    assert all(
        st.get_execution_options().get("autoflush") is False
        for st in statements
        if st.get_execution_options().get("populate_existing")
    )


@pytest.mark.parametrize("field", ["subject", "writer", "owner", "scope", "operation", "purpose"])
def test_saved_signer_binding_is_exact_not_issue_owner_or_consumer(shared, field):
    v = shared
    if field == "subject":
        v.row["authority_snapshot"]["subject_id"] = str(v.work.actor)
    elif field in {"writer", "owner"}:
        v.row[f"{field}_id"] = uuid4()
    elif field == "scope":
        v.row["authority_snapshot"]["scope"]["project_id"] = str(uuid4())
    else:
        v.row["authority_snapshot"][field] = "another exact operation or purpose"
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert not v.authority_calls


@pytest.mark.parametrize("field", ["inactive", "agent", "grant_write", "grant_expiry", "no_grant"])
def test_original_signer_later_membership_does_not_erase_signed_history(shared, field):
    v = shared
    if field == "inactive":
        v.person["active"] = False
    elif field == "agent":
        v.person["kind"] = "agent"
    elif field == "grant_write":
        v.grant["can_write"] = False
    elif field == "grant_expiry":
        v.grant["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    else:
        v.work.s.rows[Grant.__tablename__].remove(v.grant)
    assert read(v).outputs


def test_saved_signer_qualification_must_remain_current_before_shared_link_return(shared):
    v = shared
    v.authority_current = False  # explicit current professional-owner refusal, no positive fake
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.reason == "RECHECK_REQUIRED"
    assert v.row["authority_snapshot"]["facts_revision"] == "a" * 64


@pytest.mark.parametrize(
    "field", ["revision", "facts_revision", "source_basis", "private", "valid_until"]
)
def test_policy_current_and_issuer_epoch_not_only_old_artifact_are_bound(shared, field):
    v = shared
    v.policy[field] = (
        2
        if field == "revision"
        else ["changed epoch"]
        if field == "source_basis"
        else True
        if field == "private"
        else "changed"
    )
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.reason == "RECHECK_REQUIRED"


def test_private_link_cannot_be_read_using_original_signer_identity(shared):
    v = shared
    v.row["visibility"] = "private"
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.status == 403 and not v.authority_calls


def test_current_consumer_grant_retraction_still_blocks_saved_shared_link(shared):
    v = shared
    v.work.grant["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.status == 403


def test_private_source_acl_stays_under_actual_consumer_not_original_signer(shared, monkeypatch):
    v = shared

    def source_refusal(_s, ctx, _pid, _reads):
        assert ctx is v.work.ctx and ctx.requester_id != v.signer
        raise DomainError("FORBIDDEN_SCOPE", "explicit private source owner refusal", 403)

    monkeypatch.setattr(service, "source_basis", source_refusal)
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.status == 403
    assert len(v.authority_calls) == 1


def test_expiry_during_last_actual_consumer_grant_sql_is_rejected(shared, monkeypatch):
    v = shared
    at = datetime.now(UTC)
    v.work.grant["expires_at"] = at + timedelta(seconds=5)
    monkeypatch.setattr(service, "now", lambda: at)
    query_count = 0

    def after_query(table):
        nonlocal at, query_count
        if table == Grant.__tablename__:
            query_count += 1
            if query_count == 4:  # current consumer initial/refresh/final/final-clock check
                at += timedelta(seconds=6)

    v.work.s.after_query = after_query
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.status == 403 and query_count == 4


@pytest.mark.parametrize(
    "change", ["source_epoch", "consumer_epoch", "issuer_epoch", "policy_epoch"]
)
def test_post_owner_io_rechecks_source_and_original_signer_runtime(shared, change):
    v = shared

    def drift(count):
        if count != 4:
            return  # final source closure after both real owner passes
        if change == "source_epoch":
            v.source_epoch += 1
        elif change == "consumer_epoch":
            v.work.grant["access_epoch"] += 1
        else:
            registry = "professional_issuer" if change == "issuer_epoch" else "quality_policy"
            setattr(
                v.work.s.get_bind(),
                f"_pdos_{registry}_epochs",
                {"actual-port": 2},
            )

    v.source_hook = drift
    with pytest.raises(DomainError) as error:
        read(v)
    assert error.value.reason == "SOURCE_STALE"


def test_clock_sampled_after_final_io_not_original_save_time(shared, monkeypatch):
    v = shared
    at = datetime.now(UTC)
    v.fact["valid_from"] = at + timedelta(seconds=5)
    monkeypatch.setattr(service, "now", lambda: at)

    def after_query(table):
        nonlocal at
        if table == ProfessionalFact.__tablename__:
            at += timedelta(seconds=6)

    v.work.s.after_query = after_query
    result = read(v)
    assert result.outputs
    assert any(value.code == "RECHECK_REQUIRED" for value in result.missing)


def test_expired_unrelated_old_fact_is_not_a_new_future_boundary(shared):
    v = shared
    old = v.work.s.seed(
        ProfessionalFact,
        id=uuid4(),
        tenant_id=v.work.ctx.tenant_id,
        product_id=v.work.pid,
        project_id=v.work.scope.project_id,
        subject_id=v.signer,
        revision=1,
        state="active",
        valid_from=datetime.now(UTC) - timedelta(days=2),
        valid_until=datetime.now(UTC) - timedelta(days=1),
    )
    v.assessment["fact_refs"].append({"id": str(old["id"]), "revision": 1, "epoch": 1})
    v.row["authority_snapshot"] = deepcopy(v.assessment)
    assert read(v).outputs
