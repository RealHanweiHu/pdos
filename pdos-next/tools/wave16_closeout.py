"""Root-run, after-the-fact Wave16 read-only evidence check; inert on import.

Never seeds, previews, consumes, replays, migrates or invokes HTTP. The only
output is a new safe report; private identifiers, facts and credentials stay
in memory. Existing OriginalStore read gates may use bounded control locks.
"""

import argparse
import asyncio
import json
import os
import re
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave16-20261002"
MARKER = "916f950f-2d2b-405d-b809-c15db75dc20c"
HEAD = "next_0025"
PORT = 62513
ROOT_CAUSE = "quality.issue.root_cause.decide"
COMPLETE = "quality.capa.actions.complete"
LINK = "quality.capa.followup.link"
POSITION = re.compile(r"line:([1-9][0-9]*);quote_sha256:([0-9a-f]{64})")


class Stop(RuntimeError):
    """Fixed diagnostic codes only; no private exception text."""


def require(value, code):
    if not value:
        raise Stop(code)


def timestamp(value):
    instant = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    require(instant.tzinfo is not None and instant.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
    return instant.astimezone(UTC)


def private_json(path):
    require(
        path.parent.is_dir() and not path.parent.is_symlink(), "SAFE_PRIVATE_DIRECTORY_REQUIRED"
    )

    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "DUPLICATE_PRIVATE_JSON_FIELD")
            result[key] = value
        return result

    def constant(_):
        raise Stop("NONFINITE_PRIVATE_JSON")

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1
            and info.st_uid == os.getuid(),
            "PRIVATE_INPUT_NOT_OWNED_REGULAR_600",
        )
        require(info.st_size <= 8_388_608, "PRIVATE_INPUT_TOO_LARGE")
        content = handle.read(8_388_609)
        require(len(content) <= 8_388_608, "PRIVATE_INPUT_TOO_LARGE")
    return json.loads(content, object_pairs_hook=pairs, parse_constant=constant)


def target(args, seed, prepared):
    from local_environment import read_state, verified
    from sqlalchemy.engine import make_url

    guarded_state = private_json(ROOT / ".local/runtime.json")
    state = read_state()
    require(state == guarded_state, "RUNTIME_STATE_CHANGED_DURING_TARGET_CHECK")
    require(
        str(args.marker) == state["marker"] == seed["marker"] == prepared["marker"] == MARKER
        and type(state["port"]) is int
        and state["port"] == PORT
        and state["container_id"] == prepared["container_id"],
        "EXPLICIT_MARKED_62513_TARGET_REQUIRED",
    )
    # Check every credential-bearing endpoint before verified() makes any connection.
    for field in ("admin_url", "app_url", "auth_url"):
        url = make_url(state[field])
        require(
            url.drivername == "postgresql+psycopg"
            and url.host == "127.0.0.1"
            and url.port == PORT
            and url.database == "pdos_test",
            "TARGET_ENDPOINT_MISMATCH",
        )
    require(
        state["preview_tenant_id"] == seed["tenant_id"]
        and state["preview_product_id"] == seed["product_id"],
        "MARKED_SEED_SCOPE_MISMATCH",
    )
    return verified(state)


@contextmanager
def readonly(state, seed):
    from pdos_next.database import engine_for
    from sqlalchemy import text

    engine = engine_for(state["admin_url"])
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='15s'"))
            connection.execute(text("SET LOCAL lock_timeout='5s'"))
            connection.execute(
                text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
                {"tenant": seed["tenant_id"]},
            )
            require(
                connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on",
                "READ_ONLY_TRANSACTION_REQUIRED",
            )
            require(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == HEAD,
                "EXACT_NEXT_0025_HEAD_REQUIRED",
            )
            yield connection
    finally:
        engine.dispose()


def reader_type():
    from pdos_next.service import digest
    from wave15_closeout import Reader

    class TrackedReader(Reader):
        def __init__(self, connection, seed):
            super().__init__(connection, seed)
            self.observed = {}
            self.cache = {}

        @staticmethod
        def fingerprint(name, rows):
            transient = (
                {"delivered_at", "lease_id", "lease_until", "attempts", "last_error"}
                if name == "outbox_events"
                else set()
            )
            fixed = [{k: v for k, v in row.items() if k not in transient} for row in rows]
            return digest(sorted(fixed, key=lambda row: str(row["id"])))

        def rows(self, name, *, limit=1001, **filters):
            key = digest({"table": name, "filters": filters, "limit": limit})
            # Cache only inside this one REPEATABLE READ transaction, never
            # across actors, transactions or phases. Fresh recheck has a new cache.
            if key in self.cache:
                return self.cache[key]
            rows = super().rows(name, limit=limit, **filters)
            fingerprint = self.fingerprint(name, rows)
            self.observed[key] = (name, limit, filters, fingerprint)
            self.cache[key] = rows
            return rows

    return TrackedReader


