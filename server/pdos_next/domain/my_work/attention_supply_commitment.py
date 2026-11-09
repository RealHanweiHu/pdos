"""Open supplier commitments the reader follows up, without writes (F25).

The check date is one day after the promised date. It is an internal follow-up
point only: never a breach judgment, a missing arrival or a kit result.
"""

from sqlalchemy import DateTime, String, and_, cast, func, literal, select

from pdos_next.core import models as registered_models  # noqa: F401 -- ordinary native registry
from pdos_next.domain.manufacturing.supply_commitments.models import (
    SupplyCommitmentCurrent,
    SupplyCommitmentVersion,
)
from pdos_next.domain.my_work.attention_common import columns

KIND = "supply_commitment_check"


def queries(ctx, queue=None):
    if queue is not None and queue != "external":
        return ()
    current, row = SupplyCommitmentCurrent, SupplyCommitmentVersion
    exact = and_(
        current.tenant_id == row.tenant_id,
        current.version_id == row.id,
        current.revision == row.revision,
        current.commitment_id == row.commitment_id,
    )
    query = (
        select(
            *columns(
                key=literal(KIND + ":") + cast(row.commitment_id, String),
                kind=KIND,
                queue="external",
                tenant_id=row.tenant_id,
                source_id=row.commitment_id,
                version_id=row.id,
                revision=row.revision,
                category_id=row.category_id,
                product_id=row.product_id,
                project_id=row.project_id,
                recorded_at=row.created_at,
                title=literal("供方承诺：") + row.body["supplier_ref"].astext,
                reason="你登记并跟进这条供方承诺；检查日是承诺日的次日，只是内部跟进点，"
                "不表示违约，也不表示未到货。",
                state=row.state,
                responsible_id=ctx.requester_id,
                responsibility="supply_commitment_responsible",
                target="project",
                due_at=cast(row.body["check_at"].astext, DateTime(timezone=True)),
                details=func.jsonb_build_object(
                    "view",
                    "supply",
                    "build_id",
                    row.build_id,
                    "material_id",
                    row.material_id,
                    "promised_at",
                    row.body["promised_at"].astext,
                    "check_at",
                    row.body["check_at"].astext,
                    "check_is_internal",
                    True,
                    "original_timezone",
                    row.body["original_timezone"].astext,
                    "time_basis",
                    row.body["time_basis"].astext,
                ),
            )
        )
        .select_from(current)
        .join(row, exact)
        .where(
            row.tenant_id == ctx.tenant_id,
            current.state == "open",
            row.body["responsible_id"].astext == str(ctx.requester_id),
        )
    )
    return (query,)
