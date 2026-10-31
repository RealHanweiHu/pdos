"""Human-confirmed category creation from human, static seed, or sealed AI material."""

import json
import secrets
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pdos_next.clock import now, proof_deadline_current
from pdos_next.database import require_context
from pdos_next.models import Audit, Category, Grant, Outbox, Principal, Receipt, RequestKey
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest, receipt_view

from .access import fail
from .category_creation_models import CategoryCreationConfirmation
from .category_models import KnowledgeCurrent, KnowledgeEntry, ParameterCurrent, ParameterVersion
from .category_schemas import CONTENT_TYPES, KnowledgeKind, ParameterPublish
from .category_seed import convert_seed
from .schemas import Reference

SEED_KEYS = ("auto-tire-inflator", "bicycle-pump")
SEED_DIRECTORY = Path(__file__).resolve().parents[5] / "docs/design/category-seeds"


class InitialKnowledge(StrictModel):
    kind: KnowledgeKind
    content: dict
    regions: list[str] = Field(default_factory=list)
    source_refs: list[Reference] = Field(default_factory=list)

    @model_validator(mode="after")
    def typed_content(self):
        self.content = CONTENT_TYPES[self.kind].model_validate(self.content).model_dump(mode="json")
        if self.kind == "competitor" and self.content.get("segment_refs"):
            raise ValueError("Initial category material cannot reference existing fixed segments")
        return self


class InitialParameter(StrictModel):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value_type: Literal["number", "range", "text", "boolean", "enum"]
    enum_values: list[str] | None = None
    unit: str | None = None
    direction: Literal["higher", "lower", "target", "neutral"]
    standard_condition: str | None = None
    method: str | None = None
    acceptance_criterion: str | None = None
    change_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_dictionary(self):
        ParameterPublish(expected_current_version=0, **self.model_dump())
        return self


