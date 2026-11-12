"""Interface-contract SQL declarations (D312); the migration owns installation.

Rows are readable exactly when the configuration series root is (its own RLS
decides). Versions are append-only and bound at commit to the common receipt of
a named person with no AI run, plus the advanced Current.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from pdos_next.domain.named_records import storage

from .models import InterfaceCurrent, InterfaceVersion
from .schemas import SUBJECT

READ = (
    "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.engineering_configurations c "
    "WHERE c.tenant_id={t}.tenant_id AND c.category_id={t}.category_id AND c.product_id={t}.product_id "
    "AND c.id={t}.configuration_series_id AND c.owner_id={t}.owner_id AND c.visibility={t}.visibility)"
)
CHAIN = storage.Chain(
    versions=InterfaceVersion,
    currents=InterfaceCurrent,
    subject=SUBJECT,
    prefix="engineering_interface",
    read=READ,
    history="Interface contract history requires s0_0880",
    visibility=True,
    extra_atom=""" IF NOT EXISTS(SELECT 1 FROM public.engineering_configurations c WHERE c.tenant_id=NEW.tenant_id
   AND c.product_id=NEW.product_id AND c.id=NEW.configuration_id AND c.series_id=NEW.configuration_series_id
   AND c.owner_id=NEW.owner_id AND c.visibility=NEW.visibility) THEN
  RAISE EXCEPTION 'engineering_interface requires a configuration of its own series and audience' USING ERRCODE='23514'; END IF;""",
)


def upgrade_sql():
    return storage.upgrade_sql(CHAIN)


def downgrade_sql():
    return storage.downgrade_sql(CHAIN)
