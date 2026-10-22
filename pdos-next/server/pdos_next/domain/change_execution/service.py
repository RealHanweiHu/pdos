"""Common transaction participant for requests and conservative dual-lane impact.

No commit, own Receipt, second confirmation, ERP I/O or qualification grants.
"""

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import exists, select

from pdos_next.clock import deadline_current
from pdos_next.domain.change_control.ports import Invocation
from pdos_next.domain.change_control.rules import digest, graph_sources
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.professional_authority import service as professional
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal, Product, Receipt, Run, now
from pdos_next.schemas.change_control.contracts import (
    ChangeRequest,
    ImpactCompute,
    Ref,
    RequestCreate,
)
from pdos_next.schemas.verification.contracts import Scope, SourceRef

from .adapters import authority_dto, kernel
from .graph import CapturedInputReader, OwnerReader, audience, capture_graph
from .models import ChangeCurrent, ChangeGraphCapture, ChangeRequestVersion
from .schemas import ChangeCreatePayload, GraphCaptureInput, ImpactComputePayload

PAYLOADS = {
    "change.request.create": ChangeCreatePayload,
    "change.impact.compute": ImpactComputePayload,
}
deduplicate_subject = {"change_request"}
MAX_ORIGINAL_BYTES = 20 * 1024 * 1024
POSITION = re.compile(r"line:([1-9][0-9]*);quote_sha256:([0-9a-f]{64})")


def configure_store(engine, store):
    """Trusted host dependency only, never enablement or qualification."""
    engine._pdos_change_store = store


def configure_issue_loader(engine, loader):
    """Optional trusted host adapter with the same fixed get_issue signature."""
    if not callable(loader):
        raise TypeError("Fixed Issue loader must be callable")
    engine._pdos_change_issue_loader = loader


def _issue_loader(s):
    installed = getattr(s.get_bind(), "_pdos_change_issue_loader", None)
    if installed is not None:
        return installed
    try:
        from pdos_next.domain.quality_execution.service import get_issue_for_change
    except ImportError:
        raise DomainError(
            "INTEGRATION_REQUIRED", "固定Issue/CAPA所有者读取端口尚未接入。", 503
        ) from None
    return get_issue_for_change


def _human(s, ctx, pid, *, write=False):
    from pdos_next.domain.supply_execution.service import _human as human

    human(s, ctx, pid, write=write)


def semantic(payload):
    value = payload.model_dump(mode="json")
    for key in ("roots", "references", "sources"):
        if key in value:
            value[key].sort(key=lambda row: digest(row))
    if len(str(value).encode()) > 1_000_000:
        raise DomainError("INVALID_PAYLOAD", "变更输入超过1MB有界上限。", 422)
    return value


def _intent(ctx, command, payload):
    return digest(
        {
            "scope": [str(ctx.tenant_id), str(command.product_id)],
            "actor": str(ctx.requester_id),
            "operation": command.operation,
            "payload": semantic(payload),
        }
    )


def stable_change_id(scope, actor_id, target, payload):
    """Key-independent intent identity with exact scope, named actor and audience."""
    return uuid5(
        NAMESPACE_URL,
        digest(
            {
                "scope": scope.model_dump(mode="json"),
                "actor": str(actor_id),
                "audience": target,
                "payload": semantic(payload),
            }
        ),
    )


def _row(s, ctx, pid, model, identity):
    row = s.scalar(
        select(model).where(
            model.tenant_id == ctx.tenant_id, model.product_id == pid, model.id == identity
        )
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "变更版本/图捕获不可访问。", 403)
    return row


def _version(s, ctx, pid, change_id, revision):
    row = s.scalar(
        select(ChangeRequestVersion).where(
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == pid,
            ChangeRequestVersion.change_id == change_id,
            ChangeRequestVersion.revision == revision,
        )
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "固定变更版本不可访问。", 403)
    return row


def _current(s, ctx, pid, change_id, *, lock=False):
    q = select(ChangeCurrent).where(
        ChangeCurrent.tenant_id == ctx.tenant_id,
        ChangeCurrent.product_id == pid,
        ChangeCurrent.change_id == change_id,
    )
    pointer = s.scalar(q.with_for_update() if lock else q)
    if pointer is None:
        return None, None
    row = _row(s, ctx, pid, ChangeRequestVersion, pointer.version_id)
    if row.change_id != change_id or row.revision != pointer.revision:
        raise DomainError("INTEGRITY_MISMATCH", "变更当前指针与固定版不一致。")
    return pointer, row


def _snapshot(row):
    if row.operation in {
        "change.order.prepare",
        "change.order.approve",
        "change.implementation.record",
        "change.effectivity.record",
        "change.verification.record",
        "change.close",
    }:
        from pdos_next.change_order_service import snapshot

        return snapshot(row)
    value = ChangeRequest.model_validate(row.request_snapshot)
    if (
        value.id != row.change_id
        or value.revision != row.revision
        or value.scope.tenant_id != row.tenant_id
        or value.scope.product_id != row.product_id
        or value.scope.project_id != row.project_id
        or digest(value) != row.request_sha256
        or value.status != row.status
        or value.orders
    ):
        raise DomainError("INTEGRITY_MISMATCH", "变更固定版摘要或准备边界不一致。")
    return value


def _scope_seed(s, ctx, pid, refs):
    if any(ref.kind == "field_feedback" for ref in refs):
        return _seed(s, ctx, pid, refs)
    loader = _issue_loader(s)
    from pdos_next.domain.quality_execution.service import (
        _change_scope_for_change,
        get_issue_for_change,
    )

    if (
        loader is get_issue_for_change
        and getattr(s.get_bind(), "_pdos_change_issue_loader", None) is None
    ):
        values = [
            _change_scope_for_change(s, ctx, pid, ref)
            for ref in refs
            if ref.kind in {"issue", "capa"}
        ]
        if not values:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "须固定真实Issue/CAPA依据。", 422)
        if any(value != values[0] for value in values[1:]):
            raise DomainError("FORBIDDEN_SCOPE", "变更依据跨项目或精确用途。", 403)
        return values[0]

    return _seed(s, ctx, pid, refs)


def _seed(s, ctx, pid, refs):
    from .field_bridge import get as field_feedback

    loader = None
    values, wrappers = [], {}
    for ref in refs:
        if ref.kind == "field_feedback":
            row, _, _, purpose = field_feedback(s, ctx, pid, ref)
            values.append((row, {"purpose": purpose}))
            continue
        if ref.kind not in {"issue", "capa"}:
            continue
        if loader is None:
            loader = _issue_loader(s)
        identity = (ref.id, ref.revision)
        if identity not in wrappers:
            wrappers[identity] = loader(s, ctx, pid, ref.id, ref.revision)
        row, typed = wrappers[identity]
        view = typed.model_dump(mode="json") if hasattr(typed, "model_dump") else typed
        if (
            str(view["issue_id"]) != str(ref.id)
            or view["revision"] != ref.revision
            or row.tenant_id != ctx.tenant_id
            or row.product_id != pid
        ):
            raise DomainError("FIXED_REFERENCE_MISMATCH", "Issue端口未返回指定固定版。")
        values.append((row, view))
    if not values:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "须固定真实Issue、CAPA或已定位现场反馈依据。", 422
        )
    if len({(str(row.project_id), view["purpose"]) for row, view in values}) != 1:
        raise DomainError("FORBIDDEN_SCOPE", "变更依据跨项目或精确用途。", 403)
    row, view = values[0]
    return Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=row.project_id), view[
        "purpose"
    ]


