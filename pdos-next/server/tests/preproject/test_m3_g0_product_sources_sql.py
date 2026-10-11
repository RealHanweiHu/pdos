"""Exact G0 source exceptions; PG probes are run only by the root coordinator."""
# ruff: noqa: F811 -- shared explicit isolated PG fixture

import hashlib
from copy import copy, deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from migrations import schema_s0_0751 as migration
from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionSource
from tests.preproject.test_evidence_commands_pg import evidence_request
from tests.preproject.test_g0 import create, decide_request, post, read, save, submit
from tests.preproject.test_g0 import work as work  # noqa: F401
from tests.preproject.test_m3_lifecycle_catalog import product_artifact, scoped
from tests.test_original_security import security_work as security_work  # noqa: F401
from tests.test_project_first_plan import cmd

QUOTE = "Synthetic exact public source"
SIGNATURE = "m3_g0_product_source_proven(uuid,uuid,uuid,uuid,uuid,integer,integer,text,boolean)"


def test_legacy_source_guard_and_complete_definition_audience_remain():
    legacy_condition = migration.PREDECESSOR_SOURCE_CONSUMER.split(" THEN RAISE EXCEPTION")[0]
    assert migration.SOURCE_CONSUMER.startswith(legacy_condition)
    assert "TG_TABLE_NAME='definition_sources' AND TG_OP='INSERT'" in migration.SOURCE_CONSUMER
    assert "m3_g0_product_source_proven" in migration.SOURCE_CONSUMER
    old_tail = migration.PREDECESSOR_SOURCE_VISIBLE.split(" -- INSERT RETURNING", 1)[1]
    assert migration.SOURCE_VISIBLE.split(" -- INSERT RETURNING", 1)[1] == old_tail
    assert "public.direct_source_set_visible" in migration.SOURCE_VISIBLE
    assert "CREATE OR REPLACE FUNCTION public.direct_source_set_visible" not in "\n".join(
        migration.SCHEMA_SQL
    )


def test_source_proof_binds_signed_citation_current_transaction_and_historical_provenance():
    sql = migration.G0_PRODUCT_SOURCE_PROVEN
    for fragment in (
        "created_definition_id=did AND created_product_id=p AND outcome='approved'",
        "decision.review_digest IS DISTINCT FROM submission.document_digest",
        "submission.frozen_document->'source_refs'",
        "(ref->>'id')::uuid=sid",
        "(ref->>'version')::integer=ver",
        "(ref->>'line')::integer=source_line",
        "ref->>'quote'=source_quote",
        "public.m3_evidence_source_reader(t,c,'artifact',sid)",
        "header_xid IS NOT DISTINCT FROM decision_xid",
        "public.m3_result_access(t,c,'definition_revisions',did)",
        "definition.sealed IS FALSE",
        "definition.source_submission_id IS DISTINCT FROM submission.id",
        "receipt.operation IS DISTINCT FROM 'proposal.g0.decide'",
    ):
        assert fragment in sql
    assert migration.SCHEMA_SQL[-1] == (
        f"REVOKE ALL ON FUNCTION public.{SIGNATURE} "
        "FROM PUBLIC,pdos_next_app,pdos_next_auth,pdos_next_dispatch,pdos_agent"
    )


def test_down_restores_exact_actual_functions_and_select_policy():
    assert migration.DOWNGRADE_SQL == (
        migration.PREDECESSOR_SOURCE_READ_POLICY,
        migration.PREDECESSOR_SOURCE_VISIBLE,
        migration.PREDECESSOR_SOURCE_CONSUMER,
        f"DROP FUNCTION public.{SIGNATURE}",
    )
    for sql, expected in zip(
        (
            migration.PREDECESSOR_SOURCE_CONSUMER,
            migration.PREDECESSOR_SOURCE_VISIBLE,
            migration.PREDECESSOR_SOURCE_READ_POLICY,
        ),
        (
            "dd49b520069946ed65f04948c78d33d6030886a11d2de3e68c181f8e6e599d66",
            "9122ca38e78b78d72e922c599d13bd04f7fea66fdd536a218df27127732e303f",
            "0a3d9aab65f12bdebb664725473cbe63f463b27e27ca01601dff600b428a6930",
        ),
        strict=True,
    ):
        assert hashlib.sha256(sql.encode()).hexdigest() == expected


