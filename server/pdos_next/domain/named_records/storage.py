"""SQL for a D47 named-person version chain; the migration owns installation.

No SQL runs here. Each chain gets: RLS that follows the scope's own read
predicate, append-only versions, a Current that advances one exact step, and a
deferred atom binding every version to its same-transaction common receipt
written by a named human with no AI run. The AI role has no privilege.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from dataclasses import dataclass

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pdos_next.core import models as registered_models  # noqa: F401 -- full registry first
from pdos_next.domain.projects.work import storage_schema as work_storage

RUNTIME = "PUBLIC,pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
OWNER = "SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp"


@dataclass(frozen=True)
class Chain:
    versions: object
    currents: object
    subject: str
    prefix: str
    read: str  # SQL predicate over {t}, the policy's own table name
    history: str  # downgrade refusal text
    extra_atom: str = ""  # additional checks on NEW inside the atom
    visibility: bool = False  # the receipt's visibility must equal NEW.visibility
    lifecycle: bool = True  # attach the generic original-lifecycle triggers

    @property
    def tables(self):
        return (self.versions.__table__, self.currents.__table__)

    @property
    def v(self):
        return self.versions.__tablename__

    @property
    def c(self):
        return self.currents.__tablename__


def atom(chain):
    vis = " OR r.visibility<>NEW.visibility" if chain.visibility else ""
    return f"""
DECLARE r public.action_receipts; p public.principals; cur public.{chain.c};
BEGIN
 SELECT * INTO r FROM public.action_receipts WHERE tenant_id=NEW.tenant_id AND id=NEW.receipt_id;
 IF NOT FOUND OR r.operation<>NEW.operation OR r.subject_type<>'{chain.subject}' OR r.subject_id<>NEW.id
  OR r.subject_revision<>NEW.revision OR r.actor_id<>NEW.actor_id OR r.requester_id<>NEW.requester_id
  OR r.command_id<>NEW.command_id OR r.category_id<>NEW.category_id OR r.product_id IS DISTINCT FROM NEW.product_id{vis}
  OR r.request_digest<>NEW.request_digest THEN
  RAISE EXCEPTION '{chain.prefix} requires its exact common receipt' USING ERRCODE='23514'; END IF;
 SELECT * INTO STRICT p FROM public.principals WHERE tenant_id=NEW.tenant_id AND id=NEW.actor_id;
 IF p.kind<>'human' OR NEW.actor_id<>NEW.requester_id OR r.agent_run_id IS NOT NULL OR r.run_id IS NOT NULL THEN
  RAISE EXCEPTION '{chain.prefix} is decided by a named person, never an AI run' USING ERRCODE='23514'; END IF;
{chain.extra_atom}
 SELECT * INTO cur FROM public.{chain.c} WHERE tenant_id=NEW.tenant_id AND product_id=NEW.product_id AND record_id=NEW.record_id;
 IF NOT FOUND OR cur.version_id<>NEW.id OR cur.revision<>NEW.revision OR cur.state<>NEW.state THEN
  RAISE EXCEPTION '{chain.prefix} requires its exact Current' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END
"""


def functions(chain):
    return (
        (
            f"protect_{chain.prefix}_current()",
            work_storage.current_guard(
                chain.c,
                chain.v,
                "previous_id",
                "previous_revision",
                ("version_id", "revision", "state"),
            ),
        ),
        (f"require_{chain.prefix}_current()", work_storage.current_atom(chain.c, chain.v)),
        (f"require_{chain.prefix}()", atom(chain)),
    )


def function_sql(chain):
    tag = f"${chain.prefix}$"
    return tuple(
        f"CREATE FUNCTION public.{signature} RETURNS trigger LANGUAGE plpgsql {OWNER} AS {tag}{body}{tag}"
        for signature, body in functions(chain)
    )


def table_sql(chain):
    return tuple(
        str(statement.compile(dialect=postgresql.dialect()))
        for table in chain.tables
        for statement in (
            CreateTable(table),
            *(CreateIndex(index) for index in sorted(table.indexes, key=lambda value: value.name)),
        )
    )


def policy_sql(chain):
    statements = []
    for table in chain.tables:
        name = table.name
        read = chain.read.format(t=name)
        write = "public.category_access(tenant_id,category_id,true)"
        statements.extend(
            (
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY',
                f'ALTER TABLE public."{name}" FORCE ROW LEVEL SECURITY',
                f'CREATE POLICY owner_internal ON public."{name}" TO pdos_next_owner USING(true) WITH CHECK(true)',
                f'CREATE POLICY {chain.prefix}_read ON public."{name}" FOR SELECT TO pdos_next_app USING({read})',
                f'CREATE POLICY {chain.prefix}_insert ON public."{name}" FOR INSERT TO pdos_next_app WITH CHECK({write} AND {read})',
                f'REVOKE ALL ON public."{name}" FROM {RUNTIME}',
                f'GRANT SELECT,INSERT ON public."{name}" TO pdos_next_app',
            )
        )
        if name == chain.c:
            statements.extend(
                (
                    f'CREATE POLICY {chain.prefix}_advance ON public."{name}" FOR UPDATE TO pdos_next_app USING({write} AND {read}) WITH CHECK({write} AND {read})',
                    f'GRANT UPDATE(version_id,revision,state) ON public."{name}" TO pdos_next_app',
                )
            )
    return tuple(statements)


def trigger_sql(chain):
    lifecycle = (
        tuple(
            statement
            for name in (chain.v, chain.c)
            for statement in (
                f"CREATE TRIGGER lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.lifecycle_reference_gate()",
                f"CREATE TRIGGER category_lifecycle_clock AFTER INSERT OR UPDATE OR DELETE ON public.{name} FOR EACH ROW EXECUTE FUNCTION public.category_lifecycle_clock()",
            )
        )
        if chain.lifecycle
        else ()
    )
    return (
        f"CREATE TRIGGER {chain.prefix}_immutable BEFORE UPDATE OR DELETE ON public.{chain.v} FOR EACH ROW EXECUTE FUNCTION public.kernel_append_only()",
        f"CREATE CONSTRAINT TRIGGER {chain.prefix}_atom AFTER INSERT ON public.{chain.v} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{chain.prefix}()",
        f"CREATE TRIGGER {chain.prefix}_current_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{chain.c} FOR EACH ROW EXECUTE FUNCTION public.protect_{chain.prefix}_current()",
        f"CREATE CONSTRAINT TRIGGER {chain.prefix}_current_atom AFTER INSERT OR UPDATE ON public.{chain.c} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.require_{chain.prefix}_current()",
        *lifecycle,
    )


def upgrade_sql(*chains):
    return tuple(
        statement
        for chain in chains
        for statement in (
            *table_sql(chain),
            *function_sql(chain),
            *policy_sql(chain),
            *trigger_sql(chain),
        )
    )


def downgrade_sql(*chains):
    out = []
    for chain in reversed(chains):
        out.extend(
            (
                f"ALTER TABLE public.{chain.v} NO FORCE ROW LEVEL SECURITY",
                f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.{chain.v}) THEN
     RAISE EXCEPTION '{chain.history}'; END IF; END $$""",
                f"DROP TABLE public.{chain.c}",
                f"DROP TABLE public.{chain.v}",
                *(f"DROP FUNCTION public.{signature}" for signature, _ in functions(chain)),
            )
        )
    return tuple(out)
