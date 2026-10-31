"""Opt-in same-execution auto_explain capture, exclusively for local PG tests.

Root configures/revokes preload and SET privileges. This module never LOADs,
changes roles/RLS/planner costs, or persists raw logs, query text or parameters.
"""

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime

# Preserve literal/identifier contents and repeated parameter identity. Psycopg
# rewrites named placeholders to $n; values and SQL constants are never erased.
SQL_TOKEN = re.compile(
    r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|%\(([^)]+)\)s|\$(\d+)|\s+|.",
    re.DOTALL,
)
LOG_HEADER = re.compile(
    r"(?m)^[^\n]*?\[(\d+)\]\s+LOG:\s+duration:\s+[\d.]+\s+ms\s+plan:\s*\n"
)
PREFIX = re.compile(r"(?m)^\d{4}-\d\d-\d\d [^\n]*?\[\d+\]\s+(?:LOG:\s+)?")
CONFIG = {
    "auto_explain.log_min_duration": "-1",
    "auto_explain.log_format": "json",
    "auto_explain.log_analyze": "on",
    "auto_explain.log_nested_statements": "off",
    "auto_explain.sample_rate": "1",
    "auto_explain.log_level": "log",
    "auto_explain.log_parameter_max_length": "0",
    "log_parameter_max_length": "0",
}


def normalized_sql(statement):
    identities = {}
    tokens = []
    for token in SQL_TOKEN.finditer(statement):
        name, position = token.group(1, 2)
        if name is not None or position is not None:
            identity = name if name is not None else position
            tokens.append(f"${identities.setdefault(identity, len(identities) + 1)}")
        elif token[0].isspace():
            tokens.append(" ")
        else:
            tokens.append(token[0])
    return "".join(tokens).strip()


def sql_digest(statement):
    return hashlib.sha256(normalized_sql(statement).encode()).hexdigest()


def match_plans(logs, pid, statements, sanitize):
    """Strict PID + complete normalized SQL + order + cardinality attribution.

    Return only sanitized plans. Incomplete/mismatched logs cannot earn credit,
    including identical SQL for successive pools whose bound LIMITs differ.
    """
    plans = []
    invalid = False
    decoder = json.JSONDecoder()
    for header in LOG_HEADER.finditer(logs):
        if int(header[1]) != pid:
            continue
        tail = PREFIX.sub("", logs[header.end() :])
        try:
            raw, _end = decoder.raw_decode(tail.lstrip())
            if isinstance(raw, list) and len(raw) == 1:
                raw = raw[0]
            if not isinstance(raw, dict):
                invalid = True
                continue
            query = raw.get("Query Text", "")
            if not isinstance(query, str) or "semantic_source_ranks" not in query:
                # No other query should be enabled in the bounded capture window.
                invalid = True
                continue
            if not isinstance(raw.get("Plan"), dict) or not isinstance(
                raw["Plan"].get("Actual Loops"), (int, float)
            ):
                invalid = True
                continue
            plans.append((normalized_sql(query), sanitize(raw)))
        except (json.JSONDecodeError, KeyError, TypeError):
            invalid = True
    expected = [normalized_sql(sql) for sql in statements]
    status = (
        "log_plan_invalid"
        if invalid
        else "actual_plan_missing"
        if len(plans) < len(expected)
        else "query_sequence_mismatch"
        if [query for query, _plan in plans] != expected
        else "same_execution_matched"
    )
    return {
        "status": status,
        "backend_pid": pid,
        "expected_statements": len(expected),
        "observed_statements": len(plans),
        "plans": [plan for _query, plan in plans] if status == "same_execution_matched" else [],
    }


def _docker_logs(container, since):
    result = subprocess.run(
        ["docker", "logs", "--since", since, container],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Local auto_explain log read failed")
    # PostgreSQL stderr logging is root's explicit preflight contract. Neither
    # stream is printed or written; a failed read never includes stderr in errors.
    return result.stdout + result.stderr


class AutoPlanCapture:
    def __init__(self, connection):
        self.enabled = os.environ.get("PDOS_ANN_AUTO_PLAN") == "1"
        self.statements = []
        self.active = False
        self.completed = 0
        self.started = datetime.now(UTC).isoformat()
        self.driver = None
        self.pid = None
        self.configuration = {}
        if not self.enabled:
            return
        self.container = os.environ.get("PDOS_ANN_CONTAINER", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.container):
            raise ValueError("Root must provide an explicit local PDOS_ANN_CONTAINER")
        self.driver = connection.connection.driver_connection
        self.pid = self.driver.info.backend_pid
        with self.driver.cursor() as cursor:
            cursor.execute(
                "SELECT " + ",".join(f"current_setting('{name}',true)" for name in CONFIG)
            )
            self.configuration = dict(zip(CONFIG, cursor.fetchone(), strict=True))
        if self.configuration != CONFIG:
            raise AssertionError("Root auto_explain configuration does not match capture contract")

    def _duration(self, value):
        # A separate cursor on exactly the SELECT's driver connection avoids
        # SQLAlchemy hook recursion and leaves its result cursor undisturbed.
        with self.driver.cursor() as cursor:
            cursor.execute(f"SET LOCAL auto_explain.log_min_duration = {value}")

    def before(self, statement):
        if not self.enabled or "semantic_source_ranks" not in statement:
            return
        assert not self.active
        self._duration(0)
        self.active = True
        self.statements.append(statement)

    def after(self, statement):
        if not self.enabled or "semantic_source_ranks" not in statement:
            return
        assert self.active
        self._duration(-1)
        self.active = False
        self.completed += 1

    def close(self):
        if self.active:
            # On a failed SELECT PostgreSQL may already have aborted the local
            # transaction; its rollback resets SET LOCAL. Do not hide that error.
            if not self.driver.closed and self.driver.info.transaction_status.name != "INERROR":
                self._duration(-1)
            self.active = False

    def collect(self, sanitize, *, timeout=6, reader=_docker_logs):
        if not self.enabled:
            return {"status": "replay_only", "plans": [], "enabled": False}
        assert not self.active and self.completed == len(self.statements)
        deadline = time.monotonic() + timeout
        while True:
            try:
                logs = reader(self.container, self.started)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                result = {"status": "log_read_failed", "plans": []}
                break
            result = match_plans(logs, self.pid, self.statements, sanitize)
            # A complete but different sequence cannot become a valid match by
            # receiving more log records. Missing/truncated records may settle.
            if result["status"] in ("same_execution_matched", "query_sequence_mismatch"):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        result.update(enabled=True, configuration=self.configuration)
        return result