def product_source_g0(work, *, source_id=None, project_owner=None):
    source_id = source_id or product_artifact(work)
    proposal_id, _ = create(work)
    item = read(work, proposal_id).json()["items"][0]
    linked = post(
        work,
        evidence_request(
            work,
            "evidence.link.create",
            {
                "evidence": {
                    "type": "artifact",
                    "id": str(source_id),
                    "version": 1,
                    "locator": "line:1",
                },
                "target": {
                    "type": "proposal_item",
                    "id": item["item_id"],
                    "version": item["version"],
                },
                "relation": "supports",
            },
        ),
    )
    assert linked.status_code == 200, linked.text
    submit(work, proposal_id)
    decision = decide_request(work, proposal_id)
    if project_owner is not None:
        decision["payload"]["project"]["owner_id"] = str(project_owner)
    receipt, _ = save(work, decision, actor=work.peer)
    result = receipt["result"]
    assert UUID(result["product_id"]) != work.product
    return {
        "t": work.tenant,
        "c": work.category,
        "p": UUID(result["product_id"]),
        "d": UUID(result["definition_id"]),
        "a": source_id,
        "v": 1,
        "line": 1,
        "quote": QUOTE,
        "writing": False,
        "project_id": result["project_id"],
    }


def unmatched_product_artifact(work, args):
    """A distinct foreign source, not semantic replay of the signed registration."""
    from pdos_next.models import Artifact

    source_product = copy(work)
    assert source_product.product != args["p"]
    unrelated = product_artifact(
        source_product, body=f"{QUOTE}\nSynthetic unsigned source {uuid4()}"
    )
    assert unrelated != args["a"]
    with scoped(work) as session:
        actual = session.get(Artifact, unrelated)
        assert actual is not None and actual.product_id == source_product.product
        assert actual.product_id != args["p"]
        assert (
            session.scalar(
                select(DefinitionSource.id).where(
                    DefinitionSource.tenant_id == work.tenant,
                    DefinitionSource.category_id == work.category,
                    DefinitionSource.product_id == args["p"],
                    DefinitionSource.artifact_id == unrelated,
                )
            )
            is None
        )
    return unrelated


def prove(session, arguments):
    return session.scalar(
        text("SELECT m3_g0_product_source_proven(:t,:c,:p,:d,:a,:v,:line,:quote,:writing)"),
        arguments,
    )


def test_pg_g0_product_artifact_source_survives_commit_and_retains_current_rls(work):
    args = product_source_g0(work)
    with scoped(work) as session:
        source = session.scalar(
            select(DefinitionSource).where(DefinitionSource.definition_id == args["d"])
        )
        assert source is not None and source.artifact_id == args["a"]
        assert source.product_id == args["p"] != work.product
        assert source.source_revision == 1 and source.line == 1 and source.quote == QUOTE
    route = f"/v1/categories/{work.category}/products/{args['p']}/definitions"
    response = work.client.get(route, headers=work.headers)
    assert response.status_code == 200, response.text
    fixed = next(row for row in response.json()["items"] if row["id"] == str(args["d"]))
    assert fixed["sealed"] is True
    assert fixed["sources"][0]["artifact_id"] == str(args["a"])
    with scoped(work, admin=True) as session:
        assert prove(session, args) is True
        assert prove(session, {**args, "writing": True}) is False


@pytest.mark.parametrize("changed", ["a", "d", "p", "c", "t", "v", "line", "quote"])
def test_pg_signed_source_exception_rejects_any_citation_or_scope_substitution(work, changed):
    args = product_source_g0(work)
    replacement = (
        2 if changed in {"v", "line"} else "Unrelated quote" if changed == "quote" else uuid4()
    )
    with scoped(work, admin=True) as session:
        assert prove(session, args) is True
        assert prove(session, {**args, changed: replacement}) is False


def test_pg_native_definition_remains_valid_without_g0_and_gets_no_new_exception(work):
    artifact_id = product_artifact(work)
    source = {"artifact_id": str(artifact_id), "expected_revision": 1, "line": 1, "quote": QUOTE}
    response = post(
        work,
        cmd(
            work,
            "product.definition.draft",
            {
                "title": "Ordinary native definition",
                "purpose": "Preserve existing source contract",
                "use_cases": ["Synthetic compatibility"],
                "change_reason": "Synthetic native draft",
                "sources": [source],
            },
            str(artifact_id),
        ),
    )
    assert response.status_code == 200, response.text
    with scoped(work, admin=True) as session:
        assert (
            prove(
                session,
                {
                    "t": work.tenant,
                    "c": work.category,
                    "p": work.product,
                    "d": UUID(response.json()["subject_id"]),
                    "a": artifact_id,
                    "v": 1,
                    "line": 1,
                    "quote": QUOTE,
                    "writing": True,
                },
            )
            is False
        )


