"""Thirty actual quality reads, containment confirmations and CAPA candidate inputs.

Invoke through s0_profile_checkpoint.py on the verified independent B8 target.
One real followup_work supplies the upstream execution, failure, Issue and CAPA.
Its preparation, root-cause T2 and action-completion T1 are excluded from samples.
No mock replaces authorization, source IO, qualification, transaction or commit.
"""

# ruff: noqa: F401,F811 -- explicit imports register the existing fixture tree
import json
import os
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from conftest import setup
from pdos_next.domain.capa_effectiveness import candidate_commands
from pdos_next.models import now
from quality_followup_transactions.fixtures import (
    accepted_work,
    complete_command,
    fixed_issue,
    followup_integration_contract,
    followup_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
    root_command,
)
from s0_performance import (
    LOAD_POLICY,
    MAX_ATTEMPTS,
    PerformancePending,
    measure,
    sample_attempts,
    sampling_counts,
)
from s0_source_manifest import snapshot
from test_project_first_plan import accepted, cmd, post
from test_resource_dependency_execution import engines

SAMPLES = 30
CONTAINMENT = "quality.issue.containment.record"
LABELS = (
    "quality_read",
    "quality_containment_inputs",
    "quality_containment_preview",
    "quality_containment_confirmation",
    "capa_candidate_read",
    "capa_candidate_inputs",
)
ROWS = defaultdict(list)
OUTCOME = "pending"
FAILURE_PHASE = None
REPORT_PATH = None
INITIAL_SOURCES = None
MODE = "full"
PENDING_REASON = None


def required_paths():
    return ("quality_containment_confirmation",) if MODE == "containment" else LABELS


def save(*, exclusive=False):
    required = required_paths()
    report = {
        "expected_samples_per_path": SAMPLES,
        "synthetic_only": True,
        "llm_calls": 0,
        "setup_excluded": True,
        "outcome": OUTCOME,
        "failure_phase": FAILURE_PHASE,
        "pending_reason": PENDING_REASON,
        "sampling_mode": MODE,
        "load_policy": LOAD_POLICY,
        "max_attempts_per_phase": MAX_ATTEMPTS,
        "required_paths": required,
        "sampling_counts": sampling_counts(ROWS, required),
        "source_sha256": INITIAL_SOURCES,
        "source_unchanged": snapshot() == INITIAL_SOURCES,
        "fixture_scope": (
            "one actual failure and CAPA; distinct first-submit containment actions; "
            + (
                "completed CAPA candidate context with missing effectiveness evidence"
                if MODE == "full"
                else "CAPA candidate preparation and sampling not run"
            )
        ),
        "excluded_preparation": (
            "upstream fixtures; named root-cause T2; actual action-completion T1; "
            "candidate duty and qualification publications"
            if MODE == "full"
            else "upstream fixtures; real read/input/preview before every actual commit"
        ),
        "commit_transport": "authenticated category-root common commands",
        "candidate_semantics": (
            "current allowed incomplete-candidate read and inputs; "
            "no effectiveness decision or Issue closure"
            if MODE == "full"
            else "not run in containment iteration"
        ),
        "samples": {label: ROWS[label] for label in required},
        "preparation_samples": {
            label: rows for label, rows in ROWS.items() if label not in required
        },
        "preparation_in_iteration_metrics": False,
        "all_observations_successful": all(
            row.get("success") is True for rows in ROWS.values() for row in rows
        ),
    }
    with REPORT_PATH.open("x" if exclusive else "w") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


