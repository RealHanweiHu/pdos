"""Freeze M3 material SQL after a read-only, identity-checked s0_0729 catalog read.

This authoring tool may import ORM definitions. Active migrations never import it.
"""

import argparse
from pathlib import Path

import local_environment as local
from alembic.config import Config
from alembic.script import ScriptDirectory
from pdos_next.database import engine_for
from pdos_next.domain.preproject.category_models import (
    MATERIAL_TABLES,
    KnowledgeCurrent,
    KnowledgeEntry,
)
from pdos_next.domain.preproject.models import PreparedCandidate
from pdos_next.domain.products.models import DefinitionSpecRow as DefinitionSpec
from pdos_next.models import Category
from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

GUARDS = r"""
CREATE FUNCTION m3_material_category_key() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF NEW.key IS DISTINCT FROM OLD.key THEN
  RAISE EXCEPTION 'category key is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER m3_material_category_key BEFORE UPDATE ON categories
 FOR EACH ROW EXECUTE FUNCTION m3_material_category_key();

CREATE FUNCTION m3_material_current_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'material current cannot be deleted' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='parameter_current' THEN
  IF TG_OP='UPDATE' AND ROW(NEW.tenant_id,NEW.category_id,NEW.parameter_id,NEW.key)
   IS DISTINCT FROM ROW(OLD.tenant_id,OLD.category_id,OLD.parameter_id,OLD.key) THEN
   RAISE EXCEPTION 'parameter identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM parameter_versions v WHERE v.tenant_id=NEW.tenant_id
   AND v.category_id=NEW.category_id AND v.parameter_id=NEW.parameter_id
   AND v.version=NEW.current_version AND v.key=NEW.key) THEN
   RAISE EXCEPTION 'parameter current must match its version' USING ERRCODE='23514';
  END IF;
 ELSE
  IF TG_OP='UPDATE' AND ROW(NEW.tenant_id,NEW.category_id,NEW.lineage_id,NEW.kind)
   IS DISTINCT FROM ROW(OLD.tenant_id,OLD.category_id,OLD.lineage_id,OLD.kind) THEN
   RAISE EXCEPTION 'knowledge identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM category_knowledge_entries v WHERE v.tenant_id=NEW.tenant_id
   AND v.category_id=NEW.category_id AND v.id=NEW.current_entry_id
   AND v.lineage_id=NEW.lineage_id AND v.version=NEW.current_version AND v.kind=NEW.kind
   AND v.origin=NEW.origin
   AND NEW.status=CASE WHEN v.action='withdraw' THEN 'withdrawn' ELSE 'active' END) THEN
   RAISE EXCEPTION 'knowledge current must match its entry' USING ERRCODE='23514';
  END IF;
 END IF;
 IF TG_OP='UPDATE' AND NEW.current_version<>OLD.current_version+1 THEN
  RAISE EXCEPTION 'material current advances one version' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' AND NEW.current_version<>1 THEN
  RAISE EXCEPTION 'material lineage starts at version one' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION m3_material_atom() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r action_receipts; ar agent_runs; pc proposal_prepared_candidates;
 prior category_knowledge_entries;
 expected_type text; identity uuid; latest integer;
BEGIN
 SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF r.category_id IS DISTINCT FROM NEW.category_id OR r.product_id IS NOT NULL
  OR r.actor_id IS DISTINCT FROM scope_actor() OR r.requester_id IS DISTINCT FROM scope_requester()
  OR r.run_id IS NOT NULL THEN
  RAISE EXCEPTION 'material receipt scope mismatch' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='promotion_proofs' THEN
  IF r.operation<>'category.knowledge.promote' OR r.actor_id<>NEW.deidentified_by
   OR r.actor_id<>r.requester_id OR NOT EXISTS(SELECT 1 FROM principals p
    WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.deidentified_by AND p.kind='human')
   OR NOT EXISTS(SELECT 1 FROM category_knowledge_entries k WHERE k.tenant_id=NEW.tenant_id
    AND k.category_id=NEW.category_id AND k.id=NEW.knowledge_entry_id AND k.receipt_id=r.id
    AND r.subject_type='category_knowledge' AND r.subject_id=k.lineage_id
    AND r.subject_revision=k.version)
   OR NOT EXISTS(SELECT 1 FROM proposal_revisions pv WHERE pv.tenant_id=NEW.tenant_id
    AND pv.category_id=NEW.category_id AND pv.proposal_id=NEW.source_proposal_id
    AND pv.revision=NEW.source_proposal_revision)
   OR NOT coalesce((NEW.checks->>'refs_clean')::boolean,false)
   OR NOT coalesce((NEW.checks->>'filenames_clean')::boolean,false)
   OR NOT coalesce((NEW.checks->>'identities_clean')::boolean,false) THEN
   RAISE EXCEPTION 'promotion proof does not bind the named receipt' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
 END IF;
 IF TG_TABLE_NAME='parameter_versions' THEN
  expected_type='parameter'; identity=NEW.parameter_id;
  IF r.operation NOT IN ('category.parameter.publish','category.create') THEN
   RAISE EXCEPTION 'parameter receipt operation mismatch' USING ERRCODE='23514';
  END IF;
  SELECT max(version) INTO latest FROM parameter_versions WHERE tenant_id=NEW.tenant_id
   AND parameter_id=NEW.parameter_id;
  IF NOT EXISTS(SELECT 1 FROM parameter_current c WHERE c.tenant_id=NEW.tenant_id
   AND c.category_id=NEW.category_id AND c.parameter_id=NEW.parameter_id
   AND c.key=NEW.key AND c.current_version=latest)
   OR (NEW.version=1 AND NEW.replaces_version IS NOT NULL)
   OR (NEW.version>1 AND (NEW.replaces_version IS DISTINCT FROM NEW.version-1
    OR NOT EXISTS(SELECT 1 FROM parameter_versions v WHERE v.tenant_id=NEW.tenant_id
     AND v.category_id=NEW.category_id AND v.parameter_id=NEW.parameter_id
     AND v.version=NEW.version-1 AND v.key=NEW.key))) THEN
   RAISE EXCEPTION 'parameter version and current must commit together' USING ERRCODE='23514';
  END IF;
 ELSE
  expected_type='category_knowledge'; identity=NEW.lineage_id;
  IF r.operation NOT IN ('category.knowledge.add','category.knowledge.withdraw',
   'category.knowledge.promote','category.create')
   OR (NEW.action='withdraw') IS DISTINCT FROM (r.operation='category.knowledge.withdraw') THEN
   RAISE EXCEPTION 'knowledge receipt operation mismatch' USING ERRCODE='23514';
  END IF;
  SELECT max(version) INTO latest FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id
   AND lineage_id=NEW.lineage_id;
  IF NOT EXISTS(SELECT 1 FROM category_knowledge_current c WHERE c.tenant_id=NEW.tenant_id
   AND c.category_id=NEW.category_id AND c.lineage_id=NEW.lineage_id AND c.current_version=latest)
   OR (NEW.version=1 AND NEW.action<>'add') THEN
   RAISE EXCEPTION 'knowledge entry and current must commit together' USING ERRCODE='23514';
  END IF;
  IF NEW.version>1 THEN
   SELECT * INTO STRICT prior FROM category_knowledge_entries WHERE tenant_id=NEW.tenant_id
    AND category_id=NEW.category_id AND lineage_id=NEW.lineage_id AND version=NEW.version-1;
   IF NEW.kind<>prior.kind OR NEW.action='add' THEN
    RAISE EXCEPTION 'knowledge lineage mismatch' USING ERRCODE='23514';
   END IF;
  END IF;
  IF r.operation='category.knowledge.promote' AND NOT EXISTS(SELECT 1 FROM promotion_proofs p
   WHERE p.tenant_id=NEW.tenant_id AND p.knowledge_entry_id=NEW.id AND p.receipt_id=r.id) THEN
   RAISE EXCEPTION 'promotion requires its private proof' USING ERRCODE='23514';
  END IF;
 END IF;
 IF NOT ((r.subject_type=expected_type AND r.subject_id=identity AND r.subject_revision=NEW.version)
  OR (r.operation='category.create' AND r.subject_type='category'
   AND r.subject_id=NEW.category_id AND NEW.version=1)) THEN
  RAISE EXCEPTION 'material receipt subject mismatch' USING ERRCODE='23514';
 END IF;
 IF NEW.origin='human' OR (NEW.origin='imported' AND r.operation='category.create') THEN
  IF NEW.writer_id<>r.actor_id OR r.actor_id<>r.requester_id
   OR NEW.run_id IS NOT NULL OR NEW.confirmed_by IS NOT NULL
   OR NEW.prepared_candidate_id IS NOT NULL OR r.agent_run_id IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id
    AND p.id=NEW.writer_id AND p.kind='human') THEN
   RAISE EXCEPTION 'material human provenance mismatch' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.origin='ai_draft' THEN
  SELECT * INTO STRICT ar FROM agent_runs WHERE tenant_id=NEW.tenant_id AND id=NEW.run_id;
  IF ar.category_id IS DISTINCT FROM NEW.category_id OR ar.writer_id<>NEW.writer_id
   OR ar.requester_id<>r.requester_id OR ar.reverted_at IS NOT NULL OR ar.state='cancelled'
   OR r.agent_run_id IS DISTINCT FROM ar.id OR ar.product_id IS NOT NULL
   OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id
    AND p.id=NEW.writer_id AND p.kind='agent') THEN
   RAISE EXCEPTION 'material AI provenance mismatch' USING ERRCODE='23514';
  END IF;
  IF r.operation='category.knowledge.add' AND ar.private_context THEN
   RAISE EXCEPTION 'private run cannot add shared knowledge' USING ERRCODE='23514';
  END IF;
  IF NEW.confirmed_by IS NULL THEN
   IF r.operation<>'category.knowledge.add' OR r.actor_id<>ar.writer_id
    OR NEW.prepared_candidate_id IS NOT NULL
    OR (NEW.version>1 AND (prior.origin='human' OR prior.confirmed_by IS NOT NULL))
    OR NOT EXISTS(SELECT 1 FROM agent_tool_calls tc WHERE tc.tenant_id=NEW.tenant_id
     AND tc.run_id=ar.id AND tc.receipt_id=r.id AND tc.state='completed'
     AND tc.execution_binding->>'operation'=r.operation) THEN
    RAISE EXCEPTION 'material T0 requires its trusted call' USING ERRCODE='23514';
   END IF;
  ELSE
   SELECT * INTO STRICT pc FROM proposal_prepared_candidates WHERE tenant_id=NEW.tenant_id
    AND id=NEW.prepared_candidate_id;
   IF NEW.confirmed_by<>r.actor_id OR r.actor_id<>r.requester_id
    OR pc.category_id<>NEW.category_id OR pc.run_id<>ar.id OR pc.writer_id<>ar.writer_id
    OR pc.requester_id<>r.requester_id OR pc.operation<>r.operation
    OR (pc.execution_binding->'model'->>'cancel_epoch')::integer IS DISTINCT FROM ar.cancel_epoch
    OR NOT EXISTS(SELECT 1 FROM principals p WHERE p.tenant_id=NEW.tenant_id
     AND p.id=NEW.confirmed_by AND p.kind='human') THEN
    RAISE EXCEPTION 'material candidate confirmation mismatch' USING ERRCODE='23514';
   END IF;
  END IF;
 ELSE
  RAISE EXCEPTION 'material import requires a registered import path' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
"""


