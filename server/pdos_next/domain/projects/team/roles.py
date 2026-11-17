"""Tenant role catalog shared with the NPI framework's responsible roles (P34-1, P60-4).

The built-in list is only an editable starting point (design §4.1). The formal
content comes from the tenant (D66); a tenant administrator publishes versions.
"""

from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select, text

from pdos_next.core.database import require_context
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context, digest
from pdos_next.domain.categories.preproject.access import fail, human
from pdos_next.errors import DomainError

from .models import RoleCatalogVersion

DEFAULT_ROLES = (
    ("product_manager", "产品经理"),
    ("project_manager", "项目经理"),
    ("industrial_design", "ID"),
    ("mechanical", "结构"),
    ("electronics", "电子"),
    ("software", "软件"),
    ("quality", "品质"),
    ("certification", "认证"),
    ("test_engineering", "测试工程"),
    ("process_factory", "工艺/工厂"),
    ("procurement_supply", "采购/供应链"),
    ("battery_safety", "电池安全"),
)
KEY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class RoleEntry(StrictModel):
    key: str | None = Field(default=None, pattern=KEY_PATTERN)
    name: str = Field(min_length=1, max_length=40)
    active: bool = True

    @field_validator("name")
    @classmethod
    def name_required(cls, value):
        if not value.strip():
            raise ValueError("请输入角色名称")
        return value.strip()


class PublishCatalog(StrictModel):
    expected_revision: int = Field(ge=0)
    request_key: UUID
    roles: list[RoleEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct(self):
        keys = [role.key for role in self.roles if role.key]
        names = [role.name for role in self.roles]
        if len(set(keys)) != len(keys) or len(set(names)) != len(names):
            raise ValueError("角色不能重复")
        return self


def default_catalog():
    return {
        "revision": 0,
        "default": True,
        "roles": [{"key": key, "name": name, "active": True} for key, name in DEFAULT_ROLES],
    }


def current(s, tenant_id):
    """Effective catalog: the latest published version, or the built-in default."""
    row = s.scalar(
        select(RoleCatalogVersion)
        .where(RoleCatalogVersion.tenant_id == tenant_id)
        .order_by(RoleCatalogVersion.revision.desc())
        .limit(1)
    )
    if row is None:
        return default_catalog()
    return {"revision": row.revision, "default": False, "roles": list(row.roles)}


def names(s, tenant_id):
    """Display names for every key ever catalogued, so departed roles stay readable."""
    found = {key: name for key, name in DEFAULT_ROLES}
    for roles in s.scalars(
        select(RoleCatalogVersion.roles)
        .where(RoleCatalogVersion.tenant_id == tenant_id)
        .order_by(RoleCatalogVersion.revision)
    ):
        found.update({role["key"]: role["name"] for role in roles})
    return found


def _administrator(s, ctx):
    from pdos_next.agent.kernel.models import TenantAdministrator

    return bool(
        s.scalar(
            select(TenantAdministrator.id).where(
                TenantAdministrator.tenant_id == ctx.tenant_id,
                TenantAdministrator.principal_id == ctx.actor_id,
                TenantAdministrator.active.is_(True),
            )
        )
    )


def check(s, ctx):
    require_context(s, ctx)
    human(s, ctx)
    if ctx.category_id is not None:
        raise DomainError("FORBIDDEN_SCOPE", "角色目录属于租户，不在单个品类内。", 403)


def reading(s, ctx: Context):
    check(s, ctx)
    return {**current(s, ctx.tenant_id), "can_publish": _administrator(s, ctx)}


def publish(s, ctx: Context, data: PublishCatalog):
    check(s, ctx)
    if not _administrator(s, ctx):
        raise DomainError("FORBIDDEN_SCOPE", "角色目录由租户管理员本人发布。", 403)
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"project-role-catalog:{ctx.tenant_id}"},
    )
    fingerprint = digest(data.model_dump(mode="json"))
    prior = s.scalar(
        select(RoleCatalogVersion).where(
            RoleCatalogVersion.tenant_id == ctx.tenant_id,
            RoleCatalogVersion.author_id == ctx.actor_id,
            RoleCatalogVersion.request_key == data.request_key,
        )
    )
    if prior is not None:
        if prior.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求已绑定其他内容。")
        return reading(s, ctx)
    before = current(s, ctx.tenant_id)
    if data.expected_revision != before["revision"]:
        raise DomainError("VERSION_CONFLICT", "角色目录已由其他管理员更新，请刷新后重试。")
    roles = [
        {"key": role.key or f"r_{uuid4().hex[:12]}", "name": role.name, "active": role.active}
        for role in data.roles
    ]
    removed = sorted({role["key"] for role in before["roles"]} - {role["key"] for role in roles})
    if removed:
        held = sorted(
            set(s.scalar(select(func.project_role_references(ctx.tenant_id, removed))))
            | set(s.scalar(select(func.npi_framework_role_references(ctx.tenant_id, removed))))
            | set(
                s.scalar(select(func.npi_unfinished_plan_role_references(ctx.tenant_id, removed)))
            )
        )
        if held:
            labels = {role["key"]: role["name"] for role in before["roles"]}
            fail(
                "VERSION_CONFLICT",
                "role_referenced",
                "项目成员、启用框架或未完成任务仍在引用这些角色，可以将其停用："
                + "、".join(labels.get(key, key) for key in held),
                role_keys=list(held),
            )
    s.add(
        RoleCatalogVersion(
            tenant_id=ctx.tenant_id,
            revision=before["revision"] + 1,
            roles=roles,
            author_id=ctx.actor_id,
            request_key=data.request_key,
            request_sha256=fingerprint,
        )
    )
    s.flush()
    return reading(s, ctx)
