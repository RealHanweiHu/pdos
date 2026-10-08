"""Root-run read-only Wave15 closeout; inert on import and never seeds facts.

Each mode needs explicit logical Issue/Change IDs and the existing private seed.
Reports describe as-of observations, not execution permission or production exit.
No HTTP, pytest, migration, repair, marker/effect write, or confirmation occurs.
"""

import argparse
import ast
import asyncio
import hashlib
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
REPO = ROOT.parent
REPORT = REPO / "docs/reports/evidence/pdos-next-wave15-20261002"
MAX_JSON = 8_388_608
MAX_LOG = 16_777_216
MERGE_RECHECK_NODE = (
    "tests/quality_execution/test_transactions.py::"
    "test_one_result_event_with_two_failures_creates_two_then_merge_retains_recheck_block"
)
GRAPH_RECHECK_NODES = (
    "tests/change_execution/test_transactions.py::"
    "test_graph_capture_exact_key_fixed_roots_unknown_facets_expiry_and_qualification_aba",
    "tests/change_execution/test_transactions.py::"
    "test_impact_terminal_outbox_failure_rolls_back_version_pointer_receipt_but_keeps_capture",
)


class CloseoutFailure(RuntimeError):
    """Only fixed diagnostic codes may be exposed; never exception bodies."""


def require(condition, code):
    if not condition:
        raise CloseoutFailure(code)


def checksum(content):
    return hashlib.sha256(content).hexdigest()


def read_file(path, limit=MAX_JSON, *, private=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "UNSAFE_INPUT_FILE")
        if private:
            require(stat.S_IMODE(info.st_mode) == 0o600, "SEED_NOT_PRIVATE_600")
        require(info.st_size <= limit, "INPUT_TOO_LARGE")
        content = handle.read(limit + 1)
        require(len(content) <= limit, "INPUT_TOO_LARGE")
        return content


def read_json(path, *, private=False):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_FIELD")
            result[key] = value
        return result

    return json.loads(read_file(path, private=private), object_pairs_hook=unique)


def manifest(name, expected_count):
    path = REPORT / name
    value = read_json(path)
    files = value["files"]
    require(isinstance(files, dict) and len(files) == expected_count, "CANDIDATE_COUNT_MISMATCH")
    entries = []
    for relative, expected in sorted(files.items()):
        candidate = REPO / relative
        require(
            not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and relative.startswith("pdos-next/")
            and candidate.resolve().is_relative_to(REPO.resolve()),
            "CANDIDATE_PATH_OUT_OF_SCOPE",
        )
        actual = checksum(read_file(candidate, MAX_LOG))
        entries.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual})
    return {
        "record": name,
        "record_sha256": checksum(read_file(path)),
        "files": entries,
        "count": len(entries),
        "matched": all(row["expected_sha256"] == row["actual_sha256"] for row in entries),
    }


def candidates():
    previous = manifest("backend-candidate-source.json", 303)
    history = [previous]
    if (REPORT / "backend-candidate-v2-source.json").exists():
        history.append(manifest("backend-candidate-v2-source.json", 303))
    if (REPORT / "backend-candidate-v3-source.json").exists():
        require(len(history) == 2, "V3_REQUIRES_RETAINED_V2_MANIFEST")
        history.append(manifest("backend-candidate-v3-source.json", 303))
    if (REPORT / "backend-candidate-v4-source.json").exists():
        require(len(history) == 3, "V4_REQUIRES_RETAINED_V3_MANIFEST")
        history.append(manifest("backend-candidate-v4-source.json", 303))
    web_history = [
        manifest("web-candidate-source.json", 138),
        manifest("web-candidate-v2-source.json", 138),
    ]
    if (REPORT / "web-candidate-v3-source.json").exists():
        web_history.append(manifest("web-candidate-v3-source.json", 138))
    return {
        "backend": history[-1],
        "web": web_history[-1],
        "backend_previous": previous,
        "backend_history": history,
        "web_history": web_history,
    }


def record_name(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.-]+", value) is not None,
        "RECHECK_RECORD_PATH_INVALID",
    )
    return value


def delta_stage(old, new, declared, *, version):
    """Each stage binds its own manifest pair and complete affected-node evidence."""
    allowed = {MERGE_RECHECK_NODE} if version == 2 else set(GRAPH_RECHECK_NODES)
    require(allowed <= set(declared), "RECHECK_NODE_NOT_ORIGINAL_SELECTION")
    path = REPORT / f"backend-candidate-v{version}-delta.json"
    if not path.exists():
        return {
            "version": version,
            "status": "pending",
            "reason": f"V{version}_DELTA_NOT_RECORDED",
            "expected_nodes": sorted(allowed),
            "rechecks": [],
            "effective_cases": {},
        }
    value = read_json(path)
    if version == 4:
        retained = value["supersedes_exact_graph_stage"]
        require(
            retained["record"] == "backend-candidate-v3-delta.json"
            and retained["sha256"] == checksum(read_file(REPORT / retained["record"])),
            "V4_RETAINED_FAILED_STAGE_NOT_BOUND",
        )
    require(
        value["previous_manifest"] == old["record"]
        and value["current_manifest"] == new["record"]
        and value["previous_manifest_sha256"] == old["record_sha256"]
        and value["current_manifest_sha256"] == new["record_sha256"],
        "DELTA_MANIFEST_IDENTITY_MISMATCH",
    )
    before = {row["path"]: row["expected_sha256"] for row in old["files"]}
    after = {row["path"]: row["expected_sha256"] for row in new["files"]}
    require(set(before) == set(after), "DELTA_FILE_SCOPE_CHANGED_UNSUPPORTED")
    difference = {key for key in before if before[key] != after[key]}
    changes = value["changes"]
    require(
        difference
        and len(changes) == len(difference)
        and {row["path"] for row in changes} == difference,
        "DELTA_CHANGED_FILES_INCOMPLETE",
    )
    require(
        all(
            row["before_sha256"] == before[row["path"]]
            and row["after_sha256"] == after[row["path"]]
            and isinstance(row.get("reason"), str)
            and row["reason"].strip()
            for row in changes
        ),
        "DELTA_HASH_OR_REASON_MISMATCH",
    )
    entries = value["rechecks"]
    require(isinstance(entries, list) and len(entries) == len(allowed), "AFFECTED_RECHECK_REQUIRED")
    nodes_seen, names_seen = set(), set()
    rechecks, effective, pending, failed = [], {}, False, False
    for entry in entries:
        nodes = entry["nodes"]
        require(
            isinstance(nodes, list)
            and len(nodes) == 1
            and nodes[0] in allowed
            and nodes[0] not in nodes_seen,
            "RECHECK_NODE_NOT_EXACT_AFFECTED_SELECTION",
        )
        nodes_seen.update(nodes)
        selection_file = (
            record_name(entry["selection_file"])
            if version >= 3
            else "merge-history-recheck-selection.json"
        )
        names = [selection_file, record_name(entry["result_file"]), record_name(entry["log_file"])]
        require(len(set(names)) == 3 and not set(names) & names_seen, "RECHECK_RECORD_REUSED")
        if version >= 3:
            prefix = "graph-history-recheck" if version == 3 else "graph-speed-recheck-v4"
            require(
                all(name.startswith(prefix) for name in names),
                "GRAPH_RECORD_PREFIX_REQUIRED",
            )
            for field in ("selection_sha256", "result_sha256", "log_sha256"):
                require(
                    isinstance(entry.get(field), str)
                    and re.fullmatch(r"[0-9a-f]{64}", entry[field]) is not None,
                    "V3_RECHECK_HASH_REQUIRED",
                )
        else:
            require(
                names
                == [
                    "merge-history-recheck-selection.json",
                    "merge-history-recheck-result.json",
                    "merge-history-recheck.log",
                ],
                "V2_MERGE_RECORD_IDENTITY_MISMATCH",
            )
        names_seen.update(names)
        selection_path, result_path, log_path = (REPORT / name for name in names)
        item = {
            "nodes": nodes,
            "selection_file": selection_file,
            "result_file": entry["result_file"],
            "log_file": entry["log_file"],
        }
        if not all(p.exists() for p in (selection_path, result_path, log_path)):
            item["status"] = "pending"
            pending = True
        else:
            hashes = {
                "selection_sha256": checksum(read_file(selection_path)),
                "result_sha256": checksum(read_file(result_path)),
                "log_sha256": checksum(read_file(log_path, MAX_LOG)),
            }
            if version >= 3:
                require(
                    all(entry[field] == actual for field, actual in hashes.items()),
                    "RECHECK_RECORD_HASH_MISMATCH",
                )
            chosen = read_json(selection_path)
            result = read_json(result_path)
            parsed = pytest_log(log_path)
            if version == 4:
                require(
                    entry.get("source_stable") is True and result.get("source_stable") is True,
                    "V4_SOURCE_CHANGED_DURING_RECHECK",
                )
            require(
                chosen["nodes"] == result["nodes"] == nodes
                and chosen["candidate"] == result["candidate"] == new["record"],
                "RECHECK_RESULT_NODE_OR_CANDIDATE_MISMATCH",
            )
            require(type(result["exit_code"]) is int, "RECHECK_EXIT_CODE_INVALID")
            if version >= 3:
                require(
                    chosen["candidate_sha256"]
                    == result["candidate_sha256"]
                    == new["record_sha256"],
                    "RECHECK_CANDIDATE_HASH_MISMATCH",
                )
            expected = sum(expected_cases(node) for node in nodes)
            matched = all(
                any(case == node or case.startswith(node + "[") for node in nodes)
                for case in parsed["cases"]
            )
            item.update(result=result, log=parsed, expected_cases=expected, **hashes)
            if result["exit_code"] == 0 and parsed["summary_counts"] is None:
                item["status"] = "pending"
                pending = True
            else:
                require(
                    result["exit_code"] in {0, 1}
                    and matched
                    and complete_cases(parsed, nodes, expected),
                    "RECHECK_LOG_INCOMPLETE_OR_OUTSIDE_SELECTION",
                )
                if result["exit_code"] == 0:
                    require(
                        len(parsed["cases"]) == parsed["summary_passed"] == expected
                        and set(parsed["cases"].values()) == {"PASSED"},
                        "RECHECK_SUCCESS_COUNTS_MISMATCH",
                    )
                    item["status"] = "passed"
                    for case, status in parsed["cases"].items():
                        require(case not in effective, "DUPLICATE_RECHECK_CASE")
                        effective[case] = status
                else:
                    require("FAILED" in parsed["cases"].values(), "RECHECK_FAILURE_LOG_MISMATCH")
                    item["status"] = "failed_retained"
                    failed = True
        rechecks.append(item)
    require(nodes_seen == allowed, "AFFECTED_RECHECK_INCOMPLETE")
    return {
        "version": version,
        "record": path.name,
        "sha256": checksum(read_file(path)),
        "status": (
            "pending" if pending else "failed_retained" if failed else "passed_affected_nodes_only"
        ),
        "changes": changes,
        "rechecks": rechecks,
        "expected_nodes": sorted(allowed),
        # The graph pair is one stage: neither replacement is effective while
        # the other node is missing/incomplete. Historical reports remain intact.
        "effective_cases": effective if not pending and not failed else {},
        "scope": f"v{version} affected nodes only; no v{version} full joint",
    }


