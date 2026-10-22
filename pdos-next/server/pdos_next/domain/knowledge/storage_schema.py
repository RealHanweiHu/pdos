"""Knowledge DDL/RLS/CAS declarations, with mandatory real domain atom hooks.

No installer or database access. Source read policies use the existing
host-owned ``knowledge_content_sources_visible`` and
``knowledge_result_sources_visible`` ACL helpers, installed by the root
migration, not a SECURITY DEFINER bare artifact lookup. Retained content keeps
its actual source-product scope; publication-target scope cannot replace it.
"""

# ruff: noqa: E501 -- complete PostgreSQL expressions keep boundary checks legible.

from collections.abc import Mapping

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable, DropConstraint

from pdos_next import models as registered_models  # noqa: F401 -- register parent tables

from .models import (
    ASSESSMENT,
    CANDIDATE,
    CANDIDATE_CURRENT,
    RULE,
    RULE_CURRENT,
    ApplicabilityAssessment,
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)

TABLES = tuple(
    model.__table__
    for model in (
        KnowledgeCandidateVersion,
        KnowledgeCandidateCurrent,
        ApplicabilityAssessment,
        DesignRuleVersion,
        DesignRuleCurrent,
    )
)
FACTS = (CANDIDATE, RULE)
CURRENT_FACTS = {CANDIDATE_CURRENT: (CANDIDATE, "candidate_id"), RULE_CURRENT: (RULE, "rule_id")}
ATOM_NAMES = (
    "assert_knowledge_candidate",
    "assert_knowledge_rule",
    "assert_knowledge_assessment",
)


def cycle_constraints():
    return tuple(
        constraint
        for table in TABLES
        for constraint in sorted(table.foreign_key_constraints, key=lambda value: value.name or "")
        if constraint.use_alter
    )


def table_sql():
    dialect = postgresql.dialect()
    return (
        *(
            str(statement.compile(dialect=dialect))
            for table in TABLES
            for statement in (
                CreateTable(table),
                *(
                    CreateIndex(index)
                    for index in sorted(table.indexes, key=lambda value: value.name)
                ),
            )
        ),
        *(
            str(AddConstraint(constraint).compile(dialect=dialect))
            for constraint in cycle_constraints()
        ),
    )


def _expression(value, *, label):
    if not isinstance(value, str) or not value.strip() or ";" in value:
        raise ValueError(f"Actual {label} source ACL expression is required")
    return value


def _scope_read(name):
    return (
        "public.category_access(tenant_id,category_id) "
        "AND (visibility='category' OR owner_id=public.scope_requester()) "
        f"AND ({name}.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products p "
        f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
        f"AND p.id={name}.product_id)) "
        f"AND ({name}.project_id IS NULL OR EXISTS(SELECT 1 FROM public.projects p "
        f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
        f"AND p.product_id={name}.product_id AND p.id={name}.project_id))"
    )


RESULT_ACL = (
    "public.knowledge_result_sources_visible(tenant_id,category_id,product_id,source_basis)"
)
CONTENT_ACL = (
    "public.knowledge_content_sources_visible(tenant_id,category_id,product_id,source_basis)"
)


