"""Frozen Wave15 DDL and reviewed guards, independent of future model code."""
# ruff: noqa: E501

TABLES = ('change_request_versions',
 'quality_issue_versions',
 'quality_policy_facts',
 'change_graph_captures',
 'change_request_currents',
 'quality_current_issues',
 'quality_current_policies',
 'quality_failure_maps',
 'quality_event_failure_links')

SCHEMA_SQL = ('\n'
 'CREATE TABLE change_request_versions (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tchange_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tprevious_version_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\trequest_snapshot JSONB NOT NULL, \n'
 '\trequest_sha256 VARCHAR(64) NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, change_id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, change_id, id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, change_id, id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, owner_id, operation, intent_digest), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, '
 'id), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, change_id, previous_version_id, '
 'previous_revision) REFERENCES change_request_versions (tenant_id, product_id, project_id, '
 'change_id, id, revision), \n'
 "\tCHECK (visibility IN ('private','product') AND status IN ('draft','analysis')), \n"
 "\tCHECK (operation IN ('change.request.create','change.impact.compute')), \n"
 '\tCHECK ((revision = 1 AND previous_version_id IS NULL AND previous_revision IS NULL) OR '
 '(revision > 1 AND previous_version_id IS NOT NULL AND previous_revision IS NOT NULL AND '
 'previous_version_id <> id AND revision = previous_revision + 1)), \n'
 "\tCHECK (COALESCE(request_snapshot->>'status' = status, false)), \n"
 "\tCHECK (COALESCE(request_snapshot->'orders' = '[]'::jsonb, false)), \n"
 "\tCHECK (COALESCE((request_snapshot->>'revision')::integer = revision, false)), \n"
 '\tCHECK (jsonb_array_length(required_source_read_set) BETWEEN 1 AND 20)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_change_request_versions_tenant_id ON change_request_versions (tenant_id)',
 '\n'
 'CREATE TABLE quality_issue_versions (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tissue_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tprevious_issue_version_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\towner_id UUID NOT NULL, \n'
 '\twriter_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tstatus VARCHAR(32) NOT NULL, \n'
 '\toperation VARCHAR(80) NOT NULL, \n'
 '\tissue_snapshot JSONB NOT NULL, \n'
 '\tsnapshot_sha256 VARCHAR(64) NOT NULL, \n'
 '\tinput_snapshot JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\tpolicy_snapshot JSONB, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tintent_digest VARCHAR(64) NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, '
 'id), \n'
 '\tUNIQUE (tenant_id, product_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, issue_id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, issue_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, issue_id, previous_issue_version_id, '
 'previous_revision) REFERENCES quality_issue_versions (tenant_id, product_id, project_id, '
 'issue_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (revision>0 AND visibility IN ('private','product')), \n"
 "\tCHECK (status IN ('open','triaged','actioning')), \n"
 '\tCHECK (operation IN '
 "('quality.issue.create','quality.issue.merge','quality.issue.triage','quality.issue.containment.record','quality.capa.draft')), \n"
 "\tCHECK (jsonb_typeof(required_source_read_set)='array' AND "
 'jsonb_array_length(required_source_read_set) BETWEEN 1 AND 20), \n'
 '\tCHECK ((revision=1 AND previous_issue_version_id IS NULL AND previous_revision IS NULL) OR '
 '(previous_issue_version_id IS NOT NULL AND previous_revision IS NOT NULL AND '
 'previous_issue_version_id<>id AND revision=previous_revision+1)), \n'
 "\tCHECK (COALESCE(issue_snapshot->>'id'=issue_id::text AND "
 "(issue_snapshot->>'revision')::integer=revision AND issue_snapshot->>'status'=status,false)), \n"
 "\tCHECK (COALESCE(issue_snapshot->'scope'->>'tenant_id'=tenant_id::text AND "
 "issue_snapshot->'scope'->>'product_id'=product_id::text AND "
 "issue_snapshot->'scope'->>'project_id'=project_id::text,false))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_issue_versions_tenant_id ON quality_issue_versions (tenant_id)',
 '\n'
 'CREATE TABLE quality_policy_facts (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tprevious_id UUID, \n'
 '\tprevious_revision INTEGER, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\trisk VARCHAR(16) NOT NULL, \n'
 '\tindependent_verification BOOLEAN NOT NULL, \n'
 '\tvalid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tvalid_until TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tissuer_key VARCHAR(100) NOT NULL, \n'
 '\tissuer_version VARCHAR(100) NOT NULL, \n'
 '\tissuer_epoch INTEGER NOT NULL, \n'
 '\tnature VARCHAR(16) NOT NULL, \n'
 '\texternal_id VARCHAR(200) NOT NULL, \n'
 '\tdata JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tfact_sha256 VARCHAR(64) NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, '
 'id), \n'
 '\tUNIQUE (tenant_id, product_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, purpose, series_id, id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, purpose, series_id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, purpose, series_id, previous_id, '
 'previous_revision) REFERENCES quality_policy_facts (tenant_id, product_id, project_id, purpose, '
 'series_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (nature='synthetic' AND status IN ('active','withdrawn') AND risk IN "
 "('low','medium','high','critical')), \n"
 '\tCHECK (revision>0 AND issuer_epoch>0 AND valid_until>valid_from AND visibility IN '
 "('private','product')), \n"
 '\tCHECK ((revision=1 AND previous_id IS NULL AND previous_revision IS NULL AND series_id=id) OR '
 '(previous_id IS NOT NULL AND previous_revision IS NOT NULL AND previous_id<>id AND '
 'revision=previous_revision+1)), \n'
 "\tCHECK (jsonb_typeof(required_source_read_set)='array' AND "
 'jsonb_array_length(required_source_read_set) BETWEEN 1 AND 20)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_policy_facts_tenant_id ON quality_policy_facts (tenant_id)',
 '\n'
 'CREATE TABLE change_graph_captures (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tchange_id UUID NOT NULL, \n'
 '\tchange_version_id UUID NOT NULL, \n'
 '\tchange_revision INTEGER NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\towner_id UUID NOT NULL, \n'
 '\tvisibility VARCHAR(16) NOT NULL, \n'
 '\tstatus VARCHAR(16) NOT NULL, \n'
 '\tcapture_key VARCHAR(160) NOT NULL, \n'
 '\tinput_digest VARCHAR(64) NOT NULL, \n'
 '\tgraph_snapshot JSONB NOT NULL, \n'
 '\tgraph_sha256 VARCHAR(64) NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tauthority_snapshot JSONB NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\treason TEXT NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, id), \n'
 '\tUNIQUE (tenant_id, product_id, id, revision), \n'
 '\tUNIQUE (tenant_id, product_id, owner_id, capture_key), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, change_id, change_version_id, change_revision) '
 'REFERENCES change_request_versions (tenant_id, product_id, project_id, change_id, id, '
 'revision), \n'
 '\tFOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), \n'
 "\tCHECK (revision = 1 AND status = 'prepared' AND change_revision > 0), \n"
 "\tCHECK (visibility IN ('private','product')), \n"
 "\tCHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'), \n"
 "\tCHECK (COALESCE(graph_snapshot->>'nature' IN ('real','synthetic'), false)), \n"
 '\tCHECK (jsonb_array_length(required_source_read_set) BETWEEN 1 AND 20)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_change_graph_captures_tenant_id ON change_graph_captures (tenant_id)',
 '\n'
 'CREATE TABLE change_request_currents (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tchange_id UUID NOT NULL, \n'
 '\tversion_id UUID NOT NULL, \n'
 '\trevision INTEGER NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, change_id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, change_id, version_id, revision) REFERENCES '
 'change_request_versions (tenant_id, product_id, change_id, id, revision), \n'
 '\tCHECK (revision > 0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_change_request_currents_tenant_id ON change_request_currents (tenant_id)',
 '\n'
 'CREATE TABLE quality_current_issues (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tissue_id UUID NOT NULL, \n'
 '\tissue_version_id UUID NOT NULL, \n'
 '\tissue_revision INTEGER NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, issue_id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, issue_id, issue_version_id, issue_revision) '
 'REFERENCES quality_issue_versions (tenant_id, product_id, project_id, issue_id, id, revision), \n'
 '\tCHECK (issue_revision>0 AND epoch>0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_current_issues_tenant_id ON quality_current_issues (tenant_id)',
 '\n'
 'CREATE TABLE quality_current_policies (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tpurpose TEXT NOT NULL, \n'
 '\tseries_id UUID NOT NULL, \n'
 '\tfact_id UUID NOT NULL, \n'
 '\tfact_revision INTEGER NOT NULL, \n'
 '\tissuer_key VARCHAR(100) NOT NULL, \n'
 '\texternal_id VARCHAR(200) NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, purpose, issuer_key, external_id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, purpose, series_id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, purpose, series_id, fact_id, fact_revision) '
 'REFERENCES quality_policy_facts (tenant_id, product_id, project_id, purpose, series_id, id, '
 'revision), \n'
 '\tCHECK (epoch>0 AND fact_revision>0)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_current_policies_tenant_id ON quality_current_policies (tenant_id)',
 '\n'
 'CREATE TABLE quality_failure_maps (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tfailure_identity VARCHAR(64) NOT NULL, \n'
 '\tissue_id UUID NOT NULL, \n'
 '\tepoch INTEGER NOT NULL, \n'
 '\tfailure JSONB NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, failure_identity), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, issue_id) REFERENCES quality_current_issues '
 '(tenant_id, product_id, project_id, issue_id) DEFERRABLE INITIALLY DEFERRED, \n'
 '\tCHECK (epoch>0 AND length(failure_identity)=64), \n'
 "\tCHECK (COALESCE(failure->>'identity'=failure_identity AND "
 "failure->'build'->>'product_id'=product_id::text AND "
 "failure->'build'->>'project_id'=project_id::text,false))\n"
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_failure_maps_tenant_id ON quality_failure_maps (tenant_id)',
 '\n'
 'CREATE TABLE quality_event_failure_links (\n'
 '\tproduct_id UUID NOT NULL, \n'
 '\tproject_id UUID NOT NULL, \n'
 '\tissue_id UUID NOT NULL, \n'
 '\tissue_version_id UUID NOT NULL, \n'
 '\tissue_revision INTEGER NOT NULL, \n'
 '\tevent_id UUID NOT NULL, \n'
 '\tfailure_identity VARCHAR(64) NOT NULL, \n'
 '\tbuild_id UUID NOT NULL, \n'
 '\trequest_id UUID NOT NULL, \n'
 '\trun_id UUID NOT NULL, \n'
 '\trun_version_id UUID NOT NULL, \n'
 '\trun_revision INTEGER NOT NULL, \n'
 '\tmeasurement_id UUID NOT NULL, \n'
 '\tmeasurement_revision INTEGER NOT NULL, \n'
 '\tprojection_id UUID NOT NULL, \n'
 '\tprojection_revision INTEGER NOT NULL, \n'
 '\tbasis_sha256 VARCHAR(64) NOT NULL, \n'
 '\tfailure JSONB NOT NULL, \n'
 '\tsources JSONB NOT NULL, \n'
 '\trequired_source_read_set JSONB NOT NULL, \n'
 '\tsource_basis JSONB NOT NULL, \n'
 '\tid UUID NOT NULL, \n'
 '\ttenant_id UUID NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tUNIQUE (tenant_id, product_id, project_id, event_id, failure_identity), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, issue_id, issue_version_id, issue_revision) '
 'REFERENCES quality_issue_versions (tenant_id, product_id, project_id, issue_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, build_id, run_id) REFERENCES '
 'verification_run_identities (tenant_id, product_id, project_id, build_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, request_id, run_id, run_version_id, '
 'run_revision) REFERENCES verification_run_versions (tenant_id, product_id, project_id, '
 'request_id, run_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, request_id, run_id, measurement_id, '
 'measurement_revision) REFERENCES test_measurements (tenant_id, product_id, project_id, '
 'request_id, run_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, product_id, project_id, request_id, run_id, projection_id, '
 'projection_revision) REFERENCES test_result_projections (tenant_id, product_id, project_id, '
 'request_id, run_id, id, revision), \n'
 '\tFOREIGN KEY(tenant_id, event_id) REFERENCES outbox_events (tenant_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, measurement_id) REFERENCES test_measurements (tenant_id, '
 'product_id, id), \n'
 '\tFOREIGN KEY(tenant_id, product_id, projection_id) REFERENCES test_result_projections '
 '(tenant_id, product_id, id), \n'
 '\tCHECK (run_revision>2 AND issue_revision>0 AND projection_revision>0), \n'
 '\tCHECK (measurement_revision=1), \n'
 "\tCHECK (COALESCE(failure->>'identity'=failure_identity AND failure->'run'->>'id'=run_id::text "
 "AND (failure->'run'->>'revision')::integer=run_revision AND "
 "failure->>'measurement_id'=measurement_id::text AND failure->'build'->>'id'=build_id::text AND "
 "failure->'build'->>'product_id'=product_id::text AND "
 "failure->'build'->>'project_id'=project_id::text,false)), \n"
 "\tCHECK (jsonb_typeof(required_source_read_set)='array' AND "
 'jsonb_array_length(required_source_read_set) BETWEEN 1 AND 20)\n'
 ')\n'
 '\n',
 'CREATE INDEX ix_quality_event_failure_links_tenant_id ON quality_event_failure_links (tenant_id)')

