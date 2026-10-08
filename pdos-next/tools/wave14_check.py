"""Bounded root-owned checks; every PostgreSQL child starts on the verified target."""

import ast
import concurrent.futures
import json
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave14-20261002"


def functions(path):
    return [
        f"{path}::{n.name}"
        for n in ast.parse((SERVER / path).read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
    ]


def run_group(key, nodes):
    state = verified(read_state())
    log = REPORT / (key + ".log")
    if log.exists():
        raise RuntimeError("Existing evidence must not be overwritten: " + key)
    start = time.monotonic()
    with log.open("x") as output:
        child = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", *nodes],
            cwd=SERVER,
            env=environment(state),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    value = dict(
        nodes=nodes, exit_code=child.returncode, seconds=round(time.monotonic() - start, 2)
    )
    print(key, child.returncode, flush=True)
    return key, value


mode = sys.argv[1]
if mode == "regression":
    groups = {
        "regression-professional": [
            "tests/professional_authority/test_transactions.py",
            "tests/professional_authority/test_assessment.py",
        ],
        "regression-build": [
            "tests/build_start/test_transactions.py::test_atomic_start_holds_receipt_and_read_projection_do_not_modify_original_plan",
            "tests/build_start/test_transactions.py::test_original_approver_qualification_revoke_restore_aba_invalidates_old_t1",
            "tests/build_start/test_transactions.py::test_source_withdrawal_guards_successful_start_replay_and_keeps_history",
            "tests/build_start/test_rules.py",
            "tests/test_build_start_common.py",
        ],
        "regression-handoff": [
            "tests/sample_handoff/test_transactions.py::test_targeted_execution_projection_preserves_qualification_stop_and_source_guards",
            "tests/sample_handoff/test_transactions.py::test_signer_qualification_revoke_restore_epoch_does_not_revive_readiness",
            "tests/sample_handoff/test_read_context.py",
            "tests/sample_handoff/test_rules.py",
        ],
        "regression-launch": [
            "tests/verification_launch/test_transactions.py::test_fixed_full_accepted_plan_promise_and_atomic_actual_start_leave_old_history",
            "tests/verification_launch/test_transactions.py::test_complete_accepted_scope_and_fixed_resource_binding_cannot_be_shrunk_or_replaced",
            "tests/verification_launch/test_transactions.py::test_build_writer_or_agent_cannot_claim_quality_or_write_run_directly",
            "tests/verification_launch/test_pure.py",
            "tests/test_launch_common.py",
        ],
        "regression-pure": [
            "tests/measurement_evidence",
            "tests/verification_results/test_pure.py",
            "tests/test_resources/test_rules.py",
            "tests/verification_front/test_pure.py",
        ],
    }
elif mode == "regression-recheck":
    groups = {
        "regression-mock-recheck": [
            "tests/test_resources/test_rules.py::test_scope_uses_narrow_sample_port_and_retains_full_binding",
            "tests/build_start/test_rules.py::test_historical_reviewer_epoch_checked_in_own_readonly_context",
            "tests/verification_results/test_pure.py",
        ],
        "regression-launch-recheck": [
            "tests/verification_launch/test_transactions.py::test_fixed_full_accepted_plan_promise_and_atomic_actual_start_leave_old_history",
            "tests/verification_launch/test_transactions.py::test_complete_accepted_scope_and_fixed_resource_binding_cannot_be_shrunk_or_replaced",
            "tests/verification_launch/test_transactions.py::test_build_writer_or_agent_cannot_claim_quality_or_write_run_directly",
            "tests/verification_launch/test_pure.py",
            "tests/test_launch_common.py",
        ],
    }
elif mode in {"new-pg", "results-fixture-recheck", "results-authority-recheck"}:
    selected = (
        functions("tests/verification_results/test_transactions.py")
        + functions("tests/verification_results/test_guards.py")
        + functions("tests/verification_results/test_runtime_guards.py")
    )
    if mode == "new-pg":
        selected += functions("tests/test_retained_execution.py")
    groups = {
        f"{mode}-{i:02}": [node] for i, node in enumerate(selected)
    }
elif mode == "retained-deviation-recheck":
    groups = {mode: [
        "tests/test_retained_execution.py::"
        "test_retained_proof_rejects_new_real_observation_of_configuration_deviation"
    ]}
elif mode == "results-pass-sample-recheck":
    # Classifier-positive flows, the exact raw-value assertion and the private
    # Run denial contract repaired against the actual protected scope.
    groups = {
        f"{mode}-{i:02}": [node]
        for i, node in enumerate([
            "tests/verification_results/test_transactions.py::"
            "test_partial_final_compute_review_disposition_same_chain_retains_prior_execution",
            "tests/verification_results/test_guards.py::"
            "test_full_previously_returned_values_support_final_empty_batch_without_consuming_again",
            "tests/verification_results/test_guards.py::"
            "test_capture_stable_key_and_unknown_original_value_remain_explicit",
            "tests/verification_results/test_guards.py::"
            "test_quality_current_role_and_exact_scope_cannot_be_supplied_by_client_or_agent",
        ])
    }
else:
    raise RuntimeError("Unknown verification selection")
flat = [n for rows in groups.values() for n in rows]
if len(set(flat)) != len(flat):
    raise RuntimeError("Overlapping selection")
(REPORT / (mode + "-selection.json")).write_text(json.dumps(groups, indent=2) + "\n")
results = {}
with concurrent.futures.ThreadPoolExecutor(
    max_workers=4 if mode == "results-authority-recheck" else 6
) as pool:
    pending = [pool.submit(run_group, key, nodes) for key, nodes in groups.items()]
    for future in concurrent.futures.as_completed(pending):
        key, value = future.result()
        results[key] = value
        (REPORT / (mode + "-result.json")).write_text(json.dumps(results, indent=2) + "\n")
if any(v["exit_code"] for v in results.values()):
    raise SystemExit(1)
