"""Persist immutable evidence text, leaving absent historical bodies explicit."""

import sqlalchemy as sa
from alembic import op

revision = "0101_evidence_bodies"
down_revision = "0100_product_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_evidence.evidence_contents (\n\ttenant_id "
        "UUID NOT NULL, \n\tcontent_digest VARCHAR(64) NOT NULL, \n\tbody"
        " TEXT NOT NULL, \n\tbyte_size INTEGER NOT NULL, \n\tstored_at TI"
        "MESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, \n"
        "\tCONSTRAINT pk_evidence_contents PRIMARY KEY (tenant_id, con"
        "tent_digest), \n\tCONSTRAINT ck_evidence_contents_body_size CH"
        "ECK (byte_size > 0 AND byte_size <= 2097152 AND octet_length"
        "(body)=byte_size), \n\tCONSTRAINT ck_evidence_contents_body_di"
        "gest CHECK (content_digest=encode(sha256(convert_to(body,'UT"
        "F8')),'hex')), \n\tCONSTRAINT fk_evidence_contents_tenant_id_t"
        "enants FOREIGN KEY(tenant_id) REFERENCES cehub_core.tenants "
        "(id) ON DELETE RESTRICT\n)\n\n;"
    )
    op.execute(
        "\n    CREATE FUNCTION cehub_evidence.protect_evidence_content"
        "() RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_c"
        "atalog AS $$\n    BEGIN\n      RAISE EXCEPTION 'Captured evide"
        "nce content is immutable' USING ERRCODE='42501';\n    END $$;"
        "\n    CREATE TRIGGER protect_evidence_content BEFORE UPDATE O"
        "R DELETE ON cehub_evidence.evidence_contents\n      FOR EACH "
        "ROW EXECUTE FUNCTION cehub_evidence.protect_evidence_content"
        "();\n    REVOKE ALL ON FUNCTION cehub_evidence.protect_eviden"
        "ce_content() FROM PUBLIC;\n    "
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_evidence.evidence_contents)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard captured evidence content")
    op.drop_table("evidence_contents", schema="cehub_evidence")
    op.execute("DROP FUNCTION cehub_evidence.protect_evidence_content()")
