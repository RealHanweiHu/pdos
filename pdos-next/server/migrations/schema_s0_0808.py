# ruff: noqa: E501 -- exact captured PostgreSQL function definitions.
"""Native development adoption, independent review and separate Change close."""

PREVIOUS_FUNCTIONS = {'require_change_order_atom()': 'CREATE OR REPLACE FUNCTION public.require_change_order_atom()\n'
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
                                '    WHERE tenant_id=parent.tenant_id AND '
                                'product_id=parent.product_id\n'
                                '      AND project_id=parent.project_id AND '
                                'change_id=parent.change_id\n'
                                '      AND id=parent.previous_version_id AND '
                                'revision=parent.previous_revision;\n'
                                '  IF parent.operation IS DISTINCT FROM NEW.operation\n'
                                '    OR parent.owner_id IS DISTINCT FROM previous.owner_id\n'
                                '    OR parent.visibility IS DISTINCT FROM previous.visibility\n'
                                '    OR parent.owner_id IS DISTINCT FROM NEW.owner_id\n'
                                '    OR parent.visibility IS DISTINCT FROM NEW.visibility\n'
                                '    OR parent.sources IS DISTINCT FROM NEW.sources\n'
                                '    OR parent.required_source_read_set IS DISTINCT FROM '
                                'NEW.required_source_read_set\n'
                                '    OR parent.source_basis IS DISTINCT FROM NEW.source_basis\n'
                                '    OR parent.authority_snapshot IS DISTINCT FROM '
                                'NEW.authority_snapshot\n'
                                "    OR (parent.request_snapshot->>'id')::uuid IS DISTINCT FROM "
                                'parent.change_id\n'
                                "    OR (parent.request_snapshot->'scope'->>'tenant_id')::uuid IS "
                                'DISTINCT FROM parent.tenant_id\n'
                                "    OR (parent.request_snapshot->'scope'->>'product_id')::uuid IS "
                                'DISTINCT FROM parent.product_id\n'
                                "    OR (parent.request_snapshot->'scope'->>'project_id')::uuid IS "
                                'DISTINCT FROM parent.project_id\n'
                                '    OR (parent.request_snapshot - '
                                "ARRAY['revision','status','history','orders']) IS DISTINCT FROM "
                                '(previous.request_snapshot - '
                                "ARRAY['revision','status','history','orders'])\n"
                                "    OR jsonb_array_length(parent.request_snapshot->'history') <> "
                                "jsonb_array_length(previous.request_snapshot->'history')+1\n"
                                "    OR ((parent.request_snapshot->'history') - "
                                "(jsonb_array_length(parent.request_snapshot->'history')-1)) IS "
                                "DISTINCT FROM (previous.request_snapshot->'history')\n"
                                "    OR (parent.request_snapshot->'history'->-1->>'command_id')::uuid "
                                'IS DISTINCT FROM NEW.command_id\n'
                                "    OR (parent.request_snapshot->'history'->-1->>'actor_id')::uuid IS "
                                'DISTINCT FROM NEW.actor_id\n'
                                "    OR (parent.request_snapshot->'history'->-1->>'operation') IS "
                                'DISTINCT FROM NEW.operation\n'
                                "    THEN RAISE EXCEPTION 'change atom parent mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                "  expected_tier := CASE NEW.operation WHEN 'change.order.approve' "
                                "THEN 'T2' ELSE 'T1' END;\n"
                                "  IF NOT COALESCE(jsonb_typeof(NEW.input_snapshot)='object'\n"
                                '    AND NEW.input_snapshot ?& '
                                "ARRAY['semantic','shared_proof','review']\n"
                                '    AND (NEW.input_snapshot - '
                                "ARRAY['semantic','shared_proof','review'])='{}'::jsonb\n"
                                "    AND jsonb_typeof(NEW.input_snapshot->'review')='object'\n"
                                "    AND (NEW.input_snapshot->'review') ?& "
                                "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier']\n"
                                "    AND ((NEW.input_snapshot->'review') - "
                                "ARRAY['operation','payload_semantic','before','after','read_set','sources','authority','policy','source_basis','selection','effect','unknown','proof_tier'])='{}'::jsonb\n"
                                '    AND '
                                "(NEW.input_snapshot->'shared_proof')=jsonb_build_object('id',NEW.shared_proof_id,'tier',expected_tier)\n"
                                "    AND jsonb_typeof(parent.request_snapshot->'history')='array'\n"
                                '    AND '
                                "jsonb_typeof(parent.request_snapshot->'orders')='array',false)\n"
                                "    THEN RAISE EXCEPTION 'exact change review shape required' USING "
                                "ERRCODE='23514'; END IF;\n"
                                '  proposed := '
                                'jsonb_set(parent.request_snapshot,\'{history,-1,at}\',\'"server_on_save"\'::jsonb);\n'
                                "  IF NEW.operation='change.order.approve' THEN\n"
                                '    proposed := '
                                'jsonb_set(proposed,\'{orders,-1,approvals,-1,at}\',\'"server_on_save"\'::jsonb);\n'
                                '    proposed := '
                                'jsonb_set(proposed,\'{orders,-1,approvals,-1,decision_id}\',\'"actual_consumed_named_proof_on_save"\'::jsonb);\n'
                                '  END IF;\n'
                                "  IF NEW.input_snapshot->'review'->>'operation' IS DISTINCT FROM "
                                'NEW.operation\n'
                                "    OR NEW.input_snapshot->'review'->>'proof_tier' IS DISTINCT FROM "
                                'expected_tier\n'
                                "    OR NEW.input_snapshot->'review'->'payload_semantic' IS DISTINCT "
                                "FROM NEW.input_snapshot->'semantic'\n"
                                "    OR NEW.input_snapshot->'review'->'before' IS DISTINCT FROM "
                                'previous.request_snapshot\n'
                                "    OR NEW.input_snapshot->'review'->'after' IS DISTINCT FROM "
                                'proposed\n'
                                "    OR NEW.input_snapshot->'review'->'read_set' IS DISTINCT FROM "
                                'NEW.required_source_read_set\n'
                                "    OR NEW.input_snapshot->'review'->'sources' IS DISTINCT FROM "
                                'NEW.sources\n'
                                "    OR NEW.input_snapshot->'review'->'authority' IS DISTINCT FROM "
                                'NEW.authority_snapshot\n'
                                "    OR NEW.input_snapshot->'review'->'policy' IS DISTINCT FROM "
                                'NEW.policy_snapshot\n'
                                "    OR NEW.input_snapshot->'review'->'source_basis' IS DISTINCT FROM "
                                'NEW.source_basis\n'
                                "    OR NOT COALESCE(jsonb_typeof(NEW.sources)='array' AND "
                                'jsonb_array_length(NEW.sources)>0\n'
                                "      AND jsonb_typeof(NEW.required_source_read_set)='array'\n"
                                '      AND jsonb_array_length(NEW.required_source_read_set)>0,false)\n'
                                "    THEN RAISE EXCEPTION 'change review correspondence mismatch' "
                                "USING ERRCODE='23514'; END IF;\n"
                                '  SELECT * INTO STRICT proof FROM confirmations\n'
                                '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND '
                                'id=NEW.shared_proof_id;\n'
                                '  IF NOT proof.consumed OR proof.actor_id IS DISTINCT FROM '
                                'NEW.actor_id\n'
                                '    OR proof.subject_id IS DISTINCT FROM NEW.product_id\n'
                                '    OR proof.operation IS DISTINCT FROM NEW.operation\n'
                                '    OR proof.revision IS DISTINCT FROM NEW.shared_proof_revision\n'
                                '    OR proof.token_hash IS DISTINCT FROM NEW.token_sha256\n'
                                '    OR proof.payload_digest IS DISTINCT FROM NEW.material_sha256\n'
                                '    OR proof.snapshot IS DISTINCT FROM '
                                "(NEW.input_snapshot->'review')\n"
                                '    OR proof.created_at > NEW.proof_consumed_at\n'
                                '    OR NEW.proof_consumed_at > NEW.created_at\n'
                                '    OR (proof.expires_at IS NOT NULL AND NEW.created_at >= '
                                'proof.expires_at)\n'
                                '    OR proof.expires_at IS DISTINCT FROM NEW.proof_expires_at\n'
                                "    THEN RAISE EXCEPTION 'change proof group mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                '  SELECT * INTO STRICT receipt FROM action_receipts\n'
                                '    WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id\n'
                                "      AND operation=NEW.operation AND subject_type='change_request'\n"
                                '      AND subject_id=parent.id AND subject_revision=parent.revision;\n'
                                "  effect := CASE NEW.operation WHEN 'change.order.prepare' THEN "
                                "'change.order_prepared'\n"
                                "    WHEN 'change.order.approve' THEN 'change.approved' ELSE "
                                "'change.implementation_recorded' END;\n"
                                '  IF receipt.actor_id IS DISTINCT FROM NEW.actor_id\n'
                                '    OR receipt.requester_id IS DISTINCT FROM NEW.actor_id OR '
                                'receipt.run_id IS NOT NULL\n'
                                '    OR receipt.visibility IS DISTINCT FROM parent.visibility\n'
                                '    OR receipt.command_id IS DISTINCT FROM NEW.command_id\n'
                                '    OR receipt.intent_digest IS DISTINCT FROM NEW.intent_digest\n'
                                "    OR (receipt.result->>'id')::uuid IS DISTINCT FROM parent.id\n"
                                "    OR (receipt.result->>'revision')::integer IS DISTINCT FROM "
                                'parent.revision\n'
                                "    OR receipt.result->>'status' IS DISTINCT FROM parent.status\n"
                                '    OR NOT EXISTS(SELECT 1 FROM request_keys k WHERE '
                                'k.tenant_id=receipt.tenant_id\n'
                                '      AND k.actor_id=receipt.actor_id AND k.receipt_id=receipt.id AND '
                                'k.digest=receipt.request_digest)\n'
                                '    OR (SELECT count(*) FROM audit_entries a WHERE '
                                'a.tenant_id=receipt.tenant_id AND a.receipt_id=receipt.id\n'
                                '      AND a.actor_id=receipt.actor_id AND '
                                'a.operation=receipt.operation)<>1\n'
                                '    OR (SELECT count(*) FROM outbox_events o WHERE '
                                'o.tenant_id=receipt.tenant_id AND o.receipt_id=receipt.id\n'
                                '      AND o.type=effect AND o.actor_id=receipt.actor_id AND '
                                'o.correlation_id=receipt.command_id\n'
                                '      AND o.subject_id=parent.id AND '
                                'o.subject_revision=parent.revision)<>1\n'
                                "    THEN RAISE EXCEPTION 'change common group mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                "  order_body := parent.request_snapshot->'orders'->-1;\n"
                                "  IF NEW.operation<>'change.order.prepare' AND (\n"
                                "    jsonb_array_length(parent.request_snapshot->'orders') IS DISTINCT "
                                "FROM jsonb_array_length(previous.request_snapshot->'orders')\n"
                                "    OR ((parent.request_snapshot->'orders') - "
                                "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS "
                                'DISTINCT FROM\n'
                                "       ((previous.request_snapshot->'orders') - "
                                "(jsonb_array_length(previous.request_snapshot->'orders')-1)))\n"
                                "    THEN RAISE EXCEPTION 'earlier Orders must remain exact'; END IF;\n"
                                "  IF NEW.operation='change.order.prepare' THEN\n"
                                "    IF ((parent.request_snapshot->'orders') - "
                                "(jsonb_array_length(parent.request_snapshot->'orders')-1)) IS "
                                "DISTINCT FROM (previous.request_snapshot->'orders')\n"
                                "      OR parent.status <> 'review' OR previous.status NOT IN "
                                "('analysis','review')\n"
                                "      OR jsonb_array_length(order_body->'approvals')<>0\n"
                                "      OR jsonb_array_length(order_body->'implementations')<>0\n"
                                "      OR order_body IS DISTINCT FROM (atom->'order_snapshot')\n"
                                "      OR (order_body->>'id')::uuid IS DISTINCT FROM "
                                "(atom->>'order_id')::uuid\n"
                                "      OR order_body->>'content_digest' IS DISTINCT FROM "
                                "atom->>'content_sha256'\n"
                                "      THEN RAISE EXCEPTION 'order material mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                "  ELSIF NEW.operation='change.order.approve' THEN\n"
                                "    IF ((order_body->'approvals') - "
                                "(jsonb_array_length(order_body->'approvals')-1)) IS DISTINCT FROM "
                                "(previous.request_snapshot->'orders'->-1->'approvals')\n"
                                "      OR (order_body - 'approvals') IS DISTINCT FROM "
                                "((previous.request_snapshot->'orders'->-1) - 'approvals')\n"
                                "      OR previous.status <> 'review' OR parent.status NOT IN "
                                "('review','approved')\n"
                                "      OR (previous.request_snapshot->>'requester_id')::uuid = "
                                'NEW.actor_id\n'
                                "      OR (order_body->'approvals'->-1) IS DISTINCT FROM "
                                "(atom->'approval_snapshot')\n"
                                "      OR (atom->'approval_snapshot'->>'decision_id')::uuid IS "
                                'DISTINCT FROM NEW.shared_proof_id\n'
                                "      OR (atom->'approval_snapshot'->>'discipline') IS DISTINCT FROM "
                                "(atom->>'discipline')\n"
                                "      OR (atom->'approval_snapshot'->>'actor_id')::uuid IS DISTINCT "
                                'FROM NEW.actor_id\n'
                                "      OR (atom->'approval_snapshot'->>'content_digest') IS DISTINCT "
                                "FROM order_body->>'content_digest'\n"
                                "      OR NOT COALESCE(order_body->'required_disciplines' @> "
                                "jsonb_build_array(atom->>'discipline'),false)\n"
                                "      OR (atom->'approval_snapshot'->>'at')::timestamptz IS DISTINCT "
                                "FROM (parent.request_snapshot->'history'->-1->>'at')::timestamptz\n"
                                "      OR (order_body->'implementations') IS DISTINCT FROM "
                                "(previous.request_snapshot->'orders'->-1->'implementations')\n"
                                "      THEN RAISE EXCEPTION 'approval material mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                '  ELSE\n'
                                "    IF ((order_body->'implementations') - "
                                "(jsonb_array_length(order_body->'implementations')-1)) IS DISTINCT "
                                "FROM (previous.request_snapshot->'orders'->-1->'implementations')\n"
                                "      OR (order_body - 'implementations') IS DISTINCT FROM "
                                "((previous.request_snapshot->'orders'->-1) - 'implementations')\n"
                                "      OR previous.status NOT IN ('approved','implementing') OR "
                                "parent.status <> 'implementing'\n"
                                "      OR (order_body->'implementations'->-1) IS DISTINCT FROM "
                                "(atom->'fact_snapshot')\n"
                                "      OR (atom->'fact_snapshot'->>'executor_id')::uuid IS DISTINCT "
                                'FROM NEW.actor_id\n'
                                '      OR NOT EXISTS(SELECT 1 FROM change_implementation_captures c '
                                'WHERE c.tenant_id=NEW.tenant_id\n'
                                '        AND c.product_id=NEW.product_id AND '
                                'c.project_id=NEW.project_id AND c.change_id=NEW.change_id\n'
                                "        AND c.id=(atom->>'capture_id')::uuid AND "
                                "c.fact_id=(atom->>'fact_id')::uuid\n"
                                "        AND c.fact_snapshot=(atom->'fact_snapshot') AND "
                                "c.output_basis=(atom->'output_basis'))\n"
                                "      OR NOT (order_body->'required_disciplines' @> "
                                '\'["engineering","manufacturing"]\'::jsonb)\n'
                                "      THEN RAISE EXCEPTION 'implementation material mismatch' USING "
                                "ERRCODE='23514'; END IF;\n"
                                '  END IF;\n'
                                '  RETURN NULL;\n'
                                'END $function$\n',
 'require_change_order_parent_atom()': 'CREATE OR REPLACE FUNCTION '
                                       'public.require_change_order_parent_atom()\n'
                                       ' RETURNS trigger\n'
                                       ' LANGUAGE plpgsql\n'
                                       " SET search_path TO 'pg_catalog', 'public'\n"
                                       'AS $function$\n'
                                       'DECLARE count_atoms integer;\n'
                                       'BEGIN\n'
                                       '  IF NEW.operation NOT IN '
                                       "('change.order.prepare','change.order.approve','change.implementation.record') "
                                       'THEN RETURN NULL; END IF;\n'
                                       '  SELECT count(*) INTO count_atoms FROM (\n'
                                       '    SELECT '
                                       'tenant_id,product_id,change_version_id,change_revision,operation '
                                       'FROM change_order_records\n'
                                       '    UNION ALL SELECT '
                                       'tenant_id,product_id,change_version_id,change_revision,operation '
                                       'FROM change_approval_records\n'
                                       '    UNION ALL SELECT '
                                       'tenant_id,product_id,change_version_id,change_revision,operation '
                                       'FROM change_implementation_records\n'
                                       '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND '
                                       'atoms.product_id=NEW.product_id\n'
                                       '    AND atoms.change_version_id=NEW.id AND '
                                       'atoms.change_revision=NEW.revision AND '
                                       'atoms.operation=NEW.operation;\n'
                                       "  IF count_atoms<>1 THEN RAISE EXCEPTION 'missing exact change "
                                       "child atom' USING ERRCODE='23514'; END IF;\n"
                                       '  RETURN NULL;\n'
                                       'END $function$\n',
 'require_change_order_proof_atom()': 'CREATE OR REPLACE FUNCTION '
                                      'public.require_change_order_proof_atom()\n'
                                      ' RETURNS trigger\n'
                                      ' LANGUAGE plpgsql\n'
                                      " SET search_path TO 'pg_catalog', 'public'\n"
                                      'AS $function$\n'
                                      'DECLARE count_atoms integer;\n'
                                      'BEGIN\n'
                                      '  IF NEW.operation NOT IN '
                                      "('change.order.prepare','change.order.approve','change.implementation.record') "
                                      'OR NOT NEW.consumed THEN RETURN NULL; END IF;\n'
                                      '  SELECT count(*) INTO count_atoms FROM (\n'
                                      '    SELECT '
                                      'tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
                                      'change_order_records\n'
                                      '    UNION ALL SELECT '
                                      'tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
                                      'change_approval_records\n'
                                      '    UNION ALL SELECT '
                                      'tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
                                      'change_implementation_records\n'
                                      '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND '
                                      'atoms.product_id=NEW.product_id\n'
                                      '    AND atoms.shared_proof_id=NEW.id AND '
                                      'atoms.actor_id=NEW.actor_id AND atoms.operation=NEW.operation;\n'
                                      "  IF count_atoms<>1 THEN RAISE EXCEPTION 'consumed proof "
                                      "missing unique change atom' USING ERRCODE='23514'; END IF;\n"
                                      '  RETURN NULL;\n'
                                      'END $function$\n',
 'require_change_receipt_atom()': 'CREATE OR REPLACE FUNCTION public.require_change_receipt_atom()\n'
                                  ' RETURNS trigger\n'
                                  ' LANGUAGE plpgsql\n'
                                  " SET search_path TO 'pg_catalog', 'public'\n"
                                  'AS $function$\n'
                                  'DECLARE tab text; n integer;\n'
                                  'BEGIN\n'
                                  '  IF NEW.operation IN '
                                  "('change.policy.import','change.selection.decide') THEN\n"
                                  "    tab:=CASE NEW.operation WHEN 'change.policy.import' THEN "
                                  "'controlled_change_policy_facts'\n"
                                  "      ELSE 'controlled_change_selection_facts' END;\n"
                                  '    PERFORM '
                                  'assert_controlled_change_atom(tab,NEW.tenant_id,NEW.subject_id);\n'
                                  '  ELSIF NEW.operation IN '
                                  "('change.order.prepare','change.order.approve','change.implementation.record') "
                                  'THEN\n'
                                  '    SELECT count(*) INTO n FROM (\n'
                                  '      SELECT '
                                  'tenant_id,product_id,change_version_id,change_revision,operation '
                                  'FROM change_order_records\n'
                                  '      UNION ALL SELECT '
                                  'tenant_id,product_id,change_version_id,change_revision,operation '
                                  'FROM change_approval_records\n'
                                  '      UNION ALL SELECT '
                                  'tenant_id,product_id,change_version_id,change_revision,operation '
                                  'FROM change_implementation_records\n'
                                  '    ) a WHERE a.tenant_id=NEW.tenant_id AND '
                                  'a.product_id=NEW.product_id\n'
                                  '      AND a.change_version_id=NEW.subject_id AND '
                                  'a.change_revision=NEW.subject_revision\n'
                                  '      AND a.operation=NEW.operation;\n'
                                  "    IF n<>1 OR NEW.subject_type<>'change_request' THEN RAISE "
                                  "EXCEPTION 'receipt has no exact change atom'; END IF;\n"
                                  '  END IF;\n'
                                  '  RETURN NULL;\n'
                                  'END $function$\n',
 'm3_lifecycle_source_links(uuid,uuid,text,jsonb)': 'CREATE OR REPLACE FUNCTION '
                                                    'public.m3_lifecycle_source_links(t uuid, c uuid, '
                                                    'table_name text, payload jsonb)\n'
                                                    ' RETURNS uuid[]\n'
                                                    ' LANGUAGE plpgsql\n'
                                                    ' STABLE SECURITY DEFINER\n'
                                                    " SET search_path TO 'pg_catalog', 'public', "
                                                    "'pg_temp'\n"
                                                    'AS $function$\n'
                                                    "DECLARE links uuid[]='{}'; extra uuid[]; key "
                                                    'text; keys text[]; item jsonb; container jsonb;\n'
                                                    ' target_kind text; referenced_target uuid; '
                                                    'referenced_version integer;\n'
                                                    'BEGIN\n'
                                                    " IF table_name='agent_runs' THEN RETURN "
                                                    'public.kernel_lifecycle_links(table_name,payload); '
                                                    'END IF;\n'
                                                    ' -- Only actual top-level relation columns '
                                                    'establish raw UUID edges. Arbitrary\n'
                                                    ' -- content dictionaries are not relational rows, '
                                                    'even if an extra key happens\n'
                                                    ' -- to be named source_id or item_id.\n'
                                                    ' keys=CASE table_name\n'
                                                    "  WHEN 'artifact_versions' THEN "
                                                    "ARRAY['original_id']\n"
                                                    "  WHEN 'claims' THEN "
                                                    "ARRAY['artifact_id','snapshot_id']\n"
                                                    "  WHEN 'definition_revisions' THEN "
                                                    "ARRAY['derived_from_definition_id','parent_definition_id',\n"
                                                    "   'source_proposal_id','source_submission_id']\n"
                                                    "  WHEN 'definition_sources' THEN "
                                                    "ARRAY['artifact_id']\n"
                                                    "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposals' THEN "
                                                    "ARRAY['baseline_definition_id','current_submission_id']\n"
                                                    "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
                                                    "  WHEN 'proposal_item_versions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_revisions' THEN "
                                                    "ARRAY['proposal_id']\n"
                                                    "  WHEN 'proposal_sources' THEN "
                                                    "ARRAY['source_id']\n"
                                                    "  WHEN 'proposal_submissions' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    "  WHEN 'proposal_decisions' THEN "
                                                    "ARRAY['submission_id']\n"
                                                    "  WHEN 'project_open_items' THEN "
                                                    "ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
                                                    "  WHEN 'category_knowledge_current' THEN "
                                                    "ARRAY['current_entry_id']\n"
                                                    "  WHEN 'promotion_proofs' THEN "
                                                    "ARRAY['knowledge_entry_id','source_proposal_id']\n"
                                                    "  WHEN 'evidence_links' THEN "
                                                    "ARRAY['evidence_id']\n"
                                                    "  WHEN 'claim_withdrawals' THEN "
                                                    "ARRAY['claim_id']\n"
                                                    "  WHEN 'manufacturing_baseline_publications' THEN "
                                                    "ARRAY['baseline_id','process_id','previous_id']\n"
                                                    "  WHEN 'manufacturing_publication_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'manufacturing_publication_documents' THEN "
                                                    "ARRAY['document_id','process_id']\n"
                                                    "  WHEN 'native_pilot_runs' THEN "
                                                    "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
                                                    "  WHEN 'native_pilot_currents' THEN "
                                                    "ARRAY['pilot_id','latest_observation_id']\n"
                                                    "  WHEN 'native_pilot_observations' THEN "
                                                    "ARRAY['pilot_id','previous_observation_id']\n"
                                                    "  WHEN 'release_packages' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_package_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'release_decisions' THEN "
                                                    "ARRAY['package_id']\n"
                                                    "  WHEN 'release_policy_facts' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'release_policy_currents' THEN "
                                                    "ARRAY['fact_id']\n"
                                                    "  WHEN 'external_handoff_authorizations' THEN "
                                                    "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
                                                    "  WHEN 'external_delivery_intents' THEN "
                                                    "ARRAY['handoff_id']\n"
                                                    "  WHEN 'external_receipts' THEN "
                                                    "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
                                                    "  WHEN 'external_handoff_currents' THEN "
                                                    "ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
                                                    "  WHEN 'release_exception_decisions' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
                                                    "  WHEN 'release_exception_currents' THEN "
                                                    "ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
                                                    "  WHEN 'work_commitment_reviews' THEN "
                                                    "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
                                                    "  WHEN 'work_commitment_review_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'external_wait_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'external_wait_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_risk_followups' THEN "
                                                    "ARRAY['previous_id','risk_id','g0_decision_id']\n"
                                                    "  WHEN 'project_risk_followup_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_task_versions' THEN "
                                                    "ARRAY['previous_id']\n"
                                                    "  WHEN 'work_task_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'work_commitment_versions' THEN "
                                                    "ARRAY['replaces_id']\n"
                                                    "  WHEN 'work_commitment_currents' THEN "
                                                    "ARRAY['version_id']\n"
                                                    "  WHEN 'project_status_updates' THEN "
                                                    'ARRAY[]::text[]\n'
                                                    '  ELSE ARRAY[]::text[] END;\n'
                                                    ' FOREACH key IN ARRAY keys LOOP\n'
                                                    '  IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    ' END LOOP;\n'
                                                    " -- Publication's exact saved read set is a "
                                                    'validated Artifact relationship.\n'
                                                    ' -- Do not scan its declaration, body, reason or '
                                                    'arbitrary JSON UUID values.\n'
                                                    ' IF table_name IN '
                                                    "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN\n"
                                                    '    '
                                                    "links=array_append(links,(item->>'artifact_id')::uuid);\n"
                                                    '   END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('native_pilot_runs','native_pilot_observations') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  '
                                                    "item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
                                                    "  IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_packages' THEN\n"
                                                    '  -- FixedObject.ref is a closed, server-resolved '
                                                    'version reference, not arbitrary body UUID text.\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) "
                                                    'LOOP\n'
                                                    "   container=item->'ref';\n"
                                                    '   IF '
                                                    "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
                                                    "    AND container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('external_handoff_authorizations','external_delivery_intents') "
                                                    'THEN\n'
                                                    '  -- Only closed, owner-verified mapping and '
                                                    'manifest references are source edges.\n'
                                                    '  container=CASE WHEN '
                                                    "table_name='external_handoff_authorizations' THEN "
                                                    "payload#>'{body,declaration}' ELSE "
                                                    "payload->'body' END;\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'mappings','[]')) "
                                                    'LOOP\n'
                                                    '   IF '
                                                    "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
                                                    "    AND item->'ref'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'ref'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'manifest','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->'artifact'->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->'artifact'->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='release_policy_facts' THEN\n"
                                                    '  -- These are Closed DTO configuration '
                                                    'references fixed by the policy owner.\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
                                                    'LOOP\n'
                                                    '   '
                                                    "container=payload#>ARRAY['material','subject_config',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- These stored fields are validated Reference '
                                                    'containers. Do not feed the\n'
                                                    ' -- whole row or arbitrary content into the '
                                                    'canonical Reference parser.\n'
                                                    ' IF '
                                                    "table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
                                                    '  '
                                                    "'category_knowledge_entries','definition_specs']) "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,payload->key);\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Match ItemInput.content_schema and '
                                                    'category_service._references: only\n'
                                                    ' -- commercial_target, voice, and competitor have '
                                                    'nested source contracts.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'kind'='commercial_target' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['target_price','cost','volume'] LOOP\n"
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='voice' THEN\n"
                                                    '  links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'kind'='competitor' THEN\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['metrics','features','prices'] LOOP\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'content'->key,'[]')) "
                                                    'LOOP\n'
                                                    '    links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
                                                    '   END LOOP;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='proposal_submissions' THEN\n"
                                                    "  container=payload->'frozen_document';\n"
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    'public.m3_lifecycle_typed_links(t,c,container->key);\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(container->'items','[]')) "
                                                    'LOOP\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
                                                    '   -- The frozen read projection records actual '
                                                    'EvidenceLink provenance here.\n'
                                                    '   links=links || '
                                                    "public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
                                                    '  END LOOP;\n'
                                                    " ELSIF table_name='promotion_proofs' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'item_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'item_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' -- Exact persisted EvidenceLink targets '
                                                    'supplement these immutable versions.\n'
                                                    ' -- Reverted links and withdrawn Claims still '
                                                    'retain the original historical\n'
                                                    ' -- dependency; lifecycle cleanup must not erase '
                                                    'their audit source.\n'
                                                    " IF table_name='proposal_item_versions' AND "
                                                    "payload->>'item_id' IS NOT NULL THEN\n"
                                                    "  target_kind='proposal_item'; "
                                                    "referenced_target=(payload->>'item_id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='category_knowledge_entries' "
                                                    "AND payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='knowledge_entry'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  '
                                                    "referenced_version=(payload->>'version')::integer;\n"
                                                    " ELSIF table_name='definition_specs' AND "
                                                    "payload->>'id' IS NOT NULL THEN\n"
                                                    "  target_kind='definition_spec'; "
                                                    "referenced_target=(payload->>'id')::uuid;\n"
                                                    '  SELECT revision INTO referenced_version FROM '
                                                    'public.definition_revisions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "id=(payload->>'definition_id')::uuid;\n"
                                                    ' END IF;\n'
                                                    ' IF referenced_target IS NOT NULL AND '
                                                    'referenced_version IS NOT NULL THEN\n'
                                                    '  SELECT '
                                                    "coalesce(array_agg(link.evidence_id),'{}') INTO "
                                                    'extra FROM public.evidence_links link\n'
                                                    '   WHERE link.tenant_id=t AND link.category_id=c '
                                                    'AND link.target_type=target_kind\n'
                                                    '    AND link.target_id=referenced_target AND '
                                                    'link.target_version=referenced_version;\n'
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    ' -- Child source rows point to their parent, '
                                                    'whereas dependency traversal needs\n'
                                                    " -- the parent's fixed source children as well. "
                                                    'Keep the actual relational edge.\n'
                                                    " IF table_name='definition_revisions' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM (\n'
                                                    '   SELECT id FROM public.definition_sources WHERE '
                                                    'tenant_id=t AND category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '   UNION ALL SELECT id FROM '
                                                    'public.definition_specs WHERE tenant_id=t AND '
                                                    'category_id=c\n'
                                                    "    AND definition_id=(payload->>'id')::uuid\n"
                                                    '  ) children;\n'
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposals' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "proposal_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='proposal_items' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.proposal_item_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "item_id=(payload->>'id')::uuid;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='product_target_segments' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.category_knowledge_entries\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "lineage_id=(payload->>'segment_lineage_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'segment_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    " ELSIF table_name='parameter_current' THEN\n"
                                                    "  SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.parameter_versions\n'
                                                    '   WHERE tenant_id=t AND category_id=c AND '
                                                    "parameter_id=(payload->>'parameter_id')::uuid\n"
                                                    '    AND '
                                                    "version=(payload->>'current_version')::integer;\n"
                                                    '  links=links || extra;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('work_task_versions','work_commitment_versions','project_status_updates') "
                                                    'THEN\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  IF table_name='work_task_versions' AND "
                                                    "payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
                                                    '   '
                                                    "links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
                                                    '  END IF;\n'
                                                    "  IF table_name='work_commitment_versions' THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.work_task_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(payload->>'task_id')::uuid AND "
                                                    "revision=(payload->>'task_revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    "  ELSIF table_name='project_status_updates' THEN\n"
                                                    '   FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'task_refs','[]')) "
                                                    'LOOP\n'
                                                    "    SELECT coalesce(array_agg(id),'{}') INTO "
                                                    'extra FROM public.work_task_versions\n'
                                                    '     WHERE tenant_id=t AND category_id=c AND '
                                                    "task_id=(item->>'id')::uuid AND "
                                                    "revision=(item->>'revision')::integer;\n"
                                                    '    links=links||extra;\n'
                                                    '   END LOOP;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='work_commitment_reviews' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    " IF table_name='external_wait_versions' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['milestone','build','calendar'] LOOP\n"
                                                    "   container=payload#>ARRAY['body',key];\n"
                                                    "   IF container->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(container->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  container=payload#>'{body,replaces}';\n"
                                                    "  IF container->>'id' IS NOT NULL THEN\n"
                                                    "   SELECT coalesce(array_agg(id),'{}') INTO extra "
                                                    'FROM public.external_wait_versions\n'
                                                    '    WHERE tenant_id=t AND category_id=c AND '
                                                    "wait_id=(container->>'id')::uuid AND "
                                                    "revision=(container->>'revision')::integer;\n"
                                                    '   links=links||extra;\n'
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='project_risk_followups' THEN\n"
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] "
                                                    'LOOP\n'
                                                    '   IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload->'reads','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'artifact_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'artifact_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'receipt_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'receipt_id')::uuid); "
                                                    'END IF;\n'
                                                    "   IF item->>'row_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'row_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    "  IF payload#>>'{source_basis,target,id}' IS NOT "
                                                    'NULL THEN '
                                                    "links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); "
                                                    'END IF;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' IF table_name IN '
                                                    "('field_feedback_versions','field_feedback_currents','field_response_records') "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['previous_id','version_id','feedback_version_id'] "
                                                    'LOOP\n'
                                                    '   IF payload->>key IS NOT NULL THEN '
                                                    'links=array_append(links,(payload->>key)::uuid); '
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['engineering_configuration','manufacturing_configuration','batch'] "
                                                    'LOOP\n'
                                                    "   IF payload#>>ARRAY['body','location',key,'id'] "
                                                    'IS NOT NULL THEN '
                                                    "links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    '  FOR item IN SELECT value FROM '
                                                    "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) "
                                                    'LOOP\n'
                                                    "   IF item->>'receipt_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'receipt_id')::uuid); "
                                                    'END IF;\n'
                                                    "   IF item->>'row_id' IS NOT NULL THEN "
                                                    "links=array_append(links,(item->>'row_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' IF table_name IN '
                                                    "('change_request_versions','change_graph_captures') "
                                                    'THEN\n'
                                                    '  FOR container IN SELECT value FROM '
                                                    "jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) "
                                                    'LOOP\n'
                                                    "   IF container->>'feedback_version_id' IS NOT "
                                                    'NULL THEN '
                                                    "links=array_append(links,(container->>'feedback_version_id')::uuid); "
                                                    'END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    '\n'
                                                    ' -- Closed native Field plan and occurrence '
                                                    'references, never arbitrary UUID prose.\n'
                                                    ' IF '
                                                    "table_name='controlled_change_selection_facts' "
                                                    "AND payload->>'basis_kind'='field_intent' THEN\n"
                                                    "  IF payload->>'feedback_version_id' IS NOT NULL "
                                                    'THEN\n'
                                                    '   '
                                                    "links=array_append(links,(payload->>'feedback_version_id')::uuid);\n"
                                                    '  END IF;\n'
                                                    ' END IF;\n'
                                                    " IF table_name='change_implementation_captures'\n"
                                                    '  AND '
                                                    "payload#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v1' "
                                                    'THEN\n'
                                                    '  FOREACH key IN ARRAY '
                                                    "ARRAY['feedback_version_id','selection_id'] LOOP\n"
                                                    "   IF payload#>>ARRAY['occurrence_snapshot',key] "
                                                    'IS NOT NULL THEN\n'
                                                    '    '
                                                    "links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);\n"
                                                    '   END IF;\n'
                                                    '  END LOOP;\n'
                                                    ' END IF;\n'
                                                    ' RETURN links;\n'
                                                    'END;\n'
                                                    '$function$\n'}