def backend_delta(current, declared):
    """Retain every failed stage; only a complete later exact pair replaces it."""
    history = current["backend_history"]
    if len(history) == 1:
        return {"status": "not_needed", "stages": [], "rechecks": [], "effective_cases": {}}
    stages, effective, case_versions, latest_by_node = [], {}, {}, {}
    for version, (old, new) in enumerate(zip(history, history[1:], strict=False), start=2):
        stage = delta_stage(old, new, declared, version=version)
        stages.append(stage)
        for node in stage["expected_nodes"]:
            latest_by_node[node] = stage
        # Once this exact selection changes, earlier positive evidence cannot
        # stand in for the new candidate while it is pending or failed.
        for case in list(effective):
            if any(case == node or case.startswith(node + "[") for node in stage["expected_nodes"]):
                require(
                    version == 4 and case_versions[case] == 3,
                    "RECHECK_CASE_OVERLAPS_UNAPPROVED_STAGES",
                )
                del effective[case]
                del case_versions[case]
        # A pending earlier stage cannot be bypassed by a later successful one.
        if any(item["status"] == "pending" for item in stages):
            continue
        for case, status in stage["effective_cases"].items():
            require(case not in effective, "RECHECK_CASE_OVERLAPS_STAGES")
            effective[case], case_versions[case] = status, version
    for stage in stages:
        newer = {latest_by_node[node]["version"] for node in stage["expected_nodes"]}
        if min(newer) > stage["version"]:
            stage["superseded_by_exact_stage"] = sorted(newer)
    latest_statuses = {stage["status"] for stage in latest_by_node.values()}
    return {
        "status": "pending"
        if any(stage["status"] == "pending" for stage in stages)
        else "failed_retained"
        if "failed_retained" in latest_statuses
        else "passed_affected_nodes_only",
        "stages": stages,
        "rechecks": [item for stage in stages for item in stage["rechecks"]],
        "effective_cases": effective,
        "case_versions": case_versions,
        "scope": (
            "v1 original complete PG, v2 merge, retained v3 graph outcomes, "
            "latest v4 exact graph pair when present; no later-tree full joint"
        ),
    }


