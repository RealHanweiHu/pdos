"""Actual native Field/Outbox/registered reads; root alone runs isolated PG."""
# ruff: noqa: F401, F811 -- imports register the genuine native fixture tree

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentToolCall, TenantAdministrator
from pdos_next.agent_kernel.types import ModelTurn
from pdos_next.database import tenant_session
from pdos_next.domain.field_feedback.models import FieldResponseRecord
from pdos_next.enterprise_search.embedding_sources import categories
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, now
from pdos_next.original_security import configure
from pdos_next.providers.types import ProviderUsage
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.enterprise_search.field_feedback_source_harness import RAW, create_feedback
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_business_sources_pg import (
    NativeClient,
    apply_event,
    native_search,
    native_session,
)
from tests.field_feedback_pg.test_field_chain import (
    configuration,
    definition,
    knowledge_work,
    project,
)
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


class FieldClient(NativeClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.child, self.main_messages = SyntheticClient(), []

    def turn(self, route, **kwargs):
        if {row["name"] for row in kwargs["tools"]} == {"assistant.passage.read", "result.read"}:
            return self.child.turn(route, **kwargs)
        assert "RAW_ONLY_CHILD_MARKER" not in str(kwargs["messages"])
        self.main_messages.append(deepcopy(kwargs["messages"]))
        values = [json.loads(row["content"]) for row in kwargs["messages"]
                  if row["role"] == "tool"]
        rows = values[-1].get("rows") if values else None
        if rows and any("as_of" not in row for row in rows):
            # Untrusted extraction yields checked quotation rows, not the
            # structured-business fact envelope asserted by NativeClient.
            self.calls += 1
            return ModelTurn(structured={
                "status": "completed", "summary": "参考已核对的现场反馈。",
                "result": {"assistant": {"citation_ids": [rows[0]["citation_id"]]}},
                "questions": [], "unfinished": [],
            }, usage=ProviderUsage(10, 2))
        return super().turn(route, **kwargs)


def records(person):
    with native_session(person) as session:
        prepare_read(session, ["field_feedback"])
        return [dict(row) for row in session.execute(select_sources(
            source_type="field_feedback", include_body=True,
        )).mappings()]


def answer(person, row, *, project_id=None):
    client = FieldClient(str(row["source_id"]), ["field_feedback"])
    owner, scope, host, adapter = fixture(person, client, project_id=project_id)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    source = output["result"]["assistant"]["sources"][0]
    assert source["source_type"] == "field_feedback"
    assert source["source_id"] == str(row["source_id"])
    assert client.calls == 3
    return source, client, owner, scope, adapter


@pytest.mark.parametrize("restricted", [False, True])
def test_native_unlocated_intake_outbox_and_isolated_raw_text_keep_unknown_identity(
    knowledge_work, restricted,
):
    work, person = knowledge_work, knowledge_work.setup
    saved = create_feedback(person, work.config, located=False, response=False)
    assert apply_event(person, saved.intake["id"])["processed"] == 1
    assert apply_event(person, saved.intake["id"])["changed"] == 0
    row = next(row for row in records(person)
               if str(row["source_id"]) == saved.intake["subject_id"])
    assert row["product_id"] is row["project_id"] is None and row["is_current"]
    assert row["nature"] == "untrusted" and row["private"]
    assert not row["original_ids"] and row["customer_original"]
    assert categories(row) == {"internal", "customer_original"}
    assert row["structured"]["facts"]["location_status"] == "unknown"
    if restricted:
        with Session(person.admin) as session, session.begin():
            session.add(TenantAdministrator(tenant_id=person.tenant, principal_id=person.human))
        with tenant_session(person.engine, person.tenant, actor_id=person.human,
                            requester_id=person.human, category_id=person.category) as session:
            register_agreement(session, person.ctx, AgreementInput(
                provider="synthetic-assistant-no-egress", expected_revision=0,
                data_categories=["internal"], signed_on=now() - timedelta(minutes=1),
                expires_at=now() + timedelta(hours=1), retention_terms="synthetic only",
                training_terms="synthetic only", decision="批准", idempotency_key=str(uuid4()),
            ))
        provider = FieldClient(str(row["source_id"]), ["field_feedback"])
        owner, scope, host, _adapter = fixture(person, provider)
        with pytest.raises(DomainError) as blocked:
            execute(owner, scope, host)
        assert blocked.value.detail["reason_key"] == "provider_agreement_category"
        assert provider.calls == 1 and provider.child.child_calls == 0
        return
    source, client, owner, scope, _adapter = answer(person, row)
    assert client.child.child_calls >= 2 and source["quote"] == "更换密封圈"
    assert "object_url" not in source  # No invented actual project destination.
    with owner.store.transaction(scope) as (session, _run):
        reads = list(session.scalars(select(AgentToolCall).where(
            AgentToolCall.run_id == scope.run_id, AgentToolCall.tool == "assistant.search",
        )))
        assert len(reads) == 1 and reads[0].execution_binding["read_kind"] == "ordinary/v1"
        assert RAW not in str(reads[0].result)  # Search remains metadata-only.


def test_native_locate_response_fixed_versions_relations_and_current_destination(knowledge_work):
    work, person = knowledge_work, knowledge_work.setup
    saved = create_feedback(person, work.config)
    assert apply_event(person, saved.intake["id"])["processed"] == 1
    assert apply_event(person, saved.located["id"])["processed"] == 2
    assert apply_event(person, saved.response["id"])["processed"] == 1
    assert apply_event(person, saved.response["id"])["changed"] == 0
    by_id = {str(row["source_id"]): row for row in records(person)}
    first, located, response = [by_id[receipt["subject_id"]]
                                for receipt in (saved.intake, saved.located, saved.response)]
    assert not first["is_current"] and located["is_current"] and response["is_current"]
    assert located["nature"] == "untrusted" and response["nature"] == "structured"
    assert response["customer_original"] and not response["original_ids"]
    assert response["structured"]["facts"]["record_kind"] == "field_response"
    assert RAW not in response["body"]
    found = native_search(person, saved.located["subject_id"], ["field_feedback"])
    assert any(row.get("relation", {}).get("type") == "field_response" for row in found["items"])
    source, client, _owner, _scope, _adapter = answer(person, response, project_id=work.project_id)
    assert client.child.child_calls == 0
    assert "panel=field" in source["object_url"]
    assert "feedback=" + saved.feedback["id"] in source["object_url"]


def test_response_retains_parent_original_basis_after_direct_reads_change_and_revocation(
    knowledge_work,
):
    work, person = knowledge_work, knowledge_work.setup
    saved = create_feedback(person, work.config)
    for receipt in (saved.intake, saved.located, saved.response):
        apply_event(person, receipt["id"])
    with native_session(person) as session:
        native = session.get(FieldResponseRecord, UUID(saved.response["subject_id"]))
        assert saved.source["id"] not in {row["artifact_id"] for row in native.reads}
        assert saved.source["id"] in {row["id"] for row in native.source_basis["artifacts"]}
    row = next(row for row in records(person)
               if str(row["source_id"]) == saved.response["subject_id"])
    denied = person.client.post(
        "/v1/personal/enterprise-search",
        headers={"Authorization": "Bearer " + person.tokens[person.peer]},
        json={"query": saved.response["subject_id"], "source_types": ["field_feedback"]},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["items"] == [] and "合成现场反馈" not in denied.text
    _source, client, owner, scope, adapter = answer(person, row, project_id=work.project_id)
    before_calls = client.calls
    with Session(person.admin) as session, session.begin():
        session.get(Artifact, UUID(saved.source["id"])).revision += 1
    moved = next(item for item in records(person)
                 if str(item["source_id"]) == saved.response["subject_id"])
    assert moved["read_basis_status"] == "needs_recheck"
    assert moved["body"] == row["body"] and moved["content_hash"] == row["content_hash"]
    with Session(person.admin) as session, session.begin():
        session.get(Artifact, UUID(saved.source["id"])).status = "withdrawn"
    assert native_search(person, saved.response["subject_id"], ["field_feedback"])["items"] == []
    with pytest.raises(DomainError) as error:
        adapter.guard(scope)
    assert error.value.code in {"SOURCE_UNAVAILABLE", "FORBIDDEN_SCOPE"}
    assert client.calls == before_calls


def test_response_inherits_real_uploaded_parent_customer_class_and_current_scan_gate(
    knowledge_work, security_work,
):
    person = knowledge_work.setup
    content = "客户来件对应的固定原件。"
    original = uploaded(security_work, content=content.encode())
    artifact = parsed(security_work, original)
    source = {"kind": "artifact", "id": str(artifact), "revision": 1,
              "position": "line:1;quote_sha256:" + sha256(content.encode()).hexdigest()}
    saved = create_feedback(person, knowledge_work.config, source=source)
    for receipt in (saved.intake, saved.located, saved.response):
        apply_event(person, receipt["id"])
    scanner_calls = security_work.scanner.calls
    row = next(row for row in records(person)
               if str(row["source_id"]) == saved.response["subject_id"])
    assert row["customer_original"] and original in row["original_ids"]
    with native_session(person) as session:
        native = session.get(FieldResponseRecord, UUID(saved.response["subject_id"]))
        assert str(artifact) not in {value["artifact_id"] for value in native.reads}
    configuration = replace(
        security_work.runtime.configuration,
        scanner=replace(security_work.runtime.configuration.scanner, rules_version="field-test@2"),
    )
    configure(person.engine, replace(security_work.runtime, configuration=configuration))
    try:
        found = native_search(person, saved.response["subject_id"], ["field_feedback"])
        assert found["items"] == []
        assert "现场反馈跟进" not in str(found)
        assert security_work.scanner.calls == scanner_calls
    finally:
        configure(person.engine, security_work.runtime)
    assert native_search(person, saved.response["subject_id"], ["field_feedback"])["items"]
