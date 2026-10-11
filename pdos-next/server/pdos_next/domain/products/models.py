from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.models import Base, Row


class DefinitionRevision(Row, Base):
    __tablename__ = "definition_revisions"
    product_id: Mapped[UUID]
    variant_id: Mapped[UUID | None] = mapped_column()
    owner_id: Mapped[UUID]
    parent_definition_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    visibility: Mapped[str] = mapped_column(String(16))
    use_cases: Mapped[list] = mapped_column(JSONB)
    requirements: Mapped[list] = mapped_column(JSONB)
    constraints: Mapped[list] = mapped_column(JSONB)
    unknowns: Mapped[list] = mapped_column(JSONB)
    exclusions: Mapped[list] = mapped_column(JSONB)
    change_reason: Mapped[str] = mapped_column(Text)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_proposal_id: Mapped[UUID | None]
    source_submission_id: Mapped[UUID | None]
    source_proposal_revision: Mapped[int | None]
    g0_decision_id: Mapped[UUID | None]
    publication_receipt_id: Mapped[UUID | None]
    derived_from_definition_id: Mapped[UUID | None]
    derived_from_definition_revision: Mapped[int | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "variant_id"],
            ["product_variants.tenant_id", "product_variants.product_id", "product_variants.id"],
            name="m3_definition_variant_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "publication_receipt_id"],
            ["action_receipts.tenant_id", "action_receipts.id"],
            name="m3_definition_publication_receipt_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "derived_from_definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.category_id",
                "definition_revisions.id",
            ],
            name="m3_definition_derived_from_fk",
        ),
        CheckConstraint(
            "(derived_from_definition_id IS NULL AND derived_from_definition_revision IS NULL) OR "
            "(derived_from_definition_id IS NOT NULL "
            "AND derived_from_definition_revision IS NOT NULL "
            "AND derived_from_definition_revision>0 "
            "AND derived_from_definition_id<>id)",
            name="m3_definition_derivation_pair",
        ),
        CheckConstraint(
            "(status='draft' AND publication_receipt_id IS NULL) OR "
            "(status='published' AND publication_receipt_id IS NOT NULL AND sealed)",
            name="m3_definition_publication_pair",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "g0_decision_id"],
            [
                "proposal_decisions.tenant_id",
                "proposal_decisions.category_id",
                "proposal_decisions.id",
            ],
            name="m3_definition_decision_fk",
            use_alter=True,
        ),
        UniqueConstraint("tenant_id", "product_id", "id"),
        Index(
            "m3_definition_model_revision",
            "tenant_id",
            "product_id",
            "revision",
            unique=True,
            postgresql_where=variant_id.is_(None),
        ),
        Index(
            "m3_definition_variant_revision",
            "tenant_id",
            "product_id",
            "variant_id",
            "revision",
            unique=True,
            postgresql_where=variant_id.is_not(None),
        ),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "parent_definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        CheckConstraint("visibility IN ('private','category','audience')"),
        CheckConstraint("revision > 0 AND parent_definition_id IS DISTINCT FROM id"),
    )


