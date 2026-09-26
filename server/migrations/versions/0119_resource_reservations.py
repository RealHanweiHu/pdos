"""Project task reservations with serialized shared capacity consumption."""

import sqlalchemy as sa
from alembic import op

revision = "0119_resource_reservations"
down_revision = "0118_resource_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_project.schedule_nodes (\n\tid UUID NOT NU"
        "LL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT NULL, \n"
        "\ttask_id UUID NOT NULL, \n\tcalendar_version_id UUID NOT NULL,"
        " \n\tcontract JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME"
        " ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_sc"
        "hedule_nodes PRIMARY KEY (id), \n\tCONSTRAINT uq_schedule_node"
        "s_project UNIQUE (tenant_id, project_id, id), \n\tCONSTRAINT u"
        "q_schedule_nodes_task UNIQUE (tenant_id, task_id), \n\tCONSTRA"
        "INT fk_schedule_nodes_tenant_id_tasks FOREIGN KEY(tenant_id,"
        " project_id, task_id) REFERENCES cehub_project.tasks (tenant"
        "_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_sch"
        "edule_nodes_tenant_id_work_calendar_versions FOREIGN KEY(ten"
        "ant_id, calendar_version_id) REFERENCES cehub_project.work_c"
        "alendar_versions (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.resource_capacity_intervals (\n\tt"
        "enant_id UUID NOT NULL, \n\tcapacity_version_id UUID NOT NULL,"
        ' \n\tstart TIMESTAMP WITH TIME ZONE NOT NULL, \n\t"end" TIMESTAM'
        "P WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_resource_capacity"
        "_intervals PRIMARY KEY (tenant_id, capacity_version_id, star"
        "t), \n\tCONSTRAINT fk_resource_capacity_intervals_tenant_id_re"
        "source_capac_0783 FOREIGN KEY(tenant_id, capacity_version_id"
        ") REFERENCES cehub_project.resource_capacity_versions (tenan"
        "t_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_resource_capac"
        'ity_intervals_capacity_interval_positive CHECK ("end">start)'
        "\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.resource_reservations (\n\tid UUID"
        " NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id UUID NOT "
        "NULL, \n\tnode_id UUID NOT NULL, \n\tresource_id UUID NOT NULL, "
        "\n\tcapacity_version_id UUID NOT NULL, \n\towner_user_id UUID NO"
        "T NULL, \n\tcreated_by_user_id UUID NOT NULL, \n\twindow_start T"
        "IMESTAMP WITH TIME ZONE NOT NULL, \n\twindow_end TIMESTAMP WIT"
        "H TIME ZONE NOT NULL, \n\tparallel_units NUMERIC(24, 8) NOT NU"
        "LL, \n\toccupancy_policy VARCHAR(24) NOT NULL, \n\tbasis TEXT NO"
        "T NULL, \n\tversion INTEGER NOT NULL, \n\tstate VARCHAR(16) NOT "
        "NULL, \n\tcontract JSONB NOT NULL, \n\tcreated_at TIMESTAMP WITH"
        " TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at "
        "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,"
        " \n\tCONSTRAINT pk_resource_reservations PRIMARY KEY (id), \n\tC"
        "ONSTRAINT uq_resource_reservations_scope UNIQUE (tenant_id, "
        "id), \n\tCONSTRAINT uq_resource_reservations_project UNIQUE (t"
        "enant_id, project_id, id), \n\tCONSTRAINT fk_resource_reservat"
        "ions_tenant_id_schedule_nodes FOREIGN KEY(tenant_id, project"
        "_id, node_id) REFERENCES cehub_project.schedule_nodes (tenan"
        "t_id, project_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_re"
        "source_reservations_tenant_id_planning_resources FOREIGN KEY"
        "(tenant_id, resource_id) REFERENCES cehub_project.planning_r"
        "esources (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk"
        "_resource_reservations_tenant_id_resource_capacity_versions "
        "FOREIGN KEY(tenant_id, capacity_version_id) REFERENCES cehub"
        "_project.resource_capacity_versions (tenant_id, id) ON DELET"
        "E RESTRICT, \n\tCONSTRAINT fk_resource_reservations_tenant_id_"
        "users FOREIGN KEY(tenant_id, owner_user_id) REFERENCES cehub"
        "_core.users (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT"
        " fk_resource_reservations_created_by_user_id_users FOREIGN K"
        "EY(tenant_id, created_by_user_id) REFERENCES cehub_core.user"
        "s (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT ck_resour"
        "ce_reservations_resource_reservation_valid CHECK (version>0 "
        "AND window_end>window_start AND parallel_units>0 AND paralle"
        "l_units<=1000 AND state IN ('proposed','reserved','released'"
        ",'cancelled') AND occupancy_policy IN ('working_only','throu"
        "gh_waiting') AND btrim(basis)<>'')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE cehub_project.resource_reservation_intervals ("
        "\n\ttenant_id UUID NOT NULL, \n\treservation_id UUID NOT NULL, \n"
        '\tstart TIMESTAMP WITH TIME ZONE NOT NULL, \n\t"end" TIMESTAMP '
        "WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_resource_reservatio"
        "n_intervals PRIMARY KEY (tenant_id, reservation_id, start), "
        "\n\tCONSTRAINT fk_resource_reservation_intervals_tenant_id_res"
        "ource_re_25c8 FOREIGN KEY(tenant_id, reservation_id) REFEREN"
        "CES cehub_project.resource_reservations (tenant_id, id) ON D"
        "ELETE RESTRICT, \n\tCONSTRAINT ck_resource_reservation_interva"
        'ls_reservation_interval_positive CHECK ("end">start)\n)\n\n'
    )
    op.execute(
        "\nCREATE TABLE cehub_project.resource_reservation_receipts (\n"
        "\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tproject_id U"
        "UID NOT NULL, \n\treservation_id UUID NOT NULL, \n\tactor_user_i"
        "d UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_diges"
        "t VARCHAR(64) NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\treason "
        "TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT"
        " CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_resource_reserv"
        "ation_receipts PRIMARY KEY (id), \n\tCONSTRAINT uq_resource_re"
        "servation_receipt_request UNIQUE (tenant_id, project_id, act"
        "or_user_id, request_id), \n\tCONSTRAINT fk_resource_reservatio"
        "n_receipts_tenant_id_resource_res_4fdc FOREIGN KEY(tenant_id"
        ", project_id, reservation_id) REFERENCES cehub_project.resou"
        "rce_reservations (tenant_id, project_id, id) ON DELETE RESTR"
        "ICT, \n\tCONSTRAINT fk_resource_reservation_receipts_tenant_id"
        "_users FOREIGN KEY(tenant_id, actor_user_id) REFERENCES cehu"
        "b_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_resource_reservations_active ON cehub_projec"
        "t.resource_reservations (tenant_id, resource_id, state)"
    )
    op.execute(
        "CREATE FUNCTION cehub_project.guard_resource_reservation() R"
        "ETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog A"
        "S $$\nDECLARE cap cehub_project.resource_capacity_versions%RO"
        "WTYPE; span record; point timestamptz; used numeric; availab"
        "le numeric; covered numeric;\nBEGIN\n IF TG_OP='DELETE' THEN R"
        "AISE EXCEPTION 'Reservation history cannot be deleted' USING"
        " ERRCODE='42501'; END IF;\n PERFORM 1 FROM cehub_project.plan"
        "ning_resources WHERE tenant_id=NEW.tenant_id AND id=NEW.reso"
        "urce_id FOR UPDATE;\n SELECT * INTO cap FROM cehub_project.re"
        "source_capacity_versions WHERE tenant_id=NEW.tenant_id AND i"
        "d=NEW.capacity_version_id;\n IF cap.resource_id IS DISTINCT F"
        "ROM NEW.resource_id THEN RAISE EXCEPTION 'Capacity resource "
        "mismatch' USING ERRCODE='23514'; END IF;\n IF TG_OP='INSERT' "
        "AND (NEW.state<>'proposed' OR NEW.version<>1) THEN RAISE EXC"
        "EPTION 'Reservation must start as proposed' USING ERRCODE='2"
        "3514'; END IF;\n IF TG_OP='UPDATE' THEN\n  IF (to_jsonb(NEW)-A"
        "RRAY['state','version','contract','updated_at']) IS DISTINCT"
        " FROM (to_jsonb(OLD)-ARRAY['state','version','contract','upd"
        "ated_at']) OR NEW.version<>OLD.version+1 OR NOT ((OLD.state="
        "'proposed' AND NEW.state IN ('reserved','cancelled')) OR (OL"
        "D.state='reserved' AND NEW.state IN ('released','cancelled')"
        ")) THEN\n   RAISE EXCEPTION 'Invalid reservation transition' "
        "USING ERRCODE='23514';\n  END IF;\n END IF;\n IF NEW.contract->"
        ">'id' IS DISTINCT FROM NEW.id::text OR NEW.contract->>'tenan"
        "t_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW.contract->"
        ">'project_id' IS DISTINCT FROM NEW.project_id::text OR NEW.c"
        "ontract->>'node_id' IS DISTINCT FROM NEW.node_id::text OR NE"
        "W.contract->>'resource_id' IS DISTINCT FROM NEW.resource_id:"
        ":text OR NEW.contract->>'state' IS DISTINCT FROM NEW.state O"
        "R (NEW.contract->>'version')::integer IS DISTINCT FROM NEW.v"
        "ersion THEN RAISE EXCEPTION 'Reservation contract mismatch' "
        "USING ERRCODE='23514'; END IF;\n IF NEW.state='reserved' THEN"
        "\n  IF EXISTS(SELECT 1 FROM cehub_project.resource_capacity_v"
        "ersions WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.re"
        "source_id AND version>cap.version) THEN RAISE EXCEPTION 'Cap"
        "acity version changed' USING ERRCODE='23514'; END IF;\n  IF N"
        "OT EXISTS(SELECT 1 FROM cehub_project.projects WHERE tenant_"
        "id=NEW.tenant_id AND id=NEW.project_id AND status IN ('appro"
        "ved','active')) THEN RAISE EXCEPTION 'Project execution appr"
        "oval is required' USING ERRCODE='23514'; END IF;\n  IF NOT EX"
        "ISTS(SELECT 1 FROM cehub_project.resource_reservation_interv"
        "als WHERE tenant_id=NEW.tenant_id AND reservation_id=NEW.id)"
        " THEN RAISE EXCEPTION 'Reservation has no occupied intervals"
        "' USING ERRCODE='23514'; END IF;\n  IF NEW.contract->'approva"
        "l' IS NULL OR NEW.contract->'approval'='null'::jsonb OR NEW."
        "contract->>'reservation_receipt_id' IS NULL OR NEW.contract-"
        ">>'reserved_at' IS NULL THEN RAISE EXCEPTION 'Reservation ap"
        "proval evidence required' USING ERRCODE='23514'; END IF;\n  F"
        'OR span IN SELECT start,"end" FROM cehub_project.resource_re'
        "servation_intervals WHERE tenant_id=NEW.tenant_id AND reserv"
        "ation_id=NEW.id LOOP\n   SELECT COALESCE(SUM(EXTRACT(EPOCH FR"
        'OM LEAST(i."end",span."end")-GREATEST(i.start,span.start))),'
        "0) INTO covered FROM cehub_project.resource_capacity_interva"
        "ls i WHERE i.tenant_id=NEW.tenant_id AND i.capacity_version_"
        'id=cap.id AND i.start<span."end" AND i."end">span.start;\n   '
        'IF covered<>EXTRACT(EPOCH FROM span."end"-span.start) THEN R'
        "AISE EXCEPTION 'Reservation exceeds declared availability' U"
        "SING ERRCODE='23514'; END IF;\n   FOR point IN SELECT span.st"
        "art UNION SELECT i.start FROM cehub_project.resource_reserva"
        "tion_intervals i JOIN cehub_project.resource_reservations r "
        "ON r.tenant_id=i.tenant_id AND r.id=i.reservation_id WHERE r"
        ".tenant_id=NEW.tenant_id AND r.resource_id=NEW.resource_id A"
        "ND r.state='reserved' AND r.id<>NEW.id AND i.start>=span.sta"
        'rt AND i.start<span."end" LOOP\n    SELECT COALESCE(SUM(r.par'
        "allel_units),0) INTO used FROM cehub_project.resource_reserv"
        "ation_intervals i JOIN cehub_project.resource_reservations r"
        " ON r.tenant_id=i.tenant_id AND r.id=i.reservation_id WHERE "
        "r.tenant_id=NEW.tenant_id AND r.resource_id=NEW.resource_id "
        "AND r.state='reserved' AND r.id<>NEW.id AND i.start<=point A"
        'ND i."end">point;\n    IF used+NEW.parallel_units>cap.paralle'
        "l_units THEN RAISE EXCEPTION 'Resource capacity is already o"
        "ccupied' USING ERRCODE='23514'; END IF;\n   END LOOP;\n  END L"
        "OOP;\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_reso"
        "urce_reservation BEFORE INSERT OR UPDATE OR DELETE ON cehub_"
        "project.resource_reservations FOR EACH ROW EXECUTE FUNCTION "
        "cehub_project.guard_resource_reservation();\nCREATE FUNCTION "
        "cehub_project.guard_reservation_interval() RETURNS trigger L"
        "ANGUAGE plpgsql SET search_path=pg_catalog AS $$\nDECLARE par"
        "ent cehub_project.resource_reservations%ROWTYPE;\nBEGIN\n SELE"
        "CT * INTO parent FROM cehub_project.resource_reservations WH"
        "ERE tenant_id=NEW.tenant_id AND id=NEW.reservation_id FOR UP"
        "DATE;\n IF parent.state IS DISTINCT FROM 'proposed' OR NEW.st"
        'art<parent.window_start OR NEW."end">parent.window_end OR EX'
        "ISTS(SELECT 1 FROM cehub_project.resource_reservation_interv"
        "als WHERE tenant_id=NEW.tenant_id AND reservation_id=NEW.res"
        'ervation_id AND start<NEW."end" AND "end">NEW.start) THEN RA'
        "ISE EXCEPTION 'Invalid reservation interval' USING ERRCODE='"
        "23514'; END IF;\n RETURN NEW;\nEND $$;\nCREATE TRIGGER guard_re"
        "servation_interval BEFORE INSERT ON cehub_project.resource_r"
        "eservation_intervals FOR EACH ROW EXECUTE FUNCTION cehub_pro"
        "ject.guard_reservation_interval();\nCREATE FUNCTION cehub_pro"
        "ject.guard_capacity_interval() RETURNS trigger LANGUAGE plpg"
        "sql SET search_path=pg_catalog AS $$\nDECLARE parent cehub_pr"
        "oject.resource_capacity_versions%ROWTYPE;\nBEGIN\n SELECT * IN"
        "TO parent FROM cehub_project.resource_capacity_versions WHER"
        "E tenant_id=NEW.tenant_id AND id=NEW.capacity_version_id FOR"
        " UPDATE;\n IF parent.id IS NULL OR NEW.start<parent.window_st"
        'art OR NEW."end">parent.window_end OR EXISTS(SELECT 1 FROM c'
        "ehub_project.resource_capacity_intervals WHERE tenant_id=NEW"
        ".tenant_id AND capacity_version_id=NEW.capacity_version_id A"
        'ND start<NEW."end" AND "end">NEW.start) OR EXISTS(SELECT 1 F'
        "ROM cehub_project.resource_reservations WHERE tenant_id=NEW."
        "tenant_id AND capacity_version_id=NEW.capacity_version_id) T"
        "HEN RAISE EXCEPTION 'Invalid or already referenced capacity "
        "intervals' USING ERRCODE='23514'; END IF;\n RETURN NEW;\nEND $"
        "$;\nCREATE TRIGGER guard_capacity_interval BEFORE INSERT ON c"
        "ehub_project.resource_capacity_intervals FOR EACH ROW EXECUT"
        "E FUNCTION cehub_project.guard_capacity_interval();\nCREATE F"
        "UNCTION cehub_project.guard_reserved_capacity_revision() RET"
        "URNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS "
        "$$\nBEGIN\n PERFORM 1 FROM cehub_project.planning_resources WH"
        "ERE tenant_id=NEW.tenant_id AND id=NEW.resource_id FOR UPDAT"
        "E;\n IF EXISTS(SELECT 1 FROM cehub_project.resource_reservati"
        "ons WHERE tenant_id=NEW.tenant_id AND resource_id=NEW.resour"
        "ce_id AND state='reserved' AND window_end>CURRENT_TIMESTAMP)"
        " THEN RAISE EXCEPTION 'Release affected future reservations "
        "before changing capacity' USING ERRCODE='23514'; END IF;\n RE"
        "TURN NEW;\nEND $$;\nCREATE TRIGGER guard_reserved_capacity_rev"
        "ision BEFORE INSERT ON cehub_project.resource_capacity_versi"
        "ons FOR EACH ROW EXECUTE FUNCTION cehub_project.guard_reserv"
        "ed_capacity_revision();\nREVOKE ALL ON FUNCTION cehub_project"
        ".guard_resource_reservation(),cehub_project.guard_reservatio"
        "n_interval(),cehub_project.guard_capacity_interval(),cehub_p"
        "roject.guard_reserved_capacity_revision() FROM PUBLIC;\n"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.schedule_nodes FOR EACH ROW EXECUTE FUN"
        "CTION cehub_project.protect_capacity_history()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.resource_capacity_intervals FOR EACH RO"
        "W EXECUTE FUNCTION cehub_project.protect_capacity_history()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.resource_reservation_intervals FOR EACH"
        " ROW EXECUTE FUNCTION cehub_project.protect_capacity_history"
        "()"
    )
    op.execute(
        "CREATE TRIGGER protect_capacity_history BEFORE UPDATE OR DEL"
        "ETE ON cehub_project.resource_reservation_receipts FOR EACH "
        "ROW EXECUTE FUNCTION cehub_project.protect_capacity_history("
        ")"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM cehub_project.resource_reservati"
                "ons) OR EXISTS(SELECT 1 FROM cehub_project.schedule_nodes)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard reservation or schedule identity evidence")
    op.execute(
        "DROP TRIGGER guard_reserved_capacity_revision ON cehub_project.resource_capacity_versions"
    )
    op.drop_table("resource_reservation_receipts", schema="cehub_project")
    op.drop_table("resource_reservation_intervals", schema="cehub_project")
    op.drop_table("resource_reservations", schema="cehub_project")
    op.drop_table("resource_capacity_intervals", schema="cehub_project")
    op.drop_table("schedule_nodes", schema="cehub_project")
    op.execute("DROP FUNCTION cehub_project.guard_resource_reservation()")
    op.execute("DROP FUNCTION cehub_project.guard_reservation_interval()")
    op.execute("DROP FUNCTION cehub_project.guard_capacity_interval()")
    op.execute("DROP FUNCTION cehub_project.guard_reserved_capacity_revision()")
