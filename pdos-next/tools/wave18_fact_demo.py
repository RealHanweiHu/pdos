"""Actual synthetic Rule + partial Observation on the verified retained target.

Supporting sources/qualification are explicitly synthetic. Original failure,
Issue Current and candidates are never updated. No independent Review or
effectiveness/close qualification is issued. Exact requests stay private.
"""

# ruff: noqa: I001
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from local_environment import ROOT
from wave16_closeout import private_json
from wave17_migrate import target
from pdos_next.api import create_app
from pdos_next.capa_rule_import import publish_rule
from pdos_next.contracts import Command
from pdos_next.database import engine_for, tenant_session
from pdos_next.domain.capa_effectiveness import (
    candidate_commands,
    candidate_storage,
    fact_commands,
)
from pdos_next.domain.capa_effectiveness import fact_atom_storage, fact_storage_models
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.fact_write import prepare_fact
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.professional_authority.schemas import FactInput
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.models import Product
from pdos_next.original_store import OriginalStore
from pdos_next.professional_import import import_professional_fact
from pdos_next.security_bootstrap import local_runtime
from pdos_next.service import Context, execute
from sqlalchemy import select, text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave18-20261003"
PLAN = ROOT / ".local/wave18-fact-demo.json"


def private_save(value):
    PLAN.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    PLAN.chmod(0o600)


def source(identity, line, quote):
    return {
        "id": str(identity),
        "revision": 1,
        "kind": "artifact",
        "position": f"line:{line};quote_sha256:{sha256(quote.encode()).hexdigest()}",
    }