def test_pg_private_proof_has_no_runtime_execute_and_does_not_replace_membership(work):
    args = product_source_g0(work)
    with Session(work.admin) as session:
        for role in ("pdos_next_app", "pdos_next_auth", "pdos_next_dispatch", "pdos_agent"):
            assert (
                session.scalar(
                    text("SELECT has_function_privilege(:role,:signature,'EXECUTE')"),
                    {"role": role, "signature": SIGNATURE},
                )
                is False
            )
    with tenant_session(
        work.admin, work.tenant, actor_id=uuid4(), requester_id=uuid4(), category_id=work.category
    ) as session:
        assert prove(session, args) is False


def test_pg_historical_g0_does_not_bypass_newly_private_source_product(work):
    args = product_source_g0(work)

    class RollbackProbe(Exception):
        pass

    # Roll back the permission-change probe. The G0 and its actual source were
    # established above through public commands; no business proof is fabricated.
    with pytest.raises(RollbackProbe):
        with tenant_session(
            work.admin,
            work.tenant,
            actor_id=work.peer,
            requester_id=work.peer,
            category_id=work.category,
        ) as session:
            assert prove(session, args) is True
            session.execute(
                text("UPDATE products SET visibility='private' WHERE tenant_id=:t AND id=:p"),
                {"t": work.tenant, "p": work.product},
            )
            assert prove(session, args) is False
            raise RollbackProbe


def consumer_commands(work, args, *, actor=None):
    from tests.test_configurations import accepted, bom_payload, command
    from tests.test_project_first_plan import application, proposal_command
    from tests.test_project_first_plan import post as product_post

    target = copy(work)
    target.product = args["p"]
    if actor is not None:
        target.headers = {"Authorization": f"Bearer {work.tokens[actor]}"}
    definition = (str(args["a"]), str(args["d"]))
    proposed = product_post(target, proposal_command(target, definition, args["project_id"]))
    assert proposed.status_code == 200, proposed.text
    plan = application(target, definition, args["project_id"], proposed.json()["subject_id"])
    plan_preview = product_post(target, plan, preview=True)
    assert plan_preview.status_code == 200, plan_preview.text

    # Configuration's own source is native; only the inherited Definition source
    # crosses Products. This cannot be satisfied by relaxing ordinary BOM inputs.
    native = product_artifact(target)
    native_ref = {"artifact_id": str(native), "expected_revision": 1, "line": 1, "quote": QUOTE}
    native_reads = [{"artifact_id": str(native), "expected_revision": 1}]
    bom, _, _ = accepted(
        target, command(target, "engineering.bom.revise", bom_payload(native_ref), native_reads)
    )
    engineering = command(
        target,
        "engineering.configuration.create",
        {
            "name": "Signed G0 source configuration",
            "reason": "Consume actual fixed definition and native BOM",
            "visibility": "private",
            "sources": [native_ref],
            "definition_id": str(args["d"]),
            "expected_definition_revision": 1,
            "bom_id": bom["subject_id"],
            "expected_bom_revision": 1,
        },
        [*native_reads, {"artifact_id": str(args["a"]), "expected_revision": 1}],
    )
    engineering_preview = product_post(target, engineering, preview=True)
    assert engineering_preview.status_code == 200, engineering_preview.text
    return target, [
        (plan, plan_preview.json()["command"]),
        (engineering, engineering_preview.json()["command"]),
    ]


def assert_consumers_rejected(target, commands):
    from pdos_next.models import Confirmation
    from pdos_next.service import digest
    from tests.test_project_first_plan import post as product_post

    for proposed, confirmed in commands:
        for request_body, preview in ((proposed, True), (confirmed, False)):
            rejected = product_post(target, deepcopy(request_body), preview=preview)
            assert rejected.status_code in {403, 409}, rejected.text
            assert rejected.json()["code"] in {
                "SOURCE_UNAVAILABLE",
                "SOURCE_STALE",
                "FORBIDDEN_SCOPE",
            }
        with Session(target.admin) as session:
            confirmation = session.scalar(
                select(Confirmation).where(
                    Confirmation.tenant_id == target.tenant,
                    Confirmation.token_hash == digest(confirmed["payload"]["confirmation_token"]),
                )
            )
            assert confirmation is not None and confirmation.consumed is False