def _authority(s, ctx, pid, scope, operation, purpose, *, write=False):
    value = professional.assess(
        s, ctx, pid, scope.project_id, operation, purpose, now(), write=write
    )
    if "PROFESSIONAL_OPERATION_NOT_CONFIGURED" in value["reason_codes"]:
        raise DomainError("INTEGRATION_REQUIRED", "变更专业职责/资格操作矩阵尚未接入。", 503)
    if value["authorized"] is not True or value["qualified"] is not True:
        raise DomainError("QUALIFICATION_REQUIRED", "当前具名专业职责/精确用途资格未满足。", 403)
    if not set(value["roles"]) & {"engineering", "manufacturing", "quality"}:
        raise DomainError("FORBIDDEN_OPERATION", "当前专业职责不能办理变更。", 403)
    return value


def _runtime_stamp(s):
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_professional_issuers", {})
    runtime = getattr(engine, "_pdos_security_runtime", None)
    value = {
        "professional_synthetic": getattr(engine, "_pdos_professional_synthetic", False),
        "issuers": {key: [id(value), value.epoch] for key, value in registry.items()},
        "issuer_epochs": getattr(engine, "_pdos_professional_issuer_epochs", {}),
        "security_runtime": id(runtime),
        "store": id(getattr(engine, "_pdos_change_store", None)),
        "issue_loader": id(getattr(engine, "_pdos_change_issue_loader", None)),
    }
    coverage = getattr(engine, "_pdos_change_coverage_issuers", {})
    epochs = getattr(engine, "_pdos_change_coverage_epochs", {})
    if coverage or epochs:
        value["coverage_runtime"] = {
            "issuers": sorted(
                ([str(v) for v in key], id(issuer), issuer.epoch, str(issuer.nonce))
                for key, issuer in coverage.items()
            ),
            "epochs": sorted(([str(v) for v in key], epoch) for key, epoch in epochs.items()),
        }
    return digest(value)


def _source_reads(sources):
    return [
        {"artifact_id": str(value.id), "expected_revision": value.revision}
        for value in sources
        if value.kind == "artifact"
    ]


def _native_registration(s, ctx, pid, source):
    """Exact immutable registration, not a client supplied source-origin flag."""
    rows = list(
        s.scalars(
            select(Receipt)
            .where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.category_id == source.category_id,
                Receipt.product_id.is_not_distinct_from(source.product_id),
                Receipt.operation == "evidence.artifact.register",
                Receipt.subject_type == "artifact",
                Receipt.subject_id == source.id,
                Receipt.subject_revision == source.revision,
            )
            .limit(2)
        )
    )
    if len(rows) != 1:
        raise DomainError("INTEGRATION_REQUIRED", "原生文本缺唯一实际登记回执。", 503)
    receipt = rows[0]
    if (
        receipt.tenant_id != ctx.tenant_id
        or receipt.category_id != source.category_id
        or receipt.product_id != source.product_id
        or receipt.operation != "evidence.artifact.register"
        or receipt.subject_type != "artifact"
        or receipt.subject_id != source.id
        or receipt.subject_revision != source.revision
        or receipt.requester_id != source.owner_id
        or receipt.visibility != source.visibility
        or not isinstance(receipt.result, dict)
        or receipt.result.get("id") != str(source.id)
        or type(receipt.result.get("revision")) is not int
        or receipt.result["revision"] != source.revision
        or receipt.result.get("status") != "active"
    ):
        raise DomainError("INTEGRATION_REQUIRED", "原生文本登记身份、版本或受众无法核对。", 503)
    actor = s.get(Principal, receipt.actor_id)
    requester = s.get(Principal, receipt.requester_id)
    if (
        actor is None
        or requester is None
        or actor.tenant_id != ctx.tenant_id
        or requester.tenant_id != ctx.tenant_id
        or requester.kind != "human"
    ):
        raise DomainError("INTEGRATION_REQUIRED", "原生文本登记人员来源无法核对。", 503)
    run = None
    if actor.kind == "human":
        if receipt.actor_id != receipt.requester_id or receipt.run_id is not None:
            raise DomainError("INTEGRATION_REQUIRED", "原生文本人工登记上下文无法核对。", 503)
    elif actor.kind == "agent" and receipt.run_id is not None:
        run = s.get(Run, receipt.run_id)
        if (
            run is None
            or run.tenant_id != ctx.tenant_id
            or run.product_id != source.product_id
            or run.requester_id != receipt.requester_id
            or run.writer_id != receipt.actor_id
        ):
            raise DomainError("INTEGRATION_REQUIRED", "原生文本委托运行来源无法核对。", 503)
    else:
        raise DomainError("INTEGRATION_REQUIRED", "原生文本登记缺实际运行来源。", 503)
    return {
        "source_origin": "registered_native_text",
        "registration_receipt_id": str(receipt.id),
        "registration_command_id": str(receipt.command_id),
        "registration_actor_id": str(receipt.actor_id),
        "registration_actor_kind": actor.kind,
        "registration_requester_id": str(receipt.requester_id),
        "registration_run_id": str(run.id) if run is not None else None,
        "registration_request_digest": receipt.request_digest,
        "registration_intent_digest": receipt.intent_digest,
    }


