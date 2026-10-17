"""Registered extraction → actual standard match; synthetic provider only."""
# ruff: noqa: F811 -- pytest uses explicitly imported isolated PG fixtures

import json
from uuid import UUID, uuid4

import pytest
from pdos_agent_runtime.graph import registered_graph_context
from security_fixture import secured_parse
from sqlalchemy import select
from test_durable_evidence import upload_input

from pdos_next.agent_kernel.bindings import SkillBinding, execution_key
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, UploadedOriginal
from pdos_next.original_security import security_row
from pdos_next.providers.types import ProviderUsage
from tests.agent_kernel.test_extract_dispatch_pg import extract
from tests.agent_kernel.test_extract_dispatch_pg import fixture as extraction_fixture
from tests.preproject.test_category_context_pg import publish
from tests.preproject.test_derivation_transactions import synthetic_parent
from tests.preproject.test_g0 import work as work
from tests.preproject.test_standard_match_pg import counts
from tests.test_original_security import security_work as security_work

TEXT = "Synthetic requirement: noise must not exceed 75 dB(A), measured at one meter."
TOOL = "calc.spec_compare"


def upload(work, security_work):
    response = security_work.client.post(
        f"/v1/categories/{work.category}/originals",
        headers=work.headers,
        json=upload_input((TEXT + "\n").encode(), visibility="private").model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    root = UUID(response.json()["subject_id"])
    parsed = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": None,
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": str(root),
        },
        security_work.store,
    )
    assert parsed["status"] == "parsed", parsed
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        source = session.scalar(select(Artifact).where(Artifact.original_id == root))
        return root, source.id


def prepare(work, security_work, *, missing=False, kind="spec"):
    parameter = publish(work, unit="dB(A)", standard_condition="one meter")
    synthetic_parent(
        work,
        status="published",
        spec_values=[
            {
                "key": "noise",
                "parameter": "噪声",
                "parameter_id": UUID(parameter["parameter_id"]),
                "parameter_version": 1,
                "value_type": "number",
                "value": 70,
                "unit": "dB(A)",
                "condition_note": "one meter",
                "test_conditions": [],
                "exceptions": [],
            }
        ],
    )

    def row(artifact_id, text):
        return {
            "artifact_version_id": artifact_id,
            "locator": "line:1",
            "quote": text,
            "kind": kind,
            "statement": "噪声不高于75 dB(A)，一米处测量",
            "spec": {
                "key": "noise",
                "parameter": "噪声",
                "value_type": "number",
                "upper": 75,
                "unit": None if missing else "dB(A)",
                "availability": "known",
                "condition_note": None if missing else "one meter",
            }
            if kind == "spec"
            else None,
            "missing": ["unit", "condition_note"] if missing else [],
        }

    owner, scope, host, client, calls, source, *_tail, args = extraction_fixture(
        work, security_work, rows_factory=row, uploader=upload, mount_quote=TEXT
    )
    extracted = extract(host, scope, source, args)
    production = owner.adapters()
    host.adapters.read_tools[TOOL] = production.read_tools[TOOL]
    host.adapters.read_restores[TOOL] = production.read_restores[TOOL]
    arguments = {
        "subjects": [{"type": "product", "id": str(work.product)}],
        "extraction_ref": {"call_id": extracted["execution_ref"]["call_id"]},
    }

    def compare_turn(_):
        return ModelTurn(
            calls=(ToolCall(id="compare-extracted", name=TOOL, arguments=arguments),),
            usage=ProviderUsage(10, 2),
        )

    client.callback = compare_turn
    with owner.store.transaction(scope) as (_, run):
        binding = next(SkillBinding.model_validate(skill)
            for snapshot in run.versions["context_snapshots"].values()
            for skill in snapshot["skills"] if skill["key"] == "rfq_extraction")
    context = host.skill_context(scope, "Synthetic extracted comparison", bindings=(binding,))
    with registered_graph_context("xiaopai"):
        turn = host.model(
            scope,
            system="frozen synthetic main prefix",
            messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            tools=owner.registry.definitions(),
            output_schema={"type": "object"},
            loaded_skills=(binding,),
        )
    source = ReadSource(model_call_id=turn.ledger_call_id, response_index=0)
    key = execution_key(scope.run_id, source.model_call_id, 0)
    return owner, scope, host, client, source, key, arguments, parameter, extracted