CREATION_GUARD = r"""
CREATE FUNCTION m3_material_creation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'category creation confirmations cannot be deleted' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.consumed THEN
   RAISE EXCEPTION 'category creation confirmation starts unconsumed' USING ERRCODE='23514';
  END IF;
 ELSE
  IF OLD.consumed OR NOT NEW.consumed OR
   (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'category creation confirmation can only be consumed once' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""


def statements(candidate_constraint):
    from pdos_next.domain.preproject.category_creation_models import TABLES as CREATION_TABLES

    dialect = postgresql.dialect()
    sql = [
        str(CreateTable(table).compile(dialect=dialect))
        for table in (*MATERIAL_TABLES, *CREATION_TABLES)
    ]
    sql += [
        str(CreateIndex(index).compile(dialect=dialect))
        for table in (*MATERIAL_TABLES, *CREATION_TABLES)
        for index in sorted(table.indexes, key=lambda i: i.name)
    ]
    sql += [
        "ALTER TABLE categories ADD COLUMN key text, ADD COLUMN created_by_run_id uuid",
        "UPDATE categories SET key='category-'||replace(id::text,'-','')",
        "ALTER TABLE categories ALTER COLUMN key SET NOT NULL",
    ]
    for constraint in Category.__table__.constraints:
        if (
            set(c.name for c in constraint.columns)
            in ({"tenant_id", "key"}, {"tenant_id", "created_by_run_id"})
            or constraint.name == "category_key_shape"
        ):
            sql.append(str(AddConstraint(constraint).compile(dialect=dialect)))
    for constraint in DefinitionSpec.__table__.constraints:
        if constraint.name in {
            "definition_spec_parameter_version_fk",
            "definition_spec_parameter_pair",
        }:
            sql.append(str(AddConstraint(constraint).compile(dialect=dialect)))
    for index in KnowledgeCurrent.__table__.indexes:
        if len(index.columns) > 1:
            sql.append(str(CreateIndex(index).compile(dialect=dialect)))
    sql.append(f'ALTER TABLE proposal_prepared_candidates DROP CONSTRAINT "{candidate_constraint}"')
    operation_check = next(
        c
        for c in PreparedCandidate.__table__.constraints
        if isinstance(c, CheckConstraint) and "operation IN" in str(c.sqltext)
    )
    sql.append(
        f'ALTER TABLE proposal_prepared_candidates ADD CONSTRAINT "{candidate_constraint}" '
        f"CHECK ({operation_check.sqltext})"
    )
    sql.append("ALTER TABLE category_knowledge_entries ADD COLUMN prepared_candidate_id uuid")
    # Existing knowledge history may predate receipts; new writes are always guarded.
    for constraint in KnowledgeEntry.__table__.foreign_key_constraints:
        if constraint.referred_table.name == "proposal_prepared_candidates":
            sql.append(str(AddConstraint(constraint).compile(dialect=dialect)))
    sql.append(GUARDS)
    sql.append(CREATION_GUARD)
    for table in CREATION_TABLES:
        name = table.name
        own = (
            "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
            "AND actor_id=scope_actor() AND actor_id=scope_requester() AND EXISTS("
            "SELECT 1 FROM principals p WHERE p.tenant_id=" + name + ".tenant_id "
            "AND p.id=" + name + ".actor_id AND p.kind='human' AND p.active)"
        )
        sql.append(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; "
            f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY; "
            f"CREATE POLICY owner_internal ON {name} TO pdos_next_owner "
            "USING(true) WITH CHECK(true); "
            f"CREATE POLICY m3_creation_actor ON {name} TO pdos_next_app "
            f"USING({own}) WITH CHECK({own}); "
            f"REVOKE ALL ON {name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch; "
            f"GRANT SELECT,INSERT,UPDATE ON {name} TO pdos_next_app; "
            f"CREATE TRIGGER m3_creation_confirmation BEFORE INSERT OR UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION m3_material_creation_guard();"
        )
    for table in MATERIAL_TABLES:
        name = table.name
        read = "category_access(tenant_id,category_id)"
        write = "category_access(tenant_id,category_id,true)"
        if name == "promotion_proofs":
            read = "m3_proposal_reader(tenant_id,category_id,source_proposal_id)"
            write += " AND " + read
        sql.append(
            f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY; "
            f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY;"
            f"CREATE POLICY owner_internal ON {name} TO pdos_next_owner "
            "USING(true) WITH CHECK(true);"
            f"CREATE POLICY m3_material_read ON {name} FOR SELECT TO pdos_next_app USING({read});"
            f"CREATE POLICY m3_material_insert ON {name} FOR INSERT TO pdos_next_app "
            f"WITH CHECK({write});"
            f"REVOKE ALL ON {name} FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;"
            f"GRANT SELECT,INSERT ON {name} TO pdos_next_app;"
        )
    for name in ("parameter_current", "category_knowledge_current"):
        sql.append(
            f"GRANT UPDATE ON {name} TO pdos_next_app;"
            f"CREATE POLICY m3_material_update ON {name} FOR UPDATE TO pdos_next_app "
            "USING(category_access(tenant_id,category_id,true)) "
            "WITH CHECK(category_access(tenant_id,category_id,true));"
            f"CREATE TRIGGER m3_material_current BEFORE INSERT OR UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION m3_material_current_guard();"
        )
    for name in ("category_knowledge_entries", "category_knowledge_current"):
        sql.append(
            f"GRANT INSERT ON {name} TO pdos_next_app;"
            f"CREATE POLICY m3_material_insert ON {name} FOR INSERT TO pdos_next_app "
            "WITH CHECK(category_access(tenant_id,category_id,true));"
        )
    for name in ("parameter_versions", "promotion_proofs"):
        sql.append(
            f"CREATE TRIGGER m3_append BEFORE UPDATE OR DELETE ON {name} "
            "FOR EACH ROW EXECUTE FUNCTION m3_append_only();"
        )
    for name in ("parameter_versions", "category_knowledge_entries", "promotion_proofs"):
        sql.append(
            f"CREATE CONSTRAINT TRIGGER m3_material_atom AFTER INSERT ON {name} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION m3_material_atom();"
        )
    for name in (
        "m3_material_category_key",
        "m3_material_current_guard",
        "m3_material_atom",
        "m3_material_creation_guard",
    ):
        sql.append(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC,pdos_agent;")
    return sql


def freeze(state_path):
    from pdos_next.domain.preproject.category_creation_models import TABLES as CREATION_TABLES

    tables = (*MATERIAL_TABLES, *CREATION_TABLES)
    target = local.SERVER / "migrations/schema_s0_0730.py"
    if target.exists():
        raise RuntimeError("Do not overwrite frozen migration SQL")
    config = Config(str(local.SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(local.SERVER / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["s0_0729"]
    local.STATE = state_path
    current = local.read_state()
    if current.get("purpose") != "m3-after-b8" or current.get("port") != 64245:
        raise RuntimeError("Only the verified M3 64245/pdos_test predecessor is permitted")
    local.verified(current)
    engine = engine_for(current["admin_url"])
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "s0_0729"
        checks = connection.execute(
            text(
                "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE "
                "conrelid='proposal_prepared_candidates'::regclass AND contype='c' "
                "AND pg_get_constraintdef(oid) LIKE '%operation%'"
            )
        ).all()
        previous_guard = connection.scalar(
            text(
                "SELECT pg_get_functiondef(oid) FROM pg_proc "
                "WHERE pronamespace='public'::regnamespace "
                "AND proname='m3_proposal_guard'"
            )
        )
    engine.dispose()
    assert previous_guard
    assert len(checks) == 1
    check_name, _ = checks[0]
    sql = statements(check_name)
    old_fragment = (
        "  IF ROW(NEW.id,NEW.tenant_id,NEW.category_id,NEW.owner_id,NEW.entry_kind,NEW.target_kind)"
    )
    assert previous_guard.count(old_fragment) == 1
    # The hint transition changes no business field or revision. RLS still checks
    # proposal readership and category write authority before the trigger runs.
    hint_guard = """  IF NEW.context_hint AND NOT OLD.context_hint
   AND (to_jsonb(NEW)-'context_hint')=(to_jsonb(OLD)-'context_hint') THEN
   RETURN NEW;
  END IF;
