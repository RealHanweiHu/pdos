"""Ordinary-caller proof ACL, generated from the existing finite source projectors.

The policy never queries the review table or the knowledge catalog. Native
answer proofs are flattened by the write atom; feedback may refer to one actual
knowledge row whose proof is already flat. This bounds policy evaluation and
avoids review -> subject -> review RLS recursion.
"""

# ruff: noqa: E501 -- generated finite SQL predicates remain auditable.

from sqlalchemy import Text, and_, cast, exists, func, literal_column, select, union_all
from sqlalchemy.dialects.postgresql import dialect

from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry

SIGNATURE = "knowledge_answer_sources_visible(uuid,uuid,jsonb)"


def _knowledge():
    from .models import DesignRuleCurrent, DesignRuleVersion

    entry, current = KnowledgeEntry, KnowledgeCurrent
    rule, pointer = DesignRuleVersion, DesignRuleCurrent

    def sha(body):
        return func.encode(func.sha256(func.convert_to(cast(body, Text), "UTF8")), "hex")

    return union_all(
        select(
            entry.id.label("source_id"),
            entry.tenant_id,
            entry.category_id,
            entry.version.label("source_revision"),
            sha(entry.content).label("content_hash"),
        )
        .join(
            current,
            and_(
                current.tenant_id == entry.tenant_id,
                current.lineage_id == entry.lineage_id,
                current.status == "active",
            ),
        )
        .where(entry.action != "withdraw"),
        select(
            rule.id.label("source_id"),
            rule.tenant_id,
            rule.category_id,
            rule.revision.label("source_revision"),
            sha(rule.body).label("content_hash"),
        ).join(pointer, and_(pointer.tenant_id == rule.tenant_id, pointer.rule_id == rule.rule_id)),
    ).subquery("ordinary_knowledge_leaves")


def visibility_body():
    from pdos_next.enterprise_search.schemas import SOURCE_TYPES
    from pdos_next.enterprise_search.sources import catalog

    branches = []
    for kind in SOURCE_TYPES:
        # Every non-knowledge branch is the existing ordinary RLS projector;
        # these branches do not query KnowledgeEntry/review metadata at all.
        source = _knowledge() if kind == "knowledge" else catalog([kind])
        statement = select(
            exists(
                select(1)
                .select_from(source)
                .where(
                    source.c.tenant_id == literal_column("t"),
                    source.c.category_id == literal_column("c"),
                    cast(source.c.source_id, Text) == literal_column("expected->>'source_id'"),
                    cast(source.c.source_revision, Text)
                    == literal_column("expected->>'source_revision'"),
                    source.c.content_hash == literal_column("expected->>'content_hash'"),
                )
            )
        )
        query = str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
        branches.append(f" WHEN '{kind}' THEN\n  {query} INTO visible;")
    return (
        """
DECLARE expected jsonb; visible boolean;
BEGIN
 IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid
 OR NOT public.category_access(t,c) OR jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 FOR expected IN SELECT value FROM jsonb_array_elements(proof) LOOP
  IF expected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false; END IF;
  CASE expected->>'source_type'
"""
        + "\n".join(branches)
        + """
  ELSE RETURN false; END CASE;
  IF visible IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END
"""
    )


def upgrade_sql():
    return (
        "CREATE FUNCTION public.knowledge_answer_sources_visible(t uuid,c uuid,proof jsonb) RETURNS boolean "
        "LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $knowledge_answer_acl$\n"
        + visibility_body()
        + ";\n$knowledge_answer_acl$",
        f"REVOKE ALL ON FUNCTION public.{SIGNATURE} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch",
        f"GRANT EXECUTE ON FUNCTION public.{SIGNATURE} TO pdos_next_app",
        "CREATE POLICY knowledge_answer_source_read ON public.category_knowledge_entries AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (answer_sources IS NULL OR public.knowledge_answer_sources_visible(tenant_id,category_id,answer_sources))",
        *(
            f"CREATE POLICY knowledge_answer_source_read ON public.{table} AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (source_basis->'answer_sources' IS NULL OR public.knowledge_answer_sources_visible(tenant_id,category_id,source_basis->'answer_sources'))"
            for table in ("knowledge_candidate_versions", "knowledge_rule_versions")
        ),
    )


def downgrade_sql():
    return (
        *(
            f"DROP POLICY knowledge_answer_source_read ON public.{table}"
            for table in (
                "category_knowledge_entries",
                "knowledge_candidate_versions",
                "knowledge_rule_versions",
            )
        ),
        f"DROP FUNCTION public.{SIGNATURE}",
    )
