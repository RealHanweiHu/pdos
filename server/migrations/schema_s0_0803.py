"""Parenthesize JSON containment operands in independent Field atom checks."""

PREVIOUS_FUNCTIONS = {'assert_field_common(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_common(t uuid, '
                                        'target uuid, kind text)\n'
                                        ' RETURNS void\n'
                                        ' LANGUAGE plpgsql\n'
                                        ' SECURITY DEFINER\n'
                                        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                        'AS $function$\n'
                                        '\n'
                                        'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref '
                                        'jsonb; basis jsonb; active_sources jsonb;\n'
                                        'BEGIN\n'
                                        '\n'
                                        " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                        'STRICT v FROM public.field_feedback_versions x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                        'INTO STRICT v FROM public.field_response_records x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        '\n'
                                        ' vx=v.tx;\n'
                                        ' SELECT xmin INTO rx FROM public.action_receipts WHERE '
                                        'tenant_id=t AND id=v.receipt_id;\n'
                                        ' PERFORM public.assert_field_members(t,target,kind);\n'
                                        " envelope=v.command->'envelope';\n"
                                        ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR '
                                        'v.requester_id IS DISTINCT FROM public.scope_requester()\n'
                                        '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
                                        'public.category_access(t,v.category_id,true)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        'h.tenant_id=t AND h.id=v.actor_id AND h.active)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        "h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' AND "
                                        'h.active)\n'
                                        "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR "
                                        "envelope->>'command_id' IS DISTINCT FROM v.command_id::text\n"
                                        "  OR envelope->>'category_id' IS DISTINCT FROM "
                                        "v.category_id::text OR envelope->>'product_id' IS DISTINCT "
                                        'FROM v.product_id::text\n'
                                        "  OR v.command->'review'->'declaration' IS DISTINCT FROM "
                                        "envelope->'payload'\n"
                                        "  OR v.command->'review'->>'operation' IS DISTINCT FROM "
                                        'v.operation\n'
                                        "  OR v.command->'review'->'sources' IS DISTINCT FROM "
                                        "envelope->'payload'->'sources'\n"
                                        "  OR v.command->'review'->'source_basis' IS DISTINCT FROM "
                                        'v.source_basis OR v.body IS DISTINCT FROM '
                                        "v.command->'review'->'after'\n"
                                        '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.categories c WHERE c.tenant_id=t AND '
                                        'c.id=v.category_id AND '
                                        "c.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.products p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.id=v.product_id AND '
                                        "p.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.projects p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.product_id=v.product_id AND '
                                        'p.id=v.project_id))\n'
                                        "  OR NOT coalesce(envelope->'source_read_set' @> "
                                        'v.reads,false) OR NOT coalesce(v.reads @> '
                                        "(envelope->'source_read_set'),false)\n"
                                        '  OR '
                                        "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                        '  OR NOT '
                                        'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                        '  OR NOT '
                                        'public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR NOT '
                                        'public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM '
                                        'public.action_receipts r WHERE r.tenant_id=t AND '
                                        'r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS '
                                        'NOT NULL))\n'
                                        '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                        'DISTINCT FROM vx)\n'
                                        '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                        'DISTINCT FROM vx)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                        'x.actor_id=v.actor_id AND x.digest=v.request_digest AND '
                                        'x.xmin=vx AND '
                                        "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                        'THEN\n'
                                        "  RAISE EXCEPTION 'Field requires actual scope actor sources "
                                        "and one common transaction' USING ERRCODE='23514'; END IF;\n"
                                        ' IF v.confirmation_id IS NOT NULL THEN\n'
                                        '  SELECT xmin INTO px FROM public.confirmations WHERE '
                                        'tenant_id=t AND id=v.confirmation_id;\n'
                                        "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 "
                                        "consumption shares its new fact transaction' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        ' END IF;\n'
                                        " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT "
                                        "FROM 'array' THEN\n"
                                        "  RAISE EXCEPTION 'Field requires actual direct-source "
                                        "metadata' USING ERRCODE='23514'; END IF;\n"
                                        ' FOR basis IN SELECT value FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
                                        '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        '   AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.id::text=basis->>'id'\n"
                                        "   AND a.revision::text=basis->>'revision' AND "
                                        "a.content_hash=basis->>'hash'\n"
                                        "   AND (v.visibility='private' OR (a.visibility='category' "
                                        'AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM '
                                        'public.products source_product\n'
                                        '    WHERE source_product.tenant_id=t AND '
                                        'source_product.category_id=v.category_id AND '
                                        'source_product.id=a.product_id AND '
                                        "source_product.visibility='category'))))\n"
                                        "   AND (a.original_id IS NULL OR v.visibility='private' OR "
                                        'EXISTS(SELECT 1 FROM public.uploaded_originals o\n'
                                        '    WHERE o.tenant_id=t AND o.id=a.original_id AND '
                                        "o.visibility='category'))) THEN\n"
                                        "   RAISE EXCEPTION 'Field historical source hash or actual "
                                        "audience changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        " active_sources=CASE WHEN kind='field_feedback' THEN "
                                        "v.sources ELSE envelope->'payload'->'sources' END;\n"
                                        " IF v.operation='field.feedback.followup.link' THEN\n"
                                        '  active_sources=active_sources||coalesce((SELECT '
                                        'jsonb_agg(content.value) FROM '
                                        "jsonb_array_elements(v.source_basis->'result_receipts') "
                                        'result,\n'
                                        '   LATERAL '
                                        "jsonb_array_elements(result->'direct_content_refs') "
                                        "content),'[]'::jsonb);\n"
                                        ' END IF;\n'
                                        ' FOR ref IN SELECT value FROM '
                                        'jsonb_array_elements(active_sources) LOOP\n'
                                        '  SELECT value INTO STRICT basis FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') WHERE "
                                        "value->>'id'=ref->>'id';\n"
                                        "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT "
                                        'EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE '
                                        "rd->>'artifact_id'=ref->>'id' AND "
                                        "rd->'expected_revision'=ref->'revision')\n"
                                        '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        "    AND a.id::text=ref->>'id' AND "
                                        "a.revision::text=ref->>'revision' AND a.status='active'\n"
                                        '    AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.revision::text=basis->>'revision'\n"
                                        "    AND a.content_hash=basis->>'hash' AND "
                                        "a.status=basis->>'status' AND "
                                        "a.owner_id::text=basis->>'owner_id' AND "
                                        "a.visibility=basis->>'visibility'\n"
                                        '    AND ((a.original_id IS NULL AND '
                                        "basis->>'source_kind'='registered_native_text' AND "
                                        'EXISTS(SELECT 1 FROM public.action_receipts r\n'
                                        '      WHERE r.tenant_id=t AND r.subject_id=a.id AND '
                                        "r.subject_revision=a.revision AND r.subject_type='artifact' "
                                        "AND r.operation='evidence.artifact.register'\n"
                                        "       AND r.id::text=basis->'registration'->>'receipt_id' "
                                        "AND r.actor_id::text=basis->'registration'->>'actor_id'\n"
                                        '       AND '
                                        "r.requester_id::text=basis->'registration'->>'requester_id' "
                                        'AND r.run_id::text IS NOT DISTINCT FROM '
                                        "basis->'registration'->>'run_id'))\n"
                                        '     OR (a.original_id IS NOT NULL AND '
                                        "basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
                                        'FROM public.uploaded_originals o\n'
                                        '      JOIN public.original_security sec ON '
                                        'sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
                                        'o.tenant_id=t AND o.category_id=v.category_id\n'
                                        '       AND o.id=a.original_id AND '
                                        "o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
                                        "sec.epoch::text=basis->'original'->>'epoch'\n"
                                        "       AND sec.source_state='active' AND "
                                        "sec.disposition='active' AND "
                                        "sec.source_state=basis->'original'->>'source_state'\n"
                                        '       AND '
                                        "sec.disposition=basis->'original'->>'disposition')))) THEN\n"
                                        "   RAISE EXCEPTION 'Field newly adopted direct source "
                                        "metadata changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        'END;\n'
                                        '$function$\n',
 'assert_field_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_members(t '
                                         'uuid, target uuid, kind text)\n'
                                         ' RETURNS void\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         '\n'
                                         'DECLARE v record; r public.action_receipts; proof '
                                         'public.confirmations; expected jsonb; event_name text;\n'
                                         'BEGIN\n'
                                         '\n'
                                         " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                         'STRICT v FROM public.field_feedback_versions x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                         'INTO STRICT v FROM public.field_response_records x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                         "ERRCODE='23514'; END IF;\n"
                                         '\n'
                                         ' '
                                         "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE "
                                         "WHEN kind='field_response' THEN 'recorded' WHEN "
                                         "v.body->'location' IS NOT NULL AND "
                                         "v.body->'location'<>'null'::jsonb THEN 'located' ELSE "
                                         "'unknown' END,\n"
                                         "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
                                         " event_name=CASE v.operation WHEN 'field.feedback.create' "
                                         "THEN 'field.feedback_created' WHEN 'field.feedback.locate' "
                                         "THEN 'field.feedback_located'\n"
                                         "  WHEN 'field.feedback.action.record' THEN "
                                         "'field.feedback_action_recorded' WHEN "
                                         "'field.feedback.followup.link' THEN "
                                         "'field.feedback_followup_linked' END;\n"
                                         ' SELECT * INTO STRICT r FROM public.action_receipts WHERE '
                                         'tenant_id=t AND id=v.receipt_id;\n'
                                         ' IF '
                                         'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
                                         '  IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                         '  OR r.result IS DISTINCT FROM expected OR '
                                         'r.created_at<v.created_at OR event_name IS NULL\n'
                                         '  OR (SELECT count(*) FROM public.action_receipts x WHERE '
                                         'x.tenant_id=t AND x.operation=v.operation AND '
                                         'x.subject_type=kind AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision)<>1\n'
                                         '  OR (SELECT count(*) FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.operation=v.operation AND x.created_at>=v.created_at)\n'
                                         '  OR (SELECT count(*) FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.type=event_name AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision AND x.schema_version=1 AND '
                                         'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) '
                                         'AND x.created_at>=v.created_at)\n'
                                         "  OR v.command->>'original_key_sha256' IS NULL OR "
                                         "v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
                                         "  OR v.command->'envelope' ? 'idempotency_key' OR "
                                         "v.command->'envelope'->'payload' ? 'confirmation_token'\n"
                                         "  OR v.command->'envelope'->'payload' ? 'approval_token'\n"
                                         '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                         'x.tenant_id=t AND x.category_id=v.category_id AND '
                                         'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
                                         'x.digest=v.request_digest AND '
                                         "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                         'THEN\n'
                                         "  RAISE EXCEPTION 'Field original receipt audit event or "
                                         "request key mismatch' USING ERRCODE='23514'; END IF;\n"
                                         " IF v.operation<>'field.feedback.create' THEN\n"
                                         '  SELECT * INTO STRICT proof FROM public.confirmations WHERE '
                                         'tenant_id=t AND id=v.confirmation_id;\n'
                                         '  IF proof.consumed IS DISTINCT FROM true OR '
                                         'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
                                         '   IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE '
                                         "WHEN v.product_id IS NULL THEN 'category' ELSE 'product' "
                                         "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
                                         "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR "
                                         'proof.created_at>v.created_at OR proof.expires_at IS NULL\n'
                                         '   OR v.created_at>=proof.expires_at OR '
                                         'r.created_at>=proof.expires_at OR '
                                         'v.actor_id<>v.requester_id\n'
                                         '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL '
                                         'THEN\n'
                                         "   RAISE EXCEPTION 'Field T1 requires its actual consumed "
                                         "human confirmation' USING ERRCODE='23514'; END IF;\n"
                                         ' END IF;\n'
                                         'END;\n'
                                         '$function$\n',
 'assert_field_feedback(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_feedback(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_feedback_versions; prior '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=target;\n'
                                     ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE '
                                     'tenant_id=t AND id=cur.id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' IF vx IS DISTINCT FROM cx OR '
                                     'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
                                     "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field "
                                     "feedback binds actual owner and same-transaction Current' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.create' THEN\n"
                                     '  '
                                     "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
                                     '   '
                                     "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
                                     '  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources' OR v.project_id IS NOT NULL\n"
                                     "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field intake records only its actual "
                                     "declared source report, with unknown location' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     ' ELSE\n'
                                     '  SELECT * INTO STRICT prior FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=v.previous_id;\n'
                                     "  location=v.body->'location';\n"
                                     '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS '
                                     'DISTINCT FROM '
                                     'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
                                     '   OR (prior.product_id IS NOT NULL AND prior.product_id IS '
                                     'DISTINCT FROM v.product_id)\n'
                                     "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT "
                                     'FROM '
                                     "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
                                     "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
                                     "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
                                     "(prior.body-ARRAY['revision','location'])\n"
                                     "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
                                     "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR "
                                     "location->>'state' IS DISTINCT FROM 'known'\n"
                                     "   OR location->>'product_id' IS DISTINCT FROM "
                                     "v.product_id::text OR location->>'project_id' IS DISTINCT FROM "
                                     'v.project_id::text\n'
                                     "   OR location->'engineering_configuration' IS DISTINCT FROM "
                                     "payload->'engineering_configuration'\n"
                                     "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
                                     "payload->'manufacturing_configuration'\n"
                                     "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
                                     "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb "
                                     "AND payload->>'project_id' IS DISTINCT FROM v.project_id::text)\n"
                                     '   OR NOT coalesce(v.sources @> prior.sources,false) OR NOT '
                                     "coalesce(v.sources @> payload->'sources',false)\n"
                                     "   OR NOT coalesce(v.sources @> location->'sources',false)\n"
                                     '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) '
                                     'source WHERE NOT(prior.sources @> jsonb_build_array(source)\n'
                                     "    OR payload->'sources' @> jsonb_build_array(source) OR "
                                     "location->'sources' @> jsonb_build_array(source))) THEN\n"
                                     "   RAISE EXCEPTION 'Field location preserves report, privacy and "
                                     "exact predecessor; known product cannot silently change' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations '
                                     'engineering WHERE engineering.tenant_id=t AND '
                                     'engineering.category_id=v.category_id\n'
                                     '   AND engineering.product_id=v.product_id AND '
                                     "engineering.id::text=location->'engineering_configuration'->>'id'\n"
                                     '   AND '
                                     "engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '   AND coalesce(v.reads @> '
                                     'engineering.required_source_read_set,false)\n'
                                     "   AND (v.visibility='private' OR "
                                     "engineering.visibility='category')\n"
                                     '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM '
                                     'public.project_product_links link WHERE link.tenant_id=t AND '
                                     'link.category_id=v.category_id\n'
                                     '    AND link.product_id=v.product_id AND '
                                     'link.project_id=v.project_id AND '
                                     'link.definition_id=engineering.definition_id AND '
                                     'link.definition_revision=engineering.definition_revision))) '
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field location requires an actual "
                                     "engineering configuration in the selected project' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF '
                                     "coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.process_revisions '
                                     'manufacturing\n'
                                     '   WHERE manufacturing.tenant_id=t AND '
                                     'manufacturing.category_id=v.category_id AND '
                                     'manufacturing.product_id=v.product_id\n'
                                     '    AND '
                                     "manufacturing.id::text=location->'manufacturing_configuration'->>'id' "
                                     'AND '
                                     "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     '    AND '
                                     "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND coalesce(v.reads @> '
                                     'manufacturing.required_source_read_set,false) AND '
                                     "(v.visibility='private' OR manufacturing.visibility='category')) "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field manufacturing configuration must match "
                                     "actual engineering configuration' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.build_lots lot\n'
                                     '   JOIN public.actual_configurations actual ON '
                                     'actual.tenant_id=lot.tenant_id AND '
                                     'actual.product_id=lot.product_id AND '
                                     'actual.id=lot.actual_configuration_id\n'
                                     '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND '
                                     'lot.product_id=v.product_id AND lot.project_id=v.project_id\n'
                                     "    AND lot.id::text=location->'batch'->>'id' AND "
                                     "lot.revision::text=location->'batch'->>'revision'\n"
                                     '    AND actual.revision=lot.actual_configuration_revision\n'
                                     '    AND '
                                     "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     "    AND (payload->>'project_id' IS NULL OR "
                                     "payload->>'project_id'=lot.project_id::text)\n"
                                     '    AND coalesce(v.reads @> lot.required_source_read_set,false) '
                                     'AND coalesce(v.reads @> actual.required_source_read_set,false)\n'
                                     "    AND (v.visibility='private' OR (lot.visibility='category' "
                                     "AND actual.visibility='category'))) THEN\n"
                                     "   RAISE EXCEPTION 'Field batch requires exact native lot and "
                                     "actual physical configuration' USING ERRCODE='23514'; END IF;\n"
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n',
 'assert_field_response(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_response_records; parent '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; result jsonb; native_receipt '
                                     'public.action_receipts;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_response_records WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_response');\n"
                                     ' SELECT * INTO STRICT parent FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'id=v.feedback_version_id;\n'
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' '
                                     "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
                                     '  '
                                     "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
                                     ' IF '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
                                     '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
                                     "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' "
                                     "AND v.visibility<>'private')\n"
                                     "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
                                     "  OR payload->'feedback' IS DISTINCT FROM "
                                     "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
                                     '  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources'\n"
                                     "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM "
                                     "(payload->>'occurred_at')::timestamptz\n"
                                     '  OR '
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
                                     "  OR (v.operation='field.feedback.action.record' AND "
                                     "(payload->>'action_kind' IS DISTINCT FROM v.response_kind OR "
                                     "v.body->'result_receipts'<>'[]'::jsonb))\n"
                                     "  OR NOT coalesce(v.source_basis->'artifacts' @> "
                                     "parent.source_basis->'artifacts',false) THEN\n"
                                     "  RAISE EXCEPTION 'Field response binds exact current parent and "
                                     "new actual facts without advancing its report' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.followup.link' THEN\n"
                                     '  IF v.project_id IS NULL OR '
                                     "jsonb_array_length(payload->'result_receipts')=0\n"
                                     '   OR '
                                     "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
                                     '   OR EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') result "
                                     "WHERE result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
                                     "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text "
                                     'OR NOT EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(payload->'result_receipts') requested WHERE "
                                     "requested->'receipt_id'=result->'receipt_id')) THEN\n"
                                     "   RAISE EXCEPTION 'Field follow-up references only finite fixed "
                                     "native results in its actual project' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  FOR result IN SELECT value FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
                                     '   SELECT * INTO STRICT native_receipt FROM '
                                     'public.action_receipts r WHERE r.tenant_id=t AND '
                                     'r.category_id=v.category_id\n'
                                     "    AND r.id::text=result->>'receipt_id' AND "
                                     "r.product_id=v.product_id AND r.operation=result->>'operation'\n"
                                     "    AND r.subject_type=result->>'subject_type' AND "
                                     "r.subject_id::text=result->>'subject_id'\n"
                                     "    AND r.subject_revision::text=result->>'subject_revision' AND "
                                     "r.request_digest=result->>'receipt_request_digest'\n"
                                     "    AND r.visibility=result->>'receipt_visibility';\n"
                                     "   IF (v.visibility='category' AND "
                                     "(native_receipt.visibility<>'category' OR "
                                     "result->>'visibility'<>'category'\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE '
                                     'p.tenant_id=t AND p.id=v.product_id AND '
                                     "p.visibility='category')\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE '
                                     'p.tenant_id=t AND p.id=v.project_id AND '
                                     "p.visibility='category')))\n"
                                     '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE '
                                     'a.tenant_id=t AND a.category_id=v.category_id AND '
                                     'a.receipt_id=native_receipt.id\n'
                                     '     AND a.actor_id=native_receipt.actor_id AND '
                                     'a.operation=native_receipt.operation)\n'
                                     '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE '
                                     'e.tenant_id=t AND e.category_id=v.category_id AND '
                                     'e.receipt_id=native_receipt.id\n'
                                     '     AND e.subject_id=native_receipt.subject_id AND '
                                     'e.subject_revision=native_receipt.subject_revision AND '
                                     'e.actor_id=native_receipt.actor_id\n'
                                     '     AND e.schema_version=1 AND '
                                     'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
                                     'THEN\n'
                                     "    RAISE EXCEPTION 'Field follow-up requires actual native "
                                     "receipt audit event and audience' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  END LOOP;\n'
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n'}

