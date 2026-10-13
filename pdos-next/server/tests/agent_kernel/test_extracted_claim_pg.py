"""Extraction-consumption proof for AI claims over the marked database."""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked database fixtures

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.models import AgentEvent, AgentToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Claim, Receipt
from tests.agent_kernel.test_extract_dispatch_pg import (
    extract as dispatch_extract,
)
from tests.agent_kernel.test_extract_dispatch_pg import (
    fixture as dispatch_fixture,
)
from tests.agent_kernel.test_extract_dispatch_pg import (
    quote_row,
)
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_m3_original_binding_pg import QUOTE
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


def prepared_run(work, security_work):
    owner, scope, host, client, calls, source, version_id, _, args = dispatch_fixture(
        work, security_work, rows_factory=quote_row
    )
    # The claim write path resolves its route through DomainCommands; use the same
    # synthetic stored-model route as the dispatch fixture's gateway.
    route = configured_route()
    owner.commands.route = lambda *_: route
    result = dispatch_extract(host, scope, source, args)
    assert result["rows"], result
    extract_call_id = result["execution_ref"]["call_id"]
    with owner.store.transaction(scope) as (session, _):
        event = session.scalar(
            select(AgentEvent).where(
                AgentEvent.run_id == scope.run_id,
                AgentEvent.body["key"].astext == "rfq_extraction",
            )
        )
        main = session.get(AgentToolCall, source.model_call_id)
        event_id, binding = event.id, dict(main.execution_binding)
    return owner, scope, version_id, extract_call_id, event_id, binding


def claim_call(owner, scope, binding, arguments, event_id):
    skill = owner.catalog._skills["rfq_extraction"]
    binding = (
        ModelBinding.model_validate(binding)
        .model_copy(
            update={
                "loaded_skills": (
                    SkillBinding(
                        key=skill.key,
                        version=skill.version,
                        digest=skill.digest,
                        load_event_id=event_id,
                    ),
                )
            }
        )
        .model_dump(mode="json")
    )
    identity, _ = owner.store.claim(
        scope, "claim-model:" + str(uuid4()), "model", {"fixture": True},
        execution_binding=binding,
    )
    owner.store.settle(
        scope, identity,
        result={"calls": [{"name": "evidence.claim.record", "arguments": arguments}]},
    )
    return identity


def record(owner, scope, event_id, binding, arguments):
    model_id = claim_call(owner, scope, binding, arguments, event_id)
    skill = owner.catalog._skills["rfq_extraction"]
    source = WriteSource(
        skill=SkillBinding(
            key=skill.key, version=skill.version, digest=skill.digest, load_event_id=event_id
        ),
        model_call_id=model_id,
        response_index=0,
    )
    return owner.commands.execute(
        scope,
        "evidence.claim.record",
        arguments,
        execution_key(scope.run_id, model_id, 0),
        source=source,
    )


def claim_arguments(version_id, extract_call_id, *, content=None, quote=None, **changes):
    return {
        "source": {
            "kind": "artifact",
            "id": str(version_id),
            "version": 1,
            "locator": "line:1",
            "quote": QUOTE if quote is None else quote,
        },
        "nature": "extracted",
        "availability": "known",
        "content": {"text": "合成合规要求"} if content is None else content,
        "extraction_ref": {"call_id": str(extract_call_id), "row_index": 0},
        **changes,
    }


def test_original_claim_consumes_the_actual_verified_extraction_row(work, security_work):
    owner, scope, version_id, extract_call_id, event_id, binding = prepared_run(
        work, security_work
    )
    arguments = claim_arguments(version_id, extract_call_id)
    saved = record(owner, scope, event_id, binding, arguments)
    with owner.store.transaction(scope) as (session, _):
        receipt = session.get(Receipt, UUID(saved["id"]))
        claim = session.get(Claim, receipt.subject_id)
        assert claim.artifact_id == version_id and claim.run_id == scope.run_id
        assert claim.nature == "extracted" and claim.status == "active"
        assert claim.extraction_ref == {"call_id": str(extract_call_id), "row_index": 0}
        assert claim.content == {"text": "合成合规要求"}


def test_legacy_shape_claim_also_consumes_the_row(work, security_work):
    owner, scope, version_id, extract_call_id, event_id, binding = prepared_run(
        work, security_work
    )
    arguments = {
        "artifact_id": str(version_id),
        "line": 1,
        "quote": QUOTE,
        "statement": "合成合规要求",
        "content": {"text": "合成合规要求"},
        "extraction_ref": {"call_id": str(extract_call_id), "row_index": 0},
    }
    saved = record(owner, scope, event_id, binding, arguments)
    with owner.store.transaction(scope) as (session, _):
        claim = session.get(Claim, session.get(Receipt, UUID(saved["id"])).subject_id)
        assert claim.statement == "合成合规要求" and claim.extraction_ref["row_index"] == 0


@pytest.mark.parametrize(
    "changes, reason",
    [
        ({"extraction_ref": None}, "extraction_ref_required"),
        ({"extraction_ref": {"call_id": str(uuid4()), "row_index": 0}}, "extraction_call_invalid"),
        ({"extraction_ref": {"call_id": "not-a-uuid", "row_index": 0}}, "extraction_ref_required"),
        ({"quote": "Synthetic original"}, "extraction_citation_mismatch"),  # 在原文但非抽取行引文
        ({"content": {"text": "篡改内容"}}, "extraction_content_mismatch"),
        ({"extraction_ref": {"call_id": "USE_ACTUAL", "row_index": 9}}, "extraction_row_missing"),
    ],
)
def test_claim_without_real_consumption_is_refused(work, security_work, changes, reason):
    owner, scope, version_id, extract_call_id, event_id, binding = prepared_run(
        work, security_work
    )
    arguments = claim_arguments(version_id, extract_call_id, **changes)
    ref = arguments.get("extraction_ref")
    if ref is None:
        arguments.pop("extraction_ref")
    elif ref.get("call_id") == "USE_ACTUAL":
        arguments["extraction_ref"] = {
            "call_id": str(extract_call_id), "row_index": ref["row_index"]
        }
    with pytest.raises(DomainError) as error:
        record(owner, scope, event_id, binding, arguments)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.detail["reason"].startswith("extraction")