def serial(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def main():
    tag, action = sys.argv[1:]
    assert tag.startswith("v") and tag[1:].isdigit() and action in {"setup", "rule", "observation"}
    REPORT.mkdir(parents=True, exist_ok=True)
    output = REPORT / f"actual-fact-{action}-{tag}.json"
    assert not output.exists()
    result = {
        "status": "RUNNING",
        "action": action,
        "started_at": datetime.now(UTC).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
        "model_calls": 0,
        "steps": [],
        "synthetic_only": True,
        "review_writes": 0,
        "effectiveness_writes": 0,
        "close_writes": 0,
    }
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    ids = private_json(ROOT / ".local/wave16-saved-ids.json")
    assert seed["marker"] == state["marker"]
    tenant, actor, pid = (UUID(seed[k]) for k in ("tenant_id", "actor_id", "product_id"))
    profile = {
        "tenant_id": str(tenant),
        "product_id": str(pid),
        "project_id": seed["project_id"],
        "issuer_key": "local-synthetic-capa-rule",
        "issuer_version": "v1",
    }
    profile_path = ROOT / ".local/capa-facts-synthetic-profile.json"
    if profile_path.exists():
        assert private_json(profile_path) == profile
    else:
        profile_path.write_text(serial(profile) + "\n")
        profile_path.chmod(0o600)
    ctx = Context(tenant, actor, actor)
    engine, auth = engine_for(state["app_url"]), engine_for(state["auth_url"])
    os.environ["PDOS_FILE_SECURITY_PROFILE"] = "local-synthetic-v1"
    store = OriginalStore(ROOT / ".local/objects")
    security = await local_runtime(store)
    try:
        create_app(
            engine,
            auth,
            object_store=store,
            security_runtime=security,
            lifecycle_enabled=True,
            professional_synthetic_scope={"tenant_id": str(tenant), "product_id": str(pid)},
            operational_synthetic_profile=private_json(
                ROOT / ".local/operational-synthetic-profile.json"
            ),
            test_resource_synthetic_profile=private_json(
                ROOT / ".local/test-resource-synthetic-profile.json"
            ),
            quality_synthetic_profile=private_json(ROOT / ".local/quality-synthetic-profile.json"),
            quality_followup_synthetic_profile=private_json(
                ROOT / ".local/quality-followup-synthetic-profile.json"
            ),
            capa_facts_synthetic_profile=profile,
        )
        with engine_for(state["admin_url"]).connect() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
        runtime = engine._pdos_capa_fact_runtime
        publisher = runtime.host.owner.publisher
        if PLAN.exists():
            plan = private_json(PLAN)
            assert plan["marker"] == state["marker"]
        else:
            assert action == "setup"
            with tenant_session(engine, tenant) as s:
                candidate = s.scalar(
                    select(CapaVerificationEvidence)
                    .where(CapaVerificationEvidence.issue_id == UUID(ids["issue"]))
                    .order_by(CapaVerificationEvidence.created_at, CapaVerificationEvidence.id)
                )
                saved = candidate_storage.read_candidate(
                    s, ctx, pid, candidate.id, semantic_owner=candidate_commands.semantic_owner()
                )
                anchor = saved.body.stable_anchor
                old_policy = policy.assess(
                    s, ctx, pid, anchor.origin.scope.project_id, anchor.origin.purpose
                )
                product_revision = s.get(Product, pid).revision
            origin, failure = anchor.origin, anchor.origin.issue.failures[0]
            at, key = datetime.now(UTC), str(uuid4())
            valid_from, valid_until = at - timedelta(minutes=1), at + timedelta(days=2)
            rule_payload = {
                "issue_id": str(origin.issue_id),
                "expected_issue_revision": origin.ref.revision,
                "capa_id": str(origin.issue.capa.id),
                "origin": origin.ref.model_dump(mode="json"),
                "previous": None,
                "external_id": f"wave18:{key}:rule",
                "policy_ref": old_policy["sources"][0],
                "method": failure.method.model_dump(mode="json"),
                "criterion": failure.criterion.model_dump(mode="json"),
                "sampling": {
                    "targets": [
                        {
                            "key": "retained-synthetic-sample",
                            "kind": "sample",
                            "ref": {
                                "id": str(failure.sample.id),
                                "revision": failure.sample.revision,
                            },
                            "actual_configuration": failure.sample.actual_configuration.model_dump(
                                mode="json"
                            ),
                            "identity_sources": [failure.source.model_dump(mode="json")],
                        }
                    ],
                    "minimum_records": 2,
                    "sampling_method": failure.method.model_dump(mode="json"),
                    "acceptance": failure.criterion.model_dump(mode="json"),
                    "observation_from": origin.issue.capa.actions[
                        0
                    ].completion.at.occurred_at.isoformat(),
                    "observation_until": (
                        origin.issue.capa.requirement.observation_until.isoformat()
                    ),
                    "require_named_review": True,
                    "require_run_review": True,
                    "require_disposition": True,
                },
                "rule_material": {
                    "requirement": origin.issue.capa.requirement.model_dump(mode="json"),
                    "limitation": (
                        "local synthetic partial observation; "
                        "actual paired execution still required"
                    ),
                },
                "independence_material": {
                    "required": "actual participant owners and independent named qualified caller"
                },
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "visibility": origin.visibility,
            }
            # Validate and normalize genuine frozen DTO clock/ref encodings.
            provisional = fact_commands.RulePublicationInput.model_validate(
                {
                    **rule_payload,
                    "sources": [failure.criterion.model_dump(mode="json")],
                    "reason": "本地合成固定规则出版演练",
                }
            )
            fields = set(rule_payload) - {"issue_id", "expected_issue_revision", "capa_id"}
            publication = serial(
                {
                    "schema_version": "pdos-capa-rule-publication-source-v1",
                    "nature": "synthetic",
                    "scope": origin.scope.model_dump(mode="json"),
                    "issue_id": str(origin.issue_id),
                    "capa_id": str(origin.issue.capa.id),
                    "purpose": origin.purpose,
                    "material": provisional.model_dump(mode="json", include=fields),
                }
            )
            qualification = serial(
                {
                    "nature": "synthetic",
                    "subject_id": str(actor),
                    "role": "quality",
                    "scope": origin.scope.model_dump(mode="json"),
                    "operations": [
                        fact_commands.RULE_OPERATION,
                        fact_commands.OBSERVATION_OPERATION,
                    ],
                    "purpose": origin.purpose,
                    "issued_at": at.isoformat(),
                    "valid_from": valid_from.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "limitation": (
                        "isolated local Rule import and partial own Observation only; "
                        "no Review, effectiveness, close or production authority"
                    ),
                }
            )
            plan = {
                "marker": state["marker"],
                "key": key,
                "scope": origin.scope.model_dump(mode="json"),
                "actor_id": str(actor),
                "purpose": origin.purpose,
                "product_revision": product_revision,
                "rule_payload": provisional.model_dump(mode="json", exclude={"sources", "reason"}),
                "publication": publication,
                "qualification": qualification,
                "issued_at": at.isoformat(),
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "source_command_id": str(uuid4()),
                "rule_command_id": str(uuid4()),
                "facts": {
                    kind: {"command_id": str(uuid4()), "external_id": f"wave18:{key}:{kind}"}
                    for kind in ("duty", "qualification")
                },
            }
            private_save(plan)
        if action == "setup":
            with tenant_session(engine, tenant) as s:
                receipt = execute(
                    s,
                    ctx,
                    Command(
                        command_id=UUID(plan["source_command_id"]),
                        idempotency_key=f"wave18:{plan['key']}:source",
                        operation="evidence.artifact.register",
                        product_id=pid,
                        expected_revision=plan["product_revision"],
                        payload={
                            "title": "本地合成 · 固定核验规则与观察职责",
                            "content": plan["publication"] + "\n" + plan["qualification"],
                            "source_label": (
                                "Explicit marked local synthetic; no production authority"
                            ),
                            "visibility": plan["rule_payload"]["visibility"],
                        },
                    ),
                )
            plan["source_receipt"] = receipt
            private_save(plan)
            issuer = engine._pdos_professional_issuers["local-synthetic-authority"]
            for kind, choice in plan["facts"].items():
                data = FactInput(
                    product_id=pid,
                    project_id=UUID(plan["scope"]["project_id"]),
                    subject_id=actor,
                    external_id=choice["external_id"],
                    kind=kind,
                    role="quality",
                    operations=[fact_commands.RULE_OPERATION, fact_commands.OBSERVATION_OPERATION],
                    purposes=[plan["purpose"]],
                    valid_from=plan["valid_from"],
                    valid_until=plan["valid_until"],
                    approval={
                        "system": "explicit-local-synthetic-wave18",
                        "external_id": choice["external_id"],
                        "version": "v1",
                        "approved_by": "本地合成具名签发，无生产资格",
                        "issued_at": plan["issued_at"],
                    },
                    sources=[
                        {
                            "artifact_id": receipt["subject_id"],
                            "expected_revision": 1,
                            "line": 2,
                            "quote": plan["qualification"],
                        }
                    ],
                    reason="仅新规则出版及本人实际观察合成资格，不授独立复核、有效性、关闭或生产",
                )
                with tenant_session(engine, tenant) as s:
                    choice["receipt"] = import_professional_fact(
                        s,
                        ctx,
                        issuer,
                        data.model_dump(mode="json"),
                        request_key=choice["external_id"],
                        command_id=UUID(choice["command_id"]),
                    )
                private_save(plan)
            result["steps"].append(
                {"name": "supporting-source-and-two-professional-facts", "saved": True}
            )
        if action == "rule":
            payload = fact_commands.RulePublicationInput.model_validate(
                {
                    **plan["rule_payload"],
                    "sources": [
                        source(plan["source_receipt"]["subject_id"], 1, plan["publication"])
                    ],
                    "reason": "本地合成发布固定核验规则，部分观察与专业独立复核仍分别办理",
                }
            )
            with tenant_session(engine, tenant) as s:
                phase = prepare_fact(s, ctx, pid, payload, host=runtime.host)
                try:
                    reads = [
                        value.model_dump(mode="json") for value in phase.required_source_read_set
                    ]
                finally:
                    runtime.host.invalidate(phase)
                command = Command(
                    command_id=UUID(plan["rule_command_id"]),
                    idempotency_key=f"wave18:{plan['key']}:rule",
                    operation=fact_commands.RULE_OPERATION,
                    product_id=pid,
                    expected_revision=plan["product_revision"],
                    source_read_set=reads,
                    payload=payload.model_dump(mode="json"),
                )
                plan["rule_command"] = command.model_dump(mode="json")
                private_save(plan)
                receipt = publish_rule(s, ctx, command, publisher=publisher)
                s.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            plan["rule_receipt"] = receipt
            private_save(plan)
            with tenant_session(engine, tenant) as s:
                row = s.get(fact_storage_models.RuleFact, UUID(receipt["subject_id"]))
                atom = fact_atom_storage.read_fact_atom(
                    s, ctx, pid, kind="rule", fact_id=row.id, revision=row.revision
                )
                fact = assemble_fact(
                    row.fact_body, atom.atom, expected_payload_sha256=row.payload_sha256
                )
                assert fact.nature == "synthetic" and fact.provenance.proof_id is None
                plan["rule_ref"] = fact.ref.model_dump(mode="json")
            private_save(plan)
            result["steps"].append(
                {
                    "name": "actual-rule-common-group-readback",
                    "receipt_id": receipt["id"],
                    "fact_id": receipt["subject_id"],
                    "read_count": len(reads),
                    "host_import_proof_null": True,
                }
            )
        if action == "observation":
            assert "rule_ref" in plan and "rule_receipt" in plan
            if "observation_setup" not in plan:
                observed_from = datetime.now(UTC)
                with tenant_session(engine, tenant) as s:
                    selector = type(
                        "SelectedRule",
                        (),
                        {"rule": fact_commands.FactRef.model_validate(plan["rule_ref"])},
                    )()
                    rule, saved = runtime.host.owner._rule(s, ctx, pid, selector)
                    current_ref = runtime.host.owner._anchor(s, ctx, pid, saved)
                    pointer = s.scalar(
                        select(QualityIssueCurrent).where(
                            QualityIssueCurrent.tenant_id == tenant,
                            QualityIssueCurrent.product_id == pid,
                            QualityIssueCurrent.issue_id == UUID(ids["issue"]),
                        )
                    )
                    candidates = list(
                        s.scalars(
                            select(CapaVerificationEvidence)
                            .where(
                                CapaVerificationEvidence.tenant_id == tenant,
                                CapaVerificationEvidence.product_id == pid,
                                CapaVerificationEvidence.issue_id == UUID(ids["issue"]),
                            )
                            .order_by(
                                CapaVerificationEvidence.created_at, CapaVerificationEvidence.id
                            )
                        )
                    )
                    assert (
                        pointer.issue_version_id == current_ref.id and pointer.issue_revision == 6
                    )
                    assert len(candidates) == 2
                    actual_snapshot = {
                        "inspection_kind": "actual-retained-system-snapshot",
                        "current_issue": current_ref.model_dump(mode="json"),
                        "saved_candidates": [
                            {
                                "id": str(v.id),
                                "revision": v.revision,
                                "result": v.result,
                                "applicable": v.applicable,
                                "independently_verified": v.independently_verified,
                                "observation_complete": v.observation_complete,
                            }
                            for v in candidates
                        ],
                        "physical_retest_performed": False,
                        "current_physical_measurement": None,
                        "limitation": (
                            "Marked local synthetic native inspection of actual "
                            "retained records; not an instrument report, sample coverage, "
                            "effectiveness or independent Review"
                        ),
                    }
                observed_until = datetime.now(UTC)
                assert observed_from < observed_until < datetime.now(UTC)
                record = {
                    "target_key": rule.sampling.targets[0].key,
                    "occurred_at": observed_until.isoformat(),
                    "original_timezone": "UTC",
                    "raw_material": actual_snapshot,
                }
                envelope = {
                    "schema_version": "pdos-capa-observation-source-v1",
                    "nature": saved.origin.nature,
                    "scope": saved.origin.scope.model_dump(mode="json"),
                    "issue_id": str(saved.origin.issue_id),
                    "capa_id": str(saved.origin.issue.capa.id),
                    "purpose": saved.origin.purpose,
                    "rule": rule.ref.model_dump(mode="json"),
                    "record": record,
                    "observed_from": observed_from.isoformat(),
                    "observed_until": observed_until.isoformat(),
                    "at": {"occurred_at": observed_until.isoformat(), "original_timezone": "UTC"},
                }
                setup = {
                    "publication": serial(envelope),
                    "record": record,
                    "observed_from": observed_from.isoformat(),
                    "observed_until": observed_until.isoformat(),
                    "source_command_id": str(uuid4()),
                    "command_id": str(uuid4()),
                    "idempotency_key": str(uuid4()),
                }
                plan["observation_setup"] = setup
                private_save(plan)
            setup = plan["observation_setup"]
            if "source_receipt" not in setup:
                with tenant_session(engine, tenant) as s:
                    source_receipt = execute(
                        s,
                        ctx,
                        Command(
                            command_id=UUID(setup["source_command_id"]),
                            idempotency_key=f"wave18:{plan['key']}:partial-observation-source",
                            operation="evidence.artifact.register",
                            product_id=pid,
                            expected_revision=s.get(Product, pid).revision,
                            payload={
                                "title": "本地合成 · 存续记录实际快照观察（未实物复测）",
                                "content": setup["publication"],
                                "source_label": (
                                    "Explicit local native synthetic inspection; "
                                    "no physical remeasurement"
                                ),
                                "visibility": plan["rule_payload"]["visibility"],
                            },
                        ),
                    )
                setup["source_receipt"] = source_receipt
                private_save(plan)
            ref = source(setup["source_receipt"]["subject_id"], 1, setup["publication"])
            payload = fact_commands.ObservationPayload.model_validate(
                {
                    "issue_id": ids["issue"],
                    "expected_issue_revision": 6,
                    "capa_id": plan["rule_payload"]["capa_id"],
                    "rule": plan["rule_ref"],
                    "target_keys": [setup["record"]["target_key"]],
                    "observed_from": setup["observed_from"],
                    "observed_until": setup["observed_until"],
                    "at": {
                        "occurred_at": setup["observed_until"],
                        "original_timezone": "UTC",
                        "source": ref,
                    },
                    "records": [{**setup["record"], "sources": [ref]}],
                    "coverage_sources": [ref],
                    "sources": [ref],
                    "reason": (
                        "保存实际系统快照的本地合成部分观察；未实物复测，"
                        "抽样和未来截止区间仍缺，不能判有效或关闭"
                    ),
                    "visibility": plan["rule_payload"]["visibility"],
                }
            )
            with tenant_session(engine, tenant) as s:
                command = Command(
                    command_id=UUID(setup["command_id"]),
                    idempotency_key=setup["idempotency_key"],
                    operation=fact_commands.OBSERVATION_OPERATION,
                    product_id=pid,
                    expected_revision=s.get(Product, pid).revision,
                    payload=payload.model_dump(mode="json", exclude={"confirmation_token"}),
                )
            setup["command"] = command.model_dump(mode="json")
            private_save(plan)
            result["steps"].append(
                {
                    "name": "actual-native-partial-observation-source-and-original-request",
                    "source_saved": True,
                    "fact_saved": False,
                    "observed_from": setup["observed_from"],
                    "observed_until": setup["observed_until"],
                    "physical_retest_performed": False,
                    "measurement_invented": False,
                }
            )
        result["status"] = "PASS_SYNTHETIC_" + action.upper()
    except Exception as error:
        result["status"] = "FAIL"
        result["error_type"] = type(error).__name__
        result["error_code"] = getattr(error, "code", None)
        # No raw SQL/credential-bearing exception in public output.
        raise RuntimeError(
            "Marked local fact check failed; inspect the retained sanitized evidence"
        ) from None
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        if security is not None:
            await security.scanner.close()
        engine.dispose()
        auth.dispose()
        print(json.dumps({"status": result["status"], "action": action, "steps": result["steps"]}))


if __name__ == "__main__":
    asyncio.run(main())
