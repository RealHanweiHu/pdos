# ruff: noqa: E501
"""Frozen next_0003 DDL; independent of future model imports."""

TABLES = (
    "definition_revisions",
    "uploaded_originals",
    "definition_specs",
    "definition_sources",
    "model_budget_reservations",
    "model_invocations",
    "inbox_deliveries",
)

SCHEMA_SQL = (
    """
CREATE TABLE definition_revisions (
	product_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	parent_definition_id UUID, 
	title VARCHAR(200) NOT NULL, 
	purpose TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	use_cases JSONB NOT NULL, 
	requirements JSONB NOT NULL, 
	constraints JSONB NOT NULL, 
	unknowns JSONB NOT NULL, 
	exclusions JSONB NOT NULL, 
	change_reason TEXT NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, id), 
	UNIQUE (tenant_id, product_id, revision), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, product_id, parent_definition_id) REFERENCES definition_revisions (tenant_id, product_id, id), 
	CHECK (status = 'draft'), 
	CHECK (visibility IN ('private','product')), 
	CHECK (revision > 0 AND parent_definition_id IS DISTINCT FROM id)
)

""",
    """CREATE INDEX ix_definition_revisions_tenant_id ON definition_revisions (tenant_id)""",
    """
CREATE TABLE uploaded_originals (
	product_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	filename VARCHAR(200) NOT NULL, 
	source_label VARCHAR(200) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	media_type VARCHAR(100) NOT NULL, 
	byte_count INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	storage_key VARCHAR(300) NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	parse_code VARCHAR(80), 
	locator_map JSONB NOT NULL, 
	scan_status VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (visibility IN ('private','product')), 
	CHECK (byte_count > 0 AND byte_count <= 8388608), 
	CHECK (status IN ('uploaded','parsed','needs_ocr','failed')), 
	UNIQUE (storage_key)
)

""",
    """CREATE INDEX ix_uploaded_originals_tenant_id ON uploaded_originals (tenant_id)""",
    """
CREATE TABLE definition_specs (
	product_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	key VARCHAR(80) NOT NULL, 
	parameter VARCHAR(200) NOT NULL, 
	value_type VARCHAR(16) NOT NULL, 
	availability VARCHAR(24) NOT NULL, 
	value NUMERIC(38, 12), 
	lower NUMERIC(38, 12), 
	upper NUMERIC(38, 12), 
	text TEXT, 
	unit VARCHAR(80), 
	tolerance NUMERIC(38, 12), 
	test_conditions JSONB NOT NULL, 
	method TEXT, 
	acceptance_criterion TEXT, 
	nature VARCHAR(16) NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	owner_id UUID, 
	reason TEXT NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, definition_id, id), 
	UNIQUE (tenant_id, definition_id, key), 
	FOREIGN KEY(tenant_id, product_id, definition_id) REFERENCES definition_revisions (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (value_type IN ('number','range','text')), 
	CHECK (availability IN ('known','unknown','conflicted','not_applicable')), 
	CHECK (nature IN ('observed','extracted','computed','inferred','decided')), 
	CHECK (state IN ('proposed','needs_confirmation')), 
	CHECK (tolerance IS NULL OR tolerance >= 0), 
	CHECK (lower IS NULL OR upper IS NULL OR lower <= upper), 
	CHECK (availability = 'known' OR (value IS NULL AND lower IS NULL AND upper IS NULL AND text IS NULL AND tolerance IS NULL)), 
	CHECK (availability <> 'known' OR (value_type = 'number' AND value IS NOT NULL AND lower IS NULL AND upper IS NULL AND text IS NULL AND unit IS NOT NULL) OR (value_type = 'range' AND lower IS NOT NULL AND upper IS NOT NULL AND value IS NULL AND text IS NULL AND unit IS NOT NULL) OR (value_type = 'text' AND text IS NOT NULL AND value IS NULL AND lower IS NULL AND upper IS NULL AND tolerance IS NULL))
)

""",
    """CREATE INDEX ix_definition_specs_tenant_id ON definition_specs (tenant_id)""",
    """
CREATE TABLE definition_sources (
	product_id UUID NOT NULL, 
	definition_id UUID NOT NULL, 
	artifact_id UUID NOT NULL, 
	source_revision INTEGER NOT NULL, 
	line INTEGER NOT NULL, 
	quote TEXT NOT NULL, 
	spec_keys JSONB NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, product_id, definition_id) REFERENCES definition_revisions (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, product_id, artifact_id) REFERENCES artifact_versions (tenant_id, product_id, id), 
	CHECK (source_revision > 0 AND line > 0)
)

""",
    """CREATE INDEX ix_definition_sources_tenant_id ON definition_sources (tenant_id)""",
    """
CREATE TABLE model_budget_reservations (
	run_id UUID NOT NULL, 
	call_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	reserved INTEGER NOT NULL, 
	charged INTEGER, 
	status VARCHAR(16) NOT NULL, 
	error_code VARCHAR(80), 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, call_id), 
	FOREIGN KEY(tenant_id, run_id) REFERENCES runs (tenant_id, id), 
	CHECK (status IN ('reserved','completed','rejected','unknown')), 
	CHECK (reserved > 0 AND (charged IS NULL OR charged >= 0))
)

""",
    """CREATE INDEX ix_model_budget_reservations_tenant_id ON model_budget_reservations (tenant_id)""",
    """
CREATE TABLE model_invocations (
	run_id UUID NOT NULL, 
	step_key VARCHAR(80) NOT NULL, 
	input_digest VARCHAR(64) NOT NULL, 
	provider_version VARCHAR(160) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	candidate JSONB, 
	error_code VARCHAR(80), 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, run_id, step_key), 
	FOREIGN KEY(tenant_id, run_id) REFERENCES runs (tenant_id, id), 
	CHECK (status IN ('started','completed','unknown','rejected'))
)

""",
    """CREATE INDEX ix_model_invocations_tenant_id ON model_invocations (tenant_id)""",
    """
CREATE TABLE inbox_deliveries (
	event_id UUID NOT NULL, 
	product_id UUID NOT NULL, 
	consumer VARCHAR(80) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	workflow_id VARCHAR(200), 
	received_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, consumer, event_id), 
	FOREIGN KEY(tenant_id, event_id) REFERENCES outbox_events (tenant_id, id), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	CHECK (status IN ('pending','received','ignored'))
)

""",
    """CREATE INDEX ix_inbox_deliveries_tenant_id ON inbox_deliveries (tenant_id)""",
)
