"""Frozen reviewed answers, explicit shared gaps and exact lifecycle source edges."""

SCHEMA_SQL = (
    (
        'ALTER TABLE public.category_knowledge_entries ADD COLUMN answer_sources jsonb;\n\nALTE'
        'R TABLE public.category_knowledge_entries ADD CONSTRAINT knowledge_answer_proof_shape '
        "CHECK (answer_sources IS NULL OR jsonb_typeof(answer_sources)='array');\n\nALTER TABLE"
        ' public.category_knowledge_entries ADD CONSTRAINT verified_answer_has_proof CHECK (kin'
        "d<>'verified_answer' OR answer_sources IS NOT NULL);\n\nDO $$ DECLARE item record; BEG"
        "IN\n FOR item IN SELECT conname FROM pg_constraint WHERE conrelid='public.category_kno"
        "wledge_entries'::regclass\n AND contype='c' AND pg_get_constraintdef(oid) LIKE '%resea"
        "rch_question%' LOOP\n EXECUTE format('ALTER TABLE public.category_knowledge_entries DR"
        "OP CONSTRAINT %I',item.conname); END LOOP;\n END $$;\n\nALTER TABLE public.category_kn"
        "owledge_entries ADD CONSTRAINT category_knowledge_kind CHECK (kind IN ('boundary','seg"
        "ment','competitor','voice','regulation','research_question','verified_answer'));\n\nDO"
        ' $$ DECLARE item record; BEGIN\n FOR item IN SELECT conname FROM pg_constraint WHERE c'
        "onrelid='public.knowledge_candidate_versions'::regclass\n AND contype='c' AND pg_get_c"
        "onstraintdef(oid) LIKE '%jsonb_typeof(command)%'\n AND pg_get_constraintdef(oid) LIKE "
        "'%jsonb_array_length%' LOOP\n EXECUTE format('ALTER TABLE public.knowledge_candidate_v"
        "ersions DROP CONSTRAINT %I',item.conname); END LOOP;\n END $$;\n\nALTER TABLE public.k"
        'nowledge_candidate_versions ADD CONSTRAINT knowledge_source_body_shape CHECK (jsonb_ty'
        "peof(command)='object' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_basis)="
        "'object' AND jsonb_typeof(sources)='array' AND jsonb_typeof(reads)='array' AND ((jsonb"
        "_array_length(sources)>0 AND jsonb_array_length(reads)>0) OR (operation='knowledge.can"
        "didate.create' AND (coalesce(jsonb_typeof(command->'envelope'->'payload'->'answer_orig"
        "in')='object',false) OR coalesce(jsonb_typeof(command->'envelope'->'payload'->'candida"
        "te')='object',false)))));\n\nDO $$ DECLARE item record; BEGIN\n FOR item IN SELECT con"
        "name FROM pg_constraint WHERE conrelid='public.knowledge_rule_versions'::regclass\n AN"
        "D contype='c' AND pg_get_constraintdef(oid) LIKE '%jsonb_typeof(command)%'\n AND pg_ge"
        "t_constraintdef(oid) LIKE '%jsonb_array_length%' LOOP\n EXECUTE format('ALTER TABLE pu"
        "blic.knowledge_rule_versions DROP CONSTRAINT %I',item.conname); END LOOP;\n END $$;\n"
        '\nALTER TABLE public.knowledge_rule_versions ADD CONSTRAINT knowledge_source_body_shap'
        "e CHECK (jsonb_typeof(command)='object' AND jsonb_typeof(body)='object' AND jsonb_type"
        "of(source_basis)='object' AND jsonb_typeof(sources)='array' AND jsonb_typeof(reads)='a"
        "rray' AND ((jsonb_array_length(sources)>0 AND jsonb_array_length(reads)>0) OR (operati"
        "on='knowledge.candidate.create' AND (coalesce(jsonb_typeof(command->'envelope'->'paylo"
        "ad'->'answer_origin')='object',false) OR coalesce(jsonb_typeof(command->'envelope'->'p"
        "ayload'->'candidate')='object',false)))));\n\nCREATE FUNCTION public.knowledge_answer_"
        'sources_visible(t uuid,c uuid,proof jsonb) RETURNS boolean LANGUAGE plpgsql STABLE SEC'
        'URITY INVOKER SET search_path=pg_catalog,public,pg_temp AS $knowledge_answer_acl$\n\nD'
        'ECLARE expected jsonb; visible boolean;\nBEGIN\n IF t IS DISTINCT FROM nullif(current_'
        "setting('pdos.tenant_id',true),'')::uuid\n OR NOT public.category_access(t,c) OR jsonb"
        "_typeof(proof) IS DISTINCT FROM 'array' THEN RETURN false; END IF;\n FOR expected IN S"
        "ELECT value FROM jsonb_array_elements(proof) LOOP\n  IF expected->>'category_id' IS DI"
        "STINCT FROM c::text THEN RETURN false; END IF;\n  CASE expected->>'source_type'\n WHEN"
        " 'artifact' THEN\n  WITH authoritative_enterprise_sources_artifact AS \n(SELECT 'artif"
        "act' AS source_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS"
        ' tenant_id, artifact_versions.category_id AS category_id, artifact_versions.product_id'
        ' AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, a'
        'rtifact_versions.owner_id AS owner_id, artifact_versions.revision AS source_revision, '
        'artifact_versions.title AS title, artifact_versions.content_hash AS content_hash, arti'
        "fact_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS natur"
        "e, artifact_versions.visibility != 'category' OR coalesce(products.visibility != 'cate"
        "gory', false) OR coalesce(uploaded_originals.visibility != 'category', false) AS priva"
        'te, artifact_versions.original_id IS NOT NULL AS customer_original, true AS is_current'
        ', artifact_versions.created_at AS created_at, artifact_versions.original_id AS origina'
        'l_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.original_id IS N'
        'OT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS origina'
        "l_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN product"
        's ON products.tenant_id = artifact_versions.tenant_id AND products.id = artifact_versi'
        'ons.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = ar'
        'tifact_versions.tenant_id AND uploaded_originals.id = artifact_versions.original_id AN'
        'D uploaded_originals.category_id = artifact_versions.category_id AND uploaded_original'
        's.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN origina'
        'l_security ON original_security.tenant_id = uploaded_originals.tenant_id AND original_'
        'security.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAS'
        "T(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.s"
        "tatus = 'active' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions."
        'product_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS N'
        "ULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND "
        "uploaded_originals.scan_status = 'clean' AND original_security.source_state = 'active'"
        " AND original_security.disposition = 'active' AND original_security.current_request_id"
        ' IS NOT NULL))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_artif'
        'act \nWHERE authoritative_enterprise_sources_artifact.tenant_id = t AND authoritative_'
        'enterprise_sources_artifact.category_id = c AND CAST(authoritative_enterprise_sources_'
        "artifact.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise"
        "_sources_artifact.source_revision AS TEXT) = expected->>'source_revision' AND authorit"
        "ative_enterprise_sources_artifact.content_hash = expected->>'content_hash') AS anon_1 "
        "INTO visible;\n WHEN 'knowledge' THEN\n  SELECT EXISTS (SELECT 1 \nFROM (SELECT catego"
        'ry_knowledge_entries.id AS source_id, category_knowledge_entries.tenant_id AS tenant_i'
        'd, category_knowledge_entries.category_id AS category_id, category_knowledge_entries.v'
        'ersion AS source_revision, encode(sha256(convert_to(CAST(category_knowledge_entries.co'
        "ntent AS TEXT), 'UTF8')), 'hex') AS content_hash \nFROM category_knowledge_entries JOI"
        'N category_knowledge_current ON category_knowledge_current.tenant_id = category_knowle'
        'dge_entries.tenant_id AND category_knowledge_current.lineage_id = category_knowledge_e'
        "ntries.lineage_id AND category_knowledge_current.status = 'active' \nWHERE category_kn"
        "owledge_entries.action != 'withdraw' UNION ALL SELECT knowledge_rule_versions.id AS so"
        'urce_id, knowledge_rule_versions.tenant_id AS tenant_id, knowledge_rule_versions.categ'
        'ory_id AS category_id, knowledge_rule_versions.revision AS source_revision, encode(sha'
        "256(convert_to(CAST(knowledge_rule_versions.body AS TEXT), 'UTF8')), 'hex') AS content"
        '_hash \nFROM knowledge_rule_versions JOIN knowledge_rule_currents ON knowledge_rule_cu'
        'rrents.tenant_id = knowledge_rule_versions.tenant_id AND knowledge_rule_currents.rule_'
        'id = knowledge_rule_versions.rule_id) AS ordinary_knowledge_leaves \nWHERE ordinary_kn'
        'owledge_leaves.tenant_id = t AND ordinary_knowledge_leaves.category_id = c AND CAST(or'
        "dinary_knowledge_leaves.source_id AS TEXT) = expected->>'source_id' AND CAST(ordinary_"
        "knowledge_leaves.source_revision AS TEXT) = expected->>'source_revision' AND ordinary_"
        "knowledge_leaves.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n W"
        "HEN 'issue' THEN\n  WITH enterprise_authoritative_artifacts_issue AS \n(SELECT 'artifa"
        "ct' AS source_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS "
        'tenant_id, artifact_versions.category_id AS category_id, artifact_versions.product_id '
        'AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, ar'
        'tifact_versions.owner_id AS owner_id, artifact_versions.revision AS source_revision, a'
        'rtifact_versions.title AS title, artifact_versions.content_hash AS content_hash, artif'
        "act_versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature"
        ", artifact_versions.visibility != 'category' OR coalesce(products.visibility != 'categ"
        "ory', false) OR coalesce(uploaded_originals.visibility != 'category', false) AS privat"
        'e, artifact_versions.original_id IS NOT NULL AS customer_original, true AS is_current,'
        ' artifact_versions.created_at AS created_at, artifact_versions.original_id AS original'
        '_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versions.original_id IS NO'
        'T NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original'
        "_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN products"
        ' ON products.tenant_id = artifact_versions.tenant_id AND products.id = artifact_versio'
        'ns.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = art'
        'ifact_versions.tenant_id AND uploaded_originals.id = artifact_versions.original_id AND'
        ' uploaded_originals.category_id = artifact_versions.category_id AND uploaded_originals'
        '.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN original'
        '_security ON original_security.tenant_id = uploaded_originals.tenant_id AND original_s'
        'ecurity.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST'
        "(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.st"
        "atus = 'active' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.p"
        'roduct_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NU'
        "LL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND u"
        "ploaded_originals.scan_status = 'clean' AND original_security.source_state = 'active' "
        "AND original_security.disposition = 'active' AND original_security.current_request_id "
        'IS NOT NULL)), \nshared_enterprise_quality_issue_versions AS MATERIALIZED \n(SELECT qu'
        'ality_issue_versions.product_id AS product_id, quality_issue_versions.project_id AS pr'
        'oject_id, quality_issue_versions.issue_id AS issue_id, quality_issue_versions.revision'
        ' AS revision, quality_issue_versions.previous_issue_version_id AS previous_issue_versi'
        'on_id, quality_issue_versions.previous_revision AS previous_revision, quality_issue_ve'
        'rsions.owner_id AS owner_id, quality_issue_versions.writer_id AS writer_id, quality_is'
        'sue_versions.visibility AS visibility, quality_issue_versions.purpose AS purpose, qual'
        'ity_issue_versions.status AS status, quality_issue_versions.operation AS operation, qu'
        'ality_issue_versions.issue_snapshot AS issue_snapshot, quality_issue_versions.snapshot'
        '_sha256 AS snapshot_sha256, quality_issue_versions.input_snapshot AS input_snapshot, q'
        'uality_issue_versions.authority_snapshot AS authority_snapshot, quality_issue_versions'
        '.policy_snapshot AS policy_snapshot, quality_issue_versions.sources AS sources, qualit'
        'y_issue_versions.required_source_read_set AS required_source_read_set, quality_issue_v'
        'ersions.source_basis AS source_basis, quality_issue_versions.intent_digest AS intent_d'
        'igest, quality_issue_versions.reason AS reason, quality_issue_versions.id AS id, quali'
        'ty_issue_versions.tenant_id AS tenant_id, quality_issue_versions.created_at AS created'
        '_at, quality_issue_versions.category_id AS category_id \nFROM quality_issue_versions '
        "\nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id"
        "', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT projec"
        'ts.product_id AS product_id, projects.owner_id AS owner_id, projects.name AS name, pro'
        'jects.purpose AS purpose, projects.scope AS scope, projects.visibility AS visibility, '
        'projects.status AS status, projects.revision AS revision, projects.current_plan_id AS '
        'current_plan_id, projects.trigger_type AS trigger_type, projects.trigger_id AS trigger'
        '_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id '
        'AS tenant_id, projects.created_at AS created_at, projects.category_id AS category_id '
        "\nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_"
        "id', true), '') AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT prod"
        'ucts.name AS name, products.purpose AS purpose, products.revision AS revision, product'
        's.lifecycle_epoch AS lifecycle_epoch, products.status AS status, products.owner_id AS '
        'owner_id, products.parent_product_id AS parent_product_id, products.category_id AS cat'
        'egory_id, products.visibility AS visibility, products.target_price AS target_price, pr'
        'oducts.target_price_currency AS target_price_currency, products.target_price_basis AS '
        'target_price_basis, products.target_price_includes_tax AS target_price_includes_tax, p'
        'roducts.target_price_as_of AS target_price_as_of, products.id AS id, products.tenant_i'
        'd AS tenant_id, products.created_at AS created_at \nFROM products \nWHERE products.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_"
        'enterprise_quality_current_issues AS MATERIALIZED \n(SELECT quality_current_issues.pro'
        'duct_id AS product_id, quality_current_issues.project_id AS project_id, quality_curren'
        't_issues.issue_id AS issue_id, quality_current_issues.issue_version_id AS issue_versio'
        'n_id, quality_current_issues.issue_revision AS issue_revision, quality_current_issues.'
        'epoch AS epoch, quality_current_issues.id AS id, quality_current_issues.tenant_id AS t'
        'enant_id, quality_current_issues.created_at AS created_at, quality_current_issues.cate'
        'gory_id AS category_id \nFROM quality_current_issues \nWHERE quality_current_issues.te'
        "nant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nauthor"
        "itative_enterprise_sources_issue AS \n(SELECT 'issue' AS source_type, shared_enterpris"
        'e_quality_issue_versions.id AS source_id, shared_enterprise_quality_issue_versions.ten'
        'ant_id AS tenant_id, shared_enterprise_quality_issue_versions.category_id AS category_'
        'id, shared_enterprise_quality_issue_versions.product_id AS product_id, shared_enterpri'
        'se_quality_issue_versions.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id,'
        ' shared_enterprise_quality_issue_versions.owner_id AS owner_id, shared_enterprise_qual'
        'ity_issue_versions.revision AS source_revision, shared_enterprise_quality_issue_versio'
        "ns.issue_snapshot ->> 'title' AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build"
        "_object('object_id', shared_enterprise_quality_issue_versions.issue_id, 'kind', 'issue"
        "', 'facts', jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.is"
        "sue_id, 'title', shared_enterprise_quality_issue_versions.issue_snapshot['title'], 'st"
        "atus', shared_enterprise_quality_issue_versions.status, 'risk', shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['risk'], 'needs_recheck', shared_enterprise_quality_"
        "issue_versions.issue_snapshot['needs_recheck'], 'recheck_reasons', shared_enterprise_q"
        "uality_issue_versions.issue_snapshot['recheck_reasons'], 'merged_into', shared_enterpr"
        "ise_quality_issue_versions.issue_snapshot['merged_into'], 'root_cause', jsonb_build_ob"
        "ject('text', shared_enterprise_quality_issue_versions.issue_snapshot['root_cause']['te"
        "xt'], 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['root_cause'"
        "]['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['root_cau"
        "se']['at']), 'containment', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterp"
        "rise_containment.value['id'], 'text', enterprise_containment.value['text'], 'executor_"
        "id', enterprise_containment.value['executor_id']) ORDER BY enterprise_containment.ordi"
        'nal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(coalesce(shared_e'
        "nterprise_quality_issue_versions.issue_snapshot['containment'], CAST('[]' AS JSONB))) "
        "WITH ORDINALITY AS enterprise_containment(value, ordinal)), 'closure', jsonb_build_obj"
        "ect('text', shared_enterprise_quality_issue_versions.issue_snapshot['closure']['text']"
        ", 'actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['closure']['acto"
        "r_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['closure']['at']"
        ")), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', '"
        "id', enterprise_reads_issue.value['artifact_id'], 'version', enterprise_reads_issue.va"
        "lue['expected_revision']) ORDER BY enterprise_reads_issue.value ->> 'artifact_id', ent"
        "erprise_reads_issue.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2"
        ' \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_source_'
        "read_set) AS enterprise_reads_issue(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex'"
        ") AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_quality"
        "_issue_versions.issue_id, 'kind', 'issue', 'facts', jsonb_build_object('issue_id', sha"
        "red_enterprise_quality_issue_versions.issue_id, 'title', shared_enterprise_quality_iss"
        "ue_versions.issue_snapshot['title'], 'status', shared_enterprise_quality_issue_version"
        "s.status, 'risk', shared_enterprise_quality_issue_versions.issue_snapshot['risk'], 'ne"
        "eds_recheck', shared_enterprise_quality_issue_versions.issue_snapshot['needs_recheck']"
        ", 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot['recheck_"
        "reasons'], 'merged_into', shared_enterprise_quality_issue_versions.issue_snapshot['mer"
        "ged_into'], 'root_cause', jsonb_build_object('text', shared_enterprise_quality_issue_v"
        "ersions.issue_snapshot['root_cause']['text'], 'actor_id', shared_enterprise_quality_is"
        "sue_versions.issue_snapshot['root_cause']['actor_id'], 'at', shared_enterprise_quality"
        "_issue_versions.issue_snapshot['root_cause']['at']), 'containment', (SELECT coalesce(j"
        "sonb_agg(jsonb_build_object('id', enterprise_containment.value['id'], 'text', enterpri"
        "se_containment.value['text'], 'executor_id', enterprise_containment.value['executor_id"
        "']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS coalesce_1 \nFRO"
        'M jsonb_array_elements(coalesce(shared_enterprise_quality_issue_versions.issue_snapsho'
        "t['containment'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_containment(valu"
        "e, ordinal)), 'closure', jsonb_build_object('text', shared_enterprise_quality_issue_ve"
        "rsions.issue_snapshot['closure']['text'], 'actor_id', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['closure']['actor_id'], 'at', shared_enterprise_quality_issue_"
        "versions.issue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg("
        "jsonb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['artifact_id"
        "'], 'version', enterprise_reads_issue.value['expected_revision']) ORDER BY enterprise_"
        "reads_issue.value ->> 'artifact_id', enterprise_reads_issue.value ->> 'expected_revisi"
        "on'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise"
        "_quality_issue_versions.required_source_read_set) AS enterprise_reads_issue(value)), '"
        "record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b"
        "\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002')"
        " AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enterprise_qu"
        "ality_issue_versions.issue_id, 'kind', 'issue', 'facts', jsonb_build_object('issue_id'"
        ", shared_enterprise_quality_issue_versions.issue_id, 'title', shared_enterprise_qualit"
        "y_issue_versions.issue_snapshot['title'], 'status', shared_enterprise_quality_issue_ve"
        "rsions.status, 'risk', shared_enterprise_quality_issue_versions.issue_snapshot['risk']"
        ", 'needs_recheck', shared_enterprise_quality_issue_versions.issue_snapshot['needs_rech"
        "eck'], 'recheck_reasons', shared_enterprise_quality_issue_versions.issue_snapshot['rec"
        "heck_reasons'], 'merged_into', shared_enterprise_quality_issue_versions.issue_snapshot"
        "['merged_into'], 'root_cause', jsonb_build_object('text', shared_enterprise_quality_is"
        "sue_versions.issue_snapshot['root_cause']['text'], 'actor_id', shared_enterprise_quali"
        "ty_issue_versions.issue_snapshot['root_cause']['actor_id'], 'at', shared_enterprise_qu"
        "ality_issue_versions.issue_snapshot['root_cause']['at']), 'containment', (SELECT coale"
        "sce(jsonb_agg(jsonb_build_object('id', enterprise_containment.value['id'], 'text', ent"
        "erprise_containment.value['text'], 'executor_id', enterprise_containment.value['execut"
        "or_id']) ORDER BY enterprise_containment.ordinal), jsonb_build_array()) AS coalesce_1 "
        '\nFROM jsonb_array_elements(coalesce(shared_enterprise_quality_issue_versions.issue_sn'
        "apshot['containment'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_containment"
        "(value, ordinal)), 'closure', jsonb_build_object('text', shared_enterprise_quality_iss"
        "ue_versions.issue_snapshot['closure']['text'], 'actor_id', shared_enterprise_quality_i"
        "ssue_versions.issue_snapshot['closure']['actor_id'], 'at', shared_enterprise_quality_i"
        "ssue_versions.issue_snapshot['closure']['at'])), 'source_refs', (SELECT coalesce(jsonb"
        "_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_issue.value['artifa"
        "ct_id'], 'version', enterprise_reads_issue.value['expected_revision']) ORDER BY enterp"
        "rise_reads_issue.value ->> 'artifact_id', enterprise_reads_issue.value ->> 'expected_r"
        "evision'), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(shared_enter"
        'prise_quality_issue_versions.required_source_read_set) AS enterprise_reads_issue(value'
        ")), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS structured, 'structured' AS nature, shared_enterprise_quality_is"
        "sue_versions.visibility != 'category' OR shared_enterprise_projects.visibility != 'cat"
        "egory' OR shared_enterprise_products.visibility != 'category' OR (EXISTS (SELECT 1 \nF"
        'ROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_source_read'
        '_set) AS enterprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_issue O'
        'N enterprise_authoritative_artifacts_issue.tenant_id = shared_enterprise_quality_issue'
        '_versions.tenant_id AND enterprise_authoritative_artifacts_issue.source_id = CAST((ent'
        "erprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative"
        '_artifacts_issue.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(sh'
        'ared_enterprise_quality_issue_versions.required_source_read_set) AS enterprise_reads_i'
        'ssue(value) JOIN enterprise_authoritative_artifacts_issue ON enterprise_authoritative_'
        'artifacts_issue.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND ent'
        'erprise_authoritative_artifacts_issue.source_id = CAST((enterprise_reads_issue.value -'
        ">> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_issue.customer_o"
        'riginal) AS customer_original, shared_enterprise_quality_current_issues.issue_version_'
        'id = shared_enterprise_quality_issue_versions.id AS is_current, shared_enterprise_qual'
        'ity_issue_versions.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared'
        '_enterprise_quality_issue_versions.issue_id AS object_id, (SELECT coalesce(array_agg(e'
        'nterprise_authoritative_artifacts_issue.original_id), ARRAY[]::UUID[]) AS coalesce_3 '
        '\nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_source_r'
        'ead_set) AS enterprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_issu'
        'e ON enterprise_authoritative_artifacts_issue.tenant_id = shared_enterprise_quality_is'
        'sue_versions.tenant_id AND enterprise_authoritative_artifacts_issue.source_id = CAST(('
        "enterprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritat"
        'ive_artifacts_issue.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELEC'
        'T 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sour'
        'ce_read_set) AS enterprise_reads_issue(value) JOIN enterprise_authoritative_artifacts_'
        'issue ON enterprise_authoritative_artifacts_issue.tenant_id = shared_enterprise_qualit'
        'y_issue_versions.tenant_id AND enterprise_authoritative_artifacts_issue.source_id = CA'
        "ST((enterprise_reads_issue.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_author"
        "itative_artifacts_issue.source_revision != CAST((enterprise_reads_issue.value ->> 'exp"
        "ected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_s"
        'tatus \nFROM shared_enterprise_quality_issue_versions JOIN shared_enterprise_projects '
        'ON shared_enterprise_projects.tenant_id = shared_enterprise_quality_issue_versions.ten'
        'ant_id AND shared_enterprise_projects.product_id = shared_enterprise_quality_issue_ver'
        'sions.product_id AND shared_enterprise_projects.id = shared_enterprise_quality_issue_v'
        'ersions.project_id AND shared_enterprise_projects.category_id = shared_enterprise_qual'
        'ity_issue_versions.category_id JOIN shared_enterprise_products ON shared_enterprise_pr'
        'oducts.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND shared_enter'
        'prise_products.id = shared_enterprise_quality_issue_versions.product_id AND shared_ent'
        'erprise_products.category_id = shared_enterprise_quality_issue_versions.category_id JO'
        'IN shared_enterprise_quality_current_issues ON shared_enterprise_quality_current_issue'
        's.tenant_id = shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise'
        '_quality_current_issues.product_id = shared_enterprise_quality_issue_versions.product_'
        'id AND shared_enterprise_quality_current_issues.project_id = shared_enterprise_quality'
        '_issue_versions.project_id AND shared_enterprise_quality_current_issues.issue_id = sha'
        'red_enterprise_quality_issue_versions.issue_id \nWHERE shared_enterprise_quality_issue'
        "_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID"
        ') AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issu'
        'e_versions.required_source_read_set) AS enterprise_reads_issue(value) \nWHERE NOT (EXI'
        'STS (SELECT 1 \nFROM enterprise_authoritative_artifacts_issue \nWHERE enterprise_autho'
        'ritative_artifacts_issue.tenant_id = shared_enterprise_quality_issue_versions.tenant_i'
        'd AND enterprise_authoritative_artifacts_issue.source_id = CAST((enterprise_reads_issu'
        "e.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritativ"
        'e_enterprise_sources_issue \nWHERE authoritative_enterprise_sources_issue.tenant_id = '
        't AND authoritative_enterprise_sources_issue.category_id = c AND CAST(authoritative_en'
        "terprise_sources_issue.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritat"
        "ive_enterprise_sources_issue.source_revision AS TEXT) = expected->>'source_revision' A"
        "ND authoritative_enterprise_sources_issue.content_hash = expected->>'content_hash') AS"
        " anon_1 INTO visible;\n WHEN 'capa' THEN\n  WITH enterprise_authoritative_artifacts_ca"
        "pa AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS source_id, artifact"
        '_versions.tenant_id AS tenant_id, artifact_versions.category_id AS category_id, artifa'
        'ct_versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS U'
        'UID) AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.revisio'
        'n AS source_revision, artifact_versions.title AS title, artifact_versions.content_hash'
        ' AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured'
        ", 'untrusted' AS nature, artifact_versions.visibility != 'category' OR coalesce(produc"
        "ts.visibility != 'category', false) OR coalesce(uploaded_originals.visibility != 'cate"
        "gory', false) AS private, artifact_versions.original_id IS NOT NULL AS customer_origin"
        'al, true AS is_current, artifact_versions.created_at AS created_at, artifact_versions.'
        'original_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_ver'
        'sions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]:'
        ":UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_versions L"
        'EFT OUTER JOIN products ON products.tenant_id = artifact_versions.tenant_id AND produc'
        'ts.id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_or'
        'iginals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id = artifact_v'
        'ersions.original_id AND uploaded_originals.category_id = artifact_versions.category_id'
        ' AND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.product_id L'
        'EFT OUTER JOIN original_security ON original_security.tenant_id = uploaded_originals.t'
        'enant_id AND original_security.original_id = uploaded_originals.id \nWHERE artifact_ve'
        "rsions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) A"
        "ND artifact_versions.status = 'active' AND artifact_versions.category_id IS NOT NULL A"
        'ND (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifact_ver'
        'sions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.'
        "status = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_security.s"
        "ource_state = 'active' AND original_security.disposition = 'active' AND original_secur"
        'ity.current_request_id IS NOT NULL)), \nshared_enterprise_quality_issue_versions AS MA'
        'TERIALIZED \n(SELECT quality_issue_versions.product_id AS product_id, quality_issue_ve'
        'rsions.project_id AS project_id, quality_issue_versions.issue_id AS issue_id, quality_'
        'issue_versions.revision AS revision, quality_issue_versions.previous_issue_version_id '
        'AS previous_issue_version_id, quality_issue_versions.previous_revision AS previous_rev'
        'ision, quality_issue_versions.owner_id AS owner_id, quality_issue_versions.writer_id A'
        'S writer_id, quality_issue_versions.visibility AS visibility, quality_issue_versions.p'
        'urpose AS purpose, quality_issue_versions.status AS status, quality_issue_versions.ope'
        'ration AS operation, quality_issue_versions.issue_snapshot AS issue_snapshot, quality_'
        'issue_versions.snapshot_sha256 AS snapshot_sha256, quality_issue_versions.input_snapsh'
        'ot AS input_snapshot, quality_issue_versions.authority_snapshot AS authority_snapshot,'
        ' quality_issue_versions.policy_snapshot AS policy_snapshot, quality_issue_versions.sou'
        'rces AS sources, quality_issue_versions.required_source_read_set AS required_source_re'
        'ad_set, quality_issue_versions.source_basis AS source_basis, quality_issue_versions.in'
        'tent_digest AS intent_digest, quality_issue_versions.reason AS reason, quality_issue_v'
        'ersions.id AS id, quality_issue_versions.tenant_id AS tenant_id, quality_issue_version'
        's.created_at AS created_at, quality_issue_versions.category_id AS category_id \nFROM q'
        'uality_issue_versions \nWHERE quality_issue_versions.tenant_id = CAST(nullif(current_s'
        "etting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIA"
        'LIZED \n(SELECT projects.product_id AS product_id, projects.owner_id AS owner_id, proj'
        'ects.name AS name, projects.purpose AS purpose, projects.scope AS scope, projects.visi'
        'bility AS visibility, projects.status AS status, projects.revision AS revision, projec'
        'ts.current_plan_id AS current_plan_id, projects.trigger_type AS trigger_type, projects'
        '.trigger_id AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS i'
        'd, projects.tenant_id AS tenant_id, projects.created_at AS created_at, projects.catego'
        'ry_id AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS MATERI"
        'ALIZED \n(SELECT products.name AS name, products.purpose AS purpose, products.revision'
        ' AS revision, products.lifecycle_epoch AS lifecycle_epoch, products.status AS status, '
        'products.owner_id AS owner_id, products.parent_product_id AS parent_product_id, produc'
        'ts.category_id AS category_id, products.visibility AS visibility, products.target_pric'
        'e AS target_price, products.target_price_currency AS target_price_currency, products.t'
        'arget_price_basis AS target_price_basis, products.target_price_includes_tax AS target_'
        'price_includes_tax, products.target_price_as_of AS target_price_as_of, products.id AS '
        'id, products.tenant_id AS tenant_id, products.created_at AS created_at \nFROM products'
        " \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '')"
        ' AS UUID)), \nshared_enterprise_quality_current_issues AS MATERIALIZED \n(SELECT quali'
        'ty_current_issues.product_id AS product_id, quality_current_issues.project_id AS proje'
        'ct_id, quality_current_issues.issue_id AS issue_id, quality_current_issues.issue_versi'
        'on_id AS issue_version_id, quality_current_issues.issue_revision AS issue_revision, qu'
        'ality_current_issues.epoch AS epoch, quality_current_issues.id AS id, quality_current_'
        'issues.tenant_id AS tenant_id, quality_current_issues.created_at AS created_at, qualit'
        'y_current_issues.category_id AS category_id \nFROM quality_current_issues \nWHERE qual'
        "ity_current_issues.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), ''"
        ") AS UUID)), \nauthoritative_enterprise_sources_capa AS \n(SELECT 'capa' AS source_typ"
        'e, shared_enterprise_quality_issue_versions.id AS source_id, shared_enterprise_quality'
        '_issue_versions.tenant_id AS tenant_id, shared_enterprise_quality_issue_versions.categ'
        'ory_id AS category_id, shared_enterprise_quality_issue_versions.product_id AS product_'
        'id, shared_enterprise_quality_issue_versions.project_id AS project_id, CAST(NULL AS UU'
        'ID) AS proposal_id, shared_enterprise_quality_issue_versions.owner_id AS owner_id, sha'
        "red_enterprise_quality_issue_versions.revision AS source_revision, 'CAPA \xb7 ' || (sh"
        "ared_enterprise_quality_issue_versions.issue_snapshot ->> 'title') AS title, encode(sh"
        "a256(convert_to(CAST(CAST(jsonb_build_object('object_id', CAST((shared_enterprise_qual"
        "ity_issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts',"
        " jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.issue_id, 'ca"
        "pa_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['id'], 'issue_"
        "status', shared_enterprise_quality_issue_versions.status, 'hypotheses', (SELECT coales"
        "ce(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses.value['text']) ORDER BY "
        'enterprise_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_'
        "elements(coalesce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['hyp"
        "otheses'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(value, ordin"
        "al)), 'actions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_a"
        "ctions.value['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', enterprise_"
        "capa_actions.value['text'], 'executor_id', enterprise_capa_actions.value['executor_id'"
        "], 'completion_text', enterprise_capa_actions.value['completion']['text'], 'completed_"
        "by', enterprise_capa_actions.value['completion']['executor_id'], 'completed_at', enter"
        "prise_capa_actions.value['completion']['at']['occurred_at']) ORDER BY enterprise_capa_"
        'actions.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(coale'
        "sce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['actions'], CAST('"
        "[]' AS JSONB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requirem"
        "ent', jsonb_build_object('method', shared_enterprise_quality_issue_versions.issue_snap"
        "shot['capa']['requirement']['method'], 'acceptance', shared_enterprise_quality_issue_v"
        "ersions.issue_snapshot['capa']['requirement']['acceptance'], 'observation_until', shar"
        "ed_enterprise_quality_issue_versions.issue_snapshot['capa']['requirement']['observatio"
        "n_until']), 'effectiveness', jsonb_build_object('text', shared_enterprise_quality_issu"
        "e_versions.issue_snapshot['capa']['effectiveness']['text'], 'result', shared_enterpris"
        "e_quality_issue_versions.issue_snapshot['capa']['effectiveness']['result'], 'actor_id'"
        ", shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['ac"
        "tor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effec"
        "tiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type"
        "', 'artifact', 'id', enterprise_reads_capa.value['artifact_id'], 'version', enterprise"
        "_reads_capa.value['expected_revision']) ORDER BY enterprise_reads_capa.value ->> 'arti"
        "fact_id', enterprise_reads_capa.value ->> 'expected_revision'), jsonb_build_array()) A"
        'S coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.requ'
        "ired_source_read_set) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')),"
        " 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', CAST((shared_enterp"
        "rise_quality_issue_versions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa',"
        " 'facts', jsonb_build_object('issue_id', shared_enterprise_quality_issue_versions.issu"
        "e_id, 'capa_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['id']"
        ", 'issue_status', shared_enterprise_quality_issue_versions.status, 'hypotheses', (SELE"
        "CT coalesce(jsonb_agg(jsonb_build_object('text', enterprise_hypotheses.value['text']) "
        'ORDER BY enterprise_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jso'
        "nb_array_elements(coalesce(shared_enterprise_quality_issue_versions.issue_snapshot['ca"
        "pa']['hypotheses'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(val"
        "ue, ordinal)), 'actions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterpri"
        "se_capa_actions.value['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', en"
        "terprise_capa_actions.value['text'], 'executor_id', enterprise_capa_actions.value['exe"
        "cutor_id'], 'completion_text', enterprise_capa_actions.value['completion']['text'], 'c"
        "ompleted_by', enterprise_capa_actions.value['completion']['executor_id'], 'completed_a"
        "t', enterprise_capa_actions.value['completion']['at']['occurred_at']) ORDER BY enterpr"
        'ise_capa_actions.ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_eleme'
        "nts(coalesce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['actions'"
        "], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), "
        "'requirement', jsonb_build_object('method', shared_enterprise_quality_issue_versions.i"
        "ssue_snapshot['capa']['requirement']['method'], 'acceptance', shared_enterprise_qualit"
        "y_issue_versions.issue_snapshot['capa']['requirement']['acceptance'], 'observation_unt"
        "il', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['requirement']['o"
        "bservation_until']), 'effectiveness', jsonb_build_object('text', shared_enterprise_qua"
        "lity_issue_versions.issue_snapshot['capa']['effectiveness']['text'], 'result', shared_"
        "enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['result'], '"
        "actor_id', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiven"
        "ess']['actor_id'], 'at', shared_enterprise_quality_issue_versions.issue_snapshot['capa"
        "']['effectiveness']['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_obj"
        "ect('type', 'artifact', 'id', enterprise_reads_capa.value['artifact_id'], 'version', e"
        "nterprise_reads_capa.value['expected_revision']) ORDER BY enterprise_reads_capa.value "
        "->> 'artifact_id', enterprise_reads_capa.value ->> 'expected_revision'), jsonb_build_a"
        'rray()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_vers'
        "ions.required_source_read_set) AS enterprise_reads_capa(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT"
        ") AS body, CAST(jsonb_build_object('object_id', CAST((shared_enterprise_quality_issue_"
        "versions.issue_snapshot['capa']) ->> 'id' AS UUID), 'kind', 'capa', 'facts', jsonb_bui"
        "ld_object('issue_id', shared_enterprise_quality_issue_versions.issue_id, 'capa_id', sh"
        "ared_enterprise_quality_issue_versions.issue_snapshot['capa']['id'], 'issue_status', s"
        "hared_enterprise_quality_issue_versions.status, 'hypotheses', (SELECT coalesce(jsonb_a"
        "gg(jsonb_build_object('text', enterprise_hypotheses.value['text']) ORDER BY enterprise"
        '_hypotheses.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(c'
        "oalesce(shared_enterprise_quality_issue_versions.issue_snapshot['capa']['hypotheses'],"
        " CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_hypotheses(value, ordinal)), 'act"
        "ions', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_capa_actions.val"
        "ue['id'], 'kind', enterprise_capa_actions.value['kind'], 'text', enterprise_capa_actio"
        "ns.value['text'], 'executor_id', enterprise_capa_actions.value['executor_id'], 'comple"
        "tion_text', enterprise_capa_actions.value['completion']['text'], 'completed_by', enter"
        "prise_capa_actions.value['completion']['executor_id'], 'completed_at', enterprise_capa"
        "_actions.value['completion']['at']['occurred_at']) ORDER BY enterprise_capa_actions.or"
        'dinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(shared'
        "_enterprise_quality_issue_versions.issue_snapshot['capa']['actions'], CAST('[]' AS JSO"
        "NB))) WITH ORDINALITY AS enterprise_capa_actions(value, ordinal)), 'requirement', json"
        "b_build_object('method', shared_enterprise_quality_issue_versions.issue_snapshot['capa"
        "']['requirement']['method'], 'acceptance', shared_enterprise_quality_issue_versions.is"
        "sue_snapshot['capa']['requirement']['acceptance'], 'observation_until', shared_enterpr"
        "ise_quality_issue_versions.issue_snapshot['capa']['requirement']['observation_until'])"
        ", 'effectiveness', jsonb_build_object('text', shared_enterprise_quality_issue_versions"
        ".issue_snapshot['capa']['effectiveness']['text'], 'result', shared_enterprise_quality_"
        "issue_versions.issue_snapshot['capa']['effectiveness']['result'], 'actor_id', shared_e"
        "nterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']['actor_id'], "
        "'at', shared_enterprise_quality_issue_versions.issue_snapshot['capa']['effectiveness']"
        "['at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifa"
        "ct', 'id', enterprise_reads_capa.value['artifact_id'], 'version', enterprise_reads_cap"
        "a.value['expected_revision']) ORDER BY enterprise_reads_capa.value ->> 'artifact_id', "
        "enterprise_reads_capa.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce"
        '_3 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_sourc'
        "e_read_set) AS enterprise_reads_capa(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structure"
        "d' AS nature, shared_enterprise_quality_issue_versions.visibility != 'category' OR sha"
        "red_enterprise_projects.visibility != 'category' OR shared_enterprise_products.visibil"
        "ity != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_q"
        'uality_issue_versions.required_source_read_set) AS enterprise_reads_capa(value) JOIN e'
        'nterprise_authoritative_artifacts_capa ON enterprise_authoritative_artifacts_capa.tena'
        'nt_id = shared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritativ'
        "e_artifacts_capa.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_capa.private)) AS private, EXISTS (SEL'
        'ECT 1 \nFROM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_so'
        'urce_read_set) AS enterprise_reads_capa(value) JOIN enterprise_authoritative_artifacts'
        '_capa ON enterprise_authoritative_artifacts_capa.tenant_id = shared_enterprise_quality'
        '_issue_versions.tenant_id AND enterprise_authoritative_artifacts_capa.source_id = CAST'
        "((enterprise_reads_capa.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authorita"
        'tive_artifacts_capa.customer_original) AS customer_original, shared_enterprise_quality'
        '_current_issues.issue_version_id = shared_enterprise_quality_issue_versions.id AS is_c'
        'urrent, shared_enterprise_quality_issue_versions.created_at AS created_at, CAST(NULL A'
        'S UUID) AS original_id, CAST((shared_enterprise_quality_issue_versions.issue_snapshot['
        "'capa']) ->> 'id' AS UUID) AS object_id, (SELECT coalesce(array_agg(enterprise_authori"
        'tative_artifacts_capa.original_id), ARRAY[]::UUID[]) AS coalesce_4 \nFROM jsonb_array_'
        'elements(shared_enterprise_quality_issue_versions.required_source_read_set) AS enterpr'
        'ise_reads_capa(value) JOIN enterprise_authoritative_artifacts_capa ON enterprise_autho'
        'ritative_artifacts_capa.tenant_id = shared_enterprise_quality_issue_versions.tenant_id'
        ' AND enterprise_authoritative_artifacts_capa.source_id = CAST((enterprise_reads_capa.v'
        "alue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_capa.origi"
        'nal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_el'
        'ements(shared_enterprise_quality_issue_versions.required_source_read_set) AS enterpris'
        'e_reads_capa(value) JOIN enterprise_authoritative_artifacts_capa ON enterprise_authori'
        'tative_artifacts_capa.tenant_id = shared_enterprise_quality_issue_versions.tenant_id A'
        'ND enterprise_authoritative_artifacts_capa.source_id = CAST((enterprise_reads_capa.val'
        "ue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_capa.source_"
        "revision != CAST((enterprise_reads_capa.value ->> 'expected_revision') AS INTEGER))) T"
        "HEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_q"
        'uality_issue_versions JOIN shared_enterprise_projects ON shared_enterprise_projects.te'
        'nant_id = shared_enterprise_quality_issue_versions.tenant_id AND shared_enterprise_pro'
        'jects.product_id = shared_enterprise_quality_issue_versions.product_id AND shared_ente'
        'rprise_projects.id = shared_enterprise_quality_issue_versions.project_id AND shared_en'
        'terprise_projects.category_id = shared_enterprise_quality_issue_versions.category_id J'
        'OIN shared_enterprise_products ON shared_enterprise_products.tenant_id = shared_enterp'
        'rise_quality_issue_versions.tenant_id AND shared_enterprise_products.id = shared_enter'
        'prise_quality_issue_versions.product_id AND shared_enterprise_products.category_id = s'
        'hared_enterprise_quality_issue_versions.category_id JOIN shared_enterprise_quality_cur'
        'rent_issues ON shared_enterprise_quality_current_issues.tenant_id = shared_enterprise_'
        'quality_issue_versions.tenant_id AND shared_enterprise_quality_current_issues.product_'
        'id = shared_enterprise_quality_issue_versions.product_id AND shared_enterprise_quality'
        '_current_issues.project_id = shared_enterprise_quality_issue_versions.project_id AND s'
        'hared_enterprise_quality_current_issues.issue_id = shared_enterprise_quality_issue_ver'
        'sions.issue_id \nWHERE shared_enterprise_quality_issue_versions.tenant_id = CAST(nulli'
        "f(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFR"
        'OM jsonb_array_elements(shared_enterprise_quality_issue_versions.required_source_read_'
        'set) AS enterprise_reads_capa(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_a'
        'uthoritative_artifacts_capa \nWHERE enterprise_authoritative_artifacts_capa.tenant_id '
        '= shared_enterprise_quality_issue_versions.tenant_id AND enterprise_authoritative_arti'
        "facts_capa.source_id = CAST((enterprise_reads_capa.value ->> 'artifact_id') AS UUID)))"
        ")) AND ((shared_enterprise_quality_issue_versions.issue_snapshot['capa']) ->> 'id') IS"
        ' NOT NULL)\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_capa \nWH'
        'ERE authoritative_enterprise_sources_capa.tenant_id = t AND authoritative_enterprise_s'
        'ources_capa.category_id = c AND CAST(authoritative_enterprise_sources_capa.source_id A'
        "S TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sources_capa.source"
        "_revision AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_sources"
        "_capa.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 'change"
        "' THEN\n  WITH enterprise_authoritative_artifacts_change AS \n(SELECT 'artifact' AS so"
        'urce_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS tenant_id'
        ', artifact_versions.category_id AS category_id, artifact_versions.product_id AS produc'
        't_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifact_ve'
        'rsions.owner_id AS owner_id, artifact_versions.revision AS source_revision, artifact_v'
        'ersions.title AS title, artifact_versions.content_hash AS content_hash, artifact_versi'
        "ons.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, artifac"
        "t_versions.visibility != 'category' OR coalesce(products.visibility != 'category', fal"
        "se) OR coalesce(uploaded_originals.visibility != 'category', false) AS private, artifa"
        'ct_versions.original_id IS NOT NULL AS customer_original, true AS is_current, artifact'
        '_versions.created_at AS created_at, artifact_versions.original_id AS original_id, arti'
        'fact_versions.id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NULL) T'
        "HEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids, 'cu"
        "rrent' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN products ON produ"
        'cts.tenant_id = artifact_versions.tenant_id AND products.id = artifact_versions.produc'
        't_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = artifact_ver'
        'sions.tenant_id AND uploaded_originals.id = artifact_versions.original_id AND uploaded'
        '_originals.category_id = artifact_versions.category_id AND uploaded_originals.product_'
        'id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN original_security'
        ' ON original_security.tenant_id = uploaded_originals.tenant_id AND original_security.o'
        'riginal_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status = 'a"
        "ctive' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.product_id"
        ' IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NULL OR upl'
        "oaded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploaded_o"
        "riginals.scan_status = 'clean' AND original_security.source_state = 'active' AND origi"
        "nal_security.disposition = 'active' AND original_security.current_request_id IS NOT NU"
        'LL)), \nshared_enterprise_change_request_versions AS MATERIALIZED \n(SELECT change_req'
        'uest_versions.product_id AS product_id, change_request_versions.project_id AS project_'
        'id, change_request_versions.change_id AS change_id, change_request_versions.revision A'
        'S revision, change_request_versions.previous_version_id AS previous_version_id, change'
        '_request_versions.previous_revision AS previous_revision, change_request_versions.owne'
        'r_id AS owner_id, change_request_versions.visibility AS visibility, change_request_ver'
        'sions.status AS status, change_request_versions.operation AS operation, change_request'
        '_versions.intent_digest AS intent_digest, change_request_versions.request_snapshot AS '
        'request_snapshot, change_request_versions.request_sha256 AS request_sha256, change_req'
        'uest_versions.sources AS sources, change_request_versions.required_source_read_set AS '
        'required_source_read_set, change_request_versions.source_basis AS source_basis, change'
        '_request_versions.authority_snapshot AS authority_snapshot, change_request_versions.id'
        ' AS id, change_request_versions.tenant_id AS tenant_id, change_request_versions.create'
        'd_at AS created_at, change_request_versions.category_id AS category_id \nFROM change_r'
        'equest_versions \nWHERE change_request_versions.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_projects AS MATERIALIZED"
        ' \n(SELECT projects.product_id AS product_id, projects.owner_id AS owner_id, projects.'
        'name AS name, projects.purpose AS purpose, projects.scope AS scope, projects.visibilit'
        'y AS visibility, projects.status AS status, projects.revision AS revision, projects.cu'
        'rrent_plan_id AS current_plan_id, projects.trigger_type AS trigger_type, projects.trig'
        'ger_id AS trigger_id, projects.g0_decision_id AS g0_decision_id, projects.id AS id, pr'
        'ojects.tenant_id AS tenant_id, projects.created_at AS created_at, projects.category_id'
        ' AS category_id \nFROM projects \nWHERE projects.tenant_id = CAST(nullif(current_setti'
        "ng('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_products AS MATERIALIZE"
        'D \n(SELECT products.name AS name, products.purpose AS purpose, products.revision AS r'
        'evision, products.lifecycle_epoch AS lifecycle_epoch, products.status AS status, produ'
        'cts.owner_id AS owner_id, products.parent_product_id AS parent_product_id, products.ca'
        'tegory_id AS category_id, products.visibility AS visibility, products.target_price AS '
        'target_price, products.target_price_currency AS target_price_currency, products.target'
        '_price_basis AS target_price_basis, products.target_price_includes_tax AS target_price'
        '_includes_tax, products.target_price_as_of AS target_price_as_of, products.id AS id, p'
        'roducts.tenant_id AS tenant_id, products.created_at AS created_at \nFROM products \nWH'
        "ERE products.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS U"
        'UID)), \nshared_enterprise_change_request_currents AS MATERIALIZED \n(SELECT change_re'
        'quest_currents.product_id AS product_id, change_request_currents.change_id AS change_i'
        'd, change_request_currents.version_id AS version_id, change_request_currents.revision '
        'AS revision, change_request_currents.id AS id, change_request_currents.tenant_id AS te'
        'nant_id, change_request_currents.created_at AS created_at, change_request_currents.cat'
        'egory_id AS category_id \nFROM change_request_currents \nWHERE change_request_currents'
        ".tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \naut"
        "horitative_enterprise_sources_change AS \n(SELECT 'change' AS source_type, shared_ente"
        'rprise_change_request_versions.id AS source_id, shared_enterprise_change_request_versi'
        'ons.tenant_id AS tenant_id, shared_enterprise_change_request_versions.category_id AS c'
        'ategory_id, shared_enterprise_change_request_versions.product_id AS product_id, shared'
        '_enterprise_change_request_versions.project_id AS project_id, CAST(NULL AS UUID) AS pr'
        'oposal_id, shared_enterprise_change_request_versions.owner_id AS owner_id, shared_ente'
        'rprise_change_request_versions.revision AS source_revision, shared_enterprise_change_r'
        "equest_versions.request_snapshot ->> 'title' AS title, encode(sha256(convert_to(CAST(C"
        "AST(jsonb_build_object('object_id', shared_enterprise_change_request_versions.change_i"
        "d, 'kind', 'change', 'facts', jsonb_build_object('id', shared_enterprise_change_reques"
        "t_versions.request_snapshot['id'], 'title', shared_enterprise_change_request_versions."
        "request_snapshot['title'], 'reason', shared_enterprise_change_request_versions.request"
        "_snapshot['reason'], 'status', shared_enterprise_change_request_versions.request_snaps"
        "hot['status'], 'needs_recheck', shared_enterprise_change_request_versions.request_snap"
        "shot['needs_recheck'], 'recheck_reasons', shared_enterprise_change_request_versions.re"
        "quest_snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coalesce(js"
        "onb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'], 'plan_items', ("
        "SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_change_items.value['id']"
        ", 'discipline', enterprise_change_items.value['discipline'], 'verification_requirement"
        "', enterprise_change_items.value['verification_requirement'], 'intent_kind', enterpris"
        "e_change_items.value['intent']['kind']) ORDER BY enterprise_change_items.ordinal), jso"
        'nb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change'
        "_orders.value['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_ch"
        "ange_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_build_objec"
        "t('actor_id', enterprise_change_approvals.value['actor_id'], 'at', enterprise_change_a"
        "pprovals.value['at'], 'discipline', enterprise_change_approvals.value['discipline'], '"
        "text', enterprise_change_approvals.value['text']) ORDER BY enterprise_change_approvals"
        '.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(ent'
        "erprise_change_orders.value['approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS ent"
        "erprise_change_approvals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_a"
        "gg(jsonb_build_object('item_id', enterprise_change_implementations.value['item_id'], '"
        "executor_id', enterprise_change_implementations.value['executor_id'], 'outcome', enter"
        "prise_change_implementations.value['outcome'], 'occurred_at', enterprise_change_implem"
        "entations.value['occurred_at'], 'received_at', enterprise_change_implementations.value"
        "['received_at'], 'note', enterprise_change_implementations.value['note']) ORDER BY ent"
        'erprise_change_implementations.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jso'
        "nb_array_elements(coalesce(enterprise_change_orders.value['implementations'], CAST('[]"
        "' AS JSONB))) WITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), '"
        "effectivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterprise_chan"
        "ge_effectivity.value['item_id'], 'stage', enterprise_change_effectivity.value['stage']"
        ", 'outcome', enterprise_change_effectivity.value['outcome'], 'covered_units', enterpri"
        "se_change_effectivity.value['covered_units'], 'occurred_at', enterprise_change_effecti"
        "vity.value['occurred_at'], 'received_at', enterprise_change_effectivity.value['receive"
        "d_at']) ORDER BY enterprise_change_effectivity.ordinal), jsonb_build_array()) AS coale"
        "sce_5 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['effectivity"
        "'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, ordi"
        "nal)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', ente"
        "rprise_change_verifications.value['actor_id'], 'at', enterprise_change_verifications.v"
        "alue['at'], 'text', enterprise_change_verifications.value['text'], 'result', enterpris"
        "e_change_verifications.value['fact']['result'], 'applicable_as_recorded', enterprise_c"
        "hange_verifications.value['fact']['applicable']) ORDER BY enterprise_change_verificati"
        'ons.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce('
        "enterprise_change_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY"
        " AS enterprise_change_verifications(value, ordinal)), 'closure', jsonb_build_object('t"
        "ext', enterprise_change_orders.value['closure']['text'], 'actor_id', enterprise_change"
        "_orders.value['closure']['actor_id'], 'at', enterprise_change_orders.value['closure']["
        "'at'])) ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesce_1"
        ' \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.request_snapsho'
        "t['orders']) WITH ORDINALITY AS enterprise_change_orders(value, ordinal))), 'source_re"
        "fs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpris"
        "e_reads_change.value['artifact_id'], 'version', enterprise_reads_change.value['expecte"
        "d_revision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', enterprise_rea"
        "ds_change.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM js"
        'onb_array_elements(shared_enterprise_change_request_versions.required_source_read_set)'
        " AS enterprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content"
        "_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_change_request_vers"
        "ions.change_id, 'kind', 'change', 'facts', jsonb_build_object('id', shared_enterprise_"
        "change_request_versions.request_snapshot['id'], 'title', shared_enterprise_change_requ"
        "est_versions.request_snapshot['title'], 'reason', shared_enterprise_change_request_ver"
        "sions.request_snapshot['reason'], 'status', shared_enterprise_change_request_versions."
        "request_snapshot['status'], 'needs_recheck', shared_enterprise_change_request_versions"
        ".request_snapshot['needs_recheck'], 'recheck_reasons', shared_enterprise_change_reques"
        "t_versions.request_snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELEC"
        "T coalesce(jsonb_agg(jsonb_build_object('id', enterprise_change_orders.value['id'], 'p"
        "lan_items', (SELECT coalesce(jsonb_agg(jsonb_build_object('id', enterprise_change_item"
        "s.value['id'], 'discipline', enterprise_change_items.value['discipline'], 'verificatio"
        "n_requirement', enterprise_change_items.value['verification_requirement'], 'intent_kin"
        "d', enterprise_change_items.value['intent']['kind']) ORDER BY enterprise_change_items."
        'ordinal), jsonb_build_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(ente'
        "rprise_change_orders.value['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS "
        "enterprise_change_items(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(json"
        "b_build_object('actor_id', enterprise_change_approvals.value['actor_id'], 'at', enterp"
        "rise_change_approvals.value['at'], 'discipline', enterprise_change_approvals.value['di"
        "scipline'], 'text', enterprise_change_approvals.value['text']) ORDER BY enterprise_cha"
        'nge_approvals.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements'
        "(coalesce(enterprise_change_orders.value['approvals'], CAST('[]' AS JSONB))) WITH ORDI"
        "NALITY AS enterprise_change_approvals(value, ordinal)), 'implementations', (SELECT coa"
        "lesce(jsonb_agg(jsonb_build_object('item_id', enterprise_change_implementations.value["
        "'item_id'], 'executor_id', enterprise_change_implementations.value['executor_id'], 'ou"
        "tcome', enterprise_change_implementations.value['outcome'], 'occurred_at', enterprise_"
        "change_implementations.value['occurred_at'], 'received_at', enterprise_change_implemen"
        "tations.value['received_at'], 'note', enterprise_change_implementations.value['note'])"
        ' ORDER BY enterprise_change_implementations.ordinal), jsonb_build_array()) AS coalesce'
        "_4 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['implementation"
        "s'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_implementations(value,"
        " ordinal)), 'effectivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', en"
        "terprise_change_effectivity.value['item_id'], 'stage', enterprise_change_effectivity.v"
        "alue['stage'], 'outcome', enterprise_change_effectivity.value['outcome'], 'covered_uni"
        "ts', enterprise_change_effectivity.value['covered_units'], 'occurred_at', enterprise_c"
        "hange_effectivity.value['occurred_at'], 'received_at', enterprise_change_effectivity.v"
        "alue['received_at']) ORDER BY enterprise_change_effectivity.ordinal), jsonb_build_arra"
        'y()) AS coalesce_5 \nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value'
        "['effectivity'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivit"
        "y(value, ordinal)), 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('ac"
        "tor_id', enterprise_change_verifications.value['actor_id'], 'at', enterprise_change_ve"
        "rifications.value['at'], 'text', enterprise_change_verifications.value['text'], 'resul"
        "t', enterprise_change_verifications.value['fact']['result'], 'applicable_as_recorded',"
        " enterprise_change_verifications.value['fact']['applicable']) ORDER BY enterprise_chan"
        'ge_verifications.ordinal), jsonb_build_array()) AS coalesce_6 \nFROM jsonb_array_eleme'
        "nts(coalesce(enterprise_change_orders.value['verifications'], CAST('[]' AS JSONB))) WI"
        "TH ORDINALITY AS enterprise_change_verifications(value, ordinal)), 'closure', jsonb_bu"
        "ild_object('text', enterprise_change_orders.value['closure']['text'], 'actor_id', ente"
        "rprise_change_orders.value['closure']['actor_id'], 'at', enterprise_change_orders.valu"
        "e['closure']['at'])) ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) "
        'AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.re'
        "quest_snapshot['orders']) WITH ORDINALITY AS enterprise_change_orders(value, ordinal))"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'i"
        "d', enterprise_reads_change.value['artifact_id'], 'version', enterprise_reads_change.v"
        "alue['expected_revision']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', e"
        "nterprise_reads_change.value ->> 'expected_revision'), jsonb_build_array()) AS coalesc"
        'e_7 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.required_sou'
        "rce_read_set) AS enterprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(js"
        "onb_build_object('object_id', shared_enterprise_change_request_versions.change_id, 'ki"
        "nd', 'change', 'facts', jsonb_build_object('id', shared_enterprise_change_request_vers"
        "ions.request_snapshot['id'], 'title', shared_enterprise_change_request_versions.reques"
        "t_snapshot['title'], 'reason', shared_enterprise_change_request_versions.request_snaps"
        "hot['reason'], 'status', shared_enterprise_change_request_versions.request_snapshot['s"
        "tatus'], 'needs_recheck', shared_enterprise_change_request_versions.request_snapshot['"
        "needs_recheck'], 'recheck_reasons', shared_enterprise_change_request_versions.request_"
        "snapshot['recheck_reasons']) || jsonb_build_object('orders', (SELECT coalesce(jsonb_ag"
        "g(jsonb_build_object('id', enterprise_change_orders.value['id'], 'plan_items', (SELECT"
        " coalesce(jsonb_agg(jsonb_build_object('id', enterprise_change_items.value['id'], 'dis"
        "cipline', enterprise_change_items.value['discipline'], 'verification_requirement', ent"
        "erprise_change_items.value['verification_requirement'], 'intent_kind', enterprise_chan"
        "ge_items.value['intent']['kind']) ORDER BY enterprise_change_items.ordinal), jsonb_bui"
        'ld_array()) AS coalesce_2 \nFROM jsonb_array_elements(coalesce(enterprise_change_order'
        "s.value['plan']['items'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_i"
        "tems(value, ordinal)), 'approvals', (SELECT coalesce(jsonb_agg(jsonb_build_object('act"
        "or_id', enterprise_change_approvals.value['actor_id'], 'at', enterprise_change_approva"
        "ls.value['at'], 'discipline', enterprise_change_approvals.value['discipline'], 'text',"
        " enterprise_change_approvals.value['text']) ORDER BY enterprise_change_approvals.ordin"
        'al), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_array_elements(coalesce(enterpris'
        "e_change_orders.value['approvals'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterpris"
        "e_change_approvals(value, ordinal)), 'implementations', (SELECT coalesce(jsonb_agg(jso"
        "nb_build_object('item_id', enterprise_change_implementations.value['item_id'], 'execut"
        "or_id', enterprise_change_implementations.value['executor_id'], 'outcome', enterprise_"
        "change_implementations.value['outcome'], 'occurred_at', enterprise_change_implementati"
        "ons.value['occurred_at'], 'received_at', enterprise_change_implementations.value['rece"
        "ived_at'], 'note', enterprise_change_implementations.value['note']) ORDER BY enterpris"
        'e_change_implementations.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jsonb_arr'
        "ay_elements(coalesce(enterprise_change_orders.value['implementations'], CAST('[]' AS J"
        "SONB))) WITH ORDINALITY AS enterprise_change_implementations(value, ordinal)), 'effect"
        "ivity', (SELECT coalesce(jsonb_agg(jsonb_build_object('item_id', enterprise_change_eff"
        "ectivity.value['item_id'], 'stage', enterprise_change_effectivity.value['stage'], 'out"
        "come', enterprise_change_effectivity.value['outcome'], 'covered_units', enterprise_cha"
        "nge_effectivity.value['covered_units'], 'occurred_at', enterprise_change_effectivity.v"
        "alue['occurred_at'], 'received_at', enterprise_change_effectivity.value['received_at']"
        ') ORDER BY enterprise_change_effectivity.ordinal), jsonb_build_array()) AS coalesce_5 '
        "\nFROM jsonb_array_elements(coalesce(enterprise_change_orders.value['effectivity'], CA"
        "ST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_change_effectivity(value, ordinal)),"
        " 'verifications', (SELECT coalesce(jsonb_agg(jsonb_build_object('actor_id', enterprise"
        "_change_verifications.value['actor_id'], 'at', enterprise_change_verifications.value['"
        "at'], 'text', enterprise_change_verifications.value['text'], 'result', enterprise_chan"
        "ge_verifications.value['fact']['result'], 'applicable_as_recorded', enterprise_change_"
        "verifications.value['fact']['applicable']) ORDER BY enterprise_change_verifications.or"
        'dinal), jsonb_build_array()) AS coalesce_6 \nFROM jsonb_array_elements(coalesce(enterp'
        "rise_change_orders.value['verifications'], CAST('[]' AS JSONB))) WITH ORDINALITY AS en"
        "terprise_change_verifications(value, ordinal)), 'closure', jsonb_build_object('text', "
        "enterprise_change_orders.value['closure']['text'], 'actor_id', enterprise_change_order"
        "s.value['closure']['actor_id'], 'at', enterprise_change_orders.value['closure']['at'])"
        ') ORDER BY enterprise_change_orders.ordinal), jsonb_build_array()) AS coalesce_1 \nFRO'
        "M jsonb_array_elements(shared_enterprise_change_request_versions.request_snapshot['ord"
        "ers']) WITH ORDINALITY AS enterprise_change_orders(value, ordinal))), 'source_refs', ("
        "SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_read"
        "s_change.value['artifact_id'], 'version', enterprise_reads_change.value['expected_revi"
        "sion']) ORDER BY enterprise_reads_change.value ->> 'artifact_id', enterprise_reads_cha"
        "nge.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_ar"
        'ray_elements(shared_enterprise_change_request_versions.required_source_read_set) AS en'
        "terprise_reads_change(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, shar"
        "ed_enterprise_change_request_versions.visibility != 'category' OR shared_enterprise_pr"
        "ojects.visibility != 'category' OR shared_enterprise_products.visibility != 'category'"
        ' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_change_request_ver'
        'sions.required_source_read_set) AS enterprise_reads_change(value) JOIN enterprise_auth'
        'oritative_artifacts_change ON enterprise_authoritative_artifacts_change.tenant_id = sh'
        'ared_enterprise_change_request_versions.tenant_id AND enterprise_authoritative_artifac'
        "ts_change.source_id = CAST((enterprise_reads_change.value ->> 'artifact_id') AS UUID) "
        '\nWHERE enterprise_authoritative_artifacts_change.private)) AS private, EXISTS (SELECT'
        ' 1 \nFROM jsonb_array_elements(shared_enterprise_change_request_versions.required_sour'
        'ce_read_set) AS enterprise_reads_change(value) JOIN enterprise_authoritative_artifacts'
        '_change ON enterprise_authoritative_artifacts_change.tenant_id = shared_enterprise_cha'
        'nge_request_versions.tenant_id AND enterprise_authoritative_artifacts_change.source_id'
        " = CAST((enterprise_reads_change.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_"
        'authoritative_artifacts_change.customer_original) AS customer_original, shared_enterpr'
        'ise_change_request_currents.version_id = shared_enterprise_change_request_versions.id '
        'AS is_current, shared_enterprise_change_request_versions.created_at AS created_at, CAS'
        'T(NULL AS UUID) AS original_id, shared_enterprise_change_request_versions.change_id AS'
        ' object_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_change.origi'
        'nal_id), ARRAY[]::UUID[]) AS coalesce_8 \nFROM jsonb_array_elements(shared_enterprise_'
        'change_request_versions.required_source_read_set) AS enterprise_reads_change(value) JO'
        'IN enterprise_authoritative_artifacts_change ON enterprise_authoritative_artifacts_cha'
        'nge.tenant_id = shared_enterprise_change_request_versions.tenant_id AND enterprise_aut'
        "horitative_artifacts_change.source_id = CAST((enterprise_reads_change.value ->> 'artif"
        "act_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_change.original_id IS NOT"
        ' NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared'
        '_enterprise_change_request_versions.required_source_read_set) AS enterprise_reads_chan'
        'ge(value) JOIN enterprise_authoritative_artifacts_change ON enterprise_authoritative_a'
        'rtifacts_change.tenant_id = shared_enterprise_change_request_versions.tenant_id AND en'
        'terprise_authoritative_artifacts_change.source_id = CAST((enterprise_reads_change.valu'
        "e ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_change.source"
        "_revision != CAST((enterprise_reads_change.value ->> 'expected_revision') AS INTEGER))"
        ") THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterpris"
        'e_change_request_versions JOIN shared_enterprise_projects ON shared_enterprise_project'
        's.tenant_id = shared_enterprise_change_request_versions.tenant_id AND shared_enterpris'
        'e_projects.product_id = shared_enterprise_change_request_versions.product_id AND share'
        'd_enterprise_projects.id = shared_enterprise_change_request_versions.project_id AND sh'
        'ared_enterprise_projects.category_id = shared_enterprise_change_request_versions.categ'
        'ory_id JOIN shared_enterprise_products ON shared_enterprise_products.tenant_id = share'
        'd_enterprise_change_request_versions.tenant_id AND shared_enterprise_products.id = sha'
        'red_enterprise_change_request_versions.product_id AND shared_enterprise_products.categ'
        'ory_id = shared_enterprise_change_request_versions.category_id JOIN shared_enterprise_'
        'change_request_currents ON shared_enterprise_change_request_currents.tenant_id = share'
        'd_enterprise_change_request_versions.tenant_id AND shared_enterprise_change_request_cu'
        'rrents.product_id = shared_enterprise_change_request_versions.product_id AND shared_en'
        'terprise_change_request_currents.change_id = shared_enterprise_change_request_versions'
        '.change_id \nWHERE shared_enterprise_change_request_versions.tenant_id = CAST(nullif(c'
        "urrent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM "
        'jsonb_array_elements(shared_enterprise_change_request_versions.required_source_read_se'
        't) AS enterprise_reads_change(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_a'
        'uthoritative_artifacts_change \nWHERE enterprise_authoritative_artifacts_change.tenant'
        '_id = shared_enterprise_change_request_versions.tenant_id AND enterprise_authoritative'
        "_artifacts_change.source_id = CAST((enterprise_reads_change.value ->> 'artifact_id') A"
        'S UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_change '
        '\nWHERE authoritative_enterprise_sources_change.tenant_id = t AND authoritative_enterp'
        'rise_sources_change.category_id = c AND CAST(authoritative_enterprise_sources_change.s'
        "ource_id AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sources_c"
        "hange.source_revision AS TEXT) = expected->>'source_revision' AND authoritative_enterp"
        "rise_sources_change.content_hash = expected->>'content_hash') AS anon_1 INTO visible;"
        "\n WHEN 'external_wait' THEN\n  WITH enterprise_authoritative_artifacts_external_wait "
        "AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS source_id, artifact_ve"
        'rsions.tenant_id AS tenant_id, artifact_versions.category_id AS category_id, artifact_'
        'versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID'
        ') AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision A'
        'S source_revision, artifact_versions.title AS title, artifact_versions.content_hash AS'
        " content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, '"
        "untrusted' AS nature, artifact_versions.visibility != 'category' OR coalesce(products."
        "visibility != 'category', false) OR coalesce(uploaded_originals.visibility != 'categor"
        "y', false) AS private, artifact_versions.original_id IS NOT NULL AS customer_original,"
        ' true AS is_current, artifact_versions.created_at AS created_at, artifact_versions.ori'
        'ginal_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versio'
        'ns.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UU'
        "ID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT"
        ' OUTER JOIN products ON products.tenant_id = artifact_versions.tenant_id AND products.'
        'id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_origi'
        'nals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id = artifact_vers'
        'ions.original_id AND uploaded_originals.category_id = artifact_versions.category_id AN'
        'D uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT'
        ' OUTER JOIN original_security ON original_security.tenant_id = uploaded_originals.tena'
        'nt_id AND original_security.original_id = uploaded_originals.id \nWHERE artifact_versi'
        "ons.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND "
        "artifact_versions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND "
        '(artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifact_versio'
        'ns.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.sta'
        "tus = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_security.sour"
        "ce_state = 'active' AND original_security.disposition = 'active' AND original_security"
        '.current_request_id IS NOT NULL)), \nshared_enterprise_external_wait_versions AS MATER'
        'IALIZED \n(SELECT external_wait_versions.wait_id AS wait_id, external_wait_versions.pr'
        'evious_id AS previous_id, external_wait_versions.previous_revision AS previous_revisio'
        'n, external_wait_versions.action AS action, external_wait_versions.state AS state, ext'
        'ernal_wait_versions.revision AS revision, external_wait_versions.writer_id AS writer_i'
        'd, external_wait_versions.actor_id AS actor_id, external_wait_versions.requester_id AS'
        ' requester_id, external_wait_versions.operation AS operation, external_wait_versions.c'
        'ommand_id AS command_id, external_wait_versions.command AS command, external_wait_vers'
        'ions.sources AS sources, external_wait_versions.reads AS reads, external_wait_versions'
        '.source_basis AS source_basis, external_wait_versions.body AS body, external_wait_vers'
        'ions.body_sha256 AS body_sha256, external_wait_versions.intent_digest AS intent_digest'
        ', external_wait_versions.request_digest AS request_digest, external_wait_versions.rece'
        'ipt_id AS receipt_id, external_wait_versions.confirmation_id AS confirmation_id, exter'
        'nal_wait_versions.product_id AS product_id, external_wait_versions.project_id AS proje'
        'ct_id, external_wait_versions.owner_id AS owner_id, external_wait_versions.visibility '
        'AS visibility, external_wait_versions.id AS id, external_wait_versions.tenant_id AS te'
        'nant_id, external_wait_versions.created_at AS created_at, external_wait_versions.categ'
        'ory_id AS category_id \nFROM external_wait_versions \nWHERE external_wait_versions.ten'
        "ant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_"
        'enterprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, proje'
        'cts.owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, projects'
        '.scope AS scope, projects.visibility AS visibility, projects.status AS status, project'
        's.revision AS revision, projects.current_plan_id AS current_plan_id, projects.trigger_'
        'type AS trigger_type, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0'
        '_decision_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.created_at '
        'AS created_at, projects.category_id AS category_id \nFROM projects \nWHERE projects.te'
        "nant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared"
        '_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpose'
        ' AS purpose, products.revision AS revision, products.lifecycle_epoch AS lifecycle_epoc'
        'h, products.status AS status, products.owner_id AS owner_id, products.parent_product_i'
        'd AS parent_product_id, products.category_id AS category_id, products.visibility AS vi'
        'sibility, products.target_price AS target_price, products.target_price_currency AS tar'
        'get_price_currency, products.target_price_basis AS target_price_basis, products.target'
        '_price_includes_tax AS target_price_includes_tax, products.target_price_as_of AS targe'
        't_price_as_of, products.id AS id, products.tenant_id AS tenant_id, products.created_at'
        ' AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_settin'
        "g('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_external_wait_currents A"
        'S MATERIALIZED \n(SELECT external_wait_currents.wait_id AS wait_id, external_wait_curr'
        'ents.version_id AS version_id, external_wait_currents.revision AS revision, external_w'
        'ait_currents.state AS state, external_wait_currents.product_id AS product_id, external'
        '_wait_currents.project_id AS project_id, external_wait_currents.owner_id AS owner_id, '
        'external_wait_currents.visibility AS visibility, external_wait_currents.id AS id, exte'
        'rnal_wait_currents.tenant_id AS tenant_id, external_wait_currents.created_at AS create'
        'd_at, external_wait_currents.category_id AS category_id \nFROM external_wait_currents '
        "\nWHERE external_wait_currents.tenant_id = CAST(nullif(current_setting('pdos.tenant_id"
        "', true), '') AS UUID)), \nauthoritative_enterprise_sources_external_wait AS \n(SELECT"
        " 'external_wait' AS source_type, shared_enterprise_external_wait_versions.id AS source"
        '_id, shared_enterprise_external_wait_versions.tenant_id AS tenant_id, shared_enterpris'
        'e_external_wait_versions.category_id AS category_id, shared_enterprise_external_wait_v'
        'ersions.product_id AS product_id, shared_enterprise_external_wait_versions.project_id '
        'AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_external_wait_vers'
        'ions.owner_id AS owner_id, shared_enterprise_external_wait_versions.revision AS source'
        "_revision, shared_enterprise_external_wait_versions.body ->> 'title' AS title, encode("
        "sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_external"
        "_wait_versions.wait_id, 'kind', 'external_wait', 'facts', jsonb_build_object('wait', j"
        "sonb_build_object('wait_id', shared_enterprise_external_wait_versions.body['wait_id'],"
        " 'revision', shared_enterprise_external_wait_versions.body['revision'], 'state', share"
        "d_enterprise_external_wait_versions.body['state'], 'responsible_id', shared_enterprise"
        "_external_wait_versions.body['responsible_id'], 'title', shared_enterprise_external_wa"
        "it_versions.body['title'], 'target', shared_enterprise_external_wait_versions.body['ta"
        "rget'], 'request_content', shared_enterprise_external_wait_versions.body['request_cont"
        "ent'], 'closure_condition', shared_enterprise_external_wait_versions.body['closure_con"
        "dition'], 'blocking', shared_enterprise_external_wait_versions.body['blocking'], 'next"
        "_check_at', shared_enterprise_external_wait_versions.body['next_check_at'], 'original_"
        "timezone', shared_enterprise_external_wait_versions.body['original_timezone']), 'deliv"
        "ery', jsonb_build_object('at', shared_enterprise_external_wait_versions.body['delivery"
        "']['at'], 'status', shared_enterprise_external_wait_versions.body['delivery']['status'"
        "], 'time_basis', shared_enterprise_external_wait_versions.body['delivery']['time_basis"
        "']), 'commitment', jsonb_build_object('promised_at', shared_enterprise_external_wait_v"
        "ersions.body['counterparty_commitment']['promised_at'], 'original_timezone', shared_en"
        "terprise_external_wait_versions.body['counterparty_commitment']['original_timezone']),"
        " 'reply', jsonb_build_object('at', shared_enterprise_external_wait_versions.body['repl"
        "y']['at'], 'status', shared_enterprise_external_wait_versions.body['reply']['status'],"
        " 'time_basis', shared_enterprise_external_wait_versions.body['reply']['time_basis'])),"
        " 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id'"
        ", enterprise_reads_external_wait.value['artifact_id'], 'version', enterprise_reads_ext"
        "ernal_wait.value['expected_revision']) ORDER BY enterprise_reads_external_wait.value -"
        ">> 'artifact_id', enterprise_reads_external_wait.value ->> 'expected_revision'), jsonb"
        '_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_w'
        "ait_versions.reads) AS enterprise_reads_external_wait(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT"
        "), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', shared_"
        "enterprise_external_wait_versions.wait_id, 'kind', 'external_wait', 'facts', jsonb_bui"
        "ld_object('wait', jsonb_build_object('wait_id', shared_enterprise_external_wait_versio"
        "ns.body['wait_id'], 'revision', shared_enterprise_external_wait_versions.body['revisio"
        "n'], 'state', shared_enterprise_external_wait_versions.body['state'], 'responsible_id'"
        ", shared_enterprise_external_wait_versions.body['responsible_id'], 'title', shared_ent"
        "erprise_external_wait_versions.body['title'], 'target', shared_enterprise_external_wai"
        "t_versions.body['target'], 'request_content', shared_enterprise_external_wait_versions"
        ".body['request_content'], 'closure_condition', shared_enterprise_external_wait_version"
        "s.body['closure_condition'], 'blocking', shared_enterprise_external_wait_versions.body"
        "['blocking'], 'next_check_at', shared_enterprise_external_wait_versions.body['next_che"
        "ck_at'], 'original_timezone', shared_enterprise_external_wait_versions.body['original_"
        "timezone']), 'delivery', jsonb_build_object('at', shared_enterprise_external_wait_vers"
        "ions.body['delivery']['at'], 'status', shared_enterprise_external_wait_versions.body['"
        "delivery']['status'], 'time_basis', shared_enterprise_external_wait_versions.body['del"
        "ivery']['time_basis']), 'commitment', jsonb_build_object('promised_at', shared_enterpr"
        "ise_external_wait_versions.body['counterparty_commitment']['promised_at'], 'original_t"
        "imezone', shared_enterprise_external_wait_versions.body['counterparty_commitment']['or"
        "iginal_timezone']), 'reply', jsonb_build_object('at', shared_enterprise_external_wait_"
        "versions.body['reply']['at'], 'status', shared_enterprise_external_wait_versions.body["
        "'reply']['status'], 'time_basis', shared_enterprise_external_wait_versions.body['reply"
        "']['time_basis'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type"
        "', 'artifact', 'id', enterprise_reads_external_wait.value['artifact_id'], 'version', e"
        "nterprise_reads_external_wait.value['expected_revision']) ORDER BY enterprise_reads_ex"
        "ternal_wait.value ->> 'artifact_id', enterprise_reads_external_wait.value ->> 'expecte"
        "d_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_en"
        "terprise_external_wait_versions.reads) AS enterprise_reads_external_wait(value)), 'rec"
        "ord_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        "\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JS"
        "ONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enterprise_external"
        "_wait_versions.wait_id, 'kind', 'external_wait', 'facts', jsonb_build_object('wait', j"
        "sonb_build_object('wait_id', shared_enterprise_external_wait_versions.body['wait_id'],"
        " 'revision', shared_enterprise_external_wait_versions.body['revision'], 'state', share"
        "d_enterprise_external_wait_versions.body['state'], 'responsible_id', shared_enterprise"
        "_external_wait_versions.body['responsible_id'], 'title', shared_enterprise_external_wa"
        "it_versions.body['title'], 'target', shared_enterprise_external_wait_versions.body['ta"
        "rget'], 'request_content', shared_enterprise_external_wait_versions.body['request_cont"
        "ent'], 'closure_condition', shared_enterprise_external_wait_versions.body['closure_con"
        "dition'], 'blocking', shared_enterprise_external_wait_versions.body['blocking'], 'next"
        "_check_at', shared_enterprise_external_wait_versions.body['next_check_at'], 'original_"
        "timezone', shared_enterprise_external_wait_versions.body['original_timezone']), 'deliv"
        "ery', jsonb_build_object('at', shared_enterprise_external_wait_versions.body['delivery"
        "']['at'], 'status', shared_enterprise_external_wait_versions.body['delivery']['status'"
        "], 'time_basis', shared_enterprise_external_wait_versions.body['delivery']['time_basis"
        "']), 'commitment', jsonb_build_object('promised_at', shared_enterprise_external_wait_v"
        "ersions.body['counterparty_commitment']['promised_at'], 'original_timezone', shared_en"
        "terprise_external_wait_versions.body['counterparty_commitment']['original_timezone']),"
        " 'reply', jsonb_build_object('at', shared_enterprise_external_wait_versions.body['repl"
        "y']['at'], 'status', shared_enterprise_external_wait_versions.body['reply']['status'],"
        " 'time_basis', shared_enterprise_external_wait_versions.body['reply']['time_basis'])),"
        " 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id'"
        ", enterprise_reads_external_wait.value['artifact_id'], 'version', enterprise_reads_ext"
        "ernal_wait.value['expected_revision']) ORDER BY enterprise_reads_external_wait.value -"
        ">> 'artifact_id', enterprise_reads_external_wait.value ->> 'expected_revision'), jsonb"
        '_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterprise_external_w'
        "ait_versions.reads) AS enterprise_reads_external_wait(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS stru"
        "ctured, 'structured' AS nature, shared_enterprise_external_wait_versions.visibility !="
        " 'category' OR shared_enterprise_projects.visibility != 'category' OR shared_enterpris"
        "e_products.visibility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(s"
        'hared_enterprise_external_wait_versions.reads) AS enterprise_reads_external_wait(value'
        ') JOIN enterprise_authoritative_artifacts_external_wait ON enterprise_authoritative_ar'
        'tifacts_external_wait.tenant_id = shared_enterprise_external_wait_versions.tenant_id A'
        'ND enterprise_authoritative_artifacts_external_wait.source_id = CAST((enterprise_reads'
        "_external_wait.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_arti"
        'facts_external_wait.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements'
        '(shared_enterprise_external_wait_versions.reads) AS enterprise_reads_external_wait(val'
        'ue) JOIN enterprise_authoritative_artifacts_external_wait ON enterprise_authoritative_'
        'artifacts_external_wait.tenant_id = shared_enterprise_external_wait_versions.tenant_id'
        ' AND enterprise_authoritative_artifacts_external_wait.source_id = CAST((enterprise_rea'
        "ds_external_wait.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_ar"
        'tifacts_external_wait.customer_original) AS customer_original, shared_enterprise_exter'
        'nal_wait_currents.version_id = shared_enterprise_external_wait_versions.id AS is_curre'
        'nt, shared_enterprise_external_wait_versions.created_at AS created_at, CAST(NULL AS UU'
        'ID) AS original_id, shared_enterprise_external_wait_versions.wait_id AS object_id, (SE'
        'LECT coalesce(array_agg(enterprise_authoritative_artifacts_external_wait.original_id),'
        ' ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_external'
        '_wait_versions.reads) AS enterprise_reads_external_wait(value) JOIN enterprise_authori'
        'tative_artifacts_external_wait ON enterprise_authoritative_artifacts_external_wait.ten'
        'ant_id = shared_enterprise_external_wait_versions.tenant_id AND enterprise_authoritati'
        've_artifacts_external_wait.source_id = CAST((enterprise_reads_external_wait.value ->> '
        "'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_external_wait.origi"
        'nal_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_el'
        'ements(shared_enterprise_external_wait_versions.reads) AS enterprise_reads_external_wa'
        'it(value) JOIN enterprise_authoritative_artifacts_external_wait ON enterprise_authorit'
        'ative_artifacts_external_wait.tenant_id = shared_enterprise_external_wait_versions.ten'
        'ant_id AND enterprise_authoritative_artifacts_external_wait.source_id = CAST((enterpri'
        "se_reads_external_wait.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritat"
        'ive_artifacts_external_wait.source_revision != CAST((enterprise_reads_external_wait.va'
        "lue ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS "
        'read_basis_status \nFROM shared_enterprise_external_wait_versions JOIN shared_enterpri'
        'se_projects ON shared_enterprise_projects.tenant_id = shared_enterprise_external_wait_'
        'versions.tenant_id AND shared_enterprise_projects.product_id = shared_enterprise_exter'
        'nal_wait_versions.product_id AND shared_enterprise_projects.id = shared_enterprise_ext'
        'ernal_wait_versions.project_id AND shared_enterprise_projects.category_id = shared_ent'
        'erprise_external_wait_versions.category_id JOIN shared_enterprise_products ON shared_e'
        'nterprise_products.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND '
        'shared_enterprise_products.id = shared_enterprise_external_wait_versions.product_id AN'
        'D shared_enterprise_products.category_id = shared_enterprise_external_wait_versions.ca'
        'tegory_id JOIN shared_enterprise_external_wait_currents ON shared_enterprise_external_'
        'wait_currents.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND share'
        'd_enterprise_external_wait_currents.product_id = shared_enterprise_external_wait_versi'
        'ons.product_id AND shared_enterprise_external_wait_currents.wait_id = shared_enterpris'
        'e_external_wait_versions.wait_id \nWHERE shared_enterprise_external_wait_versions.tena'
        "nt_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXI"
        'STS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_external_wait_versions.rea'
        'ds) AS enterprise_reads_external_wait(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM ente'
        'rprise_authoritative_artifacts_external_wait \nWHERE enterprise_authoritative_artifact'
        's_external_wait.tenant_id = shared_enterprise_external_wait_versions.tenant_id AND ent'
        'erprise_authoritative_artifacts_external_wait.source_id = CAST((enterprise_reads_exter'
        "nal_wait.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM autho"
        'ritative_enterprise_sources_external_wait \nWHERE authoritative_enterprise_sources_ext'
        'ernal_wait.tenant_id = t AND authoritative_enterprise_sources_external_wait.category_i'
        'd = c AND CAST(authoritative_enterprise_sources_external_wait.source_id AS TEXT) = exp'
        "ected->>'source_id' AND CAST(authoritative_enterprise_sources_external_wait.source_rev"
        "ision AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_sources_ext"
        "ernal_wait.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN 's"
        "upply' THEN\n  WITH enterprise_authoritative_artifacts_supply AS \n(SELECT 'artifact' "
        'AS source_type, artifact_versions.id AS source_id, artifact_versions.tenant_id AS tena'
        'nt_id, artifact_versions.category_id AS category_id, artifact_versions.product_id AS p'
        'roduct_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID) AS proposal_id, artifa'
        'ct_versions.owner_id AS owner_id, artifact_versions.revision AS source_revision, artif'
        'act_versions.title AS title, artifact_versions.content_hash AS content_hash, artifact_'
        "versions.content AS body, CAST(NULL AS JSONB) AS structured, 'untrusted' AS nature, ar"
        "tifact_versions.visibility != 'category' OR coalesce(products.visibility != 'category'"
        ", false) OR coalesce(uploaded_originals.visibility != 'category', false) AS private, a"
        'rtifact_versions.original_id IS NOT NULL AS customer_original, true AS is_current, art'
        'ifact_versions.created_at AS created_at, artifact_versions.original_id AS original_id,'
        ' artifact_versions.id AS object_id, CASE WHEN (artifact_versions.original_id IS NOT NU'
        'LL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UUID[] END AS original_ids'
        ", 'current' AS read_basis_status \nFROM artifact_versions LEFT OUTER JOIN products ON "
        'products.tenant_id = artifact_versions.tenant_id AND products.id = artifact_versions.p'
        'roduct_id LEFT OUTER JOIN uploaded_originals ON uploaded_originals.tenant_id = artifac'
        't_versions.tenant_id AND uploaded_originals.id = artifact_versions.original_id AND upl'
        'oaded_originals.category_id = artifact_versions.category_id AND uploaded_originals.pro'
        'duct_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT OUTER JOIN original_sec'
        'urity ON original_security.tenant_id = uploaded_originals.tenant_id AND original_secur'
        'ity.original_id = uploaded_originals.id \nWHERE artifact_versions.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID) AND artifact_versions.status"
        " = 'active' AND artifact_versions.category_id IS NOT NULL AND (artifact_versions.produ"
        'ct_id IS NULL OR products.id IS NOT NULL) AND (artifact_versions.original_id IS NULL O'
        "R uploaded_originals.id IS NOT NULL AND uploaded_originals.status = 'parsed' AND uploa"
        "ded_originals.scan_status = 'clean' AND original_security.source_state = 'active' AND "
        "original_security.disposition = 'active' AND original_security.current_request_id IS N"
        'OT NULL)), \nshared_enterprise_supply_snapshots AS MATERIALIZED \n(SELECT supply_snaps'
        'hots.revision AS revision, supply_snapshots.status AS status, supply_snapshots.capture'
        '_id AS capture_id, supply_snapshots.previous_snapshot_id AS previous_snapshot_id, supp'
        'ly_snapshots.previous_revision AS previous_revision, supply_snapshots.snapshot AS snap'
        'shot, supply_snapshots.snapshot_sha256 AS snapshot_sha256, supply_snapshots.bound_dema'
        'nd AS bound_demand, supply_snapshots.reconciliation AS reconciliation, supply_snapshot'
        's.sources AS sources, supply_snapshots.product_id AS product_id, supply_snapshots.proj'
        'ect_id AS project_id, supply_snapshots.build_id AS build_id, supply_snapshots.build_re'
        'vision AS build_revision, supply_snapshots.owner_id AS owner_id, supply_snapshots.visi'
        'bility AS visibility, supply_snapshots.reason AS reason, supply_snapshots.required_sou'
        'rce_read_set AS required_source_read_set, supply_snapshots.id AS id, supply_snapshots.'
        'tenant_id AS tenant_id, supply_snapshots.created_at AS created_at, supply_snapshots.ca'
        'tegory_id AS category_id \nFROM supply_snapshots \nWHERE supply_snapshots.tenant_id = '
        "CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpris"
        'e_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id, projects.owner'
        '_id AS owner_id, projects.name AS name, projects.purpose AS purpose, projects.scope AS'
        ' scope, projects.visibility AS visibility, projects.status AS status, projects.revisio'
        'n AS revision, projects.current_plan_id AS current_plan_id, projects.trigger_type AS t'
        'rigger_type, projects.trigger_id AS trigger_id, projects.g0_decision_id AS g0_decision'
        '_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.created_at AS create'
        'd_at, projects.category_id AS category_id \nFROM projects \nWHERE projects.tenant_id ='
        " CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterpri"
        'se_products AS MATERIALIZED \n(SELECT products.name AS name, products.purpose AS purpo'
        'se, products.revision AS revision, products.lifecycle_epoch AS lifecycle_epoch, produc'
        'ts.status AS status, products.owner_id AS owner_id, products.parent_product_id AS pare'
        'nt_product_id, products.category_id AS category_id, products.visibility AS visibility,'
        ' products.target_price AS target_price, products.target_price_currency AS target_price'
        '_currency, products.target_price_basis AS target_price_basis, products.target_price_in'
        'cludes_tax AS target_price_includes_tax, products.target_price_as_of AS target_price_a'
        's_of, products.id AS id, products.tenant_id AS tenant_id, products.created_at AS creat'
        "ed_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_setting('pdos.t"
        "enant_id', true), '') AS UUID)), \nshared_enterprise_builds AS MATERIALIZED \n(SELECT "
        'builds.product_id AS product_id, builds.project_id AS project_id, builds.project_revis'
        'ion AS project_revision, builds.engineering_configuration_id AS engineering_configurat'
        'ion_id, builds.manufacturing_configuration_id AS manufacturing_configuration_id, build'
        's.previous_build_id AS previous_build_id, builds.owner_id AS owner_id, builds.name AS '
        'name, builds.type AS type, builds.purpose AS purpose, builds.planned_quantity AS plann'
        'ed_quantity, builds.unit AS unit, builds.planned_start AS planned_start, builds.planne'
        'd_end AS planned_end, builds.verification_objectives AS verification_objectives, build'
        's.disposition_plan AS disposition_plan, builds.visibility AS visibility, builds.revisi'
        'on AS revision, builds.status AS status, builds.id AS id, builds.tenant_id AS tenant_i'
        'd, builds.created_at AS created_at, builds.category_id AS category_id \nFROM builds \n'
        "WHERE builds.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS U"
        'UID)), \nshared_enterprise_supply_current_snapshots AS MATERIALIZED \n(SELECT supply_c'
        'urrent_snapshots.product_id AS product_id, supply_current_snapshots.build_id AS build_'
        'id, supply_current_snapshots.snapshot_id AS snapshot_id, supply_current_snapshots.snap'
        'shot_revision AS snapshot_revision, supply_current_snapshots.id AS id, supply_current_'
        'snapshots.tenant_id AS tenant_id, supply_current_snapshots.created_at AS created_at, s'
        'upply_current_snapshots.category_id AS category_id \nFROM supply_current_snapshots \nW'
        "HERE supply_current_snapshots.tenant_id = CAST(nullif(current_setting('pdos.tenant_id'"
        ", true), '') AS UUID)), \nauthoritative_enterprise_sources_supply AS \n(SELECT 'supply"
        "' AS source_type, shared_enterprise_supply_snapshots.id AS source_id, shared_enterpris"
        'e_supply_snapshots.tenant_id AS tenant_id, shared_enterprise_supply_snapshots.category'
        '_id AS category_id, shared_enterprise_supply_snapshots.product_id AS product_id, share'
        'd_enterprise_supply_snapshots.project_id AS project_id, CAST(NULL AS UUID) AS proposal'
        '_id, shared_enterprise_supply_snapshots.owner_id AS owner_id, shared_enterprise_supply'
        "_snapshots.revision AS source_revision, '\u4f9b\u5e94\u627f\u8bfa \xb7 ' || CAST(share"
        'd_enterprise_supply_snapshots.build_id AS TEXT) AS title, encode(sha256(convert_to(CAS'
        "T(CAST(jsonb_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', "
        "'supply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_snapshots.b"
        "uild_id, 'status', shared_enterprise_supply_snapshots.status, 'commitments', (SELECT c"
        "oalesce(jsonb_agg(jsonb_build_object('record_id', enterprise_supply_commitments.value["
        "'record_id'], 'supplier_id', enterprise_supply_commitments.value['supplier_id'], 'mate"
        "rial_id', enterprise_supply_commitments.value['material_id'], 'quantity', enterprise_s"
        "upply_commitments.value['quantity'], 'unit', enterprise_supply_commitments.value['unit"
        "'], 'expected_at', enterprise_supply_commitments.value['expected_at']) ORDER BY enterp"
        'rise_supply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_arra'
        "y_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitments'], CAST('"
        "[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitments(value, ordinal))), 's"
        "ource_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', e"
        "nterprise_reads_supply.value['artifact_id'], 'version', enterprise_reads_supply.value["
        "'expected_revision']) ORDER BY enterprise_reads_supply.value ->> 'artifact_id', enterp"
        "rise_reads_supply.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 "
        '\nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_read_se'
        "t) AS enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS c"
        "ontent_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_supply_snapsh"
        "ots.id, 'kind', 'supply', 'facts', jsonb_build_object('build_id', shared_enterprise_su"
        "pply_snapshots.build_id, 'status', shared_enterprise_supply_snapshots.status, 'commitm"
        "ents', (SELECT coalesce(jsonb_agg(jsonb_build_object('record_id', enterprise_supply_co"
        "mmitments.value['record_id'], 'supplier_id', enterprise_supply_commitments.value['supp"
        "lier_id'], 'material_id', enterprise_supply_commitments.value['material_id'], 'quantit"
        "y', enterprise_supply_commitments.value['quantity'], 'unit', enterprise_supply_commitm"
        "ents.value['unit'], 'expected_at', enterprise_supply_commitments.value['expected_at'])"
        ' ORDER BY enterprise_supply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 '
        "\nFROM jsonb_array_elements(coalesce(shared_enterprise_supply_snapshots.snapshot['comm"
        "itments'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitments(valu"
        "e, ordinal))), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'a"
        "rtifact', 'id', enterprise_reads_supply.value['artifact_id'], 'version', enterprise_re"
        "ads_supply.value['expected_revision']) ORDER BY enterprise_reads_supply.value ->> 'art"
        "ifact_id', enterprise_reads_supply.value ->> 'expected_revision'), jsonb_build_array()"
        ') AS coalesce_2 \nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.require'
        "d_source_read_set) AS enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, C"
        "AST(jsonb_build_object('object_id', shared_enterprise_supply_snapshots.id, 'kind', 'su"
        "pply', 'facts', jsonb_build_object('build_id', shared_enterprise_supply_snapshots.buil"
        "d_id, 'status', shared_enterprise_supply_snapshots.status, 'commitments', (SELECT coal"
        "esce(jsonb_agg(jsonb_build_object('record_id', enterprise_supply_commitments.value['re"
        "cord_id'], 'supplier_id', enterprise_supply_commitments.value['supplier_id'], 'materia"
        "l_id', enterprise_supply_commitments.value['material_id'], 'quantity', enterprise_supp"
        "ly_commitments.value['quantity'], 'unit', enterprise_supply_commitments.value['unit'],"
        " 'expected_at', enterprise_supply_commitments.value['expected_at']) ORDER BY enterpris"
        'e_supply_commitments.ordinal), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_e'
        "lements(coalesce(shared_enterprise_supply_snapshots.snapshot['commitments'], CAST('[]'"
        " AS JSONB))) WITH ORDINALITY AS enterprise_supply_commitments(value, ordinal))), 'sour"
        "ce_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', ente"
        "rprise_reads_supply.value['artifact_id'], 'version', enterprise_reads_supply.value['ex"
        "pected_revision']) ORDER BY enterprise_reads_supply.value ->> 'artifact_id', enterpris"
        "e_reads_supply.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_2 \nFR"
        'OM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_read_set) A'
        "S enterprise_reads_supply(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature"
        ", shared_enterprise_supply_snapshots.visibility != 'category' OR shared_enterprise_pro"
        "jects.visibility != 'category' OR shared_enterprise_products.visibility != 'category' "
        'OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.re'
        'quired_source_read_set) AS enterprise_reads_supply(value) JOIN enterprise_authoritativ'
        'e_artifacts_supply ON enterprise_authoritative_artifacts_supply.tenant_id = shared_ent'
        'erprise_supply_snapshots.tenant_id AND enterprise_authoritative_artifacts_supply.sourc'
        "e_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_supply.private)) OR shared_enterprise_builds.visibility !='
        " 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise"
        '_supply_snapshots.required_source_read_set) AS enterprise_reads_supply(value) JOIN ent'
        'erprise_authoritative_artifacts_supply ON enterprise_authoritative_artifacts_supply.te'
        'nant_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_ar'
        "tifacts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS U"
        'UID) \nWHERE enterprise_authoritative_artifacts_supply.customer_original) AS customer_'
        'original, shared_enterprise_supply_current_snapshots.snapshot_id = shared_enterprise_s'
        'upply_snapshots.id AS is_current, shared_enterprise_supply_snapshots.created_at AS cre'
        'ated_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_supply_snapshots.id AS o'
        'bject_id, (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_supply.origina'
        'l_id), ARRAY[]::UUID[]) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_su'
        'pply_snapshots.required_source_read_set) AS enterprise_reads_supply(value) JOIN enterp'
        'rise_authoritative_artifacts_supply ON enterprise_authoritative_artifacts_supply.tenan'
        't_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_artif'
        "acts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID"
        ') \nWHERE enterprise_authoritative_artifacts_supply.original_id IS NOT NULL) AS origin'
        'al_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_supp'
        'ly_snapshots.required_source_read_set) AS enterprise_reads_supply(value) JOIN enterpri'
        'se_authoritative_artifacts_supply ON enterprise_authoritative_artifacts_supply.tenant_'
        'id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_artifac'
        "ts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID) "
        '\nWHERE enterprise_authoritative_artifacts_supply.source_revision != CAST((enterprise_'
        "reads_supply.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'c"
        "urrent' END AS read_basis_status \nFROM shared_enterprise_supply_snapshots JOIN shared"
        '_enterprise_projects ON shared_enterprise_projects.tenant_id = shared_enterprise_suppl'
        'y_snapshots.tenant_id AND shared_enterprise_projects.product_id = shared_enterprise_su'
        'pply_snapshots.product_id AND shared_enterprise_projects.id = shared_enterprise_supply'
        '_snapshots.project_id AND shared_enterprise_projects.category_id = shared_enterprise_s'
        'upply_snapshots.category_id JOIN shared_enterprise_products ON shared_enterprise_produ'
        'cts.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_enterprise_pro'
        'ducts.id = shared_enterprise_supply_snapshots.product_id AND shared_enterprise_product'
        's.category_id = shared_enterprise_supply_snapshots.category_id JOIN shared_enterprise_'
        'builds ON shared_enterprise_builds.tenant_id = shared_enterprise_supply_snapshots.tena'
        'nt_id AND shared_enterprise_builds.category_id = shared_enterprise_supply_snapshots.ca'
        'tegory_id AND shared_enterprise_builds.product_id = shared_enterprise_supply_snapshots'
        '.product_id AND shared_enterprise_builds.project_id = shared_enterprise_supply_snapsho'
        'ts.project_id AND shared_enterprise_builds.id = shared_enterprise_supply_snapshots.bui'
        'ld_id AND shared_enterprise_builds.revision = shared_enterprise_supply_snapshots.build'
        '_revision JOIN shared_enterprise_supply_current_snapshots ON shared_enterprise_supply_'
        'current_snapshots.tenant_id = shared_enterprise_supply_snapshots.tenant_id AND shared_'
        'enterprise_supply_current_snapshots.product_id = shared_enterprise_supply_snapshots.pr'
        'oduct_id AND shared_enterprise_supply_current_snapshots.build_id = shared_enterprise_s'
        'upply_snapshots.build_id \nWHERE shared_enterprise_supply_snapshots.tenant_id = CAST(n'
        "ullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 "
        '\nFROM jsonb_array_elements(shared_enterprise_supply_snapshots.required_source_read_se'
        't) AS enterprise_reads_supply(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_a'
        'uthoritative_artifacts_supply \nWHERE enterprise_authoritative_artifacts_supply.tenant'
        '_id = shared_enterprise_supply_snapshots.tenant_id AND enterprise_authoritative_artifa'
        "cts_supply.source_id = CAST((enterprise_reads_supply.value ->> 'artifact_id') AS UUID)"
        ')))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative_enterprise_sources_supply \nWHERE'
        ' authoritative_enterprise_sources_supply.tenant_id = t AND authoritative_enterprise_so'
        'urces_supply.category_id = c AND CAST(authoritative_enterprise_sources_supply.source_i'
        "d AS TEXT) = expected->>'source_id' AND CAST(authoritative_enterprise_sources_supply.s"
        "ource_revision AS TEXT) = expected->>'source_revision' AND authoritative_enterprise_so"
        "urces_supply.content_hash = expected->>'content_hash') AS anon_1 INTO visible;\n WHEN "
        "'build' THEN\n  WITH shared_enterprise_engineering_configurations AS MATERIALIZED \n(S"
        'ELECT engineering_configurations.definition_id AS definition_id, engineering_configura'
        'tions.definition_revision AS definition_revision, engineering_configurations.bom_id AS'
        ' bom_id, engineering_configurations.bom_revision AS bom_revision, engineering_configur'
        'ations.design_versions AS design_versions, engineering_configurations.series_id AS ser'
        'ies_id, engineering_configurations.previous_id AS previous_id, engineering_configurati'
        'ons.expected_previous_revision AS expected_previous_revision, engineering_configuratio'
        'ns.reason AS reason, engineering_configurations.product_id AS product_id, engineering_'
        'configurations.owner_id AS owner_id, engineering_configurations.name AS name, engineer'
        'ing_configurations.status AS status, engineering_configurations.visibility AS visibili'
        'ty, engineering_configurations.revision AS revision, engineering_configurations.source'
        's AS sources, engineering_configurations.required_source_read_set AS required_source_r'
        'ead_set, engineering_configurations.id AS id, engineering_configurations.tenant_id AS '
        'tenant_id, engineering_configurations.created_at AS created_at, engineering_configurat'
        'ions.category_id AS category_id \nFROM engineering_configurations \nWHERE engineering_'
        "configurations.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS"
        ' UUID)), \nshared_enterprise_process_revisions AS MATERIALIZED \n(SELECT process_revis'
        'ions.engineering_configuration_id AS engineering_configuration_id, process_revisions.e'
        'ngineering_revision AS engineering_revision, process_revisions.operations AS operation'
        's, process_revisions.site AS site, process_revisions.line AS line, process_revisions.s'
        'eries_id AS series_id, process_revisions.previous_id AS previous_id, process_revisions'
        '.expected_previous_revision AS expected_previous_revision, process_revisions.reason AS'
        ' reason, process_revisions.product_id AS product_id, process_revisions.owner_id AS own'
        'er_id, process_revisions.name AS name, process_revisions.status AS status, process_rev'
        'isions.visibility AS visibility, process_revisions.revision AS revision, process_revis'
        'ions.sources AS sources, process_revisions.required_source_read_set AS required_source'
        '_read_set, process_revisions.id AS id, process_revisions.tenant_id AS tenant_id, proce'
        'ss_revisions.created_at AS created_at, process_revisions.category_id AS category_id \n'
        'FROM process_revisions \nWHERE process_revisions.tenant_id = CAST(nullif(current_setti'
        "ng('pdos.tenant_id', true), '') AS UUID)), \nenterprise_authoritative_artifacts_build "
        "AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS source_id, artifact_ve"
        'rsions.tenant_id AS tenant_id, artifact_versions.category_id AS category_id, artifact_'
        'versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NULL AS UUID'
        ') AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.revision A'
        'S source_revision, artifact_versions.title AS title, artifact_versions.content_hash AS'
        " content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS structured, '"
        "untrusted' AS nature, artifact_versions.visibility != 'category' OR coalesce(products."
        "visibility != 'category', false) OR coalesce(uploaded_originals.visibility != 'categor"
        "y', false) AS private, artifact_versions.original_id IS NOT NULL AS customer_original,"
        ' true AS is_current, artifact_versions.created_at AS created_at, artifact_versions.ori'
        'ginal_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (artifact_versio'
        'ns.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE ARRAY[]::UU'
        "ID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_versions LEFT"
        ' OUTER JOIN products ON products.tenant_id = artifact_versions.tenant_id AND products.'
        'id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uploaded_origi'
        'nals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id = artifact_vers'
        'ions.original_id AND uploaded_originals.category_id = artifact_versions.category_id AN'
        'D uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.product_id LEFT'
        ' OUTER JOIN original_security ON original_security.tenant_id = uploaded_originals.tena'
        'nt_id AND original_security.original_id = uploaded_originals.id \nWHERE artifact_versi'
        "ons.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND "
        "artifact_versions.status = 'active' AND artifact_versions.category_id IS NOT NULL AND "
        '(artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artifact_versio'
        'ns.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_originals.sta'
        "tus = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_security.sour"
        "ce_state = 'active' AND original_security.disposition = 'active' AND original_security"
        '.current_request_id IS NOT NULL)), \nshared_enterprise_builds AS MATERIALIZED \n(SELEC'
        'T builds.product_id AS product_id, builds.project_id AS project_id, builds.project_rev'
        'ision AS project_revision, builds.engineering_configuration_id AS engineering_configur'
        'ation_id, builds.manufacturing_configuration_id AS manufacturing_configuration_id, bui'
        'lds.previous_build_id AS previous_build_id, builds.owner_id AS owner_id, builds.name A'
        'S name, builds.type AS type, builds.purpose AS purpose, builds.planned_quantity AS pla'
        'nned_quantity, builds.unit AS unit, builds.planned_start AS planned_start, builds.plan'
        'ned_end AS planned_end, builds.verification_objectives AS verification_objectives, bui'
        'lds.disposition_plan AS disposition_plan, builds.visibility AS visibility, builds.revi'
        'sion AS revision, builds.status AS status, builds.id AS id, builds.tenant_id AS tenant'
        '_id, builds.created_at AS created_at, builds.category_id AS category_id \nFROM builds '
        "\nWHERE builds.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS"
        ' UUID)), \nshared_enterprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS'
        ' product_id, projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS'
        ' purpose, projects.scope AS scope, projects.visibility AS visibility, projects.status '
        'AS status, projects.revision AS revision, projects.current_plan_id AS current_plan_id,'
        ' projects.trigger_type AS trigger_type, projects.trigger_id AS trigger_id, projects.g0'
        '_decision_id AS g0_decision_id, projects.id AS id, projects.tenant_id AS tenant_id, pr'
        'ojects.created_at AS created_at, projects.category_id AS category_id \nFROM projects '
        "\nWHERE projects.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') "
        'AS UUID)), \nshared_enterprise_products AS MATERIALIZED \n(SELECT products.name AS nam'
        'e, products.purpose AS purpose, products.revision AS revision, products.lifecycle_epoc'
        'h AS lifecycle_epoch, products.status AS status, products.owner_id AS owner_id, produc'
        'ts.parent_product_id AS parent_product_id, products.category_id AS category_id, produc'
        'ts.visibility AS visibility, products.target_price AS target_price, products.target_pr'
        'ice_currency AS target_price_currency, products.target_price_basis AS target_price_bas'
        'is, products.target_price_includes_tax AS target_price_includes_tax, products.target_p'
        'rice_as_of AS target_price_as_of, products.id AS id, products.tenant_id AS tenant_id, '
        'products.created_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nu'
        "llif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_build"
        '_starts AS MATERIALIZED \n(SELECT build_starts.product_id AS product_id, build_starts.'
        'project_id AS project_id, build_starts.build_id AS build_id, build_starts.build_revisi'
        'on AS build_revision, build_starts.engineering_configuration_id AS engineering_configu'
        'ration_id, build_starts.manufacturing_configuration_id AS manufacturing_configuration_'
        'id, build_starts.assessment_id AS assessment_id, build_starts.assessment_revision AS a'
        'ssessment_revision, build_starts.assessment_sha256 AS assessment_sha256, build_starts.'
        'engineering_authorization_id AS engineering_authorization_id, build_starts.engineering'
        '_authorization_revision AS engineering_authorization_revision, build_starts.manufactur'
        'ing_authorization_id AS manufacturing_authorization_id, build_starts.manufacturing_aut'
        'horization_revision AS manufacturing_authorization_revision, build_starts.engineering_'
        'role AS engineering_role, build_starts.manufacturing_role AS manufacturing_role, build'
        '_starts.revision AS revision, build_starts.owner_id AS owner_id, build_starts.visibili'
        'ty AS visibility, build_starts.status AS status, build_starts.occurred_at AS occurred_'
        'at, build_starts.occurred_timezone AS occurred_timezone, build_starts.execution_scope '
        'AS execution_scope, build_starts.event_source AS event_source, build_starts.authority_'
        'snapshot AS authority_snapshot, build_starts.reservations AS reservations, build_start'
        's.sources AS sources, build_starts.required_source_read_set AS required_source_read_se'
        't, build_starts.snapshot_sha256 AS snapshot_sha256, build_starts.intent_digest AS inte'
        'nt_digest, build_starts.reason AS reason, build_starts.id AS id, build_starts.tenant_i'
        'd AS tenant_id, build_starts.created_at AS created_at, build_starts.category_id AS cat'
        'egory_id \nFROM build_starts \nWHERE build_starts.tenant_id = CAST(nullif(current_sett'
        "ing('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_actual_configurations "
        'AS MATERIALIZED \n(SELECT actual_configurations.status AS status, actual_configuration'
        's.planned_engineering_configuration_id AS planned_engineering_configuration_id, actual'
        '_configurations.planned_manufacturing_configuration_id AS planned_manufacturing_config'
        'uration_id, actual_configurations.actual_engineering_configuration_id AS actual_engine'
        'ering_configuration_id, actual_configurations.actual_engineering_revision AS actual_en'
        'gineering_revision, actual_configurations.actual_manufacturing_configuration_id AS act'
        'ual_manufacturing_configuration_id, actual_configurations.actual_manufacturing_revisio'
        'n AS actual_manufacturing_revision, actual_configurations.observed_at AS observed_at, '
        'actual_configurations.differences AS differences, actual_configurations.product_id AS '
        'product_id, actual_configurations.project_id AS project_id, actual_configurations.buil'
        'd_id AS build_id, actual_configurations.build_revision AS build_revision, actual_confi'
        'gurations.owner_id AS owner_id, actual_configurations.visibility AS visibility, actual'
        '_configurations.revision AS revision, actual_configurations.reason AS reason, actual_c'
        'onfigurations.sources AS sources, actual_configurations.required_source_read_set AS re'
        'quired_source_read_set, actual_configurations.id AS id, actual_configurations.tenant_i'
        'd AS tenant_id, actual_configurations.created_at AS created_at, actual_configurations.'
        'category_id AS category_id \nFROM actual_configurations \nWHERE actual_configurations.'
        "tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \nshar"
        'ed_enterprise_build_lots AS MATERIALIZED \n(SELECT build_lots.status AS status, build_'
        'lots.actual_configuration_id AS actual_configuration_id, build_lots.actual_configurati'
        'on_revision AS actual_configuration_revision, build_lots.lot_label AS lot_label, build'
        '_lots.observed_unit_count AS observed_unit_count, build_lots.unit AS unit, build_lots.'
        'observation_system AS observation_system, build_lots.observation_external_id AS observ'
        'ation_external_id, build_lots.observation_nature AS observation_nature, build_lots.occ'
        'urred_at AS occurred_at, build_lots.received_at AS received_at, build_lots.product_id '
        'AS product_id, build_lots.project_id AS project_id, build_lots.build_id AS build_id, b'
        'uild_lots.build_revision AS build_revision, build_lots.owner_id AS owner_id, build_lot'
        's.visibility AS visibility, build_lots.revision AS revision, build_lots.reason AS reas'
        'on, build_lots.sources AS sources, build_lots.required_source_read_set AS required_sou'
        'rce_read_set, build_lots.id AS id, build_lots.tenant_id AS tenant_id, build_lots.creat'
        'ed_at AS created_at, build_lots.category_id AS category_id \nFROM build_lots \nWHERE b'
        "uild_lots.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID"
        ")), \nauthoritative_enterprise_sources_build AS \n(SELECT 'build' AS source_type, shar"
        'ed_enterprise_builds.id AS source_id, shared_enterprise_builds.tenant_id AS tenant_id,'
        ' shared_enterprise_builds.category_id AS category_id, shared_enterprise_builds.product'
        '_id AS product_id, shared_enterprise_builds.project_id AS project_id, CAST(NULL AS UUI'
        'D) AS proposal_id, shared_enterprise_builds.owner_id AS owner_id, shared_enterprise_bu'
        'ilds.revision AS source_revision, shared_enterprise_builds.name AS title, encode(sha25'
        "6(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_builds.id, 'k"
        "ind', 'build', 'facts', jsonb_build_object('name', shared_enterprise_builds.name, 'typ"
        "e', shared_enterprise_builds.type, 'purpose', shared_enterprise_builds.purpose, 'plann"
        "ed_quantity', shared_enterprise_builds.planned_quantity, 'unit', shared_enterprise_bui"
        "lds.unit, 'planned_start', shared_enterprise_builds.planned_start, 'planned_end', shar"
        "ed_enterprise_builds.planned_end, 'engineering_configuration_id', shared_enterprise_bu"
        "ilds.engineering_configuration_id, 'manufacturing_configuration_id', shared_enterprise"
        "_builds.manufacturing_configuration_id, 'verification_objectives', shared_enterprise_b"
        "uilds.verification_objectives, 'plan_status', shared_enterprise_builds.status), 'sourc"
        "e_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enter"
        "prise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_re"
        "ads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM js"
        'onb_array_elements((SELECT shared_enterprise_engineering_configurations.required_sourc'
        'e_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterpri'
        'se_engineering_configurations.tenant_id = shared_enterprise_builds.tenant_id AND share'
        'd_enterprise_engineering_configurations.product_id = shared_enterprise_builds.product_'
        'id AND shared_enterprise_engineering_configurations.id = shared_enterprise_builds.engi'
        'neering_configuration_id) || (SELECT shared_enterprise_process_revisions.required_sour'
        'ce_read_set \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_proce'
        'ss_revisions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_proc'
        'ess_revisions.product_id = shared_enterprise_builds.product_id AND shared_enterprise_p'
        'rocess_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)) AS ent'
        "erprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c"
        '\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027'
        "\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash,"
        " CAST(CAST(jsonb_build_object('object_id', shared_enterprise_builds.id, 'kind', 'build"
        "', 'facts', jsonb_build_object('name', shared_enterprise_builds.name, 'type', shared_e"
        "nterprise_builds.type, 'purpose', shared_enterprise_builds.purpose, 'planned_quantity'"
        ", shared_enterprise_builds.planned_quantity, 'unit', shared_enterprise_builds.unit, 'p"
        "lanned_start', shared_enterprise_builds.planned_start, 'planned_end', shared_enterpris"
        "e_builds.planned_end, 'engineering_configuration_id', shared_enterprise_builds.enginee"
        "ring_configuration_id, 'manufacturing_configuration_id', shared_enterprise_builds.manu"
        "facturing_configuration_id, 'verification_objectives', shared_enterprise_builds.verifi"
        "cation_objectives, 'plan_status', shared_enterprise_builds.status), 'source_refs', (SE"
        "LECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_"
        "build.value['artifact_id'], 'version', enterprise_reads_build.value['expected_revision"
        "']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_reads_build.va"
        "lue ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_el"
        'ements((SELECT shared_enterprise_engineering_configurations.required_source_read_set '
        '\nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterprise_engineer'
        'ing_configurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterpris'
        'e_engineering_configurations.product_id = shared_enterprise_builds.product_id AND shar'
        'ed_enterprise_engineering_configurations.id = shared_enterprise_builds.engineering_con'
        'figuration_id) || (SELECT shared_enterprise_process_revisions.required_source_read_set'
        ' \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_revision'
        's.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisio'
        'ns.product_id = shared_enterprise_builds.product_id AND shared_enterprise_process_revi'
        'sions.id = shared_enterprise_builds.manufacturing_configuration_id)) AS enterprise_rea'
        "ds_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', "
        "shared_enterprise_builds.id, 'kind', 'build', 'facts', jsonb_build_object('name', shar"
        "ed_enterprise_builds.name, 'type', shared_enterprise_builds.type, 'purpose', shared_en"
        "terprise_builds.purpose, 'planned_quantity', shared_enterprise_builds.planned_quantity"
        ", 'unit', shared_enterprise_builds.unit, 'planned_start', shared_enterprise_builds.pla"
        "nned_start, 'planned_end', shared_enterprise_builds.planned_end, 'engineering_configur"
        "ation_id', shared_enterprise_builds.engineering_configuration_id, 'manufacturing_confi"
        "guration_id', shared_enterprise_builds.manufacturing_configuration_id, 'verification_o"
        "bjectives', shared_enterprise_builds.verification_objectives, 'plan_status', shared_en"
        "terprise_builds.status), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object("
        "'type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'version', ente"
        "rprise_reads_build.value['expected_revision']) ORDER BY enterprise_reads_build.value -"
        ">> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_a"
        'rray()) AS coalesce_1 \nFROM jsonb_array_elements((SELECT shared_enterprise_engineerin'
        'g_configurations.required_source_read_set \nFROM shared_enterprise_engineering_configu'
        'rations \nWHERE shared_enterprise_engineering_configurations.tenant_id = shared_enterp'
        'rise_builds.tenant_id AND shared_enterprise_engineering_configurations.product_id = sh'
        'ared_enterprise_builds.product_id AND shared_enterprise_engineering_configurations.id '
        '= shared_enterprise_builds.engineering_configuration_id) || (SELECT shared_enterprise_'
        'process_revisions.required_source_read_set \nFROM shared_enterprise_process_revisions '
        '\nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterprise_builds.tenan'
        't_id AND shared_enterprise_process_revisions.product_id = shared_enterprise_builds.pro'
        'duct_id AND shared_enterprise_process_revisions.id = shared_enterprise_builds.manufact'
        "uring_configuration_id)) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured"
        ", 'structured' AS nature, shared_enterprise_builds.visibility != 'category' OR shared_"
        "enterprise_projects.visibility != 'category' OR shared_enterprise_products.visibility "
        "!= 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterpri"
        'se_engineering_configurations.required_source_read_set \nFROM shared_enterprise_engine'
        'ering_configurations \nWHERE shared_enterprise_engineering_configurations.tenant_id = '
        'shared_enterprise_builds.tenant_id AND shared_enterprise_engineering_configurations.pr'
        'oduct_id = shared_enterprise_builds.product_id AND shared_enterprise_engineering_confi'
        'gurations.id = shared_enterprise_builds.engineering_configuration_id) || (SELECT share'
        'd_enterprise_process_revisions.required_source_read_set \nFROM shared_enterprise_proce'
        'ss_revisions \nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterprise'
        '_builds.tenant_id AND shared_enterprise_process_revisions.product_id = shared_enterpri'
        'se_builds.product_id AND shared_enterprise_process_revisions.id = shared_enterprise_bu'
        'ilds.manufacturing_configuration_id)) AS enterprise_reads_build(value) JOIN enterprise'
        '_authoritative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id ='
        ' shared_enterprise_builds.tenant_id AND enterprise_authoritative_artifacts_build.sourc'
        "e_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterpri"
        'se_authoritative_artifacts_build.private)) AS private, EXISTS (SELECT 1 \nFROM jsonb_a'
        'rray_elements((SELECT shared_enterprise_engineering_configurations.required_source_rea'
        'd_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterprise_en'
        'gineering_configurations.tenant_id = shared_enterprise_builds.tenant_id AND shared_ent'
        'erprise_engineering_configurations.product_id = shared_enterprise_builds.product_id AN'
        'D shared_enterprise_engineering_configurations.id = shared_enterprise_builds.engineeri'
        'ng_configuration_id) || (SELECT shared_enterprise_process_revisions.required_source_re'
        'ad_set \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_re'
        'visions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_r'
        'evisions.product_id = shared_enterprise_builds.product_id AND shared_enterprise_proces'
        's_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)) AS enterpri'
        'se_reads_build(value) JOIN enterprise_authoritative_artifacts_build ON enterprise_auth'
        'oritative_artifacts_build.tenant_id = shared_enterprise_builds.tenant_id AND enterpris'
        "e_authoritative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'ar"
        "tifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.customer_origina"
        'l) AS customer_original, true AS is_current, shared_enterprise_builds.created_at AS cr'
        'eated_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_builds.id AS object_id,'
        ' (SELECT coalesce(array_agg(enterprise_authoritative_artifacts_build.original_id), ARR'
        'AY[]::UUID[]) AS coalesce_2 \nFROM jsonb_array_elements((SELECT shared_enterprise_engi'
        'neering_configurations.required_source_read_set \nFROM shared_enterprise_engineering_c'
        'onfigurations \nWHERE shared_enterprise_engineering_configurations.tenant_id = shared_'
        'enterprise_builds.tenant_id AND shared_enterprise_engineering_configurations.product_i'
        'd = shared_enterprise_builds.product_id AND shared_enterprise_engineering_configuratio'
        'ns.id = shared_enterprise_builds.engineering_configuration_id) || (SELECT shared_enter'
        'prise_process_revisions.required_source_read_set \nFROM shared_enterprise_process_revi'
        'sions \nWHERE shared_enterprise_process_revisions.tenant_id = shared_enterprise_builds'
        '.tenant_id AND shared_enterprise_process_revisions.product_id = shared_enterprise_buil'
        'ds.product_id AND shared_enterprise_process_revisions.id = shared_enterprise_builds.ma'
        'nufacturing_configuration_id)) AS enterprise_reads_build(value) JOIN enterprise_author'
        'itative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = shared'
        '_enterprise_builds.tenant_id AND enterprise_authoritative_artifacts_build.source_id = '
        "CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_auth"
        'oritative_artifacts_build.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS '
        '(SELECT 1 \nFROM jsonb_array_elements((SELECT shared_enterprise_engineering_configurat'
        'ions.required_source_read_set \nFROM shared_enterprise_engineering_configurations \nWH'
        'ERE shared_enterprise_engineering_configurations.tenant_id = shared_enterprise_builds.'
        'tenant_id AND shared_enterprise_engineering_configurations.product_id = shared_enterpr'
        'ise_builds.product_id AND shared_enterprise_engineering_configurations.id = shared_ent'
        'erprise_builds.engineering_configuration_id) || (SELECT shared_enterprise_process_revi'
        'sions.required_source_read_set \nFROM shared_enterprise_process_revisions \nWHERE shar'
        'ed_enterprise_process_revisions.tenant_id = shared_enterprise_builds.tenant_id AND sha'
        'red_enterprise_process_revisions.product_id = shared_enterprise_builds.product_id AND '
        'shared_enterprise_process_revisions.id = shared_enterprise_builds.manufacturing_config'
        'uration_id)) AS enterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_'
        'build ON enterprise_authoritative_artifacts_build.tenant_id = shared_enterprise_builds'
        '.tenant_id AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_r'
        "eads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifact"
        "s_build.source_revision != CAST((enterprise_reads_build.value ->> 'expected_revision')"
        " AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM sha"
        'red_enterprise_builds JOIN shared_enterprise_projects ON shared_enterprise_projects.te'
        'nant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_projects.product_id'
        ' = shared_enterprise_builds.product_id AND shared_enterprise_projects.id = shared_ente'
        'rprise_builds.project_id AND shared_enterprise_projects.category_id = shared_enterpris'
        'e_builds.category_id JOIN shared_enterprise_products ON shared_enterprise_products.ten'
        'ant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_products.id = shared'
        '_enterprise_builds.product_id AND shared_enterprise_products.category_id = shared_ente'
        'rprise_builds.category_id \nWHERE shared_enterprise_builds.tenant_id = CAST(nullif(cur'
        "rent_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM js"
        'onb_array_elements((SELECT shared_enterprise_engineering_configurations.required_sourc'
        'e_read_set \nFROM shared_enterprise_engineering_configurations \nWHERE shared_enterpri'
        'se_engineering_configurations.tenant_id = shared_enterprise_builds.tenant_id AND share'
        'd_enterprise_engineering_configurations.product_id = shared_enterprise_builds.product_'
        'id AND shared_enterprise_engineering_configurations.id = shared_enterprise_builds.engi'
        'neering_configuration_id) || (SELECT shared_enterprise_process_revisions.required_sour'
        'ce_read_set \nFROM shared_enterprise_process_revisions \nWHERE shared_enterprise_proce'
        'ss_revisions.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_proc'
        'ess_revisions.product_id = shared_enterprise_builds.product_id AND shared_enterprise_p'
        'rocess_revisions.id = shared_enterprise_builds.manufacturing_configuration_id)) AS ent'
        'erprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritati'
        've_artifacts_build \nWHERE enterprise_authoritative_artifacts_build.tenant_id = shared'
        '_enterprise_builds.tenant_id AND enterprise_authoritative_artifacts_build.source_id = '
        "CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID))))) AND (EXISTS (SELECT"
        ' shared_enterprise_engineering_configurations.required_source_read_set \nFROM shared_e'
        'nterprise_engineering_configurations \nWHERE shared_enterprise_engineering_configurati'
        'ons.tenant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_engineering_c'
        'onfigurations.product_id = shared_enterprise_builds.product_id AND shared_enterprise_e'
        'ngineering_configurations.id = shared_enterprise_builds.engineering_configuration_id))'
        ' AND (EXISTS (SELECT shared_enterprise_process_revisions.required_source_read_set \nFR'
        'OM shared_enterprise_process_revisions \nWHERE shared_enterprise_process_revisions.ten'
        'ant_id = shared_enterprise_builds.tenant_id AND shared_enterprise_process_revisions.pr'
        'oduct_id = shared_enterprise_builds.product_id AND shared_enterprise_process_revisions'
        ".id = shared_enterprise_builds.manufacturing_configuration_id)) UNION ALL SELECT 'buil"
        "d' AS source_type, shared_enterprise_build_starts.id AS source_id, shared_enterprise_b"
        'uild_starts.tenant_id AS tenant_id, shared_enterprise_build_starts.category_id AS cate'
        'gory_id, shared_enterprise_build_starts.product_id AS product_id, shared_enterprise_bu'
        'ild_starts.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterpr'
        'ise_build_starts.owner_id AS owner_id, shared_enterprise_build_starts.revision AS sour'
        "ce_revision, '\u5f00\u5de5\u8bb0\u5f55 \xb7 ' || shared_enterprise_builds.name AS titl"
        "e, encode(sha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterpris"
        "e_build_starts.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', '"
        "build_start', 'build_id', shared_enterprise_build_starts.build_id, 'build_revision', s"
        "hared_enterprise_build_starts.build_revision, 'status', shared_enterprise_build_starts"
        ".status, 'occurred_at', shared_enterprise_build_starts.occurred_at, 'occurred_timezone"
        "', shared_enterprise_build_starts.occurred_timezone, 'assessment_id', shared_enterpris"
        "e_build_starts.assessment_id, 'assessment_revision', shared_enterprise_build_starts.as"
        "sessment_revision, 'engineering_authorization_id', shared_enterprise_build_starts.engi"
        "neering_authorization_id, 'engineering_authorization_revision', shared_enterprise_buil"
        "d_starts.engineering_authorization_revision, 'manufacturing_authorization_id', shared_"
        "enterprise_build_starts.manufacturing_authorization_id, 'manufacturing_authorization_r"
        "evision', shared_enterprise_build_starts.manufacturing_authorization_revision) || json"
        "b_build_object('execution_scope', jsonb_build_object('purpose', shared_enterprise_buil"
        "d_starts.execution_scope['purpose'], 'quantity', shared_enterprise_build_starts.execut"
        "ion_scope['quantity'], 'unit', shared_enterprise_build_starts.execution_scope['unit'],"
        " 'site', shared_enterprise_build_starts.execution_scope['site'], 'window_start', share"
        "d_enterprise_build_starts.execution_scope['window_start'], 'window_end', shared_enterp"
        "rise_build_starts.execution_scope['window_end'], 'window_timezone', shared_enterprise_"
        "build_starts.execution_scope['window_timezone']), 'continuation_permission', 'not_eval"
        "uated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifac"
        "t', 'id', enterprise_reads_build.value['artifact_id'], 'version', enterprise_reads_bui"
        "ld.value['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id'"
        ", enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coale"
        'sce_3 \nFROM jsonb_array_elements(shared_enterprise_build_starts.required_source_read_'
        "set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS c"
        "ontent_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_build_starts."
        "build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'build_start', '"
        "build_id', shared_enterprise_build_starts.build_id, 'build_revision', shared_enterpris"
        "e_build_starts.build_revision, 'status', shared_enterprise_build_starts.status, 'occur"
        "red_at', shared_enterprise_build_starts.occurred_at, 'occurred_timezone', shared_enter"
        "prise_build_starts.occurred_timezone, 'assessment_id', shared_enterprise_build_starts."
        "assessment_id, 'assessment_revision', shared_enterprise_build_starts.assessment_revisi"
        "on, 'engineering_authorization_id', shared_enterprise_build_starts.engineering_authori"
        "zation_id, 'engineering_authorization_revision', shared_enterprise_build_starts.engine"
        "ering_authorization_revision, 'manufacturing_authorization_id', shared_enterprise_buil"
        "d_starts.manufacturing_authorization_id, 'manufacturing_authorization_revision', share"
        'd_enterprise_build_starts.manufacturing_authorization_revision) || jsonb_build_object('
        "'execution_scope', jsonb_build_object('purpose', shared_enterprise_build_starts.execut"
        "ion_scope['purpose'], 'quantity', shared_enterprise_build_starts.execution_scope['quan"
        "tity'], 'unit', shared_enterprise_build_starts.execution_scope['unit'], 'site', shared"
        "_enterprise_build_starts.execution_scope['site'], 'window_start', shared_enterprise_bu"
        "ild_starts.execution_scope['window_start'], 'window_end', shared_enterprise_build_star"
        "ts.execution_scope['window_end'], 'window_timezone', shared_enterprise_build_starts.ex"
        "ecution_scope['window_timezone']), 'continuation_permission', 'not_evaluated'), 'sourc"
        "e_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enter"
        "prise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.value['expec"
        "ted_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_re"
        "ads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_3 \nFROM js"
        'onb_array_elements(shared_enterprise_build_starts.required_source_read_set) AS enterpr'
        "ise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object"
        "_id', shared_enterprise_build_starts.build_id, 'kind', 'build', 'facts', jsonb_build_o"
        "bject('record_kind', 'build_start', 'build_id', shared_enterprise_build_starts.build_i"
        "d, 'build_revision', shared_enterprise_build_starts.build_revision, 'status', shared_e"
        "nterprise_build_starts.status, 'occurred_at', shared_enterprise_build_starts.occurred_"
        "at, 'occurred_timezone', shared_enterprise_build_starts.occurred_timezone, 'assessment"
        "_id', shared_enterprise_build_starts.assessment_id, 'assessment_revision', shared_ente"
        "rprise_build_starts.assessment_revision, 'engineering_authorization_id', shared_enterp"
        "rise_build_starts.engineering_authorization_id, 'engineering_authorization_revision', "
        "shared_enterprise_build_starts.engineering_authorization_revision, 'manufacturing_auth"
        "orization_id', shared_enterprise_build_starts.manufacturing_authorization_id, 'manufac"
        "turing_authorization_revision', shared_enterprise_build_starts.manufacturing_authoriza"
        "tion_revision) || jsonb_build_object('execution_scope', jsonb_build_object('purpose', "
        "shared_enterprise_build_starts.execution_scope['purpose'], 'quantity', shared_enterpri"
        "se_build_starts.execution_scope['quantity'], 'unit', shared_enterprise_build_starts.ex"
        "ecution_scope['unit'], 'site', shared_enterprise_build_starts.execution_scope['site'],"
        " 'window_start', shared_enterprise_build_starts.execution_scope['window_start'], 'wind"
        "ow_end', shared_enterprise_build_starts.execution_scope['window_end'], 'window_timezon"
        "e', shared_enterprise_build_starts.execution_scope['window_timezone']), 'continuation_"
        "permission', 'not_evaluated'), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_o"
        "bject('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'version'"
        ", enterprise_reads_build.value['expected_revision']) ORDER BY enterprise_reads_build.v"
        "alue ->> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_b"
        'uild_array()) AS coalesce_3 \nFROM jsonb_array_elements(shared_enterprise_build_starts'
        ".required_source_read_set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5"
        '\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d'
        "\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured"
        ", 'structured' AS nature, shared_enterprise_build_starts.visibility != 'category' OR s"
        "hared_enterprise_projects.visibility != 'category' OR shared_enterprise_products.visib"
        "ility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise"
        '_build_starts.required_source_read_set) AS enterprise_reads_build(value) JOIN enterpri'
        'se_authoritative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id'
        ' = shared_enterprise_build_starts.tenant_id AND enterprise_authoritative_artifacts_bui'
        "ld.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE "
        'enterprise_authoritative_artifacts_build.private)) OR shared_enterprise_builds.visibil'
        "ity != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_ente"
        'rprise_build_starts.required_source_read_set) AS enterprise_reads_build(value) JOIN en'
        'terprise_authoritative_artifacts_build ON enterprise_authoritative_artifacts_build.ten'
        'ant_id = shared_enterprise_build_starts.tenant_id AND enterprise_authoritative_artifac'
        "ts_build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_build.customer_original) AS customer_original'
        ', true AS is_current, shared_enterprise_build_starts.created_at AS created_at, CAST(NU'
        'LL AS UUID) AS original_id, shared_enterprise_build_starts.build_id AS object_id, (SEL'
        'ECT coalesce(array_agg(enterprise_authoritative_artifacts_build.original_id), ARRAY[]:'
        ':UUID[]) AS coalesce_4 \nFROM jsonb_array_elements(shared_enterprise_build_starts.requ'
        'ired_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_authoritative_a'
        'rtifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = shared_enterpri'
        'se_build_starts.tenant_id AND enterprise_authoritative_artifacts_build.source_id = CAS'
        "T((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authori"
        'tative_artifacts_build.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SE'
        'LECT 1 \nFROM jsonb_array_elements(shared_enterprise_build_starts.required_source_read'
        '_set) AS enterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_build O'
        'N enterprise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_starts.'
        'tenant_id AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_re'
        "ads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts"
        "_build.source_revision != CAST((enterprise_reads_build.value ->> 'expected_revision') "
        "AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shar"
        'ed_enterprise_build_starts JOIN shared_enterprise_projects ON shared_enterprise_projec'
        'ts.tenant_id = shared_enterprise_build_starts.tenant_id AND shared_enterprise_projects'
        '.product_id = shared_enterprise_build_starts.product_id AND shared_enterprise_projects'
        '.id = shared_enterprise_build_starts.project_id AND shared_enterprise_projects.categor'
        'y_id = shared_enterprise_build_starts.category_id JOIN shared_enterprise_products ON s'
        'hared_enterprise_products.tenant_id = shared_enterprise_build_starts.tenant_id AND sha'
        'red_enterprise_products.id = shared_enterprise_build_starts.product_id AND shared_ente'
        'rprise_products.category_id = shared_enterprise_build_starts.category_id JOIN shared_e'
        'nterprise_builds ON shared_enterprise_builds.tenant_id = shared_enterprise_build_start'
        's.tenant_id AND shared_enterprise_builds.category_id = shared_enterprise_build_starts.'
        'category_id AND shared_enterprise_builds.product_id = shared_enterprise_build_starts.p'
        'roduct_id AND shared_enterprise_builds.project_id = shared_enterprise_build_starts.pro'
        'ject_id AND shared_enterprise_builds.id = shared_enterprise_build_starts.build_id AND '
        'shared_enterprise_builds.revision = shared_enterprise_build_starts.build_revision \nWH'
        "ERE shared_enterprise_build_starts.tenant_id = CAST(nullif(current_setting('pdos.tenan"
        "t_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(share"
        'd_enterprise_build_starts.required_source_read_set) AS enterprise_reads_build(value) '
        '\nWHERE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_build \nWHERE '
        'enterprise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_starts.te'
        'nant_id AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_read'
        "s_build.value ->> 'artifact_id') AS UUID))))) UNION ALL SELECT 'build' AS source_type,"
        ' shared_enterprise_actual_configurations.id AS source_id, shared_enterprise_actual_con'
        'figurations.tenant_id AS tenant_id, shared_enterprise_actual_configurations.category_i'
        'd AS category_id, shared_enterprise_actual_configurations.product_id AS product_id, sh'
        'ared_enterprise_actual_configurations.project_id AS project_id, CAST(NULL AS UUID) AS '
        'proposal_id, shared_enterprise_actual_configurations.owner_id AS owner_id, shared_ente'
        "rprise_actual_configurations.revision AS source_revision, '\u5b9e\u9645\u914d\u7f6e"
        "\u8bb0\u5f55 \xb7 ' || shared_enterprise_builds.name AS title, encode(sha256(convert_t"
        "o(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_actual_configurations.bu"
        "ild_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actual_configurat"
        "ion', 'build_id', shared_enterprise_actual_configurations.build_id, 'build_revision', "
        "shared_enterprise_actual_configurations.build_revision, 'status', shared_enterprise_ac"
        "tual_configurations.status, 'planned_engineering_configuration_id', shared_enterprise_"
        "actual_configurations.planned_engineering_configuration_id, 'planned_manufacturing_con"
        "figuration_id', shared_enterprise_actual_configurations.planned_manufacturing_configur"
        "ation_id, 'actual_engineering_configuration_id', shared_enterprise_actual_configuratio"
        "ns.actual_engineering_configuration_id, 'actual_engineering_revision', shared_enterpri"
        "se_actual_configurations.actual_engineering_revision, 'actual_manufacturing_configurat"
        "ion_id', shared_enterprise_actual_configurations.actual_manufacturing_configuration_id"
        ", 'actual_manufacturing_revision', shared_enterprise_actual_configurations.actual_manu"
        "facturing_revision, 'observed_at', shared_enterprise_actual_configurations.observed_at"
        "), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'i"
        "d', enterprise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.val"
        "ue['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', ente"
        "rprise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_5 "
        '\nFROM jsonb_array_elements(shared_enterprise_actual_configurations.required_source_re'
        "ad_set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5"
        '\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002'
        "\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS c"
        "ontent_hash, CAST(CAST(jsonb_build_object('object_id', shared_enterprise_actual_config"
        "urations.build_id, 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actual"
        "_configuration', 'build_id', shared_enterprise_actual_configurations.build_id, 'build_"
        "revision', shared_enterprise_actual_configurations.build_revision, 'status', shared_en"
        "terprise_actual_configurations.status, 'planned_engineering_configuration_id', shared_"
        "enterprise_actual_configurations.planned_engineering_configuration_id, 'planned_manufa"
        "cturing_configuration_id', shared_enterprise_actual_configurations.planned_manufacturi"
        "ng_configuration_id, 'actual_engineering_configuration_id', shared_enterprise_actual_c"
        "onfigurations.actual_engineering_configuration_id, 'actual_engineering_revision', shar"
        "ed_enterprise_actual_configurations.actual_engineering_revision, 'actual_manufacturing"
        "_configuration_id', shared_enterprise_actual_configurations.actual_manufacturing_confi"
        "guration_id, 'actual_manufacturing_revision', shared_enterprise_actual_configurations."
        "actual_manufacturing_revision, 'observed_at', shared_enterprise_actual_configurations."
        "observed_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'ar"
        "tifact', 'id', enterprise_reads_build.value['artifact_id'], 'version', enterprise_read"
        "s_build.value['expected_revision']) ORDER BY enterprise_reads_build.value ->> 'artifac"
        "t_id', enterprise_reads_build.value ->> 'expected_revision'), jsonb_build_array()) AS "
        'coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.require'
        "d_source_read_set) AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868"
        '\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a'
        "\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT) AS body, C"
        "AST(jsonb_build_object('object_id', shared_enterprise_actual_configurations.build_id, "
        "'kind', 'build', 'facts', jsonb_build_object('record_kind', 'actual_configuration', 'b"
        "uild_id', shared_enterprise_actual_configurations.build_id, 'build_revision', shared_e"
        "nterprise_actual_configurations.build_revision, 'status', shared_enterprise_actual_con"
        "figurations.status, 'planned_engineering_configuration_id', shared_enterprise_actual_c"
        "onfigurations.planned_engineering_configuration_id, 'planned_manufacturing_configurati"
        "on_id', shared_enterprise_actual_configurations.planned_manufacturing_configuration_id"
        ", 'actual_engineering_configuration_id', shared_enterprise_actual_configurations.actua"
        "l_engineering_configuration_id, 'actual_engineering_revision', shared_enterprise_actua"
        "l_configurations.actual_engineering_revision, 'actual_manufacturing_configuration_id',"
        " shared_enterprise_actual_configurations.actual_manufacturing_configuration_id, 'actua"
        "l_manufacturing_revision', shared_enterprise_actual_configurations.actual_manufacturin"
        "g_revision, 'observed_at', shared_enterprise_actual_configurations.observed_at), 'sour"
        "ce_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', ente"
        "rprise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.value['expe"
        "cted_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_r"
        "eads_build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_5 \nFROM j"
        'sonb_array_elements(shared_enterprise_actual_configurations.required_source_read_set) '
        "AS enterprise_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248"
        '\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528'
        "\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature"
        ", shared_enterprise_actual_configurations.visibility != 'category' OR shared_enterpris"
        "e_projects.visibility != 'category' OR shared_enterprise_products.visibility != 'categ"
        "ory' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_actual_configu"
        'rations.required_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_aut'
        'horitative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = sha'
        'red_enterprise_actual_configurations.tenant_id AND enterprise_authoritative_artifacts_'
        "build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHE"
        'RE enterprise_authoritative_artifacts_build.private)) OR shared_enterprise_builds.visi'
        "bility != 'category' AS private, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_e"
        'nterprise_actual_configurations.required_source_read_set) AS enterprise_reads_build(va'
        'lue) JOIN enterprise_authoritative_artifacts_build ON enterprise_authoritative_artifac'
        'ts_build.tenant_id = shared_enterprise_actual_configurations.tenant_id AND enterprise_'
        "authoritative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'arti"
        "fact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.customer_original)"
        ' AS customer_original, true AS is_current, shared_enterprise_actual_configurations.cre'
        'ated_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_actual_con'
        'figurations.build_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative'
        '_artifacts_build.original_id), ARRAY[]::UUID[]) AS coalesce_6 \nFROM jsonb_array_eleme'
        'nts(shared_enterprise_actual_configurations.required_source_read_set) AS enterprise_re'
        'ads_build(value) JOIN enterprise_authoritative_artifacts_build ON enterprise_authorita'
        'tive_artifacts_build.tenant_id = shared_enterprise_actual_configurations.tenant_id AND'
        ' enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_build.val'
        "ue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.origin"
        'al_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_ele'
        'ments(shared_enterprise_actual_configurations.required_source_read_set) AS enterprise_'
        'reads_build(value) JOIN enterprise_authoritative_artifacts_build ON enterprise_authori'
        'tative_artifacts_build.tenant_id = shared_enterprise_actual_configurations.tenant_id A'
        'ND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_build.v'
        "alue ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.sour"
        "ce_revision != CAST((enterprise_reads_build.value ->> 'expected_revision') AS INTEGER)"
        ")) THEN 'needs_recheck' ELSE 'current' END AS read_basis_status \nFROM shared_enterpri"
        'se_actual_configurations JOIN shared_enterprise_projects ON shared_enterprise_projects'
        '.tenant_id = shared_enterprise_actual_configurations.tenant_id AND shared_enterprise_p'
        'rojects.product_id = shared_enterprise_actual_configurations.product_id AND shared_ent'
        'erprise_projects.id = shared_enterprise_actual_configurations.project_id AND shared_en'
        'terprise_projects.category_id = shared_enterprise_actual_configurations.category_id JO'
        'IN shared_enterprise_products ON shared_enterprise_products.tenant_id = shared_enterpr'
        'ise_actual_configurations.tenant_id AND shared_enterprise_products.id = shared_enterpr'
        'ise_actual_configurations.product_id AND shared_enterprise_products.category_id = shar'
        'ed_enterprise_actual_configurations.category_id JOIN shared_enterprise_builds ON share'
        'd_enterprise_builds.tenant_id = shared_enterprise_actual_configurations.tenant_id AND '
        'shared_enterprise_builds.category_id = shared_enterprise_actual_configurations.categor'
        'y_id AND shared_enterprise_builds.product_id = shared_enterprise_actual_configurations'
        '.product_id AND shared_enterprise_builds.project_id = shared_enterprise_actual_configu'
        'rations.project_id AND shared_enterprise_builds.id = shared_enterprise_actual_configur'
        'ations.build_id AND shared_enterprise_builds.revision = shared_enterprise_actual_confi'
        'gurations.build_revision \nWHERE shared_enterprise_actual_configurations.tenant_id = C'
        "AST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELE"
        'CT 1 \nFROM jsonb_array_elements(shared_enterprise_actual_configurations.required_sour'
        'ce_read_set) AS enterprise_reads_build(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM ent'
        'erprise_authoritative_artifacts_build \nWHERE enterprise_authoritative_artifacts_build'
        '.tenant_id = shared_enterprise_actual_configurations.tenant_id AND enterprise_authorit'
        "ative_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id'"
        ") AS UUID))))) UNION ALL SELECT 'build' AS source_type, shared_enterprise_build_lots.i"
        'd AS source_id, shared_enterprise_build_lots.tenant_id AS tenant_id, shared_enterprise'
        '_build_lots.category_id AS category_id, shared_enterprise_build_lots.product_id AS pro'
        'duct_id, shared_enterprise_build_lots.project_id AS project_id, CAST(NULL AS UUID) AS '
        'proposal_id, shared_enterprise_build_lots.owner_id AS owner_id, shared_enterprise_buil'
        "d_lots.revision AS source_revision, '\u5b9e\u7269\u4ea7\u51fa\u8bb0\u5f55 \xb7 ' || sh"
        'ared_enterprise_builds.name AS title, encode(sha256(convert_to(CAST(CAST(jsonb_build_o'
        "bject('object_id', shared_enterprise_build_lots.build_id, 'kind', 'build', 'facts', js"
        "onb_build_object('record_kind', 'build_output', 'build_id', shared_enterprise_build_lo"
        "ts.build_id, 'build_revision', shared_enterprise_build_lots.build_revision, 'status', "
        "shared_enterprise_build_lots.status, 'lot_label', shared_enterprise_build_lots.lot_lab"
        "el, 'actual_configuration_id', shared_enterprise_build_lots.actual_configuration_id, '"
        "actual_configuration_revision', shared_enterprise_build_lots.actual_configuration_revi"
        "sion, 'observed_unit_count', shared_enterprise_build_lots.observed_unit_count, 'unit',"
        " shared_enterprise_build_lots.unit, 'observation_nature', shared_enterprise_build_lots"
        ".observation_nature, 'occurred_at', shared_enterprise_build_lots.occurred_at, 'receive"
        "d_at', shared_enterprise_build_lots.received_at), 'source_refs', (SELECT coalesce(json"
        "b_agg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_build.value['artif"
        "act_id'], 'version', enterprise_reads_build.value['expected_revision']) ORDER BY enter"
        "prise_reads_build.value ->> 'artifact_id', enterprise_reads_build.value ->> 'expected_"
        "revision'), jsonb_build_array()) AS coalesce_7 \nFROM jsonb_array_elements(shared_ente"
        "rprise_build_lots.required_source_read_set) AS enterprise_reads_build(value)), 'record"
        "_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e"
        "\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JS"
        "ONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_"
        "id', shared_enterprise_build_lots.build_id, 'kind', 'build', 'facts', jsonb_build_obje"
        "ct('record_kind', 'build_output', 'build_id', shared_enterprise_build_lots.build_id, '"
        "build_revision', shared_enterprise_build_lots.build_revision, 'status', shared_enterpr"
        "ise_build_lots.status, 'lot_label', shared_enterprise_build_lots.lot_label, 'actual_co"
        "nfiguration_id', shared_enterprise_build_lots.actual_configuration_id, 'actual_configu"
        "ration_revision', shared_enterprise_build_lots.actual_configuration_revision, 'observe"
        "d_unit_count', shared_enterprise_build_lots.observed_unit_count, 'unit', shared_enterp"
        "rise_build_lots.unit, 'observation_nature', shared_enterprise_build_lots.observation_n"
        "ature, 'occurred_at', shared_enterprise_build_lots.occurred_at, 'received_at', shared_"
        "enterprise_build_lots.received_at), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_bu"
        "ild_object('type', 'artifact', 'id', enterprise_reads_build.value['artifact_id'], 'ver"
        "sion', enterprise_reads_build.value['expected_revision']) ORDER BY enterprise_reads_bu"
        "ild.value ->> 'artifact_id', enterprise_reads_build.value ->> 'expected_revision'), js"
        'onb_build_array()) AS coalesce_7 \nFROM jsonb_array_elements(shared_enterprise_build_l'
        "ots.required_source_read_set) AS enterprise_reads_build(value)), 'record_policy', '"
        '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53'
        "\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS TEXT"
        ") AS body, CAST(jsonb_build_object('object_id', shared_enterprise_build_lots.build_id,"
        " 'kind', 'build', 'facts', jsonb_build_object('record_kind', 'build_output', 'build_id"
        "', shared_enterprise_build_lots.build_id, 'build_revision', shared_enterprise_build_lo"
        "ts.build_revision, 'status', shared_enterprise_build_lots.status, 'lot_label', shared_"
        "enterprise_build_lots.lot_label, 'actual_configuration_id', shared_enterprise_build_lo"
        "ts.actual_configuration_id, 'actual_configuration_revision', shared_enterprise_build_l"
        "ots.actual_configuration_revision, 'observed_unit_count', shared_enterprise_build_lots"
        ".observed_unit_count, 'unit', shared_enterprise_build_lots.unit, 'observation_nature',"
        " shared_enterprise_build_lots.observation_nature, 'occurred_at', shared_enterprise_bui"
        "ld_lots.occurred_at, 'received_at', shared_enterprise_build_lots.received_at), 'source"
        "_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterp"
        "rise_reads_build.value['artifact_id'], 'version', enterprise_reads_build.value['expect"
        "ed_revision']) ORDER BY enterprise_reads_build.value ->> 'artifact_id', enterprise_rea"
        "ds_build.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_7 \nFROM jso"
        'nb_array_elements(shared_enterprise_build_lots.required_source_read_set) AS enterprise'
        "_reads_build(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2"
        '\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd'
        "\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, shared_ent"
        "erprise_build_lots.visibility != 'category' OR shared_enterprise_projects.visibility !"
        "= 'category' OR shared_enterprise_products.visibility != 'category' OR (EXISTS (SELECT"
        ' 1 \nFROM jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set) '
        'AS enterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_build ON ente'
        'rprise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_lots.tenant_i'
        'd AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_buil'
        "d.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build.p"
        "rivate)) OR shared_enterprise_builds.visibility != 'category' AS private, EXISTS (SELE"
        'CT 1 \nFROM jsonb_array_elements(shared_enterprise_build_lots.required_source_read_set'
        ') AS enterprise_reads_build(value) JOIN enterprise_authoritative_artifacts_build ON en'
        'terprise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_lots.tenant'
        '_id AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_bu'
        "ild.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_build"
        '.customer_original) AS customer_original, true AS is_current, shared_enterprise_build_'
        'lots.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_bu'
        'ild_lots.build_id AS object_id, (SELECT coalesce(array_agg(enterprise_authoritative_ar'
        'tifacts_build.original_id), ARRAY[]::UUID[]) AS coalesce_8 \nFROM jsonb_array_elements'
        '(shared_enterprise_build_lots.required_source_read_set) AS enterprise_reads_build(valu'
        'e) JOIN enterprise_authoritative_artifacts_build ON enterprise_authoritative_artifacts'
        '_build.tenant_id = shared_enterprise_build_lots.tenant_id AND enterprise_authoritative'
        "_artifacts_build.source_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS "
        'UUID) \nWHERE enterprise_authoritative_artifacts_build.original_id IS NOT NULL) AS ori'
        'ginal_ids, CASE WHEN (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_b'
        'uild_lots.required_source_read_set) AS enterprise_reads_build(value) JOIN enterprise_a'
        'uthoritative_artifacts_build ON enterprise_authoritative_artifacts_build.tenant_id = s'
        'hared_enterprise_build_lots.tenant_id AND enterprise_authoritative_artifacts_build.sou'
        "rce_id = CAST((enterprise_reads_build.value ->> 'artifact_id') AS UUID) \nWHERE enterp"
        'rise_authoritative_artifacts_build.source_revision != CAST((enterprise_reads_build.val'
        "ue ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END AS r"
        'ead_basis_status \nFROM shared_enterprise_build_lots JOIN shared_enterprise_projects O'
        'N shared_enterprise_projects.tenant_id = shared_enterprise_build_lots.tenant_id AND sh'
        'ared_enterprise_projects.product_id = shared_enterprise_build_lots.product_id AND shar'
        'ed_enterprise_projects.id = shared_enterprise_build_lots.project_id AND shared_enterpr'
        'ise_projects.category_id = shared_enterprise_build_lots.category_id JOIN shared_enterp'
        'rise_products ON shared_enterprise_products.tenant_id = shared_enterprise_build_lots.t'
        'enant_id AND shared_enterprise_products.id = shared_enterprise_build_lots.product_id A'
        'ND shared_enterprise_products.category_id = shared_enterprise_build_lots.category_id J'
        'OIN shared_enterprise_builds ON shared_enterprise_builds.tenant_id = shared_enterprise'
        '_build_lots.tenant_id AND shared_enterprise_builds.category_id = shared_enterprise_bui'
        'ld_lots.category_id AND shared_enterprise_builds.product_id = shared_enterprise_build_'
        'lots.product_id AND shared_enterprise_builds.project_id = shared_enterprise_build_lots'
        '.project_id AND shared_enterprise_builds.id = shared_enterprise_build_lots.build_id AN'
        'D shared_enterprise_builds.revision = shared_enterprise_build_lots.build_revision \nWH'
        "ERE shared_enterprise_build_lots.tenant_id = CAST(nullif(current_setting('pdos.tenant_"
        "id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_"
        'enterprise_build_lots.required_source_read_set) AS enterprise_reads_build(value) \nWHE'
        'RE NOT (EXISTS (SELECT 1 \nFROM enterprise_authoritative_artifacts_build \nWHERE enter'
        'prise_authoritative_artifacts_build.tenant_id = shared_enterprise_build_lots.tenant_id'
        ' AND enterprise_authoritative_artifacts_build.source_id = CAST((enterprise_reads_build'
        ".value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM authoritative"
        '_enterprise_sources_build \nWHERE authoritative_enterprise_sources_build.tenant_id = t'
        ' AND authoritative_enterprise_sources_build.category_id = c AND CAST(authoritative_ent'
        "erprise_sources_build.source_id AS TEXT) = expected->>'source_id' AND CAST(authoritati"
        "ve_enterprise_sources_build.source_revision AS TEXT) = expected->>'source_revision' AN"
        "D authoritative_enterprise_sources_build.content_hash = expected->>'content_hash') AS "
        "anon_1 INTO visible;\n WHEN 'test_run' THEN\n  WITH enterprise_authoritative_artifacts"
        "_test_run AS \n(SELECT 'artifact' AS source_type, artifact_versions.id AS source_id, a"
        'rtifact_versions.tenant_id AS tenant_id, artifact_versions.category_id AS category_id,'
        ' artifact_versions.product_id AS product_id, CAST(NULL AS UUID) AS project_id, CAST(NU'
        'LL AS UUID) AS proposal_id, artifact_versions.owner_id AS owner_id, artifact_versions.'
        'revision AS source_revision, artifact_versions.title AS title, artifact_versions.conte'
        'nt_hash AS content_hash, artifact_versions.content AS body, CAST(NULL AS JSONB) AS str'
        "uctured, 'untrusted' AS nature, artifact_versions.visibility != 'category' OR coalesce"
        "(products.visibility != 'category', false) OR coalesce(uploaded_originals.visibility !"
        "= 'category', false) AS private, artifact_versions.original_id IS NOT NULL AS customer"
        '_original, true AS is_current, artifact_versions.created_at AS created_at, artifact_ve'
        'rsions.original_id AS original_id, artifact_versions.id AS object_id, CASE WHEN (artif'
        'act_versions.original_id IS NOT NULL) THEN ARRAY[artifact_versions.original_id] ELSE A'
        "RRAY[]::UUID[] END AS original_ids, 'current' AS read_basis_status \nFROM artifact_ver"
        'sions LEFT OUTER JOIN products ON products.tenant_id = artifact_versions.tenant_id AND'
        ' products.id = artifact_versions.product_id LEFT OUTER JOIN uploaded_originals ON uplo'
        'aded_originals.tenant_id = artifact_versions.tenant_id AND uploaded_originals.id = art'
        'ifact_versions.original_id AND uploaded_originals.category_id = artifact_versions.cate'
        'gory_id AND uploaded_originals.product_id IS NOT DISTINCT FROM artifact_versions.produ'
        'ct_id LEFT OUTER JOIN original_security ON original_security.tenant_id = uploaded_orig'
        'inals.tenant_id AND original_security.original_id = uploaded_originals.id \nWHERE arti'
        "fact_versions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS "
        "UUID) AND artifact_versions.status = 'active' AND artifact_versions.category_id IS NOT"
        ' NULL AND (artifact_versions.product_id IS NULL OR products.id IS NOT NULL) AND (artif'
        'act_versions.original_id IS NULL OR uploaded_originals.id IS NOT NULL AND uploaded_ori'
        "ginals.status = 'parsed' AND uploaded_originals.scan_status = 'clean' AND original_sec"
        "urity.source_state = 'active' AND original_security.disposition = 'active' AND origina"
        'l_security.current_request_id IS NOT NULL)), \nshared_enterprise_verification_run_vers'
        'ions AS MATERIALIZED \n(SELECT verification_run_versions.product_id AS product_id, ver'
        'ification_run_versions.project_id AS project_id, verification_run_versions.build_id AS'
        ' build_id, verification_run_versions.build_revision AS build_revision, verification_ru'
        'n_versions.request_id AS request_id, verification_run_versions.request_version_id AS r'
        'equest_version_id, verification_run_versions.request_revision AS request_revision, ver'
        'ification_run_versions.run_id AS run_id, verification_run_versions.revision AS revisio'
        'n, verification_run_versions.previous_run_version_id AS previous_run_version_id, verif'
        'ication_run_versions.previous_revision AS previous_revision, verification_run_versions'
        '.owner_id AS owner_id, verification_run_versions.writer_id AS writer_id, verification_'
        'run_versions.visibility AS visibility, verification_run_versions.status AS status, ver'
        'ification_run_versions.operation AS operation, verification_run_versions.run_snapshot '
        'AS run_snapshot, verification_run_versions.execution_plan AS execution_plan, verificat'
        'ion_run_versions.plan_sha256 AS plan_sha256, verification_run_versions.input_snapshot '
        'AS input_snapshot, verification_run_versions.snapshot_sha256 AS snapshot_sha256, verif'
        'ication_run_versions.sources AS sources, verification_run_versions.required_source_rea'
        'd_set AS required_source_read_set, verification_run_versions.source_basis AS source_ba'
        'sis, verification_run_versions.authority_snapshot AS authority_snapshot, verification_'
        'run_versions.intent_digest AS intent_digest, verification_run_versions.reason AS reaso'
        'n, verification_run_versions.id AS id, verification_run_versions.tenant_id AS tenant_i'
        'd, verification_run_versions.created_at AS created_at, verification_run_versions.categ'
        'ory_id AS category_id \nFROM verification_run_versions \nWHERE verification_run_versio'
        "ns.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \ns"
        'hared_enterprise_projects AS MATERIALIZED \n(SELECT projects.product_id AS product_id,'
        ' projects.owner_id AS owner_id, projects.name AS name, projects.purpose AS purpose, pr'
        'ojects.scope AS scope, projects.visibility AS visibility, projects.status AS status, p'
        'rojects.revision AS revision, projects.current_plan_id AS current_plan_id, projects.tr'
        'igger_type AS trigger_type, projects.trigger_id AS trigger_id, projects.g0_decision_id'
        ' AS g0_decision_id, projects.id AS id, projects.tenant_id AS tenant_id, projects.creat'
        'ed_at AS created_at, projects.category_id AS category_id \nFROM projects \nWHERE proje'
        "cts.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID)), \n"
        'shared_enterprise_products AS MATERIALIZED \n(SELECT products.name AS name, products.p'
        'urpose AS purpose, products.revision AS revision, products.lifecycle_epoch AS lifecycl'
        'e_epoch, products.status AS status, products.owner_id AS owner_id, products.parent_pro'
        'duct_id AS parent_product_id, products.category_id AS category_id, products.visibility'
        ' AS visibility, products.target_price AS target_price, products.target_price_currency '
        'AS target_price_currency, products.target_price_basis AS target_price_basis, products.'
        'target_price_includes_tax AS target_price_includes_tax, products.target_price_as_of AS'
        ' target_price_as_of, products.id AS id, products.tenant_id AS tenant_id, products.crea'
        'ted_at AS created_at \nFROM products \nWHERE products.tenant_id = CAST(nullif(current_'
        "setting('pdos.tenant_id', true), '') AS UUID)), \nshared_enterprise_builds AS MATERIAL"
        'IZED \n(SELECT builds.product_id AS product_id, builds.project_id AS project_id, build'
        's.project_revision AS project_revision, builds.engineering_configuration_id AS enginee'
        'ring_configuration_id, builds.manufacturing_configuration_id AS manufacturing_configur'
        'ation_id, builds.previous_build_id AS previous_build_id, builds.owner_id AS owner_id, '
        'builds.name AS name, builds.type AS type, builds.purpose AS purpose, builds.planned_qu'
        'antity AS planned_quantity, builds.unit AS unit, builds.planned_start AS planned_start'
        ', builds.planned_end AS planned_end, builds.verification_objectives AS verification_ob'
        'jectives, builds.disposition_plan AS disposition_plan, builds.visibility AS visibility'
        ', builds.revision AS revision, builds.status AS status, builds.id AS id, builds.tenant'
        '_id AS tenant_id, builds.created_at AS created_at, builds.category_id AS category_id '
        "\nFROM builds \nWHERE builds.tenant_id = CAST(nullif(current_setting('pdos.tenant_id',"
        " true), '') AS UUID)), \nshared_enterprise_verification_current_runs AS MATERIALIZED "
        '\n(SELECT verification_current_runs.product_id AS product_id, verification_current_run'
        's.request_id AS request_id, verification_current_runs.run_id AS run_id, verification_c'
        'urrent_runs.run_version_id AS run_version_id, verification_current_runs.run_revision A'
        'S run_revision, verification_current_runs.id AS id, verification_current_runs.tenant_i'
        'd AS tenant_id, verification_current_runs.created_at AS created_at, verification_curre'
        'nt_runs.category_id AS category_id \nFROM verification_current_runs \nWHERE verificati'
        "on_current_runs.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') A"
        'S UUID)), \nshared_enterprise_test_result_actions AS MATERIALIZED \n(SELECT test_resul'
        't_actions.operation AS operation, test_result_actions.actor_id AS actor_id, test_resul'
        't_actions.intent_digest AS intent_digest, test_result_actions.request_version_id AS re'
        'quest_version_id, test_result_actions.request_revision AS request_revision, test_resul'
        't_actions.next_request_version_id AS next_request_version_id, test_result_actions.next'
        '_request_revision AS next_request_revision, test_result_actions.run_version_id AS run_'
        'version_id, test_result_actions.run_revision AS run_revision, test_result_actions.next'
        '_run_version_id AS next_run_version_id, test_result_actions.next_run_revision AS next_'
        'run_revision, test_result_actions.capture_id AS capture_id, test_result_actions.projec'
        'tion_id AS projection_id, test_result_actions.input_snapshot AS input_snapshot, test_r'
        'esult_actions.authority_snapshot AS authority_snapshot, test_result_actions.event AS e'
        'vent, test_result_actions.sources AS sources, test_result_actions.required_source_read'
        '_set AS required_source_read_set, test_result_actions.source_basis AS source_basis, te'
        'st_result_actions.reason AS reason, test_result_actions.product_id AS product_id, test'
        '_result_actions.project_id AS project_id, test_result_actions.build_id AS build_id, te'
        'st_result_actions.request_id AS request_id, test_result_actions.run_id AS run_id, test'
        '_result_actions.revision AS revision, test_result_actions.owner_id AS owner_id, test_r'
        'esult_actions.visibility AS visibility, test_result_actions.status AS status, test_res'
        'ult_actions.id AS id, test_result_actions.tenant_id AS tenant_id, test_result_actions.'
        'created_at AS created_at, test_result_actions.category_id AS category_id \nFROM test_r'
        "esult_actions \nWHERE test_result_actions.tenant_id = CAST(nullif(current_setting('pdo"
        "s.tenant_id', true), '') AS UUID)), \nauthoritative_enterprise_sources_test_run AS \n("
        "SELECT 'test_run' AS source_type, shared_enterprise_verification_run_versions.id AS so"
        'urce_id, shared_enterprise_verification_run_versions.tenant_id AS tenant_id, shared_en'
        'terprise_verification_run_versions.category_id AS category_id, shared_enterprise_verif'
        'ication_run_versions.product_id AS product_id, shared_enterprise_verification_run_vers'
        'ions.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_enterprise_ve'
        'rification_run_versions.owner_id AS owner_id, shared_enterprise_verification_run_versi'
        "ons.revision AS source_revision, '\u6d4b\u8bd5\u8fd0\u884c \xb7 ' || CAST(shared_enter"
        'prise_verification_run_versions.run_id AS TEXT) AS title, encode(sha256(convert_to(CAS'
        "T(CAST(jsonb_build_object('object_id', shared_enterprise_verification_run_versions.run"
        "_id, 'kind', 'test_run', 'facts', jsonb_build_object('id', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['id'], 'revision', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['revision'], 'request_id', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['request_id'], 'status', shared_enterprise_verification_run_versions"
        ".run_snapshot['status'], 'result', shared_enterprise_verification_run_versions.run_sna"
        "pshot['result']) || jsonb_build_object('actual_start', jsonb_build_object('occurred_at"
        "', shared_enterprise_verification_run_versions.run_snapshot['actual_start']['occurred_"
        "at'], 'original_timezone', shared_enterprise_verification_run_versions.run_snapshot['a"
        "ctual_start']['original_timezone'], 'effective_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['actual_start']['effective_at']), 'actual_end', jsonb_build_obj"
        "ect('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['actual_en"
        "d']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_versions.r"
        "un_snapshot['actual_end']['original_timezone'], 'effective_at', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['actual_end']['effective_at']), 'preliminary_result"
        "', jsonb_build_object('occurred_at', shared_enterprise_verification_run_versions.run_s"
        "napshot['preliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_v"
        "erification_run_versions.run_snapshot['preliminary_result']['original_timezone'], 'eff"
        "ective_at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_resu"
        "lt']['effective_at']), 'final_result', jsonb_build_object('occurred_at', shared_enterp"
        "rise_verification_run_versions.run_snapshot['final_result']['occurred_at'], 'original_"
        "timezone', shared_enterprise_verification_run_versions.run_snapshot['final_result']['o"
        "riginal_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_sn"
        "apshot['final_result']['effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact_i"
        "d'], 'version', enterprise_reads_test_run.value['expected_revision']) ORDER BY enterpr"
        "ise_reads_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expec"
        "ted_revision'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_"
        'enterprise_verification_run_versions.required_source_read_set) AS enterprise_reads_tes'
        "t_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b"
        '\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b'
        "\u590d\u6838\u3002') AS JSONB) AS TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(j"
        "sonb_build_object('object_id', shared_enterprise_verification_run_versions.run_id, 'ki"
        "nd', 'test_run', 'facts', jsonb_build_object('id', shared_enterprise_verification_run_"
        "versions.run_snapshot['id'], 'revision', shared_enterprise_verification_run_versions.r"
        "un_snapshot['revision'], 'request_id', shared_enterprise_verification_run_versions.run"
        "_snapshot['request_id'], 'status', shared_enterprise_verification_run_versions.run_sna"
        "pshot['status'], 'result', shared_enterprise_verification_run_versions.run_snapshot['r"
        "esult']) || jsonb_build_object('actual_start', jsonb_build_object('occurred_at', share"
        "d_enterprise_verification_run_versions.run_snapshot['actual_start']['occurred_at'], 'o"
        "riginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['actual_st"
        "art']['original_timezone'], 'effective_at', shared_enterprise_verification_run_version"
        "s.run_snapshot['actual_start']['effective_at']), 'actual_end', jsonb_build_object('occ"
        "urred_at', shared_enterprise_verification_run_versions.run_snapshot['actual_end']['occ"
        "urred_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_end']['original_timezone'], 'effective_at', shared_enterprise_verification"
        "_run_versions.run_snapshot['actual_end']['effective_at']), 'preliminary_result', jsonb"
        "_build_object('occurred_at', shared_enterprise_verification_run_versions.run_snapshot["
        "'preliminary_result']['occurred_at'], 'original_timezone', shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['preliminary_result']['original_timezone'], 'effective_a"
        "t', shared_enterprise_verification_run_versions.run_snapshot['preliminary_result']['ef"
        "fective_at']), 'final_result', jsonb_build_object('occurred_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['final_result']['occurred_at'], 'original_timezone"
        "', shared_enterprise_verification_run_versions.run_snapshot['final_result']['original_"
        "timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['"
        "final_result']['effective_at'])), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_buil"
        "d_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact_id'], 've"
        "rsion', enterprise_reads_test_run.value['expected_revision']) ORDER BY enterprise_read"
        "s_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expected_revi"
        "sion'), jsonb_build_array()) AS coalesce_1 \nFROM jsonb_array_elements(shared_enterpri"
        'se_verification_run_versions.required_source_read_set) AS enterprise_reads_test_run(va'
        "lue)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684"
        '\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838'
        "\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared_enter"
        "prise_verification_run_versions.run_id, 'kind', 'test_run', 'facts', jsonb_build_objec"
        "t('id', shared_enterprise_verification_run_versions.run_snapshot['id'], 'revision', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['revision'], 'request_id', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['request_id'], 'status', shared_e"
        "nterprise_verification_run_versions.run_snapshot['status'], 'result', shared_enterpris"
        "e_verification_run_versions.run_snapshot['result']) || jsonb_build_object('actual_star"
        "t', jsonb_build_object('occurred_at', shared_enterprise_verification_run_versions.run_"
        "snapshot['actual_start']['occurred_at'], 'original_timezone', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['actual_start']['original_timezone'], 'effective_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['actual_start']['effective_a"
        "t']), 'actual_end', jsonb_build_object('occurred_at', shared_enterprise_verification_r"
        "un_versions.run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_ent"
        "erprise_verification_run_versions.run_snapshot['actual_end']['original_timezone'], 'ef"
        "fective_at', shared_enterprise_verification_run_versions.run_snapshot['actual_end']['e"
        "ffective_at']), 'preliminary_result', jsonb_build_object('occurred_at', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['preliminary_result']['occurred_at'], 'orig"
        "inal_timezone', shared_enterprise_verification_run_versions.run_snapshot['preliminary_"
        "result']['original_timezone'], 'effective_at', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['preliminary_result']['effective_at']), 'final_result', jsonb_build_"
        "object('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['final_"
        "result']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_versi"
        "ons.run_snapshot['final_result']['original_timezone'], 'effective_at', shared_enterpri"
        "se_verification_run_versions.run_snapshot['final_result']['effective_at'])), 'source_r"
        "efs', (SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'artifact', 'id', enterpri"
        "se_reads_test_run.value['artifact_id'], 'version', enterprise_reads_test_run.value['ex"
        "pected_revision']) ORDER BY enterprise_reads_test_run.value ->> 'artifact_id', enterpr"
        "ise_reads_test_run.value ->> 'expected_revision'), jsonb_build_array()) AS coalesce_1 "
        '\nFROM jsonb_array_elements(shared_enterprise_verification_run_versions.required_sourc'
        "e_read_set) AS enterprise_reads_test_run(value)), 'record_policy', '\u4ec5\u8868\u793a"
        '\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1'
        "\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) AS structured, 'structure"
        "d' AS nature, shared_enterprise_verification_run_versions.visibility != 'category' OR "
        "shared_enterprise_projects.visibility != 'category' OR shared_enterprise_products.visi"
        "bility != 'category' OR (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterpris"
        'e_verification_run_versions.required_source_read_set) AS enterprise_reads_test_run(val'
        'ue) JOIN enterprise_authoritative_artifacts_test_run ON enterprise_authoritative_artif'
        'acts_test_run.tenant_id = shared_enterprise_verification_run_versions.tenant_id AND en'
        'terprise_authoritative_artifacts_test_run.source_id = CAST((enterprise_reads_test_run.'
        "value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritative_artifacts_test_run."
        "private)) OR shared_enterprise_builds.visibility != 'category' AS private, EXISTS (SEL"
        'ECT 1 \nFROM jsonb_array_elements(shared_enterprise_verification_run_versions.required'
        '_source_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative_ar'
        'tifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id = shared_ent'
        'erprise_verification_run_versions.tenant_id AND enterprise_authoritative_artifacts_tes'
        "t_run.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \n"
        'WHERE enterprise_authoritative_artifacts_test_run.customer_original) AS customer_origi'
        'nal, shared_enterprise_verification_current_runs.run_version_id = shared_enterprise_ve'
        'rification_run_versions.id AS is_current, shared_enterprise_verification_run_versions.'
        'created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterprise_verific'
        'ation_run_versions.run_id AS object_id, (SELECT coalesce(array_agg(enterprise_authorit'
        'ative_artifacts_test_run.original_id), ARRAY[]::UUID[]) AS coalesce_2 \nFROM jsonb_arr'
        'ay_elements(shared_enterprise_verification_run_versions.required_source_read_set) AS e'
        'nterprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_test_run ON en'
        'terprise_authoritative_artifacts_test_run.tenant_id = shared_enterprise_verification_r'
        'un_versions.tenant_id AND enterprise_authoritative_artifacts_test_run.source_id = CAST'
        "((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_autho"
        'ritative_artifacts_test_run.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXIST'
        'S (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_verification_run_versions.re'
        'quired_source_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritat'
        'ive_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id = shar'
        'ed_enterprise_verification_run_versions.tenant_id AND enterprise_authoritative_artifac'
        "ts_test_run.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UU"
        'ID) \nWHERE enterprise_authoritative_artifacts_test_run.source_revision != CAST((enter'
        "prise_reads_test_run.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck'"
        " ELSE 'current' END AS read_basis_status \nFROM shared_enterprise_verification_run_ver"
        'sions JOIN shared_enterprise_projects ON shared_enterprise_projects.tenant_id = shared'
        '_enterprise_verification_run_versions.tenant_id AND shared_enterprise_projects.product'
        '_id = shared_enterprise_verification_run_versions.product_id AND shared_enterprise_pro'
        'jects.id = shared_enterprise_verification_run_versions.project_id AND shared_enterpris'
        'e_projects.category_id = shared_enterprise_verification_run_versions.category_id JOIN '
        'shared_enterprise_products ON shared_enterprise_products.tenant_id = shared_enterprise'
        '_verification_run_versions.tenant_id AND shared_enterprise_products.id = shared_enterp'
        'rise_verification_run_versions.product_id AND shared_enterprise_products.category_id ='
        ' shared_enterprise_verification_run_versions.category_id JOIN shared_enterprise_builds'
        ' ON shared_enterprise_builds.tenant_id = shared_enterprise_verification_run_versions.t'
        'enant_id AND shared_enterprise_builds.category_id = shared_enterprise_verification_run'
        '_versions.category_id AND shared_enterprise_builds.product_id = shared_enterprise_veri'
        'fication_run_versions.product_id AND shared_enterprise_builds.project_id = shared_ente'
        'rprise_verification_run_versions.project_id AND shared_enterprise_builds.id = shared_e'
        'nterprise_verification_run_versions.build_id AND shared_enterprise_builds.revision = s'
        'hared_enterprise_verification_run_versions.build_revision JOIN shared_enterprise_verif'
        'ication_current_runs ON shared_enterprise_verification_current_runs.tenant_id = shared'
        '_enterprise_verification_run_versions.tenant_id AND shared_enterprise_verification_cur'
        'rent_runs.product_id = shared_enterprise_verification_run_versions.product_id AND shar'
        'ed_enterprise_verification_current_runs.run_id = shared_enterprise_verification_run_ve'
        'rsions.run_id \nWHERE shared_enterprise_verification_run_versions.tenant_id = CAST(nul'
        "lif(current_setting('pdos.tenant_id', true), '') AS UUID) AND NOT (EXISTS (SELECT 1 \n"
        'FROM jsonb_array_elements(shared_enterprise_verification_run_versions.required_source_'
        'read_set) AS enterprise_reads_test_run(value) \nWHERE NOT (EXISTS (SELECT 1 \nFROM ent'
        'erprise_authoritative_artifacts_test_run \nWHERE enterprise_authoritative_artifacts_te'
        'st_run.tenant_id = shared_enterprise_verification_run_versions.tenant_id AND enterpris'
        'e_authoritative_artifacts_test_run.source_id = CAST((enterprise_reads_test_run.value -'
        ">> 'artifact_id') AS UUID))))) UNION ALL SELECT 'test_run' AS source_type, shared_ente"
        'rprise_test_result_actions.id AS source_id, shared_enterprise_test_result_actions.tena'
        'nt_id AS tenant_id, shared_enterprise_test_result_actions.category_id AS category_id, '
        'shared_enterprise_test_result_actions.product_id AS product_id, shared_enterprise_test'
        '_result_actions.project_id AS project_id, CAST(NULL AS UUID) AS proposal_id, shared_en'
        'terprise_test_result_actions.owner_id AS owner_id, shared_enterprise_test_result_actio'
        'ns.revision AS source_revision, CASE WHEN (shared_enterprise_test_result_actions.opera'
        "tion = 'test.run.review') THEN '\u4e13\u4e1a\u8bc4\u5ba1\u8bb0\u5f55 \xb7 ' WHEN (shar"
        "ed_enterprise_test_result_actions.operation = 'test.disposition.decide') THEN '\u6d4b"
        "\u8bd5\u5904\u7f6e\u8bb0\u5f55 \xb7 ' ELSE '\u6d4b\u8bd5\u7ed3\u679c\u8bb0\u5f55 \xb7 "
        "' END || CAST(shared_enterprise_test_result_actions.run_id AS TEXT) AS title, encode(s"
        "ha256(convert_to(CAST(CAST(jsonb_build_object('object_id', shared_enterprise_test_resu"
        "lt_actions.run_id, 'kind', 'test_run', 'facts', (jsonb_build_object('id', shared_enter"
        "prise_verification_run_versions.run_snapshot['id'], 'revision', shared_enterprise_veri"
        "fication_run_versions.run_snapshot['revision'], 'request_id', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['request_id'], 'status', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['status'], 'result', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['result']) || jsonb_build_object('record_kind', 'test_run', 'cove"
        "rage', (SELECT coalesce(jsonb_agg(jsonb_build_object('sample_id', enterprise_run_cover"
        "age.value['sample_id'], 'item_id', enterprise_run_coverage.value['item_id']) ORDER BY "
        'enterprise_run_coverage.ordinal), jsonb_build_array()) AS coalesce_3 \nFROM jsonb_arra'
        "y_elements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['coverage"
        "'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_coverage(value, ordinal)),"
        " 'computed_results', (SELECT coalesce(jsonb_agg(jsonb_build_object('coverage', enterpr"
        "ise_computed_results.value['coverage'], 'result', enterprise_computed_results.value['r"
        "esult'], 'measurement_id', enterprise_computed_results.value['measurement_id']) ORDER "
        'BY enterprise_computed_results.ordinal), jsonb_build_array()) AS coalesce_4 \nFROM jso'
        "nb_array_elements(coalesce(shared_enterprise_verification_run_versions.run_snapshot['c"
        "omputed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_computed_result"
        "s(value, ordinal)), 'professional_conclusion', CASE WHEN (((shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['professional_conclusion']) ->> 'actor_id') IS NULL) TH"
        "EN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_enterprise_verification_"
        "run_versions.run_snapshot['professional_conclusion']['text'], 'actor_id', shared_enter"
        "prise_verification_run_versions.run_snapshot['professional_conclusion']['actor_id']) |"
        "| jsonb_build_object('at', CASE WHEN (((shared_enterprise_verification_run_versions.ru"
        "n_snapshot['professional_conclusion']['at']) ->> 'occurred_at') IS NULL) THEN CAST(NUL"
        "L AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_run_"
        "versions.run_snapshot['professional_conclusion']['at']['occurred_at'], 'original_timez"
        "one', shared_enterprise_verification_run_versions.run_snapshot['professional_conclusio"
        "n']['at']['original_timezone'], 'effective_at', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['professional_conclusion']['at']['effective_at'], 'received_at', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['professional_conclusion']['at'"
        "]['received_at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot"
        "['professional_conclusion']['at']['actor_id']) END, 'source_reference', jsonb_build_ob"
        "ject('kind', shared_enterprise_verification_run_versions.run_snapshot['professional_co"
        "nclusion']['source']['kind'], 'id', shared_enterprise_verification_run_versions.run_sn"
        "apshot['professional_conclusion']['source']['id'], 'revision', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['professional_conclusion']['source']['revision'])) E"
        "ND, 'disposition', CASE WHEN (((shared_enterprise_verification_run_versions.run_snapsh"
        "ot['disposition']) ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_"
        "object('text', shared_enterprise_verification_run_versions.run_snapshot['disposition']"
        "['text'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['dispos"
        "ition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['disposition']['at']) ->> 'occurred_at') IS NULL) THE"
        "N CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verific"
        "ation_run_versions.run_snapshot['disposition']['at']['occurred_at'], 'original_timezon"
        "e', shared_enterprise_verification_run_versions.run_snapshot['disposition']['at']['ori"
        "ginal_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snap"
        "shot['disposition']['at']['effective_at'], 'received_at', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['disposition']['at']['received_at'], 'actor_id', shared_e"
        "nterprise_verification_run_versions.run_snapshot['disposition']['at']['actor_id']) END"
        ", 'source_reference', jsonb_build_object('kind', shared_enterprise_verification_run_ve"
        "rsions.run_snapshot['disposition']['source']['kind'], 'id', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['disposition']['source']['id'], 'revision', shared_ente"
        "rprise_verification_run_versions.run_snapshot['disposition']['source']['revision'])) E"
        "ND, 'actual_start', CASE WHEN (((shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_b"
        "uild_object('occurred_at', shared_enterprise_verification_run_versions.run_snapshot['a"
        "ctual_start']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_"
        "versions.run_snapshot['actual_start']['original_timezone'], 'effective_at', shared_ent"
        "erprise_verification_run_versions.run_snapshot['actual_start']['effective_at'], 'recei"
        "ved_at', shared_enterprise_verification_run_versions.run_snapshot['actual_start']['rec"
        "eived_at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['actu"
        "al_start']['actor_id']) END, 'actual_end', CASE WHEN (((shared_enterprise_verification"
        "_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS NULL) THEN CAST(NULL A"
        "S JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['actual_end']['occurred_at'], 'original_timezone', shared_enterpris"
        "e_verification_run_versions.run_snapshot['actual_end']['original_timezone'], 'effectiv"
        "e_at', shared_enterprise_verification_run_versions.run_snapshot['actual_end']['effecti"
        "ve_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapshot['actu"
        "al_end']['received_at'], 'actor_id', shared_enterprise_verification_run_versions.run_s"
        "napshot['actual_end']['actor_id']) END, 'preliminary_result', CASE WHEN (((shared_ente"
        "rprise_verification_run_versions.run_snapshot['preliminary_result']) ->> 'occurred_at'"
        ") IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_ente"
        "rprise_verification_run_versions.run_snapshot['preliminary_result']['occurred_at'], 'o"
        "riginal_timezone', shared_enterprise_verification_run_versions.run_snapshot['prelimina"
        "ry_result']['original_timezone'], 'effective_at', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['preliminary_result']['effective_at'], 'received_at', shared_ente"
        "rprise_verification_run_versions.run_snapshot['preliminary_result']['received_at'], 'a"
        "ctor_id', shared_enterprise_verification_run_versions.run_snapshot['preliminary_result"
        "']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterprise_verification_run_v"
        "ersions.run_snapshot['final_result']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JS"
        "ONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_run_version"
        "s.run_snapshot['final_result']['occurred_at'], 'original_timezone', shared_enterprise_"
        "verification_run_versions.run_snapshot['final_result']['original_timezone'], 'effectiv"
        "e_at', shared_enterprise_verification_run_versions.run_snapshot['final_result']['effec"
        "tive_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapshot['fi"
        "nal_result']['received_at'], 'actor_id', shared_enterprise_verification_run_versions.r"
        "un_snapshot['final_result']['actor_id']) END)) || jsonb_build_object('record_kind', 't"
        "est_result_action', 'operation', shared_enterprise_test_result_actions.operation, 'act"
        "or_id', shared_enterprise_test_result_actions.actor_id, 'run_version_id', shared_enter"
        "prise_verification_run_versions.id, 'run_revision', shared_enterprise_verification_run"
        "_versions.revision), 'source_refs', (SELECT coalesce(jsonb_agg(jsonb_build_object('typ"
        "e', 'artifact', 'id', enterprise_reads_test_run.value['artifact_id'], 'version', enter"
        "prise_reads_test_run.value['expected_revision']) ORDER BY enterprise_reads_test_run.va"
        "lue ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expected_revision'), jsonb"
        '_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_enterprise_test_resul'
        "t_actions.required_source_read_set) AS enterprise_reads_test_run(value)), 'record_poli"
        "cy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0\u7684\u4e8b\u5b9e\uff0c"
        "\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d\u6838\u3002') AS JSONB) A"
        "S TEXT), 'UTF8')), 'hex') AS content_hash, CAST(CAST(jsonb_build_object('object_id', s"
        "hared_enterprise_test_result_actions.run_id, 'kind', 'test_run', 'facts', (jsonb_build"
        "_object('id', shared_enterprise_verification_run_versions.run_snapshot['id'], 'revisio"
        "n', shared_enterprise_verification_run_versions.run_snapshot['revision'], 'request_id'"
        ", shared_enterprise_verification_run_versions.run_snapshot['request_id'], 'status', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['status'], 'result', shared_ent"
        "erprise_verification_run_versions.run_snapshot['result']) || jsonb_build_object('recor"
        "d_kind', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(jsonb_build_object('sample"
        "_id', enterprise_run_coverage.value['sample_id'], 'item_id', enterprise_run_coverage.v"
        "alue['item_id']) ORDER BY enterprise_run_coverage.ordinal), jsonb_build_array()) AS co"
        'alesce_3 \nFROM jsonb_array_elements(coalesce(shared_enterprise_verification_run_versi'
        "ons.run_snapshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_"
        "coverage(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jsonb_build_"
        "object('coverage', enterprise_computed_results.value['coverage'], 'result', enterprise"
        "_computed_results.value['result'], 'measurement_id', enterprise_computed_results.value"
        "['measurement_id']) ORDER BY enterprise_computed_results.ordinal), jsonb_build_array()"
        ') AS coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterprise_verification_ru'
        "n_versions.run_snapshot['computed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS "
        "enterprise_computed_results(value, ordinal)), 'professional_conclusion', CASE WHEN ((("
        "shared_enterprise_verification_run_versions.run_snapshot['professional_conclusion']) -"
        ">> 'actor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', share"
        "d_enterprise_verification_run_versions.run_snapshot['professional_conclusion']['text']"
        ", 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['professional_c"
        "onclusion']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_ve"
        "rification_run_versions.run_snapshot['professional_conclusion']['at']) ->> 'occurred_a"
        "t') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_en"
        "terprise_verification_run_versions.run_snapshot['professional_conclusion']['at']['occu"
        "rred_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_snapsh"
        "ot['professional_conclusion']['at']['original_timezone'], 'effective_at', shared_enter"
        "prise_verification_run_versions.run_snapshot['professional_conclusion']['at']['effecti"
        "ve_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapshot['prof"
        "essional_conclusion']['at']['received_at'], 'actor_id', shared_enterprise_verification"
        "_run_versions.run_snapshot['professional_conclusion']['at']['actor_id']) END, 'source_"
        "reference', jsonb_build_object('kind', shared_enterprise_verification_run_versions.run"
        "_snapshot['professional_conclusion']['source']['kind'], 'id', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['professional_conclusion']['source']['id'], 'revision"
        "', shared_enterprise_verification_run_versions.run_snapshot['professional_conclusion']"
        "['source']['revision'])) END, 'disposition', CASE WHEN (((shared_enterprise_verificati"
        "on_run_versions.run_snapshot['disposition']) ->> 'actor_id') IS NULL) THEN CAST(NULL A"
        "S JSONB) ELSE jsonb_build_object('text', shared_enterprise_verification_run_versions.r"
        "un_snapshot['disposition']['text'], 'actor_id', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN ("
        "((shared_enterprise_verification_run_versions.run_snapshot['disposition']['at']) ->> '"
        "occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at',"
        " shared_enterprise_verification_run_versions.run_snapshot['disposition']['at']['occurr"
        "ed_at'], 'original_timezone', shared_enterprise_verification_run_versions.run_snapshot"
        "['disposition']['at']['original_timezone'], 'effective_at', shared_enterprise_verifica"
        "tion_run_versions.run_snapshot['disposition']['at']['effective_at'], 'received_at', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['disposition']['at']['received_"
        "at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['dispositio"
        "n']['at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', shared_ente"
        "rprise_verification_run_versions.run_snapshot['disposition']['source']['kind'], 'id', "
        "shared_enterprise_verification_run_versions.run_snapshot['disposition']['source']['id'"
        "], 'revision', shared_enterprise_verification_run_versions.run_snapshot['disposition']"
        "['source']['revision'])) END, 'actual_start', CASE WHEN (((shared_enterprise_verificat"
        "ion_run_versions.run_snapshot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(N"
        "ULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_ru"
        "n_versions.run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared_en"
        "terprise_verification_run_versions.run_snapshot['actual_start']['original_timezone'], "
        "'effective_at', shared_enterprise_verification_run_versions.run_snapshot['actual_start"
        "']['effective_at'], 'received_at', shared_enterprise_verification_run_versions.run_sna"
        "pshot['actual_start']['received_at'], 'actor_id', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['actual_start']['actor_id']) END, 'actual_end', CASE WHEN (((shar"
        "ed_enterprise_verification_run_versions.run_snapshot['actual_end']) ->> 'occurred_at')"
        " IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enter"
        "prise_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'original_t"
        "imezone', shared_enterprise_verification_run_versions.run_snapshot['actual_end']['orig"
        "inal_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snaps"
        "hot['actual_end']['effective_at'], 'received_at', shared_enterprise_verification_run_v"
        "ersions.run_snapshot['actual_end']['received_at'], 'actor_id', shared_enterprise_verif"
        "ication_run_versions.run_snapshot['actual_end']['actor_id']) END, 'preliminary_result'"
        ", CASE WHEN (((shared_enterprise_verification_run_versions.run_snapshot['preliminary_r"
        "esult']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object("
        "'occurred_at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_r"
        "esult']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['preliminary_result']['original_timezone'], 'effective_at', shared_ent"
        "erprise_verification_run_versions.run_snapshot['preliminary_result']['effective_at'], "
        "'received_at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_r"
        "esult']['received_at'], 'actor_id', shared_enterprise_verification_run_versions.run_sn"
        "apshot['preliminary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_ent"
        "erprise_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at') IS "
        "NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpris"
        "e_verification_run_versions.run_snapshot['final_result']['occurred_at'], 'original_tim"
        "ezone', shared_enterprise_verification_run_versions.run_snapshot['final_result']['orig"
        "inal_timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snaps"
        "hot['final_result']['effective_at'], 'received_at', shared_enterprise_verification_run"
        "_versions.run_snapshot['final_result']['received_at'], 'actor_id', shared_enterprise_v"
        "erification_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_buil"
        "d_object('record_kind', 'test_result_action', 'operation', shared_enterprise_test_resu"
        "lt_actions.operation, 'actor_id', shared_enterprise_test_result_actions.actor_id, 'run"
        "_version_id', shared_enterprise_verification_run_versions.id, 'run_revision', shared_e"
        "nterprise_verification_run_versions.revision), 'source_refs', (SELECT coalesce(jsonb_a"
        "gg(jsonb_build_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artif"
        "act_id'], 'version', enterprise_reads_test_run.value['expected_revision']) ORDER BY en"
        "terprise_reads_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> '"
        "expected_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(sh"
        'ared_enterprise_test_result_actions.required_source_read_set) AS enterprise_reads_test'
        "_run(value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS TEXT) AS body, CAST(jsonb_build_object('object_id', shared"
        "_enterprise_test_result_actions.run_id, 'kind', 'test_run', 'facts', (jsonb_build_obje"
        "ct('id', shared_enterprise_verification_run_versions.run_snapshot['id'], 'revision', s"
        "hared_enterprise_verification_run_versions.run_snapshot['revision'], 'request_id', sha"
        "red_enterprise_verification_run_versions.run_snapshot['request_id'], 'status', shared_"
        "enterprise_verification_run_versions.run_snapshot['status'], 'result', shared_enterpri"
        "se_verification_run_versions.run_snapshot['result']) || jsonb_build_object('record_kin"
        "d', 'test_run', 'coverage', (SELECT coalesce(jsonb_agg(jsonb_build_object('sample_id',"
        " enterprise_run_coverage.value['sample_id'], 'item_id', enterprise_run_coverage.value["
        "'item_id']) ORDER BY enterprise_run_coverage.ordinal), jsonb_build_array()) AS coalesc"
        'e_3 \nFROM jsonb_array_elements(coalesce(shared_enterprise_verification_run_versions.r'
        "un_snapshot['coverage'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enterprise_run_cover"
        "age(value, ordinal)), 'computed_results', (SELECT coalesce(jsonb_agg(jsonb_build_objec"
        "t('coverage', enterprise_computed_results.value['coverage'], 'result', enterprise_comp"
        "uted_results.value['result'], 'measurement_id', enterprise_computed_results.value['mea"
        "surement_id']) ORDER BY enterprise_computed_results.ordinal), jsonb_build_array()) AS "
        'coalesce_4 \nFROM jsonb_array_elements(coalesce(shared_enterprise_verification_run_ver'
        "sions.run_snapshot['computed_results'], CAST('[]' AS JSONB))) WITH ORDINALITY AS enter"
        "prise_computed_results(value, ordinal)), 'professional_conclusion', CASE WHEN (((share"
        "d_enterprise_verification_run_versions.run_snapshot['professional_conclusion']) ->> 'a"
        "ctor_id') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('text', shared_ent"
        "erprise_verification_run_versions.run_snapshot['professional_conclusion']['text'], 'ac"
        "tor_id', shared_enterprise_verification_run_versions.run_snapshot['professional_conclu"
        "sion']['actor_id']) || jsonb_build_object('at', CASE WHEN (((shared_enterprise_verific"
        "ation_run_versions.run_snapshot['professional_conclusion']['at']) ->> 'occurred_at') I"
        "S NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['professional_conclusion']['at']['occurred_"
        "at'], 'original_timezone', shared_enterprise_verification_run_versions.run_snapshot['p"
        "rofessional_conclusion']['at']['original_timezone'], 'effective_at', shared_enterprise"
        "_verification_run_versions.run_snapshot['professional_conclusion']['at']['effective_at"
        "'], 'received_at', shared_enterprise_verification_run_versions.run_snapshot['professio"
        "nal_conclusion']['at']['received_at'], 'actor_id', shared_enterprise_verification_run_"
        "versions.run_snapshot['professional_conclusion']['at']['actor_id']) END, 'source_refer"
        "ence', jsonb_build_object('kind', shared_enterprise_verification_run_versions.run_snap"
        "shot['professional_conclusion']['source']['kind'], 'id', shared_enterprise_verificatio"
        "n_run_versions.run_snapshot['professional_conclusion']['source']['id'], 'revision', sh"
        "ared_enterprise_verification_run_versions.run_snapshot['professional_conclusion']['sou"
        "rce']['revision'])) END, 'disposition', CASE WHEN (((shared_enterprise_verification_ru"
        "n_versions.run_snapshot['disposition']) ->> 'actor_id') IS NULL) THEN CAST(NULL AS JSO"
        "NB) ELSE jsonb_build_object('text', shared_enterprise_verification_run_versions.run_sn"
        "apshot['disposition']['text'], 'actor_id', shared_enterprise_verification_run_versions"
        ".run_snapshot['disposition']['actor_id']) || jsonb_build_object('at', CASE WHEN (((sha"
        "red_enterprise_verification_run_versions.run_snapshot['disposition']['at']) ->> 'occur"
        "red_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shar"
        "ed_enterprise_verification_run_versions.run_snapshot['disposition']['at']['occurred_at"
        "'], 'original_timezone', shared_enterprise_verification_run_versions.run_snapshot['dis"
        "position']['at']['original_timezone'], 'effective_at', shared_enterprise_verification_"
        "run_versions.run_snapshot['disposition']['at']['effective_at'], 'received_at', shared_"
        "enterprise_verification_run_versions.run_snapshot['disposition']['at']['received_at'],"
        " 'actor_id', shared_enterprise_verification_run_versions.run_snapshot['disposition']['"
        "at']['actor_id']) END, 'source_reference', jsonb_build_object('kind', shared_enterpris"
        "e_verification_run_versions.run_snapshot['disposition']['source']['kind'], 'id', share"
        "d_enterprise_verification_run_versions.run_snapshot['disposition']['source']['id'], 'r"
        "evision', shared_enterprise_verification_run_versions.run_snapshot['disposition']['sou"
        "rce']['revision'])) END, 'actual_start', CASE WHEN (((shared_enterprise_verification_r"
        "un_versions.run_snapshot['actual_start']) ->> 'occurred_at') IS NULL) THEN CAST(NULL A"
        "S JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_verification_run_ver"
        "sions.run_snapshot['actual_start']['occurred_at'], 'original_timezone', shared_enterpr"
        "ise_verification_run_versions.run_snapshot['actual_start']['original_timezone'], 'effe"
        "ctive_at', shared_enterprise_verification_run_versions.run_snapshot['actual_start']['e"
        "ffective_at'], 'received_at', shared_enterprise_verification_run_versions.run_snapshot"
        "['actual_start']['received_at'], 'actor_id', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['actual_start']['actor_id']) END, 'actual_end', CASE WHEN (((shared_en"
        "terprise_verification_run_versions.run_snapshot['actual_end']) ->> 'occurred_at') IS N"
        "ULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise"
        "_verification_run_versions.run_snapshot['actual_end']['occurred_at'], 'original_timezo"
        "ne', shared_enterprise_verification_run_versions.run_snapshot['actual_end']['original_"
        "timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['"
        "actual_end']['effective_at'], 'received_at', shared_enterprise_verification_run_versio"
        "ns.run_snapshot['actual_end']['received_at'], 'actor_id', shared_enterprise_verificati"
        "on_run_versions.run_snapshot['actual_end']['actor_id']) END, 'preliminary_result', CAS"
        "E WHEN (((shared_enterprise_verification_run_versions.run_snapshot['preliminary_result"
        "']) ->> 'occurred_at') IS NULL) THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occu"
        "rred_at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_result"
        "']['occurred_at'], 'original_timezone', shared_enterprise_verification_run_versions.ru"
        "n_snapshot['preliminary_result']['original_timezone'], 'effective_at', shared_enterpri"
        "se_verification_run_versions.run_snapshot['preliminary_result']['effective_at'], 'rece"
        "ived_at', shared_enterprise_verification_run_versions.run_snapshot['preliminary_result"
        "']['received_at'], 'actor_id', shared_enterprise_verification_run_versions.run_snapsho"
        "t['preliminary_result']['actor_id']) END, 'final_result', CASE WHEN (((shared_enterpri"
        "se_verification_run_versions.run_snapshot['final_result']) ->> 'occurred_at') IS NULL)"
        " THEN CAST(NULL AS JSONB) ELSE jsonb_build_object('occurred_at', shared_enterprise_ver"
        "ification_run_versions.run_snapshot['final_result']['occurred_at'], 'original_timezone"
        "', shared_enterprise_verification_run_versions.run_snapshot['final_result']['original_"
        "timezone'], 'effective_at', shared_enterprise_verification_run_versions.run_snapshot['"
        "final_result']['effective_at'], 'received_at', shared_enterprise_verification_run_vers"
        "ions.run_snapshot['final_result']['received_at'], 'actor_id', shared_enterprise_verifi"
        "cation_run_versions.run_snapshot['final_result']['actor_id']) END)) || jsonb_build_obj"
        "ect('record_kind', 'test_result_action', 'operation', shared_enterprise_test_result_ac"
        "tions.operation, 'actor_id', shared_enterprise_test_result_actions.actor_id, 'run_vers"
        "ion_id', shared_enterprise_verification_run_versions.id, 'run_revision', shared_enterp"
        "rise_verification_run_versions.revision), 'source_refs', (SELECT coalesce(jsonb_agg(js"
        "onb_build_object('type', 'artifact', 'id', enterprise_reads_test_run.value['artifact_i"
        "d'], 'version', enterprise_reads_test_run.value['expected_revision']) ORDER BY enterpr"
        "ise_reads_test_run.value ->> 'artifact_id', enterprise_reads_test_run.value ->> 'expec"
        "ted_revision'), jsonb_build_array()) AS coalesce_5 \nFROM jsonb_array_elements(shared_"
        'enterprise_test_result_actions.required_source_read_set) AS enterprise_reads_test_run('
        "value)), 'record_policy', '\u4ec5\u8868\u793a\u8be5\u7248\u672c\u5df2\u767b\u8bb0"
        '\u7684\u4e8b\u5b9e\uff0c\u5f53\u524d\u4e1a\u52a1\u9002\u7528\u6027\u4ecd\u987b\u590d'
        "\u6838\u3002') AS JSONB) AS structured, 'structured' AS nature, shared_enterprise_test"
        "_result_actions.visibility != 'category' OR shared_enterprise_projects.visibility != '"
        "category' OR shared_enterprise_products.visibility != 'category' OR (EXISTS (SELECT 1 "
        '\nFROM jsonb_array_elements(shared_enterprise_test_result_actions.required_source_read'
        '_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_test'
        '_run ON enterprise_authoritative_artifacts_test_run.tenant_id = shared_enterprise_test'
        '_result_actions.tenant_id AND enterprise_authoritative_artifacts_test_run.source_id = '
        "CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_a"
        'uthoritative_artifacts_test_run.private)) OR shared_enterprise_verification_run_versio'
        "ns.visibility != 'category' OR shared_enterprise_builds.visibility != 'category' AS pr"
        'ivate, EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_test_result_acti'
        'ons.required_source_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_auth'
        'oritative_artifacts_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id '
        '= shared_enterprise_test_result_actions.tenant_id AND enterprise_authoritative_artifac'
        "ts_test_run.source_id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UU"
        'ID) \nWHERE enterprise_authoritative_artifacts_test_run.customer_original) AS customer'
        '_original, shared_enterprise_verification_current_runs.run_version_id = shared_enterpr'
        'ise_test_result_actions.next_run_version_id AS is_current, shared_enterprise_test_resu'
        'lt_actions.created_at AS created_at, CAST(NULL AS UUID) AS original_id, shared_enterpr'
        'ise_test_result_actions.run_id AS object_id, (SELECT coalesce(array_agg(enterprise_aut'
        'horitative_artifacts_test_run.original_id), ARRAY[]::UUID[]) AS coalesce_6 \nFROM json'
        'b_array_elements(shared_enterprise_test_result_actions.required_source_read_set) AS en'
        'terprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts_test_run ON ent'
        'erprise_authoritative_artifacts_test_run.tenant_id = shared_enterprise_test_result_act'
        'ions.tenant_id AND enterprise_authoritative_artifacts_test_run.source_id = CAST((enter'
        "prise_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterprise_authoritativ"
        'e_artifacts_test_run.original_id IS NOT NULL) AS original_ids, CASE WHEN (EXISTS (SELE'
        'CT 1 \nFROM jsonb_array_elements(shared_enterprise_test_result_actions.required_source'
        '_read_set) AS enterprise_reads_test_run(value) JOIN enterprise_authoritative_artifacts'
        '_test_run ON enterprise_authoritative_artifacts_test_run.tenant_id = shared_enterprise'
        '_test_result_actions.tenant_id AND enterprise_authoritative_artifacts_test_run.source_'
        "id = CAST((enterprise_reads_test_run.value ->> 'artifact_id') AS UUID) \nWHERE enterpr"
        'ise_authoritative_artifacts_test_run.source_revision != CAST((enterprise_reads_test_ru'
        "n.value ->> 'expected_revision') AS INTEGER))) THEN 'needs_recheck' ELSE 'current' END"
        ' AS read_basis_status \nFROM shared_enterprise_test_result_actions JOIN shared_enterpr'
        'ise_projects ON shared_enterprise_projects.tenant_id = shared_enterprise_test_result_a'
        'ctions.tenant_id AND shared_enterprise_projects.product_id = shared_enterprise_test_re'
        'sult_actions.product_id AND shared_enterprise_projects.id = shared_enterprise_test_res'
        'ult_actions.project_id AND shared_enterprise_projects.category_id = shared_enterprise_'
        'test_result_actions.category_id JOIN shared_enterprise_products ON shared_enterprise_p'
        'roducts.tenant_id = shared_enterprise_test_result_actions.tenant_id AND shared_enterpr'
        'ise_products.id = shared_enterprise_test_result_actions.product_id AND shared_enterpri'
        'se_products.category_id = shared_enterprise_test_result_actions.category_id JOIN share'
        'd_enterprise_verification_run_versions ON shared_enterprise_verification_run_versions.'
        'tenant_id = shared_enterprise_test_result_actions.tenant_id AND shared_enterprise_veri'
        'fication_run_versions.category_id = shared_enterprise_test_result_actions.category_id '
        'AND shared_enterprise_verification_run_versions.product_id = shared_enterprise_test_re'
        'sult_actions.product_id AND shared_enterprise_verification_run_versions.project_id = s'
        'hared_enterprise_test_result_actions.project_id AND shared_enterprise_verification_run'
        '_versions.build_id = shared_enterprise_test_result_actions.build_id AND shared_enterpr'
        'ise_verification_run_versions.run_id = shared_enterprise_test_result_actions.run_id AN'
        'D shared_enterprise_verification_run_versions.id = shared_enterprise_test_result_actio'
        'ns.next_run_version_id AND shared_enterprise_verification_run_versions.revision = shar'
        'ed_enterprise_test_result_actions.next_run_revision JOIN shared_enterprise_builds ON s'
        'hared_enterprise_builds.tenant_id = shared_enterprise_test_result_actions.tenant_id AN'
        'D shared_enterprise_builds.category_id = shared_enterprise_test_result_actions.categor'
        'y_id AND shared_enterprise_builds.product_id = shared_enterprise_test_result_actions.p'
        'roduct_id AND shared_enterprise_builds.project_id = shared_enterprise_test_result_acti'
        'ons.project_id AND shared_enterprise_builds.id = shared_enterprise_test_result_actions'
        '.build_id AND shared_enterprise_builds.revision = shared_enterprise_verification_run_v'
        'ersions.build_revision JOIN shared_enterprise_verification_current_runs ON shared_ente'
        'rprise_verification_current_runs.tenant_id = shared_enterprise_test_result_actions.ten'
        'ant_id AND shared_enterprise_verification_current_runs.product_id = shared_enterprise_'
        'test_result_actions.product_id AND shared_enterprise_verification_current_runs.run_id '
        '= shared_enterprise_test_result_actions.run_id \nWHERE shared_enterprise_test_result_a'
        "ctions.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true), '') AS UUID) A"
        'ND NOT (EXISTS (SELECT 1 \nFROM jsonb_array_elements(shared_enterprise_test_result_act'
        'ions.required_source_read_set) AS enterprise_reads_test_run(value) \nWHERE NOT (EXISTS'
        ' (SELECT 1 \nFROM enterprise_authoritative_artifacts_test_run \nWHERE enterprise_autho'
        'ritative_artifacts_test_run.tenant_id = shared_enterprise_test_result_actions.tenant_i'
        'd AND enterprise_authoritative_artifacts_test_run.source_id = CAST((enterprise_reads_t'
        "est_run.value ->> 'artifact_id') AS UUID))))))\n SELECT EXISTS (SELECT 1 \nFROM author"
        'itative_enterprise_sources_test_run \nWHERE authoritative_enterprise_sources_test_run.'
        'tenant_id = t AND authoritative_enterprise_sources_test_run.category_id = c AND CAST(a'
        "uthoritative_enterprise_sources_test_run.source_id AS TEXT) = expected->>'source_id' A"
        'ND CAST(authoritative_enterprise_sources_test_run.source_revision AS TEXT) = expected-'
        ">>'source_revision' AND authoritative_enterprise_sources_test_run.content_hash = expec"
        "ted->>'content_hash') AS anon_1 INTO visible;\n  ELSE RETURN false; END CASE;\n  IF vi"
        'sible IS DISTINCT FROM true THEN RETURN false; END IF;\n END LOOP;\n RETURN true;\nEXC'
        'EPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN fals'
        'e;\nEND\n;\n$knowledge_answer_acl$;\n\nREVOKE ALL ON FUNCTION public.knowledge_answer_'
        'sources_visible(uuid,uuid,jsonb) FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,p'
        'dos_next_dispatch;\n\nGRANT EXECUTE ON FUNCTION public.knowledge_answer_sources_visibl'
        'e(uuid,uuid,jsonb) TO pdos_next_app;\n\nCREATE POLICY knowledge_answer_source_read ON '
        'public.category_knowledge_entries AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (an'
        'swer_sources IS NULL OR public.knowledge_answer_sources_visible(tenant_id,category_id,'
        'answer_sources));\n\nCREATE POLICY knowledge_answer_source_read ON public.knowledge_ca'
        "ndidate_versions AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (source_basis->'answ"
        "er_sources' IS NULL OR public.knowledge_answer_sources_visible(tenant_id,category_id,s"
        "ource_basis->'answer_sources'));\n\nCREATE POLICY knowledge_answer_source_read ON publ"
        'ic.knowledge_rule_versions AS RESTRICTIVE FOR SELECT TO pdos_next_app USING (source_ba'
        "sis->'answer_sources' IS NULL OR public.knowledge_answer_sources_visible(tenant_id,cat"
        "egory_id,source_basis->'answer_sources'));\n\n\nCREATE TABLE knowledge_answer_reviews "
        '(\n\tcategory_id UUID NOT NULL, \n\tsubject_kind TEXT NOT NULL, \n\tsubject_id UUID NO'
        'T NULL, \n\tresponsible_id UUID NOT NULL, \n\tapplicability_scope TEXT NOT NULL, \n\tr'
        'eview_due_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\torigin_run_id UUID, \n\tanswer_dig'
        'est TEXT, \n\tsource_proof JSONB NOT NULL, \n\tbasis_count INTEGER NOT NULL, \n\tverif'
        'ied_by UUID, \n\tcommand_id UUID NOT NULL, \n\treceipt_id UUID NOT NULL, \n\tid UUID N'
        'OT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL'
        ', \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories '
        '(tenant_id, id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, subject_kind, subj'
        'ect_id), \n\tFOREIGN KEY(tenant_id, responsible_id) REFERENCES principals (tenant_id, '
        'id), \n\tFOREIGN KEY(tenant_id, verified_by) REFERENCES principals (tenant_id, id), \n'
        '\tFOREIGN KEY(tenant_id, origin_run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOR'
        'EIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE '
        "INITIALLY DEFERRED, \n\tCHECK (subject_kind IN ('category','candidate','rule')), \n\tC"
        "HECK (length(applicability_scope)>0 AND jsonb_typeof(source_proof)='array'), \n\tCHECK"
        ' (basis_count>=jsonb_array_length(source_proof) AND basis_count>=0), \n\tCHECK ((origi'
        'n_run_id IS NULL)=(answer_digest IS NULL)), \n\tCHECK (answer_digest IS NULL OR answer'
        "_digest ~ '^[a-f0-9]{64}$')\n)\n\n;\n\nCREATE INDEX ix_knowledge_answer_reviews_catego"
        'ry_id ON knowledge_answer_reviews (category_id);\n\nCREATE INDEX ix_knowledge_answer_r'
        'eviews_tenant_id ON knowledge_answer_reviews (tenant_id);\n\nALTER TABLE public.knowle'
        'dge_answer_reviews ENABLE ROW LEVEL SECURITY;\n\nALTER TABLE public.knowledge_answer_r'
        'eviews FORCE ROW LEVEL SECURITY;\n\nCREATE POLICY owner_internal ON public.knowledge_a'
        'nswer_reviews TO pdos_next_owner USING(true) WITH CHECK(true);\n\nCREATE POLICY contri'
        'bution_read ON public.knowledge_answer_reviews FOR SELECT TO pdos_next_app USING(tenan'
        "t_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid AND public.category_acces"
        "s(tenant_id,category_id,false) AND ((subject_kind='category' AND EXISTS(SELECT 1 FROM "
        'public.category_knowledge_entries k\n WHERE k.tenant_id=knowledge_answer_reviews.tenan'
        't_id AND k.category_id=knowledge_answer_reviews.category_id AND k.id=subject_id))\n OR'
        " (subject_kind='candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_version"
        's k\n WHERE k.tenant_id=knowledge_answer_reviews.tenant_id AND k.category_id=knowledge'
        "_answer_reviews.category_id AND k.id=subject_id))\n OR (subject_kind='rule' AND EXISTS"
        '(SELECT 1 FROM public.knowledge_rule_versions k\n WHERE k.tenant_id=knowledge_answer_r'
        'eviews.tenant_id AND k.category_id=knowledge_answer_reviews.category_id AND k.id=subje'
        'ct_id))));\n\nCREATE POLICY contribution_append ON public.knowledge_answer_reviews FOR'
        " INSERT TO pdos_next_app WITH CHECK(tenant_id=nullif(current_setting('pdos.tenant_id',"
        "true),'')::uuid\n AND public.scope_actor()=public.scope_requester()\n AND EXISTS(SELEC"
        "T 1 FROM public.principals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id'"
        ",true),'')::uuid\n AND h.id=public.scope_actor() AND h.kind='human' AND h.active) AND "
        'public.category_access(tenant_id,category_id,false));\n\nREVOKE ALL ON public.knowledg'
        'e_answer_reviews FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatc'
        'h;\n\nGRANT SELECT,INSERT ON public.knowledge_answer_reviews TO pdos_next_app;\n\n\nCR'
        'EATE TABLE knowledge_gap_submissions (\n\tcategory_id UUID NOT NULL, \n\towner_id UUID'
        ' NOT NULL, \n\trecipient_id UUID NOT NULL, \n\trun_id UUID NOT NULL, \n\tfeedback_id U'
        'UID, \n\trequest_key UUID NOT NULL, \n\trequest_sha256 TEXT NOT NULL, \n\tkind TEXT NO'
        'T NULL, \n\tquestion TEXT NOT NULL, \n\tanswer TEXT, \n\tsearch_scope JSONB NOT NULL, '
        '\n\tsource_proof JSONB NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n'
        '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY('
        'tenant_id, category_id) REFERENCES categories (tenant_id, id), \n\tUNIQUE (tenant_id, '
        'id), \n\tUNIQUE (tenant_id, owner_id, request_key), \n\tFOREIGN KEY(tenant_id, owner_i'
        'd) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, recipient_id) REF'
        'ERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agen'
        't_runs (tenant_id, id), \n\tFOREIGN KEY(feedback_id) REFERENCES agent_run_events (id),'
        " \n\tCHECK (kind IN ('missing_material','shared_feedback')), \n\tCHECK (length(questio"
        "n)>0 AND jsonb_typeof(search_scope)='object' AND jsonb_typeof(source_proof)='array'), "
        "\n\tCHECK ((kind='shared_feedback')=(feedback_id IS NOT NULL AND answer IS NOT NULL))"
        '\n)\n\n;\n\nCREATE INDEX ix_knowledge_gap_submissions_category_id ON knowledge_gap_sub'
        'missions (category_id);\n\nCREATE INDEX ix_knowledge_gap_submissions_tenant_id ON know'
        'ledge_gap_submissions (tenant_id);\n\nALTER TABLE public.knowledge_gap_submissions ENA'
        'BLE ROW LEVEL SECURITY;\n\nALTER TABLE public.knowledge_gap_submissions FORCE ROW LEVE'
        'L SECURITY;\n\nCREATE POLICY owner_internal ON public.knowledge_gap_submissions TO pdo'
        's_next_owner USING(true) WITH CHECK(true);\n\nCREATE POLICY contribution_read ON publi'
        'c.knowledge_gap_submissions FOR SELECT TO pdos_next_app USING(tenant_id=nullif(current'
        "_setting('pdos.tenant_id',true),'')::uuid\n AND public.scope_actor()=public.scope_requ"
        'ester()\n AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id=nullif(curren'
        "t_setting('pdos.tenant_id',true),'')::uuid\n AND h.id=public.scope_actor() AND h.kind="
        "'human' AND h.active) AND public.category_access(tenant_id,category_id,false) AND (own"
        'er_id=public.scope_requester() OR EXISTS(SELECT 1 FROM public.categories c WHERE c.ten'
        "ant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND c.id=category_id "
        "AND c.owner_id=public.scope_requester())) AND (kind='missing_material' OR public.knowl"
        'edge_answer_sources_visible(tenant_id,category_id,source_proof)));\n\nCREATE POLICY co'
        'ntribution_append ON public.knowledge_gap_submissions FOR INSERT TO pdos_next_app WITH'
        " CHECK(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND public."
        'scope_actor()=public.scope_requester()\n AND EXISTS(SELECT 1 FROM public.principals h '
        "WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND h.id=p"
        "ublic.scope_actor() AND h.kind='human' AND h.active) AND public.category_access(tenant"
        '_id,category_id,false));\n\nREVOKE ALL ON public.knowledge_gap_submissions FROM PUBLIC'
        ',pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nGRANT SELECT,INSERT ON'
        ' public.knowledge_gap_submissions TO pdos_next_app;\n\n\nCREATE TABLE knowledge_gap_at'
        'tributions (\n\tcategory_id UUID NOT NULL, \n\tsubmission_id UUID NOT NULL, \n\tactor_'
        'id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\treason TEXT NOT NULL, \n\tid UUID'
        ' NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NU'
        'LL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categorie'
        's (tenant_id, id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, actor_id, reques'
        't_key), \n\tFOREIGN KEY(tenant_id, submission_id) REFERENCES knowledge_gap_submissions'
        ' (tenant_id, id), \n\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_i'
        "d, id), \n\tCHECK (reason IN ('missing_material','version_conflict','unclear_content',"
        "'retrieval_miss','answer_problem'))\n)\n\n;\n\nCREATE INDEX ix_knowledge_gap_attributi"
        'ons_category_id ON knowledge_gap_attributions (category_id);\n\nCREATE INDEX ix_knowle'
        'dge_gap_attributions_tenant_id ON knowledge_gap_attributions (tenant_id);\n\nALTER TAB'
        'LE public.knowledge_gap_attributions ENABLE ROW LEVEL SECURITY;\n\nALTER TABLE public.'
        'knowledge_gap_attributions FORCE ROW LEVEL SECURITY;\n\nCREATE POLICY owner_internal O'
        'N public.knowledge_gap_attributions TO pdos_next_owner USING(true) WITH CHECK(true);\n'
        '\nCREATE POLICY contribution_read ON public.knowledge_gap_attributions FOR SELECT TO p'
        "dos_next_app USING(tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n"
        ' AND public.scope_actor()=public.scope_requester()\n AND EXISTS(SELECT 1 FROM public.p'
        "rincipals h WHERE h.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid"
        "\n AND h.id=public.scope_actor() AND h.kind='human' AND h.active) AND public.category_"
        'access(tenant_id,category_id,false) AND EXISTS(SELECT 1 FROM public.categories c WHERE'
        " c.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND c.id=catego"
        'ry_id AND c.owner_id=public.scope_requester()));\n\nCREATE POLICY contribution_append '
        'ON public.knowledge_gap_attributions FOR INSERT TO pdos_next_app WITH CHECK(tenant_id='
        "nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND public.scope_actor()=pub"
        'lic.scope_requester()\n AND EXISTS(SELECT 1 FROM public.principals h WHERE h.tenant_id'
        "=nullif(current_setting('pdos.tenant_id',true),'')::uuid\n AND h.id=public.scope_actor"
        "() AND h.kind='human' AND h.active) AND public.category_access(tenant_id,category_id,f"
        'alse));\n\nREVOKE ALL ON public.knowledge_gap_attributions FROM PUBLIC,pdos_next_app,p'
        'dos_agent,pdos_next_auth,pdos_next_dispatch;\n\nGRANT SELECT,INSERT ON public.knowledg'
        'e_gap_attributions TO pdos_next_app;\n\nCREATE FUNCTION public.knowledge_answer_source'
        's_known(origin_id uuid,proof jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER '
        'SET search_path=pg_catalog,public,pg_temp AS $knowledge_assistant$\n\nDECLARE valid bo'
        'olean;\nBEGIN\n WITH RECURSIVE initial(value) AS (\n  SELECT value FROM public.agent_r'
        "uns r,\n   LATERAL jsonb_array_elements(coalesce(r.result#>'{result,assistant,sources}"
        "','[]'::jsonb)) entry(value)\n   WHERE r.id=origin_id AND r.tenant_id=nullif(current_s"
        "etting('pdos.tenant_id',true),'')::uuid\n  UNION ALL\n  SELECT jsonb_build_object('sou"
        "rce_type','artifact','source_id',a.id,'source_revision',a.revision,\n   'content_hash'"
        ",a.content_hash,'category_id',a.category_id)\n   FROM public.agent_runs r CROSS JOIN L"
        'ATERAL jsonb_array_elements(r.read_sources) ref(value)\n   JOIN public.artifact_versio'
        'ns a ON a.tenant_id=r.tenant_id AND a.category_id=r.category_id\n    AND a.id::text=re'
        "f.value->>'artifact_id' AND a.revision::text=ref.value->>'expected_revision'\n   WHERE"
        " r.id=origin_id AND r.tenant_id=nullif(current_setting('pdos.tenant_id',true),'')::uui"
        "d\n ), closure(value,seen) AS (\n  SELECT value,ARRAY[value->>'source_id'] FROM initia"
        "l\n  UNION ALL\n  SELECT child.value,parent.seen||(child.value->>'source_id') FROM clo"
        'sure parent\n   JOIN public.knowledge_answer_reviews prior ON prior.subject_id::text=p'
        "arent.value->>'source_id'\n     AND prior.tenant_id=nullif(current_setting('pdos.tenan"
        "t_id',true),'')::uuid\n     AND parent.value->>'source_type'='knowledge'\n   CROSS JOI"
        'N LATERAL jsonb_array_elements(prior.source_proof) child(value)\n   WHERE NOT (child.v'
        "alue->>'source_id'=ANY(parent.seen))\n ) SELECT NOT EXISTS(SELECT 1 FROM jsonb_array_e"
        "lements(proof) p WHERE NOT EXISTS(\n  SELECT 1 FROM closure c WHERE c.value->>'source_"
        "type'=p->>'source_type'\n   AND c.value->>'source_id'=p->>'source_id'\n   AND c.value-"
        ">>'source_revision'=p->>'source_revision'\n   AND c.value->>'content_hash'=p->>'conten"
        "t_hash'\n   AND c.value->>'category_id'=p->>'category_id')) INTO valid;\n RETURN jsonb"
        "_typeof(proof)='array' AND coalesce(valid,false);\nEND\n\n$knowledge_assistant$;\n\nRE"
        'VOKE ALL ON FUNCTION public.knowledge_answer_sources_known(uuid,jsonb) FROM PUBLIC,pdo'
        's_next_app,pdos_agent;\n\nCREATE FUNCTION public.assert_knowledge_assistant_fact() RET'
        'URNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_te'
        'mp AS $knowledge_assistant$\n\nDECLARE subject jsonb; sx xid; rx xid; nx xid; receipt '
        'public.action_receipts; origin public.agent_runs;\n category public.categories; actual'
        "_owner uuid; field_name text;\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Knowle"
        "dge contribution facts are append-only' USING ERRCODE='23514'; END IF;\n IF NEW.tenant"
        "_id IS DISTINCT FROM nullif(current_setting('pdos.tenant_id',true),'')::uuid\n OR publ"
        'ic.scope_actor() IS DISTINCT FROM public.scope_requester()\n OR NOT EXISTS(SELECT 1 FR'
        'OM public.principals h WHERE h.tenant_id=NEW.tenant_id AND h.id=public.scope_actor() A'
        "ND h.active AND h.kind='human')\n OR NOT public.category_access(NEW.tenant_id,NEW.cate"
        "gory_id,false) THEN\n  RAISE EXCEPTION 'Only the actual authorized Human may append kn"
        "owledge contributions' USING ERRCODE='42501'; END IF;\n SELECT * INTO STRICT category "
        'FROM public.categories WHERE tenant_id=NEW.tenant_id AND id=NEW.category_id;\n IF TG_T'
        "ABLE_NAME='knowledge_answer_reviews' THEN\n  IF NOT public.category_access(NEW.tenant_"
        "id,NEW.category_id,true) THEN\n   RAISE EXCEPTION 'Knowledge review uses its native ca"
        "tegory write authority' USING ERRCODE='42501'; END IF;\n  IF NOT EXISTS(SELECT 1 FROM "
        'public.principals p JOIN public.grants g ON g.tenant_id=p.tenant_id AND g.principal_id'
        "=p.id\n   WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.responsible_id AND p.kind='huma"
        "n' AND p.active\n   AND g.category_id=NEW.category_id AND (g.expires_at IS NULL OR g.e"
        "xpires_at>transaction_timestamp())) THEN\n   RAISE EXCEPTION 'Review responsible perso"
        "n must be an active actual category reader' USING ERRCODE='23514'; END IF;\n  EXECUTE "
        "format('SELECT to_jsonb(x),xmin FROM public.%I x WHERE tenant_id=$1 AND category_id=$2"
        " AND id=$3',\n   CASE NEW.subject_kind WHEN 'category' THEN 'category_knowledge_entrie"
        "s' WHEN 'candidate' THEN 'knowledge_candidate_versions' WHEN 'rule' THEN 'knowledge_ru"
        "le_versions' END)\n   INTO STRICT subject,sx USING NEW.tenant_id,NEW.category_id,NEW.s"
        'ubject_id;\n  SELECT * INTO STRICT receipt FROM public.action_receipts r WHERE r.tenan'
        't_id=NEW.tenant_id AND r.id=NEW.receipt_id;\n  SELECT xmin INTO rx FROM public.action_'
        'receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;\n  SELECT xmin INTO nx F'
        'ROM public.knowledge_answer_reviews WHERE tenant_id=NEW.tenant_id AND id=NEW.id;\n  IF'
        " sx IS DISTINCT FROM rx OR nx IS DISTINCT FROM sx OR subject->>'receipt_id' IS DISTINC"
        'T FROM NEW.receipt_id::text\n   OR receipt.command_id<>NEW.command_id OR receipt.actor'
        '_id<>public.scope_actor()\n   OR receipt.requester_id<>public.scope_requester()\n   OR'
        ' (NEW.verified_by IS NOT NULL AND NEW.verified_by<>public.scope_requester())\n   OR (N'
        "EW.subject_kind='candidate' AND NEW.verified_by IS NOT NULL)\n   OR (NEW.subject_kind="
        "'rule' AND (receipt.operation<>'knowledge.rule.publish' OR receipt.confirmation_id IS "
        "NULL OR NEW.verified_by IS NULL)) THEN\n   RAISE EXCEPTION 'Review must share its real"
        " native version and Human receipt transaction' USING ERRCODE='23514'; END IF;\n  IF NE"
        "W.source_proof IS DISTINCT FROM (CASE WHEN NEW.subject_kind='category'\n      THEN sub"
        "ject->'answer_sources' ELSE subject#>'{source_basis,answer_sources}' END) THEN\n   RAI"
        "SE EXCEPTION 'Native proof and review must be identical' USING ERRCODE='23514'; END IF"
        ";\n  IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.source_proof) ref WHERE ref->>'s"
        "ource_type'='knowledge' AND (\n    EXISTS(SELECT 1 FROM public.category_knowledge_entr"
        "ies k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'source_id' AND coal"
        'esce(jsonb_array_length(k.answer_sources),0)>0)\n    OR EXISTS(SELECT 1 FROM public.kn'
        "owledge_rule_versions k WHERE k.tenant_id=NEW.tenant_id\n      AND k.id::text=ref->>'s"
        "ource_id' AND coalesce(jsonb_array_length(k.source_basis->'answer_sources'),0)>0))) TH"
        "EN\n   RAISE EXCEPTION 'Reviewed knowledge proofs must flatten existing answer-derived"
        " parents' USING ERRCODE='23514'; END IF;\n  IF NEW.origin_run_id IS NOT NULL THEN\n   "
        'SELECT * INTO STRICT origin FROM public.agent_runs WHERE tenant_id=NEW.tenant_id AND c'
        "ategory_id=NEW.category_id AND id=NEW.origin_run_id;\n   IF origin.state NOT IN ('comp"
        "leted','partial') OR origin.reverted_at IS NOT NULL\n    OR NOT public.knowledge_answe"
        "r_sources_known(NEW.origin_run_id,NEW.source_proof) THEN\n    RAISE EXCEPTION 'Answer "
        "origin is not an actual retained completed answer' USING ERRCODE='23514'; END IF;\n   "
        'IF origin.requester_id<>public.scope_requester() AND NOT EXISTS(\n    SELECT 1 FROM pu'
        'blic.knowledge_answer_reviews prior WHERE prior.tenant_id=NEW.tenant_id\n    AND prior'
        '.origin_run_id=NEW.origin_run_id AND prior.answer_digest=NEW.answer_digest\n    AND pr'
        "ior.source_proof=NEW.source_proof AND (\n     (NEW.subject_kind='rule' AND prior.subje"
        "ct_id::text=subject->>'candidate_version_id')\n     OR (NEW.subject_kind='candidate' A"
        "ND prior.subject_id::text=subject->>'previous_id')\n     OR (NEW.subject_kind='categor"
        "y' AND EXISTS(SELECT 1 FROM public.category_knowledge_entries p\n         WHERE p.id=p"
        "rior.subject_id AND p.lineage_id::text=subject->>'lineage_id'\n         AND p.version<"
        "(subject->>'version')::integer)))) THEN\n    RAISE EXCEPTION 'A new answer origin must"
        " belong to the actual Human; inherited native evidence stays fixed' USING ERRCODE='235"
        "14'; END IF;\n  END IF;\n ELSE\n  IF TG_TABLE_NAME='knowledge_gap_submissions' THEN\n "
        '  IF NEW.owner_id<>public.scope_requester() OR NEW.recipient_id<>category.owner_id THE'
        "N\n    RAISE EXCEPTION 'Gap sharing binds the actual owner and current category recipi"
        "ent' USING ERRCODE='23514'; END IF;\n   SELECT * INTO STRICT origin FROM public.agent_"
        'runs WHERE tenant_id=NEW.tenant_id AND category_id=NEW.category_id AND id=NEW.run_id;'
        "\n   IF origin.requester_id<>NEW.owner_id OR origin.state NOT IN ('completed','partial"
        "') OR origin.reverted_at IS NOT NULL\n    OR (NEW.kind='missing_material' AND (NEW.ans"
        "wer IS NOT NULL OR jsonb_array_length(NEW.source_proof)<>0))\n    OR (NEW.kind='shared"
        "_feedback' AND NOT public.knowledge_answer_sources_known(NEW.run_id,NEW.source_proof))"
        "\n    OR (NEW.kind='shared_feedback' AND NOT EXISTS(SELECT 1 FROM public.agent_run_eve"
        'nts e\n        WHERE e.id=NEW.feedback_id AND e.tenant_id=NEW.tenant_id AND e.run_id=N'
        "EW.run_id\n        AND e.body->>'type'='run_feedback' AND e.body->>'recorded_by'=NEW.o"
        "wner_id::text)) THEN\n    RAISE EXCEPTION 'Only an actual explicit owner submission or"
        " actual private feedback may be shared' USING ERRCODE='23514'; END IF;\n  ELSE\n   IF "
        'NEW.actor_id<>public.scope_requester() OR category.owner_id<>NEW.actor_id\n    OR NOT '
        'EXISTS(SELECT 1 FROM public.knowledge_gap_submissions g WHERE g.tenant_id=NEW.tenant_i'
        'd AND g.category_id=NEW.category_id AND g.id=NEW.submission_id) THEN\n    RAISE EXCEPT'
        "ION 'Only the current actual category owner may attribute a submitted gap' USING ERRCO"
        "DE='42501'; END IF;\n  END IF;\n END IF;\n RETURN NULL;\nEND\n\n$knowledge_assistant$;"
        '\n\nCREATE FUNCTION public.require_knowledge_answer_origin() RETURNS trigger LANGUAGE '
        'plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $knowledge_assis'
        'tant$\n\nDECLARE payload jsonb; review public.knowledge_answer_reviews; needs boolean;'
        "\nBEGIN\n IF TG_TABLE_NAME='category_knowledge_entries' THEN\n  needs=NEW.kind='verifi"
        "ed_answer' AND NEW.action<>'withdraw';\n ELSE\n  payload=NEW.command->'envelope'->'pay"
        "load';\n  needs=(payload->'answer_origin' IS NOT NULL AND payload->'answer_origin'<>'n"
        "ull'::jsonb)\n   OR jsonb_array_length(NEW.sources)=0 OR jsonb_array_length(NEW.reads)"
        "=0;\n  IF TG_TABLE_NAME='knowledge_rule_versions' THEN\n   needs=needs OR EXISTS(SELEC"
        'T 1 FROM public.knowledge_answer_reviews p\n     WHERE p.tenant_id=NEW.tenant_id AND p'
        ".subject_id=NEW.candidate_version_id AND p.subject_kind='candidate');\n  ELSE\n   need"
        's=needs OR EXISTS(SELECT 1 FROM public.knowledge_answer_reviews p\n     WHERE p.tenant'
        "_id=NEW.tenant_id AND p.subject_id=NEW.previous_id AND p.subject_kind='candidate');\n "
        ' END IF;\n END IF;\n IF needs THEN\n  SELECT * INTO review FROM public.knowledge_answe'
        'r_reviews r WHERE r.tenant_id=NEW.tenant_id\n   AND r.subject_id=NEW.id AND r.subject_'
        "kind=CASE TG_TABLE_NAME\n    WHEN 'category_knowledge_entries' THEN 'category' WHEN 'k"
        "nowledge_candidate_versions' THEN 'candidate' ELSE 'rule' END;\n  IF review.id IS NULL"
        " OR (TG_TABLE_NAME<>'category_knowledge_entries' AND payload->'answer_origin' IS NOT N"
        "ULL AND payload->'answer_origin'<>'null'::jsonb AND (\n   review.origin_run_id::text I"
        "S DISTINCT FROM payload->'answer_origin'->>'run_id'\n   OR review.answer_digest IS DIS"
        "TINCT FROM payload->'answer_origin'->>'answer_digest')) THEN\n   RAISE EXCEPTION 'Answ"
        "er-derived knowledge requires its exact real native provenance in this transaction' US"
        "ING ERRCODE='23514'; END IF;\n  IF TG_TABLE_NAME='category_knowledge_entries' AND revi"
        "ew.origin_run_id IS NULL THEN\n   RAISE EXCEPTION 'Verified answer must retain its act"
        "ual answer origin' USING ERRCODE='23514'; END IF;\n  IF TG_TABLE_NAME='category_knowle"
        "dge_entries' AND jsonb_array_length(review.source_proof)=0\n   AND NOT EXISTS(SELECT 1"
        ' FROM public.promotion_proofs p WHERE p.tenant_id=NEW.tenant_id\n     AND p.knowledge_'
        "entry_id=NEW.id AND p.receipt_id=NEW.receipt_id) THEN\n   RAISE EXCEPTION 'Shared answ"
        "er requires fixed sources or the native deidentification proof' USING ERRCODE='23514';"
        ' END IF;\n END IF;\n RETURN NULL;\nEND\n\n$knowledge_assistant$;\n\nREVOKE ALL ON FUNC'
        'TION public.require_knowledge_answer_origin() FROM PUBLIC,pdos_next_app,pdos_agent;\n'
        '\nCREATE CONSTRAINT TRIGGER knowledge_answer_origin AFTER INSERT ON public.category_kn'
        'owledge_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.req'
        'uire_knowledge_answer_origin();\n\nCREATE CONSTRAINT TRIGGER knowledge_answer_origin A'
        'FTER INSERT ON public.knowledge_candidate_versions DEFERRABLE INITIALLY DEFERRED FOR E'
        'ACH ROW EXECUTE FUNCTION public.require_knowledge_answer_origin();\n\nCREATE CONSTRAIN'
        'T TRIGGER knowledge_answer_origin AFTER INSERT ON public.knowledge_rule_versions DEFER'
        'RABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_knowledge_answer'
        '_origin();\n\nCREATE CONSTRAINT TRIGGER knowledge_assistant_atom AFTER INSERT ON publi'
        'c.knowledge_answer_reviews DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION'
        ' public.assert_knowledge_assistant_fact();\n\nCREATE TRIGGER knowledge_assistant_immut'
        'able BEFORE UPDATE OR DELETE ON public.knowledge_answer_reviews FOR EACH ROW EXECUTE F'
        'UNCTION public.assert_knowledge_assistant_fact();\n\nCREATE CONSTRAINT TRIGGER knowled'
        'ge_assistant_atom AFTER INSERT ON public.knowledge_gap_submissions DEFERRABLE INITIALL'
        'Y DEFERRED FOR EACH ROW EXECUTE FUNCTION public.assert_knowledge_assistant_fact();\n\n'
        'CREATE TRIGGER knowledge_assistant_immutable BEFORE UPDATE OR DELETE ON public.knowled'
        'ge_gap_submissions FOR EACH ROW EXECUTE FUNCTION public.assert_knowledge_assistant_fac'
        't();\n\nCREATE CONSTRAINT TRIGGER knowledge_assistant_atom AFTER INSERT ON public.know'
        'ledge_gap_attributions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION pub'
        'lic.assert_knowledge_assistant_fact();\n\nCREATE TRIGGER knowledge_assistant_immutable'
        ' BEFORE UPDATE OR DELETE ON public.knowledge_gap_attributions FOR EACH ROW EXECUTE FUN'
        'CTION public.assert_knowledge_assistant_fact();\n\nCREATE FUNCTION public.knowledge_we'
        'ekly_lookup_stats(t uuid,c uuid,a timestamptz,z timestamptz) RETURNS TABLE(total bigin'
        't,not_found bigint,rate numeric,suppressed boolean) LANGUAGE plpgsql SECURITY DEFINER '
        'SET search_path=pg_catalog,public,pg_temp AS $knowledge_assistant$\n\nDECLARE n bigint'
        "; missed bigint;\nBEGIN\n IF t IS DISTINCT FROM nullif(current_setting('pdos.tenant_id"
        "',true),'')::uuid\n OR c IS DISTINCT FROM nullif(current_setting('pdos.category_id',tr"
        "ue),'')::uuid\n OR public.scope_actor() IS DISTINCT FROM public.scope_requester()\n OR"
        ' NOT public.category_access(t,c,false)\n OR NOT EXISTS(SELECT 1 FROM public.categories'
        ' x JOIN public.principals p ON p.tenant_id=x.tenant_id AND p.id=x.owner_id\n WHERE x.t'
        "enant_id=t AND x.id=c AND p.id=public.scope_requester() AND p.kind='human' AND p.activ"
        "e)\n OR extract(isodow FROM a AT TIME ZONE 'UTC')<>1\n OR (a AT TIME ZONE 'UTC')::time"
        "<>'00:00:00'::time OR z<>a+interval '7 days' THEN\n RAISE EXCEPTION 'Knowledge rates a"
        "re fixed weekly category-owner aggregates' USING ERRCODE='42501'; END IF;\n SELECT cou"
        "nt(*),count(*) FILTER(WHERE r.result#>>'{result,assistant,lookup}'='no_match') INTO n,"
        'missed\n FROM public.agent_runs r WHERE r.tenant_id=t AND r.category_id=c AND r.create'
        "d_at>=a AND r.created_at<z\n AND r.state IN ('completed','partial') AND r.reverted_at "
        "IS NULL\n AND r.result#>>'{result,assistant,lookup}' IN ('no_match','uncited','cited')"
        '\n AND EXISTS(SELECT 1 FROM public.agent_tool_calls call WHERE call.tenant_id=t AND ca'
        "ll.run_id=r.id\n   AND call.tool='assistant.search' AND call.state='completed'\n   AND"
        " call.execution_binding->>'read_kind'='ordinary/v1');\n RETURN QUERY SELECT CASE WHEN "
        'n>=5 THEN n ELSE NULL END,\n CASE WHEN n>=5 THEN missed ELSE NULL END,\n CASE WHEN n>='
        '5 THEN missed::numeric/n ELSE NULL END,n<5;\nEND\n\n$knowledge_assistant$;\n\nREVOKE A'
        'LL ON FUNCTION public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz)'
        ' FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nGRANT EXECUTE ON FUNCTIO'
        'N public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz) TO pdos_next'
        '_app;\n\nREVOKE ALL ON FUNCTION public.assert_knowledge_assistant_fact() FROM PUBLIC,p'
        'dos_next_app,pdos_agent;\n'
    ),
)

LIFECYCLE_SQL = (
    (
        'CREATE FUNCTION public.assistant_source_lifecycle_links(t uuid,c uuid,proof jsonb) RET'
        'URNS uuid[] LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public'
        ",pg_temp AS $assistant_lifecycle$\n\nDECLARE links uuid[]='{}'; item jsonb; container "
        "jsonb; key text;\nBEGIN\n IF jsonb_typeof(proof) IS DISTINCT FROM 'array' THEN\n  RAIS"
        "E EXCEPTION 'Fixed assistant source dependencies must be an array' USING ERRCODE='2351"
        "4'; END IF;\n FOR item IN SELECT value FROM jsonb_array_elements(proof) LOOP\n  IF ite"
        "m->>'category_id' IS DISTINCT FROM c::text\n   OR item->>'source_type' IS NULL\n   OR "
        "item->>'source_type'<>ALL(ARRAY['artifact','knowledge','issue','capa','change','extern"
        "al_wait','supply','build','test_run'])\n   OR item->>'source_id' IS NULL\n   OR item->"
        ">'source_revision' IS NULL OR item->>'source_revision' !~ '^[1-9][0-9]*$'\n   OR item-"
        ">>'content_hash' IS NULL OR item->>'content_hash' !~ '^[a-f0-9]{64}$' THEN\n   RAISE E"
        "XCEPTION 'Assistant dependency must retain its actual fixed identity' USING ERRCODE='2"
        "3514';\n  END IF;\n  links=array_append(links,(item->>'source_id')::uuid);\n  -- Exact"
        ' original dependency projection, not read permission or business facts.\n  -- Build/te'
        'st record IDs resolve their own real registered Artifact read sets.\n  FOR container I'
        'N\n   SELECT s.required_source_read_set AS reads FROM public.quality_issue_versions s '
        "WHERE item->>'source_type'='issue' AND s.tenant_id=t AND s.category_id=c AND s.id::tex"
        "t=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads FROM"
        " public.quality_issue_versions s WHERE item->>'source_type'='capa' AND s.tenant_id=t A"
        "ND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.requir"
        "ed_source_read_set AS reads FROM public.change_request_versions s WHERE item->>'source"
        "_type'='change' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id"
        "'\n   UNION ALL\n   SELECT s.reads AS reads FROM public.external_wait_versions s WHERE"
        " item->>'source_type'='external_wait' AND s.tenant_id=t AND s.category_id=c AND s.id::"
        "text=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads F"
        "ROM public.supply_snapshots s WHERE item->>'source_type'='supply' AND s.tenant_id=t AN"
        "D s.category_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.require"
        "d_source_read_set AS reads FROM public.build_starts s WHERE item->>'source_type'='buil"
        "d' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   UNION A"
        'LL\n   SELECT s.required_source_read_set AS reads FROM public.actual_configurations s '
        "WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.category_id=c AND s.id::tex"
        "t=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_read_set AS reads FROM"
        " public.build_lots s WHERE item->>'source_type'='build' AND s.tenant_id=t AND s.catego"
        "ry_id=c AND s.id::text=item->>'source_id'\n   UNION ALL\n   SELECT s.required_source_r"
        "ead_set AS reads FROM public.verification_run_versions s WHERE item->>'source_type'='t"
        "est_run' AND s.tenant_id=t AND s.category_id=c AND s.id::text=item->>'source_id'\n   U"
        'NION ALL\n   SELECT s.required_source_read_set AS reads FROM public.test_result_action'
        "s s WHERE item->>'source_type'='test_run' AND s.tenant_id=t AND s.category_id=c AND s."
        "id::text=item->>'source_id'\n   UNION ALL\n   SELECT coalesce(e.required_source_read_s"
        "et,'[]'::jsonb)||coalesce(p.required_source_read_set,'[]'::jsonb) AS reads FROM public"
        '.builds b JOIN public.engineering_configurations e ON e.tenant_id=b.tenant_id AND e.ca'
        'tegory_id=b.category_id AND e.id=b.engineering_configuration_id JOIN public.process_re'
        'visions p ON p.tenant_id=b.tenant_id AND p.category_id=b.category_id AND p.id=b.manufa'
        "cturing_configuration_id WHERE item->>'source_type'='build' AND b.tenant_id=t AND b.ca"
        "tegory_id=c AND b.id::text=item->>'source_id'\n  LOOP\n   FOR key IN SELECT value->>'a"
        "rtifact_id' FROM jsonb_array_elements(coalesce(container,'[]'::jsonb)) LOOP\n    IF ke"
        'y IS NOT NULL THEN links=array_append(links,key::uuid); END IF;\n   END LOOP;\n  END L'
        'OOP;\n END LOOP;\n RETURN links;\nEND\n;\n$assistant_lifecycle$;\n\nREVOKE ALL ON FUNC'
        'TION public.assistant_source_lifecycle_links(uuid,uuid,jsonb) FROM PUBLIC,pdos_next_ap'
        'p,pdos_agent,pdos_next_auth,pdos_next_dispatch;\n\nCREATE OR REPLACE FUNCTION public.m'
        '3_lifecycle_source_links(t uuid, c uuid, table_name text, payload jsonb)\n RETURNS uui'
        "d[]\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'p"
        "ublic', 'pg_temp'\nAS $function$\nDECLARE links uuid[]='{}'; extra uuid[]; key text; k"
        'eys text[]; item jsonb; container jsonb;\n target_kind text; referenced_target uuid; r'
        "eferenced_version integer;\nBEGIN\n IF table_name='agent_runs' THEN RETURN public.kern"
        'el_lifecycle_links(table_name,payload); END IF;\n -- Only actual top-level relation co'
        'lumns establish raw UUID edges. Arbitrary\n -- content dictionaries are not relational'
        ' rows, even if an extra key happens\n -- to be named source_id or item_id.\n keys=CASE'
        " table_name\n  WHEN 'artifact_versions' THEN ARRAY['original_id']\n  WHEN 'claims' THE"
        "N ARRAY['artifact_id','snapshot_id']\n  WHEN 'definition_revisions' THEN ARRAY['derive"
        "d_from_definition_id','parent_definition_id',\n   'source_proposal_id','source_submiss"
        "ion_id']\n  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n  WHEN 'definition_sp"
        "ecs' THEN ARRAY[]::text[]\n  WHEN 'proposals' THEN ARRAY['baseline_definition_id','cur"
        "rent_submission_id']\n  WHEN 'proposal_items' THEN ARRAY[]::text[]\n  WHEN 'proposal_i"
        "tem_versions' THEN ARRAY[]::text[]\n  WHEN 'proposal_revisions' THEN ARRAY['proposal_i"
        "d']\n  WHEN 'proposal_sources' THEN ARRAY['source_id']\n  WHEN 'proposal_submissions' "
        "THEN ARRAY[]::text[]\n  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n  WHEN "
        "'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decisio"
        "n_id']\n  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n  WHEN 'pr"
        "omotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n  WHEN 'evidenc"
        "e_links' THEN ARRAY['evidence_id']\n  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']"
        "\n  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','"
        "previous_id']\n  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n "
        " WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n  "
        "WHEN 'native_pilot_runs' THEN ARRAY['build_id','lot_id','actual_configuration_id','eng"
        "ineering_configuration_id','process_id','publication_id']\n  WHEN 'native_pilot_curren"
        "ts' THEN ARRAY['pilot_id','latest_observation_id']\n  WHEN 'native_pilot_observations'"
        " THEN ARRAY['pilot_id','previous_observation_id']\n  WHEN 'release_packages' THEN ARRA"
        "Y['previous_id']\n  WHEN 'release_package_currents' THEN ARRAY['version_id']\n  WHEN '"
        "release_decisions' THEN ARRAY['package_id']\n  WHEN 'release_policy_facts' THEN ARRAY["
        "'previous_id']\n  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n  WHEN 'extern"
        "al_handoff_authorizations' THEN ARRAY['package_id','engineering_decision_id','manufact"
        "uring_decision_id']\n  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n  WH"
        "EN 'external_receipts' THEN ARRAY['handoff_id','intent_id','previous_receipt_id','reco"
        "nciles_id']\n  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','l"
        "atest_receipt_id']\n  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id'"
        ",'policy_fact_id','previous_id']\n  WHEN 'release_exception_currents' THEN ARRAY['basi"
        "s_package_id','policy_fact_id','decision_id']\n  WHEN 'work_commitment_reviews' THEN A"
        "RRAY['commitment_id','task_version_id','submission_id','previous_id']\n  WHEN 'work_co"
        "mmitment_review_currents' THEN ARRAY['version_id']\n  WHEN 'external_wait_versions' TH"
        "EN ARRAY['previous_id']\n  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n  W"
        "HEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n  W"
        "HEN 'project_risk_followup_currents' THEN ARRAY['version_id']\n  WHEN 'work_task_versi"
        "ons' THEN ARRAY['previous_id']\n  WHEN 'work_task_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']\n  WHEN 'work_commitment_c"
        "urrents' THEN ARRAY['version_id']\n  WHEN 'project_status_updates' THEN ARRAY[]::text["
        ']\n  ELSE ARRAY[]::text[] END;\n FOREACH key IN ARRAY keys LOOP\n  IF payload->>key IS'
        ' NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n END LOOP;\n '
        "-- Publication's exact saved read set is a validated Artifact relationship.\n -- Do no"
        't scan its declaration, body, reason or arbitrary JSON UUID values.\n IF table_name IN'
        " ('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations"
        "','release_packages','release_decisions','release_policy_facts','external_handoff_auth"
        "orizations','external_receipts','release_exception_decisions') THEN\n  FOR item IN SEL"
        "ECT value FROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')"
        ") LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN\n    links=array_append(links,(ite"
        "m->>'artifact_id')::uuid);\n   END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('nat"
        "ive_pilot_runs','native_pilot_observations') THEN\n  FOR item IN SELECT value FROM jso"
        "nb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LO"
        "OP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); "
        'END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(pa'
        "yload#>'{material_snapshot,statistics,issues}','[]')) LOOP\n   IF item->>'id' IS NOT N"
        "ULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  item=p"
        "ayload#>'{material_snapshot,statistics,resource,fact}';\n  IF item->>'id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'id')::uuid); END IF;\n END IF;\n IF table_name="
        "'release_packages' THEN\n  -- FixedObject.ref is a closed, server-resolved version ref"
        'erence, not arbitrary body UUID text.\n  FOR item IN SELECT value FROM jsonb_array_ele'
        "ments(coalesce(payload#>'{body,objects}','[]')) LOOP\n   container=item->'ref';\n   IF"
        " container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revisi"
        "on','manufacturing_publication','test_run','pilot_run','issue','change','exception','a"
        "rtifact','work_instruction','control_plan','build_lot','line'])\n    AND container->>'"
        "id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n IF table_name IN ('external_handoff_authorizations','external_deli"
        "very_intents') THEN\n  -- Only closed, owner-verified mapping and manifest references "
        "are source edges.\n  container=CASE WHEN table_name='external_handoff_authorizations' "
        "THEN payload#>'{body,declaration}' ELSE payload->'body' END;\n  FOR item IN SELECT val"
        "ue FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n   IF item->'"
        "ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','p"
        "art','bom_revision','artifact','work_instruction','control_plan'])\n    AND item->'ref"
        "'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); END IF"
        ';\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(containe'
        "r->'manifest','[]')) LOOP\n   IF item->'artifact'->>'id' IS NOT NULL THEN links=array_"
        "append(links,(item->'artifact'->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n IF tab"
        "le_name='release_policy_facts' THEN\n  -- These are Closed DTO configuration reference"
        "s fixed by the policy owner.\n  FOREACH key IN ARRAY ARRAY['definition','engineering_c"
        "onfiguration','manufacturing_configuration'] LOOP\n   container=payload#>ARRAY['materi"
        "al','subject_config',key];\n   IF container->>'id' IS NOT NULL THEN links=array_append"
        "(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- These stored fie"
        'lds are validated Reference containers. Do not feed the\n -- whole row or arbitrary co'
        "ntent into the canonical Reference parser.\n IF table_name=ANY(ARRAY['proposals','prop"
        "osal_item_versions','proposal_submissions',\n  'category_knowledge_entries','definitio"
        "n_specs']) THEN\n  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','cont"
        "ext_refs','baseline_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_lin"
        'ks(t,c,payload->key);\n  END LOOP;\n END IF;\n -- Match ItemInput.content_schema and c'
        'ategory_service._references: only\n -- commercial_target, voice, and competitor have n'
        "ested source contracts.\n IF table_name='proposal_item_versions' AND payload->>'kind'="
        "'commercial_target' THEN\n  FOREACH key IN ARRAY ARRAY['target_price','cost','volume']"
        " LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->"
        "'source');\n  END LOOP;\n ELSIF table_name='category_knowledge_entries' AND payload->>"
        "'kind'='voice' THEN\n  links=links || public.m3_lifecycle_typed_links(t,c,payload->'co"
        "ntent'->'representative_refs');\n ELSIF table_name='category_knowledge_entries' AND pa"
        "yload->>'kind'='competitor' THEN\n  FOREACH key IN ARRAY ARRAY['metrics','features','p"
        "rices'] LOOP\n   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->"
        "'content'->key,'[]')) LOOP\n    links=links || public.m3_lifecycle_typed_links(t,c,ite"
        "m->'source_ref');\n   END LOOP;\n  END LOOP;\n END IF;\n IF table_name='proposal_submi"
        "ssions' THEN\n  container=payload->'frozen_document';\n  FOREACH key IN ARRAY ARRAY['s"
        "ource_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   links="
        'links || public.m3_lifecycle_typed_links(t,c,container->key);\n  END LOOP;\n  FOR item'
        " IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n  "
        " links=links || public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARR"
        "AY['item_id','proposal_id']);\n   -- The frozen read projection records actual Evidenc"
        "eLink provenance here.\n   links=links || public.m3_lifecycle_typed_links(t,c,item->'e"
        "vidence_links');\n  END LOOP;\n ELSIF table_name='promotion_proofs' THEN\n  FOR item I"
        "N SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) L"
        "OOP\n   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id"
        "')::uuid); END IF;\n  END LOOP;\n END IF;\n -- Exact persisted EvidenceLink targets su"
        'pplement these immutable versions.\n -- Reverted links and withdrawn Claims still reta'
        'in the original historical\n -- dependency; lifecycle cleanup must not erase their aud'
        "it source.\n IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NUL"
        "L THEN\n  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;"
        "\n  referenced_version=(payload->>'version')::integer;\n ELSIF table_name='category_kn"
        "owledge_entries' AND payload->>'id' IS NOT NULL THEN\n  target_kind='knowledge_entry';"
        " referenced_target=(payload->>'id')::uuid;\n  referenced_version=(payload->>'version')"
        "::integer;\n ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n"
        "  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n  SELECT r"
        'evision INTO referenced_version FROM public.definition_revisions\n   WHERE tenant_id=t'
        " AND category_id=c AND id=(payload->>'definition_id')::uuid;\n END IF;\n IF referenced"
        '_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n  SELECT coalesce(array_a'
        "gg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link\n   WHERE link.t"
        'enant_id=t AND link.category_id=c AND link.target_type=target_kind\n    AND link.targe'
        't_id=referenced_target AND link.target_version=referenced_version;\n  links=links || e'
        'xtra;\n END IF;\n -- Child source rows point to their parent, whereas dependency trave'
        "rsal needs\n -- the parent's fixed source children as well. Keep the actual relational"
        " edge.\n IF table_name='definition_revisions' THEN\n  SELECT coalesce(array_agg(id),'{"
        "}') INTO extra FROM (\n   SELECT id FROM public.definition_sources WHERE tenant_id=t A"
        "ND category_id=c\n    AND definition_id=(payload->>'id')::uuid\n   UNION ALL SELECT id"
        ' FROM public.definition_specs WHERE tenant_id=t AND category_id=c\n    AND definition_'
        "id=(payload->>'id')::uuid\n  ) children;\n  links=links || extra;\n ELSIF table_name='"
        "proposals' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal"
        "_item_versions\n   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id'"
        ")::uuid;\n  links=links || extra;\n ELSIF table_name='proposal_items' THEN\n  SELECT c"
        "oalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE te"
        "nant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n  links=links || extr"
        "a;\n ELSIF table_name='product_target_segments' THEN\n  SELECT coalesce(array_agg(id),"
        "'{}') INTO extra FROM public.category_knowledge_entries\n   WHERE tenant_id=t AND cate"
        "gory_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid\n    AND version=(payl"
        "oad->>'segment_version')::integer;\n  links=links || extra;\n ELSIF table_name='parame"
        "ter_current' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parame"
        "ter_versions\n   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'para"
        "meter_id')::uuid\n    AND version=(payload->>'current_version')::integer;\n  links=lin"
        "ks || extra;\n END IF;\n\n IF table_name IN ('work_task_versions','work_commitment_ver"
        "sions','project_status_updates') THEN\n  FOR item IN SELECT value FROM jsonb_array_ele"
        "ments(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL TH"
        "EN links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  IF "
        "table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
        "   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n  END IF;\n  IF"
        " table_name='work_commitment_versions' THEN\n   SELECT coalesce(array_agg(id),'{}') IN"
        'TO extra FROM public.work_task_versions\n    WHERE tenant_id=t AND category_id=c AND t'
        "ask_id=(payload->>'task_id')::uuid AND revision=(payload->>'task_revision')::integer;"
        "\n   links=links||extra;\n  ELSIF table_name='project_status_updates' THEN\n   FOR ite"
        "m IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP"
        "\n    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n "
        "    WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND revision=("
        "item->>'revision')::integer;\n    links=links||extra;\n   END LOOP;\n  END IF;\n END I"
        "F;\n\n IF table_name='work_commitment_reviews' THEN\n  FOR item IN SELECT value FROM j"
        "sonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' "
        "IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n\n IF table_name='external_wait_versions' THEN\n  FOR item IN SELEC"
        "T value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
        "LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid)"
        "; END IF;\n  END LOOP;\n  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] L"
        "OOP\n   container=payload#>ARRAY['body',key];\n   IF container->>'id' IS NOT NULL THEN"
        " links=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n  container"
        "=payload#>'{body,replaces}';\n  IF container->>'id' IS NOT NULL THEN\n   SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n    WHERE tenant"
        "_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND revision=(container->"
        ">'revision')::integer;\n   links=links||extra;\n  END IF;\n END IF;\n IF table_name='p"
        "roject_risk_followups' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coal"
        "esce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL TH"
        "EN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n I"
        "F table_name IN ('knowledge_candidate_versions','knowledge_candidate_currents','knowle"
        "dge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') TH"
        "EN\n  FOREACH key IN ARRAY ARRAY['previous_id','version_id','candidate_version_id','as"
        "sessment_id','publication_id'] LOOP\n   IF payload->>key IS NOT NULL THEN links=array_"
        'append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value '
        "FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n  "
        " IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF"
        ';\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload-'
        ">'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(l"
        "inks,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value F"
        "ROM jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOO"
        "P\n   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receip"
        "t_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT NULL THEN links=array_append(link"
        "s,(item->>'row_id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM json"
        "b_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP"
        "\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); EN"
        "D IF;\n  END LOOP;\n  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN links=a"
        "rray_append(links,(payload#>>'{source_basis,target,id}')::uuid); END IF;\n END IF;\n\n"
        " IF table_name IN ('field_feedback_versions','field_feedback_currents','field_response"
        "_records') THEN\n  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_ver"
        "sion_id'] LOOP\n   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload"
        '->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NO"
        "T NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOR"
        "EACH key IN ARRAY ARRAY['engineering_configuration','manufacturing_configuration','bat"
        "ch'] LOOP\n   IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN links=ar"
        "ray_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;\n  END "
        "LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source"
        "_basis,result_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links"
        "=array_append(links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NO"
        "T NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LOOP;\n "
        "END IF;\n IF table_name IN ('change_request_versions','change_graph_captures') THEN\n "
        " FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners"
        "}','{}')) LOOP\n   IF container->>'feedback_version_id' IS NOT NULL THEN links=array_a"
        "ppend(links,(container->>'feedback_version_id')::uuid); END IF;\n  END LOOP;\n END IF;"
        '\n\n -- Closed native Field plan and occurrence references, never arbitrary UUID prose'
        ".\n IF table_name='controlled_change_selection_facts' AND payload->>'basis_kind'='fiel"
        "d_intent' THEN\n  IF payload->>'feedback_version_id' IS NOT NULL THEN\n   links=array_"
        "append(links,(payload->>'feedback_version_id')::uuid);\n  END IF;\n END IF;\n IF table"
        "_name='change_implementation_captures'\n  AND payload#>>'{occurrence_snapshot,schema_v"
        "ersion}'='pdos-field-change-implementation-occurrence-v1' THEN\n  FOREACH key IN ARRAY"
        " ARRAY['feedback_version_id','selection_id'] LOOP\n   IF payload#>>ARRAY['occurrence_s"
        "napshot',key] IS NOT NULL THEN\n    links=array_append(links,(payload#>>ARRAY['occurre"
        "nce_snapshot',key])::uuid);\n   END IF;\n  END LOOP;\n END IF;\n\n IF table_name='chan"
        "ge_completion_records' THEN\n  FOREACH key IN ARRAY ARRAY['project_id','change_version"
        "_id','order_record_id','shared_proof_id'] LOOP\n   IF payload->>key IS NOT NULL THEN l"
        'inks=array_append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN SE'
        "LECT value FROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]'"
        ")) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>"
        "'artifact_id')::uuid); END IF;\n  END LOOP;\n  IF payload#>>'{native_input,lot,id}' IS"
        " NOT NULL THEN links=array_append(links,(payload#>>'{native_input,lot,id}')::uuid); EN"
        "D IF;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native"
        "_input,sample_refs}','[]')) LOOP\n   links=array_append(links,(item->>'id')::uuid);\n "
        " END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{n"
        "ative_input,mappings}','[]')) LOOP\n   SELECT coalesce(array_agg(id),'{}') INTO extra "
        'FROM verification_run_versions\n    WHERE tenant_id=t AND category_id=c AND run_id=(it'
        "em#>>'{run,id}')::uuid AND revision=(item#>>'{run,revision}')::integer;\n   links=link"
        "s||extra; links=array_append(links,(item->>'sample_id')::uuid);\n  END LOOP;\n END IF;"
        '\n\n -- Closed native owner DTOs: retain exact outputs and native execution/report row'
        "s.\n IF table_name='change_completion_records' THEN\n  FOR item IN SELECT value FROM j"
        "sonb_array_elements(coalesce(payload#>'{fact_snapshot,output_refs}','[]')) LOOP\n   IF"
        " item->>'kind'='test_run' THEN\n    SELECT coalesce(array_agg(id),'{}') INTO extra FRO"
        'M verification_run_versions\n     WHERE tenant_id=t AND category_id=c AND run_id=(item'
        "->>'id')::uuid AND revision=(item->>'revision')::integer;\n    links=links||extra;\n  "
        " ELSIF item->>'kind'=ANY(ARRAY['engineering_configuration','manufacturing_configuratio"
        "n','build','sample']) THEN\n    links=array_append(links,(item->>'id')::uuid);\n   END"
        " IF;\n  END LOOP;\n  IF payload#>>'{owner_basis,schema_version}'='pdos-native-build-ad"
        "option-read-v1' THEN\n   FOREACH key IN ARRAY ARRAY['previous_build','successor_build'"
        ",'actual_configuration','lot','start'] LOOP\n    IF payload#>>ARRAY['owner_basis',key,"
        "'id'] IS NOT NULL THEN\n     links=array_append(links,(payload#>>ARRAY['owner_basis',k"
        "ey,'id'])::uuid);\n    END IF;\n   END LOOP;\n  ELSIF payload#>>'{owner_basis,schema_v"
        "ersion}'='pdos-native-change-run-verification-v1' THEN\n   FOR container IN SELECT val"
        "ue FROM jsonb_each(coalesce(payload#>'{owner_basis,runs}','{}')) LOOP\n    FOREACH key"
        " IN ARRAY ARRAY['run_version_id','request_version_id','projection_id'] LOOP\n     IF c"
        'ontainer->>key IS NOT NULL THEN links=array_append(links,(container->>key)::uuid); END'
        ' IF;\n    END LOOP;\n   END LOOP;\n  END IF;\n END IF;\n\n -- F: only server-verified '
        'fixed answer proofs establish these dependency edges.\n -- Native deferred atoms bind '
        "these exact arrays to real source ledgers.\n IF table_name IN ('category_knowledge_ent"
        "ries','knowledge_candidate_versions','knowledge_rule_versions','knowledge_answer_revie"
        "ws','knowledge_gap_submissions') THEN\n  container=CASE table_name WHEN 'category_know"
        "ledge_entries' THEN payload->'answer_sources'\n   WHEN 'knowledge_candidate_versions' "
        "THEN payload#>'{source_basis,answer_sources}'\n   WHEN 'knowledge_rule_versions' THEN "
        "payload#>'{source_basis,answer_sources}'\n   ELSE payload->'source_proof' END;\n  link"
        "s=links||public.assistant_source_lifecycle_links(t,c,coalesce(container,'[]'::jsonb));"
        '\n END IF;\n RETURN links;\nEND;\n$function$;\n\nCREATE OR REPLACE FUNCTION public.m3_'
        'lifecycle_nodes(t uuid, c uuid, identities uuid[] DEFAULT NULL::uuid[])\n RETURNS TABL'
        'E(table_name text, node_id uuid, links uuid[])\n LANGUAGE plpgsql\n STABLE SECURITY DE'
        "FINER\n SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE n"
        'ame text; payload jsonb; controls uuid[];\nBEGIN\n IF identities IS NULL THEN\n  SELEC'
        "T coalesce(array_agg(id),'{}') INTO controls FROM public.action_receipts\n   WHERE ten"
        "ant_id=t AND category_id=c AND operation LIKE 'evidence.lifecycle.%';\n ELSE controls="
        "'{}'; END IF;\n FOREACH name IN ARRAY CASE WHEN identities IS NULL THEN ARRAY['agent_r"
        "uns','action_receipts','actual_configurations','artifact_versions','audit_entries','bo"
        "m_lines','bom_revisions','build_authorization_decisions','build_current_authorizations"
        "','build_current_execution_assessments','build_execution_assessments','build_lots','bu"
        "ild_operational_current','build_operational_facts','build_readiness','build_starts','b"
        "uilds','capa_current_observations','capa_current_verification_rules','capa_named_verif"
        "ication_reviews','capa_observation_facts','capa_remediation_links','capa_verification_"
        "evidence','capa_verification_rule_facts','change_approval_records','change_dependency_"
        "clocks','change_graph_captures','change_implementation_captures','change_implementatio"
        "n_records','change_order_records','change_request_currents','change_request_versions',"
        "'claim_consumptions','claims','controlled_change_coverage_currents','controlled_change"
        "_coverage_facts','controlled_change_policy_currents','controlled_change_policy_facts',"
        "'controlled_change_selection_currents','controlled_change_selection_facts','cost_curre"
        "nt_inputs','cost_estimates','cost_input_snapshots','cost_source_captures','definition_"
        "revisions','definition_sources','definition_specs','engineering_configurations','manuf"
        "acturing_baseline_document_links','manufacturing_preparation_currents','manufacturing_"
        "preparation_versions','measurement_import_captures','operational_material_holds','oper"
        "ational_resource_occupancies','original_scan_requests','original_scan_results','origin"
        "al_security','outbox_events','parts','plan_proposals','plan_revisions','process_revisi"
        "ons','product_variants','professional_authority_current','professional_authority_facts"
        "','project_product_links','project_tasks','project_work_packages','projects','quality_"
        "current_issues','quality_current_policies','quality_event_failure_links','quality_fail"
        "ure_maps','quality_issue_versions','quality_policy_facts','request_keys','runs','sampl"
        "e_allocations','sample_current_readiness','sample_readiness_facts','sample_run_usages'"
        ",'sample_units','sample_usage_sentinels','supply_current_snapshots','supply_kit_projec"
        "tions','supply_snapshots','supply_source_captures','task_dependencies','test_measureme"
        "nts','test_resource_current','test_resource_facts','test_resource_reservations','test_"
        "result_actions','test_result_projections','uploaded_originals','variant_revisions','ve"
        "rification_actual_method_applicabilities','verification_actual_method_batches','verifi"
        "cation_current_actual_methods','verification_current_formal_requests','verification_cu"
        "rrent_preparations','verification_current_runs','verification_formal_requests','verifi"
        "cation_handoff_facts','verification_launch_facts','verification_method_applicabilities"
        "','verification_preparations','verification_run_identities','verification_run_versions"
        "','verification_window_proposals','work_requests','proposals','proposal_items','propos"
        "al_item_versions','proposal_revisions','proposal_sources','proposal_submissions','prop"
        "osal_decisions','project_open_items','category_knowledge_entries','category_knowledge_"
        "current','product_target_segments','parameter_versions','parameter_current','promotion"
        "_proofs','evidence_links','claim_withdrawals','manufacturing_baseline_publications','m"
        "anufacturing_publication_currents','manufacturing_publication_documents','native_pilot"
        "_runs','native_pilot_currents','native_pilot_observations','release_packages','release"
        "_package_currents','release_decisions','release_policy_facts','release_policy_currents"
        "','external_handoff_authorizations','external_delivery_intents','external_receipts','e"
        "xternal_handoff_currents','release_exception_decisions','release_exception_currents','"
        "work_commitment_reviews','work_commitment_review_currents','work_task_versions','work_"
        "task_currents','work_commitment_versions','work_commitment_currents','project_status_u"
        "pdates','external_wait_versions','external_wait_currents','project_risk_followups','pr"
        "oject_risk_followup_currents','knowledge_candidate_versions','knowledge_candidate_curr"
        "ents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_"
        "currents','field_feedback_versions','field_feedback_currents','field_response_records'"
        ",'knowledge_answer_reviews','knowledge_gap_submissions'] ELSE ARRAY[\n  'artifact_vers"
        "ions','claims','definition_revisions','definition_sources','definition_specs',\n  'pro"
        "posals','proposal_items','proposal_item_versions','proposal_submissions','proposal_dec"
        "isions',\n  'category_knowledge_entries','category_knowledge_current','parameter_versi"
        "ons','parameter_current',\n  'evidence_links','promotion_proofs','native_pilot_runs','"
        "native_pilot_currents','native_pilot_observations','release_packages','release_package"
        "_currents','release_decisions','release_policy_facts','release_policy_currents','exter"
        "nal_handoff_authorizations','external_delivery_intents','external_receipts','external_"
        "handoff_currents','release_exception_decisions','release_exception_currents','work_com"
        "mitment_reviews','work_commitment_review_currents','work_task_versions','work_task_cur"
        "rents','work_commitment_versions','work_commitment_currents','project_status_updates',"
        "'external_wait_versions','external_wait_currents','project_risk_followups','project_ri"
        "sk_followup_currents','knowledge_candidate_versions','knowledge_candidate_currents','k"
        "nowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents"
        "','field_feedback_versions','field_feedback_currents','field_response_records','knowle"
        "dge_answer_reviews','knowledge_gap_submissions'] END LOOP\n  FOR payload IN EXECUTE CA"
        "SE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n   THEN forma"
        "t('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON r.id=x.receipt"
        "_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',name)\n   E"
        "LSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND category_id=$2 "
        "AND ($3 IS NULL OR %I=ANY($3))',name,\n    CASE name WHEN 'category_knowledge_current'"
        " THEN 'lineage_id'\n     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id' END)\n"
        "   END USING t,c,identities LOOP\n   IF (payload->>'receipt_id')::uuid=ANY(controls) O"
        "R\n    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecycle.%') "
        "THEN CONTINUE; END IF;\n   table_name=name;\n   node_id=CASE name WHEN 'category_knowl"
        "edge_current' THEN (payload->>'lineage_id')::uuid\n    WHEN 'parameter_current' THEN ("
        "payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n   IF identities IS "
        'NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n   ELSE links=public'
        ".m3_lifecycle_source_links(t,c,name,payload); END IF;\n   -- Preserve predecessor's co"
        'nservative legacy graph; M3-only nodes use\n   -- strictly typed/relational links. Roo'
        "t lookup never uses free-text UUIDs.\n   IF identities IS NULL AND name<>ALL(ARRAY['na"
        "tive_pilot_runs','native_pilot_currents','native_pilot_observations','release_packages"
        "','release_package_currents','release_decisions','release_policy_facts','release_polic"
        "y_currents','external_handoff_authorizations','external_delivery_intents','external_re"
        "ceipts','external_handoff_currents','release_exception_decisions','release_exception_c"
        "urrents','work_commitment_reviews','work_commitment_review_currents','work_task_versio"
        "ns','work_task_currents','work_commitment_versions','work_commitment_currents','projec"
        "t_status_updates','external_wait_versions','external_wait_currents','project_risk_foll"
        "owups','project_risk_followup_currents','manufacturing_baseline_publications','manufac"
        "turing_publication_currents','manufacturing_publication_documents','proposals','propos"
        "al_items','proposal_item_versions','proposal_revisions','proposal_sources','proposal_s"
        "ubmissions','proposal_decisions','project_open_items','category_knowledge_entries','ca"
        "tegory_knowledge_current','product_target_segments','parameter_versions','parameter_cu"
        "rrent','promotion_proofs','evidence_links','claim_withdrawals','knowledge_candidate_ve"
        "rsions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledg"
        "e_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_c"
        "urrents','field_response_records','knowledge_answer_reviews','knowledge_gap_submission"
        "s']) THEN\n    links=links || public.kernel_lifecycle_links(name,payload);\n   END IF;"
        '\n   RETURN NEXT;\n  END LOOP;\n END LOOP;\nEND;\n$function$;\n\nCREATE TRIGGER catego'
        'ry_lifecycle_clock BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_answer_review'
        's FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_clock();\n\nCREATE TRIGG'
        'ER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_answer_re'
        'views FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_gate();\n\nCREATE TR'
        'IGGER category_lifecycle_clock BEFORE INSERT OR UPDATE OR DELETE ON public.knowledge_g'
        'ap_submissions FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_clock();\n'
        '\nCREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.knowl'
        'edge_gap_submissions FOR EACH ROW EXECUTE FUNCTION public.m3_lifecycle_reference_gate('
        ');\n'
    ),
)

EMPTY_HISTORY_SQL = (
    (
        'DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.knowledge_answer_reviews) OR EXISTS(SELECT '
        '1 FROM public.knowledge_gap_submissions) OR EXISTS(SELECT 1 FROM public.knowledge_gap_'
        "attributions) OR EXISTS(SELECT 1 FROM public.category_knowledge_entries WHERE kind='ve"
        "rified_answer') THEN RAISE EXCEPTION 'Cannot discard recorded knowledge contributions'"
        '; END IF; END $$;\n\n'
    ),
)

LIFECYCLE_DOWN_SQL = (
    (
        'DROP TRIGGER lifecycle_reference ON public.knowledge_answer_reviews;\n\nDROP TRIGGER c'
        'ategory_lifecycle_clock ON public.knowledge_answer_reviews;\n\nDROP TRIGGER lifecycle_'
        'reference ON public.knowledge_gap_submissions;\n\nDROP TRIGGER category_lifecycle_cloc'
        'k ON public.knowledge_gap_submissions;\n\nCREATE OR REPLACE FUNCTION public.m3_lifecyc'
        'le_source_links(t uuid, c uuid, table_name text, payload jsonb)\n RETURNS uuid[]\n LAN'
        "GUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', '"
        "pg_temp'\nAS $function$\nDECLARE links uuid[]='{}'; extra uuid[]; key text; keys text["
        ']; item jsonb; container jsonb;\n target_kind text; referenced_target uuid; referenced'
        "_version integer;\nBEGIN\n IF table_name='agent_runs' THEN RETURN public.kernel_lifecy"
        'cle_links(table_name,payload); END IF;\n -- Only actual top-level relation columns est'
        'ablish raw UUID edges. Arbitrary\n -- content dictionaries are not relational rows, ev'
        'en if an extra key happens\n -- to be named source_id or item_id.\n keys=CASE table_na'
        "me\n  WHEN 'artifact_versions' THEN ARRAY['original_id']\n  WHEN 'claims' THEN ARRAY['"
        "artifact_id','snapshot_id']\n  WHEN 'definition_revisions' THEN ARRAY['derived_from_de"
        "finition_id','parent_definition_id',\n   'source_proposal_id','source_submission_id']"
        "\n  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n  WHEN 'definition_specs' THE"
        "N ARRAY[]::text[]\n  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_sub"
        "mission_id']\n  WHEN 'proposal_items' THEN ARRAY[]::text[]\n  WHEN 'proposal_item_vers"
        "ions' THEN ARRAY[]::text[]\n  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']\n  W"
        "HEN 'proposal_sources' THEN ARRAY['source_id']\n  WHEN 'proposal_submissions' THEN ARR"
        "AY[]::text[]\n  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n  WHEN 'project"
        "_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
        "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n  WHEN 'promotion_"
        "proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n  WHEN 'evidence_links'"
        " THEN ARRAY['evidence_id']\n  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n  WHEN "
        "'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_"
        "id']\n  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n  WHEN 'ma"
        "nufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n  WHEN 'nat"
        "ive_pilot_runs' THEN ARRAY['build_id','lot_id','actual_configuration_id','engineering_"
        "configuration_id','process_id','publication_id']\n  WHEN 'native_pilot_currents' THEN "
        "ARRAY['pilot_id','latest_observation_id']\n  WHEN 'native_pilot_observations' THEN ARR"
        "AY['pilot_id','previous_observation_id']\n  WHEN 'release_packages' THEN ARRAY['previo"
        "us_id']\n  WHEN 'release_package_currents' THEN ARRAY['version_id']\n  WHEN 'release_d"
        "ecisions' THEN ARRAY['package_id']\n  WHEN 'release_policy_facts' THEN ARRAY['previous"
        "_id']\n  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n  WHEN 'external_handof"
        "f_authorizations' THEN ARRAY['package_id','engineering_decision_id','manufacturing_dec"
        "ision_id']\n  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n  WHEN 'exter"
        "nal_receipts' THEN ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id"
        "']\n  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_rec"
        "eipt_id']\n  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_"
        "fact_id','previous_id']\n  WHEN 'release_exception_currents' THEN ARRAY['basis_package"
        "_id','policy_fact_id','decision_id']\n  WHEN 'work_commitment_reviews' THEN ARRAY['com"
        "mitment_id','task_version_id','submission_id','previous_id']\n  WHEN 'work_commitment_"
        "review_currents' THEN ARRAY['version_id']\n  WHEN 'external_wait_versions' THEN ARRAY["
        "'previous_id']\n  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n  WHEN 'proj"
        "ect_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n  WHEN 'proj"
        "ect_risk_followup_currents' THEN ARRAY['version_id']\n  WHEN 'work_task_versions' THEN"
        " ARRAY['previous_id']\n  WHEN 'work_task_currents' THEN ARRAY['version_id']\n  WHEN 'w"
        "ork_commitment_versions' THEN ARRAY['replaces_id']\n  WHEN 'work_commitment_currents' "
        "THEN ARRAY['version_id']\n  WHEN 'project_status_updates' THEN ARRAY[]::text[]\n  ELSE"
        ' ARRAY[]::text[] END;\n FOREACH key IN ARRAY keys LOOP\n  IF payload->>key IS NOT NULL'
        ' THEN links=array_append(links,(payload->>key)::uuid); END IF;\n END LOOP;\n -- Public'
        "ation's exact saved read set is a validated Artifact relationship.\n -- Do not scan it"
        "s declaration, body, reason or arbitrary JSON UUID values.\n IF table_name IN ('manufa"
        "cturing_baseline_publications','native_pilot_runs','native_pilot_observations','releas"
        "e_packages','release_decisions','release_policy_facts','external_handoff_authorization"
        "s','external_receipts','release_exception_decisions') THEN\n  FOR item IN SELECT value"
        " FROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n "
        "  IF item->>'artifact_id' IS NOT NULL THEN\n    links=array_append(links,(item->>'arti"
        "fact_id')::uuid);\n   END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('native_pilot"
        "_runs','native_pilot_observations') THEN\n  FOR item IN SELECT value FROM jsonb_array_"
        "elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP\n   IF"
        " item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
        "  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{"
        "material_snapshot,statistics,issues}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN "
        "links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  item=payload#>'"
        "{material_snapshot,statistics,resource,fact}';\n  IF item->>'id' IS NOT NULL THEN link"
        "s=array_append(links,(item->>'id')::uuid); END IF;\n END IF;\n IF table_name='release_"
        "packages' THEN\n  -- FixedObject.ref is a closed, server-resolved version reference, n"
        'ot arbitrary body UUID text.\n  FOR item IN SELECT value FROM jsonb_array_elements(coa'
        "lesce(payload#>'{body,objects}','[]')) LOOP\n   container=item->'ref';\n   IF containe"
        "r->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manu"
        "facturing_publication','test_run','pilot_run','issue','change','exception','artifact',"
        "'work_instruction','control_plan','build_lot','line'])\n    AND container->>'id' IS NO"
        "T NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n"
        " END IF;\n IF table_name IN ('external_handoff_authorizations','external_delivery_inte"
        "nts') THEN\n  -- Only closed, owner-verified mapping and manifest references are sourc"
        "e edges.\n  container=CASE WHEN table_name='external_handoff_authorizations' THEN payl"
        "oad#>'{body,declaration}' ELSE payload->'body' END;\n  FOR item IN SELECT value FROM j"
        "sonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n   IF item->'ref'->>'k"
        "ind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom"
        "_revision','artifact','work_instruction','control_plan'])\n    AND item->'ref'->>'id' "
        "IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); END IF;\n  END "
        "LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manif"
        "est','[]')) LOOP\n   IF item->'artifact'->>'id' IS NOT NULL THEN links=array_append(li"
        "nks,(item->'artifact'->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n IF table_name='"
        "release_policy_facts' THEN\n  -- These are Closed DTO configuration references fixed b"
        "y the policy owner.\n  FOREACH key IN ARRAY ARRAY['definition','engineering_configurat"
        "ion','manufacturing_configuration'] LOOP\n   container=payload#>ARRAY['material','subj"
        "ect_config',key];\n   IF container->>'id' IS NOT NULL THEN links=array_append(links,(c"
        "ontainer->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- These stored fields are v"
        'alidated Reference containers. Do not feed the\n -- whole row or arbitrary content int'
        "o the canonical Reference parser.\n IF table_name=ANY(ARRAY['proposals','proposal_item"
        "_versions','proposal_submissions',\n  'category_knowledge_entries','definition_specs']"
        ") THEN\n  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs'"
        ",'baseline_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,pa"
        'yload->key);\n  END LOOP;\n END IF;\n -- Match ItemInput.content_schema and category_s'
        'ervice._references: only\n -- commercial_target, voice, and competitor have nested sou'
        "rce contracts.\n IF table_name='proposal_item_versions' AND payload->>'kind'='commerci"
        "al_target' THEN\n  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP\n  "
        " links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source')"
        ";\n  END LOOP;\n ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='v"
        "oice' THEN\n  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'"
        "representative_refs');\n ELSIF table_name='category_knowledge_entries' AND payload->>'"
        "kind'='competitor' THEN\n  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] L"
        "OOP\n   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'"
        "->key,'[]')) LOOP\n    links=links || public.m3_lifecycle_typed_links(t,c,item->'sourc"
        "e_ref');\n   END LOOP;\n  END LOOP;\n END IF;\n IF table_name='proposal_submissions' T"
        "HEN\n  container=payload->'frozen_document';\n  FOREACH key IN ARRAY ARRAY['source_ref"
        "s','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   links=links || "
        'public.m3_lifecycle_typed_links(t,c,container->key);\n  END LOOP;\n  FOR item IN SELEC'
        "T value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n   links=li"
        "nks || public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_"
        "id','proposal_id']);\n   -- The frozen read projection records actual EvidenceLink pro"
        "venance here.\n   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_l"
        "inks');\n  END LOOP;\n ELSIF table_name='promotion_proofs' THEN\n  FOR item IN SELECT "
        "value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) LOOP\n   I"
        "F item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid)"
        '; END IF;\n  END LOOP;\n END IF;\n -- Exact persisted EvidenceLink targets supplement '
        'these immutable versions.\n -- Reverted links and withdrawn Claims still retain the or'
        'iginal historical\n -- dependency; lifecycle cleanup must not erase their audit source'
        ".\n IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN\n "
        " target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;\n  refere"
        "nced_version=(payload->>'version')::integer;\n ELSIF table_name='category_knowledge_en"
        "tries' AND payload->>'id' IS NOT NULL THEN\n  target_kind='knowledge_entry'; reference"
        "d_target=(payload->>'id')::uuid;\n  referenced_version=(payload->>'version')::integer;"
        "\n ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n  target_k"
        "ind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n  SELECT revision IN"
        'TO referenced_version FROM public.definition_revisions\n   WHERE tenant_id=t AND categ'
        "ory_id=c AND id=(payload->>'definition_id')::uuid;\n END IF;\n IF referenced_target IS"
        ' NOT NULL AND referenced_version IS NOT NULL THEN\n  SELECT coalesce(array_agg(link.ev'
        "idence_id),'{}') INTO extra FROM public.evidence_links link\n   WHERE link.tenant_id=t"
        ' AND link.category_id=c AND link.target_type=target_kind\n    AND link.target_id=refer'
        'enced_target AND link.target_version=referenced_version;\n  links=links || extra;\n EN'
        'D IF;\n -- Child source rows point to their parent, whereas dependency traversal needs'
        "\n -- the parent's fixed source children as well. Keep the actual relational edge.\n I"
        "F table_name='definition_revisions' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO e"
        'xtra FROM (\n   SELECT id FROM public.definition_sources WHERE tenant_id=t AND categor'
        "y_id=c\n    AND definition_id=(payload->>'id')::uuid\n   UNION ALL SELECT id FROM publ"
        'ic.definition_specs WHERE tenant_id=t AND category_id=c\n    AND definition_id=(payloa'
        "d->>'id')::uuid\n  ) children;\n  links=links || extra;\n ELSIF table_name='proposals'"
        " THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_vers"
        "ions\n   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n"
        "  links=links || extra;\n ELSIF table_name='proposal_items' THEN\n  SELECT coalesce(ar"
        "ray_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n   WHERE tenant_id=t "
        "AND category_id=c AND item_id=(payload->>'id')::uuid;\n  links=links || extra;\n ELSIF"
        " table_name='product_target_segments' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO"
        ' extra FROM public.category_knowledge_entries\n   WHERE tenant_id=t AND category_id=c '
        "AND lineage_id=(payload->>'segment_lineage_id')::uuid\n    AND version=(payload->>'seg"
        "ment_version')::integer;\n  links=links || extra;\n ELSIF table_name='parameter_curren"
        "t' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versio"
        "ns\n   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')"
        "::uuid\n    AND version=(payload->>'current_version')::integer;\n  links=links || extr"
        "a;\n END IF;\n\n IF table_name IN ('work_task_versions','work_commitment_versions','pr"
        "oject_status_updates') THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coal"
        "esce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=a"
        "rray_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  IF table_name"
        "='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n   links=a"
        "rray_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n  END IF;\n  IF table_nam"
        "e='work_commitment_versions' THEN\n   SELECT coalesce(array_agg(id),'{}') INTO extra F"
        'ROM public.work_task_versions\n    WHERE tenant_id=t AND category_id=c AND task_id=(pa'
        "yload->>'task_id')::uuid AND revision=(payload->>'task_revision')::integer;\n   links="
        "links||extra;\n  ELSIF table_name='project_status_updates' THEN\n   FOR item IN SELECT"
        " value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP\n    SELECT"
        " coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n     WHERE te"
        "nant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND revision=(item->>'revi"
        "sion')::integer;\n    links=links||extra;\n   END LOOP;\n  END IF;\n END IF;\n\n IF ta"
        "ble_name='work_commitment_reviews' THEN\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n EN"
        "D IF;\n\n IF table_name='external_wait_versions' THEN\n  FOR item IN SELECT value FROM"
        " jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF "
        "item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n "
        " END LOOP;\n  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n   cont"
        "ainer=payload#>ARRAY['body',key];\n   IF container->>'id' IS NOT NULL THEN links=array"
        "_append(links,(container->>'id')::uuid); END IF;\n  END LOOP;\n  container=payload#>'{"
        "body,replaces}';\n  IF container->>'id' IS NOT NULL THEN\n   SELECT coalesce(array_agg"
        "(id),'{}') INTO extra FROM public.external_wait_versions\n    WHERE tenant_id=t AND ca"
        "tegory_id=c AND wait_id=(container->>'id')::uuid AND revision=(container->>'revision')"
        "::integer;\n   links=links||extra;\n  END IF;\n END IF;\n IF table_name='project_risk_"
        "followups' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload"
        "#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=arr"
        "ay_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n IF table_name"
        " IN ('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicab"
        "ility_assessments','knowledge_rule_versions','knowledge_rule_currents') THEN\n  FOREAC"
        "H key IN ARRAY ARRAY['previous_id','version_id','candidate_version_id','assessment_id'"
        ",'publication_id'] LOOP\n   IF payload->>key IS NOT NULL THEN links=array_append(links"
        ',(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_a'
        "rray_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'"
        "id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOO"
        "P;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]"
        "')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->"
        ">'artifact_id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_ar"
        "ray_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n   IF ite"
        "m->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid"
        "); END IF;\n   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'r"
        "ow_id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elem"
        "ents(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n   IF item"
        "->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n  END"
        " LOOP;\n  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN links=array_append("
        "links,(payload#>>'{source_basis,target,id}')::uuid); END IF;\n END IF;\n\n IF table_na"
        "me IN ('field_feedback_versions','field_feedback_currents','field_response_records') T"
        "HEN\n  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_version_id'] LO"
        'OP\n   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uui'
        'd); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesc'
        "e(payload#>'{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN "
        "links=array_append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOREACH key IN "
        "ARRAY ARRAY['engineering_configuration','manufacturing_configuration','batch'] LOOP\n "
        "  IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN links=array_append(l"
        "inks,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;\n  END LOOP;\n  FOR"
        " item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,resul"
        "t_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links=array_appen"
        "d(links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT NULL THEN "
        "links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LOOP;\n END IF;\n IF"
        " table_name IN ('change_request_versions','change_graph_captures') THEN\n  FOR contain"
        "er IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) LO"
        "OP\n   IF container->>'feedback_version_id' IS NOT NULL THEN links=array_append(links,"
        "(container->>'feedback_version_id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n -- Clos"
        'ed native Field plan and occurrence references, never arbitrary UUID prose.\n IF table'
        "_name='controlled_change_selection_facts' AND payload->>'basis_kind'='field_intent' TH"
        "EN\n  IF payload->>'feedback_version_id' IS NOT NULL THEN\n   links=array_append(links"
        ",(payload->>'feedback_version_id')::uuid);\n  END IF;\n END IF;\n IF table_name='chang"
        "e_implementation_captures'\n  AND payload#>>'{occurrence_snapshot,schema_version}'='pd"
        "os-field-change-implementation-occurrence-v1' THEN\n  FOREACH key IN ARRAY ARRAY['feed"
        "back_version_id','selection_id'] LOOP\n   IF payload#>>ARRAY['occurrence_snapshot',key"
        "] IS NOT NULL THEN\n    links=array_append(links,(payload#>>ARRAY['occurrence_snapshot"
        "',key])::uuid);\n   END IF;\n  END LOOP;\n END IF;\n\n IF table_name='change_completio"
        "n_records' THEN\n  FOREACH key IN ARRAY ARRAY['project_id','change_version_id','order_"
        "record_id','shared_proof_id'] LOOP\n   IF payload->>key IS NOT NULL THEN links=array_a"
        'ppend(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value F'
        "ROM jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n   "
        "IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id"
        "')::uuid); END IF;\n  END LOOP;\n  IF payload#>>'{native_input,lot,id}' IS NOT NULL TH"
        "EN links=array_append(links,(payload#>>'{native_input,lot,id}')::uuid); END IF;\n  FOR"
        " item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,sampl"
        "e_refs}','[]')) LOOP\n   links=array_append(links,(item->>'id')::uuid);\n  END LOOP;\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{native_input,"
        "mappings}','[]')) LOOP\n   SELECT coalesce(array_agg(id),'{}') INTO extra FROM verific"
        "ation_run_versions\n    WHERE tenant_id=t AND category_id=c AND run_id=(item#>>'{run,i"
        "d}')::uuid AND revision=(item#>>'{run,revision}')::integer;\n   links=links||extra; li"
        "nks=array_append(links,(item->>'sample_id')::uuid);\n  END LOOP;\n END IF;\n\n -- Clos"
        'ed native owner DTOs: retain exact outputs and native execution/report rows.\n IF tabl'
        "e_name='change_completion_records' THEN\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload#>'{fact_snapshot,output_refs}','[]')) LOOP\n   IF item->>'kin"
        "d'='test_run' THEN\n    SELECT coalesce(array_agg(id),'{}') INTO extra FROM verificati"
        "on_run_versions\n     WHERE tenant_id=t AND category_id=c AND run_id=(item->>'id')::uu"
        "id AND revision=(item->>'revision')::integer;\n    links=links||extra;\n   ELSIF item-"
        ">>'kind'=ANY(ARRAY['engineering_configuration','manufacturing_configuration','build','"
        "sample']) THEN\n    links=array_append(links,(item->>'id')::uuid);\n   END IF;\n  END "
        "LOOP;\n  IF payload#>>'{owner_basis,schema_version}'='pdos-native-build-adoption-read-"
        "v1' THEN\n   FOREACH key IN ARRAY ARRAY['previous_build','successor_build','actual_con"
        "figuration','lot','start'] LOOP\n    IF payload#>>ARRAY['owner_basis',key,'id'] IS NOT"
        " NULL THEN\n     links=array_append(links,(payload#>>ARRAY['owner_basis',key,'id'])::u"
        "uid);\n    END IF;\n   END LOOP;\n  ELSIF payload#>>'{owner_basis,schema_version}'='pd"
        "os-native-change-run-verification-v1' THEN\n   FOR container IN SELECT value FROM json"
        "b_each(coalesce(payload#>'{owner_basis,runs}','{}')) LOOP\n    FOREACH key IN ARRAY AR"
        "RAY['run_version_id','request_version_id','projection_id'] LOOP\n     IF container->>k"
        'ey IS NOT NULL THEN links=array_append(links,(container->>key)::uuid); END IF;\n    EN'
        'D LOOP;\n   END LOOP;\n  END IF;\n END IF;\n RETURN links;\nEND;\n$function$;\n\nCREAT'
        'E OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[] DEFA'
        'ULT NULL::uuid[])\n RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n LANGU'
        "AGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public', 'pg"
        "_temp'\nAS $function$\nDECLARE name text; payload jsonb; controls uuid[];\nBEGIN\n IF "
        "identities IS NULL THEN\n  SELECT coalesce(array_agg(id),'{}') INTO controls FROM publ"
        "ic.action_receipts\n   WHERE tenant_id=t AND category_id=c AND operation LIKE 'evidenc"
        "e.lifecycle.%';\n ELSE controls='{}'; END IF;\n FOREACH name IN ARRAY CASE WHEN identi"
        "ties IS NULL THEN ARRAY['agent_runs','action_receipts','actual_configurations','artifa"
        "ct_versions','audit_entries','bom_lines','bom_revisions','build_authorization_decision"
        "s','build_current_authorizations','build_current_execution_assessments','build_executi"
        "on_assessments','build_lots','build_operational_current','build_operational_facts','bu"
        "ild_readiness','build_starts','builds','capa_current_observations','capa_current_verif"
        "ication_rules','capa_named_verification_reviews','capa_observation_facts','capa_remedi"
        "ation_links','capa_verification_evidence','capa_verification_rule_facts','change_appro"
        "val_records','change_dependency_clocks','change_graph_captures','change_implementation"
        "_captures','change_implementation_records','change_order_records','change_request_curr"
        "ents','change_request_versions','claim_consumptions','claims','controlled_change_cover"
        "age_currents','controlled_change_coverage_facts','controlled_change_policy_currents','"
        "controlled_change_policy_facts','controlled_change_selection_currents','controlled_cha"
        "nge_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshots','co"
        "st_source_captures','definition_revisions','definition_sources','definition_specs','en"
        "gineering_configurations','manufacturing_baseline_document_links','manufacturing_prepa"
        "ration_currents','manufacturing_preparation_versions','measurement_import_captures','o"
        "perational_material_holds','operational_resource_occupancies','original_scan_requests'"
        ",'original_scan_results','original_security','outbox_events','parts','plan_proposals',"
        "'plan_revisions','process_revisions','product_variants','professional_authority_curren"
        "t','professional_authority_facts','project_product_links','project_tasks','project_wor"
        "k_packages','projects','quality_current_issues','quality_current_policies','quality_ev"
        "ent_failure_links','quality_failure_maps','quality_issue_versions','quality_policy_fac"
        "ts','request_keys','runs','sample_allocations','sample_current_readiness','sample_read"
        "iness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply_curre"
        "nt_snapshots','supply_kit_projections','supply_snapshots','supply_source_captures','ta"
        "sk_dependencies','test_measurements','test_resource_current','test_resource_facts','te"
        "st_resource_reservations','test_result_actions','test_result_projections','uploaded_or"
        "iginals','variant_revisions','verification_actual_method_applicabilities','verificatio"
        "n_actual_method_batches','verification_current_actual_methods','verification_current_f"
        "ormal_requests','verification_current_preparations','verification_current_runs','verif"
        "ication_formal_requests','verification_handoff_facts','verification_launch_facts','ver"
        "ification_method_applicabilities','verification_preparations','verification_run_identi"
        "ties','verification_run_versions','verification_window_proposals','work_requests','pro"
        "posals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sourc"
        "es','proposal_submissions','proposal_decisions','project_open_items','category_knowled"
        "ge_entries','category_knowledge_current','product_target_segments','parameter_versions"
        "','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','manufac"
        "turing_baseline_publications','manufacturing_publication_currents','manufacturing_publ"
        "ication_documents','native_pilot_runs','native_pilot_currents','native_pilot_observati"
        "ons','release_packages','release_package_currents','release_decisions','release_policy"
        "_facts','release_policy_currents','external_handoff_authorizations','external_delivery"
        "_intents','external_receipts','external_handoff_currents','release_exception_decisions"
        "','release_exception_currents','work_commitment_reviews','work_commitment_review_curre"
        "nts','work_task_versions','work_task_currents','work_commitment_versions','work_commit"
        "ment_currents','project_status_updates','external_wait_versions','external_wait_curren"
        "ts','project_risk_followups','project_risk_followup_currents','knowledge_candidate_ver"
        "sions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge"
        "_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_cu"
        "rrents','field_response_records'] ELSE ARRAY[\n  'artifact_versions','claims','definit"
        "ion_revisions','definition_sources','definition_specs',\n  'proposals','proposal_items"
        "','proposal_item_versions','proposal_submissions','proposal_decisions',\n  'category_k"
        "nowledge_entries','category_knowledge_current','parameter_versions','parameter_current"
        "',\n  'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_currents',"
        "'native_pilot_observations','release_packages','release_package_currents','release_dec"
        "isions','release_policy_facts','release_policy_currents','external_handoff_authorizati"
        "ons','external_delivery_intents','external_receipts','external_handoff_currents','rele"
        "ase_exception_decisions','release_exception_currents','work_commitment_reviews','work_"
        "commitment_review_currents','work_task_versions','work_task_currents','work_commitment"
        "_versions','work_commitment_currents','project_status_updates','external_wait_versions"
        "','external_wait_currents','project_risk_followups','project_risk_followup_currents','"
        "knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_"
        "assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versi"
        "ons','field_feedback_currents','field_response_records'] END LOOP\n  FOR payload IN EX"
        "ECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])\n   TH"
        "EN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON r.id=x"
        ".receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id=$2',nam"
        "e)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND categor"
        "y_id=$2 AND ($3 IS NULL OR %I=ANY($3))',name,\n    CASE name WHEN 'category_knowledge_"
        "current' THEN 'lineage_id'\n     WHEN 'parameter_current' THEN 'parameter_id' ELSE 'id"
        "' END)\n   END USING t,c,identities LOOP\n   IF (payload->>'receipt_id')::uuid=ANY(con"
        "trols) OR\n    (name='action_receipts' AND payload->>'operation' LIKE 'evidence.lifecy"
        "cle.%') THEN CONTINUE; END IF;\n   table_name=name;\n   node_id=CASE name WHEN 'catego"
        "ry_knowledge_current' THEN (payload->>'lineage_id')::uuid\n    WHEN 'parameter_current"
        "' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n   IF identi"
        'ties IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n   ELSE link'
        's=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n   -- Preserve predeces'
        "sor's conservative legacy graph; M3-only nodes use\n   -- strictly typed/relational li"
        'nks. Root lookup never uses free-text UUIDs.\n   IF identities IS NULL AND name<>ALL(A'
        "RRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','release_"
        "packages','release_package_currents','release_decisions','release_policy_facts','relea"
        "se_policy_currents','external_handoff_authorizations','external_delivery_intents','ext"
        "ernal_receipts','external_handoff_currents','release_exception_decisions','release_exc"
        "eption_currents','work_commitment_reviews','work_commitment_review_currents','work_tas"
        "k_versions','work_task_currents','work_commitment_versions','work_commitment_currents'"
        ",'project_status_updates','external_wait_versions','external_wait_currents','project_r"
        "isk_followups','project_risk_followup_currents','manufacturing_baseline_publications',"
        "'manufacturing_publication_currents','manufacturing_publication_documents','proposals'"
        ",'proposal_items','proposal_item_versions','proposal_revisions','proposal_sources','pr"
        "oposal_submissions','proposal_decisions','project_open_items','category_knowledge_entr"
        "ies','category_knowledge_current','product_target_segments','parameter_versions','para"
        "meter_current','promotion_proofs','evidence_links','claim_withdrawals','knowledge_cand"
        "idate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','"
        "knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_fe"
        "edback_currents','field_response_records']) THEN\n    links=links || public.kernel_lif"
        'ecycle_links(name,payload);\n   END IF;\n   RETURN NEXT;\n  END LOOP;\n END LOOP;\nEND'
        ';\n$function$;\n\nDROP FUNCTION public.assistant_source_lifecycle_links(uuid,uuid,json'
        'b);\n'
    ),
)

DOWNGRADE_SQL = (
    (
        'DROP FUNCTION public.knowledge_weekly_lookup_stats(uuid,uuid,timestamptz,timestamptz);'
        '\n\nDROP POLICY knowledge_answer_source_read ON public.category_knowledge_entries;\n\n'
        'DROP POLICY knowledge_answer_source_read ON public.knowledge_candidate_versions;\n\nDR'
        'OP POLICY knowledge_answer_source_read ON public.knowledge_rule_versions;\n\nDROP TRIG'
        'GER knowledge_answer_origin ON public.category_knowledge_entries;\n\nDROP TRIGGER know'
        'ledge_answer_origin ON public.knowledge_candidate_versions;\n\nDROP TRIGGER knowledge_'
        'answer_origin ON public.knowledge_rule_versions;\n\nDROP FUNCTION public.require_knowl'
        'edge_answer_origin();\n\nDROP TABLE public.knowledge_gap_attributions;\n\nDROP TABLE p'
        'ublic.knowledge_gap_submissions;\n\nDROP TABLE public.knowledge_answer_reviews;\n\nDRO'
        'P FUNCTION public.knowledge_answer_sources_visible(uuid,uuid,jsonb);\n\nDROP FUNCTION '
        'public.assert_knowledge_assistant_fact();\n\nDROP FUNCTION public.knowledge_answer_sou'
        'rces_known(uuid,jsonb);\n\nALTER TABLE public.category_knowledge_entries DROP CONSTRAI'
        'NT category_knowledge_kind;\n\nALTER TABLE public.category_knowledge_entries ADD CONST'
        "RAINT category_knowledge_kind CHECK (kind IN ('boundary','segment','competitor','voice"
        "','regulation','research_question'));\n\nALTER TABLE public.knowledge_candidate_versio"
        'ns DROP CONSTRAINT knowledge_source_body_shape;\n\nALTER TABLE public.knowledge_candid'
        "ate_versions ADD CONSTRAINT knowledge_source_body_shape CHECK (jsonb_typeof(command)='"
        "object' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_basis)='object' AND js"
        "onb_typeof(sources)='array' AND jsonb_typeof(reads)='array' AND jsonb_array_length(sou"
        'rces)>0 AND jsonb_array_length(reads)>0);\n\nALTER TABLE public.knowledge_rule_version'
        's DROP CONSTRAINT knowledge_source_body_shape;\n\nALTER TABLE public.knowledge_rule_ve'
        "rsions ADD CONSTRAINT knowledge_source_body_shape CHECK (jsonb_typeof(command)='object"
        "' AND jsonb_typeof(body)='object' AND jsonb_typeof(source_basis)='object' AND jsonb_ty"
        "peof(sources)='array' AND jsonb_typeof(reads)='array' AND jsonb_array_length(sources)>"
        '0 AND jsonb_array_length(reads)>0);\n\nALTER TABLE public.category_knowledge_entries D'
        'ROP COLUMN answer_sources;\n'
    ),
)

PREVIOUS_FUNCTIONS = {
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name'
        ' text, payload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n '
        "SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE links uui"
        "d[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n target_k"
        "ind text; referenced_target uuid; referenced_version integer;\nBEGIN\n IF table_name='"
        "agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n -"
        '- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n -- cont'
        'ent dictionaries are not relational rows, even if an extra key happens\n -- to be name'
        "d source_id or item_id.\n keys=CASE table_name\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n  WHEN 'defin"
        "ition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n   '"
        "source_proposal_id','source_submission_id']\n  WHEN 'definition_sources' THEN ARRAY['a"
        "rtifact_id']\n  WHEN 'definition_specs' THEN ARRAY[]::text[]\n  WHEN 'proposals' THEN "
        "ARRAY['baseline_definition_id','current_submission_id']\n  WHEN 'proposal_items' THEN "
        "ARRAY[]::text[]\n  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n  WHEN 'proposa"
        "l_revisions' THEN ARRAY['proposal_id']\n  WHEN 'proposal_sources' THEN ARRAY['source_i"
        "d']\n  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n  WHEN 'proposal_decisions' T"
        "HEN ARRAY['submission_id']\n  WHEN 'project_open_items' THEN ARRAY['source_question_id"
        "','source_spec_item_id','g0_decision_id']\n  WHEN 'category_knowledge_current' THEN AR"
        "RAY['current_entry_id']\n  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','so"
        "urce_proposal_id']\n  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n  WHEN 'claim_w"
        "ithdrawals' THEN ARRAY['claim_id']\n  WHEN 'manufacturing_baseline_publications' THEN "
        "ARRAY['baseline_id','process_id','previous_id']\n  WHEN 'manufacturing_publication_cur"
        "rents' THEN ARRAY['version_id']\n  WHEN 'manufacturing_publication_documents' THEN ARR"
        "AY['document_id','process_id']\n  WHEN 'native_pilot_runs' THEN ARRAY['build_id','lot_"
        "id','actual_configuration_id','engineering_configuration_id','process_id','publication"
        "_id']\n  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
        "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n "
        " WHEN 'release_packages' THEN ARRAY['previous_id']\n  WHEN 'release_package_currents' "
        "THEN ARRAY['version_id']\n  WHEN 'release_decisions' THEN ARRAY['package_id']\n  WHEN "
        "'release_policy_facts' THEN ARRAY['previous_id']\n  WHEN 'release_policy_currents' THE"
        "N ARRAY['fact_id']\n  WHEN 'external_handoff_authorizations' THEN ARRAY['package_id','"
        "engineering_decision_id','manufacturing_decision_id']\n  WHEN 'external_delivery_inten"
        "ts' THEN ARRAY['handoff_id']\n  WHEN 'external_receipts' THEN ARRAY['handoff_id','inte"
        "nt_id','previous_receipt_id','reconciles_id']\n  WHEN 'external_handoff_currents' THEN"
        " ARRAY['handoff_id','intent_id','latest_receipt_id']\n  WHEN 'release_exception_decisi"
        "ons' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n  WHEN 'release_ex"
        "ception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n  WHE"
        "N 'work_commitment_reviews' THEN ARRAY['commitment_id','task_version_id','submission_i"
        "d','previous_id']\n  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n  WHEN 'external_wait_curre"
        "nts' THEN ARRAY['version_id']\n  WHEN 'project_risk_followups' THEN ARRAY['previous_id"
        "','risk_id','g0_decision_id']\n  WHEN 'project_risk_followup_currents' THEN ARRAY['ver"
        "sion_id']\n  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n  WHEN 'work_task_cu"
        "rrents' THEN ARRAY['version_id']\n  WHEN 'work_commitment_versions' THEN ARRAY['replac"
        "es_id']\n  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n  WHEN 'project_s"
        "tatus_updates' THEN ARRAY[]::text[]\n  ELSE ARRAY[]::text[] END;\n FOREACH key IN ARRA"
        'Y keys LOOP\n  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>k'
        "ey)::uuid); END IF;\n END LOOP;\n -- Publication's exact saved read set is a validated"
        ' Artifact relationship.\n -- Do not scan its declaration, body, reason or arbitrary JS'
        "ON UUID values.\n IF table_name IN ('manufacturing_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','release_packages','release_decisions','release_po"
        "licy_facts','external_handoff_authorizations','external_receipts','release_exception_d"
        "ecisions') THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload"
        "->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN"
        "\n    links=array_append(links,(item->>'artifact_id')::uuid);\n   END IF;\n  END LOOP;"
        "\n END IF;\n IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{material_snap"
        "shot,statistics,samples}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_"
        "append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FR"
        "OM jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]'"
        ")) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uu"
        "id); END IF;\n  END LOOP;\n  item=payload#>'{material_snapshot,statistics,resource,fac"
        "t}';\n  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid);"
        " END IF;\n END IF;\n IF table_name='release_packages' THEN\n  -- FixedObject.ref is a "
        'closed, server-resolved version reference, not arbitrary body UUID text.\n  FOR item I'
        "N SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOO"
        "P\n   container=item->'ref';\n   IF container->>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','manufacturing_publication','test_run','pilot_r"
        "un','issue','change','exception','artifact','work_instruction','control_plan','build_l"
        "ot','line'])\n    AND container->>'id' IS NOT NULL THEN links=array_append(links,(cont"
        "ainer->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('external_han"
        "doff_authorizations','external_delivery_intents') THEN\n  -- Only closed, owner-verifi"
        'ed mapping and manifest references are source edges.\n  container=CASE WHEN table_name'
        "='external_handoff_authorizations' THEN payload#>'{body,declaration}' ELSE payload->'b"
        "ody' END;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'m"
        "appings','[]')) LOOP\n   IF item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_c"
        "onfiguration','process_revision','part','bom_revision','artifact','work_instruction','"
        "control_plan'])\n    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,"
        "(item->'ref'->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jso"
        "nb_array_elements(coalesce(container->'manifest','[]')) LOOP\n   IF item->'artifact'->"
        ">'id' IS NOT NULL THEN links=array_append(links,(item->'artifact'->>'id')::uuid); END "
        "IF;\n  END LOOP;\n END IF;\n IF table_name='release_policy_facts' THEN\n  -- These are"
        ' Closed DTO configuration references fixed by the policy owner.\n  FOREACH key IN ARRA'
        "Y ARRAY['definition','engineering_configuration','manufacturing_configuration'] LOOP\n"
        "   container=payload#>ARRAY['material','subject_config',key];\n   IF container->>'id' "
        "IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n  END LO"
        'OP;\n END IF;\n -- These stored fields are validated Reference containers. Do not feed'
        ' the\n -- whole row or arbitrary content into the canonical Reference parser.\n IF tab'
        "le_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n  'cat"
        "egory_knowledge_entries','definition_specs']) THEN\n  FOREACH key IN ARRAY ARRAY['sour"
        "ce_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   links=lin"
        'ks || public.m3_lifecycle_typed_links(t,c,payload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and category_service._references: only\n -- commercial_t'
        "arget, voice, and competitor have nested source contracts.\n IF table_name='proposal_i"
        "tem_versions' AND payload->>'kind'='commercial_target' THEN\n  FOREACH key IN ARRAY AR"
        "RAY['target_price','cost','volume'] LOOP\n   links=links || public.m3_lifecycle_typed_"
        "links(t,c,payload->'content'->key->'source');\n  END LOOP;\n ELSIF table_name='categor"
        "y_knowledge_entries' AND payload->>'kind'='voice' THEN\n  links=links || public.m3_lif"
        "ecycle_typed_links(t,c,payload->'content'->'representative_refs');\n ELSIF table_name="
        "'category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n  FOREACH key IN "
        "ARRAY ARRAY['metrics','features','prices'] LOOP\n   FOR item IN SELECT value FROM json"
        "b_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n    links=links || publ"
        "ic.m3_lifecycle_typed_links(t,c,item->'source_ref');\n   END LOOP;\n  END LOOP;\n END "
        "IF;\n IF table_name='proposal_submissions' THEN\n  container=payload->'frozen_document"
        "';\n  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,contai"
        'ner->key);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce'
        "(container->'items','[]')) LOOP\n   links=links || public.m3_lifecycle_source_links(t,"
        "c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink provenance here.\n   links=links || public.m3'
        "_lifecycle_typed_links(t,c,item->'evidence_links');\n  END LOOP;\n ELSIF table_name='p"
        "romotion_proofs' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p"
        "ayload->'source_item_refs','[]')) LOOP\n   IF item->>'item_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'item_id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- Exac"
        't persisted EvidenceLink targets supplement these immutable versions.\n -- Reverted li'
        'nks and withdrawn Claims still retain the original historical\n -- dependency; lifecyc'
        "le cleanup must not erase their audit source.\n IF table_name='proposal_item_versions'"
        " AND payload->>'item_id' IS NOT NULL THEN\n  target_kind='proposal_item'; referenced_t"
        "arget=(payload->>'item_id')::uuid;\n  referenced_version=(payload->>'version')::intege"
        "r;\n ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN"
        "\n  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n  refere"
        "nced_version=(payload->>'version')::integer;\n ELSIF table_name='definition_specs' AND"
        " payload->>'id' IS NOT NULL THEN\n  target_kind='definition_spec'; referenced_target=("
        "payload->>'id')::uuid;\n  SELECT revision INTO referenced_version FROM public.definiti"
        "on_revisions\n   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id'"
        ')::uuid;\n END IF;\n IF referenced_target IS NOT NULL AND referenced_version IS NOT NU'
        "LL THEN\n  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.ev"
        'idence_links link\n   WHERE link.tenant_id=t AND link.category_id=c AND link.target_ty'
        'pe=target_kind\n    AND link.target_id=referenced_target AND link.target_version=refer'
        'enced_version;\n  links=links || extra;\n END IF;\n -- Child source rows point to thei'
        "r parent, whereas dependency traversal needs\n -- the parent's fixed source children a"
        "s well. Keep the actual relational edge.\n IF table_name='definition_revisions' THEN\n"
        "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n   SELECT id FROM public.defi"
        "nition_sources WHERE tenant_id=t AND category_id=c\n    AND definition_id=(payload->>'"
        "id')::uuid\n   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND "
        "category_id=c\n    AND definition_id=(payload->>'id')::uuid\n  ) children;\n  links=li"
        "nks || extra;\n ELSIF table_name='proposals' THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO extra FROM public.proposal_item_versions\n   WHERE tenant_id=t AND category_id"
        "=c AND proposal_id=(payload->>'id')::uuid;\n  links=links || extra;\n ELSIF table_name"
        "='proposal_items' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.p"
        "roposal_item_versions\n   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'"
        "id')::uuid;\n  links=links || extra;\n ELSIF table_name='product_target_segments' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entr"
        "ies\n   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage"
        "_id')::uuid\n    AND version=(payload->>'segment_version')::integer;\n  links=links ||"
        " extra;\n ELSIF table_name='parameter_current' THEN\n  SELECT coalesce(array_agg(id),'"
        "{}') INTO extra FROM public.parameter_versions\n   WHERE tenant_id=t AND category_id=c"
        " AND parameter_id=(payload->>'parameter_id')::uuid\n    AND version=(payload->>'curren"
        "t_version')::integer;\n  links=links || extra;\n END IF;\n\n IF table_name IN ('work_t"
        "ask_versions','work_commitment_versions','project_status_updates') THEN\n  FOR item IN"
        " SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF i"
        "tem->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::"
        "uuid); END IF;\n  END LOOP;\n  IF table_name='work_task_versions' AND payload#>>'{body"
        ",plan_task,id}' IS NOT NULL THEN\n   links=array_append(links,(payload#>>'{body,plan_t"
        "ask,id}')::uuid);\n  END IF;\n  IF table_name='work_commitment_versions' THEN\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n    WHERE t"
        "enant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND revision=(pay"
        "load->>'task_revision')::integer;\n   links=links||extra;\n  ELSIF table_name='project"
        "_status_updates' THEN\n   FOR item IN SELECT value FROM jsonb_array_elements(coalesce("
        "payload->'task_refs','[]')) LOOP\n    SELECT coalesce(array_agg(id),'{}') INTO extra F"
        'ROM public.work_task_versions\n     WHERE tenant_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'revision')::integer;\n    links=links||extra;"
        "\n   END LOOP;\n  END IF;\n END IF;\n\n IF table_name='work_commitment_reviews' THEN\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) "
        "LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'ar"
        "tifact_id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n IF table_name='external_wait_ve"
        "rsions' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'"
        "{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_"
        "append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOREACH key IN ARRAY ARRAY["
        "'milestone','build','calendar'] LOOP\n   container=payload#>ARRAY['body',key];\n   IF "
        "container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); "
        "END IF;\n  END LOOP;\n  container=payload#>'{body,replaces}';\n  IF container->>'id' I"
        "S NOT NULL THEN\n   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.externa"
        "l_wait_versions\n    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id'"
        ")::uuid AND revision=(container->>'revision')::integer;\n   links=links||extra;\n  END"
        " IF;\n END IF;\n IF table_name='project_risk_followups' THEN\n  FOR item IN SELECT val"
        "ue FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP"
        "\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); EN"
        "D IF;\n  END LOOP;\n END IF;\n\n IF table_name IN ('knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versi"
        "ons','knowledge_rule_currents') THEN\n  FOREACH key IN ARRAY ARRAY['previous_id','vers"
        "ion_id','candidate_version_id','assessment_id','publication_id'] LOOP\n   IF payload->"
        '>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n  END '
        "LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append("
        "links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM json"
        "b_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS "
        "NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END L"
        "OOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT"
        " NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LOOP;\n  "
        "FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,pr"
        "ofessional,fact_refs}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_app"
        "end(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  IF payload#>>'{source_basis,ta"
        "rget,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'{source_basis,target,i"
        "d}')::uuid); END IF;\n END IF;\n\n IF table_name IN ('field_feedback_versions','field_"
        "feedback_currents','field_response_records') THEN\n  FOREACH key IN ARRAY ARRAY['previ"
        "ous_id','version_id','feedback_version_id'] LOOP\n   IF payload->>key IS NOT NULL THEN"
        ' links=array_append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN '
        "SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::"
        "uuid); END IF;\n  END LOOP;\n  FOREACH key IN ARRAY ARRAY['engineering_configuration',"
        "'manufacturing_configuration','batch'] LOOP\n   IF payload#>>ARRAY['body','location',k"
        "ey,'id'] IS NOT NULL THEN links=array_append(links,(payload#>>ARRAY['body','location',"
        "key,'id'])::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n   IF item->>'"
        "receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); EN"
        "D IF;\n   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id"
        "')::uuid); END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('change_request_versions"
        "','change_graph_captures') THEN\n  FOR container IN SELECT value FROM jsonb_each(coale"
        "sce(payload#>'{source_basis,owners}','{}')) LOOP\n   IF container->>'feedback_version_"
        "id' IS NOT NULL THEN links=array_append(links,(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Closed native Field plan and occurrence refe'
        "rences, never arbitrary UUID prose.\n IF table_name='controlled_change_selection_facts"
        "' AND payload->>'basis_kind'='field_intent' THEN\n  IF payload->>'feedback_version_id'"
        " IS NOT NULL THEN\n   links=array_append(links,(payload->>'feedback_version_id')::uuid"
        ");\n  END IF;\n END IF;\n IF table_name='change_implementation_captures'\n  AND payloa"
        "d#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrenc"
        "e-v1' THEN\n  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] LOOP\n "
        "  IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n    links=array_appe"
        "nd(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);\n   END IF;\n  END LOOP;"
        "\n END IF;\n\n IF table_name='change_completion_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','order_record_id','shared_proof_id'] LOOP\n   I"
        'F payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END '
        'IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payloa'
        "d->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN"
        " links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  IF pa"
        "yload#>>'{native_input,lot,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'"
        "{native_input,lot,id}')::uuid); END IF;\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload#>'{native_input,sample_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_ar"
        "ray_elements(coalesce(payload#>'{native_input,mappings}','[]')) LOOP\n   SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM verification_run_versions\n    WHERE tenant_id="
        "t AND category_id=c AND run_id=(item#>>'{run,id}')::uuid AND revision=(item#>>'{run,re"
        "vision}')::integer;\n   links=links||extra; links=array_append(links,(item->>'sample_i"
        "d')::uuid);\n  END LOOP;\n END IF;\n\n -- Closed native owner DTOs: retain exact outpu"
        "ts and native execution/report rows.\n IF table_name='change_completion_records' THEN"
        "\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{fact_snapsh"
        "ot,output_refs}','[]')) LOOP\n   IF item->>'kind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM verification_run_versions\n     WHERE tenant_id=t"
        " AND category_id=c AND run_id=(item->>'id')::uuid AND revision=(item->>'revision')::in"
        "teger;\n    links=links||extra;\n   ELSIF item->>'kind'=ANY(ARRAY['engineering_configu"
        "ration','manufacturing_configuration','build','sample']) THEN\n    links=array_append("
        "links,(item->>'id')::uuid);\n   END IF;\n  END LOOP;\n  IF payload#>>'{owner_basis,sch"
        "ema_version}'='pdos-native-build-adoption-read-v1' THEN\n   FOREACH key IN ARRAY ARRAY"
        "['previous_build','successor_build','actual_configuration','lot','start'] LOOP\n    IF"
        " payload#>>ARRAY['owner_basis',key,'id'] IS NOT NULL THEN\n     links=array_append(lin"
        "ks,(payload#>>ARRAY['owner_basis',key,'id'])::uuid);\n    END IF;\n   END LOOP;\n  ELS"
        "IF payload#>>'{owner_basis,schema_version}'='pdos-native-change-run-verification-v1' T"
        "HEN\n   FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{owner_basis,"
        "runs}','{}')) LOOP\n    FOREACH key IN ARRAY ARRAY['run_version_id','request_version_i"
        "d','projection_id'] LOOP\n     IF container->>key IS NOT NULL THEN links=array_append("
        'links,(container->>key)::uuid); END IF;\n    END LOOP;\n   END LOOP;\n  END IF;\n END '
        'IF;\n RETURN links;\nEND;\n$function$\n'
    ),
    'm3_lifecycle_nodes(uuid,uuid,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[]'
        ' DEFAULT NULL::uuid[])\n RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n '
        "LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public'"
        ", 'pg_temp'\nAS $function$\nDECLARE name text; payload jsonb; controls uuid[];\nBEGIN"
        "\n IF identities IS NULL THEN\n  SELECT coalesce(array_agg(id),'{}') INTO controls FRO"
        "M public.action_receipts\n   WHERE tenant_id=t AND category_id=c AND operation LIKE 'e"
        "vidence.lifecycle.%';\n ELSE controls='{}'; END IF;\n FOREACH name IN ARRAY CASE WHEN "
        "identities IS NULL THEN ARRAY['agent_runs','action_receipts','actual_configurations','"
        "artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_de"
        "cisions','build_current_authorizations','build_current_execution_assessments','build_e"
        "xecution_assessments','build_lots','build_operational_current','build_operational_fact"
        "s','build_readiness','build_starts','builds','capa_current_observations','capa_current"
        "_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_"
        "remediation_links','capa_verification_evidence','capa_verification_rule_facts','change"
        "_approval_records','change_dependency_clocks','change_graph_captures','change_implemen"
        "tation_captures','change_implementation_records','change_order_records','change_reques"
        "t_currents','change_request_versions','claim_consumptions','claims','controlled_change"
        "_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_curre"
        "nts','controlled_change_policy_facts','controlled_change_selection_currents','controll"
        "ed_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshot"
        "s','cost_source_captures','definition_revisions','definition_sources','definition_spec"
        "s','engineering_configurations','manufacturing_baseline_document_links','manufacturing"
        "_preparation_currents','manufacturing_preparation_versions','measurement_import_captur"
        "es','operational_material_holds','operational_resource_occupancies','original_scan_req"
        "uests','original_scan_results','original_security','outbox_events','parts','plan_propo"
        "sals','plan_revisions','process_revisions','product_variants','professional_authority_"
        "current','professional_authority_facts','project_product_links','project_tasks','proje"
        "ct_work_packages','projects','quality_current_issues','quality_current_policies','qual"
        "ity_event_failure_links','quality_failure_maps','quality_issue_versions','quality_poli"
        "cy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sampl"
        "e_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply"
        "_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_capture"
        "s','task_dependencies','test_measurements','test_resource_current','test_resource_fact"
        "s','test_resource_reservations','test_result_actions','test_result_projections','uploa"
        "ded_originals','variant_revisions','verification_actual_method_applicabilities','verif"
        "ication_actual_method_batches','verification_current_actual_methods','verification_cur"
        "rent_formal_requests','verification_current_preparations','verification_current_runs',"
        "'verification_formal_requests','verification_handoff_facts','verification_launch_facts"
        "','verification_method_applicabilities','verification_preparations','verification_run_"
        "identities','verification_run_versions','verification_window_proposals','work_requests"
        "','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','proposal_decisions','project_open_items','category_k"
        "nowledge_entries','category_knowledge_current','product_target_segments','parameter_ve"
        "rsions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','m"
        "anufacturing_baseline_publications','manufacturing_publication_currents','manufacturin"
        "g_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_obs"
        "ervations','release_packages','release_package_currents','release_decisions','release_"
        "policy_facts','release_policy_currents','external_handoff_authorizations','external_de"
        "livery_intents','external_receipts','external_handoff_currents','release_exception_dec"
        "isions','release_exception_currents','work_commitment_reviews','work_commitment_review"
        "_currents','work_task_versions','work_task_currents','work_commitment_versions','work_"
        "commitment_currents','project_status_updates','external_wait_versions','external_wait_"
        "currents','project_risk_followups','project_risk_followup_currents','knowledge_candida"
        "te_versions','knowledge_candidate_currents','knowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedb"
        "ack_currents','field_response_records'] ELSE ARRAY[\n  'artifact_versions','claims','d"
        "efinition_revisions','definition_sources','definition_specs',\n  'proposals','proposal"
        "_items','proposal_item_versions','proposal_submissions','proposal_decisions',\n  'cate"
        "gory_knowledge_entries','category_knowledge_current','parameter_versions','parameter_c"
        "urrent',\n  'evidence_links','promotion_proofs','native_pilot_runs','native_pilot_curr"
        "ents','native_pilot_observations','release_packages','release_package_currents','relea"
        "se_decisions','release_policy_facts','release_policy_currents','external_handoff_autho"
        "rizations','external_delivery_intents','external_receipts','external_handoff_currents'"
        ",'release_exception_decisions','release_exception_currents','work_commitment_reviews',"
        "'work_commitment_review_currents','work_task_versions','work_task_currents','work_comm"
        "itment_versions','work_commitment_currents','project_status_updates','external_wait_ve"
        "rsions','external_wait_currents','project_risk_followups','project_risk_followup_curre"
        "nts','knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicab"
        "ility_assessments','knowledge_rule_versions','knowledge_rule_currents','field_feedback"
        "_versions','field_feedback_currents','field_response_records'] END LOOP\n  FOR payload"
        " IN EXECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_events','request_keys'])"
        "\n   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN public.action_receipts r ON"
        ' r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_id=$1 AND r.category_id='
        "$2',name)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x WHERE tenant_id=$1 AND "
        "category_id=$2 AND ($3 IS NULL OR %I=ANY($3))',name,\n    CASE name WHEN 'category_kno"
        "wledge_current' THEN 'lineage_id'\n     WHEN 'parameter_current' THEN 'parameter_id' E"
        "LSE 'id' END)\n   END USING t,c,identities LOOP\n   IF (payload->>'receipt_id')::uuid="
        "ANY(controls) OR\n    (name='action_receipts' AND payload->>'operation' LIKE 'evidence"
        ".lifecycle.%') THEN CONTINUE; END IF;\n   table_name=name;\n   node_id=CASE name WHEN "
        "'category_knowledge_current' THEN (payload->>'lineage_id')::uuid\n    WHEN 'parameter_"
        "current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>'id')::uuid END;\n   IF"
        ' identities IS NULL THEN links=public.m3_lifecycle_row_links(t,c,name,payload);\n   EL'
        'SE links=public.m3_lifecycle_source_links(t,c,name,payload); END IF;\n   -- Preserve p'
        "redecessor's conservative legacy graph; M3-only nodes use\n   -- strictly typed/relati"
        'onal links. Root lookup never uses free-text UUIDs.\n   IF identities IS NULL AND name'
        "<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native_pilot_observations','r"
        "elease_packages','release_package_currents','release_decisions','release_policy_facts'"
        ",'release_policy_currents','external_handoff_authorizations','external_delivery_intent"
        "s','external_receipts','external_handoff_currents','release_exception_decisions','rele"
        "ase_exception_currents','work_commitment_reviews','work_commitment_review_currents','w"
        "ork_task_versions','work_task_currents','work_commitment_versions','work_commitment_cu"
        "rrents','project_status_updates','external_wait_versions','external_wait_currents','pr"
        "oject_risk_followups','project_risk_followup_currents','manufacturing_baseline_publica"
        "tions','manufacturing_publication_currents','manufacturing_publication_documents','pro"
        "posals','proposal_items','proposal_item_versions','proposal_revisions','proposal_sourc"
        "es','proposal_submissions','proposal_decisions','project_open_items','category_knowled"
        "ge_entries','category_knowledge_current','product_target_segments','parameter_versions"
        "','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','knowled"
        "ge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessm"
        "ents','knowledge_rule_versions','knowledge_rule_currents','field_feedback_versions','f"
        "ield_feedback_currents','field_response_records']) THEN\n    links=links || public.ker"
        'nel_lifecycle_links(name,payload);\n   END IF;\n   RETURN NEXT;\n  END LOOP;\n END LOO'
        'P;\nEND;\n$function$\n'
    ),
}

NATIVE_FUNCTIONS = {
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name'
        ' text, payload jsonb)\n RETURNS uuid[]\n LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n '
        "SET search_path TO 'pg_catalog', 'public', 'pg_temp'\nAS $function$\nDECLARE links uui"
        "d[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n target_k"
        "ind text; referenced_target uuid; referenced_version integer;\nBEGIN\n IF table_name='"
        "agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n -"
        '- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n -- cont'
        'ent dictionaries are not relational rows, even if an extra key happens\n -- to be name'
        "d source_id or item_id.\n keys=CASE table_name\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n  WHEN 'defin"
        "ition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n   '"
        "source_proposal_id','source_submission_id']\n  WHEN 'definition_sources' THEN ARRAY['a"
        "rtifact_id']\n  WHEN 'definition_specs' THEN ARRAY[]::text[]\n  WHEN 'proposals' THEN "
        "ARRAY['baseline_definition_id','current_submission_id']\n  WHEN 'proposal_items' THEN "
        "ARRAY[]::text[]\n  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n  WHEN 'proposa"
        "l_revisions' THEN ARRAY['proposal_id']\n  WHEN 'proposal_sources' THEN ARRAY['source_i"
        "d']\n  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n  WHEN 'proposal_decisions' T"
        "HEN ARRAY['submission_id']\n  WHEN 'project_open_items' THEN ARRAY['source_question_id"
        "','source_spec_item_id','g0_decision_id']\n  WHEN 'category_knowledge_current' THEN AR"
        "RAY['current_entry_id']\n  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','so"
        "urce_proposal_id']\n  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n  WHEN 'claim_w"
        "ithdrawals' THEN ARRAY['claim_id']\n  WHEN 'manufacturing_baseline_publications' THEN "
        "ARRAY['baseline_id','process_id','previous_id']\n  WHEN 'manufacturing_publication_cur"
        "rents' THEN ARRAY['version_id']\n  WHEN 'manufacturing_publication_documents' THEN ARR"
        "AY['document_id','process_id']\n  WHEN 'native_pilot_runs' THEN ARRAY['build_id','lot_"
        "id','actual_configuration_id','engineering_configuration_id','process_id','publication"
        "_id']\n  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
        "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n "
        " WHEN 'release_packages' THEN ARRAY['previous_id']\n  WHEN 'release_package_currents' "
        "THEN ARRAY['version_id']\n  WHEN 'release_decisions' THEN ARRAY['package_id']\n  WHEN "
        "'release_policy_facts' THEN ARRAY['previous_id']\n  WHEN 'release_policy_currents' THE"
        "N ARRAY['fact_id']\n  WHEN 'external_handoff_authorizations' THEN ARRAY['package_id','"
        "engineering_decision_id','manufacturing_decision_id']\n  WHEN 'external_delivery_inten"
        "ts' THEN ARRAY['handoff_id']\n  WHEN 'external_receipts' THEN ARRAY['handoff_id','inte"
        "nt_id','previous_receipt_id','reconciles_id']\n  WHEN 'external_handoff_currents' THEN"
        " ARRAY['handoff_id','intent_id','latest_receipt_id']\n  WHEN 'release_exception_decisi"
        "ons' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n  WHEN 'release_ex"
        "ception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n  WHE"
        "N 'work_commitment_reviews' THEN ARRAY['commitment_id','task_version_id','submission_i"
        "d','previous_id']\n  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n  WHEN 'external_wait_curre"
        "nts' THEN ARRAY['version_id']\n  WHEN 'project_risk_followups' THEN ARRAY['previous_id"
        "','risk_id','g0_decision_id']\n  WHEN 'project_risk_followup_currents' THEN ARRAY['ver"
        "sion_id']\n  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n  WHEN 'work_task_cu"
        "rrents' THEN ARRAY['version_id']\n  WHEN 'work_commitment_versions' THEN ARRAY['replac"
        "es_id']\n  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n  WHEN 'project_s"
        "tatus_updates' THEN ARRAY[]::text[]\n  ELSE ARRAY[]::text[] END;\n FOREACH key IN ARRA"
        'Y keys LOOP\n  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>k'
        "ey)::uuid); END IF;\n END LOOP;\n -- Publication's exact saved read set is a validated"
        ' Artifact relationship.\n -- Do not scan its declaration, body, reason or arbitrary JS'
        "ON UUID values.\n IF table_name IN ('manufacturing_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','release_packages','release_decisions','release_po"
        "licy_facts','external_handoff_authorizations','external_receipts','release_exception_d"
        "ecisions') THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload"
        "->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN"
        "\n    links=array_append(links,(item->>'artifact_id')::uuid);\n   END IF;\n  END LOOP;"
        "\n END IF;\n IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{material_snap"
        "shot,statistics,samples}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_"
        "append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FR"
        "OM jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]'"
        ")) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uu"
        "id); END IF;\n  END LOOP;\n  item=payload#>'{material_snapshot,statistics,resource,fac"
        "t}';\n  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid);"
        " END IF;\n END IF;\n IF table_name='release_packages' THEN\n  -- FixedObject.ref is a "
        'closed, server-resolved version reference, not arbitrary body UUID text.\n  FOR item I'
        "N SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOO"
        "P\n   container=item->'ref';\n   IF container->>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','manufacturing_publication','test_run','pilot_r"
        "un','issue','change','exception','artifact','work_instruction','control_plan','build_l"
        "ot','line'])\n    AND container->>'id' IS NOT NULL THEN links=array_append(links,(cont"
        "ainer->>'id')::uuid); END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('external_han"
        "doff_authorizations','external_delivery_intents') THEN\n  -- Only closed, owner-verifi"
        'ed mapping and manifest references are source edges.\n  container=CASE WHEN table_name'
        "='external_handoff_authorizations' THEN payload#>'{body,declaration}' ELSE payload->'b"
        "ody' END;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'m"
        "appings','[]')) LOOP\n   IF item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_c"
        "onfiguration','process_revision','part','bom_revision','artifact','work_instruction','"
        "control_plan'])\n    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,"
        "(item->'ref'->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jso"
        "nb_array_elements(coalesce(container->'manifest','[]')) LOOP\n   IF item->'artifact'->"
        ">'id' IS NOT NULL THEN links=array_append(links,(item->'artifact'->>'id')::uuid); END "
        "IF;\n  END LOOP;\n END IF;\n IF table_name='release_policy_facts' THEN\n  -- These are"
        ' Closed DTO configuration references fixed by the policy owner.\n  FOREACH key IN ARRA'
        "Y ARRAY['definition','engineering_configuration','manufacturing_configuration'] LOOP\n"
        "   container=payload#>ARRAY['material','subject_config',key];\n   IF container->>'id' "
        "IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n  END LO"
        'OP;\n END IF;\n -- These stored fields are validated Reference containers. Do not feed'
        ' the\n -- whole row or arbitrary content into the canonical Reference parser.\n IF tab'
        "le_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n  'cat"
        "egory_knowledge_entries','definition_specs']) THEN\n  FOREACH key IN ARRAY ARRAY['sour"
        "ce_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n   links=lin"
        'ks || public.m3_lifecycle_typed_links(t,c,payload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and category_service._references: only\n -- commercial_t'
        "arget, voice, and competitor have nested source contracts.\n IF table_name='proposal_i"
        "tem_versions' AND payload->>'kind'='commercial_target' THEN\n  FOREACH key IN ARRAY AR"
        "RAY['target_price','cost','volume'] LOOP\n   links=links || public.m3_lifecycle_typed_"
        "links(t,c,payload->'content'->key->'source');\n  END LOOP;\n ELSIF table_name='categor"
        "y_knowledge_entries' AND payload->>'kind'='voice' THEN\n  links=links || public.m3_lif"
        "ecycle_typed_links(t,c,payload->'content'->'representative_refs');\n ELSIF table_name="
        "'category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n  FOREACH key IN "
        "ARRAY ARRAY['metrics','features','prices'] LOOP\n   FOR item IN SELECT value FROM json"
        "b_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n    links=links || publ"
        "ic.m3_lifecycle_typed_links(t,c,item->'source_ref');\n   END LOOP;\n  END LOOP;\n END "
        "IF;\n IF table_name='proposal_submissions' THEN\n  container=payload->'frozen_document"
        "';\n  FOREACH key IN ARRAY ARRAY['source_refs','direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links || public.m3_lifecycle_typed_links(t,c,contai"
        'ner->key);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce'
        "(container->'items','[]')) LOOP\n   links=links || public.m3_lifecycle_source_links(t,"
        "c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink provenance here.\n   links=links || public.m3'
        "_lifecycle_typed_links(t,c,item->'evidence_links');\n  END LOOP;\n ELSIF table_name='p"
        "romotion_proofs' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p"
        "ayload->'source_item_refs','[]')) LOOP\n   IF item->>'item_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'item_id')::uuid); END IF;\n  END LOOP;\n END IF;\n -- Exac"
        't persisted EvidenceLink targets supplement these immutable versions.\n -- Reverted li'
        'nks and withdrawn Claims still retain the original historical\n -- dependency; lifecyc'
        "le cleanup must not erase their audit source.\n IF table_name='proposal_item_versions'"
        " AND payload->>'item_id' IS NOT NULL THEN\n  target_kind='proposal_item'; referenced_t"
        "arget=(payload->>'item_id')::uuid;\n  referenced_version=(payload->>'version')::intege"
        "r;\n ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN"
        "\n  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n  refere"
        "nced_version=(payload->>'version')::integer;\n ELSIF table_name='definition_specs' AND"
        " payload->>'id' IS NOT NULL THEN\n  target_kind='definition_spec'; referenced_target=("
        "payload->>'id')::uuid;\n  SELECT revision INTO referenced_version FROM public.definiti"
        "on_revisions\n   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id'"
        ')::uuid;\n END IF;\n IF referenced_target IS NOT NULL AND referenced_version IS NOT NU'
        "LL THEN\n  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.ev"
        'idence_links link\n   WHERE link.tenant_id=t AND link.category_id=c AND link.target_ty'
        'pe=target_kind\n    AND link.target_id=referenced_target AND link.target_version=refer'
        'enced_version;\n  links=links || extra;\n END IF;\n -- Child source rows point to thei'
        "r parent, whereas dependency traversal needs\n -- the parent's fixed source children a"
        "s well. Keep the actual relational edge.\n IF table_name='definition_revisions' THEN\n"
        "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n   SELECT id FROM public.defi"
        "nition_sources WHERE tenant_id=t AND category_id=c\n    AND definition_id=(payload->>'"
        "id')::uuid\n   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND "
        "category_id=c\n    AND definition_id=(payload->>'id')::uuid\n  ) children;\n  links=li"
        "nks || extra;\n ELSIF table_name='proposals' THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO extra FROM public.proposal_item_versions\n   WHERE tenant_id=t AND category_id"
        "=c AND proposal_id=(payload->>'id')::uuid;\n  links=links || extra;\n ELSIF table_name"
        "='proposal_items' THEN\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.p"
        "roposal_item_versions\n   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'"
        "id')::uuid;\n  links=links || extra;\n ELSIF table_name='product_target_segments' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entr"
        "ies\n   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage"
        "_id')::uuid\n    AND version=(payload->>'segment_version')::integer;\n  links=links ||"
        " extra;\n ELSIF table_name='parameter_current' THEN\n  SELECT coalesce(array_agg(id),'"
        "{}') INTO extra FROM public.parameter_versions\n   WHERE tenant_id=t AND category_id=c"
        " AND parameter_id=(payload->>'parameter_id')::uuid\n    AND version=(payload->>'curren"
        "t_version')::integer;\n  links=links || extra;\n END IF;\n\n IF table_name IN ('work_t"
        "ask_versions','work_commitment_versions','project_status_updates') THEN\n  FOR item IN"
        " SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF i"
        "tem->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::"
        "uuid); END IF;\n  END LOOP;\n  IF table_name='work_task_versions' AND payload#>>'{body"
        ",plan_task,id}' IS NOT NULL THEN\n   links=array_append(links,(payload#>>'{body,plan_t"
        "ask,id}')::uuid);\n  END IF;\n  IF table_name='work_commitment_versions' THEN\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n    WHERE t"
        "enant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND revision=(pay"
        "load->>'task_revision')::integer;\n   links=links||extra;\n  ELSIF table_name='project"
        "_status_updates' THEN\n   FOR item IN SELECT value FROM jsonb_array_elements(coalesce("
        "payload->'task_refs','[]')) LOOP\n    SELECT coalesce(array_agg(id),'{}') INTO extra F"
        'ROM public.work_task_versions\n     WHERE tenant_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'revision')::integer;\n    links=links||extra;"
        "\n   END LOOP;\n  END IF;\n END IF;\n\n IF table_name='work_commitment_reviews' THEN\n"
        "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) "
        "LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'ar"
        "tifact_id')::uuid); END IF;\n  END LOOP;\n END IF;\n\n IF table_name='external_wait_ve"
        "rsions' THEN\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'"
        "{source_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_"
        "append(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOREACH key IN ARRAY ARRAY["
        "'milestone','build','calendar'] LOOP\n   container=payload#>ARRAY['body',key];\n   IF "
        "container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); "
        "END IF;\n  END LOOP;\n  container=payload#>'{body,replaces}';\n  IF container->>'id' I"
        "S NOT NULL THEN\n   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.externa"
        "l_wait_versions\n    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id'"
        ")::uuid AND revision=(container->>'revision')::integer;\n   links=links||extra;\n  END"
        " IF;\n END IF;\n IF table_name='project_risk_followups' THEN\n  FOR item IN SELECT val"
        "ue FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP"
        "\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); EN"
        "D IF;\n  END LOOP;\n END IF;\n\n IF table_name IN ('knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versi"
        "ons','knowledge_rule_currents') THEN\n  FOREACH key IN ARRAY ARRAY['previous_id','vers"
        "ion_id','candidate_version_id','assessment_id','publication_id'] LOOP\n   IF payload->"
        '>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n  END '
        "LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append("
        "links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM json"
        "b_array_elements(coalesce(payload->'reads','[]')) LOOP\n   IF item->>'artifact_id' IS "
        "NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END L"
        "OOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   IF item->>'receipt_id' IS NOT NULL THEN links="
        "array_append(links,(item->>'receipt_id')::uuid); END IF;\n   IF item->>'row_id' IS NOT"
        " NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n  END LOOP;\n  "
        "FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,pr"
        "ofessional,fact_refs}','[]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_app"
        "end(links,(item->>'id')::uuid); END IF;\n  END LOOP;\n  IF payload#>>'{source_basis,ta"
        "rget,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'{source_basis,target,i"
        "d}')::uuid); END IF;\n END IF;\n\n IF table_name IN ('field_feedback_versions','field_"
        "feedback_currents','field_response_records') THEN\n  FOREACH key IN ARRAY ARRAY['previ"
        "ous_id','version_id','feedback_version_id'] LOOP\n   IF payload->>key IS NOT NULL THEN"
        ' links=array_append(links,(payload->>key)::uuid); END IF;\n  END LOOP;\n  FOR item IN '
        "SELECT value FROM jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::"
        "uuid); END IF;\n  END LOOP;\n  FOREACH key IN ARRAY ARRAY['engineering_configuration',"
        "'manufacturing_configuration','batch'] LOOP\n   IF payload#>>ARRAY['body','location',k"
        "ey,'id'] IS NOT NULL THEN links=array_append(links,(payload#>>ARRAY['body','location',"
        "key,'id'])::uuid); END IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n   IF item->>'"
        "receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); EN"
        "D IF;\n   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id"
        "')::uuid); END IF;\n  END LOOP;\n END IF;\n IF table_name IN ('change_request_versions"
        "','change_graph_captures') THEN\n  FOR container IN SELECT value FROM jsonb_each(coale"
        "sce(payload#>'{source_basis,owners}','{}')) LOOP\n   IF container->>'feedback_version_"
        "id' IS NOT NULL THEN links=array_append(links,(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Closed native Field plan and occurrence refe'
        "rences, never arbitrary UUID prose.\n IF table_name='controlled_change_selection_facts"
        "' AND payload->>'basis_kind'='field_intent' THEN\n  IF payload->>'feedback_version_id'"
        " IS NOT NULL THEN\n   links=array_append(links,(payload->>'feedback_version_id')::uuid"
        ");\n  END IF;\n END IF;\n IF table_name='change_implementation_captures'\n  AND payloa"
        "d#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrenc"
        "e-v1' THEN\n  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] LOOP\n "
        "  IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n    links=array_appe"
        "nd(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);\n   END IF;\n  END LOOP;"
        "\n END IF;\n\n IF table_name='change_completion_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','order_record_id','shared_proof_id'] LOOP\n   I"
        'F payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END '
        'IF;\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payloa'
        "d->'required_source_read_set','[]')) LOOP\n   IF item->>'artifact_id' IS NOT NULL THEN"
        " links=array_append(links,(item->>'artifact_id')::uuid); END IF;\n  END LOOP;\n  IF pa"
        "yload#>>'{native_input,lot,id}' IS NOT NULL THEN links=array_append(links,(payload#>>'"
        "{native_input,lot,id}')::uuid); END IF;\n  FOR item IN SELECT value FROM jsonb_array_e"
        "lements(coalesce(payload#>'{native_input,sample_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LOOP;\n  FOR item IN SELECT value FROM jsonb_ar"
        "ray_elements(coalesce(payload#>'{native_input,mappings}','[]')) LOOP\n   SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM verification_run_versions\n    WHERE tenant_id="
        "t AND category_id=c AND run_id=(item#>>'{run,id}')::uuid AND revision=(item#>>'{run,re"
        "vision}')::integer;\n   links=links||extra; links=array_append(links,(item->>'sample_i"
        "d')::uuid);\n  END LOOP;\n END IF;\n\n -- Closed native owner DTOs: retain exact outpu"
        "ts and native execution/report rows.\n IF table_name='change_completion_records' THEN"
        "\n  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{fact_snapsh"
        "ot,output_refs}','[]')) LOOP\n   IF item->>'kind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM verification_run_versions\n     WHERE tenant_id=t"
        " AND category_id=c AND run_id=(item->>'id')::uuid AND revision=(item->>'revision')::in"
        "teger;\n    links=links||extra;\n   ELSIF item->>'kind'=ANY(ARRAY['engineering_configu"
        "ration','manufacturing_configuration','build','sample']) THEN\n    links=array_append("
        "links,(item->>'id')::uuid);\n   END IF;\n  END LOOP;\n  IF payload#>>'{owner_basis,sch"
        "ema_version}'='pdos-native-build-adoption-read-v1' THEN\n   FOREACH key IN ARRAY ARRAY"
        "['previous_build','successor_build','actual_configuration','lot','start'] LOOP\n    IF"
        " payload#>>ARRAY['owner_basis',key,'id'] IS NOT NULL THEN\n     links=array_append(lin"
        "ks,(payload#>>ARRAY['owner_basis',key,'id'])::uuid);\n    END IF;\n   END LOOP;\n  ELS"
        "IF payload#>>'{owner_basis,schema_version}'='pdos-native-change-run-verification-v1' T"
        "HEN\n   FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{owner_basis,"
        "runs}','{}')) LOOP\n    FOREACH key IN ARRAY ARRAY['run_version_id','request_version_i"
        "d','projection_id'] LOOP\n     IF container->>key IS NOT NULL THEN links=array_append("
        'links,(container->>key)::uuid); END IF;\n    END LOOP;\n   END LOOP;\n  END IF;\n END '
        'IF;\n\n -- F: only server-verified fixed answer proofs establish these dependency edge'
        's.\n -- Native deferred atoms bind these exact arrays to real source ledgers.\n IF tab'
        "le_name IN ('category_knowledge_entries','knowledge_candidate_versions','knowledge_rul"
        "e_versions','knowledge_answer_reviews','knowledge_gap_submissions') THEN\n  container="
        "CASE table_name WHEN 'category_knowledge_entries' THEN payload->'answer_sources'\n   W"
        "HEN 'knowledge_candidate_versions' THEN payload#>'{source_basis,answer_sources}'\n   W"
        "HEN 'knowledge_rule_versions' THEN payload#>'{source_basis,answer_sources}'\n   ELSE p"
        "ayload->'source_proof' END;\n  links=links||public.assistant_source_lifecycle_links(t,"
        "c,coalesce(container,'[]'::jsonb));\n END IF;\n RETURN links;\nEND;\n$function$\n"
    ),
    'm3_lifecycle_nodes(uuid,uuid,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.m3_lifecycle_nodes(t uuid, c uuid, identities uuid[]'
        ' DEFAULT NULL::uuid[])\n RETURNS TABLE(table_name text, node_id uuid, links uuid[])\n '
        "LANGUAGE plpgsql\n STABLE SECURITY DEFINER\n SET search_path TO 'pg_catalog', 'public'"
        ", 'pg_temp'\nAS $function$\nDECLARE name text; payload jsonb; controls uuid[];\nBEGIN"
        "\n IF identities IS NULL THEN\n  SELECT coalesce(array_agg(id),'{}') INTO controls FRO"
        "M public.action_receipts\n   WHERE tenant_id=t AND category_id=c AND operation LIKE 'e"
        "vidence.lifecycle.%';\n ELSE controls='{}'; END IF;\n FOREACH name IN ARRAY CASE WHEN "
        "identities IS NULL THEN ARRAY['agent_runs','action_receipts','actual_configurations','"
        "artifact_versions','audit_entries','bom_lines','bom_revisions','build_authorization_de"
        "cisions','build_current_authorizations','build_current_execution_assessments','build_e"
        "xecution_assessments','build_lots','build_operational_current','build_operational_fact"
        "s','build_readiness','build_starts','builds','capa_current_observations','capa_current"
        "_verification_rules','capa_named_verification_reviews','capa_observation_facts','capa_"
        "remediation_links','capa_verification_evidence','capa_verification_rule_facts','change"
        "_approval_records','change_dependency_clocks','change_graph_captures','change_implemen"
        "tation_captures','change_implementation_records','change_order_records','change_reques"
        "t_currents','change_request_versions','claim_consumptions','claims','controlled_change"
        "_coverage_currents','controlled_change_coverage_facts','controlled_change_policy_curre"
        "nts','controlled_change_policy_facts','controlled_change_selection_currents','controll"
        "ed_change_selection_facts','cost_current_inputs','cost_estimates','cost_input_snapshot"
        "s','cost_source_captures','definition_revisions','definition_sources','definition_spec"
        "s','engineering_configurations','manufacturing_baseline_document_links','manufacturing"
        "_preparation_currents','manufacturing_preparation_versions','measurement_import_captur"
        "es','operational_material_holds','operational_resource_occupancies','original_scan_req"
        "uests','original_scan_results','original_security','outbox_events','parts','plan_propo"
        "sals','plan_revisions','process_revisions','product_variants','professional_authority_"
        "current','professional_authority_facts','project_product_links','project_tasks','proje"
        "ct_work_packages','projects','quality_current_issues','quality_current_policies','qual"
        "ity_event_failure_links','quality_failure_maps','quality_issue_versions','quality_poli"
        "cy_facts','request_keys','runs','sample_allocations','sample_current_readiness','sampl"
        "e_readiness_facts','sample_run_usages','sample_units','sample_usage_sentinels','supply"
        "_current_snapshots','supply_kit_projections','supply_snapshots','supply_source_capture"
        "s','task_dependencies','test_measurements','test_resource_current','test_resource_fact"
        "s','test_resource_reservations','test_result_actions','test_result_projections','uploa"
        "ded_originals','variant_revisions','verification_actual_method_applicabilities','verif"
        "ication_actual_method_batches','verification_current_actual_methods','verification_cur"
        "rent_formal_requests','verification_current_preparations','verification_current_runs',"
        "'verification_formal_requests','verification_handoff_facts','verification_launch_facts"
        "','verification_method_applicabilities','verification_preparations','verification_run_"
        "identities','verification_run_versions','verification_window_proposals','work_requests"
        "','proposals','proposal_items','proposal_item_versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','proposal_decisions','project_open_items','category_k"
        "nowledge_entries','category_knowledge_current','product_target_segments','parameter_ve"
        "rsions','parameter_current','promotion_proofs','evidence_links','claim_withdrawals','m"
        "anufacturing_baseline_publications','manufacturing_publication_currents','manufacturin"
        "g_publication_documents','native_pilot_runs','native_pilot_currents','native_pilot_obs"
        "ervations','release_packages','release_package_currents','release_decisions','release_"
        "policy_facts','release_policy_currents','external_handoff_authorizations','external_de"
        "livery_intents','external_receipts','external_handoff_currents','release_exception_dec"
        "isions','release_exception_currents','work_commitment_reviews','work_commitment_review"
        "_currents','work_task_versions','work_task_currents','work_commitment_versions','work_"
        "commitment_currents','project_status_updates','external_wait_versions','external_wait_"
        "currents','project_risk_followups','project_risk_followup_currents','knowledge_candida"
        "te_versions','knowledge_candidate_currents','knowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_currents','field_feedback_versions','field_feedb"
        "ack_currents','field_response_records','knowledge_answer_reviews','knowledge_gap_submi"
        "ssions'] ELSE ARRAY[\n  'artifact_versions','claims','definition_revisions','definitio"
        "n_sources','definition_specs',\n  'proposals','proposal_items','proposal_item_versions"
        "','proposal_submissions','proposal_decisions',\n  'category_knowledge_entries','catego"
        "ry_knowledge_current','parameter_versions','parameter_current',\n  'evidence_links','p"
        "romotion_proofs','native_pilot_runs','native_pilot_currents','native_pilot_observation"
        "s','release_packages','release_package_currents','release_decisions','release_policy_f"
        "acts','release_policy_currents','external_handoff_authorizations','external_delivery_i"
        "ntents','external_receipts','external_handoff_currents','release_exception_decisions',"
        "'release_exception_currents','work_commitment_reviews','work_commitment_review_current"
        "s','work_task_versions','work_task_currents','work_commitment_versions','work_commitme"
        "nt_currents','project_status_updates','external_wait_versions','external_wait_currents"
        "','project_risk_followups','project_risk_followup_currents','knowledge_candidate_versi"
        "ons','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_r"
        "ule_versions','knowledge_rule_currents','field_feedback_versions','field_feedback_curr"
        "ents','field_response_records','knowledge_answer_reviews','knowledge_gap_submissions']"
        " END LOOP\n  FOR payload IN EXECUTE CASE WHEN name=ANY(ARRAY['audit_entries','outbox_e"
        "vents','request_keys'])\n   THEN format('SELECT to_jsonb(x) FROM public.%I x JOIN publ"
        'ic.action_receipts r ON r.id=x.receipt_id AND r.tenant_id=x.tenant_id WHERE x.tenant_i'
        "d=$1 AND r.category_id=$2',name)\n   ELSE format('SELECT to_jsonb(x) FROM public.%I x "
        "WHERE tenant_id=$1 AND category_id=$2 AND ($3 IS NULL OR %I=ANY($3))',name,\n    CASE "
        "name WHEN 'category_knowledge_current' THEN 'lineage_id'\n     WHEN 'parameter_current"
        "' THEN 'parameter_id' ELSE 'id' END)\n   END USING t,c,identities LOOP\n   IF (payload"
        "->>'receipt_id')::uuid=ANY(controls) OR\n    (name='action_receipts' AND payload->>'op"
        "eration' LIKE 'evidence.lifecycle.%') THEN CONTINUE; END IF;\n   table_name=name;\n   "
        "node_id=CASE name WHEN 'category_knowledge_current' THEN (payload->>'lineage_id')::uui"
        "d\n    WHEN 'parameter_current' THEN (payload->>'parameter_id')::uuid ELSE (payload->>"
        "'id')::uuid END;\n   IF identities IS NULL THEN links=public.m3_lifecycle_row_links(t,"
        'c,name,payload);\n   ELSE links=public.m3_lifecycle_source_links(t,c,name,payload); EN'
        "D IF;\n   -- Preserve predecessor's conservative legacy graph; M3-only nodes use\n   -"
        '- strictly typed/relational links. Root lookup never uses free-text UUIDs.\n   IF iden'
        "tities IS NULL AND name<>ALL(ARRAY['native_pilot_runs','native_pilot_currents','native"
        "_pilot_observations','release_packages','release_package_currents','release_decisions'"
        ",'release_policy_facts','release_policy_currents','external_handoff_authorizations','e"
        "xternal_delivery_intents','external_receipts','external_handoff_currents','release_exc"
        "eption_decisions','release_exception_currents','work_commitment_reviews','work_commitm"
        "ent_review_currents','work_task_versions','work_task_currents','work_commitment_versio"
        "ns','work_commitment_currents','project_status_updates','external_wait_versions','exte"
        "rnal_wait_currents','project_risk_followups','project_risk_followup_currents','manufac"
        "turing_baseline_publications','manufacturing_publication_currents','manufacturing_publ"
        "ication_documents','proposals','proposal_items','proposal_item_versions','proposal_rev"
        "isions','proposal_sources','proposal_submissions','proposal_decisions','project_open_i"
        "tems','category_knowledge_entries','category_knowledge_current','product_target_segmen"
        "ts','parameter_versions','parameter_current','promotion_proofs','evidence_links','clai"
        "m_withdrawals','knowledge_candidate_versions','knowledge_candidate_currents','knowledg"
        "e_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents','fiel"
        "d_feedback_versions','field_feedback_currents','field_response_records','knowledge_ans"
        "wer_reviews','knowledge_gap_submissions']) THEN\n    links=links || public.kernel_life"
        'cycle_links(name,payload);\n   END IF;\n   RETURN NEXT;\n  END LOOP;\n END LOOP;\nEND;'
        '\n$function$\n'
    ),
}

