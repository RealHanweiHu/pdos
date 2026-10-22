"""Root-run PG/API proof renewal; never mutate an immutable Confirmation.

Only the two expiry readers use a controlled future clock during rejection and
receipt replay. Fresh confirmation/save and all actual events use the real clocks.
This is not evidence that wall time elapsed or that SQL clocks were advanced.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from quality_followup_transactions.fixtures import (
    complete_command,
    counts,
    fixed_issue,
    post,
    root_command,
)
from quality_followup_transactions.test_transactions import prepared
from sqlalchemy import func, select
from test_project_first_plan import accepted

from pdos_next import quality_followup_host as host
from pdos_next import service as common
from pdos_next.database import tenant_session
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey

pytest_plugins = ["quality_followup_transactions.fixtures"]


def _proof(work, command):
    token_hash = common.digest(command["payload"]["confirmation_token"])
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        row = session.scalar(select(Confirmation).where(Confirmation.token_hash == token_hash))
        assert row is not None
        return SimpleNamespace(
            id=row.id,
            consumed=row.consumed,
            expires_at=row.expires_at,
            snapshot=deepcopy(row.snapshot),
        )


def _counts(work):
    value = counts(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        value[Confirmation.__tablename__] = session.scalar(
            select(func.count()).select_from(Confirmation)
        )
    return value


def _assert_unchanged(work, baseline, before, original):
    assert _counts(work) == baseline
    current = fixed_issue(work)
    assert (current.id, current.revision, current.issue_snapshot) == (
        before.id,
        before.revision,
        before.issue_snapshot,
    )
    assert _proof(work, original).consumed is False


def _assert_plain_rejection(response, code):
    assert response.status_code == 409, response.text
    value = response.json()
    assert value["code"] == code, response.text
    assert "recovery" not in value


def test_expired_followup_proof_has_bound_no_saved_repreview_and_saved_replay(
    followup_work, monkeypatch
):
    work = followup_work
    accepted(work.quality, root_command(work))
    before = fixed_issue(work)
    original = prepared(work, complete_command(work))
    original_proof = _proof(work, original)
    assert original_proof.consumed is False
    baseline = _counts(work)
    deadline = original_proof.expires_at + timedelta(microseconds=1)

    # Do not UPDATE expires_at (the database forbids changing proof material),
    # mock the source/SQL clock, or waive any professional/lifecycle check.
    with monkeypatch.context() as expiry:
        expiry.setattr(common, "now", lambda: deadline)
        expiry.setattr(host, "now", lambda: deadline)
        expired = post(work.quality, original)
        assert expired.status_code == 409, expired.text
        value = expired.json()
        assert value["code"] == "CONFIRMATION_REQUIRED"
        assert value["detail"]["reason"] == "FOLLOWUP_CONFIRMATION_EXPIRED", expired.text
        recovery = value["recovery"]
        expected = deepcopy(original)
        expected["payload"] = {
            key: item
            for key, item in expected["payload"].items()
            if key not in {"approval_token", "confirmation_token"}
        }
        assert recovery == {"state": "not_saved_expired_proof", "command": expected}
        assert recovery["command"]["command_id"] == original["command_id"]
        assert recovery["command"]["idempotency_key"] == original["idempotency_key"]
        _assert_unchanged(work, baseline, before, original)

        # A token that does not identify the actual old proof cannot establish
        # no-saved provenance. An expired proof for different material cannot
        # renew a changed conclusion either, even though its sources are valid.
        missing = deepcopy(original)
        missing["payload"]["confirmation_token"] = f"not-the-original-proof-{uuid4().hex}"
        _assert_plain_rejection(post(work.quality, missing), "CONFIRMATION_REQUIRED")
        _assert_unchanged(work, baseline, before, original)
        different = deepcopy(original)
        different["payload"]["completions"] = [deepcopy(work.completions[1])]
        _assert_plain_rejection(post(work.quality, different), "CONFIRMATION_REQUIRED")
        _assert_unchanged(work, baseline, before, original)

    # Real clocks, an unchanged command/key/semantic scope, a real shared
    # preview and a NEW actual T1 consumption. No old proof is renewed in place.
    renewed = prepared(work, recovery["command"])
    assert renewed["command_id"] == original["command_id"]
    assert renewed["idempotency_key"] == original["idempotency_key"]
    assert renewed["payload"]["confirmation_token"] != original["payload"]["confirmation_token"]
    assert {
        key: item for key, item in renewed["payload"].items() if key != "confirmation_token"
    } == recovery["command"]["payload"]
    fresh_proof = _proof(work, renewed)
    assert fresh_proof.id != original_proof.id and fresh_proof.consumed is False
    before_save = _counts(work)
    committed = post(work.quality, renewed)
    assert committed.status_code == 200, committed.text
    receipt = committed.json()
    assert "recovery" not in receipt
    saved = fixed_issue(work)
    assert saved.revision == before.revision + 1 and saved.previous_issue_version_id == before.id
    assert receipt["subject_type"] == "quality_issue"
    assert receipt["subject_id"] == str(saved.id)
    assert saved.source_basis["shared_proof"] == {"id": str(fresh_proof.id), "tier": "T1"}
    assert _proof(work, original).consumed is False
    assert _proof(work, renewed).consumed is True
    assert fixed_issue(work, before.revision).issue_snapshot == before.issue_snapshot
    after_save = _counts(work)
    for cls in (QualityIssueVersion, Receipt, Audit, Outbox, RequestKey):
        assert after_save[cls.__tablename__] == before_save[cls.__tablename__] + 1
    assert after_save[Confirmation.__tablename__] == before_save[Confirmation.__tablename__]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert (
            session.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "capa.actions_completed"
        )

    # Replaying the NEW saved full command returns its exact Receipt before
    # inspecting even a consumed/expired proof; no new consumption or renewal.
    after_expiry = fresh_proof.expires_at + timedelta(microseconds=1)
    with monkeypatch.context() as expiry:
        expiry.setattr(common, "now", lambda: after_expiry)
        expiry.setattr(host, "now", lambda: after_expiry)
        replay = post(work.quality, renewed)
        assert replay.status_code == 200, replay.text
        assert replay.json() == receipt
        assert "recovery" not in replay.json()
        assert _counts(work) == after_save

        # The old full request has a different request digest because its token
        # is different. Same key must conflict instead of overwriting the key
        # or interpreting that old failed proof as permission to renew again.
        _assert_plain_rejection(post(work.quality, original), "DUPLICATE_INTENT_CONFLICT")
        assert _counts(work) == after_save
        consumed = deepcopy(renewed)
        consumed["command_id"] = str(uuid4())
        consumed["idempotency_key"] = str(uuid4())
        consumed["payload"]["expected_issue_revision"] = saved.revision
        consumed["payload"]["completions"] = [deepcopy(work.completions[1])]
        _assert_plain_rejection(post(work.quality, consumed), "CONFIRMATION_REQUIRED")
        assert _counts(work) == after_save
    assert fixed_issue(work).id == saved.id
    assert _proof(work, original).consumed is False
    assert _proof(work, renewed).consumed is True
