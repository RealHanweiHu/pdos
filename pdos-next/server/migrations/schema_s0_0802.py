"""Allow only the Field owner guarded unknown-to-known product adoption."""

PREVIOUS_FUNCTIONS = {'advance_change_dependency_clock()': 'CREATE OR REPLACE FUNCTION '
                                      'public.advance_change_dependency_clock()\n'
                                      ' RETURNS trigger\n'
                                      ' LANGUAGE plpgsql\n'
                                      ' SECURITY DEFINER\n'
                                      " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                      'AS $function$\n'
                                      'DECLARE v jsonb; t uuid; p uuid;\n'
                                      'BEGIN\n'
                                      " IF TG_OP='DELETE' THEN v=to_jsonb(OLD); ELSE v=to_jsonb(NEW); "
                                      'END IF;\n'
                                      " t=(v->>'tenant_id')::uuid; p=(v->>'product_id')::uuid;\n"
                                      " IF TG_TABLE_NAME='operational_asset_sentinels' THEN\n"
                                      '  -- Only persisted physical references receive invalidation. '
                                      'Historical\n'
                                      '  -- facts retain their reference; unrelated models keep their '
                                      'watermark.\n'
                                      '  -- Importers lock the physical asset before publishing their '
                                      'fact. A racing\n'
                                      '  -- new reference therefore sees the changed asset or precedes '
                                      'this update.\n'
                                      "  IF t IS NULL THEN RAISE EXCEPTION 'Shared dependency tenant "
                                      "is missing'; END IF;\n"
                                      '  FOR p IN\n'
                                      '   SELECT product_id FROM public.build_operational_facts f\n'
                                      '    WHERE f.tenant_id=t AND (\n'
                                      '     f.data @> '
                                      "jsonb_build_object('resources',jsonb_build_array(\n"
                                      '       '
                                      "jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
                                      "     OR (v->>'kind'='material' AND f.data @> "
                                      "jsonb_build_object('materials',\n"
                                      '       '
                                      "jsonb_build_array(jsonb_build_object('key',v->'identity')))))\n"
                                      '   UNION SELECT product_id FROM public.test_resource_facts f\n'
                                      '    WHERE f.tenant_id=t AND f.data @> '
                                      "jsonb_build_object('resources',\n"
                                      '      '
                                      "jsonb_build_array(jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
                                      '   UNION SELECT product_id FROM '
                                      'public.operational_material_holds\n'
                                      "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
                                      '   UNION SELECT product_id FROM '
                                      'public.operational_resource_occupancies\n'
                                      "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
                                      '   ORDER BY product_id\n'
                                      '  LOOP\n'
                                      '   UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
                                      '    WHERE tenant_id=t AND product_id=p;\n'
                                      '  END LOOP;\n'
                                      '  RETURN NULL;\n'
                                      ' END IF;\n'
                                      " IF TG_OP='UPDATE' AND ROW(t,p) IS DISTINCT FROM\n"
                                      '  '
                                      "ROW((to_jsonb(OLD)->>'tenant_id')::uuid,(to_jsonb(OLD)->>'product_id')::uuid) "
                                      'THEN\n'
                                      "  RAISE EXCEPTION 'Dependency scope cannot be reassigned'; END "
                                      'IF;\n'
                                      ' IF p IS NULL AND '
                                      "TG_TABLE_NAME=ANY(ARRAY['artifact_versions','uploaded_originals','original_scan_requests','original_scan_results','original_security','upload_attempts','lifecycle_objects','lifecycle_candidates','lifecycle_intents','lifecycle_requests']) "
                                      'THEN\n'
                                      '  PERFORM 1 FROM public.categories WHERE tenant_id=t AND '
                                      "id=(v->>'category_id')::uuid;\n"
                                      "  IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Category "
                                      "is missing'; END IF;\n"
                                      '  RETURN NULL;\n'
                                      ' END IF;\n'
                                      ' PERFORM 1 FROM public.products WHERE tenant_id=t AND id=p FOR '
                                      'UPDATE;\n'
                                      " IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Product "
                                      "is missing'; END IF;\n"
                                      ' UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
                                      '  WHERE tenant_id=t AND product_id=p;\n'
                                      " IF NOT FOUND THEN RAISE EXCEPTION 'Actual product dependency "
                                      "clock is missing'; END IF;\n"
                                      ' RETURN NULL;\n'
                                      'END $function$\n'}

