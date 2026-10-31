"""Explicit human revisions alongside immutable category AI candidates."""

from sqlalchemy import select

from .access import fail
from .category_models import KnowledgeEntry, ParameterVersion
from .category_schemas import KnowledgeAdd, KnowledgeWithdraw, ParameterPublish


def effective(payload):
    edits = getattr(payload, "human_edits", None)
    if edits is None:
        return payload
    if not payload.prepared_by_run_id or not payload.candidate_digest:
        fail("FORBIDDEN_SCOPE", "candidate_edit_binding", "人工修订须保留原小Pai候选。", 403)
    from .schemas import ItemPatch, ProposalCreate

    if isinstance(payload, ProposalCreate):
        allowed = {"title", "brief", "groups"}
    elif isinstance(payload, ItemPatch):
        allowed = {"ops"}
    elif isinstance(payload, KnowledgeAdd) and payload.kind in {"competitor", "voice"}:
        allowed = {"content"}
    elif isinstance(payload, ParameterPublish):
        allowed = {
            "name",
            "value_type",
            "enum_values",
            "unit",
            "direction",
            "standard_condition",
            "method",
            "acceptance_criterion",
            "change_note",
        }
        if payload.parameter_id is None:
            allowed.add("key")
    elif isinstance(payload, KnowledgeWithdraw):
        allowed = {"reason"}
    else:
        allowed = set()
    if not edits or not set(edits) <= allowed:
        fail(
            "FORBIDDEN_SCOPE",
            "candidate_edit_scope",
            "只能编辑当前资料内容，不能改变对象、来源范围或原版本。",
            403,
        )
    body = payload.model_dump(mode="json", exclude={"human_edits"})
    return type(payload).model_validate({**body, **edits})


def saved_receipt_id(session, candidate_id):
    for model in (KnowledgeEntry, ParameterVersion):
        receipt = session.scalar(
            select(model.receipt_id).where(
                model.prepared_candidate_id == candidate_id,
            )
        )
        if receipt:
            return receipt
    from pdos_next.models import Receipt

    return session.scalar(
        select(Receipt.id).where(
            Receipt.result["prepared_candidate_id"].astext == str(candidate_id)
        )
    )