def _evidence(s, ctx, pid, reads, sources=(), *, io=True):
    from pdos_next.object_storage import StorageFailure
    from pdos_next.original_security import require_safe
    from pdos_next.originals import object_reference, read_registered_bytes, require_original
    from pdos_next.service import digest as content_digest
    from pdos_next.service import source_for

    basis, lines, private = {}, {}, False
    store = getattr(s.get_bind(), "_pdos_change_store", None)
    for read in reads:
        source = source_for(s, ctx, pid, UUID(read["artifact_id"]), read["expected_revision"])
        if source.content_hash != content_digest(source.content):
            raise DomainError("INTEGRITY_MISMATCH", "来源派生文本摘要不一致。")
        if source.original_id is None:
            if len(source.content.encode("utf-8")) > MAX_ORIGINAL_BYTES:
                raise DomainError("SOURCE_UNAVAILABLE", "原生文本超过有界核验上限。")
            provenance = _native_registration(s, ctx, pid, source)
            private |= source.visibility == "private"
            lines[str(source.id)] = source.content.splitlines()
            basis[str(source.id)] = {
                "revision": source.revision,
                "sha256": source.content_hash,
                "owner_id": str(source.owner_id),
                "visibility": source.visibility,
                **provenance,
            }
            continue
        writing = not s.info.get("read_snapshot")
        original = require_original(s, ctx, pid, source.original_id, lock=writing)
        epoch, _ = require_safe(s, ctx, original, lock=writing)
        ref = object_reference(original)
        if original.status != "parsed" or ref.size_bytes > MAX_ORIGINAL_BYTES:
            raise DomainError("SOURCE_UNAVAILABLE", "原件不可定位或超过有界核验上限。")
        if io:
            if store is None:
                raise DomainError("INTEGRATION_REQUIRED", "变更原件安全读取端口未配置。", 503)
            try:
                content = read_registered_bytes(
                    store, ref, ctx.tenant_id, original.product_id, ctx.category_id
                )
            except StorageFailure:
                raise DomainError(
                    "STORAGE_UNAVAILABLE", "变更原件读取失败，未保存业务变更。", 503
                ) from None
            if (
                len(content) != ref.size_bytes
                or hashlib.sha256(content).hexdigest() != ref.content_sha256
            ):
                raise DomainError("INTEGRITY_MISMATCH", "变更原件字节摘要不一致。")
            latest, _ = require_safe(s, ctx, original, lock=writing)
            if latest != epoch:
                raise DomainError("SOURCE_STALE", "原件读取期间安全epoch变化。")
        private |= source.visibility == "private" or original.visibility == "private"
        lines[str(source.id)] = source.content.splitlines()
        basis[str(source.id)] = {
            "source_origin": "uploaded_original",
            "revision": source.revision,
            "sha256": source.content_hash,
            "owner_id": str(source.owner_id),
            "visibility": source.visibility,
            "original_id": str(original.id),
            "original_sha256": original.content_hash,
            "original_revision": original.revision,
            "security_epoch": epoch,
            "original_owner_id": str(original.owner_id),
            "original_visibility": original.visibility,
        }
    verified = set()
    for source in sources:
        if source.kind != "artifact":
            continue
        match = POSITION.fullmatch(source.position)
        content_lines = lines.get(str(source.id), [])
        if (
            match is None
            or int(match[1]) > len(content_lines)
            or hashlib.sha256(content_lines[int(match[1]) - 1].encode()).hexdigest() != match[2]
        ):
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "来源须精确固定原文行及整行摘要。", 422)
        verified.add(digest(source))
    return basis, private, verified


@dataclass
class Bound:
    scope: Scope
    purpose: str
    target: tuple
    change_id: UUID
    request_row: object
    request: ChangeRequest | None
    reader: OwnerReader
    reads: list
    sources: tuple
    source_basis: dict
    authority: dict
    verified_sources: set
    runtime_stamp: str
    graph: object = None
    capture: object = None
    coverage: object = None


def _graph(row):
    from pdos_next.schemas.change_control.contracts import GraphSnapshot

    value = GraphSnapshot.model_validate(row.graph_snapshot)
    if (
        value.id != row.id
        or value.revision != row.revision
        or digest(value) != row.graph_sha256
        or value.expires_at != row.expires_at
        or value.scope.project_id != row.project_id
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定影响图摘要/范围不一致。")
    return value


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _human(s, ctx, product.id, write=True)
    if (
        command.operation not in PAYLOADS
        or product.tenant_id != ctx.tenant_id
        or not isinstance(payload, PAYLOADS[command.operation])
    ):
        raise DomainError("FORBIDDEN_OPERATION", "本轮只开放请求创建与影响计算。", 403)
    semantic(payload)
    stamp = _runtime_stamp(s)
    if isinstance(payload, ChangeCreatePayload):
        scope, purpose = _scope_seed(s, ctx, product.id, (*payload.roots, *payload.references))
        target = audience(product.id, ctx.requester_id, payload.visibility)
        change_id = stable_change_id(scope, ctx.requester_id, target, payload)
        row = request = graph = capture = None
        roots, refs, sources = payload.roots, payload.references, payload.sources
    else:
        row = _version(s, ctx, product.id, payload.change_id, payload.expected_change_revision)
        request = _snapshot(row)
        scope, purpose = _scope_seed(s, ctx, product.id, (*request.roots, *request.references))
        target, change_id = request.audience, row.change_id
        roots, refs = request.roots, request.references
        capture = _row(s, ctx, product.id, ChangeGraphCapture, payload.snapshot.id)
        graph = _graph(capture)
        if (
            capture.revision != payload.snapshot.revision
            or capture.change_id != row.change_id
            or capture.change_revision != row.revision
            or capture.change_version_id != row.id
        ):
            raise DomainError("FIXED_REFERENCE_MISMATCH", "图捕获不属于固定Change版。")
        sources = (
            *request.sources,
            *(v for h in payload.hypotheses for v in h.sources),
            *(v for v in graph_sources(graph) if v.kind == "artifact"),
        )
    if graph is not None and "closure" in capture.source_basis:
        from pdos_next.change_graph_closure import lock_dependency_clock

        lock_dependency_clock(s, ctx, scope=scope, audience=target)
    authority = _authority(s, ctx, product.id, scope, command.operation, purpose, write=True)
    reader = OwnerReader(s, ctx, product.id, scope, target, _issue_loader(s))
    graph_refs = tuple(node.ref for node in graph.nodes) if graph else ()
    for ref in (*roots, *refs, *graph_refs):
        if not reader.resolve(ref).current:
            raise DomainError("RECHECK_REQUIRED", "固定Issue、配置或执行证明待重核。")
    coverage = None
    if graph is not None and any(v.status == "complete" for v in graph.coverage):
        from pdos_next.change_coverage_binding import read_graph

        coverage = read_graph(
            s,
            ctx,
            product.id,
            request=request,
            purpose=purpose,
            graph=graph,
            saved=capture.source_basis.get("coverage"),
        )
        sources = tuple(dict.fromkeys((*sources, *coverage.sources)))
    reads = _merge_reads(
        _source_reads(sources),
        authority["required_source_read_set"],
        *(obj.reads for obj in reader.objects.values()),
        *([list(coverage.required_source_read_set)] if coverage is not None else []),
    )
    evidence, private, verified = _evidence(s, ctx, product.id, reads, sources)
    if private and target != audience(product.id, ctx.requester_id, "private"):
        raise DomainError("AUDIENCE_USE_FORBIDDEN", "私有原件不能扩大变更受众。", 403)
    bound = Bound(
        scope,
        purpose,
        target,
        change_id,
        row,
        request,
        reader,
        reads,
        tuple(sources),
        {
            "evidence": evidence,
            "runtime_stamp": stamp,
            "owners": {key: obj.source_basis for key, obj in reader.objects.items()},
        },
        authority,
        verified,
        stamp,
        graph,
        capture,
        coverage,
    )
    if coverage is not None:
        bound.source_basis["coverage"] = coverage.source_basis
    if graph is not None:
        if "closure" in capture.source_basis:
            from pdos_next.change_graph_closure import closure_stamp

            bound.source_basis["closure"] = closure_stamp(s, ctx, scope=scope, audience=target)
        _capture_valid(s, ctx, product.id, bound)
    _refresh(s, ctx, product.id, command.operation, bound)
    if require_reads and not {(r["artifact_id"], r["expected_revision"]) for r in reads} <= {
        (str(r.artifact_id), r.expected_revision) for r in command.source_read_set
    }:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "共同命令缺少固定变更完整来源读集。", 422)
    return bound