def policy_sql(*, candidate_result_acl: str = RESULT_ACL, rule_result_acl: str = RESULT_ACL):
    """Real result-owner ACL expressions are required before any read policy exists.

    Expressions refer to the respective Version row using its full table name.
    They must check actual linked result authority/ACL, not booleans supplied in
    candidate bodies. Parent queries run as the ordinary application caller.
    """
    result_acls = {
        CANDIDATE: _expression(candidate_result_acl, label="candidate result"),
        RULE: _expression(rule_result_acl, label="rule result"),
    }
    statements = []
    for table in TABLES:
        name = table.name
        read = _scope_read(name)
        if name in FACTS:
            read += f" AND {CONTENT_ACL} AND ({result_acls[name]})"
        elif name in CURRENT_FACTS:
            fact, identity = CURRENT_FACTS[name]
            read += (
                f" AND EXISTS(SELECT 1 FROM public.{fact} fixed "
                f"WHERE fixed.tenant_id={name}.tenant_id AND fixed.category_id={name}.category_id "
                f"AND fixed.id={name}.version_id AND fixed.revision={name}.revision "
                f"AND fixed.{identity}={name}.{identity} "
                f"AND ROW(fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility) "
                f"IS NOT DISTINCT FROM ROW({name}.product_id,{name}.project_id,{name}.owner_id,{name}.visibility))"
            )
        else:
            read += (
                f" AND EXISTS(SELECT 1 FROM public.{RULE} publication "
                f"WHERE publication.tenant_id={name}.tenant_id AND publication.category_id={name}.category_id "
                f"AND publication.id={name}.publication_id AND publication.assessment_id={name}.id "
                f"AND publication.candidate_version_id={name}.candidate_version_id "
                f"AND publication.candidate_revision={name}.candidate_revision "
                f"AND ROW(publication.product_id,publication.project_id,publication.owner_id,publication.visibility) "
                f"IS NOT DISTINCT FROM ROW({name}.product_id,{name}.project_id,{name}.owner_id,{name}.visibility))"
            )
        write = "public.category_access(tenant_id,category_id,true)"
        if name in (RULE, RULE_CURRENT, ASSESSMENT):
            write += (
                " AND public.scope_actor()=public.scope_requester() "
                "AND EXISTS(SELECT 1 FROM public.principals h "
                "WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid "
                "AND h.id=public.scope_actor() AND h.kind='human' AND h.active)"
            )
        # Fact insertion cannot require a reciprocal parent to be flushed first:
        # independent deferred atoms and cyclic FKs prove the complete new group.
        insert = f"{write} AND {_scope_read(name)}"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY knowledge_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY knowledge_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({insert})',
                f'REVOKE ALL ON public."{name}" FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name in CURRENT_FACTS:
            statements.extend(
                (
                    f'CREATE POLICY knowledge_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {_scope_read(name)})',
                    f'GRANT UPDATE(version_id,revision) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def current_guard(table, version_table):
    return f"""
BEGIN
 IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW;
 ELSIF TG_OP='UPDATE' AND (to_jsonb(NEW)-ARRAY['version_id','revision']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['version_id','revision'])
  AND NEW.revision=OLD.revision+1 AND EXISTS(SELECT 1 FROM public.{version_table} v WHERE v.tenant_id=NEW.tenant_id
   AND v.id=NEW.version_id AND v.revision=NEW.revision AND v.previous_id=OLD.version_id AND v.previous_revision=OLD.revision) THEN RETURN NEW;
 END IF;
 RAISE EXCEPTION '{table} requires exact immutable-scope single-step CAS' USING ERRCODE='23514';
END
"""


def current_atom(table, version_table, identity):
    return f"""
DECLARE cur public.{table}; fixed public.{version_table}; cx xid; vx xid;
BEGIN
 SELECT * INTO STRICT cur FROM public.{table} WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT xmin INTO cx FROM public.{table} WHERE tenant_id=NEW.tenant_id AND id=NEW.id;
 SELECT * INTO STRICT fixed FROM public.{version_table} WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 SELECT xmin INTO vx FROM public.{version_table} WHERE tenant_id=NEW.tenant_id AND id=cur.version_id;
 IF vx IS DISTINCT FROM cx
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.{identity},cur.version_id,cur.revision)
   IS DISTINCT FROM ROW(fixed.category_id,fixed.product_id,fixed.project_id,fixed.owner_id,fixed.visibility,fixed.{identity},fixed.id,fixed.revision) THEN
  RAISE EXCEPTION 'Knowledge Current requires its exact same-transaction scoped version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""


def _function(name, args, body, returns="trigger"):
    return (
        f"CREATE FUNCTION public.{name}({args}) RETURNS {returns}\n"
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge$\n"
        f"{body.rstrip()};\n$knowledge$"
    )


def guard_functions():
    values = [
        (
            "reject_knowledge_mutation",
            "",
            "BEGIN RAISE EXCEPTION 'Knowledge facts and assessment history are immutable' USING ERRCODE='23514'; END",
            "trigger",
        )
    ]
    for table, (version, identity) in CURRENT_FACTS.items():
        stem = "knowledge_candidate" if table == CANDIDATE_CURRENT else "knowledge_rule"
        values.extend(
            (
                (f"protect_{stem}_current", "", current_guard(table, version), "trigger"),
                (f"require_{stem}_current", "", current_atom(table, version, identity), "trigger"),
            )
        )
    return tuple(values)


def functions(*, atom_bodies: Mapping[str, str] | None = None):
    atom_bodies = ATOM_BODIES if atom_bodies is None else atom_bodies
    if set(atom_bodies) != set(ATOM_NAMES):
        raise ValueError(
            "Actual candidate, rule and reciprocal assessment atom bodies are required"
        )
    values = [*guard_functions(), *SUPPORT_FUNCTIONS]
    for name in ATOM_NAMES:
        body = atom_bodies[name]
        if not isinstance(body, str) or not body.strip() or "BEGIN" not in body:
            raise ValueError(f"Actual domain atom is not implemented: {name}")
        values.append((name, "t uuid,target uuid", body, "void"))
        stem = name.removeprefix("assert_")
        values.append(
            (
                f"require_{stem}",
                "",
                f"BEGIN PERFORM public.{name}(NEW.tenant_id,NEW.id); RETURN NULL; END",
                "trigger",
            )
        )
    return tuple(values)


def function_sql(*, atom_bodies: Mapping[str, str] | None = None):
    return tuple(_function(*value) for value in functions(atom_bodies=atom_bodies))


def signatures(*, atom_bodies: Mapping[str, str] | None = None):
    return tuple(
        name + "(" + ",".join(part.split()[-1] for part in args.split(",") if part) + ")"
        for name, args, _body, _returns in functions(atom_bodies=atom_bodies)
    )


def trigger_sql():
    statements = []
    for table, stem in (
        (CANDIDATE, "knowledge_candidate"),
        (RULE, "knowledge_rule"),
        (ASSESSMENT, "knowledge_assessment"),
    ):
        statements.extend(
            (
                f"CREATE TRIGGER {stem}_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.reject_knowledge_mutation()",
                f"CREATE CONSTRAINT TRIGGER {stem}_atom AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}()",
            )
        )
    for table in CURRENT_FACTS:
        stem = "knowledge_candidate" if table == CANDIDATE_CURRENT else "knowledge_rule"
        statements.extend(
            (
                f"CREATE TRIGGER {stem}_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.protect_{stem}_current()",
                f"CREATE CONSTRAINT TRIGGER {stem}_current_atom AFTER INSERT OR UPDATE ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{stem}_current()",
            )
        )
    return tuple(statements)


def drop_cycle_sql():
    return tuple(
        str(DropConstraint(constraint).compile(dialect=postgresql.dialect()))
        for constraint in reversed(cycle_constraints())
    )


MEMBERS_ATOM = r"""
DECLARE v record; receipt public.action_receipts; proof public.confirmations;
 expected jsonb; event_name text;
BEGIN
 IF kind='knowledge_candidate' THEN
  SELECT * INTO STRICT v FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;
  expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','draft','candidate_id',v.candidate_id,'project_id',v.project_id);
  event_name='knowledge.candidate_created';
 ELSIF kind='design_rule' THEN
  SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;
  expected=jsonb_build_object('id',v.id,'revision',v.revision,'status','published','rule_id',v.rule_id,'project_id',v.project_id,'assessment_id',v.assessment_id);
  event_name='knowledge.rule_published';
 ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT receipt FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 IF ROW(receipt.category_id,receipt.product_id,receipt.command_id,receipt.confirmation_id,receipt.actor_id,receipt.requester_id,receipt.operation,receipt.subject_type,receipt.subject_id,receipt.subject_revision,receipt.visibility,receipt.request_digest,receipt.intent_digest)
  IS DISTINCT FROM ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)
  OR receipt.result IS DISTINCT FROM expected OR receipt.created_at<v.created_at
  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1
  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND x.operation=v.operation AND x.created_at>=v.created_at)
  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1
  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND x.type=event_name AND x.subject_id=v.id AND x.subject_revision=v.revision AND x.schema_version=1 AND x.correlation_id=coalesce(receipt.agent_run_id,receipt.run_id,v.command_id) AND x.created_at>=v.created_at)
  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'
  OR v.command->'envelope' ? 'idempotency_key'
  OR v.command->'envelope'->'payload' ? 'confirmation_token' OR v.command->'envelope'->'payload' ? 'approval_token'
  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Knowledge original receipt audit event or request mismatch' USING ERRCODE='23514'; END IF;
 IF kind='design_rule' THEN
  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF proof.consumed IS DISTINCT FROM true
   OR ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)
    IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation,'product'::varchar,v.product_id,(v.command->'envelope'->>'expected_revision')::integer)
   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at
   OR (proof.expires_at IS NOT NULL AND (v.created_at>=proof.expires_at OR receipt.created_at>=proof.expires_at))
   OR receipt.run_id IS NOT NULL OR receipt.agent_run_id IS NOT NULL
   OR v.actor_id<>v.requester_id THEN
   RAISE EXCEPTION 'Knowledge rule requires the actual named consumed T2 proof' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

