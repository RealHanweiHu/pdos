"""Fixture acceptance SQL declarations (D306); the migration owns installation.

Rows are readable exactly when their project is. Versions are append-only and
bound at commit to the common receipt of a named person with no AI run.
"""

# ruff: noqa: E501 -- finite SQL guards stay readable as complete expressions.

from pdos_next.domain.named_records import storage

from .models import FixtureAcceptanceCurrent, FixtureAcceptanceVersion
from .schemas import SUBJECT

PROJECT_READ = (
    "public.category_access(tenant_id,category_id) AND EXISTS(SELECT 1 FROM public.projects p "
    "WHERE p.tenant_id={t}.tenant_id AND p.product_id={t}.product_id AND p.id={t}.project_id "
    "AND p.owner_id={t}.owner_id AND p.visibility={t}.visibility)"
)
CHAIN = storage.Chain(
    versions=FixtureAcceptanceVersion,
    currents=FixtureAcceptanceCurrent,
    subject=SUBJECT,
    prefix="fixture_acceptance",
    read=PROJECT_READ,
    history="Fixture acceptance history requires s0_0872",
    visibility=True,
)


# Named T2 approvals carry no preview expiry; the deadline check lists them.
INSTALLED_DEADLINE = (
    "ai.skill.qualify",
    "build.engineering.authorize",
    "build.manufacturing.authorize",
    "change.close",
    "change.order.approve",
    "change.selection.decide",
    "change.verification.record",
    "integration.handoff.authorize",
    "knowledge.rule.publish",
    "mcp.connector.allow",
    "npi.manufacturing_baseline.publish",
    "proposal.g0.decide",
    "quality.capa.verification.review",
    "quality.issue.root_cause.decide",
    "release.engineering.approve",
    "release.exception.decide",
    "release.exception.withdraw",
    "release.manufacturing.approve",
    "test.disposition.decide",
    "test.run.review",
    "work.baseline.approve",
    "work.stage.decide",
)
D47_T2 = (
    "npi.fixture.accept",
    "quality.capa.effectiveness.decide",
    "supply.alternate.approve",
    "customer.sample.send",
    "customer.acceptance.record",
    "evidence.source.withdraw",
)


def _deadline(operations):
    listed = ",".join(repr(value) for value in operations)
    return (
        "ALTER TABLE confirmations DROP CONSTRAINT ck_confirmations_decision_deadline",
        f"ALTER TABLE confirmations ADD CONSTRAINT ck_confirmations_decision_deadline CHECK(expires_at IS NOT NULL OR operation IN ({listed}))",
    )


def upgrade_sql():
    return (*storage.upgrade_sql(CHAIN), *_deadline((*INSTALLED_DEADLINE, *D47_T2)))


def downgrade_sql():
    listed = ",".join(repr(value) for value in D47_T2)
    return (
        f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM public.confirmations WHERE expires_at IS NULL AND operation IN ({listed})) THEN
     RAISE EXCEPTION 'D47 named approvals require s0_0872'; END IF; END $$""",
        *_deadline(INSTALLED_DEADLINE),
        *storage.downgrade_sql(CHAIN),
    )