def source_reads(reader, values, actor):
    from pdos_next.service import digest

    require(isinstance(values, list) and 1 <= len(values) <= 20, "FIXED_READ_SET_REQUIRED")
    seen, basis = set(), []
    for value in sorted(values, key=lambda item: item["artifact_id"]):
        identity = UUID(value["artifact_id"])
        require(identity not in seen, "SOURCE_READ_DUPLICATE")
        seen.add(identity)
        require(type(value["expected_revision"]) is int, "SOURCE_REVISION_NOT_INTEGER")
        row = reader.one("artifact_versions", id=identity, revision=value["expected_revision"])
        require(
            row["status"] == "active"
            and digest(row["content"]) == row["content_hash"]
            and (row["visibility"] == "product" or row["owner_id"] == actor),
            "SOURCE_INACTIVE_HASH_OR_PRIVATE_ACCESS_CHANGED",
        )
        entry = {
            "id": str(row["id"]),
            "revision": row["revision"],
            "hash": row["content_hash"],
            "status": row["status"],
            "owner_id": str(row["owner_id"]),
            "visibility": row["visibility"],
        }
        if row["original_id"] is None:
            receipt = reader.one(
                "action_receipts",
                operation="evidence.artifact.register",
                subject_type="artifact",
                subject_id=row["id"],
                subject_revision=row["revision"],
            )
            require(
                receipt["actor_id"] == receipt["requester_id"] == row["owner_id"]
                and receipt["run_id"] is None
                and receipt["visibility"] == row["visibility"]
                and receipt["result"]["id"] == str(row["id"])
                and receipt["result"]["revision"] == row["revision"],
                "DIRECT_HUMAN_NATIVE_SOURCE_RECEIPT_REQUIRED",
            )
            entry.update(
                source_kind="registered_native_text",
                registration={
                    "receipt_id": str(receipt["id"]),
                    "actor_id": str(receipt["actor_id"]),
                    "requester_id": str(receipt["requester_id"]),
                    "run_id": None,
                },
            )
        else:
            require(
                row["original_id"] == UUID(reader.seed["report_upload"]["subject_id"]),
                "ADDITIONAL_ORIGINAL_RUNTIME_PROOF_NOT_IMPLEMENTED",
            )
            security = reader.one("original_security", original_id=row["original_id"])
            require(
                security["source_state"] == "active" and security["disposition"] == "active",
                "ORIGINAL_WITHDRAWN_OR_QUARANTINED",
            )
            entry.update(
                source_kind="uploaded_original",
                original={
                    "id": str(row["original_id"]),
                    "epoch": security["epoch"],
                    "source_state": security["source_state"],
                    "disposition": security["disposition"],
                },
            )
        basis.append(entry)
    return basis


def exact_line(reader, source, actor):
    from pdos_next.service import digest

    require(source.kind == "artifact", "EXACT_ARTIFACT_EVENT_SOURCE_REQUIRED")
    match = POSITION.fullmatch(source.position)
    require(match is not None, "EXACT_LINE_SHA_LOCATOR_REQUIRED")
    source_reads(
        reader, [{"artifact_id": str(source.id), "expected_revision": source.revision}], actor
    )
    row = reader.one("artifact_versions", id=source.id, revision=source.revision)
    lines = row["content"].splitlines()
    require(int(match[1]) <= len(lines), "EXACT_LINE_OUT_OF_RANGE")
    line = lines[int(match[1]) - 1]
    require(digest(line) == match[2], "WHOLE_LINE_SHA_MISMATCH")
    return line


def atom(reader, row, family, operation, payload, actor):
    from pdos_next.command_handlers import handler
    from pdos_next.service import EVENTS, digest

    module = handler(operation)
    require(module is not None, "FROZEN_HANDLER_NOT_REGISTERED")
    receipt = reader.one(
        "action_receipts",
        subject_type=family,
        subject_id=row["id"],
        subject_revision=row["revision"],
        operation=operation,
    )
    require(
        receipt["actor_id"] == receipt["requester_id"] == actor
        and receipt["run_id"] is None
        and receipt["visibility"] == row["visibility"]
        and receipt["intent_digest"]
        == digest(
            {
                "operation": operation,
                "product": row["product_id"],
                "payload": module.semantic(payload),
                "named_actor": actor,
                "source_revision": None,
                "private_owner": actor
                if getattr(payload, "visibility", "private") == "private"
                else None,
            }
        )
        and receipt["result"]["id"] == str(row["id"])
        and receipt["result"]["revision"] == row["revision"],
        "EXACT_NAMED_RECEIPT_BINDING_MISMATCH",
    )
    audit = reader.one("audit_entries", receipt_id=receipt["id"])
    event = reader.one("outbox_events", receipt_id=receipt["id"])
    require(
        audit["actor_id"] == actor
        and audit["operation"] == operation
        and event["actor_id"] == actor
        and event["type"] == EVENTS[operation]
        and event["subject_id"] == row["id"]
        and event["subject_revision"] == row["revision"]
        and event["schema_version"] == 1
        and event["correlation_id"] == receipt["command_id"],
        "EXACT_AUDIT_OUTBOX_BINDING_MISMATCH",
    )
    keys = reader.rows("request_keys", receipt_id=receipt["id"], actor_id=actor)
    require(
        re.fullmatch(r"[0-9a-f]{64}", receipt["request_digest"]) is not None
        and any(key["digest"] == receipt["request_digest"] for key in keys),
        "ORIGINAL_REQUEST_KEY_DIGEST_BINDING_MISSING",
    )
    source_reads(reader, row["required_source_read_set"], actor)
    if hasattr(module, "_intent"):
        from pdos_next.service import Context

        require(
            row["intent_digest"]
            == module._intent(
                Context(row["tenant_id"], actor, actor),
                SimpleNamespace(operation=operation, product_id=row["product_id"]),
                payload,
            ),
            "DOMAIN_SEMANTIC_INTENT_MISMATCH",
        )
    return receipt


