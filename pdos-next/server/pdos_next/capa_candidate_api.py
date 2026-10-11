"""Current candidate work context; all writes remain in common commands."""

from hashlib import sha256
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from pdos_next.capa_history import page_query, page_rows
from pdos_next.database import tenant_session
from pdos_next.domain.capa_effectiveness import (
    anchor_storage,
    candidate_commands,
    candidate_prepare,
    candidate_storage,
    fact_atom_storage,
)
from pdos_next.domain.capa_effectiveness import (
    service as candidates_service,
)
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import FixedRef
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.quality_followup_views import _links, owners
from pdos_next.request_proof import scope_is_held
from pdos_next.service import Context, digest, require_access, source_for


def _selected(s, ctx, product_id, issue_id):
    """Select an actual current Issue; the candidate owner verifies completion."""
    pointer = fact_atom_storage._one(
        s,
        QualityIssueCurrent,
        QualityIssueCurrent.tenant_id == ctx.tenant_id,
        QualityIssueCurrent.product_id == product_id,
        QualityIssueCurrent.issue_id == issue_id,
    )
    row = fact_atom_storage._one(
        s,
        QualityIssueVersion,
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == product_id,
        QualityIssueVersion.project_id == pointer.project_id,
        QualityIssueVersion.issue_id == issue_id,
        QualityIssueVersion.id == pointer.issue_version_id,
        QualityIssueVersion.revision == pointer.issue_revision,
    )
    issue = anchor_storage._snapshot(row, ctx, product_id, issue_id)
    project = anchor_storage._project(s, ctx, product_id, row.project_id)
    if issue.capa is None:
        raise DomainError("INVALID_STATE", "请先读取已实际完成的整改及独立验证要求。", 409)
    payload = candidate_commands.CandidateRecordPayload(
        issue_id=issue_id,
        expected_issue_revision=row.revision,
        capa_id=issue.capa.id,
        reason="读取当前复验候选办理范围",
        visibility=row.visibility,
    )
    origin = candidates_service._origin(s, ctx, product_id, payload)
    current = anchor_storage._current(s, ctx, product_id, row)
    if current.ref != origin:
        raise DomainError("SOURCE_STALE", "选择期间当前问题版本已变化。", 409)
    return row, issue, project, current, origin, payload


def _source_options(s, ctx, product_id, prepared):
    """Offer only actual full lines; report/domain locators remain unconverted."""
    sources = []
    for ref in prepared.sources:
        match = evidence.POSITION.fullmatch(ref.position) if ref.kind == "artifact" else None
        if match is None:
            continue
        row = source_for(s, ctx, product_id, ref.id, ref.revision)
        lines, index = row.content.splitlines(), int(match[1]) - 1
        if (
            row.tenant_id != ctx.tenant_id
            or row.content_hash != digest(row.content)
            or index >= len(lines)
            or sha256(lines[index].encode()).hexdigest() != match[2]
        ):
            raise DomainError("SOURCE_STALE", "候选来源不能核对不可变内容及完整原文行。", 409)
        sources.append(
            {
                "reference": {
                    "artifact_id": str(ref.id),
                    "expected_revision": ref.revision,
                    "line": index + 1,
                    "quote": lines[index],
                },
                "title": row.title,
                "visibility": row.visibility,
            }
        )
    return sources


def _history(s, ctx, product_id, issue_id, cursor=None):
    candidates = []
    rows, page = page_rows(
        s.scalars(
            page_query(
                select(CapaVerificationEvidence).where(
                    CapaVerificationEvidence.tenant_id == ctx.tenant_id,
                    CapaVerificationEvidence.product_id == product_id,
                    CapaVerificationEvidence.issue_id == issue_id,
                ),
                CapaVerificationEvidence.created_at,
                CapaVerificationEvidence.id,
                "candidate",
                cursor,
            )
        ),
        "candidate",
    )
    owner = candidate_commands.semantic_owner()
    for row in rows:
        if row.visibility == "private" and row.owner_id != ctx.requester_id:
            continue
        saved = candidate_storage.read_candidate(s, ctx, product_id, row.id, semantic_owner=owner)
        candidates.append(
            {
                "id": str(saved.ref.id),
                "revision": saved.ref.revision,
                "reason": row.reason,
                "received_at": row.created_at,
                "result": row.result,
                "applicable": row.applicable,
                "independently_verified": row.independently_verified,
                "observation_complete": row.observation_complete,
                "receipt_id": saved.group["receipt"]["id"],
            }
        )
    return candidates, page


def _final_scope(s, ctx, product_id, row, issue, project, current, origin, caller):
    fresh, snapshot = anchor_storage._version(
        s, ctx, product_id, row.issue_id, origin, row.project_id
    )
    if (
        snapshot != issue
        or anchor_storage._current(s, ctx, product_id, fresh) != current
        or anchor_storage._project(s, ctx, product_id, row.project_id) != project
    ):
        raise DomainError("SOURCE_STALE", "展示读取后Issue/Current/Project固定范围已改变。", 409)
    final_caller, _ = candidate_prepare._caller(s, ctx, product_id)
    if final_caller != caller:
        raise DomainError("SOURCE_STALE", "展示读取后本人或产品授权水位已改变。", 409)


