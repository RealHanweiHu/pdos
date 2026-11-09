"""Forecast-refresh SQL declarations; the migration owns head and installation.

Rows bind to the project's owner and visibility, so a forecast is readable
exactly when its project is. Records are append-only, bound at commit to their
common receipt and the advanced Current. No source material is copied: the
result holds computed times, keys and identities only (non-consuming).
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next.core import models as registered_models  # noqa: F401 -- full registry first
from pdos_next.domain.projects.work import storage_schema as work_storage

from .models import CURRENTS, REFRESHES, WorkForecastCurrent, WorkForecastRefresh
from .schemas import OPERATION, SUBJECT

TABLES = (WorkForecastRefresh.__table__, WorkForecastCurrent.__table__)
RUNTIME = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
OWNER = "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp"

ATOM = f"""
DECLARE r public.action_receipts; p public.principals; cur public.{CURRENTS};
BEGIN
 SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NOT FOUND OR r.operation<>'{OPERATION}' OR r.subject_type<>'{SUBJECT}' OR r.subject_id<>NEW.id
  OR r.subject_revision<>NEW.revision OR r.actor_id<>NEW.actor_id OR r.requester_id<>NEW.requester_id
  OR r.command_id<>NEW.command_id OR r.category_id<>NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id
  OR r.visibility<>NEW.visibility OR r.request_digest<>NEW.request_digest THEN
  RAISE EXCEPTION 'Forecast refresh requires its exact common receipt' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT p FROM public.principals WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id;
 IF (p.kind='human' AND (NEW.actor_id<>NEW.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL))
  OR (p.kind<>'human' AND r.agent_run_id IS NULL) THEN
  RAISE EXCEPTION 'Forecast refresh requires a named person or a bound run' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.projects pr WHERE pr.tenant_id=NEW.tenant_id AND pr.id=NEW.project_id
  AND pr.current_plan_id=NEW.plan_id) THEN
  RAISE EXCEPTION 'Forecast refresh must use the current applied plan' USING ERRCODE='23514'; END IF;
 SELECT * INTO cur FROM public.{CURRENTS} WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND project_id=NEW.project_id;
 IF NOT FOUND OR cur.version_id<>NEW.id OR cur.revision<>NEW.revision THEN
  RAISE EXCEPTION 'Forecast refresh requires its exact Current' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

FUNCTIONS = (
    (
        "protect_work_forecast_current()",
        work_storage.current_guard(
            CURRENTS, REFRESHES, "previous_id", "previous_revision", ("version_id", "revision")
        ),
    ),
    ("require_work_forecast_current()", work_storage.current_atom(CURRENTS, REFRESHES)),
    ("require_work_forecast_refresh()", ATOM),
)


def function_sql():
    return tuple(
        f"CREATE FUNCTION public.{signature} RETURNS trigger LANGUAGE plpgsql {OWNER} AS $work_forecast${body}$work_forecast$"
        for signature, body in FUNCTIONS
    )


def table_sql():
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in TABLES
        for statement in (
            CreateTable(table),
            *(CreateIndex(index) for index in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def policy_sql():
    statements = []
    for table in TABLES:
        name = table.name
        read = (
            "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p "
            f"WHERE p.tenant_id={name}.tenant_id AND p.category_id={name}.category_id "
            f"AND p.product_id={name}.product_id AND p.id={name}.project_id "
            f"AND p.owner_id={name}.owner_id AND p.visibility={name}.visibility)"
        )
        write = "public.category_access(tenant_id,category_id,true)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY work_forecast_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY work_forecast_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM {RUNTIME}',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == CURRENTS:
            statements.extend(
                (
                    f'CREATE POLICY work_forecast_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    return (
        f"CREATE TRIGGER work_forecast_immutable BEFORE UPDATE OR DELETE ON public.{REFRESHES} FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
        f"CREATE CONSTRAINT TRIGGER work_forecast_atom AFTER INSERT ON public.{REFRESHES} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_work_forecast_refresh()",
        f"CREATE TRIGGER work_forecast_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENTS} FOR EACH ROW EXECUTE FUNCTION public.protect_work_forecast_current()",
        f"CREATE CONSTRAINT TRIGGER work_forecast_current_atom AFTER INSERT OR UPDATE ON public.{CURRENTS} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_work_forecast_current()",
    )


def upgrade_sql():
    return (*table_sql(), *function_sql(), *policy_sql(), *trigger_sql())


def downgrade_sql():
    return (
        f"ALTER TABLE public.{REFRESHES} NO FORCE ROW LEVEL SECURITY",
        f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.{REFRESHES}) THEN
     RAISE EXCEPTION 'Forecast refresh history requires s0_0869'; END IF; END $$""",
        f"DROP TABLE public.{CURRENTS}",
        f"DROP TABLE public.{REFRESHES}",
        *(f"DROP FUNCTION public.{signature}" for signature, _ in FUNCTIONS),
    )
