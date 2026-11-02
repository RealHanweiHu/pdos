"""Refresh fixed source visibility and normalize absent optional knowledge proof."""

PREVIOUS_FUNCTIONS = {
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
        "_enterprise_sources_artifact AS \n(SELECT 'artifact' AS source_type, artifac"
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
        't_id IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise'
        '_sources_artifact \nWHERE authoritative_enterprise_sources_artifact.tenant_i'
        'd = t AND authoritative_enterprise_sources_artifact.category_id = c AND CAST'
        "(authoritative_enterprise_sources_artifact.source_id AS TEXT) = expected->>'"
        "source_id' AND CAST(authoritative_enterprise_sources_artifact.source_revisio"
        "n AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_sourc"
        "es_artifact.content_hash = expected->>'content_hash') AS anon_1 INTO visible"
        ";\n WHEN 'knowledge' THEN\n  SELECT EXISTS (SELECT 1 \nFROM (SELECT category"
        '_knowledge_entries.id AS source_id, category_knowledge_entries.tenant_id AS '
        'tenant_id, category_knowledge_entries.category_id AS category_id, category_k'
        'nowledge_entries.version AS source_revision, encode(sha256(convert_to(CAST(c'
        "ategory_knowledge_entries.content AS TEXT), 'UTF8')), 'hex') AS content_hash"
        ' \nFROM category_knowledge_entries JOIN category_knowledge_current ON catego'
        'ry_knowledge_current.tenant_id = category_knowledge_entries.tenant_id AND ca'
        'tegory_knowledge_current.lineage_id = category_knowledge_entries.lineage_id '
        "AND category_knowledge_current.status = 'active' \nWHERE category_knowledge_"
        "entries.action != 'withdraw' UNION ALL SELECT knowledge_rule_versions.id AS "
        'source_id, knowledge_rule_versions.tenant_id AS tenant_id, knowledge_rule_ve'
        'rsions.category_id AS category_id, knowledge_rule_versions.revision AS sourc'
        'e_revision, encode(sha256(convert_to(CAST(knowledge_rule_versions.body AS TE'
        "XT), 'UTF8')), 'hex') AS content_hash \nFROM knowledge_rule_versions JOIN kn"
        'owledge_rule_currents ON knowledge_rule_currents.tenant_id = knowledge_rule_'
        'versions.tenant_id AND knowledge_rule_currents.rule_id = knowledge_rule_vers'
        'ions.rule_id) AS ordinary_knowledge_leaves \nWHERE ordinary_knowledge_leaves'
        '.tenant_id = t AND ordinary_knowledge_leaves.category_id = c AND CAST(ordina'
        "ry_knowledge_leaves.source_id AS TEXT) = expected->>'source_id' AND CAST(ord"
        "inary_knowledge_leaves.source_revision AS TEXT) = expected->>'source_revisio"
        "n' AND ordinary_knowledge_leaves.content_hash = expected->>'content_hash') A"
        "S anon_1 INTO visible;\n WHEN 'issue' THEN\n  WITH enterprise_authoritative_"
        "artifacts_issue AS \n(SELECT 'artifact' AS source_type, artifact_versions.id"
        ' AS source_id, artifact_versions.tenant_id AS tenant_id, artifact_versions.c'
        'ategory_id AS category_id, artifact_versions.product_id AS product_id, CAST('
        'NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_ver'
        'sions.owner_id AS owner_id, artifact_versions.revision AS source_revision, a'
        'rtifact_versions.title AS title, artifact_versions.content_hash AS content_h'
        "ash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, '"
        "untrusted' AS nature, artifact_versions.visibility != 'category' OR coalesce"
        "(products.visibility != 'category', false) OR coalesce(uploaded_originals.vi"
        "sibility != 'category', false) AS private, artifact_versions.original_id IS "
        'NOT NULL AS customer_original, true AS is_current, artifact_versions.created'
        '_at AS created_at, artifact_versions.original_id AS original_id, artifact_ve'
        'rsions.id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL'
        ') THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS orig'
        "inal_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER"
        ' JOIN products ON products.tenant_id = artifact_versions.tenant_id AND produ'
        'cts.id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON '
        'uploaded_originals.tenant_id = artifact_versions.tenant_id AND uploaded_orig'
        'inals.id = artifact_versions.original_id AND uploaded_originals.category_id '
        '= artifact_versions.category_id AND uploaded_originals.product_id IS NOT DIS'
        'TINCT FROM artifact_versions.product_id LEFT OUTER JOIN original_security ON'
        ' original_security.tenant_id = uploaded_originals.tenant_id AND original_sec'
        'urity.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_i'
        "d = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND ar"
        "tifact_versions.status = 'active' AND artifact_versions.category_id IS NOT N"
        'ULL AND (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AN'
        'D (artifact_versions.original_id IS NULL OR uploaded_originals.id IS NOT NUL'
        "L AND uploaded_originals.status = 'parsed' AND uploaded_originals.scan_statu"
        "s = 'clean' AND original_security.source_state = 'active' AND original_secur"
        "ity.disposition = 'active' AND original_security.current_request_id IS NOT N"
        'ULL)), \nshared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT '
        'quality_issue_versions.product_id AS product_id, quality_issue_versions.proj'
        'ect_id AS project_id, quality_issue_versions.issue_id AS issue_id, quality_i'
        'ssue_versions.revision AS revision, quality_issue_versions.previous_issue_ve'
        'rsion_id AS previous_issue_version_id, quality_issue_versions.previous_revis'
        'ion AS previous_revision, quality_issue_versions.owner_id AS owner_id, quali'
        'ty_issue_versions.writer_id AS writer_id, quality_issue_versions.visibility '
        'AS visibility, quality_issue_versions.purpose AS purpose, quality_issue_vers'
        'ions.status AS status, quality_issue_versions.operation AS operation, qualit'
        'y_issue_versions.issue_snapshot AS issue_snapshot, quality_issue_versions.sn'
        'apshot_sha256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS i'
        'nput_snapshot, quality_issue_versions.authority_snapshot AS authority_snapsh'
        'ot, quality_issue_versions.policy_snapshot AS policy_snapshot, quality_issue'
        '_versions.sources AS sources, quality_issue_versions.required_source_read_se'
        't AS required_source_read_set, quality_issue_versions.source_basis AS source'
        '_basis, quality_issue_versions.intent_digest AS intent_digest, quality_issue'
        '_versions.reason AS reason, quality_issue_versions.id AS id, quality_issue_v'
        'ersions.tenant_id AS tenant_id, quality_issue_versions.created_at AS created'
        '_at, quality_issue_versions.category_id AS category_id \nFROM quality_issue_'
        'versions \nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_sett'
        "ing('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS "
        'MATERIALIZED \n(SELECT projects.product_id AS product_id, projects.owner_id '
        'AS owner_id, projects.name AS name, projects.purpose AS purpose, projects.sc'
        'ope AS scope, projects.visibility AS visibility, projects.status AS status, '
        'projects.revision AS revision, projects.current_plan_id AS current_plan_id, '
        'projects.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, pr'
        'ojects.g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_'
        'id AS tenant_id, projects.created_at AS created_at, projects.category_id AS '
        'category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current'
        "_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_product"
        's AS MATERIALIZED \n(SELECT products.name AS name, products.purpose AS purpo'
        'se, products.revision AS revision, products.lifecycle_epoch AS lifecycle_epo'
        'ch, products.status AS status, products.owner_id AS owner_id, products.paren'
        't_product_id AS parent_product_id, products.category_id AS category_id, prod'
        'ucts.visibility AS visibility, products.target_price AS target_price, produc'
        'ts.target_price_currency AS target_price_currency, products.target_price_bas'
        'is AS target_price_basis, products.target_price_includes_tax AS target_price'
        '_includes_tax, products.target_price_as_of AS target_price_as_of, products.i'
        'd AS id, products.tenant_id AS tenant_id, products.created_at AS created_at '
        "\nFROM products \nWHERE products.tenant_id = CAST(nullif(current_setting('pd"
        "os.tenant_id', true), '') AS UUID)), \nshared_enterprise_quality_current_iss"
        'ues AS MATERIALIZED \n(SELECT quality_current_issues.product_id AS product_i'
        'd, quality_current_issues.project_id AS project_id, quality_current_issues.i'
        'ssue_id AS issue_id, quality_current_issues.issue_version_id AS issue_versio'
        'n_id, quality_current_issues.issue_revision AS issue_revision, quality_curre'
        'nt_issues.epoch AS epoch, quality_current_issues.id AS id, quality_current_i'
        'ssues.tenant_id AS tenant_id, quality_current_issues.created_at AS created_a'
        't, quality_current_issues.category_id AS category_id \nFROM quality_current_'
        'issues \nWHERE quality_current_issues.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources"
        "_issue AS \n(SELECT 'issue' AS source_type, shared_enterprise_quality_issue_"
        'versions.id AS source_id, shared_enterprise_quality_issue_versions.tenant_id'
        ' AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS categ'
        'ory_id, shared_enterprise_quality_issue_versions.product_id AS product_id, s'
        'hared_enterprise_quality_issue_versions.project_id AS project_id, CAST(NULL '
        'AS UUID) AS proposal_id, shared_enterprise_quality_issue_versions.owner_id A'
        'S owner_id, shared_enterprise_quality_issue_versions.revision AS source_revi'
        "sion, shared_enterprise_quality_issue_versions.issue_snapshot ->> 'title' AS"
        " title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', s"
        "hared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'facts', "
        "jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.issu"
        "e_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot['titl"
        "e'], 'status', shared_enterprise_quality_issue_versions.status, 'risk', shar"
        "ed_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_recheck'"
        ", shared_enterprise_quality_issue_versions.issue_snapshot['needs_recheck'], "
        "'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot['"
        "recheck_reasons'], 'merged_into', shared_enterprise_quality_issue_versions.i"
        "ssue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', share"
        "d_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'], 'a"
        "ctor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root_caus"
        "e']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapsh"
        "ot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(jsonb_bui"
        "ld_object('id', enterprise_containment.value['id'], 'text', enterprise_conta"
        "inment.value['text'], 'executor_id', enterprise_containment.value['executor_"
        "id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS coal"
        'esce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_'
        "versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDINALIT"
        "Y AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_object("
        "'text', shared_enterprise_quality_issue_versions.issue_snapshot['closure']['"
        "text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot["
        "'closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(json"
        "b_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['artif"
        "act_id'], 'version', enterprise_reads_issue.value['expected_revision']) ORDE"
        "R BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_issue."
        "value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM js"
        'onb_array_elements(shared_enterprise_quality_issue_versions.required_source_'
        "read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSON"
        "B) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object("
        "'object_id', shared_enterprise_quality_issue_versions.issue_id, 'kind', 'iss"
        "ue', 'facts', jsonb_build_object('issue_id', shared_enterprise_quality_issue"
        "_versions.issue_id, 'title', shared_enterprise_quality_issue_versions.issue_"
        "snapshot['title'], 'status', shared_enterprise_quality_issue_versions.status"
        ", 'risk', shared_enterprise_quality_issue_versions.issue_snapshot['risk'], '"
        "needs_recheck', shared_enterprise_quality_issue_versions.issue_snapshot['nee"
        "ds_recheck'], 'recheck_reasons', shared_enterprise_quality_issue_versions.is"
        "sue_snapshot['recheck_reasons'], 'merged_into', shared_enterprise_quality_is"
        "sue_versions.issue_snapshot['merged_into'], 'root_cause', jsonb_build_object"
        "('text', shared_enterprise_quality_issue_versions.issue_snapshot['root_cause"
        "']['text'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snaps"
        "hot['root_cause']['actor_id'], 'at', shared_enterprise_quality_issue_version"
        "s.issue_snapshot['root_cause']['at']), 'containment', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('id', enterprise_containment.value['id'], 'text', en"
        "terprise_containment.value['text'], 'executor_id', enterprise_containment.va"
        "lue['executor_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_ar"
        'ray()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_'
        "quality_issue_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) "
        "WITH ORDINALITY AS enterprise_containment(value, ordinal)), 'closure', jsonb"
        "_build_object('text', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['closure']['text'], 'actor_id', shared_enterprise_quality_issue_versions.i"
        "ssue_snapshot['closure']['actor_id'], 'at', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce("
        "jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_issu"
        "e.value['artifact_id'], 'version', enterprise_reads_issue.value['expected_re"
        "vision']) ORDER BY enterprise_reads_issue.value ->> 'artifact_id', enterpris"
        "e_reads_issue.value ->> 'expected_revision'), jsonb_build_array()) AS coales"
        'ce_2 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.re'
        "quired_source_read_set) AS enterprise_reads_issue(value)), 'record_policy', "
        "'\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue', 'facts', j"
        "sonb_build_object('issue_id', shared_enterprise_quality_issue_versions.issue"
        "_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot['title"
        "'], 'status', shared_enterprise_quality_issue_versions.status, 'risk', share"
        "d_enterprise_quality_issue_versions.issue_snapshot['risk'], 'needs_recheck',"
        " shared_enterprise_quality_issue_versions.issue_snapshot['needs_recheck'], '"
        "recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot['r"
        "echeck_reasons'], 'merged_into', shared_enterprise_quality_issue_versions.is"
        "sue_snapshot['merged_into'], 'root_cause', jsonb_build_object('text', shared"
        "_enterprise_quality_issue_versions.issue_snapshot['root_cause']['text'], 'ac"
        "tor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root_cause"
        "']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapsho"
        "t['root_cause']['at']), 'containment', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('id', enterprise_containment.value['id'], 'text', enterprise_contai"
        "nment.value['text'], 'executor_id', enterprise_containment.value['executor_i"
        "d']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS coale"
        'sce_1 \nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_v'
        "ersions.issue_snapshot['containment'], CAST('[]' AS JSONB))) WITH ORDINALITY"
        " AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_object('"
        "text', shared_enterprise_quality_issue_versions.issue_snapshot['closure']['t"
        "ext'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['"
        "closure']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_"
        "snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb"
        "_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['artifa"
        "ct_id'], 'version', enterprise_reads_issue.value['expected_revision']) ORDER"
        " BY enterprise_reads_issue.value ->> 'artifact_id', enterprise_reads_issue.v"
        "alue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jso"
        'nb_array_elements(shared_enterprise_quality_issue_versions.required_source_r'
        "ead_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSON"
        "B) AS structured, 'structured' AS nature, shared_enterprise_quality_issue_ve"
        "rsions.visibility != 'category' OR shared_enterprise_projects.visibility != "
        "'category' OR shared_enterprise_products.visibility != 'category' OR (EXISTS"
        ' (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versi'
        'ons.required_source_read_set) AS enterprise_reads_issue(value) JOIN enterpri'
        'se_authoritative_artifacts_issue ON enterprise_authoritative_artifacts_issue'
        '.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND enterpri'
        'se_authoritative_artifacts_issue.source_id = CAST((enterprise_reads_issue.va'
        "lue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_i"
        'ssue.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shar'
        'ed_enterprise_quality_issue_versions.required_source_read_set) AS enterprise'
        '_reads_issue(value) JOIN enterprise_authoritative_artifacts_issue ON enterpr'
        'ise_authoritative_artifacts_issue.tenant_id = shared_enterprise_quality_issu'
        'e_versions.tenant_id AND enterprise_authoritative_artifacts_issue.source_id '
        "= CAST((enterprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE ent"
        'erprise_authoritative_artifacts_issue.customer_original) AS customer_origina'
        'l, shared_enterprise_quality_current_issues.issue_version_id = shared_enterp'
        'rise_quality_issue_versions.id AS is_current, shared_enterprise_quality_issu'
        'e_versions.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shar'
        'ed_enterprise_quality_issue_versions.issue_id AS object_id, (SELECT coalesce'
        '(array_agg(enterprise_authoritative_artifacts_issue.original_id), ARRAY[]::U'
        'UID[]) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_i'
        'ssue_versions.required_source_read_set) AS enterprise_reads_issue(value) JOI'
        'N enterprise_authoritative_artifacts_issue ON enterprise_authoritative_artif'
        'acts_issue.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AN'
        'D enterprise_authoritative_artifacts_issue.source_id = CAST((enterprise_read'
        "s_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_a"
        'rtifacts_issue.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS ('
        'SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_version'
        's.required_source_read_set) AS enterprise_reads_issue(value) JOIN enterprise'
        '_authoritative_artifacts_issue ON enterprise_authoritative_artifacts_issue.t'
        'enant_id = shared_enterprise_quality_issue_versions.tenant_id AND enterprise'
        '_authoritative_artifacts_issue.source_id = CAST((enterprise_reads_issue.valu'
        "e ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_iss"
        "ue.source_revision != CAST((enterprise_reads_issue.value ->> 'expected_revis"
        "ion') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_st"
        'atus \nFROM shared_enterprise_quality_issue_versions JOIN shared_enterprise_'
        'projects ON shared_enterprise_projects.tenant_id = shared_enterprise_quality'
        '_issue_versions.tenant_id AND shared_enterprise_projects.product_id = shared'
        '_enterprise_quality_issue_versions.product_id AND shared_enterprise_projects'
        '.id = shared_enterprise_quality_issue_versions.project_id AND shared_enterpr'
        'ise_projects.category_id = shared_enterprise_quality_issue_versions.category'
        '_id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id '
        '= shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise_p'
        'roducts.id = shared_enterprise_quality_issue_versions.product_id AND shared_'
        'enterprise_products.category_id = shared_enterprise_quality_issue_versions.c'
        'ategory_id JOIN shared_enterprise_quality_current_issues ON shared_enterpris'
        'e_quality_current_issues.tenant_id = shared_enterprise_quality_issue_version'
        's.tenant_id AND shared_enterprise_quality_current_issues.product_id = shared'
        '_enterprise_quality_issue_versions.product_id AND shared_enterprise_quality_'
        'current_issues.project_id = shared_enterprise_quality_issue_versions.project'
        '_id AND shared_enterprise_quality_current_issues.issue_id = shared_enterpris'
        'e_quality_issue_versions.issue_id \nWHERE shared_enterprise_quality_issue_ve'
        "rsions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') "
        'AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterp'
        'rise_quality_issue_versions.required_source_read_set) AS enterprise_reads_is'
        'sue(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_art'
        'ifacts_issue \nWHERE enterprise_authoritative_artifacts_issue.tenant_id = sh'
        'ared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritativ'
        "e_artifacts_issue.source_id = CAST((enterprise_reads_issue.value ->> 'artifa"
        "ct_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterpr"
        'ise_sources_issue \nWHERE authoritative_enterprise_sources_issue.tenant_id ='
        ' t AND authoritative_enterprise_sources_issue.category_id = c AND CAST(autho'
        "ritative_enterprise_sources_issue.source_id AS TEXT) = expected->>'source_id"
        "' AND CAST(authoritative_enterprise_sources_issue.source_revision AS TEXT) ="
        " expected->>'source_revision' AND authoritative_enterprise_sources_issue.con"
        "tent_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'capa'"
        " THEN\n  WITH enterprise_authoritative_artifacts_capa AS \n(SELECT 'artifact"
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
        'l_security.current_request_id IS NOT NULL)), \nshared_enterprise_quality_iss'
        'ue_versions AS MATERIALIZED \n(SELECT quality_issue_versions.product_id AS p'
        'roduct_id, quality_issue_versions.project_id AS project_id, quality_issue_ve'
        'rsions.issue_id AS issue_id, quality_issue_versions.revision AS revision, qu'
        'ality_issue_versions.previous_issue_version_id AS previous_issue_version_id,'
        ' quality_issue_versions.previous_revision AS previous_revision, quality_issu'
        'e_versions.owner_id AS owner_id, quality_issue_versions.writer_id AS writer_'
        'id, quality_issue_versions.visibility AS visibility, quality_issue_versions.'
        'purpose AS purpose, quality_issue_versions.status AS status, quality_issue_v'
        'ersions.operation AS operation, quality_issue_versions.issue_snapshot AS iss'
        'ue_snapshot, quality_issue_versions.snapshot_sha256 AS snapshot_sha256, qual'
        'ity_issue_versions.input_snapshot AS input_snapshot, quality_issue_versions.'
        'authority_snapshot AS authority_snapshot, quality_issue_versions.policy_snap'
        'shot AS policy_snapshot, quality_issue_versions.sources AS sources, quality_'
        'issue_versions.required_source_read_set AS required_source_read_set, quality'
        '_issue_versions.source_basis AS source_basis, quality_issue_versions.intent_'
        'digest AS intent_digest, quality_issue_versions.reason AS reason, quality_is'
        'sue_versions.id AS id, quality_issue_versions.tenant_id AS tenant_id, qualit'
        'y_issue_versions.created_at AS created_at, quality_issue_versions.category_i'
        'd AS category_id \nFROM quality_issue_versions \nWHERE quality_issue_version'
        "s.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UU"
        'ID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT projects.produc'
        't_id AS product_id, projects.owner_id AS owner_id, projects.name AS name, pr'
        'ojects.purpose AS purpose, projects.scope AS scope, projects.visibility AS v'
        'isibility, projects.status AS status, projects.revision AS revision, project'
        's.current_plan_id AS current_plan_id, projects.trigger_type AS trigger_type,'
        ' projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0_decision_i'
        'd, projects.id AS id, projects.tenant_id AS tenant_id, projects.created_at A'
        'S created_at, projects.category_id AS category_id \nFROM projects \nWHERE pr'
        "ojects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') "
        'AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT products.n'
        'ame AS name, products.purpose AS purpose, products.revision AS revision, pro'
        'ducts.lifecycle_epoch AS lifecycle_epoch, products.status AS status, product'
        's.owner_id AS owner_id, products.parent_product_id AS parent_product_id, pro'
        'ducts.category_id AS category_id, products.visibility AS visibility, product'
        's.target_price AS target_price, products.target_price_currency AS target_pri'
        'ce_currency, products.target_price_basis AS target_price_basis, products.tar'
        'get_price_includes_tax AS target_price_includes_tax, products.target_price_a'
        's_of AS target_price_as_of, products.id AS id, products.tenant_id AS tenant_'
        'id, products.created_at AS created_at \nFROM products \nWHERE products.tenan'
        "t_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), "
        '\nshared_enterprise_quality_current_issues AS MATERIALIZED \n(SELECT quality'
        '_current_issues.product_id AS product_id, quality_current_issues.project_id '
        'AS project_id, quality_current_issues.issue_id AS issue_id, quality_current_'
        'issues.issue_version_id AS issue_version_id, quality_current_issues.issue_re'
        'vision AS issue_revision, quality_current_issues.epoch AS epoch, quality_cur'
        'rent_issues.id AS id, quality_current_issues.tenant_id AS tenant_id, quality'
        '_current_issues.created_at AS created_at, quality_current_issues.category_id'
        ' AS category_id \nFROM quality_current_issues \nWHERE quality_current_issues'
        ".tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUI"
        "D)), \nauthoritative_enterprise_sources_capa AS \n(SELECT 'capa' AS source_t"
        'ype, shared_enterprise_quality_issue_versions.id AS source_id, shared_enterp'
        'rise_quality_issue_versions.tenant_id AS tenant_id, shared_enterprise_qualit'
        'y_issue_versions.category_id AS category_id, shared_enterprise_quality_issue'
        '_versions.product_id AS product_id, shared_enterprise_quality_issue_versions'
        '.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterpr'
        'ise_quality_issue_versions.owner_id AS owner_id, shared_enterprise_quality_i'
        "ssue_versions.revision AS source_revision, 'CAPA \xb7 ' || (shared_enterpris"
        "e_quality_issue_versions.issue_snapshot ->> 'title') AS title, encode(sha256"
        "(convert_to(CAST(CAST(jsonb_build_object('object_id', CAST((shared_enterpris"
        "e_quality_issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', "
        "'capa', 'facts', jsonb_build_object('issue_id', shared_enterprise_quality_is"
        "sue_versions.issue_id, 'capa_id', shared_enterprise_quality_issue_versions.i"
        "ssue_snapshot['capa']['id'], 'issue_status', shared_enterprise_quality_issue"
        "_versions.status, 'hypotheses', (SELECT coalesce(jsonb_agg(jsonb_build_objec"
        "t('text', enterprise_hypotheses.value['text']) ORDER BY enterprise_hypothese"
        's.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(c'
        "oalesce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['hyp"
        "otheses'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(va"
        "lue, ordinal)), 'actions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id"
        "', enterprise_capa_actions.value['id'], 'kind', enterprise_capa_actions.valu"
        "e['kind'], 'text', enterprise_capa_actions.value['text'], 'executor_id', ent"
        "erprise_capa_actions.value['executor_id'], 'completion_text', enterprise_cap"
        "a_actions.value['completion']['text'], 'completed_by', enterprise_capa_actio"
        "ns.value['completion']['executor_id'], 'completed_at', enterprise_capa_actio"
        "ns.value['completion']['at']['occurred_at']) ORDER BY enterprise_capa_action"
        's.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(c'
        "oalesce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['act"
        "ions'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_capa_actions(val"
        "ue, ordinal)), 'requirement', jsonb_build_object('method', shared_enterprise"
        "_quality_issue_versions.issue_snapshot['capa']['requirement']['method'], 'ac"
        "ceptance', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['"
        "requirement']['acceptance'], 'observation_until', shared_enterprise_quality_"
        "issue_versions.issue_snapshot['capa']['requirement']['observation_until']), "
        "'effectiveness', jsonb_build_object('text', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['capa']['effectiveness']['text'], 'result', shared_e"
        "nterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['re"
        "sult'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot["
        "'capa']['effectiveness']['actor_id'], 'at', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['capa']['effectiveness']['at'])), 'source_refs', (SE"
        "LECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpr"
        "ise_reads_capa.value['artifact_id'], 'version', enterprise_reads_capa.value["
        "'expected_revision']) ORDER BY enterprise_reads_capa.value ->> 'artifact_id'"
        ", enterprise_reads_capa.value ->> 'expected_revision'), jsonb_build_array())"
        ' AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_v'
        "ersions.required_source_read_set) AS enterprise_reads_capa(value)), 'record_"
        "policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CA"
        "ST(jsonb_build_object('object_id', CAST((shared_enterprise_quality_issue_ver"
        "sions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', js"
        "onb_build_object('issue_id', shared_enterprise_quality_issue_versions.issue_"
        "id, 'capa_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa"
        "']['id'], 'issue_status', shared_enterprise_quality_issue_versions.status, '"
        "hypotheses', (SELECT coalesce(jsonb_agg(jsonb_build_object('text', enterpris"
        "e_hypotheses.value['text']) ORDER BY enterprise_hypotheses.ordinal), jsonb_b"
        'uild_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_ente'
        "rprise_quality_issue_versions.issue_snapshot['capa']['hypotheses'], CAST('[]"
        "' AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'ac"
        "tions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_"
        "actions.value['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', "
        "enterprise_capa_actions.value['text'], 'executor_id', enterprise_capa_action"
        "s.value['executor_id'], 'completion_text', enterprise_capa_actions.value['co"
        "mpletion']['text'], 'completed_by', enterprise_capa_actions.value['completio"
        "n']['executor_id'], 'completed_at', enterprise_capa_actions.value['completio"
        "n']['at']['occurred_at']) ORDER BY enterprise_capa_actions.ordinal), jsonb_b"
        'uild_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared_ente'
        "rprise_quality_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' A"
        "S JSONB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'req"
        "uirement', jsonb_build_object('method', shared_enterprise_quality_issue_vers"
        "ions.issue_snapshot['capa']['requirement']['method'], 'acceptance', shared_e"
        "nterprise_quality_issue_versions.issue_snapshot['capa']['requirement']['acce"
        "ptance'], 'observation_until', shared_enterprise_quality_issue_versions.issu"
        "e_snapshot['capa']['requirement']['observation_until']), 'effectiveness', js"
        "onb_build_object('text', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['capa']['effectiveness']['text'], 'result', shared_enterprise_quality_i"
        "ssue_versions.issue_snapshot['capa']['effectiveness']['result'], 'actor_id',"
        " shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiven"
        "ess']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['capa']['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_capa.valu"
        "e['artifact_id'], 'version', enterprise_reads_capa.value['expected_revision'"
        "]) ORDER BY enterprise_reads_capa.value ->> 'artifact_id', enterprise_reads_"
        "capa.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFR"
        'OM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_so'
        "urce_read_set) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c'
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') A"
        "S JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', CAST((shared"
        "_enterprise_quality_issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID)"
        ", 'kind', 'capa', 'facts', jsonb_build_object('issue_id', shared_enterprise_"
        "quality_issue_versions.issue_id, 'capa_id', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['capa']['id'], 'issue_status', shared_enterprise_qua"
        "lity_issue_versions.status, 'hypotheses', (SELECT coalesce(jsonb_agg(jsonb_b"
        "uild_object('text', enterprise_hypotheses.value['text']) ORDER BY enterprise"
        '_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_'
        "elements(coalesce(shared_enterprise_quality_issue_versions.issue_snapshot['c"
        "apa']['hypotheses'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_hyp"
        "otheses(value, ordinal)), 'actions', (SELECT coalesce(jsonb_agg(jsonb_build_"
        "object('id', enterprise_capa_actions.value['id'], 'kind', enterprise_capa_ac"
        "tions.value['kind'], 'text', enterprise_capa_actions.value['text'], 'executo"
        "r_id', enterprise_capa_actions.value['executor_id'], 'completion_text', ente"
        "rprise_capa_actions.value['completion']['text'], 'completed_by', enterprise_"
        "capa_actions.value['completion']['executor_id'], 'completed_at', enterprise_"
        "capa_actions.value['completion']['at']['occurred_at']) ORDER BY enterprise_c"
        'apa_actions.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_'
        "elements(coalesce(shared_enterprise_quality_issue_versions.issue_snapshot['c"
        "apa']['actions'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_capa_a"
        "ctions(value, ordinal)), 'requirement', jsonb_build_object('method', shared_"
        "enterprise_quality_issue_versions.issue_snapshot['capa']['requirement']['met"
        "hod'], 'acceptance', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['capa']['requirement']['acceptance'], 'observation_until', shared_enterpris"
        "e_quality_issue_versions.issue_snapshot['capa']['requirement']['observation_"
        "until']), 'effectiveness', jsonb_build_object('text', shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['capa']['effectiveness']['text'], 'result'"
        ", shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effective"
        "ness']['result'], 'actor_id', shared_enterprise_quality_issue_versions.issue"
        "_snapshot['capa']['effectiveness']['actor_id'], 'at', shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['capa']['effectiveness']['at'])), 'source_"
        "refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id"
        "', enterprise_reads_capa.value['artifact_id'], 'version', enterprise_reads_c"
        "apa.value['expected_revision']) ORDER BY enterprise_reads_capa.value ->> 'ar"
        "tifact_id', enterprise_reads_capa.value ->> 'expected_revision'), jsonb_buil"
        'd_array()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_quali'
        'ty_issue_versions.required_source_read_set) AS enterprise_reads_capa(value))'
        ", 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, "
        "shared_enterprise_quality_issue_versions.visibility != 'category' OR shared_"
        "enterprise_projects.visibility != 'category' OR shared_enterprise_products.v"
        "isibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(sha"
        'red_enterprise_quality_issue_versions.required_source_read_set) AS enterpris'
        'e_reads_capa(value) JOIN enterprise_authoritative_artifacts_capa ON enterpri'
        'se_authoritative_artifacts_capa.tenant_id = shared_enterprise_quality_issue_'
        'versions.tenant_id AND enterprise_authoritative_artifacts_capa.source_id = C'
        "AST((enterprise_reads_capa.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_capa.private)) AS private, EXISTS (SELECT 1 \nFR'
        'OM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_so'
        'urce_read_set) AS enterprise_reads_capa(value) JOIN enterprise_authoritative'
        '_artifacts_capa ON enterprise_authoritative_artifacts_capa.tenant_id = share'
        'd_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritative_a'
        "rtifacts_capa.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id"
        "') AS UUID) \nWHERE enterprise_authoritative_artifacts_capa.customer_origina"
        'l) AS customer_original, shared_enterprise_quality_current_issues.issue_vers'
        'ion_id = shared_enterprise_quality_issue_versions.id AS is_current, shared_e'
        'nterprise_quality_issue_versions.created_at AS created_at, CAST(NULL AS UUID'
        ') AS original_id, CAST((shared_enterprise_quality_issue_versions.issue_snaps'
        "hot['capa']) ->> 'id' AS UUID) AS object_id, (SELECT coalesce(array_agg(ente"
        'rprise_authoritative_artifacts_capa.original_id), ARRAY[]::UUID[]) AS coales'
        'ce_4 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.re'
        'quired_source_read_set) AS enterprise_reads_capa(value) JOIN enterprise_auth'
        'oritative_artifacts_capa ON enterprise_authoritative_artifacts_capa.tenant_i'
        'd = shared_enterprise_quality_issue_versions.tenant_id AND enterprise_author'
        "itative_artifacts_capa.source_id = CAST((enterprise_reads_capa.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_capa.origina"
        'l_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_'
        'array_elements(shared_enterprise_quality_issue_versions.required_source_read'
        '_set) AS enterprise_reads_capa(value) JOIN enterprise_authoritative_artifact'
        's_capa ON enterprise_authoritative_artifacts_capa.tenant_id = shared_enterpr'
        'ise_quality_issue_versions.tenant_id AND enterprise_authoritative_artifacts_'
        "capa.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id') AS UUI"
        'D) \nWHERE enterprise_authoritative_artifacts_capa.source_revision != CAST(('
        "enterprise_reads_capa.value ->> 'expected_revision') AS INTEGER))) THEN 'nee"
        "ds_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise"
        '_quality_issue_versions JOIN shared_enterprise_projects ON shared_enterprise'
        '_projects.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND'
        ' shared_enterprise_projects.product_id = shared_enterprise_quality_issue_ver'
        'sions.product_id AND shared_enterprise_projects.id = shared_enterprise_quali'
        'ty_issue_versions.project_id AND shared_enterprise_projects.category_id = sh'
        'ared_enterprise_quality_issue_versions.category_id JOIN shared_enterprise_pr'
        'oducts ON shared_enterprise_products.tenant_id = shared_enterprise_quality_i'
        'ssue_versions.tenant_id AND shared_enterprise_products.id = shared_enterpris'
        'e_quality_issue_versions.product_id AND shared_enterprise_products.category_'
        'id = shared_enterprise_quality_issue_versions.category_id JOIN shared_enterp'
        'rise_quality_current_issues ON shared_enterprise_quality_current_issues.tena'
        'nt_id = shared_enterprise_quality_issue_versions.tenant_id AND shared_enterp'
        'rise_quality_current_issues.product_id = shared_enterprise_quality_issue_ver'
        'sions.product_id AND shared_enterprise_quality_current_issues.project_id = s'
        'hared_enterprise_quality_issue_versions.project_id AND shared_enterprise_qua'
        'lity_current_issues.issue_id = shared_enterprise_quality_issue_versions.issu'
        'e_id \nWHERE shared_enterprise_quality_issue_versions.tenant_id = CAST(nulli'
        "f(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SEL"
        'ECT 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.r'
        'equired_source_read_set) AS enterprise_reads_capa(value) \nWHERE NOT (EXISTS'
        ' (SELECT 1 \nFROM enterprise_authoritative_artifacts_capa \nWHERE enterprise'
        '_authoritative_artifacts_capa.tenant_id = shared_enterprise_quality_issue_ve'
        'rsions.tenant_id AND enterprise_authoritative_artifacts_capa.source_id = CAS'
        "T((enterprise_reads_capa.value ->> 'artifact_id') AS UUID))))) AND ((shared_"
        "enterprise_quality_issue_versions.issue_snapshot['capa']) ->> 'id') IS NOT N"
        'ULL)\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_capa '
        '\nWHERE authoritative_enterprise_sources_capa.tenant_id = t AND authoritativ'
        'e_enterprise_sources_capa.category_id = c AND CAST(authoritative_enterprise_'
        "sources_capa.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritat"
        "ive_enterprise_sources_capa.source_revision AS TEXT) = expected->>'source_re"
        "vision' AND authoritative_enterprise_sources_capa.content_hash = expected->>"
        "'content_hash') AS anon_1 INTO visible;\n WHEN 'change' THEN\n  WITH enterpr"
        "ise_authoritative_artifacts_change AS \n(SELECT 'artifact' AS source_type, a"
        'rtifact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, '
        'artifact_versions.category_id AS category_id, artifact_versions.product_id A'
        'S product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS propos'
        'al_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision AS'
        ' source_revision, artifact_versions.title AS title, artifact_versions.conten'
        't_hash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSON'
        "B) AS structured, 'untrusted' AS nature, artifact_versions.visibility != 'ca"
        "tegory' OR coalesce(products.visibility != 'category', false) OR coalesce(up"
        "loaded_originals.visibility != 'category', false) AS private, artifact_versi"
        'ons.original_id IS NOT NULL AS customer_original, true AS is_current, artifa'
        'ct_versions.created_at AS created_at, artifact_versions.original_id AS origi'
        'nal_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.orig'
        'inal_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]:'
        ":UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_"
        'versions LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.'
        'tenant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN upl'
        'oaded_originals ON uploaded_originals.tenant_id = artifact_versions.tenant_i'
        'd AND uploaded_originals.id = artifact_versions.original_id AND uploaded_ori'
        'ginals.category_id = artifact_versions.category_id AND uploaded_originals.pr'
        'oduct_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN o'
        'riginal_security ON original_security.tenant_id = uploaded_originals.tenant_'
        'id AND original_security.original_id = uploaded_originals.id \nWHERE artifac'
        "t_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), "
        "'') AS UUID) AND artifact_versions.status = 'active' AND artifact_versions.c"
        'ategory_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products'
        '.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_orig'
        "inals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_o"
        "riginals.scan_status = 'clean' AND original_security.source_state = 'active'"
        " AND original_security.disposition = 'active' AND original_security.current_"
        'request_id IS NOT NULL)), \nshared_enterprise_change_request_versions AS MAT'
        'ERIALIZED \n(SELECT change_request_versions.product_id AS product_id, change'
        '_request_versions.project_id AS project_id, change_request_versions.change_i'
        'd AS change_id, change_request_versions.revision AS revision, change_request'
        '_versions.previous_version_id AS previous_version_id, change_request_version'
        's.previous_revision AS previous_revision, change_request_versions.owner_id A'
        'S owner_id, change_request_versions.visibility AS visibility, change_request'
        '_versions.status AS status, change_request_versions.operation AS operation, '
        'change_request_versions.intent_digest AS intent_digest, change_request_versi'
        'ons.request_snapshot AS request_snapshot, change_request_versions.request_sh'
        'a256 AS request_sha256, change_request_versions.sources AS sources, change_r'
        'equest_versions.required_source_read_set AS required_source_read_set, change'
        '_request_versions.source_basis AS source_basis, change_request_versions.auth'
        'ority_snapshot AS authority_snapshot, change_request_versions.id AS id, chan'
        'ge_request_versions.tenant_id AS tenant_id, change_request_versions.created_'
        'at AS created_at, change_request_versions.category_id AS category_id \nFROM '
        'change_request_versions \nWHERE change_request_versions.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpr"
        'ise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, pr'
        'ojects.owner_id AS owner_id, projects.name AS name, projects.purpose AS purp'
        'ose, projects.scope AS scope, projects.visibility AS visibility, projects.st'
        'atus AS status, projects.revision AS revision, projects.current_plan_id AS c'
        'urrent_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id A'
        'S trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, '
        'projects.tenant_id AS tenant_id, projects.created_at AS created_at, projects'
        '.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAS'
        "T(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_en"
        'terprise_products AS MATERIALIZED \n(SELECT products.name AS name, products.'
        'purpose AS purpose, products.revision AS revision, products.lifecycle_epoch '
        'AS lifecycle_epoch, products.status AS status, products.owner_id AS owner_id'
        ', products.parent_product_id AS parent_product_id, products.category_id AS c'
        'ategory_id, products.visibility AS visibility, products.target_price AS targ'
        'et_price, products.target_price_currency AS target_price_currency, products.'
        'target_price_basis AS target_price_basis, products.target_price_includes_tax'
        ' AS target_price_includes_tax, products.target_price_as_of AS target_price_a'
        's_of, products.id AS id, products.tenant_id AS tenant_id, products.created_a'
        't AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_cha"
        'nge_request_currents AS MATERIALIZED \n(SELECT change_request_currents.produ'
        'ct_id AS product_id, change_request_currents.change_id AS change_id, change_'
        'request_currents.version_id AS version_id, change_request_currents.revision '
        'AS revision, change_request_currents.id AS id, change_request_currents.tenan'
        't_id AS tenant_id, change_request_currents.created_at AS created_at, change_'
        'request_currents.category_id AS category_id \nFROM change_request_currents '
        "\nWHERE change_request_currents.tenant_id = CAST(nullif(current_setting('pdo"
        "s.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_chang"
        "e AS \n(SELECT 'change' AS source_type, shared_enterprise_change_request_ver"
        'sions.id AS source_id, shared_enterprise_change_request_versions.tenant_id A'
        'S tenant_id, shared_enterprise_change_request_versions.category_id AS catego'
        'ry_id, shared_enterprise_change_request_versions.product_id AS product_id, s'
        'hared_enterprise_change_request_versions.project_id AS project_id, CAST(NULL'
        ' AS UUID) AS proposal_id, shared_enterprise_change_request_versions.owner_id'
        ' AS owner_id, shared_enterprise_change_request_versions.revision AS source_r'
        "evision, shared_enterprise_change_request_versions.request_snapshot ->> 'tit"
        "le' AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_"
        "id', shared_enterprise_change_request_versions.change_id, 'kind', 'change', "
        "'facts', jsonb_build_object('id', shared_enterprise_change_request_versions."
        "request_snapshot['id'], 'title', shared_enterprise_change_request_versions.r"
        "equest_snapshot['title'], 'reason', shared_enterprise_change_request_version"
        "s.request_snapshot['reason'], 'status', shared_enterprise_change_request_ver"
        "sions.request_snapshot['status'], 'needs_recheck', shared_enterprise_change_"
        "request_versions.request_snapshot['needs_recheck'], 'recheck_reasons', share"
        "d_enterprise_change_request_versions.request_snapshot['recheck_reasons']) ||"
        " jsonb_build_object('orders', (SELECT coalesce(jsonb_agg(jsonb_build_object("
        "'id', enterprise_change_orders.value['id'], 'plan_items', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('id', enterprise_change_items.value['id'], 'disc"
        "ipline', enterprise_change_items.value['discipline'], 'verification_requirem"
        "ent', enterprise_change_items.value['verification_requirement'], 'intent_kin"
        "d', enterprise_change_items.value['intent']['kind']) ORDER BY enterprise_cha"
        'nge_items.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_el'
        "ements(coalesce(enterprise_change_orders.value['plan']['items'], CAST('[]' A"
        "S JSONB))) WITH ORDINALITY AS enterprise_change_items(value, ordinal)), 'app"
        "rovals', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', enterpris"
        "e_change_approvals.value['actor_id'], 'at', enterprise_change_approvals.valu"
        "e['at'], 'discipline', enterprise_change_approvals.value['discipline'], 'tex"
        "t', enterprise_change_approvals.value['text']) ORDER BY enterprise_change_ap"
        'provals.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elem'
        "ents(coalesce(enterprise_change_orders.value['approvals'], CAST('[]' AS JSON"
        "B))) WITH ORDINALITY AS enterprise_change_approvals(value, ordinal)), 'imple"
        "mentations', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterp"
        "rise_change_implementations.value['item_id'], 'executor_id', enterprise_chan"
        "ge_implementations.value['executor_id'], 'outcome', enterprise_change_implem"
        "entations.value['outcome'], 'occurred_at', enterprise_change_implementations"
        ".value['occurred_at'], 'received_at', enterprise_change_implementations.valu"
        "e['received_at'], 'note', enterprise_change_implementations.value['note']) O"
        'RDER BY enterprise_change_implementations.ordinal), jsonb_build_array()) AS '
        'coalesce_4 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.val'
        "ue['implementations'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_c"
        "hange_implementations(value, ordinal)), 'effectivity', (SELECT coalesce(json"
        "b_agg(jsonb_build_object('item_id', enterprise_change_effectivity.value['ite"
        "m_id'], 'stage', enterprise_change_effectivity.value['stage'], 'outcome', en"
        "terprise_change_effectivity.value['outcome'], 'covered_units', enterprise_ch"
        "ange_effectivity.value['covered_units'], 'occurred_at', enterprise_change_ef"
        "fectivity.value['occurred_at'], 'received_at', enterprise_change_effectivity"
        ".value['received_at']) ORDER BY enterprise_change_effectivity.ordinal), json"
        'b_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(coalesce(enterpri'
        "se_change_orders.value['effectivity'], CAST('[]' AS JSONB))) WITH ORDINALITY"
        " AS enterprise_change_effectivity(value, ordinal)), 'verifications', (SELECT"
        " coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise_change_verific"
        "ations.value['actor_id'], 'at', enterprise_change_verifications.value['at'],"
        " 'text', enterprise_change_verifications.value['text'], 'result', enterprise"
        "_change_verifications.value['fact']['result'], 'applicable_as_recorded', ent"
        "erprise_change_verifications.value['fact']['applicable']) ORDER BY enterpris"
        'e_change_verifications.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM j'
        "sonb_array_elements(coalesce(enterprise_change_orders.value['verifications']"
        ", CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_verifications(v"
        "alue, ordinal)), 'closure', jsonb_build_object('text', enterprise_change_ord"
        "ers.value['closure']['text'], 'actor_id', enterprise_change_orders.value['cl"
        "osure']['actor_id'], 'at', enterprise_change_orders.value['closure']['at']))"
        ' ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesc'
        'e_1 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.re'
        "quest_snapshot['orders']) WITH ORDINALITY AS enterprise_change_orders(value,"
        " ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('t"
        "ype', 'artifact', 'id', enterprise_reads_change.value['artifact_id'], 'versi"
        "on', enterprise_reads_change.value['expected_revision']) ORDER BY enterprise"
        "_reads_change.value ->> 'artifact_id', enterprise_reads_change.value ->> 'ex"
        "pected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_ele"
        'ments(shared_enterprise_change_request_versions.required_source_read_set) AS'
        " enterprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT),"
        " 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_change_request_versions.change_id, 'kind', 'change', 'fac"
        "ts', jsonb_build_object('id', shared_enterprise_change_request_versions.requ"
        "est_snapshot['id'], 'title', shared_enterprise_change_request_versions.reque"
        "st_snapshot['title'], 'reason', shared_enterprise_change_request_versions.re"
        "quest_snapshot['reason'], 'status', shared_enterprise_change_request_version"
        "s.request_snapshot['status'], 'needs_recheck', shared_enterprise_change_requ"
        "est_versions.request_snapshot['needs_recheck'], 'recheck_reasons', shared_en"
        "terprise_change_request_versions.request_snapshot['recheck_reasons']) || jso"
        "nb_build_object('orders', (SELECT coalesce(jsonb_agg(jsonb_build_object('id'"
        ", enterprise_change_orders.value['id'], 'plan_items', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('id', enterprise_change_items.value['id'], 'discipli"
        "ne', enterprise_change_items.value['discipline'], 'verification_requirement'"
        ", enterprise_change_items.value['verification_requirement'], 'intent_kind', "
        "enterprise_change_items.value['intent']['kind']) ORDER BY enterprise_change_"
        'items.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elemen'
        "ts(coalesce(enterprise_change_orders.value['plan']['items'], CAST('[]' AS JS"
        "ONB))) WITH ORDINALITY AS enterprise_change_items(value, ordinal)), 'approva"
        "ls', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise_ch"
        "ange_approvals.value['actor_id'], 'at', enterprise_change_approvals.value['a"
        "t'], 'discipline', enterprise_change_approvals.value['discipline'], 'text', "
        "enterprise_change_approvals.value['text']) ORDER BY enterprise_change_approv"
        'als.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements'
        "(coalesce(enterprise_change_orders.value['approvals'], CAST('[]' AS JSONB)))"
        " WITH ORDINALITY AS enterprise_change_approvals(value, ordinal)), 'implement"
        "ations', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterprise"
        "_change_implementations.value['item_id'], 'executor_id', enterprise_change_i"
        "mplementations.value['executor_id'], 'outcome', enterprise_change_implementa"
        "tions.value['outcome'], 'occurred_at', enterprise_change_implementations.val"
        "ue['occurred_at'], 'received_at', enterprise_change_implementations.value['r"
        "eceived_at'], 'note', enterprise_change_implementations.value['note']) ORDER"
        ' BY enterprise_change_implementations.ordinal), jsonb_build_array()) AS coal'
        "esce_4 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['"
        "implementations'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_chang"
        "e_implementations(value, ordinal)), 'effectivity', (SELECT coalesce(jsonb_ag"
        "g(jsonb_build_object('item_id', enterprise_change_effectivity.value['item_id"
        "'], 'stage', enterprise_change_effectivity.value['stage'], 'outcome', enterp"
        "rise_change_effectivity.value['outcome'], 'covered_units', enterprise_change"
        "_effectivity.value['covered_units'], 'occurred_at', enterprise_change_effect"
        "ivity.value['occurred_at'], 'received_at', enterprise_change_effectivity.val"
        "ue['received_at']) ORDER BY enterprise_change_effectivity.ordinal), jsonb_bu"
        'ild_array()) AS coalesce_5 \nFROM jsonb_array_elements(coalesce(enterprise_c'
        "hange_orders.value['effectivity'], CAST('[]' AS JSONB))) WITH ORDINALITY AS "
        "enterprise_change_effectivity(value, ordinal)), 'verifications', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('actor_id', enterprise_change_verificatio"
        "ns.value['actor_id'], 'at', enterprise_change_verifications.value['at'], 'te"
        "xt', enterprise_change_verifications.value['text'], 'result', enterprise_cha"
        "nge_verifications.value['fact']['result'], 'applicable_as_recorded', enterpr"
        "ise_change_verifications.value['fact']['applicable']) ORDER BY enterprise_ch"
        'ange_verifications.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM jsonb'
        "_array_elements(coalesce(enterprise_change_orders.value['verifications'], CA"
        "ST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_verifications(value"
        ", ordinal)), 'closure', jsonb_build_object('text', enterprise_change_orders."
        "value['closure']['text'], 'actor_id', enterprise_change_orders.value['closur"
        "e']['actor_id'], 'at', enterprise_change_orders.value['closure']['at'])) ORD"
        'ER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesce_1 '
        '\nFROM jsonb_array_elements(shared_enterprise_change_request_versions.reques'
        "t_snapshot['orders']) WITH ORDINALITY AS enterprise_change_orders(value, ord"
        "inal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type'"
        ", 'artifact', 'id', enterprise_reads_change.value['artifact_id'], 'version',"
        " enterprise_reads_change.value['expected_revision']) ORDER BY enterprise_rea"
        "ds_change.value ->> 'artifact_id', enterprise_reads_change.value ->> 'expect"
        "ed_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_element"
        's(shared_enterprise_change_request_versions.required_source_read_set) AS ent'
        "erprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) "
        "AS body, CAST(jsonb_build_object('object_id', shared_enterprise_change_reque"
        "st_versions.change_id, 'kind', 'change', 'facts', jsonb_build_object('id', s"
        "hared_enterprise_change_request_versions.request_snapshot['id'], 'title', sh"
        "ared_enterprise_change_request_versions.request_snapshot['title'], 'reason',"
        " shared_enterprise_change_request_versions.request_snapshot['reason'], 'stat"
        "us', shared_enterprise_change_request_versions.request_snapshot['status'], '"
        "needs_recheck', shared_enterprise_change_request_versions.request_snapshot['"
        "needs_recheck'], 'recheck_reasons', shared_enterprise_change_request_version"
        "s.request_snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELE"
        "CT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.valu"
        "e['id'], 'plan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', e"
        "nterprise_change_items.value['id'], 'discipline', enterprise_change_items.va"
        "lue['discipline'], 'verification_requirement', enterprise_change_items.value"
        "['verification_requirement'], 'intent_kind', enterprise_change_items.value['"
        "intent']['kind']) ORDER BY enterprise_change_items.ordinal), jsonb_build_arr"
        'ay()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_o'
        "rders.value['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enter"
        "prise_change_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg"
        "(jsonb_build_object('actor_id', enterprise_change_approvals.value['actor_id'"
        "], 'at', enterprise_change_approvals.value['at'], 'discipline', enterprise_c"
        "hange_approvals.value['discipline'], 'text', enterprise_change_approvals.val"
        "ue['text']) ORDER BY enterprise_change_approvals.ordinal), jsonb_build_array"
        '()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(enterprise_change_ord'
        "ers.value['approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_"
        "change_approvals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('item_id', enterprise_change_implementations.value['"
        "item_id'], 'executor_id', enterprise_change_implementations.value['executor_"
        "id'], 'outcome', enterprise_change_implementations.value['outcome'], 'occurr"
        "ed_at', enterprise_change_implementations.value['occurred_at'], 'received_at"
        "', enterprise_change_implementations.value['received_at'], 'note', enterpris"
        "e_change_implementations.value['note']) ORDER BY enterprise_change_implement"
        'ations.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_eleme'
        "nts(coalesce(enterprise_change_orders.value['implementations'], CAST('[]' AS"
        ' JSONB))) WITH ORDINALITY AS enterprise_change_implementations(value, ordina'
        "l)), 'effectivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id',"
        " enterprise_change_effectivity.value['item_id'], 'stage', enterprise_change_"
        "effectivity.value['stage'], 'outcome', enterprise_change_effectivity.value['"
        "outcome'], 'covered_units', enterprise_change_effectivity.value['covered_uni"
        "ts'], 'occurred_at', enterprise_change_effectivity.value['occurred_at'], 're"
        "ceived_at', enterprise_change_effectivity.value['received_at']) ORDER BY ent"
        'erprise_change_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 \nFR'
        "OM jsonb_array_elements(coalesce(enterprise_change_orders.value['effectivity"
        "'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(v"
        "alue, ordinal)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_obj"
        "ect('actor_id', enterprise_change_verifications.value['actor_id'], 'at', ent"
        "erprise_change_verifications.value['at'], 'text', enterprise_change_verifica"
        "tions.value['text'], 'result', enterprise_change_verifications.value['fact']"
        "['result'], 'applicable_as_recorded', enterprise_change_verifications.value["
        "'fact']['applicable']) ORDER BY enterprise_change_verifications.ordinal), js"
        'onb_build_array()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterp'
        "rise_change_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINA"
        "LITY AS enterprise_change_verifications(value, ordinal)), 'closure', jsonb_b"
        "uild_object('text', enterprise_change_orders.value['closure']['text'], 'acto"
        "r_id', enterprise_change_orders.value['closure']['actor_id'], 'at', enterpri"
        "se_change_orders.value['closure']['at'])) ORDER BY enterprise_change_orders."
        'ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(sha'
        "red_enterprise_change_request_versions.request_snapshot['orders']) WITH ORDI"
        "NALITY AS enterprise_change_orders(value, ordinal))), 'source_refs', (SELECT"
        " coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_"
        "reads_change.value['artifact_id'], 'version', enterprise_reads_change.value["
        "'expected_revision']) ORDER BY enterprise_reads_change.value ->> 'artifact_i"
        "d', enterprise_reads_change.value ->> 'expected_revision'), jsonb_build_arra"
        'y()) AS coalesce_7 \nFROM jsonb_array_elements(shared_enterprise_change_requ'
        "est_versions.required_source_read_set) AS enterprise_reads_change(value)), '"
        "record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, "
        "shared_enterprise_change_request_versions.visibility != 'category' OR shared"
        "_enterprise_projects.visibility != 'category' OR shared_enterprise_products."
        "visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(sh"
        'ared_enterprise_change_request_versions.required_source_read_set) AS enterpr'
        'ise_reads_change(value) JOIN enterprise_authoritative_artifacts_change ON en'
        'terprise_authoritative_artifacts_change.tenant_id = shared_enterprise_change'
        '_request_versions.tenant_id AND enterprise_authoritative_artifacts_change.so'
        "urce_id = CAST((enterprise_reads_change.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_change.private)) AS private, EXISTS'
        ' (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_change_request_vers'
        'ions.required_source_read_set) AS enterprise_reads_change(value) JOIN enterp'
        'rise_authoritative_artifacts_change ON enterprise_authoritative_artifacts_ch'
        'ange.tenant_id = shared_enterprise_change_request_versions.tenant_id AND ent'
        'erprise_authoritative_artifacts_change.source_id = CAST((enterprise_reads_ch'
        "ange.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_arti"
        'facts_change.customer_original) AS customer_original, shared_enterprise_chan'
        'ge_request_currents.version_id = shared_enterprise_change_request_versions.i'
        'd AS is_current, shared_enterprise_change_request_versions.created_at AS cre'
        'ated_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_change_request'
        '_versions.change_id AS object_id, (SELECT coalesce(array_agg(enterprise_auth'
        'oritative_artifacts_change.original_id), ARRAY[]::UUID[]) AS coalesce_8 \nFR'
        'OM jsonb_array_elements(shared_enterprise_change_request_versions.required_s'
        'ource_read_set) AS enterprise_reads_change(value) JOIN enterprise_authoritat'
        'ive_artifacts_change ON enterprise_authoritative_artifacts_change.tenant_id '
        '= shared_enterprise_change_request_versions.tenant_id AND enterprise_authori'
        'tative_artifacts_change.source_id = CAST((enterprise_reads_change.value ->> '
        "'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_change.or"
        'iginal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM j'
        'sonb_array_elements(shared_enterprise_change_request_versions.required_sourc'
        'e_read_set) AS enterprise_reads_change(value) JOIN enterprise_authoritative_'
        'artifacts_change ON enterprise_authoritative_artifacts_change.tenant_id = sh'
        'ared_enterprise_change_request_versions.tenant_id AND enterprise_authoritati'
        "ve_artifacts_change.source_id = CAST((enterprise_reads_change.value ->> 'art"
        "ifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_change.source"
        "_revision != CAST((enterprise_reads_change.value ->> 'expected_revision') AS"
        " INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nF"
        'ROM shared_enterprise_change_request_versions JOIN shared_enterprise_project'
        's ON shared_enterprise_projects.tenant_id = shared_enterprise_change_request'
        '_versions.tenant_id AND shared_enterprise_projects.product_id = shared_enter'
        'prise_change_request_versions.product_id AND shared_enterprise_projects.id ='
        ' shared_enterprise_change_request_versions.project_id AND shared_enterprise_'
        'projects.category_id = shared_enterprise_change_request_versions.category_id'
        ' JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id = s'
        'hared_enterprise_change_request_versions.tenant_id AND shared_enterprise_pro'
        'ducts.id = shared_enterprise_change_request_versions.product_id AND shared_e'
        'nterprise_products.category_id = shared_enterprise_change_request_versions.c'
        'ategory_id JOIN shared_enterprise_change_request_currents ON shared_enterpri'
        'se_change_request_currents.tenant_id = shared_enterprise_change_request_vers'
        'ions.tenant_id AND shared_enterprise_change_request_currents.product_id = sh'
        'ared_enterprise_change_request_versions.product_id AND shared_enterprise_cha'
        'nge_request_currents.change_id = shared_enterprise_change_request_versions.c'
        'hange_id \nWHERE shared_enterprise_change_request_versions.tenant_id = CAST('
        "nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS"
        ' (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_change_request_vers'
        'ions.required_source_read_set) AS enterprise_reads_change(value) \nWHERE NOT'
        ' (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_change \nWHERE '
        'enterprise_authoritative_artifacts_change.tenant_id = shared_enterprise_chan'
        'ge_request_versions.tenant_id AND enterprise_authoritative_artifacts_change.'
        "source_id = CAST((enterprise_reads_change.value ->> 'artifact_id') AS UUID))"
        '))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_chang'
        'e \nWHERE authoritative_enterprise_sources_change.tenant_id = t AND authorit'
        'ative_enterprise_sources_change.category_id = c AND CAST(authoritative_enter'
        "prise_sources_change.source_id AS TEXT) = expected->>'source_id' AND CAST(au"
        'thoritative_enterprise_sources_change.source_revision AS TEXT) = expected->>'
        "'source_revision' AND authoritative_enterprise_sources_change.content_hash ="
        " expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'external_wait' T"
        "HEN\n  WITH enterprise_authoritative_artifacts_external_wait AS \n(SELECT 'a"
        "rtifact' AS source_type, artifact_versions.id AS source_id, artifact_version"
        's.tenant_id AS tenant_id, artifact_versions.category_id AS category_id, arti'
        'fact_versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CA'
        'ST(NULL AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, art'
        'ifact_versions.revision AS source_revision, artifact_versions.title AS title'
        ', artifact_versions.content_hash AS content_hash, artifact_versions.content '
        "AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_"
        "versions.visibility != 'category' OR coalesce(products.visibility != 'catego"
        "ry', false) OR coalesce(uploaded_originals.visibility != 'category', false) "
        'AS private, artifact_versions.original_id IS NOT NULL AS customer_original, '
        'true AS is_current, artifact_versions.created_at AS created_at, artifact_ver'
        'sions.original_id AS original_id, artifact_versions.id AS object_id, CASE WH'
        'EN (artifact_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.'
        "original_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_bas"
        'is_status \nFROM artifact_versions LEFT OUTER JOIN products ON products.tena'
        'nt_id = artifact_versions.tenant_id AND products.id = artifact_versions.prod'
        'uct_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = '
        'artifact_versions.tenant_id AND uploaded_originals.id = artifact_versions.or'
        'iginal_id AND uploaded_originals.category_id = artifact_versions.category_id'
        ' AND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.pr'
        'oduct_id LEFT OUTER JOIN original_security ON original_security.tenant_id = '
        'uploaded_originals.tenant_id AND original_security.original_id = uploaded_or'
        'iginals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(current_setting'
        "('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status = 'activ"
        "e' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.prod"
        'uct_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_i'
        'd IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status'
        " = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_securi"
        "ty.source_state = 'active' AND original_security.disposition = 'active' AND "
        'original_security.current_request_id IS NOT NULL)), \nshared_enterprise_exte'
        'rnal_wait_versions AS MATERIALIZED \n(SELECT external_wait_versions.wait_id '
        'AS wait_id, external_wait_versions.previous_id AS previous_id, external_wait'
        '_versions.previous_revision AS previous_revision, external_wait_versions.act'
        'ion AS action, external_wait_versions.state AS state, external_wait_versions'
        '.revision AS revision, external_wait_versions.writer_id AS writer_id, extern'
        'al_wait_versions.actor_id AS actor_id, external_wait_versions.requester_id A'
        'S requester_id, external_wait_versions.operation AS operation, external_wait'
        '_versions.command_id AS command_id, external_wait_versions.command AS comman'
        'd, external_wait_versions.sources AS sources, external_wait_versions.reads A'
        'S reads, external_wait_versions.source_basis AS source_basis, external_wait_'
        'versions.body AS body, external_wait_versions.body_sha256 AS body_sha256, ex'
        'ternal_wait_versions.intent_digest AS intent_digest, external_wait_versions.'
        'request_digest AS request_digest, external_wait_versions.receipt_id AS recei'
        'pt_id, external_wait_versions.confirmation_id AS confirmation_id, external_w'
        'ait_versions.product_id AS product_id, external_wait_versions.project_id AS '
        'project_id, external_wait_versions.owner_id AS owner_id, external_wait_versi'
        'ons.visibility AS visibility, external_wait_versions.id AS id, external_wait'
        '_versions.tenant_id AS tenant_id, external_wait_versions.created_at AS creat'
        'ed_at, external_wait_versions.category_id AS category_id \nFROM external_wai'
        't_versions \nWHERE external_wait_versions.tenant_id = CAST(nullif(current_se'
        "tting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects A"
        'S MATERIALIZED \n(SELECT projects.product_id AS product_id, projects.owner_i'
        'd AS owner_id, projects.name AS name, projects.purpose AS purpose, projects.'
        'scope AS scope, projects.visibility AS visibility, projects.status AS status'
        ', projects.revision AS revision, projects.current_plan_id AS current_plan_id'
        ', projects.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, '
        'projects.g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenan'
        't_id AS tenant_id, projects.created_at AS created_at, projects.category_id A'
        'S category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(curre'
        "nt_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_produ"
        'cts AS MATERIALIZED \n(SELECT products.name AS name, products.purpose AS pur'
        'pose, products.revision AS revision, products.lifecycle_epoch AS lifecycle_e'
        'poch, products.status AS status, products.owner_id AS owner_id, products.par'
        'ent_product_id AS parent_product_id, products.category_id AS category_id, pr'
        'oducts.visibility AS visibility, products.target_price AS target_price, prod'
        'ucts.target_price_currency AS target_price_currency, products.target_price_b'
        'asis AS target_price_basis, products.target_price_includes_tax AS target_pri'
        'ce_includes_tax, products.target_price_as_of AS target_price_as_of, products'
        '.id AS id, products.tenant_id AS tenant_id, products.created_at AS created_a'
        "t \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_setting('"
        "pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_external_wait_cur"
        'rents AS MATERIALIZED \n(SELECT external_wait_currents.wait_id AS wait_id, e'
        'xternal_wait_currents.version_id AS version_id, external_wait_currents.revis'
        'ion AS revision, external_wait_currents.state AS state, external_wait_curren'
        'ts.product_id AS product_id, external_wait_currents.project_id AS project_id'
        ', external_wait_currents.owner_id AS owner_id, external_wait_currents.visibi'
        'lity AS visibility, external_wait_currents.id AS id, external_wait_currents.'
        'tenant_id AS tenant_id, external_wait_currents.created_at AS created_at, ext'
        'ernal_wait_currents.category_id AS category_id \nFROM external_wait_currents'
        " \nWHERE external_wait_currents.tenant_id = CAST(nullif(current_setting('pdo"
        "s.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_exter"
        "nal_wait AS \n(SELECT 'external_wait' AS source_type, shared_enterprise_exte"
        'rnal_wait_versions.id AS source_id, shared_enterprise_external_wait_versions'
        '.tenant_id AS tenant_id, shared_enterprise_external_wait_versions.category_i'
        'd AS category_id, shared_enterprise_external_wait_versions.product_id AS pro'
        'duct_id, shared_enterprise_external_wait_versions.project_id AS project_id, '
        'CAST(NULL AS UUID) AS proposal_id, shared_enterprise_external_wait_versions.'
        'owner_id AS owner_id, shared_enterprise_external_wait_versions.revision AS s'
        "ource_revision, shared_enterprise_external_wait_versions.body ->> 'title' AS"
        " title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', s"
        "hared_enterprise_external_wait_versions.wait_id, 'kind', 'external_wait', 'f"
        "acts', jsonb_build_object('wait', jsonb_build_object('wait_id', shared_enter"
        "prise_external_wait_versions.body['wait_id'], 'revision', shared_enterprise_"
        "external_wait_versions.body['revision'], 'state', shared_enterprise_external"
        "_wait_versions.body['state'], 'responsible_id', shared_enterprise_external_w"
        "ait_versions.body['responsible_id'], 'title', shared_enterprise_external_wai"
        "t_versions.body['title'], 'target', shared_enterprise_external_wait_versions"
        ".body['target'], 'request_content', shared_enterprise_external_wait_versions"
        ".body['request_content'], 'closure_condition', shared_enterprise_external_wa"
        "it_versions.body['closure_condition'], 'blocking', shared_enterprise_externa"
        "l_wait_versions.body['blocking'], 'next_check_at', shared_enterprise_externa"
        "l_wait_versions.body['next_check_at'], 'original_timezone', shared_enterpris"
        "e_external_wait_versions.body['original_timezone']), 'delivery', jsonb_build"
        "_object('at', shared_enterprise_external_wait_versions.body['delivery']['at'"
        "], 'status', shared_enterprise_external_wait_versions.body['delivery']['stat"
        "us'], 'time_basis', shared_enterprise_external_wait_versions.body['delivery'"
        "]['time_basis']), 'commitment', jsonb_build_object('promised_at', shared_ent"
        "erprise_external_wait_versions.body['counterparty_commitment']['promised_at'"
        "], 'original_timezone', shared_enterprise_external_wait_versions.body['count"
        "erparty_commitment']['original_timezone']), 'reply', jsonb_build_object('at'"
        ", shared_enterprise_external_wait_versions.body['reply']['at'], 'status', sh"
        "ared_enterprise_external_wait_versions.body['reply']['status'], 'time_basis'"
        ", shared_enterprise_external_wait_versions.body['reply']['time_basis'])), 's"
        "ource_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact"
        "', 'id', enterprise_reads_external_wait.value['artifact_id'], 'version', ent"
        "erprise_reads_external_wait.value['expected_revision']) ORDER BY enterprise_"
        "reads_external_wait.value ->> 'artifact_id', enterprise_reads_external_wait."
        "value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM js"
        'onb_array_elements(shared_enterprise_external_wait_versions.reads) AS enterp'
        "rise_reads_external_wait(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT),"
        " 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_external_wait_versions.wait_id, 'kind', 'external_wait', "
        "'facts', jsonb_build_object('wait', jsonb_build_object('wait_id', shared_ent"
        "erprise_external_wait_versions.body['wait_id'], 'revision', shared_enterpris"
        "e_external_wait_versions.body['revision'], 'state', shared_enterprise_extern"
        "al_wait_versions.body['state'], 'responsible_id', shared_enterprise_external"
        "_wait_versions.body['responsible_id'], 'title', shared_enterprise_external_w"
        "ait_versions.body['title'], 'target', shared_enterprise_external_wait_versio"
        "ns.body['target'], 'request_content', shared_enterprise_external_wait_versio"
        "ns.body['request_content'], 'closure_condition', shared_enterprise_external_"
        "wait_versions.body['closure_condition'], 'blocking', shared_enterprise_exter"
        "nal_wait_versions.body['blocking'], 'next_check_at', shared_enterprise_exter"
        "nal_wait_versions.body['next_check_at'], 'original_timezone', shared_enterpr"
        "ise_external_wait_versions.body['original_timezone']), 'delivery', jsonb_bui"
        "ld_object('at', shared_enterprise_external_wait_versions.body['delivery']['a"
        "t'], 'status', shared_enterprise_external_wait_versions.body['delivery']['st"
        "atus'], 'time_basis', shared_enterprise_external_wait_versions.body['deliver"
        "y']['time_basis']), 'commitment', jsonb_build_object('promised_at', shared_e"
        "nterprise_external_wait_versions.body['counterparty_commitment']['promised_a"
        "t'], 'original_timezone', shared_enterprise_external_wait_versions.body['cou"
        "nterparty_commitment']['original_timezone']), 'reply', jsonb_build_object('a"
        "t', shared_enterprise_external_wait_versions.body['reply']['at'], 'status', "
        "shared_enterprise_external_wait_versions.body['reply']['status'], 'time_basi"
        "s', shared_enterprise_external_wait_versions.body['reply']['time_basis'])), "
        "'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_external_wait.value['artifact_id'], 'version', e"
        "nterprise_reads_external_wait.value['expected_revision']) ORDER BY enterpris"
        "e_reads_external_wait.value ->> 'artifact_id', enterprise_reads_external_wai"
        "t.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM "
        'jsonb_array_elements(shared_enterprise_external_wait_versions.reads) AS ente'
        "rprise_reads_external_wait(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enterprise_extern"
        "al_wait_versions.wait_id, 'kind', 'external_wait', 'facts', jsonb_build_obje"
        "ct('wait', jsonb_build_object('wait_id', shared_enterprise_external_wait_ver"
        "sions.body['wait_id'], 'revision', shared_enterprise_external_wait_versions."
        "body['revision'], 'state', shared_enterprise_external_wait_versions.body['st"
        "ate'], 'responsible_id', shared_enterprise_external_wait_versions.body['resp"
        "onsible_id'], 'title', shared_enterprise_external_wait_versions.body['title'"
        "], 'target', shared_enterprise_external_wait_versions.body['target'], 'reque"
        "st_content', shared_enterprise_external_wait_versions.body['request_content'"
        "], 'closure_condition', shared_enterprise_external_wait_versions.body['closu"
        "re_condition'], 'blocking', shared_enterprise_external_wait_versions.body['b"
        "locking'], 'next_check_at', shared_enterprise_external_wait_versions.body['n"
        "ext_check_at'], 'original_timezone', shared_enterprise_external_wait_version"
        "s.body['original_timezone']), 'delivery', jsonb_build_object('at', shared_en"
        "terprise_external_wait_versions.body['delivery']['at'], 'status', shared_ent"
        "erprise_external_wait_versions.body['delivery']['status'], 'time_basis', sha"
        "red_enterprise_external_wait_versions.body['delivery']['time_basis']), 'comm"
        "itment', jsonb_build_object('promised_at', shared_enterprise_external_wait_v"
        "ersions.body['counterparty_commitment']['promised_at'], 'original_timezone',"
        " shared_enterprise_external_wait_versions.body['counterparty_commitment']['o"
        "riginal_timezone']), 'reply', jsonb_build_object('at', shared_enterprise_ext"
        "ernal_wait_versions.body['reply']['at'], 'status', shared_enterprise_externa"
        "l_wait_versions.body['reply']['status'], 'time_basis', shared_enterprise_ext"
        "ernal_wait_versions.body['reply']['time_basis'])), 'source_refs', (SELECT co"
        "alesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_rea"
        "ds_external_wait.value['artifact_id'], 'version', enterprise_reads_external_"
        "wait.value['expected_revision']) ORDER BY enterprise_reads_external_wait.val"
        "ue ->> 'artifact_id', enterprise_reads_external_wait.value ->> 'expected_rev"
        "ision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shar"
        'ed_enterprise_external_wait_versions.reads) AS enterprise_reads_external_wai'
        "t(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured'"
        " AS nature, shared_enterprise_external_wait_versions.visibility != 'category"
        "' OR shared_enterprise_projects.visibility != 'category' OR shared_enterpris"
        "e_products.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_"
        'elements(shared_enterprise_external_wait_versions.reads) AS enterprise_reads'
        '_external_wait(value) JOIN enterprise_authoritative_artifacts_external_wait '
        'ON enterprise_authoritative_artifacts_external_wait.tenant_id = shared_enter'
        'prise_external_wait_versions.tenant_id AND enterprise_authoritative_artifact'
        "s_external_wait.source_id = CAST((enterprise_reads_external_wait.value ->> '"
        "artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_external_w"
        'ait.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(share'
        'd_enterprise_external_wait_versions.reads) AS enterprise_reads_external_wait'
        '(value) JOIN enterprise_authoritative_artifacts_external_wait ON enterprise_'
        'authoritative_artifacts_external_wait.tenant_id = shared_enterprise_external'
        '_wait_versions.tenant_id AND enterprise_authoritative_artifacts_external_wai'
        "t.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifact_id') "
        'AS UUID) \nWHERE enterprise_authoritative_artifacts_external_wait.customer_o'
        'riginal) AS customer_original, shared_enterprise_external_wait_currents.vers'
        'ion_id = shared_enterprise_external_wait_versions.id AS is_current, shared_e'
        'nterprise_external_wait_versions.created_at AS created_at, CAST(NULL AS UUID'
        ') AS original_id, shared_enterprise_external_wait_versions.wait_id AS object'
        '_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_external_'
        'wait.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_array_element'
        's(shared_enterprise_external_wait_versions.reads) AS enterprise_reads_extern'
        'al_wait(value) JOIN enterprise_authoritative_artifacts_external_wait ON ente'
        'rprise_authoritative_artifacts_external_wait.tenant_id = shared_enterprise_e'
        'xternal_wait_versions.tenant_id AND enterprise_authoritative_artifacts_exter'
        "nal_wait.source_id = CAST((enterprise_reads_external_wait.value ->> 'artifac"
        "t_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_external_wait.ori"
        'ginal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM js'
        'onb_array_elements(shared_enterprise_external_wait_versions.reads) AS enterp'
        'rise_reads_external_wait(value) JOIN enterprise_authoritative_artifacts_exte'
        'rnal_wait ON enterprise_authoritative_artifacts_external_wait.tenant_id = sh'
        'ared_enterprise_external_wait_versions.tenant_id AND enterprise_authoritativ'
        'e_artifacts_external_wait.source_id = CAST((enterprise_reads_external_wait.v'
        "alue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_"
        'external_wait.source_revision != CAST((enterprise_reads_external_wait.value '
        "->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' E"
        'ND AS read_basis_status \nFROM shared_enterprise_external_wait_versions JOIN'
        ' shared_enterprise_projects ON shared_enterprise_projects.tenant_id = shared'
        '_enterprise_external_wait_versions.tenant_id AND shared_enterprise_projects.'
        'product_id = shared_enterprise_external_wait_versions.product_id AND shared_'
        'enterprise_projects.id = shared_enterprise_external_wait_versions.project_id'
        ' AND shared_enterprise_projects.category_id = shared_enterprise_external_wai'
        't_versions.category_id JOIN shared_enterprise_products ON shared_enterprise_'
        'products.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND '
        'shared_enterprise_products.id = shared_enterprise_external_wait_versions.pro'
        'duct_id AND shared_enterprise_products.category_id = shared_enterprise_exter'
        'nal_wait_versions.category_id JOIN shared_enterprise_external_wait_currents '
        'ON shared_enterprise_external_wait_currents.tenant_id = shared_enterprise_ex'
        'ternal_wait_versions.tenant_id AND shared_enterprise_external_wait_currents.'
        'product_id = shared_enterprise_external_wait_versions.product_id AND shared_'
        'enterprise_external_wait_currents.wait_id = shared_enterprise_external_wait_'
        'versions.wait_id \nWHERE shared_enterprise_external_wait_versions.tenant_id '
        "= CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT "
        '(EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_external_wai'
        't_versions.reads) AS enterprise_reads_external_wait(value) \nWHERE NOT (EXIS'
        'TS (SELECT 1 \nFROM enterprise_authoritative_artifacts_external_wait \nWHERE'
        ' enterprise_authoritative_artifacts_external_wait.tenant_id = shared_enterpr'
        'ise_external_wait_versions.tenant_id AND enterprise_authoritative_artifacts_'
        "external_wait.source_id = CAST((enterprise_reads_external_wait.value ->> 'ar"
        "tifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_ent"
        'erprise_sources_external_wait \nWHERE authoritative_enterprise_sources_exter'
        'nal_wait.tenant_id = t AND authoritative_enterprise_sources_external_wait.ca'
        'tegory_id = c AND CAST(authoritative_enterprise_sources_external_wait.source'
        "_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sour"
        "ces_external_wait.source_revision AS TEXT) = expected->>'source_revision' AN"
        "D authoritative_enterprise_sources_external_wait.content_hash = expected->>'"
        "content_hash') AS anon_1 INTO visible;\n WHEN 'supply' THEN\n  WITH enterpri"
        "se_authoritative_artifacts_supply AS \n(SELECT 'artifact' AS source_type, ar"
        'tifact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id, a'
        'rtifact_versions.category_id AS category_id, artifact_versions.product_id AS'
        ' product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposa'
        'l_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision AS '
        'source_revision, artifact_versions.title AS title, artifact_versions.content'
        '_hash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB'
        ") AS structured, 'untrusted' AS nature, artifact_versions.visibility != 'cat"
        "egory' OR coalesce(products.visibility != 'category', false) OR coalesce(upl"
        "oaded_originals.visibility != 'category', false) AS private, artifact_versio"
        'ns.original_id IS NOT NULL AS customer_original, true AS is_current, artifac'
        't_versions.created_at AS created_at, artifact_versions.original_id AS origin'
        'al_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.origi'
        'nal_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::'
        "UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_v"
        'ersions LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.t'
        'enant_id AND products.id = artifact_versions.product_id LEFT OUTER JOIN uplo'
        'aded_originals ON uploaded_originals.tenant_id = artifact_versions.tenant_id'
        ' AND uploaded_originals.id = artifact_versions.original_id AND uploaded_orig'
        'inals.category_id = artifact_versions.category_id AND uploaded_originals.pro'
        'duct_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN or'
        'iginal_security ON original_security.tenant_id = uploaded_originals.tenant_i'
        'd AND original_security.original_id = uploaded_originals.id \nWHERE artifact'
        "_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '"
        "') AS UUID) AND artifact_versions.status = 'active' AND artifact_versions.ca"
        'tegory_id IS NOT NULL AND (artifact_versions.product_id IS NULL OR products.'
        'id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR uploaded_origi'
        "nals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_or"
        "iginals.scan_status = 'clean' AND original_security.source_state = 'active' "
        "AND original_security.disposition = 'active' AND original_security.current_r"
        'equest_id IS NOT NULL)), \nshared_enterprise_supply_snapshots AS MATERIALIZE'
        'D \n(SELECT supply_snapshots.revision AS revision, supply_snapshots.status A'
        'S status, supply_snapshots.capture_id AS capture_id, supply_snapshots.previo'
        'us_snapshot_id AS previous_snapshot_id, supply_snapshots.previous_revision A'
        'S previous_revision, supply_snapshots.snapshot AS snapshot, supply_snapshots'
        '.snapshot_sha256 AS snapshot_sha256, supply_snapshots.bound_demand AS bound_'
        'demand, supply_snapshots.reconciliation AS reconciliation, supply_snapshots.'
        'sources AS sources, supply_snapshots.product_id AS product_id, supply_snapsh'
        'ots.project_id AS project_id, supply_snapshots.build_id AS build_id, supply_'
        'snapshots.build_revision AS build_revision, supply_snapshots.owner_id AS own'
        'er_id, supply_snapshots.visibility AS visibility, supply_snapshots.reason AS'
        ' reason, supply_snapshots.required_source_read_set AS required_source_read_s'
        'et, supply_snapshots.id AS id, supply_snapshots.tenant_id AS tenant_id, supp'
        'ly_snapshots.created_at AS created_at, supply_snapshots.category_id AS categ'
        'ory_id \nFROM supply_snapshots \nWHERE supply_snapshots.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpr"
        'ise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, pr'
        'ojects.owner_id AS owner_id, projects.name AS name, projects.purpose AS purp'
        'ose, projects.scope AS scope, projects.visibility AS visibility, projects.st'
        'atus AS status, projects.revision AS revision, projects.current_plan_id AS c'
        'urrent_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id A'
        'S trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, '
        'projects.tenant_id AS tenant_id, projects.created_at AS created_at, projects'
        '.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAS'
        "T(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_en"
        'terprise_products AS MATERIALIZED \n(SELECT products.name AS name, products.'
        'purpose AS purpose, products.revision AS revision, products.lifecycle_epoch '
        'AS lifecycle_epoch, products.status AS status, products.owner_id AS owner_id'
        ', products.parent_product_id AS parent_product_id, products.category_id AS c'
        'ategory_id, products.visibility AS visibility, products.target_price AS targ'
        'et_price, products.target_price_currency AS target_price_currency, products.'
        'target_price_basis AS target_price_basis, products.target_price_includes_tax'
        ' AS target_price_includes_tax, products.target_price_as_of AS target_price_a'
        's_of, products.id AS id, products.tenant_id AS tenant_id, products.created_a'
        't AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_bui"
        'lds AS MATERIALIZED \n(SELECT builds.product_id AS product_id, builds.projec'
        't_id AS project_id, builds.project_revision AS project_revision, builds.engi'
        'neering_configuration_id AS engineering_configuration_id, builds.manufacturi'
        'ng_configuration_id AS manufacturing_configuration_id, builds.previous_build'
        '_id AS previous_build_id, builds.owner_id AS owner_id, builds.name AS name, '
        'builds.type AS type, builds.purpose AS purpose, builds.planned_quantity AS p'
        'lanned_quantity, builds.unit AS unit, builds.planned_start AS planned_start,'
        ' builds.planned_end AS planned_end, builds.verification_objectives AS verifi'
        'cation_objectives, builds.disposition_plan AS disposition_plan, builds.visib'
        'ility AS visibility, builds.revision AS revision, builds.status AS status, b'
        'uilds.id AS id, builds.tenant_id AS tenant_id, builds.created_at AS created_'
        'at, builds.category_id AS category_id \nFROM builds \nWHERE builds.tenant_id'
        " = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nsha"
        'red_enterprise_supply_current_snapshots AS MATERIALIZED \n(SELECT supply_cur'
        'rent_snapshots.product_id AS product_id, supply_current_snapshots.build_id A'
        'S build_id, supply_current_snapshots.snapshot_id AS snapshot_id, supply_curr'
        'ent_snapshots.snapshot_revision AS snapshot_revision, supply_current_snapsho'
        'ts.id AS id, supply_current_snapshots.tenant_id AS tenant_id, supply_current'
        '_snapshots.created_at AS created_at, supply_current_snapshots.category_id AS'
        ' category_id \nFROM supply_current_snapshots \nWHERE supply_current_snapshot'
        "s.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UU"
        "ID)), \nauthoritative_enterprise_sources_supply AS \n(SELECT 'supply' AS sou"
        'rce_type, shared_enterprise_supply_snapshots.id AS source_id, shared_enterpr'
        'ise_supply_snapshots.tenant_id AS tenant_id, shared_enterprise_supply_snapsh'
        'ots.category_id AS category_id, shared_enterprise_supply_snapshots.product_i'
        'd AS product_id, shared_enterprise_supply_snapshots.project_id AS project_id'
        ', CAST(NULL AS UUID) AS proposal_id, shared_enterprise_supply_snapshots.owne'
        'r_id AS owner_id, shared_enterprise_supply_snapshots.revision AS source_revi'
        "sion, '\u4f9b\u5e94\u627f\u8bfa \xb7 ' || CAST(shared_enterprise_supply_snap"
        'shots.build_id AS TEXT) AS title, encode(sha256(convert_to(CAST(CAST(jsonb_b'
        "uild_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', 'sup"
        "ply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_snaps"
        "hots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'commitm"
        "ents', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enterprise"
        "_supply_commitments.value['record_id'], 'supplier_id', enterprise_supply_com"
        "mitments.value['supplier_id'], 'material_id', enterprise_supply_commitments."
        "value['material_id'], 'quantity', enterprise_supply_commitments.value['quant"
        "ity'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_at', e"
        "nterprise_supply_commitments.value['expected_at']) ORDER BY enterprise_suppl"
        'y_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_arra'
        "y_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitments"
        "'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitments(v"
        "alue, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_obje"
        "ct('type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id'], '"
        "version', enterprise_reads_supply.value['expected_revision']) ORDER BY enter"
        "prise_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.value ->"
        "> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_arra"
        'y_elements(shared_enterprise_supply_snapshots.required_source_read_set) AS e'
        "nterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT),"
        " 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id',"
        " shared_enterprise_supply_snapshots.id, 'kind', 'supply', 'facts', jsonb_bui"
        "ld_object('build_id', shared_enterprise_supply_snapshots.build_id, 'status',"
        " shared_enterprise_supply_snapshots.status, 'commitments', (SELECT coalesce("
        "jsonb_agg(jsonb_build_object('record_id', enterprise_supply_commitments.valu"
        "e['record_id'], 'supplier_id', enterprise_supply_commitments.value['supplier"
        "_id'], 'material_id', enterprise_supply_commitments.value['material_id'], 'q"
        "uantity', enterprise_supply_commitments.value['quantity'], 'unit', enterpris"
        "e_supply_commitments.value['unit'], 'expected_at', enterprise_supply_commitm"
        "ents.value['expected_at']) ORDER BY enterprise_supply_commitments.ordinal), "
        'jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shar'
        "ed_enterprise_supply_snapshots.snapshot['commitments'], CAST('[]' AS JSONB))"
        ") WITH ORDINALITY AS enterprise_supply_commitments(value, ordinal))), 'sourc"
        "e_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', '"
        "id', enterprise_reads_supply.value['artifact_id'], 'version', enterprise_rea"
        "ds_supply.value['expected_revision']) ORDER BY enterprise_reads_supply.value"
        " ->> 'artifact_id', enterprise_reads_supply.value ->> 'expected_revision'), "
        'jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterp'
        'rise_supply_snapshots.required_source_read_set) AS enterprise_reads_supply(v'
        "alue)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_buil"
        "d_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', 'supply"
        "', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_snapshot"
        "s.build_id, 'status', shared_enterprise_supply_snapshots.status, 'commitment"
        "s', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enterprise_su"
        "pply_commitments.value['record_id'], 'supplier_id', enterprise_supply_commit"
        "ments.value['supplier_id'], 'material_id', enterprise_supply_commitments.val"
        "ue['material_id'], 'quantity', enterprise_supply_commitments.value['quantity"
        "'], 'unit', enterprise_supply_commitments.value['unit'], 'expected_at', ente"
        "rprise_supply_commitments.value['expected_at']) ORDER BY enterprise_supply_c"
        'ommitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_e'
        "lements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitments'],"
        " CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitments(valu"
        "e, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object("
        "'type', 'artifact', 'id', enterprise_reads_supply.value['artifact_id'], 'ver"
        "sion', enterprise_reads_supply.value['expected_revision']) ORDER BY enterpri"
        "se_reads_supply.value ->> 'artifact_id', enterprise_reads_supply.value ->> '"
        "expected_revision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_e"
        'lements(shared_enterprise_supply_snapshots.required_source_read_set) AS ente'
        "rprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS struct"
        "ured, 'structured' AS nature, shared_enterprise_supply_snapshots.visibility "
        "!= 'category' OR shared_enterprise_projects.visibility != 'category' OR shar"
        "ed_enterprise_products.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM "
        'jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_read'
        '_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritative_artifa'
        'cts_supply ON enterprise_authoritative_artifacts_supply.tenant_id = shared_e'
        'nterprise_supply_snapshots.tenant_id AND enterprise_authoritative_artifacts_'
        "supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS"
        ' UUID) \nWHERE enterprise_authoritative_artifacts_supply.private)) OR shared'
        "_enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1 \nF"
        'ROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_'
        'read_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritative_ar'
        'tifacts_supply ON enterprise_authoritative_artifacts_supply.tenant_id = shar'
        'ed_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_artifa'
        "cts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id'"
        ') AS UUID) \nWHERE enterprise_authoritative_artifacts_supply.customer_origin'
        'al) AS customer_original, shared_enterprise_supply_current_snapshots.snapsho'
        't_id = shared_enterprise_supply_snapshots.id AS is_current, shared_enterpris'
        'e_supply_snapshots.created_at AS created_at, CAST(NULL AS UUID) AS original_'
        'id, shared_enterprise_supply_snapshots.id AS object_id, (SELECT coalesce(arr'
        'ay_agg(enterprise_authoritative_artifacts_supply.original_id), ARRAY[]::UUID'
        '[]) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_supply_snaps'
        'hots.required_source_read_set) AS enterprise_reads_supply(value) JOIN enterp'
        'rise_authoritative_artifacts_supply ON enterprise_authoritative_artifacts_su'
        'pply.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise'
        '_authoritative_artifacts_supply.source_id = CAST((enterprise_reads_supply.va'
        "lue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_s"
        'upply.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 '
        '\nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_sour'
        'ce_read_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritative'
        '_artifacts_supply ON enterprise_authoritative_artifacts_supply.tenant_id = s'
        'hared_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_art'
        "ifacts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_"
        "id') AS UUID) \nWHERE enterprise_authoritative_artifacts_supply.source_revis"
        "ion != CAST((enterprise_reads_supply.value ->> 'expected_revision') AS INTEG"
        "ER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM sh"
        'ared_enterprise_supply_snapshots JOIN shared_enterprise_projects ON shared_e'
        'nterprise_projects.tenant_id = shared_enterprise_supply_snapshots.tenant_id '
        'AND shared_enterprise_projects.product_id = shared_enterprise_supply_snapsho'
        'ts.product_id AND shared_enterprise_projects.id = shared_enterprise_supply_s'
        'napshots.project_id AND shared_enterprise_projects.category_id = shared_ente'
        'rprise_supply_snapshots.category_id JOIN shared_enterprise_products ON share'
        'd_enterprise_products.tenant_id = shared_enterprise_supply_snapshots.tenant_'
        'id AND shared_enterprise_products.id = shared_enterprise_supply_snapshots.pr'
        'oduct_id AND shared_enterprise_products.category_id = shared_enterprise_supp'
        'ly_snapshots.category_id JOIN shared_enterprise_builds ON shared_enterprise_'
        'builds.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_e'
        'nterprise_builds.category_id = shared_enterprise_supply_snapshots.category_i'
        'd AND shared_enterprise_builds.product_id = shared_enterprise_supply_snapsho'
        'ts.product_id AND shared_enterprise_builds.project_id = shared_enterprise_su'
        'pply_snapshots.project_id AND shared_enterprise_builds.id = shared_enterpris'
        'e_supply_snapshots.build_id AND shared_enterprise_builds.revision = shared_e'
        'nterprise_supply_snapshots.build_revision JOIN shared_enterprise_supply_curr'
        'ent_snapshots ON shared_enterprise_supply_current_snapshots.tenant_id = shar'
        'ed_enterprise_supply_snapshots.tenant_id AND shared_enterprise_supply_curren'
        't_snapshots.product_id = shared_enterprise_supply_snapshots.product_id AND s'
        'hared_enterprise_supply_current_snapshots.build_id = shared_enterprise_suppl'
        'y_snapshots.build_id \nWHERE shared_enterprise_supply_snapshots.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (E"
        'XISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_supply_snapsho'
        'ts.required_source_read_set) AS enterprise_reads_supply(value) \nWHERE NOT ('
        'EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_supply \nWHERE en'
        'terprise_authoritative_artifacts_supply.tenant_id = shared_enterprise_supply'
        '_snapshots.tenant_id AND enterprise_authoritative_artifacts_supply.source_id'
        " = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID))))))\n SE"
        'LECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_supply \nWHERE'
        ' authoritative_enterprise_sources_supply.tenant_id = t AND authoritative_ent'
        'erprise_sources_supply.category_id = c AND CAST(authoritative_enterprise_sou'
        "rces_supply.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritati"
        "ve_enterprise_sources_supply.source_revision AS TEXT) = expected->>'source_r"
        "evision' AND authoritative_enterprise_sources_supply.content_hash = expected"
        "->>'content_hash') AS anon_1 INTO visible;\n WHEN 'build' THEN\n  WITH share"
        'd_enterprise_engineering_configurations AS MATERIALIZED \n(SELECT engineerin'
        'g_configurations.definition_id AS definition_id, engineering_configurations.'
        'definition_revision AS definition_revision, engineering_configurations.bom_i'
        'd AS bom_id, engineering_configurations.bom_revision AS bom_revision, engine'
        'ering_configurations.design_versions AS design_versions, engineering_configu'
        'rations.series_id AS series_id, engineering_configurations.previous_id AS pr'
        'evious_id, engineering_configurations.expected_previous_revision AS expected'
        '_previous_revision, engineering_configurations.reason AS reason, engineering'
        '_configurations.product_id AS product_id, engineering_configurations.owner_i'
        'd AS owner_id, engineering_configurations.name AS name, engineering_configur'
        'ations.status AS status, engineering_configurations.visibility AS visibility'
        ', engineering_configurations.revision AS revision, engineering_configuration'
        's.sources AS sources, engineering_configurations.required_source_read_set AS'
        ' required_source_read_set, engineering_configurations.id AS id, engineering_'
        'configurations.tenant_id AS tenant_id, engineering_configurations.created_at'
        ' AS created_at, engineering_configurations.category_id AS category_id \nFROM'
        ' engineering_configurations \nWHERE engineering_configurations.tenant_id = C'
        "AST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_"
        'enterprise_process_revisions AS MATERIALIZED \n(SELECT process_revisions.eng'
        'ineering_configuration_id AS engineering_configuration_id, process_revisions'
        '.engineering_revision AS engineering_revision, process_revisions.operations '
        'AS operations, process_revisions.site AS site, process_revisions.line AS lin'
        'e, process_revisions.series_id AS series_id, process_revisions.previous_id A'
        'S previous_id, process_revisions.expected_previous_revision AS expected_prev'
        'ious_revision, process_revisions.reason AS reason, process_revisions.product'
        '_id AS product_id, process_revisions.owner_id AS owner_id, process_revisions'
        '.name AS name, process_revisions.status AS status, process_revisions.visibil'
        'ity AS visibility, process_revisions.revision AS revision, process_revisions'
        '.sources AS sources, process_revisions.required_source_read_set AS required_'
        'source_read_set, process_revisions.id AS id, process_revisions.tenant_id AS '
        'tenant_id, process_revisions.created_at AS created_at, process_revisions.cat'
        'egory_id AS category_id \nFROM process_revisions \nWHERE process_revisions.t'
        "enant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)"
        "), \nenterprise_authoritative_artifacts_build AS \n(SELECT 'artifact' AS sou"
        'rce_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS '
        'tenant_id, artifact_versions.category_id AS category_id, artifact_versions.p'
        'roduct_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID'
        ') AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.'
        'revision AS source_revision, artifact_versions.title AS title, artifact_vers'
        'ions.content_hash AS content_hash, artifact_versions.content AS body, CAST(N'
        "ULL AS JSONB) AS structured, 'untrusted' AS nature, artifact_versions.visibi"
        "lity != 'category' OR coalesce(products.visibility != 'category', false) OR "
        "coalesce(uploaded_originals.visibility != 'category', false) AS private, art"
        'ifact_versions.original_id IS NOT NULL AS customer_original, true AS is_curr'
        'ent, artifact_versions.created_at AS created_at, artifact_versions.original_'
        'id AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_ve'
        'rsions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] EL'
        "SE ARRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFRO"
        'M artifact_versions LEFT OUTER JOIN products ON products.tenant_id = artifac'
        't_versions.tenant_id AND products.id = artifact_versions.product_id LEFT OUT'
        'ER JOIN uploaded_originals ON uploaded_originals.tenant_id = artifact_versio'
        'ns.tenant_id AND uploaded_originals.id = artifact_versions.original_id AND u'
        'ploaded_originals.category_id = artifact_versions.category_id AND uploaded_o'
        'riginals.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT O'
        'UTER JOIN original_security ON original_security.tenant_id = uploaded_origin'
        'als.tenant_id AND original_security.original_id = uploaded_originals.id \nWH'
        "ERE artifact_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_i"
        "d', true), '') AS UUID) AND artifact_versions.status = 'active' AND artifact"
        '_versions.category_id IS NOT NULL AND (artifact_versions.product_id IS NULL '
        'OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR up'
        "loaded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND"
        " uploaded_originals.scan_status = 'clean' AND original_security.source_state"
        " = 'active' AND original_security.disposition = 'active' AND original_securi"
        'ty.current_request_id IS NOT NULL)), \nshared_enterprise_builds AS MATERIALI'
        'ZED \n(SELECT builds.product_id AS product_id, builds.project_id AS project_'
        'id, builds.project_revision AS project_revision, builds.engineering_configur'
        'ation_id AS engineering_configuration_id, builds.manufacturing_configuration'
        '_id AS manufacturing_configuration_id, builds.previous_build_id AS previous_'
        'build_id, builds.owner_id AS owner_id, builds.name AS name, builds.type AS t'
        'ype, builds.purpose AS purpose, builds.planned_quantity AS planned_quantity,'
        ' builds.unit AS unit, builds.planned_start AS planned_start, builds.planned_'
        'end AS planned_end, builds.verification_objectives AS verification_objective'
        's, builds.disposition_plan AS disposition_plan, builds.visibility AS visibil'
        'ity, builds.revision AS revision, builds.status AS status, builds.id AS id, '
        'builds.tenant_id AS tenant_id, builds.created_at AS created_at, builds.categ'
        'ory_id AS category_id \nFROM builds \nWHERE builds.tenant_id = CAST(nullif(c'
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
        "setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_build_st"
        'arts AS MATERIALIZED \n(SELECT build_starts.product_id AS product_id, build_'
        'starts.project_id AS project_id, build_starts.build_id AS build_id, build_st'
        'arts.build_revision AS build_revision, build_starts.engineering_configuratio'
        'n_id AS engineering_configuration_id, build_starts.manufacturing_configurati'
        'on_id AS manufacturing_configuration_id, build_starts.assessment_id AS asses'
        'sment_id, build_starts.assessment_revision AS assessment_revision, build_sta'
        'rts.assessment_sha256 AS assessment_sha256, build_starts.engineering_authori'
        'zation_id AS engineering_authorization_id, build_starts.engineering_authoriz'
        'ation_revision AS engineering_authorization_revision, build_starts.manufactu'
        'ring_authorization_id AS manufacturing_authorization_id, build_starts.manufa'
        'cturing_authorization_revision AS manufacturing_authorization_revision, buil'
        'd_starts.engineering_role AS engineering_role, build_starts.manufacturing_ro'
        'le AS manufacturing_role, build_starts.revision AS revision, build_starts.ow'
        'ner_id AS owner_id, build_starts.visibility AS visibility, build_starts.stat'
        'us AS status, build_starts.occurred_at AS occurred_at, build_starts.occurred'
        '_timezone AS occurred_timezone, build_starts.execution_scope AS execution_sc'
        'ope, build_starts.event_source AS event_source, build_starts.authority_snaps'
        'hot AS authority_snapshot, build_starts.reservations AS reservations, build_'
        'starts.sources AS sources, build_starts.required_source_read_set AS required'
        '_source_read_set, build_starts.snapshot_sha256 AS snapshot_sha256, build_sta'
        'rts.intent_digest AS intent_digest, build_starts.reason AS reason, build_sta'
        'rts.id AS id, build_starts.tenant_id AS tenant_id, build_starts.created_at A'
        'S created_at, build_starts.category_id AS category_id \nFROM build_starts \n'
        "WHERE build_starts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id',"
        " true), '') AS UUID)), \nshared_enterprise_actual_configurations AS MATERIAL"
        'IZED \n(SELECT actual_configurations.status AS status, actual_configurations'
        '.planned_engineering_configuration_id AS planned_engineering_configuration_i'
        'd, actual_configurations.planned_manufacturing_configuration_id AS planned_m'
        'anufacturing_configuration_id, actual_configurations.actual_engineering_conf'
        'iguration_id AS actual_engineering_configuration_id, actual_configurations.a'
        'ctual_engineering_revision AS actual_engineering_revision, actual_configurat'
        'ions.actual_manufacturing_configuration_id AS actual_manufacturing_configura'
        'tion_id, actual_configurations.actual_manufacturing_revision AS actual_manuf'
        'acturing_revision, actual_configurations.observed_at AS observed_at, actual_'
        'configurations.differences AS differences, actual_configurations.product_id '
        'AS product_id, actual_configurations.project_id AS project_id, actual_config'
        'urations.build_id AS build_id, actual_configurations.build_revision AS build'
        '_revision, actual_configurations.owner_id AS owner_id, actual_configurations'
        '.visibility AS visibility, actual_configurations.revision AS revision, actua'
        'l_configurations.reason AS reason, actual_configurations.sources AS sources,'
        ' actual_configurations.required_source_read_set AS required_source_read_set,'
        ' actual_configurations.id AS id, actual_configurations.tenant_id AS tenant_i'
        'd, actual_configurations.created_at AS created_at, actual_configurations.cat'
        'egory_id AS category_id \nFROM actual_configurations \nWHERE actual_configur'
        "ations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') "
        'AS UUID)), \nshared_enterprise_build_lots AS MATERIALIZED \n(SELECT build_lo'
        'ts.status AS status, build_lots.actual_configuration_id AS actual_configurat'
        'ion_id, build_lots.actual_configuration_revision AS actual_configuration_rev'
        'ision, build_lots.lot_label AS lot_label, build_lots.observed_unit_count AS '
        'observed_unit_count, build_lots.unit AS unit, build_lots.observation_system '
        'AS observation_system, build_lots.observation_external_id AS observation_ext'
        'ernal_id, build_lots.observation_nature AS observation_nature, build_lots.oc'
        'curred_at AS occurred_at, build_lots.received_at AS received_at, build_lots.'
        'product_id AS product_id, build_lots.project_id AS project_id, build_lots.bu'
        'ild_id AS build_id, build_lots.build_revision AS build_revision, build_lots.'
        'owner_id AS owner_id, build_lots.visibility AS visibility, build_lots.revisi'
        'on AS revision, build_lots.reason AS reason, build_lots.sources AS sources, '
        'build_lots.required_source_read_set AS required_source_read_set, build_lots.'
        'id AS id, build_lots.tenant_id AS tenant_id, build_lots.created_at AS create'
        'd_at, build_lots.category_id AS category_id \nFROM build_lots \nWHERE build_'
        "lots.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS"
        " UUID)), \nauthoritative_enterprise_sources_build AS \n(SELECT 'build' AS so"
        'urce_type, shared_enterprise_builds.id AS source_id, shared_enterprise_build'
        's.tenant_id AS tenant_id, shared_enterprise_builds.category_id AS category_i'
        'd, shared_enterprise_builds.product_id AS product_id, shared_enterprise_buil'
        'ds.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enter'
        'prise_builds.owner_id AS owner_id, shared_enterprise_builds.revision AS sour'
        'ce_revision, shared_enterprise_builds.name AS title, encode(sha256(convert_t'
        "o(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_builds.id, 'ki"
        "nd', 'build', 'facts', jsonb_build_object('name', shared_enterprise_builds.n"
        "ame, 'type', shared_enterprise_builds.type, 'purpose', shared_enterprise_bui"
        "lds.purpose, 'planned_quantity', shared_enterprise_builds.planned_quantity, "
        "'unit', shared_enterprise_builds.unit, 'planned_start', shared_enterprise_bu"
        "ilds.planned_start, 'planned_end', shared_enterprise_builds.planned_end, 'en"
        "gineering_configuration_id', shared_enterprise_builds.engineering_configurat"
        "ion_id, 'manufacturing_configuration_id', shared_enterprise_builds.manufactu"
        "ring_configuration_id, 'verification_objectives', shared_enterprise_builds.v"
        "erification_objectives, 'plan_status', shared_enterprise_builds.status), 'so"
        "urce_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact'"
        ", 'id', enterprise_reads_build.value['artifact_id'], 'version', enterprise_r"
        "eads_build.value['expected_revision']) ORDER BY enterprise_reads_build.value"
        " ->> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), j"
        'sonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT shared'
        '_enterprise_engineering_configurations.required_source_read_set \nFROM share'
        'd_enterprise_engineering_configurations \nWHERE shared_enterprise_engineerin'
        'g_configurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_e'
        'nterprise_engineering_configurations.product_id = shared_enterprise_builds.p'
        'roduct_id AND shared_enterprise_engineering_configurations.id = shared_enter'
        'prise_builds.engineering_configuration_id) || (SELECT shared_enterprise_proc'
        'ess_revisions.required_source_read_set \nFROM shared_enterprise_process_revi'
        'sions \nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterpr'
        'ise_builds.tenant_id AND shared_enterprise_process_revisions.product_id = sh'
        'ared_enterprise_builds.product_id AND shared_enterprise_process_revisions.id'
        ' = shared_enterprise_builds.manufacturing_configuration_id)) AS enterprise_r'
        "eads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), '"
        "hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_ente"
        "rprise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('name', share"
        "d_enterprise_builds.name, 'type', shared_enterprise_builds.type, 'purpose', "
        "shared_enterprise_builds.purpose, 'planned_quantity', shared_enterprise_buil"
        "ds.planned_quantity, 'unit', shared_enterprise_builds.unit, 'planned_start',"
        " shared_enterprise_builds.planned_start, 'planned_end', shared_enterprise_bu"
        "ilds.planned_end, 'engineering_configuration_id', shared_enterprise_builds.e"
        "ngineering_configuration_id, 'manufacturing_configuration_id', shared_enterp"
        "rise_builds.manufacturing_configuration_id, 'verification_objectives', share"
        "d_enterprise_builds.verification_objectives, 'plan_status', shared_enterpris"
        "e_builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_obje"
        "ct('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'v"
        "ersion', enterprise_reads_build.value['expected_revision']) ORDER BY enterpr"
        "ise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'e"
        "xpected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_el"
        'ements((SELECT shared_enterprise_engineering_configurations.required_source_'
        'read_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_'
        'enterprise_engineering_configurations.tenant_id = shared_enterprise_builds.t'
        'enant_id AND shared_enterprise_engineering_configurations.product_id = share'
        'd_enterprise_builds.product_id AND shared_enterprise_engineering_configurati'
        'ons.id = shared_enterprise_builds.engineering_configuration_id) || (SELECT s'
        'hared_enterprise_process_revisions.required_source_read_set \nFROM shared_en'
        'terprise_process_revisions \nWHERE shared_enterprise_process_revisions.tenan'
        't_id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revi'
        'sions.product_id = shared_enterprise_builds.product_id AND shared_enterprise'
        '_process_revisions.id = shared_enterprise_builds.manufacturing_configuration'
        "_id)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSON"
        "B) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enterprise_"
        "builds.id, 'kind', 'build', 'facts', jsonb_build_object('name', shared_enter"
        "prise_builds.name, 'type', shared_enterprise_builds.type, 'purpose', shared_"
        "enterprise_builds.purpose, 'planned_quantity', shared_enterprise_builds.plan"
        "ned_quantity, 'unit', shared_enterprise_builds.unit, 'planned_start', shared"
        "_enterprise_builds.planned_start, 'planned_end', shared_enterprise_builds.pl"
        "anned_end, 'engineering_configuration_id', shared_enterprise_builds.engineer"
        "ing_configuration_id, 'manufacturing_configuration_id', shared_enterprise_bu"
        "ilds.manufacturing_configuration_id, 'verification_objectives', shared_enter"
        "prise_builds.verification_objectives, 'plan_status', shared_enterprise_build"
        "s.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'version'"
        ", enterprise_reads_build.value['expected_revision']) ORDER BY enterprise_rea"
        "ds_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'expected"
        "_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements("
        '(SELECT shared_enterprise_engineering_configurations.required_source_read_se'
        't \nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterpr'
        'ise_engineering_configurations.tenant_id = shared_enterprise_builds.tenant_i'
        'd AND shared_enterprise_engineering_configurations.product_id = shared_enter'
        'prise_builds.product_id AND shared_enterprise_engineering_configurations.id '
        '= shared_enterprise_builds.engineering_configuration_id) || (SELECT shared_e'
        'nterprise_process_revisions.required_source_read_set \nFROM shared_enterpris'
        'e_process_revisions \nWHERE shared_enterprise_process_revisions.tenant_id = '
        'shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisions.p'
        'roduct_id = shared_enterprise_builds.product_id AND shared_enterprise_proces'
        's_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)) A'
        "S enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS struct"
        "ured, 'structured' AS nature, shared_enterprise_builds.visibility != 'catego"
        "ry' OR shared_enterprise_projects.visibility != 'category' OR shared_enterpr"
        "ise_products.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_arra"
        'y_elements((SELECT shared_enterprise_engineering_configurations.required_sou'
        'rce_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE sha'
        'red_enterprise_engineering_configurations.tenant_id = shared_enterprise_buil'
        'ds.tenant_id AND shared_enterprise_engineering_configurations.product_id = s'
        'hared_enterprise_builds.product_id AND shared_enterprise_engineering_configu'
        'rations.id = shared_enterprise_builds.engineering_configuration_id) || (SELE'
        'CT shared_enterprise_process_revisions.required_source_read_set \nFROM share'
        'd_enterprise_process_revisions \nWHERE shared_enterprise_process_revisions.t'
        'enant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_'
        'revisions.product_id = shared_enterprise_builds.product_id AND shared_enterp'
        'rise_process_revisions.id = shared_enterprise_builds.manufacturing_configura'
        'tion_id)) AS enterprise_reads_build(value) JOIN enterprise_authoritative_art'
        'ifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = shared_'
        'enterprise_builds.tenant_id AND enterprise_authoritative_artifacts_build.sou'
        "rce_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWH"
        'ERE enterprise_authoritative_artifacts_build.private)) AS private, EXISTS (S'
        'ELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterprise_engineering_co'
        'nfigurations.required_source_read_set \nFROM shared_enterprise_engineering_c'
        'onfigurations \nWHERE shared_enterprise_engineering_configurations.tenant_id'
        ' = shared_enterprise_builds.tenant_id AND shared_enterprise_engineering_conf'
        'igurations.product_id = shared_enterprise_builds.product_id AND shared_enter'
        'prise_engineering_configurations.id = shared_enterprise_builds.engineering_c'
        'onfiguration_id) || (SELECT shared_enterprise_process_revisions.required_sou'
        'rce_read_set \nFROM shared_enterprise_process_revisions \nWHERE shared_enter'
        'prise_process_revisions.tenant_id = shared_enterprise_builds.tenant_id AND s'
        'hared_enterprise_process_revisions.product_id = shared_enterprise_builds.pro'
        'duct_id AND shared_enterprise_process_revisions.id = shared_enterprise_build'
        's.manufacturing_configuration_id)) AS enterprise_reads_build(value) JOIN ent'
        'erprise_authoritative_artifacts_build ON enterprise_authoritative_artifacts_'
        'build.tenant_id = shared_enterprise_builds.tenant_id AND enterprise_authorit'
        "ative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.custom"
        'er_original) AS customer_original, true AS is_current, shared_enterprise_bui'
        'lds.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_ente'
        'rprise_builds.id AS object_id, (SELECT coalesce(array_agg(enterprise_authori'
        'tative_artifacts_build.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM j'
        'sonb_array_elements((SELECT shared_enterprise_engineering_configurations.req'
        'uired_source_read_set \nFROM shared_enterprise_engineering_configurations \n'
        'WHERE shared_enterprise_engineering_configurations.tenant_id = shared_enterp'
        'rise_builds.tenant_id AND shared_enterprise_engineering_configurations.produ'
        'ct_id = shared_enterprise_builds.product_id AND shared_enterprise_engineerin'
        'g_configurations.id = shared_enterprise_builds.engineering_configuration_id)'
        ' || (SELECT shared_enterprise_process_revisions.required_source_read_set \nF'
        'ROM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_re'
        'visions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise'
        '_process_revisions.product_id = shared_enterprise_builds.product_id AND shar'
        'ed_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_'
        'configuration_id)) AS enterprise_reads_build(value) JOIN enterprise_authorit'
        'ative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id '
        '= shared_enterprise_builds.tenant_id AND enterprise_authoritative_artifacts_'
        "build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_build.original_id IS NOT NUL'
        'L) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements('
        '(SELECT shared_enterprise_engineering_configurations.required_source_read_se'
        't \nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterpr'
        'ise_engineering_configurations.tenant_id = shared_enterprise_builds.tenant_i'
        'd AND shared_enterprise_engineering_configurations.product_id = shared_enter'
        'prise_builds.product_id AND shared_enterprise_engineering_configurations.id '
        '= shared_enterprise_builds.engineering_configuration_id) || (SELECT shared_e'
        'nterprise_process_revisions.required_source_read_set \nFROM shared_enterpris'
        'e_process_revisions \nWHERE shared_enterprise_process_revisions.tenant_id = '
        'shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisions.p'
        'roduct_id = shared_enterprise_builds.product_id AND shared_enterprise_proces'
        's_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)) A'
        'S enterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_buil'
        'd ON enterprise_authoritative_artifacts_build.tenant_id = shared_enterprise_'
        'builds.tenant_id AND enterprise_authoritative_artifacts_build.source_id = CA'
        "ST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_build.source_revision != CAST((enterprise_reads_'
        "build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE"
        " 'current' END AS read_basis_status \nFROM shared_enterprise_builds JOIN sha"
        'red_enterprise_projects ON shared_enterprise_projects.tenant_id = shared_ent'
        'erprise_builds.tenant_id AND shared_enterprise_projects.product_id = shared_'
        'enterprise_builds.product_id AND shared_enterprise_projects.id = shared_ente'
        'rprise_builds.project_id AND shared_enterprise_projects.category_id = shared'
        '_enterprise_builds.category_id JOIN shared_enterprise_products ON shared_ent'
        'erprise_products.tenant_id = shared_enterprise_builds.tenant_id AND shared_e'
        'nterprise_products.id = shared_enterprise_builds.product_id AND shared_enter'
        'prise_products.category_id = shared_enterprise_builds.category_id \nWHERE sh'
        "ared_enterprise_builds.tenant_id = CAST(nullif(current_setting('pdos.tenant_"
        "id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elemen"
        'ts((SELECT shared_enterprise_engineering_configurations.required_source_read'
        '_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_ente'
        'rprise_engineering_configurations.tenant_id = shared_enterprise_builds.tenan'
        't_id AND shared_enterprise_engineering_configurations.product_id = shared_en'
        'terprise_builds.product_id AND shared_enterprise_engineering_configurations.'
        'id = shared_enterprise_builds.engineering_configuration_id) || (SELECT share'
        'd_enterprise_process_revisions.required_source_read_set \nFROM shared_enterp'
        'rise_process_revisions \nWHERE shared_enterprise_process_revisions.tenant_id'
        ' = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revision'
        's.product_id = shared_enterprise_builds.product_id AND shared_enterprise_pro'
        'cess_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)'
        ') AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM ente'
        'rprise_authoritative_artifacts_build \nWHERE enterprise_authoritative_artifa'
        'cts_build.tenant_id = shared_enterprise_builds.tenant_id AND enterprise_auth'
        'oritative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->>'
        " 'artifact_id') AS UUID))))) AND (EXISTS (SELECT shared_enterprise_engineeri"
        'ng_configurations.required_source_read_set \nFROM shared_enterprise_engineer'
        'ing_configurations \nWHERE shared_enterprise_engineering_configurations.tena'
        'nt_id = shared_enterprise_builds.tenant_id AND shared_enterprise_engineering'
        '_configurations.product_id = shared_enterprise_builds.product_id AND shared_'
        'enterprise_engineering_configurations.id = shared_enterprise_builds.engineer'
        'ing_configuration_id)) AND (EXISTS (SELECT shared_enterprise_process_revisio'
        'ns.required_source_read_set \nFROM shared_enterprise_process_revisions \nWHE'
        'RE shared_enterprise_process_revisions.tenant_id = shared_enterprise_builds.'
        'tenant_id AND shared_enterprise_process_revisions.product_id = shared_enterp'
        'rise_builds.product_id AND shared_enterprise_process_revisions.id = shared_e'
        "nterprise_builds.manufacturing_configuration_id)) UNION ALL SELECT 'build' A"
        'S source_type, shared_enterprise_build_starts.id AS source_id, shared_enterp'
        'rise_build_starts.tenant_id AS tenant_id, shared_enterprise_build_starts.cat'
        'egory_id AS category_id, shared_enterprise_build_starts.product_id AS produc'
        't_id, shared_enterprise_build_starts.project_id AS project_id, CAST(NULL AS '
        'UUID) AS proposal_id, shared_enterprise_build_starts.owner_id AS owner_id, s'
        "hared_enterprise_build_starts.revision AS source_revision, '\u5f00\u5de5"
        "\u8bb0\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode(sha256"
        "(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_buil"
        "d_starts.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind"
        "', 'build_start', 'build_id', shared_enterprise_build_starts.build_id, 'buil"
        "d_revision', shared_enterprise_build_starts.build_revision, 'status', shared"
        "_enterprise_build_starts.status, 'occurred_at', shared_enterprise_build_star"
        "ts.occurred_at, 'occurred_timezone', shared_enterprise_build_starts.occurred"
        "_timezone, 'assessment_id', shared_enterprise_build_starts.assessment_id, 'a"
        "ssessment_revision', shared_enterprise_build_starts.assessment_revision, 'en"
        "gineering_authorization_id', shared_enterprise_build_starts.engineering_auth"
        "orization_id, 'engineering_authorization_revision', shared_enterprise_build_"
        "starts.engineering_authorization_revision, 'manufacturing_authorization_id',"
        " shared_enterprise_build_starts.manufacturing_authorization_id, 'manufacturi"
        "ng_authorization_revision', shared_enterprise_build_starts.manufacturing_aut"
        "horization_revision) || jsonb_build_object('execution_scope', jsonb_build_ob"
        "ject('purpose', shared_enterprise_build_starts.execution_scope['purpose'], '"
        "quantity', shared_enterprise_build_starts.execution_scope['quantity'], 'unit"
        "', shared_enterprise_build_starts.execution_scope['unit'], 'site', shared_en"
        "terprise_build_starts.execution_scope['site'], 'window_start', shared_enterp"
        "rise_build_starts.execution_scope['window_start'], 'window_end', shared_ente"
        "rprise_build_starts.execution_scope['window_end'], 'window_timezone', shared"
        "_enterprise_build_starts.execution_scope['window_timezone']), 'continuation_"
        "permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('type', 'artifact', 'id', enterprise_reads_build.value['arti"
        "fact_id'], 'version', enterprise_reads_build.value['expected_revision']) ORD"
        "ER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build"
        ".value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM j"
        'sonb_array_elements(shared_enterprise_build_starts.required_source_read_set)'
        " AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('objec"
        "t_id', shared_enterprise_build_starts.build_id, 'kind', 'build', 'facts', js"
        "onb_build_object('record_kind', 'build_start', 'build_id', shared_enterprise"
        "_build_starts.build_id, 'build_revision', shared_enterprise_build_starts.bui"
        "ld_revision, 'status', shared_enterprise_build_starts.status, 'occurred_at',"
        " shared_enterprise_build_starts.occurred_at, 'occurred_timezone', shared_ent"
        "erprise_build_starts.occurred_timezone, 'assessment_id', shared_enterprise_b"
        "uild_starts.assessment_id, 'assessment_revision', shared_enterprise_build_st"
        "arts.assessment_revision, 'engineering_authorization_id', shared_enterprise_"
        "build_starts.engineering_authorization_id, 'engineering_authorization_revisi"
        "on', shared_enterprise_build_starts.engineering_authorization_revision, 'man"
        "ufacturing_authorization_id', shared_enterprise_build_starts.manufacturing_a"
        "uthorization_id, 'manufacturing_authorization_revision', shared_enterprise_b"
        "uild_starts.manufacturing_authorization_revision) || jsonb_build_object('exe"
        "cution_scope', jsonb_build_object('purpose', shared_enterprise_build_starts."
        "execution_scope['purpose'], 'quantity', shared_enterprise_build_starts.execu"
        "tion_scope['quantity'], 'unit', shared_enterprise_build_starts.execution_sco"
        "pe['unit'], 'site', shared_enterprise_build_starts.execution_scope['site'], "
        "'window_start', shared_enterprise_build_starts.execution_scope['window_start"
        "'], 'window_end', shared_enterprise_build_starts.execution_scope['window_end"
        "'], 'window_timezone', shared_enterprise_build_starts.execution_scope['windo"
        "w_timezone']), 'continuation_permission', 'not_evaluated'), 'source_refs', ("
        "SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enter"
        "prise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.va"
        "lue['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifac"
        "t_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_ar"
        'ray()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_build_sta'
        "rts.required_source_read_set) AS enterprise_reads_build(value)), 'record_pol"
        "icy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_i"
        "d', shared_enterprise_build_starts.build_id, 'kind', 'build', 'facts', jsonb"
        "_build_object('record_kind', 'build_start', 'build_id', shared_enterprise_bu"
        "ild_starts.build_id, 'build_revision', shared_enterprise_build_starts.build_"
        "revision, 'status', shared_enterprise_build_starts.status, 'occurred_at', sh"
        "ared_enterprise_build_starts.occurred_at, 'occurred_timezone', shared_enterp"
        "rise_build_starts.occurred_timezone, 'assessment_id', shared_enterprise_buil"
        "d_starts.assessment_id, 'assessment_revision', shared_enterprise_build_start"
        "s.assessment_revision, 'engineering_authorization_id', shared_enterprise_bui"
        "ld_starts.engineering_authorization_id, 'engineering_authorization_revision'"
        ", shared_enterprise_build_starts.engineering_authorization_revision, 'manufa"
        "cturing_authorization_id', shared_enterprise_build_starts.manufacturing_auth"
        "orization_id, 'manufacturing_authorization_revision', shared_enterprise_buil"
        "d_starts.manufacturing_authorization_revision) || jsonb_build_object('execut"
        "ion_scope', jsonb_build_object('purpose', shared_enterprise_build_starts.exe"
        "cution_scope['purpose'], 'quantity', shared_enterprise_build_starts.executio"
        "n_scope['quantity'], 'unit', shared_enterprise_build_starts.execution_scope["
        "'unit'], 'site', shared_enterprise_build_starts.execution_scope['site'], 'wi"
        "ndow_start', shared_enterprise_build_starts.execution_scope['window_start'],"
        " 'window_end', shared_enterprise_build_starts.execution_scope['window_end'],"
        " 'window_timezone', shared_enterprise_build_starts.execution_scope['window_t"
        "imezone']), 'continuation_permission', 'not_evaluated'), 'source_refs', (SEL"
        "ECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpri"
        "se_reads_build.value['artifact_id'], 'version', enterprise_reads_build.value"
        "['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_i"
        "d', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_array"
        '()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_build_starts'
        ".required_source_read_set) AS enterprise_reads_build(value)), 'record_policy"
        "', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS structured, 'structured' AS nature, shared_enterprise_"
        "build_starts.visibility != 'category' OR shared_enterprise_projects.visibili"
        "ty != 'category' OR shared_enterprise_products.visibility != 'category' OR ("
        'EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.'
        'required_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_a'
        'uthoritative_artifacts_build ON enterprise_authoritative_artifacts_build.ten'
        'ant_id = shared_enterprise_build_starts.tenant_id AND enterprise_authoritati'
        "ve_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'artif"
        "act_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.private))"
        " OR shared_enterprise_builds.visibility != 'category' AS private, EXISTS (SE"
        'LECT 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.required_s'
        'ource_read_set) AS enterprise_reads_build(value) JOIN enterprise_authoritati'
        've_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = s'
        'hared_enterprise_build_starts.tenant_id AND enterprise_authoritative_artifac'
        "ts_build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') A"
        'S UUID) \nWHERE enterprise_authoritative_artifacts_build.customer_original) '
        'AS customer_original, true AS is_current, shared_enterprise_build_starts.cre'
        'ated_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_'
        'build_starts.build_id AS object_id, (SELECT coalesce(array_agg(enterprise_au'
        'thoritative_artifacts_build.original_id), ARRAY[]::UUID[]) AS coalesce_4 \nF'
        'ROM jsonb_array_elements(shared_enterprise_build_starts.required_source_read'
        '_set) AS enterprise_reads_build(value) JOIN enterprise_authoritative_artifac'
        'ts_build ON enterprise_authoritative_artifacts_build.tenant_id = shared_ente'
        'rprise_build_starts.tenant_id AND enterprise_authoritative_artifacts_build.s'
        "ource_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_build.original_id IS NOT NULL) AS o'
        'riginal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_'
        'enterprise_build_starts.required_source_read_set) AS enterprise_reads_build('
        'value) JOIN enterprise_authoritative_artifacts_build ON enterprise_authorita'
        'tive_artifacts_build.tenant_id = shared_enterprise_build_starts.tenant_id AN'
        'D enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_read'
        "s_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_a"
        "rtifacts_build.source_revision != CAST((enterprise_reads_build.value ->> 'ex"
        "pected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS r"
        'ead_basis_status \nFROM shared_enterprise_build_starts JOIN shared_enterpris'
        'e_projects ON shared_enterprise_projects.tenant_id = shared_enterprise_build'
        '_starts.tenant_id AND shared_enterprise_projects.product_id = shared_enterpr'
        'ise_build_starts.product_id AND shared_enterprise_projects.id = shared_enter'
        'prise_build_starts.project_id AND shared_enterprise_projects.category_id = s'
        'hared_enterprise_build_starts.category_id JOIN shared_enterprise_products ON'
        ' shared_enterprise_products.tenant_id = shared_enterprise_build_starts.tenan'
        't_id AND shared_enterprise_products.id = shared_enterprise_build_starts.prod'
        'uct_id AND shared_enterprise_products.category_id = shared_enterprise_build_'
        'starts.category_id JOIN shared_enterprise_builds ON shared_enterprise_builds'
        '.tenant_id = shared_enterprise_build_starts.tenant_id AND shared_enterprise_'
        'builds.category_id = shared_enterprise_build_starts.category_id AND shared_e'
        'nterprise_builds.product_id = shared_enterprise_build_starts.product_id AND '
        'shared_enterprise_builds.project_id = shared_enterprise_build_starts.project'
        '_id AND shared_enterprise_builds.id = shared_enterprise_build_starts.build_i'
        'd AND shared_enterprise_builds.revision = shared_enterprise_build_starts.bui'
        'ld_revision \nWHERE shared_enterprise_build_starts.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT"
        ' 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.required_sourc'
        'e_read_set) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 '
        '\nFROM enterprise_authoritative_artifacts_build \nWHERE enterprise_authorita'
        'tive_artifacts_build.tenant_id = shared_enterprise_build_starts.tenant_id AN'
        'D enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_read'
        "s_build.value ->> 'artifact_id') AS UUID))))) UNION ALL SELECT 'build' AS so"
        'urce_type, shared_enterprise_actual_configurations.id AS source_id, shared_e'
        'nterprise_actual_configurations.tenant_id AS tenant_id, shared_enterprise_ac'
        'tual_configurations.category_id AS category_id, shared_enterprise_actual_con'
        'figurations.product_id AS product_id, shared_enterprise_actual_configuration'
        's.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterp'
        'rise_actual_configurations.owner_id AS owner_id, shared_enterprise_actual_co'
        "nfigurations.revision AS source_revision, '\u5b9e\u9645\u914d\u7f6e\u8bb0"
        "\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode(sha256(conve"
        "rt_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_actual_con"
        "figurations.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_k"
        "ind', 'actual_configuration', 'build_id', shared_enterprise_actual_configura"
        "tions.build_id, 'build_revision', shared_enterprise_actual_configurations.bu"
        "ild_revision, 'status', shared_enterprise_actual_configurations.status, 'pla"
        "nned_engineering_configuration_id', shared_enterprise_actual_configurations."
        "planned_engineering_configuration_id, 'planned_manufacturing_configuration_i"
        "d', shared_enterprise_actual_configurations.planned_manufacturing_configurat"
        "ion_id, 'actual_engineering_configuration_id', shared_enterprise_actual_conf"
        "igurations.actual_engineering_configuration_id, 'actual_engineering_revision"
        "', shared_enterprise_actual_configurations.actual_engineering_revision, 'act"
        "ual_manufacturing_configuration_id', shared_enterprise_actual_configurations"
        ".actual_manufacturing_configuration_id, 'actual_manufacturing_revision', sha"
        "red_enterprise_actual_configurations.actual_manufacturing_revision, 'observe"
        "d_at', shared_enterprise_actual_configurations.observed_at), 'source_refs', "
        "(SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', ente"
        "rprise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.v"
        "alue['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifa"
        "ct_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_a"
        'rray()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_c'
        "onfigurations.required_source_read_set) AS enterprise_reads_build(value)), '"
        "record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_h"
        "ash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_actual_conf"
        "igurations.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_ki"
        "nd', 'actual_configuration', 'build_id', shared_enterprise_actual_configurat"
        "ions.build_id, 'build_revision', shared_enterprise_actual_configurations.bui"
        "ld_revision, 'status', shared_enterprise_actual_configurations.status, 'plan"
        "ned_engineering_configuration_id', shared_enterprise_actual_configurations.p"
        "lanned_engineering_configuration_id, 'planned_manufacturing_configuration_id"
        "', shared_enterprise_actual_configurations.planned_manufacturing_configurati"
        "on_id, 'actual_engineering_configuration_id', shared_enterprise_actual_confi"
        "gurations.actual_engineering_configuration_id, 'actual_engineering_revision'"
        ", shared_enterprise_actual_configurations.actual_engineering_revision, 'actu"
        "al_manufacturing_configuration_id', shared_enterprise_actual_configurations."
        "actual_manufacturing_configuration_id, 'actual_manufacturing_revision', shar"
        "ed_enterprise_actual_configurations.actual_manufacturing_revision, 'observed"
        "_at', shared_enterprise_actual_configurations.observed_at), 'source_refs', ("
        "SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enter"
        "prise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.va"
        "lue['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifac"
        "t_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_ar"
        'ray()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_co'
        "nfigurations.required_source_read_set) AS enterprise_reads_build(value)), 'r"
        "ecord_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('ob"
        "ject_id', shared_enterprise_actual_configurations.build_id, 'kind', 'build',"
        " 'facts', jsonb_build_object('record_kind', 'actual_configuration', 'build_i"
        "d', shared_enterprise_actual_configurations.build_id, 'build_revision', shar"
        "ed_enterprise_actual_configurations.build_revision, 'status', shared_enterpr"
        "ise_actual_configurations.status, 'planned_engineering_configuration_id', sh"
        'ared_enterprise_actual_configurations.planned_engineering_configuration_id, '
        "'planned_manufacturing_configuration_id', shared_enterprise_actual_configura"
        "tions.planned_manufacturing_configuration_id, 'actual_engineering_configurat"
        "ion_id', shared_enterprise_actual_configurations.actual_engineering_configur"
        "ation_id, 'actual_engineering_revision', shared_enterprise_actual_configurat"
        "ions.actual_engineering_revision, 'actual_manufacturing_configuration_id', s"
        'hared_enterprise_actual_configurations.actual_manufacturing_configuration_id'
        ", 'actual_manufacturing_revision', shared_enterprise_actual_configurations.a"
        "ctual_manufacturing_revision, 'observed_at', shared_enterprise_actual_config"
        "urations.observed_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build"
        "_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'"
        "], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY en"
        "terprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value -"
        ">> 'expected_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_arr"
        'ay_elements(shared_enterprise_actual_configurations.required_source_read_set'
        ") AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "structured, 'structured' AS nature, shared_enterprise_actual_configurations."
        "visibility != 'category' OR shared_enterprise_projects.visibility != 'catego"
        "ry' OR shared_enterprise_products.visibility != 'category' OR (EXISTS (SELEC"
        'T 1 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.requ'
        'ired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_autho'
        'ritative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_'
        'id = shared_enterprise_actual_configurations.tenant_id AND enterprise_author'
        "itative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> '"
        "artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.priv"
        "ate)) OR shared_enterprise_builds.visibility != 'category' AS private, EXIST"
        'S (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_actual_configurati'
        'ons.required_source_read_set) AS enterprise_reads_build(value) JOIN enterpri'
        'se_authoritative_artifacts_build ON enterprise_authoritative_artifacts_build'
        '.tenant_id = shared_enterprise_actual_configurations.tenant_id AND enterpris'
        'e_authoritative_artifacts_build.source_id = CAST((enterprise_reads_build.val'
        "ue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_bu"
        'ild.customer_original) AS customer_original, true AS is_current, shared_ente'
        'rprise_actual_configurations.created_at AS created_at, CAST(NULL AS UUID) AS'
        ' original_id, shared_enterprise_actual_configurations.build_id AS object_id,'
        ' (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_build.origina'
        'l_id), ARRAY[]::UUID[]) AS coalesce_6 \nFROM jsonb_array_elements(shared_ent'
        'erprise_actual_configurations.required_source_read_set) AS enterprise_reads_'
        'build(value) JOIN enterprise_authoritative_artifacts_build ON enterprise_aut'
        'horitative_artifacts_build.tenant_id = shared_enterprise_actual_configuratio'
        'ns.tenant_id AND enterprise_authoritative_artifacts_build.source_id = CAST(('
        "enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_"
        'authoritative_artifacts_build.original_id IS NOT NULL) AS original_ids, CASE'
        ' WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_actual'
        '_configurations.required_source_read_set) AS enterprise_reads_build(value) J'
        'OIN enterprise_authoritative_artifacts_build ON enterprise_authoritative_art'
        'ifacts_build.tenant_id = shared_enterprise_actual_configurations.tenant_id A'
        'ND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_rea'
        "ds_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_"
        "artifacts_build.source_revision != CAST((enterprise_reads_build.value ->> 'e"
        "xpected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS "
        'read_basis_status \nFROM shared_enterprise_actual_configurations JOIN shared'
        '_enterprise_projects ON shared_enterprise_projects.tenant_id = shared_enterp'
        'rise_actual_configurations.tenant_id AND shared_enterprise_projects.product_'
        'id = shared_enterprise_actual_configurations.product_id AND shared_enterpris'
        'e_projects.id = shared_enterprise_actual_configurations.project_id AND share'
        'd_enterprise_projects.category_id = shared_enterprise_actual_configurations.'
        'category_id JOIN shared_enterprise_products ON shared_enterprise_products.te'
        'nant_id = shared_enterprise_actual_configurations.tenant_id AND shared_enter'
        'prise_products.id = shared_enterprise_actual_configurations.product_id AND s'
        'hared_enterprise_products.category_id = shared_enterprise_actual_configurati'
        'ons.category_id JOIN shared_enterprise_builds ON shared_enterprise_builds.te'
        'nant_id = shared_enterprise_actual_configurations.tenant_id AND shared_enter'
        'prise_builds.category_id = shared_enterprise_actual_configurations.category_'
        'id AND shared_enterprise_builds.product_id = shared_enterprise_actual_config'
        'urations.product_id AND shared_enterprise_builds.project_id = shared_enterpr'
        'ise_actual_configurations.project_id AND shared_enterprise_builds.id = share'
        'd_enterprise_actual_configurations.build_id AND shared_enterprise_builds.rev'
        'ision = shared_enterprise_actual_configurations.build_revision \nWHERE share'
        "d_enterprise_actual_configurations.tenant_id = CAST(nullif(current_setting('"
        "pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_"
        'array_elements(shared_enterprise_actual_configurations.required_source_read_'
        'set) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM e'
        'nterprise_authoritative_artifacts_build \nWHERE enterprise_authoritative_art'
        'ifacts_build.tenant_id = shared_enterprise_actual_configurations.tenant_id A'
        'ND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_rea'
        "ds_build.value ->> 'artifact_id') AS UUID))))) UNION ALL SELECT 'build' AS s"
        'ource_type, shared_enterprise_build_lots.id AS source_id, shared_enterprise_'
        'build_lots.tenant_id AS tenant_id, shared_enterprise_build_lots.category_id '
        'AS category_id, shared_enterprise_build_lots.product_id AS product_id, share'
        'd_enterprise_build_lots.project_id AS project_id, CAST(NULL AS UUID) AS prop'
        'osal_id, shared_enterprise_build_lots.owner_id AS owner_id, shared_enterpris'
        "e_build_lots.revision AS source_revision, '\u5b9e\u7269\u4ea7\u51fa\u8bb0"
        "\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode(sha256(conve"
        "rt_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_build_lots"
        ".build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'buil"
        "d_output', 'build_id', shared_enterprise_build_lots.build_id, 'build_revisio"
        "n', shared_enterprise_build_lots.build_revision, 'status', shared_enterprise"
        "_build_lots.status, 'lot_label', shared_enterprise_build_lots.lot_label, 'ac"
        "tual_configuration_id', shared_enterprise_build_lots.actual_configuration_id"
        ", 'actual_configuration_revision', shared_enterprise_build_lots.actual_confi"
        "guration_revision, 'observed_unit_count', shared_enterprise_build_lots.obser"
        "ved_unit_count, 'unit', shared_enterprise_build_lots.unit, 'observation_natu"
        "re', shared_enterprise_build_lots.observation_nature, 'occurred_at', shared_"
        "enterprise_build_lots.occurred_at, 'received_at', shared_enterprise_build_lo"
        "ts.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_objec"
        "t('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 've"
        "rsion', enterprise_reads_build.value['expected_revision']) ORDER BY enterpri"
        "se_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'ex"
        "pected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_ele"
        'ments(shared_enterprise_build_lots.required_source_read_set) AS enterprise_r'
        "eads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), '"
        "hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_ente"
        "rprise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('re"
        "cord_kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_i"
        "d, 'build_revision', shared_enterprise_build_lots.build_revision, 'status', "
        "shared_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lo"
        "ts.lot_label, 'actual_configuration_id', shared_enterprise_build_lots.actual"
        "_configuration_id, 'actual_configuration_revision', shared_enterprise_build_"
        "lots.actual_configuration_revision, 'observed_unit_count', shared_enterprise"
        "_build_lots.observed_unit_count, 'unit', shared_enterprise_build_lots.unit, "
        "'observation_nature', shared_enterprise_build_lots.observation_nature, 'occu"
        "rred_at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_en"
        "terprise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg("
        "jsonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value['a"
        "rtifact_id'], 'version', enterprise_reads_build.value['expected_revision']) "
        "ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_bu"
        "ild.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFRO"
        'M jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set'
        ") AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS "
        "TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enterprise_build_"
        "lots.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', '"
        "build_output', 'build_id', shared_enterprise_build_lots.build_id, 'build_rev"
        "ision', shared_enterprise_build_lots.build_revision, 'status', shared_enterp"
        "rise_build_lots.status, 'lot_label', shared_enterprise_build_lots.lot_label,"
        " 'actual_configuration_id', shared_enterprise_build_lots.actual_configuratio"
        "n_id, 'actual_configuration_revision', shared_enterprise_build_lots.actual_c"
        "onfiguration_revision, 'observed_unit_count', shared_enterprise_build_lots.o"
        "bserved_unit_count, 'unit', shared_enterprise_build_lots.unit, 'observation_"
        "nature', shared_enterprise_build_lots.observation_nature, 'occurred_at', sha"
        "red_enterprise_build_lots.occurred_at, 'received_at', shared_enterprise_buil"
        "d_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_o"
        "bject('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'],"
        " 'version', enterprise_reads_build.value['expected_revision']) ORDER BY ente"
        "rprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->>"
        " 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array"
        '_elements(shared_enterprise_build_lots.required_source_read_set) AS enterpri'
        "se_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, "
        "'structured' AS nature, shared_enterprise_build_lots.visibility != 'category"
        "' OR shared_enterprise_projects.visibility != 'category' OR shared_enterpris"
        "e_products.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_"
        'elements(shared_enterprise_build_lots.required_source_read_set) AS enterpris'
        'e_reads_build(value) JOIN enterprise_authoritative_artifacts_build ON enterp'
        'rise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_lots.'
        'tenant_id AND enterprise_authoritative_artifacts_build.source_id = CAST((ent'
        "erprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_aut"
        'horitative_artifacts_build.private)) OR shared_enterprise_builds.visibility '
        "!= 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(share"
        'd_enterprise_build_lots.required_source_read_set) AS enterprise_reads_build('
        'value) JOIN enterprise_authoritative_artifacts_build ON enterprise_authorita'
        'tive_artifacts_build.tenant_id = shared_enterprise_build_lots.tenant_id AND '
        'enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_'
        "build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_art"
        'ifacts_build.customer_original) AS customer_original, true AS is_current, sh'
        'ared_enterprise_build_lots.created_at AS created_at, CAST(NULL AS UUID) AS o'
        'riginal_id, shared_enterprise_build_lots.build_id AS object_id, (SELECT coal'
        'esce(array_agg(enterprise_authoritative_artifacts_build.original_id), ARRAY['
        ']::UUID[]) AS coalesce_8 \nFROM jsonb_array_elements(shared_enterprise_build'
        '_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN enterp'
        'rise_authoritative_artifacts_build ON enterprise_authoritative_artifacts_bui'
        'ld.tenant_id = shared_enterprise_build_lots.tenant_id AND enterprise_authori'
        "tative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'a"
        "rtifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.origi"
        'nal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM json'
        'b_array_elements(shared_enterprise_build_lots.required_source_read_set) AS e'
        'nterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_build O'
        'N enterprise_authoritative_artifacts_build.tenant_id = shared_enterprise_bui'
        'ld_lots.tenant_id AND enterprise_authoritative_artifacts_build.source_id = C'
        "AST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_build.source_revision != CAST((enterprise_reads'
        "_build.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELS"
        "E 'current' END AS read_basis_status \nFROM shared_enterprise_build_lots JOI"
        'N shared_enterprise_projects ON shared_enterprise_projects.tenant_id = share'
        'd_enterprise_build_lots.tenant_id AND shared_enterprise_projects.product_id '
        '= shared_enterprise_build_lots.product_id AND shared_enterprise_projects.id '
        '= shared_enterprise_build_lots.project_id AND shared_enterprise_projects.cat'
        'egory_id = shared_enterprise_build_lots.category_id JOIN shared_enterprise_p'
        'roducts ON shared_enterprise_products.tenant_id = shared_enterprise_build_lo'
        'ts.tenant_id AND shared_enterprise_products.id = shared_enterprise_build_lot'
        's.product_id AND shared_enterprise_products.category_id = shared_enterprise_'
        'build_lots.category_id JOIN shared_enterprise_builds ON shared_enterprise_bu'
        'ilds.tenant_id = shared_enterprise_build_lots.tenant_id AND shared_enterpris'
        'e_builds.category_id = shared_enterprise_build_lots.category_id AND shared_e'
        'nterprise_builds.product_id = shared_enterprise_build_lots.product_id AND sh'
        'ared_enterprise_builds.project_id = shared_enterprise_build_lots.project_id '
        'AND shared_enterprise_builds.id = shared_enterprise_build_lots.build_id AND '
        'shared_enterprise_builds.revision = shared_enterprise_build_lots.build_revis'
        'ion \nWHERE shared_enterprise_build_lots.tenant_id = CAST(nullif(current_set'
        "ting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM "
        'jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set) '
        'AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterp'
        'rise_authoritative_artifacts_build \nWHERE enterprise_authoritative_artifact'
        's_build.tenant_id = shared_enterprise_build_lots.tenant_id AND enterprise_au'
        'thoritative_artifacts_build.source_id = CAST((enterprise_reads_build.value -'
        ">> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritati"
        've_enterprise_sources_build \nWHERE authoritative_enterprise_sources_build.t'
        'enant_id = t AND authoritative_enterprise_sources_build.category_id = c AND '
        'CAST(authoritative_enterprise_sources_build.source_id AS TEXT) = expected->>'
        "'source_id' AND CAST(authoritative_enterprise_sources_build.source_revision "
        "AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_sources"
        "_build.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n W"
        "HEN 'test_run' THEN\n  WITH enterprise_authoritative_artifacts_test_run AS "
        "\n(SELECT 'artifact' AS source_type, artifact_versions.id AS source_id, arti"
        'fact_versions.tenant_id AS tenant_id, artifact_versions.category_id AS categ'
        'ory_id, artifact_versions.product_id AS product_id, CAST(NULL AS UUID) AS pr'
        'oject_id, CAST(NULL AS UUID) AS proposal_id, artifact_versions.owner_id AS o'
        'wner_id, artifact_versions.revision AS source_revision, artifact_versions.ti'
        'tle AS title, artifact_versions.content_hash AS content_hash, artifact_versi'
        "ons.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS natur"
        "e, artifact_versions.visibility != 'category' OR coalesce(products.visibilit"
        "y != 'category', false) OR coalesce(uploaded_originals.visibility != 'catego"
        "ry', false) AS private, artifact_versions.original_id IS NOT NULL AS custome"
        'r_original, true AS is_current, artifact_versions.created_at AS created_at, '
        'artifact_versions.original_id AS original_id, artifact_versions.id AS object'
        '_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) THEN ARRAY[artifa'
        "ct_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'current'"
        ' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN products ON p'
        'roducts.tenant_id = artifact_versions.tenant_id AND products.id = artifact_v'
        'ersions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.'
        'tenant_id = artifact_versions.tenant_id AND uploaded_originals.id = artifact'
        '_versions.original_id AND uploaded_originals.category_id = artifact_versions'
        '.category_id AND uploaded_originals.product_id IS NOT DISTINCT FROM artifact'
        '_versions.product_id LEFT OUTER JOIN original_security ON original_security.'
        'tenant_id = uploaded_originals.tenant_id AND original_security.original_id ='
        ' uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.sta"
        "tus = 'active' AND artifact_versions.category_id IS NOT NULL AND (artifact_v"
        'ersions.product_id IS NULL OR products.id IS NOT NULL) AND (artifact_version'
        's.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_orig'
        "inals.status = 'parsed' AND uploaded_originals.scan_status = 'clean' AND ori"
        "ginal_security.source_state = 'active' AND original_security.disposition = '"
        "active' AND original_security.current_request_id IS NOT NULL)), \nshared_ent"
        'erprise_verification_run_versions AS MATERIALIZED \n(SELECT verification_run'
        '_versions.product_id AS product_id, verification_run_versions.project_id AS '
        'project_id, verification_run_versions.build_id AS build_id, verification_run'
        '_versions.build_revision AS build_revision, verification_run_versions.reques'
        't_id AS request_id, verification_run_versions.request_version_id AS request_'
        'version_id, verification_run_versions.request_revision AS request_revision, '
        'verification_run_versions.run_id AS run_id, verification_run_versions.revisi'
        'on AS revision, verification_run_versions.previous_run_version_id AS previou'
        's_run_version_id, verification_run_versions.previous_revision AS previous_re'
        'vision, verification_run_versions.owner_id AS owner_id, verification_run_ver'
        'sions.writer_id AS writer_id, verification_run_versions.visibility AS visibi'
        'lity, verification_run_versions.status AS status, verification_run_versions.'
        'operation AS operation, verification_run_versions.run_snapshot AS run_snapsh'
        'ot, verification_run_versions.execution_plan AS execution_plan, verification'
        '_run_versions.plan_sha256 AS plan_sha256, verification_run_versions.input_sn'
        'apshot AS input_snapshot, verification_run_versions.snapshot_sha256 AS snaps'
        'hot_sha256, verification_run_versions.sources AS sources, verification_run_v'
        'ersions.required_source_read_set AS required_source_read_set, verification_r'
        'un_versions.source_basis AS source_basis, verification_run_versions.authorit'
        'y_snapshot AS authority_snapshot, verification_run_versions.intent_digest AS'
        ' intent_digest, verification_run_versions.reason AS reason, verification_run'
        '_versions.id AS id, verification_run_versions.tenant_id AS tenant_id, verifi'
        'cation_run_versions.created_at AS created_at, verification_run_versions.cate'
        'gory_id AS category_id \nFROM verification_run_versions \nWHERE verification'
        "_run_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true"
        "), '') AS UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT pro"
        'jects.product_id AS product_id, projects.owner_id AS owner_id, projects.name'
        ' AS name, projects.purpose AS purpose, projects.scope AS scope, projects.vis'
        'ibility AS visibility, projects.status AS status, projects.revision AS revis'
        'ion, projects.current_plan_id AS current_plan_id, projects.trigger_type AS t'
        'rigger_type, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g'
        '0_decision_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.'
        'created_at AS created_at, projects.category_id AS category_id \nFROM project'
        "s \nWHERE projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id',"
        " true), '') AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELEC"
        'T products.name AS name, products.purpose AS purpose, products.revision AS r'
        'evision, products.lifecycle_epoch AS lifecycle_epoch, products.status AS sta'
        'tus, products.owner_id AS owner_id, products.parent_product_id AS parent_pro'
        'duct_id, products.category_id AS category_id, products.visibility AS visibil'
        'ity, products.target_price AS target_price, products.target_price_currency A'
        'S target_price_currency, products.target_price_basis AS target_price_basis, '
        'products.target_price_includes_tax AS target_price_includes_tax, products.ta'
        'rget_price_as_of AS target_price_as_of, products.id AS id, products.tenant_i'
        'd AS tenant_id, products.created_at AS created_at \nFROM products \nWHERE pr'
        "oducts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') "
        'AS UUID)), \nshared_enterprise_builds AS MATERIALIZED \n(SELECT builds.produ'
        'ct_id AS product_id, builds.project_id AS project_id, builds.project_revisio'
        'n AS project_revision, builds.engineering_configuration_id AS engineering_co'
        'nfiguration_id, builds.manufacturing_configuration_id AS manufacturing_confi'
        'guration_id, builds.previous_build_id AS previous_build_id, builds.owner_id '
        'AS owner_id, builds.name AS name, builds.type AS type, builds.purpose AS pur'
        'pose, builds.planned_quantity AS planned_quantity, builds.unit AS unit, buil'
        'ds.planned_start AS planned_start, builds.planned_end AS planned_end, builds'
        '.verification_objectives AS verification_objectives, builds.disposition_plan'
        ' AS disposition_plan, builds.visibility AS visibility, builds.revision AS re'
        'vision, builds.status AS status, builds.id AS id, builds.tenant_id AS tenant'
        '_id, builds.created_at AS created_at, builds.category_id AS category_id \nFR'
        "OM builds \nWHERE builds.tenant_id = CAST(nullif(current_setting('pdos.tenan"
        "t_id', true), '') AS UUID)), \nshared_enterprise_verification_current_runs A"
        'S MATERIALIZED \n(SELECT verification_current_runs.product_id AS product_id,'
        ' verification_current_runs.request_id AS request_id, verification_current_ru'
        'ns.run_id AS run_id, verification_current_runs.run_version_id AS run_version'
        '_id, verification_current_runs.run_revision AS run_revision, verification_cu'
        'rrent_runs.id AS id, verification_current_runs.tenant_id AS tenant_id, verif'
        'ication_current_runs.created_at AS created_at, verification_current_runs.cat'
        'egory_id AS category_id \nFROM verification_current_runs \nWHERE verificatio'
        "n_current_runs.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', tru"
        "e), '') AS UUID)), \nshared_enterprise_test_result_actions AS MATERIALIZED "
        '\n(SELECT test_result_actions.operation AS operation, test_result_actions.ac'
        'tor_id AS actor_id, test_result_actions.intent_digest AS intent_digest, test'
        '_result_actions.request_version_id AS request_version_id, test_result_action'
        's.request_revision AS request_revision, test_result_actions.next_request_ver'
        'sion_id AS next_request_version_id, test_result_actions.next_request_revisio'
        'n AS next_request_revision, test_result_actions.run_version_id AS run_versio'
        'n_id, test_result_actions.run_revision AS run_revision, test_result_actions.'
        'next_run_version_id AS next_run_version_id, test_result_actions.next_run_rev'
        'ision AS next_run_revision, test_result_actions.capture_id AS capture_id, te'
        'st_result_actions.projection_id AS projection_id, test_result_actions.input_'
        'snapshot AS input_snapshot, test_result_actions.authority_snapshot AS author'
        'ity_snapshot, test_result_actions.event AS event, test_result_actions.source'
        's AS sources, test_result_actions.required_source_read_set AS required_sourc'
        'e_read_set, test_result_actions.source_basis AS source_basis, test_result_ac'
        'tions.reason AS reason, test_result_actions.product_id AS product_id, test_r'
        'esult_actions.project_id AS project_id, test_result_actions.build_id AS buil'
        'd_id, test_result_actions.request_id AS request_id, test_result_actions.run_'
        'id AS run_id, test_result_actions.revision AS revision, test_result_actions.'
        'owner_id AS owner_id, test_result_actions.visibility AS visibility, test_res'
        'ult_actions.status AS status, test_result_actions.id AS id, test_result_acti'
        'ons.tenant_id AS tenant_id, test_result_actions.created_at AS created_at, te'
        'st_result_actions.category_id AS category_id \nFROM test_result_actions \nWH'
        "ERE test_result_actions.tenant_id = CAST(nullif(current_setting('pdos.tenant"
        "_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_test_run AS "
        "\n(SELECT 'test_run' AS source_type, shared_enterprise_verification_run_vers"
        'ions.id AS source_id, shared_enterprise_verification_run_versions.tenant_id '
        'AS tenant_id, shared_enterprise_verification_run_versions.category_id AS cat'
        'egory_id, shared_enterprise_verification_run_versions.product_id AS product_'
        'id, shared_enterprise_verification_run_versions.project_id AS project_id, CA'
        'ST(NULL AS UUID) AS proposal_id, shared_enterprise_verification_run_versions'
        '.owner_id AS owner_id, shared_enterprise_verification_run_versions.revision '
        "AS source_revision, '\u6d4b\u8bd5\u8fd0\u884c \xb7 ' || CAST(shared_enterpri"
        'se_verification_run_versions.run_id AS TEXT) AS title, encode(sha256(convert'
        "_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_verification"
        "_run_versions.run_id, 'kind', 'test_run', 'facts', jsonb_build_object('id', "
        "shared_enterprise_verification_run_versions.run_snapshot['id'], 'revision', "
        "shared_enterprise_verification_run_versions.run_snapshot['revision'], 'reque"
        "st_id', shared_enterprise_verification_run_versions.run_snapshot['request_id"
        "'], 'status', shared_enterprise_verification_run_versions.run_snapshot['stat"
        "us'], 'result', shared_enterprise_verification_run_versions.run_snapshot['re"
        "sult']) || jsonb_build_object('actual_start', jsonb_build_object('occurred_a"
        "t', shared_enterprise_verification_run_versions.run_snapshot['actual_start']"
        "['occurred_at'], 'original_timezone', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['actual_start']['original_timezone'], 'effective_at', sha"
        "red_enterprise_verification_run_versions.run_snapshot['actual_start']['effec"
        "tive_at']), 'actual_end', jsonb_build_object('occurred_at', shared_enterpris"
        "e_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'orig"
        "inal_timezone', shared_enterprise_verification_run_versions.run_snapshot['ac"
        "tual_end']['original_timezone'], 'effective_at', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['actual_end']['effective_at']), 'preliminary_r"
        "esult', jsonb_build_object('occurred_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['preliminary_result']['occurred_at'], 'original_timez"
        "one', shared_enterprise_verification_run_versions.run_snapshot['preliminary_"
        "result']['original_timezone'], 'effective_at', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['preliminary_result']['effective_at']), 'final_r"
        "esult', jsonb_build_object('occurred_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['final_result']['occurred_at'], 'original_timezone', "
        "shared_enterprise_verification_run_versions.run_snapshot['final_result']['or"
        "iginal_timezone'], 'effective_at', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['final_result']['effective_at'])), 'source_refs', (SELECT co"
        "alesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_rea"
        "ds_test_run.value['artifact_id'], 'version', enterprise_reads_test_run.value"
        "['expected_revision']) ORDER BY enterprise_reads_test_run.value ->> 'artifac"
        "t_id', enterprise_reads_test_run.value ->> 'expected_revision'), jsonb_build"
        '_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_verifi'
        'cation_run_versions.required_source_read_set) AS enterprise_reads_test_run(v'
        "alue)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS con"
        "tent_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_verif"
        "ication_run_versions.run_id, 'kind', 'test_run', 'facts', jsonb_build_object"
        "('id', shared_enterprise_verification_run_versions.run_snapshot['id'], 'revi"
        "sion', shared_enterprise_verification_run_versions.run_snapshot['revision'],"
        " 'request_id', shared_enterprise_verification_run_versions.run_snapshot['req"
        "uest_id'], 'status', shared_enterprise_verification_run_versions.run_snapsho"
        "t['status'], 'result', shared_enterprise_verification_run_versions.run_snaps"
        "hot['result']) || jsonb_build_object('actual_start', jsonb_build_object('occ"
        "urred_at', shared_enterprise_verification_run_versions.run_snapshot['actual_"
        "start']['occurred_at'], 'original_timezone', shared_enterprise_verification_"
        "run_versions.run_snapshot['actual_start']['original_timezone'], 'effective_a"
        "t', shared_enterprise_verification_run_versions.run_snapshot['actual_start']"
        "['effective_at']), 'actual_end', jsonb_build_object('occurred_at', shared_en"
        "terprise_verification_run_versions.run_snapshot['actual_end']['occurred_at']"
        ", 'original_timezone', shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_end']['original_timezone'], 'effective_at', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['actual_end']['effective_at']), 'prelim"
        "inary_result', jsonb_build_object('occurred_at', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['preliminary_result']['occurred_at'], 'origina"
        "l_timezone', shared_enterprise_verification_run_versions.run_snapshot['preli"
        "minary_result']['original_timezone'], 'effective_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['preliminary_result']['effective_at']), '"
        "final_result', jsonb_build_object('occurred_at', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['final_result']['occurred_at'], 'original_time"
        "zone', shared_enterprise_verification_run_versions.run_snapshot['final_resul"
        "t']['original_timezone'], 'effective_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['final_result']['effective_at'])), 'source_refs', (SE"
        "LECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpr"
        "ise_reads_test_run.value['artifact_id'], 'version', enterprise_reads_test_ru"
        "n.value['expected_revision']) ORDER BY enterprise_reads_test_run.value ->> '"
        "artifact_id', enterprise_reads_test_run.value ->> 'expected_revision'), json"
        'b_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise'
        '_verification_run_versions.required_source_read_set) AS enterprise_reads_tes'
        "t_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(json"
        "b_build_object('object_id', shared_enterprise_verification_run_versions.run_"
        "id, 'kind', 'test_run', 'facts', jsonb_build_object('id', shared_enterprise_"
        "verification_run_versions.run_snapshot['id'], 'revision', shared_enterprise_"
        "verification_run_versions.run_snapshot['revision'], 'request_id', shared_ent"
        "erprise_verification_run_versions.run_snapshot['request_id'], 'status', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['status'], 'result', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['result']) || jsonb_b"
        "uild_object('actual_start', jsonb_build_object('occurred_at', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['actual_start']['occurred_at'], '"
        "original_timezone', shared_enterprise_verification_run_versions.run_snapshot"
        "['actual_start']['original_timezone'], 'effective_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['actual_start']['effective_at']), 'actua"
        "l_end', jsonb_build_object('occurred_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['actual_end']['occurred_at'], 'original_timezone', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['actual_end']['origin"
        "al_timezone'], 'effective_at', shared_enterprise_verification_run_versions.r"
        "un_snapshot['actual_end']['effective_at']), 'preliminary_result', jsonb_buil"
        "d_object('occurred_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['preliminary_result']['occurred_at'], 'original_timezone', shared_enter"
        "prise_verification_run_versions.run_snapshot['preliminary_result']['original"
        "_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run"
        "_snapshot['preliminary_result']['effective_at']), 'final_result', jsonb_buil"
        "d_object('occurred_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['final_result']['occurred_at'], 'original_timezone', shared_enterprise_"
        "verification_run_versions.run_snapshot['final_result']['original_timezone'],"
        " 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['f"
        "inal_result']['effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(j"
        "sonb_build_object('type', 'artifact', 'id', enterprise_reads_test_run.value["
        "'artifact_id'], 'version', enterprise_reads_test_run.value['expected_revisio"
        "n']) ORDER BY enterprise_reads_test_run.value ->> 'artifact_id', enterprise_"
        "reads_test_run.value ->> 'expected_revision'), jsonb_build_array()) AS coale"
        'sce_1 \nFROM jsonb_array_elements(shared_enterprise_verification_run_version'
        "s.required_source_read_set) AS enterprise_reads_test_run(value)), 'record_po"
        "licy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        '\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, shared_enter"
        "prise_verification_run_versions.visibility != 'category' OR shared_enterpris"
        "e_projects.visibility != 'category' OR shared_enterprise_products.visibility"
        " != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enter"
        'prise_verification_run_versions.required_source_read_set) AS enterprise_read'
        's_test_run(value) JOIN enterprise_authoritative_artifacts_test_run ON enterp'
        'rise_authoritative_artifacts_test_run.tenant_id = shared_enterprise_verifica'
        'tion_run_versions.tenant_id AND enterprise_authoritative_artifacts_test_run.'
        "source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_test_run.private)) OR shared_en'
        "terprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1 \nFROM"
        ' jsonb_array_elements(shared_enterprise_verification_run_versions.required_s'
        'ource_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authorit'
        'ative_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tena'
        'nt_id = shared_enterprise_verification_run_versions.tenant_id AND enterprise'
        '_authoritative_artifacts_test_run.source_id = CAST((enterprise_reads_test_ru'
        "n.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifac"
        'ts_test_run.customer_original) AS customer_original, shared_enterprise_verif'
        'ication_current_runs.run_version_id = shared_enterprise_verification_run_ver'
        'sions.id AS is_current, shared_enterprise_verification_run_versions.created_'
        'at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_verif'
        'ication_run_versions.run_id AS object_id, (SELECT coalesce(array_agg(enterpr'
        'ise_authoritative_artifacts_test_run.original_id), ARRAY[]::UUID[]) AS coale'
        'sce_2 \nFROM jsonb_array_elements(shared_enterprise_verification_run_version'
        's.required_source_read_set) AS enterprise_reads_test_run(value) JOIN enterpr'
        'ise_authoritative_artifacts_test_run ON enterprise_authoritative_artifacts_t'
        'est_run.tenant_id = shared_enterprise_verification_run_versions.tenant_id AN'
        'D enterprise_authoritative_artifacts_test_run.source_id = CAST((enterprise_r'
        "eads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorita"
        'tive_artifacts_test_run.original_id IS NOT NULL) AS original_ids, CASE WHEN '
        '(EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_verification'
        '_run_versions.required_source_read_set) AS enterprise_reads_test_run(value) '
        'JOIN enterprise_authoritative_artifacts_test_run ON enterprise_authoritative'
        '_artifacts_test_run.tenant_id = shared_enterprise_verification_run_versions.'
        'tenant_id AND enterprise_authoritative_artifacts_test_run.source_id = CAST(('
        "enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterpri"
        'se_authoritative_artifacts_test_run.source_revision != CAST((enterprise_read'
        "s_test_run.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck'"
        " ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_verificati"
        'on_run_versions JOIN shared_enterprise_projects ON shared_enterprise_project'
        's.tenant_id = shared_enterprise_verification_run_versions.tenant_id AND shar'
        'ed_enterprise_projects.product_id = shared_enterprise_verification_run_versi'
        'ons.product_id AND shared_enterprise_projects.id = shared_enterprise_verific'
        'ation_run_versions.project_id AND shared_enterprise_projects.category_id = s'
        'hared_enterprise_verification_run_versions.category_id JOIN shared_enterpris'
        'e_products ON shared_enterprise_products.tenant_id = shared_enterprise_verif'
        'ication_run_versions.tenant_id AND shared_enterprise_products.id = shared_en'
        'terprise_verification_run_versions.product_id AND shared_enterprise_products'
        '.category_id = shared_enterprise_verification_run_versions.category_id JOIN '
        'shared_enterprise_builds ON shared_enterprise_builds.tenant_id = shared_ente'
        'rprise_verification_run_versions.tenant_id AND shared_enterprise_builds.cate'
        'gory_id = shared_enterprise_verification_run_versions.category_id AND shared'
        '_enterprise_builds.product_id = shared_enterprise_verification_run_versions.'
        'product_id AND shared_enterprise_builds.project_id = shared_enterprise_verif'
        'ication_run_versions.project_id AND shared_enterprise_builds.id = shared_ent'
        'erprise_verification_run_versions.build_id AND shared_enterprise_builds.revi'
        'sion = shared_enterprise_verification_run_versions.build_revision JOIN share'
        'd_enterprise_verification_current_runs ON shared_enterprise_verification_cur'
        'rent_runs.tenant_id = shared_enterprise_verification_run_versions.tenant_id '
        'AND shared_enterprise_verification_current_runs.product_id = shared_enterpri'
        'se_verification_run_versions.product_id AND shared_enterprise_verification_c'
        'urrent_runs.run_id = shared_enterprise_verification_run_versions.run_id \nWH'
        'ERE shared_enterprise_verification_run_versions.tenant_id = CAST(nullif(curr'
        "ent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 "
        '\nFROM jsonb_array_elements(shared_enterprise_verification_run_versions.requ'
        'ired_source_read_set) AS enterprise_reads_test_run(value) \nWHERE NOT (EXIST'
        'S (SELECT 1 \nFROM enterprise_authoritative_artifacts_test_run \nWHERE enter'
        'prise_authoritative_artifacts_test_run.tenant_id = shared_enterprise_verific'
        'ation_run_versions.tenant_id AND enterprise_authoritative_artifacts_test_run'
        ".source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUI"
        "D))))) UNION ALL SELECT 'test_run' AS source_type, shared_enterprise_test_re"
        'sult_actions.id AS source_id, shared_enterprise_test_result_actions.tenant_i'
        'd AS tenant_id, shared_enterprise_test_result_actions.category_id AS categor'
        'y_id, shared_enterprise_test_result_actions.product_id AS product_id, shared'
        '_enterprise_test_result_actions.project_id AS project_id, CAST(NULL AS UUID)'
        ' AS proposal_id, shared_enterprise_test_result_actions.owner_id AS owner_id,'
        ' shared_enterprise_test_result_actions.revision AS source_revision, CASE WHE'
        "N (shared_enterprise_test_result_actions.operation = 'test.run.review') THEN"
        " '\u4e13\u4e1a\u8bc4\u5ba1\u8bb0\u5f55 \xb7 ' WHEN (shared_enterprise_test_r"
        "esult_actions.operation = 'test.disposition.decide') THEN '\u6d4b\u8bd5"
        "\u5904\u7f6e\u8bb0\u5f55 \xb7 ' ELSE '\u6d4b\u8bd5\u7ed3\u679c\u8bb0\u5f55 "
        "\xb7 ' END || CAST(shared_enterprise_test_result_actions.run_id AS TEXT) AS "
        "title, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', sh"
        "ared_enterprise_test_result_actions.run_id, 'kind', 'test_run', 'facts', (js"
        "onb_build_object('id', shared_enterprise_verification_run_versions.run_snaps"
        "hot['id'], 'revision', shared_enterprise_verification_run_versions.run_snaps"
        "hot['revision'], 'request_id', shared_enterprise_verification_run_versions.r"
        "un_snapshot['request_id'], 'status', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['status'], 'result', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['result']) || jsonb_build_object('record_kind', 'test_ru"
        "n', 'coverage', (SELECT coalesce(jsonb_agg(jsonb_build_object('sample_id', e"
        "nterprise_run_coverage.value['sample_id'], 'item_id', enterprise_run_coverag"
        "e.value['item_id']) ORDER BY enterprise_run_coverage.ordinal), jsonb_build_a"
        'rray()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(shared_enterprise'
        "_verification_run_versions.run_snapshot['coverage'], CAST('[]' AS JSONB))) W"
        "ITH ORDINALITY AS enterprise_run_coverage(value, ordinal)), 'computed_result"
        "s', (SELECT coalesce(jsonb_agg(jsonb_build_object('coverage', enterprise_com"
        "puted_results.value['coverage'], 'result', enterprise_computed_results.value"
        "['result'], 'measurement_id', enterprise_computed_results.value['measurement"
        "_id']) ORDER BY enterprise_computed_results.ordinal), jsonb_build_array()) A"
        'S coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterprise_verifica'
        "tion_run_versions.run_snapshot['computed_results'], CAST('[]' AS JSONB))) WI"
        "TH ORDINALITY AS enterprise_computed_results(value, ordinal)), 'professional"
        "_conclusion', CASE WHEN (((shared_enterprise_verification_run_versions.run_s"
        "napshot['professional_conclusion']) ->> 'actor_id') IS NULL) THEN CAST(NULL "
        "AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_verification_run"
        "_versions.run_snapshot['professional_conclusion']['text'], 'actor_id', share"
        "d_enterprise_verification_run_versions.run_snapshot['professional_conclusion"
        "']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_v"
        "erification_run_versions.run_snapshot['professional_conclusion']['at']) ->> "
        "'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('oc"
        "curred_at', shared_enterprise_verification_run_versions.run_snapshot['profes"
        "sional_conclusion']['at']['occurred_at'], 'original_timezone', shared_enterp"
        "rise_verification_run_versions.run_snapshot['professional_conclusion']['at']"
        "['original_timezone'], 'effective_at', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['professional_conclusion']['at']['effective_at'], 'recei"
        "ved_at', shared_enterprise_verification_run_versions.run_snapshot['professio"
        "nal_conclusion']['at']['received_at'], 'actor_id', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['professional_conclusion']['at']['actor_id']"
        ") END, 'source_reference', jsonb_build_object('kind', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['professional_conclusion']['source']['kin"
        "d'], 'id', shared_enterprise_verification_run_versions.run_snapshot['profess"
        "ional_conclusion']['source']['id'], 'revision', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['professional_conclusion']['source']['revision'"
        "])) END, 'disposition', CASE WHEN (((shared_enterprise_verification_run_vers"
        "ions.run_snapshot['disposition']) ->> 'actor_id') IS NULL) THEN CAST(NULL AS"
        " JSONB) ELSE jsonb_build_object('text', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['disposition']['text'], 'actor_id', shared_enterprise_v"
        "erification_run_versions.run_snapshot['disposition']['actor_id']) || jsonb_b"
        "uild_object('at', CASE WHEN (((shared_enterprise_verification_run_versions.r"
        "un_snapshot['disposition']['at']) ->> 'occurred_at') IS NULL) THEN CAST(NULL"
        " AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['disposition']['at']['occurred_at'], 'origina"
        "l_timezone', shared_enterprise_verification_run_versions.run_snapshot['dispo"
        "sition']['at']['original_timezone'], 'effective_at', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['at']['effective_at'], 'rec"
        "eived_at', shared_enterprise_verification_run_versions.run_snapshot['disposi"
        "tion']['at']['received_at'], 'actor_id', shared_enterprise_verification_run_"
        "versions.run_snapshot['disposition']['at']['actor_id']) END, 'source_referen"
        "ce', jsonb_build_object('kind', shared_enterprise_verification_run_versions."
        "run_snapshot['disposition']['source']['kind'], 'id', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['disposition']['source']['id'], 'revision'"
        ", shared_enterprise_verification_run_versions.run_snapshot['disposition']['s"
        "ource']['revision'])) END, 'actual_start', CASE WHEN (((shared_enterprise_ve"
        "rification_run_versions.run_snapshot['actual_start']) ->> 'occurred_at') IS "
        "NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['actual_start']['occurred"
        "_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_"
        "snapshot['actual_start']['original_timezone'], 'effective_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['actual_start']['effective_at'],"
        " 'received_at', shared_enterprise_verification_run_versions.run_snapshot['ac"
        "tual_start']['received_at'], 'actor_id', shared_enterprise_verification_run_"
        "versions.run_snapshot['actual_start']['actor_id']) END, 'actual_end', CASE W"
        "HEN (((shared_enterprise_verification_run_versions.run_snapshot['actual_end'"
        "]) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_obj"
        "ect('occurred_at', shared_enterprise_verification_run_versions.run_snapshot["
        "'actual_end']['occurred_at'], 'original_timezone', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['actual_end']['original_timezone'], 'effecti"
        "ve_at', shared_enterprise_verification_run_versions.run_snapshot['actual_end"
        "']['effective_at'], 'received_at', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['actual_end']['received_at'], 'actor_id', shared_enterprise_"
        "verification_run_versions.run_snapshot['actual_end']['actor_id']) END, 'prel"
        "iminary_result', CASE WHEN (((shared_enterprise_verification_run_versions.ru"
        "n_snapshot['preliminary_result']) ->> 'occurred_at') IS NULL) THEN CAST(NULL"
        " AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['preliminary_result']['occurred_at'], 'origin"
        "al_timezone', shared_enterprise_verification_run_versions.run_snapshot['prel"
        "iminary_result']['original_timezone'], 'effective_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['preliminary_result']['effective_at'], '"
        "received_at', shared_enterprise_verification_run_versions.run_snapshot['prel"
        "iminary_result']['received_at'], 'actor_id', shared_enterprise_verification_"
        "run_versions.run_snapshot['preliminary_result']['actor_id']) END, 'final_res"
        "ult', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapshot["
        "'final_result']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE j"
        "sonb_build_object('occurred_at', shared_enterprise_verification_run_versions"
        ".run_snapshot['final_result']['occurred_at'], 'original_timezone', shared_en"
        "terprise_verification_run_versions.run_snapshot['final_result']['original_ti"
        "mezone'], 'effective_at', shared_enterprise_verification_run_versions.run_sn"
        "apshot['final_result']['effective_at'], 'received_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['final_result']['received_at'], 'actor_i"
        "d', shared_enterprise_verification_run_versions.run_snapshot['final_result']"
        "['actor_id']) END)) || jsonb_build_object('record_kind', 'test_result_action"
        "', 'operation', shared_enterprise_test_result_actions.operation, 'actor_id',"
        " shared_enterprise_test_result_actions.actor_id, 'run_version_id', shared_en"
        "terprise_verification_run_versions.id, 'run_revision', shared_enterprise_ver"
        "ification_run_versions.revision), 'source_refs', (SELECT coalesce(jsonb_agg("
        "jsonb_build_object('type', 'artifact', 'id', enterprise_reads_test_run.value"
        "['artifact_id'], 'version', enterprise_reads_test_run.value['expected_revisi"
        "on']) ORDER BY enterprise_reads_test_run.value ->> 'artifact_id', enterprise"
        "_reads_test_run.value ->> 'expected_revision'), jsonb_build_array()) AS coal"
        'esce_5 \nFROM jsonb_array_elements(shared_enterprise_test_result_actions.req'
        "uired_source_read_set) AS enterprise_reads_test_run(value)), 'record_policy'"
        ", '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        '\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jso"
        "nb_build_object('object_id', shared_enterprise_test_result_actions.run_id, '"
        "kind', 'test_run', 'facts', (jsonb_build_object('id', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['id'], 'revision', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['revision'], 'request_id', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['request_id'], 'status', shared_e"
        "nterprise_verification_run_versions.run_snapshot['status'], 'result', shared"
        "_enterprise_verification_run_versions.run_snapshot['result']) || jsonb_build"
        "_object('record_kind', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('sample_id', enterprise_run_coverage.value['sample_id'], 'i"
        "tem_id', enterprise_run_coverage.value['item_id']) ORDER BY enterprise_run_c"
        'overage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elem'
        "ents(coalesce(shared_enterprise_verification_run_versions.run_snapshot['cove"
        "rage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_coverage(val"
        "ue, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jsonb_build_ob"
        "ject('coverage', enterprise_computed_results.value['coverage'], 'result', en"
        "terprise_computed_results.value['result'], 'measurement_id', enterprise_comp"
        "uted_results.value['measurement_id']) ORDER BY enterprise_computed_results.o"
        'rdinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coal'
        "esce(shared_enterprise_verification_run_versions.run_snapshot['computed_resu"
        "lts'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_computed_results("
        "value, ordinal)), 'professional_conclusion', CASE WHEN (((shared_enterprise_"
        "verification_run_versions.run_snapshot['professional_conclusion']) ->> 'acto"
        "r_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', sha"
        "red_enterprise_verification_run_versions.run_snapshot['professional_conclusi"
        "on']['text'], 'actor_id', shared_enterprise_verification_run_versions.run_sn"
        "apshot['professional_conclusion']['actor_id']) || jsonb_build_object('at', C"
        "ASE WHEN (((shared_enterprise_verification_run_versions.run_snapshot['profes"
        "sional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSO"
        "NB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['professional_conclusion']['at']['occurred_at'], 'or"
        "iginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['"
        "professional_conclusion']['at']['original_timezone'], 'effective_at', shared"
        "_enterprise_verification_run_versions.run_snapshot['professional_conclusion'"
        "]['at']['effective_at'], 'received_at', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['professional_conclusion']['at']['received_at'], 'actor"
        "_id', shared_enterprise_verification_run_versions.run_snapshot['professional"
        "_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_build_object"
        "('kind', shared_enterprise_verification_run_versions.run_snapshot['professio"
        "nal_conclusion']['source']['kind'], 'id', shared_enterprise_verification_run"
        "_versions.run_snapshot['professional_conclusion']['source']['id'], 'revision"
        "', shared_enterprise_verification_run_versions.run_snapshot['professional_co"
        "nclusion']['source']['revision'])) END, 'disposition', CASE WHEN (((shared_e"
        "nterprise_verification_run_versions.run_snapshot['disposition']) ->> 'actor_"
        "id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', share"
        "d_enterprise_verification_run_versions.run_snapshot['disposition']['text'], "
        "'actor_id', shared_enterprise_verification_run_versions.run_snapshot['dispos"
        "ition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterpr"
        "ise_verification_run_versions.run_snapshot['disposition']['at']) ->> 'occurr"
        "ed_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_"
        "at', shared_enterprise_verification_run_versions.run_snapshot['disposition']"
        "['at']['occurred_at'], 'original_timezone', shared_enterprise_verification_r"
        "un_versions.run_snapshot['disposition']['at']['original_timezone'], 'effecti"
        "ve_at', shared_enterprise_verification_run_versions.run_snapshot['dispositio"
        "n']['at']['effective_at'], 'received_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['disposition']['at']['received_at'], 'actor_id', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['disposition']['at']['a"
        "ctor_id']) END, 'source_reference', jsonb_build_object('kind', shared_enterp"
        "rise_verification_run_versions.run_snapshot['disposition']['source']['kind']"
        ", 'id', shared_enterprise_verification_run_versions.run_snapshot['dispositio"
        "n']['source']['id'], 'revision', shared_enterprise_verification_run_versions"
        ".run_snapshot['disposition']['source']['revision'])) END, 'actual_start', CA"
        "SE WHEN (((shared_enterprise_verification_run_versions.run_snapshot['actual_"
        "start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_bui"
        "ld_object('occurred_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_start']['occurred_at'], 'original_timezone', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_start']['original_timezone']"
        ", 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['"
        "actual_start']['effective_at'], 'received_at', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['actual_start']['received_at'], 'actor_id', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['actual_start']['actor_"
        "id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verification_run_ver"
        "sions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) THEN CAST(NULL"
        " AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['actual_end']['occurred_at'], 'original_timez"
        "one', shared_enterprise_verification_run_versions.run_snapshot['actual_end']"
        "['original_timezone'], 'effective_at', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['actual_end']['effective_at'], 'received_at', shared_ent"
        "erprise_verification_run_versions.run_snapshot['actual_end']['received_at'],"
        " 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['actua"
        "l_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((shared_enterpri"
        "se_verification_run_versions.run_snapshot['preliminary_result']) ->> 'occurr"
        "ed_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_"
        "at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_r"
        "esult']['occurred_at'], 'original_timezone', shared_enterprise_verification_"
        "run_versions.run_snapshot['preliminary_result']['original_timezone'], 'effec"
        "tive_at', shared_enterprise_verification_run_versions.run_snapshot['prelimin"
        "ary_result']['effective_at'], 'received_at', shared_enterprise_verification_"
        "run_versions.run_snapshot['preliminary_result']['received_at'], 'actor_id', "
        "shared_enterprise_verification_run_versions.run_snapshot['preliminary_result"
        "']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['final_result']) ->> 'occurred_at') IS NULL) "
        "THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enter"
        "prise_verification_run_versions.run_snapshot['final_result']['occurred_at'],"
        " 'original_timezone', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['final_result']['original_timezone'], 'effective_at', shared_enterprise_v"
        "erification_run_versions.run_snapshot['final_result']['effective_at'], 'rece"
        "ived_at', shared_enterprise_verification_run_versions.run_snapshot['final_re"
        "sult']['received_at'], 'actor_id', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['final_result']['actor_id']) END)) || jsonb_build_object('re"
        "cord_kind', 'test_result_action', 'operation', shared_enterprise_test_result"
        "_actions.operation, 'actor_id', shared_enterprise_test_result_actions.actor_"
        "id, 'run_version_id', shared_enterprise_verification_run_versions.id, 'run_r"
        "evision', shared_enterprise_verification_run_versions.revision), 'source_ref"
        "s', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', "
        "enterprise_reads_test_run.value['artifact_id'], 'version', enterprise_reads_"
        "test_run.value['expected_revision']) ORDER BY enterprise_reads_test_run.valu"
        "e ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expected_revision'"
        '), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ent'
        'erprise_test_result_actions.required_source_read_set) AS enterprise_reads_te'
        "st_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(json"
        "b_build_object('object_id', shared_enterprise_test_result_actions.run_id, 'k"
        "ind', 'test_run', 'facts', (jsonb_build_object('id', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['id'], 'revision', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['revision'], 'request_id', shared_enterpri"
        "se_verification_run_versions.run_snapshot['request_id'], 'status', shared_en"
        "terprise_verification_run_versions.run_snapshot['status'], 'result', shared_"
        "enterprise_verification_run_versions.run_snapshot['result']) || jsonb_build_"
        "object('record_kind', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('sample_id', enterprise_run_coverage.value['sample_id'], 'it"
        "em_id', enterprise_run_coverage.value['item_id']) ORDER BY enterprise_run_co"
        'verage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_eleme'
        "nts(coalesce(shared_enterprise_verification_run_versions.run_snapshot['cover"
        "age'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_coverage(valu"
        "e, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jsonb_build_obj"
        "ect('coverage', enterprise_computed_results.value['coverage'], 'result', ent"
        "erprise_computed_results.value['result'], 'measurement_id', enterprise_compu"
        "ted_results.value['measurement_id']) ORDER BY enterprise_computed_results.or"
        'dinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_array_elements(coale'
        "sce(shared_enterprise_verification_run_versions.run_snapshot['computed_resul"
        "ts'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_computed_results(v"
        "alue, ordinal)), 'professional_conclusion', CASE WHEN (((shared_enterprise_v"
        "erification_run_versions.run_snapshot['professional_conclusion']) ->> 'actor"
        "_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['professional_conclusio"
        "n']['text'], 'actor_id', shared_enterprise_verification_run_versions.run_sna"
        "pshot['professional_conclusion']['actor_id']) || jsonb_build_object('at', CA"
        "SE WHEN (((shared_enterprise_verification_run_versions.run_snapshot['profess"
        "ional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSON"
        "B) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['professional_conclusion']['at']['occurred_at'], 'ori"
        "ginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['p"
        "rofessional_conclusion']['at']['original_timezone'], 'effective_at', shared_"
        "enterprise_verification_run_versions.run_snapshot['professional_conclusion']"
        "['at']['effective_at'], 'received_at', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['professional_conclusion']['at']['received_at'], 'actor_"
        "id', shared_enterprise_verification_run_versions.run_snapshot['professional_"
        "conclusion']['at']['actor_id']) END, 'source_reference', jsonb_build_object("
        "'kind', shared_enterprise_verification_run_versions.run_snapshot['profession"
        "al_conclusion']['source']['kind'], 'id', shared_enterprise_verification_run_"
        "versions.run_snapshot['professional_conclusion']['source']['id'], 'revision'"
        ", shared_enterprise_verification_run_versions.run_snapshot['professional_con"
        "clusion']['source']['revision'])) END, 'disposition', CASE WHEN (((shared_en"
        "terprise_verification_run_versions.run_snapshot['disposition']) ->> 'actor_i"
        "d') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared"
        "_enterprise_verification_run_versions.run_snapshot['disposition']['text'], '"
        "actor_id', shared_enterprise_verification_run_versions.run_snapshot['disposi"
        "tion']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterpri"
        "se_verification_run_versions.run_snapshot['disposition']['at']) ->> 'occurre"
        "d_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_a"
        "t', shared_enterprise_verification_run_versions.run_snapshot['disposition']["
        "'at']['occurred_at'], 'original_timezone', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['disposition']['at']['original_timezone'], 'effectiv"
        "e_at', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['at']['effective_at'], 'received_at', shared_enterprise_verification_run_"
        "versions.run_snapshot['disposition']['at']['received_at'], 'actor_id', share"
        "d_enterprise_verification_run_versions.run_snapshot['disposition']['at']['ac"
        "tor_id']) END, 'source_reference', jsonb_build_object('kind', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['disposition']['source']['kind'],"
        " 'id', shared_enterprise_verification_run_versions.run_snapshot['disposition"
        "']['source']['id'], 'revision', shared_enterprise_verification_run_versions."
        "run_snapshot['disposition']['source']['revision'])) END, 'actual_start', CAS"
        "E WHEN (((shared_enterprise_verification_run_versions.run_snapshot['actual_s"
        "tart']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_buil"
        "d_object('occurred_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['actual_start']['occurred_at'], 'original_timezone', shared_enterprise_"
        "verification_run_versions.run_snapshot['actual_start']['original_timezone'],"
        " 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['a"
        "ctual_start']['effective_at'], 'received_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['actual_start']['received_at'], 'actor_id', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_start']['actor_i"
        "d']) END, 'actual_end', CASE WHEN (((shared_enterprise_verification_run_vers"
        "ions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) THEN CAST(NULL "
        "AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['actual_end']['occurred_at'], 'original_timezo"
        "ne', shared_enterprise_verification_run_versions.run_snapshot['actual_end']["
        "'original_timezone'], 'effective_at', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['actual_end']['effective_at'], 'received_at', shared_ente"
        "rprise_verification_run_versions.run_snapshot['actual_end']['received_at'], "
        "'actor_id', shared_enterprise_verification_run_versions.run_snapshot['actual"
        "_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((shared_enterpris"
        "e_verification_run_versions.run_snapshot['preliminary_result']) ->> 'occurre"
        "d_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_a"
        "t', shared_enterprise_verification_run_versions.run_snapshot['preliminary_re"
        "sult']['occurred_at'], 'original_timezone', shared_enterprise_verification_r"
        "un_versions.run_snapshot['preliminary_result']['original_timezone'], 'effect"
        "ive_at', shared_enterprise_verification_run_versions.run_snapshot['prelimina"
        "ry_result']['effective_at'], 'received_at', shared_enterprise_verification_r"
        "un_versions.run_snapshot['preliminary_result']['received_at'], 'actor_id', s"
        "hared_enterprise_verification_run_versions.run_snapshot['preliminary_result'"
        "]['actor_id']) END, 'final_result', CASE WHEN (((shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['final_result']) ->> 'occurred_at') IS NULL) T"
        "HEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['final_result']['occurred_at'], "
        "'original_timezone', shared_enterprise_verification_run_versions.run_snapsho"
        "t['final_result']['original_timezone'], 'effective_at', shared_enterprise_ve"
        "rification_run_versions.run_snapshot['final_result']['effective_at'], 'recei"
        "ved_at', shared_enterprise_verification_run_versions.run_snapshot['final_res"
        "ult']['received_at'], 'actor_id', shared_enterprise_verification_run_version"
        "s.run_snapshot['final_result']['actor_id']) END)) || jsonb_build_object('rec"
        "ord_kind', 'test_result_action', 'operation', shared_enterprise_test_result_"
        "actions.operation, 'actor_id', shared_enterprise_test_result_actions.actor_i"
        "d, 'run_version_id', shared_enterprise_verification_run_versions.id, 'run_re"
        "vision', shared_enterprise_verification_run_versions.revision), 'source_refs"
        "', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', e"
        "nterprise_reads_test_run.value['artifact_id'], 'version', enterprise_reads_t"
        "est_run.value['expected_revision']) ORDER BY enterprise_reads_test_run.value"
        " ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expected_revision')"
        ', jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_ente'
        'rprise_test_result_actions.required_source_read_set) AS enterprise_reads_tes'
        "t_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured'"
        " AS nature, shared_enterprise_test_result_actions.visibility != 'category' O"
        "R shared_enterprise_projects.visibility != 'category' OR shared_enterprise_p"
        "roducts.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_ele"
        'ments(shared_enterprise_test_result_actions.required_source_read_set) AS ent'
        'erprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_test_r'
        'un ON enterprise_authoritative_artifacts_test_run.tenant_id = shared_enterpr'
        'ise_test_result_actions.tenant_id AND enterprise_authoritative_artifacts_tes'
        "t_run.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') A"
        'S UUID) \nWHERE enterprise_authoritative_artifacts_test_run.private)) OR sha'
        "red_enterprise_verification_run_versions.visibility != 'category' OR shared_"
        "enterprise_builds.visibility != 'category' AS private, EXISTS (SELECT 1 \nFR"
        'OM jsonb_array_elements(shared_enterprise_test_result_actions.required_sourc'
        'e_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritativ'
        'e_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_i'
        'd = shared_enterprise_test_result_actions.tenant_id AND enterprise_authorita'
        'tive_artifacts_test_run.source_id = CAST((enterprise_reads_test_run.value ->'
        "> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_test_ru"
        'n.customer_original) AS customer_original, shared_enterprise_verification_cu'
        'rrent_runs.run_version_id = shared_enterprise_test_result_actions.next_run_v'
        'ersion_id AS is_current, shared_enterprise_test_result_actions.created_at AS'
        ' created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_test_resul'
        't_actions.run_id AS object_id, (SELECT coalesce(array_agg(enterprise_authori'
        'tative_artifacts_test_run.original_id), ARRAY[]::UUID[]) AS coalesce_6 \nFRO'
        'M jsonb_array_elements(shared_enterprise_test_result_actions.required_source'
        '_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative'
        '_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id'
        ' = shared_enterprise_test_result_actions.tenant_id AND enterprise_authoritat'
        'ive_artifacts_test_run.source_id = CAST((enterprise_reads_test_run.value ->>'
        " 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_test_run"
        '.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFRO'
        'M jsonb_array_elements(shared_enterprise_test_result_actions.required_source'
        '_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative'
        '_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id'
        ' = shared_enterprise_test_result_actions.tenant_id AND enterprise_authoritat'
        'ive_artifacts_test_run.source_id = CAST((enterprise_reads_test_run.value ->>'
        " 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_test_run"
        ".source_revision != CAST((enterprise_reads_test_run.value ->> 'expected_revi"
        "sion') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_s"
        'tatus \nFROM shared_enterprise_test_result_actions JOIN shared_enterprise_pr'
        'ojects ON shared_enterprise_projects.tenant_id = shared_enterprise_test_resu'
        'lt_actions.tenant_id AND shared_enterprise_projects.product_id = shared_ente'
        'rprise_test_result_actions.product_id AND shared_enterprise_projects.id = sh'
        'ared_enterprise_test_result_actions.project_id AND shared_enterprise_project'
        's.category_id = shared_enterprise_test_result_actions.category_id JOIN share'
        'd_enterprise_products ON shared_enterprise_products.tenant_id = shared_enter'
        'prise_test_result_actions.tenant_id AND shared_enterprise_products.id = shar'
        'ed_enterprise_test_result_actions.product_id AND shared_enterprise_products.'
        'category_id = shared_enterprise_test_result_actions.category_id JOIN shared_'
        'enterprise_verification_run_versions ON shared_enterprise_verification_run_v'
        'ersions.tenant_id = shared_enterprise_test_result_actions.tenant_id AND shar'
        'ed_enterprise_verification_run_versions.category_id = shared_enterprise_test'
        '_result_actions.category_id AND shared_enterprise_verification_run_versions.'
        'product_id = shared_enterprise_test_result_actions.product_id AND shared_ent'
        'erprise_verification_run_versions.project_id = shared_enterprise_test_result'
        '_actions.project_id AND shared_enterprise_verification_run_versions.build_id'
        ' = shared_enterprise_test_result_actions.build_id AND shared_enterprise_veri'
        'fication_run_versions.run_id = shared_enterprise_test_result_actions.run_id '
        'AND shared_enterprise_verification_run_versions.id = shared_enterprise_test_'
        'result_actions.next_run_version_id AND shared_enterprise_verification_run_ve'
        'rsions.revision = shared_enterprise_test_result_actions.next_run_revision JO'
        'IN shared_enterprise_builds ON shared_enterprise_builds.tenant_id = shared_e'
        'nterprise_test_result_actions.tenant_id AND shared_enterprise_builds.categor'
        'y_id = shared_enterprise_test_result_actions.category_id AND shared_enterpri'
        'se_builds.product_id = shared_enterprise_test_result_actions.product_id AND '
        'shared_enterprise_builds.project_id = shared_enterprise_test_result_actions.'
        'project_id AND shared_enterprise_builds.id = shared_enterprise_test_result_a'
        'ctions.build_id AND shared_enterprise_builds.revision = shared_enterprise_ve'
        'rification_run_versions.build_revision JOIN shared_enterprise_verification_c'
        'urrent_runs ON shared_enterprise_verification_current_runs.tenant_id = share'
        'd_enterprise_test_result_actions.tenant_id AND shared_enterprise_verificatio'
        'n_current_runs.product_id = shared_enterprise_test_result_actions.product_id'
        ' AND shared_enterprise_verification_current_runs.run_id = shared_enterprise_'
        'test_result_actions.run_id \nWHERE shared_enterprise_test_result_actions.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) A"
        'ND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_test_'
        'result_actions.required_source_read_set) AS enterprise_reads_test_run(value)'
        ' \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_tes'
        't_run \nWHERE enterprise_authoritative_artifacts_test_run.tenant_id = shared'
        '_enterprise_test_result_actions.tenant_id AND enterprise_authoritative_artif'
        "acts_test_run.source_id = CAST((enterprise_reads_test_run.value ->> 'artifac"
        "t_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterpri"
        'se_sources_test_run \nWHERE authoritative_enterprise_sources_test_run.tenant'
        '_id = t AND authoritative_enterprise_sources_test_run.category_id = c AND CA'
        'ST(authoritative_enterprise_sources_test_run.source_id AS TEXT) = expected->'
        ">'source_id' AND CAST(authoritative_enterprise_sources_test_run.source_revis"
        "ion AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_sou"
        "rces_test_run.content_hash = expected->>'content_hash') AS anon_1 INTO visib"
        'le;\n  ELSE RETURN false; END CASE;\n  IF visible IS DISTINCT FROM true THEN'
        ' RETURN false; END IF;\n END LOOP;\n RETURN true;\nEXCEPTION WHEN invalid_te'
        'xt_representation OR numeric_value_out_of_range THEN RETURN false;\nEND\n;\n'
        '$function$\n'
    ),
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, '
        'table_name text, payload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE'
        " SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS"
        " $function$\nDECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[];"
        ' item jsonb; container jsonb;\n target_kind text; referenced_target uuid; re'
        "ferenced_version integer;\nBEGIN\n IF table_name='agent_runs' THEN RETURN pu"
        'blic.kernel_lifecycle_links(table_name,payload); END IF;\n -- Only actual to'
        'p-level relation columns establish raw UUID edges. Arbitrary\n -- content di'
        'ctionaries are not relational rows, even if an extra key happens\n -- to be '
        "named source_id or item_id.\n keys=CASE table_name\n  WHEN 'artifact_version"
        "s' THEN ARRAY['original_id']\n  WHEN 'claims' THEN ARRAY['artifact_id','snap"
        "shot_id']\n  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition"
        "_id','parent_definition_id',\n   'source_proposal_id','source_submission_id'"
        "]\n  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n  WHEN 'definition"
        "_specs' THEN ARRAY[]::text[]\n  WHEN 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN 'proposal_items' THEN ARRAY[]::tex"
        "t[]\n  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n  WHEN 'proposal_"
        "revisions' THEN ARRAY['proposal_id']\n  WHEN 'proposal_sources' THEN ARRAY['"
        "source_id']\n  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n  WHEN 'pro"
        "posal_decisions' THEN ARRAY['submission_id']\n  WHEN 'project_open_items' TH"
        "EN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n  WHE"
        "N 'category_knowledge_current' THEN ARRAY['current_entry_id']\n  WHEN 'promo"
        "tion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n  WHEN '"
        "evidence_links' THEN ARRAY['evidence_id']\n  WHEN 'claim_withdrawals' THEN A"
        "RRAY['claim_id']\n  WHEN 'manufacturing_baseline_publications' THEN ARRAY['b"
        "aseline_id','process_id','previous_id']\n  WHEN 'manufacturing_publication_c"
        "urrents' THEN ARRAY['version_id']\n  WHEN 'manufacturing_publication_documen"
        "ts' THEN ARRAY['document_id','process_id']\n  WHEN 'native_pilot_runs' THEN "
        "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configurati"
        "on_id','process_id','publication_id']\n  WHEN 'native_pilot_currents' THEN A"
        "RRAY['pilot_id','latest_observation_id']\n  WHEN 'native_pilot_observations'"
        " THEN ARRAY['pilot_id','previous_observation_id']\n  WHEN 'release_packages'"
        " THEN ARRAY['previous_id']\n  WHEN 'release_package_currents' THEN ARRAY['ve"
        "rsion_id']\n  WHEN 'release_decisions' THEN ARRAY['package_id']\n  WHEN 'rel"
        "ease_policy_facts' THEN ARRAY['previous_id']\n  WHEN 'release_policy_current"
        "s' THEN ARRAY['fact_id']\n  WHEN 'external_handoff_authorizations' THEN ARRA"
        "Y['package_id','engineering_decision_id','manufacturing_decision_id']\n  WHE"
        "N 'external_delivery_intents' THEN ARRAY['handoff_id']\n  WHEN 'external_rec"
        "eipts' THEN ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles"
        "_id']\n  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id"
        "','latest_receipt_id']\n  WHEN 'release_exception_decisions' THEN ARRAY['bas"
        "is_package_id','policy_fact_id','previous_id']\n  WHEN 'release_exception_cu"
        "rrents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n  WHE"
        "N 'work_commitment_reviews' THEN ARRAY['commitment_id','task_version_id','su"
        "bmission_id','previous_id']\n  WHEN 'work_commitment_review_currents' THEN A"
        "RRAY['version_id']\n  WHEN 'external_wait_versions' THEN ARRAY['previous_id'"
        "]\n  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n  WHEN 'project"
        "_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n  WHE"
        "N 'project_risk_followup_currents' THEN ARRAY['version_id']\n  WHEN 'work_ta"
        "sk_versions' THEN ARRAY['previous_id']\n  WHEN 'work_task_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id'"
        "]\n  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n  WHEN 'proje"
        "ct_status_updates' THEN ARRAY[]::text[]\n  ELSE ARRAY[]::text[] END;\n FOREA"
        'CH key IN ARRAY keys LOOP\n  IF payload->>key IS NOT NULL THEN links=array_a'
        "ppend(links,(payload->>key)::uuid); END IF;\n END LOOP;\n -- Publication's e"
        'xact saved read set is a validated Artifact relationship.\n -- Do not scan i'
        'ts declaration, body, reason or arbitrary JSON UUID values.\n IF table_name '
        "IN ('manufacturing_baseline_publications','native_pilot_runs','native_pilot_"
        "observations','release_packages','release_decisions','release_policy_facts',"
        "'external_handoff_authorizations','external_receipts','release_exception_dec"
        "isions') THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce"
        "(payload->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id'"
        " IS NOT NULL THEN\n    links=array_append(links,(item->>'artifact_id')::uuid"
        ");\n   END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('native_pilot_runs"
        "','native_pilot_observations') THEN\n  FOR item IN SELECT value FROM jsonb_a"
        "rray_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]"
        "')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item-"
        ">>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_"
        "array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]"
        "')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item-"
        ">>'id')::uuid); END IF;\n  END LOOP;\n  item=payload#>'{material_snapshot,st"
        "atistics,resource,fact}';\n  IF item->>'id' IS NOT NULL THEN links=array_app"
        "end(links,(item->>'id')::uuid); END IF;\n END IF;\n IF table_name='release_p"
        "ackages' THEN\n  -- FixedObject.ref is a closed, server-resolved version ref"
        'erence, not arbitrary body UUID text.\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n   container"
        "=item->'ref';\n   IF container->>'kind'=ANY(ARRAY['definition','engineering_"
        "configuration','process_revision','manufacturing_publication','test_run','pi"
        "lot_run','issue','change','exception','artifact','work_instruction','control"
        "_plan','build_lot','line'])\n    AND container->>'id' IS NOT NULL THEN links"
        "=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n END IF"
        ";\n IF table_name IN ('external_handoff_authorizations','external_delivery_i"
        "ntents') THEN\n  -- Only closed, owner-verified mapping and manifest referen"
        "ces are source edges.\n  container=CASE WHEN table_name='external_handoff_au"
        "thorizations' THEN payload#>'{body,declaration}' ELSE payload->'body' END;\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'ma"
        "ppings','[]')) LOOP\n   IF item->'ref'->>'kind'=ANY(ARRAY['definition','engi"
        "neering_configuration','process_revision','part','bom_revision','artifact','"
        "work_instruction','control_plan'])\n    AND item->'ref'->>'id' IS NOT NULL T"
        "HEN links=array_append(links,(item->'ref'->>'id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container-'
        ">'manifest','[]')) LOOP\n   IF item->'artifact'->>'id' IS NOT NULL THEN link"
        "s=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n  END LOOP;"
        "\n END IF;\n IF table_name='release_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by the policy owner.\n  FOREACH key IN '
        "ARRAY ARRAY['definition','engineering_configuration','manufacturing_configur"
        "ation'] LOOP\n   container=payload#>ARRAY['material','subject_config',key];"
        "\n   IF container->>'id' IS NOT NULL THEN links=array_append(links,(containe"
        "r->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- These stored fields ar"
        'e validated Reference containers. Do not feed the\n -- whole row or arbitrar'
        "y content into the canonical Reference parser.\n IF table_name=ANY(ARRAY['pr"
        "oposals','proposal_item_versions','proposal_submissions',\n  'category_knowl"
        "edge_entries','definition_specs']) THEN\n  FOREACH key IN ARRAY ARRAY['sourc"
        "e_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   "
        'links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n  END LOO'
        'P;\n END IF;\n -- Match ItemInput.content_schema and category_service._refer'
        'ences: only\n -- commercial_target, voice, and competitor have nested source'
        " contracts.\n IF table_name='proposal_item_versions' AND payload->>'kind'='c"
        "ommercial_target' THEN\n  FOREACH key IN ARRAY ARRAY['target_price','cost','"
        "volume'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,payload"
        "->'content'->key->'source');\n  END LOOP;\n ELSIF table_name='category_knowl"
        "edge_entries' AND payload->>'kind'='voice' THEN\n  links=links || public.m3_"
        "lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n ELSI"
        "F table_name='category_knowledge_entries' AND payload->>'kind'='competitor' "
        "THEN\n  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n   F"
        "OR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content"
        "'->key,'[]')) LOOP\n    links=links || public.m3_lifecycle_typed_links(t,c,i"
        "tem->'source_ref');\n   END LOOP;\n  END LOOP;\n END IF;\n IF table_name='pr"
        "oposal_submissions' THEN\n  container=payload->'frozen_document';\n  FOREACH"
        " key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','basel"
        "ine_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c"
        ',container->key);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_'
        "elements(coalesce(container->'items','[]')) LOOP\n   links=links || public.m"
        "3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','"
        "proposal_id']);\n   -- The frozen read projection records actual EvidenceLin"
        'k provenance here.\n   links=links || public.m3_lifecycle_typed_links(t,c,it'
        "em->'evidence_links');\n  END LOOP;\n ELSIF table_name='promotion_proofs' TH"
        "EN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'"
        "source_item_refs','[]')) LOOP\n   IF item->>'item_id' IS NOT NULL THEN links"
        "=array_append(links,(item->>'item_id')::uuid); END IF;\n  END LOOP;\n END IF"
        ';\n -- Exact persisted EvidenceLink targets supplement these immutable versi'
        'ons.\n -- Reverted links and withdrawn Claims still retain the original hist'
        'orical\n -- dependency; lifecycle cleanup must not erase their audit source.'
        "\n IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NUL"
        "L THEN\n  target_kind='proposal_item'; referenced_target=(payload->>'item_id"
        "')::uuid;\n  referenced_version=(payload->>'version')::integer;\n ELSIF tabl"
        "e_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n  t"
        "arget_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n  r"
        "eferenced_version=(payload->>'version')::integer;\n ELSIF table_name='defini"
        "tion_specs' AND payload->>'id' IS NOT NULL THEN\n  target_kind='definition_s"
        "pec'; referenced_target=(payload->>'id')::uuid;\n  SELECT revision INTO refe"
        'renced_version FROM public.definition_revisions\n   WHERE tenant_id=t AND ca'
        "tegory_id=c AND id=(payload->>'definition_id')::uuid;\n END IF;\n IF referen"
        'ced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n  SELECT coa'
        "lesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_link"
        's link\n   WHERE link.tenant_id=t AND link.category_id=c AND link.target_typ'
        'e=target_kind\n    AND link.target_id=referenced_target AND link.target_vers'
        'ion=referenced_version;\n  links=links || extra;\n END IF;\n -- Child source'
        ' rows point to their parent, whereas dependency traversal needs\n -- the par'
        "ent's fixed source children as well. Keep the actual relational edge.\n IF t"
        "able_name='definition_revisions' THEN\n  SELECT coalesce(array_agg(id),'{}')"
        ' INTO extra FROM (\n   SELECT id FROM public.definition_sources WHERE tenant'
        "_id=t AND category_id=c\n    AND definition_id=(payload->>'id')::uuid\n   UN"
        'ION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND categor'
        "y_id=c\n    AND definition_id=(payload->>'id')::uuid\n  ) children;\n  links"
        "=links || extra;\n ELSIF table_name='proposals' THEN\n  SELECT coalesce(arra"
        "y_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE tena"
        "nt_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n  links=l"
        "inks || extra;\n ELSIF table_name='proposal_items' THEN\n  SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE t"
        "enant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n  links=li"
        "nks || extra;\n ELSIF table_name='product_target_segments' THEN\n  SELECT co"
        "alesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries"
        "\n   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_"
        "lineage_id')::uuid\n    AND version=(payload->>'segment_version')::integer;"
        "\n  links=links || extra;\n ELSIF table_name='parameter_current' THEN\n  SEL"
        "ECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
        "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'paramete"
        "r_id')::uuid\n    AND version=(payload->>'current_version')::integer;\n  lin"
        "ks=links || extra;\n END IF;\n\n IF table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_updates') THEN\n  FOR item IN SELECT "
        "value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF"
        " item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'art"
        "ifact_id')::uuid); END IF;\n  END LOOP;\n  IF table_name='work_task_versions"
        "' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n   links=array_appen"
        "d(links,(payload#>>'{body,plan_task,id}')::uuid);\n  END IF;\n  IF table_nam"
        "e='work_commitment_versions' THEN\n   SELECT coalesce(array_agg(id),'{}') IN"
        'TO extra FROM public.work_task_versions\n    WHERE tenant_id=t AND category_'
        "id=c AND task_id=(payload->>'task_id')::uuid AND revision=(payload->>'task_r"
        "evision')::integer;\n   links=links||extra;\n  ELSIF table_name='project_sta"
        "tus_updates' THEN\n   FOR item IN SELECT value FROM jsonb_array_elements(coa"
        "lesce(payload->'task_refs','[]')) LOOP\n    SELECT coalesce(array_agg(id),'{"
        "}') INTO extra FROM public.work_task_versions\n     WHERE tenant_id=t AND ca"
        "tegory_id=c AND task_id=(item->>'id')::uuid AND revision=(item->>'revision')"
        '::integer;\n    links=links||extra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' THEN\n  FOR item IN SELECT value FROM"
        " jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')"
        "::uuid); END IF;\n  END LOOP;\n END IF;\n\n IF table_name='external_wait_ver"
        "sions' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p"
        "ayload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NUL"
        "L THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n   contai"
        "ner=payload#>ARRAY['body',key];\n   IF container->>'id' IS NOT NULL THEN lin"
        "ks=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n  con"
        "tainer=payload#>'{body,replaces}';\n  IF container->>'id' IS NOT NULL THEN\n"
        "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_"
        "versions\n    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'"
        "id')::uuid AND revision=(container->>'revision')::integer;\n   links=links||"
        "extra;\n  END IF;\n END IF;\n IF table_name='project_risk_followups' THEN\n "
        " FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{sour"
        "ce_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=a"
        "rray_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n I"
        "F table_name IN ('knowledge_candidate_versions','knowledge_candidate_current"
        "s','knowledge_applicability_assessments','knowledge_rule_versions','knowledg"
        "e_rule_currents') THEN\n  FOREACH key IN ARRAY ARRAY['previous_id','version_"
        "id','candidate_version_id','assessment_id','publication_id'] LOOP\n   IF pay"
        'load->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid);'
        ' END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' "
        "IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  E"
        'ND LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  FO"
        "R item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL T"
        "HEN links=array_append(links,(item->>'receipt_id')::uuid); END IF;\n   IF it"
        "em->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n"
        "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::u"
        "uid); END IF;\n  END LOOP;\n  IF payload#>>'{source_basis,target,id}' IS NOT"
        " NULL THEN links=array_append(links,(payload#>>'{source_basis,target,id}')::"
        "uuid); END IF;\n END IF;\n\n IF table_name IN ('field_feedback_versions','fi"
        "eld_feedback_currents','field_response_records') THEN\n  FOREACH key IN ARRA"
        "Y ARRAY['previous_id','version_id','feedback_version_id'] LOOP\n   IF payloa"
        'd->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); EN'
        'D IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coa'
        "lesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS "
        "NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END "
        "LOOP;\n  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturi"
        "ng_configuration','batch'] LOOP\n   IF payload#>>ARRAY['body','location',key"
        ",'id'] IS NOT NULL THEN links=array_append(links,(payload#>>ARRAY['body','lo"
        "cation',key,'id'])::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value "
        "FROM jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}'"
        ",'[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links=array_append("
        "links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT NU"
        "LL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LO"
        "OP;\n END IF;\n IF table_name IN ('change_request_versions','change_graph_ca"
        "ptures') THEN\n  FOR container IN SELECT value FROM jsonb_each(coalesce(payl"
        "oad#>'{source_basis,owners}','{}')) LOOP\n   IF container->>'feedback_versio"
        "n_id' IS NOT NULL THEN links=array_append(links,(container->>'feedback_versi"
        "on_id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n -- Closed native Field pl"
        "an and occurrence references, never arbitrary UUID prose.\n IF table_name='c"
        "ontrolled_change_selection_facts' AND payload->>'basis_kind'='field_intent' "
        "THEN\n  IF payload->>'feedback_version_id' IS NOT NULL THEN\n   links=array_"
        "append(links,(payload->>'feedback_version_id')::uuid);\n  END IF;\n END IF;"
        "\n IF table_name='change_implementation_captures'\n  AND payload#>>'{occurre"
        "nce_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v"
        "1' THEN\n  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] "
        "LOOP\n   IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n   "
        " links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid"
        ");\n   END IF;\n  END LOOP;\n END IF;\n\n IF table_name='change_completion_r"
        "ecords' THEN\n  FOREACH key IN ARRAY ARRAY['project_id','change_version_id',"
        "'order_record_id','shared_proof_id'] LOOP\n   IF payload->>key IS NOT NULL T"
        'HEN links=array_append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n '
        " FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'requi"
        "red_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOO"
        "P;\n  IF payload#>>'{native_input,lot,id}' IS NOT NULL THEN links=array_appe"
        "nd(links,(payload#>>'{native_input,lot,id}')::uuid); END IF;\n  FOR item IN "
        "SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_append(links,(item->>'id')::uuid);\n  "
        'END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(pay'
        "load#>'{native_input,mappings}','[]')) LOOP\n   SELECT coalesce(array_agg(id"
        "),'{}') INTO extra FROM verification_run_versions\n    WHERE tenant_id=t AND"
        " category_id=c AND run_id=(item#>>'{run,id}')::uuid AND revision=(item#>>'{r"
        "un,revision}')::integer;\n   links=links||extra; links=array_append(links,(i"
        "tem->>'sample_id')::uuid);\n  END LOOP;\n END IF;\n\n -- Closed native owner"
        ' DTOs: retain exact outputs and native execution/report rows.\n IF table_nam'
        "e='change_completion_records' THEN\n  FOR item IN SELECT value FROM jsonb_ar"
        "ray_elements(coalesce(payload#>'{fact_snapshot,output_refs}','[]')) LOOP\n  "
        " IF item->>'kind'='test_run' THEN\n    SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM verification_run_versions\n     WHERE tenant_id=t AND categor'
        "y_id=c AND run_id=(item->>'id')::uuid AND revision=(item->>'revision')::inte"
        "ger;\n    links=links||extra;\n   ELSIF item->>'kind'=ANY(ARRAY['engineering"
        "_configuration','manufacturing_configuration','build','sample']) THEN\n    l"
        "inks=array_append(links,(item->>'id')::uuid);\n   END IF;\n  END LOOP;\n  IF"
        " payload#>>'{owner_basis,schema_version}'='pdos-native-build-adoption-read-v"
        "1' THEN\n   FOREACH key IN ARRAY ARRAY['previous_build','successor_build','a"
        "ctual_configuration','lot','start'] LOOP\n    IF payload#>>ARRAY['owner_basi"
        "s',key,'id'] IS NOT NULL THEN\n     links=array_append(links,(payload#>>ARRA"
        "Y['owner_basis',key,'id'])::uuid);\n    END IF;\n   END LOOP;\n  ELSIF paylo"
        "ad#>>'{owner_basis,schema_version}'='pdos-native-change-run-verification-v1'"
        " THEN\n   FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREACH key IN ARRAY ARRAY['run_version_"
        "id','request_version_id','projection_id'] LOOP\n     IF container->>key IS N"
        'OT NULL THEN links=array_append(links,(container->>key)::uuid); END IF;\n   '
        ' END LOOP;\n   END LOOP;\n  END IF;\n END IF;\n\n -- F: only server-verified'
        ' fixed answer proofs establish these dependency edges.\n -- Native deferred '
        "atoms bind these exact arrays to real source ledgers.\n IF table_name IN ('c"
        "ategory_knowledge_entries','knowledge_candidate_versions','knowledge_rule_ve"
        "rsions','knowledge_answer_reviews','knowledge_gap_submissions') THEN\n  cont"
        "ainer=CASE table_name WHEN 'category_knowledge_entries' THEN payload->'answe"
        "r_sources'\n   WHEN 'knowledge_candidate_versions' THEN payload#>'{source_ba"
        "sis,answer_sources}'\n   WHEN 'knowledge_rule_versions' THEN payload#>'{sour"
        "ce_basis,answer_sources}'\n   ELSE payload->'source_proof' END;\n  links=lin"
        "ks||public.assistant_source_lifecycle_links(t,c,coalesce(container,'[]'::jso"
        'nb));\n END IF;\n\n -- G private outbound body copies have no category colum'
        'n. Only the fixed\n -- server footprint subset for this REAL category establ'
        "ishes retention edges.\n IF table_name='dingtalk_deliveries' THEN\n  IF payl"
        "oad->>'tenant_id' IS DISTINCT FROM t::text OR c IS NULL THEN\n   RAISE EXCEP"
        "TION 'Delivery retention scope mismatch' USING ERRCODE='23514'; END IF;\n  S"
        "ELECT coalesce(jsonb_agg(value),'[]'::jsonb) INTO container\n   FROM jsonb_a"
        "rray_elements(coalesce(payload->'source_dependencies','[]'::jsonb))\n   WHER"
        "E value->>'category_id'=c::text;\n  links=links||public.assistant_source_lif"
        'ecycle_links(t,c,container);\n END IF;\n RETURN links;\nEND;\n$function$\n'
    ),
}

