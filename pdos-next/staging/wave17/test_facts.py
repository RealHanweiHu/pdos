"""Synthetic, in-memory structural/host-protocol checks; no DB or qualification."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import facts as f
import pytest
from anchor import IssueVersionEvidence, OriginalFailureProof, build_anchor, json_value
from paired import verify_paired_material
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import event
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import Session as SQLAlchemySession
from test_anchor_lineage import origin_fixture, safety
from test_paired import AT, NOW, saved, uid

OPS = f.FactOperations(
    rule_import="synthetic.host.rule.import",
    rule_tier="host_import",
    rule_event="synthetic.rule_imported",
    rule_subject_type="synthetic_rule",
    observation="synthetic.observation.record",
    observation_tier="T1",
    observation_event="synthetic.observation_recorded",
    observation_subject_type="synthetic_observation",
    review="synthetic.verification.review",
    review_tier="T2",
    review_event="synthetic.verification_reviewed",
    review_subject_type="synthetic_review",
)


def substitute(value, replacements):
    if isinstance(value, dict):
        return {k: substitute(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, replacements) for v in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def fixture_anchor(binding, pair):
    """Re-scope pure synthetic original data, never edit any saved real object."""
    original = origin_fixture()
    checked = verify_paired_material(binding, pair, at=AT)
    replacements = {
        str(getattr(original.origin.scope, k)): str(getattr(binding.scope, k))
        for k in ("tenant_id", "product_id", "project_id")
    }
    replacements[f"product:{original.origin.scope.product_id}"] = (
        f"product:{binding.scope.product_id}"
    )
    replacements[original.origin.purpose] = binding.purpose
    # Reuse actual source identities across the synthetic material to remain
    # below the production MAX20 closure, rather than widening/truncating it.
    for a, b in zip(
        original.origin_source_basis, checked.proof.required_source_read_set, strict=False
    ):
        replacements[str(a.id)] = str(b.artifact_id)
    failures = []
    for p in original.failures:
        result = type(p.result).model_validate(substitute(json_value(p.result), replacements))
        failures.append(
            OriginalFailureProof(
                failure=failure_ref(result.verified, result.measurement_id),
                result=result,
            )
        )
    raw = substitute(json_value(original.origin), replacements)
    raw["issue"]["failures"] = [json_value(p.failure) for p in failures]
    raw["issue"]["capa"]["requirement"]["required_failure_ids"] = sorted(
        p.failure.identity for p in failures
    )
    raw["ref"]["snapshot_sha256"] = f.digest(raw["issue"])
    row = IssueVersionEvidence.model_validate(raw)
    return build_anchor(row, failures, source_basis=row.source_basis)


def seal(klass, values, actor):
    raw = TypeAdapter(dict).dump_python(values, mode="json")
    stem = raw["kind"]
    name = OPS.rule_import if stem == "rule" else getattr(OPS, stem)
    tier = "host_import" if stem == "rule" else "T1" if stem == "observation" else "T2"
    row = {"id": raw["ref"]["id"], "revision": raw["ref"]["revision"]}
    proof = uid(f"{stem}-proof") if tier != "host_import" else None
    raw["provenance"] = json_value(
        f.FactAtom(
            scope=raw["scope"],
            operation=name,
            tier=tier,
            fact=row,
            actor_id=actor,
            requester_id=actor,
            actor_kind="human",
            command_id=uid(stem + "-command"),
            receipt_id=uid(stem + "-receipt"),
            receipt_subject=row,
            receipt_subject_type=getattr(OPS, stem + "_subject_type"),
            receipt_operation=name,
            receipt_actor_id=actor,
            payload_sha256=f.fact_payload_sha256(raw),
            read_set_sha256=f.digest(
                [json_value(r) for r in f.canonical_reads(raw["required_source_read_set"])]
            ),
            proof_id=proof,
            invocation_decision_id=proof if tier == "T2" else None,
            token_sha256=f.digest(stem + "-secret-not-stored") if proof else None,
            material_sha256=f.digest(stem + "-common-material") if proof else None,
            consumed_at=raw["created_at"] if proof else None,
            transaction_proof_id=uid(stem + "-actual-transaction"),
            transaction_proof_sha256=f.digest(stem + "-actual-transaction"),
            audit=f.AuditBinding(
                id=uid(stem + "-audit"),
                receipt_id=uid(stem + "-receipt"),
                actor_id=actor,
                operation=name,
            ),
            outbox=f.OutboxBinding(
                id=uid(stem + "-outbox"),
                receipt_id=uid(stem + "-receipt"),
                correlation_id=uid(stem + "-command"),
                effect=getattr(OPS, stem + "_event"),
            ),
            received_at=raw["created_at"],
        )
    )
    raw["ref"]["sha256"] = f.fact_sha256(raw)
    return klass.model_validate(raw)


def reseal(value, **changes):
    raw = json_value(value)
    raw.update(json_value(changes))
    return seal(type(value), raw, value.provenance.actor_id)


def material_fixture(*, null_raw=False):
    binding, pair = saved("test.disposition.decide", null_raw=null_raw)
    binding = binding.model_copy(update={"caller_id": uid("named-reviewer")})
    anchor = fixture_anchor(binding, pair)
    pair_proof = verify_paired_material(binding, pair, at=AT).proof
    run = pair.run_after.snapshot
    # Actual new paired result retains its own independent actual clocks; full
    # result rule computation is exercised by verify_paired_material, not here.
    sample, item, measurement = run.samples[0], run.items[0], run.measurements[0]
    exact = f.SourceRef(
        id=pair_proof.required_source_read_set[0].artifact_id,
        revision=1,
        kind="artifact",
        position="synthetic exact owner source",
    )
    sources = f.canonical_sources(
        (*anchor.origin_sources, exact, item.method, item.criterion.source)
    )
    reads = f.canonical_reads(
        (*anchor.origin_required_source_read_set, *pair_proof.required_source_read_set)
    )
    origin_basis = {b.id: b for b in anchor.origin_source_basis}
    basis = tuple(
        origin_basis.get(r.artifact_id)
        or safety(
            f.SourceRef(
                id=r.artifact_id,
                revision=r.expected_revision,
                kind="artifact",
                position="synthetic full source",
            )
        )
        for r in reads
    )
    common = dict(
        previous=None,
        scope=anchor.origin.scope,
        issue_id=anchor.origin.issue_id,
        capa_id=anchor.origin.issue.capa.id,
        purpose=anchor.origin.purpose,
        anchor_sha256=anchor.anchor_sha256,
        requirement_sha256=f.digest(json_value(anchor.origin.issue.capa.requirement)),
        nature="synthetic",
        owner_id=anchor.origin.owner_id,
        visibility="product",
        sources=sources,
        required_source_read_set=reads,
        source_basis=basis,
    )
    targets = (
        f.ObservationTarget(
            key="known-sample-A",
            kind="sample",
            ref=f.FixedRef(id=sample.id, revision=sample.revision),
            actual_configuration=f.FixedRef(
                id=sample.actual_configuration.id, revision=sample.actual_configuration.revision
            ),
            identity_sources=(exact,),
        ),
    )
    actions = f._action_bindings(anchor)
    rule = seal(
        f.RuleVersion,
        dict(
            **common,
            kind="rule",
            ref={"id": uid("new-rule-v1"), "revision": 1, "sha256": "0" * 64},
            created_at=NOW + timedelta(minutes=1),
            issuer={
                "key": "explicit-synthetic-rule",
                "version": "v1",
                "epoch": 1,
                "nature": "synthetic",
            },
            policy_ref=exact,
            policy_sha256=f.digest("full fixed policy"),
            failures=anchor.origin.issue.failures,
            actions=actions,
            method=item.method,
            criterion=item.criterion.source,
            sampling=f.SamplingRequirement(
                targets=targets,
                minimum_records=1,
                sampling_method=exact,
                acceptance=item.criterion.source,
                observation_from=NOW + timedelta(minutes=2),
                observation_until=NOW + timedelta(minutes=20),
                require_run_review=True,
                require_disposition=True,
            ),
            rule_material={"exact_published_method": "no generated numeric thresholds"},
            independence_material={"actual_owner_policy": "needs live owner proof"},
            valid_from=NOW + timedelta(minutes=1),
            valid_until=AT + timedelta(hours=2),
        ),
        uid("issuer-human"),
    )
    observation = seal(
        f.ObservationVersion,
        dict(
            **common,
            kind="observation",
            ref={"id": uid("observation-v1"), "revision": 1, "sha256": "0" * 64},
            created_at=NOW + timedelta(minutes=30),
            rule=rule.ref,
            issuer=rule.issuer,
            targets=targets,
            executor_id=uid("actual-observer"),
            observed_from=NOW + timedelta(minutes=2),
            observed_until=NOW + timedelta(minutes=20),
            at=f.EventTime(
                occurred_at=NOW + timedelta(minutes=21), original_timezone="UTC", source=exact
            ),
            records=(
                f.ObservationRecord(
                    target_key=targets[0].key,
                    occurred_at=NOW + timedelta(minutes=12),
                    original_timezone="America/Los_Angeles",
                    sources=(exact,),
                    raw_material={"actual_owner_record": "fixed text; not a pass claim"},
                    missing_fields=(),
                ),
            ),
            coverage_sources=(exact,),
            sampling_material={"fixed_owner_sampling_receipt": "opaque input must be live checked"},
        ),
        uid("actual-observer"),
    )
    mapping = f.FailurePairMapping(
        failure_id=rule.failures[0].identity,
        run={
            "id": pair.run_after.ref.id,
            "revision": pair.run_after.ref.revision,
            "kind": "verification_run",
        },
        sample_id=sample.id,
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        item_id=item.id,
        measurement_id=measurement.id,
        projection_id=pair.projection.ref.id,
        applicability_sources=(),
    )
    review = seal(
        f.NamedReview,
        dict(
            **common,
            kind="review",
            ref={"id": uid("review-v1"), "revision": 1, "sha256": "0" * 64},
            created_at=NOW + timedelta(minutes=170),
            candidate=f.FactRef(
                id=uid("actual-candidate"),
                revision=1,
                sha256=f.digest("actual owner saved unknown candidate"),
            ),
            candidate_sha256=f.digest("actual owner saved unknown candidate"),
            rule=rule.ref,
            observations=(observation.ref,),
            reviewer_id=uid("named-reviewer"),
            at=f.EventTime(
                occurred_at=NOW + timedelta(minutes=169), original_timezone="UTC", source=exact
            ),
            pair_applicability=(
                f.PairApplicability(
                    mapping=mapping,
                    method=item.method,
                    criterion=item.criterion.source,
                    conclusion="applicable",
                    reason="synthetic saved qualified actual review",
                    sources=(exact,),
                ),
            ),
            action_fulfillment=(
                f.ActionFulfillment(
                    action=actions[0],
                    classification="investigation",
                    conclusion="applicable",
                    reason="saved actual action owner investigation",
                    owner_refs=(exact,),
                    owner_material={"exact": "bound action completion and actual owner evidence"},
                ),
            ),
            participants=(
                f.Participant(
                    id=uid("actual-observer"), roles=("observation",), owner_sources=(exact,)
                ),
                f.Participant(
                    id=run.execution.executor_id, roles=("new_test",), owner_sources=(exact,)
                ),
            ),
            participant_owner_material={
                "original_and_new": "host must collect complete actual owners"
            },
            conclusion="applicable",
            reason="actual synthetic named applicability; not effectiveness",
            authority_snapshot={"saved_exact_human": str(uid("named-reviewer"))},
            policy_snapshot={"full_published_snapshot": "kept"},
            valid_until=AT + timedelta(hours=1),
        ),
        uid("named-reviewer"),
    )
    return f.FactMaterial(
        anchor=anchor,
        rule=rule,
        observations=(observation,),
        review=review,
        pairs=(f.SavedPair(binding=binding, material=pair),),
    )


class Session(SQLAlchemySession):
    def __init__(self):
        # Genuine active caller UOW/SAVEPOINT, with no engine/bind/DB connection.
        super().__init__()
        self.begin()
        self.begin_nested()


class Reader:
    """Explicit fake owner, never a real qualification or physical source proof."""

    def __init__(self, material, clock):
        self.material = material
        self.clock = clock
        self.calls = []
        self.epoch = 1
        self.deadline = AT + timedelta(minutes=30)
        self.hook = lambda name, s: None

    def read(self, s, ctx, pid, ref, *, at):
        self.calls.append("read")
        self.hook("read", s)
        return self.material

    def refresh(self, s, ctx, pid, previous, *, at):
        self.calls.append("refresh")
        self.hook("refresh", s)
        return self.material

    def proof(self, name, s, ctx, material, at):
        return f.HostFactProof(
            issued_by=self,
            session=s,
            transaction=s.get_transaction(),
            nested_transaction=s.get_nested_transaction(),
            scope=material.anchor.origin.scope,
            caller_id=ctx.requester_id,
            material_sha256=f.digest(json_value(material)),
            kind=name,
            basis_sha256=f.digest({"kind": name, "complete_runtime_epoch": self.epoch}),
            nature="synthetic",
            checked_at=self.clock(),
            valid_until=self.deadline,
        )

    def refresh_proofs(self, s, ctx, pid, material, operations, proofs, *, at):
        self.calls.append("refresh_proofs")
        self.hook("refresh_proofs", s)
        return tuple(self.proof(name, s, ctx, material, at) for name in f.GATES)


def install(name):
    def gate(self, s, ctx, pid, material, operations, *, at):
        self.calls.append(name)
        self.hook(name, s)
        return self.proof(name, s, ctx, material, at)

    setattr(Reader, name, gate)


for gate_name in f.GATES:
    install(gate_name)


@pytest.fixture
def material():
    return material_fixture()


def load(material, *, reader=None, session=None, clock=None):
    s = session or Session()
    ctx = SimpleNamespace(
        tenant_id=material.anchor.origin.scope.tenant_id, requester_id=uid("named-reviewer")
    )
    clock = clock or (lambda: AT)
    reader = reader or Reader(material, clock)
    return f.load_verification_facts(
        s,
        ctx,
        material.anchor.origin.scope.product_id,
        material.review.ref,
        operations=OPS,
        reader=reader,
        clock=clock,
    )


def test_structural_material_reuses_full_anchor_and_actual_paired_rows(material):
    out = f.inspect_fact_material(material, OPS, at=AT)
    assert out.proof.structural_only is True and not out.missing
    assert len(out.proof.required_source_read_set) <= 20
    assert out.proof.anchor_sha256 == material.anchor.anchor_sha256
    assert out.proof.pair_proofs[0].meaning == "performed"
    assert not hasattr(out.proof, "current") and not hasattr(out.proof, "result")
    assert not hasattr(out.proof, "qualified")


def test_same_uow_independent_refresh_then_real_post_io_clock(material):
    reader = Reader(material, lambda: AT)
    out = load(material, reader=reader)
    assert not out.missing and len(out.host_proofs) == 7
    assert reader.calls == ["read", *f.GATES, "refresh", *f.GATES, "refresh_proofs"]
    assert not hasattr(out, "verification_evidence")


@pytest.mark.parametrize("name", ["read", "refresh", "refresh_proofs", *f.GATES])
def test_every_actual_owner_callback_is_mandatory_not_dto_flags(material, name):
    reader = Reader(material, lambda: AT)
    setattr(reader, name, None)
    out = load(material, reader=reader)
    assert out.host_proofs == () and out.missing[0].code == "INTEGRATION_REQUIRED"
    assert reader.calls == []


def test_no_registry_never_self_registers_or_calls_any_owner(material):
    reader = Reader(material, lambda: AT)
    out = f.load_verification_facts(
        Session(),
        SimpleNamespace(),
        material.anchor.origin.scope.product_id,
        material.review.ref,
        reader=reader,
    )
    assert out.missing[0].code == "INTEGRATION_REQUIRED" and not reader.calls
    assert f.inspect_fact_material(material, None, at=AT).missing[0].code == "FACT_REGISTRY_MISSING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("observation_tier", "T0"),
        ("review_tier", "T1"),
        ("rule_tier", "T2"),
        ("review", OPS.observation),
    ],
)
def test_host_registry_has_exact_tiers_and_distinct_names(field, value):
    with pytest.raises(ValidationError):
        f.FactOperations.model_validate({**json_value(OPS), field: value})


@pytest.mark.parametrize(
    "field",
    ["observation", "observation_event", "observation_subject_type", "review", "rule_import"],
)
def test_saved_operation_event_subject_cannot_use_different_registry(material, field):
    ops = f.FactOperations.model_validate({**json_value(OPS), field: "different.actual.entry"})
    with pytest.raises(DomainError, match="host registry"):
        f.inspect_fact_material(material, ops, at=AT)


def test_unknown_review_saved_but_never_promoted_to_full_evidence(material):
    review = reseal(material.review, conclusion="unknown")
    out = load(material.model_copy(update={"review": review}))
    assert out.host_proofs == () and any(m.code == "APPLICABILITY_UNCONFIRMED" for m in out.missing)


def test_action_completion_exists_but_unknown_classification_remains_missing(material):
    action = material.review.action_fulfillment[0].model_copy(update={"classification": "unknown"})
    review = reseal(material.review, action_fulfillment=[json_value(action)])
    out = f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert any(m.code == "ACTION_FULFILLMENT_UNCONFIRMED" for m in out.missing)


def test_actual_partial_window_and_null_records_remain_missing(material):
    o = material.observations[0]
    rec = o.records[0].model_copy(update={"missing_fields": ("observed_quantity",)})
    o = reseal(o, observed_until=NOW + timedelta(minutes=15), records=[json_value(rec)])
    review = reseal(material.review, observations=[json_value(o.ref)])
    out = f.inspect_fact_material(
        material.model_copy(update={"observations": (o,), "review": review}), OPS, at=AT
    )
    assert {m.code for m in out.missing} >= {
        "OBSERVATION_WINDOW_INCOMPLETE",
        "OBSERVATION_RECORDS_INCOMPLETE",
    }


@pytest.mark.parametrize(
    "field", ["applicable", "current", "complete", "pass", "participant_complete"]
)
def test_client_truth_flags_rejected_even_resealed_as_structural_input(material, field):
    raw = json_value(material.review)
    raw[field] = True
    with pytest.raises(ValidationError):
        seal(f.NamedReview, raw, material.review.reviewer_id)


def test_fact_hash_covers_raw_values_original_times_and_participant_ledger(material):
    raw = json_value(material.observations[0])
    raw["records"][0]["raw_material"]["actual_owner_record"] = "tampered"
    with pytest.raises(ValidationError, match="digest/provenance"):
        f.ObservationVersion.model_validate(raw)
    raw = json_value(material.review)
    raw["participant_owner_material"] = {"client": "pretend complete"}
    with pytest.raises(ValidationError, match="digest/provenance"):
        f.NamedReview.model_validate(raw)


def test_original_failure_full_proof_is_not_replaced_with_new_run_current(material):
    raw = json_value(material)
    raw["anchor"]["failures"][0]["result"]["run_version_id"] = str(
        material.pairs[0].material.run_after.ref.id
    )
    with pytest.raises(ValidationError):
        f.FactMaterial.model_validate(raw)


def test_wrong_original_requirement_and_purpose_rejected_after_reseal(material):
    for change in (
        {"requirement_sha256": f.digest("changed")},
        {"purpose": "other purpose"},
        {"nature": "real"},
    ):
        if "nature" in change:
            change["issuer"] = {**json_value(material.rule.issuer), "nature": "real"}
        rule = reseal(material.rule, **change)
        with pytest.raises(DomainError) as exc:
            f.inspect_fact_material(material.model_copy(update={"rule": rule}), OPS, at=AT)
        assert exc.value.code == "FACT_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "field", ["sample_id", "actual_configuration_id", "measurement_id", "projection_id"]
)
def test_mapping_bindings_require_real_saved_pair_not_ref_existence(material, field):
    p = material.review.pair_applicability[0]
    raw = json_value(p)
    raw["mapping"][field] = str(uid("unrelated-existing-object"))
    review = reseal(material.review, pair_applicability=[raw])
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "FACT_PAIR_MAPPING_MISMATCH"


def test_failure_omission_and_action_completion_relabel_rejected(material):
    p = json_value(material.review.pair_applicability[0])
    p["mapping"]["failure_id"] = "unrelated failure"
    review = reseal(material.review, pair_applicability=[p])
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "FACT_FAILURE_COVERAGE_MISMATCH"
    act = json_value(material.review.action_fulfillment[0])
    act["action"]["completion_sha256"] = f.digest("other completion")
    review = reseal(material.review, action_fulfillment=[act])
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "FACT_ACTION_COVERAGE_MISMATCH"


def test_nested_original_refs_must_stay_in_full_exact_readset(material):
    raw = json_value(material.review)
    raw["sources"] = [s for s in raw["sources"] if s != json_value(material.review.at.source)]
    review = seal(f.NamedReview, raw, material.review.reviewer_id)
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "MISSING_REQUIRED_EVIDENCE"


@pytest.mark.parametrize("when", ["read", "refresh", "sources", "authority", "refresh_proofs"])
@pytest.mark.parametrize("field", ["transaction", "nested"])
def test_owner_cannot_commit_replace_or_cross_savepoint_at_any_io(material, when, field):
    reader = Reader(material, lambda: AT)

    def replace_uow(name, s):
        if name != when:
            return
        if field == "transaction":
            s.rollback()
            s.begin()
        else:
            s.get_nested_transaction().rollback()
        s.begin_nested()

    reader.hook = replace_uow
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader)
    assert exc.value.code == "CALLER_UOW_CHANGED"


def test_host_callback_hash_or_bool_is_not_an_opaque_same_uow_proof(material):
    reader = Reader(material, lambda: AT)
    reader.participants = lambda *args, **kwargs: {"complete": True, "sha256": f.digest("pretend")}
    out = load(material, reader=reader)
    assert out.host_proofs == () and out.missing[0].code == "FACT_OWNER_PROOF_MISSING"


@pytest.mark.parametrize("change", ["caller", "session", "nature", "issuer", "kind"])
def test_opaque_proof_cannot_be_reused_in_different_scope_or_reader(material, change):
    reader = Reader(material, lambda: AT)
    original = reader.proof

    def wrong(name, s, ctx, m, at):
        p = original(name, s, ctx, m, at)
        return replace(
            p,
            **{
                "caller": {"caller_id": uid("other")},
                "session": {"session": Session()},
                "nature": {"nature": "real"},
                "issuer": {"issued_by": object()},
                "kind": {"kind": "wrong"},
            }[change],
        )

    reader.proof = wrong
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader)
    assert exc.value.code == "FACT_OWNER_PROOF_UNBOUND"


def test_owner_runtime_changes_after_first_round_sources_fail_final_refresh(material):
    reader = Reader(material, lambda: AT)
    reader.hook = lambda name, s: setattr(reader, "epoch", 2) if name == "refresh" else None
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader)
    assert exc.value.code == "SOURCE_STALE"


def test_later_final_owner_io_revokes_earlier_proof_fail_post_all_io_refresh(material):
    reader = Reader(material, lambda: AT)

    def revoke(name, s):
        if name == "authority" and reader.calls.count("authority") == 2:
            reader.epoch += 1

    reader.hook = revoke
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader)
    assert exc.value.code == "SOURCE_STALE"


def test_last_refresh_io_crossing_expiry_cannot_use_earlier_clock(material):
    times = [AT]

    def clock():
        return times[0]

    reader = Reader(material, clock)
    reader.deadline = AT + timedelta(seconds=1)
    reader.hook = lambda name, s: (
        times.__setitem__(0, AT + timedelta(seconds=2)) if name == "refresh_proofs" else None
    )
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader, clock=clock)
    assert exc.value.code == "FACT_OWNER_PROOF_EXPIRED"


def test_saved_rule_expires_during_final_io_keeps_explicit_missing(material):
    times = [AT]
    rule = reseal(material.rule, valid_until=AT + timedelta(seconds=1))
    observation = reseal(material.observations[0], rule=json_value(rule.ref))
    review = reseal(
        material.review, rule=json_value(rule.ref), observations=[json_value(observation.ref)]
    )
    material = material.model_copy(
        update={"rule": rule, "observations": (observation,), "review": review}
    )
    reader = Reader(material, lambda: times[0])
    reader.hook = lambda name, s: (
        times.__setitem__(0, AT + timedelta(seconds=2)) if name == "refresh_proofs" else None
    )
    out = load(material, reader=reader, clock=lambda: times[0])
    assert out.host_proofs == () and out.missing[0].code == "FACT_EXPIRED"


@pytest.mark.parametrize(
    "path", ["proof_id", "invocation_decision_id", "receipt_subject", "outbox", "audit"]
)
def test_saved_named_t2_reciprocal_atom_is_not_replaceable(material, path):
    raw = json_value(material.review.provenance)
    if path in {"proof_id", "invocation_decision_id"}:
        raw[path] = str(uid("different-real-proof"))
    elif path == "receipt_subject":
        raw[path]["revision"] += 1
    else:
        raw[path]["receipt_id"] = str(uid("other-receipt"))
    with pytest.raises(ValidationError):
        f.FactAtom.model_validate(raw)


def test_publication_does_not_invent_public_t2_or_invocation(material):
    raw = json_value(material.rule.provenance)
    raw["proof_id"] = str(uid("pretend-publication-approval"))
    with pytest.raises(ValidationError, match="publication"):
        f.FactAtom.model_validate(raw)


def test_wrong_source_safety_epoch_after_reseal_cannot_hide_aba(material):
    raw = json_value(material.review)
    raw["source_basis"][0]["hash"] = f.digest("changed actual original content")
    review = seal(f.NamedReview, raw, material.review.reviewer_id)
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "SOURCE_STALE"


def test_clock_timezone_and_actual_times_are_not_filled_from_created_at(material):
    raw = json_value(material.observations[0])
    raw["at"]["occurred_at"] = raw["at"]["occurred_at"].replace("Z", "").replace("+00:00", "")
    with pytest.raises(ValidationError):
        seal(f.ObservationVersion, raw, material.observations[0].executor_id)
    raw = json_value(material.observations[0])
    raw["records"][0]["original_timezone"] = "made-up/timezone"
    with pytest.raises(ValidationError):
        seal(f.ObservationVersion, raw, material.observations[0].executor_id)


def test_no_session_or_no_actual_material_is_explicit_missing(material):
    s = Session()
    s.rollback()
    assert load(material, session=s).missing[0].code == "CALLER_UOW_REQUIRED"
    reader = Reader(material, lambda: AT)
    reader.read = lambda *args, **kwargs: None
    assert load(material, reader=reader).missing[0].code == "FACT_OWNER_MATERIAL_MISSING"


def test_duck_typed_object_placeholders_are_not_an_actual_sqlalchemy_uow(material):
    placeholder = SimpleNamespace(
        get_transaction=lambda: object(), get_nested_transaction=lambda: object()
    )
    reader = Reader(material, lambda: AT)
    out = load(material, session=placeholder, reader=reader)
    assert out.missing[0].code == "CALLER_UOW_REQUIRED"
    assert reader.calls == []


@pytest.mark.parametrize("state", ["closed_root", "inactive_root", "closed_nested"])
def test_actual_but_closed_or_inactive_sqlalchemy_transaction_is_not_usable(material, state):
    s = Session()
    if state == "closed_root":
        s.get_transaction().close()
    elif state == "inactive_root":
        # Closing the root after an explicit rollback is inactive, not a usable
        # historical identity. The persistent failed-flush state is below.
        s.get_nested_transaction().rollback()
        s.get_transaction().rollback(_capture_exception=True, _to_root=True)
    else:
        closed = s.get_nested_transaction()
        closed.close()
        # Closed nested transaction must not be resurrected as current by a
        # faulty reader/subclass even if its old identity was remembered.
        s.get_nested_transaction = lambda: closed
    reader = Reader(material, lambda: AT)
    out = load(material, session=s, reader=reader)
    assert out.missing[0].code == "CALLER_UOW_REQUIRED" and not reader.calls


@pytest.mark.parametrize("when", ["sources", "refresh", "refresh_proofs"])
def test_owner_closing_actual_uow_during_io_is_denied(material, when):
    reader = Reader(material, lambda: AT)
    reader.hook = lambda name, s: s.get_transaction().close() if name == when else None
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader)
    assert exc.value.code == "CALLER_UOW_CHANGED"


def test_genuine_active_no_savepoint_uow_is_allowed_without_any_connection(material):
    s = SQLAlchemySession()
    s.begin()
    assert s.bind is None and f._uow(s) == (s.get_transaction(), None)
    out = load(material, session=s)
    assert not out.missing and all(p.nested_transaction is None for p in out.host_proofs)
    assert s.bind is None and not s.get_transaction()._connections


def test_actual_savepoint_rejection_does_not_connect_or_replace_outer_uow(material):
    s = Session()
    root = s.get_transaction()
    # SAVEPOINT rollback restores the same usable outer Session, but the
    # wrapper must still reject its originally captured nested proof identity.
    reader = Reader(material, lambda: AT)
    reader.hook = lambda name, session: (
        session.get_nested_transaction().rollback() if name == "sources" else None
    )
    with pytest.raises(DomainError) as exc:
        load(material, reader=reader, session=s)
    assert exc.value.code == "CALLER_UOW_CHANGED"
    assert s.get_transaction() is root and root.is_active and s.is_active
    assert s.bind is None and not root._connections


def test_real_rollback_event_inactive_state_is_rejected_without_database(material):
    s = Session()
    # The real SessionTransaction rollback sets DEACTIVE, exactly the gate that
    # matters. An event observes it before restoration; no mapped rows/SQL.
    observed = []

    @event.listens_for(s, "after_rollback")
    def during_failed_rollback(session):
        observed.append((session.is_active, f._uow(session)))

    s.get_nested_transaction().rollback()
    assert observed and observed[0] == (False, (None, None))
    assert s.bind is None


def test_real_failed_flush_requires_caller_rollback_without_engine_or_sql(material):
    class LocalBase(DeclarativeBase):
        pass

    class LocalRow(LocalBase):
        __tablename__ = "pure_unbound_in_memory_row"
        id: Mapped[int] = mapped_column(primary_key=True)

    s = SQLAlchemySession()  # No engine exists; no DB can be contacted.
    root = s.begin()
    s.add(LocalRow(id=1))
    with pytest.raises(UnboundExecutionError):
        s.flush()
    assert s.get_transaction() is root and not s.is_active and not root.is_active
    assert s.bind is None and not root._connections
    reader = Reader(material, lambda: AT)
    assert load(material, session=s, reader=reader).missing[0].code == "CALLER_UOW_REQUIRED"
    assert not reader.calls
    s.rollback()


def test_saved_pair_binding_cannot_impersonate_a_different_current_consumer(material):
    saved_pair = material.pairs[0]
    value = saved_pair.model_copy(
        update={
            "binding": saved_pair.binding.model_copy(update={"caller_id": uid("other-reader")}),
        }
    )
    with pytest.raises(DomainError) as exc:
        load(material.model_copy(update={"pairs": (value,)}))
    assert exc.value.code == "FACT_SCOPE_MISMATCH"


def test_observation_and_review_cannot_share_actual_command_even_with_new_receipts(material):
    raw = json_value(material.review)
    raw["provenance"]["command_id"] = str(material.observations[0].provenance.command_id)
    raw["provenance"]["outbox"]["correlation_id"] = raw["provenance"]["command_id"]
    raw["ref"]["sha256"] = f.fact_sha256(raw)
    review = f.NamedReview.model_validate(raw)
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "FACT_PROVENANCE_MISMATCH"


def test_named_review_cannot_anticipate_actual_saved_new_output(material):
    # Both the submitted actual clock and its received clock are internally
    # valid, but earlier than the actual retained new Run's saved result.
    review = reseal(
        material.review,
        created_at=NOW + timedelta(minutes=150),
        at=json_value(
            material.review.at.model_copy(update={"occurred_at": NOW + timedelta(minutes=149)})
        ),
    )
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(material.model_copy(update={"review": review}), OPS, at=AT)
    assert exc.value.code == "FACT_TIME_INVALID"


def test_rule_cannot_move_observation_requirement_before_actual_completion(material):
    sampling = material.rule.sampling.model_copy(
        update={"observation_from": NOW - timedelta(minutes=1)}
    )
    rule = reseal(material.rule, sampling=json_value(sampling))
    observation = reseal(material.observations[0], rule=json_value(rule.ref))
    review = reseal(
        material.review, rule=json_value(rule.ref), observations=[json_value(observation.ref)]
    )
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(
            material.model_copy(
                update={"rule": rule, "observations": (observation,), "review": review}
            ),
            OPS,
            at=AT,
        )
    assert exc.value.code == "FACT_TIME_INVALID"


def test_indeterminate_original_new_measurement_never_becomes_verified_effectiveness():
    material = material_fixture(null_raw=True)
    out = load(material)
    assert any(m.code == "NEW_RUN_RESULT_UNKNOWN" for m in out.missing)
    assert out.host_proofs == ()
    assert not hasattr(out, "verification_evidence")


@pytest.mark.parametrize("delta", ["first_non_one", "same_id", "skip_version"])
def test_versioned_fact_has_exact_immutable_predecessor_structure(material, delta):
    raw = json_value(material.rule)
    if delta == "first_non_one":
        raw["ref"]["revision"] = 2
    else:
        raw["ref"]["revision"] = 3 if delta == "skip_version" else 2
        raw["previous"] = {
            "id": raw["ref"]["id"] if delta == "same_id" else str(uid("actual-old-rule")),
            "revision": 1,
            "sha256": f.digest("actual previous rule full snapshot"),
        }
    with pytest.raises(ValidationError):
        seal(f.RuleVersion, raw, material.rule.provenance.actor_id)


def test_complete_multi_owner_source_union_never_truncates_over_twenty(material):
    def add(value, suffix):
        refs = tuple(
            f.SourceRef(
                id=uid(f"extra-{suffix}-{n}"),
                revision=1,
                kind="artifact",
                position="actual-source-line",
            )
            for n in range(2)
        )
        reads = f.canonical_reads(
            (
                *value.required_source_read_set,
                *(f.SourceRead(artifact_id=r.id, expected_revision=1) for r in refs),
            )
        )
        return reseal(
            value,
            sources=[json_value(v) for v in f.canonical_sources((*value.sources, *refs))],
            required_source_read_set=[json_value(r) for r in reads],
            source_basis=[json_value(b) for b in (*value.source_basis, *(safety(r) for r in refs))],
        )

    rule = add(material.rule, "rule")
    observation = reseal(material.observations[0], rule=json_value(rule.ref))
    review = add(material.review, "review")
    review = reseal(review, rule=json_value(rule.ref), observations=[json_value(observation.ref)])
    assert len(rule.required_source_read_set) <= 20 and len(review.required_source_read_set) <= 20
    with pytest.raises(DomainError) as exc:
        f.inspect_fact_material(
            material.model_copy(
                update={"rule": rule, "observations": (observation,), "review": review}
            ),
            OPS,
            at=AT,
        )
    assert "never truncate" in str(exc.value)
