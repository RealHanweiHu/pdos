"""Freeze the one-time S0 schema reset; no database access or old-chain imports."""

import json
import sys
from hashlib import sha256
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable
from sqlalchemy.sql.ddl import sort_tables_and_constraints

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from pdos_next.models import Base  # noqa: E402

SCOPE_SQL = [
    """CREATE FUNCTION public.scope_actor() RETURNS uuid LANGUAGE sql STABLE AS $$
      SELECT nullif(current_setting('pdos.actor_id',true),'')::uuid $$""",
    """CREATE FUNCTION public.scope_requester() RETURNS uuid LANGUAGE sql STABLE AS $$
      SELECT nullif(current_setting('pdos.requester_id',true),'')::uuid $$""",
    """CREATE FUNCTION public.category_access(tid uuid,cid uuid,writing boolean DEFAULT false)
      RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      SELECT tid=nullif(current_setting('pdos.tenant_id',true),'')::uuid
       AND (nullif(current_setting('pdos.category_id',true),'') IS NULL
         OR cid=nullif(current_setting('pdos.category_id',true),'')::uuid)
       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g
         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
         WHERE p.tenant_id=tid AND p.id=public.scope_actor() AND p.active
          AND g.category_id=cid AND g.expires_at>statement_timestamp()
          AND (NOT writing OR g.can_write))
       AND EXISTS(SELECT 1 FROM public.principals p JOIN public.grants g
         ON g.tenant_id=p.tenant_id AND g.principal_id=p.id
         WHERE p.tenant_id=tid AND p.id=public.scope_requester() AND p.active
          AND g.category_id=cid AND g.expires_at>statement_timestamp()
          AND (NOT writing OR g.can_write)) $$""",
    """CREATE FUNCTION public.category_bootstrap(tid uuid,cid uuid) RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      SELECT tid=nullif(current_setting('pdos.tenant_id',true),'')::uuid
       AND public.scope_actor()=public.scope_requester()
       AND EXISTS(SELECT 1 FROM public.categories c JOIN public.principals p ON p.id=c.owner_id
         AND p.tenant_id=c.tenant_id WHERE c.tenant_id=tid AND c.id=cid
          AND p.id=public.scope_actor() AND p.active AND p.kind='human')
       AND NOT EXISTS(SELECT 1 FROM public.grants g WHERE g.tenant_id=tid AND g.category_id=cid) $$""",
    """CREATE FUNCTION public.category_owner(tid uuid,cid uuid) RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      SELECT public.category_access(tid,cid,true)
       AND public.scope_actor()=public.scope_requester()
       AND EXISTS(SELECT 1 FROM public.categories c JOIN public.principals p ON p.id=c.owner_id
         AND p.tenant_id=c.tenant_id WHERE c.tenant_id=tid AND c.id=cid
          AND p.id=public.scope_actor() AND p.active AND p.kind='human') $$""",
    """CREATE FUNCTION public.category_for_product(pid uuid) RETURNS uuid
      LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
      SELECT category_id FROM public.products WHERE id=pid
       AND tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid $$""",
    """CREATE FUNCTION public.bind_model_category() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
      DECLARE expected uuid;
      BEGIN
       IF NEW.product_id IS NOT NULL THEN
        SELECT category_id INTO STRICT expected FROM public.products
         WHERE id=NEW.product_id AND tenant_id=NEW.tenant_id;
        IF NEW.category_id IS NULL THEN NEW.category_id:=expected; END IF;
        IF NEW.category_id IS DISTINCT FROM expected THEN
         RAISE EXCEPTION 'category/model mismatch'; END IF;
       END IF;
       RETURN NEW;
      END $$""",
    """CREATE FUNCTION public.bind_receipt_category() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
      DECLARE expected uuid;
      BEGIN
       SELECT category_id INTO STRICT expected FROM public.action_receipts
        WHERE id=NEW.receipt_id AND tenant_id=NEW.tenant_id;
       IF NEW.category_id IS NULL THEN NEW.category_id:=expected; END IF;
       IF NEW.category_id IS DISTINCT FROM expected THEN
        RAISE EXCEPTION 'category/receipt mismatch'; END IF;
       RETURN NEW;
      END $$""",
    """CREATE FUNCTION public.protect_category_binding() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
      BEGIN
       IF NEW.category_id IS DISTINCT FROM OLD.category_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'category binding is immutable'; END IF;
       RETURN NEW;
      END $$""",
]


def audience(table):
    owner = next(
        (
            name
            for name in ("owner_id", "human_owner_id", "accountable_owner_id", "requester_id")
            if name in table.c
        ),
        None,
    )
    if "visibility" not in table.c:
        # Pointers/links to private facts inherit the fact's RLS instead of exposing its ID.
        parents = []
        for constraint in table.foreign_key_constraints:
            parent = constraint.referred_table
            if parent is table or "visibility" not in parent.c:
                continue
            comparisons = " AND ".join(
                f'p."{element.column.name}"="{table.name}"."{element.parent.name}"'
                for element in constraint.elements
            )
            # MATCH SIMPLE optional references do not hide a row when absent.
            absent = " OR ".join(
                f'"{table.name}"."{element.parent.name}" IS NULL'
                for element in constraint.elements
                if element.parent.nullable
            )
            present = f'EXISTS(SELECT 1 FROM "{parent.name}" p WHERE {comparisons})'
            parents.append(f"({absent} OR {present})" if absent else present)
        return " AND ".join(parents) or "true"
    if owner is None:
        raise RuntimeError(f"Visibility-bearing table without explicit owner: {table.name}")
    return (
        f"(\"{table.name}\".visibility='category' OR "
        f'"{table.name}"."{owner}"=public.scope_requester() OR '
        f"EXISTS(SELECT 1 FROM public.object_audiences a WHERE "
        f'a.tenant_id="{table.name}".tenant_id AND a.category_id="{table.name}".category_id '
        f"AND a.object_type='{table.name}' AND a.subject_id=\"{table.name}\".id "
        f'AND a.owner_id="{table.name}"."{owner}" AND a.principal_id=public.scope_requester()))'
    )


