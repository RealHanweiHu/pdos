"""Disambiguate the channel retention trigger local category array."""

SIGNATURE = 'dingtalk_lifecycle_reference_clock()'
PREVIOUS_FUNCTIONS = {SIGNATURE: (
        'CREATE OR REPLACE FUNCTION public.dingtalk_lifecycle_reference_clock()\n RET'
        "URNS trigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_"
        "catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE t uuid; dependencies j"
        'sonb; kind text; payload jsonb; categories uuid[];\n c uuid; model_id uuid; '
        "roots uuid[]='{}'; affected integer;\nBEGIN\n IF TG_TABLE_NAME<>'dingtalk_de"
        "liveries' THEN RAISE EXCEPTION 'Delivery-only lifecycle guard' USING ERRCODE"
        "='23514'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF ROW(NEW.tenant_id,NEW.sourc"
        'e_dependencies,NEW.content_kind,NEW.payload_sha256) IS DISTINCT FROM\n   ROW'
        '(OLD.tenant_id,OLD.source_dependencies,OLD.content_kind,OLD.payload_sha256) '
        "THEN\n   RAISE EXCEPTION 'Delivery retention footprint is immutable' USING E"
        "RRCODE='23514',CONSTRAINT='dingtalk_source_identity_immutable'; END IF;\n  -"
        '- Transport receipt/state updates neither create nor remove this immutable\n'
        '  -- copy. They remain possible while old roots are pending/quarantined.\n  '
        "RETURN NEW;\n END IF;\n IF TG_OP='DELETE' THEN t=OLD.tenant_id; dependencies"
        '=OLD.source_dependencies; kind=OLD.content_kind;\n ELSE t=NEW.tenant_id; dep'
        'endencies=NEW.source_dependencies; kind=NEW.content_kind; END IF;\n IF t IS '
        "DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n  OR "
        "jsonb_typeof(dependencies) IS DISTINCT FROM 'array' THEN\n  RAISE EXCEPTION "
        "'Delivery retention tenant/shape mismatch' USING ERRCODE='23514'; END IF;\n "
        "IF kind<>'answer' THEN\n  IF jsonb_array_length(dependencies)<>0 THEN RAISE "
        "EXCEPTION 'Control messages have no business footprint' USING ERRCODE='23514"
        "'; END IF;\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\n "
        'END IF;\n IF jsonb_array_length(dependencies)=0 OR EXISTS(SELECT 1 FROM json'
        "b_array_elements(dependencies) d\n  WHERE jsonb_typeof(d)<>'object' OR NOT(d"
        " ?& ARRAY['source_type','source_id','source_revision','content_hash','catego"
        "ry_id'])\n   OR d-ARRAY['source_type','source_id','source_revision','content"
        "_hash','category_id']<>'{}'::jsonb\n   OR d->>'category_id' IS NULL) THEN\n "
        " RAISE EXCEPTION 'Fixed Delivery source footprint required' USING ERRCODE='2"
        "3514'; END IF;\n SELECT array_agg(id ORDER BY id) INTO categories FROM\n  (S"
        "ELECT DISTINCT (value->>'category_id')::uuid AS id FROM jsonb_array_elements"
        '(dependencies)) groups;\n -- Preserve native category\u2192product order: lo'
        'ck ALL actual categories sorted\n -- before touching any product, then updat'
        'e actual root products sorted.\n PERFORM 1 FROM public.categories WHERE tena'
        'nt_id=t AND id=ANY(categories) ORDER BY id FOR UPDATE;\n GET DIAGNOSTICS aff'
        'ected=ROW_COUNT;\n IF affected<>cardinality(categories) THEN RAISE EXCEPTION'
        " 'Delivery source category unavailable' USING ERRCODE='23514'; END IF;\n pay"
        "load=jsonb_build_object('tenant_id',t,'source_dependencies',dependencies,'co"
        "ntent_kind',kind);\n FOREACH c IN ARRAY categories LOOP\n  roots=roots||publ"
        "ic.m3_lifecycle_roots(t,c,'dingtalk_deliveries',payload);\n END LOOP;\n FOR "
        'model_id IN SELECT DISTINCT id FROM (\n  SELECT product_id AS id FROM public'
        '.uploaded_originals WHERE tenant_id=t AND category_id=ANY(categories) AND id'
        '=ANY(roots)\n  UNION SELECT product_id FROM public.lifecycle_objects WHERE t'
        'enant_id=t AND category_id=ANY(categories) AND id=ANY(roots)\n  UNION SELECT'
        ' product_id FROM public.upload_attempts WHERE tenant_id=t AND category_id=AN'
        'Y(categories) AND id=ANY(roots)\n ) affected_products WHERE id IS NOT NULL O'
        'RDER BY id LOOP\n  UPDATE public.products SET lifecycle_epoch=lifecycle_epoc'
        'h+1\n   WHERE tenant_id=t AND category_id=ANY(categories) AND id=model_id;\n'
        "  IF NOT FOUND THEN RAISE EXCEPTION 'Delivery source product unavailable' US"
        "ING ERRCODE='23514'; END IF;\n END LOOP;\n UPDATE public.categories SET life"
        'cycle_epoch=lifecycle_epoch+1 WHERE tenant_id=t AND id=ANY(categories);\n IF'
        " TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND;\n$function$"
        '\n'
    )}
