"""Accept fixed v2 applicability declarations in the existing publication atom."""

import hashlib
import importlib

import sqlalchemy as sa
from alembic import op

from migrations.schema_s0_0001 import SCHEMA_SQL

revision = "s0_0775"
down_revision = "s0_0774"
branch_labels = None
depends_on = None

SIGNATURE = "public.assert_change_coverage_atom(uuid,uuid)"
_predecessor = importlib.import_module(
    "migrations.versions.s0_0424_change_manufacturing_capture_contract"
)
_definitions = [
    sql
    for sql in SCHEMA_SQL
    if sql.startswith("CREATE OR REPLACE FUNCTION public.assert_change_coverage_atom(")
]
if len(_definitions) != 1:
    raise RuntimeError("Expected the one frozen coverage publication guard")
OLD_FUNCTION = _definitions[0]
for _before, _after in _predecessor.REPAIRS["assert_change_coverage_atom(uuid,uuid)"]:
    if OLD_FUNCTION.count(_before) != 1:
        raise RuntimeError("Frozen coverage predecessor repair is not unique")
    OLD_FUNCTION = OLD_FUNCTION.replace(_before, _after, 1)
OLD_BODY = OLD_FUNCTION.split("$function$")[1]
if (
    hashlib.sha256(OLD_BODY.encode()).hexdigest()
    != _predecessor.HASHES["assert_change_coverage_atom(uuid,uuid)"][1]
):
    raise RuntimeError("Unexpected coverage predecessor body")

DECLARATIONS = r"""
  IF NOT COALESCE(jsonb_typeof(COALESCE(m->'paths','[]'::jsonb))='array'
    AND jsonb_typeof(COALESCE(m->'facet_states','[]'::jsonb))='array',false)
  THEN RAISE EXCEPTION 'coverage applicability arrays required'; END IF;
  applicability_keys:=ARRAY[]::text[];
  FOR item IN SELECT v FROM jsonb_array_elements(COALESCE(m->'paths','[]'::jsonb)) v LOOP
    IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['node','targets','status','reason'])
      AND public.coverage_ref_identity(item->'node')=ANY(nodes)
      AND jsonb_typeof(item->'targets')='array' AND jsonb_array_length(item->'targets')>0
      AND item->>'status' IN ('applicable','not_applicable','unknown')
      AND jsonb_typeof(item->'reason')='string'
      AND length(btrim(item->>'reason')) BETWEEN 1 AND 2000,false)
    THEN RAISE EXCEPTION 'coverage exact path applicability required'; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(item->'targets') t
      WHERE jsonb_typeof(t)<>'string' OR (t #>> '{}') NOT IN (
        'spec','part','bom','interface','engineering_configuration','build','sample','test_run',
        'operation','tooling','fixture','sop','work_instruction','control_plan',
        'manufacturing_baseline','pilot_run','manufacturing_release','customer_sample',
        'supply_commitment','inventory','wip','training','evidence','issue','capa',
        'manufacturing_configuration','graph_snapshot'))
    THEN RAISE EXCEPTION 'coverage path target kind required'; END IF;
    SELECT array_agg(t ORDER BY t) INTO facet_nodes
      FROM jsonb_array_elements_text(item->'targets') t;
    IF cardinality(facet_nodes)<>(SELECT count(DISTINCT t) FROM unnest(facet_nodes) t)
    THEN RAISE EXCEPTION 'coverage path target kinds must be unique'; END IF;
    applicability_key:=jsonb_build_array(public.coverage_ref_identity(item->'node'),
      to_jsonb(facet_nodes))::text;
    IF applicability_key=ANY(applicability_keys)
    THEN RAISE EXCEPTION 'coverage path applicability must be unique'; END IF;
    applicability_keys:=array_append(applicability_keys,applicability_key);
  END LOOP;
  applicability_keys:=ARRAY[]::text[];
  FOR item IN SELECT v FROM jsonb_array_elements(COALESCE(m->'facet_states','[]'::jsonb)) v LOOP
    IF NOT COALESCE(public.coverage_json_keys(item,ARRAY['node','facet','status','reason'])
      AND public.coverage_ref_identity(item->'node')=ANY(nodes)
      AND item->>'facet'=ANY(facets)
      AND item->>'status' IN ('complete','not_applicable','unknown')
      AND jsonb_typeof(item->'reason')='string'
      AND length(btrim(item->>'reason')) BETWEEN 1 AND 2000,false)
    THEN RAISE EXCEPTION 'coverage exact facet applicability required'; END IF;
    applicability_key:=jsonb_build_array(public.coverage_ref_identity(item->'node'),
      item->>'facet')::text;
    IF applicability_key=ANY(applicability_keys)
    THEN RAISE EXCEPTION 'coverage facet applicability must be unique'; END IF;
    applicability_keys:=array_append(applicability_keys,applicability_key);
  END LOOP;
"""

REPLACEMENTS = (
    (
        "fixed jsonb; steps integer:=0;",
        "fixed jsonb; steps integer:=0;\n applicability_keys text[]; applicability_key text;",
    ),
    (
        "public.coverage_json_keys(m,ARRAY[",
        "public.coverage_json_keys(m-ARRAY['paths','facet_states'],ARRAY[",
    ),
    (
        "m->>'schema_version'='pdos-controlled-change-coverage-v1'",
        "m->>'schema_version' IN ('pdos-controlled-change-coverage-v1',"
        "'pdos-controlled-change-coverage-v2')\n"
        "   AND (m->>'schema_version'<>'pdos-controlled-change-coverage-v1'\n"
        "     OR NOT (m ?| ARRAY['paths','facet_states']))",
    ),
    (
        " FOR item IN SELECT v FROM jsonb_array_elements(m->'units') v LOOP",
        DECLARATIONS + " FOR item IN SELECT v FROM jsonb_array_elements(m->'units') v LOOP",
    ),
)
NEW_FUNCTION = OLD_FUNCTION
for _before, _after in REPLACEMENTS:
    if NEW_FUNCTION.count(_before) != 1:
        raise RuntimeError("Coverage applicability replacement is not unique")
    NEW_FUNCTION = NEW_FUNCTION.replace(_before, _after, 1)
NEW_BODY = NEW_FUNCTION.split("$function$")[1]


def _replace(expected_body, replacements):
    definition, body = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT pg_get_functiondef(p.oid),p.prosrc FROM pg_proc p "
                "WHERE p.oid=to_regprocedure(:signature)"
            ),
            {"signature": SIGNATURE},
        )
        .one()
    )
    if body != expected_body:
        raise RuntimeError("Unreviewed coverage guard; no replacement was applied")
    for before, after in replacements:
        if definition.count(before) != 1:
            raise RuntimeError("Coverage guard anchor changed; no replacement was applied")
        definition = definition.replace(before, after, 1)
    op.execute(definition)


def upgrade():
    _replace(OLD_BODY, REPLACEMENTS)


def downgrade():
    op.execute("LOCK TABLE controlled_change_coverage_facts IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM controlled_change_coverage_facts
        WHERE material->>'schema_version'='pdos-controlled-change-coverage-v2')
      THEN RAISE EXCEPTION 'Published v2 coverage requires s0_0775' USING ERRCODE='23514';
      END IF;
    END $$""")
    _replace(NEW_BODY, tuple((after, before) for before, after in reversed(REPLACEMENTS)))
