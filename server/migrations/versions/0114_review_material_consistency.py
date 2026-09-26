"""Serialize project technical material writes with review source capture."""

from alembic import op

revision = "0114_review_material_consistency"
down_revision = "0113_case_reviews"
branch_labels = None
depends_on = None

TARGETS = (
    ("cehub_product", "specifications"),
    ("cehub_quality", "test_plans"),
    ("cehub_quality", "test_cases"),
    ("cehub_quality", "test_runs"),
    ("cehub_quality", "test_reports"),
    ("cehub_quality", "certifications"),
)


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION cehub_project.serialize_review_material_writ"
        "e() RETURNS trigger\n    LANGUAGE plpgsql SET search_path=pg_"
        "catalog AS $$\n    BEGIN\n      IF TG_OP='DELETE' THEN\n       "
        " PERFORM 1 FROM cehub_project.projects WHERE tenant_id=OLD.t"
        "enant_id AND id=OLD.project_id FOR UPDATE;\n        RETURN OL"
        "D;\n      END IF;\n      PERFORM 1 FROM cehub_project.projects"
        " WHERE tenant_id=NEW.tenant_id AND id=NEW.project_id FOR UPD"
        "ATE;\n      RETURN NEW;\n    END $$;\n    REVOKE ALL ON FUNCTIO"
        "N cehub_project.serialize_review_material_write() FROM PUBLI"
        "C;"
    )
    for schema, table in TARGETS:
        op.execute(
            f"CREATE TRIGGER serialize_review_material_write BEFORE INSERT OR UPDATE OR DELETE "
            f"ON {schema}.{table} FOR EACH ROW "
            "EXECUTE FUNCTION cehub_project.serialize_review_material_write()"
        )


def downgrade() -> None:
    for schema, table in TARGETS:
        op.execute(f"DROP TRIGGER serialize_review_material_write ON {schema}.{table}")
    op.execute("DROP FUNCTION cehub_project.serialize_review_material_write()")