@pytest.fixture
def performance_work(request):
    """Persist pending before preparing the real fixture; preserve setup failure."""
    global OUTCOME, FAILURE_PHASE, REPORT_PATH, INITIAL_SOURCES, MODE, PENDING_REASON
    directory = Path(os.environ["S0_PERFORMANCE_DIRECTORY"]).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    REPORT_PATH = directory / "quality-samples.json"
    if REPORT_PATH.exists():
        raise RuntimeError("Preserve completed quality performance evidence")
    MODE = os.environ.get("S0_B5_PERFORMANCE_MODE", "full")
    if MODE not in {"full", "containment"}:
        raise ValueError("S0_B5_PERFORMANCE_MODE must be full or containment")
    ROWS.clear()
    PENDING_REASON = None
    OUTCOME, FAILURE_PHASE = "pending", None
    INITIAL_SOURCES = snapshot()
    save(exclusive=True)
    try:
        return request.getfixturevalue("followup_work")
    except BaseException:
        OUTCOME, FAILURE_PHASE = "failed", "fixture_setup"
        save()
        raise


def require(condition):
    if not condition:
        raise AssertionError("Actual quality performance response failed its business guard")


def timed(work, label, callback, validate):
    sample = {}
    try:
        value, sample = measure(work.setup, label, callback)
        validate(value)
    except Exception as error:
        ROWS[label].append(
            {
                **getattr(error, "performance_sample", sample),
                "success": False,
                "error_type": type(error).__name__,
            }
        )
        save()
        raise
    ROWS[label].append({**sample, "success": True})
    save()
    return value


def quality_path(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution"


def read_quality(work):
    return work.quality.client.get(
        quality_path(work),
        headers=work.quality.headers,
        params={"run_id": str(work.failure_run.id), "build_id": work.build_id},
    )


def require_quality(work, value, revision):
    pointer = value["current_by_issue"][str(work.issue_id)]
    require(pointer["revision"] == revision)
    current = next(row for row in value["issues"] if row["id"] == pointer["issue_version_id"])
    require(
        current["issue_id"] == str(work.issue_id)
        and current["revision"] == revision
        and current["is_current"] is True
        and current["source_status"] == "current"
        and current["status"] == "actioning"
        and current["issue"]["capa"]["id"] == str(work.capa_id)
        and current["capabilities"][CONTAINMENT] is True
        and bool(current["failures"])
        and all(row["available"] is True for row in current["failures"])
    )


def require_inputs(value, operation):
    require(
        value["operation"] == operation
        and value["allowed"] is True
        and bool(value["required_source_read_set"])
        and value["authority"]["authorized"] is True
        and value["authority"]["qualified"] is True
    )


def sample_containment(work, index, revision, receipts):
    timed(
        work,
        "quality_read",
        lambda: read_quality(work),
        lambda value: require_quality(work, value, revision),
    )
    source = work.containment_source.model_dump(mode="json")
    action_id = str(uuid4())
    value = cmd(
        work.quality,
        CONTAINMENT,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": revision,
            "action": {
                "id": action_id,
                "text": f"Synthetic personally observed containment sample {index + 1}.",
                "executor_id": str(work.quality.human),
                "evidence": [source],
                "at": {
                    "occurred_at": now().isoformat(),
                    "original_timezone": "UTC",
                    "source": source,
                },
            },
        },
    )
    inputs = timed(
        work,
        "quality_containment_inputs",
        lambda: work.quality.client.post(
            quality_path(work) + "/inputs", headers=work.quality.headers, json=value
        ),
        lambda response: require_inputs(response, CONTAINMENT),
    )
    value["source_read_set"] = inputs["required_source_read_set"]

    def require_preview(response):
        prepared = response["command"]
        require(
            prepared["operation"] == CONTAINMENT
            and prepared["command_id"] == value["command_id"]
            and prepared["idempotency_key"] == value["idempotency_key"]
            and prepared["payload"]["action"]["id"] == action_id
            and prepared["payload"]["expected_issue_revision"] == revision
            and bool(prepared["payload"]["confirmation_token"])
        )

    preview = timed(
        work,
        "quality_containment_preview",
        lambda: post(work.quality, value, preview=True),
        require_preview,
    )
    prepared = preview["command"]

    def require_receipt(response):
        UUID(response["id"])
        require(
            response["id"] not in receipts
            and response["operation"] == CONTAINMENT
            and response["subject_type"] == "quality_issue"
            and response["subject_revision"] == revision + 1
            and response["result"]["issue_id"] == str(work.issue_id)
        )

    saved = timed(
        work,
        "quality_containment_confirmation",
        lambda: post(work.quality, prepared),
        require_receipt,
    )
    receipts.add(saved["id"])
    return revision + 1


