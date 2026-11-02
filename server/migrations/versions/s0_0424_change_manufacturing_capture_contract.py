# ruff: noqa: E501 -- exact reviewed PostgreSQL repair anchors
"""B6 optional ordinary captures and complete change/manufacturing collections."""

import hashlib

from alembic import op
from sqlalchemy import text

revision = "s0_0424"
down_revision = "s0_0423"
branch_labels = None
depends_on = None

TIME_CHECK = (
    "CREATE FUNCTION public.capture_authority_time_current(\n"
    "  authority jsonb, saved_at timestamptz) RETURNS boolean\n"
    "LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$\n"
    "  SELECT COALESCE(\n"
    "    (authority->>'valid_until' IS NULL OR\n"
    "      (authority->>'valid_until')::timestamptz>saved_at)\n"
    "    AND EXISTS (\n"
    "      SELECT 1 FROM jsonb_array_elements(authority->'fact_refs') duty\n"
    "      JOIN jsonb_array_elements(authority->'fact_refs') qualification\n"
    "        ON qualification->>'role'=duty->>'role'\n"
    "      WHERE duty->>'kind'='duty' AND qualification->>'kind'='qualification'\n"
    "        AND authority->'roles' @> jsonb_build_array(duty->>'role')\n"
    "        AND duty->>'state'='active' AND qualification->>'state'='active'\n"
    "        AND (duty->>'nature'<>'synthetic' OR authority->'synthetic'='true'::jsonb)\n"
    "        AND (qualification->>'nature'<>'synthetic' OR authority->'synthetic'='true'::jsonb)\n"
    "        AND duty->'operations' @> jsonb_build_array(authority->>'operation')\n"
    "        AND qualification->'operations' @> jsonb_build_array(authority->>'operation')\n"
    "        AND duty->'purposes' @> jsonb_build_array(authority->>'purpose')\n"
    "        AND qualification->'purposes' @> jsonb_build_array(authority->>'purpose')\n"
    "        AND (duty->>'valid_from')::timestamptz<=saved_at\n"
    "        AND saved_at<(duty->>'valid_until')::timestamptz\n"
    "        AND (qualification->>'valid_from')::timestamptz<=saved_at\n"
    "        AND saved_at<(qualification->>'valid_until')::timestamptz)\n"
    ",false)\n"
    "$$;\n"
)