def web_evidence(current, old_helper):
    """Old 35 checks remain historical; the precision delta needs its own 37 checks."""
    history = current["web_history"]
    before = {row["path"]: row["expected_sha256"] for row in history[0]["files"]}
    second = {row["path"]: row["expected_sha256"] for row in history[1]["files"]}
    require(set(before) == set(second), "WEB_V2_FILE_SCOPE_CHANGED")
    label_path = REPORT / "ui-result-label-fix.json"
    label = read_json(label_path)
    component = "pdos-next/web/src/components/builds/build-quality-loop.tsx"
    require(
        {path for path in before if before[path] != second[path]} == {component}
        and label["previous_component_sha256"] == before[component]
        and any(
            entry["path"] == component
            and entry["sha256"] == second[component]
            and entry["changed"] is True
            for entry in label["files"]
        ),
        "WEB_V2_LABEL_DELTA_MISMATCH",
    )
    old_build = read_json(REPORT / "web-v2-build-result.json")
    require(
        old_build["files"] == 138
        and old_build["source_stable"] is True
        and {entry["check"] for entry in old_build["checks"]} == {"lint", "build"}
        and all(entry["exit_code"] == 0 for entry in old_build["checks"]),
        "WEB_V2_BUILD_EVIDENCE_MISMATCH",
    )
    result = {
        "status": "passed_current_checks",
        "previous_helper": old_helper,
        "helper_current": old_helper,
        "v2_label_delta": {"record": label_path.name, "sha256": checksum(read_file(label_path))},
        "v2_build": {
            "record": "web-v2-build-result.json",
            "sha256": checksum(read_file(REPORT / "web-v2-build-result.json")),
            "result": old_build,
        },
    }
    if len(history) == 2:
        return result
    latest = history[2]
    after = {row["path"]: row["expected_sha256"] for row in latest["files"]}
    helper_paths = {
        "pdos-next/web/src/lib/build-quality-loop-view.ts",
        "pdos-next/web/src/lib/build-quality-loop-view.test.ts",
    }
    require(
        set(second) == set(after)
        and {path for path in second if second[path] != after[path]} == helper_paths,
        "WEB_V3_PRECISION_DIFF_MISMATCH",
    )
    delta_path = REPORT / "ui-event-time-precision-fix.json"
    build_path = REPORT / "web-v3-build-result.json"
    if not delta_path.exists() or not build_path.exists():
        return {
            **result,
            "status": "pending",
            "helper_current": None,
            "reason": "WEB_V3_CHECKS_NOT_RECORDED",
        }
    delta, build = read_json(delta_path), read_json(build_path)
    fixed = {entry["path"]: entry["sha256"] for entry in delta["files"]}
    require(
        len(delta["files"]) == 2
        and set(fixed) == set(delta["previous_hashes"]) == helper_paths
        and all(
            fixed[path] == after[path] and delta["previous_hashes"][path] == second[path]
            for path in helper_paths
        ),
        "WEB_V3_PRECISION_SOURCE_MISMATCH",
    )
    require(
        build["candidate_manifest"] == latest["record"]
        and build["candidate_manifest_sha256"] == latest["record_sha256"]
        and build["precision_delta_file"] == delta_path.name
        and build["precision_delta_sha256"] == checksum(read_file(delta_path)),
        "WEB_V3_BUILD_CANDIDATE_MISMATCH",
    )
    log_name = record_name(build["helper_log_file"])
    require(log_name == "ui-helper-v3-checks.log", "WEB_V3_HELPER_LOG_IDENTITY_MISMATCH")
    log_path = REPORT / log_name
    if not log_path.exists():
        return {
            **result,
            "status": "pending",
            "helper_current": None,
            "reason": "WEB_V3_HELPER_LOG_NOT_RECORDED",
        }
    pure_entries = [entry for entry in delta["checks"] if entry["kind"] == "pure_helpers"]
    require(
        len(pure_entries) == 1
        and pure_entries[0]["exit_code"] == 0
        and delta["helper_tests"]["total"] == delta["helper_tests"]["pass"] == 37
        and delta["helper_tests"]["fail"] == 0
        and checksum(read_file(log_path, MAX_LOG))
        == build["helper_log_sha256"]
        == checksum(pure_entries[0]["raw_output"].encode()),
        "WEB_V3_HELPER_EVIDENCE_MISMATCH",
    )
    require(
        build["files"] == 138
        and build["source_stable"] is True
        and len(build["checks"]) == len({entry["check"] for entry in build["checks"]})
        and {"lint", "build"}
        <= {entry["check"] for entry in build["checks"]}
        <= {"typecheck", "lint", "build"}
        and all(
            type(entry["exit_code"]) is int and entry["exit_code"] == 0 for entry in build["checks"]
        ),
        "WEB_V3_BUILD_FAILED_OR_INCOMPLETE",
    )
    result.update(
        helper_current=node_summary(log_name, 37),
        v3_precision_delta={"record": delta_path.name, "sha256": checksum(read_file(delta_path))},
        v3_build={
            "record": build_path.name,
            "sha256": checksum(read_file(build_path)),
            "result": build,
        },
        scope="web v3 precision helper 37 + lint/build; old 35 retained, no browser/Exit claim",
    )
    return result


def target(seed):
    from local_environment import read_state, verified

    state = read_state()
    require(state["port"] == 62513 and state["marker"] == seed["marker"], "TARGET_SCOPE_MISMATCH")
    state = verified(state)
    from sqlalchemy.engine import make_url

    for key in ("admin_url", "app_url"):
        url = make_url(state[key])
        require(
            url.host == "127.0.0.1" and url.port == 62513 and url.database == "pdos_test",
            "TARGET_ENDPOINT_MISMATCH",
        )
    require(
        state["preview_tenant_id"] == seed["tenant_id"]
        and state["preview_product_id"] == seed["product_id"],
        "SEED_SCOPE_MISMATCH",
    )
    return state


@contextmanager
def readonly(state, seed):
    from pdos_next.database import engine_for
    from sqlalchemy import text

    engine = engine_for(state["admin_url"])
    try:
        with engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout='15s'"))
            connection.execute(text("SET LOCAL lock_timeout='5s'"))
            connection.execute(
                text("SELECT set_config('pdos.tenant_id', :tenant, true)"),
                {"tenant": seed["tenant_id"]},
            )
            require(
                connection.execute(text("SHOW transaction_read_only")).scalar_one() == "on",
                "READ_ONLY_REQUIRED",
            )
            require(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "next_0023",
                "HEAD_NOT_23",
            )
            yield connection
    finally:
        engine.dispose()


class Reader:
    def __init__(self, connection, seed):
        from pdos_next.models import Base

        self.connection, self.seed, self.tables = connection, seed, Base.metadata.tables
        self.scope = {key: UUID(seed[key]) for key in ("tenant_id", "product_id", "project_id")}

    def rows(self, name, *, limit=1001, **filters):
        from sqlalchemy import select

        table = self.tables[name]
        filters = {**{k: v for k, v in self.scope.items() if k in table.c}, **filters}
        require(all(key in table.c for key in filters), "TABLE_FIELD_NOT_SUPPORTED")
        query = select(table)
        for key, value in filters.items():
            query = query.where(table.c[key] == value)
        result = [dict(row) for row in self.connection.execute(query.limit(limit)).mappings()]
        require(len(result) < limit, "READ_BOUND_EXCEEDED")
        return result

    def one(self, name, **filters):
        rows = self.rows(name, limit=3, **filters)
        require(len(rows) == 1, "SELECTED_ROW_MISSING_OR_AMBIGUOUS")
        return rows[0]

    def actor_access(self, actor):
        principal = self.one("principals", id=actor)
        grant = self.one("grants", principal_id=actor)
        require(
            principal["active"]
            and principal["kind"] == "human"
            and grant["expires_at"] > datetime.now(UTC),
            "CURRENT_ACTOR_ACCESS_REQUIRED",
        )
        return principal, grant


def atom_payload(reader, row, subject_type):
    from pdos_next.contracts import PAYLOADS

    if subject_type == "test_run":
        value = row["input_snapshot"]["launch_input"]
    elif subject_type == "quality_issue":
        value = row["input_snapshot"]
    elif subject_type == "change_request":
        saved = row["request_snapshot"]
        if row["operation"] == "change.request.create":
            value = {
                key: saved[key] for key in ("title", "reason", "roots", "references", "sources")
            }
            value["visibility"] = row["visibility"]
        else:
            require(row["operation"] == "change.impact.compute", "ATOM_OPERATION_UNSUPPORTED")
            prior = reader.one("change_request_versions", id=row["previous_version_id"])
            old_ids = {item["id"] for item in prior["request_snapshot"]["assessments"]}
            added = [item for item in saved["assessments"] if item["id"] not in old_ids]
            require(len(added) == 1, "ATOM_SINGLE_NEW_ASSESSMENT_REQUIRED")
            assessment = added[0]
            require(
                assessment["request_revision"] == row["previous_revision"],
                "ATOM_ASSESSMENT_PREDECESSOR_MISMATCH",
            )
            value = {
                "change_id": str(row["change_id"]),
                "expected_change_revision": row["previous_revision"],
                "snapshot": {
                    "kind": "graph_snapshot",
                    "id": assessment["graph"]["id"],
                    "revision": assessment["graph"]["revision"],
                },
                "hypotheses": assessment["hypotheses"],
            }
    else:
        raise CloseoutFailure("ATOM_SUBJECT_UNSUPPORTED")
    return PAYLOADS[row["operation"]].model_validate(value)


