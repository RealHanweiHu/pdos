"""Versioned human notice decisions retain the original deterministic candidate."""

from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.evidence import content_digest
from app.domain.material_exceptions import _authorize, _editable
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_notice_scans import current_input, exact_match
from app.domain.supplier_notice_watches import row, subscription
from app.domain.supplier_recovery_results import Evidence
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

DATE_KINDS = {"announced", "effective", "last_order", "last_delivery"}


class NoticeDate(Contract):
    kind: Literal["announced", "effective", "last_order", "last_delivery"]
    value: date | None = None
    basis: Text


class ReviewDraft(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    decision: Literal["accepted", "excluded", "needs_info"]
    reason: Text
    notice_type: Literal["eol", "pcn", "other"] = "other"
    notice_identifier: str = Field(default="", max_length=200)
    manufacturer: str = Field(default="", max_length=128)
    manufacturer_part_number: str = Field(default="", max_length=128)
    identity_basis: str = Field(default="", max_length=4000)
    applicable_scope: str = Field(default="", max_length=4000)
    impact: str = Field(default="", max_length=4000)
    follow_up: Text
    dates: list[NoticeDate] = Field(default_factory=list, max_length=4)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    original_text_checked: bool = False
    manufacturer_checked: bool = False
    part_scope_checked: bool = False
    latest_snapshot_checked: bool = False
    latest_snapshot_basis: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def complete(self) -> "ReviewDraft":
        if len({v.kind for v in self.dates}) != len(self.dates):
            raise ValueError("每类日期只核对一次")
        if len({(v.document_id, v.location) for v in self.evidence}) != len(self.evidence):
            raise ValueError("同一核对资料位置无需重复登记")
        if self.decision == "accepted":
            if not all(
                (
                    self.notice_identifier,
                    self.manufacturer,
                    self.manufacturer_part_number,
                    self.identity_basis,
                    self.applicable_scope,
                    self.impact,
                    self.original_text_checked,
                    self.manufacturer_checked,
                    self.part_scope_checked,
                )
            ):
                raise ValueError("接受前须核对通告标识、厂商真实性、完整料号、适用范围及实际影响")
            if {v.kind for v in self.dates} != DATE_KINDS:
                raise ValueError(
                    "请逐项核对发布、生效、最后下单和最后交付日期；未知或不适用须说明依据"
                )
        return self


class ReviewSave(ReviewDraft):
    expected_digest: Digest


def candidate(c: Connection, tenant: UUID, project: UUID, candidate_id: UUID) -> Any:
    t = tables.supplier_notice_candidates
    found = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == candidate_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if found is None:
        raise ProductWorkError("原通告线索不存在或不属于本项目")
    return found


def latest(c: Connection, candidate_id: UUID) -> Any:
    t = tables.supplier_notice_reviews
    return (
        c.execute(
            select(t).where(t.c.candidate_id == candidate_id).order_by(t.c.version.desc()).limit(1)
        )
        .mappings()
        .one_or_none()
    )


def sources(
    c: Connection, context: AuthContext, project: UUID, item: Any, evidence: list[Evidence]
) -> dict[str, Any]:
    scan = (
        c.execute(
            select(tables.supplier_notice_scans).where(
                tables.supplier_notice_scans.c.tenant_id == context.tenant.id,
                tables.supplier_notice_scans.c.project_id == project,
                tables.supplier_notice_scans.c.id == item["first_scan_id"],
            )
        )
        .mappings()
        .one()
    )
    subscription(c, context, scan["subscription_id"])
    watch = row(c, context.tenant.id, project, item["watch_id"])
    subscription(c, context, watch["subscription_id"])
    snap = (
        c.execute(
            select(tables.evidence_snapshots).where(
                tables.evidence_snapshots.c.tenant_id == context.tenant.id,
                tables.evidence_snapshots.c.id == item["snapshot_id"],
            )
        )
        .mappings()
        .one()
    )
    active = (
        c.execute(
            select(tables.research_sources.c.id).where(
                tables.research_sources.c.tenant_id == context.tenant.id,
                tables.research_sources.c.id == snap["source_id"],
                tables.research_sources.c.status == "active",
            )
        ).scalar_one_or_none()
        is not None
    )
    current = None
    with suppress(ValueError, LookupError):
        current = current_input(c, context, project, watch)
    valid = active and not (
        snap["superseded_by_id"]
        or snap["conflicts_with_id"]
        or (snap["freshness_expires_at"] and snap["freshness_expires_at"] <= datetime.now(UTC))
    )
    exact = False
    if valid:
        body = c.execute(
            select(tables.evidence_contents.c.body).where(
                tables.evidence_contents.c.tenant_id == context.tenant.id,
                tables.evidence_contents.c.content_digest == snap["content_digest"],
            )
        ).scalar_one_or_none()
        exact = (
            body is not None
            and content_digest(body) == snap["content_digest"]
            and exact_match(body, item["evidence"])
        )
    return {
        "candidate_id": str(item["id"]),
        "watch_id": str(item["watch_id"]),
        "candidate_scope_digest": item["scope_digest"],
        "original": scan["source_snapshot"],
        "original_snapshot": _plain(snap),
        "content_available": active,
        "original_valid": bool(valid and exact),
        "current": current,
        "scope_current": bool(current and current["scope_digest"] == item["scope_digest"]),
        "latest_snapshot_changed": bool(
            current and current["snapshot"]["content_digest"] != snap["content_digest"]
        ),
        "evidence": [
            {
                "document": metadata(document_row(c, context.tenant.id, project, v.document_id)),
                "location": v.location,
                "supports": v.supports,
            }
            for v in evidence
        ],
    }


def preview(
    c: Connection, context: AuthContext, project: UUID, candidate_id: UUID, command: ReviewDraft
) -> dict[str, Any]:
    _authorize(c, context, project, write=True)
    item = candidate(c, context.tenant.id, project, candidate_id)
    old = latest(c, candidate_id)
    version = old["version"] if old else 0
    if version != command.expected_version:
        raise ProductWorkError("原审阅已变化，请读取最新版本后再保存")
    source = sources(c, context, project, item, command.evidence)
    if not source["content_available"]:
        raise ProductWorkError("原来源已停用，恢复授权来源后再审阅原文")
    if command.decision == "accepted":
        if not source["original_valid"] or not source["scope_current"]:
            raise ProductWorkError("原通告或在用范围已失效/变化，请先核对来源和映射后再接受")
        current = source["current"]
        if (
            command.manufacturer.casefold() != current["manufacturer"].casefold()
            or command.manufacturer_part_number.upper() != current["part_number"].upper()
        ):
            raise ProductWorkError(
                "人审厂商/完整料号与在用映射不同，请先修订映射，不扩大原匹配范围"
            )
        if source["latest_snapshot_changed"] and not (
            command.latest_snapshot_checked and command.latest_snapshot_basis.strip()
        ):
            raise ProductWorkError("当前采集正文与原命中不同，请核对新旧快照并说明仍适用的依据")
    review = command.model_dump(mode="json", exclude={"expected_digest"})
    observed = {"candidate_id": str(candidate_id), "review": review, "source": source}
    return {**observed, "digest": digest(observed)}


class SupplierNoticeReviews:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        candidate_id: UUID,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            item = candidate(c, context.tenant.id, project, candidate_id)
            source = sources(c, context, project, item, [])
            t = tables.supplier_notice_reviews
            newest = latest(c, candidate_id)
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.candidate_id == candidate_id,
            )
            if before_version is not None:
                query = query.where(t.c.version < before_version)
            found = c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings().all()
            visible = source["content_available"]
            authors = dict(
                c.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id.in_([v["created_by_user_id"] for v in found]),
                    )
                )
                .tuples()
                .all()
            )
            history = []
            for entry in found[:20]:
                history.append(
                    {**_plain(entry), "created_by_name": authors.get(entry["created_by_user_id"])}
                    if visible
                    else {
                        "id": str(entry["id"]),
                        "version": entry["version"],
                        "decision": entry["decision"],
                        "created_at": entry["created_at"].isoformat(),
                        "content_available": False,
                    }
                )
            current_review = None
            if newest and visible:
                with suppress(LookupError, ValueError, PermissionError):
                    current_review = sources(
                        c,
                        context,
                        project,
                        item,
                        ReviewDraft.model_validate(newest["review"]).evidence,
                    )
            return {
                "candidate_id": str(candidate_id),
                "source": source,
                "evidence": item["evidence"] if visible else None,
                "version": newest["version"] if newest else 0,
                "decision": newest["decision"] if newest else "pending_review",
                "review": newest["review"] if newest and visible else None,
                "review_source_current": bool(
                    newest and current_review and digest(current_review) == newest["source_digest"]
                ),
                "can_review": visible and _editable(c, context, project),
                "history": history,
                "next_before_version": found[19]["version"] if len(found) > 20 else None,
            }

    def text(
        self,
        context: AuthContext,
        project: UUID,
        candidate_id: UUID,
        snapshot_id: UUID,
        offset: int = 0,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            item = candidate(c, context.tenant.id, project, candidate_id)
            source = sources(c, context, project, item, [])
            snapshots = [source["original_snapshot"]]
            if source["current"]:
                snapshots.append(source["current"]["snapshot"])
            snap = next((v for v in snapshots if v["id"] == str(snapshot_id)), None)
            if not source["content_available"] or snap is None:
                raise ProductWorkError("原来源或所选快照不可读取，请重新读取审阅资料")
            body = c.execute(
                select(tables.evidence_contents.c.body).where(
                    tables.evidence_contents.c.tenant_id == context.tenant.id,
                    tables.evidence_contents.c.content_digest == snap["content_digest"],
                )
            ).scalar_one_or_none()
            if body is None or content_digest(body) != snap["content_digest"]:
                raise ProductWorkError("原文缺失或摘要不一致")
            if offset < 0 or offset > len(body):
                raise ProductWorkError("请从原文分页位置继续读取")
            end = min(offset + 16000, len(body))
            return {
                "snapshot_id": str(snapshot_id),
                "offset": offset,
                "end": end,
                "total": len(body),
                "body": body[offset:end],
                "next_offset": end if end < len(body) else None,
            }

    def preview(
        self, context: AuthContext, project: UUID, candidate_id: UUID, command: ReviewDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, candidate_id, command)

    def save(
        self, context: AuthContext, project: UUID, candidate_id: UUID, command: ReviewSave
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "candidate": str(candidate_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            _authorize(c, context, project, write=True)
            item = candidate(c, context.tenant.id, project, candidate_id)
            # Recheck source scope before returning a previous request's human text.
            current = sources(c, context, project, item, [])
            if not current["content_available"]:
                raise ProductWorkError("原来源已停用，原文及人审内容暂不可读取")
            t = tables.supplier_notice_reviews
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于另一审阅，请保留原回执")
                return _plain(prior)
            observed = preview(c, context, project, candidate_id, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("原通告、映射、资料或审阅版本已变化，请重新预览")
            values = dict(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=project,
                candidate_id=candidate_id,
                version=command.expected_version + 1,
                decision=command.decision,
                review=observed["review"],
                snapshot=observed["source"],
                source_digest=digest(observed["source"]),
                request_id=command.request_id,
                request_digest=signature,
                created_by_user_id=context.user.id,
                created_at=datetime.now(UTC),
            )
            c.execute(t.insert().values(**values))
            EventAuditWriter(
                c, tenant_id=context.tenant.id, project_id=project, actor_user_id=context.user.id
            ).record(
                EventDraft(
                    event_id=f"supplier-notice-review:{values['id']}",
                    event_type="SUPPLIER_NOTICE_REVIEWED",
                    source="supplier_service",
                    entity_id=candidate_id,
                    payload={"version": values["version"], "decision": command.decision},
                ),
                AuditDraft(action="supplier.notice.reviewed", after_snapshot=_plain(values)),
            )
            return _plain(values)