FIELD_FUNCTIONS = {'advance_change_dependency_clock()': 'CREATE OR REPLACE FUNCTION '
                                      'public.advance_change_dependency_clock()\n'
                                      ' RETURNS trigger\n'
                                      ' LANGUAGE plpgsql\n'
                                      ' SECURITY DEFINER\n'
                                      " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
                                      'AS $function$\n'
                                      'DECLARE v jsonb; t uuid; p uuid;\n'
                                      'BEGIN\n'
                                      " IF TG_OP='DELETE' THEN v=to_jsonb(OLD); ELSE v=to_jsonb(NEW); "
                                      'END IF;\n'
                                      " t=(v->>'tenant_id')::uuid; p=(v->>'product_id')::uuid;\n"
                                      " IF TG_TABLE_NAME='operational_asset_sentinels' THEN\n"
                                      '  -- Only persisted physical references receive invalidation. '
                                      'Historical\n'
                                      '  -- facts retain their reference; unrelated models keep their '
                                      'watermark.\n'
                                      '  -- Importers lock the physical asset before publishing their '
                                      'fact. A racing\n'
                                      '  -- new reference therefore sees the changed asset or precedes '
                                      'this update.\n'
                                      "  IF t IS NULL THEN RAISE EXCEPTION 'Shared dependency tenant "
                                      "is missing'; END IF;\n"
                                      '  FOR p IN\n'
                                      '   SELECT product_id FROM public.build_operational_facts f\n'
                                      '    WHERE f.tenant_id=t AND (\n'
                                      '     f.data @> '
                                      "jsonb_build_object('resources',jsonb_build_array(\n"
                                      '       '
                                      "jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
                                      "     OR (v->>'kind'='material' AND f.data @> "
                                      "jsonb_build_object('materials',\n"
                                      '       '
                                      "jsonb_build_array(jsonb_build_object('key',v->'identity')))))\n"
                                      '   UNION SELECT product_id FROM public.test_resource_facts f\n'
                                      '    WHERE f.tenant_id=t AND f.data @> '
                                      "jsonb_build_object('resources',\n"
                                      '      '
                                      "jsonb_build_array(jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
                                      '   UNION SELECT product_id FROM '
                                      'public.operational_material_holds\n'
                                      "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
                                      '   UNION SELECT product_id FROM '
                                      'public.operational_resource_occupancies\n'
                                      "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
                                      '   ORDER BY product_id\n'
                                      '  LOOP\n'
                                      '   UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
                                      '    WHERE tenant_id=t AND product_id=p;\n'
                                      '  END LOOP;\n'
                                      '  RETURN NULL;\n'
                                      ' END IF;\n'
                                      " IF TG_OP='UPDATE' AND ROW(t,p) IS DISTINCT FROM\n"
                                      '  '
                                      "ROW((to_jsonb(OLD)->>'tenant_id')::uuid,(to_jsonb(OLD)->>'product_id')::uuid)\n"
                                      "  AND NOT (TG_TABLE_NAME='field_feedback_currents' AND "
                                      "t=(to_jsonb(OLD)->>'tenant_id')::uuid\n"
                                      "   AND (to_jsonb(OLD)->>'product_id') IS NULL AND p IS NOT "
                                      'NULL\n'
                                      "   AND (v->>'category_id')=(to_jsonb(OLD)->>'category_id')) "
                                      'THEN\n'
                                      "  RAISE EXCEPTION 'Dependency scope cannot be reassigned'; END "
                                      'IF;\n'
                                      ' IF p IS NULL AND '
                                      "TG_TABLE_NAME=ANY(ARRAY['artifact_versions','uploaded_originals','original_scan_requests','original_scan_results','original_security','upload_attempts','lifecycle_objects','lifecycle_candidates','lifecycle_intents','lifecycle_requests']) "
                                      'THEN\n'
                                      '  PERFORM 1 FROM public.categories WHERE tenant_id=t AND '
                                      "id=(v->>'category_id')::uuid;\n"
                                      "  IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Category "
                                      "is missing'; END IF;\n"
                                      '  RETURN NULL;\n'
                                      ' END IF;\n'
                                      ' PERFORM 1 FROM public.products WHERE tenant_id=t AND id=p FOR '
                                      'UPDATE;\n'
                                      " IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Product "
                                      "is missing'; END IF;\n"
                                      ' UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
                                      '  WHERE tenant_id=t AND product_id=p;\n'
                                      " IF NOT FOUND THEN RAISE EXCEPTION 'Actual product dependency "
                                      "clock is missing'; END IF;\n"
                                      ' RETURN NULL;\n'
                                      'END $function$\n'}

