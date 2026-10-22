"""No-connect actual ORM/UOW and consumer; owner/SQL/source truth substituted.

These cases exercise the real writer and False -> True consumption history.
They do not attest original bytes, public qualifications, FK/RLS or PG commit.
"""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from quality_issues.helpers import NOW, uid
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, make_transient_to_detached
from test_candidate_write_prepare import origin_fixture

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness import fact_commands as commands
from pdos_next.domain.capa_effectiveness import fact_consumption as consumption
from pdos_next.domain.capa_effectiveness import fact_write as writer
from pdos_next.domain.capa_effectiveness.fact_storage_codec import (
    body_payload_sha256,
    decode_fact_body,
)
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Principal, Product
from pdos_next.service import Context, digest


def rejects(code, fn):
    with pytest.raises(DomainError) as error:
        fn()
    assert error.value.reason == code


def make_world(monkeypatch, kind="observation"):
    fixed = origin_fixture()
    origin = fixed.origin
    clock = SimpleNamespace(at=NOW + timedelta(hours=2))
    bind = create_engine("sqlite://")
    event.listen(bind, "do_connect", lambda *_: pytest.fail("Owned pure must not connect"))
    s = Session(bind=bind)
    s.begin()
    ctx = Context(
        origin.scope.tenant_id,
        uid("independent-fact-writer"),
        uid("independent-fact-writer"),
        category_id=origin.category_id,
    )
    source = origin.sources[-1].model_dump(mode="json")
    at = {
        "occurred_at": (NOW + timedelta(hours=1, microseconds=123457)).isoformat(),
        "original_timezone": "America/Los_Angeles",
        "source": source,
    }
    target = {
        "key": "one-population",
        "kind": "population",
        "ref": {"id": str(uid("actual-population")), "revision": 1},
        "actual_configuration": None,
        "identity_sources": [source],
    }
    sampling = {
        "targets": [target],
        "minimum_records": 2,
        "sampling_method": source,
        "acceptance": source,
        "observation_from": (NOW + timedelta(minutes=30)).isoformat(),
        "observation_until": (NOW + timedelta(hours=1)).isoformat(),
        "require_named_review": True,
        "require_run_review": True,
        "require_disposition": True,
    }
    payload = {
        "issue_id": str(origin.issue_id),
        "expected_issue_revision": origin.ref.revision,
        "capa_id": str(origin.issue.capa.id),
        "sources": [source],
        "reason": "Explicit original unknown remains a named recorded fact",
        "visibility": "category",
    }
    fact_ref = {
        "id": str(uid("actual-rule")),
        "revision": 1,
        "sha256": digest("fixed full actual Rule ref fixture"),
    }
    issuer = {
        "key": "explicit-synthetic-pure-owner",
        "version": "v1",
        "epoch": 1,
        "nature": "synthetic",
    }
    body = {
        "previous": None,
        "scope": origin.scope.model_dump(mode="json"),
        "issue_id": str(origin.issue_id),
        "capa_id": str(origin.issue.capa.id),
        "purpose": origin.purpose,
        "anchor_sha256": fixed.anchor_sha256,
        "requirement_sha256": digest(origin.issue.capa.requirement.model_dump(mode="json")),
        "nature": origin.nature,
        "owner_id": str(origin.owner_id),
        "visibility": origin.visibility,
        "sources": [v.model_dump(mode="json") for v in origin.sources],
        "required_source_read_set": [
            v.model_dump(mode="json") for v in origin.required_source_read_set
        ],
        "source_basis": [v.model_dump(mode="json") for v in origin.source_basis],
        "kind": kind,
    }
    if kind == "rule":
        payload.update(
            origin=origin.ref.model_dump(mode="json"),
            external_id="controlled-rule-series",
            policy_ref=source,
            method=source,
            criterion=source,
            sampling=sampling,
            rule_material={"acceptance_source": source},
            independence_material={"all_actual_participant_owners_required": True},
            valid_from=NOW.isoformat(),
            valid_until=(clock.at + timedelta(hours=2)).isoformat(),
        )
        body.update(
            issuer=issuer,
            policy_ref=source,
            policy_sha256=digest("controlled policy source bytes"),
            failures=[v.model_dump(mode="json") for v in origin.issue.failures],
            actions=[v.model_dump(mode="json") for v in writer._action_bindings(fixed)],
            **{
                k: payload[k]
                for k in (
                    "method",
                    "criterion",
                    "sampling",
                    "rule_material",
                    "independence_material",
                    "valid_from",
                    "valid_until",
                )
            },
        )
    elif kind == "observation":
        record = {
            "target_key": target["key"],
            "occurred_at": sampling["observation_until"],
            "original_timezone": "America/Los_Angeles",
            "sources": [source],
            "raw_material": {"value": None, "reported": "original unknown"},
        }
        payload.update(
            rule=fact_ref,
            target_keys=[target["key"]],
            observed_from=sampling["observation_from"],
            observed_until=sampling["observation_until"],
            at=at,
            records=[record],
            coverage_sources=[source],
            confirmation_token="actual-common-observation-token",
        )
        body.update(
            rule=fact_ref,
            issuer=issuer,
            targets=[target],
            executor_id=str(ctx.actor_id),
            observed_from=payload["observed_from"],
            observed_until=payload["observed_until"],
            at=at,
            records=[{**record, "missing_fields": ["value"]}],
            coverage_sources=[source],
            sampling_material={"coverage": "unknown", "sampling_method": source},
        )
    else:
        failure = origin.issue.failures[0]
        mapping = {
            "failure_id": failure.identity,
            "run": {
                "id": str(uid("actual-new-run-version")),
                "revision": 4,
                "kind": "verification_run",
                "key": None,
            },
            "sample_id": str(uid("actual-new-sample")),
            "sample_revision": 1,
            "actual_configuration_id": str(uid("new-actual")),
            "actual_configuration_revision": 1,
            "item_id": "fixed-item",
            "measurement_id": None,
            "projection_id": None,
            "applicability_sources": [],
        }
        pair = {
            "mapping": mapping,
            "method": None,
            "criterion": None,
            "conclusion": "unknown",
            "reason": "Current actual unknown is not a pass",
            "sources": [source],
        }
        action = writer._action_bindings(fixed)[0]
        review_action = {
            "action_id": str(action.action_id),
            "conclusion": "unknown",
            "reason": "Owner material is not fulfillment",
            "sources": [source],
        }
        payload.update(
            candidate={
                "id": str(uid("actual-candidate")),
                "revision": 1,
                "sha256": digest("full candidate SHA fixture"),
            },
            rule=fact_ref,
            observations=[
                {
                    "id": str(uid("observation")),
                    "revision": 1,
                    "sha256": digest("full observation SHA fixture"),
                }
            ],
            at=at,
            pair_applicability=[pair],
            action_fulfillment=[review_action],
            conclusion="unknown",
            approval_token="actual-common-named-review-token",
        )
        body.update(
            candidate=payload["candidate"],
            candidate_sha256=payload["candidate"]["sha256"],
            rule=fact_ref,
            observations=payload["observations"],
            reviewer_id=str(ctx.actor_id),
            at=at,
            pair_applicability=[pair],
            action_fulfillment=[
                {
                    "action": action.model_dump(mode="json"),
                    "classification": "investigation",
                    "conclusion": "unknown",
                    "reason": review_action["reason"],
                    "owner_refs": [source],
                    "owner_material": {"actual_owner_source": source},
                }
            ],
            participants=[
                {"id": str(origin.owner_id), "roles": ["completion"], "owner_sources": [source]}
            ],
            participant_owner_material={"actual_participant_sources": [source]},
            conclusion="unknown",
            reason=payload["reason"],
            valid_until=(clock.at + timedelta(hours=1)).isoformat(),
        )
    checked = commands.payload_for(kind, payload)
    authority = {
        "scope": origin.scope.model_dump(mode="json"),
        "subject_id": str(ctx.actor_id),
        "operation": commands.SPECS[kind][0],
        "purpose": origin.purpose,
        "authorized": True,
        "qualified": True,
        "synthetic": True,
        "required_source_read_set": body["required_source_read_set"],
        "facts_revision": digest("explicit substituted current operation facts"),
        "roles": ["quality"],
        "fact_refs": [
            dict(
                id=str(uid("fact-" + selected)),
                revision=1,
                kind=selected,
                role="quality",
                nature="synthetic",
                state="active",
                operations=[commands.SPECS[kind][0]],
                purposes=[origin.purpose],
                valid_from=(clock.at - timedelta(hours=1)).isoformat(),
                valid_until=(clock.at + timedelta(minutes=45)).isoformat(),
            )
            for selected in ("duty", "qualification")
        ],
    }
    policy = {
        "facts_revision": digest("explicit substituted current policy"),
        "required_source_read_set": body["required_source_read_set"],
        "id": str(uid("selected-policy")),
        "revision": 1,
        "source_basis": [
            dict(
                id=str(uid("selected-policy")),
                revision=1,
                state="active",
                valid_from=(clock.at - timedelta(hours=1)).isoformat(),
                valid_until=(clock.at + timedelta(hours=1)).isoformat(),
            )
        ],
    }
    if kind == "review":
        body.update(authority_snapshot=authority, policy_snapshot=policy)
    material = writer.FactWriteMaterial.model_validate(
        {
            "body_material": body,
            "anchor": fixed.model_dump(mode="json"),
            "current_issue_version_id": str(origin.ref.id),
            "current_issue_revision": origin.ref.revision,
            "authority_snapshot": authority,
            "policy_snapshot": policy,
            "inspection": {
                "recording_only": True,
                "outcome": "unknown",
                "live_effectiveness_authorized": False,
            },
            "valid_until": None,
            "time_constraints": [(clock.at + timedelta(minutes=45)).isoformat()],
        }
    )
    state = SimpleNamespace(reads=0, refreshes=0, epoch=1, hook=None, sql_hook=None)

    class Owner:
        def read(self, session, context, pid, selected_kind, value, *, new_write):
            assert (session, context, pid, selected_kind) == (s, ctx, origin.scope.product_id, kind)
            assert commands.semantic(value) == commands.semantic(checked)
            state.reads += 1
            return material

        def refresh(self, session, context, pid, selected_kind, value, old, *, new_write):
            assert (session, context, pid, selected_kind) == (s, ctx, origin.scope.product_id, kind)
            state.refreshes += 1
            if state.hook:
                state.hook()
            return material

        def runtime_stamp(self, session):
            assert session is s
            return digest({"explicit_synthetic_runtime_epoch": state.epoch})

    product = Product(
        id=origin.scope.product_id,
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        revision=40,
    )
    person = Principal(
        id=ctx.actor_id, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1
    )
    grant = Grant(
        id=uid("fact-grant"),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        access_epoch=1,
        expires_at=clock.at + timedelta(hours=2),
    )
    project = Project(
        id=origin.scope.project_id,
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        owner_id=origin.owner_id,
        visibility="category",
        status="active",
    )
    current = QualityIssueCurrent(
        id=uid("fact-current-issue"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=project.id,
        issue_id=origin.issue_id,
        issue_version_id=origin.ref.id,
        issue_revision=origin.ref.revision,
        epoch=1,
    )
    rows = {
        Product: product,
        Principal: person,
        Grant: grant,
        Project: project,
        QualityIssueCurrent: current,
    }
    make_transient_to_detached(product)
    s.add(product)

    def one(session, model, *where, lock=False):
        assert session is s and model in rows
        for clause in where:
            value = (
                ctx.category_id
                if getattr(clause.right, "name", None) == "category_for_product"
                else clause.right.value
            )
            assert getattr(rows[model], clause.left.key) == value
        if state.sql_hook:
            state.sql_hook(model)
        return rows[model]

    class ClockMeta(type):
        def __instancecheck__(cls, value):
            return isinstance(value, datetime)

    class Clock(datetime, metaclass=ClockMeta):
        @classmethod
        def now(cls, tz=None):
            return clock.at if tz is not None else clock.at.replace(tzinfo=None)

    monkeypatch.setattr(writer, "_one", one)
    monkeypatch.setattr(writer, "_clock", lambda: clock.at)
    monkeypatch.setattr(writer, "_initial_series_exists", lambda *_: False)
    monkeypatch.setattr(consumption, "datetime", Clock)
    host = writer.FactWriteHost(Owner())
    command = Command(
        command_id=uid("wave18-command-" + kind),
        idempotency_key="wave18-" + kind,
        operation=commands.SPECS[kind][0],
        category_id=ctx.category_id,
        product_id=product.id,
        expected_revision=product.revision,
        source_read_set=body["required_source_read_set"],
        payload=checked.model_dump(mode="json"),
    )
    return SimpleNamespace(
        s=s,
        ctx=ctx,
        kind=kind,
        fixed=fixed,
        clock=clock,
        host=host,
        state=state,
        product=product,
        person=person,
        grant=grant,
        project=project,
        current=current,
        payload=checked,
        command=command,
        material=material,
        rows=rows,
    )


def prepared(f, *, new_write=True):
    return writer.prepare_fact(
        f.s, f.ctx, f.product.id, f.payload, host=f.host, new_write=new_write
    )


def consume(f, phase):
    token = getattr(f.payload, "approval_token" if f.kind == "review" else "confirmation_token")
    proof = Confirmation(
        id=uid("actual-fact-proof-" + f.kind),
        tenant_id=f.ctx.tenant_id,
        product_id=f.product.id,
        actor_id=f.ctx.actor_id,
        subject_id=f.product.id,
        operation=f.command.operation,
        revision=f.product.revision,
        token_hash=digest(token),
        payload_digest=common.material_digest(f.ctx, f.command, f.payload, commands),
        snapshot=writer.reviewed_fact(phase, host=f.host),
        consumed=False,
        created_at=f.clock.at - timedelta(seconds=1),
        expires_at=f.clock.at + timedelta(minutes=10),
    )
    make_transient_to_detached(proof)
    f.s.add(proof)
    host = consumption.ConsumptionHost({f.command.operation: commands})
    binding = host.bind_before_transition(
        f.s, f.ctx, f.command, f.payload, commands, proof, reviewed_snapshot=proof.snapshot
    )
    proof.consumed = True
    marker = host.capture_after_transition(
        f.s, f.ctx, f.command, f.payload, commands, proof, binding=binding
    )
    return proof, host, binding, marker


def apply(f, phase, consumed):
    proof, host, binding, marker = consumed
    return writer.apply_prepared_fact(
        f.s,
        f.ctx,
        f.command,
        f.product,
        f.payload,
        phase,
        host=f.host,
        consumption_host=host,
        module=commands,
        proof=proof,
        consumption_binding=binding,
        consumption_marker=marker,
    )


@pytest.mark.parametrize("kind", ["observation", "review"])
def test_actual_common_consumer_writer_preserves_unknown_body_json_and_one_pointer(
    monkeypatch, kind
):
    f = make_world(monkeypatch, kind)
    phase = prepared(f)
    review = writer.reviewed_fact(phase, host=f.host)
    assert len(review) == 13
    assert "ref" not in review["binding"]["body_material"]
    assert "created_at" not in review["binding"]["body_material"]
    json.dumps(review, allow_nan=False)
    proof, host, binding, marker = consumed = consume(f, phase)
    row = apply(f, phase, consumed)
    assert row.created_at == f.clock.at
    assert row.shared_proof_id == proof.id
    assert row.proof_consumed_at == marker.consumed_at
    assert row.intent_digest == marker.common_intent_sha256
    assert row.owner_id == f.fixed.origin.owner_id != row.writer_id
    assert row.required_source_read_set == review["required_source_read_set"]
    assert row.payload_sha256 == body_payload_sha256(row.fact_body)
    assert "provenance" not in row.fact_body["body"]
    assert "sha256" not in row.fact_body["body"]["ref"]
    assert row.action_result == {"fact_kind": kind, "payload_sha256": row.payload_sha256}
    assert all("token" not in key for key in row.input_snapshot["semantic"])
    json.dumps(row.fact_body, allow_nan=False)
    assert f.state.refreshes == 2
    if kind == "observation":
        assert len(f.s.new) == 2
        pointer = next(v for v in f.s.new if isinstance(v, writer.models.ObservationCurrent))
        assert pointer.anchor_snapshot == row.anchor_snapshot
        assert pointer.anchor_snapshot is not row.anchor_snapshot
        assert all(
            getattr(pointer, column.key) is not None
            for column in pointer.__table__.columns
            if not column.nullable and column.server_default is None
        )
        assert row.fact_body["body"]["records"][0]["raw_material"]["value"] is None
        assert row.fact_body["body"]["records"][0]["missing_fields"] == ["value"]
        assert row.fact_body["body"]["records"][0]["occurred_at"].endswith("Z")
    else:
        assert len(f.s.new) == 1
        assert row.fact_body["body"]["conclusion"] == "unknown"
        assert row.fact_body["body"]["participants"][0]["id"] != str(f.ctx.actor_id)
    assert phase not in f.host._phases
    rejects("FACT_OPAQUE_PHASE_REQUIRED", lambda: apply(f, phase, consumed))
    f.s.close()


def test_rule_only_host_appends_null_public_proof_and_never_full_atom(monkeypatch):
    f = make_world(monkeypatch, "rule")
    phase = prepared(f)
    intent = digest(
        {
            "operation": f.command.operation,
            "category": f.command.category_id,
            "product": f.command.product_id,
            "payload": commands.semantic(f.payload),
            "named_actor": f.ctx.requester_id,
            "source_revision": None,
            "private_owner": None,
        }
    )
    row = writer.append_prepared_rule(
        f.s,
        f.ctx,
        f.command,
        f.product,
        f.payload,
        phase,
        host=f.host,
        module=commands,
        common_intent_digest=intent,
    )
    assert row.status == "published" and row.external_id == f.payload.external_id
    assert len(f.s.new) == 2 and row.series_id == row.id
    pointer = next(v for v in f.s.new if isinstance(v, writer.models.RuleCurrent))
    assert pointer.anchor_snapshot == row.anchor_snapshot
    assert pointer.anchor_snapshot is not row.anchor_snapshot
    assert all(
        getattr(pointer, column.key) is not None
        for column in pointer.__table__.columns
        if not column.nullable and column.server_default is None
    )
    assert all(
        getattr(row, key) is None
        for key in (
            "shared_proof_id",
            "proof_consumed_at",
            "shared_proof_revision",
            "proof_expires_at",
            "token_sha256",
            "material_sha256",
        )
    )
    assert row.intent_digest == intent
    assert row.payload_sha256 == body_payload_sha256(row.fact_body)
    assert decode_fact_body(row.fact_body).body.sampling.minimum_records == 2
    f.s.close()


def test_no_actual_owner_copied_phase_or_inactive_transaction_never_authorizes(monkeypatch):
    rejects("FACT_WRITE_OWNER_REQUIRED", lambda: writer.FactWriteHost(None))
    f = make_world(monkeypatch)
    phase = prepared(f)
    rejects(
        "FACT_OPAQUE_PHASE_REQUIRED",
        lambda: f.host.require(f.s, f.ctx, f.product.id, f.payload, replace(phase)),
    )
    product_id = f.product.id
    f.s.rollback()
    rejects(
        "FACT_ACTIVE_TRANSACTION_REQUIRED",
        lambda: f.host.require(f.s, f.ctx, product_id, f.payload, phase),
    )
    f.s.close()


def test_new_current_cas_is_separate_from_replay_current_permission(monkeypatch):
    f = make_world(monkeypatch)
    f.payload = f.payload.model_copy(
        update={"expected_issue_revision": f.payload.expected_issue_revision - 1}
    )
    # The actual owner substitute observes the same requested semantic object.
    f.host.owner.read = lambda *_, **__: f.material
    phase = prepared(f, new_write=False)
    assert phase.new_write is False
    rejects("VERSION_CONFLICT", lambda: prepared(f, new_write=True))
    f.person.active = False
    rejects("FORBIDDEN_SCOPE", lambda: prepared(f, new_write=False))
    f.s.close()


@pytest.mark.parametrize("kind", ["observation", "rule"])
def test_existing_series_cannot_be_bypassed_by_new_uuid_without_previous(monkeypatch, kind):
    f = make_world(monkeypatch, kind)
    monkeypatch.setattr(writer, "_initial_series_exists", lambda *_: True)
    rejects("FACT_SERIES_CONFLICT", lambda: prepared(f))
    assert not f.s.new
    # Historical replay does not pretend the original first version is a new
    # series. Its current permissions and actual owner still run independently.
    assert prepared(f, new_write=False).new_write is False
    f.s.close()


def test_private_project_and_private_source_cannot_be_shared(monkeypatch):
    f = make_world(monkeypatch)
    f.project.visibility = "private"
    rejects("FORBIDDEN_SCOPE", lambda: prepared(f))
    f.project.visibility = "category"
    raw = f.material.model_dump(mode="json")
    raw["body_material"]["source_basis"][0]["visibility"] = "private"
    f.host.owner.read = lambda *_, **__: writer.FactWriteMaterial.model_validate(raw)
    rejects("FACT_AUDIENCE_MISMATCH", lambda: prepared(f))
    f.s.close()


@pytest.mark.parametrize("change", ["runtime", "principal", "project", "current", "expiry"])
def test_all_owner_io_has_final_runtime_current_private_acl_and_clock_guards(monkeypatch, change):
    f = make_world(monkeypatch)

    def change_during_refresh():
        if change == "runtime":
            f.state.epoch += 1
        elif change == "principal":
            f.person.access_epoch += 1
        elif change == "project":
            f.project.visibility = "private"
        elif change == "current":
            f.current.epoch += 1
        else:
            f.clock.at = min(f.material.time_constraints)

    f.state.hook = change_during_refresh
    expected = "FORBIDDEN_SCOPE" if change == "project" else "SOURCE_STALE"
    rejects(expected, lambda: prepared(f))
    assert not f.s.new
    f.s.close()


def test_full_review_and_last_io_proof_expiry_cannot_save(monkeypatch):
    f = make_world(monkeypatch)
    phase = prepared(f)
    consumed = consume(f, phase)
    consumed[0].snapshot["inspection"]["outcome"] = "pass"
    rejects("FACT_REVIEW_MATERIAL_CHANGED", lambda: apply(f, phase, consumed))
    assert not f.s.new
    consumed[0].snapshot = writer.reviewed_fact(phase, host=f.host)
    f.state.hook = lambda: setattr(f.clock, "at", consumed[0].expires_at)
    rejects("FACT_CONSUMPTION_CLOCK_INVALID", lambda: apply(f, phase, consumed))
    assert not f.s.new
    f.s.close()


def test_review_of_own_actual_participation_is_not_independent(monkeypatch):
    f = make_world(monkeypatch, "review")
    raw = f.material.model_dump(mode="json")
    raw["body_material"]["participants"][0]["id"] = str(f.ctx.actor_id)
    f.host.owner.read = lambda *_, **__: writer.FactWriteMaterial.model_validate(raw)
    rejects("INDEPENDENT_REVIEWER_REQUIRED", lambda: prepared(f))
    assert not f.s.new
    f.s.close()


def test_final_pointer_io_cannot_skip_fresh_caller_revocation(monkeypatch):
    f = make_world(monkeypatch)
    phase = prepared(f)
    consumed = consume(f, phase)
    checks = 0

    def last_series(*_):
        nonlocal checks
        checks += 1
        if checks == 2:  # apply's pointer IO after its full owner refresh
            f.person.active = False
        return False

    monkeypatch.setattr(writer, "_initial_series_exists", last_series)
    rejects("FORBIDDEN_SCOPE", lambda: apply(f, phase, consumed))
    assert checks == 2 and not f.s.new
    f.s.close()


def test_known_next_activation_deadline_is_exclusive_even_after_serialization(monkeypatch):
    f = make_world(monkeypatch)
    f.material = writer.FactWriteMaterial.model_validate(
        {**f.material.model_dump(), "time_constraints": (f.clock.at + timedelta(minutes=5),)}
    )
    f.host.owner.read = lambda *_, **__: f.material
    f.host.owner.refresh = lambda *_, **__: f.material
    phase = prepared(f)
    consumed = consume(f, phase)
    construct = writer._construct_row

    def crosses_next_activation(*args):
        row = construct(*args)
        f.clock.at = min(phase.material.time_constraints)
        return row

    monkeypatch.setattr(writer, "_construct_row", crosses_next_activation)
    rejects("SOURCE_STALE", lambda: apply(f, phase, consumed))
    assert not f.s.new
    f.s.close()


def test_agent_context_rejects_before_material_owner_io(monkeypatch):
    f = make_world(monkeypatch)
    invalid = Context(f.ctx.tenant_id, uid("agent"), f.ctx.requester_id, uid("agent-run"))
    rejects(
        "FORBIDDEN_SCOPE",
        lambda: writer.prepare_fact(f.s, invalid, f.product.id, f.payload, host=f.host),
    )
    assert f.state.reads == 0 and f.state.refreshes == 0 and not f.s.new
    f.s.close()


@pytest.mark.parametrize("kind", ["rule", "observation"])
def test_successor_advances_exact_existing_series_without_erasing_previous_full_ref(
    monkeypatch, kind
):
    f = make_world(monkeypatch, kind)
    previous = {
        "id": str(uid("actual-prior-" + kind)),
        "revision": 1,
        "sha256": digest("real owner substituted prior full group"),
    }
    raw = f.material.model_dump(mode="json")
    raw["body_material"]["previous"] = previous
    raw["series"] = {
        "id": str(uid("existing-pointer-" + kind)),
        "series_id": previous["id"],
        "fact": previous,
        "epoch": 4,
    }
    f.material = writer.FactWriteMaterial.model_validate(raw)
    payload = f.payload.model_dump(mode="json")
    payload["previous"] = previous
    f.payload = commands.payload_for(kind, payload)
    f.command = f.command.model_copy(update={"payload": f.payload.model_dump(mode="json")})
    f.host.owner.read = lambda *_, **__: f.material
    f.host.owner.refresh = lambda *_, **__: f.material
    b, series = f.material.body_material, f.material.series
    values = {
        "id": series.id,
        "tenant_id": b.scope.tenant_id,
        "product_id": b.scope.product_id,
        "project_id": b.scope.project_id,
        "origin_issue_version_id": f.fixed.origin.ref.id,
        "origin_issue_revision": f.fixed.origin.ref.revision,
        **{k: getattr(b, k) for k in writer.models.BINDING if hasattr(b, k)},
        "series_id": series.series_id,
        "fact_id": series.fact.id,
        "fact_revision": series.fact.revision,
        "epoch": series.epoch,
    }
    cls = writer.models.RuleCurrent if kind == "rule" else writer.models.ObservationCurrent
    if kind == "rule":
        values.update(
            issuer_key=b.issuer.key,
            issuer_version=b.issuer.version,
            external_id=f.payload.external_id,
        )
    pointer = cls(**values)
    make_transient_to_detached(pointer)
    f.s.add(pointer)
    f.rows[cls] = pointer
    if kind == "observation":
        f.rows[writer.models.ObservationFact] = writer.models.ObservationFact(
            id=series.fact.id,
            tenant_id=b.scope.tenant_id,
            product_id=b.scope.product_id,
            revision=series.fact.revision,
            rule_fact_id=b.rule.id,
            rule_revision=b.rule.revision,
            rule_sha256=b.rule.sha256,
            executor_id=b.executor_id,
            issuer_key=b.issuer.key,
        )
    phase = prepared(f)
    if kind == "observation":
        row = apply(f, phase, consume(f, phase))
    else:
        intent = digest(
            {
                "operation": f.command.operation,
                "category": f.command.category_id,
                "product": f.command.product_id,
                "payload": commands.semantic(f.payload),
                "named_actor": f.ctx.requester_id,
                "source_revision": None,
                "private_owner": None,
            }
        )
        row = writer.append_prepared_rule(
            f.s,
            f.ctx,
            f.command,
            f.product,
            f.payload,
            phase,
            host=f.host,
            module=commands,
            common_intent_digest=intent,
        )
    assert row.revision == 2 and row.series_id == series.series_id
    assert row.previous_fact_id == series.fact.id and row.previous_revision == 1
    assert pointer.fact_id == row.id and pointer.fact_revision == 2 and pointer.epoch == 5
    assert decode_fact_body(row.fact_body).body.previous.sha256 == previous["sha256"]
    assert len(f.s.new) == 1
    f.s.close()