class DefinitionSpecRow(Row, Base):
    __tablename__ = "definition_specs"
    product_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    item_id: Mapped[UUID] = mapped_column(server_default=FetchedValue())
    item_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    removed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    prepared_candidate_id: Mapped[UUID | None]
    key: Mapped[str] = mapped_column(Text)
    parameter: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(16))
    availability: Mapped[str] = mapped_column(String(24))
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    lower: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    upper: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    test_conditions: Mapped[list] = mapped_column(JSONB)
    method: Mapped[str | None] = mapped_column(Text)
    acceptance_criterion: Mapped[str | None] = mapped_column(Text)
    nature: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24))
    owner_id: Mapped[UUID | None]
    reason: Mapped[str] = mapped_column(Text)
    parameter_id: Mapped[UUID | None]
    parameter_version: Mapped[int | None]
    item_status: Mapped[str] = mapped_column(Text, default="unknown", server_default="unknown")
    condition_note: Mapped[str | None] = mapped_column(Text)
    modality: Mapped[str | None] = mapped_column(Text)
    exceptions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    applicable_variants: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    source_refs: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    origin: Mapped[str] = mapped_column(Text, default="human", server_default="human")
    writer_id: Mapped[UUID | None]
    run_id: Mapped[UUID | None]
    confirmed_by: Mapped[UUID | None]
    receipt_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "parameter_id", "parameter_version"],
            [
                "parameter_versions.tenant_id",
                "parameter_versions.category_id",
                "parameter_versions.parameter_id",
                "parameter_versions.version",
            ],
            name="definition_spec_parameter_version_fk",
        ),
        CheckConstraint(
            "(parameter_id IS NULL AND parameter_version IS NULL) OR "
            "(parameter_id IS NOT NULL AND parameter_version IS NOT NULL AND parameter_version>0)",
            name="definition_spec_parameter_pair",
        ),
        CheckConstraint(
            "item_status IN ('ai_draft','confirmed','expert_pending','unknown')",
            name="m3_spec_status",
        ),
        CheckConstraint(
            "origin IN ('human','ai_draft','imported') "
            "AND (origin<>'ai_draft' OR run_id IS NOT NULL)",
            name="m3_spec_origin",
        ),
        UniqueConstraint("tenant_id", "product_id", "definition_id", "id"),
        UniqueConstraint(
            "tenant_id",
            "definition_id",
            "item_id",
            "item_version",
            name="m3_spec_item_version_unique",
        ),
        UniqueConstraint(
            "tenant_id",
            "category_id",
            "product_id",
            "definition_id",
            "item_id",
            "id",
            "item_version",
            "key",
            "removed",
            name="m3_spec_current_identity_unique",
        ),
        CheckConstraint("item_version > 0", name="m3_spec_item_version_positive"),
        ForeignKeyConstraint(
            ["tenant_id", "prepared_candidate_id"],
            ["proposal_prepared_candidates.tenant_id", "proposal_prepared_candidates.id"],
            name="m3_spec_candidate_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["principals.tenant_id", "principals.id"]),
        CheckConstraint(
            "value_type IN ('number','range','text','boolean','enum')", name="m3_spec_value_type"
        ),
        CheckConstraint("availability IN ('known','unknown','conflicted','not_applicable')"),
        CheckConstraint("nature IN ('observed','extracted','computed','inferred','decided')"),
        CheckConstraint("state IN ('proposed','needs_confirmation')"),
        CheckConstraint("tolerance IS NULL OR tolerance >= 0"),
        CheckConstraint("lower IS NULL OR upper IS NULL OR lower <= upper"),
        CheckConstraint(
            "availability = 'known' OR (value IS NULL AND lower IS NULL "
            "AND upper IS NULL AND text IS NULL AND tolerance IS NULL)"
        ),
        CheckConstraint(
            "availability<>'known' OR "
            "(value_type='number' AND value IS NOT NULL "
            "AND lower IS NULL AND upper IS NULL AND text IS NULL) OR "
            "(value_type IN ('number','range') AND (lower IS NOT NULL OR upper IS NOT NULL) "
            "AND value IS NULL AND text IS NULL) OR "
            "(value_type IN ('text','boolean','enum') AND text IS NOT NULL AND value IS NULL "
            "AND lower IS NULL AND upper IS NULL)",
            name="m3_spec_known_shape",
        ),
    )


class DefinitionSpecCurrent(Row, Base):
    __tablename__ = "definition_spec_current"
    product_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    item_id: Mapped[UUID]
    current_row_id: Mapped[UUID]
    current_version: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(Text)
    removed: Mapped[bool] = mapped_column(Boolean)
    __table_args__ = (
        UniqueConstraint("tenant_id", "item_id", name="m3_spec_current_item_unique"),
        UniqueConstraint("tenant_id", "definition_id", "key", name="m3_spec_current_key_unique"),
        CheckConstraint("id=item_id AND current_version>0", name="m3_spec_current_shape"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "category_id",
                "product_id",
                "definition_id",
                "item_id",
                "current_row_id",
                "current_version",
                "key",
                "removed",
            ],
            [
                "definition_specs.tenant_id",
                "definition_specs.category_id",
                "definition_specs.product_id",
                "definition_specs.definition_id",
                "definition_specs.item_id",
                "definition_specs.id",
                "definition_specs.item_version",
                "definition_specs.key",
                "definition_specs.removed",
            ],
            name="m3_spec_current_row_fk",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
            name="m3_spec_current_definition_fk",
        ),
    )


class DefinitionSource(Row, Base):
    __tablename__ = "definition_sources"
    product_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    artifact_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(Integer)
    line: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    spec_keys: Mapped[list] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "product_id", "definition_id"],
            [
                "definition_revisions.tenant_id",
                "definition_revisions.product_id",
                "definition_revisions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "category_id", "artifact_id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.category_id",
                "artifact_versions.id",
            ],
            name="fk_definition_sources_category_artifact_id",
        ),
        CheckConstraint("source_revision > 0 AND line > 0"),
    )