def _refresh(s, ctx, pid, operation, bound):
    # This is after all byte IO and owner/graph reads. It grants no authority from
    # a saved boolean and is called separately in each common command phase.
    # A captured closure already has the DB-owned watermark and is protected
    # by the scope gate. Re-read its direct evidence and real intervals below;
    # a second owner traversal would duplicate the complete capture.
    if "closure" not in bound.source_basis:
        fresh = OwnerReader(s, ctx, pid, bound.scope, bound.target, _issue_loader(s))
        for obj in bound.reader.objects.values():
            current = fresh.resolve(obj.ref)
            if (
                not current.current
                or digest(current.view) != digest(obj.view)
                or current.source_basis != obj.source_basis
            ):
                raise DomainError("SOURCE_STALE", "固定所有者或直接来源证明变化。")
    evidence, _, _ = _evidence(s, ctx, pid, bound.reads, bound.sources, io=False)
    value = _authority(s, ctx, pid, bound.scope, operation, bound.purpose, write=True)
    if (
        value != bound.authority
        or evidence != bound.source_basis["evidence"]
        or _runtime_stamp(s) != bound.runtime_stamp
    ):
        raise DomainError("SOURCE_STALE", "原件读取后专业资格、issuer或来源安全版本变化。")
    if bound.coverage is not None:
        from pdos_next.domain.change_coverage_owner.owner import recheck_access

        recheck_access(s, ctx, pid, bound.coverage, request=bound.request, purpose=bound.purpose)
    if "closure" in bound.source_basis:
        from pdos_next.change_graph_closure import closure_stamp

        if (
            closure_stamp(s, ctx, scope=bound.scope, audience=bound.target)
            != bound.source_basis["closure"]
        ):
            raise DomainError("RECHECK_REQUIRED", "核验期间完整依赖水位变化，请重新捕获。")
    if bound.coverage is not None:
        _valid_at(bound, now())


def _capture_valid(s, ctx, pid, bound):
    capture, graph = bound.capture, bound.graph
    if not deadline_current(capture.expires_at, now()):
        raise DomainError("GRAPH_CAPTURE_EXPIRED", "影响图已过期，请重新捕获；原图不延长。")
    saved_authority = capture.authority_snapshot
    # Captured by the same actor; the scope/operation-specific current authority
    # must match in full, including negative fact refs and revoke/restore epochs.
    if saved_authority != bound.authority:
        raise DomainError("SOURCE_STALE", "图捕获后当前专业资格依据发生变化。")
    captured_basis = capture.source_basis
    current_basis = bound.source_basis
    if (
        captured_basis["runtime_stamp"] != current_basis["runtime_stamp"]
        or any(
            current_basis["evidence"].get(key) != value
            for key, value in captured_basis["evidence"].items()
        )
        or any(
            current_basis["owners"].get(key) != value
            for key, value in captured_basis["owners"].items()
        )
        or (
            "closure" in captured_basis
            and current_basis.get("closure") != captured_basis["closure"]
        )
    ):
        raise DomainError("SOURCE_STALE", "图捕获后原件安全、来源或所有者事实发生变化。")
    fresh = OwnerReader(s, ctx, pid, bound.scope, bound.target, _issue_loader(s))
    rebuilt = capture_graph(
        fresh,
        identity=graph.id,
        roots=graph.roots,
        captured_at=graph.captured_at,
        expires_at=graph.expires_at,
        nature=graph.nature,
        sources=graph.sources,
    )
    if bound.coverage is not None:
        from pdos_next.change_coverage_binding import covered_graph, require_saved

        require_saved(captured_basis.get("coverage"), bound.coverage)
        rebuilt = covered_graph(rebuilt, bound.coverage)
    elif "coverage" in captured_basis:
        raise DomainError("COVERAGE_OWNER_STALE", "原捕获的覆盖依据必须重新核对。", 409)
    if digest(rebuilt) != digest(graph):
        raise DomainError("SOURCE_STALE", "实际所有者已读依赖图发生变化，请重新捕获。")


def validate(s, ctx, command, product, payload):
    _load(s, ctx, command, product, payload)


def _new_write(s, ctx, command, product, payload, bound):
    if product.revision != command.expected_revision:
        raise DomainError("VERSION_CONFLICT", "型号版本已变化。")
    pointer, row = _current(s, ctx, product.id, bound.change_id, lock=True)
    if isinstance(payload, ChangeCreatePayload):
        if pointer is not None:
            raise DomainError("VERSION_CONFLICT", "固定请求已存在，请回读原请求。")
    elif (
        pointer is None
        or row.id != bound.request_row.id
        or row.revision != payload.expected_change_revision
    ):
        raise DomainError("VERSION_CONFLICT", "变更前版已推进。")
    return pointer


def _kernel_payload(payload):
    if isinstance(payload, ChangeCreatePayload):
        raw = semantic(payload)
        raw.pop("visibility")
        return RequestCreate.model_validate(raw)
    return ImpactCompute(snapshot=payload.snapshot, hypotheses=payload.hypotheses)


def _kernel(ctx, bound, at, save=None):
    _valid_at(bound, at)
    return kernel(
        authority_dto(bound.authority, ctx, bound.scope, bound.target, at),
        bound.request,
        bound.reader,
        bound.verified_sources,
        bound.graph,
        save,
    )


def _valid_at(bound, at):
    if not professional.authority_time_current(bound.authority, at):
        raise DomainError("SOURCE_STALE", "专业资格在本阶段核验期间到期，请重新核对。")
    if bound.graph is not None and not deadline_current(bound.graph.expires_at, at):
        raise DomainError("GRAPH_CAPTURE_EXPIRED", "固定图在本阶段核验期间到期。")
    if bound.coverage is not None and at >= bound.coverage.valid_until:
        raise DomainError("COVERAGE_OWNER_STALE", "当前覆盖依据已到期，请重新核对。", 409)


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, bound)
    core = _kernel(ctx, bound, now())
    parsed = _kernel_payload(payload)
    preview, (after, _, _, _) = core._prepare(
        s,
        core.ports.commands.authority,
        command.operation,
        bound.change_id,
        0 if bound.request is None else bound.request.revision,
        parsed,
        None,
    )
    return {
        "operation": command.operation,
        "name": "创建固定变更请求" if bound.request is None else "计算双线影响与未知",
        "effect": preview.effect,
        "before": bound.request.model_dump(mode="json") if bound.request else None,
        "after": after.model_dump(mode="json"),
        "server_on_save": ["history.at", "version_id"],
        "read_basis": {
            "source_basis": bound.source_basis,
            "authority": bound.authority,
            "runtime_stamp": bound.runtime_stamp,
            "pure_preview_digest": preview.digest,
        },
        "required_source_read_set": bound.reads,
    }


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    pointer = _new_write(s, ctx, command, product, payload, bound)
    parsed, at = _kernel_payload(payload), now()
    result = []

    def save(mutation):
        _valid_at(bound, now())
        if _runtime_stamp(s) != bound.runtime_stamp:
            raise DomainError("SOURCE_STALE", "保存前可信运行配置发生变化。")
        request = mutation.change
        previous = bound.request_row
        row = ChangeRequestVersion(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=bound.scope.project_id,
            change_id=bound.change_id,
            revision=request.revision,
            previous_version_id=previous.id if previous else None,
            previous_revision=previous.revision if previous else None,
            owner_id=previous.owner_id if previous else ctx.requester_id,
            visibility=previous.visibility if previous else payload.visibility,
            status=request.status,
            operation=command.operation,
            intent_digest=_intent(ctx, command, payload),
            request_snapshot=request.model_dump(mode="json"),
            request_sha256=digest(request),
            sources=[v.model_dump(mode="json") for v in bound.sources],
            required_source_read_set=bound.reads,
            source_basis=bound.source_basis,
            authority_snapshot=bound.authority,
            created_at=at,
        )
        s.add(row)
        s.flush()
        if pointer is None:
            s.add(
                ChangeCurrent(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    change_id=bound.change_id,
                    version_id=row.id,
                    revision=row.revision,
                )
            )
        else:
            pointer.version_id, pointer.revision = row.id, row.revision
        s.flush()
        result.append(row)
        from pdos_next.domain.change_control.ports import Outcome

        return Outcome(subject_id=request.id, revision=request.revision, status=request.status)

    invocation = Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=bound.change_id,
        expected_revision=0 if bound.request is None else bound.request.revision,
        semantic_digest=digest(parsed),
    )
    _kernel(ctx, bound, at, save).execute(s, invocation, parsed.model_dump(mode="json"))
    if command.operation == "change.impact.compute":
        from pdos_next.change_publication_finalization import attach_impact

        attach_impact(s, ctx, command, result[0], bound)
    return result[0], "change_request", result[0].visibility