def proof(reader, row, operation, payload, actor, *, before=None, after=None):
    from pdos_next.command_handlers import handler
    from pdos_next.contracts import SourceRead
    from pdos_next.service import Context, digest, material_digest
    from sqlalchemy import func, select

    marker = (row["input_snapshot"] if operation == LINK else row["source_basis"])["shared_proof"]
    tier = "T2" if operation == ROOT_CAUSE else "T1"
    require(marker["tier"] == tier, "EXACT_PROOF_TIER_REQUIRED")
    saved = reader.one("confirmations", id=UUID(marker["id"]))
    require(
        saved["consumed"] is True
        and saved["actor_id"] == actor
        and saved["operation"] == operation
        and saved["subject_id"] == row["product_id"]
        and 0 < saved["revision"]
        and saved["created_at"] <= row["created_at"] <= saved["expires_at"],
        "CONSUMED_NAMED_PROOF_SCOPE_OR_COMMIT_WINDOW_MISMATCH",
    )
    command = SimpleNamespace(
        operation=operation,
        product_id=row["product_id"],
        expected_revision=saved["revision"],
        source_read_set=[SourceRead.model_validate(v) for v in row["required_source_read_set"]],
    )
    require(
        saved["payload_digest"]
        == material_digest(
            Context(row["tenant_id"], actor, actor), command, payload, handler(operation)
        ),
        "PROOF_MATERIAL_DIGEST_MISMATCH",
    )
    review = saved["snapshot"]
    authority = row["authority_snapshot"]
    require(
        authority["authorized"] is True
        and authority["qualified"] is True
        and authority["synthetic"] is True
        and authority["subject_id"] == str(actor)
        and authority["operation"] == operation
        and authority["purpose"] == row["purpose"],
        "SAVED_NAMED_PROFESSIONAL_AUTHORITY_SCOPE_MISMATCH",
    )
    if operation != LINK:
        from pdos_next.domain.quality_followup.service import _preview_issue

        basis = review["read_basis"]
        original = {
            key: value
            for key, value in row["source_basis"].items()
            if key not in {"shared_proof", "completion_observations"}
        }
        require(
            review["before"] == {str(before.id): before.model_dump(mode="json")}
            and review["after"] == {str(after.id): _preview_issue(after, before)}
            and digest(basis["authority"]) == digest(row["authority_snapshot"])
            and digest(basis["policy"]) == digest(row["policy_snapshot"])
            and digest(basis["source_basis"]) == digest(original)
            and digest(sorted(basis["read_set"], key=lambda v: v["artifact_id"]))
            == digest(sorted(row["required_source_read_set"], key=lambda v: v["artifact_id"]))
            and review["received_at"] is None
            and review["clock_basis"] == "server_on_save"
            and review["effectiveness_decide"] is False
            and review["issue_close"] is False,
            "PROOF_FIXED_BEFORE_AFTER_OR_READ_BASIS_MISMATCH",
        )
    else:
        require(
            review["before"] is None
            and review["after"]
            == {
                "id": None,
                "revision": 1,
                "issue_id": str(row["issue_id"]),
                "issue_revision": row["issue_revision"],
                "capa_id": str(row["capa_id"]),
                "action_id": str(row["action_id"]),
                "resolution": row["output_snapshot"],
                "visibility": row["visibility"],
                "received_at": "server_on_save",
                "action_fulfilled": None,
            }
            and digest(review["authority"]) == digest(row["authority_snapshot"])
            and digest(review["policy"]) == digest(row["policy_snapshot"]),
            "LINK_PROOF_FIXED_RESOLUTION_MISMATCH",
        )
    # Explicit tenant/product scope, not Reader's narrower project: a proof may
    # not be reused by a second immutable version or Link in another project.
    uses = 0
    for name, field in (
        ("quality_issue_versions", "source_basis"),
        ("capa_remediation_links", "input_snapshot"),
    ):
        table = reader.tables[name]
        query = (
            select(func.count())
            .select_from(table)
            .where(
                table.c.tenant_id == row["tenant_id"],
                table.c.product_id == row["product_id"],
                table.c[field]["shared_proof"]["id"].astext == marker["id"],
            )
        )
        uses += reader.connection.execute(query).scalar_one()
    require(uses == 1, "CONSUMED_PROOF_NOT_SINGLE_USE_ACROSS_VERSION_AND_LINK")


