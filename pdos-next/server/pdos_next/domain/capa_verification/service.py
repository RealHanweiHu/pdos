"""Read-only fixed owner resolution in the caller UOW; never creates an execution."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import category_for_product
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution import service as quality
from pdos_next.domain.quality_execution.evidence import merge_reads, refs_from_exact, source_basis
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, now
from pdos_next.request_proof import request_proof, scope_is_held
from pdos_next.service import digest

from .schemas import (
    ActionBinding,
    CandidateBinding,
    CandidateInspect,
    FixedRef,
    FollowupBasis,
    Missing,
    OutputReading,
    OutputRef,
    ResolvedOutputs,
    SourceRead,
)


def _at(value):
    value = now() if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("INVALID_TIME", "复验读取时点须含明确时区。", 422)
    if value > now():
        raise DomainError("INVALID_TIME", "不能使用未来读取时点声明当前依据。", 422)
    return value.astimezone(UTC)


def _missing(dimension, code, detail, *, output=None, failure=None):
    return Missing(
        dimension=dimension, code=code, detail=detail, output_ref=output, failure_id=failure
    )


def _reads(*groups):
    return tuple(SourceRead.model_validate(value) for value in merge_reads(*groups))


def _basis_digest(value):
    return digest(value.model_dump(mode="json", exclude={"basis_sha256"}))


def _basis_material(value):
    """Version-only aggregate additions do not rewrite the fixed CAPA semantics."""
    return value.model_dump(
        mode="json", exclude={"issue_version_id", "issue_revision", "basis_sha256"}
    )


def basis_from_issue(row, issue, *, sources, reads, source_basis):
    """Pure server projection shared with follow-up adapters; it confers no permission."""
    if issue.capa is None or issue.merged_into or issue.needs_recheck:
        raise DomainError("RECHECK_REQUIRED", "需固定未归并、无待重核的真实CAPA。")
    if (row.issue_id, row.id, row.revision, row.tenant_id, row.product_id, row.project_id) != (
        issue.id,
        row.id,
        issue.revision,
        issue.scope.tenant_id,
        issue.scope.product_id,
        issue.scope.project_id,
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定Issue身份与保存聚合不能核对。")
    if digest(issue.model_dump(mode="json")) != row.snapshot_sha256:
        raise DomainError("INTEGRITY_MISMATCH", "固定Issue原聚合摘要不能核对。")
    natures = {failure.nature for failure in issue.failures}
    if len(natures) != 1:
        raise DomainError("INTEGRITY_MISMATCH", "真实/合成失败不能拼成同一复验性质。")
    actions = tuple(
        ActionBinding(
            action_id=action.id,
            executor_id=action.executor_id,
            action_sha256=digest(action.model_dump(mode="json", exclude={"completion"})),
            completion_sha256=digest(action.completion.model_dump(mode="json"))
            if action.completion
            else None,
            completed_at=action.completion.at if action.completion else None,
        )
        for action in issue.capa.actions
    )
    value = FollowupBasis(
        scope=issue.scope,
        issue_id=issue.id,
        issue_version_id=row.id,
        issue_revision=row.revision,
        capa_id=issue.capa.id,
        purpose=row.purpose,
        owner_id=row.owner_id,
        visibility=row.visibility,
        nature=next(iter(natures)),
        requirement=issue.capa.requirement,
        requirement_sha256=digest(issue.capa.requirement.model_dump(mode="json")),
        failure_ids=tuple(sorted(f.identity for f in issue.failures)),
        failure_basis_sha256=digest([f.model_dump(mode="json") for f in issue.failures]),
        actions=actions,
        root_cause_sha256=digest(issue.root_cause.model_dump(mode="json"))
        if issue.root_cause
        else None,
        sources=sources,
        required_source_read_set=_reads(reads),
        source_basis_sha256=digest(source_basis),
        basis_sha256="0" * 64,
    )
    return value.model_copy(update={"basis_sha256": _basis_digest(value)})


def _snapshot_basis_context(s, ctx, product_id, row):
    if not (
        isinstance(s, Session) and s.info.get("read_snapshot") and scope_is_held(s, product_id)
    ):
        return None
    from pdos_next.database import require_context
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow
    from pdos_next.quality_result_bridge import _runtime_stamp

    require_context(s, ctx)
    proof = request_proof(s)
    key = (
        "capa-fixed-followup-basis",
        _uow(s),
        proof.mutation_epoch,
        digest(vars(ctx)),
        digest(s.info.get("scope")),
        product_id,
        row.id,
        row.revision,
        digest({column.key: getattr(row, column.key) for column in row.__mapper__.column_attrs}),
        _runtime_stamp(s),
        id(quality._result),
        id(quality._human),
        id(quality._row),
        id(quality._snapshot),
        id(source_basis),
    )
    return proof, key


def load_exact_followup_basis(s, ctx, product_id, issue_id, revision, *, write=False):
    """Recheck a genuine fixed version, without a new-write Current CAS requirement."""
    from pdos_next.domain.quality_execution.evidence import union_sources
    from pdos_next.domain.quality_issues.rules import failure_ref

    quality._human(s, ctx, product_id, write=write)
    revision = FixedRef(id=issue_id, revision=revision).revision
    row = quality._row(s, ctx, product_id, issue_id, revision)
    issue = quality._snapshot(row)
    context = None if write else _snapshot_basis_context(s, ctx, product_id, row)
    if context is not None:
        proof, key = context
        if key in proof.scalar_rows:
            # An immutable serialization keeps later DTO edits out of the held
            # proof. Scope/caller, exact Issue and runtime are checked above;
            # Current/CAS and the host's terminal clocks remain outside it.
            return FollowupBasis.model_validate(json.loads(proof.scalar_rows[key]))
    values = []
    for failure in issue.failures:
        value = quality._result(
            s,
            ctx,
            product_id,
            run_id=failure.run.id,
            measurement_id=failure.measurement_id,
            run_revision=failure.run.revision,
        )
        if failure_ref(value.verified, failure.measurement_id) != failure:
            raise DomainError("RECHECK_REQUIRED", "原失败固定方法、配置、测量或来源已改变。")
        values.append(value)
    reads = _reads(row.required_source_read_set, *(v.required_source_read_set for v in values))
    evidence, _ = source_basis(s, ctx, product_id, reads)
    value = basis_from_issue(
        row,
        issue,
        sources=union_sources(row.sources, *(v.sources for v in values)),
        reads=reads,
        source_basis=evidence,
    )
    if context is not None:
        proof, key = context
        final = _snapshot_basis_context(s, ctx, product_id, row)
        if final is not None and final[0] is proof and final[1] == key:
            proof.scalar_rows[key] = json.dumps(value.model_dump(mode="json"), sort_keys=True)
    return value


def load_followup_basis(s, ctx, product_id, issue_id, expected_issue_revision, *, write=False):
    """Return a current server-derived anchor; old replay uses the exact loader instead."""
    from pdos_next.domain.quality_execution.models import QualityIssueCurrent

    revision = FixedRef(id=issue_id, revision=expected_issue_revision).revision
    quality._human(s, ctx, product_id, write=write)
    pointer = s.scalar(
        select(QualityIssueCurrent).where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product_id,
            QualityIssueCurrent.issue_id == issue_id,
        )
    )
    if pointer is None or pointer.issue_revision != revision:
        raise DomainError("VERSION_CONFLICT", "当前Issue聚合版已推进，请重新核对整改范围。")
    value = load_exact_followup_basis(s, ctx, product_id, issue_id, revision, write=write)
    if value.issue_version_id != pointer.issue_version_id:
        raise DomainError("INTEGRITY_MISMATCH", "当前Issue精确指针与版行不一致。")
    return value


def recheck_followup_basis(s, ctx, product_id, basis, *, write=False):
    """Recheck current semantic basis; client hashes never substitute for owner reads."""
    from pdos_next.domain.quality_execution.models import QualityIssueCurrent

    basis = FollowupBasis.model_validate(basis)
    if basis.scope.tenant_id != ctx.tenant_id or basis.scope.product_id != product_id:
        raise DomainError("FORBIDDEN_SCOPE", "整改依据不在当前租户型号范围。", 403)
    if basis.basis_sha256 != _basis_digest(basis):
        raise DomainError("INTEGRITY_MISMATCH", "固定整改依据摘要不能核对。")
    # A historical version must genuinely exist and have the same fixed identity.
    old = load_exact_followup_basis(
        s, ctx, product_id, basis.issue_id, basis.issue_revision, write=write
    )
    if old != basis:
        raise DomainError("FORBIDDEN_SCOPE", "固定Issue版行与整改范围不一致。", 403)
    pointer = s.scalar(
        select(QualityIssueCurrent).where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product_id,
            QualityIssueCurrent.project_id == basis.scope.project_id,
            QualityIssueCurrent.issue_id == basis.issue_id,
        )
    )
    if pointer is None:
        raise DomainError("RECHECK_REQUIRED", "固定Issue当前指针不存在。")
    if (pointer.issue_version_id, pointer.issue_revision) == (
        old.issue_version_id,
        old.issue_revision,
    ):
        return old  # exact failure/source checks above have just completed in this phase
    current = load_followup_basis(
        s, ctx, product_id, basis.issue_id, pointer.issue_revision, write=write
    )
    if _basis_material(current) != _basis_material(basis):
        raise DomainError("RECHECK_REQUIRED", "CAPA措施、要求、失败或安全来源依据已改变。")
    return current


def _fixed_row(s, ctx, product_id, model, ref):
    row = s.scalar(
        select(model).where(
            model.tenant_id == ctx.tenant_id,
            model.product_id == product_id,
            model.id == ref.id,
        )
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "整改输出不在当前可读范围。", 403)
    if row.revision != ref.revision:
        raise DomainError("VERSION_CONFLICT", "必须选择输出实际不可变版行与版本。")
    return row


def _owner(s, ctx, product_id, ref):
    """Existing owner APIs perform identity, ancestry and private/source ACL guards."""
    from pdos_next.domain.build_execution import service as execution
    from pdos_next.domain.builds import service as builds
    from pdos_next.domain.configurations import service as configurations

    if ref.kind == "definition":
        return configurations._definition(s, ctx, product_id, ref.id)
    if ref.kind in {"bom", "engineering_configuration", "manufacturing_configuration"}:
        function = {
            "bom": configurations.get_bom,
            "engineering_configuration": configurations.get_engineering,
            "manufacturing_configuration": configurations.get_process,
        }[ref.kind]
        return function(s, ctx, product_id, ref.id)
    if ref.kind == "build":
        row = builds._build(s, ctx, product_id, ref.id)
        _, engineering, manufacturing, reads = builds._linked(s, ctx, product_id, row)
        return row, dict(
            id=str(row.id),
            revision=row.revision,
            name=row.name,
            status=row.status,
            owner_id=str(row.owner_id),
            visibility=row.visibility,
            project_id=str(row.project_id),
            purpose=row.purpose,
            engineering_configuration=engineering,
            manufacturing_configuration=manufacturing,
            required_source_read_set=reads,
            source_status="current"
            if all(v["source_status"] == "current" for v in (engineering, manufacturing))
            else "needs_recheck",
        )
    if ref.kind in {"actual_configuration", "build_lot", "sample"}:
        return {
            "actual_configuration": execution.get_actual_configuration,
            "build_lot": execution.get_lot,
            "sample": execution.get_sample,
        }[ref.kind](s, ctx, product_id, ref.id)
    if ref.kind == "verification_preparation":
        from pdos_next.domain.verification_execution.service import get_preparation

        return get_preparation(s, ctx, product_id, ref.id)
    if ref.kind == "verification_request":
        from pdos_next.domain.verification_front.service import get_request

        row, view = get_request(s, ctx, product_id, ref.id, assess_capabilities=False)
        # The UI also publishes reads for actions the current caller could take.
        # Fixed output material retains the saved parent and its actual children,
        # while get_request keeps their current source/professional checks intact.
        fixed_reads = _reads(
            row.required_source_read_set,
            *(child["required_source_read_set"] for child in view["method_assessments"]),
            *(child["required_source_read_set"] for child in view["window_proposals"]),
        )
        return row, {
            **view,
            "required_source_read_set": [read.model_dump(mode="json") for read in fixed_reads],
        }
    if ref.kind == "verification_run":
        from pdos_next.domain.test_resources.retained import inspect_retained_execution
        from pdos_next.domain.verification_launch import service as launch
        from pdos_next.domain.verification_launch.models import VerificationRunVersion

        row = _fixed_row(s, ctx, product_id, VerificationRunVersion, ref)
        run, plan = launch._snapshot(row)
        state = launch._read_evidence(s, ctx, product_id, row)
        retained = None
        if run.status != "planned":
            retained = inspect_retained_execution(s, ctx, product_id, row, write=False)
            if retained.get("current") is not True:
                raise DomainError("RECHECK_REQUIRED", "新Run的实际执行与消费证明需要重核。")
        _, current = launch._current(s, ctx, product_id, run_id=run.id)
        view = dict(
            id=str(row.id),
            revision=row.revision,
            run_id=str(run.id),
            status=run.status,
            title=f"测试Run v{row.revision}",
            run=run.model_dump(mode="json"),
            execution_plan=plan.model_dump(mode="json"),
            required_source_read_set=merge_reads(
                row.required_source_read_set,
                retained["required_source_read_set"] if retained else (),
            ),
            source_status=state,
            is_current=current is not None and current.id == row.id,
            source_nature=retained.get("source_nature") if retained else None,
            retained={
                key: value
                for key, value in retained.items()
                if key not in {"checked_at", "execution_window_elapsed"}
            }
            if retained
            else None,
        )
        return row, view
    raise DomainError("INTEGRATION_REQUIRED", "该整改输出owner读取接口未接通。", 503)


def _reading(s, ctx, product_id, basis, ref):
    paired = _paired_output(s, ctx, product_id, basis, ref)
    if paired is not None:
        return paired.output
    return _direct_reading(s, ctx, product_id, basis, ref)


def _paired_output(s, ctx, product_id, basis, ref, *, previous=None, write=False):
    """Only actual paired Formal operations use the startup-owned reader.

    The returned opaque object is confined to this call stack. It is never
    inserted into OutputReading, source JSON, Session.info or a shared cache.
    """
    if ref.kind != "verification_request" or s is None:
        return None
    from pdos_next.domain.verification_front.models import FormalVerificationRequest

    row = _fixed_row(s, ctx, product_id, FormalVerificationRequest, ref)
    if row.operation not in {
        "verification.schedule.promise",
        "test.run.start",
        "test.results.import",
        "test.run.review",
        "test.disposition.decide",
    }:
        if previous is not None:
            raise DomainError("SOURCE_STALE", "配对输出的原保存操作发生变化。")
        return None
    from pdos_next import paired_followup_adapter

    owner = paired_followup_adapter.configured(s)
    if owner is None:
        raise DomainError("INTEGRATION_REQUIRED", "配对Formal的真实owner读取接口尚未接通。", 503)
    if ref.key is not None:
        raise DomainError("FORBIDDEN_SCOPE", "配对Formal不能使用BOM或工序key。", 403)
    value = (
        owner.read(s, ctx, product_id, basis, ref, write=write)
        if previous is None
        else owner.refresh(s, ctx, product_id, basis, ref, previous, write=write)
    )
    if (
        not isinstance(value.output, OutputReading)
        or value.output.ref != ref
        or value.output.project_id != basis.scope.project_id
        or (value.output.visibility == "private" and value.output.owner_id != ctx.requester_id)
    ):
        raise DomainError("INTEGRITY_MISMATCH", "实际配对owner未返回完整固定输出范围。")
    return value


def _read_output(s, ctx, product_id, basis, ref, *, write=False):
    """Return the unchanged public material and a private same-phase handle."""
    paired = _paired_output(s, ctx, product_id, basis, ref, write=write)
    if paired is not None:
        return paired.output, paired
    return _reading(s, ctx, product_id, basis, ref), None


def _refresh_output(s, ctx, product_id, basis, ref, previous, *, write=False):
    if previous is None:
        return _reading(s, ctx, product_id, basis, ref)
    paired = _paired_output(s, ctx, product_id, basis, ref, previous=previous, write=write)
    if paired is None:
        raise DomainError("SOURCE_STALE", "不能把原配对读取降级为直接回执读取。")
    return paired.output


def _direct_reading(s, ctx, product_id, basis, ref):
    row, view = _owner(s, ctx, product_id, ref)
    if (row.tenant_id, row.product_id, row.id, row.revision) != (
        ctx.tenant_id,
        product_id,
        ref.id,
        ref.revision,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "输出版本、租户或产品不能精确核对。", 403)
    if row.visibility == "private" and row.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "当前调用者不可读取私人整改输出。", 403)
    project_id = getattr(row, "project_id", None)
    if project_id is not None and project_id != basis.scope.project_id:
        raise DomainError("FORBIDDEN_SCOPE", "整改输出不能跨越Issue项目范围。", 403)
    if ref.key is not None:
        collection = view["lines"] if ref.kind == "bom" else view["operations"]
        selected = [item for item in collection if item["key"] == ref.key]
        if len(selected) != 1:
            raise DomainError("FORBIDDEN_SCOPE", "输出key必须存在于固定BOM或工序版本。", 403)
        view = {**view, "selected_key": ref.key, "selected": selected[0]}
    missing = []
    meaning = "draft"
    if ref.kind in {"build", "verification_preparation", "verification_request"}:
        meaning = "planned"
    elif ref.kind in {"actual_configuration", "build_lot", "sample"}:
        meaning = "observed"
    elif ref.kind == "verification_run":
        meaning = "planned" if row.status == "planned" else "performed"
        if meaning == "planned":
            missing.append(
                _missing(
                    "execution", "RUN_NOT_STARTED", "新Run仅为计划，尚无实际执行。", output=ref
                )
            )
    if view.get("is_current") is False:
        missing.append(
            _missing(
                "owner",
                "FIXED_OUTPUT_HISTORICAL",
                "输出为固定历史版，需相应owner重核。",
                output=ref,
            )
        )
    state = view.get("source_status", "current")
    if state != "current":
        state = "needs_recheck"
        missing.append(_missing("source", "SOURCE_STALE", "输出来源当前需要重核。", output=ref))
    # Mutable count projections do not become the fixed physical output identity.
    snapshot = {
        key: value
        for key, value in view.items()
        if key
        not in {
            "capabilities",
            "authority",
            "checked_at",
            "created_at",
            "identified_count",
            "remaining_unit_count",
            "build_observed_unit_count",
            "over_planned_quantity",
        }
    }
    raw_reads = view.get("required_source_read_set", getattr(row, "required_source_read_set", None))
    if raw_reads is None:
        raw_reads = [
            {"artifact_id": item["artifact_id"], "expected_revision": item["expected_revision"]}
            for item in view.get("sources", ())
        ]
    reads = _reads(raw_reads)
    if not reads:
        raise DomainError("INTEGRATION_REQUIRED", "输出缺少可核验的完整来源读集。", 503)
    evidence, _ = source_basis(s, ctx, product_id, reads)
    logical_id = (
        getattr(row, "run_id", None)
        if ref.kind == "verification_run"
        else (
            getattr(row, "request_id", None)
            if ref.kind in {"verification_preparation", "verification_request"}
            else None
        )
    )
    title = view.get("name") or view.get("title") or view.get("label") or view.get("lot_label")
    value = OutputReading(
        ref=ref,
        logical_id=logical_id,
        project_id=project_id,
        owner_id=row.owner_id,
        visibility=row.visibility,
        title=title or f"{ref.kind} v{row.revision}",
        status=view.get("status", row.status),
        meaning=meaning,
        source_status=state,
        snapshot=snapshot,
        required_source_read_set=reads,
        owner_basis_sha256=digest(
            {"ref": ref.model_dump(mode="json"), "snapshot": snapshot, "source_basis": evidence}
        ),
        missing=tuple(missing),
    )
    return value


def _unique_outputs(refs):
    refs = tuple(OutputRef.model_validate(ref) for ref in refs)
    if not refs:
        raise DomainError("INVALID_SCOPE", "回链需要精确输出。", 422)
    if len({(r.kind, r.id, r.revision, r.key) for r in refs}) != len(refs):
        raise DomainError("INVALID_SCOPE", "固定输出不能重复。", 422)
    return refs


def resolve_followup_outputs(
    s, ctx, product_id, basis, action_id, output_refs, *, at=None, write=False
):
    _at(at)
    current = recheck_followup_basis(s, ctx, product_id, basis, write=write)
    action = next((a for a in current.actions if a.action_id == action_id), None)
    if action is None:
        raise DomainError("FORBIDDEN_SCOPE", "回链须引用本固定CAPA的真实措施。", 403)
    refs = _unique_outputs(output_refs)
    owner_reads = tuple(_read_output(s, ctx, product_id, current, ref, write=write) for ref in refs)
    outputs = tuple(value for value, _ in owner_reads)
    reads = _reads(current.required_source_read_set, *(o.required_source_read_set for o in outputs))
    evidence, private_source = source_basis(s, ctx, product_id, reads)
    # Recheck the semantic/source anchor after owner I/O; no cross-phase proof cache.
    recheck_followup_basis(s, ctx, product_id, current, write=write)
    refreshed = tuple(
        _refresh_output(s, ctx, product_id, current, ref, handle, write=write)
        for ref, (_, handle) in zip(refs, owner_reads, strict=True)
    )
    if outputs != refreshed:
        raise DomainError("SOURCE_STALE", "读取期间输出身份、来源或执行证明发生变化。")
    after, _ = source_basis(s, ctx, product_id, reads)
    if evidence != after:
        raise DomainError("SOURCE_STALE", "读取期间整改来源安全依据发生变化。")
    quality._human(s, ctx, product_id, write=write)
    visibility = (
        "private"
        if private_source
        or current.visibility == "private"
        or any(output.visibility == "private" for output in outputs)
        else "audience"
        if current.visibility == "audience"
        or any(output.visibility == "audience" for output in outputs)
        else "category"
    )
    missing = tuple(m for output in outputs for m in output.missing)
    if action.completion_sha256 is None:
        missing += (_missing("completion", "ACTION_NOT_COMPLETED", "措施尚无执行者本人完成事实。"),)
    missing += (
        _missing(
            "applicability",
            "ACTION_FULFILLMENT_PORT_MISSING",
            "对象存在不能证明措施文本已满足，尚缺措施适用owner。",
        ),
    )
    material = dict(
        basis=current,
        action_id=action_id,
        outputs=outputs,
        visibility=visibility,
        owner_id=ctx.requester_id,
        required_source_read_set=reads,
        source_basis_sha256=digest(evidence),
        missing=missing,
        resolution_sha256="0" * 64,
    )
    resolved = ResolvedOutputs(**material)
    return resolved.model_copy(
        update={
            "resolution_sha256": digest(
                resolved.model_dump(mode="json", exclude={"resolution_sha256"})
            )
        }
    )


def _mapping_measurement(s, ctx, product_id, mapping, output):
    """Re-use original report, verified original values and deterministic result owner."""
    from pdos_next.domain.measurement_evidence.verifier import verify_measurement
    from pdos_next.domain.verification import rules
    from pdos_next.domain.verification_launch import service as launch
    from pdos_next.domain.verification_launch.models import VerificationRunVersion
    from pdos_next.domain.verification_results import service as results
    from pdos_next.domain.verification_results.models import TestResultProjection
    from pdos_next.schemas.verification.contracts import Measurement

    row = _fixed_row(s, ctx, product_id, VerificationRunVersion, mapping.run)
    run, plan = launch._snapshot(row)
    sample = next((sample for sample in run.samples if sample.id == mapping.sample_id), None)
    if sample is None or (
        sample.revision,
        sample.actual_configuration.id,
        sample.actual_configuration.revision,
    ) != (
        mapping.sample_revision,
        mapping.actual_configuration_id,
        mapping.actual_configuration_revision,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "复验pair的实际样件与配置不能改换。", 403)
    if not any(c.sample_id == sample.id and c.item_id == mapping.item_id for c in run.coverage):
        raise DomainError("FORBIDDEN_SCOPE", "复验映射不在新Run真实已接收范围。", 403)
    if mapping.measurement_id is None:
        return output, (
            _missing(
                "results",
                "MEASUREMENT_MISSING",
                "该复验pair尚无原报告测量。",
                failure=mapping.failure_id,
            ),
        )
    records = results._measurement_records(s, ctx, product_id, run)
    record = next((m for m in records if m.id == mapping.measurement_id), None)
    if record is None or (
        record.sample_id,
        record.sample_revision,
        record.item_id,
        record.actual_configuration_id,
        record.actual_configuration_revision,
    ) != (
        mapping.sample_id,
        mapping.sample_revision,
        mapping.item_id,
        mapping.actual_configuration_id,
        mapping.actual_configuration_revision,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "测量须固定同一新Run/sample/item/实际配置。", 403)
    capture = results._measurement_capture(s, ctx, product_id, record)
    content, binding = results._report_for_capture(s, ctx, product_id, capture, run, plan)
    verified = verify_measurement(
        content, binding, Measurement.model_validate(record.measurement), run
    )
    if verified.model_dump(mode="json") != record.verified_observation:
        raise DomainError("INTEGRITY_MISMATCH", "复验测量原值证明与原件重核不一致。")
    extra = {
        "measurement": record.measurement,
        "measurement_sha256": record.measurement_sha256,
        "original_verified": True,
        "measurement_source": record.verified_observation,
    }
    reads = _reads(
        output.required_source_read_set,
        record.required_source_read_set,
        capture.required_source_read_set,
    )
    missing = []
    if mapping.projection_id is None:
        missing.append(
            _missing(
                "results",
                "PROJECTION_MISSING",
                "新测量尚未固定确定性判定投影。",
                failure=mapping.failure_id,
            )
        )
    else:
        projection = results._row(s, ctx, product_id, TestResultProjection, mapping.projection_id)
        if projection.run_id != run.id or projection.project_id != row.project_id:
            raise DomainError("FORBIDDEN_SCOPE", "确定判定须属于同一新Run和项目。", 403)
        projected_row = launch._row(
            s, ctx, product_id, VerificationRunVersion, projection.run_version_id
        )
        projected_run, projected_plan = launch._snapshot(projected_row)
        calculated, aggregate = rules.compute_results(
            run, run.measurements, final=run.final_result is not None
        )
        if (
            projection.run_revision != projected_row.revision
            or projection.run_sha256 != projected_row.snapshot_sha256
            or projection.basis_sha256 != results._basis_sha(run, plan)
            or projection.input_snapshot != results._projection_basis(run, plan)
            or results._basis_sha(projected_run, projected_plan) != projection.basis_sha256
            or projection.rules_version != results.RULES_VERSION
            or projection.rules_sha256 != results.RULES_SHA256
            or projection.result != aggregate
            or run.result != aggregate
            or projection.computed_results != [c.model_dump(mode="json") for c in calculated]
            or tuple(calculated) != run.computed_results
        ):
            raise DomainError("RESULT_BASIS_CHANGED", "新复验原值、规则、判据与投影不能一致核对。")
        extra["projection"] = {
            "id": str(projection.id),
            "revision": projection.revision,
            "result": projection.result,
            "basis_sha256": projection.basis_sha256,
            "computed_results": projection.computed_results,
        }
        reads = _reads(reads, projection.required_source_read_set)
    evidence, _ = source_basis(s, ctx, product_id, reads)
    snapshot = {**output.snapshot, **extra}
    return output.model_copy(
        update={
            "snapshot": snapshot,
            "required_source_read_set": reads,
            "owner_basis_sha256": digest(
                {
                    "ref": output.ref.model_dump(mode="json"),
                    "snapshot": snapshot,
                    "source_basis": evidence,
                }
            ),
        }
    ), tuple(missing)


def _link(s, ctx, product_id, basis, ref):
    from .models import RemediationLinkRecord

    row = _fixed_row(s, ctx, product_id, RemediationLinkRecord, ref)
    saved = FollowupBasis.model_validate(row.basis_snapshot)
    if (
        saved.scope != basis.scope
        or saved.issue_id != basis.issue_id
        or saved.capa_id != basis.capa_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "整改回链不能跨Issue/CAPA范围。", 403)
    recheck_followup_basis(s, ctx, product_id, saved)
    resolved = ResolvedOutputs.model_validate(row.output_snapshot)
    if (
        saved.basis_sha256 != row.basis_sha256
        or resolved.basis != saved
        or resolved.action_id != row.action_id
        or resolved.resolution_sha256 != row.resolution_sha256
        or digest(resolved.model_dump(mode="json", exclude={"resolution_sha256"}))
        != row.resolution_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "保存的整改回链与固定输出摘要不一致。")
    signer = _link_signer(row, saved)
    runtime = _link_runtime(s)
    authority, signer_access = _link_authority(s, ctx, product_id, row, saved, signer)
    published = _link_policy(s, ctx, product_id, row, saved)
    current = resolve_followup_outputs(
        s, ctx, product_id, saved, row.action_id, tuple(o.ref for o in resolved.outputs)
    )
    # Version-only Issue additions are permitted, but every output/source proof is exact.
    if (current.outputs, current.source_basis_sha256, current.visibility) != (
        resolved.outputs,
        resolved.source_basis_sha256,
        resolved.visibility,
    ):
        raise DomainError("RECHECK_REQUIRED", "整改回链的固定输出或来源发生变化。")
    reads = _reads(current.required_source_read_set, row.required_source_read_set)
    evidence, private = source_basis(s, ctx, product_id, reads)
    if row.source_basis != {"artifact_sources": evidence}:
        raise DomainError("SOURCE_STALE", "原回链全部来源安全依据已改变。")
    if private and row.visibility != "private":
        raise DomainError("FORBIDDEN_SCOPE", "回链不能扩大私人来源受众。", 403)
    # Signed history is retained under the actual consumer's scope. A later
    # signer qualification change marks the evidence for review.
    late_authority, late_access = _link_authority(s, ctx, product_id, row, saved, signer)
    late_policy = _link_policy(s, ctx, product_id, row, saved)
    after, after_private = source_basis(s, ctx, product_id, reads)
    if (
        authority != late_authority
        or signer_access != late_access
        or published != late_policy
        or after != evidence
        or after_private != private
        or _link_runtime(s) != runtime
    ):
        raise DomainError("SOURCE_STALE", "读取期间原签发人、政策或完整来源依据已变化。")
    deadlines = (late_access["expires_at"],)
    final_consumer = _link_access(s, ctx, product_id, ctx.requester_id, write=False)
    if final_consumer != late_access:
        raise DomainError("SOURCE_STALE", "末端当前读取者权限epoch已改变。")
    quality._human(s, ctx, product_id, write=False)
    consumer = _link_access(s, ctx, product_id, ctx.requester_id, write=False)
    deadlines = tuple(value for value in (*deadlines, consumer["expires_at"]) if value is not None)
    final_at = now()  # after the final caller/Grant SQL, never the old save clock
    from pdos_next.domain.professional_authority.service import authority_time_current

    if (
        not policy.policy_time_current(late_policy, final_at)
        or any(bound <= final_at for bound in deadlines)
        or _link_runtime(s) != runtime
    ):
        raise DomainError("SOURCE_STALE", "原签发人、当前读取者或政策期限已失效。")
    needs_review = late_authority.get("needs_review") is True or not authority_time_current(
        late_authority, final_at
    )
    missing = current.missing
    if needs_review:
        missing = (
            *missing,
            _missing(
                "owner",
                "RECHECK_REQUIRED",
                "原回链签发资格待复核；新受约束动作须重新取得有效依据。",
            ),
        )
    result = current.model_copy(update={"required_source_read_set": reads, "missing": missing})
    at = now()
    if not policy.policy_time_current(late_policy, at) or any(value <= at for value in deadlines):
        raise DomainError("SOURCE_STALE", "固定回链材料构造期间当前依据已到期。")
    return result


def _link_signer(row, saved):
    snapshot = row.authority_snapshot
    try:
        signer = UUID(snapshot["subject_id"])
    except (ValueError, TypeError, KeyError):
        raise DomainError("INTEGRITY_MISMATCH", "原回链签发人身份缺少精确绑定。") from None
    if (
        signer != row.writer_id
        or signer != row.owner_id
        or snapshot.get("scope") != saved.scope.model_dump(mode="json")
        or snapshot.get("operation") != "quality.capa.followup.link"
        or snapshot.get("purpose") != saved.purpose
        or row.purpose != saved.purpose
        or row.project_id != saved.scope.project_id
    ):
        raise DomainError("INTEGRITY_MISMATCH", "原回链签发人、用途或专业操作不能精确核对。")
    return signer


def _link_access(s, ctx, pid, person_id, *, write):
    def exact(model, *where):
        rows = list(
            s.scalars(
                select(model)
                .where(*where)
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if len(rows) != 1:
            raise DomainError("FORBIDDEN_SCOPE", "原签发人或当前读取者身份已失效。", 403)
        return rows[0]

    person = exact(Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == person_id)
    grant = exact(
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(pid),
        Grant.principal_id == person_id,
    )
    if (
        person.kind != "human"
        or person.active is not True
        or (
            grant.expires_at is not None
            and (grant.expires_at is not None and grant.expires_at <= now())
        )
        or (write and grant.can_write is not True)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原签发人或当前读取者当前权限已失效。", 403)
    return {
        "person_id": person.id,
        "principal_epoch": person.access_epoch,
        "grant_id": grant.id,
        "grant_epoch": grant.access_epoch,
        "can_write": grant.can_write,
        "expires_at": grant.expires_at,
    }


def _link_authority(s, ctx, pid, row, saved, signer):
    from pdos_next.domain.professional_authority.service import recheck_snapshot

    access = _link_access(s, ctx, pid, ctx.requester_id, write=False)
    value = recheck_snapshot(
        s,
        ctx,
        pid,
        saved.scope.project_id,
        row.authority_snapshot,
        now(),
        write=False,
        retained=True,
    )
    if value.get("current") is not True or not value.get("assessment"):
        raise DomainError("RECHECK_REQUIRED", "原回链签发人的当前专业依据需要重核。")
    return {**value["assessment"], "needs_review": value.get("needs_review") is True}, access


def _link_policy(s, ctx, pid, row, saved):
    from pdos_next.domain.quality_execution import policy

    current = policy.assess(s, ctx, pid, saved.scope.project_id, saved.purpose)
    if current != row.policy_snapshot:
        raise DomainError("RECHECK_REQUIRED", "原回链政策版本或签发epoch已改变。")
    return current


def _link_runtime(s):
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.quality_execution import policy

    engine = s.get_bind()
    return digest(
        {
            "synthetic": getattr(engine, "_pdos_professional_synthetic", False),
            "professional": {
                k: [id(v), getattr(v, "epoch", None)]
                for k, v in getattr(engine, "_pdos_professional_issuers", {}).items()
            },
            "professional_epochs": getattr(engine, "_pdos_professional_issuer_epochs", {}),
            "policy": {
                k: [id(v), getattr(v, "epoch", None)]
                for k, v in getattr(engine, "_pdos_quality_policy_issuers", {}).items()
            },
            "policy_epochs": getattr(engine, "_pdos_quality_policy_epochs", {}),
            "ports": [id(professional.recheck_snapshot), id(policy.assess)],
        }
    )


def inspect_candidate(s, ctx, product_id, binding, *, at, write=False):
    checked_at = _at(at)
    binding = CandidateBinding.model_validate(binding)
    current = recheck_followup_basis(s, ctx, product_id, binding.basis, write=write)
    reads = current.required_source_read_set
    missing = []
    if current.root_cause_sha256 is None:
        missing.append(_missing("root_cause", "ROOT_CAUSE_MISSING", "尚无具名根因结论。"))
    if any(a.completion_sha256 is None for a in current.actions):
        missing.append(_missing("completion", "ACTION_NOT_COMPLETED", "CAPA尚有未完成措施。"))
    for ref in binding.remediation_link_refs:
        link = _link(s, ctx, product_id, current, ref)
        reads = _reads(reads, link.required_source_read_set)
        missing.extend(link.missing)
    original_row = quality._row(s, ctx, product_id, current.issue_id, current.issue_revision)
    original = quality._snapshot(original_row)
    original_runs = {f.run.id for f in original.failures}
    covered = set()
    outputs = []
    for mapping in binding.mappings:
        output = _reading(s, ctx, product_id, current, mapping.run)
        if output.logical_id in original_runs:
            raise DomainError("ORIGINAL_FAILURE_RUN", "原失败Run不能作为独立复验。", 422)
        run_data = output.snapshot["run"]
        source_nature = output.snapshot.get("source_nature")
        if source_nature is not None and source_nature != current.nature:
            raise DomainError("NATURE_MISMATCH", "复验不得混用真实与合成事实。", 422)
        if source_nature is None:
            missing.append(
                _missing(
                    "execution",
                    "NATURE_UNVERIFIED",
                    "尚无执行owner提供可核对的事实性质。",
                    failure=mapping.failure_id,
                )
            )
        if output.meaning == "performed":
            output, gaps = _mapping_measurement(s, ctx, product_id, mapping, output)
            missing.extend(gaps)
        else:
            if mapping.measurement_id is not None or mapping.projection_id is not None:
                raise DomainError(
                    "MEASUREMENT_WITHOUT_EXECUTION", "计划Run不能声明已有测量或结果投影。", 422
                )
            # A planned pair is still an exact server-owned pair, never a reading.
            run_samples = {sample["id"]: sample for sample in run_data["samples"]}
            sample = run_samples.get(str(mapping.sample_id))
            if sample is None or (
                sample["revision"],
                sample["actual_configuration"]["id"],
                sample["actual_configuration"]["revision"],
            ) != (
                mapping.sample_revision,
                str(mapping.actual_configuration_id),
                mapping.actual_configuration_revision,
            ):
                raise DomainError("FORBIDDEN_SCOPE", "计划复验映射不能改换实际样件配置。", 403)
            if not any(
                c["sample_id"] == str(mapping.sample_id) and c["item_id"] == mapping.item_id
                for c in run_data["coverage"]
            ):
                raise DomainError("FORBIDDEN_SCOPE", "计划映射超出真实接收范围。", 403)
        refs = refs_from_exact(s, ctx, product_id, mapping.applicability_sources)
        reads = _reads(
            reads,
            output.required_source_read_set,
            [{"artifact_id": r.id, "expected_revision": r.revision} for r in refs],
        )
        missing.extend(output.missing)
        outputs.append(output)
        covered.add(mapping.failure_id)
    for identity in sorted(set(current.failure_ids) - covered):
        missing.append(
            _missing(
                "mapping", "FAILURE_NOT_MAPPED", "原失败尚未映射到新复验pair。", failure=identity
            )
        )
    missing.extend(
        (
            _missing(
                "applicability",
                "INTEGRATION_REQUIRED",
                "尚缺CAPA要求与新方法/判据/实际配置的专业适用权威接口。",
            ),
            _missing(
                "independence",
                "INTEGRATION_REQUIRED",
                "尚缺独立复验人专业依据与参与者排除的权威接口。",
            ),
            _missing(
                "observation",
                "INTEGRATION_REQUIRED",
                "尚缺覆盖真实观察期的事实owner，要求日期不能当实际完成。",
            ),
            _missing("policy", "EFFECTIVENESS_NOT_ENABLED", "本波不开放CAPA有效性与Issue关闭。"),
        )
    )
    evidence, _ = source_basis(s, ctx, product_id, reads)
    recheck_followup_basis(s, ctx, product_id, current, write=write)
    # All original-byte reads are complete; recheck retained runtime/issuer facts now.
    for mapping in binding.mappings:
        fresh = _reading(s, ctx, product_id, current, mapping.run)
        old = next(o for o in outputs if o.ref == mapping.run)
        if old.snapshot.get("retained") != fresh.snapshot.get("retained"):
            raise DomainError("SOURCE_STALE", "原件读取期间复验执行的资格/来源/消费依据发生变化。")
    after, _ = source_basis(s, ctx, product_id, reads)
    if evidence != after:
        raise DomainError("SOURCE_STALE", "读取期间复验来源或安全依据发生变化。")
    for ref in binding.remediation_link_refs:
        _link(s, ctx, product_id, current, ref)
    quality._human(s, ctx, product_id, write=write)
    _at(checked_at)
    value = CandidateInspect(
        binding=binding.model_copy(update={"basis": current}),
        outputs=tuple(outputs),
        current=all(
            o.source_status == "current"
            and not any(m.code == "FIXED_OUTPUT_HISTORICAL" for m in o.missing)
            for o in outputs
        ),
        required_source_read_set=reads,
        source_basis_sha256=digest(evidence),
        inspection_sha256="0" * 64,
        missing=tuple(missing),
    )
    return value.model_copy(
        update={
            "inspection_sha256": digest(
                value.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
            )
        }
    )


def inspect_verification(s, ctx, product_id, basis, evidence_ref, *, at, write=False):
    from .models import CapaVerificationEvidence

    quality._human(s, ctx, product_id, write=write)
    basis = FollowupBasis.model_validate(basis)
    ref = FixedRef.model_validate(evidence_ref)
    row = _fixed_row(s, ctx, product_id, CapaVerificationEvidence, ref)
    saved = CandidateBinding.model_validate(row.candidate_binding)
    if saved.basis != FollowupBasis.model_validate(row.basis_snapshot):
        raise DomainError("INTEGRITY_MISMATCH", "复验候选与保存的整改依据不一致。")
    if (saved.basis.scope, saved.basis.issue_id, saved.basis.capa_id) != (
        basis.scope,
        basis.issue_id,
        basis.capa_id,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "复验候选不在固定Issue/CAPA范围。", 403)
    if (
        digest(saved.model_dump(mode="json")) != row.binding_sha256
        or row.basis_sha256 != saved.basis.basis_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "保存的复验候选摘要无法核对。")
    snapshot = CandidateInspect.model_validate(row.candidate_snapshot)
    if (
        snapshot.binding != saved
        or snapshot.inspection_sha256 != row.inspection_sha256
        or digest(snapshot.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"}))
        != row.inspection_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "候选检查原文摘要无法核对。")
    current = inspect_candidate(s, ctx, product_id, saved, at=at, write=write)
    return current.model_copy(update={"candidate_ref": ref})