COMMON_ATOM = r"""
DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb;
BEGIN
 IF kind='knowledge_candidate' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.knowledge_candidate_versions x WHERE x.tenant_id=t AND x.id=target;
 ELSIF kind='design_rule' THEN
  SELECT x.*,x.xmin AS tx INTO STRICT v FROM public.knowledge_rule_versions x WHERE x.tenant_id=t AND x.id=target;
 ELSE RAISE EXCEPTION 'Unknown knowledge subject' USING ERRCODE='23514'; END IF;
 vx=v.tx;
 SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;
 PERFORM public.assert_knowledge_members(t,target,kind);
 envelope=v.command->'envelope';
 IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM public.scope_requester()
  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT public.category_access(t,v.category_id,true)
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND h.active)
  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' AND h.active)
  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM v.command_id::text
  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS DISTINCT FROM v.product_id::text
  OR envelope->'payload'->>'project_id' IS DISTINCT FROM v.project_id::text
  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'
  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation
  OR v.command->'review'->'sources' IS DISTINCT FROM v.sources
  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis
  OR v.body IS DISTINCT FROM v.command->'review'->'after'
  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))
  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.category_id=v.category_id AND p.id=v.product_id AND p.revision::text=envelope->>'expected_revision'))
  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))
  OR NOT COALESCE(envelope->'source_read_set' @> v.reads,false) OR NOT COALESCE(v.reads @> (envelope->'source_read_set'),false)
  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)
  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)
  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)
  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)
  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))
  OR (kind='design_rule' AND (v.actor_id<>v.requester_id OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND h.kind='human' AND h.active)))
  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS DISTINCT FROM vx)
  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN
  RAISE EXCEPTION 'Knowledge requires actual scope actor sources and one common transaction' USING ERRCODE='23514'; END IF;
 IF v.confirmation_id IS NOT NULL THEN
  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;
  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Knowledge T2 proof consumption must share its new rule transaction' USING ERRCODE='23514'; END IF;
 END IF;
 FOR ref IN SELECT value FROM jsonb_array_elements(v.reads) LOOP
  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=v.category_id
   AND a.id::text=ref->>'artifact_id' AND a.revision::text=ref->>'expected_revision' AND a.status='active'
   AND (a.original_id IS NULL OR EXISTS(SELECT 1 FROM public.uploaded_originals o JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id
    WHERE o.tenant_id=t AND o.category_id=v.category_id AND o.id=a.original_id AND o.status='parsed' AND sec.source_state='active' AND sec.disposition='active'))) THEN
   RAISE EXCEPTION 'Knowledge content or authority original is no longer current' USING ERRCODE='23514'; END IF;
 END LOOP;
__ACTUAL_CONTENT_SOURCE_CHECKS__
END
"""