def issue_chain(reader, args, seed, prepared, checks):
    from pdos_next.contracts import PAYLOADS
    from pdos_next.domain.quality_followup.evidence import verify_completion_line
    from pdos_next.schemas.quality_issues.contracts import Issue
    from pdos_next.service import digest

    actor = UUID(seed["actor_id"])
    reader.actor_access(actor)
    reader.one("products", id=UUID(seed["product_id"]))
    pointer = reader.one("quality_current_issues", issue_id=args.issue)
    rows = [
        reader.one("quality_issue_versions", id=v, issue_id=args.issue)
        for v in (args.issue_v4, args.root_v5, args.complete_v6)
    ]
    require(
        [v["revision"] for v in rows] == [4, 5, 6]
        and pointer["issue_version_id"] == args.complete_v6
        and pointer["issue_revision"] == 6
        and [v["operation"] for v in rows] == ["quality.capa.draft", ROOT_CAUSE, COMPLETE],
        "EXACT_ISSUE_4_TO_5_TO_6_CURRENT_CHAIN_REQUIRED",
    )
    values = [Issue.model_validate(row["issue_snapshot"]) for row in rows]
    require(
        prepared["observed_issue_basis"]
        == {
            "issue_version_id": str(args.issue_v4),
            "issue_revision": 4,
            "snapshot_sha256": rows[0]["snapshot_sha256"],
        },
        "EXTERNAL_PRE_FOLLOWUP_ISSUE4_BASELINE_MISMATCH",
    )
    for row, issue in zip(rows, values, strict=True):
        require(
            issue.id == args.issue
            and issue.revision == row["revision"]
            and issue.scope.tenant_id == row["tenant_id"]
            and issue.scope.product_id == row["product_id"]
            and issue.scope.project_id == row["project_id"]
            and digest(issue.model_dump(mode="json")) == row["snapshot_sha256"]
            and row["writer_id"] == row["owner_id"] == actor
            and issue.capa is not None
            and str(issue.capa.id) == seed["capa_id"]
            and issue.failures == values[0].failures
            and issue.merged_into is None
            and not issue.needs_recheck
            and issue.closure is None
            and issue.capa.effectiveness is None
            and not issue.capa.effectiveness_history,
            "IMMUTABLE_ISSUE_IDENTITY_FAILURE_OR_CLOSED_BOUNDARY_MISMATCH",
        )
        payload = PAYLOADS[row["operation"]].model_validate(row["input_snapshot"])
        atom(reader, row, "quality_issue", row["operation"], payload, actor)
        if row["revision"] > 4:
            old_row = rows[row["revision"] - 5]
            old = values[row["revision"] - 5]
            require(
                row["previous_issue_version_id"] == old_row["id"]
                and row["previous_revision"] == old_row["revision"]
                and old_row["created_at"] <= row["created_at"]
                and payload.issue_id == args.issue
                and payload.expected_issue_revision == old.revision
                and issue.history[: len(old.history)] == old.history
                and len(issue.history) == len(old.history) + 1
                and issue.history[-1].operation == row["operation"]
                and issue.history[-1].actor_id == actor,
                "ISSUE_CAS_HISTORY_PREDECESSOR_MISMATCH",
            )
            proof(reader, row, row["operation"], payload, actor, before=old, after=issue)
    old, root, completed = values
    require(
        old.status == root.status == "actioning"
        and completed.status == "awaiting_verification"
        and old.root_cause is None
        and root.root_cause is not None
        and completed.root_cause == root.root_cause
        and root.root_cause.actor_id == actor
        and root.root_cause.text == prepared["materials"]["root_cause_text"]
        and len(old.capa.actions) == len(root.capa.actions) == len(completed.capa.actions) == 1,
        "ROOT_CAUSE_BEFORE_ALL_COMPLETED_SCOPE_REQUIRED",
    )
    actions = [issue.capa.actions[0] for issue in values]
    require(
        all(a.id == args.action and a.executor_id == actor for a in actions)
        and actions[0].completion is actions[1].completion is None
        and actions[2].completion is not None
        and all(
            digest(a.model_dump(mode="json", exclude={"completion"}))
            == prepared["action_binding"]["action_sha256"]
            for a in actions
        ),
        "ORIGINAL_NAMED_ACTION_OR_COMPLETION_MISMATCH",
    )
    completion = actions[2].completion
    line = exact_line(reader, completion.at.source, actor)
    received = rows[2]["source_basis"]["completion_observations"]
    require(len(received) == 1, "SINGLE_REAL_COMPLETION_RECEIVE_CLOCK_REQUIRED")
    fact = verify_completion_line(
        line, root, rows[2]["purpose"], completion, actor, timestamp(received[0]["received_at"])
    )
    raw = prepared["materials"]["observed_completion"]["raw"]
    require(
        json.loads(line) == raw
        and fact.model_dump(mode="json") == received[0]["fact"]
        and completion.at.occurred_at == timestamp(raw["occurred_at"])
        and completion.at.original_timezone == raw["original_timezone"]
        and completion.at.effective_at is None
        and completion.at.source in completion.evidence
        and rows[1]["created_at"] <= rows[2]["created_at"]
        and timestamp(received[0]["received_at"]) <= rows[2]["created_at"]
        and timestamp(root.root_cause.at) <= rows[1]["created_at"],
        "ORIGINAL_MICROSECOND_OFFSET_COMPLETION_OR_RECEIVED_CLOCK_MISMATCH",
    )
    for source in root.root_cause.sources:
        exact_line(reader, source, actor)
    checks.extend(
        [
            "issue4_external_baseline_and_fixed_failures_intact",
            "issue_current_exact_root5_then_complete6",
            "root_T2_and_completion_T1_single_consumed_material_proof",
            "each_issue_version_exact_receipt_audit_outbox",
            "original_completion_line_microseconds_offset_and_independent_receive_clock",
            "original_action_root_before_all_completion_effectiveness_and_close_absent",
        ]
    )
    return rows[2], completed


