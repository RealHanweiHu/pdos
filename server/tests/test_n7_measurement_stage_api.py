"""One synthetic stage journey through personal capture and independent team reception.

The existing fixture supplies a historical approved project task and document metadata.
All measurement, consent, delivery and reception writes use the real HTTP API and DB
guards. These observations are explicitly synthetic, never real employee evidence.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.auth.roles import Role
from app.db.engine import get_engine
from app.db.schema import tables
from tests.stage_plan_fixtures import seed_formal_task
from tests.test_product_engineering_api import SETUP_PAYLOAD, bearer_headers, seed_user
from tests.test_product_engineering_api import client as client
from tests.test_product_engineering_api import (
    isolated_product_database as isolated_product_database,
)
from tests.test_projects_api import approved_case, create_project
from tests.test_quality_capa_api import seed_document


def post(
    client: TestClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    status: int = 200,
) -> dict[str, Any]:
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == status, response.text
    if status < 400:
        assert response.headers["cache-control"] == "no-store"
    return cast(dict[str, Any], response.json())


@pytest.mark.parametrize("scope", ["project", "product_line"])
def test_synthetic_measurement_stage_retains_receipts_and_honors_withdrawal(
    client: TestClient, isolated_product_database: str, scope: Literal["project", "product_line"]
) -> None:
    setup = post(client, "/api/setup", {}, SETUP_PAYLOAD, status=201)
    tenant, owner = UUID(setup["tenant"]["id"]), UUID(setup["user"]["id"])
    manager = bearer_headers(client)
    case = approved_case(client, manager, suffix="N7-SYNTHETIC")
    response = create_project(client, manager, case["id"], code="N7-SYNTHETIC")
    assert response.status_code == 201, response.text
    project = UUID(response.json()["id"])
    people = {
        name: seed_user(
            isolated_product_database,
            tenant_id=tenant,
            project_id=project,
            owner_id=owner,
            username=f"synthetic-{name}",
            role=Role.ENGINEER,
        )
        for name in ("deliverer", "receiver")
    }
    auth = {name: bearer_headers(client, username=f"synthetic-{name}") for name in people}
    document = seed_document(
        isolated_product_database, tenant, project, owner, filename="synthetic-fixture.pdf"
    )
    study_scope: dict[str, Any] = {}
    line: dict[str, Any] = {}
    research: dict[str, Any] = {}
    space_url = ""
    if scope == "project":
        with get_engine().begin() as connection:
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.id == project)
                .values(status="active")
            )
            task, _ = seed_formal_task(connection, tenant, project, owner, people["deliverer"])
        base = f"/api/projects/{project}"
        personal, team = base + "/value-measurement", base + "/value-workpacks"
        subject = {"task_id": str(task)}
        delivery_subject = {"document_id": str(document)}
        sample_source = {
            "evidence_document_id": str(document),
            "evidence_locator": "Synthetic fixture metadata; no real employee document",
        }
    else:
        space = post(
            client,
            "/api/product-work/spaces",
            manager,
            {
                "request_id": str(uuid4()),
                "code": "n7-synthetic",
                "title": "Synthetic stage verification only",
                "user_groups": ["Synthetic participants"],
                "regions": ["Synthetic region"],
                "use_scenarios": ["API integration verification"],
                "research_questions": ["Does the fixed work scope retain independent receipts?"],
            },
            status=201,
        )
        space_url = f"/api/product-work/spaces/{space['id']}"
        line = post(
            client,
            space_url + "/products",
            manager,
            {
                "request_id": str(uuid4()),
                "code": "synthetic-line",
                "name": "Synthetic product line",
                "level": "line",
                "owner_user_id": str(owner),
            },
            status=201,
        )
        for person in people.values():
            member = client.put(
                space_url + f"/members/{person}", headers=manager, json={"access": "contributor"}
            )
            assert member.status_code == 204, member.text
            line = post(
                client,
                space_url + f"/products/{line['id']}/members",
                manager,
                {
                    "expected_version": line["version"],
                    "payload_digest": line["payload_digest"],
                    "idempotency_key": str(uuid4()),
                    "user_id": str(person),
                    "access": "contributor",
                },
            )
        research = post(
            client,
            space_url + "/research",
            manager,
            {
                "request_id": str(uuid4()),
                "product_line_id": line["id"],
                "owner_user_id": str(people["deliverer"]),
                "question": "Synthetic independent reception journey",
                "user_groups": ["Synthetic participants"],
                "regions": ["Synthetic region"],
                "time_scope": "This isolated test only",
                "method": "Synthetic API exercise without real research or model calls",
                "expected_decision": "No business decision is made",
                "stop_conditions": ["Stop when the test finishes"],
            },
            status=201,
        )
        personal, team = space_url + "/research-measurement", space_url + "/research-workpacks"
        subject = {"subject_kind": "research_task", "subject_id": research["id"]}
        delivery_subject = {"subject_id": research["id"]}
        sample_source = {"source_locator": "Synthetic research question and fixed scope"}
        study_scope = {"product_line_id": line["id"]}

    now = datetime.now(UTC)
    study_request = {
        **study_scope,
        "request_id": str(uuid4()),
        "title": "Synthetic stage verification; not employee performance evidence",
        "protocol_version": "n7.synthetic.v1",
        "window_start": (now - timedelta(hours=1)).isoformat(),
        "window_end": (now + timedelta(hours=1)).isoformat(),
        "timezone": "UTC",
        "scenario_id": "synthetic-handoff",
        "role_ids": ["execute", "receive"],
        "complexity_strata": ["synthetic-small"],
        "inclusion_rule": "Only explicitly synthetic isolated test observations",
        "matching_rule": "No causal benefit comparison or real-world acceptance claim",
        "evidence_kind": "synthetic",
        "purpose": "Verify API persistence, privacy and independent reception",
    }
    study = post(client, personal + "/study-create", manager, study_request)
    assert post(client, personal + "/study-create", manager, study_request)["id"] == study["id"]

    def consent(name: str, version: int, status: str) -> dict[str, Any]:
        result = post(
            client,
            personal + "/consent",
            auth[name],
            {
                "request_id": str(uuid4()),
                "study_id": study["id"],
                "expected_version": version,
                "status": status,
                "activity_and_aggregate_use_confirmed": status == "consented",
                "reason": "Explicit synthetic participant action",
            },
        )
        return cast(dict[str, Any], result["my_consent"])

    grants = {name: consent(name, 0, "consented") for name in people}
    pack_request = {
        **subject,
        "request_id": str(uuid4()),
        "study_id": study["id"],
        "mode": "assisted",
        "deliverer_user_id": str(people["deliverer"]),
        "receiver_user_id": str(people["receiver"]),
        "members": [
            {"user_id": str(person), "role_id": role, "first_use": True}
            for (name, person), role in zip(people.items(), ("execute", "receive"), strict=True)
        ],
        "complexity_stratum": "synthetic-small",
        "workflow_version": "synthetic.v1",
        "scope": "Fixed synthetic two-person work scope",
        "completion_criteria": "The named receiver checked this synthetic delivery",
        "full_roster_confirmed": True,
    }
    pack = post(client, team + "/create", manager, pack_request)["workpack"]
    pack_ref = {"workpack_id": pack["id"]}
    assert post(client, team + "/create", manager, pack_request)["workpack"]["id"] == pack["id"]
    samples: dict[str, dict[str, Any]] = {}
    drafts: dict[str, dict[str, Any]] = {}

    def save_sample(name: str, draft: dict[str, Any]) -> dict[str, Any]:
        preview = post(client, personal + "/sample-preview", auth[name], draft)
        command = {
            **draft,
            "request_id": str(uuid4()),
            "expected_digest": preview["digest"],
            "reason": "Synthetic activity revision, not observed employee time",
        }
        saved = post(client, personal + "/sample-save", auth[name], command)
        assert post(client, personal + "/sample-save", auth[name], command)["id"] == saved["id"]
        return saved

    started = now - timedelta(minutes=10)
    for name, role in (("deliverer", "execute"), ("receiver", "receive")):
        drafts[name] = {
            **subject,
            **sample_source,
            "study_id": study["id"],
            "sample_id": str(uuid4()),
            "expected_version": 0,
            "role_id": role,
            "complexity_stratum": "synthetic-small",
            "mode": "assisted",
            "first_use": True,
            "workflow_version": "synthetic.v1",
            "started_at": started.isoformat(),
            "as_of": datetime.now(UTC).isoformat(),
            "terminal_state": "incomplete",
            "segments": [
                {
                    "segment_id": str(uuid4()),
                    "phase": "prepare",
                    "start_at": started.isoformat(),
                    "end_at": (started + timedelta(seconds=60)).isoformat(),
                    "capture_method": "participant_recollection",
                    "participant_verified": True,
                }
            ],
        }
        samples[name] = save_sample(name, drafts[name])
        assert samples[name]["draft"]["participant_user_id"] == str(people[name])

    originals: list[dict[str, Any]] = []
    for round_no, decision in ((1, "returned"), (2, "accepted")):
        delivery = {
            **pack_ref,
            **delivery_subject,
            "locator": "Synthetic fixed scope",
            "description": f"Synthetic round {round_no}",
        }
        preview = post(client, team + "/delivery-preview", auth["deliverer"], delivery)
        delivery_command = {
            **delivery,
            "request_id": str(uuid4()),
            "expected_digest": preview["digest"],
        }
        detail = post(client, team + "/delivery-save", auth["deliverer"], delivery_command)
        assert (
            len(
                post(client, team + "/delivery-save", auth["deliverer"], delivery_command)[
                    "deliveries"
                ]
            )
            == round_no
        )
        submitted = detail["deliveries"][-1]
        originals.append(submitted["source_snapshot"])
        reception = {
            **pack_ref,
            "delivery_id": submitted["id"],
            "decision": decision,
            "criteria_checked": True,
            "reason": "Named receiver synthetic decision",
        }
        post(client, team + "/reception-preview", auth["deliverer"], reception, status=403)
        if round_no == 1:
            if scope == "product_line":
                research = post(
                    client,
                    space_url + f"/research/{research['id']}/start",
                    auth["deliverer"],
                    {
                        "research_task_id": research["id"],
                        "expected_version": research["version"],
                        "payload_digest": research["payload_digest"],
                        "idempotency_key": str(uuid4()),
                    },
                )
                post(
                    client,
                    team + "/reception-preview",
                    auth["receiver"],
                    {**reception, "decision": "accepted"},
                    status=409,
                )
            else:
                post(
                    client,
                    f"/api/projects/{project}/tasks/{task}/transitions",
                    auth["deliverer"],
                    {"to_status": "in_progress"},
                )
        preview = post(client, team + "/reception-preview", auth["receiver"], reception)
        reception_command = {
            **reception,
            "request_id": str(uuid4()),
            "expected_digest": preview["digest"],
        }
        detail = post(client, team + "/reception-save", auth["receiver"], reception_command)
        assert (
            len(
                post(client, team + "/reception-save", auth["receiver"], reception_command)[
                    "receptions"
                ]
            )
            == round_no
        )
        post(
            client,
            team + "/reception-save",
            auth["receiver"],
            {**reception_command, "reason": "Attempt to rewrite an existing receipt"},
            status=409,
        )
    assert [d["source_snapshot"] for d in detail["deliveries"]] == originals
    incomplete = post(client, team + "/summary", manager, pack_ref)["summary"]
    assert incomplete["outcome"] == "accepted" and incomplete["active_seconds"] is None
    post(client, team + "/summary", auth["receiver"], pack_ref, status=403)

    for name in people:
        ended = datetime.now(UTC)
        draft = {
            **drafts[name],
            "expected_version": 1,
            "ended_at": ended.isoformat(),
            "as_of": ended.isoformat(),
            "terminal_state": "completed",
            "review_confirmed": True,
            "correction_confirmed": True,
            "all_activity_confirmed": True,
        }
        saved = save_sample(name, draft)
        assert saved["version"] == 2
        history = post(
            client, personal + "/sample-read", auth[name], {"sample_id": saved["sample_id"]}
        )["history"]
        assert [row["version"] for row in history] == [2, 1]
        assert history[1]["id"] == samples[name]["id"]
        assert history[1]["draft"]["terminal_state"] == "incomplete"
    summary = post(client, team + "/summary", manager, pack_ref)["summary"]
    assert summary["status"] == "observed" and Decimal(summary["active_seconds"]) == 120
    assert summary["first_reception"] == "returned" and summary["return_count"] == 1
    assert summary["evidence_kind"] == "synthetic" and summary["threshold_version"] is None
    stage = post(client, team + "/study-summary", manager, {"study_id": study["id"]})["summary"]
    assert stage["strata"][0]["first_acceptance_numerator"] == 0
    assert stage["strata"][0]["first_acceptance_denominator"] == 1

    # A measured acceptance does not complete the source task/research or mutate receipts.
    prefix = "value_measurement" if scope == "project" else "research_measurement"
    reception_table = getattr(tables, prefix + "_receptions")
    with get_engine().connect() as connection:
        source_table = tables.tasks if scope == "project" else tables.research_tasks
        state_column = source_table.c.status if scope == "project" else source_table.c.state
        identity = task if scope == "project" else UUID(research["id"])
        assert connection.execute(
            select(state_column).where(source_table.c.id == identity)
        ).scalar_one() == ("in_progress" if scope == "project" else "active")
    with pytest.raises(DBAPIError), get_engine().begin() as connection:
        connection.execute(
            reception_table.update()
            .where(reception_table.c.id == UUID(detail["receptions"][-1]["id"]))
            .values(reason="Forbidden historical rewrite")
        )

    consent("receiver", 1, "withdrawn")
    for regrant in (False, True):
        if regrant:
            assert consent("receiver", 2, "consented")["id"] != grants["receiver"]["id"]
        hidden = post(client, team + "/read", manager, pack_ref)
        assert hidden["deliveries"] == [] and hidden["receptions"] == []
        assert hidden["unavailable_receipt_count"] == 4
        partial = post(client, team + "/summary", manager, pack_ref)["summary"]
        assert partial["active_seconds"] is None and partial["outcome"] == "unavailable"
        receiver = next(
            p for p in partial["participants"] if p["user_id"] == str(people["receiver"])
        )
        assert receiver["sample_id"] is None and receiver["known_active_seconds"] is None
        own = post(
            client,
            personal + "/sample-read",
            auth["receiver"],
            {"sample_id": samples["receiver"]["sample_id"]},
        )
        assert len(own["history"]) == 2
        post(
            client,
            personal + "/sample-read",
            manager,
            {"sample_id": samples["receiver"]["sample_id"]},
            status=403,
        )

    # Even the participant's own history still requires current source-scope access.
    if scope == "product_line":
        post(
            client,
            space_url + f"/products/{line['id']}/members",
            manager,
            {
                "expected_version": line["version"],
                "payload_digest": line["payload_digest"],
                "idempotency_key": str(uuid4()),
                "user_id": str(people["receiver"]),
                "access": None,
            },
        )
    else:
        with get_engine().begin() as connection:
            connection.execute(
                tables.project_members.delete().where(
                    tables.project_members.c.tenant_id == tenant,
                    tables.project_members.c.project_id == project,
                    tables.project_members.c.user_id == people["receiver"],
                )
            )
    post(
        client,
        personal + "/sample-read",
        auth["receiver"],
        {"sample_id": samples["receiver"]["sample_id"]},
        status=403,
    )
