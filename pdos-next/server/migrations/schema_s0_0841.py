"""Fixed personal answer origins retain explicit target-category provenance."""

SCHEMA_SQL = (
    (
        'CREATE OR REPLACE FUNCTION public.assert_knowledge_assistant_fact() RETURNS trigger LA'
        'NGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledg'
        'e_assistant$\n\nDECLARE subject jsonb; sx xid; rx xid; nx xid; receipt public.action_r'
        'eceipts; origin public.agent_runs;\n category public.categories; actual_owner uuid; fi'
        "eld_name text;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge contributio"
        "n facts are append-only' USING ERRCODE='23514'; END IF;\n IF NEW.tenant_id IS DISTINCT"
        " FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n OR public.scope_actor("
        ') IS DISTINCT FROM public.scope_requester()\n OR NOT EXISTS(SELECT 1 FROM public.princ'
        'ipals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() AND h.active AND'
        " h.kind='human')\n OR NOT public.category_access(NEW.tenant_id,NEW.category_id,false) "
        "THEN\n  RAISE EXCEPTION 'Only the actual authorized Human may append knowledge contrib"
        "utions' USING ERRCODE='42501'; END IF;\n SELECT * INTO STRICT category FROM public.cat"
        "egories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;\n IF TG_TABLE_NAME='know"
        "ledge_answer_reviews' THEN\n  IF NOT public.category_access(NEW.tenant_id,NEW.category"
        "_id,true) THEN\n   RAISE EXCEPTION 'Knowledge review uses its native category write au"
        "thority' USING ERRCODE='42501'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM public.principa"
        'ls p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id\n   WHERE'
        " p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='human' AND p.active"
        '\n   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expires_at>trans'
        "action_timestamp())) THEN\n   RAISE EXCEPTION 'Review responsible person must be an ac"
        "tive actual category reader' USING ERRCODE='23514'; END IF;\n  EXECUTE format('SELECT "
        "to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND id=$3',\n "
        "  CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entries' WHEN 'candid"
        "ate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_rule_versions' EN"
        'D)\n   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.subject_id;\n  S'
        'ELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenant_id=NEW.tenant'
        '_id AND r.id=NEW.receipt_id;\n  SELECT xmin INTO rx FROM public.action_receipts WHERE '
        'tenant_id=NEW.tenant_id AND id=NEW.receipt_id;\n  SELECT xmin INTO nx FROM public.know'
        'ledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n  IF sx IS DISTINCT'
        " FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINCT FROM NEW.rece"
        'ipt_id::text\n   OR receipt.command_id<>NEW.command_id OR receipt.actor_id<>public.sco'
        'pe_actor()\n   OR receipt.requester_id<>public.scope_requester()\n   OR (NEW.verified_'
        'by IS NOT NULL AND NEW.verified_by<>public.scope_requester())\n   OR (NEW.subject_kind'
        "='candidate' AND NEW.verified_by IS NOT NULL)\n   OR (NEW.subject_kind='rule' AND (rec"
        "eipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS NULL OR NEW.ver"
        "ified_by IS NULL)) THEN\n   RAISE EXCEPTION 'Review must share its real native version"
        " and Human receipt transaction' USING ERRCODE='23514'; END IF;\n  IF NEW.source_proof "
        "IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'\n      THEN subject->'answer_s"
        "ources' ELSE subject#>'{source_basis,answer_sources}' END) THEN\n   RAISE EXCEPTION 'N"
        "ative proof and review must be identical' USING ERRCODE='23514'; END IF;\n  IF EXISTS("
        "SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'source_type'='kn"
        "owledge' AND (\n    EXISTS(SELECT 1 FROM public.category_knowledge_entries k WHERE k.t"
        "enant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND coalesce(jsonb_arra"
        'y_length(k.answer_sources),0)>0)\n    OR EXISTS(SELECT 1 FROM public.knowledge_rule_ve'
        "rsions k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND c"
        "oalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) THEN\n   RAISE EX"
        "CEPTION 'Reviewed knowledge proofs must flatten existing answer-derived parents' USING"
        " ERRCODE='23514'; END IF;\n  IF NEW.origin_run_id IS NOT NULL THEN\n   SELECT * INTO S"
        'TRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND (category_id=NEW'
        '.category_id OR category_id IS NULL) AND id=NEW.origin_run_id;\n   IF origin.state NOT'
        " IN ('completed','partial') OR origin.reverted_at IS NOT NULL\n    OR NOT public.knowl"
        'edge_answer_sources_known(NEW.origin_run_id,NEW.source_proof) THEN\n    RAISE EXCEPTIO'
        "N 'Answer origin is not an actual retained completed answer' USING ERRCODE='23514'; EN"
        'D IF;\n   IF origin.requester_id<>public.scope_requester() AND NOT EXISTS(\n    SELECT'
        ' 1 FROM public.knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tenant_id\n   '
        ' AND prior.origin_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answer_digest\n'
        "    AND prior.source_proof=NEW.source_proof AND (\n     (NEW.subject_kind='rule' AND p"
        "rior.subject_id::text=subject->>'candidate_version_id')\n     OR (NEW.subject_kind='ca"
        "ndidate' AND prior.subject_id::text=subject->>'previous_id')\n     OR (NEW.subject_kin"
        "d='category' AND EXISTS(SELECT 1 FROM public.category_knowledge_entries p\n         WH"
        "ERE p.id=prior.subject_id AND p.lineage_id::text=subject->>'lineage_id'\n         AND "
        "p.version<(subject->>'version')::integer)))) THEN\n    RAISE EXCEPTION 'A new answer o"
        "rigin must belong to the actual Human; inherited native evidence stays fixed' USING ER"
        "RCODE='23514'; END IF;\n  END IF;\n ELSE\n  IF TG_TABLE_NAME='knowledge_gap_submission"
        "s' THEN\n   IF NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>category.ow"
        "ner_id THEN\n    RAISE EXCEPTION 'Gap sharing binds the actual owner and current categ"
        "ory recipient' USING ERRCODE='23514'; END IF;\n   SELECT * INTO STRICT origin FROM pub"
        'lic.agent_runs WHERE tenant_id=NEW.tenant_id AND (category_id=NEW.category_id OR categ'
        'ory_id IS NULL) AND id=NEW.run_id;\n   IF origin.requester_id<>NEW.owner_id OR origin.'
        "state NOT IN ('completed','partial') OR origin.reverted_at IS NOT NULL\n    OR (NEW.ki"
        "nd='missing_material' AND (NEW.answer IS NOT NULL OR jsonb_array_length(NEW.source_pro"
        "of)<>0))\n    OR (NEW.kind='shared_feedback' AND NOT public.knowledge_answer_sources_k"
        "nown(NEW.run_id,NEW.source_proof))\n    OR (NEW.kind='shared_feedback' AND NOT EXISTS("
        'SELECT 1 FROM public.agent_run_events e\n        WHERE e.id=NEW.feedback_id AND e.tena'
        "nt_id=NEW.tenant_id AND e.run_id=NEW.run_id\n        AND e.body->>'type'='run_feedback"
        "' AND e.body->>'recorded_by'=NEW.owner_id::text)) THEN\n    RAISE EXCEPTION 'Only an a"
        "ctual explicit owner submission or actual private feedback may be shared' USING ERRCOD"
        "E='23514'; END IF;\n  ELSE\n   IF NEW.actor_id<>public.scope_requester() OR category.o"
        'wner_id<>NEW.actor_id\n    OR NOT EXISTS(SELECT 1 FROM public.knowledge_gap_submission'
        's g WHERE g.tenant_id=NEW.tenant_id AND g.category_id=NEW.category_id AND g.id=NEW.sub'
        "mission_id) THEN\n    RAISE EXCEPTION 'Only the current actual category owner may attr"
        "ibute a submitted gap' USING ERRCODE='42501'; END IF;\n  END IF;\n END IF;\n RETURN NU"
        'LL;\nEND\n\n$knowledge_assistant$'
    ),
    (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known(origin_id uuid,proof '
        'jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pu'
        'blic,pg_temp AS $knowledge_assistant$\n\nDECLARE valid boolean;\nBEGIN\n WITH RECURSIV'
        'E initial(value) AS (\n  SELECT value FROM public.agent_runs r,\n   LATERAL jsonb_arra'
        "y_elements(coalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) entry(value)"
        "\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true"
        "),'')::uuid\n  UNION ALL\n  SELECT jsonb_build_object('source_type','artifact','source"
        "_id',a.id,'source_revision',a.revision,\n   'content_hash',a.content_hash,'category_id"
        "',a.category_id)\n   FROM public.agent_runs r CROSS JOIN LATERAL jsonb_array_elements("
        'r.read_sources) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id=r.tenant'
        '_id AND (r.category_id IS NULL OR a.category_id=r.category_id)\n    AND a.id::text=ref'
        ".value->>'artifact_id' AND a.revision::text=ref.value->>'expected_revision'\n   WHERE "
        "r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
        "\n ), closure(value,seen) AS (\n  SELECT value,ARRAY[value->>'source_id'] FROM initial"
        "\n  UNION ALL\n  SELECT child.value,parent.seen||(child.value->>'source_id') FROM clos"
        'ure parent\n   JOIN public.knowledge_answer_reviews prior ON prior.subject_id::text=pa'
        "rent.value->>'source_id'\n     AND prior.tenant_id=nullif(current_setting('pdos.tenant"
        "_id',true),'')::uuid\n     AND parent.value->>'source_type'='knowledge'\n   CROSS JOIN"
        ' LATERAL jsonb_array_elements(prior.source_proof) child(value)\n   WHERE NOT (child.va'
        "lue->>'source_id'=ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_el"
        "ements(proof) p WHERE NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'source_t"
        "ype'=p->>'source_type'\n   AND c.value->>'source_id'=p->>'source_id'\n   AND c.value->"
        ">'source_revision'=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'content"
        "_hash'\n   AND c.value->>'category_id'=p->>'category_id')) INTO valid;\n RETURN jsonb_"
        "typeof(proof)='array' AND coalesce(valid,false);\nEND\n\n$knowledge_assistant$"
    ),
)

EMPTY_HISTORY_SQL = (
    (
        'DO $$ BEGIN IF EXISTS(\n SELECT 1 FROM public.knowledge_answer_reviews r JOIN public.a'
        'gent_runs origin\n ON origin.tenant_id=r.tenant_id AND origin.id=r.origin_run_id WHERE'
        ' origin.category_id IS NULL\n) OR EXISTS(\n SELECT 1 FROM public.knowledge_gap_submiss'
        'ions g JOIN public.agent_runs origin\n ON origin.tenant_id=g.tenant_id AND origin.id=g'
        ".run_id WHERE origin.category_id IS NULL\n) THEN RAISE EXCEPTION 'Cannot remove person"
        "al knowledge targets while recorded contributions remain';\nEND IF; END $$"
    ),
)

DOWNGRADE_SQL = (
    (
        'CREATE OR REPLACE FUNCTION public.assert_knowledge_assistant_fact()\n RETURNS trigger'
        "\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'p"
        "g_temp'\nAS $function$\n\nDECLARE subject jsonb; sx xid; rx xid; nx xid; receipt publi"
        'c.action_receipts; origin public.agent_runs;\n category public.categories; actual_owne'
        "r uuid; field_name text;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge c"
        "ontribution facts are append-only' USING ERRCODE='23514'; END IF;\n IF NEW.tenant_id I"
        "S DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n OR public.sc"
        'ope_actor() IS DISTINCT FROM public.scope_requester()\n OR NOT EXISTS(SELECT 1 FROM pu'
        'blic.principals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() AND h.'
        "active AND h.kind='human')\n OR NOT public.category_access(NEW.tenant_id,NEW.category_"
        "id,false) THEN\n  RAISE EXCEPTION 'Only the actual authorized Human may append knowled"
        "ge contributions' USING ERRCODE='42501'; END IF;\n SELECT * INTO STRICT category FROM "
        'public.categories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;\n IF TG_TABLE_'
        "NAME='knowledge_answer_reviews' THEN\n  IF NOT public.category_access(NEW.tenant_id,NE"
        "W.category_id,true) THEN\n   RAISE EXCEPTION 'Knowledge review uses its native categor"
        "y write authority' USING ERRCODE='42501'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM publi"
        'c.principals p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id'
        "\n   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='human' AN"
        'D p.active\n   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expire'
        "s_at>transaction_timestamp())) THEN\n   RAISE EXCEPTION 'Review responsible person mus"
        "t be an active actual category reader' USING ERRCODE='23514'; END IF;\n  EXECUTE forma"
        "t('SELECT to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND "
        "id=$3',\n   CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entries' WH"
        "EN 'candidate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_rule_ve"
        "rsions' END)\n   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.subjec"
        't_id;\n  SELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenant_id='
        'NEW.tenant_id AND r.id=NEW.receipt_id;\n  SELECT xmin INTO rx FROM public.action_recei'
        'pts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;\n  SELECT xmin INTO nx FROM p'
        'ublic.knowledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n  IF sx I'
        "S DISTINCT FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINCT FRO"
        'M NEW.receipt_id::text\n   OR receipt.command_id<>NEW.command_id OR receipt.actor_id<>'
        'public.scope_actor()\n   OR receipt.requester_id<>public.scope_requester()\n   OR (NEW'
        '.verified_by IS NOT NULL AND NEW.verified_by<>public.scope_requester())\n   OR (NEW.su'
        "bject_kind='candidate' AND NEW.verified_by IS NOT NULL)\n   OR (NEW.subject_kind='rule"
        "' AND (receipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS NULL "
        "OR NEW.verified_by IS NULL)) THEN\n   RAISE EXCEPTION 'Review must share its real nati"
        "ve version and Human receipt transaction' USING ERRCODE='23514'; END IF;\n  IF NEW.sou"
        "rce_proof IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'\n      THEN subject-"
        ">'answer_sources' ELSE subject#>'{source_basis,answer_sources}' END) THEN\n   RAISE EX"
        "CEPTION 'Native proof and review must be identical' USING ERRCODE='23514'; END IF;\n  "
        "IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'source"
        "_type'='knowledge' AND (\n    EXISTS(SELECT 1 FROM public.category_knowledge_entries k"
        " WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND coalesce("
        'jsonb_array_length(k.answer_sources),0)>0)\n    OR EXISTS(SELECT 1 FROM public.knowled'
        "ge_rule_versions k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source"
        "_id' AND coalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) THEN\n "
        "  RAISE EXCEPTION 'Reviewed knowledge proofs must flatten existing answer-derived pare"
        "nts' USING ERRCODE='23514'; END IF;\n  IF NEW.origin_run_id IS NOT NULL THEN\n   SELEC"
        'T * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND catego'
        "ry_id=NEW.category_id AND id=NEW.origin_run_id;\n   IF origin.state NOT IN ('completed"
        "','partial') OR origin.reverted_at IS NOT NULL\n    OR NOT public.knowledge_answer_sou"
        "rces_known(NEW.origin_run_id,NEW.source_proof) THEN\n    RAISE EXCEPTION 'Answer origi"
        "n is not an actual retained completed answer' USING ERRCODE='23514'; END IF;\n   IF or"
        'igin.requester_id<>public.scope_requester() AND NOT EXISTS(\n    SELECT 1 FROM public.'
        'knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tenant_id\n    AND prior.orig'
        'in_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answer_digest\n    AND prior.s'
        "ource_proof=NEW.source_proof AND (\n     (NEW.subject_kind='rule' AND prior.subject_id"
        "::text=subject->>'candidate_version_id')\n     OR (NEW.subject_kind='candidate' AND pr"
        "ior.subject_id::text=subject->>'previous_id')\n     OR (NEW.subject_kind='category' AN"
        'D EXISTS(SELECT 1 FROM public.category_knowledge_entries p\n         WHERE p.id=prior.'
        "subject_id AND p.lineage_id::text=subject->>'lineage_id'\n         AND p.version<(subj"
        "ect->>'version')::integer)))) THEN\n    RAISE EXCEPTION 'A new answer origin must belo"
        "ng to the actual Human; inherited native evidence stays fixed' USING ERRCODE='23514'; "
        "END IF;\n  END IF;\n ELSE\n  IF TG_TABLE_NAME='knowledge_gap_submissions' THEN\n   IF "
        'NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>category.owner_id THEN\n  '
        "  RAISE EXCEPTION 'Gap sharing binds the actual owner and current category recipient' "
        "USING ERRCODE='23514'; END IF;\n   SELECT * INTO STRICT origin FROM public.agent_runs "
        'WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.run_id;\n   I'
        "F origin.requester_id<>NEW.owner_id OR origin.state NOT IN ('completed','partial') OR "
        "origin.reverted_at IS NOT NULL\n    OR (NEW.kind='missing_material' AND (NEW.answer IS"
        " NOT NULL OR jsonb_array_length(NEW.source_proof)<>0))\n    OR (NEW.kind='shared_feedb"
        "ack' AND NOT public.knowledge_answer_sources_known(NEW.run_id,NEW.source_proof))\n    "
        "OR (NEW.kind='shared_feedback' AND NOT EXISTS(SELECT 1 FROM public.agent_run_events e"
        '\n        WHERE e.id=NEW.feedback_id AND e.tenant_id=NEW.tenant_id AND e.run_id=NEW.ru'
        "n_id\n        AND e.body->>'type'='run_feedback' AND e.body->>'recorded_by'=NEW.owner_"
        "id::text)) THEN\n    RAISE EXCEPTION 'Only an actual explicit owner submission or actu"
        "al private feedback may be shared' USING ERRCODE='23514'; END IF;\n  ELSE\n   IF NEW.a"
        'ctor_id<>public.scope_requester() OR category.owner_id<>NEW.actor_id\n    OR NOT EXIST'
        'S(SELECT 1 FROM public.knowledge_gap_submissions g WHERE g.tenant_id=NEW.tenant_id AND'
        " g.category_id=NEW.category_id AND g.id=NEW.submission_id) THEN\n    RAISE EXCEPTION '"
        "Only the current actual category owner may attribute a submitted gap' USING ERRCODE='4"
        "2501'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND\n\n$function$\n"
    ),
    (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known(origin_id uuid, proof'
        " jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO '"
        "pg_catalog', 'public', 'pg_temp'\nAS $function$\n\nDECLARE valid boolean;\nBEGIN\n WIT"
        'H RECURSIVE initial(value) AS (\n  SELECT value FROM public.agent_runs r,\n   LATERAL '
        "jsonb_array_elements(coalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) ent"
        "ry(value)\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant"
        "_id',true),'')::uuid\n  UNION ALL\n  SELECT jsonb_build_object('source_type','artifact"
        "','source_id',a.id,'source_revision',a.revision,\n   'content_hash',a.content_hash,'ca"
        "tegory_id',a.category_id)\n   FROM public.agent_runs r CROSS JOIN LATERAL jsonb_array_"
        'elements(r.read_sources) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id'
        "=r.tenant_id AND a.category_id=r.category_id\n    AND a.id::text=ref.value->>'artifact"
        "_id' AND a.revision::text=ref.value->>'expected_revision'\n   WHERE r.id=origin_id AND"
        " r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n ), closure(valu"
        "e,seen) AS (\n  SELECT value,ARRAY[value->>'source_id'] FROM initial\n  UNION ALL\n  S"
        "ELECT child.value,parent.seen||(child.value->>'source_id') FROM closure parent\n   JOI"
        "N public.knowledge_answer_reviews prior ON prior.subject_id::text=parent.value->>'sour"
        "ce_id'\n     AND prior.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uu"
        "id\n     AND parent.value->>'source_type'='knowledge'\n   CROSS JOIN LATERAL jsonb_arr"
        "ay_elements(prior.source_proof) child(value)\n   WHERE NOT (child.value->>'source_id'="
        'ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_elements(proof) p WH'
        "ERE NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'source_type'=p->>'source_t"
        "ype'\n   AND c.value->>'source_id'=p->>'source_id'\n   AND c.value->>'source_revision'"
        "=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'content_hash'\n   AND c.v"
        "alue->>'category_id'=p->>'category_id')) INTO valid;\n RETURN jsonb_typeof(proof)='arr"
        "ay' AND coalesce(valid,false);\nEND\n\n$function$\n"
    ),
)

PREVIOUS_FUNCTIONS = {
    'assert_knowledge_assistant_fact()': (
        'CREATE OR REPLACE FUNCTION public.assert_knowledge_assistant_fact()\n RETURNS trigger'
        "\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'p"
        "g_temp'\nAS $function$\n\nDECLARE subject jsonb; sx xid; rx xid; nx xid; receipt publi"
        'c.action_receipts; origin public.agent_runs;\n category public.categories; actual_owne'
        "r uuid; field_name text;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge c"
        "ontribution facts are append-only' USING ERRCODE='23514'; END IF;\n IF NEW.tenant_id I"
        "S DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n OR public.sc"
        'ope_actor() IS DISTINCT FROM public.scope_requester()\n OR NOT EXISTS(SELECT 1 FROM pu'
        'blic.principals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() AND h.'
        "active AND h.kind='human')\n OR NOT public.category_access(NEW.tenant_id,NEW.category_"
        "id,false) THEN\n  RAISE EXCEPTION 'Only the actual authorized Human may append knowled"
        "ge contributions' USING ERRCODE='42501'; END IF;\n SELECT * INTO STRICT category FROM "
        'public.categories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;\n IF TG_TABLE_'
        "NAME='knowledge_answer_reviews' THEN\n  IF NOT public.category_access(NEW.tenant_id,NE"
        "W.category_id,true) THEN\n   RAISE EXCEPTION 'Knowledge review uses its native categor"
        "y write authority' USING ERRCODE='42501'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM publi"
        'c.principals p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id'
        "\n   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='human' AN"
        'D p.active\n   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expire'
        "s_at>transaction_timestamp())) THEN\n   RAISE EXCEPTION 'Review responsible person mus"
        "t be an active actual category reader' USING ERRCODE='23514'; END IF;\n  EXECUTE forma"
        "t('SELECT to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND "
        "id=$3',\n   CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entries' WH"
        "EN 'candidate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_rule_ve"
        "rsions' END)\n   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.subjec"
        't_id;\n  SELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenant_id='
        'NEW.tenant_id AND r.id=NEW.receipt_id;\n  SELECT xmin INTO rx FROM public.action_recei'
        'pts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;\n  SELECT xmin INTO nx FROM p'
        'ublic.knowledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n  IF sx I'
        "S DISTINCT FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINCT FRO"
        'M NEW.receipt_id::text\n   OR receipt.command_id<>NEW.command_id OR receipt.actor_id<>'
        'public.scope_actor()\n   OR receipt.requester_id<>public.scope_requester()\n   OR (NEW'
        '.verified_by IS NOT NULL AND NEW.verified_by<>public.scope_requester())\n   OR (NEW.su'
        "bject_kind='candidate' AND NEW.verified_by IS NOT NULL)\n   OR (NEW.subject_kind='rule"
        "' AND (receipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS NULL "
        "OR NEW.verified_by IS NULL)) THEN\n   RAISE EXCEPTION 'Review must share its real nati"
        "ve version and Human receipt transaction' USING ERRCODE='23514'; END IF;\n  IF NEW.sou"
        "rce_proof IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'\n      THEN subject-"
        ">'answer_sources' ELSE subject#>'{source_basis,answer_sources}' END) THEN\n   RAISE EX"
        "CEPTION 'Native proof and review must be identical' USING ERRCODE='23514'; END IF;\n  "
        "IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'source"
        "_type'='knowledge' AND (\n    EXISTS(SELECT 1 FROM public.category_knowledge_entries k"
        " WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND coalesce("
        'jsonb_array_length(k.answer_sources),0)>0)\n    OR EXISTS(SELECT 1 FROM public.knowled'
        "ge_rule_versions k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source"
        "_id' AND coalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) THEN\n "
        "  RAISE EXCEPTION 'Reviewed knowledge proofs must flatten existing answer-derived pare"
        "nts' USING ERRCODE='23514'; END IF;\n  IF NEW.origin_run_id IS NOT NULL THEN\n   SELEC"
        'T * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND catego'
        "ry_id=NEW.category_id AND id=NEW.origin_run_id;\n   IF origin.state NOT IN ('completed"
        "','partial') OR origin.reverted_at IS NOT NULL\n    OR NOT public.knowledge_answer_sou"
        "rces_known(NEW.origin_run_id,NEW.source_proof) THEN\n    RAISE EXCEPTION 'Answer origi"
        "n is not an actual retained completed answer' USING ERRCODE='23514'; END IF;\n   IF or"
        'igin.requester_id<>public.scope_requester() AND NOT EXISTS(\n    SELECT 1 FROM public.'
        'knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tenant_id\n    AND prior.orig'
        'in_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answer_digest\n    AND prior.s'
        "ource_proof=NEW.source_proof AND (\n     (NEW.subject_kind='rule' AND prior.subject_id"
        "::text=subject->>'candidate_version_id')\n     OR (NEW.subject_kind='candidate' AND pr"
        "ior.subject_id::text=subject->>'previous_id')\n     OR (NEW.subject_kind='category' AN"
        'D EXISTS(SELECT 1 FROM public.category_knowledge_entries p\n         WHERE p.id=prior.'
        "subject_id AND p.lineage_id::text=subject->>'lineage_id'\n         AND p.version<(subj"
        "ect->>'version')::integer)))) THEN\n    RAISE EXCEPTION 'A new answer origin must belo"
        "ng to the actual Human; inherited native evidence stays fixed' USING ERRCODE='23514'; "
        "END IF;\n  END IF;\n ELSE\n  IF TG_TABLE_NAME='knowledge_gap_submissions' THEN\n   IF "
        'NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>category.owner_id THEN\n  '
        "  RAISE EXCEPTION 'Gap sharing binds the actual owner and current category recipient' "
        "USING ERRCODE='23514'; END IF;\n   SELECT * INTO STRICT origin FROM public.agent_runs "
        'WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.run_id;\n   I'
        "F origin.requester_id<>NEW.owner_id OR origin.state NOT IN ('completed','partial') OR "
        "origin.reverted_at IS NOT NULL\n    OR (NEW.kind='missing_material' AND (NEW.answer IS"
        " NOT NULL OR jsonb_array_length(NEW.source_proof)<>0))\n    OR (NEW.kind='shared_feedb"
        "ack' AND NOT public.knowledge_answer_sources_known(NEW.run_id,NEW.source_proof))\n    "
        "OR (NEW.kind='shared_feedback' AND NOT EXISTS(SELECT 1 FROM public.agent_run_events e"
        '\n        WHERE e.id=NEW.feedback_id AND e.tenant_id=NEW.tenant_id AND e.run_id=NEW.ru'
        "n_id\n        AND e.body->>'type'='run_feedback' AND e.body->>'recorded_by'=NEW.owner_"
        "id::text)) THEN\n    RAISE EXCEPTION 'Only an actual explicit owner submission or actu"
        "al private feedback may be shared' USING ERRCODE='23514'; END IF;\n  ELSE\n   IF NEW.a"
        'ctor_id<>public.scope_requester() OR category.owner_id<>NEW.actor_id\n    OR NOT EXIST'
        'S(SELECT 1 FROM public.knowledge_gap_submissions g WHERE g.tenant_id=NEW.tenant_id AND'
        " g.category_id=NEW.category_id AND g.id=NEW.submission_id) THEN\n    RAISE EXCEPTION '"
        "Only the current actual category owner may attribute a submitted gap' USING ERRCODE='4"
        "2501'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND\n\n$function$\n"
    ),
    'knowledge_answer_sources_known(uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known(origin_id uuid, proof'
        " jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO '"
        "pg_catalog', 'public', 'pg_temp'\nAS $function$\n\nDECLARE valid boolean;\nBEGIN\n WIT"
        'H RECURSIVE initial(value) AS (\n  SELECT value FROM public.agent_runs r,\n   LATERAL '
        "jsonb_array_elements(coalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) ent"
        "ry(value)\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant"
        "_id',true),'')::uuid\n  UNION ALL\n  SELECT jsonb_build_object('source_type','artifact"
        "','source_id',a.id,'source_revision',a.revision,\n   'content_hash',a.content_hash,'ca"
        "tegory_id',a.category_id)\n   FROM public.agent_runs r CROSS JOIN LATERAL jsonb_array_"
        'elements(r.read_sources) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id'
        "=r.tenant_id AND a.category_id=r.category_id\n    AND a.id::text=ref.value->>'artifact"
        "_id' AND a.revision::text=ref.value->>'expected_revision'\n   WHERE r.id=origin_id AND"
        " r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n ), closure(valu"
        "e,seen) AS (\n  SELECT value,ARRAY[value->>'source_id'] FROM initial\n  UNION ALL\n  S"
        "ELECT child.value,parent.seen||(child.value->>'source_id') FROM closure parent\n   JOI"
        "N public.knowledge_answer_reviews prior ON prior.subject_id::text=parent.value->>'sour"
        "ce_id'\n     AND prior.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uu"
        "id\n     AND parent.value->>'source_type'='knowledge'\n   CROSS JOIN LATERAL jsonb_arr"
        "ay_elements(prior.source_proof) child(value)\n   WHERE NOT (child.value->>'source_id'="
        'ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_elements(proof) p WH'
        "ERE NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'source_type'=p->>'source_t"
        "ype'\n   AND c.value->>'source_id'=p->>'source_id'\n   AND c.value->>'source_revision'"
        "=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'content_hash'\n   AND c.v"
        "alue->>'category_id'=p->>'category_id')) INTO valid;\n RETURN jsonb_typeof(proof)='arr"
        "ay' AND coalesce(valid,false);\nEND\n\n$function$\n"
    ),
}

NATIVE_FUNCTIONS = {
    'assert_knowledge_assistant_fact()': (
        'CREATE OR REPLACE FUNCTION public.assert_knowledge_assistant_fact()\n RETURNS trigger'
        "\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'p"
        "g_temp'\nAS $function$\n\nDECLARE subject jsonb; sx xid; rx xid; nx xid; receipt publi"
        'c.action_receipts; origin public.agent_runs;\n category public.categories; actual_owne'
        "r uuid; field_name text;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowledge c"
        "ontribution facts are append-only' USING ERRCODE='23514'; END IF;\n IF NEW.tenant_id I"
        "S DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n OR public.sc"
        'ope_actor() IS DISTINCT FROM public.scope_requester()\n OR NOT EXISTS(SELECT 1 FROM pu'
        'blic.principals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() AND h.'
        "active AND h.kind='human')\n OR NOT public.category_access(NEW.tenant_id,NEW.category_"
        "id,false) THEN\n  RAISE EXCEPTION 'Only the actual authorized Human may append knowled"
        "ge contributions' USING ERRCODE='42501'; END IF;\n SELECT * INTO STRICT category FROM "
        'public.categories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;\n IF TG_TABLE_'
        "NAME='knowledge_answer_reviews' THEN\n  IF NOT public.category_access(NEW.tenant_id,NE"
        "W.category_id,true) THEN\n   RAISE EXCEPTION 'Knowledge review uses its native categor"
        "y write authority' USING ERRCODE='42501'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM publi"
        'c.principals p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id=p.id'
        "\n   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='human' AN"
        'D p.active\n   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.expire'
        "s_at>transaction_timestamp())) THEN\n   RAISE EXCEPTION 'Review responsible person mus"
        "t be an active actual category reader' USING ERRCODE='23514'; END IF;\n  EXECUTE forma"
        "t('SELECT to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 AND "
        "id=$3',\n   CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entries' WH"
        "EN 'candidate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_rule_ve"
        "rsions' END)\n   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.subjec"
        't_id;\n  SELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenant_id='
        'NEW.tenant_id AND r.id=NEW.receipt_id;\n  SELECT xmin INTO rx FROM public.action_recei'
        'pts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;\n  SELECT xmin INTO nx FROM p'
        'ublic.knowledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n  IF sx I'
        "S DISTINCT FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINCT FRO"
        'M NEW.receipt_id::text\n   OR receipt.command_id<>NEW.command_id OR receipt.actor_id<>'
        'public.scope_actor()\n   OR receipt.requester_id<>public.scope_requester()\n   OR (NEW'
        '.verified_by IS NOT NULL AND NEW.verified_by<>public.scope_requester())\n   OR (NEW.su'
        "bject_kind='candidate' AND NEW.verified_by IS NOT NULL)\n   OR (NEW.subject_kind='rule"
        "' AND (receipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS NULL "
        "OR NEW.verified_by IS NULL)) THEN\n   RAISE EXCEPTION 'Review must share its real nati"
        "ve version and Human receipt transaction' USING ERRCODE='23514'; END IF;\n  IF NEW.sou"
        "rce_proof IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'\n      THEN subject-"
        ">'answer_sources' ELSE subject#>'{source_basis,answer_sources}' END) THEN\n   RAISE EX"
        "CEPTION 'Native proof and review must be identical' USING ERRCODE='23514'; END IF;\n  "
        "IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'source"
        "_type'='knowledge' AND (\n    EXISTS(SELECT 1 FROM public.category_knowledge_entries k"
        " WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND coalesce("
        'jsonb_array_length(k.answer_sources),0)>0)\n    OR EXISTS(SELECT 1 FROM public.knowled'
        "ge_rule_versions k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source"
        "_id' AND coalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) THEN\n "
        "  RAISE EXCEPTION 'Reviewed knowledge proofs must flatten existing answer-derived pare"
        "nts' USING ERRCODE='23514'; END IF;\n  IF NEW.origin_run_id IS NOT NULL THEN\n   SELEC"
        'T * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND (categ'
        'ory_id=NEW.category_id OR category_id IS NULL) AND id=NEW.origin_run_id;\n   IF origin'
        ".state NOT IN ('completed','partial') OR origin.reverted_at IS NOT NULL\n    OR NOT pu"
        'blic.knowledge_answer_sources_known(NEW.origin_run_id,NEW.source_proof) THEN\n    RAIS'
        "E EXCEPTION 'Answer origin is not an actual retained completed answer' USING ERRCODE='"
        "23514'; END IF;\n   IF origin.requester_id<>public.scope_requester() AND NOT EXISTS(\n"
        '    SELECT 1 FROM public.knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tena'
        'nt_id\n    AND prior.origin_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answe'
        "r_digest\n    AND prior.source_proof=NEW.source_proof AND (\n     (NEW.subject_kind='r"
        "ule' AND prior.subject_id::text=subject->>'candidate_version_id')\n     OR (NEW.subjec"
        "t_kind='candidate' AND prior.subject_id::text=subject->>'previous_id')\n     OR (NEW.s"
        "ubject_kind='category' AND EXISTS(SELECT 1 FROM public.category_knowledge_entries p\n "
        "        WHERE p.id=prior.subject_id AND p.lineage_id::text=subject->>'lineage_id'\n   "
        "      AND p.version<(subject->>'version')::integer)))) THEN\n    RAISE EXCEPTION 'A ne"
        'w answer origin must belong to the actual Human; inherited native evidence stays fixed'
        "' USING ERRCODE='23514'; END IF;\n  END IF;\n ELSE\n  IF TG_TABLE_NAME='knowledge_gap_"
        "submissions' THEN\n   IF NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>c"
        "ategory.owner_id THEN\n    RAISE EXCEPTION 'Gap sharing binds the actual owner and cur"
        "rent category recipient' USING ERRCODE='23514'; END IF;\n   SELECT * INTO STRICT origi"
        'n FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND (category_id=NEW.category_i'
        'd OR category_id IS NULL) AND id=NEW.run_id;\n   IF origin.requester_id<>NEW.owner_id '
        "OR origin.state NOT IN ('completed','partial') OR origin.reverted_at IS NOT NULL\n    "
        "OR (NEW.kind='missing_material' AND (NEW.answer IS NOT NULL OR jsonb_array_length(NEW."
        "source_proof)<>0))\n    OR (NEW.kind='shared_feedback' AND NOT public.knowledge_answer"
        "_sources_known(NEW.run_id,NEW.source_proof))\n    OR (NEW.kind='shared_feedback' AND N"
        'OT EXISTS(SELECT 1 FROM public.agent_run_events e\n        WHERE e.id=NEW.feedback_id '
        "AND e.tenant_id=NEW.tenant_id AND e.run_id=NEW.run_id\n        AND e.body->>'type'='ru"
        "n_feedback' AND e.body->>'recorded_by'=NEW.owner_id::text)) THEN\n    RAISE EXCEPTION "
        "'Only an actual explicit owner submission or actual private feedback may be shared' US"
        "ING ERRCODE='23514'; END IF;\n  ELSE\n   IF NEW.actor_id<>public.scope_requester() OR "
        'category.owner_id<>NEW.actor_id\n    OR NOT EXISTS(SELECT 1 FROM public.knowledge_gap_'
        'submissions g WHERE g.tenant_id=NEW.tenant_id AND g.category_id=NEW.category_id AND g.'
        "id=NEW.submission_id) THEN\n    RAISE EXCEPTION 'Only the current actual category owne"
        "r may attribute a submitted gap' USING ERRCODE='42501'; END IF;\n  END IF;\n END IF;\n"
        ' RETURN NULL;\nEND\n\n$function$\n'
    ),
    'knowledge_answer_sources_known(uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_known(origin_id uuid, proof'
        " jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO '"
        "pg_catalog', 'public', 'pg_temp'\nAS $function$\n\nDECLARE valid boolean;\nBEGIN\n WIT"
        'H RECURSIVE initial(value) AS (\n  SELECT value FROM public.agent_runs r,\n   LATERAL '
        "jsonb_array_elements(coalesce(r.result#>'{result,assistant,sources}','[]'::jsonb)) ent"
        "ry(value)\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant"
        "_id',true),'')::uuid\n  UNION ALL\n  SELECT jsonb_build_object('source_type','artifact"
        "','source_id',a.id,'source_revision',a.revision,\n   'content_hash',a.content_hash,'ca"
        "tegory_id',a.category_id)\n   FROM public.agent_runs r CROSS JOIN LATERAL jsonb_array_"
        'elements(r.read_sources) ref(value)\n   JOIN public.artifact_versions a ON a.tenant_id'
        '=r.tenant_id AND (r.category_id IS NULL OR a.category_id=r.category_id)\n    AND a.id:'
        ":text=ref.value->>'artifact_id' AND a.revision::text=ref.value->>'expected_revision'\n"
        "   WHERE r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),"
        "'')::uuid\n ), closure(value,seen) AS (\n  SELECT value,ARRAY[value->>'source_id'] FRO"
        "M initial\n  UNION ALL\n  SELECT child.value,parent.seen||(child.value->>'source_id') "
        'FROM closure parent\n   JOIN public.knowledge_answer_reviews prior ON prior.subject_id'
        "::text=parent.value->>'source_id'\n     AND prior.tenant_id=nullif(current_setting('pd"
        "os.tenant_id',true),'')::uuid\n     AND parent.value->>'source_type'='knowledge'\n   C"
        'ROSS JOIN LATERAL jsonb_array_elements(prior.source_proof) child(value)\n   WHERE NOT '
        "(child.value->>'source_id'=ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb"
        '_array_elements(proof) p WHERE NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'
        "'source_type'=p->>'source_type'\n   AND c.value->>'source_id'=p->>'source_id'\n   AND "
        "c.value->>'source_revision'=p->>'source_revision'\n   AND c.value->>'content_hash'=p->"
        ">'content_hash'\n   AND c.value->>'category_id'=p->>'category_id')) INTO valid;\n RETU"
        "RN jsonb_typeof(proof)='array' AND coalesce(valid,false);\nEND\n\n$function$\n"
    ),
}

