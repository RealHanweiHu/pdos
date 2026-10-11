"""T1 quality commands bind the stored Issue and immediate source watermarks."""

from dataclasses import dataclass
from types import SimpleNamespace

from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_issues.ports import Invocation, Mutation
from pdos_next.domain.quality_issues.rules import issue_sources, semantic_digest
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.quality_result_bridge import direct_issue_failure
from pdos_next.service import digest
from pdos_next.source_current import direct_source_basis

from . import policy
from .evidence import merge_reads, source_basis, union_sources

OPERATIONS = frozenset({"quality.issue.triage", "quality.issue.containment.record"})


def _professional_seal(s, authority):
    engine = s.get_bind()
    registry = getattr(engine, "_pdos_professional_issuers", {})
    epochs = getattr(engine, "_pdos_professional_issuer_epochs", {})
    return tuple(
        (
            ref["issuer_key"],
            id(registry.get(ref["issuer_key"])),
            getattr(registry.get(ref["issuer_key"]), "version", None),
            getattr(registry.get(ref["issuer_key"]), "epoch", None),
            epochs.get(ref["issuer_key"]),
        )
        for ref in authority["fact_refs"]
    )


@dataclass
class Prepared:
    bound: object
    pointers: dict
    mutation: Mutation
    review: dict


def issue_refs(issue):
    return union_sources(
        issue_sources(issue),
        *(tuple((f.criterion, f.method, f.source)) for f in issue.failures),
    )


def load(s, ctx, command, product, payload, *, require_reads=True):
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _uow

    from . import service as owner

    call_owner = _uow(s), digest(vars(ctx)), s.info.get("scope")
    write = not s.info.get("read_snapshot", False)
    owner._human(s, ctx, product.id, write=True, lock=write)
    row = owner._row(s, ctx, product.id, payload.issue_id, payload.expected_issue_revision)
    issue = owner._snapshot(row)
    pointer = owner._current(s, ctx, product.id, issue.id, lock=write)
    if pointer is None or (pointer.issue_version_id, pointer.issue_revision) != (
        row.id,
        row.revision,
    ):
        raise DomainError("VERSION_CONFLICT", "问题当前版本已改变。")
    authority = professional.assess(
        s,
        ctx,
        product.id,
        issue.scope.project_id,
        command.operation,
        row.purpose,
        now(),
        write=write,
    )
    if authority.get("authorized") is not True or authority.get("qualified") is not True:
        raise DomainError("QUALIFICATION_REQUIRED", "当前具名专业职责与资格不足。", 403)
    professional_seal = _professional_seal(s, authority)
    published = policy.assess(s, ctx, product.id, issue.scope.project_id, row.purpose)
    policy_seal = owner._policy_issuer_seal(s, SimpleNamespace(scope=issue.scope, policy=published))
    values = tuple(
        direct_issue_failure(s, ctx, product.id, issue, f, purpose=row.purpose)
        for f in issue.failures
    )
    refs = union_sources(issue_refs(issue), owner._extra_sources(payload), published["sources"])
    direct_reads = merge_reads(
        [{"artifact_id": str(r.id), "expected_revision": r.revision} for r in refs]
    )
    actual, private = direct_source_basis(s, ctx, product, refs, direct_reads)
    # The current caller's professional facts carry their own exact direct evidence;
    # this is not the old author's qualification or the result's upstream read set.
    authority_reads = merge_reads(authority.get("required_source_read_set", []))
    authority_basis, authority_private = source_basis(s, ctx, product.id, authority_reads)
    reads = merge_reads(direct_reads, authority_reads)
    actual = sorted(
        {entry["id"]: entry for entry in (*actual, *authority_basis)}.values(),
        key=lambda e: e["id"],
    )
    if row.visibility != "private" and (private or authority_private or published["private"]):
        raise DomainError("FORBIDDEN_SCOPE", "直接来源包含私有材料，不能扩大问题受众。", 403)
    # Existing immutable judgments keep their original direct source-safety basis.
    saved = {entry["id"]: entry for entry in row.source_basis.get("artifact_sources", [])}
    historical = {str(r.id) for r in issue_refs(issue)}
    if any(entry["id"] in historical and saved.get(entry["id"]) != entry for entry in actual):
        raise DomainError("SOURCE_STALE", "问题的直接来源版本或安全水位已变化。")
    if require_reads and merge_reads(command.source_read_set) != reads:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "命令须包含本次直接品质来源读集。")
    domain = owner._domain(payload)
    bound = owner.Bound(
        issue.scope,
        row.purpose,
        row.visibility,
        row.owner_id,
        {issue.id: row},
        {issue.id: issue},
        values,
        (),
        None,
        {},
        authority,
        published,
        refs,
        reads,
        {
            "contract": "s0.direct-quality.v1",
            "artifact_sources": actual,
            "current_issue": {
                "id": str(row.id),
                "revision": row.revision,
                "epoch": pointer.epoch,
                "sha256": row.snapshot_sha256,
            },
            "result_watermarks": [v.watermark for v in values],
        },
        domain,
        Invocation(
            command_id=command.command_id,
            operation=command.operation,
            subject_id=issue.id,
            expected_revision=payload.expected_issue_revision,
            semantic_digest=semantic_digest(domain),
            confirmation_token=getattr(payload, "confirmation_token", None),
        ),
    )
    bound.runtime_guard = (
        *call_owner,
        professional_seal,
        policy_seal,
    )
    refresh(s, ctx, product.id, command.operation, bound)
    return bound


