"""Frozen coverage plus root-run PG probes; pure cases never connect to a DB."""
# ruff: noqa: F811 -- explicit shared fixture export

import json
from uuid import UUID, uuid4

import pytest
from lifecycle_fixture import lifecycle_work  # noqa: F401
from security_fixture import secured_parse
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input

from migrations import schema_s0_0749 as migration
from pdos_next import models
from pdos_next.database import tenant_session
from pdos_next.lifecycle_access import NON_CONSUMING, schema_covered
from pdos_next.lifecycle_catalog import COVERED_COLUMNS, GUARDED, M3_GUARDED
from tests.preproject.test_g0 import create, payload


def test_frozen_catalog_matches_actual_columns_without_consuming_transport():
    assert set(COVERED_COLUMNS) == set(models.Base.metadata.tables)
    for name, table in models.Base.metadata.tables.items():
        assert set(COVERED_COLUMNS[name]) == set(table.columns.keys())
    assert set(M3_GUARDED) == set(migration.M3_TABLES)
    assert len(M3_GUARDED) == 16
    assert set(M3_GUARDED) <= set(GUARDED)
    assert not set(M3_GUARDED) & NON_CONSUMING
    assert {"proposal_prepared_candidates", "category_creation_confirmations"} <= NON_CONSUMING


class Catalog:
    def __init__(self, *, column=None, missing=None, wrong_function=False):
        self.columns = [(t, c) for t, columns in COVERED_COLUMNS.items() for c in columns]
        if column:
            self.columns.append(column)
        self.guards = set()
        for name in (*GUARDED, "upload_attempts"):
            if name == "inbox_deliveries":
                continue
            gate = (
                "kernel_source_reference_gate"
                if name == "agent_runs"
                else (
                    "m3_lifecycle_reference_gate"
                    if name in M3_GUARDED
                    else "lifecycle_reference_gate"
                )
            )
            clock = (
                "kernel_source_reference_clock"
                if name == "agent_runs"
                else (
                    "m3_lifecycle_reference_clock"
                    if name in M3_GUARDED
                    else "category_lifecycle_clock"
                )
            )
            self.guards |= {
                (name, "lifecycle_reference", gate),
                (name, "category_lifecycle_clock", clock),
            }
        self.guards |= {
            ("products", "lifecycle_epoch", "lifecycle_product_epoch"),
            ("uploaded_originals", "upload_registration", "protect_upload_registration"),
            ("object_audiences", "audience_reference_fence", "protect_object_audience_target"),
            *(
                (n, "retained_record", "protect_lifecycle_record")
                for n in ("upload_attempts", "lifecycle_objects", "lifecycle_intents")
            ),
            *(
                (n, "retained_record", "protect_next_snapshot")
                for n in ("lifecycle_candidates", "lifecycle_requests")
            ),
        }
        if missing:
            self.guards = {g for g in self.guards if g[:2] != missing}
        if wrong_function:
            self.guards.remove(("proposals", "lifecycle_reference", "m3_lifecycle_reference_gate"))
            self.guards.add(("proposals", "lifecycle_reference", "lifecycle_reference_gate"))

    def execute(self, statement):
        if "pg_attribute" in str(statement):
            return iter(self.columns)
        return self

    def all(self):
        return list(self.guards)


@pytest.mark.parametrize("table", M3_GUARDED)
@pytest.mark.parametrize("trigger", ["lifecycle_reference", "category_lifecycle_clock"])
def test_each_actual_m3_guard_is_required_for_coverage(table, trigger):
    assert schema_covered(Catalog())
    assert not schema_covered(Catalog(missing=(table, trigger)))


def test_unknown_columns_tables_and_wrong_guard_implementation_fail_closed():
    assert not schema_covered(Catalog(column=("proposals", "unreviewed_source")))
    assert not schema_covered(Catalog(column=("unreviewed_table", "id")))
    assert not schema_covered(Catalog(wrong_function=True))


def test_frozen_migration_has_source_free_fast_path_and_exact_predecessor_down():
    assert "IF cardinality(reached)=0 THEN RETURN '{}'" in migration.ROOTS
    assert "m3_lifecycle_nodes(t,c,frontier)" in migration.ROOTS
    assert "jsonb_agg" not in migration.ROOTS
    assert "public.upload_attempts" in migration.ROOTS
    assert migration.PREDECESSOR_SUMMARY in migration.DOWNGRADE_SQL
    assert len([s for s in migration.SCHEMA_SQL if s.startswith("CREATE TRIGGER")]) == 32
    assert all("__TABLES__" not in s and "__M3_TABLES__" not in s for s in migration.SCHEMA_SQL)


