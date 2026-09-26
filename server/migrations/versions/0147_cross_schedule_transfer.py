"""Atomic transfer of an approved dependency, preserving both history lineages."""

import sqlalchemy as sa
from alembic import op

revision = "0147_cross_schedule_transfer"
down_revision = "0146_cross_schedule_removal"
branch_labels = None
depends_on = None
NEW_SQL = (
    "CREATE OR REPLACE FUNCTION cehub_project.guard_cross_schedul"
    "e_application() RETURNS trigger LANGUAGE plpgsql SET search_"
    "path=pg_catalog AS $$\nDECLARE proposal cehub_project.cross_p"
    "roject_schedule_proposals%ROWTYPE; previous uuid; destinatio"
    "n uuid; displaced uuid; side text; pid uuid; latest uuid; po"
    "licy uuid;\nBEGIN\n SELECT * INTO proposal FROM cehub_project."
    "cross_project_schedule_proposals WHERE tenant_id=NEW.tenant_"
    "id AND id=NEW.proposal_id;\n IF proposal.id IS NULL OR propos"
    "al.predecessor_project_id IS DISTINCT FROM NEW.predecessor_p"
    "roject_id OR proposal.successor_project_id IS DISTINCT FROM "
    "NEW.successor_project_id OR proposal.predecessor_node_id IS "
    "DISTINCT FROM NEW.predecessor_node_id OR proposal.successor_"
    "node_id IS DISTINCT FROM NEW.successor_node_id OR proposal.r"
    "elation IS DISTINCT FROM NEW.relation OR proposal.payload_di"
    "gest IS DISTINCT FROM NEW.approved_payload_digest THEN RAISE"
    " EXCEPTION 'Application must match the exact bilateral appro"
    "ved relation' USING ERRCODE='23514'; END IF;\n PERFORM 1 FROM"
    " cehub_project.projects WHERE tenant_id=NEW.tenant_id AND id"
    " IN (NEW.predecessor_project_id,NEW.successor_project_id) OR"
    "DER BY id FOR UPDATE;\n PERFORM pg_advisory_xact_lock(hashtex"
    "textended('schedule-graph:'||NEW.tenant_id::text,0));\n IF (S"
    "ELECT count(*) FROM cehub_project.cross_project_schedule_dec"
    "isions WHERE tenant_id=NEW.tenant_id AND proposal_id=NEW.pro"
    "posal_id AND action='approve' AND approved_payload_digest=NE"
    "W.approved_payload_digest AND project_id IN (NEW.predecessor"
    "_project_id,NEW.successor_project_id))<>2 THEN RAISE EXCEPTI"
    "ON 'Both sides must approve before independent application' "
    "USING ERRCODE='23514'; END IF;\n FOREACH side IN ARRAY ARRAY["
    "'predecessor','successor'] LOOP\n  pid:=(to_jsonb(NEW)->>(sid"
    "e||'_project_id'))::uuid;\n  SELECT id INTO latest FROM cehub"
    "_project.schedule_time_records WHERE tenant_id=NEW.tenant_id"
    " AND project_id=pid AND time_kind='baseline' ORDER BY versio"
    "n DESC LIMIT 1;\n  SELECT id INTO policy FROM cehub_project.b"
    "aseline_change_policies WHERE tenant_id=NEW.tenant_id AND pr"
    "oject_id=pid ORDER BY version DESC LIMIT 1;\n  IF latest IS D"
    "ISTINCT FROM (to_jsonb(proposal)->>(side||'_baseline_id'))::"
    "uuid OR policy IS DISTINCT FROM (to_jsonb(proposal)->>(side|"
    "|'_policy_id'))::uuid THEN RAISE EXCEPTION 'Application requ"
    "ires both approved baselines and policies still current' USI"
    "NG ERRCODE='23514'; END IF;\n END LOOP;\n SELECT a.id INTO des"
    "tination FROM cehub_project.cross_project_schedule_applicati"
    "ons a WHERE a.tenant_id=NEW.tenant_id AND a.predecessor_node"
    "_id=NEW.predecessor_node_id AND a.successor_node_id=NEW.succ"
    "essor_node_id AND a.relation=NEW.relation AND NOT EXISTS(SEL"
    "ECT 1 FROM cehub_project.cross_project_schedule_applications"
    " newer WHERE newer.tenant_id=a.tenant_id AND (newer.replaces"
    "_application_id=a.id OR newer.displaces_application_id=a.id)"
    ");\n previous:=CASE WHEN NEW.operation='replace' THEN proposa"
    "l.target_application_id ELSE destination END;\n displaced:=CA"
    "SE WHEN NEW.operation='replace' AND destination IS DISTINCT "
    "FROM previous THEN destination ELSE NULL END;\n IF previous I"
    "S DISTINCT FROM NEW.replaces_application_id OR displaced IS "
    "DISTINCT FROM NEW.displaces_application_id OR displaced IS D"
    "ISTINCT FROM proposal.destination_application_id THEN RAISE "
    "EXCEPTION 'Atomic transfer must bind current source and dest"
    "ination history' USING ERRCODE='23514'; END IF;\n IF NEW.oper"
    "ation='replace' AND NOT EXISTS(SELECT 1 FROM cehub_project.c"
    "ross_project_schedule_applications a WHERE a.tenant_id=NEW.t"
    "enant_id AND a.id=previous AND a.operation<>'remove' AND NOT"
    " EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_a"
    "pplications n WHERE n.tenant_id=a.tenant_id AND (n.replaces_"
    "application_id=a.id OR n.displaces_application_id=a.id))) TH"
    "EN RAISE EXCEPTION 'Transfer source is no longer active' USI"
    "NG ERRCODE='23514'; END IF;\n IF displaced IS NOT NULL AND NO"
    "T EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_"
    "applications WHERE tenant_id=NEW.tenant_id AND id=displaced "
    "AND operation='remove') THEN RAISE EXCEPTION 'Transfer desti"
    "nation already has an active relation' USING ERRCODE='23514'"
    "; END IF;\n RETURN NEW;\nEND $$;\n\nCREATE OR REPLACE FUNCTION c"
    "ehub_project.guard_cross_schedule_operation() RETURNS trigge"
    "r LANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE "
    "target cehub_project.cross_project_schedule_applications%ROW"
    "TYPE; original cehub_project.cross_project_schedule_proposal"
    "s%ROWTYPE; destination uuid;\nBEGIN\n IF COALESCE(NEW.snapshot"
    "->>'operation','add') IS DISTINCT FROM NEW.operation OR (NEW"
    ".snapshot->>'target_application_id')::uuid IS DISTINCT FROM "
    "NEW.target_application_id OR (NEW.snapshot->>'destination_ap"
    "plication_id')::uuid IS DISTINCT FROM NEW.destination_applic"
    "ation_id THEN RAISE EXCEPTION 'Operation must match its revi"
    "ewed payload' USING ERRCODE='23514'; END IF;\n IF NEW.operati"
    "on<>'add' THEN\n  SELECT * INTO target FROM cehub_project.cro"
    "ss_project_schedule_applications WHERE tenant_id=NEW.tenant_"
    "id AND id=NEW.target_application_id;\n  SELECT * INTO origina"
    "l FROM cehub_project.cross_project_schedule_proposals WHERE "
    "tenant_id=NEW.tenant_id AND id=target.proposal_id;\n  IF targ"
    "et.id IS NULL OR target.operation='remove' OR target.predece"
    "ssor_project_id NOT IN (NEW.predecessor_project_id,NEW.succe"
    "ssor_project_id) OR target.successor_project_id NOT IN (NEW."
    "predecessor_project_id,NEW.successor_project_id) OR EXISTS(S"
    "ELECT 1 FROM cehub_project.cross_project_schedule_applicatio"
    "ns WHERE tenant_id=NEW.tenant_id AND (replaces_application_i"
    "d=target.id OR displaces_application_id=target.id)) THEN RAI"
    "SE EXCEPTION 'Transfer or removal requires the current relat"
    "ion between these projects' USING ERRCODE='23514'; END IF;\n "
    " IF NEW.operation='remove' AND (target.predecessor_node_id I"
    "S DISTINCT FROM NEW.predecessor_node_id OR target.successor_"
    "node_id IS DISTINCT FROM NEW.successor_node_id OR target.rel"
    "ation IS DISTINCT FROM NEW.relation OR original.lag IS DISTI"
    "NCT FROM NEW.lag OR original.lag_unit IS DISTINCT FROM NEW.l"
    "ag_unit) THEN RAISE EXCEPTION 'Removal must retain exact old"
    " conditions' USING ERRCODE='23514'; END IF;\n  IF NEW.operati"
    "on='replace' THEN\n   IF NEW.snapshot->'previous_relation'->>"
    "'application_id' IS DISTINCT FROM target.id::text THEN RAISE"
    " EXCEPTION 'Transfer review must identify the old applicatio"
    "n' USING ERRCODE='23514'; END IF;\n   SELECT a.id INTO destin"
    "ation FROM cehub_project.cross_project_schedule_applications"
    " a WHERE a.tenant_id=NEW.tenant_id AND a.id<>target.id AND a"
    ".predecessor_node_id=NEW.predecessor_node_id AND a.successor"
    "_node_id=NEW.successor_node_id AND a.relation=NEW.relation A"
    "ND NOT EXISTS(SELECT 1 FROM cehub_project.cross_project_sche"
    "dule_applications n WHERE n.tenant_id=a.tenant_id AND (n.rep"
    "laces_application_id=a.id OR n.displaces_application_id=a.id"
    "));\n   IF destination IS DISTINCT FROM NEW.destination_appli"
    "cation_id OR (destination IS NOT NULL AND NOT EXISTS(SELECT "
    "1 FROM cehub_project.cross_project_schedule_applications WHE"
    "RE tenant_id=NEW.tenant_id AND id=destination AND operation="
    "'remove')) THEN RAISE EXCEPTION 'Transfer destination must m"
    "atch its reviewed inactive history' USING ERRCODE='23514'; E"
    "ND IF;\n  END IF;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE OR REP"
    "LACE FUNCTION cehub_project.guard_cross_schedule_removal_dec"
    "ision() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_"
    "catalog AS $$\nDECLARE proposal cehub_project.cross_project_s"
    "chedule_proposals%ROWTYPE;\nBEGIN\n SELECT * INTO proposal FRO"
    "M cehub_project.cross_project_schedule_proposals WHERE tenan"
    "t_id=NEW.tenant_id AND id=NEW.proposal_id;\n IF NEW.action='a"
    "pprove' AND proposal.operation IN ('remove','replace') AND N"
    "OT EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule"
    "_applications a WHERE a.tenant_id=NEW.tenant_id AND a.id=pro"
    "posal.target_application_id AND a.operation<>'remove' AND NO"
    "T EXISTS(SELECT 1 FROM cehub_project.cross_project_schedule_"
    "applications n WHERE n.tenant_id=a.tenant_id AND (n.replaces"
    "_application_id=a.id OR n.displaces_application_id=a.id))) T"
    "HEN RAISE EXCEPTION 'Removal target changed before bilateral"
    " approval' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $"
    "$;\nCREATE OR REPLACE FUNCTION cehub_project.guard_cross_sche"
    "dule_application_operation() RETURNS trigger LANGUAGE plpgsq"
    "l SET search_path=pg_catalog AS $$\nDECLARE proposal cehub_pr"
    "oject.cross_project_schedule_proposals%ROWTYPE;\nBEGIN\n SELEC"
    "T * INTO proposal FROM cehub_project.cross_project_schedule_"
    "proposals WHERE tenant_id=NEW.tenant_id AND id=NEW.proposal_"
    "id;\n IF NEW.operation IS DISTINCT FROM proposal.operation OR"
    " (NEW.operation='remove' AND (NEW.replaces_application_id IS"
    " DISTINCT FROM proposal.target_application_id OR NOT EXISTS("
    "SELECT 1 FROM cehub_project.cross_project_schedule_applicati"
    "ons WHERE tenant_id=NEW.tenant_id AND id=NEW.replaces_applic"
    "ation_id AND operation<>'remove'))) THEN RAISE EXCEPTION 'Ap"
    "plied removal must preserve the exact approved target' USING"
    " ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\n"
)
OLD_SQL = (
    "CREATE OR REPLACE FUNCTION cehub_project.guard_cross_schedul"
    "e_application() RETURNS trigger LANGUAGE plpgsql SET search_"
    "path=pg_catalog AS $$\nDECLARE proposal cehub_project.cross_p"
    "roject_schedule_proposals%ROWTYPE; previous uuid; side text;"
    " pid uuid; latest uuid; policy uuid;\nBEGIN\n SELECT * INTO pr"
    "oposal FROM cehub_project.cross_project_schedule_proposals W"
    "HERE tenant_id=NEW.tenant_id AND id=NEW.proposal_id;\n IF pro"
    "posal.id IS NULL OR proposal.predecessor_project_id IS DISTI"
    "NCT FROM NEW.predecessor_project_id OR proposal.successor_pr"
    "oject_id IS DISTINCT FROM NEW.successor_project_id OR propos"
    "al.predecessor_node_id IS DISTINCT FROM NEW.predecessor_node"
    "_id OR proposal.successor_node_id IS DISTINCT FROM NEW.succe"
    "ssor_node_id OR proposal.relation IS DISTINCT FROM NEW.relat"
    "ion OR proposal.payload_digest IS DISTINCT FROM NEW.approved"
    "_payload_digest THEN RAISE EXCEPTION 'Application must match"
    " the exact bilateral approved relation' USING ERRCODE='23514"
    "'; END IF;\n PERFORM 1 FROM cehub_project.projects WHERE tena"
    "nt_id=NEW.tenant_id AND id IN (NEW.predecessor_project_id,NE"
    "W.successor_project_id) ORDER BY id FOR UPDATE;\n PERFORM pg_"
    "advisory_xact_lock(hashtextextended('schedule-graph:'||NEW.t"
    "enant_id::text,0));\n IF (SELECT count(*) FROM cehub_project."
    "cross_project_schedule_decisions WHERE tenant_id=NEW.tenant_"
    "id AND proposal_id=NEW.proposal_id AND action='approve' AND "
    "approved_payload_digest=NEW.approved_payload_digest AND proj"
    "ect_id IN (NEW.predecessor_project_id,NEW.successor_project_"
    "id))<>2 THEN RAISE EXCEPTION 'Both sides must approve before"
    " independent application' USING ERRCODE='23514'; END IF;\n FO"
    "REACH side IN ARRAY ARRAY['predecessor','successor'] LOOP\n  "
    "pid:=(to_jsonb(NEW)->>(side||'_project_id'))::uuid;\n  SELECT"
    " id INTO latest FROM cehub_project.schedule_time_records WHE"
    "RE tenant_id=NEW.tenant_id AND project_id=pid AND time_kind="
    "'baseline' ORDER BY version DESC LIMIT 1;\n  SELECT id INTO p"
    "olicy FROM cehub_project.baseline_change_policies WHERE tena"
    "nt_id=NEW.tenant_id AND project_id=pid ORDER BY version DESC"
    " LIMIT 1;\n  IF latest IS DISTINCT FROM (to_jsonb(proposal)->"
    ">(side||'_baseline_id'))::uuid OR policy IS DISTINCT FROM (t"
    "o_jsonb(proposal)->>(side||'_policy_id'))::uuid THEN RAISE E"
    "XCEPTION 'Application requires both approved baselines and p"
    "olicies still current' USING ERRCODE='23514'; END IF;\n END L"
    "OOP;\n SELECT a.id INTO previous FROM cehub_project.cross_pro"
    "ject_schedule_applications a WHERE a.tenant_id=NEW.tenant_id"
    " AND a.predecessor_node_id=NEW.predecessor_node_id AND a.suc"
    "cessor_node_id=NEW.successor_node_id AND a.relation=NEW.rela"
    "tion AND NOT EXISTS(SELECT 1 FROM cehub_project.cross_projec"
    "t_schedule_applications newer WHERE newer.tenant_id=a.tenant"
    "_id AND newer.replaces_application_id=a.id);\n IF previous IS"
    " DISTINCT FROM NEW.replaces_application_id THEN RAISE EXCEPT"
    "ION 'Relation replacement must bind the current application'"
    " USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $$;\n\n\nCREAT"
    "E OR REPLACE FUNCTION cehub_project.guard_cross_schedule_ope"
    "ration() RETURNS trigger LANGUAGE plpgsql SET search_path=pg"
    "_catalog AS $$\nDECLARE target cehub_project.cross_project_sc"
    "hedule_applications%ROWTYPE; original cehub_project.cross_pr"
    "oject_schedule_proposals%ROWTYPE;\nBEGIN\n IF COALESCE(NEW.sna"
    "pshot->>'operation','add') IS DISTINCT FROM NEW.operation OR"
    " (NEW.snapshot->>'target_application_id')::uuid IS DISTINCT "
    "FROM NEW.target_application_id THEN RAISE EXCEPTION 'Operati"
    "on must match the immutable reviewed payload' USING ERRCODE="
    "'23514'; END IF;\n IF NEW.operation='remove' THEN\n  SELECT * "
    "INTO target FROM cehub_project.cross_project_schedule_applic"
    "ations WHERE tenant_id=NEW.tenant_id AND id=NEW.target_appli"
    "cation_id;\n  SELECT * INTO original FROM cehub_project.cross"
    "_project_schedule_proposals WHERE tenant_id=NEW.tenant_id AN"
    "D id=target.proposal_id;\n  IF target.id IS NULL OR target.op"
    "eration<>'add' OR target.predecessor_project_id IS DISTINCT "
    "FROM NEW.predecessor_project_id OR target.successor_project_"
    "id IS DISTINCT FROM NEW.successor_project_id OR target.prede"
    "cessor_node_id IS DISTINCT FROM NEW.predecessor_node_id OR t"
    "arget.successor_node_id IS DISTINCT FROM NEW.successor_node_"
    "id OR target.relation IS DISTINCT FROM NEW.relation OR origi"
    "nal.lag IS DISTINCT FROM NEW.lag OR original.lag_unit IS DIS"
    "TINCT FROM NEW.lag_unit OR EXISTS(SELECT 1 FROM cehub_projec"
    "t.cross_project_schedule_applications WHERE tenant_id=NEW.te"
    "nant_id AND replaces_application_id=target.id) THEN RAISE EX"
    "CEPTION 'Removal must bind the current active relation and i"
    "ts exact conditions' USING ERRCODE='23514'; END IF;\n END IF;"
    "\n RETURN NEW;\nEND $$;\nCREATE OR REPLACE FUNCTION cehub_proje"
    "ct.guard_cross_schedule_removal_decision() RETURNS trigger L"
    "ANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE pro"
    "posal cehub_project.cross_project_schedule_proposals%ROWTYPE"
    ";\nBEGIN\n SELECT * INTO proposal FROM cehub_project.cross_pro"
    "ject_schedule_proposals WHERE tenant_id=NEW.tenant_id AND id"
    "=NEW.proposal_id;\n IF NEW.action='approve' AND proposal.oper"
    "ation='remove' AND NOT EXISTS(SELECT 1 FROM cehub_project.cr"
    "oss_project_schedule_applications a WHERE a.tenant_id=NEW.te"
    "nant_id AND a.id=proposal.target_application_id AND a.operat"
    "ion='add' AND NOT EXISTS(SELECT 1 FROM cehub_project.cross_p"
    "roject_schedule_applications n WHERE n.tenant_id=a.tenant_id"
    " AND n.replaces_application_id=a.id)) THEN RAISE EXCEPTION '"
    "Removal target changed before bilateral approval' USING ERRC"
    "ODE='23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE OR REPLACE "
    "FUNCTION cehub_project.guard_cross_schedule_application_oper"
    "ation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_"
    "catalog AS $$\nDECLARE proposal cehub_project.cross_project_s"
    "chedule_proposals%ROWTYPE;\nBEGIN\n SELECT * INTO proposal FRO"
    "M cehub_project.cross_project_schedule_proposals WHERE tenan"
    "t_id=NEW.tenant_id AND id=NEW.proposal_id;\n IF NEW.operation"
    " IS DISTINCT FROM proposal.operation OR (NEW.operation='remo"
    "ve' AND (NEW.replaces_application_id IS DISTINCT FROM propos"
    "al.target_application_id OR NOT EXISTS(SELECT 1 FROM cehub_p"
    "roject.cross_project_schedule_applications WHERE tenant_id=N"
    "EW.tenant_id AND id=NEW.replaces_application_id AND operatio"
    "n='add'))) THEN RAISE EXCEPTION 'Applied removal must preser"
    "ve the exact approved target' USING ERRCODE='23514'; END IF;"
    "\n RETURN NEW;\nEND $$;\n"
)


