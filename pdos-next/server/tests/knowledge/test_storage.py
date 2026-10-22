"""Offline knowledge declarations; real transactions remain a host checkpoint."""

import re

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, text
from sqlalchemy.engine import Engine

from pdos_next import models as registered_models  # noqa: F401 -- parent registry
from pdos_next.domain.knowledge import storage_schema as storage
from pdos_next.domain.knowledge.models import (
    ASSESSMENT,
    CANDIDATE,
    CANDIDATE_CURRENT,
    RULE,
    RULE_CURRENT,
    DesignRuleVersion,
    KnowledgeCandidateVersion,
)


@pytest.fixture(autouse=True)
def no_connection(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Knowledge declaration tests must never connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


def checks(table):
    return " ".join(
        str(value.sqltext) for value in table.constraints if isinstance(value, CheckConstraint)
    )


def uniques(table):
    return {
        tuple(value.columns.keys())
        for value in table.constraints
        if isinstance(value, UniqueConstraint)
    }


def test_actual_metadata_compiles_and_every_reference_has_a_unique_target():
    assert {table.name for table in storage.TABLES} == {
        CANDIDATE,
        CANDIDATE_CURRENT,
        ASSESSMENT,
        RULE,
        RULE_CURRENT,
    }
    for table in storage.TABLES:
        for reference in table.foreign_key_constraints:
            remote = reference.referred_table
            assert tuple(value.column.name for value in reference.elements) in {
                tuple(remote.primary_key.columns.keys()),
                *uniques(remote),
            }
    statements = storage.table_sql()
    assert sum(value.lstrip().startswith("CREATE TABLE") for value in statements) == 5
    assert sum(value.lstrip().startswith("ALTER TABLE") for value in statements) == 2
    assert "ADD CONSTRAINT knowledge_rule_assessment_fk" in statements[-1]


def test_category_candidate_does_not_require_a_fabricated_product_or_project():
    table = KnowledgeCandidateVersion.__table__
    assert table.c.product_id.nullable and table.c.project_id.nullable
    assert not table.c.category_id.nullable
    assert "project_id IS NULL OR product_id IS NOT NULL" in checks(table)
    assert KnowledgeCandidateVersion().status == "draft"
    assert "product_id IS NOT NULL AND project_id IS NOT NULL" not in checks(table)
    assert "operation='knowledge.candidate.create' AND confirmation_id IS NULL" in checks(table)


def test_publication_and_assessment_require_actual_scope_and_named_t2():
    rule = DesignRuleVersion.__table__
    assert "product_id IS NOT NULL AND project_id IS NOT NULL" in checks(rule)
    assert "operation='knowledge.rule.publish' AND confirmation_id IS NOT NULL" in checks(rule)
    assert "writer_id=actor_id AND actor_id=requester_id" in checks(rule)
    assert "nature IN ('real','synthetic')" in checks(rule)
    assert "valid_until IS NULL OR valid_from<valid_until" in checks(rule)
    assert DesignRuleVersion().status == "published"
    for table in storage.TABLES:
        assert "visibility IN ('private','category')" in checks(table)
        assert "audience" not in checks(table)
    for name in (ASSESSMENT, RULE_CURRENT):
        assert "product_id IS NOT NULL AND project_id IS NOT NULL" in checks(
            registered_models.Base.metadata.tables[name]
        )


def test_assessment_has_no_independent_operation_or_confirmation_and_is_reciprocal():
    table = registered_models.Base.metadata.tables[ASSESSMENT]
    assert not {"command_id", "operation", "confirmation_id", "qualified", "approved"} & set(
        table.c.keys()
    )
    assert ("tenant_id", "publication_id") in uniques(table)
    cycles = storage.cycle_constraints()
    assert {value.name for value in cycles} == {
        "knowledge_assessment_publication_fk",
        "knowledge_rule_assessment_fk",
    }
    assert all(value.deferrable and value.initially == "DEFERRED" for value in cycles)
    assert "publication.assessment_id<>assessment.id" in storage.ASSESSMENT_ATOM
    assert (
        "assessment.body IS DISTINCT FROM publication.body->'applicability'"
        in storage.ASSESSMENT_ATOM
    )
    assert "ax IS DISTINCT FROM vx" in storage.ASSESSMENT_ATOM


def test_current_cas_preserves_nullable_scope_and_requires_the_new_version_transaction():
    for table, (version, identity) in storage.CURRENT_FACTS.items():
        guard = storage.current_guard(table, version)
        atom = storage.current_atom(table, version, identity)
        assert "NEW.revision=OLD.revision+1" in guard
        assert "v.previous_id=OLD.version_id" in guard
        assert "v.previous_revision=OLD.revision" in guard
        assert "to_jsonb(NEW)-ARRAY['version_id','revision']" in guard
        assert "vx IS DISTINCT FROM cx" in atom
        assert "cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility" in atom
        assert "IS DISTINCT FROM ROW(fixed.category_id,fixed.product_id,fixed.project_id" in atom


def test_candidate_uses_whole_declared_body_and_exact_previous_scope():
    atom = storage.CANDIDATE_ATOM
    assert "public.assert_knowledge_common(t,target,'knowledge_candidate')" in atom
    assert "'applicability_hypothesis',payload->'applicability_hypothesis'" in atom
    assert "'result_receipts',payload->'result_receipts'" in atom
    assert "payload->>'visibility' IS DISTINCT FROM v.visibility" in atom
    assert "v.body IS DISTINCT FROM expected" in atom
    assert "v.command->'review'->'before' IS DISTINCT FROM prior.body" in atom
    assert "IS DISTINCT FROM ROW(prior.category_id,prior.product_id,prior.project_id" in atom
    assert "v.owner_id<>v.requester_id" in atom
    assert "IS NOT DISTINCT FROM" not in atom  # A mismatch rejects, including NULL scope movement.


def test_read_policies_use_real_content_and_result_acl_owners_not_private_authority_reads():
    sql = "\n".join(storage.policy_sql())
    assert sql.count("FORCE ROW LEVEL SECURITY") == 5
    assert storage.CONTENT_ACL in sql and storage.RESULT_ACL in sql
    assert "product_id,reads)" not in sql
    assert "FROM public.artifact_versions" not in sql
    assert "source_basis->'professional'" not in sql
    assert "fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility" in sql
    assert "IS NOT DISTINCT FROM ROW(" in sql
    assert "publication.candidate_version_id=" in sql
    assert "GRANT UPDATE(version_id,revision)" in sql
    assert "TO pdos_agent" not in sql and "FOR DELETE" not in sql
    with pytest.raises(ValueError, match="Actual candidate result"):
        storage.policy_sql(candidate_result_acl="")


def test_retained_content_uses_actual_source_product_and_is_never_shared_from_a_private_parent():
    sql = storage.COMMON_ATOM
    assert "a.product_id::text IS NOT DISTINCT FROM basis->>'product_id'" in sql
    assert "a.product_id IS NULL OR a.product_id=v.product_id" not in sql
    assert (
        "public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)"
        in sql
    )
    assert "source_product.visibility='category'" in sql
    assert "v.visibility='private' OR o.visibility='category'" in sql
    assert "v.visibility='private' OR a.visibility<>'private'" not in sql
    for retained in (
        "a.content_hash=basis->>'hash'",
        "sec.epoch::text=basis->'original'->>'epoch'",
        "a.status='active'",
        "r.operation='evidence.artifact.register'",
        "Work source metadata security or audience changed",
    ):
        assert retained in sql


def test_publication_keeps_actual_candidate_version_and_current_only_at_the_new_write():
    atom = storage.RULE_ATOM
    assert "candidate_current.version_id<>candidate.id" in atom
    assert "candidate_current.revision<>candidate.revision" in atom
    assert "'body_sha256',candidate.body_sha256" in atom
    assert "candidate.visibility='private' AND (v.visibility<>'private'" in atom
    assert "v.source_basis->'candidate' IS DISTINCT FROM" in atom
    assert "assessment.body->>'decision' IS DISTINCT FROM 'applicable'" in atom
    assert "'assessor_id',v.actor_id,'withdrawal_reason',NULL" in atom
    assert "assessment.body IS DISTINCT FROM expected_assessment" in atom
    assert "vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM ax" in atom
    assert "v.command->'review'->'before' IS DISTINCT FROM prior.body" in atom
    rule_read = next(
        value for value in storage.policy_sql() if f'ON public."{RULE}" FOR SELECT' in value
    )
    assert "candidate_current" not in rule_read


def test_target_is_fixed_real_configuration_with_ordinary_audience_and_single_product():
    atom = storage.RULE_ATOM
    for table in ("engineering_configurations", "process_revisions"):
        assert f"FROM public.{table} target" in atom
        assert f"audience.object_type='{table}'" in atom
    assert atom.count("target.product_id=v.product_id") == 2
    assert atom.count("target.owner_id=public.scope_requester()") == 2
    assert atom.count("v.visibility='private' OR target.visibility='category'") == 2
    assert "target.revision::text=applicability->'target'->>'revision'" in atom


def test_authority_is_real_current_named_knowledge_duty_and_qualification_not_booleans():
    atom = storage.PROFESSIONAL_ATOM
    assert "authority->'roles' IS DISTINCT FROM '[\"knowledge\"]'::jsonb" in atom
    assert "FROM public.professional_authority_facts" in atom
    assert "FROM public.professional_authority_current" in atom
    assert "f.subject_id=v.actor_id" in atom
    assert (
        "pointer.fact_revision" not in atom
    )  # Actual join compares p.fact_revision with immutable Fact.
    assert "p.fact_id=fact.id AND p.fact_revision=fact.revision" in atom
    assert "fact.fact_sha256 IS DISTINCT FROM reference->>'fact_sha256'" in atom
    assert "fact.role='knowledge' AND fact.state='active'" in atom
    assert "fact.operations @> jsonb_build_array(v.operation)" in atom
    assert "has_duty=true" in atom and "has_qualification=true" in atom
    assert "IF NOT has_duty OR NOT has_qualification" in atom
    assert "NOT coalesce(v.reads @> fact.required_source_read_set,false)" in atom


def test_common_original_group_binds_category_only_commands_and_named_t2_without_new_ttl():
    members, common = storage.MEMBERS_ATOM, storage.COMMON_ATOM
    for retained in (
        "receipt.result IS DISTINCT FROM expected",
        "coalesce(receipt.agent_run_id,receipt.run_id,v.command_id)",
        "proof.snapshot IS DISTINCT FROM v.command->'review'",
        "proof.consumed IS DISTINCT FROM true",
        "proof.expires_at IS NOT NULL",
        "receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL",
    ):
        assert retained in members
    assert "v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories" in common
    assert "v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products" in common
    assert "envelope->>'product_id' IS DISTINCT FROM v.product_id::text" in common
    assert "v.body IS DISTINCT FROM v.command->'review'->'after'" in common
    assert "Knowledge T2 proof consumption must share its new rule transaction" in common
    assert "x.xmin=vx" in common
    assert "interval '" not in members + common


def test_owned_history_guards_preserve_all_proofs_and_dispatch_metadata_exception():
    assert "Knowledge receipt history is immutable" in storage.RECEIPT_GUARD
    assert "Knowledge original audit event or request key is immutable" in storage.MEMBER_GUARD
    assert "'delivered_at','lease_id','lease_until','attempts','last_error'" in storage.MEMBER_GUARD
    assert (
        "(to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed')"
        in storage.CONFIRMATION_GUARD
    )
    assert "exactly one new publication" in storage.CONFIRMATION_TARGET
    assert (
        "v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1" in storage.CONFIRMATION_TARGET
    )
    assert "public.assert_work_management" not in "\n".join(storage.function_sql())


def test_sql_references_columns_present_on_actual_models():
    for body, aliases in (
        (storage.CANDIDATE_ATOM, {"v": CANDIDATE, "prior": CANDIDATE, "cur": CANDIDATE_CURRENT}),
        (
            storage.RULE_ATOM,
            {
                "v": RULE,
                "prior": RULE,
                "cur": RULE_CURRENT,
                "candidate": CANDIDATE,
                "candidate_current": CANDIDATE_CURRENT,
                "assessment": ASSESSMENT,
            },
        ),
        (
            storage.PROFESSIONAL_ATOM,
            {
                "v": RULE,
                "fact": "professional_authority_facts",
                "pointer": "professional_authority_current",
            },
        ),
        (storage.ASSESSMENT_ATOM, {"assessment": ASSESSMENT, "publication": RULE}),
    ):
        for alias, table in aliases.items():
            assert set(re.findall(rf"\b{alias}\.([a-z_]+)\b", body)) <= {
                *registered_models.Base.metadata.tables[table].c.keys(),
                "xmin",
            }


def test_complete_sql_is_declarative_and_downgrade_refuses_any_retained_history():
    assert not hasattr(storage, "install") and not hasattr(storage, "execute")
    upgrade, downgrade = storage.upgrade_sql(), storage.downgrade_sql()
    assert len(storage.functions()) == len(set(storage.signatures()))
    assert len(storage.trigger_sql()) == 10
    assert len(storage.common_trigger_sql()) == 10
    assert downgrade[0].startswith("LOCK TABLE")
    down = "\n".join(downgrade)
    assert down.index("downgrade refused") < down.index("DROP TRIGGER")
    assert "knowledge.rule.publish" in down and "public.confirmations" in down
    assert down.index("DROP CONSTRAINT knowledge_rule_assessment_fk") < down.index("DROP TABLE")
    assert "DELETE FROM" not in down and "TRUNCATE" not in down
    for statement in (*upgrade, *downgrade):
        assert not text(statement)._bindparams
        assert not re.search(r"\b(?:COMMIT|CREATE\s+ROLE|SET\s+(?:LOCAL\s+)?ROLE)\b", statement)
    with pytest.raises(ValueError, match="Actual candidate, rule"):
        storage.function_sql(atom_bodies={})