class ResearchSnapshotRef(StrictModel):
    call_id: UUID
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class InitialGroups(StrictModel):
    knowledge: list[InitialKnowledge] = Field(default_factory=list)
    parameters: list[InitialParameter] = Field(default_factory=list)
    snapshot_refs: list[ResearchSnapshotRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_parameters(self):
        keys = [parameter.key for parameter in self.parameters]
        if len(keys) != len(set(keys)):
            raise ValueError("Initial parameter keys must be unique")
        return self


class CategoryHumanEdits(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def meaningful(self):
        if not self.name.strip() or not self.purpose.strip():
            raise ValueError("名称和主要场景不能为空")
        return self


class CategoryCreate(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1)
    groups: InitialGroups = Field(default_factory=InitialGroups)
    seed_key: Literal["auto-tire-inflator", "bicycle-pump"] | None = None
    deidentified_confirmed: bool
    prepared_by_run_id: UUID | None = None
    candidate_digest: str | None = None
    human_edits: CategoryHumanEdits | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirmation_token: str | None = None

    @model_validator(mode="after")
    def candidate_pair(self):
        if self.human_edits and not self.prepared_by_run_id:
            raise ValueError("人工修订须绑定原小Pai候选")
        if bool(self.prepared_by_run_id) != bool(self.candidate_digest):
            raise ValueError("A candidate requires both its run and server digest")
        return self


def load_seed(key):
    """Return optional canonical groups and the unmodified source material."""
    if key not in SEED_KEYS:
        fail("NOT_FOUND", "seed_not_found", "初始资料不存在。", 404)
    document = json.loads((SEED_DIRECTORY / f"{key}.json").read_text())
    sources = (SEED_DIRECTORY / "sources.md").read_text()
    seed = convert_seed(document, sources)
    category = next(item for item in seed.categories if item.key == key)
    raw, knowledge = category.raw, []
    boundary = raw["boundary"]
    knowledge.append(
        InitialKnowledge(
            kind="boundary",
            content={
                **boundary,
                "includes": [
                    item["item"] if isinstance(item, dict) else item
                    for item in boundary["includes"]
                ],
                "excludes": [
                    item["item"] if isinstance(item, dict) else item
                    for item in boundary["excludes"]
                ],
                "criteria": [
                    item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                    for item in boundary.get("criteria", [])
                ],
                "material": {"boundary": boundary},
            },
        )
    )
    scenarios = raw["scenarios"]
    for group in scenarios["user_groups"]:
        knowledge.append(
            InitialKnowledge(
                kind="segment",
                content={
                    "segment": group["group"],
                    "jtbd": scenarios["jtbd"],
                    "buying_criteria": scenarios["buying_criteria"],
                    "material": {"user_group": group, "scenarios": scenarios},
                },
            )
        )
    for regulation in raw["regulations"]["items"]:
        knowledge.append(
            InitialKnowledge(
                kind="regulation",
                regions=[regulation["region"]],
                content={
                    **{
                        field: regulation.get(field)
                        for field in (
                            "instrument",
                            "region",
                            "applicability",
                            "source_state",
                            "applicability_state",
                            "compliance_state",
                            "requirement_kind",
                            "classification_state",
                        )
                    },
                    "material": regulation,
                },
            )
        )
    parameters = [
        InitialParameter(
            key=item.key,
            name=item.name,
            value_type=("text" if item.value_type == "enum_set" else item.value_type),
            enum_values=item.enum_values,
            unit=item.unit,
            direction=item.direction,
            standard_condition=item.standard_condition,
            method=item.method,
            acceptance_criterion=item.acceptance_criterion,
            change_note=raw["draft_label"],
        )
        for item in category.parameters
    ]
    groups = InitialGroups(knowledge=knowledge, parameters=parameters)
    return {
        "seed_key": key,
        "key": key,
        "name": category.name,
        "purpose": boundary["definition"],
        "groups": groups.model_dump(mode="json"),
        "material": {"document": seed.raw_document, "sources_markdown": seed.sources_markdown},
        "material_digest": digest([seed.raw_document, seed.sources_markdown]),
        "origin": "imported",
        "parameter_projection_notes": [
            {
                "key": item.key,
                "source_value_type": item.value_type,
                "value_type": "text",
                "reason": "原稿未给结构化枚举集合；保留原文，待人工发布枚举版本。",
            }
            for item in category.parameters
            if item.value_type == "enum_set"
        ],
    }


def _semantic(data):
    result = data.model_dump(mode="json", exclude={"confirmation_token", "idempotency_key"})
    if data.human_edits is None:
        result.pop("human_edits", None)
    return result


def _human(s, ctx):
    require_context(s, ctx)
    actor = s.scalar(
        select(Principal)
        .where(
            Principal.tenant_id == ctx.tenant_id,
            Principal.id == ctx.actor_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        not actor
        or actor.tenant_id != ctx.tenant_id
        or not actor.active
        or actor.kind != "human"
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or ctx.agent_run_id
        or ctx.agent_call_id
    ):
        fail("FORBIDDEN_SCOPE", "human_only", "品类创建须由当前租户的本人确认。", 403)
    return actor


def _validate(s, ctx, data):
    if not data.deidentified_confirmed:
        fail("CONFIRMATION_REQUIRED", "deidentification_not_confirmed", "请确认已去除客户身份。")
    if data.prepared_by_run_id:
        from pdos_next.agent_kernel.category_candidate import validate

        candidate = validate(s, ctx, data)
        for item in data.groups.knowledge:
            _initial_parameters(item)
        return {"candidate": candidate, "material_digest": data.candidate_digest}
    if data.groups.snapshot_refs:
        fail(
            "SOURCE_UNAVAILABLE",
            "category_candidate_required",
            "研究快照须由实际模型候选和原运行读取证明办理。",
        )
    material = None
    if data.seed_key:
        seed = load_seed(data.seed_key)
        # Each initial group is independently selected or omitted. Altered content
        # must use the ordinary human path, never impersonate the imported source.
        if data.key != seed["key"]:
            fail("VALIDATION_FAILED", "seed_key_mismatch", "初始资料须对应此品类键。", 422)
        for group in ("knowledge", "parameters"):
            selected = getattr(data.groups, group)
            actual = [item.model_dump(mode="json") for item in selected]
            if actual and actual != seed["groups"][group]:
                fail(
                    "VALIDATION_FAILED",
                    "seed_material_changed",
                    "初始资料组与服务器原稿不符。",
                    422,
                )
        material = seed
    # A new category has no existing shared artifacts, parameters or snapshots.
    # Human statements can already be resolved to actual tenant identities.
    from .category_service import _references, check_shared_sources

    for item in data.groups.knowledge:
        refs = _references(item)
        if any(ref.type != "human" for ref in refs):
            fail(
                "VALIDATION_FAILED",
                "private_source_in_shared",
                "新品类初始知识不能引用其他范围的原件或快照。",
                422,
            )
        check_shared_sources(s, ctx, refs)
        _initial_parameters(item)
    return material


def _initial_parameters(item):
    if item.kind == "competitor" and (item.content["metrics"] or item.content["features"]):
        fail(
            "VALIDATION_FAILED",
            "parameter_not_in_category",
            "初始竞品指标须待本品类参数建立后引用。",
            422,
        )


def _candidate(material):
    return material.get("candidate") if material else None


def _candidate_event(material):
    candidate = _candidate(material)
    return str(candidate.event.id) if candidate else None


def _origin(material):
    return "ai_draft" if _candidate(material) else "imported" if material else "human"


def _snapshot_manifest(candidate):
    snapshots = {}
    for item in candidate.snapshots if candidate else ():
        snapshots.setdefault(
            item.snapshot.id,
            {
                "snapshot_id": str(item.snapshot.id),
                "content_hash": item.snapshot.content_hash,
                "call_id": str(item.read_call_id),
            },
        )
    return list(snapshots.values())


def preview(s, ctx, data):
    actor = _human(s, ctx)
    material = _validate(s, ctx, data)
    if s.scalar(
        select(Category.id).where(
            Category.tenant_id == ctx.tenant_id,
            Category.key == data.key,
        )
    ):
        fail("VALIDATION_FAILED", "key_taken", "品类键已存在。", 422)
    payload = _semantic(data)
    token, expires = secrets.token_urlsafe(32), now() + timedelta(minutes=10)
    proof = CategoryCreationConfirmation(
        tenant_id=ctx.tenant_id,
        actor_id=ctx.actor_id,
        reserved_category_id=uuid4(),
        token_hash=digest(token),
        payload_digest=digest(payload),
        expires_at=expires,
        snapshot={
            "payload": payload,
            "actor_access_epoch": actor.access_epoch,
            "material_digest": material["material_digest"] if material else None,
            "category_candidate_event_id": _candidate_event(material),
        },
    )
    s.add(proof)
    s.flush()
    candidate = _candidate(material)
    return {
        "operation": "category.create",
        "tier": "T1",
        "payload": {**payload, **(data.human_edits.model_dump() if data.human_edits else {})},
        "confirmation_token": token,
        "expires_at": expires.isoformat(),
        "origin": _origin(material),
        "writer_id": str(candidate.run.writer_id) if candidate else str(ctx.actor_id),
        "prepared_by_run_id": str(candidate.run.id) if candidate else None,
        "category_candidate_event_id": _candidate_event(material),
        "candidate": {
            "digest": data.candidate_digest,
            "input": candidate.event.body["input"],
            "checks": {
                "actual_model": True,
                "actual_source_reads": True,
                "complete_groups_only": True,
                "deidentified_confirmed": True,
            },
            "sources": [
                {
                    "snapshot_id": str(item.snapshot.id),
                    "url": item.snapshot.url,
                    "title": item.snapshot.title,
                    "content_hash": item.snapshot.content_hash,
                    "read_call_id": str(item.read_call_id),
                }
                for item in candidate.snapshots
            ],
        }
        if candidate
        else None,
        "import_material": material.get("material") if material else None,
        "parameter_projection_notes": material.get("parameter_projection_notes", [])
        if material
        else [],
        "groups": {
            key: {
                "selected_count": len(getattr(data.groups, key)),
                "available_count": len(candidate.event.body["input"]["groups"][key])
                if candidate
                else len(getattr(data.groups, key)),
                "depends_on": "snapshot_refs"
                if candidate and key == "knowledge" and data.groups.snapshot_refs
                else "category",
            }
            for key in ("knowledge", "parameters", "snapshot_refs")
        },
        "effect": "创建品类并授予本人管理权限；按所选组保存初始知识与规格字典。",
    }


def _read_prior(s, ctx, receipt):
    from pdos_next.category_scope import category_scope

    if (
        not receipt
        or receipt.tenant_id != ctx.tenant_id
        or receipt.actor_id != ctx.actor_id
        or receipt.operation != "category.create"
    ):
        fail("FORBIDDEN_SCOPE", "receipt_not_readable", "原回执不可读。", 403)
    category_scope(s, replace(ctx, category_id=receipt.category_id), lock=True)
    return receipt_view(receipt)


def create(s, ctx, data):
    actor = _human(s, ctx)
    semantic = digest(_semantic(data))
    prior = s.scalar(
        select(RequestKey).where(
            RequestKey.tenant_id == ctx.tenant_id,
            RequestKey.actor_id == ctx.actor_id,
            RequestKey.key == data.idempotency_key,
        )
    )
    if prior:
        if prior.digest != semantic:
            fail("DUPLICATE_INTENT_CONFLICT", "request_key_conflict", "请求编号已绑定其他内容。")
        return _read_prior(s, ctx, s.get(Receipt, prior.receipt_id))
    intent = digest(["category.create", ctx.tenant_id, ctx.actor_id, semantic])
    prior_receipt = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.actor_id == ctx.actor_id,
            Receipt.operation == "category.create",
            Receipt.intent_digest == intent,
        )
    )
    if prior_receipt:
        result = _read_prior(s, ctx, prior_receipt)
        s.add(
            RequestKey(
                tenant_id=ctx.tenant_id,
                category_id=prior_receipt.category_id,
                actor_id=ctx.actor_id,
                key=data.idempotency_key,
                digest=semantic,
                receipt_id=prior_receipt.id,
            )
        )
        s.flush()
        return result
    material = _validate(s, ctx, data)
    proof = s.scalar(
        select(CategoryCreationConfirmation)
        .where(
            CategoryCreationConfirmation.tenant_id == ctx.tenant_id,
            CategoryCreationConfirmation.actor_id == ctx.actor_id,
            CategoryCreationConfirmation.token_hash == digest(data.confirmation_token or ""),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if proof and proof.consumed and proof.payload_digest == semantic:
        from pdos_next.category_scope import category_scope

        # A completed preview remains visible to its creator after revocation;
        # its old request key and receipt are correctly hidden by category RLS.
        category_scope(s, replace(ctx, category_id=proof.reserved_category_id), lock=True)
    if (
        not proof
        or proof.consumed
        or not proof_deadline_current("T1", proof.expires_at, now())
        or proof.payload_digest != semantic
        or proof.snapshot.get("actor_access_epoch") != actor.access_epoch
        or proof.snapshot.get("material_digest")
        != (material["material_digest"] if material else None)
        or proof.snapshot.get("category_candidate_event_id") != _candidate_event(material)
    ):
        fail("CONFIRMATION_REQUIRED", "preview_required", "请重新查看并确认服务器预览。")
    if s.scalar(
        select(Category.id).where(
            Category.tenant_id == ctx.tenant_id,
            Category.key == data.key,
        )
    ):
        fail("VALIDATION_FAILED", "key_taken", "品类键已存在。", 422)
    try:
        with s.begin_nested():
            result = _apply(s, ctx, data, proof, semantic, intent, material)
    except IntegrityError as error:
        # An invisible category or a concurrent creator can win the unique key.
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", "")
        if constraint in {"categories_tenant_id_key_key", "uq_categories_tenant_key"}:
            fail("VALIDATION_FAILED", "key_taken", "品类键已存在。", 422)
        raise
    return result


def _apply(s, ctx, data, proof, semantic, intent, material):
    category_id, receipt_id = proof.reserved_category_id, uuid4()
    candidate = _candidate(material)
    category = Category(
        id=category_id,
        tenant_id=ctx.tenant_id,
        key=data.key,
        name=data.human_edits.name if data.human_edits else data.name,
        purpose=data.human_edits.purpose if data.human_edits else data.purpose,
        owner_id=ctx.actor_id,
        revision=1,
        created_by_run_id=candidate.run.id if candidate else None,
    )
    s.add(category)
    s.flush([category])
    grant = Grant(
        tenant_id=ctx.tenant_id,
        category_id=category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        expires_at=None,
    )
    s.add(grant)
    s.flush([grant])
    provenance = dict(
        origin=_origin(material),
        writer_id=candidate.run.writer_id if candidate else ctx.actor_id,
        run_id=candidate.run.id if candidate else None,
        confirmed_by=ctx.actor_id if candidate else None,
        prepared_candidate_id=None,
        receipt_id=receipt_id,
    )
    snapshot_refs = _snapshot_manifest(candidate)
    if candidate:
        from pdos_next.agent_kernel.models import PublicWebSnapshot

        registered = set()
        for item in candidate.snapshots:
            if item.snapshot.id in registered:
                continue
            registered.add(item.snapshot.id)
            snapshot = PublicWebSnapshot(
                **asdict(item.snapshot),
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                owner_id=ctx.actor_id,
                visibility="category",
                registered_by_run_id=candidate.run.id,
                receipt_id=receipt_id,
            )
            s.add(snapshot)
            s.flush([snapshot])
    knowledge, parameters = [], []
    for item in data.groups.knowledge:
        content = dict(item.content)
        from .category_service import _references

        refs = _references(item)
        if item.kind == "voice":
            content["sample_size"] = len({(str(ref.id), ref.version, ref.line) for ref in refs})
        row = KnowledgeEntry(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=category_id,
            lineage_id=uuid4(),
            version=1,
            action="add",
            kind=item.kind,
            content=content,
            regions=item.regions,
            source_refs=[ref.model_dump(mode="json") for ref in refs],
            **provenance,
        )
        s.add(row)
        s.flush([row])
        s.add(
            KnowledgeCurrent(
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                lineage_id=row.lineage_id,
                kind=row.kind,
                current_entry_id=row.id,
                current_version=1,
                status="active",
                origin=row.origin,
            )
        )
        knowledge.append({"entry_id": str(row.id), "lineage_id": str(row.lineage_id), "version": 1})
    for item in data.groups.parameters:
        parameter_id = uuid4()
        row = ParameterVersion(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=category_id,
            parameter_id=parameter_id,
            version=1,
            replaces_version=None,
            **item.model_dump(),
            **provenance,
        )
        s.add(row)
        s.flush([row])
        s.add(
            ParameterCurrent(
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                parameter_id=parameter_id,
                key=item.key,
                current_version=1,
            )
        )
        parameters.append({"parameter_id": str(parameter_id), "key": item.key, "version": 1})
    receipt = Receipt(
        id=receipt_id,
        tenant_id=ctx.tenant_id,
        category_id=category_id,
        product_id=None,
        run_id=None,
        agent_run_id=None,
        command_id=uuid4(),
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation="category.create",
        subject_type="category",
        subject_id=category_id,
        subject_revision=1,
        visibility="category",
        request_digest=semantic,
        intent_digest=intent,
        result={
            "category_id": str(category_id),
            "key": data.key,
            "name": category.name,
            "purpose": category.purpose,
            **(
                {"human_edits": data.human_edits.model_dump(), "edited_by": str(ctx.actor_id)}
                if data.human_edits
                else {}
            ),
            "tier": "T1",
            "knowledge": knowledge,
            "parameters": parameters,
            "snapshot_refs": snapshot_refs,
            "groups": data.groups.model_dump(mode="json"),
            "groups_digest": digest(data.groups.model_dump(mode="json")),
            "origin": provenance["origin"],
            "seed_key": data.seed_key,
            "import_material": material.get("material") if material else None,
            **(
                {
                    "proof_version": 1,
                    "prepared_by_run_id": str(candidate.run.id),
                    "registered_by_run_id": str(candidate.run.id),
                    "category_candidate_event_id": str(candidate.event.id),
                    "candidate_digest": data.candidate_digest,
                }
                if candidate
                else {}
            ),
        },
    )
    if candidate:
        from pdos_next.agent_kernel.category_adoption import record

        record(s, candidate, receipt)
    s.add(receipt)
    s.flush([receipt])
    s.add_all(
        [
            Audit(
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                receipt_id=receipt_id,
                actor_id=ctx.actor_id,
                operation=receipt.operation,
            ),
            Outbox(
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                receipt_id=receipt_id,
                actor_id=ctx.actor_id,
                type="category.created",
                subject_id=category_id,
                subject_revision=1,
                correlation_id=receipt.command_id,
            ),
            RequestKey(
                tenant_id=ctx.tenant_id,
                category_id=category_id,
                actor_id=ctx.actor_id,
                key=data.idempotency_key,
                digest=semantic,
                receipt_id=receipt_id,
            ),
        ]
    )
    proof.consumed = True
    s.flush()
    return receipt_view(receipt)