"""
    sql.append(previous_guard.replace(old_fragment, hint_guard + old_fragment))
    from migrations.schema_s0_0729 import SCHEMA_SQL as PREVIOUS_SQL

    candidate_ddl = next(
        s for s in PREVIOUS_SQL if "CREATE TABLE proposal_prepared_candidates (" in s
    )
    old_check = next(
        line.strip().rstrip(",")
        for line in candidate_ddl.splitlines()
        if "CHECK (operation IN" in line
    )
    down = [
        "DROP TRIGGER m3_material_atom ON category_knowledge_entries",
        "DROP TRIGGER m3_material_current ON category_knowledge_current",
        "DROP TRIGGER m3_material_category_key ON categories",
        "DROP POLICY m3_material_insert ON category_knowledge_entries",
        "DROP POLICY m3_material_insert ON category_knowledge_current",
        "DROP POLICY m3_material_update ON category_knowledge_current",
        "REVOKE INSERT ON category_knowledge_entries FROM pdos_next_app",
        "REVOKE INSERT,UPDATE ON category_knowledge_current FROM pdos_next_app",
        "ALTER TABLE category_knowledge_entries DROP COLUMN prepared_candidate_id",
    ]
    down.append(previous_guard)
    for constraint in DefinitionSpec.__table__.constraints:
        if constraint.name in {
            "definition_spec_parameter_version_fk",
            "definition_spec_parameter_pair",
        }:
            down.append(f'ALTER TABLE definition_specs DROP CONSTRAINT "{constraint.name}"')
    for index in KnowledgeCurrent.__table__.indexes:
        if len(index.columns) > 1:
            down.append(f'DROP INDEX "{index.name}"')
    down.extend(f'DROP TABLE "{table.name}"' for table in reversed(tables))
    down += [
        "DROP FUNCTION m3_material_creation_guard()",
        "DROP FUNCTION m3_material_atom()",
        "DROP FUNCTION m3_material_current_guard()",
        "DROP FUNCTION m3_material_category_key()",
        "ALTER TABLE categories DROP COLUMN key, DROP COLUMN created_by_run_id",
        f'ALTER TABLE proposal_prepared_candidates DROP CONSTRAINT "{check_name}"',
        f'ALTER TABLE proposal_prepared_candidates ADD CONSTRAINT "{check_name}" {old_check}',
    ]
    target.write_text(
        "# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"
        '"""M3 category materials frozen from s0_0729; no live ORM imports."""\n\n'
        + "TABLES = "
        + repr(tuple(t.name for t in tables))
        + "\n\n"
        + "SCHEMA_SQL = "
        + repr(tuple(sql))
        + "\n\n"
        + "DOWNGRADE_SQL = "
        + repr(tuple(down))
        + "\n"
    )
    print(f"Frozen {len(tables)} material tables and {len(sql)} statements from s0_0729")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    freeze(parser.parse_args().state.resolve())
