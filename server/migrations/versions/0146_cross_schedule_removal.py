"""Bilateral removal of an exact applied cross-project dependency."""

import sqlalchemy as sa
from alembic import op

revision = "0146_cross_schedule_removal"
down_revision = "0145_schedule_propagation"
branch_labels = None
depends_on = None

SQL = (
    "\nCREATE FUNCTION cehub_project.guard_cross_schedule_operatio"
    "n() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_cata"
    "log AS $$\nDECLARE target cehub_project.cross_project_schedul"
    "e_applications%ROWTYPE; original cehub_project.cross_project"
    "_schedule_proposals%ROWTYPE;\nBEGIN\n IF COALESCE(NEW.snapshot"
    "->>'operation','add') IS DISTINCT FROM NEW.operation OR (NEW"
    ".snapshot->>'target_application_id')::uuid IS DISTINCT FROM "
    "NEW.target_application_id THEN RAISE EXCEPTION 'Operation mu"
    "st match the immutable reviewed payload' USING ERRCODE='2351"
    "4'; END IF;\n IF NEW.operation='remove' THEN\n  SELECT * INTO "
    "target FROM cehub_project.cross_project_schedule_application"
    "s WHERE tenant_id=NEW.tenant_id AND id=NEW.target_applicatio"
    "n_id;\n  SELECT * INTO original FROM cehub_project.cross_proj"
    "ect_schedule_proposals WHERE tenant_id=NEW.tenant_id AND id="
    "target.proposal_id;\n  IF target.id IS NULL OR target.operati"
    "on<>'add' OR target.predecessor_project_id IS DISTINCT FROM "
    "NEW.predecessor_project_id OR target.successor_project_id IS"
    " DISTINCT FROM NEW.successor_project_id OR target.predecesso"
    "r_node_id IS DISTINCT FROM NEW.predecessor_node_id OR target"
    ".successor_node_id IS DISTINCT FROM NEW.successor_node_id OR"
    " target.relation IS DISTINCT FROM NEW.relation OR original.l"
    "ag IS DISTINCT FROM NEW.lag OR original.lag_unit IS DISTINCT"
    " FROM NEW.lag_unit OR EXISTS(SELECT 1 FROM cehub_project.cro"
    "ss_project_schedule_applications WHERE tenant_id=NEW.tenant_"
    "id AND replaces_application_id=target.id) THEN RAISE EXCEPTI"
    "ON 'Removal must bind the current active relation and its ex"
    "act conditions' USING ERRCODE='23514'; END IF;\n END IF;\n RET"
    "URN NEW;\nEND $$;\nCREATE FUNCTION cehub_project.guard_cross_s"
    "chedule_removal_decision() RETURNS trigger LANGUAGE plpgsql "
    "SET search_path=pg_catalog AS $$\nDECLARE proposal cehub_proj"
    "ect.cross_project_schedule_proposals%ROWTYPE;\nBEGIN\n SELECT "
    "* INTO proposal FROM cehub_project.cross_project_schedule_pr"
    "oposals WHERE tenant_id=NEW.tenant_id AND id=NEW.proposal_id"
    ";\n IF NEW.action='approve' AND proposal.operation='remove' A"
    "ND NOT EXISTS(SELECT 1 FROM cehub_project.cross_project_sche"
    "dule_applications a WHERE a.tenant_id=NEW.tenant_id AND a.id"
    "=proposal.target_application_id AND a.operation='add' AND NO"
    "T EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_"
    "applications n WHERE n.tenant_id=a.tenant_id AND n.replaces_"
    "application_id=a.id)) THEN RAISE EXCEPTION 'Removal target c"
    "hanged before bilateral approval' USING ERRCODE='23514'; END"
    " IF;\n RETURN NEW;\nEND $$;\nCREATE FUNCTION cehub_project.guar"
    "d_cross_schedule_application_operation() RETURNS trigger LAN"
    "GUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE propo"
    "sal cehub_project.cross_project_schedule_proposals%ROWTYPE;\n"
    "BEGIN\n SELECT * INTO proposal FROM cehub_project.cross_proje"
    "ct_schedule_proposals WHERE tenant_id=NEW.tenant_id AND id=N"
    "EW.proposal_id;\n IF NEW.operation IS DISTINCT FROM proposal."
    "operation OR (NEW.operation='remove' AND (NEW.replaces_appli"
    "cation_id IS DISTINCT FROM proposal.target_application_id OR"
    " NOT EXISTS(SELECT 1 FROM cehub_project.cross_project_schedu"
    "le_applications WHERE tenant_id=NEW.tenant_id AND id=NEW.rep"
    "laces_application_id AND operation='add'))) THEN RAISE EXCEP"
    "TION 'Applied removal must preserve the exact approved targe"
    "t' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREAT"
    "E TRIGGER guard_cross_schedule_operation BEFORE INSERT ON ce"
    "hub_project.cross_project_schedule_proposals FOR EACH ROW EX"
    "ECUTE FUNCTION cehub_project.guard_cross_schedule_operation("
    ");\nCREATE TRIGGER guard_cross_schedule_removal_decision BEFO"
    "RE INSERT ON cehub_project.cross_project_schedule_decisions "
    "FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_cross_sche"
    "dule_removal_decision();\nCREATE TRIGGER guard_cross_schedule"
    "_application_operation BEFORE INSERT ON cehub_project.cross_"
    "project_schedule_applications FOR EACH ROW EXECUTE FUNCTION "
    "cehub_project.guard_cross_schedule_application_operation();\n"
    "REVOKE ALL ON FUNCTION cehub_project.guard_cross_schedule_op"
    "eration(),cehub_project.guard_cross_schedule_removal_decisio"
    "n(),cehub_project.guard_cross_schedule_application_operation"
    "() FROM PUBLIC;\n"
)