# Reuse only the proven direct-content loop declarations; no shared work guard is
# replaced, invoked or granted additional subjects by this knowledge domain.
from pdos_next.domain.work_management import storage_schema as _work_sources  # noqa: E402

_SOURCE_START = " IF jsonb_typeof(v.source_basis->'artifacts')"
_content_checks = _work_sources.WRITE_ATOM.split(_SOURCE_START, 1)[1].rsplit("\nEND", 1)[0]
_content_checks = _content_checks.replace(
    "AND (a.product_id IS NULL OR a.product_id=v.product_id) AND a.id::text=basis->>'id'",
    "AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'",
    1,
)
_content_checks = _content_checks.replace(
    "(v.visibility='private' OR a.visibility<>'private')",
    "(v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM public.products source_product WHERE source_product.tenant_id=t AND source_product.category_id=v.category_id AND source_product.id=a.product_id AND source_product.visibility='category'))))",
).replace(
    "(v.visibility='private' OR o.visibility<>'private')",
    "(v.visibility='private' OR o.visibility='category')",
)
COMMON_ATOM = COMMON_ATOM.replace(
    "__ACTUAL_CONTENT_SOURCE_CHECKS__", _SOURCE_START + _content_checks
)

CANDIDATE_ATOM = r"""
DECLARE v public.knowledge_candidate_versions; prior public.knowledge_candidate_versions;
 cur public.knowledge_candidate_currents; payload jsonb; expected jsonb; vx xid; cx xid;
BEGIN
 SELECT * INTO STRICT v FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=target;
 PERFORM public.assert_knowledge_common(t,target,'knowledge_candidate');
 SELECT * INTO STRICT cur FROM public.knowledge_candidate_currents WHERE tenant_id=t AND category_id=v.category_id AND candidate_id=v.candidate_id;
 SELECT xmin INTO cx FROM public.knowledge_candidate_currents WHERE tenant_id=t AND id=cur.id;
 payload=v.command->'envelope'->'payload';
 expected=jsonb_build_object('candidate_id',v.candidate_id,'revision',v.revision,'title',payload->'title',
  'lesson',payload->'lesson','evidence_summary',payload->'evidence_summary',
  'applicability_hypothesis',payload->'applicability_hypothesis','result_receipts',payload->'result_receipts');
 IF vx IS DISTINCT FROM cx OR v.body IS DISTINCT FROM expected
  OR payload->>'visibility' IS DISTINCT FROM v.visibility
  OR v.owner_id<>v.requester_id
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.candidate_id,cur.version_id,cur.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id,v.id,v.revision) THEN
  RAISE EXCEPTION 'Knowledge candidate requires exact declared content and same-transaction Current' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  IF coalesce(payload->'candidate','null'::jsonb)<>'null'::jsonb
   OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb
   OR v.owner_id<>v.requester_id THEN
   RAISE EXCEPTION 'First knowledge candidate binds its actual requester and declared category scope' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT prior FROM public.knowledge_candidate_versions WHERE tenant_id=t AND id=v.previous_id;
  IF payload->'candidate' IS DISTINCT FROM jsonb_build_object('id',v.candidate_id,'revision',v.previous_revision)
   OR v.command->'review'->'before' IS DISTINCT FROM prior.body
   OR ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.candidate_id)
    IS DISTINCT FROM ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.candidate_id) THEN
   RAISE EXCEPTION 'Knowledge candidate continuation cannot replace its fixed scope or predecessor' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM public.principals actor WHERE actor.tenant_id=t AND actor.id=v.actor_id AND actor.kind='agent')
   AND (prior.actor_id<>v.actor_id OR NOT EXISTS(SELECT 1 FROM public.principals author WHERE author.tenant_id=t AND author.id=prior.actor_id AND author.kind='agent')
    OR EXISTS(SELECT 1 FROM public.knowledge_rule_versions consumed WHERE consumed.tenant_id=t AND consumed.category_id=v.category_id AND consumed.candidate_id=v.candidate_id)) THEN
   RAISE EXCEPTION 'AI may continue only its own unpublished candidate lineage without overwriting human content' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

PROFESSIONAL_ATOM = r"""
DECLARE v public.knowledge_rule_versions; authority jsonb; reference jsonb;
 fact public.professional_authority_facts; pointer public.professional_authority_current;
 has_duty boolean=false; has_qualification boolean=false;
