"""Actual signed TestRun start promises under ordinary personal HTTP/RLS scope.

Three existing valid launch chains cover business transitions, ACLs and paging;
lightweight ordinary sessions cover empty and invalid requests. Only the root
runs PostgreSQL. No promise, Run, immutable version or qualification is forged.
"""
# ruff: noqa: F811 -- imported fixtures register the real launch chain dependencies.

import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted
from verification_handoff import fixtures as handoff
from verification_launch import fixtures as launch
from verification_launch import test_multi_run_chain as multi_run
from verification_launch.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
)
from verification_launch.test_multi_run_chain import launch_command
from verification_launch.test_transactions import counts

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import OperationalAsset
from pdos_next.domain.test_resources import service as resources
from pdos_next.domain.verification_launch.models import VerificationLaunchFact
from pdos_next.models import Grant, ObjectAudience, Product, now
from tests.test_personal_views import second_category

CLOCK_FIELDS = {"occurred_at", "original_timezone", "effective_at"}


def page(actor, **params):
    return actor.client.get(
        "/v1/personal/test-start-promises", params=params, headers=actor.headers
    )


def successful(actor, **params):
    response = page(actor, **params)
    assert response.status_code == 200, response.text
    value = response.json()
    assert set(value) == {
        "version",
        "principal_id",
        "as_of",
        "total_records",
        "items",
        "next_cursor",
    }
    assert value["version"] == "personal-test-start-promises/v1"
    assert value["principal_id"] == str(actor.human)
    assert datetime.fromisoformat(value["as_of"]).utcoffset() is not None
    for item in value["items"]:
        assert set(item) == {
            "id",
            "recorded_at",
            "category",
            "product",
            "project",
            "build",
            "request",
            "run",
            "promise",
            "actual_start",
            "recipient",
            "recipient_status",
            "timing",
            "coverage",
        }
        for scope in ("category", "product", "project", "build"):
            assert set(item[scope]) == {"id", "name"}
        assert set(item["request"]) == {"id"}
        assert set(item["run"]) == {"id", "revision", "status"}
        assert set(item["promise"]) == CLOCK_FIELDS
        if item["actual_start"] is not None:
            assert set(item["actual_start"]) == CLOCK_FIELDS | {"received_at"}
        assert item["recipient"] is None and item["recipient_status"] == "not_recorded"
        assert set(item["coverage"]) == {"sample_count", "item_count", "pair_count"}
    return value


def fact(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
    ) as session:
        return session.execute(
            select(
                VerificationLaunchFact.id,
                VerificationLaunchFact.created_at,
                VerificationLaunchFact.owner_id,
                VerificationLaunchFact.run_version_id,
                VerificationLaunchFact.run_revision,
                VerificationLaunchFact.input_snapshot,
            ).where(
                VerificationLaunchFact.tenant_id == work.setup.tenant,
                VerificationLaunchFact.run_id == work.binding.run_id,
                VerificationLaunchFact.operation == "verification.schedule.promise",
            )
        ).one()


def forbidden_cursor(actor, identity):
    response = page(actor, cursor=identity)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
    assert "刷新" in response.text
    assert "items" not in response.json()


def quality_grant(session, work):
    grant = session.scalar(
        select(Grant).where(
            Grant.tenant_id == work.setup.tenant,
            Grant.category_id == work.setup.category,
            Grant.principal_id == work.quality.human,
        )
    )
    assert grant is not None
    return grant


