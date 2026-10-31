"""Default M3 entry skills from server scope and persisted facts; no database."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject.models import Proposal, ProposalSubmission
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, UploadedOriginal


class Session:
    def __init__(self):
        self.rows = {}
        self.reads = []

    def put(self, model, **fields):
        row = NS(id=uuid4(), **fields)
        self.rows[model, row.id] = row
        return row

    def get(self, model, identity):
        self.reads.append((model, identity))
        return self.rows.get((model, identity))


class Store:
    def __init__(self, session, run):
        self.session, self.run = session, run
        self.checked = []
        self.failure = None

    @contextmanager
    def transaction(self, scope):
        if self.failure:
            raise self.failure
        yield self.session, self.run

    def authority(self, session, scope):
        assert session is self.session
        self.checked.append(scope)


@pytest.fixture(autouse=True)
def synthetic_source_guard(monkeypatch):
    def source(session, ctx, product_id, identity, revision):
        row = session.get(Artifact, identity)
        if not row or row.status != "active" or row.revision != revision:
            raise DomainError("SOURCE_UNAVAILABLE", "synthetic stale source")
        return row

    monkeypatch.setattr("pdos_next.agent_kernel.bootstrap.source_for", source)


def fixture(*, category=True, proposal=False, status="draft", reviewer=False):
    scope = RunScope(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4() if category else None)
    session = Session()
    row = None
    if proposal:
        row = session.put(
            Proposal, tenant_id=scope.tenant_id, category_id=scope.category_id,
            status=status, current_submission_id=None, source_refs=[],
        )
        scope = replace(scope, proposal_id=row.id)
        if reviewer:
            submission = session.put(
                ProposalSubmission, tenant_id=scope.tenant_id, proposal_id=row.id,
                reviewer_id=scope.requester_id,
            )
            row.current_submission_id = submission.id
    run = NS(read_sources=[])
    owner = Bootstrap.__new__(Bootstrap)
    owner.store = Store(session, run)
    owner.commands = NS(context=DomainCommands.context)
    return NS(owner=owner, scope=scope, session=session, run=run, proposal=row)


def test_personal_entry_has_no_default_business_skill():
    f = fixture(category=False)
    assert f.owner.default_preload(f.scope) == ()
    assert f.owner.store.checked == [f.scope]
    assert f.session.reads == []


def test_category_entry_preloads_proposal_drafting():
    f = fixture()
    assert f.owner.default_preload(f.scope) == ("proposal_drafting",)
    assert f.owner.store.checked == [f.scope]


def test_proposal_entry_preloads_drafting_and_gap_check():
    f = fixture(proposal=True)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_current_g0_reviewer_preloads_decision_material_skills():
    f = fixture(proposal=True, status="in_review", reviewer=True)
    assert f.owner.default_preload(f.scope) == ("gap_check", "option_comparison")


@pytest.mark.parametrize("status", ["draft", "returned", "approved", "rejected", "withdrawn"])
def test_historical_reviewer_is_not_current_g0_entry(status):
    f = fixture(proposal=True, status=status, reviewer=True)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_other_requester_in_review_is_not_given_reviewer_entry():
    f = fixture(proposal=True, status="in_review", reviewer=True)
    current = f.session.get(ProposalSubmission, f.proposal.current_submission_id)
    current.reviewer_id = uuid4()
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_missing_proposal_is_rejected_instead_of_preloaded_from_client_scope():
    f = fixture()
    with pytest.raises(DomainError) as error:
        f.owner.default_preload(replace(f.scope, proposal_id=uuid4()))
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("isolation", ["research", "extract", "mcp"])
def test_isolated_graph_never_inherits_main_entry_skills(isolation):
    f = fixture(proposal=True)
    assert f.owner.default_preload(replace(f.scope, isolation=isolation)) == ()
    assert f.owner.store.checked == []
    assert f.session.reads == []


@pytest.mark.parametrize("code", ["FORBIDDEN_SCOPE", "CANCELLED_RUN"])
def test_scope_or_cancel_failure_cannot_be_bypassed_by_preload(code):
    f = fixture(category=False)
    f.owner.store.failure = DomainError(code, "synthetic current authority failure")
    with pytest.raises(DomainError) as error:
        f.owner.default_preload(f.scope)
    assert error.value.code == code


def test_ordinary_artifact_does_not_imply_customer_original_for_rfq():
    f = fixture(proposal=True)
    artifact = f.session.put(
        Artifact, tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
        original_id=None, revision=1, status="active", visibility="private",
    )
    f.run.read_sources = [{"artifact_id": str(artifact.id), "expected_revision": 1}]
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def attach_original(f):
    original = f.session.put(
        UploadedOriginal, tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
        product_id=None,
        owner_id=f.scope.requester_id, revision=1, status="parsed", visibility="private",
        source_label="客户提供的 RFQ", scan_status="clean",
    )
    artifact = f.session.put(
        Artifact, tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
        product_id=None, original_id=original.id, revision=1, status="active",
        visibility="private", owner_id=f.scope.requester_id,
    )
    f.proposal.source_refs = [{"type": "original", "id": str(artifact.id), "version": 1}]
    f.run.read_sources = [{"artifact_id": str(artifact.id), "expected_revision": 1}]
    return artifact


def test_proposal_with_actual_bound_original_preloads_rfq():
    f = fixture(proposal=True)
    attach_original(f)
    assert f.owner.default_preload(f.scope) == (
        "proposal_drafting", "gap_check", "rfq_extraction",
    )


def test_current_reviewer_with_original_keeps_review_material_entry():
    f = fixture(proposal=True, status="in_review", reviewer=True)
    attach_original(f)
    assert f.owner.default_preload(f.scope) == ("gap_check", "option_comparison")


@pytest.mark.parametrize("field,value", [
    ("revision", 2), ("status", "withdrawn"),
    ("tenant_id", uuid4()), ("category_id", uuid4()), ("original_id", uuid4()),
])
def test_moved_or_unreadable_original_artifact_does_not_preload_rfq(field, value):
    f = fixture(proposal=True)
    artifact = attach_original(f)
    setattr(artifact, field, value)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_missing_artifact_cannot_be_substituted_by_original_metadata():
    f = fixture(proposal=True)
    artifact = attach_original(f)
    del f.session.rows[Artifact, artifact.id]
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_original_not_mounted_on_proposal_does_not_preload_rfq():
    f = fixture(proposal=True)
    attach_original(f)
    f.proposal.source_refs = []
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_original_not_bound_to_run_does_not_preload_rfq():
    f = fixture(proposal=True)
    attach_original(f)
    f.run.read_sources = []
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_artifact_reference_is_not_a_mounted_original_reference():
    f = fixture(proposal=True)
    attach_original(f)
    f.proposal.source_refs[0]["type"] = "artifact"
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_uploaded_root_identity_is_not_an_artifact_version_reference():
    f = fixture(proposal=True)
    artifact = attach_original(f)
    f.proposal.source_refs[0]["id"] = str(artifact.original_id)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_mounted_version_must_match_the_exact_run_read_source_version():
    f = fixture(proposal=True)
    attach_original(f)
    f.proposal.source_refs[0]["version"] = 2
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


@pytest.mark.parametrize("field,value", [
    ("tenant_id", uuid4()), ("category_id", uuid4()), ("product_id", uuid4()),
    ("status", "failed"), ("status", "needs_ocr"), ("scan_status", "infected"),
])
def test_unavailable_original_root_does_not_activate_rfq(field, value):
    f = fixture(proposal=True)
    artifact = attach_original(f)
    original = f.session.get(UploadedOriginal, artifact.original_id)
    setattr(original, field, value)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_actual_current_source_guard_rejection_does_not_activate_rfq(monkeypatch):
    f = fixture(proposal=True)
    attach_original(f)

    def blocked(*_):
        raise DomainError("ORIGINAL_SECURITY_BLOCKED", "synthetic new scan invalidated")

    monkeypatch.setattr("pdos_next.agent_kernel.bootstrap.source_for", blocked)
    assert f.owner.default_preload(f.scope) == ("proposal_drafting", "gap_check")


def test_bootstrap_installs_default_preload_without_external_override():
    owner = Bootstrap(NS())
    assert owner.adapters().preload == owner.default_preload


def test_explicit_runtime_preload_override_remains_supported():
    def custom(scope):
        return ("public_research",)

    owner = Bootstrap(NS(), ports=RuntimePorts(preload=custom))
    assert owner.adapters().preload is custom


def test_project_entry_does_not_preload_proposal_drafting():
    f = fixture()
    scope = replace(f.scope, project_id=uuid4())
    assert f.owner.default_preload(scope) == ()
    assert f.owner.store.checked == [scope]
    assert f.session.reads == []


def test_proposal_entry_keeps_its_skills_when_a_project_is_also_bound():
    f = fixture(proposal=True)
    scope = replace(f.scope, project_id=uuid4())
    assert f.owner.default_preload(scope) == ("proposal_drafting", "gap_check")