NATIVE_FUNCTIONS = {
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
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, '
        'table_name text, payload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE'
        " SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS"
        " $function$\nDECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[];"
        ' item jsonb; container jsonb;\n target_kind text; referenced_target uuid; re'
        "ferenced_version integer;\nBEGIN\n IF table_name='agent_runs' THEN RETURN pu"
        'blic.kernel_lifecycle_links(table_name,payload); END IF;\n -- Only actual to'
        'p-level relation columns establish raw UUID edges. Arbitrary\n -- content di'
        'ctionaries are not relational rows, even if an extra key happens\n -- to be '
        "named source_id or item_id.\n keys=CASE table_name\n  WHEN 'artifact_version"
        "s' THEN ARRAY['original_id']\n  WHEN 'claims' THEN ARRAY['artifact_id','snap"
        "shot_id']\n  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition"
        "_id','parent_definition_id',\n   'source_proposal_id','source_submission_id'"
        "]\n  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n  WHEN 'definition"
        "_specs' THEN ARRAY[]::text[]\n  WHEN 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN 'proposal_items' THEN ARRAY[]::tex"
        "t[]\n  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n  WHEN 'proposal_"
        "revisions' THEN ARRAY['proposal_id']\n  WHEN 'proposal_sources' THEN ARRAY['"
        "source_id']\n  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n  WHEN 'pro"
        "posal_decisions' THEN ARRAY['submission_id']\n  WHEN 'project_open_items' TH"
        "EN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n  WHE"
        "N 'category_knowledge_current' THEN ARRAY['current_entry_id']\n  WHEN 'promo"
        "tion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n  WHEN '"
        "evidence_links' THEN ARRAY['evidence_id']\n  WHEN 'claim_withdrawals' THEN A"
        "RRAY['claim_id']\n  WHEN 'manufacturing_baseline_publications' THEN ARRAY['b"
        "aseline_id','process_id','previous_id']\n  WHEN 'manufacturing_publication_c"
        "urrents' THEN ARRAY['version_id']\n  WHEN 'manufacturing_publication_documen"
        "ts' THEN ARRAY['document_id','process_id']\n  WHEN 'native_pilot_runs' THEN "
        "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configurati"
        "on_id','process_id','publication_id']\n  WHEN 'native_pilot_currents' THEN A"
        "RRAY['pilot_id','latest_observation_id']\n  WHEN 'native_pilot_observations'"
        " THEN ARRAY['pilot_id','previous_observation_id']\n  WHEN 'release_packages'"
        " THEN ARRAY['previous_id']\n  WHEN 'release_package_currents' THEN ARRAY['ve"
        "rsion_id']\n  WHEN 'release_decisions' THEN ARRAY['package_id']\n  WHEN 'rel"
        "ease_policy_facts' THEN ARRAY['previous_id']\n  WHEN 'release_policy_current"
        "s' THEN ARRAY['fact_id']\n  WHEN 'external_handoff_authorizations' THEN ARRA"
        "Y['package_id','engineering_decision_id','manufacturing_decision_id']\n  WHE"
        "N 'external_delivery_intents' THEN ARRAY['handoff_id']\n  WHEN 'external_rec"
        "eipts' THEN ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles"
        "_id']\n  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id"
        "','latest_receipt_id']\n  WHEN 'release_exception_decisions' THEN ARRAY['bas"
        "is_package_id','policy_fact_id','previous_id']\n  WHEN 'release_exception_cu"
        "rrents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n  WHE"
        "N 'work_commitment_reviews' THEN ARRAY['commitment_id','task_version_id','su"
        "bmission_id','previous_id']\n  WHEN 'work_commitment_review_currents' THEN A"
        "RRAY['version_id']\n  WHEN 'external_wait_versions' THEN ARRAY['previous_id'"
        "]\n  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n  WHEN 'project"
        "_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n  WHE"
        "N 'project_risk_followup_currents' THEN ARRAY['version_id']\n  WHEN 'work_ta"
        "sk_versions' THEN ARRAY['previous_id']\n  WHEN 'work_task_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id'"
        "]\n  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n  WHEN 'proje"
        "ct_status_updates' THEN ARRAY[]::text[]\n  ELSE ARRAY[]::text[] END;\n FOREA"
        'CH key IN ARRAY keys LOOP\n  IF payload->>key IS NOT NULL THEN links=array_a'
        "ppend(links,(payload->>key)::uuid); END IF;\n END LOOP;\n -- Publication's e"
        'xact saved read set is a validated Artifact relationship.\n -- Do not scan i'
        'ts declaration, body, reason or arbitrary JSON UUID values.\n IF table_name '
        "IN ('manufacturing_baseline_publications','native_pilot_runs','native_pilot_"
        "observations','release_packages','release_decisions','release_policy_facts',"
        "'external_handoff_authorizations','external_receipts','release_exception_dec"
        "isions') THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce"
        "(payload->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id'"
        " IS NOT NULL THEN\n    links=array_append(links,(item->>'artifact_id')::uuid"
        ");\n   END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('native_pilot_runs"
        "','native_pilot_observations') THEN\n  FOR item IN SELECT value FROM jsonb_a"
        "rray_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]"
        "')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item-"
        ">>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_"
        "array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]"
        "')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item-"
        ">>'id')::uuid); END IF;\n  END LOOP;\n  item=payload#>'{material_snapshot,st"
        "atistics,resource,fact}';\n  IF item->>'id' IS NOT NULL THEN links=array_app"
        "end(links,(item->>'id')::uuid); END IF;\n END IF;\n IF table_name='release_p"
        "ackages' THEN\n  -- FixedObject.ref is a closed, server-resolved version ref"
        'erence, not arbitrary body UUID text.\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n   container"
        "=item->'ref';\n   IF container->>'kind'=ANY(ARRAY['definition','engineering_"
        "configuration','process_revision','manufacturing_publication','test_run','pi"
        "lot_run','issue','change','exception','artifact','work_instruction','control"
        "_plan','build_lot','line'])\n    AND container->>'id' IS NOT NULL THEN links"
        "=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n END IF"
        ";\n IF table_name IN ('external_handoff_authorizations','external_delivery_i"
        "ntents') THEN\n  -- Only closed, owner-verified mapping and manifest referen"
        "ces are source edges.\n  container=CASE WHEN table_name='external_handoff_au"
        "thorizations' THEN payload#>'{body,declaration}' ELSE payload->'body' END;\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'ma"
        "ppings','[]')) LOOP\n   IF item->'ref'->>'kind'=ANY(ARRAY['definition','engi"
        "neering_configuration','process_revision','part','bom_revision','artifact','"
        "work_instruction','control_plan'])\n    AND item->'ref'->>'id' IS NOT NULL T"
        "HEN links=array_append(links,(item->'ref'->>'id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container-'
        ">'manifest','[]')) LOOP\n   IF item->'artifact'->>'id' IS NOT NULL THEN link"
        "s=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n  END LOOP;"
        "\n END IF;\n IF table_name='release_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by the policy owner.\n  FOREACH key IN '
        "ARRAY ARRAY['definition','engineering_configuration','manufacturing_configur"
        "ation'] LOOP\n   container=payload#>ARRAY['material','subject_config',key];"
        "\n   IF container->>'id' IS NOT NULL THEN links=array_append(links,(containe"
        "r->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- These stored fields ar"
        'e validated Reference containers. Do not feed the\n -- whole row or arbitrar'
        "y content into the canonical Reference parser.\n IF table_name=ANY(ARRAY['pr"
        "oposals','proposal_item_versions','proposal_submissions',\n  'category_knowl"
        "edge_entries','definition_specs']) THEN\n  FOREACH key IN ARRAY ARRAY['sourc"
        "e_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   "
        'links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n  END LOO'
        'P;\n END IF;\n -- Match ItemInput.content_schema and category_service._refer'
        'ences: only\n -- commercial_target, voice, and competitor have nested source'
        " contracts.\n IF table_name='proposal_item_versions' AND payload->>'kind'='c"
        "ommercial_target' THEN\n  FOREACH key IN ARRAY ARRAY['target_price','cost','"
        "volume'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,payload"
        "->'content'->key->'source');\n  END LOOP;\n ELSIF table_name='category_knowl"
        "edge_entries' AND payload->>'kind'='voice' THEN\n  links=links || public.m3_"
        "lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n ELSI"
        "F table_name='category_knowledge_entries' AND payload->>'kind'='competitor' "
        "THEN\n  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n   F"
        "OR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content"
        "'->key,'[]')) LOOP\n    links=links || public.m3_lifecycle_typed_links(t,c,i"
        "tem->'source_ref');\n   END LOOP;\n  END LOOP;\n END IF;\n IF table_name='pr"
        "oposal_submissions' THEN\n  container=payload->'frozen_document';\n  FOREACH"
        " key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','basel"
        "ine_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c"
        ',container->key);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_'
        "elements(coalesce(container->'items','[]')) LOOP\n   links=links || public.m"
        "3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','"
        "proposal_id']);\n   -- The frozen read projection records actual EvidenceLin"
        'k provenance here.\n   links=links || public.m3_lifecycle_typed_links(t,c,it'
        "em->'evidence_links');\n  END LOOP;\n ELSIF table_name='promotion_proofs' TH"
        "EN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'"
        "source_item_refs','[]')) LOOP\n   IF item->>'item_id' IS NOT NULL THEN links"
        "=array_append(links,(item->>'item_id')::uuid); END IF;\n  END LOOP;\n END IF"
        ';\n -- Exact persisted EvidenceLink targets supplement these immutable versi'
        'ons.\n -- Reverted links and withdrawn Claims still retain the original hist'
        'orical\n -- dependency; lifecycle cleanup must not erase their audit source.'
        "\n IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NUL"
        "L THEN\n  target_kind='proposal_item'; referenced_target=(payload->>'item_id"
        "')::uuid;\n  referenced_version=(payload->>'version')::integer;\n ELSIF tabl"
        "e_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n  t"
        "arget_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n  r"
        "eferenced_version=(payload->>'version')::integer;\n ELSIF table_name='defini"
        "tion_specs' AND payload->>'id' IS NOT NULL THEN\n  target_kind='definition_s"
        "pec'; referenced_target=(payload->>'id')::uuid;\n  SELECT revision INTO refe"
        'renced_version FROM public.definition_revisions\n   WHERE tenant_id=t AND ca'
        "tegory_id=c AND id=(payload->>'definition_id')::uuid;\n END IF;\n IF referen"
        'ced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n  SELECT coa'
        "lesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_link"
        's link\n   WHERE link.tenant_id=t AND link.category_id=c AND link.target_typ'
        'e=target_kind\n    AND link.target_id=referenced_target AND link.target_vers'
        'ion=referenced_version;\n  links=links || extra;\n END IF;\n -- Child source'
        ' rows point to their parent, whereas dependency traversal needs\n -- the par'
        "ent's fixed source children as well. Keep the actual relational edge.\n IF t"
        "able_name='definition_revisions' THEN\n  SELECT coalesce(array_agg(id),'{}')"
        ' INTO extra FROM (\n   SELECT id FROM public.definition_sources WHERE tenant'
        "_id=t AND category_id=c\n    AND definition_id=(payload->>'id')::uuid\n   UN"
        'ION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND categor'
        "y_id=c\n    AND definition_id=(payload->>'id')::uuid\n  ) children;\n  links"
        "=links || extra;\n ELSIF table_name='proposals' THEN\n  SELECT coalesce(arra"
        "y_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE tena"
        "nt_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n  links=l"
        "inks || extra;\n ELSIF table_name='proposal_items' THEN\n  SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE t"
        "enant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n  links=li"
        "nks || extra;\n ELSIF table_name='product_target_segments' THEN\n  SELECT co"
        "alesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries"
        "\n   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_"
        "lineage_id')::uuid\n    AND version=(payload->>'segment_version')::integer;"
        "\n  links=links || extra;\n ELSIF table_name='parameter_current' THEN\n  SEL"
        "ECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
        "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'paramete"
        "r_id')::uuid\n    AND version=(payload->>'current_version')::integer;\n  lin"
        "ks=links || extra;\n END IF;\n\n IF table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_updates') THEN\n  FOR item IN SELECT "
        "value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF"
        " item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'art"
        "ifact_id')::uuid); END IF;\n  END LOOP;\n  IF table_name='work_task_versions"
        "' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n   links=array_appen"
        "d(links,(payload#>>'{body,plan_task,id}')::uuid);\n  END IF;\n  IF table_nam"
        "e='work_commitment_versions' THEN\n   SELECT coalesce(array_agg(id),'{}') IN"
        'TO extra FROM public.work_task_versions\n    WHERE tenant_id=t AND category_'
        "id=c AND task_id=(payload->>'task_id')::uuid AND revision=(payload->>'task_r"
        "evision')::integer;\n   links=links||extra;\n  ELSIF table_name='project_sta"
        "tus_updates' THEN\n   FOR item IN SELECT value FROM jsonb_array_elements(coa"
        "lesce(payload->'task_refs','[]')) LOOP\n    SELECT coalesce(array_agg(id),'{"
        "}') INTO extra FROM public.work_task_versions\n     WHERE tenant_id=t AND ca"
        "tegory_id=c AND task_id=(item->>'id')::uuid AND revision=(item->>'revision')"
        '::integer;\n    links=links||extra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' THEN\n  FOR item IN SELECT value FROM"
        " jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')"
        "::uuid); END IF;\n  END LOOP;\n END IF;\n\n IF table_name='external_wait_ver"
        "sions' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p"
        "ayload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NUL"
        "L THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n   contai"
        "ner=payload#>ARRAY['body',key];\n   IF container->>'id' IS NOT NULL THEN lin"
        "ks=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n  con"
        "tainer=payload#>'{body,replaces}';\n  IF container->>'id' IS NOT NULL THEN\n"
        "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_"
        "versions\n    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'"
        "id')::uuid AND revision=(container->>'revision')::integer;\n   links=links||"
        "extra;\n  END IF;\n END IF;\n IF table_name='project_risk_followups' THEN\n "
        " FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{sour"
        "ce_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=a"
        "rray_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n I"
        "F table_name IN ('knowledge_candidate_versions','knowledge_candidate_current"
        "s','knowledge_applicability_assessments','knowledge_rule_versions','knowledg"
        "e_rule_currents') THEN\n  FOREACH key IN ARRAY ARRAY['previous_id','version_"
        "id','candidate_version_id','assessment_id','publication_id'] LOOP\n   IF pay"
        'load->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid);'
        ' END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' "
        "IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  E"
        'ND LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  FO"
        "R item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL T"
        "HEN links=array_append(links,(item->>'receipt_id')::uuid); END IF;\n   IF it"
        "em->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n"
        "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::u"
        "uid); END IF;\n  END LOOP;\n  IF payload#>>'{source_basis,target,id}' IS NOT"
        " NULL THEN links=array_append(links,(payload#>>'{source_basis,target,id}')::"
        "uuid); END IF;\n END IF;\n\n IF table_name IN ('field_feedback_versions','fi"
        "eld_feedback_currents','field_response_records') THEN\n  FOREACH key IN ARRA"
        "Y ARRAY['previous_id','version_id','feedback_version_id'] LOOP\n   IF payloa"
        'd->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); EN'
        'D IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coa'
        "lesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS "
        "NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END "
        "LOOP;\n  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturi"
        "ng_configuration','batch'] LOOP\n   IF payload#>>ARRAY['body','location',key"
        ",'id'] IS NOT NULL THEN links=array_append(links,(payload#>>ARRAY['body','lo"
        "cation',key,'id'])::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value "
        "FROM jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}'"
        ",'[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links=array_append("
        "links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT NU"
        "LL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LO"
        "OP;\n END IF;\n IF table_name IN ('change_request_versions','change_graph_ca"
        "ptures') THEN\n  FOR container IN SELECT value FROM jsonb_each(coalesce(payl"
        "oad#>'{source_basis,owners}','{}')) LOOP\n   IF container->>'feedback_versio"
        "n_id' IS NOT NULL THEN links=array_append(links,(container->>'feedback_versi"
        "on_id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n -- Closed native Field pl"
        "an and occurrence references, never arbitrary UUID prose.\n IF table_name='c"
        "ontrolled_change_selection_facts' AND payload->>'basis_kind'='field_intent' "
        "THEN\n  IF payload->>'feedback_version_id' IS NOT NULL THEN\n   links=array_"
        "append(links,(payload->>'feedback_version_id')::uuid);\n  END IF;\n END IF;"
        "\n IF table_name='change_implementation_captures'\n  AND payload#>>'{occurre"
        "nce_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v"
        "1' THEN\n  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] "
        "LOOP\n   IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n   "
        " links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid"
        ");\n   END IF;\n  END LOOP;\n END IF;\n\n IF table_name='change_completion_r"
        "ecords' THEN\n  FOREACH key IN ARRAY ARRAY['project_id','change_version_id',"
        "'order_record_id','shared_proof_id'] LOOP\n   IF payload->>key IS NOT NULL T"
        'HEN links=array_append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n '
        " FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'requi"
        "red_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOO"
        "P;\n  IF payload#>>'{native_input,lot,id}' IS NOT NULL THEN links=array_appe"
        "nd(links,(payload#>>'{native_input,lot,id}')::uuid); END IF;\n  FOR item IN "
        "SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_append(links,(item->>'id')::uuid);\n  "
        'END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(pay'
        "load#>'{native_input,mappings}','[]')) LOOP\n   SELECT coalesce(array_agg(id"
        "),'{}') INTO extra FROM verification_run_versions\n    WHERE tenant_id=t AND"
        " category_id=c AND run_id=(item#>>'{run,id}')::uuid AND revision=(item#>>'{r"
        "un,revision}')::integer;\n   links=links||extra; links=array_append(links,(i"
        "tem->>'sample_id')::uuid);\n  END LOOP;\n END IF;\n\n -- Closed native owner"
        ' DTOs: retain exact outputs and native execution/report rows.\n IF table_nam'
        "e='change_completion_records' THEN\n  FOR item IN SELECT value FROM jsonb_ar"
        "ray_elements(coalesce(payload#>'{fact_snapshot,output_refs}','[]')) LOOP\n  "
        " IF item->>'kind'='test_run' THEN\n    SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM verification_run_versions\n     WHERE tenant_id=t AND categor'
        "y_id=c AND run_id=(item->>'id')::uuid AND revision=(item->>'revision')::inte"
        "ger;\n    links=links||extra;\n   ELSIF item->>'kind'=ANY(ARRAY['engineering"
        "_configuration','manufacturing_configuration','build','sample']) THEN\n    l"
        "inks=array_append(links,(item->>'id')::uuid);\n   END IF;\n  END LOOP;\n  IF"
        " payload#>>'{owner_basis,schema_version}'='pdos-native-build-adoption-read-v"
        "1' THEN\n   FOREACH key IN ARRAY ARRAY['previous_build','successor_build','a"
        "ctual_configuration','lot','start'] LOOP\n    IF payload#>>ARRAY['owner_basi"
        "s',key,'id'] IS NOT NULL THEN\n     links=array_append(links,(payload#>>ARRA"
        "Y['owner_basis',key,'id'])::uuid);\n    END IF;\n   END LOOP;\n  ELSIF paylo"
        "ad#>>'{owner_basis,schema_version}'='pdos-native-change-run-verification-v1'"
        " THEN\n   FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREACH key IN ARRAY ARRAY['run_version_"
        "id','request_version_id','projection_id'] LOOP\n     IF container->>key IS N"
        'OT NULL THEN links=array_append(links,(container->>key)::uuid); END IF;\n   '
        ' END LOOP;\n   END LOOP;\n  END IF;\n END IF;\n\n -- F: only server-verified'
        ' fixed answer proofs establish these dependency edges.\n -- Native deferred '
        "atoms bind these exact arrays to real source ledgers.\n IF table_name IN ('c"
        "ategory_knowledge_entries','knowledge_candidate_versions','knowledge_rule_ve"
        "rsions','knowledge_answer_reviews','knowledge_gap_submissions') THEN\n  cont"
        "ainer=CASE table_name WHEN 'category_knowledge_entries' THEN payload->'answe"
        "r_sources'\n   WHEN 'knowledge_candidate_versions' THEN payload#>'{source_ba"
        "sis,answer_sources}'\n   WHEN 'knowledge_rule_versions' THEN payload#>'{sour"
        "ce_basis,answer_sources}'\n   ELSE payload->'source_proof' END;\n  -- Only t"
        'hese native knowledge rows have an optional answer-derived proof.\n  -- to_j'
        'sonb(row) represents an SQL NULL column as a JSON null member.\n  IF table_n'
        "ame IN ('category_knowledge_entries','knowledge_candidate_versions','knowled"
        "ge_rule_versions') THEN\n   container=coalesce(nullif(container,'null'::json"
        "b),'[]'::jsonb);\n  END IF;\n  -- Review/Gap proof remains required and reac"
        'hes the strict resolver unchanged.\n  links=links||public.assistant_source_l'
        'ifecycle_links(t,c,container);\n END IF;\n\n -- G private outbound body copi'
        'es have no category column. Only the fixed\n -- server footprint subset for '
        "this REAL category establishes retention edges.\n IF table_name='dingtalk_de"
        "liveries' THEN\n  IF payload->>'tenant_id' IS DISTINCT FROM t::text OR c IS "
        "NULL THEN\n   RAISE EXCEPTION 'Delivery retention scope mismatch' USING ERRC"
        "ODE='23514'; END IF;\n  SELECT coalesce(jsonb_agg(value),'[]'::jsonb) INTO c"
        "ontainer\n   FROM jsonb_array_elements(coalesce(payload->'source_dependencie"
        "s','[]'::jsonb))\n   WHERE value->>'category_id'=c::text;\n  links=links||pu"
        'blic.assistant_source_lifecycle_links(t,c,container);\n END IF;\n RETURN lin'
        'ks;\nEND;\n$function$\n'
    ),
}

