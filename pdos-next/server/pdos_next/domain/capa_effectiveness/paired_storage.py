"""Staged actual storage structure reader; no HostGate, writer or effect port.

Current read ACL and private scope are real. Numerical snapshots are checked by
existing owners, but original bytes, historical authority and retained effects
still need the future trusted reader's independent refresh/attest.
"""

from pdos_next.database import category_for_product


# Initialize the actual common registry before importing its domain children.
# ruff: noqa: I001

from datetime import UTC, datetime
from uuid import UUID

from pdos_next.service import Context, digest, require_access

from . import paired as p
from pdos_next.domain.builds import service as builds
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.models import FormalVerificationCurrent
from pdos_next.domain.verification_launch import service as launch
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import TestResultActionFact, TestResultProjection
from pdos_next.errors import DomainError
from pdos_next.receipt_request_binding import readable_receipt_request_bound
from pdos_next.models import Audit, Grant, Outbox, Principal, Product, Receipt, RequestKey, now
from pydantic import ValidationError
from sqlalchemy import and_, select
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.orm import Session, SessionTransaction


def _missing(code, detail):
    raise DomainError(code, detail, 503)


def _uow(s):
    if not isinstance(s, Session) or s.is_active is not True:
        _missing("CALLER_UOW_REQUIRED", "配对材料须由实际调用者Session读取。")
    # SQLAlchemy get_transaction itself traverses _parent without cycle checks.
    # Bound that actual internal chain before calling the public getters. No
    # transaction is created, closed or repaired here; corrupt state is denied.
    chain, seen, ancestor = [], set(), s._transaction
    while ancestor is not None:
        if (
            not isinstance(ancestor, SessionTransaction)
            or ancestor.session is not s
            or ancestor.is_active is not True
            or id(ancestor) in seen
            or len(chain) >= 64
        ):
            _missing(
                "CALLER_UOW_REQUIRED", "配对读取的完整子事务祖先链必须保持活动且属于本Session。"
            )
        seen.add(id(ancestor))
        chain.append(ancestor)
        ancestor = ancestor.parent
    if not chain:
        _missing("CALLER_UOW_REQUIRED", "配对材料需要现有实际活动事务。")
    tx = chain[-1]
    nested = s.get_nested_transaction()
    if (
        tx.nested is not False
        or tx.parent is not None
        or s.get_transaction() is not tx
        or any(ancestor.nested is not True for ancestor in chain[:-1])
        or (nested is None and len(chain) != 1)
        or (nested is not None and (len(chain) == 1 or nested is not chain[0]))
    ):
        _missing("CALLER_UOW_REQUIRED", "配对子事务链未归属于当前实际主事务。")
    try:
        bind = s.get_bind()
    except UnboundExecutionError:
        _missing("CALLER_UOW_REQUIRED", "实际调用者Session缺单一存储绑定。")
    return tx, tuple(chain[:-1]), bind


def _guard_uow(s, saved, ctx, identity):
    current = _uow(s)
    if (
        saved[0] is not current[0]
        or saved[2] is not current[2]
        or len(saved[1]) != len(current[1])
        or any(a is not b for a, b in zip(saved[1], current[1], strict=True))
        or digest(vars(ctx)) != identity
    ):
        raise DomainError("CALLER_UOW_CHANGED", "存储读取不能跨事务、连接或调用者身份。")


def _query(s, q, *, lock=False):
    return s.scalar((q.with_for_update() if lock else q).execution_options(populate_existing=True))


