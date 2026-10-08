"""Derived full-text projection over crawled research snapshots."""

from alembic import op

revision = "0422_research_index_documents"
down_revision = "0421_research_robots_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cehub_product.research_index_documents (
            tenant_id UUID NOT NULL,
            snapshot_id UUID NOT NULL,
            market_space_id UUID NOT NULL,
            product_line_id UUID,
            source_id UUID NOT NULL,
            content_digest VARCHAR(64) NOT NULL,
            url VARCHAR(1024) NOT NULL,
            title VARCHAR(512) DEFAULT '' NOT NULL,
            lang VARCHAR(16) NOT NULL,
            extracted_text TEXT NOT NULL,
            doc_tsv TSVECTOR NOT NULL,
            captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
            indexed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT pk_research_index_documents PRIMARY KEY (tenant_id, snapshot_id),
            CONSTRAINT ck_research_index_documents_required_content CHECK (
                btrim(url)<>'' AND btrim(content_digest)<>'' AND char_length(title)<=512),
            CONSTRAINT fk_research_index_documents_space FOREIGN KEY (tenant_id, market_space_id)
                REFERENCES cehub_product.market_spaces (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_index_documents_line FOREIGN KEY
                (tenant_id, market_space_id, product_line_id)
                REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_research_index_documents_source FOREIGN KEY (tenant_id, source_id)
                REFERENCES cehub_evidence.research_sources (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_index_documents_snapshot FOREIGN KEY (tenant_id, snapshot_id)
                REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT
        );

        CREATE INDEX ix_research_index_documents_tsv
            ON cehub_product.research_index_documents USING gin (doc_tsv);

        CREATE INDEX ix_research_index_documents_scope
            ON cehub_product.research_index_documents (tenant_id, market_space_id)
            WHERE product_line_id IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cehub_product.research_index_documents;")