def set_checks(proposal: str, application: str) -> None:
    for table, suffix, value in (
        ("proposals", "proposal", proposal),
        ("applications", "application", application),
    ):
        name = op.f(f"ck_cross_project_schedule_{table}_cross_schedule_{suffix}_operation")
        op.drop_constraint(
            name, f"cross_project_schedule_{table}", schema="cehub_project", type_="check"
        )
        op.create_check_constraint(
            name, f"cross_project_schedule_{table}", value, schema="cehub_project"
        )


def upgrade() -> None:
    for table, column, name in (
        (
            "cross_project_schedule_proposals",
            "destination_application_id",
            "fk_cross_schedule_proposal_destination",
        ),
        (
            "cross_project_schedule_applications",
            "displaces_application_id",
            "fk_cross_schedule_application_destination",
        ),
    ):
        op.add_column(table, sa.Column(column, sa.Uuid()), schema="cehub_project")
        op.create_foreign_key(
            name,
            table,
            "cross_project_schedule_applications",
            ["tenant_id", column],
            ["tenant_id", "id"],
            source_schema="cehub_project",
            referent_schema="cehub_project",
            ondelete="RESTRICT",
        )
    op.create_unique_constraint(
        "uq_cross_schedule_displacement",
        "cross_project_schedule_applications",
        ["tenant_id", "displaces_application_id"],
        schema="cehub_project",
    )
    set_checks(
        (
            "((operation='add' AND target_application_id IS NULL) OR (ope"
            "ration IN ('remove','replace') AND target_application_id IS "
            "NOT NULL)) AND (operation='replace' OR destination_applicati"
            "on_id IS NULL)"
        ),
        (
            "operation IN ('add','remove','replace') AND (operation='add'"
            " OR replaces_application_id IS NOT NULL) AND (operation='rep"
            "lace' OR displaces_application_id IS NULL)"
        ),
    )
    op.execute(NEW_SQL)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.cross_project_sche"
                "dule_proposals WHERE operation='replace')"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard atomic transfer history")
    op.execute(OLD_SQL)
    set_checks(
        (
            "(operation='add' AND target_application_id IS NULL) OR (oper"
            "ation='remove' AND target_application_id IS NOT NULL)"
        ),
        (
            "operation IN ('add','remove') AND (operation<>'remove' OR re"
            "places_application_id IS NOT NULL)"
        ),
    )
    op.drop_constraint(
        "uq_cross_schedule_displacement",
        "cross_project_schedule_applications",
        schema="cehub_project",
        type_="unique",
    )
    for table, column, name in (
        (
            "cross_project_schedule_applications",
            "displaces_application_id",
            "fk_cross_schedule_application_destination",
        ),
        (
            "cross_project_schedule_proposals",
            "destination_application_id",
            "fk_cross_schedule_proposal_destination",
        ),
    ):
        op.drop_constraint(name, table, schema="cehub_project", type_="foreignkey")
        op.drop_column(table, column, schema="cehub_project")