def _acl(s, ctx, pid, *, write):
    # Existing Product -> Principal -> Grant gate first. Re-read mutable rows
    # with populate_existing so an already-present identity map is not proof.
    require_access(s, ctx, pid, write=write, lock=write)
    product = _query(
        s, select(Product).where(Product.id == pid, Product.tenant_id == ctx.tenant_id)
    )
    actor = _query(s, select(Principal).where(Principal.id == ctx.requester_id))
    grant = _query(
        s,
        select(Grant).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(pid),
            Grant.principal_id == ctx.requester_id,
        ),
    )
    if (
        product is None
        or actor is None
        or actor.tenant_id != ctx.tenant_id
        or actor.kind != "human"
        or actor.active is not True
        or grant is None
        or (
            grant.expires_at is not None
            and (grant.expires_at is not None and grant.expires_at <= now())
        )
        or (write and grant.can_write is not True)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前本人读取范围或身份已失效。", 403)


def _many(s, model, *where):
    # Two is enough to reject non-unique proof; no table-wide enumeration.
    return list(s.scalars(select(model).where(*where).limit(2)))


def _one(rows, code, detail):
    if len(rows) != 1:
        _missing(code, detail)
    return rows[0]


def _output_fact(s, ctx, product_id, formal):
    """Match the selected Formal and each fact's exact current Run before limiting."""
    filters = dict(
        tenant_id=ctx.tenant_id,
        product_id=product_id,
        project_id=formal.project_id,
        build_id=formal.build_id,
        request_id=formal.request_id,
        next_request_version_id=formal.id,
        next_request_revision=formal.revision,
    )
    matches = []
    current = VerificationRunCurrent
    for model in (VerificationLaunchFact, TestResultActionFact):
        version_id, revision = (
            (model.run_version_id, model.run_revision)
            if model is VerificationLaunchFact
            else (model.next_run_version_id, model.next_run_revision)
        )
        query = (
            select(model)
            .join(
                current,
                and_(
                    current.tenant_id == model.tenant_id,
                    current.product_id == model.product_id,
                    current.request_id == model.request_id,
                    current.run_id == model.run_id,
                    current.run_version_id == version_id,
                    current.run_revision == revision,
                ),
            )
            .where(*(getattr(model, k) == v for k, v in filters.items()))
            .limit(2)
            .execution_options(populate_existing=True)
        )
        matches.extend(s.scalars(query))
    if not matches:
        _missing("PAIR_FACT_MISMATCH", "正式输出没有与当前Run精确匹配的配对事实。")
    return _one(
        matches,
        "PAIR_CURRENT_MISSING_OR_AMBIGUOUS",
        "正式输出须有唯一精确配对事实以确定Run，不能按时间或列表顺序猜选。",
    )


def _previous(identity, revision):
    if identity is None and revision is None:
        return None
    if identity is None or revision is None:
        _missing("PAIR_PREDECESSOR_MISSING", "固定前版身份与版本不完整。")
    return p.FixedRef(id=identity, revision=revision)


def _formal(row):
    snapshot = front._snapshot(row)
    try:
        actor = UUID(row.authority_snapshot["subject_id"])
    except (KeyError, TypeError, ValueError, AttributeError):
        _missing("PAIR_ORIGINAL_AUTHORITY_MISSING", "正式版缺实际当次人的固定专业归属。")
    return p.FormalRow(
        ref={"id": row.id, "revision": row.revision},
        previous=_previous(row.previous_request_id, row.previous_revision),
        owner_id=row.owner_id,
        authority_actor_id=actor,
        visibility=row.visibility,
        operation=row.operation,
        snapshot=snapshot,
        snapshot_sha256=row.snapshot_sha256,
        domain_intent=row.intent_digest,
        reads=row.required_source_read_set,
        created_at=row.created_at,
    )


def _run(row):
    snapshot, plan = launch._snapshot(row)
    return p.RunRow(
        ref={"id": row.id, "revision": row.revision},
        previous=_previous(row.previous_run_version_id, row.previous_revision),
        origin_request={"id": row.request_version_id, "revision": row.request_revision},
        owner_id=row.owner_id,
        writer_id=row.writer_id,
        visibility=row.visibility,
        operation=row.operation,
        snapshot=snapshot,
        snapshot_sha256=row.snapshot_sha256,
        plan=plan,
        plan_sha256=row.plan_sha256,
        domain_intent=row.intent_digest,
        reads=row.required_source_read_set,
        created_at=row.created_at,
    )


def _exact_formal(s, ctx, pid, identity, revision):
    row = front._row(s, ctx, pid, identity)
    if row.revision != revision:
        raise DomainError("PAIR_FACT_MISMATCH", "正式版本与事实引用不一致。")
    return row


def _exact_run(s, ctx, pid, identity, revision):
    row = launch._row(s, ctx, pid, VerificationRunVersion, identity)
    if row.revision != revision:
        raise DomainError("PAIR_FACT_MISMATCH", "Run版本与事实引用不一致。")
    return row


def _fact(row, scope, projection_ref=None):
    base = dict(
        ref={"id": row.id, "revision": row.revision},
        scope=scope,
        build_id=row.build_id,
        request_id=row.request_id,
        run_id=row.run_id,
        request_before={"id": row.request_version_id, "revision": row.request_revision},
        next_request={"id": row.next_request_version_id, "revision": row.next_request_revision},
        actor_id=row.owner_id if isinstance(row, VerificationLaunchFact) else row.actor_id,
        visibility=row.visibility,
        operation=row.operation,
        input_snapshot=row.input_snapshot,
        domain_intent=row.intent_digest,
        reads=row.required_source_read_set,
        created_at=row.created_at,
    )
    if isinstance(row, VerificationLaunchFact):
        return p.LaunchFact(
            **base,
            run={"id": row.run_version_id, "revision": row.run_revision},
            kernel_event=row.kernel_event,
            snapshot_sha256=row.snapshot_sha256,
        )
    return p.ResultAction(
        **base,
        run_before={"id": row.run_version_id, "revision": row.run_revision},
        next_run={"id": row.next_run_version_id, "revision": row.next_run_revision},
        projection=projection_ref,
        event=row.event,
    )


def _common(fact, pid, actor, category_id):
    if actor != fact.actor_id:
        raise DomainError("PAIR_WRITER_MISMATCH", "共同原办理人不等于真实领域当次人。")
    raw = fact.input_snapshot
    if {"confirmation_token", "approval_token"} & raw.keys():
        _missing("PAIR_ORIGINAL_SEMANTIC_MISSING", "原语义不得包含明文批准秘密。")
    try:
        payload = p.PAYLOAD_TYPES[fact.operation].model_validate(raw)
    except ValidationError:
        _missing("PAIR_ORIGINAL_SEMANTIC_MISSING", "不能由固定快照回填缺失原操作载荷。")
    module = launch if isinstance(fact, p.LaunchFact) else results
    semantic = module.semantic(payload)
    if semantic != raw:
        _missing("PAIR_ORIGINAL_SEMANTIC_MISSING", "实际handler语义与保存的闭合原输入不一致。")
    # All six actual closed payloads are neither Claim nor Work. Their default
    # visibility is the common private branch, independent of the saved audience.
    return p.CommonIntentMaterial(
        handler="verification_launch" if module is launch else "verification_results",
        operation=fact.operation,
        category=category_id,
        product=pid,
        payload=semantic,
        named_actor=actor,
        source_revision=None,
        private_owner=actor if getattr(payload, "visibility", "private") == "private" else None,
    )


def _read_storage_pair(s, ctx, product_id, output_ref, *, at, write=False) -> p.ServerPairRead:
    """Read exact real storage relationships. This never returns a HostGateProof."""
    saved = _uow(s)
    if (
        not isinstance(ctx, Context)
        or ctx.run_id is not None
        or ctx.actor_id != ctx.requester_id
        or not isinstance(product_id, UUID)
        or type(write) is not bool
    ):
        raise DomainError("FORBIDDEN_SCOPE", "配对读取须由当前具名本人办理真实产品。", 403)
    identity = digest(vars(ctx))
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None or at > now():
        raise DomainError("INVALID_TIME", "配对读取时点须为实际已到达的服务器aware时钟。", 422)
    at = at.astimezone(UTC)
    selected = p.FormalRef.model_validate(
        output_ref.model_dump() if isinstance(output_ref, p.FormalRef) else output_ref
    )
    _acl(s, ctx, product_id, write=write)
    current_formal = _exact_formal(s, ctx, product_id, selected.id, selected.revision)
    request = front._snapshot(current_formal)
    build = builds._build(s, ctx, product_id, request.build.id)
    engineering = launch._row(
        s, ctx, product_id, EngineeringConfiguration, build.engineering_configuration_id
    )
    manufacturing = launch._row(
        s, ctx, product_id, ProcessRevision, build.manufacturing_configuration_id
    )
    if (
        request.scope.tenant_id != ctx.tenant_id
        or request.scope.product_id != product_id
        or current_formal.purpose != request.purpose
        or (build.id, build.revision, build.project_id, build.product_id)
        != (
            request.build.id,
            request.build.revision,
            request.build.project_id,
            request.build.product_id,
        )
        or request.build.project_id != request.scope.project_id
        or (engineering.id, engineering.revision)
        != (
            request.build.engineering_configuration.id,
            request.build.engineering_configuration.revision,
        )
        or (manufacturing.id, manufacturing.revision)
        != (
            request.build.manufacturing_configuration.id,
            request.build.manufacturing_configuration.revision,
        )
        or engineering.product_id != build.product_id
        or manufacturing.engineering_configuration_id != engineering.id
        or manufacturing.engineering_revision != engineering.revision
    ):
        raise DomainError("PAIR_SCOPE_MISMATCH", "正式请求与真实Build/固定双配置不一致。", 403)
    pointer = _query(
        s,
        select(FormalVerificationCurrent).where(
            FormalVerificationCurrent.tenant_id == ctx.tenant_id,
            FormalVerificationCurrent.product_id == product_id,
            FormalVerificationCurrent.request_id == current_formal.request_id,
        ),
        lock=write,
    )
    if pointer is None:
        _missing("PAIR_CURRENT_MISSING", "正式请求当前指针不存在。")
    if (pointer.request_version_id, pointer.request_revision) != (selected.id, selected.revision):
        raise DomainError("PAIR_CURRENT_MISMATCH", "旧输出或origin不能代替真实Formal Current。")
    formal_current_ref = (pointer.request_version_id, pointer.request_revision)
    fact_row = _output_fact(s, ctx, product_id, current_formal)
    run_pointer = _query(
        s,
        select(VerificationRunCurrent).where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == product_id,
            VerificationRunCurrent.request_id == current_formal.request_id,
            VerificationRunCurrent.run_id == fact_row.run_id,
        ),
        lock=write,
    )
    if run_pointer is None:
        _missing("PAIR_CURRENT_MISSING", "该正式请求尚无真实Run Current。")
    current_run = _exact_run(
        s, ctx, product_id, run_pointer.run_version_id, run_pointer.run_revision
    )
    if (current_run.run_id, current_run.request_id) != (
        run_pointer.run_id,
        current_formal.request_id,
    ):
        raise DomainError("PAIR_CURRENT_MISMATCH", "Run Current的逻辑身份无法核对。")
    run_current_ref = (run_pointer.run_id, run_pointer.run_version_id, run_pointer.run_revision)
    run_identity = launch._row(s, ctx, product_id, VerificationRunIdentity, current_run.run_id)
    if (
        run_identity.project_id != request.scope.project_id
        or run_identity.build_id != request.build.id
        or run_identity.request_id != current_formal.request_id
        or run_identity.owner_id != current_run.owner_id
        or run_identity.visibility != current_run.visibility
    ):
        raise DomainError("PAIR_SCOPE_MISMATCH", "真实Run身份不能跨Build、请求或受众。", 403)
    scope = request.scope
    fact_run = (
        (fact_row.run_version_id, fact_row.run_revision)
        if isinstance(fact_row, VerificationLaunchFact)
        else (fact_row.next_run_version_id, fact_row.next_run_revision)
    )
    if fact_run != (current_run.id, current_run.revision):
        _missing("PAIR_CURRENT_MISMATCH", "本次正式输出事实所指Run已不是该Run当前版。")
    projection_row = None
    if isinstance(fact_row, TestResultActionFact):
        projection_row = launch._row(
            s, ctx, product_id, TestResultProjection, fact_row.projection_id
        )
    fact = _fact(
        fact_row,
        scope,
        {"id": projection_row.id, "revision": projection_row.revision} if projection_row else None,
    )
    before_formal = _exact_formal(
        s, ctx, product_id, fact.request_before.id, fact.request_before.revision
    )
    origin = _exact_formal(
        s, ctx, product_id, current_run.request_version_id, current_run.request_revision
    )
    before_run = None
    if isinstance(fact, p.ResultAction):
        before_run = _exact_run(s, ctx, product_id, fact.run_before.id, fact.run_before.revision)
    elif fact.operation == "verification.schedule.promise":
        before_run = current_run
    elif fact.operation != "test.run.plan":
        if current_run.previous_run_version_id is None or current_run.previous_revision is None:
            _missing("PAIR_PREDECESSOR_MISSING", "Run缺真实不可变前版。")
        before_run = _exact_run(
            s, ctx, product_id, current_run.previous_run_version_id, current_run.previous_revision
        )
    subject = current_formal if fact.operation == "verification.schedule.promise" else current_run
    receipt = _one(
        _many(
            s,
            Receipt,
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.product_id == product_id,
            Receipt.operation == fact.operation,
            Receipt.subject_type
            == (
                "verification_request"
                if fact.operation == "verification.schedule.promise"
                else "test_run"
            ),
            Receipt.subject_id == subject.id,
            Receipt.subject_revision == subject.revision,
        ),
        "PAIR_RECEIPT_MISSING",
        "配对动作缺唯一精确共同保存回执。",
    )
    request_bound = bool(
        _many(
            s,
            RequestKey,
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == receipt.actor_id,
            RequestKey.receipt_id == receipt.id,
            RequestKey.digest == receipt.request_digest,
        )
    )
    # The Receipt is readable above; the peer's RequestKey body remains private.
    if not request_bound and receipt.actor_id != ctx.actor_id:
        request_bound = readable_receipt_request_bound(s, ctx, product_id, receipt.id)
    if not request_bound:
        _missing(
            "PAIR_REQUEST_PROVENANCE_MISSING", "原回执缺原writer与原摘要的真实RequestKey关联。"
        )
    common = _common(fact, product_id, receipt.requester_id, ctx.category_id)
    audits = _many(s, Audit, Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
    events = _many(s, Outbox, Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id)
    projection, projected = None, None
    if isinstance(fact, p.ResultAction):
        row = projection_row
        projection = p.ProjectionRow(
            ref={"id": row.id, "revision": row.revision},
            scope=scope,
            build_id=row.build_id,
            request_id=row.request_id,
            run_id=row.run_id,
            run={"id": row.run_version_id, "revision": row.run_revision},
            run_sha256=row.run_sha256,
            basis_sha256=row.basis_sha256,
            rules_version=row.rules_version,
            rules_sha256=row.rules_sha256,
            result=row.result,
            computed_results=row.computed_results,
            reads=row.required_source_read_set,
        )
        if row.project_id != scope.project_id:
            raise DomainError("PAIR_SCOPE_MISMATCH", "结果投影不能跨项目。", 403)
        projected = _run(_exact_run(s, ctx, product_id, row.run_version_id, row.run_revision))
    material = p.PairedMaterial(
        request_before=_formal(before_formal),
        request_after=_formal(current_formal),
        origin_request=_formal(origin),
        run_before=_run(before_run) if before_run else None,
        run_after=_run(current_run),
        request_current={"id": pointer.request_version_id, "revision": pointer.request_revision},
        run_current={"id": run_pointer.run_version_id, "revision": run_pointer.run_revision},
        fact=fact,
        receipt=p.ReceiptRow(
            id=receipt.id,
            tenant_id=receipt.tenant_id,
            product_id=receipt.product_id,
            command_id=receipt.command_id,
            actor_id=receipt.actor_id,
            requester_id=receipt.requester_id,
            operation=receipt.operation,
            subject_type=receipt.subject_type,
            subject={"id": receipt.subject_id, "revision": receipt.subject_revision},
            visibility=receipt.visibility,
            request_digest=receipt.request_digest,
            common_intent=receipt.intent_digest,
            run_id=receipt.run_id,
            result=receipt.result,
            created_at=receipt.created_at,
        ),
        audits=tuple(
            p.AuditRow(
                id=a.id,
                tenant_id=a.tenant_id,
                receipt_id=a.receipt_id,
                actor_id=a.actor_id,
                operation=a.operation,
            )
            for a in audits
        ),
        outbox=tuple(
            p.OutboxRow(
                id=e.id,
                tenant_id=e.tenant_id,
                receipt_id=e.receipt_id,
                type=e.type,
                subject={"id": e.subject_id, "revision": e.subject_revision},
                actor_id=e.actor_id,
                correlation_id=e.correlation_id,
                schema_version=e.schema_version,
            )
            for e in events
        ),
        common_material=common,
        projection=projection,
        projection_run=projected,
    )
    binding = p.PairBinding(
        scope=scope,
        build=request.build,
        request_id=current_formal.request_id,
        run_id=current_run.run_id,
        purpose=current_formal.purpose,
        caller_id=ctx.requester_id,
        output_ref=selected,
    )
    checked = p.verify_paired_material(binding, material, at=at)
    if checked.missing:
        _missing(checked.missing[0].code, checked.missing[0].detail)
    _guard_uow(s, saved, ctx, identity)
    _acl(s, ctx, product_id, write=write)
    # Mutable Current is re-read without choosing a different version. This
    # still is not post-byte/authority attestation; the host must refresh later.
    final_formal = _query(
        s,
        select(FormalVerificationCurrent).where(
            FormalVerificationCurrent.tenant_id == ctx.tenant_id,
            FormalVerificationCurrent.product_id == product_id,
            FormalVerificationCurrent.request_id == current_formal.request_id,
        ),
        lock=write,
    )
    final_run = _query(
        s,
        select(VerificationRunCurrent).where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == product_id,
            VerificationRunCurrent.request_id == current_formal.request_id,
            VerificationRunCurrent.run_id == fact_row.run_id,
        ),
        lock=write,
    )
    if (
        final_formal is None
        or final_run is None
        or (final_formal.request_version_id, final_formal.request_revision) != formal_current_ref
        or (final_run.run_id, final_run.run_version_id, final_run.run_revision) != run_current_ref
    ):
        raise DomainError("PAIR_CURRENT_MISMATCH", "读取期间实际Current发生变化，请重新办理。")
    _guard_uow(s, saved, ctx, identity)
    return p.ServerPairRead(binding=binding, material=material)


def read_storage_pair(s, ctx, product_id, output_ref, *, at, write=False) -> p.ServerPairRead:
    """Read saved structure without autoflush or live proof attestation.

    Caller pending rows are not storage evidence until the caller explicitly
    flushes them. The bridge never flushes, commits or begins a transaction.
    """
    _uow(s)
    try:
        with s.no_autoflush:
            return _read_storage_pair(s, ctx, product_id, output_ref, at=at, write=write)
    except ValidationError as error:
        raise DomainError(
            "PAIR_STORAGE_INVALID", "实际固定存储无法解析为完整封闭配对材料。", 503
        ) from error


class StoragePairReader:
    """Only storage read/refresh; deliberately lacks the mandatory live attest."""

    def read(self, s, ctx, product_id, output_ref, *, at, write=False):
        return read_storage_pair(s, ctx, product_id, output_ref, at=at, write=write)

    def refresh(self, s, ctx, product_id, previous, *, at, write=False):
        if not isinstance(previous, p.ServerPairRead):
            _missing("INTEGRATION_REQUIRED", "重新读取须使用先前真实typed材料。")
        return self.read(s, ctx, product_id, previous.binding.output_ref, at=at, write=write)
