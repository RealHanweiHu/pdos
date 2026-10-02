"""Private RFQ source files before project creation."""
# ruff: noqa: E501
from alembic import op

revision = "0403_product_source_files"
down_revision = "0402_definition_inheritance"
branch_labels = None
depends_on = None

DDL = "\nCREATE TABLE cehub_product.product_source_files (\n\tid UUID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id UUID NOT NULL, \n\tproduct_line_id UUID, \n\tuploaded_by_user_id UUID NOT NULL, \n\trequest_id UUID NOT NULL, \n\trequest_digest VARCHAR(64) NOT NULL, \n\tfilename TEXT NOT NULL, \n\tmedia_type TEXT NOT NULL, \n\tclassification VARCHAR(16) NOT NULL, \n\tsize_bytes BIGINT NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tobject_key TEXT NOT NULL, \n\tparser_version VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(32) DEFAULT 'awaiting_upload' NOT NULL, \n\terror_code VARCHAR(128), \n\tfragments JSONB DEFAULT '[]'::jsonb NOT NULL, \n\textraction_metadata JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tversion INTEGER DEFAULT '1' NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tCONSTRAINT pk_product_source_files PRIMARY KEY (id), \n\tCONSTRAINT uq_product_source_files_space_id UNIQUE (tenant_id, market_space_id, id), \n\tCONSTRAINT uq_product_source_files_request UNIQUE (tenant_id, market_space_id, uploaded_by_user_id, request_id), \n\tCONSTRAINT uq_product_source_files_object_key UNIQUE (object_key), \n\tCONSTRAINT ck_product_source_files_bounds CHECK (size_bytes BETWEEN 1 AND 20971520 AND version>0 AND btrim(filename)<>''), \n\tCONSTRAINT ck_product_source_files_digests CHECK (sha256 ~ '^[a-f0-9]{64}$' AND request_digest ~ '^[a-f0-9]{64}$'), \n\tCONSTRAINT ck_product_source_files_classification CHECK (classification IN ('internal','confidential','restricted')), \n\tCONSTRAINT ck_product_source_files_status CHECK (status IN ('awaiting_upload','uploaded','extracted','ocr_required','failed')), \n\tCONSTRAINT ck_product_source_files_extraction CHECK (jsonb_typeof(fragments)='array' AND jsonb_typeof(extraction_metadata)='object'), \n\tCONSTRAINT fk_product_source_files_space FOREIGN KEY(tenant_id, market_space_id) REFERENCES cehub_product.market_spaces (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_source_files_line FOREIGN KEY(tenant_id, market_space_id, product_line_id) REFERENCES cehub_product.product_nodes (tenant_id, market_space_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_product_source_files_uploader FOREIGN KEY(tenant_id, uploaded_by_user_id) REFERENCES cehub_core.users (tenant_id, id) ON DELETE RESTRICT\n)\n\n"

GUARD = r"""
CREATE FUNCTION cehub_product.guard_product_source_file() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'RFQ file history is retained; revoke the reference'; END IF;
 IF NEW.product_line_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM cehub_product.product_nodes WHERE tenant_id=NEW.tenant_id AND market_space_id=NEW.market_space_id AND id=NEW.product_line_id AND level='line')
 THEN RAISE EXCEPTION 'File line must belong to the market space'; END IF;
 IF NEW.object_key IS DISTINCT FROM 'tenants/'||NEW.tenant_id::text||'/private-product-files/'||NEW.market_space_id::text||'/'||NEW.id::text
  OR NEW.parser_version<>'product-rfq-pdf-xlsx.v1'
  OR NEW.media_type NOT IN ('application/pdf','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
 THEN RAISE EXCEPTION 'File storage and parser identity must be server-bound'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.version<>1 OR NEW.status<>'awaiting_upload' OR NEW.fragments<>'[]'::jsonb OR NEW.extraction_metadata<>'{}'::jsonb OR NEW.revoked_at IS NOT NULL
  THEN RAISE EXCEPTION 'File starts with metadata only'; END IF;
 ELSE
  IF (NEW.id,NEW.tenant_id,NEW.market_space_id,NEW.product_line_id,NEW.uploaded_by_user_id,NEW.request_id,NEW.request_digest,NEW.filename,NEW.media_type,NEW.classification,NEW.size_bytes,NEW.sha256,NEW.object_key,NEW.parser_version,NEW.created_at,NEW.version)
   IS DISTINCT FROM (OLD.id,OLD.tenant_id,OLD.market_space_id,OLD.product_line_id,OLD.uploaded_by_user_id,OLD.request_id,OLD.request_digest,OLD.filename,OLD.media_type,OLD.classification,OLD.size_bytes,OLD.sha256,OLD.object_key,OLD.parser_version,OLD.created_at,OLD.version+1)
  THEN RAISE EXCEPTION 'File identity is immutable and version must advance once'; END IF;
  IF OLD.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'Revoked file cannot be changed'; END IF;
  IF OLD.status IN ('extracted','ocr_required') AND (NEW.status,NEW.fragments,NEW.extraction_metadata,NEW.error_code) IS DISTINCT FROM (OLD.status,OLD.fragments,OLD.extraction_metadata,OLD.error_code)
  THEN RAISE EXCEPTION 'Parsed source fragments are immutable'; END IF;
  IF OLD.status='awaiting_upload' AND NEW.status NOT IN ('awaiting_upload','uploaded')
   OR OLD.status IN ('uploaded','failed') AND NEW.status NOT IN ('uploaded','failed','extracted','ocr_required')
  THEN RAISE EXCEPTION 'Invalid file state transition'; END IF;
 END IF;
 IF (NEW.status='extracted' AND jsonb_array_length(NEW.fragments)=0)
  OR (NEW.status<>'extracted' AND NEW.fragments<>'[]'::jsonb)
 THEN RAISE EXCEPTION 'Extraction status must reflect actual parsed fragments'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER product_source_file_guard BEFORE INSERT OR UPDATE OR DELETE ON cehub_product.product_source_files
 FOR EACH ROW EXECUTE FUNCTION cehub_product.guard_product_source_file();
REVOKE ALL ON cehub_product.product_source_files FROM PUBLIC,pdos_agent;
REVOKE ALL ON FUNCTION cehub_product.guard_product_source_file() FROM PUBLIC,pdos_agent;
"""


def upgrade() -> None:
    op.execute(DDL)
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM cehub_product.product_source_files) THEN RAISE EXCEPTION 'Cannot discard RFQ file history'; END IF; END $$;")
    op.execute("DROP TABLE cehub_product.product_source_files; DROP FUNCTION cehub_product.guard_product_source_file();")