def atom(reader, row, subject_type, actor):
    from pdos_next.command_handlers import handler
    from pdos_next.service import EVENTS, Context, digest

    receipt = reader.one(
        "action_receipts",
        subject_type=subject_type,
        subject_id=row["id"],
        subject_revision=row["revision"],
        operation=row["operation"],
    )
    require(
        receipt["actor_id"] == receipt["requester_id"] == actor and receipt["run_id"] is None,
        "NAMED_RECEIPT_ACTOR_MISMATCH",
    )
    payload = atom_payload(reader, row, subject_type)
    module = handler(row["operation"])
    ctx = Context(row["tenant_id"], actor, actor)
    command = SimpleNamespace(operation=row["operation"], product_id=row["product_id"])
    # Common Receipt and domain replay fingerprints deliberately have different
    # schemas. Recompute each from the immutable saved semantic input.
    common_intent = digest(
        {
            "operation": row["operation"],
            "product": row["product_id"],
            "payload": module.semantic(payload),
            "named_actor": actor,
            "source_revision": None,
            "private_owner": actor
            if getattr(payload, "visibility", "private") == "private"
            else None,
        }
    )
    require(
        receipt["visibility"] == row["visibility"]
        and receipt["intent_digest"] == common_intent
        and row["intent_digest"] == module._intent(ctx, command, payload),
        "RECEIPT_BINDING_MISMATCH",
    )
    require(
        receipt["result"]["id"] == str(row["id"])
        and receipt["result"]["revision"] == row["revision"],
        "RECEIPT_RESULT_MISMATCH",
    )
    audit = reader.one("audit_entries", receipt_id=receipt["id"])
    event = reader.one("outbox_events", receipt_id=receipt["id"])
    require(
        audit["actor_id"] == actor and audit["operation"] == row["operation"],
        "AUDIT_BINDING_MISMATCH",
    )
    require(
        event["actor_id"] == actor
        and event["type"] == EVENTS[row["operation"]]
        and event["subject_id"] == row["id"]
        and event["subject_revision"] == row["revision"]
        and event["correlation_id"] == receipt["command_id"]
        and event["schema_version"] == 1,
        "OUTBOX_BINDING_MISMATCH",
    )
    return {
        "version_id": str(row["id"]),
        "revision": row["revision"],
        "receipt_id": str(receipt["id"]),
        "audit_id": str(audit["id"]),
        "event_id": str(event["id"]),
    }


def retained(reader, seed):
    from wave15_seed import RETAINED_TABLES, canonical

    baseline = seed.get("retained_before")
    require(
        isinstance(baseline, dict) and set(baseline) == set(RETAINED_TABLES),
        "RETAINED_BASELINE_REQUIRED",
    )
    output = []
    for name in RETAINED_TABLES:
        # Same inventory scope as the original seed; do not narrow old rows to
        # this new demo's project. Product and its reference epoch are excluded.
        table = reader.tables[name]
        from sqlalchemy import select

        query = select(table).where(table.c.tenant_id == UUID(seed["tenant_id"]))
        if "product_id" in table.c:
            query = query.where(table.c.product_id == UUID(seed["product_id"]))
        rows = [dict(row) for row in reader.connection.execute(query.limit(5001)).mappings()]
        require(len(rows) <= 5000, "RETAINED_READ_BOUND_EXCEEDED")
        hashes = {str(row["id"]): checksum(canonical(row).encode()) for row in rows}
        for identity, before in baseline[name].items():
            output.append(
                {
                    "table": name,
                    "id": identity,
                    "before_sha256": before,
                    "current_sha256": hashes.get(identity),
                    "unchanged": hashes.get(identity) == before,
                }
            )
    require(all(row["unchanged"] for row in output), "RETAINED_ROW_CHANGED_OR_MISSING")
    return {
        "table_count": len(RETAINED_TABLES),
        "row_count": len(output),
        "rows": output,
        "scope": "only pre-existing seed rows; new rows and Product reference_epoch excluded",
    }


class ReadOnlyScanGuard:
    """Diagnostic binding adapter; no locks, grants, scanner replies or writes."""

    def __init__(self, reader, original, security, configuration):
        self.reader, self.original, self.security, self.configuration = (
            reader,
            original,
            security,
            configuration,
        )

    def current_configuration(self):
        return self.configuration

    def bind_for_scan(self, reference):
        from pdos_next.evidence_security import ScanBinding
        from pdos_next.originals import object_reference
        from pdos_next.service import digest

        original, state = self.original, self.security
        principal, grant = self.reader.actor_access(self.requester)
        source = self.reader.one("artifact_versions", original_id=original["id"])
        actual = object_reference(SimpleNamespace(**original))
        active = (
            state["source_state"] == state["disposition"] == source["status"] == "active"
            and (original["visibility"] != "private" or original["owner_id"] == self.requester)
            and actual == reference
        )
        return ScanBinding(
            actual,
            original["tenant_id"],
            original["product_id"],
            self.requester,
            state["epoch"],
            digest(
                [
                    grant["id"],
                    grant["can_write"],
                    grant["expires_at"],
                    grant["access_epoch"],
                    principal["active"],
                    principal["access_epoch"],
                ]
            ),
            digest(
                [
                    original["owner_id"],
                    original["visibility"],
                    state["source_state"],
                    state["disposition"],
                ]
            ),
            active,
        )

    def is_current(self, binding):
        self.requester = binding.requester_id
        return binding == self.bind_for_scan(binding.object_ref) and binding.source_active


def original_proof(reader, seed, measurement, capture, run):
    from pdos_next.domain.measurement_evidence.schemas import ReportBinding
    from pdos_next.domain.measurement_evidence.verifier import verify_measurement
    from pdos_next.evidence_security import ScanLimits, ScanPolicy, parsing_gate
    from pdos_next.original_security import decoded_receipt, decoded_request
    from pdos_next.original_store import OriginalStore
    from pdos_next.originals import object_reference, read_registered_bytes
    from pdos_next.schemas.verification.contracts import Measurement
    from pdos_next.security_runtime import DockerClamAVTransport
    from pdos_next.service import digest

    binding = ReportBinding.model_validate(capture["report_binding"])
    source = reader.one("artifact_versions", id=binding.report.id, revision=binding.report.revision)
    # The immutable physical ObjectRef stays at version 1. UploadedOriginal's
    # access/parsing row has its own advancing revision and current safety gate.
    original = reader.one("uploaded_originals", id=binding.original.id)
    physical = object_reference(SimpleNamespace(**original))
    require(
        physical.id == binding.original.id
        and physical.version == binding.original.revision
        and physical.content_sha256 == binding.original.sha256
        and physical.size_bytes == binding.original.size
        and physical.media_type == binding.original.media_type,
        "PHYSICAL_ORIGINAL_BINDING_MISMATCH",
    )
    require(
        source["original_id"] == original["id"]
        and digest(source["content"]) == source["content_hash"]
        and source["owner_id"] == original["owner_id"]
        and source["visibility"] == original["visibility"]
        and source["status"] == "active"
        and original["status"] == "parsed"
        and original["owner_id"] == UUID(seed["actor_id"]),
        "REPORT_SOURCE_BINDING_MISMATCH",
    )
    require(
        original["id"] == UUID(seed["report_upload"]["subject_id"])
        and original["content_hash"] == seed["report"]["sha256"],
        "SEED_REPORT_MISMATCH",
    )
    security = reader.one("original_security", original_id=original["id"])
    request = reader.one(
        "original_scan_requests", id=security["current_request_id"], original_id=original["id"]
    )
    scanned = reader.one(
        "original_scan_results", request_id=request["id"], original_id=original["id"]
    )
    policy = ScanPolicy(
        version="pdos-local-synthetic-file-policy-v1", limits=ScanLimits(timeout_seconds=60)
    )
    configuration = asyncio.run(DockerClamAVTransport().observe_configuration(policy))
    trusted_request = decoded_request(request["binding"])
    receipt = decoded_receipt(scanned["result"], trusted_request)
    gate = parsing_gate(
        trusted_request,
        receipt,
        ReadOnlyScanGuard(reader, original, security, configuration),
        now=datetime.now(UTC),
    )
    require(
        gate.allow_parse
        and scanned["status"] == "clean"
        and security["epoch"] == binding.security_epoch,
        "CURRENT_ORIGINAL_SECURITY_REQUIRED",
    )
    root = ROOT / ".local/objects"
    for path in (
        root,
        root / "journal",
        root / "locks",
        root / "originals",
        root / "lifecycle-runtime-v1",
    ):
        require(path.is_dir() and not path.is_symlink(), "EXISTING_OBJECT_GATE_REQUIRED")
    store = OriginalStore(root)
    try:
        content = read_registered_bytes(
            store,
            object_reference(SimpleNamespace(**original)),
            UUID(seed["tenant_id"]),
            UUID(seed["product_id"]),
        )
    finally:
        store.close()
    require(
        reader.one("uploaded_originals", id=original["id"]) == original
        and reader.one("original_security", original_id=original["id"]) == security
        and reader.one("artifact_versions", id=source["id"]) == source,
        "ORIGINAL_BASIS_CHANGED_DURING_READ",
    )
    guard_after = ReadOnlyScanGuard(reader, original, security, configuration)
    require(
        parsing_gate(trusted_request, receipt, guard_after, now=datetime.now(UTC)).allow_parse,
        "ORIGINAL_GATE_CHANGED_DURING_READ",
    )
    require(
        checksum(content) == original["content_hash"] == binding.original.sha256
        and len(content) == original["byte_count"] == binding.original.size
        and content == seed["report"]["content"].encode(),
        "ACTUAL_REPORT_BYTES_MISMATCH",
    )
    verified = verify_measurement(
        content, binding, Measurement.model_validate(measurement["measurement"]), run
    )
    require(
        digest(verified.model_dump(mode="json")) == digest(measurement["verified_observation"])
        and verified.measurement.raw_value == "11.0000",
        "EXACT_OBSERVATION_PROOF_MISMATCH",
    )
    return {
        "original_id": str(original["id"]),
        "report_artifact_id": str(source["id"]),
        "original_sha256": checksum(content),
        "byte_count": len(content),
        "security_epoch": security["epoch"],
        "scan_request_id": str(request["id"]),
        "scanner_configuration": "actually observed fixed local synthetic image; no new scan",
        "measurement_id": str(measurement["id"]),
        "raw_value": "11.0000",
        "proof_sha256": verified.proof_sha256,
        "nature": "synthetic",
        "permission": "as-of read observation, not an execution authorization",
    }