def replay_subject_type(payload):
    return "change_request"


def replay_subject(s, ctx, command, product, payload):
    # validate has already rechecked current identity/sources before common dedup.
    row = s.scalar(
        select(ChangeRequestVersion).where(
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == product.id,
            ChangeRequestVersion.operation == command.operation,
            ChangeRequestVersion.intent_digest == _intent(ctx, command, payload),
        )
    )
    if row is not None and row.visibility == "private" and row.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "原变更回执不在当前可读受众范围。", 403)
    return row


def _input_bound(s, ctx, command, product, payload):
    """Project a captured Current graph using direct sources and its DB clock.

    Actual command validation/preview/application keep their existing writer
    readers. Only this HTTP input projection uses the persisted graph proof.
    """
    from pdos_next.change_graph_closure import lock_dependency_clock
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
    from pdos_next.service import digest as caller_digest

    if (
        not isinstance(payload, ImpactComputePayload)
        or getattr(s.get_bind(), "_pdos_change_issue_loader", None) is not None
    ):
        return _load(s, ctx, command, product, payload, require_reads=False), None
    semantic(payload)
    _human(s, ctx, product.id, write=True)
    uow, caller = _uow(s), caller_digest(vars(ctx))
    row = _version(s, ctx, product.id, payload.change_id, payload.expected_change_revision)
    request = _snapshot(row)
    scope, purpose = _scope_seed(s, ctx, product.id, (*request.roots, *request.references))
    capture = _row(s, ctx, product.id, ChangeGraphCapture, payload.snapshot.id)
    if "closure" not in capture.source_basis:
        return _load(s, ctx, command, product, payload, require_reads=False), None
    graph = _graph(capture)
    if (
        capture.revision != payload.snapshot.revision
        or capture.change_id != row.change_id
        or capture.change_revision != row.revision
        or capture.change_version_id != row.id
    ):
        raise DomainError("FIXED_REFERENCE_MISMATCH", "图捕获不属于固定Change版。")
    lock_dependency_clock(s, ctx, scope=scope, audience=request.audience)
    authority = _authority(s, ctx, product.id, scope, command.operation, purpose, write=True)
    if not _capture_is_current(s, ctx, product.id, capture, request, purpose, authority):
        raise DomainError("SOURCE_STALE", "固定图的直接来源、资格或依赖水位已变化。")

    def material():
        return caller_digest({c.key: getattr(capture, c.key) for c in capture.__table__.columns})

    saved_material = material()
    basis = deepcopy(capture.source_basis)
    reader = CapturedInputReader(capture, request, graph)
    sources = tuple(
        dict.fromkeys(
            (
                *request.sources,
                *(SourceRef.model_validate(v) for v in capture.sources),
                *(v for h in payload.hypotheses for v in h.sources),
                *(v for v in graph_sources(graph) if v.kind == "artifact"),
            )
        )
    )
    reads = _merge_reads(
        capture.required_source_read_set,
        authority["required_source_read_set"],
        _source_reads(sources),
    )
    evidence, private, verified = _evidence(s, ctx, product.id, reads, sources)
    if private and request.audience != audience(product.id, ctx.requester_id, "private"):
        raise DomainError("AUDIENCE_USE_FORBIDDEN", "私有原件不能扩大变更受众。", 403)
    basis["evidence"] = evidence
    bound = Bound(
        scope,
        purpose,
        request.audience,
        row.change_id,
        row,
        request,
        reader,
        reads,
        sources,
        basis,
        authority,
        verified,
        basis["runtime_stamp"],
        graph,
        capture,
    )
    _refresh(s, ctx, product.id, command.operation, bound)

    def finish():
        _same_uow(s, uow, ctx, caller)
        if material() != saved_material or not _capture_is_current(
            s, ctx, product.id, capture, request, purpose, authority
        ):
            raise DomainError("SOURCE_STALE", "输入投影期间固定图或依赖水位已变化。")
        _human(s, ctx, product.id, write=True)
        _valid_at(bound, now())

    finish()
    return bound, finish


def inputs(s, ctx, product_id, command):
    if command.product_id != product_id or command.operation not in PAYLOADS:
        raise DomainError("FORBIDDEN_SCOPE", "变更输入不属于当前型号/操作。", 403)
    product = s.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == ctx.tenant_id)
    )
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "产品不可读取。", 403)
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    bound, finish = _input_bound(s, ctx, command, product, payload)
    blockers = []
    try:
        _new_write(s, ctx, command, product, payload, bound)
    except DomainError as error:
        blockers.append({"code": error.code, "detail": error.message})
    core = _kernel(ctx, bound, now())
    parsed = _kernel_payload(payload)
    preview, (after, _, _, _) = core._prepare(
        s,
        core.ports.commands.authority,
        command.operation,
        bound.change_id,
        0 if bound.request is None else bound.request.revision,
        parsed,
        None,
    )
    if finish is not None:
        finish()
    return {
        "operation": command.operation,
        "change_id": str(bound.change_id),
        "purpose": bound.purpose,
        "allowed": not blockers,
        "authority": bound.authority,
        "required_source_read_set": bound.reads,
        "blockers": blockers,
        "source_status": "current",
        "scope": bound.scope.model_dump(mode="json"),
        "review": {
            "before": bound.request.model_dump(mode="json") if bound.request else None,
            "after": after.model_dump(mode="json"),
            "effect": preview.effect,
            "read_basis": {"source_basis": bound.source_basis, "authority": bound.authority},
        },
    }


