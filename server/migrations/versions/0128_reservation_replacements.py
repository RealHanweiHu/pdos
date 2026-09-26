"""Atomic resource reservation replacement history."""

import sqlalchemy as sa
from alembic import op

revision = "0128_reservation_replacements"
down_revision = "0127_schedule_commitments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.resource_reservation_replacement"
        "s (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_"
        "id UUID NOT NULL, \n\tprevious_reservation_id UUID NOT NULL, \n"
        "\treplacement_reservation_id UUID NOT NULL, \n\treason TEXT NOT"
        " NULL, \n\tsnapshot JSONB NOT NULL, \n\tactor_user_id UUID NOT N"
        "ULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64"
        ") NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CU"
        "RRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_resource_reservati"
        "on_replacements PRIMARY KEY (id), \n\tCONSTRAINT uq_resource_r"
        "eservation_replacements_previous UNIQUE (tenant_id, previous"
        "_reservation_id), \n\tCONSTRAINT uq_resource_reservation_repla"
        "cements_next UNIQUE (tenant_id, replacement_reservation_id),"
        " \n\tCONSTRAINT uq_resource_reservation_replacements_request U"
        "NIQUE (tenant_id, actor_user_id, request_id), \n\tCONSTRAINT f"
        "k_resource_reservation_replacements_previous FOREIGN KEY(ten"
        "ant_id, project_id, previous_reservation_id) REFERENCES cehu"
        "b_project.resource_reservations (tenant_id, project_id, id) "
        "ON DELETE RESTRICT, \n\tCONSTRAINT fk_resource_reservation_rep"
        "lacements_next FOREIGN KEY(tenant_id, project_id, replacemen"
        "t_reservation_id) REFERENCES cehub_project.resource_reservat"
        "ions (tenant_id, project_id, id) ON DELETE RESTRICT, \n\tCONST"
        "RAINT fk_resource_reservation_replacements_tenant_id_users F"
        "OREIGN KEY(tenant_id, actor_user_id) REFERENCES cehub_core.u"
        "sers (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_res"
        "ource_reservation_replacements_reservation_replac_d61b CHECK"
        " (previous_reservation_id<>replacement_reservation_id AND bt"
        "rim(reason)<>'')\n)\n\n"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_reservation_replacement("
        ") RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalo"
        "g AS $$\nBEGIN\n IF NOT EXISTS(SELECT 1 FROM cehub_project.res"
        "ource_reservations previous JOIN cehub_project.resource_rese"
        "rvations replacement ON replacement.tenant_id=previous.tenan"
        "t_id AND replacement.project_id=previous.project_id AND repl"
        "acement.node_id=previous.node_id AND replacement.owner_user_"
        "id=previous.owner_user_id WHERE previous.tenant_id=NEW.tenan"
        "t_id AND previous.project_id=NEW.project_id AND previous.id="
        "NEW.previous_reservation_id AND replacement.id=NEW.replaceme"
        "nt_reservation_id AND previous.state='released' AND replacem"
        "ent.state='reserved') OR NOT EXISTS(SELECT 1 FROM cehub_core"
        ".users WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_user_i"
        "d AND is_active AND role IN ('owner','admin')) THEN RAISE EX"
        "CEPTION 'Reservation replacement requires released old hold,"
        " confirmed new hold and actual administrator' USING ERRCODE="
        "'23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_r"
        "eservation_replacement BEFORE INSERT ON cehub_project.resour"
        "ce_reservation_replacements FOR EACH ROW EXECUTE FUNCTION ce"
        "hub_project.guard_reservation_replacement();\nCREATE TRIGGER "
        "protect_capacity_history BEFORE UPDATE OR DELETE ON cehub_pr"
        "oject.resource_reservation_replacements FOR EACH ROW EXECUTE"
        " FUNCTION cehub_project.protect_capacity_history();\nREVOKE A"
        "LL ON FUNCTION cehub_project.guard_reservation_replacement()"
        " FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS(SELECT 1 FROM cehub_project.resource_reservation_replacements)")
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard reservation replacement evidence")
    op.drop_table("resource_reservation_replacements", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_reservation_replacement()")