SCHEMA_SQL = ('CREATE OR REPLACE FUNCTION public.advance_change_dependency_clock()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE v jsonb; t uuid; p uuid;\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN v=to_jsonb(OLD); ELSE v=to_jsonb(NEW); END IF;\n"
 " t=(v->>'tenant_id')::uuid; p=(v->>'product_id')::uuid;\n"
 " IF TG_TABLE_NAME='operational_asset_sentinels' THEN\n"
 '  -- Only persisted physical references receive invalidation. Historical\n'
 '  -- facts retain their reference; unrelated models keep their watermark.\n'
 '  -- Importers lock the physical asset before publishing their fact. A racing\n'
 '  -- new reference therefore sees the changed asset or precedes this update.\n'
 "  IF t IS NULL THEN RAISE EXCEPTION 'Shared dependency tenant is missing'; END IF;\n"
 '  FOR p IN\n'
 '   SELECT product_id FROM public.build_operational_facts f\n'
 '    WHERE f.tenant_id=t AND (\n'
 "     f.data @> jsonb_build_object('resources',jsonb_build_array(\n"
 "       jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
 "     OR (v->>'kind'='material' AND f.data @> jsonb_build_object('materials',\n"
 "       jsonb_build_array(jsonb_build_object('key',v->'identity')))))\n"
 '   UNION SELECT product_id FROM public.test_resource_facts f\n'
 "    WHERE f.tenant_id=t AND f.data @> jsonb_build_object('resources',\n"
 "      jsonb_build_array(jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
 '   UNION SELECT product_id FROM public.operational_material_holds\n'
 "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
 '   UNION SELECT product_id FROM public.operational_resource_occupancies\n'
 "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
 '   ORDER BY product_id\n'
 '  LOOP\n'
 '   UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
 '    WHERE tenant_id=t AND product_id=p;\n'
 '  END LOOP;\n'
 '  RETURN NULL;\n'
 ' END IF;\n'
 " IF TG_OP='UPDATE' AND ROW(t,p) IS DISTINCT FROM\n"
 "  ROW((to_jsonb(OLD)->>'tenant_id')::uuid,(to_jsonb(OLD)->>'product_id')::uuid)\n"
 "  AND NOT (TG_TABLE_NAME='field_feedback_currents' AND t=(to_jsonb(OLD)->>'tenant_id')::uuid\n"
 "   AND (to_jsonb(OLD)->>'product_id') IS NULL AND p IS NOT NULL\n"
 "   AND (v->>'category_id')=(to_jsonb(OLD)->>'category_id')) THEN\n"
 "  RAISE EXCEPTION 'Dependency scope cannot be reassigned'; END IF;\n"
 ' IF p IS NULL AND '
 "TG_TABLE_NAME=ANY(ARRAY['artifact_versions','uploaded_originals','original_scan_requests','original_scan_results','original_security','upload_attempts','lifecycle_objects','lifecycle_candidates','lifecycle_intents','lifecycle_requests']) "
 'THEN\n'
 "  PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=(v->>'category_id')::uuid;\n"
 "  IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Category is missing'; END IF;\n"
 '  RETURN NULL;\n'
 ' END IF;\n'
 ' PERFORM 1 FROM public.products WHERE tenant_id=t AND id=p FOR UPDATE;\n'
 " IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Product is missing'; END IF;\n"
 ' UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
 '  WHERE tenant_id=t AND product_id=p;\n'
 " IF NOT FOUND THEN RAISE EXCEPTION 'Actual product dependency clock is missing'; END IF;\n"
 ' RETURN NULL;\n'
 'END $function$\n',)

