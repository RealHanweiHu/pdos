"""Knowledge T2 deadline registration and bounded ordinary-caller receipt ACL."""

OLD_CHECK = ('CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "((ARRAY['release.exception.decide'::character varying, 'release.exception.withdraw'::character "
 'varying])::text[])))))')

NEW_CHECK = ('CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "(ARRAY[('release.exception.decide'::character varying)::text, "
 "('release.exception.withdraw'::character varying)::text]))) OR ((operation)::text = "
 "'knowledge.rule.publish'::text)))")

PREVIOUS_FUNCTIONS = {}

KNOWLEDGE_FUNCTIONS = {'knowledge_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)': 'CREATE OR REPLACE FUNCTION '
                                                                          'public.knowledge_receipt_visible(t '
                                                                          'uuid, c uuid, p uuid, kind '
                                                                          'text, target uuid, rev '
                                                                          'integer, receipt uuid, '
                                                                          'actor uuid)\n'
                                                                          ' RETURNS boolean\n'
                                                                          ' LANGUAGE plpgsql\n'
                                                                          ' STABLE\n'
                                                                          ' SET search_path TO '
                                                                          "'pg_catalog', 'public', "
                                                                          "'pg_temp'\n"
                                                                          'AS $function$\n'
                                                                          'BEGIN\n'
                                                                          ' IF kind NOT IN '
                                                                          "('knowledge_candidate','design_rule') "
                                                                          'THEN RETURN true; END IF;\n'
                                                                          ' IF NOT '
                                                                          'public.category_access(t,c) '
                                                                          'THEN RETURN false; END IF;\n'
                                                                          ' IF '
                                                                          "kind='knowledge_candidate' "
                                                                          'THEN\n'
                                                                          '  RETURN EXISTS(SELECT 1 '
                                                                          'FROM '
                                                                          'public.knowledge_candidate_versions '
                                                                          'k WHERE k.tenant_id=t AND '
                                                                          'k.category_id=c AND '
                                                                          'k.product_id IS NOT '
                                                                          'DISTINCT FROM p AND '
                                                                          'k.id=target AND '
                                                                          'k.revision=rev AND '
                                                                          'k.receipt_id=receipt AND '
                                                                          'k.actor_id=actor AND '
                                                                          "k.operation='knowledge.candidate.create');\n"
                                                                          " ELSIF kind='design_rule' "
                                                                          'THEN\n'
                                                                          '  RETURN EXISTS(SELECT 1 '
                                                                          'FROM '
                                                                          'public.knowledge_rule_versions '
                                                                          'k WHERE k.tenant_id=t AND '
                                                                          'k.category_id=c AND '
                                                                          'k.product_id=p AND '
                                                                          'k.id=target AND '
                                                                          'k.revision=rev AND '
                                                                          'k.receipt_id=receipt AND '
                                                                          'k.actor_id=actor AND '
                                                                          "k.operation='knowledge.rule.publish');\n"
                                                                          ' END IF;\n'
                                                                          ' RETURN false;\n'
                                                                          'END;\n'
                                                                          '$function$\n'}

SCHEMA_SQL = ('CREATE FUNCTION public.knowledge_receipt_visible(t uuid,c uuid,p uuid,kind text,target uuid,rev '
 'integer,receipt uuid,actor uuid)\n'
 'RETURNS boolean LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path=pg_catalog,public,pg_temp '
 'AS $knowledge_receipt$\n'
 'BEGIN\n'
 " IF kind NOT IN ('knowledge_candidate','design_rule') THEN RETURN true; END IF;\n"
 ' IF NOT public.category_access(t,c) THEN RETURN false; END IF;\n'
 " IF kind='knowledge_candidate' THEN\n"
 '  RETURN EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k WHERE k.tenant_id=t AND '
 'k.category_id=c AND k.product_id IS NOT DISTINCT FROM p AND k.id=target AND k.revision=rev AND '
 "k.receipt_id=receipt AND k.actor_id=actor AND k.operation='knowledge.candidate.create');\n"
 " ELSIF kind='design_rule' THEN\n"
 '  RETURN EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE k.tenant_id=t AND '
 'k.category_id=c AND k.product_id=p AND k.id=target AND k.revision=rev AND k.receipt_id=receipt AND '
 "k.actor_id=actor AND k.operation='knowledge.rule.publish');\n"
 ' END IF;\n'
 ' RETURN false;\n'
 'END;\n'
 '$knowledge_receipt$',
 'REVOKE ALL ON FUNCTION public.knowledge_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) '
 'FROM PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch',
 'GRANT EXECUTE ON FUNCTION '
 'public.knowledge_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid) TO pdos_next_app',
 'DROP POLICY knowledge_receipt_owner ON public.action_receipts',
 'DROP POLICY knowledge_receipt_content ON public.action_receipts',
 'CREATE POLICY knowledge_receipt_content ON public.action_receipts AS RESTRICTIVE FOR SELECT TO '
 'pdos_next_app '
 'USING(public.knowledge_receipt_visible(tenant_id,category_id,product_id,subject_type::text,subject_id,subject_revision,id,actor_id))',
 'CREATE POLICY knowledge_receipt_owner ON public.action_receipts FOR SELECT TO pdos_next_app '
 "USING(subject_type IN ('knowledge_candidate','design_rule') AND "
 'public.knowledge_receipt_visible(tenant_id,category_id,product_id,subject_type::text,subject_id,subject_revision,id,actor_id))',
 'ALTER TABLE public.confirmations DROP CONSTRAINT ck_confirmations_decision_deadline',
 'ALTER TABLE public.confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK '
 '(((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "((ARRAY['release.exception.decide'::character varying, 'release.exception.withdraw'::character "
 "varying])::text[])))) OR operation='knowledge.rule.publish')")

