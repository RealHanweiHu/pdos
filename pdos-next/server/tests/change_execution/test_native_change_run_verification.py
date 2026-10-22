"""Native Change mapping over the real original-value/result bridge, with IO seams."""

# ruff: noqa: F811 -- imported pytest fixture is also a parameter name

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_quality_result_bridge_reuse import (
    archive,  # noqa: F401 -- real typed Run/original fixture
)

import pdos_next.models  # noqa: F401 -- model registration precedes domain imports
from pdos_next import change_run_verification as owner
from pdos_next.domain.change_control.rules import digest as change_digest
from pdos_next.schemas.change_control.contracts import (
    ChangeOrder,
    ChangeRequest,
    ControlledIntent,
    Disposition,
    EffectivityFact,
    EffectivityPlan,
    ImplementationFact,
    PlanItem,
    Ref,
    Selection,
)
from pdos_next.service import digest


@pytest.fixture
def native(archive, monkeypatch):
    run = archive.run
    for record in archive.records:
        record.sample_id = record.measurement["coverage"]["sample_id"]
        record.sample_id = next(v.id for v in run.samples if str(v.id) == record.sample_id)
        record.item_id = record.measurement["coverage"]["item_id"]
    source = run.measurements[0].source
    output_refs = (
        Ref(kind="engineering_configuration", **run.build.engineering_configuration.model_dump()),
        Ref(
            kind="manufacturing_configuration", **run.build.manufacturing_configuration.model_dump()
        ),
    )
    items, implemented, effective = [], [], []
    for output, discipline in zip(output_refs, ("engineering", "manufacturing"), strict=True):
        previous = Ref(kind=output.kind, id=uuid4(), revision=1)
        item = PlanItem(
            id=uuid4(),
            discipline=discipline,
            selection=Selection(
                objects=(previous,),
                units=(f"object:{previous.identity}",),
                conditions=("Explicit development configuration object only",),
                sources=(source,),
            ),
            intent=ControlledIntent(
                id=uuid4(),
                kind=f"new_{output.kind}",
                basis=(previous,),
                description="New fixed config",
            ),
            verification_requirement="Named applicability to the actual measured item and method",
        )
        common = dict(
            id=uuid4(),
            item_id=item.id,
            intent_id=item.intent.id,
            outcome="succeeded",
            occurred_at=run.actual_start.occurred_at - timedelta(seconds=1),
            received_at=run.actual_start.occurred_at,
            sources=(source,),
            nature="synthetic",
        )
        implemented.append(
            ImplementationFact(
                **common, executor_id=uuid4(), outputs=(output,), note="Actual output"
            )
        )
        effective.append(
            EffectivityFact(
                **common,
                stage="effective",
                covered_units=item.selection.units,
                conditions_digest=change_digest(item.selection),
                output_refs=(output,),
                system="native-development-build",
                external_id=str(run.build.id),
            )
        )
        items.append(item)
    plan = EffectivityPlan(
        id=uuid4(),
        items=tuple(items),
        dispositions=tuple(
            Disposition(
                object=item.selection.objects[0],
                handling="covered_by_plan",
                item_ids=(item.id,),
                rationale="Explicit fixed object",
                sources=(source,),
            )
            for item in items
        ),
    )
    order = ChangeOrder(
        id=uuid4(),
        assessment_id=uuid4(),
        assessment_digest="fixed-assessment",
        plan=plan,
        policy=source,
        required_disciplines=("engineering", "manufacturing"),
        content_digest="fixed",
        implementations=tuple(implemented),
        effectivity=tuple(effective),
    )
    request = ChangeRequest(
        id=uuid4(),
        revision=1,
        scope=run.scope,
        audience=(f"private:{archive.row.owner_id}",),
        requester_id=uuid4(),
        title="Native Field change",
        reason="Fixed native change",
        roots=(items[0].selection.objects[0],),
        references=(),
        sources=(source,),
        orders=(order,),
    )
    build = SimpleNamespace(
        id=run.build.id,
        revision=run.build.revision,
        tenant_id=run.scope.tenant_id,
        product_id=run.scope.product_id,
        project_id=run.scope.project_id,
        engineering_configuration_id=run.build.engineering_configuration.id,
        manufacturing_configuration_id=run.build.manufacturing_configuration.id,
    )
    views = tuple(
        dict(
            id=str(ref.id),
            revision=ref.revision,
            owner_id=str(archive.ctx.requester_id),
            visibility="private",
            source_status="current",
        )
        for ref in output_refs
    )
    current_request = SimpleNamespace(
        **{
            **vars(archive.request_row),
            "request_snapshot": {
                **archive.request_row.request_snapshot,
                "items": [i.model_dump(mode="json") for i in run.items],
            },
        }
    )
    current_request.snapshot_sha256 = digest(current_request.request_snapshot)
    monkeypatch.setattr(
        owner.launch, "_current", lambda *_: (SimpleNamespace(epoch=1), archive.row)
    )
    monkeypatch.setattr(
        owner.front, "_current", lambda *_: (SimpleNamespace(epoch=1), current_request)
    )
    monkeypatch.setattr(owner.builds, "_build", lambda *_: build)
    monkeypatch.setattr(
        owner.builds,
        "_linked",
        lambda *_: (
            SimpleNamespace(id=run.scope.project_id),
            *views,
            archive.row.required_source_read_set,
        ),
    )
    mapping = tuple(
        owner.RunScopeMapping(
            item_id=item.id,
            run=Ref(kind="test_run", id=run.id, revision=run.revision),
            sample_id=run.coverage[0].sample_id,
            test_item_id=run.coverage[0].item_id,
            method=run.items[0].method,
            requirement_sha256=change_digest(item.verification_requirement),
            rationale="Named selection of this requirement against this exact method and pair",
        )
        for item in items
    )
    return SimpleNamespace(
        archive=archive,
        request=request,
        order=order,
        mappings=mapping,
        build=build,
        views=views,
        at=run.actual_end.occurred_at + timedelta(seconds=1),
        fact_id=uuid4(),
        current_request=current_request,
    )


