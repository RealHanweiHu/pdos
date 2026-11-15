"""Assigned s0_0891 on s0_0890 at the 11-15 memory integration (placeholder s0_0900).

Scope notes for M2b (P87; P121 第 3、4、6 项): notes, versions, evidence links, relations.

占位号: written as placeholder s0_0900 on head s0_0887 in a parallel worktree
(2026-11-13); at integration the revision, down_revision, this snapshot's file
name and the downgrade guard text move together to the real head (不可协商项 3).

A scope note is attached to a category and optionally one product, proposal or
project. Reading follows that object's own audience, evaluated for the reader
at read time: no audience copy is stored, so narrowing the object narrows its
notes at once. Every table is append-only. A version is bound at commit to the
common receipt of one registered command. A named person acting for themself
writes any kind; the AI writer identity can only write, inside its own Run's
receipt of ``scope_note.observation.record``, a new unverified observation or
an evidence link on an existing note (P121 第 4 项). Qualification for that lane
is checked by the command path, not here.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

# Filled from the exact reviewed ORM tables (pdos_next.domain.knowledge.scope_notes.models).
TABLE_SQL = (
    "\nCREATE TABLE scope_notes (\n\tclaim_key VARCHAR(64) NOT NULL, \n\tauthor_id UUID NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tproduct_id UUID, \n\tproposal_id UUID, \n\tproject_id UUID, \n\tanchor_kind VARCHAR(16) NOT NULL, \n\tkind VARCHAR(24) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tCONSTRAINT scope_note_binding UNIQUE (tenant_id, category_id, id, anchor_kind, kind), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, id), \n\tFOREIGN KEY(tenant_id, category_id, proposal_id) REFERENCES proposals (tenant_id, category_id, id), \n\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n\tFOREIGN KEY(tenant_id, author_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT scope_note_anchor CHECK (anchor_kind IN ('category','product','proposal','project') AND ((anchor_kind='category' AND product_id IS NULL AND proposal_id IS NULL AND project_id IS NULL) OR (anchor_kind='product' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NULL) OR (anchor_kind='proposal' AND product_id IS NULL AND proposal_id IS NOT NULL AND project_id IS NULL) OR (anchor_kind='project' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NOT NULL))), \n\tCONSTRAINT scope_note_kind CHECK (kind IN ('convention','concern','decision_context','observation')), \n\tCONSTRAINT scope_note_claim_key CHECK (claim_key ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_scope_notes_anchor ON scope_notes (tenant_id, category_id, anchor_kind)',
    'CREATE INDEX ix_scope_notes_category_id ON scope_notes (category_id)',
    'CREATE INDEX ix_scope_notes_project ON scope_notes (tenant_id, project_id)',
    'CREATE INDEX ix_scope_notes_proposal ON scope_notes (tenant_id, proposal_id)',
    'CREATE INDEX ix_scope_notes_tenant_id ON scope_notes (tenant_id)',
    "\nCREATE TABLE scope_note_versions (\n\tnote_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\taction VARCHAR(16) NOT NULL, \n\tlifecycle VARCHAR(16) NOT NULL, \n\tstatement TEXT NOT NULL, \n\tsubject_kind VARCHAR(16), \n\tsubject_id UUID, \n\tsubject_version INTEGER, \n\tcustomer_identity VARCHAR(80), \n\tstage VARCHAR(40), \n\ttopic VARCHAR(40), \n\tsensitivity VARCHAR(24) NOT NULL, \n\tsource_authority VARCHAR(24) NOT NULL, \n\tepistemic VARCHAR(16) NOT NULL, \n\tconfirmation VARCHAR(24) NOT NULL, \n\tformal_kind VARCHAR(24), \n\tformal_id UUID, \n\tformal_version INTEGER, \n\tgenerated_by VARCHAR(24) NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE, \n\tvalid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n\tvalid_to TIMESTAMP WITH TIME ZONE, \n\treview_due_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tpinned BOOLEAN NOT NULL, \n\twriter_id UUID NOT NULL, \n\trequester_id UUID NOT NULL, \n\tconfirmed_by UUID, \n\trun_id UUID, \n\treason TEXT, \n\torigin JSONB NOT NULL, \n\toperation VARCHAR(80) NOT NULL, \n\tcommand_id UUID NOT NULL, \n\treceipt_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tcategory_id UUID NOT NULL, \n\tproduct_id UUID, \n\tproposal_id UUID, \n\tproject_id UUID, \n\tanchor_kind VARCHAR(16) NOT NULL, \n\tkind VARCHAR(24) NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, note_id, revision), \n\tFOREIGN KEY(tenant_id, category_id, note_id, anchor_kind, kind) REFERENCES scope_notes (tenant_id, category_id, id, anchor_kind, kind), \n\tFOREIGN KEY(tenant_id, category_id) REFERENCES categories (tenant_id, id), \n\tFOREIGN KEY(tenant_id, category_id, product_id) REFERENCES products (tenant_id, category_id, id), \n\tFOREIGN KEY(tenant_id, category_id, proposal_id) REFERENCES proposals (tenant_id, category_id, id), \n\tFOREIGN KEY(tenant_id, product_id, project_id) REFERENCES projects (tenant_id, product_id, id), \n\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, confirmed_by) REFERENCES principals (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id) DEFERRABLE INITIALLY DEFERRED, \n\tCONSTRAINT scope_note_version_anchor CHECK (anchor_kind IN ('category','product','proposal','project') AND ((anchor_kind='category' AND product_id IS NULL AND proposal_id IS NULL AND project_id IS NULL) OR (anchor_kind='product' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NULL) OR (anchor_kind='proposal' AND product_id IS NULL AND proposal_id IS NOT NULL AND project_id IS NULL) OR (anchor_kind='project' AND product_id IS NOT NULL AND proposal_id IS NULL AND project_id IS NOT NULL))), \n\tCONSTRAINT scope_note_version_chain CHECK (revision > 0 AND kind IN ('convention','concern','decision_context','observation') AND action IN ('create','revise','add_evidence','supersede','backfill','retire','withdraw') AND lifecycle IN ('active','superseded','withdrawn','retired') AND operation IN ('scope_note.save','scope_note.retire','scope_note.observation.record') AND ((revision=1) = (action IN ('create','backfill')))), \n\tCONSTRAINT scope_note_version_statement CHECK (char_length(statement) BETWEEN 1 AND 300), \n\tCONSTRAINT scope_note_version_subject CHECK ((subject_id IS NULL) = (subject_kind IS NULL) AND (subject_id IS NULL) = (subject_version IS NULL) AND (subject_kind IS NULL OR subject_kind IN ('category','product','proposal','project'))), \n\tCONSTRAINT scope_note_version_formal CHECK ((formal_id IS NULL) = (formal_kind IS NULL) AND (formal_id IS NULL) = (formal_version IS NULL) AND (formal_kind IS NULL OR formal_kind IN ('category','product','proposal','project','proposal_decision')) AND ((confirmation='formal_linked') = (formal_id IS NOT NULL))), \n\tCONSTRAINT scope_note_version_states CHECK (source_authority IN ('business_record','published_rule','verified_answer','original','human_statement','discussion','xiaopai_generated') AND epistemic IN ('stated','verified','inferred','disputed') AND confirmation IN ('discussion','proposed','member_confirmed','formal_linked') AND generated_by IN ('human','xiaopai_drafted','xiaopai') AND sensitivity IN ('normal','customer_private') AND ((sensitivity='customer_private') = (customer_identity IS NOT NULL))), \n\tCONSTRAINT scope_note_version_writer CHECK ((generated_by<>'xiaopai' OR (kind='observation' AND epistemic IN ('stated','inferred') AND confirmation='proposed' AND confirmed_by IS NULL AND run_id IS NOT NULL AND NOT pinned)) AND (generated_by='xiaopai' OR action IN ('retire','withdraw','supersede') OR confirmed_by IS NOT NULL) AND (generated_by<>'xiaopai_drafted' OR run_id IS NOT NULL)), \n\tCONSTRAINT scope_note_version_time CHECK ((valid_to IS NULL OR valid_to >= valid_from) AND review_due_at >= created_at AND (lifecycle<>'active' OR action IN ('create','revise','add_evidence')) AND ((action IN ('retire','withdraw')) = (lifecycle IN ('retired','withdrawn'))) AND (reason IS NULL OR char_length(reason) BETWEEN 1 AND 200)), \n\tCONSTRAINT scope_note_version_origin CHECK (jsonb_typeof(origin)='object' AND request_digest ~ '^[0-9a-f]{64}$')\n)\n\n",
    'CREATE INDEX ix_scope_note_versions_category_id ON scope_note_versions (category_id)',
    'CREATE INDEX ix_scope_note_versions_note ON scope_note_versions (tenant_id, note_id, revision)',
    'CREATE INDEX ix_scope_note_versions_receipt ON scope_note_versions (tenant_id, receipt_id)',
    'CREATE INDEX ix_scope_note_versions_run ON scope_note_versions (tenant_id, run_id)',
    'CREATE INDEX ix_scope_note_versions_tenant_id ON scope_note_versions (tenant_id)',
    "\nCREATE TABLE scope_note_evidence (\n\tcategory_id UUID NOT NULL, \n\tnote_id UUID NOT NULL, \n\trevision INTEGER NOT NULL, \n\tsource_type VARCHAR(24) NOT NULL, \n\tsource_kind VARCHAR(24), \n\tsource_id UUID NOT NULL, \n\tsource_version INTEGER, \n\tlocator JSONB NOT NULL, \n\tquote_sha256 VARCHAR(64), \n\troot_source_id UUID NOT NULL, \n\tstance VARCHAR(16) NOT NULL, \n\twriter_id UUID NOT NULL, \n\trun_id UUID, \n\tretracts_id UUID, \n\treceipt_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, retracts_id), \n\tFOREIGN KEY(tenant_id, retracts_id) REFERENCES scope_note_evidence (tenant_id, id), \n\tFOREIGN KEY(tenant_id, run_id) REFERENCES agent_runs (tenant_id, id), \n\tFOREIGN KEY(tenant_id, note_id, revision) REFERENCES scope_note_versions (tenant_id, note_id, revision) DEFERRABLE INITIALLY DEFERRED, \n\tFOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT scope_note_evidence_shape CHECK (source_type IN ('run','discussion','receipt','original','business_object') AND stance IN ('supports','opposes','context') AND ((source_type='business_object') = (source_kind IS NOT NULL)) AND (source_kind IS NULL OR source_kind IN ('category','product','proposal','project','proposal_decision')) AND jsonb_typeof(locator)='object' AND (quote_sha256 IS NULL OR quote_sha256 ~ '^[0-9a-f]{64}$'))\n)\n\n",
    'CREATE INDEX ix_scope_note_evidence_category_id ON scope_note_evidence (category_id)',
    'CREATE INDEX ix_scope_note_evidence_note ON scope_note_evidence (tenant_id, note_id, revision)',
    'CREATE INDEX ix_scope_note_evidence_run ON scope_note_evidence (tenant_id, run_id)',
    'CREATE INDEX ix_scope_note_evidence_tenant_id ON scope_note_evidence (tenant_id)',
    "\nCREATE TABLE scope_note_relations (\n\tcategory_id UUID NOT NULL, \n\tfrom_note_id UUID NOT NULL, \n\tto_note_id UUID NOT NULL, \n\ttype VARCHAR(16) NOT NULL, \n\tcreated_by UUID NOT NULL, \n\treceipt_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (tenant_id, id), \n\tUNIQUE (tenant_id, from_note_id, to_note_id, type), \n\tFOREIGN KEY(tenant_id, from_note_id) REFERENCES scope_notes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, to_note_id) REFERENCES scope_notes (tenant_id, id), \n\tFOREIGN KEY(tenant_id, created_by) REFERENCES principals (tenant_id, id), \n\tCONSTRAINT scope_note_relation_type CHECK (type IN ('supersedes','conflicts','duplicates','refines','derived_from') AND from_note_id<>to_note_id)\n)\n\n",
    'CREATE INDEX ix_scope_note_relations_category_id ON scope_note_relations (category_id)',
    'CREATE INDEX ix_scope_note_relations_tenant_id ON scope_note_relations (tenant_id)',
    'CREATE INDEX ix_scope_note_relations_to ON scope_note_relations (tenant_id, to_note_id)',
)

TABLES = ("scope_notes", "scope_note_versions", "scope_note_evidence", "scope_note_relations")
_REVOKED = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
_OWNER = "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp"

# The reader's own view of the attached object: category grant, then the product,
# proposal and project audiences exactly as those objects decide them.
OPEN_SQL = """
CREATE FUNCTION public.scope_note_open(t uuid, c uuid, product uuid, proposal uuid, project uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $scope_note$
 SELECT public.category_access(t, c)
  AND (product IS NULL OR EXISTS(SELECT 1 FROM public.products m WHERE m.tenant_id=t AND m.category_id=c AND m.id=product
   AND (m.visibility='category' OR m.owner_id=public.scope_requester() OR EXISTS(SELECT 1 FROM public.object_audiences a
    WHERE a.tenant_id=m.tenant_id AND a.category_id=m.category_id AND a.object_type='products' AND a.subject_id=m.id
     AND a.owner_id=m.owner_id AND a.principal_id=public.scope_requester()))))
  AND (proposal IS NULL OR public.m3_proposal_reader(t, c, proposal))
  AND (project IS NULL OR public.discussion_project_open(t, project))
$scope_note$
"""

NOTE_OPEN_SQL = """
CREATE FUNCTION public.scope_note_readable(t uuid, note uuid) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog,public,pg_temp AS $scope_note$
 SELECT EXISTS(SELECT 1 FROM public.scope_notes n WHERE n.tenant_id=t AND n.id=note)
$scope_note$
"""

IDENTITY_ATOM_SQL = f"""
CREATE FUNCTION public.require_scope_note() RETURNS trigger LANGUAGE plpgsql {_OWNER} AS $scope_note$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.scope_note_versions v WHERE v.tenant_id=NEW.tenant_id AND v.note_id=NEW.id
   AND v.revision=1 AND v.writer_id=NEW.author_id) THEN
  RAISE EXCEPTION 'scope_note requires its first version' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $scope_note$