def read_set(values):
    require(isinstance(values, list) and 1 <= len(values) <= 20, "SOURCE_READ_SET_BOUND_INVALID")
    result = {}
    for value in values:
        require(
            type(value["expected_revision"]) is int and value["expected_revision"] >= 1,
            "SOURCE_READ_REVISION_INVALID",
        )
        identity = str(UUID(value["artifact_id"]))
        require(identity not in result, "SOURCE_READ_DUPLICATE_OR_CONFLICT")
        result[identity] = value["expected_revision"]
    return result


def demo(connection, seed, issue_id, change_id):
    from typing import get_args

    from pdos_next.domain.change_control.rules import compute_impact
    from pdos_next.domain.quality_issues.ports import VerifiedRun
    from pdos_next.domain.quality_issues.rules import failure_ref
    from pdos_next.domain.verification import rules
    from pdos_next.domain.verification_launch.service import _snapshot
    from pdos_next.schemas.change_control.contracts import Facet, GraphSnapshot
    from pdos_next.schemas.quality_issues.contracts import Issue
    from pdos_next.service import digest

    reader = Reader(connection, seed)
    actor, run_id, build_id = UUID(seed["actor_id"]), UUID(seed["run_id"]), UUID(seed["build_id"])
    reader.actor_access(actor)
    identity = reader.one(
        "verification_run_identities",
        id=run_id,
        build_id=build_id,
        request_id=UUID(seed["request_id"]),
    )
    require(identity["owner_id"] == actor, "RUN_OWNER_MISMATCH")
    pointer = reader.one("verification_current_runs", run_id=run_id)
    current = reader.one(
        "verification_run_versions",
        id=pointer["run_version_id"],
        run_id=run_id,
        revision=pointer["run_revision"],
    )
    run, plan = _snapshot(SimpleNamespace(**current))
    require(
        run.result == "fail"
        and len(run.measurements) == len(run.coverage) == 1
        and run.final_result is not None,
        "FINAL_DEFINITE_FAIL_REQUIRED",
    )
    computed, aggregate = rules.compute_results(run, run.measurements, final=True)
    require(aggregate == "fail" and computed[0].result == "fail", "DETERMINISTIC_FAIL_MISMATCH")
    saved_start = reader.one(
        "verification_run_versions", run_id=run_id, revision=2, operation="test.run.start"
    )
    started_run, started_plan = _snapshot(SimpleNamespace(**saved_start))
    require(
        started_run.actual_start is not None
        and started_plan == plan
        and started_run.actual_start == run.actual_start,
        "ACTUAL_START_MISMATCH",
    )
    start_atom = atom(reader, saved_start, "test_run", actor)
    launch_fact = reader.one(
        "verification_launch_facts",
        run_id=run_id,
        run_version_id=saved_start["id"],
        run_revision=2,
        operation="test.run.start",
    )
    require(
        launch_fact["intent_digest"] == saved_start["intent_digest"], "LAUNCH_START_INTENT_MISMATCH"
    )
    occupancies = reader.rows(
        "operational_resource_occupancies",
        owner_kind="test_run",
        owner_execution_id=run_id,
        test_run_id=run_id,
        build_id=build_id,
    )
    usages = reader.rows("sample_run_usages", run_id=run_id, build_id=build_id)
    reservation = reader.one("test_resource_reservations", run_id=run_id, build_id=build_id)
    require(
        len(occupancies) == 2
        and len(usages) == 1
        and reservation["intent_digest"] == saved_start["intent_digest"],
        "START_EFFECT_COUNT_OR_INTENT_MISMATCH",
    )
    for occupied in occupancies:
        require(
            occupied["intent_digest"] == saved_start["intent_digest"]
            and occupied["build_start_id"] is None
            and occupied["window_start"] == plan.window.start
            and occupied["window_finish"] == plan.window.finish,
            "RUN_OCCUPANCY_BINDING_MISMATCH",
        )
    usage = usages[0]
    sample = run.samples[0]
    require(
        usage["intent_digest"] == saved_start["intent_digest"]
        and usage["sample_id"] == sample.id
        and usage["sample_revision"] == sample.revision
        and usage["actual_configuration_id"] == sample.actual_configuration.id
        and usage["actual_configuration_revision"] == sample.actual_configuration.revision
        and usage["window_start"] == plan.window.start
        and usage["window_finish"] == plan.window.finish
        and usage["state"] == ("consumed" if usage["destructive"] else "reserved"),
        "SAMPLE_USAGE_BINDING_MISMATCH",
    )
    reader.one("build_starts", build_id=build_id, status="executing")
    measurement = reader.one("test_measurements", run_id=run_id, id=run.measurements[0].id)
    capture = reader.one("measurement_import_captures", id=measurement["capture_id"], run_id=run_id)
    require(
        digest(measurement["measurement"]) == measurement["measurement_sha256"]
        and measurement["measurement"] == run.measurements[0].model_dump(mode="json"),
        "MEASUREMENT_FIXED_HASH_MISMATCH",
    )
    report = original_proof(reader, seed, measurement, capture, run)
    ip = reader.one("quality_current_issues", issue_id=issue_id)
    issue_versions = sorted(
        reader.rows("quality_issue_versions", issue_id=issue_id), key=lambda v: v["revision"]
    )
    require(
        issue_versions
        and [r["revision"] for r in issue_versions] == list(range(1, ip["issue_revision"] + 1)),
        "ISSUE_CHAIN_GAP",
    )
    latest = issue_versions[-1]
    require(
        latest["id"] == ip["issue_version_id"]
        and latest["writer_id"] == latest["owner_id"] == actor,
        "ISSUE_CURRENT_SCOPE_MISMATCH",
    )
    issue = Issue.model_validate(latest["issue_snapshot"])
    require(
        issue.id == issue_id
        and issue.status == "actioning"
        and issue.root_cause is None
        and issue.closure is None
        and issue.capa is not None
        and issue.capa.effectiveness is None
        and not issue.capa.effectiveness_history
        and all(action.completion is None for action in issue.capa.actions),
        "CAPA_DRAFT_ONLY_REQUIRED",
    )
    require(
        str(issue.capa.id) == seed["capa_id"] and len(issue.failures) == 1,
        "ISSUE_CAPA_SCOPE_MISMATCH",
    )
    original = failure_ref(VerifiedRun(run=run, nature="synthetic"), measurement["id"])
    require(issue.failures[0] == original, "ISSUE_EXACT_FAILURE_MISMATCH")
    failure = reader.one(
        "quality_failure_maps", failure_identity=original.identity, issue_id=issue_id
    )
    require(failure["failure"] == original.model_dump(mode="json"), "FAILURE_MAP_MISMATCH")
    links = reader.rows(
        "quality_event_failure_links", failure_identity=original.identity, issue_id=issue_id
    )
    require(len(links) >= 1, "FAILURE_EVENT_LINK_REQUIRED")
    for link in links:
        require(
            link["failure"] == original.model_dump(mode="json")
            and link["run_id"] == run_id
            and link["measurement_id"] == measurement["id"]
            and link["build_id"] == build_id,
            "FAILURE_EVENT_BINDING_MISMATCH",
        )
        event = reader.one("outbox_events", id=link["event_id"])
        receipt = reader.one("action_receipts", id=event["receipt_id"])
        projection = reader.one("test_result_projections", id=link["projection_id"], run_id=run_id)
        require(
            event["correlation_id"] == receipt["command_id"]
            and receipt["operation"] == "test.result.compute"
            and receipt["subject_id"] == projection["id"]
            and projection["result"] == "fail"
            and projection["basis_sha256"] == link["basis_sha256"],
            "FAILURE_DELIVERY_PROJECTION_MISMATCH",
        )
    issue_atoms = []
    for index, row in enumerate(issue_versions):
        require(
            digest(row["issue_snapshot"]) == row["snapshot_sha256"] and row["writer_id"] == actor,
            "ISSUE_VERSION_HASH_OR_ACTOR_MISMATCH",
        )
        require(
            row["previous_issue_version_id"] == (issue_versions[index - 1]["id"] if index else None)
            and row["previous_revision"] == (index if index else None),
            "ISSUE_PREDECESSOR_MISMATCH",
        )
        issue_atoms.append(atom(reader, row, "quality_issue", actor))
    cp = reader.one("change_request_currents", change_id=change_id)
    versions = sorted(
        reader.rows("change_request_versions", change_id=change_id), key=lambda v: v["revision"]
    )
    require(
        versions
        and [r["revision"] for r in versions] == list(range(1, cp["revision"] + 1))
        and versions[-1]["id"] == cp["version_id"],
        "CHANGE_CURRENT_CHAIN_MISMATCH",
    )
    request = versions[-1]["request_snapshot"]
    require(
        request["status"] == "analysis" and not request["orders"] and request["assessments"],
        "CHANGE_IMPACT_ONLY_REQUIRED",
    )
    fixed = [
        ref
        for ref in (*request["roots"], *request["references"])
        if ref["kind"] in {"issue", "capa"}
    ]
    require(
        fixed
        and all(
            ref["id"] == str(issue_id)
            and ref["revision"] == issue.revision
            and (ref["kind"] != "capa" or ref["key"] == str(issue.capa.id))
            for ref in fixed
        ),
        "CHANGE_FIXED_CURRENT_ISSUE_CAPA_REQUIRED",
    )
    assessments = []
    for saved in request["assessments"]:
        captured = reader.one(
            "change_graph_captures", id=UUID(saved["graph"]["id"]), change_id=change_id
        )
        graph = GraphSnapshot.model_validate(captured["graph_snapshot"])
        require(
            graph.model_dump(mode="json") == saved["graph"]
            and digest(saved["graph"]) == captured["graph_sha256"],
            "FIXED_GRAPH_CAPTURE_MISMATCH",
        )
        expected = compute_impact(graph, saved["request_revision"], saved["hypotheses"]).model_dump(
            mode="json"
        )
        require(
            expected == saved
            and set(get_args(Facet)) <= {item["facet"] for item in saved["unknown"]},
            "DETERMINISTIC_EIGHT_FACET_UNKNOWN_REQUIRED",
        )
        require(
            captured["change_revision"] == saved["request_revision"]
            and captured["owner_id"] == actor
            and read_set(captured["required_source_read_set"]).items()
            <= read_set(versions[-1]["required_source_read_set"]).items(),
            "CAPTURE_SCOPE_OR_READSET_MISMATCH",
        )
        basis_version = next(
            (row for row in versions if row["revision"] == captured["change_revision"]), None
        )
        require(
            basis_version is not None and basis_version["id"] == captured["change_version_id"],
            "CAPTURE_PREDECESSOR_VERSION_MISMATCH",
        )
        require(
            {ref.identity for ref in graph.roots}
            == {
                "{}:{}:{}:{}".format(ref["kind"], ref["id"], ref["revision"], ref.get("key") or "")
                for ref in basis_version["request_snapshot"]["roots"]
            },
            "CAPTURE_FIXED_ROOT_MISMATCH",
        )
        assessments.append(
            {
                "id": saved["id"],
                "capture_id": str(captured["id"]),
                "unknown_facets": sorted({item["facet"] for item in saved["unknown"]}),
                "known_paths": len(saved["known"]),
                "capture_expiry": captured["expires_at"].isoformat(),
                "expiry_note": "historical fixed capture; no new compute authorized by this report",
            }
        )
    change_atoms = []
    for index, row in enumerate(versions):
        require(
            digest(row["request_snapshot"]) == row["request_sha256"]
            and row["owner_id"] == actor
            and row["authority_snapshot"]["subject_id"] == str(actor),
            "CHANGE_VERSION_HASH_OR_ACTOR_MISMATCH",
        )
        require(
            row["previous_version_id"] == (versions[index - 1]["id"] if index else None)
            and row["previous_revision"] == (index if index else None),
            "CHANGE_PREDECESSOR_MISMATCH",
        )
        change_atoms.append(atom(reader, row, "change_request", actor))
    return {
        "run": {
            "id": str(run_id),
            "revision": run.revision,
            "aggregate": aggregate,
            "actual_start": run.actual_start.occurred_at.isoformat(),
            "saved_start_atom": start_atom,
            "launch_fact_id": str(launch_fact["id"]),
            "test_resource_occupancies": [str(r["id"]) for r in occupancies],
            "sample_usages": [str(usage["id"])],
        },
        "report": report,
        "issue": {
            "id": str(issue_id),
            "revision": issue.revision,
            "capa_id": str(issue.capa.id),
            "state": issue.status,
            "root_cause": None,
            "effectiveness": None,
            "closure": None,
            "atoms": issue_atoms,
        },
        "change": {
            "id": str(change_id),
            "revision": cp["revision"],
            "assessments": assessments,
            "orders": [],
            "atoms": change_atoms,
        },
        "retained": retained(reader, seed),
        "not_assessed": [
            "current production qualification",
            "formal ChangeOrder/effectivity",
            "CAPA effectiveness",
            "browser or manual Exit",
            "whole repository regression",
        ],
    }