def read(native, **changes):
    args = dict(
        request=native.request,
        order=native.order,
        mappings=native.mappings,
        fact_id=native.fact_id,
        at=native.at,
    )
    args.update(changes)
    archive = native.archive
    return owner.read_verification(archive.session, archive.ctx, archive.product_id, **args)


def test_actual_complete_run_not_capa_drives_result_executors_window_and_stable_fact(native):
    value = read(native)
    run = native.archive.run
    assert value.fact.result == run.result == "fail"
    assert value.fact.executor_ids == (run.execution.executor_id,)
    assert value.fact.observed_from == value.fact.observed_until == run.measurements[0].observed_at
    assert value.fact.nature == "synthetic" and value.fact.applicable and value.fact.current
    assert set(value.fact.item_ids) == {i.id for i in native.order.plan.items}
    assert len(native.archive.state.byte_calls) == 1  # both item mappings share one actual Run read
    assert {r.kind for r in value.actual_refs} >= {"build", "test_run", "sample"}
    assert all(s.kind == "domain" for s in value.verified_domain_sources)
    assert "checked_at" not in str(value.provenance) and "runtime_stamp" not in str(
        value.provenance
    )
    later = read(native, at=native.at + timedelta(hours=1))
    assert later.fact == value.fact and later.provenance == value.provenance


def test_requirement_sha_uses_the_pure_change_digest_and_mismatch_does_not_read_bytes(native):
    text = native.order.plan.items[0].verification_requirement
    assert change_digest(text) != digest(text)
    mappings = (
        native.mappings[0].model_copy(update={"requirement_sha256": digest(text)}),
        *native.mappings[1:],
    )
    with pytest.raises(owner.DomainError, match="固定验证要求"):
        read(native, mappings=mappings)
    assert native.archive.state.byte_calls == []


@pytest.mark.parametrize("change", ["missing", "duplicate", "different_method", "wrong_pair"])
def test_explicit_applicability_cannot_be_replaced_by_same_project_configuration(native, change):
    mappings = list(native.mappings)
    if change == "missing":
        mappings.pop()
    elif change == "duplicate":
        mappings.append(mappings[0])
    elif change == "different_method":
        mappings[0] = mappings[0].model_copy(
            update={"method": mappings[0].method.model_copy(update={"id": uuid4()})}
        )
    else:
        mappings[0] = mappings[0].model_copy(update={"sample_id": uuid4()})
    with pytest.raises(owner.DomainError):
        read(native, mappings=mappings)


def test_real_build_must_contain_actual_implemented_output_and_not_merely_a_matching_title(native):
    native.build.engineering_configuration_id = uuid4()
    with pytest.raises(owner.DomainError, match="实际项目/双配置"):
        read(native)


def test_changed_current_run_rejects_before_original_io(native, monkeypatch):
    row = SimpleNamespace(id=uuid4(), revision=native.archive.run.revision + 1)
    monkeypatch.setattr(owner.launch, "_current", lambda *_: (SimpleNamespace(epoch=2), row))
    with pytest.raises(owner.DomainError, match="当前固定版本"):
        read(native)
    assert native.archive.state.byte_calls == []


def test_unknown_executor_or_time_in_actual_original_cannot_certify_complete_verification(native):
    record = native.archive.records[-1]
    record.verified_observation["observation"]["executor_id"] = None
    with pytest.raises(owner.DomainError):
        read(native)


def test_original_tamper_and_terminal_source_change_fail_through_real_bridge(native):
    native.archive.state.content = native.archive.state.content.replace(b'"3"', b'"9"')
    with pytest.raises(owner.DomainError):
        read(native)


def test_original_verifier_is_host_bound_and_does_not_replace_the_caller_acl(native, monkeypatch):
    original, callers = uuid4(), []
    real = owner.bridge.fixed_failure_result

    def capture(s, ctx, pid, **kwargs):
        callers.append(ctx)
        return real(s, ctx, pid, **kwargs)

    monkeypatch.setattr(owner.bridge, "fixed_failure_result", capture)
    result = read(native, verifier_id=original)
    assert result.fact.verifier_id == original and callers == [native.archive.ctx]
    # Public mappings cannot carry any owner-derived fact or historical signer.
    with pytest.raises(ValidationError):
        owner.RunScopeMapping.model_validate(
            {**native.mappings[0].model_dump(), "verifier_id": original}
        )


def test_private_run_audience_cannot_be_widened_by_an_authorized_reader(native):
    request = native.request.model_copy(
        update={"audience": (f"product:{native.archive.product_id}",)}
    )
    with pytest.raises(owner.DomainError, match="私有运行或配置"):
        read(native, request=request)


def test_original_observed_window_cannot_be_replaced_by_review_time(native):
    with pytest.raises(owner.DomainError, match="未来观测"):
        read(native, at=native.archive.run.actual_start.occurred_at)


def test_no_public_ai_or_second_actor_substitution(native, monkeypatch):
    archive = native.archive
    archive.ctx = replace(archive.ctx, actor_id=uuid4(), run_id=uuid4())

    def human(s, ctx, pid, **kwargs):
        assert ctx is archive.ctx
        raise owner.DomainError("NAMED_DECISION_REQUIRED", "Actual human owner denied", 403)

    monkeypatch.setattr(owner.launch, "_human", human)
    with pytest.raises(owner.DomainError, match="Actual human owner denied"):
        read(native)
    assert archive.state.byte_calls == []