FIELD_FUNCTIONS = {}

SCHEMA_SQL = ('\n'
 'CREATE TABLE change_completion_records (\n'
 '\torder_id UUID NOT NULL, \n'
 '\torder_record_id UUID NOT NULL, \n'
 '\titem_id UUID, \n'
 '\tfact_id UUID NOT NULL, \n'
 '\tfact_snapshot JSONB NOT NULL, \n'
 '\tnative_input JSONB NOT NULL, \n'
 '\towner_basis JSONB NOT NULL, \n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tchange_id UUID NOT NULL, \n'
 '\tchange_version_id UUID NOT NULL, \n'
 '\tchange_revision INTEGER NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tactor_id UUID NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tcommand_id UUID NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\tshared_proof_id UUID NOT NULL, \n'
 '\tshared_proof_revision INTEGER NOT NULL, \n'
 '\tproof_consumed_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tproof_expires_at TIMESTAMP WITH TIME ZONE, \n'
 '\ttoken_sha256 VARCHAR(64) NOT NULL, \n'
 '\tmaterial_sha256 VARCHAR(64) NOT NULL, \n'
 '\tread_set_sha256 VARCHAR(64) NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\tpolicy_snapshot JSONB NOT NULL, \n'
 '\tinput_snapshot JSONB NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcategory_id UUID NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, change_id, change_version_id, change_revision), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, change_id, operation, fact_id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, change_id, change_version_id, change_revision) '
 'REFERENCES change_request_versions (tenant_id, product_id, project_id, change_id, id, revision) '
 'DEFERRABLE INITIALLY DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, shared_proof_id) REFERENCES confirmations (tenant_id, id) DEFERRABLE '
 'INITIALLY DEFERRED, \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, change_id, order_id, order_record_id) REFERENCES '
 'change_order_records (tenant_id, product_id, project_id, change_id, order_id, id), \n'
 "\tCHECK (operation IN ('change.effectivity.record','change.verification.record','change.close')), \n"
 '\tCHECK (revision = 1 AND change_revision > 1 AND shared_proof_revision > 0), \n'
 "\tCHECK (visibility IN ('private','category','audience')), \n"
 '\tCHECK (proof_consumed_at <= created_at AND (proof_expires_at IS NULL OR created_at < '
 'proof_expires_at)), \n'
 "\tCHECK (operation <> 'change.effectivity.record' OR (proof_expires_at IS NOT NULL AND item_id IS "
 'NOT NULL)), \n'
 "\tCHECK (operation = 'change.effectivity.record' OR item_id IS NULL), \n"
 '\tCHECK (jsonb_array_length(required_source_read_set)>0), \n'
 '\tCONSTRAINT fk_change_completion_records_category FOREIGN KEY(tenant_id, category_id) REFERENCES '
 'categories (tenant_id, id), \n'
 '\tCONSTRAINT fk_change_completion_records_category_product FOREIGN KEY(tenant_id, category_id, '
 'product_id) REFERENCES products (tenant_id, category_id, id)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_change_completion_records_category_id ON change_completion_records (category_id)',
 'CREATE INDEX ix_change_completion_records_tenant_id ON change_completion_records (tenant_id)',
 'CREATE POLICY owner_internal ON public.change_completion_records FOR ALL TO pdos_next_owner USING '
 '(true) WITH CHECK (true)',
 'CREATE POLICY category_scope ON public.change_completion_records FOR ALL TO public USING '
 "((category_access(tenant_id, category_id) AND (((visibility)::text = 'category'::text) OR (owner_id "
 '= scope_requester()) OR (EXISTS ( SELECT 1\n'
 '   FROM object_audiences a\n'
 '  WHERE ((a.tenant_id = change_completion_records.tenant_id) AND (a.category_id = '
 'change_completion_records.category_id) AND ((a.object_type)::text = '
 "'change_completion_records'::text) AND (a.subject_id = change_completion_records.id) AND (a.owner_id "
 '= change_completion_records.owner_id) AND (a.principal_id = scope_requester()))))))) WITH CHECK '
 "((category_access(tenant_id, category_id, true) AND (((visibility)::text = 'category'::text) OR "
 '(owner_id = scope_requester()) OR (EXISTS ( SELECT 1\n'
 '   FROM object_audiences a\n'
 '  WHERE ((a.tenant_id = change_completion_records.tenant_id) AND (a.category_id = '
 'change_completion_records.category_id) AND ((a.object_type)::text = '
 "'change_completion_records'::text) AND (a.subject_id = change_completion_records.id) AND (a.owner_id "
 '= change_completion_records.owner_id) AND (a.principal_id = scope_requester())))))))',
 'CREATE POLICY model_audience ON public.change_completion_records FOR ALL TO '
 'pdos_agent,pdos_next_app,pdos_next_auth,pdos_next_dispatch USING ((category_access(tenant_id, '
 'category_id) AND (EXISTS ( SELECT 1\n'
 '   FROM products p\n'
 '  WHERE ((p.tenant_id = change_completion_records.tenant_id) AND (p.category_id = '
 'change_completion_records.category_id) AND (p.id = change_completion_records.product_id)))))) WITH '
 'CHECK ((category_access(tenant_id, category_id) AND (EXISTS ( SELECT 1\n'
 '   FROM products p\n'
 '  WHERE ((p.tenant_id = change_completion_records.tenant_id) AND (p.category_id = '
 'change_completion_records.category_id) AND (p.id = change_completion_records.product_id))))))',
 'ALTER TABLE public.change_completion_records ENABLE ROW LEVEL SECURITY',
 'ALTER TABLE public.change_completion_records FORCE ROW LEVEL SECURITY',
 'REVOKE ALL ON public.change_completion_records FROM '
 'PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT SELECT,INSERT ON public.change_completion_records TO pdos_next_app',
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
 "    OR (parent.request_snapshot->'scope'->>'tenant_id')::uuid IS DISTINCT FROM parent.tenant_id\n"
 "    OR (parent.request_snapshot->'scope'->>'product_id')::uuid IS DISTINCT FROM parent.product_id\n"
 "    OR (parent.request_snapshot->'scope'->>'project_id')::uuid IS DISTINCT FROM parent.project_id\n"
 "    OR (parent.request_snapshot - ARRAY['revision','status','history','orders']) IS DISTINCT FROM "
 "(previous.request_snapshot - ARRAY['revision','status','history','orders'])\n"
 "    OR jsonb_array_length(parent.request_snapshot->'history') <> "
 "jsonb_array_length(previous.request_snapshot->'history')+1\n"
 "    OR ((parent.request_snapshot->'history') - "
 "(jsonb_array_length(parent.request_snapshot->'history')-1)) IS DISTINCT FROM "
 "(previous.request_snapshot->'history')\n"
 "    OR (parent.request_snapshot->'history'->-1->>'command_id')::uuid IS DISTINCT FROM "
 'NEW.command_id\n'
 "    OR (parent.request_snapshot->'history'->-1->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 "    OR (parent.request_snapshot->'history'->-1->>'operation') IS DISTINCT FROM NEW.operation\n"
 "    THEN RAISE EXCEPTION 'change atom parent mismatch' USING ERRCODE='23514'; END IF;\n"
 '  expected_tier := CASE WHEN NEW.operation IN '
 "('change.order.approve','change.verification.record','change.close') THEN 'T2' ELSE 'T1' END;\n"
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
 '  proposed := jsonb_set(parent.request_snapshot,\'{history,-1,at}\',\'"server_on_save"\'::jsonb);\n'
 "  IF NEW.operation='change.order.approve' THEN\n"
 '    proposed := jsonb_set(proposed,\'{orders,-1,approvals,-1,at}\',\'"server_on_save"\'::jsonb);\n'
 '    proposed := '
 'jsonb_set(proposed,\'{orders,-1,approvals,-1,decision_id}\',\'"actual_consumed_named_proof_on_save"\'::jsonb);\n'
 '  END IF;\n'
 "  IF NEW.operation='change.verification.record' THEN\n"
 '    proposed=jsonb_set(proposed,\'{orders,-1,verifications,-1,at}\',\'"server_on_save"\'::jsonb);\n'
 '    '
 'proposed=jsonb_set(proposed,\'{orders,-1,verifications,-1,decision_id}\',\'"actual_consumed_named_proof_on_save"\'::jsonb);\n'
 "  ELSIF NEW.operation='change.close' THEN\n"
 '    proposed=jsonb_set(proposed,\'{orders,-1,closure,at}\',\'"server_on_save"\'::jsonb);\n'
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
 "    THEN RAISE EXCEPTION 'change review correspondence mismatch' USING ERRCODE='23514'; END IF;\n"
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
 "    WHEN 'change.order.approve' THEN 'change.approved' WHEN 'change.effectivity.record' THEN "
 "'change.effectivity_recorded' WHEN 'change.verification.record' THEN 'change.verification_recorded' "
 "WHEN 'change.close' THEN 'change.closed' ELSE 'change.implementation_recorded' END;\n"
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
 '      AND o.type=effect AND o.actor_id=receipt.actor_id AND o.correlation_id=receipt.command_id\n'
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
 "    IF ((order_body->'approvals') - (jsonb_array_length(order_body->'approvals')-1)) IS DISTINCT "
 "FROM (previous.request_snapshot->'orders'->-1->'approvals')\n"
 "      OR (order_body - 'approvals') IS DISTINCT FROM ((previous.request_snapshot->'orders'->-1) - "
 "'approvals')\n"
 "      OR previous.status <> 'review' OR parent.status NOT IN ('review','approved')\n"
 "      OR (previous.request_snapshot->>'requester_id')::uuid = NEW.actor_id\n"
 "      OR (order_body->'approvals'->-1) IS DISTINCT FROM (atom->'approval_snapshot')\n"
 "      OR (atom->'approval_snapshot'->>'decision_id')::uuid IS DISTINCT FROM NEW.shared_proof_id\n"
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
 "  ELSIF NEW.operation IN ('change.effectivity.record','change.verification.record','change.close') "
 'THEN\n'
 "    IF (order_body - ARRAY['effectivity','verifications','closure']) IS DISTINCT FROM\n"
 "       ((previous.request_snapshot->'orders'->-1) - ARRAY['effectivity','verifications','closure'])\n"
 "      OR (atom->'fact_snapshot'->>'id')::uuid IS DISTINCT FROM (atom->>'fact_id')::uuid\n"
 "      OR atom->'owner_basis' IS DISTINCT FROM parent.source_basis->'completion'->(atom->>'fact_id')\n"
 "      OR (atom->'native_input'->>'change_id')::uuid IS DISTINCT FROM parent.change_id\n"
 "      OR atom->'native_input'->>'visibility' IS DISTINCT FROM parent.visibility\n"
 "      THEN RAISE EXCEPTION 'native completion binding mismatch' USING ERRCODE='23514'; END IF;\n"
 "    IF NEW.operation='change.effectivity.record' THEN\n"
 "      IF previous.status NOT IN ('implementing','verifying') OR parent.status NOT IN "
 "('implementing','verifying')\n"
 "        OR ((order_body->'effectivity') - (jsonb_array_length(order_body->'effectivity')-1)) IS "
 "DISTINCT FROM previous.request_snapshot->'orders'->-1->'effectivity'\n"
 "        OR order_body->'effectivity'->-1 IS DISTINCT FROM atom->'fact_snapshot'\n"
 "        OR order_body->'verifications' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'verifications'\n"
 "        OR order_body->'closure' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'closure'\n"
 "        OR (atom->'fact_snapshot'->>'item_id')::uuid IS DISTINCT FROM (atom->>'item_id')::uuid\n"
 "        OR (atom->'native_input'->>'item_id')::uuid IS DISTINCT FROM (atom->>'item_id')::uuid\n"
 "        OR atom->'native_input' IS DISTINCT FROM NEW.input_snapshot->'semantic'\n"
 "        OR atom->'fact_snapshot'->>'stage' IS DISTINCT FROM 'effective'\n"
 "        OR atom->'fact_snapshot'->>'outcome' IS DISTINCT FROM 'succeeded'\n"
 "        OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(order_body->'implementations') impl\n"
 "          WHERE impl->>'item_id'=atom->>'item_id' AND impl->>'outcome'='succeeded'\n"
 "            AND impl->'outputs'=atom->'fact_snapshot'->'output_refs'\n"
 "            AND (impl->>'occurred_at')::timestamptz <= "
 "(atom->'fact_snapshot'->>'occurred_at')::timestamptz)\n"
 '        OR NOT EXISTS(SELECT 1 FROM build_lots lot JOIN builds b ON b.tenant_id=lot.tenant_id AND '
 'b.product_id=lot.product_id AND b.id=lot.build_id\n'
 '          WHERE lot.tenant_id=NEW.tenant_id AND lot.product_id=NEW.product_id AND '
 'lot.project_id=NEW.project_id\n'
 "            AND lot.id=(atom#>>'{native_input,lot,id}')::uuid AND "
 "lot.revision=(atom#>>'{native_input,lot,revision}')::integer\n"
 "            AND lot.occurred_at=(atom->'fact_snapshot'->>'occurred_at')::timestamptz\n"
 "            AND lot.received_at=(atom->'fact_snapshot'->>'received_at')::timestamptz)\n"
 "        THEN RAISE EXCEPTION 'native adoption must append its actual implemented Lot event' USING "
 "ERRCODE='23514'; END IF;\n"
 "    ELSIF NEW.operation='change.verification.record' THEN\n"
 "      IF previous.status<>'verifying' OR parent.status<>'verifying'\n"
 "        OR ((order_body->'verifications') - (jsonb_array_length(order_body->'verifications')-1)) IS "
 "DISTINCT FROM previous.request_snapshot->'orders'->-1->'verifications'\n"
 "        OR order_body->'verifications'->-1->'fact' IS DISTINCT FROM atom->'fact_snapshot'\n"
 "        OR (order_body->'verifications'->-1->>'decision_id')::uuid IS DISTINCT FROM "
 'NEW.shared_proof_id\n'
 "        OR (order_body->'verifications'->-1->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 "        OR (atom->'fact_snapshot'->>'verifier_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 "        OR atom->'native_input' IS DISTINCT FROM NEW.input_snapshot->'semantic'\n"
 "        OR order_body->'effectivity' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'effectivity'\n"
 "        OR order_body->'closure' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'closure'\n"
 "        OR atom->'fact_snapshot'->>'content_digest' IS DISTINCT FROM order_body->>'content_digest'\n"
 "        OR atom->'fact_snapshot'->'current' IS DISTINCT FROM 'true'::jsonb\n"
 "        OR atom->'fact_snapshot'->'applicable' IS DISTINCT FROM 'true'::jsonb\n"
 "        OR atom->'fact_snapshot'->>'result' NOT IN ('pass','fail')\n"
 "        OR NEW.actor_id=(previous.request_snapshot->>'requester_id')::uuid\n"
 "        OR EXISTS(SELECT 1 FROM jsonb_array_elements(order_body->'approvals') a WHERE "
 "(a->>'actor_id')::uuid=NEW.actor_id)\n"
 "        OR EXISTS(SELECT 1 FROM jsonb_array_elements(order_body->'implementations') i WHERE "
 "(i->>'executor_id')::uuid=NEW.actor_id)\n"
 "        OR atom->'fact_snapshot'->'executor_ids' @> jsonb_build_array(NEW.actor_id)\n"
 "        OR (atom->'fact_snapshot'->>'observed_from')::timestamptz < (SELECT "
 "max((f->>'occurred_at')::timestamptz) FROM jsonb_array_elements(order_body->'effectivity') f WHERE "
 "f->>'stage'='effective' AND f->>'outcome'='succeeded')\n"
 "        OR (atom->'fact_snapshot'->>'observed_until')::timestamptz > NEW.created_at\n"
 "        THEN RAISE EXCEPTION 'native verification requires its independent named T2 and exact fact' "
 "USING ERRCODE='23514'; END IF;\n"
 '    ELSE\n'
 "      IF previous.status<>'verifying' OR parent.status<>'closed'\n"
 "        OR order_body->'verifications' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'verifications'\n"
 "        OR order_body->'effectivity' IS DISTINCT FROM "
 "previous.request_snapshot->'orders'->-1->'effectivity'\n"
 "        OR order_body->'closure' IS NULL OR order_body->'closure'='null'::jsonb\n"
 "        OR previous.request_snapshot->'orders'->-1->'closure' IS DISTINCT FROM 'null'::jsonb\n"
 "        OR (order_body->'closure'->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 "        OR (atom->'fact_snapshot'->>'verifier_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 "        OR order_body->'verifications'->-1->'fact' IS DISTINCT FROM atom->'fact_snapshot'\n"
 "        OR atom->'fact_snapshot'->>'result' IS DISTINCT FROM 'pass'\n"
 "        THEN RAISE EXCEPTION 'native closure requires a separate named T2 after independent pass' "
 "USING ERRCODE='23514'; END IF;\n"
 '    END IF;\n'
 '  ELSE\n'
 "    IF ((order_body->'implementations') - (jsonb_array_length(order_body->'implementations')-1)) IS "
 "DISTINCT FROM (previous.request_snapshot->'orders'->-1->'implementations')\n"
 "      OR (order_body - 'implementations') IS DISTINCT FROM "
 "((previous.request_snapshot->'orders'->-1) - 'implementations')\n"
 "      OR previous.status NOT IN ('approved','implementing') OR parent.status <> 'implementing'\n"
 "      OR (order_body->'implementations'->-1) IS DISTINCT FROM (atom->'fact_snapshot')\n"
 "      OR (atom->'fact_snapshot'->>'executor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 '      OR NOT EXISTS(SELECT 1 FROM change_implementation_captures c WHERE c.tenant_id=NEW.tenant_id\n'
 '        AND c.product_id=NEW.product_id AND c.project_id=NEW.project_id AND '
 'c.change_id=NEW.change_id\n'
 "        AND c.id=(atom->>'capture_id')::uuid AND c.fact_id=(atom->>'fact_id')::uuid\n"
 "        AND c.fact_snapshot=(atom->'fact_snapshot') AND c.output_basis=(atom->'output_basis'))\n"
 '      OR NOT (order_body->\'required_disciplines\' @> \'["engineering","manufacturing"]\'::jsonb)\n'
 "      THEN RAISE EXCEPTION 'implementation material mismatch' USING ERRCODE='23514'; END IF;\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_order_parent_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE count_atoms integer;\n'
 'BEGIN\n'
 '  IF NEW.operation NOT IN '
 "('change.order.prepare','change.order.approve','change.implementation.record','change.effectivity.record','change.verification.record','change.close') "
 'THEN RETURN NULL; END IF;\n'
 '  SELECT count(*) INTO count_atoms FROM (\n'
 '    SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_order_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_approval_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_implementation_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_completion_records\n'
 '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND atoms.product_id=NEW.product_id\n'
 '    AND atoms.change_version_id=NEW.id AND atoms.change_revision=NEW.revision AND '
 'atoms.operation=NEW.operation;\n'
 "  IF count_atoms<>1 THEN RAISE EXCEPTION 'missing exact change child atom' USING ERRCODE='23514'; "
 'END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_order_proof_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE count_atoms integer;\n'
 'BEGIN\n'
 '  IF NEW.operation NOT IN '
 "('change.order.prepare','change.order.approve','change.implementation.record','change.effectivity.record','change.verification.record','change.close') "
 'OR NOT NEW.consumed THEN RETURN NULL; END IF;\n'
 '  SELECT count(*) INTO count_atoms FROM (\n'
 '    SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM change_order_records\n'
 '    UNION ALL SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
 'change_approval_records\n'
 '    UNION ALL SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
 'change_implementation_records\n'
 '    UNION ALL SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
 'change_completion_records\n'
 '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND atoms.product_id=NEW.product_id\n'
 '    AND atoms.shared_proof_id=NEW.id AND atoms.actor_id=NEW.actor_id AND '
 'atoms.operation=NEW.operation;\n'
 "  IF count_atoms<>1 THEN RAISE EXCEPTION 'consumed proof missing unique change atom' USING "
 "ERRCODE='23514'; END IF;\n"
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_receipt_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE tab text; n integer;\n'
 'BEGIN\n'
 "  IF NEW.operation IN ('change.policy.import','change.selection.decide') THEN\n"
 "    tab:=CASE NEW.operation WHEN 'change.policy.import' THEN 'controlled_change_policy_facts'\n"
 "      ELSE 'controlled_change_selection_facts' END;\n"
 '    PERFORM assert_controlled_change_atom(tab,NEW.tenant_id,NEW.subject_id);\n'
 '  ELSIF NEW.operation IN '
 "('change.order.prepare','change.order.approve','change.implementation.record','change.effectivity.record','change.verification.record','change.close') "
 'THEN\n'
 '    SELECT count(*) INTO n FROM (\n'
 '      SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_order_records\n'
 '      UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_approval_records\n'
 '      UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_implementation_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_completion_records\n'
 '    ) a WHERE a.tenant_id=NEW.tenant_id AND a.product_id=NEW.product_id\n'
 '      AND a.change_version_id=NEW.subject_id AND a.change_revision=NEW.subject_revision\n'
 '      AND a.operation=NEW.operation;\n'
 "    IF n<>1 OR NEW.subject_type<>'change_request' THEN RAISE EXCEPTION 'receipt has no exact change "
 "atom'; END IF;\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n"
 ' -- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n'
 ' -- content dictionaries are not relational rows, even if an extra key happens\n'
 ' -- to be named source_id or item_id.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'artifact_versions' THEN ARRAY['original_id']\n"
 "  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n"
 "  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n"
 "   'source_proposal_id','source_submission_id']\n"
 "  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_submission_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n"
 "  WHEN 'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
 "  WHEN 'native_pilot_runs' THEN "
 "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY[]::text[]\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
 'THEN\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN\n"
 "    links=array_append(links,(item->>'artifact_id')::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
 "  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 ' END IF;\n'
 " IF table_name='release_packages' THEN\n"
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n"
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='release_policy_facts' THEN\n"
 '  -- These are Closed DTO configuration references fixed by the policy owner.\n'
 "  FOREACH key IN ARRAY ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
 'LOOP\n'
 "   container=payload#>ARRAY['material','subject_config',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- These stored fields are validated Reference containers. Do not feed the\n'
 ' -- whole row or arbitrary content into the canonical Reference parser.\n'
 " IF table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
 "  'category_knowledge_entries','definition_specs']) THEN\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n'
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Match ItemInput.content_schema and category_service._references: only\n'
 ' -- commercial_target, voice, and competitor have nested source contracts.\n'
 " IF table_name='proposal_item_versions' AND payload->>'kind'='commercial_target' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP\n"
 "   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
 '  END LOOP;\n'
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='voice' THEN\n"
 "  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n"
 "    links=links || public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
 '   END LOOP;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='proposal_submissions' THEN\n"
 "  container=payload->'frozen_document';\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,container->key);\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n"
 '   links=links || '
 "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
 '   -- The frozen read projection records actual EvidenceLink provenance here.\n'
 "   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
 '  END LOOP;\n'
 " ELSIF table_name='promotion_proofs' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
 'LOOP\n'
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Exact persisted EvidenceLink targets supplement these immutable versions.\n'
 ' -- Reverted links and withdrawn Claims still retain the original historical\n'
 ' -- dependency; lifecycle cleanup must not erase their audit source.\n'
 " IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN\n"
 "  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n"
 '  SELECT revision INTO referenced_version FROM public.definition_revisions\n'
 "   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id')::uuid;\n"
 ' END IF;\n'
 ' IF referenced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n'
 "  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link\n"
 '   WHERE link.tenant_id=t AND link.category_id=c AND link.target_type=target_kind\n'
 '    AND link.target_id=referenced_target AND link.target_version=referenced_version;\n'
 '  links=links || extra;\n'
 ' END IF;\n'
 ' -- Child source rows point to their parent, whereas dependency traversal needs\n'
 " -- the parent's fixed source children as well. Keep the actual relational edge.\n"
 " IF table_name='definition_revisions' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n"
 '   SELECT id FROM public.definition_sources WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '  ) children;\n'
 '  links=links || extra;\n'
 " ELSIF table_name='proposals' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='proposal_items' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='product_target_segments' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries\n"
 "   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid\n"
 "    AND version=(payload->>'segment_version')::integer;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='parameter_current' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')::uuid\n"
 "    AND version=(payload->>'current_version')::integer;\n"
 '  links=links || extra;\n'
 ' END IF;\n'
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  IF table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
 '  END IF;\n'
 "  IF table_name='work_commitment_versions' THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND "
 "revision=(payload->>'task_revision')::integer;\n"
 '   links=links||extra;\n'
 "  ELSIF table_name='project_status_updates' THEN\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP\n"
 "    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "     WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND "
 "revision=(item->>'revision')::integer;\n"
 '    links=links||extra;\n'
 '   END LOOP;\n'
 '  END IF;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='work_commitment_reviews' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='external_wait_versions' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n"
 "   container=payload#>ARRAY['body',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  container=payload#>'{body,replaces}';\n"
 "  IF container->>'id' IS NOT NULL THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND "
 "revision=(container->>'revision')::integer;\n"
 '   links=links||extra;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='project_risk_followups' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 ' IF table_name IN '
 "('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') "
 'THEN\n'
 '  FOREACH key IN ARRAY '
 "ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN "
 "links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); END IF;\n"
 ' END IF;\n'
 '\n'
 " IF table_name IN ('field_feedback_versions','field_feedback_currents','field_response_records') "
 'THEN\n'
 "  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_version_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturing_configuration','batch'] "
 'LOOP\n'
 "   IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN "
 "links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('change_request_versions','change_graph_captures') THEN\n"
 "  FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) "
 'LOOP\n'
 "   IF container->>'feedback_version_id' IS NOT NULL THEN "
 "links=array_append(links,(container->>'feedback_version_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 ' -- Closed native Field plan and occurrence references, never arbitrary UUID prose.\n'
 " IF table_name='controlled_change_selection_facts' AND payload->>'basis_kind'='field_intent' THEN\n"
 "  IF payload->>'feedback_version_id' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload->>'feedback_version_id')::uuid);\n"
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='change_implementation_captures'\n"
 '  AND '
 "payload#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v1' "
 'THEN\n'
 "  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] LOOP\n"
 "   IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n"
 "    links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='change_completion_records' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['project_id','change_version_id','order_record_id','shared_proof_id'] "
 'LOOP\n'
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  IF payload#>>'{native_input,lot,id}' IS NOT NULL THEN "
 "links=array_append(links,(payload#>>'{native_input,lot,id}')::uuid); END IF;\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{native_input,sample_refs}','[]')) LOOP\n"
 "   links=array_append(links,(item->>'id')::uuid);\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{native_input,mappings}','[]')) LOOP\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM verification_run_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND run_id=(item#>>'{run,id}')::uuid AND "
 "revision=(item#>>'{run,revision}')::integer;\n"
 "   links=links||extra; links=array_append(links,(item->>'sample_id')::uuid);\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'CREATE CONSTRAINT TRIGGER change_completion_atom AFTER INSERT ON public.change_completion_records '
 'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_change_order_atom()',
 'CREATE TRIGGER lifecycle_reference BEFORE INSERT OR DELETE OR UPDATE ON '
 'public.change_completion_records FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()',
 'CREATE TRIGGER retained_record BEFORE DELETE OR UPDATE ON public.change_completion_records FOR EACH '
 'ROW EXECUTE FUNCTION protect_next_snapshot()',
 'CREATE TRIGGER a_bind_category BEFORE INSERT ON public.change_completion_records FOR EACH ROW '
 'EXECUTE FUNCTION bind_model_category()',
 'CREATE TRIGGER a_protect_category BEFORE UPDATE ON public.change_completion_records FOR EACH ROW '
 'EXECUTE FUNCTION protect_category_binding()',
 'CREATE TRIGGER category_lifecycle_clock BEFORE INSERT OR DELETE OR UPDATE ON '
 'public.change_completion_records FOR EACH ROW EXECUTE FUNCTION category_lifecycle_clock()',
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_check',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_check CHECK '
 "((((visibility)::text = ANY ((ARRAY['private'::character varying, 'category'::character varying, "
 "'audience'::character varying])::text[])) AND ((status)::text = ANY ((ARRAY['draft'::character "
 "varying, 'analysis'::character varying, 'review'::character varying, 'approved'::character varying, "
 "'implementing'::character varying, 'verifying'::character varying, 'closed'::character "
 'varying])::text[]))))',
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_operation_check',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_operation_check '
 "CHECK (((operation)::text = ANY ((ARRAY['change.request.create'::character varying, "
 "'change.impact.compute'::character varying, 'change.order.prepare'::character varying, "
 "'change.order.approve'::character varying, 'change.implementation.record'::character varying, "
 "'change.effectivity.record'::character varying, 'change.verification.record'::character varying, "
 "'change.close'::character varying])::text[])))",
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_check3',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_check3 CHECK '
 "((((operation)::text = ANY ((ARRAY['change.order.prepare'::character varying, "
 "'change.order.approve'::character varying, 'change.implementation.record'::character varying, "
 "'change.effectivity.record'::character varying, 'change.verification.record'::character varying, "
 "'change.close'::character varying])::text[])) OR COALESCE(((request_snapshot -> 'orders'::text) = "
 "'[]'::jsonb), false)))")

DOWNGRADE_SQL = ('DO $completion$ BEGIN IF EXISTS(SELECT 1 FROM public.change_completion_records) THEN RAISE EXCEPTION '
 "'native completion history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; "
 '$completion$',
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_check',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_check CHECK '
 "((((visibility)::text = ANY ((ARRAY['private'::character varying, 'category'::character varying, "
 "'audience'::character varying])::text[])) AND ((status)::text = ANY ((ARRAY['draft'::character "
 "varying, 'analysis'::character varying, 'review'::character varying, 'approved'::character varying, "
 "'implementing'::character varying])::text[]))))",
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_operation_check',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_operation_check '
 "CHECK (((operation)::text = ANY ((ARRAY['change.request.create'::character varying, "
 "'change.impact.compute'::character varying, 'change.order.prepare'::character varying, "
 "'change.order.approve'::character varying, 'change.implementation.record'::character "
 'varying])::text[])))',
 'ALTER TABLE public.change_request_versions DROP CONSTRAINT change_request_versions_check3',
 'ALTER TABLE public.change_request_versions ADD CONSTRAINT change_request_versions_check3 CHECK '
 "((((operation)::text = ANY ((ARRAY['change.order.prepare'::character varying, "
 "'change.order.approve'::character varying, 'change.implementation.record'::character "
 "varying])::text[])) OR COALESCE(((request_snapshot -> 'orders'::text) = '[]'::jsonb), false)))",
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
 "    OR (parent.request_snapshot->'scope'->>'tenant_id')::uuid IS DISTINCT FROM parent.tenant_id\n"
 "    OR (parent.request_snapshot->'scope'->>'product_id')::uuid IS DISTINCT FROM parent.product_id\n"
 "    OR (parent.request_snapshot->'scope'->>'project_id')::uuid IS DISTINCT FROM parent.project_id\n"
 "    OR (parent.request_snapshot - ARRAY['revision','status','history','orders']) IS DISTINCT FROM "
 "(previous.request_snapshot - ARRAY['revision','status','history','orders'])\n"
 "    OR jsonb_array_length(parent.request_snapshot->'history') <> "
 "jsonb_array_length(previous.request_snapshot->'history')+1\n"
 "    OR ((parent.request_snapshot->'history') - "
 "(jsonb_array_length(parent.request_snapshot->'history')-1)) IS DISTINCT FROM "
 "(previous.request_snapshot->'history')\n"
 "    OR (parent.request_snapshot->'history'->-1->>'command_id')::uuid IS DISTINCT FROM "
 'NEW.command_id\n'
 "    OR (parent.request_snapshot->'history'->-1->>'actor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
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
 '  proposed := jsonb_set(parent.request_snapshot,\'{history,-1,at}\',\'"server_on_save"\'::jsonb);\n'
 "  IF NEW.operation='change.order.approve' THEN\n"
 '    proposed := jsonb_set(proposed,\'{orders,-1,approvals,-1,at}\',\'"server_on_save"\'::jsonb);\n'
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
 "    THEN RAISE EXCEPTION 'change review correspondence mismatch' USING ERRCODE='23514'; END IF;\n"
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
 "    WHEN 'change.order.approve' THEN 'change.approved' ELSE 'change.implementation_recorded' END;\n"
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
 '      AND o.type=effect AND o.actor_id=receipt.actor_id AND o.correlation_id=receipt.command_id\n'
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
 "    IF ((order_body->'approvals') - (jsonb_array_length(order_body->'approvals')-1)) IS DISTINCT "
 "FROM (previous.request_snapshot->'orders'->-1->'approvals')\n"
 "      OR (order_body - 'approvals') IS DISTINCT FROM ((previous.request_snapshot->'orders'->-1) - "
 "'approvals')\n"
 "      OR previous.status <> 'review' OR parent.status NOT IN ('review','approved')\n"
 "      OR (previous.request_snapshot->>'requester_id')::uuid = NEW.actor_id\n"
 "      OR (order_body->'approvals'->-1) IS DISTINCT FROM (atom->'approval_snapshot')\n"
 "      OR (atom->'approval_snapshot'->>'decision_id')::uuid IS DISTINCT FROM NEW.shared_proof_id\n"
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
 "    IF ((order_body->'implementations') - (jsonb_array_length(order_body->'implementations')-1)) IS "
 "DISTINCT FROM (previous.request_snapshot->'orders'->-1->'implementations')\n"
 "      OR (order_body - 'implementations') IS DISTINCT FROM "
 "((previous.request_snapshot->'orders'->-1) - 'implementations')\n"
 "      OR previous.status NOT IN ('approved','implementing') OR parent.status <> 'implementing'\n"
 "      OR (order_body->'implementations'->-1) IS DISTINCT FROM (atom->'fact_snapshot')\n"
 "      OR (atom->'fact_snapshot'->>'executor_id')::uuid IS DISTINCT FROM NEW.actor_id\n"
 '      OR NOT EXISTS(SELECT 1 FROM change_implementation_captures c WHERE c.tenant_id=NEW.tenant_id\n'
 '        AND c.product_id=NEW.product_id AND c.project_id=NEW.project_id AND '
 'c.change_id=NEW.change_id\n'
 "        AND c.id=(atom->>'capture_id')::uuid AND c.fact_id=(atom->>'fact_id')::uuid\n"
 "        AND c.fact_snapshot=(atom->'fact_snapshot') AND c.output_basis=(atom->'output_basis'))\n"
 '      OR NOT (order_body->\'required_disciplines\' @> \'["engineering","manufacturing"]\'::jsonb)\n'
 "      THEN RAISE EXCEPTION 'implementation material mismatch' USING ERRCODE='23514'; END IF;\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_order_parent_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE count_atoms integer;\n'
 'BEGIN\n'
 '  IF NEW.operation NOT IN '
 "('change.order.prepare','change.order.approve','change.implementation.record') THEN RETURN NULL; END "
 'IF;\n'
 '  SELECT count(*) INTO count_atoms FROM (\n'
 '    SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_order_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_approval_records\n'
 '    UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_implementation_records\n'
 '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND atoms.product_id=NEW.product_id\n'
 '    AND atoms.change_version_id=NEW.id AND atoms.change_revision=NEW.revision AND '
 'atoms.operation=NEW.operation;\n'
 "  IF count_atoms<>1 THEN RAISE EXCEPTION 'missing exact change child atom' USING ERRCODE='23514'; "
 'END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_order_proof_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE count_atoms integer;\n'
 'BEGIN\n'
 '  IF NEW.operation NOT IN '
 "('change.order.prepare','change.order.approve','change.implementation.record') OR NOT NEW.consumed "
 'THEN RETURN NULL; END IF;\n'
 '  SELECT count(*) INTO count_atoms FROM (\n'
 '    SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM change_order_records\n'
 '    UNION ALL SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
 'change_approval_records\n'
 '    UNION ALL SELECT tenant_id,product_id,shared_proof_id,actor_id,operation FROM '
 'change_implementation_records\n'
 '  ) AS atoms WHERE atoms.tenant_id=NEW.tenant_id AND atoms.product_id=NEW.product_id\n'
 '    AND atoms.shared_proof_id=NEW.id AND atoms.actor_id=NEW.actor_id AND '
 'atoms.operation=NEW.operation;\n'
 "  IF count_atoms<>1 THEN RAISE EXCEPTION 'consumed proof missing unique change atom' USING "
 "ERRCODE='23514'; END IF;\n"
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.require_change_receipt_atom()\n'
 ' RETURNS trigger\n'
 ' LANGUAGE plpgsql\n'
 " SET search_path TO 'pg_catalog', 'public'\n"
 'AS $function$\n'
 'DECLARE tab text; n integer;\n'
 'BEGIN\n'
 "  IF NEW.operation IN ('change.policy.import','change.selection.decide') THEN\n"
 "    tab:=CASE NEW.operation WHEN 'change.policy.import' THEN 'controlled_change_policy_facts'\n"
 "      ELSE 'controlled_change_selection_facts' END;\n"
 '    PERFORM assert_controlled_change_atom(tab,NEW.tenant_id,NEW.subject_id);\n'
 '  ELSIF NEW.operation IN '
 "('change.order.prepare','change.order.approve','change.implementation.record') THEN\n"
 '    SELECT count(*) INTO n FROM (\n'
 '      SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_order_records\n'
 '      UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_approval_records\n'
 '      UNION ALL SELECT tenant_id,product_id,change_version_id,change_revision,operation FROM '
 'change_implementation_records\n'
 '    ) a WHERE a.tenant_id=NEW.tenant_id AND a.product_id=NEW.product_id\n'
 '      AND a.change_version_id=NEW.subject_id AND a.change_revision=NEW.subject_revision\n'
 '      AND a.operation=NEW.operation;\n'
 "    IF n<>1 OR NEW.subject_type<>'change_request' THEN RAISE EXCEPTION 'receipt has no exact change "
 "atom'; END IF;\n"
 '  END IF;\n'
 '  RETURN NULL;\n'
 'END $function$\n',
 'CREATE OR REPLACE FUNCTION public.m3_lifecycle_source_links(t uuid, c uuid, table_name text, payload '
 'jsonb)\n'
 ' RETURNS uuid[]\n'
 ' LANGUAGE plpgsql\n'
 ' STABLE SECURITY DEFINER\n'
 " SET search_path TO 'pg_catalog', 'public', 'pg_temp'\n"
 'AS $function$\n'
 "DECLARE links uuid[]='{}'; extra uuid[]; key text; keys text[]; item jsonb; container jsonb;\n"
 ' target_kind text; referenced_target uuid; referenced_version integer;\n'
 'BEGIN\n'
 " IF table_name='agent_runs' THEN RETURN public.kernel_lifecycle_links(table_name,payload); END IF;\n"
 ' -- Only actual top-level relation columns establish raw UUID edges. Arbitrary\n'
 ' -- content dictionaries are not relational rows, even if an extra key happens\n'
 ' -- to be named source_id or item_id.\n'
 ' keys=CASE table_name\n'
 "  WHEN 'artifact_versions' THEN ARRAY['original_id']\n"
 "  WHEN 'claims' THEN ARRAY['artifact_id','snapshot_id']\n"
 "  WHEN 'definition_revisions' THEN ARRAY['derived_from_definition_id','parent_definition_id',\n"
 "   'source_proposal_id','source_submission_id']\n"
 "  WHEN 'definition_sources' THEN ARRAY['artifact_id']\n"
 "  WHEN 'definition_specs' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposals' THEN ARRAY['baseline_definition_id','current_submission_id']\n"
 "  WHEN 'proposal_items' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_item_versions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_revisions' THEN ARRAY['proposal_id']\n"
 "  WHEN 'proposal_sources' THEN ARRAY['source_id']\n"
 "  WHEN 'proposal_submissions' THEN ARRAY[]::text[]\n"
 "  WHEN 'proposal_decisions' THEN ARRAY['submission_id']\n"
 "  WHEN 'project_open_items' THEN ARRAY['source_question_id','source_spec_item_id','g0_decision_id']\n"
 "  WHEN 'category_knowledge_current' THEN ARRAY['current_entry_id']\n"
 "  WHEN 'promotion_proofs' THEN ARRAY['knowledge_entry_id','source_proposal_id']\n"
 "  WHEN 'evidence_links' THEN ARRAY['evidence_id']\n"
 "  WHEN 'claim_withdrawals' THEN ARRAY['claim_id']\n"
 "  WHEN 'manufacturing_baseline_publications' THEN ARRAY['baseline_id','process_id','previous_id']\n"
 "  WHEN 'manufacturing_publication_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'manufacturing_publication_documents' THEN ARRAY['document_id','process_id']\n"
 "  WHEN 'native_pilot_runs' THEN "
 "ARRAY['build_id','lot_id','actual_configuration_id','engineering_configuration_id','process_id','publication_id']\n"
 "  WHEN 'native_pilot_currents' THEN ARRAY['pilot_id','latest_observation_id']\n"
 "  WHEN 'native_pilot_observations' THEN ARRAY['pilot_id','previous_observation_id']\n"
 "  WHEN 'release_packages' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_package_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'release_decisions' THEN ARRAY['package_id']\n"
 "  WHEN 'release_policy_facts' THEN ARRAY['previous_id']\n"
 "  WHEN 'release_policy_currents' THEN ARRAY['fact_id']\n"
 "  WHEN 'external_handoff_authorizations' THEN "
 "ARRAY['package_id','engineering_decision_id','manufacturing_decision_id']\n"
 "  WHEN 'external_delivery_intents' THEN ARRAY['handoff_id']\n"
 "  WHEN 'external_receipts' THEN "
 "ARRAY['handoff_id','intent_id','previous_receipt_id','reconciles_id']\n"
 "  WHEN 'external_handoff_currents' THEN ARRAY['handoff_id','intent_id','latest_receipt_id']\n"
 "  WHEN 'release_exception_decisions' THEN ARRAY['basis_package_id','policy_fact_id','previous_id']\n"
 "  WHEN 'release_exception_currents' THEN ARRAY['basis_package_id','policy_fact_id','decision_id']\n"
 "  WHEN 'work_commitment_reviews' THEN "
 "ARRAY['commitment_id','task_version_id','submission_id','previous_id']\n"
 "  WHEN 'work_commitment_review_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'external_wait_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'external_wait_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_risk_followups' THEN ARRAY['previous_id','risk_id','g0_decision_id']\n"
 "  WHEN 'project_risk_followup_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_task_versions' THEN ARRAY['previous_id']\n"
 "  WHEN 'work_task_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'work_commitment_versions' THEN ARRAY['replaces_id']\n"
 "  WHEN 'work_commitment_currents' THEN ARRAY['version_id']\n"
 "  WHEN 'project_status_updates' THEN ARRAY[]::text[]\n"
 '  ELSE ARRAY[]::text[] END;\n'
 ' FOREACH key IN ARRAY keys LOOP\n'
 '  IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 ' END LOOP;\n'
 " -- Publication's exact saved read set is a validated Artifact relationship.\n"
 ' -- Do not scan its declaration, body, reason or arbitrary JSON UUID values.\n'
 ' IF table_name IN '
 "('manufacturing_baseline_publications','native_pilot_runs','native_pilot_observations','release_packages','release_decisions','release_policy_facts','external_handoff_authorizations','external_receipts','release_exception_decisions') "
 'THEN\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload->'required_source_read_set','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN\n"
 "    links=array_append(links,(item->>'artifact_id')::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('native_pilot_runs','native_pilot_observations') THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,samples}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{material_snapshot,statistics,issues}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  item=payload#>'{material_snapshot,statistics,resource,fact}';\n"
 "  IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 ' END IF;\n'
 " IF table_name='release_packages' THEN\n"
 '  -- FixedObject.ref is a closed, server-resolved version reference, not arbitrary body UUID text.\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload#>'{body,objects}','[]')) LOOP\n"
 "   container=item->'ref';\n"
 '   IF '
 "container->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','manufacturing_publication','test_run','pilot_run','issue','change','exception','artifact','work_instruction','control_plan','build_lot','line'])\n"
 "    AND container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END "
 'IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('external_handoff_authorizations','external_delivery_intents') THEN\n"
 '  -- Only closed, owner-verified mapping and manifest references are source edges.\n'
 "  container=CASE WHEN table_name='external_handoff_authorizations' THEN "
 "payload#>'{body,declaration}' ELSE payload->'body' END;\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'mappings','[]')) LOOP\n"
 '   IF '
 "item->'ref'->>'kind'=ANY(ARRAY['definition','engineering_configuration','process_revision','part','bom_revision','artifact','work_instruction','control_plan'])\n"
 "    AND item->'ref'->>'id' IS NOT NULL THEN links=array_append(links,(item->'ref'->>'id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'manifest','[]')) LOOP\n"
 "   IF item->'artifact'->>'id' IS NOT NULL THEN "
 "links=array_append(links,(item->'artifact'->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='release_policy_facts' THEN\n"
 '  -- These are Closed DTO configuration references fixed by the policy owner.\n'
 "  FOREACH key IN ARRAY ARRAY['definition','engineering_configuration','manufacturing_configuration'] "
 'LOOP\n'
 "   container=payload#>ARRAY['material','subject_config',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- These stored fields are validated Reference containers. Do not feed the\n'
 ' -- whole row or arbitrary content into the canonical Reference parser.\n'
 " IF table_name=ANY(ARRAY['proposals','proposal_item_versions','proposal_submissions',\n"
 "  'category_knowledge_entries','definition_specs']) THEN\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,payload->key);\n'
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Match ItemInput.content_schema and category_service._references: only\n'
 ' -- commercial_target, voice, and competitor have nested source contracts.\n'
 " IF table_name='proposal_item_versions' AND payload->>'kind'='commercial_target' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['target_price','cost','volume'] LOOP\n"
 "   links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->key->'source');\n"
 '  END LOOP;\n'
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='voice' THEN\n"
 "  links=links || public.m3_lifecycle_typed_links(t,c,payload->'content'->'representative_refs');\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'kind'='competitor' THEN\n"
 "  FOREACH key IN ARRAY ARRAY['metrics','features','prices'] LOOP\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'content'->key,'[]')) LOOP\n"
 "    links=links || public.m3_lifecycle_typed_links(t,c,item->'source_ref');\n"
 '   END LOOP;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name='proposal_submissions' THEN\n"
 "  container=payload->'frozen_document';\n"
 '  FOREACH key IN ARRAY '
 "ARRAY['source_refs','direct_source_refs','context_refs','baseline_claim_refs'] LOOP\n"
 '   links=links || public.m3_lifecycle_typed_links(t,c,container->key);\n'
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(container->'items','[]')) LOOP\n"
 '   links=links || '
 "public.m3_lifecycle_source_links(t,c,'proposal_item_versions',item-ARRAY['item_id','proposal_id']);\n"
 '   -- The frozen read projection records actual EvidenceLink provenance here.\n'
 "   links=links || public.m3_lifecycle_typed_links(t,c,item->'evidence_links');\n"
 '  END LOOP;\n'
 " ELSIF table_name='promotion_proofs' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'source_item_refs','[]')) "
 'LOOP\n'
 "   IF item->>'item_id' IS NOT NULL THEN links=array_append(links,(item->>'item_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 ' -- Exact persisted EvidenceLink targets supplement these immutable versions.\n'
 ' -- Reverted links and withdrawn Claims still retain the original historical\n'
 ' -- dependency; lifecycle cleanup must not erase their audit source.\n'
 " IF table_name='proposal_item_versions' AND payload->>'item_id' IS NOT NULL THEN\n"
 "  target_kind='proposal_item'; referenced_target=(payload->>'item_id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='category_knowledge_entries' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='knowledge_entry'; referenced_target=(payload->>'id')::uuid;\n"
 "  referenced_version=(payload->>'version')::integer;\n"
 " ELSIF table_name='definition_specs' AND payload->>'id' IS NOT NULL THEN\n"
 "  target_kind='definition_spec'; referenced_target=(payload->>'id')::uuid;\n"
 '  SELECT revision INTO referenced_version FROM public.definition_revisions\n'
 "   WHERE tenant_id=t AND category_id=c AND id=(payload->>'definition_id')::uuid;\n"
 ' END IF;\n'
 ' IF referenced_target IS NOT NULL AND referenced_version IS NOT NULL THEN\n'
 "  SELECT coalesce(array_agg(link.evidence_id),'{}') INTO extra FROM public.evidence_links link\n"
 '   WHERE link.tenant_id=t AND link.category_id=c AND link.target_type=target_kind\n'
 '    AND link.target_id=referenced_target AND link.target_version=referenced_version;\n'
 '  links=links || extra;\n'
 ' END IF;\n'
 ' -- Child source rows point to their parent, whereas dependency traversal needs\n'
 " -- the parent's fixed source children as well. Keep the actual relational edge.\n"
 " IF table_name='definition_revisions' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM (\n"
 '   SELECT id FROM public.definition_sources WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '   UNION ALL SELECT id FROM public.definition_specs WHERE tenant_id=t AND category_id=c\n'
 "    AND definition_id=(payload->>'id')::uuid\n"
 '  ) children;\n'
 '  links=links || extra;\n'
 " ELSIF table_name='proposals' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND proposal_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='proposal_items' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.proposal_item_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND item_id=(payload->>'id')::uuid;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='product_target_segments' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.category_knowledge_entries\n"
 "   WHERE tenant_id=t AND category_id=c AND lineage_id=(payload->>'segment_lineage_id')::uuid\n"
 "    AND version=(payload->>'segment_version')::integer;\n"
 '  links=links || extra;\n'
 " ELSIF table_name='parameter_current' THEN\n"
 "  SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.parameter_versions\n"
 "   WHERE tenant_id=t AND category_id=c AND parameter_id=(payload->>'parameter_id')::uuid\n"
 "    AND version=(payload->>'current_version')::integer;\n"
 '  links=links || extra;\n'
 ' END IF;\n'
 '\n'
 " IF table_name IN ('work_task_versions','work_commitment_versions','project_status_updates') THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 "  IF table_name='work_task_versions' AND payload#>>'{body,plan_task,id}' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload#>>'{body,plan_task,id}')::uuid);\n"
 '  END IF;\n'
 "  IF table_name='work_commitment_versions' THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND task_id=(payload->>'task_id')::uuid AND "
 "revision=(payload->>'task_revision')::integer;\n"
 '   links=links||extra;\n'
 "  ELSIF table_name='project_status_updates' THEN\n"
 "   FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'task_refs','[]')) LOOP\n"
 "    SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.work_task_versions\n"
 "     WHERE tenant_id=t AND category_id=c AND task_id=(item->>'id')::uuid AND "
 "revision=(item->>'revision')::integer;\n"
 '    links=links||extra;\n'
 '   END LOOP;\n'
 '  END IF;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='work_commitment_reviews' THEN\n"
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 " IF table_name='external_wait_versions' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['milestone','build','calendar'] LOOP\n"
 "   container=payload#>ARRAY['body',key];\n"
 "   IF container->>'id' IS NOT NULL THEN links=array_append(links,(container->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  container=payload#>'{body,replaces}';\n"
 "  IF container->>'id' IS NOT NULL THEN\n"
 "   SELECT coalesce(array_agg(id),'{}') INTO extra FROM public.external_wait_versions\n"
 "    WHERE tenant_id=t AND category_id=c AND wait_id=(container->>'id')::uuid AND "
 "revision=(container->>'revision')::integer;\n"
 '   links=links||extra;\n'
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='project_risk_followups' THEN\n"
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 ' IF table_name IN '
 "('knowledge_candidate_versions','knowledge_candidate_currents','knowledge_applicability_assessments','knowledge_rule_versions','knowledge_rule_currents') "
 'THEN\n'
 '  FOREACH key IN ARRAY '
 "ARRAY['previous_id','version_id','candidate_version_id','assessment_id','publication_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOR item IN SELECT value FROM jsonb_array_elements(coalesce(payload->'reads','[]')) LOOP\n"
 "   IF item->>'artifact_id' IS NOT NULL THEN links=array_append(links,(item->>'artifact_id')::uuid); "
 'END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,professional,fact_refs}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  IF payload#>>'{source_basis,target,id}' IS NOT NULL THEN "
 "links=array_append(links,(payload#>>'{source_basis,target,id}')::uuid); END IF;\n"
 ' END IF;\n'
 '\n'
 " IF table_name IN ('field_feedback_versions','field_feedback_currents','field_response_records') "
 'THEN\n'
 "  FOREACH key IN ARRAY ARRAY['previous_id','version_id','feedback_version_id'] LOOP\n"
 '   IF payload->>key IS NOT NULL THEN links=array_append(links,(payload->>key)::uuid); END IF;\n'
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,artifacts}','[]')) LOOP\n"
 "   IF item->>'id' IS NOT NULL THEN links=array_append(links,(item->>'id')::uuid); END IF;\n"
 '  END LOOP;\n'
 "  FOREACH key IN ARRAY ARRAY['engineering_configuration','manufacturing_configuration','batch'] "
 'LOOP\n'
 "   IF payload#>>ARRAY['body','location',key,'id'] IS NOT NULL THEN "
 "links=array_append(links,(payload#>>ARRAY['body','location',key,'id'])::uuid); END IF;\n"
 '  END LOOP;\n'
 '  FOR item IN SELECT value FROM '
 "jsonb_array_elements(coalesce(payload#>'{source_basis,result_receipts}','[]')) LOOP\n"
 "   IF item->>'receipt_id' IS NOT NULL THEN links=array_append(links,(item->>'receipt_id')::uuid); "
 'END IF;\n'
 "   IF item->>'row_id' IS NOT NULL THEN links=array_append(links,(item->>'row_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 " IF table_name IN ('change_request_versions','change_graph_captures') THEN\n"
 "  FOR container IN SELECT value FROM jsonb_each(coalesce(payload#>'{source_basis,owners}','{}')) "
 'LOOP\n'
 "   IF container->>'feedback_version_id' IS NOT NULL THEN "
 "links=array_append(links,(container->>'feedback_version_id')::uuid); END IF;\n"
 '  END LOOP;\n'
 ' END IF;\n'
 '\n'
 ' -- Closed native Field plan and occurrence references, never arbitrary UUID prose.\n'
 " IF table_name='controlled_change_selection_facts' AND payload->>'basis_kind'='field_intent' THEN\n"
 "  IF payload->>'feedback_version_id' IS NOT NULL THEN\n"
 "   links=array_append(links,(payload->>'feedback_version_id')::uuid);\n"
 '  END IF;\n'
 ' END IF;\n'
 " IF table_name='change_implementation_captures'\n"
 '  AND '
 "payload#>>'{occurrence_snapshot,schema_version}'='pdos-field-change-implementation-occurrence-v1' "
 'THEN\n'
 "  FOREACH key IN ARRAY ARRAY['feedback_version_id','selection_id'] LOOP\n"
 "   IF payload#>>ARRAY['occurrence_snapshot',key] IS NOT NULL THEN\n"
 "    links=array_append(links,(payload#>>ARRAY['occurrence_snapshot',key])::uuid);\n"
 '   END IF;\n'
 '  END LOOP;\n'
 ' END IF;\n'
 ' RETURN links;\n'
 'END;\n'
 '$function$\n',
 'DROP TABLE public.change_completion_records')
