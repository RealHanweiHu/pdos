"""Disambiguate fixed result row aliases from the response atom loop value."""

PREVIOUS_FUNCTIONS = {'assert_field_response(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, '
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
                                     "jsonb_array_elements(v.source_basis->'result_receipts') AS "
                                     "fixed_result(value) WHERE fixed_result.value->>'product_id' IS "
                                     'DISTINCT FROM v.product_id::text\n'
                                     "    OR fixed_result.value->>'project_id' IS DISTINCT FROM "
                                     'v.project_id::text OR NOT EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(payload->'result_receipts') requested WHERE "
                                     "requested->'receipt_id'=fixed_result.value->'receipt_id')) THEN\n"
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

FIELD_FUNCTIONS = {'assert_field_response(uuid,uuid)': 'CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid, '
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
                                     ' payload jsonb; expected jsonb; selected_result jsonb; '
                                     'native_receipt public.action_receipts;\n'
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
                                     "jsonb_array_elements(v.source_basis->'result_receipts') AS "
                                     "fixed_result(value) WHERE fixed_result.value->>'product_id' IS "
                                     'DISTINCT FROM v.product_id::text\n'
                                     "    OR fixed_result.value->>'project_id' IS DISTINCT FROM "
                                     'v.project_id::text OR NOT EXISTS(SELECT 1 FROM '
                                     "jsonb_array_elements(payload->'result_receipts') requested WHERE "
                                     "requested->'receipt_id'=fixed_result.value->'receipt_id')) THEN\n"
                                     "   RAISE EXCEPTION 'Field follow-up references only finite fixed "
                                     "native results in its actual project' USING ERRCODE='23514'; END "
                                     'IF;\n'
                                     '  FOR selected_result IN SELECT value FROM '
                                     "jsonb_array_elements(v.source_basis->'result_receipts') LOOP\n"
                                     '   SELECT * INTO STRICT native_receipt FROM '
                                     'public.action_receipts r WHERE r.tenant_id=t AND '
                                     'r.category_id=v.category_id\n'
                                     "    AND r.id::text=selected_result->>'receipt_id' AND "
                                     'r.product_id=v.product_id AND '
                                     "r.operation=selected_result->>'operation'\n"
                                     "    AND r.subject_type=selected_result->>'subject_type' AND "
                                     "r.subject_id::text=selected_result->>'subject_id'\n"
                                     '    AND '
                                     "r.subject_revision::text=selected_result->>'subject_revision' "
                                     "AND r.request_digest=selected_result->>'receipt_request_digest'\n"
                                     "    AND r.visibility=selected_result->>'receipt_visibility';\n"
                                     "   IF (v.visibility='category' AND "
                                     "(native_receipt.visibility<>'category' OR "
                                     "selected_result->>'visibility'<>'category'\n"
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

SCHEMA_SQL = ('CREATE OR REPLACE FUNCTION public.assert_field_response(t uuid,target uuid) RETURNS void\n'
 'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $field$\n'
 '\n'
 'DECLARE v public.field_response_records; parent public.field_feedback_versions; cur '
 'public.field_feedback_currents;\n'
 ' payload jsonb; expected jsonb; selected_result jsonb; native_receipt public.action_receipts;\n'
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
 "   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') AS "
 "fixed_result(value) WHERE fixed_result.value->>'product_id' IS DISTINCT FROM v.product_id::text\n"
 "    OR fixed_result.value->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 "
 "FROM jsonb_array_elements(payload->'result_receipts') requested WHERE "
 "requested->'receipt_id'=fixed_result.value->'receipt_id')) THEN\n"
 "   RAISE EXCEPTION 'Field follow-up references only finite fixed native results in its actual "
 "project' USING ERRCODE='23514'; END IF;\n"
 "  FOR selected_result IN SELECT value FROM jsonb_array_elements(v.source_basis->'result_receipts') "
 'LOOP\n'
 '   SELECT * INTO STRICT native_receipt FROM public.action_receipts r WHERE r.tenant_id=t AND '
 'r.category_id=v.category_id\n'
 "    AND r.id::text=selected_result->>'receipt_id' AND r.product_id=v.product_id AND "
 "r.operation=selected_result->>'operation'\n"
 "    AND r.subject_type=selected_result->>'subject_type' AND "
 "r.subject_id::text=selected_result->>'subject_id'\n"
 "    AND r.subject_revision::text=selected_result->>'subject_revision' AND "
 "r.request_digest=selected_result->>'receipt_request_digest'\n"
 "    AND r.visibility=selected_result->>'receipt_visibility';\n"
 "   IF (v.visibility='category' AND (native_receipt.visibility<>'category' OR "
 "selected_result->>'visibility'<>'category'\n"
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
 '$field$',)

DOWNGRADE_SQL = ('DO $field$ BEGIN IF EXISTS(SELECT 1 FROM public.field_response_records WHERE '
 "response_kind='followup') THEN RAISE EXCEPTION 'Field follow-up history retained; downgrade refused' "
 "USING ERRCODE='23514'; END IF; END; $field$",
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
 "  OR NOT coalesce((v.source_basis->'artifacts') @> (parent.source_basis->'artifacts'),false) THEN\n"
 "  RAISE EXCEPTION 'Field response binds exact current parent and new actual facts without advancing "
 "its report' USING ERRCODE='23514'; END IF;\n"
 " IF v.operation='field.feedback.followup.link' THEN\n"
 "  IF v.project_id IS NULL OR jsonb_array_length(payload->'result_receipts')=0\n"
 '   OR '
 "jsonb_array_length(v.source_basis->'result_receipts')<>jsonb_array_length(payload->'result_receipts')\n"
 "   OR EXISTS(SELECT 1 FROM jsonb_array_elements(v.source_basis->'result_receipts') AS "
 "fixed_result(value) WHERE fixed_result.value->>'product_id' IS DISTINCT FROM v.product_id::text\n"
 "    OR fixed_result.value->>'project_id' IS DISTINCT FROM v.project_id::text OR NOT EXISTS(SELECT 1 "
 "FROM jsonb_array_elements(payload->'result_receipts') requested WHERE "
 "requested->'receipt_id'=fixed_result.value->'receipt_id')) THEN\n"
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