def generate():
    captured = json.loads(
        (
            ROOT.parent
            / "docs/reports/evidence/pdos-next-s0-20261008/baseline"
            / "database-guards.json"
        ).read_text()
    )
    metadata = Base.metadata
    for table in metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            if not constraint.name:
                signature = "|".join(
                    element.target_fullname + ":" + element.parent.name
                    for element in constraint.elements
                )
                constraint.name = (
                    f"fk_{table.name[:40]}_{sha256(signature.encode()).hexdigest()[:8]}"
                )
    dialect = postgresql.dialect()
    statements = []
    for table, constraints in sort_tables_and_constraints(metadata.tables.values()):
        if table is not None:
            statements.append(
                str(
                    CreateTable(table, include_foreign_key_constraints=constraints).compile(
                        dialect=dialect
                    )
                )
            )
            statements.extend(
                str(CreateIndex(index).compile(dialect=dialect))
                for index in sorted(table.indexes, key=lambda index: index.name)
            )
        else:
            statements.extend(str(AddConstraint(c).compile(dialect=dialect)) for c in constraints)
    statements += SCOPE_SQL
    for function in captured["functions"]:
        sql = function["sql"]
        sql = sql.replace(
            "g.product_id=a.product_id", "g.category_id=public.category_for_product(a.product_id)"
        )
        sql = sql.replace(
            "AND product_id=(n->>'product_id')::uuid AND principal_id=",
            "AND category_id=public.category_for_product((n->>'product_id')::uuid) AND principal_id=",
        )
        statements.append(sql)
    statements += captured["triggers"]
    for name, role, permission in captured["table_grants"]:
        statements.append(f'GRANT {permission} ON "{name}" TO {role}')
    for name, column, role, permission in captured["column_grants"]:
        statements.append(f'GRANT {permission}("{column}") ON "{name}" TO {role}')
    for name in ("categories", "object_audiences"):
        statements.append(f'GRANT SELECT,INSERT,UPDATE ON "{name}" TO pdos_next_app')
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        name = table.name
        if name == "login_sessions":
            continue
        tenant = "tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
        if name == "categories":
            read = "public.category_access(tenant_id,id) OR public.category_bootstrap(tenant_id,id)"
            write = f"{tenant} AND owner_id=public.scope_actor() AND public.scope_actor()=public.scope_requester()"
        elif name == "grants":
            read = "public.category_access(tenant_id,category_id) OR public.category_bootstrap(tenant_id,category_id)"
            write = (
                "public.category_owner(tenant_id,category_id) OR "
                "(public.category_bootstrap(tenant_id,category_id) AND principal_id=public.scope_actor())"
            )
        elif "category_id" in table.c:
            read = f"public.category_access(tenant_id,category_id) AND {audience(table)}"
            write = f"public.category_access(tenant_id,category_id,true) AND {audience(table)}"
            if name == "object_audiences":
                write += " AND owner_id=public.scope_requester()"
            if "product_id" in table.c:
                statements.append(
                    f'CREATE TRIGGER a_bind_category BEFORE INSERT ON "{name}" '
                    "FOR EACH ROW EXECUTE FUNCTION public.bind_model_category()"
                )
            elif "receipt_id" in table.c:
                statements.append(
                    f'CREATE TRIGGER a_bind_category BEFORE INSERT ON "{name}" '
                    "FOR EACH ROW EXECUTE FUNCTION public.bind_receipt_category()"
                )
            statements.append(
                f'CREATE TRIGGER a_protect_category BEFORE UPDATE ON "{name}" '
                "FOR EACH ROW EXECUTE FUNCTION public.protect_category_binding()"
            )
        else:
            read = write = tenant
        statements += [
            f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY',
            f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY',
            f'CREATE POLICY category_scope ON "{name}" USING ({read}) WITH CHECK ({write})',
        ]
    statements += [
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pdos_agent",
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC,pdos_agent",
    ]
    statements += [
        f"GRANT {permission} ON FUNCTION {signature} TO {role}"
        for signature, role, permission in captured["function_grants"]
    ]
    statements += [
        f"GRANT EXECUTE ON FUNCTION {signature} TO pdos_next_app"
        for signature in (
            "scope_actor()",
            "scope_requester()",
            "category_access(uuid,uuid,boolean)",
            "category_bootstrap(uuid,uuid)",
            "category_owner(uuid,uuid)",
            "category_for_product(uuid)",
        )
    ]
    functions = [
        (function["sql"].split(" RETURNS ", 1)[0].split("FUNCTION ", 1)[1])
        for function in captured["functions"]
    ]
    # regprocedure signatures avoid parameters/defaults in downgrade statements.
    functions = captured.get("function_signatures", functions)
    content = (
        '"""Frozen S0 baseline DDL; regenerate only before first installation."""\n'
        "# ruff: noqa: E501\n\nSCHEMA_SQL = " + repr(tuple(statements)) + "\n"
        "TABLES = " + repr(tuple(sorted(metadata.tables))) + "\n"
        "FUNCTIONS = " + repr(tuple(functions)) + "\n"
    )
    output = ROOT / "server/migrations/schema_s0_0001.py"
    output.write_text(content)
    print(f"Frozen S0 schema: {len(metadata.tables)} tables, {len(statements)} statements")


if __name__ == "__main__":
    generate()
