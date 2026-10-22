"""M2 branch migration roundtrip and metadata checks on its verified synthetic fixture."""

import argparse

import local_environment as local
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from m2_verify import REPORT, run
from pdos_next.agent_kernel.models import KernelRow
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import text


def main(*, metadata_only=False):
    local.STATE = local.ROOT / ".local/m2-runtime.json"
    state = local.verified(local.read_state())
    engine = engine_for(state["admin_url"])
    if not metadata_only:
        retire_fixtures(engine)
    engine.dispose()
    # Only M2-owned synthetic run/research metadata is dropped; the common baseline remains.
    if not metadata_only:
        for args, name in [
            (["-m", "alembic", "downgrade", "s0_0011"], "migrations-down-0011.log"),
            (["-m", "alembic", "upgrade", "m2@head"], "migrations-up-0715.log"),
        ]:
            if run(args, name=name):
                raise RuntimeError("M2 migration roundtrip failed; inspect redacted evidence")
    state = local.verified(local.read_state())
    engine = engine_for(state["admin_url"])
    owned = {cls.__tablename__ for cls in KernelRow.__subclasses__()}

    def include_object(obj, name, type_, reflected, compare_to):
        table = obj if type_ == "table" else getattr(obj, "table", None)
        return table is None or table.name in owned

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        differences = compare_metadata(context, Base.metadata)
        installed = connection.scalar(text("""SELECT count(*) FROM pg_constraint
          WHERE conname='fk_action_receipts_agent_run' AND convalidated
            AND conrelid='action_receipts'::regclass AND confrelid='agent_runs'::regclass
            AND pg_get_constraintdef(oid)='FOREIGN KEY (tenant_id, category_id, agent_run_id) '
              || 'REFERENCES agent_runs(tenant_id, category_id, id)'"""))
    engine.dispose()
    (REPORT / "m2-owned-metadata.txt").write_text(
        f"Owned tables: {len(owned)}\nDifferences: {differences!r}\n"
        f"Root Receipt FK installed/validated: {installed == 1}\n"
    )
    if differences or installed != 1:
        raise RuntimeError("M2 owned schema or installed root receipt FK differs from ORM")
    print(f"M2 owned metadata passed; {len(owned)} tables and root Receipt FK match ORM.")


def retire_fixtures(engine):
    with engine.begin() as connection:
        # Only this test's explicitly tagged, standalone synthetic receipts may
        # be retired before dropping their M2 fixture runs. A real domain atom
        # or an unrecognized run-bound receipt makes this roundtrip stop.
        fixture = """SELECT id FROM action_receipts WHERE agent_run_id IS NOT NULL
          AND operation='synthetic.draft' AND subject_type='synthetic'
          AND result=jsonb_build_object('synthetic',true)"""
        protected = connection.scalar(text(f"""SELECT count(*) FROM action_receipts r
          WHERE r.agent_run_id IS NOT NULL AND (r.id NOT IN ({fixture})
            OR EXISTS(SELECT 1 FROM audit_entries a WHERE a.receipt_id=r.id)
            OR EXISTS(SELECT 1 FROM outbox_events o WHERE o.receipt_id=r.id))"""))
        if protected:
            raise RuntimeError("Roundtrip refuses unrecognized or atomic run-bound domain receipts")
        retired = connection.execute(text(f"DELETE FROM action_receipts WHERE id IN ({fixture})"))
        (REPORT / "roundtrip-fixture-retirement.txt").write_text(
            f"Standalone synthetic.draft test receipts retired: {retired.rowcount}\n"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-only", action="store_true")
    main(metadata_only=parser.parse_args().metadata_only)
