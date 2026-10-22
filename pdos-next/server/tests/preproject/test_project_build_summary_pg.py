"""Project Build summaries over actual commands, fixed configurations and results.

Only root executes PostgreSQL. The two-project helper uses its existing explicit
synthetic stored parent; this file adds no publication, qualification or ACL grant.
One existing result chain supplies initial, partial, final and reviewed HTTP DTOs.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from build_start.test_transactions import shared_configuration
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from test_build_project_scope import second_project_configuration
from test_builds import build_command
from test_builds import configuration as configuration
from test_project_first_plan import accepted
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project
from verification_results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    command,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
)

from pdos_next.domain.build_execution.models import SampleUnit
from pdos_next.domain.build_operational_facts.models import BuildOperationalFact, ResourceOccupancy
from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.domain.test_resources.models import (
    SampleRunUsage,
    TestResourceFact,
    TestResourceReservation,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
)
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunIdentity,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import (
    MeasurementImportCapture,
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    ObjectAudience,
    Outbox,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.service import digest


def business_counts(setup):
    """Explicit closed-loop tables only; unrelated S4 tables need not exist."""
    models = (
        Product,
        Project,
        ProjectProductLink,
        BomRevision,
        EngineeringConfiguration,
        ProcessRevision,
        Build,
        BuildReadiness,
        BuildOperationalFact,
        SampleUnit,
        FormalVerificationRequest,
        FormalVerificationCurrent,
        VerificationRunIdentity,
        VerificationRunVersion,
        VerificationRunCurrent,
        MeasurementImportCapture,
        MeasurementRecord,
        TestResultProjection,
        TestResultActionFact,
        TestResourceReservation,
        TestResourceFact,
        SampleRunUsage,
        ResourceOccupancy,
        Artifact,
        Confirmation,
        RequestKey,
        Receipt,
        Audit,
        Outbox,
    )
    with Session(setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in models
        }


def builds(setup, project_id, *, headers=None, category_id=None):
    return setup.client.get(
        f"/v1/categories/{category_id or setup.category}/products/{setup.product}/builds",
        headers=headers or setup.headers,
        params={"project_id": project_id},
    )


def results(setup, build_id, *, headers=None, category_id=None, run_id=None):
    return setup.client.get(
        f"/v1/categories/{category_id or setup.category}/products/{setup.product}"
        "/verification-results",
        headers=headers or setup.headers,
        params={"build_id": build_id, **({"run_id": run_id} if run_id else {})},
    )


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def current_run(page, run_id):
    pointer = page["current_by_run"][str(run_id)]
    [row] = [
        row
        for row in page["runs"]
        if row["id"] == pointer["run_version_id"]
        and row["revision"] == pointer["revision"]
        and row["run_id"] == str(run_id)
    ]
    assert row["is_current"] is True
    return row


def current_projection(page, run):
    pointer = run["current_projection"]
    assert pointer is not None
    [projection] = [
        row
        for row in page["projections"]
        if all(row[key] == pointer[key] for key in ("id", "revision", "basis_sha256", "result"))
    ]
    assert projection["run_id"] == run["run_id"]
    assert projection["basis_sha256"] == digest(projection["input_snapshot"])
    # A retained projection may predate a current review/disposition Run version.
    # Resolve its own immutable version; do not require it to be the current one.
    [fixed] = [row for row in page["runs"] if row["id"] == projection["run_version_id"]]
    assert fixed["run_id"] == run["run_id"]
    assert fixed["revision"] == projection["run_revision"]
    return projection


def qa_runtime(work):
    """Finite existing test inputs for a separate GET-only local reader process."""

    def issuer(value):
        assert value.nature == "synthetic" and value.epoch == 1
        return {
            "key": value.key,
            "version": value.version,
            "tenant_id": str(value.tenant_id),
            "product_id": str(value.product_id),
            "project_id": str(value.project_id) if value.project_id else None,
            "epoch": value.epoch,
        }

    def decisions(row):
        return {
            "binding": row.binding,
            "decisions": [
                {"resource": resource["resource"], "decision": decision}
                for resource in row.data["resources"]
                for decision in resource["facts"]
                if decision.get("named_decision_id") is not None
            ],
        }

    with Session(work.setup.admin) as session:
        operational = session.scalars(
            select(BuildOperationalFact).where(
                BuildOperationalFact.tenant_id == work.setup.tenant,
                BuildOperationalFact.product_id == work.setup.product,
                BuildOperationalFact.build_id == UUID(work.build_id),
            )
        ).one()
        test_fact = session.get(TestResourceFact, work.test_fact_id)
        assert test_fact is not None
        return {
            "professional": issuer(work.professional_issuer),
            "operational": {**issuer(work.issuer), **decisions(operational)},
            "test_resource": {**issuer(work.test_issuer), **decisions(test_fact)},
        }


def export_qa(work, build_page, stages):
    response_path = os.environ.get("PDOS_PROJECT_BUILDS_QA_RESPONSE_PATH")
    session_path = os.environ.get("PDOS_PROJECT_BUILDS_QA_SESSION_PATH")
    if not (response_path or session_path):
        return
    setup = work.setup  # Actual ordinary project owner; never the PM reviewer.
    session_info = ok(setup.client.get("/v1/session", headers=setup.headers))
    categories = ok(setup.client.get("/v1/categories", headers=setup.headers))
    personal_projects = ok(setup.client.get("/v1/personal/projects", headers=setup.headers))
    detail = ok(
        setup.client.get(f"/v1/personal/projects/{work.config['project']}", headers=setup.headers)
    )
    scope = {
        "principal_id": str(setup.human),
        "category_id": str(setup.category),
        "product_id": str(setup.product),
        "project_id": str(work.config["project"]),
        "build_id": str(work.build_id),
        "request_id": str(work.request_id),
        "run_id": str(work.binding.run_id),
    }
    if response_path:
        output = Path(response_path)
        assert output.is_absolute(), "QA response destination must be absolute"
        output.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "scope": scope,
            "session": session_info,
            "categories": categories,
            "personal_projects": personal_projects,
            "project_detail": detail,
            "builds": build_page,
            "result_stages": stages,
        }
        encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
        assert setup.tokens[setup.human] not in encoded
        assert "confirmation_token" not in encoded
        output.write_text(encoded + "\n", encoding="utf-8")
    if session_path:
        private_path = Path(session_path)
        assert private_path.is_absolute(), "QA session destination must be absolute"
        private_path = private_path.resolve()
        private_root = (Path(__file__).resolve().parents[3] / ".local").resolve()
        assert private_path.is_relative_to(private_root), "QA session must stay in pdos-next/.local"
        private_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as private_file:
            os.fchmod(private_file.fileno(), 0o600)
            json.dump(
                {
                    "token": setup.tokens[setup.human],
                    **scope,
                    "object_root": str(work.report_store.root),
                    "runtime": qa_runtime(work),
                },
                private_file,
            )
            private_file.write("\n")


def test_http_project_builds_keep_two_projects_fixed_configurations_and_exact_quantities(
    setup, configuration
):
    second = second_project_configuration(setup, configuration)
    configurations = (configuration, second)
    quantities = ("9007199254740991.12345678", "2.00000001")
    created = [
        accepted(
            setup,
            build_command(
                setup,
                config,
                name=f"Synthetic project summary {index}",
                planned_quantity=quantity,
                planned_start="2026-11-01T01:02:03+08:00",
                planned_end="2026-11-02T02:03:04+08:00",
            ),
        )[0]
        for index, (config, quantity) in enumerate(zip(configurations, quantities, strict=True), 1)
    ]
    before = business_counts(setup)
    for config, quantity, receipt in zip(configurations, quantities, created, strict=True):
        page = ok(builds(setup, config["project"]))
        assert page["unavailable_count"] == 0 and page["has_more"] is False
        [row] = page["items"]
        assert row["id"] == receipt["subject_id"] and row["project_id"] == config["project"]
        assert row["planned_quantity"] == quantity and row["unit"] == "ea"
        assert row["planned_start"] == "2026-10-31T17:02:03+00:00"
        assert row["planned_end"] == "2026-11-01T18:03:04+00:00"
        assert row["status"] == "planned" and row["readiness"] is None
        engineering, manufacturing = (
            row["engineering_configuration"],
            row["manufacturing_configuration"],
        )
        assert (engineering["id"], engineering["revision"]) == (
            config["engineering"]["subject_id"],
            1,
        )
        assert engineering["definition_id"] == config["definition"]
        assert (manufacturing["id"], manufacturing["revision"]) == (
            config["process"]["subject_id"],
            1,
        )
        assert manufacturing["engineering_configuration_id"] == engineering["id"]
        empty = ok(results(setup, row["id"]))
        assert empty["current_by_run"] == {} and empty["runs"] == empty["projections"] == []
    assert business_counts(setup) == before


def test_http_project_builds_reject_foreign_scope_and_recheck_parent_read_acl(setup):
    config = shared_configuration(setup)
    receipt, _ = accepted(setup, build_command(setup, config))
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert (
        ok(builds(setup, config["project"], headers=peer_headers))["items"][0]["id"]
        == (receipt["subject_id"])
    )
    assert ok(results(setup, receipt["subject_id"], headers=peer_headers))["runs"] == []
    before = business_counts(setup)
    for response in (
        builds(setup, str(uuid4())),
        builds(setup, config["project"], category_id=uuid4()),
        results(setup, str(uuid4())),
        builds(
            setup,
            config["project"],
            headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
        ),
        results(
            setup,
            receipt["subject_id"],
            headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
        ),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in response.json() and "runs" not in response.json()
    assert business_counts(setup) == before
    # Ordinary synthetic parent ACL setup only; immutable configuration/source
    # snapshots and all existing acceptance accounts remain untouched.
    with Session(setup.admin) as session, session.begin():
        product = session.get(Product, setup.product)
        assert product is not None and product.owner_id == setup.human
        product.visibility = "private"
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.object_type == "products",
                ObjectAudience.subject_id == setup.product,
                ObjectAudience.principal_id == setup.peer,
            )
        )
    before = business_counts(setup)
    for response in (
        builds(setup, config["project"], headers=peer_headers),
        results(setup, receipt["subject_id"], headers=peer_headers),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in response.json() and "runs" not in response.json()
    assert ok(builds(setup, config["project"]))["items"][0]["id"] == receipt["subject_id"]
    assert business_counts(setup) == before


def test_http_project_build_results_current_index_partial_final_and_retained_projection(
    results_work,
):
    work, stages = results_work, []
    setup = work.setup
    with Session(setup.admin) as session:
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
        )
        assert grant is not None and grant.product_manager is False

    def read_stage(stage):
        before = business_counts(setup)
        build_page = ok(builds(setup, work.config["project"]))
        [build] = build_page["items"]
        assert build["id"] == work.build_id
        page = ok(results(setup, work.build_id))  # Explicit Build, ordinary non-PM owner.
        assert page["unavailable_count"] == 0 and page["has_more"] is False
        row = current_run(page, work.binding.run_id)
        assert row["build"]["id"] == work.build_id
        assert all(run["build"]["id"] == work.build_id for run in page["runs"])
        assert business_counts(setup) == before
        stages.append({"stage": stage, "results": page})
        return build_page, page, row

    _, initial_page, initial = read_stage("started_no_results")
    assert initial["status"] == "running" and initial["result"] == "pending"
    assert initial["current_projection"] is None and initial_page["measurements"] == []
    first, _ = capture(work, (0,))
    accepted(work.quality, command(work, "test.results.import", captured=first))
    _, partial_page, partial = read_stage("partial_results")
    partial_projection = current_projection(partial_page, partial)
    assert partial["status"] == "running" and partial_projection["result"] == "indeterminate"
    assert len(partial_page["measurements"]) == 1
    assert {row["result"] for row in partial_projection["computed_results"]} == {
        "pass",
        "indeterminate",
    }
    assert partial_projection["input_snapshot"]["final"] is False

    second, _ = capture(work, (1,))
    accepted(work.quality, command(work, "test.results.import", captured=second, final=True))
    _, final_page, final = read_stage("complete_numeric_results")
    projection = current_projection(final_page, final)
    assert final["status"] == "results_pending" and projection["result"] == "pass"
    assert projection["input_snapshot"]["final"] is True
    assert len(projection["computed_results"]) == 2
    assert {row["result"] for row in projection["computed_results"]} == {"pass"}
    assert len(final_page["measurements"]) == 2
    assert {row["measurement"]["raw_value"] for row in final_page["measurements"]} == {"10.0000"}
    assert {row["measurement"]["unit"] for row in final_page["measurements"]} == {"mm"}
    assert {row["criterion"]["lower"] for row in final["run_snapshot"]["items"]} == {"9.5"}
    assert {row["criterion"]["upper"] for row in final["run_snapshot"]["items"]} == {"10.5"}

    accepted(work.quality, command(work, "test.run.review"))
    build_page, reviewed_page, reviewed = read_stage("reviewed_retaining_result_basis")
    retained = current_projection(reviewed_page, reviewed)
    assert reviewed["status"] == "reviewed" and reviewed["result"] == "pass"
    assert retained["id"] == projection["id"]
    assert retained["run_version_id"] == final["id"] != reviewed["id"]
    assert retained["run_revision"] < reviewed["revision"]
    # The actual API currently uses the same computation basis for this pair;
    # the fixed projection version is still deliberately a historical Run.
    assert retained["basis_sha256"] == reviewed["basis_sha256"]
    before = business_counts(setup)
    export_qa(work, build_page, stages)  # Last business state; no later mutation.
    assert business_counts(setup) == before
