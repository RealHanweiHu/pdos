"""Root-run stored candidate closeout; inert on import and never writes business data.

Only marked target verification and SELECTs in a rolled-back READ ONLY snapshot
are performed. Stored proof/group checks do not attest fresh seven-owner gates,
reconstruct the false-to-true hook, or certify effectiveness/closure/production.
The sole output is one exclusively created, bounded, credential-free report.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
MARKER = "916f950f-2d2b-405d-b809-c15db75dc20c"
OPERATION = "quality.capa.verification.candidate.record"
SUBJECT = "capa_verification_candidate"
EVENT = "CapaVerificationCandidateRecorded"
SHA = re.compile(r"[0-9a-f]{64}")
NULLS = ("applicable", "independently_verified", "observation_complete")
# Actual names in the saved head25 baseline/model registry. Common/authority/
# Artifact tables have legitimate additions and are not called unchanged.
RETAINED = (
    "quality_issue_versions",
    "quality_current_issues",
    "capa_remediation_links",
    "builds",
    "build_starts",
    "build_current_execution_assessments",
    "build_current_authorizations",
    "actual_configurations",
    "build_lots",
    "sample_units",
    "verification_formal_requests",
    "verification_current_formal_requests",
    "verification_run_identities",
    "verification_run_versions",
    "verification_current_runs",
    "verification_launch_facts",
    "test_measurements",
    "test_result_projections",
    "test_result_actions",
    "operational_material_holds",
    "operational_resource_occupancies",
    "test_resource_reservations",
    "sample_usage_sentinels",
    "sample_run_usages",
)


class Stop(RuntimeError):
    """Fixed diagnostic code, never raw SQL/private exception text."""


def require(value, code):
    if not value:
        raise Stop(code)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aware(value):
    at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    require(at.tzinfo is not None and at.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
    return at.astimezone(UTC)


def public_json(path):
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 8_388_608,
        "BOUNDED_REGULAR_EVIDENCE_REQUIRED",
    )

    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "DUPLICATE_EVIDENCE_FIELD")
            result[key] = value
        return result

    def constant(_):
        raise Stop("NONFINITE_EVIDENCE")

    return json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=constant)


def manifest(path, base):
    data = public_json(path)
    entries = data.get("files")
    require(isinstance(entries, dict) and 1 <= len(entries) <= 1000, "SOURCE_MANIFEST_REQUIRED")
    for name, expected in entries.items():
        relative = Path(name)
        require(
            isinstance(expected, str)
            and SHA.fullmatch(expected)
            and not relative.is_absolute()
            and ".." not in relative.parts,
            "SOURCE_MANIFEST_ENTRY_INVALID",
        )
        actual = base / relative
        require(
            actual.is_file() and not actual.is_symlink() and file_sha(actual) == expected,
            "SOURCE_MANIFEST_MISMATCH",
        )
    return {"file": path.name, "sha256": file_sha(path), "files": len(entries), "matches": True}


class Reader:
    """Core SELECT only: no ORM Session, flush, owner callback or new connection."""

    def __init__(self, connection, tables, tenant, product):
        self.c, self.tables, self.tenant, self.product = connection, tables, tenant, product

    def rows(self, name, *, limit=2, **filters):
        from sqlalchemy import select

        require(type(limit) is int and 1 <= limit <= 21, "BOUNDED_GROUP_READ_REQUIRED")
        table = self.tables[name]
        query = select(table)
        if "tenant_id" in table.c:
            query = query.where(table.c.tenant_id == self.tenant)
        if "product_id" in table.c:
            query = query.where(table.c.product_id == self.product)
        for key, value in filters.items():
            require(key in table.c, "ACTUAL_COLUMN_REQUIRED")
            query = query.where(table.c[key] == value)
        return [dict(row) for row in self.c.execute(query.limit(limit)).mappings()]

    def one(self, name, **filters):
        rows = self.rows(name, **filters)
        require(len(rows) == 1, "EXACT_COMMON_GROUP_ROW_REQUIRED")
        return rows[0]


def caller(reader, actor, project):
    reader.one("products", id=reader.product)
    person = reader.one("principals", id=actor)
    scope = reader.one("projects", id=project)
    grant = reader.one("grants", principal_id=actor)
    at = datetime.now(UTC)  # after the last actual Grant SELECT
    require(
        person["kind"] == "human"
        and person["active"] is True
        and aware(grant["expires_at"]) > at
        and scope["status"] == "active"
        and (scope["visibility"] == "product" or scope["owner_id"] == actor),
        "CURRENT_CALLER_PROJECT_ACCESS_REQUIRED",
    )
    return at


def issue_origin(reader, row, stable):
    from pdos_next.domain.capa_effectiveness import anchor
    from pdos_next.schemas.quality_issues.contracts import Issue
    from pdos_next.service import digest

    origin = stable.origin
    require(
        row["issue_revision"] == 6
        and type(row["issue_revision"]) is int
        and origin.ref.revision == 6
        and origin.ref.id == row["issue_version_id"],
        "EXACT_COMPLETED_ISSUE6_REQUIRED",
    )
    fixed = reader.one(
        "quality_issue_versions",
        id=origin.ref.id,
        project_id=row["project_id"],
        issue_id=row["issue_id"],
        revision=6,
    )
    before = reader.one("quality_issue_versions", id=fixed["previous_issue_version_id"], revision=5)
    issue = Issue.model_validate(fixed["issue_snapshot"])
    actual = anchor.IssueVersionEvidence(
        ref={"id": fixed["id"], "revision": 6, "snapshot_sha256": fixed["snapshot_sha256"]},
        previous_ref={
            "id": before["id"],
            "revision": before["revision"],
            "snapshot_sha256": before["snapshot_sha256"],
        },
        scope=issue.scope,
        issue_id=fixed["issue_id"],
        purpose=fixed["purpose"],
        owner_id=fixed["owner_id"],
        writer_id=fixed["writer_id"],
        visibility=fixed["visibility"],
        nature=row["nature"],
        operation=fixed["operation"],
        domain_intent_sha256=fixed["intent_digest"],
        created_at=fixed["created_at"],
        issue=issue,
        sources=fixed["sources"],
        required_source_read_set=fixed["required_source_read_set"],
        source_basis=fixed["source_basis"]["artifact_sources"],
        input_snapshot=fixed["input_snapshot"],
        authority_snapshot=fixed["authority_snapshot"],
        policy_snapshot=fixed["policy_snapshot"],
        persisted_source_basis=fixed["source_basis"],
    )
    current = reader.one(
        "quality_current_issues", project_id=row["project_id"], issue_id=row["issue_id"]
    )
    require(
        origin == actual
        and fixed["snapshot_sha256"] == digest(fixed["issue_snapshot"])
        and (current["issue_version_id"], current["issue_revision"]) == (fixed["id"], 6)
        and issue.status == "awaiting_verification"
        and fixed["operation"] == "quality.capa.actions.complete"
        and issue.capa.id == row["capa_id"]
        and issue.capa.effectiveness is None
        and not issue.capa.effectiveness_history
        and issue.closure is None,
        "ORIGIN_CURRENT_OR_UNDECIDED_CAPA_CHANGED",
    )
    return fixed, issue


def original_failures(reader, stable):
    """Exact saved Run/value/projection comparison; no original-byte IO attestation."""
    from pdos_next.domain.verification import rules
    from pdos_next.service import digest
    from sqlalchemy import or_, select

    found = []
    require(len(stable.failures) <= 1000, "FIXED_FAILURE_INVENTORY_BOUND_EXCEEDED")
    for item in stable.failures:
        result, run = item.result, item.result.verified.run
        row = reader.one(
            "verification_run_versions",
            id=result.run_version_id,
            project_id=result.scope.project_id,
            run_id=run.id,
            revision=result.run_revision,
        )
        measurement = reader.one("test_measurements", id=result.measurement_id, run_id=run.id)
        projected = reader.one(
            "test_result_projections",
            id=result.projection_id,
            run_id=run.id,
            revision=result.projection_revision,
        )
        value = next(m for m in run.measurements if m.id == result.measurement_id)
        calculated, aggregate = rules.compute_results(
            run, run.measurements, final=run.final_result is not None
        )
        require(
            row["run_snapshot"] == run.model_dump(mode="json")
            and row["snapshot_sha256"] == digest(row["run_snapshot"])
            and measurement["measurement"] == value.model_dump(mode="json")
            and measurement["measurement_sha256"] == digest(measurement["measurement"])
            and projected["basis_sha256"] == result.basis_sha256
            and projected["rules_version"] == result.rules_version
            and projected["rules_sha256"] == result.rules_sha256
            and projected["computed_results"] == [v.model_dump(mode="json") for v in calculated]
            and projected["result"] == aggregate == run.result
            and tuple(calculated) == run.computed_results,
            "FIXED_ORIGINAL_FAILURE_VALUE_OR_RULE_BASIS_CHANGED",
        )
        found.append(
            {
                "run_version_id": str(row["id"]),
                "measurement_id": str(measurement["id"]),
                "measurement_sha256": measurement["measurement_sha256"],
                "projection_id": str(projected["id"]),
                "matched_saved_value_and_projection": True,
            }
        )
    # Actual Issue family or logical Issue targets, never all product decisions.
    q, receipts = reader.tables["quality_issue_versions"], reader.tables["action_receipts"]
    versions = select(q.c.id).where(
        q.c.tenant_id == reader.tenant,
        q.c.product_id == reader.product,
        q.c.issue_id == stable.origin.issue_id,
    )
    unexpected = reader.c.execute(
        select(receipts.c.id)
        .where(
            receipts.c.tenant_id == reader.tenant,
            receipts.c.product_id == reader.product,
            receipts.c.operation.in_(("quality.capa.effectiveness.decide", "quality.issue.close")),
            or_(
                receipts.c.subject_id.in_(versions), receipts.c.subject_id == stable.origin.issue_id
            ),
        )
        .limit(1)
    ).first()
    require(unexpected is None, "UNEXPECTED_EFFECTIVENESS_OR_CLOSE_RECEIPT")
    return found


def candidate(reader, row, actor, plan):
    from pdos_next.domain.capa_effectiveness import anchor, candidate_commands
    from pdos_next.domain.capa_effectiveness.candidate_storage import CandidateInput
    from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect
    from pdos_next.domain.capa_verification.service import basis_from_issue
    from pdos_next.service import digest

    snapshot = row["candidate_snapshot"]
    require(
        row["status"] == "candidate"
        and row["result"] == "indeterminate"
        and type(row["revision"]) is int
        and row["revision"] == 1
        and all(row[key] is None for key in NULLS)
        and isinstance(snapshot, dict)
        and snapshot.get("result") == "indeterminate"
        and all(key in snapshot and snapshot[key] is None for key in NULLS),
        "CANDIDATE_THREE_EXPLICIT_NULLS_REQUIRED",
    )
    raw = row["input_snapshot"]
    require(
        isinstance(raw, dict)
        and set(raw) == {"semantic", "shared_proof", "proof_consumed_at", "stable_anchor"}
        and not {"confirmation_token", "approval_token"} & raw["semantic"].keys(),
        "EXACT_TOKEN_FREE_CANDIDATE_INPUT_REQUIRED",
    )
    body = CandidateInput.model_validate(raw)
    stable, binding, inspection = (
        body.stable_anchor,
        CandidateBinding.model_validate(row["candidate_binding"]),
        CandidateInspect.model_validate(snapshot),
    )
    payload = candidate_commands.CandidateRecordPayload.model_validate(body.semantic)
    require(candidate_commands.semantic(payload) == body.semantic, "ACTUAL_SEMANTIC_MISMATCH")
    fixed, issue = issue_origin(reader, row, stable)
    basis = binding.basis
    identity = (
        reader.tenant,
        reader.product,
        row["project_id"],
        row["issue_id"],
        row["issue_version_id"],
        6,
        row["capa_id"],
        row["purpose"],
        row["owner_id"],
        row["visibility"],
        row["nature"],
    )
    require(
        (
            basis.scope.tenant_id,
            basis.scope.product_id,
            basis.scope.project_id,
            basis.issue_id,
            basis.issue_version_id,
            basis.issue_revision,
            basis.capa_id,
            basis.purpose,
            basis.owner_id,
            basis.visibility,
            basis.nature,
        )
        == identity
        and row["owner_id"] == fixed["owner_id"]
        and row["visibility"] == fixed["visibility"]
        and payload.visibility == row["visibility"]
        and payload.reason == row["reason"]
        and row["remediation_link_id"]
        == (
            binding.remediation_link_refs[0].id if len(binding.remediation_link_refs) == 1 else None
        )
        and row["writer_id"] == actor
        and (row["visibility"] == "product" or row["owner_id"] == actor)
        and binding.basis.model_dump(mode="json") == row["basis_snapshot"],
        "EXACT_CANDIDATE_SCOPE_OWNER_AUDIENCE_REQUIRED",
    )
    sources, reads, _ = anchor.source_closure(
        row["sources"], row["required_source_read_set"], row["source_basis"]["artifact_sources"]
    )
    raw_safety = row["source_basis"]["artifact_sources"]
    wanted = {str(r.artifact_id) for r in basis.required_source_read_set}
    basis_safety = [v for v in raw_safety if v["id"] in wanted]
    reconstructed = basis_from_issue(
        SimpleNamespace(**fixed),
        issue,
        sources=basis.sources,
        reads=basis.required_source_read_set,
        source_basis=basis_safety,
    )
    require(
        reconstructed == basis
        and row["basis_sha256"] == basis.basis_sha256
        and digest(binding.model_dump(mode="json")) == row["binding_sha256"]
        and inspection.binding == binding
        and inspection.candidate_ref is None
        and inspection.inspection_sha256 == row["inspection_sha256"]
        and digest(
            inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
        )
        == row["inspection_sha256"]
        and digest(raw_safety) == inspection.source_basis_sha256
        and reads == anchor.canonical_reads(inspection.required_source_read_set)
        and set(stable.origin_required_source_read_set) <= set(reads)
        and set(stable.origin_sources) <= set(sources)
        and set(basis.required_source_read_set) <= set(reads)
        and set(basis.sources) <= set(sources),
        "COMPLETE_CANDIDATE_HASH_AND_SOURCE_BINDING_REQUIRED",
    )
    candidate_commands.check_candidate_request(payload, binding, current_issue_revision=6)
    receipt = reader.one(
        "action_receipts", subject_id=row["id"], subject_revision=1, subject_type=SUBJECT
    )
    audit = reader.one("audit_entries", receipt_id=receipt["id"])
    outbox = reader.one("outbox_events", receipt_id=receipt["id"])
    proof = reader.one("confirmations", id=body.shared_proof.id)
    key = reader.rows(
        "request_keys",
        limit=1,
        receipt_id=receipt["id"],
        actor_id=actor,
        digest=receipt["request_digest"],
    )
    expected_intent = digest(
        {
            "operation": OPERATION,
            "product": reader.product,
            "payload": body.semantic,
            "named_actor": actor,
            "source_revision": None,
            "private_owner": actor if payload.visibility == "private" else None,
        }
    )
    material = digest(
        {
            "tenant": reader.tenant,
            "actor": actor,
            "requester": actor,
            "operation": OPERATION,
            "product": reader.product,
            "expected_revision": proof["revision"],
            "read_set": sorted(
                row["required_source_read_set"],
                key=lambda r: (r["artifact_id"], r["expected_revision"]),
            ),
            "payload": body.semantic,
        }
    )
    review = {
        "operation": OPERATION,
        "payload_semantic": body.semantic,
        "stable_anchor": raw["stable_anchor"],
        "binding": row["candidate_binding"],
        "inspection": snapshot,
        "raw_source_basis": raw_safety,
        "required_source_read_set": row["required_source_read_set"],
        "sources": row["sources"],
        "authority_snapshot": row["source_basis"]["authority"],
        "policy_snapshot": row["source_basis"]["policy"],
        "owner_id": str(row["owner_id"]),
        "visibility": row["visibility"],
        "current_issue_revision": 6,
    }
    require(
        receipt["operation"] == OPERATION
        and receipt["actor_id"] == receipt["requester_id"] == actor
        and receipt["visibility"] == row["visibility"]
        and receipt["run_id"] is None
        and receipt["intent_digest"] == row["intent_digest"] == expected_intent
        and receipt["result"]
        == {
            "id": str(row["id"]),
            "revision": 1,
            "status": "candidate",
            "candidate_binding_sha256": row["binding_sha256"],
            "inspection_sha256": row["inspection_sha256"],
        }
        and type(receipt["result"]["revision"]) is int
        and SHA.fullmatch(receipt["request_digest"])
        and bool(key)
        and audit["actor_id"] == actor
        and audit["operation"] == OPERATION
        and outbox["actor_id"] == actor
        and outbox["type"] == EVENT
        and outbox["subject_id"] == row["id"]
        and type(outbox["subject_revision"]) is int
        and outbox["subject_revision"] == 1
        and outbox["schema_version"] == 1
        and outbox["correlation_id"] == receipt["command_id"],
        "EXACT_UNIQUE_RECEIPT_AUDIT_OUTBOX_KEY_GROUP_REQUIRED",
    )
    require(
        proof["actor_id"] == actor
        and proof["subject_id"] == reader.product
        and proof["operation"] == OPERATION
        and type(proof["revision"]) is int
        and proof["revision"] > 0
        and proof["consumed"] is True
        and proof["payload_digest"] == material
        and proof["snapshot"] == review
        and len(proof["snapshot"]) == 13
        and SHA.fullmatch(proof["token_hash"]),
        "EXACT_CONSUMED_SHARED_PROOF_AND_13KEY_REVIEW_REQUIRED",
    )
    created, consumed, saved, expiry = (
        aware(proof["created_at"]),
        body.proof_consumed_at,
        aware(row["created_at"]),
        aware(proof["expires_at"]),
    )
    checked_at = datetime.now(UTC)
    require(
        created <= consumed <= saved < expiry
        and all(saved <= aware(v["created_at"]) <= checked_at for v in (receipt, audit, outbox)),
        "SAVED_PROOF_CONSUMPTION_CLOCK_INVALID",
    )
    original = row["id"] == UUID(plan["receipt"]["subject_id"])
    if original:
        original_command(reader, row, receipt, proof, plan, payload)
    return {
        "id": str(row["id"]),
        "receipt_id": str(receipt["id"]),
        "status": "PASS",
        "issue_revision": 6,
        "three_columns_and_json_keys_explicit_null": True,
        "result": "indeterminate",
        "original_full_anchor_matches_confirmation": True,
        "anchor_sha256": stable.anchor_sha256,
        "fixed_issue_sha256": stable.origin.ref.snapshot_sha256,
        "stable_failure_material_sha256": stable.stable_failure_material_sha256,
        "binding_sha256": row["binding_sha256"],
        "inspection_sha256": row["inspection_sha256"],
        "ordered_full_readset_sha256": digest(row["required_source_read_set"]),
        "source_count": len(reads),
        "actual_common_intent_matches": True,
        "unique_receipt_audit_outbox_and_original_key": True,
        "created_consumed_saved_expiry_order_valid": True,
        "proof_created_at": created.isoformat(),
        "proof_consumed_at": consumed.isoformat(),
        "candidate_saved_at": saved.isoformat(),
        "proof_expires_at": expiry.isoformat(),
        "proof_seconds_remaining_at_save": round((expiry - saved).total_seconds(), 6),
        "original_cli_request_digest_recomputed": original,
        "failures": original_failures(reader, stable),
    }


def original_command(reader, row, receipt, proof, plan, payload):
    from pdos_next.contracts import Command, SourceRead
    from pdos_next.service import digest, receipt_view

    command = Command.model_validate(plan["prepared_command"])
    original_payload = type(payload).model_validate(command.payload)
    require(
        command.operation == OPERATION
        and command.product_id == reader.product
        and command.command_id == receipt["command_id"]
        and command.expected_revision == proof["revision"]
        and original_payload.model_dump(mode="json", exclude={"confirmation_token"})
        == row["input_snapshot"]["semantic"]
        and digest(original_payload.confirmation_token) == proof["token_hash"]
        and plan["receipt"] == receipt_view(SimpleNamespace(**receipt))
        and plan["preview"]["review"] == proof["snapshot"],
        "ORIGINAL_SAVED_CLI_COMMAND_OR_PREVIEW_CHANGED",
    )
    ordered = [
        SourceRead.model_validate(v).model_dump(mode="json") for v in command.source_read_set
    ]
    expected = digest(
        {
            "operation": command.operation,
            "product_id": command.product_id,
            "expected_revision": command.expected_revision,
            "source_read_set": ordered,
            "payload": original_payload.model_dump(mode="json"),
        }
    )
    exact_key = reader.one("request_keys", actor_id=row["writer_id"], key=command.idempotency_key)
    require(
        receipt["request_digest"] == expected == exact_key["digest"]
        and exact_key["receipt_id"] == receipt["id"]
        and sorted(ordered, key=lambda v: v["artifact_id"])
        == sorted(row["required_source_read_set"], key=lambda v: v["artifact_id"]),
        "ORIGINAL_ORDERED_REQUEST_DIGEST_OR_KEY_ASSOCIATION_CHANGED",
    )


def catalog(connection, tables):
    from sqlalchemy import text

    actual = (
        connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename NOT IN ('alembic_version','environment_guard') ORDER BY tablename"
            )
        )
        .scalars()
        .all()
    )
    require(
        len(actual) == len(tables) == 111 and set(actual) == set(tables),
        "EXACT_111_TABLE_CATALOG_REQUIRED",
    )
    forbidden = (
        connection.execute(
            text(
                "SELECT p.tablename FROM pg_tables p WHERE p.schemaname='public' "
                "AND p.tablename NOT IN ('alembic_version','environment_guard') AND ("
                "has_table_privilege('pdos_agent',"
                "quote_ident(p.schemaname)||'.'||quote_ident(p.tablename),'INSERT,UPDATE,DELETE') "
                "OR EXISTS (SELECT 1 FROM information_schema.columns c "
                "WHERE c.table_schema=p.schemaname AND c.table_name=p.tablename AND "
                "has_column_privilege('pdos_agent',"
                "quote_ident(p.schemaname)||'.'||quote_ident(p.tablename),"
                "c.column_name,'INSERT,UPDATE')))"
            )
        )
        .scalars()
        .all()
    )
    require(not forbidden, "AGENT_DIRECT_BUSINESS_WRITE_PRIVILEGE_FOUND")
    return {
        "public_business_tables": 111,
        "registered_names_match": True,
        "agent_direct_table_and_column_write_privileges": 0,
        "scope": "catalog names and effective INSERT/UPDATE/DELETE; no repeated full schema audit",
    }


def retained(connection, baseline_path):
    from wave16_migrate import history

    baseline = public_json(baseline_path)
    require(set(RETAINED) <= baseline.keys(), "ACTUAL_SAVED_RETAINED_BASELINE_REQUIRED")
    current = history(connection, RETAINED)
    rows = []
    for name in RETAINED:
        expected = baseline[name]
        require(
            set(expected) == {"rows", "sha256"}
            and type(expected["rows"]) is int
            and expected["rows"] >= 0
            and SHA.fullmatch(expected["sha256"]),
            "RETAINED_BASELINE_ENTRY_INVALID",
        )
        rows.append(
            {
                "table": name,
                "baseline": expected,
                "current": current[name],
                "unchanged": expected == current[name],
            }
        )
    return {
        "status": "PASS" if all(row["unchanged"] for row in rows) else "FAIL",
        "baseline_file": baseline_path.name,
        "baseline_sha256": file_sha(baseline_path),
        "tables": rows,
        "scope": "listed complete tables via actual wave16_migrate.history; not whole database",
        "not_compared": [
            "new candidates",
            "Confirmation/common receipt/audit/outbox/request keys",
            "Artifact/Original byte content",
            "professional/issuer facts and current qualifications",
            "Product normal reference_epoch",
            "unlisted tables",
        ],
    }


def inspect_stored(state, plan, args, report):
    from pdos_next.database import engine_for
    from pdos_next.models import Base
    from sqlalchemy import select, text

    product = UUID(plan["prepared_command"]["product_id"])
    identity = UUID(plan["receipt"]["subject_id"])
    engine = engine_for(state["admin_url"])
    try:
        with engine.connect() as c:
            tx = c.begin()
            try:
                c.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                c.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
                c.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
                require(
                    c.scalar(text("SHOW transaction_read_only")) == "on",
                    "READ_ONLY_SNAPSHOT_REQUIRED",
                )
                require(
                    c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026",
                    "ACTUAL_HEAD26_REQUIRED",
                )
                table = Base.metadata.tables["capa_verification_evidence"]
                rows = (
                    c.execute(
                        select(table)
                        .where(table.c.id == identity, table.c.product_id == product)
                        .limit(2)
                    )
                    .mappings()
                    .all()
                )
                require(len(rows) == 1, "ORIGINAL_SAVED_CLI_CANDIDATE_MISSING")
                original = dict(rows[0])
                require(
                    str(original["issue_id"]) == plan["issue_id"], "CLI_EXACT_ISSUE_SCOPE_MISMATCH"
                )
                reader = Reader(c, Base.metadata.tables, original["tenant_id"], product)
                actor = UUID(plan["receipt"]["writer_id"])
                caller(reader, actor, original["project_id"])
                selected = reader.rows(
                    "capa_verification_evidence",
                    limit=args.expected_candidates + 1,
                    project_id=original["project_id"],
                    issue_id=original["issue_id"],
                )
                report["expected_candidates"] = args.expected_candidates
                report["observed_candidates"] = len(selected)
                require(
                    len(selected) == args.expected_candidates,
                    "EXACT_EXPECTED_CANDIDATE_COUNT_NOT_PRESENT",
                )
                report["candidates"] = []
                for row in sorted(selected, key=lambda v: (v["created_at"], str(v["id"]))):
                    report["active_candidate_id"] = str(row["id"])
                    report["candidates"].append(candidate(reader, row, actor, plan))
                report.pop("active_candidate_id", None)
                require(
                    len({v["fixed_issue_sha256"] for v in report["candidates"]}) == 1
                    and len({v["stable_failure_material_sha256"] for v in report["candidates"]})
                    == 1,
                    "CANDIDATES_CHANGED_ORIGINAL_FIXED_FAILURE_ANCHOR",
                )
                report["candidate_atomic_groups"] = "PASS"
                report["catalog"] = catalog(c, Base.metadata.tables)
                report["retained_history"] = retained(c, REPORT / args.retained_baseline)
                require(
                    report["retained_history"]["status"] == "PASS",
                    "SAVED_RETAINED_TABLE_ROWS_CHANGED",
                )
                report["checked_at"] = caller(reader, actor, original["project_id"]).isoformat()
            finally:
                tx.rollback()
    finally:
        engine.dispose()


def basename(value):
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,110}\.json", value), "EVIDENCE_BASENAME_REQUIRED")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", required=True, type=UUID)
    parser.add_argument("--expected-candidates", required=True, type=int)
    parser.add_argument("--runtime-manifest", default="candidate-actual-http-source-v7.json")
    parser.add_argument("--web-manifest", default="web-candidate-source-v5.json")
    parser.add_argument("--retained-baseline", default="public-migration-retained-before-v2.json")
    parser.add_argument("--report-name", default="closeout-v1.json")
    args = parser.parse_args()
    require(
        str(args.marker) == MARKER and 1 <= args.expected_candidates <= 20,
        "EXPLICIT_MARKER_AND_BOUNDED_COUNT_REQUIRED",
    )
    for value in (
        args.runtime_manifest,
        args.web_manifest,
        args.retained_baseline,
        args.report_name,
    ):
        basename(value)
    require(
        REPORT.is_dir() and not REPORT.is_symlink(), "SAFE_EXISTING_EVIDENCE_DIRECTORY_REQUIRED"
    )
    require(
        not (REPORT / args.report_name).exists(), "ORIGINAL_CLOSEOUT_REPORT_MUST_NOT_BE_OVERWRITTEN"
    )
    report = {
        "schema": "wave17-candidate-readonly-closeout-v1",
        "status": "RUNNING",
        "tool_sha256": file_sha(Path(__file__)),
        "business_writes": 0,
        "http_calls": 0,
        "model_calls": 0,
        "target": "127.0.0.1:62513/pdos_test",
        "marker": MARKER,
        "limits": [
            "Stored as-of evidence only; not fresh professional/seven-owner authorization.",
            "No original byte IO; original proof checked against saved rows and snapshot.",
            "Stored consumed=True/group does not recreate the actual same-UOW consumption marker.",
            "CLI digest recomputed from actual saved command; other original key associations "
            "checked without inventing token preimages.",
            "TTL checked at actual saved_at; no commit-clock or current-TTL guarantee.",
            "No effectiveness, closure, production qualification or human Exit granted.",
        ],
    }
    code = 1
    try:
        sys.path.insert(0, str(SERVER))
        from wave17_migrate import private_json, target

        report["runtime_source"] = manifest(REPORT / args.runtime_manifest, SERVER)
        report["web_source"] = manifest(REPORT / args.web_manifest, ROOT.parent)
        plan = private_json(ROOT / ".local/wave17-candidate-http.json")
        require(
            plan["state"] == "saved" and plan["marker"] == MARKER,
            "ACTUAL_PRIVATE_CLI_SAVED_STATE_REQUIRED",
        )
        state = target()
        inspect_stored(state, plan, args, report)
        require(target() == state, "MARKED_TARGET_CHANGED_DURING_CLOSEOUT")
        require(
            manifest(REPORT / args.runtime_manifest, SERVER) == report["runtime_source"]
            and manifest(REPORT / args.web_manifest, ROOT.parent) == report["web_source"],
            "CANDIDATE_SOURCE_CHANGED_DURING_CLOSEOUT",
        )
        report["status"] = "PASS_STORED_CANDIDATE_CLOSEOUT"
        code = 0
    except Stop as error:
        report.update(status="FAIL", reason_code=str(error))
    except Exception as error:
        # Driver/Pydantic/runtime exceptions can contain private parameters/URLs.
        report.update(
            status="FAIL",
            reason_code="UNVERIFIABLE_SELECTED_STORED_EVIDENCE",
            error_type=type(error).__name__,
        )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode()) > 8_388_608:
        report = {
            "schema": report["schema"],
            "tool_sha256": report["tool_sha256"],
            "status": "FAIL",
            "reason_code": "SAFE_REPORT_BOUND_EXCEEDED",
            "business_writes": 0,
        }
        encoded = json.dumps(report, indent=2) + "\n"
        code = 1
    descriptor = os.open(
        REPORT / args.report_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as output:
        output.write(encoded)
    print(f"Stored candidate closeout: {'PASS' if code == 0 else 'FAIL'}; {args.report_name}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