def scoped(setup, *, admin=False):
    return tenant_session(
        setup.admin if admin else setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    )


def test_pg_actual_coverage_and_private_helpers_have_no_runtime_execute(setup):
    with scoped(setup) as session:
        assert schema_covered(session)
    with Session(setup.admin) as session:
        for role in ("pdos_next_app", "pdos_next_auth", "pdos_next_dispatch", "pdos_agent"):
            count = session.scalar(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname LIKE 'm3_lifecycle_%' "
                    "AND has_function_privilege(:role,p.oid,'EXECUTE')"
                ),
                {"role": role},
            )
            assert count == 0


@pytest.mark.parametrize("kind", ["artifact", "original", "claim", "knowledge", "definition"])
def test_pg_typed_refs_keep_id_but_ignore_identity_and_free_text(setup, kind):
    reference, identity = uuid4(), uuid4()
    body = {
        "id": str(identity),
        "tenant_id": str(identity),
        "owner_id": str(identity),
        "confirmed_by": str(identity),
        "text": str(identity),
        "quote": str(identity),
        "content": {"source_id": str(identity), "nested": {"item_id": str(identity)}},
        "source_refs": [{"type": kind, "id": str(reference), "version": 1}],
    }
    with scoped(setup, admin=True) as session:
        actual = session.scalar(
            text("SELECT m3_lifecycle_typed_links(:t,:c,CAST(:body AS jsonb))"),
            {"t": setup.tenant, "c": setup.category, "body": json.dumps(body)},
        )
        assert actual == [reference]


@pytest.mark.parametrize("kind", ["section", "option", "risk"])
def test_pg_arbitrary_content_relation_keys_are_not_source_edges(setup, kind):
    from pdos_next.domain.preproject.schemas import ItemInput

    unrelated = str(uuid4())
    content = {
        "key": "summary",
        "text": "Synthetic extra fields",
        "name": "Synthetic option",
        "kind": "new",
        "source_id": unrelated,
        "item_id": unrelated,
        "extra": {"source_id": unrelated, "artifact_id": unrelated},
        # Even a Reference-looking object in an unregistered content field
        # does not become validated evidence for a section/option/risk.
        "source_ref": {"type": "artifact", "id": unrelated, "version": 1},
    }
    item = ItemInput(kind=kind, content=content).model_dump(mode="json")
    assert item["source_refs"] == []
    with scoped(setup, admin=True) as session:
        actual = session.scalar(
            text(
                "SELECT m3_lifecycle_row_links(:t,:c,'proposal_item_versions',CAST(:body AS jsonb))"
            ),
            {"t": setup.tenant, "c": setup.category, "body": json.dumps(item)},
        )
        assert actual == []
        frozen = session.scalar(
            text(
                "SELECT m3_lifecycle_row_links(:t,:c,'proposal_submissions',CAST(:body AS jsonb))"
            ),
            {
                "t": setup.tenant,
                "c": setup.category,
                "body": json.dumps({"frozen_document": {"items": [item]}}),
            },
        )
        assert frozen == []


@pytest.mark.parametrize("shape", ["commercial", "competitor", "voice", "frozen_link"])
def test_pg_registered_nested_reference_containers_are_retained(setup, shape):
    identity = uuid4()
    ref = {"type": "artifact", "id": str(identity), "version": 1}
    if shape == "commercial":
        table = "proposal_item_versions"
        body = {"kind": "commercial_target", "content": {"target_price": {"source": ref}}}
    elif shape == "competitor":
        table = "category_knowledge_entries"
        body = {"kind": "competitor", "content": {"metrics": [{"source_ref": ref}]}}
    elif shape == "voice":
        table = "category_knowledge_entries"
        body = {"kind": "voice", "content": {"representative_refs": [ref]}}
    else:
        table = "proposal_submissions"
        body = {
            "frozen_document": {
                "items": [{"kind": "section", "content": {}, "evidence_links": [{"evidence": ref}]}]
            }
        }
    with scoped(setup, admin=True) as session:
        actual = session.scalar(
            text("SELECT m3_lifecycle_row_links(:t,:c,:table,CAST(:body AS jsonb))"),
            {"t": setup.tenant, "c": setup.category, "table": table, "body": json.dumps(body)},
        )
        assert identity in actual