FIELD_FUNCTIONS = {'assert_field_members(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_members(t '
                                         'uuid, target uuid, kind text)\n'
                                         ' RETURNS void\n'
                                         ' LANGUAGE plpgsql\n'
                                         ' SECURITY DEFINER\n'
                                         " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                         'AS $function$\n'
                                         '\n'
                                         'DECLARE v record; r public.action_receipts; proof '
                                         'public.confirmations; expected jsonb; event_name text;\n'
                                         'BEGIN\n'
                                         '\n'
                                         " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                         'STRICT v FROM public.field_feedback_versions x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                         'INTO STRICT v FROM public.field_response_records x WHERE '
                                         'x.tenant_id=t AND x.id=target;\n'
                                         " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                         "ERRCODE='23514'; END IF;\n"
                                         '\n'
                                         ' '
                                         "expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE "
                                         "WHEN kind='field_response' THEN 'recorded' WHEN "
                                         "v.body->'location' IS NOT NULL AND "
                                         "v.body->'location'<>'null'::jsonb THEN 'located' ELSE "
                                         "'unknown' END,\n"
                                         "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
                                         " event_name=CASE v.operation WHEN 'field.feedback.create' "
                                         "THEN 'field.feedback_created' WHEN 'field.feedback.locate' "
                                         "THEN 'field.feedback_located'\n"
                                         "  WHEN 'field.feedback.action.record' THEN "
                                         "'field.feedback_action_recorded' WHEN "
                                         "'field.feedback.followup.link' THEN "
                                         "'field.feedback_followup_linked' END;\n"
                                         ' SELECT * INTO STRICT r FROM public.action_receipts WHERE '
                                         'tenant_id=t AND id=v.receipt_id;\n'
                                         ' IF '
                                         'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
                                         '  IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
                                         '  OR r.result IS DISTINCT FROM expected OR '
                                         'r.created_at<v.created_at OR event_name IS NULL\n'
                                         '  OR (SELECT count(*) FROM public.action_receipts x WHERE '
                                         'x.tenant_id=t AND x.operation=v.operation AND '
                                         'x.subject_type=kind AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision)<>1\n'
                                         '  OR (SELECT count(*) FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.operation=v.operation AND x.created_at>=v.created_at)\n'
                                         '  OR (SELECT count(*) FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id)<>1\n'
                                         '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                         'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                         'x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
                                         'x.type=event_name AND x.subject_id=v.id AND '
                                         'x.subject_revision=v.revision AND x.schema_version=1 AND '
                                         'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) '
                                         'AND x.created_at>=v.created_at)\n'
                                         "  OR v.command->>'original_key_sha256' IS NULL OR "
                                         "v.command->>'original_key_sha256' !~ '^[a-f0-9]{64}$'\n"
                                         "  OR (v.command->'envelope') ? 'idempotency_key' OR "
                                         "(v.command->'envelope'->'payload') ? 'confirmation_token'\n"
                                         "  OR (v.command->'envelope'->'payload') ? 'approval_token'\n"
                                         '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                         'x.tenant_id=t AND x.category_id=v.category_id AND '
                                         'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
                                         'x.digest=v.request_digest AND '
                                         "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                         'THEN\n'
                                         "  RAISE EXCEPTION 'Field original receipt audit event or "
                                         "request key mismatch' USING ERRCODE='23514'; END IF;\n"
                                         " IF v.operation<>'field.feedback.create' THEN\n"
                                         '  SELECT * INTO STRICT proof FROM public.confirmations WHERE '
                                         'tenant_id=t AND id=v.confirmation_id;\n'
                                         '  IF proof.consumed IS DISTINCT FROM true OR '
                                         'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
                                         '   IS DISTINCT FROM '
                                         'ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE '
                                         "WHEN v.product_id IS NULL THEN 'category' ELSE 'product' "
                                         "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
                                         "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR "
                                         'proof.created_at>v.created_at OR proof.expires_at IS NULL\n'
                                         '   OR v.created_at>=proof.expires_at OR '
                                         'r.created_at>=proof.expires_at OR '
                                         'v.actor_id<>v.requester_id\n'
                                         '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL '
                                         'THEN\n'
                                         "   RAISE EXCEPTION 'Field T1 requires its actual consumed "
                                         "human confirmation' USING ERRCODE='23514'; END IF;\n"
                                         ' END IF;\n'
                                         'END;\n'
                                         '$function$\n',
 'assert_field_common(uuid,uuid,text)': 'CREATE OR REPLACE FUNCTION public.assert_field_common(t uuid, '
                                        'target uuid, kind text)\n'
                                        ' RETURNS void\n'
                                        ' LANGUAGE plpgsql\n'
                                        ' SECURITY DEFINER\n'
                                        " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                        'AS $function$\n'
                                        '\n'
                                        'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref '
                                        'jsonb; basis jsonb; active_sources jsonb;\n'
                                        'BEGIN\n'
                                        '\n'
                                        " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO "
                                        'STRICT v FROM public.field_feedback_versions x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx "
                                        'INTO STRICT v FROM public.field_response_records x WHERE '
                                        'x.tenant_id=t AND x.id=target;\n'
                                        " ELSE RAISE EXCEPTION 'Unknown Field subject' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        '\n'
                                        ' vx=v.tx;\n'
                                        ' SELECT xmin INTO rx FROM public.action_receipts WHERE '
                                        'tenant_id=t AND id=v.receipt_id;\n'
                                        ' PERFORM public.assert_field_members(t,target,kind);\n'
                                        " envelope=v.command->'envelope';\n"
                                        ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR '
                                        'v.requester_id IS DISTINCT FROM public.scope_requester()\n'
                                        '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
                                        'public.category_access(t,v.category_id,true)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        'h.tenant_id=t AND h.id=v.actor_id AND h.active)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE '
                                        "h.tenant_id=t AND h.id=v.requester_id AND h.kind='human' AND "
                                        'h.active)\n'
                                        "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR "
                                        "envelope->>'command_id' IS DISTINCT FROM v.command_id::text\n"
                                        "  OR envelope->>'category_id' IS DISTINCT FROM "
                                        "v.category_id::text OR envelope->>'product_id' IS DISTINCT "
                                        'FROM v.product_id::text\n'
                                        "  OR v.command->'review'->'declaration' IS DISTINCT FROM "
                                        "envelope->'payload'\n"
                                        "  OR v.command->'review'->>'operation' IS DISTINCT FROM "
                                        'v.operation\n'
                                        "  OR v.command->'review'->'sources' IS DISTINCT FROM "
                                        "envelope->'payload'->'sources'\n"
                                        "  OR v.command->'review'->'source_basis' IS DISTINCT FROM "
                                        'v.source_basis OR v.body IS DISTINCT FROM '
                                        "v.command->'review'->'after'\n"
                                        '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.categories c WHERE c.tenant_id=t AND '
                                        'c.id=v.category_id AND '
                                        "c.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.products p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.id=v.product_id AND '
                                        "p.revision::text=envelope->>'expected_revision'))\n"
                                        '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM '
                                        'public.projects p WHERE p.tenant_id=t AND '
                                        'p.category_id=v.category_id AND p.product_id=v.product_id AND '
                                        'p.id=v.project_id))\n'
                                        "  OR NOT coalesce((envelope->'source_read_set') @> "
                                        '(v.reads),false) OR NOT coalesce((v.reads) @> '
                                        "(envelope->'source_read_set'),false)\n"
                                        '  OR '
                                        "jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
                                        '  OR NOT '
                                        'public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
                                        '  OR NOT '
                                        'public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR NOT '
                                        'public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
                                        '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM '
                                        'public.action_receipts r WHERE r.tenant_id=t AND '
                                        'r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS '
                                        'NOT NULL))\n'
                                        '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                        'DISTINCT FROM vx)\n'
                                        '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND x.xmin IS '
                                        'DISTINCT FROM vx)\n'
                                        '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE '
                                        'x.tenant_id=t AND x.receipt_id=v.receipt_id AND '
                                        'x.actor_id=v.actor_id AND x.digest=v.request_digest AND '
                                        'x.xmin=vx AND '
                                        "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') "
                                        'THEN\n'
                                        "  RAISE EXCEPTION 'Field requires actual scope actor sources "
                                        "and one common transaction' USING ERRCODE='23514'; END IF;\n"
                                        ' IF v.confirmation_id IS NOT NULL THEN\n'
                                        '  SELECT xmin INTO px FROM public.confirmations WHERE '
                                        'tenant_id=t AND id=v.confirmation_id;\n'
                                        "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 "
                                        "consumption shares its new fact transaction' USING "
                                        "ERRCODE='23514'; END IF;\n"
                                        ' END IF;\n'
                                        " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT "
                                        "FROM 'array' THEN\n"
                                        "  RAISE EXCEPTION 'Field requires actual direct-source "
                                        "metadata' USING ERRCODE='23514'; END IF;\n"
                                        ' FOR basis IN SELECT value FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
                                        '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        '   AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.id::text=basis->>'id'\n"
                                        "   AND a.revision::text=basis->>'revision' AND "
                                        "a.content_hash=basis->>'hash'\n"
                                        "   AND (v.visibility='private' OR (a.visibility='category' "
                                        'AND (a.product_id IS NULL OR EXISTS(SELECT 1 FROM '
                                        'public.products source_product\n'
                                        '    WHERE source_product.tenant_id=t AND '
                                        'source_product.category_id=v.category_id AND '
                                        'source_product.id=a.product_id AND '
                                        "source_product.visibility='category'))))\n"
                                        "   AND (a.original_id IS NULL OR v.visibility='private' OR "
                                        'EXISTS(SELECT 1 FROM public.uploaded_originals o\n'
                                        '    WHERE o.tenant_id=t AND o.id=a.original_id AND '
                                        "o.visibility='category'))) THEN\n"
                                        "   RAISE EXCEPTION 'Field historical source hash or actual "
                                        "audience changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        " active_sources=CASE WHEN kind='field_feedback' THEN "
                                        "v.sources ELSE envelope->'payload'->'sources' END;\n"
                                        " IF v.operation='field.feedback.followup.link' THEN\n"
                                        '  active_sources=active_sources||coalesce((SELECT '
                                        'jsonb_agg(content.value) FROM '
                                        "jsonb_array_elements(v.source_basis->'result_receipts') "
                                        'result,\n'
                                        '   LATERAL '
                                        "jsonb_array_elements(result->'direct_content_refs') "
                                        "content),'[]'::jsonb);\n"
                                        ' END IF;\n'
                                        ' FOR ref IN SELECT value FROM '
                                        'jsonb_array_elements(active_sources) LOOP\n'
                                        '  SELECT value INTO STRICT basis FROM '
                                        "jsonb_array_elements(v.source_basis->'artifacts') WHERE "
                                        "value->>'id'=ref->>'id';\n"
                                        "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT "
                                        'EXISTS(SELECT 1 FROM jsonb_array_elements(v.reads) rd WHERE '
                                        "rd->>'artifact_id'=ref->>'id' AND "
                                        "rd->'expected_revision'=ref->'revision')\n"
                                        '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a '
                                        'WHERE a.tenant_id=t AND a.category_id=v.category_id\n'
                                        "    AND a.id::text=ref->>'id' AND "
                                        "a.revision::text=ref->>'revision' AND a.status='active'\n"
                                        '    AND a.product_id::text IS NOT DISTINCT FROM '
                                        "basis->>'product_id' AND a.revision::text=basis->>'revision'\n"
                                        "    AND a.content_hash=basis->>'hash' AND "
                                        "a.status=basis->>'status' AND "
                                        "a.owner_id::text=basis->>'owner_id' AND "
                                        "a.visibility=basis->>'visibility'\n"
                                        '    AND ((a.original_id IS NULL AND '
                                        "basis->>'source_kind'='registered_native_text' AND "
                                        'EXISTS(SELECT 1 FROM public.action_receipts r\n'
                                        '      WHERE r.tenant_id=t AND r.subject_id=a.id AND '
                                        "r.subject_revision=a.revision AND r.subject_type='artifact' "
                                        "AND r.operation='evidence.artifact.register'\n"
                                        "       AND r.id::text=basis->'registration'->>'receipt_id' "
                                        "AND r.actor_id::text=basis->'registration'->>'actor_id'\n"
                                        '       AND '
                                        "r.requester_id::text=basis->'registration'->>'requester_id' "
                                        'AND r.run_id::text IS NOT DISTINCT FROM '
                                        "basis->'registration'->>'run_id'))\n"
                                        '     OR (a.original_id IS NOT NULL AND '
                                        "basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
                                        'FROM public.uploaded_originals o\n'
                                        '      JOIN public.original_security sec ON '
                                        'sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
                                        'o.tenant_id=t AND o.category_id=v.category_id\n'
                                        '       AND o.id=a.original_id AND '
                                        "o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
                                        "sec.epoch::text=basis->'original'->>'epoch'\n"
                                        "       AND sec.source_state='active' AND "
                                        "sec.disposition='active' AND "
                                        "sec.source_state=basis->'original'->>'source_state'\n"
                                        '       AND '
                                        "sec.disposition=basis->'original'->>'disposition')))) THEN\n"
                                        "   RAISE EXCEPTION 'Field newly adopted direct source "
                                        "metadata changed' USING ERRCODE='23514'; END IF;\n"
                                        ' END LOOP;\n'
                                        'END;\n'
                                        '$function$\n',
 'assert_field_feedback(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_feedback(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_feedback_versions; prior '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=target;\n'
                                     ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE '
                                     'tenant_id=t AND id=cur.id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' IF vx IS DISTINCT FROM cx OR '
                                     'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
                                     "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field "
                                     "feedback binds actual owner and same-transaction Current' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.create' THEN\n"
                                     '  '
                                     "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
                                     '   '
                                     "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
                                     '  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources' OR v.project_id IS NOT NULL\n"
                                     "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field intake records only its actual "
                                     "declared source report, with unknown location' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     ' ELSE\n'
                                     '  SELECT * INTO STRICT prior FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND id=v.previous_id;\n'
                                     "  location=v.body->'location';\n"
                                     '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS '
                                     'DISTINCT FROM '
                                     'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
                                     '   OR (prior.product_id IS NOT NULL AND prior.product_id IS '
                                     'DISTINCT FROM v.product_id)\n'
                                     "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT "
                                     'FROM '
                                     "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
                                     "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
                                     "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
                                     "(prior.body-ARRAY['revision','location'])\n"
                                     "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
                                     "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR "
                                     "location->>'state' IS DISTINCT FROM 'known'\n"
                                     "   OR location->>'product_id' IS DISTINCT FROM "
                                     "v.product_id::text OR location->>'project_id' IS DISTINCT FROM "
                                     'v.project_id::text\n'
                                     "   OR location->'engineering_configuration' IS DISTINCT FROM "
                                     "payload->'engineering_configuration'\n"
                                     "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
                                     "payload->'manufacturing_configuration'\n"
                                     "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
                                     "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb "
                                     "AND payload->>'project_id' IS DISTINCT FROM v.project_id::text)\n"
                                     '   OR NOT coalesce((v.sources) @> (prior.sources),false) OR NOT '
                                     "coalesce((v.sources) @> (payload->'sources'),false)\n"
                                     "   OR NOT coalesce((v.sources) @> (location->'sources'),false)\n"
                                     '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) '
                                     'source WHERE NOT((prior.sources) @> (jsonb_build_array(source))\n'
                                     "    OR (payload->'sources') @> (jsonb_build_array(source)) OR "
                                     "(location->'sources') @> (jsonb_build_array(source)))) THEN\n"
                                     "   RAISE EXCEPTION 'Field location preserves report, privacy and "
                                     "exact predecessor; known product cannot silently change' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations '
                                     'engineering WHERE engineering.tenant_id=t AND '
                                     'engineering.category_id=v.category_id\n'
                                     '   AND engineering.product_id=v.product_id AND '
                                     "engineering.id::text=location->'engineering_configuration'->>'id'\n"
                                     '   AND '
                                     "engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '   AND coalesce((v.reads) @> '
                                     '(engineering.required_source_read_set),false)\n'
                                     "   AND (v.visibility='private' OR "
                                     "engineering.visibility='category')\n"
                                     '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM '
                                     'public.project_product_links link WHERE link.tenant_id=t AND '
                                     'link.category_id=v.category_id\n'
                                     '    AND link.product_id=v.product_id AND '
                                     'link.project_id=v.project_id AND '
                                     'link.definition_id=engineering.definition_id AND '
                                     'link.definition_revision=engineering.definition_revision))) '
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field location requires an actual "
                                     "engineering configuration in the selected project' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     '  IF '
                                     "coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.process_revisions '
                                     'manufacturing\n'
                                     '   WHERE manufacturing.tenant_id=t AND '
                                     'manufacturing.category_id=v.category_id AND '
                                     'manufacturing.product_id=v.product_id\n'
                                     '    AND '
                                     "manufacturing.id::text=location->'manufacturing_configuration'->>'id' "
                                     'AND '
                                     "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     '    AND '
                                     "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND coalesce((v.reads) @> '
                                     '(manufacturing.required_source_read_set),false) AND '
                                     "(v.visibility='private' OR manufacturing.visibility='category')) "
                                     'THEN\n'
                                     "   RAISE EXCEPTION 'Field manufacturing configuration must match "
                                     "actual engineering configuration' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb "
                                     'AND NOT EXISTS(SELECT 1 FROM public.build_lots lot\n'
                                     '   JOIN public.actual_configurations actual ON '
                                     'actual.tenant_id=lot.tenant_id AND '
                                     'actual.product_id=lot.product_id AND '
                                     'actual.id=lot.actual_configuration_id\n'
                                     '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND '
                                     'lot.product_id=v.product_id AND lot.project_id=v.project_id\n'
                                     "    AND lot.id::text=location->'batch'->>'id' AND "
                                     "lot.revision::text=location->'batch'->>'revision'\n"
                                     '    AND actual.revision=lot.actual_configuration_revision\n'
                                     '    AND '
                                     "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
                                     '    AND '
                                     "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
                                     "    AND (payload->>'project_id' IS NULL OR "
                                     "payload->>'project_id'=lot.project_id::text)\n"
                                     '    AND coalesce((v.reads) @> '
                                     '(lot.required_source_read_set),false) AND coalesce((v.reads) @> '
                                     '(actual.required_source_read_set),false)\n'
                                     "    AND (v.visibility='private' OR (lot.visibility='category' "
                                     "AND actual.visibility='category'))) THEN\n"
                                     "   RAISE EXCEPTION 'Field batch requires exact native lot and "
                                     "actual physical configuration' USING ERRCODE='23514'; END IF;\n"
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n',
 'assert_field_response(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, '
                                     'target uuid)\n'
                                     ' RETURNS void\n'
                                     ' LANGUAGE plpgsql\n'
                                     ' SECURITY DEFINER\n'
                                     " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                     'AS $function$\n'
                                     '\n'
                                     'DECLARE v public.field_response_records; parent '
                                     'public.field_feedback_versions; cur '
                                     'public.field_feedback_currents;\n'
                                     ' payload jsonb; expected jsonb; result jsonb; native_receipt '
                                     'public.action_receipts;\n'
                                     'BEGIN\n'
                                     ' SELECT * INTO STRICT v FROM public.field_response_records WHERE '
                                     'tenant_id=t AND id=target;\n'
                                     " PERFORM public.assert_field_common(t,target,'field_response');\n"
                                     ' SELECT * INTO STRICT parent FROM public.field_feedback_versions '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'id=v.feedback_version_id;\n'
                                     ' SELECT * INTO STRICT cur FROM public.field_feedback_currents '
                                     'WHERE tenant_id=t AND category_id=v.category_id AND '
                                     'feedback_id=v.feedback_id;\n'
                                     " payload=v.command->'envelope'->'payload';\n"
                                     ' '
                                     "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
                                     '  '
                                     "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
                                     ' IF '
                                     'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
                                     '  IS DISTINCT FROM '
                                     'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
                                     '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
                                     "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' "
                                     "AND v.visibility<>'private')\n"
                                     "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
                                     "  OR payload->'feedback' IS DISTINCT FROM "
                                     "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
                                     '  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT '
                                     "FROM payload->'sources'\n"
                                     "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM "
                                     "(payload->>'occurred_at')::timestamptz\n"
                                     '  OR '
                                     "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
                                     "  OR (v.operation='field.feedback.action.record' AND "
                                     "(payload->>'action_kind' IS DISTINCT FROM v.response_kind OR "
                                     "v.body->'result_receipts'<>'[]'::jsonb))\n"
                                     "  OR NOT coalesce((v.source_basis->'artifacts') @> "
                                     "(parent.source_basis->'artifacts'),false) THEN\n"
                                     "  RAISE EXCEPTION 'Field response binds exact current parent and "
                                     "new actual facts without advancing its report' USING "
                                     "ERRCODE='23514'; END IF;\n"
                                     " IF v.operation='field.feedback.followup.link' THEN\n"
                                     '  IF v.project_id IS NULL OR '
                                     "jsonb_array_length(payload->'result_receipts')=0\n"
                                     '   OR '
                                     "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
                                     '   OR EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') result "
                                     "WHERE result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
                                     "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text "
                                     'OR NOT EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(payload->'result_receipts') requested WHERE "
                                     "requested->'receipt_id'=result->'receipt_id')) THEN\n"
                                     "   RAISE EXCEPTION 'Field follow-up references only finite fixed "
                                     "native results in its actual project' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  FOR result IN SELECT value FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
                                     '   SELECT * INTO STRICT native_receipt FROM '
                                     'public.action_receipts r WHERE r.tenant_id=t AND '
                                     'r.category_id=v.category_id\n'
                                     "    AND r.id::text=result->>'receipt_id' AND "
                                     "r.product_id=v.product_id AND r.operation=result->>'operation'\n"
                                     "    AND r.subject_type=result->>'subject_type' AND "
                                     "r.subject_id::text=result->>'subject_id'\n"
                                     "    AND r.subject_revision::text=result->>'subject_revision' AND "
                                     "r.request_digest=result->>'receipt_request_digest'\n"
                                     "    AND r.visibility=result->>'receipt_visibility';\n"
                                     "   IF (v.visibility='category' AND "
                                     "(native_receipt.visibility<>'category' OR "
                                     "result->>'visibility'<>'category'\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE '
                                     'p.tenant_id=t AND p.id=v.product_id AND '
                                     "p.visibility='category')\n"
                                     '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE '
                                     'p.tenant_id=t AND p.id=v.project_id AND '
                                     "p.visibility='category')))\n"
                                     '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE '
                                     'a.tenant_id=t AND a.category_id=v.category_id AND '
                                     'a.receipt_id=native_receipt.id\n'
                                     '     AND a.actor_id=native_receipt.actor_id AND '
                                     'a.operation=native_receipt.operation)\n'
                                     '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE '
                                     'e.tenant_id=t AND e.category_id=v.category_id AND '
                                     'e.receipt_id=native_receipt.id\n'
                                     '     AND e.subject_id=native_receipt.subject_id AND '
                                     'e.subject_revision=native_receipt.subject_revision AND '
                                     'e.actor_id=native_receipt.actor_id\n'
                                     '     AND e.schema_version=1 AND '
                                     'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
                                     'THEN\n'
                                     "    RAISE EXCEPTION 'Field follow-up requires actual native "
                                     "receipt audit event and audience' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  END LOOP;\n'
                                     ' END IF;\n'
                                     'END;\n'
                                     '$function$\n'}