BEGIN
 SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;
 authority=v.source_basis->'professional';
 IF jsonb_typeof(authority) IS DISTINCT FROM 'object'
  OR authority->'scope' IS DISTINCT FROM jsonb_build_object('tenant_id',t,'product_id',v.product_id,'project_id',v.project_id)
  OR authority->>'subject_id' IS DISTINCT FROM v.actor_id::text
  OR authority->>'operation' IS DISTINCT FROM v.operation
  OR authority->>'purpose' IS DISTINCT FROM v.body->'applicability'->>'purpose'
  OR authority->'authorized' IS DISTINCT FROM 'true'::jsonb OR authority->'qualified' IS DISTINCT FROM 'true'::jsonb
  OR authority->'roles' IS DISTINCT FROM '["knowledge"]'::jsonb
  OR jsonb_typeof(authority->'fact_refs') IS DISTINCT FROM 'array'
  OR jsonb_array_length(authority->'fact_refs')=0
  OR v.nature IS DISTINCT FROM (CASE WHEN authority->'synthetic'='true'::jsonb THEN 'synthetic' ELSE 'real' END) THEN
  RAISE EXCEPTION 'Knowledge publication requires its own actual named authority scope' USING ERRCODE='23514'; END IF;
 FOR reference IN SELECT value FROM jsonb_array_elements(authority->'fact_refs') LOOP
  SELECT * INTO fact FROM public.professional_authority_facts f WHERE f.tenant_id=t AND f.product_id=v.product_id AND f.project_id=v.project_id
   AND f.subject_id=v.actor_id AND f.id::text=reference->>'id' AND f.revision::text=reference->>'revision';
  IF NOT FOUND THEN RAISE EXCEPTION 'Knowledge authority cannot be invented from a snapshot' USING ERRCODE='23514'; END IF;
  SELECT * INTO pointer FROM public.professional_authority_current p WHERE p.tenant_id=t AND p.product_id=v.product_id AND p.project_id=v.project_id
   AND p.subject_id=v.actor_id AND p.fact_id=fact.id AND p.fact_revision=fact.revision AND p.series_id=fact.series_id AND p.epoch::text=reference->>'epoch';
  IF NOT FOUND OR fact.fact_sha256 IS DISTINCT FROM reference->>'fact_sha256'
   OR fact.series_id::text IS DISTINCT FROM reference->>'series_id'
   OR fact.kind IS DISTINCT FROM reference->>'kind' OR fact.role IS DISTINCT FROM reference->>'role'
   OR fact.nature IS DISTINCT FROM reference->>'nature' OR fact.state IS DISTINCT FROM reference->>'state'
   OR fact.issuer_key IS DISTINCT FROM reference->>'issuer_key' OR fact.issuer_version IS DISTINCT FROM reference->>'issuer_version'
   OR fact.operations IS DISTINCT FROM reference->'operations' OR fact.purposes IS DISTINCT FROM reference->'purposes'
   OR NOT coalesce(v.reads @> fact.required_source_read_set,false) THEN
   RAISE EXCEPTION 'Knowledge authority snapshot must bind actual current duty and qualification facts' USING ERRCODE='23514'; END IF;
  IF fact.role='knowledge' AND fact.state='active' AND fact.valid_from<=v.created_at AND v.created_at<fact.valid_until
   AND fact.operations @> jsonb_build_array(v.operation) AND fact.purposes @> jsonb_build_array(v.body->'applicability'->>'purpose') THEN
   IF fact.kind='duty' THEN has_duty=true; ELSIF fact.kind='qualification' THEN has_qualification=true; END IF;
  END IF;
 END LOOP;
 IF NOT has_duty OR NOT has_qualification THEN
  RAISE EXCEPTION 'Prior engineering quality or manufacturing roles do not grant knowledge publication' USING ERRCODE='23514'; END IF;
END
"""

RULE_ATOM = r"""
DECLARE v public.knowledge_rule_versions; prior public.knowledge_rule_versions;
 cur public.knowledge_rule_currents; candidate public.knowledge_candidate_versions;
 candidate_current public.knowledge_candidate_currents; assessment public.knowledge_applicability_assessments;
 payload jsonb; expected jsonb; applicability jsonb; expected_assessment jsonb; vx xid; cx xid; ax xid;
