"""Append-only specification edits within one unsealed definition draft.

The immutable definition revision is a container. Item Current versions, actual
source references and execution provenance are the write/confirmation boundary.
"""

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.domain.preproject.access import fail, human, member
from pdos_next.domain.preproject.category_service import check_parameter
from pdos_next.domain.preproject.models import PreparedCandidate
from pdos_next.models import Principal
from pdos_next.request_proof import command_inputs_once
from pdos_next.schemas.products.definition_items import DefinitionItemPatch
from pdos_next.service import require_access, source_for

from .definition_item_consumers import ensure_unconsumed
from .models import DefinitionRevision, DefinitionSpecRow

# Fixed references may connect different Products in this Category. Serialize
# their creation with item edits before either Product lock is acquired.
category_lifecycle_fence = True


@dataclass
class ValidatedItems:
    definition: object
    provenance: dict
    changes: tuple
    confirmation_id: UUID | None = None


@dataclass(frozen=True)
class RevertItems:
    run_id: UUID
    changes: tuple
    original_rows: tuple
    retained: tuple


def semantic(payload):
    return payload.model_dump(mode="json", exclude_unset=True, exclude={"confirmation_token"})


def supports_confirmation(command):
    return True


def needs_confirmation(payload):
    return bool(payload.prepared_by_run_id)