def test_pg_signed_g0_source_supports_actual_first_plan_and_engineering_configuration(work):
    from pdos_next.domain.configurations.models import EngineeringConfiguration
    from pdos_next.domain.projects.models import PlanRevision, Project
    from tests.test_project_first_plan import post as product_post

    args = product_source_g0(work, project_owner=work.human)
    target, commands = consumer_commands(work, args)
    receipts = []
    for _, confirmed in commands:
        saved = product_post(target, confirmed)
        assert saved.status_code == 200, saved.text
        receipts.append(saved.json())
    with scoped(target) as session:
        project = session.get(Project, UUID(args["project_id"]))
        plan = session.get(PlanRevision, UUID(receipts[0]["subject_id"]))
        configuration = session.get(EngineeringConfiguration, UUID(receipts[1]["subject_id"]))
        assert plan is not None and plan.id == project.current_plan_id
        assert configuration is not None and configuration.definition_id == args["d"]
        assert {
            "artifact_id": str(args["a"]),
            "expected_revision": 1,
        } in configuration.required_source_read_set


@pytest.mark.parametrize("missing_proof", ["unmatched_source", "no_target_g0", "wrong_version"])
def test_pg_actual_http_rejects_foreign_reads_without_exact_target_g0_proof(work, missing_proof):
    from tests.test_configurations import bom_payload, command
    from tests.test_project_first_plan import post as product_post

    args = product_source_g0(work, project_owner=work.human)
    target = copy(work)
    target.product = args["p"]
    source_id, version = args["a"], 1
    if missing_proof == "unmatched_source":
        source_id = unmatched_product_artifact(work, args)
    elif missing_proof == "no_target_g0":
        source_id = product_artifact(target)
        target.product = work.product
    else:
        version = 2
    from pdos_next.domain.products.models import DefinitionRevision
    from pdos_next.models import Artifact

    with scoped(work) as session:
        actual = session.get(Artifact, source_id)
        assert actual is not None and actual.product_id != target.product
        assert actual.product_id == (args["p"] if missing_proof == "no_target_g0" else work.product)
        if missing_proof == "no_target_g0":
            assert target.product == work.product
            assert (
                session.scalar(
                    select(DefinitionRevision.id).where(
                        DefinitionRevision.tenant_id == work.tenant,
                        DefinitionRevision.category_id == work.category,
                        DefinitionRevision.product_id == target.product,
                        DefinitionRevision.g0_decision_id.is_not(None),
                    )
                )
                is None
            )
        elif missing_proof == "wrong_version":
            assert actual.id == args["a"] and actual.revision == 1 != version
    reference = {
        "artifact_id": str(source_id),
        "expected_revision": version,
        "line": 1,
        "quote": QUOTE,
    }
    request_body = command(
        target,
        "engineering.bom.revise",
        bom_payload(reference),
        [
            {"artifact_id": str(source_id), "expected_revision": version},
        ],
    )
    for preview in (True, False):
        rejected = product_post(target, request_body, preview=preview)
        assert rejected.status_code in {403, 409}, rejected.text
        assert rejected.json()["code"] in {"SOURCE_UNAVAILABLE", "SOURCE_STALE", "FORBIDDEN_SCOPE"}


def test_pg_private_source_product_blocks_actual_consumers_and_prepared_confirmations(work):
    from pdos_next.models import Grant, Product

    # Give the actual named project owner write membership before the command
    # chain. The source Product still belongs to another real principal.
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == work.tenant,
                Grant.category_id == work.category,
                Grant.principal_id == work.peer,
            )
        )
        grant.can_write = True
    args = product_source_g0(work, project_owner=work.peer)
    target, commands = consumer_commands(work, args, actor=work.peer)
    with Session(work.admin) as session, session.begin():
        source_product = session.get(Product, work.product)
        assert source_product.owner_id == work.human != work.peer
        source_product.visibility = "private"
    assert_consumers_rejected(target, commands)