def expected_cases(node):
    """Static parameter product; unsupported dynamic declarations fail explicitly."""
    relative, function = node.split("::", 1)
    require(
        re.fullmatch(r"tests/[a-z_]+/test_[a-z_]+\.py", relative) is not None
        and re.fullmatch(r"test_[a-z_]+", function) is not None,
        "UNSUPPORTED_SELECTION_NODE",
    )
    tree = ast.parse(read_file(ROOT / "server" / relative).decode())
    matches = [
        item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == function
    ]
    require(len(matches) == 1, "SELECTED_FUNCTION_MISSING")
    count = 1
    for decorator in matches[0].decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "parametrize"
        ):
            require(len(decorator.args) >= 2, "PARAMETER_DECLARATION_UNSUPPORTED")
            try:
                values = ast.literal_eval(decorator.args[1])
            except (ValueError, TypeError, SyntaxError):
                raise CloseoutFailure("DYNAMIC_PARAMETERS_NOT_SUPPORTED") from None
            require(
                isinstance(values, (list, tuple)) and values, "PARAMETER_DECLARATION_UNSUPPORTED"
            )
            count *= len(values)
    return count


def pytest_log(path):
    content = read_file(path, MAX_LOG).decode("utf-8", "replace")
    # Pytest parameter ids may contain spaces; preserve the exact full node id.
    rows = re.findall(
        r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) "
        r"(tests/[A-Za-z0-9_/.]+::[A-Za-z0-9_]+(?:\[[^\r\n]*\])?)\s*$",
        content,
        re.M,
    )
    actual = {}
    for status, node in rows:
        require(node not in actual, "DUPLICATE_LOG_CASE")
        actual[node] = status
    summaries = re.findall(r"^(?:=+\s*)?(\d+) passed(?:[^\n]*) in [^\n]+(?:=+)?\s*$", content, re.M)
    endings = re.findall(
        r"^(?:=+\s*)?((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|"
        r"deselected|warnings?)(?:, )?)+) in [^\n]+$",
        content,
        re.M,
    )
    counts = (
        dict(
            (kind, int(number))
            for number, kind in re.findall(
                r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)",
                endings[-1],
            )
        )
        if endings
        else None
    )
    return {
        "record": path.name,
        "sha256": checksum(content.encode()),
        "cases": actual,
        "summary_passed": int(summaries[-1]) if summaries else None,
        "summary_counts": counts,
    }


