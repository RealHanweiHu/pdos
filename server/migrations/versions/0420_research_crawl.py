"""Crawl frontier and fenced crawl runs for the local research index."""

from alembic import op

revision = "0420_research_crawl"
down_revision = "0419_user_work_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cehub_evidence.research_crawl_frontier (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            market_space_id UUID NOT NULL,
            product_line_id UUID,
            source_id UUID NOT NULL,
            owner_user_id UUID NOT NULL,
            url VARCHAR(1024) NOT NULL,
            url_key VARCHAR(64) NOT NULL,
            hostname VARCHAR(253) NOT NULL,
            depth INTEGER NOT NULL,
            discovered_from VARCHAR(16) NOT NULL,
            discovered_from_snapshot_id UUID,
            status VARCHAR(16) NOT NULL,
            next_attempt_at TIMESTAMP WITH TIME ZONE,
            lease_token UUID,
            lease_expires_at TIMESTAMP WITH TIME ZONE,
            attempts INTEGER DEFAULT 0 NOT NULL,
            consecutive_failures INTEGER DEFAULT 0 NOT NULL,
            last_attempt_at TIMESTAMP WITH TIME ZONE,
            last_success_at TIMESTAMP WITH TIME ZONE,
            last_snapshot_id UUID,
            last_error_code VARCHAR(64),
            last_error_message TEXT,
            version INTEGER DEFAULT 1 NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT pk_research_crawl_frontier PRIMARY KEY (id),
            CONSTRAINT ck_research_crawl_frontier_state_allowed CHECK (
                discovered_from IN ('seed','sitemap','feed','link')
                AND status IN ('pending','running','done','skipped','failed')),
            CONSTRAINT ck_research_crawl_frontier_required_content CHECK (
                depth BETWEEN 0 AND 5 AND attempts>=0 AND consecutive_failures>=0
                AND version>0 AND btrim(url)<>'' AND btrim(url_key)<>'' AND btrim(hostname)<>''),
            CONSTRAINT ck_research_crawl_frontier_schedule_state CHECK (
                (status='pending')=(next_attempt_at IS NOT NULL)),
            CONSTRAINT ck_research_crawl_frontier_lease_pair CHECK (
                (lease_token IS NULL)=(lease_expires_at IS NULL)
                AND (lease_token IS NULL OR status='running')),
            CONSTRAINT uq_research_crawl_frontier_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT uq_research_crawl_frontier_url UNIQUE (tenant_id, source_id, url_key),
            CONSTRAINT fk_research_crawl_frontier_space FOREIGN KEY (tenant_id, market_space_id)
                REFERENCES cehub_product.market_spaces (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_frontier_line FOREIGN KEY
                (tenant_id, market_space_id, product_line_id)
                REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_frontier_source FOREIGN KEY (tenant_id, source_id)
                REFERENCES cehub_evidence.research_sources (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_frontier_seed_snapshot FOREIGN KEY
                (tenant_id, discovered_from_snapshot_id)
                REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_frontier_snapshot FOREIGN KEY (tenant_id, last_snapshot_id)
                REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_frontier_owner FOREIGN KEY (tenant_id, owner_user_id)
                REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT
        );

        CREATE INDEX ix_research_crawl_frontier_due
            ON cehub_evidence.research_crawl_frontier (tenant_id, status, next_attempt_at);

        CREATE TABLE cehub_evidence.research_crawl_runs (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            frontier_id UUID NOT NULL,
            frontier_version INTEGER NOT NULL,
            hostname VARCHAR(253) NOT NULL,
            status VARCHAR(16) NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL,
            finished_at TIMESTAMP WITH TIME ZONE,
            snapshot_id UUID,
            content_changed BOOLEAN,
            links_added INTEGER,
            error_code VARCHAR(64),
            error_message TEXT,
            CONSTRAINT pk_research_crawl_runs PRIMARY KEY (id),
            CONSTRAINT ck_research_crawl_runs_state_allowed CHECK (
                status IN ('running','completed','failed','skipped_robots','timed_out')
                AND frontier_version>0),
            CONSTRAINT ck_research_crawl_runs_finish_state CHECK (
                (status='running')=(finished_at IS NULL)),
            CONSTRAINT ck_research_crawl_runs_result_consistent CHECK (
                (status='completed')=(snapshot_id IS NOT NULL)),
            CONSTRAINT ck_research_crawl_runs_links_valid CHECK
                (links_added IS NULL OR links_added>=0),
            CONSTRAINT uq_research_crawl_run_scope UNIQUE (tenant_id, id),
            CONSTRAINT fk_research_crawl_runs_frontier FOREIGN KEY (tenant_id, frontier_id)
                REFERENCES cehub_evidence.research_crawl_frontier (tenant_id, id)
                ON DELETE RESTRICT,
            CONSTRAINT fk_research_crawl_runs_snapshot FOREIGN KEY (tenant_id, snapshot_id)
                REFERENCES cehub_evidence.evidence_snapshots (tenant_id, id) ON DELETE RESTRICT
        );

        CREATE UNIQUE INDEX ix_research_crawl_runs_running
            ON cehub_evidence.research_crawl_runs (tenant_id, frontier_id)
            WHERE status='running';

        CREATE INDEX ix_research_crawl_runs_host_time
            ON cehub_evidence.research_crawl_runs (tenant_id, hostname, started_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS cehub_evidence.research_crawl_runs;
        DROP TABLE IF EXISTS cehub_evidence.research_crawl_frontier;
        """
    )