def _capture_response(row, *, current=True):
    graph = _graph(row)
    payload = {
        "change_id": str(row.change_id),
        "expected_change_revision": row.change_revision,
        "snapshot": {
            "id": str(row.id),
            "revision": row.revision,
            "kind": "graph_snapshot",
            "key": None,
        },
        "hypotheses": [],
    }
    return {
        "capture": {
            "id": str(row.id),
            "revision": row.revision,
            "change_id": str(row.change_id),
            "change_revision": row.change_revision,
            "graph": graph.model_dump(mode="json"),
            "expires_at": row.expires_at.isoformat() if row.expires_at is not None else None,
            "created_at": row.created_at.isoformat(),
            "current": current,
            "source_status": "current" if current else "needs_recheck",
            "owner_id": str(row.owner_id),
            "visibility": row.visibility,
            "reason": row.reason,
            "required_source_read_set": row.required_source_read_set,
            "impact_payload": payload,
        },
        "impact_payload": payload,
        "required_source_read_set": row.required_source_read_set,
    }


def prepare_capture(s, ctx, product_id, input: GraphCaptureInput):
    """Persist a recoverable fixed graph draft in caller UOW, without a Receipt."""
    s.scalar(
        select(Product)
        .where(Product.tenant_id == ctx.tenant_id, Product.id == product_id)
        .with_for_update()
    )
    _human(s, ctx, product_id, write=True)
    old = s.scalar(
        select(ChangeGraphCapture).where(
            ChangeGraphCapture.tenant_id == ctx.tenant_id,
            ChangeGraphCapture.product_id == product_id,
            ChangeGraphCapture.owner_id == ctx.requester_id,
            ChangeGraphCapture.capture_key == input.capture_key,
        )
    )
    input_digest = digest(input)
    if old is not None and old.input_digest != input_digest:
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一捕获key不能改写原请求。")
    row = _version(s, ctx, product_id, input.change_id, input.expected_change_revision)
    request = _snapshot(row)
    scope, purpose = _scope_seed(s, ctx, product_id, (*request.roots, *request.references))
    authority = _authority(s, ctx, product_id, scope, "change.impact.compute", purpose, write=True)
    stamp = _runtime_stamp(s)
    from pdos_next.change_graph_closure import closure_stamp, lock_dependency_clock

    lock_dependency_clock(s, ctx, scope=scope, audience=request.audience)
    dependency_closure = closure_stamp(s, ctx, scope=scope, audience=request.audience)
    reader = OwnerReader(s, ctx, product_id, scope, request.audience, _issue_loader(s))
    for ref in (*request.roots, *request.references):
        if not reader.resolve(ref).current:
            raise DomainError("RECHECK_REQUIRED", "固定请求依据待重核。")
    at = old.created_at if old else now()
    expiry = old.expires_at if old else None
    graph = capture_graph(
        reader,
        identity=old.id if old else uuid4(),
        roots=request.roots,
        captured_at=at,
        expires_at=expiry,
        nature="synthetic" if authority["synthetic"] else "real",
        sources=request.sources,
    )
    from pdos_next.change_coverage_binding import covered_graph, read_graph

    coverage = read_graph(
        s,
        ctx,
        product_id,
        request=request,
        purpose=purpose,
        graph=_graph(old) if old is not None and "coverage" in old.source_basis else graph,
        saved=old.source_basis.get("coverage") if old is not None else None,
        optional=old is None or "coverage" not in old.source_basis,
    )
    graph = covered_graph(graph, coverage)
    sources = tuple(dict.fromkeys((*request.sources, *(coverage.sources if coverage else ()))))
    reads = _merge_reads(
        authority["required_source_read_set"],
        _source_reads(request.sources),
        *(obj.reads for obj in reader.objects.values()),
        *([list(coverage.required_source_read_set)] if coverage is not None else []),
    )
    evidence, private, verified = _evidence(s, ctx, product_id, reads, sources)
    if private and request.audience != audience(product_id, ctx.requester_id, "private"):
        raise DomainError("AUDIENCE_USE_FORBIDDEN", "私有图来源不能扩大已固定请求受众。", 403)
    bound = Bound(
        scope,
        purpose,
        request.audience,
        row.change_id,
        row,
        request,
        reader,
        reads,
        sources,
        {
            "evidence": evidence,
            "runtime_stamp": stamp,
            "owners": {key: obj.source_basis for key, obj in reader.objects.items()},
            "closure": dependency_closure,
        },
        authority,
        verified,
        stamp,
        graph,
        coverage=coverage,
    )
    if coverage is not None:
        bound.source_basis["coverage"] = coverage.source_basis
    _refresh(s, ctx, product_id, "change.impact.compute", bound)
    if closure_stamp(s, ctx, scope=scope, audience=request.audience) != dependency_closure:
        raise DomainError("RECHECK_REQUIRED", "图读取期间依赖范围变化，请重新捕获。")
    if old is not None:
        from pdos_next.change_coverage_binding import same_capture_basis

        if (
            old.graph_sha256 != digest(graph)
            or not same_capture_basis(old.source_basis, bound.source_basis)
            or old.authority_snapshot != authority
            or old.required_source_read_set != reads
        ):
            raise DomainError("SOURCE_STALE", "原捕获的权限、来源或图已变化；不能延长或覆盖。")
        return _capture_response(old, current=deadline_current(old.expires_at))
    if not deadline_current(expiry):
        raise DomainError("GRAPH_CAPTURE_EXPIRED", "有界图读取期间有效期已结束，请重新捕获。")
    _, latest = _current(s, ctx, product_id, row.change_id, lock=True)
    if latest is None or latest.id != row.id:
        raise DomainError("VERSION_CONFLICT", "新捕获只能固定当前Change版。")
    _valid_at(bound, now())
    capture = ChangeGraphCapture(
        id=graph.id,
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        project_id=scope.project_id,
        change_id=row.change_id,
        change_version_id=row.id,
        change_revision=row.revision,
        revision=1,
        owner_id=ctx.requester_id,
        visibility=row.visibility,
        status="prepared",
        capture_key=input.capture_key,
        input_digest=input_digest,
        graph_snapshot=graph.model_dump(mode="json"),
        graph_sha256=digest(graph),
        sources=[v.model_dump(mode="json") for v in sources],
        required_source_read_set=reads,
        source_basis=bound.source_basis,
        authority_snapshot=authority,
        expires_at=expiry,
        created_at=at,
        reason=input.reason,
    )
    s.add(capture)
    s.flush()
    if bound.coverage is not None:
        from pdos_next.domain.change_coverage_owner.owner import recheck_access

        # Hold the real publisher locks and re-read its exact stamp AFTER full
        # flush and other SQL. A failure escapes the entire caller UOW.
        recheck_access(s, ctx, product_id, bound.coverage, request=request, purpose=purpose)
    # The final owner access check also performs trusted SQL in this UOW.
    # Compare scalar Current and dependency watermarks after it; row locks
    # cannot protect against this Session's own writes. No graph is rebuilt.
    from pdos_next.change_order_service import current_fixed

    _, latest = current_fixed(s, ctx, product_id, row.change_id, lock=True)
    if (latest.id, latest.revision) != (row.id, row.revision):
        raise DomainError("VERSION_CONFLICT", "图保存末端固定Change版已变化。")
    if closure_stamp(s, ctx, scope=scope, audience=request.audience) != dependency_closure:
        raise DomainError("RECHECK_REQUIRED", "图保存末端依赖水位变化。")
    if _runtime_stamp(s) != stamp:
        raise DomainError("RECHECK_REQUIRED", "图保存末端可信配置变化。")
    _valid_at(bound, now())
    return _capture_response(capture)


