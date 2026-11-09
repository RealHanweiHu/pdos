"""Project team reads and owner maintenance (`project.member.set`, P34-1, P55, P56).

Rules kept here and in the database guard:
- membership is never a permission root; a person needs a current category grant
  first, and the project owner cannot grant one;
- only the project owner, as a named human, changes the team; 小Pai is never a
  member and its identity can neither read nor write these tables;
- in a private project the audience is exactly the current members; a removed
  member with open work reaches only those items through the handover lane (P56).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from pdos_next.core.database import require_context
from pdos_next.core.models import Grant, ObjectAudience, Principal
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context, digest, require_access
from pdos_next.domain.categories.preproject.access import fail, human
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError

from . import handover
from . import roles as catalog
from .models import MemberAudience, MemberRole, ProjectMember, TeamChange

OPEN_TASK_STATES = ("assigned", "accepted", "in_progress", "submitted")
UPSTREAM_LABELS = {
    "products": "型号",
    "definition_revisions": "立项定义",
    "product_variants": "变体",
    "variant_revisions": "变体定义",
}


class RoleChoice(StrictModel):
    key: str = Field(pattern=catalog.KEY_PATTERN)
    lead: bool = False


class MemberChange(StrictModel):
    action: str = Field(pattern="^(add|set_roles|remove|complete)$")
    principal_id: UUID
    roles: list[RoleChoice] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def shape(self):
        if self.action in {"remove", "complete"} and self.roles:
            raise ValueError("移出成员时不设置角色")
        if len({role.key for role in self.roles}) != len(self.roles):
            raise ValueError("同一角色只能选择一次")
        return self


class SetTeam(StrictModel):
    expected_revision: int = Field(ge=0)
    request_key: UUID
    changes: list[MemberChange] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def one_change_per_person(self):
        people = [change.principal_id for change in self.changes]
        if len(set(people)) != len(people):
            raise ValueError("同一成员在一次提交中只能出现一次")
        return self


def _now():
    return datetime.now(UTC)


def _project(s, ctx, product_id, project_id, *, write=False):
    require_context(s, ctx)
    require_access(s, ctx, product_id, write=write, lock=write)
    query = select(Project).where(
        Project.tenant_id == ctx.tenant_id,
        Project.category_id == ctx.category_id,
        Project.product_id == product_id,
        Project.id == project_id,
    )
    row = s.scalar(query.with_for_update() if write else query)
    if row is None:
        raise DomainError("FORBIDDEN_SCOPE", "项目不存在或不在当前受众内。", 403)
    return row


def _revision(s, ctx, project_id):
    return (
        s.scalar(
            select(func.max(TeamChange.revision)).where(
                TeamChange.tenant_id == ctx.tenant_id, TeamChange.project_id == project_id
            )
        )
        or 0
    )


def _grants(s, ctx, category_id, people):
    """Current category grant per person: write, read, expired or missing."""
    found = {
        row.principal_id: row
        for row in s.scalars(
            select(Grant).where(
                Grant.tenant_id == ctx.tenant_id,
                Grant.category_id == category_id,
                Grant.principal_id.in_(list(people)),
            )
        )
    }
    at = _now()
    result = {}
    for person in people:
        grant = found.get(person)
        if grant is None:
            result[person] = "missing"
        elif grant.expires_at is not None and grant.expires_at <= at:
            result[person] = "expired"
        else:
            result[person] = "write" if grant.can_write else "read"
    return result


def pending_items(s, ctx, project, person):
    """Unhanded responsibility of one person in this project (P56), counted in SQL.

    The same rule gates the handover lane and settles the removal, so the page,
    the lane and the database can never disagree about what is left.
    """
    return handover.counts(handover.items(s, ctx, project.id, person))


def pending_detail(s, ctx, project, person):
    return handover.items(s, ctx, project.id, person)


def _open(pending):
    return any(pending.values())


def _pending_text(pending):
    parts = [
        f"{label} {pending[key]}"
        for key, label in (
            ("tasks", "任务"),
            ("commitments", "承诺"),
            ("external_waits", "外部等待"),
        )
        if pending[key]
    ]
    return "、".join(parts)


def _upstream(s, ctx, project, person):
    """Model, G0 definition and variant of a private project, as this person sees them."""
    return s.execute(
        text(
            "SELECT object_type, subject_id, owner_id, state "
            "FROM project_upstream(:tenant, :project, :person)"
        ),
        {"tenant": ctx.tenant_id, "project": project.id, "person": person},
    ).all()


def _claim_upstream(s, ctx, project, member):
    """Joining a private project brings its model and definition audiences the owner owns."""
    if project.visibility == "category":
        return
    for object_type, subject_id, owner_id, state in _upstream(s, ctx, project, member.principal_id):
        if state not in {"addable", "audience"}:
            continue
        if state == "addable":
            s.execute(
                insert(ObjectAudience)
                .values(
                    id=uuid4(),
                    tenant_id=ctx.tenant_id,
                    category_id=project.category_id,
                    object_type=object_type,
                    subject_id=subject_id,
                    owner_id=owner_id,
                    principal_id=member.principal_id,
                )
                .on_conflict_do_nothing()
            )
        s.add(
            MemberAudience(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                member_id=member.id,
                object_type=object_type,
                subject_id=subject_id,
                owner_id=owner_id,
                principal_id=member.principal_id,
                inserted=state == "addable",
            )
        )
    s.flush()


def _release_upstream(s, ctx, member):
    s.flush()
    s.execute(
        text("SELECT release_project_member_upstream(:tenant, :member)"),
        {"tenant": ctx.tenant_id, "member": member.id},
    )


def _role_view(names, key, lead):
    return {"key": key, "name": names.get(key, key), "lead": lead}


def view(s, ctx, product_id, project_id):
    project = _project(s, ctx, product_id, project_id)
    human(s, ctx)
    current = catalog.current(s, ctx.tenant_id)
    names = catalog.names(s, ctx.tenant_id)
    stints = list(
        s.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.tenant_id == ctx.tenant_id,
                ProjectMember.project_id == project.id,
            )
            .order_by(ProjectMember.joined_at, ProjectMember.id)
        )
    )
    held = {}
    for row in s.scalars(
        select(MemberRole)
        .where(MemberRole.tenant_id == ctx.tenant_id, MemberRole.project_id == project.id)
        .order_by(MemberRole.role_key)
    ):
        held.setdefault(row.member_id, []).append(row)
    can_manage = ctx.requester_id == project.owner_id
    tenant_people = {
        row.id: row
        for row in s.scalars(
            select(Principal).where(Principal.tenant_id == ctx.tenant_id, Principal.kind == "human")
        )
    }
    order = {role["key"]: index for index, role in enumerate(current["roles"])}
    # The owner leads the list; everyone else in joining order.
    active = sorted(
        (row for row in stints if row.left_at is None),
        key=lambda row: row.principal_id != project.owner_id,
    )
    grants = _grants(
        s, ctx, project.category_id, {row.principal_id for row in stints} | set(tenant_people)
    )

    def person(identity):
        row = tenant_people.get(identity)
        return row.name if row else "未知成员"

    private = project.visibility != "category"

    def gaps(identity):
        if not (can_manage and private):
            return []
        return [
            {"object": UPSTREAM_LABELS[object_type], "owner_name": person(owner_id)}
            for object_type, _, owner_id, state in _upstream(s, ctx, project, identity)
            if state == "blocked"
        ]

    members = []
    for row in active:
        assigned = sorted(
            held.get(row.id, []), key=lambda value: (order.get(value.role_key, 999), value.role_key)
        )
        members.append(
            {
                "member_id": str(row.id),
                "principal_id": str(row.principal_id),
                "name": person(row.principal_id),
                "is_owner": row.principal_id == project.owner_id,
                "roles": [_role_view(names, value.role_key, value.is_lead) for value in assigned],
                "joined_at": row.joined_at.isoformat(),
                "added_by": str(row.added_by),
                "added_by_name": person(row.added_by),
                "grant": grants[row.principal_id],
                "active_person": bool(
                    tenant_people.get(row.principal_id) and tenant_people[row.principal_id].active
                ),
                "pending": pending_items(s, ctx, project, row.principal_id)
                if can_manage and private and row.principal_id != project.owner_id
                else None,
                "pending_detail": pending_detail(s, ctx, project, row.principal_id)
                if can_manage
                and row.principal_id != project.owner_id
                and not (
                    tenant_people.get(row.principal_id) and tenant_people[row.principal_id].active
                )
                else [],
                "needs_model_access": gaps(row.principal_id),
            }
        )
    departed = [
        {
            "member_id": str(row.id),
            "principal_id": str(row.principal_id),
            "name": person(row.principal_id),
            "roles": [
                _role_view(names, value["key"], value["lead"]) for value in row.departed_roles
            ],
            "joined_at": row.joined_at.isoformat(),
            "left_at": row.left_at.isoformat(),
            "removed_by_name": person(row.removed_by),
            "handover_pending": row.handover_pending,
            "active_person": bool(
                tenant_people.get(row.principal_id) and tenant_people[row.principal_id].active
            ),
            "pending": pending_items(s, ctx, project, row.principal_id)
            if row.handover_pending and can_manage
            else None,
            # The handover card (§4.4): what is left to take over, item by item.
            "pending_detail": pending_detail(s, ctx, project, row.principal_id)
            if row.handover_pending and can_manage
            else [],
        }
        for row in sorted(
            (row for row in stints if row.left_at is not None),
            key=lambda value: value.left_at,
            reverse=True,
        )
    ]
    staffed = {value.role_key for rows in held.values() for value in rows}
    led = {value.role_key for rows in held.values() for value in rows if value.is_lead}
    result = {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "owner_id": str(project.owner_id),
            "owner_name": person(project.owner_id),
            "visibility": project.visibility,
        },
        "revision": _revision(s, ctx, project.id),
        "can_manage": can_manage,
        # A private project is visible to exactly its members; a category-shared one
        # stays visible to the whole category whatever the team is (§4.2).
        "membership_controls_visibility": project.visibility != "category",
        "catalog": current,
        "members": members,
        "departed": departed,
        "vacant_roles": [
            role["key"]
            for role in current["roles"]
            if role["active"] and role["key"] not in staffed
        ],
        "roles_without_lead": [
            role["key"]
            for role in current["roles"]
            if role["active"] and role["key"] in staffed and role["key"] not in led
        ],
    }
    if can_manage:
        present = {row.principal_id for row in active}
        result["candidates"] = [
            {"principal_id": str(identity), "name": row.name, "grant": grants[identity]}
            for identity, row in sorted(tenant_people.items(), key=lambda item: item[1].name)
            if identity not in present and row.active
        ]
    return result


def _audience(s, ctx, project, person, *, present):
    if present:
        s.execute(
            insert(ObjectAudience)
            .values(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=project.category_id,
                object_type="projects",
                subject_id=project.id,
                owner_id=project.owner_id,
                principal_id=person,
            )
            .on_conflict_do_nothing()
        )
        return
    s.execute(
        delete(ObjectAudience).where(
            ObjectAudience.tenant_id == ctx.tenant_id,
            ObjectAudience.category_id == project.category_id,
            ObjectAudience.object_type == "projects",
            ObjectAudience.subject_id == project.id,
            ObjectAudience.owner_id == project.owner_id,
            ObjectAudience.principal_id == person,
        )
    )


def _validate_roles(choices, current, previous_keys):
    usable = {role["key"]: role["active"] for role in current["roles"]}
    for choice in choices:
        if choice.key not in usable:
            fail("VALIDATION_FAILED", "role_unknown", "角色不在当前角色目录中。", 422)
        # P60-4: a deactivated role is kept where held, never newly assigned.
        if not usable[choice.key] and choice.key not in previous_keys:
            fail("VALIDATION_FAILED", "role_inactive", "该角色已停用，不能再分派。", 422)


def apply(s, ctx: Context, product_id, project_id, data: SetTeam):
    human(s, ctx)
    project = _project(s, ctx, product_id, project_id, write=True)
    if ctx.requester_id != project.owner_id:
        fail("FORBIDDEN_SCOPE", "owner_only", "项目成员由本项目负责人维护。", 403)
    fingerprint = digest(data.model_dump(mode="json"))
    prior = s.scalar(
        select(TeamChange).where(
            TeamChange.tenant_id == ctx.tenant_id,
            TeamChange.author_id == ctx.actor_id,
            TeamChange.request_key == data.request_key,
        )
    )
    if prior is not None:
        if prior.request_sha256 != fingerprint or prior.project_id != project.id:
            fail("DUPLICATE_INTENT_CONFLICT", "request_rebound", "原请求已绑定其他内容。")
        return view(s, ctx, product_id, project_id)
    revision = _revision(s, ctx, project.id)
    if data.expected_revision != revision:
        fail("VERSION_CONFLICT", "team_changed", "项目成员已被修改，请刷新后重试。")
    current = catalog.current(s, ctx.tenant_id)
    active = {
        row.principal_id: row
        for row in s.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.tenant_id == ctx.tenant_id,
                ProjectMember.project_id == project.id,
                ProjectMember.left_at.is_(None),
            )
            .with_for_update()
        )
    }
    retained = {
        row.principal_id: row
        for row in s.scalars(
            select(ProjectMember)
            .where(
                ProjectMember.tenant_id == ctx.tenant_id,
                ProjectMember.project_id == project.id,
                ProjectMember.handover_pending.is_(True),
            )
            .with_for_update()
        )
    }
    held = {}
    for row in s.scalars(
        select(MemberRole).where(
            MemberRole.tenant_id == ctx.tenant_id, MemberRole.project_id == project.id
        )
    ):
        held.setdefault(row.member_id, []).append(row)
    pending = {}
    people = {
        row.id: row
        for row in s.scalars(
            select(Principal).where(
                Principal.tenant_id == ctx.tenant_id,
                Principal.id.in_([change.principal_id for change in data.changes]),
            )
        )
    }
    grants = _grants(s, ctx, project.category_id, {change.principal_id for change in data.changes})
    final = {
        identity: {(value.role_key, value.is_lead) for value in held.get(row.id, [])}
        for identity, row in active.items()
    }
    for change in data.changes:
        identity = change.principal_id
        person = people.get(identity)
        if person is not None and person.kind != "human":
            fail(
                "VALIDATION_FAILED",
                "agent_not_member",
                "小Pai 不是项目成员，不能加入团队或担任角色。",
                422,
            )
        if change.action == "add":
            if person is None or not person.active:
                fail(
                    "VALIDATION_FAILED", "person_unavailable", "此人不在当前组织或账号已停用。", 422
                )
            if identity in active:
                fail("VERSION_CONFLICT", "already_member", "此人已是项目成员，请刷新后重试。")
            if grants[identity] in {"missing", "expired"}:
                fail(
                    "FORBIDDEN_SCOPE",
                    "category_grant_required",
                    f"需要品类授权：{person.name} 还没有当前品类的有效授权，"
                    "请联系管理员处理；项目负责人不能代为授权。",
                    403,
                    principal_id=str(identity),
                )
            _validate_roles(change.roles, current, set())
            final[identity] = {(role.key, role.lead) for role in change.roles}
            continue
        if change.action == "complete":
            if identity not in retained:
                fail("VERSION_CONFLICT", "no_open_removal", "此人没有待交接的移出，请刷新后重试。")
            left = pending_items(s, ctx, project, identity)
            if _open(left):
                fail(
                    "VALIDATION_FAILED",
                    "handover_open",
                    f"还有未交接事项（{_pending_text(left)}），交接完成后才能完全移出。",
                    422,
                    pending=left,
                )
            continue
        if identity not in active:
            fail("VERSION_CONFLICT", "not_member", "此人已不在项目中，请刷新后重试。")
        if change.action == "remove":
            if identity == project.owner_id:
                fail("VALIDATION_FAILED", "owner_stays", "项目负责人始终在团队中，不能移出。", 422)
            # P56: unhanded work keeps only the person's own items reachable until handed over.
            if project.visibility != "category":
                pending[identity] = pending_items(s, ctx, project, identity)
            final.pop(identity)
            continue
        _validate_roles(
            change.roles, current, {value.role_key for value in held.get(active[identity].id, [])}
        )
        final[identity] = {(role.key, role.lead) for role in change.roles}
    leads = [key for values in final.values() for key, lead in values if lead]
    if len(leads) != len(set(leads)):
        fail("VALIDATION_FAILED", "one_lead_per_role", "每个角色最多一名主责人。", 422)
    change_row = TeamChange(
        tenant_id=ctx.tenant_id,
        project_id=project.id,
        revision=revision + 1,
        source="owner",
        author_id=ctx.actor_id,
        request_key=data.request_key,
        request_sha256=fingerprint,
        changes=[change.model_dump(mode="json") for change in data.changes],
    )
    s.add(change_row)
    s.flush()
    at = _now()
    # Clear the roles being replaced first, so a lead can move between people.
    touched = [active[c.principal_id].id for c in data.changes if c.principal_id in active]
    if touched:
        s.execute(
            delete(MemberRole).where(
                MemberRole.tenant_id == ctx.tenant_id,
                MemberRole.project_id == project.id,
                MemberRole.member_id.in_(touched),
            )
        )
    for change in data.changes:
        identity = change.principal_id
        if change.action == "complete":
            row = retained[identity]
            row.handover_pending = False
            s.flush()
            _audience(s, ctx, project, identity, present=False)
            _release_upstream(s, ctx, row)
            continue
        if change.action == "remove":
            row = active[identity]
            row.left_at = at
            row.removed_by = ctx.actor_id
            row.left_change_id = change_row.id
            row.departed_roles = [
                {"key": value.role_key, "lead": value.is_lead} for value in held.get(row.id, [])
            ]
            row.handover_pending = _open(pending.get(identity, {}))
            s.flush()
            # The project audience ends now either way (P56-1); only a removal with
            # open work keeps the model/definition claims its own items still need.
            _audience(s, ctx, project, identity, present=False)
            if not row.handover_pending:
                _release_upstream(s, ctx, row)
            continue
        if change.action == "add":
            row = ProjectMember(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                principal_id=identity,
                joined_at=at,
                added_by=ctx.actor_id,
                joined_change_id=change_row.id,
            )
            s.add(row)
            s.flush()
            _audience(s, ctx, project, identity, present=True)
            _claim_upstream(s, ctx, project, row)
            # Re-joining closes a removal still open for handover; its upstream
            # claims pass to the new membership instead of being withdrawn.
            if identity in retained:
                retained[identity].handover_pending = False
                _release_upstream(s, ctx, retained[identity])
        else:
            row = active[identity]
        for role in change.roles:
            s.add(
                MemberRole(
                    tenant_id=ctx.tenant_id,
                    project_id=project.id,
                    member_id=row.id,
                    role_key=role.key,
                    is_lead=role.lead,
                    change_id=change_row.id,
                )
            )
    s.flush()
    return view(s, ctx, product_id, project_id)


def register_g0(s, ctx, project, people, decision):
    """P55: whoever G0 adds to the project audience joins the team, roles empty."""
    people = sorted(set(people), key=str)
    change = TeamChange(
        tenant_id=ctx.tenant_id,
        project_id=project.id,
        revision=1,
        source="g0",
        author_id=ctx.actor_id,
        request_key=decision.id,
        request_sha256=digest({"g0_decision_id": str(decision.id), "people": people}),
        changes=[{"action": "add", "principal_id": str(person), "roles": []} for person in people],
    )
    s.add(change)
    s.flush()
    at = _now()
    for person in people:
        s.add(
            ProjectMember(
                tenant_id=ctx.tenant_id,
                project_id=project.id,
                principal_id=person,
                joined_at=at,
                added_by=ctx.actor_id,
                joined_change_id=change.id,
            )
        )
    s.flush()
    return [str(person) for person in people]