def uploaded(lifecycle_work, product_scope, *, visibility="private"):
    work, setup = lifecycle_work, lifecycle_work.setup
    path = f"/v1/categories/{setup.category}"
    if product_scope:
        path += f"/products/{setup.product}"
    result = work.client.post(
        path + "/originals",
        headers=setup.headers,
        json=upload_input(
            b"Synthetic exact M3 lifecycle source\n", visibility=visibility
        ).model_dump(mode="json"),
    )
    assert result.status_code == 200, result.text
    original_id = UUID(result.json()["subject_id"])
    parsed = secured_parse(
        setup.engine,
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "product_id": str(setup.product) if product_scope else None,
            "actor_id": str(setup.human),
            "requester_id": str(setup.human),
            "subject_id": str(original_id),
        },
        work.store,
    )
    assert parsed["status"] == "parsed", parsed
    with scoped(setup) as session:
        artifact = session.scalar(
            select(models.Artifact).where(models.Artifact.original_id == original_id)
        )
        assert artifact is not None
        return original_id, artifact.id


def product_artifact(setup, *, body="Synthetic exact public source"):
    """Register the native source through the actual product-scoped command."""
    from tests.test_project_first_plan import cmd, post

    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic product definition source",
                "source_label": "Synthetic lifecycle fixture",
                "content": body,
                "visibility": "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


class ProbeRollback(Exception):
    pass