def export_qa(work, value):
    """Export only after this test's last real transition, with no later Start."""
    if destination := os.environ.get("PDOS_TEST_PROMISES_QA_RESPONSE_PATH"):
        output = Path(destination)
        assert output.is_absolute(), "QA response destination must be absolute"
        session_info = work.quality.client.get("/v1/session", headers=work.quality.headers)
        categories = work.quality.client.get("/v1/categories", headers=work.quality.headers)
        assert session_info.status_code == categories.status_code == 200
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {"page": value, "session": session_info.json(), "categories": categories.json()},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if destination := os.environ.get("PDOS_TEST_PROMISES_QA_SESSION_PATH"):
        private_path = Path(destination)
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
                    "token": work.quality.headers["Authorization"].removeprefix("Bearer "),
                    "principal_id": str(work.quality.human),
                    "category_id": str(work.setup.category),
                    "product_id": str(work.setup.product),
                    "project_id": str(work.config["project"]),
                    "build_id": str(work.build_id),
                    "request_id": str(work.request_id),
                    "run_id": str(work.binding.run_id),
                },
                private_file,
            )
            private_file.write("\n")


def test_http_test_start_promise_keeps_original_binding_after_real_start_and_get_is_readonly(
    launch_work,
    monkeypatch,
):
    work = launch_work
    launch.promised(work)
    original = fact(work)
    planned = launch.fixed_run(work)
    before_start = successful(work.quality)
    assert before_start["total_records"] == 1 and before_start["next_cursor"] is None
    [entry] = before_start["items"]
    assert entry["id"] == str(original.id)
    assert original.owner_id == work.quality.human
    assert work.accepted_request["owner_id"] != str(work.quality.human)
    for scope, identity in (
        ("category", work.setup.category),
        ("product", work.setup.product),
        ("project", work.config["project"]),
        ("build", work.build_id),
    ):
        assert entry[scope]["id"] == str(identity)
    assert entry["request"]["id"] == str(work.request_id)
    assert entry["recorded_at"] == original.created_at.isoformat()
    assert entry["run"] == {"id": str(work.binding.run_id), "revision": 1, "status": "planned"}
    assert entry["promise"] == {key: original.input_snapshot["at"][key] for key in CLOCK_FIELDS}
    assert entry["actual_start"] is None
    assert entry["timing"] == (
        "past_due_no_start_record"
        if datetime.fromisoformat(before_start["as_of"]) > work.binding.window.start
        else "awaiting_start"
    )
    pairs = work.binding.pairs
    assert entry["coverage"] == {
        "sample_count": len({pair.sample.id for pair in pairs}),
        "item_count": len({pair.item_id for pair in pairs}),
        "pair_count": len(pairs),
    }
    # The existing fixture plans one second ahead of a real instant. Wait only
    # for that real deadline; never advance Python beyond the database clock.
    remaining = (work.binding.window.start - datetime.now(UTC)).total_seconds()
    if remaining >= 0:
        assert remaining <= 2
        sleep(remaining + 0.02)
    overdue = successful(work.quality)
    assert overdue["items"][0]["timing"] == "past_due_no_start_record"
    launch.advance_clock(work, monkeypatch)
    actual = launch.command(work, "test.run.start")
    accepted(work.quality, actual)
    current = launch.fixed_run(work)
    retained = fact(work)
    assert retained.id == original.id
    assert retained.run_version_id == original.run_version_id == UUID(planned["id"])
    assert retained.run_revision == original.run_revision == 1
    assert retained.input_snapshot == original.input_snapshot
    assert current["id"] != planned["id"] and current["revision"] == 2

    before = counts(work)
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        after_start = successful(work.quality)
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert after_start["total_records"] == 1
    [started] = after_start["items"]
    assert started["id"] == entry["id"] and started["promise"] == entry["promise"]
    assert started["recorded_at"] == entry["recorded_at"]
    assert started["run"] == {"id": str(work.binding.run_id), "revision": 2, "status": "running"}
    assert started["actual_start"] == {
        key: current["run_snapshot"]["actual_start"][key] for key in CLOCK_FIELDS | {"received_at"}
    }
    assert datetime.fromisoformat(started["actual_start"]["occurred_at"]) == datetime.fromisoformat(
        actual["payload"]["at"]["occurred_at"]
    )
    assert started["timing"] == "started_late"
    assert datetime.fromisoformat(started["recorded_at"]) < datetime.fromisoformat(
        started["actual_start"]["occurred_at"]
    )
    assert counts(work) == before
    assert statements and not any(
        sql.lstrip().startswith(("insert ", "update ", "delete ")) for sql in statements
    )
    assert not any(
        re.search(
            r"\b(?:verification_launch_facts\.input_snapshot|current_run\.run_snapshot)\s*(?:,|as\b)",
            sql,
        )
        or any(
            field in sql
            for field in (
                ".sources",
                ".kernel_event",
                ".source_basis",
                ".authority_snapshot",
                ".execution_plan",
                ".required_source_read_set",
                "artifact_versions",
                "request_snapshot",
            )
        )
        for sql in statements
    )
    assert not {"capabilities", "sources", "owner", "request_owner"} & set(started)
    export_qa(work, after_start)