def _history_sources(s, ctx, pid, reads):
    from pdos_next.original_security import source_status

    current = True
    for read in reads:
        source = s.scalar(
            select(Artifact).where(
                Artifact.tenant_id == ctx.tenant_id,
                Artifact.category_id == ctx.category_id,
                Artifact.product_id.is_(None) | (Artifact.product_id == pid),
                Artifact.id == UUID(read["artifact_id"]),
            )
        )
        if source is None or (
            source.visibility == "private" and source.owner_id != ctx.requester_id
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "当前来源ACL不允许展示派生历史。", 403)
        current &= (
            source.revision == read["expected_revision"] and source_status(s, source) == "active"
        )
    return current


def _source_options(s, ctx, pid, reads, *, include_registered_native=False):
    from pdos_next.original_security import require_safe
    from pdos_next.originals import require_original
    from pdos_next.service import source_for

    options = []
    for read in reads:
        try:
            row = source_for(s, ctx, pid, UUID(read["artifact_id"]), read["expected_revision"])
            if row.original_id is None:
                if not include_registered_native:
                    continue
                _native_registration(s, ctx, pid, row)
            else:
                writing = not s.info.get("read_snapshot")
                require_safe(
                    s,
                    ctx,
                    require_original(s, ctx, pid, row.original_id, lock=writing),
                    lock=writing,
                )
        except DomainError:
            continue
        for number, line in enumerate(row.content.splitlines(), 1):
            if line.strip() and len(line) <= 4000:
                options.append(
                    {
                        "title": row.title,
                        "quote": line,
                        "source": SourceRef(
                            id=row.id,
                            revision=row.revision,
                            kind="artifact",
                            position=f"line:{number};quote_sha256:{hashlib.sha256(line.encode()).hexdigest()}",
                        ).model_dump(mode="json"),
                        "required_source_read_set": [read],
                    }
                )
    return options


def _capture_is_current(s, ctx, pid, capture, request, purpose, authority):
    """Current watermarks and real intervals; GET never rebuilds owner closure."""
    from pdos_next.change_graph_closure import closure_stamp

    basis = capture.source_basis
    if (
        not deadline_current(capture.expires_at)
        or capture.authority_snapshot != authority
        or basis.get("runtime_stamp") != _runtime_stamp(s)
        or basis.get("closure")
        != closure_stamp(s, ctx, scope=request.scope, audience=request.audience)
        or basis.get("evidence")
        != _evidence(s, ctx, pid, capture.required_source_read_set, io=False)[0]
    ):
        return False
    if "coverage" in basis:
        from pdos_next.domain.change_coverage_owner import models, owner

        saved = basis["coverage"]
        fact = s.scalar(
            select(models.ChangeCoverageFact)
            .join(
                models.ChangeCoverageCurrent,
                (models.ChangeCoverageCurrent.tenant_id == models.ChangeCoverageFact.tenant_id)
                & (models.ChangeCoverageCurrent.product_id == models.ChangeCoverageFact.product_id)
                & (models.ChangeCoverageCurrent.fact_id == models.ChangeCoverageFact.id)
                & (models.ChangeCoverageCurrent.revision == models.ChangeCoverageFact.revision),
            )
            .where(
                models.ChangeCoverageFact.tenant_id == ctx.tenant_id,
                models.ChangeCoverageFact.product_id == pid,
                models.ChangeCoverageFact.project_id == request.scope.project_id,
                models.ChangeCoverageFact.change_id == request.id,
                models.ChangeCoverageFact.id == UUID(saved["fact_id"]),
                models.ChangeCoverageFact.purpose_sha256 == digest(purpose),
            )
        )
        at = now()
        if (
            fact is None
            or fact.revision != saved["revision"]
            or fact.epoch != saved["epoch"]
            or fact.material_sha256 != saved["material_sha256"]
            or not fact.valid_from <= at < fact.valid_until
            or saved["temporal_sha256"] != owner.temporal(s, ctx, pid, request.scope)[0]
        ):
            return False
    return True


