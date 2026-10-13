"""Persist the parser-declared location inventory; NULL stays honestly unknown."""
# ruff: noqa: E501 -- frozen SQL literals retain the checked representation

SCHEMA_SQL = (
    'ALTER TABLE uploaded_originals ADD COLUMN parse_manifest jsonb',
    "ALTER TABLE uploaded_originals ADD CONSTRAINT uploaded_originals_parse_manifest_shape CHECK (parse_manifest IS NULL OR (jsonb_typeof(parse_manifest)='object' AND (parse_manifest ? 'parser_version') AND (parse_manifest ? 'basis') AND (parse_manifest ? 'expected_locations') AND (parse_manifest->>'basis') IN ('line','page','cell') AND jsonb_typeof(parse_manifest->'expected_locations')='array'))",
)

DOWNGRADE_SQL = (
    'ALTER TABLE uploaded_originals DROP CONSTRAINT uploaded_originals_parse_manifest_shape',
    'ALTER TABLE uploaded_originals DROP COLUMN parse_manifest',
)
