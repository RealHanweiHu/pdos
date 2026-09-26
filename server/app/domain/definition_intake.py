"""Reviewable definition-to-requirement proposals and atomic, idempotent application."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.contracts.common_objects import Contract, Digest, Key, Text
from app.contracts.object_operations import CommandPrecondition
from app.db.schema import tables
from app.domain.opportunity_requirements import requirement_snapshot
from app.domain.product_definitions import _release, _row, definition_digest
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _precondition,
    _record,
    _role,
    _space,
    digest,
)
from app.domain.requirements import RequirementService, _snapshot
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RequirementCandidate(Contract):
    key: Key
    item_keys: tuple[Key, ...] = Field(min_length=1, max_length=100)
    mode: Literal["new", "reuse"]
    requirement_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"\S")
    title: str | None = Field(default=None, min_length=1, max_length=512, pattern=r"\S")
    parent_requirement_id: UUID | None = None
    acknowledge_differences: bool = False
    rationale: Text

    @model_validator(mode="after")
    def target_shape(self) -> Self:
        if (self.mode == "reuse") != (self.requirement_id is not None):
            raise ValueError("复用须选择实际需求，新建不能指定既有需求")
        if self.mode == "reuse" and (
            self.code is not None
            or self.title is not None
            or self.parent_requirement_id is not None
        ):
            raise ValueError("复用仅建立关联，不修改既有需求的编号、标题或父级")
        if len(set(self.item_keys)) != len(self.item_keys):
            raise ValueError("候选内的规格条目不能重复")
        return self


class PackageDraft(Input):
    request_id: UUID
    definition_id: UUID
    candidates: tuple[RequirementCandidate, ...] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def unique_assignments(self) -> Self:
        if len({row.key for row in self.candidates}) != len(self.candidates):
            raise ValueError("候选标识不能重复")
        keys = [key for row in self.candidates for key in row.item_keys]
        if len(set(keys)) != len(keys):
            raise ValueError("同一规格条目在一个包中只能分配一次，可将多项归入同一需求")
        return self


class PackageAction(CommandPrecondition):
    action: Literal["accept", "apply", "reject"]
    reviewed_proposal_digest: Digest
    reason: Text


def _requirements_from_items(
    definition: Any, candidate: RequirementCandidate, items: list[Any]
) -> dict[str, Any]:
    criteria, descriptions = (
        [],
        [
            f"来源：{definition['title']} · 修订 {definition['revision_number']} · "
            f"{definition['id']}"
        ],
    )
    for item in items:
        descriptions.extend(
            (
                f"\n[{item['item_key']}] {item['title']}",
                f"目标：{item['target_text'] or ''} "
                f"{item['target_value'] if item['target_value'] is not None else ''} "
                f"{item['unit'] or ''}",
                f"容差：{item['tolerance'] or '待定'}；"
                f"工况：{'；'.join(item['conditions']) or '待定'}",
                f"方法：{item['verification_method']}；阶段：{item['verification_stage']}",
                f"通过判据：{item['acceptance_criterion']}",
            )
        )
        criterion = f"[{item['item_key']}] {item['acceptance_criterion']}"
        criteria.append(
            criterion
            if len(criterion) <= 512
            else (
                f"[{item['item_key']}] 按所引用发布定义的完整通过判据验收（详见需求描述和定义快照）"
            )
        )
    return {
        "code": candidate.code or f"PD-{str(definition['id'])[:8]}-{digest(candidate.key)[:12]}",
        "title": candidate.title or items[0]["title"][:512],
        "description": "\n".join(descriptions),
        "acceptance_criteria": criteria,
        "priority": "high" if any(item["priority"] == "must" for item in items) else "medium",
        "tier": "product",
        "parent_requirement_id": str(candidate.parent_requirement_id)
        if candidate.parent_requirement_id
        else None,
    }


def prior_mappings(
    connection: Connection, context: AuthContext, definition: Any, item_keys: tuple[str, ...]
) -> list[dict[str, Any]]:
    link, source = tables.definition_requirement_links, tables.product_definitions
    ranked = (
        select(
            link.c.item_key,
            link.c.requirement_id,
            link.c.definition_id,
            link.c.specification_snapshot,
            link.c.requirement_snapshot,
            source.c.title.label("definition_title"),
            source.c.revision_number,
            func.row_number()
            .over(partition_by=link.c.item_key, order_by=source.c.revision_number.desc())
            .label("position"),
        )
        .select_from(link)
        .join(
            source, (source.c.tenant_id == link.c.tenant_id) & (source.c.id == link.c.definition_id)
        )
        .where(
            link.c.tenant_id == context.tenant.id,
            source.c.series_id == definition["series_id"],
            source.c.revision_number < definition["revision_number"],
            link.c.item_key.in_(item_keys),
        )
        .subquery()
    )
    rows = list(
        connection.execute(
            select(ranked).where(ranked.c.position == 1).order_by(ranked.c.item_key)
        ).mappings()
    )
    requirements = {
        row["id"]: row
        for row in connection.execute(
            select(tables.requirements).where(
                tables.requirements.c.tenant_id == context.tenant.id,
                tables.requirements.c.id.in_([row["requirement_id"] for row in rows]),
            )
        ).mappings()
    }
    current_items = {item["item_key"]: item for item in definition["content"]["items"]}
    return [
        {
            "item_key": row["item_key"],
            "definition_id": str(row["definition_id"]),
            "definition_title": row["definition_title"],
            "definition_revision": row["revision_number"],
            "requirement": requirement_snapshot(requirements[row["requirement_id"]]),
            "requirement_has_changed": digest(
                requirement_snapshot(requirements[row["requirement_id"]])
            )
            != digest(row["requirement_snapshot"]),
            "previous_specification": row["specification_snapshot"],
            "current_specification": current_items[row["item_key"]],
            "specification_changes": [
                key
                for key, value in current_items[row["item_key"]].items()
                if value != row["specification_snapshot"].get(key)
            ],
        }
        for row in rows
    ]


def _inspect(
    connection: Connection, context: AuthContext, definition: Any, candidate: RequirementCandidate
) -> dict[str, Any]:
    all_items = {item["item_key"]: item for item in definition["content"]["items"]}
    if any(
        key not in all_items or all_items[key]["state"] != "confirmed"
        for key in candidate.item_keys
    ):
        raise ProductWorkError("需求候选只能引用此发布定义中已确认的规格条目")
    items = [all_items[key] for key in candidate.item_keys]
    proposed = _requirements_from_items(definition, candidate, items)
    links = list(
        connection.execute(
            select(tables.definition_requirement_links).where(
                tables.definition_requirement_links.c.tenant_id == context.tenant.id,
                tables.definition_requirement_links.c.definition_id == definition["id"],
                tables.definition_requirement_links.c.item_key.in_(candidate.item_keys),
            )
        ).mappings()
    )
    blockers = []
    target_id = candidate.requirement_id
    mode: str = candidate.mode
    if links:
        target_ids = {link["requirement_id"] for link in links}
        if (
            len(links) == len(items)
            and len(target_ids) == 1
            and (target_id is None or target_id in target_ids)
        ):
            target_id, mode = next(iter(target_ids)), "already_linked"
        else:
            blockers.append("部分规格已关联其他需求，请保留既有映射并重新分组")
    target = None
    if target_id:
        target = (
            connection.execute(
                select(tables.requirements).where(
                    tables.requirements.c.tenant_id == context.tenant.id,
                    tables.requirements.c.id == target_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            raise ProductWorkAccessError("复用需求不存在或不可访问")
        if target["status"] == "rejected":
            blockers.append("所选需求已拒绝，须先按需求流程处置")
    elif connection.execute(
        select(tables.requirements.c.id).where(
            tables.requirements.c.tenant_id == context.tenant.id,
            tables.requirements.c.code == proposed["code"],
        )
    ).first():
        blockers.append("新建编号已被占用，请更换编号或明确选择复用需求")
    differences = []
    if target:
        for key in ("title", "description", "acceptance_criteria"):
            if _plain(target[key]) != proposed[key]:
                differences.append(key)
        if differences and mode == "reuse" and not candidate.acknowledge_differences:
            blockers.append("复用需求与建议内容有差异，须查看并明确确认差异")
    parent = None
    if candidate.parent_requirement_id:
        parent = (
            connection.execute(
                select(tables.requirements).where(
                    tables.requirements.c.tenant_id == context.tenant.id,
                    tables.requirements.c.id == candidate.parent_requirement_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            raise ProductWorkAccessError("父需求不存在或不可访问")
        if parent["status"] == "rejected":
            blockers.append("父需求已拒绝，不能据此创建子需求")
    if len(proposed["description"]) > 20000:
        blockers.append("合并后的需求描述超过20000字，请拆分候选分组")
    return {
        "prior_mappings": prior_mappings(connection, context, definition, candidate.item_keys),
        "input": candidate.model_dump(mode="json"),
        "key": candidate.key,
        "mode": mode,
        "proposed": proposed,
        "specifications": items,
        "target": requirement_snapshot(target) if target else None,
        "target_digest": digest(requirement_snapshot(target)) if target else None,
        "parent_digest": digest(requirement_snapshot(parent)) if parent else None,
        "differences": differences,
        "blockers": blockers,
    }


def _package(connection: Connection, context: AuthContext, row: Any) -> dict[str, Any]:
    from app.domain.requirement_package_succession import links

    definition = _row(connection, context, row["market_space_id"], row["definition_id"])
    latest = _release(connection, context, definition["product_id"])
    return {
        **_record(row),
        "succession": links(connection, context.tenant.id, row["market_space_id"], row["id"]),
        "can_apply": is_allowed(context.user.role, Action.REQUIREMENT_CREATE)
        and is_allowed(context.user.role, Action.REQUIREMENT_EDIT),
        "definition_title": definition["title"],
        "definition_revision": definition["revision_number"],
        "source_is_current": latest is not None
        and latest["id"] == row["release_id"]
        and latest["action"] == "publish",
    }


class DefinitionIntakeService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.definition_requirement_packages
            rows = connection.execute(
                select(table)
                .where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    _line_filter(table, context),
                )
                .order_by(table.c.updated_at.desc())
                .limit(100)
            ).mappings()
            return {"items": [_package(connection, context, row) for row in rows]}

    def detail(self, context: AuthContext, space_id: UUID, package_id: UUID) -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.definition_requirement_packages
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == package_id,
                        _line_filter(table, context),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("需求候选包不存在或不可访问")
            return _package(connection, context, row)

    def reuse_options(
        self, context: AuthContext, space_id: UUID, definition_id: UUID
    ) -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            definition = _row(connection, context, space_id, definition_id)
            return {
                "items": prior_mappings(
                    connection,
                    context,
                    definition,
                    tuple(item["item_key"] for item in definition["content"]["items"]),
                )
            }

    def requirement_sources(self, context: AuthContext, requirement_id: UUID) -> dict[str, Any]:
        _role(context, Action.REQUIREMENT_VIEW)
        _role(context, Action.PRODUCT_WORK_VIEW)
        with self.engine.connect() as connection:
            current = (
                connection.execute(
                    select(tables.requirements).where(
                        tables.requirements.c.tenant_id == context.tenant.id,
                        tables.requirements.c.id == requirement_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if current is None:
                raise ProductWorkAccessError("需求不存在或不可访问")
            link, definition, space = (
                tables.definition_requirement_links,
                tables.product_definitions,
                tables.market_spaces,
            )
            statement = (
                select(
                    link,
                    definition.c.title.label("definition_title"),
                    definition.c.revision_number.label("definition_revision"),
                    definition.c.product_id,
                    space.c.title.label("space_title"),
                )
                .select_from(link)
                .join(
                    definition,
                    (definition.c.tenant_id == link.c.tenant_id)
                    & (definition.c.id == link.c.definition_id),
                )
                .join(
                    space,
                    (space.c.tenant_id == link.c.tenant_id)
                    & (space.c.id == link.c.market_space_id),
                )
                .where(
                    link.c.tenant_id == context.tenant.id,
                    link.c.requirement_id == requirement_id,
                    _line_filter(definition, context),
                )
            )
            if context.user.role not in {Role.OWNER, Role.ADMIN}:
                statement = statement.where(
                    space.c.id.in_(
                        select(tables.market_space_members.c.market_space_id).where(
                            tables.market_space_members.c.tenant_id == context.tenant.id,
                            tables.market_space_members.c.user_id == context.user.id,
                        )
                    )
                )
            rows = list(
                connection.execute(
                    statement.order_by(link.c.created_at.desc(), link.c.id).limit(201)
                ).mappings()
            )
            releases = {
                product_id: _release(connection, context, product_id)
                for product_id in {row["product_id"] for row in rows[:200]}
            }
            fingerprint = digest(requirement_snapshot(current))
            return {
                "items": [
                    {
                        **_plain(row),
                        "source_is_current": releases[row["product_id"]] is not None
                        and releases[row["product_id"]]["action"] == "publish"
                        and releases[row["product_id"]]["definition_id"] == row["definition_id"],
                        "requirement_has_changed": digest(row["requirement_snapshot"])
                        != fingerprint,
                    }
                    for row in rows[:200]
                ],
                "has_more": len(rows) > 200,
            }

    def create(self, context: AuthContext, space_id: UUID, draft: PackageDraft) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        _role(context, Action.REQUIREMENT_VIEW)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            definition = _row(connection, context, space_id, draft.definition_id, write=True)
            table = tables.definition_requirement_packages
            fingerprint = digest(draft.model_dump(mode="json"))
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.owner_user_id == context.user.id,
                        table.c.request_id == draft.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一请求编号不能用于不同候选包")
                return _package(connection, context, existing)
            release = _release(connection, context, definition["product_id"])
            if (
                definition["state"] != "published"
                or release is None
                or release["definition_id"] != definition["id"]
                or release["action"] != "publish"
            ):
                raise ProductWorkError("只能从当前生效的已发布定义生成需求候选")
            included = {key for row in draft.candidates for key in row.item_keys}
            eligible = {
                item["item_key"]
                for item in definition["content"]["items"]
                if item["state"] == "confirmed"
            }
            if included != eligible:
                raise ProductWorkError("候选包须覆盖全部已确认规格，可将多条规格归入一个需求")
            candidates = [
                _inspect(connection, context, definition, candidate)
                for candidate in draft.candidates
            ]
            codes = [item["proposed"]["code"] for item in candidates if item["mode"] == "new"]
            if len(set(codes)) != len(codes):
                raise ProductWorkError("包内新建需求编号不能重复")
            proposal = {
                "definition_digest": definition_digest(definition),
                "candidates": candidates,
                "excluded_items": [
                    {
                        "item_key": item["item_key"],
                        "state": item["state"],
                        "reason": item["disposition_reason"] or "此条目尚未确认，未进入需求候选",
                    }
                    for item in definition["content"]["items"]
                    if item["item_key"] not in included
                ],
                "creates_status": "draft",
                "policy_version": "definition-requirement-intake-v2",
            }
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        product_line_id=definition["product_line_id"],
                        definition_id=definition["id"],
                        release_id=release["id"],
                        owner_user_id=context.user.id,
                        proposal=proposal,
                        proposal_digest=digest(proposal),
                        request_id=draft.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, space_id, "definition_requirement_package", "created", row)
            return _package(connection, context, row)

    def change(
        self, context: AuthContext, space_id: UUID, package_id: UUID, command: PackageAction
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
        _role(context, Action.REQUIREMENT_CREATE)
        _role(context, Action.REQUIREMENT_EDIT)
        with self.engine.begin() as connection:
            _space(connection, context, space_id, access="contributor", lock=True)
            table = tables.definition_requirement_packages
            row = (
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == package_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("候选包不存在或不可访问")
            _line(
                connection,
                context,
                space_id,
                row["product_line_id"],
                access="contributor",
                writable=True,
            )
            if not _precondition(connection, context, row, command):
                return _package(connection, context, row)
            if command.reviewed_proposal_digest != row["proposal_digest"]:
                raise ProductWorkError("请确认当前候选包内容摘要")
            if (
                row["state"] in {"applied", "rejected"}
                or (command.action == "apply" and row["state"] != "accepted")
                or (command.action == "accept" and row["state"] != "pending_review")
            ):
                raise ProductWorkError("候选包当前状态不能执行此动作")
            now = datetime.now(UTC)
            values: dict[str, Any]
            if command.action == "reject":
                values = {"state": "rejected"}
            else:
                definition = _row(connection, context, space_id, row["definition_id"], write=True)
                release = _release(connection, context, definition["product_id"])
                if (
                    release is None
                    or release["id"] != row["release_id"]
                    or release["action"] != "publish"
                    or definition_digest(definition) != row["proposal"]["definition_digest"]
                ):
                    raise ProductWorkError("定义已撤回或被新版本替代，请重新生成候选包")
                # Lock all existing targets in a stable order before comparing reviewed snapshots.
                ids = {
                    UUID(item["target"]["id"])
                    for item in row["proposal"]["candidates"]
                    if item["target"]
                }
                ids.update(
                    UUID(item["input"]["parent_requirement_id"])
                    for item in row["proposal"]["candidates"]
                    if item["input"]["parent_requirement_id"]
                )
                if ids:
                    list(
                        connection.execute(
                            select(tables.requirements.c.id)
                            .where(
                                tables.requirements.c.tenant_id == context.tenant.id,
                                tables.requirements.c.id.in_(ids),
                            )
                            .order_by(tables.requirements.c.id)
                            .with_for_update()
                        )
                    )
                for candidate in row["proposal"]["candidates"]:
                    current = _inspect(
                        connection,
                        context,
                        definition,
                        RequirementCandidate.model_validate(candidate["input"]),
                    )
                    if "prior_mappings" not in candidate:
                        current.pop("prior_mappings", None)
                    if current["blockers"] or digest(current) != digest(candidate):
                        raise ProductWorkError(
                            "需求内容、编号或映射已变化或仍有冲突，请重新生成并审阅候选包"
                        )
                if command.action == "accept":
                    values = {
                        "state": "accepted",
                        "accepted_by_user_id": context.user.id,
                        "accepted_at": now,
                    }
                else:
                    result = []
                    for candidate in row["proposal"]["candidates"]:
                        target = candidate["target"]
                        if target is None:
                            proposed = candidate["proposed"]
                            requirement_id = uuid4()
                            target = (
                                connection.execute(
                                    tables.requirements.insert()
                                    .values(
                                        **{
                                            key: proposed[key]
                                            for key in (
                                                "code",
                                                "title",
                                                "description",
                                                "acceptance_criteria",
                                                "priority",
                                                "tier",
                                            )
                                        },
                                        parent_requirement_id=UUID(
                                            proposed["parent_requirement_id"]
                                        )
                                        if proposed["parent_requirement_id"]
                                        else None,
                                        id=requirement_id,
                                        tenant_id=context.tenant.id,
                                        created_by_user_id=context.user.id,
                                        source="product_definition",
                                        status="draft",
                                        created_at=now,
                                        updated_at=now,
                                    )
                                    .returning(tables.requirements)
                                )
                                .mappings()
                                .one()
                            )
                            record = RequirementService(self.engine)._get_record(
                                connection,
                                tenant_id=context.tenant.id,
                                requirement_id=requirement_id,
                            )
                            EventAuditWriter(
                                connection,
                                tenant_id=context.tenant.id,
                                actor_user_id=context.user.id,
                            ).record(
                                EventDraft(
                                    event_id=f"requirement:{requirement_id}:created",
                                    event_type="REQUIREMENT_CREATED",
                                    source="requirement_service",
                                    entity_id=requirement_id,
                                    payload={
                                        "requirement_code": record.code,
                                        "status": record.status,
                                        "priority": record.priority,
                                    },
                                    occurred_at=now,
                                ),
                                AuditDraft(
                                    action="requirement.create",
                                    after_snapshot=_snapshot(record),
                                    context={
                                        "definition_id": str(definition["id"]),
                                        "package_id": str(row["id"]),
                                    },
                                ),
                            )
                            target = requirement_snapshot(target)
                        requirement_id = UUID(target["id"])
                        if candidate["mode"] != "already_linked":
                            for specification in candidate["specifications"]:
                                connection.execute(
                                    tables.definition_requirement_links.insert().values(
                                        id=uuid4(),
                                        tenant_id=context.tenant.id,
                                        market_space_id=space_id,
                                        definition_id=definition["id"],
                                        package_id=row["id"],
                                        item_key=specification["item_key"],
                                        candidate_key=candidate["key"],
                                        requirement_id=requirement_id,
                                        specification_snapshot=specification,
                                        requirement_snapshot=target,
                                        rationale=candidate["input"]["rationale"],
                                    )
                                )
                        result.append(
                            {
                                "candidate_key": candidate["key"],
                                "requirement_id": str(requirement_id),
                                "requirement_code": target["code"],
                                "status_at_application": target["status"],
                                "disposition": "created"
                                if candidate["target"] is None
                                else "reused",
                                "item_keys": candidate["input"]["item_keys"],
                            }
                        )
                    values = {
                        "state": "applied",
                        "applied_at": now,
                        "result": {"requirements": result},
                    }
            updated = (
                connection.execute(
                    table.update()
                    .where(table.c.tenant_id == context.tenant.id, table.c.id == row["id"])
                    .values(**values, version=row["version"] + 1, updated_at=now)
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(
                connection,
                context,
                space_id,
                "definition_requirement_package",
                command.action,
                updated,
                before=row,
                operation=command,
            )
            return _package(connection, context, updated)
