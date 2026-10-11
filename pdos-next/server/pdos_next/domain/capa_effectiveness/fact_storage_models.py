"""Five unregistered declarations, not installed DDL/permissions or live facts.

Root must install append-only/RLS/lifecycle, pointer CAS and reciprocal atom
guards. shared proof clocks are captured by the actual consumption host; no
future Receipt/transaction proof UUIDs are allocated in these declarations.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.models import Base, Row

from .fact_storage_codec import BODY_FIELDS, SCHEMA_VERSION

SCOPE = ("tenant_id", "product_id", "project_id", "issue_id", "capa_id")
BINDING = SCOPE + (
    "origin_issue_version_id",
    "origin_issue_revision",
    "owner_id",
    "visibility",
    "nature",
    "purpose",
    "anchor_sha256",
    "requirement_sha256",
)
# Readers retain the complete semantic binding. Only physical B-tree/FK keys
# exclude long purpose; the row/body/full anchor and actual guards preserve it.
INDEX_BINDING = tuple(column for column in BINDING if column != "purpose")
BODY = "(fact_body->'body')"


def _fk(columns, table, targets=None):
    return ForeignKeyConstraint(
        list(columns),
        [f"{table}.{c}" for c in (targets or columns)],
        deferrable=True,
        initially="DEFERRED",
    )


class _Bound:
    product_id: Mapped[UUID]
    project_id: Mapped[UUID]
    issue_id: Mapped[UUID]
    capa_id: Mapped[UUID]
    origin_issue_version_id: Mapped[UUID]
    origin_issue_revision: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[UUID]
    visibility: Mapped[str] = mapped_column(String(16))
    nature: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(Text)
    anchor_snapshot: Mapped[dict] = mapped_column(JSONB)
    anchor_sha256: Mapped[str] = mapped_column(String(64))
    requirement_sha256: Mapped[str] = mapped_column(String(64))


class _Fact(_Bound):
    revision: Mapped[int] = mapped_column(Integer)
    writer_id: Mapped[UUID]
    actor_id: Mapped[UUID]
    requester_id: Mapped[UUID]
    command_id: Mapped[UUID]
    operation: Mapped[str] = mapped_column(String(80))
    tier: Mapped[str] = mapped_column(String(16))
    fact_kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    fact_body: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    # Actual common semantic intent, not the domain's differently shaped _intent.
    intent_digest: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list] = mapped_column(JSONB)
    required_source_read_set: Mapped[list] = mapped_column(JSONB)
    source_basis: Mapped[list] = mapped_column(JSONB)
    read_set_sha256: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(JSONB)
    authority_snapshot: Mapped[dict] = mapped_column(JSONB)
    policy_snapshot: Mapped[dict] = mapped_column(JSONB)
    shared_proof_id: Mapped[UUID | None]
    shared_proof_revision: Mapped[int | None] = mapped_column(Integer)
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proof_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_sha256: Mapped[str | None] = mapped_column(String(64))
    material_sha256: Mapped[str | None] = mapped_column(String(64))

    @property
    def action_result(self):
        # Full FactRef SHA includes the saved group: never make Receipt cyclic.
        return {"fact_kind": self.fact_kind, "payload_sha256": self.payload_sha256}


class _Series:
    series_id: Mapped[UUID]
    previous_fact_id: Mapped[UUID | None]
    previous_revision: Mapped[int | None] = mapped_column(Integer)


def _bound_constraints():
    return (
        _fk(
            ("tenant_id", "product_id", "project_id"),
            "projects",
            ("tenant_id", "product_id", "id"),
        ),
        _fk(("tenant_id", "owner_id"), "principals", ("tenant_id", "id")),
        _fk(
            (
                "tenant_id",
                "product_id",
                "project_id",
                "issue_id",
                "origin_issue_version_id",
                "origin_issue_revision",
            ),
            QualityIssueVersion.__tablename__,
            ("tenant_id", "product_id", "project_id", "issue_id", "id", "revision"),
        ),
        CheckConstraint(
            "origin_issue_revision>0 AND visibility IN ('private','category','audience') "
            "AND nature IN ('real','synthetic') AND length(purpose) BETWEEN 1 AND 2000 "
            "AND purpose=btrim(purpose)"
        ),
        CheckConstraint(
            "anchor_sha256 ~ '^[0-9a-f]{64}$' AND requirement_sha256 ~ '^[0-9a-f]{64}$'"
        ),
        CheckConstraint(
            "COALESCE(jsonb_typeof(anchor_snapshot)='object' "
            "AND anchor_snapshot->>'anchor_sha256'=anchor_sha256 "
            "AND anchor_snapshot->'origin'->'ref'->>'id'=origin_issue_version_id::text "
            "AND (anchor_snapshot->'origin'->'ref'->>'revision')::integer=origin_issue_revision "
            "AND anchor_snapshot->'origin'->>'issue_id'=issue_id::text "
            "AND anchor_snapshot->'origin'->'issue'->'capa'->>'id'=capa_id::text "
            "AND anchor_snapshot->'origin'->'scope'->>'tenant_id'=tenant_id::text "
            "AND anchor_snapshot->'origin'->'scope'->>'product_id'=product_id::text "
            "AND anchor_snapshot->'origin'->'scope'->>'project_id'=project_id::text "
            "AND anchor_snapshot->'origin'->>'owner_id'=owner_id::text "
            "AND anchor_snapshot->'origin'->>'visibility'=visibility "
            "AND anchor_snapshot->'origin'->>'nature'=nature "
            "AND anchor_snapshot->'origin'->>'purpose'=purpose,false)"
        ),
    )


def _fact_constraints(kind, operation, tier, status):
    fields = ",".join(f"'{name}'" for name in BODY_FIELDS[kind])
    proof = (
        "shared_proof_id IS NULL AND shared_proof_revision IS NULL AND proof_expires_at IS NULL "
        "AND proof_consumed_at IS NULL AND token_sha256 IS NULL AND material_sha256 IS NULL"
        if tier == "host_import"
        else "shared_proof_id IS NOT NULL AND shared_proof_revision IS NOT NULL "
        "AND shared_proof_revision>0 "
        "AND proof_consumed_at IS NOT NULL AND proof_consumed_at<=created_at "
        + ("AND (proof_expires_at IS NULL OR created_at<proof_expires_at) "
           if tier == "T2" else "AND proof_expires_at IS NOT NULL AND created_at<proof_expires_at ")
        + "AND token_sha256 IS NOT NULL "
        "AND material_sha256 IS NOT NULL AND token_sha256 ~ '^[0-9a-f]{64}$' "
        "AND material_sha256 ~ '^[0-9a-f]{64}$'"
    )
    return (
        *_bound_constraints(),
        UniqueConstraint("tenant_id", "product_id", "id"),
        UniqueConstraint(*SCOPE, "id", "revision"),
        UniqueConstraint("tenant_id", "product_id", "writer_id", "intent_digest"),
        UniqueConstraint("tenant_id", "shared_proof_id"),
        _fk(("tenant_id", "writer_id"), "principals", ("tenant_id", "id")),
        _fk(("tenant_id", "actor_id"), "principals", ("tenant_id", "id")),
        _fk(("tenant_id", "requester_id"), "principals", ("tenant_id", "id")),
        _fk(("tenant_id", "shared_proof_id"), "confirmations", ("tenant_id", "id")),
        CheckConstraint(
            f"revision>0 AND operation='{operation}' AND tier='{tier}' "
            f"AND fact_kind='{kind}' AND status='{status}' "
            "AND actor_id=requester_id AND writer_id=actor_id"
        ),
        CheckConstraint(proof),
        CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$' AND intent_digest ~ '^[0-9a-f]{64}$' "
            "AND read_set_sha256 ~ '^[0-9a-f]{64}$'"
        ),
        CheckConstraint(
            f"COALESCE(jsonb_typeof(fact_body)='object' "
            f"AND fact_body->>'schema_version'='{SCHEMA_VERSION}' "
            "AND (fact_body - ARRAY['schema_version','body'])='{}'::jsonb "
            f"AND jsonb_typeof({BODY})='object' AND {BODY} ?& ARRAY[{fields}] "
            f"AND ({BODY} - ARRAY[{fields}])='{{}}'::jsonb "
            f"AND {BODY}->>'kind'=fact_kind AND {BODY}->'ref'->>'id'=id::text "
            f"AND ({BODY}->'ref'->>'revision')::integer=revision "
            f"AND (({BODY}->'ref') - ARRAY['id','revision'])='{{}}'::jsonb "
            f"AND {BODY}->'scope'->>'tenant_id'=tenant_id::text "
            f"AND {BODY}->'scope'->>'product_id'=product_id::text "
            f"AND {BODY}->'scope'->>'project_id'=project_id::text "
            f"AND {BODY}->>'issue_id'=issue_id::text AND {BODY}->>'capa_id'=capa_id::text "
            f"AND {BODY}->>'owner_id'=owner_id::text AND {BODY}->>'visibility'=visibility "
            f"AND {BODY}->>'nature'=nature AND {BODY}->>'purpose'=purpose "
            f"AND {BODY}->>'anchor_sha256'=anchor_sha256 "
            f"AND {BODY}->>'requirement_sha256'=requirement_sha256 "
            f"AND ({BODY}->>'created_at')::timestamptz=created_at,false)"
        ),
        CheckConstraint(
            "COALESCE(jsonb_typeof(required_source_read_set)='array' "
            "AND jsonb_array_length(required_source_read_set)>0 "
            "AND jsonb_typeof(source_basis)='array' "
            "AND jsonb_array_length(source_basis)>0 "
            "AND jsonb_typeof(sources)='array' AND jsonb_array_length(sources)>0 "
            f"AND required_source_read_set={BODY}->'required_source_read_set' "
            f"AND source_basis={BODY}->'source_basis' AND sources={BODY}->'sources',false)"
        ),
        CheckConstraint(
            "COALESCE(jsonb_typeof(input_snapshot)='object' "
            "AND jsonb_typeof(authority_snapshot)='object' "
            "AND jsonb_typeof(policy_snapshot)='object',false) "
            "AND NOT (input_snapshot ? 'confirmation_token') "
            "AND NOT (input_snapshot ? 'approval_token')"
        ),
    )


def _series_constraints(table):
    return (
        UniqueConstraint(*SCOPE, "series_id", "revision"),
        UniqueConstraint(*INDEX_BINDING, "series_id", "id", "revision"),
        _fk(
            INDEX_BINDING + ("series_id", "previous_fact_id", "previous_revision"),
            table,
            INDEX_BINDING + ("series_id", "id", "revision"),
        ),
        CheckConstraint(
            "(revision=1 AND series_id=id AND previous_fact_id IS NULL "
            "AND previous_revision IS NULL) OR "
            "(revision>1 AND previous_fact_id IS NOT NULL AND previous_revision IS NOT NULL "
            "AND previous_fact_id<>id AND revision=previous_revision+1)"
        ),
        CheckConstraint(
            f"COALESCE((previous_fact_id IS NULL AND {BODY}->'previous'='null'::jsonb) OR "
            f"(previous_fact_id IS NOT NULL AND {BODY}->'previous'->>'id'=previous_fact_id::text "
            f"AND ({BODY}->'previous'->>'revision')::integer=previous_revision "
            f"AND {BODY}->'previous'->>'sha256' ~ '^[0-9a-f]{{64}}$'),false)"
        ),
    )


class RuleFact(_Series, _Fact, Row, Base):
    __tablename__ = "capa_verification_rule_facts"
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    issuer_epoch: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_fact_constraints(
            "rule", "quality.capa.verification.rule.import", "host_import", "published"
        ),
        *_series_constraints(__tablename__),
        UniqueConstraint(
            *INDEX_BINDING,
            "series_id",
            "issuer_key",
            "issuer_version",
            "external_id",
            "id",
            "revision",
        ),
        CheckConstraint(
            "issuer_epoch>0 AND valid_until>valid_from AND length(external_id)>0 "
            "AND length(issuer_key) BETWEEN 1 AND 100 "
            "AND length(issuer_version) BETWEEN 1 AND 100"
        ),
        CheckConstraint(
            f"COALESCE({BODY}->'issuer'->>'key'=issuer_key "
            f"AND {BODY}->'issuer'->>'version'=issuer_version "
            f"AND ({BODY}->'issuer'->>'epoch')::integer=issuer_epoch "
            f"AND {BODY}->'issuer'->>'nature'=nature "
            f"AND ({BODY}->>'valid_from')::timestamptz=valid_from "
            f"AND ({BODY}->>'valid_until')::timestamptz=valid_until,false)"
        ),
    )


class _Current(_Bound):
    series_id: Mapped[UUID]
    fact_id: Mapped[UUID]
    fact_revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer)


def _current_constraints(table):
    return (
        *_bound_constraints(),
        UniqueConstraint(*SCOPE, "series_id"),
        _fk(
            INDEX_BINDING + ("series_id", "fact_id", "fact_revision"),
            table,
            INDEX_BINDING + ("series_id", "id", "revision"),
        ),
        CheckConstraint("fact_revision>0 AND epoch>0"),
    )


class RuleCurrent(_Current, Row, Base):
    __tablename__ = "capa_current_verification_rules"
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    __table_args__ = (
        *_current_constraints(RuleFact.__tablename__),
        _fk(
            INDEX_BINDING
            + (
                "series_id",
                "issuer_key",
                "issuer_version",
                "external_id",
                "fact_id",
                "fact_revision",
            ),
            RuleFact.__tablename__,
            INDEX_BINDING
            + ("series_id", "issuer_key", "issuer_version", "external_id", "id", "revision"),
        ),
        UniqueConstraint(*SCOPE, "anchor_sha256", "issuer_key", "external_id"),
        CheckConstraint(
            "length(issuer_key) BETWEEN 1 AND 100 "
            "AND length(issuer_version) BETWEEN 1 AND 100 AND length(external_id)>0"
        ),
    )


class ObservationFact(_Series, _Fact, Row, Base):
    __tablename__ = "capa_observation_facts"
    rule_fact_id: Mapped[UUID]
    rule_revision: Mapped[int] = mapped_column(Integer)
    rule_sha256: Mapped[str] = mapped_column(String(64))
    issuer_key: Mapped[str] = mapped_column(String(100))
    issuer_version: Mapped[str] = mapped_column(String(100))
    issuer_epoch: Mapped[int] = mapped_column(Integer)
    executor_id: Mapped[UUID]
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_fact_constraints("observation", "quality.capa.observation.record", "T1", "recorded"),
        *_series_constraints(__tablename__),
        UniqueConstraint(
            *INDEX_BINDING,
            "series_id",
            "rule_fact_id",
            "rule_revision",
            "rule_sha256",
            "executor_id",
            "id",
            "revision",
        ),
        _fk(
            INDEX_BINDING
            + (
                "series_id",
                "rule_fact_id",
                "rule_revision",
                "rule_sha256",
                "executor_id",
                "previous_fact_id",
                "previous_revision",
            ),
            __tablename__,
            INDEX_BINDING
            + (
                "series_id",
                "rule_fact_id",
                "rule_revision",
                "rule_sha256",
                "executor_id",
                "id",
                "revision",
            ),
        ),
        _fk(
            SCOPE + ("rule_fact_id", "rule_revision"),
            RuleFact.__tablename__,
            SCOPE + ("id", "revision"),
        ),
        _fk(("tenant_id", "executor_id"), "principals", ("tenant_id", "id")),
        CheckConstraint(
            "rule_revision>0 AND rule_sha256 ~ '^[0-9a-f]{64}$' AND issuer_epoch>0 "
            "AND executor_id=writer_id AND observed_until>observed_from "
            "AND length(issuer_key) BETWEEN 1 AND 100 "
            "AND length(issuer_version) BETWEEN 1 AND 100"
        ),
        CheckConstraint(
            f"COALESCE({BODY}->'rule'->>'id'=rule_fact_id::text "
            f"AND ({BODY}->'rule'->>'revision')::integer=rule_revision "
            f"AND {BODY}->'rule'->>'sha256'=rule_sha256 "
            f"AND {BODY}->'issuer'->>'key'=issuer_key "
            f"AND {BODY}->'issuer'->>'version'=issuer_version "
            f"AND ({BODY}->'issuer'->>'epoch')::integer=issuer_epoch "
            f"AND {BODY}->'issuer'->>'nature'=nature AND {BODY}->>'executor_id'=executor_id::text "
            f"AND ({BODY}->>'observed_from')::timestamptz=observed_from "
            f"AND ({BODY}->>'observed_until')::timestamptz=observed_until,false)"
        ),
    )


class ObservationCurrent(_Current, Row, Base):
    __tablename__ = "capa_current_observations"
    __table_args__ = _current_constraints(ObservationFact.__tablename__)


class NamedReviewRecord(_Fact, Row, Base):
    __tablename__ = "capa_named_verification_reviews"
    candidate_id: Mapped[UUID]
    candidate_revision: Mapped[int] = mapped_column(Integer)
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    rule_fact_id: Mapped[UUID]
    rule_revision: Mapped[int] = mapped_column(Integer)
    rule_sha256: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[UUID]
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        *_fact_constraints("review", "quality.capa.verification.review", "T2", "reviewed"),
        _fk(SCOPE + ("candidate_id",), CapaVerificationEvidence.__tablename__, SCOPE + ("id",)),
        _fk(
            SCOPE + ("rule_fact_id", "rule_revision"),
            RuleFact.__tablename__,
            SCOPE + ("id", "revision"),
        ),
        _fk(("tenant_id", "reviewer_id"), "principals", ("tenant_id", "id")),
        CheckConstraint(
            "revision=1 AND candidate_revision=1 AND rule_revision>0 AND reviewer_id=writer_id "
            "AND (valid_until IS NULL OR valid_until>created_at) "
            "AND candidate_sha256 ~ '^[0-9a-f]{64}$' "
            "AND rule_sha256 ~ '^[0-9a-f]{64}$'"
        ),
        CheckConstraint(
            f"COALESCE({BODY}->'previous'='null'::jsonb "
            f"AND {BODY}->'candidate'->>'id'=candidate_id::text "
            f"AND ({BODY}->'candidate'->>'revision')::integer=candidate_revision "
            f"AND {BODY}->'candidate'->>'sha256'=candidate_sha256 "
            f"AND {BODY}->>'candidate_sha256'=candidate_sha256 "
            f"AND {BODY}->'rule'->>'id'=rule_fact_id::text "
            f"AND ({BODY}->'rule'->>'revision')::integer=rule_revision "
            f"AND {BODY}->'rule'->>'sha256'=rule_sha256 "
            f"AND {BODY}->>'reviewer_id'=reviewer_id::text "
            f"AND {BODY}->'authority_snapshot'=authority_snapshot "
            f"AND {BODY}->'policy_snapshot'=policy_snapshot "
            f"AND (({BODY}->>'valid_until')::timestamptz IS NOT DISTINCT FROM valid_until),false)"
        ),
    )


STAGED_MODELS = (RuleFact, RuleCurrent, ObservationFact, ObservationCurrent, NamedReviewRecord)