def test_http_test_start_promises_actor_tenant_parent_acl_and_grant_rechecked(launch_work):
    work = launch_work
    launch.promised(work)
    original = fact(work)
    assert successful(work.quality)["total_records"] == 1
    # These actors can share the category/Run, but did not sign this promise.
    for actor in (work.setup, work.engineer):
        value = successful(actor)
        assert value["total_records"] == 0 and value["items"] == []
        forbidden_cursor(actor, str(original.id))
    foreign = handoff.caller(
        work.setup, work.setup.other_human, work.setup.tokens[work.setup.other_human]
    )
    assert successful(foreign)["items"] == []
    forbidden_cursor(foreign, str(original.id))

    other = second_category(work.setup)
    with Session(work.setup.admin) as session, session.begin():
        session.add(
            Grant(
                tenant_id=work.setup.tenant,
                category_id=other.category,
                principal_id=work.quality.human,
                can_write=False,
            )
        )
        grant = quality_grant(session, work)
        previous_expiry = grant.expires_at
        grant.expires_at = now() - timedelta(seconds=1)
    hidden = successful(work.quality)
    assert hidden["total_records"] == 0 and hidden["items"] == []
    assert str(work.setup.category) not in json.dumps(hidden)
    forbidden_cursor(work.quality, str(original.id))
    with Session(work.setup.admin) as session, session.begin():
        quality_grant(session, work).expires_at = previous_expiry
    assert successful(work.quality)["total_records"] == 1

    # Narrow only the mutable Product head and ordinary synthetic audience ACL;
    # no retained Run/Fact/source snapshot is changed.
    with Session(work.setup.admin) as session, session.begin():
        session.get(Product, work.setup.product).visibility = "private"
        for audience in session.scalars(
            select(ObjectAudience).where(
                ObjectAudience.tenant_id == work.setup.tenant,
                ObjectAudience.category_id == work.setup.category,
                ObjectAudience.object_type == "products",
                ObjectAudience.subject_id == work.setup.product,
                ObjectAudience.principal_id == work.quality.human,
            )
        ):
            session.delete(audience)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
    ) as session:
        assert session.get(Product, work.setup.product) is None
    hidden_parent = successful(work.quality)
    assert hidden_parent["items"] == [] and hidden_parent["total_records"] == 0
    forbidden_cursor(work.quality, str(original.id))