def _definition(s, ctx, product, identity, *, reverting=False):
    require_access(s, ctx, product.id, write=True, lock=True)
    row = s.scalar(
        select(DefinitionRevision)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.category_id == ctx.category_id,
            DefinitionRevision.product_id == product.id,
            DefinitionRevision.id == identity,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if not row:
        fail("FORBIDDEN_SCOPE", "definition_not_readable", "定义不属于当前可读型号。", 403)
    if row.sealed or row.status != "draft":
        if reverting:
            fail(
                "UNDO_BLOCKED_BY_DEPENDENCY", "definition_consumed", "定义已发布或封存，不能撤回。"
            )
        fail("VALIDATION_FAILED", "definition_locked", "只能编辑尚未封存的定义草稿。")
    ensure_unconsumed(s, ctx, row, reverting=reverting)
    newer = s.scalar(
        select(DefinitionRevision.id)
        .where(
            DefinitionRevision.tenant_id == ctx.tenant_id,
            DefinitionRevision.product_id == product.id,
            DefinitionRevision.variant_id == row.variant_id,
            DefinitionRevision.revision > row.revision,
        )
        .limit(1)
    )
    if newer:
        fail("VERSION_CONFLICT", "definition_not_current", "已有后续定义版本，请读取当前草稿。")
    return row


def _writing_path(s, ctx, command, product, payload):
    if ctx.agent_run_id:
        from pdos_next.agent_kernel.execution import command_call, command_run

        run = command_run(s, ctx, product.id)
        command_call(s, ctx, command.operation)
        return dict(
            origin="ai_draft",
            writer_id=run.writer_id,
            run_id=run.id,
            confirmed_by=None,
            prepared_candidate_id=None,
            private_context=run.private_context,
        )
    human(s, ctx)
    if not payload.prepared_by_run_id:
        if payload.candidate_digest:
            fail("FORBIDDEN_SCOPE", "candidate_binding_invalid", "候选摘要缺少实际运行。", 403)
        return dict(
            origin="human",
            writer_id=ctx.actor_id,
            run_id=None,
            confirmed_by=None,
            prepared_candidate_id=None,
            private_context=False,
        )
    run = s.scalar(
        select(AgentRun)
        .where(
            AgentRun.tenant_id == ctx.tenant_id,
            AgentRun.id == payload.prepared_by_run_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    candidate = s.scalar(
        select(PreparedCandidate).where(
            PreparedCandidate.tenant_id == ctx.tenant_id,
            PreparedCandidate.category_id == ctx.category_id,
            PreparedCandidate.run_id == payload.prepared_by_run_id,
            PreparedCandidate.candidate_digest == payload.candidate_digest,
        )
    )
    if (
        not run
        or not candidate
        or run.category_id != ctx.category_id
        or run.product_id != product.id
        or run.requester_id != ctx.requester_id
        or run.reverted_at
        or run.state == "cancelled"
        or candidate.requester_id != ctx.requester_id
        or candidate.writer_id != run.writer_id
        or candidate.operation != command.operation
        or candidate.payload
        != payload.model_dump(
            mode="json",
            exclude_unset=True,
            exclude={"confirmation_token", "prepared_by_run_id", "candidate_digest"},
        )
        or candidate.execution_binding.get("model", {}).get("cancel_epoch") != run.cancel_epoch
    ):
        fail(
            "FORBIDDEN_SCOPE", "candidate_binding_invalid", "候选不属于本人、本型号或原运行。", 403
        )
    writer = s.get(Principal, run.writer_id)
    if (
        not writer
        or writer.tenant_id != ctx.tenant_id
        or not writer.active
        or writer.kind != "agent"
    ):
        fail("FORBIDDEN_SCOPE", "candidate_writer_invalid", "原候选署名不可用。", 403)
    return dict(
        origin="ai_draft",
        writer_id=writer.id,
        run_id=run.id,
        confirmed_by=ctx.requester_id,
        prepared_candidate_id=candidate.id,
        private_context=run.private_context,
    )


def _references(s, ctx, product, definition, refs):
    from pdos_next.domain.preproject.service import _references as category_references

    # De-duplicate the complete incoming patch's direct references once. The common
    # request proof caches source authority, locks and withdrawal/version checks.
    unique = {tuple(sorted(ref.model_dump(mode="json").items())): ref for ref in refs}
    category_refs, privacy = [], []
    for ref in unique.values():
        if ref.type not in {"artifact", "original"}:
            category_refs.append(ref)
            continue
        source = source_for(s, ctx, product.id, ref.id, ref.version)
        lines = source.content.splitlines()
        if (
            not ref.line
            or not ref.quote
            or ref.line > len(lines)
            or ref.quote not in lines[ref.line - 1]
        ):
            fail("VALIDATION_FAILED", "quote_not_in_source", "引用须为原件指定行的逐字片段。")
        privacy.append("shared" if source.visibility == "category" else "private")
    privacy.extend(kind for _ref, kind in category_references(s, ctx, category_refs))
    if definition.visibility == "category" and "private" in privacy:
        fail("FORBIDDEN_SCOPE", "private_source_in_shared", "共享定义不能引入私有来源。", 403)


def _current_rows(s, ctx, definition, identities=(), keys=()):
    from .models import DefinitionSpecCurrent

    query = select(DefinitionSpecCurrent).where(
        DefinitionSpecCurrent.tenant_id == ctx.tenant_id,
        DefinitionSpecCurrent.category_id == ctx.category_id,
        DefinitionSpecCurrent.product_id == definition.product_id,
        DefinitionSpecCurrent.definition_id == definition.id,
    )
    if identities or keys:
        query = query.where(
            DefinitionSpecCurrent.item_id.in_(identities) | DefinitionSpecCurrent.key.in_(keys)
        )
    return s.scalars(
        query.order_by(DefinitionSpecCurrent.item_id)
        .execution_options(populate_existing=True)
    ).all()


@command_inputs_once
def validate(s, ctx, command, product, payload: DefinitionItemPatch):
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        fail("FORBIDDEN_SCOPE", "definition_scope_mismatch", "定义命令须绑定当前实际型号。", 403)
    definition = _definition(s, ctx, product, payload.definition_id)
    provenance = _writing_path(s, ctx, command, product, payload)
    if provenance["private_context"] and definition.visibility == "category":
        fail("FORBIDDEN_SCOPE", "private_context_run", "私有运行内容不能写入共享定义。", 403)
    current = _current_rows(
        s,
        ctx,
        definition,
        identities=[op.item_id for op in payload.ops if op.item_id],
        keys=[op.content.key for op in payload.ops if op.content],
    )
    by_id, by_key = {row.item_id: row for row in current}, {row.key: row for row in current}
    changes, refs = [], []
    for op in payload.ops:
        pointer, before = by_id.get(op.item_id), None
        if op.item_id:
            if not pointer or pointer.current_version != op.base_version:
                fail("VERSION_CONFLICT", "definition_item_moved", "规格条目已变化，请核对该条目。")
            before = s.get(DefinitionSpecRow, pointer.current_row_id)
            if not before:
                fail("SOURCE_UNAVAILABLE", "definition_item_unreadable", "当前规格版本不可读。")
            if ctx.agent_run_id and (
                before.origin == "human" or before.confirmed_by or before.item_status == "confirmed"
            ):
                fail("CONFIRMATION_REQUIRED", "human_value_protected", "人工值须转一次确认候选。")
        if op.op == "remove":
            if pointer.removed:
                fail("VERSION_CONFLICT", "definition_item_removed", "规格条目已移除。")
        else:
            content = op.content
            if pointer and pointer.key != content.key:
                fail("VALIDATION_FAILED", "definition_item_key_immutable", "规格稳定键不能改变。")
            if not pointer and content.key in by_key:
                fail(
                    "VALIDATION_FAILED", "definition_item_key_taken", "规格键已存在，请修订原条目。"
                )
            if provenance["origin"] == "ai_draft" and content.item_status == "confirmed":
                fail("VALIDATION_FAILED", "ai_cannot_confirm", "AI 草稿不能标为人工已确认。")
            if content.parameter_id:
                parameter = check_parameter(
                    s,
                    ctx,
                    content.parameter_id,
                    content.parameter_version,
                    content.unit,
                    content.value_type,
                )
                if parameter.key != content.key:
                    fail("VALIDATION_FAILED", "parameter_key_mismatch", "条目键须等于字典稳定键。")
            if content.owner_id:
                member(s, ctx, content.owner_id)
            refs.extend(op.source_refs)
        changes.append((op, before))
    _references(s, ctx, product, definition, refs)
    return ValidatedItems(definition, provenance, tuple(changes))


def confirmation_subject(s, ctx, command, product, payload):
    return "definition_revision", validate(s, ctx, command, product, payload).definition


def preview_view(s, ctx, command, product, payload):
    prepared = validate(s, ctx, command, product, payload)
    return {
        "operation": command.operation,
        "payload": semantic(payload),
        "definition_id": str(prepared.definition.id),
        "changes": [
            {
                "item_id": str(before.item_id) if before else None,
                "base_version": before.item_version if before else None,
                "key": before.key if before else op.content.key,
                "op": op.op,
            }
            for op, before in prepared.changes
        ],
        "effect": "追加所选规格条目版本；保留原版本与来源。",
    }


def _copy_fields(row):
    excluded = {
        "id",
        "tenant_id",
        "category_id",
        "product_id",
        "definition_id",
        "created_at",
        "item_id",
        "item_version",
        "receipt_id",
        "origin",
        "writer_id",
        "run_id",
        "confirmed_by",
        "prepared_candidate_id",
    }
    return {
        column.name: deepcopy(getattr(row, column.name))
        for column in row.__table__.columns
        if column.name not in excluded
    }


def _content_fields(content):
    fields = content.model_dump()
    fields["text"] = fields.pop("text_value")
    fields["method"] = fields.pop("verification_method")
    fields["test_conditions"] = list(content.test_conditions)
    fields["reason"] = content.reason or ""
    fields["state"] = (
        "needs_confirmation" if content.item_status == "expert_pending" else "proposed"
    )
    return fields


def apply_validated(s, ctx, command, product, payload, validated):
    definition = validated.definition
    provenance = {
        key: value for key, value in validated.provenance.items() if key != "private_context"
    }
    rows = []
    for op, before in validated.changes:
        fields = _copy_fields(before) if op.op == "remove" else _content_fields(op.content)
        if op.op != "remove":
            fields["source_refs"] = [ref.model_dump(mode="json") for ref in op.source_refs]
        fields["removed"] = op.op == "remove"
        row_id = uuid4()
        row = DefinitionSpecRow(
            id=row_id,
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product.id,
            definition_id=definition.id,
            item_id=before.item_id if before else row_id,
            item_version=before.item_version + 1 if before else 1,
            **fields,
            **provenance,
        )
        s.add(row)
        rows.append(row)
    s.flush(rows)
    subject = SimpleNamespace(
        id=definition.id,
        revision=definition.revision,
        status=definition.status,
        confirmation_id=validated.confirmation_id,
        category_id=ctx.category_id,
        changed_rows=rows,
        prepared_by_run_id=provenance["run_id"],
        action_result={
            "definition_id": str(definition.id),
            "origin": provenance["origin"],
            "writer_id": str(provenance["writer_id"]),
            "run_id": str(provenance["run_id"]) if provenance["run_id"] else None,
            "confirmed_by": str(provenance["confirmed_by"]) if provenance["confirmed_by"] else None,
            "changes": [_change(row) for row in rows],
        },
    )
    return subject, "definition_revision", definition.visibility


def _change(row):
    return {
        "item_id": str(row.item_id),
        "item_version": row.item_version,
        "row_id": str(row.id),
        "key": row.key,
        "removed": row.removed,
    }


def apply(s, ctx, command, product, payload):
    return apply_validated(
        s, ctx, command, product, payload, validate(s, ctx, command, product, payload)
    )


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    for row in subject.changed_rows:
        row.receipt_id = receipt.id
    s.flush(subject.changed_rows)


def prepare_revert(s, ctx, run, receipts):
    """Prepare all this run's definition patches together, including repeated edits."""
    from pdos_next.models import Product

    human(s, ctx)
    if (
        run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.requester_id != ctx.requester_id
        or not run.product_id
        or run.reverted_at
    ):
        fail("FORBIDDEN_SCOPE", "run_scope_mismatch", "只能撤回本人当前型号运行。", 403)
    product = s.get(Product, run.product_id)
    if not product:
        fail("FORBIDDEN_SCOPE", "run_scope_mismatch", "运行型号已不可读。", 403)
    grouped, all_rows = {}, []
    for receipt in receipts:
        if receipt.operation != "product.definition.item.patch":
            continue
        if (
            receipt.tenant_id != ctx.tenant_id
            or receipt.product_id != run.product_id
            or receipt.agent_run_id != run.id
            or receipt.actor_id not in {run.writer_id, run.requester_id}
            or receipt.requester_id != run.requester_id
            or receipt.category_id != ctx.category_id
        ):
            fail("FORBIDDEN_SCOPE", "run_receipt_mismatch", "回执不属于实际运行。", 403)
        if not receipt.result.get("changes"):
            fail(
                "UNDO_BLOCKED_BY_DEPENDENCY",
                "definition_item_history_missing",
                "运行回执缺少原条目记录。",
            )
        for change in receipt.result["changes"]:
            row = s.get(DefinitionSpecRow, UUID(change["row_id"]))
            if (
                not row
                or row.receipt_id != receipt.id
                or row.run_id != run.id
                or row.origin != "ai_draft"
                or row.writer_id != run.writer_id
                or row.product_id != product.id
                or row.category_id != ctx.category_id
                or row.item_id != UUID(change["item_id"])
                or row.item_version != change["item_version"]
            ):
                fail(
                    "UNDO_BLOCKED_BY_DEPENDENCY",
                    "definition_item_changed",
                    "规格已由人确认或不属于本次运行原写入。",
                )
            grouped.setdefault(row.definition_id, {}).setdefault(row.item_id, []).append(row)
            all_rows.append(row)
    changes, retained = [], []
    for identity, item_groups in sorted(grouped.items(), key=lambda pair: str(pair[0])):
        definition = _definition(s, ctx, product, identity, reverting=True)
        current = {
            row.item_id: row
            for row in _current_rows(s, ctx, definition, identities=list(item_groups))
        }
        for item_id, rows in sorted(item_groups.items(), key=lambda pair: str(pair[0])):
            rows.sort(key=lambda row: row.item_version)
            first, latest, pointer = rows[0], rows[-1], current.get(item_id)
            if (
                not pointer
                or pointer.current_row_id != latest.id
                or pointer.current_version != latest.item_version
                or any(row.confirmed_by or row.item_status == "confirmed" for row in rows)
                or [row.item_version for row in rows]
                != list(range(first.item_version, latest.item_version + 1))
            ):
                retained.append(
                    {
                        "definition_id": str(identity),
                        "item_id": str(item_id),
                        "reason": "definition_item_changed_or_confirmed",
                    }
                )
                continue
            baseline = (
                None
                if first.item_version == 1
                else s.scalar(
                    select(DefinitionSpecRow).where(
                        DefinitionSpecRow.tenant_id == ctx.tenant_id,
                        DefinitionSpecRow.definition_id == identity,
                        DefinitionSpecRow.item_id == item_id,
                        DefinitionSpecRow.item_version == first.item_version - 1,
                    )
                )
            )
            if first.item_version > 1 and baseline is None:
                fail(
                    "UNDO_BLOCKED_BY_DEPENDENCY",
                    "definition_item_history_missing",
                    "原版本不可读。",
                )
            changes.append((definition, latest, baseline))
    return RevertItems(run.id, tuple(changes), tuple(all_rows), tuple(retained))


def apply_revert(s, ctx, plan, receipt_id):
    """Append compensation; the original item versions and receipts remain intact."""
    rows = []
    for definition, latest, baseline in plan.changes:
        fields = _copy_fields(baseline or latest)
        fields["removed"] = baseline.removed if baseline else True
        provenance = (
            {
                key: getattr(baseline, key)
                for key in (
                    "origin", "writer_id", "run_id", "confirmed_by", "prepared_candidate_id"
                )
            }
            if baseline
            else dict(
                origin="human", writer_id=ctx.actor_id, run_id=None,
                confirmed_by=None, prepared_candidate_id=None,
            )
        )
        row = DefinitionSpecRow(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=definition.product_id,
            definition_id=definition.id,
            item_id=latest.item_id,
            item_version=latest.item_version + 1,
            receipt_id=receipt_id,
            **provenance,
            **fields,
        )
        s.add(row)
        rows.append(row)
    s.flush(rows)
    return rows
