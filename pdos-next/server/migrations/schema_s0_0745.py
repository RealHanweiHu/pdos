"""Defer snapshot receipt validation to the common command transaction boundary.

The snapshot subject is persisted before its receipt and completed domain Call.
The receipt foreign key and existing guard check the complete unit before commit; the
append-only and identity triggers remain immediate and unchanged.
"""

SCHEMA_SQL = (
    "ALTER TABLE public.public_web_snapshots ALTER CONSTRAINT "
    "public_web_snapshots_tenant_id_receipt_id_fkey DEFERRABLE INITIALLY DEFERRED",
    "DROP TRIGGER kernel_snapshot ON public.public_web_snapshots",
    "CREATE CONSTRAINT TRIGGER kernel_snapshot AFTER INSERT ON public.public_web_snapshots "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kernel_snapshot_guard()",
)

DOWNGRADE_SQL = (
    "ALTER TABLE public.public_web_snapshots ALTER CONSTRAINT "
    "public_web_snapshots_tenant_id_receipt_id_fkey NOT DEFERRABLE INITIALLY IMMEDIATE",
    "DROP TRIGGER kernel_snapshot ON public.public_web_snapshots",
    "CREATE TRIGGER kernel_snapshot BEFORE INSERT ON public.public_web_snapshots "
    "FOR EACH ROW EXECUTE FUNCTION kernel_snapshot_guard()",
)
