"""Answer-to-knowledge provenance from actual immutable reads; no inference or fake artifact."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.work_state import user_goal
from pdos_next.domain.preproject.access import human
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.enterprise_search.assistant_answer import checked_sources
from pdos_next.enterprise_search.assistant_sources import current
from pdos_next.errors import DomainError
from pdos_next.service import digest, require_access
from sqlalchemy import select

FIELDS = ("source_type", "source_id", "source_revision", "content_hash", "category_id")


def require(
    value, message="回答来源已变化，请重新读取后整理知识。", code="SOURCE_STALE", status=409
):
    if not value:
        raise DomainError(code, message, status)


def answer_body(run):
    body = (run.result or {}).get("summary", "").strip()
    assistant = (run.result or {}).get("result", {}).get("assistant", {})
    comparison, task = assistant.get("comparison"), assistant.get("task_result")
    if comparison:
        from pdos_next.enterprise_search.comparison_result import markdown

        body += "\n\n" + markdown(comparison)
    if task:
        from pdos_next.enterprise_search.task_result import markdown

        body += "\n\n" + markdown(task)
    return body.strip()


def bound_proof(session, run, *, category_id=None):
    """Actual bound material versions are dependencies, never fabricated citations."""
    from pdos_next.enterprise_search.sources import select_sources

    expected = {
        UUID(str(ref["artifact_id"])): ref["expected_revision"]
        for ref in getattr(run, "read_sources", []) or []
    }
    if not expected:
        return [], {}
    relation = select_sources(source_type="artifact").subquery()
    rows = (
        session.execute(select(relation).where(relation.c.source_id.in_(expected))).mappings().all()
    )
    require(len(rows) == len(expected), "原绑定资料当前不可读。", "SOURCE_UNAVAILABLE", 403)
    proof = []
    for row in rows:
        require(
            row["source_revision"] == expected[row["source_id"]]
            and row["category_id"] == (category_id or run.category_id),
            "原绑定资料版本或范围已变化。",
            "SOURCE_UNAVAILABLE",
            403,
        )
        proof.append(
            {key: str(row[key]) if isinstance(row[key], UUID) else row[key] for key in FIELDS}
        )
    return proof, recheck(session, proof)


def capture(session, ctx, run_id, *, expected_digest=None):
    human(session, ctx)
    run = session.get(AgentRun, run_id)
    require(
        run is not None
        and run.tenant_id == ctx.tenant_id
        and run.requester_id == ctx.requester_id
        and (run.category_id == ctx.category_id or run.category_id is None)
        and ctx.category_id is not None
        and run.state in {"completed", "partial"}
        and run.reverted_at is None,
        "请选择本人有权写入的目标品类，再从本人已完成且有实际来源的回答整理知识。",
        "FORBIDDEN_SCOPE",
        403,
    )
    require_access(session, ctx, run.product_id, write=False)
    if run.project_id:
        from pdos_next.agent_kernel.project_scope import require_project

        require_project(session, ctx, run.project_id, run.product_id)
    actual = checked_sources(session, run)
    issued, _ = ledger.carried(session, scope_for_run(run))
    answer = (run.result or {}).get("result", {}).get("assistant", {})
    ids = set(answer.get("citation_ids", []))
    require(
        ids and ids <= actual.keys() and ids <= issued.keys(),
        "请先在目标品类引用实际资料形成回答，再整理为知识。当前原回答会保留。",
        "MISSING_REQUIRED_EVIDENCE",
        422,
    )
    artifacts, private, customer = [], run.private_context, False
    source_products = set()
    # Unconstrained answer prose may depend on every source actually disclosed
    # in this Run or carried history, including an unquoted search result. A
    # model's citation selection cannot remove those dependencies or their ACLs.
    require(actual.keys() == issued.keys())
    fixed_sources = {}
    for cid in sorted(issued):
        fixed, row = issued[cid], actual[cid]
        require(
            row.get("fixed_body_available", True)
            and fixed["source_revision"] == row["source_revision"]
            and fixed["content_hash"] == row["content_hash"]
        )
        require(
            str(row["category_id"]) == str(ctx.category_id),
            "本回答含其他品类来源。请在目标品类重新查询并引用同品类资料后整理，原回答会保留。",
            "FORBIDDEN_SCOPE",
            403,
        )
        if row.get("product_id") is not None:
            source_products.add(str(row["product_id"]))
        private |= row["private"]
        customer |= row["customer_original"]
        reference = {key: fixed[key] for key in FIELDS}
        key = (reference["source_type"], reference["source_id"])
        require(
            key not in fixed_sources or fixed_sources[key] == reference,
            "同一回答携带了同一来源的不同固定版本，请重新查询后整理知识。",
        )
        fixed_sources[key] = reference
        if cid in ids and fixed["source_type"] == "artifact":
            evidence = next(
                (source for source in answer.get("sources", []) if source["citation_id"] == cid),
                None,
            )
            locator = (evidence or {}).get("locator", {})
            line = locator.get("line_start")
            quote = (evidence or {}).get("quote")
            if line and quote:
                from pdos_next.domain.quality_execution.evidence import refs_from_exact

                exact = refs_from_exact(
                    session,
                    ctx,
                    run.product_id,
                    [
                        SimpleNamespace(
                            artifact_id=UUID(fixed["source_id"]),
                            expected_revision=fixed["source_revision"],
                            line=line,
                            quote=quote,
                        )
                    ],
                )
                artifacts.extend(value.model_dump(mode="json") for value in exact)

    bound, bound_rows = bound_proof(session, run, category_id=ctx.category_id)
    source_products.update(
        str(row["product_id"]) for row in bound_rows.values() if row.get("product_id") is not None
    )
    private |= any(row["private"] for row in bound_rows.values())
    customer |= any(row["customer_original"] for row in bound_rows.values())
    for reference in bound:
        key = (reference["source_type"], reference["source_id"])
        require(key not in fixed_sources or fixed_sources[key] == reference)
        fixed_sources[key] = reference
    proof = sorted(fixed_sources.values(), key=lambda ref: (ref["source_type"], ref["source_id"]))
    body = answer_body(run)
    require(body, "原回答尚未形成可保存的正文。", "MISSING_REQUIRED_EVIDENCE", 422)
    fingerprint = digest({"body": body, "sources": proof})
    require(expected_digest is None or expected_digest == fingerprint)
    return {
        "run": run,
        "question": user_goal(run.goal),
        "answer": body,
        "answer_digest": fingerprint,
        "source_proof": proof,
        "artifacts": artifacts,
        "source_product_ids": sorted(source_products),
        "private": bool(private),
        "customer_original": bool(customer),
    }


def recheck(session, proof):
    """Ordinary recipient RLS/scan/dependency check; it never reads a private conversation."""
    selected = {str(index): deepcopy(ref) for index, ref in enumerate(proof)}
    # current() uses these non-authoritative old classification hints only when
    # annotating a change. The fixed IDs/revision/hash remain the actual selectors.
    for value in selected.values():
        value.update(private=False, customer_original=False, is_current=True)
    actual, missing = current(session, selected)
    require(
        not missing and len(actual) == len(selected),
        "知识所引的固定资料当前不可读或需要重新核对。",
        "SOURCE_UNAVAILABLE",
        403,
    )
    return actual


def review_for(session, kind, identity):
    from .assistant_models import KnowledgeAnswerReview

    return session.scalar(
        select(KnowledgeAnswerReview).where(
            KnowledgeAnswerReview.subject_kind == kind,
            KnowledgeAnswerReview.subject_id == identity,
        )
    )


def inherited_proof(session, proof, seen=None):
    """Flatten reviewed answers; legacy knowledge retains native dependency checks."""
    seen = set() if seen is None else seen
    found = {}
    for ref in proof:
        key = (ref["source_type"], ref["source_id"])
        require(key not in seen, "知识来源存在循环，不能重复沉淀。", "VALIDATION_FAILED", 422)
        prior = (
            review_for(session, "category", UUID(ref["source_id"]))
            if key[0] == "knowledge"
            else None
        )
        if prior is None and key[0] == "knowledge":
            prior = review_for(session, "rule", UUID(ref["source_id"]))
        children = (
            inherited_proof(session, prior.source_proof, seen | {key})
            if prior and prior.source_proof
            else [ref]
        )
        for child in children:
            found[(child["source_type"], child["source_id"])] = child
    return list(found.values())
