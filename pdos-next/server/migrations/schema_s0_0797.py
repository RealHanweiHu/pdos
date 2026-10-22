"""Exact installed 0796 calendar guard with explicit JSONB containment operands."""

PREVIOUS_FUNCTIONS = {'assert_external_wait_calendar(uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                             'public.assert_external_wait_calendar(t uuid, target '
                                             'uuid)\n'
                                             ' RETURNS void\n'
                                             ' LANGUAGE plpgsql\n'
                                             ' SECURITY DEFINER\n'
                                             " SET search_path TO 'pg_catalog', 'public', "
                                             "'pg_temp'\n"
                                             'AS $function$\n'
                                             '\n'
                                             'DECLARE v public.external_wait_versions; cal jsonb; '
                                             'ref jsonb;\n'
                                             'BEGIN\n'
                                             ' SELECT * INTO STRICT v FROM '
                                             'public.external_wait_versions WHERE tenant_id=t AND '
                                             'id=target;\n'
                                             " cal=v.source_basis->'calendar'; "
                                             "ref=v.body->'calendar';\n"
                                             " IF coalesce(ref,'null'::jsonb)='null'::jsonb THEN\n"
                                             "  IF coalesce(cal,'null'::jsonb)<>'null'::jsonb "
                                             'THEN\n'
                                             "   RAISE EXCEPTION 'No inline calendar or detached "
                                             "calendar basis may be supplied' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             '  RETURN;\n'
                                             ' END IF;\n'
                                             " IF jsonb_typeof(cal) IS DISTINCT FROM 'object' OR "
                                             "cal->'ref' IS DISTINCT FROM ref\n"
                                             "  OR cal->'scope' IS DISTINCT FROM "
                                             "jsonb_build_object('tenant_id',t,'category_id',v.category_id,'product_id',v.product_id,'project_id',v.project_id)\n"
                                             "  OR jsonb_typeof(cal->'source_calendar') IS "
                                             "DISTINCT FROM 'object'\n"
                                             "  OR cal->>'digest' IS NULL OR cal->>'digest' !~ "
                                             "'^[a-f0-9]{64}$'\n"
                                             "  OR cal->>'calendar_sha256' IS NULL OR "
                                             "cal->>'calendar_sha256' !~ '^[a-f0-9]{64}$'\n"
                                             '  OR '
                                             "jsonb_typeof(cal->'material'->'source_basis'->'artifacts') "
                                             "IS DISTINCT FROM 'array'\n"
                                             "  OR NOT coalesce(v.source_basis->'artifacts' @> "
                                             "cal->'material'->'source_basis'->'artifacts',false) "
                                             'THEN\n'
                                             "  RAISE EXCEPTION 'Calendar requires the exact "
                                             "native reference and retained direct sources' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             " IF ref->>'kind'='project_plan' THEN\n"
                                             '  IF NOT EXISTS(SELECT 1 FROM public.plan_revisions '
                                             'pl JOIN public.plan_proposals pp\n'
                                             '   ON pp.tenant_id=pl.tenant_id AND '
                                             'pp.category_id=pl.category_id AND '
                                             'pp.product_id=pl.product_id\n'
                                             '    AND pp.project_id=pl.project_id AND '
                                             'pp.id=pl.proposal_id\n'
                                             '   JOIN public.project_product_links link ON '
                                             'link.tenant_id=pl.tenant_id AND '
                                             'link.category_id=pl.category_id\n'
                                             '    AND link.product_id=pl.product_id AND '
                                             'link.project_id=pl.project_id\n'
                                             '   WHERE pl.tenant_id=t AND '
                                             'pl.category_id=v.category_id AND '
                                             'pl.product_id=v.product_id AND '
                                             'pl.project_id=v.project_id\n'
                                             "    AND pl.id::text=ref->>'id' AND "
                                             "pl.revision::text=ref->>'revision' AND "
                                             "pl.status='applied'\n"
                                             "    AND pl.id::text=cal->'material'->>'plan_id' AND "
                                             "pl.revision::text=cal->'material'->>'plan_revision'\n"
                                             "    AND pp.id::text=cal->'material'->>'proposal_id' "
                                             'AND '
                                             "pp.revision::text=cal->'material'->>'proposal_revision'\n"
                                             '    AND '
                                             "cal->'material'->'definition_ref'=jsonb_build_object('id',link.definition_id,'revision',link.definition_revision)\n"
                                             '    AND '
                                             "pp.input_snapshot->'calendar'=cal->'source_calendar'\n"
                                             '    AND '
                                             "ref->>'calendar_key'=pp.input_snapshot->'calendar'->>'key'\n"
                                             '    AND '
                                             "ref->>'calendar_version'=pp.input_snapshot->'calendar'->>'version'\n"
                                             '    AND '
                                             "coalesce(ref->'resource_id','null'::jsonb)='null'::jsonb) "
                                             'THEN\n'
                                             "   RAISE EXCEPTION 'Calendar is not the selected "
                                             "actual project plan calendar' USING ERRCODE='23514'; "
                                             'END IF;\n'
                                             " ELSIF ref->>'kind'='build_resource' THEN\n"
                                             '  IF NOT EXISTS(SELECT 1 FROM '
                                             'public.build_operational_facts fixed\n'
                                             '   JOIN public.build_operational_current ptr ON '
                                             'ptr.tenant_id=fixed.tenant_id AND '
                                             'ptr.category_id=fixed.category_id\n'
                                             '    AND ptr.product_id=fixed.product_id AND '
                                             'ptr.project_id=fixed.project_id AND '
                                             'ptr.build_id=fixed.build_id\n'
                                             '   JOIN public.build_operational_facts live ON '
                                             'live.tenant_id=ptr.tenant_id AND '
                                             'live.category_id=ptr.category_id\n'
                                             '    AND live.product_id=ptr.product_id AND '
                                             'live.project_id=ptr.project_id AND '
                                             'live.build_id=ptr.build_id\n'
                                             '    AND live.id=ptr.fact_id AND '
                                             'live.revision=ptr.fact_revision AND '
                                             'live.series_id=fixed.series_id\n'
                                             '   JOIN LATERAL '
                                             "jsonb_array_elements(fixed.data->'resources') res ON "
                                             'true\n'
                                             '   JOIN LATERAL '
                                             "jsonb_array_elements(live.data->'resources') actual "
                                             'ON true\n'
                                             '   JOIN public.operational_asset_sentinels asset ON '
                                             'asset.tenant_id=fixed.tenant_id\n'
                                             "    AND asset.id::text=actual->'resource'->>'id' AND "
                                             "asset.revision::text=actual->'resource'->>'revision'\n"
                                             '   WHERE fixed.tenant_id=t AND '
                                             'fixed.category_id=v.category_id AND '
                                             'fixed.product_id=v.product_id AND '
                                             'fixed.project_id=v.project_id\n'
                                             "    AND fixed.id::text=ref->>'id' AND "
                                             "fixed.revision::text=ref->>'revision'\n"
                                             "    AND fixed.id::text=cal->'material'->>'fact_id' "
                                             'AND '
                                             "fixed.revision::text=cal->'material'->>'fact_revision'\n"
                                             '    AND '
                                             "fixed.fact_sha256=cal->'material'->>'fact_sha256' "
                                             'AND '
                                             "fixed.build_id::text=cal->'material'->>'build_id'\n"
                                             "    AND fixed.state='active' AND "
                                             'fixed.valid_from<=v.created_at AND '
                                             '(fixed.valid_until IS NULL OR '
                                             'v.created_at<fixed.valid_until)\n'
                                             "    AND live.state='active' AND "
                                             'live.valid_from<=v.created_at AND (live.valid_until '
                                             'IS NULL OR v.created_at<live.valid_until)\n'
                                             "    AND res->'resource'->>'id'=ref->>'resource_id' "
                                             "AND actual->'resource'->>'id'=ref->>'resource_id'\n"
                                             '    AND '
                                             "cal->'material'->>'resource_id'=ref->>'resource_id' "
                                             'AND '
                                             "res->'resource'->>'revision'=cal->'material'->>'resource_revision'\n"
                                             "    AND res->>'lifecycle'='active' AND "
                                             "actual->>'lifecycle'='active'\n"
                                             "    AND res->'calendar'=cal->'source_calendar' AND "
                                             "actual->'calendar'->>'calendar_id'=res->'calendar'->>'calendar_id'\n"
                                             '    AND '
                                             "ref->>'calendar_key'=res->'calendar'->>'calendar_id' "
                                             'AND '
                                             "ref->>'calendar_version'=res->'calendar'->>'version'\n"
                                             "    AND asset.kind='resource' AND "
                                             "asset.data->>'state'='active') THEN\n"
                                             "   RAISE EXCEPTION 'Calendar is not a retained "
                                             "native resource with a currently usable source' "
                                             "USING ERRCODE='23514'; END IF;\n"
                                             " ELSE RAISE EXCEPTION 'Unknown native calendar "
                                             "source' USING ERRCODE='23514'; END IF;\n"
                                             'END;\n'
                                             '$function$\n'}

CALENDAR_FUNCTIONS = {'assert_external_wait_calendar(uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                             'public.assert_external_wait_calendar(t uuid, target '
                                             'uuid)\n'
                                             ' RETURNS void\n'
                                             ' LANGUAGE plpgsql\n'
                                             ' SECURITY DEFINER\n'
                                             " SET search_path TO 'pg_catalog', 'public', "
                                             "'pg_temp'\n"
                                             'AS $function$\n'
                                             '\n'
                                             'DECLARE v public.external_wait_versions; cal jsonb; '
                                             'ref jsonb;\n'
                                             'BEGIN\n'
                                             ' SELECT * INTO STRICT v FROM '
                                             'public.external_wait_versions WHERE tenant_id=t AND '
                                             'id=target;\n'
                                             " cal=v.source_basis->'calendar'; "
                                             "ref=v.body->'calendar';\n"
                                             " IF coalesce(ref,'null'::jsonb)='null'::jsonb THEN\n"
                                             "  IF coalesce(cal,'null'::jsonb)<>'null'::jsonb "
                                             'THEN\n'
                                             "   RAISE EXCEPTION 'No inline calendar or detached "
                                             "calendar basis may be supplied' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             '  RETURN;\n'
                                             ' END IF;\n'
                                             " IF jsonb_typeof(cal) IS DISTINCT FROM 'object' OR "
                                             "cal->'ref' IS DISTINCT FROM ref\n"
                                             "  OR cal->'scope' IS DISTINCT FROM "
                                             "jsonb_build_object('tenant_id',t,'category_id',v.category_id,'product_id',v.product_id,'project_id',v.project_id)\n"
                                             "  OR jsonb_typeof(cal->'source_calendar') IS "
                                             "DISTINCT FROM 'object'\n"
                                             "  OR cal->>'digest' IS NULL OR cal->>'digest' !~ "
                                             "'^[a-f0-9]{64}$'\n"
                                             "  OR cal->>'calendar_sha256' IS NULL OR "
                                             "cal->>'calendar_sha256' !~ '^[a-f0-9]{64}$'\n"
                                             '  OR '
                                             "jsonb_typeof(cal->'material'->'source_basis'->'artifacts') "
                                             "IS DISTINCT FROM 'array'\n"
                                             "  OR NOT coalesce((v.source_basis->'artifacts') @> "
                                             "(cal#>'{material,source_basis,artifacts}'),false) "
                                             'THEN\n'
                                             "  RAISE EXCEPTION 'Calendar requires the exact "
                                             "native reference and retained direct sources' USING "
                                             "ERRCODE='23514'; END IF;\n"
                                             " IF ref->>'kind'='project_plan' THEN\n"
                                             '  IF NOT EXISTS(SELECT 1 FROM public.plan_revisions '
                                             'pl JOIN public.plan_proposals pp\n'
                                             '   ON pp.tenant_id=pl.tenant_id AND '
                                             'pp.category_id=pl.category_id AND '
                                             'pp.product_id=pl.product_id\n'
                                             '    AND pp.project_id=pl.project_id AND '
                                             'pp.id=pl.proposal_id\n'
                                             '   JOIN public.project_product_links link ON '
                                             'link.tenant_id=pl.tenant_id AND '
                                             'link.category_id=pl.category_id\n'
                                             '    AND link.product_id=pl.product_id AND '
                                             'link.project_id=pl.project_id\n'
                                             '   WHERE pl.tenant_id=t AND '
                                             'pl.category_id=v.category_id AND '
                                             'pl.product_id=v.product_id AND '
                                             'pl.project_id=v.project_id\n'
                                             "    AND pl.id::text=ref->>'id' AND "
                                             "pl.revision::text=ref->>'revision' AND "
                                             "pl.status='applied'\n"
                                             "    AND pl.id::text=cal->'material'->>'plan_id' AND "
                                             "pl.revision::text=cal->'material'->>'plan_revision'\n"
                                             "    AND pp.id::text=cal->'material'->>'proposal_id' "
                                             'AND '
                                             "pp.revision::text=cal->'material'->>'proposal_revision'\n"
                                             '    AND '
                                             "cal->'material'->'definition_ref'=jsonb_build_object('id',link.definition_id,'revision',link.definition_revision)\n"
                                             '    AND '
                                             "pp.input_snapshot->'calendar'=cal->'source_calendar'\n"
                                             '    AND '
                                             "ref->>'calendar_key'=pp.input_snapshot->'calendar'->>'key'\n"
                                             '    AND '
                                             "ref->>'calendar_version'=pp.input_snapshot->'calendar'->>'version'\n"
                                             '    AND '
                                             "coalesce(ref->'resource_id','null'::jsonb)='null'::jsonb) "
                                             'THEN\n'
                                             "   RAISE EXCEPTION 'Calendar is not the selected "
                                             "actual project plan calendar' USING ERRCODE='23514'; "
                                             'END IF;\n'
                                             " ELSIF ref->>'kind'='build_resource' THEN\n"
                                             '  IF NOT EXISTS(SELECT 1 FROM '
                                             'public.build_operational_facts fixed\n'
                                             '   JOIN public.build_operational_current ptr ON '
                                             'ptr.tenant_id=fixed.tenant_id AND '
                                             'ptr.category_id=fixed.category_id\n'
                                             '    AND ptr.product_id=fixed.product_id AND '
                                             'ptr.project_id=fixed.project_id AND '
                                             'ptr.build_id=fixed.build_id\n'
                                             '   JOIN public.build_operational_facts live ON '
                                             'live.tenant_id=ptr.tenant_id AND '
                                             'live.category_id=ptr.category_id\n'
                                             '    AND live.product_id=ptr.product_id AND '
                                             'live.project_id=ptr.project_id AND '
                                             'live.build_id=ptr.build_id\n'
                                             '    AND live.id=ptr.fact_id AND '
                                             'live.revision=ptr.fact_revision AND '
                                             'live.series_id=fixed.series_id\n'
                                             '   JOIN LATERAL '
                                             "jsonb_array_elements(fixed.data->'resources') res ON "
                                             'true\n'
                                             '   JOIN LATERAL '
                                             "jsonb_array_elements(live.data->'resources') actual "
                                             'ON true\n'
                                             '   JOIN public.operational_asset_sentinels asset ON '
                                             'asset.tenant_id=fixed.tenant_id\n'
                                             "    AND asset.id::text=actual->'resource'->>'id' AND "
                                             "asset.revision::text=actual->'resource'->>'revision'\n"
                                             '   WHERE fixed.tenant_id=t AND '
                                             'fixed.category_id=v.category_id AND '
                                             'fixed.product_id=v.product_id AND '
                                             'fixed.project_id=v.project_id\n'
                                             "    AND fixed.id::text=ref->>'id' AND "
                                             "fixed.revision::text=ref->>'revision'\n"
                                             "    AND fixed.id::text=cal->'material'->>'fact_id' "
                                             'AND '
                                             "fixed.revision::text=cal->'material'->>'fact_revision'\n"
                                             '    AND '
                                             "fixed.fact_sha256=cal->'material'->>'fact_sha256' "
                                             'AND '
                                             "fixed.build_id::text=cal->'material'->>'build_id'\n"
                                             "    AND fixed.state='active' AND "
                                             'fixed.valid_from<=v.created_at AND '
                                             '(fixed.valid_until IS NULL OR '
                                             'v.created_at<fixed.valid_until)\n'
                                             "    AND live.state='active' AND "
                                             'live.valid_from<=v.created_at AND (live.valid_until '
                                             'IS NULL OR v.created_at<live.valid_until)\n'
                                             "    AND res->'resource'->>'id'=ref->>'resource_id' "
                                             "AND actual->'resource'->>'id'=ref->>'resource_id'\n"
                                             '    AND '
                                             "cal->'material'->>'resource_id'=ref->>'resource_id' "
                                             'AND '
                                             "res->'resource'->>'revision'=cal->'material'->>'resource_revision'\n"
                                             "    AND res->>'lifecycle'='active' AND "
                                             "actual->>'lifecycle'='active'\n"
                                             "    AND res->'calendar'=cal->'source_calendar' AND "
                                             "actual->'calendar'->>'calendar_id'=res->'calendar'->>'calendar_id'\n"
                                             '    AND '
                                             "ref->>'calendar_key'=res->'calendar'->>'calendar_id' "
                                             'AND '
                                             "ref->>'calendar_version'=res->'calendar'->>'version'\n"
                                             "    AND asset.kind='resource' AND "
                                             "asset.data->>'state'='active') THEN\n"
                                             "   RAISE EXCEPTION 'Calendar is not a retained "
                                             "native resource with a currently usable source' "
                                             "USING ERRCODE='23514'; END IF;\n"
                                             " ELSE RAISE EXCEPTION 'Unknown native calendar "
                                             "source' USING ERRCODE='23514'; END IF;\n"
                                             'END;\n'
                                             '$function$\n'}