BEGIN
 SELECT * INTO STRICT v FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;
 SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=target;
 PERFORM public.assert_knowledge_common(t,target,'design_rule');
 PERFORM public.assert_knowledge_professional(t,target);
 SELECT * INTO STRICT cur FROM public.knowledge_rule_currents WHERE tenant_id=t AND category_id=v.category_id AND rule_id=v.rule_id;
 SELECT xmin INTO cx FROM public.knowledge_rule_currents WHERE tenant_id=t AND id=cur.id;
 SELECT * INTO STRICT candidate FROM public.knowledge_candidate_versions WHERE tenant_id=t AND category_id=v.category_id AND id=v.candidate_version_id;
 SELECT * INTO STRICT candidate_current FROM public.knowledge_candidate_currents WHERE tenant_id=t AND category_id=v.category_id AND candidate_id=v.candidate_id;
 SELECT * INTO STRICT assessment FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND id=v.assessment_id;
 SELECT xmin INTO ax FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND id=v.assessment_id;
 payload=v.command->'envelope'->'payload'; applicability=payload->'applicability';
 expected_assessment=applicability||jsonb_build_object('candidate_version',jsonb_build_object('id',candidate.id,'revision',candidate.revision),
  'assessor_id',v.actor_id,'withdrawal_reason',NULL);
 expected=jsonb_build_object('rule_id',v.rule_id,'revision',v.revision,'candidate',jsonb_build_object('id',v.candidate_id,'revision',v.candidate_revision),
  'candidate_version_id',v.candidate_version_id,'assessment_id',v.assessment_id,'title',payload->'title','rule_text',payload->'rule_text',
  'applicability',assessment.body,'nature',v.nature);
 IF vx IS DISTINCT FROM cx OR vx IS DISTINCT FROM ax
  OR ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.rule_id,cur.version_id,cur.revision)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id,v.id,v.revision)
  OR candidate.candidate_id<>v.candidate_id OR candidate.revision<>v.candidate_revision
  OR (candidate.visibility='private' AND (v.visibility<>'private' OR candidate.owner_id<>v.owner_id))
  OR candidate_current.version_id<>candidate.id OR candidate_current.revision<>candidate.revision
  OR v.source_basis->'candidate' IS DISTINCT FROM jsonb_build_object('id',candidate.id,'revision',candidate.revision,'body_sha256',candidate.body_sha256)
  OR payload->'candidate' IS DISTINCT FROM jsonb_build_object('id',candidate.candidate_id,'revision',candidate.revision)
  OR assessment.body IS DISTINCT FROM expected_assessment OR v.body IS DISTINCT FROM expected
  OR ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.publication_id,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)
   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.id,v.candidate_version_id,v.candidate_revision,v.actor_id,v.receipt_id)
  OR assessment.body->>'decision' IS DISTINCT FROM 'applicable'
  OR (assessment.body->>'valid_from')::timestamptz IS DISTINCT FROM v.valid_from
  OR (assessment.body->>'valid_until')::timestamptz IS DISTINCT FROM v.valid_until THEN
  RAISE EXCEPTION 'Knowledge publication binds exact candidate assessment authority and one atomic group' USING ERRCODE='23514'; END IF;
 IF applicability->'target'->>'kind'='engineering_configuration' THEN
  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations target WHERE target.tenant_id=t AND target.category_id=v.category_id AND target.product_id=v.product_id
   AND target.id::text=applicability->'target'->>'id' AND target.revision::text=applicability->'target'->>'revision'
   AND v.source_basis->'target'=jsonb_build_object('kind','engineering_configuration','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)
   AND coalesce(v.reads @> target.required_source_read_set,false)
   AND EXISTS(SELECT 1 FROM public.project_product_links link WHERE link.tenant_id=t AND link.category_id=v.category_id AND link.product_id=v.product_id AND link.project_id=v.project_id AND link.definition_id=target.definition_id AND link.definition_revision=target.definition_revision)
   AND (target.visibility='category' OR target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM public.object_audiences audience WHERE audience.tenant_id=t AND audience.category_id=v.category_id AND audience.object_type='engineering_configurations' AND audience.subject_id=target.id AND audience.owner_id=target.owner_id AND audience.principal_id=public.scope_requester()))
   AND (v.visibility='private' OR target.visibility='category')) THEN
   RAISE EXCEPTION 'Knowledge target must be an actual readable fixed engineering configuration' USING ERRCODE='23514'; END IF;
 ELSIF applicability->'target'->>'kind'='process_revision' THEN
  IF NOT EXISTS(SELECT 1 FROM public.process_revisions target WHERE target.tenant_id=t AND target.category_id=v.category_id AND target.product_id=v.product_id
   AND target.id::text=applicability->'target'->>'id' AND target.revision::text=applicability->'target'->>'revision'
   AND v.source_basis->'target'=jsonb_build_object('kind','process_revision','id',target.id,'revision',target.revision,'product_id',target.product_id,'owner_id',target.owner_id,'visibility',target.visibility,'sources',target.sources,'required_source_read_set',target.required_source_read_set)
   AND coalesce(v.reads @> target.required_source_read_set,false)
   AND EXISTS(SELECT 1 FROM public.engineering_configurations engineering JOIN public.project_product_links link ON link.tenant_id=engineering.tenant_id AND link.category_id=engineering.category_id AND link.product_id=engineering.product_id AND link.definition_id=engineering.definition_id AND link.definition_revision=engineering.definition_revision
    WHERE engineering.tenant_id=t AND engineering.category_id=v.category_id AND engineering.product_id=v.product_id AND engineering.id=target.engineering_configuration_id AND engineering.revision=target.engineering_revision AND link.project_id=v.project_id)
   AND (target.visibility='category' OR target.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM public.object_audiences audience WHERE audience.tenant_id=t AND audience.category_id=v.category_id AND audience.object_type='process_revisions' AND audience.subject_id=target.id AND audience.owner_id=target.owner_id AND audience.principal_id=public.scope_requester()))
   AND (v.visibility='private' OR target.visibility='category')) THEN
   RAISE EXCEPTION 'Knowledge target must be an actual readable fixed manufacturing configuration' USING ERRCODE='23514'; END IF;
 ELSE RAISE EXCEPTION 'Knowledge target configuration kind is not registered' USING ERRCODE='23514'; END IF;
 IF v.revision=1 THEN
  IF coalesce(payload->'rule','null'::jsonb)<>'null'::jsonb
   OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb OR v.owner_id<>v.requester_id THEN
   RAISE EXCEPTION 'First published rule binds the actual named publisher' USING ERRCODE='23514'; END IF;
 ELSE
  SELECT * INTO STRICT prior FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=v.previous_id;
  IF payload->'rule' IS DISTINCT FROM jsonb_build_object('id',v.rule_id,'revision',v.previous_revision)
   OR v.command->'review'->'before' IS DISTINCT FROM prior.body
   OR ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.rule_id)
    IS DISTINCT FROM ROW(prior.category_id,prior.product_id,prior.project_id,prior.owner_id,prior.visibility,prior.rule_id) THEN
   RAISE EXCEPTION 'Published rule continuation cannot replace fixed scope or its original predecessor' USING ERRCODE='23514'; END IF;
 END IF;
