"""Frozen B7 shared decision schema; retains T1 expiry and actual professional intervals."""

FUNCTIONS = (('assert_capa_publication_atom',
  '4655ff7b0b717689f031aab0c73bd2028f19ca0613e836f0b152512758927977',
  '4712787c21b0a7b794d5c96f4be3811dd560afada2ae8cb5315fbbf9d839d230',
  'CREATE OR REPLACE FUNCTION public.assert_capa_publication_atom(table_name text, tid uuid, sid '
  'uuid)\n'
  ' RETURNS void\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE n jsonb; body jsonb; anchor jsonb; original_id uuid; original_rev integer;\n'
  '  op_name text; family text; tier_value text; kind_value text; c confirmations%ROWTYPE;\n'
  '  r action_receipts%ROWTYPE; previous jsonb; dependency jsonb; child jsonb; actual_time '
  'timestamptz;\n'
  'BEGIN\n'
  '  CASE table_name\n'
  "    WHEN 'capa_verification_rule_facts' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_verification_rule_facts f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.verification.rule.import'; family := 'capa_verification_rule';\n"
  "      tier_value := 'host_import'; kind_value := 'rule';\n"
  "    WHEN 'capa_observation_facts' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_observation_facts f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.observation.record'; family := 'capa_observation';\n"
  "      tier_value := 'T1'; kind_value := 'observation';\n"
  "    WHEN 'capa_named_verification_reviews' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_named_verification_reviews f WHERE f.tenant_id=tid '
  'AND f.id=sid;\n'
  "      op_name := 'quality.capa.verification.review'; family := "
  "'capa_named_verification_review';\n"
  "      tier_value := 'T2'; kind_value := 'review';\n"
  "    WHEN 'capa_verification_evidence' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_verification_evidence f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.verification.candidate.record'; family := "
  "'capa_verification_candidate';\n"
  "      tier_value := 'T1'; kind_value := 'candidate';\n"
  "    ELSE RAISE EXCEPTION 'Unsupported CAPA publication target';\n"
  '  END CASE;\n'
  "  IF n IS NULL OR NOT COALESCE(isfinite((n->>'created_at')::timestamptz),false)\n"
  '    OR NOT EXISTS (SELECT 1 FROM principals WHERE tenant_id=tid\n'
  "    AND id=(n->>'writer_id')::uuid AND kind='human' AND active)\n"
  '    OR NOT EXISTS (SELECT 1 FROM grants WHERE tenant_id=tid\n'
  "      AND category_id=public.category_for_product((n->>'product_id')::uuid) AND "
  "principal_id=(n->>'writer_id')::uuid\n"
  "      AND can_write AND (expires_at IS NULL OR expires_at>(n->>'created_at')::timestamptz)) "
  'THEN\n'
  "    RAISE EXCEPTION 'CAPA publication requires exact target and named actual human'; END IF;\n"
  "  IF kind_value='candidate' THEN\n"
  "    anchor := n->'input_snapshot'->'stable_anchor';\n"
  "    original_id := (n->>'issue_version_id')::uuid; original_rev := "
  "(n->>'issue_revision')::integer;\n"
  "    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot')='object'\n"
  "      AND (n->'input_snapshot') ?& "
  "ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor']\n"
  '      AND '
  "((n->'input_snapshot')-ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor'])='{}'::jsonb\n"
  "      AND jsonb_typeof(n->'input_snapshot'->'semantic')='object'\n"
  "      AND n->>'owner_id'=anchor->'origin'->>'owner_id'\n"
  "      AND n->>'visibility'=anchor->'origin'->>'visibility'\n"
  "      AND ((n->'input_snapshot'->'shared_proof')-ARRAY['id','tier'])='{}'::jsonb\n"
  "      AND NOT ((n->'input_snapshot'->'semantic') ? 'confirmation_token')\n"
  "      AND NOT ((n->'input_snapshot'->'semantic') ? 'approval_token')\n"
  "      AND n->'candidate_binding'->'basis'=n->'basis_snapshot'\n"
  "      AND n->'candidate_snapshot'->'binding'=n->'candidate_binding'\n"
  "      AND n->'candidate_snapshot'->>'inspection_sha256'=n->>'inspection_sha256'\n"
  "      AND n->'basis_snapshot'->>'basis_sha256'=n->>'basis_sha256'\n"
  '      AND '
  "n->'candidate_snapshot'->'required_source_read_set'=n->'required_source_read_set',false) THEN\n"
  "      RAISE EXCEPTION 'Candidate requires exact frozen unknown binding/inspection and no-token "
  "semantic'; END IF;\n"
  '    PERFORM '
  "assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',\n"
  "      n->'source_basis'->'artifact_sources',n->>'visibility',(n->>'owner_id')::uuid);\n"
  "    c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,\n"
  "      op_name,n->'input_snapshot'->'shared_proof',(n->>'created_at')::timestamptz);\n"
  "    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot'->'proof_consumed_at')='string'\n"
  "      AND n->'input_snapshot'->>'proof_consumed_at' ~ "
  "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$'\n"
  "      AND c.created_at<=(n->'input_snapshot'->>'proof_consumed_at')::timestamptz\n"
  '      AND '
  "(n->'input_snapshot'->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) "
  'THEN\n'
  "      RAISE EXCEPTION 'Candidate retains actual consumed and saved clocks'; END IF;\n"
  '  ELSE\n'
  "    body := n->'fact_body'->'body'; anchor := n->'anchor_snapshot';\n"
  "    original_id := (n->>'origin_issue_version_id')::uuid;\n"
  "    original_rev := (n->>'origin_issue_revision')::integer;\n"
  "    IF n->>'operation' IS DISTINCT FROM op_name OR n->>'tier' IS DISTINCT FROM tier_value\n"
  "      OR n->>'fact_kind' IS DISTINCT FROM kind_value\n"
  "      OR ROW(n->>'actor_id',n->>'requester_id') IS DISTINCT FROM "
  "ROW(n->>'writer_id',n->>'writer_id') THEN\n"
  "      RAISE EXCEPTION 'CAPA fact actual operation, tier and writer must match'; END IF;\n"
  '    PERFORM '
  "assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',\n"
  "      n->'source_basis',n->>'visibility',(n->>'owner_id')::uuid);\n"
  "    IF tier_value<>'host_import' THEN\n"
  "      c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,\n"
  '        '
  "op_name,jsonb_build_object('id',n->'shared_proof_id','tier',tier_value),(n->>'created_at')::timestamptz);\n"
  "      IF NOT COALESCE((n->>'shared_proof_revision')::integer=c.revision\n"
  "        AND (n->>'proof_expires_at')::timestamptz=c.expires_at AND "
  "n->>'token_sha256'=c.token_hash\n"
  "        AND n->>'material_sha256'=c.payload_digest AND "
  "c.created_at<=(n->>'proof_consumed_at')::timestamptz\n"
  "        AND (n->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) "
  'THEN\n'
  "        RAISE EXCEPTION 'CAPA fact requires exact actual shared proof fields and consumption "
  "clock'; END IF;\n"
  '    END IF;\n'
  '  END IF;\n'
  "  PERFORM assert_capa_fact_origin(tid,(n->>'product_id')::uuid,(n->>'project_id')::uuid,\n"
  '    '
  "(n->>'issue_id')::uuid,(n->>'capa_id')::uuid,original_id,original_rev,n->>'purpose',n->>'nature',\n"
  "    anchor,n->'required_source_read_set',n->>'visibility',(n->>'writer_id')::uuid);\n"
  "  IF kind_value IN ('rule','observation') AND n->>'previous_fact_id' IS NOT NULL THEN\n"
  "    IF kind_value='rule' THEN\n"
  '      SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f\n'
  "        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  '    ELSE\n'
  '      SELECT to_jsonb(f) INTO previous FROM capa_observation_facts f\n'
  "        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  '    END IF;\n'
  "    IF previous IS NULL OR previous->>'purpose' IS DISTINCT FROM n->>'purpose' THEN\n"
  "      RAISE EXCEPTION 'CAPA successor retains exact complete original purpose'; END IF;\n"
  '  END IF;\n'
  '  r := '
  "assert_quality_followup_receipt(tid,(n->>'product_id')::uuid,sid,(n->>'revision')::integer,\n"
  "    op_name,family,(n->>'writer_id')::uuid,n->>'visibility',n->>'status');\n"
  "  IF jsonb_typeof(r.result->'revision') IS DISTINCT FROM 'number'\n"
  "    OR NOT COALESCE(r.result->>'revision' ~ '^[1-9][0-9]*$',false)\n"
  "    OR r.result->'revision' IS DISTINCT FROM n->'revision'\n"
  "    OR r.created_at<(n->>'created_at')::timestamptz THEN\n"
  "    RAISE EXCEPTION 'CAPA receipt retains exact numeric revision and actual save ordering'; END "
  'IF;\n'
  "  IF r.intent_digest IS DISTINCT FROM n->>'intent_digest' THEN\n"
  "    RAISE EXCEPTION 'CAPA publication uses actual common intent, not domain intent'; END IF;\n"
  "  IF tier_value<>'host_import' AND (c.snapshot->>'operation' IS DISTINCT FROM op_name\n"
  "    OR c.snapshot->'required_source_read_set' IS DISTINCT FROM n->'required_source_read_set') "
  'THEN\n'
  "    RAISE EXCEPTION 'CAPA proof review retains operation and exact complete read set'; END IF;\n"
  "  IF kind_value='candidate' THEN\n"
  '    IF '
  "(r.result-ARRAY['id','revision','status','candidate_binding_sha256','inspection_sha256'])<>'{}'::jsonb\n"
  "      OR r.result->>'candidate_binding_sha256' IS DISTINCT FROM n->>'binding_sha256'\n"
  "      OR r.result->>'inspection_sha256' IS DISTINCT FROM n->>'inspection_sha256' THEN\n"
  "      RAISE EXCEPTION 'Candidate receipt binds actual non-cyclic binding and inspection "
  "hashes'; END IF;\n"
  '  ELSE\n'
  "    IF (r.result-ARRAY['id','revision','status','fact_kind','payload_sha256'])<>'{}'::jsonb\n"
  "      OR r.command_id IS DISTINCT FROM (n->>'command_id')::uuid\n"
  "      OR r.result->>'fact_kind' IS DISTINCT FROM kind_value\n"
  "      OR r.result->>'payload_sha256' IS DISTINCT FROM n->>'payload_sha256' THEN\n"
  "      RAISE EXCEPTION 'CAPA fact receipt binds actual command and body payload hash'; END IF;\n"
  '  END IF;\n'
  "  IF kind_value IN ('rule','observation') THEN\n"
  "    IF kind_value='rule' THEN\n"
  "      IF NOT COALESCE(isfinite((n->>'valid_from')::timestamptz)\n"
  "        AND isfinite((n->>'valid_until')::timestamptz),false) THEN\n"
  "        RAISE EXCEPTION 'Rule publication retains finite fixed validity clocks'; END IF;\n"
  '      IF NOT EXISTS (SELECT 1 FROM capa_current_verification_rules p WHERE p.tenant_id=tid\n'
  "        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid\n"
  "        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid\n"
  "        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid\n"
  "        AND p.fact_revision=(n->>'revision')::integer) THEN\n"
  "        RAISE EXCEPTION 'Rule publication and its exact Current must commit together'; END IF;\n"
  "      IF n->>'previous_fact_id' IS NOT NULL THEN\n"
  '        SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f\n'
  "          WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  "        IF previous->>'issuer_key' IS DISTINCT FROM n->>'issuer_key'\n"
  "          OR previous->>'external_id' IS DISTINCT FROM n->>'external_id'\n"
  "          OR (n->>'issuer_epoch')::integer<(previous->>'issuer_epoch')::integer THEN\n"
  "          RAISE EXCEPTION 'Rule successor preserves external series and cannot rewind issuer "
  "epoch'; END IF;\n"
  '      END IF;\n'
  '    ELSE\n'
  '      IF NOT EXISTS (SELECT 1 FROM capa_current_observations p WHERE p.tenant_id=tid\n'
  "        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid\n"
  "        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid\n"
  "        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid\n"
  "        AND p.fact_revision=(n->>'revision')::integer) THEN\n"
  "        RAISE EXCEPTION 'Observation and its exact Current must commit together'; END IF;\n"
  "      actual_time := (body->'at'->>'occurred_at')::timestamptz;\n"
  "      IF NOT COALESCE((n->>'observed_from')::timestamptz<(n->>'observed_until')::timestamptz\n"
  "        AND (n->>'observed_until')::timestamptz<=actual_time\n"
  "        AND actual_time<=(n->>'created_at')::timestamptz\n"
  "        AND jsonb_typeof(body->'records')='array' AND jsonb_array_length(body->'records')>0\n"
  "        AND jsonb_typeof(body->'targets')='array' AND "
  "jsonb_array_length(body->'targets')>0,false)\n"
  "        OR EXISTS (SELECT 1 FROM jsonb_array_elements(body->'records') x WHERE NOT COALESCE(\n"
  "          (x->>'occurred_at')::timestamptz BETWEEN (n->>'observed_from')::timestamptz\n"
  "            AND (n->>'observed_until')::timestamptz\n"
  "          AND EXISTS (SELECT 1 FROM jsonb_array_elements(body->'targets') t WHERE "
  "t->>'key'=x->>'target_key'),false)) THEN\n"
  "        RAISE EXCEPTION 'Observation retains actual target records and original received time'; "
  'END IF;\n'
  '    END IF;\n'
  '  END IF;\n'
  "  IF kind_value IN ('observation','review') THEN\n"
  '    SELECT to_jsonb(f) INTO dependency FROM capa_verification_rule_facts f WHERE '
  'f.tenant_id=tid\n'
  "      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "      AND f.id=(n->>'rule_fact_id')::uuid AND f.revision=(n->>'rule_revision')::integer;\n"
  '    IF dependency IS NULL OR '
  "ROW(dependency->>'anchor_sha256',dependency->>'requirement_sha256',\n"
  "      dependency->>'purpose',dependency->>'nature') IS DISTINCT FROM ROW(n->>'anchor_sha256',\n"
  "      n->>'requirement_sha256',n->>'purpose',n->>'nature') THEN\n"
  "      RAISE EXCEPTION 'CAPA observation/review requires exact scoped published Rule'; END IF;\n"
  '  END IF;\n'
  "  IF kind_value='review' THEN\n"
  "    IF NOT COALESCE(isfinite((body->'at'->>'occurred_at')::timestamptz)\n"
  "      AND (body->'at'->>'occurred_at')::timestamptz<=(n->>'created_at')::timestamptz\n"
  "      AND (n->>'valid_until' IS NULL OR\n"
  "        isfinite((n->>'valid_until')::timestamptz)),false)\n"
  '      OR NOT EXISTS (SELECT 1 FROM capa_verification_evidence f WHERE f.tenant_id=tid\n'
  "      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "      AND f.id=(n->>'candidate_id')::uuid AND f.revision=(n->>'candidate_revision')::integer\n"
  "      AND f.input_snapshot->'stable_anchor'=anchor AND f.purpose=n->>'purpose' AND "
  "f.nature=n->>'nature')\n"
  "      OR NOT COALESCE(jsonb_typeof(body->'observations')='array'\n"
  "        AND jsonb_array_length(body->'observations')>0\n"
  "        AND jsonb_array_length(body->'observations')=(SELECT count(DISTINCT x->>'id')\n"
  "          FROM jsonb_array_elements(body->'observations') x),false) THEN\n"
  "      RAISE EXCEPTION 'Named review requires exact scoped candidate and unique ordered "
  "observation refs'; END IF;\n"
  "    FOR child IN SELECT value FROM jsonb_array_elements(body->'observations') LOOP\n"
  '      IF NOT EXISTS (SELECT 1 FROM capa_observation_facts f WHERE f.tenant_id=tid\n'
  "        AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "        AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "        AND f.id=(child->>'id')::uuid AND f.revision=(child->>'revision')::integer\n"
  "        AND f.rule_fact_id=(n->>'rule_fact_id')::uuid AND "
  "f.rule_revision=(n->>'rule_revision')::integer\n"
  "        AND f.rule_sha256=n->>'rule_sha256' AND f.anchor_sha256=n->>'anchor_sha256'\n"
  "        AND f.requirement_sha256=n->>'requirement_sha256' AND f.purpose=n->>'purpose' AND "
  "f.nature=n->>'nature'\n"
  '        AND '
  "(f.fact_body->'body'->'at'->>'occurred_at')::timestamptz<=(body->'at'->>'occurred_at')::timestamptz) "
  'THEN\n'
  "        RAISE EXCEPTION 'Named review requires every exact original observation in the saved "
  "scope'; END IF;\n"
  '    END LOOP;\n'
  '  END IF;\n'
  '  -- Canonical body/full SHA, original bytes, full child FactRef SHA, actual\n'
  '  -- semantic material and seven current owner gates remain host responsibilities.\n'
  'END $function$\n',
  'CREATE OR REPLACE FUNCTION public.assert_capa_publication_atom(table_name text, tid uuid, sid '
  'uuid)\n'
  ' RETURNS void\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE n jsonb; body jsonb; anchor jsonb; original_id uuid; original_rev integer;\n'
  '  op_name text; family text; tier_value text; kind_value text; c confirmations%ROWTYPE;\n'
  '  r action_receipts%ROWTYPE; previous jsonb; dependency jsonb; child jsonb; actual_time '
  'timestamptz;\n'
  'BEGIN\n'
  '  CASE table_name\n'
  "    WHEN 'capa_verification_rule_facts' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_verification_rule_facts f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.verification.rule.import'; family := 'capa_verification_rule';\n"
  "      tier_value := 'host_import'; kind_value := 'rule';\n"
  "    WHEN 'capa_observation_facts' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_observation_facts f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.observation.record'; family := 'capa_observation';\n"
  "      tier_value := 'T1'; kind_value := 'observation';\n"
  "    WHEN 'capa_named_verification_reviews' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_named_verification_reviews f WHERE f.tenant_id=tid '
  'AND f.id=sid;\n'
  "      op_name := 'quality.capa.verification.review'; family := "
  "'capa_named_verification_review';\n"
  "      tier_value := 'T2'; kind_value := 'review';\n"
  "    WHEN 'capa_verification_evidence' THEN\n"
  '      SELECT to_jsonb(f) INTO n FROM capa_verification_evidence f WHERE f.tenant_id=tid AND '
  'f.id=sid;\n'
  "      op_name := 'quality.capa.verification.candidate.record'; family := "
  "'capa_verification_candidate';\n"
  "      tier_value := 'T1'; kind_value := 'candidate';\n"
  "    ELSE RAISE EXCEPTION 'Unsupported CAPA publication target';\n"
  '  END CASE;\n'
  "  IF n IS NULL OR NOT COALESCE(isfinite((n->>'created_at')::timestamptz),false)\n"
  '    OR NOT EXISTS (SELECT 1 FROM principals WHERE tenant_id=tid\n'
  "    AND id=(n->>'writer_id')::uuid AND kind='human' AND active)\n"
  '    OR NOT EXISTS (SELECT 1 FROM grants WHERE tenant_id=tid\n'
  "      AND category_id=public.category_for_product((n->>'product_id')::uuid) AND "
  "principal_id=(n->>'writer_id')::uuid\n"
  "      AND can_write AND (expires_at IS NULL OR expires_at>(n->>'created_at')::timestamptz)) "
  'THEN\n'
  "    RAISE EXCEPTION 'CAPA publication requires exact target and named actual human'; END IF;\n"
  "  IF kind_value='candidate' THEN\n"
  "    anchor := n->'input_snapshot'->'stable_anchor';\n"
  "    original_id := (n->>'issue_version_id')::uuid; original_rev := "
  "(n->>'issue_revision')::integer;\n"
  "    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot')='object'\n"
  "      AND (n->'input_snapshot') ?& "
  "ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor']\n"
  '      AND '
  "((n->'input_snapshot')-ARRAY['semantic','shared_proof','proof_consumed_at','stable_anchor'])='{}'::jsonb\n"
  "      AND jsonb_typeof(n->'input_snapshot'->'semantic')='object'\n"
  "      AND n->>'owner_id'=anchor->'origin'->>'owner_id'\n"
  "      AND n->>'visibility'=anchor->'origin'->>'visibility'\n"
  "      AND ((n->'input_snapshot'->'shared_proof')-ARRAY['id','tier'])='{}'::jsonb\n"
  "      AND NOT ((n->'input_snapshot'->'semantic') ? 'confirmation_token')\n"
  "      AND NOT ((n->'input_snapshot'->'semantic') ? 'approval_token')\n"
  "      AND n->'candidate_binding'->'basis'=n->'basis_snapshot'\n"
  "      AND n->'candidate_snapshot'->'binding'=n->'candidate_binding'\n"
  "      AND n->'candidate_snapshot'->>'inspection_sha256'=n->>'inspection_sha256'\n"
  "      AND n->'basis_snapshot'->>'basis_sha256'=n->>'basis_sha256'\n"
  '      AND '
  "n->'candidate_snapshot'->'required_source_read_set'=n->'required_source_read_set',false) THEN\n"
  "      RAISE EXCEPTION 'Candidate requires exact frozen unknown binding/inspection and no-token "
  "semantic'; END IF;\n"
  '    PERFORM '
  "assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',\n"
  "      n->'source_basis'->'artifact_sources',n->>'visibility',(n->>'owner_id')::uuid);\n"
  "    c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,\n"
  "      op_name,n->'input_snapshot'->'shared_proof',(n->>'created_at')::timestamptz);\n"
  "    IF NOT COALESCE(jsonb_typeof(n->'input_snapshot'->'proof_consumed_at')='string'\n"
  "      AND n->'input_snapshot'->>'proof_consumed_at' ~ "
  "'^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+-][0-9]{2}:[0-9]{2})$'\n"
  "      AND c.created_at<=(n->'input_snapshot'->>'proof_consumed_at')::timestamptz\n"
  '      AND '
  "(n->'input_snapshot'->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) "
  'THEN\n'
  "      RAISE EXCEPTION 'Candidate retains actual consumed and saved clocks'; END IF;\n"
  '  ELSE\n'
  "    body := n->'fact_body'->'body'; anchor := n->'anchor_snapshot';\n"
  "    original_id := (n->>'origin_issue_version_id')::uuid;\n"
  "    original_rev := (n->>'origin_issue_revision')::integer;\n"
  "    IF n->>'operation' IS DISTINCT FROM op_name OR n->>'tier' IS DISTINCT FROM tier_value\n"
  "      OR n->>'fact_kind' IS DISTINCT FROM kind_value\n"
  "      OR ROW(n->>'actor_id',n->>'requester_id') IS DISTINCT FROM "
  "ROW(n->>'writer_id',n->>'writer_id') THEN\n"
  "      RAISE EXCEPTION 'CAPA fact actual operation, tier and writer must match'; END IF;\n"
  '    PERFORM '
  "assert_capa_fact_source_closure(tid,(n->>'product_id')::uuid,n->'sources',n->'required_source_read_set',\n"
  "      n->'source_basis',n->>'visibility',(n->>'owner_id')::uuid);\n"
  "    IF tier_value<>'host_import' THEN\n"
  "      c := assert_quality_followup_proof(tid,(n->>'product_id')::uuid,(n->>'writer_id')::uuid,\n"
  '        '
  "op_name,jsonb_build_object('id',n->'shared_proof_id','tier',tier_value),(n->>'created_at')::timestamptz);\n"
  "      IF NOT COALESCE((n->>'shared_proof_revision')::integer=c.revision\n"
  "        AND (n->>'proof_expires_at')::timestamptz IS NOT DISTINCT FROM c.expires_at AND "
  "n->>'token_sha256'=c.token_hash\n"
  "        AND n->>'material_sha256'=c.payload_digest AND "
  "c.created_at<=(n->>'proof_consumed_at')::timestamptz\n"
  "        AND (n->>'proof_consumed_at')::timestamptz<=(n->>'created_at')::timestamptz,false) "
  'THEN\n'
  "        RAISE EXCEPTION 'CAPA fact requires exact actual shared proof fields and consumption "
  "clock'; END IF;\n"
  '    END IF;\n'
  '  END IF;\n'
  "  PERFORM assert_capa_fact_origin(tid,(n->>'product_id')::uuid,(n->>'project_id')::uuid,\n"
  '    '
  "(n->>'issue_id')::uuid,(n->>'capa_id')::uuid,original_id,original_rev,n->>'purpose',n->>'nature',\n"
  "    anchor,n->'required_source_read_set',n->>'visibility',(n->>'writer_id')::uuid);\n"
  "  IF kind_value IN ('rule','observation') AND n->>'previous_fact_id' IS NOT NULL THEN\n"
  "    IF kind_value='rule' THEN\n"
  '      SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f\n'
  "        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  '    ELSE\n'
  '      SELECT to_jsonb(f) INTO previous FROM capa_observation_facts f\n'
  "        WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  '    END IF;\n'
  "    IF previous IS NULL OR previous->>'purpose' IS DISTINCT FROM n->>'purpose' THEN\n"
  "      RAISE EXCEPTION 'CAPA successor retains exact complete original purpose'; END IF;\n"
  '  END IF;\n'
  '  r := '
  "assert_quality_followup_receipt(tid,(n->>'product_id')::uuid,sid,(n->>'revision')::integer,\n"
  "    op_name,family,(n->>'writer_id')::uuid,n->>'visibility',n->>'status');\n"
  "  IF jsonb_typeof(r.result->'revision') IS DISTINCT FROM 'number'\n"
  "    OR NOT COALESCE(r.result->>'revision' ~ '^[1-9][0-9]*$',false)\n"
  "    OR r.result->'revision' IS DISTINCT FROM n->'revision'\n"
  "    OR r.created_at<(n->>'created_at')::timestamptz THEN\n"
  "    RAISE EXCEPTION 'CAPA receipt retains exact numeric revision and actual save ordering'; END "
  'IF;\n'
  "  IF r.intent_digest IS DISTINCT FROM n->>'intent_digest' THEN\n"
  "    RAISE EXCEPTION 'CAPA publication uses actual common intent, not domain intent'; END IF;\n"
  "  IF tier_value<>'host_import' AND (c.snapshot->>'operation' IS DISTINCT FROM op_name\n"
  "    OR c.snapshot->'required_source_read_set' IS DISTINCT FROM n->'required_source_read_set') "
  'THEN\n'
  "    RAISE EXCEPTION 'CAPA proof review retains operation and exact complete read set'; END IF;\n"
  "  IF kind_value='candidate' THEN\n"
  '    IF '
  "(r.result-ARRAY['id','revision','status','candidate_binding_sha256','inspection_sha256'])<>'{}'::jsonb\n"
  "      OR r.result->>'candidate_binding_sha256' IS DISTINCT FROM n->>'binding_sha256'\n"
  "      OR r.result->>'inspection_sha256' IS DISTINCT FROM n->>'inspection_sha256' THEN\n"
  "      RAISE EXCEPTION 'Candidate receipt binds actual non-cyclic binding and inspection "
  "hashes'; END IF;\n"
  '  ELSE\n'
  "    IF (r.result-ARRAY['id','revision','status','fact_kind','payload_sha256'])<>'{}'::jsonb\n"
  "      OR r.command_id IS DISTINCT FROM (n->>'command_id')::uuid\n"
  "      OR r.result->>'fact_kind' IS DISTINCT FROM kind_value\n"
  "      OR r.result->>'payload_sha256' IS DISTINCT FROM n->>'payload_sha256' THEN\n"
  "      RAISE EXCEPTION 'CAPA fact receipt binds actual command and body payload hash'; END IF;\n"
  '  END IF;\n'
  "  IF kind_value IN ('rule','observation') THEN\n"
  "    IF kind_value='rule' THEN\n"
  "      IF NOT COALESCE(isfinite((n->>'valid_from')::timestamptz)\n"
  "        AND isfinite((n->>'valid_until')::timestamptz),false) THEN\n"
  "        RAISE EXCEPTION 'Rule publication retains finite fixed validity clocks'; END IF;\n"
  '      IF NOT EXISTS (SELECT 1 FROM capa_current_verification_rules p WHERE p.tenant_id=tid\n'
  "        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid\n"
  "        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid\n"
  "        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid\n"
  "        AND p.fact_revision=(n->>'revision')::integer) THEN\n"
  "        RAISE EXCEPTION 'Rule publication and its exact Current must commit together'; END IF;\n"
  "      IF n->>'previous_fact_id' IS NOT NULL THEN\n"
  '        SELECT to_jsonb(f) INTO previous FROM capa_verification_rule_facts f\n'
  "          WHERE f.tenant_id=tid AND f.id=(n->>'previous_fact_id')::uuid;\n"
  "        IF previous->>'issuer_key' IS DISTINCT FROM n->>'issuer_key'\n"
  "          OR previous->>'external_id' IS DISTINCT FROM n->>'external_id'\n"
  "          OR (n->>'issuer_epoch')::integer<(previous->>'issuer_epoch')::integer THEN\n"
  "          RAISE EXCEPTION 'Rule successor preserves external series and cannot rewind issuer "
  "epoch'; END IF;\n"
  '      END IF;\n'
  '    ELSE\n'
  '      IF NOT EXISTS (SELECT 1 FROM capa_current_observations p WHERE p.tenant_id=tid\n'
  "        AND p.product_id=(n->>'product_id')::uuid AND p.project_id=(n->>'project_id')::uuid\n"
  "        AND p.issue_id=(n->>'issue_id')::uuid AND p.capa_id=(n->>'capa_id')::uuid\n"
  "        AND p.series_id=(n->>'series_id')::uuid AND p.fact_id=sid\n"
  "        AND p.fact_revision=(n->>'revision')::integer) THEN\n"
  "        RAISE EXCEPTION 'Observation and its exact Current must commit together'; END IF;\n"
  "      actual_time := (body->'at'->>'occurred_at')::timestamptz;\n"
  "      IF NOT COALESCE((n->>'observed_from')::timestamptz<(n->>'observed_until')::timestamptz\n"
  "        AND (n->>'observed_until')::timestamptz<=actual_time\n"
  "        AND actual_time<=(n->>'created_at')::timestamptz\n"
  "        AND jsonb_typeof(body->'records')='array' AND jsonb_array_length(body->'records')>0\n"
  "        AND jsonb_typeof(body->'targets')='array' AND "
  "jsonb_array_length(body->'targets')>0,false)\n"
  "        OR EXISTS (SELECT 1 FROM jsonb_array_elements(body->'records') x WHERE NOT COALESCE(\n"
  "          (x->>'occurred_at')::timestamptz BETWEEN (n->>'observed_from')::timestamptz\n"
  "            AND (n->>'observed_until')::timestamptz\n"
  "          AND EXISTS (SELECT 1 FROM jsonb_array_elements(body->'targets') t WHERE "
  "t->>'key'=x->>'target_key'),false)) THEN\n"
  "        RAISE EXCEPTION 'Observation retains actual target records and original received time'; "
  'END IF;\n'
  '    END IF;\n'
  '  END IF;\n'
  "  IF kind_value IN ('observation','review') THEN\n"
  '    SELECT to_jsonb(f) INTO dependency FROM capa_verification_rule_facts f WHERE '
  'f.tenant_id=tid\n'
  "      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "      AND f.id=(n->>'rule_fact_id')::uuid AND f.revision=(n->>'rule_revision')::integer;\n"
  '    IF dependency IS NULL OR '
  "ROW(dependency->>'anchor_sha256',dependency->>'requirement_sha256',\n"
  "      dependency->>'purpose',dependency->>'nature') IS DISTINCT FROM ROW(n->>'anchor_sha256',\n"
  "      n->>'requirement_sha256',n->>'purpose',n->>'nature') THEN\n"
  "      RAISE EXCEPTION 'CAPA observation/review requires exact scoped published Rule'; END IF;\n"
  '  END IF;\n'
  "  IF kind_value='review' THEN\n"
  "    IF NOT COALESCE(isfinite((body->'at'->>'occurred_at')::timestamptz)\n"
  "      AND (body->'at'->>'occurred_at')::timestamptz<=(n->>'created_at')::timestamptz\n"
  "      AND (n->>'valid_until' IS NULL OR\n"
  "        isfinite((n->>'valid_until')::timestamptz)),false)\n"
  '      OR NOT EXISTS (SELECT 1 FROM capa_verification_evidence f WHERE f.tenant_id=tid\n'
  "      AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "      AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "      AND f.id=(n->>'candidate_id')::uuid AND f.revision=(n->>'candidate_revision')::integer\n"
  "      AND f.input_snapshot->'stable_anchor'=anchor AND f.purpose=n->>'purpose' AND "
  "f.nature=n->>'nature')\n"
  "      OR NOT COALESCE(jsonb_typeof(body->'observations')='array'\n"
  "        AND jsonb_array_length(body->'observations')>0\n"
  "        AND jsonb_array_length(body->'observations')=(SELECT count(DISTINCT x->>'id')\n"
  "          FROM jsonb_array_elements(body->'observations') x),false) THEN\n"
  "      RAISE EXCEPTION 'Named review requires exact scoped candidate and unique ordered "
  "observation refs'; END IF;\n"
  "    FOR child IN SELECT value FROM jsonb_array_elements(body->'observations') LOOP\n"
  '      IF NOT EXISTS (SELECT 1 FROM capa_observation_facts f WHERE f.tenant_id=tid\n'
  "        AND f.product_id=(n->>'product_id')::uuid AND f.project_id=(n->>'project_id')::uuid\n"
  "        AND f.issue_id=(n->>'issue_id')::uuid AND f.capa_id=(n->>'capa_id')::uuid\n"
  "        AND f.id=(child->>'id')::uuid AND f.revision=(child->>'revision')::integer\n"
  "        AND f.rule_fact_id=(n->>'rule_fact_id')::uuid AND "
  "f.rule_revision=(n->>'rule_revision')::integer\n"
  "        AND f.rule_sha256=n->>'rule_sha256' AND f.anchor_sha256=n->>'anchor_sha256'\n"
  "        AND f.requirement_sha256=n->>'requirement_sha256' AND f.purpose=n->>'purpose' AND "
  "f.nature=n->>'nature'\n"
  '        AND '
  "(f.fact_body->'body'->'at'->>'occurred_at')::timestamptz<=(body->'at'->>'occurred_at')::timestamptz) "
  'THEN\n'
  "        RAISE EXCEPTION 'Named review requires every exact original observation in the saved "
  "scope'; END IF;\n"
  '    END LOOP;\n'
  '  END IF;\n'
  '  -- Canonical body/full SHA, original bytes, full child FactRef SHA, actual\n'
  '  -- semantic material and seven current owner gates remain host responsibilities.\n'
  'END $function$\n'),
 ('assert_controlled_change_atom',
  'c5fece46c5c8565bec92dba4f2e20b5d88f0f1f717d9b046948519bc72430c0a',
  '5d4d9e4c580def177bf1a1deb3d5cd2b9e1a36a23b61a44758d3b28f9a8df0cb',
  'CREATE OR REPLACE FUNCTION public.assert_controlled_change_atom(tab text, tid uuid, target '
  'uuid)\n'
  ' RETURNS void\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE a jsonb; r action_receipts%ROWTYPE; p confirmations%ROWTYPE;\n'
  '  family text; effect text; parent change_request_versions%ROWTYPE;\n'
  '  issue quality_issue_versions%ROWTYPE; policy controlled_change_policy_facts%ROWTYPE;\n'
  'BEGIN\n'
  "  IF tab NOT IN ('controlled_change_policy_facts','controlled_change_selection_facts') THEN\n"
  "    RAISE EXCEPTION 'unknown controlled atom'; END IF;\n"
  "  EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE tenant_id=$1 AND id=$2',tab)\n"
  '    INTO STRICT a USING tid,target;\n'
  "  IF tab='controlled_change_policy_facts' THEN\n"
  "    family:='change_policy_fact'; effect:='change.policy_imported';\n"
  "    IF NOT COALESCE(jsonb_typeof(a->'material')='object' AND (a->'material') ?&\n"
  '      '
  "ARRAY['schema_version','scope','purpose','owner_id','visibility','publisher_id','required_disciplines','valid_from','valid_until','nature']\n"
  "      AND ((a->'material') - "
  "ARRAY['schema_version','scope','purpose','owner_id','visibility','publisher_id','required_disciplines','valid_from','valid_until','nature'])='{}'::jsonb\n"
  "      AND jsonb_typeof(a->'material'->'required_disciplines')='array'\n"
  "      AND jsonb_array_length(a->'material'->'required_disciplines')>=2,false)\n"
  "      THEN RAISE EXCEPTION 'exact policy JSON shape required'; END IF;\n"
  "    IF a->>'operation'<>'change.policy.import' OR a->>'status'<>'published'\n"
  "      OR a->'material'->>'schema_version'<>'pdos-controlled-change-policy-v1'\n"
  "      OR (a->'material'->>'publisher_id')::uuid IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR (a->'material'->>'owner_id')::uuid IS DISTINCT FROM (a->>'owner_id')::uuid\n"
  "      OR a->'material'->>'visibility' IS DISTINCT FROM a->>'visibility'\n"
  "      OR (a->'material'->>'valid_from')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_from')::timestamptz\n"
  "      OR (a->'material'->>'valid_until')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_until')::timestamptz\n"
  "      OR NOT (a->'material'->'required_disciplines' @> "
  '\'["engineering","manufacturing"]\'::jsonb)\n'
  '      OR NOT EXISTS(SELECT 1 FROM controlled_change_policy_currents c WHERE c.tenant_id=tid\n'
  "        AND c.product_id=(a->>'product_id')::uuid AND c.project_id=(a->>'project_id')::uuid\n"
  "        AND c.purpose_sha256=a->>'purpose_sha256' AND c.fact_id=target\n"
  "        AND c.revision=(a->>'revision')::integer AND c.epoch=(a->>'epoch')::integer)\n"
  "      THEN RAISE EXCEPTION 'controlled policy material/current mismatch'; END IF;\n"
  '  ELSE\n'
  "    family:='change_selection_fact'; effect:='change.selection_decided';\n"
  "    IF NOT COALESCE(jsonb_typeof(a->'material')='object' AND (a->'material') ?&\n"
  '      '
  "ARRAY['schema_version','scope','purpose','change_id','item','issue_id','capa_id','action_id','action_sha256','executor_id','decider_id','status','valid_until','reason','nature']\n"
  "      AND ((a->'material') - "
  "ARRAY['schema_version','scope','purpose','change_id','item','issue_id','capa_id','action_id','action_sha256','executor_id','decider_id','status','valid_until','reason','nature'])='{}'::jsonb,false)\n"
  "      THEN RAISE EXCEPTION 'exact selection JSON shape required'; END IF;\n"
  '    SELECT * INTO STRICT parent FROM change_request_versions WHERE tenant_id=tid\n'
  "      AND product_id=(a->>'product_id')::uuid AND project_id=(a->>'project_id')::uuid\n"
  "      AND change_id=(a->>'change_id')::uuid AND id=(a->>'change_version_id')::uuid\n"
  "      AND revision=(a->>'change_revision')::integer;\n"
  '    SELECT * INTO STRICT issue FROM quality_issue_versions WHERE tenant_id=tid\n'
  '      AND product_id=parent.product_id AND project_id=parent.project_id\n'
  "      AND issue_id=(a->>'issue_id')::uuid AND id=(a->>'issue_version_id')::uuid\n"
  "      AND revision=(a->>'issue_revision')::integer;\n"
  '    SELECT * INTO STRICT policy FROM controlled_change_policy_facts WHERE tenant_id=tid\n'
  '      AND product_id=parent.product_id AND project_id=parent.project_id\n'
  "      AND id=(a->>'policy_id')::uuid AND revision=(a->>'policy_revision')::integer;\n"
  "    IF a->>'operation'<>'change.selection.decide'\n"
  "      OR a->'material'->>'schema_version'<>'pdos-controlled-change-selection-v1'\n"
  "      OR (a->'material'->>'change_id')::uuid IS DISTINCT FROM parent.change_id\n"
  "      OR (a->'material'->'item'->>'id')::uuid IS DISTINCT FROM (a->>'item_id')::uuid\n"
  "      OR (a->'material'->'item'->'intent'->>'id')::uuid IS DISTINCT FROM "
  "(a->>'intent_id')::uuid\n"
  "      OR (a->'material'->>'issue_id')::uuid IS DISTINCT FROM issue.issue_id\n"
  "      OR (a->'material'->>'capa_id')::uuid IS DISTINCT FROM (a->>'capa_id')::uuid\n"
  "      OR (issue.issue_snapshot->'capa'->>'id')::uuid IS DISTINCT FROM (a->>'capa_id')::uuid\n"
  "      OR (a->'material'->>'action_id')::uuid IS DISTINCT FROM (a->>'action_id')::uuid\n"
  "      OR a->'material'->>'action_sha256' IS DISTINCT FROM a->>'action_sha256'\n"
  "      OR (a->'material'->>'decider_id')::uuid IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR a->'material'->>'status' IS DISTINCT FROM a->>'status'\n"
  "      OR (a->'material'->>'valid_until')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_until')::timestamptz\n"
  "      OR parent.owner_id IS DISTINCT FROM (a->>'owner_id')::uuid\n"
  "      OR parent.visibility IS DISTINCT FROM a->>'visibility'\n"
  '      OR issue.owner_id IS DISTINCT FROM parent.owner_id OR issue.visibility IS DISTINCT FROM '
  'parent.visibility\n'
  "      OR a->'policy_snapshot'->'owner_proof'->'receipt'->>'subject_id' IS DISTINCT FROM "
  'policy.id::text\n'
  "      OR a->'policy_snapshot'->'scope' IS DISTINCT FROM policy.material->'scope'\n"
  "      OR a->'policy_snapshot'->>'purpose' IS DISTINCT FROM policy.purpose\n"
  "      OR a->'policy_snapshot'->>'owner_id' IS DISTINCT FROM policy.owner_id::text\n"
  "      OR a->'policy_snapshot'->>'visibility' IS DISTINCT FROM policy.visibility\n"
  "      OR a->'policy_snapshot'->>'nature' IS DISTINCT FROM policy.nature\n"
  "      OR a->'policy_snapshot'->'source' IS DISTINCT FROM policy.source\n"
  "      OR (a->'policy_snapshot'->>'epoch')::integer IS DISTINCT FROM policy.epoch\n"
  "      OR a->'policy_snapshot'->'required_disciplines' IS DISTINCT FROM "
  "policy.material->'required_disciplines'\n"
  '      OR NOT '
  "COALESCE((a->'policy_snapshot'->>'valid_until')::timestamptz<=policy.valid_until,false)\n"
  "      OR a->'input_snapshot'->'review'->'after'->'material' IS DISTINCT FROM a->'material'\n"
  "      OR a->'input_snapshot'->'review'->'selection'->'units' IS DISTINCT FROM "
  "a->'units_snapshot'\n"
  "      OR a->'input_snapshot'->'review'->'selection'->'objects' IS DISTINCT FROM "
  "a->'object_basis'\n"
  "      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(issue.issue_snapshot->'capa'->'actions') "
  'v\n'
  "        WHERE (v->>'id')::uuid=(a->>'action_id')::uuid\n"
  "          AND v->>'executor_id'=a->'material'->>'executor_id')\n"
  '      OR NOT EXISTS(SELECT 1 FROM controlled_change_selection_currents c WHERE c.tenant_id=tid\n'
  '        AND c.product_id=parent.product_id AND c.project_id=parent.project_id\n'
  "        AND c.change_id=parent.change_id AND c.item_id=(a->>'item_id')::uuid\n"
  "        AND c.fact_id=target AND c.revision=(a->>'revision')::integer\n"
  "        AND c.epoch=(a->>'epoch')::integer)\n"
  "      THEN RAISE EXCEPTION 'controlled selection material/current mismatch'; END IF;\n"
  '    SELECT * INTO STRICT p FROM confirmations WHERE tenant_id=tid\n'
  "      AND product_id=parent.product_id AND id=(a->>'shared_proof_id')::uuid;\n"
  "    IF p.consumed IS DISTINCT FROM true OR p.actor_id IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR p.operation IS DISTINCT FROM a->>'operation' OR p.subject_id IS DISTINCT FROM "
  'parent.product_id\n'
  "      OR p.revision IS DISTINCT FROM (a->>'shared_proof_revision')::integer\n"
  "      OR p.token_hash IS DISTINCT FROM a->>'token_sha256'\n"
  "      OR p.payload_digest IS DISTINCT FROM a->>'confirmation_material_sha256'\n"
  "      OR p.snapshot IS DISTINCT FROM a->'input_snapshot'->'review'\n"
  "      OR p.created_at>(a->>'proof_consumed_at')::timestamptz\n"
  "      OR (a->>'proof_consumed_at')::timestamptz>(a->>'created_at')::timestamptz\n"
  "      OR (a->>'created_at')::timestamptz>=p.expires_at\n"
  "      OR p.expires_at IS DISTINCT FROM (a->>'proof_expires_at')::timestamptz\n"
  "      THEN RAISE EXCEPTION 'controlled selection proof mismatch'; END IF;\n"
  "    IF (a->'input_snapshot'->'review') - "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier'] "
  "<> '{}'::jsonb\n"
  "      OR (SELECT count(*) FROM jsonb_object_keys(a->'input_snapshot'->'review'))<>13\n"
  "      OR a->'input_snapshot'->'review'->>'operation' IS DISTINCT FROM a->>'operation'\n"
  "      OR a->'input_snapshot'->'review'->>'proof_tier' IS DISTINCT FROM 'T2'\n"
  "      OR (a->'input_snapshot'->'shared_proof') IS DISTINCT FROM "
  "jsonb_build_object('id',p.id,'tier','T2')\n"
  "      OR a->'input_snapshot'->'review'->'before'->>'change_id' IS DISTINCT FROM "
  'parent.change_id::text\n'
  "      OR (a->'input_snapshot'->'review'->'before'->>'change_revision')::integer IS DISTINCT "
  'FROM parent.revision\n'
  "      OR (a->'input_snapshot'->'review'->'after'->>'selection_revision')::integer IS DISTINCT "
  "FROM (a->>'revision')::integer\n"
  "      OR a->'input_snapshot'->'review'->'after'->>'issue_version_id' IS DISTINCT FROM "
  'issue.id::text\n'
  "      OR a->'input_snapshot'->'review'->'payload_semantic' IS DISTINCT FROM "
  "a->'input_snapshot'->'semantic'\n"
  "      OR a->'input_snapshot'->'review'->'read_set' IS DISTINCT FROM "
  "a->'required_source_read_set'\n"
  "      OR a->'input_snapshot'->'review'->'sources' IS DISTINCT FROM a->'sources'\n"
  "      OR a->'input_snapshot'->'review'->'source_basis' IS DISTINCT FROM a->'source_basis'\n"
  "      OR a->'input_snapshot'->'review'->'authority' IS DISTINCT FROM a->'authority_snapshot'\n"
  "      OR a->'input_snapshot'->'review'->'policy' IS DISTINCT FROM a->'policy_snapshot'\n"
  "      THEN RAISE EXCEPTION 'controlled selection exact review mismatch'; END IF;\n"
  '  END IF;\n'
  "  IF a->'material'->'scope' IS DISTINCT FROM jsonb_build_object(\n"
  '       '
  "'tenant_id',tid,'product_id',(a->>'product_id')::uuid,'project_id',(a->>'project_id')::uuid)\n"
  "    OR a->'material'->>'purpose' IS DISTINCT FROM a->>'purpose'\n"
  "    OR jsonb_typeof(a->'sources')<>'array' OR jsonb_array_length(a->'sources')<1\n"
  "    OR jsonb_typeof(a->'required_source_read_set')<>'array'\n"
  "    OR jsonb_array_length(a->'required_source_read_set')<1\n"
  "    OR NOT (a->'sources' @> jsonb_build_array(a->'source'))\n"
  "    THEN RAISE EXCEPTION 'controlled source scope mismatch'; END IF;\n"
  '  SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=tid\n'
  "    AND product_id=(a->>'product_id')::uuid AND operation=a->>'operation'\n"
  '    AND subject_type=family AND subject_id=target AND '
  "subject_revision=(a->>'revision')::integer;\n"
  "  IF r.actor_id IS DISTINCT FROM (a->>'actor_id')::uuid OR r.requester_id IS DISTINCT FROM "
  'r.actor_id\n'
  "    OR r.run_id IS NOT NULL OR r.command_id IS DISTINCT FROM (a->>'command_id')::uuid\n"
  "    OR r.intent_digest IS DISTINCT FROM a->>'intent_digest'\n"
  "    OR r.visibility IS DISTINCT FROM a->>'visibility'\n"
  "    OR r.result->>'id' IS DISTINCT FROM target::text\n"
  "    OR (r.result->>'revision')::integer IS DISTINCT FROM (a->>'revision')::integer\n"
  "    OR r.result->>'status' IS DISTINCT FROM a->>'status'\n"
  "    OR (tab='controlled_change_selection_facts' AND\n"
  "      (r.result->>'item_id' IS DISTINCT FROM a->>'item_id'\n"
  "       OR r.result->>'action_id' IS DISTINCT FROM a->>'action_id'\n"
  "       OR r.result->>'material_sha256' IS DISTINCT FROM a->>'material_sha256'))\n"
  '    OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE k.tenant_id=tid AND k.actor_id=r.actor_id\n'
  '      AND k.receipt_id=r.id AND k.digest=r.request_digest)\n'
  '    OR (SELECT count(*) FROM audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id\n'
  '      AND x.actor_id=r.actor_id AND x.operation=r.operation)<>1\n'
  '    OR (SELECT count(*) FROM outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id\n'
  '      AND x.actor_id=r.actor_id AND x.type=effect AND x.subject_id=r.subject_id\n'
  '      AND x.subject_revision=r.subject_revision AND x.correlation_id=r.command_id)<>1\n'
  "    THEN RAISE EXCEPTION 'controlled publication common group mismatch'; END IF;\n"
  'END $function$\n',
  'CREATE OR REPLACE FUNCTION public.assert_controlled_change_atom(tab text, tid uuid, target '
  'uuid)\n'
  ' RETURNS void\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE a jsonb; r action_receipts%ROWTYPE; p confirmations%ROWTYPE;\n'
  '  family text; effect text; parent change_request_versions%ROWTYPE;\n'
  '  issue quality_issue_versions%ROWTYPE; policy controlled_change_policy_facts%ROWTYPE;\n'
  'BEGIN\n'
  "  IF tab NOT IN ('controlled_change_policy_facts','controlled_change_selection_facts') THEN\n"
  "    RAISE EXCEPTION 'unknown controlled atom'; END IF;\n"
  "  EXECUTE format('SELECT to_jsonb(t) FROM public.%I t WHERE tenant_id=$1 AND id=$2',tab)\n"
  '    INTO STRICT a USING tid,target;\n'
  "  IF tab='controlled_change_policy_facts' THEN\n"
  "    family:='change_policy_fact'; effect:='change.policy_imported';\n"
  "    IF NOT COALESCE(jsonb_typeof(a->'material')='object' AND (a->'material') ?&\n"
  '      '
  "ARRAY['schema_version','scope','purpose','owner_id','visibility','publisher_id','required_disciplines','valid_from','valid_until','nature']\n"
  "      AND ((a->'material') - "
  "ARRAY['schema_version','scope','purpose','owner_id','visibility','publisher_id','required_disciplines','valid_from','valid_until','nature'])='{}'::jsonb\n"
  "      AND jsonb_typeof(a->'material'->'required_disciplines')='array'\n"
  "      AND jsonb_array_length(a->'material'->'required_disciplines')>=2,false)\n"
  "      THEN RAISE EXCEPTION 'exact policy JSON shape required'; END IF;\n"
  "    IF a->>'operation'<>'change.policy.import' OR a->>'status'<>'published'\n"
  "      OR a->'material'->>'schema_version'<>'pdos-controlled-change-policy-v1'\n"
  "      OR (a->'material'->>'publisher_id')::uuid IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR (a->'material'->>'owner_id')::uuid IS DISTINCT FROM (a->>'owner_id')::uuid\n"
  "      OR a->'material'->>'visibility' IS DISTINCT FROM a->>'visibility'\n"
  "      OR (a->'material'->>'valid_from')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_from')::timestamptz\n"
  "      OR (a->'material'->>'valid_until')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_until')::timestamptz\n"
  "      OR NOT (a->'material'->'required_disciplines' @> "
  '\'["engineering","manufacturing"]\'::jsonb)\n'
  '      OR NOT EXISTS(SELECT 1 FROM controlled_change_policy_currents c WHERE c.tenant_id=tid\n'
  "        AND c.product_id=(a->>'product_id')::uuid AND c.project_id=(a->>'project_id')::uuid\n"
  "        AND c.purpose_sha256=a->>'purpose_sha256' AND c.fact_id=target\n"
  "        AND c.revision=(a->>'revision')::integer AND c.epoch=(a->>'epoch')::integer)\n"
  "      THEN RAISE EXCEPTION 'controlled policy material/current mismatch'; END IF;\n"
  '  ELSE\n'
  "    family:='change_selection_fact'; effect:='change.selection_decided';\n"
  "    IF NOT COALESCE(jsonb_typeof(a->'material')='object' AND (a->'material') ?&\n"
  '      '
  "ARRAY['schema_version','scope','purpose','change_id','item','issue_id','capa_id','action_id','action_sha256','executor_id','decider_id','status','valid_until','reason','nature']\n"
  "      AND ((a->'material') - "
  "ARRAY['schema_version','scope','purpose','change_id','item','issue_id','capa_id','action_id','action_sha256','executor_id','decider_id','status','valid_until','reason','nature'])='{}'::jsonb,false)\n"
  "      THEN RAISE EXCEPTION 'exact selection JSON shape required'; END IF;\n"
  '    SELECT * INTO STRICT parent FROM change_request_versions WHERE tenant_id=tid\n'
  "      AND product_id=(a->>'product_id')::uuid AND project_id=(a->>'project_id')::uuid\n"
  "      AND change_id=(a->>'change_id')::uuid AND id=(a->>'change_version_id')::uuid\n"
  "      AND revision=(a->>'change_revision')::integer;\n"
  '    SELECT * INTO STRICT issue FROM quality_issue_versions WHERE tenant_id=tid\n'
  '      AND product_id=parent.product_id AND project_id=parent.project_id\n'
  "      AND issue_id=(a->>'issue_id')::uuid AND id=(a->>'issue_version_id')::uuid\n"
  "      AND revision=(a->>'issue_revision')::integer;\n"
  '    SELECT * INTO STRICT policy FROM controlled_change_policy_facts WHERE tenant_id=tid\n'
  '      AND product_id=parent.product_id AND project_id=parent.project_id\n'
  "      AND id=(a->>'policy_id')::uuid AND revision=(a->>'policy_revision')::integer;\n"
  "    IF a->>'operation'<>'change.selection.decide'\n"
  "      OR a->'material'->>'schema_version'<>'pdos-controlled-change-selection-v1'\n"
  "      OR (a->'material'->>'change_id')::uuid IS DISTINCT FROM parent.change_id\n"
  "      OR (a->'material'->'item'->>'id')::uuid IS DISTINCT FROM (a->>'item_id')::uuid\n"
  "      OR (a->'material'->'item'->'intent'->>'id')::uuid IS DISTINCT FROM "
  "(a->>'intent_id')::uuid\n"
  "      OR (a->'material'->>'issue_id')::uuid IS DISTINCT FROM issue.issue_id\n"
  "      OR (a->'material'->>'capa_id')::uuid IS DISTINCT FROM (a->>'capa_id')::uuid\n"
  "      OR (issue.issue_snapshot->'capa'->>'id')::uuid IS DISTINCT FROM (a->>'capa_id')::uuid\n"
  "      OR (a->'material'->>'action_id')::uuid IS DISTINCT FROM (a->>'action_id')::uuid\n"
  "      OR a->'material'->>'action_sha256' IS DISTINCT FROM a->>'action_sha256'\n"
  "      OR (a->'material'->>'decider_id')::uuid IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR a->'material'->>'status' IS DISTINCT FROM a->>'status'\n"
  "      OR (a->'material'->>'valid_until')::timestamptz IS DISTINCT FROM "
  "(a->>'valid_until')::timestamptz\n"
  "      OR parent.owner_id IS DISTINCT FROM (a->>'owner_id')::uuid\n"
  "      OR parent.visibility IS DISTINCT FROM a->>'visibility'\n"
  '      OR issue.owner_id IS DISTINCT FROM parent.owner_id OR issue.visibility IS DISTINCT FROM '
  'parent.visibility\n'
  "      OR a->'policy_snapshot'->'owner_proof'->'receipt'->>'subject_id' IS DISTINCT FROM "
  'policy.id::text\n'
  "      OR a->'policy_snapshot'->'scope' IS DISTINCT FROM policy.material->'scope'\n"
  "      OR a->'policy_snapshot'->>'purpose' IS DISTINCT FROM policy.purpose\n"
  "      OR a->'policy_snapshot'->>'owner_id' IS DISTINCT FROM policy.owner_id::text\n"
  "      OR a->'policy_snapshot'->>'visibility' IS DISTINCT FROM policy.visibility\n"
  "      OR a->'policy_snapshot'->>'nature' IS DISTINCT FROM policy.nature\n"
  "      OR a->'policy_snapshot'->'source' IS DISTINCT FROM policy.source\n"
  "      OR (a->'policy_snapshot'->>'epoch')::integer IS DISTINCT FROM policy.epoch\n"
  "      OR a->'policy_snapshot'->'required_disciplines' IS DISTINCT FROM "
  "policy.material->'required_disciplines'\n"
  '      OR NOT '
  "COALESCE((a->'policy_snapshot'->>'valid_until')::timestamptz<=policy.valid_until,false)\n"
  "      OR a->'input_snapshot'->'review'->'after'->'material' IS DISTINCT FROM a->'material'\n"
  "      OR a->'input_snapshot'->'review'->'selection'->'units' IS DISTINCT FROM "
  "a->'units_snapshot'\n"
  "      OR a->'input_snapshot'->'review'->'selection'->'objects' IS DISTINCT FROM "
  "a->'object_basis'\n"
  "      OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(issue.issue_snapshot->'capa'->'actions') "
  'v\n'
  "        WHERE (v->>'id')::uuid=(a->>'action_id')::uuid\n"
  "          AND v->>'executor_id'=a->'material'->>'executor_id')\n"
  '      OR NOT EXISTS(SELECT 1 FROM controlled_change_selection_currents c WHERE c.tenant_id=tid\n'
  '        AND c.product_id=parent.product_id AND c.project_id=parent.project_id\n'
  "        AND c.change_id=parent.change_id AND c.item_id=(a->>'item_id')::uuid\n"
  "        AND c.fact_id=target AND c.revision=(a->>'revision')::integer\n"
  "        AND c.epoch=(a->>'epoch')::integer)\n"
  "      THEN RAISE EXCEPTION 'controlled selection material/current mismatch'; END IF;\n"
  '    SELECT * INTO STRICT p FROM confirmations WHERE tenant_id=tid\n'
  "      AND product_id=parent.product_id AND id=(a->>'shared_proof_id')::uuid;\n"
  "    IF p.consumed IS DISTINCT FROM true OR p.actor_id IS DISTINCT FROM (a->>'actor_id')::uuid\n"
  "      OR p.operation IS DISTINCT FROM a->>'operation' OR p.subject_id IS DISTINCT FROM "
  'parent.product_id\n'
  "      OR p.revision IS DISTINCT FROM (a->>'shared_proof_revision')::integer\n"
  "      OR p.token_hash IS DISTINCT FROM a->>'token_sha256'\n"
  "      OR p.payload_digest IS DISTINCT FROM a->>'confirmation_material_sha256'\n"
  "      OR p.snapshot IS DISTINCT FROM a->'input_snapshot'->'review'\n"
  "      OR p.created_at>(a->>'proof_consumed_at')::timestamptz\n"
  "      OR (a->>'proof_consumed_at')::timestamptz>(a->>'created_at')::timestamptz\n"
  "      OR (p.expires_at IS NOT NULL AND (a->>'created_at')::timestamptz>=p.expires_at)\n"
  "      OR p.expires_at IS DISTINCT FROM (a->>'proof_expires_at')::timestamptz\n"
  "      THEN RAISE EXCEPTION 'controlled selection proof mismatch'; END IF;\n"
  "    IF (a->'input_snapshot'->'review') - "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier'] "
  "<> '{}'::jsonb\n"
  "      OR (SELECT count(*) FROM jsonb_object_keys(a->'input_snapshot'->'review'))<>13\n"
  "      OR a->'input_snapshot'->'review'->>'operation' IS DISTINCT FROM a->>'operation'\n"
  "      OR a->'input_snapshot'->'review'->>'proof_tier' IS DISTINCT FROM 'T2'\n"
  "      OR (a->'input_snapshot'->'shared_proof') IS DISTINCT FROM "
  "jsonb_build_object('id',p.id,'tier','T2')\n"
  "      OR a->'input_snapshot'->'review'->'before'->>'change_id' IS DISTINCT FROM "
  'parent.change_id::text\n'
  "      OR (a->'input_snapshot'->'review'->'before'->>'change_revision')::integer IS DISTINCT "
  'FROM parent.revision\n'
  "      OR (a->'input_snapshot'->'review'->'after'->>'selection_revision')::integer IS DISTINCT "
  "FROM (a->>'revision')::integer\n"
  "      OR a->'input_snapshot'->'review'->'after'->>'issue_version_id' IS DISTINCT FROM "
  'issue.id::text\n'
  "      OR a->'input_snapshot'->'review'->'payload_semantic' IS DISTINCT FROM "
  "a->'input_snapshot'->'semantic'\n"
  "      OR a->'input_snapshot'->'review'->'read_set' IS DISTINCT FROM "
  "a->'required_source_read_set'\n"
  "      OR a->'input_snapshot'->'review'->'sources' IS DISTINCT FROM a->'sources'\n"
  "      OR a->'input_snapshot'->'review'->'source_basis' IS DISTINCT FROM a->'source_basis'\n"
  "      OR a->'input_snapshot'->'review'->'authority' IS DISTINCT FROM a->'authority_snapshot'\n"
  "      OR a->'input_snapshot'->'review'->'policy' IS DISTINCT FROM a->'policy_snapshot'\n"
  "      THEN RAISE EXCEPTION 'controlled selection exact review mismatch'; END IF;\n"
  '  END IF;\n'
  "  IF a->'material'->'scope' IS DISTINCT FROM jsonb_build_object(\n"
  '       '
  "'tenant_id',tid,'product_id',(a->>'product_id')::uuid,'project_id',(a->>'project_id')::uuid)\n"
  "    OR a->'material'->>'purpose' IS DISTINCT FROM a->>'purpose'\n"
  "    OR jsonb_typeof(a->'sources')<>'array' OR jsonb_array_length(a->'sources')<1\n"
  "    OR jsonb_typeof(a->'required_source_read_set')<>'array'\n"
  "    OR jsonb_array_length(a->'required_source_read_set')<1\n"
  "    OR NOT (a->'sources' @> jsonb_build_array(a->'source'))\n"
  "    THEN RAISE EXCEPTION 'controlled source scope mismatch'; END IF;\n"
  '  SELECT * INTO STRICT r FROM action_receipts WHERE tenant_id=tid\n'
  "    AND product_id=(a->>'product_id')::uuid AND operation=a->>'operation'\n"
  '    AND subject_type=family AND subject_id=target AND '
  "subject_revision=(a->>'revision')::integer;\n"
  "  IF r.actor_id IS DISTINCT FROM (a->>'actor_id')::uuid OR r.requester_id IS DISTINCT FROM "
  'r.actor_id\n'
  "    OR r.run_id IS NOT NULL OR r.command_id IS DISTINCT FROM (a->>'command_id')::uuid\n"
  "    OR r.intent_digest IS DISTINCT FROM a->>'intent_digest'\n"
  "    OR r.visibility IS DISTINCT FROM a->>'visibility'\n"
  "    OR r.result->>'id' IS DISTINCT FROM target::text\n"
  "    OR (r.result->>'revision')::integer IS DISTINCT FROM (a->>'revision')::integer\n"
  "    OR r.result->>'status' IS DISTINCT FROM a->>'status'\n"
  "    OR (tab='controlled_change_selection_facts' AND\n"
  "      (r.result->>'item_id' IS DISTINCT FROM a->>'item_id'\n"
  "       OR r.result->>'action_id' IS DISTINCT FROM a->>'action_id'\n"
  "       OR r.result->>'material_sha256' IS DISTINCT FROM a->>'material_sha256'))\n"
  '    OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE k.tenant_id=tid AND k.actor_id=r.actor_id\n'
  '      AND k.receipt_id=r.id AND k.digest=r.request_digest)\n'
  '    OR (SELECT count(*) FROM audit_entries x WHERE x.tenant_id=tid AND x.receipt_id=r.id\n'
  '      AND x.actor_id=r.actor_id AND x.operation=r.operation)<>1\n'
  '    OR (SELECT count(*) FROM outbox_events x WHERE x.tenant_id=tid AND x.receipt_id=r.id\n'
  '      AND x.actor_id=r.actor_id AND x.type=effect AND x.subject_id=r.subject_id\n'
  '      AND x.subject_revision=r.subject_revision AND x.correlation_id=r.command_id)<>1\n'
  "    THEN RAISE EXCEPTION 'controlled publication common group mismatch'; END IF;\n"
  'END $function$\n'),
 ('assert_quality_followup_proof',
  '71119a84adde336ab7596be7022a3d2adc1d84d796df934c64659de0172ea4a2',
  'a5ae5a76370a7b1402dc7c87ea24cb9cbee96f9bde54a4575139e450393f0cf0',
  'CREATE OR REPLACE FUNCTION public.assert_quality_followup_proof(tid uuid, pid uuid, actor uuid, '
  'op_name text, proof jsonb, saved_at timestamp with time zone)\n'
  ' RETURNS confirmations\n'
  ' LANGUAGE plpgsql\n'
  'AS $function$\n'
  'DECLARE c confirmations%ROWTYPE; expected_tier text; uses integer;\n'
  'BEGIN\n'
  "  expected_tier := CASE op_name WHEN 'quality.issue.root_cause.decide' THEN 'T2'\n"
  "    WHEN 'quality.capa.actions.complete' THEN 'T1' WHEN 'quality.capa.followup.link' THEN 'T1'\n"
  "    WHEN 'quality.capa.observation.record' THEN 'T1'\n"
  "    WHEN 'quality.capa.verification.review' THEN 'T2'\n"
  "    WHEN 'quality.capa.verification.candidate.record' THEN 'T1' END;\n"
  "  IF expected_tier IS NULL OR NOT COALESCE(proof->>'tier'=expected_tier AND\n"
  "    proof->>'id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',false) "
  'THEN\n'
  "    RAISE EXCEPTION 'Followup requires its exact shared proof tier and identity'; END IF;\n"
  "  SELECT * INTO c FROM confirmations WHERE tenant_id=tid AND id=(proof->>'id')::uuid;\n"
  '  IF c.id IS NULL OR ROW(c.product_id,c.subject_id,c.actor_id,c.operation)\n'
  '    IS DISTINCT FROM ROW(pid,pid,actor,op_name) OR c.consumed IS DISTINCT FROM true\n'
  '    OR c.revision IS DISTINCT FROM (SELECT revision FROM products WHERE tenant_id=tid AND '
  'id=pid)\n'
  '    OR c.expires_at<=saved_at OR c.created_at>saved_at\n'
  "    OR NOT COALESCE(c.payload_digest ~ '^[0-9a-f]{64}$' AND c.token_hash ~ '^[0-9a-f]{64}$'\n"
  "      AND jsonb_typeof(c.snapshot)='object',false)\n"
  "    OR NOT EXISTS (SELECT 1 FROM principals WHERE tenant_id=tid AND id=actor AND kind='human' "
  'AND active) THEN\n'
  "    RAISE EXCEPTION 'Followup requires a consumed current Product proof by the named human'; "
  'END IF;\n'
  '  SELECT count(*) INTO uses FROM (\n'
  '    SELECT id FROM quality_issue_versions WHERE tenant_id=tid AND operation IN\n'
  "      ('quality.issue.root_cause.decide','quality.capa.actions.complete')\n"
  "      AND source_basis->'shared_proof'->>'id'=c.id::text\n"
  '    UNION ALL SELECT id FROM capa_remediation_links WHERE tenant_id=tid\n'
  "      AND input_snapshot->'shared_proof'->>'id'=c.id::text\n"
  '    UNION ALL SELECT id FROM capa_observation_facts WHERE tenant_id=tid AND '
  'shared_proof_id=c.id\n'
  '    UNION ALL SELECT id FROM capa_named_verification_reviews WHERE tenant_id=tid AND '
  'shared_proof_id=c.id\n'
  '    UNION ALL SELECT id FROM capa_verification_evidence WHERE tenant_id=tid\n'
  "      AND input_snapshot->'shared_proof'->>'id'=c.id::text\n"
  '  ) u;\n'
  "  IF uses<>1 THEN RAISE EXCEPTION 'One consumed proof must bind exactly one new followup "
  "target'; END IF;\n"
  '  -- The reciprocal deferred transition guard and immutable consumed rows pair\n'
  '  -- this target with a real False->True transition in the same UOW. No xmin/top\n'
  '  -- xid assumption is used, so a legitimate SAVEPOINT remains supported.\n'
  '  -- Python canonical material/token digests and runtime freshness still require\n'
  "  -- quality_followup_host's actual marker; JSONB text hashing is not equivalent.\n"
  '  RETURN c;\n'
  'END $function$\n',
  'CREATE OR REPLACE FUNCTION public.assert_quality_followup_proof(tid uuid, pid uuid, actor uuid, '
  'op_name text, proof jsonb, saved_at timestamp with time zone)\n'
  ' RETURNS confirmations\n'
  ' LANGUAGE plpgsql\n'
  'AS $function$\n'
  'DECLARE c confirmations%ROWTYPE; expected_tier text; uses integer;\n'
  'BEGIN\n'
  "  expected_tier := CASE op_name WHEN 'quality.issue.root_cause.decide' THEN 'T2'\n"
  "    WHEN 'quality.capa.actions.complete' THEN 'T1' WHEN 'quality.capa.followup.link' THEN 'T1'\n"
  "    WHEN 'quality.capa.observation.record' THEN 'T1'\n"
  "    WHEN 'quality.capa.verification.review' THEN 'T2'\n"
  "    WHEN 'quality.capa.verification.candidate.record' THEN 'T1' END;\n"
  "  IF expected_tier IS NULL OR NOT COALESCE(proof->>'tier'=expected_tier AND\n"
  "    proof->>'id' ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',false) "
  'THEN\n'
  "    RAISE EXCEPTION 'Followup requires its exact shared proof tier and identity'; END IF;\n"
  "  SELECT * INTO c FROM confirmations WHERE tenant_id=tid AND id=(proof->>'id')::uuid;\n"
  '  IF c.id IS NULL OR ROW(c.product_id,c.subject_id,c.actor_id,c.operation)\n'
  '    IS DISTINCT FROM ROW(pid,pid,actor,op_name) OR c.consumed IS DISTINCT FROM true\n'
  '    OR c.revision IS DISTINCT FROM (SELECT revision FROM products WHERE tenant_id=tid AND '
  'id=pid)\n'
  "    OR (expected_tier='T1' AND c.expires_at IS NULL)\n"
  '    OR (c.expires_at IS NOT NULL AND c.expires_at<=saved_at) OR c.created_at>saved_at\n'
  "    OR NOT COALESCE(c.payload_digest ~ '^[0-9a-f]{64}$' AND c.token_hash ~ '^[0-9a-f]{64}$'\n"
  "      AND jsonb_typeof(c.snapshot)='object',false)\n"
  "    OR NOT EXISTS (SELECT 1 FROM principals WHERE tenant_id=tid AND id=actor AND kind='human' "
  'AND active) THEN\n'
  "    RAISE EXCEPTION 'Followup requires a consumed current Product proof by the named human'; "
  'END IF;\n'
  '  SELECT count(*) INTO uses FROM (\n'
  '    SELECT id FROM quality_issue_versions WHERE tenant_id=tid AND operation IN\n'
  "      ('quality.issue.root_cause.decide','quality.capa.actions.complete')\n"
  "      AND source_basis->'shared_proof'->>'id'=c.id::text\n"
  '    UNION ALL SELECT id FROM capa_remediation_links WHERE tenant_id=tid\n'
  "      AND input_snapshot->'shared_proof'->>'id'=c.id::text\n"
  '    UNION ALL SELECT id FROM capa_observation_facts WHERE tenant_id=tid AND '
  'shared_proof_id=c.id\n'
  '    UNION ALL SELECT id FROM capa_named_verification_reviews WHERE tenant_id=tid AND '
  'shared_proof_id=c.id\n'
  '    UNION ALL SELECT id FROM capa_verification_evidence WHERE tenant_id=tid\n'
  "      AND input_snapshot->'shared_proof'->>'id'=c.id::text\n"
  '  ) u;\n'
  "  IF uses<>1 THEN RAISE EXCEPTION 'One consumed proof must bind exactly one new followup "
  "target'; END IF;\n"
  '  -- The reciprocal deferred transition guard and immutable consumed rows pair\n'
  '  -- this target with a real False->True transition in the same UOW. No xmin/top\n'
  '  -- xid assumption is used, so a legitimate SAVEPOINT remains supported.\n'
  '  -- Python canonical material/token digests and runtime freshness still require\n'
  "  -- quality_followup_host's actual marker; JSONB text hashing is not equivalent.\n"
  '  RETURN c;\n'
  'END $function$\n'),
 ('require_change_order_atom',
  '8c3969d8e238ad9cf98e2be0938b5ff08f3c0b0e2a22a4d913921afe816bc9e4',
  '33eeade234fc9ba76397a57ac724ffc1da074b4c2fee81905803b0a84f890364',
  'CREATE OR REPLACE FUNCTION public.require_change_order_atom()\n'
  ' RETURNS trigger\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE\n'
  '  atom jsonb := to_jsonb(NEW);\n'
  '  parent change_request_versions%ROWTYPE;\n'
  '  previous change_request_versions%ROWTYPE;\n'
  '  proof confirmations%ROWTYPE;\n'
  '  receipt action_receipts%ROWTYPE;\n'
  '  effect text;\n'
  '  order_body jsonb;\n'
  '  proposed jsonb;\n'
  '  expected_tier text;\n'
  'BEGIN\n'
  '  SELECT * INTO STRICT parent FROM change_request_versions\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id\n'
  '      AND project_id=NEW.project_id AND change_id=NEW.change_id\n'
  '      AND id=NEW.change_version_id AND revision=NEW.change_revision;\n'
  '  SELECT * INTO STRICT previous FROM change_request_versions\n'
  '    WHERE tenant_id=parent.tenant_id AND product_id=parent.product_id\n'
  '      AND project_id=parent.project_id AND change_id=parent.change_id\n'
  '      AND id=parent.previous_version_id AND revision=parent.previous_revision;\n'
  '  IF parent.operation IS DISTINCT FROM NEW.operation\n'
  '    OR parent.owner_id IS DISTINCT FROM previous.owner_id\n'
  '    OR parent.visibility IS DISTINCT FROM previous.visibility\n'
  '    OR parent.owner_id IS DISTINCT FROM NEW.owner_id\n'
  '    OR parent.visibility IS DISTINCT FROM NEW.visibility\n'
  '    OR parent.sources IS DISTINCT FROM NEW.sources\n'
  '    OR parent.required_source_read_set IS DISTINCT FROM NEW.required_source_read_set\n'
  '    OR parent.source_basis IS DISTINCT FROM NEW.source_basis\n'
  '    OR parent.authority_snapshot IS DISTINCT FROM NEW.authority_snapshot\n'
  "    OR (parent.request_snapshot->>'id')::uuid IS DISTINCT FROM parent.change_id\n"
  "    OR (parent.request_snapshot->'scope'->>'tenant_id')::uuid IS DISTINCT FROM "
  'parent.tenant_id\n'
  "    OR (parent.request_snapshot->'scope'->>'product_id')::uuid IS DISTINCT FROM "
  'parent.product_id\n'
  "    OR (parent.request_snapshot->'scope'->>'project_id')::uuid IS DISTINCT FROM "
  'parent.project_id\n'
  "    OR (parent.request_snapshot - ARRAY['revision','status','history','orders']) IS DISTINCT "
  "FROM (previous.request_snapshot - ARRAY['revision','status','history','orders'])\n"
  "    OR jsonb_array_length(parent.request_snapshot->'history') <> "
  "jsonb_array_length(previous.request_snapshot->'history')+1\n"
  "    OR ((parent.request_snapshot->'history') - "
  "(jsonb_array_length(parent.request_snapshot->'history')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'history')\n"
  "    OR (parent.request_snapshot->'history'->-1->>'command_id')::uuid IS DISTINCT FROM "
  'NEW.command_id\n'
  "    OR (parent.request_snapshot->'history'->-1->>'actor_id')::uuid IS DISTINCT FROM "
  'NEW.actor_id\n'
  "    OR (parent.request_snapshot->'history'->-1->>'operation') IS DISTINCT FROM NEW.operation\n"
  "    THEN RAISE EXCEPTION 'change atom parent mismatch' USING ERRCODE='23514'; END IF;\n"
  "  expected_tier := CASE NEW.operation WHEN 'change.order.approve' THEN 'T2' ELSE 'T1' END;\n"
  "  IF NOT COALESCE(jsonb_typeof(NEW.input_snapshot)='object'\n"
  "    AND NEW.input_snapshot ?& ARRAY['semantic','shared_proof','review']\n"
  "    AND (NEW.input_snapshot - ARRAY['semantic','shared_proof','review'])='{}'::jsonb\n"
  "    AND jsonb_typeof(NEW.input_snapshot->'review')='object'\n"
  "    AND (NEW.input_snapshot->'review') ?& "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier']\n"
  "    AND ((NEW.input_snapshot->'review') - "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier'])='{}'::jsonb\n"
  '    AND '
  "(NEW.input_snapshot->'shared_proof')=jsonb_build_object('id',NEW.shared_proof_id,'tier',expected_tier)\n"
  "    AND jsonb_typeof(parent.request_snapshot->'history')='array'\n"
  "    AND jsonb_typeof(parent.request_snapshot->'orders')='array',false)\n"
  "    THEN RAISE EXCEPTION 'exact change review shape required' USING ERRCODE='23514'; END IF;\n"
  '  proposed := '
  'jsonb_set(parent.request_snapshot,\'{history,-1,at}\',\'"server_on_save"\'::jsonb);\n'
  "  IF NEW.operation='change.order.approve' THEN\n"
  '    proposed := '
  'jsonb_set(proposed,\'{orders,-1,approvals,-1,at}\',\'"server_on_save"\'::jsonb);\n'
  '    proposed := '
  'jsonb_set(proposed,\'{orders,-1,approvals,-1,decision_id}\',\'"actual_consumed_named_proof_on_save"\'::jsonb);\n'
  '  END IF;\n'
  "  IF NEW.input_snapshot->'review'->>'operation' IS DISTINCT FROM NEW.operation\n"
  "    OR NEW.input_snapshot->'review'->>'proof_tier' IS DISTINCT FROM expected_tier\n"
  "    OR NEW.input_snapshot->'review'->'payload_semantic' IS DISTINCT FROM "
  "NEW.input_snapshot->'semantic'\n"
  "    OR NEW.input_snapshot->'review'->'before' IS DISTINCT FROM previous.request_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'after' IS DISTINCT FROM proposed\n"
  "    OR NEW.input_snapshot->'review'->'read_set' IS DISTINCT FROM NEW.required_source_read_set\n"
  "    OR NEW.input_snapshot->'review'->'sources' IS DISTINCT FROM NEW.sources\n"
  "    OR NEW.input_snapshot->'review'->'authority' IS DISTINCT FROM NEW.authority_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'policy' IS DISTINCT FROM NEW.policy_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'source_basis' IS DISTINCT FROM NEW.source_basis\n"
  "    OR NOT COALESCE(jsonb_typeof(NEW.sources)='array' AND jsonb_array_length(NEW.sources)>0\n"
  "      AND jsonb_typeof(NEW.required_source_read_set)='array'\n"
  '      AND jsonb_array_length(NEW.required_source_read_set)>0,false)\n'
  "    THEN RAISE EXCEPTION 'change review correspondence mismatch' USING ERRCODE='23514'; END "
  'IF;\n'
  '  SELECT * INTO STRICT proof FROM confirmations\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND id=NEW.shared_proof_id;\n'
  '  IF NOT proof.consumed OR proof.actor_id IS DISTINCT FROM NEW.actor_id\n'
  '    OR proof.subject_id IS DISTINCT FROM NEW.product_id\n'
  '    OR proof.operation IS DISTINCT FROM NEW.operation\n'
  '    OR proof.revision IS DISTINCT FROM NEW.shared_proof_revision\n'
  '    OR proof.token_hash IS DISTINCT FROM NEW.token_sha256\n'
  '    OR proof.payload_digest IS DISTINCT FROM NEW.material_sha256\n'
  "    OR proof.snapshot IS DISTINCT FROM (NEW.input_snapshot->'review')\n"
  '    OR proof.created_at > NEW.proof_consumed_at\n'
  '    OR NEW.proof_consumed_at > NEW.created_at OR NEW.created_at >= proof.expires_at\n'
  '    OR proof.expires_at IS DISTINCT FROM NEW.proof_expires_at\n'
  "    THEN RAISE EXCEPTION 'change proof group mismatch' USING ERRCODE='23514'; END IF;\n"
  '  SELECT * INTO STRICT receipt FROM action_receipts\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id\n'
  "      AND operation=NEW.operation AND subject_type='change_request'\n"
  '      AND subject_id=parent.id AND subject_revision=parent.revision;\n'
  "  effect := CASE NEW.operation WHEN 'change.order.prepare' THEN 'change.order_prepared'\n"
  "    WHEN 'change.order.approve' THEN 'change.approved' ELSE 'change.implementation_recorded' "
  'END;\n'
  '  IF receipt.actor_id IS DISTINCT FROM NEW.actor_id\n'
  '    OR receipt.requester_id IS DISTINCT FROM NEW.actor_id OR receipt.run_id IS NOT NULL\n'
  '    OR receipt.visibility IS DISTINCT FROM parent.visibility\n'
  '    OR receipt.command_id IS DISTINCT FROM NEW.command_id\n'
  '    OR receipt.intent_digest IS DISTINCT FROM NEW.intent_digest\n'
  "    OR (receipt.result->>'id')::uuid IS DISTINCT FROM parent.id\n"
  "    OR (receipt.result->>'revision')::integer IS DISTINCT FROM parent.revision\n"
  "    OR receipt.result->>'status' IS DISTINCT FROM parent.status\n"
  '    OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE k.tenant_id=receipt.tenant_id\n'
  '      AND k.actor_id=receipt.actor_id AND k.receipt_id=receipt.id AND '
  'k.digest=receipt.request_digest)\n'
  '    OR (SELECT count(*) FROM audit_entries a WHERE a.tenant_id=receipt.tenant_id AND '
  'a.receipt_id=receipt.id\n'
  '      AND a.actor_id=receipt.actor_id AND a.operation=receipt.operation)<>1\n'
  '    OR (SELECT count(*) FROM outbox_events o WHERE o.tenant_id=receipt.tenant_id AND '
  'o.receipt_id=receipt.id\n'
  '      AND o.type=effect AND o.actor_id=receipt.actor_id AND '
  'o.correlation_id=receipt.command_id\n'
  '      AND o.subject_id=parent.id AND o.subject_revision=parent.revision)<>1\n'
  "    THEN RAISE EXCEPTION 'change common group mismatch' USING ERRCODE='23514'; END IF;\n"
  "  order_body := parent.request_snapshot->'orders'->-1;\n"
  "  IF NEW.operation<>'change.order.prepare' AND (\n"
  "    jsonb_array_length(parent.request_snapshot->'orders') IS DISTINCT FROM "
  "jsonb_array_length(previous.request_snapshot->'orders')\n"
  "    OR ((parent.request_snapshot->'orders') - "
  "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS DISTINCT FROM\n"
  "       ((previous.request_snapshot->'orders') - "
  "(jsonb_array_length(previous.request_snapshot->'orders')-1)))\n"
  "    THEN RAISE EXCEPTION 'earlier Orders must remain exact'; END IF;\n"
  "  IF NEW.operation='change.order.prepare' THEN\n"
  "    IF ((parent.request_snapshot->'orders') - "
  "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'orders')\n"
  "      OR parent.status <> 'review' OR previous.status NOT IN ('analysis','review')\n"
  "      OR jsonb_array_length(order_body->'approvals')<>0\n"
  "      OR jsonb_array_length(order_body->'implementations')<>0\n"
  "      OR order_body IS DISTINCT FROM (atom->'order_snapshot')\n"
  "      OR (order_body->>'id')::uuid IS DISTINCT FROM (atom->>'order_id')::uuid\n"
  "      OR order_body->>'content_digest' IS DISTINCT FROM atom->>'content_sha256'\n"
  "      THEN RAISE EXCEPTION 'order material mismatch' USING ERRCODE='23514'; END IF;\n"
  "  ELSIF NEW.operation='change.order.approve' THEN\n"
  "    IF ((order_body->'approvals') - (jsonb_array_length(order_body->'approvals')-1)) IS "
  "DISTINCT FROM (previous.request_snapshot->'orders'->-1->'approvals')\n"
  "      OR (order_body - 'approvals') IS DISTINCT FROM ((previous.request_snapshot->'orders'->-1) "
  "- 'approvals')\n"
  "      OR previous.status <> 'review' OR parent.status NOT IN ('review','approved')\n"
  "      OR (previous.request_snapshot->>'requester_id')::uuid = NEW.actor_id\n"
  "      OR (order_body->'approvals'->-1) IS DISTINCT FROM (atom->'approval_snapshot')\n"
  "      OR (atom->'approval_snapshot'->>'decision_id')::uuid IS DISTINCT FROM "
  'NEW.shared_proof_id\n'
  "      OR (atom->'approval_snapshot'->>'discipline') IS DISTINCT FROM (atom->>'discipline')\n"
  "      OR (atom->'approval_snapshot'->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
  "      OR (atom->'approval_snapshot'->>'content_digest') IS DISTINCT FROM "
  "order_body->>'content_digest'\n"
  "      OR NOT COALESCE(order_body->'required_disciplines' @> "
  "jsonb_build_array(atom->>'discipline'),false)\n"
  "      OR (atom->'approval_snapshot'->>'at')::timestamptz IS DISTINCT FROM "
  "(parent.request_snapshot->'history'->-1->>'at')::timestamptz\n"
  "      OR (order_body->'implementations') IS DISTINCT FROM "
  "(previous.request_snapshot->'orders'->-1->'implementations')\n"
  "      THEN RAISE EXCEPTION 'approval material mismatch' USING ERRCODE='23514'; END IF;\n"
  '  ELSE\n'
  "    IF ((order_body->'implementations') - "
  "(jsonb_array_length(order_body->'implementations')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'orders'->-1->'implementations')\n"
  "      OR (order_body - 'implementations') IS DISTINCT FROM "
  "((previous.request_snapshot->'orders'->-1) - 'implementations')\n"
  "      OR previous.status NOT IN ('approved','implementing') OR parent.status <> 'implementing'\n"
  "      OR (order_body->'implementations'->-1) IS DISTINCT FROM (atom->'fact_snapshot')\n"
  "      OR (atom->'fact_snapshot'->>'executor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
  '      OR NOT EXISTS(SELECT 1 FROM change_implementation_captures c WHERE '
  'c.tenant_id=NEW.tenant_id\n'
  '        AND c.product_id=NEW.product_id AND c.project_id=NEW.project_id AND '
  'c.change_id=NEW.change_id\n'
  "        AND c.id=(atom->>'capture_id')::uuid AND c.fact_id=(atom->>'fact_id')::uuid\n"
  "        AND c.fact_snapshot=(atom->'fact_snapshot') AND c.output_basis=(atom->'output_basis'))\n"
  "      OR NOT (order_body->'required_disciplines' @> "
  '\'["engineering","manufacturing"]\'::jsonb)\n'
  "      THEN RAISE EXCEPTION 'implementation material mismatch' USING ERRCODE='23514'; END IF;\n"
  '  END IF;\n'
  '  RETURN NULL;\n'
  'END $function$\n',
  'CREATE OR REPLACE FUNCTION public.require_change_order_atom()\n'
  ' RETURNS trigger\n'
  ' LANGUAGE plpgsql\n'
  " SET search_path TO 'pg_catalog', 'public'\n"
  'AS $function$\n'
  'DECLARE\n'
  '  atom jsonb := to_jsonb(NEW);\n'
  '  parent change_request_versions%ROWTYPE;\n'
  '  previous change_request_versions%ROWTYPE;\n'
  '  proof confirmations%ROWTYPE;\n'
  '  receipt action_receipts%ROWTYPE;\n'
  '  effect text;\n'
  '  order_body jsonb;\n'
  '  proposed jsonb;\n'
  '  expected_tier text;\n'
  'BEGIN\n'
  '  SELECT * INTO STRICT parent FROM change_request_versions\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id\n'
  '      AND project_id=NEW.project_id AND change_id=NEW.change_id\n'
  '      AND id=NEW.change_version_id AND revision=NEW.change_revision;\n'
  '  SELECT * INTO STRICT previous FROM change_request_versions\n'
  '    WHERE tenant_id=parent.tenant_id AND product_id=parent.product_id\n'
  '      AND project_id=parent.project_id AND change_id=parent.change_id\n'
  '      AND id=parent.previous_version_id AND revision=parent.previous_revision;\n'
  '  IF parent.operation IS DISTINCT FROM NEW.operation\n'
  '    OR parent.owner_id IS DISTINCT FROM previous.owner_id\n'
  '    OR parent.visibility IS DISTINCT FROM previous.visibility\n'
  '    OR parent.owner_id IS DISTINCT FROM NEW.owner_id\n'
  '    OR parent.visibility IS DISTINCT FROM NEW.visibility\n'
  '    OR parent.sources IS DISTINCT FROM NEW.sources\n'
  '    OR parent.required_source_read_set IS DISTINCT FROM NEW.required_source_read_set\n'
  '    OR parent.source_basis IS DISTINCT FROM NEW.source_basis\n'
  '    OR parent.authority_snapshot IS DISTINCT FROM NEW.authority_snapshot\n'
  "    OR (parent.request_snapshot->>'id')::uuid IS DISTINCT FROM parent.change_id\n"
  "    OR (parent.request_snapshot->'scope'->>'tenant_id')::uuid IS DISTINCT FROM "
  'parent.tenant_id\n'
  "    OR (parent.request_snapshot->'scope'->>'product_id')::uuid IS DISTINCT FROM "
  'parent.product_id\n'
  "    OR (parent.request_snapshot->'scope'->>'project_id')::uuid IS DISTINCT FROM "
  'parent.project_id\n'
  "    OR (parent.request_snapshot - ARRAY['revision','status','history','orders']) IS DISTINCT "
  "FROM (previous.request_snapshot - ARRAY['revision','status','history','orders'])\n"
  "    OR jsonb_array_length(parent.request_snapshot->'history') <> "
  "jsonb_array_length(previous.request_snapshot->'history')+1\n"
  "    OR ((parent.request_snapshot->'history') - "
  "(jsonb_array_length(parent.request_snapshot->'history')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'history')\n"
  "    OR (parent.request_snapshot->'history'->-1->>'command_id')::uuid IS DISTINCT FROM "
  'NEW.command_id\n'
  "    OR (parent.request_snapshot->'history'->-1->>'actor_id')::uuid IS DISTINCT FROM "
  'NEW.actor_id\n'
  "    OR (parent.request_snapshot->'history'->-1->>'operation') IS DISTINCT FROM NEW.operation\n"
  "    THEN RAISE EXCEPTION 'change atom parent mismatch' USING ERRCODE='23514'; END IF;\n"
  "  expected_tier := CASE NEW.operation WHEN 'change.order.approve' THEN 'T2' ELSE 'T1' END;\n"
  "  IF NOT COALESCE(jsonb_typeof(NEW.input_snapshot)='object'\n"
  "    AND NEW.input_snapshot ?& ARRAY['semantic','shared_proof','review']\n"
  "    AND (NEW.input_snapshot - ARRAY['semantic','shared_proof','review'])='{}'::jsonb\n"
  "    AND jsonb_typeof(NEW.input_snapshot->'review')='object'\n"
  "    AND (NEW.input_snapshot->'review') ?& "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier']\n"
  "    AND ((NEW.input_snapshot->'review') - "
  "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier'])='{}'::jsonb\n"
  '    AND '
  "(NEW.input_snapshot->'shared_proof')=jsonb_build_object('id',NEW.shared_proof_id,'tier',expected_tier)\n"
  "    AND jsonb_typeof(parent.request_snapshot->'history')='array'\n"
  "    AND jsonb_typeof(parent.request_snapshot->'orders')='array',false)\n"
  "    THEN RAISE EXCEPTION 'exact change review shape required' USING ERRCODE='23514'; END IF;\n"
  '  proposed := '
  'jsonb_set(parent.request_snapshot,\'{history,-1,at}\',\'"server_on_save"\'::jsonb);\n'
  "  IF NEW.operation='change.order.approve' THEN\n"
  '    proposed := '
  'jsonb_set(proposed,\'{orders,-1,approvals,-1,at}\',\'"server_on_save"\'::jsonb);\n'
  '    proposed := '
  'jsonb_set(proposed,\'{orders,-1,approvals,-1,decision_id}\',\'"actual_consumed_named_proof_on_save"\'::jsonb);\n'
  '  END IF;\n'
  "  IF NEW.input_snapshot->'review'->>'operation' IS DISTINCT FROM NEW.operation\n"
  "    OR NEW.input_snapshot->'review'->>'proof_tier' IS DISTINCT FROM expected_tier\n"
  "    OR NEW.input_snapshot->'review'->'payload_semantic' IS DISTINCT FROM "
  "NEW.input_snapshot->'semantic'\n"
  "    OR NEW.input_snapshot->'review'->'before' IS DISTINCT FROM previous.request_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'after' IS DISTINCT FROM proposed\n"
  "    OR NEW.input_snapshot->'review'->'read_set' IS DISTINCT FROM NEW.required_source_read_set\n"
  "    OR NEW.input_snapshot->'review'->'sources' IS DISTINCT FROM NEW.sources\n"
  "    OR NEW.input_snapshot->'review'->'authority' IS DISTINCT FROM NEW.authority_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'policy' IS DISTINCT FROM NEW.policy_snapshot\n"
  "    OR NEW.input_snapshot->'review'->'source_basis' IS DISTINCT FROM NEW.source_basis\n"
  "    OR NOT COALESCE(jsonb_typeof(NEW.sources)='array' AND jsonb_array_length(NEW.sources)>0\n"
  "      AND jsonb_typeof(NEW.required_source_read_set)='array'\n"
  '      AND jsonb_array_length(NEW.required_source_read_set)>0,false)\n'
  "    THEN RAISE EXCEPTION 'change review correspondence mismatch' USING ERRCODE='23514'; END "
  'IF;\n'
  '  SELECT * INTO STRICT proof FROM confirmations\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND id=NEW.shared_proof_id;\n'
  '  IF NOT proof.consumed OR proof.actor_id IS DISTINCT FROM NEW.actor_id\n'
  '    OR proof.subject_id IS DISTINCT FROM NEW.product_id\n'
  '    OR proof.operation IS DISTINCT FROM NEW.operation\n'
  '    OR proof.revision IS DISTINCT FROM NEW.shared_proof_revision\n'
  '    OR proof.token_hash IS DISTINCT FROM NEW.token_sha256\n'
  '    OR proof.payload_digest IS DISTINCT FROM NEW.material_sha256\n'
  "    OR proof.snapshot IS DISTINCT FROM (NEW.input_snapshot->'review')\n"
  '    OR proof.created_at > NEW.proof_consumed_at\n'
  '    OR NEW.proof_consumed_at > NEW.created_at\n'
  '    OR (proof.expires_at IS NOT NULL AND NEW.created_at >= proof.expires_at)\n'
  '    OR proof.expires_at IS DISTINCT FROM NEW.proof_expires_at\n'
  "    THEN RAISE EXCEPTION 'change proof group mismatch' USING ERRCODE='23514'; END IF;\n"
  '  SELECT * INTO STRICT receipt FROM action_receipts\n'
  '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id\n'
  "      AND operation=NEW.operation AND subject_type='change_request'\n"
  '      AND subject_id=parent.id AND subject_revision=parent.revision;\n'
  "  effect := CASE NEW.operation WHEN 'change.order.prepare' THEN 'change.order_prepared'\n"
  "    WHEN 'change.order.approve' THEN 'change.approved' ELSE 'change.implementation_recorded' "
  'END;\n'
  '  IF receipt.actor_id IS DISTINCT FROM NEW.actor_id\n'
  '    OR receipt.requester_id IS DISTINCT FROM NEW.actor_id OR receipt.run_id IS NOT NULL\n'
  '    OR receipt.visibility IS DISTINCT FROM parent.visibility\n'
  '    OR receipt.command_id IS DISTINCT FROM NEW.command_id\n'
  '    OR receipt.intent_digest IS DISTINCT FROM NEW.intent_digest\n'
  "    OR (receipt.result->>'id')::uuid IS DISTINCT FROM parent.id\n"
  "    OR (receipt.result->>'revision')::integer IS DISTINCT FROM parent.revision\n"
  "    OR receipt.result->>'status' IS DISTINCT FROM parent.status\n"
  '    OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE k.tenant_id=receipt.tenant_id\n'
  '      AND k.actor_id=receipt.actor_id AND k.receipt_id=receipt.id AND '
  'k.digest=receipt.request_digest)\n'
  '    OR (SELECT count(*) FROM audit_entries a WHERE a.tenant_id=receipt.tenant_id AND '
  'a.receipt_id=receipt.id\n'
  '      AND a.actor_id=receipt.actor_id AND a.operation=receipt.operation)<>1\n'
  '    OR (SELECT count(*) FROM outbox_events o WHERE o.tenant_id=receipt.tenant_id AND '
  'o.receipt_id=receipt.id\n'
  '      AND o.type=effect AND o.actor_id=receipt.actor_id AND '
  'o.correlation_id=receipt.command_id\n'
  '      AND o.subject_id=parent.id AND o.subject_revision=parent.revision)<>1\n'
  "    THEN RAISE EXCEPTION 'change common group mismatch' USING ERRCODE='23514'; END IF;\n"
  "  order_body := parent.request_snapshot->'orders'->-1;\n"
  "  IF NEW.operation<>'change.order.prepare' AND (\n"
  "    jsonb_array_length(parent.request_snapshot->'orders') IS DISTINCT FROM "
  "jsonb_array_length(previous.request_snapshot->'orders')\n"
  "    OR ((parent.request_snapshot->'orders') - "
  "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS DISTINCT FROM\n"
  "       ((previous.request_snapshot->'orders') - "
  "(jsonb_array_length(previous.request_snapshot->'orders')-1)))\n"
  "    THEN RAISE EXCEPTION 'earlier Orders must remain exact'; END IF;\n"
  "  IF NEW.operation='change.order.prepare' THEN\n"
  "    IF ((parent.request_snapshot->'orders') - "
  "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'orders')\n"
  "      OR parent.status <> 'review' OR previous.status NOT IN ('analysis','review')\n"
  "      OR jsonb_array_length(order_body->'approvals')<>0\n"
  "      OR jsonb_array_length(order_body->'implementations')<>0\n"
  "      OR order_body IS DISTINCT FROM (atom->'order_snapshot')\n"
  "      OR (order_body->>'id')::uuid IS DISTINCT FROM (atom->>'order_id')::uuid\n"
  "      OR order_body->>'content_digest' IS DISTINCT FROM atom->>'content_sha256'\n"
  "      THEN RAISE EXCEPTION 'order material mismatch' USING ERRCODE='23514'; END IF;\n"
  "  ELSIF NEW.operation='change.order.approve' THEN\n"
  "    IF ((order_body->'approvals') - (jsonb_array_length(order_body->'approvals')-1)) IS "
  "DISTINCT FROM (previous.request_snapshot->'orders'->-1->'approvals')\n"
  "      OR (order_body - 'approvals') IS DISTINCT FROM ((previous.request_snapshot->'orders'->-1) "
  "- 'approvals')\n"
  "      OR previous.status <> 'review' OR parent.status NOT IN ('review','approved')\n"
  "      OR (previous.request_snapshot->>'requester_id')::uuid = NEW.actor_id\n"
  "      OR (order_body->'approvals'->-1) IS DISTINCT FROM (atom->'approval_snapshot')\n"
  "      OR (atom->'approval_snapshot'->>'decision_id')::uuid IS DISTINCT FROM "
  'NEW.shared_proof_id\n'
  "      OR (atom->'approval_snapshot'->>'discipline') IS DISTINCT FROM (atom->>'discipline')\n"
  "      OR (atom->'approval_snapshot'->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
  "      OR (atom->'approval_snapshot'->>'content_digest') IS DISTINCT FROM "
  "order_body->>'content_digest'\n"
  "      OR NOT COALESCE(order_body->'required_disciplines' @> "
  "jsonb_build_array(atom->>'discipline'),false)\n"
  "      OR (atom->'approval_snapshot'->>'at')::timestamptz IS DISTINCT FROM "
  "(parent.request_snapshot->'history'->-1->>'at')::timestamptz\n"
  "      OR (order_body->'implementations') IS DISTINCT FROM "
  "(previous.request_snapshot->'orders'->-1->'implementations')\n"
  "      THEN RAISE EXCEPTION 'approval material mismatch' USING ERRCODE='23514'; END IF;\n"
  '  ELSE\n'
  "    IF ((order_body->'implementations') - "
  "(jsonb_array_length(order_body->'implementations')-1)) IS DISTINCT FROM "
  "(previous.request_snapshot->'orders'->-1->'implementations')\n"
  "      OR (order_body - 'implementations') IS DISTINCT FROM "
  "((previous.request_snapshot->'orders'->-1) - 'implementations')\n"
  "      OR previous.status NOT IN ('approved','implementing') OR parent.status <> 'implementing'\n"
  "      OR (order_body->'implementations'->-1) IS DISTINCT FROM (atom->'fact_snapshot')\n"
  "      OR (atom->'fact_snapshot'->>'executor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
  '      OR NOT EXISTS(SELECT 1 FROM change_implementation_captures c WHERE '
  'c.tenant_id=NEW.tenant_id\n'
  '        AND c.product_id=NEW.product_id AND c.project_id=NEW.project_id AND '
  'c.change_id=NEW.change_id\n'
  "        AND c.id=(atom->>'capture_id')::uuid AND c.fact_id=(atom->>'fact_id')::uuid\n"
  "        AND c.fact_snapshot=(atom->'fact_snapshot') AND c.output_basis=(atom->'output_basis'))\n"
  "      OR NOT (order_body->'required_disciplines' @> "
  '\'["engineering","manufacturing"]\'::jsonb)\n'
  "      THEN RAISE EXCEPTION 'implementation material mismatch' USING ERRCODE='23514'; END IF;\n"
  '  END IF;\n'
  '  RETURN NULL;\n'
  'END $function$\n'))