FUNCTIONS = {'assert_quality_change_receipt': '\n'
                                  'CREATE FUNCTION assert_quality_change_receipt(tid uuid, pid '
                                  'uuid, sid uuid, rev integer,\n'
                                  '  op_name text, subject_name text, actor uuid, audience text) '
                                  'RETURNS void LANGUAGE plpgsql AS $$\n'
                                  'DECLARE receipt action_receipts%ROWTYPE; expected_event text;\n'
                                  'BEGIN\n'
                                  '  SELECT * INTO receipt FROM action_receipts WHERE '
                                  'tenant_id=tid AND product_id=pid\n'
                                  '    AND subject_id=sid AND subject_revision=rev AND '
                                  'operation=op_name\n'
                                  '    AND subject_type=subject_name AND actor_id=actor AND '
                                  'requester_id=actor AND run_id IS NULL\n'
                                  '    AND visibility=audience;\n'
                                  '  expected_event := CASE op_name\n'
                                  "    WHEN 'quality.issue.create' THEN 'issue.created'\n"
                                  "    WHEN 'quality.issue.merge' THEN 'issues.merged'\n"
                                  "    WHEN 'quality.issue.triage' THEN 'issue.triaged'\n"
                                  "    WHEN 'quality.issue.containment.record' THEN "
                                  "'issue.contained'\n"
                                  "    WHEN 'quality.capa.draft' THEN 'capa.drafted'\n"
                                  "    WHEN 'quality.policy.import' THEN "
                                  "'quality.policy_imported'\n"
                                  "    WHEN 'change.request.create' THEN 'change.requested'\n"
                                  "    WHEN 'change.impact.compute' THEN 'change.impact_created' "
                                  'END;\n'
                                  '  IF receipt.id IS NULL OR expected_event IS NULL\n'
                                  '    OR (SELECT count(*) FROM action_receipts WHERE '
                                  'tenant_id=tid AND product_id=pid\n'
                                  '      AND subject_id=sid AND subject_revision=rev AND '
                                  'operation=op_name)<>1\n'
                                  '    OR (SELECT count(*) FROM audit_entries WHERE tenant_id=tid '
                                  'AND receipt_id=receipt.id)<>1\n'
                                  '    OR NOT EXISTS (SELECT 1 FROM audit_entries WHERE '
                                  'tenant_id=tid AND receipt_id=receipt.id\n'
                                  '      AND actor_id=actor AND operation=op_name)\n'
                                  '    OR (SELECT count(*) FROM outbox_events WHERE tenant_id=tid '
                                  'AND receipt_id=receipt.id)<>1\n'
                                  '    OR NOT EXISTS (SELECT 1 FROM outbox_events WHERE '
                                  'tenant_id=tid AND receipt_id=receipt.id\n'
                                  '      AND type=expected_event AND actor_id=actor AND '
                                  'subject_id=sid AND subject_revision=rev\n'
                                  '      AND correlation_id=receipt.command_id AND '
                                  'schema_version=1) THEN\n'
                                  "    RAISE EXCEPTION 'Quality/change write requires exactly one "
                                  "named receipt, audit and event';\n"
                                  '  END IF;\n'
                                  'END $$;\n',
 'protect_quality_current': '\n'
                            'CREATE FUNCTION protect_quality_current() RETURNS trigger LANGUAGE '
                            'plpgsql AS $$\n'
                            'DECLARE target quality_issue_versions%ROWTYPE;\n'
                            'BEGIN\n'
                            "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Issue identity pointer "
                            "cannot be deleted'; END IF;\n"
                            '  SELECT * INTO target FROM quality_issue_versions WHERE '
                            'tenant_id=NEW.tenant_id\n'
                            '    AND id=NEW.issue_version_id;\n'
                            '  IF target.id IS NULL OR '
                            'ROW(target.product_id,target.project_id,target.issue_id,target.revision)\n'
                            '    IS DISTINCT FROM '
                            'ROW(NEW.product_id,NEW.project_id,NEW.issue_id,NEW.issue_revision) '
                            'THEN\n'
                            "    RAISE EXCEPTION 'Issue current requires its exact scoped "
                            "version'; END IF;\n"
                            "  IF TG_OP='INSERT' THEN\n"
                            '    IF NEW.issue_revision<>1 OR NEW.epoch<>1 THEN\n'
                            "      RAISE EXCEPTION 'Issue identity starts only at revision and "
                            "epoch one'; END IF;\n"
                            '  ELSE\n'
                            '    IF '
                            'ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.issue_id,NEW.created_at)\n'
                            '      IS DISTINCT FROM '
                            'ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.issue_id,OLD.created_at)\n'
                            '      OR NEW.issue_revision<>OLD.issue_revision+1 OR '
                            'NEW.epoch<>OLD.epoch+1\n'
                            '      OR target.previous_issue_version_id IS DISTINCT FROM '
                            'OLD.issue_version_id\n'
                            '      OR target.previous_revision IS DISTINCT FROM OLD.issue_revision '
                            'THEN\n'
                            "      RAISE EXCEPTION 'Issue current requires a continuous exact "
                            "predecessor'; END IF;\n"
                            '  END IF;\n'
                            '  RETURN NEW;\n'
                            'END $$;\n',
 'protect_quality_policy_current': '\n'
                                   'CREATE FUNCTION protect_quality_policy_current() RETURNS '
                                   'trigger LANGUAGE plpgsql AS $$\n'
                                   'DECLARE target quality_policy_facts%ROWTYPE;\n'
                                   'BEGIN\n'
                                   "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Policy series "
                                   "pointer cannot be deleted'; END IF;\n"
                                   '  SELECT * INTO target FROM quality_policy_facts WHERE '
                                   'tenant_id=NEW.tenant_id AND id=NEW.fact_id;\n'
                                   '  IF target.id IS NULL OR '
                                   'ROW(target.product_id,target.project_id,target.purpose,target.series_id,\n'
                                   '    target.revision,target.issuer_key,target.external_id) IS '
                                   'DISTINCT FROM\n'
                                   '    '
                                   'ROW(NEW.product_id,NEW.project_id,NEW.purpose,NEW.series_id,NEW.fact_revision,\n'
                                   '      NEW.issuer_key,NEW.external_id) THEN\n'
                                   "    RAISE EXCEPTION 'Policy current requires its exact scoped "
                                   "fact'; END IF;\n"
                                   "  IF TG_OP='INSERT' THEN\n"
                                   '    IF NEW.fact_revision<>1 OR NEW.epoch<>1 THEN\n'
                                   "      RAISE EXCEPTION 'Policy series starts at revision and "
                                   "epoch one'; END IF;\n"
                                   '  ELSE\n'
                                   '    IF '
                                   'ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.purpose,NEW.series_id,\n'
                                   '      NEW.issuer_key,NEW.external_id,NEW.created_at) IS '
                                   'DISTINCT FROM\n'
                                   '      '
                                   'ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.purpose,OLD.series_id,\n'
                                   '        OLD.issuer_key,OLD.external_id,OLD.created_at)\n'
                                   '      OR NEW.fact_revision<>OLD.fact_revision+1 OR '
                                   'NEW.epoch<>OLD.epoch+1\n'
                                   '      OR target.previous_id IS DISTINCT FROM OLD.fact_id\n'
                                   '      OR target.previous_revision IS DISTINCT FROM '
                                   'OLD.fact_revision THEN\n'
                                   "      RAISE EXCEPTION 'Policy pointer requires a continuous "
                                   "exact predecessor'; END IF;\n"
                                   '  END IF;\n'
                                   '  RETURN NEW;\n'
                                   'END $$;\n',
 'protect_change_current': '\n'
                           'CREATE FUNCTION protect_change_current() RETURNS trigger LANGUAGE '
                           'plpgsql AS $$\n'
                           'DECLARE target change_request_versions%ROWTYPE;\n'
                           'BEGIN\n'
                           "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Change pointer cannot be "
                           "deleted'; END IF;\n"
                           '  SELECT * INTO target FROM change_request_versions WHERE '
                           'tenant_id=NEW.tenant_id AND id=NEW.version_id;\n'
                           '  IF target.id IS NULL OR '
                           'ROW(target.product_id,target.change_id,target.revision)\n'
                           '    IS DISTINCT FROM ROW(NEW.product_id,NEW.change_id,NEW.revision) '
                           'THEN\n'
                           "    RAISE EXCEPTION 'Change current requires its exact scoped "
                           "version'; END IF;\n"
                           "  IF TG_OP='INSERT' THEN\n"
                           "    IF NEW.revision<>1 THEN RAISE EXCEPTION 'Change starts at revision "
                           "one'; END IF;\n"
                           '  ELSE\n'
                           '    IF '
                           'ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.change_id,NEW.created_at)\n'
                           '      IS DISTINCT FROM '
                           'ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.change_id,OLD.created_at)\n'
                           '      OR NEW.revision<>OLD.revision+1 OR target.previous_version_id IS '
                           'DISTINCT FROM OLD.version_id\n'
                           '      OR target.previous_revision IS DISTINCT FROM OLD.revision THEN\n'
                           "      RAISE EXCEPTION 'Change pointer requires a continuous exact "
                           "predecessor'; END IF;\n"
                           '  END IF;\n'
                           '  RETURN NEW;\n'
                           'END $$;\n',
 'protect_quality_failure_alias': '\n'
                                  'CREATE FUNCTION protect_quality_failure_alias() RETURNS trigger '
                                  'LANGUAGE plpgsql AS $$\n'
                                  'DECLARE target quality_issue_versions%ROWTYPE; source '
                                  'quality_issue_versions%ROWTYPE;\n'
                                  'BEGIN\n'
                                  "  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Failure identity "
                                  "cannot be deleted'; END IF;\n"
                                  '  SELECT v.* INTO target FROM quality_current_issues c JOIN '
                                  'quality_issue_versions v\n'
                                  '    ON v.tenant_id=c.tenant_id AND v.id=c.issue_version_id\n'
                                  '    WHERE c.tenant_id=NEW.tenant_id AND '
                                  'c.product_id=NEW.product_id\n'
                                  '      AND c.project_id=NEW.project_id AND '
                                  'c.issue_id=NEW.issue_id;\n'
                                  '  IF target.id IS NULL OR NOT EXISTS (SELECT 1 FROM '
                                  "jsonb_array_elements(target.issue_snapshot->'failures') f\n"
                                  '      WHERE f=NEW.failure) THEN\n'
                                  "    RAISE EXCEPTION 'Failure alias requires the exact retained "
                                  "failure in its current Issue'; END IF;\n"
                                  "  IF TG_OP='INSERT' THEN\n"
                                  "    IF NEW.epoch<>1 THEN RAISE EXCEPTION 'Failure identity "
                                  "starts at epoch one'; END IF;\n"
                                  '  ELSE\n'
                                  '    SELECT v.* INTO source FROM quality_current_issues c JOIN '
                                  'quality_issue_versions v\n'
                                  '      ON v.tenant_id=c.tenant_id AND v.id=c.issue_version_id\n'
                                  '      WHERE c.tenant_id=OLD.tenant_id AND '
                                  'c.product_id=OLD.product_id\n'
                                  '        AND c.project_id=OLD.project_id AND '
                                  'c.issue_id=OLD.issue_id;\n'
                                  '    IF '
                                  'ROW(NEW.id,NEW.tenant_id,NEW.product_id,NEW.project_id,NEW.failure_identity,NEW.failure,NEW.created_at)\n'
                                  '      IS DISTINCT FROM '
                                  'ROW(OLD.id,OLD.tenant_id,OLD.product_id,OLD.project_id,OLD.failure_identity,OLD.failure,OLD.created_at)\n'
                                  '      OR NEW.issue_id=OLD.issue_id OR NEW.epoch<>OLD.epoch+1 OR '
                                  'source.id IS NULL\n'
                                  "      OR source.operation<>'quality.issue.merge' OR "
                                  "target.operation<>'quality.issue.merge'\n"
                                  '      OR source.intent_digest<>target.intent_digest\n'
                                  "      OR source.issue_snapshot->>'merged_into' IS DISTINCT FROM "
                                  'NEW.issue_id::text THEN\n'
                                  "      RAISE EXCEPTION 'Failure alias can move only through the "
                                  "exact preserved merge'; END IF;\n"
                                  '  END IF;\n'
                                  '  RETURN NEW;\n'
                                  'END $$;\n',
 'require_quality_change_atom': '\n'
                                'CREATE FUNCTION require_quality_change_atom() RETURNS trigger '
                                'LANGUAGE plpgsql AS $$\n'
                                'DECLARE target quality_issue_versions%ROWTYPE; prior '
                                'quality_issue_versions%ROWTYPE;\n'
                                '  merge_source quality_issue_versions%ROWTYPE; selected jsonb;\n'
                                '  change_before change_request_versions%ROWTYPE; capture '
                                'change_graph_captures%ROWTYPE;\n'
                                '  receipt action_receipts%ROWTYPE; event outbox_events%ROWTYPE; '
                                'projection test_result_projections%ROWTYPE;\n'
                                'BEGIN\n'
                                "  IF TG_TABLE_NAME='quality_issue_versions' THEN\n"
                                '    target := NEW;\n'
                                '    IF (NEW.revision=1 AND '
                                "NEW.operation<>'quality.issue.create')\n"
                                '      OR (NEW.revision>1 AND '
                                "NEW.operation='quality.issue.create')\n"
                                '      OR NOT EXISTS (SELECT 1 FROM quality_current_issues c WHERE '
                                'c.tenant_id=NEW.tenant_id\n'
                                '        AND c.issue_version_id=NEW.id AND '
                                'c.issue_revision=NEW.revision) THEN\n'
                                "      RAISE EXCEPTION 'Issue version must be the exact canonical "
                                "creation or successor'; END IF;\n"
                                '    IF NEW.previous_issue_version_id IS NOT NULL THEN\n'
                                '      SELECT * INTO prior FROM quality_issue_versions WHERE '
                                'tenant_id=NEW.tenant_id AND id=NEW.previous_issue_version_id;\n'
                                '      IF prior.id IS NULL OR '
                                'ROW(prior.product_id,prior.project_id,prior.issue_id,prior.owner_id,prior.visibility,prior.purpose)\n'
                                '        IS DISTINCT FROM '
                                'ROW(NEW.product_id,NEW.project_id,NEW.issue_id,NEW.owner_id,NEW.visibility,NEW.purpose)\n'
                                '        OR prior.revision<>NEW.previous_revision THEN\n'
                                "        RAISE EXCEPTION 'Issue successor must retain its exact "
                                "owner, audience and scope'; END IF;\n"
                                '    END IF;\n'
                                "    IF NEW.operation='quality.issue.merge' THEN\n"
                                '      SELECT * INTO target FROM quality_issue_versions WHERE '
                                'tenant_id=NEW.tenant_id\n'
                                '        AND product_id=NEW.product_id AND '
                                'project_id=NEW.project_id\n'
                                "        AND issue_id::text=NEW.input_snapshot->>'issue_id' AND "
                                'operation=NEW.operation\n'
                                '        AND intent_digest=NEW.intent_digest AND '
                                'writer_id=NEW.writer_id;\n'
                                "      IF target.id IS NULL THEN RAISE EXCEPTION 'Merge requires "
                                "one exact target version'; END IF;\n"
                                '      IF '
                                "COALESCE(jsonb_typeof(target.input_snapshot->'sources'),'')<>'array'\n"
                                '        OR '
                                "COALESCE(jsonb_array_length(target.input_snapshot->'sources'),0) "
                                'NOT BETWEEN 1 AND 30\n'
                                '        OR EXISTS (SELECT 1 FROM '
                                "jsonb_array_elements(target.input_snapshot->'sources') r\n"
                                "          WHERE r->>'id'=target.issue_id::text)\n"
                                "        OR (SELECT count(DISTINCT r->>'id') FROM "
                                "jsonb_array_elements(target.input_snapshot->'sources') r)\n"
                                "          <>jsonb_array_length(target.input_snapshot->'sources')\n"
                                '        OR (NEW.id<>target.id AND NOT EXISTS (\n'
                                '          SELECT 1 FROM '
                                "jsonb_array_elements(target.input_snapshot->'sources') r\n"
                                "          WHERE r->>'id'=NEW.issue_id::text AND "
                                "(r->>'revision')::integer=NEW.previous_revision)) THEN\n"
                                "        RAISE EXCEPTION 'Merge requires explicit unique sources "
                                "and only its exact listed successors'; END IF;\n"
                                '      IF target.previous_revision IS DISTINCT FROM\n'
                                '        '
                                "(target.input_snapshot->>'expected_issue_revision')::integer "
                                'THEN\n'
                                "        RAISE EXCEPTION 'Merge must retain its exact target "
                                "precondition'; END IF;\n"
                                '      FOR selected IN SELECT * FROM '
                                "jsonb_array_elements(target.input_snapshot->'sources') LOOP\n"
                                '        SELECT * INTO merge_source FROM quality_issue_versions '
                                'WHERE tenant_id=target.tenant_id\n'
                                '          AND product_id=target.product_id AND '
                                'project_id=target.project_id\n'
                                "          AND issue_id::text=selected->>'id' AND "
                                "previous_revision=(selected->>'revision')::integer\n"
                                "          AND revision=(selected->>'revision')::integer+1 AND "
                                'operation=target.operation\n'
                                '          AND intent_digest=target.intent_digest AND '
                                'writer_id=target.writer_id;\n'
                                '        IF merge_source.id IS NULL\n'
                                "          OR merge_source.issue_snapshot->>'merged_into' IS "
                                'DISTINCT FROM target.issue_id::text\n'
                                "          OR NOT COALESCE((target.issue_snapshot->'failures') @> "
                                "(merge_source.issue_snapshot->'failures'),false)\n"
                                '          OR NOT EXISTS (SELECT 1 FROM quality_current_issues c '
                                'WHERE c.tenant_id=target.tenant_id\n'
                                '            AND c.issue_version_id=merge_source.id AND '
                                'c.issue_revision=merge_source.revision) THEN\n'
                                "          RAISE EXCEPTION 'Merge must preserve every exact source "
                                "successor and failure'; END IF;\n"
                                '      END LOOP;\n'
                                '      IF EXISTS (SELECT 1 FROM '
                                "jsonb_array_elements(target.issue_snapshot->'failures') f\n"
                                '        WHERE NOT EXISTS (SELECT 1 FROM quality_failure_maps m '
                                'WHERE m.tenant_id=target.tenant_id\n'
                                '          AND m.product_id=target.product_id AND '
                                'm.project_id=target.project_id\n'
                                '          AND m.issue_id=target.issue_id AND m.failure=f)) THEN\n'
                                "        RAISE EXCEPTION 'Merge requires all stable failure "
                                "aliases to retain their exact target'; END IF;\n"
                                '    END IF;\n'
                                '    PERFORM '
                                'assert_quality_change_receipt(target.tenant_id,target.product_id,target.id,target.revision,\n'
                                '      '
                                "target.operation,'quality_issue',target.writer_id,target.visibility);\n"
                                "  ELSIF TG_TABLE_NAME='quality_policy_facts' THEN\n"
                                '    IF NOT EXISTS (SELECT 1 FROM quality_current_policies c WHERE '
                                'c.tenant_id=NEW.tenant_id\n'
                                '      AND c.fact_id=NEW.id AND c.fact_revision=NEW.revision) '
                                'THEN\n'
                                "      RAISE EXCEPTION 'Policy fact requires its exact canonical "
                                "series pointer'; END IF;\n"
                                '    PERFORM '
                                'assert_quality_change_receipt(NEW.tenant_id,NEW.product_id,NEW.id,NEW.revision,\n'
                                '      '
                                "'quality.policy.import','quality_policy_fact',NEW.owner_id,NEW.visibility);\n"
                                "  ELSIF TG_TABLE_NAME='change_request_versions' THEN\n"
                                '    IF NOT EXISTS (SELECT 1 FROM change_request_currents c WHERE '
                                'c.tenant_id=NEW.tenant_id\n'
                                '      AND c.version_id=NEW.id AND c.revision=NEW.revision)\n'
                                "      OR (NEW.operation='change.request.create' AND "
                                '(NEW.revision<>1\n'
                                "        OR NEW.request_snapshot->'assessments' IS DISTINCT FROM "
                                "'[]'::jsonb))\n"
                                "      OR (NEW.operation='change.impact.compute' AND "
                                'NEW.revision<2) THEN\n'
                                "      RAISE EXCEPTION 'Change creation and impact must advance "
                                "the exact canonical pointer'; END IF;\n"
                                '    IF NEW.previous_version_id IS NOT NULL THEN\n'
                                '      SELECT * INTO change_before FROM change_request_versions '
                                'WHERE tenant_id=NEW.tenant_id AND id=NEW.previous_version_id;\n'
                                '      IF change_before.id IS NULL OR '
                                'ROW(change_before.product_id,change_before.project_id,change_before.change_id,\n'
                                '        change_before.owner_id,change_before.visibility) IS '
                                'DISTINCT FROM\n'
                                '        '
                                'ROW(NEW.product_id,NEW.project_id,NEW.change_id,NEW.owner_id,NEW.visibility)\n'
                                '        OR change_before.revision<>NEW.previous_revision THEN\n'
                                "        RAISE EXCEPTION 'Change successor must retain exact "
                                "owner, audience and scope'; END IF;\n"
                                '    END IF;\n'
                                "    IF NEW.operation='change.impact.compute' THEN\n"
                                '      SELECT * INTO capture FROM change_graph_captures WHERE '
                                'tenant_id=NEW.tenant_id\n'
                                '        AND '
                                "id::text=(NEW.request_snapshot->'assessments'->-1)->'graph'->>'id';\n"
                                '      IF capture.id IS NULL OR '
                                'ROW(capture.product_id,capture.project_id,capture.change_id,\n'
                                '        capture.change_version_id,capture.change_revision) IS '
                                'DISTINCT FROM\n'
                                '        '
                                'ROW(NEW.product_id,NEW.project_id,NEW.change_id,NEW.previous_version_id,NEW.previous_revision)\n'
                                '        OR capture.graph_snapshot IS DISTINCT FROM '
                                "(NEW.request_snapshot->'assessments'->-1)->'graph'\n"
                                '        OR '
                                "jsonb_array_length(NEW.request_snapshot->'assessments')\n"
                                '          '
                                "<>jsonb_array_length(change_before.request_snapshot->'assessments')+1\n"
                                "        OR ((NEW.request_snapshot->'assessments')\n"
                                '          - '
                                "(jsonb_array_length(NEW.request_snapshot->'assessments')-1))\n"
                                '          IS DISTINCT FROM '
                                "(change_before.request_snapshot->'assessments')\n"
                                '        OR capture.expires_at<=NEW.created_at THEN\n'
                                "        RAISE EXCEPTION 'Impact successor requires its exact "
                                "unexpired committed graph capture'; END IF;\n"
                                '    END IF;\n'
                                '    PERFORM '
                                'assert_quality_change_receipt(NEW.tenant_id,NEW.product_id,NEW.id,NEW.revision,\n'
                                '      '
                                "NEW.operation,'change_request',(NEW.authority_snapshot->>'subject_id')::uuid,NEW.visibility);\n"
                                "  ELSIF TG_TABLE_NAME='quality_event_failure_links' THEN\n"
                                '    IF NOT EXISTS (SELECT 1 FROM quality_issue_versions v,\n'
                                "      LATERAL jsonb_array_elements(v.issue_snapshot->'failures') "
                                'f\n'
                                '      WHERE v.tenant_id=NEW.tenant_id AND '
                                'v.id=NEW.issue_version_id\n'
                                "        AND (f-'run')=(NEW.failure-'run') AND "
                                "f->'run'->>'id'=NEW.run_id::text) THEN\n"
                                "      RAISE EXCEPTION 'Event delivery must retain the stable "
                                "failure and its actual event Run revision'; END IF;\n"
                                '    SELECT * INTO event FROM outbox_events WHERE '
                                'tenant_id=NEW.tenant_id AND id=NEW.event_id;\n'
                                '    SELECT * INTO receipt FROM action_receipts WHERE '
                                'tenant_id=NEW.tenant_id AND id=event.receipt_id;\n'
                                '    SELECT * INTO projection FROM test_result_projections WHERE '
                                'tenant_id=NEW.tenant_id AND id=NEW.projection_id;\n'
                                '    IF receipt.id IS NULL OR receipt.product_id<>NEW.product_id '
                                'OR event.subject_id<>receipt.subject_id\n'
                                '      OR event.subject_revision<>receipt.subject_revision OR '
                                'event.actor_id<>receipt.actor_id\n'
                                '      OR event.schema_version<>1 OR '
                                'event.correlation_id<>receipt.command_id\n'
                                '      OR projection.basis_sha256<>NEW.basis_sha256\n'
                                '      OR NOT EXISTS (SELECT 1 FROM '
                                'jsonb_array_elements(projection.computed_results) r\n'
                                "        WHERE r->>'measurement_id'=NEW.measurement_id::text AND "
                                "r->>'result'='fail')\n"
                                "      OR NOT ((receipt.operation='test.result.compute' AND "
                                "receipt.subject_type='test_result_projection'\n"
                                '          AND receipt.subject_id=NEW.projection_id AND '
                                'receipt.subject_revision=NEW.projection_revision\n'
                                "          AND event.type='test.result_computed' AND "
                                'projection.run_version_id=NEW.run_version_id)\n'
                                '        OR (receipt.operation IN '
                                "('test.results.import','test.run.review','test.disposition.decide')\n"
                                "          AND receipt.subject_type='test_run' AND "
                                'receipt.subject_id=NEW.run_version_id\n'
                                '          AND receipt.subject_revision=NEW.run_revision\n'
                                '          AND EXISTS (SELECT 1 FROM test_result_actions a WHERE '
                                'a.tenant_id=NEW.tenant_id\n'
                                '            AND a.product_id=NEW.product_id AND '
                                'a.project_id=NEW.project_id\n'
                                '            AND a.build_id=NEW.build_id AND '
                                'a.request_id=NEW.request_id AND a.run_id=NEW.run_id\n'
                                '            AND a.next_run_version_id=NEW.run_version_id AND '
                                'a.next_run_revision=NEW.run_revision\n'
                                '            AND a.operation=receipt.operation AND '
                                'a.projection_id=NEW.projection_id)\n'
                                '          AND event.type=CASE receipt.operation WHEN '
                                "'test.results.import' THEN 'test.results_imported'\n"
                                "            WHEN 'test.run.review' THEN 'test.run_reviewed' ELSE "
                                "'test.disposition_decided' END)) THEN\n"
                                "      RAISE EXCEPTION 'Failure link requires its exact actual "
                                "result event and fixed failing projection'; END IF;\n"
                                '  END IF;\n'
                                '  RETURN NULL;\n'
                                'END $$;\n'}

IMMUTABLE = ('quality_issue_versions',
 'quality_policy_facts',
 'quality_event_failure_links',
 'change_request_versions',
 'change_graph_captures')

POINTERS = {'quality_current_issues': 'protect_quality_current',
 'quality_current_policies': 'protect_quality_policy_current',
 'quality_failure_maps': 'protect_quality_failure_alias',
 'change_request_currents': 'protect_change_current'}

ATOMIC = ('quality_issue_versions',
 'quality_policy_facts',
 'quality_event_failure_links',
 'change_request_versions')

PARENT_TABLES = ('verification_run_versions', 'test_measurements', 'test_result_projections')

PARENT_COLUMNS = ('tenant_id', 'product_id', 'project_id', 'request_id', 'run_id', 'id', 'revision')
