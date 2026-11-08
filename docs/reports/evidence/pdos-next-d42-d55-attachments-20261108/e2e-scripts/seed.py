"""Add the tenant's 小Pai identity, a second category with one registered text source, and grants."""
import json, os, sys
from datetime import timedelta
from uuid import UUID, uuid4
sys.path.insert(0, os.path.dirname(__file__))
from common import STATE, env  # noqa: E402
os.environ.update(env())
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from pdos_next.core.contracts import Command  # noqa: E402
from pdos_next.core.database import engine_for, tenant_session  # noqa: E402
from pdos_next.core.models import Category, Grant, Principal, now  # noqa: E402
from pdos_next.core.service import Context, execute  # noqa: E402
from pdos_next.agent.kernel.models import TenantPilotAdmission  # noqa: E402
account = STATE["dev_accounts"]["d42"]
tenant, person, first = UUID(account["tenant_id"]), UUID(account["principal_id"]), UUID(account["category_id"])
admin, app = engine_for(STATE["admin_url"]), engine_for(STATE["app_url"])
with Session(admin) as s, s.begin():
    agent = s.scalar(select(Principal).where(Principal.tenant_id == tenant, Principal.kind == "agent"))
    if agent is None:
        agent = Principal(id=uuid4(), tenant_id=tenant, name="小Pai", kind="agent"); s.add(agent); s.flush()
    if s.get(TenantPilotAdmission, tenant) is None:
        s.add(TenantPilotAdmission(tenant_id=tenant, active=True, approval_reference="isolated synthetic e2e only"))
    second = s.scalar(select(Category).where(Category.tenant_id == tenant, Category.name == "自行车打气筒（合成）"))
    if second is None:
        second = Category(id=uuid4(), tenant_id=tenant, name="自行车打气筒（合成）", purpose="D42 跨品类附件验收", owner_id=person)
        s.add(second); s.flush()
    for category in (first, second.id):
        for principal in (person, agent.id):
            if not s.scalar(select(Grant).where(Grant.category_id == category, Grant.principal_id == principal)):
                s.add(Grant(tenant_id=tenant, category_id=category, principal_id=principal, can_write=True,
                            product_manager=principal == person, expires_at=now() + timedelta(days=7)))
    second_id = second.id
with tenant_session(app, tenant, actor_id=person, requester_id=person, category_id=second_id) as s:
    execute(s, Context(tenant, person, person, category_id=second_id), Command(
        command_id=uuid4(), idempotency_key=f"d42-seed:{uuid4()}", operation="evidence.artifact.register",
        category_id=second_id, product_id=None, expected_revision=1, source_read_set=[],
        payload={"title": "打气筒售后记录（合成）", "content": "合成售后记录（非真实客户资料）\n气嘴漏气时先更换气嘴垫圈再复测压力\n",
                 "source_label": "D42 合成登记资料", "visibility": "category"}))
print("seeded tenant", str(tenant)[:8], "categories", 2)
