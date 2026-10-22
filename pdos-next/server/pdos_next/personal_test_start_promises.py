"""The caller's signed start promises, projected in one ordinary RR/RLS snapshot."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from pdos_next import models
from pdos_next.domain.builds.models import Build
from pdos_next.domain.projects.models import Project
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.personal_views import _personal
from pdos_next.schemas.verification.contracts import Coverage, EventTime, TimeFact

VERSION = "personal-test-start-promises/v1"
SCOPE = ("tenant_id", "category_id", "product_id", "project_id", "build_id", "request_id", "run_id")
STATES = {"planned", "running", "results_pending", "reviewed", "disposed"}
CLOCK_FIELDS = {"occurred_at", "original_timezone", "effective_at"}


def _records(ctx):
    promised_run = aliased(VerificationRunVersion, name="promised_run")
    current_run = aliased(VerificationRunVersion, name="current_run")
    heads = (
        (
            "fact",
            VerificationLaunchFact,
            (*SCOPE, "id", "created_at", "owner_id", "run_version_id", "run_revision"),
        ),
        ("product", models.Product, ("id", "tenant_id", "category_id", "name")),
        ("category", models.Category, ("id", "tenant_id", "name")),
        ("project", Project, ("id", "tenant_id", "category_id", "product_id", "name")),
        ("build", Build, ("id", "tenant_id", "category_id", "product_id", "project_id", "name")),
        (
            "pointer",
            VerificationRunCurrent,
            (
                "id",
                "tenant_id",
                "category_id",
                "product_id",
                "request_id",
                "run_id",
                "run_version_id",
                "run_revision",
            ),
        ),
        ("promised", promised_run, (*SCOPE, "id", "revision", "status")),
        ("current", current_run, (*SCOPE, "id", "revision", "status")),
    )
    fact = VerificationLaunchFact
    # No ORM entities, frozen documents, source text or full snapshots are loaded.
    return (
        select(
            *(
                getattr(model, field).label(f"{prefix}_{field}")
                for prefix, model, fields in heads
                for field in fields
            ),
            fact.input_snapshot["at"].label("promise_at"),
            current_run.run_snapshot["actual_start"].label("actual_start"),
            current_run.run_snapshot["coverage"].label("coverage"),
        )
        .select_from(fact)
        .join(
            models.Product,
            and_(models.Product.tenant_id == fact.tenant_id, models.Product.id == fact.product_id),
        )
        .join(
            models.Category,
            and_(
                models.Category.tenant_id == models.Product.tenant_id,
                models.Category.id == models.Product.category_id,
            ),
        )
        .join(Project, and_(Project.tenant_id == fact.tenant_id, Project.id == fact.project_id))
        .join(Build, and_(Build.tenant_id == fact.tenant_id, Build.id == fact.build_id))
        .outerjoin(
            VerificationRunCurrent,
            and_(
                VerificationRunCurrent.tenant_id == fact.tenant_id,
                VerificationRunCurrent.run_id == fact.run_id,
            ),
        )
        .outerjoin(
            promised_run,
            and_(promised_run.tenant_id == fact.tenant_id, promised_run.id == fact.run_version_id),
        )
        .outerjoin(
            current_run,
            and_(
                current_run.tenant_id == fact.tenant_id,
                current_run.id == VerificationRunCurrent.run_version_id,
            ),
        )
        .where(
            fact.tenant_id == ctx.tenant_id,
            fact.owner_id == ctx.requester_id,
            fact.operation == "verification.schedule.promise",
        )
    )


def _invalid():
    raise DomainError("INTEGRITY_MISMATCH", "开测承诺的范围、时间或覆盖元数据无法核对，请刷新。")


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _invalid()
    return value.astimezone(UTC)


def _matches(row, prefix, expected):
    if any(row[f"{prefix}_{field}"] != value for field, value in expected.items()):
        _invalid()


def _entry(row, ctx, as_of):
    scope = {field: row[f"fact_{field}"] for field in SCOPE}
    if scope["tenant_id"] != ctx.tenant_id or row["fact_owner_id"] != ctx.requester_id:
        _invalid()
    _matches(
        row,
        "product",
        {
            "id": scope["product_id"],
            "tenant_id": scope["tenant_id"],
            "category_id": scope["category_id"],
        },
    )
    _matches(row, "category", {"id": scope["category_id"], "tenant_id": scope["tenant_id"]})
    _matches(
        row,
        "project",
        {
            "id": scope["project_id"],
            **{key: scope[key] for key in ("tenant_id", "category_id", "product_id")},
        },
    )
    _matches(
        row,
        "build",
        {
            "id": scope["build_id"],
            **{key: scope[key] for key in ("tenant_id", "category_id", "product_id", "project_id")},
        },
    )
    if any(row[f"{prefix}_id"] is None for prefix in ("pointer", "promised", "current")):
        raise DomainError("SOURCE_UNAVAILABLE", "承诺依赖的运行版本当前不可读，请刷新后重试。")
    _matches(
        row,
        "pointer",
        {
            key: scope[key]
            for key in ("tenant_id", "category_id", "product_id", "request_id", "run_id")
        },
    )
    _matches(
        row,
        "promised",
        {
            **scope,
            "id": row["fact_run_version_id"],
            "revision": row["fact_run_revision"],
            "status": "planned",
        },
    )
    _matches(
        row,
        "current",
        {**scope, "id": row["pointer_run_version_id"], "revision": row["pointer_run_revision"]},
    )
    status, revision = row["current_status"], row["current_revision"]
    if status not in STATES or revision < row["fact_run_revision"]:
        _invalid()
    try:
        promise = EventTime.model_validate(row["promise_at"])
        actual = (
            TimeFact.model_validate(row["actual_start"])
            if row["actual_start"] is not None
            else None
        )
        raw_coverage = row["coverage"]
        if type(raw_coverage) is not list or not raw_coverage:
            _invalid()
        coverage = [Coverage.model_validate(pair) for pair in raw_coverage]
    except ValidationError:
        _invalid()
    pairs = {(pair.sample_id, pair.item_id) for pair in coverage}
    if len(pairs) != len(coverage) or (status == "planned") != (actual is None):
        _invalid()
    if actual is not None:
        timing = (
            "started_on_or_before" if actual.occurred_at <= promise.occurred_at else "started_late"
        )
    else:
        timing = "past_due_no_start_record" if as_of > promise.occurred_at else "awaiting_start"
    return {
        "id": str(row["fact_id"]),
        "recorded_at": _aware(row["fact_created_at"]).isoformat(),
        **{
            prefix: {"id": str(row[f"{prefix}_id"]), "name": row[f"{prefix}_name"]}
            for prefix in ("category", "product", "project", "build")
        },
        "request": {"id": str(scope["request_id"])},
        "run": {"id": str(scope["run_id"]), "revision": revision, "status": status},
        "promise": promise.model_dump(mode="json", include=CLOCK_FIELDS),
        "actual_start": actual.model_dump(mode="json", include=CLOCK_FIELDS | {"received_at"})
        if actual
        else None,
        "recipient": None,
        "recipient_status": "not_recorded",
        "timing": timing,
        "coverage": {
            "sample_count": len({pair.sample_id for pair in coverage}),
            "item_count": len({pair.item_id for pair in coverage}),
            "pair_count": len(pairs),
        },
    }


def read(s, ctx, *, cursor=None, page_size=20):
    _personal(s, ctx)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise DomainError("VALIDATION_FAILED", "每页数量须为 1–100 的整数。", 422)
    if cursor is not None:
        try:
            cursor = cursor if isinstance(cursor, UUID) else UUID(cursor)
        except (ValueError, TypeError, AttributeError):
            raise DomainError("VALIDATION_FAILED", "分页位置须为承诺记录 UUID。", 422) from None
    as_of = _aware(s.scalar(select(func.transaction_timestamp())))
    records = _records(ctx)
    page = records
    if cursor is not None:
        anchor = s.execute(records.where(VerificationLaunchFact.id == cursor)).mappings().first()
        if anchor is None:
            raise DomainError("FORBIDDEN_SCOPE", "分页位置已不可读，请刷新承诺记录。", 403)
        _entry(anchor, ctx, as_of)
        page = page.where(
            or_(
                VerificationLaunchFact.created_at < anchor["fact_created_at"],
                and_(
                    VerificationLaunchFact.created_at == anchor["fact_created_at"],
                    VerificationLaunchFact.id < anchor["fact_id"],
                ),
            )
        )
    # This counts readable signed fact candidates. A broken dependency on this
    # page (including the look-ahead row) fails the entire GET, never a partial page.
    total = s.scalar(select(func.count()).select_from(records.subquery()))
    rows = (
        s.execute(
            page.order_by(
                VerificationLaunchFact.created_at.desc(), VerificationLaunchFact.id.desc()
            ).limit(page_size + 1)
        )
        .mappings()
        .all()
    )
    entries = [_entry(row, ctx, as_of) for row in rows]
    visible = entries[:page_size]
    return {
        "version": VERSION,
        "principal_id": str(ctx.requester_id),
        "as_of": as_of.isoformat(),
        "total_records": total,
        "items": visible,
        "next_cursor": visible[-1]["id"] if len(entries) > page_size else None,
    }
