"""No-connect actual UOW/query tests; missing live owners never become proof.

This is not a PG, actual independent professional or paired-owner acceptance.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from capa_effectiveness.test_candidate_write_prepare import origin_fixture
from capa_effectiveness.test_fact_sources_owner import native, project
from capa_effectiveness.test_participants_owner import work as work

from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import fact_commands as commands
from pdos_next.domain.capa_effectiveness import named_review_owner as owner
from pdos_next.domain.capa_effectiveness.facts import Participant
from pdos_next.domain.capa_effectiveness.paired_storage import StoragePairReader
from pdos_next.domain.verification_front.models import FormalVerificationCurrent
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.schemas.verification.contracts import SourceRef


def payload_for(saved, *, conclusion="unknown"):
    failure = saved.origin.issue.failures[0]
    source = commands.ExactSource.model_validate(saved.origin_sources[0].model_dump(mode="json"))
    mapping = {
        "failure_id": failure.identity,
        "run": {"id": str(uuid4()), "revision": 3, "kind": "verification_run", "key": None},
        "sample_id": str(failure.sample.id),
        "sample_revision": failure.sample.revision,
        "actual_configuration_id": str(failure.sample.actual_configuration.id),
        "actual_configuration_revision": failure.sample.actual_configuration.revision,
        "item_id": failure.coverage.item_id,
        "measurement_id": None,
        "projection_id": None,
        "applicability_sources": [],
    }
    return commands.NamedReviewPayload(
        issue_id=saved.origin.issue_id,
        expected_issue_revision=saved.origin.ref.revision,
        capa_id=saved.origin.issue.capa.id,
        visibility=saved.origin.visibility,
        sources=(source,),
        reason="Named pending review, no effectiveness",
        candidate={"id": uuid4(), "revision": 1, "sha256": "a" * 64},
        rule={"id": uuid4(), "revision": 1, "sha256": "b" * 64},
        observations=({"id": uuid4(), "revision": 1, "sha256": "c" * 64},),
        at={
            "occurred_at": datetime.now(UTC) - timedelta(seconds=1),
            "original_timezone": "UTC",
            "source": source.model_dump(mode="json"),
        },
        pair_applicability=(
            {
                "mapping": mapping,
                "method": None,
                "criterion": None,
                "conclusion": conclusion,
                "reason": "Actual purpose stays pending",
                "sources": (source,),
            },
        ),
        action_fulfillment=tuple(
            {
                "action_id": v.id,
                "conclusion": conclusion,
                "reason": "Needs independent actual action owner",
                "sources": (source,),
            }
            for v in saved.origin.issue.capa.actions
        ),
        conclusion=conclusion,
    )


def configured(*, paired_owner=None, applicability_owner=None):
    fact_owner = SimpleNamespace(
        _rule=lambda *_: None,
        _anchor=lambda *_: None,
        _authority=lambda *_: None,
        runtime_stamp=lambda _s: "actual configured scope stamp",
    )
    return owner.ActualNamedReviewOwner(
        fact_owner,
        candidate_semantic_owner=None,
        paired_owner=paired_owner,
        applicability_owner=applicability_owner,
    )


def test_exact_pair_and_action_coverage_is_not_relabelled():
    saved = origin_fixture()
    payload = payload_for(saved)
    candidate = SimpleNamespace(
        binding=SimpleNamespace(mappings=tuple(v.mapping for v in payload.pair_applicability))
    )
    owner._coverage(payload, candidate, saved)


@pytest.mark.parametrize(
    "change", ["wrong_mapping", "missing_action", "extra_action", "missing_failure"]
)
def test_review_cannot_cover_different_fixed_pair_or_action(change):
    saved = origin_fixture()
    payload = payload_for(saved)
    mapping = payload.pair_applicability[0].mapping
    candidate = SimpleNamespace(binding=SimpleNamespace(mappings=(mapping,)))
    if change == "wrong_mapping":
        candidate.binding.mappings = (
            mapping.model_copy(update={"item_id": "different actual item"}),
        )
    elif change == "missing_action":
        payload = payload.model_copy(update={"action_fulfillment": ()})
    elif change == "extra_action":
        payload = payload.model_copy(
            update={
                "action_fulfillment": (
                    *payload.action_fulfillment,
                    payload.action_fulfillment[0].model_copy(update={"action_id": uuid4()}),
                )
            }
        )
    else:
        candidate.binding.mappings = (mapping.model_copy(update={"failure_id": "not-original"}),)
        payload = payload.model_copy(
            update={
                "pair_applicability": (
                    payload.pair_applicability[0].model_copy(
                        update={"mapping": candidate.binding.mappings[0]}
                    ),
                )
            }
        )
    with pytest.raises(DomainError):
        owner._coverage(payload, candidate, saved)


@pytest.mark.parametrize(
    "role",
    [
        "original_test",
        "root_cause",
        "containment",
        "completion",
        "new_test",
        "measurement",
        "observation",
    ],
)
def test_current_reviewer_cannot_be_any_actual_participant_even_report_registrant(work, role):
    source = SourceRef(id=uuid4(), revision=1, kind="domain", position="action-receipt")
    actual = Participant(id=work.actor, roles=(role,), owner_sources=(source,))
    with pytest.raises(DomainError) as error:
        owner._independent(work.ctx, SimpleNamespace(participants=(actual,)))
    assert error.value.reason == "INDEPENDENT_REVIEWER_REQUIRED"


def test_peer_product_grant_does_not_itself_claim_independence(work):
    source = SourceRef(id=uuid4(), revision=1, kind="domain", position="action-receipt")
    other = Participant(id=uuid4(), roles=("completion",), owner_sources=(source,))
    assert owner._independent(work.ctx, SimpleNamespace(participants=(other,))) is None
    # This only checks the exact exclusion set; actual private access and
    # professional/current/source owners remain mandatory in read().


@pytest.mark.parametrize(
    "reader", [None, StoragePairReader(), SimpleNamespace(read=lambda *_a, **_k: True)]
)
def test_missing_or_raw_paired_reader_never_attests_real_run(work, reader):
    value = configured(paired_owner=reader)
    with pytest.raises(DomainError) as error:
        value._pair(work.s, work.ctx, work.pid, object())
    assert error.value.reason == "LIVE_PAIRED_OWNER_REQUIRED"
    assert not work.s.queries


def test_unknown_actions_stay_unknown_without_classification_or_fulfillment_owner(work):
    saved = origin_fixture()
    payload = payload_for(saved)
    candidate = SimpleNamespace(ref=payload.candidate)
    raw, pairs, actions = configured()._applicability(
        work.s,
        work.ctx,
        work.pid,
        saved,
        candidate,
        payload,
        (),
        (),
    )
    assert raw is None and pairs[0].conclusion == "unknown"
    assert actions[0].classification == "unknown" and actions[0].conclusion == "unknown"
    assert actions[0].owner_material["fulfillment"] is None
    assert actions[0].owner_material["classification"] is None


@pytest.mark.parametrize("conclusion", ["applicable", "not_applicable"])
def test_nonunknown_human_selection_still_needs_actual_applicability_owner(work, conclusion):
    saved = origin_fixture()
    payload = payload_for(saved, conclusion=conclusion)
    with pytest.raises(DomainError) as error:
        configured()._applicability(
            work.s,
            work.ctx,
            work.pid,
            saved,
            SimpleNamespace(ref=payload.candidate),
            payload,
            (),
            (),
        )
    assert error.value.reason == "FACT_APPLICABILITY_OWNER_REQUIRED"


def test_overall_applicable_cannot_hide_unknown_subconclusions(work):
    saved = origin_fixture()
    payload = payload_for(saved).model_copy(update={"conclusion": "applicable"})
    with pytest.raises(DomainError):
        configured()._applicability(
            work.s,
            work.ctx,
            work.pid,
            saved,
            SimpleNamespace(ref=payload.candidate),
            payload,
            (),
            (),
        )


def test_definition_quote_uses_server_whole_line_and_dto_sources_are_collected(work):
    project(work)
    _row, _receipt, ref, _read = native(work)
    exact = {"artifact_id": str(ref.id), "expected_revision": 1, "line": 1, "quote": "source"}
    selected = owner._checked_refs(work.s, work.ctx, work.pid, {"partial": exact, "dto": ref})
    assert selected == (ref, ref)
    assert selected[0].position != "line:1;quote_sha256:" + common.digest("source")


@pytest.mark.parametrize("changed", [None, "hash", "build", "scope", "request", "private"])
def test_actual_core_binding_uses_current_formal_and_new_build_not_run_origin(work, changed):
    new_build = uuid4()
    run_id, run_row_id, request_id, current_formal = (uuid4() for _ in range(4))
    old_run = origin_fixture().failures[0].result.verified.run
    run = old_run.model_copy(
        update={
            "id": run_id,
            "revision": 4,
            "request_id": request_id,
            "scope": work.scope,
            "build": old_run.build.model_copy(
                update={
                    "id": new_build,
                    "revision": 2,
                    "product_id": work.pid,
                    "project_id": work.scope.project_id,
                }
            ),
        }
    )
    snapshot = run.model_dump(mode="json")
    row = work.s.seed(
        VerificationRunVersion,
        id=run_row_id,
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        build_id=new_build,
        build_revision=2,
        run_id=run_id,
        request_id=request_id,
        revision=4,
        owner_id=work.actor,
        visibility="category",
        request_version_id=uuid4(),
        request_revision=2,
        run_snapshot=snapshot,
        snapshot_sha256=common.digest(snapshot),
        sources=[],
        required_source_read_set=[],
    )
    work.s.seed(
        FormalVerificationCurrent,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        request_id=request_id,
        request_version_id=current_formal,
        request_revision=7,
    )
    saved = SimpleNamespace(
        origin=SimpleNamespace(scope=work.scope, visibility="category", purpose="exact new purpose")
    )
    candidate = SimpleNamespace(
        binding=SimpleNamespace(
            mappings=(SimpleNamespace(run=SimpleNamespace(id=run_row_id, revision=4)),)
        )
    )
    if changed == "hash":
        row["snapshot_sha256"] = "0" * 64
    elif changed == "build":
        row["build_revision"] += 1
    elif changed == "private":
        row.update(visibility="private", owner_id=uuid4())
    elif changed in {"scope", "request"}:
        if changed == "scope":
            snapshot["scope"]["product_id"] = str(uuid4())
        else:
            snapshot["request_id"] = str(uuid4())
        row["snapshot_sha256"] = common.digest(snapshot)
    if changed:
        with pytest.raises(DomainError) as error:
            configured()._bindings(work.s, work.ctx, work.pid, saved, candidate)
        assert error.value.reason in {"FACT_REVIEW_PAIR_SCOPE_MISMATCH", "FORBIDDEN_SCOPE"}
        return
    (bound,) = configured()._bindings(work.s, work.ctx, work.pid, saved, candidate)
    assert bound.output_ref.id == current_formal and bound.output_ref.revision == 7
    assert bound.run_id == run_id and bound.build.id == new_build and bound.build.revision == 2
    assert bound.caller_id == work.actor


def test_real_uow_identity_and_runtime_epoch_are_not_dto_flags(work):
    value = configured()
    uow, caller, stamp = (
        owner.guards._uow(work.s),
        common.digest(vars(work.ctx)),
        value.runtime_stamp(work.s),
    )
    value._phase(work.s, work.ctx, uow, caller, stamp)
    value.paired_owner = object()
    with pytest.raises(DomainError) as error:
        value._phase(work.s, work.ctx, uow, caller, stamp)
    assert error.value.reason == "SOURCE_STALE"


def test_full_applicability_result_cannot_cross_session_or_rewrite_action(work):
    saved = origin_fixture()
    payload = payload_for(saved)
    candidate = SimpleNamespace(ref=payload.candidate)
    _raw, pairs, actions = configured()._applicability(
        work.s, work.ctx, work.pid, saved, candidate, payload, (), ()
    )
    actual = owner.ActualReviewApplicability(
        session=work.s,
        caller=work.ctx,
        product_id=work.pid,
        anchor_sha256=saved.anchor_sha256,
        candidate_ref=candidate.ref,
        conclusion="unknown",
        pairs=pairs,
        actions=actions,
        owner_material={"actual": "source owner material"},
        sources=payload.sources,
        reads=(),
        checked_at=datetime.now(UTC),
        valid_until=datetime.now(UTC) + timedelta(seconds=30),
    )
    value = configured()
    value._check_applicability(work.s, work.ctx, work.pid, saved, candidate, payload, actual)
    wrong = replace(actual, session=object())
    with pytest.raises(DomainError):
        value._check_applicability(work.s, work.ctx, work.pid, saved, candidate, payload, wrong)


@pytest.mark.parametrize("changed", [None, "id", "revision", "kind", "position"])
def test_typed_source_subclass_equivalence_keeps_every_exact_field(work, changed):
    saved = origin_fixture()
    payload = payload_for(saved)
    # ExactSource is a strict input subclass of the persisted SourceRef DTO.
    # Equal typed references must compare by all fields, not Python subclass.
    exact = payload.sources[0]
    method = SourceRef.model_validate(exact.model_dump(mode="json"))
    pair = payload.pair_applicability[0].model_copy(update={"method": exact, "criterion": exact})
    payload = payload.model_copy(update={"pair_applicability": (pair,)})
    value = configured()
    _, pairs, actions = value._applicability(
        work.s, work.ctx, work.pid, saved, SimpleNamespace(ref=payload.candidate), payload, (), ()
    )
    delta = {"id": uuid4(), "revision": method.revision + 1, "kind": "domain", "position": "other"}
    actual_method = (
        method if changed is None else method.model_copy(update={changed: delta[changed]})
    )
    pairs = (pairs[0].model_copy(update={"method": actual_method}),)
    actual = owner.ActualReviewApplicability(
        session=work.s,
        caller=work.ctx,
        product_id=work.pid,
        anchor_sha256=saved.anchor_sha256,
        candidate_ref=payload.candidate,
        conclusion="unknown",
        pairs=pairs,
        actions=actions,
        owner_material={},
        sources=payload.sources,
        reads=(),
        checked_at=datetime.now(UTC),
        valid_until=datetime.now(UTC) + timedelta(seconds=30),
    )
    if changed is None:
        value._check_applicability(
            work.s,
            work.ctx,
            work.pid,
            saved,
            SimpleNamespace(ref=payload.candidate),
            payload,
            actual,
        )
    else:
        with pytest.raises(DomainError) as error:
            value._check_applicability(
                work.s,
                work.ctx,
                work.pid,
                saved,
                SimpleNamespace(ref=payload.candidate),
                payload,
                actual,
            )
        assert error.value.reason == "FACT_APPLICABILITY_MISMATCH"


def test_actual_mapping_cannot_replace_fixed_current_sample_or_measurement():
    saved = origin_fixture()
    payload = payload_for(saved)
    mapping = payload.pair_applicability[0].mapping
    original_run = saved.failures[0].result.verified.run
    run_row = SimpleNamespace(
        ref=SimpleNamespace(id=mapping.run.id, revision=mapping.run.revision), snapshot=original_run
    )
    request_row = SimpleNamespace(snapshot=SimpleNamespace(items=(original_run.items[0],)))
    material = SimpleNamespace(run_after=run_row, request_after=request_row, projection=None)
    pair = SimpleNamespace(material=material)
    candidate = SimpleNamespace(binding=SimpleNamespace(mappings=(mapping,)))
    configured()._mapping_pairs(candidate, ((pair, None),))
    candidate.binding.mappings = (
        mapping.model_copy(update={"sample_revision": mapping.sample_revision + 1}),
    )
    with pytest.raises(DomainError):
        configured()._mapping_pairs(candidate, ((pair, None),))


@pytest.mark.parametrize("participant_is_caller", [True, False])
def test_read_checks_actual_caller_exclusion_before_missing_live_pair(
    work, monkeypatch, participant_is_caller
):
    """Explicit owner substitutes stop before any positive/live paired claim."""
    saved = origin_fixture()
    payload = payload_for(saved)
    ctx = common.Context(saved.origin.scope.tenant_id, work.actor, work.actor)
    pid = saved.origin.scope.product_id
    for table in (Product, Principal, Grant):
        for row in work.s.rows[table.__tablename__]:
            row["tenant_id"] = ctx.tenant_id
            if "product_id" in row:
                row["product_id"] = pid
            if table is Product:
                row["id"] = pid
    value = configured()
    rule = SimpleNamespace(ref=payload.rule)
    value.fact_owner._rule = lambda *_: (rule, saved)
    value.fact_owner._anchor = lambda *_: saved.origin.ref
    candidate = SimpleNamespace(
        body=SimpleNamespace(stable_anchor=saved),
        origin=SimpleNamespace(current=SimpleNamespace(ref=saved.origin.ref)),
        binding=SimpleNamespace(mappings=tuple(v.mapping for v in payload.pair_applicability)),
    )
    value._candidate = lambda *_: candidate
    value._bindings = lambda *_: (object(),)
    observation = SimpleNamespace(
        registry=SimpleNamespace(state="current_registered"),
        fact=SimpleNamespace(
            rule=rule.ref,
            anchor_sha256=saved.anchor_sha256,
            scope=saved.origin.scope,
            purpose=saved.origin.purpose,
            capa_id=saved.origin.issue.capa.id,
        ),
    )
    monkeypatch.setattr(owner, "read_stored_fact", lambda *_: observation)
    original_registrant = Participant(
        id=ctx.actor_id if participant_is_caller else uuid4(),
        roles=("measurement",),
        owner_sources=(saved.origin_sources[0],),
    )
    monkeypatch.setattr(
        owner,
        "read_participants",
        lambda *_a, **_kw: SimpleNamespace(participants=(original_registrant,)),
    )
    with pytest.raises(DomainError) as error:
        value.read(work.s, ctx, pid, payload)
    assert error.value.reason == (
        "INDEPENDENT_REVIEWER_REQUIRED" if participant_is_caller else "LIVE_PAIRED_OWNER_REQUIRED"
    )
    assert not work.s.new and not work.s.dirty