def upgrade() -> None:
    for table in ("cross_project_schedule_proposals", "cross_project_schedule_applications"):
        op.add_column(
            table,
            sa.Column("operation", sa.String(16), nullable=False, server_default=sa.text("'add'")),
            schema="cehub_project",
        )
    op.add_column(
        "cross_project_schedule_proposals",
        sa.Column("target_application_id", sa.Uuid()),
        schema="cehub_project",
    )
    op.create_foreign_key(
        "fk_cross_schedule_removal_target",
        "cross_project_schedule_proposals",
        "cross_project_schedule_applications",
        ["tenant_id", "target_application_id"],
        ["tenant_id", "id"],
        source_schema="cehub_project",
        referent_schema="cehub_project",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_cross_project_schedule_proposals_cross_schedule_proposal_operation"),
        "cross_project_schedule_proposals",
        (
            "(operation='add' AND target_application_id IS NULL) OR (oper"
            "ation='remove' AND target_application_id IS NOT NULL)"
        ),
        schema="cehub_project",
    )
    op.create_check_constraint(
        op.f("ck_cross_project_schedule_applications_cross_schedule_application_operation"),
        "cross_project_schedule_applications",
        (
            "operation IN ('add','remove') AND (operation<>'remove' OR re"
            "places_application_id IS NOT NULL)"
        ),
        schema="cehub_project",
    )
    op.execute(SQL)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.cross_project_sche"
                "dule_proposals WHERE operation='remove')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard bilateral removal history")
    for table, name in (
        ("cross_project_schedule_applications", "guard_cross_schedule_application_operation"),
        ("cross_project_schedule_decisions", "guard_cross_schedule_removal_decision"),
        ("cross_project_schedule_proposals", "guard_cross_schedule_operation"),
    ):
        op.execute(f"DROP TRIGGER {name} ON cehub_project.{table}")
        op.execute(f"DROP FUNCTION cehub_project.{name}()")
    op.drop_constraint(
        op.f("ck_cross_project_schedule_applications_cross_schedule_application_operation"),
        "cross_project_schedule_applications",
        schema="cehub_project",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_cross_project_schedule_proposals_cross_schedule_proposal_operation"),
        "cross_project_schedule_proposals",
        schema="cehub_project",
        type_="check",
    )
    op.drop_constraint(
        "fk_cross_schedule_removal_target",
        "cross_project_schedule_proposals",
        schema="cehub_project",
        type_="foreignkey",
    )
    op.drop_column(
        "cross_project_schedule_proposals", "target_application_id", schema="cehub_project"
    )
    for table in ("cross_project_schedule_applications", "cross_project_schedule_proposals"):
        op.drop_column(table, "operation", schema="cehub_project")
