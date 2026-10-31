"""Unnumbered E summary delivery SQL on exact head851 predecessors; root assigns revision."""

PREVIOUS_FUNCTIONS = {
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_source_links(t uuid, c uuid, tabl'
        'e_name text, payload jsonb)\n RETURNS uui'
        'd[]\n LANGUAGE plpgsql\n STABLE SECURITY D'
        "EFINER\n SET search_path TO 'pg_catalog',"
        " 'public', 'pg_temp'\nAS $function$\nDECLA"
        "RE links uuid[]='{}'; extra uuid[]; key "
        'text; keys text[]; item jsonb; container'
        ' jsonb;\n target_kind text; referenced_ta'
        'rget uuid; referenced_version integer;\nB'
        "EGIN\n IF table_name='agent_runs' THEN RE"
        'TURN public.kernel_lifecycle_links(table'
        '_name,payload); END IF;\n -- Only actual '
        'top-level relation columns establish raw'
        ' UUID edges. Arbitrary\n -- content dicti'
        'onaries are not relational rows, even if'
        ' an extra key happens\n -- to be named so'
        'urce_id or item_id.\n keys=CASE table_nam'
        "e\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRA"
        "Y['artifact_id','snapshot_id']\n  WHEN 'd"
        "efinition_revisions' THEN ARRAY['derived"
        "_from_definition_id','parent_definition_"
        "id',\n   'source_proposal_id','source_sub"
        "mission_id']\n  WHEN 'definition_sources'"
        " THEN ARRAY['artifact_id']\n  WHEN 'defin"
        "ition_specs' THEN ARRAY[]::text[]\n  WHEN"
        " 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN"
        " 'proposal_items' THEN ARRAY[]::text[]\n "
        " WHEN 'proposal_item_versions' THEN ARRA"
        "Y[]::text[]\n  WHEN 'proposal_revisions' "
        "THEN ARRAY['proposal_id']\n  WHEN 'propos"
        "al_sources' THEN ARRAY['source_id']\n  WH"
        "EN 'proposal_submissions' THEN ARRAY[]::"
        "text[]\n  WHEN 'proposal_decisions' THEN "
        "ARRAY['submission_id']\n  WHEN 'project_o"
        "pen_items' THEN ARRAY['source_question_i"
        "d','source_spec_item_id','g0_decision_id"
        "']\n  WHEN 'category_knowledge_current' T"
        "HEN ARRAY['current_entry_id']\n  WHEN 'pr"
        "omotion_proofs' THEN ARRAY['knowledge_en"
        "try_id','source_proposal_id']\n  WHEN 'ev"
        "idence_links' THEN ARRAY['evidence_id']\n"
        "  WHEN 'claim_withdrawals' THEN ARRAY['c"
        "laim_id']\n  WHEN 'manufacturing_baseline"
        "_publications' THEN ARRAY['baseline_id',"
        "'process_id','previous_id']\n  WHEN 'manu"
        "facturing_publication_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'manufacturing_p"
        "ublication_documents' THEN ARRAY['docume"
        "nt_id','process_id']\n  WHEN 'native_pilo"
        "t_runs' THEN ARRAY['build_id','lot_id','"
        "actual_configuration_id','engineering_co"
        "nfiguration_id','process_id','publicatio"
        "n_id']\n  WHEN 'native_pilot_currents' TH"
        "EN ARRAY['pilot_id','latest_observation_"
        "id']\n  WHEN 'native_pilot_observations' "
        "THEN ARRAY['pilot_id','previous_observat"
        "ion_id']\n  WHEN 'release_packages' THEN "
        "ARRAY['previous_id']\n  WHEN 'release_pac"
        "kage_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'release_decisions' THEN ARRAY['p"
        "ackage_id']\n  WHEN 'release_policy_facts"
        "' THEN ARRAY['previous_id']\n  WHEN 'rele"
        "ase_policy_currents' THEN ARRAY['fact_id"
        "']\n  WHEN 'external_handoff_authorizatio"
        "ns' THEN ARRAY['package_id','engineering"
        "_decision_id','manufacturing_decision_id"
        "']\n  WHEN 'external_delivery_intents' TH"
        "EN ARRAY['handoff_id']\n  WHEN 'external_"
        "receipts' THEN ARRAY['handoff_id','inten"
        "t_id','previous_receipt_id','reconciles_"
        "id']\n  WHEN 'external_handoff_currents' "
        "THEN ARRAY['handoff_id','intent_id','lat"
        "est_receipt_id']\n  WHEN 'release_excepti"
        "on_decisions' THEN ARRAY['basis_package_"
        "id','policy_fact_id','previous_id']\n  WH"
        "EN 'release_exception_currents' THEN ARR"
        "AY['basis_package_id','policy_fact_id','"
        "decision_id']\n  WHEN 'work_commitment_re"
        "views' THEN ARRAY['commitment_id','task_"
        "version_id','submission_id','previous_id"
        "']\n  WHEN 'work_commitment_review_curren"
        "ts' THEN ARRAY['version_id']\n  WHEN 'ext"
        "ernal_wait_versions' THEN ARRAY['previou"
        "s_id']\n  WHEN 'external_wait_currents' T"
        "HEN ARRAY['version_id']\n  WHEN 'project_"
        "risk_followups' THEN ARRAY['previous_id'"
        ",'risk_id','g0_decision_id']\n  WHEN 'pro"
        "ject_risk_followup_currents' THEN ARRAY["
        "'version_id']\n  WHEN 'work_task_versions"
        "' THEN ARRAY['previous_id']\n  WHEN 'work"
        "_task_currents' THEN ARRAY['version_id']"
        "\n  WHEN 'work_commitment_versions' THEN "
        "ARRAY['replaces_id']\n  WHEN 'work_commit"
        "ment_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'project_status_updates' THEN ARR"
        'AY[]::text[]\n  ELSE ARRAY[]::text[] END;'
        '\n FOREACH key IN ARRAY keys LOOP\n  IF pa'
        'yload->>key IS NOT NULL THEN links=array'
        '_append(links,(payload->>key)::uuid); EN'
        "D IF;\n END LOOP;\n -- Publication's exact"
        ' saved read set is a validated Artifact '
        'relationship.\n -- Do not scan its declar'
        'ation, body, reason or arbitrary JSON UU'
        "ID values.\n IF table_name IN ('manufactu"
        "ring_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','rel"
        "ease_packages','release_decisions','rele"
        "ase_policy_facts','external_handoff_auth"
        "orizations','external_receipts','release"
        "_exception_decisions') THEN\n  FOR item I"
        'N SELECT value FROM jsonb_array_elements'
        "(coalesce(payload->'required_source_read"
        "_set','[]')) LOOP\n   IF item->>'artifact"
        "_id' IS NOT NULL THEN\n    links=array_ap"
        "pend(links,(item->>'artifact_id')::uuid)"
        ';\n   END IF;\n  END LOOP;\n END IF;\n IF ta'
        "ble_name IN ('native_pilot_runs','native"
        "_pilot_observations') THEN\n  FOR item IN"
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{material_snapshot,st"
        "atistics,samples}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOR item IN SELECT value '
        'FROM jsonb_array_elements(coalesce(paylo'
        "ad#>'{material_snapshot,statistics,issue"
        "s}','[]')) LOOP\n   IF item->>'id' IS NOT"
        ' NULL THEN links=array_append(links,(ite'
        "m->>'id')::uuid); END IF;\n  END LOOP;\n  "
        "item=payload#>'{material_snapshot,statis"
        "tics,resource,fact}';\n  IF item->>'id' I"
        'S NOT NULL THEN links=array_append(links'
        ",(item->>'id')::uuid); END IF;\n END IF;\n"
        " IF table_name='release_packages' THEN\n "
        ' -- FixedObject.ref is a closed, server-'
        'resolved version reference, not arbitrar'
        'y body UUID text.\n  FOR item IN SELECT v'
        'alue FROM jsonb_array_elements(coalesce('
        "payload#>'{body,objects}','[]')) LOOP\n  "
        " container=item->'ref';\n   IF container-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "manufacturing_publication','test_run','p"
        "ilot_run','issue','change','exception','"
        "artifact','work_instruction','control_pl"
        "an','build_lot','line'])\n    AND contain"
        "er->>'id' IS NOT NULL THEN links=array_a"
        "ppend(links,(container->>'id')::uuid); E"
        'ND IF;\n  END LOOP;\n END IF;\n IF table_na'
        "me IN ('external_handoff_authorizations'"
        ",'external_delivery_intents') THEN\n  -- "
        'Only closed, owner-verified mapping and '
        'manifest references are source edges.\n  '
        "container=CASE WHEN table_name='external"
        "_handoff_authorizations' THEN payload#>'"
        "{body,declaration}' ELSE payload->'body'"
        ' END;\n  FOR item IN SELECT value FROM js'
        "onb_array_elements(coalesce(container->'"
        "mappings','[]')) LOOP\n   IF item->'ref'-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "part','bom_revision','artifact','work_in"
        "struction','control_plan'])\n    AND item"
        "->'ref'->>'id' IS NOT NULL THEN links=ar"
        "ray_append(links,(item->'ref'->>'id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN '
        'SELECT value FROM jsonb_array_elements(c'
        "oalesce(container->'manifest','[]')) LOO"
        "P\n   IF item->'artifact'->>'id' IS NOT N"
        'ULL THEN links=array_append(links,(item-'
        ">'artifact'->>'id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n IF table_name='release"
        "_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by '
        'the policy owner.\n  FOREACH key IN ARRAY'
        " ARRAY['definition','engineering_configu"
        "ration','manufacturing_configuration'] L"
        "OOP\n   container=payload#>ARRAY['materia"
        "l','subject_config',key];\n   IF containe"
        "r->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(container->>'id')::uuid); EN"
        'D IF;\n  END LOOP;\n END IF;\n -- These sto'
        'red fields are validated Reference conta'
        'iners. Do not feed the\n -- whole row or '
        'arbitrary content into the canonical Ref'
        'erence parser.\n IF table_name=ANY(ARRAY['
        "'proposals','proposal_item_versions','pr"
        "oposal_submissions',\n  'category_knowled"
        "ge_entries','definition_specs']) THEN\n  "
        "FOREACH key IN ARRAY ARRAY['source_refs'"
        ",'direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links "
        '|| public.m3_lifecycle_typed_links(t,c,p'
        'ayload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and catego'
        'ry_service._references: only\n -- commerc'
        'ial_target, voice, and competitor have n'
        "ested source contracts.\n IF table_name='"
        "proposal_item_versions' AND payload->>'k"
        "ind'='commercial_target' THEN\n  FOREACH "
        "key IN ARRAY ARRAY['target_price','cost'"
        ",'volume'] LOOP\n   links=links || public"
        ".m3_lifecycle_typed_links(t,c,payload->'"
        "content'->key->'source');\n  END LOOP;\n E"
        "LSIF table_name='category_knowledge_entr"
        "ies' AND payload->>'kind'='voice' THEN\n "
        ' links=links || public.m3_lifecycle_type'
        "d_links(t,c,payload->'content'->'represe"
        "ntative_refs');\n ELSIF table_name='categ"
        "ory_knowledge_entries' AND payload->>'ki"
        "nd'='competitor' THEN\n  FOREACH key IN A"
        "RRAY ARRAY['metrics','features','prices'"
        '] LOOP\n   FOR item IN SELECT value FROM '
        "jsonb_array_elements(coalesce(payload->'"
        "content'->key,'[]')) LOOP\n    links=link"
        's || public.m3_lifecycle_typed_links(t,c'
        ",item->'source_ref');\n   END LOOP;\n  END"
        " LOOP;\n END IF;\n IF table_name='proposal"
        "_submissions' THEN\n  container=payload->"
        "'frozen_document';\n  FOREACH key IN ARRA"
        "Y ARRAY['source_refs','direct_source_ref"
        "s','context_refs','baseline_claim_refs']"
        ' LOOP\n   links=links || public.m3_lifecy'
        'cle_typed_links(t,c,container->key);\n  E'
        'ND LOOP;\n  FOR item IN SELECT value FROM'
        ' jsonb_array_elements(coalesce(container'
        "->'items','[]')) LOOP\n   links=links || "
        "public.m3_lifecycle_source_links(t,c,'pr"
        "oposal_item_versions',item-ARRAY['item_i"
        "d','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink'
        ' provenance here.\n   links=links || publ'
        "ic.m3_lifecycle_typed_links(t,c,item->'e"
        "vidence_links');\n  END LOOP;\n ELSIF tabl"
        "e_name='promotion_proofs' THEN\n  FOR ite"
        'm IN SELECT value FROM jsonb_array_eleme'
        "nts(coalesce(payload->'source_item_refs'"
        ",'[]')) LOOP\n   IF item->>'item_id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'item_id')::uuid); END IF;\n  END L"
        'OOP;\n END IF;\n -- Exact persisted Eviden'
        'ceLink targets supplement these immutabl'
        'e versions.\n -- Reverted links and withd'
        'rawn Claims still retain the original hi'
        'storical\n -- dependency; lifecycle clean'
        'up must not erase their audit source.\n I'
        "F table_name='proposal_item_versions' AN"
        "D payload->>'item_id' IS NOT NULL THEN\n "
        " target_kind='proposal_item'; referenced"
        "_target=(payload->>'item_id')::uuid;\n  r"
        "eferenced_version=(payload->>'version'):"
        ":integer;\n ELSIF table_name='category_kn"
        "owledge_entries' AND payload->>'id' IS N"
        "OT NULL THEN\n  target_kind='knowledge_en"
        "try'; referenced_target=(payload->>'id')"
        '::uuid;\n  referenced_version=(payload->>'
        "'version')::integer;\n ELSIF table_name='"
        "definition_specs' AND payload->>'id' IS "
        "NOT NULL THEN\n  target_kind='definition_"
        "spec'; referenced_target=(payload->>'id'"
        ')::uuid;\n  SELECT revision INTO referenc'
        'ed_version FROM public.definition_revisi'
        'ons\n   WHERE tenant_id=t AND category_id'
        "=c AND id=(payload->>'definition_id')::u"
        'uid;\n END IF;\n IF referenced_target IS N'
        'OT NULL AND referenced_version IS NOT NU'
        'LL THEN\n  SELECT coalesce(array_agg(link'
        ".evidence_id),'{}') INTO extra FROM publ"
        'ic.evidence_links link\n   WHERE link.ten'
        'ant_id=t AND link.category_id=c AND link'
        '.target_type=target_kind\n    AND link.ta'
        'rget_id=referenced_target AND link.targe'
        't_version=referenced_version;\n  links=li'
        'nks || extra;\n END IF;\n -- Child source '
        'rows point to their parent, whereas depe'
        "ndency traversal needs\n -- the parent's "
        'fixed source children as well. Keep the '
        "actual relational edge.\n IF table_name='"
        "definition_revisions' THEN\n  SELECT coal"
        "esce(array_agg(id),'{}') INTO extra FROM"
        ' (\n   SELECT id FROM public.definition_s'
        'ources WHERE tenant_id=t AND category_id'
        "=c\n    AND definition_id=(payload->>'id'"
        ')::uuid\n   UNION ALL SELECT id FROM publ'
        'ic.definition_specs WHERE tenant_id=t AN'
        'D category_id=c\n    AND definition_id=(p'
        "ayload->>'id')::uuid\n  ) children;\n  lin"
        "ks=links || extra;\n ELSIF table_name='pr"
        "oposals' THEN\n  SELECT coalesce(array_ag"
        "g(id),'{}') INTO extra FROM public.propo"
        'sal_item_versions\n   WHERE tenant_id=t A'
        'ND category_id=c AND proposal_id=(payloa'
        "d->>'id')::uuid;\n  links=links || extra;"
        "\n ELSIF table_name='proposal_items' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM public.proposal_item_vers'
        'ions\n   WHERE tenant_id=t AND category_i'
        "d=c AND item_id=(payload->>'id')::uuid;\n"
        '  links=links || extra;\n ELSIF table_nam'
        "e='product_target_segments' THEN\n  SELEC"
        "T coalesce(array_agg(id),'{}') INTO extr"
        'a FROM public.category_knowledge_entries'
        '\n   WHERE tenant_id=t AND category_id=c '
        "AND lineage_id=(payload->>'segment_linea"
        "ge_id')::uuid\n    AND version=(payload->"
        ">'segment_version')::integer;\n  links=li"
        "nks || extra;\n ELSIF table_name='paramet"
        "er_current' THEN\n  SELECT coalesce(array"
        "_agg(id),'{}') INTO extra FROM public.pa"
        'rameter_versions\n   WHERE tenant_id=t AN'
        'D category_id=c AND parameter_id=(payloa'
        "d->>'parameter_id')::uuid\n    AND versio"
        "n=(payload->>'current_version')::integer"
        ';\n  links=links || extra;\n END IF;\n\n IF '
        "table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_u"
        "pdates') THEN\n  FOR item IN SELECT value"
        ' FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array"
        "_append(links,(item->>'artifact_id')::uu"
        'id); END IF;\n  END LOOP;\n  IF table_name'
        "='work_task_versions' AND payload#>>'{bo"
        "dy,plan_task,id}' IS NOT NULL THEN\n   li"
        "nks=array_append(links,(payload#>>'{body"
        ",plan_task,id}')::uuid);\n  END IF;\n  IF "
        "table_name='work_commitment_versions' TH"
        "EN\n   SELECT coalesce(array_agg(id),'{}'"
        ') INTO extra FROM public.work_task_versi'
        'ons\n    WHERE tenant_id=t AND category_i'
        "d=c AND task_id=(payload->>'task_id')::u"
        "uid AND revision=(payload->>'task_revisi"
        "on')::integer;\n   links=links||extra;\n  "
        "ELSIF table_name='project_status_updates"
        "' THEN\n   FOR item IN SELECT value FROM "
        "jsonb_array_elements(coalesce(payload->'"
        "task_refs','[]')) LOOP\n    SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM p"
        'ublic.work_task_versions\n     WHERE tena'
        'nt_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'"
        "revision')::integer;\n    links=links||ex"
        'tra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' T"
        'HEN\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload->'read"
        "s','[]')) LOOP\n   IF item->>'artifact_id"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(item->>'artifact_id')::uuid); END I"
        'F;\n  END LOOP;\n END IF;\n\n IF table_name='
        "'external_wait_versions' THEN\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{source_basis,arti"
        "facts}','[]')) LOOP\n   IF item->>'id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(item->>'id')::uuid); END IF;\n  END LOOP"
        ";\n  FOREACH key IN ARRAY ARRAY['mileston"
        "e','build','calendar'] LOOP\n   container"
        "=payload#>ARRAY['body',key];\n   IF conta"
        "iner->>'id' IS NOT NULL THEN links=array"
        "_append(links,(container->>'id')::uuid);"
        ' END IF;\n  END LOOP;\n  container=payload'
        "#>'{body,replaces}';\n  IF container->>'i"
        "d' IS NOT NULL THEN\n   SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM publi"
        'c.external_wait_versions\n    WHERE tenan'
        't_id=t AND category_id=c AND wait_id=(co'
        "ntainer->>'id')::uuid AND revision=(cont"
        "ainer->>'revision')::integer;\n   links=l"
        'inks||extra;\n  END IF;\n END IF;\n IF tabl'
        "e_name='project_risk_followups' THEN\n  F"
        'OR item IN SELECT value FROM jsonb_array'
        "_elements(coalesce(payload#>'{source_bas"
        "is,artifacts}','[]')) LOOP\n   IF item->>"
        "'id' IS NOT NULL THEN links=array_append"
        "(links,(item->>'id')::uuid); END IF;\n  E"
        "ND LOOP;\n END IF;\n\n IF table_name IN ('k"
        "nowledge_candidate_versions','knowledge_"
        "candidate_currents','knowledge_applicabi"
        "lity_assessments','knowledge_rule_versio"
        "ns','knowledge_rule_currents') THEN\n  FO"
        "REACH key IN ARRAY ARRAY['previous_id','"
        "version_id','candidate_version_id','asse"
        "ssment_id','publication_id'] LOOP\n   IF "
        'payload->>key IS NOT NULL THEN links=arr'
        'ay_append(links,(payload->>key)::uuid); '
        'END IF;\n  END LOOP;\n  FOR item IN SELECT'
        ' value FROM jsonb_array_elements(coalesc'
        "e(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'i"
        "d')::uuid); END IF;\n  END LOOP;\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload->'reads','[]')) LO"
        "OP\n   IF item->>'artifact_id' IS NOT NUL"
        'L THEN links=array_append(links,(item->>'
        "'artifact_id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{sour"
        "ce_basis,result_receipts}','[]')) LOOP\n "
        "  IF item->>'receipt_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'rece"
        "ipt_id')::uuid); END IF;\n   IF item->>'r"
        "ow_id' IS NOT NULL THEN links=array_appe"
        "nd(links,(item->>'row_id')::uuid); END I"
        'F;\n  END LOOP;\n  FOR item IN SELECT valu'
        'e FROM jsonb_array_elements(coalesce(pay'
        "load#>'{source_basis,professional,fact_r"
        "efs}','[]')) LOOP\n   IF item->>'id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  IF payload#>>'{source_basis,target,id}"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(payload#>>'{source_basis,target,id}"
        "')::uuid); END IF;\n END IF;\n\n IF table_n"
        "ame IN ('field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds') THEN\n  FOREACH key IN ARRAY ARRAY["
        "'previous_id','version_id','feedback_ver"
        "sion_id'] LOOP\n   IF payload->>key IS NO"
        'T NULL THEN links=array_append(links,(pa'
        'yload->>key)::uuid); END IF;\n  END LOOP;'
        '\n  FOR item IN SELECT value FROM jsonb_a'
        "rray_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOREACH key IN ARRAY ARRA'
        "Y['engineering_configuration','manufactu"
        "ring_configuration','batch'] LOOP\n   IF "
        "payload#>>ARRAY['body','location',key,'i"
        "d'] IS NOT NULL THEN links=array_append("
        "links,(payload#>>ARRAY['body','location'"
        ",key,'id'])::uuid); END IF;\n  END LOOP;\n"
        '  FOR item IN SELECT value FROM jsonb_ar'
        "ray_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   I"
        "F item->>'receipt_id' IS NOT NULL THEN l"
        "inks=array_append(links,(item->>'receipt"
        "_id')::uuid); END IF;\n   IF item->>'row_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'row_id')::uuid); END IF;\n"
        '  END LOOP;\n END IF;\n IF table_name IN ('
        "'change_request_versions','change_graph_"
        "captures') THEN\n  FOR container IN SELEC"
        'T value FROM jsonb_each(coalesce(payload'
        "#>'{source_basis,owners}','{}')) LOOP\n  "
        " IF container->>'feedback_version_id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Cl'
        'osed native Field plan and occurrence re'
        'ferences, never arbitrary UUID prose.\n I'
        "F table_name='controlled_change_selectio"
        "n_facts' AND payload->>'basis_kind'='fie"
        "ld_intent' THEN\n  IF payload->>'feedback"
        "_version_id' IS NOT NULL THEN\n   links=a"
        "rray_append(links,(payload->>'feedback_v"
        "ersion_id')::uuid);\n  END IF;\n END IF;\n "
        "IF table_name='change_implementation_cap"
        "tures'\n  AND payload#>>'{occurrence_snap"
        "shot,schema_version}'='pdos-field-change"
        "-implementation-occurrence-v1' THEN\n  FO"
        "REACH key IN ARRAY ARRAY['feedback_versi"
        "on_id','selection_id'] LOOP\n   IF payloa"
        "d#>>ARRAY['occurrence_snapshot',key] IS "
        'NOT NULL THEN\n    links=array_append(lin'
        "ks,(payload#>>ARRAY['occurrence_snapshot"
        "',key])::uuid);\n   END IF;\n  END LOOP;\n "
        "END IF;\n\n IF table_name='change_completi"
        "on_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','"
        "order_record_id','shared_proof_id'] LOOP"
        '\n   IF payload->>key IS NOT NULL THEN li'
        'nks=array_append(links,(payload->>key)::'
        'uuid); END IF;\n  END LOOP;\n  FOR item IN'
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload->'required_source_read_"
        "set','[]')) LOOP\n   IF item->>'artifact_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'artifact_id')::uuid); END"
        " IF;\n  END LOOP;\n  IF payload#>>'{native"
        "_input,lot,id}' IS NOT NULL THEN links=a"
        "rray_append(links,(payload#>>'{native_in"
        "put,lot,id}')::uuid); END IF;\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LO"
        'OP;\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload#>'{nat"
        "ive_input,mappings}','[]')) LOOP\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO ext"
        'ra FROM verification_run_versions\n    WH'
        'ERE tenant_id=t AND category_id=c AND ru'
        "n_id=(item#>>'{run,id}')::uuid AND revis"
        "ion=(item#>>'{run,revision}')::integer;\n"
        '   links=links||extra; links=array_appen'
        "d(links,(item->>'sample_id')::uuid);\n  E"
        'ND LOOP;\n END IF;\n\n -- Closed native own'
        'er DTOs: retain exact outputs and native'
        " execution/report rows.\n IF table_name='"
        "change_completion_records' THEN\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{fact_snapshot,o"
        "utput_refs}','[]')) LOOP\n   IF item->>'k"
        "ind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM ver"
        'ification_run_versions\n     WHERE tenant'
        '_id=t AND category_id=c AND run_id=(item'
        "->>'id')::uuid AND revision=(item->>'rev"
        "ision')::integer;\n    links=links||extra"
        ";\n   ELSIF item->>'kind'=ANY(ARRAY['engi"
        "neering_configuration','manufacturing_co"
        "nfiguration','build','sample']) THEN\n   "
        " links=array_append(links,(item->>'id'):"
        ':uuid);\n   END IF;\n  END LOOP;\n  IF payl'
        "oad#>>'{owner_basis,schema_version}'='pd"
        "os-native-build-adoption-read-v1' THEN\n "
        "  FOREACH key IN ARRAY ARRAY['previous_b"
        "uild','successor_build','actual_configur"
        "ation','lot','start'] LOOP\n    IF payloa"
        "d#>>ARRAY['owner_basis',key,'id'] IS NOT"
        ' NULL THEN\n     links=array_append(links'
        ",(payload#>>ARRAY['owner_basis',key,'id'"
        '])::uuid);\n    END IF;\n   END LOOP;\n  EL'
        "SIF payload#>>'{owner_basis,schema_versi"
        "on}'='pdos-native-change-run-verificatio"
        "n-v1' THEN\n   FOR container IN SELECT va"
        "lue FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREA"
        "CH key IN ARRAY ARRAY['run_version_id','"
        "request_version_id','projection_id'] LOO"
        'P\n     IF container->>key IS NOT NULL TH'
        'EN links=array_append(links,(container->'
        '>key)::uuid); END IF;\n    END LOOP;\n   E'
        'ND LOOP;\n  END IF;\n END IF;\n\n -- F: only'
        ' server-verified fixed answer proofs est'
        'ablish these dependency edges.\n -- Nativ'
        'e deferred atoms bind these exact arrays'
        ' to real source ledgers.\n IF table_name '
        "IN ('category_knowledge_entries','knowle"
        "dge_candidate_versions','knowledge_rule_"
        "versions','knowledge_answer_reviews','kn"
        "owledge_gap_submissions') THEN\n  contain"
        "er=CASE table_name WHEN 'category_knowle"
        "dge_entries' THEN payload->'answer_sourc"
        "es'\n   WHEN 'knowledge_candidate_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   WHEN 'knowledge_rule_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   ELSE payload->'source_proof'"
        ' END;\n  -- Only these native knowledge r'
        'ows have an optional answer-derived proo'
        'f.\n  -- to_jsonb(row) represents an SQL '
        'NULL column as a JSON null member.\n  IF '
        "table_name IN ('category_knowledge_entri"
        "es','knowledge_candidate_versions','know"
        "ledge_rule_versions') THEN\n   container="
        "coalesce(nullif(container,'null'::jsonb)"
        ",'[]'::jsonb);\n  END IF;\n  -- Review/Gap"
        ' proof remains required and reaches the '
        'strict resolver unchanged.\n  links=links'
        '||public.assistant_source_lifecycle_link'
        's(t,c,container);\n END IF;\n\n -- G privat'
        'e outbound body copies have no category '
        'column. Only the fixed\n -- server footpr'
        'int subset for this REAL category establ'
        "ishes retention edges.\n IF table_name='d"
        "ingtalk_deliveries' THEN\n  IF payload->>"
        "'tenant_id' IS DISTINCT FROM t::text OR "
        "c IS NULL THEN\n   RAISE EXCEPTION 'Deliv"
        "ery retention scope mismatch' USING ERRC"
        "ODE='23514'; END IF;\n  SELECT coalesce(j"
        "sonb_agg(value),'[]'::jsonb) INTO contai"
        'ner\n   FROM jsonb_array_elements(coalesc'
        "e(payload->'source_dependencies','[]'::j"
        "sonb))\n   WHERE value->>'category_id'=c:"
        ':text;\n  links=links||public.assistant_s'
        'ource_lifecycle_links(t,c,container);\n E'
        'ND IF;\n RETURN links;\nEND;\n$function$\n'
    ),
    'm3_lifecycle_nodes(uuid,uuid,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_nodes(t uuid, c uuid, identities '
        'uuid[] DEFAULT NULL::uuid[])\n RETURNS TA'
        'BLE(table_name text, node_id uuid, links'
        ' uuid[])\n LANGUAGE plpgsql\n STABLE SECUR'
        "ITY DEFINER\n SET search_path TO 'pg_cata"
        "log', 'public', 'pg_temp'\nAS $function$\n"
        'DECLARE name text; payload jsonb; contro'
        'ls uuid[];\nBEGIN\n IF identities IS NULL '
        "THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO controls FROM public.action_rece"
        'ipts\n   WHERE tenant_id=t AND category_i'
        "d=c AND operation LIKE 'evidence.lifecyc"
        "le.%';\n ELSE controls='{}'; END IF;\n FOR"
        'EACH name IN ARRAY CASE WHEN identities '
        "IS NULL THEN ARRAY['agent_runs','action_"
        "receipts','actual_configurations','artif"
        "act_versions','audit_entries','bom_lines"
        "','bom_revisions','build_authorization_d"
        "ecisions','build_current_authorizations'"
        ",'build_current_execution_assessments','"
        "build_execution_assessments','build_lots"
        "','build_operational_current','build_ope"
        "rational_facts','build_readiness','build"
        "_starts','builds','capa_current_observat"
        "ions','capa_current_verification_rules',"
        "'capa_named_verification_reviews','capa_"
        "observation_facts','capa_remediation_lin"
        "ks','capa_verification_evidence','capa_v"
        "erification_rule_facts','change_approval"
        "_records','change_dependency_clocks','ch"
        "ange_graph_captures','change_implementat"
        "ion_captures','change_implementation_rec"
        "ords','change_order_records','change_req"
        "uest_currents','change_request_versions'"
        ",'claim_consumptions','claims','controll"
        "ed_change_coverage_currents','controlled"
        "_change_coverage_facts','controlled_chan"
        "ge_policy_currents','controlled_change_p"
        "olicy_facts','controlled_change_selectio"
        "n_currents','controlled_change_selection"
        "_facts','cost_current_inputs','cost_esti"
        "mates','cost_input_snapshots','cost_sour"
        "ce_captures','definition_revisions','def"
        "inition_sources','definition_specs','eng"
        "ineering_configurations','manufacturing_"
        "baseline_document_links','manufacturing_"
        "preparation_currents','manufacturing_pre"
        "paration_versions','measurement_import_c"
        "aptures','operational_material_holds','o"
        "perational_resource_occupancies','origin"
        "al_scan_requests','original_scan_results"
        "','original_security','outbox_events','p"
        "arts','plan_proposals','plan_revisions',"
        "'process_revisions','product_variants','"
        "professional_authority_current','profess"
        "ional_authority_facts','project_product_"
        "links','project_tasks','project_work_pac"
        "kages','projects','quality_current_issue"
        "s','quality_current_policies','quality_e"
        "vent_failure_links','quality_failure_map"
        "s','quality_issue_versions','quality_pol"
        "icy_facts','request_keys','runs','sample"
        "_allocations','sample_current_readiness'"
        ",'sample_readiness_facts','sample_run_us"
        "ages','sample_units','sample_usage_senti"
        "nels','supply_current_snapshots','supply"
        "_kit_projections','supply_snapshots','su"
        "pply_source_captures','task_dependencies"
        "','test_measurements','test_resource_cur"
        "rent','test_resource_facts','test_resour"
        "ce_reservations','test_result_actions','"
        "test_result_projections','uploaded_origi"
        "nals','variant_revisions','verification_"
        "actual_method_applicabilities','verifica"
        "tion_actual_method_batches','verificatio"
        "n_current_actual_methods','verification_"
        "current_formal_requests','verification_c"
        "urrent_preparations','verification_curre"
        "nt_runs','verification_formal_requests',"
        "'verification_handoff_facts','verificati"
        "on_launch_facts','verification_method_ap"
        "plicabilities','verification_preparation"
        "s','verification_run_identities','verifi"
        "cation_run_versions','verification_windo"
        "w_proposals','work_requests','proposals'"
        ",'proposal_items','proposal_item_version"
        "s','proposal_revisions','proposal_source"
        "s','proposal_submissions','proposal_deci"
        "sions','project_open_items','category_kn"
        "owledge_entries','category_knowledge_cur"
        "rent','product_target_segments','paramet"
        "er_versions','parameter_current','promot"
        "ion_proofs','evidence_links','claim_with"
        "drawals','manufacturing_baseline_publica"
        "tions','manufacturing_publication_curren"
        "ts','manufacturing_publication_documents"
        "','native_pilot_runs','native_pilot_curr"
        "ents','native_pilot_observations','relea"
        "se_packages','release_package_currents',"
        "'release_decisions','release_policy_fact"
        "s','release_policy_currents','external_h"
        "andoff_authorizations','external_deliver"
        "y_intents','external_receipts','external"
        "_handoff_currents','release_exception_de"
        "cisions','release_exception_currents','w"
        "ork_commitment_reviews','work_commitment"
        "_review_currents','work_task_versions','"
        "work_task_currents','work_commitment_ver"
        "sions','work_commitment_currents','proje"
        "ct_status_updates','external_wait_versio"
        "ns','external_wait_currents','project_ri"
        "sk_followups','project_risk_followup_cur"
        "rents','knowledge_candidate_versions','k"
        "nowledge_candidate_currents','knowledge_"
        "applicability_assessments','knowledge_ru"
        "le_versions','knowledge_rule_currents','"
        "field_feedback_versions','field_feedback"
        "_currents','field_response_records','kno"
        "wledge_answer_reviews','knowledge_gap_su"
        "bmissions'] ELSE ARRAY[\n  'artifact_vers"
        "ions','claims','definition_revisions','d"
        "efinition_sources','definition_specs',\n "
        " 'proposals','proposal_items','proposal_"
        "item_versions','proposal_submissions','p"
        "roposal_decisions',\n  'category_knowledg"
        "e_entries','category_knowledge_current',"
        "'parameter_versions','parameter_current'"
        ",\n  'evidence_links','promotion_proofs',"
        "'native_pilot_runs','native_pilot_curren"
        "ts','native_pilot_observations','release"
        "_packages','release_package_currents','r"
        "elease_decisions','release_policy_facts'"
        ",'release_policy_currents','external_han"
        "doff_authorizations','external_delivery_"
        "intents','external_receipts','external_h"
        "andoff_currents','release_exception_deci"
        "sions','release_exception_currents','wor"
        "k_commitment_reviews','work_commitment_r"
        "eview_currents','work_task_versions','wo"
        "rk_task_currents','work_commitment_versi"
        "ons','work_commitment_currents','project"
        "_status_updates','external_wait_versions"
        "','external_wait_currents','project_risk"
        "_followups','project_risk_followup_curre"
        "nts','knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_ap"
        "plicability_assessments','knowledge_rule"
        "_versions','knowledge_rule_currents','fi"
        "eld_feedback_versions','field_feedback_c"
        "urrents','field_response_records','knowl"
        "edge_answer_reviews','knowledge_gap_subm"
        "issions'] END LOOP\n  FOR payload IN EXEC"
        "UTE CASE WHEN name=ANY(ARRAY['audit_entr"
        "ies','outbox_events','request_keys'])\n  "
        " THEN format('SELECT to_jsonb(x) FROM pu"
        'blic.%I x JOIN public.action_receipts r '
        'ON r.id=x.receipt_id AND r.tenant_id=x.t'
        'enant_id WHERE x.tenant_id=$1 AND r.cate'
        "gory_id=$2',name)\n   ELSE format('SELECT"
        ' to_jsonb(x) FROM public.%I x WHERE tena'
        'nt_id=$1 AND category_id=$2 AND ($3 IS N'
        "ULL OR %I=ANY($3))',name,\n    CASE name "
        "WHEN 'category_knowledge_current' THEN '"
        "lineage_id'\n     WHEN 'parameter_current"
        "' THEN 'parameter_id' ELSE 'id' END)\n   "
        'END USING t,c,identities LOOP\n   IF (pay'
        "load->>'receipt_id')::uuid=ANY(controls)"
        " OR\n    (name='action_receipts' AND payl"
        "oad->>'operation' LIKE 'evidence.lifecyc"
        "le.%') THEN CONTINUE; END IF;\n   table_n"
        "ame=name;\n   node_id=CASE name WHEN 'cat"
        "egory_knowledge_current' THEN (payload->"
        ">'lineage_id')::uuid\n    WHEN 'parameter"
        "_current' THEN (payload->>'parameter_id'"
        ")::uuid ELSE (payload->>'id')::uuid END;"
        '\n   IF identities IS NULL THEN links=pub'
        'lic.m3_lifecycle_row_links(t,c,name,payl'
        'oad);\n   ELSE links=public.m3_lifecycle_'
        'source_links(t,c,name,payload); END IF;\n'
        "   -- Preserve predecessor's conservativ"
        'e legacy graph; M3-only nodes use\n   -- '
        'strictly typed/relational links. Root lo'
        'okup never uses free-text UUIDs.\n   IF i'
        "dentities IS NULL AND name<>ALL(ARRAY['n"
        "ative_pilot_runs','native_pilot_currents"
        "','native_pilot_observations','release_p"
        "ackages','release_package_currents','rel"
        "ease_decisions','release_policy_facts','"
        "release_policy_currents','external_hando"
        "ff_authorizations','external_delivery_in"
        "tents','external_receipts','external_han"
        "doff_currents','release_exception_decisi"
        "ons','release_exception_currents','work_"
        "commitment_reviews','work_commitment_rev"
        "iew_currents','work_task_versions','work"
        "_task_currents','work_commitment_version"
        "s','work_commitment_currents','project_s"
        "tatus_updates','external_wait_versions',"
        "'external_wait_currents','project_risk_f"
        "ollowups','project_risk_followup_current"
        "s','manufacturing_baseline_publications'"
        ",'manufacturing_publication_currents','m"
        "anufacturing_publication_documents','pro"
        "posals','proposal_items','proposal_item_"
        "versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','propos"
        "al_decisions','project_open_items','cate"
        "gory_knowledge_entries','category_knowle"
        "dge_current','product_target_segments','"
        "parameter_versions','parameter_current',"
        "'promotion_proofs','evidence_links','cla"
        "im_withdrawals','knowledge_candidate_ver"
        "sions','knowledge_candidate_currents','k"
        "nowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_cu"
        "rrents','field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds','knowledge_answer_reviews','knowled"
        "ge_gap_submissions']) THEN\n    links=lin"
        'ks || public.kernel_lifecycle_links(name'
        ',payload);\n   END IF;\n   RETURN NEXT;\n  '
        'END LOOP;\n END LOOP;\n\n -- Read exactly t'
        'he retained metadata, never Delivery.pay'
        'load. One personal\n -- answer may appear'
        ' in several categories, each with its ow'
        'n source subset.\n FOR payload IN\n  SELEC'
        "T jsonb_build_object('id',d.id,'tenant_i"
        "d',d.tenant_id,\n   'content_kind',d.cont"
        "ent_kind,'source_dependencies',d.source_"
        'dependencies)\n  FROM public.dingtalk_del'
        'iveries d\n  WHERE d.tenant_id=t AND d.co'
        "ntent_kind='answer'\n   AND (identities I"
        'S NULL OR d.id=ANY(identities))\n   AND E'
        'XISTS(SELECT 1 FROM jsonb_array_elements'
        '(d.source_dependencies) dependency\n    W'
        "HERE dependency->>'category_id'=c::text)"
        "\n LOOP\n  table_name='dingtalk_deliveries"
        "'; node_id=(payload->>'id')::uuid;\n  lin"
        'ks=public.m3_lifecycle_source_links(t,c,'
        'table_name,payload);\n  RETURN NEXT;\n END'
        ' LOOP;\nEND;\n$function$\n'
    ),
}

NATIVE_FUNCTIONS = {
    'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_source_links(t uuid, c uuid, tabl'
        'e_name text, payload jsonb)\n RETURNS uui'
        'd[]\n LANGUAGE plpgsql\n STABLE SECURITY D'
        "EFINER\n SET search_path TO 'pg_catalog',"
        " 'public', 'pg_temp'\nAS $function$\nDECLA"
        "RE links uuid[]='{}'; extra uuid[]; key "
        'text; keys text[]; item jsonb; container'
        ' jsonb;\n target_kind text; referenced_ta'
        'rget uuid; referenced_version integer;\nB'
        "EGIN\n IF table_name='agent_runs' THEN RE"
        'TURN public.kernel_lifecycle_links(table'
        '_name,payload); END IF;\n -- Only actual '
        'top-level relation columns establish raw'
        ' UUID edges. Arbitrary\n -- content dicti'
        'onaries are not relational rows, even if'
        ' an extra key happens\n -- to be named so'
        'urce_id or item_id.\n keys=CASE table_nam'
        "e\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRA"
        "Y['artifact_id','snapshot_id']\n  WHEN 'd"
        "efinition_revisions' THEN ARRAY['derived"
        "_from_definition_id','parent_definition_"
        "id',\n   'source_proposal_id','source_sub"
        "mission_id']\n  WHEN 'definition_sources'"
        " THEN ARRAY['artifact_id']\n  WHEN 'defin"
        "ition_specs' THEN ARRAY[]::text[]\n  WHEN"
        " 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN"
        " 'proposal_items' THEN ARRAY[]::text[]\n "
        " WHEN 'proposal_item_versions' THEN ARRA"
        "Y[]::text[]\n  WHEN 'proposal_revisions' "
        "THEN ARRAY['proposal_id']\n  WHEN 'propos"
        "al_sources' THEN ARRAY['source_id']\n  WH"
        "EN 'proposal_submissions' THEN ARRAY[]::"
        "text[]\n  WHEN 'proposal_decisions' THEN "
        "ARRAY['submission_id']\n  WHEN 'project_o"
        "pen_items' THEN ARRAY['source_question_i"
        "d','source_spec_item_id','g0_decision_id"
        "']\n  WHEN 'category_knowledge_current' T"
        "HEN ARRAY['current_entry_id']\n  WHEN 'pr"
        "omotion_proofs' THEN ARRAY['knowledge_en"
        "try_id','source_proposal_id']\n  WHEN 'ev"
        "idence_links' THEN ARRAY['evidence_id']\n"
        "  WHEN 'claim_withdrawals' THEN ARRAY['c"
        "laim_id']\n  WHEN 'manufacturing_baseline"
        "_publications' THEN ARRAY['baseline_id',"
        "'process_id','previous_id']\n  WHEN 'manu"
        "facturing_publication_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'manufacturing_p"
        "ublication_documents' THEN ARRAY['docume"
        "nt_id','process_id']\n  WHEN 'native_pilo"
        "t_runs' THEN ARRAY['build_id','lot_id','"
        "actual_configuration_id','engineering_co"
        "nfiguration_id','process_id','publicatio"
        "n_id']\n  WHEN 'native_pilot_currents' TH"
        "EN ARRAY['pilot_id','latest_observation_"
        "id']\n  WHEN 'native_pilot_observations' "
        "THEN ARRAY['pilot_id','previous_observat"
        "ion_id']\n  WHEN 'release_packages' THEN "
        "ARRAY['previous_id']\n  WHEN 'release_pac"
        "kage_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'release_decisions' THEN ARRAY['p"
        "ackage_id']\n  WHEN 'release_policy_facts"
        "' THEN ARRAY['previous_id']\n  WHEN 'rele"
        "ase_policy_currents' THEN ARRAY['fact_id"
        "']\n  WHEN 'external_handoff_authorizatio"
        "ns' THEN ARRAY['package_id','engineering"
        "_decision_id','manufacturing_decision_id"
        "']\n  WHEN 'external_delivery_intents' TH"
        "EN ARRAY['handoff_id']\n  WHEN 'external_"
        "receipts' THEN ARRAY['handoff_id','inten"
        "t_id','previous_receipt_id','reconciles_"
        "id']\n  WHEN 'external_handoff_currents' "
        "THEN ARRAY['handoff_id','intent_id','lat"
        "est_receipt_id']\n  WHEN 'release_excepti"
        "on_decisions' THEN ARRAY['basis_package_"
        "id','policy_fact_id','previous_id']\n  WH"
        "EN 'release_exception_currents' THEN ARR"
        "AY['basis_package_id','policy_fact_id','"
        "decision_id']\n  WHEN 'work_commitment_re"
        "views' THEN ARRAY['commitment_id','task_"
        "version_id','submission_id','previous_id"
        "']\n  WHEN 'work_commitment_review_curren"
        "ts' THEN ARRAY['version_id']\n  WHEN 'ext"
        "ernal_wait_versions' THEN ARRAY['previou"
        "s_id']\n  WHEN 'external_wait_currents' T"
        "HEN ARRAY['version_id']\n  WHEN 'project_"
        "risk_followups' THEN ARRAY['previous_id'"
        ",'risk_id','g0_decision_id']\n  WHEN 'pro"
        "ject_risk_followup_currents' THEN ARRAY["
        "'version_id']\n  WHEN 'work_task_versions"
        "' THEN ARRAY['previous_id']\n  WHEN 'work"
        "_task_currents' THEN ARRAY['version_id']"
        "\n  WHEN 'work_commitment_versions' THEN "
        "ARRAY['replaces_id']\n  WHEN 'work_commit"
        "ment_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'project_status_updates' THEN ARR"
        'AY[]::text[]\n  ELSE ARRAY[]::text[] END;'
        '\n FOREACH key IN ARRAY keys LOOP\n  IF pa'
        'yload->>key IS NOT NULL THEN links=array'
        '_append(links,(payload->>key)::uuid); EN'
        "D IF;\n END LOOP;\n -- Publication's exact"
        ' saved read set is a validated Artifact '
        'relationship.\n -- Do not scan its declar'
        'ation, body, reason or arbitrary JSON UU'
        "ID values.\n IF table_name IN ('manufactu"
        "ring_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','rel"
        "ease_packages','release_decisions','rele"
        "ase_policy_facts','external_handoff_auth"
        "orizations','external_receipts','release"
        "_exception_decisions') THEN\n  FOR item I"
        'N SELECT value FROM jsonb_array_elements'
        "(coalesce(payload->'required_source_read"
        "_set','[]')) LOOP\n   IF item->>'artifact"
        "_id' IS NOT NULL THEN\n    links=array_ap"
        "pend(links,(item->>'artifact_id')::uuid)"
        ';\n   END IF;\n  END LOOP;\n END IF;\n IF ta'
        "ble_name IN ('native_pilot_runs','native"
        "_pilot_observations') THEN\n  FOR item IN"
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{material_snapshot,st"
        "atistics,samples}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOR item IN SELECT value '
        'FROM jsonb_array_elements(coalesce(paylo'
        "ad#>'{material_snapshot,statistics,issue"
        "s}','[]')) LOOP\n   IF item->>'id' IS NOT"
        ' NULL THEN links=array_append(links,(ite'
        "m->>'id')::uuid); END IF;\n  END LOOP;\n  "
        "item=payload#>'{material_snapshot,statis"
        "tics,resource,fact}';\n  IF item->>'id' I"
        'S NOT NULL THEN links=array_append(links'
        ",(item->>'id')::uuid); END IF;\n END IF;\n"
        " IF table_name='release_packages' THEN\n "
        ' -- FixedObject.ref is a closed, server-'
        'resolved version reference, not arbitrar'
        'y body UUID text.\n  FOR item IN SELECT v'
        'alue FROM jsonb_array_elements(coalesce('
        "payload#>'{body,objects}','[]')) LOOP\n  "
        " container=item->'ref';\n   IF container-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "manufacturing_publication','test_run','p"
        "ilot_run','issue','change','exception','"
        "artifact','work_instruction','control_pl"
        "an','build_lot','line'])\n    AND contain"
        "er->>'id' IS NOT NULL THEN links=array_a"
        "ppend(links,(container->>'id')::uuid); E"
        'ND IF;\n  END LOOP;\n END IF;\n IF table_na'
        "me IN ('external_handoff_authorizations'"
        ",'external_delivery_intents') THEN\n  -- "
        'Only closed, owner-verified mapping and '
        'manifest references are source edges.\n  '
        "container=CASE WHEN table_name='external"
        "_handoff_authorizations' THEN payload#>'"
        "{body,declaration}' ELSE payload->'body'"
        ' END;\n  FOR item IN SELECT value FROM js'
        "onb_array_elements(coalesce(container->'"
        "mappings','[]')) LOOP\n   IF item->'ref'-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "part','bom_revision','artifact','work_in"
        "struction','control_plan'])\n    AND item"
        "->'ref'->>'id' IS NOT NULL THEN links=ar"
        "ray_append(links,(item->'ref'->>'id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN '
        'SELECT value FROM jsonb_array_elements(c'
        "oalesce(container->'manifest','[]')) LOO"
        "P\n   IF item->'artifact'->>'id' IS NOT N"
        'ULL THEN links=array_append(links,(item-'
        ">'artifact'->>'id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n IF table_name='release"
        "_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by '
        'the policy owner.\n  FOREACH key IN ARRAY'
        " ARRAY['definition','engineering_configu"
        "ration','manufacturing_configuration'] L"
        "OOP\n   container=payload#>ARRAY['materia"
        "l','subject_config',key];\n   IF containe"
        "r->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(container->>'id')::uuid); EN"
        'D IF;\n  END LOOP;\n END IF;\n -- These sto'
        'red fields are validated Reference conta'
        'iners. Do not feed the\n -- whole row or '
        'arbitrary content into the canonical Ref'
        'erence parser.\n IF table_name=ANY(ARRAY['
        "'proposals','proposal_item_versions','pr"
        "oposal_submissions',\n  'category_knowled"
        "ge_entries','definition_specs']) THEN\n  "
        "FOREACH key IN ARRAY ARRAY['source_refs'"
        ",'direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links "
        '|| public.m3_lifecycle_typed_links(t,c,p'
        'ayload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and catego'
        'ry_service._references: only\n -- commerc'
        'ial_target, voice, and competitor have n'
        "ested source contracts.\n IF table_name='"
        "proposal_item_versions' AND payload->>'k"
        "ind'='commercial_target' THEN\n  FOREACH "
        "key IN ARRAY ARRAY['target_price','cost'"
        ",'volume'] LOOP\n   links=links || public"
        ".m3_lifecycle_typed_links(t,c,payload->'"
        "content'->key->'source');\n  END LOOP;\n E"
        "LSIF table_name='category_knowledge_entr"
        "ies' AND payload->>'kind'='voice' THEN\n "
        ' links=links || public.m3_lifecycle_type'
        "d_links(t,c,payload->'content'->'represe"
        "ntative_refs');\n ELSIF table_name='categ"
        "ory_knowledge_entries' AND payload->>'ki"
        "nd'='competitor' THEN\n  FOREACH key IN A"
        "RRAY ARRAY['metrics','features','prices'"
        '] LOOP\n   FOR item IN SELECT value FROM '
        "jsonb_array_elements(coalesce(payload->'"
        "content'->key,'[]')) LOOP\n    links=link"
        's || public.m3_lifecycle_typed_links(t,c'
        ",item->'source_ref');\n   END LOOP;\n  END"
        " LOOP;\n END IF;\n IF table_name='proposal"
        "_submissions' THEN\n  container=payload->"
        "'frozen_document';\n  FOREACH key IN ARRA"
        "Y ARRAY['source_refs','direct_source_ref"
        "s','context_refs','baseline_claim_refs']"
        ' LOOP\n   links=links || public.m3_lifecy'
        'cle_typed_links(t,c,container->key);\n  E'
        'ND LOOP;\n  FOR item IN SELECT value FROM'
        ' jsonb_array_elements(coalesce(container'
        "->'items','[]')) LOOP\n   links=links || "
        "public.m3_lifecycle_source_links(t,c,'pr"
        "oposal_item_versions',item-ARRAY['item_i"
        "d','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink'
        ' provenance here.\n   links=links || publ'
        "ic.m3_lifecycle_typed_links(t,c,item->'e"
        "vidence_links');\n  END LOOP;\n ELSIF tabl"
        "e_name='promotion_proofs' THEN\n  FOR ite"
        'm IN SELECT value FROM jsonb_array_eleme'
        "nts(coalesce(payload->'source_item_refs'"
        ",'[]')) LOOP\n   IF item->>'item_id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'item_id')::uuid); END IF;\n  END L"
        'OOP;\n END IF;\n -- Exact persisted Eviden'
        'ceLink targets supplement these immutabl'
        'e versions.\n -- Reverted links and withd'
        'rawn Claims still retain the original hi'
        'storical\n -- dependency; lifecycle clean'
        'up must not erase their audit source.\n I'
        "F table_name='proposal_item_versions' AN"
        "D payload->>'item_id' IS NOT NULL THEN\n "
        " target_kind='proposal_item'; referenced"
        "_target=(payload->>'item_id')::uuid;\n  r"
        "eferenced_version=(payload->>'version'):"
        ":integer;\n ELSIF table_name='category_kn"
        "owledge_entries' AND payload->>'id' IS N"
        "OT NULL THEN\n  target_kind='knowledge_en"
        "try'; referenced_target=(payload->>'id')"
        '::uuid;\n  referenced_version=(payload->>'
        "'version')::integer;\n ELSIF table_name='"
        "definition_specs' AND payload->>'id' IS "
        "NOT NULL THEN\n  target_kind='definition_"
        "spec'; referenced_target=(payload->>'id'"
        ')::uuid;\n  SELECT revision INTO referenc'
        'ed_version FROM public.definition_revisi'
        'ons\n   WHERE tenant_id=t AND category_id'
        "=c AND id=(payload->>'definition_id')::u"
        'uid;\n END IF;\n IF referenced_target IS N'
        'OT NULL AND referenced_version IS NOT NU'
        'LL THEN\n  SELECT coalesce(array_agg(link'
        ".evidence_id),'{}') INTO extra FROM publ"
        'ic.evidence_links link\n   WHERE link.ten'
        'ant_id=t AND link.category_id=c AND link'
        '.target_type=target_kind\n    AND link.ta'
        'rget_id=referenced_target AND link.targe'
        't_version=referenced_version;\n  links=li'
        'nks || extra;\n END IF;\n -- Child source '
        'rows point to their parent, whereas depe'
        "ndency traversal needs\n -- the parent's "
        'fixed source children as well. Keep the '
        "actual relational edge.\n IF table_name='"
        "definition_revisions' THEN\n  SELECT coal"
        "esce(array_agg(id),'{}') INTO extra FROM"
        ' (\n   SELECT id FROM public.definition_s'
        'ources WHERE tenant_id=t AND category_id'
        "=c\n    AND definition_id=(payload->>'id'"
        ')::uuid\n   UNION ALL SELECT id FROM publ'
        'ic.definition_specs WHERE tenant_id=t AN'
        'D category_id=c\n    AND definition_id=(p'
        "ayload->>'id')::uuid\n  ) children;\n  lin"
        "ks=links || extra;\n ELSIF table_name='pr"
        "oposals' THEN\n  SELECT coalesce(array_ag"
        "g(id),'{}') INTO extra FROM public.propo"
        'sal_item_versions\n   WHERE tenant_id=t A'
        'ND category_id=c AND proposal_id=(payloa'
        "d->>'id')::uuid;\n  links=links || extra;"
        "\n ELSIF table_name='proposal_items' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM public.proposal_item_vers'
        'ions\n   WHERE tenant_id=t AND category_i'
        "d=c AND item_id=(payload->>'id')::uuid;\n"
        '  links=links || extra;\n ELSIF table_nam'
        "e='product_target_segments' THEN\n  SELEC"
        "T coalesce(array_agg(id),'{}') INTO extr"
        'a FROM public.category_knowledge_entries'
        '\n   WHERE tenant_id=t AND category_id=c '
        "AND lineage_id=(payload->>'segment_linea"
        "ge_id')::uuid\n    AND version=(payload->"
        ">'segment_version')::integer;\n  links=li"
        "nks || extra;\n ELSIF table_name='paramet"
        "er_current' THEN\n  SELECT coalesce(array"
        "_agg(id),'{}') INTO extra FROM public.pa"
        'rameter_versions\n   WHERE tenant_id=t AN'
        'D category_id=c AND parameter_id=(payloa'
        "d->>'parameter_id')::uuid\n    AND versio"
        "n=(payload->>'current_version')::integer"
        ';\n  links=links || extra;\n END IF;\n\n IF '
        "table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_u"
        "pdates') THEN\n  FOR item IN SELECT value"
        ' FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array"
        "_append(links,(item->>'artifact_id')::uu"
        'id); END IF;\n  END LOOP;\n  IF table_name'
        "='work_task_versions' AND payload#>>'{bo"
        "dy,plan_task,id}' IS NOT NULL THEN\n   li"
        "nks=array_append(links,(payload#>>'{body"
        ",plan_task,id}')::uuid);\n  END IF;\n  IF "
        "table_name='work_commitment_versions' TH"
        "EN\n   SELECT coalesce(array_agg(id),'{}'"
        ') INTO extra FROM public.work_task_versi'
        'ons\n    WHERE tenant_id=t AND category_i'
        "d=c AND task_id=(payload->>'task_id')::u"
        "uid AND revision=(payload->>'task_revisi"
        "on')::integer;\n   links=links||extra;\n  "
        "ELSIF table_name='project_status_updates"
        "' THEN\n   FOR item IN SELECT value FROM "
        "jsonb_array_elements(coalesce(payload->'"
        "task_refs','[]')) LOOP\n    SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM p"
        'ublic.work_task_versions\n     WHERE tena'
        'nt_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'"
        "revision')::integer;\n    links=links||ex"
        'tra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' T"
        'HEN\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload->'read"
        "s','[]')) LOOP\n   IF item->>'artifact_id"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(item->>'artifact_id')::uuid); END I"
        'F;\n  END LOOP;\n END IF;\n\n IF table_name='
        "'external_wait_versions' THEN\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{source_basis,arti"
        "facts}','[]')) LOOP\n   IF item->>'id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(item->>'id')::uuid); END IF;\n  END LOOP"
        ";\n  FOREACH key IN ARRAY ARRAY['mileston"
        "e','build','calendar'] LOOP\n   container"
        "=payload#>ARRAY['body',key];\n   IF conta"
        "iner->>'id' IS NOT NULL THEN links=array"
        "_append(links,(container->>'id')::uuid);"
        ' END IF;\n  END LOOP;\n  container=payload'
        "#>'{body,replaces}';\n  IF container->>'i"
        "d' IS NOT NULL THEN\n   SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM publi"
        'c.external_wait_versions\n    WHERE tenan'
        't_id=t AND category_id=c AND wait_id=(co'
        "ntainer->>'id')::uuid AND revision=(cont"
        "ainer->>'revision')::integer;\n   links=l"
        'inks||extra;\n  END IF;\n END IF;\n IF tabl'
        "e_name='project_risk_followups' THEN\n  F"
        'OR item IN SELECT value FROM jsonb_array'
        "_elements(coalesce(payload#>'{source_bas"
        "is,artifacts}','[]')) LOOP\n   IF item->>"
        "'id' IS NOT NULL THEN links=array_append"
        "(links,(item->>'id')::uuid); END IF;\n  E"
        "ND LOOP;\n END IF;\n\n IF table_name IN ('k"
        "nowledge_candidate_versions','knowledge_"
        "candidate_currents','knowledge_applicabi"
        "lity_assessments','knowledge_rule_versio"
        "ns','knowledge_rule_currents') THEN\n  FO"
        "REACH key IN ARRAY ARRAY['previous_id','"
        "version_id','candidate_version_id','asse"
        "ssment_id','publication_id'] LOOP\n   IF "
        'payload->>key IS NOT NULL THEN links=arr'
        'ay_append(links,(payload->>key)::uuid); '
        'END IF;\n  END LOOP;\n  FOR item IN SELECT'
        ' value FROM jsonb_array_elements(coalesc'
        "e(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'i"
        "d')::uuid); END IF;\n  END LOOP;\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload->'reads','[]')) LO"
        "OP\n   IF item->>'artifact_id' IS NOT NUL"
        'L THEN links=array_append(links,(item->>'
        "'artifact_id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{sour"
        "ce_basis,result_receipts}','[]')) LOOP\n "
        "  IF item->>'receipt_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'rece"
        "ipt_id')::uuid); END IF;\n   IF item->>'r"
        "ow_id' IS NOT NULL THEN links=array_appe"
        "nd(links,(item->>'row_id')::uuid); END I"
        'F;\n  END LOOP;\n  FOR item IN SELECT valu'
        'e FROM jsonb_array_elements(coalesce(pay'
        "load#>'{source_basis,professional,fact_r"
        "efs}','[]')) LOOP\n   IF item->>'id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  IF payload#>>'{source_basis,target,id}"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(payload#>>'{source_basis,target,id}"
        "')::uuid); END IF;\n END IF;\n\n IF table_n"
        "ame IN ('field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds') THEN\n  FOREACH key IN ARRAY ARRAY["
        "'previous_id','version_id','feedback_ver"
        "sion_id'] LOOP\n   IF payload->>key IS NO"
        'T NULL THEN links=array_append(links,(pa'
        'yload->>key)::uuid); END IF;\n  END LOOP;'
        '\n  FOR item IN SELECT value FROM jsonb_a'
        "rray_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOREACH key IN ARRAY ARRA'
        "Y['engineering_configuration','manufactu"
        "ring_configuration','batch'] LOOP\n   IF "
        "payload#>>ARRAY['body','location',key,'i"
        "d'] IS NOT NULL THEN links=array_append("
        "links,(payload#>>ARRAY['body','location'"
        ",key,'id'])::uuid); END IF;\n  END LOOP;\n"
        '  FOR item IN SELECT value FROM jsonb_ar'
        "ray_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   I"
        "F item->>'receipt_id' IS NOT NULL THEN l"
        "inks=array_append(links,(item->>'receipt"
        "_id')::uuid); END IF;\n   IF item->>'row_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'row_id')::uuid); END IF;\n"
        '  END LOOP;\n END IF;\n IF table_name IN ('
        "'change_request_versions','change_graph_"
        "captures') THEN\n  FOR container IN SELEC"
        'T value FROM jsonb_each(coalesce(payload'
        "#>'{source_basis,owners}','{}')) LOOP\n  "
        " IF container->>'feedback_version_id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Cl'
        'osed native Field plan and occurrence re'
        'ferences, never arbitrary UUID prose.\n I'
        "F table_name='controlled_change_selectio"
        "n_facts' AND payload->>'basis_kind'='fie"
        "ld_intent' THEN\n  IF payload->>'feedback"
        "_version_id' IS NOT NULL THEN\n   links=a"
        "rray_append(links,(payload->>'feedback_v"
        "ersion_id')::uuid);\n  END IF;\n END IF;\n "
        "IF table_name='change_implementation_cap"
        "tures'\n  AND payload#>>'{occurrence_snap"
        "shot,schema_version}'='pdos-field-change"
        "-implementation-occurrence-v1' THEN\n  FO"
        "REACH key IN ARRAY ARRAY['feedback_versi"
        "on_id','selection_id'] LOOP\n   IF payloa"
        "d#>>ARRAY['occurrence_snapshot',key] IS "
        'NOT NULL THEN\n    links=array_append(lin'
        "ks,(payload#>>ARRAY['occurrence_snapshot"
        "',key])::uuid);\n   END IF;\n  END LOOP;\n "
        "END IF;\n\n IF table_name='change_completi"
        "on_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','"
        "order_record_id','shared_proof_id'] LOOP"
        '\n   IF payload->>key IS NOT NULL THEN li'
        'nks=array_append(links,(payload->>key)::'
        'uuid); END IF;\n  END LOOP;\n  FOR item IN'
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload->'required_source_read_"
        "set','[]')) LOOP\n   IF item->>'artifact_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'artifact_id')::uuid); END"
        " IF;\n  END LOOP;\n  IF payload#>>'{native"
        "_input,lot,id}' IS NOT NULL THEN links=a"
        "rray_append(links,(payload#>>'{native_in"
        "put,lot,id}')::uuid); END IF;\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LO"
        'OP;\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload#>'{nat"
        "ive_input,mappings}','[]')) LOOP\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO ext"
        'ra FROM verification_run_versions\n    WH'
        'ERE tenant_id=t AND category_id=c AND ru'
        "n_id=(item#>>'{run,id}')::uuid AND revis"
        "ion=(item#>>'{run,revision}')::integer;\n"
        '   links=links||extra; links=array_appen'
        "d(links,(item->>'sample_id')::uuid);\n  E"
        'ND LOOP;\n END IF;\n\n -- Closed native own'
        'er DTOs: retain exact outputs and native'
        " execution/report rows.\n IF table_name='"
        "change_completion_records' THEN\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{fact_snapshot,o"
        "utput_refs}','[]')) LOOP\n   IF item->>'k"
        "ind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM ver"
        'ification_run_versions\n     WHERE tenant'
        '_id=t AND category_id=c AND run_id=(item'
        "->>'id')::uuid AND revision=(item->>'rev"
        "ision')::integer;\n    links=links||extra"
        ";\n   ELSIF item->>'kind'=ANY(ARRAY['engi"
        "neering_configuration','manufacturing_co"
        "nfiguration','build','sample']) THEN\n   "
        " links=array_append(links,(item->>'id'):"
        ':uuid);\n   END IF;\n  END LOOP;\n  IF payl'
        "oad#>>'{owner_basis,schema_version}'='pd"
        "os-native-build-adoption-read-v1' THEN\n "
        "  FOREACH key IN ARRAY ARRAY['previous_b"
        "uild','successor_build','actual_configur"
        "ation','lot','start'] LOOP\n    IF payloa"
        "d#>>ARRAY['owner_basis',key,'id'] IS NOT"
        ' NULL THEN\n     links=array_append(links'
        ",(payload#>>ARRAY['owner_basis',key,'id'"
        '])::uuid);\n    END IF;\n   END LOOP;\n  EL'
        "SIF payload#>>'{owner_basis,schema_versi"
        "on}'='pdos-native-change-run-verificatio"
        "n-v1' THEN\n   FOR container IN SELECT va"
        "lue FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREA"
        "CH key IN ARRAY ARRAY['run_version_id','"
        "request_version_id','projection_id'] LOO"
        'P\n     IF container->>key IS NOT NULL TH'
        'EN links=array_append(links,(container->'
        '>key)::uuid); END IF;\n    END LOOP;\n   E'
        'ND LOOP;\n  END IF;\n END IF;\n\n -- F: only'
        ' server-verified fixed answer proofs est'
        'ablish these dependency edges.\n -- Nativ'
        'e deferred atoms bind these exact arrays'
        ' to real source ledgers.\n IF table_name '
        "IN ('category_knowledge_entries','knowle"
        "dge_candidate_versions','knowledge_rule_"
        "versions','knowledge_answer_reviews','kn"
        "owledge_gap_submissions') THEN\n  contain"
        "er=CASE table_name WHEN 'category_knowle"
        "dge_entries' THEN payload->'answer_sourc"
        "es'\n   WHEN 'knowledge_candidate_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   WHEN 'knowledge_rule_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   ELSE payload->'source_proof'"
        ' END;\n  -- Only these native knowledge r'
        'ows have an optional answer-derived proo'
        'f.\n  -- to_jsonb(row) represents an SQL '
        'NULL column as a JSON null member.\n  IF '
        "table_name IN ('category_knowledge_entri"
        "es','knowledge_candidate_versions','know"
        "ledge_rule_versions') THEN\n   container="
        "coalesce(nullif(container,'null'::jsonb)"
        ",'[]'::jsonb);\n  END IF;\n  -- Review/Gap"
        ' proof remains required and reaches the '
        'strict resolver unchanged.\n  links=links'
        '||public.assistant_source_lifecycle_link'
        's(t,c,container);\n END IF;\n\n -- G privat'
        'e outbound body copies have no category '
        'column. Only the fixed\n -- server footpr'
        'int subset for this REAL category establ'
        "ishes retention edges.\n IF table_name='d"
        "ingtalk_deliveries' THEN\n  IF payload->>"
        "'tenant_id' IS DISTINCT FROM t::text OR "
        "c IS NULL THEN\n   RAISE EXCEPTION 'Deliv"
        "ery retention scope mismatch' USING ERRC"
        "ODE='23514'; END IF;\n  SELECT coalesce(j"
        "sonb_agg(value),'[]'::jsonb) INTO contai"
        'ner\n   FROM jsonb_array_elements(coalesc'
        "e(payload->'source_dependencies','[]'::j"
        "sonb))\n   WHERE value->>'category_id'=c:"
        ':text;\n  links=links||public.assistant_s'
        'ource_lifecycle_links(t,c,container);\n E'
        'ND IF;\n\n -- E: actual deterministic-summ'
        'ary fixed ObjectRef IDs, from server-onl'
        "y delivery capture.\n IF table_name='ding"
        "talk_summary_deliveries' THEN\n  IF paylo"
        "ad->>'tenant_id' IS DISTINCT FROM t::tex"
        "t OR payload->>'category_id' IS DISTINCT"
        " FROM c::text THEN\n   RAISE EXCEPTION 'S"
        'ummary delivery retention scope mismatch'
        "' USING ERRCODE='23514'; END IF;\n  IF pa"
        "yload->>'run_id' IS NOT NULL THEN links="
        "array_append(links,(payload->>'run_id'):"
        ':uuid); END IF;\n  FOR key IN SELECT valu'
        'e FROM jsonb_array_elements_text(payload'
        "->'source_ids') LOOP\n   links=array_appe"
        'nd(links,key::uuid);\n  END LOOP;\n END IF'
        ';\n RETURN links;\nEND;\n$function$\n'
    ),
    'm3_lifecycle_nodes(uuid,uuid,uuid[])': (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_nodes(t uuid, c uuid, identities '
        'uuid[] DEFAULT NULL::uuid[])\n RETURNS TA'
        'BLE(table_name text, node_id uuid, links'
        ' uuid[])\n LANGUAGE plpgsql\n STABLE SECUR'
        "ITY DEFINER\n SET search_path TO 'pg_cata"
        "log', 'public', 'pg_temp'\nAS $function$\n"
        'DECLARE name text; payload jsonb; contro'
        'ls uuid[];\nBEGIN\n IF identities IS NULL '
        "THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO controls FROM public.action_rece"
        'ipts\n   WHERE tenant_id=t AND category_i'
        "d=c AND operation LIKE 'evidence.lifecyc"
        "le.%';\n ELSE controls='{}'; END IF;\n FOR"
        'EACH name IN ARRAY CASE WHEN identities '
        "IS NULL THEN ARRAY['agent_runs','action_"
        "receipts','actual_configurations','artif"
        "act_versions','audit_entries','bom_lines"
        "','bom_revisions','build_authorization_d"
        "ecisions','build_current_authorizations'"
        ",'build_current_execution_assessments','"
        "build_execution_assessments','build_lots"
        "','build_operational_current','build_ope"
        "rational_facts','build_readiness','build"
        "_starts','builds','capa_current_observat"
        "ions','capa_current_verification_rules',"
        "'capa_named_verification_reviews','capa_"
        "observation_facts','capa_remediation_lin"
        "ks','capa_verification_evidence','capa_v"
        "erification_rule_facts','change_approval"
        "_records','change_dependency_clocks','ch"
        "ange_graph_captures','change_implementat"
        "ion_captures','change_implementation_rec"
        "ords','change_order_records','change_req"
        "uest_currents','change_request_versions'"
        ",'claim_consumptions','claims','controll"
        "ed_change_coverage_currents','controlled"
        "_change_coverage_facts','controlled_chan"
        "ge_policy_currents','controlled_change_p"
        "olicy_facts','controlled_change_selectio"
        "n_currents','controlled_change_selection"
        "_facts','cost_current_inputs','cost_esti"
        "mates','cost_input_snapshots','cost_sour"
        "ce_captures','definition_revisions','def"
        "inition_sources','definition_specs','eng"
        "ineering_configurations','manufacturing_"
        "baseline_document_links','manufacturing_"
        "preparation_currents','manufacturing_pre"
        "paration_versions','measurement_import_c"
        "aptures','operational_material_holds','o"
        "perational_resource_occupancies','origin"
        "al_scan_requests','original_scan_results"
        "','original_security','outbox_events','p"
        "arts','plan_proposals','plan_revisions',"
        "'process_revisions','product_variants','"
        "professional_authority_current','profess"
        "ional_authority_facts','project_product_"
        "links','project_tasks','project_work_pac"
        "kages','projects','quality_current_issue"
        "s','quality_current_policies','quality_e"
        "vent_failure_links','quality_failure_map"
        "s','quality_issue_versions','quality_pol"
        "icy_facts','request_keys','runs','sample"
        "_allocations','sample_current_readiness'"
        ",'sample_readiness_facts','sample_run_us"
        "ages','sample_units','sample_usage_senti"
        "nels','supply_current_snapshots','supply"
        "_kit_projections','supply_snapshots','su"
        "pply_source_captures','task_dependencies"
        "','test_measurements','test_resource_cur"
        "rent','test_resource_facts','test_resour"
        "ce_reservations','test_result_actions','"
        "test_result_projections','uploaded_origi"
        "nals','variant_revisions','verification_"
        "actual_method_applicabilities','verifica"
        "tion_actual_method_batches','verificatio"
        "n_current_actual_methods','verification_"
        "current_formal_requests','verification_c"
        "urrent_preparations','verification_curre"
        "nt_runs','verification_formal_requests',"
        "'verification_handoff_facts','verificati"
        "on_launch_facts','verification_method_ap"
        "plicabilities','verification_preparation"
        "s','verification_run_identities','verifi"
        "cation_run_versions','verification_windo"
        "w_proposals','work_requests','proposals'"
        ",'proposal_items','proposal_item_version"
        "s','proposal_revisions','proposal_source"
        "s','proposal_submissions','proposal_deci"
        "sions','project_open_items','category_kn"
        "owledge_entries','category_knowledge_cur"
        "rent','product_target_segments','paramet"
        "er_versions','parameter_current','promot"
        "ion_proofs','evidence_links','claim_with"
        "drawals','manufacturing_baseline_publica"
        "tions','manufacturing_publication_curren"
        "ts','manufacturing_publication_documents"
        "','native_pilot_runs','native_pilot_curr"
        "ents','native_pilot_observations','relea"
        "se_packages','release_package_currents',"
        "'release_decisions','release_policy_fact"
        "s','release_policy_currents','external_h"
        "andoff_authorizations','external_deliver"
        "y_intents','external_receipts','external"
        "_handoff_currents','release_exception_de"
        "cisions','release_exception_currents','w"
        "ork_commitment_reviews','work_commitment"
        "_review_currents','work_task_versions','"
        "work_task_currents','work_commitment_ver"
        "sions','work_commitment_currents','proje"
        "ct_status_updates','external_wait_versio"
        "ns','external_wait_currents','project_ri"
        "sk_followups','project_risk_followup_cur"
        "rents','knowledge_candidate_versions','k"
        "nowledge_candidate_currents','knowledge_"
        "applicability_assessments','knowledge_ru"
        "le_versions','knowledge_rule_currents','"
        "field_feedback_versions','field_feedback"
        "_currents','field_response_records','kno"
        "wledge_answer_reviews','knowledge_gap_su"
        "bmissions'] ELSE ARRAY[\n  'artifact_vers"
        "ions','claims','definition_revisions','d"
        "efinition_sources','definition_specs',\n "
        " 'proposals','proposal_items','proposal_"
        "item_versions','proposal_submissions','p"
        "roposal_decisions',\n  'category_knowledg"
        "e_entries','category_knowledge_current',"
        "'parameter_versions','parameter_current'"
        ",\n  'evidence_links','promotion_proofs',"
        "'native_pilot_runs','native_pilot_curren"
        "ts','native_pilot_observations','release"
        "_packages','release_package_currents','r"
        "elease_decisions','release_policy_facts'"
        ",'release_policy_currents','external_han"
        "doff_authorizations','external_delivery_"
        "intents','external_receipts','external_h"
        "andoff_currents','release_exception_deci"
        "sions','release_exception_currents','wor"
        "k_commitment_reviews','work_commitment_r"
        "eview_currents','work_task_versions','wo"
        "rk_task_currents','work_commitment_versi"
        "ons','work_commitment_currents','project"
        "_status_updates','external_wait_versions"
        "','external_wait_currents','project_risk"
        "_followups','project_risk_followup_curre"
        "nts','knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_ap"
        "plicability_assessments','knowledge_rule"
        "_versions','knowledge_rule_currents','fi"
        "eld_feedback_versions','field_feedback_c"
        "urrents','field_response_records','knowl"
        "edge_answer_reviews','knowledge_gap_subm"
        "issions'] END LOOP\n  FOR payload IN EXEC"
        "UTE CASE WHEN name=ANY(ARRAY['audit_entr"
        "ies','outbox_events','request_keys'])\n  "
        " THEN format('SELECT to_jsonb(x) FROM pu"
        'blic.%I x JOIN public.action_receipts r '
        'ON r.id=x.receipt_id AND r.tenant_id=x.t'
        'enant_id WHERE x.tenant_id=$1 AND r.cate'
        "gory_id=$2',name)\n   ELSE format('SELECT"
        ' to_jsonb(x) FROM public.%I x WHERE tena'
        'nt_id=$1 AND category_id=$2 AND ($3 IS N'
        "ULL OR %I=ANY($3))',name,\n    CASE name "
        "WHEN 'category_knowledge_current' THEN '"
        "lineage_id'\n     WHEN 'parameter_current"
        "' THEN 'parameter_id' ELSE 'id' END)\n   "
        'END USING t,c,identities LOOP\n   IF (pay'
        "load->>'receipt_id')::uuid=ANY(controls)"
        " OR\n    (name='action_receipts' AND payl"
        "oad->>'operation' LIKE 'evidence.lifecyc"
        "le.%') THEN CONTINUE; END IF;\n   table_n"
        "ame=name;\n   node_id=CASE name WHEN 'cat"
        "egory_knowledge_current' THEN (payload->"
        ">'lineage_id')::uuid\n    WHEN 'parameter"
        "_current' THEN (payload->>'parameter_id'"
        ")::uuid ELSE (payload->>'id')::uuid END;"
        '\n   IF identities IS NULL THEN links=pub'
        'lic.m3_lifecycle_row_links(t,c,name,payl'
        'oad);\n   ELSE links=public.m3_lifecycle_'
        'source_links(t,c,name,payload); END IF;\n'
        "   -- Preserve predecessor's conservativ"
        'e legacy graph; M3-only nodes use\n   -- '
        'strictly typed/relational links. Root lo'
        'okup never uses free-text UUIDs.\n   IF i'
        "dentities IS NULL AND name<>ALL(ARRAY['n"
        "ative_pilot_runs','native_pilot_currents"
        "','native_pilot_observations','release_p"
        "ackages','release_package_currents','rel"
        "ease_decisions','release_policy_facts','"
        "release_policy_currents','external_hando"
        "ff_authorizations','external_delivery_in"
        "tents','external_receipts','external_han"
        "doff_currents','release_exception_decisi"
        "ons','release_exception_currents','work_"
        "commitment_reviews','work_commitment_rev"
        "iew_currents','work_task_versions','work"
        "_task_currents','work_commitment_version"
        "s','work_commitment_currents','project_s"
        "tatus_updates','external_wait_versions',"
        "'external_wait_currents','project_risk_f"
        "ollowups','project_risk_followup_current"
        "s','manufacturing_baseline_publications'"
        ",'manufacturing_publication_currents','m"
        "anufacturing_publication_documents','pro"
        "posals','proposal_items','proposal_item_"
        "versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','propos"
        "al_decisions','project_open_items','cate"
        "gory_knowledge_entries','category_knowle"
        "dge_current','product_target_segments','"
        "parameter_versions','parameter_current',"
        "'promotion_proofs','evidence_links','cla"
        "im_withdrawals','knowledge_candidate_ver"
        "sions','knowledge_candidate_currents','k"
        "nowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_cu"
        "rrents','field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds','knowledge_answer_reviews','knowled"
        "ge_gap_submissions']) THEN\n    links=lin"
        'ks || public.kernel_lifecycle_links(name'
        ',payload);\n   END IF;\n   RETURN NEXT;\n  '
        'END LOOP;\n END LOOP;\n\n -- Read exactly t'
        'he retained metadata, never Delivery.pay'
        'load. One personal\n -- answer may appear'
        ' in several categories, each with its ow'
        'n source subset.\n FOR payload IN\n  SELEC'
        "T jsonb_build_object('id',d.id,'tenant_i"
        "d',d.tenant_id,\n   'content_kind',d.cont"
        "ent_kind,'source_dependencies',d.source_"
        'dependencies)\n  FROM public.dingtalk_del'
        'iveries d\n  WHERE d.tenant_id=t AND d.co'
        "ntent_kind='answer'\n   AND (identities I"
        'S NULL OR d.id=ANY(identities))\n   AND E'
        'XISTS(SELECT 1 FROM jsonb_array_elements'
        '(d.source_dependencies) dependency\n    W'
        "HERE dependency->>'category_id'=c::text)"
        "\n LOOP\n  table_name='dingtalk_deliveries"
        "'; node_id=(payload->>'id')::uuid;\n  lin"
        'ks=public.m3_lifecycle_source_links(t,c,'
        'table_name,payload);\n  RETURN NEXT;\n END'
        ' LOOP;\n\n -- Summary copies have a real c'
        'ategory. Read only immutable reference m'
        'etadata.\n FOR payload IN SELECT jsonb_bu'
        "ild_object('id',d.id,'tenant_id',d.tenan"
        "t_id,\n   'category_id',d.category_id,'ru"
        "n_id',d.run_id,'source_ids',d.source_ids"
        ')\n  FROM public.dingtalk_summary_deliver'
        'ies d\n  WHERE d.tenant_id=t AND d.catego'
        'ry_id=c AND (identities IS NULL OR d.id='
        "ANY(identities))\n LOOP\n  table_name='din"
        "gtalk_summary_deliveries'; node_id=(payl"
        "oad->>'id')::uuid;\n  links=public.m3_lif"
        'ecycle_source_links(t,c,table_name,paylo'
        'ad);\n  RETURN NEXT;\n END LOOP;\nEND;\n$fun'
        'ction$\n'
    ),
}

TABLE_SQL = (
    '\nCREATE TABLE dingtalk_summary_deliverie'
    's (\n\tcategory_id UUID NOT NULL, \n\towner_'
    'id UUID NOT NULL, \n\trun_id UUID NOT NULL'
    ', \n\tattempt_id UUID NOT NULL, \n\tservice_'
    'grant_id UUID NOT NULL, \n\tpublished_vers'
    'ion_id UUID NOT NULL, \n\tapplication_id U'
    'UID NOT NULL, \n\tapplication_revision INT'
    'EGER NOT NULL, \n\tbinding_id UUID NOT NUL'
    'L, \n\tbinding_epoch INTEGER NOT NULL, \n\tc'
    'ancel_epoch INTEGER NOT NULL, \n\tsummary_'
    'sha256 VARCHAR(64) NOT NULL, \n\tsource_id'
    's UUID[] NOT NULL, \n\trequest_key UUID NO'
    'T NULL, \n\tpayload JSONB NOT NULL, \n\tpayl'
    'oad_sha256 VARCHAR(64) NOT NULL, \n\tstate'
    ' VARCHAR(24) NOT NULL, \n\tp26 JSONB, \n\tpr'
    'ovider_receipt JSONB, \n\terror_code VARCH'
    'AR(80), \n\tattempts INTEGER NOT NULL, \n\ts'
    'end_attempt_id UUID, \n\tsend_started_at T'
    'IMESTAMP WITH TIME ZONE, \n\tid UUID NOT N'
    'ULL, \n\ttenant_id UUID NOT NULL, \n\tcreate'
    'd_at TIMESTAMP WITH TIME ZONE NOT NULL, '
    '\n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id,'
    ' id), \n\tUNIQUE (tenant_id, run_id), \n\tUN'
    'IQUE (tenant_id, request_key), \n\tFOREIGN'
    ' KEY(tenant_id, category_id) REFERENCES '
    'categories (tenant_id, id), \n\tFOREIGN KE'
    'Y(tenant_id, owner_id) REFERENCES princi'
    'pals (tenant_id, id), \n\tFOREIGN KEY(tena'
    'nt_id, run_id) REFERENCES agent_runs (te'
    'nant_id, id), \n\tFOREIGN KEY(tenant_id, a'
    'ttempt_id) REFERENCES automation_service'
    '_attempts (tenant_id, id), \n\tFOREIGN KEY'
    '(tenant_id, service_grant_id) REFERENCES'
    ' automation_service_grants (tenant_id, i'
    'd), \n\tFOREIGN KEY(tenant_id, published_v'
    'ersion_id) REFERENCES automation_rule_ve'
    'rsions (tenant_id, id), \n\tFOREIGN KEY(te'
    'nant_id, application_id) REFERENCES ding'
    'talk_applications (tenant_id, id), \n\tFOR'
    'EIGN KEY(tenant_id, binding_id) REFERENC'
    'ES dingtalk_account_bindings (tenant_id,'
    ' id), \n\tCHECK (application_revision>0 AN'
    'D binding_epoch>0 AND cancel_epoch>=0), '
    "\n\tCHECK (summary_sha256 ~ '^[a-f0-9]{64}"
    "$' AND payload_sha256 ~ '^[a-f0-9]{64}$'"
    "), \n\tCHECK (state IN ('planned','sending"
    "','delivered','unknown','blocked','cance"
    "lled')), \n\tCHECK (attempts>=0 AND (state"
    " NOT IN ('sending','delivered','unknown'"
    ') OR p26 IS NOT NULL)), \n\tCHECK (jsonb_t'
    "ypeof(payload)='object' AND payload->>'t"
    "arget_kind'='direct')\n)\n\n"
)

BASE_SQL = (
    (
        '\nCREATE TABLE dingtalk_summary_deliverie'
        's (\n\tcategory_id UUID NOT NULL, \n\towner_'
        'id UUID NOT NULL, \n\trun_id UUID NOT NULL'
        ', \n\tattempt_id UUID NOT NULL, \n\tservice_'
        'grant_id UUID NOT NULL, \n\tpublished_vers'
        'ion_id UUID NOT NULL, \n\tapplication_id U'
        'UID NOT NULL, \n\tapplication_revision INT'
        'EGER NOT NULL, \n\tbinding_id UUID NOT NUL'
        'L, \n\tbinding_epoch INTEGER NOT NULL, \n\tc'
        'ancel_epoch INTEGER NOT NULL, \n\tsummary_'
        'sha256 VARCHAR(64) NOT NULL, \n\tsource_id'
        's UUID[] NOT NULL, \n\trequest_key UUID NO'
        'T NULL, \n\tpayload JSONB NOT NULL, \n\tpayl'
        'oad_sha256 VARCHAR(64) NOT NULL, \n\tstate'
        ' VARCHAR(24) NOT NULL, \n\tp26 JSONB, \n\tpr'
        'ovider_receipt JSONB, \n\terror_code VARCH'
        'AR(80), \n\tattempts INTEGER NOT NULL, \n\ts'
        'end_attempt_id UUID, \n\tsend_started_at T'
        'IMESTAMP WITH TIME ZONE, \n\tid UUID NOT N'
        'ULL, \n\ttenant_id UUID NOT NULL, \n\tcreate'
        'd_at TIMESTAMP WITH TIME ZONE NOT NULL, '
        '\n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id,'
        ' id), \n\tUNIQUE (tenant_id, run_id), \n\tUN'
        'IQUE (tenant_id, request_key), \n\tFOREIGN'
        ' KEY(tenant_id, category_id) REFERENCES '
        'categories (tenant_id, id), \n\tFOREIGN KE'
        'Y(tenant_id, owner_id) REFERENCES princi'
        'pals (tenant_id, id), \n\tFOREIGN KEY(tena'
        'nt_id, run_id) REFERENCES agent_runs (te'
        'nant_id, id), \n\tFOREIGN KEY(tenant_id, a'
        'ttempt_id) REFERENCES automation_service'
        '_attempts (tenant_id, id), \n\tFOREIGN KEY'
        '(tenant_id, service_grant_id) REFERENCES'
        ' automation_service_grants (tenant_id, i'
        'd), \n\tFOREIGN KEY(tenant_id, published_v'
        'ersion_id) REFERENCES automation_rule_ve'
        'rsions (tenant_id, id), \n\tFOREIGN KEY(te'
        'nant_id, application_id) REFERENCES ding'
        'talk_applications (tenant_id, id), \n\tFOR'
        'EIGN KEY(tenant_id, binding_id) REFERENC'
        'ES dingtalk_account_bindings (tenant_id,'
        ' id), \n\tCHECK (application_revision>0 AN'
        'D binding_epoch>0 AND cancel_epoch>=0), '
        "\n\tCHECK (summary_sha256 ~ '^[a-f0-9]{64}"
        "$' AND payload_sha256 ~ '^[a-f0-9]{64}$'"
        "), \n\tCHECK (state IN ('planned','sending"
        "','delivered','unknown','blocked','cance"
        "lled')), \n\tCHECK (attempts>=0 AND (state"
        " NOT IN ('sending','delivered','unknown'"
        ') OR p26 IS NOT NULL)), \n\tCHECK (jsonb_t'
        "ypeof(payload)='object' AND payload->>'t"
        "arget_kind'='direct')\n)\n\n"
    ),
    (
        'ALTER TABLE public.dingtalk_summary_deli'
        'veries ENABLE ROW LEVEL SECURITY'
    ),
    (
        'ALTER TABLE public.dingtalk_summary_deli'
        'veries FORCE ROW LEVEL SECURITY'
    ),
    (
        'REVOKE ALL ON public.dingtalk_summary_de'
        'liveries FROM PUBLIC,pdos_agent,pdos_nex'
        't_auth,pdos_next_dispatch'
    ),
    (
        'GRANT SELECT,INSERT,UPDATE ON public.din'
        'gtalk_summary_deliveries TO pdos_next_ap'
        'p'
    ),
    (
        'GRANT SELECT(id,tenant_id,category_id,ow'
        'ner_id,run_id,attempt_id,service_grant_i'
        'd,published_version_id,application_id,ap'
        'plication_revision,binding_id,binding_ep'
        'och,cancel_epoch,source_ids,state,error_'
        'code,created_at),UPDATE(state,error_code'
        ') ON public.dingtalk_summary_deliveries '
        'TO pdos_next_owner'
    ),
    (
        'GRANT SELECT(id,tenant_id,application_id'
        ',binding_id) ON public.dingtalk_summary_'
        'deliveries TO pdos_next_dingtalk_mainten'
        'ance'
    ),
    (
        'CREATE POLICY summary_owner_metadata ON '
        'public.dingtalk_summary_deliveries TO pd'
        'os_next_owner USING (tenant_id=nullif(cu'
        "rrent_setting('pdos.tenant_id',true),'')"
        '::uuid) WITH CHECK (tenant_id=nullif(cur'
        "rent_setting('pdos.tenant_id',true),''):"
        ':uuid)'
    ),
    (
        'CREATE POLICY summary_channel_metadata O'
        'N public.dingtalk_summary_deliveries FOR'
        ' SELECT TO pdos_next_dingtalk_maintenanc'
        'e USING (tenant_id=nullif(current_settin'
        "g('pdos.tenant_id',true),'')::uuid)"
    ),
    (
        'CREATE POLICY summary_read ON public.din'
        'gtalk_summary_deliveries FOR SELECT TO p'
        'dos_next_app USING (tenant_id=nullif(cur'
        "rent_setting('pdos.tenant_id',true),''):"
        ':uuid AND ((owner_id=scope_requester() A'
        'ND scope_actor()=scope_requester()) OR d'
        'ingtalk_service(tenant_id,application_id'
        ')))'
    ),
    (
        'CREATE POLICY summary_insert ON public.d'
        'ingtalk_summary_deliveries FOR INSERT TO'
        ' pdos_next_app WITH CHECK (tenant_id=nul'
        "lif(current_setting('pdos.tenant_id',tru"
        "e),'')::uuid AND dingtalk_service(tenant"
        '_id,application_id))'
    ),
    (
        'CREATE POLICY summary_update ON public.d'
        'ingtalk_summary_deliveries FOR UPDATE TO'
        ' pdos_next_app USING (tenant_id=nullif(c'
        "urrent_setting('pdos.tenant_id',true),''"
        ')::uuid AND dingtalk_service(tenant_id,a'
        'pplication_id)) WITH CHECK (tenant_id=nu'
        "llif(current_setting('pdos.tenant_id',tr"
        "ue),'')::uuid AND dingtalk_service(tenan"
        't_id,application_id))'
    ),
    (
        'CREATE POLICY summary_dispatch_metadata '
        'ON public.dingtalk_applications FOR SELE'
        'CT TO pdos_next_owner USING (tenant_id=n'
        "ullif(current_setting('pdos.tenant_id',t"
        "rue),'')::uuid)"
    ),
    (
        'CREATE POLICY summary_dispatch_metadata '
        'ON public.dingtalk_account_bindings FOR '
        'SELECT TO pdos_next_owner USING (tenant_'
        "id=nullif(current_setting('pdos.tenant_i"
        "d',true),'')::uuid)"
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_summary'
        '_reference(t uuid, rid uuid)\nRETURNS TAB'
        'LE(tenant_id uuid,category_id uuid,owner'
        '_id uuid,run_id uuid,attempt_id uuid,\n s'
        'ervice_grant_id uuid,published_version_i'
        'd uuid,application_id uuid,application_r'
        'evision integer,\n binding_id uuid,bindin'
        'g_epoch integer,cancel_epoch integer,ser'
        'vice_id uuid)\nLANGUAGE sql STABLE SECURI'
        'TY DEFINER SET search_path=pg_catalog,pu'
        'blic,pg_temp AS $summary$\n SELECT r.tena'
        'nt_id,r.category_id,r.requester_id,r.id,'
        'a.id,g.id,v.id,app.id,app.revision,\n b.i'
        'd,b.epoch,r.cancel_epoch,app.service_pri'
        'ncipal_id\n FROM public.agent_runs r\n JOI'
        'N public.automation_service_attempts a O'
        'N a.tenant_id=r.tenant_id AND a.run_id=r'
        '.id\n  AND a.owner_id=r.requester_id AND '
        'a.writer_id=r.writer_id AND a.category_i'
        "d=r.category_id\n  AND a.state='admitted'"
        ' AND a.request_digest=r.intent_digest\n J'
        'OIN public.automation_service_grants g O'
        'N g.tenant_id=a.tenant_id AND g.id=a.ser'
        'vice_grant_id\n  AND g.owner_id=a.owner_i'
        'd AND g.writer_id=a.writer_id AND g.cate'
        'gory_id=a.category_id\n  AND g.rule_id=a.'
        'rule_id AND g.published_version_id=a.pub'
        'lished_version_id\n JOIN public.automatio'
        'n_rule_versions v ON v.tenant_id=g.tenan'
        't_id AND v.id=g.published_version_id\n  A'
        'ND v.rule_id=g.rule_id AND v.owner_id=g.'
        'owner_id AND v.category_id=g.category_id'
        '\n  AND v.actor_id=g.owner_id AND v.reque'
        'ster_id=g.owner_id AND v.receipt_id=g.re'
        "ceipt_id\n  AND v.action='activate' AND v"
        ".state='active' AND v.operation='ai.auto"
        "mation.activate'\n JOIN public.action_rec"
        'eipts rec ON rec.tenant_id=v.tenant_id A'
        'ND rec.id=v.receipt_id\n  AND rec.categor'
        'y_id=v.category_id AND rec.subject_id=v.'
        'id AND rec.subject_revision=v.revision\n '
        " AND rec.subject_type='automation_rule' "
        'AND rec.operation=v.operation\n  AND rec.'
        'actor_id=v.owner_id AND rec.requester_id'
        '=v.owner_id AND rec.command_id=v.command'
        '_id\n  AND rec.confirmation_id=v.confirma'
        'tion_id AND rec.confirmation_id IS NOT N'
        'ULL\n  AND rec.request_digest=v.request_d'
        'igest AND rec.intent_digest=v.intent_dig'
        'est\n JOIN public.dingtalk_account_bindin'
        'gs b ON b.tenant_id=r.tenant_id AND b.ow'
        "ner_id=r.requester_id\n  AND v.spec#>>'{p"
        "ersonal_summary,dingtalk_binding_id}'=b."
        'id::text\n JOIN public.dingtalk_applicati'
        'ons app ON app.tenant_id=b.tenant_id AND'
        ' app.id=b.application_id\n WHERE t=nullif'
        "(current_setting('pdos.tenant_id',true),"
        "'')::uuid AND r.tenant_id=t AND r.id=rid"
        "\n AND r.trigger='automation_service' AND"
        ' r.category_id IS NOT NULL\n AND (public.'
        'scope_actor() IS NULL AND public.scope_r'
        'equester() IS NULL\n  OR public.scope_act'
        'or()=public.scope_requester() AND public'
        '.scope_requester()=r.requester_id\n  OR p'
        'ublic.scope_actor()=public.scope_request'
        'er() AND public.scope_actor()=app.servic'
        'e_principal_id)\n$summary$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_summary_r'
        'eference(uuid,uuid) OWNER TO pdos_next_o'
        'wner'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_s'
        'ummary_reference(uuid,uuid) FROM PUBLIC,'
        'pdos_next_app,pdos_agent,pdos_next_auth,'
        'pdos_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_summary_reference(uuid,uuid) TO pdos_n'
        'ext_app,pdos_next_dispatch'
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_pending'
        '_summaries(t uuid, maximum integer)\nRETU'
        'RNS TABLE(run_id uuid) LANGUAGE sql STAB'
        'LE SECURITY DEFINER\nSET search_path=pg_c'
        'atalog,public,pg_temp AS $summary$\n SELE'
        'CT r.id FROM public.agent_runs r\n JOIN p'
        'ublic.automation_service_attempts a ON a'
        '.tenant_id=r.tenant_id AND a.run_id=r.id'
        '\n JOIN public.automation_rule_versions v'
        ' ON v.tenant_id=a.tenant_id AND v.id=a.p'
        'ublished_version_id\n CROSS JOIN LATERAL '
        'public.dingtalk_summary_reference(t,r.id'
        ') ref\n WHERE r.tenant_id=t AND t=nullif('
        "current_setting('pdos.tenant_id',true),'"
        "')::uuid\n AND r.state IN ('completed','p"
        "artial') AND r.reverted_at IS NULL\n AND "
        "v.spec#>>'{personal_summary,dingtalk_bin"
        "ding_id}' IS NOT NULL\n AND NOT EXISTS(SE"
        'LECT 1 FROM public.dingtalk_summary_deli'
        'veries d\n  WHERE d.tenant_id=r.tenant_id'
        ' AND d.run_id=r.id)\n ORDER BY r.created_'
        'at,r.id LIMIT greatest(1,least(maximum,1'
        '00))\n$summary$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_pending_s'
        'ummaries(uuid,integer) OWNER TO pdos_nex'
        't_owner'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_p'
        'ending_summaries(uuid,integer) FROM PUBL'
        'IC,pdos_next_app,pdos_agent,pdos_next_au'
        'th,pdos_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_pending_summaries(uuid,integer) TO pdo'
        's_next_dispatch'
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_lock_su'
        'mmary_binding(t uuid, did uuid) RETURNS '
        'void\nLANGUAGE plpgsql SECURITY DEFINER S'
        'ET search_path=pg_catalog,public,pg_temp'
        ' AS $summary$\nDECLARE app uuid; binding '
        'uuid;\nBEGIN\n SELECT d.application_id,d.b'
        'inding_id INTO app,binding FROM public.d'
        'ingtalk_summary_deliveries d\n WHERE d.te'
        'nant_id=t AND d.id=did AND t=nullif(curr'
        "ent_setting('pdos.tenant_id',true),'')::"
        'uuid;\n IF NOT FOUND OR NOT public.dingta'
        'lk_service(t,app) THEN\n  RAISE EXCEPTION'
        " 'Summary delivery service binding requi"
        "red' USING ERRCODE='42501'; END IF;\n PER"
        'FORM 1 FROM public.dingtalk_applications'
        ' a WHERE a.tenant_id=t AND a.id=app FOR '
        'UPDATE;\n PERFORM 1 FROM public.dingtalk_'
        'account_bindings b WHERE b.tenant_id=t A'
        'ND b.id=binding FOR UPDATE;\nEND;\n$summar'
        'y$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_lock_summ'
        'ary_binding(uuid,uuid) OWNER TO pdos_nex'
        't_dingtalk_maintenance'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_l'
        'ock_summary_binding(uuid,uuid) FROM PUBL'
        'IC,pdos_next_app,pdos_agent,pdos_next_au'
        'th,pdos_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_lock_summary_binding(uuid,uuid) TO pdo'
        's_next_app'
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_summary'
        '_cancel_lost(t uuid,rid uuid) RETURNS bo'
        'olean\nLANGUAGE plpgsql SECURITY DEFINER '
        'SET search_path=pg_catalog,public,pg_tem'
        'p AS $summary$\nDECLARE meta record;\nBEGI'
        'N\n SELECT * INTO meta FROM public.dingta'
        'lk_summary_reference(t,rid);\n IF NOT FOU'
        'ND THEN RETURN true; END IF;\n IF EXISTS('
        'SELECT 1 FROM public.dingtalk_applicatio'
        'ns a\n  JOIN public.dingtalk_account_bind'
        'ings b ON b.tenant_id=a.tenant_id AND b.'
        'application_id=a.id\n  JOIN public.princi'
        'pals owner ON owner.tenant_id=a.tenant_i'
        'd AND owner.id=b.owner_id\n  JOIN public.'
        'principals service ON service.tenant_id='
        'a.tenant_id AND service.id=a.service_pri'
        'ncipal_id\n  JOIN public.agent_runs r ON '
        'r.tenant_id=a.tenant_id AND r.id=rid\n  W'
        'HERE a.tenant_id=t AND a.id=meta.applica'
        'tion_id AND a.active AND b.id=meta.bindi'
        'ng_id AND b.active\n  AND owner.active AN'
        "D owner.kind='human' AND service.active "
        "AND service.kind='agent'\n  AND r.state I"
        "N ('completed','partial') AND r.reverted"
        '_at IS NULL) THEN RETURN false; END IF;\n'
        ' UPDATE public.dingtalk_summary_deliveri'
        "es SET state='cancelled',error_code='CAN"
        "CELLED_RUN'\n WHERE tenant_id=t AND run_i"
        "d=rid AND state='planned';\n RETURN true;"
        '\nEND;\n$summary$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_summary_c'
        'ancel_lost(uuid,uuid) OWNER TO pdos_next'
        '_owner'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_s'
        'ummary_cancel_lost(uuid,uuid) FROM PUBLI'
        'C,pdos_next_app,pdos_agent,pdos_next_aut'
        'h,pdos_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_summary_cancel_lost(uuid,uuid) TO pdos'
        '_next_dispatch'
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_summary'
        '_identity_guard() RETURNS trigger\nLANGUA'
        'GE plpgsql SECURITY DEFINER SET search_p'
        'ath=pg_catalog,public,pg_temp AS $summar'
        'y$\nDECLARE meta record;\nBEGIN\n IF TG_OP='
        "'DELETE' THEN RAISE EXCEPTION 'Summary d"
        "elivery history is retained' USING ERRCO"
        "DE='23514'; END IF;\n IF TG_OP='UPDATE' T"
        "HEN\n  IF to_jsonb(NEW)-ARRAY['state','p2"
        "6','provider_receipt','error_code','atte"
        "mpts','send_attempt_id','send_started_at"
        "']\n   IS DISTINCT FROM to_jsonb(OLD)-ARR"
        "AY['state','p26','provider_receipt','err"
        "or_code','attempts','send_attempt_id','s"
        "end_started_at'] THEN\n   RAISE EXCEPTION"
        " 'Summary delivery fixed identity is imm"
        "utable' USING ERRCODE='23514'; END IF;\n "
        " IF OLD.state IN ('delivered','blocked',"
        "'cancelled') AND NEW IS DISTINCT FROM OL"
        "D THEN\n   RAISE EXCEPTION 'Summary deliv"
        "ery terminal outcome is immutable' USING"
        " ERRCODE='23514'; END IF;\n  IF NEW.attem"
        'pts IS DISTINCT FROM OLD.attempts AND NO'
        "T\n   (OLD.state='planned' AND NEW.state="
        "'sending' AND OLD.attempts=0 AND NEW.att"
        "empts=1) THEN\n   RAISE EXCEPTION 'Unknow"
        "n summary delivery must not be resent' U"
        "SING ERRCODE='23514'; END IF;\n  RETURN N"
        'EW;\n END IF;\n SELECT * INTO meta FROM pu'
        'blic.dingtalk_summary_reference(NEW.tena'
        'nt_id,NEW.run_id);\n IF NOT FOUND OR ROW('
        'NEW.category_id,NEW.owner_id,NEW.attempt'
        '_id,NEW.service_grant_id,\n   NEW.publish'
        'ed_version_id,NEW.application_id,NEW.app'
        'lication_revision,NEW.binding_id,\n   NEW'
        '.binding_epoch,NEW.cancel_epoch) IS DIST'
        'INCT FROM ROW(meta.category_id,meta.owne'
        'r_id,\n   meta.attempt_id,meta.service_gr'
        'ant_id,meta.published_version_id,meta.ap'
        'plication_id,\n   meta.application_revisi'
        'on,meta.binding_id,meta.binding_epoch,me'
        'ta.cancel_epoch)\n  OR public.scope_actor'
        '() IS DISTINCT FROM meta.service_id\n  OR'
        ' public.scope_requester() IS DISTINCT FR'
        'OM meta.service_id THEN\n  RAISE EXCEPTIO'
        "N 'Summary delivery requires its origina"
        "l T1 service Run' USING ERRCODE='23514';"
        " END IF;\n IF NEW.state NOT IN ('planned'"
        ",'blocked','cancelled') OR NEW.attempts<"
        '>0\n  OR NEW.send_attempt_id IS NOT NULL '
        'OR NEW.p26 IS NOT NULL OR NEW.provider_r'
        'eceipt IS NOT NULL THEN\n  RAISE EXCEPTIO'
        "N 'Summary delivery starts with no netwo"
        "rk attempt' USING ERRCODE='23514'; END I"
        'F;\n RETURN NEW;\nEND;\n$summary$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_summary_i'
        'dentity_guard() OWNER TO pdos_next_owner'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_s'
        'ummary_identity_guard() FROM PUBLIC,pdos'
        '_next_app,pdos_agent,pdos_next_auth,pdos'
        '_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_summary_identity_guard() TO pdos_next_'
        'owner'
    ),
    (
        '\nCREATE FUNCTION public.dingtalk_summary'
        '_reference_clock() RETURNS trigger\nLANGU'
        'AGE plpgsql SECURITY DEFINER SET search_'
        'path=pg_catalog,public,pg_temp AS $summa'
        'ry$\nDECLARE payload jsonb; roots uuid[];'
        " model_id uuid;\nBEGIN\n IF TG_OP='UPDATE'"
        " THEN RETURN NEW; END IF;\n IF TG_OP='DEL"
        "ETE' THEN RETURN OLD; END IF;\n IF NEW.te"
        'nant_id IS DISTINCT FROM nullif(current_'
        "setting('pdos.tenant_id',true),'')::uuid"
        " THEN\n  RAISE EXCEPTION 'Summary retenti"
        "on tenant mismatch' USING ERRCODE='23514"
        "'; END IF;\n PERFORM 1 FROM public.catego"
        'ries c WHERE c.tenant_id=NEW.tenant_id A'
        'ND c.id=NEW.category_id FOR UPDATE;\n IF '
        "NOT FOUND THEN RAISE EXCEPTION 'Summary "
        "retention category missing' USING ERRCOD"
        "E='23514'; END IF;\n payload=jsonb_build_"
        "object('tenant_id',NEW.tenant_id,'catego"
        "ry_id',NEW.category_id,\n  'run_id',NEW.r"
        "un_id,'source_ids',NEW.source_ids);\n roo"
        'ts=public.m3_lifecycle_roots(NEW.tenant_'
        "id,NEW.category_id,'dingtalk_summary_del"
        "iveries',payload);\n FOR model_id IN SELE"
        'CT DISTINCT id FROM (\n  SELECT product_i'
        'd AS id FROM public.uploaded_originals o'
        '\n   WHERE o.tenant_id=NEW.tenant_id AND '
        'o.category_id=NEW.category_id AND o.id=A'
        'NY(roots)\n  UNION SELECT product_id FROM'
        ' public.lifecycle_objects o\n   WHERE o.t'
        'enant_id=NEW.tenant_id AND o.category_id'
        '=NEW.category_id AND o.id=ANY(roots)\n  U'
        'NION SELECT product_id FROM public.uploa'
        'd_attempts o\n   WHERE o.tenant_id=NEW.te'
        'nant_id AND o.category_id=NEW.category_i'
        'd AND o.id=ANY(roots)\n ) affected WHERE '
        'id IS NOT NULL ORDER BY id LOOP\n  UPDATE'
        ' public.products p SET lifecycle_epoch=p'
        '.lifecycle_epoch+1\n   WHERE p.tenant_id='
        'NEW.tenant_id AND p.category_id=NEW.cate'
        'gory_id AND p.id=model_id;\n  IF NOT FOUN'
        "D THEN RAISE EXCEPTION 'Summary retentio"
        "n product missing' USING ERRCODE='23514'"
        '; END IF;\n END LOOP;\n UPDATE public.cate'
        'gories c SET lifecycle_epoch=c.lifecycle'
        '_epoch+1\n  WHERE c.tenant_id=NEW.tenant_'
        'id AND c.id=NEW.category_id;\n IF EXISTS('
        'SELECT 1 FROM public.lifecycle_objects o'
        ' WHERE o.tenant_id=NEW.tenant_id\n  AND o'
        '.category_id=NEW.category_id AND o.id=AN'
        "Y(roots)\n  AND (o.state->'value'->>'pend"
        "ing_intent_id' IS NOT NULL\n   OR o.state"
        "->'value'->>'disposition' IN ('quarantin"
        "ed','unknown','purged'))) THEN\n  RAISE E"
        "XCEPTION 'Pending original prohibits sum"
        "mary body copy'\n   USING ERRCODE='23514'"
        ",CONSTRAINT='m3_source_reference_fence';"
        ' END IF;\n RETURN NEW;\nEND;\n$summary$;\n'
    ),
    (
        'ALTER FUNCTION public.dingtalk_summary_r'
        'eference_clock() OWNER TO pdos_next_owne'
        'r'
    ),
    (
        'REVOKE ALL ON FUNCTION public.dingtalk_s'
        'ummary_reference_clock() FROM PUBLIC,pdo'
        's_next_app,pdos_agent,pdos_next_auth,pdo'
        's_next_dispatch'
    ),
    (
        'GRANT EXECUTE ON FUNCTION public.dingtal'
        'k_summary_reference_clock() TO pdos_next'
        '_owner'
    ),
    (
        'CREATE TRIGGER summary_identity BEFORE I'
        'NSERT OR UPDATE OR DELETE ON public.ding'
        'talk_summary_deliveries FOR EACH ROW EXE'
        'CUTE FUNCTION public.dingtalk_summary_id'
        'entity_guard()'
    ),
)

LIFECYCLE_UP_SQL = (
    (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_source_links(t uuid, c uuid, tabl'
        'e_name text, payload jsonb)\n RETURNS uui'
        'd[]\n LANGUAGE plpgsql\n STABLE SECURITY D'
        "EFINER\n SET search_path TO 'pg_catalog',"
        " 'public', 'pg_temp'\nAS $function$\nDECLA"
        "RE links uuid[]='{}'; extra uuid[]; key "
        'text; keys text[]; item jsonb; container'
        ' jsonb;\n target_kind text; referenced_ta'
        'rget uuid; referenced_version integer;\nB'
        "EGIN\n IF table_name='agent_runs' THEN RE"
        'TURN public.kernel_lifecycle_links(table'
        '_name,payload); END IF;\n -- Only actual '
        'top-level relation columns establish raw'
        ' UUID edges. Arbitrary\n -- content dicti'
        'onaries are not relational rows, even if'
        ' an extra key happens\n -- to be named so'
        'urce_id or item_id.\n keys=CASE table_nam'
        "e\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRA"
        "Y['artifact_id','snapshot_id']\n  WHEN 'd"
        "efinition_revisions' THEN ARRAY['derived"
        "_from_definition_id','parent_definition_"
        "id',\n   'source_proposal_id','source_sub"
        "mission_id']\n  WHEN 'definition_sources'"
        " THEN ARRAY['artifact_id']\n  WHEN 'defin"
        "ition_specs' THEN ARRAY[]::text[]\n  WHEN"
        " 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN"
        " 'proposal_items' THEN ARRAY[]::text[]\n "
        " WHEN 'proposal_item_versions' THEN ARRA"
        "Y[]::text[]\n  WHEN 'proposal_revisions' "
        "THEN ARRAY['proposal_id']\n  WHEN 'propos"
        "al_sources' THEN ARRAY['source_id']\n  WH"
        "EN 'proposal_submissions' THEN ARRAY[]::"
        "text[]\n  WHEN 'proposal_decisions' THEN "
        "ARRAY['submission_id']\n  WHEN 'project_o"
        "pen_items' THEN ARRAY['source_question_i"
        "d','source_spec_item_id','g0_decision_id"
        "']\n  WHEN 'category_knowledge_current' T"
        "HEN ARRAY['current_entry_id']\n  WHEN 'pr"
        "omotion_proofs' THEN ARRAY['knowledge_en"
        "try_id','source_proposal_id']\n  WHEN 'ev"
        "idence_links' THEN ARRAY['evidence_id']\n"
        "  WHEN 'claim_withdrawals' THEN ARRAY['c"
        "laim_id']\n  WHEN 'manufacturing_baseline"
        "_publications' THEN ARRAY['baseline_id',"
        "'process_id','previous_id']\n  WHEN 'manu"
        "facturing_publication_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'manufacturing_p"
        "ublication_documents' THEN ARRAY['docume"
        "nt_id','process_id']\n  WHEN 'native_pilo"
        "t_runs' THEN ARRAY['build_id','lot_id','"
        "actual_configuration_id','engineering_co"
        "nfiguration_id','process_id','publicatio"
        "n_id']\n  WHEN 'native_pilot_currents' TH"
        "EN ARRAY['pilot_id','latest_observation_"
        "id']\n  WHEN 'native_pilot_observations' "
        "THEN ARRAY['pilot_id','previous_observat"
        "ion_id']\n  WHEN 'release_packages' THEN "
        "ARRAY['previous_id']\n  WHEN 'release_pac"
        "kage_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'release_decisions' THEN ARRAY['p"
        "ackage_id']\n  WHEN 'release_policy_facts"
        "' THEN ARRAY['previous_id']\n  WHEN 'rele"
        "ase_policy_currents' THEN ARRAY['fact_id"
        "']\n  WHEN 'external_handoff_authorizatio"
        "ns' THEN ARRAY['package_id','engineering"
        "_decision_id','manufacturing_decision_id"
        "']\n  WHEN 'external_delivery_intents' TH"
        "EN ARRAY['handoff_id']\n  WHEN 'external_"
        "receipts' THEN ARRAY['handoff_id','inten"
        "t_id','previous_receipt_id','reconciles_"
        "id']\n  WHEN 'external_handoff_currents' "
        "THEN ARRAY['handoff_id','intent_id','lat"
        "est_receipt_id']\n  WHEN 'release_excepti"
        "on_decisions' THEN ARRAY['basis_package_"
        "id','policy_fact_id','previous_id']\n  WH"
        "EN 'release_exception_currents' THEN ARR"
        "AY['basis_package_id','policy_fact_id','"
        "decision_id']\n  WHEN 'work_commitment_re"
        "views' THEN ARRAY['commitment_id','task_"
        "version_id','submission_id','previous_id"
        "']\n  WHEN 'work_commitment_review_curren"
        "ts' THEN ARRAY['version_id']\n  WHEN 'ext"
        "ernal_wait_versions' THEN ARRAY['previou"
        "s_id']\n  WHEN 'external_wait_currents' T"
        "HEN ARRAY['version_id']\n  WHEN 'project_"
        "risk_followups' THEN ARRAY['previous_id'"
        ",'risk_id','g0_decision_id']\n  WHEN 'pro"
        "ject_risk_followup_currents' THEN ARRAY["
        "'version_id']\n  WHEN 'work_task_versions"
        "' THEN ARRAY['previous_id']\n  WHEN 'work"
        "_task_currents' THEN ARRAY['version_id']"
        "\n  WHEN 'work_commitment_versions' THEN "
        "ARRAY['replaces_id']\n  WHEN 'work_commit"
        "ment_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'project_status_updates' THEN ARR"
        'AY[]::text[]\n  ELSE ARRAY[]::text[] END;'
        '\n FOREACH key IN ARRAY keys LOOP\n  IF pa'
        'yload->>key IS NOT NULL THEN links=array'
        '_append(links,(payload->>key)::uuid); EN'
        "D IF;\n END LOOP;\n -- Publication's exact"
        ' saved read set is a validated Artifact '
        'relationship.\n -- Do not scan its declar'
        'ation, body, reason or arbitrary JSON UU'
        "ID values.\n IF table_name IN ('manufactu"
        "ring_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','rel"
        "ease_packages','release_decisions','rele"
        "ase_policy_facts','external_handoff_auth"
        "orizations','external_receipts','release"
        "_exception_decisions') THEN\n  FOR item I"
        'N SELECT value FROM jsonb_array_elements'
        "(coalesce(payload->'required_source_read"
        "_set','[]')) LOOP\n   IF item->>'artifact"
        "_id' IS NOT NULL THEN\n    links=array_ap"
        "pend(links,(item->>'artifact_id')::uuid)"
        ';\n   END IF;\n  END LOOP;\n END IF;\n IF ta'
        "ble_name IN ('native_pilot_runs','native"
        "_pilot_observations') THEN\n  FOR item IN"
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{material_snapshot,st"
        "atistics,samples}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOR item IN SELECT value '
        'FROM jsonb_array_elements(coalesce(paylo'
        "ad#>'{material_snapshot,statistics,issue"
        "s}','[]')) LOOP\n   IF item->>'id' IS NOT"
        ' NULL THEN links=array_append(links,(ite'
        "m->>'id')::uuid); END IF;\n  END LOOP;\n  "
        "item=payload#>'{material_snapshot,statis"
        "tics,resource,fact}';\n  IF item->>'id' I"
        'S NOT NULL THEN links=array_append(links'
        ",(item->>'id')::uuid); END IF;\n END IF;\n"
        " IF table_name='release_packages' THEN\n "
        ' -- FixedObject.ref is a closed, server-'
        'resolved version reference, not arbitrar'
        'y body UUID text.\n  FOR item IN SELECT v'
        'alue FROM jsonb_array_elements(coalesce('
        "payload#>'{body,objects}','[]')) LOOP\n  "
        " container=item->'ref';\n   IF container-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "manufacturing_publication','test_run','p"
        "ilot_run','issue','change','exception','"
        "artifact','work_instruction','control_pl"
        "an','build_lot','line'])\n    AND contain"
        "er->>'id' IS NOT NULL THEN links=array_a"
        "ppend(links,(container->>'id')::uuid); E"
        'ND IF;\n  END LOOP;\n END IF;\n IF table_na'
        "me IN ('external_handoff_authorizations'"
        ",'external_delivery_intents') THEN\n  -- "
        'Only closed, owner-verified mapping and '
        'manifest references are source edges.\n  '
        "container=CASE WHEN table_name='external"
        "_handoff_authorizations' THEN payload#>'"
        "{body,declaration}' ELSE payload->'body'"
        ' END;\n  FOR item IN SELECT value FROM js'
        "onb_array_elements(coalesce(container->'"
        "mappings','[]')) LOOP\n   IF item->'ref'-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "part','bom_revision','artifact','work_in"
        "struction','control_plan'])\n    AND item"
        "->'ref'->>'id' IS NOT NULL THEN links=ar"
        "ray_append(links,(item->'ref'->>'id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN '
        'SELECT value FROM jsonb_array_elements(c'
        "oalesce(container->'manifest','[]')) LOO"
        "P\n   IF item->'artifact'->>'id' IS NOT N"
        'ULL THEN links=array_append(links,(item-'
        ">'artifact'->>'id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n IF table_name='release"
        "_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by '
        'the policy owner.\n  FOREACH key IN ARRAY'
        " ARRAY['definition','engineering_configu"
        "ration','manufacturing_configuration'] L"
        "OOP\n   container=payload#>ARRAY['materia"
        "l','subject_config',key];\n   IF containe"
        "r->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(container->>'id')::uuid); EN"
        'D IF;\n  END LOOP;\n END IF;\n -- These sto'
        'red fields are validated Reference conta'
        'iners. Do not feed the\n -- whole row or '
        'arbitrary content into the canonical Ref'
        'erence parser.\n IF table_name=ANY(ARRAY['
        "'proposals','proposal_item_versions','pr"
        "oposal_submissions',\n  'category_knowled"
        "ge_entries','definition_specs']) THEN\n  "
        "FOREACH key IN ARRAY ARRAY['source_refs'"
        ",'direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links "
        '|| public.m3_lifecycle_typed_links(t,c,p'
        'ayload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and catego'
        'ry_service._references: only\n -- commerc'
        'ial_target, voice, and competitor have n'
        "ested source contracts.\n IF table_name='"
        "proposal_item_versions' AND payload->>'k"
        "ind'='commercial_target' THEN\n  FOREACH "
        "key IN ARRAY ARRAY['target_price','cost'"
        ",'volume'] LOOP\n   links=links || public"
        ".m3_lifecycle_typed_links(t,c,payload->'"
        "content'->key->'source');\n  END LOOP;\n E"
        "LSIF table_name='category_knowledge_entr"
        "ies' AND payload->>'kind'='voice' THEN\n "
        ' links=links || public.m3_lifecycle_type'
        "d_links(t,c,payload->'content'->'represe"
        "ntative_refs');\n ELSIF table_name='categ"
        "ory_knowledge_entries' AND payload->>'ki"
        "nd'='competitor' THEN\n  FOREACH key IN A"
        "RRAY ARRAY['metrics','features','prices'"
        '] LOOP\n   FOR item IN SELECT value FROM '
        "jsonb_array_elements(coalesce(payload->'"
        "content'->key,'[]')) LOOP\n    links=link"
        's || public.m3_lifecycle_typed_links(t,c'
        ",item->'source_ref');\n   END LOOP;\n  END"
        " LOOP;\n END IF;\n IF table_name='proposal"
        "_submissions' THEN\n  container=payload->"
        "'frozen_document';\n  FOREACH key IN ARRA"
        "Y ARRAY['source_refs','direct_source_ref"
        "s','context_refs','baseline_claim_refs']"
        ' LOOP\n   links=links || public.m3_lifecy'
        'cle_typed_links(t,c,container->key);\n  E'
        'ND LOOP;\n  FOR item IN SELECT value FROM'
        ' jsonb_array_elements(coalesce(container'
        "->'items','[]')) LOOP\n   links=links || "
        "public.m3_lifecycle_source_links(t,c,'pr"
        "oposal_item_versions',item-ARRAY['item_i"
        "d','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink'
        ' provenance here.\n   links=links || publ'
        "ic.m3_lifecycle_typed_links(t,c,item->'e"
        "vidence_links');\n  END LOOP;\n ELSIF tabl"
        "e_name='promotion_proofs' THEN\n  FOR ite"
        'm IN SELECT value FROM jsonb_array_eleme'
        "nts(coalesce(payload->'source_item_refs'"
        ",'[]')) LOOP\n   IF item->>'item_id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'item_id')::uuid); END IF;\n  END L"
        'OOP;\n END IF;\n -- Exact persisted Eviden'
        'ceLink targets supplement these immutabl'
        'e versions.\n -- Reverted links and withd'
        'rawn Claims still retain the original hi'
        'storical\n -- dependency; lifecycle clean'
        'up must not erase their audit source.\n I'
        "F table_name='proposal_item_versions' AN"
        "D payload->>'item_id' IS NOT NULL THEN\n "
        " target_kind='proposal_item'; referenced"
        "_target=(payload->>'item_id')::uuid;\n  r"
        "eferenced_version=(payload->>'version'):"
        ":integer;\n ELSIF table_name='category_kn"
        "owledge_entries' AND payload->>'id' IS N"
        "OT NULL THEN\n  target_kind='knowledge_en"
        "try'; referenced_target=(payload->>'id')"
        '::uuid;\n  referenced_version=(payload->>'
        "'version')::integer;\n ELSIF table_name='"
        "definition_specs' AND payload->>'id' IS "
        "NOT NULL THEN\n  target_kind='definition_"
        "spec'; referenced_target=(payload->>'id'"
        ')::uuid;\n  SELECT revision INTO referenc'
        'ed_version FROM public.definition_revisi'
        'ons\n   WHERE tenant_id=t AND category_id'
        "=c AND id=(payload->>'definition_id')::u"
        'uid;\n END IF;\n IF referenced_target IS N'
        'OT NULL AND referenced_version IS NOT NU'
        'LL THEN\n  SELECT coalesce(array_agg(link'
        ".evidence_id),'{}') INTO extra FROM publ"
        'ic.evidence_links link\n   WHERE link.ten'
        'ant_id=t AND link.category_id=c AND link'
        '.target_type=target_kind\n    AND link.ta'
        'rget_id=referenced_target AND link.targe'
        't_version=referenced_version;\n  links=li'
        'nks || extra;\n END IF;\n -- Child source '
        'rows point to their parent, whereas depe'
        "ndency traversal needs\n -- the parent's "
        'fixed source children as well. Keep the '
        "actual relational edge.\n IF table_name='"
        "definition_revisions' THEN\n  SELECT coal"
        "esce(array_agg(id),'{}') INTO extra FROM"
        ' (\n   SELECT id FROM public.definition_s'
        'ources WHERE tenant_id=t AND category_id'
        "=c\n    AND definition_id=(payload->>'id'"
        ')::uuid\n   UNION ALL SELECT id FROM publ'
        'ic.definition_specs WHERE tenant_id=t AN'
        'D category_id=c\n    AND definition_id=(p'
        "ayload->>'id')::uuid\n  ) children;\n  lin"
        "ks=links || extra;\n ELSIF table_name='pr"
        "oposals' THEN\n  SELECT coalesce(array_ag"
        "g(id),'{}') INTO extra FROM public.propo"
        'sal_item_versions\n   WHERE tenant_id=t A'
        'ND category_id=c AND proposal_id=(payloa'
        "d->>'id')::uuid;\n  links=links || extra;"
        "\n ELSIF table_name='proposal_items' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM public.proposal_item_vers'
        'ions\n   WHERE tenant_id=t AND category_i'
        "d=c AND item_id=(payload->>'id')::uuid;\n"
        '  links=links || extra;\n ELSIF table_nam'
        "e='product_target_segments' THEN\n  SELEC"
        "T coalesce(array_agg(id),'{}') INTO extr"
        'a FROM public.category_knowledge_entries'
        '\n   WHERE tenant_id=t AND category_id=c '
        "AND lineage_id=(payload->>'segment_linea"
        "ge_id')::uuid\n    AND version=(payload->"
        ">'segment_version')::integer;\n  links=li"
        "nks || extra;\n ELSIF table_name='paramet"
        "er_current' THEN\n  SELECT coalesce(array"
        "_agg(id),'{}') INTO extra FROM public.pa"
        'rameter_versions\n   WHERE tenant_id=t AN'
        'D category_id=c AND parameter_id=(payloa'
        "d->>'parameter_id')::uuid\n    AND versio"
        "n=(payload->>'current_version')::integer"
        ';\n  links=links || extra;\n END IF;\n\n IF '
        "table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_u"
        "pdates') THEN\n  FOR item IN SELECT value"
        ' FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array"
        "_append(links,(item->>'artifact_id')::uu"
        'id); END IF;\n  END LOOP;\n  IF table_name'
        "='work_task_versions' AND payload#>>'{bo"
        "dy,plan_task,id}' IS NOT NULL THEN\n   li"
        "nks=array_append(links,(payload#>>'{body"
        ",plan_task,id}')::uuid);\n  END IF;\n  IF "
        "table_name='work_commitment_versions' TH"
        "EN\n   SELECT coalesce(array_agg(id),'{}'"
        ') INTO extra FROM public.work_task_versi'
        'ons\n    WHERE tenant_id=t AND category_i'
        "d=c AND task_id=(payload->>'task_id')::u"
        "uid AND revision=(payload->>'task_revisi"
        "on')::integer;\n   links=links||extra;\n  "
        "ELSIF table_name='project_status_updates"
        "' THEN\n   FOR item IN SELECT value FROM "
        "jsonb_array_elements(coalesce(payload->'"
        "task_refs','[]')) LOOP\n    SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM p"
        'ublic.work_task_versions\n     WHERE tena'
        'nt_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'"
        "revision')::integer;\n    links=links||ex"
        'tra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' T"
        'HEN\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload->'read"
        "s','[]')) LOOP\n   IF item->>'artifact_id"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(item->>'artifact_id')::uuid); END I"
        'F;\n  END LOOP;\n END IF;\n\n IF table_name='
        "'external_wait_versions' THEN\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{source_basis,arti"
        "facts}','[]')) LOOP\n   IF item->>'id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(item->>'id')::uuid); END IF;\n  END LOOP"
        ";\n  FOREACH key IN ARRAY ARRAY['mileston"
        "e','build','calendar'] LOOP\n   container"
        "=payload#>ARRAY['body',key];\n   IF conta"
        "iner->>'id' IS NOT NULL THEN links=array"
        "_append(links,(container->>'id')::uuid);"
        ' END IF;\n  END LOOP;\n  container=payload'
        "#>'{body,replaces}';\n  IF container->>'i"
        "d' IS NOT NULL THEN\n   SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM publi"
        'c.external_wait_versions\n    WHERE tenan'
        't_id=t AND category_id=c AND wait_id=(co'
        "ntainer->>'id')::uuid AND revision=(cont"
        "ainer->>'revision')::integer;\n   links=l"
        'inks||extra;\n  END IF;\n END IF;\n IF tabl'
        "e_name='project_risk_followups' THEN\n  F"
        'OR item IN SELECT value FROM jsonb_array'
        "_elements(coalesce(payload#>'{source_bas"
        "is,artifacts}','[]')) LOOP\n   IF item->>"
        "'id' IS NOT NULL THEN links=array_append"
        "(links,(item->>'id')::uuid); END IF;\n  E"
        "ND LOOP;\n END IF;\n\n IF table_name IN ('k"
        "nowledge_candidate_versions','knowledge_"
        "candidate_currents','knowledge_applicabi"
        "lity_assessments','knowledge_rule_versio"
        "ns','knowledge_rule_currents') THEN\n  FO"
        "REACH key IN ARRAY ARRAY['previous_id','"
        "version_id','candidate_version_id','asse"
        "ssment_id','publication_id'] LOOP\n   IF "
        'payload->>key IS NOT NULL THEN links=arr'
        'ay_append(links,(payload->>key)::uuid); '
        'END IF;\n  END LOOP;\n  FOR item IN SELECT'
        ' value FROM jsonb_array_elements(coalesc'
        "e(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'i"
        "d')::uuid); END IF;\n  END LOOP;\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload->'reads','[]')) LO"
        "OP\n   IF item->>'artifact_id' IS NOT NUL"
        'L THEN links=array_append(links,(item->>'
        "'artifact_id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{sour"
        "ce_basis,result_receipts}','[]')) LOOP\n "
        "  IF item->>'receipt_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'rece"
        "ipt_id')::uuid); END IF;\n   IF item->>'r"
        "ow_id' IS NOT NULL THEN links=array_appe"
        "nd(links,(item->>'row_id')::uuid); END I"
        'F;\n  END LOOP;\n  FOR item IN SELECT valu'
        'e FROM jsonb_array_elements(coalesce(pay'
        "load#>'{source_basis,professional,fact_r"
        "efs}','[]')) LOOP\n   IF item->>'id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  IF payload#>>'{source_basis,target,id}"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(payload#>>'{source_basis,target,id}"
        "')::uuid); END IF;\n END IF;\n\n IF table_n"
        "ame IN ('field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds') THEN\n  FOREACH key IN ARRAY ARRAY["
        "'previous_id','version_id','feedback_ver"
        "sion_id'] LOOP\n   IF payload->>key IS NO"
        'T NULL THEN links=array_append(links,(pa'
        'yload->>key)::uuid); END IF;\n  END LOOP;'
        '\n  FOR item IN SELECT value FROM jsonb_a'
        "rray_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOREACH key IN ARRAY ARRA'
        "Y['engineering_configuration','manufactu"
        "ring_configuration','batch'] LOOP\n   IF "
        "payload#>>ARRAY['body','location',key,'i"
        "d'] IS NOT NULL THEN links=array_append("
        "links,(payload#>>ARRAY['body','location'"
        ",key,'id'])::uuid); END IF;\n  END LOOP;\n"
        '  FOR item IN SELECT value FROM jsonb_ar'
        "ray_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   I"
        "F item->>'receipt_id' IS NOT NULL THEN l"
        "inks=array_append(links,(item->>'receipt"
        "_id')::uuid); END IF;\n   IF item->>'row_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'row_id')::uuid); END IF;\n"
        '  END LOOP;\n END IF;\n IF table_name IN ('
        "'change_request_versions','change_graph_"
        "captures') THEN\n  FOR container IN SELEC"
        'T value FROM jsonb_each(coalesce(payload'
        "#>'{source_basis,owners}','{}')) LOOP\n  "
        " IF container->>'feedback_version_id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Cl'
        'osed native Field plan and occurrence re'
        'ferences, never arbitrary UUID prose.\n I'
        "F table_name='controlled_change_selectio"
        "n_facts' AND payload->>'basis_kind'='fie"
        "ld_intent' THEN\n  IF payload->>'feedback"
        "_version_id' IS NOT NULL THEN\n   links=a"
        "rray_append(links,(payload->>'feedback_v"
        "ersion_id')::uuid);\n  END IF;\n END IF;\n "
        "IF table_name='change_implementation_cap"
        "tures'\n  AND payload#>>'{occurrence_snap"
        "shot,schema_version}'='pdos-field-change"
        "-implementation-occurrence-v1' THEN\n  FO"
        "REACH key IN ARRAY ARRAY['feedback_versi"
        "on_id','selection_id'] LOOP\n   IF payloa"
        "d#>>ARRAY['occurrence_snapshot',key] IS "
        'NOT NULL THEN\n    links=array_append(lin'
        "ks,(payload#>>ARRAY['occurrence_snapshot"
        "',key])::uuid);\n   END IF;\n  END LOOP;\n "
        "END IF;\n\n IF table_name='change_completi"
        "on_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','"
        "order_record_id','shared_proof_id'] LOOP"
        '\n   IF payload->>key IS NOT NULL THEN li'
        'nks=array_append(links,(payload->>key)::'
        'uuid); END IF;\n  END LOOP;\n  FOR item IN'
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload->'required_source_read_"
        "set','[]')) LOOP\n   IF item->>'artifact_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'artifact_id')::uuid); END"
        " IF;\n  END LOOP;\n  IF payload#>>'{native"
        "_input,lot,id}' IS NOT NULL THEN links=a"
        "rray_append(links,(payload#>>'{native_in"
        "put,lot,id}')::uuid); END IF;\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LO"
        'OP;\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload#>'{nat"
        "ive_input,mappings}','[]')) LOOP\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO ext"
        'ra FROM verification_run_versions\n    WH'
        'ERE tenant_id=t AND category_id=c AND ru'
        "n_id=(item#>>'{run,id}')::uuid AND revis"
        "ion=(item#>>'{run,revision}')::integer;\n"
        '   links=links||extra; links=array_appen'
        "d(links,(item->>'sample_id')::uuid);\n  E"
        'ND LOOP;\n END IF;\n\n -- Closed native own'
        'er DTOs: retain exact outputs and native'
        " execution/report rows.\n IF table_name='"
        "change_completion_records' THEN\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{fact_snapshot,o"
        "utput_refs}','[]')) LOOP\n   IF item->>'k"
        "ind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM ver"
        'ification_run_versions\n     WHERE tenant'
        '_id=t AND category_id=c AND run_id=(item'
        "->>'id')::uuid AND revision=(item->>'rev"
        "ision')::integer;\n    links=links||extra"
        ";\n   ELSIF item->>'kind'=ANY(ARRAY['engi"
        "neering_configuration','manufacturing_co"
        "nfiguration','build','sample']) THEN\n   "
        " links=array_append(links,(item->>'id'):"
        ':uuid);\n   END IF;\n  END LOOP;\n  IF payl'
        "oad#>>'{owner_basis,schema_version}'='pd"
        "os-native-build-adoption-read-v1' THEN\n "
        "  FOREACH key IN ARRAY ARRAY['previous_b"
        "uild','successor_build','actual_configur"
        "ation','lot','start'] LOOP\n    IF payloa"
        "d#>>ARRAY['owner_basis',key,'id'] IS NOT"
        ' NULL THEN\n     links=array_append(links'
        ",(payload#>>ARRAY['owner_basis',key,'id'"
        '])::uuid);\n    END IF;\n   END LOOP;\n  EL'
        "SIF payload#>>'{owner_basis,schema_versi"
        "on}'='pdos-native-change-run-verificatio"
        "n-v1' THEN\n   FOR container IN SELECT va"
        "lue FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREA"
        "CH key IN ARRAY ARRAY['run_version_id','"
        "request_version_id','projection_id'] LOO"
        'P\n     IF container->>key IS NOT NULL TH'
        'EN links=array_append(links,(container->'
        '>key)::uuid); END IF;\n    END LOOP;\n   E'
        'ND LOOP;\n  END IF;\n END IF;\n\n -- F: only'
        ' server-verified fixed answer proofs est'
        'ablish these dependency edges.\n -- Nativ'
        'e deferred atoms bind these exact arrays'
        ' to real source ledgers.\n IF table_name '
        "IN ('category_knowledge_entries','knowle"
        "dge_candidate_versions','knowledge_rule_"
        "versions','knowledge_answer_reviews','kn"
        "owledge_gap_submissions') THEN\n  contain"
        "er=CASE table_name WHEN 'category_knowle"
        "dge_entries' THEN payload->'answer_sourc"
        "es'\n   WHEN 'knowledge_candidate_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   WHEN 'knowledge_rule_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   ELSE payload->'source_proof'"
        ' END;\n  -- Only these native knowledge r'
        'ows have an optional answer-derived proo'
        'f.\n  -- to_jsonb(row) represents an SQL '
        'NULL column as a JSON null member.\n  IF '
        "table_name IN ('category_knowledge_entri"
        "es','knowledge_candidate_versions','know"
        "ledge_rule_versions') THEN\n   container="
        "coalesce(nullif(container,'null'::jsonb)"
        ",'[]'::jsonb);\n  END IF;\n  -- Review/Gap"
        ' proof remains required and reaches the '
        'strict resolver unchanged.\n  links=links'
        '||public.assistant_source_lifecycle_link'
        's(t,c,container);\n END IF;\n\n -- G privat'
        'e outbound body copies have no category '
        'column. Only the fixed\n -- server footpr'
        'int subset for this REAL category establ'
        "ishes retention edges.\n IF table_name='d"
        "ingtalk_deliveries' THEN\n  IF payload->>"
        "'tenant_id' IS DISTINCT FROM t::text OR "
        "c IS NULL THEN\n   RAISE EXCEPTION 'Deliv"
        "ery retention scope mismatch' USING ERRC"
        "ODE='23514'; END IF;\n  SELECT coalesce(j"
        "sonb_agg(value),'[]'::jsonb) INTO contai"
        'ner\n   FROM jsonb_array_elements(coalesc'
        "e(payload->'source_dependencies','[]'::j"
        "sonb))\n   WHERE value->>'category_id'=c:"
        ':text;\n  links=links||public.assistant_s'
        'ource_lifecycle_links(t,c,container);\n E'
        'ND IF;\n\n -- E: actual deterministic-summ'
        'ary fixed ObjectRef IDs, from server-onl'
        "y delivery capture.\n IF table_name='ding"
        "talk_summary_deliveries' THEN\n  IF paylo"
        "ad->>'tenant_id' IS DISTINCT FROM t::tex"
        "t OR payload->>'category_id' IS DISTINCT"
        " FROM c::text THEN\n   RAISE EXCEPTION 'S"
        'ummary delivery retention scope mismatch'
        "' USING ERRCODE='23514'; END IF;\n  IF pa"
        "yload->>'run_id' IS NOT NULL THEN links="
        "array_append(links,(payload->>'run_id'):"
        ':uuid); END IF;\n  FOR key IN SELECT valu'
        'e FROM jsonb_array_elements_text(payload'
        "->'source_ids') LOOP\n   links=array_appe"
        'nd(links,key::uuid);\n  END LOOP;\n END IF'
        ';\n RETURN links;\nEND;\n$function$\n'
    ),
    (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_nodes(t uuid, c uuid, identities '
        'uuid[] DEFAULT NULL::uuid[])\n RETURNS TA'
        'BLE(table_name text, node_id uuid, links'
        ' uuid[])\n LANGUAGE plpgsql\n STABLE SECUR'
        "ITY DEFINER\n SET search_path TO 'pg_cata"
        "log', 'public', 'pg_temp'\nAS $function$\n"
        'DECLARE name text; payload jsonb; contro'
        'ls uuid[];\nBEGIN\n IF identities IS NULL '
        "THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO controls FROM public.action_rece"
        'ipts\n   WHERE tenant_id=t AND category_i'
        "d=c AND operation LIKE 'evidence.lifecyc"
        "le.%';\n ELSE controls='{}'; END IF;\n FOR"
        'EACH name IN ARRAY CASE WHEN identities '
        "IS NULL THEN ARRAY['agent_runs','action_"
        "receipts','actual_configurations','artif"
        "act_versions','audit_entries','bom_lines"
        "','bom_revisions','build_authorization_d"
        "ecisions','build_current_authorizations'"
        ",'build_current_execution_assessments','"
        "build_execution_assessments','build_lots"
        "','build_operational_current','build_ope"
        "rational_facts','build_readiness','build"
        "_starts','builds','capa_current_observat"
        "ions','capa_current_verification_rules',"
        "'capa_named_verification_reviews','capa_"
        "observation_facts','capa_remediation_lin"
        "ks','capa_verification_evidence','capa_v"
        "erification_rule_facts','change_approval"
        "_records','change_dependency_clocks','ch"
        "ange_graph_captures','change_implementat"
        "ion_captures','change_implementation_rec"
        "ords','change_order_records','change_req"
        "uest_currents','change_request_versions'"
        ",'claim_consumptions','claims','controll"
        "ed_change_coverage_currents','controlled"
        "_change_coverage_facts','controlled_chan"
        "ge_policy_currents','controlled_change_p"
        "olicy_facts','controlled_change_selectio"
        "n_currents','controlled_change_selection"
        "_facts','cost_current_inputs','cost_esti"
        "mates','cost_input_snapshots','cost_sour"
        "ce_captures','definition_revisions','def"
        "inition_sources','definition_specs','eng"
        "ineering_configurations','manufacturing_"
        "baseline_document_links','manufacturing_"
        "preparation_currents','manufacturing_pre"
        "paration_versions','measurement_import_c"
        "aptures','operational_material_holds','o"
        "perational_resource_occupancies','origin"
        "al_scan_requests','original_scan_results"
        "','original_security','outbox_events','p"
        "arts','plan_proposals','plan_revisions',"
        "'process_revisions','product_variants','"
        "professional_authority_current','profess"
        "ional_authority_facts','project_product_"
        "links','project_tasks','project_work_pac"
        "kages','projects','quality_current_issue"
        "s','quality_current_policies','quality_e"
        "vent_failure_links','quality_failure_map"
        "s','quality_issue_versions','quality_pol"
        "icy_facts','request_keys','runs','sample"
        "_allocations','sample_current_readiness'"
        ",'sample_readiness_facts','sample_run_us"
        "ages','sample_units','sample_usage_senti"
        "nels','supply_current_snapshots','supply"
        "_kit_projections','supply_snapshots','su"
        "pply_source_captures','task_dependencies"
        "','test_measurements','test_resource_cur"
        "rent','test_resource_facts','test_resour"
        "ce_reservations','test_result_actions','"
        "test_result_projections','uploaded_origi"
        "nals','variant_revisions','verification_"
        "actual_method_applicabilities','verifica"
        "tion_actual_method_batches','verificatio"
        "n_current_actual_methods','verification_"
        "current_formal_requests','verification_c"
        "urrent_preparations','verification_curre"
        "nt_runs','verification_formal_requests',"
        "'verification_handoff_facts','verificati"
        "on_launch_facts','verification_method_ap"
        "plicabilities','verification_preparation"
        "s','verification_run_identities','verifi"
        "cation_run_versions','verification_windo"
        "w_proposals','work_requests','proposals'"
        ",'proposal_items','proposal_item_version"
        "s','proposal_revisions','proposal_source"
        "s','proposal_submissions','proposal_deci"
        "sions','project_open_items','category_kn"
        "owledge_entries','category_knowledge_cur"
        "rent','product_target_segments','paramet"
        "er_versions','parameter_current','promot"
        "ion_proofs','evidence_links','claim_with"
        "drawals','manufacturing_baseline_publica"
        "tions','manufacturing_publication_curren"
        "ts','manufacturing_publication_documents"
        "','native_pilot_runs','native_pilot_curr"
        "ents','native_pilot_observations','relea"
        "se_packages','release_package_currents',"
        "'release_decisions','release_policy_fact"
        "s','release_policy_currents','external_h"
        "andoff_authorizations','external_deliver"
        "y_intents','external_receipts','external"
        "_handoff_currents','release_exception_de"
        "cisions','release_exception_currents','w"
        "ork_commitment_reviews','work_commitment"
        "_review_currents','work_task_versions','"
        "work_task_currents','work_commitment_ver"
        "sions','work_commitment_currents','proje"
        "ct_status_updates','external_wait_versio"
        "ns','external_wait_currents','project_ri"
        "sk_followups','project_risk_followup_cur"
        "rents','knowledge_candidate_versions','k"
        "nowledge_candidate_currents','knowledge_"
        "applicability_assessments','knowledge_ru"
        "le_versions','knowledge_rule_currents','"
        "field_feedback_versions','field_feedback"
        "_currents','field_response_records','kno"
        "wledge_answer_reviews','knowledge_gap_su"
        "bmissions'] ELSE ARRAY[\n  'artifact_vers"
        "ions','claims','definition_revisions','d"
        "efinition_sources','definition_specs',\n "
        " 'proposals','proposal_items','proposal_"
        "item_versions','proposal_submissions','p"
        "roposal_decisions',\n  'category_knowledg"
        "e_entries','category_knowledge_current',"
        "'parameter_versions','parameter_current'"
        ",\n  'evidence_links','promotion_proofs',"
        "'native_pilot_runs','native_pilot_curren"
        "ts','native_pilot_observations','release"
        "_packages','release_package_currents','r"
        "elease_decisions','release_policy_facts'"
        ",'release_policy_currents','external_han"
        "doff_authorizations','external_delivery_"
        "intents','external_receipts','external_h"
        "andoff_currents','release_exception_deci"
        "sions','release_exception_currents','wor"
        "k_commitment_reviews','work_commitment_r"
        "eview_currents','work_task_versions','wo"
        "rk_task_currents','work_commitment_versi"
        "ons','work_commitment_currents','project"
        "_status_updates','external_wait_versions"
        "','external_wait_currents','project_risk"
        "_followups','project_risk_followup_curre"
        "nts','knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_ap"
        "plicability_assessments','knowledge_rule"
        "_versions','knowledge_rule_currents','fi"
        "eld_feedback_versions','field_feedback_c"
        "urrents','field_response_records','knowl"
        "edge_answer_reviews','knowledge_gap_subm"
        "issions'] END LOOP\n  FOR payload IN EXEC"
        "UTE CASE WHEN name=ANY(ARRAY['audit_entr"
        "ies','outbox_events','request_keys'])\n  "
        " THEN format('SELECT to_jsonb(x) FROM pu"
        'blic.%I x JOIN public.action_receipts r '
        'ON r.id=x.receipt_id AND r.tenant_id=x.t'
        'enant_id WHERE x.tenant_id=$1 AND r.cate'
        "gory_id=$2',name)\n   ELSE format('SELECT"
        ' to_jsonb(x) FROM public.%I x WHERE tena'
        'nt_id=$1 AND category_id=$2 AND ($3 IS N'
        "ULL OR %I=ANY($3))',name,\n    CASE name "
        "WHEN 'category_knowledge_current' THEN '"
        "lineage_id'\n     WHEN 'parameter_current"
        "' THEN 'parameter_id' ELSE 'id' END)\n   "
        'END USING t,c,identities LOOP\n   IF (pay'
        "load->>'receipt_id')::uuid=ANY(controls)"
        " OR\n    (name='action_receipts' AND payl"
        "oad->>'operation' LIKE 'evidence.lifecyc"
        "le.%') THEN CONTINUE; END IF;\n   table_n"
        "ame=name;\n   node_id=CASE name WHEN 'cat"
        "egory_knowledge_current' THEN (payload->"
        ">'lineage_id')::uuid\n    WHEN 'parameter"
        "_current' THEN (payload->>'parameter_id'"
        ")::uuid ELSE (payload->>'id')::uuid END;"
        '\n   IF identities IS NULL THEN links=pub'
        'lic.m3_lifecycle_row_links(t,c,name,payl'
        'oad);\n   ELSE links=public.m3_lifecycle_'
        'source_links(t,c,name,payload); END IF;\n'
        "   -- Preserve predecessor's conservativ"
        'e legacy graph; M3-only nodes use\n   -- '
        'strictly typed/relational links. Root lo'
        'okup never uses free-text UUIDs.\n   IF i'
        "dentities IS NULL AND name<>ALL(ARRAY['n"
        "ative_pilot_runs','native_pilot_currents"
        "','native_pilot_observations','release_p"
        "ackages','release_package_currents','rel"
        "ease_decisions','release_policy_facts','"
        "release_policy_currents','external_hando"
        "ff_authorizations','external_delivery_in"
        "tents','external_receipts','external_han"
        "doff_currents','release_exception_decisi"
        "ons','release_exception_currents','work_"
        "commitment_reviews','work_commitment_rev"
        "iew_currents','work_task_versions','work"
        "_task_currents','work_commitment_version"
        "s','work_commitment_currents','project_s"
        "tatus_updates','external_wait_versions',"
        "'external_wait_currents','project_risk_f"
        "ollowups','project_risk_followup_current"
        "s','manufacturing_baseline_publications'"
        ",'manufacturing_publication_currents','m"
        "anufacturing_publication_documents','pro"
        "posals','proposal_items','proposal_item_"
        "versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','propos"
        "al_decisions','project_open_items','cate"
        "gory_knowledge_entries','category_knowle"
        "dge_current','product_target_segments','"
        "parameter_versions','parameter_current',"
        "'promotion_proofs','evidence_links','cla"
        "im_withdrawals','knowledge_candidate_ver"
        "sions','knowledge_candidate_currents','k"
        "nowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_cu"
        "rrents','field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds','knowledge_answer_reviews','knowled"
        "ge_gap_submissions']) THEN\n    links=lin"
        'ks || public.kernel_lifecycle_links(name'
        ',payload);\n   END IF;\n   RETURN NEXT;\n  '
        'END LOOP;\n END LOOP;\n\n -- Read exactly t'
        'he retained metadata, never Delivery.pay'
        'load. One personal\n -- answer may appear'
        ' in several categories, each with its ow'
        'n source subset.\n FOR payload IN\n  SELEC'
        "T jsonb_build_object('id',d.id,'tenant_i"
        "d',d.tenant_id,\n   'content_kind',d.cont"
        "ent_kind,'source_dependencies',d.source_"
        'dependencies)\n  FROM public.dingtalk_del'
        'iveries d\n  WHERE d.tenant_id=t AND d.co'
        "ntent_kind='answer'\n   AND (identities I"
        'S NULL OR d.id=ANY(identities))\n   AND E'
        'XISTS(SELECT 1 FROM jsonb_array_elements'
        '(d.source_dependencies) dependency\n    W'
        "HERE dependency->>'category_id'=c::text)"
        "\n LOOP\n  table_name='dingtalk_deliveries"
        "'; node_id=(payload->>'id')::uuid;\n  lin"
        'ks=public.m3_lifecycle_source_links(t,c,'
        'table_name,payload);\n  RETURN NEXT;\n END'
        ' LOOP;\n\n -- Summary copies have a real c'
        'ategory. Read only immutable reference m'
        'etadata.\n FOR payload IN SELECT jsonb_bu'
        "ild_object('id',d.id,'tenant_id',d.tenan"
        "t_id,\n   'category_id',d.category_id,'ru"
        "n_id',d.run_id,'source_ids',d.source_ids"
        ')\n  FROM public.dingtalk_summary_deliver'
        'ies d\n  WHERE d.tenant_id=t AND d.catego'
        'ry_id=c AND (identities IS NULL OR d.id='
        "ANY(identities))\n LOOP\n  table_name='din"
        "gtalk_summary_deliveries'; node_id=(payl"
        "oad->>'id')::uuid;\n  links=public.m3_lif"
        'ecycle_source_links(t,c,table_name,paylo'
        'ad);\n  RETURN NEXT;\n END LOOP;\nEND;\n$fun'
        'ction$\n'
    ),
    (
        'CREATE TRIGGER category_lifecycle_clock '
        'BEFORE INSERT OR UPDATE OR DELETE ON pub'
        'lic.dingtalk_summary_deliveries FOR EACH'
        ' ROW EXECUTE FUNCTION public.dingtalk_su'
        'mmary_reference_clock()'
    ),
)

DOWN_SQL = (
    (
        'DO $$ BEGIN IF EXISTS(SELECT 1 FROM publ'
        'ic.dingtalk_summary_deliveries) THEN RAI'
        "SE EXCEPTION 'Summary delivery history m"
        "ust be retained' USING ERRCODE='23514'; "
        'END IF; END $$'
    ),
    (
        'DROP TRIGGER category_lifecycle_clock ON'
        ' public.dingtalk_summary_deliveries'
    ),
    (
        'DROP TRIGGER summary_identity ON public.'
        'dingtalk_summary_deliveries'
    ),
    (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_source_links(t uuid, c uuid, tabl'
        'e_name text, payload jsonb)\n RETURNS uui'
        'd[]\n LANGUAGE plpgsql\n STABLE SECURITY D'
        "EFINER\n SET search_path TO 'pg_catalog',"
        " 'public', 'pg_temp'\nAS $function$\nDECLA"
        "RE links uuid[]='{}'; extra uuid[]; key "
        'text; keys text[]; item jsonb; container'
        ' jsonb;\n target_kind text; referenced_ta'
        'rget uuid; referenced_version integer;\nB'
        "EGIN\n IF table_name='agent_runs' THEN RE"
        'TURN public.kernel_lifecycle_links(table'
        '_name,payload); END IF;\n -- Only actual '
        'top-level relation columns establish raw'
        ' UUID edges. Arbitrary\n -- content dicti'
        'onaries are not relational rows, even if'
        ' an extra key happens\n -- to be named so'
        'urce_id or item_id.\n keys=CASE table_nam'
        "e\n  WHEN 'artifact_versions' THEN ARRAY["
        "'original_id']\n  WHEN 'claims' THEN ARRA"
        "Y['artifact_id','snapshot_id']\n  WHEN 'd"
        "efinition_revisions' THEN ARRAY['derived"
        "_from_definition_id','parent_definition_"
        "id',\n   'source_proposal_id','source_sub"
        "mission_id']\n  WHEN 'definition_sources'"
        " THEN ARRAY['artifact_id']\n  WHEN 'defin"
        "ition_specs' THEN ARRAY[]::text[]\n  WHEN"
        " 'proposals' THEN ARRAY['baseline_defini"
        "tion_id','current_submission_id']\n  WHEN"
        " 'proposal_items' THEN ARRAY[]::text[]\n "
        " WHEN 'proposal_item_versions' THEN ARRA"
        "Y[]::text[]\n  WHEN 'proposal_revisions' "
        "THEN ARRAY['proposal_id']\n  WHEN 'propos"
        "al_sources' THEN ARRAY['source_id']\n  WH"
        "EN 'proposal_submissions' THEN ARRAY[]::"
        "text[]\n  WHEN 'proposal_decisions' THEN "
        "ARRAY['submission_id']\n  WHEN 'project_o"
        "pen_items' THEN ARRAY['source_question_i"
        "d','source_spec_item_id','g0_decision_id"
        "']\n  WHEN 'category_knowledge_current' T"
        "HEN ARRAY['current_entry_id']\n  WHEN 'pr"
        "omotion_proofs' THEN ARRAY['knowledge_en"
        "try_id','source_proposal_id']\n  WHEN 'ev"
        "idence_links' THEN ARRAY['evidence_id']\n"
        "  WHEN 'claim_withdrawals' THEN ARRAY['c"
        "laim_id']\n  WHEN 'manufacturing_baseline"
        "_publications' THEN ARRAY['baseline_id',"
        "'process_id','previous_id']\n  WHEN 'manu"
        "facturing_publication_currents' THEN ARR"
        "AY['version_id']\n  WHEN 'manufacturing_p"
        "ublication_documents' THEN ARRAY['docume"
        "nt_id','process_id']\n  WHEN 'native_pilo"
        "t_runs' THEN ARRAY['build_id','lot_id','"
        "actual_configuration_id','engineering_co"
        "nfiguration_id','process_id','publicatio"
        "n_id']\n  WHEN 'native_pilot_currents' TH"
        "EN ARRAY['pilot_id','latest_observation_"
        "id']\n  WHEN 'native_pilot_observations' "
        "THEN ARRAY['pilot_id','previous_observat"
        "ion_id']\n  WHEN 'release_packages' THEN "
        "ARRAY['previous_id']\n  WHEN 'release_pac"
        "kage_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'release_decisions' THEN ARRAY['p"
        "ackage_id']\n  WHEN 'release_policy_facts"
        "' THEN ARRAY['previous_id']\n  WHEN 'rele"
        "ase_policy_currents' THEN ARRAY['fact_id"
        "']\n  WHEN 'external_handoff_authorizatio"
        "ns' THEN ARRAY['package_id','engineering"
        "_decision_id','manufacturing_decision_id"
        "']\n  WHEN 'external_delivery_intents' TH"
        "EN ARRAY['handoff_id']\n  WHEN 'external_"
        "receipts' THEN ARRAY['handoff_id','inten"
        "t_id','previous_receipt_id','reconciles_"
        "id']\n  WHEN 'external_handoff_currents' "
        "THEN ARRAY['handoff_id','intent_id','lat"
        "est_receipt_id']\n  WHEN 'release_excepti"
        "on_decisions' THEN ARRAY['basis_package_"
        "id','policy_fact_id','previous_id']\n  WH"
        "EN 'release_exception_currents' THEN ARR"
        "AY['basis_package_id','policy_fact_id','"
        "decision_id']\n  WHEN 'work_commitment_re"
        "views' THEN ARRAY['commitment_id','task_"
        "version_id','submission_id','previous_id"
        "']\n  WHEN 'work_commitment_review_curren"
        "ts' THEN ARRAY['version_id']\n  WHEN 'ext"
        "ernal_wait_versions' THEN ARRAY['previou"
        "s_id']\n  WHEN 'external_wait_currents' T"
        "HEN ARRAY['version_id']\n  WHEN 'project_"
        "risk_followups' THEN ARRAY['previous_id'"
        ",'risk_id','g0_decision_id']\n  WHEN 'pro"
        "ject_risk_followup_currents' THEN ARRAY["
        "'version_id']\n  WHEN 'work_task_versions"
        "' THEN ARRAY['previous_id']\n  WHEN 'work"
        "_task_currents' THEN ARRAY['version_id']"
        "\n  WHEN 'work_commitment_versions' THEN "
        "ARRAY['replaces_id']\n  WHEN 'work_commit"
        "ment_currents' THEN ARRAY['version_id']\n"
        "  WHEN 'project_status_updates' THEN ARR"
        'AY[]::text[]\n  ELSE ARRAY[]::text[] END;'
        '\n FOREACH key IN ARRAY keys LOOP\n  IF pa'
        'yload->>key IS NOT NULL THEN links=array'
        '_append(links,(payload->>key)::uuid); EN'
        "D IF;\n END LOOP;\n -- Publication's exact"
        ' saved read set is a validated Artifact '
        'relationship.\n -- Do not scan its declar'
        'ation, body, reason or arbitrary JSON UU'
        "ID values.\n IF table_name IN ('manufactu"
        "ring_baseline_publications','native_pilo"
        "t_runs','native_pilot_observations','rel"
        "ease_packages','release_decisions','rele"
        "ase_policy_facts','external_handoff_auth"
        "orizations','external_receipts','release"
        "_exception_decisions') THEN\n  FOR item I"
        'N SELECT value FROM jsonb_array_elements'
        "(coalesce(payload->'required_source_read"
        "_set','[]')) LOOP\n   IF item->>'artifact"
        "_id' IS NOT NULL THEN\n    links=array_ap"
        "pend(links,(item->>'artifact_id')::uuid)"
        ';\n   END IF;\n  END LOOP;\n END IF;\n IF ta'
        "ble_name IN ('native_pilot_runs','native"
        "_pilot_observations') THEN\n  FOR item IN"
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload#>'{material_snapshot,st"
        "atistics,samples}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOR item IN SELECT value '
        'FROM jsonb_array_elements(coalesce(paylo'
        "ad#>'{material_snapshot,statistics,issue"
        "s}','[]')) LOOP\n   IF item->>'id' IS NOT"
        ' NULL THEN links=array_append(links,(ite'
        "m->>'id')::uuid); END IF;\n  END LOOP;\n  "
        "item=payload#>'{material_snapshot,statis"
        "tics,resource,fact}';\n  IF item->>'id' I"
        'S NOT NULL THEN links=array_append(links'
        ",(item->>'id')::uuid); END IF;\n END IF;\n"
        " IF table_name='release_packages' THEN\n "
        ' -- FixedObject.ref is a closed, server-'
        'resolved version reference, not arbitrar'
        'y body UUID text.\n  FOR item IN SELECT v'
        'alue FROM jsonb_array_elements(coalesce('
        "payload#>'{body,objects}','[]')) LOOP\n  "
        " container=item->'ref';\n   IF container-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "manufacturing_publication','test_run','p"
        "ilot_run','issue','change','exception','"
        "artifact','work_instruction','control_pl"
        "an','build_lot','line'])\n    AND contain"
        "er->>'id' IS NOT NULL THEN links=array_a"
        "ppend(links,(container->>'id')::uuid); E"
        'ND IF;\n  END LOOP;\n END IF;\n IF table_na'
        "me IN ('external_handoff_authorizations'"
        ",'external_delivery_intents') THEN\n  -- "
        'Only closed, owner-verified mapping and '
        'manifest references are source edges.\n  '
        "container=CASE WHEN table_name='external"
        "_handoff_authorizations' THEN payload#>'"
        "{body,declaration}' ELSE payload->'body'"
        ' END;\n  FOR item IN SELECT value FROM js'
        "onb_array_elements(coalesce(container->'"
        "mappings','[]')) LOOP\n   IF item->'ref'-"
        ">>'kind'=ANY(ARRAY['definition','enginee"
        "ring_configuration','process_revision','"
        "part','bom_revision','artifact','work_in"
        "struction','control_plan'])\n    AND item"
        "->'ref'->>'id' IS NOT NULL THEN links=ar"
        "ray_append(links,(item->'ref'->>'id')::u"
        'uid); END IF;\n  END LOOP;\n  FOR item IN '
        'SELECT value FROM jsonb_array_elements(c'
        "oalesce(container->'manifest','[]')) LOO"
        "P\n   IF item->'artifact'->>'id' IS NOT N"
        'ULL THEN links=array_append(links,(item-'
        ">'artifact'->>'id')::uuid); END IF;\n  EN"
        "D LOOP;\n END IF;\n IF table_name='release"
        "_policy_facts' THEN\n  -- These are Close"
        'd DTO configuration references fixed by '
        'the policy owner.\n  FOREACH key IN ARRAY'
        " ARRAY['definition','engineering_configu"
        "ration','manufacturing_configuration'] L"
        "OOP\n   container=payload#>ARRAY['materia"
        "l','subject_config',key];\n   IF containe"
        "r->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(container->>'id')::uuid); EN"
        'D IF;\n  END LOOP;\n END IF;\n -- These sto'
        'red fields are validated Reference conta'
        'iners. Do not feed the\n -- whole row or '
        'arbitrary content into the canonical Ref'
        'erence parser.\n IF table_name=ANY(ARRAY['
        "'proposals','proposal_item_versions','pr"
        "oposal_submissions',\n  'category_knowled"
        "ge_entries','definition_specs']) THEN\n  "
        "FOREACH key IN ARRAY ARRAY['source_refs'"
        ",'direct_source_refs','context_refs','ba"
        "seline_claim_refs'] LOOP\n   links=links "
        '|| public.m3_lifecycle_typed_links(t,c,p'
        'ayload->key);\n  END LOOP;\n END IF;\n -- M'
        'atch ItemInput.content_schema and catego'
        'ry_service._references: only\n -- commerc'
        'ial_target, voice, and competitor have n'
        "ested source contracts.\n IF table_name='"
        "proposal_item_versions' AND payload->>'k"
        "ind'='commercial_target' THEN\n  FOREACH "
        "key IN ARRAY ARRAY['target_price','cost'"
        ",'volume'] LOOP\n   links=links || public"
        ".m3_lifecycle_typed_links(t,c,payload->'"
        "content'->key->'source');\n  END LOOP;\n E"
        "LSIF table_name='category_knowledge_entr"
        "ies' AND payload->>'kind'='voice' THEN\n "
        ' links=links || public.m3_lifecycle_type'
        "d_links(t,c,payload->'content'->'represe"
        "ntative_refs');\n ELSIF table_name='categ"
        "ory_knowledge_entries' AND payload->>'ki"
        "nd'='competitor' THEN\n  FOREACH key IN A"
        "RRAY ARRAY['metrics','features','prices'"
        '] LOOP\n   FOR item IN SELECT value FROM '
        "jsonb_array_elements(coalesce(payload->'"
        "content'->key,'[]')) LOOP\n    links=link"
        's || public.m3_lifecycle_typed_links(t,c'
        ",item->'source_ref');\n   END LOOP;\n  END"
        " LOOP;\n END IF;\n IF table_name='proposal"
        "_submissions' THEN\n  container=payload->"
        "'frozen_document';\n  FOREACH key IN ARRA"
        "Y ARRAY['source_refs','direct_source_ref"
        "s','context_refs','baseline_claim_refs']"
        ' LOOP\n   links=links || public.m3_lifecy'
        'cle_typed_links(t,c,container->key);\n  E'
        'ND LOOP;\n  FOR item IN SELECT value FROM'
        ' jsonb_array_elements(coalesce(container'
        "->'items','[]')) LOOP\n   links=links || "
        "public.m3_lifecycle_source_links(t,c,'pr"
        "oposal_item_versions',item-ARRAY['item_i"
        "d','proposal_id']);\n   -- The frozen rea"
        'd projection records actual EvidenceLink'
        ' provenance here.\n   links=links || publ'
        "ic.m3_lifecycle_typed_links(t,c,item->'e"
        "vidence_links');\n  END LOOP;\n ELSIF tabl"
        "e_name='promotion_proofs' THEN\n  FOR ite"
        'm IN SELECT value FROM jsonb_array_eleme'
        "nts(coalesce(payload->'source_item_refs'"
        ",'[]')) LOOP\n   IF item->>'item_id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'item_id')::uuid); END IF;\n  END L"
        'OOP;\n END IF;\n -- Exact persisted Eviden'
        'ceLink targets supplement these immutabl'
        'e versions.\n -- Reverted links and withd'
        'rawn Claims still retain the original hi'
        'storical\n -- dependency; lifecycle clean'
        'up must not erase their audit source.\n I'
        "F table_name='proposal_item_versions' AN"
        "D payload->>'item_id' IS NOT NULL THEN\n "
        " target_kind='proposal_item'; referenced"
        "_target=(payload->>'item_id')::uuid;\n  r"
        "eferenced_version=(payload->>'version'):"
        ":integer;\n ELSIF table_name='category_kn"
        "owledge_entries' AND payload->>'id' IS N"
        "OT NULL THEN\n  target_kind='knowledge_en"
        "try'; referenced_target=(payload->>'id')"
        '::uuid;\n  referenced_version=(payload->>'
        "'version')::integer;\n ELSIF table_name='"
        "definition_specs' AND payload->>'id' IS "
        "NOT NULL THEN\n  target_kind='definition_"
        "spec'; referenced_target=(payload->>'id'"
        ')::uuid;\n  SELECT revision INTO referenc'
        'ed_version FROM public.definition_revisi'
        'ons\n   WHERE tenant_id=t AND category_id'
        "=c AND id=(payload->>'definition_id')::u"
        'uid;\n END IF;\n IF referenced_target IS N'
        'OT NULL AND referenced_version IS NOT NU'
        'LL THEN\n  SELECT coalesce(array_agg(link'
        ".evidence_id),'{}') INTO extra FROM publ"
        'ic.evidence_links link\n   WHERE link.ten'
        'ant_id=t AND link.category_id=c AND link'
        '.target_type=target_kind\n    AND link.ta'
        'rget_id=referenced_target AND link.targe'
        't_version=referenced_version;\n  links=li'
        'nks || extra;\n END IF;\n -- Child source '
        'rows point to their parent, whereas depe'
        "ndency traversal needs\n -- the parent's "
        'fixed source children as well. Keep the '
        "actual relational edge.\n IF table_name='"
        "definition_revisions' THEN\n  SELECT coal"
        "esce(array_agg(id),'{}') INTO extra FROM"
        ' (\n   SELECT id FROM public.definition_s'
        'ources WHERE tenant_id=t AND category_id'
        "=c\n    AND definition_id=(payload->>'id'"
        ')::uuid\n   UNION ALL SELECT id FROM publ'
        'ic.definition_specs WHERE tenant_id=t AN'
        'D category_id=c\n    AND definition_id=(p'
        "ayload->>'id')::uuid\n  ) children;\n  lin"
        "ks=links || extra;\n ELSIF table_name='pr"
        "oposals' THEN\n  SELECT coalesce(array_ag"
        "g(id),'{}') INTO extra FROM public.propo"
        'sal_item_versions\n   WHERE tenant_id=t A'
        'ND category_id=c AND proposal_id=(payloa'
        "d->>'id')::uuid;\n  links=links || extra;"
        "\n ELSIF table_name='proposal_items' THEN"
        "\n  SELECT coalesce(array_agg(id),'{}') I"
        'NTO extra FROM public.proposal_item_vers'
        'ions\n   WHERE tenant_id=t AND category_i'
        "d=c AND item_id=(payload->>'id')::uuid;\n"
        '  links=links || extra;\n ELSIF table_nam'
        "e='product_target_segments' THEN\n  SELEC"
        "T coalesce(array_agg(id),'{}') INTO extr"
        'a FROM public.category_knowledge_entries'
        '\n   WHERE tenant_id=t AND category_id=c '
        "AND lineage_id=(payload->>'segment_linea"
        "ge_id')::uuid\n    AND version=(payload->"
        ">'segment_version')::integer;\n  links=li"
        "nks || extra;\n ELSIF table_name='paramet"
        "er_current' THEN\n  SELECT coalesce(array"
        "_agg(id),'{}') INTO extra FROM public.pa"
        'rameter_versions\n   WHERE tenant_id=t AN'
        'D category_id=c AND parameter_id=(payloa'
        "d->>'parameter_id')::uuid\n    AND versio"
        "n=(payload->>'current_version')::integer"
        ';\n  links=links || extra;\n END IF;\n\n IF '
        "table_name IN ('work_task_versions','wor"
        "k_commitment_versions','project_status_u"
        "pdates') THEN\n  FOR item IN SELECT value"
        ' FROM jsonb_array_elements(coalesce(payl'
        "oad->'reads','[]')) LOOP\n   IF item->>'a"
        "rtifact_id' IS NOT NULL THEN links=array"
        "_append(links,(item->>'artifact_id')::uu"
        'id); END IF;\n  END LOOP;\n  IF table_name'
        "='work_task_versions' AND payload#>>'{bo"
        "dy,plan_task,id}' IS NOT NULL THEN\n   li"
        "nks=array_append(links,(payload#>>'{body"
        ",plan_task,id}')::uuid);\n  END IF;\n  IF "
        "table_name='work_commitment_versions' TH"
        "EN\n   SELECT coalesce(array_agg(id),'{}'"
        ') INTO extra FROM public.work_task_versi'
        'ons\n    WHERE tenant_id=t AND category_i'
        "d=c AND task_id=(payload->>'task_id')::u"
        "uid AND revision=(payload->>'task_revisi"
        "on')::integer;\n   links=links||extra;\n  "
        "ELSIF table_name='project_status_updates"
        "' THEN\n   FOR item IN SELECT value FROM "
        "jsonb_array_elements(coalesce(payload->'"
        "task_refs','[]')) LOOP\n    SELECT coales"
        "ce(array_agg(id),'{}') INTO extra FROM p"
        'ublic.work_task_versions\n     WHERE tena'
        'nt_id=t AND category_id=c AND task_id=(i'
        "tem->>'id')::uuid AND revision=(item->>'"
        "revision')::integer;\n    links=links||ex"
        'tra;\n   END LOOP;\n  END IF;\n END IF;\n\n I'
        "F table_name='work_commitment_reviews' T"
        'HEN\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload->'read"
        "s','[]')) LOOP\n   IF item->>'artifact_id"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(item->>'artifact_id')::uuid); END I"
        'F;\n  END LOOP;\n END IF;\n\n IF table_name='
        "'external_wait_versions' THEN\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{source_basis,arti"
        "facts}','[]')) LOOP\n   IF item->>'id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(item->>'id')::uuid); END IF;\n  END LOOP"
        ";\n  FOREACH key IN ARRAY ARRAY['mileston"
        "e','build','calendar'] LOOP\n   container"
        "=payload#>ARRAY['body',key];\n   IF conta"
        "iner->>'id' IS NOT NULL THEN links=array"
        "_append(links,(container->>'id')::uuid);"
        ' END IF;\n  END LOOP;\n  container=payload'
        "#>'{body,replaces}';\n  IF container->>'i"
        "d' IS NOT NULL THEN\n   SELECT coalesce(a"
        "rray_agg(id),'{}') INTO extra FROM publi"
        'c.external_wait_versions\n    WHERE tenan'
        't_id=t AND category_id=c AND wait_id=(co'
        "ntainer->>'id')::uuid AND revision=(cont"
        "ainer->>'revision')::integer;\n   links=l"
        'inks||extra;\n  END IF;\n END IF;\n IF tabl'
        "e_name='project_risk_followups' THEN\n  F"
        'OR item IN SELECT value FROM jsonb_array'
        "_elements(coalesce(payload#>'{source_bas"
        "is,artifacts}','[]')) LOOP\n   IF item->>"
        "'id' IS NOT NULL THEN links=array_append"
        "(links,(item->>'id')::uuid); END IF;\n  E"
        "ND LOOP;\n END IF;\n\n IF table_name IN ('k"
        "nowledge_candidate_versions','knowledge_"
        "candidate_currents','knowledge_applicabi"
        "lity_assessments','knowledge_rule_versio"
        "ns','knowledge_rule_currents') THEN\n  FO"
        "REACH key IN ARRAY ARRAY['previous_id','"
        "version_id','candidate_version_id','asse"
        "ssment_id','publication_id'] LOOP\n   IF "
        'payload->>key IS NOT NULL THEN links=arr'
        'ay_append(links,(payload->>key)::uuid); '
        'END IF;\n  END LOOP;\n  FOR item IN SELECT'
        ' value FROM jsonb_array_elements(coalesc'
        "e(payload#>'{source_basis,artifacts}','["
        "]')) LOOP\n   IF item->>'id' IS NOT NULL "
        "THEN links=array_append(links,(item->>'i"
        "d')::uuid); END IF;\n  END LOOP;\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload->'reads','[]')) LO"
        "OP\n   IF item->>'artifact_id' IS NOT NUL"
        'L THEN links=array_append(links,(item->>'
        "'artifact_id')::uuid); END IF;\n  END LOO"
        'P;\n  FOR item IN SELECT value FROM jsonb'
        "_array_elements(coalesce(payload#>'{sour"
        "ce_basis,result_receipts}','[]')) LOOP\n "
        "  IF item->>'receipt_id' IS NOT NULL THE"
        "N links=array_append(links,(item->>'rece"
        "ipt_id')::uuid); END IF;\n   IF item->>'r"
        "ow_id' IS NOT NULL THEN links=array_appe"
        "nd(links,(item->>'row_id')::uuid); END I"
        'F;\n  END LOOP;\n  FOR item IN SELECT valu'
        'e FROM jsonb_array_elements(coalesce(pay'
        "load#>'{source_basis,professional,fact_r"
        "efs}','[]')) LOOP\n   IF item->>'id' IS N"
        'OT NULL THEN links=array_append(links,(i'
        "tem->>'id')::uuid); END IF;\n  END LOOP;\n"
        "  IF payload#>>'{source_basis,target,id}"
        "' IS NOT NULL THEN links=array_append(li"
        "nks,(payload#>>'{source_basis,target,id}"
        "')::uuid); END IF;\n END IF;\n\n IF table_n"
        "ame IN ('field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds') THEN\n  FOREACH key IN ARRAY ARRAY["
        "'previous_id','version_id','feedback_ver"
        "sion_id'] LOOP\n   IF payload->>key IS NO"
        'T NULL THEN links=array_append(links,(pa'
        'yload->>key)::uuid); END IF;\n  END LOOP;'
        '\n  FOR item IN SELECT value FROM jsonb_a'
        "rray_elements(coalesce(payload#>'{source"
        "_basis,artifacts}','[]')) LOOP\n   IF ite"
        "m->>'id' IS NOT NULL THEN links=array_ap"
        "pend(links,(item->>'id')::uuid); END IF;"
        '\n  END LOOP;\n  FOREACH key IN ARRAY ARRA'
        "Y['engineering_configuration','manufactu"
        "ring_configuration','batch'] LOOP\n   IF "
        "payload#>>ARRAY['body','location',key,'i"
        "d'] IS NOT NULL THEN links=array_append("
        "links,(payload#>>ARRAY['body','location'"
        ",key,'id'])::uuid); END IF;\n  END LOOP;\n"
        '  FOR item IN SELECT value FROM jsonb_ar'
        "ray_elements(coalesce(payload#>'{source_"
        "basis,result_receipts}','[]')) LOOP\n   I"
        "F item->>'receipt_id' IS NOT NULL THEN l"
        "inks=array_append(links,(item->>'receipt"
        "_id')::uuid); END IF;\n   IF item->>'row_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'row_id')::uuid); END IF;\n"
        '  END LOOP;\n END IF;\n IF table_name IN ('
        "'change_request_versions','change_graph_"
        "captures') THEN\n  FOR container IN SELEC"
        'T value FROM jsonb_each(coalesce(payload'
        "#>'{source_basis,owners}','{}')) LOOP\n  "
        " IF container->>'feedback_version_id' IS"
        ' NOT NULL THEN links=array_append(links,'
        "(container->>'feedback_version_id')::uui"
        'd); END IF;\n  END LOOP;\n END IF;\n\n -- Cl'
        'osed native Field plan and occurrence re'
        'ferences, never arbitrary UUID prose.\n I'
        "F table_name='controlled_change_selectio"
        "n_facts' AND payload->>'basis_kind'='fie"
        "ld_intent' THEN\n  IF payload->>'feedback"
        "_version_id' IS NOT NULL THEN\n   links=a"
        "rray_append(links,(payload->>'feedback_v"
        "ersion_id')::uuid);\n  END IF;\n END IF;\n "
        "IF table_name='change_implementation_cap"
        "tures'\n  AND payload#>>'{occurrence_snap"
        "shot,schema_version}'='pdos-field-change"
        "-implementation-occurrence-v1' THEN\n  FO"
        "REACH key IN ARRAY ARRAY['feedback_versi"
        "on_id','selection_id'] LOOP\n   IF payloa"
        "d#>>ARRAY['occurrence_snapshot',key] IS "
        'NOT NULL THEN\n    links=array_append(lin'
        "ks,(payload#>>ARRAY['occurrence_snapshot"
        "',key])::uuid);\n   END IF;\n  END LOOP;\n "
        "END IF;\n\n IF table_name='change_completi"
        "on_records' THEN\n  FOREACH key IN ARRAY "
        "ARRAY['project_id','change_version_id','"
        "order_record_id','shared_proof_id'] LOOP"
        '\n   IF payload->>key IS NOT NULL THEN li'
        'nks=array_append(links,(payload->>key)::'
        'uuid); END IF;\n  END LOOP;\n  FOR item IN'
        ' SELECT value FROM jsonb_array_elements('
        "coalesce(payload->'required_source_read_"
        "set','[]')) LOOP\n   IF item->>'artifact_"
        "id' IS NOT NULL THEN links=array_append("
        "links,(item->>'artifact_id')::uuid); END"
        " IF;\n  END LOOP;\n  IF payload#>>'{native"
        "_input,lot,id}' IS NOT NULL THEN links=a"
        "rray_append(links,(payload#>>'{native_in"
        "put,lot,id}')::uuid); END IF;\n  FOR item"
        ' IN SELECT value FROM jsonb_array_elemen'
        "ts(coalesce(payload#>'{native_input,samp"
        "le_refs}','[]')) LOOP\n   links=array_app"
        "end(links,(item->>'id')::uuid);\n  END LO"
        'OP;\n  FOR item IN SELECT value FROM json'
        "b_array_elements(coalesce(payload#>'{nat"
        "ive_input,mappings}','[]')) LOOP\n   SELE"
        "CT coalesce(array_agg(id),'{}') INTO ext"
        'ra FROM verification_run_versions\n    WH'
        'ERE tenant_id=t AND category_id=c AND ru'
        "n_id=(item#>>'{run,id}')::uuid AND revis"
        "ion=(item#>>'{run,revision}')::integer;\n"
        '   links=links||extra; links=array_appen'
        "d(links,(item->>'sample_id')::uuid);\n  E"
        'ND LOOP;\n END IF;\n\n -- Closed native own'
        'er DTOs: retain exact outputs and native'
        " execution/report rows.\n IF table_name='"
        "change_completion_records' THEN\n  FOR it"
        'em IN SELECT value FROM jsonb_array_elem'
        "ents(coalesce(payload#>'{fact_snapshot,o"
        "utput_refs}','[]')) LOOP\n   IF item->>'k"
        "ind'='test_run' THEN\n    SELECT coalesce"
        "(array_agg(id),'{}') INTO extra FROM ver"
        'ification_run_versions\n     WHERE tenant'
        '_id=t AND category_id=c AND run_id=(item'
        "->>'id')::uuid AND revision=(item->>'rev"
        "ision')::integer;\n    links=links||extra"
        ";\n   ELSIF item->>'kind'=ANY(ARRAY['engi"
        "neering_configuration','manufacturing_co"
        "nfiguration','build','sample']) THEN\n   "
        " links=array_append(links,(item->>'id'):"
        ':uuid);\n   END IF;\n  END LOOP;\n  IF payl'
        "oad#>>'{owner_basis,schema_version}'='pd"
        "os-native-build-adoption-read-v1' THEN\n "
        "  FOREACH key IN ARRAY ARRAY['previous_b"
        "uild','successor_build','actual_configur"
        "ation','lot','start'] LOOP\n    IF payloa"
        "d#>>ARRAY['owner_basis',key,'id'] IS NOT"
        ' NULL THEN\n     links=array_append(links'
        ",(payload#>>ARRAY['owner_basis',key,'id'"
        '])::uuid);\n    END IF;\n   END LOOP;\n  EL'
        "SIF payload#>>'{owner_basis,schema_versi"
        "on}'='pdos-native-change-run-verificatio"
        "n-v1' THEN\n   FOR container IN SELECT va"
        "lue FROM jsonb_each(coalesce(payload#>'{"
        "owner_basis,runs}','{}')) LOOP\n    FOREA"
        "CH key IN ARRAY ARRAY['run_version_id','"
        "request_version_id','projection_id'] LOO"
        'P\n     IF container->>key IS NOT NULL TH'
        'EN links=array_append(links,(container->'
        '>key)::uuid); END IF;\n    END LOOP;\n   E'
        'ND LOOP;\n  END IF;\n END IF;\n\n -- F: only'
        ' server-verified fixed answer proofs est'
        'ablish these dependency edges.\n -- Nativ'
        'e deferred atoms bind these exact arrays'
        ' to real source ledgers.\n IF table_name '
        "IN ('category_knowledge_entries','knowle"
        "dge_candidate_versions','knowledge_rule_"
        "versions','knowledge_answer_reviews','kn"
        "owledge_gap_submissions') THEN\n  contain"
        "er=CASE table_name WHEN 'category_knowle"
        "dge_entries' THEN payload->'answer_sourc"
        "es'\n   WHEN 'knowledge_candidate_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   WHEN 'knowledge_rule_version"
        "s' THEN payload#>'{source_basis,answer_s"
        "ources}'\n   ELSE payload->'source_proof'"
        ' END;\n  -- Only these native knowledge r'
        'ows have an optional answer-derived proo'
        'f.\n  -- to_jsonb(row) represents an SQL '
        'NULL column as a JSON null member.\n  IF '
        "table_name IN ('category_knowledge_entri"
        "es','knowledge_candidate_versions','know"
        "ledge_rule_versions') THEN\n   container="
        "coalesce(nullif(container,'null'::jsonb)"
        ",'[]'::jsonb);\n  END IF;\n  -- Review/Gap"
        ' proof remains required and reaches the '
        'strict resolver unchanged.\n  links=links'
        '||public.assistant_source_lifecycle_link'
        's(t,c,container);\n END IF;\n\n -- G privat'
        'e outbound body copies have no category '
        'column. Only the fixed\n -- server footpr'
        'int subset for this REAL category establ'
        "ishes retention edges.\n IF table_name='d"
        "ingtalk_deliveries' THEN\n  IF payload->>"
        "'tenant_id' IS DISTINCT FROM t::text OR "
        "c IS NULL THEN\n   RAISE EXCEPTION 'Deliv"
        "ery retention scope mismatch' USING ERRC"
        "ODE='23514'; END IF;\n  SELECT coalesce(j"
        "sonb_agg(value),'[]'::jsonb) INTO contai"
        'ner\n   FROM jsonb_array_elements(coalesc'
        "e(payload->'source_dependencies','[]'::j"
        "sonb))\n   WHERE value->>'category_id'=c:"
        ':text;\n  links=links||public.assistant_s'
        'ource_lifecycle_links(t,c,container);\n E'
        'ND IF;\n RETURN links;\nEND;\n$function$\n'
    ),
    (
        'CREATE OR REPLACE FUNCTION public.m3_lif'
        'ecycle_nodes(t uuid, c uuid, identities '
        'uuid[] DEFAULT NULL::uuid[])\n RETURNS TA'
        'BLE(table_name text, node_id uuid, links'
        ' uuid[])\n LANGUAGE plpgsql\n STABLE SECUR'
        "ITY DEFINER\n SET search_path TO 'pg_cata"
        "log', 'public', 'pg_temp'\nAS $function$\n"
        'DECLARE name text; payload jsonb; contro'
        'ls uuid[];\nBEGIN\n IF identities IS NULL '
        "THEN\n  SELECT coalesce(array_agg(id),'{}"
        "') INTO controls FROM public.action_rece"
        'ipts\n   WHERE tenant_id=t AND category_i'
        "d=c AND operation LIKE 'evidence.lifecyc"
        "le.%';\n ELSE controls='{}'; END IF;\n FOR"
        'EACH name IN ARRAY CASE WHEN identities '
        "IS NULL THEN ARRAY['agent_runs','action_"
        "receipts','actual_configurations','artif"
        "act_versions','audit_entries','bom_lines"
        "','bom_revisions','build_authorization_d"
        "ecisions','build_current_authorizations'"
        ",'build_current_execution_assessments','"
        "build_execution_assessments','build_lots"
        "','build_operational_current','build_ope"
        "rational_facts','build_readiness','build"
        "_starts','builds','capa_current_observat"
        "ions','capa_current_verification_rules',"
        "'capa_named_verification_reviews','capa_"
        "observation_facts','capa_remediation_lin"
        "ks','capa_verification_evidence','capa_v"
        "erification_rule_facts','change_approval"
        "_records','change_dependency_clocks','ch"
        "ange_graph_captures','change_implementat"
        "ion_captures','change_implementation_rec"
        "ords','change_order_records','change_req"
        "uest_currents','change_request_versions'"
        ",'claim_consumptions','claims','controll"
        "ed_change_coverage_currents','controlled"
        "_change_coverage_facts','controlled_chan"
        "ge_policy_currents','controlled_change_p"
        "olicy_facts','controlled_change_selectio"
        "n_currents','controlled_change_selection"
        "_facts','cost_current_inputs','cost_esti"
        "mates','cost_input_snapshots','cost_sour"
        "ce_captures','definition_revisions','def"
        "inition_sources','definition_specs','eng"
        "ineering_configurations','manufacturing_"
        "baseline_document_links','manufacturing_"
        "preparation_currents','manufacturing_pre"
        "paration_versions','measurement_import_c"
        "aptures','operational_material_holds','o"
        "perational_resource_occupancies','origin"
        "al_scan_requests','original_scan_results"
        "','original_security','outbox_events','p"
        "arts','plan_proposals','plan_revisions',"
        "'process_revisions','product_variants','"
        "professional_authority_current','profess"
        "ional_authority_facts','project_product_"
        "links','project_tasks','project_work_pac"
        "kages','projects','quality_current_issue"
        "s','quality_current_policies','quality_e"
        "vent_failure_links','quality_failure_map"
        "s','quality_issue_versions','quality_pol"
        "icy_facts','request_keys','runs','sample"
        "_allocations','sample_current_readiness'"
        ",'sample_readiness_facts','sample_run_us"
        "ages','sample_units','sample_usage_senti"
        "nels','supply_current_snapshots','supply"
        "_kit_projections','supply_snapshots','su"
        "pply_source_captures','task_dependencies"
        "','test_measurements','test_resource_cur"
        "rent','test_resource_facts','test_resour"
        "ce_reservations','test_result_actions','"
        "test_result_projections','uploaded_origi"
        "nals','variant_revisions','verification_"
        "actual_method_applicabilities','verifica"
        "tion_actual_method_batches','verificatio"
        "n_current_actual_methods','verification_"
        "current_formal_requests','verification_c"
        "urrent_preparations','verification_curre"
        "nt_runs','verification_formal_requests',"
        "'verification_handoff_facts','verificati"
        "on_launch_facts','verification_method_ap"
        "plicabilities','verification_preparation"
        "s','verification_run_identities','verifi"
        "cation_run_versions','verification_windo"
        "w_proposals','work_requests','proposals'"
        ",'proposal_items','proposal_item_version"
        "s','proposal_revisions','proposal_source"
        "s','proposal_submissions','proposal_deci"
        "sions','project_open_items','category_kn"
        "owledge_entries','category_knowledge_cur"
        "rent','product_target_segments','paramet"
        "er_versions','parameter_current','promot"
        "ion_proofs','evidence_links','claim_with"
        "drawals','manufacturing_baseline_publica"
        "tions','manufacturing_publication_curren"
        "ts','manufacturing_publication_documents"
        "','native_pilot_runs','native_pilot_curr"
        "ents','native_pilot_observations','relea"
        "se_packages','release_package_currents',"
        "'release_decisions','release_policy_fact"
        "s','release_policy_currents','external_h"
        "andoff_authorizations','external_deliver"
        "y_intents','external_receipts','external"
        "_handoff_currents','release_exception_de"
        "cisions','release_exception_currents','w"
        "ork_commitment_reviews','work_commitment"
        "_review_currents','work_task_versions','"
        "work_task_currents','work_commitment_ver"
        "sions','work_commitment_currents','proje"
        "ct_status_updates','external_wait_versio"
        "ns','external_wait_currents','project_ri"
        "sk_followups','project_risk_followup_cur"
        "rents','knowledge_candidate_versions','k"
        "nowledge_candidate_currents','knowledge_"
        "applicability_assessments','knowledge_ru"
        "le_versions','knowledge_rule_currents','"
        "field_feedback_versions','field_feedback"
        "_currents','field_response_records','kno"
        "wledge_answer_reviews','knowledge_gap_su"
        "bmissions'] ELSE ARRAY[\n  'artifact_vers"
        "ions','claims','definition_revisions','d"
        "efinition_sources','definition_specs',\n "
        " 'proposals','proposal_items','proposal_"
        "item_versions','proposal_submissions','p"
        "roposal_decisions',\n  'category_knowledg"
        "e_entries','category_knowledge_current',"
        "'parameter_versions','parameter_current'"
        ",\n  'evidence_links','promotion_proofs',"
        "'native_pilot_runs','native_pilot_curren"
        "ts','native_pilot_observations','release"
        "_packages','release_package_currents','r"
        "elease_decisions','release_policy_facts'"
        ",'release_policy_currents','external_han"
        "doff_authorizations','external_delivery_"
        "intents','external_receipts','external_h"
        "andoff_currents','release_exception_deci"
        "sions','release_exception_currents','wor"
        "k_commitment_reviews','work_commitment_r"
        "eview_currents','work_task_versions','wo"
        "rk_task_currents','work_commitment_versi"
        "ons','work_commitment_currents','project"
        "_status_updates','external_wait_versions"
        "','external_wait_currents','project_risk"
        "_followups','project_risk_followup_curre"
        "nts','knowledge_candidate_versions','kno"
        "wledge_candidate_currents','knowledge_ap"
        "plicability_assessments','knowledge_rule"
        "_versions','knowledge_rule_currents','fi"
        "eld_feedback_versions','field_feedback_c"
        "urrents','field_response_records','knowl"
        "edge_answer_reviews','knowledge_gap_subm"
        "issions'] END LOOP\n  FOR payload IN EXEC"
        "UTE CASE WHEN name=ANY(ARRAY['audit_entr"
        "ies','outbox_events','request_keys'])\n  "
        " THEN format('SELECT to_jsonb(x) FROM pu"
        'blic.%I x JOIN public.action_receipts r '
        'ON r.id=x.receipt_id AND r.tenant_id=x.t'
        'enant_id WHERE x.tenant_id=$1 AND r.cate'
        "gory_id=$2',name)\n   ELSE format('SELECT"
        ' to_jsonb(x) FROM public.%I x WHERE tena'
        'nt_id=$1 AND category_id=$2 AND ($3 IS N'
        "ULL OR %I=ANY($3))',name,\n    CASE name "
        "WHEN 'category_knowledge_current' THEN '"
        "lineage_id'\n     WHEN 'parameter_current"
        "' THEN 'parameter_id' ELSE 'id' END)\n   "
        'END USING t,c,identities LOOP\n   IF (pay'
        "load->>'receipt_id')::uuid=ANY(controls)"
        " OR\n    (name='action_receipts' AND payl"
        "oad->>'operation' LIKE 'evidence.lifecyc"
        "le.%') THEN CONTINUE; END IF;\n   table_n"
        "ame=name;\n   node_id=CASE name WHEN 'cat"
        "egory_knowledge_current' THEN (payload->"
        ">'lineage_id')::uuid\n    WHEN 'parameter"
        "_current' THEN (payload->>'parameter_id'"
        ")::uuid ELSE (payload->>'id')::uuid END;"
        '\n   IF identities IS NULL THEN links=pub'
        'lic.m3_lifecycle_row_links(t,c,name,payl'
        'oad);\n   ELSE links=public.m3_lifecycle_'
        'source_links(t,c,name,payload); END IF;\n'
        "   -- Preserve predecessor's conservativ"
        'e legacy graph; M3-only nodes use\n   -- '
        'strictly typed/relational links. Root lo'
        'okup never uses free-text UUIDs.\n   IF i'
        "dentities IS NULL AND name<>ALL(ARRAY['n"
        "ative_pilot_runs','native_pilot_currents"
        "','native_pilot_observations','release_p"
        "ackages','release_package_currents','rel"
        "ease_decisions','release_policy_facts','"
        "release_policy_currents','external_hando"
        "ff_authorizations','external_delivery_in"
        "tents','external_receipts','external_han"
        "doff_currents','release_exception_decisi"
        "ons','release_exception_currents','work_"
        "commitment_reviews','work_commitment_rev"
        "iew_currents','work_task_versions','work"
        "_task_currents','work_commitment_version"
        "s','work_commitment_currents','project_s"
        "tatus_updates','external_wait_versions',"
        "'external_wait_currents','project_risk_f"
        "ollowups','project_risk_followup_current"
        "s','manufacturing_baseline_publications'"
        ",'manufacturing_publication_currents','m"
        "anufacturing_publication_documents','pro"
        "posals','proposal_items','proposal_item_"
        "versions','proposal_revisions','proposal"
        "_sources','proposal_submissions','propos"
        "al_decisions','project_open_items','cate"
        "gory_knowledge_entries','category_knowle"
        "dge_current','product_target_segments','"
        "parameter_versions','parameter_current',"
        "'promotion_proofs','evidence_links','cla"
        "im_withdrawals','knowledge_candidate_ver"
        "sions','knowledge_candidate_currents','k"
        "nowledge_applicability_assessments','kno"
        "wledge_rule_versions','knowledge_rule_cu"
        "rrents','field_feedback_versions','field"
        "_feedback_currents','field_response_reco"
        "rds','knowledge_answer_reviews','knowled"
        "ge_gap_submissions']) THEN\n    links=lin"
        'ks || public.kernel_lifecycle_links(name'
        ',payload);\n   END IF;\n   RETURN NEXT;\n  '
        'END LOOP;\n END LOOP;\n\n -- Read exactly t'
        'he retained metadata, never Delivery.pay'
        'load. One personal\n -- answer may appear'
        ' in several categories, each with its ow'
        'n source subset.\n FOR payload IN\n  SELEC'
        "T jsonb_build_object('id',d.id,'tenant_i"
        "d',d.tenant_id,\n   'content_kind',d.cont"
        "ent_kind,'source_dependencies',d.source_"
        'dependencies)\n  FROM public.dingtalk_del'
        'iveries d\n  WHERE d.tenant_id=t AND d.co'
        "ntent_kind='answer'\n   AND (identities I"
        'S NULL OR d.id=ANY(identities))\n   AND E'
        'XISTS(SELECT 1 FROM jsonb_array_elements'
        '(d.source_dependencies) dependency\n    W'
        "HERE dependency->>'category_id'=c::text)"
        "\n LOOP\n  table_name='dingtalk_deliveries"
        "'; node_id=(payload->>'id')::uuid;\n  lin"
        'ks=public.m3_lifecycle_source_links(t,c,'
        'table_name,payload);\n  RETURN NEXT;\n END'
        ' LOOP;\nEND;\n$function$\n'
    ),
    (
        'DROP FUNCTION public.dingtalk_summary_re'
        'ference_clock()'
    ),
    'DROP FUNCTION public.dingtalk_summary_identity_guard()',
    (
        'DROP FUNCTION public.dingtalk_summary_ca'
        'ncel_lost(uuid,uuid)'
    ),
    (
        'DROP FUNCTION public.dingtalk_lock_summa'
        'ry_binding(uuid,uuid)'
    ),
    (
        'DROP FUNCTION public.dingtalk_pending_su'
        'mmaries(uuid,integer)'
    ),
    (
        'DROP FUNCTION public.dingtalk_summary_re'
        'ference(uuid,uuid)'
    ),
    (
        'DROP POLICY summary_dispatch_metadata ON'
        ' public.dingtalk_applications'
    ),
    (
        'DROP POLICY summary_dispatch_metadata ON'
        ' public.dingtalk_account_bindings'
    ),
    'DROP TABLE public.dingtalk_summary_deliveries',
)
