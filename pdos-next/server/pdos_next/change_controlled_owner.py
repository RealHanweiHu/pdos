"""Actual bounded policy/selection registry owners; no graph coverage or completion verdict."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from sqlalchemy import select

from pdos_next import change_controlled_store as models
from pdos_next import change_order_store as outputs
from pdos_next import field_change_selection as field
from pdos_next.change_controlled_schemas import FieldIntentTarget, FieldSelectionMaterial
from pdos_next.change_implementation_owner import _atom_proof, _json, common_group
from pdos_next.change_order_service import _one, current_fixed, snapshot
from pdos_next.clock import deadline_current, earliest_deadline
from pdos_next.clock import now as server_now
from pdos_next.contracts import Command
from pdos_next.database import category_for_product
from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
from pdos_next.domain.capa_verification.service import load_followup_basis
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import service as old
from pdos_next.domain.change_execution.graph import OwnerReader
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_followup.evidence import _constant, _pairs
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product, Receipt, RequestKey
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import append_receipt, receipt_view, source_for
from pdos_next.service import digest as common_digest


def clock():
    return server_now()


def require(ok, code="CONTROLLED_MATERIAL_MISMATCH", status=409):
    if not ok:
        raise DomainError(code, "受控出版、逐项适用、实际CAPA措施或当前来源未满足。", status)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def same(actual, expected):
    return canonical(actual) == canonical(expected)


def original(s, ctx, pid, source, cls):
    require(source.kind == "artifact", "MISSING_REQUIRED_EVIDENCE", 422)
    artifact = source_for(s, ctx, pid, source.id, source.revision)
    require(artifact.original_id is None, "CONTROLLED_ORIGINAL_OWNER_REQUIRED", 503)
    require(artifact.content_hash == common_digest(artifact.content), "SOURCE_STALE")
    old._native_registration(s, ctx, pid, artifact)
    match = old.POSITION.fullmatch(source.position)
    lines = artifact.content.splitlines()
    require(match is not None and 0 < int(match[1]) <= len(lines), "MISSING_REQUIRED_EVIDENCE", 422)
    line = lines[int(match[1]) - 1]
    require(hashlib.sha256(line.encode()).hexdigest() == match[2], "SOURCE_STALE")
    try:
        value = cls.model_validate(
            json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        )
    except (ValueError, TypeError) as error:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "出版依据须完整结构化原行，拒绝重复键及额外字段。", 422
        ) from error
    return value, artifact


def _project(s, ctx, scope):
    row = _one(
        s,
        Project,
        Project.tenant_id == ctx.tenant_id,
        Project.product_id == scope.product_id,
        Project.id == scope.project_id,
    )
    require(
        row.status == "active"
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    return row, (
        row.id,
        row.tenant_id,
        row.product_id,
        row.owner_id,
        row.visibility,
        deepcopy(row.scope),
        row.status,
    )


def _caller(s, ctx, pid, *, write):
    old._human(s, ctx, pid, write=write)
    actor = _one(
        s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.requester_id
    )
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.category_id == category_for_product(pid),
        Grant.principal_id == ctx.requester_id,
    )
    require(
        ctx.actor_id == ctx.requester_id
        and ctx.run_id is None
        and actor.kind == "human"
        and actor.active,
        "NAMED_PERSON_REQUIRED",
        403,
    )
    require(not write or grant.can_write, "FORBIDDEN_SCOPE", 403)
    return (
        actor.id,
        actor.active,
        actor.kind,
        grant.id,
        grant.access_epoch,
        grant.can_write,
        grant.expires_at,
    ), grant.expires_at


def authority(s, ctx, pid, scope, operation, purpose, *, write=True):
    result = old._authority(s, ctx, pid, scope, operation, purpose, write=write)
    require(bool(result.get("fact_refs")), "INTEGRATION_REQUIRED", 503)
    require(professional.authority_time_current(result, clock()), "SOURCE_STALE")
    return result, None


def original_authority(s, ctx, pid, row):
    require(row.authority_snapshot.get("subject_id") == str(row.actor_id), "INTEGRITY_MISMATCH")
    # recheck_snapshot reads the original subject from its fixed snapshot. The
    # current reader keeps their own transaction/ACL; never impersonate a signer.
    check = professional.recheck_snapshot(
        s, ctx, pid, row.project_id, row.authority_snapshot, clock(), write=False, retained=True
    )
    require(check.get("current") is True, "RECHECK_REQUIRED")
    return None


def _reads(*groups):
    return _merge_reads(
        *[
            [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in values]
            for values in groups
        ]
    )


def _source_guard(s, ctx, pid, visibility, owner_id, reads, sources, *, io=True):
    basis, private, _ = old._evidence(s, ctx, pid, reads, sources, io=io)
    require(
        not (private and (visibility != "private" or owner_id != ctx.requester_id)),
        "AUDIENCE_USE_FORBIDDEN",
        403,
    )
    return basis


def policy_pointer(s, ctx, pid, scope, purpose, *, lock=False):
    q = (
        select(models.ChangePolicyCurrent)
        .where(
            models.ChangePolicyCurrent.tenant_id == ctx.tenant_id,
            models.ChangePolicyCurrent.product_id == pid,
            models.ChangePolicyCurrent.project_id == scope.project_id,
            models.ChangePolicyCurrent.purpose_sha256 == digest(purpose),
        )
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    rows = list(s.scalars(q.with_for_update() if lock else q))
    require(len(rows) <= 1, "INTEGRITY_MISMATCH")
    if not rows:
        return None, None
    p = rows[0]
    row = _one(
        s,
        models.ChangePolicyFact,
        models.ChangePolicyFact.tenant_id == ctx.tenant_id,
        models.ChangePolicyFact.product_id == pid,
        models.ChangePolicyFact.project_id == scope.project_id,
        models.ChangePolicyFact.id == p.fact_id,
        models.ChangePolicyFact.revision == p.revision,
    )
    require(
        (row.owner_id, row.visibility, row.epoch, row.purpose_sha256)
        == (p.owner_id, p.visibility, p.epoch, p.purpose_sha256)
        and row.purpose == purpose,
        "INTEGRITY_MISMATCH",
    )
    return p, row


def selection_pointer(s, ctx, pid, scope, change_id, item_id, *, lock=False):
    q = (
        select(models.ChangeSelectionCurrent)
        .where(
            models.ChangeSelectionCurrent.tenant_id == ctx.tenant_id,
            models.ChangeSelectionCurrent.product_id == pid,
            models.ChangeSelectionCurrent.project_id == scope.project_id,
            models.ChangeSelectionCurrent.change_id == change_id,
            models.ChangeSelectionCurrent.item_id == item_id,
        )
        .limit(2)
        .execution_options(populate_existing=True, autoflush=False)
    )
    rows = list(s.scalars(q.with_for_update() if lock else q))
    require(len(rows) <= 1, "INTEGRITY_MISMATCH")
    if not rows:
        return None, None
    p = rows[0]
    row = _one(
        s,
        models.ChangeSelectionFact,
        models.ChangeSelectionFact.tenant_id == ctx.tenant_id,
        models.ChangeSelectionFact.product_id == pid,
        models.ChangeSelectionFact.project_id == scope.project_id,
        models.ChangeSelectionFact.id == p.fact_id,
        models.ChangeSelectionFact.revision == p.revision,
    )
    require(
        (row.owner_id, row.visibility, row.epoch, row.change_id, row.item_id, row.purpose_sha256)
        == (p.owner_id, p.visibility, p.epoch, p.change_id, p.item_id, p.purpose_sha256),
        "INTEGRITY_MISMATCH",
    )
    return p, row


def previous(pointer, row, wanted_id, wanted_revision):
    if pointer is None:
        require(wanted_id is None and wanted_revision is None, "VERSION_CONFLICT")
        return 1, 1
    require((row.id, row.revision) == (wanted_id, wanted_revision), "VERSION_CONFLICT")
    return row.revision + 1, row.epoch + 1


def exact_units(item):
    by_identity = {r.identity: r for r in item.selection.objects}
    result = []
    for unit in item.selection.units:
        # No number/label/UUID heuristic. Batch/serial requires its actual owner.
        require(unit.startswith("object:"), "CHANGE_UNIT_OWNER_REQUIRED", 503)
        identity = unit[len("object:") :]
        require(identity in by_identity, "SELECTION_SCOPE_MISMATCH")
        result.append(models.UnitBinding(unit=unit, object_identity=identity))
    require({v.object_identity for v in result} == set(by_identity), "SELECTION_SCOPE_MISMATCH")
    return tuple(result)


def action_basis(s, ctx, pid, target, scope, purpose):
    value = load_followup_basis(
        s, ctx, pid, target.issue_id, target.expected_issue_revision, write=False
    )
    require(
        value.scope == scope and value.capa_id == target.capa_id and value.purpose == purpose,
        "ACTION_INTENT_SCOPE_MISMATCH",
        403,
    )
    action = next((a for a in value.actions if a.action_id == target.action_id), None)
    require(action is not None, "ACTION_INTENT_REQUIRED", 422)
    return value, action


def objects(s, ctx, pid, request, item):
    reader = OwnerReader(s, ctx, pid, request.scope, request.audience, old._issue_loader(s))
    fixed, reads, sources = {}, [], list(item.selection.sources)
    for ref in (*item.selection.objects, *item.intent.basis):
        v = reader.resolve(ref)
        require(v.current, "RECHECK_REQUIRED")
        fixed[ref.identity] = {
            "ref": ref.model_dump(mode="json"),
            "view": deepcopy(v.view),
            "source_basis": deepcopy(v.source_basis),
            "owner_id": str(v.owner_id),
            "visibility": v.visibility,
        }
        reads += list(v.reads)
        sources.append(v.source)
    return fixed, reads, tuple(dict.fromkeys(sources))


def policy_callback(s, ctx, pid, *, scope, purpose, request, previous=None):
    uow, runtime = _uow(s), old._runtime_stamp(s)
    caller, until = _caller(s, ctx, pid, write=False)
    _, project = _project(s, ctx, scope)
    pointer, row = policy_pointer(s, ctx, pid, scope, purpose)
    require(row is not None, "CHANGE_POLICY_OWNER_REQUIRED", 503)
    require(row.visibility != "private" or row.owner_id == ctx.requester_id, "FORBIDDEN_SCOPE", 403)
    source = SourceRef.model_validate(row.source)
    material, _ = original(s, ctx, pid, source, models.PolicyMaterial)
    require(
        material.scope == scope
        and material.purpose == purpose
        and (material.owner_id, material.visibility, material.publisher_id, material.nature)
        == (row.owner_id, row.visibility, row.actor_id, row.nature)
        and material.model_dump(mode="json") == row.material
        and digest(material) == row.material_sha256
        and material.valid_until == row.valid_until
        and material.valid_from == row.valid_from,
        "INTEGRITY_MISMATCH",
    )
    group = common_group(
        s,
        ctx,
        pid,
        row,
        operation=models.POLICY_OPERATION,
        event=models.POLICY_EVENT,
        actor=row.actor_id,
    )
    require(
        group["receipt"]["subject_type"] == models.POLICY_FAMILY
        and group["receipt"]["intent_digest"] == row.intent_digest
        and group["receipt"]["command_id"] == row.command_id,
        "INTEGRITY_MISMATCH",
    )
    original_until = original_authority(s, ctx, pid, row)
    basis = _source_guard(
        s,
        ctx,
        pid,
        row.visibility,
        row.owner_id,
        row.required_source_read_set,
        tuple(SourceRef.model_validate(x) for x in row.sources),
    )
    require(same(basis, row.source_basis), "SOURCE_STALE")
    # All original IO has finished before current/actor/source metadata/UOW/clock.
    final_original_until = original_authority(s, ctx, pid, row)
    require(
        same(
            _source_guard(
                s,
                ctx,
                pid,
                row.visibility,
                row.owner_id,
                row.required_source_read_set,
                tuple(SourceRef.model_validate(x) for x in row.sources),
                io=False,
            ),
            basis,
        ),
        "SOURCE_STALE",
    )
    final_pointer, final_row = policy_pointer(s, ctx, pid, scope, purpose)
    require(
        (final_pointer.id, final_row.id, final_row.revision, final_row.epoch)
        == (pointer.id, row.id, row.revision, row.epoch),
        "SOURCE_STALE",
    )
    require(
        _project(s, ctx, scope)[1] == project
        and _caller(s, ctx, pid, write=False)[0] == caller
        and old._runtime_stamp(s) == runtime,
        "SOURCE_STALE",
    )
    _same_uow(s, uow, ctx, common_digest(vars(ctx)))
    require(
        material.valid_from
        <= clock()
        < earliest_deadline(material.valid_until, until, original_until, final_original_until),
        "RECHECK_REQUIRED",
    )
    result = outputs.ControlledPolicy(
        scope=scope.model_dump(mode="json"),
        purpose=purpose,
        owner_id=row.owner_id,
        visibility=row.visibility,
        nature=row.nature,
        source=source,
        required_disciplines=material.required_disciplines,
        valid_from=material.valid_from,
        # Propagate original publisher deadlines to later owner IO, while the
        # current consumer's Grant remains an independent caller gate.
        valid_until=earliest_deadline(material.valid_until, original_until, final_original_until),
        epoch=row.epoch,
        required_source_read_set=row.required_source_read_set,
        source_basis=basis,
        owner_proof=group,
    )
    require(previous is None or result == previous, "SOURCE_STALE")
    return result


def selection_callback(s, ctx, pid, *, scope, purpose, item, request, previous=None):
    uow, runtime = _uow(s), old._runtime_stamp(s)
    caller, until = _caller(s, ctx, pid, write=False)
    _, project = _project(s, ctx, scope)
    pointer, row = selection_pointer(s, ctx, pid, scope, request.id, item.id)
    require(row is not None, "CHANGE_SELECTION_OWNER_REQUIRED", 503)
    require(row.visibility != "private" or row.owner_id == ctx.requester_id, "FORBIDDEN_SCOPE", 403)
    material, _ = original(
        s, ctx, pid, SourceRef.model_validate(row.source), field.SelectionMaterialReader
    )
    require(
        material.model_dump(mode="json") == row.material
        and digest(material) == row.material_sha256
        and material.scope == scope
        and material.purpose == purpose
        and material.item == item
        and digest(item) == row.item_sha256
        and material.change_id == request.id
        and material.decider_id == row.actor_id
        and material.status == row.status
        and material.nature == row.nature
        and material.valid_until == row.valid_until,
        "INTEGRITY_MISMATCH",
    )
    require(row.status == "applicable", "SELECTION_NOT_APPLICABLE")
    current_policy = policy_callback(s, ctx, pid, scope=scope, purpose=purpose, request=request)
    require(same(current_policy.model_dump(mode="json"), row.policy_snapshot), "RECHECK_REQUIRED")
    is_field = isinstance(material, FieldSelectionMaterial)
    require(
        getattr(row, "basis_kind", "capa_action")
        == ("field_intent" if is_field else "capa_action"),
        "INTEGRITY_MISMATCH",
    )
    target = (
        FieldIntentTarget(
            kind="field_intent", feedback=material.feedback, executor_id=material.executor_id
        )
        if is_field
        else models.ActionTarget(
            issue_id=row.issue_id,
            expected_issue_revision=_current_issue_revision(s, ctx, pid, scope, row.issue_id),
            capa_id=row.capa_id,
            action_id=row.action_id,
        )
    )

    def action_read():
        if is_field:
            return field.load_basis(
                s, ctx, pid, target, item, request, scope, purpose, current_policy.nature
            )
        return action_basis(s, ctx, pid, target, scope, purpose)

    basis, action = action_read()
    if is_field:
        require(
            (
                row.feedback_id,
                row.feedback_version_id,
                row.feedback_revision,
                row.feedback_sha256,
                row.executor_id,
                row.intent_id,
            )
            == (
                material.feedback.id,
                material.feedback_version_id,
                material.feedback.revision,
                material.feedback_sha256,
                material.executor_id,
                action.intent_id,
            ),
            "INTEGRITY_MISMATCH",
        )
        require(
            (basis.feedback_version_id, basis.feedback_sha256, action.executor_id)
            == (material.feedback_version_id, material.feedback_sha256, material.executor_id),
            "ACTION_INTENT_CHANGED",
        )
    else:
        require(
            (action.action_sha256, action.executor_id)
            == (material.action_sha256, material.executor_id),
            "ACTION_INTENT_CHANGED",
        )
        require(
            row.visibility == basis.visibility and row.owner_id == basis.owner_id,
            "AUDIENCE_USE_FORBIDDEN",
            403,
        )
    require(
        [v.model_dump(mode="json") for v in exact_units(item)] == row.units_snapshot,
        "SELECTION_SCOPE_MISMATCH",
    )
    fixed, object_reads, object_sources = objects(s, ctx, pid, request, item)
    require(same(fixed, row.object_basis), "RECHECK_REQUIRED")
    group = common_group(
        s,
        ctx,
        pid,
        row,
        operation=models.SELECTION_OPERATION,
        event=models.SELECTION_EVENT,
        actor=row.actor_id,
    )
    require(group["receipt"]["subject_type"] == models.SELECTION_FAMILY, "INTEGRITY_MISMATCH")
    proof_atom = type(
        "ProofAtom", (), {**row.__dict__, "material_sha256": row.confirmation_material_sha256}
    )()
    _atom_proof(s, ctx, pid, proof_atom, group)
    original_until = original_authority(s, ctx, pid, row)
    sources = tuple(SourceRef.model_validate(x) for x in row.sources)
    actual_basis = _source_guard(
        s, ctx, pid, row.visibility, row.owner_id, row.required_source_read_set, sources
    )
    require(same(actual_basis, row.source_basis), "SOURCE_STALE")
    # The stored material is unchanged; current action/owner closure is additional
    # live evidence, never silently omitted to keep an old list below 20.
    complete_sources = tuple(dict.fromkeys((*sources, *basis.sources, *object_sources)))
    complete_reads = _reads(
        row.required_source_read_set,
        basis.required_source_read_set,
        object_reads,
        current_policy.required_source_read_set,
        old._source_reads(complete_sources),
    )
    complete_basis = _source_guard(
        s, ctx, pid, row.visibility, row.owner_id, complete_reads, complete_sources
    )
    # Recheck every original after the last byte owner, then pointer/ACL/runtime/clock.
    policy_callback(
        s, ctx, pid, scope=scope, purpose=purpose, request=request, previous=current_policy
    )
    final_original_until = original_authority(s, ctx, pid, row)
    last_basis, last_action = action_read()
    require(
        last_basis == basis
        and last_action == action
        and same(objects(s, ctx, pid, request, item)[0], fixed),
        "SOURCE_STALE",
    )
    require(
        same(
            _source_guard(
                s,
                ctx,
                pid,
                row.visibility,
                row.owner_id,
                complete_reads,
                complete_sources,
                io=False,
            ),
            complete_basis,
        ),
        "SOURCE_STALE",
    )
    final, last = selection_pointer(s, ctx, pid, scope, request.id, item.id)
    require(
        (final.id, last.id, last.revision, last.epoch)
        == (pointer.id, row.id, row.revision, row.epoch),
        "SOURCE_STALE",
    )
    require(
        _project(s, ctx, scope)[1] == project
        and _caller(s, ctx, pid, write=False)[0] == caller
        and old._runtime_stamp(s) == runtime,
        "SOURCE_STALE",
    )
    _same_uow(s, uow, ctx, common_digest(vars(ctx)))
    require(
        clock() < earliest_deadline(row.valid_until, until, original_until, final_original_until),
        "RECHECK_REQUIRED",
    )
    result = outputs.SelectionProof(
        scope=scope.model_dump(mode="json"),
        item_sha256=row.item_sha256,
        nature=row.nature,
        applicable=True,
        valid_until=earliest_deadline(
            row.valid_until, original_until, final_original_until, current_policy.valid_until
        ),
        sources=complete_sources,
        required_source_read_set=complete_reads,
        source_basis=complete_basis,
        owner_proof=group,
    )
    require(previous is None or result == previous, "SOURCE_STALE")
    return result


def _current_issue_revision(s, ctx, pid, scope, issue_id):
    from pdos_next.domain.quality_execution.models import QualityIssueCurrent

    p = _one(
        s,
        QualityIssueCurrent,
        QualityIssueCurrent.tenant_id == ctx.tenant_id,
        QualityIssueCurrent.product_id == pid,
        QualityIssueCurrent.project_id == scope.project_id,
        QualityIssueCurrent.issue_id == issue_id,
    )
    return p.issue_revision


def import_policy(s, ctx, pid, payload, *, command_id, request_key):
    """Host-only publication through current professional publisher + common tail.

    No issuer/qualification is created here. Unconfigured publisher operation is
    503. Shared append_receipt needs Root's explicit host-only event registration.
    """
    data = models.PolicyImport.model_validate(payload)
    from pdos_next import service as common

    require(
        common.EVENTS.get(models.POLICY_OPERATION) == models.POLICY_EVENT,
        "CONTROLLED_PUBLICATION_TAIL_REQUIRED",
        503,
    )
    uow = _uow(s)
    product = _one(s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid, lock=True)
    scope = Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=data.project_id)
    caller, until = _caller(s, ctx, pid, write=True)
    project, project_stamp = _project(s, ctx, scope)
    runtime = old._runtime_stamp(s)
    value, _ = original(s, ctx, pid, data.source, models.PolicyMaterial)
    require(
        value.scope == scope
        and value.purpose == data.purpose
        and value.publisher_id == ctx.requester_id
        and value.owner_id == project.owner_id,
        "CONTROLLED_POLICY_SCOPE_MISMATCH",
        403,
    )
    auth, auth_until = authority(s, ctx, pid, scope, models.POLICY_OPERATION, data.purpose)
    require(
        "quality" in auth["roles"]
        and (value.nature == "synthetic" if auth.get("synthetic") else value.nature == "real"),
        "PUBLISHER_AUTHORITY_REQUIRED",
        403,
    )
    reads = _reads(old._source_reads((data.source,)), auth["required_source_read_set"])
    basis = _source_guard(s, ctx, pid, value.visibility, value.owner_id, reads, (data.source,))
    cmd = Command(
        command_id=command_id,
        idempotency_key=request_key,
        operation=models.POLICY_OPERATION,
        category_id=ctx.category_id,
        product_id=pid,
        expected_revision=product.revision,
        source_read_set=reads,
        payload=data.model_dump(mode="json"),
    )
    fingerprint = common_digest(
        {
            "operation": cmd.operation,
            "tenant": str(ctx.tenant_id),
            "product": str(pid),
            "actor": str(ctx.requester_id),
            "payload": data.model_dump(mode="json"),
        }
    )
    keys = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == ctx.requester_id,
                RequestKey.key == request_key,
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(
        len(keys) <= 1 and (not keys or keys[0].digest == fingerprint), "DUPLICATE_INTENT_CONFLICT"
    )
    receipts = list(
        s.scalars(
            select(Receipt)
            .where(
                Receipt.tenant_id == ctx.tenant_id,
                Receipt.product_id == pid,
                Receipt.operation == models.POLICY_OPERATION,
                Receipt.actor_id == ctx.actor_id,
                Receipt.intent_digest == fingerprint,
            )
            .limit(2)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    require(len(receipts) <= 1, "INTEGRITY_MISMATCH")
    if receipts:
        saved = _one(
            s,
            models.ChangePolicyFact,
            models.ChangePolicyFact.tenant_id == ctx.tenant_id,
            models.ChangePolicyFact.product_id == pid,
            models.ChangePolicyFact.id == receipts[0].subject_id,
        )
        require(
            saved.input_snapshot["payload"] == data.model_dump(mode="json")
            and saved.material == value.model_dump(mode="json")
            and same(saved.source_basis, basis),
            "SOURCE_STALE",
        )
        original_authority(s, ctx, pid, saved)
        group = common_group(
            s,
            ctx,
            pid,
            saved,
            operation=models.POLICY_OPERATION,
            event=models.POLICY_EVENT,
            actor=saved.actor_id,
        )
        require(
            group["receipt"]["subject_type"] == models.POLICY_FAMILY
            and (not keys or keys[0].receipt_id == receipts[0].id),
            "INTEGRITY_MISMATCH",
        )
        if not keys:
            s.add(
                RequestKey(
                    tenant_id=ctx.tenant_id,
                    actor_id=ctx.actor_id,
                    key=request_key,
                    digest=fingerprint,
                    receipt_id=receipts[0].id,
                )
            )
        # All source/authority/ACL/runtime/UOW checks also precede old Receipt replay.
        require(
            original(s, ctx, pid, data.source, models.PolicyMaterial)[0] == value
            and same(
                _source_guard(
                    s, ctx, pid, value.visibility, value.owner_id, reads, (data.source,), io=False
                ),
                basis,
            )
            and authority(s, ctx, pid, scope, models.POLICY_OPERATION, data.purpose)[0] == auth,
            "SOURCE_STALE",
        )
        require(
            _caller(s, ctx, pid, write=True)[0] == caller
            and _project(s, ctx, scope)[1] == project_stamp
            and old._runtime_stamp(s) == runtime,
            "SOURCE_STALE",
        )
        _same_uow(s, uow, ctx, common_digest(vars(ctx)))
        require(clock() < earliest_deadline(until, auth_until, value.valid_until), "SOURCE_STALE")
        return receipt_view(receipts[0])
    require(not keys, "INTEGRITY_MISMATCH")
    pointer, prior = policy_pointer(s, ctx, pid, scope, data.purpose, lock=True)
    revision, epoch = previous(
        pointer, prior, data.expected_previous_id, data.expected_previous_revision
    )
    require(
        prior is None
        or (prior.owner_id, prior.visibility, prior.purpose)
        == (value.owner_id, value.visibility, value.purpose),
        "POLICY_SERIES_SCOPE_CHANGED",
    )
    require(
        original(s, ctx, pid, data.source, models.PolicyMaterial)[0] == value
        and authority(s, ctx, pid, scope, models.POLICY_OPERATION, data.purpose)[0] == auth,
        "SOURCE_STALE",
    )
    require(
        same(
            _source_guard(
                s, ctx, pid, value.visibility, value.owner_id, reads, (data.source,), io=False
            ),
            basis,
        )
        and _caller(s, ctx, pid, write=True)[0] == caller
        and _project(s, ctx, scope)[1] == project_stamp
        and old._runtime_stamp(s) == runtime,
        "SOURCE_STALE",
    )
    _same_uow(s, uow, ctx, common_digest(vars(ctx)))
    saved_at = clock()
    require(
        value.valid_from <= saved_at < earliest_deadline(value.valid_until, until, auth_until),
        "SOURCE_STALE",
    )
    row = models.ChangePolicyFact(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=scope.project_id,
        owner_id=value.owner_id,
        visibility=value.visibility,
        revision=revision,
        epoch=epoch,
        purpose=value.purpose,
        purpose_sha256=digest(value.purpose),
        previous_id=prior.id if prior else None,
        previous_revision=prior.revision if prior else None,
        actor_id=ctx.actor_id,
        command_id=command_id,
        operation=models.POLICY_OPERATION,
        intent_digest=fingerprint,
        status="published",
        nature=value.nature,
        material=value.model_dump(mode="json"),
        material_sha256=digest(value),
        source=data.source.model_dump(mode="json"),
        sources=[data.source.model_dump(mode="json")],
        required_source_read_set=reads,
        source_basis=basis,
        authority_snapshot=auth,
        input_snapshot={"payload": data.model_dump(mode="json")},
        valid_from=value.valid_from,
        valid_until=value.valid_until,
        created_at=saved_at,
    )
    s.add(row)
    s.flush([row])  # BEFORE Current target guard, never a commit/second Receipt.
    if pointer is None:
        s.add(
            models.ChangePolicyCurrent(
                tenant_id=ctx.tenant_id,
                product_id=pid,
                project_id=scope.project_id,
                purpose_sha256=row.purpose_sha256,
                owner_id=row.owner_id,
                visibility=row.visibility,
                fact_id=row.id,
                revision=row.revision,
                epoch=row.epoch,
            )
        )
    else:
        pointer.fact_id, pointer.revision, pointer.epoch = row.id, row.revision, row.epoch
    receipt = append_receipt(
        s, ctx, cmd, models.POLICY_FAMILY, row, fingerprint, fingerprint, row.visibility
    )
    s.add(
        RequestKey(
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            key=request_key,
            digest=fingerprint,
            receipt_id=receipt.id,
        )
    )
    return receipt_view(receipt)


@dataclass(frozen=True, eq=False)
class ActionIntentRead:
    selection_id: UUID
    item_id: UUID
    intent_id: UUID
    action_id: UUID
    action_sha256: str
    executor_id: UUID
    order_id: UUID
    selection: outputs.SelectionProof


def _intent_digest(value):
    return digest(_json({**vars(value), "selection": value.selection.model_dump(mode="json")}))


class ApprovedActionIntentOwner:
    """Only the actual approved order + persistent T2 selection can bind an action."""

    def __init__(self):
        self._handles = WeakKeyDictionary()

    def read(self, s, ctx, pid, *, change_id, order_id, item_id, action_id):
        uow, runtime = _uow(s), old._runtime_stamp(s)
        pointer, row = current_fixed(s, ctx, pid, change_id)
        request = snapshot(row)
        order = next((o for o in request.orders if o.id == order_id), None)
        require(order is not None, "APPROVED_ACTION_INTENT_REQUIRED", 503)
        item = next((i for i in order.plan.items if i.id == item_id), None)
        require(item is not None, "ACTION_INTENT_SCOPE_MISMATCH")
        # This calls the actual immutable order/dual T2 approval owner, not a status flag.
        approval_until = approved_order(s, ctx, pid, request, order)
        _, purpose = old._seed(s, ctx, pid, (*request.roots, *request.references))
        selection = selection_callback(
            s, ctx, pid, scope=request.scope, purpose=purpose, request=request, item=item
        )
        _, selected = selection_pointer(s, ctx, pid, request.scope, request.id, item.id)
        material = models.SelectionMaterial.model_validate(selected.material)
        require(material.action_id == action_id, "ACTION_INTENT_SCOPE_MISMATCH")
        approval_until = earliest_deadline(
            approval_until, approved_order(s, ctx, pid, request, order)
        )
        last_pointer, last_row = current_fixed(s, ctx, pid, change_id)
        require(
            (last_pointer.id, last_row.id, last_row.request_sha256)
            == (pointer.id, row.id, row.request_sha256)
            and old._runtime_stamp(s) == runtime,
            "SOURCE_STALE",
        )
        _caller(s, ctx, pid, write=False)
        _project(s, ctx, request.scope)
        _same_uow(s, uow, ctx, common_digest(vars(ctx)))
        require(
            clock()
            < earliest_deadline(
                order.plan.expires_at,
                selection.valid_until,
                approval_until,
                *[a.expires_at for a in order.approvals],
            ),
            "SOURCE_STALE",
        )
        handle = ActionIntentRead(
            selected.id,
            item.id,
            item.intent.id,
            action_id,
            material.action_sha256,
            material.executor_id,
            order.id,
            selection,
        )
        self._handles[handle] = (
            s,
            uow,
            common_digest(vars(ctx)),
            runtime,
            (change_id, order_id, item_id, action_id),
            _intent_digest(handle),
        )
        return handle

    def refresh(self, s, ctx, pid, previous):
        entry = self._handles.get(previous)
        require(
            entry is not None and entry[0] is s and entry[2] == common_digest(vars(ctx)),
            "ACTION_INTENT_OWNER_REQUIRED",
            503,
        )
        _same_uow(s, entry[1], ctx, entry[2])
        require(
            entry[3] == old._runtime_stamp(s) and entry[5] == _intent_digest(previous),
            "SOURCE_STALE",
        )
        current = self.read(
            s,
            ctx,
            pid,
            change_id=entry[4][0],
            order_id=entry[4][1],
            item_id=entry[4][2],
            action_id=entry[4][3],
        )
        require(_intent_digest(current) == entry[5], "SOURCE_STALE")
        return current


def approved_order(s, ctx, pid, request, order):
    """Read actual original order/dual approvals and common groups, not a flag."""
    from pdos_next.domain.change_execution.models import ChangeRequestVersion

    require(
        {a.discipline for a in order.approvals} == set(order.required_disciplines)
        and {"engineering", "manufacturing"} <= set(order.required_disciplines),
        "DUAL_APPROVAL_REQUIRED",
    )
    original = _one(
        s,
        outputs.ChangeOrderRecord,
        outputs.ChangeOrderRecord.tenant_id == ctx.tenant_id,
        outputs.ChangeOrderRecord.product_id == pid,
        outputs.ChangeOrderRecord.change_id == request.id,
        outputs.ChangeOrderRecord.order_id == order.id,
    )
    require(
        original.content_sha256 == order.content_digest
        and original.order_snapshot["plan"] == order.plan.model_dump(mode="json"),
        "INTEGRITY_MISMATCH",
    )
    atoms = [original]
    for decision in order.approvals:
        atom = _one(
            s,
            outputs.ChangeApprovalRecord,
            outputs.ChangeApprovalRecord.tenant_id == ctx.tenant_id,
            outputs.ChangeApprovalRecord.product_id == pid,
            outputs.ChangeApprovalRecord.change_id == request.id,
            outputs.ChangeApprovalRecord.order_id == order.id,
            outputs.ChangeApprovalRecord.discipline == decision.discipline,
        )
        require(
            atom.approval_snapshot == decision.model_dump(mode="json")
            and atom.shared_proof_id == decision.decision_id
            and atom.actor_id == decision.actor_id
            and atom.actor_id != request.requester_id
            and decision.content_digest == order.content_digest,
            "INTEGRITY_MISMATCH",
        )
        atoms.append(atom)
    deadlines = []
    for atom in atoms:
        parent = _one(
            s,
            ChangeRequestVersion,
            ChangeRequestVersion.tenant_id == ctx.tenant_id,
            ChangeRequestVersion.product_id == pid,
            ChangeRequestVersion.project_id == request.scope.project_id,
            ChangeRequestVersion.change_id == request.id,
            ChangeRequestVersion.id == atom.change_version_id,
            ChangeRequestVersion.revision == atom.change_revision,
        )
        fixed = snapshot(parent)
        require(
            any(
                o.id == order.id and o.content_digest == order.content_digest for o in fixed.orders
            ),
            "INTEGRITY_MISMATCH",
        )
        op = atom.operation
        group = common_group(
            s,
            ctx,
            pid,
            parent,
            operation=op,
            event="change.order_prepared" if op == "change.order.prepare" else "change.approved",
            actor=atom.actor_id,
        )
        require(group["receipt"]["subject_type"] == "change_request", "INTEGRITY_MISMATCH")
        _atom_proof(s, ctx, pid, atom, group)
        deadlines.append(original_authority(s, ctx, pid, atom))
        # Formal order atoms retain the complete review basis. _source_guard
        # returns its artifact projection; the other owner/closure proofs remain
        # separately bound by the immutable order and actual consumed approvals.
        artifacts = atom.source_basis.get("artifacts") if type(atom.source_basis) is dict else None
        require(type(artifacts) is dict and bool(artifacts), "SOURCE_STALE")
        require(
            same(
                _source_guard(
                    s,
                    ctx,
                    pid,
                    atom.visibility,
                    atom.owner_id,
                    atom.required_source_read_set,
                    tuple(SourceRef.model_validate(x) for x in atom.sources),
                ),
                artifacts,
            ),
            "SOURCE_STALE",
        )
    deadline = earliest_deadline(
        order.plan.expires_at, *[a.expires_at for a in order.approvals], *deadlines
    )
    require(deadline_current(deadline), "RECHECK_REQUIRED")
    return deadline