NATIVE_FUNCTIONS = {SIGNATURE: (
        'CREATE OR REPLACE FUNCTION public.dingtalk_lifecycle_reference_clock()\n RET'
        "URNS trigger\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_"
        "catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE t uuid; dependencies j"
        'sonb; kind text; payload jsonb; source_categories uuid[];\n c uuid; model_id'
        " uuid; roots uuid[]='{}'; affected integer;\nBEGIN\n IF TG_TABLE_NAME<>'ding"
        "talk_deliveries' THEN RAISE EXCEPTION 'Delivery-only lifecycle guard' USING "
        "ERRCODE='23514'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF ROW(NEW.tenant_id,NE"
        'W.source_dependencies,NEW.content_kind,NEW.payload_sha256) IS DISTINCT FROM'
        '\n   ROW(OLD.tenant_id,OLD.source_dependencies,OLD.content_kind,OLD.payload_'
        "sha256) THEN\n   RAISE EXCEPTION 'Delivery retention footprint is immutable'"
        " USING ERRCODE='23514',CONSTRAINT='dingtalk_source_identity_immutable'; END "
        'IF;\n  -- Transport receipt/state updates neither create nor remove this imm'
        'utable\n  -- copy. They remain possible while old roots are pending/quaranti'
        "ned.\n  RETURN NEW;\n END IF;\n IF TG_OP='DELETE' THEN t=OLD.tenant_id; depe"
        'ndencies=OLD.source_dependencies; kind=OLD.content_kind;\n ELSE t=NEW.tenant'
        '_id; dependencies=NEW.source_dependencies; kind=NEW.content_kind; END IF;\n '
        "IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uui"
        "d\n  OR jsonb_typeof(dependencies) IS DISTINCT FROM 'array' THEN\n  RAISE EX"
        "CEPTION 'Delivery retention tenant/shape mismatch' USING ERRCODE='23514'; EN"
        "D IF;\n IF kind<>'answer' THEN\n  IF jsonb_array_length(dependencies)<>0 THE"
        "N RAISE EXCEPTION 'Control messages have no business footprint' USING ERRCOD"
        "E='23514'; END IF;\n  IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; EN"
        'D IF;\n END IF;\n IF jsonb_array_length(dependencies)=0 OR EXISTS(SELECT 1 F'
        "ROM jsonb_array_elements(dependencies) d\n  WHERE jsonb_typeof(d)<>'object' "
        "OR NOT(d ?& ARRAY['source_type','source_id','source_revision','content_hash'"
        ",'category_id'])\n   OR d-ARRAY['source_type','source_id','source_revision',"
        "'content_hash','category_id']<>'{}'::jsonb\n   OR d->>'category_id' IS NULL)"
        " THEN\n  RAISE EXCEPTION 'Fixed Delivery source footprint required' USING ER"
        "RCODE='23514'; END IF;\n SELECT array_agg(id ORDER BY id) INTO source_catego"
        "ries FROM\n  (SELECT DISTINCT (value->>'category_id')::uuid AS id FROM jsonb"
        '_array_elements(dependencies)) groups;\n -- Preserve native category\u2192pr'
        'oduct order: lock ALL actual categories sorted\n -- before touching any prod'
        'uct, then update actual root products sorted.\n PERFORM 1 FROM public.catego'
        'ries WHERE tenant_id=t AND id=ANY(source_categories) ORDER BY id FOR UPDATE;'
        '\n GET DIAGNOSTICS affected=ROW_COUNT;\n IF affected<>cardinality(source_cat'
        "egories) THEN RAISE EXCEPTION 'Delivery source category unavailable' USING E"
        "RRCODE='23514'; END IF;\n payload=jsonb_build_object('tenant_id',t,'source_d"
        "ependencies',dependencies,'content_kind',kind);\n FOREACH c IN ARRAY source_"
        "categories LOOP\n  roots=roots||public.m3_lifecycle_roots(t,c,'dingtalk_deli"
        "veries',payload);\n END LOOP;\n FOR model_id IN SELECT DISTINCT id FROM (\n "
        ' SELECT product_id AS id FROM public.uploaded_originals WHERE tenant_id=t AN'
        'D category_id=ANY(source_categories) AND id=ANY(roots)\n  UNION SELECT produ'
        'ct_id FROM public.lifecycle_objects WHERE tenant_id=t AND category_id=ANY(so'
        'urce_categories) AND id=ANY(roots)\n  UNION SELECT product_id FROM public.up'
        'load_attempts WHERE tenant_id=t AND category_id=ANY(source_categories) AND i'
        'd=ANY(roots)\n ) affected_products WHERE id IS NOT NULL ORDER BY id LOOP\n  '
        'UPDATE public.products SET lifecycle_epoch=lifecycle_epoch+1\n   WHERE tenan'
        't_id=t AND category_id=ANY(source_categories) AND id=model_id;\n  IF NOT FOU'
        "ND THEN RAISE EXCEPTION 'Delivery source product unavailable' USING ERRCODE="
        "'23514'; END IF;\n END LOOP;\n UPDATE public.categories SET lifecycle_epoch="
        'lifecycle_epoch+1 WHERE tenant_id=t AND id=ANY(source_categories);\n IF TG_O'
        "P='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;\nEND;\n$function$\n"
    )}
SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