DOWNGRADE_SQL = ('DO $knowledge$ BEGIN IF EXISTS(SELECT 1 FROM public.confirmations WHERE '
 "operation='knowledge.rule.publish' AND expires_at IS NULL) THEN RAISE EXCEPTION 'Knowledge named "
 "confirmation history retained; downgrade refused' USING ERRCODE='23514'; END IF; END; $knowledge$",
 'DROP POLICY knowledge_receipt_owner ON public.action_receipts',
 'DROP POLICY knowledge_receipt_content ON public.action_receipts',
 'CREATE POLICY knowledge_receipt_content ON public.action_receipts AS RESTRICTIVE FOR SELECT TO '
 "pdos_next_app USING(((subject_type NOT IN ('knowledge_candidate','design_rule')) OR\n"
 " (subject_type='knowledge_candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k "
 'WHERE k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id IS NOT DISTINCT FROM action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id)) OR\n'
 " (subject_type='design_rule' AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE "
 'k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id=action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id))))',
 'CREATE POLICY knowledge_receipt_owner ON public.action_receipts FOR SELECT TO pdos_next_app '
 "USING(subject_type IN ('knowledge_candidate','design_rule') AND ((subject_type NOT IN "
 "('knowledge_candidate','design_rule')) OR\n"
 " (subject_type='knowledge_candidate' AND EXISTS(SELECT 1 FROM public.knowledge_candidate_versions k "
 'WHERE k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id IS NOT DISTINCT FROM action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id)) OR\n'
 " (subject_type='design_rule' AND EXISTS(SELECT 1 FROM public.knowledge_rule_versions k WHERE "
 'k.tenant_id=action_receipts.tenant_id AND k.category_id=action_receipts.category_id AND '
 'k.product_id=action_receipts.product_id AND k.id=action_receipts.subject_id AND '
 'k.revision=action_receipts.subject_revision AND k.receipt_id=action_receipts.id AND '
 'k.operation=action_receipts.operation AND k.actor_id=action_receipts.actor_id))))',
 'DROP FUNCTION public.knowledge_receipt_visible(uuid,uuid,uuid,text,uuid,integer,uuid,uuid)',
 'ALTER TABLE public.confirmations DROP CONSTRAINT ck_confirmations_decision_deadline',
 'ALTER TABLE public.confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK '
 '(((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "((ARRAY['release.exception.decide'::character varying, 'release.exception.withdraw'::character "
 'varying])::text[])))))')


# PostgreSQL reparses an array cast into equivalent per-element casts on restore.
OLD_CHECKS = ('CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "((ARRAY['release.exception.decide'::character varying, 'release.exception.withdraw'::character "
 'varying])::text[])))))',
 'CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY '
 "(ARRAY[('release.engineering.approve'::character varying)::text, "
 "('release.manufacturing.approve'::character varying)::text, "
 "('npi.manufacturing_baseline.publish'::character varying)::text, ('mcp.connector.allow'::character "
 "varying)::text, ('ai.skill.qualify'::character varying)::text, "
 "('build.engineering.authorize'::character varying)::text, "
 "('build.manufacturing.authorize'::character varying)::text, ('change.order.approve'::character "
 "varying)::text, ('change.selection.decide'::character varying)::text, "
 "('proposal.g0.decide'::character varying)::text, ('quality.capa.verification.review'::character "
 "varying)::text, ('quality.issue.root_cause.decide'::character varying)::text, "
 "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
 'varying)::text])) OR ((expires_at IS NULL) AND ((operation)::text = '
 "'integration.handoff.authorize'::text)) OR ((expires_at IS NULL) AND ((operation)::text = ANY "
 "(ARRAY[('release.exception.decide'::character varying)::text, "
 "('release.exception.withdraw'::character varying)::text])))))")
