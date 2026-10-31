"""Registered domain commands → Outbox → fixed native sources → actual read proofs."""
# ruff: noqa: F811, F401 -- imported fixtures register their actual dependency tree

import json
from uuid import UUID

from change_execution.test_transactions import (
    accepted_work,
    change_work,
    created,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.enterprise_search.events import process_event
from pdos_next.enterprise_search.indexing import project
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.models import Artifact, Outbox, Receipt
from pdos_next.providers.types import ProviderUsage
from tests.enterprise_search.test_assistant_pg import execute, fixture


def native_search(person, query, kinds, **extra):
    response = person.client.post(
        "/v1/personal/enterprise-search",
        headers=person.headers,
        json={"query": query, "source_types": kinds, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def native_session(person):
    return tenant_session(
        person.engine,
        person.tenant,
        actor_id=person.human,
        requester_id=person.human,
        category_id=None,
    )


def apply_event(person, receipt_id):
    with Session(person.admin) as session:
        event, receipt = session.execute(
            select(Outbox, Receipt)
            .join(Receipt, Receipt.id == Outbox.receipt_id)
            .where(Receipt.id == UUID(str(receipt_id)))
        ).one()
        reference = {
            "event_id": str(event.id),
            "event_type": event.type,
            "tenant_id": str(event.tenant_id),
            "category_id": str(event.category_id),
            "actor_id": str(event.actor_id),
            "requester_id": str(receipt.requester_id),
            "subject_id": str(event.subject_id),
            "subject_revision": event.subject_revision,
        }
    return process_event(person.engine, reference)


class NativeClient:
    def __init__(self, query, kinds, *, expected_scope=None):
        self.query, self.kinds, self.calls = query, kinds, 0
        self.expected_scope = expected_scope

    def close(self):
        pass

    def turn(self, _route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        assert "assistant.passage.read" not in {row["name"] for row in kwargs["tools"]}
        self.calls += 1
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        if not values:
            call = ToolCall(
                id="native-search",
                name="assistant.search",
                arguments={
                    "query": self.query,
                    "source_types": self.kinds,
                },
            )
        elif "items" in values[-1]:
            assert values[-1]["items"], values[-1]
            if self.expected_scope:
                assert values[-1]["scope"]["project_id"] == self.expected_scope
                assert all(row["project_id"] == self.expected_scope for row in values[-1]["items"])
            call = ToolCall(
                id="native-extract",
                name="assistant.extract",
                arguments={
                    "citation_ids": [values[-1]["items"][0]["citation_id"]],
                },
            )
        else:
            assert values[-1]["rows"], values[-1]
            assert all(row["as_of"] for row in values[-1]["rows"])
            assert '"position":' not in json.dumps(values[-1]["rows"])
            return ModelTurn(
                structured={
                    "status": "completed",
                    "summary": "依据已登记的内部记录，未知项保持未知。",
                    "result": {
                        "assistant": {"citation_ids": [values[-1]["rows"][0]["citation_id"]]}
                    },
                    "questions": [],
                    "unfinished": [],
                },
                usage=ProviderUsage(10, 2),
            )
        return ModelTurn(calls=(call,), usage=ProviderUsage(10, 2))


def test_actual_quality_capa_change_build_and_run_sources_keep_scope_and_fixed_proofs(change_work):
    work, person = change_work, change_work.quality
    change, _command, change_id = created(work)
    assert apply_event(person, change["id"])["processed"] == 1
    assert apply_event(person, change["id"])["changed"] == 0
    assert apply_event(person, work.issue_receipt["id"])["processed"] == 2
    with Session(person.admin) as session:
        receipt_ids = session.execute(
            select(Receipt.id, Receipt.operation).where(
                Receipt.tenant_id == person.tenant,
                Receipt.operation.in_(
                    ["build.create", "test.run.plan", "test.run.start", "test.results.import"]
                ),
            )
        ).all()
    assert len(receipt_ids) >= 4
    for identity, operation in receipt_ids:
        assert apply_event(person, identity)["processed"] == (
            2 if operation == "test.results.import" else 1
        )
    kinds = ["issue", "capa", "change", "build", "test_run"]
    with native_session(person) as session:
        prepare_read(session, kinds)
        rows = session.execute(select_sources(source_types=kinds)).mappings().all()
        assert set(kinds) <= {row["source_type"] for row in rows}, [
            row["source_type"] for row in rows
        ]
        # The existing native owner decides visibility, not an index audience copy.
        for row in rows:
            assert (
                project(session, person.ctx, row["source_type"], row["source_id"])["status"]
                == "ready"
            )
    for kind, identity in [("issue", work.issue_id), ("capa", work.capa_id), ("change", change_id)]:
        found = native_search(person, str(identity), [kind])
        assert found["items"][0]["object_id"] == str(identity), found
        assert found["items"][0]["channel"] == "exact_id"
        assert found["items"][0]["nature"] == "structured"
        assert "facts" not in found["items"][0]
        hidden = native_search(work.setup, str(identity), [kind])
        assert hidden["items"] == [], hidden
    project_id = UUID(work.config["project"])
    client = NativeClient(str(work.issue_id), ["issue"], expected_scope=str(project_id))
    owner, scope, host, _adapter = fixture(person, client, project_id=project_id)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    source = output["result"]["assistant"]["sources"][0]
    assert source["source_type"] == "issue" and source["object_id"] == str(work.issue_id)
    assert source["locator"]["json_pointer"] == "/facts"
    assert client.calls == 3  # Native fields require no extraction model child.
    run_path = f"/v1/categories/{person.category}/agent-runs/{scope.run_id}"
    saved = person.client.get(run_path, headers=person.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["result"]["assistant"]["sources"][0] == source
    for kind in ("build", "test_run"):
        identity = next(
            row["object_id"] for row in rows if row["source_type"] == kind and row["is_current"]
        )
        native_client = NativeClient(str(identity), [kind])
        native_owner, native_scope, native_host, _ = fixture(person, native_client)
        result = execute(native_owner, native_scope, native_host)
        assert result["status"] == "completed", result
        assert native_client.calls == 3
    with native_session(person) as session:
        row = (
            session.execute(
                select_sources(
                    source_type="issue", source_id=UUID(source["source_id"]), include_body=True
                )
            )
            .mappings()
            .one()
        )
        root = row["structured"]["source_refs"][0]["id"]
        assert "position" not in str(row["structured"])
        assert "authority_snapshot" not in row["body"] and "input_snapshot" not in row["body"]
    with Session(person.admin) as session, session.begin():
        session.get(Artifact, UUID(root)).status = "withdrawn"
    assert native_search(person, str(work.issue_id), ["issue"])["items"] == []
    saved = person.client.get(run_path, headers=person.headers)
    assert saved.status_code == 403
