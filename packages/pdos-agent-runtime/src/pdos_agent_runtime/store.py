"""Private runtime storage, separate from domain databases and Temporal history.

Schema installation is explicit. A runtime role owns only its own realm's work;
the host reauthorizes business inputs and outputs on each execution/retrieval.
"""

import json
from hashlib import sha256
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_NAMESPACE = UUID("57995d78-7a49-46e1-954d-3fbb0b850527")


def digest(value) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RuntimeStore:
    def __init__(self, url: str, *, realm: str, marker: str):
        self.url, self.realm, self.marker = url, realm, marker
        if realm not in {"pdos-next"}:
            raise ValueError("Unknown runtime realm")
        with self.connection() as c:
            row = c.execute("SELECT marker FROM environment_guard").fetchone()
            if row is None or str(row["marker"]) != marker:
                raise ValueError("Independent runtime database marker mismatch")
            database = c.execute("SELECT current_database() AS name").fetchone()["name"]
            if database != "pdos_agent_runtime":
                raise ValueError("Runtime storage must use its own database")

    def connection(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def put(self, tenant_id: str, handler: str, payload: dict) -> dict:
        fingerprint = digest(payload)
        job_id = str(
            uuid5(_NAMESPACE, f"{self.realm}:{tenant_id}:{handler}:{fingerprint}")
        )
        with self.connection() as c:
            c.execute(
                "INSERT INTO agent_runtime_jobs(realm,tenant_id,id,handler,input_digest,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(realm,id) DO NOTHING",
                (self.realm, tenant_id, job_id, handler, fingerprint, Jsonb(payload)),
            )
        return {
            "realm": self.realm,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "handler": handler,
            "input_digest": fingerprint,
        }

    def read(self, ref: dict) -> dict:
        if ref["realm"] != self.realm:
            raise ValueError("Runtime realm mismatch")
        with self.connection() as c:
            row = c.execute(
                "SELECT * FROM agent_runtime_jobs WHERE realm=%s AND tenant_id=%s AND id=%s",
                (self.realm, ref["tenant_id"], ref["job_id"]),
            ).fetchone()
        if (
            row is None
            or row["handler"] != ref["handler"]
            or row["input_digest"] != ref["input_digest"]
            or digest(row["payload"]) != row["input_digest"]
        ):
            raise ValueError("Private work reference mismatch")
        return row

    def claim(self, ref: dict) -> bool:
        self.read(ref)
        with self.connection() as c:
            return (
                c.execute(
                    "UPDATE agent_runtime_jobs SET state='running',started_at=clock_timestamp() "
                    "WHERE realm=%s AND id=%s AND state='queued' RETURNING id",
                    (self.realm, ref["job_id"]),
                ).fetchone()
                is not None
            )

    def finish(self, ref: dict, result: dict):
        self.read(ref)
        with self.connection() as c:
            c.execute(
                "UPDATE agent_runtime_jobs SET state='completed',result=%s,"
                "error_code=NULL,finished_at=clock_timestamp() "
                "WHERE realm=%s AND id=%s AND state='running'",
                (Jsonb(result), self.realm, ref["job_id"]),
            )

    def fail(self, ref: dict, code: str):
        self.read(ref)
        with self.connection() as c:
            c.execute(
                "UPDATE agent_runtime_jobs SET state='failed',error_code=%s,"
                "finished_at=clock_timestamp() WHERE realm=%s AND id=%s AND state='running'",
                (code, self.realm, ref["job_id"]),
            )

    def require_reconciliation(self, ref: dict):
        self.read(ref)
        with self.connection() as connection:
            connection.execute(
                "UPDATE agent_runtime_jobs SET error_code='AGENT_RECONCILIATION_REQUIRED' "
                "WHERE realm=%s AND id=%s AND state='running'",
                (self.realm, ref["job_id"]),
            )

    def emit(self, ref: dict, event: dict):
        self.read(ref)
        with self.connection() as c:
            c.execute(
                "INSERT INTO agent_runtime_events(realm,job_id,body) VALUES(%s,%s,%s)",
                (self.realm, ref["job_id"], Jsonb(event)),
            )

    def events(self, ref: dict, after: int):
        self.read(ref)
        with self.connection() as c:
            return c.execute(
                "SELECT sequence,body FROM agent_runtime_events "
                "WHERE realm=%s AND job_id=%s AND sequence>%s ORDER BY sequence LIMIT 200",
                (self.realm, ref["job_id"], after),
            ).fetchall()


SCHEMA = """
CREATE TABLE agent_runtime_jobs(
 realm text NOT NULL CHECK(realm IN ('pdos-next')),
 tenant_id uuid NOT NULL, id uuid NOT NULL, handler text NOT NULL,
 input_digest text NOT NULL, payload jsonb NOT NULL,
 state text NOT NULL DEFAULT 'queued'
 CHECK(state IN ('queued','running','completed','failed')),
 result jsonb, error_code text, started_at timestamptz, finished_at timestamptz,
 PRIMARY KEY(realm,id)
);
CREATE TABLE agent_runtime_events(
 sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 realm text NOT NULL, job_id uuid NOT NULL, body jsonb NOT NULL,
 FOREIGN KEY(realm,job_id) REFERENCES agent_runtime_jobs(realm,id)
);
CREATE INDEX agent_runtime_events_job ON agent_runtime_events(realm,job_id,sequence);
REVOKE ALL ON agent_runtime_jobs, agent_runtime_events FROM PUBLIC;
CREATE FUNCTION agent_runtime_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' OR NEW.realm IS DISTINCT FROM OLD.realm
 OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id
 OR NEW.handler IS DISTINCT FROM OLD.handler
 OR NEW.input_digest IS DISTINCT FROM OLD.input_digest
 OR NEW.payload IS DISTINCT FROM OLD.payload
 OR OLD.state IN ('completed','failed') THEN
   RAISE EXCEPTION 'Runtime identity, inputs and terminal results are immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER agent_runtime_immutable BEFORE UPDATE OR DELETE ON agent_runtime_jobs
FOR EACH ROW EXECUTE FUNCTION agent_runtime_guard();
"""