def original_failure(reader, seed, issue, checks):
    from pdos_next.domain.quality_issues.ports import VerifiedRun
    from pdos_next.domain.quality_issues.rules import failure_ref
    from pdos_next.domain.verification import rules
    from pdos_next.domain.verification_launch.service import _snapshot
    from pdos_next.service import digest
    from wave15_closeout import original_proof

    require(len(issue.failures) == 1, "SINGLE_FIXED_SYNTHETIC_FAILURE_REQUIRED")
    failure = issue.failures[0]
    fixed = reader.one(
        "verification_run_versions", run_id=failure.run.id, revision=failure.run.revision
    )
    run, plan = _snapshot(SimpleNamespace(**fixed))
    require(
        fixed["request_id"] == UUID(seed["request_id"])
        and fixed["owner_id"] == UUID(seed["actor_id"])
        and run.actual_start is not None
        and run.final_result is not None
        and run.result == "fail"
        and failure
        == failure_ref(VerifiedRun(run=run, nature="synthetic"), failure.measurement_id),
        "FIXED_STARTED_FINAL_FAIL_PROOF_MISMATCH",
    )
    mapped = reader.one(
        "quality_failure_maps", issue_id=issue.id, failure_identity=failure.identity
    )
    require(
        mapped["failure"] == failure.model_dump(mode="json"),
        "ORIGINAL_FAILURE_IDENTITY_MAP_CHANGED",
    )
    computed, result = rules.compute_results(run, run.measurements, final=True)
    require(
        result == "fail" and tuple(computed) == run.computed_results,
        "ORIGINAL_DETERMINISTIC_FAIL_RECOMPUTE_MISMATCH",
    )
    measurement = reader.one("test_measurements", id=failure.measurement_id, run_id=run.id)
    require(
        digest(measurement["measurement"]) == measurement["measurement_sha256"]
        and measurement["measurement"]
        == next(m for m in run.measurements if m.id == failure.measurement_id).model_dump(
            mode="json"
        ),
        "FIXED_MEASUREMENT_HASH_MISMATCH",
    )
    capture = reader.one("measurement_import_captures", id=measurement["capture_id"])
    original_proof(
        reader, seed, measurement, capture, run
    )  # Return contains private facts: discard.
    links = reader.rows(
        "quality_event_failure_links", issue_id=issue.id, failure_identity=failure.identity
    )
    require(bool(links), "EXACT_FAILURE_DELIVERY_REQUIRED")
    for link in links:
        from pdos_next.domain.verification_results import service as results

        projection = reader.one("test_result_projections", id=link["projection_id"])
        projected = reader.one("verification_run_versions", id=projection["run_version_id"])
        projected_run, projected_plan = _snapshot(SimpleNamespace(**projected))
        event = reader.one("outbox_events", id=link["event_id"])
        receipt = reader.one("action_receipts", id=event["receipt_id"])
        require(
            link["failure"] == failure.model_dump(mode="json")
            and link["run_version_id"] == fixed["id"]
            and link["run_revision"] == fixed["revision"]
            and link["measurement_id"] == measurement["id"]
            and projection["run_id"] == run.id
            and projection["run_revision"] == projected["revision"]
            and projection["run_sha256"] == projected["snapshot_sha256"]
            and projection["revision"] == link["projection_revision"]
            and projection["basis_sha256"]
            == link["basis_sha256"]
            == results._basis_sha(run, plan)
            == results._basis_sha(projected_run, projected_plan)
            and projection["input_snapshot"] == results._projection_basis(run, plan)
            and projection["rules_version"] == results.RULES_VERSION
            and projection["rules_sha256"] == results.RULES_SHA256
            and projection["result"] == "fail"
            and projection["computed_results"] == [c.model_dump(mode="json") for c in computed]
            and receipt["operation"] == "test.result.compute"
            and receipt["subject_type"] == "test_result_projection"
            and receipt["subject_id"] == projection["id"]
            and receipt["subject_revision"] == projection["revision"]
            and event["subject_id"] == projection["id"]
            and event["correlation_id"] == receipt["command_id"],
            "EXACT_ORIGINAL_FAILURE_EVENT_PROJECTION_BINDING_MISMATCH",
        )
    checks.append("original_fixed_run_measurement_fail_event_projection_and_current_safe_bytes")