DOWNGRADE_SQL = ('DO $field$ BEGIN IF EXISTS(SELECT 1 FROM public.field_feedback_versions v JOIN '
 'public.field_feedback_versions prior ON prior.tenant_id=v.tenant_id AND prior.id=v.previous_id WHERE '
 "prior.product_id IS NULL AND v.product_id IS NOT NULL) THEN RAISE EXCEPTION 'Field located history "
 "retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $field$",
 'CREATE OR REPLACE FUNCTION public.advance_change_dependency_clock()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 ' SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 'DECLARE v jsonb; t uuid; p uuid;\n'
 'BEGIN\n'
 " IF TG_OP='DELETE' THEN v=to_jsonb(OLD); ELSE v=to_jsonb(NEW); END IF;\n"
 " t=(v->>'tenant_id')::uuid; p=(v->>'product_id')::uuid;\n"
 " IF TG_TABLE_NAME='operational_asset_sentinels' THEN\n"
 '  -- Only persisted physical references receive invalidation. Historical\n'
 '  -- facts retain their reference; unrelated models keep their watermark.\n'
 '  -- Importers lock the physical asset before publishing their fact. A racing\n'
 '  -- new reference therefore sees the changed asset or precedes this update.\n'
 "  IF t IS NULL THEN RAISE EXCEPTION 'Shared dependency tenant is missing'; END IF;\n"
 '  FOR p IN\n'
 '   SELECT product_id FROM public.build_operational_facts f\n'
 '    WHERE f.tenant_id=t AND (\n'
 "     f.data @> jsonb_build_object('resources',jsonb_build_array(\n"
 "       jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
 "     OR (v->>'kind'='material' AND f.data @> jsonb_build_object('materials',\n"
 "       jsonb_build_array(jsonb_build_object('key',v->'identity')))))\n"
 '   UNION SELECT product_id FROM public.test_resource_facts f\n'
 "    WHERE f.tenant_id=t AND f.data @> jsonb_build_object('resources',\n"
 "      jsonb_build_array(jsonb_build_object('resource',jsonb_build_object('id',v->>'id'))))\n"
 '   UNION SELECT product_id FROM public.operational_material_holds\n'
 "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
 '   UNION SELECT product_id FROM public.operational_resource_occupancies\n'
 "    WHERE tenant_id=t AND asset_id=(v->>'id')::uuid\n"
 '   ORDER BY product_id\n'
 '  LOOP\n'
 '   UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
 '    WHERE tenant_id=t AND product_id=p;\n'
 '  END LOOP;\n'
 '  RETURN NULL;\n'
 ' END IF;\n'
 " IF TG_OP='UPDATE' AND ROW(t,p) IS DISTINCT FROM\n"
 "  ROW((to_jsonb(OLD)->>'tenant_id')::uuid,(to_jsonb(OLD)->>'product_id')::uuid) THEN\n"
 "  RAISE EXCEPTION 'Dependency scope cannot be reassigned'; END IF;\n"
 ' IF p IS NULL AND '
 "TG_TABLE_NAME=ANY(ARRAY['artifact_versions','uploaded_originals','original_scan_requests','original_scan_results','original_security','upload_attempts','lifecycle_objects','lifecycle_candidates','lifecycle_intents','lifecycle_requests']) "
 'THEN\n'
 "  PERFORM 1 FROM public.categories WHERE tenant_id=t AND id=(v->>'category_id')::uuid;\n"
 "  IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Category is missing'; END IF;\n"
 '  RETURN NULL;\n'
 ' END IF;\n'
 ' PERFORM 1 FROM public.products WHERE tenant_id=t AND id=p FOR UPDATE;\n'
 " IF NOT FOUND THEN RAISE EXCEPTION 'Actual dependency Product is missing'; END IF;\n"
 ' UPDATE public.change_dependency_clocks SET epoch=epoch+1\n'
 '  WHERE tenant_id=t AND product_id=p;\n'
 " IF NOT FOUND THEN RAISE EXCEPTION 'Actual product dependency clock is missing'; END IF;\n"
 ' RETURN NULL;\n'
 'END $function$\n')

