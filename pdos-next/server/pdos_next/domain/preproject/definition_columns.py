"""Lazy M3 schema supplement; the unmerged B3 baseline ORM remains usable."""

from sqlalchemy import Column, Integer, MetaData, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next.domain.products.models import DefinitionSpecRow

SPEC_TABLE = DefinitionSpecRow.__table__.to_metadata(MetaData())
for name, kind in {
    "parameter_id": Uuid,
    "parameter_version": Integer,
    "item_status": Text,
    "condition_note": Text,
    "modality": Text,
    "exceptions": JSONB,
    "applicable_variants": JSONB,
    "source_refs": JSONB,
    "origin": Text,
    "writer_id": Uuid,
    "run_id": Uuid,
    "confirmed_by": Uuid,
    "receipt_id": Uuid,
}.items():
    SPEC_TABLE.append_column(Column(name, kind))