def new_draft(reader, args, seed, checks):
    from pdos_next.contracts import PAYLOADS
    from pdos_next.schemas.verification.contracts import VerificationRequest
    from pdos_next.service import digest

    actor = UUID(seed["actor_id"])
    prep = reader.one(
        "verification_preparations",
        id=args.new_preparation_version,
        request_id=args.new_preparation_request,
    )
    formal = reader.one(
        "verification_formal_requests",
        id=args.new_formal_version,
        request_id=args.new_formal_request,
    )
    prep_pointer = reader.one(
        "verification_current_preparations", request_id=args.new_preparation_request
    )
    formal_pointer = reader.one(
        "verification_current_formal_requests", request_id=args.new_formal_request
    )
    require(
        prep_pointer["preparation_id"] == prep["id"]
        and prep_pointer["preparation_revision"] == prep["revision"] == 1
        and formal_pointer["request_version_id"] == formal["id"]
        and formal_pointer["request_revision"] == formal["revision"] == 1
        and formal["operation"] == "verification.request.create"
        and formal["status"] == "draft"
        and prep["status"] == "prepared"
        and prep["previous_preparation_id"] is prep["previous_revision"] is None
        and formal["previous_request_id"] is formal["previous_revision"] is None
        and formal["preparation_id"] == prep["id"]
        and formal["preparation_revision"] == prep["revision"]
        and formal["preparation_sha256"] == prep["snapshot_sha256"]
        and formal["build_id"] == prep["build_id"]
        and formal["build_revision"] == prep["build_revision"]
        and formal["owner_id"] == prep["owner_id"] == actor
        and args.new_formal_request != UUID(seed["request_id"])
        and args.new_preparation_request != UUID(seed["preparation_request_id"]),
        "FRESH_DIRECT_CURRENT_PREPARATION_FORMAL_FIXED_BINDING_REQUIRED",
    )
    snapshots = [VerificationRequest.model_validate(v["request_snapshot"]) for v in (prep, formal)]
    for row, snapshot in zip((prep, formal), snapshots, strict=True):
        require(
            digest(snapshot.model_dump(mode="json")) == row["snapshot_sha256"]
            and snapshot.id == row["request_id"]
            and snapshot.revision == row["revision"]
            and snapshot.status == "draft"
            and snapshot.scope.tenant_id == row["tenant_id"]
            and snapshot.scope.product_id == row["product_id"]
            and snapshot.scope.project_id == row["project_id"]
            and snapshot.build.id == row["build_id"]
            and snapshot.build.revision == row["build_revision"]
            and not snapshot.samples
            and not snapshot.offered_coverage
            and not snapshot.acceptances
            and not snapshot.returns
            and all(
                value is None
                for key, value in snapshot.timeline.model_dump().items()
                if key != "request_created"
            ),
            "FRESH_DRAFT_HAS_PHYSICAL_SAMPLE_OR_EVENT_FACTS",
        )
    require(
        snapshots[0].items == snapshots[1].items
        and snapshots[0].build == snapshots[1].build
        and snapshots[0].purpose == snapshots[1].purpose,
        "FRESH_FORMAL_FIXED_PREPARATION_CONTENT_MISMATCH",
    )
    require(
        not reader.rows("verification_run_identities", request_id=args.new_formal_request),
        "FRESH_FORMAL_ALREADY_HAS_RUN",
    )
    prep_payload = PAYLOADS["verification.preparation.record"].model_validate(
        prep["input_snapshot"]
    )
    prep_receipt = atom(
        reader,
        prep,
        "verification_preparation",
        "verification.preparation.record",
        prep_payload,
        actor,
    )
    raw = {k: v for k, v in formal["input_snapshot"].items() if k != "method_assessment_refs"}
    formal_payload = PAYLOADS["verification.request.create"].model_validate(raw)
    require(
        formal["input_snapshot"].get("method_assessment_refs") == [],
        "FRESH_FORMAL_HAS_METHOD_FACTS",
    )
    formal_receipt = atom(
        reader, formal, "verification_request", "verification.request.create", formal_payload, actor
    )
    for row, snapshot, receipt in zip(
        (prep, formal), snapshots, (prep_receipt, formal_receipt), strict=True
    ):
        first = snapshot.timeline.request_created
        require(
            first.source.kind == "command"
            and first.source.id == receipt["command_id"]
            and first.source.revision == 1
            and first.source.position == "receipt"
            and first.actor_id == actor
            and first.occurred_at == first.received_at <= row["created_at"],
            "FRESH_REQUEST_CREATION_CLOCK_NOT_EXACT_DIRECT_COMMAND_RECEIPT",
        )
    require(
        formal["intent_digest"]
        == digest(
            {
                "operation": formal["operation"],
                "payload": raw,
                "actor": actor,
            }
        ),
        "DIRECT_FORMAL_SEMANTIC_INTENT_MISMATCH",
    )
    checks.append("fresh_current_direct_receipt_draft_empty_physical_samples_and_clocks")
    return formal


