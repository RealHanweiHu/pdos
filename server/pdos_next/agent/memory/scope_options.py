"""Products and proposals the owner can pick as a note's scope (D301).

The “我的记忆” page lists them when the owner adds or edits a note by hand.
Only objects the owner can read now are listed (ordinary row-level security plus
category access, the same check ``notes.resolve_scope`` applies on save).
"""

from typing import Literal

from pydantic import Field
from sqlalchemy import func, select

from pdos_next.core.schema_base import StrictModel

PAGE = 50


class ScopeOptions(StrictModel):
    kind: Literal["product", "proposal"]
    query: str = Field(default="", max_length=80)


def options(session, data):
    from pdos_next.core.models import Category

    from .notes import _models

    model, column, category = _models()[data.kind]
    title = getattr(model, column)
    query = (
        select(model.id, title, Category.name)
        .join(Category, Category.id == category)
        .where(func.category_access(model.tenant_id, category))
    )
    if data.query.strip():
        query = query.where(title.icontains(data.query.strip(), autoescape=True))
    rows = session.execute(query.order_by(title, model.id).limit(PAGE + 1)).all()
    return {
        "version": "memory-scope-options/v1", "kind": data.kind,
        "items": [{"id": str(identity), "label": f"{name} · {owner}"}
                  for identity, name, owner in rows[:PAGE]],
        "more": len(rows) > PAGE,
    }