END
"""

ASSESSMENT_ATOM = r"""
DECLARE assessment public.knowledge_applicability_assessments; publication public.knowledge_rule_versions; ax xid; vx xid;
BEGIN
 SELECT * INTO STRICT assessment FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND id=target;
 SELECT xmin INTO ax FROM public.knowledge_applicability_assessments WHERE tenant_id=t AND id=target;
 SELECT * INTO STRICT publication FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=assessment.publication_id;
 SELECT xmin INTO vx FROM public.knowledge_rule_versions WHERE tenant_id=t AND id=assessment.publication_id;
 IF ax IS DISTINCT FROM vx OR publication.assessment_id<>assessment.id
  OR assessment.body IS DISTINCT FROM publication.body->'applicability'
  OR ROW(assessment.category_id,assessment.product_id,assessment.project_id,assessment.owner_id,assessment.visibility,assessment.candidate_version_id,assessment.candidate_revision,assessment.actor_id,assessment.receipt_id)
   IS DISTINCT FROM ROW(publication.category_id,publication.product_id,publication.project_id,publication.owner_id,publication.visibility,publication.candidate_version_id,publication.candidate_revision,publication.actor_id,publication.receipt_id) THEN
  RAISE EXCEPTION 'Applicability assessment exists only as its one actual T2 publication child' USING ERRCODE='23514'; END IF;
END
"""


RECEIPT_GUARD = r"""
DECLARE scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN scoped=OLD.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR OLD.subject_type IN ('knowledge_candidate','design_rule'); END IF;
 IF TG_OP<>'DELETE' THEN scoped=scoped OR NEW.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR NEW.subject_type IN ('knowledge_candidate','design_rule'); END IF;
 IF scoped AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge receipt history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""
MEMBER_GUARD = r"""
DECLARE scoped boolean=false; old_scoped boolean=false;
BEGIN
 IF TG_OP<>'DELETE' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.receipt_id AND (r.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR r.subject_type IN ('knowledge_candidate','design_rule'))) INTO scoped; END IF;
 IF TG_OP<>'INSERT' THEN SELECT EXISTS(SELECT 1 FROM public.action_receipts r WHERE r.tenant_id=OLD.tenant_id AND r.id=OLD.receipt_id AND (r.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR r.subject_type IN ('knowledge_candidate','design_rule'))) INTO old_scoped; END IF;
 IF TG_OP<>'INSERT' AND (scoped OR old_scoped) THEN
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='outbox_events' AND (to_jsonb(NEW)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) IS NOT DISTINCT FROM (to_jsonb(OLD)-ARRAY['delivered_at','lease_id','lease_until','attempts','last_error']) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Knowledge original audit event or request key is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""
MEMBER_TARGET = r"""
DECLARE receipt public.action_receipts;
BEGIN
 IF TG_TABLE_NAME='action_receipts' THEN receipt=NEW; ELSE SELECT * INTO receipt FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id; END IF;
 IF receipt.operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR receipt.subject_type IN ('knowledge_candidate','design_rule') THEN
  PERFORM public.assert_knowledge_members(receipt.tenant_id,receipt.subject_id,receipt.subject_type::text); END IF;
 RETURN NULL;
