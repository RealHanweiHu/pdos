"""Actual storage functions, explicit no-DB source/result returns; no real gates.

Configured callbacks below are synthetic test substitutes. Their successful
execution is not actual original bytes, qualification, SQL guards or a HostGate.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import anchor_owner as owner
import pytest
import test_anchor_lineage as samples
import test_anchor_storage as stored
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


@pytest.fixture
def origin_work(monkeypatch):
    yield from stored.work.__wrapped__(monkeypatch)


@pytest.fixture
def actual(origin_work, monkeypatch):
    work = origin_work
    result = samples.origin_fixture().failures[0].result.model_copy(deep=True)
    log = []
    state = SimpleNamespace(reads=0, mutate_bridge=None, mutate_refresh=None, mutate_basis=None)

    def bridge(s, ctx, pid, **binding):
        assert s is work.s and ctx is work.ctx and pid == work.pid
        assert s.autoflush is False and binding["write"] is False
        assert binding["event_id"] is None
        log.append(("bridge", binding.copy()))
        value = result.model_copy(deep=True)
        value.source_basis["runtime_stamp"] = owner._runtime_stamp(s)
        if state.mutate_bridge:
            value = state.mutate_bridge(value)
        return value

    def refresh(s, ctx, pid, value, *, write):
        assert s is work.s and ctx is work.ctx and pid == work.pid
        assert s.autoflush is False and write is False
        log.append(("refresh", value.measurement_id))
        fresh = value.model_copy(deep=True)
        if state.mutate_refresh:
            fresh = state.mutate_refresh(fresh)
        return fresh

    def source(s, ctx, pid, ref):
        assert s is work.s and ctx is work.ctx and pid == work.pid
        log.append(("source", ref))
        return [{"artifact_id": str(ref.id), "expected_revision": ref.revision}], [], False

    def basis(s, ctx, pid, reads):
        assert s is work.s and ctx is work.ctx and pid == work.pid
        state.reads += 1
        log.append(("basis", state.reads))
        values = deepcopy(work.row.source_basis["artifact_sources"])
        values = [{k: v for k, v in entry.items() if v is not None} for entry in values]
        if state.mutate_basis:
            values = state.mutate_basis(values, state.reads)
        return values, any(v["visibility"] == "private" for v in values)

    work.s.get_bind()._pdos_quality_result_bridge = bridge
    work.s.get_bind()._pdos_quality_result_refresh = refresh
    monkeypatch.setattr(owner.evidence, "check_source", source)
    monkeypatch.setattr(owner.evidence, "source_basis", basis)
    return SimpleNamespace(work=work, state=state, result=result, log=log, monkeypatch=monkeypatch)


def read(actual, **changes):
    work = actual.work
    return owner.read_anchor_from_actual_owner(
        work.s,
        changes.get("ctx", work.ctx),
        changes.get("pid", work.pid),
        changes.get("issue_id", work.logical),
        changes.get("ref", work.ref),
    )


def failure(actual, code=None):
    with pytest.raises(DomainError) as error:
        read(actual)
    if code is not None:
        assert error.value.code == code
    return error.value


def test_configured_storage_sources_and_failure_calls_keep_complete_original(actual):
    out = read(actual)
    work = actual.work
    assert out.anchor.origin.issue.model_dump(mode="json") == work.row.issue_snapshot
    assert out.anchor.origin.persisted_source_basis == work.row.source_basis
    assert out.origin_descriptor.origin == out.anchor.origin
    assert out.origin_descriptor.source_bytes_verified is False  # raw reader remains honest
    assert out.original_failure_bytes_verified is True
    assert out.current_source_security_checked is True
    assert out.current_evidence_authorized is False
    assert out.same_uow_consumption_attested is False
    assert out.origin_descriptor.completion_group.same_uow_consumption_attested is False
    assert out.missing_owners == ("current_professional_policy_owner",)
    binding = next(v for k, v in actual.log if k == "bridge")
    fixed = out.anchor.origin.issue.failures[0]
    assert binding == dict(
        run_id=fixed.run.id,
        run_revision=fixed.run.revision,
        measurement_id=fixed.measurement_id,
        event_id=None,
        write=False,
    )
    manual = {v for k, v in actual.log if k == "source"}
    assert manual == set(owner.a.issue_sources(out.anchor.origin.issue))
    # In this fixture named root/completion refs are ALSO in the bridge sources.
    assert manual <= set(out.anchor.failures[0].result.sources)
    assert actual.state.reads == 3
    assert actual.log.index(("basis", 1)) < actual.log.index(("refresh", fixed.measurement_id))
    assert out.anchor.origin_required_source_read_set == out.anchor.origin.required_source_read_set


@pytest.mark.parametrize(
    "attribute", ["_pdos_quality_result_bridge", "_pdos_quality_result_refresh"]
)
def test_missing_actual_callback_is_503_without_any_positive_anchor(actual, attribute):
    setattr(actual.work.s.get_bind(), attribute, None)
    assert failure(actual, "INTEGRATION_REQUIRED").status == 503
    assert actual.log == []


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.model_copy(update={"purpose": "different purpose"}),
        lambda value: value.model_copy(update={"run_revision": value.run_revision + 1}),
        lambda value: value.model_copy(update={"measurement_id": samples.uid("other")}),
        lambda value: value.model_copy(update={"event_id": samples.uid("unselected event")}),
        lambda value: value.model_copy(update={"current": False}),
        lambda value: value.model_copy(update={"reasons": ("SOURCE_STALE",)}),
        lambda value: value.model_copy(
            update={"scope": value.scope.model_copy(update={"project_id": samples.uid("other")})}
        ),
        lambda value: value.model_copy(
            update={"verified": value.verified.model_copy(update={"nature": "real"})}
        ),
        lambda value: value.model_copy(
            update={"visibility": "private", "owner_id": samples.uid("someone else")}
        ),
        lambda value: value.model_copy(
            update={
                "verified": value.verified.model_copy(
                    update={
                        "run": value.verified.run.model_copy(
                            update={"id": samples.uid("later run")}
                        )
                    }
                )
            }
        ),
    ],
)
def test_actual_bridge_cannot_substitute_scope_clock_nature_or_later_current(actual, change):
    actual.state.mutate_bridge = change
    failure(actual)


@pytest.mark.parametrize("path", ["occupancy", "reservation", "sample_usage", "source_basis"])
def test_all_effects_and_security_remain_in_stable_failure_material(actual, path):
    def mutate(value):
        if path in {"occupancy", "sample_usage"}:
            value.retained[path][0]["epoch"] += 1
        else:
            value.retained[path]["epoch"] += 1
        return value

    actual.state.mutate_refresh = mutate
    failure(actual, "SOURCE_STALE")


@pytest.mark.parametrize("field", ["basis_sha256", "rules_sha256", "projection_id", "owner_id"])
def test_actual_refresh_cannot_replace_original_result_or_projection(actual, field):
    value = digest("changed") if "sha256" in field else samples.uid("changed")
    actual.state.mutate_refresh = lambda fresh: fresh.model_copy(update={field: value})
    failure(actual, "SOURCE_STALE")


def test_only_exact_observation_paths_can_change_and_original_full_values_survive(actual):
    def refresh(value):
        value.retained["checked_at"] = "a later observation"
        value.retained["execution_window_elapsed"] = True
        # runtime_stamp is independently required to equal real current runtime;
        # the original frozen stable helper exclusion is not a config bypass.
        return value

    actual.state.mutate_refresh = refresh
    out = read(actual)
    assert (
        out.anchor.failures[0].result.retained["checked_at"] == actual.result.retained["checked_at"]
    )
    assert out.anchor.failures[0].result.retained["execution_window_elapsed"] is False


def test_same_named_field_nested_inside_plan_is_not_an_observation_exception(actual):
    def refresh(value):
        value.retained["plan_binding"]["checked_at"] = "changed fixed nested material"
        return value

    actual.state.mutate_refresh = refresh
    failure(actual, "SOURCE_STALE")


@pytest.mark.parametrize(
    "attribute", ["_pdos_quality_result_bridge", "_pdos_quality_result_refresh"]
)
def test_callback_replacement_during_owner_io_is_rejected(actual, attribute):
    def mutate(value):
        setattr(actual.work.s.get_bind(), attribute, lambda *args, **kwargs: value)
        return value

    actual.state.mutate_bridge = mutate
    failure(actual, "SOURCE_STALE")


@pytest.mark.parametrize("namespace", ["professional", "test_resource", "operational"])
def test_issuer_revoke_restore_epoch_during_io_is_not_a_positive_boolean(actual, namespace):
    engine = actual.work.s.get_bind()
    setattr(engine, f"_pdos_{namespace}_issuer_epochs", {"issuer": 1})

    def mutate(value):
        # Final enabled state can be unchanged while the monotonic epoch moves.
        getattr(engine, f"_pdos_{namespace}_issuer_epochs")["issuer"] = 3
        return value

    actual.state.mutate_refresh = mutate
    failure(actual, "SOURCE_STALE")


def test_source_runtime_or_security_identity_changed_by_last_io_is_rejected(actual):
    def mutate(values, count):
        if count == 2:
            actual.work.s.get_bind()._pdos_security_runtime = object()
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "SOURCE_STALE")


@pytest.mark.parametrize("change", ["hash", "original_epoch", "native_registration", "status"])
def test_source_safety_epoch_and_complete_registered_provenance_are_not_ignored(actual, change):
    def mutate(values, count):
        if count == 2:
            entry = values[0]
            if change == "hash":
                entry["hash"] = digest("different bytes")
            elif change == "status":
                entry["status"] = "withdrawn"
            elif change == "native_registration":
                entry["registration"]["receipt_id"] = str(samples.uid("other receipt"))
            else:
                entry.pop("registration")
                entry["source_kind"] = "uploaded_original"
                entry["original"] = {
                    "id": str(samples.uid("original")),
                    "epoch": 3,
                    "source_state": "active",
                    "disposition": "active",
                }
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "SOURCE_STALE")


def test_raw_sparse_basis_is_not_resealed_with_added_typed_null_keys(actual):
    def mutate(values, count):
        if count == 2:
            values[0]["original"] = None
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "SOURCE_STALE")


def test_original_declared_security_must_match_real_current_source_basis(actual):
    def mutate(values, count):
        values[0]["hash"] = digest("changed before read")
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "SOURCE_STALE")


def test_full_union_never_truncates_twenty_artifact_limit(actual):
    reads = tuple(
        owner.a.SourceRead(artifact_id=samples.uid(f"extra-{n}"), expected_revision=1)
        for n in range(21)
    )
    actual.state.mutate_bridge = lambda value: value.model_copy(
        update={"required_source_read_set": (*value.required_source_read_set, *reads[:20])}
    )
    failure(actual)


def test_manual_ref_must_be_in_complete_original_reads_and_is_not_a_generic_uuid(actual):
    def check(s, ctx, pid, ref):
        return [{"artifact_id": str(samples.uid("undeclared")), "expected_revision": 1}], [], False

    actual.monkeypatch.setattr(owner.evidence, "check_source", check)
    failure(actual, "MISSING_REQUIRED_EVIDENCE")


def test_current_successor_keeps_original_history_and_explicit_lineage_missing(actual):
    stored.successor(actual.work)
    out = read(actual)
    assert out.needs_lineage_owner is True
    assert out.origin_descriptor.current.ref != out.anchor.origin.ref
    assert "limited_issue_lineage_owner" in out.missing_owners
    assert out.anchor.origin.ref == actual.work.ref
    assert out.anchor.origin.issue.model_dump(mode="json") == actual.work.row.issue_snapshot
    assert out.current_evidence_authorized is False


def test_current_epoch_change_during_failure_bytes_is_rejected(actual):
    def mutate(value):
        actual.work.pointer.epoch += 2
        return value

    actual.state.mutate_bridge = mutate
    failure(actual, "SOURCE_STALE")


@pytest.mark.parametrize("which", ["scope", "owner_id", "visibility"])
def test_project_actual_scope_and_private_gate_rechecked_after_owner_io(actual, which):
    def mutate(value):
        setattr(
            actual.work.project,
            which,
            {
                "scope": "changed actual project scope",
                "owner_id": samples.uid("different project owner"),
                "visibility": "private",
            }[which],
        )
        return value

    actual.state.mutate_refresh = mutate
    failure(actual)


def test_fresh_caller_clock_after_last_owner_io_rejects_read_expiry(actual):
    def mutate(values, count):
        if count == 2:
            actual.work.clock.at = actual.work.grant.expires_at + timedelta(microseconds=1)
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "FORBIDDEN_SCOPE")


@pytest.mark.parametrize("change", ["rollback", "close", "nested", "caller"])
def test_owner_cannot_switch_actual_uow_or_current_person(actual, change):
    def mutate(value):
        work = actual.work
        if change == "rollback":
            work.s.rollback()
        elif change == "close":
            work.s.close()
        elif change == "nested":
            work.s.begin_nested()
        else:
            object.__setattr__(work.ctx, "actor_id", samples.uid("different actor"))
        return value

    actual.state.mutate_bridge = mutate
    failure(actual)


def test_unrelated_original_writer_inactive_is_not_a_current_reader_grant(actual):
    out = read(actual)
    assert out.anchor.origin.writer_id != actual.work.ctx.actor_id
    actual.work.principal.active = False
    failure(actual, "FORBIDDEN_SCOPE")


def add_second_original_failure(actual):
    work = actual.work
    second = actual.result.model_copy(deep=True)
    second_run = second.verified.run.model_copy(update={"id": samples.uid("second-logical-run")})
    second = second.model_copy(
        update={
            "verified": second.verified.model_copy(update={"run": second_run}),
            "run_version_id": samples.uid("second-run-v4"),
            "projection_id": samples.uid("second-projection"),
        }
    )
    fixed = failure_ref(second.verified, second.measurement_id)
    for row in (work.row, work.before):
        snapshot = deepcopy(row.issue_snapshot)
        snapshot["failures"].append(fixed.model_dump(mode="json"))
        snapshot["capa"]["requirement"]["required_failure_ids"].append(fixed.identity)
        row.issue_snapshot = stored.storage.Issue.model_validate(snapshot).model_dump(mode="json")
        row.snapshot_sha256 = digest(row.issue_snapshot)
    work.ref = owner.a.VersionRef(
        id=work.row.id, revision=work.row.revision, snapshot_sha256=work.row.snapshot_sha256
    )
    work.proof.snapshot["before"][str(work.logical)] = deepcopy(work.before.issue_snapshot)
    work.proof.snapshot["after"][str(work.logical)] = stored.storage.followup._preview_issue(
        stored.storage.Issue.model_validate(work.row.issue_snapshot),
        stored.storage.Issue.model_validate(work.before.issue_snapshot),
    )
    return second


def test_every_failure_refresh_waits_until_all_original_bytes_complete(actual):
    second = add_second_original_failure(actual)
    original_bridge = actual.work.s.get_bind()._pdos_quality_result_bridge

    def bridge(s, ctx, pid, **binding):
        if binding["run_id"] == second.verified.run.id:
            actual.log.append(("second bytes", binding["run_id"]))
            value = second.model_copy(deep=True)
            value.source_basis["runtime_stamp"] = owner._runtime_stamp(s)
            return value
        return original_bridge(s, ctx, pid, **binding)

    actual.work.s.get_bind()._pdos_quality_result_bridge = bridge
    out = read(actual)
    assert len(out.anchor.failures) == 2
    second_at = actual.log.index(("second bytes", second.verified.run.id))
    assert all(index > second_at for index, (kind, _) in enumerate(actual.log) if kind == "refresh")


def test_later_failure_refresh_revocation_cannot_leave_earlier_failure_positive(actual):
    second = add_second_original_failure(actual)
    engine = actual.work.s.get_bind()
    original = engine._pdos_quality_result_bridge

    def bridge(s, ctx, pid, **binding):
        if binding["run_id"] != second.verified.run.id:
            return original(s, ctx, pid, **binding)
        value = second.model_copy(deep=True)
        value.source_basis["runtime_stamp"] = owner._runtime_stamp(s)
        return value

    engine._pdos_quality_result_bridge = bridge
    seen = []

    def refresh(value):
        seen.append(value.verified.run.id)
        if len(seen) == 2:
            engine._pdos_professional_issuer_epochs = {"original-issuer": 3}
        return value

    actual.state.mutate_refresh = refresh
    failure(actual, "SOURCE_STALE")
    assert len(seen) == 2


def test_new_layer_never_calls_writer_or_professional_or_builds_an_owner_context(actual):
    work = actual.work
    for name in ("flush", "commit", "add", "execute", "connection"):
        actual.monkeypatch.setattr(
            work.s, name, lambda *a, **k: pytest.fail("No writer/connection")
        )
    result = read(actual)
    assert result.checked_at == work.clock.at
    assert work.ctx == Context(work.row.tenant_id, work.principal.id, work.principal.id)
    assert result.current_evidence_authorized is False


def test_anchor_pure_construction_precedes_final_actual_caller_clock(actual):
    original = owner.a.build_anchor

    def build(*args, **kwargs):
        out = original(*args, **kwargs)
        actual.work.clock.at = actual.work.grant.expires_at + timedelta(microseconds=1)
        return out

    actual.monkeypatch.setattr(owner.a, "build_anchor", build)
    failure(actual, "FORBIDDEN_SCOPE")


def test_source_changes_after_final_descriptor_are_independently_rechecked(actual):
    def mutate(values, count):
        if count == 3:
            values[0]["hash"] = digest("withdrawn after last descriptor IO")
        return values

    actual.state.mutate_basis = mutate
    failure(actual, "SOURCE_STALE")


def test_actual_last_grant_query_expiry_is_rejected_with_post_query_clock(actual):
    original = actual.work.memory.scalars

    def scalars(statement, *args, **kwargs):
        returned = original(statement, *args, **kwargs)
        if actual.state.reads == 3 and statement.column_descriptions[0]["entity"] is owner.Grant:
            actual.work.clock.at = actual.work.grant.expires_at + timedelta(microseconds=1)
        return returned

    actual.monkeypatch.setattr(actual.work.s, "scalars", scalars)
    failure(actual, "FORBIDDEN_SCOPE")
