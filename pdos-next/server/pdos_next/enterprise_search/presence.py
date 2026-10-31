"""Prune absent source families under ordinary RLS; never admit a candidate here."""

from sqlalchemy import func, literal, or_, select, union_all

from pdos_next.database import require_context
from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.external_wait.models import ExternalWaitVersion
from pdos_next.domain.field_feedback.models import FieldFeedbackVersion, FieldResponseRecord
from pdos_next.domain.knowledge.models import DesignRuleVersion
from pdos_next.domain.preproject.category_models import KnowledgeEntry
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.supply_execution.models import SupplySnapshot
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.domain.verification_results.models import TestResultActionFact
from pdos_next.models import Artifact

from .role_native_sources import MODELS as ROLE_MODELS

MODELS = {
    "artifact": (Artifact,),
    "knowledge": (KnowledgeEntry, DesignRuleVersion),
    "issue": (QualityIssueVersion,),
    "capa": (QualityIssueVersion,),
    "change": (ChangeRequestVersion,),
    "external_wait": (ExternalWaitVersion,),
    "supply": (SupplySnapshot,),
    "build": (Build, BuildStart, ActualConfiguration, BuildLot),
    "test_run": (VerificationRunVersion, TestResultActionFact),
    "field_feedback": (FieldFeedbackVersion, FieldResponseRecord),
    **ROLE_MODELS,
}


def source_families(session, ctx, requested, scope):
    require_context(session, ctx)
    branches = []
    for kind in sorted(set(requested)):
        possible = []
        for model in MODELS[kind]:
            query = select(1).select_from(model).where(model.tenant_id == ctx.tenant_id)
            for key, value in scope.items():
                if value is not None and hasattr(model, key):
                    query = query.where(getattr(model, key) == value)
            possible.append(query.exists())
        branches.append(
            select(
                literal(kind).label("source_type"),
                or_(*possible).label("present"),
                func.transaction_timestamp().label("as_of"),
            )
        )
    rows = session.execute(union_all(*branches)).all()
    # This is a superset: current pointers, roots, hashes, scans and audiences
    # still go through the full authority relation before metadata/counts return.
    # Never use index rows for this pruning: an unindexed family must mark health.
    return tuple(row.source_type for row in rows if row.present), rows[0].as_of
