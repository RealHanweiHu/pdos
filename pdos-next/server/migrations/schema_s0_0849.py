"""Native role sources use the existing visibility, lifecycle and index recovery ports."""

PREVIOUS_FUNCTIONS = {
    'assistant_source_lifecycle_links(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.assistant_source_lifecycle_links(t uuid, c'
        ' uuid, proof jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE SECURITY DE'
        "FINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$"
        "\n\nDECLARE links uuid[]='{}'; item jsonb; container jsonb; key text;\nBEGIN"
        "\n IF jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN\n  RAISE EXCEPTION '"
        "Fixed assistant source dependencies must be an array' USING ERRCODE='23514';"
        ' END IF;\n FOR item IN SELECT value FROM jsonb_array_elements(proof) LOOP\n '
        " IF item->>'category_id' IS DISTINCT FROM c::text\n   OR item->>'source_type"
        "' IS NULL\n   OR item->>'source_type'<>ALL(ARRAY['artifact','knowledge','iss"
        "ue','capa','change','external_wait','supply','build','test_run','field_feedb"
        "ack'])\n   OR item->>'source_id' IS NULL\n   OR item->>'source_revision' IS "
        "NULL OR item->>'source_revision' !~ '^[1-9][0-9]*$'\n   OR item->>'content_h"
        "ash' IS NULL OR item->>'content_hash' !~ '^[a-f0-9]{64}$' THEN\n   RAISE EXC"
        "EPTION 'Assistant dependency must retain its actual fixed identity' USING ER"
        "RCODE='23514';\n  END IF;\n  links=array_append(links,(item->>'source_id')::"
        'uuid);\n  -- Exact original dependency projection, not read permission or bu'
        'siness facts.\n  -- Build/test record IDs resolve their own real registered '
        'Artifact read sets.\n  FOR container IN\n   SELECT s.required_source_read_se'
        "t AS reads FROM public.quality_issue_versions s WHERE item->>'source_type'='"
        "issue' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_i"
        "d'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads FROM public."
        "quality_issue_versions s WHERE item->>'source_type'='capa' AND s.tenant_id=t"
        " AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SEL"
        'ECT s.required_source_read_set AS reads FROM public.change_request_versions '
        "s WHERE item->>'source_type'='change' AND s.tenant_id=t AND s.category_id=c "
        "AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.reads AS reads "
        "FROM public.external_wait_versions s WHERE item->>'source_type'='external_wa"
        "it' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'"
        '\n   UNION ALL\n   SELECT s.required_source_read_set AS reads FROM public.su'
        "pply_snapshots s WHERE item->>'source_type'='supply' AND s.tenant_id=t AND s"
        ".category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s."
        "required_source_read_set AS reads FROM public.build_starts s WHERE item->>'s"
        "ource_type'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::text=ite"
        "m->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads"
        " FROM public.actual_configurations s WHERE item->>'source_type'='build' AND "
        "s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNIO"
        'N ALL\n   SELECT s.required_source_read_set AS reads FROM public.build_lots '
        "s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.category_id=c A"
        "ND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_"
        "read_set AS reads FROM public.verification_run_versions s WHERE item->>'sour"
        "ce_type'='test_run' AND s.tenant_id=t AND s.category_id=c AND s.id::text=ite"
        "m->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads"
        " FROM public.test_result_actions s WHERE item->>'source_type'='test_run' AND"
        " s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNI"
        "ON ALL\n   SELECT coalesce(e.required_source_read_set,'[]'::jsonb)||coalesce"
        "(p.required_source_read_set,'[]'::jsonb) AS reads FROM public.builds b JOIN "
        'public.engineering_configurations e ON e.tenant_id=b.tenant_id AND e.categor'
        'y_id=b.category_id AND e.id=b.engineering_configuration_id JOIN public.proce'
        'ss_revisions p ON p.tenant_id=b.tenant_id AND p.category_id=b.category_id AN'
        "D p.id=b.manufacturing_configuration_id WHERE item->>'source_type'='build' A"
        "ND b.tenant_id=t AND b.category_id=c AND b.id::text=item->>'source_id'\n   U"
        "NION ALL\n   SELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id',root"
        "->'id',\n      'expected_revision',root->'revision')),'[]'::jsonb) AS reads"
        '\n    FROM public.field_feedback_versions s\n     CROSS JOIN LATERAL jsonb_a'
        "rray_elements(s.source_basis->'artifacts') root\n    WHERE item->>'source_ty"
        "pe'='field_feedback' AND s.tenant_id=t AND s.category_id=c\n     AND s.id::t"
        "ext=item->>'source_id'\n   UNION ALL\n   SELECT coalesce(jsonb_agg(jsonb_bui"
        "ld_object('artifact_id',root->'id',\n      'expected_revision',root->'revisi"
        "on')),'[]'::jsonb) AS reads\n    FROM public.field_response_records s\n     "
        "CROSS JOIN LATERAL jsonb_array_elements(s.source_basis->'artifacts') root\n "
        "   WHERE item->>'source_type'='field_feedback' AND s.tenant_id=t AND s.categ"
        "ory_id=c\n     AND s.id::text=item->>'source_id'\n  LOOP\n   FOR key IN SELE"
        "CT value->>'artifact_id' FROM jsonb_array_elements(coalesce(container,'[]'::"
        'jsonb)) LOOP\n    IF key IS NOT NULL THEN links=array_append(links,key::uuid'
        '); END IF;\n   END LOOP;\n  END LOOP;\n END LOOP;\n RETURN links;\nEND\n;\n$'
        'function$\n'
    ),
    'knowledge_answer_sources_visible(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_visible(t uuid, c'
        ' uuid, proof jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n STABLE\n SET sear'
        "ch_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\n\nDECLARE expec"
        'ted jsonb; visible boolean;\nBEGIN\n IF t IS DISTINCT FROM nullif(current_se'
        "tting('pdos.tenant_id',true),'')::uuid\n OR NOT public.category_access(t,c) "
        "OR jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
        ' FOR expected IN SELECT value FROM jsonb_array_elements(proof) LOOP\n  IF ex'
        "pected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false; END IF;\n"
        "  CASE expected->>'source_type'\n WHEN 'artifact' THEN\n  WITH authoritative"
        "_enterprise_sources_c7c5c1d70c5dec44 AS \n(SELECT 'artifact' AS source_type,"
        ' artifact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id'
        ', artifact_versions.category_id AS category_id, artifact_versions.product_id'
        ' AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS prop'
        'osal_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision '
        'AS source_revision, artifact_versions.title AS title, artifact_versions.cont'
        'ent_hash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JS'
        "ONB) AS structured, 'untrusted' AS nature, artifact_versions.visibility != '"
        "category' OR coalesce(products.visibility != 'category', false) OR coalesce("
        "uploaded_originals.visibility != 'category', false) AS private, artifact_ver"
        'sions.original_id IS NOT NULL AS customer_original, true AS is_current, arti'
        'fact_versions.created_at AS created_at, artifact_versions.original_id AS ori'
        'ginal_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.or'
        'iginal_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY['
        "]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifac"
        't_versions LEFT OUTER JOIN products ON products.tenant_id = artifact_version'
        's.tenant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN u'
        'ploaded_originals ON uploaded_originals.tenant_id = artifact_versions.tenant'
        '_id AND uploaded_originals.id = artifact_versions.original_id AND uploaded_o'
        'riginals.category_id = artifact_versions.category_id AND uploaded_originals.'
        'product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN'
        ' original_security ON original_security.tenant_id = uploaded_originals.tenan'
        't_id AND original_security.original_id = uploaded_originals.id \nWHERE artif'
        "act_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)"
        ", '') AS UUID) AND artifact_versions.status = 'active' AND artifact_versions"
        '.category_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR produc'
        'ts.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_or'
        "iginals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded"
        "_originals.scan_status = 'clean' AND original_security.source_state = 'activ"
        "e' AND original_security.disposition = 'active' AND original_security.curren"
        't_request_id IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_en'
        'terprise_sources_c7c5c1d70c5dec44 \nWHERE authoritative_enterprise_sources_c'
        '7c5c1d70c5dec44.tenant_id = t AND authoritative_enterprise_sources_c7c5c1d70'
        'c5dec44.category_id = c AND CAST(authoritative_enterprise_sources_c7c5c1d70c'
        "5dec44.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_en"
        "terprise_sources_c7c5c1d70c5dec44.source_revision AS TEXT) = expected->>'sou"
        "rce_revision' AND authoritative_enterprise_sources_c7c5c1d70c5dec44.content_"
        "hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'knowledge'"
        ' THEN\n  SELECT EXISTS (SELECT 1 \nFROM (SELECT category_knowledge_entries.i'
        'd AS source_id, category_knowledge_entries.tenant_id AS tenant_id, category_'
        'knowledge_entries.category_id AS category_id, category_knowledge_entries.ver'
        'sion AS source_revision, encode(sha256(convert_to(CAST(category_knowledge_en'
        "tries.content AS TEXT), 'UTF8')), 'hex') AS content_hash \nFROM category_kno"
        'wledge_entries JOIN category_knowledge_current ON category_knowledge_current'
        '.tenant_id = category_knowledge_entries.tenant_id AND category_knowledge_cur'
        'rent.lineage_id = category_knowledge_entries.lineage_id AND category_knowled'
        "ge_current.status = 'active' \nWHERE category_knowledge_entries.action != 'w"
        "ithdraw' UNION ALL SELECT knowledge_rule_versions.id AS source_id, knowledge"
        '_rule_versions.tenant_id AS tenant_id, knowledge_rule_versions.category_id A'
        'S category_id, knowledge_rule_versions.revision AS source_revision, encode(s'
        "ha256(convert_to(CAST(knowledge_rule_versions.body AS TEXT), 'UTF8')), 'hex'"
        ') AS content_hash \nFROM knowledge_rule_versions JOIN knowledge_rule_current'
        's ON knowledge_rule_currents.tenant_id = knowledge_rule_versions.tenant_id A'
        'ND knowledge_rule_currents.rule_id = knowledge_rule_versions.rule_id) AS ord'
        'inary_knowledge_leaves \nWHERE ordinary_knowledge_leaves.tenant_id = t AND o'
        'rdinary_knowledge_leaves.category_id = c AND CAST(ordinary_knowledge_leaves.'
        "source_id AS TEXT) = expected->>'source_id' AND CAST(ordinary_knowledge_leav"
        "es.source_revision AS TEXT) = expected->>'source_revision' AND ordinary_know"
        "ledge_leaves.content_hash = expected->>'content_hash') AS anon_1 INTO visibl"
        "e;\n WHEN 'issue' THEN\n  WITH enterprise_authoritative_artifacts_4a502846d0"
        "70e208 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sourc"
        'e_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category_i'
        'd AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS U'
        'UID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.own'
        'er_id AS owner_id, artifact_versions.revision AS source_revision, artifact_v'
        'ersions.title AS title, artifact_versions.content_hash AS content_hash, arti'
        "fact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted"
        "' AS nature, artifact_versions.visibility != 'category' OR coalesce(products"
        ".visibility != 'category', false) OR coalesce(uploaded_originals.visibility "
        "!= 'category', false) AS private, artifact_versions.original_id IS NOT NULL "
        'AS customer_original, true AS is_current, artifact_versions.created_at AS cr'
        'eated_at, artifact_versions.original_id AS original_id, artifact_versions.id'
        ' AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN AR'
        'RAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids,'
        " 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN pro"
        'ducts ON products.tenant_id = artifact_versions.tenant_id AND products.id = '
        'artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_'
        'originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id '
        '= artifact_versions.original_id AND uploaded_originals.category_id = artifac'
        't_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT FRO'
        'M artifact_versions.product_id LEFT OUTER JOIN original_security ON original'
        '_security.tenant_id = uploaded_originals.tenant_id AND original_security.ori'
        'ginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_ve"
        "rsions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND ("
        'artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifa'
        'ct_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND upl'
        "oaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'clea"
        "n' AND original_security.source_state = 'active' AND original_security.dispo"
        "sition = 'active' AND original_security.current_request_id IS NOT NULL)), \n"
        'shared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT quality_i'
        'ssue_versions.product_id AS product_id, quality_issue_versions.project_id AS'
        ' project_id, quality_issue_versions.issue_id AS issue_id, quality_issue_vers'
        'ions.revision AS revision, quality_issue_versions.previous_issue_version_id '
        'AS previous_issue_version_id, quality_issue_versions.previous_revision AS pr'
        'evious_revision, quality_issue_versions.owner_id AS owner_id, quality_issue_'
        'versions.writer_id AS writer_id, quality_issue_versions.visibility AS visibi'
        'lity, quality_issue_versions.purpose AS purpose, quality_issue_versions.stat'
        'us AS status, quality_issue_versions.operation AS operation, quality_issue_v'
        'ersions.issue_snapshot AS issue_snapshot, quality_issue_versions.snapshot_sh'
        'a256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS input_snap'
        'shot, quality_issue_versions.authority_snapshot AS authority_snapshot, quali'
        'ty_issue_versions.policy_snapshot AS policy_snapshot, quality_issue_versions'
        '.sources AS sources, quality_issue_versions.required_source_read_set AS requ'
        'ired_source_read_set, quality_issue_versions.source_basis AS source_basis, q'
        'uality_issue_versions.intent_digest AS intent_digest, quality_issue_versions'
        '.reason AS reason, quality_issue_versions.id AS id, quality_issue_versions.t'
        'enant_id AS tenant_id, quality_issue_versions.created_at AS created_at, qual'
        'ity_issue_versions.category_id AS category_id \nFROM quality_issue_versions '
        "\nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_setting('pdos"
        ".tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIALI"
        'ZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS owner_'
        'id, projects.name AS name, projects.purpose AS purpose, projects.scope AS sc'
        'ope, projects.visibility AS visibility, projects.status AS status, projects.'
        'revision AS revision, projects.current_plan_id AS current_plan_id, projects.'
        'trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projects.g0'
        '_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id AS ten'
        'ant_id, projects.created_at AS created_at, projects.category_id AS category_'
        'id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS MATE"
        'RIALIZED \n(SELECT products.name AS name, products.purpose AS purpose, produ'
        'cts.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, produ'
        'cts.status AS status, products.owner_id AS owner_id, products.parent_product'
        '_id AS parent_product_id, products.category_id AS category_id, products.visi'
        'bility AS visibility, products.target_price AS target_price, products.target'
        '_price_currency AS target_price_currency, products.target_price_basis AS tar'
        'get_price_basis, products.target_price_includes_tax AS target_price_includes'
        '_tax, products.target_price_as_of AS target_price_as_of, products.id AS id, '
        'products.tenant_id AS tenant_id, products.created_at AS created_at \nFROM pr'
        "oducts \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.tenant"
        "_id', true), '') AS UUID)), \nshared_enterprise_quality_current_issues AS MA"
        'TERIALIZED \n(SELECT quality_current_issues.product_id AS product_id, qualit'
        'y_current_issues.project_id AS project_id, quality_current_issues.issue_id A'
        'S issue_id, quality_current_issues.issue_version_id AS issue_version_id, qua'
        'lity_current_issues.issue_revision AS issue_revision, quality_current_issues'
        '.epoch AS epoch, quality_current_issues.id AS id, quality_current_issues.ten'
        'ant_id AS tenant_id, quality_current_issues.created_at AS created_at, qualit'
        'y_current_issues.category_id AS category_id \nFROM quality_current_issues \n'
        "WHERE quality_current_issues.tenant_id = CAST(nullif(current_setting('pdos.t"
        "enant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_4a502846"
        "d070e208 AS \n(SELECT 'issue' AS source_type, shared_enterprise_quality_issu"
        'e_versions.id AS source_id, shared_enterprise_quality_issue_versions.tenant_'
        'id AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS cat'
        'egory_id, shared_enterprise_quality_issue_versions.product_id AS product_id,'
        ' shared_enterprise_quality_issue_versions.project_id AS project_id, CAST(NUL'
        'L AS UUID) AS proposal_id, shared_enterprise_quality_issue_versions.owner_id'
        ' AS owner_id, shared_enterprise_quality_issue_versions.revision AS source_re'
        "vision, shared_enterprise_quality_issue_versions.issue_snapshot ->> 'title' "
        "AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'facts'"
        ", jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.is"
        "sue_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot['ti"
        "tle'], 'status', shared_enterprise_quality_issue_versions.status, 'risk', sh"
        "ared_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_rechec"
        "k', shared_enterprise_quality_issue_versions.issue_snapshot['needs_recheck']"
        ", 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['recheck_reasons'], 'merged_into', shared_enterprise_quality_issue_versions"
        ".issue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'], "
        "'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root_ca"
        "use']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('id', enterprise_containment.value['id'], 'text', enterprise_con"
        "tainment.value['text'], 'executor_id', enterprise_containment.value['executo"
        "r_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS co"
        'alesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issu'
        "e_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDINAL"
        "ITY AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_objec"
        "t('text', shared_enterprise_quality_issue_versions.issue_snapshot['closure']"
        "['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions.iss"
        "ue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['art"
        "ifact_id'], 'version', enterprise_reads_issue.value['expected_revision']) OR"
        "DER BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_issu"
        "e.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM "
        'jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sourc'
        "e_read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_o"
        "bject('object_id', shared_enterprise_quality_issue_versions.issue_id, 'kind'"
        ", 'issue', 'facts', jsonb_build_object('issue_id', shared_enterprise_quality"
        "_issue_versions.issue_id, 'title', shared_enterprise_quality_issue_versions."
        "issue_snapshot['title'], 'status', shared_enterprise_quality_issue_versions."
        "status, 'risk', shared_enterprise_quality_issue_versions.issue_snapshot['ris"
        "k'], 'needs_recheck', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['needs_recheck'], 'recheck_reasons', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['recheck_reasons'], 'merged_into', shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['merged_into'], 'root_cause', jsonb_build_"
        "object('text', shared_enterprise_quality_issue_versions.issue_snapshot['root"
        "_cause']['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['root_cause']['actor_id'], 'at', shared_enterprise_quality_issue_v"
        "ersions.issue_snapshot['root_cause']['at']), 'containment', (SELECT coalesce"
        "(jsonb_agg(jsonb_build_object('id', enterprise_containment.value['id'], 'tex"
        "t', enterprise_containment.value['text'], 'executor_id', enterprise_containm"
        "ent.value['executor_id']) ORDER BY enterprise_containment.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['containment'], CAST('[]' AS JSO"
        "NB))) WITH ORDINALITY AS enterprise_containment(value, ordinal)), 'closure',"
        " jsonb_build_object('text', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['closure']['text'], 'actor_id', shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['closure']['actor_id'], 'at', shared_enterprise_quality_"
        "issue_versions.issue_snapshot['closure']['at'])), 'source_refs', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_read"
        "s_issue.value['artifact_id'], 'version', enterprise_reads_issue.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_issue.value ->> 'artifact_id', ent"
        "erprise_reads_issue.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versi'
        "ons.required_source_read_set) AS enterprise_reads_issue(value)), 'record_pol"
        "icy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'fac"
        "ts', jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions"
        ".issue_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot["
        "'title'], 'status', shared_enterprise_quality_issue_versions.status, 'risk',"
        " shared_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_rec"
        "heck', shared_enterprise_quality_issue_versions.issue_snapshot['needs_rechec"
        "k'], 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['recheck_reasons'], 'merged_into', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', "
        "shared_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'"
        "], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root"
        "_cause']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(json"
        "b_build_object('id', enterprise_containment.value['id'], 'text', enterprise_"
        "containment.value['text'], 'executor_id', enterprise_containment.value['exec"
        "utor_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS"
        ' coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_i'
        "ssue_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDI"
        "NALITY AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_ob"
        "ject('text', shared_enterprise_quality_issue_versions.issue_snapshot['closur"
        "e']['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions."
        "issue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg"
        "(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['"
        "artifact_id'], 'version', enterprise_reads_issue.value['expected_revision'])"
        " ORDER BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_i"
        "ssue.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFR"
        'OM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_so'
        "urce_read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_quality_is"
        "sue_versions.visibility != 'category' OR coalesce(shared_enterprise_projects"
        ".visibility != 'category', false) OR coalesce(shared_enterprise_products.vis"
        "ibility != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_quality_issue_versions.required_source_read_set) AS ent'
        'erprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_4a502846d'
        '070e208 ON enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = s'
        'hared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritati'
        've_artifacts_4a502846d070e208.source_id = CAST((enterprise_reads_issue.value'
        " ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a50"
        '2846d070e208.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_eleme'
        'nts(shared_enterprise_quality_issue_versions.required_source_read_set) AS en'
        'terprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_4a502846'
        'd070e208 ON enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = '
        'shared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritat'
        'ive_artifacts_4a502846d070e208.source_id = CAST((enterprise_reads_issue.valu'
        "e ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a5"
        '02846d070e208.customer_original) AS customer_original, shared_enterprise_qua'
        'lity_current_issues.issue_version_id = shared_enterprise_quality_issue_versi'
        'ons.id AS is_current, shared_enterprise_quality_issue_versions.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_quality_is'
        'sue_versions.issue_id AS object_id, (SELECT coalesce(array_agg(enterprise_au'
        'thoritative_artifacts_4a502846d070e208.original_id), ARRAY[]::UUID[]) AS coa'
        'lesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions'
        '.required_source_read_set) AS enterprise_reads_issue(value) JOIN enterprise_'
        'authoritative_artifacts_4a502846d070e208 ON enterprise_authoritative_artifac'
        'ts_4a502846d070e208.tenant_id = shared_enterprise_quality_issue_versions.ten'
        'ant_id AND enterprise_authoritative_artifacts_4a502846d070e208.source_id = C'
        "AST((enterprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_4a502846d070e208.original_id IS NOT NULL) AS or'
        'iginal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_e'
        'nterprise_quality_issue_versions.required_source_read_set) AS enterprise_rea'
        'ds_issue(value) JOIN enterprise_authoritative_artifacts_4a502846d070e208 ON '
        'enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = shared_enter'
        'prise_quality_issue_versions.tenant_id AND enterprise_authoritative_artifact'
        "s_4a502846d070e208.source_id = CAST((enterprise_reads_issue.value ->> 'artif"
        "act_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a502846d070e20"
        "8.source_revision != CAST((enterprise_reads_issue.value ->> 'expected_revisi"
        "on') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_sta"
        'tus \nFROM shared_enterprise_quality_issue_versions JOIN shared_enterprise_p'
        'rojects ON shared_enterprise_projects.tenant_id = shared_enterprise_quality_'
        'issue_versions.tenant_id AND shared_enterprise_projects.product_id = shared_'
        'enterprise_quality_issue_versions.product_id AND shared_enterprise_projects.'
        'id = shared_enterprise_quality_issue_versions.project_id AND shared_enterpri'
        'se_projects.category_id = shared_enterprise_quality_issue_versions.category_'
        'id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id ='
        ' shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise_pr'
        'oducts.id = shared_enterprise_quality_issue_versions.product_id AND shared_e'
        'nterprise_products.category_id = shared_enterprise_quality_issue_versions.ca'
        'tegory_id JOIN shared_enterprise_quality_current_issues ON shared_enterprise'
        '_quality_current_issues.tenant_id = shared_enterprise_quality_issue_versions'
        '.tenant_id AND shared_enterprise_quality_current_issues.product_id = shared_'
        'enterprise_quality_issue_versions.product_id AND shared_enterprise_quality_c'
        'urrent_issues.project_id = shared_enterprise_quality_issue_versions.project_'
        'id AND shared_enterprise_quality_current_issues.issue_id = shared_enterprise'
        '_quality_issue_versions.issue_id \nWHERE shared_enterprise_quality_issue_ver'
        "sions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') A"
        'S UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr'
        'ise_quality_issue_versions.required_source_read_set) AS enterprise_reads_iss'
        'ue(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_arti'
        'facts_4a502846d070e208 \nWHERE enterprise_authoritative_artifacts_4a502846d0'
        '70e208.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND en'
        'terprise_authoritative_artifacts_4a502846d070e208.source_id = CAST((enterpri'
        "se_reads_issue.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELEC"
        'T 1 \nFROM authoritative_enterprise_sources_4a502846d070e208 \nWHERE authori'
        'tative_enterprise_sources_4a502846d070e208.tenant_id = t AND authoritative_e'
        'nterprise_sources_4a502846d070e208.category_id = c AND CAST(authoritative_en'
        "terprise_sources_4a502846d070e208.source_id AS TEXT) = expected->>'source_id"
        "' AND CAST(authoritative_enterprise_sources_4a502846d070e208.source_revision"
        " AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_source"
        "s_4a502846d070e208.content_hash = expected->>'content_hash') AS anon_1 INTO "
        "visible;\n WHEN 'capa' THEN\n  WITH enterprise_authoritative_artifacts_b398e"
        "ff2ffc06d18 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS "
        'source_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.categ'
        'ory_id AS category_id, artifact_versions.product_id AS product_id, CAST(NULL'
        ' AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_version'
        's.owner_id AS owner_id, artifact_versions.revision AS source_revision, artif'
        'act_versions.title AS title, artifact_versions.content_hash AS content_hash,'
        " artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untr"
        "usted' AS nature, artifact_versions.visibility != 'category' OR coalesce(pro"
        "ducts.visibility != 'category', false) OR coalesce(uploaded_originals.visibi"
        "lity != 'category', false) AS private, artifact_versions.original_id IS NOT "
        'NULL AS customer_original, true AS is_current, artifact_versions.created_at '
        'AS created_at, artifact_versions.original_id AS original_id, artifact_versio'
        'ns.id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) TH'
        'EN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original'
        "_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOI"
        'N products ON products.tenant_id = artifact_versions.tenant_id AND products.'
        'id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uplo'
        'aded_originals.tenant_id = artifact_versions.tenant_id AND uploaded_original'
        's.id = artifact_versions.original_id AND uploaded_originals.category_id = ar'
        'tifact_versions.category_id AND uploaded_originals.product_id IS NOT DISTINC'
        'T FROM artifact_versions.product_id LEFT OUTER JOIN original_security ON ori'
        'ginal_security.tenant_id = uploaded_originals.tenant_id AND original_securit'
        'y.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifa"
        "ct_versions.status = 'active' AND artifact_versions.category_id IS NOT NULL "
        'AND (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (a'
        'rtifact_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AN'
        "D uploaded_originals.status = 'parsed' AND uploaded_originals.scan_status = "
        "'clean' AND original_security.source_state = 'active' AND original_security."
        "disposition = 'active' AND original_security.current_request_id IS NOT NULL)"
        '), \nshared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT qual'
        'ity_issue_versions.product_id AS product_id, quality_issue_versions.project_'
        'id AS project_id, quality_issue_versions.issue_id AS issue_id, quality_issue'
        '_versions.revision AS revision, quality_issue_versions.previous_issue_versio'
        'n_id AS previous_issue_version_id, quality_issue_versions.previous_revision '
        'AS previous_revision, quality_issue_versions.owner_id AS owner_id, quality_i'
        'ssue_versions.writer_id AS writer_id, quality_issue_versions.visibility AS v'
        'isibility, quality_issue_versions.purpose AS purpose, quality_issue_versions'
        '.status AS status, quality_issue_versions.operation AS operation, quality_is'
        'sue_versions.issue_snapshot AS issue_snapshot, quality_issue_versions.snapsh'
        'ot_sha256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS input'
        '_snapshot, quality_issue_versions.authority_snapshot AS authority_snapshot, '
        'quality_issue_versions.policy_snapshot AS policy_snapshot, quality_issue_ver'
        'sions.sources AS sources, quality_issue_versions.required_source_read_set AS'
        ' required_source_read_set, quality_issue_versions.source_basis AS source_bas'
        'is, quality_issue_versions.intent_digest AS intent_digest, quality_issue_ver'
        'sions.reason AS reason, quality_issue_versions.id AS id, quality_issue_versi'
        'ons.tenant_id AS tenant_id, quality_issue_versions.created_at AS created_at,'
        ' quality_issue_versions.category_id AS category_id \nFROM quality_issue_vers'
        'ions \nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATE"
        'RIALIZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS o'
        'wner_id, projects.name AS name, projects.purpose AS purpose, projects.scope '
        'AS scope, projects.visibility AS visibility, projects.status AS status, proj'
        'ects.revision AS revision, projects.current_plan_id AS current_plan_id, proj'
        'ects.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projec'
        'ts.g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id A'
        'S tenant_id, projects.created_at AS created_at, projects.category_id AS cate'
        'gory_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_set'
        "ting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS"
        ' MATERIALIZED \n(SELECT products.name AS name, products.purpose AS purpose, '
        'products.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, '
        'products.status AS status, products.owner_id AS owner_id, products.parent_pr'
        'oduct_id AS parent_product_id, products.category_id AS category_id, products'
        '.visibility AS visibility, products.target_price AS target_price, products.t'
        'arget_price_currency AS target_price_currency, products.target_price_basis A'
        'S target_price_basis, products.target_price_includes_tax AS target_price_inc'
        'ludes_tax, products.target_price_as_of AS target_price_as_of, products.id AS'
        ' id, products.tenant_id AS tenant_id, products.created_at AS created_at \nFR'
        "OM products \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.t"
        "enant_id', true), '') AS UUID)), \nshared_enterprise_quality_current_issues "
        'AS MATERIALIZED \n(SELECT quality_current_issues.product_id AS product_id, q'
        'uality_current_issues.project_id AS project_id, quality_current_issues.issue'
        '_id AS issue_id, quality_current_issues.issue_version_id AS issue_version_id'
        ', quality_current_issues.issue_revision AS issue_revision, quality_current_i'
        'ssues.epoch AS epoch, quality_current_issues.id AS id, quality_current_issue'
        's.tenant_id AS tenant_id, quality_current_issues.created_at AS created_at, q'
        'uality_current_issues.category_id AS category_id \nFROM quality_current_issu'
        "es \nWHERE quality_current_issues.tenant_id = CAST(nullif(current_setting('p"
        "dos.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_b39"
        "8eff2ffc06d18 AS \n(SELECT 'capa' AS source_type, shared_enterprise_quality_"
        'issue_versions.id AS source_id, shared_enterprise_quality_issue_versions.ten'
        'ant_id AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS'
        ' category_id, shared_enterprise_quality_issue_versions.product_id AS product'
        '_id, shared_enterprise_quality_issue_versions.project_id AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, shared_enterprise_quality_issue_versions.owne'
        'r_id AS owner_id, shared_enterprise_quality_issue_versions.revision AS sourc'
        "e_revision, 'CAPA \xb7 ' || (shared_enterprise_quality_issue_versions.issue_"
        "snapshot ->> 'title') AS title, encode(sha256(convert_to(CAST(CAST(jsonb_bui"
        "ld_object('object_id', CAST((shared_enterprise_quality_issue_versions.issue_"
        "snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', jsonb_build_ob"
        "ject('issue_id', shared_enterprise_quality_issue_versions.issue_id, 'capa_id"
        "', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['id'], 'i"
        "ssue_status', shared_enterprise_quality_issue_versions.status, 'hypotheses',"
        " (SELECT coalesce(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses"
        ".value['text']) ORDER BY enterprise_hypotheses.ordinal), jsonb_build_array()"
        ') AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quali'
        "ty_issue_versions.issue_snapshot['capa']['hypotheses'], CAST('[]' AS JSONB))"
        ") WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'actions', (SEL"
        "ECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_actions.valu"
        "e['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', enterprise_c"
        "apa_actions.value['text'], 'executor_id', enterprise_capa_actions.value['exe"
        "cutor_id'], 'completion_text', enterprise_capa_actions.value['completion']['"
        "text'], 'completed_by', enterprise_capa_actions.value['completion']['executo"
        "r_id'], 'completed_at', enterprise_capa_actions.value['completion']['at']['o"
        "ccurred_at']) ORDER BY enterprise_capa_actions.ordinal), jsonb_build_array()"
        ') AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quali'
        "ty_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' AS JSONB))) W"
        "ITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requirement', j"
        "sonb_build_object('method', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['capa']['requirement']['method'], 'acceptance', shared_enterprise_qu"
        "ality_issue_versions.issue_snapshot['capa']['requirement']['acceptance'], 'o"
        "bservation_until', shared_enterprise_quality_issue_versions.issue_snapshot['"
        "capa']['requirement']['observation_until']), 'effectiveness', jsonb_build_ob"
        "ject('text', shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        "['effectiveness']['text'], 'result', shared_enterprise_quality_issue_version"
        "s.issue_snapshot['capa']['effectiveness']['result'], 'actor_id', shared_ente"
        "rprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['actor"
        "_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        "['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('type', 'artifact', 'id', enterprise_reads_capa.value['artifact_"
        "id'], 'version', enterprise_reads_capa.value['expected_revision']) ORDER BY "
        "enterprise_reads_capa.value ->> 'artifact_id', enterprise_reads_capa.value -"
        ">> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_arr"
        'ay_elements(shared_enterprise_quality_issue_versions.required_source_read_se'
        "t) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', CAST((shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        ") ->> 'id' AS UUID), 'kind', 'capa', 'facts', jsonb_build_object('issue_id',"
        " shared_enterprise_quality_issue_versions.issue_id, 'capa_id', shared_enterp"
        "rise_quality_issue_versions.issue_snapshot['capa']['id'], 'issue_status', sh"
        "ared_enterprise_quality_issue_versions.status, 'hypotheses', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses.value['text']) "
        'ORDER BY enterprise_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 '
        '\nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_version'
        "s.issue_snapshot['capa']['hypotheses'], CAST('[]' AS JSONB))) WITH ORDINALIT"
        "Y AS enterprise_hypotheses(value, ordinal)), 'actions', (SELECT coalesce(jso"
        "nb_agg(jsonb_build_object('id', enterprise_capa_actions.value['id'], 'kind',"
        " enterprise_capa_actions.value['kind'], 'text', enterprise_capa_actions.valu"
        "e['text'], 'executor_id', enterprise_capa_actions.value['executor_id'], 'com"
        "pletion_text', enterprise_capa_actions.value['completion']['text'], 'complet"
        "ed_by', enterprise_capa_actions.value['completion']['executor_id'], 'complet"
        "ed_at', enterprise_capa_actions.value['completion']['at']['occurred_at']) OR"
        'DER BY enterprise_capa_actions.ordinal), jsonb_build_array()) AS coalesce_2 '
        '\nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_version'
        "s.issue_snapshot['capa']['actions'], CAST('[]' AS JSONB))) WITH ORDINALITY A"
        "S enterprise_capa_actions(value, ordinal)), 'requirement', jsonb_build_objec"
        "t('method', shared_enterprise_quality_issue_versions.issue_snapshot['capa']["
        "'requirement']['method'], 'acceptance', shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['capa']['requirement']['acceptance'], 'observation_until"
        "', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['requirem"
        "ent']['observation_until']), 'effectiveness', jsonb_build_object('text', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness'"
        "]['text'], 'result', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['capa']['effectiveness']['result'], 'actor_id', shared_enterprise_quality_i"
        "ssue_versions.issue_snapshot['capa']['effectiveness']['actor_id'], 'at', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness'"
        "]['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_capa.value['artifact_id'], 'version',"
        " enterprise_reads_capa.value['expected_revision']) ORDER BY enterprise_reads"
        "_capa.value ->> 'artifact_id', enterprise_reads_capa.value ->> 'expected_rev"
        "ision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(shar"
        'ed_enterprise_quality_issue_versions.required_source_read_set) AS enterprise'
        "_reads_capa(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAS"
        "T(jsonb_build_object('object_id', CAST((shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', jso"
        "nb_build_object('issue_id', shared_enterprise_quality_issue_versions.issue_i"
        "d, 'capa_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa'"
        "]['id'], 'issue_status', shared_enterprise_quality_issue_versions.status, 'h"
        "ypotheses', (SELECT coalesce(jsonb_agg(jsonb_build_object('text', enterprise"
        "_hypotheses.value['text']) ORDER BY enterprise_hypotheses.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['capa']['hypotheses'], CAST('[]'"
        " AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'act"
        "ions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_a"
        "ctions.value['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', e"
        "nterprise_capa_actions.value['text'], 'executor_id', enterprise_capa_actions"
        ".value['executor_id'], 'completion_text', enterprise_capa_actions.value['com"
        "pletion']['text'], 'completed_by', enterprise_capa_actions.value['completion"
        "']['executor_id'], 'completed_at', enterprise_capa_actions.value['completion"
        "']['at']['occurred_at']) ORDER BY enterprise_capa_actions.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' AS"
        " JSONB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requ"
        "irement', jsonb_build_object('method', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['capa']['requirement']['method'], 'acceptance', shared_en"
        "terprise_quality_issue_versions.issue_snapshot['capa']['requirement']['accep"
        "tance'], 'observation_until', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['capa']['requirement']['observation_until']), 'effectiveness', jso"
        "nb_build_object('text', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['capa']['effectiveness']['text'], 'result', shared_enterprise_quality_is"
        "sue_versions.issue_snapshot['capa']['effectiveness']['result'], 'actor_id', "
        "shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectivene"
        "ss']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['capa']['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_"
        "agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_capa.value"
        "['artifact_id'], 'version', enterprise_reads_capa.value['expected_revision']"
        ") ORDER BY enterprise_reads_capa.value ->> 'artifact_id', enterprise_reads_c"
        "apa.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFRO"
        'M jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sou'
        "rce_read_set) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_quality_is"
        "sue_versions.visibility != 'category' OR coalesce(shared_enterprise_projects"
        ".visibility != 'category', false) OR coalesce(shared_enterprise_products.vis"
        "ibility != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_quality_issue_versions.required_source_read_set) AS ent'
        'erprise_reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ff'
        'c06d18 ON enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = sh'
        'ared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritativ'
        'e_artifacts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value -'
        ">> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398ef"
        'f2ffc06d18.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_element'
        's(shared_enterprise_quality_issue_versions.required_source_read_set) AS ente'
        'rprise_reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ffc'
        '06d18 ON enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = sha'
        'red_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritative'
        '_artifacts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value ->'
        "> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398eff"
        '2ffc06d18.customer_original) AS customer_original, shared_enterprise_quality'
        '_current_issues.issue_version_id = shared_enterprise_quality_issue_versions.'
        'id AS is_current, shared_enterprise_quality_issue_versions.created_at AS cre'
        'ated_at, CAST(NULL AS UUID) AS original_id, CAST((shared_enterprise_quality_'
        "issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID) AS object_id, (SELE"
        'CT coalesce(array_agg(enterprise_authoritative_artifacts_b398eff2ffc06d18.or'
        'iginal_id), ARRAY[]::UUID[]) AS coalesce_4 \nFROM jsonb_array_elements(share'
        'd_enterprise_quality_issue_versions.required_source_read_set) AS enterprise_'
        'reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ffc06d18 O'
        'N enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = shared_ent'
        'erprise_quality_issue_versions.tenant_id AND enterprise_authoritative_artifa'
        "cts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value ->> 'arti"
        "fact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398eff2ffc06d"
        '18.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nF'
        'ROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_s'
        'ource_read_set) AS enterprise_reads_capa(value) JOIN enterprise_authoritativ'
        'e_artifacts_b398eff2ffc06d18 ON enterprise_authoritative_artifacts_b398eff2f'
        'fc06d18.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND e'
        'nterprise_authoritative_artifacts_b398eff2ffc06d18.source_id = CAST((enterpr'
        "ise_reads_capa.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorit"
        'ative_artifacts_b398eff2ffc06d18.source_revision != CAST((enterprise_reads_c'
        "apa.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE '"
        "current' END AS read_basis_status \nFROM shared_enterprise_quality_issue_ver"
        'sions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_i'
        'd = shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise'
        '_projects.product_id = shared_enterprise_quality_issue_versions.product_id A'
        'ND shared_enterprise_projects.id = shared_enterprise_quality_issue_versions.'
        'project_id AND shared_enterprise_projects.category_id = shared_enterprise_qu'
        'ality_issue_versions.category_id JOIN shared_enterprise_products ON shared_e'
        'nterprise_products.tenant_id = shared_enterprise_quality_issue_versions.tena'
        'nt_id AND shared_enterprise_products.id = shared_enterprise_quality_issue_ve'
        'rsions.product_id AND shared_enterprise_products.category_id = shared_enterp'
        'rise_quality_issue_versions.category_id JOIN shared_enterprise_quality_curre'
        'nt_issues ON shared_enterprise_quality_current_issues.tenant_id = shared_ent'
        'erprise_quality_issue_versions.tenant_id AND shared_enterprise_quality_curre'
        'nt_issues.product_id = shared_enterprise_quality_issue_versions.product_id A'
        'ND shared_enterprise_quality_current_issues.project_id = shared_enterprise_q'
        'uality_issue_versions.project_id AND shared_enterprise_quality_current_issue'
        's.issue_id = shared_enterprise_quality_issue_versions.issue_id \nWHERE share'
        'd_enterprise_quality_issue_versions.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb"
        '_array_elements(shared_enterprise_quality_issue_versions.required_source_rea'
        'd_set) AS enterprise_reads_capa(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM '
        'enterprise_authoritative_artifacts_b398eff2ffc06d18 \nWHERE enterprise_autho'
        'ritative_artifacts_b398eff2ffc06d18.tenant_id = shared_enterprise_quality_is'
        'sue_versions.tenant_id AND enterprise_authoritative_artifacts_b398eff2ffc06d'
        "18.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id') AS UUID)"
        ")))) AND ((shared_enterprise_quality_issue_versions.issue_snapshot['capa']) "
        "->> 'id') IS NOT NULL)\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterp"
        'rise_sources_b398eff2ffc06d18 \nWHERE authoritative_enterprise_sources_b398e'
        'ff2ffc06d18.tenant_id = t AND authoritative_enterprise_sources_b398eff2ffc06'
        'd18.category_id = c AND CAST(authoritative_enterprise_sources_b398eff2ffc06d'
        "18.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterp"
        "rise_sources_b398eff2ffc06d18.source_revision AS TEXT) = expected->>'source_"
        "revision' AND authoritative_enterprise_sources_b398eff2ffc06d18.content_hash"
        " = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'change' THEN\n"
        "  WITH enterprise_authoritative_artifacts_12ea12eace7d655f AS \n(SELECT 'art"
        "ifact' AS source_type, artifact_versions.id AS source_id, artifact_versions."
        'tenant_id AS tenant_id, artifact_versions.category_id AS category_id, artifa'
        'ct_versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, artif'
        'act_versions.revision AS source_revision, artifact_versions.title AS title, '
        'artifact_versions.content_hash AS content_hash, artifact_versions.content AS'
        " body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_ve"
        "rsions.visibility != 'category' OR coalesce(products.visibility != 'category"
        "', false) OR coalesce(uploaded_originals.visibility != 'category', false) AS"
        ' private, artifact_versions.original_id IS NOT NULL AS customer_original, tr'
        'ue AS is_current, artifact_versions.created_at AS created_at, artifact_versi'
        'ons.original_id AS original_id, artifact_versions.id AS object_id, CASE WHEN'
        ' (artifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.or'
        "iginal_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis"
        '_status \nFROM artifact_versions LEFT OUTER JOIN products ON products.tenant'
        '_id = artifact_versions.tenant_id AND products.id = artifact_versions.produc'
        't_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = ar'
        'tifact_versions.tenant_id AND uploaded_originals.id = artifact_versions.orig'
        'inal_id AND uploaded_originals.category_id = artifact_versions.category_id A'
        'ND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.prod'
        'uct_id LEFT OUTER JOIN original_security ON original_security.tenant_id = up'
        'loaded_originals.tenant_id AND original_security.original_id = uploaded_orig'
        "inals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_setting('"
        "pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status = 'active'"
        ' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.produc'
        't_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id '
        'IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status ='
        " 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_security"
        ".source_state = 'active' AND original_security.disposition = 'active' AND or"
        'iginal_security.current_request_id IS NOT NULL)), \nshared_enterprise_change'
        '_request_versions AS MATERIALIZED \n(SELECT change_request_versions.product_'
        'id AS product_id, change_request_versions.project_id AS project_id, change_r'
        'equest_versions.change_id AS change_id, change_request_versions.revision AS '
        'revision, change_request_versions.previous_version_id AS previous_version_id'
        ', change_request_versions.previous_revision AS previous_revision, change_req'
        'uest_versions.owner_id AS owner_id, change_request_versions.visibility AS vi'
        'sibility, change_request_versions.status AS status, change_request_versions.'
        'operation AS operation, change_request_versions.intent_digest AS intent_dige'
        'st, change_request_versions.request_snapshot AS request_snapshot, change_req'
        'uest_versions.request_sha256 AS request_sha256, change_request_versions.sour'
        'ces AS sources, change_request_versions.required_source_read_set AS required'
        '_source_read_set, change_request_versions.source_basis AS source_basis, chan'
        'ge_request_versions.authority_snapshot AS authority_snapshot, change_request'
        '_versions.id AS id, change_request_versions.tenant_id AS tenant_id, change_r'
        'equest_versions.created_at AS created_at, change_request_versions.category_i'
        'd AS category_id \nFROM change_request_versions \nWHERE change_request_versi'
        "ons.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS "
        'UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT projects.prod'
        'uct_id AS product_id, projects.owner_id AS owner_id, projects.name AS name, '
        'projects.purpose AS purpose, projects.scope AS scope, projects.visibility AS'
        ' visibility, projects.status AS status, projects.revision AS revision, proje'
        'cts.current_plan_id AS current_plan_id, projects.trigger_type AS trigger_typ'
        'e, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0_decision'
        '_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.created_at'
        ' AS created_at, projects.category_id AS category_id \nFROM projects \nWHERE '
        "projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), ''"
        ') AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT products'
        '.name AS name, products.purpose AS purpose, products.revision AS revision, p'
        'roducts.lifecycle_epoch AS lifecycle_epoch, products.status AS status, produ'
        'cts.owner_id AS owner_id, products.parent_product_id AS parent_product_id, p'
        'roducts.category_id AS category_id, products.visibility AS visibility, produ'
        'cts.target_price AS target_price, products.target_price_currency AS target_p'
        'rice_currency, products.target_price_basis AS target_price_basis, products.t'
        'arget_price_includes_tax AS target_price_includes_tax, products.target_price'
        '_as_of AS target_price_as_of, products.id AS id, products.tenant_id AS tenan'
        't_id, products.created_at AS created_at \nFROM products \nWHERE products.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)),"
        ' \nshared_enterprise_change_request_currents AS MATERIALIZED \n(SELECT chang'
        'e_request_currents.product_id AS product_id, change_request_currents.change_'
        'id AS change_id, change_request_currents.version_id AS version_id, change_re'
        'quest_currents.revision AS revision, change_request_currents.id AS id, chang'
        'e_request_currents.tenant_id AS tenant_id, change_request_currents.created_a'
        't AS created_at, change_request_currents.category_id AS category_id \nFROM c'
        'hange_request_currents \nWHERE change_request_currents.tenant_id = CAST(null'
        "if(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritative_e"
        "nterprise_sources_12ea12eace7d655f AS \n(SELECT 'change' AS source_type, sha"
        'red_enterprise_change_request_versions.id AS source_id, shared_enterprise_ch'
        'ange_request_versions.tenant_id AS tenant_id, shared_enterprise_change_reque'
        'st_versions.category_id AS category_id, shared_enterprise_change_request_ver'
        'sions.product_id AS product_id, shared_enterprise_change_request_versions.pr'
        'oject_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise'
        '_change_request_versions.owner_id AS owner_id, shared_enterprise_change_requ'
        'est_versions.revision AS source_revision, shared_enterprise_change_request_v'
        "ersions.request_snapshot ->> 'title' AS title, encode(sha256(convert_to(CAST"
        "(CAST(jsonb_build_object('object_id', shared_enterprise_change_request_versi"
        "ons.change_id, 'kind', 'change', 'facts', jsonb_build_object('id', shared_en"
        "terprise_change_request_versions.request_snapshot['id'], 'title', shared_ent"
        "erprise_change_request_versions.request_snapshot['title'], 'reason', shared_"
        "enterprise_change_request_versions.request_snapshot['reason'], 'status', sha"
        "red_enterprise_change_request_versions.request_snapshot['status'], 'needs_re"
        "check', shared_enterprise_change_request_versions.request_snapshot['needs_re"
        "check'], 'recheck_reasons', shared_enterprise_change_request_versions.reques"
        "t_snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coale"
        "sce(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'],"
        " 'plan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterpris"
        "e_change_items.value['id'], 'discipline', enterprise_change_items.value['dis"
        "cipline'], 'verification_requirement', enterprise_change_items.value['verifi"
        "cation_requirement'], 'intent_kind', enterprise_change_items.value['intent']"
        "['kind']) ORDER BY enterprise_change_items.ordinal), jsonb_build_array()) AS"
        ' coalesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.va'
        "lue['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_ch"
        "ange_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('actor_id', enterprise_change_approvals.value['actor_id'], 'at',"
        " enterprise_change_approvals.value['at'], 'discipline', enterprise_change_ap"
        "provals.value['discipline'], 'text', enterprise_change_approvals.value['text"
        "']) ORDER BY enterprise_change_approvals.ordinal), jsonb_build_array()) AS c"
        'oalesce_3 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.valu'
        "e['approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_a"
        "pprovals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('item_id', enterprise_change_implementations.value['item_id'"
        "], 'executor_id', enterprise_change_implementations.value['executor_id'], 'o"
        "utcome', enterprise_change_implementations.value['outcome'], 'occurred_at', "
        "enterprise_change_implementations.value['occurred_at'], 'received_at', enter"
        "prise_change_implementations.value['received_at'], 'note', enterprise_change"
        "_implementations.value['note']) ORDER BY enterprise_change_implementations.o"
        'rdinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coal'
        "esce(enterprise_change_orders.value['implementations'], CAST('[]' AS JSONB))"
        ") WITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), 'ef"
        "fectivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterpr"
        "ise_change_effectivity.value['item_id'], 'stage', enterprise_change_effectiv"
        "ity.value['stage'], 'outcome', enterprise_change_effectivity.value['outcome'"
        "], 'covered_units', enterprise_change_effectivity.value['covered_units'], 'o"
        "ccurred_at', enterprise_change_effectivity.value['occurred_at'], 'received_a"
        "t', enterprise_change_effectivity.value['received_at']) ORDER BY enterprise_"
        'change_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 \nFROM jsonb'
        "_array_elements(coalesce(enterprise_change_orders.value['effectivity'], CAST"
        "('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, or"
        "dinal)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('act"
        "or_id', enterprise_change_verifications.value['actor_id'], 'at', enterprise_"
        "change_verifications.value['at'], 'text', enterprise_change_verifications.va"
        "lue['text'], 'result', enterprise_change_verifications.value['fact']['result"
        "'], 'applicable_as_recorded', enterprise_change_verifications.value['fact']["
        "'applicable']) ORDER BY enterprise_change_verifications.ordinal), jsonb_buil"
        'd_array()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterprise_cha'
        "nge_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY AS "
        "enterprise_change_verifications(value, ordinal)), 'closure', jsonb_build_obj"
        "ect('text', enterprise_change_orders.value['closure']['text'], 'actor_id', e"
        "nterprise_change_orders.value['closure']['actor_id'], 'at', enterprise_chang"
        "e_orders.value['closure']['at'])) ORDER BY enterprise_change_orders.ordinal)"
        ', jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_ente'
        "rprise_change_request_versions.request_snapshot['orders']) WITH ORDINALITY A"
        "S enterprise_change_orders(value, ordinal))), 'source_refs', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_ch"
        "ange.value['artifact_id'], 'version', enterprise_reads_change.value['expecte"
        "d_revision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', ente"
        "rprise_reads_change.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_7 \nFROM jsonb_array_elements(shared_enterprise_change_request_vers'
        "ions.required_source_read_set) AS enterprise_reads_change(value)), 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CA"
        "ST(jsonb_build_object('object_id', shared_enterprise_change_request_versions"
        ".change_id, 'kind', 'change', 'facts', jsonb_build_object('id', shared_enter"
        "prise_change_request_versions.request_snapshot['id'], 'title', shared_enterp"
        "rise_change_request_versions.request_snapshot['title'], 'reason', shared_ent"
        "erprise_change_request_versions.request_snapshot['reason'], 'status', shared"
        "_enterprise_change_request_versions.request_snapshot['status'], 'needs_reche"
        "ck', shared_enterprise_change_request_versions.request_snapshot['needs_reche"
        "ck'], 'recheck_reasons', shared_enterprise_change_request_versions.request_s"
        "napshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coalesce"
        "(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'], 'p"
        "lan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_c"
        "hange_items.value['id'], 'discipline', enterprise_change_items.value['discip"
        "line'], 'verification_requirement', enterprise_change_items.value['verificat"
        "ion_requirement'], 'intent_kind', enterprise_change_items.value['intent']['k"
        "ind']) ORDER BY enterprise_change_items.ordinal), jsonb_build_array()) AS co"
        'alesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value'
        "['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_chang"
        "e_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('actor_id', enterprise_change_approvals.value['actor_id'], 'at', en"
        "terprise_change_approvals.value['at'], 'discipline', enterprise_change_appro"
        "vals.value['discipline'], 'text', enterprise_change_approvals.value['text'])"
        ' ORDER BY enterprise_change_approvals.ordinal), jsonb_build_array()) AS coal'
        "esce_3 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['"
        "approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_appr"
        "ovals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('item_id', enterprise_change_implementations.value['item_id'], "
        "'executor_id', enterprise_change_implementations.value['executor_id'], 'outc"
        "ome', enterprise_change_implementations.value['outcome'], 'occurred_at', ent"
        "erprise_change_implementations.value['occurred_at'], 'received_at', enterpri"
        "se_change_implementations.value['received_at'], 'note', enterprise_change_im"
        "plementations.value['note']) ORDER BY enterprise_change_implementations.ordi"
        'nal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesc'
        "e(enterprise_change_orders.value['implementations'], CAST('[]' AS JSONB))) W"
        "ITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), 'effec"
        "tivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterprise"
        "_change_effectivity.value['item_id'], 'stage', enterprise_change_effectivity"
        ".value['stage'], 'outcome', enterprise_change_effectivity.value['outcome'], "
        "'covered_units', enterprise_change_effectivity.value['covered_units'], 'occu"
        "rred_at', enterprise_change_effectivity.value['occurred_at'], 'received_at',"
        " enterprise_change_effectivity.value['received_at']) ORDER BY enterprise_cha"
        'nge_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_ar'
        "ray_elements(coalesce(enterprise_change_orders.value['effectivity'], CAST('["
        "]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, ordin"
        "al)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_"
        "id', enterprise_change_verifications.value['actor_id'], 'at', enterprise_cha"
        "nge_verifications.value['at'], 'text', enterprise_change_verifications.value"
        "['text'], 'result', enterprise_change_verifications.value['fact']['result'],"
        " 'applicable_as_recorded', enterprise_change_verifications.value['fact']['ap"
        "plicable']) ORDER BY enterprise_change_verifications.ordinal), jsonb_build_a"
        'rray()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterprise_change'
        "_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY AS ent"
        "erprise_change_verifications(value, ordinal)), 'closure', jsonb_build_object"
        "('text', enterprise_change_orders.value['closure']['text'], 'actor_id', ente"
        "rprise_change_orders.value['closure']['actor_id'], 'at', enterprise_change_o"
        "rders.value['closure']['at'])) ORDER BY enterprise_change_orders.ordinal), j"
        'sonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterpr'
        "ise_change_request_versions.request_snapshot['orders']) WITH ORDINALITY AS e"
        "nterprise_change_orders(value, ordinal))), 'source_refs', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_chang"
        "e.value['artifact_id'], 'version', enterprise_reads_change.value['expected_r"
        "evision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', enterpr"
        "ise_reads_change.value ->> 'expected_revision'), jsonb_build_array()) AS coa"
        'lesce_7 \nFROM jsonb_array_elements(shared_enterprise_change_request_version'
        "s.required_source_read_set) AS enterprise_reads_change(value)), 'record_poli"
        "cy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_change_request_versions.change_id, 'kind', 'change', '"
        "facts', jsonb_build_object('id', shared_enterprise_change_request_versions.r"
        "equest_snapshot['id'], 'title', shared_enterprise_change_request_versions.re"
        "quest_snapshot['title'], 'reason', shared_enterprise_change_request_versions"
        ".request_snapshot['reason'], 'status', shared_enterprise_change_request_vers"
        "ions.request_snapshot['status'], 'needs_recheck', shared_enterprise_change_r"
        "equest_versions.request_snapshot['needs_recheck'], 'recheck_reasons', shared"
        "_enterprise_change_request_versions.request_snapshot['recheck_reasons']) || "
        "jsonb_build_object('orders', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "id', enterprise_change_orders.value['id'], 'plan_items', (SELECT coalesce(js"
        "onb_agg(jsonb_build_object('id', enterprise_change_items.value['id'], 'disci"
        "pline', enterprise_change_items.value['discipline'], 'verification_requireme"
        "nt', enterprise_change_items.value['verification_requirement'], 'intent_kind"
        "', enterprise_change_items.value['intent']['kind']) ORDER BY enterprise_chan"
        'ge_items.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_ele'
        "ments(coalesce(enterprise_change_orders.value['plan']['items'], CAST('[]' AS"
        " JSONB))) WITH ORDINALITY AS enterprise_change_items(value, ordinal)), 'appr"
        "ovals', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise"
        "_change_approvals.value['actor_id'], 'at', enterprise_change_approvals.value"
        "['at'], 'discipline', enterprise_change_approvals.value['discipline'], 'text"
        "', enterprise_change_approvals.value['text']) ORDER BY enterprise_change_app"
        'rovals.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_eleme'
        "nts(coalesce(enterprise_change_orders.value['approvals'], CAST('[]' AS JSONB"
        "))) WITH ORDINALITY AS enterprise_change_approvals(value, ordinal)), 'implem"
        "entations', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterpr"
        "ise_change_implementations.value['item_id'], 'executor_id', enterprise_chang"
        "e_implementations.value['executor_id'], 'outcome', enterprise_change_impleme"
        "ntations.value['outcome'], 'occurred_at', enterprise_change_implementations."
        "value['occurred_at'], 'received_at', enterprise_change_implementations.value"
        "['received_at'], 'note', enterprise_change_implementations.value['note']) OR"
        'DER BY enterprise_change_implementations.ordinal), jsonb_build_array()) AS c'
        'oalesce_4 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.valu'
        "e['implementations'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_ch"
        "ange_implementations(value, ordinal)), 'effectivity', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('item_id', enterprise_change_effectivity.value['item"
        "_id'], 'stage', enterprise_change_effectivity.value['stage'], 'outcome', ent"
        "erprise_change_effectivity.value['outcome'], 'covered_units', enterprise_cha"
        "nge_effectivity.value['covered_units'], 'occurred_at', enterprise_change_eff"
        "ectivity.value['occurred_at'], 'received_at', enterprise_change_effectivity."
        "value['received_at']) ORDER BY enterprise_change_effectivity.ordinal), jsonb"
        '_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(coalesce(enterpris'
        "e_change_orders.value['effectivity'], CAST('[]' AS JSONB))) WITH ORDINALITY "
        "AS enterprise_change_effectivity(value, ordinal)), 'verifications', (SELECT "
        "coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise_change_verifica"
        "tions.value['actor_id'], 'at', enterprise_change_verifications.value['at'], "
        "'text', enterprise_change_verifications.value['text'], 'result', enterprise_"
        "change_verifications.value['fact']['result'], 'applicable_as_recorded', ente"
        "rprise_change_verifications.value['fact']['applicable']) ORDER BY enterprise"
        '_change_verifications.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM js'
        "onb_array_elements(coalesce(enterprise_change_orders.value['verifications'],"
        " CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_verifications(va"
        "lue, ordinal)), 'closure', jsonb_build_object('text', enterprise_change_orde"
        "rs.value['closure']['text'], 'actor_id', enterprise_change_orders.value['clo"
        "sure']['actor_id'], 'at', enterprise_change_orders.value['closure']['at'])) "
        'ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesce'
        '_1 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.req'
        "uest_snapshot['orders']) WITH ORDINALITY AS enterprise_change_orders(value, "
        "ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('ty"
        "pe', 'artifact', 'id', enterprise_reads_change.value['artifact_id'], 'versio"
        "n', enterprise_reads_change.value['expected_revision']) ORDER BY enterprise_"
        "reads_change.value ->> 'artifact_id', enterprise_reads_change.value ->> 'exp"
        "ected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_elem"
        'ents(shared_enterprise_change_request_versions.required_source_read_set) AS '
        "enterprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS struct"
        "ured, 'structured' AS nature, shared_enterprise_change_request_versions.visi"
        "bility != 'category' OR coalesce(shared_enterprise_projects.visibility != 'c"
        "ategory', false) OR coalesce(shared_enterprise_products.visibility != 'categ"
        "ory', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr"
        'ise_change_request_versions.required_source_read_set) AS enterprise_reads_ch'
        'ange(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON ente'
        'rprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_enterpris'
        'e_change_request_versions.tenant_id AND enterprise_authoritative_artifacts_1'
        "2ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'artifac"
        "t_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f."
        'private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_en'
        'terprise_change_request_versions.required_source_read_set) AS enterprise_rea'
        'ds_change(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON'
        ' enterprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_ente'
        'rprise_change_request_versions.tenant_id AND enterprise_authoritative_artifa'
        "cts_12ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d"
        '655f.customer_original) AS customer_original, shared_enterprise_change_reque'
        'st_currents.version_id = shared_enterprise_change_request_versions.id AS is_'
        'current, shared_enterprise_change_request_versions.created_at AS created_at,'
        ' CAST(NULL AS UUID) AS original_id, shared_enterprise_change_request_version'
        's.change_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritativ'
        'e_artifacts_12ea12eace7d655f.original_id), ARRAY[]::UUID[]) AS coalesce_8 \n'
        'FROM jsonb_array_elements(shared_enterprise_change_request_versions.required'
        '_source_read_set) AS enterprise_reads_change(value) JOIN enterprise_authorit'
        'ative_artifacts_12ea12eace7d655f ON enterprise_authoritative_artifacts_12ea1'
        '2eace7d655f.tenant_id = shared_enterprise_change_request_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_12ea12eace7d655f.source_id = CAST((en'
        "terprise_reads_change.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_a"
        'uthoritative_artifacts_12ea12eace7d655f.original_id IS NOT NULL) AS original'
        '_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr'
        'ise_change_request_versions.required_source_read_set) AS enterprise_reads_ch'
        'ange(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON ente'
        'rprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_enterpris'
        'e_change_request_versions.tenant_id AND enterprise_authoritative_artifacts_1'
        "2ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'artifac"
        "t_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f."
        "source_revision != CAST((enterprise_reads_change.value ->> 'expected_revisio"
        "n') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_stat"
        'us \nFROM shared_enterprise_change_request_versions JOIN shared_enterprise_p'
        'rojects ON shared_enterprise_projects.tenant_id = shared_enterprise_change_r'
        'equest_versions.tenant_id AND shared_enterprise_projects.product_id = shared'
        '_enterprise_change_request_versions.product_id AND shared_enterprise_project'
        's.id = shared_enterprise_change_request_versions.project_id AND shared_enter'
        'prise_projects.category_id = shared_enterprise_change_request_versions.categ'
        'ory_id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_'
        'id = shared_enterprise_change_request_versions.tenant_id AND shared_enterpri'
        'se_products.id = shared_enterprise_change_request_versions.product_id AND sh'
        'ared_enterprise_products.category_id = shared_enterprise_change_request_vers'
        'ions.category_id JOIN shared_enterprise_change_request_currents ON shared_en'
        'terprise_change_request_currents.tenant_id = shared_enterprise_change_reques'
        't_versions.tenant_id AND shared_enterprise_change_request_currents.product_i'
        'd = shared_enterprise_change_request_versions.product_id AND shared_enterpri'
        'se_change_request_currents.change_id = shared_enterprise_change_request_vers'
        'ions.change_id \nWHERE shared_enterprise_change_request_versions.tenant_id ='
        " CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT ("
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_change_reques'
        't_versions.required_source_read_set) AS enterprise_reads_change(value) \nWHE'
        'RE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_12ea12eac'
        'e7d655f \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f.tenant_i'
        'd = shared_enterprise_change_request_versions.tenant_id AND enterprise_autho'
        'ritative_artifacts_12ea12eace7d655f.source_id = CAST((enterprise_reads_chang'
        "e.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM au"
        'thoritative_enterprise_sources_12ea12eace7d655f \nWHERE authoritative_enterp'
        'rise_sources_12ea12eace7d655f.tenant_id = t AND authoritative_enterprise_sou'
        'rces_12ea12eace7d655f.category_id = c AND CAST(authoritative_enterprise_sour'
        "ces_12ea12eace7d655f.source_id AS TEXT) = expected->>'source_id' AND CAST(au"
        'thoritative_enterprise_sources_12ea12eace7d655f.source_revision AS TEXT) = e'
        "xpected->>'source_revision' AND authoritative_enterprise_sources_12ea12eace7"
        "d655f.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WH"
        "EN 'external_wait' THEN\n  WITH enterprise_authoritative_artifacts_b3e531ff7"
        "3e706c8 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sour"
        'ce_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category_'
        'id AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS '
        'UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.ow'
        'ner_id AS owner_id, artifact_versions.revision AS source_revision, artifact_'
        'versions.title AS title, artifact_versions.content_hash AS content_hash, art'
        "ifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untruste"
        "d' AS nature, artifact_versions.visibility != 'category' OR coalesce(product"
        "s.visibility != 'category', false) OR coalesce(uploaded_originals.visibility"
        " != 'category', false) AS private, artifact_versions.original_id IS NOT NULL"
        ' AS customer_original, true AS is_current, artifact_versions.created_at AS c'
        'reated_at, artifact_versions.original_id AS original_id, artifact_versions.i'
        'd AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN A'
        'RRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids'
        ", 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN pr"
        'oducts ON products.tenant_id = artifact_versions.tenant_id AND products.id ='
        ' artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded'
        '_originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id'
        ' = artifact_versions.original_id AND uploaded_originals.category_id = artifa'
        'ct_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT FR'
        'OM artifact_versions.product_id LEFT OUTER JOIN original_security ON origina'
        'l_security.tenant_id = uploaded_originals.tenant_id AND original_security.or'
        'iginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_v"
        "ersions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND "
        '(artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artif'
        'act_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND up'
        "loaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'cle"
        "an' AND original_security.source_state = 'active' AND original_security.disp"
        "osition = 'active' AND original_security.current_request_id IS NOT NULL)), "
        '\nshared_enterprise_external_wait_versions AS MATERIALIZED \n(SELECT externa'
        'l_wait_versions.wait_id AS wait_id, external_wait_versions.previous_id AS pr'
        'evious_id, external_wait_versions.previous_revision AS previous_revision, ex'
        'ternal_wait_versions.action AS action, external_wait_versions.state AS state'
        ', external_wait_versions.revision AS revision, external_wait_versions.writer'
        '_id AS writer_id, external_wait_versions.actor_id AS actor_id, external_wait'
        '_versions.requester_id AS requester_id, external_wait_versions.operation AS '
        'operation, external_wait_versions.command_id AS command_id, external_wait_ve'
        'rsions.command AS command, external_wait_versions.sources AS sources, extern'
        'al_wait_versions.reads AS reads, external_wait_versions.source_basis AS sour'
        'ce_basis, external_wait_versions.body AS body, external_wait_versions.body_s'
        'ha256 AS body_sha256, external_wait_versions.intent_digest AS intent_digest,'
        ' external_wait_versions.request_digest AS request_digest, external_wait_vers'
        'ions.receipt_id AS receipt_id, external_wait_versions.confirmation_id AS con'
        'firmation_id, external_wait_versions.product_id AS product_id, external_wait'
        '_versions.project_id AS project_id, external_wait_versions.owner_id AS owner'
        '_id, external_wait_versions.visibility AS visibility, external_wait_versions'
        '.id AS id, external_wait_versions.tenant_id AS tenant_id, external_wait_vers'
        'ions.created_at AS created_at, external_wait_versions.category_id AS categor'
        'y_id \nFROM external_wait_versions \nWHERE external_wait_versions.tenant_id '
        "= CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshar"
        'ed_enterprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS prod'
        'uct_id, projects.owner_id AS owner_id, projects.name AS name, projects.purpo'
        'se AS purpose, projects.scope AS scope, projects.visibility AS visibility, p'
        'rojects.status AS status, projects.revision AS revision, projects.current_pl'
        'an_id AS current_plan_id, projects.trigger_type AS trigger_type, projects.tr'
        'igger_id AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.'
        'id AS id, projects.tenant_id AS tenant_id, projects.created_at AS created_at'
        ', projects.category_id AS category_id \nFROM projects \nWHERE projects.tenan'
        "t_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), "
        '\nshared_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name'
        ', products.purpose AS purpose, products.revision AS revision, products.lifec'
        'ycle_epoch AS lifecycle_epoch, products.status AS status, products.owner_id '
        'AS owner_id, products.parent_product_id AS parent_product_id, products.categ'
        'ory_id AS category_id, products.visibility AS visibility, products.target_pr'
        'ice AS target_price, products.target_price_currency AS target_price_currency'
        ', products.target_price_basis AS target_price_basis, products.target_price_i'
        'ncludes_tax AS target_price_includes_tax, products.target_price_as_of AS tar'
        'get_price_as_of, products.id AS id, products.tenant_id AS tenant_id, product'
        's.created_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_external_wait_currents AS MATERIALIZED \n(SELECT external_wait_curre'
        'nts.wait_id AS wait_id, external_wait_currents.version_id AS version_id, ext'
        'ernal_wait_currents.revision AS revision, external_wait_currents.state AS st'
        'ate, external_wait_currents.product_id AS product_id, external_wait_currents'
        '.project_id AS project_id, external_wait_currents.owner_id AS owner_id, exte'
        'rnal_wait_currents.visibility AS visibility, external_wait_currents.id AS id'
        ', external_wait_currents.tenant_id AS tenant_id, external_wait_currents.crea'
        'ted_at AS created_at, external_wait_currents.category_id AS category_id \nFR'
        'OM external_wait_currents \nWHERE external_wait_currents.tenant_id = CAST(nu'
        "llif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritative"
        "_enterprise_sources_b3e531ff73e706c8 AS \n(SELECT 'external_wait' AS source_"
        'type, shared_enterprise_external_wait_versions.id AS source_id, shared_enter'
        'prise_external_wait_versions.tenant_id AS tenant_id, shared_enterprise_exter'
        'nal_wait_versions.category_id AS category_id, shared_enterprise_external_wai'
        't_versions.product_id AS product_id, shared_enterprise_external_wait_version'
        's.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterp'
        'rise_external_wait_versions.owner_id AS owner_id, shared_enterprise_external'
        '_wait_versions.revision AS source_revision, shared_enterprise_external_wait_'
        "versions.body ->> 'title' AS title, encode(sha256(convert_to(CAST(CAST(jsonb"
        "_build_object('object_id', shared_enterprise_external_wait_versions.wait_id,"
        " 'kind', 'external_wait', 'facts', jsonb_build_object('wait', jsonb_build_ob"
        "ject('wait_id', shared_enterprise_external_wait_versions.body['wait_id'], 'r"
        "evision', shared_enterprise_external_wait_versions.body['revision'], 'state'"
        ", shared_enterprise_external_wait_versions.body['state'], 'responsible_id', "
        "shared_enterprise_external_wait_versions.body['responsible_id'], 'title', sh"
        "ared_enterprise_external_wait_versions.body['title'], 'target', shared_enter"
        "prise_external_wait_versions.body['target'], 'request_content', shared_enter"
        "prise_external_wait_versions.body['request_content'], 'closure_condition', s"
        "hared_enterprise_external_wait_versions.body['closure_condition'], 'blocking"
        "', shared_enterprise_external_wait_versions.body['blocking'], 'next_check_at"
        "', shared_enterprise_external_wait_versions.body['next_check_at'], 'original"
        "_timezone', shared_enterprise_external_wait_versions.body['original_timezone"
        "']), 'delivery', jsonb_build_object('at', shared_enterprise_external_wait_ve"
        "rsions.body['delivery']['at'], 'status', shared_enterprise_external_wait_ver"
        "sions.body['delivery']['status'], 'time_basis', shared_enterprise_external_w"
        "ait_versions.body['delivery']['time_basis']), 'commitment', jsonb_build_obje"
        "ct('promised_at', shared_enterprise_external_wait_versions.body['counterpart"
        "y_commitment']['promised_at'], 'original_timezone', shared_enterprise_extern"
        "al_wait_versions.body['counterparty_commitment']['original_timezone']), 'rep"
        "ly', jsonb_build_object('at', shared_enterprise_external_wait_versions.body["
        "'reply']['at'], 'status', shared_enterprise_external_wait_versions.body['rep"
        "ly']['status'], 'time_basis', shared_enterprise_external_wait_versions.body["
        "'reply']['time_basis'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_bu"
        "ild_object('type', 'artifact', 'id', enterprise_reads_external_wait.value['a"
        "rtifact_id'], 'version', enterprise_reads_external_wait.value['expected_revi"
        "sion']) ORDER BY enterprise_reads_external_wait.value ->> 'artifact_id', ent"
        "erprise_reads_external_wait.value ->> 'expected_revision'), jsonb_build_arra"
        'y()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_wa'
        "it_versions.reads) AS enterprise_reads_external_wait(value)), 'record_policy"
        "', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jso"
        "nb_build_object('object_id', shared_enterprise_external_wait_versions.wait_i"
        "d, 'kind', 'external_wait', 'facts', jsonb_build_object('wait', jsonb_build_"
        "object('wait_id', shared_enterprise_external_wait_versions.body['wait_id'], "
        "'revision', shared_enterprise_external_wait_versions.body['revision'], 'stat"
        "e', shared_enterprise_external_wait_versions.body['state'], 'responsible_id'"
        ", shared_enterprise_external_wait_versions.body['responsible_id'], 'title', "
        "shared_enterprise_external_wait_versions.body['title'], 'target', shared_ent"
        "erprise_external_wait_versions.body['target'], 'request_content', shared_ent"
        "erprise_external_wait_versions.body['request_content'], 'closure_condition',"
        " shared_enterprise_external_wait_versions.body['closure_condition'], 'blocki"
        "ng', shared_enterprise_external_wait_versions.body['blocking'], 'next_check_"
        "at', shared_enterprise_external_wait_versions.body['next_check_at'], 'origin"
        "al_timezone', shared_enterprise_external_wait_versions.body['original_timezo"
        "ne']), 'delivery', jsonb_build_object('at', shared_enterprise_external_wait_"
        "versions.body['delivery']['at'], 'status', shared_enterprise_external_wait_v"
        "ersions.body['delivery']['status'], 'time_basis', shared_enterprise_external"
        "_wait_versions.body['delivery']['time_basis']), 'commitment', jsonb_build_ob"
        "ject('promised_at', shared_enterprise_external_wait_versions.body['counterpa"
        "rty_commitment']['promised_at'], 'original_timezone', shared_enterprise_exte"
        "rnal_wait_versions.body['counterparty_commitment']['original_timezone']), 'r"
        "eply', jsonb_build_object('at', shared_enterprise_external_wait_versions.bod"
        "y['reply']['at'], 'status', shared_enterprise_external_wait_versions.body['r"
        "eply']['status'], 'time_basis', shared_enterprise_external_wait_versions.bod"
        "y['reply']['time_basis'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('type', 'artifact', 'id', enterprise_reads_external_wait.value["
        "'artifact_id'], 'version', enterprise_reads_external_wait.value['expected_re"
        "vision']) ORDER BY enterprise_reads_external_wait.value ->> 'artifact_id', e"
        "nterprise_reads_external_wait.value ->> 'expected_revision'), jsonb_build_ar"
        'ray()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_'
        "wait_versions.reads) AS enterprise_reads_external_wait(value)), 'record_poli"
        "cy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_external_wait_versions.wait_id, 'kind', 'external_wait"
        "', 'facts', jsonb_build_object('wait', jsonb_build_object('wait_id', shared_"
        "enterprise_external_wait_versions.body['wait_id'], 'revision', shared_enterp"
        "rise_external_wait_versions.body['revision'], 'state', shared_enterprise_ext"
        "ernal_wait_versions.body['state'], 'responsible_id', shared_enterprise_exter"
        "nal_wait_versions.body['responsible_id'], 'title', shared_enterprise_externa"
        "l_wait_versions.body['title'], 'target', shared_enterprise_external_wait_ver"
        "sions.body['target'], 'request_content', shared_enterprise_external_wait_ver"
        "sions.body['request_content'], 'closure_condition', shared_enterprise_extern"
        "al_wait_versions.body['closure_condition'], 'blocking', shared_enterprise_ex"
        "ternal_wait_versions.body['blocking'], 'next_check_at', shared_enterprise_ex"
        "ternal_wait_versions.body['next_check_at'], 'original_timezone', shared_ente"
        "rprise_external_wait_versions.body['original_timezone']), 'delivery', jsonb_"
        "build_object('at', shared_enterprise_external_wait_versions.body['delivery']"
        "['at'], 'status', shared_enterprise_external_wait_versions.body['delivery']["
        "'status'], 'time_basis', shared_enterprise_external_wait_versions.body['deli"
        "very']['time_basis']), 'commitment', jsonb_build_object('promised_at', share"
        "d_enterprise_external_wait_versions.body['counterparty_commitment']['promise"
        "d_at'], 'original_timezone', shared_enterprise_external_wait_versions.body['"
        "counterparty_commitment']['original_timezone']), 'reply', jsonb_build_object"
        "('at', shared_enterprise_external_wait_versions.body['reply']['at'], 'status"
        "', shared_enterprise_external_wait_versions.body['reply']['status'], 'time_b"
        "asis', shared_enterprise_external_wait_versions.body['reply']['time_basis'])"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'art"
        "ifact', 'id', enterprise_reads_external_wait.value['artifact_id'], 'version'"
        ", enterprise_reads_external_wait.value['expected_revision']) ORDER BY enterp"
        "rise_reads_external_wait.value ->> 'artifact_id', enterprise_reads_external_"
        "wait.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFR"
        'OM jsonb_array_elements(shared_enterprise_external_wait_versions.reads) AS e'
        "nterprise_reads_external_wait(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_external_wait_versions"
        ".visibility != 'category' OR coalesce(shared_enterprise_projects.visibility "
        "!= 'category', false) OR coalesce(shared_enterprise_products.visibility != '"
        "category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_en"
        'terprise_external_wait_versions.reads) AS enterprise_reads_external_wait(val'
        'ue) JOIN enterprise_authoritative_artifacts_b3e531ff73e706c8 ON enterprise_a'
        'uthoritative_artifacts_b3e531ff73e706c8.tenant_id = shared_enterprise_extern'
        'al_wait_versions.tenant_id AND enterprise_authoritative_artifacts_b3e531ff73'
        "e706c8.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifact_"
        "id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b3e531ff73e706c8.pr"
        'ivate)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ente'
        'rprise_external_wait_versions.reads) AS enterprise_reads_external_wait(value'
        ') JOIN enterprise_authoritative_artifacts_b3e531ff73e706c8 ON enterprise_aut'
        'horitative_artifacts_b3e531ff73e706c8.tenant_id = shared_enterprise_external'
        '_wait_versions.tenant_id AND enterprise_authoritative_artifacts_b3e531ff73e7'
        "06c8.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifact_id"
        "') AS UUID) \nWHERE enterprise_authoritative_artifacts_b3e531ff73e706c8.cust"
        'omer_original) AS customer_original, shared_enterprise_external_wait_current'
        's.version_id = shared_enterprise_external_wait_versions.id AS is_current, sh'
        'ared_enterprise_external_wait_versions.created_at AS created_at, CAST(NULL A'
        'S UUID) AS original_id, shared_enterprise_external_wait_versions.wait_id AS '
        'object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_b3e'
        '531ff73e706c8.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_arra'
        'y_elements(shared_enterprise_external_wait_versions.reads) AS enterprise_rea'
        'ds_external_wait(value) JOIN enterprise_authoritative_artifacts_b3e531ff73e7'
        '06c8 ON enterprise_authoritative_artifacts_b3e531ff73e706c8.tenant_id = shar'
        'ed_enterprise_external_wait_versions.tenant_id AND enterprise_authoritative_'
        'artifacts_b3e531ff73e706c8.source_id = CAST((enterprise_reads_external_wait.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        '_b3e531ff73e706c8.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXIST'
        'S (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_external_wait_vers'
        'ions.reads) AS enterprise_reads_external_wait(value) JOIN enterprise_authori'
        'tative_artifacts_b3e531ff73e706c8 ON enterprise_authoritative_artifacts_b3e5'
        '31ff73e706c8.tenant_id = shared_enterprise_external_wait_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_b3e531ff73e706c8.source_id = CAST((en'
        "terprise_reads_external_wait.value ->> 'artifact_id') AS UUID) \nWHERE enter"
        'prise_authoritative_artifacts_b3e531ff73e706c8.source_revision != CAST((ente'
        "rprise_reads_external_wait.value ->> 'expected_revision') AS INTEGER))) THEN"
        " 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enter"
        'prise_external_wait_versions JOIN shared_enterprise_projects ON shared_enter'
        'prise_projects.tenant_id = shared_enterprise_external_wait_versions.tenant_i'
        'd AND shared_enterprise_projects.product_id = shared_enterprise_external_wai'
        't_versions.product_id AND shared_enterprise_projects.id = shared_enterprise_'
        'external_wait_versions.project_id AND shared_enterprise_projects.category_id'
        ' = shared_enterprise_external_wait_versions.category_id JOIN shared_enterpri'
        'se_products ON shared_enterprise_products.tenant_id = shared_enterprise_exte'
        'rnal_wait_versions.tenant_id AND shared_enterprise_products.id = shared_ente'
        'rprise_external_wait_versions.product_id AND shared_enterprise_products.cate'
        'gory_id = shared_enterprise_external_wait_versions.category_id JOIN shared_e'
        'nterprise_external_wait_currents ON shared_enterprise_external_wait_currents'
        '.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND shared_e'
        'nterprise_external_wait_currents.product_id = shared_enterprise_external_wai'
        't_versions.product_id AND shared_enterprise_external_wait_currents.wait_id ='
        ' shared_enterprise_external_wait_versions.wait_id \nWHERE shared_enterprise_'
        "external_wait_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_"
        "id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_external_wait_versions.reads) AS enterprise_reads_exter'
        'nal_wait(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritativ'
        'e_artifacts_b3e531ff73e706c8 \nWHERE enterprise_authoritative_artifacts_b3e5'
        '31ff73e706c8.tenant_id = shared_enterprise_external_wait_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_b3e531ff73e706c8.source_id = CAST((en'
        "terprise_reads_external_wait.value ->> 'artifact_id') AS UUID))))))\n SELECT"
        ' EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_b3e531ff73e706c8 '
        '\nWHERE authoritative_enterprise_sources_b3e531ff73e706c8.tenant_id = t AND '
        'authoritative_enterprise_sources_b3e531ff73e706c8.category_id = c AND CAST(a'
        'uthoritative_enterprise_sources_b3e531ff73e706c8.source_id AS TEXT) = expect'
        "ed->>'source_id' AND CAST(authoritative_enterprise_sources_b3e531ff73e706c8."
        "source_revision AS TEXT) = expected->>'source_revision' AND authoritative_en"
        "terprise_sources_b3e531ff73e706c8.content_hash = expected->>'content_hash') "
        "AS anon_1 INTO visible;\n WHEN 'supply' THEN\n  WITH enterprise_authoritativ"
        "e_artifacts_f30dfe1cfb6de6d1 AS \n(SELECT 'artifact' AS source_type, artifac"
        't_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, artifa'
        'ct_versions.category_id AS category_id, artifact_versions.product_id AS prod'
        'uct_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id,'
        ' artifact_versions.owner_id AS owner_id, artifact_versions.revision AS sourc'
        'e_revision, artifact_versions.title AS title, artifact_versions.content_hash'
        ' AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS '
        "structured, 'untrusted' AS nature, artifact_versions.visibility != 'category"
        "' OR coalesce(products.visibility != 'category', false) OR coalesce(uploaded"
        "_originals.visibility != 'category', false) AS private, artifact_versions.or"
        'iginal_id IS NOT NULL AS customer_original, true AS is_current, artifact_ver'
        'sions.created_at AS created_at, artifact_versions.original_id AS original_id'
        ', artifact_versions.id AS object_id, CASE WHEN (artifact_versions.original_i'
        'd IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID['
        "] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_versio"
        'ns LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.tenant'
        '_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN uploaded_'
        'originals ON uploaded_originals.tenant_id = artifact_versions.tenant_id AND '
        'uploaded_originals.id = artifact_versions.original_id AND uploaded_originals'
        '.category_id = artifact_versions.category_id AND uploaded_originals.product_'
        'id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN origina'
        'l_security ON original_security.tenant_id = uploaded_originals.tenant_id AND'
        ' original_security.original_id = uploaded_originals.id \nWHERE artifact_vers'
        "ions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS"
        " UUID) AND artifact_versions.status = 'active' AND artifact_versions.categor"
        'y_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products.id IS'
        ' NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_originals.'
        "id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_origina"
        "ls.scan_status = 'clean' AND original_security.source_state = 'active' AND o"
        "riginal_security.disposition = 'active' AND original_security.current_reques"
        't_id IS NOT NULL)), \nshared_enterprise_supply_snapshots AS MATERIALIZED \n('
        'SELECT supply_snapshots.revision AS revision, supply_snapshots.status AS sta'
        'tus, supply_snapshots.capture_id AS capture_id, supply_snapshots.previous_sn'
        'apshot_id AS previous_snapshot_id, supply_snapshots.previous_revision AS pre'
        'vious_revision, supply_snapshots.snapshot AS snapshot, supply_snapshots.snap'
        'shot_sha256 AS snapshot_sha256, supply_snapshots.bound_demand AS bound_deman'
        'd, supply_snapshots.reconciliation AS reconciliation, supply_snapshots.sourc'
        'es AS sources, supply_snapshots.product_id AS product_id, supply_snapshots.p'
        'roject_id AS project_id, supply_snapshots.build_id AS build_id, supply_snaps'
        'hots.build_revision AS build_revision, supply_snapshots.owner_id AS owner_id'
        ', supply_snapshots.visibility AS visibility, supply_snapshots.reason AS reas'
        'on, supply_snapshots.required_source_read_set AS required_source_read_set, s'
        'upply_snapshots.id AS id, supply_snapshots.tenant_id AS tenant_id, supply_sn'
        'apshots.created_at AS created_at, supply_snapshots.category_id AS category_i'
        'd \nFROM supply_snapshots \nWHERE supply_snapshots.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_p"
        'rojects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, project'
        's.owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, '
        'projects.scope AS scope, projects.visibility AS visibility, projects.status '
        'AS status, projects.revision AS revision, projects.current_plan_id AS curren'
        't_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS tri'
        'gger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, proje'
        'cts.tenant_id AS tenant_id, projects.created_at AS created_at, projects.cate'
        'gory_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpr"
        'ise_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpo'
        'se AS purpose, products.revision AS revision, products.lifecycle_epoch AS li'
        'fecycle_epoch, products.status AS status, products.owner_id AS owner_id, pro'
        'ducts.parent_product_id AS parent_product_id, products.category_id AS catego'
        'ry_id, products.visibility AS visibility, products.target_price AS target_pr'
        'ice, products.target_price_currency AS target_price_currency, products.targe'
        't_price_basis AS target_price_basis, products.target_price_includes_tax AS t'
        'arget_price_includes_tax, products.target_price_as_of AS target_price_as_of,'
        ' products.id AS id, products.tenant_id AS tenant_id, products.created_at AS '
        'created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_builds A"
        'S MATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id '
        'AS project_id, builds.project_revision AS project_revision, builds.engineeri'
        'ng_configuration_id AS engineering_configuration_id, builds.manufacturing_co'
        'nfiguration_id AS manufacturing_configuration_id, builds.previous_build_id A'
        'S previous_build_id, builds.owner_id AS owner_id, builds.name AS name, build'
        's.type AS type, builds.purpose AS purpose, builds.planned_quantity AS planne'
        'd_quantity, builds.unit AS unit, builds.planned_start AS planned_start, buil'
        'ds.planned_end AS planned_end, builds.verification_objectives AS verificatio'
        'n_objectives, builds.disposition_plan AS disposition_plan, builds.visibility'
        ' AS visibility, builds.revision AS revision, builds.status AS status, builds'
        '.id AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, b'
        'uilds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CA'
        "ST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_e"
        'nterprise_supply_current_snapshots AS MATERIALIZED \n(SELECT supply_current_'
        'snapshots.product_id AS product_id, supply_current_snapshots.build_id AS bui'
        'ld_id, supply_current_snapshots.snapshot_id AS snapshot_id, supply_current_s'
        'napshots.snapshot_revision AS snapshot_revision, supply_current_snapshots.id'
        ' AS id, supply_current_snapshots.tenant_id AS tenant_id, supply_current_snap'
        'shots.created_at AS created_at, supply_current_snapshots.category_id AS cate'
        'gory_id \nFROM supply_current_snapshots \nWHERE supply_current_snapshots.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)),"
        " \nauthoritative_enterprise_sources_f30dfe1cfb6de6d1 AS \n(SELECT 'supply' A"
        'S source_type, shared_enterprise_supply_snapshots.id AS source_id, shared_en'
        'terprise_supply_snapshots.tenant_id AS tenant_id, shared_enterprise_supply_s'
        'napshots.category_id AS category_id, shared_enterprise_supply_snapshots.prod'
        'uct_id AS product_id, shared_enterprise_supply_snapshots.project_id AS proje'
        'ct_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_supply_snapshots'
        '.owner_id AS owner_id, shared_enterprise_supply_snapshots.revision AS source'
        "_revision, '\u4f9b\u5e94\u627f\u8bfa \xb7 ' || CAST(shared_enterprise_supply"
        '_snapshots.build_id AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(js'
        "onb_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind',"
        " 'supply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_"
        "snapshots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'co"
        "mmitments', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enter"
        "prise_supply_commitments.value['record_id'], 'supplier_id', enterprise_suppl"
        "y_commitments.value['supplier_id'], 'material_id', enterprise_supply_commitm"
        "ents.value['material_id'], 'quantity', enterprise_supply_commitments.value['"
        "quantity'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_a"
        "t', enterprise_supply_commitments.value['expected_at']) ORDER BY enterprise_"
        'supply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb'
        "_array_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commit"
        "ments'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitme"
        "nts(value, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build"
        "_object('type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id"
        "'], 'version', enterprise_reads_supply.value['expected_revision']) ORDER BY "
        "enterprise_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.val"
        "ue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb"
        '_array_elements(shared_enterprise_supply_snapshots.required_source_read_set)'
        " AS enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_supply_snapshots.id, 'kind', 'supply', 'facts', jso"
        "nb_build_object('build_id', shared_enterprise_supply_snapshots.build_id, 'st"
        "atus', shared_enterprise_supply_snapshots.status, 'commitments', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('record_id', enterprise_supply_commitment"
        "s.value['record_id'], 'supplier_id', enterprise_supply_commitments.value['su"
        "pplier_id'], 'material_id', enterprise_supply_commitments.value['material_id"
        "'], 'quantity', enterprise_supply_commitments.value['quantity'], 'unit', ent"
        "erprise_supply_commitments.value['unit'], 'expected_at', enterprise_supply_c"
        "ommitments.value['expected_at']) ORDER BY enterprise_supply_commitments.ordi"
        'nal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesc'
        "e(shared_enterprise_supply_snapshots.snapshot['commitments'], CAST('[]' AS J"
        'SONB))) WITH ORDINALITY AS enterprise_supply_commitments(value, ordinal))), '
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_supply.value['artifact_id'], 'version', enterpri"
        "se_reads_supply.value['expected_revision']) ORDER BY enterprise_reads_supply"
        ".value ->> 'artifact_id', enterprise_reads_supply.value ->> 'expected_revisi"
        "on'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_"
        'enterprise_supply_snapshots.required_source_read_set) AS enterprise_reads_su'
        "pply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(json"
        "b_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', '"
        "supply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_sn"
        "apshots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'comm"
        "itments', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enterpr"
        "ise_supply_commitments.value['record_id'], 'supplier_id', enterprise_supply_"
        "commitments.value['supplier_id'], 'material_id', enterprise_supply_commitmen"
        "ts.value['material_id'], 'quantity', enterprise_supply_commitments.value['qu"
        "antity'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_at'"
        ", enterprise_supply_commitments.value['expected_at']) ORDER BY enterprise_su"
        'pply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_a'
        "rray_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitme"
        "nts'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitment"
        "s(value, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_o"
        "bject('type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id']"
        ", 'version', enterprise_reads_supply.value['expected_revision']) ORDER BY en"
        "terprise_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.value"
        " ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_a"
        'rray_elements(shared_enterprise_supply_snapshots.required_source_read_set) A'
        "S enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_supply_snapshots.visib"
        "ility != 'category' OR coalesce(shared_enterprise_projects.visibility != 'ca"
        "tegory', false) OR coalesce(shared_enterprise_products.visibility != 'catego"
        "ry', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpri"
        'se_supply_snapshots.required_source_read_set) AS enterprise_reads_supply(val'
        'ue) JOIN enterprise_authoritative_artifacts_f30dfe1cfb6de6d1 ON enterprise_a'
        'uthoritative_artifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_supply'
        '_snapshots.tenant_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de6d1'
        ".source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID)"
        ' \nWHERE enterprise_authoritative_artifacts_f30dfe1cfb6de6d1.private)) OR sh'
        "ared_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1"
        ' \nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_sou'
        'rce_read_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritativ'
        'e_artifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_artifacts_f30dfe1cf'
        'b6de6d1.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND enterpr'
        'ise_authoritative_artifacts_f30dfe1cfb6de6d1.source_id = CAST((enterprise_re'
        "ads_supply.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritativ"
        'e_artifacts_f30dfe1cfb6de6d1.customer_original) AS customer_original, shared'
        '_enterprise_supply_current_snapshots.snapshot_id = shared_enterprise_supply_'
        'snapshots.id AS is_current, shared_enterprise_supply_snapshots.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_supply_sna'
        'pshots.id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_'
        'artifacts_f30dfe1cfb6de6d1.original_id), ARRAY[]::UUID[]) AS coalesce_3 \nFR'
        'OM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_r'
        'ead_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritative_art'
        'ifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_artifacts_f30dfe1cfb6de6'
        'd1.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_a'
        'uthoritative_artifacts_f30dfe1cfb6de6d1.source_id = CAST((enterprise_reads_s'
        "upply.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_art"
        'ifacts_f30dfe1cfb6de6d1.original_id IS NOT NULL) AS original_ids, CASE WHEN '
        '(EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_supply_snaps'
        'hots.required_source_read_set) AS enterprise_reads_supply(value) JOIN enterp'
        'rise_authoritative_artifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_ar'
        'tifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_supply_snapshots.tena'
        'nt_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de6d1.source_id = CA'
        "ST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_f30dfe1cfb6de6d1.source_revision != CAST((enter'
        "prise_reads_supply.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_"
        "recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_su"
        'pply_snapshots JOIN shared_enterprise_projects ON shared_enterprise_projects'
        '.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_enterpr'
        'ise_projects.product_id = shared_enterprise_supply_snapshots.product_id AND '
        'shared_enterprise_projects.id = shared_enterprise_supply_snapshots.project_i'
        'd AND shared_enterprise_projects.category_id = shared_enterprise_supply_snap'
        'shots.category_id JOIN shared_enterprise_products ON shared_enterprise_produ'
        'cts.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_ente'
        'rprise_products.id = shared_enterprise_supply_snapshots.product_id AND share'
        'd_enterprise_products.category_id = shared_enterprise_supply_snapshots.categ'
        'ory_id JOIN shared_enterprise_builds ON shared_enterprise_builds.tenant_id ='
        ' shared_enterprise_supply_snapshots.tenant_id AND shared_enterprise_builds.c'
        'ategory_id = shared_enterprise_supply_snapshots.category_id AND shared_enter'
        'prise_builds.product_id = shared_enterprise_supply_snapshots.product_id AND '
        'shared_enterprise_builds.project_id = shared_enterprise_supply_snapshots.pro'
        'ject_id AND shared_enterprise_builds.id = shared_enterprise_supply_snapshots'
        '.build_id AND shared_enterprise_builds.revision = shared_enterprise_supply_s'
        'napshots.build_revision JOIN shared_enterprise_supply_current_snapshots ON s'
        'hared_enterprise_supply_current_snapshots.tenant_id = shared_enterprise_supp'
        'ly_snapshots.tenant_id AND shared_enterprise_supply_current_snapshots.produc'
        't_id = shared_enterprise_supply_snapshots.product_id AND shared_enterprise_s'
        'upply_current_snapshots.build_id = shared_enterprise_supply_snapshots.build_'
        'id \nWHERE shared_enterprise_supply_snapshots.tenant_id = CAST(nullif(curren'
        "t_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source'
        '_read_set) AS enterprise_reads_supply(value) \nWHERE NOT (EXISTS (SELECT 1 '
        '\nFROM enterprise_authoritative_artifacts_f30dfe1cfb6de6d1 \nWHERE enterpris'
        'e_authoritative_artifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_sup'
        'ply_snapshots.tenant_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de'
        "6d1.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UU"
        'ID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_f'
        '30dfe1cfb6de6d1 \nWHERE authoritative_enterprise_sources_f30dfe1cfb6de6d1.te'
        'nant_id = t AND authoritative_enterprise_sources_f30dfe1cfb6de6d1.category_i'
        'd = c AND CAST(authoritative_enterprise_sources_f30dfe1cfb6de6d1.source_id A'
        "S TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sources_f"
        "30dfe1cfb6de6d1.source_revision AS TEXT) = expected->>'source_revision' AND "
        'authoritative_enterprise_sources_f30dfe1cfb6de6d1.content_hash = expected->>'
        "'content_hash') AS anon_1 INTO visible;\n WHEN 'build' THEN\n  WITH shared_e"
        'nterprise_engineering_configurations AS MATERIALIZED \n(SELECT engineering_c'
        'onfigurations.definition_id AS definition_id, engineering_configurations.def'
        'inition_revision AS definition_revision, engineering_configurations.bom_id A'
        'S bom_id, engineering_configurations.bom_revision AS bom_revision, engineeri'
        'ng_configurations.design_versions AS design_versions, engineering_configurat'
        'ions.series_id AS series_id, engineering_configurations.previous_id AS previ'
        'ous_id, engineering_configurations.expected_previous_revision AS expected_pr'
        'evious_revision, engineering_configurations.reason AS reason, engineering_co'
        'nfigurations.product_id AS product_id, engineering_configurations.owner_id A'
        'S owner_id, engineering_configurations.name AS name, engineering_configurati'
        'ons.status AS status, engineering_configurations.visibility AS visibility, e'
        'ngineering_configurations.revision AS revision, engineering_configurations.s'
        'ources AS sources, engineering_configurations.required_source_read_set AS re'
        'quired_source_read_set, engineering_configurations.id AS id, engineering_con'
        'figurations.tenant_id AS tenant_id, engineering_configurations.created_at AS'
        ' created_at, engineering_configurations.category_id AS category_id \nFROM en'
        'gineering_configurations \nWHERE engineering_configurations.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_process_revisions AS MATERIALIZED \n(SELECT process_revisions.engine'
        'ering_configuration_id AS engineering_configuration_id, process_revisions.en'
        'gineering_revision AS engineering_revision, process_revisions.operations AS '
        'operations, process_revisions.site AS site, process_revisions.line AS line, '
        'process_revisions.series_id AS series_id, process_revisions.previous_id AS p'
        'revious_id, process_revisions.expected_previous_revision AS expected_previou'
        's_revision, process_revisions.reason AS reason, process_revisions.product_id'
        ' AS product_id, process_revisions.owner_id AS owner_id, process_revisions.na'
        'me AS name, process_revisions.status AS status, process_revisions.visibility'
        ' AS visibility, process_revisions.revision AS revision, process_revisions.so'
        'urces AS sources, process_revisions.required_source_read_set AS required_sou'
        'rce_read_set, process_revisions.id AS id, process_revisions.tenant_id AS ten'
        'ant_id, process_revisions.created_at AS created_at, process_revisions.catego'
        'ry_id AS category_id \nFROM process_revisions \nWHERE process_revisions.tena'
        "nt_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), "
        "\nenterprise_authoritative_artifacts_44575cf5b28512d7 AS \n(SELECT 'artifact"
        "' AS source_type, artifact_versions.id AS source_id, artifact_versions.tenan"
        't_id AS tenant_id, artifact_versions.category_id AS category_id, artifact_ve'
        'rsions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL'
        ' AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_v'
        'ersions.revision AS source_revision, artifact_versions.title AS title, artif'
        'act_versions.content_hash AS content_hash, artifact_versions.content AS body'
        ", CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_version"
        "s.visibility != 'category' OR coalesce(products.visibility != 'category', fa"
        "lse) OR coalesce(uploaded_originals.visibility != 'category', false) AS priv"
        'ate, artifact_versions.original_id IS NOT NULL AS customer_original, true AS'
        ' is_current, artifact_versions.created_at AS created_at, artifact_versions.o'
        'riginal_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (art'
        'ifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.origina'
        "l_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_stat"
        'us \nFROM artifact_versions LEFT OUTER JOIN products ON products.tenant_id ='
        ' artifact_versions.tenant_id AND products.id = artifact_versions.product_id '
        'LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = artifac'
        't_versions.tenant_id AND uploaded_originals.id = artifact_versions.original_'
        'id AND uploaded_originals.category_id = artifact_versions.category_id AND up'
        'loaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.product_i'
        'd LEFT OUTER JOIN original_security ON original_security.tenant_id = uploade'
        'd_originals.tenant_id AND original_security.original_id = uploaded_originals'
        ".id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_setting('pdos."
        "tenant_id', true), '') AS UUID) AND artifact_versions.status = 'active' AND "
        'artifact_versions.category_id IS NOT NULL AND (artifact_versions.product_id '
        'IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NU'
        "LL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status = 'par"
        "sed' AND uploaded_originals.scan_status = 'clean' AND original_security.sour"
        "ce_state = 'active' AND original_security.disposition = 'active' AND origina"
        'l_security.current_request_id IS NOT NULL)), \nshared_enterprise_builds AS M'
        'ATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id AS '
        'project_id, builds.project_revision AS project_revision, builds.engineering_'
        'configuration_id AS engineering_configuration_id, builds.manufacturing_confi'
        'guration_id AS manufacturing_configuration_id, builds.previous_build_id AS p'
        'revious_build_id, builds.owner_id AS owner_id, builds.name AS name, builds.t'
        'ype AS type, builds.purpose AS purpose, builds.planned_quantity AS planned_q'
        'uantity, builds.unit AS unit, builds.planned_start AS planned_start, builds.'
        'planned_end AS planned_end, builds.verification_objectives AS verification_o'
        'bjectives, builds.disposition_plan AS disposition_plan, builds.visibility AS'
        ' visibility, builds.revision AS revision, builds.status AS status, builds.id'
        ' AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, buil'
        'ds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ente"
        'rprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id,'
        ' projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS p'
        'urpose, projects.scope AS scope, projects.visibility AS visibility, projects'
        '.status AS status, projects.revision AS revision, projects.current_plan_id A'
        'S current_plan_id, projects.trigger_type AS trigger_type, projects.trigger_i'
        'd AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS i'
        'd, projects.tenant_id AS tenant_id, projects.created_at AS created_at, proje'
        'cts.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared"
        '_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, produc'
        'ts.purpose AS purpose, products.revision AS revision, products.lifecycle_epo'
        'ch AS lifecycle_epoch, products.status AS status, products.owner_id AS owner'
        '_id, products.parent_product_id AS parent_product_id, products.category_id A'
        'S category_id, products.visibility AS visibility, products.target_price AS t'
        'arget_price, products.target_price_currency AS target_price_currency, produc'
        'ts.target_price_basis AS target_price_basis, products.target_price_includes_'
        'tax AS target_price_includes_tax, products.target_price_as_of AS target_pric'
        'e_as_of, products.id AS id, products.tenant_id AS tenant_id, products.create'
        'd_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif('
        "current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_"
        'build_starts AS MATERIALIZED \n(SELECT build_starts.product_id AS product_id'
        ', build_starts.project_id AS project_id, build_starts.build_id AS build_id, '
        'build_starts.build_revision AS build_revision, build_starts.engineering_conf'
        'iguration_id AS engineering_configuration_id, build_starts.manufacturing_con'
        'figuration_id AS manufacturing_configuration_id, build_starts.assessment_id '
        'AS assessment_id, build_starts.assessment_revision AS assessment_revision, b'
        'uild_starts.assessment_sha256 AS assessment_sha256, build_starts.engineering'
        '_authorization_id AS engineering_authorization_id, build_starts.engineering_'
        'authorization_revision AS engineering_authorization_revision, build_starts.m'
        'anufacturing_authorization_id AS manufacturing_authorization_id, build_start'
        's.manufacturing_authorization_revision AS manufacturing_authorization_revisi'
        'on, build_starts.engineering_role AS engineering_role, build_starts.manufact'
        'uring_role AS manufacturing_role, build_starts.revision AS revision, build_s'
        'tarts.owner_id AS owner_id, build_starts.visibility AS visibility, build_sta'
        'rts.status AS status, build_starts.occurred_at AS occurred_at, build_starts.'
        'occurred_timezone AS occurred_timezone, build_starts.execution_scope AS exec'
        'ution_scope, build_starts.event_source AS event_source, build_starts.authori'
        'ty_snapshot AS authority_snapshot, build_starts.reservations AS reservations'
        ', build_starts.sources AS sources, build_starts.required_source_read_set AS '
        'required_source_read_set, build_starts.snapshot_sha256 AS snapshot_sha256, b'
        'uild_starts.intent_digest AS intent_digest, build_starts.reason AS reason, b'
        'uild_starts.id AS id, build_starts.tenant_id AS tenant_id, build_starts.crea'
        'ted_at AS created_at, build_starts.category_id AS category_id \nFROM build_s'
        "tarts \nWHERE build_starts.tenant_id = CAST(nullif(current_setting('pdos.ten"
        "ant_id', true), '') AS UUID)), \nshared_enterprise_actual_configurations AS "
        'MATERIALIZED \n(SELECT actual_configurations.status AS status, actual_config'
        'urations.planned_engineering_configuration_id AS planned_engineering_configu'
        'ration_id, actual_configurations.planned_manufacturing_configuration_id AS p'
        'lanned_manufacturing_configuration_id, actual_configurations.actual_engineer'
        'ing_configuration_id AS actual_engineering_configuration_id, actual_configur'
        'ations.actual_engineering_revision AS actual_engineering_revision, actual_co'
        'nfigurations.actual_manufacturing_configuration_id AS actual_manufacturing_c'
        'onfiguration_id, actual_configurations.actual_manufacturing_revision AS actu'
        'al_manufacturing_revision, actual_configurations.observed_at AS observed_at,'
        ' actual_configurations.differences AS differences, actual_configurations.pro'
        'duct_id AS product_id, actual_configurations.project_id AS project_id, actua'
        'l_configurations.build_id AS build_id, actual_configurations.build_revision '
        'AS build_revision, actual_configurations.owner_id AS owner_id, actual_config'
        'urations.visibility AS visibility, actual_configurations.revision AS revisio'
        'n, actual_configurations.reason AS reason, actual_configurations.sources AS '
        'sources, actual_configurations.required_source_read_set AS required_source_r'
        'ead_set, actual_configurations.id AS id, actual_configurations.tenant_id AS '
        'tenant_id, actual_configurations.created_at AS created_at, actual_configurat'
        'ions.category_id AS category_id \nFROM actual_configurations \nWHERE actual_'
        "configurations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', tru"
        "e), '') AS UUID)), \nshared_enterprise_build_lots AS MATERIALIZED \n(SELECT "
        'build_lots.status AS status, build_lots.actual_configuration_id AS actual_co'
        'nfiguration_id, build_lots.actual_configuration_revision AS actual_configura'
        'tion_revision, build_lots.lot_label AS lot_label, build_lots.observed_unit_c'
        'ount AS observed_unit_count, build_lots.unit AS unit, build_lots.observation'
        '_system AS observation_system, build_lots.observation_external_id AS observa'
        'tion_external_id, build_lots.observation_nature AS observation_nature, build'
        '_lots.occurred_at AS occurred_at, build_lots.received_at AS received_at, bui'
        'ld_lots.product_id AS product_id, build_lots.project_id AS project_id, build'
        '_lots.build_id AS build_id, build_lots.build_revision AS build_revision, bui'
        'ld_lots.owner_id AS owner_id, build_lots.visibility AS visibility, build_lot'
        's.revision AS revision, build_lots.reason AS reason, build_lots.sources AS s'
        'ources, build_lots.required_source_read_set AS required_source_read_set, bui'
        'ld_lots.id AS id, build_lots.tenant_id AS tenant_id, build_lots.created_at A'
        'S created_at, build_lots.category_id AS category_id \nFROM build_lots \nWHER'
        "E build_lots.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)"
        ", '') AS UUID)), \nauthoritative_enterprise_sources_44575cf5b28512d7 AS \n(S"
        "ELECT 'build' AS source_type, shared_enterprise_builds.id AS source_id, shar"
        'ed_enterprise_builds.tenant_id AS tenant_id, shared_enterprise_builds.catego'
        'ry_id AS category_id, shared_enterprise_builds.product_id AS product_id, sha'
        'red_enterprise_builds.project_id AS project_id, CAST(NULL AS UUID) AS propos'
        'al_id, shared_enterprise_builds.owner_id AS owner_id, shared_enterprise_buil'
        'ds.revision AS source_revision, shared_enterprise_builds.name AS title, enco'
        "de(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterp"
        "rise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('name', shared_"
        "enterprise_builds.name, 'type', shared_enterprise_builds.type, 'purpose', sh"
        "ared_enterprise_builds.purpose, 'planned_quantity', shared_enterprise_builds"
        ".planned_quantity, 'unit', shared_enterprise_builds.unit, 'planned_start', s"
        "hared_enterprise_builds.planned_start, 'planned_end', shared_enterprise_buil"
        "ds.planned_end, 'engineering_configuration_id', shared_enterprise_builds.eng"
        "ineering_configuration_id, 'manufacturing_configuration_id', shared_enterpri"
        "se_builds.manufacturing_configuration_id, 'verification_objectives', shared_"
        "enterprise_builds.verification_objectives, 'plan_status', shared_enterprise_"
        "builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object"
        "('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'ver"
        "sion', enterprise_reads_build.value['expected_revision']) ORDER BY enterpris"
        "e_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'exp"
        "ected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elem"
        'ents((SELECT shared_enterprise_engineering_configurations.required_source_re'
        'ad_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_en'
        'terprise_engineering_configurations.tenant_id = shared_enterprise_builds.ten'
        'ant_id AND shared_enterprise_engineering_configurations.product_id = shared_'
        'enterprise_builds.product_id AND shared_enterprise_engineering_configuration'
        's.id = shared_enterprise_builds.engineering_configuration_id) || (SELECT sha'
        'red_enterprise_process_revisions.required_source_read_set \nFROM shared_ente'
        'rprise_process_revisions \nWHERE shared_enterprise_process_revisions.tenant_'
        'id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisi'
        'ons.product_id = shared_enterprise_builds.product_id AND shared_enterprise_p'
        'rocess_revisions.id = shared_enterprise_builds.manufacturing_configuration_i'
        "d)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_builds.id, 'kind', 'build', 'facts', jsonb_build_ob"
        "ject('name', shared_enterprise_builds.name, 'type', shared_enterprise_builds"
        ".type, 'purpose', shared_enterprise_builds.purpose, 'planned_quantity', shar"
        "ed_enterprise_builds.planned_quantity, 'unit', shared_enterprise_builds.unit"
        ", 'planned_start', shared_enterprise_builds.planned_start, 'planned_end', sh"
        "ared_enterprise_builds.planned_end, 'engineering_configuration_id', shared_e"
        "nterprise_builds.engineering_configuration_id, 'manufacturing_configuration_"
        "id', shared_enterprise_builds.manufacturing_configuration_id, 'verification_"
        "objectives', shared_enterprise_builds.verification_objectives, 'plan_status'"
        ", shared_enterprise_builds.status), 'source_refs', (SELECT coalesce(jsonb_ag"
        "g(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value["
        "'artifact_id'], 'version', enterprise_reads_build.value['expected_revision']"
        ") ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_"
        "build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        'ROM jsonb_array_elements((SELECT shared_enterprise_engineering_configuration'
        's.required_source_read_set \nFROM shared_enterprise_engineering_configuratio'
        'ns \nWHERE shared_enterprise_engineering_configurations.tenant_id = shared_e'
        'nterprise_builds.tenant_id AND shared_enterprise_engineering_configurations.'
        'product_id = shared_enterprise_builds.product_id AND shared_enterprise_engin'
        'eering_configurations.id = shared_enterprise_builds.engineering_configuratio'
        'n_id) || (SELECT shared_enterprise_process_revisions.required_source_read_se'
        't \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_proce'
        'ss_revisions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enter'
        'prise_process_revisions.product_id = shared_enterprise_builds.product_id AND'
        ' shared_enterprise_process_revisions.id = shared_enterprise_builds.manufactu'
        "ring_configuration_id)) AS enterprise_reads_build(value)), 'record_policy', "
        "'\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('nam"
        "e', shared_enterprise_builds.name, 'type', shared_enterprise_builds.type, 'p"
        "urpose', shared_enterprise_builds.purpose, 'planned_quantity', shared_enterp"
        "rise_builds.planned_quantity, 'unit', shared_enterprise_builds.unit, 'planne"
        "d_start', shared_enterprise_builds.planned_start, 'planned_end', shared_ente"
        "rprise_builds.planned_end, 'engineering_configuration_id', shared_enterprise"
        "_builds.engineering_configuration_id, 'manufacturing_configuration_id', shar"
        "ed_enterprise_builds.manufacturing_configuration_id, 'verification_objective"
        "s', shared_enterprise_builds.verification_objectives, 'plan_status', shared_"
        "enterprise_builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact"
        "_id'], 'version', enterprise_reads_build.value['expected_revision']) ORDER B"
        "Y enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.val"
        "ue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb"
        '_array_elements((SELECT shared_enterprise_engineering_configurations.require'
        'd_source_read_set \nFROM shared_enterprise_engineering_configurations \nWHER'
        'E shared_enterprise_engineering_configurations.tenant_id = shared_enterprise'
        '_builds.tenant_id AND shared_enterprise_engineering_configurations.product_i'
        'd = shared_enterprise_builds.product_id AND shared_enterprise_engineering_co'
        'nfigurations.id = shared_enterprise_builds.engineering_configuration_id) || '
        '(SELECT shared_enterprise_process_revisions.required_source_read_set \nFROM '
        'shared_enterprise_process_revisions \nWHERE shared_enterprise_process_revisi'
        'ons.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_pro'
        'cess_revisions.product_id = shared_enterprise_builds.product_id AND shared_e'
        'nterprise_process_revisions.id = shared_enterprise_builds.manufacturing_conf'
        "iguration_id)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_builds.vis"
        "ibility != 'category' OR coalesce(shared_enterprise_projects.visibility != '"
        "category', false) OR coalesce(shared_enterprise_products.visibility != 'cate"
        "gory', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT share"
        'd_enterprise_engineering_configurations.required_source_read_set \nFROM shar'
        'ed_enterprise_engineering_configurations \nWHERE shared_enterprise_engineeri'
        'ng_configurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_'
        'enterprise_engineering_configurations.product_id = shared_enterprise_builds.'
        'product_id AND shared_enterprise_engineering_configurations.id = shared_ente'
        'rprise_builds.engineering_configuration_id) || (SELECT shared_enterprise_pro'
        'cess_revisions.required_source_read_set \nFROM shared_enterprise_process_rev'
        'isions \nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterp'
        'rise_builds.tenant_id AND shared_enterprise_process_revisions.product_id = s'
        'hared_enterprise_builds.product_id AND shared_enterprise_process_revisions.i'
        'd = shared_enterprise_builds.manufacturing_configuration_id)) AS enterprise_'
        'reads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 '
        'ON enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_en'
        'terprise_builds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28'
        "512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.private)) A'
        'S private, EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enter'
        'prise_engineering_configurations.required_source_read_set \nFROM shared_ente'
        'rprise_engineering_configurations \nWHERE shared_enterprise_engineering_conf'
        'igurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterpr'
        'ise_engineering_configurations.product_id = shared_enterprise_builds.product'
        '_id AND shared_enterprise_engineering_configurations.id = shared_enterprise_'
        'builds.engineering_configuration_id) || (SELECT shared_enterprise_process_re'
        'visions.required_source_read_set \nFROM shared_enterprise_process_revisions '
        '\nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterprise_bu'
        'ilds.tenant_id AND shared_enterprise_process_revisions.product_id = shared_e'
        'nterprise_builds.product_id AND shared_enterprise_process_revisions.id = sha'
        'red_enterprise_builds.manufacturing_configuration_id)) AS enterprise_reads_b'
        'uild(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterpris'
        'e_builds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.s'
        "ource_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_44575cf5b28512d7.customer_original)'
        ' AS customer_original, true AS is_current, shared_enterprise_builds.created_'
        'at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_build'
        's.id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artif'
        'acts_44575cf5b28512d7.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM js'
        'onb_array_elements((SELECT shared_enterprise_engineering_configurations.requ'
        'ired_source_read_set \nFROM shared_enterprise_engineering_configurations \nW'
        'HERE shared_enterprise_engineering_configurations.tenant_id = shared_enterpr'
        'ise_builds.tenant_id AND shared_enterprise_engineering_configurations.produc'
        't_id = shared_enterprise_builds.product_id AND shared_enterprise_engineering'
        '_configurations.id = shared_enterprise_builds.engineering_configuration_id) '
        '|| (SELECT shared_enterprise_process_revisions.required_source_read_set \nFR'
        'OM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_rev'
        'isions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_'
        'process_revisions.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_c'
        'onfiguration_id)) AS enterprise_reads_build(value) JOIN enterprise_authorita'
        'tive_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts_44575c'
        'f5b28512d7.tenant_id = shared_enterprise_builds.tenant_id AND enterprise_aut'
        'horitative_artifacts_44575cf5b28512d7.source_id = CAST((enterprise_reads_bui'
        "ld.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifa"
        'cts_44575cf5b28512d7.original_id IS NOT NULL) AS original_ids, CASE WHEN (EX'
        'ISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterprise_enginee'
        'ring_configurations.required_source_read_set \nFROM shared_enterprise_engine'
        'ering_configurations \nWHERE shared_enterprise_engineering_configurations.te'
        'nant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_engineeri'
        'ng_configurations.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_engineering_configurations.id = shared_enterprise_builds.engine'
        'ering_configuration_id) || (SELECT shared_enterprise_process_revisions.requi'
        'red_source_read_set \nFROM shared_enterprise_process_revisions \nWHERE share'
        'd_enterprise_process_revisions.tenant_id = shared_enterprise_builds.tenant_i'
        'd AND shared_enterprise_process_revisions.product_id = shared_enterprise_bui'
        'lds.product_id AND shared_enterprise_process_revisions.id = shared_enterpris'
        'e_builds.manufacturing_configuration_id)) AS enterprise_reads_build(value) J'
        'OIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_author'
        'itative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_builds.tena'
        'nt_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CA'
        "ST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_44575cf5b28512d7.source_revision != CAST((enterp'
        "rise_reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_re"
        "check' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_buil"
        'ds JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id ='
        ' shared_enterprise_builds.tenant_id AND shared_enterprise_projects.product_i'
        'd = shared_enterprise_builds.product_id AND shared_enterprise_projects.id = '
        'shared_enterprise_builds.project_id AND shared_enterprise_projects.category_'
        'id = shared_enterprise_builds.category_id JOIN shared_enterprise_products ON'
        ' shared_enterprise_products.tenant_id = shared_enterprise_builds.tenant_id A'
        'ND shared_enterprise_products.id = shared_enterprise_builds.product_id AND s'
        'hared_enterprise_products.category_id = shared_enterprise_builds.category_id'
        " \nWHERE shared_enterprise_builds.tenant_id = CAST(nullif(current_setting('p"
        "dos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_a"
        'rray_elements((SELECT shared_enterprise_engineering_configurations.required_'
        'source_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE '
        'shared_enterprise_engineering_configurations.tenant_id = shared_enterprise_b'
        'uilds.tenant_id AND shared_enterprise_engineering_configurations.product_id '
        '= shared_enterprise_builds.product_id AND shared_enterprise_engineering_conf'
        'igurations.id = shared_enterprise_builds.engineering_configuration_id) || (S'
        'ELECT shared_enterprise_process_revisions.required_source_read_set \nFROM sh'
        'ared_enterprise_process_revisions \nWHERE shared_enterprise_process_revision'
        's.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_proce'
        'ss_revisions.product_id = shared_enterprise_builds.product_id AND shared_ent'
        'erprise_process_revisions.id = shared_enterprise_builds.manufacturing_config'
        'uration_id)) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 '
        '\nFROM enterprise_authoritative_artifacts_44575cf5b28512d7 \nWHERE enterpris'
        'e_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_bui'
        'lds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source'
        "_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID))))) AND"
        ' (EXISTS (SELECT shared_enterprise_engineering_configurations.required_sourc'
        'e_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE share'
        'd_enterprise_engineering_configurations.tenant_id = shared_enterprise_builds'
        '.tenant_id AND shared_enterprise_engineering_configurations.product_id = sha'
        'red_enterprise_builds.product_id AND shared_enterprise_engineering_configura'
        'tions.id = shared_enterprise_builds.engineering_configuration_id)) AND (EXIS'
        'TS (SELECT shared_enterprise_process_revisions.required_source_read_set \nFR'
        'OM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_rev'
        'isions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_'
        'process_revisions.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_c'
        "onfiguration_id)) UNION ALL SELECT 'build' AS source_type, shared_enterprise"
        '_build_starts.id AS source_id, shared_enterprise_build_starts.tenant_id AS t'
        'enant_id, shared_enterprise_build_starts.category_id AS category_id, shared_'
        'enterprise_build_starts.product_id AS product_id, shared_enterprise_build_st'
        'arts.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_ent'
        'erprise_build_starts.owner_id AS owner_id, shared_enterprise_build_starts.re'
        "vision AS source_revision, '\u5f00\u5de5\u8bb0\u5f55 \xb7 ' || shared_enterp"
        'rise_builds.name AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_ob'
        "ject('object_id', shared_enterprise_build_starts.build_id, 'kind', 'build', "
        "'facts', jsonb_build_object('record_kind', 'build_start', 'build_id', shared"
        "_enterprise_build_starts.build_id, 'build_revision', shared_enterprise_build"
        "_starts.build_revision, 'status', shared_enterprise_build_starts.status, 'oc"
        "curred_at', shared_enterprise_build_starts.occurred_at, 'occurred_timezone',"
        " shared_enterprise_build_starts.occurred_timezone, 'assessment_id', shared_e"
        "nterprise_build_starts.assessment_id, 'assessment_revision', shared_enterpri"
        "se_build_starts.assessment_revision, 'engineering_authorization_id', shared_"
        "enterprise_build_starts.engineering_authorization_id, 'engineering_authoriza"
        "tion_revision', shared_enterprise_build_starts.engineering_authorization_rev"
        "ision, 'manufacturing_authorization_id', shared_enterprise_build_starts.manu"
        "facturing_authorization_id, 'manufacturing_authorization_revision', shared_e"
        'nterprise_build_starts.manufacturing_authorization_revision) || jsonb_build_'
        "object('execution_scope', jsonb_build_object('purpose', shared_enterprise_bu"
        "ild_starts.execution_scope['purpose'], 'quantity', shared_enterprise_build_s"
        "tarts.execution_scope['quantity'], 'unit', shared_enterprise_build_starts.ex"
        "ecution_scope['unit'], 'site', shared_enterprise_build_starts.execution_scop"
        "e['site'], 'window_start', shared_enterprise_build_starts.execution_scope['w"
        "indow_start'], 'window_end', shared_enterprise_build_starts.execution_scope["
        "'window_end'], 'window_timezone', shared_enterprise_build_starts.execution_s"
        "cope['window_timezone']), 'continuation_permission', 'not_evaluated'), 'sour"
        "ce_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', "
        "'id', enterprise_reads_build.value['artifact_id'], 'version', enterprise_rea"
        "ds_build.value['expected_revision']) ORDER BY enterprise_reads_build.value -"
        ">> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), jso"
        'nb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterpris'
        'e_build_starts.required_source_read_set) AS enterprise_reads_build(value)), '
        "'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_h"
        "ash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_build_start"
        "s.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'bui"
        "ld_start', 'build_id', shared_enterprise_build_starts.build_id, 'build_revis"
        "ion', shared_enterprise_build_starts.build_revision, 'status', shared_enterp"
        "rise_build_starts.status, 'occurred_at', shared_enterprise_build_starts.occu"
        "rred_at, 'occurred_timezone', shared_enterprise_build_starts.occurred_timezo"
        "ne, 'assessment_id', shared_enterprise_build_starts.assessment_id, 'assessme"
        "nt_revision', shared_enterprise_build_starts.assessment_revision, 'engineeri"
        "ng_authorization_id', shared_enterprise_build_starts.engineering_authorizati"
        "on_id, 'engineering_authorization_revision', shared_enterprise_build_starts."
        "engineering_authorization_revision, 'manufacturing_authorization_id', shared"
        "_enterprise_build_starts.manufacturing_authorization_id, 'manufacturing_auth"
        "orization_revision', shared_enterprise_build_starts.manufacturing_authorizat"
        "ion_revision) || jsonb_build_object('execution_scope', jsonb_build_object('p"
        "urpose', shared_enterprise_build_starts.execution_scope['purpose'], 'quantit"
        "y', shared_enterprise_build_starts.execution_scope['quantity'], 'unit', shar"
        "ed_enterprise_build_starts.execution_scope['unit'], 'site', shared_enterpris"
        "e_build_starts.execution_scope['site'], 'window_start', shared_enterprise_bu"
        "ild_starts.execution_scope['window_start'], 'window_end', shared_enterprise_"
        "build_starts.execution_scope['window_end'], 'window_timezone', shared_enterp"
        "rise_build_starts.execution_scope['window_timezone']), 'continuation_permiss"
        "ion', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id"
        "'], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY e"
        "nterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value "
        "->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_ar"
        'ray_elements(shared_enterprise_build_starts.required_source_read_set) AS ent'
        "erprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) "
        "AS body, CAST(jsonb_build_object('object_id', shared_enterprise_build_starts"
        ".build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'buil"
        "d_start', 'build_id', shared_enterprise_build_starts.build_id, 'build_revisi"
        "on', shared_enterprise_build_starts.build_revision, 'status', shared_enterpr"
        "ise_build_starts.status, 'occurred_at', shared_enterprise_build_starts.occur"
        "red_at, 'occurred_timezone', shared_enterprise_build_starts.occurred_timezon"
        "e, 'assessment_id', shared_enterprise_build_starts.assessment_id, 'assessmen"
        "t_revision', shared_enterprise_build_starts.assessment_revision, 'engineerin"
        "g_authorization_id', shared_enterprise_build_starts.engineering_authorizatio"
        "n_id, 'engineering_authorization_revision', shared_enterprise_build_starts.e"
        "ngineering_authorization_revision, 'manufacturing_authorization_id', shared_"
        "enterprise_build_starts.manufacturing_authorization_id, 'manufacturing_autho"
        "rization_revision', shared_enterprise_build_starts.manufacturing_authorizati"
        "on_revision) || jsonb_build_object('execution_scope', jsonb_build_object('pu"
        "rpose', shared_enterprise_build_starts.execution_scope['purpose'], 'quantity"
        "', shared_enterprise_build_starts.execution_scope['quantity'], 'unit', share"
        "d_enterprise_build_starts.execution_scope['unit'], 'site', shared_enterprise"
        "_build_starts.execution_scope['site'], 'window_start', shared_enterprise_bui"
        "ld_starts.execution_scope['window_start'], 'window_end', shared_enterprise_b"
        "uild_starts.execution_scope['window_end'], 'window_timezone', shared_enterpr"
        "ise_build_starts.execution_scope['window_timezone']), 'continuation_permissi"
        "on', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build"
        "_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'"
        "], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY en"
        "terprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value -"
        ">> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_arr"
        'ay_elements(shared_enterprise_build_starts.required_source_read_set) AS ente'
        "rprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_build_starts.visibility != 'catego"
        "ry' OR coalesce(shared_enterprise_projects.visibility != 'category', false) "
        "OR coalesce(shared_enterprise_products.visibility != 'category', false) OR ("
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.'
        'required_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_a'
        'uthoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifact'
        's_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts.tenant_id AND '
        'enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((enterp'
        "rise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_author"
        'itative_artifacts_44575cf5b28512d7.private)) OR shared_enterprise_builds.vis'
        "ibility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_build_starts.required_source_read_set) AS enterprise_re'
        'ads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON'
        ' enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_ente'
        'rprise_build_starts.tenant_id AND enterprise_authoritative_artifacts_44575cf'
        "5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') "
        'AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.custome'
        'r_original) AS customer_original, true AS is_current, shared_enterprise_buil'
        'd_starts.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared'
        '_enterprise_build_starts.build_id AS object_id, (SELECT coalesce(array_agg(e'
        'nterprise_authoritative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UU'
        'ID[]) AS coalesce_4 \nFROM jsonb_array_elements(shared_enterprise_build_star'
        'ts.required_source_read_set) AS enterprise_reads_build(value) JOIN enterpris'
        'e_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artif'
        'acts_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts.tenant_id A'
        'ND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((ent'
        "erprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_aut"
        'horitative_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS original_i'
        'ds, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpris'
        'e_build_starts.required_source_read_set) AS enterprise_reads_build(value) JO'
        'IN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authori'
        'tative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts'
        '.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id'
        " = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE en"
        'terprise_authoritative_artifacts_44575cf5b28512d7.source_revision != CAST((e'
        "nterprise_reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'nee"
        "ds_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise"
        '_build_starts JOIN shared_enterprise_projects ON shared_enterprise_projects.'
        'tenant_id = shared_enterprise_build_starts.tenant_id AND shared_enterprise_p'
        'rojects.product_id = shared_enterprise_build_starts.product_id AND shared_en'
        'terprise_projects.id = shared_enterprise_build_starts.project_id AND shared_'
        'enterprise_projects.category_id = shared_enterprise_build_starts.category_id'
        ' JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id = s'
        'hared_enterprise_build_starts.tenant_id AND shared_enterprise_products.id = '
        'shared_enterprise_build_starts.product_id AND shared_enterprise_products.cat'
        'egory_id = shared_enterprise_build_starts.category_id JOIN shared_enterprise'
        '_builds ON shared_enterprise_builds.tenant_id = shared_enterprise_build_star'
        'ts.tenant_id AND shared_enterprise_builds.category_id = shared_enterprise_bu'
        'ild_starts.category_id AND shared_enterprise_builds.product_id = shared_ente'
        'rprise_build_starts.product_id AND shared_enterprise_builds.project_id = sha'
        'red_enterprise_build_starts.project_id AND shared_enterprise_builds.id = sha'
        'red_enterprise_build_starts.build_id AND shared_enterprise_builds.revision ='
        ' shared_enterprise_build_starts.build_revision \nWHERE shared_enterprise_bui'
        "ld_starts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '"
        "') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ent"
        'erprise_build_starts.required_source_read_set) AS enterprise_reads_build(val'
        'ue) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_'
        '44575cf5b28512d7 \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7'
        '.tenant_id = shared_enterprise_build_starts.tenant_id AND enterprise_authori'
        'tative_artifacts_44575cf5b28512d7.source_id = CAST((enterprise_reads_build.v'
        "alue ->> 'artifact_id') AS UUID))))) UNION ALL SELECT 'build' AS source_type"
        ', shared_enterprise_actual_configurations.id AS source_id, shared_enterprise'
        '_actual_configurations.tenant_id AS tenant_id, shared_enterprise_actual_conf'
        'igurations.category_id AS category_id, shared_enterprise_actual_configuratio'
        'ns.product_id AS product_id, shared_enterprise_actual_configurations.project'
        '_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_actu'
        'al_configurations.owner_id AS owner_id, shared_enterprise_actual_configurati'
        "ons.revision AS source_revision, '\u5b9e\u9645\u914d\u7f6e\u8bb0\u5f55 \xb7 "
        "' || shared_enterprise_builds.name AS title, encode(sha256(convert_to(CAST(C"
        "AST(jsonb_build_object('object_id', shared_enterprise_actual_configurations."
        "build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actua"
        "l_configuration', 'build_id', shared_enterprise_actual_configurations.build_"
        "id, 'build_revision', shared_enterprise_actual_configurations.build_revision"
        ", 'status', shared_enterprise_actual_configurations.status, 'planned_enginee"
        "ring_configuration_id', shared_enterprise_actual_configurations.planned_engi"
        "neering_configuration_id, 'planned_manufacturing_configuration_id', shared_e"
        "nterprise_actual_configurations.planned_manufacturing_configuration_id, 'act"
        "ual_engineering_configuration_id', shared_enterprise_actual_configurations.a"
        "ctual_engineering_configuration_id, 'actual_engineering_revision', shared_en"
        "terprise_actual_configurations.actual_engineering_revision, 'actual_manufact"
        "uring_configuration_id', shared_enterprise_actual_configurations.actual_manu"
        "facturing_configuration_id, 'actual_manufacturing_revision', shared_enterpri"
        "se_actual_configurations.actual_manufacturing_revision, 'observed_at', share"
        "d_enterprise_actual_configurations.observed_at), 'source_refs', (SELECT coal"
        "esce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads"
        "_build.value['artifact_id'], 'version', enterprise_reads_build.value['expect"
        "ed_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', ente"
        "rprise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS c"
        'oalesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_configuration'
        "s.required_source_read_set) AS enterprise_reads_build(value)), 'record_polic"
        "y', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CA"
        "ST(jsonb_build_object('object_id', shared_enterprise_actual_configurations.b"
        "uild_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actual"
        "_configuration', 'build_id', shared_enterprise_actual_configurations.build_i"
        "d, 'build_revision', shared_enterprise_actual_configurations.build_revision,"
        " 'status', shared_enterprise_actual_configurations.status, 'planned_engineer"
        "ing_configuration_id', shared_enterprise_actual_configurations.planned_engin"
        "eering_configuration_id, 'planned_manufacturing_configuration_id', shared_en"
        "terprise_actual_configurations.planned_manufacturing_configuration_id, 'actu"
        "al_engineering_configuration_id', shared_enterprise_actual_configurations.ac"
        "tual_engineering_configuration_id, 'actual_engineering_revision', shared_ent"
        "erprise_actual_configurations.actual_engineering_revision, 'actual_manufactu"
        "ring_configuration_id', shared_enterprise_actual_configurations.actual_manuf"
        "acturing_configuration_id, 'actual_manufacturing_revision', shared_enterpris"
        "e_actual_configurations.actual_manufacturing_revision, 'observed_at', shared"
        "_enterprise_actual_configurations.observed_at), 'source_refs', (SELECT coale"
        "sce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_"
        "build.value['artifact_id'], 'version', enterprise_reads_build.value['expecte"
        "d_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enter"
        "prise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS co"
        'alesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations'
        ".required_source_read_set) AS enterprise_reads_build(value)), 'record_policy"
        "', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_actual_configurations.build_id, 'kind', 'build', 'facts', js"
        "onb_build_object('record_kind', 'actual_configuration', 'build_id', shared_e"
        "nterprise_actual_configurations.build_id, 'build_revision', shared_enterpris"
        "e_actual_configurations.build_revision, 'status', shared_enterprise_actual_c"
        "onfigurations.status, 'planned_engineering_configuration_id', shared_enterpr"
        "ise_actual_configurations.planned_engineering_configuration_id, 'planned_man"
        "ufacturing_configuration_id', shared_enterprise_actual_configurations.planne"
        "d_manufacturing_configuration_id, 'actual_engineering_configuration_id', sha"
        "red_enterprise_actual_configurations.actual_engineering_configuration_id, 'a"
        "ctual_engineering_revision', shared_enterprise_actual_configurations.actual_"
        "engineering_revision, 'actual_manufacturing_configuration_id', shared_enterp"
        "rise_actual_configurations.actual_manufacturing_configuration_id, 'actual_ma"
        "nufacturing_revision', shared_enterprise_actual_configurations.actual_manufa"
        "cturing_revision, 'observed_at', shared_enterprise_actual_configurations.obs"
        "erved_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'version'"
        ", enterprise_reads_build.value['expected_revision']) ORDER BY enterprise_rea"
        "ds_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'expected"
        "_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements("
        'shared_enterprise_actual_configurations.required_source_read_set) AS enterpr'
        "ise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_actual_configurations.visibility !"
        "= 'category' OR coalesce(shared_enterprise_projects.visibility != 'category'"
        ", false) OR coalesce(shared_enterprise_products.visibility != 'category', fa"
        'lse) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_actu'
        'al_configurations.required_source_read_set) AS enterprise_reads_build(value)'
        ' JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_auth'
        'oritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_actual_co'
        'nfigurations.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512'
        "d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.private)) OR s'
        "hared_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT "
        '1 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.requir'
        'ed_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_authori'
        'tative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts_4457'
        '5cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant_id A'
        'ND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((ent'
        "erprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_aut"
        'horitative_artifacts_44575cf5b28512d7.customer_original) AS customer_origina'
        'l, true AS is_current, shared_enterprise_actual_configurations.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_actual_con'
        'figurations.build_id AS object_id, (SELECT coalesce(array_agg(enterprise_aut'
        'horitative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UUID[]) AS coal'
        'esce_6 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.r'
        'equired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_au'
        'thoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts'
        '_44575cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant'
        '_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST'
        "((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpris"
        'e_authoritative_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS origi'
        'nal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ente'
        'rprise_actual_configurations.required_source_read_set) AS enterprise_reads_b'
        'uild(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterpris'
        'e_actual_configurations.tenant_id AND enterprise_authoritative_artifacts_445'
        "75cf5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_i"
        "d') AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.sou"
        "rce_revision != CAST((enterprise_reads_build.value ->> 'expected_revision') "
        "AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status "
        '\nFROM shared_enterprise_actual_configurations JOIN shared_enterprise_projec'
        'ts ON shared_enterprise_projects.tenant_id = shared_enterprise_actual_config'
        'urations.tenant_id AND shared_enterprise_projects.product_id = shared_enterp'
        'rise_actual_configurations.product_id AND shared_enterprise_projects.id = sh'
        'ared_enterprise_actual_configurations.project_id AND shared_enterprise_proje'
        'cts.category_id = shared_enterprise_actual_configurations.category_id JOIN s'
        'hared_enterprise_products ON shared_enterprise_products.tenant_id = shared_e'
        'nterprise_actual_configurations.tenant_id AND shared_enterprise_products.id '
        '= shared_enterprise_actual_configurations.product_id AND shared_enterprise_p'
        'roducts.category_id = shared_enterprise_actual_configurations.category_id JO'
        'IN shared_enterprise_builds ON shared_enterprise_builds.tenant_id = shared_e'
        'nterprise_actual_configurations.tenant_id AND shared_enterprise_builds.categ'
        'ory_id = shared_enterprise_actual_configurations.category_id AND shared_ente'
        'rprise_builds.product_id = shared_enterprise_actual_configurations.product_i'
        'd AND shared_enterprise_builds.project_id = shared_enterprise_actual_configu'
        'rations.project_id AND shared_enterprise_builds.id = shared_enterprise_actua'
        'l_configurations.build_id AND shared_enterprise_builds.revision = shared_ent'
        'erprise_actual_configurations.build_revision \nWHERE shared_enterprise_actua'
        "l_configurations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', t"
        "rue), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(sha"
        'red_enterprise_actual_configurations.required_source_read_set) AS enterprise'
        '_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authorit'
        'ative_artifacts_44575cf5b28512d7 \nWHERE enterprise_authoritative_artifacts_'
        '44575cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant_'
        'id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST('
        "(enterprise_reads_build.value ->> 'artifact_id') AS UUID))))) UNION ALL SELE"
        "CT 'build' AS source_type, shared_enterprise_build_lots.id AS source_id, sha"
        'red_enterprise_build_lots.tenant_id AS tenant_id, shared_enterprise_build_lo'
        'ts.category_id AS category_id, shared_enterprise_build_lots.product_id AS pr'
        'oduct_id, shared_enterprise_build_lots.project_id AS project_id, CAST(NULL A'
        'S UUID) AS proposal_id, shared_enterprise_build_lots.owner_id AS owner_id, s'
        "hared_enterprise_build_lots.revision AS source_revision, '\u5b9e\u7269\u4ea7"
        "\u51fa\u8bb0\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode("
        "sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterpris"
        "e_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_"
        "kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_id, 'b"
        "uild_revision', shared_enterprise_build_lots.build_revision, 'status', share"
        "d_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lots.lo"
        "t_label, 'actual_configuration_id', shared_enterprise_build_lots.actual_conf"
        "iguration_id, 'actual_configuration_revision', shared_enterprise_build_lots."
        "actual_configuration_revision, 'observed_unit_count', shared_enterprise_buil"
        "d_lots.observed_unit_count, 'unit', shared_enterprise_build_lots.unit, 'obse"
        "rvation_nature', shared_enterprise_build_lots.observation_nature, 'occurred_"
        "at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_enterpr"
        "ise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb"
        "_build_object('type', 'artifact', 'id', enterprise_reads_build.value['artifa"
        "ct_id'], 'version', enterprise_reads_build.value['expected_revision']) ORDER"
        " BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.v"
        "alue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jso"
        'nb_array_elements(shared_enterprise_build_lots.required_source_read_set) AS '
        "enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT),"
        " 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_buil"
        "d_object('record_kind', 'build_output', 'build_id', shared_enterprise_build_"
        "lots.build_id, 'build_revision', shared_enterprise_build_lots.build_revision"
        ", 'status', shared_enterprise_build_lots.status, 'lot_label', shared_enterpr"
        "ise_build_lots.lot_label, 'actual_configuration_id', shared_enterprise_build"
        "_lots.actual_configuration_id, 'actual_configuration_revision', shared_enter"
        "prise_build_lots.actual_configuration_revision, 'observed_unit_count', share"
        "d_enterprise_build_lots.observed_unit_count, 'unit', shared_enterprise_build"
        "_lots.unit, 'observation_nature', shared_enterprise_build_lots.observation_n"
        "ature, 'occurred_at', shared_enterprise_build_lots.occurred_at, 'received_at"
        "', shared_enterprise_build_lots.received_at), 'source_refs', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_bu"
        "ild.value['artifact_id'], 'version', enterprise_reads_build.value['expected_"
        "revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterpr"
        "ise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coal"
        'esce_7 \nFROM jsonb_array_elements(shared_enterprise_build_lots.required_sou'
        "rce_read_set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enter"
        "prise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('rec"
        "ord_kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_id"
        ", 'build_revision', shared_enterprise_build_lots.build_revision, 'status', s"
        "hared_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lot"
        "s.lot_label, 'actual_configuration_id', shared_enterprise_build_lots.actual_"
        "configuration_id, 'actual_configuration_revision', shared_enterprise_build_l"
        "ots.actual_configuration_revision, 'observed_unit_count', shared_enterprise_"
        "build_lots.observed_unit_count, 'unit', shared_enterprise_build_lots.unit, '"
        "observation_nature', shared_enterprise_build_lots.observation_nature, 'occur"
        "red_at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_ent"
        "erprise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(j"
        "sonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value['ar"
        "tifact_id'], 'version', enterprise_reads_build.value['expected_revision']) O"
        "RDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_bui"
        "ld.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM"
        ' jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set)'
        " AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_build_lots.visibility "
        "!= 'category' OR coalesce(shared_enterprise_projects.visibility != 'category"
        "', false) OR coalesce(shared_enterprise_products.visibility != 'category', f"
        'alse) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_bui'
        'ld_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_'
        'artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_i'
        'd AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST(('
        "enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_"
        'authoritative_artifacts_44575cf5b28512d7.private)) OR shared_enterprise_buil'
        "ds.visibility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_"
        'elements(shared_enterprise_build_lots.required_source_read_set) AS enterpris'
        'e_reads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d'
        '7 ON enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_'
        'enterprise_build_lots.tenant_id AND enterprise_authoritative_artifacts_44575'
        "cf5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id'"
        ') AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.custo'
        'mer_original) AS customer_original, true AS is_current, shared_enterprise_bu'
        'ild_lots.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared'
        '_enterprise_build_lots.build_id AS object_id, (SELECT coalesce(array_agg(ent'
        'erprise_authoritative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UUID'
        '[]) AS coalesce_8 \nFROM jsonb_array_elements(shared_enterprise_build_lots.r'
        'equired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_au'
        'thoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts'
        '_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_id AND ent'
        'erprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((enterpris'
        "e_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorita"
        'tive_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS original_ids, CA'
        'SE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_buil'
        'd_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN enter'
        'prise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_a'
        'rtifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_id'
        ' AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((e'
        "nterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_a"
        'uthoritative_artifacts_44575cf5b28512d7.source_revision != CAST((enterprise_'
        "reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck"
        "' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_build_lot"
        's JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id = '
        'shared_enterprise_build_lots.tenant_id AND shared_enterprise_projects.produc'
        't_id = shared_enterprise_build_lots.product_id AND shared_enterprise_project'
        's.id = shared_enterprise_build_lots.project_id AND shared_enterprise_project'
        's.category_id = shared_enterprise_build_lots.category_id JOIN shared_enterpr'
        'ise_products ON shared_enterprise_products.tenant_id = shared_enterprise_bui'
        'ld_lots.tenant_id AND shared_enterprise_products.id = shared_enterprise_buil'
        'd_lots.product_id AND shared_enterprise_products.category_id = shared_enterp'
        'rise_build_lots.category_id JOIN shared_enterprise_builds ON shared_enterpri'
        'se_builds.tenant_id = shared_enterprise_build_lots.tenant_id AND shared_ente'
        'rprise_builds.category_id = shared_enterprise_build_lots.category_id AND sha'
        'red_enterprise_builds.product_id = shared_enterprise_build_lots.product_id A'
        'ND shared_enterprise_builds.project_id = shared_enterprise_build_lots.projec'
        't_id AND shared_enterprise_builds.id = shared_enterprise_build_lots.build_id'
        ' AND shared_enterprise_builds.revision = shared_enterprise_build_lots.build_'
        'revision \nWHERE shared_enterprise_build_lots.tenant_id = CAST(nullif(curren'
        "t_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_build_lots.required_source_read_'
        'set) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM e'
        'nterprise_authoritative_artifacts_44575cf5b28512d7 \nWHERE enterprise_author'
        'itative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.'
        'tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id '
        "= CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID))))))\n SELE"
        'CT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_44575cf5b28512d7'
        ' \nWHERE authoritative_enterprise_sources_44575cf5b28512d7.tenant_id = t AND'
        ' authoritative_enterprise_sources_44575cf5b28512d7.category_id = c AND CAST('
        'authoritative_enterprise_sources_44575cf5b28512d7.source_id AS TEXT) = expec'
        "ted->>'source_id' AND CAST(authoritative_enterprise_sources_44575cf5b28512d7"
        ".source_revision AS TEXT) = expected->>'source_revision' AND authoritative_e"
        "nterprise_sources_44575cf5b28512d7.content_hash = expected->>'content_hash')"
        " AS anon_1 INTO visible;\n WHEN 'test_run' THEN\n  WITH enterprise_authorita"
        "tive_artifacts_b8475898ff5f3dcb AS \n(SELECT 'artifact' AS source_type, arti"
        'fact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, art'
        'ifact_versions.category_id AS category_id, artifact_versions.product_id AS p'
        'roduct_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_'
        'id, artifact_versions.owner_id AS owner_id, artifact_versions.revision AS so'
        'urce_revision, artifact_versions.title AS title, artifact_versions.content_h'
        'ash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) '
        "AS structured, 'untrusted' AS nature, artifact_versions.visibility != 'categ"
        "ory' OR coalesce(products.visibility != 'category', false) OR coalesce(uploa"
        "ded_originals.visibility != 'category', false) AS private, artifact_versions"
        '.original_id IS NOT NULL AS customer_original, true AS is_current, artifact_'
        'versions.created_at AS created_at, artifact_versions.original_id AS original'
        '_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.origina'
        'l_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UU'
        "ID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_ver"
        'sions LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.ten'
        'ant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN upload'
        'ed_originals ON uploaded_originals.tenant_id = artifact_versions.tenant_id A'
        'ND uploaded_originals.id = artifact_versions.original_id AND uploaded_origin'
        'als.category_id = artifact_versions.category_id AND uploaded_originals.produ'
        'ct_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN orig'
        'inal_security ON original_security.tenant_id = uploaded_originals.tenant_id '
        'AND original_security.original_id = uploaded_originals.id \nWHERE artifact_v'
        "ersions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '')"
        " AS UUID) AND artifact_versions.status = 'active' AND artifact_versions.cate"
        'gory_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products.id'
        ' IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_origina'
        "ls.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_orig"
        "inals.scan_status = 'clean' AND original_security.source_state = 'active' AN"
        "D original_security.disposition = 'active' AND original_security.current_req"
        'uest_id IS NOT NULL)), \nshared_enterprise_verification_run_versions AS MATE'
        'RIALIZED \n(SELECT verification_run_versions.product_id AS product_id, verif'
        'ication_run_versions.project_id AS project_id, verification_run_versions.bui'
        'ld_id AS build_id, verification_run_versions.build_revision AS build_revisio'
        'n, verification_run_versions.request_id AS request_id, verification_run_vers'
        'ions.request_version_id AS request_version_id, verification_run_versions.req'
        'uest_revision AS request_revision, verification_run_versions.run_id AS run_i'
        'd, verification_run_versions.revision AS revision, verification_run_versions'
        '.previous_run_version_id AS previous_run_version_id, verification_run_versio'
        'ns.previous_revision AS previous_revision, verification_run_versions.owner_i'
        'd AS owner_id, verification_run_versions.writer_id AS writer_id, verificatio'
        'n_run_versions.visibility AS visibility, verification_run_versions.status AS'
        ' status, verification_run_versions.operation AS operation, verification_run_'
        'versions.run_snapshot AS run_snapshot, verification_run_versions.execution_p'
        'lan AS execution_plan, verification_run_versions.plan_sha256 AS plan_sha256,'
        ' verification_run_versions.input_snapshot AS input_snapshot, verification_ru'
        'n_versions.snapshot_sha256 AS snapshot_sha256, verification_run_versions.sou'
        'rces AS sources, verification_run_versions.required_source_read_set AS requi'
        'red_source_read_set, verification_run_versions.source_basis AS source_basis,'
        ' verification_run_versions.authority_snapshot AS authority_snapshot, verific'
        'ation_run_versions.intent_digest AS intent_digest, verification_run_versions'
        '.reason AS reason, verification_run_versions.id AS id, verification_run_vers'
        'ions.tenant_id AS tenant_id, verification_run_versions.created_at AS created'
        '_at, verification_run_versions.category_id AS category_id \nFROM verificatio'
        'n_run_versions \nWHERE verification_run_versions.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_pro"
        'jects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, projects.'
        'owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, pr'
        'ojects.scope AS scope, projects.visibility AS visibility, projects.status AS'
        ' status, projects.revision AS revision, projects.current_plan_id AS current_'
        'plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS trigg'
        'er_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, project'
        's.tenant_id AS tenant_id, projects.created_at AS created_at, projects.catego'
        'ry_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nulli'
        "f(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpris"
        'e_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpose'
        ' AS purpose, products.revision AS revision, products.lifecycle_epoch AS life'
        'cycle_epoch, products.status AS status, products.owner_id AS owner_id, produ'
        'cts.parent_product_id AS parent_product_id, products.category_id AS category'
        '_id, products.visibility AS visibility, products.target_price AS target_pric'
        'e, products.target_price_currency AS target_price_currency, products.target_'
        'price_basis AS target_price_basis, products.target_price_includes_tax AS tar'
        'get_price_includes_tax, products.target_price_as_of AS target_price_as_of, p'
        'roducts.id AS id, products.tenant_id AS tenant_id, products.created_at AS cr'
        'eated_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_se'
        "tting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_builds AS "
        'MATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id AS'
        ' project_id, builds.project_revision AS project_revision, builds.engineering'
        '_configuration_id AS engineering_configuration_id, builds.manufacturing_conf'
        'iguration_id AS manufacturing_configuration_id, builds.previous_build_id AS '
        'previous_build_id, builds.owner_id AS owner_id, builds.name AS name, builds.'
        'type AS type, builds.purpose AS purpose, builds.planned_quantity AS planned_'
        'quantity, builds.unit AS unit, builds.planned_start AS planned_start, builds'
        '.planned_end AS planned_end, builds.verification_objectives AS verification_'
        'objectives, builds.disposition_plan AS disposition_plan, builds.visibility A'
        'S visibility, builds.revision AS revision, builds.status AS status, builds.i'
        'd AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, bui'
        'lds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_verification_current_runs AS MATERIALIZED \n(SELECT verification_cur'
        'rent_runs.product_id AS product_id, verification_current_runs.request_id AS '
        'request_id, verification_current_runs.run_id AS run_id, verification_current'
        '_runs.run_version_id AS run_version_id, verification_current_runs.run_revisi'
        'on AS run_revision, verification_current_runs.id AS id, verification_current'
        '_runs.tenant_id AS tenant_id, verification_current_runs.created_at AS create'
        'd_at, verification_current_runs.category_id AS category_id \nFROM verificati'
        'on_current_runs \nWHERE verification_current_runs.tenant_id = CAST(nullif(cu'
        "rrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_te"
        'st_result_actions AS MATERIALIZED \n(SELECT test_result_actions.operation AS'
        ' operation, test_result_actions.actor_id AS actor_id, test_result_actions.in'
        'tent_digest AS intent_digest, test_result_actions.request_version_id AS requ'
        'est_version_id, test_result_actions.request_revision AS request_revision, te'
        'st_result_actions.next_request_version_id AS next_request_version_id, test_r'
        'esult_actions.next_request_revision AS next_request_revision, test_result_ac'
        'tions.run_version_id AS run_version_id, test_result_actions.run_revision AS '
        'run_revision, test_result_actions.next_run_version_id AS next_run_version_id'
        ', test_result_actions.next_run_revision AS next_run_revision, test_result_ac'
        'tions.capture_id AS capture_id, test_result_actions.projection_id AS project'
        'ion_id, test_result_actions.input_snapshot AS input_snapshot, test_result_ac'
        'tions.authority_snapshot AS authority_snapshot, test_result_actions.event AS'
        ' event, test_result_actions.sources AS sources, test_result_actions.required'
        '_source_read_set AS required_source_read_set, test_result_actions.source_bas'
        'is AS source_basis, test_result_actions.reason AS reason, test_result_action'
        's.product_id AS product_id, test_result_actions.project_id AS project_id, te'
        'st_result_actions.build_id AS build_id, test_result_actions.request_id AS re'
        'quest_id, test_result_actions.run_id AS run_id, test_result_actions.revision'
        ' AS revision, test_result_actions.owner_id AS owner_id, test_result_actions.'
        'visibility AS visibility, test_result_actions.status AS status, test_result_'
        'actions.id AS id, test_result_actions.tenant_id AS tenant_id, test_result_ac'
        'tions.created_at AS created_at, test_result_actions.category_id AS category_'
        'id \nFROM test_result_actions \nWHERE test_result_actions.tenant_id = CAST(n'
        "ullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritativ"
        "e_enterprise_sources_b8475898ff5f3dcb AS \n(SELECT 'test_run' AS source_type"
        ', shared_enterprise_verification_run_versions.id AS source_id, shared_enterp'
        'rise_verification_run_versions.tenant_id AS tenant_id, shared_enterprise_ver'
        'ification_run_versions.category_id AS category_id, shared_enterprise_verific'
        'ation_run_versions.product_id AS product_id, shared_enterprise_verification_'
        'run_versions.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, sh'
        'ared_enterprise_verification_run_versions.owner_id AS owner_id, shared_enter'
        "prise_verification_run_versions.revision AS source_revision, '\u6d4b\u8bd5"
        "\u8fd0\u884c \xb7 ' || CAST(shared_enterprise_verification_run_versions.run_"
        'id AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('
        "'object_id', shared_enterprise_verification_run_versions.run_id, 'kind', 'te"
        "st_run', 'facts', jsonb_build_object('id', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['id'], 'revision', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['revision'], 'request_id', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['request_id'], 'status', shared_enterprise_v"
        "erification_run_versions.run_snapshot['status'], 'result', shared_enterprise"
        "_verification_run_versions.run_snapshot['result']) || jsonb_build_object('ac"
        "tual_start', jsonb_build_object('occurred_at', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['actual_start']['occurred_at'], 'original_timezo"
        "ne', shared_enterprise_verification_run_versions.run_snapshot['actual_start'"
        "]['original_timezone'], 'effective_at', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['actual_start']['effective_at']), 'actual_end', jsonb_b"
        "uild_object('occurred_at', shared_enterprise_verification_run_versions.run_s"
        "napshot['actual_end']['occurred_at'], 'original_timezone', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_end']['original_timezone'], "
        "'effective_at', shared_enterprise_verification_run_versions.run_snapshot['ac"
        "tual_end']['effective_at']), 'preliminary_result', jsonb_build_object('occur"
        "red_at', shared_enterprise_verification_run_versions.run_snapshot['prelimina"
        "ry_result']['occurred_at'], 'original_timezone', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['preliminary_result']['original_timezone'], 'e"
        "ffective_at', shared_enterprise_verification_run_versions.run_snapshot['prel"
        "iminary_result']['effective_at']), 'final_result', jsonb_build_object('occur"
        "red_at', shared_enterprise_verification_run_versions.run_snapshot['final_res"
        "ult']['occurred_at'], 'original_timezone', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['final_result']['original_timezone'], 'effective_at'"
        ", shared_enterprise_verification_run_versions.run_snapshot['final_result']['"
        "effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_obje"
        "ct('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact_id'],"
        " 'version', enterprise_reads_test_run.value['expected_revision']) ORDER BY e"
        "nterprise_reads_test_run.value ->> 'artifact_id', enterprise_reads_test_run."
        "value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM js"
        'onb_array_elements(shared_enterprise_verification_run_versions.required_sour'
        "ce_read_set) AS enterprise_reads_test_run(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_o"
        "bject('object_id', shared_enterprise_verification_run_versions.run_id, 'kind"
        "', 'test_run', 'facts', jsonb_build_object('id', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['id'], 'revision', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['revision'], 'request_id', shared_enterprise_v"
        "erification_run_versions.run_snapshot['request_id'], 'status', shared_enterp"
        "rise_verification_run_versions.run_snapshot['status'], 'result', shared_ente"
        "rprise_verification_run_versions.run_snapshot['result']) || jsonb_build_obje"
        "ct('actual_start', jsonb_build_object('occurred_at', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['actual_start']['occurred_at'], 'original_"
        "timezone', shared_enterprise_verification_run_versions.run_snapshot['actual_"
        "start']['original_timezone'], 'effective_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['actual_start']['effective_at']), 'actual_end', j"
        "sonb_build_object('occurred_at', shared_enterprise_verification_run_versions"
        ".run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_ente"
        "rprise_verification_run_versions.run_snapshot['actual_end']['original_timezo"
        "ne'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['actual_end']['effective_at']), 'preliminary_result', jsonb_build_object("
        "'occurred_at', shared_enterprise_verification_run_versions.run_snapshot['pre"
        "liminary_result']['occurred_at'], 'original_timezone', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['preliminary_result']['original_timezone"
        "'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot"
        "['preliminary_result']['effective_at']), 'final_result', jsonb_build_object("
        "'occurred_at', shared_enterprise_verification_run_versions.run_snapshot['fin"
        "al_result']['occurred_at'], 'original_timezone', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['final_result']['original_timezone'], 'effecti"
        "ve_at', shared_enterprise_verification_run_versions.run_snapshot['final_resu"
        "lt']['effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact"
        "_id'], 'version', enterprise_reads_test_run.value['expected_revision']) ORDE"
        "R BY enterprise_reads_test_run.value ->> 'artifact_id', enterprise_reads_tes"
        "t_run.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        'ROM jsonb_array_elements(shared_enterprise_verification_run_versions.require'
        "d_source_read_set) AS enterprise_reads_test_run(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e'
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_verification_run_versions.run_id, 'kind', 'test_run', 'facts"
        "', jsonb_build_object('id', shared_enterprise_verification_run_versions.run_"
        "snapshot['id'], 'revision', shared_enterprise_verification_run_versions.run_"
        "snapshot['revision'], 'request_id', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['request_id'], 'status', shared_enterprise_verification_run"
        "_versions.run_snapshot['status'], 'result', shared_enterprise_verification_r"
        "un_versions.run_snapshot['result']) || jsonb_build_object('actual_start', js"
        "onb_build_object('occurred_at', shared_enterprise_verification_run_versions."
        "run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared_ent"
        "erprise_verification_run_versions.run_snapshot['actual_start']['original_tim"
        "ezone'], 'effective_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_start']['effective_at']), 'actual_end', jsonb_build_object('oc"
        "curred_at', shared_enterprise_verification_run_versions.run_snapshot['actual"
        "_end']['occurred_at'], 'original_timezone', shared_enterprise_verification_r"
        "un_versions.run_snapshot['actual_end']['original_timezone'], 'effective_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['actual_end']['eff"
        "ective_at']), 'preliminary_result', jsonb_build_object('occurred_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['preliminary_result']['oc"
        "curred_at'], 'original_timezone', shared_enterprise_verification_run_version"
        "s.run_snapshot['preliminary_result']['original_timezone'], 'effective_at', s"
        "hared_enterprise_verification_run_versions.run_snapshot['preliminary_result'"
        "]['effective_at']), 'final_result', jsonb_build_object('occurred_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['final_result']['occurred"
        "_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_"
        "snapshot['final_result']['original_timezone'], 'effective_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['final_result']['effective_at'])"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'art"
        "ifact', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', ent"
        "erprise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads"
        "_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expe"
        "cted_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_eleme"
        'nts(shared_enterprise_verification_run_versions.required_source_read_set) AS'
        " enterprise_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_verification_run_versi"
        "ons.visibility != 'category' OR coalesce(shared_enterprise_projects.visibili"
        "ty != 'category', false) OR coalesce(shared_enterprise_products.visibility !"
        "= 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared"
        '_enterprise_verification_run_versions.required_source_read_set) AS enterpris'
        'e_reads_test_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f'
        '3dcb ON enterprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shar'
        'ed_enterprise_verification_run_versions.tenant_id AND enterprise_authoritati'
        've_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.va'
        "lue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b"
        "8475898ff5f3dcb.private)) OR shared_enterprise_builds.visibility != 'categor"
        "y' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpris"
        'e_verification_run_versions.required_source_read_set) AS enterprise_reads_te'
        'st_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON en'
        'terprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterpr'
        'ise_verification_run_versions.tenant_id AND enterprise_authoritative_artifac'
        "ts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'a"
        "rtifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b8475898ff5"
        'f3dcb.customer_original) AS customer_original, shared_enterprise_verificatio'
        'n_current_runs.run_version_id = shared_enterprise_verification_run_versions.'
        'id AS is_current, shared_enterprise_verification_run_versions.created_at AS '
        'created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_verificatio'
        'n_run_versions.run_id AS object_id, (SELECT coalesce(array_agg(enterprise_au'
        'thoritative_artifacts_b8475898ff5f3dcb.original_id), ARRAY[]::UUID[]) AS coa'
        'lesce_2 \nFROM jsonb_array_elements(shared_enterprise_verification_run_versi'
        'ons.required_source_read_set) AS enterprise_reads_test_run(value) JOIN enter'
        'prise_authoritative_artifacts_b8475898ff5f3dcb ON enterprise_authoritative_a'
        'rtifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_verification_run_ver'
        'sions.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.sour'
        "ce_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.original_id IS NOT'
        ' NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_eleme'
        'nts(shared_enterprise_verification_run_versions.required_source_read_set) AS'
        ' enterprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_b8'
        '475898ff5f3dcb ON enterprise_authoritative_artifacts_b8475898ff5f3dcb.tenant'
        '_id = shared_enterprise_verification_run_versions.tenant_id AND enterprise_a'
        'uthoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_t'
        "est_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_a"
        'rtifacts_b8475898ff5f3dcb.source_revision != CAST((enterprise_reads_test_run'
        ".value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'cur"
        "rent' END AS read_basis_status \nFROM shared_enterprise_verification_run_ver"
        'sions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_i'
        'd = shared_enterprise_verification_run_versions.tenant_id AND shared_enterpr'
        'ise_projects.product_id = shared_enterprise_verification_run_versions.produc'
        't_id AND shared_enterprise_projects.id = shared_enterprise_verification_run_'
        'versions.project_id AND shared_enterprise_projects.category_id = shared_ente'
        'rprise_verification_run_versions.category_id JOIN shared_enterprise_products'
        ' ON shared_enterprise_products.tenant_id = shared_enterprise_verification_ru'
        'n_versions.tenant_id AND shared_enterprise_products.id = shared_enterprise_v'
        'erification_run_versions.product_id AND shared_enterprise_products.category_'
        'id = shared_enterprise_verification_run_versions.category_id JOIN shared_ent'
        'erprise_builds ON shared_enterprise_builds.tenant_id = shared_enterprise_ver'
        'ification_run_versions.tenant_id AND shared_enterprise_builds.category_id = '
        'shared_enterprise_verification_run_versions.category_id AND shared_enterpris'
        'e_builds.product_id = shared_enterprise_verification_run_versions.product_id'
        ' AND shared_enterprise_builds.project_id = shared_enterprise_verification_ru'
        'n_versions.project_id AND shared_enterprise_builds.id = shared_enterprise_ve'
        'rification_run_versions.build_id AND shared_enterprise_builds.revision = sha'
        'red_enterprise_verification_run_versions.build_revision JOIN shared_enterpri'
        'se_verification_current_runs ON shared_enterprise_verification_current_runs.'
        'tenant_id = shared_enterprise_verification_run_versions.tenant_id AND shared'
        '_enterprise_verification_current_runs.product_id = shared_enterprise_verific'
        'ation_run_versions.product_id AND shared_enterprise_verification_current_run'
        's.run_id = shared_enterprise_verification_run_versions.run_id \nWHERE shared'
        '_enterprise_verification_run_versions.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jso"
        'nb_array_elements(shared_enterprise_verification_run_versions.required_sourc'
        'e_read_set) AS enterprise_reads_test_run(value) \nWHERE NOT (EXISTS (SELECT '
        '1 \nFROM enterprise_authoritative_artifacts_b8475898ff5f3dcb \nWHERE enterpr'
        'ise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_v'
        'erification_run_versions.tenant_id AND enterprise_authoritative_artifacts_b8'
        "475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'artifa"
        "ct_id') AS UUID))))) UNION ALL SELECT 'test_run' AS source_type, shared_ente"
        'rprise_test_result_actions.id AS source_id, shared_enterprise_test_result_ac'
        'tions.tenant_id AS tenant_id, shared_enterprise_test_result_actions.category'
        '_id AS category_id, shared_enterprise_test_result_actions.product_id AS prod'
        'uct_id, shared_enterprise_test_result_actions.project_id AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, shared_enterprise_test_result_actions.owner_i'
        'd AS owner_id, shared_enterprise_test_result_actions.revision AS source_revi'
        "sion, CASE WHEN (shared_enterprise_test_result_actions.operation = 'test.run"
        ".review') THEN '\u4e13\u4e1a\u8bc4\u5ba1\u8bb0\u5f55 \xb7 ' WHEN (shared_ent"
        "erprise_test_result_actions.operation = 'test.disposition.decide') THEN '"
        "\u6d4b\u8bd5\u5904\u7f6e\u8bb0\u5f55 \xb7 ' ELSE '\u6d4b\u8bd5\u7ed3\u679c"
        "\u8bb0\u5f55 \xb7 ' END || CAST(shared_enterprise_test_result_actions.run_id"
        " AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('o"
        "bject_id', shared_enterprise_test_result_actions.run_id, 'kind', 'test_run',"
        " 'facts', (jsonb_build_object('id', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['id'], 'revision', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['revision'], 'request_id', shared_enterprise_verification_r"
        "un_versions.run_snapshot['request_id'], 'status', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['status'], 'result', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['result']) || jsonb_build_object('record_ki"
        "nd', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "sample_id', enterprise_run_coverage.value['sample_id'], 'item_id', enterpris"
        "e_run_coverage.value['item_id']) ORDER BY enterprise_run_coverage.ordinal), "
        'jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(shar'
        "ed_enterprise_verification_run_versions.run_snapshot['coverage'], CAST('[]' "
        "AS JSONB))) WITH ORDINALITY AS enterprise_run_coverage(value, ordinal)), 'co"
        "mputed_results', (SELECT coalesce(jsonb_agg(jsonb_build_object('coverage', e"
        "nterprise_computed_results.value['coverage'], 'result', enterprise_computed_"
        "results.value['result'], 'measurement_id', enterprise_computed_results.value"
        "['measurement_id']) ORDER BY enterprise_computed_results.ordinal), jsonb_bui"
        'ld_array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterp'
        "rise_verification_run_versions.run_snapshot['computed_results'], CAST('[]' A"
        'S JSONB))) WITH ORDINALITY AS enterprise_computed_results(value, ordinal)), '
        "'professional_conclusion', CASE WHEN (((shared_enterprise_verification_run_v"
        "ersions.run_snapshot['professional_conclusion']) ->> 'actor_id') IS NULL) TH"
        "EN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['professional_conclusion']['text'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['profession"
        "al_conclusion']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared"
        "_enterprise_verification_run_versions.run_snapshot['professional_conclusion'"
        "]['at']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_bui"
        "ld_object('occurred_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['professional_conclusion']['at']['occurred_at'], 'original_timezone', "
        "shared_enterprise_verification_run_versions.run_snapshot['professional_concl"
        "usion']['at']['original_timezone'], 'effective_at', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['professional_conclusion']['at']['effective"
        "_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['professional_conclusion']['at']['received_at'], 'actor_id', shared_enter"
        "prise_verification_run_versions.run_snapshot['professional_conclusion']['at'"
        "]['actor_id']) END, 'source_reference', jsonb_build_object('kind', shared_en"
        "terprise_verification_run_versions.run_snapshot['professional_conclusion']['"
        "source']['kind'], 'id', shared_enterprise_verification_run_versions.run_snap"
        "shot['professional_conclusion']['source']['id'], 'revision', shared_enterpri"
        "se_verification_run_versions.run_snapshot['professional_conclusion']['source"
        "']['revision'])) END, 'disposition', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['disposition']) ->> 'actor_id') IS NULL) THEN"
        " CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['text'], 'actor_id', shared"
        "_enterprise_verification_run_versions.run_snapshot['disposition']['actor_id'"
        "]) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_verification_r"
        "un_versions.run_snapshot['disposition']['at']) ->> 'occurred_at') IS NULL) T"
        "HEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['disposition']['at']['occurred_a"
        "t'], 'original_timezone', shared_enterprise_verification_run_versions.run_sn"
        "apshot['disposition']['at']['original_timezone'], 'effective_at', shared_ent"
        "erprise_verification_run_versions.run_snapshot['disposition']['at']['effecti"
        "ve_at'], 'received_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['disposition']['at']['received_at'], 'actor_id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['disposition']['at']['actor_id']) END, 's"
        "ource_reference', jsonb_build_object('kind', shared_enterprise_verification_"
        "run_versions.run_snapshot['disposition']['source']['kind'], 'id', shared_ent"
        "erprise_verification_run_versions.run_snapshot['disposition']['source']['id'"
        "], 'revision', shared_enterprise_verification_run_versions.run_snapshot['dis"
        "position']['source']['revision'])) END, 'actual_start', CASE WHEN (((shared_"
        "enterprise_verification_run_versions.run_snapshot['actual_start']) ->> 'occu"
        "rred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurre"
        "d_at', shared_enterprise_verification_run_versions.run_snapshot['actual_star"
        "t']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_"
        "versions.run_snapshot['actual_start']['original_timezone'], 'effective_at', "
        "shared_enterprise_verification_run_versions.run_snapshot['actual_start']['ef"
        "fective_at'], 'received_at', shared_enterprise_verification_run_versions.run"
        "_snapshot['actual_start']['received_at'], 'actor_id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['actual_start']['actor_id']) END, 'actual"
        "_end', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapshot"
        "['actual_end']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE js"
        "onb_build_object('occurred_at', shared_enterprise_verification_run_versions."
        "run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_enter"
        "prise_verification_run_versions.run_snapshot['actual_end']['original_timezon"
        "e'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['actual_end']['effective_at'], 'received_at', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['actual_end']['received_at'], 'actor_id', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_end']['actor_id'"
        "]) END, 'preliminary_result', CASE WHEN (((shared_enterprise_verification_ru"
        "n_versions.run_snapshot['preliminary_result']) ->> 'occurred_at') IS NULL) T"
        "HEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['preliminary_result']['occurred_"
        "at'], 'original_timezone', shared_enterprise_verification_run_versions.run_s"
        "napshot['preliminary_result']['original_timezone'], 'effective_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['preliminary_result']['effe"
        "ctive_at'], 'received_at', shared_enterprise_verification_run_versions.run_s"
        "napshot['preliminary_result']['received_at'], 'actor_id', shared_enterprise_"
        "verification_run_versions.run_snapshot['preliminary_result']['actor_id']) EN"
        "D, 'final_result', CASE WHEN (((shared_enterprise_verification_run_versions."
        "run_snapshot['final_result']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS "
        "JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['final_result']['occurred_at'], 'original_timezon"
        "e', shared_enterprise_verification_run_versions.run_snapshot['final_result']"
        "['original_timezone'], 'effective_at', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['final_result']['effective_at'], 'received_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['final_result']['received_a"
        "t'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['f"
        "inal_result']['actor_id']) END)) || jsonb_build_object('record_kind', 'test_"
        "result_action', 'operation', shared_enterprise_test_result_actions.operation"
        ", 'actor_id', shared_enterprise_test_result_actions.actor_id, 'run_version_i"
        "d', shared_enterprise_verification_run_versions.id, 'run_revision', shared_e"
        "nterprise_verification_run_versions.revision), 'source_refs', (SELECT coales"
        "ce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_t"
        "est_run.value['artifact_id'], 'version', enterprise_reads_test_run.value['ex"
        "pected_revision']) ORDER BY enterprise_reads_test_run.value ->> 'artifact_id"
        "', enterprise_reads_test_run.value ->> 'expected_revision'), jsonb_build_arr"
        'ay()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_test_resul'
        "t_actions.required_source_read_set) AS enterprise_reads_test_run(value)), 'r"
        "ecord_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, C"
        "AST(CAST(jsonb_build_object('object_id', shared_enterprise_test_result_actio"
        "ns.run_id, 'kind', 'test_run', 'facts', (jsonb_build_object('id', shared_ent"
        "erprise_verification_run_versions.run_snapshot['id'], 'revision', shared_ent"
        "erprise_verification_run_versions.run_snapshot['revision'], 'request_id', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['request_id'], 'statu"
        "s', shared_enterprise_verification_run_versions.run_snapshot['status'], 'res"
        "ult', shared_enterprise_verification_run_versions.run_snapshot['result']) ||"
        " jsonb_build_object('record_kind', 'test_run', 'coverage', (SELECT coalesce("
        "jsonb_agg(jsonb_build_object('sample_id', enterprise_run_coverage.value['sam"
        "ple_id'], 'item_id', enterprise_run_coverage.value['item_id']) ORDER BY ente"
        'rprise_run_coverage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM json'
        'b_array_elements(coalesce(shared_enterprise_verification_run_versions.run_sn'
        "apshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_"
        "coverage(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('coverage', enterprise_computed_results.value['coverage'], "
        "'result', enterprise_computed_results.value['result'], 'measurement_id', ent"
        "erprise_computed_results.value['measurement_id']) ORDER BY enterprise_comput"
        'ed_results.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_e'
        "lements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['c"
        "omputed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_compu"
        "ted_results(value, ordinal)), 'professional_conclusion', CASE WHEN (((shared"
        "_enterprise_verification_run_versions.run_snapshot['professional_conclusion'"
        "]) ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('text', shared_enterprise_verification_run_versions.run_snapshot['professio"
        "nal_conclusion']['text'], 'actor_id', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['professional_conclusion']['actor_id']) || jsonb_build_ob"
        "ject('at', CASE WHEN (((shared_enterprise_verification_run_versions.run_snap"
        "shot['professional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST"
        "(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['professional_conclusion']['at']['occurr"
        "ed_at'], 'original_timezone', shared_enterprise_verification_run_versions.ru"
        "n_snapshot['professional_conclusion']['at']['original_timezone'], 'effective"
        "_at', shared_enterprise_verification_run_versions.run_snapshot['professional"
        "_conclusion']['at']['effective_at'], 'received_at', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['professional_conclusion']['at']['received_"
        "at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['"
        "professional_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_"
        "build_object('kind', shared_enterprise_verification_run_versions.run_snapsho"
        "t['professional_conclusion']['source']['kind'], 'id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['professional_conclusion']['source']['id'"
        "], 'revision', shared_enterprise_verification_run_versions.run_snapshot['pro"
        "fessional_conclusion']['source']['revision'])) END, 'disposition', CASE WHEN"
        " (((shared_enterprise_verification_run_versions.run_snapshot['disposition'])"
        " ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('"
        "text', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['text'], 'actor_id', shared_enterprise_verification_run_versions.run_snap"
        "shot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((sh"
        "ared_enterprise_verification_run_versions.run_snapshot['disposition']['at'])"
        " ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_objec"
        "t('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['d"
        "isposition']['at']['occurred_at'], 'original_timezone', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['disposition']['at']['original_timezone"
        "'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot"
        "['disposition']['at']['effective_at'], 'received_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['disposition']['at']['received_at'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['dispositio"
        "n']['at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', s"
        "hared_enterprise_verification_run_versions.run_snapshot['disposition']['sour"
        "ce']['kind'], 'id', shared_enterprise_verification_run_versions.run_snapshot"
        "['disposition']['source']['id'], 'revision', shared_enterprise_verification_"
        "run_versions.run_snapshot['disposition']['source']['revision'])) END, 'actua"
        "l_start', CASE WHEN (((shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) EL"
        "SE jsonb_build_object('occurred_at', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['actual_start']['occurred_at'], 'original_timezone', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_start']['origina"
        "l_timezone'], 'effective_at', shared_enterprise_verification_run_versions.ru"
        "n_snapshot['actual_start']['effective_at'], 'received_at', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_start']['received_at'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['actual_sta"
        "rt']['actor_id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) TH"
        "EN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'or"
        "iginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['"
        "actual_end']['original_timezone'], 'effective_at', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['actual_end']['effective_at'], 'received_at'"
        ", shared_enterprise_verification_run_versions.run_snapshot['actual_end']['re"
        "ceived_at'], 'actor_id', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((sha"
        "red_enterprise_verification_run_versions.run_snapshot['preliminary_result'])"
        " ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_objec"
        "t('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['p"
        "reliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_v"
        "erification_run_versions.run_snapshot['preliminary_result']['original_timezo"
        "ne'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['preliminary_result']['effective_at'], 'received_at', shared_enterprise_v"
        "erification_run_versions.run_snapshot['preliminary_result']['received_at'], "
        "'actor_id', shared_enterprise_verification_run_versions.run_snapshot['prelim"
        "inary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterpr"
        "ise_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at"
        "') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', "
        "shared_enterprise_verification_run_versions.run_snapshot['final_result']['oc"
        "curred_at'], 'original_timezone', shared_enterprise_verification_run_version"
        "s.run_snapshot['final_result']['original_timezone'], 'effective_at', shared_"
        "enterprise_verification_run_versions.run_snapshot['final_result']['effective"
        "_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['final_result']['received_at'], 'actor_id', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_buil"
        "d_object('record_kind', 'test_result_action', 'operation', shared_enterprise"
        "_test_result_actions.operation, 'actor_id', shared_enterprise_test_result_ac"
        "tions.actor_id, 'run_version_id', shared_enterprise_verification_run_version"
        "s.id, 'run_revision', shared_enterprise_verification_run_versions.revision),"
        " 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artif"
        "act', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', enter"
        "prise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads_t"
        "est_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expect"
        "ed_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_element"
        's(shared_enterprise_test_result_actions.required_source_read_set) AS enterpr'
        "ise_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS bod"
        "y, CAST(jsonb_build_object('object_id', shared_enterprise_test_result_action"
        "s.run_id, 'kind', 'test_run', 'facts', (jsonb_build_object('id', shared_ente"
        "rprise_verification_run_versions.run_snapshot['id'], 'revision', shared_ente"
        "rprise_verification_run_versions.run_snapshot['revision'], 'request_id', sha"
        "red_enterprise_verification_run_versions.run_snapshot['request_id'], 'status"
        "', shared_enterprise_verification_run_versions.run_snapshot['status'], 'resu"
        "lt', shared_enterprise_verification_run_versions.run_snapshot['result']) || "
        "jsonb_build_object('record_kind', 'test_run', 'coverage', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('sample_id', enterprise_run_coverage.value['samp"
        "le_id'], 'item_id', enterprise_run_coverage.value['item_id']) ORDER BY enter"
        'prise_run_coverage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb'
        '_array_elements(coalesce(shared_enterprise_verification_run_versions.run_sna'
        "pshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_c"
        "overage(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('coverage', enterprise_computed_results.value['coverage'], '"
        "result', enterprise_computed_results.value['result'], 'measurement_id', ente"
        "rprise_computed_results.value['measurement_id']) ORDER BY enterprise_compute"
        'd_results.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_el'
        "ements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['co"
        "mputed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_comput"
        "ed_results(value, ordinal)), 'professional_conclusion', CASE WHEN (((shared_"
        "enterprise_verification_run_versions.run_snapshot['professional_conclusion']"
        ") ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object("
        "'text', shared_enterprise_verification_run_versions.run_snapshot['profession"
        "al_conclusion']['text'], 'actor_id', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['professional_conclusion']['actor_id']) || jsonb_build_obj"
        "ect('at', CASE WHEN (((shared_enterprise_verification_run_versions.run_snaps"
        "hot['professional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST("
        "NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['professional_conclusion']['at']['occurre"
        "d_at'], 'original_timezone', shared_enterprise_verification_run_versions.run"
        "_snapshot['professional_conclusion']['at']['original_timezone'], 'effective_"
        "at', shared_enterprise_verification_run_versions.run_snapshot['professional_"
        "conclusion']['at']['effective_at'], 'received_at', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['professional_conclusion']['at']['received_a"
        "t'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['p"
        "rofessional_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_b"
        "uild_object('kind', shared_enterprise_verification_run_versions.run_snapshot"
        "['professional_conclusion']['source']['kind'], 'id', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['professional_conclusion']['source']['id']"
        ", 'revision', shared_enterprise_verification_run_versions.run_snapshot['prof"
        "essional_conclusion']['source']['revision'])) END, 'disposition', CASE WHEN "
        "(((shared_enterprise_verification_run_versions.run_snapshot['disposition']) "
        "->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('t"
        "ext', shared_enterprise_verification_run_versions.run_snapshot['disposition'"
        "]['text'], 'actor_id', shared_enterprise_verification_run_versions.run_snaps"
        "hot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((sha"
        "red_enterprise_verification_run_versions.run_snapshot['disposition']['at']) "
        "->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['di"
        "sposition']['at']['occurred_at'], 'original_timezone', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['disposition']['at']['original_timezone'"
        "], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot["
        "'disposition']['at']['effective_at'], 'received_at', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['at']['received_at'], 'acto"
        "r_id', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['disposition']['sourc"
        "e']['kind'], 'id', shared_enterprise_verification_run_versions.run_snapshot["
        "'disposition']['source']['id'], 'revision', shared_enterprise_verification_r"
        "un_versions.run_snapshot['disposition']['source']['revision'])) END, 'actual"
        "_start', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapsh"
        "ot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELS"
        "E jsonb_build_object('occurred_at', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared"
        "_enterprise_verification_run_versions.run_snapshot['actual_start']['original"
        "_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run"
        "_snapshot['actual_start']['effective_at'], 'received_at', shared_enterprise_"
        "verification_run_versions.run_snapshot['actual_start']['received_at'], 'acto"
        "r_id', shared_enterprise_verification_run_versions.run_snapshot['actual_star"
        "t']['actor_id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) THE"
        "N CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpri"
        "se_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'ori"
        "ginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['a"
        "ctual_end']['original_timezone'], 'effective_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['actual_end']['effective_at'], 'received_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['actual_end']['rec"
        "eived_at'], 'actor_id', shared_enterprise_verification_run_versions.run_snap"
        "shot['actual_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((shar"
        "ed_enterprise_verification_run_versions.run_snapshot['preliminary_result']) "
        "->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['pr"
        "eliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['preliminary_result']['original_timezon"
        "e'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['preliminary_result']['effective_at'], 'received_at', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['preliminary_result']['received_at'], '"
        "actor_id', shared_enterprise_verification_run_versions.run_snapshot['prelimi"
        "nary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterpri"
        "se_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at'"
        ") IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', s"
        "hared_enterprise_verification_run_versions.run_snapshot['final_result']['occ"
        "urred_at'], 'original_timezone', shared_enterprise_verification_run_versions"
        ".run_snapshot['final_result']['original_timezone'], 'effective_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['final_result']['effective_"
        "at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['final_result']['received_at'], 'actor_id', shared_enterprise_verification"
        "_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_build"
        "_object('record_kind', 'test_result_action', 'operation', shared_enterprise_"
        "test_result_actions.operation, 'actor_id', shared_enterprise_test_result_act"
        "ions.actor_id, 'run_version_id', shared_enterprise_verification_run_versions"
        ".id, 'run_revision', shared_enterprise_verification_run_versions.revision), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', enterp"
        "rise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads_te"
        "st_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expecte"
        "d_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements"
        '(shared_enterprise_test_result_actions.required_source_read_set) AS enterpri'
        "se_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_test_result_actions.visibility != "
        "'category' OR coalesce(shared_enterprise_projects.visibility != 'category', "
        "false) OR coalesce(shared_enterprise_products.visibility != 'category', fals"
        'e) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_test_r'
        'esult_actions.required_source_read_set) AS enterprise_reads_test_run(value) '
        'JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON enterprise_autho'
        'ritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_test_resul'
        't_actions.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.'
        "source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.private)) OR s'
        "hared_enterprise_verification_run_versions.visibility != 'category' OR share"
        "d_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_test_result_actions.required_sou'
        'rce_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritat'
        'ive_artifacts_b8475898ff5f3dcb ON enterprise_authoritative_artifacts_b847589'
        '8ff5f3dcb.tenant_id = shared_enterprise_test_result_actions.tenant_id AND en'
        'terprise_authoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterpri'
        "se_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_autho"
        'ritative_artifacts_b8475898ff5f3dcb.customer_original) AS customer_original,'
        ' shared_enterprise_verification_current_runs.run_version_id = shared_enterpr'
        'ise_test_result_actions.next_run_version_id AS is_current, shared_enterprise'
        '_test_result_actions.created_at AS created_at, CAST(NULL AS UUID) AS origina'
        'l_id, shared_enterprise_test_result_actions.run_id AS object_id, (SELECT coa'
        'lesce(array_agg(enterprise_authoritative_artifacts_b8475898ff5f3dcb.original'
        '_id), ARRAY[]::UUID[]) AS coalesce_6 \nFROM jsonb_array_elements(shared_ente'
        'rprise_test_result_actions.required_source_read_set) AS enterprise_reads_tes'
        't_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON ent'
        'erprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterpri'
        'se_test_result_actions.tenant_id AND enterprise_authoritative_artifacts_b847'
        "5898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact"
        "_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.o"
        'riginal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM '
        'jsonb_array_elements(shared_enterprise_test_result_actions.required_source_r'
        'ead_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative_a'
        'rtifacts_b8475898ff5f3dcb ON enterprise_authoritative_artifacts_b8475898ff5f'
        '3dcb.tenant_id = shared_enterprise_test_result_actions.tenant_id AND enterpr'
        'ise_authoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_re'
        "ads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritat"
        'ive_artifacts_b8475898ff5f3dcb.source_revision != CAST((enterprise_reads_tes'
        "t_run.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE"
        " 'current' END AS read_basis_status \nFROM shared_enterprise_test_result_act"
        'ions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id'
        ' = shared_enterprise_test_result_actions.tenant_id AND shared_enterprise_pro'
        'jects.product_id = shared_enterprise_test_result_actions.product_id AND shar'
        'ed_enterprise_projects.id = shared_enterprise_test_result_actions.project_id'
        ' AND shared_enterprise_projects.category_id = shared_enterprise_test_result_'
        'actions.category_id JOIN shared_enterprise_products ON shared_enterprise_pro'
        'ducts.tenant_id = shared_enterprise_test_result_actions.tenant_id AND shared'
        '_enterprise_products.id = shared_enterprise_test_result_actions.product_id A'
        'ND shared_enterprise_products.category_id = shared_enterprise_test_result_ac'
        'tions.category_id JOIN shared_enterprise_verification_run_versions ON shared'
        '_enterprise_verification_run_versions.tenant_id = shared_enterprise_test_res'
        'ult_actions.tenant_id AND shared_enterprise_verification_run_versions.catego'
        'ry_id = shared_enterprise_test_result_actions.category_id AND shared_enterpr'
        'ise_verification_run_versions.product_id = shared_enterprise_test_result_act'
        'ions.product_id AND shared_enterprise_verification_run_versions.project_id ='
        ' shared_enterprise_test_result_actions.project_id AND shared_enterprise_veri'
        'fication_run_versions.build_id = shared_enterprise_test_result_actions.build'
        '_id AND shared_enterprise_verification_run_versions.run_id = shared_enterpri'
        'se_test_result_actions.run_id AND shared_enterprise_verification_run_version'
        's.id = shared_enterprise_test_result_actions.next_run_version_id AND shared_'
        'enterprise_verification_run_versions.revision = shared_enterprise_test_resul'
        't_actions.next_run_revision JOIN shared_enterprise_builds ON shared_enterpri'
        'se_builds.tenant_id = shared_enterprise_test_result_actions.tenant_id AND sh'
        'ared_enterprise_builds.category_id = shared_enterprise_test_result_actions.c'
        'ategory_id AND shared_enterprise_builds.product_id = shared_enterprise_test_'
        'result_actions.product_id AND shared_enterprise_builds.project_id = shared_e'
        'nterprise_test_result_actions.project_id AND shared_enterprise_builds.id = s'
        'hared_enterprise_test_result_actions.build_id AND shared_enterprise_builds.r'
        'evision = shared_enterprise_verification_run_versions.build_revision JOIN sh'
        'ared_enterprise_verification_current_runs ON shared_enterprise_verification_'
        'current_runs.tenant_id = shared_enterprise_test_result_actions.tenant_id AND'
        ' shared_enterprise_verification_current_runs.product_id = shared_enterprise_'
        'test_result_actions.product_id AND shared_enterprise_verification_current_ru'
        'ns.run_id = shared_enterprise_test_result_actions.run_id \nWHERE shared_ente'
        "rprise_test_result_actions.tenant_id = CAST(nullif(current_setting('pdos.ten"
        "ant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_el"
        'ements(shared_enterprise_test_result_actions.required_source_read_set) AS en'
        'terprise_reads_test_run(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterpri'
        'se_authoritative_artifacts_b8475898ff5f3dcb \nWHERE enterprise_authoritative'
        '_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_test_result_action'
        's.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.source_i'
        "d = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID))))))\n"
        ' SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_b8475898ff5'
        'f3dcb \nWHERE authoritative_enterprise_sources_b8475898ff5f3dcb.tenant_id = '
        't AND authoritative_enterprise_sources_b8475898ff5f3dcb.category_id = c AND '
        'CAST(authoritative_enterprise_sources_b8475898ff5f3dcb.source_id AS TEXT) = '
        "expected->>'source_id' AND CAST(authoritative_enterprise_sources_b8475898ff5"
        "f3dcb.source_revision AS TEXT) = expected->>'source_revision' AND authoritat"
        "ive_enterprise_sources_b8475898ff5f3dcb.content_hash = expected->>'content_h"
        "ash') AS anon_1 INTO visible;\n WHEN 'field_feedback' THEN\n  WITH enterpris"
        "e_authoritative_artifacts_83b71844b30b68bc AS \n(SELECT 'artifact' AS source"
        '_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS ten'
        'ant_id, artifact_versions.category_id AS category_id, artifact_versions.prod'
        'uct_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) A'
        'S proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.rev'
        'ision AS source_revision, artifact_versions.title AS title, artifact_version'
        's.content_hash AS content_hash, artifact_versions.content AS body, CAST(NULL'
        " AS JSONB) AS structured, 'untrusted' AS nature, artifact_versions.visibilit"
        "y != 'category' OR coalesce(products.visibility != 'category', false) OR coa"
        "lesce(uploaded_originals.visibility != 'category', false) AS private, artifa"
        'ct_versions.original_id IS NOT NULL AS customer_original, true AS is_current'
        ', artifact_versions.created_at AS created_at, artifact_versions.original_id '
        'AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versi'
        'ons.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE '
        "ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM a"
        'rtifact_versions LEFT OUTER JOIN products ON products.tenant_id = artifact_v'
        'ersions.tenant_id AND products.id = artifact_versions.product_id LEFT OUTER '
        'JOIN uploaded_originals ON uploaded_originals.tenant_id = artifact_versions.'
        'tenant_id AND uploaded_originals.id = artifact_versions.original_id AND uplo'
        'aded_originals.category_id = artifact_versions.category_id AND uploaded_orig'
        'inals.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTE'
        'R JOIN original_security ON original_security.tenant_id = uploaded_originals'
        '.tenant_id AND original_security.original_id = uploaded_originals.id \nWHERE'
        " artifact_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id',"
        " true), '') AS UUID) AND artifact_versions.status = 'active' AND artifact_ve"
        'rsions.category_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR '
        'products.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploa'
        "ded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND up"
        "loaded_originals.scan_status = 'clean' AND original_security.source_state = "
        "'active' AND original_security.disposition = 'active' AND original_security."
        'current_request_id IS NOT NULL)), \nshared_enterprise_field_feedback_version'
        's AS MATERIALIZED \n(SELECT field_feedback_versions.feedback_id AS feedback_'
        'id, field_feedback_versions.previous_id AS previous_id, field_feedback_versi'
        'ons.previous_revision AS previous_revision, field_feedback_versions.revision'
        ' AS revision, field_feedback_versions.writer_id AS writer_id, field_feedback'
        '_versions.actor_id AS actor_id, field_feedback_versions.requester_id AS requ'
        'ester_id, field_feedback_versions.operation AS operation, field_feedback_ver'
        'sions.command_id AS command_id, field_feedback_versions.command AS command, '
        'field_feedback_versions.sources AS sources, field_feedback_versions.reads AS'
        ' reads, field_feedback_versions.source_basis AS source_basis, field_feedback'
        '_versions.body AS body, field_feedback_versions.body_sha256 AS body_sha256, '
        'field_feedback_versions.intent_digest AS intent_digest, field_feedback_versi'
        'ons.request_digest AS request_digest, field_feedback_versions.receipt_id AS '
        'receipt_id, field_feedback_versions.confirmation_id AS confirmation_id, fiel'
        'd_feedback_versions.category_id AS category_id, field_feedback_versions.prod'
        'uct_id AS product_id, field_feedback_versions.project_id AS project_id, fiel'
        'd_feedback_versions.owner_id AS owner_id, field_feedback_versions.visibility'
        ' AS visibility, field_feedback_versions.id AS id, field_feedback_versions.te'
        'nant_id AS tenant_id, field_feedback_versions.created_at AS created_at \nFRO'
        'M field_feedback_versions \nWHERE field_feedback_versions.tenant_id = CAST(n'
        "ullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enter"
        'prise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, '
        'projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS pu'
        'rpose, projects.scope AS scope, projects.visibility AS visibility, projects.'
        'status AS status, projects.revision AS revision, projects.current_plan_id AS'
        ' current_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id'
        ' AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id'
        ', projects.tenant_id AS tenant_id, projects.created_at AS created_at, projec'
        'ts.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = C'
        "AST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_"
        'enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, product'
        's.purpose AS purpose, products.revision AS revision, products.lifecycle_epoc'
        'h AS lifecycle_epoch, products.status AS status, products.owner_id AS owner_'
        'id, products.parent_product_id AS parent_product_id, products.category_id AS'
        ' category_id, products.visibility AS visibility, products.target_price AS ta'
        'rget_price, products.target_price_currency AS target_price_currency, product'
        's.target_price_basis AS target_price_basis, products.target_price_includes_t'
        'ax AS target_price_includes_tax, products.target_price_as_of AS target_price'
        '_as_of, products.id AS id, products.tenant_id AS tenant_id, products.created'
        '_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_f"
        'ield_feedback_currents AS MATERIALIZED \n(SELECT field_feedback_currents.fee'
        'dback_id AS feedback_id, field_feedback_currents.version_id AS version_id, f'
        'ield_feedback_currents.revision AS revision, field_feedback_currents.categor'
        'y_id AS category_id, field_feedback_currents.product_id AS product_id, field'
        '_feedback_currents.project_id AS project_id, field_feedback_currents.owner_i'
        'd AS owner_id, field_feedback_currents.visibility AS visibility, field_feedb'
        'ack_currents.id AS id, field_feedback_currents.tenant_id AS tenant_id, field'
        '_feedback_currents.created_at AS created_at \nFROM field_feedback_currents '
        "\nWHERE field_feedback_currents.tenant_id = CAST(nullif(current_setting('pdo"
        "s.tenant_id', true), '') AS UUID)), \nshared_enterprise_field_response_recor"
        'ds AS MATERIALIZED \n(SELECT field_response_records.feedback_id AS feedback_'
        'id, field_response_records.feedback_version_id AS feedback_version_id, field'
        '_response_records.feedback_revision AS feedback_revision, field_response_rec'
        'ords.response_kind AS response_kind, field_response_records.revision AS revi'
        'sion, field_response_records.writer_id AS writer_id, field_response_records.'
        'actor_id AS actor_id, field_response_records.requester_id AS requester_id, f'
        'ield_response_records.operation AS operation, field_response_records.command'
        '_id AS command_id, field_response_records.command AS command, field_response'
        '_records.sources AS sources, field_response_records.reads AS reads, field_re'
        'sponse_records.source_basis AS source_basis, field_response_records.body AS '
        'body, field_response_records.body_sha256 AS body_sha256, field_response_reco'
        'rds.intent_digest AS intent_digest, field_response_records.request_digest AS'
        ' request_digest, field_response_records.receipt_id AS receipt_id, field_resp'
        'onse_records.confirmation_id AS confirmation_id, field_response_records.cate'
        'gory_id AS category_id, field_response_records.product_id AS product_id, fie'
        'ld_response_records.project_id AS project_id, field_response_records.owner_i'
        'd AS owner_id, field_response_records.visibility AS visibility, field_respon'
        'se_records.id AS id, field_response_records.tenant_id AS tenant_id, field_re'
        'sponse_records.created_at AS created_at \nFROM field_response_records \nWHER'
        "E field_response_records.tenant_id = CAST(nullif(current_setting('pdos.tenan"
        "t_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_83b71844b30b"
        "68bc AS \n(SELECT 'field_feedback' AS source_type, shared_enterprise_field_f"
        'eedback_versions.id AS source_id, shared_enterprise_field_feedback_versions.'
        'tenant_id AS tenant_id, shared_enterprise_field_feedback_versions.category_i'
        'd AS category_id, shared_enterprise_field_feedback_versions.product_id AS pr'
        'oduct_id, shared_enterprise_field_feedback_versions.project_id AS project_id'
        ', CAST(NULL AS UUID) AS proposal_id, shared_enterprise_field_feedback_versio'
        'ns.owner_id AS owner_id, shared_enterprise_field_feedback_versions.revision '
        "AS source_revision, shared_enterprise_field_feedback_versions.body ->> 'titl"
        "e' AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_field_feedback_versions.feedback_id, 'kind', 'field_fe"
        "edback', 'facts', jsonb_build_object('record_kind', 'field_feedback', 'opera"
        "tion', shared_enterprise_field_feedback_versions.operation, 'feedback_id', s"
        "hared_enterprise_field_feedback_versions.feedback_id, 'feedback_revision', s"
        "hared_enterprise_field_feedback_versions.revision, 'title', shared_enterpris"
        "e_field_feedback_versions.body['title'], 'description', shared_enterprise_fi"
        "eld_feedback_versions.body['description'], 'channel', shared_enterprise_fiel"
        "d_feedback_versions.body['channel'], 'feedback_kind', shared_enterprise_fiel"
        "d_feedback_versions.body['feedback_kind'], 'reported', shared_enterprise_fie"
        "ld_feedback_versions.body['reported'], 'received_at', shared_enterprise_fiel"
        "d_feedback_versions.body['received_at'], 'purpose', shared_enterprise_field_"
        "feedback_versions.body['purpose'], 'location', shared_enterprise_field_feedb"
        "ack_versions.body['location'], 'location_status', CASE WHEN (((shared_enterp"
        "rise_field_feedback_versions.body['location']) ->> 'state') = 'known') THEN "
        "'known' ELSE 'unknown' END, 'continuation_permission', 'not_evaluated', 'rec"
        "ord_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001"
        '\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1'
        '\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe'
        "\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002'), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_field_feedback.value['artifact_id'], 'version', "
        "enterprise_reads_field_feedback.value['expected_revision']) ORDER BY enterpr"
        "ise_reads_field_feedback.value ->> 'artifact_id', enterprise_reads_field_fee"
        "dback.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        "ROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('arti"
        "fact_id', field_basis_field_feedback_versions.value['id'], 'expected_revisio"
        "n', field_basis_field_feedback_versions.value['revision'])), jsonb_build_arr"
        'ay()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field_feed'
        "back_versions.source_basis['artifacts']) AS field_basis_field_feedback_versi"
        "ons(value))) AS enterprise_reads_field_feedback(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e'
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jso"
        "nb_build_object('object_id', shared_enterprise_field_feedback_versions.feedb"
        "ack_id, 'kind', 'field_feedback', 'facts', jsonb_build_object('record_kind',"
        " 'field_feedback', 'operation', shared_enterprise_field_feedback_versions.op"
        "eration, 'feedback_id', shared_enterprise_field_feedback_versions.feedback_i"
        "d, 'feedback_revision', shared_enterprise_field_feedback_versions.revision, "
        "'title', shared_enterprise_field_feedback_versions.body['title'], 'descripti"
        "on', shared_enterprise_field_feedback_versions.body['description'], 'channel"
        "', shared_enterprise_field_feedback_versions.body['channel'], 'feedback_kind"
        "', shared_enterprise_field_feedback_versions.body['feedback_kind'], 'reporte"
        "d', shared_enterprise_field_feedback_versions.body['reported'], 'received_at"
        "', shared_enterprise_field_feedback_versions.body['received_at'], 'purpose',"
        " shared_enterprise_field_feedback_versions.body['purpose'], 'location', shar"
        "ed_enterprise_field_feedback_versions.body['location'], 'location_status', C"
        "ASE WHEN (((shared_enterprise_field_feedback_versions.body['location']) ->> "
        "'state') = 'known') THEN 'known' ELSE 'unknown' END, 'continuation_permissio"
        "n', 'not_evaluated', 'record_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0"
        '\u7684\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b'
        '\u5ba2\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6'
        '\u653e\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd'
        "\u6216\u590d\u9a8c\u3002'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('type', 'artifact', 'id', enterprise_reads_field_feedback.value"
        "['artifact_id'], 'version', enterprise_reads_field_feedback.value['expected_"
        "revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact_id'"
        ", enterprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_buil"
        'd_array()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_'
        "agg(jsonb_build_object('artifact_id', field_basis_field_feedback_versions.va"
        "lue['id'], 'expected_revision', field_basis_field_feedback_versions.value['r"
        "evision'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements("
        "shared_enterprise_field_feedback_versions.source_basis['artifacts']) AS fiel"
        'd_basis_field_feedback_versions(value))) AS enterprise_reads_field_feedback('
        "value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_buil"
        "d_object('object_id', shared_enterprise_field_feedback_versions.feedback_id,"
        " 'kind', 'field_feedback', 'facts', jsonb_build_object('record_kind', 'field"
        "_feedback', 'operation', shared_enterprise_field_feedback_versions.operation"
        ", 'feedback_id', shared_enterprise_field_feedback_versions.feedback_id, 'fee"
        "dback_revision', shared_enterprise_field_feedback_versions.revision, 'title'"
        ", shared_enterprise_field_feedback_versions.body['title'], 'description', sh"
        "ared_enterprise_field_feedback_versions.body['description'], 'channel', shar"
        "ed_enterprise_field_feedback_versions.body['channel'], 'feedback_kind', shar"
        "ed_enterprise_field_feedback_versions.body['feedback_kind'], 'reported', sha"
        "red_enterprise_field_feedback_versions.body['reported'], 'received_at', shar"
        "ed_enterprise_field_feedback_versions.body['received_at'], 'purpose', shared"
        "_enterprise_field_feedback_versions.body['purpose'], 'location', shared_ente"
        "rprise_field_feedback_versions.body['location'], 'location_status', CASE WHE"
        "N (((shared_enterprise_field_feedback_versions.body['location']) ->> 'state'"
        ") = 'known') THEN 'known' ELSE 'unknown' END, 'continuation_permission', 'no"
        "t_evaluated', 'record_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684"
        '\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2'
        '\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e'
        '\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216'
        "\u590d\u9a8c\u3002'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_"
        "object('type', 'artifact', 'id', enterprise_reads_field_feedback.value['arti"
        "fact_id'], 'version', enterprise_reads_field_feedback.value['expected_revisi"
        "on']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact_id', ente"
        "rprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_build_arra"
        'y()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(js'
        "onb_build_object('artifact_id', field_basis_field_feedback_versions.value['i"
        "d'], 'expected_revision', field_basis_field_feedback_versions.value['revisio"
        "n'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared"
        "_enterprise_field_feedback_versions.source_basis['artifacts']) AS field_basi"
        's_field_feedback_versions(value))) AS enterprise_reads_field_feedback(value)'
        "), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'untrusted' AS nature, s"
        "hared_enterprise_field_feedback_versions.visibility != 'category' OR coalesc"
        "e(shared_enterprise_projects.visibility != 'category', false) OR coalesce(sh"
        "ared_enterprise_products.visibility != 'category', false) OR (EXISTS (SELECT"
        ' 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object'
        "('artifact_id', field_basis_field_feedback_versions.value['id'], 'expected_r"
        "evision', field_basis_field_feedback_versions.value['revision'])), jsonb_bui"
        'ld_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_fiel'
        "d_feedback_versions.source_basis['artifacts']) AS field_basis_field_feedback"
        '_versions(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise'
        '_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifa'
        'cts_83b71844b30b68bc.tenant_id = shared_enterprise_field_feedback_versions.t'
        'enant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id ='
        " CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nW"
        'HERE enterprise_authoritative_artifacts_83b71844b30b68bc.private)) AS privat'
        'e, (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg('
        "jsonb_build_object('artifact_id', field_basis_field_feedback_versions.value["
        "'id'], 'expected_revision', field_basis_field_feedback_versions.value['revis"
        "ion'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shar"
        "ed_enterprise_field_feedback_versions.source_basis['artifacts']) AS field_ba"
        'sis_field_feedback_versions(value))) AS enterprise_reads_field_feedback(valu'
        'e) JOIN enterprise_authoritative_artifacts_83b71844b30b68bc ON enterprise_au'
        'thoritative_artifacts_83b71844b30b68bc.tenant_id = shared_enterprise_field_f'
        'eedback_versions.tenant_id AND enterprise_authoritative_artifacts_83b71844b3'
        "0b68bc.source_id = CAST((enterprise_reads_field_feedback.value ->> 'artifact"
        "_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.c"
        "ustomer_original)) OR (shared_enterprise_field_feedback_versions.body ->> 'c"
        "hannel') = 'customer' AS customer_original, shared_enterprise_field_feedback"
        '_currents.version_id = shared_enterprise_field_feedback_versions.id AS is_cu'
        'rrent, shared_enterprise_field_feedback_versions.created_at AS created_at, C'
        'AST(NULL AS UUID) AS original_id, shared_enterprise_field_feedback_versions.'
        'feedback_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritativ'
        'e_artifacts_83b71844b30b68bc.original_id), ARRAY[]::UUID[]) AS coalesce_3 \n'
        "FROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('art"
        "ifact_id', field_basis_field_feedback_versions.value['id'], 'expected_revisi"
        "on', field_basis_field_feedback_versions.value['revision'])), jsonb_build_ar"
        'ray()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field_fee'
        "dback_versions.source_basis['artifacts']) AS field_basis_field_feedback_vers"
        'ions(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise_auth'
        'oritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifacts_8'
        '3b71844b30b68bc.tenant_id = shared_enterprise_field_feedback_versions.tenant'
        '_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id = CAST'
        "((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nWHERE "
        'enterprise_authoritative_artifacts_83b71844b30b68bc.original_id IS NOT NULL)'
        ' AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements((S'
        "ELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field"
        "_feedback_versions.value['id'], 'expected_revision', field_basis_field_feedb"
        "ack_versions.value['revision'])), jsonb_build_array()) AS coalesce_2 \nFROM "
        'jsonb_array_elements(shared_enterprise_field_feedback_versions.source_basis['
        "'artifacts']) AS field_basis_field_feedback_versions(value))) AS enterprise_"
        'reads_field_feedback(value) JOIN enterprise_authoritative_artifacts_83b71844'
        'b30b68bc ON enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = '
        'shared_enterprise_field_feedback_versions.tenant_id AND enterprise_authorita'
        'tive_artifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_fee'
        "dback.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_art"
        'ifacts_83b71844b30b68bc.source_revision != CAST((enterprise_reads_field_feed'
        "back.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE "
        "'current' END AS read_basis_status \nFROM shared_enterprise_field_feedback_v"
        'ersions LEFT OUTER JOIN shared_enterprise_projects ON shared_enterprise_proj'
        'ects.tenant_id = shared_enterprise_field_feedback_versions.tenant_id AND sha'
        'red_enterprise_projects.product_id = shared_enterprise_field_feedback_versio'
        'ns.product_id AND shared_enterprise_projects.id = shared_enterprise_field_fe'
        'edback_versions.project_id AND shared_enterprise_projects.category_id = shar'
        'ed_enterprise_field_feedback_versions.category_id LEFT OUTER JOIN shared_ent'
        'erprise_products ON shared_enterprise_products.tenant_id = shared_enterprise'
        '_field_feedback_versions.tenant_id AND shared_enterprise_products.id = share'
        'd_enterprise_field_feedback_versions.product_id AND shared_enterprise_produc'
        'ts.category_id = shared_enterprise_field_feedback_versions.category_id JOIN '
        'shared_enterprise_field_feedback_currents ON shared_enterprise_field_feedbac'
        'k_currents.tenant_id = shared_enterprise_field_feedback_versions.tenant_id A'
        'ND shared_enterprise_field_feedback_currents.category_id = shared_enterprise'
        '_field_feedback_versions.category_id AND shared_enterprise_field_feedback_cu'
        'rrents.feedback_id = shared_enterprise_field_feedback_versions.feedback_id '
        '\nWHERE shared_enterprise_field_feedback_versions.tenant_id = CAST(nullif(cu'
        "rrent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT "
        '1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('
        "'artifact_id', field_basis_field_feedback_versions.value['id'], 'expected_re"
        "vision', field_basis_field_feedback_versions.value['revision'])), jsonb_buil"
        'd_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field'
        "_feedback_versions.source_basis['artifacts']) AS field_basis_field_feedback_"
        'versions(value))) AS enterprise_reads_field_feedback(value) \nWHERE NOT (EXI'
        'STS (SELECT 1 \nFROM enterprise_authoritative_artifacts_83b71844b30b68bc \nW'
        'HERE enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = shared_'
        'enterprise_field_feedback_versions.tenant_id AND enterprise_authoritative_ar'
        'tifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_feedback.v'
        "alue ->> 'artifact_id') AS UUID))))) AND (shared_enterprise_field_feedback_v"
        'ersions.product_id IS NULL OR shared_enterprise_products.id IS NOT NULL) AND'
        ' (shared_enterprise_field_feedback_versions.project_id IS NULL OR shared_ent'
        "erprise_projects.id IS NOT NULL) UNION ALL SELECT 'field_feedback' AS source"
        '_type, shared_enterprise_field_response_records.id AS source_id, shared_ente'
        'rprise_field_response_records.tenant_id AS tenant_id, shared_enterprise_fiel'
        'd_response_records.category_id AS category_id, shared_enterprise_field_respo'
        'nse_records.product_id AS product_id, shared_enterprise_field_response_recor'
        'ds.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enter'
        'prise_field_response_records.owner_id AS owner_id, shared_enterprise_field_r'
        "esponse_records.revision AS source_revision, '\u73b0\u573a\u53cd\u9988\u8ddf"
        "\u8fdb \xb7 ' || CAST(shared_enterprise_field_response_records.response_kind"
        " AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('o"
        "bject_id', shared_enterprise_field_response_records.feedback_id, 'kind', 'fi"
        "eld_feedback', 'facts', jsonb_build_object('record_kind', 'field_response', "
        "'operation', shared_enterprise_field_response_records.operation, 'feedback_i"
        "d', shared_enterprise_field_response_records.feedback_id, 'feedback_version_"
        "id', shared_enterprise_field_response_records.feedback_version_id, 'feedback"
        "_revision', shared_enterprise_field_response_records.feedback_revision, 'res"
        "ponse_kind', shared_enterprise_field_response_records.response_kind, 'descri"
        "ption', shared_enterprise_field_response_records.body['description'], 'occur"
        "red_at', shared_enterprise_field_response_records.body['occurred_at'], 'resu"
        "lt_receipts', shared_enterprise_field_response_records.body['result_receipts"
        "'], 'actor_id', shared_enterprise_field_response_records.actor_id, 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a"
        '\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e'
        '\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5'
        "\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'contin"
        "uation_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_"
        "agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_field_feed"
        "back.value['artifact_id'], 'version', enterprise_reads_field_feedback.value["
        "'expected_revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'ar"
        "tifact_id', enterprise_reads_field_feedback.value ->> 'expected_revision'), "
        'jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements((SELECT coale'
        "sce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field_response_r"
        "ecords.value['id'], 'expected_revision', field_basis_field_response_records."
        "value['revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_e"
        "lements(shared_enterprise_field_response_records.source_basis['artifacts']) "
        'AS field_basis_field_response_records(value))) AS enterprise_reads_field_fee'
        "dback(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') "
        "AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise"
        "_field_response_records.feedback_id, 'kind', 'field_feedback', 'facts', json"
        "b_build_object('record_kind', 'field_response', 'operation', shared_enterpri"
        "se_field_response_records.operation, 'feedback_id', shared_enterprise_field_"
        "response_records.feedback_id, 'feedback_version_id', shared_enterprise_field"
        "_response_records.feedback_version_id, 'feedback_revision', shared_enterpris"
        "e_field_response_records.feedback_revision, 'response_kind', shared_enterpri"
        "se_field_response_records.response_kind, 'description', shared_enterprise_fi"
        "eld_response_records.body['description'], 'occurred_at', shared_enterprise_f"
        "ield_response_records.body['occurred_at'], 'result_receipts', shared_enterpr"
        "ise_field_response_records.body['result_receipts'], 'actor_id', shared_enter"
        "prise_field_response_records.actor_id, 'record_policy', '\u4ec5\u8868\u793a"
        '\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb'
        '\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e'
        '\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3'
        "\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'continuation_permission', 'not"
        "_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "type', 'artifact', 'id', enterprise_reads_field_feedback.value['artifact_id'"
        "], 'version', enterprise_reads_field_feedback.value['expected_revision']) OR"
        "DER BY enterprise_reads_field_feedback.value ->> 'artifact_id', enterprise_r"
        "eads_field_feedback.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_4 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_buil'
        "d_object('artifact_id', field_basis_field_response_records.value['id'], 'exp"
        "ected_revision', field_basis_field_response_records.value['revision'])), jso"
        'nb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterpris'
        "e_field_response_records.source_basis['artifacts']) AS field_basis_field_res"
        "ponse_records(value))) AS enterprise_reads_field_feedback(value)), 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_field_response_records.feedback_id, 'kind', 'field_fee"
        "dback', 'facts', jsonb_build_object('record_kind', 'field_response', 'operat"
        "ion', shared_enterprise_field_response_records.operation, 'feedback_id', sha"
        "red_enterprise_field_response_records.feedback_id, 'feedback_version_id', sh"
        "ared_enterprise_field_response_records.feedback_version_id, 'feedback_revisi"
        "on', shared_enterprise_field_response_records.feedback_revision, 'response_k"
        "ind', shared_enterprise_field_response_records.response_kind, 'description',"
        " shared_enterprise_field_response_records.body['description'], 'occurred_at'"
        ", shared_enterprise_field_response_records.body['occurred_at'], 'result_rece"
        "ipts', shared_enterprise_field_response_records.body['result_receipts'], 'ac"
        "tor_id', shared_enterprise_field_response_records.actor_id, 'record_policy',"
        " '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a\u4f4d"
        '\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e\u627f'
        '\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5\u7ed3'
        "\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'continuation"
        "_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_field_feedback.v"
        "alue['artifact_id'], 'version', enterprise_reads_field_feedback.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact"
        "_id', enterprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_"
        'build_array()) AS coalesce_4 \nFROM jsonb_array_elements((SELECT coalesce(js'
        "onb_agg(jsonb_build_object('artifact_id', field_basis_field_response_records"
        ".value['id'], 'expected_revision', field_basis_field_response_records.value["
        "'revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_element"
        "s(shared_enterprise_field_response_records.source_basis['artifacts']) AS fie"
        'ld_basis_field_response_records(value))) AS enterprise_reads_field_feedback('
        "value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS na"
        "ture, shared_enterprise_field_response_records.visibility != 'category' OR c"
        "oalesce(shared_enterprise_projects.visibility != 'category', false) OR coale"
        "sce(shared_enterprise_products.visibility != 'category', false) OR (EXISTS ("
        'SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_'
        "object('artifact_id', field_basis_field_response_records.value['id'], 'expec"
        "ted_revision', field_basis_field_response_records.value['revision'])), jsonb"
        '_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_'
        "field_response_records.source_basis['artifacts']) AS field_basis_field_respo"
        'nse_records(value))) AS enterprise_reads_field_feedback(value) JOIN enterpri'
        'se_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_arti'
        'facts_83b71844b30b68bc.tenant_id = shared_enterprise_field_response_records.'
        'tenant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id '
        "= CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_83b71844b30b68bc.private)) OR share'
        "d_enterprise_field_feedback_versions.visibility != 'category' AS private, (E"
        'XISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb'
        "_build_object('artifact_id', field_basis_field_response_records.value['id'],"
        " 'expected_revision', field_basis_field_response_records.value['revision']))"
        ', jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ente'
        "rprise_field_response_records.source_basis['artifacts']) AS field_basis_fiel"
        'd_response_records(value))) AS enterprise_reads_field_feedback(value) JOIN e'
        'nterprise_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritati'
        've_artifacts_83b71844b30b68bc.tenant_id = shared_enterprise_field_response_r'
        'ecords.tenant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.sou'
        "rce_id = CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.customer_or'
        "iginal)) OR (shared_enterprise_field_feedback_versions.body ->> 'channel') ="
        " 'customer' AS customer_original, shared_enterprise_field_feedback_currents."
        'version_id = shared_enterprise_field_response_records.feedback_version_id AS'
        ' is_current, shared_enterprise_field_response_records.created_at AS created_'
        'at, CAST(NULL AS UUID) AS original_id, shared_enterprise_field_response_reco'
        'rds.feedback_id AS object_id, (SELECT coalesce(array_agg(enterprise_authorit'
        'ative_artifacts_83b71844b30b68bc.original_id), ARRAY[]::UUID[]) AS coalesce_'
        '6 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('
        "'artifact_id', field_basis_field_response_records.value['id'], 'expected_rev"
        "ision', field_basis_field_response_records.value['revision'])), jsonb_build_"
        'array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_field_r'
        "esponse_records.source_basis['artifacts']) AS field_basis_field_response_rec"
        'ords(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise_auth'
        'oritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifacts_8'
        '3b71844b30b68bc.tenant_id = shared_enterprise_field_response_records.tenant_'
        'id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id = CAST('
        "(enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nWHERE e"
        'nterprise_authoritative_artifacts_83b71844b30b68bc.original_id IS NOT NULL) '
        'AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SE'
        "LECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field_"
        "response_records.value['id'], 'expected_revision', field_basis_field_respons"
        "e_records.value['revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jso"
        "nb_array_elements(shared_enterprise_field_response_records.source_basis['art"
        "ifacts']) AS field_basis_field_response_records(value))) AS enterprise_reads"
        '_field_feedback(value) JOIN enterprise_authoritative_artifacts_83b71844b30b6'
        '8bc ON enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = share'
        'd_enterprise_field_response_records.tenant_id AND enterprise_authoritative_a'
        'rtifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_feedback.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        '_83b71844b30b68bc.source_revision != CAST((enterprise_reads_field_feedback.v'
        "alue ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'curre"
        "nt' END AS read_basis_status \nFROM shared_enterprise_field_response_records"
        ' LEFT OUTER JOIN shared_enterprise_projects ON shared_enterprise_projects.te'
        'nant_id = shared_enterprise_field_response_records.tenant_id AND shared_ente'
        'rprise_projects.product_id = shared_enterprise_field_response_records.produc'
        't_id AND shared_enterprise_projects.id = shared_enterprise_field_response_re'
        'cords.project_id AND shared_enterprise_projects.category_id = shared_enterpr'
        'ise_field_response_records.category_id LEFT OUTER JOIN shared_enterprise_pro'
        'ducts ON shared_enterprise_products.tenant_id = shared_enterprise_field_resp'
        'onse_records.tenant_id AND shared_enterprise_products.id = shared_enterprise'
        '_field_response_records.product_id AND shared_enterprise_products.category_i'
        'd = shared_enterprise_field_response_records.category_id JOIN shared_enterpr'
        'ise_field_feedback_versions ON shared_enterprise_field_feedback_versions.ten'
        'ant_id = shared_enterprise_field_response_records.tenant_id AND shared_enter'
        'prise_field_feedback_versions.category_id = shared_enterprise_field_response'
        '_records.category_id AND shared_enterprise_field_feedback_versions.product_i'
        'd IS NOT DISTINCT FROM shared_enterprise_field_response_records.product_id A'
        'ND shared_enterprise_field_feedback_versions.project_id IS NOT DISTINCT FROM'
        ' shared_enterprise_field_response_records.project_id AND shared_enterprise_f'
        'ield_feedback_versions.feedback_id = shared_enterprise_field_response_record'
        's.feedback_id AND shared_enterprise_field_feedback_versions.id = shared_ente'
        'rprise_field_response_records.feedback_version_id AND shared_enterprise_fiel'
        'd_feedback_versions.revision = shared_enterprise_field_response_records.feed'
        'back_revision JOIN shared_enterprise_field_feedback_currents ON shared_enter'
        'prise_field_feedback_currents.tenant_id = shared_enterprise_field_response_r'
        'ecords.tenant_id AND shared_enterprise_field_feedback_currents.category_id ='
        ' shared_enterprise_field_response_records.category_id AND shared_enterprise_'
        'field_feedback_currents.feedback_id = shared_enterprise_field_response_recor'
        'ds.feedback_id \nWHERE shared_enterprise_field_response_records.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (E"
        'XISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb'
        "_build_object('artifact_id', field_basis_field_response_records.value['id'],"
        " 'expected_revision', field_basis_field_response_records.value['revision']))"
        ', jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ente'
        "rprise_field_response_records.source_basis['artifacts']) AS field_basis_fiel"
        'd_response_records(value))) AS enterprise_reads_field_feedback(value) \nWHER'
        'E NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_83b71844b3'
        '0b68bc \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id'
        ' = shared_enterprise_field_response_records.tenant_id AND enterprise_authori'
        'tative_artifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_f'
        "eedback.value ->> 'artifact_id') AS UUID))))) AND (shared_enterprise_field_r"
        'esponse_records.product_id IS NULL OR shared_enterprise_products.id IS NOT N'
        'ULL) AND (shared_enterprise_field_response_records.project_id IS NULL OR sha'
        'red_enterprise_projects.id IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM au'
        'thoritative_enterprise_sources_83b71844b30b68bc \nWHERE authoritative_enterp'
        'rise_sources_83b71844b30b68bc.tenant_id = t AND authoritative_enterprise_sou'
        'rces_83b71844b30b68bc.category_id = c AND CAST(authoritative_enterprise_sour'
        "ces_83b71844b30b68bc.source_id AS TEXT) = expected->>'source_id' AND CAST(au"
        'thoritative_enterprise_sources_83b71844b30b68bc.source_revision AS TEXT) = e'
        "xpected->>'source_revision' AND authoritative_enterprise_sources_83b71844b30"
        "b68bc.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n  E"
        'LSE RETURN false; END CASE;\n  IF visible IS DISTINCT FROM true THEN RETURN '
        'false; END IF;\n END LOOP;\n RETURN true;\nEXCEPTION WHEN invalid_text_repre'
        'sentation OR numeric_value_out_of_range THEN RETURN false;\nEND\n;\n$functio'
        'n$\n'
    ),
    'enterprise_index_source_clear(text,uuid,uuid,text,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.enterprise_index_source_clear(kind text, s'
        'id uuid, category uuid, expected_key text, expected_ids uuid[])\n RETURNS vo'
        "id\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', "
        "'public', 'pg_temp'\nAS $function$\nDECLARE\n  t uuid := NULLIF(current_sett"
        "ing('pdos.tenant_id',true),'')::uuid;\n  a uuid := NULLIF(current_setting('p"
        "dos.actor_id',true),'')::uuid;\n  r uuid := NULLIF(current_setting('pdos.req"
        "uester_id',true),'')::uuid;\nBEGIN\n  IF t IS NULL OR a IS NULL OR r IS NULL"
        '\n     OR NOT EXISTS(SELECT 1 FROM public.principals p\n                   W'
        'HERE p.tenant_id=t AND p.id=a AND p.active)\n     OR NOT EXISTS(SELECT 1 FRO'
        'M public.principals p\n                   WHERE p.tenant_id=t AND p.id=r AND'
        ' p.active)\n     OR public.category_access(t,category,false) IS DISTINCT FRO'
        "M true THEN\n    RAISE EXCEPTION 'Derived source repair requires active boun"
        "d source scope'\n      USING ERRCODE='42501';\n  END IF;\n  IF kind IS NULL "
        "OR kind NOT IN\n     ('artifact','knowledge','issue','capa','change','test_r"
        "un','build','supply','external_wait','field_feedback')\n     OR sid IS NULL "
        "OR expected_key IS NULL OR expected_key !~ '^[a-f0-9]{64}$'\n     OR expecte"
        'd_ids IS NULL OR array_position(expected_ids,NULL) IS NOT NULL THEN\n    RAI'
        "SE EXCEPTION 'Derived source repair requires projector-computed identity'\n "
        "     USING ERRCODE='22023';\n  END IF;\n  PERFORM pg_advisory_xact_lock(hash"
        "textextended('enterprise-index:' || t::text,0));\n  DELETE FROM public.enter"
        'prise_search_chunks c WHERE c.tenant_id=t\n    AND ((c.source_type=kind AND '
        'c.source_id=sid)\n      OR c.work_key=expected_key OR c.id=ANY(expected_ids)'
        ');\n  DELETE FROM public.enterprise_search_sources s WHERE s.tenant_id=t\n  '
        '  AND ((s.source_type=kind AND s.source_id=sid) OR s.work_key=expected_key);'
        '\nEND $function$\n'
    ),
}

NATIVE_FUNCTIONS = {
    'assistant_source_lifecycle_links(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.assistant_source_lifecycle_links(t uuid, c'
        ' uuid, proof jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE SECURITY DE'
        "FINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$"
        "\n\nDECLARE links uuid[]='{}'; item jsonb; container jsonb; key text;\nBEGIN"
        "\n IF jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN\n  RAISE EXCEPTION '"
        "Fixed assistant source dependencies must be an array' USING ERRCODE='23514';"
        ' END IF;\n FOR item IN SELECT value FROM jsonb_array_elements(proof) LOOP\n '
        " IF item->>'category_id' IS DISTINCT FROM c::text\n   OR item->>'source_type"
        "' IS NULL\n   OR item->>'source_type'<>ALL(ARRAY['artifact','knowledge','iss"
        "ue','capa','change','external_wait','supply','build','test_run','field_feedb"
        "ack','project_status','manufacturing_document','verification_handoff'])\n   "
        "OR item->>'source_id' IS NULL\n   OR item->>'source_revision' IS NULL OR ite"
        "m->>'source_revision' !~ '^[1-9][0-9]*$'\n   OR item->>'content_hash' IS NUL"
        "L OR item->>'content_hash' !~ '^[a-f0-9]{64}$' THEN\n   RAISE EXCEPTION 'Ass"
        "istant dependency must retain its actual fixed identity' USING ERRCODE='2351"
        "4';\n  END IF;\n  links=array_append(links,(item->>'source_id')::uuid);\n  I"
        "F item->>'source_type'='manufacturing_document' THEN\n   links=links||coales"
        'ce((SELECT ARRAY[s.document_id,s.publication_id]\n    FROM public.manufactur'
        'ing_publication_documents s\n    WHERE s.tenant_id=t AND s.category_id=c AND'
        " s.id::text=item->>'source_id'),'{}'::uuid[]);\n  END IF;\n  -- Exact origin"
        'al dependency projection, not read permission or business facts.\n  -- Build'
        '/test record IDs resolve their own real registered Artifact read sets.\n  FO'
        'R container IN\n   SELECT s.required_source_read_set AS reads FROM public.qu'
        "ality_issue_versions s WHERE item->>'source_type'='issue' AND s.tenant_id=t "
        "AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELE"
        'CT s.required_source_read_set AS reads FROM public.quality_issue_versions s '
        "WHERE item->>'source_type'='capa' AND s.tenant_id=t AND s.category_id=c AND "
        "s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_rea"
        "d_set AS reads FROM public.change_request_versions s WHERE item->>'source_ty"
        "pe'='change' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'so"
        "urce_id'\n   UNION ALL\n   SELECT s.reads AS reads FROM public.external_wait"
        "_versions s WHERE item->>'source_type'='external_wait' AND s.tenant_id=t AND"
        " s.category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT "
        's.required_source_read_set AS reads FROM public.supply_snapshots s WHERE ite'
        "m->>'source_type'='supply' AND s.tenant_id=t AND s.category_id=c AND s.id::t"
        "ext=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set A"
        "S reads FROM public.build_starts s WHERE item->>'source_type'='build' AND s."
        "tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION "
        'ALL\n   SELECT s.required_source_read_set AS reads FROM public.actual_config'
        "urations s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.catego"
        "ry_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.require"
        "d_source_read_set AS reads FROM public.build_lots s WHERE item->>'source_typ"
        "e'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'sour"
        "ce_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads FROM pub"
        "lic.verification_run_versions s WHERE item->>'source_type'='test_run' AND s."
        "tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION "
        'ALL\n   SELECT s.required_source_read_set AS reads FROM public.test_result_a'
        "ctions s WHERE item->>'source_type'='test_run' AND s.tenant_id=t AND s.categ"
        "ory_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT coalesce"
        "(e.required_source_read_set,'[]'::jsonb)||coalesce(p.required_source_read_se"
        "t,'[]'::jsonb) AS reads FROM public.builds b JOIN public.engineering_configu"
        'rations e ON e.tenant_id=b.tenant_id AND e.category_id=b.category_id AND e.i'
        'd=b.engineering_configuration_id JOIN public.process_revisions p ON p.tenant'
        '_id=b.tenant_id AND p.category_id=b.category_id AND p.id=b.manufacturing_con'
        "figuration_id WHERE item->>'source_type'='build' AND b.tenant_id=t AND b.cat"
        "egory_id=c AND b.id::text=item->>'source_id'\n   UNION ALL\n   SELECT coales"
        "ce(jsonb_agg(jsonb_build_object('artifact_id',root->'id',\n      'expected_r"
        "evision',root->'revision')),'[]'::jsonb) AS reads\n    FROM public.field_fee"
        'dback_versions s\n     CROSS JOIN LATERAL jsonb_array_elements(s.source_basi'
        "s->'artifacts') root\n    WHERE item->>'source_type'='field_feedback' AND s."
        "tenant_id=t AND s.category_id=c\n     AND s.id::text=item->>'source_id'\n   "
        "UNION ALL\n   SELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id',roo"
        "t->'id',\n      'expected_revision',root->'revision')),'[]'::jsonb) AS reads"
        '\n    FROM public.field_response_records s\n     CROSS JOIN LATERAL jsonb_ar'
        "ray_elements(s.source_basis->'artifacts') root\n    WHERE item->>'source_typ"
        "e'='field_feedback' AND s.tenant_id=t AND s.category_id=c\n     AND s.id::te"
        "xt=item->>'source_id'\n   UNION ALL\n   SELECT s.reads||coalesce((SELECT jso"
        "nb_agg(jsonb_build_object('artifact_id',root->'id',\n      'expected_revisio"
        "n',root->'revision')) FROM jsonb_array_elements(s.source_basis->'artifacts')"
        " root),'[]'::jsonb)\n    FROM public.project_status_updates s\n    WHERE ite"
        "m->>'source_type'='project_status' AND s.tenant_id=t AND s.category_id=c\n  "
        "   AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.required_sou"
        'rce_read_set FROM public.manufacturing_preparation_versions s\n    WHERE ite'
        "m->>'source_type'='manufacturing_document' AND s.tenant_id=t AND s.category_"
        "id=c\n     AND s.id::text=item->>'source_id' AND s.kind IN ('work_instructio"
        "n','control_plan')\n   UNION ALL\n   SELECT d.required_source_read_set||p.re"
        'quired_source_read_set\n    FROM public.manufacturing_publication_documents '
        's\n    JOIN public.manufacturing_preparation_versions d ON d.tenant_id=s.ten'
        'ant_id AND d.category_id=s.category_id\n     AND d.product_id=s.product_id A'
        'ND d.project_id=s.project_id\n     AND d.id=s.document_id AND d.revision=s.d'
        'ocument_revision AND d.kind=s.document_kind\n     AND d.process_id=s.process'
        '_id AND d.process_revision=s.process_revision AND d.operation_key=s.operatio'
        'n_key\n    JOIN public.manufacturing_baseline_publications p ON p.tenant_id='
        's.tenant_id AND p.category_id=s.category_id\n     AND p.product_id=s.product'
        '_id AND p.project_id=s.project_id\n     AND p.id=s.publication_id AND p.revi'
        "sion=s.publication_revision\n    WHERE item->>'source_type'='manufacturing_d"
        "ocument' AND s.tenant_id=t AND s.category_id=c\n     AND s.id::text=item->>'"
        "source_id'\n   UNION ALL\n   SELECT s.required_source_read_set FROM public.v"
        "erification_handoff_facts s\n    WHERE item->>'source_type'='verification_ha"
        "ndoff' AND s.tenant_id=t AND s.category_id=c\n     AND s.id::text=item->>'so"
        "urce_id'\n  LOOP\n   FOR key IN SELECT value->>'artifact_id' FROM jsonb_arra"
        "y_elements(coalesce(container,'[]'::jsonb)) LOOP\n    IF key IS NOT NULL THE"
        'N links=array_append(links,key::uuid); END IF;\n   END LOOP;\n  END LOOP;\n '
        'END LOOP;\n RETURN links;\nEND\n;\n$function$\n'
    ),
    'knowledge_answer_sources_visible(uuid,uuid,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.knowledge_answer_sources_visible(t uuid, c'
        ' uuid, proof jsonb)\n RETURNS boolean\n LANGUAGE plpgsql\n STABLE\n SET sear'
        "ch_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\n\nDECLARE expec"
        'ted jsonb; visible boolean;\nBEGIN\n IF t IS DISTINCT FROM nullif(current_se'
        "tting('pdos.tenant_id',true),'')::uuid\n OR NOT public.category_access(t,c) "
        "OR jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n"
        ' FOR expected IN SELECT value FROM jsonb_array_elements(proof) LOOP\n  IF ex'
        "pected->>'category_id' IS DISTINCT FROM c::text THEN RETURN false; END IF;\n"
        "  CASE expected->>'source_type'\n WHEN 'artifact' THEN\n  WITH authoritative"
        "_enterprise_sources_c7c5c1d70c5dec44 AS \n(SELECT 'artifact' AS source_type,"
        ' artifact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id'
        ', artifact_versions.category_id AS category_id, artifact_versions.product_id'
        ' AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS prop'
        'osal_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision '
        'AS source_revision, artifact_versions.title AS title, artifact_versions.cont'
        'ent_hash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JS'
        "ONB) AS structured, 'untrusted' AS nature, artifact_versions.visibility != '"
        "category' OR coalesce(products.visibility != 'category', false) OR coalesce("
        "uploaded_originals.visibility != 'category', false) AS private, artifact_ver"
        'sions.original_id IS NOT NULL AS customer_original, true AS is_current, arti'
        'fact_versions.created_at AS created_at, artifact_versions.original_id AS ori'
        'ginal_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.or'
        'iginal_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY['
        "]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifac"
        't_versions LEFT OUTER JOIN products ON products.tenant_id = artifact_version'
        's.tenant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN u'
        'ploaded_originals ON uploaded_originals.tenant_id = artifact_versions.tenant'
        '_id AND uploaded_originals.id = artifact_versions.original_id AND uploaded_o'
        'riginals.category_id = artifact_versions.category_id AND uploaded_originals.'
        'product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN'
        ' original_security ON original_security.tenant_id = uploaded_originals.tenan'
        't_id AND original_security.original_id = uploaded_originals.id \nWHERE artif'
        "act_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)"
        ", '') AS UUID) AND artifact_versions.status = 'active' AND artifact_versions"
        '.category_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR produc'
        'ts.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_or'
        "iginals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded"
        "_originals.scan_status = 'clean' AND original_security.source_state = 'activ"
        "e' AND original_security.disposition = 'active' AND original_security.curren"
        't_request_id IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_en'
        'terprise_sources_c7c5c1d70c5dec44 \nWHERE authoritative_enterprise_sources_c'
        '7c5c1d70c5dec44.tenant_id = t AND authoritative_enterprise_sources_c7c5c1d70'
        'c5dec44.category_id = c AND CAST(authoritative_enterprise_sources_c7c5c1d70c'
        "5dec44.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_en"
        "terprise_sources_c7c5c1d70c5dec44.source_revision AS TEXT) = expected->>'sou"
        "rce_revision' AND authoritative_enterprise_sources_c7c5c1d70c5dec44.content_"
        "hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'knowledge'"
        ' THEN\n  SELECT EXISTS (SELECT 1 \nFROM (SELECT category_knowledge_entries.i'
        'd AS source_id, category_knowledge_entries.tenant_id AS tenant_id, category_'
        'knowledge_entries.category_id AS category_id, category_knowledge_entries.ver'
        'sion AS source_revision, encode(sha256(convert_to(CAST(category_knowledge_en'
        "tries.content AS TEXT), 'UTF8')), 'hex') AS content_hash \nFROM category_kno"
        'wledge_entries JOIN category_knowledge_current ON category_knowledge_current'
        '.tenant_id = category_knowledge_entries.tenant_id AND category_knowledge_cur'
        'rent.lineage_id = category_knowledge_entries.lineage_id AND category_knowled'
        "ge_current.status = 'active' \nWHERE category_knowledge_entries.action != 'w"
        "ithdraw' UNION ALL SELECT knowledge_rule_versions.id AS source_id, knowledge"
        '_rule_versions.tenant_id AS tenant_id, knowledge_rule_versions.category_id A'
        'S category_id, knowledge_rule_versions.revision AS source_revision, encode(s'
        "ha256(convert_to(CAST(knowledge_rule_versions.body AS TEXT), 'UTF8')), 'hex'"
        ') AS content_hash \nFROM knowledge_rule_versions JOIN knowledge_rule_current'
        's ON knowledge_rule_currents.tenant_id = knowledge_rule_versions.tenant_id A'
        'ND knowledge_rule_currents.rule_id = knowledge_rule_versions.rule_id) AS ord'
        'inary_knowledge_leaves \nWHERE ordinary_knowledge_leaves.tenant_id = t AND o'
        'rdinary_knowledge_leaves.category_id = c AND CAST(ordinary_knowledge_leaves.'
        "source_id AS TEXT) = expected->>'source_id' AND CAST(ordinary_knowledge_leav"
        "es.source_revision AS TEXT) = expected->>'source_revision' AND ordinary_know"
        "ledge_leaves.content_hash = expected->>'content_hash') AS anon_1 INTO visibl"
        "e;\n WHEN 'issue' THEN\n  WITH enterprise_authoritative_artifacts_4a502846d0"
        "70e208 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sourc"
        'e_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category_i'
        'd AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS U'
        'UID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.own'
        'er_id AS owner_id, artifact_versions.revision AS source_revision, artifact_v'
        'ersions.title AS title, artifact_versions.content_hash AS content_hash, arti'
        "fact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted"
        "' AS nature, artifact_versions.visibility != 'category' OR coalesce(products"
        ".visibility != 'category', false) OR coalesce(uploaded_originals.visibility "
        "!= 'category', false) AS private, artifact_versions.original_id IS NOT NULL "
        'AS customer_original, true AS is_current, artifact_versions.created_at AS cr'
        'eated_at, artifact_versions.original_id AS original_id, artifact_versions.id'
        ' AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN AR'
        'RAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids,'
        " 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN pro"
        'ducts ON products.tenant_id = artifact_versions.tenant_id AND products.id = '
        'artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_'
        'originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id '
        '= artifact_versions.original_id AND uploaded_originals.category_id = artifac'
        't_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT FRO'
        'M artifact_versions.product_id LEFT OUTER JOIN original_security ON original'
        '_security.tenant_id = uploaded_originals.tenant_id AND original_security.ori'
        'ginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_ve"
        "rsions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND ("
        'artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifa'
        'ct_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND upl'
        "oaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'clea"
        "n' AND original_security.source_state = 'active' AND original_security.dispo"
        "sition = 'active' AND original_security.current_request_id IS NOT NULL)), \n"
        'shared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT quality_i'
        'ssue_versions.product_id AS product_id, quality_issue_versions.project_id AS'
        ' project_id, quality_issue_versions.issue_id AS issue_id, quality_issue_vers'
        'ions.revision AS revision, quality_issue_versions.previous_issue_version_id '
        'AS previous_issue_version_id, quality_issue_versions.previous_revision AS pr'
        'evious_revision, quality_issue_versions.owner_id AS owner_id, quality_issue_'
        'versions.writer_id AS writer_id, quality_issue_versions.visibility AS visibi'
        'lity, quality_issue_versions.purpose AS purpose, quality_issue_versions.stat'
        'us AS status, quality_issue_versions.operation AS operation, quality_issue_v'
        'ersions.issue_snapshot AS issue_snapshot, quality_issue_versions.snapshot_sh'
        'a256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS input_snap'
        'shot, quality_issue_versions.authority_snapshot AS authority_snapshot, quali'
        'ty_issue_versions.policy_snapshot AS policy_snapshot, quality_issue_versions'
        '.sources AS sources, quality_issue_versions.required_source_read_set AS requ'
        'ired_source_read_set, quality_issue_versions.source_basis AS source_basis, q'
        'uality_issue_versions.intent_digest AS intent_digest, quality_issue_versions'
        '.reason AS reason, quality_issue_versions.id AS id, quality_issue_versions.t'
        'enant_id AS tenant_id, quality_issue_versions.created_at AS created_at, qual'
        'ity_issue_versions.category_id AS category_id \nFROM quality_issue_versions '
        "\nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_setting('pdos"
        ".tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIALI"
        'ZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS owner_'
        'id, projects.name AS name, projects.purpose AS purpose, projects.scope AS sc'
        'ope, projects.visibility AS visibility, projects.status AS status, projects.'
        'revision AS revision, projects.current_plan_id AS current_plan_id, projects.'
        'trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projects.g0'
        '_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id AS ten'
        'ant_id, projects.created_at AS created_at, projects.category_id AS category_'
        'id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS MATE"
        'RIALIZED \n(SELECT products.name AS name, products.purpose AS purpose, produ'
        'cts.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, produ'
        'cts.status AS status, products.owner_id AS owner_id, products.parent_product'
        '_id AS parent_product_id, products.category_id AS category_id, products.visi'
        'bility AS visibility, products.target_price AS target_price, products.target'
        '_price_currency AS target_price_currency, products.target_price_basis AS tar'
        'get_price_basis, products.target_price_includes_tax AS target_price_includes'
        '_tax, products.target_price_as_of AS target_price_as_of, products.id AS id, '
        'products.tenant_id AS tenant_id, products.created_at AS created_at \nFROM pr'
        "oducts \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.tenant"
        "_id', true), '') AS UUID)), \nshared_enterprise_quality_current_issues AS MA"
        'TERIALIZED \n(SELECT quality_current_issues.product_id AS product_id, qualit'
        'y_current_issues.project_id AS project_id, quality_current_issues.issue_id A'
        'S issue_id, quality_current_issues.issue_version_id AS issue_version_id, qua'
        'lity_current_issues.issue_revision AS issue_revision, quality_current_issues'
        '.epoch AS epoch, quality_current_issues.id AS id, quality_current_issues.ten'
        'ant_id AS tenant_id, quality_current_issues.created_at AS created_at, qualit'
        'y_current_issues.category_id AS category_id \nFROM quality_current_issues \n'
        "WHERE quality_current_issues.tenant_id = CAST(nullif(current_setting('pdos.t"
        "enant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_4a502846"
        "d070e208 AS \n(SELECT 'issue' AS source_type, shared_enterprise_quality_issu"
        'e_versions.id AS source_id, shared_enterprise_quality_issue_versions.tenant_'
        'id AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS cat'
        'egory_id, shared_enterprise_quality_issue_versions.product_id AS product_id,'
        ' shared_enterprise_quality_issue_versions.project_id AS project_id, CAST(NUL'
        'L AS UUID) AS proposal_id, shared_enterprise_quality_issue_versions.owner_id'
        ' AS owner_id, shared_enterprise_quality_issue_versions.revision AS source_re'
        "vision, shared_enterprise_quality_issue_versions.issue_snapshot ->> 'title' "
        "AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'facts'"
        ", jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.is"
        "sue_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot['ti"
        "tle'], 'status', shared_enterprise_quality_issue_versions.status, 'risk', sh"
        "ared_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_rechec"
        "k', shared_enterprise_quality_issue_versions.issue_snapshot['needs_recheck']"
        ", 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['recheck_reasons'], 'merged_into', shared_enterprise_quality_issue_versions"
        ".issue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'], "
        "'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root_ca"
        "use']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('id', enterprise_containment.value['id'], 'text', enterprise_con"
        "tainment.value['text'], 'executor_id', enterprise_containment.value['executo"
        "r_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS co"
        'alesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issu'
        "e_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDINAL"
        "ITY AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_objec"
        "t('text', shared_enterprise_quality_issue_versions.issue_snapshot['closure']"
        "['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions.iss"
        "ue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['art"
        "ifact_id'], 'version', enterprise_reads_issue.value['expected_revision']) OR"
        "DER BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_issu"
        "e.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM "
        'jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sourc'
        "e_read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_o"
        "bject('object_id', shared_enterprise_quality_issue_versions.issue_id, 'kind'"
        ", 'issue', 'facts', jsonb_build_object('issue_id', shared_enterprise_quality"
        "_issue_versions.issue_id, 'title', shared_enterprise_quality_issue_versions."
        "issue_snapshot['title'], 'status', shared_enterprise_quality_issue_versions."
        "status, 'risk', shared_enterprise_quality_issue_versions.issue_snapshot['ris"
        "k'], 'needs_recheck', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['needs_recheck'], 'recheck_reasons', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['recheck_reasons'], 'merged_into', shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['merged_into'], 'root_cause', jsonb_build_"
        "object('text', shared_enterprise_quality_issue_versions.issue_snapshot['root"
        "_cause']['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['root_cause']['actor_id'], 'at', shared_enterprise_quality_issue_v"
        "ersions.issue_snapshot['root_cause']['at']), 'containment', (SELECT coalesce"
        "(jsonb_agg(jsonb_build_object('id', enterprise_containment.value['id'], 'tex"
        "t', enterprise_containment.value['text'], 'executor_id', enterprise_containm"
        "ent.value['executor_id']) ORDER BY enterprise_containment.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['containment'], CAST('[]' AS JSO"
        "NB))) WITH ORDINALITY AS enterprise_containment(value, ordinal)), 'closure',"
        " jsonb_build_object('text', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['closure']['text'], 'actor_id', shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['closure']['actor_id'], 'at', shared_enterprise_quality_"
        "issue_versions.issue_snapshot['closure']['at'])), 'source_refs', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_read"
        "s_issue.value['artifact_id'], 'version', enterprise_reads_issue.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_issue.value ->> 'artifact_id', ent"
        "erprise_reads_issue.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versi'
        "ons.required_source_read_set) AS enterprise_reads_issue(value)), 'record_pol"
        "icy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'fac"
        "ts', jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions"
        ".issue_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot["
        "'title'], 'status', shared_enterprise_quality_issue_versions.status, 'risk',"
        " shared_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_rec"
        "heck', shared_enterprise_quality_issue_versions.issue_snapshot['needs_rechec"
        "k'], 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['recheck_reasons'], 'merged_into', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', "
        "shared_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'"
        "], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root"
        "_cause']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(json"
        "b_build_object('id', enterprise_containment.value['id'], 'text', enterprise_"
        "containment.value['text'], 'executor_id', enterprise_containment.value['exec"
        "utor_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS"
        ' coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_i'
        "ssue_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDI"
        "NALITY AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_ob"
        "ject('text', shared_enterprise_quality_issue_versions.issue_snapshot['closur"
        "e']['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions."
        "issue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg"
        "(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['"
        "artifact_id'], 'version', enterprise_reads_issue.value['expected_revision'])"
        " ORDER BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_i"
        "ssue.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFR"
        'OM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_so'
        "urce_read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_quality_is"
        "sue_versions.visibility != 'category' OR coalesce(shared_enterprise_projects"
        ".visibility != 'category', false) OR coalesce(shared_enterprise_products.vis"
        "ibility != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_quality_issue_versions.required_source_read_set) AS ent'
        'erprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_4a502846d'
        '070e208 ON enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = s'
        'hared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritati'
        've_artifacts_4a502846d070e208.source_id = CAST((enterprise_reads_issue.value'
        " ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a50"
        '2846d070e208.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_eleme'
        'nts(shared_enterprise_quality_issue_versions.required_source_read_set) AS en'
        'terprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_4a502846'
        'd070e208 ON enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = '
        'shared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritat'
        'ive_artifacts_4a502846d070e208.source_id = CAST((enterprise_reads_issue.valu'
        "e ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a5"
        '02846d070e208.customer_original) AS customer_original, shared_enterprise_qua'
        'lity_current_issues.issue_version_id = shared_enterprise_quality_issue_versi'
        'ons.id AS is_current, shared_enterprise_quality_issue_versions.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_quality_is'
        'sue_versions.issue_id AS object_id, (SELECT coalesce(array_agg(enterprise_au'
        'thoritative_artifacts_4a502846d070e208.original_id), ARRAY[]::UUID[]) AS coa'
        'lesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions'
        '.required_source_read_set) AS enterprise_reads_issue(value) JOIN enterprise_'
        'authoritative_artifacts_4a502846d070e208 ON enterprise_authoritative_artifac'
        'ts_4a502846d070e208.tenant_id = shared_enterprise_quality_issue_versions.ten'
        'ant_id AND enterprise_authoritative_artifacts_4a502846d070e208.source_id = C'
        "AST((enterprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_4a502846d070e208.original_id IS NOT NULL) AS or'
        'iginal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_e'
        'nterprise_quality_issue_versions.required_source_read_set) AS enterprise_rea'
        'ds_issue(value) JOIN enterprise_authoritative_artifacts_4a502846d070e208 ON '
        'enterprise_authoritative_artifacts_4a502846d070e208.tenant_id = shared_enter'
        'prise_quality_issue_versions.tenant_id AND enterprise_authoritative_artifact'
        "s_4a502846d070e208.source_id = CAST((enterprise_reads_issue.value ->> 'artif"
        "act_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_4a502846d070e20"
        "8.source_revision != CAST((enterprise_reads_issue.value ->> 'expected_revisi"
        "on') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_sta"
        'tus \nFROM shared_enterprise_quality_issue_versions JOIN shared_enterprise_p'
        'rojects ON shared_enterprise_projects.tenant_id = shared_enterprise_quality_'
        'issue_versions.tenant_id AND shared_enterprise_projects.product_id = shared_'
        'enterprise_quality_issue_versions.product_id AND shared_enterprise_projects.'
        'id = shared_enterprise_quality_issue_versions.project_id AND shared_enterpri'
        'se_projects.category_id = shared_enterprise_quality_issue_versions.category_'
        'id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id ='
        ' shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise_pr'
        'oducts.id = shared_enterprise_quality_issue_versions.product_id AND shared_e'
        'nterprise_products.category_id = shared_enterprise_quality_issue_versions.ca'
        'tegory_id JOIN shared_enterprise_quality_current_issues ON shared_enterprise'
        '_quality_current_issues.tenant_id = shared_enterprise_quality_issue_versions'
        '.tenant_id AND shared_enterprise_quality_current_issues.product_id = shared_'
        'enterprise_quality_issue_versions.product_id AND shared_enterprise_quality_c'
        'urrent_issues.project_id = shared_enterprise_quality_issue_versions.project_'
        'id AND shared_enterprise_quality_current_issues.issue_id = shared_enterprise'
        '_quality_issue_versions.issue_id \nWHERE shared_enterprise_quality_issue_ver'
        "sions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') A"
        'S UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr'
        'ise_quality_issue_versions.required_source_read_set) AS enterprise_reads_iss'
        'ue(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_arti'
        'facts_4a502846d070e208 \nWHERE enterprise_authoritative_artifacts_4a502846d0'
        '70e208.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND en'
        'terprise_authoritative_artifacts_4a502846d070e208.source_id = CAST((enterpri'
        "se_reads_issue.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELEC"
        'T 1 \nFROM authoritative_enterprise_sources_4a502846d070e208 \nWHERE authori'
        'tative_enterprise_sources_4a502846d070e208.tenant_id = t AND authoritative_e'
        'nterprise_sources_4a502846d070e208.category_id = c AND CAST(authoritative_en'
        "terprise_sources_4a502846d070e208.source_id AS TEXT) = expected->>'source_id"
        "' AND CAST(authoritative_enterprise_sources_4a502846d070e208.source_revision"
        " AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_source"
        "s_4a502846d070e208.content_hash = expected->>'content_hash') AS anon_1 INTO "
        "visible;\n WHEN 'capa' THEN\n  WITH enterprise_authoritative_artifacts_b398e"
        "ff2ffc06d18 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS "
        'source_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.categ'
        'ory_id AS category_id, artifact_versions.product_id AS product_id, CAST(NULL'
        ' AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_version'
        's.owner_id AS owner_id, artifact_versions.revision AS source_revision, artif'
        'act_versions.title AS title, artifact_versions.content_hash AS content_hash,'
        " artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untr"
        "usted' AS nature, artifact_versions.visibility != 'category' OR coalesce(pro"
        "ducts.visibility != 'category', false) OR coalesce(uploaded_originals.visibi"
        "lity != 'category', false) AS private, artifact_versions.original_id IS NOT "
        'NULL AS customer_original, true AS is_current, artifact_versions.created_at '
        'AS created_at, artifact_versions.original_id AS original_id, artifact_versio'
        'ns.id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) TH'
        'EN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original'
        "_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOI"
        'N products ON products.tenant_id = artifact_versions.tenant_id AND products.'
        'id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uplo'
        'aded_originals.tenant_id = artifact_versions.tenant_id AND uploaded_original'
        's.id = artifact_versions.original_id AND uploaded_originals.category_id = ar'
        'tifact_versions.category_id AND uploaded_originals.product_id IS NOT DISTINC'
        'T FROM artifact_versions.product_id LEFT OUTER JOIN original_security ON ori'
        'ginal_security.tenant_id = uploaded_originals.tenant_id AND original_securit'
        'y.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifa"
        "ct_versions.status = 'active' AND artifact_versions.category_id IS NOT NULL "
        'AND (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (a'
        'rtifact_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AN'
        "D uploaded_originals.status = 'parsed' AND uploaded_originals.scan_status = "
        "'clean' AND original_security.source_state = 'active' AND original_security."
        "disposition = 'active' AND original_security.current_request_id IS NOT NULL)"
        '), \nshared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT qual'
        'ity_issue_versions.product_id AS product_id, quality_issue_versions.project_'
        'id AS project_id, quality_issue_versions.issue_id AS issue_id, quality_issue'
        '_versions.revision AS revision, quality_issue_versions.previous_issue_versio'
        'n_id AS previous_issue_version_id, quality_issue_versions.previous_revision '
        'AS previous_revision, quality_issue_versions.owner_id AS owner_id, quality_i'
        'ssue_versions.writer_id AS writer_id, quality_issue_versions.visibility AS v'
        'isibility, quality_issue_versions.purpose AS purpose, quality_issue_versions'
        '.status AS status, quality_issue_versions.operation AS operation, quality_is'
        'sue_versions.issue_snapshot AS issue_snapshot, quality_issue_versions.snapsh'
        'ot_sha256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS input'
        '_snapshot, quality_issue_versions.authority_snapshot AS authority_snapshot, '
        'quality_issue_versions.policy_snapshot AS policy_snapshot, quality_issue_ver'
        'sions.sources AS sources, quality_issue_versions.required_source_read_set AS'
        ' required_source_read_set, quality_issue_versions.source_basis AS source_bas'
        'is, quality_issue_versions.intent_digest AS intent_digest, quality_issue_ver'
        'sions.reason AS reason, quality_issue_versions.id AS id, quality_issue_versi'
        'ons.tenant_id AS tenant_id, quality_issue_versions.created_at AS created_at,'
        ' quality_issue_versions.category_id AS category_id \nFROM quality_issue_vers'
        'ions \nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATE"
        'RIALIZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS o'
        'wner_id, projects.name AS name, projects.purpose AS purpose, projects.scope '
        'AS scope, projects.visibility AS visibility, projects.status AS status, proj'
        'ects.revision AS revision, projects.current_plan_id AS current_plan_id, proj'
        'ects.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projec'
        'ts.g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id A'
        'S tenant_id, projects.created_at AS created_at, projects.category_id AS cate'
        'gory_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_set'
        "ting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS"
        ' MATERIALIZED \n(SELECT products.name AS name, products.purpose AS purpose, '
        'products.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, '
        'products.status AS status, products.owner_id AS owner_id, products.parent_pr'
        'oduct_id AS parent_product_id, products.category_id AS category_id, products'
        '.visibility AS visibility, products.target_price AS target_price, products.t'
        'arget_price_currency AS target_price_currency, products.target_price_basis A'
        'S target_price_basis, products.target_price_includes_tax AS target_price_inc'
        'ludes_tax, products.target_price_as_of AS target_price_as_of, products.id AS'
        ' id, products.tenant_id AS tenant_id, products.created_at AS created_at \nFR'
        "OM products \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.t"
        "enant_id', true), '') AS UUID)), \nshared_enterprise_quality_current_issues "
        'AS MATERIALIZED \n(SELECT quality_current_issues.product_id AS product_id, q'
        'uality_current_issues.project_id AS project_id, quality_current_issues.issue'
        '_id AS issue_id, quality_current_issues.issue_version_id AS issue_version_id'
        ', quality_current_issues.issue_revision AS issue_revision, quality_current_i'
        'ssues.epoch AS epoch, quality_current_issues.id AS id, quality_current_issue'
        's.tenant_id AS tenant_id, quality_current_issues.created_at AS created_at, q'
        'uality_current_issues.category_id AS category_id \nFROM quality_current_issu'
        "es \nWHERE quality_current_issues.tenant_id = CAST(nullif(current_setting('p"
        "dos.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_b39"
        "8eff2ffc06d18 AS \n(SELECT 'capa' AS source_type, shared_enterprise_quality_"
        'issue_versions.id AS source_id, shared_enterprise_quality_issue_versions.ten'
        'ant_id AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS'
        ' category_id, shared_enterprise_quality_issue_versions.product_id AS product'
        '_id, shared_enterprise_quality_issue_versions.project_id AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, shared_enterprise_quality_issue_versions.owne'
        'r_id AS owner_id, shared_enterprise_quality_issue_versions.revision AS sourc'
        "e_revision, 'CAPA \xb7 ' || (shared_enterprise_quality_issue_versions.issue_"
        "snapshot ->> 'title') AS title, encode(sha256(convert_to(CAST(CAST(jsonb_bui"
        "ld_object('object_id', CAST((shared_enterprise_quality_issue_versions.issue_"
        "snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', jsonb_build_ob"
        "ject('issue_id', shared_enterprise_quality_issue_versions.issue_id, 'capa_id"
        "', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['id'], 'i"
        "ssue_status', shared_enterprise_quality_issue_versions.status, 'hypotheses',"
        " (SELECT coalesce(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses"
        ".value['text']) ORDER BY enterprise_hypotheses.ordinal), jsonb_build_array()"
        ') AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quali'
        "ty_issue_versions.issue_snapshot['capa']['hypotheses'], CAST('[]' AS JSONB))"
        ") WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'actions', (SEL"
        "ECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_actions.valu"
        "e['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', enterprise_c"
        "apa_actions.value['text'], 'executor_id', enterprise_capa_actions.value['exe"
        "cutor_id'], 'completion_text', enterprise_capa_actions.value['completion']['"
        "text'], 'completed_by', enterprise_capa_actions.value['completion']['executo"
        "r_id'], 'completed_at', enterprise_capa_actions.value['completion']['at']['o"
        "ccurred_at']) ORDER BY enterprise_capa_actions.ordinal), jsonb_build_array()"
        ') AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quali'
        "ty_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' AS JSONB))) W"
        "ITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requirement', j"
        "sonb_build_object('method', shared_enterprise_quality_issue_versions.issue_s"
        "napshot['capa']['requirement']['method'], 'acceptance', shared_enterprise_qu"
        "ality_issue_versions.issue_snapshot['capa']['requirement']['acceptance'], 'o"
        "bservation_until', shared_enterprise_quality_issue_versions.issue_snapshot['"
        "capa']['requirement']['observation_until']), 'effectiveness', jsonb_build_ob"
        "ject('text', shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        "['effectiveness']['text'], 'result', shared_enterprise_quality_issue_version"
        "s.issue_snapshot['capa']['effectiveness']['result'], 'actor_id', shared_ente"
        "rprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['actor"
        "_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        "['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('type', 'artifact', 'id', enterprise_reads_capa.value['artifact_"
        "id'], 'version', enterprise_reads_capa.value['expected_revision']) ORDER BY "
        "enterprise_reads_capa.value ->> 'artifact_id', enterprise_reads_capa.value -"
        ">> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_arr"
        'ay_elements(shared_enterprise_quality_issue_versions.required_source_read_se'
        "t) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', CAST((shared_enterprise_quality_issue_versions.issue_snapshot['capa']"
        ") ->> 'id' AS UUID), 'kind', 'capa', 'facts', jsonb_build_object('issue_id',"
        " shared_enterprise_quality_issue_versions.issue_id, 'capa_id', shared_enterp"
        "rise_quality_issue_versions.issue_snapshot['capa']['id'], 'issue_status', sh"
        "ared_enterprise_quality_issue_versions.status, 'hypotheses', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses.value['text']) "
        'ORDER BY enterprise_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 '
        '\nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_version'
        "s.issue_snapshot['capa']['hypotheses'], CAST('[]' AS JSONB))) WITH ORDINALIT"
        "Y AS enterprise_hypotheses(value, ordinal)), 'actions', (SELECT coalesce(jso"
        "nb_agg(jsonb_build_object('id', enterprise_capa_actions.value['id'], 'kind',"
        " enterprise_capa_actions.value['kind'], 'text', enterprise_capa_actions.valu"
        "e['text'], 'executor_id', enterprise_capa_actions.value['executor_id'], 'com"
        "pletion_text', enterprise_capa_actions.value['completion']['text'], 'complet"
        "ed_by', enterprise_capa_actions.value['completion']['executor_id'], 'complet"
        "ed_at', enterprise_capa_actions.value['completion']['at']['occurred_at']) OR"
        'DER BY enterprise_capa_actions.ordinal), jsonb_build_array()) AS coalesce_2 '
        '\nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_version'
        "s.issue_snapshot['capa']['actions'], CAST('[]' AS JSONB))) WITH ORDINALITY A"
        "S enterprise_capa_actions(value, ordinal)), 'requirement', jsonb_build_objec"
        "t('method', shared_enterprise_quality_issue_versions.issue_snapshot['capa']["
        "'requirement']['method'], 'acceptance', shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['capa']['requirement']['acceptance'], 'observation_until"
        "', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['requirem"
        "ent']['observation_until']), 'effectiveness', jsonb_build_object('text', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness'"
        "]['text'], 'result', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['capa']['effectiveness']['result'], 'actor_id', shared_enterprise_quality_i"
        "ssue_versions.issue_snapshot['capa']['effectiveness']['actor_id'], 'at', sha"
        "red_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness'"
        "]['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_capa.value['artifact_id'], 'version',"
        " enterprise_reads_capa.value['expected_revision']) ORDER BY enterprise_reads"
        "_capa.value ->> 'artifact_id', enterprise_reads_capa.value ->> 'expected_rev"
        "ision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(shar"
        'ed_enterprise_quality_issue_versions.required_source_read_set) AS enterprise'
        "_reads_capa(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAS"
        "T(jsonb_build_object('object_id', CAST((shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', jso"
        "nb_build_object('issue_id', shared_enterprise_quality_issue_versions.issue_i"
        "d, 'capa_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa'"
        "]['id'], 'issue_status', shared_enterprise_quality_issue_versions.status, 'h"
        "ypotheses', (SELECT coalesce(jsonb_agg(jsonb_build_object('text', enterprise"
        "_hypotheses.value['text']) ORDER BY enterprise_hypotheses.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['capa']['hypotheses'], CAST('[]'"
        " AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'act"
        "ions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_a"
        "ctions.value['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', e"
        "nterprise_capa_actions.value['text'], 'executor_id', enterprise_capa_actions"
        ".value['executor_id'], 'completion_text', enterprise_capa_actions.value['com"
        "pletion']['text'], 'completed_by', enterprise_capa_actions.value['completion"
        "']['executor_id'], 'completed_at', enterprise_capa_actions.value['completion"
        "']['at']['occurred_at']) ORDER BY enterprise_capa_actions.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_quality_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' AS"
        " JSONB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requ"
        "irement', jsonb_build_object('method', shared_enterprise_quality_issue_versi"
        "ons.issue_snapshot['capa']['requirement']['method'], 'acceptance', shared_en"
        "terprise_quality_issue_versions.issue_snapshot['capa']['requirement']['accep"
        "tance'], 'observation_until', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['capa']['requirement']['observation_until']), 'effectiveness', jso"
        "nb_build_object('text', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['capa']['effectiveness']['text'], 'result', shared_enterprise_quality_is"
        "sue_versions.issue_snapshot['capa']['effectiveness']['result'], 'actor_id', "
        "shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectivene"
        "ss']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['capa']['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_"
        "agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_capa.value"
        "['artifact_id'], 'version', enterprise_reads_capa.value['expected_revision']"
        ") ORDER BY enterprise_reads_capa.value ->> 'artifact_id', enterprise_reads_c"
        "apa.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFRO"
        'M jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sou'
        "rce_read_set) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_quality_is"
        "sue_versions.visibility != 'category' OR coalesce(shared_enterprise_projects"
        ".visibility != 'category', false) OR coalesce(shared_enterprise_products.vis"
        "ibility != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_quality_issue_versions.required_source_read_set) AS ent'
        'erprise_reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ff'
        'c06d18 ON enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = sh'
        'ared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritativ'
        'e_artifacts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value -'
        ">> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398ef"
        'f2ffc06d18.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_element'
        's(shared_enterprise_quality_issue_versions.required_source_read_set) AS ente'
        'rprise_reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ffc'
        '06d18 ON enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = sha'
        'red_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritative'
        '_artifacts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value ->'
        "> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398eff"
        '2ffc06d18.customer_original) AS customer_original, shared_enterprise_quality'
        '_current_issues.issue_version_id = shared_enterprise_quality_issue_versions.'
        'id AS is_current, shared_enterprise_quality_issue_versions.created_at AS cre'
        'ated_at, CAST(NULL AS UUID) AS original_id, CAST((shared_enterprise_quality_'
        "issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID) AS object_id, (SELE"
        'CT coalesce(array_agg(enterprise_authoritative_artifacts_b398eff2ffc06d18.or'
        'iginal_id), ARRAY[]::UUID[]) AS coalesce_4 \nFROM jsonb_array_elements(share'
        'd_enterprise_quality_issue_versions.required_source_read_set) AS enterprise_'
        'reads_capa(value) JOIN enterprise_authoritative_artifacts_b398eff2ffc06d18 O'
        'N enterprise_authoritative_artifacts_b398eff2ffc06d18.tenant_id = shared_ent'
        'erprise_quality_issue_versions.tenant_id AND enterprise_authoritative_artifa'
        "cts_b398eff2ffc06d18.source_id = CAST((enterprise_reads_capa.value ->> 'arti"
        "fact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b398eff2ffc06d"
        '18.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nF'
        'ROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_s'
        'ource_read_set) AS enterprise_reads_capa(value) JOIN enterprise_authoritativ'
        'e_artifacts_b398eff2ffc06d18 ON enterprise_authoritative_artifacts_b398eff2f'
        'fc06d18.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND e'
        'nterprise_authoritative_artifacts_b398eff2ffc06d18.source_id = CAST((enterpr'
        "ise_reads_capa.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorit"
        'ative_artifacts_b398eff2ffc06d18.source_revision != CAST((enterprise_reads_c'
        "apa.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE '"
        "current' END AS read_basis_status \nFROM shared_enterprise_quality_issue_ver"
        'sions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_i'
        'd = shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise'
        '_projects.product_id = shared_enterprise_quality_issue_versions.product_id A'
        'ND shared_enterprise_projects.id = shared_enterprise_quality_issue_versions.'
        'project_id AND shared_enterprise_projects.category_id = shared_enterprise_qu'
        'ality_issue_versions.category_id JOIN shared_enterprise_products ON shared_e'
        'nterprise_products.tenant_id = shared_enterprise_quality_issue_versions.tena'
        'nt_id AND shared_enterprise_products.id = shared_enterprise_quality_issue_ve'
        'rsions.product_id AND shared_enterprise_products.category_id = shared_enterp'
        'rise_quality_issue_versions.category_id JOIN shared_enterprise_quality_curre'
        'nt_issues ON shared_enterprise_quality_current_issues.tenant_id = shared_ent'
        'erprise_quality_issue_versions.tenant_id AND shared_enterprise_quality_curre'
        'nt_issues.product_id = shared_enterprise_quality_issue_versions.product_id A'
        'ND shared_enterprise_quality_current_issues.project_id = shared_enterprise_q'
        'uality_issue_versions.project_id AND shared_enterprise_quality_current_issue'
        's.issue_id = shared_enterprise_quality_issue_versions.issue_id \nWHERE share'
        'd_enterprise_quality_issue_versions.tenant_id = CAST(nullif(current_setting('
        "'pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb"
        '_array_elements(shared_enterprise_quality_issue_versions.required_source_rea'
        'd_set) AS enterprise_reads_capa(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM '
        'enterprise_authoritative_artifacts_b398eff2ffc06d18 \nWHERE enterprise_autho'
        'ritative_artifacts_b398eff2ffc06d18.tenant_id = shared_enterprise_quality_is'
        'sue_versions.tenant_id AND enterprise_authoritative_artifacts_b398eff2ffc06d'
        "18.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id') AS UUID)"
        ")))) AND ((shared_enterprise_quality_issue_versions.issue_snapshot['capa']) "
        "->> 'id') IS NOT NULL)\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterp"
        'rise_sources_b398eff2ffc06d18 \nWHERE authoritative_enterprise_sources_b398e'
        'ff2ffc06d18.tenant_id = t AND authoritative_enterprise_sources_b398eff2ffc06'
        'd18.category_id = c AND CAST(authoritative_enterprise_sources_b398eff2ffc06d'
        "18.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterp"
        "rise_sources_b398eff2ffc06d18.source_revision AS TEXT) = expected->>'source_"
        "revision' AND authoritative_enterprise_sources_b398eff2ffc06d18.content_hash"
        " = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'change' THEN\n"
        "  WITH enterprise_authoritative_artifacts_12ea12eace7d655f AS \n(SELECT 'art"
        "ifact' AS source_type, artifact_versions.id AS source_id, artifact_versions."
        'tenant_id AS tenant_id, artifact_versions.category_id AS category_id, artifa'
        'ct_versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, artif'
        'act_versions.revision AS source_revision, artifact_versions.title AS title, '
        'artifact_versions.content_hash AS content_hash, artifact_versions.content AS'
        " body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_ve"
        "rsions.visibility != 'category' OR coalesce(products.visibility != 'category"
        "', false) OR coalesce(uploaded_originals.visibility != 'category', false) AS"
        ' private, artifact_versions.original_id IS NOT NULL AS customer_original, tr'
        'ue AS is_current, artifact_versions.created_at AS created_at, artifact_versi'
        'ons.original_id AS original_id, artifact_versions.id AS object_id, CASE WHEN'
        ' (artifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.or'
        "iginal_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis"
        '_status \nFROM artifact_versions LEFT OUTER JOIN products ON products.tenant'
        '_id = artifact_versions.tenant_id AND products.id = artifact_versions.produc'
        't_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = ar'
        'tifact_versions.tenant_id AND uploaded_originals.id = artifact_versions.orig'
        'inal_id AND uploaded_originals.category_id = artifact_versions.category_id A'
        'ND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.prod'
        'uct_id LEFT OUTER JOIN original_security ON original_security.tenant_id = up'
        'loaded_originals.tenant_id AND original_security.original_id = uploaded_orig'
        "inals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_setting('"
        "pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status = 'active'"
        ' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.produc'
        't_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id '
        'IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status ='
        " 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_security"
        ".source_state = 'active' AND original_security.disposition = 'active' AND or"
        'iginal_security.current_request_id IS NOT NULL)), \nshared_enterprise_change'
        '_request_versions AS MATERIALIZED \n(SELECT change_request_versions.product_'
        'id AS product_id, change_request_versions.project_id AS project_id, change_r'
        'equest_versions.change_id AS change_id, change_request_versions.revision AS '
        'revision, change_request_versions.previous_version_id AS previous_version_id'
        ', change_request_versions.previous_revision AS previous_revision, change_req'
        'uest_versions.owner_id AS owner_id, change_request_versions.visibility AS vi'
        'sibility, change_request_versions.status AS status, change_request_versions.'
        'operation AS operation, change_request_versions.intent_digest AS intent_dige'
        'st, change_request_versions.request_snapshot AS request_snapshot, change_req'
        'uest_versions.request_sha256 AS request_sha256, change_request_versions.sour'
        'ces AS sources, change_request_versions.required_source_read_set AS required'
        '_source_read_set, change_request_versions.source_basis AS source_basis, chan'
        'ge_request_versions.authority_snapshot AS authority_snapshot, change_request'
        '_versions.id AS id, change_request_versions.tenant_id AS tenant_id, change_r'
        'equest_versions.created_at AS created_at, change_request_versions.category_i'
        'd AS category_id \nFROM change_request_versions \nWHERE change_request_versi'
        "ons.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS "
        'UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT projects.prod'
        'uct_id AS product_id, projects.owner_id AS owner_id, projects.name AS name, '
        'projects.purpose AS purpose, projects.scope AS scope, projects.visibility AS'
        ' visibility, projects.status AS status, projects.revision AS revision, proje'
        'cts.current_plan_id AS current_plan_id, projects.trigger_type AS trigger_typ'
        'e, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0_decision'
        '_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.created_at'
        ' AS created_at, projects.category_id AS category_id \nFROM projects \nWHERE '
        "projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), ''"
        ') AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT products'
        '.name AS name, products.purpose AS purpose, products.revision AS revision, p'
        'roducts.lifecycle_epoch AS lifecycle_epoch, products.status AS status, produ'
        'cts.owner_id AS owner_id, products.parent_product_id AS parent_product_id, p'
        'roducts.category_id AS category_id, products.visibility AS visibility, produ'
        'cts.target_price AS target_price, products.target_price_currency AS target_p'
        'rice_currency, products.target_price_basis AS target_price_basis, products.t'
        'arget_price_includes_tax AS target_price_includes_tax, products.target_price'
        '_as_of AS target_price_as_of, products.id AS id, products.tenant_id AS tenan'
        't_id, products.created_at AS created_at \nFROM products \nWHERE products.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)),"
        ' \nshared_enterprise_change_request_currents AS MATERIALIZED \n(SELECT chang'
        'e_request_currents.product_id AS product_id, change_request_currents.change_'
        'id AS change_id, change_request_currents.version_id AS version_id, change_re'
        'quest_currents.revision AS revision, change_request_currents.id AS id, chang'
        'e_request_currents.tenant_id AS tenant_id, change_request_currents.created_a'
        't AS created_at, change_request_currents.category_id AS category_id \nFROM c'
        'hange_request_currents \nWHERE change_request_currents.tenant_id = CAST(null'
        "if(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritative_e"
        "nterprise_sources_12ea12eace7d655f AS \n(SELECT 'change' AS source_type, sha"
        'red_enterprise_change_request_versions.id AS source_id, shared_enterprise_ch'
        'ange_request_versions.tenant_id AS tenant_id, shared_enterprise_change_reque'
        'st_versions.category_id AS category_id, shared_enterprise_change_request_ver'
        'sions.product_id AS product_id, shared_enterprise_change_request_versions.pr'
        'oject_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise'
        '_change_request_versions.owner_id AS owner_id, shared_enterprise_change_requ'
        'est_versions.revision AS source_revision, shared_enterprise_change_request_v'
        "ersions.request_snapshot ->> 'title' AS title, encode(sha256(convert_to(CAST"
        "(CAST(jsonb_build_object('object_id', shared_enterprise_change_request_versi"
        "ons.change_id, 'kind', 'change', 'facts', jsonb_build_object('id', shared_en"
        "terprise_change_request_versions.request_snapshot['id'], 'title', shared_ent"
        "erprise_change_request_versions.request_snapshot['title'], 'reason', shared_"
        "enterprise_change_request_versions.request_snapshot['reason'], 'status', sha"
        "red_enterprise_change_request_versions.request_snapshot['status'], 'needs_re"
        "check', shared_enterprise_change_request_versions.request_snapshot['needs_re"
        "check'], 'recheck_reasons', shared_enterprise_change_request_versions.reques"
        "t_snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coale"
        "sce(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'],"
        " 'plan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterpris"
        "e_change_items.value['id'], 'discipline', enterprise_change_items.value['dis"
        "cipline'], 'verification_requirement', enterprise_change_items.value['verifi"
        "cation_requirement'], 'intent_kind', enterprise_change_items.value['intent']"
        "['kind']) ORDER BY enterprise_change_items.ordinal), jsonb_build_array()) AS"
        ' coalesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.va'
        "lue['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_ch"
        "ange_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('actor_id', enterprise_change_approvals.value['actor_id'], 'at',"
        " enterprise_change_approvals.value['at'], 'discipline', enterprise_change_ap"
        "provals.value['discipline'], 'text', enterprise_change_approvals.value['text"
        "']) ORDER BY enterprise_change_approvals.ordinal), jsonb_build_array()) AS c"
        'oalesce_3 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.valu'
        "e['approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_a"
        "pprovals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('item_id', enterprise_change_implementations.value['item_id'"
        "], 'executor_id', enterprise_change_implementations.value['executor_id'], 'o"
        "utcome', enterprise_change_implementations.value['outcome'], 'occurred_at', "
        "enterprise_change_implementations.value['occurred_at'], 'received_at', enter"
        "prise_change_implementations.value['received_at'], 'note', enterprise_change"
        "_implementations.value['note']) ORDER BY enterprise_change_implementations.o"
        'rdinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coal'
        "esce(enterprise_change_orders.value['implementations'], CAST('[]' AS JSONB))"
        ") WITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), 'ef"
        "fectivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterpr"
        "ise_change_effectivity.value['item_id'], 'stage', enterprise_change_effectiv"
        "ity.value['stage'], 'outcome', enterprise_change_effectivity.value['outcome'"
        "], 'covered_units', enterprise_change_effectivity.value['covered_units'], 'o"
        "ccurred_at', enterprise_change_effectivity.value['occurred_at'], 'received_a"
        "t', enterprise_change_effectivity.value['received_at']) ORDER BY enterprise_"
        'change_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 \nFROM jsonb'
        "_array_elements(coalesce(enterprise_change_orders.value['effectivity'], CAST"
        "('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, or"
        "dinal)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('act"
        "or_id', enterprise_change_verifications.value['actor_id'], 'at', enterprise_"
        "change_verifications.value['at'], 'text', enterprise_change_verifications.va"
        "lue['text'], 'result', enterprise_change_verifications.value['fact']['result"
        "'], 'applicable_as_recorded', enterprise_change_verifications.value['fact']["
        "'applicable']) ORDER BY enterprise_change_verifications.ordinal), jsonb_buil"
        'd_array()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterprise_cha'
        "nge_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY AS "
        "enterprise_change_verifications(value, ordinal)), 'closure', jsonb_build_obj"
        "ect('text', enterprise_change_orders.value['closure']['text'], 'actor_id', e"
        "nterprise_change_orders.value['closure']['actor_id'], 'at', enterprise_chang"
        "e_orders.value['closure']['at'])) ORDER BY enterprise_change_orders.ordinal)"
        ', jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_ente'
        "rprise_change_request_versions.request_snapshot['orders']) WITH ORDINALITY A"
        "S enterprise_change_orders(value, ordinal))), 'source_refs', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_ch"
        "ange.value['artifact_id'], 'version', enterprise_reads_change.value['expecte"
        "d_revision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', ente"
        "rprise_reads_change.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_7 \nFROM jsonb_array_elements(shared_enterprise_change_request_vers'
        "ions.required_source_read_set) AS enterprise_reads_change(value)), 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CA"
        "ST(jsonb_build_object('object_id', shared_enterprise_change_request_versions"
        ".change_id, 'kind', 'change', 'facts', jsonb_build_object('id', shared_enter"
        "prise_change_request_versions.request_snapshot['id'], 'title', shared_enterp"
        "rise_change_request_versions.request_snapshot['title'], 'reason', shared_ent"
        "erprise_change_request_versions.request_snapshot['reason'], 'status', shared"
        "_enterprise_change_request_versions.request_snapshot['status'], 'needs_reche"
        "ck', shared_enterprise_change_request_versions.request_snapshot['needs_reche"
        "ck'], 'recheck_reasons', shared_enterprise_change_request_versions.request_s"
        "napshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coalesce"
        "(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'], 'p"
        "lan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_c"
        "hange_items.value['id'], 'discipline', enterprise_change_items.value['discip"
        "line'], 'verification_requirement', enterprise_change_items.value['verificat"
        "ion_requirement'], 'intent_kind', enterprise_change_items.value['intent']['k"
        "ind']) ORDER BY enterprise_change_items.ordinal), jsonb_build_array()) AS co"
        'alesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value'
        "['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_chang"
        "e_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('actor_id', enterprise_change_approvals.value['actor_id'], 'at', en"
        "terprise_change_approvals.value['at'], 'discipline', enterprise_change_appro"
        "vals.value['discipline'], 'text', enterprise_change_approvals.value['text'])"
        ' ORDER BY enterprise_change_approvals.ordinal), jsonb_build_array()) AS coal'
        "esce_3 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['"
        "approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_appr"
        "ovals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('item_id', enterprise_change_implementations.value['item_id'], "
        "'executor_id', enterprise_change_implementations.value['executor_id'], 'outc"
        "ome', enterprise_change_implementations.value['outcome'], 'occurred_at', ent"
        "erprise_change_implementations.value['occurred_at'], 'received_at', enterpri"
        "se_change_implementations.value['received_at'], 'note', enterprise_change_im"
        "plementations.value['note']) ORDER BY enterprise_change_implementations.ordi"
        'nal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesc'
        "e(enterprise_change_orders.value['implementations'], CAST('[]' AS JSONB))) W"
        "ITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), 'effec"
        "tivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterprise"
        "_change_effectivity.value['item_id'], 'stage', enterprise_change_effectivity"
        ".value['stage'], 'outcome', enterprise_change_effectivity.value['outcome'], "
        "'covered_units', enterprise_change_effectivity.value['covered_units'], 'occu"
        "rred_at', enterprise_change_effectivity.value['occurred_at'], 'received_at',"
        " enterprise_change_effectivity.value['received_at']) ORDER BY enterprise_cha"
        'nge_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_ar'
        "ray_elements(coalesce(enterprise_change_orders.value['effectivity'], CAST('["
        "]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, ordin"
        "al)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_"
        "id', enterprise_change_verifications.value['actor_id'], 'at', enterprise_cha"
        "nge_verifications.value['at'], 'text', enterprise_change_verifications.value"
        "['text'], 'result', enterprise_change_verifications.value['fact']['result'],"
        " 'applicable_as_recorded', enterprise_change_verifications.value['fact']['ap"
        "plicable']) ORDER BY enterprise_change_verifications.ordinal), jsonb_build_a"
        'rray()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterprise_change'
        "_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY AS ent"
        "erprise_change_verifications(value, ordinal)), 'closure', jsonb_build_object"
        "('text', enterprise_change_orders.value['closure']['text'], 'actor_id', ente"
        "rprise_change_orders.value['closure']['actor_id'], 'at', enterprise_change_o"
        "rders.value['closure']['at'])) ORDER BY enterprise_change_orders.ordinal), j"
        'sonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterpr'
        "ise_change_request_versions.request_snapshot['orders']) WITH ORDINALITY AS e"
        "nterprise_change_orders(value, ordinal))), 'source_refs', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_chang"
        "e.value['artifact_id'], 'version', enterprise_reads_change.value['expected_r"
        "evision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', enterpr"
        "ise_reads_change.value ->> 'expected_revision'), jsonb_build_array()) AS coa"
        'lesce_7 \nFROM jsonb_array_elements(shared_enterprise_change_request_version'
        "s.required_source_read_set) AS enterprise_reads_change(value)), 'record_poli"
        "cy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_change_request_versions.change_id, 'kind', 'change', '"
        "facts', jsonb_build_object('id', shared_enterprise_change_request_versions.r"
        "equest_snapshot['id'], 'title', shared_enterprise_change_request_versions.re"
        "quest_snapshot['title'], 'reason', shared_enterprise_change_request_versions"
        ".request_snapshot['reason'], 'status', shared_enterprise_change_request_vers"
        "ions.request_snapshot['status'], 'needs_recheck', shared_enterprise_change_r"
        "equest_versions.request_snapshot['needs_recheck'], 'recheck_reasons', shared"
        "_enterprise_change_request_versions.request_snapshot['recheck_reasons']) || "
        "jsonb_build_object('orders', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "id', enterprise_change_orders.value['id'], 'plan_items', (SELECT coalesce(js"
        "onb_agg(jsonb_build_object('id', enterprise_change_items.value['id'], 'disci"
        "pline', enterprise_change_items.value['discipline'], 'verification_requireme"
        "nt', enterprise_change_items.value['verification_requirement'], 'intent_kind"
        "', enterprise_change_items.value['intent']['kind']) ORDER BY enterprise_chan"
        'ge_items.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_ele'
        "ments(coalesce(enterprise_change_orders.value['plan']['items'], CAST('[]' AS"
        " JSONB))) WITH ORDINALITY AS enterprise_change_items(value, ordinal)), 'appr"
        "ovals', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise"
        "_change_approvals.value['actor_id'], 'at', enterprise_change_approvals.value"
        "['at'], 'discipline', enterprise_change_approvals.value['discipline'], 'text"
        "', enterprise_change_approvals.value['text']) ORDER BY enterprise_change_app"
        'rovals.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_eleme'
        "nts(coalesce(enterprise_change_orders.value['approvals'], CAST('[]' AS JSONB"
        "))) WITH ORDINALITY AS enterprise_change_approvals(value, ordinal)), 'implem"
        "entations', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterpr"
        "ise_change_implementations.value['item_id'], 'executor_id', enterprise_chang"
        "e_implementations.value['executor_id'], 'outcome', enterprise_change_impleme"
        "ntations.value['outcome'], 'occurred_at', enterprise_change_implementations."
        "value['occurred_at'], 'received_at', enterprise_change_implementations.value"
        "['received_at'], 'note', enterprise_change_implementations.value['note']) OR"
        'DER BY enterprise_change_implementations.ordinal), jsonb_build_array()) AS c'
        'oalesce_4 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.valu'
        "e['implementations'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_ch"
        "ange_implementations(value, ordinal)), 'effectivity', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('item_id', enterprise_change_effectivity.value['item"
        "_id'], 'stage', enterprise_change_effectivity.value['stage'], 'outcome', ent"
        "erprise_change_effectivity.value['outcome'], 'covered_units', enterprise_cha"
        "nge_effectivity.value['covered_units'], 'occurred_at', enterprise_change_eff"
        "ectivity.value['occurred_at'], 'received_at', enterprise_change_effectivity."
        "value['received_at']) ORDER BY enterprise_change_effectivity.ordinal), jsonb"
        '_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(coalesce(enterpris'
        "e_change_orders.value['effectivity'], CAST('[]' AS JSONB))) WITH ORDINALITY "
        "AS enterprise_change_effectivity(value, ordinal)), 'verifications', (SELECT "
        "coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise_change_verifica"
        "tions.value['actor_id'], 'at', enterprise_change_verifications.value['at'], "
        "'text', enterprise_change_verifications.value['text'], 'result', enterprise_"
        "change_verifications.value['fact']['result'], 'applicable_as_recorded', ente"
        "rprise_change_verifications.value['fact']['applicable']) ORDER BY enterprise"
        '_change_verifications.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM js'
        "onb_array_elements(coalesce(enterprise_change_orders.value['verifications'],"
        " CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_verifications(va"
        "lue, ordinal)), 'closure', jsonb_build_object('text', enterprise_change_orde"
        "rs.value['closure']['text'], 'actor_id', enterprise_change_orders.value['clo"
        "sure']['actor_id'], 'at', enterprise_change_orders.value['closure']['at'])) "
        'ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesce'
        '_1 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.req'
        "uest_snapshot['orders']) WITH ORDINALITY AS enterprise_change_orders(value, "
        "ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('ty"
        "pe', 'artifact', 'id', enterprise_reads_change.value['artifact_id'], 'versio"
        "n', enterprise_reads_change.value['expected_revision']) ORDER BY enterprise_"
        "reads_change.value ->> 'artifact_id', enterprise_reads_change.value ->> 'exp"
        "ected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_elem"
        'ents(shared_enterprise_change_request_versions.required_source_read_set) AS '
        "enterprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS struct"
        "ured, 'structured' AS nature, shared_enterprise_change_request_versions.visi"
        "bility != 'category' OR coalesce(shared_enterprise_projects.visibility != 'c"
        "ategory', false) OR coalesce(shared_enterprise_products.visibility != 'categ"
        "ory', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr"
        'ise_change_request_versions.required_source_read_set) AS enterprise_reads_ch'
        'ange(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON ente'
        'rprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_enterpris'
        'e_change_request_versions.tenant_id AND enterprise_authoritative_artifacts_1'
        "2ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'artifac"
        "t_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f."
        'private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_en'
        'terprise_change_request_versions.required_source_read_set) AS enterprise_rea'
        'ds_change(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON'
        ' enterprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_ente'
        'rprise_change_request_versions.tenant_id AND enterprise_authoritative_artifa'
        "cts_12ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d"
        '655f.customer_original) AS customer_original, shared_enterprise_change_reque'
        'st_currents.version_id = shared_enterprise_change_request_versions.id AS is_'
        'current, shared_enterprise_change_request_versions.created_at AS created_at,'
        ' CAST(NULL AS UUID) AS original_id, shared_enterprise_change_request_version'
        's.change_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritativ'
        'e_artifacts_12ea12eace7d655f.original_id), ARRAY[]::UUID[]) AS coalesce_8 \n'
        'FROM jsonb_array_elements(shared_enterprise_change_request_versions.required'
        '_source_read_set) AS enterprise_reads_change(value) JOIN enterprise_authorit'
        'ative_artifacts_12ea12eace7d655f ON enterprise_authoritative_artifacts_12ea1'
        '2eace7d655f.tenant_id = shared_enterprise_change_request_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_12ea12eace7d655f.source_id = CAST((en'
        "terprise_reads_change.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_a"
        'uthoritative_artifacts_12ea12eace7d655f.original_id IS NOT NULL) AS original'
        '_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpr'
        'ise_change_request_versions.required_source_read_set) AS enterprise_reads_ch'
        'ange(value) JOIN enterprise_authoritative_artifacts_12ea12eace7d655f ON ente'
        'rprise_authoritative_artifacts_12ea12eace7d655f.tenant_id = shared_enterpris'
        'e_change_request_versions.tenant_id AND enterprise_authoritative_artifacts_1'
        "2ea12eace7d655f.source_id = CAST((enterprise_reads_change.value ->> 'artifac"
        "t_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f."
        "source_revision != CAST((enterprise_reads_change.value ->> 'expected_revisio"
        "n') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_stat"
        'us \nFROM shared_enterprise_change_request_versions JOIN shared_enterprise_p'
        'rojects ON shared_enterprise_projects.tenant_id = shared_enterprise_change_r'
        'equest_versions.tenant_id AND shared_enterprise_projects.product_id = shared'
        '_enterprise_change_request_versions.product_id AND shared_enterprise_project'
        's.id = shared_enterprise_change_request_versions.project_id AND shared_enter'
        'prise_projects.category_id = shared_enterprise_change_request_versions.categ'
        'ory_id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_'
        'id = shared_enterprise_change_request_versions.tenant_id AND shared_enterpri'
        'se_products.id = shared_enterprise_change_request_versions.product_id AND sh'
        'ared_enterprise_products.category_id = shared_enterprise_change_request_vers'
        'ions.category_id JOIN shared_enterprise_change_request_currents ON shared_en'
        'terprise_change_request_currents.tenant_id = shared_enterprise_change_reques'
        't_versions.tenant_id AND shared_enterprise_change_request_currents.product_i'
        'd = shared_enterprise_change_request_versions.product_id AND shared_enterpri'
        'se_change_request_currents.change_id = shared_enterprise_change_request_vers'
        'ions.change_id \nWHERE shared_enterprise_change_request_versions.tenant_id ='
        " CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT ("
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_change_reques'
        't_versions.required_source_read_set) AS enterprise_reads_change(value) \nWHE'
        'RE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_12ea12eac'
        'e7d655f \nWHERE enterprise_authoritative_artifacts_12ea12eace7d655f.tenant_i'
        'd = shared_enterprise_change_request_versions.tenant_id AND enterprise_autho'
        'ritative_artifacts_12ea12eace7d655f.source_id = CAST((enterprise_reads_chang'
        "e.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM au"
        'thoritative_enterprise_sources_12ea12eace7d655f \nWHERE authoritative_enterp'
        'rise_sources_12ea12eace7d655f.tenant_id = t AND authoritative_enterprise_sou'
        'rces_12ea12eace7d655f.category_id = c AND CAST(authoritative_enterprise_sour'
        "ces_12ea12eace7d655f.source_id AS TEXT) = expected->>'source_id' AND CAST(au"
        'thoritative_enterprise_sources_12ea12eace7d655f.source_revision AS TEXT) = e'
        "xpected->>'source_revision' AND authoritative_enterprise_sources_12ea12eace7"
        "d655f.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WH"
        "EN 'external_wait' THEN\n  WITH enterprise_authoritative_artifacts_b3e531ff7"
        "3e706c8 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sour"
        'ce_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category_'
        'id AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS '
        'UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.ow'
        'ner_id AS owner_id, artifact_versions.revision AS source_revision, artifact_'
        'versions.title AS title, artifact_versions.content_hash AS content_hash, art'
        "ifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untruste"
        "d' AS nature, artifact_versions.visibility != 'category' OR coalesce(product"
        "s.visibility != 'category', false) OR coalesce(uploaded_originals.visibility"
        " != 'category', false) AS private, artifact_versions.original_id IS NOT NULL"
        ' AS customer_original, true AS is_current, artifact_versions.created_at AS c'
        'reated_at, artifact_versions.original_id AS original_id, artifact_versions.i'
        'd AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN A'
        'RRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids'
        ", 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN pr"
        'oducts ON products.tenant_id = artifact_versions.tenant_id AND products.id ='
        ' artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded'
        '_originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id'
        ' = artifact_versions.original_id AND uploaded_originals.category_id = artifa'
        'ct_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT FR'
        'OM artifact_versions.product_id LEFT OUTER JOIN original_security ON origina'
        'l_security.tenant_id = uploaded_originals.tenant_id AND original_security.or'
        'iginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_v"
        "ersions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND "
        '(artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artif'
        'act_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND up'
        "loaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'cle"
        "an' AND original_security.source_state = 'active' AND original_security.disp"
        "osition = 'active' AND original_security.current_request_id IS NOT NULL)), "
        '\nshared_enterprise_external_wait_versions AS MATERIALIZED \n(SELECT externa'
        'l_wait_versions.wait_id AS wait_id, external_wait_versions.previous_id AS pr'
        'evious_id, external_wait_versions.previous_revision AS previous_revision, ex'
        'ternal_wait_versions.action AS action, external_wait_versions.state AS state'
        ', external_wait_versions.revision AS revision, external_wait_versions.writer'
        '_id AS writer_id, external_wait_versions.actor_id AS actor_id, external_wait'
        '_versions.requester_id AS requester_id, external_wait_versions.operation AS '
        'operation, external_wait_versions.command_id AS command_id, external_wait_ve'
        'rsions.command AS command, external_wait_versions.sources AS sources, extern'
        'al_wait_versions.reads AS reads, external_wait_versions.source_basis AS sour'
        'ce_basis, external_wait_versions.body AS body, external_wait_versions.body_s'
        'ha256 AS body_sha256, external_wait_versions.intent_digest AS intent_digest,'
        ' external_wait_versions.request_digest AS request_digest, external_wait_vers'
        'ions.receipt_id AS receipt_id, external_wait_versions.confirmation_id AS con'
        'firmation_id, external_wait_versions.product_id AS product_id, external_wait'
        '_versions.project_id AS project_id, external_wait_versions.owner_id AS owner'
        '_id, external_wait_versions.visibility AS visibility, external_wait_versions'
        '.id AS id, external_wait_versions.tenant_id AS tenant_id, external_wait_vers'
        'ions.created_at AS created_at, external_wait_versions.category_id AS categor'
        'y_id \nFROM external_wait_versions \nWHERE external_wait_versions.tenant_id '
        "= CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshar"
        'ed_enterprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS prod'
        'uct_id, projects.owner_id AS owner_id, projects.name AS name, projects.purpo'
        'se AS purpose, projects.scope AS scope, projects.visibility AS visibility, p'
        'rojects.status AS status, projects.revision AS revision, projects.current_pl'
        'an_id AS current_plan_id, projects.trigger_type AS trigger_type, projects.tr'
        'igger_id AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.'
        'id AS id, projects.tenant_id AS tenant_id, projects.created_at AS created_at'
        ', projects.category_id AS category_id \nFROM projects \nWHERE projects.tenan'
        "t_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), "
        '\nshared_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name'
        ', products.purpose AS purpose, products.revision AS revision, products.lifec'
        'ycle_epoch AS lifecycle_epoch, products.status AS status, products.owner_id '
        'AS owner_id, products.parent_product_id AS parent_product_id, products.categ'
        'ory_id AS category_id, products.visibility AS visibility, products.target_pr'
        'ice AS target_price, products.target_price_currency AS target_price_currency'
        ', products.target_price_basis AS target_price_basis, products.target_price_i'
        'ncludes_tax AS target_price_includes_tax, products.target_price_as_of AS tar'
        'get_price_as_of, products.id AS id, products.tenant_id AS tenant_id, product'
        's.created_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_external_wait_currents AS MATERIALIZED \n(SELECT external_wait_curre'
        'nts.wait_id AS wait_id, external_wait_currents.version_id AS version_id, ext'
        'ernal_wait_currents.revision AS revision, external_wait_currents.state AS st'
        'ate, external_wait_currents.product_id AS product_id, external_wait_currents'
        '.project_id AS project_id, external_wait_currents.owner_id AS owner_id, exte'
        'rnal_wait_currents.visibility AS visibility, external_wait_currents.id AS id'
        ', external_wait_currents.tenant_id AS tenant_id, external_wait_currents.crea'
        'ted_at AS created_at, external_wait_currents.category_id AS category_id \nFR'
        'OM external_wait_currents \nWHERE external_wait_currents.tenant_id = CAST(nu'
        "llif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritative"
        "_enterprise_sources_b3e531ff73e706c8 AS \n(SELECT 'external_wait' AS source_"
        'type, shared_enterprise_external_wait_versions.id AS source_id, shared_enter'
        'prise_external_wait_versions.tenant_id AS tenant_id, shared_enterprise_exter'
        'nal_wait_versions.category_id AS category_id, shared_enterprise_external_wai'
        't_versions.product_id AS product_id, shared_enterprise_external_wait_version'
        's.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterp'
        'rise_external_wait_versions.owner_id AS owner_id, shared_enterprise_external'
        '_wait_versions.revision AS source_revision, shared_enterprise_external_wait_'
        "versions.body ->> 'title' AS title, encode(sha256(convert_to(CAST(CAST(jsonb"
        "_build_object('object_id', shared_enterprise_external_wait_versions.wait_id,"
        " 'kind', 'external_wait', 'facts', jsonb_build_object('wait', jsonb_build_ob"
        "ject('wait_id', shared_enterprise_external_wait_versions.body['wait_id'], 'r"
        "evision', shared_enterprise_external_wait_versions.body['revision'], 'state'"
        ", shared_enterprise_external_wait_versions.body['state'], 'responsible_id', "
        "shared_enterprise_external_wait_versions.body['responsible_id'], 'title', sh"
        "ared_enterprise_external_wait_versions.body['title'], 'target', shared_enter"
        "prise_external_wait_versions.body['target'], 'request_content', shared_enter"
        "prise_external_wait_versions.body['request_content'], 'closure_condition', s"
        "hared_enterprise_external_wait_versions.body['closure_condition'], 'blocking"
        "', shared_enterprise_external_wait_versions.body['blocking'], 'next_check_at"
        "', shared_enterprise_external_wait_versions.body['next_check_at'], 'original"
        "_timezone', shared_enterprise_external_wait_versions.body['original_timezone"
        "']), 'delivery', jsonb_build_object('at', shared_enterprise_external_wait_ve"
        "rsions.body['delivery']['at'], 'status', shared_enterprise_external_wait_ver"
        "sions.body['delivery']['status'], 'time_basis', shared_enterprise_external_w"
        "ait_versions.body['delivery']['time_basis']), 'commitment', jsonb_build_obje"
        "ct('promised_at', shared_enterprise_external_wait_versions.body['counterpart"
        "y_commitment']['promised_at'], 'original_timezone', shared_enterprise_extern"
        "al_wait_versions.body['counterparty_commitment']['original_timezone']), 'rep"
        "ly', jsonb_build_object('at', shared_enterprise_external_wait_versions.body["
        "'reply']['at'], 'status', shared_enterprise_external_wait_versions.body['rep"
        "ly']['status'], 'time_basis', shared_enterprise_external_wait_versions.body["
        "'reply']['time_basis'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_bu"
        "ild_object('type', 'artifact', 'id', enterprise_reads_external_wait.value['a"
        "rtifact_id'], 'version', enterprise_reads_external_wait.value['expected_revi"
        "sion']) ORDER BY enterprise_reads_external_wait.value ->> 'artifact_id', ent"
        "erprise_reads_external_wait.value ->> 'expected_revision'), jsonb_build_arra"
        'y()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_wa'
        "it_versions.reads) AS enterprise_reads_external_wait(value)), 'record_policy"
        "', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jso"
        "nb_build_object('object_id', shared_enterprise_external_wait_versions.wait_i"
        "d, 'kind', 'external_wait', 'facts', jsonb_build_object('wait', jsonb_build_"
        "object('wait_id', shared_enterprise_external_wait_versions.body['wait_id'], "
        "'revision', shared_enterprise_external_wait_versions.body['revision'], 'stat"
        "e', shared_enterprise_external_wait_versions.body['state'], 'responsible_id'"
        ", shared_enterprise_external_wait_versions.body['responsible_id'], 'title', "
        "shared_enterprise_external_wait_versions.body['title'], 'target', shared_ent"
        "erprise_external_wait_versions.body['target'], 'request_content', shared_ent"
        "erprise_external_wait_versions.body['request_content'], 'closure_condition',"
        " shared_enterprise_external_wait_versions.body['closure_condition'], 'blocki"
        "ng', shared_enterprise_external_wait_versions.body['blocking'], 'next_check_"
        "at', shared_enterprise_external_wait_versions.body['next_check_at'], 'origin"
        "al_timezone', shared_enterprise_external_wait_versions.body['original_timezo"
        "ne']), 'delivery', jsonb_build_object('at', shared_enterprise_external_wait_"
        "versions.body['delivery']['at'], 'status', shared_enterprise_external_wait_v"
        "ersions.body['delivery']['status'], 'time_basis', shared_enterprise_external"
        "_wait_versions.body['delivery']['time_basis']), 'commitment', jsonb_build_ob"
        "ject('promised_at', shared_enterprise_external_wait_versions.body['counterpa"
        "rty_commitment']['promised_at'], 'original_timezone', shared_enterprise_exte"
        "rnal_wait_versions.body['counterparty_commitment']['original_timezone']), 'r"
        "eply', jsonb_build_object('at', shared_enterprise_external_wait_versions.bod"
        "y['reply']['at'], 'status', shared_enterprise_external_wait_versions.body['r"
        "eply']['status'], 'time_basis', shared_enterprise_external_wait_versions.bod"
        "y['reply']['time_basis'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('type', 'artifact', 'id', enterprise_reads_external_wait.value["
        "'artifact_id'], 'version', enterprise_reads_external_wait.value['expected_re"
        "vision']) ORDER BY enterprise_reads_external_wait.value ->> 'artifact_id', e"
        "nterprise_reads_external_wait.value ->> 'expected_revision'), jsonb_build_ar"
        'ray()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_'
        "wait_versions.reads) AS enterprise_reads_external_wait(value)), 'record_poli"
        "cy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_external_wait_versions.wait_id, 'kind', 'external_wait"
        "', 'facts', jsonb_build_object('wait', jsonb_build_object('wait_id', shared_"
        "enterprise_external_wait_versions.body['wait_id'], 'revision', shared_enterp"
        "rise_external_wait_versions.body['revision'], 'state', shared_enterprise_ext"
        "ernal_wait_versions.body['state'], 'responsible_id', shared_enterprise_exter"
        "nal_wait_versions.body['responsible_id'], 'title', shared_enterprise_externa"
        "l_wait_versions.body['title'], 'target', shared_enterprise_external_wait_ver"
        "sions.body['target'], 'request_content', shared_enterprise_external_wait_ver"
        "sions.body['request_content'], 'closure_condition', shared_enterprise_extern"
        "al_wait_versions.body['closure_condition'], 'blocking', shared_enterprise_ex"
        "ternal_wait_versions.body['blocking'], 'next_check_at', shared_enterprise_ex"
        "ternal_wait_versions.body['next_check_at'], 'original_timezone', shared_ente"
        "rprise_external_wait_versions.body['original_timezone']), 'delivery', jsonb_"
        "build_object('at', shared_enterprise_external_wait_versions.body['delivery']"
        "['at'], 'status', shared_enterprise_external_wait_versions.body['delivery']["
        "'status'], 'time_basis', shared_enterprise_external_wait_versions.body['deli"
        "very']['time_basis']), 'commitment', jsonb_build_object('promised_at', share"
        "d_enterprise_external_wait_versions.body['counterparty_commitment']['promise"
        "d_at'], 'original_timezone', shared_enterprise_external_wait_versions.body['"
        "counterparty_commitment']['original_timezone']), 'reply', jsonb_build_object"
        "('at', shared_enterprise_external_wait_versions.body['reply']['at'], 'status"
        "', shared_enterprise_external_wait_versions.body['reply']['status'], 'time_b"
        "asis', shared_enterprise_external_wait_versions.body['reply']['time_basis'])"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'art"
        "ifact', 'id', enterprise_reads_external_wait.value['artifact_id'], 'version'"
        ", enterprise_reads_external_wait.value['expected_revision']) ORDER BY enterp"
        "rise_reads_external_wait.value ->> 'artifact_id', enterprise_reads_external_"
        "wait.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFR"
        'OM jsonb_array_elements(shared_enterprise_external_wait_versions.reads) AS e'
        "nterprise_reads_external_wait(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_external_wait_versions"
        ".visibility != 'category' OR coalesce(shared_enterprise_projects.visibility "
        "!= 'category', false) OR coalesce(shared_enterprise_products.visibility != '"
        "category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_en"
        'terprise_external_wait_versions.reads) AS enterprise_reads_external_wait(val'
        'ue) JOIN enterprise_authoritative_artifacts_b3e531ff73e706c8 ON enterprise_a'
        'uthoritative_artifacts_b3e531ff73e706c8.tenant_id = shared_enterprise_extern'
        'al_wait_versions.tenant_id AND enterprise_authoritative_artifacts_b3e531ff73'
        "e706c8.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifact_"
        "id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b3e531ff73e706c8.pr"
        'ivate)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ente'
        'rprise_external_wait_versions.reads) AS enterprise_reads_external_wait(value'
        ') JOIN enterprise_authoritative_artifacts_b3e531ff73e706c8 ON enterprise_aut'
        'horitative_artifacts_b3e531ff73e706c8.tenant_id = shared_enterprise_external'
        '_wait_versions.tenant_id AND enterprise_authoritative_artifacts_b3e531ff73e7'
        "06c8.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifact_id"
        "') AS UUID) \nWHERE enterprise_authoritative_artifacts_b3e531ff73e706c8.cust"
        'omer_original) AS customer_original, shared_enterprise_external_wait_current'
        's.version_id = shared_enterprise_external_wait_versions.id AS is_current, sh'
        'ared_enterprise_external_wait_versions.created_at AS created_at, CAST(NULL A'
        'S UUID) AS original_id, shared_enterprise_external_wait_versions.wait_id AS '
        'object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_b3e'
        '531ff73e706c8.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_arra'
        'y_elements(shared_enterprise_external_wait_versions.reads) AS enterprise_rea'
        'ds_external_wait(value) JOIN enterprise_authoritative_artifacts_b3e531ff73e7'
        '06c8 ON enterprise_authoritative_artifacts_b3e531ff73e706c8.tenant_id = shar'
        'ed_enterprise_external_wait_versions.tenant_id AND enterprise_authoritative_'
        'artifacts_b3e531ff73e706c8.source_id = CAST((enterprise_reads_external_wait.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        '_b3e531ff73e706c8.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXIST'
        'S (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_external_wait_vers'
        'ions.reads) AS enterprise_reads_external_wait(value) JOIN enterprise_authori'
        'tative_artifacts_b3e531ff73e706c8 ON enterprise_authoritative_artifacts_b3e5'
        '31ff73e706c8.tenant_id = shared_enterprise_external_wait_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_b3e531ff73e706c8.source_id = CAST((en'
        "terprise_reads_external_wait.value ->> 'artifact_id') AS UUID) \nWHERE enter"
        'prise_authoritative_artifacts_b3e531ff73e706c8.source_revision != CAST((ente'
        "rprise_reads_external_wait.value ->> 'expected_revision') AS INTEGER))) THEN"
        " 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enter"
        'prise_external_wait_versions JOIN shared_enterprise_projects ON shared_enter'
        'prise_projects.tenant_id = shared_enterprise_external_wait_versions.tenant_i'
        'd AND shared_enterprise_projects.product_id = shared_enterprise_external_wai'
        't_versions.product_id AND shared_enterprise_projects.id = shared_enterprise_'
        'external_wait_versions.project_id AND shared_enterprise_projects.category_id'
        ' = shared_enterprise_external_wait_versions.category_id JOIN shared_enterpri'
        'se_products ON shared_enterprise_products.tenant_id = shared_enterprise_exte'
        'rnal_wait_versions.tenant_id AND shared_enterprise_products.id = shared_ente'
        'rprise_external_wait_versions.product_id AND shared_enterprise_products.cate'
        'gory_id = shared_enterprise_external_wait_versions.category_id JOIN shared_e'
        'nterprise_external_wait_currents ON shared_enterprise_external_wait_currents'
        '.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND shared_e'
        'nterprise_external_wait_currents.product_id = shared_enterprise_external_wai'
        't_versions.product_id AND shared_enterprise_external_wait_currents.wait_id ='
        ' shared_enterprise_external_wait_versions.wait_id \nWHERE shared_enterprise_'
        "external_wait_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_"
        "id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_external_wait_versions.reads) AS enterprise_reads_exter'
        'nal_wait(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritativ'
        'e_artifacts_b3e531ff73e706c8 \nWHERE enterprise_authoritative_artifacts_b3e5'
        '31ff73e706c8.tenant_id = shared_enterprise_external_wait_versions.tenant_id '
        'AND enterprise_authoritative_artifacts_b3e531ff73e706c8.source_id = CAST((en'
        "terprise_reads_external_wait.value ->> 'artifact_id') AS UUID))))))\n SELECT"
        ' EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_b3e531ff73e706c8 '
        '\nWHERE authoritative_enterprise_sources_b3e531ff73e706c8.tenant_id = t AND '
        'authoritative_enterprise_sources_b3e531ff73e706c8.category_id = c AND CAST(a'
        'uthoritative_enterprise_sources_b3e531ff73e706c8.source_id AS TEXT) = expect'
        "ed->>'source_id' AND CAST(authoritative_enterprise_sources_b3e531ff73e706c8."
        "source_revision AS TEXT) = expected->>'source_revision' AND authoritative_en"
        "terprise_sources_b3e531ff73e706c8.content_hash = expected->>'content_hash') "
        "AS anon_1 INTO visible;\n WHEN 'supply' THEN\n  WITH enterprise_authoritativ"
        "e_artifacts_f30dfe1cfb6de6d1 AS \n(SELECT 'artifact' AS source_type, artifac"
        't_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, artifa'
        'ct_versions.category_id AS category_id, artifact_versions.product_id AS prod'
        'uct_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id,'
        ' artifact_versions.owner_id AS owner_id, artifact_versions.revision AS sourc'
        'e_revision, artifact_versions.title AS title, artifact_versions.content_hash'
        ' AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS '
        "structured, 'untrusted' AS nature, artifact_versions.visibility != 'category"
        "' OR coalesce(products.visibility != 'category', false) OR coalesce(uploaded"
        "_originals.visibility != 'category', false) AS private, artifact_versions.or"
        'iginal_id IS NOT NULL AS customer_original, true AS is_current, artifact_ver'
        'sions.created_at AS created_at, artifact_versions.original_id AS original_id'
        ', artifact_versions.id AS object_id, CASE WHEN (artifact_versions.original_i'
        'd IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID['
        "] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_versio"
        'ns LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.tenant'
        '_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN uploaded_'
        'originals ON uploaded_originals.tenant_id = artifact_versions.tenant_id AND '
        'uploaded_originals.id = artifact_versions.original_id AND uploaded_originals'
        '.category_id = artifact_versions.category_id AND uploaded_originals.product_'
        'id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN origina'
        'l_security ON original_security.tenant_id = uploaded_originals.tenant_id AND'
        ' original_security.original_id = uploaded_originals.id \nWHERE artifact_vers'
        "ions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS"
        " UUID) AND artifact_versions.status = 'active' AND artifact_versions.categor"
        'y_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products.id IS'
        ' NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_originals.'
        "id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_origina"
        "ls.scan_status = 'clean' AND original_security.source_state = 'active' AND o"
        "riginal_security.disposition = 'active' AND original_security.current_reques"
        't_id IS NOT NULL)), \nshared_enterprise_supply_snapshots AS MATERIALIZED \n('
        'SELECT supply_snapshots.revision AS revision, supply_snapshots.status AS sta'
        'tus, supply_snapshots.capture_id AS capture_id, supply_snapshots.previous_sn'
        'apshot_id AS previous_snapshot_id, supply_snapshots.previous_revision AS pre'
        'vious_revision, supply_snapshots.snapshot AS snapshot, supply_snapshots.snap'
        'shot_sha256 AS snapshot_sha256, supply_snapshots.bound_demand AS bound_deman'
        'd, supply_snapshots.reconciliation AS reconciliation, supply_snapshots.sourc'
        'es AS sources, supply_snapshots.product_id AS product_id, supply_snapshots.p'
        'roject_id AS project_id, supply_snapshots.build_id AS build_id, supply_snaps'
        'hots.build_revision AS build_revision, supply_snapshots.owner_id AS owner_id'
        ', supply_snapshots.visibility AS visibility, supply_snapshots.reason AS reas'
        'on, supply_snapshots.required_source_read_set AS required_source_read_set, s'
        'upply_snapshots.id AS id, supply_snapshots.tenant_id AS tenant_id, supply_sn'
        'apshots.created_at AS created_at, supply_snapshots.category_id AS category_i'
        'd \nFROM supply_snapshots \nWHERE supply_snapshots.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_p"
        'rojects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, project'
        's.owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, '
        'projects.scope AS scope, projects.visibility AS visibility, projects.status '
        'AS status, projects.revision AS revision, projects.current_plan_id AS curren'
        't_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS tri'
        'gger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, proje'
        'cts.tenant_id AS tenant_id, projects.created_at AS created_at, projects.cate'
        'gory_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpr"
        'ise_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpo'
        'se AS purpose, products.revision AS revision, products.lifecycle_epoch AS li'
        'fecycle_epoch, products.status AS status, products.owner_id AS owner_id, pro'
        'ducts.parent_product_id AS parent_product_id, products.category_id AS catego'
        'ry_id, products.visibility AS visibility, products.target_price AS target_pr'
        'ice, products.target_price_currency AS target_price_currency, products.targe'
        't_price_basis AS target_price_basis, products.target_price_includes_tax AS t'
        'arget_price_includes_tax, products.target_price_as_of AS target_price_as_of,'
        ' products.id AS id, products.tenant_id AS tenant_id, products.created_at AS '
        'created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_builds A"
        'S MATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id '
        'AS project_id, builds.project_revision AS project_revision, builds.engineeri'
        'ng_configuration_id AS engineering_configuration_id, builds.manufacturing_co'
        'nfiguration_id AS manufacturing_configuration_id, builds.previous_build_id A'
        'S previous_build_id, builds.owner_id AS owner_id, builds.name AS name, build'
        's.type AS type, builds.purpose AS purpose, builds.planned_quantity AS planne'
        'd_quantity, builds.unit AS unit, builds.planned_start AS planned_start, buil'
        'ds.planned_end AS planned_end, builds.verification_objectives AS verificatio'
        'n_objectives, builds.disposition_plan AS disposition_plan, builds.visibility'
        ' AS visibility, builds.revision AS revision, builds.status AS status, builds'
        '.id AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, b'
        'uilds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CA'
        "ST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_e"
        'nterprise_supply_current_snapshots AS MATERIALIZED \n(SELECT supply_current_'
        'snapshots.product_id AS product_id, supply_current_snapshots.build_id AS bui'
        'ld_id, supply_current_snapshots.snapshot_id AS snapshot_id, supply_current_s'
        'napshots.snapshot_revision AS snapshot_revision, supply_current_snapshots.id'
        ' AS id, supply_current_snapshots.tenant_id AS tenant_id, supply_current_snap'
        'shots.created_at AS created_at, supply_current_snapshots.category_id AS cate'
        'gory_id \nFROM supply_current_snapshots \nWHERE supply_current_snapshots.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)),"
        " \nauthoritative_enterprise_sources_f30dfe1cfb6de6d1 AS \n(SELECT 'supply' A"
        'S source_type, shared_enterprise_supply_snapshots.id AS source_id, shared_en'
        'terprise_supply_snapshots.tenant_id AS tenant_id, shared_enterprise_supply_s'
        'napshots.category_id AS category_id, shared_enterprise_supply_snapshots.prod'
        'uct_id AS product_id, shared_enterprise_supply_snapshots.project_id AS proje'
        'ct_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_supply_snapshots'
        '.owner_id AS owner_id, shared_enterprise_supply_snapshots.revision AS source'
        "_revision, '\u4f9b\u5e94\u627f\u8bfa \xb7 ' || CAST(shared_enterprise_supply"
        '_snapshots.build_id AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(js'
        "onb_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind',"
        " 'supply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_"
        "snapshots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'co"
        "mmitments', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enter"
        "prise_supply_commitments.value['record_id'], 'supplier_id', enterprise_suppl"
        "y_commitments.value['supplier_id'], 'material_id', enterprise_supply_commitm"
        "ents.value['material_id'], 'quantity', enterprise_supply_commitments.value['"
        "quantity'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_a"
        "t', enterprise_supply_commitments.value['expected_at']) ORDER BY enterprise_"
        'supply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb'
        "_array_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commit"
        "ments'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitme"
        "nts(value, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build"
        "_object('type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id"
        "'], 'version', enterprise_reads_supply.value['expected_revision']) ORDER BY "
        "enterprise_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.val"
        "ue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb"
        '_array_elements(shared_enterprise_supply_snapshots.required_source_read_set)'
        " AS enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_supply_snapshots.id, 'kind', 'supply', 'facts', jso"
        "nb_build_object('build_id', shared_enterprise_supply_snapshots.build_id, 'st"
        "atus', shared_enterprise_supply_snapshots.status, 'commitments', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('record_id', enterprise_supply_commitment"
        "s.value['record_id'], 'supplier_id', enterprise_supply_commitments.value['su"
        "pplier_id'], 'material_id', enterprise_supply_commitments.value['material_id"
        "'], 'quantity', enterprise_supply_commitments.value['quantity'], 'unit', ent"
        "erprise_supply_commitments.value['unit'], 'expected_at', enterprise_supply_c"
        "ommitments.value['expected_at']) ORDER BY enterprise_supply_commitments.ordi"
        'nal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesc'
        "e(shared_enterprise_supply_snapshots.snapshot['commitments'], CAST('[]' AS J"
        'SONB))) WITH ORDINALITY AS enterprise_supply_commitments(value, ordinal))), '
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_supply.value['artifact_id'], 'version', enterpri"
        "se_reads_supply.value['expected_revision']) ORDER BY enterprise_reads_supply"
        ".value ->> 'artifact_id', enterprise_reads_supply.value ->> 'expected_revisi"
        "on'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_"
        'enterprise_supply_snapshots.required_source_read_set) AS enterprise_reads_su'
        "pply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(json"
        "b_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', '"
        "supply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_sn"
        "apshots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'comm"
        "itments', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enterpr"
        "ise_supply_commitments.value['record_id'], 'supplier_id', enterprise_supply_"
        "commitments.value['supplier_id'], 'material_id', enterprise_supply_commitmen"
        "ts.value['material_id'], 'quantity', enterprise_supply_commitments.value['qu"
        "antity'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_at'"
        ", enterprise_supply_commitments.value['expected_at']) ORDER BY enterprise_su"
        'pply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_a'
        "rray_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitme"
        "nts'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitment"
        "s(value, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_o"
        "bject('type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id']"
        ", 'version', enterprise_reads_supply.value['expected_revision']) ORDER BY en"
        "terprise_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.value"
        " ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_a"
        'rray_elements(shared_enterprise_supply_snapshots.required_source_read_set) A'
        "S enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_supply_snapshots.visib"
        "ility != 'category' OR coalesce(shared_enterprise_projects.visibility != 'ca"
        "tegory', false) OR coalesce(shared_enterprise_products.visibility != 'catego"
        "ry', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpri"
        'se_supply_snapshots.required_source_read_set) AS enterprise_reads_supply(val'
        'ue) JOIN enterprise_authoritative_artifacts_f30dfe1cfb6de6d1 ON enterprise_a'
        'uthoritative_artifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_supply'
        '_snapshots.tenant_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de6d1'
        ".source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID)"
        ' \nWHERE enterprise_authoritative_artifacts_f30dfe1cfb6de6d1.private)) OR sh'
        "ared_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1"
        ' \nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_sou'
        'rce_read_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritativ'
        'e_artifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_artifacts_f30dfe1cf'
        'b6de6d1.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND enterpr'
        'ise_authoritative_artifacts_f30dfe1cfb6de6d1.source_id = CAST((enterprise_re'
        "ads_supply.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritativ"
        'e_artifacts_f30dfe1cfb6de6d1.customer_original) AS customer_original, shared'
        '_enterprise_supply_current_snapshots.snapshot_id = shared_enterprise_supply_'
        'snapshots.id AS is_current, shared_enterprise_supply_snapshots.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_supply_sna'
        'pshots.id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_'
        'artifacts_f30dfe1cfb6de6d1.original_id), ARRAY[]::UUID[]) AS coalesce_3 \nFR'
        'OM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_r'
        'ead_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritative_art'
        'ifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_artifacts_f30dfe1cfb6de6'
        'd1.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_a'
        'uthoritative_artifacts_f30dfe1cfb6de6d1.source_id = CAST((enterprise_reads_s'
        "upply.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_art"
        'ifacts_f30dfe1cfb6de6d1.original_id IS NOT NULL) AS original_ids, CASE WHEN '
        '(EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_supply_snaps'
        'hots.required_source_read_set) AS enterprise_reads_supply(value) JOIN enterp'
        'rise_authoritative_artifacts_f30dfe1cfb6de6d1 ON enterprise_authoritative_ar'
        'tifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_supply_snapshots.tena'
        'nt_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de6d1.source_id = CA'
        "ST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_f30dfe1cfb6de6d1.source_revision != CAST((enter'
        "prise_reads_supply.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_"
        "recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_su"
        'pply_snapshots JOIN shared_enterprise_projects ON shared_enterprise_projects'
        '.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_enterpr'
        'ise_projects.product_id = shared_enterprise_supply_snapshots.product_id AND '
        'shared_enterprise_projects.id = shared_enterprise_supply_snapshots.project_i'
        'd AND shared_enterprise_projects.category_id = shared_enterprise_supply_snap'
        'shots.category_id JOIN shared_enterprise_products ON shared_enterprise_produ'
        'cts.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_ente'
        'rprise_products.id = shared_enterprise_supply_snapshots.product_id AND share'
        'd_enterprise_products.category_id = shared_enterprise_supply_snapshots.categ'
        'ory_id JOIN shared_enterprise_builds ON shared_enterprise_builds.tenant_id ='
        ' shared_enterprise_supply_snapshots.tenant_id AND shared_enterprise_builds.c'
        'ategory_id = shared_enterprise_supply_snapshots.category_id AND shared_enter'
        'prise_builds.product_id = shared_enterprise_supply_snapshots.product_id AND '
        'shared_enterprise_builds.project_id = shared_enterprise_supply_snapshots.pro'
        'ject_id AND shared_enterprise_builds.id = shared_enterprise_supply_snapshots'
        '.build_id AND shared_enterprise_builds.revision = shared_enterprise_supply_s'
        'napshots.build_revision JOIN shared_enterprise_supply_current_snapshots ON s'
        'hared_enterprise_supply_current_snapshots.tenant_id = shared_enterprise_supp'
        'ly_snapshots.tenant_id AND shared_enterprise_supply_current_snapshots.produc'
        't_id = shared_enterprise_supply_snapshots.product_id AND shared_enterprise_s'
        'upply_current_snapshots.build_id = shared_enterprise_supply_snapshots.build_'
        'id \nWHERE shared_enterprise_supply_snapshots.tenant_id = CAST(nullif(curren'
        "t_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source'
        '_read_set) AS enterprise_reads_supply(value) \nWHERE NOT (EXISTS (SELECT 1 '
        '\nFROM enterprise_authoritative_artifacts_f30dfe1cfb6de6d1 \nWHERE enterpris'
        'e_authoritative_artifacts_f30dfe1cfb6de6d1.tenant_id = shared_enterprise_sup'
        'ply_snapshots.tenant_id AND enterprise_authoritative_artifacts_f30dfe1cfb6de'
        "6d1.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UU"
        'ID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_f'
        '30dfe1cfb6de6d1 \nWHERE authoritative_enterprise_sources_f30dfe1cfb6de6d1.te'
        'nant_id = t AND authoritative_enterprise_sources_f30dfe1cfb6de6d1.category_i'
        'd = c AND CAST(authoritative_enterprise_sources_f30dfe1cfb6de6d1.source_id A'
        "S TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sources_f"
        "30dfe1cfb6de6d1.source_revision AS TEXT) = expected->>'source_revision' AND "
        'authoritative_enterprise_sources_f30dfe1cfb6de6d1.content_hash = expected->>'
        "'content_hash') AS anon_1 INTO visible;\n WHEN 'build' THEN\n  WITH shared_e"
        'nterprise_engineering_configurations AS MATERIALIZED \n(SELECT engineering_c'
        'onfigurations.definition_id AS definition_id, engineering_configurations.def'
        'inition_revision AS definition_revision, engineering_configurations.bom_id A'
        'S bom_id, engineering_configurations.bom_revision AS bom_revision, engineeri'
        'ng_configurations.design_versions AS design_versions, engineering_configurat'
        'ions.series_id AS series_id, engineering_configurations.previous_id AS previ'
        'ous_id, engineering_configurations.expected_previous_revision AS expected_pr'
        'evious_revision, engineering_configurations.reason AS reason, engineering_co'
        'nfigurations.product_id AS product_id, engineering_configurations.owner_id A'
        'S owner_id, engineering_configurations.name AS name, engineering_configurati'
        'ons.status AS status, engineering_configurations.visibility AS visibility, e'
        'ngineering_configurations.revision AS revision, engineering_configurations.s'
        'ources AS sources, engineering_configurations.required_source_read_set AS re'
        'quired_source_read_set, engineering_configurations.id AS id, engineering_con'
        'figurations.tenant_id AS tenant_id, engineering_configurations.created_at AS'
        ' created_at, engineering_configurations.category_id AS category_id \nFROM en'
        'gineering_configurations \nWHERE engineering_configurations.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_process_revisions AS MATERIALIZED \n(SELECT process_revisions.engine'
        'ering_configuration_id AS engineering_configuration_id, process_revisions.en'
        'gineering_revision AS engineering_revision, process_revisions.operations AS '
        'operations, process_revisions.site AS site, process_revisions.line AS line, '
        'process_revisions.series_id AS series_id, process_revisions.previous_id AS p'
        'revious_id, process_revisions.expected_previous_revision AS expected_previou'
        's_revision, process_revisions.reason AS reason, process_revisions.product_id'
        ' AS product_id, process_revisions.owner_id AS owner_id, process_revisions.na'
        'me AS name, process_revisions.status AS status, process_revisions.visibility'
        ' AS visibility, process_revisions.revision AS revision, process_revisions.so'
        'urces AS sources, process_revisions.required_source_read_set AS required_sou'
        'rce_read_set, process_revisions.id AS id, process_revisions.tenant_id AS ten'
        'ant_id, process_revisions.created_at AS created_at, process_revisions.catego'
        'ry_id AS category_id \nFROM process_revisions \nWHERE process_revisions.tena'
        "nt_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), "
        "\nenterprise_authoritative_artifacts_44575cf5b28512d7 AS \n(SELECT 'artifact"
        "' AS source_type, artifact_versions.id AS source_id, artifact_versions.tenan"
        't_id AS tenant_id, artifact_versions.category_id AS category_id, artifact_ve'
        'rsions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL'
        ' AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_v'
        'ersions.revision AS source_revision, artifact_versions.title AS title, artif'
        'act_versions.content_hash AS content_hash, artifact_versions.content AS body'
        ", CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_version"
        "s.visibility != 'category' OR coalesce(products.visibility != 'category', fa"
        "lse) OR coalesce(uploaded_originals.visibility != 'category', false) AS priv"
        'ate, artifact_versions.original_id IS NOT NULL AS customer_original, true AS'
        ' is_current, artifact_versions.created_at AS created_at, artifact_versions.o'
        'riginal_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (art'
        'ifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.origina'
        "l_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_stat"
        'us \nFROM artifact_versions LEFT OUTER JOIN products ON products.tenant_id ='
        ' artifact_versions.tenant_id AND products.id = artifact_versions.product_id '
        'LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = artifac'
        't_versions.tenant_id AND uploaded_originals.id = artifact_versions.original_'
        'id AND uploaded_originals.category_id = artifact_versions.category_id AND up'
        'loaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.product_i'
        'd LEFT OUTER JOIN original_security ON original_security.tenant_id = uploade'
        'd_originals.tenant_id AND original_security.original_id = uploaded_originals'
        ".id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_setting('pdos."
        "tenant_id', true), '') AS UUID) AND artifact_versions.status = 'active' AND "
        'artifact_versions.category_id IS NOT NULL AND (artifact_versions.product_id '
        'IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NU'
        "LL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status = 'par"
        "sed' AND uploaded_originals.scan_status = 'clean' AND original_security.sour"
        "ce_state = 'active' AND original_security.disposition = 'active' AND origina"
        'l_security.current_request_id IS NOT NULL)), \nshared_enterprise_builds AS M'
        'ATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id AS '
        'project_id, builds.project_revision AS project_revision, builds.engineering_'
        'configuration_id AS engineering_configuration_id, builds.manufacturing_confi'
        'guration_id AS manufacturing_configuration_id, builds.previous_build_id AS p'
        'revious_build_id, builds.owner_id AS owner_id, builds.name AS name, builds.t'
        'ype AS type, builds.purpose AS purpose, builds.planned_quantity AS planned_q'
        'uantity, builds.unit AS unit, builds.planned_start AS planned_start, builds.'
        'planned_end AS planned_end, builds.verification_objectives AS verification_o'
        'bjectives, builds.disposition_plan AS disposition_plan, builds.visibility AS'
        ' visibility, builds.revision AS revision, builds.status AS status, builds.id'
        ' AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, buil'
        'ds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ente"
        'rprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id,'
        ' projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS p'
        'urpose, projects.scope AS scope, projects.visibility AS visibility, projects'
        '.status AS status, projects.revision AS revision, projects.current_plan_id A'
        'S current_plan_id, projects.trigger_type AS trigger_type, projects.trigger_i'
        'd AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS i'
        'd, projects.tenant_id AS tenant_id, projects.created_at AS created_at, proje'
        'cts.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared"
        '_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, produc'
        'ts.purpose AS purpose, products.revision AS revision, products.lifecycle_epo'
        'ch AS lifecycle_epoch, products.status AS status, products.owner_id AS owner'
        '_id, products.parent_product_id AS parent_product_id, products.category_id A'
        'S category_id, products.visibility AS visibility, products.target_price AS t'
        'arget_price, products.target_price_currency AS target_price_currency, produc'
        'ts.target_price_basis AS target_price_basis, products.target_price_includes_'
        'tax AS target_price_includes_tax, products.target_price_as_of AS target_pric'
        'e_as_of, products.id AS id, products.tenant_id AS tenant_id, products.create'
        'd_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif('
        "current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_"
        'build_starts AS MATERIALIZED \n(SELECT build_starts.product_id AS product_id'
        ', build_starts.project_id AS project_id, build_starts.build_id AS build_id, '
        'build_starts.build_revision AS build_revision, build_starts.engineering_conf'
        'iguration_id AS engineering_configuration_id, build_starts.manufacturing_con'
        'figuration_id AS manufacturing_configuration_id, build_starts.assessment_id '
        'AS assessment_id, build_starts.assessment_revision AS assessment_revision, b'
        'uild_starts.assessment_sha256 AS assessment_sha256, build_starts.engineering'
        '_authorization_id AS engineering_authorization_id, build_starts.engineering_'
        'authorization_revision AS engineering_authorization_revision, build_starts.m'
        'anufacturing_authorization_id AS manufacturing_authorization_id, build_start'
        's.manufacturing_authorization_revision AS manufacturing_authorization_revisi'
        'on, build_starts.engineering_role AS engineering_role, build_starts.manufact'
        'uring_role AS manufacturing_role, build_starts.revision AS revision, build_s'
        'tarts.owner_id AS owner_id, build_starts.visibility AS visibility, build_sta'
        'rts.status AS status, build_starts.occurred_at AS occurred_at, build_starts.'
        'occurred_timezone AS occurred_timezone, build_starts.execution_scope AS exec'
        'ution_scope, build_starts.event_source AS event_source, build_starts.authori'
        'ty_snapshot AS authority_snapshot, build_starts.reservations AS reservations'
        ', build_starts.sources AS sources, build_starts.required_source_read_set AS '
        'required_source_read_set, build_starts.snapshot_sha256 AS snapshot_sha256, b'
        'uild_starts.intent_digest AS intent_digest, build_starts.reason AS reason, b'
        'uild_starts.id AS id, build_starts.tenant_id AS tenant_id, build_starts.crea'
        'ted_at AS created_at, build_starts.category_id AS category_id \nFROM build_s'
        "tarts \nWHERE build_starts.tenant_id = CAST(nullif(current_setting('pdos.ten"
        "ant_id', true), '') AS UUID)), \nshared_enterprise_actual_configurations AS "
        'MATERIALIZED \n(SELECT actual_configurations.status AS status, actual_config'
        'urations.planned_engineering_configuration_id AS planned_engineering_configu'
        'ration_id, actual_configurations.planned_manufacturing_configuration_id AS p'
        'lanned_manufacturing_configuration_id, actual_configurations.actual_engineer'
        'ing_configuration_id AS actual_engineering_configuration_id, actual_configur'
        'ations.actual_engineering_revision AS actual_engineering_revision, actual_co'
        'nfigurations.actual_manufacturing_configuration_id AS actual_manufacturing_c'
        'onfiguration_id, actual_configurations.actual_manufacturing_revision AS actu'
        'al_manufacturing_revision, actual_configurations.observed_at AS observed_at,'
        ' actual_configurations.differences AS differences, actual_configurations.pro'
        'duct_id AS product_id, actual_configurations.project_id AS project_id, actua'
        'l_configurations.build_id AS build_id, actual_configurations.build_revision '
        'AS build_revision, actual_configurations.owner_id AS owner_id, actual_config'
        'urations.visibility AS visibility, actual_configurations.revision AS revisio'
        'n, actual_configurations.reason AS reason, actual_configurations.sources AS '
        'sources, actual_configurations.required_source_read_set AS required_source_r'
        'ead_set, actual_configurations.id AS id, actual_configurations.tenant_id AS '
        'tenant_id, actual_configurations.created_at AS created_at, actual_configurat'
        'ions.category_id AS category_id \nFROM actual_configurations \nWHERE actual_'
        "configurations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', tru"
        "e), '') AS UUID)), \nshared_enterprise_build_lots AS MATERIALIZED \n(SELECT "
        'build_lots.status AS status, build_lots.actual_configuration_id AS actual_co'
        'nfiguration_id, build_lots.actual_configuration_revision AS actual_configura'
        'tion_revision, build_lots.lot_label AS lot_label, build_lots.observed_unit_c'
        'ount AS observed_unit_count, build_lots.unit AS unit, build_lots.observation'
        '_system AS observation_system, build_lots.observation_external_id AS observa'
        'tion_external_id, build_lots.observation_nature AS observation_nature, build'
        '_lots.occurred_at AS occurred_at, build_lots.received_at AS received_at, bui'
        'ld_lots.product_id AS product_id, build_lots.project_id AS project_id, build'
        '_lots.build_id AS build_id, build_lots.build_revision AS build_revision, bui'
        'ld_lots.owner_id AS owner_id, build_lots.visibility AS visibility, build_lot'
        's.revision AS revision, build_lots.reason AS reason, build_lots.sources AS s'
        'ources, build_lots.required_source_read_set AS required_source_read_set, bui'
        'ld_lots.id AS id, build_lots.tenant_id AS tenant_id, build_lots.created_at A'
        'S created_at, build_lots.category_id AS category_id \nFROM build_lots \nWHER'
        "E build_lots.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)"
        ", '') AS UUID)), \nauthoritative_enterprise_sources_44575cf5b28512d7 AS \n(S"
        "ELECT 'build' AS source_type, shared_enterprise_builds.id AS source_id, shar"
        'ed_enterprise_builds.tenant_id AS tenant_id, shared_enterprise_builds.catego'
        'ry_id AS category_id, shared_enterprise_builds.product_id AS product_id, sha'
        'red_enterprise_builds.project_id AS project_id, CAST(NULL AS UUID) AS propos'
        'al_id, shared_enterprise_builds.owner_id AS owner_id, shared_enterprise_buil'
        'ds.revision AS source_revision, shared_enterprise_builds.name AS title, enco'
        "de(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterp"
        "rise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('name', shared_"
        "enterprise_builds.name, 'type', shared_enterprise_builds.type, 'purpose', sh"
        "ared_enterprise_builds.purpose, 'planned_quantity', shared_enterprise_builds"
        ".planned_quantity, 'unit', shared_enterprise_builds.unit, 'planned_start', s"
        "hared_enterprise_builds.planned_start, 'planned_end', shared_enterprise_buil"
        "ds.planned_end, 'engineering_configuration_id', shared_enterprise_builds.eng"
        "ineering_configuration_id, 'manufacturing_configuration_id', shared_enterpri"
        "se_builds.manufacturing_configuration_id, 'verification_objectives', shared_"
        "enterprise_builds.verification_objectives, 'plan_status', shared_enterprise_"
        "builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object"
        "('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'ver"
        "sion', enterprise_reads_build.value['expected_revision']) ORDER BY enterpris"
        "e_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'exp"
        "ected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elem"
        'ents((SELECT shared_enterprise_engineering_configurations.required_source_re'
        'ad_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_en'
        'terprise_engineering_configurations.tenant_id = shared_enterprise_builds.ten'
        'ant_id AND shared_enterprise_engineering_configurations.product_id = shared_'
        'enterprise_builds.product_id AND shared_enterprise_engineering_configuration'
        's.id = shared_enterprise_builds.engineering_configuration_id) || (SELECT sha'
        'red_enterprise_process_revisions.required_source_read_set \nFROM shared_ente'
        'rprise_process_revisions \nWHERE shared_enterprise_process_revisions.tenant_'
        'id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisi'
        'ons.product_id = shared_enterprise_builds.product_id AND shared_enterprise_p'
        'rocess_revisions.id = shared_enterprise_builds.manufacturing_configuration_i'
        "d)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_builds.id, 'kind', 'build', 'facts', jsonb_build_ob"
        "ject('name', shared_enterprise_builds.name, 'type', shared_enterprise_builds"
        ".type, 'purpose', shared_enterprise_builds.purpose, 'planned_quantity', shar"
        "ed_enterprise_builds.planned_quantity, 'unit', shared_enterprise_builds.unit"
        ", 'planned_start', shared_enterprise_builds.planned_start, 'planned_end', sh"
        "ared_enterprise_builds.planned_end, 'engineering_configuration_id', shared_e"
        "nterprise_builds.engineering_configuration_id, 'manufacturing_configuration_"
        "id', shared_enterprise_builds.manufacturing_configuration_id, 'verification_"
        "objectives', shared_enterprise_builds.verification_objectives, 'plan_status'"
        ", shared_enterprise_builds.status), 'source_refs', (SELECT coalesce(jsonb_ag"
        "g(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value["
        "'artifact_id'], 'version', enterprise_reads_build.value['expected_revision']"
        ") ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_"
        "build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        'ROM jsonb_array_elements((SELECT shared_enterprise_engineering_configuration'
        's.required_source_read_set \nFROM shared_enterprise_engineering_configuratio'
        'ns \nWHERE shared_enterprise_engineering_configurations.tenant_id = shared_e'
        'nterprise_builds.tenant_id AND shared_enterprise_engineering_configurations.'
        'product_id = shared_enterprise_builds.product_id AND shared_enterprise_engin'
        'eering_configurations.id = shared_enterprise_builds.engineering_configuratio'
        'n_id) || (SELECT shared_enterprise_process_revisions.required_source_read_se'
        't \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_proce'
        'ss_revisions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enter'
        'prise_process_revisions.product_id = shared_enterprise_builds.product_id AND'
        ' shared_enterprise_process_revisions.id = shared_enterprise_builds.manufactu'
        "ring_configuration_id)) AS enterprise_reads_build(value)), 'record_policy', "
        "'\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('nam"
        "e', shared_enterprise_builds.name, 'type', shared_enterprise_builds.type, 'p"
        "urpose', shared_enterprise_builds.purpose, 'planned_quantity', shared_enterp"
        "rise_builds.planned_quantity, 'unit', shared_enterprise_builds.unit, 'planne"
        "d_start', shared_enterprise_builds.planned_start, 'planned_end', shared_ente"
        "rprise_builds.planned_end, 'engineering_configuration_id', shared_enterprise"
        "_builds.engineering_configuration_id, 'manufacturing_configuration_id', shar"
        "ed_enterprise_builds.manufacturing_configuration_id, 'verification_objective"
        "s', shared_enterprise_builds.verification_objectives, 'plan_status', shared_"
        "enterprise_builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact"
        "_id'], 'version', enterprise_reads_build.value['expected_revision']) ORDER B"
        "Y enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.val"
        "ue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb"
        '_array_elements((SELECT shared_enterprise_engineering_configurations.require'
        'd_source_read_set \nFROM shared_enterprise_engineering_configurations \nWHER'
        'E shared_enterprise_engineering_configurations.tenant_id = shared_enterprise'
        '_builds.tenant_id AND shared_enterprise_engineering_configurations.product_i'
        'd = shared_enterprise_builds.product_id AND shared_enterprise_engineering_co'
        'nfigurations.id = shared_enterprise_builds.engineering_configuration_id) || '
        '(SELECT shared_enterprise_process_revisions.required_source_read_set \nFROM '
        'shared_enterprise_process_revisions \nWHERE shared_enterprise_process_revisi'
        'ons.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_pro'
        'cess_revisions.product_id = shared_enterprise_builds.product_id AND shared_e'
        'nterprise_process_revisions.id = shared_enterprise_builds.manufacturing_conf'
        "iguration_id)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_builds.vis"
        "ibility != 'category' OR coalesce(shared_enterprise_projects.visibility != '"
        "category', false) OR coalesce(shared_enterprise_products.visibility != 'cate"
        "gory', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT share"
        'd_enterprise_engineering_configurations.required_source_read_set \nFROM shar'
        'ed_enterprise_engineering_configurations \nWHERE shared_enterprise_engineeri'
        'ng_configurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_'
        'enterprise_engineering_configurations.product_id = shared_enterprise_builds.'
        'product_id AND shared_enterprise_engineering_configurations.id = shared_ente'
        'rprise_builds.engineering_configuration_id) || (SELECT shared_enterprise_pro'
        'cess_revisions.required_source_read_set \nFROM shared_enterprise_process_rev'
        'isions \nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterp'
        'rise_builds.tenant_id AND shared_enterprise_process_revisions.product_id = s'
        'hared_enterprise_builds.product_id AND shared_enterprise_process_revisions.i'
        'd = shared_enterprise_builds.manufacturing_configuration_id)) AS enterprise_'
        'reads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 '
        'ON enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_en'
        'terprise_builds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28'
        "512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.private)) A'
        'S private, EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enter'
        'prise_engineering_configurations.required_source_read_set \nFROM shared_ente'
        'rprise_engineering_configurations \nWHERE shared_enterprise_engineering_conf'
        'igurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterpr'
        'ise_engineering_configurations.product_id = shared_enterprise_builds.product'
        '_id AND shared_enterprise_engineering_configurations.id = shared_enterprise_'
        'builds.engineering_configuration_id) || (SELECT shared_enterprise_process_re'
        'visions.required_source_read_set \nFROM shared_enterprise_process_revisions '
        '\nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterprise_bu'
        'ilds.tenant_id AND shared_enterprise_process_revisions.product_id = shared_e'
        'nterprise_builds.product_id AND shared_enterprise_process_revisions.id = sha'
        'red_enterprise_builds.manufacturing_configuration_id)) AS enterprise_reads_b'
        'uild(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterpris'
        'e_builds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.s'
        "ource_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_44575cf5b28512d7.customer_original)'
        ' AS customer_original, true AS is_current, shared_enterprise_builds.created_'
        'at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_build'
        's.id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artif'
        'acts_44575cf5b28512d7.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM js'
        'onb_array_elements((SELECT shared_enterprise_engineering_configurations.requ'
        'ired_source_read_set \nFROM shared_enterprise_engineering_configurations \nW'
        'HERE shared_enterprise_engineering_configurations.tenant_id = shared_enterpr'
        'ise_builds.tenant_id AND shared_enterprise_engineering_configurations.produc'
        't_id = shared_enterprise_builds.product_id AND shared_enterprise_engineering'
        '_configurations.id = shared_enterprise_builds.engineering_configuration_id) '
        '|| (SELECT shared_enterprise_process_revisions.required_source_read_set \nFR'
        'OM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_rev'
        'isions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_'
        'process_revisions.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_c'
        'onfiguration_id)) AS enterprise_reads_build(value) JOIN enterprise_authorita'
        'tive_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts_44575c'
        'f5b28512d7.tenant_id = shared_enterprise_builds.tenant_id AND enterprise_aut'
        'horitative_artifacts_44575cf5b28512d7.source_id = CAST((enterprise_reads_bui'
        "ld.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifa"
        'cts_44575cf5b28512d7.original_id IS NOT NULL) AS original_ids, CASE WHEN (EX'
        'ISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterprise_enginee'
        'ring_configurations.required_source_read_set \nFROM shared_enterprise_engine'
        'ering_configurations \nWHERE shared_enterprise_engineering_configurations.te'
        'nant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_engineeri'
        'ng_configurations.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_engineering_configurations.id = shared_enterprise_builds.engine'
        'ering_configuration_id) || (SELECT shared_enterprise_process_revisions.requi'
        'red_source_read_set \nFROM shared_enterprise_process_revisions \nWHERE share'
        'd_enterprise_process_revisions.tenant_id = shared_enterprise_builds.tenant_i'
        'd AND shared_enterprise_process_revisions.product_id = shared_enterprise_bui'
        'lds.product_id AND shared_enterprise_process_revisions.id = shared_enterpris'
        'e_builds.manufacturing_configuration_id)) AS enterprise_reads_build(value) J'
        'OIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_author'
        'itative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_builds.tena'
        'nt_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CA'
        "ST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_44575cf5b28512d7.source_revision != CAST((enterp'
        "rise_reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_re"
        "check' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_buil"
        'ds JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id ='
        ' shared_enterprise_builds.tenant_id AND shared_enterprise_projects.product_i'
        'd = shared_enterprise_builds.product_id AND shared_enterprise_projects.id = '
        'shared_enterprise_builds.project_id AND shared_enterprise_projects.category_'
        'id = shared_enterprise_builds.category_id JOIN shared_enterprise_products ON'
        ' shared_enterprise_products.tenant_id = shared_enterprise_builds.tenant_id A'
        'ND shared_enterprise_products.id = shared_enterprise_builds.product_id AND s'
        'hared_enterprise_products.category_id = shared_enterprise_builds.category_id'
        " \nWHERE shared_enterprise_builds.tenant_id = CAST(nullif(current_setting('p"
        "dos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_a"
        'rray_elements((SELECT shared_enterprise_engineering_configurations.required_'
        'source_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE '
        'shared_enterprise_engineering_configurations.tenant_id = shared_enterprise_b'
        'uilds.tenant_id AND shared_enterprise_engineering_configurations.product_id '
        '= shared_enterprise_builds.product_id AND shared_enterprise_engineering_conf'
        'igurations.id = shared_enterprise_builds.engineering_configuration_id) || (S'
        'ELECT shared_enterprise_process_revisions.required_source_read_set \nFROM sh'
        'ared_enterprise_process_revisions \nWHERE shared_enterprise_process_revision'
        's.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_proce'
        'ss_revisions.product_id = shared_enterprise_builds.product_id AND shared_ent'
        'erprise_process_revisions.id = shared_enterprise_builds.manufacturing_config'
        'uration_id)) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 '
        '\nFROM enterprise_authoritative_artifacts_44575cf5b28512d7 \nWHERE enterpris'
        'e_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_bui'
        'lds.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source'
        "_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID))))) AND"
        ' (EXISTS (SELECT shared_enterprise_engineering_configurations.required_sourc'
        'e_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE share'
        'd_enterprise_engineering_configurations.tenant_id = shared_enterprise_builds'
        '.tenant_id AND shared_enterprise_engineering_configurations.product_id = sha'
        'red_enterprise_builds.product_id AND shared_enterprise_engineering_configura'
        'tions.id = shared_enterprise_builds.engineering_configuration_id)) AND (EXIS'
        'TS (SELECT shared_enterprise_process_revisions.required_source_read_set \nFR'
        'OM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_rev'
        'isions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_'
        'process_revisions.product_id = shared_enterprise_builds.product_id AND share'
        'd_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_c'
        "onfiguration_id)) UNION ALL SELECT 'build' AS source_type, shared_enterprise"
        '_build_starts.id AS source_id, shared_enterprise_build_starts.tenant_id AS t'
        'enant_id, shared_enterprise_build_starts.category_id AS category_id, shared_'
        'enterprise_build_starts.product_id AS product_id, shared_enterprise_build_st'
        'arts.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_ent'
        'erprise_build_starts.owner_id AS owner_id, shared_enterprise_build_starts.re'
        "vision AS source_revision, '\u5f00\u5de5\u8bb0\u5f55 \xb7 ' || shared_enterp"
        'rise_builds.name AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_ob'
        "ject('object_id', shared_enterprise_build_starts.build_id, 'kind', 'build', "
        "'facts', jsonb_build_object('record_kind', 'build_start', 'build_id', shared"
        "_enterprise_build_starts.build_id, 'build_revision', shared_enterprise_build"
        "_starts.build_revision, 'status', shared_enterprise_build_starts.status, 'oc"
        "curred_at', shared_enterprise_build_starts.occurred_at, 'occurred_timezone',"
        " shared_enterprise_build_starts.occurred_timezone, 'assessment_id', shared_e"
        "nterprise_build_starts.assessment_id, 'assessment_revision', shared_enterpri"
        "se_build_starts.assessment_revision, 'engineering_authorization_id', shared_"
        "enterprise_build_starts.engineering_authorization_id, 'engineering_authoriza"
        "tion_revision', shared_enterprise_build_starts.engineering_authorization_rev"
        "ision, 'manufacturing_authorization_id', shared_enterprise_build_starts.manu"
        "facturing_authorization_id, 'manufacturing_authorization_revision', shared_e"
        'nterprise_build_starts.manufacturing_authorization_revision) || jsonb_build_'
        "object('execution_scope', jsonb_build_object('purpose', shared_enterprise_bu"
        "ild_starts.execution_scope['purpose'], 'quantity', shared_enterprise_build_s"
        "tarts.execution_scope['quantity'], 'unit', shared_enterprise_build_starts.ex"
        "ecution_scope['unit'], 'site', shared_enterprise_build_starts.execution_scop"
        "e['site'], 'window_start', shared_enterprise_build_starts.execution_scope['w"
        "indow_start'], 'window_end', shared_enterprise_build_starts.execution_scope["
        "'window_end'], 'window_timezone', shared_enterprise_build_starts.execution_s"
        "cope['window_timezone']), 'continuation_permission', 'not_evaluated'), 'sour"
        "ce_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', "
        "'id', enterprise_reads_build.value['artifact_id'], 'version', enterprise_rea"
        "ds_build.value['expected_revision']) ORDER BY enterprise_reads_build.value -"
        ">> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), jso"
        'nb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterpris'
        'e_build_starts.required_source_read_set) AS enterprise_reads_build(value)), '
        "'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_h"
        "ash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_build_start"
        "s.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'bui"
        "ld_start', 'build_id', shared_enterprise_build_starts.build_id, 'build_revis"
        "ion', shared_enterprise_build_starts.build_revision, 'status', shared_enterp"
        "rise_build_starts.status, 'occurred_at', shared_enterprise_build_starts.occu"
        "rred_at, 'occurred_timezone', shared_enterprise_build_starts.occurred_timezo"
        "ne, 'assessment_id', shared_enterprise_build_starts.assessment_id, 'assessme"
        "nt_revision', shared_enterprise_build_starts.assessment_revision, 'engineeri"
        "ng_authorization_id', shared_enterprise_build_starts.engineering_authorizati"
        "on_id, 'engineering_authorization_revision', shared_enterprise_build_starts."
        "engineering_authorization_revision, 'manufacturing_authorization_id', shared"
        "_enterprise_build_starts.manufacturing_authorization_id, 'manufacturing_auth"
        "orization_revision', shared_enterprise_build_starts.manufacturing_authorizat"
        "ion_revision) || jsonb_build_object('execution_scope', jsonb_build_object('p"
        "urpose', shared_enterprise_build_starts.execution_scope['purpose'], 'quantit"
        "y', shared_enterprise_build_starts.execution_scope['quantity'], 'unit', shar"
        "ed_enterprise_build_starts.execution_scope['unit'], 'site', shared_enterpris"
        "e_build_starts.execution_scope['site'], 'window_start', shared_enterprise_bu"
        "ild_starts.execution_scope['window_start'], 'window_end', shared_enterprise_"
        "build_starts.execution_scope['window_end'], 'window_timezone', shared_enterp"
        "rise_build_starts.execution_scope['window_timezone']), 'continuation_permiss"
        "ion', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id"
        "'], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY e"
        "nterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value "
        "->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_ar"
        'ray_elements(shared_enterprise_build_starts.required_source_read_set) AS ent'
        "erprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) "
        "AS body, CAST(jsonb_build_object('object_id', shared_enterprise_build_starts"
        ".build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'buil"
        "d_start', 'build_id', shared_enterprise_build_starts.build_id, 'build_revisi"
        "on', shared_enterprise_build_starts.build_revision, 'status', shared_enterpr"
        "ise_build_starts.status, 'occurred_at', shared_enterprise_build_starts.occur"
        "red_at, 'occurred_timezone', shared_enterprise_build_starts.occurred_timezon"
        "e, 'assessment_id', shared_enterprise_build_starts.assessment_id, 'assessmen"
        "t_revision', shared_enterprise_build_starts.assessment_revision, 'engineerin"
        "g_authorization_id', shared_enterprise_build_starts.engineering_authorizatio"
        "n_id, 'engineering_authorization_revision', shared_enterprise_build_starts.e"
        "ngineering_authorization_revision, 'manufacturing_authorization_id', shared_"
        "enterprise_build_starts.manufacturing_authorization_id, 'manufacturing_autho"
        "rization_revision', shared_enterprise_build_starts.manufacturing_authorizati"
        "on_revision) || jsonb_build_object('execution_scope', jsonb_build_object('pu"
        "rpose', shared_enterprise_build_starts.execution_scope['purpose'], 'quantity"
        "', shared_enterprise_build_starts.execution_scope['quantity'], 'unit', share"
        "d_enterprise_build_starts.execution_scope['unit'], 'site', shared_enterprise"
        "_build_starts.execution_scope['site'], 'window_start', shared_enterprise_bui"
        "ld_starts.execution_scope['window_start'], 'window_end', shared_enterprise_b"
        "uild_starts.execution_scope['window_end'], 'window_timezone', shared_enterpr"
        "ise_build_starts.execution_scope['window_timezone']), 'continuation_permissi"
        "on', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build"
        "_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'"
        "], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY en"
        "terprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value -"
        ">> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_arr"
        'ay_elements(shared_enterprise_build_starts.required_source_read_set) AS ente'
        "rprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_build_starts.visibility != 'catego"
        "ry' OR coalesce(shared_enterprise_projects.visibility != 'category', false) "
        "OR coalesce(shared_enterprise_products.visibility != 'category', false) OR ("
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.'
        'required_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_a'
        'uthoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifact'
        's_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts.tenant_id AND '
        'enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((enterp'
        "rise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_author"
        'itative_artifacts_44575cf5b28512d7.private)) OR shared_enterprise_builds.vis'
        "ibility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts(shared_enterprise_build_starts.required_source_read_set) AS enterprise_re'
        'ads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON'
        ' enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_ente'
        'rprise_build_starts.tenant_id AND enterprise_authoritative_artifacts_44575cf'
        "5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') "
        'AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.custome'
        'r_original) AS customer_original, true AS is_current, shared_enterprise_buil'
        'd_starts.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared'
        '_enterprise_build_starts.build_id AS object_id, (SELECT coalesce(array_agg(e'
        'nterprise_authoritative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UU'
        'ID[]) AS coalesce_4 \nFROM jsonb_array_elements(shared_enterprise_build_star'
        'ts.required_source_read_set) AS enterprise_reads_build(value) JOIN enterpris'
        'e_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artif'
        'acts_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts.tenant_id A'
        'ND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((ent'
        "erprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_aut"
        'horitative_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS original_i'
        'ds, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpris'
        'e_build_starts.required_source_read_set) AS enterprise_reads_build(value) JO'
        'IN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authori'
        'tative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_starts'
        '.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id'
        " = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE en"
        'terprise_authoritative_artifacts_44575cf5b28512d7.source_revision != CAST((e'
        "nterprise_reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'nee"
        "ds_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise"
        '_build_starts JOIN shared_enterprise_projects ON shared_enterprise_projects.'
        'tenant_id = shared_enterprise_build_starts.tenant_id AND shared_enterprise_p'
        'rojects.product_id = shared_enterprise_build_starts.product_id AND shared_en'
        'terprise_projects.id = shared_enterprise_build_starts.project_id AND shared_'
        'enterprise_projects.category_id = shared_enterprise_build_starts.category_id'
        ' JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id = s'
        'hared_enterprise_build_starts.tenant_id AND shared_enterprise_products.id = '
        'shared_enterprise_build_starts.product_id AND shared_enterprise_products.cat'
        'egory_id = shared_enterprise_build_starts.category_id JOIN shared_enterprise'
        '_builds ON shared_enterprise_builds.tenant_id = shared_enterprise_build_star'
        'ts.tenant_id AND shared_enterprise_builds.category_id = shared_enterprise_bu'
        'ild_starts.category_id AND shared_enterprise_builds.product_id = shared_ente'
        'rprise_build_starts.product_id AND shared_enterprise_builds.project_id = sha'
        'red_enterprise_build_starts.project_id AND shared_enterprise_builds.id = sha'
        'red_enterprise_build_starts.build_id AND shared_enterprise_builds.revision ='
        ' shared_enterprise_build_starts.build_revision \nWHERE shared_enterprise_bui'
        "ld_starts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '"
        "') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ent"
        'erprise_build_starts.required_source_read_set) AS enterprise_reads_build(val'
        'ue) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_'
        '44575cf5b28512d7 \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7'
        '.tenant_id = shared_enterprise_build_starts.tenant_id AND enterprise_authori'
        'tative_artifacts_44575cf5b28512d7.source_id = CAST((enterprise_reads_build.v'
        "alue ->> 'artifact_id') AS UUID))))) UNION ALL SELECT 'build' AS source_type"
        ', shared_enterprise_actual_configurations.id AS source_id, shared_enterprise'
        '_actual_configurations.tenant_id AS tenant_id, shared_enterprise_actual_conf'
        'igurations.category_id AS category_id, shared_enterprise_actual_configuratio'
        'ns.product_id AS product_id, shared_enterprise_actual_configurations.project'
        '_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_actu'
        'al_configurations.owner_id AS owner_id, shared_enterprise_actual_configurati'
        "ons.revision AS source_revision, '\u5b9e\u9645\u914d\u7f6e\u8bb0\u5f55 \xb7 "
        "' || shared_enterprise_builds.name AS title, encode(sha256(convert_to(CAST(C"
        "AST(jsonb_build_object('object_id', shared_enterprise_actual_configurations."
        "build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actua"
        "l_configuration', 'build_id', shared_enterprise_actual_configurations.build_"
        "id, 'build_revision', shared_enterprise_actual_configurations.build_revision"
        ", 'status', shared_enterprise_actual_configurations.status, 'planned_enginee"
        "ring_configuration_id', shared_enterprise_actual_configurations.planned_engi"
        "neering_configuration_id, 'planned_manufacturing_configuration_id', shared_e"
        "nterprise_actual_configurations.planned_manufacturing_configuration_id, 'act"
        "ual_engineering_configuration_id', shared_enterprise_actual_configurations.a"
        "ctual_engineering_configuration_id, 'actual_engineering_revision', shared_en"
        "terprise_actual_configurations.actual_engineering_revision, 'actual_manufact"
        "uring_configuration_id', shared_enterprise_actual_configurations.actual_manu"
        "facturing_configuration_id, 'actual_manufacturing_revision', shared_enterpri"
        "se_actual_configurations.actual_manufacturing_revision, 'observed_at', share"
        "d_enterprise_actual_configurations.observed_at), 'source_refs', (SELECT coal"
        "esce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads"
        "_build.value['artifact_id'], 'version', enterprise_reads_build.value['expect"
        "ed_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', ente"
        "rprise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS c"
        'oalesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_configuration'
        "s.required_source_read_set) AS enterprise_reads_build(value)), 'record_polic"
        "y', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CA"
        "ST(jsonb_build_object('object_id', shared_enterprise_actual_configurations.b"
        "uild_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actual"
        "_configuration', 'build_id', shared_enterprise_actual_configurations.build_i"
        "d, 'build_revision', shared_enterprise_actual_configurations.build_revision,"
        " 'status', shared_enterprise_actual_configurations.status, 'planned_engineer"
        "ing_configuration_id', shared_enterprise_actual_configurations.planned_engin"
        "eering_configuration_id, 'planned_manufacturing_configuration_id', shared_en"
        "terprise_actual_configurations.planned_manufacturing_configuration_id, 'actu"
        "al_engineering_configuration_id', shared_enterprise_actual_configurations.ac"
        "tual_engineering_configuration_id, 'actual_engineering_revision', shared_ent"
        "erprise_actual_configurations.actual_engineering_revision, 'actual_manufactu"
        "ring_configuration_id', shared_enterprise_actual_configurations.actual_manuf"
        "acturing_configuration_id, 'actual_manufacturing_revision', shared_enterpris"
        "e_actual_configurations.actual_manufacturing_revision, 'observed_at', shared"
        "_enterprise_actual_configurations.observed_at), 'source_refs', (SELECT coale"
        "sce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_"
        "build.value['artifact_id'], 'version', enterprise_reads_build.value['expecte"
        "d_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enter"
        "prise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS co"
        'alesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations'
        ".required_source_read_set) AS enterprise_reads_build(value)), 'record_policy"
        "', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_actual_configurations.build_id, 'kind', 'build', 'facts', js"
        "onb_build_object('record_kind', 'actual_configuration', 'build_id', shared_e"
        "nterprise_actual_configurations.build_id, 'build_revision', shared_enterpris"
        "e_actual_configurations.build_revision, 'status', shared_enterprise_actual_c"
        "onfigurations.status, 'planned_engineering_configuration_id', shared_enterpr"
        "ise_actual_configurations.planned_engineering_configuration_id, 'planned_man"
        "ufacturing_configuration_id', shared_enterprise_actual_configurations.planne"
        "d_manufacturing_configuration_id, 'actual_engineering_configuration_id', sha"
        "red_enterprise_actual_configurations.actual_engineering_configuration_id, 'a"
        "ctual_engineering_revision', shared_enterprise_actual_configurations.actual_"
        "engineering_revision, 'actual_manufacturing_configuration_id', shared_enterp"
        "rise_actual_configurations.actual_manufacturing_configuration_id, 'actual_ma"
        "nufacturing_revision', shared_enterprise_actual_configurations.actual_manufa"
        "cturing_revision, 'observed_at', shared_enterprise_actual_configurations.obs"
        "erved_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'version'"
        ", enterprise_reads_build.value['expected_revision']) ORDER BY enterprise_rea"
        "ds_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'expected"
        "_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements("
        'shared_enterprise_actual_configurations.required_source_read_set) AS enterpr'
        "ise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_actual_configurations.visibility !"
        "= 'category' OR coalesce(shared_enterprise_projects.visibility != 'category'"
        ", false) OR coalesce(shared_enterprise_products.visibility != 'category', fa"
        'lse) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_actu'
        'al_configurations.required_source_read_set) AS enterprise_reads_build(value)'
        ' JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_auth'
        'oritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_actual_co'
        'nfigurations.tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512'
        "d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.private)) OR s'
        "hared_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT "
        '1 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.requir'
        'ed_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_authori'
        'tative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts_4457'
        '5cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant_id A'
        'ND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((ent'
        "erprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_aut"
        'horitative_artifacts_44575cf5b28512d7.customer_original) AS customer_origina'
        'l, true AS is_current, shared_enterprise_actual_configurations.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_actual_con'
        'figurations.build_id AS object_id, (SELECT coalesce(array_agg(enterprise_aut'
        'horitative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UUID[]) AS coal'
        'esce_6 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.r'
        'equired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_au'
        'thoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts'
        '_44575cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant'
        '_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST'
        "((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpris"
        'e_authoritative_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS origi'
        'nal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ente'
        'rprise_actual_configurations.required_source_read_set) AS enterprise_reads_b'
        'uild(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d7 ON ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_enterpris'
        'e_actual_configurations.tenant_id AND enterprise_authoritative_artifacts_445'
        "75cf5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_i"
        "d') AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.sou"
        "rce_revision != CAST((enterprise_reads_build.value ->> 'expected_revision') "
        "AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status "
        '\nFROM shared_enterprise_actual_configurations JOIN shared_enterprise_projec'
        'ts ON shared_enterprise_projects.tenant_id = shared_enterprise_actual_config'
        'urations.tenant_id AND shared_enterprise_projects.product_id = shared_enterp'
        'rise_actual_configurations.product_id AND shared_enterprise_projects.id = sh'
        'ared_enterprise_actual_configurations.project_id AND shared_enterprise_proje'
        'cts.category_id = shared_enterprise_actual_configurations.category_id JOIN s'
        'hared_enterprise_products ON shared_enterprise_products.tenant_id = shared_e'
        'nterprise_actual_configurations.tenant_id AND shared_enterprise_products.id '
        '= shared_enterprise_actual_configurations.product_id AND shared_enterprise_p'
        'roducts.category_id = shared_enterprise_actual_configurations.category_id JO'
        'IN shared_enterprise_builds ON shared_enterprise_builds.tenant_id = shared_e'
        'nterprise_actual_configurations.tenant_id AND shared_enterprise_builds.categ'
        'ory_id = shared_enterprise_actual_configurations.category_id AND shared_ente'
        'rprise_builds.product_id = shared_enterprise_actual_configurations.product_i'
        'd AND shared_enterprise_builds.project_id = shared_enterprise_actual_configu'
        'rations.project_id AND shared_enterprise_builds.id = shared_enterprise_actua'
        'l_configurations.build_id AND shared_enterprise_builds.revision = shared_ent'
        'erprise_actual_configurations.build_revision \nWHERE shared_enterprise_actua'
        "l_configurations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', t"
        "rue), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(sha"
        'red_enterprise_actual_configurations.required_source_read_set) AS enterprise'
        '_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authorit'
        'ative_artifacts_44575cf5b28512d7 \nWHERE enterprise_authoritative_artifacts_'
        '44575cf5b28512d7.tenant_id = shared_enterprise_actual_configurations.tenant_'
        'id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST('
        "(enterprise_reads_build.value ->> 'artifact_id') AS UUID))))) UNION ALL SELE"
        "CT 'build' AS source_type, shared_enterprise_build_lots.id AS source_id, sha"
        'red_enterprise_build_lots.tenant_id AS tenant_id, shared_enterprise_build_lo'
        'ts.category_id AS category_id, shared_enterprise_build_lots.product_id AS pr'
        'oduct_id, shared_enterprise_build_lots.project_id AS project_id, CAST(NULL A'
        'S UUID) AS proposal_id, shared_enterprise_build_lots.owner_id AS owner_id, s'
        "hared_enterprise_build_lots.revision AS source_revision, '\u5b9e\u7269\u4ea7"
        "\u51fa\u8bb0\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode("
        "sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterpris"
        "e_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_"
        "kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_id, 'b"
        "uild_revision', shared_enterprise_build_lots.build_revision, 'status', share"
        "d_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lots.lo"
        "t_label, 'actual_configuration_id', shared_enterprise_build_lots.actual_conf"
        "iguration_id, 'actual_configuration_revision', shared_enterprise_build_lots."
        "actual_configuration_revision, 'observed_unit_count', shared_enterprise_buil"
        "d_lots.observed_unit_count, 'unit', shared_enterprise_build_lots.unit, 'obse"
        "rvation_nature', shared_enterprise_build_lots.observation_nature, 'occurred_"
        "at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_enterpr"
        "ise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb"
        "_build_object('type', 'artifact', 'id', enterprise_reads_build.value['artifa"
        "ct_id'], 'version', enterprise_reads_build.value['expected_revision']) ORDER"
        " BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.v"
        "alue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jso"
        'nb_array_elements(shared_enterprise_build_lots.required_source_read_set) AS '
        "enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT),"
        " 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_buil"
        "d_object('record_kind', 'build_output', 'build_id', shared_enterprise_build_"
        "lots.build_id, 'build_revision', shared_enterprise_build_lots.build_revision"
        ", 'status', shared_enterprise_build_lots.status, 'lot_label', shared_enterpr"
        "ise_build_lots.lot_label, 'actual_configuration_id', shared_enterprise_build"
        "_lots.actual_configuration_id, 'actual_configuration_revision', shared_enter"
        "prise_build_lots.actual_configuration_revision, 'observed_unit_count', share"
        "d_enterprise_build_lots.observed_unit_count, 'unit', shared_enterprise_build"
        "_lots.unit, 'observation_nature', shared_enterprise_build_lots.observation_n"
        "ature, 'occurred_at', shared_enterprise_build_lots.occurred_at, 'received_at"
        "', shared_enterprise_build_lots.received_at), 'source_refs', (SELECT coalesc"
        "e(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_bu"
        "ild.value['artifact_id'], 'version', enterprise_reads_build.value['expected_"
        "revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterpr"
        "ise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coal"
        'esce_7 \nFROM jsonb_array_elements(shared_enterprise_build_lots.required_sou'
        "rce_read_set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enter"
        "prise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('rec"
        "ord_kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_id"
        ", 'build_revision', shared_enterprise_build_lots.build_revision, 'status', s"
        "hared_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lot"
        "s.lot_label, 'actual_configuration_id', shared_enterprise_build_lots.actual_"
        "configuration_id, 'actual_configuration_revision', shared_enterprise_build_l"
        "ots.actual_configuration_revision, 'observed_unit_count', shared_enterprise_"
        "build_lots.observed_unit_count, 'unit', shared_enterprise_build_lots.unit, '"
        "observation_nature', shared_enterprise_build_lots.observation_nature, 'occur"
        "red_at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_ent"
        "erprise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(j"
        "sonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value['ar"
        "tifact_id'], 'version', enterprise_reads_build.value['expected_revision']) O"
        "RDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_bui"
        "ld.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM"
        ' jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set)'
        " AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_build_lots.visibility "
        "!= 'category' OR coalesce(shared_enterprise_projects.visibility != 'category"
        "', false) OR coalesce(shared_enterprise_products.visibility != 'category', f"
        'alse) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_bui'
        'ld_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN ente'
        'rprise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_'
        'artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_i'
        'd AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST(('
        "enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_"
        'authoritative_artifacts_44575cf5b28512d7.private)) OR shared_enterprise_buil'
        "ds.visibility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_"
        'elements(shared_enterprise_build_lots.required_source_read_set) AS enterpris'
        'e_reads_build(value) JOIN enterprise_authoritative_artifacts_44575cf5b28512d'
        '7 ON enterprise_authoritative_artifacts_44575cf5b28512d7.tenant_id = shared_'
        'enterprise_build_lots.tenant_id AND enterprise_authoritative_artifacts_44575'
        "cf5b28512d7.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id'"
        ') AS UUID) \nWHERE enterprise_authoritative_artifacts_44575cf5b28512d7.custo'
        'mer_original) AS customer_original, true AS is_current, shared_enterprise_bu'
        'ild_lots.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared'
        '_enterprise_build_lots.build_id AS object_id, (SELECT coalesce(array_agg(ent'
        'erprise_authoritative_artifacts_44575cf5b28512d7.original_id), ARRAY[]::UUID'
        '[]) AS coalesce_8 \nFROM jsonb_array_elements(shared_enterprise_build_lots.r'
        'equired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_au'
        'thoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_artifacts'
        '_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_id AND ent'
        'erprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((enterpris'
        "e_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorita"
        'tive_artifacts_44575cf5b28512d7.original_id IS NOT NULL) AS original_ids, CA'
        'SE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_buil'
        'd_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN enter'
        'prise_authoritative_artifacts_44575cf5b28512d7 ON enterprise_authoritative_a'
        'rtifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.tenant_id'
        ' AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id = CAST((e'
        "nterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_a"
        'uthoritative_artifacts_44575cf5b28512d7.source_revision != CAST((enterprise_'
        "reads_build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck"
        "' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_build_lot"
        's JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id = '
        'shared_enterprise_build_lots.tenant_id AND shared_enterprise_projects.produc'
        't_id = shared_enterprise_build_lots.product_id AND shared_enterprise_project'
        's.id = shared_enterprise_build_lots.project_id AND shared_enterprise_project'
        's.category_id = shared_enterprise_build_lots.category_id JOIN shared_enterpr'
        'ise_products ON shared_enterprise_products.tenant_id = shared_enterprise_bui'
        'ld_lots.tenant_id AND shared_enterprise_products.id = shared_enterprise_buil'
        'd_lots.product_id AND shared_enterprise_products.category_id = shared_enterp'
        'rise_build_lots.category_id JOIN shared_enterprise_builds ON shared_enterpri'
        'se_builds.tenant_id = shared_enterprise_build_lots.tenant_id AND shared_ente'
        'rprise_builds.category_id = shared_enterprise_build_lots.category_id AND sha'
        'red_enterprise_builds.product_id = shared_enterprise_build_lots.product_id A'
        'ND shared_enterprise_builds.project_id = shared_enterprise_build_lots.projec'
        't_id AND shared_enterprise_builds.id = shared_enterprise_build_lots.build_id'
        ' AND shared_enterprise_builds.revision = shared_enterprise_build_lots.build_'
        'revision \nWHERE shared_enterprise_build_lots.tenant_id = CAST(nullif(curren'
        "t_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_build_lots.required_source_read_'
        'set) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM e'
        'nterprise_authoritative_artifacts_44575cf5b28512d7 \nWHERE enterprise_author'
        'itative_artifacts_44575cf5b28512d7.tenant_id = shared_enterprise_build_lots.'
        'tenant_id AND enterprise_authoritative_artifacts_44575cf5b28512d7.source_id '
        "= CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID))))))\n SELE"
        'CT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_44575cf5b28512d7'
        ' \nWHERE authoritative_enterprise_sources_44575cf5b28512d7.tenant_id = t AND'
        ' authoritative_enterprise_sources_44575cf5b28512d7.category_id = c AND CAST('
        'authoritative_enterprise_sources_44575cf5b28512d7.source_id AS TEXT) = expec'
        "ted->>'source_id' AND CAST(authoritative_enterprise_sources_44575cf5b28512d7"
        ".source_revision AS TEXT) = expected->>'source_revision' AND authoritative_e"
        "nterprise_sources_44575cf5b28512d7.content_hash = expected->>'content_hash')"
        " AS anon_1 INTO visible;\n WHEN 'test_run' THEN\n  WITH enterprise_authorita"
        "tive_artifacts_b8475898ff5f3dcb AS \n(SELECT 'artifact' AS source_type, arti"
        'fact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, art'
        'ifact_versions.category_id AS category_id, artifact_versions.product_id AS p'
        'roduct_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_'
        'id, artifact_versions.owner_id AS owner_id, artifact_versions.revision AS so'
        'urce_revision, artifact_versions.title AS title, artifact_versions.content_h'
        'ash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) '
        "AS structured, 'untrusted' AS nature, artifact_versions.visibility != 'categ"
        "ory' OR coalesce(products.visibility != 'category', false) OR coalesce(uploa"
        "ded_originals.visibility != 'category', false) AS private, artifact_versions"
        '.original_id IS NOT NULL AS customer_original, true AS is_current, artifact_'
        'versions.created_at AS created_at, artifact_versions.original_id AS original'
        '_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.origina'
        'l_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UU'
        "ID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_ver"
        'sions LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.ten'
        'ant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN upload'
        'ed_originals ON uploaded_originals.tenant_id = artifact_versions.tenant_id A'
        'ND uploaded_originals.id = artifact_versions.original_id AND uploaded_origin'
        'als.category_id = artifact_versions.category_id AND uploaded_originals.produ'
        'ct_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN orig'
        'inal_security ON original_security.tenant_id = uploaded_originals.tenant_id '
        'AND original_security.original_id = uploaded_originals.id \nWHERE artifact_v'
        "ersions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '')"
        " AS UUID) AND artifact_versions.status = 'active' AND artifact_versions.cate"
        'gory_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products.id'
        ' IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_origina'
        "ls.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_orig"
        "inals.scan_status = 'clean' AND original_security.source_state = 'active' AN"
        "D original_security.disposition = 'active' AND original_security.current_req"
        'uest_id IS NOT NULL)), \nshared_enterprise_verification_run_versions AS MATE'
        'RIALIZED \n(SELECT verification_run_versions.product_id AS product_id, verif'
        'ication_run_versions.project_id AS project_id, verification_run_versions.bui'
        'ld_id AS build_id, verification_run_versions.build_revision AS build_revisio'
        'n, verification_run_versions.request_id AS request_id, verification_run_vers'
        'ions.request_version_id AS request_version_id, verification_run_versions.req'
        'uest_revision AS request_revision, verification_run_versions.run_id AS run_i'
        'd, verification_run_versions.revision AS revision, verification_run_versions'
        '.previous_run_version_id AS previous_run_version_id, verification_run_versio'
        'ns.previous_revision AS previous_revision, verification_run_versions.owner_i'
        'd AS owner_id, verification_run_versions.writer_id AS writer_id, verificatio'
        'n_run_versions.visibility AS visibility, verification_run_versions.status AS'
        ' status, verification_run_versions.operation AS operation, verification_run_'
        'versions.run_snapshot AS run_snapshot, verification_run_versions.execution_p'
        'lan AS execution_plan, verification_run_versions.plan_sha256 AS plan_sha256,'
        ' verification_run_versions.input_snapshot AS input_snapshot, verification_ru'
        'n_versions.snapshot_sha256 AS snapshot_sha256, verification_run_versions.sou'
        'rces AS sources, verification_run_versions.required_source_read_set AS requi'
        'red_source_read_set, verification_run_versions.source_basis AS source_basis,'
        ' verification_run_versions.authority_snapshot AS authority_snapshot, verific'
        'ation_run_versions.intent_digest AS intent_digest, verification_run_versions'
        '.reason AS reason, verification_run_versions.id AS id, verification_run_vers'
        'ions.tenant_id AS tenant_id, verification_run_versions.created_at AS created'
        '_at, verification_run_versions.category_id AS category_id \nFROM verificatio'
        'n_run_versions \nWHERE verification_run_versions.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_pro"
        'jects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, projects.'
        'owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, pr'
        'ojects.scope AS scope, projects.visibility AS visibility, projects.status AS'
        ' status, projects.revision AS revision, projects.current_plan_id AS current_'
        'plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS trigg'
        'er_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, project'
        's.tenant_id AS tenant_id, projects.created_at AS created_at, projects.catego'
        'ry_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nulli'
        "f(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpris"
        'e_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpose'
        ' AS purpose, products.revision AS revision, products.lifecycle_epoch AS life'
        'cycle_epoch, products.status AS status, products.owner_id AS owner_id, produ'
        'cts.parent_product_id AS parent_product_id, products.category_id AS category'
        '_id, products.visibility AS visibility, products.target_price AS target_pric'
        'e, products.target_price_currency AS target_price_currency, products.target_'
        'price_basis AS target_price_basis, products.target_price_includes_tax AS tar'
        'get_price_includes_tax, products.target_price_as_of AS target_price_as_of, p'
        'roducts.id AS id, products.tenant_id AS tenant_id, products.created_at AS cr'
        'eated_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_se'
        "tting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_builds AS "
        'MATERIALIZED \n(SELECT builds.product_id AS product_id, builds.project_id AS'
        ' project_id, builds.project_revision AS project_revision, builds.engineering'
        '_configuration_id AS engineering_configuration_id, builds.manufacturing_conf'
        'iguration_id AS manufacturing_configuration_id, builds.previous_build_id AS '
        'previous_build_id, builds.owner_id AS owner_id, builds.name AS name, builds.'
        'type AS type, builds.purpose AS purpose, builds.planned_quantity AS planned_'
        'quantity, builds.unit AS unit, builds.planned_start AS planned_start, builds'
        '.planned_end AS planned_end, builds.verification_objectives AS verification_'
        'objectives, builds.disposition_plan AS disposition_plan, builds.visibility A'
        'S visibility, builds.revision AS revision, builds.status AS status, builds.i'
        'd AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_at, bui'
        'lds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ent"
        'erprise_verification_current_runs AS MATERIALIZED \n(SELECT verification_cur'
        'rent_runs.product_id AS product_id, verification_current_runs.request_id AS '
        'request_id, verification_current_runs.run_id AS run_id, verification_current'
        '_runs.run_version_id AS run_version_id, verification_current_runs.run_revisi'
        'on AS run_revision, verification_current_runs.id AS id, verification_current'
        '_runs.tenant_id AS tenant_id, verification_current_runs.created_at AS create'
        'd_at, verification_current_runs.category_id AS category_id \nFROM verificati'
        'on_current_runs \nWHERE verification_current_runs.tenant_id = CAST(nullif(cu'
        "rrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_te"
        'st_result_actions AS MATERIALIZED \n(SELECT test_result_actions.operation AS'
        ' operation, test_result_actions.actor_id AS actor_id, test_result_actions.in'
        'tent_digest AS intent_digest, test_result_actions.request_version_id AS requ'
        'est_version_id, test_result_actions.request_revision AS request_revision, te'
        'st_result_actions.next_request_version_id AS next_request_version_id, test_r'
        'esult_actions.next_request_revision AS next_request_revision, test_result_ac'
        'tions.run_version_id AS run_version_id, test_result_actions.run_revision AS '
        'run_revision, test_result_actions.next_run_version_id AS next_run_version_id'
        ', test_result_actions.next_run_revision AS next_run_revision, test_result_ac'
        'tions.capture_id AS capture_id, test_result_actions.projection_id AS project'
        'ion_id, test_result_actions.input_snapshot AS input_snapshot, test_result_ac'
        'tions.authority_snapshot AS authority_snapshot, test_result_actions.event AS'
        ' event, test_result_actions.sources AS sources, test_result_actions.required'
        '_source_read_set AS required_source_read_set, test_result_actions.source_bas'
        'is AS source_basis, test_result_actions.reason AS reason, test_result_action'
        's.product_id AS product_id, test_result_actions.project_id AS project_id, te'
        'st_result_actions.build_id AS build_id, test_result_actions.request_id AS re'
        'quest_id, test_result_actions.run_id AS run_id, test_result_actions.revision'
        ' AS revision, test_result_actions.owner_id AS owner_id, test_result_actions.'
        'visibility AS visibility, test_result_actions.status AS status, test_result_'
        'actions.id AS id, test_result_actions.tenant_id AS tenant_id, test_result_ac'
        'tions.created_at AS created_at, test_result_actions.category_id AS category_'
        'id \nFROM test_result_actions \nWHERE test_result_actions.tenant_id = CAST(n'
        "ullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritativ"
        "e_enterprise_sources_b8475898ff5f3dcb AS \n(SELECT 'test_run' AS source_type"
        ', shared_enterprise_verification_run_versions.id AS source_id, shared_enterp'
        'rise_verification_run_versions.tenant_id AS tenant_id, shared_enterprise_ver'
        'ification_run_versions.category_id AS category_id, shared_enterprise_verific'
        'ation_run_versions.product_id AS product_id, shared_enterprise_verification_'
        'run_versions.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, sh'
        'ared_enterprise_verification_run_versions.owner_id AS owner_id, shared_enter'
        "prise_verification_run_versions.revision AS source_revision, '\u6d4b\u8bd5"
        "\u8fd0\u884c \xb7 ' || CAST(shared_enterprise_verification_run_versions.run_"
        'id AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('
        "'object_id', shared_enterprise_verification_run_versions.run_id, 'kind', 'te"
        "st_run', 'facts', jsonb_build_object('id', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['id'], 'revision', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['revision'], 'request_id', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['request_id'], 'status', shared_enterprise_v"
        "erification_run_versions.run_snapshot['status'], 'result', shared_enterprise"
        "_verification_run_versions.run_snapshot['result']) || jsonb_build_object('ac"
        "tual_start', jsonb_build_object('occurred_at', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['actual_start']['occurred_at'], 'original_timezo"
        "ne', shared_enterprise_verification_run_versions.run_snapshot['actual_start'"
        "]['original_timezone'], 'effective_at', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['actual_start']['effective_at']), 'actual_end', jsonb_b"
        "uild_object('occurred_at', shared_enterprise_verification_run_versions.run_s"
        "napshot['actual_end']['occurred_at'], 'original_timezone', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_end']['original_timezone'], "
        "'effective_at', shared_enterprise_verification_run_versions.run_snapshot['ac"
        "tual_end']['effective_at']), 'preliminary_result', jsonb_build_object('occur"
        "red_at', shared_enterprise_verification_run_versions.run_snapshot['prelimina"
        "ry_result']['occurred_at'], 'original_timezone', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['preliminary_result']['original_timezone'], 'e"
        "ffective_at', shared_enterprise_verification_run_versions.run_snapshot['prel"
        "iminary_result']['effective_at']), 'final_result', jsonb_build_object('occur"
        "red_at', shared_enterprise_verification_run_versions.run_snapshot['final_res"
        "ult']['occurred_at'], 'original_timezone', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['final_result']['original_timezone'], 'effective_at'"
        ", shared_enterprise_verification_run_versions.run_snapshot['final_result']['"
        "effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_obje"
        "ct('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact_id'],"
        " 'version', enterprise_reads_test_run.value['expected_revision']) ORDER BY e"
        "nterprise_reads_test_run.value ->> 'artifact_id', enterprise_reads_test_run."
        "value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM js"
        'onb_array_elements(shared_enterprise_verification_run_versions.required_sour'
        "ce_read_set) AS enterprise_reads_test_run(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_o"
        "bject('object_id', shared_enterprise_verification_run_versions.run_id, 'kind"
        "', 'test_run', 'facts', jsonb_build_object('id', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['id'], 'revision', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['revision'], 'request_id', shared_enterprise_v"
        "erification_run_versions.run_snapshot['request_id'], 'status', shared_enterp"
        "rise_verification_run_versions.run_snapshot['status'], 'result', shared_ente"
        "rprise_verification_run_versions.run_snapshot['result']) || jsonb_build_obje"
        "ct('actual_start', jsonb_build_object('occurred_at', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['actual_start']['occurred_at'], 'original_"
        "timezone', shared_enterprise_verification_run_versions.run_snapshot['actual_"
        "start']['original_timezone'], 'effective_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['actual_start']['effective_at']), 'actual_end', j"
        "sonb_build_object('occurred_at', shared_enterprise_verification_run_versions"
        ".run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_ente"
        "rprise_verification_run_versions.run_snapshot['actual_end']['original_timezo"
        "ne'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['actual_end']['effective_at']), 'preliminary_result', jsonb_build_object("
        "'occurred_at', shared_enterprise_verification_run_versions.run_snapshot['pre"
        "liminary_result']['occurred_at'], 'original_timezone', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['preliminary_result']['original_timezone"
        "'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot"
        "['preliminary_result']['effective_at']), 'final_result', jsonb_build_object("
        "'occurred_at', shared_enterprise_verification_run_versions.run_snapshot['fin"
        "al_result']['occurred_at'], 'original_timezone', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['final_result']['original_timezone'], 'effecti"
        "ve_at', shared_enterprise_verification_run_versions.run_snapshot['final_resu"
        "lt']['effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact"
        "_id'], 'version', enterprise_reads_test_run.value['expected_revision']) ORDE"
        "R BY enterprise_reads_test_run.value ->> 'artifact_id', enterprise_reads_tes"
        "t_run.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        'ROM jsonb_array_elements(shared_enterprise_verification_run_versions.require'
        "d_source_read_set) AS enterprise_reads_test_run(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e'
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_verification_run_versions.run_id, 'kind', 'test_run', 'facts"
        "', jsonb_build_object('id', shared_enterprise_verification_run_versions.run_"
        "snapshot['id'], 'revision', shared_enterprise_verification_run_versions.run_"
        "snapshot['revision'], 'request_id', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['request_id'], 'status', shared_enterprise_verification_run"
        "_versions.run_snapshot['status'], 'result', shared_enterprise_verification_r"
        "un_versions.run_snapshot['result']) || jsonb_build_object('actual_start', js"
        "onb_build_object('occurred_at', shared_enterprise_verification_run_versions."
        "run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared_ent"
        "erprise_verification_run_versions.run_snapshot['actual_start']['original_tim"
        "ezone'], 'effective_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_start']['effective_at']), 'actual_end', jsonb_build_object('oc"
        "curred_at', shared_enterprise_verification_run_versions.run_snapshot['actual"
        "_end']['occurred_at'], 'original_timezone', shared_enterprise_verification_r"
        "un_versions.run_snapshot['actual_end']['original_timezone'], 'effective_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['actual_end']['eff"
        "ective_at']), 'preliminary_result', jsonb_build_object('occurred_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['preliminary_result']['oc"
        "curred_at'], 'original_timezone', shared_enterprise_verification_run_version"
        "s.run_snapshot['preliminary_result']['original_timezone'], 'effective_at', s"
        "hared_enterprise_verification_run_versions.run_snapshot['preliminary_result'"
        "]['effective_at']), 'final_result', jsonb_build_object('occurred_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['final_result']['occurred"
        "_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_"
        "snapshot['final_result']['original_timezone'], 'effective_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['final_result']['effective_at'])"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'art"
        "ifact', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', ent"
        "erprise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads"
        "_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expe"
        "cted_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_eleme"
        'nts(shared_enterprise_verification_run_versions.required_source_read_set) AS'
        " enterprise_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_verification_run_versi"
        "ons.visibility != 'category' OR coalesce(shared_enterprise_projects.visibili"
        "ty != 'category', false) OR coalesce(shared_enterprise_products.visibility !"
        "= 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared"
        '_enterprise_verification_run_versions.required_source_read_set) AS enterpris'
        'e_reads_test_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f'
        '3dcb ON enterprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shar'
        'ed_enterprise_verification_run_versions.tenant_id AND enterprise_authoritati'
        've_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.va'
        "lue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b"
        "8475898ff5f3dcb.private)) OR shared_enterprise_builds.visibility != 'categor"
        "y' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpris"
        'e_verification_run_versions.required_source_read_set) AS enterprise_reads_te'
        'st_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON en'
        'terprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterpr'
        'ise_verification_run_versions.tenant_id AND enterprise_authoritative_artifac'
        "ts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'a"
        "rtifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b8475898ff5"
        'f3dcb.customer_original) AS customer_original, shared_enterprise_verificatio'
        'n_current_runs.run_version_id = shared_enterprise_verification_run_versions.'
        'id AS is_current, shared_enterprise_verification_run_versions.created_at AS '
        'created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_verificatio'
        'n_run_versions.run_id AS object_id, (SELECT coalesce(array_agg(enterprise_au'
        'thoritative_artifacts_b8475898ff5f3dcb.original_id), ARRAY[]::UUID[]) AS coa'
        'lesce_2 \nFROM jsonb_array_elements(shared_enterprise_verification_run_versi'
        'ons.required_source_read_set) AS enterprise_reads_test_run(value) JOIN enter'
        'prise_authoritative_artifacts_b8475898ff5f3dcb ON enterprise_authoritative_a'
        'rtifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_verification_run_ver'
        'sions.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.sour'
        "ce_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.original_id IS NOT'
        ' NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_eleme'
        'nts(shared_enterprise_verification_run_versions.required_source_read_set) AS'
        ' enterprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_b8'
        '475898ff5f3dcb ON enterprise_authoritative_artifacts_b8475898ff5f3dcb.tenant'
        '_id = shared_enterprise_verification_run_versions.tenant_id AND enterprise_a'
        'uthoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_reads_t'
        "est_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_a"
        'rtifacts_b8475898ff5f3dcb.source_revision != CAST((enterprise_reads_test_run'
        ".value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'cur"
        "rent' END AS read_basis_status \nFROM shared_enterprise_verification_run_ver"
        'sions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_i'
        'd = shared_enterprise_verification_run_versions.tenant_id AND shared_enterpr'
        'ise_projects.product_id = shared_enterprise_verification_run_versions.produc'
        't_id AND shared_enterprise_projects.id = shared_enterprise_verification_run_'
        'versions.project_id AND shared_enterprise_projects.category_id = shared_ente'
        'rprise_verification_run_versions.category_id JOIN shared_enterprise_products'
        ' ON shared_enterprise_products.tenant_id = shared_enterprise_verification_ru'
        'n_versions.tenant_id AND shared_enterprise_products.id = shared_enterprise_v'
        'erification_run_versions.product_id AND shared_enterprise_products.category_'
        'id = shared_enterprise_verification_run_versions.category_id JOIN shared_ent'
        'erprise_builds ON shared_enterprise_builds.tenant_id = shared_enterprise_ver'
        'ification_run_versions.tenant_id AND shared_enterprise_builds.category_id = '
        'shared_enterprise_verification_run_versions.category_id AND shared_enterpris'
        'e_builds.product_id = shared_enterprise_verification_run_versions.product_id'
        ' AND shared_enterprise_builds.project_id = shared_enterprise_verification_ru'
        'n_versions.project_id AND shared_enterprise_builds.id = shared_enterprise_ve'
        'rification_run_versions.build_id AND shared_enterprise_builds.revision = sha'
        'red_enterprise_verification_run_versions.build_revision JOIN shared_enterpri'
        'se_verification_current_runs ON shared_enterprise_verification_current_runs.'
        'tenant_id = shared_enterprise_verification_run_versions.tenant_id AND shared'
        '_enterprise_verification_current_runs.product_id = shared_enterprise_verific'
        'ation_run_versions.product_id AND shared_enterprise_verification_current_run'
        's.run_id = shared_enterprise_verification_run_versions.run_id \nWHERE shared'
        '_enterprise_verification_run_versions.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jso"
        'nb_array_elements(shared_enterprise_verification_run_versions.required_sourc'
        'e_read_set) AS enterprise_reads_test_run(value) \nWHERE NOT (EXISTS (SELECT '
        '1 \nFROM enterprise_authoritative_artifacts_b8475898ff5f3dcb \nWHERE enterpr'
        'ise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_v'
        'erification_run_versions.tenant_id AND enterprise_authoritative_artifacts_b8'
        "475898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'artifa"
        "ct_id') AS UUID))))) UNION ALL SELECT 'test_run' AS source_type, shared_ente"
        'rprise_test_result_actions.id AS source_id, shared_enterprise_test_result_ac'
        'tions.tenant_id AS tenant_id, shared_enterprise_test_result_actions.category'
        '_id AS category_id, shared_enterprise_test_result_actions.product_id AS prod'
        'uct_id, shared_enterprise_test_result_actions.project_id AS project_id, CAST'
        '(NULL AS UUID) AS proposal_id, shared_enterprise_test_result_actions.owner_i'
        'd AS owner_id, shared_enterprise_test_result_actions.revision AS source_revi'
        "sion, CASE WHEN (shared_enterprise_test_result_actions.operation = 'test.run"
        ".review') THEN '\u4e13\u4e1a\u8bc4\u5ba1\u8bb0\u5f55 \xb7 ' WHEN (shared_ent"
        "erprise_test_result_actions.operation = 'test.disposition.decide') THEN '"
        "\u6d4b\u8bd5\u5904\u7f6e\u8bb0\u5f55 \xb7 ' ELSE '\u6d4b\u8bd5\u7ed3\u679c"
        "\u8bb0\u5f55 \xb7 ' END || CAST(shared_enterprise_test_result_actions.run_id"
        " AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('o"
        "bject_id', shared_enterprise_test_result_actions.run_id, 'kind', 'test_run',"
        " 'facts', (jsonb_build_object('id', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['id'], 'revision', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['revision'], 'request_id', shared_enterprise_verification_r"
        "un_versions.run_snapshot['request_id'], 'status', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['status'], 'result', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['result']) || jsonb_build_object('record_ki"
        "nd', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "sample_id', enterprise_run_coverage.value['sample_id'], 'item_id', enterpris"
        "e_run_coverage.value['item_id']) ORDER BY enterprise_run_coverage.ordinal), "
        'jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(shar'
        "ed_enterprise_verification_run_versions.run_snapshot['coverage'], CAST('[]' "
        "AS JSONB))) WITH ORDINALITY AS enterprise_run_coverage(value, ordinal)), 'co"
        "mputed_results', (SELECT coalesce(jsonb_agg(jsonb_build_object('coverage', e"
        "nterprise_computed_results.value['coverage'], 'result', enterprise_computed_"
        "results.value['result'], 'measurement_id', enterprise_computed_results.value"
        "['measurement_id']) ORDER BY enterprise_computed_results.ordinal), jsonb_bui"
        'ld_array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterp'
        "rise_verification_run_versions.run_snapshot['computed_results'], CAST('[]' A"
        'S JSONB))) WITH ORDINALITY AS enterprise_computed_results(value, ordinal)), '
        "'professional_conclusion', CASE WHEN (((shared_enterprise_verification_run_v"
        "ersions.run_snapshot['professional_conclusion']) ->> 'actor_id') IS NULL) TH"
        "EN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['professional_conclusion']['text'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['profession"
        "al_conclusion']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared"
        "_enterprise_verification_run_versions.run_snapshot['professional_conclusion'"
        "]['at']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_bui"
        "ld_object('occurred_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['professional_conclusion']['at']['occurred_at'], 'original_timezone', "
        "shared_enterprise_verification_run_versions.run_snapshot['professional_concl"
        "usion']['at']['original_timezone'], 'effective_at', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['professional_conclusion']['at']['effective"
        "_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['professional_conclusion']['at']['received_at'], 'actor_id', shared_enter"
        "prise_verification_run_versions.run_snapshot['professional_conclusion']['at'"
        "]['actor_id']) END, 'source_reference', jsonb_build_object('kind', shared_en"
        "terprise_verification_run_versions.run_snapshot['professional_conclusion']['"
        "source']['kind'], 'id', shared_enterprise_verification_run_versions.run_snap"
        "shot['professional_conclusion']['source']['id'], 'revision', shared_enterpri"
        "se_verification_run_versions.run_snapshot['professional_conclusion']['source"
        "']['revision'])) END, 'disposition', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['disposition']) ->> 'actor_id') IS NULL) THEN"
        " CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['text'], 'actor_id', shared"
        "_enterprise_verification_run_versions.run_snapshot['disposition']['actor_id'"
        "]) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_verification_r"
        "un_versions.run_snapshot['disposition']['at']) ->> 'occurred_at') IS NULL) T"
        "HEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['disposition']['at']['occurred_a"
        "t'], 'original_timezone', shared_enterprise_verification_run_versions.run_sn"
        "apshot['disposition']['at']['original_timezone'], 'effective_at', shared_ent"
        "erprise_verification_run_versions.run_snapshot['disposition']['at']['effecti"
        "ve_at'], 'received_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['disposition']['at']['received_at'], 'actor_id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['disposition']['at']['actor_id']) END, 's"
        "ource_reference', jsonb_build_object('kind', shared_enterprise_verification_"
        "run_versions.run_snapshot['disposition']['source']['kind'], 'id', shared_ent"
        "erprise_verification_run_versions.run_snapshot['disposition']['source']['id'"
        "], 'revision', shared_enterprise_verification_run_versions.run_snapshot['dis"
        "position']['source']['revision'])) END, 'actual_start', CASE WHEN (((shared_"
        "enterprise_verification_run_versions.run_snapshot['actual_start']) ->> 'occu"
        "rred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurre"
        "d_at', shared_enterprise_verification_run_versions.run_snapshot['actual_star"
        "t']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_"
        "versions.run_snapshot['actual_start']['original_timezone'], 'effective_at', "
        "shared_enterprise_verification_run_versions.run_snapshot['actual_start']['ef"
        "fective_at'], 'received_at', shared_enterprise_verification_run_versions.run"
        "_snapshot['actual_start']['received_at'], 'actor_id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['actual_start']['actor_id']) END, 'actual"
        "_end', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapshot"
        "['actual_end']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE js"
        "onb_build_object('occurred_at', shared_enterprise_verification_run_versions."
        "run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_enter"
        "prise_verification_run_versions.run_snapshot['actual_end']['original_timezon"
        "e'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['actual_end']['effective_at'], 'received_at', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['actual_end']['received_at'], 'actor_id', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_end']['actor_id'"
        "]) END, 'preliminary_result', CASE WHEN (((shared_enterprise_verification_ru"
        "n_versions.run_snapshot['preliminary_result']) ->> 'occurred_at') IS NULL) T"
        "HEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['preliminary_result']['occurred_"
        "at'], 'original_timezone', shared_enterprise_verification_run_versions.run_s"
        "napshot['preliminary_result']['original_timezone'], 'effective_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['preliminary_result']['effe"
        "ctive_at'], 'received_at', shared_enterprise_verification_run_versions.run_s"
        "napshot['preliminary_result']['received_at'], 'actor_id', shared_enterprise_"
        "verification_run_versions.run_snapshot['preliminary_result']['actor_id']) EN"
        "D, 'final_result', CASE WHEN (((shared_enterprise_verification_run_versions."
        "run_snapshot['final_result']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS "
        "JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['final_result']['occurred_at'], 'original_timezon"
        "e', shared_enterprise_verification_run_versions.run_snapshot['final_result']"
        "['original_timezone'], 'effective_at', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['final_result']['effective_at'], 'received_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['final_result']['received_a"
        "t'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['f"
        "inal_result']['actor_id']) END)) || jsonb_build_object('record_kind', 'test_"
        "result_action', 'operation', shared_enterprise_test_result_actions.operation"
        ", 'actor_id', shared_enterprise_test_result_actions.actor_id, 'run_version_i"
        "d', shared_enterprise_verification_run_versions.id, 'run_revision', shared_e"
        "nterprise_verification_run_versions.revision), 'source_refs', (SELECT coales"
        "ce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_t"
        "est_run.value['artifact_id'], 'version', enterprise_reads_test_run.value['ex"
        "pected_revision']) ORDER BY enterprise_reads_test_run.value ->> 'artifact_id"
        "', enterprise_reads_test_run.value ->> 'expected_revision'), jsonb_build_arr"
        'ay()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_test_resul'
        "t_actions.required_source_read_set) AS enterprise_reads_test_run(value)), 'r"
        "ecord_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, C"
        "AST(CAST(jsonb_build_object('object_id', shared_enterprise_test_result_actio"
        "ns.run_id, 'kind', 'test_run', 'facts', (jsonb_build_object('id', shared_ent"
        "erprise_verification_run_versions.run_snapshot['id'], 'revision', shared_ent"
        "erprise_verification_run_versions.run_snapshot['revision'], 'request_id', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['request_id'], 'statu"
        "s', shared_enterprise_verification_run_versions.run_snapshot['status'], 'res"
        "ult', shared_enterprise_verification_run_versions.run_snapshot['result']) ||"
        " jsonb_build_object('record_kind', 'test_run', 'coverage', (SELECT coalesce("
        "jsonb_agg(jsonb_build_object('sample_id', enterprise_run_coverage.value['sam"
        "ple_id'], 'item_id', enterprise_run_coverage.value['item_id']) ORDER BY ente"
        'rprise_run_coverage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM json'
        'b_array_elements(coalesce(shared_enterprise_verification_run_versions.run_sn'
        "apshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_"
        "coverage(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('coverage', enterprise_computed_results.value['coverage'], "
        "'result', enterprise_computed_results.value['result'], 'measurement_id', ent"
        "erprise_computed_results.value['measurement_id']) ORDER BY enterprise_comput"
        'ed_results.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_e'
        "lements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['c"
        "omputed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_compu"
        "ted_results(value, ordinal)), 'professional_conclusion', CASE WHEN (((shared"
        "_enterprise_verification_run_versions.run_snapshot['professional_conclusion'"
        "]) ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('text', shared_enterprise_verification_run_versions.run_snapshot['professio"
        "nal_conclusion']['text'], 'actor_id', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['professional_conclusion']['actor_id']) || jsonb_build_ob"
        "ject('at', CASE WHEN (((shared_enterprise_verification_run_versions.run_snap"
        "shot['professional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST"
        "(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['professional_conclusion']['at']['occurr"
        "ed_at'], 'original_timezone', shared_enterprise_verification_run_versions.ru"
        "n_snapshot['professional_conclusion']['at']['original_timezone'], 'effective"
        "_at', shared_enterprise_verification_run_versions.run_snapshot['professional"
        "_conclusion']['at']['effective_at'], 'received_at', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['professional_conclusion']['at']['received_"
        "at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['"
        "professional_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_"
        "build_object('kind', shared_enterprise_verification_run_versions.run_snapsho"
        "t['professional_conclusion']['source']['kind'], 'id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['professional_conclusion']['source']['id'"
        "], 'revision', shared_enterprise_verification_run_versions.run_snapshot['pro"
        "fessional_conclusion']['source']['revision'])) END, 'disposition', CASE WHEN"
        " (((shared_enterprise_verification_run_versions.run_snapshot['disposition'])"
        " ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('"
        "text', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['text'], 'actor_id', shared_enterprise_verification_run_versions.run_snap"
        "shot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((sh"
        "ared_enterprise_verification_run_versions.run_snapshot['disposition']['at'])"
        " ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_objec"
        "t('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['d"
        "isposition']['at']['occurred_at'], 'original_timezone', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['disposition']['at']['original_timezone"
        "'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot"
        "['disposition']['at']['effective_at'], 'received_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['disposition']['at']['received_at'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['dispositio"
        "n']['at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', s"
        "hared_enterprise_verification_run_versions.run_snapshot['disposition']['sour"
        "ce']['kind'], 'id', shared_enterprise_verification_run_versions.run_snapshot"
        "['disposition']['source']['id'], 'revision', shared_enterprise_verification_"
        "run_versions.run_snapshot['disposition']['source']['revision'])) END, 'actua"
        "l_start', CASE WHEN (((shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) EL"
        "SE jsonb_build_object('occurred_at', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['actual_start']['occurred_at'], 'original_timezone', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_start']['origina"
        "l_timezone'], 'effective_at', shared_enterprise_verification_run_versions.ru"
        "n_snapshot['actual_start']['effective_at'], 'received_at', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_start']['received_at'], 'act"
        "or_id', shared_enterprise_verification_run_versions.run_snapshot['actual_sta"
        "rt']['actor_id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) TH"
        "EN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'or"
        "iginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['"
        "actual_end']['original_timezone'], 'effective_at', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['actual_end']['effective_at'], 'received_at'"
        ", shared_enterprise_verification_run_versions.run_snapshot['actual_end']['re"
        "ceived_at'], 'actor_id', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((sha"
        "red_enterprise_verification_run_versions.run_snapshot['preliminary_result'])"
        " ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_objec"
        "t('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['p"
        "reliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_v"
        "erification_run_versions.run_snapshot['preliminary_result']['original_timezo"
        "ne'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['preliminary_result']['effective_at'], 'received_at', shared_enterprise_v"
        "erification_run_versions.run_snapshot['preliminary_result']['received_at'], "
        "'actor_id', shared_enterprise_verification_run_versions.run_snapshot['prelim"
        "inary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterpr"
        "ise_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at"
        "') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', "
        "shared_enterprise_verification_run_versions.run_snapshot['final_result']['oc"
        "curred_at'], 'original_timezone', shared_enterprise_verification_run_version"
        "s.run_snapshot['final_result']['original_timezone'], 'effective_at', shared_"
        "enterprise_verification_run_versions.run_snapshot['final_result']['effective"
        "_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['final_result']['received_at'], 'actor_id', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_buil"
        "d_object('record_kind', 'test_result_action', 'operation', shared_enterprise"
        "_test_result_actions.operation, 'actor_id', shared_enterprise_test_result_ac"
        "tions.actor_id, 'run_version_id', shared_enterprise_verification_run_version"
        "s.id, 'run_revision', shared_enterprise_verification_run_versions.revision),"
        " 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artif"
        "act', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', enter"
        "prise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads_t"
        "est_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expect"
        "ed_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_element"
        's(shared_enterprise_test_result_actions.required_source_read_set) AS enterpr'
        "ise_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS bod"
        "y, CAST(jsonb_build_object('object_id', shared_enterprise_test_result_action"
        "s.run_id, 'kind', 'test_run', 'facts', (jsonb_build_object('id', shared_ente"
        "rprise_verification_run_versions.run_snapshot['id'], 'revision', shared_ente"
        "rprise_verification_run_versions.run_snapshot['revision'], 'request_id', sha"
        "red_enterprise_verification_run_versions.run_snapshot['request_id'], 'status"
        "', shared_enterprise_verification_run_versions.run_snapshot['status'], 'resu"
        "lt', shared_enterprise_verification_run_versions.run_snapshot['result']) || "
        "jsonb_build_object('record_kind', 'test_run', 'coverage', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('sample_id', enterprise_run_coverage.value['samp"
        "le_id'], 'item_id', enterprise_run_coverage.value['item_id']) ORDER BY enter"
        'prise_run_coverage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb'
        '_array_elements(coalesce(shared_enterprise_verification_run_versions.run_sna'
        "pshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_c"
        "overage(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('coverage', enterprise_computed_results.value['coverage'], '"
        "result', enterprise_computed_results.value['result'], 'measurement_id', ente"
        "rprise_computed_results.value['measurement_id']) ORDER BY enterprise_compute"
        'd_results.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_el'
        "ements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['co"
        "mputed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_comput"
        "ed_results(value, ordinal)), 'professional_conclusion', CASE WHEN (((shared_"
        "enterprise_verification_run_versions.run_snapshot['professional_conclusion']"
        ") ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object("
        "'text', shared_enterprise_verification_run_versions.run_snapshot['profession"
        "al_conclusion']['text'], 'actor_id', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['professional_conclusion']['actor_id']) || jsonb_build_obj"
        "ect('at', CASE WHEN (((shared_enterprise_verification_run_versions.run_snaps"
        "hot['professional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST("
        "NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['professional_conclusion']['at']['occurre"
        "d_at'], 'original_timezone', shared_enterprise_verification_run_versions.run"
        "_snapshot['professional_conclusion']['at']['original_timezone'], 'effective_"
        "at', shared_enterprise_verification_run_versions.run_snapshot['professional_"
        "conclusion']['at']['effective_at'], 'received_at', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['professional_conclusion']['at']['received_a"
        "t'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['p"
        "rofessional_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_b"
        "uild_object('kind', shared_enterprise_verification_run_versions.run_snapshot"
        "['professional_conclusion']['source']['kind'], 'id', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['professional_conclusion']['source']['id']"
        ", 'revision', shared_enterprise_verification_run_versions.run_snapshot['prof"
        "essional_conclusion']['source']['revision'])) END, 'disposition', CASE WHEN "
        "(((shared_enterprise_verification_run_versions.run_snapshot['disposition']) "
        "->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('t"
        "ext', shared_enterprise_verification_run_versions.run_snapshot['disposition'"
        "]['text'], 'actor_id', shared_enterprise_verification_run_versions.run_snaps"
        "hot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((sha"
        "red_enterprise_verification_run_versions.run_snapshot['disposition']['at']) "
        "->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['di"
        "sposition']['at']['occurred_at'], 'original_timezone', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['disposition']['at']['original_timezone'"
        "], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot["
        "'disposition']['at']['effective_at'], 'received_at', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['at']['received_at'], 'acto"
        "r_id', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['disposition']['sourc"
        "e']['kind'], 'id', shared_enterprise_verification_run_versions.run_snapshot["
        "'disposition']['source']['id'], 'revision', shared_enterprise_verification_r"
        "un_versions.run_snapshot['disposition']['source']['revision'])) END, 'actual"
        "_start', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapsh"
        "ot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELS"
        "E jsonb_build_object('occurred_at', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared"
        "_enterprise_verification_run_versions.run_snapshot['actual_start']['original"
        "_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run"
        "_snapshot['actual_start']['effective_at'], 'received_at', shared_enterprise_"
        "verification_run_versions.run_snapshot['actual_start']['received_at'], 'acto"
        "r_id', shared_enterprise_verification_run_versions.run_snapshot['actual_star"
        "t']['actor_id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) THE"
        "N CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpri"
        "se_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'ori"
        "ginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['a"
        "ctual_end']['original_timezone'], 'effective_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['actual_end']['effective_at'], 'received_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['actual_end']['rec"
        "eived_at'], 'actor_id', shared_enterprise_verification_run_versions.run_snap"
        "shot['actual_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((shar"
        "ed_enterprise_verification_run_versions.run_snapshot['preliminary_result']) "
        "->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object"
        "('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['pr"
        "eliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['preliminary_result']['original_timezon"
        "e'], 'effective_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['preliminary_result']['effective_at'], 'received_at', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['preliminary_result']['received_at'], '"
        "actor_id', shared_enterprise_verification_run_versions.run_snapshot['prelimi"
        "nary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterpri"
        "se_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at'"
        ") IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', s"
        "hared_enterprise_verification_run_versions.run_snapshot['final_result']['occ"
        "urred_at'], 'original_timezone', shared_enterprise_verification_run_versions"
        ".run_snapshot['final_result']['original_timezone'], 'effective_at', shared_e"
        "nterprise_verification_run_versions.run_snapshot['final_result']['effective_"
        "at'], 'received_at', shared_enterprise_verification_run_versions.run_snapsho"
        "t['final_result']['received_at'], 'actor_id', shared_enterprise_verification"
        "_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_build"
        "_object('record_kind', 'test_result_action', 'operation', shared_enterprise_"
        "test_result_actions.operation, 'actor_id', shared_enterprise_test_result_act"
        "ions.actor_id, 'run_version_id', shared_enterprise_verification_run_versions"
        ".id, 'run_revision', shared_enterprise_verification_run_versions.revision), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', enterp"
        "rise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads_te"
        "st_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expecte"
        "d_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements"
        '(shared_enterprise_test_result_actions.required_source_read_set) AS enterpri'
        "se_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_test_result_actions.visibility != "
        "'category' OR coalesce(shared_enterprise_projects.visibility != 'category', "
        "false) OR coalesce(shared_enterprise_products.visibility != 'category', fals"
        'e) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_test_r'
        'esult_actions.required_source_read_set) AS enterprise_reads_test_run(value) '
        'JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON enterprise_autho'
        'ritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_test_resul'
        't_actions.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.'
        "source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.private)) OR s'
        "hared_enterprise_verification_run_versions.visibility != 'category' OR share"
        "d_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_test_result_actions.required_sou'
        'rce_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritat'
        'ive_artifacts_b8475898ff5f3dcb ON enterprise_authoritative_artifacts_b847589'
        '8ff5f3dcb.tenant_id = shared_enterprise_test_result_actions.tenant_id AND en'
        'terprise_authoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterpri'
        "se_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_autho"
        'ritative_artifacts_b8475898ff5f3dcb.customer_original) AS customer_original,'
        ' shared_enterprise_verification_current_runs.run_version_id = shared_enterpr'
        'ise_test_result_actions.next_run_version_id AS is_current, shared_enterprise'
        '_test_result_actions.created_at AS created_at, CAST(NULL AS UUID) AS origina'
        'l_id, shared_enterprise_test_result_actions.run_id AS object_id, (SELECT coa'
        'lesce(array_agg(enterprise_authoritative_artifacts_b8475898ff5f3dcb.original'
        '_id), ARRAY[]::UUID[]) AS coalesce_6 \nFROM jsonb_array_elements(shared_ente'
        'rprise_test_result_actions.required_source_read_set) AS enterprise_reads_tes'
        't_run(value) JOIN enterprise_authoritative_artifacts_b8475898ff5f3dcb ON ent'
        'erprise_authoritative_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterpri'
        'se_test_result_actions.tenant_id AND enterprise_authoritative_artifacts_b847'
        "5898ff5f3dcb.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact"
        "_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b8475898ff5f3dcb.o"
        'riginal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM '
        'jsonb_array_elements(shared_enterprise_test_result_actions.required_source_r'
        'ead_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative_a'
        'rtifacts_b8475898ff5f3dcb ON enterprise_authoritative_artifacts_b8475898ff5f'
        '3dcb.tenant_id = shared_enterprise_test_result_actions.tenant_id AND enterpr'
        'ise_authoritative_artifacts_b8475898ff5f3dcb.source_id = CAST((enterprise_re'
        "ads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritat"
        'ive_artifacts_b8475898ff5f3dcb.source_revision != CAST((enterprise_reads_tes'
        "t_run.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE"
        " 'current' END AS read_basis_status \nFROM shared_enterprise_test_result_act"
        'ions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id'
        ' = shared_enterprise_test_result_actions.tenant_id AND shared_enterprise_pro'
        'jects.product_id = shared_enterprise_test_result_actions.product_id AND shar'
        'ed_enterprise_projects.id = shared_enterprise_test_result_actions.project_id'
        ' AND shared_enterprise_projects.category_id = shared_enterprise_test_result_'
        'actions.category_id JOIN shared_enterprise_products ON shared_enterprise_pro'
        'ducts.tenant_id = shared_enterprise_test_result_actions.tenant_id AND shared'
        '_enterprise_products.id = shared_enterprise_test_result_actions.product_id A'
        'ND shared_enterprise_products.category_id = shared_enterprise_test_result_ac'
        'tions.category_id JOIN shared_enterprise_verification_run_versions ON shared'
        '_enterprise_verification_run_versions.tenant_id = shared_enterprise_test_res'
        'ult_actions.tenant_id AND shared_enterprise_verification_run_versions.catego'
        'ry_id = shared_enterprise_test_result_actions.category_id AND shared_enterpr'
        'ise_verification_run_versions.product_id = shared_enterprise_test_result_act'
        'ions.product_id AND shared_enterprise_verification_run_versions.project_id ='
        ' shared_enterprise_test_result_actions.project_id AND shared_enterprise_veri'
        'fication_run_versions.build_id = shared_enterprise_test_result_actions.build'
        '_id AND shared_enterprise_verification_run_versions.run_id = shared_enterpri'
        'se_test_result_actions.run_id AND shared_enterprise_verification_run_version'
        's.id = shared_enterprise_test_result_actions.next_run_version_id AND shared_'
        'enterprise_verification_run_versions.revision = shared_enterprise_test_resul'
        't_actions.next_run_revision JOIN shared_enterprise_builds ON shared_enterpri'
        'se_builds.tenant_id = shared_enterprise_test_result_actions.tenant_id AND sh'
        'ared_enterprise_builds.category_id = shared_enterprise_test_result_actions.c'
        'ategory_id AND shared_enterprise_builds.product_id = shared_enterprise_test_'
        'result_actions.product_id AND shared_enterprise_builds.project_id = shared_e'
        'nterprise_test_result_actions.project_id AND shared_enterprise_builds.id = s'
        'hared_enterprise_test_result_actions.build_id AND shared_enterprise_builds.r'
        'evision = shared_enterprise_verification_run_versions.build_revision JOIN sh'
        'ared_enterprise_verification_current_runs ON shared_enterprise_verification_'
        'current_runs.tenant_id = shared_enterprise_test_result_actions.tenant_id AND'
        ' shared_enterprise_verification_current_runs.product_id = shared_enterprise_'
        'test_result_actions.product_id AND shared_enterprise_verification_current_ru'
        'ns.run_id = shared_enterprise_test_result_actions.run_id \nWHERE shared_ente'
        "rprise_test_result_actions.tenant_id = CAST(nullif(current_setting('pdos.ten"
        "ant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_el"
        'ements(shared_enterprise_test_result_actions.required_source_read_set) AS en'
        'terprise_reads_test_run(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterpri'
        'se_authoritative_artifacts_b8475898ff5f3dcb \nWHERE enterprise_authoritative'
        '_artifacts_b8475898ff5f3dcb.tenant_id = shared_enterprise_test_result_action'
        's.tenant_id AND enterprise_authoritative_artifacts_b8475898ff5f3dcb.source_i'
        "d = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID))))))\n"
        ' SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_b8475898ff5'
        'f3dcb \nWHERE authoritative_enterprise_sources_b8475898ff5f3dcb.tenant_id = '
        't AND authoritative_enterprise_sources_b8475898ff5f3dcb.category_id = c AND '
        'CAST(authoritative_enterprise_sources_b8475898ff5f3dcb.source_id AS TEXT) = '
        "expected->>'source_id' AND CAST(authoritative_enterprise_sources_b8475898ff5"
        "f3dcb.source_revision AS TEXT) = expected->>'source_revision' AND authoritat"
        "ive_enterprise_sources_b8475898ff5f3dcb.content_hash = expected->>'content_h"
        "ash') AS anon_1 INTO visible;\n WHEN 'field_feedback' THEN\n  WITH enterpris"
        "e_authoritative_artifacts_83b71844b30b68bc AS \n(SELECT 'artifact' AS source"
        '_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS ten'
        'ant_id, artifact_versions.category_id AS category_id, artifact_versions.prod'
        'uct_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) A'
        'S proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.rev'
        'ision AS source_revision, artifact_versions.title AS title, artifact_version'
        's.content_hash AS content_hash, artifact_versions.content AS body, CAST(NULL'
        " AS JSONB) AS structured, 'untrusted' AS nature, artifact_versions.visibilit"
        "y != 'category' OR coalesce(products.visibility != 'category', false) OR coa"
        "lesce(uploaded_originals.visibility != 'category', false) AS private, artifa"
        'ct_versions.original_id IS NOT NULL AS customer_original, true AS is_current'
        ', artifact_versions.created_at AS created_at, artifact_versions.original_id '
        'AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versi'
        'ons.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE '
        "ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM a"
        'rtifact_versions LEFT OUTER JOIN products ON products.tenant_id = artifact_v'
        'ersions.tenant_id AND products.id = artifact_versions.product_id LEFT OUTER '
        'JOIN uploaded_originals ON uploaded_originals.tenant_id = artifact_versions.'
        'tenant_id AND uploaded_originals.id = artifact_versions.original_id AND uplo'
        'aded_originals.category_id = artifact_versions.category_id AND uploaded_orig'
        'inals.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTE'
        'R JOIN original_security ON original_security.tenant_id = uploaded_originals'
        '.tenant_id AND original_security.original_id = uploaded_originals.id \nWHERE'
        " artifact_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id',"
        " true), '') AS UUID) AND artifact_versions.status = 'active' AND artifact_ve"
        'rsions.category_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR '
        'products.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploa'
        "ded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND up"
        "loaded_originals.scan_status = 'clean' AND original_security.source_state = "
        "'active' AND original_security.disposition = 'active' AND original_security."
        'current_request_id IS NOT NULL)), \nshared_enterprise_field_feedback_version'
        's AS MATERIALIZED \n(SELECT field_feedback_versions.feedback_id AS feedback_'
        'id, field_feedback_versions.previous_id AS previous_id, field_feedback_versi'
        'ons.previous_revision AS previous_revision, field_feedback_versions.revision'
        ' AS revision, field_feedback_versions.writer_id AS writer_id, field_feedback'
        '_versions.actor_id AS actor_id, field_feedback_versions.requester_id AS requ'
        'ester_id, field_feedback_versions.operation AS operation, field_feedback_ver'
        'sions.command_id AS command_id, field_feedback_versions.command AS command, '
        'field_feedback_versions.sources AS sources, field_feedback_versions.reads AS'
        ' reads, field_feedback_versions.source_basis AS source_basis, field_feedback'
        '_versions.body AS body, field_feedback_versions.body_sha256 AS body_sha256, '
        'field_feedback_versions.intent_digest AS intent_digest, field_feedback_versi'
        'ons.request_digest AS request_digest, field_feedback_versions.receipt_id AS '
        'receipt_id, field_feedback_versions.confirmation_id AS confirmation_id, fiel'
        'd_feedback_versions.category_id AS category_id, field_feedback_versions.prod'
        'uct_id AS product_id, field_feedback_versions.project_id AS project_id, fiel'
        'd_feedback_versions.owner_id AS owner_id, field_feedback_versions.visibility'
        ' AS visibility, field_feedback_versions.id AS id, field_feedback_versions.te'
        'nant_id AS tenant_id, field_feedback_versions.created_at AS created_at \nFRO'
        'M field_feedback_versions \nWHERE field_feedback_versions.tenant_id = CAST(n'
        "ullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enter"
        'prise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, '
        'projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS pu'
        'rpose, projects.scope AS scope, projects.visibility AS visibility, projects.'
        'status AS status, projects.revision AS revision, projects.current_plan_id AS'
        ' current_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id'
        ' AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id'
        ', projects.tenant_id AS tenant_id, projects.created_at AS created_at, projec'
        'ts.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = C'
        "AST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_"
        'enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, product'
        's.purpose AS purpose, products.revision AS revision, products.lifecycle_epoc'
        'h AS lifecycle_epoch, products.status AS status, products.owner_id AS owner_'
        'id, products.parent_product_id AS parent_product_id, products.category_id AS'
        ' category_id, products.visibility AS visibility, products.target_price AS ta'
        'rget_price, products.target_price_currency AS target_price_currency, product'
        's.target_price_basis AS target_price_basis, products.target_price_includes_t'
        'ax AS target_price_includes_tax, products.target_price_as_of AS target_price'
        '_as_of, products.id AS id, products.tenant_id AS tenant_id, products.created'
        '_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_f"
        'ield_feedback_currents AS MATERIALIZED \n(SELECT field_feedback_currents.fee'
        'dback_id AS feedback_id, field_feedback_currents.version_id AS version_id, f'
        'ield_feedback_currents.revision AS revision, field_feedback_currents.categor'
        'y_id AS category_id, field_feedback_currents.product_id AS product_id, field'
        '_feedback_currents.project_id AS project_id, field_feedback_currents.owner_i'
        'd AS owner_id, field_feedback_currents.visibility AS visibility, field_feedb'
        'ack_currents.id AS id, field_feedback_currents.tenant_id AS tenant_id, field'
        '_feedback_currents.created_at AS created_at \nFROM field_feedback_currents '
        "\nWHERE field_feedback_currents.tenant_id = CAST(nullif(current_setting('pdo"
        "s.tenant_id', true), '') AS UUID)), \nshared_enterprise_field_response_recor"
        'ds AS MATERIALIZED \n(SELECT field_response_records.feedback_id AS feedback_'
        'id, field_response_records.feedback_version_id AS feedback_version_id, field'
        '_response_records.feedback_revision AS feedback_revision, field_response_rec'
        'ords.response_kind AS response_kind, field_response_records.revision AS revi'
        'sion, field_response_records.writer_id AS writer_id, field_response_records.'
        'actor_id AS actor_id, field_response_records.requester_id AS requester_id, f'
        'ield_response_records.operation AS operation, field_response_records.command'
        '_id AS command_id, field_response_records.command AS command, field_response'
        '_records.sources AS sources, field_response_records.reads AS reads, field_re'
        'sponse_records.source_basis AS source_basis, field_response_records.body AS '
        'body, field_response_records.body_sha256 AS body_sha256, field_response_reco'
        'rds.intent_digest AS intent_digest, field_response_records.request_digest AS'
        ' request_digest, field_response_records.receipt_id AS receipt_id, field_resp'
        'onse_records.confirmation_id AS confirmation_id, field_response_records.cate'
        'gory_id AS category_id, field_response_records.product_id AS product_id, fie'
        'ld_response_records.project_id AS project_id, field_response_records.owner_i'
        'd AS owner_id, field_response_records.visibility AS visibility, field_respon'
        'se_records.id AS id, field_response_records.tenant_id AS tenant_id, field_re'
        'sponse_records.created_at AS created_at \nFROM field_response_records \nWHER'
        "E field_response_records.tenant_id = CAST(nullif(current_setting('pdos.tenan"
        "t_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_83b71844b30b"
        "68bc AS \n(SELECT 'field_feedback' AS source_type, shared_enterprise_field_f"
        'eedback_versions.id AS source_id, shared_enterprise_field_feedback_versions.'
        'tenant_id AS tenant_id, shared_enterprise_field_feedback_versions.category_i'
        'd AS category_id, shared_enterprise_field_feedback_versions.product_id AS pr'
        'oduct_id, shared_enterprise_field_feedback_versions.project_id AS project_id'
        ', CAST(NULL AS UUID) AS proposal_id, shared_enterprise_field_feedback_versio'
        'ns.owner_id AS owner_id, shared_enterprise_field_feedback_versions.revision '
        "AS source_revision, shared_enterprise_field_feedback_versions.body ->> 'titl"
        "e' AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_field_feedback_versions.feedback_id, 'kind', 'field_fe"
        "edback', 'facts', jsonb_build_object('record_kind', 'field_feedback', 'opera"
        "tion', shared_enterprise_field_feedback_versions.operation, 'feedback_id', s"
        "hared_enterprise_field_feedback_versions.feedback_id, 'feedback_revision', s"
        "hared_enterprise_field_feedback_versions.revision, 'title', shared_enterpris"
        "e_field_feedback_versions.body['title'], 'description', shared_enterprise_fi"
        "eld_feedback_versions.body['description'], 'channel', shared_enterprise_fiel"
        "d_feedback_versions.body['channel'], 'feedback_kind', shared_enterprise_fiel"
        "d_feedback_versions.body['feedback_kind'], 'reported', shared_enterprise_fie"
        "ld_feedback_versions.body['reported'], 'received_at', shared_enterprise_fiel"
        "d_feedback_versions.body['received_at'], 'purpose', shared_enterprise_field_"
        "feedback_versions.body['purpose'], 'location', shared_enterprise_field_feedb"
        "ack_versions.body['location'], 'location_status', CASE WHEN (((shared_enterp"
        "rise_field_feedback_versions.body['location']) ->> 'state') = 'known') THEN "
        "'known' ELSE 'unknown' END, 'continuation_permission', 'not_evaluated', 'rec"
        "ord_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001"
        '\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1'
        '\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe'
        "\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002'), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_field_feedback.value['artifact_id'], 'version', "
        "enterprise_reads_field_feedback.value['expected_revision']) ORDER BY enterpr"
        "ise_reads_field_feedback.value ->> 'artifact_id', enterprise_reads_field_fee"
        "dback.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nF"
        "ROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('arti"
        "fact_id', field_basis_field_feedback_versions.value['id'], 'expected_revisio"
        "n', field_basis_field_feedback_versions.value['revision'])), jsonb_build_arr"
        'ay()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field_feed'
        "back_versions.source_basis['artifacts']) AS field_basis_field_feedback_versi"
        "ons(value))) AS enterprise_reads_field_feedback(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e'
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jso"
        "nb_build_object('object_id', shared_enterprise_field_feedback_versions.feedb"
        "ack_id, 'kind', 'field_feedback', 'facts', jsonb_build_object('record_kind',"
        " 'field_feedback', 'operation', shared_enterprise_field_feedback_versions.op"
        "eration, 'feedback_id', shared_enterprise_field_feedback_versions.feedback_i"
        "d, 'feedback_revision', shared_enterprise_field_feedback_versions.revision, "
        "'title', shared_enterprise_field_feedback_versions.body['title'], 'descripti"
        "on', shared_enterprise_field_feedback_versions.body['description'], 'channel"
        "', shared_enterprise_field_feedback_versions.body['channel'], 'feedback_kind"
        "', shared_enterprise_field_feedback_versions.body['feedback_kind'], 'reporte"
        "d', shared_enterprise_field_feedback_versions.body['reported'], 'received_at"
        "', shared_enterprise_field_feedback_versions.body['received_at'], 'purpose',"
        " shared_enterprise_field_feedback_versions.body['purpose'], 'location', shar"
        "ed_enterprise_field_feedback_versions.body['location'], 'location_status', C"
        "ASE WHEN (((shared_enterprise_field_feedback_versions.body['location']) ->> "
        "'state') = 'known') THEN 'known' ELSE 'unknown' END, 'continuation_permissio"
        "n', 'not_evaluated', 'record_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0"
        '\u7684\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b'
        '\u5ba2\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6'
        '\u653e\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd'
        "\u6216\u590d\u9a8c\u3002'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_"
        "build_object('type', 'artifact', 'id', enterprise_reads_field_feedback.value"
        "['artifact_id'], 'version', enterprise_reads_field_feedback.value['expected_"
        "revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact_id'"
        ", enterprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_buil"
        'd_array()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_'
        "agg(jsonb_build_object('artifact_id', field_basis_field_feedback_versions.va"
        "lue['id'], 'expected_revision', field_basis_field_feedback_versions.value['r"
        "evision'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements("
        "shared_enterprise_field_feedback_versions.source_basis['artifacts']) AS fiel"
        'd_basis_field_feedback_versions(value))) AS enterprise_reads_field_feedback('
        "value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_buil"
        "d_object('object_id', shared_enterprise_field_feedback_versions.feedback_id,"
        " 'kind', 'field_feedback', 'facts', jsonb_build_object('record_kind', 'field"
        "_feedback', 'operation', shared_enterprise_field_feedback_versions.operation"
        ", 'feedback_id', shared_enterprise_field_feedback_versions.feedback_id, 'fee"
        "dback_revision', shared_enterprise_field_feedback_versions.revision, 'title'"
        ", shared_enterprise_field_feedback_versions.body['title'], 'description', sh"
        "ared_enterprise_field_feedback_versions.body['description'], 'channel', shar"
        "ed_enterprise_field_feedback_versions.body['channel'], 'feedback_kind', shar"
        "ed_enterprise_field_feedback_versions.body['feedback_kind'], 'reported', sha"
        "red_enterprise_field_feedback_versions.body['reported'], 'received_at', shar"
        "ed_enterprise_field_feedback_versions.body['received_at'], 'purpose', shared"
        "_enterprise_field_feedback_versions.body['purpose'], 'location', shared_ente"
        "rprise_field_feedback_versions.body['location'], 'location_status', CASE WHE"
        "N (((shared_enterprise_field_feedback_versions.body['location']) ->> 'state'"
        ") = 'known') THEN 'known' ELSE 'unknown' END, 'continuation_permission', 'no"
        "t_evaluated', 'record_policy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684"
        '\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2'
        '\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e'
        '\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216'
        "\u590d\u9a8c\u3002'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_"
        "object('type', 'artifact', 'id', enterprise_reads_field_feedback.value['arti"
        "fact_id'], 'version', enterprise_reads_field_feedback.value['expected_revisi"
        "on']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact_id', ente"
        "rprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_build_arra"
        'y()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(js'
        "onb_build_object('artifact_id', field_basis_field_feedback_versions.value['i"
        "d'], 'expected_revision', field_basis_field_feedback_versions.value['revisio"
        "n'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared"
        "_enterprise_field_feedback_versions.source_basis['artifacts']) AS field_basi"
        's_field_feedback_versions(value))) AS enterprise_reads_field_feedback(value)'
        "), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'untrusted' AS nature, s"
        "hared_enterprise_field_feedback_versions.visibility != 'category' OR coalesc"
        "e(shared_enterprise_projects.visibility != 'category', false) OR coalesce(sh"
        "ared_enterprise_products.visibility != 'category', false) OR (EXISTS (SELECT"
        ' 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object'
        "('artifact_id', field_basis_field_feedback_versions.value['id'], 'expected_r"
        "evision', field_basis_field_feedback_versions.value['revision'])), jsonb_bui"
        'ld_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_fiel'
        "d_feedback_versions.source_basis['artifacts']) AS field_basis_field_feedback"
        '_versions(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise'
        '_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifa'
        'cts_83b71844b30b68bc.tenant_id = shared_enterprise_field_feedback_versions.t'
        'enant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id ='
        " CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nW"
        'HERE enterprise_authoritative_artifacts_83b71844b30b68bc.private)) AS privat'
        'e, (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg('
        "jsonb_build_object('artifact_id', field_basis_field_feedback_versions.value["
        "'id'], 'expected_revision', field_basis_field_feedback_versions.value['revis"
        "ion'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shar"
        "ed_enterprise_field_feedback_versions.source_basis['artifacts']) AS field_ba"
        'sis_field_feedback_versions(value))) AS enterprise_reads_field_feedback(valu'
        'e) JOIN enterprise_authoritative_artifacts_83b71844b30b68bc ON enterprise_au'
        'thoritative_artifacts_83b71844b30b68bc.tenant_id = shared_enterprise_field_f'
        'eedback_versions.tenant_id AND enterprise_authoritative_artifacts_83b71844b3'
        "0b68bc.source_id = CAST((enterprise_reads_field_feedback.value ->> 'artifact"
        "_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.c"
        "ustomer_original)) OR (shared_enterprise_field_feedback_versions.body ->> 'c"
        "hannel') = 'customer' AS customer_original, shared_enterprise_field_feedback"
        '_currents.version_id = shared_enterprise_field_feedback_versions.id AS is_cu'
        'rrent, shared_enterprise_field_feedback_versions.created_at AS created_at, C'
        'AST(NULL AS UUID) AS original_id, shared_enterprise_field_feedback_versions.'
        'feedback_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritativ'
        'e_artifacts_83b71844b30b68bc.original_id), ARRAY[]::UUID[]) AS coalesce_3 \n'
        "FROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('art"
        "ifact_id', field_basis_field_feedback_versions.value['id'], 'expected_revisi"
        "on', field_basis_field_feedback_versions.value['revision'])), jsonb_build_ar"
        'ray()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field_fee'
        "dback_versions.source_basis['artifacts']) AS field_basis_field_feedback_vers"
        'ions(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise_auth'
        'oritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifacts_8'
        '3b71844b30b68bc.tenant_id = shared_enterprise_field_feedback_versions.tenant'
        '_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id = CAST'
        "((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nWHERE "
        'enterprise_authoritative_artifacts_83b71844b30b68bc.original_id IS NOT NULL)'
        ' AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements((S'
        "ELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field"
        "_feedback_versions.value['id'], 'expected_revision', field_basis_field_feedb"
        "ack_versions.value['revision'])), jsonb_build_array()) AS coalesce_2 \nFROM "
        'jsonb_array_elements(shared_enterprise_field_feedback_versions.source_basis['
        "'artifacts']) AS field_basis_field_feedback_versions(value))) AS enterprise_"
        'reads_field_feedback(value) JOIN enterprise_authoritative_artifacts_83b71844'
        'b30b68bc ON enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = '
        'shared_enterprise_field_feedback_versions.tenant_id AND enterprise_authorita'
        'tive_artifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_fee'
        "dback.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_art"
        'ifacts_83b71844b30b68bc.source_revision != CAST((enterprise_reads_field_feed'
        "back.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE "
        "'current' END AS read_basis_status \nFROM shared_enterprise_field_feedback_v"
        'ersions LEFT OUTER JOIN shared_enterprise_projects ON shared_enterprise_proj'
        'ects.tenant_id = shared_enterprise_field_feedback_versions.tenant_id AND sha'
        'red_enterprise_projects.product_id = shared_enterprise_field_feedback_versio'
        'ns.product_id AND shared_enterprise_projects.id = shared_enterprise_field_fe'
        'edback_versions.project_id AND shared_enterprise_projects.category_id = shar'
        'ed_enterprise_field_feedback_versions.category_id LEFT OUTER JOIN shared_ent'
        'erprise_products ON shared_enterprise_products.tenant_id = shared_enterprise'
        '_field_feedback_versions.tenant_id AND shared_enterprise_products.id = share'
        'd_enterprise_field_feedback_versions.product_id AND shared_enterprise_produc'
        'ts.category_id = shared_enterprise_field_feedback_versions.category_id JOIN '
        'shared_enterprise_field_feedback_currents ON shared_enterprise_field_feedbac'
        'k_currents.tenant_id = shared_enterprise_field_feedback_versions.tenant_id A'
        'ND shared_enterprise_field_feedback_currents.category_id = shared_enterprise'
        '_field_feedback_versions.category_id AND shared_enterprise_field_feedback_cu'
        'rrents.feedback_id = shared_enterprise_field_feedback_versions.feedback_id '
        '\nWHERE shared_enterprise_field_feedback_versions.tenant_id = CAST(nullif(cu'
        "rrent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT "
        '1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('
        "'artifact_id', field_basis_field_feedback_versions.value['id'], 'expected_re"
        "vision', field_basis_field_feedback_versions.value['revision'])), jsonb_buil"
        'd_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_field'
        "_feedback_versions.source_basis['artifacts']) AS field_basis_field_feedback_"
        'versions(value))) AS enterprise_reads_field_feedback(value) \nWHERE NOT (EXI'
        'STS (SELECT 1 \nFROM enterprise_authoritative_artifacts_83b71844b30b68bc \nW'
        'HERE enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = shared_'
        'enterprise_field_feedback_versions.tenant_id AND enterprise_authoritative_ar'
        'tifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_feedback.v'
        "alue ->> 'artifact_id') AS UUID))))) AND (shared_enterprise_field_feedback_v"
        'ersions.product_id IS NULL OR shared_enterprise_products.id IS NOT NULL) AND'
        ' (shared_enterprise_field_feedback_versions.project_id IS NULL OR shared_ent'
        "erprise_projects.id IS NOT NULL) UNION ALL SELECT 'field_feedback' AS source"
        '_type, shared_enterprise_field_response_records.id AS source_id, shared_ente'
        'rprise_field_response_records.tenant_id AS tenant_id, shared_enterprise_fiel'
        'd_response_records.category_id AS category_id, shared_enterprise_field_respo'
        'nse_records.product_id AS product_id, shared_enterprise_field_response_recor'
        'ds.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enter'
        'prise_field_response_records.owner_id AS owner_id, shared_enterprise_field_r'
        "esponse_records.revision AS source_revision, '\u73b0\u573a\u53cd\u9988\u8ddf"
        "\u8fdb \xb7 ' || CAST(shared_enterprise_field_response_records.response_kind"
        " AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('o"
        "bject_id', shared_enterprise_field_response_records.feedback_id, 'kind', 'fi"
        "eld_feedback', 'facts', jsonb_build_object('record_kind', 'field_response', "
        "'operation', shared_enterprise_field_response_records.operation, 'feedback_i"
        "d', shared_enterprise_field_response_records.feedback_id, 'feedback_version_"
        "id', shared_enterprise_field_response_records.feedback_version_id, 'feedback"
        "_revision', shared_enterprise_field_response_records.feedback_revision, 'res"
        "ponse_kind', shared_enterprise_field_response_records.response_kind, 'descri"
        "ption', shared_enterprise_field_response_records.body['description'], 'occur"
        "red_at', shared_enterprise_field_response_records.body['occurred_at'], 'resu"
        "lt_receipts', shared_enterprise_field_response_records.body['result_receipts"
        "'], 'actor_id', shared_enterprise_field_response_records.actor_id, 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a"
        '\u4f4d\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e'
        '\u627f\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5'
        "\u7ed3\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'contin"
        "uation_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_"
        "agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_field_feed"
        "back.value['artifact_id'], 'version', enterprise_reads_field_feedback.value["
        "'expected_revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'ar"
        "tifact_id', enterprise_reads_field_feedback.value ->> 'expected_revision'), "
        'jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements((SELECT coale'
        "sce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field_response_r"
        "ecords.value['id'], 'expected_revision', field_basis_field_response_records."
        "value['revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_e"
        "lements(shared_enterprise_field_response_records.source_basis['artifacts']) "
        'AS field_basis_field_response_records(value))) AS enterprise_reads_field_fee'
        "dback(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') "
        "AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise"
        "_field_response_records.feedback_id, 'kind', 'field_feedback', 'facts', json"
        "b_build_object('record_kind', 'field_response', 'operation', shared_enterpri"
        "se_field_response_records.operation, 'feedback_id', shared_enterprise_field_"
        "response_records.feedback_id, 'feedback_version_id', shared_enterprise_field"
        "_response_records.feedback_version_id, 'feedback_revision', shared_enterpris"
        "e_field_response_records.feedback_revision, 'response_kind', shared_enterpri"
        "se_field_response_records.response_kind, 'description', shared_enterprise_fi"
        "eld_response_records.body['description'], 'occurred_at', shared_enterprise_f"
        "ield_response_records.body['occurred_at'], 'result_receipts', shared_enterpr"
        "ise_field_response_records.body['result_receipts'], 'actor_id', shared_enter"
        "prise_field_response_records.actor_id, 'record_policy', '\u4ec5\u8868\u793a"
        '\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a\u4f4d\u6216\u72ec\u7acb'
        '\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e\u627f\u8ba4\u58f0\u660e'
        '\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5\u7ed3\u679c\u4e0d\u4ee3'
        "\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'continuation_permission', 'not"
        "_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('"
        "type', 'artifact', 'id', enterprise_reads_field_feedback.value['artifact_id'"
        "], 'version', enterprise_reads_field_feedback.value['expected_revision']) OR"
        "DER BY enterprise_reads_field_feedback.value ->> 'artifact_id', enterprise_r"
        "eads_field_feedback.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_4 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_buil'
        "d_object('artifact_id', field_basis_field_response_records.value['id'], 'exp"
        "ected_revision', field_basis_field_response_records.value['revision'])), jso"
        'nb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterpris'
        "e_field_response_records.source_basis['artifacts']) AS field_basis_field_res"
        "ponse_records(value))) AS enterprise_reads_field_feedback(value)), 'record_p"
        "olicy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_field_response_records.feedback_id, 'kind', 'field_fee"
        "dback', 'facts', jsonb_build_object('record_kind', 'field_response', 'operat"
        "ion', shared_enterprise_field_response_records.operation, 'feedback_id', sha"
        "red_enterprise_field_response_records.feedback_id, 'feedback_version_id', sh"
        "ared_enterprise_field_response_records.feedback_version_id, 'feedback_revisi"
        "on', shared_enterprise_field_response_records.feedback_revision, 'response_k"
        "ind', shared_enterprise_field_response_records.response_kind, 'description',"
        " shared_enterprise_field_response_records.body['description'], 'occurred_at'"
        ", shared_enterprise_field_response_records.body['occurred_at'], 'result_rece"
        "ipts', shared_enterprise_field_response_records.body['result_receipts'], 'ac"
        "tor_id', shared_enterprise_field_response_records.actor_id, 'record_policy',"
        " '\u4ec5\u8868\u793a\u5df2\u767b\u8bb0\u7684\u6765\u6e90\u3001\u5b9a\u4f4d"
        '\u6216\u72ec\u7acb\u8ddf\u8fdb\uff1b\u5ba2\u6237\u610f\u89c1\u4e0e\u627f'
        '\u8ba4\u58f0\u660e\u4e0d\u6279\u51c6\u653e\u884c\uff0c\u94fe\u63a5\u7ed3'
        "\u679c\u4e0d\u4ee3\u66ff\u5b9e\u65bd\u6216\u590d\u9a8c\u3002', 'continuation"
        "_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_field_feedback.v"
        "alue['artifact_id'], 'version', enterprise_reads_field_feedback.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_field_feedback.value ->> 'artifact"
        "_id', enterprise_reads_field_feedback.value ->> 'expected_revision'), jsonb_"
        'build_array()) AS coalesce_4 \nFROM jsonb_array_elements((SELECT coalesce(js'
        "onb_agg(jsonb_build_object('artifact_id', field_basis_field_response_records"
        ".value['id'], 'expected_revision', field_basis_field_response_records.value["
        "'revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_element"
        "s(shared_enterprise_field_response_records.source_basis['artifacts']) AS fie"
        'ld_basis_field_response_records(value))) AS enterprise_reads_field_feedback('
        "value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS na"
        "ture, shared_enterprise_field_response_records.visibility != 'category' OR c"
        "oalesce(shared_enterprise_projects.visibility != 'category', false) OR coale"
        "sce(shared_enterprise_products.visibility != 'category', false) OR (EXISTS ("
        'SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_'
        "object('artifact_id', field_basis_field_response_records.value['id'], 'expec"
        "ted_revision', field_basis_field_response_records.value['revision'])), jsonb"
        '_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_'
        "field_response_records.source_basis['artifacts']) AS field_basis_field_respo"
        'nse_records(value))) AS enterprise_reads_field_feedback(value) JOIN enterpri'
        'se_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_arti'
        'facts_83b71844b30b68bc.tenant_id = shared_enterprise_field_response_records.'
        'tenant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id '
        "= CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_83b71844b30b68bc.private)) OR share'
        "d_enterprise_field_feedback_versions.visibility != 'category' AS private, (E"
        'XISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb'
        "_build_object('artifact_id', field_basis_field_response_records.value['id'],"
        " 'expected_revision', field_basis_field_response_records.value['revision']))"
        ', jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ente'
        "rprise_field_response_records.source_basis['artifacts']) AS field_basis_fiel"
        'd_response_records(value))) AS enterprise_reads_field_feedback(value) JOIN e'
        'nterprise_authoritative_artifacts_83b71844b30b68bc ON enterprise_authoritati'
        've_artifacts_83b71844b30b68bc.tenant_id = shared_enterprise_field_response_r'
        'ecords.tenant_id AND enterprise_authoritative_artifacts_83b71844b30b68bc.sou'
        "rce_id = CAST((enterprise_reads_field_feedback.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.customer_or'
        "iginal)) OR (shared_enterprise_field_feedback_versions.body ->> 'channel') ="
        " 'customer' AS customer_original, shared_enterprise_field_feedback_currents."
        'version_id = shared_enterprise_field_response_records.feedback_version_id AS'
        ' is_current, shared_enterprise_field_response_records.created_at AS created_'
        'at, CAST(NULL AS UUID) AS original_id, shared_enterprise_field_response_reco'
        'rds.feedback_id AS object_id, (SELECT coalesce(array_agg(enterprise_authorit'
        'ative_artifacts_83b71844b30b68bc.original_id), ARRAY[]::UUID[]) AS coalesce_'
        '6 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb_build_object('
        "'artifact_id', field_basis_field_response_records.value['id'], 'expected_rev"
        "ision', field_basis_field_response_records.value['revision'])), jsonb_build_"
        'array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_field_r'
        "esponse_records.source_basis['artifacts']) AS field_basis_field_response_rec"
        'ords(value))) AS enterprise_reads_field_feedback(value) JOIN enterprise_auth'
        'oritative_artifacts_83b71844b30b68bc ON enterprise_authoritative_artifacts_8'
        '3b71844b30b68bc.tenant_id = shared_enterprise_field_response_records.tenant_'
        'id AND enterprise_authoritative_artifacts_83b71844b30b68bc.source_id = CAST('
        "(enterprise_reads_field_feedback.value ->> 'artifact_id') AS UUID) \nWHERE e"
        'nterprise_authoritative_artifacts_83b71844b30b68bc.original_id IS NOT NULL) '
        'AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SE'
        "LECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_field_"
        "response_records.value['id'], 'expected_revision', field_basis_field_respons"
        "e_records.value['revision'])), jsonb_build_array()) AS coalesce_5 \nFROM jso"
        "nb_array_elements(shared_enterprise_field_response_records.source_basis['art"
        "ifacts']) AS field_basis_field_response_records(value))) AS enterprise_reads"
        '_field_feedback(value) JOIN enterprise_authoritative_artifacts_83b71844b30b6'
        '8bc ON enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id = share'
        'd_enterprise_field_response_records.tenant_id AND enterprise_authoritative_a'
        'rtifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_feedback.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        '_83b71844b30b68bc.source_revision != CAST((enterprise_reads_field_feedback.v'
        "alue ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'curre"
        "nt' END AS read_basis_status \nFROM shared_enterprise_field_response_records"
        ' LEFT OUTER JOIN shared_enterprise_projects ON shared_enterprise_projects.te'
        'nant_id = shared_enterprise_field_response_records.tenant_id AND shared_ente'
        'rprise_projects.product_id = shared_enterprise_field_response_records.produc'
        't_id AND shared_enterprise_projects.id = shared_enterprise_field_response_re'
        'cords.project_id AND shared_enterprise_projects.category_id = shared_enterpr'
        'ise_field_response_records.category_id LEFT OUTER JOIN shared_enterprise_pro'
        'ducts ON shared_enterprise_products.tenant_id = shared_enterprise_field_resp'
        'onse_records.tenant_id AND shared_enterprise_products.id = shared_enterprise'
        '_field_response_records.product_id AND shared_enterprise_products.category_i'
        'd = shared_enterprise_field_response_records.category_id JOIN shared_enterpr'
        'ise_field_feedback_versions ON shared_enterprise_field_feedback_versions.ten'
        'ant_id = shared_enterprise_field_response_records.tenant_id AND shared_enter'
        'prise_field_feedback_versions.category_id = shared_enterprise_field_response'
        '_records.category_id AND shared_enterprise_field_feedback_versions.product_i'
        'd IS NOT DISTINCT FROM shared_enterprise_field_response_records.product_id A'
        'ND shared_enterprise_field_feedback_versions.project_id IS NOT DISTINCT FROM'
        ' shared_enterprise_field_response_records.project_id AND shared_enterprise_f'
        'ield_feedback_versions.feedback_id = shared_enterprise_field_response_record'
        's.feedback_id AND shared_enterprise_field_feedback_versions.id = shared_ente'
        'rprise_field_response_records.feedback_version_id AND shared_enterprise_fiel'
        'd_feedback_versions.revision = shared_enterprise_field_response_records.feed'
        'back_revision JOIN shared_enterprise_field_feedback_currents ON shared_enter'
        'prise_field_feedback_currents.tenant_id = shared_enterprise_field_response_r'
        'ecords.tenant_id AND shared_enterprise_field_feedback_currents.category_id ='
        ' shared_enterprise_field_response_records.category_id AND shared_enterprise_'
        'field_feedback_currents.feedback_id = shared_enterprise_field_response_recor'
        'ds.feedback_id \nWHERE shared_enterprise_field_response_records.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (E"
        'XISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT coalesce(jsonb_agg(jsonb'
        "_build_object('artifact_id', field_basis_field_response_records.value['id'],"
        " 'expected_revision', field_basis_field_response_records.value['revision']))"
        ', jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ente'
        "rprise_field_response_records.source_basis['artifacts']) AS field_basis_fiel"
        'd_response_records(value))) AS enterprise_reads_field_feedback(value) \nWHER'
        'E NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_83b71844b3'
        '0b68bc \nWHERE enterprise_authoritative_artifacts_83b71844b30b68bc.tenant_id'
        ' = shared_enterprise_field_response_records.tenant_id AND enterprise_authori'
        'tative_artifacts_83b71844b30b68bc.source_id = CAST((enterprise_reads_field_f'
        "eedback.value ->> 'artifact_id') AS UUID))))) AND (shared_enterprise_field_r"
        'esponse_records.product_id IS NULL OR shared_enterprise_products.id IS NOT N'
        'ULL) AND (shared_enterprise_field_response_records.project_id IS NULL OR sha'
        'red_enterprise_projects.id IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM au'
        'thoritative_enterprise_sources_83b71844b30b68bc \nWHERE authoritative_enterp'
        'rise_sources_83b71844b30b68bc.tenant_id = t AND authoritative_enterprise_sou'
        'rces_83b71844b30b68bc.category_id = c AND CAST(authoritative_enterprise_sour'
        "ces_83b71844b30b68bc.source_id AS TEXT) = expected->>'source_id' AND CAST(au"
        'thoritative_enterprise_sources_83b71844b30b68bc.source_revision AS TEXT) = e'
        "xpected->>'source_revision' AND authoritative_enterprise_sources_83b71844b30"
        "b68bc.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WH"
        "EN 'project_status' THEN\n  WITH enterprise_authoritative_artifacts_5974f9e7"
        "2e6d02d1 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sou"
        'rce_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category'
        '_id AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS'
        ' UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.o'
        'wner_id AS owner_id, artifact_versions.revision AS source_revision, artifact'
        '_versions.title AS title, artifact_versions.content_hash AS content_hash, ar'
        "tifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrust"
        "ed' AS nature, artifact_versions.visibility != 'category' OR coalesce(produc"
        "ts.visibility != 'category', false) OR coalesce(uploaded_originals.visibilit"
        "y != 'category', false) AS private, artifact_versions.original_id IS NOT NUL"
        'L AS customer_original, true AS is_current, artifact_versions.created_at AS '
        'created_at, artifact_versions.original_id AS original_id, artifact_versions.'
        'id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN '
        'ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_id'
        "s, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN p"
        'roducts ON products.tenant_id = artifact_versions.tenant_id AND products.id '
        '= artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploade'
        'd_originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.i'
        'd = artifact_versions.original_id AND uploaded_originals.category_id = artif'
        'act_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT F'
        'ROM artifact_versions.product_id LEFT OUTER JOIN original_security ON origin'
        'al_security.tenant_id = uploaded_originals.tenant_id AND original_security.o'
        'riginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAS'
        "T(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_"
        "versions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND"
        ' (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (arti'
        'fact_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND u'
        "ploaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'cl"
        "ean' AND original_security.source_state = 'active' AND original_security.dis"
        "position = 'active' AND original_security.current_request_id IS NOT NULL)), "
        '\nshared_enterprise_project_status_updates AS MATERIALIZED \n(SELECT project'
        '_status_updates.fact_summary AS fact_summary, project_status_updates.next_st'
        'eps AS next_steps, project_status_updates.task_refs AS task_refs, project_st'
        'atus_updates.revision AS revision, project_status_updates.writer_id AS write'
        'r_id, project_status_updates.actor_id AS actor_id, project_status_updates.re'
        'quester_id AS requester_id, project_status_updates.operation AS operation, p'
        'roject_status_updates.command_id AS command_id, project_status_updates.comma'
        'nd AS command, project_status_updates.sources AS sources, project_status_upd'
        'ates.reads AS reads, project_status_updates.source_basis AS source_basis, pr'
        'oject_status_updates.body AS body, project_status_updates.body_sha256 AS bod'
        'y_sha256, project_status_updates.intent_digest AS intent_digest, project_sta'
        'tus_updates.request_digest AS request_digest, project_status_updates.receipt'
        '_id AS receipt_id, project_status_updates.confirmation_id AS confirmation_id'
        ', project_status_updates.product_id AS product_id, project_status_updates.pr'
        'oject_id AS project_id, project_status_updates.owner_id AS owner_id, project'
        '_status_updates.visibility AS visibility, project_status_updates.id AS id, p'
        'roject_status_updates.tenant_id AS tenant_id, project_status_updates.created'
        '_at AS created_at, project_status_updates.category_id AS category_id \nFROM '
        'project_status_updates \nWHERE project_status_updates.tenant_id = CAST(nulli'
        "f(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpris"
        'e_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, proj'
        'ects.owner_id AS owner_id, projects.name AS name, projects.purpose AS purpos'
        'e, projects.scope AS scope, projects.visibility AS visibility, projects.stat'
        'us AS status, projects.revision AS revision, projects.current_plan_id AS cur'
        'rent_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS '
        'trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, pr'
        'ojects.tenant_id AS tenant_id, projects.created_at AS created_at, projects.c'
        'ategory_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_ente"
        'rprise_products AS MATERIALIZED \n(SELECT products.name AS name, products.pu'
        'rpose AS purpose, products.revision AS revision, products.lifecycle_epoch AS'
        ' lifecycle_epoch, products.status AS status, products.owner_id AS owner_id, '
        'products.parent_product_id AS parent_product_id, products.category_id AS cat'
        'egory_id, products.visibility AS visibility, products.target_price AS target'
        '_price, products.target_price_currency AS target_price_currency, products.ta'
        'rget_price_basis AS target_price_basis, products.target_price_includes_tax A'
        'S target_price_includes_tax, products.target_price_as_of AS target_price_as_'
        'of, products.id AS id, products.tenant_id AS tenant_id, products.created_at '
        'AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(curre'
        "nt_setting('pdos.tenant_id', true), '') AS UUID)), \nauthoritative_enterpris"
        "e_sources_5974f9e72e6d02d1 AS \n(SELECT 'project_status' AS source_type, sha"
        'red_enterprise_project_status_updates.id AS source_id, shared_enterprise_pro'
        'ject_status_updates.tenant_id AS tenant_id, shared_enterprise_project_status'
        '_updates.category_id AS category_id, shared_enterprise_project_status_update'
        's.product_id AS product_id, shared_enterprise_project_status_updates.project'
        '_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_proj'
        'ect_status_updates.owner_id AS owner_id, shared_enterprise_project_status_up'
        "dates.revision AS source_revision, '\u9879\u76ee\u5177\u540d\u72b6\u6001 "
        "\xb7 ' || shared_enterprise_project_status_updates.fact_summary AS title, en"
        "code(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_ente"
        "rprise_project_status_updates.project_id, 'kind', 'project_status', 'facts',"
        " jsonb_build_object('record_kind', 'named_project_status', 'operation', shar"
        "ed_enterprise_project_status_updates.operation, 'fact_summary', shared_enter"
        "prise_project_status_updates.fact_summary, 'next_steps', shared_enterprise_p"
        "roject_status_updates.next_steps, 'task_refs', shared_enterprise_project_sta"
        "tus_updates.task_refs, 'recorded_by', shared_enterprise_project_status_updat"
        "es.actor_id, 'recorded_at', shared_enterprise_project_status_updates.created"
        "_at, 'continuation_permission', 'not_evaluated'), 'source_refs', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_read"
        "s_project_status.value['artifact_id'], 'version', enterprise_reads_project_s"
        "tatus.value['expected_revision']) ORDER BY enterprise_reads_project_status.v"
        "alue ->> 'artifact_id', enterprise_reads_project_status.value ->> 'expected_"
        "revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(s"
        'hared_enterprise_project_status_updates.reads || (SELECT coalesce(jsonb_agg('
        "jsonb_build_object('artifact_id', field_basis_project_status_updates.value['"
        "id'], 'expected_revision', field_basis_project_status_updates.value['revisio"
        "n'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared"
        "_enterprise_project_status_updates.source_basis['artifacts']) AS field_basis"
        '_project_status_updates(value))) AS enterprise_reads_project_status(value)),'
        " 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_h"
        "ash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_project_sta"
        "tus_updates.project_id, 'kind', 'project_status', 'facts', jsonb_build_objec"
        "t('record_kind', 'named_project_status', 'operation', shared_enterprise_proj"
        "ect_status_updates.operation, 'fact_summary', shared_enterprise_project_stat"
        "us_updates.fact_summary, 'next_steps', shared_enterprise_project_status_upda"
        "tes.next_steps, 'task_refs', shared_enterprise_project_status_updates.task_r"
        "efs, 'recorded_by', shared_enterprise_project_status_updates.actor_id, 'reco"
        "rded_at', shared_enterprise_project_status_updates.created_at, 'continuation"
        "_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_project_status.v"
        "alue['artifact_id'], 'version', enterprise_reads_project_status.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_project_status.value ->> 'artifact"
        "_id', enterprise_reads_project_status.value ->> 'expected_revision'), jsonb_"
        'build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_p'
        'roject_status_updates.reads || (SELECT coalesce(jsonb_agg(jsonb_build_object'
        "('artifact_id', field_basis_project_status_updates.value['id'], 'expected_re"
        "vision', field_basis_project_status_updates.value['revision'])), jsonb_build"
        '_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_projec'
        "t_status_updates.source_basis['artifacts']) AS field_basis_project_status_up"
        "dates(value))) AS enterprise_reads_project_status(value)), 'record_policy', "
        "'\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_project_status_updates.project_id, 'kind', 'project_status',"
        " 'facts', jsonb_build_object('record_kind', 'named_project_status', 'operati"
        "on', shared_enterprise_project_status_updates.operation, 'fact_summary', sha"
        "red_enterprise_project_status_updates.fact_summary, 'next_steps', shared_ent"
        "erprise_project_status_updates.next_steps, 'task_refs', shared_enterprise_pr"
        "oject_status_updates.task_refs, 'recorded_by', shared_enterprise_project_sta"
        "tus_updates.actor_id, 'recorded_at', shared_enterprise_project_status_update"
        "s.created_at, 'continuation_permission', 'not_evaluated'), 'source_refs', (S"
        "ELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterp"
        "rise_reads_project_status.value['artifact_id'], 'version', enterprise_reads_"
        "project_status.value['expected_revision']) ORDER BY enterprise_reads_project"
        "_status.value ->> 'artifact_id', enterprise_reads_project_status.value ->> '"
        "expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_e"
        'lements(shared_enterprise_project_status_updates.reads || (SELECT coalesce(j'
        "sonb_agg(jsonb_build_object('artifact_id', field_basis_project_status_update"
        "s.value['id'], 'expected_revision', field_basis_project_status_updates.value"
        "['revision'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elemen"
        "ts(shared_enterprise_project_status_updates.source_basis['artifacts']) AS fi"
        'eld_basis_project_status_updates(value))) AS enterprise_reads_project_status'
        "(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS na"
        "ture, shared_enterprise_project_status_updates.visibility != 'category' OR c"
        "oalesce(shared_enterprise_projects.visibility != 'category', false) OR coale"
        "sce(shared_enterprise_products.visibility != 'category', false) OR (EXISTS ("
        'SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_project_status_update'
        "s.reads || (SELECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', fiel"
        "d_basis_project_status_updates.value['id'], 'expected_revision', field_basis"
        "_project_status_updates.value['revision'])), jsonb_build_array()) AS coalesc"
        'e_2 \nFROM jsonb_array_elements(shared_enterprise_project_status_updates.sou'
        "rce_basis['artifacts']) AS field_basis_project_status_updates(value))) AS en"
        'terprise_reads_project_status(value) JOIN enterprise_authoritative_artifacts'
        '_5974f9e72e6d02d1 ON enterprise_authoritative_artifacts_5974f9e72e6d02d1.ten'
        'ant_id = shared_enterprise_project_status_updates.tenant_id AND enterprise_a'
        'uthoritative_artifacts_5974f9e72e6d02d1.source_id = CAST((enterprise_reads_p'
        "roject_status.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorita"
        'tive_artifacts_5974f9e72e6d02d1.private)) AS private, EXISTS (SELECT 1 \nFRO'
        'M jsonb_array_elements(shared_enterprise_project_status_updates.reads || (SE'
        "LECT coalesce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_projec"
        "t_status_updates.value['id'], 'expected_revision', field_basis_project_statu"
        "s_updates.value['revision'])), jsonb_build_array()) AS coalesce_2 \nFROM jso"
        "nb_array_elements(shared_enterprise_project_status_updates.source_basis['art"
        "ifacts']) AS field_basis_project_status_updates(value))) AS enterprise_reads"
        '_project_status(value) JOIN enterprise_authoritative_artifacts_5974f9e72e6d0'
        '2d1 ON enterprise_authoritative_artifacts_5974f9e72e6d02d1.tenant_id = share'
        'd_enterprise_project_status_updates.tenant_id AND enterprise_authoritative_a'
        'rtifacts_5974f9e72e6d02d1.source_id = CAST((enterprise_reads_project_status.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        '_5974f9e72e6d02d1.customer_original) AS customer_original, NOT (EXISTS (SELE'
        'CT 1 \nFROM shared_enterprise_project_status_updates AS later_named_project_'
        'update \nWHERE later_named_project_update.tenant_id = shared_enterprise_proj'
        'ect_status_updates.tenant_id AND later_named_project_update.category_id = sh'
        'ared_enterprise_project_status_updates.category_id AND later_named_project_u'
        'pdate.product_id = shared_enterprise_project_status_updates.product_id AND l'
        'ater_named_project_update.project_id = shared_enterprise_project_status_upda'
        'tes.project_id AND (later_named_project_update.created_at, later_named_proje'
        'ct_update.id) > (shared_enterprise_project_status_updates.created_at, shared'
        '_enterprise_project_status_updates.id))) AS is_current, shared_enterprise_pr'
        'oject_status_updates.created_at AS created_at, CAST(NULL AS UUID) AS origina'
        'l_id, shared_enterprise_project_status_updates.project_id AS object_id, (SEL'
        'ECT coalesce(array_agg(enterprise_authoritative_artifacts_5974f9e72e6d02d1.o'
        'riginal_id), ARRAY[]::UUID[]) AS coalesce_3 \nFROM jsonb_array_elements(shar'
        'ed_enterprise_project_status_updates.reads || (SELECT coalesce(jsonb_agg(jso'
        "nb_build_object('artifact_id', field_basis_project_status_updates.value['id'"
        "], 'expected_revision', field_basis_project_status_updates.value['revision']"
        ')), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_en'
        "terprise_project_status_updates.source_basis['artifacts']) AS field_basis_pr"
        'oject_status_updates(value))) AS enterprise_reads_project_status(value) JOIN'
        ' enterprise_authoritative_artifacts_5974f9e72e6d02d1 ON enterprise_authorita'
        'tive_artifacts_5974f9e72e6d02d1.tenant_id = shared_enterprise_project_status'
        '_updates.tenant_id AND enterprise_authoritative_artifacts_5974f9e72e6d02d1.s'
        "ource_id = CAST((enterprise_reads_project_status.value ->> 'artifact_id') AS"
        ' UUID) \nWHERE enterprise_authoritative_artifacts_5974f9e72e6d02d1.original_'
        'id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_ar'
        'ray_elements(shared_enterprise_project_status_updates.reads || (SELECT coale'
        "sce(jsonb_agg(jsonb_build_object('artifact_id', field_basis_project_status_u"
        "pdates.value['id'], 'expected_revision', field_basis_project_status_updates."
        "value['revision'])), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_e"
        "lements(shared_enterprise_project_status_updates.source_basis['artifacts']) "
        'AS field_basis_project_status_updates(value))) AS enterprise_reads_project_s'
        'tatus(value) JOIN enterprise_authoritative_artifacts_5974f9e72e6d02d1 ON ent'
        'erprise_authoritative_artifacts_5974f9e72e6d02d1.tenant_id = shared_enterpri'
        'se_project_status_updates.tenant_id AND enterprise_authoritative_artifacts_5'
        '974f9e72e6d02d1.source_id = CAST((enterprise_reads_project_status.value ->> '
        "'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_5974f9e72"
        "e6d02d1.source_revision != CAST((enterprise_reads_project_status.value ->> '"
        "expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS"
        ' read_basis_status \nFROM shared_enterprise_project_status_updates JOIN shar'
        'ed_enterprise_projects ON shared_enterprise_projects.tenant_id = shared_ente'
        'rprise_project_status_updates.tenant_id AND shared_enterprise_projects.produ'
        'ct_id = shared_enterprise_project_status_updates.product_id AND shared_enter'
        'prise_projects.id = shared_enterprise_project_status_updates.project_id AND '
        'shared_enterprise_projects.category_id = shared_enterprise_project_status_up'
        'dates.category_id JOIN shared_enterprise_products ON shared_enterprise_produ'
        'cts.tenant_id = shared_enterprise_project_status_updates.tenant_id AND share'
        'd_enterprise_products.id = shared_enterprise_project_status_updates.product_'
        'id AND shared_enterprise_products.category_id = shared_enterprise_project_st'
        'atus_updates.category_id \nWHERE shared_enterprise_project_status_updates.te'
        "nant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) "
        'AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_proj'
        "ect_status_updates.reads || (SELECT coalesce(jsonb_agg(jsonb_build_object('a"
        "rtifact_id', field_basis_project_status_updates.value['id'], 'expected_revis"
        "ion', field_basis_project_status_updates.value['revision'])), jsonb_build_ar"
        'ray()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_project_s'
        "tatus_updates.source_basis['artifacts']) AS field_basis_project_status_updat"
        'es(value))) AS enterprise_reads_project_status(value) \nWHERE NOT (EXISTS (S'
        'ELECT 1 \nFROM enterprise_authoritative_artifacts_5974f9e72e6d02d1 \nWHERE e'
        'nterprise_authoritative_artifacts_5974f9e72e6d02d1.tenant_id = shared_enterp'
        'rise_project_status_updates.tenant_id AND enterprise_authoritative_artifacts'
        '_5974f9e72e6d02d1.source_id = CAST((enterprise_reads_project_status.value ->'
        "> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritativ"
        'e_enterprise_sources_5974f9e72e6d02d1 \nWHERE authoritative_enterprise_sourc'
        'es_5974f9e72e6d02d1.tenant_id = t AND authoritative_enterprise_sources_5974f'
        '9e72e6d02d1.category_id = c AND CAST(authoritative_enterprise_sources_5974f9'
        "e72e6d02d1.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritativ"
        'e_enterprise_sources_5974f9e72e6d02d1.source_revision AS TEXT) = expected->>'
        "'source_revision' AND authoritative_enterprise_sources_5974f9e72e6d02d1.cont"
        "ent_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'manufa"
        "cturing_document' THEN\n  WITH enterprise_authoritative_artifacts_b87857c504"
        "72d0c4 AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS sourc"
        'e_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.category_i'
        'd AS category_id, artifact_versions.product_id AS product_id, CAST(NULL AS U'
        'UID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.own'
        'er_id AS owner_id, artifact_versions.revision AS source_revision, artifact_v'
        'ersions.title AS title, artifact_versions.content_hash AS content_hash, arti'
        "fact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted"
        "' AS nature, artifact_versions.visibility != 'category' OR coalesce(products"
        ".visibility != 'category', false) OR coalesce(uploaded_originals.visibility "
        "!= 'category', false) AS private, artifact_versions.original_id IS NOT NULL "
        'AS customer_original, true AS is_current, artifact_versions.created_at AS cr'
        'eated_at, artifact_versions.original_id AS original_id, artifact_versions.id'
        ' AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN AR'
        'RAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids,'
        " 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN pro"
        'ducts ON products.tenant_id = artifact_versions.tenant_id AND products.id = '
        'artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_'
        'originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id '
        '= artifact_versions.original_id AND uploaded_originals.category_id = artifac'
        't_versions.category_id AND uploaded_originals.product_id IS NOT DISTINCT FRO'
        'M artifact_versions.product_id LEFT OUTER JOIN original_security ON original'
        '_security.tenant_id = uploaded_originals.tenant_id AND original_security.ori'
        'ginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_ve"
        "rsions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND ("
        'artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifa'
        'ct_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND upl'
        "oaded_originals.status = 'parsed' AND uploaded_originals.scan_status = 'clea"
        "n' AND original_security.source_state = 'active' AND original_security.dispo"
        "sition = 'active' AND original_security.current_request_id IS NOT NULL)), \n"
        'shared_enterprise_manufacturing_preparation_versions AS MATERIALIZED \n(SELE'
        'CT manufacturing_preparation_versions.product_id AS product_id, manufacturin'
        'g_preparation_versions.project_id AS project_id, manufacturing_preparation_v'
        'ersions.kind AS kind, manufacturing_preparation_versions.series_id AS series'
        '_id, manufacturing_preparation_versions.revision AS revision, manufacturing_'
        'preparation_versions.previous_id AS previous_id, manufacturing_preparation_v'
        'ersions.previous_revision AS previous_revision, manufacturing_preparation_ve'
        'rsions.owner_id AS owner_id, manufacturing_preparation_versions.visibility A'
        'S visibility, manufacturing_preparation_versions.title AS title, manufacturi'
        'ng_preparation_versions.status AS status, manufacturing_preparation_versions'
        '.process_id AS process_id, manufacturing_preparation_versions.process_revisi'
        'on AS process_revision, manufacturing_preparation_versions.operation_key AS '
        'operation_key, manufacturing_preparation_versions.purpose AS purpose, manufa'
        'cturing_preparation_versions.purpose_sha256 AS purpose_sha256, manufacturing'
        '_preparation_versions.operation AS operation, manufacturing_preparation_vers'
        'ions.intent_digest AS intent_digest, manufacturing_preparation_versions.body'
        ' AS body, manufacturing_preparation_versions.body_sha256 AS body_sha256, man'
        'ufacturing_preparation_versions.input_snapshot AS input_snapshot, manufactur'
        'ing_preparation_versions.sources AS sources, manufacturing_preparation_versi'
        'ons.required_source_read_set AS required_source_read_set, manufacturing_prep'
        'aration_versions.source_basis AS source_basis, manufacturing_preparation_ver'
        'sions.authority_snapshot AS authority_snapshot, manufacturing_preparation_ve'
        'rsions.review AS review, manufacturing_preparation_versions.shared_proof_id '
        'AS shared_proof_id, manufacturing_preparation_versions.shared_proof_revision'
        ' AS shared_proof_revision, manufacturing_preparation_versions.proof_consumed'
        '_at AS proof_consumed_at, manufacturing_preparation_versions.proof_expires_a'
        't AS proof_expires_at, manufacturing_preparation_versions.token_sha256 AS to'
        'ken_sha256, manufacturing_preparation_versions.material_sha256 AS material_s'
        'ha256, manufacturing_preparation_versions.read_set_sha256 AS read_set_sha256'
        ', manufacturing_preparation_versions.id AS id, manufacturing_preparation_ver'
        'sions.tenant_id AS tenant_id, manufacturing_preparation_versions.created_at '
        'AS created_at, manufacturing_preparation_versions.category_id AS category_id'
        ' \nFROM manufacturing_preparation_versions \nWHERE manufacturing_preparation'
        "_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '"
        "') AS UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT project"
        's.product_id AS product_id, projects.owner_id AS owner_id, projects.name AS '
        'name, projects.purpose AS purpose, projects.scope AS scope, projects.visibil'
        'ity AS visibility, projects.status AS status, projects.revision AS revision,'
        ' projects.current_plan_id AS current_plan_id, projects.trigger_type AS trigg'
        'er_type, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0_de'
        'cision_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.crea'
        'ted_at AS created_at, projects.category_id AS category_id \nFROM projects \n'
        "WHERE projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', tru"
        "e), '') AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT pr"
        'oducts.name AS name, products.purpose AS purpose, products.revision AS revis'
        'ion, products.lifecycle_epoch AS lifecycle_epoch, products.status AS status,'
        ' products.owner_id AS owner_id, products.parent_product_id AS parent_product'
        '_id, products.category_id AS category_id, products.visibility AS visibility,'
        ' products.target_price AS target_price, products.target_price_currency AS ta'
        'rget_price_currency, products.target_price_basis AS target_price_basis, prod'
        'ucts.target_price_includes_tax AS target_price_includes_tax, products.target'
        '_price_as_of AS target_price_as_of, products.id AS id, products.tenant_id AS'
        ' tenant_id, products.created_at AS created_at \nFROM products \nWHERE produc'
        "ts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS U"
        'UID)), \nshared_enterprise_manufacturing_preparation_currents AS MATERIALIZE'
        'D \n(SELECT manufacturing_preparation_currents.product_id AS product_id, man'
        'ufacturing_preparation_currents.project_id AS project_id, manufacturing_prep'
        'aration_currents.kind AS kind, manufacturing_preparation_currents.series_id '
        'AS series_id, manufacturing_preparation_currents.owner_id AS owner_id, manuf'
        'acturing_preparation_currents.visibility AS visibility, manufacturing_prepar'
        'ation_currents.version_id AS version_id, manufacturing_preparation_currents.'
        'revision AS revision, manufacturing_preparation_currents.id AS id, manufactu'
        'ring_preparation_currents.tenant_id AS tenant_id, manufacturing_preparation_'
        'currents.created_at AS created_at, manufacturing_preparation_currents.catego'
        'ry_id AS category_id \nFROM manufacturing_preparation_currents \nWHERE manuf'
        "acturing_preparation_currents.tenant_id = CAST(nullif(current_setting('pdos."
        "tenant_id', true), '') AS UUID)), \nshared_enterprise_manufacturing_baseline"
        '_publications AS MATERIALIZED \n(SELECT manufacturing_baseline_publications.'
        'product_id AS product_id, manufacturing_baseline_publications.project_id AS '
        'project_id, manufacturing_baseline_publications.series_id AS series_id, manu'
        'facturing_baseline_publications.revision AS revision, manufacturing_baseline'
        '_publications.previous_id AS previous_id, manufacturing_baseline_publication'
        's.previous_revision AS previous_revision, manufacturing_baseline_publication'
        's.owner_id AS owner_id, manufacturing_baseline_publications.writer_id AS wri'
        'ter_id, manufacturing_baseline_publications.actor_id AS actor_id, manufactur'
        'ing_baseline_publications.requester_id AS requester_id, manufacturing_baseli'
        'ne_publications.visibility AS visibility, manufacturing_baseline_publication'
        's.purpose AS purpose, manufacturing_baseline_publications.baseline_kind AS b'
        'aseline_kind, manufacturing_baseline_publications.baseline_id AS baseline_id'
        ', manufacturing_baseline_publications.baseline_revision AS baseline_revision'
        ', manufacturing_baseline_publications.process_id AS process_id, manufacturin'
        'g_baseline_publications.process_revision AS process_revision, manufacturing_'
        'baseline_publications.status AS status, manufacturing_baseline_publications.'
        'operation AS operation, manufacturing_baseline_publications.write_tier AS wr'
        'ite_tier, manufacturing_baseline_publications.body AS body, manufacturing_ba'
        'seline_publications.body_sha256 AS body_sha256, manufacturing_baseline_publi'
        'cations.input_snapshot AS input_snapshot, manufacturing_baseline_publication'
        's.payload_sha256 AS payload_sha256, manufacturing_baseline_publications.sour'
        'ces AS sources, manufacturing_baseline_publications.required_source_read_set'
        ' AS required_source_read_set, manufacturing_baseline_publications.source_bas'
        'is AS source_basis, manufacturing_baseline_publications.authority_snapshot A'
        'S authority_snapshot, manufacturing_baseline_publications.gaps AS gaps, manu'
        'facturing_baseline_publications.command_id AS command_id, manufacturing_base'
        'line_publications.receipt_id AS receipt_id, manufacturing_baseline_publicati'
        'ons.shared_proof_id AS shared_proof_id, manufacturing_baseline_publications.'
        'shared_proof_revision AS shared_proof_revision, manufacturing_baseline_publi'
        'cations.proof_consumed_at AS proof_consumed_at, manufacturing_baseline_publi'
        'cations.proof_expires_at AS proof_expires_at, manufacturing_baseline_publica'
        'tions.token_sha256 AS token_sha256, manufacturing_baseline_publications.mate'
        'rial_sha256 AS material_sha256, manufacturing_baseline_publications.read_set'
        '_sha256 AS read_set_sha256, manufacturing_baseline_publications.intent_diges'
        't AS intent_digest, manufacturing_baseline_publications.request_digest AS re'
        'quest_digest, manufacturing_baseline_publications.id AS id, manufacturing_ba'
        'seline_publications.tenant_id AS tenant_id, manufacturing_baseline_publicati'
        'ons.created_at AS created_at, manufacturing_baseline_publications.category_i'
        'd AS category_id \nFROM manufacturing_baseline_publications \nWHERE manufact'
        "uring_baseline_publications.tenant_id = CAST(nullif(current_setting('pdos.te"
        "nant_id', true), '') AS UUID)), \nshared_enterprise_manufacturing_publicatio"
        'n_documents AS MATERIALIZED \n(SELECT manufacturing_publication_documents.pr'
        'oduct_id AS product_id, manufacturing_publication_documents.project_id AS pr'
        'oject_id, manufacturing_publication_documents.publication_id AS publication_'
        'id, manufacturing_publication_documents.publication_revision AS publication_'
        'revision, manufacturing_publication_documents.process_id AS process_id, manu'
        'facturing_publication_documents.process_revision AS process_revision, manufa'
        'cturing_publication_documents.operation_key AS operation_key, manufacturing_'
        'publication_documents.document_kind AS document_kind, manufacturing_publicat'
        'ion_documents.document_id AS document_id, manufacturing_publication_document'
        's.document_revision AS document_revision, manufacturing_publication_document'
        's.id AS id, manufacturing_publication_documents.tenant_id AS tenant_id, manu'
        'facturing_publication_documents.created_at AS created_at, manufacturing_publ'
        'ication_documents.category_id AS category_id \nFROM manufacturing_publicatio'
        'n_documents \nWHERE manufacturing_publication_documents.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpr"
        'ise_manufacturing_publication_currents AS MATERIALIZED \n(SELECT manufacturi'
        'ng_publication_currents.product_id AS product_id, manufacturing_publication_'
        'currents.project_id AS project_id, manufacturing_publication_currents.series'
        '_id AS series_id, manufacturing_publication_currents.owner_id AS owner_id, m'
        'anufacturing_publication_currents.visibility AS visibility, manufacturing_pu'
        'blication_currents.version_id AS version_id, manufacturing_publication_curre'
        'nts.revision AS revision, manufacturing_publication_currents.epoch AS epoch,'
        ' manufacturing_publication_currents.id AS id, manufacturing_publication_curr'
        'ents.tenant_id AS tenant_id, manufacturing_publication_currents.created_at A'
        'S created_at, manufacturing_publication_currents.category_id AS category_id '
        '\nFROM manufacturing_publication_currents \nWHERE manufacturing_publication_'
        "currents.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), ''"
        ') AS UUID)), \nauthoritative_enterprise_sources_b87857c50472d0c4 AS \n(SELEC'
        "T 'manufacturing_document' AS source_type, shared_enterprise_manufacturing_p"
        'reparation_versions.id AS source_id, shared_enterprise_manufacturing_prepara'
        'tion_versions.tenant_id AS tenant_id, shared_enterprise_manufacturing_prepar'
        'ation_versions.category_id AS category_id, shared_enterprise_manufacturing_p'
        'reparation_versions.product_id AS product_id, shared_enterprise_manufacturin'
        'g_preparation_versions.project_id AS project_id, CAST(NULL AS UUID) AS propo'
        'sal_id, shared_enterprise_manufacturing_preparation_versions.owner_id AS own'
        'er_id, shared_enterprise_manufacturing_preparation_versions.revision AS sour'
        'ce_revision, shared_enterprise_manufacturing_preparation_versions.title AS t'
        "itle, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', sha"
        "red_enterprise_manufacturing_preparation_versions.series_id, 'kind', 'manufa"
        "cturing_document', 'facts', jsonb_build_object('record_kind', 'manufacturing"
        "_draft', 'status', shared_enterprise_manufacturing_preparation_versions.stat"
        "us, 'document', jsonb_build_object('document_kind', shared_enterprise_manufa"
        "cturing_preparation_versions.kind, 'document_id', shared_enterprise_manufact"
        "uring_preparation_versions.id, 'document_revision', shared_enterprise_manufa"
        "cturing_preparation_versions.revision, 'series_id', shared_enterprise_manufa"
        "cturing_preparation_versions.series_id, 'title', shared_enterprise_manufactu"
        "ring_preparation_versions.title, 'process_id', shared_enterprise_manufacturi"
        "ng_preparation_versions.process_id, 'process_revision', shared_enterprise_ma"
        "nufacturing_preparation_versions.process_revision, 'operation_key', shared_e"
        "nterprise_manufacturing_preparation_versions.operation_key, 'conditions', sh"
        "ared_enterprise_manufacturing_preparation_versions.body['input']['conditions"
        "'], 'steps', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_ins"
        "truction_steps.value['key'], 'text', native_instruction_steps.value['text'],"
        " 'safety_notes', native_instruction_steps.value['safety_notes'], 'parameters"
        "', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_instruction_p"
        "arameters.value['key'], 'unit', native_instruction_parameters.value['unit'],"
        " 'nominal', native_instruction_parameters.value['nominal'], 'lower', native_"
        "instruction_parameters.value['lower'], 'upper', native_instruction_parameter"
        "s.value['upper'], 'nature', native_instruction_parameters.value['nature'], '"
        "condition', native_instruction_parameters.value['condition']) ORDER BY nativ"
        'e_instruction_parameters.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM'
        " jsonb_array_elements(coalesce(native_instruction_steps.value['parameters'],"
        " CAST('[]' AS JSONB))) WITH ORDINALITY AS native_instruction_parameters(valu"
        'e, ordinal))) ORDER BY native_instruction_steps.ordinal), jsonb_build_array('
        ')) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_manu'
        "facturing_preparation_versions.body['input']['steps'], CAST('[]' AS JSONB)))"
        " WITH ORDINALITY AS native_instruction_steps(value, ordinal)), 'checks', (SE"
        "LECT coalesce(jsonb_agg(jsonb_build_object('key', native_control_checks.valu"
        "e['key'], 'feature', native_control_checks.value['feature'], 'method', nativ"
        "e_control_checks.value['method'], 'frequency', native_control_checks.value['"
        "frequency'], 'sampling_method', native_control_checks.value['sampling_method"
        "'], 'reaction_plan', native_control_checks.value['reaction_plan'], 'responsi"
        "ble_role', native_control_checks.value['responsible_role'], 'criterion_key',"
        " native_control_checks.value['criterion']['key'], 'criterion_unit', native_c"
        "ontrol_checks.value['criterion']['unit'], 'criterion_nominal', native_contro"
        "l_checks.value['criterion']['nominal'], 'criterion_lower', native_control_ch"
        "ecks.value['criterion']['lower'], 'criterion_upper', native_control_checks.v"
        "alue['criterion']['upper'], 'criterion_nature', native_control_checks.value["
        "'criterion']['nature']) ORDER BY native_control_checks.ordinal), jsonb_build"
        '_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(shared_enterpri'
        "se_manufacturing_preparation_versions.body['input']['checks'], CAST('[]' AS "
        "JSONB))) WITH ORDINALITY AS native_control_checks(value, ordinal)), 'declare"
        "d_gaps', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', native_docume"
        "nt_declared_gaps.value['code'], 'message', native_document_declared_gaps.val"
        "ue['message']) ORDER BY native_document_declared_gaps.ordinal), jsonb_build_"
        'array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterpris'
        "e_manufacturing_preparation_versions.body['gaps'], CAST('[]' AS JSONB))) WIT"
        "H ORDINALITY AS native_document_declared_gaps(value, ordinal)), 'continuatio"
        "n_permission', 'not_evaluated'), 'record_policy', '\u4ec5\u4e3a\u539f\u751f"
        '\u5236\u9020\u8349\u7a3f\uff1b\u6700\u65b0\u8349\u7a3f\u4e0d\u7b49\u4e8e'
        "\u6b63\u5f0f\u53d1\u5e03\u6216\u5f53\u524d\u6267\u884c\u8bb8\u53ef\u3002'), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_manufacturing_document.value['artifact_id'], 've"
        "rsion', enterprise_reads_manufacturing_document.value['expected_revision']) "
        "ORDER BY enterprise_reads_manufacturing_document.value ->> 'artifact_id', en"
        "terprise_reads_manufacturing_document.value ->> 'expected_revision'), jsonb_"
        'build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_m'
        'anufacturing_preparation_versions.required_source_read_set) AS enterprise_re'
        "ads_manufacturing_document(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_manufacturing_preparation_versions.series_id, 'kind"
        "', 'manufacturing_document', 'facts', jsonb_build_object('record_kind', 'man"
        "ufacturing_draft', 'status', shared_enterprise_manufacturing_preparation_ver"
        "sions.status, 'document', jsonb_build_object('document_kind', shared_enterpr"
        "ise_manufacturing_preparation_versions.kind, 'document_id', shared_enterpris"
        "e_manufacturing_preparation_versions.id, 'document_revision', shared_enterpr"
        "ise_manufacturing_preparation_versions.revision, 'series_id', shared_enterpr"
        "ise_manufacturing_preparation_versions.series_id, 'title', shared_enterprise"
        "_manufacturing_preparation_versions.title, 'process_id', shared_enterprise_m"
        "anufacturing_preparation_versions.process_id, 'process_revision', shared_ent"
        "erprise_manufacturing_preparation_versions.process_revision, 'operation_key'"
        ", shared_enterprise_manufacturing_preparation_versions.operation_key, 'condi"
        "tions', shared_enterprise_manufacturing_preparation_versions.body['input']['"
        "conditions'], 'steps', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', "
        "native_instruction_steps.value['key'], 'text', native_instruction_steps.valu"
        "e['text'], 'safety_notes', native_instruction_steps.value['safety_notes'], '"
        "parameters', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_ins"
        "truction_parameters.value['key'], 'unit', native_instruction_parameters.valu"
        "e['unit'], 'nominal', native_instruction_parameters.value['nominal'], 'lower"
        "', native_instruction_parameters.value['lower'], 'upper', native_instruction"
        "_parameters.value['upper'], 'nature', native_instruction_parameters.value['n"
        "ature'], 'condition', native_instruction_parameters.value['condition']) ORDE"
        'R BY native_instruction_parameters.ordinal), jsonb_build_array()) AS coalesc'
        "e_2 \nFROM jsonb_array_elements(coalesce(native_instruction_steps.value['par"
        "ameters'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_instruction_param"
        'eters(value, ordinal))) ORDER BY native_instruction_steps.ordinal), jsonb_bu'
        'ild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enter'
        "prise_manufacturing_preparation_versions.body['input']['steps'], CAST('[]' A"
        "S JSONB))) WITH ORDINALITY AS native_instruction_steps(value, ordinal)), 'ch"
        "ecks', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_control_c"
        "hecks.value['key'], 'feature', native_control_checks.value['feature'], 'meth"
        "od', native_control_checks.value['method'], 'frequency', native_control_chec"
        "ks.value['frequency'], 'sampling_method', native_control_checks.value['sampl"
        "ing_method'], 'reaction_plan', native_control_checks.value['reaction_plan'],"
        " 'responsible_role', native_control_checks.value['responsible_role'], 'crite"
        "rion_key', native_control_checks.value['criterion']['key'], 'criterion_unit'"
        ", native_control_checks.value['criterion']['unit'], 'criterion_nominal', nat"
        "ive_control_checks.value['criterion']['nominal'], 'criterion_lower', native_"
        "control_checks.value['criterion']['lower'], 'criterion_upper', native_contro"
        "l_checks.value['criterion']['upper'], 'criterion_nature', native_control_che"
        "cks.value['criterion']['nature']) ORDER BY native_control_checks.ordinal), j"
        'sonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(share'
        "d_enterprise_manufacturing_preparation_versions.body['input']['checks'], CAS"
        "T('[]' AS JSONB))) WITH ORDINALITY AS native_control_checks(value, ordinal))"
        ", 'declared_gaps', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', nat"
        "ive_document_declared_gaps.value['code'], 'message', native_document_declare"
        "d_gaps.value['message']) ORDER BY native_document_declared_gaps.ordinal), js"
        'onb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared'
        "_enterprise_manufacturing_preparation_versions.body['gaps'], CAST('[]' AS JS"
        "ONB))) WITH ORDINALITY AS native_document_declared_gaps(value, ordinal)), 'c"
        "ontinuation_permission', 'not_evaluated'), 'record_policy', '\u4ec5\u4e3a"
        '\u539f\u751f\u5236\u9020\u8349\u7a3f\uff1b\u6700\u65b0\u8349\u7a3f\u4e0d'
        '\u7b49\u4e8e\u6b63\u5f0f\u53d1\u5e03\u6216\u5f53\u524d\u6267\u884c\u8bb8'
        "\u53ef\u3002'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object"
        "('type', 'artifact', 'id', enterprise_reads_manufacturing_document.value['ar"
        "tifact_id'], 'version', enterprise_reads_manufacturing_document.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_manufacturing_document.value ->> '"
        "artifact_id', enterprise_reads_manufacturing_document.value ->> 'expected_re"
        "vision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(sha"
        'red_enterprise_manufacturing_preparation_versions.required_source_read_set) '
        "AS enterprise_reads_manufacturing_document(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enter"
        "prise_manufacturing_preparation_versions.series_id, 'kind', 'manufacturing_d"
        "ocument', 'facts', jsonb_build_object('record_kind', 'manufacturing_draft', "
        "'status', shared_enterprise_manufacturing_preparation_versions.status, 'docu"
        "ment', jsonb_build_object('document_kind', shared_enterprise_manufacturing_p"
        "reparation_versions.kind, 'document_id', shared_enterprise_manufacturing_pre"
        "paration_versions.id, 'document_revision', shared_enterprise_manufacturing_p"
        "reparation_versions.revision, 'series_id', shared_enterprise_manufacturing_p"
        "reparation_versions.series_id, 'title', shared_enterprise_manufacturing_prep"
        "aration_versions.title, 'process_id', shared_enterprise_manufacturing_prepar"
        "ation_versions.process_id, 'process_revision', shared_enterprise_manufacturi"
        "ng_preparation_versions.process_revision, 'operation_key', shared_enterprise"
        "_manufacturing_preparation_versions.operation_key, 'conditions', shared_ente"
        "rprise_manufacturing_preparation_versions.body['input']['conditions'], 'step"
        "s', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_instruction_"
        "steps.value['key'], 'text', native_instruction_steps.value['text'], 'safety_"
        "notes', native_instruction_steps.value['safety_notes'], 'parameters', (SELEC"
        "T coalesce(jsonb_agg(jsonb_build_object('key', native_instruction_parameters"
        ".value['key'], 'unit', native_instruction_parameters.value['unit'], 'nominal"
        "', native_instruction_parameters.value['nominal'], 'lower', native_instructi"
        "on_parameters.value['lower'], 'upper', native_instruction_parameters.value['"
        "upper'], 'nature', native_instruction_parameters.value['nature'], 'condition"
        "', native_instruction_parameters.value['condition']) ORDER BY native_instruc"
        'tion_parameters.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_ar'
        "ray_elements(coalesce(native_instruction_steps.value['parameters'], CAST('[]"
        "' AS JSONB))) WITH ORDINALITY AS native_instruction_parameters(value, ordina"
        'l))) ORDER BY native_instruction_steps.ordinal), jsonb_build_array()) AS coa'
        'lesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_manufacturing'
        "_preparation_versions.body['input']['steps'], CAST('[]' AS JSONB))) WITH ORD"
        "INALITY AS native_instruction_steps(value, ordinal)), 'checks', (SELECT coal"
        "esce(jsonb_agg(jsonb_build_object('key', native_control_checks.value['key'],"
        " 'feature', native_control_checks.value['feature'], 'method', native_control"
        "_checks.value['method'], 'frequency', native_control_checks.value['frequency"
        "'], 'sampling_method', native_control_checks.value['sampling_method'], 'reac"
        "tion_plan', native_control_checks.value['reaction_plan'], 'responsible_role'"
        ", native_control_checks.value['responsible_role'], 'criterion_key', native_c"
        "ontrol_checks.value['criterion']['key'], 'criterion_unit', native_control_ch"
        "ecks.value['criterion']['unit'], 'criterion_nominal', native_control_checks."
        "value['criterion']['nominal'], 'criterion_lower', native_control_checks.valu"
        "e['criterion']['lower'], 'criterion_upper', native_control_checks.value['cri"
        "terion']['upper'], 'criterion_nature', native_control_checks.value['criterio"
        "n']['nature']) ORDER BY native_control_checks.ordinal), jsonb_build_array())"
        ' AS coalesce_3 \nFROM jsonb_array_elements(coalesce(shared_enterprise_manufa'
        "cturing_preparation_versions.body['input']['checks'], CAST('[]' AS JSONB))) "
        "WITH ORDINALITY AS native_control_checks(value, ordinal)), 'declared_gaps', "
        "(SELECT coalesce(jsonb_agg(jsonb_build_object('code', native_document_declar"
        "ed_gaps.value['code'], 'message', native_document_declared_gaps.value['messa"
        "ge']) ORDER BY native_document_declared_gaps.ordinal), jsonb_build_array()) "
        'AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterprise_manufac'
        "turing_preparation_versions.body['gaps'], CAST('[]' AS JSONB))) WITH ORDINAL"
        "ITY AS native_document_declared_gaps(value, ordinal)), 'continuation_permiss"
        "ion', 'not_evaluated'), 'record_policy', '\u4ec5\u4e3a\u539f\u751f\u5236"
        '\u9020\u8349\u7a3f\uff1b\u6700\u65b0\u8349\u7a3f\u4e0d\u7b49\u4e8e\u6b63'
        "\u5f0f\u53d1\u5e03\u6216\u5f53\u524d\u6267\u884c\u8bb8\u53ef\u3002'), 'sourc"
        "e_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', '"
        "id', enterprise_reads_manufacturing_document.value['artifact_id'], 'version'"
        ", enterprise_reads_manufacturing_document.value['expected_revision']) ORDER "
        "BY enterprise_reads_manufacturing_document.value ->> 'artifact_id', enterpri"
        "se_reads_manufacturing_document.value ->> 'expected_revision'), jsonb_build_"
        'array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_manufac'
        'turing_preparation_versions.required_source_read_set) AS enterprise_reads_ma'
        "nufacturing_document(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS struct"
        "ured, 'structured' AS nature, shared_enterprise_manufacturing_preparation_ve"
        "rsions.visibility != 'category' OR coalesce(shared_enterprise_projects.visib"
        "ility != 'category', false) OR coalesce(shared_enterprise_products.visibilit"
        "y != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(sha"
        'red_enterprise_manufacturing_preparation_versions.required_source_read_set) '
        'AS enterprise_reads_manufacturing_document(value) JOIN enterprise_authoritat'
        'ive_artifacts_b87857c50472d0c4 ON enterprise_authoritative_artifacts_b87857c'
        '50472d0c4.tenant_id = shared_enterprise_manufacturing_preparation_versions.t'
        'enant_id AND enterprise_authoritative_artifacts_b87857c50472d0c4.source_id ='
        " CAST((enterprise_reads_manufacturing_document.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_b87857c50472d0c4.private)) A'
        'S private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_ma'
        'nufacturing_preparation_versions.required_source_read_set) AS enterprise_rea'
        'ds_manufacturing_document(value) JOIN enterprise_authoritative_artifacts_b87'
        '857c50472d0c4 ON enterprise_authoritative_artifacts_b87857c50472d0c4.tenant_'
        'id = shared_enterprise_manufacturing_preparation_versions.tenant_id AND ente'
        'rprise_authoritative_artifacts_b87857c50472d0c4.source_id = CAST((enterprise'
        "_reads_manufacturing_document.value ->> 'artifact_id') AS UUID) \nWHERE ente"
        'rprise_authoritative_artifacts_b87857c50472d0c4.customer_original) AS custom'
        'er_original, shared_enterprise_manufacturing_preparation_currents.version_id'
        ' = shared_enterprise_manufacturing_preparation_versions.id AS is_current, sh'
        'ared_enterprise_manufacturing_preparation_versions.created_at AS created_at,'
        ' CAST(NULL AS UUID) AS original_id, shared_enterprise_manufacturing_preparat'
        'ion_versions.series_id AS object_id, (SELECT coalesce(array_agg(enterprise_a'
        'uthoritative_artifacts_b87857c50472d0c4.original_id), ARRAY[]::UUID[]) AS co'
        'alesce_6 \nFROM jsonb_array_elements(shared_enterprise_manufacturing_prepara'
        'tion_versions.required_source_read_set) AS enterprise_reads_manufacturing_do'
        'cument(value) JOIN enterprise_authoritative_artifacts_b87857c50472d0c4 ON en'
        'terprise_authoritative_artifacts_b87857c50472d0c4.tenant_id = shared_enterpr'
        'ise_manufacturing_preparation_versions.tenant_id AND enterprise_authoritativ'
        'e_artifacts_b87857c50472d0c4.source_id = CAST((enterprise_reads_manufacturin'
        "g_document.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritativ"
        'e_artifacts_b87857c50472d0c4.original_id IS NOT NULL) AS original_ids, CASE '
        'WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_manufac'
        'turing_preparation_versions.required_source_read_set) AS enterprise_reads_ma'
        'nufacturing_document(value) JOIN enterprise_authoritative_artifacts_b87857c5'
        '0472d0c4 ON enterprise_authoritative_artifacts_b87857c50472d0c4.tenant_id = '
        'shared_enterprise_manufacturing_preparation_versions.tenant_id AND enterpris'
        'e_authoritative_artifacts_b87857c50472d0c4.source_id = CAST((enterprise_read'
        "s_manufacturing_document.value ->> 'artifact_id') AS UUID) \nWHERE enterpris"
        'e_authoritative_artifacts_b87857c50472d0c4.source_revision != CAST((enterpri'
        "se_reads_manufacturing_document.value ->> 'expected_revision') AS INTEGER)))"
        " THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_"
        'enterprise_manufacturing_preparation_versions JOIN shared_enterprise_project'
        's ON shared_enterprise_projects.tenant_id = shared_enterprise_manufacturing_'
        'preparation_versions.tenant_id AND shared_enterprise_projects.product_id = s'
        'hared_enterprise_manufacturing_preparation_versions.product_id AND shared_en'
        'terprise_projects.id = shared_enterprise_manufacturing_preparation_versions.'
        'project_id AND shared_enterprise_projects.category_id = shared_enterprise_ma'
        'nufacturing_preparation_versions.category_id JOIN shared_enterprise_products'
        ' ON shared_enterprise_products.tenant_id = shared_enterprise_manufacturing_p'
        'reparation_versions.tenant_id AND shared_enterprise_products.id = shared_ent'
        'erprise_manufacturing_preparation_versions.product_id AND shared_enterprise_'
        'products.category_id = shared_enterprise_manufacturing_preparation_versions.'
        'category_id JOIN shared_enterprise_manufacturing_preparation_currents ON sha'
        'red_enterprise_manufacturing_preparation_currents.tenant_id = shared_enterpr'
        'ise_manufacturing_preparation_versions.tenant_id AND shared_enterprise_manuf'
        'acturing_preparation_currents.category_id = shared_enterprise_manufacturing_'
        'preparation_versions.category_id AND shared_enterprise_manufacturing_prepara'
        'tion_currents.product_id = shared_enterprise_manufacturing_preparation_versi'
        'ons.product_id AND shared_enterprise_manufacturing_preparation_currents.proj'
        'ect_id = shared_enterprise_manufacturing_preparation_versions.project_id AND'
        ' shared_enterprise_manufacturing_preparation_currents.kind = shared_enterpri'
        'se_manufacturing_preparation_versions.kind AND shared_enterprise_manufacturi'
        'ng_preparation_currents.series_id = shared_enterprise_manufacturing_preparat'
        'ion_versions.series_id \nWHERE shared_enterprise_manufacturing_preparation_v'
        "ersions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '')"
        ' AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enter'
        'prise_manufacturing_preparation_versions.required_source_read_set) AS enterp'
        'rise_reads_manufacturing_document(value) \nWHERE NOT (EXISTS (SELECT 1 \nFRO'
        'M enterprise_authoritative_artifacts_b87857c50472d0c4 \nWHERE enterprise_aut'
        'horitative_artifacts_b87857c50472d0c4.tenant_id = shared_enterprise_manufact'
        'uring_preparation_versions.tenant_id AND enterprise_authoritative_artifacts_'
        'b87857c50472d0c4.source_id = CAST((enterprise_reads_manufacturing_document.v'
        "alue ->> 'artifact_id') AS UUID))))) AND shared_enterprise_manufacturing_pre"
        "paration_versions.kind IN ('work_instruction', 'control_plan') UNION ALL SEL"
        "ECT 'manufacturing_document' AS source_type, shared_enterprise_manufacturing"
        '_publication_documents.id AS source_id, shared_enterprise_manufacturing_publ'
        'ication_documents.tenant_id AS tenant_id, shared_enterprise_manufacturing_pu'
        'blication_documents.category_id AS category_id, shared_enterprise_manufactur'
        'ing_publication_documents.product_id AS product_id, shared_enterprise_manufa'
        'cturing_publication_documents.project_id AS project_id, CAST(NULL AS UUID) A'
        'S proposal_id, shared_enterprise_manufacturing_baseline_publications.owner_i'
        'd AS owner_id, shared_enterprise_manufacturing_publication_documents.publica'
        "tion_revision AS source_revision, '\u6b63\u5f0f\u5236\u9020\u8d44\u6599 \xb7"
        " ' || shared_enterprise_manufacturing_preparation_versions.title AS title, e"
        "ncode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_ent"
        "erprise_manufacturing_publication_documents.id, 'kind', 'manufacturing_docum"
        "ent', 'facts', jsonb_build_object('record_kind', 'published_manufacturing_do"
        "cument', 'status', shared_enterprise_manufacturing_baseline_publications.sta"
        "tus, 'publication_id', shared_enterprise_manufacturing_baseline_publications"
        ".id, 'publication_revision', shared_enterprise_manufacturing_baseline_public"
        "ations.revision, 'document', jsonb_build_object('document_kind', shared_ente"
        "rprise_manufacturing_preparation_versions.kind, 'document_id', shared_enterp"
        "rise_manufacturing_preparation_versions.id, 'document_revision', shared_ente"
        "rprise_manufacturing_preparation_versions.revision, 'series_id', shared_ente"
        "rprise_manufacturing_preparation_versions.series_id, 'title', shared_enterpr"
        "ise_manufacturing_preparation_versions.title, 'process_id', shared_enterpris"
        "e_manufacturing_preparation_versions.process_id, 'process_revision', shared_"
        "enterprise_manufacturing_preparation_versions.process_revision, 'operation_k"
        "ey', shared_enterprise_manufacturing_preparation_versions.operation_key, 'co"
        "nditions', shared_enterprise_manufacturing_preparation_versions.body['input'"
        "]['conditions'], 'steps', (SELECT coalesce(jsonb_agg(jsonb_build_object('key"
        "', native_instruction_steps.value['key'], 'text', native_instruction_steps.v"
        "alue['text'], 'safety_notes', native_instruction_steps.value['safety_notes']"
        ", 'parameters', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_"
        "instruction_parameters.value['key'], 'unit', native_instruction_parameters.v"
        "alue['unit'], 'nominal', native_instruction_parameters.value['nominal'], 'lo"
        "wer', native_instruction_parameters.value['lower'], 'upper', native_instruct"
        "ion_parameters.value['upper'], 'nature', native_instruction_parameters.value"
        "['nature'], 'condition', native_instruction_parameters.value['condition']) O"
        'RDER BY native_instruction_parameters.ordinal), jsonb_build_array()) AS coal'
        "esce_8 \nFROM jsonb_array_elements(coalesce(native_instruction_steps.value['"
        "parameters'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_instruction_pa"
        'rameters(value, ordinal))) ORDER BY native_instruction_steps.ordinal), jsonb'
        '_build_array()) AS coalesce_7 \nFROM jsonb_array_elements(coalesce(shared_en'
        "terprise_manufacturing_preparation_versions.body['input']['steps'], CAST('[]"
        "' AS JSONB))) WITH ORDINALITY AS native_instruction_steps(value, ordinal)), "
        "'checks', (SELECT coalesce(jsonb_agg(jsonb_build_object('key', native_contro"
        "l_checks.value['key'], 'feature', native_control_checks.value['feature'], 'm"
        "ethod', native_control_checks.value['method'], 'frequency', native_control_c"
        "hecks.value['frequency'], 'sampling_method', native_control_checks.value['sa"
        "mpling_method'], 'reaction_plan', native_control_checks.value['reaction_plan"
        "'], 'responsible_role', native_control_checks.value['responsible_role'], 'cr"
        "iterion_key', native_control_checks.value['criterion']['key'], 'criterion_un"
        "it', native_control_checks.value['criterion']['unit'], 'criterion_nominal', "
        "native_control_checks.value['criterion']['nominal'], 'criterion_lower', nati"
        "ve_control_checks.value['criterion']['lower'], 'criterion_upper', native_con"
        "trol_checks.value['criterion']['upper'], 'criterion_nature', native_control_"
        "checks.value['criterion']['nature']) ORDER BY native_control_checks.ordinal)"
        ', jsonb_build_array()) AS coalesce_9 \nFROM jsonb_array_elements(coalesce(sh'
        "ared_enterprise_manufacturing_preparation_versions.body['input']['checks'], "
        "CAST('[]' AS JSONB))) WITH ORDINALITY AS native_control_checks(value, ordina"
        "l)), 'declared_gaps', (SELECT coalesce(jsonb_agg(jsonb_build_object('code', "
        "native_document_declared_gaps.value['code'], 'message', native_document_decl"
        "ared_gaps.value['message']) ORDER BY native_document_declared_gaps.ordinal),"
        ' jsonb_build_array()) AS coalesce_10 \nFROM jsonb_array_elements(coalesce(sh'
        "ared_enterprise_manufacturing_preparation_versions.body['gaps'], CAST('[]' A"
        'S JSONB))) WITH ORDINALITY AS native_document_declared_gaps(value, ordinal))'
        ", 'continuation_permission', 'not_evaluated'), 'record_policy', '\u8be5"
        '\u6b63\u5f0f\u53d1\u5e03\u56fa\u5b9a\u5f15\u7528\u6b64\u6587\u6863\u7248'
        '\u672c\uff1b\u4e0d\u66ff\u4ee3\u539f\u751f\u9002\u7528\u6027\u6216\u7ee7'
        "\u7eed\u6267\u884c\u6838\u9a8c\u3002'), 'source_refs', (SELECT coalesce(json"
        "b_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_manufact"
        "uring_document.value['artifact_id'], 'version', enterprise_reads_manufacturi"
        "ng_document.value['expected_revision']) ORDER BY enterprise_reads_manufactur"
        "ing_document.value ->> 'artifact_id', enterprise_reads_manufacturing_documen"
        "t.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_11 \nFROM"
        ' jsonb_array_elements((SELECT shared_enterprise_manufacturing_preparation_ve'
        'rsions.required_source_read_set || shared_enterprise_manufacturing_baseline_'
        'publications.required_source_read_set AS anon_2 \nFROM shared_enterprise_man'
        'ufacturing_preparation_versions JOIN shared_enterprise_manufacturing_baselin'
        'e_publications ON shared_enterprise_manufacturing_publication_documents.tena'
        'nt_id = shared_enterprise_manufacturing_baseline_publications.tenant_id AND '
        'shared_enterprise_manufacturing_publication_documents.category_id = shared_e'
        'nterprise_manufacturing_baseline_publications.category_id AND shared_enterpr'
        'ise_manufacturing_publication_documents.product_id = shared_enterprise_manuf'
        'acturing_baseline_publications.product_id AND shared_enterprise_manufacturin'
        'g_publication_documents.project_id = shared_enterprise_manufacturing_baselin'
        'e_publications.project_id AND shared_enterprise_manufacturing_publication_do'
        'cuments.publication_id = shared_enterprise_manufacturing_baseline_publicatio'
        'ns.id AND shared_enterprise_manufacturing_publication_documents.publication_'
        'revision = shared_enterprise_manufacturing_baseline_publications.revision \n'
        'WHERE shared_enterprise_manufacturing_publication_documents.tenant_id = shar'
        'ed_enterprise_manufacturing_preparation_versions.tenant_id AND shared_enterp'
        'rise_manufacturing_publication_documents.category_id = shared_enterprise_man'
        'ufacturing_preparation_versions.category_id AND shared_enterprise_manufactur'
        'ing_publication_documents.product_id = shared_enterprise_manufacturing_prepa'
        'ration_versions.product_id AND shared_enterprise_manufacturing_publication_d'
        'ocuments.project_id = shared_enterprise_manufacturing_preparation_versions.p'
        'roject_id AND shared_enterprise_manufacturing_publication_documents.document'
        '_id = shared_enterprise_manufacturing_preparation_versions.id AND shared_ent'
        'erprise_manufacturing_publication_documents.document_kind = shared_enterpris'
        'e_manufacturing_preparation_versions.kind AND shared_enterprise_manufacturin'
        'g_publication_documents.document_revision = shared_enterprise_manufacturing_'
        'preparation_versions.revision AND shared_enterprise_manufacturing_publicatio'
        'n_documents.process_id = shared_enterprise_manufacturing_preparation_version'
        's.process_id AND shared_enterprise_manufacturing_publication_documents.proce'
        'ss_revision = shared_enterprise_manufacturing_preparation_versions.process_r'
        'evision AND shared_enterprise_manufacturing_publication_documents.operation_'
        'key = shared_enterprise_manufacturing_preparation_versions.operation_key)) A'
        "S enterprise_reads_manufacturing_document(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_o"
        "bject('object_id', shared_enterprise_manufacturing_publication_documents.id,"
        " 'kind', 'manufacturing_document', 'facts', jsonb_build_object('record_kind'"
        ", 'published_manufacturing_document', 'status', shared_enterprise_manufactur"
        "ing_baseline_publications.status, 'publication_id', shared_enterprise_manufa"
        "cturing_baseline_publications.id, 'publication_revision', shared_enterprise_"
        "manufacturing_baseline_publications.revision, 'document', jsonb_build_object"
        "('document_kind', shared_enterprise_manufacturing_preparation_versions.kind,"
        " 'document_id', shared_enterprise_manufacturing_preparation_versions.id, 'do"
        "cument_revision', shared_enterprise_manufacturing_preparation_versions.revis"
        "ion, 'series_id', shared_enterprise_manufacturing_preparation_versions.serie"
        "s_id, 'title', shared_enterprise_manufacturing_preparation_versions.title, '"
        "process_id', shared_enterprise_manufacturing_preparation_versions.process_id"
        ", 'process_revision', shared_enterprise_manufacturing_preparation_versions.p"
        "rocess_revision, 'operation_key', shared_enterprise_manufacturing_preparatio"
        "n_versions.operation_key, 'conditions', shared_enterprise_manufacturing_prep"
        "aration_versions.body['input']['conditions'], 'steps', (SELECT coalesce(json"
        "b_agg(jsonb_build_object('key', native_instruction_steps.value['key'], 'text"
        "', native_instruction_steps.value['text'], 'safety_notes', native_instructio"
        "n_steps.value['safety_notes'], 'parameters', (SELECT coalesce(jsonb_agg(json"
        "b_build_object('key', native_instruction_parameters.value['key'], 'unit', na"
        "tive_instruction_parameters.value['unit'], 'nominal', native_instruction_par"
        "ameters.value['nominal'], 'lower', native_instruction_parameters.value['lowe"
        "r'], 'upper', native_instruction_parameters.value['upper'], 'nature', native"
        "_instruction_parameters.value['nature'], 'condition', native_instruction_par"
        "ameters.value['condition']) ORDER BY native_instruction_parameters.ordinal),"
        ' jsonb_build_array()) AS coalesce_8 \nFROM jsonb_array_elements(coalesce(nat'
        "ive_instruction_steps.value['parameters'], CAST('[]' AS JSONB))) WITH ORDINA"
        'LITY AS native_instruction_parameters(value, ordinal))) ORDER BY native_inst'
        'ruction_steps.ordinal), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_arra'
        'y_elements(coalesce(shared_enterprise_manufacturing_preparation_versions.bod'
        "y['input']['steps'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_instruc"
        "tion_steps(value, ordinal)), 'checks', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('key', native_control_checks.value['key'], 'feature', native_contro"
        "l_checks.value['feature'], 'method', native_control_checks.value['method'], "
        "'frequency', native_control_checks.value['frequency'], 'sampling_method', na"
        "tive_control_checks.value['sampling_method'], 'reaction_plan', native_contro"
        "l_checks.value['reaction_plan'], 'responsible_role', native_control_checks.v"
        "alue['responsible_role'], 'criterion_key', native_control_checks.value['crit"
        "erion']['key'], 'criterion_unit', native_control_checks.value['criterion']['"
        "unit'], 'criterion_nominal', native_control_checks.value['criterion']['nomin"
        "al'], 'criterion_lower', native_control_checks.value['criterion']['lower'], "
        "'criterion_upper', native_control_checks.value['criterion']['upper'], 'crite"
        "rion_nature', native_control_checks.value['criterion']['nature']) ORDER BY n"
        'ative_control_checks.ordinal), jsonb_build_array()) AS coalesce_9 \nFROM jso'
        'nb_array_elements(coalesce(shared_enterprise_manufacturing_preparation_versi'
        "ons.body['input']['checks'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native"
        "_control_checks(value, ordinal)), 'declared_gaps', (SELECT coalesce(jsonb_ag"
        "g(jsonb_build_object('code', native_document_declared_gaps.value['code'], 'm"
        "essage', native_document_declared_gaps.value['message']) ORDER BY native_doc"
        'ument_declared_gaps.ordinal), jsonb_build_array()) AS coalesce_10 \nFROM jso'
        'nb_array_elements(coalesce(shared_enterprise_manufacturing_preparation_versi'
        "ons.body['gaps'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_document_d"
        "eclared_gaps(value, ordinal)), 'continuation_permission', 'not_evaluated'), "
        "'record_policy', '\u8be5\u6b63\u5f0f\u53d1\u5e03\u56fa\u5b9a\u5f15\u7528"
        '\u6b64\u6587\u6863\u7248\u672c\uff1b\u4e0d\u66ff\u4ee3\u539f\u751f\u9002'
        "\u7528\u6027\u6216\u7ee7\u7eed\u6267\u884c\u6838\u9a8c\u3002'), 'source_refs"
        "', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', e"
        "nterprise_reads_manufacturing_document.value['artifact_id'], 'version', ente"
        "rprise_reads_manufacturing_document.value['expected_revision']) ORDER BY ent"
        "erprise_reads_manufacturing_document.value ->> 'artifact_id', enterprise_rea"
        "ds_manufacturing_document.value ->> 'expected_revision'), jsonb_build_array("
        ')) AS coalesce_11 \nFROM jsonb_array_elements((SELECT shared_enterprise_manu'
        'facturing_preparation_versions.required_source_read_set || shared_enterprise'
        '_manufacturing_baseline_publications.required_source_read_set AS anon_2 \nFR'
        'OM shared_enterprise_manufacturing_preparation_versions JOIN shared_enterpri'
        'se_manufacturing_baseline_publications ON shared_enterprise_manufacturing_pu'
        'blication_documents.tenant_id = shared_enterprise_manufacturing_baseline_pub'
        'lications.tenant_id AND shared_enterprise_manufacturing_publication_document'
        's.category_id = shared_enterprise_manufacturing_baseline_publications.catego'
        'ry_id AND shared_enterprise_manufacturing_publication_documents.product_id ='
        ' shared_enterprise_manufacturing_baseline_publications.product_id AND shared'
        '_enterprise_manufacturing_publication_documents.project_id = shared_enterpri'
        'se_manufacturing_baseline_publications.project_id AND shared_enterprise_manu'
        'facturing_publication_documents.publication_id = shared_enterprise_manufactu'
        'ring_baseline_publications.id AND shared_enterprise_manufacturing_publicatio'
        'n_documents.publication_revision = shared_enterprise_manufacturing_baseline_'
        'publications.revision \nWHERE shared_enterprise_manufacturing_publication_do'
        'cuments.tenant_id = shared_enterprise_manufacturing_preparation_versions.ten'
        'ant_id AND shared_enterprise_manufacturing_publication_documents.category_id'
        ' = shared_enterprise_manufacturing_preparation_versions.category_id AND shar'
        'ed_enterprise_manufacturing_publication_documents.product_id = shared_enterp'
        'rise_manufacturing_preparation_versions.product_id AND shared_enterprise_man'
        'ufacturing_publication_documents.project_id = shared_enterprise_manufacturin'
        'g_preparation_versions.project_id AND shared_enterprise_manufacturing_public'
        'ation_documents.document_id = shared_enterprise_manufacturing_preparation_ve'
        'rsions.id AND shared_enterprise_manufacturing_publication_documents.document'
        '_kind = shared_enterprise_manufacturing_preparation_versions.kind AND shared'
        '_enterprise_manufacturing_publication_documents.document_revision = shared_e'
        'nterprise_manufacturing_preparation_versions.revision AND shared_enterprise_'
        'manufacturing_publication_documents.process_id = shared_enterprise_manufactu'
        'ring_preparation_versions.process_id AND shared_enterprise_manufacturing_pub'
        'lication_documents.process_revision = shared_enterprise_manufacturing_prepar'
        'ation_versions.process_revision AND shared_enterprise_manufacturing_publicat'
        'ion_documents.operation_key = shared_enterprise_manufacturing_preparation_ve'
        "rsions.operation_key)) AS enterprise_reads_manufacturing_document(value)), '"
        "record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_obje"
        "ct('object_id', shared_enterprise_manufacturing_publication_documents.id, 'k"
        "ind', 'manufacturing_document', 'facts', jsonb_build_object('record_kind', '"
        "published_manufacturing_document', 'status', shared_enterprise_manufacturing"
        "_baseline_publications.status, 'publication_id', shared_enterprise_manufactu"
        "ring_baseline_publications.id, 'publication_revision', shared_enterprise_man"
        "ufacturing_baseline_publications.revision, 'document', jsonb_build_object('d"
        "ocument_kind', shared_enterprise_manufacturing_preparation_versions.kind, 'd"
        "ocument_id', shared_enterprise_manufacturing_preparation_versions.id, 'docum"
        "ent_revision', shared_enterprise_manufacturing_preparation_versions.revision"
        ", 'series_id', shared_enterprise_manufacturing_preparation_versions.series_i"
        "d, 'title', shared_enterprise_manufacturing_preparation_versions.title, 'pro"
        "cess_id', shared_enterprise_manufacturing_preparation_versions.process_id, '"
        "process_revision', shared_enterprise_manufacturing_preparation_versions.proc"
        "ess_revision, 'operation_key', shared_enterprise_manufacturing_preparation_v"
        "ersions.operation_key, 'conditions', shared_enterprise_manufacturing_prepara"
        "tion_versions.body['input']['conditions'], 'steps', (SELECT coalesce(jsonb_a"
        "gg(jsonb_build_object('key', native_instruction_steps.value['key'], 'text', "
        "native_instruction_steps.value['text'], 'safety_notes', native_instruction_s"
        "teps.value['safety_notes'], 'parameters', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('key', native_instruction_parameters.value['key'], 'unit', nativ"
        "e_instruction_parameters.value['unit'], 'nominal', native_instruction_parame"
        "ters.value['nominal'], 'lower', native_instruction_parameters.value['lower']"
        ", 'upper', native_instruction_parameters.value['upper'], 'nature', native_in"
        "struction_parameters.value['nature'], 'condition', native_instruction_parame"
        "ters.value['condition']) ORDER BY native_instruction_parameters.ordinal), js"
        'onb_build_array()) AS coalesce_8 \nFROM jsonb_array_elements(coalesce(native'
        "_instruction_steps.value['parameters'], CAST('[]' AS JSONB))) WITH ORDINALIT"
        'Y AS native_instruction_parameters(value, ordinal))) ORDER BY native_instruc'
        'tion_steps.ordinal), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_e'
        "lements(coalesce(shared_enterprise_manufacturing_preparation_versions.body['"
        "input']['steps'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_instructio"
        "n_steps(value, ordinal)), 'checks', (SELECT coalesce(jsonb_agg(jsonb_build_o"
        "bject('key', native_control_checks.value['key'], 'feature', native_control_c"
        "hecks.value['feature'], 'method', native_control_checks.value['method'], 'fr"
        "equency', native_control_checks.value['frequency'], 'sampling_method', nativ"
        "e_control_checks.value['sampling_method'], 'reaction_plan', native_control_c"
        "hecks.value['reaction_plan'], 'responsible_role', native_control_checks.valu"
        "e['responsible_role'], 'criterion_key', native_control_checks.value['criteri"
        "on']['key'], 'criterion_unit', native_control_checks.value['criterion']['uni"
        "t'], 'criterion_nominal', native_control_checks.value['criterion']['nominal'"
        "], 'criterion_lower', native_control_checks.value['criterion']['lower'], 'cr"
        "iterion_upper', native_control_checks.value['criterion']['upper'], 'criterio"
        "n_nature', native_control_checks.value['criterion']['nature']) ORDER BY nati"
        've_control_checks.ordinal), jsonb_build_array()) AS coalesce_9 \nFROM jsonb_'
        'array_elements(coalesce(shared_enterprise_manufacturing_preparation_versions'
        ".body['input']['checks'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_co"
        "ntrol_checks(value, ordinal)), 'declared_gaps', (SELECT coalesce(jsonb_agg(j"
        "sonb_build_object('code', native_document_declared_gaps.value['code'], 'mess"
        "age', native_document_declared_gaps.value['message']) ORDER BY native_docume"
        'nt_declared_gaps.ordinal), jsonb_build_array()) AS coalesce_10 \nFROM jsonb_'
        'array_elements(coalesce(shared_enterprise_manufacturing_preparation_versions'
        ".body['gaps'], CAST('[]' AS JSONB))) WITH ORDINALITY AS native_document_decl"
        "ared_gaps(value, ordinal)), 'continuation_permission', 'not_evaluated'), 're"
        "cord_policy', '\u8be5\u6b63\u5f0f\u53d1\u5e03\u56fa\u5b9a\u5f15\u7528\u6b64"
        '\u6587\u6863\u7248\u672c\uff1b\u4e0d\u66ff\u4ee3\u539f\u751f\u9002\u7528'
        "\u6027\u6216\u7ee7\u7eed\u6267\u884c\u6838\u9a8c\u3002'), 'source_refs', (SE"
        "LECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpr"
        "ise_reads_manufacturing_document.value['artifact_id'], 'version', enterprise"
        "_reads_manufacturing_document.value['expected_revision']) ORDER BY enterpris"
        "e_reads_manufacturing_document.value ->> 'artifact_id', enterprise_reads_man"
        "ufacturing_document.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_11 \nFROM jsonb_array_elements((SELECT shared_enterprise_manufactur'
        'ing_preparation_versions.required_source_read_set || shared_enterprise_manuf'
        'acturing_baseline_publications.required_source_read_set AS anon_2 \nFROM sha'
        'red_enterprise_manufacturing_preparation_versions JOIN shared_enterprise_man'
        'ufacturing_baseline_publications ON shared_enterprise_manufacturing_publicat'
        'ion_documents.tenant_id = shared_enterprise_manufacturing_baseline_publicati'
        'ons.tenant_id AND shared_enterprise_manufacturing_publication_documents.cate'
        'gory_id = shared_enterprise_manufacturing_baseline_publications.category_id '
        'AND shared_enterprise_manufacturing_publication_documents.product_id = share'
        'd_enterprise_manufacturing_baseline_publications.product_id AND shared_enter'
        'prise_manufacturing_publication_documents.project_id = shared_enterprise_man'
        'ufacturing_baseline_publications.project_id AND shared_enterprise_manufactur'
        'ing_publication_documents.publication_id = shared_enterprise_manufacturing_b'
        'aseline_publications.id AND shared_enterprise_manufacturing_publication_docu'
        'ments.publication_revision = shared_enterprise_manufacturing_baseline_public'
        'ations.revision \nWHERE shared_enterprise_manufacturing_publication_document'
        's.tenant_id = shared_enterprise_manufacturing_preparation_versions.tenant_id'
        ' AND shared_enterprise_manufacturing_publication_documents.category_id = sha'
        'red_enterprise_manufacturing_preparation_versions.category_id AND shared_ent'
        'erprise_manufacturing_publication_documents.product_id = shared_enterprise_m'
        'anufacturing_preparation_versions.product_id AND shared_enterprise_manufactu'
        'ring_publication_documents.project_id = shared_enterprise_manufacturing_prep'
        'aration_versions.project_id AND shared_enterprise_manufacturing_publication_'
        'documents.document_id = shared_enterprise_manufacturing_preparation_versions'
        '.id AND shared_enterprise_manufacturing_publication_documents.document_kind '
        '= shared_enterprise_manufacturing_preparation_versions.kind AND shared_enter'
        'prise_manufacturing_publication_documents.document_revision = shared_enterpr'
        'ise_manufacturing_preparation_versions.revision AND shared_enterprise_manufa'
        'cturing_publication_documents.process_id = shared_enterprise_manufacturing_p'
        'reparation_versions.process_id AND shared_enterprise_manufacturing_publicati'
        'on_documents.process_revision = shared_enterprise_manufacturing_preparation_'
        'versions.process_revision AND shared_enterprise_manufacturing_publication_do'
        'cuments.operation_key = shared_enterprise_manufacturing_preparation_versions'
        ".operation_key)) AS enterprise_reads_manufacturing_document(value)), 'record"
        "_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, shared"
        "_enterprise_manufacturing_baseline_publications.visibility != 'category' OR "
        "coalesce(shared_enterprise_projects.visibility != 'category', false) OR coal"
        "esce(shared_enterprise_products.visibility != 'category', false) OR (EXISTS "
        '(SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterprise_manufacturin'
        'g_preparation_versions.required_source_read_set || shared_enterprise_manufac'
        'turing_baseline_publications.required_source_read_set AS anon_2 \nFROM share'
        'd_enterprise_manufacturing_preparation_versions JOIN shared_enterprise_manuf'
        'acturing_baseline_publications ON shared_enterprise_manufacturing_publicatio'
        'n_documents.tenant_id = shared_enterprise_manufacturing_baseline_publication'
        's.tenant_id AND shared_enterprise_manufacturing_publication_documents.catego'
        'ry_id = shared_enterprise_manufacturing_baseline_publications.category_id AN'
        'D shared_enterprise_manufacturing_publication_documents.product_id = shared_'
        'enterprise_manufacturing_baseline_publications.product_id AND shared_enterpr'
        'ise_manufacturing_publication_documents.project_id = shared_enterprise_manuf'
        'acturing_baseline_publications.project_id AND shared_enterprise_manufacturin'
        'g_publication_documents.publication_id = shared_enterprise_manufacturing_bas'
        'eline_publications.id AND shared_enterprise_manufacturing_publication_docume'
        'nts.publication_revision = shared_enterprise_manufacturing_baseline_publicat'
        'ions.revision \nWHERE shared_enterprise_manufacturing_publication_documents.'
        'tenant_id = shared_enterprise_manufacturing_preparation_versions.tenant_id A'
        'ND shared_enterprise_manufacturing_publication_documents.category_id = share'
        'd_enterprise_manufacturing_preparation_versions.category_id AND shared_enter'
        'prise_manufacturing_publication_documents.product_id = shared_enterprise_man'
        'ufacturing_preparation_versions.product_id AND shared_enterprise_manufacturi'
        'ng_publication_documents.project_id = shared_enterprise_manufacturing_prepar'
        'ation_versions.project_id AND shared_enterprise_manufacturing_publication_do'
        'cuments.document_id = shared_enterprise_manufacturing_preparation_versions.i'
        'd AND shared_enterprise_manufacturing_publication_documents.document_kind = '
        'shared_enterprise_manufacturing_preparation_versions.kind AND shared_enterpr'
        'ise_manufacturing_publication_documents.document_revision = shared_enterpris'
        'e_manufacturing_preparation_versions.revision AND shared_enterprise_manufact'
        'uring_publication_documents.process_id = shared_enterprise_manufacturing_pre'
        'paration_versions.process_id AND shared_enterprise_manufacturing_publication'
        '_documents.process_revision = shared_enterprise_manufacturing_preparation_ve'
        'rsions.process_revision AND shared_enterprise_manufacturing_publication_docu'
        'ments.operation_key = shared_enterprise_manufacturing_preparation_versions.o'
        'peration_key)) AS enterprise_reads_manufacturing_document(value) JOIN enterp'
        'rise_authoritative_artifacts_b87857c50472d0c4 ON enterprise_authoritative_ar'
        'tifacts_b87857c50472d0c4.tenant_id = shared_enterprise_manufacturing_publica'
        'tion_documents.tenant_id AND enterprise_authoritative_artifacts_b87857c50472'
        "d0c4.source_id = CAST((enterprise_reads_manufacturing_document.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_b87857c50472"
        'd0c4.private)) OR shared_enterprise_manufacturing_preparation_versions.visib'
        "ility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements"
        '((SELECT shared_enterprise_manufacturing_preparation_versions.required_sourc'
        'e_read_set || shared_enterprise_manufacturing_baseline_publications.required'
        '_source_read_set AS anon_2 \nFROM shared_enterprise_manufacturing_preparatio'
        'n_versions JOIN shared_enterprise_manufacturing_baseline_publications ON sha'
        'red_enterprise_manufacturing_publication_documents.tenant_id = shared_enterp'
        'rise_manufacturing_baseline_publications.tenant_id AND shared_enterprise_man'
        'ufacturing_publication_documents.category_id = shared_enterprise_manufacturi'
        'ng_baseline_publications.category_id AND shared_enterprise_manufacturing_pub'
        'lication_documents.product_id = shared_enterprise_manufacturing_baseline_pub'
        'lications.product_id AND shared_enterprise_manufacturing_publication_documen'
        'ts.project_id = shared_enterprise_manufacturing_baseline_publications.projec'
        't_id AND shared_enterprise_manufacturing_publication_documents.publication_i'
        'd = shared_enterprise_manufacturing_baseline_publications.id AND shared_ente'
        'rprise_manufacturing_publication_documents.publication_revision = shared_ent'
        'erprise_manufacturing_baseline_publications.revision \nWHERE shared_enterpri'
        'se_manufacturing_publication_documents.tenant_id = shared_enterprise_manufac'
        'turing_preparation_versions.tenant_id AND shared_enterprise_manufacturing_pu'
        'blication_documents.category_id = shared_enterprise_manufacturing_preparatio'
        'n_versions.category_id AND shared_enterprise_manufacturing_publication_docum'
        'ents.product_id = shared_enterprise_manufacturing_preparation_versions.produ'
        'ct_id AND shared_enterprise_manufacturing_publication_documents.project_id ='
        ' shared_enterprise_manufacturing_preparation_versions.project_id AND shared_'
        'enterprise_manufacturing_publication_documents.document_id = shared_enterpri'
        'se_manufacturing_preparation_versions.id AND shared_enterprise_manufacturing'
        '_publication_documents.document_kind = shared_enterprise_manufacturing_prepa'
        'ration_versions.kind AND shared_enterprise_manufacturing_publication_documen'
        'ts.document_revision = shared_enterprise_manufacturing_preparation_versions.'
        'revision AND shared_enterprise_manufacturing_publication_documents.process_i'
        'd = shared_enterprise_manufacturing_preparation_versions.process_id AND shar'
        'ed_enterprise_manufacturing_publication_documents.process_revision = shared_'
        'enterprise_manufacturing_preparation_versions.process_revision AND shared_en'
        'terprise_manufacturing_publication_documents.operation_key = shared_enterpri'
        'se_manufacturing_preparation_versions.operation_key)) AS enterprise_reads_ma'
        'nufacturing_document(value) JOIN enterprise_authoritative_artifacts_b87857c5'
        '0472d0c4 ON enterprise_authoritative_artifacts_b87857c50472d0c4.tenant_id = '
        'shared_enterprise_manufacturing_publication_documents.tenant_id AND enterpri'
        'se_authoritative_artifacts_b87857c50472d0c4.source_id = CAST((enterprise_rea'
        "ds_manufacturing_document.value ->> 'artifact_id') AS UUID) \nWHERE enterpri"
        'se_authoritative_artifacts_b87857c50472d0c4.customer_original) AS customer_o'
        'riginal, shared_enterprise_manufacturing_publication_currents.version_id = s'
        'hared_enterprise_manufacturing_baseline_publications.id AS is_current, share'
        'd_enterprise_manufacturing_publication_documents.created_at AS created_at, C'
        'AST(NULL AS UUID) AS original_id, shared_enterprise_manufacturing_publicatio'
        'n_documents.id AS object_id, (SELECT coalesce(array_agg(enterprise_authorita'
        'tive_artifacts_b87857c50472d0c4.original_id), ARRAY[]::UUID[]) AS coalesce_1'
        '2 \nFROM jsonb_array_elements((SELECT shared_enterprise_manufacturing_prepar'
        'ation_versions.required_source_read_set || shared_enterprise_manufacturing_b'
        'aseline_publications.required_source_read_set AS anon_2 \nFROM shared_enterp'
        'rise_manufacturing_preparation_versions JOIN shared_enterprise_manufacturing'
        '_baseline_publications ON shared_enterprise_manufacturing_publication_docume'
        'nts.tenant_id = shared_enterprise_manufacturing_baseline_publications.tenant'
        '_id AND shared_enterprise_manufacturing_publication_documents.category_id = '
        'shared_enterprise_manufacturing_baseline_publications.category_id AND shared'
        '_enterprise_manufacturing_publication_documents.product_id = shared_enterpri'
        'se_manufacturing_baseline_publications.product_id AND shared_enterprise_manu'
        'facturing_publication_documents.project_id = shared_enterprise_manufacturing'
        '_baseline_publications.project_id AND shared_enterprise_manufacturing_public'
        'ation_documents.publication_id = shared_enterprise_manufacturing_baseline_pu'
        'blications.id AND shared_enterprise_manufacturing_publication_documents.publ'
        'ication_revision = shared_enterprise_manufacturing_baseline_publications.rev'
        'ision \nWHERE shared_enterprise_manufacturing_publication_documents.tenant_i'
        'd = shared_enterprise_manufacturing_preparation_versions.tenant_id AND share'
        'd_enterprise_manufacturing_publication_documents.category_id = shared_enterp'
        'rise_manufacturing_preparation_versions.category_id AND shared_enterprise_ma'
        'nufacturing_publication_documents.product_id = shared_enterprise_manufacturi'
        'ng_preparation_versions.product_id AND shared_enterprise_manufacturing_publi'
        'cation_documents.project_id = shared_enterprise_manufacturing_preparation_ve'
        'rsions.project_id AND shared_enterprise_manufacturing_publication_documents.'
        'document_id = shared_enterprise_manufacturing_preparation_versions.id AND sh'
        'ared_enterprise_manufacturing_publication_documents.document_kind = shared_e'
        'nterprise_manufacturing_preparation_versions.kind AND shared_enterprise_manu'
        'facturing_publication_documents.document_revision = shared_enterprise_manufa'
        'cturing_preparation_versions.revision AND shared_enterprise_manufacturing_pu'
        'blication_documents.process_id = shared_enterprise_manufacturing_preparation'
        '_versions.process_id AND shared_enterprise_manufacturing_publication_documen'
        'ts.process_revision = shared_enterprise_manufacturing_preparation_versions.p'
        'rocess_revision AND shared_enterprise_manufacturing_publication_documents.op'
        'eration_key = shared_enterprise_manufacturing_preparation_versions.operation'
        '_key)) AS enterprise_reads_manufacturing_document(value) JOIN enterprise_aut'
        'horitative_artifacts_b87857c50472d0c4 ON enterprise_authoritative_artifacts_'
        'b87857c50472d0c4.tenant_id = shared_enterprise_manufacturing_publication_doc'
        'uments.tenant_id AND enterprise_authoritative_artifacts_b87857c50472d0c4.sou'
        "rce_id = CAST((enterprise_reads_manufacturing_document.value ->> 'artifact_i"
        "d') AS UUID) \nWHERE enterprise_authoritative_artifacts_b87857c50472d0c4.ori"
        'ginal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM js'
        'onb_array_elements((SELECT shared_enterprise_manufacturing_preparation_versi'
        'ons.required_source_read_set || shared_enterprise_manufacturing_baseline_pub'
        'lications.required_source_read_set AS anon_2 \nFROM shared_enterprise_manufa'
        'cturing_preparation_versions JOIN shared_enterprise_manufacturing_baseline_p'
        'ublications ON shared_enterprise_manufacturing_publication_documents.tenant_'
        'id = shared_enterprise_manufacturing_baseline_publications.tenant_id AND sha'
        'red_enterprise_manufacturing_publication_documents.category_id = shared_ente'
        'rprise_manufacturing_baseline_publications.category_id AND shared_enterprise'
        '_manufacturing_publication_documents.product_id = shared_enterprise_manufact'
        'uring_baseline_publications.product_id AND shared_enterprise_manufacturing_p'
        'ublication_documents.project_id = shared_enterprise_manufacturing_baseline_p'
        'ublications.project_id AND shared_enterprise_manufacturing_publication_docum'
        'ents.publication_id = shared_enterprise_manufacturing_baseline_publications.'
        'id AND shared_enterprise_manufacturing_publication_documents.publication_rev'
        'ision = shared_enterprise_manufacturing_baseline_publications.revision \nWHE'
        'RE shared_enterprise_manufacturing_publication_documents.tenant_id = shared_'
        'enterprise_manufacturing_preparation_versions.tenant_id AND shared_enterpris'
        'e_manufacturing_publication_documents.category_id = shared_enterprise_manufa'
        'cturing_preparation_versions.category_id AND shared_enterprise_manufacturing'
        '_publication_documents.product_id = shared_enterprise_manufacturing_preparat'
        'ion_versions.product_id AND shared_enterprise_manufacturing_publication_docu'
        'ments.project_id = shared_enterprise_manufacturing_preparation_versions.proj'
        'ect_id AND shared_enterprise_manufacturing_publication_documents.document_id'
        ' = shared_enterprise_manufacturing_preparation_versions.id AND shared_enterp'
        'rise_manufacturing_publication_documents.document_kind = shared_enterprise_m'
        'anufacturing_preparation_versions.kind AND shared_enterprise_manufacturing_p'
        'ublication_documents.document_revision = shared_enterprise_manufacturing_pre'
        'paration_versions.revision AND shared_enterprise_manufacturing_publication_d'
        'ocuments.process_id = shared_enterprise_manufacturing_preparation_versions.p'
        'rocess_id AND shared_enterprise_manufacturing_publication_documents.process_'
        'revision = shared_enterprise_manufacturing_preparation_versions.process_revi'
        'sion AND shared_enterprise_manufacturing_publication_documents.operation_key'
        ' = shared_enterprise_manufacturing_preparation_versions.operation_key)) AS e'
        'nterprise_reads_manufacturing_document(value) JOIN enterprise_authoritative_'
        'artifacts_b87857c50472d0c4 ON enterprise_authoritative_artifacts_b87857c5047'
        '2d0c4.tenant_id = shared_enterprise_manufacturing_publication_documents.tena'
        'nt_id AND enterprise_authoritative_artifacts_b87857c50472d0c4.source_id = CA'
        "ST((enterprise_reads_manufacturing_document.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_b87857c50472d0c4.source_revisio'
        "n != CAST((enterprise_reads_manufacturing_document.value ->> 'expected_revis"
        "ion') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_st"
        'atus \nFROM shared_enterprise_manufacturing_publication_documents JOIN share'
        'd_enterprise_projects ON shared_enterprise_projects.tenant_id = shared_enter'
        'prise_manufacturing_publication_documents.tenant_id AND shared_enterprise_pr'
        'ojects.product_id = shared_enterprise_manufacturing_publication_documents.pr'
        'oduct_id AND shared_enterprise_projects.id = shared_enterprise_manufacturing'
        '_publication_documents.project_id AND shared_enterprise_projects.category_id'
        ' = shared_enterprise_manufacturing_publication_documents.category_id JOIN sh'
        'ared_enterprise_products ON shared_enterprise_products.tenant_id = shared_en'
        'terprise_manufacturing_publication_documents.tenant_id AND shared_enterprise'
        '_products.id = shared_enterprise_manufacturing_publication_documents.product'
        '_id AND shared_enterprise_products.category_id = shared_enterprise_manufactu'
        'ring_publication_documents.category_id JOIN shared_enterprise_manufacturing_'
        'preparation_versions ON shared_enterprise_manufacturing_publication_document'
        's.tenant_id = shared_enterprise_manufacturing_preparation_versions.tenant_id'
        ' AND shared_enterprise_manufacturing_publication_documents.category_id = sha'
        'red_enterprise_manufacturing_preparation_versions.category_id AND shared_ent'
        'erprise_manufacturing_publication_documents.product_id = shared_enterprise_m'
        'anufacturing_preparation_versions.product_id AND shared_enterprise_manufactu'
        'ring_publication_documents.project_id = shared_enterprise_manufacturing_prep'
        'aration_versions.project_id AND shared_enterprise_manufacturing_publication_'
        'documents.document_id = shared_enterprise_manufacturing_preparation_versions'
        '.id AND shared_enterprise_manufacturing_publication_documents.document_kind '
        '= shared_enterprise_manufacturing_preparation_versions.kind AND shared_enter'
        'prise_manufacturing_publication_documents.document_revision = shared_enterpr'
        'ise_manufacturing_preparation_versions.revision AND shared_enterprise_manufa'
        'cturing_publication_documents.process_id = shared_enterprise_manufacturing_p'
        'reparation_versions.process_id AND shared_enterprise_manufacturing_publicati'
        'on_documents.process_revision = shared_enterprise_manufacturing_preparation_'
        'versions.process_revision AND shared_enterprise_manufacturing_publication_do'
        'cuments.operation_key = shared_enterprise_manufacturing_preparation_versions'
        '.operation_key JOIN shared_enterprise_manufacturing_baseline_publications ON'
        ' shared_enterprise_manufacturing_publication_documents.tenant_id = shared_en'
        'terprise_manufacturing_baseline_publications.tenant_id AND shared_enterprise'
        '_manufacturing_publication_documents.category_id = shared_enterprise_manufac'
        'turing_baseline_publications.category_id AND shared_enterprise_manufacturing'
        '_publication_documents.product_id = shared_enterprise_manufacturing_baseline'
        '_publications.product_id AND shared_enterprise_manufacturing_publication_doc'
        'uments.project_id = shared_enterprise_manufacturing_baseline_publications.pr'
        'oject_id AND shared_enterprise_manufacturing_publication_documents.publicati'
        'on_id = shared_enterprise_manufacturing_baseline_publications.id AND shared_'
        'enterprise_manufacturing_publication_documents.publication_revision = shared'
        '_enterprise_manufacturing_baseline_publications.revision JOIN shared_enterpr'
        'ise_manufacturing_publication_currents ON shared_enterprise_manufacturing_pu'
        'blication_currents.tenant_id = shared_enterprise_manufacturing_baseline_publ'
        'ications.tenant_id AND shared_enterprise_manufacturing_publication_currents.'
        'category_id = shared_enterprise_manufacturing_baseline_publications.category'
        '_id AND shared_enterprise_manufacturing_publication_currents.product_id = sh'
        'ared_enterprise_manufacturing_baseline_publications.product_id AND shared_en'
        'terprise_manufacturing_publication_currents.project_id = shared_enterprise_m'
        'anufacturing_baseline_publications.project_id AND shared_enterprise_manufact'
        'uring_publication_currents.series_id = shared_enterprise_manufacturing_basel'
        'ine_publications.series_id \nWHERE shared_enterprise_manufacturing_publicati'
        "on_documents.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)"
        ", '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT"
        ' shared_enterprise_manufacturing_preparation_versions.required_source_read_s'
        'et || shared_enterprise_manufacturing_baseline_publications.required_source_'
        'read_set AS anon_2 \nFROM shared_enterprise_manufacturing_preparation_versio'
        'ns JOIN shared_enterprise_manufacturing_baseline_publications ON shared_ente'
        'rprise_manufacturing_publication_documents.tenant_id = shared_enterprise_man'
        'ufacturing_baseline_publications.tenant_id AND shared_enterprise_manufacturi'
        'ng_publication_documents.category_id = shared_enterprise_manufacturing_basel'
        'ine_publications.category_id AND shared_enterprise_manufacturing_publication'
        '_documents.product_id = shared_enterprise_manufacturing_baseline_publication'
        's.product_id AND shared_enterprise_manufacturing_publication_documents.proje'
        'ct_id = shared_enterprise_manufacturing_baseline_publications.project_id AND'
        ' shared_enterprise_manufacturing_publication_documents.publication_id = shar'
        'ed_enterprise_manufacturing_baseline_publications.id AND shared_enterprise_m'
        'anufacturing_publication_documents.publication_revision = shared_enterprise_'
        'manufacturing_baseline_publications.revision \nWHERE shared_enterprise_manuf'
        'acturing_publication_documents.tenant_id = shared_enterprise_manufacturing_p'
        'reparation_versions.tenant_id AND shared_enterprise_manufacturing_publicatio'
        'n_documents.category_id = shared_enterprise_manufacturing_preparation_versio'
        'ns.category_id AND shared_enterprise_manufacturing_publication_documents.pro'
        'duct_id = shared_enterprise_manufacturing_preparation_versions.product_id AN'
        'D shared_enterprise_manufacturing_publication_documents.project_id = shared_'
        'enterprise_manufacturing_preparation_versions.project_id AND shared_enterpri'
        'se_manufacturing_publication_documents.document_id = shared_enterprise_manuf'
        'acturing_preparation_versions.id AND shared_enterprise_manufacturing_publica'
        'tion_documents.document_kind = shared_enterprise_manufacturing_preparation_v'
        'ersions.kind AND shared_enterprise_manufacturing_publication_documents.docum'
        'ent_revision = shared_enterprise_manufacturing_preparation_versions.revision'
        ' AND shared_enterprise_manufacturing_publication_documents.process_id = shar'
        'ed_enterprise_manufacturing_preparation_versions.process_id AND shared_enter'
        'prise_manufacturing_publication_documents.process_revision = shared_enterpri'
        'se_manufacturing_preparation_versions.process_revision AND shared_enterprise'
        '_manufacturing_publication_documents.operation_key = shared_enterprise_manuf'
        'acturing_preparation_versions.operation_key)) AS enterprise_reads_manufactur'
        'ing_document(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authorit'
        'ative_artifacts_b87857c50472d0c4 \nWHERE enterprise_authoritative_artifacts_'
        'b87857c50472d0c4.tenant_id = shared_enterprise_manufacturing_publication_doc'
        'uments.tenant_id AND enterprise_authoritative_artifacts_b87857c50472d0c4.sou'
        "rce_id = CAST((enterprise_reads_manufacturing_document.value ->> 'artifact_i"
        "d') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_"
        'sources_b87857c50472d0c4 \nWHERE authoritative_enterprise_sources_b87857c504'
        '72d0c4.tenant_id = t AND authoritative_enterprise_sources_b87857c50472d0c4.c'
        'ategory_id = c AND CAST(authoritative_enterprise_sources_b87857c50472d0c4.so'
        "urce_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_"
        "sources_b87857c50472d0c4.source_revision AS TEXT) = expected->>'source_revis"
        "ion' AND authoritative_enterprise_sources_b87857c50472d0c4.content_hash = ex"
        "pected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'verification_handof"
        "f' THEN\n  WITH enterprise_authoritative_artifacts_13192f369ba42d6a AS \n(SE"
        "LECT 'artifact' AS source_type, artifact_versions.id AS source_id, artifact_"
        'versions.tenant_id AS tenant_id, artifact_versions.category_id AS category_i'
        'd, artifact_versions.product_id AS product_id, CAST(NULL AS UUID) AS project'
        '_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_'
        'id, artifact_versions.revision AS source_revision, artifact_versions.title A'
        'S title, artifact_versions.content_hash AS content_hash, artifact_versions.c'
        "ontent AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, ar"
        "tifact_versions.visibility != 'category' OR coalesce(products.visibility != "
        "'category', false) OR coalesce(uploaded_originals.visibility != 'category', "
        'false) AS private, artifact_versions.original_id IS NOT NULL AS customer_ori'
        'ginal, true AS is_current, artifact_versions.created_at AS created_at, artif'
        'act_versions.original_id AS original_id, artifact_versions.id AS object_id, '
        'CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_ve'
        "rsions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS r"
        'ead_basis_status \nFROM artifact_versions LEFT OUTER JOIN products ON produc'
        'ts.tenant_id = artifact_versions.tenant_id AND products.id = artifact_versio'
        'ns.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenan'
        't_id = artifact_versions.tenant_id AND uploaded_originals.id = artifact_vers'
        'ions.original_id AND uploaded_originals.category_id = artifact_versions.cate'
        'gory_id AND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_vers'
        'ions.product_id LEFT OUTER JOIN original_security ON original_security.tenan'
        't_id = uploaded_originals.tenant_id AND original_security.original_id = uplo'
        'aded_originals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status ="
        " 'active' AND artifact_versions.category_id IS NOT NULL AND (artifact_versio"
        'ns.product_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.ori'
        'ginal_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals'
        ".status = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original"
        "_security.source_state = 'active' AND original_security.disposition = 'activ"
        "e' AND original_security.current_request_id IS NOT NULL)), \nshared_enterpri"
        'se_verification_handoff_facts AS MATERIALIZED \n(SELECT verification_handoff'
        '_facts.operation AS operation, verification_handoff_facts.status AS status, '
        'verification_handoff_facts.next_request_version_id AS next_request_version_i'
        'd, verification_handoff_facts.next_request_revision AS next_request_revision'
        ', verification_handoff_facts.input_snapshot AS input_snapshot, verification_'
        'handoff_facts.kernel_event AS kernel_event, verification_handoff_facts.inten'
        't_digest AS intent_digest, verification_handoff_facts.reason AS reason, veri'
        'fication_handoff_facts.product_id AS product_id, verification_handoff_facts.'
        'project_id AS project_id, verification_handoff_facts.request_id AS request_i'
        'd, verification_handoff_facts.request_version_id AS request_version_id, veri'
        'fication_handoff_facts.request_revision AS request_revision, verification_ha'
        'ndoff_facts.owner_id AS owner_id, verification_handoff_facts.visibility AS v'
        'isibility, verification_handoff_facts.revision AS revision, verification_han'
        'doff_facts.sources AS sources, verification_handoff_facts.required_source_re'
        'ad_set AS required_source_read_set, verification_handoff_facts.source_basis '
        'AS source_basis, verification_handoff_facts.authority_snapshot AS authority_'
        'snapshot, verification_handoff_facts.snapshot_sha256 AS snapshot_sha256, ver'
        'ification_handoff_facts.id AS id, verification_handoff_facts.tenant_id AS te'
        'nant_id, verification_handoff_facts.created_at AS created_at, verification_h'
        'andoff_facts.category_id AS category_id \nFROM verification_handoff_facts \n'
        "WHERE verification_handoff_facts.tenant_id = CAST(nullif(current_setting('pd"
        "os.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIA"
        'LIZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS owne'
        'r_id, projects.name AS name, projects.purpose AS purpose, projects.scope AS '
        'scope, projects.visibility AS visibility, projects.status AS status, project'
        's.revision AS revision, projects.current_plan_id AS current_plan_id, project'
        's.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projects.'
        'g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id AS t'
        'enant_id, projects.created_at AS created_at, projects.category_id AS categor'
        'y_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS MA"
        'TERIALIZED \n(SELECT products.name AS name, products.purpose AS purpose, pro'
        'ducts.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, pro'
        'ducts.status AS status, products.owner_id AS owner_id, products.parent_produ'
        'ct_id AS parent_product_id, products.category_id AS category_id, products.vi'
        'sibility AS visibility, products.target_price AS target_price, products.targ'
        'et_price_currency AS target_price_currency, products.target_price_basis AS t'
        'arget_price_basis, products.target_price_includes_tax AS target_price_includ'
        'es_tax, products.target_price_as_of AS target_price_as_of, products.id AS id'
        ', products.tenant_id AS tenant_id, products.created_at AS created_at \nFROM '
        "products \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.tena"
        "nt_id', true), '') AS UUID)), \nshared_enterprise_verification_formal_reques"
        'ts AS MATERIALIZED \n(SELECT verification_formal_requests.product_id AS prod'
        'uct_id, verification_formal_requests.project_id AS project_id, verification_'
        'formal_requests.build_id AS build_id, verification_formal_requests.build_rev'
        'ision AS build_revision, verification_formal_requests.request_id AS request_'
        'id, verification_formal_requests.revision AS revision, verification_formal_r'
        'equests.previous_request_id AS previous_request_id, verification_formal_requ'
        'ests.previous_revision AS previous_revision, verification_formal_requests.ow'
        'ner_id AS owner_id, verification_formal_requests.visibility AS visibility, v'
        'erification_formal_requests.status AS status, verification_formal_requests.o'
        'peration AS operation, verification_formal_requests.preparation_id AS prepar'
        'ation_id, verification_formal_requests.preparation_revision AS preparation_r'
        'evision, verification_formal_requests.preparation_sha256 AS preparation_sha2'
        '56, verification_formal_requests.purpose AS purpose, verification_formal_req'
        'uests.request_snapshot AS request_snapshot, verification_formal_requests.inp'
        'ut_snapshot AS input_snapshot, verification_formal_requests.snapshot_sha256 '
        'AS snapshot_sha256, verification_formal_requests.sources AS sources, verific'
        'ation_formal_requests.required_source_read_set AS required_source_read_set, '
        'verification_formal_requests.authority_snapshot AS authority_snapshot, verif'
        'ication_formal_requests.intent_digest AS intent_digest, verification_formal_'
        'requests.reason AS reason, verification_formal_requests.id AS id, verificati'
        'on_formal_requests.tenant_id AS tenant_id, verification_formal_requests.crea'
        'ted_at AS created_at, verification_formal_requests.category_id AS category_i'
        'd \nFROM verification_formal_requests \nWHERE verification_formal_requests.t'
        "enant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)"
        '), \nshared_enterprise_verification_current_formal_requests AS MATERIALIZED '
        '\n(SELECT verification_current_formal_requests.product_id AS product_id, ver'
        'ification_current_formal_requests.request_id AS request_id, verification_cur'
        'rent_formal_requests.request_version_id AS request_version_id, verification_'
        'current_formal_requests.request_revision AS request_revision, verification_c'
        'urrent_formal_requests.id AS id, verification_current_formal_requests.tenant'
        '_id AS tenant_id, verification_current_formal_requests.created_at AS created'
        '_at, verification_current_formal_requests.category_id AS category_id \nFROM '
        'verification_current_formal_requests \nWHERE verification_current_formal_req'
        "uests.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') A"
        "S UUID)), \nauthoritative_enterprise_sources_13192f369ba42d6a AS \n(SELECT '"
        "verification_handoff' AS source_type, shared_enterprise_verification_handoff"
        '_facts.id AS source_id, shared_enterprise_verification_handoff_facts.tenant_'
        'id AS tenant_id, shared_enterprise_verification_handoff_facts.category_id AS'
        ' category_id, shared_enterprise_verification_handoff_facts.product_id AS pro'
        'duct_id, shared_enterprise_verification_handoff_facts.project_id AS project_'
        'id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_verification_handof'
        'f_facts.owner_id AS owner_id, shared_enterprise_verification_handoff_facts.r'
        "evision AS source_revision, '\u5b9e\u7269\u9a8c\u8bc1\u4ea4\u63a5 \xb7 ' || "
        'CAST(shared_enterprise_verification_handoff_facts.request_id AS TEXT) AS tit'
        "le, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', share"
        "d_enterprise_verification_handoff_facts.request_id, 'kind', 'verification_ha"
        "ndoff', 'facts', jsonb_build_object('record_kind', 'physical_verification_ha"
        "ndoff', 'operation', shared_enterprise_verification_handoff_facts.operation,"
        " 'status_as_recorded', shared_enterprise_verification_handoff_facts.status, "
        "'request_id', shared_enterprise_verification_handoff_facts.request_id, 'requ"
        "est_version_id', shared_enterprise_verification_handoff_facts.request_versio"
        "n_id, 'request_revision', shared_enterprise_verification_handoff_facts.reque"
        "st_revision, 'next_request_version_id', shared_enterprise_verification_hando"
        "ff_facts.next_request_version_id, 'next_request_revision', shared_enterprise"
        "_verification_handoff_facts.next_request_revision, 'build_id', shared_enterp"
        "rise_verification_formal_requests.build_id, 'reason', shared_enterprise_veri"
        "fication_handoff_facts.reason, 'continuation_permission', 'not_evaluated'), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_verification_handoff.value['artifact_id'], 'vers"
        "ion', enterprise_reads_verification_handoff.value['expected_revision']) ORDE"
        "R BY enterprise_reads_verification_handoff.value ->> 'artifact_id', enterpri"
        "se_reads_verification_handoff.value ->> 'expected_revision'), jsonb_build_ar"
        'ray()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_verificat'
        'ion_handoff_facts.required_source_read_set) AS enterprise_reads_verification'
        "_handoff(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), '"
        "hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_ente"
        "rprise_verification_handoff_facts.request_id, 'kind', 'verification_handoff'"
        ", 'facts', jsonb_build_object('record_kind', 'physical_verification_handoff'"
        ", 'operation', shared_enterprise_verification_handoff_facts.operation, 'stat"
        "us_as_recorded', shared_enterprise_verification_handoff_facts.status, 'reque"
        "st_id', shared_enterprise_verification_handoff_facts.request_id, 'request_ve"
        "rsion_id', shared_enterprise_verification_handoff_facts.request_version_id, "
        "'request_revision', shared_enterprise_verification_handoff_facts.request_rev"
        "ision, 'next_request_version_id', shared_enterprise_verification_handoff_fac"
        "ts.next_request_version_id, 'next_request_revision', shared_enterprise_verif"
        "ication_handoff_facts.next_request_revision, 'build_id', shared_enterprise_v"
        "erification_formal_requests.build_id, 'reason', shared_enterprise_verificati"
        "on_handoff_facts.reason, 'continuation_permission', 'not_evaluated'), 'sourc"
        "e_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', '"
        "id', enterprise_reads_verification_handoff.value['artifact_id'], 'version', "
        "enterprise_reads_verification_handoff.value['expected_revision']) ORDER BY e"
        "nterprise_reads_verification_handoff.value ->> 'artifact_id', enterprise_rea"
        "ds_verification_handoff.value ->> 'expected_revision'), jsonb_build_array())"
        ' AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_verification_ha'
        'ndoff_facts.required_source_read_set) AS enterprise_reads_verification_hando'
        "ff(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(json"
        "b_build_object('object_id', shared_enterprise_verification_handoff_facts.req"
        "uest_id, 'kind', 'verification_handoff', 'facts', jsonb_build_object('record"
        "_kind', 'physical_verification_handoff', 'operation', shared_enterprise_veri"
        "fication_handoff_facts.operation, 'status_as_recorded', shared_enterprise_ve"
        "rification_handoff_facts.status, 'request_id', shared_enterprise_verificatio"
        "n_handoff_facts.request_id, 'request_version_id', shared_enterprise_verifica"
        "tion_handoff_facts.request_version_id, 'request_revision', shared_enterprise"
        "_verification_handoff_facts.request_revision, 'next_request_version_id', sha"
        "red_enterprise_verification_handoff_facts.next_request_version_id, 'next_req"
        "uest_revision', shared_enterprise_verification_handoff_facts.next_request_re"
        "vision, 'build_id', shared_enterprise_verification_formal_requests.build_id,"
        " 'reason', shared_enterprise_verification_handoff_facts.reason, 'continuatio"
        "n_permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(j"
        "sonb_build_object('type', 'artifact', 'id', enterprise_reads_verification_ha"
        "ndoff.value['artifact_id'], 'version', enterprise_reads_verification_handoff"
        ".value['expected_revision']) ORDER BY enterprise_reads_verification_handoff."
        "value ->> 'artifact_id', enterprise_reads_verification_handoff.value ->> 'ex"
        "pected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_ele"
        'ments(shared_enterprise_verification_handoff_facts.required_source_read_set)'
        " AS enterprise_reads_verification_handoff(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS structured, 'structured' AS nature, shared_enterprise_verificati"
        "on_handoff_facts.visibility != 'category' OR coalesce(shared_enterprise_proj"
        "ects.visibility != 'category', false) OR coalesce(shared_enterprise_products"
        ".visibility != 'category', false) OR (EXISTS (SELECT 1 \nFROM jsonb_array_el"
        'ements(shared_enterprise_verification_handoff_facts.required_source_read_set'
        ') AS enterprise_reads_verification_handoff(value) JOIN enterprise_authoritat'
        'ive_artifacts_13192f369ba42d6a ON enterprise_authoritative_artifacts_13192f3'
        '69ba42d6a.tenant_id = shared_enterprise_verification_handoff_facts.tenant_id'
        ' AND enterprise_authoritative_artifacts_13192f369ba42d6a.source_id = CAST((e'
        "nterprise_reads_verification_handoff.value ->> 'artifact_id') AS UUID) \nWHE"
        'RE enterprise_authoritative_artifacts_13192f369ba42d6a.private)) OR shared_e'
        "nterprise_verification_formal_requests.visibility != 'category' AS private, "
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_verification_'
        'handoff_facts.required_source_read_set) AS enterprise_reads_verification_han'
        'doff(value) JOIN enterprise_authoritative_artifacts_13192f369ba42d6a ON ente'
        'rprise_authoritative_artifacts_13192f369ba42d6a.tenant_id = shared_enterpris'
        'e_verification_handoff_facts.tenant_id AND enterprise_authoritative_artifact'
        's_13192f369ba42d6a.source_id = CAST((enterprise_reads_verification_handoff.v'
        "alue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_"
        '13192f369ba42d6a.customer_original) AS customer_original, shared_enterprise_'
        'verification_current_formal_requests.request_version_id = shared_enterprise_'
        'verification_handoff_facts.next_request_version_id AS is_current, shared_ent'
        'erprise_verification_handoff_facts.created_at AS created_at, CAST(NULL AS UU'
        'ID) AS original_id, shared_enterprise_verification_handoff_facts.request_id '
        'AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_'
        '13192f369ba42d6a.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_a'
        'rray_elements(shared_enterprise_verification_handoff_facts.required_source_r'
        'ead_set) AS enterprise_reads_verification_handoff(value) JOIN enterprise_aut'
        'horitative_artifacts_13192f369ba42d6a ON enterprise_authoritative_artifacts_'
        '13192f369ba42d6a.tenant_id = shared_enterprise_verification_handoff_facts.te'
        'nant_id AND enterprise_authoritative_artifacts_13192f369ba42d6a.source_id = '
        "CAST((enterprise_reads_verification_handoff.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_13192f369ba42d6a.original_id IS'
        ' NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_e'
        'lements(shared_enterprise_verification_handoff_facts.required_source_read_se'
        't) AS enterprise_reads_verification_handoff(value) JOIN enterprise_authorita'
        'tive_artifacts_13192f369ba42d6a ON enterprise_authoritative_artifacts_13192f'
        '369ba42d6a.tenant_id = shared_enterprise_verification_handoff_facts.tenant_i'
        'd AND enterprise_authoritative_artifacts_13192f369ba42d6a.source_id = CAST(('
        "enterprise_reads_verification_handoff.value ->> 'artifact_id') AS UUID) \nWH"
        'ERE enterprise_authoritative_artifacts_13192f369ba42d6a.source_revision != C'
        "AST((enterprise_reads_verification_handoff.value ->> 'expected_revision') AS"
        " INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nF"
        'ROM shared_enterprise_verification_handoff_facts JOIN shared_enterprise_proj'
        'ects ON shared_enterprise_projects.tenant_id = shared_enterprise_verificatio'
        'n_handoff_facts.tenant_id AND shared_enterprise_projects.product_id = shared'
        '_enterprise_verification_handoff_facts.product_id AND shared_enterprise_proj'
        'ects.id = shared_enterprise_verification_handoff_facts.project_id AND shared'
        '_enterprise_projects.category_id = shared_enterprise_verification_handoff_fa'
        'cts.category_id JOIN shared_enterprise_products ON shared_enterprise_product'
        's.tenant_id = shared_enterprise_verification_handoff_facts.tenant_id AND sha'
        'red_enterprise_products.id = shared_enterprise_verification_handoff_facts.pr'
        'oduct_id AND shared_enterprise_products.category_id = shared_enterprise_veri'
        'fication_handoff_facts.category_id JOIN shared_enterprise_verification_forma'
        'l_requests ON shared_enterprise_verification_handoff_facts.tenant_id = share'
        'd_enterprise_verification_formal_requests.tenant_id AND shared_enterprise_ve'
        'rification_handoff_facts.category_id = shared_enterprise_verification_formal'
        '_requests.category_id AND shared_enterprise_verification_handoff_facts.produ'
        'ct_id = shared_enterprise_verification_formal_requests.product_id AND shared'
        '_enterprise_verification_handoff_facts.project_id = shared_enterprise_verifi'
        'cation_formal_requests.project_id AND shared_enterprise_verification_handoff'
        '_facts.request_id = shared_enterprise_verification_formal_requests.request_i'
        'd AND shared_enterprise_verification_handoff_facts.next_request_version_id ='
        ' shared_enterprise_verification_formal_requests.id AND shared_enterprise_ver'
        'ification_handoff_facts.next_request_revision = shared_enterprise_verificati'
        'on_formal_requests.revision JOIN shared_enterprise_verification_current_form'
        'al_requests ON shared_enterprise_verification_current_formal_requests.tenant'
        '_id = shared_enterprise_verification_handoff_facts.tenant_id AND shared_ente'
        'rprise_verification_current_formal_requests.category_id = shared_enterprise_'
        'verification_handoff_facts.category_id AND shared_enterprise_verification_cu'
        'rrent_formal_requests.product_id = shared_enterprise_verification_handoff_fa'
        'cts.product_id AND shared_enterprise_verification_current_formal_requests.re'
        'quest_id = shared_enterprise_verification_handoff_facts.request_id \nWHERE s'
        'hared_enterprise_verification_handoff_facts.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFR"
        'OM jsonb_array_elements(shared_enterprise_verification_handoff_facts.require'
        'd_source_read_set) AS enterprise_reads_verification_handoff(value) \nWHERE N'
        'OT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_13192f369ba42'
        'd6a \nWHERE enterprise_authoritative_artifacts_13192f369ba42d6a.tenant_id = '
        'shared_enterprise_verification_handoff_facts.tenant_id AND enterprise_author'
        'itative_artifacts_13192f369ba42d6a.source_id = CAST((enterprise_reads_verifi'
        "cation_handoff.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELEC"
        'T 1 \nFROM authoritative_enterprise_sources_13192f369ba42d6a \nWHERE authori'
        'tative_enterprise_sources_13192f369ba42d6a.tenant_id = t AND authoritative_e'
        'nterprise_sources_13192f369ba42d6a.category_id = c AND CAST(authoritative_en'
        "terprise_sources_13192f369ba42d6a.source_id AS TEXT) = expected->>'source_id"
        "' AND CAST(authoritative_enterprise_sources_13192f369ba42d6a.source_revision"
        " AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_source"
        "s_13192f369ba42d6a.content_hash = expected->>'content_hash') AS anon_1 INTO "
        'visible;\n  ELSE RETURN false; END CASE;\n  IF visible IS DISTINCT FROM true'
        ' THEN RETURN false; END IF;\n END LOOP;\n RETURN true;\nEXCEPTION WHEN inval'
        'id_text_representation OR numeric_value_out_of_range THEN RETURN false;\nEND'
        '\n;\n$function$\n'
    ),
    'enterprise_index_source_clear(text,uuid,uuid,text,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.enterprise_index_source_clear(kind text, s'
        'id uuid, category uuid, expected_key text, expected_ids uuid[])\n RETURNS vo'
        "id\n LANGUAGE plpgsql\n SECURITY DEFINER\n SET search_path TO 'pg_catalog', "
        "'public', 'pg_temp'\nAS $function$\nDECLARE\n  t uuid := NULLIF(current_sett"
        "ing('pdos.tenant_id',true),'')::uuid;\n  a uuid := NULLIF(current_setting('p"
        "dos.actor_id',true),'')::uuid;\n  r uuid := NULLIF(current_setting('pdos.req"
        "uester_id',true),'')::uuid;\nBEGIN\n  IF t IS NULL OR a IS NULL OR r IS NULL"
        '\n     OR NOT EXISTS(SELECT 1 FROM public.principals p\n                   W'
        'HERE p.tenant_id=t AND p.id=a AND p.active)\n     OR NOT EXISTS(SELECT 1 FRO'
        'M public.principals p\n                   WHERE p.tenant_id=t AND p.id=r AND'
        ' p.active)\n     OR public.category_access(t,category,false) IS DISTINCT FRO'
        "M true THEN\n    RAISE EXCEPTION 'Derived source repair requires active boun"
        "d source scope'\n      USING ERRCODE='42501';\n  END IF;\n  IF kind IS NULL "
        "OR kind NOT IN\n     ('artifact','knowledge','issue','capa','change','test_r"
        "un','build','supply','external_wait','field_feedback','project_status','manu"
        "facturing_document','verification_handoff')\n     OR sid IS NULL OR expected"
        "_key IS NULL OR expected_key !~ '^[a-f0-9]{64}$'\n     OR expected_ids IS NU"
        'LL OR array_position(expected_ids,NULL) IS NOT NULL THEN\n    RAISE EXCEPTIO'
        "N 'Derived source repair requires projector-computed identity'\n      USING "
        "ERRCODE='22023';\n  END IF;\n  PERFORM pg_advisory_xact_lock(hashtextextende"
        "d('enterprise-index:' || t::text,0));\n  DELETE FROM public.enterprise_searc"
        'h_chunks c WHERE c.tenant_id=t\n    AND ((c.source_type=kind AND c.source_id'
        '=sid)\n      OR c.work_key=expected_key OR c.id=ANY(expected_ids));\n  DELET'
        'E FROM public.enterprise_search_sources s WHERE s.tenant_id=t\n    AND ((s.s'
        'ource_type=kind AND s.source_id=sid) OR s.work_key=expected_key);\nEND $func'
        'tion$\n'
    ),
}

SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
EMPTY_HISTORY_SQL = (
    (
        'DO $role_migrator$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='
        "current_user AND (rolsuper OR rolbypassrls)) THEN RAISE EXCEPTION 'All-tenan"
        "t role-source history check requires an administrative migrator'; END IF; EN"
        'D $role_migrator$'
    ),
    (
        'LOCK TABLE public.category_knowledge_entries,public.knowledge_candidate_vers'
        'ions,public.knowledge_rule_versions,public.knowledge_answer_reviews,public.k'
        'nowledge_gap_submissions,public.dingtalk_deliveries ,public.agent_tool_calls'
        ' IN SHARE ROW EXCLUSIVE MODE'
    ),
    (
        'DO $role_history$ BEGIN IF EXISTS(SELECT 1 FROM public.category_knowledge_en'
        "tries WHERE jsonb_path_exists(coalesce(answer_sources,'[]'::jsonb),'$[*] ? ("
        '@.source_type == "project_status" || @.source_type == "manufacturing_documen'
        't" || @.source_type == "verification_handoff")\') UNION ALL SELECT 1 FROM pu'
        'blic.knowledge_candidate_versions WHERE jsonb_path_exists(coalesce(source_ba'
        'sis->\'answer_sources\',\'[]\'::jsonb),\'$[*] ? (@.source_type == "project_s'
        'tatus" || @.source_type == "manufacturing_document" || @.source_type == "ver'
        'ification_handoff")\') UNION ALL SELECT 1 FROM public.knowledge_rule_version'
        "s WHERE jsonb_path_exists(coalesce(source_basis->'answer_sources','[]'::json"
        'b),\'$[*] ? (@.source_type == "project_status" || @.source_type == "manufact'
        'uring_document" || @.source_type == "verification_handoff")\') UNION ALL SEL'
        'ECT 1 FROM public.knowledge_answer_reviews WHERE jsonb_path_exists(coalesce('
        'source_proof,\'[]\'::jsonb),\'$[*] ? (@.source_type == "project_status" || @'
        '.source_type == "manufacturing_document" || @.source_type == "verification_h'
        'andoff")\') UNION ALL SELECT 1 FROM public.knowledge_gap_submissions WHERE j'
        "sonb_path_exists(coalesce(source_proof,'[]'::jsonb),'$[*] ? (@.source_type ="
        '= "project_status" || @.source_type == "manufacturing_document" || @.source_'
        'type == "verification_handoff")\') UNION ALL SELECT 1 FROM public.dingtalk_d'
        "eliveries WHERE jsonb_path_exists(coalesce(source_dependencies,'[]'::jsonb),"
        '\'$[*] ? (@.source_type == "project_status" || @.source_type == "manufacturi'
        'ng_document" || @.source_type == "verification_handoff")\')) OR EXISTS(SELEC'
        "T 1 FROM public.agent_tool_calls WHERE tool IN ('assistant.search','assistan"
        "t.materials.read','assistant.citations.read') AND jsonb_path_exists(coalesce"
        '(result->\'items\',\'[]\'::jsonb),\'$[*] ? (@.source_type == "project_status'
        '" || @.source_type == "manufacturing_document" || @.source_type == "verifica'
        'tion_handoff")\')) THEN RAISE EXCEPTION \'Native role source history cannot '
        "lose native lifecycle roots' USING ERRCODE='23514'; END IF; END $role_histor"
        'y$'
    ),
)
