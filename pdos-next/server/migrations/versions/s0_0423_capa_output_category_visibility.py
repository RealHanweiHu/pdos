"""B5 link outputs preserve the category visibility vocabulary."""

import hashlib

from alembic import op
from sqlalchemy import text

revision = "s0_0423"
down_revision = "s0_0422"
branch_labels = None
depends_on = None

OLD = "x->>'visibility' IN ('private','product')"
NEW = "x->>'visibility' IN ('private','category','audience')"
BEFORE = "c18f68dc70f7a841f52e0b287024569fb7d56d69c9aba77beccb50e4c8833011"
AFTER = "28bdf5a9023efe39f7a8ef17d7130c90b1c74f7e9c34f99a471d385a9a4e27c1"


def _replace(reverse=False):
    body, definition = (
        op.get_bind()
        .execute(
            text(
                "SELECT prosrc,pg_get_functiondef(oid) FROM pg_proc "
                "WHERE oid='require_capa_link_atom()'::regprocedure"
            )
        )
        .one()
    )
    old, new, expected, desired = (
        (NEW, OLD, AFTER, BEFORE) if reverse else (OLD, NEW, BEFORE, AFTER)
    )
    if hashlib.sha256(body.encode()).hexdigest() != expected:
        raise RuntimeError("Unreviewed CAPA link predecessor")
    if body.count(old) != 1 or definition.count(old) != 1:
        raise RuntimeError("Non-unique CAPA output visibility guard")
    if hashlib.sha256(body.replace(old, new).encode()).hexdigest() != desired:
        raise RuntimeError("Unexpected CAPA link visibility repair")
    op.execute(definition.replace(old, new))


def upgrade():
    _replace()


def downgrade():
    _replace(reverse=True)