SCHEMA_SQL = ('CREATE OR REPLACE FUNCTION public.assert_field_members(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v record; r public.action_receipts; proof public.confirmations; expected jsonb; event_name '
 'text;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE WHEN "
 "kind='field_response' THEN 'recorded' WHEN v.body->'location' IS NOT NULL AND "
 "v.body->'location'<>'null'::jsonb THEN 'located' ELSE 'unknown' END,\n"
 "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
 " event_name=CASE v.operation WHEN 'field.feedback.create' THEN 'field.feedback_created' WHEN "
 "'field.feedback.locate' THEN 'field.feedback_located'\n"
 "  WHEN 'field.feedback.action.record' THEN 'field.feedback_action_recorded' WHEN "
 "'field.feedback.followup.link' THEN 'field.feedback_followup_linked' END;\n"
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR r.result IS DISTINCT FROM expected OR r.created_at<v.created_at OR event_name IS NULL\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation '
 'AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.operation=v.operation AND x.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.type=event_name AND x.subject_id=v.id AND x.subject_revision=v.revision AND x.schema_version=1 AND '
 'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND x.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR (v.command->'envelope') ? 'idempotency_key' OR (v.command->'envelope'->'payload') ? "
 "'confirmation_token'\n"
 "  OR (v.command->'envelope'->'payload') ? 'approval_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
 'x.digest=v.request_digest AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field original receipt audit event or request key mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF v.operation<>'field.feedback.create' THEN\n"
 '  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF proof.consumed IS DISTINCT FROM true OR '
 'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE WHEN v.product_id IS '
 "NULL THEN 'category' ELSE 'product' "
 "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
 "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at OR "
 'proof.expires_at IS NULL\n'
 '   OR v.created_at>=proof.expires_at OR r.created_at>=proof.expires_at OR '
 'v.actor_id<>v.requester_id\n'
 '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'Field T1 requires its actual consumed human confirmation' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END IF;\n'
 'END;\n'
 '$field$',
 'CREATE OR REPLACE FUNCTION public.assert_field_common(t uuid,target uuid,kind text) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb; active_sources '
 'jsonb;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 ' vx=v.tx;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_field_members(t,target,kind);\n'
 " envelope=v.command->'envelope';\n"
 ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND '
 'h.active)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.requester_id AND '
 "h.kind='human' AND h.active)\n"
 "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM "
 'v.command_id::text\n'
 "  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM envelope->'payload'->'sources'\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis OR v.body IS DISTINCT FROM "
 "v.command->'review'->'after'\n"
 '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND '
 "c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.id=v.product_id AND '
 "p.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))\n'
 "  OR NOT coalesce((envelope->'source_read_set') @> (v.reads),false) OR NOT coalesce((v.reads) @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 '  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field requires actual scope actor sources and one common transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 consumption shares its new fact "
 "transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Field requires actual direct-source metadata' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash'\n"
 "   AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR "
 'EXISTS(SELECT 1 FROM public.products source_product\n'
 '    WHERE source_product.tenant_id=t AND source_product.category_id=v.category_id AND '
 "source_product.id=a.product_id AND source_product.visibility='category'))))\n"
 "   AND (a.original_id IS NULL OR v.visibility='private' OR EXISTS(SELECT 1 FROM "
 'public.uploaded_originals o\n'
 "    WHERE o.tenant_id=t AND o.id=a.original_id AND o.visibility='category'))) THEN\n"
 "   RAISE EXCEPTION 'Field historical source hash or actual audience changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 " active_sources=CASE WHEN kind='field_feedback' THEN v.sources ELSE envelope->'payload'->'sources' "
 'END;\n'
 " IF v.operation='field.feedback.followup.link' THEN\n"
 '  active_sources=active_sources||coalesce((SELECT jsonb_agg(content.value) FROM '
 "jsonb_array_elements(v.source_basis->'result_receipts') result,\n"
 "   LATERAL jsonb_array_elements(result->'direct_content_refs') content),'[]'::jsonb);\n"
 ' END IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(active_sources) LOOP\n'
 "  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE "
 "value->>'id'=ref->>'id';\n"
 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND "
 "rd->'expected_revision'=ref->'revision')\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'\n"
 "    AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND "
 "a.revision::text=basis->>'revision'\n"
 "    AND a.content_hash=basis->>'hash' AND a.status=basis->>'status' AND "
 "a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'\n"
 "    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(SELECT "
 '1 FROM public.action_receipts r\n'
 '      WHERE r.tenant_id=t AND r.subject_id=a.id AND r.subject_revision=a.revision AND '
 "r.subject_type='artifact' AND r.operation='evidence.artifact.register'\n"
 "       AND r.id::text=basis->'registration'->>'receipt_id' AND "
 "r.actor_id::text=basis->'registration'->>'actor_id'\n"
 "       AND r.requester_id::text=basis->'registration'->>'requester_id' AND r.run_id::text IS NOT "
 "DISTINCT FROM basis->'registration'->>'run_id'))\n"
 "     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
 'FROM public.uploaded_originals o\n'
 '      JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
 'o.tenant_id=t AND o.category_id=v.category_id\n'
 "       AND o.id=a.original_id AND o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
 "sec.epoch::text=basis->'original'->>'epoch'\n"
 "       AND sec.source_state='active' AND sec.disposition='active' AND "
 "sec.source_state=basis->'original'->>'source_state'\n"
 "       AND sec.disposition=basis->'original'->>'disposition')))) THEN\n"
 "   RAISE EXCEPTION 'Field newly adopted direct source metadata changed' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$field$',
 'CREATE OR REPLACE FUNCTION public.assert_field_feedback(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v public.field_feedback_versions; prior public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=t AND id=cur.id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' IF vx IS DISTINCT FROM cx OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
 "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field feedback binds actual owner and "
 "same-transaction Current' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.create' THEN\n"
 '  '
 "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
 '   '
 "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
 "  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources' OR "
 'v.project_id IS NOT NULL\n'
 "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
 "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb THEN\n"
 "   RAISE EXCEPTION 'Field intake records only its actual declared source report, with unknown "
 "location' USING ERRCODE='23514'; END IF;\n"
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  location=v.body->'location';\n"
 '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS DISTINCT FROM '
 'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
 '   OR (prior.product_id IS NOT NULL AND prior.product_id IS DISTINCT FROM v.product_id)\n'
 "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
 "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
 "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
 "(prior.body-ARRAY['revision','location'])\n"
 "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
 "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR location->>'state' IS DISTINCT FROM "
 "'known'\n"
 "   OR location->>'product_id' IS DISTINCT FROM v.product_id::text OR location->>'project_id' IS "
 'DISTINCT FROM v.project_id::text\n'
 "   OR location->'engineering_configuration' IS DISTINCT FROM payload->'engineering_configuration'\n"
 "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
 "payload->'manufacturing_configuration'\n"
 "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
 "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb AND payload->>'project_id' IS DISTINCT "
 'FROM v.project_id::text)\n'
 '   OR NOT coalesce((v.sources) @> (prior.sources),false) OR NOT coalesce((v.sources) @> '
 "(payload->'sources'),false)\n"
 "   OR NOT coalesce((v.sources) @> (location->'sources'),false)\n"
 '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) source WHERE NOT((prior.sources) @> '
 '(jsonb_build_array(source))\n'
 "    OR (payload->'sources') @> (jsonb_build_array(source)) OR (location->'sources') @> "
 '(jsonb_build_array(source)))) THEN\n'
 "   RAISE EXCEPTION 'Field location preserves report, privacy and exact predecessor; known product "
 "cannot silently change' USING ERRCODE='23514'; END IF;\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations engineering WHERE '
 'engineering.tenant_id=t AND engineering.category_id=v.category_id\n'
 '   AND engineering.product_id=v.product_id AND '
 "engineering.id::text=location->'engineering_configuration'->>'id'\n"
 "   AND engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
 '   AND coalesce((v.reads) @> (engineering.required_source_read_set),false)\n'
 "   AND (v.visibility='private' OR engineering.visibility='category')\n"
 '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM public.project_product_links link WHERE '
 'link.tenant_id=t AND link.category_id=v.category_id\n'
 '    AND link.product_id=v.product_id AND link.project_id=v.project_id AND '
 'link.definition_id=engineering.definition_id AND '
 'link.definition_revision=engineering.definition_revision))) THEN\n'
 "   RAISE EXCEPTION 'Field location requires an actual engineering configuration in the selected "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb AND NOT "
 'EXISTS(SELECT 1 FROM public.process_revisions manufacturing\n'
 '   WHERE manufacturing.tenant_id=t AND manufacturing.category_id=v.category_id AND '
 'manufacturing.product_id=v.product_id\n'
 "    AND manufacturing.id::text=location->'manufacturing_configuration'->>'id' AND "
 "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
 '    AND '
 "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 '    AND coalesce((v.reads) @> (manufacturing.required_source_read_set),false) AND '
 "(v.visibility='private' OR manufacturing.visibility='category')) THEN\n"
 "   RAISE EXCEPTION 'Field manufacturing configuration must match actual engineering configuration' "
 "USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM "
 'public.build_lots lot\n'
 '   JOIN public.actual_configurations actual ON actual.tenant_id=lot.tenant_id AND '
 'actual.product_id=lot.product_id AND actual.id=lot.actual_configuration_id\n'
 '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND lot.product_id=v.product_id AND '
 'lot.project_id=v.project_id\n'
 "    AND lot.id::text=location->'batch'->>'id' AND lot.revision::text=location->'batch'->>'revision'\n"
 '    AND actual.revision=lot.actual_configuration_revision\n'
 '    AND '
 "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 "    AND actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
 '    AND '
 "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
 '    AND '
 "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
 "    AND (payload->>'project_id' IS NULL OR payload->>'project_id'=lot.project_id::text)\n"
 '    AND coalesce((v.reads) @> (lot.required_source_read_set),false) AND coalesce((v.reads) @> '
 '(actual.required_source_read_set),false)\n'
 "    AND (v.visibility='private' OR (lot.visibility='category' AND actual.visibility='category'))) "
 'THEN\n'
 "   RAISE EXCEPTION 'Field batch requires exact native lot and actual physical configuration' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$field$',
 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v public.field_response_records; parent public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; result jsonb; native_receipt public.action_receipts;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_response_records WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_response');\n"
 ' SELECT * INTO STRICT parent FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'category_id=v.category_id AND id=v.feedback_version_id;\n'
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' '
 "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
 '  '
 "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
 ' IF '
 'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
 '  IS DISTINCT FROM '
 'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
 '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
 "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' AND v.visibility<>'private')\n"
 "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
 "  OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
 "  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources'\n"
 "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM (payload->>'occurred_at')::timestamptz\n"
 "  OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
 "  OR (v.operation='field.feedback.action.record' AND (payload->>'action_kind' IS DISTINCT FROM "
 "v.response_kind OR v.body->'result_receipts'<>'[]'::jsonb))\n"
 "  OR NOT coalesce((v.source_basis->'artifacts') @> (parent.source_basis->'artifacts'),false) THEN\n"
 "  RAISE EXCEPTION 'Field response binds exact current parent and new actual facts without advancing "
 "its report' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.followup.link' THEN\n"
 "  IF v.project_id IS NULL OR jsonb_array_length(payload->'result_receipts')=0\n"
 '   OR '
 "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
 "   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') result WHERE "
 "result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
 "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(payload->'result_receipts') requested WHERE "
 "requested->'receipt_id'=result->'receipt_id')) THEN\n"
 "   RAISE EXCEPTION 'Field follow-up references only finite fixed native results in its actual "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  FOR result IN SELECT value FROM jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
 '   SELECT * INTO STRICT native_receipt FROM public.action_receipts r WHERE r.tenant_id=t AND '
 'r.category_id=v.category_id\n'
 "    AND r.id::text=result->>'receipt_id' AND r.product_id=v.product_id AND "
 "r.operation=result->>'operation'\n"
 "    AND r.subject_type=result->>'subject_type' AND r.subject_id::text=result->>'subject_id'\n"
 "    AND r.subject_revision::text=result->>'subject_revision' AND "
 "r.request_digest=result->>'receipt_request_digest'\n"
 "    AND r.visibility=result->>'receipt_visibility';\n"
 "   IF (v.visibility='category' AND (native_receipt.visibility<>'category' OR "
 "result->>'visibility'<>'category'\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.id=v.product_id AND '
 "p.visibility='category')\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.id=v.project_id AND '
 "p.visibility='category')))\n"
 '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id AND a.receipt_id=native_receipt.id\n'
 '     AND a.actor_id=native_receipt.actor_id AND a.operation=native_receipt.operation)\n'
 '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND '
 'e.category_id=v.category_id AND e.receipt_id=native_receipt.id\n'
 '     AND e.subject_id=native_receipt.subject_id AND '
 'e.subject_revision=native_receipt.subject_revision AND e.actor_id=native_receipt.actor_id\n'
 '     AND e.schema_version=1 AND '
 'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
 'THEN\n'
 "    RAISE EXCEPTION 'Field follow-up requires actual native receipt audit event and audience' USING "
 "ERRCODE='23514'; END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 'END;\n'
 '$field$')

