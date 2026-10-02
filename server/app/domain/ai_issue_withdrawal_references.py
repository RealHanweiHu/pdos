"""Read-only incoming-reference guard; caller owns authorization and object locks.

Issue/case mutation checks belong to the withdrawal service. Here every canonical
Issue FK is inspected, including historical links (NCR links also protect CAPA).
Known polymorphic contracts and FMEA/change/knowledge references are explicit.
All remaining tenant-scoped JSON is checked for exact UUID tokens, including keys,
full object snapshots in Gate/reports/exports/handoff, Finding and knowledge data.
An unclassified token is a reason to review, never proof that withdrawal is safe.

A consumer may belong to a different project than the source Issue. Reference
queries therefore bind the tenant and exact Issue identity; project restrictions
come only from the actual foreign key, never the consumer project. This also
protects shared source_project_id projections and cross-project JSON snapshots.
No payload, table name or another project's content leaves this helper. Queries
are EXISTS over whole relations, batched only by statement count, never rows.
This is not a free-text/link crawler: prose mentioning an Issue without a stored
structured identity cannot establish a machine-verifiable reference.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Connection,
    String,
    Table,
    Uuid,
    and_,
    cast,
    exists,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import Select

from app.db.schema import metadata, tables

BUSINESS_REFERENCE = "ISSUE_BUSINESS_REFERENCE"
UNCLASSIFIED_REFERENCE = "ISSUE_UNCLASSIFIED_REFERENCE"
SCOPE_UNKNOWN = "ISSUE_REFERENCE_SCOPE_UNKNOWN"
_BATCH_SIZE = 24

# Actual discriminators used by their readers, rather than client-supplied origin.
_POLYMORPHIC = (
    ("tasks", "source_entity_id", "source_entity", "issues"),
    ("risks", "source_entity_id", "source_entity", "issue"),
    ("meeting_agenda_items", "source_entity_id", "source_kind", "issue"),
    ("knowledge_candidate_jobs", "source_id", "source_kind", "issue"),
    ("portfolio_escalations", "source_id", "source_kind", "severe_issue"),
    ("events", "entity_id", "entity", "issue"),
    ("audit_log", "entity_id", "entity", "issue"),
)
_IDENTITY_COLUMNS = frozenset(
    (
        "entity_id",
        "source_entity_id",
        "source_id",
        "target_id",
        "object_id",
        "reference_id",
        "subject_id",
    )
)


def _identity(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def _scope(t: Table, tenant: UUID, project: UUID) -> list[Any]:
    # Tables without project_id are tenant-owned histories (e.g. meeting agenda).
    predicates: list[Any] = [t.c.tenant_id == tenant]
    if "project_id" in t.c:
        predicates.append(t.c.project_id == project)
    return predicates


def _reference_scope(t: Table, tenant: UUID) -> list[Any]:
    # Exact Issue identity determines the source. A consumer's project_id (or
    # recipient_project_id) is not necessarily the source project. Only stable
    # reason codes leave this tenant-wide existence check, never row contents.
    return [t.c.tenant_id == tenant]


def _exclusions(
    t: Table, tenant: UUID, project: UUID, issue: UUID, app: Mapping[str, Any]
) -> list[Any]:
    if t is tables.issues:
        return [t.c.id != issue]
    if t is tables.ai_issue_applications:
        return [t.c.id != app["id"]]
    if t is tables.test_cases:
        receipt = app.get("receipt")
        after = receipt.get("source_case_after") if isinstance(receipt, Mapping) else None
        case_id = _identity(after.get("id")) if isinstance(after, Mapping) else None
        return [t.c.id != case_id] if case_id else []
    own_events = [
        app[key]
        for key in ("issue_event_row_id", "output_event_row_id")
        if app.get(key) is not None
    ]
    if t is tables.events:
        return [t.c.id.not_in(own_events)] if own_events else []
    if t is tables.audit_log and own_events:
        e = tables.events
        own_event_names = select(e.c.event_id).where(
            *_scope(e, tenant, project), e.c.id.in_(own_events)
        )
        return [or_(t.c.event_id.is_(None), t.c.event_id.not_in(own_event_names))]
    return []


def _probe(t: Table, predicates: list[Any], condition: Any, reason: str) -> Select[Any]:
    return select(literal(reason).label("reason")).where(
        exists(select(1).select_from(t).where(*predicates, condition))
    )


def _queries(
    tenant: UUID, project: UUID, issue: UUID, app: Mapping[str, Any]
) -> tuple[list[Select[Any]], list[Select[Any]]]:
    exact: list[Select[Any]] = []
    uncertain: list[Select[Any]] = []
    values = {"tenant_id": tenant, "project_id": project, "id": issue}
    for t in sorted(metadata.tables.values(), key=lambda item: item.fullname):
        foreign = [fk for fk in t.foreign_key_constraints if fk.referred_table is tables.issues]
        # A future reference without a safely bindable tenant cannot be cleared.
        if "tenant_id" not in t.c:
            if foreign:
                uncertain.append(select(literal(SCOPE_UNKNOWN).label("reason")))
            continue
        scope = _reference_scope(t, tenant) + _exclusions(t, tenant, project, issue, app)
        for fk in foreign:
            if any(element.column.name not in values for element in fk.elements):
                uncertain.append(select(literal(SCOPE_UNKNOWN).label("reason")))
                continue
            exact.append(
                _probe(
                    t,
                    scope,
                    and_(
                        *(element.parent == values[element.column.name] for element in fk.elements)
                    ),
                    BUSINESS_REFERENCE,
                )
            )
        # Unbound polymorphic UUIDs must not silently fall through when a new
        # business type is added. Known contracts are prioritized below.
        unknown_ids = [
            col == issue
            for col in t.c
            if isinstance(col.type, Uuid)
            and not col.foreign_keys
            and (col.name in _IDENTITY_COLUMNS or col.name.endswith("issue_id"))
        ]
        if unknown_ids:
            uncertain.append(_probe(t, scope, or_(*unknown_ids), UNCLASSIFIED_REFERENCE))
        json_columns = [col for col in t.c if isinstance(col.type, JSON)]
        if json_columns:
            # Quoted exact JSON string/key tokens; no substring UUID match or
            # arbitrary later activity. Canonical source_key="issue:<uuid>"
            # is an actual structured source identity too. Case-insensitive
            # matching preserves equivalent UUID spellings in imported JSON.
            pattern = '"(?:issue:)?' + str(issue) + '"'
            uncertain.append(
                _probe(
                    t,
                    scope,
                    or_(*(cast(col, String).op("~*")(pattern) for col in json_columns)),
                    UNCLASSIFIED_REFERENCE,
                )
            )

    for name, identity, discriminator, kind in _POLYMORPHIC:
        t = getattr(tables, name)
        exact.append(
            _probe(
                t,
                _reference_scope(t, tenant) + _exclusions(t, tenant, project, issue, app),
                and_(t.c[identity] == issue, t.c[discriminator] == kind),
                BUSINESS_REFERENCE,
            )
        )

    for t, col, key, ref in (
        (tables.fmea_versions, "body", "references", {"kind": "issue", "id": str(issue)}),
        (
            tables.change_impact_scope_versions,
            "snapshot",
            "items",
            {"kind": "issue", "id": str(issue)},
        ),
        (tables.decisions, "evidence_refs", None, {"kind": "issue", "reference": str(issue)}),
    ):
        field = t.c[col][key] if key else t.c[col]
        exact.append(
            _probe(
                t,
                _reference_scope(t, tenant),
                cast(field, JSONB).contains([ref]),
                BUSINESS_REFERENCE,
            )
        )

    # Real executions on an associated test case are downstream business
    # records, including those on the source case which itself is exempt.
    r, case = tables.test_runs, tables.test_cases
    linked: Any = exists(
        select(1)
        .select_from(case)
        .where(
            *_scope(case, tenant, project),
            case.c.id == r.c.test_case_id,
            case.c.related_issue_id == issue,
        )
    )
    receipt = app.get("receipt")
    after = receipt.get("source_case_after") if isinstance(receipt, Mapping) else None
    source_case = _identity(after.get("id")) if isinstance(after, Mapping) else None
    if source_case is not None:
        # The source case may already have executions which led to this Issue.
        # Only later creation/edit is downstream consumption of that association.
        linked = and_(
            linked,
            or_(
                r.c.test_case_id != source_case,
                r.c.created_at > app["created_at"],
                r.c.updated_at > app["created_at"],
            ),
        )
    exact.append(_probe(r, _reference_scope(r, tenant), linked, BUSINESS_REFERENCE))
    return exact, uncertain


def withdrawal_reference(
    c: Connection, tenant: UUID, project: UUID, issue_id: UUID, application: Mapping[str, Any]
) -> str | None:
    """Return a stable blocking code, or None after checking every scoped query.

    Only trusted persisted application rows may be passed. The caller must check
    snapshots and authorize first; no client request controls own-row exclusions.
    Database failures propagate, so an incomplete read never permits withdrawal.
    """
    if (
        not isinstance(application.get("created_at"), datetime)
        or _identity(application.get("id")) is None
        or _identity(application.get("tenant_id")) != tenant
        or _identity(application.get("project_id")) != project
        or _identity(application.get("issue_id")) != issue_id
    ):
        return SCOPE_UNKNOWN
    for queries in _queries(tenant, project, issue_id, application):
        for start in range(0, len(queries), _BATCH_SIZE):
            batch = queries[start : start + _BATCH_SIZE]
            reason = c.execute(union_all(*batch).limit(1)).scalar_one_or_none()
            if reason is not None:
                return str(reason)
    return None
