"""Include native Field feedback in the existing derived-only recovery primitive."""

SIGNATURE = 'enterprise_index_source_clear(text,uuid,uuid,text,uuid[])'
PREVIOUS_FUNCTIONS = {SIGNATURE: (
        'CREATE OR REPLACE FUNCTION public.enterprise_index_source_clear(kind tex'
        't, sid uuid, category uuid, expected_key text, expected_ids uuid[])\n RET'
        "URNS void\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_ca"
        "talog', 'public', 'pg_temp'\nAS $function$\nDECLARE\n  t uuid := NULLIF(cur"
        "rent_setting('pdos.tenant_id',true),'')::uuid;\n  a uuid := NULLIF(curren"
        "t_setting('pdos.actor_id',true),'')::uuid;\n  r uuid := NULLIF(current_se"
        "tting('pdos.requester_id',true),'')::uuid;\nBEGIN\n  IF t IS NULL OR a IS "
        'NULL OR r IS NULL\n     OR NOT EXISTS(SELECT 1 FROM public.principals p\n '
        '                  WHERE p.tenant_id=t AND p.id=a AND p.active)\n     OR N'
        'OT EXISTS(SELECT 1 FROM public.principals p\n                   WHERE p.t'
        'enant_id=t AND p.id=r AND p.active)\n     OR public.category_access(t,cat'
        "egory,false) IS DISTINCT FROM true THEN\n    RAISE EXCEPTION 'Derived sou"
        "rce repair requires active bound source scope'\n      USING ERRCODE='4250"
        "1';\n  END IF;\n  IF kind IS NULL OR kind NOT IN\n     ('artifact','knowled"
        "ge','issue','capa','change','test_run','build','supply','external_wait')"
        "\n     OR sid IS NULL OR expected_key IS NULL OR expected_key !~ '^[a-f0-"
        "9]{64}$'\n     OR expected_ids IS NULL OR array_position(expected_ids,NUL"
        "L) IS NOT NULL THEN\n    RAISE EXCEPTION 'Derived source repair requires "
        "projector-computed identity'\n      USING ERRCODE='22023';\n  END IF;\n  PE"
        "RFORM pg_advisory_xact_lock(hashtextextended('enterprise-index:' || t::t"
        'ext,0));\n  DELETE FROM public.enterprise_search_chunks c WHERE c.tenant_'
        'id=t\n    AND ((c.source_type=kind AND c.source_id=sid)\n      OR c.work_k'
        'ey=expected_key OR c.id=ANY(expected_ids));\n  DELETE FROM public.enterpr'
        'ise_search_sources s WHERE s.tenant_id=t\n    AND ((s.source_type=kind AN'
        'D s.source_id=sid) OR s.work_key=expected_key);\nEND $function$\n'
    )}
NATIVE_FUNCTIONS = {SIGNATURE: (
        'CREATE OR REPLACE FUNCTION public.enterprise_index_source_clear(kind tex'
        't, sid uuid, category uuid, expected_key text, expected_ids uuid[])\n RET'
        "URNS void\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_ca"
        "talog', 'public', 'pg_temp'\nAS $function$\nDECLARE\n  t uuid := NULLIF(cur"
        "rent_setting('pdos.tenant_id',true),'')::uuid;\n  a uuid := NULLIF(curren"
        "t_setting('pdos.actor_id',true),'')::uuid;\n  r uuid := NULLIF(current_se"
        "tting('pdos.requester_id',true),'')::uuid;\nBEGIN\n  IF t IS NULL OR a IS "
        'NULL OR r IS NULL\n     OR NOT EXISTS(SELECT 1 FROM public.principals p\n '
        '                  WHERE p.tenant_id=t AND p.id=a AND p.active)\n     OR N'
        'OT EXISTS(SELECT 1 FROM public.principals p\n                   WHERE p.t'
        'enant_id=t AND p.id=r AND p.active)\n     OR public.category_access(t,cat'
        "egory,false) IS DISTINCT FROM true THEN\n    RAISE EXCEPTION 'Derived sou"
        "rce repair requires active bound source scope'\n      USING ERRCODE='4250"
        "1';\n  END IF;\n  IF kind IS NULL OR kind NOT IN\n     ('artifact','knowled"
        "ge','issue','capa','change','test_run','build','supply','external_wait',"
        "'field_feedback')\n     OR sid IS NULL OR expected_key IS NULL OR expecte"
        "d_key !~ '^[a-f0-9]{64}$'\n     OR expected_ids IS NULL OR array_position"
        "(expected_ids,NULL) IS NOT NULL THEN\n    RAISE EXCEPTION 'Derived source"
        " repair requires projector-computed identity'\n      USING ERRCODE='22023"
        "';\n  END IF;\n  PERFORM pg_advisory_xact_lock(hashtextextended('enterpris"
        "e-index:' || t::text,0));\n  DELETE FROM public.enterprise_search_chunks "
        'c WHERE c.tenant_id=t\n    AND ((c.source_type=kind AND c.source_id=sid)\n'
        '      OR c.work_key=expected_key OR c.id=ANY(expected_ids));\n  DELETE FR'
        'OM public.enterprise_search_sources s WHERE s.tenant_id=t\n    AND ((s.so'
        'urce_type=kind AND s.source_id=sid) OR s.work_key=expected_key);\nEND $fu'
        'nction$\n'
    )}
SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
