"""Rollback-only SQL guard probes against explicitly selected synthetic Wave15 rows.

This tool does not run on import. Root must run it after the selected successful
local demonstration exists; it neither seeds business facts nor creates receipts.
"""

import argparse
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for
from pdos_next.domain.change_control.rules import compute_impact
from pdos_next.domain.change_execution.models import (
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.quality_execution.models import (
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyCurrent,
    QualityPolicyFact,
)
from pdos_next.models import Product, Receipt
from pdos_next.schemas.change_control.contracts import GraphSnapshot
from pdos_next.service import digest
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError

IMMUTABLE = "fixed business snapshots are immutable"
NO_RECEIPT = "Quality/change write requires exactly one named receipt, audit and event"
GRAPH_BINDING = "Impact successor requires its exact unexpired committed graph capture"
MERGE_ALIAS = "Merge requires all stable failure aliases to retain their exact target"
POINTER_ERRORS = {
    QualityIssueCurrent: (
        "Issue current requires its exact scoped version",
        "Issue current requires a continuous exact predecessor",
    ),
    QualityPolicyCurrent: (
        "Policy current requires its exact scoped fact",
        "Policy pointer requires a continuous exact predecessor",
    ),
    ChangeCurrent: (
        "Change current requires its exact scoped version",
        "Change pointer requires a continuous exact predecessor",
    ),
}
SAFE_ERRORS = {IMMUTABLE, NO_RECEIPT, GRAPH_BINDING, MERGE_ALIAS} | {
    message for messages in POINTER_ERRORS.values() for message in messages
}
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave15-20261002"


class ProbeFailure(RuntimeError):
    """Safe diagnostic code only; database messages and URLs are never echoed."""


class ProbeSkip(RuntimeError):
    pass


@dataclass(frozen=True)
class Selection:
    tenant: UUID
    product: UUID
    issue: UUID
    change: UUID
    policy: UUID | None
    capture: UUID | None
    merge_source: UUID | None


def _environment_identity(state):
    return (state["marker"], state["container_id"], state["port"], digest(state["admin_url"]))


def _reverify(expected):
    state = verified(read_state())
    if _environment_identity(state) != expected:
        raise ProbeFailure("TARGET_CHANGED")
    return state


def _row(connection, model, **filters):
    statement = select(model.__table__)
    for key, value in filters.items():
        statement = statement.where(model.__table__.c[key] == value)
    rows = connection.execute(statement.limit(2)).mappings().all()
    if len(rows) != 1:
        raise ProbeFailure("SELECTED_ROW_MISSING_OR_AMBIGUOUS")
    return copy.deepcopy(dict(rows[0]))


def _scoped(connection, model, choice, **filters):
    return _row(connection, model, tenant_id=choice.tenant, product_id=choice.product, **filters)


def _receipt(connection, row, subject_type, *, operation=None):
    receipt = _row(
        connection,
        Receipt,
        tenant_id=row["tenant_id"],
        product_id=row["product_id"],
        subject_id=row["id"],
        subject_revision=row["revision"],
        operation=operation or row["operation"],
        subject_type=subject_type,
    )
    if receipt["run_id"] is not None or receipt["actor_id"] != receipt["requester_id"]:
        raise ProbeFailure("SELECTED_RECEIPT_NOT_NAMED_LOCAL_WRITE")


def _fixture(connection, choice):
    issue_pointer = _scoped(connection, QualityIssueCurrent, choice, issue_id=choice.issue)
    issue = _scoped(connection, QualityIssueVersion, choice, id=issue_pointer["issue_version_id"])
    change_pointer = _scoped(connection, ChangeCurrent, choice, change_id=choice.change)
    change = _scoped(connection, ChangeRequestVersion, choice, id=change_pointer["version_id"])
    if (
        issue["project_id"] != change["project_id"]
        or issue["revision"] != issue_pointer["issue_revision"]
        or change["revision"] != change_pointer["revision"]
    ):
        raise ProbeFailure("SELECTED_SCOPE_OR_CURRENT_MISMATCH")
    _receipt(connection, issue, "quality_issue")
    _receipt(connection, change, "change_request")
    policy_id = choice.policy
    if policy_id is None and issue["policy_snapshot"] is not None:
        policy_id = UUID(issue["policy_snapshot"]["id"])
    policy = _scoped(connection, QualityPolicyFact, choice, id=policy_id) if policy_id else None
    policy_pointer = (
        _scoped(connection, QualityPolicyCurrent, choice, fact_id=policy_id) if policy_id else None
    )
    if policy and (
        policy["project_id"] != issue["project_id"] or policy["purpose"] != issue["purpose"]
    ):
        raise ProbeFailure("SELECTED_POLICY_SCOPE_MISMATCH")
    if policy:
        _receipt(connection, policy, "quality_policy_fact", operation="quality.policy.import")
    capture_id = choice.capture
    if capture_id is None and change["request_snapshot"]["assessments"]:
        capture_id = UUID(change["request_snapshot"]["assessments"][-1]["graph"]["id"])
    capture = _scoped(connection, ChangeGraphCapture, choice, id=capture_id) if capture_id else None
    if capture and (
        capture["project_id"] != change["project_id"] or capture["change_id"] != choice.change
    ):
        raise ProbeFailure("SELECTED_CAPTURE_SCOPE_MISMATCH")
    merge_pointer = (
        _scoped(connection, QualityIssueCurrent, choice, issue_id=choice.merge_source)
        if choice.merge_source
        else None
    )
    merge_source = (
        _scoped(connection, QualityIssueVersion, choice, id=merge_pointer["issue_version_id"])
        if merge_pointer
        else None
    )
    if merge_source:
        _receipt(connection, merge_source, "quality_issue")
    return {
        "issue": issue,
        "issue_pointer": issue_pointer,
        "change": change,
        "change_pointer": change_pointer,
        "policy": policy,
        "policy_pointer": policy_pointer,
        "capture": capture,
        "merge_source": merge_source,
        "merge_source_pointer": merge_pointer,
    }


def _baseline(connection, choice, fixture):
    checks = []
    for key, model in (
        ("issue", QualityIssueVersion),
        ("issue_pointer", QualityIssueCurrent),
        ("policy", QualityPolicyFact),
        ("policy_pointer", QualityPolicyCurrent),
        ("change", ChangeRequestVersion),
        ("change_pointer", ChangeCurrent),
        ("capture", ChangeGraphCapture),
        ("merge_source", QualityIssueVersion),
        ("merge_source_pointer", QualityIssueCurrent),
    ):
        if fixture[key] is not None:
            checks.append(_scoped(connection, model, choice, id=fixture[key]["id"]))
    checks.append(_row(connection, Product, tenant_id=choice.tenant, id=choice.product))
    return digest(checks)


def _update(connection, model, row, **values):
    affected = connection.execute(
        update(model.__table__)
        .where(model.id == row["id"], model.tenant_id == row["tenant_id"])
        .values(**values)
    ).rowcount
    if affected != 1:
        raise ProbeFailure("SELECTED_UPDATE_NOT_ONE_ROW")


def _insert(connection, model, row):
    connection.execute(insert(model.__table__).values(**row))


def _unpaired_issue(connection, fixture):
    row = copy.deepcopy(fixture["issue"])
    row.update(
        id=uuid4(),
        issue_id=uuid4(),
        revision=1,
        previous_issue_version_id=None,
        previous_revision=None,
        status="open",
        operation="quality.issue.create",
        intent_digest=digest(str(uuid4())),
        created_at=datetime.now(UTC),
    )
    row["issue_snapshot"].update(id=str(row["issue_id"]), revision=1, status="open")
    row["snapshot_sha256"] = digest(row["issue_snapshot"])
    _insert(connection, QualityIssueVersion, row)
    _insert(
        connection,
        QualityIssueCurrent,
        {
            "id": uuid4(),
            "tenant_id": row["tenant_id"],
            "product_id": row["product_id"],
            "project_id": row["project_id"],
            "issue_id": row["issue_id"],
            "issue_version_id": row["id"],
            "issue_revision": 1,
            "epoch": 1,
            "created_at": row["created_at"],
        },
    )


def _unpaired_change(connection, fixture):
    row = copy.deepcopy(fixture["change"])
    row.update(
        id=uuid4(),
        change_id=uuid4(),
        revision=1,
        previous_version_id=None,
        previous_revision=None,
        status="draft",
        operation="change.request.create",
        intent_digest=digest(str(uuid4())),
        created_at=datetime.now(UTC),
    )
    row["request_snapshot"].update(
        id=str(row["change_id"]), revision=1, status="draft", assessments=[], orders=[]
    )
    row["request_sha256"] = digest(row["request_snapshot"])
    _insert(connection, ChangeRequestVersion, row)
    _insert(
        connection,
        ChangeCurrent,
        {
            "id": uuid4(),
            "tenant_id": row["tenant_id"],
            "product_id": row["product_id"],
            "change_id": row["change_id"],
            "version_id": row["id"],
            "revision": 1,
            "created_at": row["created_at"],
        },
    )


def _graph_basis(connection, fixture):
    if fixture["capture"] is None:
        raise ProbeSkip("NO_SELECTED_GRAPH_CAPTURE")
    prior, at = fixture["change"], datetime.now(UTC)
    capture = copy.deepcopy(fixture["capture"])
    graph = capture["graph_snapshot"]
    capture.update(
        id=uuid4(),
        change_version_id=prior["id"],
        change_revision=prior["revision"],
        capture_key=f"rollback-atom:{uuid4()}",
        input_digest=digest(str(uuid4())),
        created_at=at,
        expires_at=at + timedelta(minutes=1),
    )
    graph.update(
        id=str(capture["id"]),
        captured_at=at.isoformat(),
        expires_at=capture["expires_at"].isoformat(),
    )
    capture["graph_sha256"] = digest(graph)
    _insert(connection, ChangeGraphCapture, capture)
    assessment = compute_impact(GraphSnapshot.model_validate(graph), prior["revision"], ())
    value = assessment.model_dump(mode="json")
    # Preserve the real capture identity and scope, altering only its fixed clock
    # in the version's graph. This must hit graph equality, not a duplicate key.
    value["graph"]["captured_at"] = (at + timedelta(microseconds=1)).isoformat()
    row = copy.deepcopy(prior)
    row.update(
        id=uuid4(),
        revision=prior["revision"] + 1,
        previous_version_id=prior["id"],
        previous_revision=prior["revision"],
        status="analysis",
        operation="change.impact.compute",
        intent_digest=digest(str(uuid4())),
        created_at=at,
    )
    row["request_snapshot"].update(revision=row["revision"], status="analysis")
    row["request_snapshot"]["assessments"].append(value)
    row["request_sha256"] = digest(row["request_snapshot"])
    _insert(connection, ChangeRequestVersion, row)
    _update(
        connection,
        ChangeCurrent,
        fixture["change_pointer"],
        version_id=row["id"],
        revision=row["revision"],
    )


def _missing_merge_alias(connection, fixture, choice):
    if choice.merge_source is None:
        raise ProbeSkip("NO_EXPLICIT_MERGE_SOURCE")
    pointer, source = fixture["merge_source_pointer"], fixture["merge_source"]
    target = fixture["issue"]
    if (
        source["issue_id"] == target["issue_id"]
        or any(source[key] != target[key] for key in ("project_id", "purpose", "visibility"))
        or set(source["issue_snapshot"]["audience"]) != set(target["issue_snapshot"]["audience"])
        or any(
            row["status"] not in {"open", "triaged"}
            or row["issue_snapshot"].get("capa")
            or row["issue_snapshot"].get("root_cause")
            or row["issue_snapshot"].get("merged_into")
            for row in (source, target)
        )
    ):
        raise ProbeSkip("SELECTED_ISSUES_NOT_LEGAL_MERGE_BASELINE")
    failures = target["issue_snapshot"]["failures"] + source["issue_snapshot"]["failures"]
    if len({f["identity"] for f in failures}) != len(failures):
        raise ProbeSkip("MERGE_FAILURE_IDENTITIES_NOT_DISJOINT")
    for original in (target, source):
        maps = (
            connection.execute(
                select(QualityFailureMap.__table__).where(
                    QualityFailureMap.tenant_id == choice.tenant,
                    QualityFailureMap.product_id == choice.product,
                    QualityFailureMap.project_id == original["project_id"],
                    QualityFailureMap.issue_id == original["issue_id"],
                )
            )
            .mappings()
            .all()
        )
        if {digest(m["failure"]) for m in maps} != {
            digest(f) for f in original["issue_snapshot"]["failures"]
        }:
            raise ProbeSkip("MERGE_BASELINE_ALIAS_LEDGER_NOT_EXACT")
    intent, at = digest(str(uuid4())), datetime.now(UTC)
    inputs = {
        "issue_id": str(target["issue_id"]),
        "expected_issue_revision": target["revision"],
        "sources": [{"id": str(source["issue_id"]), "revision": source["revision"]}],
        "reason": "Rollback-only SQL atom probe; no professional decision",
    }
    for original, current in (
        (target, fixture["issue_pointer"]),
        (source, pointer),
    ):
        row = copy.deepcopy(original)
        row.update(
            id=uuid4(),
            revision=original["revision"] + 1,
            previous_issue_version_id=original["id"],
            previous_revision=original["revision"],
            operation="quality.issue.merge",
            writer_id=target["writer_id"],
            intent_digest=intent,
            input_snapshot=inputs,
            created_at=at,
        )
        row["issue_snapshot"]["revision"] = row["revision"]
        if original is target:
            row["issue_snapshot"]["failures"] = sorted(failures, key=lambda f: f["identity"])
        else:
            row["issue_snapshot"]["merged_into"] = str(target["issue_id"])
        row["snapshot_sha256"] = digest(row["issue_snapshot"])
        _insert(connection, QualityIssueVersion, row)
        _update(
            connection,
            QualityIssueCurrent,
            current,
            issue_version_id=row["id"],
            issue_revision=row["revision"],
            epoch=current["epoch"] + 1,
        )
    # Deliberately omit source alias movement. No receipts are fabricated; this
    # specific guard must fire before the missing common-group check.


def _diagnostic(error):
    original = error.orig
    diag = getattr(original, "diag", None)
    message = getattr(diag, "message_primary", None)
    constraint = getattr(diag, "constraint_name", None)
    if not isinstance(constraint, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", constraint):
        constraint = None
    return {
        "sqlstate": getattr(original, "sqlstate", None),
        "error_type": type(original).__name__,
        "guard": message if message in SAFE_ERRORS else None,
        "constraint": constraint,
    }


def _probe(engine, environment_id, choice, name, action, expected):
    _reverify(environment_id)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SET LOCAL lock_timeout='5s'"))
            connection.execute(text("SET LOCAL statement_timeout='15s'"))
            connection.execute(
                text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
                {"tenant": str(choice.tenant)},
            )
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != "next_0023":
                raise ProbeFailure("WRONG_SCHEMA_HEAD")
            if connection.scalar(text("SELECT current_database()")) != "pdos_test":
                raise ProbeFailure("WRONG_DATABASE")
            connection.execute(
                select(Product.id)
                .where(Product.tenant_id == choice.tenant, Product.id == choice.product)
                .with_for_update()
            ).scalar_one()
            fixture = _fixture(connection, choice)
            before = _baseline(connection, choice, fixture)
            savepoint = connection.begin_nested()
            result = {"case": name, "expected_guard": expected}
            try:
                connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                action(connection, fixture)
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                result["status"] = "unexpectedly_accepted"
            except ProbeSkip as error:
                result.update(status="skipped", reason=error.args[0])
            except DBAPIError as error:
                observed = _diagnostic(error)
                result.update(observed)
                result["status"] = (
                    "rejected_expected_guard"
                    if observed["sqlstate"] == "P0001" and observed["guard"] == expected
                    else "rejected_unexpected_boundary"
                )
            finally:
                savepoint.rollback()
            if _baseline(connection, choice, fixture) != before:
                raise ProbeFailure("SELECTED_RETAINED_ROWS_CHANGED")
            result["savepoint_rolled_back"] = True
            result["retained_rows_and_product_epoch_unchanged"] = True
        finally:
            transaction.rollback()
    _reverify(environment_id)
    result["outer_transaction_rolled_back"] = True
    return result


def _cases(choice):
    cases = []
    for key, model in (
        ("issue", QualityIssueVersion),
        ("policy", QualityPolicyFact),
        ("change", ChangeRequestVersion),
        ("capture", ChangeGraphCapture),
    ):

        def immutable(connection, fixture, key=key, model=model):
            if fixture[key] is None:
                raise ProbeSkip(
                    "NO_SELECTED_POLICY" if key == "policy" else "NO_SELECTED_GRAPH_CAPTURE"
                )
            values = (
                {"reason": "rollback-only immutable probe"}
                if "reason" in model.__table__.columns
                else {"intent_digest": digest("rollback-only immutable probe")}
            )
            _update(connection, model, fixture[key], **values)

        cases.append((f"{key}.immutable", immutable, IMMUTABLE))
    for key, model, revision in (
        ("issue_pointer", QualityIssueCurrent, "issue_revision"),
        ("policy_pointer", QualityPolicyCurrent, "fact_revision"),
        ("change_pointer", ChangeCurrent, "revision"),
    ):

        def jump(connection, fixture, key=key, model=model, revision=revision):
            if fixture[key] is None:
                raise ProbeSkip("NO_SELECTED_POLICY")
            _update(connection, model, fixture[key], **{revision: fixture[key][revision] + 2})

        def fake_cas(connection, fixture, key=key, model=model):
            if fixture[key] is None:
                raise ProbeSkip("NO_SELECTED_POLICY")
            _update(connection, model, fixture[key], id=uuid4())

        cases.append((f"{key}.invalid_revision_jump", jump, POINTER_ERRORS[model][0]))
        cases.append((f"{key}.forged_pointer_identity", fake_cas, POINTER_ERRORS[model][1]))
    cases.extend(
        [
            ("issue.unpaired_version_and_current", _unpaired_issue, NO_RECEIPT),
            ("change.unpaired_version_and_current", _unpaired_change, NO_RECEIPT),
            ("change.fixed_graph_basis", _graph_basis, GRAPH_BINDING),
            (
                "issue.merge_without_alias_moves",
                lambda connection, fixture: _missing_merge_alias(connection, fixture, choice),
                MERGE_ALIAS,
            ),
        ]
    )
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("tenant", "product", "issue", "change"):
        parser.add_argument(f"--{field}", type=UUID, required=True)
    for field in ("policy", "capture", "merge-source"):
        parser.add_argument(f"--{field}", type=UUID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    choice = Selection(
        args.tenant,
        args.product,
        args.issue,
        args.change,
        args.policy,
        args.capture,
        args.merge_source,
    )
    output = args.output or REPORT / f"atom-probes-{uuid4()}.json"
    if (
        output.resolve().parent != REPORT.resolve()
        or output.exists()
        or not output.name.startswith("atom-probes-")
        or output.suffix != ".json"
    ):
        raise ProbeFailure("OUTPUT_MUST_BE_FRESH_WAVE15_EVIDENCE")
    summary = {
        "nature": "synthetic_local_rollback_sql_guards_not_professional_qualification",
        "selection": {key: str(value) if value else None for key, value in vars(choice).items()},
        "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "status": "incomplete",
        "cases": [],
        "coverage_limits": [
            "No positive business facts, receipts, authority, source reads or releases are created",
            "Empty/missing optional graph or legally mergeable source is an explicit skip",
            "Extra merge Version and full end-to-end authority/rollback use transaction tests",
            "Observed unrelated errors, including duplicate PK, do not count as expected rejection",
        ],
    }
    engine = None
    try:
        state = verified(read_state())
        environment_id = _environment_identity(state)
        engine = engine_for(state["admin_url"])
        for name, action, expected in _cases(choice):
            result = _probe(engine, environment_id, choice, name, action, expected)
            summary["cases"].append(result)
            if result["status"] not in {"rejected_expected_guard", "skipped"}:
                raise ProbeFailure("PROBE_NOT_REJECTED_BY_EXPECTED_GUARD")
        summary["status"] = (
            "completed_with_explicit_skips"
            if any(case["status"] == "skipped" for case in summary["cases"])
            else "completed"
        )
    except Exception as error:
        summary["failure"] = {
            "type": type(error).__name__,
            "code": error.args[0] if isinstance(error, ProbeFailure) else "UNEXPECTED_SAFE_ABORT",
        }
        if isinstance(error, DBAPIError):
            summary["failure"].update(_diagnostic(error))
    finally:
        if engine is not None:
            engine.dispose()
        with output.open("x") as stream:
            stream.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(f"Rollback probe report: {output.name}; status={summary['status']}")
    return 0 if summary["status"].startswith("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
