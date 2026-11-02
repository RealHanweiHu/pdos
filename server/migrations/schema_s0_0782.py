"""Frozen exact deadline constraint correction for the two release T2 operations."""

CONSTRAINT = "ck_confirmations_decision_deadline"

PREVIOUS_DEFINITION = (
    "CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY "
    "((ARRAY['npi.manufacturing_baseline.publish'::character varying, "
    "'mcp.connector.allow'::character varying, 'ai.skill.qualify'::character varying, "
    "'build.engineering.authorize'::character varying, "
    "'build.manufacturing.authorize'::character varying, 'change.order.approve'::character "
    "varying, 'change.selection.decide'::character varying, 'proposal.g0.decide'::character "
    "varying, 'quality.capa.verification.review'::character varying, "
    "'quality.issue.root_cause.decide'::character varying, 'test.disposition.decide'::character "
    "varying, 'test.run.review'::character varying])::text[]))))"
)

REPLACEMENT_DEFINITION = (
    "CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY "
    "((ARRAY['release.engineering.approve'::character varying, "
    "'release.manufacturing.approve'::character varying, "
    "'npi.manufacturing_baseline.publish'::character varying, 'mcp.connector.allow'::character "
    "varying, 'ai.skill.qualify'::character varying, 'build.engineering.authorize'::character "
    "varying, 'build.manufacturing.authorize'::character varying, "
    "'change.order.approve'::character varying, 'change.selection.decide'::character varying, "
    "'proposal.g0.decide'::character varying, 'quality.capa.verification.review'::character "
    "varying, 'quality.issue.root_cause.decide'::character varying, "
    "'test.disposition.decide'::character varying, 'test.run.review'::character "
    "varying])::text[]))))"
)
# PostgreSQL stores the explicit typed-array SQL with per-element casts. These
# observed rollback expectations preserve the upgrade SQL above unchanged.
APPLIED_DEFINITION = (
    "CHECK (((expires_at IS NOT NULL) OR ((operation)::text = ANY "
    "(ARRAY[('release.engineering.approve'::character varying)::text, "
    "('release.manufacturing.approve'::character varying)::text, "
    "('npi.manufacturing_baseline.publish'::character varying)::text, "
    "('mcp.connector.allow'::character varying)::text, ('ai.skill.qualify'::character "
    "varying)::text, ('build.engineering.authorize'::character varying)::text, "
    "('build.manufacturing.authorize'::character varying)::text, "
    "('change.order.approve'::character varying)::text, ('change.selection.decide'::character "
    "varying)::text, ('proposal.g0.decide'::character varying)::text, "
    "('quality.capa.verification.review'::character varying)::text, "
    "('quality.issue.root_cause.decide'::character varying)::text, "
    "('test.disposition.decide'::character varying)::text, ('test.run.review'::character "
    "varying)::text]))))"
)

PREVIOUS_STATEMENT = (
    "CHECK (expires_at IS NOT NULL OR operation IN "
    "('npi.manufacturing_baseline.publish','mcp.connector.allow','ai.skill.qualify','build.engineering.authorize','build.manufacturing.authorize','change.order.approve','change.selection.decide','proposal.g0.decide','quality.capa.verification.review','quality.issue.root_cause.decide','test.disposition.decide','test.run.review'))"
)