REPAIRS = {
    "require_quality_change_atom()": [
        (
            "COALESCE(jsonb_array_length(target.input_snapshot->'sources'),0) NOT BETWEEN 1 AND 30",
            "COALESCE(jsonb_array_length(target.input_snapshot->'sources'),0)<1",
        ),
        (
            "OR capture.expires_at<=NEW.created_at",
            "OR (capture.expires_at IS NOT NULL AND capture.expires_at<=NEW.created_at)",
        ),
    ],
    "require_change_order_atom()": [
        ("jsonb_array_length(NEW.sources) BETWEEN 1 AND 20", "jsonb_array_length(NEW.sources)>0"),
        (
            "jsonb_array_length(NEW.required_source_read_set) BETWEEN 1 AND 20",
            "jsonb_array_length(NEW.required_source_read_set)>0",
        ),
    ],
    "protect_change_implementation_capture()": [
        ("jsonb_array_length(NEW.sources) BETWEEN 1 AND 20", "jsonb_array_length(NEW.sources)>0"),
        (
            "jsonb_array_length(NEW.required_source_read_set) BETWEEN 1 AND 20",
            "jsonb_array_length(NEW.required_source_read_set)>0",
        ),
        (
            "AND NEW.expires_at<=(o->'plan'->>'expires_at')::timestamptz",
            "AND (o->'plan'->>'expires_at' IS NULL OR\n"
            "        (NEW.expires_at IS NOT NULL AND "
            "NEW.expires_at<=(o->'plan'->>'expires_at')::timestamptz))",
        ),
        (
            "AND "
            "(NEW.fact_snapshot->>'occurred_at')::timestamptz<(a->>'expires_at')::timestamptz\n"
            "          AND "
            "NEW.expires_at<=(a->>'expires_at')::timestamptz",
            "AND (a->>'expires_at' IS NULL OR\n"
            "            "
            "((NEW.fact_snapshot->>'occurred_at')::timestamptz<(a->>'expires_at')::timestamptz\n"
            "              AND NEW.expires_at IS NOT NULL\n"
            "              AND "
            "NEW.expires_at<=(a->>'expires_at')::timestamptz))",
        ),
    ],
    "assert_controlled_change_atom(text,uuid,uuid)": [
        (
            "jsonb_array_length(a->'material'->'required_disciplines') BETWEEN 2 AND 4",
            "jsonb_array_length(a->'material'->'required_disciplines')>=2",
        ),
        (
            "jsonb_array_length(a->'sources') NOT BETWEEN 1 AND 20",
            "jsonb_array_length(a->'sources')<1",
        ),
        (
            "jsonb_array_length(a->'required_source_read_set') NOT BETWEEN 1 AND 20",
            "jsonb_array_length(a->'required_source_read_set')<1",
        ),
    ],
    "assert_change_coverage_atom(uuid,uuid)": [
        ("jsonb_array_length(m->'nodes') BETWEEN 1 AND 250", "jsonb_array_length(m->'nodes')>0"),
        ("jsonb_array_length(m->'roots') BETWEEN 1 AND 100", "jsonb_array_length(m->'roots')>0"),
        ("jsonb_array_length(m->'units') BETWEEN 1 AND 250", "jsonb_array_length(m->'units')>0"),
        (
            "jsonb_array_length(item->'nodes') BETWEEN 1 AND 250",
            "jsonb_array_length(item->'nodes')>0",
        ),
        (
            "AND (a.authority_snapshot->>'valid_until')::timestamptz>a.created_at",
            "AND capture_authority_time_current(a.authority_snapshot,a.created_at)",
        ),
        (
            "jsonb_array_length(a.required_source_read_set) BETWEEN 1 AND 20",
            "jsonb_array_length(a.required_source_read_set)>0",
        ),
        (
            "AND product_id=a.product_id AND id=(a.source->>'id')::uuid;",
            "AND category_id=a.category_id AND "
            "(product_id=a.product_id OR product_id IS NULL)\n"
            "  AND id=(a.source->>'id')::uuid;",
        ),
        (
            "AND x.product_id=a.product_id AND x.operation='evidence.artifact.register'",
            "AND x.category_id=a.category_id AND x.product_id "
            "IS NOT DISTINCT FROM native.product_id\n"
            "  AND x.operation='evidence.artifact.register'",
        ),
    ],
    "assert_manufacturing_preparation_atom(uuid,uuid)": [
        (
            "OR jsonb_array_length(v.required_source_read_set)>20",
            "OR jsonb_array_length(v.required_source_read_set)<1",
        ),
        (
            "OR v.authority_snapshot->>'valid_until' "
            "IS NULL\n"
            "    OR "
            "(v.authority_snapshot->>'valid_until')::timestamptz<=v.created_at",
            "OR NOT capture_authority_time_current(v.authority_snapshot,v.created_at)",
        ),
        (
            "(p.visibility='product' AND e.visibility='product')",
            "(p.visibility IN ('category','audience') AND e.visibility IN ('category','audience'))",
        ),
    ],
}

HASHES = {
    "require_quality_change_atom()": (
        "50db4dc948a030b6926a3ed72ca9fc9e6fce0a960f95911864e837181d01938a",
        "779230197ad6f689ada3f251b6f82f2174cea6b53d178a4772397b7b77e1d963",
    ),
    "require_change_order_atom()": (
        "2efc4bbb133ef80171187c7ad78cffce15ac74c40008e062afb5cedcd2920f54",
        "f1a00fe9709cb4be78074daf3c5ee3b1d366a052e0dd45ad239d6fb20cbe126b",
    ),
    "protect_change_implementation_capture()": (
        "78d016aab5f11ee2c87b11408b8f30ef9c1d464230d40525d66798b208db3aab",
        "7c9393670d590326df381f320d860aceb5246ddb973d1c32a0c494f0b7e1f409",
    ),
    "assert_controlled_change_atom(text,uuid,uuid)": (
        "f8f07f351dc761c0ba56de76a81ca5613d2a2248134fa2860751f8f2e270ca04",
        "63eac6b8d70230228a27a4972007d9fd39af1e64a143daa2eda4335dea353a01",
    ),
    "assert_change_coverage_atom(uuid,uuid)": (
        "099e6bac7fed14ca74280ad9ca86c93f671d312142f4664a3233f23726d620c6",
        "ec0145abe0f6e593a6de7240b2ab939e1b6c6939caad91a111a0fe79281f6852",
    ),
    "assert_manufacturing_preparation_atom(uuid,uuid)": (
        "54f24840aea1aeb8a88af0947d82c20dbc35b382a6e1d7fcf2abeeb830330aa6",
        "7e18a9f5d4104f80aa1ecfff729857218826cdf5d7999df9eed6938c40d5ddcb",
    ),
}