def prepare_preview(s, ctx, command, product, payload):
    from . import service as owner

    bound = load(s, ctx, command, product, payload)
    pointers = owner._new_write(s, ctx, command, product, payload, bound)
    handler = owner._kernel(s, ctx, product.id, bound, lambda _: None)
    handler._authorize(handler.ports.commands.authority, command.operation)
    preview, mutation = handler._prepare(
        handler.ports.commands.authority, bound.invocation, bound.domain_payload
    )
    if mutation.event_name == "issue.recheck_required":
        raise DomainError("RECHECK_REQUIRED", "原失败须重核，不能继续办理。")
    phase = Prepared(
        bound,
        pointers,
        mutation,
        owner._review(s, ctx, product.id, bound, prepared=(preview, mutation)),
    )
    refresh(s, ctx, product.id, command.operation, bound)
    return phase


def encode_prepared(phase):
    return {
        "contract": "s0.direct-quality.v1",
        "scope": phase.bound.scope.model_dump(mode="json"),
        "operation": phase.bound.invocation.operation,
        "semantic_digest": phase.bound.invocation.semantic_digest,
        "reads": phase.bound.reads,
        "source_basis": phase.bound.source_basis,
        "policy_revision": phase.bound.policy["facts_revision"],
        "authority_revision": phase.bound.authority["facts_revision"],
        "mutation": phase.mutation.model_dump(mode="json"),
    }


def prepare_confirmed(s, ctx, command, product, payload, saved):
    from . import service as owner

    bound = load(s, ctx, command, product, payload)
    if (
        saved.get("contract") != "s0.direct-quality.v1"
        or saved.get("scope") != bound.scope.model_dump(mode="json")
        or saved.get("operation") != command.operation
        or saved.get("semantic_digest") != bound.invocation.semantic_digest
        or saved.get("reads") != bound.reads
        or saved.get("source_basis") != bound.source_basis
        or saved.get("policy_revision") != bound.policy["facts_revision"]
        or saved.get("authority_revision") != bound.authority["facts_revision"]
    ):
        raise DomainError("CONFIRMATION_SCOPE_CHANGED", "问题或直接来源水位已变化，请重新预览。")
    mutation = Mutation.model_validate(saved["mutation"])
    handler = owner._kernel(s, ctx, product.id, bound, lambda _: None)
    handler._authorize(handler.ports.commands.authority, command.operation)
    # The action time belongs to this actual submission; material/result proofs
    # and the mutation's business effect remain the saved preview's values.
    at = now()
    changes = tuple(
        i.model_copy(
            update={
                "history": tuple(
                    h.model_copy(update={"at": at, "command_id": command.command_id})
                    if index >= len(bound.issues[i.id].history)
                    else h
                    for index, h in enumerate(i.history)
                )
            }
        )
        for i in mutation.changes
    )
    mutation = mutation.model_copy(update={"changes": changes})
    pointers = owner._new_write(s, ctx, command, product, payload, bound)
    return Prepared(bound, pointers, mutation, {})


def apply_confirmed(s, ctx, command, product, payload, phase):
    from . import service as owner

    row = owner._record(
        s, ctx, command, product, payload, phase.bound, phase.pointers, phase.mutation
    )
    return row, "quality_issue", row.visibility


def refresh(s, ctx, pid, operation, bound):
    # Locks on Product and Issue Current hold through the caller's transaction.
    # Sources and the current actor were read once after the confirmation lookup.
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow

    from . import service as owner

    try:
        _same_uow(s, bound.runtime_guard[0], ctx, bound.runtime_guard[1])
    except DomainError as exc:
        if exc.reason != "FACT_CALLER_UOW_CHANGED":
            raise
        raise DomainError("SOURCE_STALE", "当前操作者或实际事务边界已变化。") from exc
    if bound.runtime_guard != (
        _uow(s),
        digest(vars(ctx)),
        s.info.get("scope"),
        _professional_seal(s, bound.authority),
        owner._policy_issuer_seal(s, bound),
    ):
        raise DomainError("SOURCE_STALE", "当前操作者、事务范围或签发入口已变化。")
    owner._human(s, ctx, pid, write=True, lock=not s.info.get("read_snapshot", False))
    if not professional.authority_time_current(bound.authority, now()):
        raise DomainError("SOURCE_STALE", "当前操作者资格已失效。")
    if bound.policy is not None and not policy.policy_time_current(bound.policy, now()):
        raise DomainError("SOURCE_STALE", "当前政策已失效。")
