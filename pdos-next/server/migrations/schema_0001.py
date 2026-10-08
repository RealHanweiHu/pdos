"""Frozen schema for next_0001; generated once from initial metadata."""

SCHEMA_SQL = [
    """
CREATE TABLE principals (
	name VARCHAR(160) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	CHECK (kind IN ('human','agent'))
)

""",
    """CREATE INDEX ix_principals_tenant_id ON principals (tenant_id)""",
    """
CREATE TABLE login_sessions (
	token_hash VARCHAR(64) NOT NULL, 
	tenant_id UUID NOT NULL, 
	principal_id UUID NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id)
)

""",
    """
CREATE TABLE products (
	name VARCHAR(160) NOT NULL, 
	purpose TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	owner_id UUID NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (revision > 0)
)

""",
    """CREATE INDEX ix_products_tenant_id ON products (tenant_id)""",
    """
CREATE TABLE qualifications (
	writer_id UUID NOT NULL, 
	skill_version VARCHAR(80) NOT NULL, 
	provider_version VARCHAR(160) NOT NULL, 
	operation VARCHAR(80) NOT NULL, 
	purpose VARCHAR(80) NOT NULL, 
	evaluation_kind VARCHAR(16) NOT NULL, 
	evaluation_ref VARCHAR(200) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	active BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), 
	CHECK (evaluation_kind IN ('synthetic','real'))
)

""",
    """CREATE INDEX ix_qualifications_tenant_id ON qualifications (tenant_id)""",
    """
CREATE TABLE grants (
	product_id UUID NOT NULL, 
	principal_id UUID NOT NULL, 
	can_write BOOLEAN NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, principal_id), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id)
)

""",
    """CREATE INDEX ix_grants_tenant_id ON grants (tenant_id)""",
    """
CREATE TABLE artifact_versions (
	product_id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	source_label VARCHAR(200) NOT NULL, 
	content TEXT NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (visibility IN ('private','product')), 
	CHECK (status IN ('active','withdrawn'))
)

""",
    """CREATE INDEX ix_artifact_versions_tenant_id ON artifact_versions (tenant_id)""",
    """
CREATE TABLE confirmations (
	product_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	subject_id UUID NOT NULL, 
	operation VARCHAR(80) NOT NULL, 
	revision INTEGER NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	consumed BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), 
	UNIQUE (token_hash)
)

""",
    """CREATE INDEX ix_confirmations_tenant_id ON confirmations (tenant_id)""",
    """
CREATE TABLE claims (
	product_id UUID NOT NULL, 
	artifact_id UUID NOT NULL, 
	source_revision INTEGER NOT NULL, 
	line INTEGER NOT NULL, 
	quote TEXT NOT NULL, 
	statement TEXT NOT NULL, 
	nature VARCHAR(16) NOT NULL, 
	availability VARCHAR(16) NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	human_owner_id UUID NOT NULL, 
	writer_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, product_id, artifact_id) REFERENCES artifact_versions (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, human_owner_id) REFERENCES principals (tenant_id, id), 
	CHECK (nature IN ('observed','extracted','inferred')), 
	CHECK (availability IN ('known','unknown','conflicted')), 
	CHECK (visibility IN ('private','product')), 
	CHECK (status IN ('active','reverted')), 
	CHECK (line > 0 AND revision > 0 AND source_revision > 0)
)

""",
    """CREATE INDEX ix_claims_tenant_id ON claims (tenant_id)""",
    """
CREATE TABLE claim_consumptions (
	product_id UUID NOT NULL, 
	claim_id UUID NOT NULL, 
	consumer_type VARCHAR(80) NOT NULL, 
	consumer_id UUID NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, product_id, claim_id) REFERENCES claims (tenant_id, product_id, id)
)

""",
    """CREATE INDEX ix_claim_consumptions_tenant_id ON claim_consumptions (tenant_id)""",
    """
CREATE TABLE work_requests (
	product_id UUID NOT NULL, 
	artifact_id UUID NOT NULL, 
	source_revision INTEGER NOT NULL, 
	goal TEXT NOT NULL, 
	outcome_spec JSONB NOT NULL, 
	accountable_owner_id UUID NOT NULL, 
	"authorization" JSONB NOT NULL, 
	max_actions INTEGER NOT NULL, 
	stop_condition VARCHAR(80) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	error_code VARCHAR(80), 
	result_id UUID, 
	revision INTEGER NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, product_id, artifact_id) REFERENCES artifact_versions (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, accountable_owner_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, product_id, result_id) REFERENCES claims (tenant_id, product_id, id), 
	CHECK (status IN ('accepted','running','waiting_input','completed','cancelled'))
)

""",
    """CREATE INDEX ix_work_requests_tenant_id ON work_requests (tenant_id)""",
    """
CREATE TABLE runs (
	product_id UUID NOT NULL, 
	work_id UUID NOT NULL, 
	requester_id UUID NOT NULL, 
	writer_id UUID, 
	cancel_epoch INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	skill_version VARCHAR(80) NOT NULL, 
	provider_version VARCHAR(160), 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (tenant_id, work_id), 
	FOREIGN KEY(tenant_id, product_id, work_id) REFERENCES work_requests (tenant_id, product_id, id), 
	FOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, writer_id) REFERENCES principals (tenant_id, id), 
	CHECK (status IN ('queued','running','waiting','succeeded','failed','cancelled'))
)

""",
    """CREATE INDEX ix_runs_tenant_id ON runs (tenant_id)""",
    """
CREATE TABLE action_receipts (
	product_id UUID NOT NULL, 
	command_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	requester_id UUID NOT NULL, 
	operation VARCHAR(80) NOT NULL, 
	subject_type VARCHAR(32) NOT NULL, 
	subject_id UUID NOT NULL, 
	subject_revision INTEGER NOT NULL, 
	visibility VARCHAR(16) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	intent_digest VARCHAR(64) NOT NULL, 
	run_id UUID, 
	result JSONB NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, id), 
	UNIQUE (tenant_id, product_id, intent_digest), 
	FOREIGN KEY(tenant_id, product_id) REFERENCES products (tenant_id, id), 
	FOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, requester_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, run_id) REFERENCES runs (tenant_id, id)
)

""",
    """CREATE INDEX ix_action_receipts_tenant_id ON action_receipts (tenant_id)""",
    """
CREATE TABLE request_keys (
	actor_id UUID NOT NULL, 
	key VARCHAR(160) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	receipt_id UUID NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tenant_id, actor_id, key), 
	FOREIGN KEY(tenant_id, actor_id) REFERENCES principals (tenant_id, id), 
	FOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id)
)

""",
    """CREATE INDEX ix_request_keys_tenant_id ON request_keys (tenant_id)""",
    """
CREATE TABLE audit_entries (
	receipt_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	operation VARCHAR(80) NOT NULL, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id)
)

""",
    """CREATE INDEX ix_audit_entries_tenant_id ON audit_entries (tenant_id)""",
    """
CREATE TABLE outbox_events (
	receipt_id UUID NOT NULL, 
	type VARCHAR(80) NOT NULL, 
	subject_id UUID NOT NULL, 
	subject_revision INTEGER NOT NULL, 
	schema_version INTEGER NOT NULL, 
	actor_id UUID NOT NULL, 
	correlation_id UUID NOT NULL, 
	delivered_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, receipt_id) REFERENCES action_receipts (tenant_id, id)
)

""",
    """CREATE INDEX ix_outbox_events_tenant_id ON outbox_events (tenant_id)""",
]
TABLES = [
    "principals",
    "login_sessions",
    "products",
    "qualifications",
    "artifact_versions",
    "confirmations",
    "grants",
    "claims",
    "claim_consumptions",
    "work_requests",
    "runs",
    "action_receipts",
    "audit_entries",
    "outbox_events",
    "request_keys",
]