def prepare_candidates(work):
    accepted(work.quality, root_command(work))
    accepted(work.quality, complete_command(work, (0, 1)))
    current = fixed_issue(work)
    require(current.status == "awaiting_verification")
    require(current.issue_snapshot["root_cause"] is not None)
    require(
        all(
            action["completion"] is not None for action in current.issue_snapshot["capa"]["actions"]
        )
    )
    # Independent current candidate credentials do not rewrite the saved Start.
    for kind in ("duty", "qualification"):
        import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=[candidate_commands.OPERATION],
            external_id=f"synthetic-b5-candidate-{work.issue_id}-{kind}",
            valid_from=(now() - timedelta(minutes=1)).isoformat(),
            valid_until=(now() + timedelta(hours=2)).isoformat(),
        )
    return current


def sample_candidates(work, index, current):
    root = f"/v1/categories/{work.setup.category}/products/{work.setup.product}"

    def require_current(response):
        host = response["host"]
        require(
            host["allowed"] is True
            and host["source_status"] == "current"
            and host["current_evaluation"] == "evaluated_current"
            and host["scope"]["issue_id"] == str(work.issue_id)
            and host["scope"]["capa_id"] == str(work.capa_id)
            and host["scope"]["current_issue"]
            == {"id": str(current.id), "revision": current.revision}
            and host["authority"]["authorized"] is True
            and host["authority"]["qualified"] is True
            and bool(host["required_source_read_set"])
        )

    timed(
        work,
        "capa_candidate_read",
        lambda: work.quality.client.get(
            root + "/capa-candidates",
            headers=work.quality.headers,
            params={"issue_id": str(work.issue_id)},
        ),
        require_current,
    )
    value = cmd(
        work.quality,
        candidate_commands.OPERATION,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": current.revision,
            "capa_id": str(work.capa_id),
            "visibility": "private",
            "reason": f"Read actual incomplete candidate sample {index + 1}.",
        },
    )
    timed(
        work,
        "capa_candidate_inputs",
        lambda: work.quality.client.post(
            root + "/quality-followup/inputs", headers=work.quality.headers, json=value
        ),
        lambda response: require_inputs(response, candidate_commands.OPERATION),
    )


def test_actual_quality_containment_and_completed_capa_candidate(performance_work):
    global OUTCOME, FAILURE_PHASE, PENDING_REASON
    work = performance_work
    phase = "containment_samples"
    try:
        revision = fixed_issue(work).revision
        receipts = set()
        required_containment = required_paths() if MODE == "containment" else LABELS[:4]
        for index in sample_attempts(ROWS, required_containment):
            revision = sample_containment(work, index, revision, receipts)
        # Every replacement is a new real command and effect, including excluded commits.
        require(len(receipts) == len(ROWS["quality_containment_confirmation"]))
        final_read = read_quality(work)
        require(final_read.status_code == 200)
        require_quality(work, final_read.json(), revision)
        if MODE == "full":
            phase = "candidate_preparation"
            current = prepare_candidates(work)
            phase = "candidate_samples"
            for index in sample_attempts(ROWS, LABELS[4:]):
                sample_candidates(work, index, current)
        require(all(row["success"] for rows in ROWS.values() for row in rows))
        require(snapshot() == INITIAL_SOURCES)
    except PerformancePending:
        OUTCOME, FAILURE_PHASE, PENDING_REASON = "pending", phase, "replacement_budget_exhausted"
        save()
        pytest.skip("Performance sampling pending: replacement budget exhausted")
    except Exception:
        OUTCOME, FAILURE_PHASE = "failed", phase
        save()
        raise
    except BaseException:
        OUTCOME, FAILURE_PHASE, PENDING_REASON = "pending", phase, "interrupted"
        save()
        raise
    OUTCOME = "passed"
    save()
