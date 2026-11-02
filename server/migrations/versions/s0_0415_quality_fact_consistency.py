# ruff: noqa: E501 -- frozen PostgreSQL definitions preserve their original SQL text
"""B5 complete source sets and nullable ordinary named-review validity.

Frozen constraints are captured from the verified s0_0414 head. Real rule and
qualification intervals remain required; no business capture TTL is introduced.
"""

from alembic import op

revision = "s0_0415"
down_revision = "s0_0414"
branch_labels = None
depends_on = None

CONSTRAINTS = (
    (
        "capa_named_verification_reviews",
        "capa_named_verification_reviews_check10",
        "CHECK (COALESCE(((((fact_body -> 'body'::text) -> 'previous'::text) = 'null'::jsonb) AND ((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'id'::text) = (candidate_id)::text) AND (((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'revision'::text))::integer = candidate_revision) AND ((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'sha256'::text) = (candidate_sha256)::text) AND (((fact_body -> 'body'::text) ->> 'candidate_sha256'::text) = (candidate_sha256)::text) AND ((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'id'::text) = (rule_fact_id)::text) AND (((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'revision'::text))::integer = rule_revision) AND ((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'sha256'::text) = (rule_sha256)::text) AND (((fact_body -> 'body'::text) ->> 'reviewer_id'::text) = (reviewer_id)::text) AND (((fact_body -> 'body'::text) -> 'authority_snapshot'::text) = authority_snapshot) AND (((fact_body -> 'body'::text) -> 'policy_snapshot'::text) = policy_snapshot) AND ((((fact_body -> 'body'::text) ->> 'valid_until'::text))::timestamp with time zone = valid_until)), false))",
        "CHECK (COALESCE(((((fact_body -> 'body'::text) -> 'previous'::text) = 'null'::jsonb) AND ((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'id'::text) = (candidate_id)::text) AND (((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'revision'::text))::integer = candidate_revision) AND ((((fact_body -> 'body'::text) -> 'candidate'::text) ->> 'sha256'::text) = (candidate_sha256)::text) AND (((fact_body -> 'body'::text) ->> 'candidate_sha256'::text) = (candidate_sha256)::text) AND ((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'id'::text) = (rule_fact_id)::text) AND (((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'revision'::text))::integer = rule_revision) AND ((((fact_body -> 'body'::text) -> 'rule'::text) ->> 'sha256'::text) = (rule_sha256)::text) AND (((fact_body -> 'body'::text) ->> 'reviewer_id'::text) = (reviewer_id)::text) AND (((fact_body -> 'body'::text) -> 'authority_snapshot'::text) = authority_snapshot) AND (((fact_body -> 'body'::text) -> 'policy_snapshot'::text) = policy_snapshot) AND ((((fact_body -> 'body'::text) ->> 'valid_until'::text))::timestamp with time zone IS NOT DISTINCT FROM valid_until)), false))",
    ),
    (
        "capa_named_verification_reviews",
        "capa_named_verification_reviews_check7",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20)) AND (jsonb_typeof(source_basis) = 'array'::text) AND ((jsonb_array_length(source_basis) >= 1) AND (jsonb_array_length(source_basis) <= 20)) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_typeof(source_basis) = 'array'::text) AND (jsonb_array_length(source_basis) >= 1) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
    ),
    (
        "capa_named_verification_reviews",
        "capa_named_verification_reviews_check9",
        "CHECK (((revision = 1) AND (candidate_revision = 1) AND (rule_revision > 0) AND (reviewer_id = writer_id) AND (valid_until > created_at) AND ((candidate_sha256)::text ~ '^[0-9a-f]{64}$'::text) AND ((rule_sha256)::text ~ '^[0-9a-f]{64}$'::text)))",
        "CHECK (((revision = 1) AND (candidate_revision = 1) AND (rule_revision > 0) AND (reviewer_id = writer_id) AND ((valid_until IS NULL) OR (valid_until > created_at)) AND ((candidate_sha256)::text ~ '^[0-9a-f]{64}$'::text) AND ((rule_sha256)::text ~ '^[0-9a-f]{64}$'::text)))",
    ),
    (
        "capa_observation_facts",
        "capa_observation_facts_check7",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20)) AND (jsonb_typeof(source_basis) = 'array'::text) AND ((jsonb_array_length(source_basis) >= 1) AND (jsonb_array_length(source_basis) <= 20)) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_typeof(source_basis) = 'array'::text) AND (jsonb_array_length(source_basis) >= 1) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
    ),
    (
        "capa_remediation_links",
        "capa_remediation_links_required_source_read_set_check",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20))), false))",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1)), false))",
    ),
    (
        "capa_verification_evidence",
        "capa_verification_evidence_required_source_read_set_check",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20))), false))",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1)), false))",
    ),
    (
        "capa_verification_rule_facts",
        "capa_verification_rule_facts_check7",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20)) AND (jsonb_typeof(source_basis) = 'array'::text) AND ((jsonb_array_length(source_basis) >= 1) AND (jsonb_array_length(source_basis) <= 20)) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
        "CHECK (COALESCE(((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_typeof(source_basis) = 'array'::text) AND (jsonb_array_length(source_basis) >= 1) AND (jsonb_typeof(sources) = 'array'::text) AND (jsonb_array_length(sources) > 0) AND (required_source_read_set = ((fact_body -> 'body'::text) -> 'required_source_read_set'::text)) AND (source_basis = ((fact_body -> 'body'::text) -> 'source_basis'::text)) AND (sources = ((fact_body -> 'body'::text) -> 'sources'::text))), false))",
    ),
    (
        "quality_event_failure_links",
        "quality_event_failure_links_required_source_read_set_check",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20))))",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1)))",
    ),
    (
        "quality_issue_versions",
        "quality_issue_versions_required_source_read_set_check",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20))))",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1)))",
    ),
    (
        "quality_policy_facts",
        "quality_policy_facts_required_source_read_set_check",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND ((jsonb_array_length(required_source_read_set) >= 1) AND (jsonb_array_length(required_source_read_set) <= 20))))",
        "CHECK (((jsonb_typeof(required_source_read_set) = 'array'::text) AND (jsonb_array_length(required_source_read_set) >= 1)))",
    ),
)


def _constraints(index):
    for table, name, before, after in CONSTRAINTS:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
        definition = (before, after)[index]
        op.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')


def upgrade():
    op.execute("ALTER TABLE capa_named_verification_reviews ALTER COLUMN valid_until DROP NOT NULL")
    _constraints(1)


def downgrade():
    # An existing unlimited review cannot be given an invented expiry.
    # PostgreSQL refuses the old NOT NULL shape unless such facts are absent.
    op.execute("ALTER TABLE capa_named_verification_reviews ALTER COLUMN valid_until SET NOT NULL")
    _constraints(0)