"""

VERSION_ATOM_SQL = f"""
CREATE FUNCTION public.require_scope_note_version() RETURNS trigger LANGUAGE plpgsql {_OWNER} AS $scope_note$
DECLARE r public.action_receipts; p public.principals; prior public.scope_note_versions;
BEGIN
 SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NOT FOUND OR r.operation<>NEW.operation OR r.subject_type<>'scope_note' OR r.actor_id<>NEW.writer_id
  OR r.requester_id<>NEW.requester_id OR r.command_id<>NEW.command_id OR r.category_id<>NEW.category_id
  OR r.request_digest<>NEW.request_digest THEN
  RAISE EXCEPTION 'scope_note version requires its exact common receipt' USING ERRCODE='23514'; END IF;
 IF NEW.revision>1 THEN
  SELECT * INTO prior FROM public.scope_note_versions WHERE tenant_id=NEW.tenant_id AND note_id=NEW.note_id
   AND revision=NEW.revision-1;
  IF NOT FOUND OR prior.lifecycle<>'active' THEN
   RAISE EXCEPTION 'only an active scope_note advances, one revision at a time' USING ERRCODE='23514'; END IF;
 END IF;
 SELECT * INTO STRICT p FROM public.principals WHERE tenant_id=NEW.tenant_id AND id=NEW.writer_id;
 IF p.kind='human' THEN
  IF NEW.writer_id<>NEW.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
   OR (NEW.action IN ('create','revise','backfill')
    AND (NEW.generated_by='xiaopai' OR NEW.confirmed_by IS DISTINCT FROM NEW.writer_id)) THEN
   RAISE EXCEPTION 'a person writes a scope_note for themself and is its confirmer' USING ERRCODE='23514'; END IF;
 ELSE
  -- P121 第 4 项: 小Pai writes only inside its own Run, only an unverified observation or an
  -- evidence link that leaves the confirmed content exactly as it was.
  IF r.agent_run_id IS NULL OR NEW.run_id IS DISTINCT FROM r.agent_run_id
   OR NEW.operation<>'scope_note.observation.record' OR NEW.action NOT IN ('create','add_evidence')
   OR (NEW.action='create' AND NEW.generated_by<>'xiaopai')
   OR (NEW.action='add_evidence' AND (prior.statement, prior.kind, prior.epistemic, prior.confirmation, prior.generated_by,
     prior.confirmed_by, prior.pinned, prior.valid_from, prior.valid_to, prior.review_due_at, prior.customer_identity)
    IS DISTINCT FROM (NEW.statement, NEW.kind, NEW.epistemic, NEW.confirmation, NEW.generated_by,
     NEW.confirmed_by, NEW.pinned, NEW.valid_from, NEW.valid_to, NEW.review_due_at, NEW.customer_identity)) THEN
   RAISE EXCEPTION 'the AI identity writes only its own Run''s unverified observation or evidence link' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NULL;
