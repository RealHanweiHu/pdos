"""One real package loop; unknown policy is never a signed release."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from native_pilot_transactions import fixtures as upstream
from sqlalchemy import select
from test_project_first_plan import cmd, post

from pdos_next.domain.configurations.models import EngineeringConfiguration
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.domain.release import service
from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage, ReleasePackageCurrent
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey

MODELS = (
    ReleasePackage,
    ReleasePackageCurrent,
    ReleaseDecision,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
)


def snapshot(work):
    return upstream.publication.snapshots(work, MODELS)


def root(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}"


def prepare(work, operation, payload):
    command = cmd(work.setup, operation, deepcopy(payload))
    response = work.setup.client.post(
        root(work) + "/release/inputs", headers=work.setup.headers, json=command
    )
    assert response.status_code == 200, response.text
    value = response.json()
    command["payload"] = value["payload"]
    command["source_read_set"] = value["required_source_read_set"]
    return command, value


def read(work, identity, *, peer=False):
    response = work.setup.client.get(
        root(work) + "/release-packages/" + str(identity),
        headers=upstream.publication.headers(work, work.setup.peer if peer else None),
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_fixed_package_revision_recovery_unknown_decision_and_rollback(native_case, monkeypatch):
    work = native_case
    # Every selected parent is an actual public/controlled record from one case.
    create, _ = upstream.prepare(
        work, upstream.CREATE_OPERATION, work.create.model_dump(mode="json")
    )
    saved_pilot = upstream.post(work.setup, create)
    assert saved_pilot.status_code == 200, saved_pilot.text
    with upstream.publication.session(work) as s:
        engineering = s.get(EngineeringConfiguration, work.basis.engineering_configuration.id)
        issue = s.scalar(
            select(QualityIssueCurrent).where(QualityIssueCurrent.issue_id == work.issue_id)
        )
        definition = {
            "id": str(engineering.definition_id),
            "revision": engineering.definition_revision,
        }
        issue_ref = {"kind": "issue", "id": str(work.issue_id), "revision": issue.issue_revision}
    payload = {
        "project_id": str(work.project_id),
        "subject_config": {
            "definition": definition,
            "engineering_configuration": {
                "id": str(work.basis.engineering_configuration.id),
                "revision": work.basis.engineering_configuration.revision,
            },
            "manufacturing_configuration": {
                "id": str(work.basis.process_revision.id),
                "revision": work.basis.process_revision.revision,
            },
        },
        "release_scope": {
            "quantity": str(work.population_count),
            "unit": work.basis.unit,
            "lots": [{"id": str(work.basis.lot.id), "revision": work.basis.lot.revision}],
            "site": work.site,
            "lines": [{"id": str(work.line.id), "revision": work.line.revision}],
            "regions": ["CN"],
        },
        "purpose": work.purpose,
        "manufacturing_publication": {
            "id": work.published["id"],
            "revision": work.published["revision"],
        },
        "verifications": [
            {
                "id": str(work.upstream.failure_run.id),
                "revision": work.upstream.failure_run.revision,
            }
        ],
        "pilots": [{"id": str(work.create.details.pilot_id), "revision": 1}],
        "residuals": [issue_ref],
        "sources": [work.create.statistics.source.model_dump(mode="json")],
        "visibility": "category",
        "reason": "固定实际发布准备内容；原失败、未知及遗留保持",
    }
    before = snapshot(work)
    command, inputs = prepare(work, "release.package.assemble", payload)
    command["source_read_set"].reverse()  # The exact set is independent of public input order.
    assert snapshot(work) == before
    assert inputs["candidate"]["policy"] is None
    assert inputs["assessments"]["engineering"]["state"] == "UNKNOWN"
    assert inputs["assessments"]["manufacturing"]["state"] == "UNKNOWN"
    response = post(work.setup, command)
    assert response.status_code == 200, response.text
    receipt = response.json()
    first = read(work, receipt["subject_id"])
    assert first["status"] == "assembled" and first["revision"] == 1
    assert first["decisions"] == [] and first["package"] == inputs["candidate"]
    assert read(work, receipt["subject_id"], peer=True) == first
    with upstream.publication.session(work, work.setup.peer) as s:
        assert (
            s.scalar(select(RequestKey).where(RequestKey.key == command["idempotency_key"])) is None
        )
    original = deepcopy(first["package"])

    counts = snapshot(work)
    replay = post(work.setup, command)
    assert replay.status_code == 200 and replay.json() == receipt, replay.text
    assert snapshot(work) == counts
    alias = {
        **deepcopy(command),
        "command_id": str(uuid4()),
        "idempotency_key": "release-alias-" + str(uuid4()),
    }
    replay = post(work.setup, alias)
    assert replay.status_code == 200 and replay.json() == receipt, replay.text
    assert snapshot(work)["release_packages"]["count"] == counts["release_packages"]["count"]

    revised = {
        **payload,
        "previous": {"id": receipt["subject_id"], "revision": 1},
        "reason": "本人明确基于当前固定包续版",
    }
    second_command, _ = prepare(work, "release.package.assemble", revised)
    response = post(work.setup, second_command)
    assert response.status_code == 200, response.text
    second_receipt = response.json()
    second = read(work, second_receipt["subject_id"])
    assert second["revision"] == 2 and second["current"]["version"]["id"] == second["id"]
    assert read(work, receipt["subject_id"])["package"] == original
    stale = cmd(work.setup, "release.package.assemble", {**revised, "reason": "stale selection"})
    before = snapshot(work)
    response = post(work.setup, stale)
    assert response.status_code == 409, response.text
    assert snapshot(work) == before

    for discipline in ("engineering", "manufacturing"):
        decision, prepared = prepare(
            work,
            f"release.{discipline}.approve",
            {
                "package": {"id": second["id"], "revision": second["revision"]},
                "purpose": payload["purpose"],
                "release_scope": payload["release_scope"],
                "sources": payload["sources"],
                "reason": "未知政策不得成为本人放行",
            },
        )
        assert prepared["candidate"]["assessment"]["state"] == "UNKNOWN"
        before = snapshot(work)
        response = post(work.setup, decision)
        assert response.status_code == 409, response.text
        assert snapshot(work) == before

    third = {
        **payload,
        "previous": {"id": second["id"], "revision": 2},
        "reason": "single actual common-tail rollback",
    }
    third_command, _ = prepare(work, "release.package.assemble", third)
    before = snapshot(work)
    original_finalize = service.finalize_receipt

    def fail_tail(*_args, **_kwargs):
        raise DomainError("STORAGE_UNAVAILABLE", "single synthetic common-tail interruption", 503)

    monkeypatch.setattr(service, "finalize_receipt", fail_tail)
    response = post(work.setup, third_command)
    assert response.status_code == 503, response.text
    assert snapshot(work) == before
    monkeypatch.setattr(service, "finalize_receipt", original_finalize)

    upstream.withdraw(work, work.statistics_original_id)
    history = read(work, second["id"])
    assert history["package"] == second["package"] and history["applicability"] == "needs_recheck"
    before = snapshot(work)
    response = post(work.setup, third_command)
    assert response.status_code == 409, response.text
    assert snapshot(work) == before
    response = post(work.setup, second_command)
    assert response.status_code == 200 and response.json() == second_receipt, response.text
    assert snapshot(work) == before
    assert UUID(second["id"]) != UUID(first["id"])
