"""Actual fixed baseline children, without fabricating a history cursor/page.

Root alone runs this case on explicitly verified isolated pdos_test URLs. Four
confirmed saves are sufficient for fixed-document reading. The actual history
page size is 50; this case deliberately does not claim a real cross-page run.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from manufacturing_preparation_transactions.fixtures import (
    bootstrap_authority,
    inputs,
    payload,
)
from manufacturing_preparation_transactions.fixtures import manufacturing_case as manufacturing_case
from manufacturing_preparation_transactions.test_transactions import reference, save
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_build_project_scope import second_project_configuration
from test_builds import configuration as configuration
from test_project_first_plan import cmd
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project

from pdos_next.capa_history import PAGE_SIZE
from pdos_next.models import Artifact
from pdos_next.safety import verify_test_target
from pdos_next.service import digest
from tests.ui import test_project_manufacturing_preparation_projection_pg as prior_ui


def _get(work, *, fixed=None, actor=None, history_cursor=None):
    path = (
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
        "/manufacturing-preparations"
    )
    if fixed is None:
        params = {"project_id": str(work.project_id)}
        if history_cursor is not None:
            params["history_cursor"] = history_cursor
    else:
        path += f"/{fixed['kind']}/{fixed['id']}"
        params = {"revision": fixed["revision"]}
    response = work.setup.client.get(
        path,
        params=params,
        headers={"Authorization": f"Bearer {work.setup.tokens[actor or work.setup.human]}"},
    )
    return {
        "path": path,
        "params": params,
        "status_code": response.status_code,
        "body": response.json(),
    }


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _phase(work, phase, readers):
    before = prior_ui._counts(work)
    reads = {name: reader() for name, reader in readers.items()}
    after = prior_ui._counts(work)
    assert before == after
    page = _ok(reads["project_preparations"])
    assert page["has_more"] is False and page["history_page"]["next_cursor"] is None
    assert page["unavailable_count"] == 0
    return {
        "phase": phase,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _bindings(baseline, documents):
    actual = {
        (row["operation_key"], row["kind"], row["id"], row["revision"], row["body_sha256"])
        for row in baseline["body"]["document_bindings"]
    }
    expected = {
        (row["operation_key"], row["kind"], row["id"], row["revision"], digest(row["body"]))
        for row in documents
    }
    assert actual == expected


def _cross_project_guard(work, other, documents):
    # The fixed GET has no project selector; this separate read-only inputs
    # request is the actual owner gate for forbidden cross-project references.
    body = payload(work, "manufacturing_baseline", documents=documents)
    body.update(
        project_id=other["project"], process={"id": other["process"]["subject_id"], "revision": 1}
    )
    request = cmd(work.setup, "npi.manufacturing_baseline.record", body)
    path = (
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
        "/manufacturing-preparations/inputs"
    )
    before = prior_ui._counts(work)
    response = work.setup.client.post(path, headers=work.setup.headers, json=request)
    after = prior_ui._counts(work)
    assert before == after
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
    assert "资料不能跨项目" in json.dumps(response.json(), ensure_ascii=False)
    return {
        "method": "POST",
        "path": path,
        "status_code": response.status_code,
        "body": response.json(),
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
        "purpose": "Cross-project reference gate only; this is not a UI GET DTO.",
    }


def _export(work, scope, phases, guard_checks, receipts):
    destination = os.environ.get("PDOS_UI_PREPARATION_HISTORY_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual fixed-child DTO export requires an absolute path"
    bundle = {
        "version": "project-preparation-history-projection-qa/v1",
        "fixture_nature": "actual commands/GETs with bounded synthetic manufacturing facts",
        "scope": scope,
        "phases": phases,
        "guard_checks": guard_checks,
        "command_receipts": receipts,
        "history_coverage": {
            "actual_server_page_size": PAGE_SIZE,
            "actual_cross_page_verified": False,
            "valid_server_next_cursor_observed": False,
        },
        "limitations": [
            "Every phase read body/status is an original unmodified actual GET response.",
            "Four saves do not exceed 50 historical rows; no valid cursor is invented.",
            "Invalid history_cursor rejection does not establish real cross-page reading.",
            "The baseline fixes WI v1 and CP v1 even after the WI series advances to v2.",
            "Body hashes and exact fixed refs are compared without substituting current documents.",
            "Source withdrawal uses the precise negative Artifact fixture, not a user command.",
            "Only that Artifact status changes; body, relations and Current stay fixed.",
            "The separate inputs POST checks cross-project rejection and is not a UI GET source.",
            "Saved gaps/current/source status confer no release or real qualification.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_fixed_preparation_children_keep_old_body_after_revision_and_source_withdrawal(
    manufacturing_case,
):
    assert PAGE_SIZE == 50, "Reassess actual history coverage if the shared page contract changes"
    work, phases, receipts = manufacturing_case, [], {}
    setup = work.setup
    other = second_project_configuration(setup, work.config)
    bootstrap_authority(work)

    def document(kind, body):
        _, receipt, view = save(work, inputs(work, kind, body))
        receipts[view["id"]] = receipt
        return view

    wi_v1 = document("work_instruction", payload(work, "work_instruction"))
    cp_v1 = document("control_plan", payload(work, "control_plan"))
    children = {"work_instruction": reference(wi_v1), "control_plan": reference(cp_v1)}
    baseline = document(
        "manufacturing_baseline", payload(work, "manufacturing_baseline", documents=children)
    )
    initial = _phase(
        work,
        "baseline_fixed_children_before_revision",
        {
            "project_preparations": lambda: _get(work),
            "fixed_baseline": lambda: _get(work, fixed=baseline),
            "fixed_wi_v1": lambda: _get(work, fixed=wi_v1),
            "fixed_cp_v1": lambda: _get(work, fixed=cp_v1),
        },
    )
    phases.append(initial)
    assert _ok(initial["reads"]["fixed_baseline"]) == baseline
    _bindings(baseline, (wi_v1, cp_v1))
    guard_checks = {
        "cross_project_baseline": _cross_project_guard(work, other, children),
    }
    wi_v2 = document(
        "work_instruction", payload(work, "work_instruction", previous=wi_v1, revision=2)
    )
    wrong_revision = {"kind": "work_instruction", "id": wi_v1["id"], "revision": 2}
    revised = _phase(
        work,
        "wi_current_v2_baseline_children_still_v1",
        {
            "project_preparations": lambda: _get(work),
            "fixed_baseline": lambda: _get(work, fixed=baseline),
            "fixed_wi_v1": lambda: _get(work, fixed=wi_v1),
            "fixed_wi_v2": lambda: _get(work, fixed=wi_v2),
            "fixed_cp_v1": lambda: _get(work, fixed=cp_v1),
            "wrong_wi_revision": lambda: _get(work, fixed=wrong_revision),
            "peer_private_wi": lambda: _get(work, fixed=wi_v1, actor=setup.peer),
            "foreign_baseline": lambda: _get(work, fixed=baseline, actor=setup.other_human),
            "invalid_history_cursor": lambda: _get(work, history_cursor="not-a-history-cursor"),
        },
    )
    phases.append(revised)
    saved_wi = _ok(revised["reads"]["fixed_wi_v1"])
    saved_cp = _ok(revised["reads"]["fixed_cp_v1"])
    saved_baseline = _ok(revised["reads"]["fixed_baseline"])
    assert saved_wi["body"] == wi_v1["body"] and saved_wi["revision"] == 1
    assert saved_wi["is_current"] is False and saved_wi["source_status"] == "current"
    assert _ok(revised["reads"]["fixed_wi_v2"])["is_current"] is True
    assert saved_baseline["body"] == baseline["body"]
    assert (
        saved_baseline["is_current"] is True and saved_baseline["source_status"] == "needs_recheck"
    )
    _bindings(saved_baseline, (saved_wi, saved_cp))
    for name, status, code in (
        ("wrong_wi_revision", 409, "VERSION_CONFLICT"),
        ("peer_private_wi", 403, "FORBIDDEN_SCOPE"),
        ("foreign_baseline", 403, "FORBIDDEN_SCOPE"),
        ("invalid_history_cursor", 422, "VALIDATION_FAILED"),
    ):
        response = revised["reads"][name]
        assert response["status_code"] == status, response
        assert response["body"]["code"] == code
    assert (
        revised["reads"]["invalid_history_cursor"]["body"]["detail"]["reason"] == "INVALID_REQUEST"
    )

    # Existing negative fixture only. This exact owned synthetic standalone
    # Artifact has no UploadedOriginal or domain withdrawal command.
    verify_test_target(setup.admin)
    with Session(setup.admin) as session, session.begin():
        changed = session.execute(
            update(Artifact)
            .where(
                Artifact.tenant_id == setup.tenant,
                Artifact.product_id == setup.product,
                Artifact.id == UUID(work.document_source),
                Artifact.owner_id == setup.human,
            )
            .values(status="withdrawn")
        )
        assert changed.rowcount == 1
    withdrawn = _phase(
        work,
        "negative_source_fixture_withdrawn_fixed_children_retained",
        {
            "project_preparations": lambda: _get(work),
            "fixed_baseline": lambda: _get(work, fixed=baseline),
            "fixed_wi_v1": lambda: _get(work, fixed=wi_v1),
            "fixed_wi_v2": lambda: _get(work, fixed=wi_v2),
            "fixed_cp_v1": lambda: _get(work, fixed=cp_v1),
        },
    )
    phases.append(withdrawn)
    for name in ("fixed_baseline", "fixed_wi_v1", "fixed_wi_v2", "fixed_cp_v1"):
        before, after = _ok(revised["reads"][name]), _ok(withdrawn["reads"][name])
        assert after["source_status"] == "needs_recheck"
        assert {key: value for key, value in before.items() if key != "source_status"} == {
            key: value for key, value in after.items() if key != "source_status"
        }
    _bindings(
        _ok(withdrawn["reads"]["fixed_baseline"]),
        (_ok(withdrawn["reads"]["fixed_wi_v1"]), _ok(withdrawn["reads"]["fixed_cp_v1"])),
    )
    _export(
        work,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(setup.human),
            "other_project_id": other["project"],
            "process": deepcopy(work.process_ref),
            "baseline": reference(baseline),
            "wi_v1": reference(wi_v1),
            "wi_v2": reference(wi_v2),
            "cp_v1": reference(cp_v1),
        },
        phases,
        guard_checks,
        receipts,
    )
