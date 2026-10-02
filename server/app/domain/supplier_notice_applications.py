"""Explicit human application of accepted notices into original Issue/ECR services."""

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.change_governance import ChangeGovernanceService
from app.domain.issues import IssueDraft, IssueService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.material_exceptions import _authorize
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_notice_reviews import ReviewDraft, candidate, latest, sources
from app.domain.supplier_recovery_findings import review_context
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TargetKind = Literal["issue", "ecr"]
TARGET_KINDS: tuple[TargetKind, ...] = ("issue", "ecr")


class ApplicationDraft(Contract):
    request_id: UUID
    review_id: UUID
    target_kind: TargetKind
    mode: Literal["create", "link"]
    reason: Text
    target_id: UUID | None = None
    title: str = Field(default="", max_length=512)
    code: str = Field(default="", max_length=64)
    owner_user_id: UUID | None = None
    verifier_user_id: UUID | None = None
    stage_id: UUID | None = None
    target_date: date | None = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    closure_criteria: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def complete(self) -> "ApplicationDraft":
        if self.mode == "link":
            if self.target_id is None:
                raise ValueError("关联已有办理须明确本项目原记录")
            if any(
                (
                    self.title,
                    self.code,
                    self.owner_user_id,
                    self.verifier_user_id,
                    self.stage_id,
                    self.target_date,
                    self.closure_criteria,
                )
            ):
                raise ValueError("关联已有记录不同时修改原责任、日期或内容")
        else:
            if self.target_id is not None or not self.title:
                raise ValueError("新建须填写标题且不指定已有记录")
            if self.target_kind == "ecr":
                if not self.code or any(
                    (
                        self.owner_user_id,
                        self.verifier_user_id,
                        self.stage_id,
                        self.target_date,
                        self.closure_criteria,
                    )
                ):
                    raise ValueError("新建ECR须填写编号；责任及执行要求沿原变更流程办理")
            elif self.code or not all(
                (self.owner_user_id, self.verifier_user_id, self.target_date, self.closure_criteria)
            ):
                raise ValueError("新建问题须核对负责人、验证人、目标日期和关闭判据")
        return self


class ApplicationSave(ApplicationDraft):
    expected_digest: Digest


def authorize(
    c: Connection, context: AuthContext, project: UUID, kind: TargetKind, *, write: bool = False
) -> None:
    _authorize(c, context, project, write=write)
    action = (
        (Action.CHANGE_EDIT if write else Action.CHANGE_VIEW)
        if kind == "ecr"
        else (Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW)
    )
    KnowledgeCorrectionService._authorize(c, context.tenant.id, context.user.id, project, action)


def target(
    c: Connection, tenant: UUID, project: UUID, kind: TargetKind, identity: UUID
) -> dict[str, Any]:
    t = tables.issues if kind == "issue" else tables.engineering_change_requests
    found = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    if found is None:
        raise ProductWorkError("原办理不存在或不属于本项目")
    return _plain(found)


def notice_key(review: Any) -> str:
    value, source = review["review"], review["snapshot"]
    return digest(
        {
            "project": str(review["project_id"]),
            "bom_item": source["current"]["watch_source"]["bom_item"]["id"],
            "manufacturer": value["manufacturer"].casefold(),
            "part": value["manufacturer_part_number"].upper(),
            "type": value["notice_type"],
            "notice": value["notice_identifier"].casefold(),
        }
    )


def canonical(c: Connection, tenant: UUID, project: UUID, key: str, kind: TargetKind) -> Any:
    t = tables.supplier_notice_applications
    return (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.notice_key == key,
                t.c.target_kind == kind,
                t.c.linked_from_id.is_(None),
            )
        )
        .mappings()
        .one_or_none()
    )


def view(c: Connection, context: AuthContext, project: UUID, entry: Any) -> dict[str, Any]:
    authorize(c, context, project, entry["target_kind"])
    actual = target(
        c, context.tenant.id, project, entry["target_kind"], entry["issue_id"] or entry["ecr_id"]
    )
    item = candidate(c, context.tenant.id, project, entry["candidate_id"])
    # Original product/source read rights still apply after a business link exists.
    source = sources(c, context, project, item, [])
    review = latest(c, item["id"])
    current = None
    try:
        current = sources(
            c,
            context,
            project,
            item,
            ReviewDraft.model_validate(entry["snapshot"]["review"]["review"]).evidence,
        )
    except (ValueError, LookupError, PermissionError):
        current = None
    visible = source["content_available"]
    return {
        "id": str(entry["id"]),
        "candidate_id": str(entry["candidate_id"]),
        "review_id": str(entry["review_id"]),
        "target_kind": entry["target_kind"],
        "mode": entry["command"]["mode"],
        "target": actual,
        "created_at": entry["created_at"].isoformat(),
        "created_by_user_id": str(entry["created_by_user_id"]),
        "review_version": entry["snapshot"]["review"]["version"],
        "notice_identifier": entry["snapshot"]["review"]["review"]["notice_identifier"]
        if visible
        else None,
        "reason": entry["command"]["reason"] if visible else None,
        "content_available": visible,
        "review_current": bool(review and review["id"] == entry["review_id"]),
        "source_current": bool(
            current and digest(current) == entry["snapshot"]["review"]["source_digest"]
        ),
        "linked_from_id": str(entry["linked_from_id"]) if entry["linked_from_id"] else None,
    }


def preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    candidate_id: UUID,
    command: ApplicationDraft,
) -> dict[str, Any]:
    authorize(c, context, project, command.target_kind, write=True)
    item = candidate(c, context.tenant.id, project, candidate_id)
    review = latest(c, candidate_id)
    if review is None or review["id"] != command.review_id or review["decision"] != "accepted":
        raise ProductWorkError("请选择最新已接受的人审版本，再独立应用")
    source = sources(
        c, context, project, item, ReviewDraft.model_validate(review["review"]).evidence
    )
    if (
        not source["content_available"]
        or not source["original_valid"]
        or not source["scope_current"]
        or digest(source) != review["source_digest"]
    ):
        raise ProductWorkError("已接受的通告、映射或核对资料已变化，请重新审阅")
    t = tables.supplier_notice_applications
    if c.execute(
        select(t.c.id).where(
            t.c.candidate_id == candidate_id, t.c.target_kind == command.target_kind
        )
    ).scalar_one_or_none():
        raise ProductWorkError("此候选已应用到该类办理，请回查原回执，不重复建单")
    key = notice_key(review)
    prior = canonical(c, context.tenant.id, project, key, command.target_kind)
    existing = None
    if command.mode == "link":
        assert command.target_id is not None
        existing = target(c, context.tenant.id, project, command.target_kind, command.target_id)
        allowed = (
            {"request", "impact_analysis"}
            if command.target_kind == "ecr"
            else {"open", "analysis", "action", "verification"}
        )
        if command.target_kind == "issue" and existing.get("withdrawn_at") is not None:
            raise ProductWorkError("原问题已撤回，不能新增供方通告关联")
        if existing["status"] not in allowed:
            raise ProductWorkError("原办理已结束或进入批准，请回原记录核对；不改写已有结论")
    if prior and (
        command.mode != "link"
        or str(command.target_id) != str(prior["issue_id"] or prior["ecr_id"])
    ):
        raise ProductWorkError("此在用件的同标识通告已有办理，请明确关联原记录，避免重复建单")
    people = review_context(c, context.tenant.id, project)
    selection: dict[str, Any] = {}
    if command.mode == "create" and command.target_kind == "issue":
        member_map = {v["id"]: v for v in people["members"]}
        stage_map = {v["id"]: v for v in people["stages"]}
        if (
            str(command.owner_user_id) not in member_map
            or str(command.verifier_user_id) not in member_map
        ):
            raise ProductWorkError("负责人和验证人须为当前本项目内部成员")
        if command.owner_user_id == command.verifier_user_id:
            raise ProductWorkError("负责人和独立验证人须为不同成员")
        if command.stage_id and str(command.stage_id) not in stage_map:
            raise ProductWorkError("阶段不属于当前项目")
        selection = {
            "owner": member_map[str(command.owner_user_id)],
            "verifier": member_map[str(command.verifier_user_id)],
            "stage": stage_map.get(str(command.stage_id)),
        }
    observed = {
        "candidate_id": str(candidate_id),
        "review": _plain(review),
        "source": source,
        "command": command.model_dump(mode="json", exclude={"expected_digest"}),
        "notice_key": key,
        "existing_target": existing,
        "selection": selection,
        "linked_from_id": str(prior["id"]) if prior else None,
    }
    return {**observed, "digest": digest(observed)}


