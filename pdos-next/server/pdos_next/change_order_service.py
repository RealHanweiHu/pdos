"""Staged Change participant: actual pure kernel + same-chain append, no Receipt/commit."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import uuid4
from weakref import WeakKeyDictionary

from sqlalchemy import select

from pdos_next import change_order_store as store
from pdos_next.change_completion_schemas import (
    ClosePayload,
    EffectivityPayload,
    VerificationPayload,
)
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.clock import now as server_now
from pdos_next.database import category_for_product
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.change_control.handlers import ChangeControlHandler
from pdos_next.domain.change_control.ports import Invocation, Outcome, Policy, Ports
from pdos_next.domain.change_control.rules import digest, graph_sources, replace
from pdos_next.domain.change_execution import adapters
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.graph import OwnerReader
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.request_proof import snapshot_rows
from pdos_next.schemas.change_control.contracts import (
    ChangeRequest,
    Close,
    EffectivityRecord,
    History,
    ImplementationRecord,
    OrderApprove,
    OrderPrepare,
    VerificationRecord,
)
from pdos_next.service import digest as common_digest

PAYLOADS = MappingProxyType(
    {
        "change.order.prepare": store.OrderPreparePayload,
        "change.order.approve": store.OrderApprovePayload,
        "change.implementation.record": store.ImplementationPayload,
        "change.effectivity.record": EffectivityPayload,
        "change.verification.record": VerificationPayload,
        "change.close": ClosePayload,
    }
)
EVENTS = MappingProxyType(
    {
        "change.order.prepare": "change.order_prepared",
        "change.order.approve": "change.approved",
        "change.implementation.record": "change.implementation_recorded",
        "change.effectivity.record": "change.effectivity_recorded",
        "change.verification.record": "change.verification_recorded",
        "change.close": "change.closed",
    }
)
deduplicate_subject = {"change_request"}
_PHASES = WeakKeyDictionary()


def clock():
    return server_now()


def require(test, code="SOURCE_STALE", status=409):
    if not test:
        raise DomainError(code, "正式变更的精确来源、对象、资格、政策或事务绑定未满足。", status)


def semantic(payload):
    require(type(payload) in PAYLOADS.values(), "INVALID_PAYLOAD", 422)
    value = type(payload).model_validate(payload.model_dump(mode="json")).model_dump(mode="json")
    value.pop("confirmation_token", None)
    value.pop("approval_token", None)
    return value


def configure(
    engine, *, policy_read=None, policy_refresh=None, selection_read=None, selection_refresh=None
):
    """Trusted startup callbacks only. Missing owners remain 503, no production self-grant."""
    callbacks = (policy_read, policy_refresh, selection_read, selection_refresh)
    require(all(callable(v) for v in callbacks), "CHANGE_OWNER_INTEGRATION_REQUIRED", 503)
    engine._pdos_change_order_runtime = (object(), callbacks)


def runtime(s):
    value = getattr(s.get_bind(), "_pdos_change_order_runtime", None)
    require(isinstance(value, tuple) and len(value) == 2, "CHANGE_OWNER_INTEGRATION_REQUIRED", 503)
    return (id(value[0]), old._runtime_stamp(s)), value[1]


def snapshot(row):
    value = ChangeRequest.model_validate(row.request_snapshot)
    require(
        (
            value.id,
            value.revision,
            value.scope.tenant_id,
            value.scope.product_id,
            value.scope.project_id,
            value.status,
            digest(value),
        )
        == (
            row.change_id,
            row.revision,
            row.tenant_id,
            row.product_id,
            row.project_id,
            row.status,
            row.request_sha256,
        ),
        "INTEGRITY_MISMATCH",
    )
    require(row.operation in {*old.PAYLOADS, *PAYLOADS}, "INTEGRITY_MISMATCH")
    if row.operation in old.PAYLOADS:
        require(not value.orders, "INTEGRITY_MISMATCH")
    return value


def _one(s, model, *where, lock=False, nowait=False):
    query = (
        select(model)
        .where(*where)
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    if lock:
        query = query.with_for_update(nowait=nowait)
    with s.no_autoflush:
        compiled = query.compile()
        scope_id = next(
            (
                getattr(getattr(clause, "right", None), "value", None)
                for clause in where
                if getattr(getattr(clause, "left", None), "name", None) == "product_id"
                or (
                    model is Product
                    and getattr(getattr(clause, "left", None), "name", None) == "id"
                )
            ),
            None,
        )
        values = (
            list(s.scalars(query))
            if lock
            else snapshot_rows(
                s,
                ("change-exact-row", model, str(compiled), common_digest(compiled.params)),
                query,
                scope_id=scope_id,
            )
        )
    require(len(values) == 1, "FIXED_REFERENCE_MISMATCH")
    return values[0]


def current_fixed(s, ctx, pid, identity, *, lock=False):
    pointer = _one(
        s,
        ChangeCurrent,
        ChangeCurrent.tenant_id == ctx.tenant_id,
        ChangeCurrent.product_id == pid,
        ChangeCurrent.change_id == identity,
        lock=lock,
    )
    row = _one(
        s,
        ChangeRequestVersion,
        ChangeRequestVersion.tenant_id == ctx.tenant_id,
        ChangeRequestVersion.product_id == pid,
        ChangeRequestVersion.id == pointer.version_id,
        ChangeRequestVersion.change_id == identity,
        ChangeRequestVersion.revision == pointer.revision,
    )
    require(row.visibility != "private" or row.owner_id == ctx.requester_id, "FORBIDDEN_SCOPE", 403)
    return pointer, row


def _policy(s, ctx, pid, scope, purpose, row, request, callbacks, *, previous=None):
    callback = callbacks[0 if previous is None else 1]
    value = callback(s, ctx, pid, scope=scope, purpose=purpose, request=request, previous=previous)
    require(type(value) is store.ControlledPolicy, "CHANGE_POLICY_OWNER_REQUIRED", 503)
    require(
        value.scope == scope.model_dump(mode="json")
        and value.purpose == purpose
        and value.source.kind == "artifact"
        and {"engineering", "manufacturing"} <= set(value.required_disciplines)
        and len(value.required_disciplines) == len(set(value.required_disciplines))
        and bool(value.owner_proof),
        "CHANGE_POLICY_OWNER_REQUIRED",
        503,
    )
    require(
        not (
            value.visibility == "private"
            and (row.visibility != "private" or row.owner_id != value.owner_id)
        ),
        "AUDIENCE_USE_FORBIDDEN",
        403,
    )
    require(value.valid_from <= clock() < value.valid_until, "RECHECK_REQUIRED")
    return value


def _authority(s, ctx, pid, scope, op, purpose):
    # The trusted shared owner bounds the current proof by every actual scope
    # activation/expiry boundary, including product-wide facts, not only positives.
    from pdos_next.change_controlled_owner import authority

    return authority(s, ctx, pid, scope, op, purpose, write=True)


def _actual_original_authority(s, ctx, pid, row):
    from pdos_next.change_controlled_owner import original_authority

    return original_authority(s, ctx, pid, row)


@dataclass(frozen=True, eq=False)
class PreparedChange:
    row: object
    request: ChangeRequest
    payload_semantic: dict
    scope: object
    purpose: str
    reader: object
    graph: object
    policy: store.ControlledPolicy
    selections: dict
    facts: dict
    capture: object | None
    reads: list
    sources: tuple
    source_basis: dict
    authority: dict
    runtime_stamp: tuple
    valid_until: datetime
    coverage: object = None
    completion: tuple = ()


class Facts(adapters.Facts):
    def __init__(self, phase):
        super().__init__(phase.reader, phase.source_basis["verified_sources"], phase.graph)
        self.phase = phase

    def selection(self, uow, authority, item):
        value = self.phase.selections.get(str(item.id))
        require(
            value is not None and value.item_sha256 == digest(item),
            "CHANGE_SELECTION_OWNER_REQUIRED",
            503,
        )
        require(deadline_current(value.valid_until))

    def implementation(self, uow, authority, fact_id, order, item):
        value = self.phase.facts.get(fact_id)
        require(
            value is not None and value.item_id == item.id and value.intent_id == item.intent.id,
            "IMPLEMENTATION_OWNER_REQUIRED",
            503,
        )
        return value

    def effectivity(self, uow, authority, fact_id, order, item):
        from pdos_next.schemas.change_control.contracts import EffectivityFact

        value = self.phase.facts.get(fact_id)
        require(
            type(value) is EffectivityFact and value.item_id == item.id,
            "SOURCE_STALE",
        )
        return value

    def verification(self, uow, authority, fact_id, order):
        from pdos_next.schemas.change_control.contracts import VerificationFact

        value = self.phase.facts.get(fact_id)
        require(
            type(value) is VerificationFact and value.content_digest == order.content_digest,
            "SOURCE_STALE",
        )
        return value

    def source(self, uow, authority, source):
        if source.kind == "domain" and any(
            source in value.owner.verified_domain_sources for value in self.phase.completion
        ):
            from pdos_next.domain.change_control.ports import Currentness

            return Currentness(current=True)
        return super().source(uow, authority, source)


class Policies:
    def __init__(self, phase):
        self.phase = phase

    def assess(self, uow, authority, request):
        return Policy(
            source=self.phase.policy.source,
            required_disciplines=self.phase.policy.required_disciplines,
        )


class Commands(adapters.Commands):
    def __init__(self, authority, request, *, confirm=None, save=None):
        super().__init__(authority, request, save)
        self.actual_confirm = confirm

    def confirm(self, uow, invocation, preview, authority):
        require(callable(self.actual_confirm), "CHANGE_CONSUMED_PROOF_REQUIRED", 503)
        self.actual_confirm()


def kernel(ctx, phase, at, *, confirm=None, save=None):
    authority = adapters.authority_dto(
        phase.authority, ctx, phase.scope, phase.request.audience, at
    )
    return ChangeControlHandler(
        Ports(
            Commands(authority, phase.request, confirm=confirm, save=save),
            Facts(phase),
            Policies(phase),
        )
    )


def parsed_payload(payload, ctx=None, request=None):
    if type(payload) is store.OrderPreparePayload:
        return OrderPrepare(
            assessment_id=payload.assessment_id, plan=payload.plan, reason=payload.reason
        )
    if type(payload) is store.OrderApprovePayload:
        return OrderApprove(
            discipline=payload.discipline, text=payload.text, expires_at=payload.expires_at
        )
    if type(payload) is ClosePayload:
        return Close(text=payload.text)
    if type(payload) in {EffectivityPayload, VerificationPayload}:
        from pdos_next.change_completion_owner import fact_id

        require(ctx is not None and request is not None and bool(request.orders), "INVALID_STATE")
        identity = fact_id(payload, request.orders[-1], ctx.actor_id)
        return (
            EffectivityRecord(item_id=payload.item_id, fact_id=identity)
            if type(payload) is EffectivityPayload
            else VerificationRecord(fact_id=identity, text=payload.text)
        )
    return ImplementationRecord(item_id=payload.item_id, fact_id=payload.fact_id)


def read_phase(
    s, ctx, command, payload, *, require_reads=True, current_cas=False, complete_recheck=False
):
    from pdos_next.change_implementation_owner import read_capture

    uow = _uow(s)
    require(type(payload) is PAYLOADS.get(command.operation), "INVALID_PAYLOAD", 422)
    old._human(s, ctx, command.product_id, write=True)
    stamp, callbacks = runtime(s)
    row = old._version(
        s, ctx, command.product_id, payload.change_id, payload.expected_change_revision
    )
    request = snapshot(row)
    pointer, current = current_fixed(
        s, ctx, command.product_id, payload.change_id, lock=current_cas
    )
    if current_cas:
        require(
            (pointer.version_id, pointer.revision) == (row.id, row.revision), "VERSION_CONFLICT"
        )
    require(payload.visibility == row.visibility, "CHANGE_AUDIENCE_MISMATCH", 403)
    scope, purpose = old._seed(s, ctx, command.product_id, (*request.roots, *request.references))
    require(scope == request.scope, "FORBIDDEN_SCOPE", 403)
    project = _one(
        s,
        Project,
        Project.tenant_id == ctx.tenant_id,
        Project.product_id == command.product_id,
        Project.id == scope.project_id,
    )
    project_stamp = (
        project.id,
        project.tenant_id,
        project.product_id,
        project.owner_id,
        project.visibility,
        project.scope,
        project.status,
    )
    require(
        project.status == "active"
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    reader = OwnerReader(s, ctx, command.product_id, scope, request.audience, old._issue_loader(s))
    sources = list(request.sources)
    graph = request.assessments[-1].graph if request.assessments else None
    refs = [*request.roots, *request.references]
    if graph is not None:
        sources.extend(graph_sources(graph))
        refs.extend(n.ref for n in graph.nodes)
    require(graph is not None, "IMPACT_UNKNOWN")
    from pdos_next.change_graph_closure import lock_dependency_clock, recheck_graph_closure

    lock_dependency_clock(s, ctx, scope=scope, audience=request.audience)

    coverage = None
    coverage_refresh = None
    completing = type(payload) in {EffectivityPayload, VerificationPayload, ClosePayload}
    implementing = type(payload) is store.ImplementationPayload or completing
    if implementing:
        from pdos_next.change_coverage_binding import read_retained_graph, refresh_retained_graph

        coverage = read_retained_graph(
            s,
            ctx,
            command.product_id,
            request=request,
            purpose=purpose,
            graph=graph,
            saved=row.source_basis.get("coverage"),
        )
    elif any(v.status != "unknown" for v in graph.coverage) or any(
        value.status != "unknown" for value in graph.path_applicability
    ):
        from pdos_next.change_coverage_binding import read_graph, refresh_graph

        def coverage_refresh(session, caller, pid, *, graph, current_graph, reader):
            nonlocal coverage
            require(session is s and caller is ctx and pid == command.product_id)
            # The owner re-traverses the actual registry against the saved graph;
            # closure additionally compares the freshly traversed graph below.
            if coverage is None:
                coverage = read_graph(
                    session,
                    caller,
                    pid,
                    request=request,
                    purpose=purpose,
                    graph=graph,
                    saved=row.source_basis.get("coverage"),
                )
            else:
                coverage = refresh_graph(
                    session,
                    caller,
                    pid,
                    coverage,
                    request=request,
                    purpose=purpose,
                    graph=graph,
                )
            return coverage.coverage
    elif "coverage" in row.source_basis:
        require(False, "COVERAGE_OWNER_STALE")

    # The persisted server stamp fences invisible/new reverse dependencies and
    # ABA. A legacy graph remains readable but cannot attest a new named order.
    closure = (
        None
        if implementing
        else recheck_graph_closure(
            s,
            ctx,
            command,
            graph=graph,
            scope=scope,
            audience=request.audience,
            roots=request.roots,
            expected_closure=row.source_basis.get("closure"),
            valid_until=graph.expires_at,
            coverage_refresh=coverage_refresh,
            complete_recheck=complete_recheck,
        )
    )
    if coverage is not None:
        sources.extend(coverage.sources)
    policy = _policy(s, ctx, command.product_id, scope, purpose, row, request, callbacks)
    sources.append(policy.source)
    items = (
        payload.plan.items
        if type(payload) is store.OrderPreparePayload
        else request.orders[-1].plan.items
        if request.orders
        else ()
    )
    selections = {}
    for item in items:
        refs.extend((*item.selection.objects, *item.intent.basis))
        sources.extend(item.selection.sources)
        value = callbacks[2](
            s,
            ctx,
            command.product_id,
            scope=scope,
            purpose=purpose,
            item=item,
            request=request,
            previous=None,
        )
        require(
            type(value) is store.SelectionProof
            and value.scope == scope.model_dump(mode="json")
            and value.item_sha256 == digest(item)
            and bool(value.owner_proof),
            "CHANGE_SELECTION_OWNER_REQUIRED",
            503,
        )
        selections[str(item.id)] = value
        sources.extend(value.sources)
    dispositions = (
        payload.plan.dispositions
        if type(payload) is store.OrderPreparePayload
        else request.orders[-1].plan.dispositions
        if request.orders
        else ()
    )
    for disposition in dispositions:
        refs.append(disposition.object)
        sources.extend(disposition.sources)
    for ref in refs:
        require(reader.resolve(ref).current, "RECHECK_REQUIRED")
    facts, capture, outputs, captures = {}, None, {}, []
    originals = []
    original_deadlines = []
    saved_reads = [row.required_source_read_set]
    for order in request.orders:
        original = _one(
            s,
            store.ChangeOrderRecord,
            store.ChangeOrderRecord.tenant_id == ctx.tenant_id,
            store.ChangeOrderRecord.product_id == command.product_id,
            store.ChangeOrderRecord.change_id == request.id,
            store.ChangeOrderRecord.order_id == order.id,
        )
        original_deadlines.append(_actual_original_authority(s, ctx, command.product_id, original))
        originals.append(original)
        saved_reads.append(original.required_source_read_set)
        require(
            original.order_snapshot["content_digest"] == order.content_digest, "INTEGRITY_MISMATCH"
        )
        for approval in order.approvals:
            saved = _one(
                s,
                store.ChangeApprovalRecord,
                store.ChangeApprovalRecord.tenant_id == ctx.tenant_id,
                store.ChangeApprovalRecord.product_id == command.product_id,
                store.ChangeApprovalRecord.change_id == request.id,
                store.ChangeApprovalRecord.order_id == order.id,
                store.ChangeApprovalRecord.discipline == approval.discipline,
            )
            require(
                saved.approval_snapshot == approval.model_dump(mode="json")
                and saved.shared_proof_id == approval.decision_id,
                "INTEGRITY_MISMATCH",
            )
            original_deadlines.append(_actual_original_authority(s, ctx, command.product_id, saved))
            saved_reads.append(saved.required_source_read_set)
            sources.extend(approval.sources)
        for fact in order.implementations:
            saved = read_capture(
                s, ctx, command.product_id, request, order, fact.id, new_write=False
            )
            facts[fact.id] = saved.fact
            captures.append(saved)
            sources.extend(saved.fact.sources)
            outputs[str(fact.id)] = saved.output_basis
            for ref in saved.fact.outputs:
                require(reader.resolve(ref).current, "RECHECK_REQUIRED")
    if type(payload) is store.OrderApprovePayload:
        sources.extend(payload.sources)
    if type(payload) is store.ImplementationPayload:
        require(bool(request.orders), "INVALID_STATE")
        capture = read_capture(
            s,
            ctx,
            command.product_id,
            request,
            request.orders[-1],
            payload.fact_id,
            new_write=current_cas,
        )
        facts[capture.fact.id] = capture.fact
        captures.append(capture)
        sources.extend(capture.fact.sources)
        outputs[str(capture.fact.id)] = capture.output_basis
        for ref in capture.fact.outputs:
            require(reader.resolve(ref).current, "RECHECK_REQUIRED")
        from pdos_next.change_graph_closure import recheck_implementation_closure

        closure = recheck_implementation_closure(
            s,
            ctx,
            command,
            request=request,
            graph=graph,
            expected_closure=row.source_basis.get("closure"),
            captures=tuple(captures),
            retained_coverage=coverage,
        )
    completion = []
    if completing:
        from pdos_next.change_completion_owner import CompletionRead, read_native, read_recorded

        require(bool(request.orders), "INVALID_STATE")
        for order in request.orders:
            for fact in order.effectivity:
                completion.append(
                    read_recorded(
                        s,
                        ctx,
                        command.product_id,
                        request,
                        order,
                        fact,
                        "change.effectivity.record",
                        at=clock(),
                    )
                )
            for verification in order.verifications:
                completion.append(
                    read_recorded(
                        s,
                        ctx,
                        command.product_id,
                        request,
                        order,
                        verification.fact,
                        "change.verification.record",
                        at=clock(),
                    )
                )
        if type(payload) in {EffectivityPayload, VerificationPayload}:
            native = read_native(
                s, ctx, command.product_id, request, request.orders[-1], payload, at=clock()
            )
            completion.append(CompletionRead(native.fact, payload, native))
        for value in completion:
            facts[value.fact.id] = value.fact
            sources.extend(value.owner.sources)
            saved_reads.append(list(value.owner.required_source_read_set))
            for ref in value.owner.actual_refs:
                require(reader.resolve(ref).current, "RECHECK_REQUIRED")
        from pdos_next.change_completion_closure import recheck_completion_closure

        closure = recheck_completion_closure(
            s,
            ctx,
            command,
            request=request,
            graph=graph,
            expected_closure=row.source_basis.get("closure"),
            captures=tuple(captures),
            completion=tuple(completion),
            retained_coverage=coverage,
        )
    sources = tuple(dict.fromkeys(sources))
    authority, authority_until = _authority(
        s, ctx, command.product_id, scope, command.operation, purpose
    )
    nature = graph.nature if graph else None
    require(nature in {"real", "synthetic"}, "IMPACT_UNKNOWN")
    require(
        policy.nature == nature
        and all(v.nature == nature for v in selections.values())
        and (nature != "real" or authority.get("synthetic") is False),
        "NATURE_MISMATCH",
        403,
    )
    reads = _merge_reads(
        *saved_reads,
        list(closure.required_source_read_set),
        old._source_reads(sources),
        list(policy.required_source_read_set),
        authority["required_source_read_set"],
        *([list(coverage.required_source_read_set)] if coverage is not None else []),
        *[o.reads for o in reader.objects.values()],
        *[list(v.required_source_read_set) for v in selections.values()],
        *([capture.row.required_source_read_set] if capture is not None else []),
    )
    basis, private, verified = old._evidence(s, ctx, command.product_id, reads, sources)
    require(not private or row.visibility == "private", "AUDIENCE_USE_FORBIDDEN", 403)
    if coverage is not None:
        coverage = (refresh_retained_graph if implementing else refresh_graph)(
            s,
            ctx,
            command.product_id,
            coverage,
            request=request,
            purpose=purpose,
            graph=graph,
        )
    # Everything with actual owner IO has finished. Recheck each trusted current callback,
    # every old signer, source security metadata, caller, runtime and the UOW again.
    require(
        _policy(
            s, ctx, command.product_id, scope, purpose, row, request, callbacks, previous=policy
        )
        == policy
    )
    for item in items:
        require(
            callbacks[3](
                s,
                ctx,
                command.product_id,
                scope=scope,
                purpose=purpose,
                item=item,
                request=request,
                previous=selections[str(item.id)],
            )
            == selections[str(item.id)]
        )
    if completion:
        from pdos_next.change_completion_owner import read_native, read_recorded

        for value in completion:
            order = next(
                o
                for o in request.orders
                if any(
                    item.id
                    in (
                        {value.fact.item_id}
                        if hasattr(value.fact, "item_id")
                        else set(value.fact.item_ids)
                    )
                    for item in o.plan.items
                )
            )
            refreshed = (
                read_native(
                    s,
                    ctx,
                    command.product_id,
                    request,
                    order,
                    value.payload,
                    at=clock(),
                    identity=value.fact.id,
                )
                if value.row is None
                else read_recorded(
                    s,
                    ctx,
                    command.product_id,
                    request,
                    order,
                    value.fact,
                    value.row.operation,
                    at=clock(),
                ).owner
            )
            require(refreshed == value.owner, "RECHECK_REQUIRED")
    # Fresh owner reads after all bytes: no stale ORM/phase memo can silently
    # retain a changed configuration or previously checked approval signer.
    fresh_reader = OwnerReader(
        s, ctx, command.product_id, scope, request.audience, old._issue_loader(s)
    )
    for obj in reader.objects.values():
        require(fresh_reader.resolve(obj.ref) == obj, "SOURCE_STALE")
    for original in originals:
        original_deadlines.append(_actual_original_authority(s, ctx, command.product_id, original))
    for order in request.orders:
        for approval in order.approvals:
            signed = _one(
                s,
                store.ChangeApprovalRecord,
                store.ChangeApprovalRecord.tenant_id == ctx.tenant_id,
                store.ChangeApprovalRecord.product_id == command.product_id,
                store.ChangeApprovalRecord.change_id == request.id,
                store.ChangeApprovalRecord.order_id == order.id,
                store.ChangeApprovalRecord.discipline == approval.discipline,
            )
            original_deadlines.append(
                _actual_original_authority(s, ctx, command.product_id, signed)
            )
    latest_authority, latest_until = _authority(
        s, ctx, command.product_id, scope, command.operation, purpose
    )
    require(latest_authority == authority)
    latest_basis, latest_private, latest_verified = old._evidence(
        s, ctx, command.product_id, reads, sources, io=False
    )
    require(latest_basis == basis and latest_private == private and latest_verified == verified)
    old._human(s, ctx, command.product_id, write=True)
    final_pointer, _ = current_fixed(s, ctx, command.product_id, request.id)
    require(
        (final_pointer.id, final_pointer.version_id, final_pointer.revision)
        == (pointer.id, pointer.version_id, pointer.revision)
    )
    person = _one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.requester_id
    )
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(command.product_id),
        Grant.principal_id == ctx.requester_id,
    )
    require(
        person.active is True and person.kind == "human" and grant.can_write is True,
        "FORBIDDEN_SCOPE",
        403,
    )
    project = _one(
        s,
        Project,
        Project.tenant_id == ctx.tenant_id,
        Project.product_id == command.product_id,
        Project.id == scope.project_id,
    )
    require(
        (
            project.id,
            project.tenant_id,
            project.product_id,
            project.owner_id,
            project.visibility,
            project.scope,
            project.status,
        )
        == project_stamp
        and (project.visibility != "private" or project.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    require(runtime(s)[0] == stamp)
    if coverage is not None:
        from pdos_next.domain.change_coverage_owner.owner import recheck_access

        recheck_access(s, ctx, command.product_id, coverage, request=request, purpose=purpose)
    from pdos_next.change_graph_closure import closure_stamp

    require(
        closure_stamp(s, ctx, scope=scope, audience=request.audience) == closure.closure,
        "RECHECK_REQUIRED",
    )
    _same_uow(s, uow, ctx, __import__("pdos_next.service", fromlist=["digest"]).digest(vars(ctx)))
    until = earliest_deadline(
        grant.expires_at,
        authority_until,
        latest_until,
        *original_deadlines,
        policy.valid_until,
        graph.expires_at,
        *[o.plan.expires_at for o in request.orders],
        *[a.expires_at for o in request.orders for a in o.approvals],
        *[v.valid_until for v in selections.values()],
        *([capture.row.expires_at] if current_cas and capture is not None else []),
        *([coverage.valid_until] if coverage is not None else []),
    )
    require(clock() < until)
    if require_reads:
        supplied = [reference.model_dump(mode="json") for reference in command.source_read_set]
        require(
            _merge_reads(supplied, reads) == _merge_reads(supplied),
            "MISSING_REQUIRED_EVIDENCE",
        )
    return PreparedChange(
        row,
        request,
        semantic(payload),
        scope,
        purpose,
        reader,
        graph,
        policy,
        selections,
        facts,
        capture,
        reads,
        sources,
        {
            "artifacts": basis,
            "owners": {str(k): v.source_basis for k, v in reader.objects.items()},
            "outputs": outputs,
            **(
                {"completion": {str(v.fact.id): v.owner.source_basis for v in completion}}
                if completion
                else {}
            ),
            "verified_sources": sorted(verified),
            "closure": closure.closure,
            **({"coverage": coverage.source_basis} if coverage is not None else {}),
        },
        authority,
        stamp,
        until,
        coverage,
        tuple(completion),
    )


def _proposed_snapshot(after, before, operation):
    proposed = after.model_dump(mode="json")
    for history in proposed["history"][len(before.history) :]:
        history["at"] = "server_on_save"
    if operation == "change.order.approve":
        approval = proposed["orders"][-1]["approvals"][-1]
        approval["at"] = "server_on_save"
        approval["decision_id"] = "actual_consumed_named_proof_on_save"
    if operation == "change.verification.record":
        verification = proposed["orders"][-1]["verifications"][-1]
        verification["at"] = "server_on_save"
        verification["decision_id"] = "actual_consumed_named_proof_on_save"
    if operation == "change.close":
        proposed["orders"][-1]["closure"]["at"] = "server_on_save"
    return proposed


def _review(ctx, command, payload, phase):
    parsed = parsed_payload(payload, ctx, phase.request)
    # Core preview is a proposal, not an actual decision/proof. Its provisional UUID
    # and appended server evaluation clock are labelled; real source clocks stay exact.
    preview, (after, _, _, event) = kernel(ctx, phase, clock())._prepare(
        None,
        adapters.authority_dto(phase.authority, ctx, phase.scope, phase.request.audience, clock()),
        command.operation,
        phase.request.id,
        phase.request.revision,
        parsed,
        phase.request.id,
    )
    if event is not None:
        after = replace(
            after,
            revision=phase.request.revision + 1,
            history=(
                *after.history,
                History(
                    command_id=command.command_id,
                    operation=command.operation,
                    actor_id=ctx.actor_id,
                    at=clock(),
                    from_state=phase.request.status,
                    to_state=after.status,
                    note=preview.effect,
                ),
            ),
        )
    proposed = _proposed_snapshot(after, phase.request, command.operation)
    return {
        "operation": command.operation,
        "payload_semantic": phase.payload_semantic,
        "before": phase.request.model_dump(mode="json"),
        "after": proposed,
        "read_set": deepcopy(phase.reads),
        "sources": [v.model_dump(mode="json") for v in phase.sources],
        "authority": deepcopy(phase.authority),
        "policy": phase.policy.model_dump(mode="json"),
        "source_basis": deepcopy(phase.source_basis),
        "selection": [v.model_dump(mode="json") for v in phase.selections.values()],
        "effect": preview.effect,
        "unknown": list(preview.unknown),
        "proof_tier": "T2"
        if command.operation
        in {"change.order.approve", "change.verification.record", "change.close"}
        else "T1",
    }


def validate(s, ctx, command, product, payload):
    phase = read_phase(s, ctx, command, payload)
    kernel(ctx, phase, clock()).preview(
        s,
        command.operation,
        phase.request.id,
        phase.request.revision,
        parsed_payload(payload, ctx, phase.request),
    )


def prepare_preview(s, ctx, command, product, payload):
    require(
        command.product_id == product.id and command.expected_revision == product.revision,
        "VERSION_CONFLICT",
    )
    return read_phase(s, ctx, command, payload, current_cas=True)


def preview_prepared(s, ctx, command, product, payload, phase):
    return _review(ctx, command, payload, phase)


def preview_view(s, ctx, command, product, payload):
    require(
        command.product_id == product.id and command.expected_revision == product.revision,
        "VERSION_CONFLICT",
    )
    return _review(ctx, command, payload, read_phase(s, ctx, command, payload, current_cas=True))


def prepare_write_review(s, ctx, command, product, payload, proof):
    phase = read_phase(
        s,
        ctx,
        command,
        payload,
        current_cas=True,
        complete_recheck=command.operation == "change.order.approve",
    )
    reviewed = _review(ctx, command, payload, phase)
    require(proof.snapshot == reviewed, "CONFIRMATION_SCOPE_CHANGED")
    _PHASES.setdefault(s, {})[id(phase)] = (
        phase,
        _uow(s),
        deepcopy(reviewed),
        command.model_dump(mode="json"),
    )
    return phase, reviewed


def _require_phase(s, ctx, command, payload, phase):
    value = _PHASES.get(s, {}).get(id(phase))
    require(
        value is not None and value[0] is phase and value[3] == command.model_dump(mode="json"),
        "CHANGE_PREPARED_PHASE_REQUIRED",
        503,
    )
    _same_uow(
        s, value[1], ctx, __import__("pdos_next.service", fromlist=["digest"]).digest(vars(ctx))
    )
    require(semantic(payload) == phase.payload_semantic)
    return value


def stage_mutation(s, ctx, command, payload, phase, mutation, marker, *, at, final_guard=None):
    """No commit/Receipt. Shared executor supplies its actual common consumption marker."""
    require(
        mutation.expected_revision == phase.row.revision
        and mutation.change.revision == phase.row.revision + 1
        and not mutation.insert
        and mutation.event_name == EVENTS[command.operation],
        "INTEGRITY_MISMATCH",
    )
    require(at < earliest_deadline(phase.valid_until, marker.expires_at))
    require(
        (
            mutation.change.id,
            mutation.change.scope,
            mutation.change.audience,
            mutation.change.requester_id,
        )
        == (
            phase.request.id,
            phase.request.scope,
            phase.request.audience,
            phase.request.requester_id,
        ),
        "INTEGRITY_MISMATCH",
    )
    pointer, current = current_fixed(s, ctx, command.product_id, phase.row.change_id, lock=True)
    require(
        (current.id, current.revision) == (phase.row.id, phase.row.revision), "VERSION_CONFLICT"
    )
    parent = None
    if command.operation != "change.order.prepare":
        parent = _one(
            s,
            store.ChangeOrderRecord,
            store.ChangeOrderRecord.tenant_id == ctx.tenant_id,
            store.ChangeOrderRecord.product_id == command.product_id,
            store.ChangeOrderRecord.change_id == mutation.change.id,
            store.ChangeOrderRecord.order_id == mutation.change.orders[-1].id,
        )
    # Current and original Order lookups are the last SQL owner reads. Capture the actual save clock
    # afterwards; a slow query must not spend an expired proof using an earlier clock.
    if final_guard is not None:
        final_guard()  # Actual common marker/UOW only; no source-result cache.
    saved_at = clock()
    require(at <= saved_at < earliest_deadline(phase.valid_until, marker.expires_at))
    request = mutation.change
    row = ChangeRequestVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=command.product_id,
        project_id=phase.scope.project_id,
        change_id=request.id,
        revision=request.revision,
        previous_version_id=phase.row.id,
        previous_revision=phase.row.revision,
        owner_id=phase.row.owner_id,
        visibility=phase.row.visibility,
        status=request.status,
        operation=command.operation,
        intent_digest=old._intent(ctx, command, payload),
        request_snapshot=request.model_dump(mode="json"),
        request_sha256=digest(request),
        sources=[v.model_dump(mode="json") for v in phase.sources],
        required_source_read_set=deepcopy(phase.reads),
        source_basis=deepcopy(phase.source_basis),
        authority_snapshot=deepcopy(phase.authority),
        created_at=saved_at,
    )
    fields = dict(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=command.product_id,
        project_id=phase.scope.project_id,
        change_id=request.id,
        change_version_id=row.id,
        change_revision=row.revision,
        revision=1,
        owner_id=row.owner_id,
        visibility=row.visibility,
        actor_id=ctx.actor_id,
        operation=command.operation,
        command_id=command.command_id,
        **marker.storage_columns(),
        sources=deepcopy(row.sources),
        required_source_read_set=deepcopy(phase.reads),
        source_basis=deepcopy(phase.source_basis),
        authority_snapshot=deepcopy(phase.authority),
        policy_snapshot=phase.policy.model_dump(mode="json"),
        input_snapshot={
            "semantic": semantic(payload),
            "shared_proof": {"id": str(marker.proof_id), "tier": marker.tier},
            "review": _review(ctx, command, payload, phase),
        },
        created_at=saved_at,
    )
    order = request.orders[-1]
    if command.operation == "change.order.prepare":
        atom = store.ChangeOrderRecord(
            **fields,
            order_id=order.id,
            content_sha256=order.content_digest,
            order_snapshot=order.model_dump(mode="json"),
        )
    else:
        if command.operation == "change.order.approve":
            approval = order.approvals[-1]
            require(
                approval.decision_id == marker.proof_id
                and approval.actor_id == ctx.actor_id
                and marker.tier == "T2",
                "CHANGE_CONSUMED_PROOF_REQUIRED",
                503,
            )
            atom = store.ChangeApprovalRecord(
                **fields,
                order_id=order.id,
                order_record_id=parent.id,
                discipline=approval.discipline,
                approval_snapshot=approval.model_dump(mode="json"),
            )
        elif command.operation in {
            "change.effectivity.record",
            "change.verification.record",
            "change.close",
        }:
            if command.operation == "change.effectivity.record":
                fact = order.effectivity[-1]
                item_id = fact.item_id
            else:
                fact = order.verifications[-1].fact
                item_id = None
            native = next((v for v in phase.completion if v.fact == fact), None)
            require(native is not None, "SOURCE_STALE")
            require(
                marker.tier == ("T1" if item_id is not None else "T2"),
                "CHANGE_CONSUMED_PROOF_REQUIRED",
                503,
            )
            if command.operation == "change.verification.record":
                require(
                    order.verifications[-1].decision_id == marker.proof_id
                    and fact.verifier_id == ctx.actor_id,
                    "CHANGE_CONSUMED_PROOF_REQUIRED",
                    503,
                )
            atom = store.ChangeCompletionRecord(
                **fields,
                order_id=order.id,
                order_record_id=parent.id,
                item_id=item_id,
                fact_id=fact.id,
                fact_snapshot=fact.model_dump(mode="json"),
                native_input=semantic(native.payload),
                owner_basis=deepcopy(native.owner.source_basis),
            )
        else:
            fact = order.implementations[-1]
            require(
                phase.capture is not None
                and phase.capture.fact == fact
                and fact.executor_id == ctx.actor_id
                and marker.tier == "T1",
                "IMPLEMENTATION_OWNER_REQUIRED",
                503,
            )
            atom = store.ChangeImplementationRecord(
                **fields,
                order_id=order.id,
                order_record_id=parent.id,
                item_id=fact.item_id,
                fact_id=fact.id,
                capture_id=phase.capture.row.id,
                fact_snapshot=fact.model_dump(mode="json"),
                output_basis=deepcopy(phase.capture.output_basis),
            )
    s.add(row)
    s.flush([row])  # Actual candidate trigger validates parent before pointer flush.
    s.add(atom)
    pointer.version_id, pointer.revision = row.id, row.revision
    return row


def apply_prepared(s, ctx, command, product, payload, phase, proof, host, module, binding, marker):
    saved = _require_phase(s, ctx, command, payload, phase)
    host.require_live(s, ctx, command, payload, module, proof, binding=binding, marker=marker)
    fresh = read_phase(s, ctx, command, payload, current_cas=True)
    require(_review(ctx, command, payload, fresh) == saved[2], "CONFIRMATION_SCOPE_CHANGED")
    host.require_live(s, ctx, command, payload, module, proof, binding=binding, marker=marker)
    at = clock()
    require(at < earliest_deadline(fresh.valid_until, marker.expires_at))
    result = []

    def save(mutation):
        # Kernel confirm was the genuine common consume; all owner IO is done.
        host.require_live(s, ctx, command, payload, module, proof, binding=binding, marker=marker)
        result.append(
            stage_mutation(
                s,
                ctx,
                command,
                payload,
                fresh,
                mutation,
                marker,
                at=at,
                final_guard=lambda: host.require_live(
                    s, ctx, command, payload, module, proof, binding=binding, marker=marker
                ),
            )
        )
        return Outcome(
            subject_id=mutation.change.id,
            revision=mutation.change.revision,
            status=mutation.change.status,
        )

    core = parsed_payload(payload, ctx, phase.request)
    invocation = Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=phase.request.id,
        expected_revision=phase.request.revision,
        semantic_digest=digest(core),
        confirmation_token=getattr(payload, "confirmation_token", None)
        or getattr(payload, "approval_token", None),
        decision_id=marker.proof_id if marker.tier == "T2" else None,
    )
    kernel(
        ctx,
        fresh,
        at,
        confirm=lambda: host.require_live(
            s, ctx, command, payload, module, proof, binding=binding, marker=marker
        ),
        save=save,
    ).execute(s, invocation, core.model_dump(mode="json"))
    from pdos_next.change_publication_finalization import attach_formal

    attach_formal(
        s,
        ctx,
        command,
        result[0],
        fresh,
        consumer=host,
        module=module,
        proof=proof,
        binding=binding,
        marker=marker,
    )
    _PHASES[s].pop(id(phase))
    return result[0], "change_request", result[0].visibility


def replay_subject_type(payload):
    return "change_request"


def replay_subject(s, ctx, command, product, payload):
    phase = read_phase(s, ctx, command, payload)
    # Guards precede historical receipt lookup; no CAS against old expected current,
    # no second proof consumption. Common executor retains request-key collision rules.
    row = s.scalar(
        select(ChangeRequestVersion).where(
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == command.product_id,
            ChangeRequestVersion.owner_id == phase.row.owner_id,
            ChangeRequestVersion.operation == command.operation,
            ChangeRequestVersion.intent_digest == old._intent(ctx, command, payload),
        )
    )
    return row


def inputs(s, ctx, pid, command):
    require(command.product_id == pid, "FORBIDDEN_SCOPE", 403)
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    phase = read_phase(s, ctx, command, payload, require_reads=False, current_cas=True)
    value = command.model_dump(mode="json")
    value["source_read_set"] = phase.reads
    return {"allowed": True, "command": value, "review": _review(ctx, command, payload, phase)}