def test_http_test_start_promises_two_actual_runs_page_by_fact_and_tail_stays_empty(
    launch_work,
    monkeypatch,
):
    work = launch_work
    launch.promised(work)
    first = fact(work)
    before = handoff.current(work)
    second_pairs = [
        pair for pair in before["offered_coverage"] if pair not in before["accepted_coverage"]
    ]
    assert len(second_pairs) == 1
    accepted(
        work.quality,
        handoff.handoff(work, operation="verification.handoff.accept", coverage=second_pairs),
    )
    work.test_issuers = []
    try:
        person = next(
            resource
            for resource in work.test_input.resources
            if resource.resource.id == work.quality.human
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as session:
            registered = session.get(OperationalAsset, work.quality.human)
            assert registered is not None and registered.data["state"] == "active"
            assert registered.revision == person.resource.revision
            registered_physical = resources.physical_projection(registered.data["value"])
        assert resources.physical_projection(person) == registered_physical
        person_input = person.model_dump(mode="json")
        real_import = multi_run.import_test_resource_fact

        def import_with_registered_person(session, ctx, product_id, issuer, data, **identifiers):
            # Adapt this helper's new input only: its two-unit multi-start
            # profile cannot replace the already registered one-unit person.
            # Keep the second Run's own binding/qualification facts and pass
            # the validated input through the unchanged real trusted importer.
            raw = data.model_dump(mode="json")
            for resource in raw["resources"]:
                if resource["resource"]["id"] == str(work.quality.human):
                    for key in ("resource", "lifecycle", "capacity", "calendar", "maintenance"):
                        resource[key] = deepcopy(person_input[key])
            adapted = type(data).model_validate(raw)
            declared_person = next(
                resource
                for resource in data.resources
                if resource.resource.id == work.quality.human
            )
            adapted_person = next(
                resource
                for resource in adapted.resources
                if resource.resource.id == work.quality.human
            )
            assert resources.physical_projection(adapted_person) == registered_physical
            assert adapted_person.facts == declared_person.facts
            assert adapted.binding == data.binding and adapted.required_uses == data.required_uses
            return real_import(session, ctx, product_id, issuer, adapted, **identifiers)

        with monkeypatch.context() as input_profile:
            input_profile.setattr(
                multi_run, "import_test_resource_fact", import_with_registered_person
            )
            second = multi_run.prepare_run(work, second_pairs, monkeypatch)
        accepted(work.quality, launch_command(second, "test.run.plan"))
        accepted(work.quality, launch_command(second, "verification.schedule.promise"))
        second_fact = fact(second)
        assert first.id != second_fact.id and work.binding.run_id != second.binding.run_id
        assert {pair.sample.id for pair in work.binding.pairs}.isdisjoint(
            pair.sample.id for pair in second.binding.pairs
        )
        expected = [
            str(row.id)
            for row in sorted(
                (first, second_fact), key=lambda row: (row.created_at, row.id.int), reverse=True
            )
        ]
        one = successful(work.quality, page_size=1)
        assert one["total_records"] == 2
        assert [entry["id"] for entry in one["items"]] == expected[:1]
        assert one["next_cursor"] == expected[0]
        two = successful(work.quality, page_size=1, cursor=one["next_cursor"])
        assert two["total_records"] == 2 and two["next_cursor"] is None
        assert [entry["id"] for entry in two["items"]] == expected[1:]
        assert len({entry["run"]["id"] for entry in one["items"] + two["items"]}) == 2
        tail = successful(work.quality, cursor=expected[-1])
        assert tail["total_records"] == 2 and tail["items"] == [] and tail["next_cursor"] is None
        assert [entry["id"] for entry in successful(work.quality)["items"]] == expected
    finally:
        for issuer in work.test_issuers:
            resources.disable_issuer(work.setup.engine, issuer.key)


def test_http_test_start_promises_empty_ordinary_session_is_metadata_only(setup):
    value = successful(setup)
    assert value["total_records"] == 0 and value["items"] == [] and value["next_cursor"] is None
    assert "total_pending" not in value
    assert "recipient" not in json.dumps(value)


def test_http_test_start_promises_reject_invalid_page_bounds_and_cursor_shape(setup):
    for params in (
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": "invalid"},
        {"cursor": "not-a-uuid"},
        {"cursor": ""},
    ):
        response = page(setup, **params)
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "VALIDATION_FAILED"


def test_http_test_start_promises_missing_cursor_is_forbidden_and_session_is_required(setup):
    forbidden_cursor(setup, str(uuid4()))
    response = setup.client.get("/v1/personal/test-start-promises")
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE"