END
"""
CONFIRMATION_GUARD = r"""
DECLARE old_scoped boolean=false; new_scoped boolean=false;
BEGIN
 IF TG_OP<>'INSERT' THEN old_scoped=OLD.operation='knowledge.rule.publish'; END IF;
 IF TG_OP<>'DELETE' THEN new_scoped=NEW.operation='knowledge.rule.publish'; END IF;
 IF old_scoped OR new_scoped THEN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Knowledge publication confirmation history retained' USING ERRCODE='23514';
  ELSIF TG_OP='INSERT' THEN
   IF NEW.consumed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Knowledge publication proof starts unconsumed' USING ERRCODE='23514'; END IF;
  ELSIF NOT(old_scoped AND new_scoped) OR OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (to_jsonb(NEW)-'consumed') IS DISTINCT FROM (to_jsonb(OLD)-'consumed') THEN
   RAISE EXCEPTION 'Knowledge publication proof consumes only its original false to true' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END
"""
CONFIRMATION_TARGET = r"""
BEGIN
 IF NEW.operation='knowledge.rule.publish' THEN
  IF OLD.consumed IS DISTINCT FROM false OR NEW.consumed IS DISTINCT FROM true
   OR (SELECT count(*) FROM public.knowledge_rule_versions v WHERE v.tenant_id=NEW.tenant_id AND v.confirmation_id=NEW.id AND v.operation=NEW.operation)<>1 THEN
   RAISE EXCEPTION 'Consumed knowledge T2 proof needs exactly one new publication' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END
"""

ATOM_BODIES = {
    "assert_knowledge_candidate": CANDIDATE_ATOM,
    "assert_knowledge_rule": RULE_ATOM,
    "assert_knowledge_assessment": ASSESSMENT_ATOM,
}
SUPPORT_FUNCTIONS = (
    ("assert_knowledge_members", "t uuid,target uuid,kind text", MEMBERS_ATOM, "void"),
    ("assert_knowledge_common", "t uuid,target uuid,kind text", COMMON_ATOM, "void"),
    ("assert_knowledge_professional", "t uuid,target uuid", PROFESSIONAL_ATOM, "void"),
    ("protect_knowledge_receipt", "", RECEIPT_GUARD, "trigger"),
    ("protect_knowledge_member", "", MEMBER_GUARD, "trigger"),
    ("require_knowledge_member", "", MEMBER_TARGET, "trigger"),
    ("protect_knowledge_confirmation", "", CONFIRMATION_GUARD, "trigger"),
    ("require_knowledge_confirmation", "", CONFIRMATION_TARGET, "trigger"),
)


def common_trigger_sql():
    values = [
        "CREATE TRIGGER protect_knowledge_receipt BEFORE INSERT OR UPDATE OR DELETE ON public.action_receipts FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_receipt()",
        "CREATE TRIGGER protect_knowledge_confirmation BEFORE INSERT OR UPDATE OR DELETE ON public.confirmations FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_confirmation()",
        "CREATE CONSTRAINT TRIGGER require_knowledge_confirmation AFTER UPDATE ON public.confirmations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_confirmation()",
    ]
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        if table != "action_receipts":
            values.append(
                f"CREATE TRIGGER protect_knowledge_member BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.protect_knowledge_member()"
            )
        values.append(
            f"CREATE CONSTRAINT TRIGGER require_knowledge_member AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_member()"
        )
    return tuple(values)


def upgrade_sql():
    """Root installs actual content/result ACL helpers before these policies."""
    return (
        *table_sql(),
        *function_sql(),
        *(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            for signature in signatures()
        ),
        *policy_sql(),
        *trigger_sql(),
        *common_trigger_sql(),
    )


def downgrade_sql():
    statements = [
        "LOCK TABLE "
        + ",".join(f"public.{table.name}" for table in TABLES)
        + ",public.action_receipts,public.confirmations IN ACCESS EXCLUSIVE MODE",
        "DO $knowledge$ BEGIN IF "
        + " OR ".join(f"EXISTS(SELECT 1 FROM public.{table.name})" for table in TABLES)
        + " OR EXISTS(SELECT 1 FROM public.action_receipts WHERE operation IN ('knowledge.candidate.create','knowledge.rule.publish') OR subject_type IN ('knowledge_candidate','design_rule')) "
        + "OR EXISTS(SELECT 1 FROM public.confirmations WHERE operation='knowledge.rule.publish') "
        + "THEN RAISE EXCEPTION 'Knowledge history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $knowledge$",
        "DROP TRIGGER protect_knowledge_receipt ON public.action_receipts",
        "DROP TRIGGER protect_knowledge_confirmation ON public.confirmations",
        "DROP TRIGGER require_knowledge_confirmation ON public.confirmations",
    ]
    for table in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
        if table != "action_receipts":
            statements.append(f"DROP TRIGGER protect_knowledge_member ON public.{table}")
        statements.append(f"DROP TRIGGER require_knowledge_member ON public.{table}")
    statements.extend(drop_cycle_sql())
    statements.extend(
        f"DROP TABLE public.{name}"
        for name in (RULE_CURRENT, ASSESSMENT, RULE, CANDIDATE_CURRENT, CANDIDATE)
    )
    statements.extend(f"DROP FUNCTION public.{signature}" for signature in reversed(signatures()))
    return tuple(statements)