CONSTRAINTS = [
    (
        "change_approval_records",
        "change_approval_records_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "change_graph_captures",
        "change_graph_captures_check1",
        "CHECK (((expires_at > created_at) AND (expires_at <= (created_at + '00:10:00'::interval))))",
        "CHECK (expires_at IS NULL OR expires_at>created_at)",
    ),
    (
        "change_graph_captures",
        "change_graph_captures_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "change_implementation_captures",
        "change_implementation_captures_check1",
        "CHECK (((expires_at > created_at) AND (expires_at <= (created_at + '00:10:00'::interval))))",
        "CHECK (expires_at IS NULL OR expires_at>created_at)",
    ),
    (
        "change_implementation_captures",
        "change_implementation_captures_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "change_implementation_records",
        "change_implementation_records_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "change_order_records",
        "change_order_records_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "change_request_versions",
        "change_request_versions_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "controlled_change_coverage_facts",
        "controlled_change_coverage_facts_check3",
        "CHECK ((((nature)::text = ANY ((ARRAY['real'::character varying, 'synthetic'::character "
        "varying])::text[])) AND ((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20))))",
        "CHECK ((((nature)::text = ANY ((ARRAY['real'::character varying, 'synthetic'::character "
        "varying])::text[])) AND (jsonb_array_length(required_source_read_set)>0)))",
    ),
    (
        "controlled_change_policy_facts",
        "controlled_change_policy_facts_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "controlled_change_selection_facts",
        "controlled_change_selection_fact_required_source_read_set_check",
        "CHECK (((jsonb_array_length(required_source_read_set) >= 1) AND "
        "(jsonb_array_length(required_source_read_set) <= 20)))",
        "CHECK ((jsonb_array_length(required_source_read_set)>0))",
    ),
    (
        "controlled_change_selection_facts",
        "controlled_change_selection_facts_check3",
        "CHECK (((proof_consumed_at <= created_at) AND (created_at < proof_expires_at) AND "
        "(valid_until > created_at)))",
        "CHECK (((proof_consumed_at <= created_at) AND (created_at < proof_expires_at) AND "
        "(valid_until IS NULL OR valid_until>created_at)))",
    ),
]

NULLABLE = [
    ("change_graph_captures", "expires_at"),
    ("change_implementation_captures", "expires_at"),
    ("controlled_change_selection_facts", "valid_until"),
]


def _replace(reverse=False):
    for signature, replacements in REPAIRS.items():
        body, definition = (
            op.get_bind()
            .execute(
                text(
                    "SELECT prosrc,pg_get_functiondef(oid) FROM pg_proc WHERE oid=to_regprocedure(:signature)"
                ),
                {"signature": signature},
            )
            .one()
        )
        before, after = HASHES[signature]
        expected, desired = (after, before) if reverse else (before, after)
        if hashlib.sha256(body.encode()).hexdigest() != expected:
            raise RuntimeError(f"Unreviewed B6 predecessor for {signature}")
        for old, new in replacements:
            old, new = (new, old) if reverse else (old, new)
            if body.count(old) != 1 or definition.count(old) != 1:
                raise RuntimeError(f"Non-unique B6 repair for {signature}")
            body, definition = body.replace(old, new, 1), definition.replace(old, new, 1)
        if hashlib.sha256(body.encode()).hexdigest() != desired:
            raise RuntimeError(f"Unexpected B6 repair for {signature}")
        op.execute(definition)


def _constraints(reverse=False):
    for table, name, before, after in CONSTRAINTS:
        if not reverse:
            actual = (
                op.get_bind()
                .execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid=to_regclass(:table) AND conname=:name"
                    ),
                    {"table": table, "name": name},
                )
                .scalar_one()
            )
            if actual != before:
                raise RuntimeError(f"Unreviewed B6 constraint {table}.{name}")
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
        op.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {before if reverse else after}')


def upgrade():
    op.execute(TIME_CHECK)
    op.execute(
        "REVOKE ALL ON FUNCTION capture_authority_time_current(jsonb,timestamptz) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION capture_authority_time_current(jsonb,timestamptz) TO pdos_next_app"
    )
    for table, column in NULLABLE:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
    _constraints()
    _replace()


def downgrade():
    # No replacement, truncation or invented deadlines for retained ordinary captures.
    for table, column in NULLABLE:
        if (
            op.get_bind()
            .execute(text(f'SELECT EXISTS(SELECT 1 FROM "{table}" WHERE "{column}" IS NULL)'))
            .scalar_one()
        ):
            raise RuntimeError("Retained unbounded B6 captures prevent downgrade")
    _replace(reverse=True)
    _constraints(reverse=True)
    for table, column in NULLABLE:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')
    op.execute("DROP FUNCTION capture_authority_time_current(jsonb,timestamptz)")