@pytest.mark.parametrize("product_scope", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def test_pg_actual_original_roots_fence_and_advance_both_scopes(
    lifecycle_work,
    product_scope,
    pending,
):
    """Real parsed source and app UPDATE; synthetic pending row always rolls back.

    This isolates the DB reference guard before deferred domain validation; it
    neither commits fabricated retention decisions nor adopts a bypassed source.
    """
    setup = lifecycle_work.setup
    original_id, artifact_id = uploaded(lifecycle_work, product_scope)
    proposal_id, _ = create(setup)
    expected = DBAPIError if pending else ProbeRollback
    with pytest.raises(expected) as caught:
        with scoped(setup, admin=True) as session:
            session.add(
                models.LifecycleObject(
                    id=original_id,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product if product_scope else None,
                    owner_id=setup.human,
                    reference={},
                    state={
                        "value": {
                            "pending_intent_id": str(uuid4()) if pending else None,
                            "disposition": "active",
                        }
                    },
                )
            )
            session.flush()
            before_category = session.get(models.Category, setup.category).lifecycle_epoch
            before_product = session.get(models.Product, setup.product).lifecycle_epoch
            session.execute(text("SET LOCAL ROLE pdos_next_app"))
            refs = [
                {
                    "type": "artifact",
                    "id": str(artifact_id),
                    "version": 1,
                    "line": 1,
                    "quote": "Synthetic exact M3 lifecycle source",
                }
            ]
            session.execute(
                text(
                    "UPDATE proposals SET source_refs=CAST(:refs AS jsonb),revision=revision+1 "
                    "WHERE id=:id"
                ),
                {"refs": json.dumps(refs), "id": UUID(proposal_id)},
            )
            category_epoch = session.scalar(
                text("SELECT lifecycle_epoch FROM categories WHERE id=:id"), {"id": setup.category}
            )
            product_epoch = session.scalar(
                text("SELECT lifecycle_epoch FROM products WHERE id=:id"), {"id": setup.product}
            )
            assert category_epoch > before_category
            if product_scope:
                assert product_epoch > before_product
            summary = session.execute(
                text(
                    "SELECT reference_count,formal_history FROM lifecycle_reference_summary"
                    "(:t,:c,:p,CAST(:roots AS uuid[]))"
                ),
                {
                    "t": setup.tenant,
                    "c": setup.category,
                    "p": setup.product if product_scope else None,
                    "roots": [original_id],
                },
            ).one()
            assert summary.reference_count > 0 and summary.formal_history
            raise ProbeRollback
    if pending:
        assert caught.value.orig.sqlstate == "23514"
        assert caught.value.orig.diag.constraint_name == "m3_source_reference_fence"


def test_pg_public_m3_source_adoption_is_counted(lifecycle_work):
    setup = lifecycle_work.setup
    original_id, artifact_id = uploaded(lifecycle_work, False)
    data = payload(setup)
    data["groups"]["items"][0]["source_refs"] = [
        {
            "type": "artifact",
            "id": str(artifact_id),
            "version": 1,
            "line": 1,
            "quote": "Synthetic exact M3 lifecycle source",
        }
    ]
    proposal_id, _ = create(setup, data)
    with scoped(setup, admin=True) as session:
        roots = session.scalar(
            text(
                "SELECT m3_lifecycle_roots(:t,:c,'proposals',to_jsonb(p)) "
                "FROM proposals p WHERE p.id=:id"
            ),
            {"t": setup.tenant, "c": setup.category, "id": UUID(proposal_id)},
        )
        assert original_id in roots
        foreign = session.scalar(
            text("SELECT m3_lifecycle_roots(:t,:c,'proposals',CAST(:body AS jsonb))"),
            {
                "t": setup.tenant,
                "c": uuid4(),
                "body": json.dumps(
                    {"source_refs": [{"type": "artifact", "id": str(artifact_id), "version": 1}]}
                ),
            },
        )
        assert foreign == []


def test_pg_fixed_knowledge_claim_and_definition_edges_retain_actual_original(lifecycle_work):
    from tests.preproject.test_evidence_commands_pg import record_claim
    from tests.preproject.test_g0 import request, save
    from tests.preproject.test_material_commands_pg import knowledge
    from tests.test_project_first_plan import cmd, post

    setup = lifecycle_work.setup
    original_id, artifact_id = uploaded(lifecycle_work, False, visibility="category")
    quote = "Synthetic exact M3 lifecycle source"
    ref = {"type": "artifact", "id": str(artifact_id), "version": 1, "line": 1, "quote": quote}
    knowledge_receipt, _ = save(
        setup, request(setup, "category.knowledge.add", knowledge(source_refs=[ref]))
    )
    claim_receipt = record_claim(setup, artifact_id, quote=quote)
    definition_original_id, definition_artifact_id = uploaded(lifecycle_work, True)
    defined = post(
        setup,
        cmd(
            setup,
            "product.definition.draft",
            {
                "title": "Fixed M3 source closure",
                "purpose": "Synthetic closure test",
                "use_cases": ["Synthetic lifecycle source retention"],
                "change_reason": "Synthetic fixed definition",
                "sources": [
                    {
                        "artifact_id": str(definition_artifact_id),
                        "expected_revision": 1,
                        "line": 1,
                        "quote": quote,
                    }
                ],
            },
            str(definition_artifact_id),
        ),
    )
    assert defined.status_code == 200, defined.text
    for kind, identity, expected_root in (
        ("knowledge", knowledge_receipt["result"]["entry_id"], original_id),
        ("claim", claim_receipt["subject_id"], original_id),
        ("definition", defined.json()["subject_id"], definition_original_id),
    ):
        with scoped(setup, admin=True) as session:
            roots = session.scalar(
                text(
                    "SELECT m3_lifecycle_roots(:t,:c,'proposal_item_versions',CAST(:body AS jsonb))"
                ),
                {
                    "t": setup.tenant,
                    "c": setup.category,
                    "body": json.dumps(
                        {
                            "source_refs": [{"type": kind, "id": identity, "version": 1}],
                        }
                    ),
                },
            )
            assert expected_root in roots, kind


def test_pg_parameter_reference_resolves_fixed_version_not_current_head(setup):
    from pdos_next.domain.preproject.category_models import ParameterVersion
    from tests.preproject.test_g0 import request, save
    from tests.preproject.test_material_commands_pg import parameter

    first, _ = save(setup, request(setup, "category.parameter.publish", parameter()))
    identity = first["result"]["parameter_id"]
    save(
        setup,
        request(
            setup,
            "category.parameter.publish",
            parameter(
                parameter_id=identity,
                expected_current_version=1,
                unit="dB(A)",
                change_note="Synthetic next fixed version",
            ),
        ),
    )
    with scoped(setup, admin=True) as session:
        expected = session.scalar(
            select(ParameterVersion.id).where(
                ParameterVersion.parameter_id == UUID(identity),
                ParameterVersion.version == 1,
            )
        )
        actual = session.scalar(
            text("SELECT m3_lifecycle_typed_links(:t,:c,CAST(:body AS jsonb))"),
            {
                "t": setup.tenant,
                "c": setup.category,
                "body": json.dumps({"type": "parameter", "id": identity, "version": 1}),
            },
        )
        assert actual == [expected]


def test_pg_source_free_item_never_invokes_history_node_queries(setup):
    """A rollback-only function probe fails if the indexed closure is entered."""
    body = {
        "id": str(uuid4()),
        "proposal_id": str(uuid4()),
        "item_id": str(uuid4()),
        "version": 1,
        "kind": "section",
        "content": {"key": "summary", "text": "No source"},
        "source_refs": [],
    }
    with Session(setup.admin) as session:
        try:
            session.execute(
                text("""
                CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(
                    t uuid,c uuid,identities uuid[] DEFAULT NULL
                )
                RETURNS TABLE(table_name text,node_id uuid,links uuid[]) LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'Unexpected M3 history node query'; END; $$
            """)
            )
            statement = text(
                "SELECT m3_lifecycle_roots(:t,:c,'proposal_item_versions',CAST(:body AS jsonb))"
            )
            arguments = {"t": setup.tenant, "c": setup.category, "body": json.dumps(body)}
            assert session.scalar(statement, arguments) == []
            body["source_refs"] = [{"type": "artifact", "id": str(uuid4()), "version": 1}]
            with (
                pytest.raises(DBAPIError, match="Unexpected M3 history node query"),
                session.begin_nested(),
            ):
                session.scalar(statement, {**arguments, "body": json.dumps(body)})
        finally:
            session.rollback()


@pytest.mark.parametrize("target_kind", ["knowledge_entry", "definition_spec"])
def test_pg_evidence_link_target_closure_retains_original_after_withdrawal(
    lifecycle_work, target_kind
):
    from pdos_next.domain.products.models import DefinitionSpecRow
    from tests.preproject.test_evidence_commands_pg import record_claim, withdraw_request
    from tests.preproject.test_g0 import post, request, save
    from tests.preproject.test_material_commands_pg import knowledge
    from tests.test_project_first_plan import cmd

    setup = lifecycle_work.setup
    original_id, source_id = uploaded(lifecycle_work, False, visibility="category")
    claim = record_claim(setup, source_id, quote="Synthetic exact M3 lifecycle source")
    if target_kind == "knowledge_entry":
        receipt, _ = save(setup, request(setup, "category.knowledge.add", knowledge()))
        target_id = receipt["result"]["entry_id"]
        query_table, query_id = "category_knowledge_entries", target_id
        command = request(setup, "evidence.link.create", {})
    else:
        # Native spec source is a standalone Artifact with no UploadedOriginal.
        # Only the EvidenceLink→Claim path can reach the separate uploaded root.
        native = product_artifact(setup)
        native_ref = {
            "artifact_id": str(native),
            "expected_revision": 1,
            "line": 1,
            "quote": "Synthetic exact public source",
        }
        defined = post(
            setup,
            cmd(
                setup,
                "product.definition.draft",
                {
                    "title": "EvidenceLink-only original root",
                    "purpose": "Synthetic fixed closure",
                    "use_cases": ["Synthetic lifecycle source retention"],
                    "change_reason": "Synthetic definition",
                    "sources": [native_ref],
                    "specs": [
                        {
                            "key": "unknown",
                            "parameter": "Unknown",
                            "value_type": "text",
                            "availability": "unknown",
                            "reason": "Synthetic uncertainty",
                            "sources": [native_ref],
                        }
                    ],
                },
                str(native),
            ),
        )
        assert defined.status_code == 200, defined.text
        query_table, query_id = "definition_revisions", defined.json()["subject_id"]
        with scoped(setup) as session:
            target_id = str(
                session.scalar(
                    select(DefinitionSpecRow.id).where(
                        DefinitionSpecRow.definition_id == UUID(query_id)
                    )
                )
            )
        command = cmd(setup, "evidence.link.create", {})

    def roots():
        with scoped(setup, admin=True) as session:
            return session.scalar(
                text(
                    f"SELECT m3_lifecycle_roots(:t,:c,:table,to_jsonb(x)) FROM {query_table} x "
                    "WHERE x.id=:id"
                ),
                {
                    "t": setup.tenant,
                    "c": setup.category,
                    "table": query_table,
                    "id": UUID(query_id),
                },
            )

    assert original_id not in roots()
    command["payload"] = {
        "evidence": {"type": "claim", "id": claim["subject_id"], "version": 1},
        "target": {"type": target_kind, "id": target_id, "version": 1},
        "relation": "supports",
    }
    linked = post(setup, command)
    assert linked.status_code == 200, linked.text
    assert original_id in roots()
    save(setup, withdraw_request(setup, claim["subject_id"]))
    assert original_id in roots()