def read(f):
    owner, scope, host, _, source, key, arguments, *_ = f
    return host.read(scope, owner.registry.get(TOOL), arguments, key, source=source)


def test_private_extracted_rows_match_actual_published_model_and_replay_without_writes(
    work,
    security_work,
):
    f = prepare(work, security_work)
    before = counts(work)
    result = read(f)
    assert result["mode"] == "extracted_standard_match"
    assert result["summary"] == {
        "selected_rows": 1,
        "spec_rows": 1,
        "non_spec_rows": 0,
        "mapped_specs": 1,
        "ambiguous_specs": 0,
        "unmapped_specs": 0,
    }
    assert result["products"][0]["status"] == "selected_specs_meet", result["products"]
    assert result["rows"][0]["parameter_mapping"]["basis"] == "exact_dictionary_label"
    required = result["requirements"][0]
    assert required["parameter_id"] == f[7]["parameter_id"] and required["lower"] is None
    assert required["upper"] == "75" and required["nature"] == "extracted"
    assert result["rows"][0]["citation"]["quote"] == TEXT
    assert result["limitations"][:2] == [
        "selected_specifications_only",
        "human_understanding_not_confirmed",
    ]
    assert result["execution_ref"]["read_kind"] == "ordinary/v1"
    owner, scope, *_ = f
    with owner.store.transaction(scope) as (session, _):
        calls = list(
            session.scalars(select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id))
        )
        before_calls = [(c.id, c.state) for c in calls]
    assert read(f) == result and counts(work) == before
    with owner.store.transaction(scope) as (session, _):
        assert [
            (c.id, c.state)
            for c in session.scalars(
                select(AgentToolCall).where(AgentToolCall.run_id == scope.run_id)
            )
        ] == before_calls
    # A new dictionary current is not silently substituted on original-call replay.
    publish(
        work,
        parameter_id=f[7]["parameter_id"],
        expected_current_version=1,
        change_note="Synthetic new dictionary version",
    )
    with pytest.raises(DomainError) as stale:
        read(f)
    assert stale.value.code == "SOURCE_STALE"


def test_extraction_omissions_remain_unknown_even_when_dictionary_has_defaults(work, security_work):
    f = prepare(work, security_work, missing=True)
    result = read(f)
    required = result["requirements"][0]
    assert required["unit"] is required["condition_note"] is None
    check = result["products"][0]["checks"][0]
    assert check["status"] == "unknown"
    assert {"unit_missing", "condition_missing"} <= set(check["reasons"])
    assert result["products"][0]["status"] == "needs_review"


def test_non_spec_rows_and_changed_original_never_become_all_requirements_satisfied(
    work,
    security_work,
):
    f = prepare(work, security_work, kind="compliance")
    result = read(f)
    assert result["requirements"] == result["products"] == []
    assert result["summary"]["non_spec_rows"] == 1 and result["summary"]["spec_rows"] == 0
    assert "non_spec_requirements_require_review" in result["limitations"]
    row = result["rows"][0]
    artifact_id = UUID(row["citation"]["artifact_id"])
    with f[0].store.transaction(f[1]) as (session, _):
        root = session.get(Artifact, artifact_id).original_id
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.human,
        requester_id=work.human,
        category_id=work.category,
    ) as session:
        epoch = security_row(session, session.get(UploadedOriginal, root), lock=False).epoch
    scan = security_work.client.post(
        f"/v1/categories/{work.category}/originals/{root}/scan",
        headers=work.headers,
        json={"expected_epoch": epoch, "idempotency_key": str(uuid4())},
    )
    assert scan.status_code == 200, scan.text
    with pytest.raises(DomainError):
        read(f)