DOWNGRADE_SQL = ('DO $field$ BEGIN IF EXISTS(SELECT 1 FROM public.field_feedback_versions WHERE revision>1) OR '
 "EXISTS(SELECT 1 FROM public.field_response_records) THEN RAISE EXCEPTION 'Field location and "
 "response history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $field$",
 'CREATE OR REPLACE FUNCTION public.assert_field_common(t uuid, target uuid, kind text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; envelope jsonb; vx xid; rx xid; px xid; ref jsonb; basis jsonb; active_sources '
 'jsonb;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 ' vx=v.tx;\n'
 ' SELECT xmin INTO rx FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' PERFORM public.assert_field_members(t,target,kind);\n'
 " envelope=v.command->'envelope';\n"
 ' IF v.actor_id IS DISTINCT FROM public.scope_actor() OR v.requester_id IS DISTINCT FROM '
 'public.scope_requester()\n'
 '  OR v.writer_id<>v.actor_id OR vx IS DISTINCT FROM rx OR NOT '
 'public.category_access(t,v.category_id,true)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.actor_id AND '
 'h.active)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=t AND h.id=v.requester_id AND '
 "h.kind='human' AND h.active)\n"
 "  OR envelope->>'operation' IS DISTINCT FROM v.operation OR envelope->>'command_id' IS DISTINCT FROM "
 'v.command_id::text\n'
 "  OR envelope->>'category_id' IS DISTINCT FROM v.category_id::text OR envelope->>'product_id' IS "
 'DISTINCT FROM v.product_id::text\n'
 "  OR v.command->'review'->'declaration' IS DISTINCT FROM envelope->'payload'\n"
 "  OR v.command->'review'->>'operation' IS DISTINCT FROM v.operation\n"
 "  OR v.command->'review'->'sources' IS DISTINCT FROM envelope->'payload'->'sources'\n"
 "  OR v.command->'review'->'source_basis' IS DISTINCT FROM v.source_basis OR v.body IS DISTINCT FROM "
 "v.command->'review'->'after'\n"
 '  OR (v.product_id IS NULL AND NOT EXISTS(SELECT 1 FROM public.categories c WHERE c.tenant_id=t AND '
 "c.id=v.category_id AND c.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.id=v.product_id AND '
 "p.revision::text=envelope->>'expected_revision'))\n"
 '  OR (v.project_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t '
 'AND p.category_id=v.category_id AND p.product_id=v.product_id AND p.id=v.project_id))\n'
 "  OR NOT coalesce(envelope->'source_read_set' @> v.reads,false) OR NOT coalesce(v.reads @> "
 "(envelope->'source_read_set'),false)\n"
 "  OR jsonb_array_length(envelope->'source_read_set')<>jsonb_array_length(v.reads)\n"
 '  OR NOT public.direct_source_set_visible(t,v.category_id,v.product_id,v.reads)\n'
 '  OR NOT public.knowledge_content_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR NOT public.knowledge_result_sources_visible(t,v.category_id,v.product_id,v.source_basis)\n'
 '  OR (v.actor_id<>v.requester_id AND NOT EXISTS(SELECT 1 FROM public.action_receipts r WHERE '
 'r.tenant_id=t AND r.id=v.receipt_id AND coalesce(r.agent_run_id,r.run_id) IS NOT NULL))\n'
 '  OR EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND x.receipt_id=v.receipt_id '
 'AND x.xmin IS DISTINCT FROM vx)\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND x.digest=v.request_digest AND x.xmin=vx AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field requires actual scope actor sources and one common transaction' USING "
 "ERRCODE='23514'; END IF;\n"
 ' IF v.confirmation_id IS NOT NULL THEN\n'
 '  SELECT xmin INTO px FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 "  IF px IS DISTINCT FROM vx THEN RAISE EXCEPTION 'Field T1 consumption shares its new fact "
 "transaction' USING ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 " IF jsonb_typeof(v.source_basis->'artifacts') IS DISTINCT FROM 'array' THEN\n"
 "  RAISE EXCEPTION 'Field requires actual direct-source metadata' USING ERRCODE='23514'; END IF;\n"
 " FOR basis IN SELECT value FROM jsonb_array_elements(v.source_basis->'artifacts') LOOP\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "   AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND a.id::text=basis->>'id'\n"
 "   AND a.revision::text=basis->>'revision' AND a.content_hash=basis->>'hash'\n"
 "   AND (v.visibility='private' OR (a.visibility='category' AND (a.product_id IS NULL OR "
 'EXISTS(SELECT 1 FROM public.products source_product\n'
 '    WHERE source_product.tenant_id=t AND source_product.category_id=v.category_id AND '
 "source_product.id=a.product_id AND source_product.visibility='category'))))\n"
 "   AND (a.original_id IS NULL OR v.visibility='private' OR EXISTS(SELECT 1 FROM "
 'public.uploaded_originals o\n'
 "    WHERE o.tenant_id=t AND o.id=a.original_id AND o.visibility='category'))) THEN\n"
 "   RAISE EXCEPTION 'Field historical source hash or actual audience changed' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END LOOP;\n'
 " active_sources=CASE WHEN kind='field_feedback' THEN v.sources ELSE envelope->'payload'->'sources' "
 'END;\n'
 " IF v.operation='field.feedback.followup.link' THEN\n"
 '  active_sources=active_sources||coalesce((SELECT jsonb_agg(content.value) FROM '
 "jsonb_array_elements(v.source_basis->'result_receipts') result,\n"
 "   LATERAL jsonb_array_elements(result->'direct_content_refs') content),'[]'::jsonb);\n"
 ' END IF;\n'
 ' FOR ref IN SELECT value FROM jsonb_array_elements(active_sources) LOOP\n'
 "  SELECT value INTO STRICT basis FROM jsonb_array_elements(v.source_basis->'artifacts') WHERE "
 "value->>'id'=ref->>'id';\n"
 "  IF ref->>'kind' IS DISTINCT FROM 'artifact' OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(v.reads) rd WHERE rd->>'artifact_id'=ref->>'id' AND "
 "rd->'expected_revision'=ref->'revision')\n"
 '   OR NOT EXISTS(SELECT 1 FROM public.artifact_versions a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id\n'
 "    AND a.id::text=ref->>'id' AND a.revision::text=ref->>'revision' AND a.status='active'\n"
 "    AND a.product_id::text IS NOT DISTINCT FROM basis->>'product_id' AND "
 "a.revision::text=basis->>'revision'\n"
 "    AND a.content_hash=basis->>'hash' AND a.status=basis->>'status' AND "
 "a.owner_id::text=basis->>'owner_id' AND a.visibility=basis->>'visibility'\n"
 "    AND ((a.original_id IS NULL AND basis->>'source_kind'='registered_native_text' AND EXISTS(SELECT "
 '1 FROM public.action_receipts r\n'
 '      WHERE r.tenant_id=t AND r.subject_id=a.id AND r.subject_revision=a.revision AND '
 "r.subject_type='artifact' AND r.operation='evidence.artifact.register'\n"
 "       AND r.id::text=basis->'registration'->>'receipt_id' AND "
 "r.actor_id::text=basis->'registration'->>'actor_id'\n"
 "       AND r.requester_id::text=basis->'registration'->>'requester_id' AND r.run_id::text IS NOT "
 "DISTINCT FROM basis->'registration'->>'run_id'))\n"
 "     OR (a.original_id IS NOT NULL AND basis->>'source_kind'='uploaded_original' AND EXISTS(SELECT 1 "
 'FROM public.uploaded_originals o\n'
 '      JOIN public.original_security sec ON sec.tenant_id=o.tenant_id AND sec.original_id=o.id WHERE '
 'o.tenant_id=t AND o.category_id=v.category_id\n'
 "       AND o.id=a.original_id AND o.id::text=basis->'original'->>'id' AND o.status='parsed' AND "
 "sec.epoch::text=basis->'original'->>'epoch'\n"
 "       AND sec.source_state='active' AND sec.disposition='active' AND "
 "sec.source_state=basis->'original'->>'source_state'\n"
 "       AND sec.disposition=basis->'original'->>'disposition')))) THEN\n"
 "   RAISE EXCEPTION 'Field newly adopted direct source metadata changed' USING ERRCODE='23514'; END "
 'IF;\n'
 ' END LOOP;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.assert_field_members(t uuid, target uuid, kind text)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v record; r public.action_receipts; proof public.confirmations; expected jsonb; event_name '
 'text;\n'
 'BEGIN\n'
 '\n'
 " IF kind='field_feedback' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_feedback_versions x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSIF kind='field_response' THEN SELECT x.*,x.xmin AS tx INTO STRICT v FROM "
 'public.field_response_records x WHERE x.tenant_id=t AND x.id=target;\n'
 " ELSE RAISE EXCEPTION 'Unknown Field subject' USING ERRCODE='23514'; END IF;\n"
 '\n'
 " expected=jsonb_build_object('id',v.id,'revision',v.revision,'status',CASE WHEN "
 "kind='field_response' THEN 'recorded' WHEN v.body->'location' IS NOT NULL AND "
 "v.body->'location'<>'null'::jsonb THEN 'located' ELSE 'unknown' END,\n"
 "  'feedback_id',v.feedback_id,'project_id',v.project_id);\n"
 " event_name=CASE v.operation WHEN 'field.feedback.create' THEN 'field.feedback_created' WHEN "
 "'field.feedback.locate' THEN 'field.feedback_located'\n"
 "  WHEN 'field.feedback.action.record' THEN 'field.feedback_action_recorded' WHEN "
 "'field.feedback.followup.link' THEN 'field.feedback_followup_linked' END;\n"
 ' SELECT * INTO STRICT r FROM public.action_receipts WHERE tenant_id=t AND id=v.receipt_id;\n'
 ' IF '
 'ROW(r.category_id,r.product_id,r.command_id,r.confirmation_id,r.actor_id,r.requester_id,r.operation,r.subject_type,r.subject_id,r.subject_revision,r.visibility,r.request_digest,r.intent_digest)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.command_id,v.confirmation_id,v.actor_id,v.requester_id,v.operation,kind::varchar,v.id,v.revision,v.visibility,v.request_digest,v.intent_digest)\n'
 '  OR r.result IS DISTINCT FROM expected OR r.created_at<v.created_at OR event_name IS NULL\n'
 '  OR (SELECT count(*) FROM public.action_receipts x WHERE x.tenant_id=t AND x.operation=v.operation '
 'AND x.subject_type=kind AND x.subject_id=v.id AND x.subject_revision=v.revision)<>1\n'
 '  OR (SELECT count(*) FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.audit_entries x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.operation=v.operation AND x.created_at>=v.created_at)\n'
 '  OR (SELECT count(*) FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id)<>1\n'
 '  OR NOT EXISTS(SELECT 1 FROM public.outbox_events x WHERE x.tenant_id=t AND '
 'x.receipt_id=v.receipt_id AND x.category_id=v.category_id AND x.actor_id=v.actor_id AND '
 'x.type=event_name AND x.subject_id=v.id AND x.subject_revision=v.revision AND x.schema_version=1 AND '
 'x.correlation_id=coalesce(r.agent_run_id,r.run_id,v.command_id) AND x.created_at>=v.created_at)\n'
 "  OR v.command->>'original_key_sha256' IS NULL OR v.command->>'original_key_sha256' !~ "
 "'^[a-f0-9]{64}$'\n"
 "  OR v.command->'envelope' ? 'idempotency_key' OR v.command->'envelope'->'payload' ? "
 "'confirmation_token'\n"
 "  OR v.command->'envelope'->'payload' ? 'approval_token'\n"
 '  OR NOT EXISTS(SELECT 1 FROM public.request_keys x WHERE x.tenant_id=t AND '
 'x.category_id=v.category_id AND x.receipt_id=v.receipt_id AND x.actor_id=v.actor_id AND '
 'x.digest=v.request_digest AND '
 "encode(sha256(convert_to(x.key,'UTF8')),'hex')=v.command->>'original_key_sha256') THEN\n"
 "  RAISE EXCEPTION 'Field original receipt audit event or request key mismatch' USING "
 "ERRCODE='23514'; END IF;\n"
 " IF v.operation<>'field.feedback.create' THEN\n"
 '  SELECT * INTO STRICT proof FROM public.confirmations WHERE tenant_id=t AND id=v.confirmation_id;\n'
 '  IF proof.consumed IS DISTINCT FROM true OR '
 'ROW(proof.category_id,proof.product_id,proof.actor_id,proof.operation,proof.subject_type,proof.subject_id,proof.revision)\n'
 '   IS DISTINCT FROM ROW(v.category_id,v.product_id,v.actor_id,v.operation,(CASE WHEN v.product_id IS '
 "NULL THEN 'category' ELSE 'product' "
 "END)::varchar,coalesce(v.product_id,v.category_id),(v.command->'envelope'->>'expected_revision')::integer)\n"
 "   OR proof.snapshot IS DISTINCT FROM v.command->'review' OR proof.created_at>v.created_at OR "
 'proof.expires_at IS NULL\n'
 '   OR v.created_at>=proof.expires_at OR r.created_at>=proof.expires_at OR '
 'v.actor_id<>v.requester_id\n'
 '   OR r.run_id IS NOT NULL OR r.agent_run_id IS NOT NULL THEN\n'
 "   RAISE EXCEPTION 'Field T1 requires its actual consumed human confirmation' USING ERRCODE='23514'; "
 'END IF;\n'
 ' END IF;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.assert_field_feedback(t uuid, target uuid)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v public.field_feedback_versions; prior public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; location jsonb; vx xid; cx xid;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 ' SELECT xmin INTO vx FROM public.field_feedback_versions WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_feedback');\n"
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 ' SELECT xmin INTO cx FROM public.field_feedback_currents WHERE tenant_id=t AND id=cur.id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' IF vx IS DISTINCT FROM cx OR '
 'ROW(cur.category_id,cur.product_id,cur.project_id,cur.owner_id,cur.visibility,cur.feedback_id,cur.version_id,cur.revision)\n'
 '  IS DISTINCT FROM '
 'ROW(v.category_id,v.product_id,v.project_id,v.owner_id,v.visibility,v.feedback_id,v.id,v.revision)\n'
 "  OR v.owner_id<>v.requester_id THEN RAISE EXCEPTION 'Field feedback binds actual owner and "
 "same-transaction Current' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.create' THEN\n"
 '  '
 "expected=jsonb_build_object('feedback_id',v.feedback_id,'revision',1,'title',payload->'title','description',payload->'description',\n"
 '   '
 "'channel',payload->'channel','feedback_kind',payload->'feedback_kind','received_at',payload->'received_at','reported',payload->'reported','purpose',payload->'purpose','location',NULL);\n"
 "  IF v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources' OR "
 'v.project_id IS NOT NULL\n'
 "   OR payload->>'visibility' IS DISTINCT FROM v.visibility OR "
 "coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb THEN\n"
 "   RAISE EXCEPTION 'Field intake records only its actual declared source report, with unknown "
 "location' USING ERRCODE='23514'; END IF;\n"
 ' ELSE\n'
 '  SELECT * INTO STRICT prior FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'id=v.previous_id;\n'
 "  location=v.body->'location';\n"
 '  IF ROW(v.category_id,v.owner_id,v.visibility,v.feedback_id) IS DISTINCT FROM '
 'ROW(prior.category_id,prior.owner_id,prior.visibility,prior.feedback_id)\n'
 '   OR (prior.product_id IS NOT NULL AND prior.product_id IS DISTINCT FROM v.product_id)\n'
 "   OR v.product_id IS NULL OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',v.feedback_id,'revision',prior.revision)\n"
 "   OR v.command->'review'->'before' IS DISTINCT FROM prior.body\n"
 "   OR (v.body-ARRAY['revision','location']) IS DISTINCT FROM "
 "(prior.body-ARRAY['revision','location'])\n"
 "   OR v.body->'revision' IS DISTINCT FROM to_jsonb(v.revision)\n"
 "   OR jsonb_typeof(location) IS DISTINCT FROM 'object' OR location->>'state' IS DISTINCT FROM "
 "'known'\n"
 "   OR location->>'product_id' IS DISTINCT FROM v.product_id::text OR location->>'project_id' IS "
 'DISTINCT FROM v.project_id::text\n'
 "   OR location->'engineering_configuration' IS DISTINCT FROM payload->'engineering_configuration'\n"
 "   OR location->'manufacturing_configuration' IS DISTINCT FROM "
 "payload->'manufacturing_configuration'\n"
 "   OR location->'batch' IS DISTINCT FROM payload->'batch'\n"
 "   OR (coalesce(payload->'batch','null'::jsonb)='null'::jsonb AND payload->>'project_id' IS DISTINCT "
 'FROM v.project_id::text)\n'
 '   OR NOT coalesce(v.sources @> prior.sources,false) OR NOT coalesce(v.sources @> '
 "payload->'sources',false)\n"
 "   OR NOT coalesce(v.sources @> location->'sources',false)\n"
 '   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.sources) source WHERE NOT(prior.sources @> '
 'jsonb_build_array(source)\n'
 "    OR payload->'sources' @> jsonb_build_array(source) OR location->'sources' @> "
 'jsonb_build_array(source))) THEN\n'
 "   RAISE EXCEPTION 'Field location preserves report, privacy and exact predecessor; known product "
 "cannot silently change' USING ERRCODE='23514'; END IF;\n"
 '  IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations engineering WHERE '
 'engineering.tenant_id=t AND engineering.category_id=v.category_id\n'
 '   AND engineering.product_id=v.product_id AND '
 "engineering.id::text=location->'engineering_configuration'->>'id'\n"
 "   AND engineering.revision::text=location->'engineering_configuration'->>'revision'\n"
 '   AND coalesce(v.reads @> engineering.required_source_read_set,false)\n'
 "   AND (v.visibility='private' OR engineering.visibility='category')\n"
 '   AND (v.project_id IS NULL OR EXISTS(SELECT 1 FROM public.project_product_links link WHERE '
 'link.tenant_id=t AND link.category_id=v.category_id\n'
 '    AND link.product_id=v.product_id AND link.project_id=v.project_id AND '
 'link.definition_id=engineering.definition_id AND '
 'link.definition_revision=engineering.definition_revision))) THEN\n'
 "   RAISE EXCEPTION 'Field location requires an actual engineering configuration in the selected "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'manufacturing_configuration','null'::jsonb)<>'null'::jsonb AND NOT "
 'EXISTS(SELECT 1 FROM public.process_revisions manufacturing\n'
 '   WHERE manufacturing.tenant_id=t AND manufacturing.category_id=v.category_id AND '
 'manufacturing.product_id=v.product_id\n'
 "    AND manufacturing.id::text=location->'manufacturing_configuration'->>'id' AND "
 "manufacturing.revision::text=location->'manufacturing_configuration'->>'revision'\n"
 '    AND '
 "manufacturing.engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 '    AND coalesce(v.reads @> manufacturing.required_source_read_set,false) AND '
 "(v.visibility='private' OR manufacturing.visibility='category')) THEN\n"
 "   RAISE EXCEPTION 'Field manufacturing configuration must match actual engineering configuration' "
 "USING ERRCODE='23514'; END IF;\n"
 "  IF coalesce(location->'batch','null'::jsonb)<>'null'::jsonb AND NOT EXISTS(SELECT 1 FROM "
 'public.build_lots lot\n'
 '   JOIN public.actual_configurations actual ON actual.tenant_id=lot.tenant_id AND '
 'actual.product_id=lot.product_id AND actual.id=lot.actual_configuration_id\n'
 '   WHERE lot.tenant_id=t AND lot.category_id=v.category_id AND lot.product_id=v.product_id AND '
 'lot.project_id=v.project_id\n'
 "    AND lot.id::text=location->'batch'->>'id' AND lot.revision::text=location->'batch'->>'revision'\n"
 '    AND actual.revision=lot.actual_configuration_revision\n'
 '    AND '
 "actual.actual_engineering_configuration_id::text=location->'engineering_configuration'->>'id'\n"
 "    AND actual.actual_engineering_revision::text=location->'engineering_configuration'->>'revision'\n"
 '    AND '
 "actual.actual_manufacturing_configuration_id::text=location->'manufacturing_configuration'->>'id'\n"
 '    AND '
 "actual.actual_manufacturing_revision::text=location->'manufacturing_configuration'->>'revision'\n"
 "    AND (payload->>'project_id' IS NULL OR payload->>'project_id'=lot.project_id::text)\n"
 '    AND coalesce(v.reads @> lot.required_source_read_set,false) AND coalesce(v.reads @> '
 'actual.required_source_read_set,false)\n'
 "    AND (v.visibility='private' OR (lot.visibility='category' AND actual.visibility='category'))) "
 'THEN\n'
 "   RAISE EXCEPTION 'Field batch requires exact native lot and actual physical configuration' USING "
 "ERRCODE='23514'; END IF;\n"
 ' END IF;\n'
 'END;\n'
 '$function$\n',
 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, target uuid)\n'
 ' RETURNS void\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 '\n'
 'DECLARE v public.field_response_records; parent public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; result jsonb; native_receipt public.action_receipts;\n'
 'BEGIN\n'
 ' SELECT * INTO STRICT v FROM public.field_response_records WHERE tenant_id=t AND id=target;\n'
 " PERFORM public.assert_field_common(t,target,'field_response');\n"
 ' SELECT * INTO STRICT parent FROM public.field_feedback_versions WHERE tenant_id=t AND '
 'category_id=v.category_id AND id=v.feedback_version_id;\n'
 ' SELECT * INTO STRICT cur FROM public.field_feedback_currents WHERE tenant_id=t AND '
 'category_id=v.category_id AND feedback_id=v.feedback_id;\n'
 " payload=v.command->'envelope'->'payload';\n"
 ' '
 "expected=jsonb_build_object('feedback',payload->'feedback','feedback_version_id',parent.id,'response_kind',v.response_kind,\n"
 '  '
 "'description',payload->'description','occurred_at',v.body->'occurred_at','result_receipts',coalesce(payload->'result_receipts','[]'::jsonb));\n"
 ' IF '
 'ROW(v.category_id,v.product_id,v.project_id,v.feedback_id,v.feedback_version_id,v.feedback_revision)\n'
 '  IS DISTINCT FROM '
 'ROW(parent.category_id,parent.product_id,parent.project_id,parent.feedback_id,parent.id,parent.revision)\n'
 '  OR cur.version_id<>parent.id OR cur.revision<>parent.revision\n'
 "  OR v.owner_id<>v.requester_id OR (parent.visibility='private' AND v.visibility<>'private')\n"
 "  OR payload->>'visibility' IS DISTINCT FROM v.visibility\n"
 "  OR payload->'feedback' IS DISTINCT FROM "
 "jsonb_build_object('id',parent.feedback_id,'revision',parent.revision)\n"
 "  OR v.body IS DISTINCT FROM expected OR v.sources IS DISTINCT FROM payload->'sources'\n"
 "  OR (v.body->>'occurred_at')::timestamptz IS DISTINCT FROM (payload->>'occurred_at')::timestamptz\n"
 "  OR coalesce(v.command->'review'->'before','null'::jsonb)<>'null'::jsonb\n"
 "  OR (v.operation='field.feedback.action.record' AND (payload->>'action_kind' IS DISTINCT FROM "
 "v.response_kind OR v.body->'result_receipts'<>'[]'::jsonb))\n"
 "  OR NOT coalesce(v.source_basis->'artifacts' @> parent.source_basis->'artifacts',false) THEN\n"
 "  RAISE EXCEPTION 'Field response binds exact current parent and new actual facts without advancing "
 "its report' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.followup.link' THEN\n"
 "  IF v.project_id IS NULL OR jsonb_array_length(payload->'result_receipts')=0\n"
 '   OR '
 "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
 "   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') result WHERE "
 "result->>'product_id' IS DISTINCT FROM v.product_id::text\n"
 "    OR result->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 FROM "
 "jsonb_array_elements(payload->'result_receipts') requested WHERE "
 "requested->'receipt_id'=result->'receipt_id')) THEN\n"
 "   RAISE EXCEPTION 'Field follow-up references only finite fixed native results in its actual "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  FOR result IN SELECT value FROM jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
 '   SELECT * INTO STRICT native_receipt FROM public.action_receipts r WHERE r.tenant_id=t AND '
 'r.category_id=v.category_id\n'
 "    AND r.id::text=result->>'receipt_id' AND r.product_id=v.product_id AND "
 "r.operation=result->>'operation'\n"
 "    AND r.subject_type=result->>'subject_type' AND r.subject_id::text=result->>'subject_id'\n"
 "    AND r.subject_revision::text=result->>'subject_revision' AND "
 "r.request_digest=result->>'receipt_request_digest'\n"
 "    AND r.visibility=result->>'receipt_visibility';\n"
 "   IF (v.visibility='category' AND (native_receipt.visibility<>'category' OR "
 "result->>'visibility'<>'category'\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.products p WHERE p.tenant_id=t AND p.id=v.product_id AND '
 "p.visibility='category')\n"
 '     OR NOT EXISTS(SELECT 1 FROM public.projects p WHERE p.tenant_id=t AND p.id=v.project_id AND '
 "p.visibility='category')))\n"
 '    OR NOT EXISTS(SELECT 1 FROM public.audit_entries a WHERE a.tenant_id=t AND '
 'a.category_id=v.category_id AND a.receipt_id=native_receipt.id\n'
 '     AND a.actor_id=native_receipt.actor_id AND a.operation=native_receipt.operation)\n'
 '    OR NOT EXISTS(SELECT 1 FROM public.outbox_events e WHERE e.tenant_id=t AND '
 'e.category_id=v.category_id AND e.receipt_id=native_receipt.id\n'
 '     AND e.subject_id=native_receipt.subject_id AND '
 'e.subject_revision=native_receipt.subject_revision AND e.actor_id=native_receipt.actor_id\n'
 '     AND e.schema_version=1 AND '
 'e.correlation_id=coalesce(native_receipt.agent_run_id,native_receipt.run_id,native_receipt.command_id)) '
 'THEN\n'
 "    RAISE EXCEPTION 'Field follow-up requires actual native receipt audit event and audience' USING "
 "ERRCODE='23514'; END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 'END;\n'
 '$function$\n')

