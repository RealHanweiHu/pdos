"""Ordinary-caller historical ACL helpers; no installer or new-use attestation.

These functions deliberately have SECURITY INVOKER and static native branches.
They retain actual artifact/product/project/native-subject RLS. Receipt
authenticity belongs to the Python resolver and the independent write atom;
reading Receipt here would recurse through knowledge's own Receipt policy. Source
withdrawal or an old signature's validity is not a reason to erase readable
history. Active bytes and current original safety are checked by provenance.py
before each new candidate/publication use.
"""

# ruff: noqa: E501 -- complete finite SQL predicates stay legible.

from .provenance import RESULT_SOURCES

CONTENT = "knowledge_content_sources_visible"
RESULT = "knowledge_result_sources_visible"
SIGNATURES = (f"{CONTENT}(uuid,uuid,uuid,jsonb)", f"{RESULT}(uuid,uuid,uuid,jsonb)")

CONTENT_BODY = r"""
DECLARE expected jsonb; actual_product uuid; original_id uuid; found_source boolean;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR NOT public.category_access(t,c) OR jsonb_typeof(basis) IS DISTINCT FROM 'object'
  OR jsonb_typeof(basis->'artifacts') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOR expected IN SELECT value FROM jsonb_array_elements(basis->'artifacts') LOOP
  IF jsonb_typeof(expected) IS DISTINCT FROM 'object' OR NOT(expected ? 'product_id')
   OR expected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false; END IF;
  SELECT a.product_id,a.original_id,true INTO actual_product,original_id,found_source
   FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c
    AND a.id::text=expected->>'id' AND a.product_id::text IS NOT DISTINCT FROM expected->>'product_id';
  IF found_source IS DISTINCT FROM true THEN RETURN false; END IF;
  IF actual_product IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products source_product
    WHERE source_product.tenant_id=t AND source_product.category_id=c AND source_product.id=actual_product) THEN RETURN false; END IF;
  IF original_id IS NOT NULL THEN
   IF original_id::text IS DISTINCT FROM expected->'original'->>'id'
    OR NOT EXISTS(SELECT 1 FROM public.uploaded_originals o WHERE o.tenant_id=t AND o.category_id=c
     AND o.product_id IS NOT DISTINCT FROM actual_product AND o.id=original_id) THEN RETURN false; END IF;
  END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END
""".strip()


def _branch(source, material):
    model = source.model
    table = model.__tablename__
    operations = "(" + ",".join(repr(value) for value in source.operations) + ")"
    operation_binding = (
        " AND native.operation=expected->>'operation'" if hasattr(model, "operation") else ""
    )
    hash_binding = (
        f" AND native.{material.hash_field}=expected->>'body_sha256'" if material.hash_field else ""
    )
    return f"""
 ELSIF expected->>'table'='{table}' AND expected->>'subject_type'='{source.subject_kind}' THEN
  SELECT EXISTS(SELECT 1 FROM public.{table} native
   JOIN public.products source_product ON source_product.tenant_id=native.tenant_id
    AND source_product.category_id=native.category_id AND source_product.id=native.product_id
   JOIN public.projects source_project ON source_project.tenant_id=native.tenant_id
    AND source_project.category_id=native.category_id AND source_project.product_id=native.product_id
    AND source_project.id=native.project_id
   WHERE native.tenant_id=t AND native.category_id=c AND native.id::text=expected->>'row_id'
    AND native.product_id::text=expected->>'product_id' AND native.project_id::text=expected->>'project_id'
    AND native.revision::text=expected->>'revision'
    AND native.id::text=expected->>'subject_id'
    AND native.revision::text=expected->>'subject_revision'
    AND expected->>'operation' IN {operations}{operation_binding}
    AND expected->>'material_contract'='{material.contract}'{hash_binding}
  ) INTO visible;
""".rstrip()


def result_body():
    branches = []
    # Multiple catalog entries can describe one table/kind (e.g. Run launch and
    # results). Merge only their finite registered operation sets for SQL CASE.
    grouped = {}
    for source, material in RESULT_SOURCES:
        key = (source.model, source.subject_kind)
        if key not in grouped:
            grouped[key] = (source, material)
        else:
            from dataclasses import replace

            previous, previous_material = grouped[key]
            grouped[key] = (
                replace(
                    previous,
                    operations=tuple(dict.fromkeys((*previous.operations, *source.operations))),
                ),
                previous_material,
            )
    for source, material in grouped.values():
        branches.append(_branch(source, material))
    return (
        r"""
DECLARE expected jsonb; visible boolean;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
  OR NOT public.category_access(t,c) OR jsonb_typeof(basis) IS DISTINCT FROM 'object'
  OR jsonb_typeof(basis->'result_receipts') IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOR expected IN SELECT value FROM jsonb_array_elements(basis->'result_receipts') LOOP
  IF jsonb_typeof(expected) IS DISTINCT FROM 'object' OR expected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false;
"""
        + "\n".join(branches)
        + r"""
  ELSE RETURN false; END IF;
  IF visible IS DISTINCT FROM true OR NOT public.knowledge_content_sources_visible(t,c,p,
   jsonb_build_object('artifacts',expected->'artifacts')) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END
"""
    )


def _function(name, body):
    return (
        f"CREATE FUNCTION public.{name}(t uuid,c uuid,p uuid,basis jsonb) RETURNS boolean\n"
        "LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $knowledge_provenance$\n"
        f"{body.rstrip()};\n$knowledge_provenance$"
    )


def upgrade_sql():
    functions = (_function(CONTENT, CONTENT_BODY), _function(RESULT, result_body()))
    names = ",".join("public." + value for value in SIGNATURES)
    return (
        *functions,
        f"REVOKE ALL ON FUNCTION {names} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        f"GRANT EXECUTE ON FUNCTION {names} TO pdos_next_app",
    )


def downgrade_sql():
    return tuple(f"DROP FUNCTION public.{value}" for value in reversed(SIGNATURES))