END $scope_note$
"""

LINK_ATOM_SQL = f"""
CREATE FUNCTION public.require_scope_note_link() RETURNS trigger LANGUAGE plpgsql {_OWNER} AS $scope_note$
DECLARE r public.action_receipts; writer uuid;
BEGIN
 writer := CASE TG_TABLE_NAME WHEN 'scope_note_evidence' THEN (to_jsonb(NEW)->>'writer_id')::uuid
  ELSE (to_jsonb(NEW)->>'created_by')::uuid END;
 SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NOT FOUND OR r.subject_type<>'scope_note' OR r.actor_id<>writer OR r.category_id<>NEW.category_id
  OR r.operation NOT IN ('scope_note.save','scope_note.retire','scope_note.observation.record') THEN
  RAISE EXCEPTION 'scope_note link requires its common receipt' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $scope_note$
"""

_READ = "public.scope_note_open(tenant_id,category_id,product_id,proposal_id,project_id)"
_WRITE = "public.category_access(tenant_id,category_id,true)"
# A direct write by the AI identity outside the observation lane is refused at once.
_VERSION_WRITER = (
    "writer_id=public.scope_actor() AND requester_id=public.scope_requester() AND "
    "(public.scope_actor()=public.scope_requester() OR "
    "(operation='scope_note.observation.record' AND action IN ('create','add_evidence')))"
)
_PARENT = "public.category_access(tenant_id,category_id) AND public.scope_note_readable(tenant_id,{note})"

SECURITY_SQL = (
    OPEN_SQL,
    NOTE_OPEN_SQL,
    IDENTITY_ATOM_SQL,
    VERSION_ATOM_SQL,
    LINK_ATOM_SQL,
    f"REVOKE ALL ON FUNCTION public.scope_note_open(uuid,uuid,uuid,uuid,uuid), public.scope_note_readable(uuid,uuid), "
    f"public.require_scope_note(), public.require_scope_note_version(), public.require_scope_note_link() FROM {_REVOKED}",
    "GRANT EXECUTE ON FUNCTION public.scope_note_open(uuid,uuid,uuid,uuid,uuid), public.scope_note_readable(uuid,uuid) TO pdos_next_app",
    *(statement for table in TABLES for statement in (
        f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY owner_internal ON public.{table} TO pdos_next_owner USING(true) WITH CHECK(true)",
        f"REVOKE ALL ON public.{table} FROM {_REVOKED}",
        f"GRANT SELECT,INSERT ON public.{table} TO pdos_next_app",
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON public.{table} "
        "FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
    )),
    f"CREATE POLICY scope_notes_read ON public.scope_notes FOR SELECT TO pdos_next_app USING({_READ})",
    f"CREATE POLICY scope_notes_insert ON public.scope_notes FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_WRITE} AND {_READ} AND author_id=public.scope_actor())",
    f"CREATE POLICY scope_note_versions_read ON public.scope_note_versions FOR SELECT TO pdos_next_app USING({_READ})",
    f"CREATE POLICY scope_note_versions_insert ON public.scope_note_versions FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_WRITE} AND {_READ} AND {_VERSION_WRITER})",
    f"CREATE POLICY scope_note_evidence_read ON public.scope_note_evidence FOR SELECT TO pdos_next_app "
    f"USING({_PARENT.format(note='note_id')})",
    f"CREATE POLICY scope_note_evidence_insert ON public.scope_note_evidence FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_WRITE} AND {_PARENT.format(note='note_id')} AND writer_id=public.scope_actor())",
    f"CREATE POLICY scope_note_relations_read ON public.scope_note_relations FOR SELECT TO pdos_next_app "
    f"USING({_PARENT.format(note='from_note_id')} AND public.scope_note_readable(tenant_id,to_note_id))",
    f"CREATE POLICY scope_note_relations_insert ON public.scope_note_relations FOR INSERT TO pdos_next_app "
    f"WITH CHECK({_WRITE} AND {_PARENT.format(note='from_note_id')} AND public.scope_note_readable(tenant_id,to_note_id) "
    "AND created_by=public.scope_actor() AND public.scope_actor()=public.scope_requester())",
    "CREATE CONSTRAINT TRIGGER scope_note_atom AFTER INSERT ON public.scope_notes DEFERRABLE INITIALLY DEFERRED "
    "FOR EACH ROW EXECUTE FUNCTION public.require_scope_note()",
    "CREATE CONSTRAINT TRIGGER scope_note_version_atom AFTER INSERT ON public.scope_note_versions DEFERRABLE INITIALLY DEFERRED "
    "FOR EACH ROW EXECUTE FUNCTION public.require_scope_note_version()",
    "CREATE CONSTRAINT TRIGGER scope_note_evidence_atom AFTER INSERT ON public.scope_note_evidence DEFERRABLE INITIALLY DEFERRED "
    "FOR EACH ROW EXECUTE FUNCTION public.require_scope_note_link()",
    "CREATE CONSTRAINT TRIGGER scope_note_relation_atom AFTER INSERT ON public.scope_note_relations DEFERRABLE INITIALLY DEFERRED "
    "FOR EACH ROW EXECUTE FUNCTION public.require_scope_note_link()",
)

SCHEMA_SQL = (*TABLE_SQL, *SECURITY_SQL)

DOWNGRADE_SQL = (
    *(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY" for table in TABLES),
    """DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.scope_notes) THEN
     RAISE EXCEPTION 'Scope notes require s0_0891'; END IF; END $$""",
    "DROP TABLE public.scope_note_relations",
    "DROP TABLE public.scope_note_evidence",
    "DROP TABLE public.scope_note_versions",
    "DROP TABLE public.scope_notes",
    "DROP FUNCTION public.require_scope_note_link()",
    "DROP FUNCTION public.require_scope_note_version()",
    "DROP FUNCTION public.require_scope_note()",
    "DROP FUNCTION public.scope_note_readable(uuid,uuid)",
    "DROP FUNCTION public.scope_note_open(uuid,uuid,uuid,uuid,uuid)",
)
