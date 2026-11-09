"""Supplier-commitment SQL declarations; the migration owns head and installation.

No SQL is executed here. Rows are readable exactly when their fixed Build is
(the Build's own RLS decides). Versions are append-only and each one must be
bound, at commit, to its common receipt and to the advanced Current. The AI
role has no privilege; 小Pai writes only through the bound command path.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next.core import models as registered_models  # noqa: F401 -- full registry first
from pdos_next.domain.projects.work import storage_schema as work_storage

from .models import CURRENTS, VERSIONS, SupplyCommitmentCurrent, SupplyCommitmentVersion
from .schemas import OPERATION, SUBJECT

TABLES = (SupplyCommitmentVersion.__table__, SupplyCommitmentCurrent.__table__)
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
  RAISE EXCEPTION 'Supply commitment requires its exact common receipt' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT p FROM public.principals WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id;
 IF p.kind='human' THEN
  IF NEW.actor_id<>NEW.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL
   OR NEW.body->>'time_basis' IS DISTINCT FROM 'human_recorded' THEN
   RAISE EXCEPTION 'A named person records supply commitments for themself' USING ERRCODE='23514'; END IF;
 ELSIF r.agent_run_id IS NULL OR NEW.body->>'time_basis' IS DISTINCT FROM 'source_claim'
  OR jsonb_array_length(NEW.sources)=0 OR NEW.body->>'statement' IS NOT NULL THEN
  RAISE EXCEPTION 'AI supply commitments need a bound run and exact original lines' USING ERRCODE='23514';
 END IF;
 SELECT * INTO cur FROM public.{CURRENTS} WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND commitment_id=NEW.commitment_id;
 IF NOT FOUND OR cur.version_id<>NEW.id OR cur.revision<>NEW.revision OR cur.state<>NEW.state THEN
  RAISE EXCEPTION 'Supply commitment requires its exact Current' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""

FUNCTIONS = (
    (
        "protect_supply_commitment_current()",
        work_storage.current_guard(
            CURRENTS,
            VERSIONS,
            "previous_id",
            "previous_revision",
            ("version_id", "revision", "state"),
        ),
    ),
    ("require_supply_commitment_current()", work_storage.current_atom(CURRENTS, VERSIONS)),
    ("require_supply_commitment()", ATOM),
)


def function_sql():
    return tuple(
        f"CREATE FUNCTION public.{signature} RETURNS trigger LANGUAGE plpgsql {OWNER} AS $supply_commitment${body}$supply_commitment$"
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
            "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.builds b "
            f"WHERE b.tenant_id={name}.tenant_id AND b.category_id={name}.category_id "
            f"AND b.product_id={name}.product_id AND b.project_id={name}.project_id AND b.id={name}.build_id "
            f"AND b.owner_id={name}.owner_id AND b.visibility={name}.visibility)"
        )
        write = "public.category_access(tenant_id,category_id,true)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY supply_commitment_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY supply_commitment_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM {RUNTIME}',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == CURRENTS:
            statements.extend(
                (
                    f'CREATE POLICY supply_commitment_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,state) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql():
    return (
        f"CREATE TRIGGER supply_commitment_immutable BEFORE UPDATE OR DELETE ON public.{VERSIONS} FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
        f"CREATE CONSTRAINT TRIGGER supply_commitment_atom AFTER INSERT ON public.{VERSIONS} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_supply_commitment()",
        f"CREATE TRIGGER supply_commitment_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{CURRENTS} FOR EACH ROW EXECUTE FUNCTION public.protect_supply_commitment_current()",
        f"CREATE CONSTRAINT TRIGGER supply_commitment_current_atom AFTER INSERT OR UPDATE ON public.{CURRENTS} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_supply_commitment_current()",
        *(
            statement
            for name in (VERSIONS, CURRENTS)
            for statement in (
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        ),
    )


def upgrade_sql():
    return (*table_sql(), *function_sql(), *policy_sql(), *trigger_sql())


def downgrade_sql():
    return (
        f"ALTER TABLE public.{VERSIONS} NO FORCE ROW LEVEL SECURITY",
        f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.{VERSIONS}) THEN
     RAISE EXCEPTION 'Supply commitment history requires s0_0868'; END IF; END $$""",
        f"DROP TABLE public.{CURRENTS}",
        f"DROP TABLE public.{VERSIONS}",
        *(f"DROP FUNCTION public.{signature}" for signature, _ in FUNCTIONS),
    )
