"""One root-run real HTTP/PG publication continuation on a fresh synthetic scope.

Only one deliberate terminal DomainError is injected. The public commands,
material/source readers, professional facts, current time, shared consumption,
RLS and PostgreSQL atom guards execute unchanged.
"""

# ruff: noqa: F811 -- the imported actual fixture is injected by pytest

from copy import deepcopy
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.domain.manufacturing_baseline import publication_service
from pdos_next.domain.manufacturing_baseline.publication_schemas import OPERATION
from pdos_next.errors import DomainError
from pdos_next.models import RequestKey

from . import publication_pg_helpers as helper
from .publication_pg_helpers import publication_case  # noqa: F401 -- explicit actual fixture


def test_actual_named_publication_history_peer_replay_rollback_and_source_withdrawal(
    publication_case, monkeypatch, record_property
):
    work, setup = publication_case, publication_case.setup
    record_property(
        "fixture_nature", "synthetic originals and controlled synthetic professional facts"
    )
    record_property("qualification", "unknown; no Pilot or manufacturing release")
    record_property("project_id", str(work.project_id))

    helper.import_authority(work, setup.human)
    baseline = helper.save_drafts(work)
    original_drafts = helper.snapshots(work, helper.DRAFT_MODELS)
    assert all(view["status"] == "draft" for view in work.documents.values())
    assert all(view["qualification"] == "unknown" for view in work.documents.values())
    assert all(view["manufacturing_release"] is None for view in work.documents.values())

    # A category grant and readable shared originals confer no manufacturing
    # signing qualification. No public inputs/preview is forged for this peer.
    first_payload = helper.publication_payload(work)
    before_unqualified = helper.snapshots(work)
    refused = helper.input_response(work, first_payload, setup.peer)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "QUALIFICATION_REQUIRED"
    assert helper.snapshots(work) == before_unqualified

    before_inputs = helper.snapshots(work)
    first_command, first_review = helper.prepare_publication(work, first_payload)
    assert first_review["before"] is None and first_review["after"]["revision"] == 1
    assert first_review["after"]["id"] is first_review["after"]["created_at"] is None
    assert first_review["after"]["status"] == "published"
    assert first_review["authority"]["qualified"] is True
    assert first_review["after"]["body"]["qualification"] == "unknown"
    # Preview creates exactly its unconsumed common Confirmation, no publication.
    after_preview = helper.snapshots(work)
    for name, before in before_inputs.items():
        if name != "confirmations":
            assert after_preview[name] == before
    assert after_preview["confirmations"]["count"] == before_inputs["confirmations"]["count"] + 1
    first_proof = helper.proof(work, first_command)
    assert first_proof[1:] == (False, None)
    response = helper.post(setup, first_command)
    assert response.status_code == 200, response.text
    first_receipt = response.json()
    helper.assert_published_atom(work, first_command, first_receipt)
    assert helper.proof(work, first_command) == (first_proof[0], True, None)
    first = helper.publication(work, first_receipt)
    assert first["baseline"]["id"] == baseline["id"] and first["baseline"]["revision"] == 1
    assert first["is_current"] is True and first["source_status"] == "current"
    assert first["body"] == first_review["after"]["body"]
    assert first["qualification"] == "unknown" and first["manufacturing_release"] is None
    assert helper.snapshots(work, helper.DRAFT_MODELS) == original_drafts
    initial_history = helper.publications(work)
    assert [row["id"] for row in initial_history["versions"]] == [first["id"]]
    assert initial_history["history_page"]["next_cursor"] is None

    # Both paths return the actual original receipt. The alias adds only its
    # ordinary RequestKey; neither path creates another decision or publication.
    saved_state = helper.snapshots(work)
    repeated = helper.post(setup, deepcopy(first_command))
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == first_receipt
    assert helper.snapshots(work) == saved_state
    alias = {**deepcopy(first_command), "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    repeated_alias = helper.post(setup, alias)
    assert repeated_alias.status_code == 200, repeated_alias.text
    assert repeated_alias.json() == first_receipt
    alias_state = helper.snapshots(work)
    for name, before in saved_state.items():
        if name == "request_keys":
            assert alias_state[name]["count"] == before["count"] + 1
        else:
            assert alias_state[name] == before
    assert helper.proof(work, first_command) == (first_proof[0], True, None)

    # The second named publication appends one version. It neither rewrites the
    # previous publication nor changes the independent draft source ledger.
    second_payload = helper.publication_payload(work, previous=first, revision=2)
    second_command, second_review = helper.prepare_publication(work, second_payload)
    assert second_review["before"]["id"] == first["id"]
    assert second_review["after"]["revision"] == 2
    response = helper.post(setup, second_command)
    assert response.status_code == 200, response.text
    second_receipt = response.json()
    helper.assert_published_atom(work, second_command, second_receipt)
    second = helper.publication(work, second_receipt)
    assert second["previous_id"] == first["id"] and second["previous_revision"] == 1
    assert second["series_id"] == first["series_id"] and second["is_current"] is True
    old = helper.publication(work, first_receipt)
    assert old["body"] == first["body"] and old["is_current"] is False
    history = helper.publications(work)
    assert {row["id"] for row in history["versions"]} == {first["id"], second["id"]}
    assert {row["id"] for row in history["versions"] if row["is_current"]} == {second["id"]}
    assert helper.snapshots(work, helper.DRAFT_MODELS) == original_drafts
    with helper.session(work) as s:
        pointer = s.scalar(
            select(helper.Current).where(helper.Current.series_id == UUID(first["series_id"]))
        )
        assert pointer.epoch == 2

    # The independent reader now receives actual controlled personnel facts.
    # Its existing own-actor RequestKey RLS still hides the original key rows.
    helper.import_authority(work, setup.peer)
    before_peer_read = helper.snapshots(work)
    with helper.session(work, setup.peer) as s:
        keys = list(
            s.scalars(select(RequestKey).where(RequestKey.receipt_id == UUID(second_receipt["id"])))
        )
        assert keys == []
    peer_view = helper.publication(work, second_receipt, setup.peer)
    peer_history = helper.publications(work, setup.peer)
    assert peer_view == second
    assert {row["id"] for row in peer_history["versions"]} == {first["id"], second["id"]}
    for command in (first_command, second_command):
        assert command["idempotency_key"] not in str(peer_view)
        assert command["payload"]["approval_token"] not in str(peer_view)
    assert helper.snapshots(work) == before_peer_read

    # Inject exactly one failure after the real common tail, including its
    # actual source/professional/current/live-consumption finalization, has run.
    failed_payload = helper.publication_payload(work, previous=second, revision=3)
    failed_payload["reason"] += "; deliberate terminal rollback verification"
    failed_command, _ = helper.prepare_publication(work, failed_payload)
    failure_proof = helper.proof(work, failed_command)
    assert failure_proof[1:] == (False, None)
    before_failure = helper.snapshots(work, helper.ROLLBACK_MODELS)
    real_finalize = publication_service.finalize_receipt
    attempted_rows = []

    def fail_final_tail(s, ctx, command, product, payload, subject, receipt):
        assert command.operation == OPERATION and command.command_id == UUID(
            failed_command["command_id"]
        )
        real_finalize(s, ctx, command, product, payload, subject, receipt)
        assert s.get(helper.Publication, subject.id) is subject
        assert receipt.id == subject.receipt_id
        attempted_rows.append(subject.id)
        raise DomainError("INTERNAL_ERROR", "Synthetic named publication terminal rollback")

    with monkeypatch.context() as fault:
        fault.setattr(publication_service, "finalize_receipt", fail_final_tail)
        failed = helper.post(setup, failed_command)
    assert failed.status_code == 500, failed.text
    assert failed.json()["code"] == "INTERNAL_ERROR" and len(attempted_rows) == 1
    assert helper.snapshots(work, helper.ROLLBACK_MODELS) == before_failure
    assert helper.proof(work, failed_command) == failure_proof
    assert helper.snapshots(work, helper.DRAFT_MODELS) == original_drafts
    with helper.session(work) as s:
        assert s.get(helper.Publication, attempted_rows[0]) is None
    assert helper.publication(work, second_receipt) == second

    # Withdraw the exact uploaded source through its actual public T1 command,
    # last. Fixed records and bytes remain; current-source status becomes pending
    # recheck and no fresh publication is accepted from that withdrawn material.
    helper.withdraw_original(work)
    remaining = helper.publications(work)
    assert len(remaining["versions"]) == 2
    assert all(row["source_status"] == "needs_recheck" for row in remaining["versions"])
    assert all(
        row["qualification"] == "unknown" and row["manufacturing_release"] is None
        for row in remaining["versions"]
    )
    assert helper.publication(work, first_receipt)["body"] == first["body"]
    assert helper.publication(work, second_receipt)["body"] == second["body"]
    after_withdrawal = helper.snapshots(work)
    fresh = helper.input_response(work, failed_payload)
    assert fresh.status_code in (403, 409), fresh.text
    assert fresh.json()["code"] in {"SOURCE_STALE", "SOURCE_UNAVAILABLE", "RECHECK_REQUIRED"}
    assert helper.snapshots(work) == after_withdrawal
    replay = helper.post(setup, first_command)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first_receipt and helper.snapshots(work) == after_withdrawal
    record_property("publication_ids", f"{first['id']},{second['id']}")
    record_property("terminal_rollback_attempt", str(attempted_rows[0]))