def candidate_context(s, ctx, product_id, issue_id, history_cursor=None):
    with s.no_autoflush:
        require_access(
            s, ctx, product_id, lock=not getattr(s, "info", {}).get("read_snapshot", False)
        )
        caller, _ = candidate_prepare._caller(s, ctx, product_id)
        row, issue, project, current, origin, payload = _selected(s, ctx, product_id, issue_id)
        prepared = None
        sources, links, missing = [], [], []
        reads, authority = evidence.merge_reads(row.required_source_read_set), {}
        allowed, source_status, evaluation = False, "needs_recheck", "unavailable"
        try:
            prepared = candidate_prepare.prepare_candidate(
                s, ctx, product_id, payload, origin_ref=origin
            )
            basis = prepared.binding.basis
            sources = _source_options(s, ctx, product_id, prepared)
            selected = {
                "project_id": str(basis.scope.project_id),
                "issue_id": str(basis.issue_id),
                "revision": basis.issue_revision,
            }
            saved_links, link_proofs, _ = _links(s, ctx, product_id, selected)
            actions = {str(value.id): value.text for value in issue.capa.actions}
            links = [
                {
                    "ref": {"id": link["id"], "revision": link["revision"]},
                    "label": actions.get(link["action_id"], "已保存的整改回链"),
                    "detail": link["reason"],
                    "visibility": link["visibility"],
                }
                for link in saved_links
                if link["source_status"] == "current"
            ]
            missing = [value.model_dump(mode="json") for value in prepared.inspection.missing]
            missing.extend(
                {"code": code, "detail": f"已保存的整改回链需要重新核对（{code}）。"}
                for link in saved_links
                if link["source_status"] != "current"
                for code in link["reason_codes"]
            )
            candidates, history_page = _history(s, ctx, product_id, issue_id, history_cursor)
            # Display/history IO is complete. Keep each real saved Link proof,
            # source closure, authority and caller bound through the last clock.
            for saved, proof in link_proofs:
                if (
                    owners._link(
                        s,
                        ctx,
                        product_id,
                        saved.basis,
                        FixedRef(id=saved.id, revision=saved.revision),
                    )
                    != proof
                ):
                    raise DomainError("SOURCE_STALE", "展示期间整改回链实际输出证明已改变。", 409)
            # The prepared proof holds the same actual source/professional and
            # policy rows under RR. Its sealed UOW/runtime and real deadline
            # guard below also runs after all display/history IO.
            if not (getattr(s, "info", {}).get("read_snapshot") and scope_is_held(s, product_id)):
                if (
                    candidate_prepare._authority(s, ctx, product_id, basis)
                    != prepared.authority_snapshot
                    or candidate_prepare._policy(s, ctx, product_id, basis)
                    != prepared.policy_snapshot
                ):
                    raise DomainError("SOURCE_STALE", "展示期间候选来源、专业或政策已改变。", 409)
                if (
                    evidence.source_basis(s, ctx, product_id, prepared.required_source_read_set)[0]
                    != prepared.raw_source_basis
                ):
                    raise DomainError(
                        "SOURCE_STALE", "全部展示读取后完整候选来源安全闭包已改变。", 409
                    )
            _final_scope(s, ctx, product_id, row, issue, project, current, origin, caller)
            candidate_prepare.require_prepared_candidate_clock(
                s, ctx, product_id, payload, prepared, candidate_prepare._clock()
            )
            reads = [value.model_dump(mode="json") for value in prepared.required_source_read_set]
            authority = prepared.authority_snapshot
            allowed, source_status, evaluation = True, "current", "evaluated_current"
        except DomainError as error:
            if error.status == 403:
                raise
            missing.append({"code": error.code, "detail": error.message})
            sources, links = [], []
            candidates, history_page = _history(s, ctx, product_id, issue_id, history_cursor)
            _final_scope(s, ctx, product_id, row, issue, project, current, origin, caller)
        finally:
            if prepared is not None:
                candidate_prepare.invalidate_prepared_candidate(prepared)
    host = {
        "scope": {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(product_id),
            "project_id": str(row.project_id),
            "principal_id": str(ctx.requester_id),
            "issue_id": str(issue_id),
            "current_issue": {"id": str(current.ref.id), "revision": current.ref.revision},
            "capa_id": str(issue.capa.id),
            "failure_ids": sorted(value.identity for value in issue.failures),
            "visibility": row.visibility,
            "issue_label": issue.title,
            "capa_label": "已实际完成的纠正与预防措施",
            "origin_issue": {"id": origin.id, "revision": origin.revision},
        },
        "materials": {"links": links, "mappings": [], "sources": sources},
        "product_revision": caller[2],
        "required_source_read_set": reads,
        "allowed": allowed,
        "current_evaluation": evaluation,
        "source_status": source_status,
        "authority": {
            "authorized": authority.get("authorized") is True,
            "qualified": authority.get("qualified"),
            "synthetic": authority.get("synthetic") is True,
        },
        "missing": missing,
        "allowProductVisibility": row.visibility == "category",
    }
    host["accessEpoch"] = digest(jsonable_encoder(host))
    return {
        "host": host,
        "candidates": candidates,
        "history_page": history_page,
        "missing_pair_options": "尚无当前办理入口可完整核对的新测试配对；可保存缺项候选。",
        "effectiveness_enabled": False,
        "close_enabled": False,
    }


def register_routes(app: FastAPI, engine, auth_dependency):
    @app.get("/v1/categories/{category_id}/products/{product_id}/capa-candidates")
    def read_candidates(
        product_id: UUID,
        request: Request,
        issue_id: UUID,
        history_cursor: str | None = Query(default=None, max_length=256),
        ctx: Context = auth_dependency,
    ):
        if any(
            name not in {"issue_id", "history_cursor"}
            or len(request.query_params.getlist(name)) != 1
            for name in request.query_params
        ):
            raise DomainError("INVALID_REQUEST", "请选择一个明确的当前问题。", 400)
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            return jsonable_encoder(candidate_context(s, ctx, product_id, issue_id, history_cursor))