def complete_cases(parsed, nodes, expected):
    """A terminated full group is required even when its original result failed."""
    if parsed is None or parsed["summary_counts"] is None:
        return False
    counts = parsed["summary_counts"]
    total = sum(
        number
        for kind, number in counts.items()
        if kind not in {"warning", "warnings", "deselected"}
    )
    actual = parsed["cases"]
    return (
        total == len(actual) == expected
        and all(
            any(case == node or case.startswith(node + "[") for node in nodes) for case in actual
        )
        and all(
            counts.get(kind, 0) == sum(status == label for status in actual.values())
            for kind, label in (
                ("passed", "PASSED"),
                ("failed", "FAILED"),
                ("skipped", "SKIPPED"),
                ("xfailed", "XFAIL"),
                ("xpassed", "XPASS"),
            )
        )
        and counts.get("error", 0) + counts.get("errors", 0)
        == sum(status == "ERROR" for status in actual.values())
    )


def selection():
    chosen = read_json(REPORT / "pg-selection.json")
    results_path = REPORT / "pg-result.json"
    results = read_json(results_path) if results_path.exists() else {}
    require(
        isinstance(chosen, dict)
        and set(chosen) == {f"pg-{i:02d}" for i in range(13)}
        and set(results) <= set(chosen),
        "PG_SELECTION_RESULT_MISMATCH",
    )
    declared = [node for group in chosen.values() for node in group]
    require(
        len(set(declared)) == len(declared) == 13
        and chosen["pg-02"] == [MERGE_RECHECK_NODE]
        and chosen["pg-11"] == [GRAPH_RECHECK_NODES[0]]
        and chosen["pg-12"] == [GRAPH_RECHECK_NODES[1]],
        "ORIGINAL_13_GROUP_SELECTION_CHANGED",
    )
    groups, all_cases, pending, failed = {}, {}, [], []
    for group, nodes in chosen.items():
        require(
            re.fullmatch(r"pg-\d{2}", group) is not None and isinstance(nodes, list) and nodes,
            "PG_GROUP_NAME_OR_NODES_INVALID",
        )
        expected = sum(expected_cases(node) for node in nodes)
        record = results.get(group)
        log_path = REPORT / (group + ".log")
        parsed = pytest_log(log_path) if log_path.exists() else None
        completed = bool(
            record is not None
            and record["nodes"] == nodes
            and type(record["exit_code"]) is int
            and record["exit_code"] in {0, 1}
            and complete_cases(parsed, nodes, expected)
        )
        value = {
            "nodes": nodes,
            "expected_cases": expected,
            "result": record,
            "log": parsed,
            "original_completed": completed,
        }
        if record is None:
            value["status"] = "pending"
            pending.append(group)
        elif record["nodes"] != nodes or type(record["exit_code"]) is not int:
            value["status"] = "failed"
            failed.append(group)
        elif not completed:
            value["status"] = "incomplete_evidence"
            pending.append(group)
        else:
            actual = parsed["cases"]
            passed = (
                record["exit_code"] == 0
                and len(actual) == expected == parsed["summary_passed"]
                and set(actual.values()) == {"PASSED"}
            )
            if not passed:
                value["status"] = "coverage_or_status_mismatch"
                failed.append(group)
            else:
                value["status"] = "passed"
            for case, outcome in actual.items():
                require(case not in all_cases, "DUPLICATE_PG_CASE_BETWEEN_GROUPS")
                all_cases[case] = outcome
        groups[group] = value
    require(
        sum(value["expected_cases"] for value in groups.values()) == 14,
        "ORIGINAL_14_CASE_SELECTION_CHANGED",
    )
    # Separate scopes; never sum these as an entire repository regression.
    pure_selection = read_json(REPORT / "pure-selection.json")
    pure_result = read_json(REPORT / "pure-result.json")
    require(
        set(pure_selection) == set(pure_result) == {"root-pure"}, "PURE_SELECTION_RESULT_MISMATCH"
    )
    pure = pytest_log(REPORT / "root-pure.log")
    pure_meta = pure_result["root-pure"]
    require(
        pure_meta["nodes"] == pure_selection["root-pure"]
        and pure_meta["exit_code"] == 0
        and pure["summary_passed"] == len(pure["cases"]) == 81
        and set(pure["cases"].values()) == {"PASSED"},
        "PURE_81_EVIDENCE_MISMATCH",
    )
    require(
        all(
            any(case.startswith(node + "::") for node in pure_meta["nodes"])
            for case in pure["cases"]
        ),
        "PURE_CASE_OUTSIDE_SELECTION",
    )
    bff = node_summary("bff-pure-tests.log", 24)
    helper = node_summary("ui-helper-checks.log", 35)
    current = candidates()
    require(current["backend"]["matched"] and current["web"]["matched"], "CANDIDATE_HASH_CHANGED")
    helper_freeze = read_json(REPORT / "ui-component-check.json")
    helper_entry = [entry for entry in helper_freeze["checks"] if entry["kind"] == "pure_helper"]
    require(
        len(helper_entry) == 1
        and helper_entry[0]["exit_code"] == 0
        and helper_entry[0]["tests"] == helper_entry[0]["pass"] == 35
        and helper_entry[0]["fail"] == helper_entry[0]["skipped"] == 0,
        "HELPER_FREEZE_MISMATCH",
    )
    for entry in helper_freeze["files"]:
        if entry["path"].endswith(
            ("build-quality-loop-view.ts", "build-quality-loop-view.test.ts")
        ):
            require(
                all(
                    any(
                        row["path"] == entry["path"] and row["expected_sha256"] == entry["sha256"]
                        for row in historical["files"]
                    )
                    for historical in current["web_history"][:2]
                ),
                "HISTORICAL_HELPER_SOURCE_MISMATCH",
            )
    web_checks = web_evidence(current, helper)
    if web_checks["status"] == "pending":
        pending.append("web-v3-affected-checks")
    delta = backend_delta(current, declared)
    replacement = delta["effective_cases"]
    original_finished = all(value["original_completed"] for value in groups.values())
    if delta["status"] == "pending":
        pending.append("backend-delta-recheck")
    elif delta["status"] == "failed_retained":
        failed.append("backend-delta-recheck")
    for group, value in groups.items():
        parsed, result = value["log"], value["result"]
        # All original 13 groups/14 cases must finish before any later replacement.
        if not original_finished or parsed is None or result is None:
            continue
        effective = dict(parsed["cases"])
        covered = {
            case: status
            for case, status in replacement.items()
            if any(case == node or case.startswith(node + "[") for node in value["nodes"])
        }
        if not covered:
            awaiting = [
                stage["version"]
                for stage in delta.get("stages", [])
                if stage["status"] == "pending"
                and set(value["nodes"]) <= set(stage["expected_nodes"])
            ]
            if awaiting and group in failed:
                value["original_status"] = value["status"]
                value["status"] = f"pending_affected_v{max(awaiting)}_recheck"
                failed.remove(group)
                pending.append(group)
            continue
        require(
            result["nodes"] == value["nodes"] and result["exit_code"] in {0, 1},
            "ORIGINAL_REPLACED_GROUP_INCOMPLETE",
        )
        require(
            complete_cases(parsed, value["nodes"], value["expected_cases"]),
            "ORIGINAL_REPLACED_LOG_NOT_FINISHED",
        )
        effective.update(covered)
        require(
            all(
                any(case == node or case.startswith(node + "[") for node in value["nodes"])
                for case in effective
            ),
            "EFFECTIVE_CASE_OUTSIDE_SELECTION",
        )
        if len(effective) == value["expected_cases"] and set(effective.values()) == {"PASSED"}:
            versions = sorted({delta["case_versions"][case] for case in covered})
            value["original_status"] = value["status"]
            value["status"] = f"passed_with_exact_v{max(versions)}_replacement"
            value["replacement_versions"] = versions
            value["effective_cases"] = effective
            pending = [item for item in pending if item != group]
            failed = [item for item in failed if item != group]
            all_cases.update(effective)
    return {
        "status": "failed" if failed else "pending" if pending else "passed_selected_scopes",
        "pg": {
            "original_records": {
                "selection_file": "pg-selection.json",
                "selection_sha256": checksum(read_file(REPORT / "pg-selection.json")),
                "result_file": "pg-result.json",
                "result_sha256": checksum(read_file(results_path))
                if results_path.exists()
                else None,
                "candidate": "backend-candidate-source.json",
            },
            "groups": groups,
            "expected_parameterized_cases": sum(
                value["expected_cases"] for value in groups.values()
            ),
            "completed_unique_passed_cases": sum(value == "PASSED" for value in all_cases.values()),
            "all_original_groups_finished": original_finished,
            "pending_groups": pending,
            "failed_groups": failed,
        },
        "separate_evidence": {
            "backend_pure": {
                "result": pure_meta,
                "log": pure,
                "candidate": "backend-candidate-source.json",
                "scope": "original v1 81 pure checks; not a v2/v3 pure joint claim",
            },
            "bff_pure": bff,
            "ui_helper_pure": web_checks["helper_current"],
            "ui_helper_previous": helper,
            "ui_helper_previous_freeze": {
                "record": "ui-component-check.json",
                "sha256": checksum(read_file(REPORT / "ui-component-check.json")),
            },
        },
        "candidates": current,
        "backend_delta": delta,
        "web_affected_checks": web_checks,
        "scope_note": (
            "Selected Wave15 PG and separate original 81 backend/24 BFF/current UI helper scopes; "
            "old UI 35 never replaces web-v3 37. No all-repository union, "
            "v2/v3 full joint, browser, production qualification, or manual Exit claim"
        ),
    }


