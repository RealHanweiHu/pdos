"""Batched ordinary-RLS structural comparisons; no inference from free text."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, select

from pdos_next.domain.build_execution.models import ActualConfiguration
from pdos_next.domain.builds.models import Build
from pdos_next.domain.configurations.models import BomLine, EngineeringConfiguration, PartIdentity
from pdos_next.domain.project_governance.models import GovernanceEvent


def structural_context(session, tenant_id, snapshots, projects):
    builds, actuals = defaultdict(set), defaultdict(set)
    for source_id, snapshot in snapshots.items():
        for failure in snapshot.get("failures", []):
            if failure.get("build", {}).get("id"):
                builds[source_id].add(UUID(failure["build"]["id"]))
            actual = failure.get("sample", {}).get("actual_configuration", {}).get("id")
            if actual:
                actuals[source_id].add(UUID(actual))
    build_ids = set().union(*builds.values()) if builds else set()
    build_names = {} if not build_ids else dict(session.execute(select(Build.id, Build.name).where(
        Build.tenant_id == tenant_id, Build.id.in_(build_ids),
    )).all())
    actual_ids = set().union(*actuals.values()) if actuals else set()
    numbers = defaultdict(set)
    if actual_ids:
        a, e, b, p = ActualConfiguration, EngineeringConfiguration, BomLine, PartIdentity
        rows = session.execute(select(a.id, p.internal_number, p.erp_number, p.customer_number)
            .join(e, and_(e.tenant_id == a.tenant_id, e.product_id == a.product_id,
                          e.id == a.actual_engineering_configuration_id,
                          e.revision == a.actual_engineering_revision))
            .join(b, and_(b.tenant_id == e.tenant_id, b.product_id == e.product_id,
                          b.bom_id == e.bom_id))
            .join(p, and_(p.tenant_id == b.tenant_id, p.product_id == b.product_id,
                          p.id == b.part_id, p.revision == b.part_revision))
            .where(a.tenant_id == tenant_id, a.id.in_(actual_ids)))
        for actual, internal, erp, customer in rows:
            for label, value in (("内部", internal), ("ERP", erp), ("客户", customer)):
                if value:
                    numbers[actual].add(f"{label}:{value}")
    stages = {}
    for row in session.scalars(select(GovernanceEvent).where(
        GovernanceEvent.tenant_id == tenant_id, GovernanceEvent.project_id.in_(projects),
    ).distinct(GovernanceEvent.project_id).order_by(
        GovernanceEvent.project_id, GovernanceEvent.revision.desc(),
    )):
        recorded, position = row.body.get("stages", []), row.body.get("position", 0)
        if position < len(recorded):
            stages[str(row.project_id)] = recorded[position]["name"]
        elif recorded:
            stages[str(row.project_id)] = "阶段已完成（末阶段：" + recorded[-1]["name"] + "）"
    return {
        "builds": {key: sorted(build_names[identity] for identity in values
                                if identity in build_names) for key, values in builds.items()},
        "parts": {key: sorted(set().union(*(numbers[identity] for identity in values)))
                  for key, values in actuals.items()},
        "stages": stages,
    }