class SupplierNoticeApplications:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, context: AuthContext, project: UUID, candidate_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project)
            item = candidate(c, context.tenant.id, project, candidate_id)
            sources(c, context, project, item, [])
            review = latest(c, candidate_id)
            eligible: list[str] = []
            for kind in TARGET_KINDS:
                try:
                    authorize(c, context, project, kind, write=True)
                    eligible.append(kind)
                except PermissionError:
                    continue
            t = tables.supplier_notice_applications
            entries = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.candidate_id == candidate_id,
                    )
                )
                .mappings()
                .all()
            )
            items, duplicates = [], []
            for entry in entries:
                try:
                    items.append(view(c, context, project, entry))
                except PermissionError:
                    continue
            if review and review["decision"] == "accepted":
                for kind in TARGET_KINDS:
                    prior = canonical(c, context.tenant.id, project, notice_key(review), kind)
                    if prior:
                        try:
                            duplicates.append(view(c, context, project, prior))
                        except (PermissionError, LookupError, ValueError):
                            continue
            return {
                "items": items,
                "duplicates": duplicates,
                "allowed_kinds": eligible,
                "review_id": str(review["id"]) if review else None,
                "decision": review["decision"] if review else "pending_review",
                **review_context(c, context.tenant.id, project),
            }

    def linked(
        self,
        context: AuthContext,
        project: UUID,
        kind: TargetKind,
        target_id: UUID,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        from sqlalchemy import tuple_

        with self.engine.connect() as c:
            authorize(c, context, project, kind)
            target(c, context.tenant.id, project, kind, target_id)
            t = tables.supplier_notice_applications
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.target_kind == kind,
                (t.c.issue_id if kind == "issue" else t.c.ecr_id) == target_id,
            )
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise ProductWorkError("请从原通告关联继续翻页")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            found = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for entry in found[:20]:
                try:
                    items.append(view(c, context, project, entry))
                except (LookupError, ValueError, PermissionError):
                    continue
            return {
                "items": items,
                "next_before_id": str(found[19]["id"]) if len(found) > 20 else None,
            }

    def preview(
        self, context: AuthContext, project: UUID, candidate_id: UUID, command: ApplicationDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, candidate_id, command)

    def apply(
        self, context: AuthContext, project: UUID, candidate_id: UUID, command: ApplicationSave
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
            authorize(c, context, project, command.target_kind, write=True)
            t = tables.supplier_notice_applications
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
                    raise ProductWorkError("原请求已用于另一应用，请保留原回执")
                return view(c, context, project, prior)
            observed = preview(c, context, project, candidate_id, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("原审阅、来源、成员或办理记录已变化，请重新预览")
            review = observed["review"]["review"]
            description = (
                f"厂商通告：{review['notice_identifier']}\n"
                f"厂商/完整料号：{review['manufacturer']} / {review['manufacturer_part_number']}\n"
                f"适用范围：{review['applicable_scope']}\n影响：{review['impact']}\n"
                f"后续要求：{review['follow_up']}\n办理依据：{command.reason}\n"
                f"通告候选：{candidate_id}；已接受审阅：{command.review_id}"
            )
            issue_id = ecr_id = None
            if command.mode == "link":
                if command.target_kind == "issue":
                    issue_id = command.target_id
                else:
                    ecr_id = command.target_id
            elif command.target_kind == "issue":
                created = IssueService(self.engine).create(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    project_id=project,
                    connection=c,
                    draft=IssueDraft(
                        stage_id=command.stage_id,
                        owner_user_id=command.owner_user_id,
                        verifier_user_id=command.verifier_user_id,
                        sample_id=None,
                        title=command.title,
                        description=description,
                        issue_type="supplier",
                        severity=command.severity,
                        root_cause=None,
                        resolution=None,
                        closure_criteria=command.closure_criteria,
                        target_date=command.target_date,
                    ),
                )
                issue_id = created.id
            else:
                ecr = ChangeGovernanceService(self.engine).create_ecr_in_transaction(
                    c,
                    tenant_id=context.tenant.id,
                    project_id=project,
                    actor_user_id=context.user.id,
                    code=command.code,
                    title=command.title,
                    reason=description,
                )
                ecr_id = ecr["id"]
            values = dict(
                id=uuid4(),
                tenant_id=context.tenant.id,
                project_id=project,
                candidate_id=candidate_id,
                review_id=command.review_id,
                notice_key=observed["notice_key"],
                target_kind=command.target_kind,
                issue_id=issue_id,
                ecr_id=ecr_id,
                linked_from_id=UUID(observed["linked_from_id"])
                if observed["linked_from_id"]
                else None,
                command=observed["command"],
                snapshot=observed,
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
                    event_id=f"supplier-notice-application:{values['id']}",
                    event_type="SUPPLIER_NOTICE_APPLIED",
                    source="supplier_service",
                    entity_id=candidate_id,
                    payload={
                        "application_id": str(values["id"]),
                        "target_kind": command.target_kind,
                        "target_id": str(issue_id or ecr_id),
                    },
                ),
                AuditDraft(action="supplier.notice.applied", after_snapshot=_plain(values)),
            )
            return view(c, context, project, values)