def node_summary(name, expected):
    content = read_file(REPORT / name, MAX_LOG).decode("utf-8", "replace")
    numbers = {}
    for key, value in re.findall(
        r"^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", content, re.M
    ):
        require(key not in numbers, "DUPLICATE_NODE_SUMMARY")
        numbers[key] = int(value)
    require(
        numbers.get("tests") == numbers.get("pass") == expected
        and all(numbers.get(key) == 0 for key in ("fail", "cancelled", "skipped", "todo")),
        "NODE_EVIDENCE_COUNT_MISMATCH",
    )
    return {
        "record": name,
        "sha256": checksum(content.encode()),
        "summary": numbers,
        "scope": "separate no-DB host-substituted checks",
    }


def publish(name, report, status):
    """Never replace historical or final output; pending attempts get unique names."""
    label = (
        name
        if status == "passed"
        else name.removesuffix(".json")
        + "."
        + status
        + "-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        + ".json"
    )
    path = REPORT / label
    encoded = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    require(len(encoded) <= 2_000_000, "OUTPUT_TOO_LARGE")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("demo", "selection"))
    parser.add_argument("--issue", required=True, type=UUID)
    parser.add_argument("--change", required=True, type=UUID)
    args = parser.parse_args()
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "read_only": True,
        "limitations": [
            "as_of evidence observation is not an execution permit",
            "existing OriginalStore read gate may acquire/create bounded control locks only",
            "no production or manual Exit claim",
        ],
    }
    filename = "demo-closure.json" if args.mode == "demo" else "final-selection.json"
    code, status = 1, "failed"
    try:
        sys.path.insert(0, str(ROOT / "server"))
        seed = read_json(ROOT / ".local/wave15-seed.json", private=True)
        require(str(args.issue) == seed["issue_id"], "EXPLICIT_ISSUE_NOT_SEED_ISSUE")
        # Parse only selected UUIDs; credentials and the recovery request bodies
        # never enter report/error output and Demo is never constructed.
        for key in (
            "marker",
            "tenant_id",
            "product_id",
            "project_id",
            "actor_id",
            "run_id",
            "build_id",
            "request_id",
        ):
            UUID(seed[key])
        state = target(seed)
        initial = (state["marker"], state["container_id"], state["port"])
        with readonly(state, seed) as connection:
            if args.mode == "demo":
                report["checks"] = demo(connection, seed, args.issue, args.change)
                report["candidates"] = candidates()
                require(
                    report["candidates"]["backend"]["matched"]
                    and report["candidates"]["web"]["matched"],
                    "CANDIDATE_HASH_CHANGED",
                )
                status, code = "passed", 0
            else:
                # Even selection-only has an explicit verified head/scope guard;
                # it does not start pytest or query arbitrary business histories.
                selected = Reader(connection, seed)
                selected.actor_access(UUID(seed["actor_id"]))
                selected.one(
                    "verification_run_identities",
                    id=UUID(seed["run_id"]),
                    build_id=UUID(seed["build_id"]),
                    owner_id=UUID(seed["actor_id"]),
                )
                selected.one("quality_current_issues", issue_id=args.issue)
                chosen_change = selected.one("change_request_currents", change_id=args.change)
                selected.one(
                    "change_request_versions",
                    id=chosen_change["version_id"],
                    owner_id=UUID(seed["actor_id"]),
                )
                report["checks"] = selection()
                outcome = report["checks"]["status"]
                status, code = (
                    ("pending", 2)
                    if outcome == "pending"
                    else ("failed", 1)
                    if outcome == "failed"
                    else ("passed", 0)
                )
        final = target(seed)
        require(
            initial == (final["marker"], final["container_id"], final["port"]), "TARGET_CHANGED"
        )
        report["target"] = {
            "port": 62513,
            "head": "next_0023",
            "marker": state["marker"],
            "tenant_id": seed["tenant_id"],
            "product_id": seed["product_id"],
            "project_id": seed["project_id"],
            "actor_id": seed["actor_id"],
            "run_id": seed["run_id"],
            "build_id": seed["build_id"],
            "issue_id": str(args.issue),
            "change_id": str(args.change),
        }
    except Exception as error:
        # Public exception strings may contain SQL parameters/private paths.
        report["error_code"] = (
            str(error)
            if isinstance(error, CloseoutFailure)
            else "CHECK_UNAVAILABLE_" + type(error).__name__
        )
        status, code = "failed", 1
    report["status"] = status
    try:
        written = publish(filename, report, status)
    except FileExistsError:
        print("Existing closeout evidence preserved; output not overwritten.", file=sys.stderr)
        return 1
    print(json.dumps({"mode": args.mode, "status": status, "record": written, "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