def link_check(reader, args, seed, row, issue, formal, checks):
    from pdos_next.domain.capa_verification import commands, service
    from pdos_next.domain.capa_verification.schemas import FollowupLinkPayload, ResolvedOutputs
    from pdos_next.service import Context, digest

    actor = UUID(seed["actor_id"])
    saved = reader.one("capa_remediation_links", id=args.new_link, issue_id=args.issue)
    require(
        saved["issue_version_id"] == row["id"]
        and saved["issue_revision"] == row["revision"] == 6
        and saved["capa_id"] == issue.capa.id
        and saved["action_id"] == args.action
        and saved["revision"] == 1
        and saved["status"] == "recorded"
        and saved["owner_id"] == saved["writer_id"] == actor
        and saved["nature"] == "synthetic",
        "LINK_EXACT_ISSUE6_CAPA_ORIGINAL_ACTION_REQUIRED",
    )
    resolution = ResolvedOutputs.model_validate(saved["output_snapshot"])
    basis = resolution.basis
    expected = service.basis_from_issue(
        SimpleNamespace(**row),
        issue,
        sources=basis.sources,
        reads=[v.model_dump(mode="json") for v in basis.required_source_read_set],
        source_basis=source_reads(
            reader, [v.model_dump(mode="json") for v in basis.required_source_read_set], actor
        ),
    )
    require(
        basis == expected
        and basis.model_dump(mode="json") == saved["basis_snapshot"]
        and service._basis_digest(basis) == saved["basis_sha256"]
        and resolution.action_id == args.action
        and resolution.action_fulfilled is None
        and digest(resolution.model_dump(mode="json", exclude={"resolution_sha256"}))
        == saved["resolution_sha256"]
        == resolution.resolution_sha256,
        "LINK_FIXED_BASIS_OR_RESOLUTION_DIGEST_MISMATCH",
    )
    for source in basis.sources:
        exact_line(reader, source, actor)
    require(len(resolution.outputs) == 1, "SINGLE_DIRECT_NEW_FORMAL_OUTPUT_REQUIRED")
    output = resolution.outputs[0]
    require(
        output.ref.kind == "verification_request"
        and output.ref.id == formal["id"]
        and output.ref.revision == formal["revision"]
        and output.ref.key is None
        and output.logical_id == formal["request_id"]
        and output.project_id == formal["project_id"]
        and output.owner_id == formal["owner_id"]
        and output.visibility == formal["visibility"]
        and output.status == "draft"
        and output.meaning == "planned"  # request branch is planned; no performed fact
        and output.source_status == "current"
        and output.snapshot["request_snapshot"] == formal["request_snapshot"],
        "LINK_OUTPUT_NOT_EXACT_DIRECT_NEW_DRAFT_ROW",
    )
    require(
        output.owner_basis_sha256
        == digest(
            {
                "ref": output.ref.model_dump(mode="json"),
                "snapshot": output.snapshot,
                "source_basis": source_reads(
                    reader,
                    [v.model_dump(mode="json") for v in output.required_source_read_set],
                    actor,
                ),
            }
        )
        and resolution.source_basis_sha256
        == digest(
            source_reads(
                reader,
                [v.model_dump(mode="json") for v in resolution.required_source_read_set],
                actor,
            )
        ),
        "LINK_OWNER_OR_COMBINED_CURRENT_SOURCE_BASIS_MISMATCH",
    )
    raw = {k: v for k, v in saved["input_snapshot"].items() if k != "shared_proof"}
    payload = FollowupLinkPayload.model_validate(raw)
    for reference in payload.sources:
        source_reads(
            reader,
            [
                {
                    "artifact_id": str(reference.artifact_id),
                    "expected_revision": reference.expected_revision,
                }
            ],
            actor,
        )
        source = reader.one(
            "artifact_versions", id=reference.artifact_id, revision=reference.expected_revision
        )
        lines = source["content"].splitlines()
        require(
            reference.line <= len(lines) and reference.quote in lines[reference.line - 1],
            "LINK_EXACT_REFERENCE_QUOTE_MISMATCH",
        )
    require(
        payload.issue_id == args.issue
        and payload.expected_issue_revision == 6
        and payload.capa_id == issue.capa.id
        and payload.action_id == args.action
        and tuple(payload.output_refs) == tuple(value.ref for value in resolution.outputs)
        and saved["intent_digest"]
        == commands._intent(
            Context(row["tenant_id"], actor, actor),
            SimpleNamespace(operation=LINK, product_id=row["product_id"]),
            payload,
        ),
        "LINK_SEMANTIC_INPUT_OR_OUTPUT_REFS_MISMATCH",
    )
    atom(reader, saved, "capa_remediation_link", LINK, payload, actor)
    proof(reader, saved, LINK, payload, actor)
    require(
        not reader.rows("capa_verification_evidence", issue_id=args.issue),
        "UNEXPECTED_CANDIDATE_EVIDENCE_PRESENT",
    )
    pointer = reader.one("quality_current_issues", issue_id=args.issue)
    require(
        pointer["issue_version_id"] == row["id"] and pointer["issue_revision"] == 6,
        "LINK_ADVANCED_OR_REPLACED_ISSUE_CURRENT",
    )
    checks.extend(
        [
            "link_T1_exact_issue6_action_basis_and_direct_new_formal_output",
            "link_single_receipt_audit_outbox_and_consumed_material_proof",
            "link_keeps_issue_current_no_candidate_no_effectiveness_or_closure",
        ]
    )