def list_changes(
    s,
    ctx,
    product_id,
    *,
    project_id=None,
    issue_id=None,
    field_feedback_id=None,
    change_id=None,
    history_cursor=None,
    capture_cursor=None,
):
    from pdos_next.capa_history import page_query, page_rows
    from pdos_next.service import require_access

    _human(s, ctx, product_id)
    if issue_id is not None and field_feedback_id is not None:
        raise DomainError("INVALID_PAYLOAD", "请分别选择问题或现场反馈作为新建变更入口。", 422)
    caller_write = True
    try:
        require_access(s, ctx, product_id, write=True)
    except DomainError:
        caller_write = False
    q = select(ChangeRequestVersion).where(
        ChangeRequestVersion.tenant_id == ctx.tenant_id,
        ChangeRequestVersion.product_id == product_id,
        (ChangeRequestVersion.visibility != "private")
        | (ChangeRequestVersion.owner_id == ctx.requester_id),
    )
    if project_id is not None:
        q = q.where(ChangeRequestVersion.project_id == project_id)
    if change_id is not None:
        q = q.where(ChangeRequestVersion.change_id == change_id)
    if issue_id is not None:
        refs = [[{"id": str(issue_id), "kind": kind}] for kind in ("issue", "capa")]
        q = q.where(
            ChangeRequestVersion.request_snapshot["roots"].contains(refs[0])
            | ChangeRequestVersion.request_snapshot["roots"].contains(refs[1])
            | ChangeRequestVersion.request_snapshot["references"].contains(refs[0])
            | ChangeRequestVersion.request_snapshot["references"].contains(refs[1])
        )
    if field_feedback_id is not None:
        fixed_ref = [{"id": str(field_feedback_id), "kind": "field_feedback"}]
        q = q.where(
            ChangeRequestVersion.request_snapshot["roots"].contains(fixed_ref)
            | ChangeRequestVersion.request_snapshot["references"].contains(fixed_ref)
        )
    joined = (
        (ChangeCurrent.tenant_id == ChangeRequestVersion.tenant_id)
        & (ChangeCurrent.product_id == ChangeRequestVersion.product_id)
        & (ChangeCurrent.change_id == ChangeRequestVersion.change_id)
        & (ChangeCurrent.version_id == ChangeRequestVersion.id)
        & (ChangeCurrent.revision == ChangeRequestVersion.revision)
    )
    current_rows = list(s.execute(q.add_columns(ChangeCurrent).join(ChangeCurrent, joined)))
    current = {row.id: pointer for row, pointer in current_rows}
    historical, history_page = page_rows(
        s.scalars(
            page_query(
                q.where(~exists(select(ChangeCurrent.id).where(joined))),
                ChangeRequestVersion.created_at,
                ChangeRequestVersion.id,
                "change",
                history_cursor,
                kinds={"change"},
            )
        ),
        "change",
        kinds={"change"},
    )
    rows = [*(row for row, _ in current_rows), *historical]
    items, captures, pointers, options, source_options, unavailable = [], [], {}, {}, [], 0
    create_authority, create_allowed = {}, False
    if issue_id is not None:
        try:
            issue_row, typed = _issue_loader(s)(s, ctx, product_id, issue_id)
            if project_id is not None and issue_row.project_id != project_id:
                raise DomainError("FORBIDDEN_SCOPE", "问题不属于筛选的项目范围。", 403)
            issue = typed.model_dump(mode="json") if hasattr(typed, "model_dump") else typed
            issue_ref = Ref(id=issue_id, revision=issue_row.revision, kind="issue")
            options[issue_ref.identity] = {
                "label": issue["issue"]["title"],
                "ref": issue_ref.model_dump(mode="json"),
            }
            capa = issue["issue"].get("capa")
            if capa:
                ref = Ref(
                    id=issue_id, revision=issue_row.revision, kind="capa", key=str(capa["id"])
                )
                options[ref.identity] = {
                    "label": "固定CAPA假设草稿",
                    "ref": ref.model_dump(mode="json"),
                }
            source_options = _source_options(s, ctx, product_id, issue["required_source_read_set"])
            scope = Scope(
                tenant_id=ctx.tenant_id, product_id=product_id, project_id=issue_row.project_id
            )
            create_authority = professional.assess(
                s,
                ctx,
                product_id,
                scope.project_id,
                "change.request.create",
                issue["purpose"],
                now(),
            )
            create_allowed = (
                caller_write
                and bool(source_options)
                and issue["source_status"] == "current"
                and create_authority["authorized"] is True
                and create_authority["qualified"] is True
            )
            if create_allowed:
                _evidence(s, ctx, product_id, issue["required_source_read_set"], io=False)
        except DomainError as error:
            if error.status == 403:
                raise
            create_authority = {
                "authorized": False,
                "qualified": None,
                "reason_codes": [error.code],
            }
            create_allowed = False
    if field_feedback_id is not None:
        from .field_bridge import current as current_feedback

        try:
            feedback_row, feedback, scope, purpose = current_feedback(
                s, ctx, product_id, field_feedback_id
            )
            if project_id is not None and scope.project_id != project_id:
                raise DomainError("FORBIDDEN_SCOPE", "现场反馈不属于筛选的实际项目。", 403)
            ref = Ref(
                id=feedback_row.feedback_id, revision=feedback_row.revision, kind="field_feedback"
            )
            options[ref.identity] = {
                "label": feedback["title"],
                "ref": ref.model_dump(mode="json"),
            }
            source_options = _source_options(
                s,
                ctx,
                product_id,
                feedback["required_source_read_set"],
                include_registered_native=True,
            )
            create_authority = professional.assess(
                s, ctx, product_id, scope.project_id, "change.request.create", purpose, now()
            )
            create_allowed = (
                caller_write
                and bool(source_options)
                and create_authority["authorized"] is True
                and create_authority["qualified"] is True
            )
            if create_allowed:
                _evidence(s, ctx, product_id, feedback["required_source_read_set"], io=False)
        except DomainError as error:
            if error.status == 403:
                raise
            create_authority = {
                "authorized": False,
                "qualified": None,
                "reason_codes": [error.code],
            }
            create_allowed = False
    ready = {}
    for row in rows:
        request = _snapshot(row)
        is_current, pointer = row.id in current, current.get(row.id)
        authority = {
            "authorized": False,
            "qualified": None,
            "reason_codes": [],
            "status": "not_evaluated_historical",
        }
        eligible = False
        try:
            source_current = _history_sources(s, ctx, product_id, row.required_source_read_set)
            if is_current:
                scope, purpose = _scope_seed(
                    s, ctx, product_id, (*request.roots, *request.references)
                )
                authority = professional.assess(
                    s, ctx, product_id, scope.project_id, "change.impact.compute", purpose, now()
                )
                eligible = (
                    caller_write
                    and source_current
                    and authority["authorized"] is True
                    and authority["qualified"] is True
                )
                if eligible:
                    ready[row.id] = (request, purpose, authority)
        except DomainError as error:
            if error.status == 403:
                unavailable += 1
                continue
            authority = {"authorized": False, "qualified": None, "reason_codes": [error.code]}
            eligible, source_current = False, False
        blockers = (
            []
            if eligible
            else [{"code": "RECHECK_REQUIRED", "detail": "当前权限、专业依据或来源需核对。"}]
        )
        items.append(
            {
                "id": str(row.id),
                "change_id": str(row.change_id),
                "revision": row.revision,
                "project_id": str(row.project_id),
                "request": request.model_dump(mode="json"),
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
                "current": is_current,
                "source_status": "current" if source_current else "needs_recheck",
                "required_source_read_set": row.required_source_read_set,
                "authority": authority,
                "capabilities": {
                    "impact_compute": eligible,
                    "order_approve": False,
                    "implementation_record": False,
                    "effectivity_record": False,
                    "verification_record": False,
                    "close": False,
                },
                "blockers": blockers,
            }
        )
        if pointer:
            pointers[str(row.change_id)] = {
                "version_id": str(pointer.version_id),
                "revision": pointer.revision,
            }
        if is_current:
            for node in (*request.roots, *request.references):
                options[node.identity] = {"label": node.kind, "ref": node.model_dump(mode="json")}
    capture_query = select(ChangeGraphCapture).where(
        ChangeGraphCapture.tenant_id == ctx.tenant_id,
        ChangeGraphCapture.product_id == product_id,
        (ChangeGraphCapture.visibility != "private")
        | (ChangeGraphCapture.owner_id == ctx.requester_id),
        ChangeGraphCapture.change_version_id.in_(q.with_only_columns(ChangeRequestVersion.id)),
    )
    current_captures = list(
        s.scalars(
            capture_query.where(
                ChangeGraphCapture.change_version_id.in_(current),
            )
        )
    )
    historical_captures, capture_history_page = page_rows(
        s.scalars(
            page_query(
                capture_query.where(ChangeGraphCapture.change_version_id.not_in(current)),
                ChangeGraphCapture.created_at,
                ChangeGraphCapture.id,
                "capture",
                capture_cursor,
                kinds={"capture"},
            )
        ),
        "capture",
        kinds={"capture"},
    )
    for capture in [*current_captures, *historical_captures]:
        try:
            visible = _history_sources(s, ctx, product_id, capture.required_source_read_set)
            reusable = visible and capture.change_version_id in ready
            if reusable:
                reusable = _capture_is_current(
                    s, ctx, product_id, capture, *ready[capture.change_version_id]
                )
            captures.append(_capture_response(capture, current=bool(reusable))["capture"])
        except DomainError as error:
            if error.status == 403:
                unavailable += 1
                continue
            captures.append(_capture_response(capture, current=False)["capture"])
    return {
        "changes": items,
        "captures": captures,
        "current_by_change": pointers,
        "reference_options": list(options.values()),
        "source_options": source_options,
        "capabilities": {"change.request.create": create_allowed},
        "authority": create_authority,
        "unavailable_count": unavailable,
        "history_page": history_page,
        "capture_history_page": capture_history_page,
        "has_more": bool(history_page["next_cursor"] or capture_history_page["next_cursor"]),
    }
