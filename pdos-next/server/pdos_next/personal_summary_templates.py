"""Display defaults from own saved preferences and current native duties.

A template is a subscription filter. Neither a job label nor a duty creates READ
or command authority. Unknown/ambiguous roles leave the choice to the subscriber.
"""

from sqlalchemy import and_, func, or_, select

from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal, Product
from pdos_next.personal_preference_models import PersonalPreference
from pdos_next.personal_preference_schemas import Preferences
from pdos_next.personal_views import _personal

KINDS = (
    "task",
    "own_task",
    "own_promise",
    "waiting_promise",
    "promise_review",
    "external_wait",
    "external_wait_transfer",
    "external_handoff",
    "project_risk",
    "g0_review",
    "verification_handoff_return",
    "verification_result_return",
    "supply_commitment",
    "project_update",
    "quality_issue_opened",
    "capa_observation_due",
    "upcoming_stage_gate",
)
TEMPLATES = (
    {
        "id": "general",
        "title": "我的工作 · 四问三组",
        "groups": ["action", "waiting", "following"],
        "kinds": list(KINDS),
    },
    {
        "id": "management",
        "title": "管理 · 项目具名状态与风险变化",
        "groups": ["action", "following"],
        "kinds": ["project_update", "project_risk", "g0_review"],
    },
    {
        "id": "product",
        "title": "产品 / 项目 · 阻塞、临近门禁与待决定事项",
        "groups": ["action", "waiting", "following"],
        "kinds": [k for k in KINDS if k not in {"quality_issue_opened", "capa_observation_due"}],
    },
    {
        "id": "quality",
        "title": "品质 · 新开问题与 CAPA 到期",
        "groups": ["action", "following"],
        "kinds": ["quality_issue_opened", "capa_observation_due"],
    },
    {
        "id": "supply",
        "title": "采购 · 外部等待与供应承诺",
        "groups": ["action", "waiting"],
        "kinds": [
            "external_wait",
            "external_wait_transfer",
            "external_handoff",
            "supply_commitment",
        ],
    },
)


def duties(ctx, at):
    """Ordinary RLS current fact join, never a qualification-as-duty shortcut."""
    f, c = ProfessionalFact, ProfessionalCurrent
    keys = (
        "tenant_id",
        "category_id",
        "product_id",
        "project_id",
        "subject_id",
        "kind",
        "issuer_key",
        "external_id",
        "series_id",
    )
    return (
        select(f)
        .join(
            c,
            and_(
                *(getattr(f, key) == getattr(c, key) for key in keys),
                f.id == c.fact_id,
                f.revision == c.fact_revision,
            ),
        )
        .where(
            f.tenant_id == ctx.tenant_id,
            f.subject_id == ctx.requester_id,
            f.kind == "duty",
            f.state == "active",
            f.valid_from <= at,
            f.valid_until > at,
        )
    )


def choose(explicit_role, duty_roles=(), *, project_manager=False):
    if explicit_role is not None:
        template = (
            explicit_role
            if explicit_role in {"management", "product", "quality", "supply"}
            else "general"
        )
        return template, "按本人已保存的岗位偏好预选；可修改，不代表专业资格。"
    known = {"quality" for role in duty_roles if role == "quality"}
    if project_manager:
        known.add("product")
    if len(known) == 1:
        return next(iter(known)), "按当前可读的本人有效职责预选；可修改，不增加权限。"
    if len(known) > 1:
        return None, "本人有多种已登记职责，请选择本次摘要模板。"
    return None, "尚无可确定的本人岗位默认，请自行选择模板。"


def read(s, ctx, category_id, product_id=None):
    _personal(s, ctx)
    person = s.get(Principal, ctx.requester_id)
    if (
        s.info.get("read_snapshot") is not True
        or ctx.run_id is not None
        or ctx.agent_run_id is not None
        or not person
        or not person.active
        or person.kind != "human"
        or person.tenant_id != ctx.tenant_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "摘要模板须由当前本人读取。", 403)
    category = s.get(Category, category_id)
    product = s.get(Product, product_id) if product_id is not None else None
    if (
        not category
        or category.tenant_id != ctx.tenant_id
        or product_id is not None
        and (
            not product or product.tenant_id != ctx.tenant_id or product.category_id != category_id
        )
    ):
        raise DomainError("FORBIDDEN_SCOPE", "摘要模板范围当前不可读。", 403)
    at = s.scalar(select(func.transaction_timestamp()))
    saved = s.scalar(
        select(PersonalPreference).where(
            PersonalPreference.tenant_id == ctx.tenant_id,
            PersonalPreference.owner_id == ctx.requester_id,
        )
    )
    explicit = Preferences.model_validate(saved.body).role if saved else None
    query = duties(ctx, at).where(ProfessionalFact.category_id == category_id)
    if product_id is not None:
        query = query.where(ProfessionalFact.product_id == product_id)
    roles = tuple(s.scalars(query.with_only_columns(ProfessionalFact.role).distinct()))
    pm = (
        s.scalar(
            select(Grant.id)
            .where(
                Grant.tenant_id == ctx.tenant_id,
                Grant.category_id == category_id,
                Grant.principal_id == ctx.requester_id,
                Grant.product_manager.is_(True),
                or_(Grant.expires_at.is_(None), Grant.expires_at > at),
            )
            .limit(1)
        )
        is not None
    )
    owned = select(Project.id).where(
        Project.tenant_id == ctx.tenant_id,
        Project.category_id == category_id,
        Project.owner_id == ctx.requester_id,
        Project.status == "active",
    )
    if product_id is not None:
        owned = owned.where(Project.product_id == product_id)
    pm = pm or s.scalar(owned.limit(1)) is not None
    template, reason = choose(explicit, roles, project_manager=pm)
    return {
        "version": "personal-summary-options/v1",
        "principal_id": str(ctx.requester_id),
        "category_id": str(category_id),
        "product_id": str(product_id) if product_id else None,
        "default_template": template,
        "reason": reason,
        "basis": {
            "saved_role": explicit,
            "current_duty_roles": sorted(roles),
            "project_manager": pm,
        },
        "templates": TEMPLATES,
    }
