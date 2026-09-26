"""Explicit recertification lineage, preserving prior certificates and their evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0141_recertification_lineage"
down_revision = "0140_certification_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE cehub_quality.certifications ADD COLUMN replaces_certification_id UUID")
    op.execute("ALTER TABLE cehub_quality.certifications ADD COLUMN recertification_reason TEXT")
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD COLUMN recertification_request_id UUID"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD COLUMN recertif"
        "ication_request_digest VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD COLUMN recertif"
        "ication_source_digest VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD CONSTRAINT uq_c"
        "ertification_recertification_request UNIQUE (tenant_id, crea"
        "ted_by_user_id, recertification_request_id)"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD CONSTRAINT fk_c"
        "ertification_previous FOREIGN KEY(tenant_id, project_id, rep"
        "laces_certification_id) REFERENCES cehub_quality.certificati"
        "ons (tenant_id, project_id, id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications ADD CONSTRAINT ck_c"
        "ertifications_recertification_provenance CHECK ((replaces_ce"
        "rtification_id IS NULL AND recertification_reason IS NULL AN"
        "D recertification_request_id IS NULL AND recertification_req"
        "uest_digest IS NULL AND recertification_source_digest IS NUL"
        "L) OR (replaces_certification_id IS NOT NULL AND replaces_ce"
        "rtification_id<>id AND recertification_reason IS NOT NULL AN"
        "D length(btrim(recertification_reason))>0 AND recertificatio"
        "n_request_id IS NOT NULL AND recertification_request_digest "
        "IS NOT NULL AND recertification_source_digest IS NOT NULL))"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_recertification_provenan"
        "ce() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\nBEGIN\n IF TG_OP='UPDATE' THEN\n  IF (NEW.replaces_"
        "certification_id,NEW.recertification_reason,NEW.recertificat"
        "ion_request_id,NEW.recertification_request_digest,NEW.recert"
        "ification_source_digest) IS DISTINCT FROM (OLD.replaces_cert"
        "ification_id,OLD.recertification_reason,OLD.recertification_"
        "request_id,OLD.recertification_request_digest,OLD.recertific"
        "ation_source_digest) THEN RAISE EXCEPTION 'Recertification p"
        "rovenance is immutable' USING ERRCODE='23514'; END IF;\n ELSI"
        "F NEW.replaces_certification_id IS NOT NULL THEN\n  IF NEW.st"
        "atus<>'draft' OR NEW.certificate_number IS NOT NULL OR NEW.v"
        "alid_from IS NOT NULL OR NEW.valid_until IS NOT NULL OR NEW."
        "evidence_reference IS NOT NULL OR NOT EXISTS(SELECT 1 FROM c"
        "ehub_quality.certifications old WHERE old.tenant_id=NEW.tena"
        "nt_id AND old.project_id=NEW.project_id AND old.id=NEW.repla"
        "ces_certification_id AND old.status<>'draft' AND old.certifi"
        "cate_type=NEW.certificate_type AND old.target_markets=NEW.ta"
        "rget_markets AND old.is_required=NEW.is_required) THEN RAISE"
        " EXCEPTION 'Recertification must start as a fresh scoped wor"
        "k record linked to the prior certificate' USING ERRCODE='235"
        "14'; END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER gu"
        "ard_recertification_provenance BEFORE INSERT OR UPDATE ON ce"
        "hub_quality.certifications FOR EACH ROW EXECUTE FUNCTION ceh"
        "ub_project.guard_recertification_provenance();\nCREATE FUNCTI"
        "ON cehub_project.check_recertification_audit() RETURNS trigg"
        "er LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nBEGIN\n "
        "IF NEW.replaces_certification_id IS NOT NULL AND NOT EXISTS("
        "SELECT 1 FROM cehub_audit.audit_log a JOIN cehub_event.event"
        "s e ON e.tenant_id=a.tenant_id AND e.project_id=a.project_id"
        " AND e.event_id=a.event_id AND e.entity_id=a.entity_id WHERE"
        " a.tenant_id=NEW.tenant_id AND a.project_id=NEW.project_id A"
        "ND a.entity_id=NEW.id AND a.actor_user_id=NEW.created_by_use"
        "r_id AND a.action='npi.certification.recertification_created"
        "' AND e.event_type='NPI_RECORD_CHANGED' AND e.source='npi_se"
        "rvice' AND a.after_snapshot->>'replaces_certification_id'=NE"
        "W.replaces_certification_id::text AND a.after_snapshot->>'re"
        "certification_reason'=NEW.recertification_reason AND a.after"
        "_snapshot->>'recertification_source_digest'=NEW.recertificat"
        "ion_source_digest AND a.after_snapshot->>'recertification_re"
        "quest_id'=NEW.recertification_request_id::text) THEN RAISE E"
        "XCEPTION 'Recertification creation must preserve its source "
        "and reason in the audit chain' USING ERRCODE='23514'; END IF"
        ";\n RETURN NEW;\nEND $$;\nCREATE CONSTRAINT TRIGGER check_recer"
        "tification_audit AFTER INSERT ON cehub_quality.certification"
        "s DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTIO"
        "N cehub_project.check_recertification_audit();\nREVOKE ALL ON"
        " FUNCTION cehub_project.guard_recertification_provenance(),c"
        "ehub_project.check_recertification_audit() FROM PUBLIC;\n"
    )

    op.execute(
        "CREATE FUNCTION cehub_project.guard_scenario_recertification"
        "() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catal"
        "og AS $$\nDECLARE replacement jsonb; choices jsonb;\nBEGIN\n ch"
        "oices := COALESCE(NEW.inputs->'certification_replacements','"
        "[]'::jsonb);\n FOR replacement IN SELECT * FROM jsonb_array_e"
        "lements(choices) LOOP\n  IF NOT EXISTS(\n   SELECT 1 FROM cehu"
        "b_project.schedule_nodes old\n   JOIN cehub_project.schedule_"
        "nodes next ON next.tenant_id=old.tenant_id AND next.project_"
        "id=old.project_id\n   JOIN cehub_quality.certifications certi"
        "ficate ON certificate.tenant_id=next.tenant_id AND certifica"
        "te.project_id=next.project_id AND certificate.id=next.certif"
        "ication_id\n   JOIN cehub_project.schedule_time_nodes baselin"
        "e ON baseline.tenant_id=old.tenant_id AND baseline.project_i"
        "d=old.project_id AND baseline.node_id=old.id AND baseline.re"
        "cord_id=NEW.baseline_id\n   WHERE old.tenant_id=NEW.tenant_id"
        " AND old.project_id=NEW.project_id AND old.id::text=replacem"
        "ent->>'previous_node_id' AND next.id::text=replacement->>'re"
        "placement_node_id' AND old.node_kind='certification' AND nex"
        "t.node_kind='certification' AND certificate.replaces_certifi"
        "cation_id=old.certification_id\n    AND EXISTS(SELECT 1 FROM "
        "jsonb_array_elements(NEW.result->'nodes') n WHERE n->>'node_"
        "id'=next.id::text)\n    AND NOT EXISTS(SELECT 1 FROM jsonb_ar"
        "ray_elements(NEW.result->'nodes') n WHERE n->>'node_id'=old."
        "id::text)\n  ) THEN RAISE EXCEPTION 'Scenario replacement mus"
        "t retain actual recertification lineage and current baseline"
        " membership' USING ERRCODE='23514'; END IF;\n END LOOP;\n IF E"
        "XISTS(SELECT 1 FROM cehub_project.schedule_time_nodes old WH"
        "ERE old.tenant_id=NEW.tenant_id AND old.project_id=NEW.proje"
        "ct_id AND old.record_id=NEW.baseline_id AND NOT EXISTS(SELEC"
        "T 1 FROM jsonb_array_elements(NEW.result->'nodes') n WHERE n"
        "->>'node_id'=old.node_id::text) AND NOT EXISTS(SELECT 1 FROM"
        " jsonb_array_elements(choices) r WHERE r->>'previous_node_id"
        "'=old.node_id::text)) THEN RAISE EXCEPTION 'Existing plan no"
        "des cannot disappear without an explicit supported replaceme"
        "nt' USING ERRCODE='23514'; END IF;\n IF EXISTS(\n  SELECT 1 FR"
        "OM cehub_project.schedule_plan_dependencies e\n  WHERE e.tena"
        "nt_id=NEW.tenant_id AND e.project_id=NEW.project_id AND e.ba"
        "seline_id=NEW.baseline_id\n   AND EXISTS(SELECT 1 FROM jsonb_"
        "array_elements(choices) r WHERE r->>'previous_node_id' IN (e"
        ".predecessor_node_id::text,e.successor_node_id::text))\n   AN"
        "D NOT EXISTS(\n    SELECT 1 FROM jsonb_array_elements(NEW.inp"
        "uts->'dependencies') proposed\n    WHERE proposed->>'predeces"
        "sor_node_id'=COALESCE((SELECT r->>'replacement_node_id' FROM"
        " jsonb_array_elements(choices) r WHERE r->>'previous_node_id"
        "'=e.predecessor_node_id::text),e.predecessor_node_id::text)\n"
        "      AND proposed->>'successor_node_id'=COALESCE((SELECT r-"
        ">>'replacement_node_id' FROM jsonb_array_elements(choices) r"
        " WHERE r->>'previous_node_id'=e.successor_node_id::text),e.s"
        "uccessor_node_id::text)\n      AND proposed->>'relation'=e.re"
        "lation AND (proposed->>'lag')::numeric=e.lag AND proposed->>"
        "'lag_unit'=e.lag_unit\n   )\n ) THEN RAISE EXCEPTION 'Recertif"
        "ication must transfer every previous scheduling constraint' "
        "USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE T"
        "RIGGER guard_scenario_recertification BEFORE INSERT ON cehub"
        "_project.project_schedule_scenarios FOR EACH ROW EXECUTE FUN"
        "CTION cehub_project.guard_scenario_recertification();\nREVOKE"
        " ALL ON FUNCTION cehub_project.guard_scenario_recertificatio"
        "n() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_quality.certifications WHE"
                "RE replaces_certification_id IS NOT NULL)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard recertification lineage")
    op.execute(
        "DROP TRIGGER guard_scenario_recertification ON cehub_project.project_schedule_scenarios"
    )
    op.execute("DROP FUNCTION cehub_project.guard_scenario_recertification()")
    op.execute("DROP TRIGGER check_recertification_audit ON cehub_quality.certifications")
    op.execute("DROP TRIGGER guard_recertification_provenance ON cehub_quality.certifications")
    op.execute(
        "DROP FUNCTION cehub_project.guard_recertification_provenance"
        "(),cehub_project.check_recertification_audit()"
    )
    op.execute(
        "ALTER TABLE cehub_quality.certifications DROP CONSTRAINT uq_"
        "certification_recertification_request"
    )
    op.execute("ALTER TABLE cehub_quality.certifications DROP CONSTRAINT fk_certification_previous")
    op.execute(
        "ALTER TABLE cehub_quality.certifications DROP CONSTRAINT ck_"
        "certifications_recertification_provenance"
    )
    op.drop_column("certifications", "recertification_source_digest", schema="cehub_quality")
    op.drop_column("certifications", "recertification_request_digest", schema="cehub_quality")
    op.drop_column("certifications", "recertification_request_id", schema="cehub_quality")
    op.drop_column("certifications", "recertification_reason", schema="cehub_quality")
    op.drop_column("certifications", "replaces_certification_id", schema="cehub_quality")
