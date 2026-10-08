"""Per-tenant robots.txt cache for the deterministic research crawler."""

from alembic import op

revision = "0421_research_robots_cache"
down_revision = "0420_research_crawl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cehub_evidence.research_robots_cache (
            id UUID NOT NULL,
            tenant_id UUID NOT NULL,
            hostname VARCHAR(253) NOT NULL,
            robots_digest VARCHAR(64) NOT NULL,
            disallow_prefixes JSONB DEFAULT '[]'::jsonb NOT NULL,
            allow_prefixes JSONB DEFAULT '[]'::jsonb NOT NULL,
            crawl_delay_seconds INTEGER,
            sitemap_urls JSONB DEFAULT '[]'::jsonb NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_research_robots_cache PRIMARY KEY (id),
            CONSTRAINT ck_research_robots_cache_arrays CHECK (
                jsonb_typeof(disallow_prefixes)='array'
                AND jsonb_typeof(allow_prefixes)='array'
                AND jsonb_typeof(sitemap_urls)='array'),
            CONSTRAINT ck_research_robots_cache_delay_valid CHECK (
                crawl_delay_seconds IS NULL OR crawl_delay_seconds BETWEEN 0 AND 86400),
            CONSTRAINT ck_research_robots_cache_window_valid CHECK (expires_at>fetched_at),
            CONSTRAINT uq_research_robots_cache_host UNIQUE (tenant_id, hostname)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cehub_evidence.research_robots_cache;")
