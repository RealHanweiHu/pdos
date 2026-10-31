"""Current object destinations from authorized fixed records; never model-authored URLs."""

from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import and_, cast, select, union_all
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from pdos_next.domain.builds.models import Build
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.supply_execution.models import SupplySnapshot
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import TestResultActionFact


def links(session, sources):
    kinds = {row["source_type"] for row in sources.values()}
    branches = []
    for group, models in (
        ({"issue", "capa"}, (QualityIssueVersion,)),
        ({"test_run"}, (VerificationRunVersion, TestResultActionFact)),
        ({"supply"}, (SupplySnapshot,)),
    ):
        if not group.intersection(kinds):
            continue
        ids = {
            UUID(str(row["source_id"])) for row in sources.values() if row["source_type"] in group
        }
        for model in models:
            quality = model is QualityIssueVersion
            build_id = (
                cast(model.issue_snapshot["failures"][0]["build"]["id"].astext, PGUUID)
                if quality
                else model.build_id
            )
            aggregate = (
                model.issue_id
                if quality
                else model.run_id
                if hasattr(model, "run_id")
                else model.id
            )
            branches.append(
                select(
                    model.id.label("source_id"),
                    Build.id.label("build_id"),
                    aggregate.label("aggregate_id"),
                )
                .join(
                    Build,
                    and_(
                        Build.tenant_id == model.tenant_id,
                        Build.category_id == model.category_id,
                        Build.product_id == model.product_id,
                        Build.project_id == model.project_id,
                        Build.id == build_id,
                    ),
                )
                .where(model.id.in_(ids))
            )
    parents = (
        {
            row.source_id: (row.build_id, row.aggregate_id)
            for row in session.execute(union_all(*branches))
        }
        if branches
        else {}
    )
    destinations = {}
    for cid, row in sources.items():
        kind = row["source_type"]
        if not all(row.get(key) for key in ("category_id", "product_id", "project_id")):
            continue
        target = str(row.get("object_id", row["source_id"]))
        identity = UUID(str(row["source_id"]))
        if kind in {"issue", "capa"} and identity in parents:
            view, panel = "issues", "quality" if kind == "issue" else "followup"
            label = "查看当前问题" if kind == "issue" else "查看当前问题与措施"
            selected = {"build": str(parents[identity][0]), "issue": str(parents[identity][1])}
        elif kind == "field_feedback":
            view, panel, label, selected = (
                "feedback",
                "field",
                "查看当前现场反馈",
                {"feedback": target},
            )
        elif kind == "change":
            view, panel, label, selected = "issues", "changes", "查看当前变更", {"change": target}
        elif kind == "build":
            view, panel, label, selected = (
                "builds",
                "summary",
                "查看当前试制轮次",
                {"build": target},
            )
        elif kind in {"test_run", "supply"} and identity in parents:
            view, panel, label = (
                ("builds", "results", "查看当前测试记录")
                if kind == "test_run"
                else ("prep", "supply", "查看当前供应记录")
            )
            selected = {"build": str(parents[identity][0])}
            if kind == "test_run":
                selected["run"] = target
        else:
            continue
        destinations[cid] = {
            "object_url": "/?"
            + urlencode(
                {
                    "area": "cockpit",
                    "category": str(row["category_id"]),
                    "product": str(row["product_id"]),
                    "project": str(row["project_id"]),
                    "projectView": view,
                    "panel": panel,
                    **selected,
                }
            ),
            "object_label": label,
        }
    from .role_native_navigation import links as role_links

    destinations.update(role_links(session, sources))
    return destinations