class SafeParser(argparse.ArgumentParser):
    def error(self, _):
        self.exit(2, "INVALID_EXPLICIT_CLOSEOUT_ARGUMENTS\n")


def main():
    parser = SafeParser(description=__doc__)
    for field in (
        "marker",
        "issue",
        "issue-v4",
        "root-v5",
        "complete-v6",
        "action",
        "new-preparation-request",
        "new-preparation-version",
        "new-formal-request",
        "new-formal-version",
        "new-link",
    ):
        parser.add_argument(f"--{field}", required=True, type=UUID)
    parser.add_argument("--report-name", default=None)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "server"))
    report = {
        "schema": "wave16-readonly-closeout-v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "not_verified",
        "read_only": True,
        "checks": [],
        "limits": [
            "As-of synthetic evidence observation; not production qualification or manual Exit.",
            "No new scan, confirmation, replay, application, migration or HTTP operation.",
            "OriginalStore read gate may use bounded control locks; no business byte mutation.",
            "Original token preimage and false-to-true same-UOW transition not reconstructed.",
            "Current professional issuer/qualification is not reassessed by this historical check.",
            "Public candidates/integration HTTP projection not executed; physical absence checked.",
        ],
    }
    try:
        from local_environment import read_state
        from pdos_next.evidence_security import ScanLimits, ScanPolicy
        from pdos_next.security_runtime import DockerClamAVTransport
        from pdos_next.service import digest

        seed = private_json(ROOT / ".local/wave15-seed.json")
        prepared = private_json(ROOT / ".local/wave16-seed.json")
        require(
            str(args.issue) == seed["issue_id"] == prepared["scope"]["issue_id"]
            and str(args.action) == prepared["action_binding"]["action_id"]
            and prepared["schema"] == "wave16-explicit-synthetic-preparation-v1"
            and all(
                prepared["scope"][key] == seed[key]
                for key in ("tenant_id", "product_id", "project_id", "actor_id", "capa_id")
            ),
            "EXPLICIT_PRIVATE_PREPARATION_SCOPE_MISMATCH",
        )
        state = target(args, seed, prepared)
        report["selection_sha256"] = digest(
            {k: str(v) for k, v in vars(args).items() if k != "report_name"}
        )
        policy = ScanPolicy(
            version="pdos-local-synthetic-file-policy-v1", limits=ScanLimits(timeout_seconds=60)
        )
        scanner = asyncio.run(DockerClamAVTransport().observe_configuration(policy))
        with readonly(state, seed) as connection:
            reader = reader_type()(connection, seed)
            row, issue = issue_chain(reader, args, seed, prepared, report["checks"])
            original_failure(reader, seed, issue, report["checks"])
            formal = new_draft(reader, args, seed, report["checks"])
            link_check(reader, args, seed, row, issue, formal, report["checks"])
            observed = list(reader.observed.values())
        # A fresh read-only snapshot catches basis changes while bytes were read;
        # this remains an as-of observation, never a durable permission guarantee.
        with readonly(state, seed) as connection:
            fresh = reader_type()(connection, seed)
            for name, limit, filters, fingerprint in observed:
                rows = fresh.rows(name, limit=limit, **filters)
                require(
                    fresh.fingerprint(name, rows) == fingerprint,
                    "BASIS_OR_ACCESS_CHANGED_ACROSS_ORIGINAL_READ",
                )
        final_state = read_state()
        require(
            all(final_state[key] == state[key] for key in ("marker", "container_id", "port"))
            and asyncio.run(DockerClamAVTransport().observe_configuration(policy)) == scanner,
            "MARKED_ENVIRONMENT_OR_SCANNER_CONFIGURATION_CHANGED",
        )
        report["checks"].append("fresh_snapshot_basis_access_container_scanner_unchanged")
        report["status"] = "passed_as_of_read_only_synthetic_scope"
        code = 0
    except Stop as exc:
        report.update(status="failed", reason_code=str(exc))
        code = 1
    except Exception as exc:
        # Includes errors from reused read gates: never print SQL, paths, raw
        # source/clock values, credential URLs, tokens or third-party exception text.
        from wave15_closeout import CloseoutFailure

        reason = str(exc) if isinstance(exc, CloseoutFailure) else ""
        report.update(
            status="failed",
            reason_code=reason
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,120}", reason)
            else "UNVERIFIABLE_SELECTED_EVIDENCE_OR_RUNTIME",
        )
        code = 1
    try:
        name = args.report_name or f"closeout-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        require(
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}\.json", name) is not None,
            "REPORT_BASENAME_NOT_ALLOWED",
        )
        require(
            REPORT.is_dir() and not REPORT.is_symlink(), "EXISTING_SAFE_REPORT_DIRECTORY_REQUIRED"
        )
        # Never overwrite earlier evidence; report is the sole output mutation.
        descriptor = os.open(
            REPORT / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except Exception:
        print('{"status":"failed","reason_code":"SAFE_NEW_REPORT_WRITE_FAILED"}')
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "reason_code": report.get("reason_code"),
                "completed_checks": len(report["checks"]),
            }
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