CONSTRAINTS = (('capa_named_verification_reviews',
  'capa_named_verification_reviews_check4',
  'CHECK (((shared_proof_id IS NOT NULL) AND (shared_proof_revision IS NOT NULL) AND '
  '(shared_proof_revision > 0) AND (proof_expires_at IS NOT NULL) AND (proof_consumed_at IS NOT '
  'NULL) AND (proof_consumed_at <= created_at) AND (created_at < proof_expires_at) AND '
  '(token_sha256 IS NOT NULL) AND (material_sha256 IS NOT NULL) AND ((token_sha256)::text ~ '
  "'^[0-9a-f]{64}$'::text) AND ((material_sha256)::text ~ '^[0-9a-f]{64}$'::text)))",
  'CHECK (((shared_proof_id IS NOT NULL) AND (shared_proof_revision IS NOT NULL) AND '
  '(shared_proof_revision > 0) AND (proof_consumed_at IS NOT NULL) AND (proof_consumed_at <= '
  'created_at) AND ((proof_expires_at IS NULL) OR (created_at < proof_expires_at)) AND '
  '(token_sha256 IS NOT NULL) AND (material_sha256 IS NOT NULL) AND ((token_sha256)::text ~ '
  "'^[0-9a-f]{64}$'::text) AND ((material_sha256)::text ~ '^[0-9a-f]{64}$'::text)))"),
 ('change_approval_records',
  'change_approval_records_check1',
  'CHECK (((proof_consumed_at <= created_at) AND (created_at < proof_expires_at)))',
  'CHECK (((proof_consumed_at <= created_at) AND ((proof_expires_at IS NULL) OR (created_at < '
  'proof_expires_at))))'),
 ('controlled_change_selection_facts',
  'controlled_change_selection_facts_check3',
  'CHECK (((proof_consumed_at <= created_at) AND (created_at < proof_expires_at) AND ((valid_until '
  'IS NULL) OR (valid_until > created_at))))',
  'CHECK (((proof_consumed_at <= created_at) AND ((proof_expires_at IS NULL) OR (created_at < '
  'proof_expires_at)) AND ((valid_until IS NULL) OR (valid_until > created_at))))'))

CONFIRMATION_DEADLINE = "expires_at IS NOT NULL OR operation IN ('build.engineering.authorize','build.manufacturing.authorize','change.order.approve','change.selection.decide','proposal.g0.decide','quality.capa.verification.review','quality.issue.root_cause.decide','test.disposition.decide','test.run.review')"