SCHEMA_SQL = tuple(NATIVE_FUNCTIONS.values())
DOWNGRADE_SQL = tuple(PREVIOUS_FUNCTIONS.values())
EMPTY_HISTORY_SQL = (
    (
        'LOCK TABLE public.category_knowledge_entries,public.knowledge_candidate_vers'
        'ions,public.knowledge_rule_versions,public.knowledge_answer_reviews,public.k'
        'nowledge_gap_submissions IN SHARE ROW EXCLUSIVE MODE'
    ),
    (
        'DO $field_knowledge_history$ BEGIN IF EXISTS(SELECT 1 FROM public.category_k'
        "nowledge_entries WHERE jsonb_path_exists(coalesce(answer_sources,'[]'::jsonb"
        '),\'$[*] ? (@.source_type == "field_feedback")\') UNION ALL SELECT 1 FROM pu'
        'blic.knowledge_candidate_versions WHERE jsonb_path_exists(coalesce(source_ba'
        'sis->\'answer_sources\',\'[]\'::jsonb),\'$[*] ? (@.source_type == "field_fee'
        'dback")\') UNION ALL SELECT 1 FROM public.knowledge_rule_versions WHERE json'
        "b_path_exists(coalesce(source_basis->'answer_sources','[]'::jsonb),'$[*] ? ("
        '@.source_type == "field_feedback")\') UNION ALL SELECT 1 FROM public.knowled'
        "ge_answer_reviews WHERE jsonb_path_exists(coalesce(source_proof,'[]'::jsonb)"
        ',\'$[*] ? (@.source_type == "field_feedback")\') UNION ALL SELECT 1 FROM pub'
        'lic.knowledge_gap_submissions WHERE jsonb_path_exists(coalesce(source_proof,'
        '\'[]\'::jsonb),\'$[*] ? (@.source_type == "field_feedback")\')) THEN RAISE E'
        "XCEPTION 'Field feedback knowledge history cannot lose native visibility' US"
        "ING ERRCODE='23514'; END IF; END $field_knowledge_history$"
    ),
)
