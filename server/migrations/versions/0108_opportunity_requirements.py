"""Many-to-many requirement snapshots pinned to opportunity revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0108_opportunity_requirements"
down_revision = "0107_vuvf_experiments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE cehub_product.opportunity_requirements (\n\tid U"
        "UID NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tmarket_space_id U"
        "UID NOT NULL, \n\topportunity_id UUID NOT NULL, \n\trequirement_"
        "id UUID NOT NULL, \n\trequirement_snapshot JSONB NOT NULL, \n\tr"
        "eference JSONB NOT NULL, \n\trationale TEXT NOT NULL, \n\tcreate"
        "d_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT "
        "NULL, \n\tCONSTRAINT pk_opportunity_requirements PRIMARY KEY ("
        "id), \n\tCONSTRAINT uq_opportunity_requirements_pair UNIQUE (t"
        "enant_id, opportunity_id, requirement_id), \n\tCONSTRAINT fk_o"
        "pportunity_requirements_opportunity FOREIGN KEY(tenant_id, m"
        "arket_space_id, opportunity_id) REFERENCES cehub_product.opp"
        "ortunities (tenant_id, market_space_id, id) ON DELETE RESTRI"
        "CT, \n\tCONSTRAINT fk_opportunity_requirements_requirement FOR"
        "EIGN KEY(tenant_id, requirement_id) REFERENCES cehub_project"
        ".requirements (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAI"
        "NT ck_opportunity_requirements_required_link_basis CHECK (bt"
        "rim(rationale)<>'' AND jsonb_typeof(requirement_snapshot)='o"
        "bject' AND jsonb_typeof(reference)='object')\n)\n\n"
    )
    op.execute(
        "\nCREATE FUNCTION cehub_product.protect_opportunity_requireme"
        "nt() RETURNS trigger\nLANGUAGE plpgsql SET search_path=pg_cat"
        "alog AS $$\nBEGIN\n IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'O"
        "pportunity requirement history is immutable' USING ERRCODE='"
        "42501'; END IF;\n IF NEW.requirement_snapshot->>'id' IS DISTI"
        "NCT FROM NEW.requirement_id::text OR NEW.requirement_snapsho"
        "t->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR NEW."
        "reference->>'ref_id' IS DISTINCT FROM NEW.requirement_id::te"
        "xt OR NEW.reference->>'tenant_id' IS DISTINCT FROM NEW.tenan"
        "t_id::text OR NEW.reference->>'kind' IS DISTINCT FROM 'requi"
        "rement' OR NEW.reference->>'project_id' IS NOT NULL OR NEW.r"
        "eference->>'digest' IS NULL OR (NEW.reference->>'digest') !~"
        " '^[0-9a-f]{64}$' OR NEW.reference->>'as_of' IS NULL OR (NEW"
        ".reference->>'as_of')::timestamptz IS DISTINCT FROM (NEW.req"
        "uirement_snapshot->>'updated_at')::timestamptz THEN\n   RAISE"
        " EXCEPTION 'Requirement snapshot and reference mismatch' USI"
        "NG ERRCODE='23514';\n END IF;\n RETURN NEW;\nEND $$;\nCREATE TRI"
        "GGER protect_opportunity_requirement BEFORE INSERT OR UPDATE"
        " OR DELETE ON cehub_product.opportunity_requirements\n FOR EA"
        "CH ROW EXECUTE FUNCTION cehub_product.protect_opportunity_re"
        "quirement();\nREVOKE ALL ON FUNCTION cehub_product.protect_op"
        "portunity_requirement() FROM PUBLIC;\n"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM cehub_product.opportunity_requirements)"))
        .scalar_one()
    ):
        raise RuntimeError("Refusing to discard requirement trace history")
    op.drop_table("opportunity_requirements", schema="cehub_product")
    op.execute("DROP FUNCTION cehub_product.protect_opportunity_requirement()")
