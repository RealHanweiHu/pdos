"""Allow the application to invoke existing invoker atom assertions.

These helpers keep caller RLS; no new business table privileges are granted.
"""

from alembic import op

revision = "s0_0417"
down_revision = "s0_0416"
branch_labels = None
depends_on = None

FUNCTIONS = (
    "assert_capa_fact_origin(uuid,uuid,uuid,uuid,uuid,uuid,integer,text,text,jsonb,jsonb,text,uuid)",
    "assert_capa_fact_source_closure(uuid,uuid,jsonb,jsonb,jsonb,text,uuid)",
    "assert_capa_publication_atom(text,uuid,uuid)",
    "assert_quality_change_receipt(uuid,uuid,uuid,integer,text,text,uuid,text)",
    "assert_quality_followup_proof(uuid,uuid,uuid,text,jsonb,timestamp with time zone)",
    "assert_quality_followup_receipt(uuid,uuid,uuid,integer,text,text,uuid,text,text)",
)


def upgrade():
    for function in FUNCTIONS:
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO pdos_next_app")


def downgrade():
    for function in FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {function} FROM pdos_next_app")
