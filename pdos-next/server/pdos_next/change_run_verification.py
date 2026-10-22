"""Read native Run truth for a named Change decision; never create an Issue or Run.

The host signs the explicit mapping in the common T2 command. This reader checks
its fixed requirement/method/pair against actual owners. It cannot interpret a
free-text requirement or grant a verifier any professional authority.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from pdos_next import quality_result_bridge as bridge
from pdos_next.change_completion_schemas import RunScopeMapping
from pdos_next.domain.builds import service as builds
from pdos_next.domain.change_control.rules import digest as change_digest
from pdos_next.domain.measurement_evidence.schemas import VerifiedObservation
from pdos_next.domain.quality_execution.evidence import merge_reads
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_results import service as results
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    ChangeOrder,
    ChangeRequest,
    Ref,
    VerificationFact,
)
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest


@dataclass(frozen=True)
class RunVerificationRead:
    fact: VerificationFact
    sources: tuple[SourceRef, ...]
    required_source_read_set: tuple[dict, ...]
    source_basis: dict
    verified_domain_sources: tuple[SourceRef, ...]
    actual_refs: tuple[Ref, ...]

    @property
    def provenance(self):
        return self.source_basis


def _require(ok, message, code="MISSING_REQUIRED_EVIDENCE"):
    if not ok:
        raise DomainError(code, message)


def _audience(request, owner_id, visibility):
    if visibility == "private" and request.audience != (f"private:{owner_id}",):
        raise DomainError("AUDIENCE_USE_FORBIDDEN", "私有运行或配置不能扩大到变更受众。", 403)


def _outputs(order):
    """Only explicitly supported object/configuration scopes get a positive read."""
    result = {}
    kinds = {
        "new_engineering_configuration": "engineering_configuration",
        "new_manufacturing_configuration": "manufacturing_configuration",
    }
    for item in order.plan.items:
        kind = kinds.get(item.intent.kind)
        objects = item.selection.objects
        if (
            kind is None
            or any(ref.kind != kind or ref.key is not None for ref in objects)
            or set(item.selection.units) != {f"object:{ref.identity}" for ref in objects}
        ):
            raise DomainError(
                "INTEGRATION_REQUIRED", "本读取仅支持明确对象范围的新工程/制造配置验证。", 503
            )
        implemented = {
            ref.identity: ref
            for fact in order.implementations
            if fact.item_id == item.id and fact.outcome == "succeeded"
            for ref in fact.outputs
            if ref.kind == kind and ref.key is None
        }
        effective = {
            ref.identity: ref
            for fact in order.effectivity
            if fact.item_id == item.id and fact.stage == "effective" and fact.outcome == "succeeded"
            for ref in fact.output_refs
            if ref.kind == kind and ref.key is None
        }
        _require(
            len(implemented) == 1 and set(implemented) <= set(effective),
            "各计划项须有实际实施并生效的唯一新配置。",
        )
        output = next(iter(implemented.values()))
        _require(output not in objects, "原配置不能冒充实施后的新配置。")
        result[item.id] = output
    return result


def _build(s, ctx, pid, request, run):
    row = builds._build(s, ctx, pid, run.build.id)
    project, engineering, manufacturing, reads = builds._linked(s, ctx, pid, row)
    actual = run.build
    _require(
        (row.tenant_id, row.product_id, row.project_id, row.revision)
        == (request.scope.tenant_id, pid, request.scope.project_id, actual.revision)
        and project.id == request.scope.project_id
        and (str(row.engineering_configuration_id), str(row.manufacturing_configuration_id))
        == (str(actual.engineering_configuration.id), str(actual.manufacturing_configuration.id)),
        "Run 的固定 Build 与实际项目/双配置不一致。",
        "FORBIDDEN_SCOPE",
    )
    refs = [Ref(kind="build", id=row.id, revision=row.revision)]
    for view, kind, fixed in (
        (engineering, "engineering_configuration", actual.engineering_configuration),
        (manufacturing, "manufacturing_configuration", actual.manufacturing_configuration),
    ):
        _require(
            (str(view["id"]), view["revision"]) == (str(fixed.id), fixed.revision)
            and view["source_status"] == "current",
            "新 Build 的实际固定配置来源需重核。",
            "SOURCE_STALE",
        )
        _audience(request, view["owner_id"], view["visibility"])
        refs.append(Ref(kind=kind, id=fixed.id, revision=fixed.revision))
    return refs, reads


def _run(s, ctx, pid, request, ref):
    row = launch._version(s, ctx, pid, ref.id, ref.revision)
    pointer, current_row = launch._current(s, ctx, pid, ref.id)
    _require(
        pointer is not None and current_row.id == row.id and current_row.revision == ref.revision,
        "所选 Run 已非当前固定版本。",
        "VERSION_CONFLICT",
    )
    run, _ = launch._snapshot(row)
    _require(run.scope == request.scope, "复验 Run 不能跨项目。", "FORBIDDEN_SCOPE")
    _audience(request, row.owner_id, row.visibility)
    _, request_row = front._current(s, ctx, pid, run.request_id)
    _require(request_row is not None, "Run 的正式请求当前版本不存在。", "SOURCE_STALE")
    formal = front._snapshot(request_row)
    _require(
        formal.scope == run.scope and formal.build == run.build and formal.items == run.items,
        "正式请求的固定配置/方法范围与 Run 不一致。",
        "SOURCE_STALE",
    )
    _require(
        run.actual_start is not None
        and run.actual_end is not None
        and run.final_result is not None,
        "需已实际完成且完整回传结果的新 Run。",
    )
    records = results._measurement_records(s, ctx, pid, run)
    _require(bool(records), "新 Run 缺少实际测量。")
    value = bridge.fixed_failure_result(
        s, ctx, pid, run_id=run.id, run_revision=ref.revision, measurement_id=records[0].id
    )
    _require(
        value.verified.run == run and value.current is True,
        "实际原值、确定性判定与执行证明不能核对。",
        "SOURCE_STALE",
    )
    coverage = {(v.sample_id, v.item_id) for v in run.coverage}
    observations = {}
    for record in records:
        verified = VerifiedObservation.model_validate(record.verified_observation)
        observation = verified.observation
        pair = (record.sample_id, record.item_id)
        _require(
            pair not in observations
            and verified.measurement.id == record.id
            and verified.measurement.model_dump(mode="json") == record.measurement
            and (observation.coverage.sample_id, observation.coverage.item_id) == pair
            and not observation.missing
            and not observation.metadata_mismatches
            and observation.executor_id is not None
            and observation.observed_at is not None,
            "全部测量须保留完整原值、执行人、观测时点及逐字段证明。",
        )
        observations[pair] = observation
    _require(set(observations) == coverage, "真实原值未完整覆盖该 Run 的样件/测试项。")
    _require(run.execution is not None, "缺少真实测试执行人。")
    return row, request_row, value, observations


def read_verification(s, ctx, pid, request, order, mappings, *, fact_id, at, verifier_id=None):
    """Re-read immutable T2 inputs with the current caller's ACL, never another ctx.

    ``verifier_id`` is a host-only original signer for replay/close, after the
    host has matched its saved atom actor. It confers no current authority.
    The pure Change handler enforces the current named verifier's independence.
    """
    launch._human(s, ctx, pid, write=False)
    request, order = ChangeRequest.model_validate(request), ChangeOrder.model_validate(order)
    _require(
        request.scope.tenant_id == ctx.tenant_id
        and request.scope.product_id == pid
        and any(value == order for value in request.orders),
        "验证须绑定当前变更中的固定变更令。",
        "FORBIDDEN_SCOPE",
    )
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise DomainError("INVALID_EVENT_TIME", "服务器复核时点须含时区。", 422)
    at = at.astimezone(UTC)
    mappings = tuple(RunScopeMapping.model_validate(value) for value in mappings)
    items = {item.id: item for item in order.plan.items}
    keys = [(m.item_id, m.run.identity, m.sample_id, m.test_item_id) for m in mappings]
    _require(
        bool(mappings)
        and len(keys) == len(set(keys))
        and {m.item_id for m in mappings} == set(items),
        "具名适用性映射须明确覆盖每个固定计划项且不能重复。",
    )
    for mapping in mappings:
        _require(
            mapping.requirement_sha256
            == change_digest(items[mapping.item_id].verification_requirement),
            "适用性声明未绑定当前固定验证要求。",
            "VERSION_CONFLICT",
        )
    outputs = _outputs(order)
    loaded, sources, reads, actual, provenance = {}, {}, [], {}, {}
    executors, observations, natures, outcomes = set(), [], set(), []
    for mapping in mappings:
        key = mapping.run.identity
        if key not in loaded:
            row, formal_row, value, original = _run(s, ctx, pid, request, mapping.run)
            run = value.verified.run
            refs, build_reads = _build(s, ctx, pid, request, run)
            refs.append(mapping.run)
            refs.extend(Ref(kind="sample", id=v.id, revision=v.revision) for v in run.samples)
            actual.update({ref.identity: ref for ref in refs})
            sources.update({change_digest(v): v for v in value.sources})
            reads = merge_reads(reads, value.required_source_read_set, build_reads)
            natures.add(value.verified.nature)
            outcomes.append(run.result)
            executors.add(run.execution.executor_id)
            for observation in original.values():
                executors.add(observation.executor_id)
                observations.append(observation.observed_at)
            provenance[key] = {
                "run_version_id": str(row.id),
                "run_revision": row.revision,
                "run_sha256": row.snapshot_sha256,
                "request_version_id": str(formal_row.id),
                "request_revision": formal_row.revision,
                "request_sha256": formal_row.snapshot_sha256,
                "projection_id": str(value.projection_id),
                "projection_revision": value.projection_revision,
                "basis_sha256": value.basis_sha256,
                "rules_sha256": value.rules_sha256,
                "source_basis": value.source_basis["evidence"],
                "observations": [v.model_dump(mode="json") for _, v in sorted(original.items())],
            }
            loaded[key] = value, original
        value, original = loaded[key]
        run, output = value.verified.run, outputs[mapping.item_id]
        config = (
            run.build.engineering_configuration
            if output.kind == "engineering_configuration"
            else run.build.manufacturing_configuration
        )
        observation = original.get((mapping.sample_id, mapping.test_item_id))
        test_item = next((v for v in run.items if v.id == mapping.test_item_id), None)
        _require(
            (config.id, config.revision) == (output.id, output.revision)
            and observation is not None
            and test_item is not None
            and observation.method == test_item.method == mapping.method,
            "具名映射须使用实际实施配置及该 Run 的准确样件、测试项和原文方法。",
            "FORBIDDEN_SCOPE",
        )
    _require(len(natures) == 1, "真实与合成执行不可拼成同一验证。", "FACT_NATURE_MISMATCH")
    _require(bool(observations) and max(observations) <= at, "不能以未来观测形成复核。")
    required_outputs = {
        ref.identity
        for fact in order.implementations
        if fact.outcome == "succeeded"
        for ref in fact.outputs
    } | {
        ref.identity
        for fact in order.effectivity
        if fact.stage == "effective" and fact.outcome == "succeeded"
        for ref in fact.output_refs
    }
    _require(required_outputs <= set(actual), "复验未覆盖所有实际实施/生效输出。")
    # All byte reads finish before the existing owner's metadata/retained refresh.
    for value, _ in loaded.values():
        bridge.recheck_fixed_failure_result(s, ctx, pid, value)
    source_tuple = tuple(sources[key] for key in sorted(sources))
    _require(bool(source_tuple), "完整复验缺少实际来源。")
    result = "fail" if "fail" in outcomes else "pass" if set(outcomes) == {"pass"} else "unknown"
    refs = tuple(actual[key] for key in sorted(actual))
    fact = VerificationFact(
        id=fact_id,
        verifier_id=verifier_id or ctx.actor_id,
        executor_ids=tuple(sorted(executors)),
        content_digest=order.content_digest,
        result=result,
        item_ids=tuple(sorted(items)),
        output_refs=refs,
        sources=source_tuple,
        observed_from=min(observations),
        observed_until=max(observations),
        applicable=True,
        current=True,
        nature=next(iter(natures)),
    )
    return RunVerificationRead(
        fact=fact,
        sources=source_tuple,
        required_source_read_set=tuple(reads),
        source_basis={
            "schema_version": "pdos-native-change-run-verification-v1",
            "order_id": str(order.id),
            "content_digest": order.content_digest,
            "mappings": [m.model_dump(mode="json") for m in mappings],
            "runs": provenance,
            "fact_sha256": digest(fact.model_dump(mode="json")),
        },
        verified_domain_sources=tuple(v for v in source_tuple if v.kind == "domain"),
        actual_refs=refs,
    )