def test_pg_withdrawn_actual_product_original_blocks_new_consumer_and_old_confirmation(
    work, security_work
):
    from security_fixture import secured_parse
    from test_durable_evidence import upload_input

    from pdos_next.models import Artifact, OriginalSecurity

    uploaded = security_work.client.post(
        f"/v1/categories/{work.category}/products/{work.product}/originals",
        headers=work.headers,
        json=upload_input((QUOTE + "\n").encode(), visibility="category").model_dump(mode="json"),
    )
    assert uploaded.status_code == 200, uploaded.text
    original_id = UUID(uploaded.json()["subject_id"])
    result = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": str(work.product),
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": str(original_id),
        },
        security_work.store,
    )
    assert result["status"] == "parsed", result
    with scoped(work) as session:
        source_id = session.scalar(select(Artifact.id).where(Artifact.original_id == original_id))
        state = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original_id)
        )
        epoch = state.epoch
    assert source_id is not None
    args = product_source_g0(work, source_id=source_id, project_owner=work.human)
    target, commands = consumer_commands(work, args)
    save(
        work,
        cmd(
            work,
            "evidence.original.withdraw",
            {
                "original_id": str(original_id),
                "expected_epoch": epoch,
                "reason": "Synthetic fixed source withdrawn before new consumption",
            },
        ),
    )
    assert_consumers_rejected(target, commands)


def test_downstream_source_bridge_preserves_all_existing_audience_checks_and_exact_down():
    from migrations import schema_s0_0752 as bridge

    old = bridge.PREDECESSOR_DIRECT_SOURCE_SET_VISIBLE
    new = bridge.DIRECT_SOURCE_SET_VISIBLE
    prefix, suffix = old.split("AND a.category_id=c AND (a.product_id IS NULL OR a.product_id=p)")
    assert new.startswith(prefix) and new.endswith(suffix)
    assert hashlib.sha256(old.encode()).hexdigest() == (
        "a9bcb2eba49cbb136590259499a29be82b1aaa1df0b46f109d849b942d4e630e"
    )
    assert bridge.SCHEMA_SQL == (new,)
    assert bridge.DOWNGRADE_SQL == (old,)
    for fragment in (
        "source.tenant_id=t AND source.category_id=c AND source.product_id=p",
        "source.artifact_id=a.id AND definition.sealed IS TRUE",
        "definition.g0_decision_id IS NOT NULL",
        "to_jsonb(source.source_revision)=r->'expected_revision'",
        "public.m3_g0_product_source_proven(t,c,p,definition.id,a.id,",
        "source.source_revision,source.line,source.quote,false) IS TRUE",
    ):
        assert fragment in new
    # Historical visibility must not become an active-source eligibility check.
    assert "a.status" not in new and "a.revision" not in new
    assert "GRANT" not in "\n".join(bridge.SCHEMA_SQL)


def bridge_visible(session, args, *, references=None):
    import json

    return session.scalar(
        text("SELECT direct_source_set_visible(:t,:c,:p,CAST(:refs AS jsonb))"),
        {
            **args,
            "refs": json.dumps(
                references
                if references is not None
                else [{"artifact_id": str(args["a"]), "expected_revision": args["v"]}]
            ),
        },
    )


def test_pg_downstream_bridge_uses_actual_sealed_source_and_exact_signed_revision(work):
    args = product_source_g0(work)
    unrelated = unmatched_product_artifact(work, args)
    with scoped(work) as session:
        assert bridge_visible(session, args) is True
        assert bridge_visible(session, args, references=[{"artifact_id": str(args["a"])}]) is True
        assert bridge_visible(session, {**args, "v": 2}) is False
        assert bridge_visible(session, {**args, "a": unrelated}) is False
        assert bridge_visible(session, {**args, "p": uuid4()}) is False
        assert bridge_visible(session, {**args, "t": uuid4()}) is False
        assert bridge_visible(session, {**args, "c": uuid4()}) is False
        # Ordinary native reads retain the predecessor behavior.
        assert bridge_visible(session, {**args, "p": work.product, "a": unrelated}) is True


def test_pg_downstream_bridge_retains_current_source_product_audience(work):
    args = product_source_g0(work)
    from pdos_next.models import Product

    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        requester_id=work.peer,
        category_id=work.category,
    ) as session:
        assert bridge_visible(session, args) is True
    with Session(work.admin) as session, session.begin():
        source_product = session.get(Product, work.product)
        assert source_product.owner_id != work.peer
        source_product.visibility = "private"
    with tenant_session(
        work.engine,
        work.tenant,
        actor_id=work.peer,
        requester_id=work.peer,
        category_id=work.category,
    ) as session:
        assert bridge_visible(session, args) is False
