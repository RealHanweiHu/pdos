"""Customer acceptance SQL declarations (D309); the migration owns installation."""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from pdos_next.domain.manufacturing.alternate_approvals.storage_schema import BUILD_READ
from pdos_next.domain.named_records import storage

from .models import CustomerAcceptanceCurrent, CustomerAcceptanceVersion
from .schemas import SUBJECT

CHAIN = storage.Chain(
    versions=CustomerAcceptanceVersion,
    currents=CustomerAcceptanceCurrent,
    subject=SUBJECT,
    prefix="customer_acceptance",
    read=BUILD_READ,
    history="Customer acceptance history requires s0_0885",
    visibility=True,
)


def upgrade_sql():
    return storage.upgrade_sql(CHAIN)


def downgrade_sql():
    return storage.downgrade_sql(CHAIN)
