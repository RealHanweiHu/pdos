"""Candidate and named publication commands in the shared atomic domain UOW."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4, uuid5

from sqlalchemy import select

from pdos_next.contracts import Command
from pdos_next.domain.preproject.access import human
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.quality_execution.evidence import merge_reads
from pdos_next.models import now
from pdos_next.service import command_digest, command_scope, digest

from . import owner, provenance, rules
from .models import (
    ApplicabilityAssessment,
    DesignRuleCurrent,
    DesignRuleVersion,
    KnowledgeCandidateCurrent,
    KnowledgeCandidateVersion,
)
from .schemas import CANDIDATE_OP, PAYLOADS, RULE_OP

category_lifecycle_fence = True
semantic = rules.semantic


@dataclass
class Validated:
    session: object
    transaction: object
    fingerprint: str
    identity: object
    version_id: object
    revision: int
    previous: object
    pointer: object
    project_id: object
    owner_id: object
    visibility: str
    body: dict
    source_basis: dict
    review: dict
    candidate: object = None
    assessment_id: object = None
    nature: str | None = None
    confirmation_id: object = None
    used: bool = False


def _target_content(s, ctx, pid, value):
    refs, reads = {}, []

    def visit(item):
        if isinstance(item, dict):
            for ref in item.get("sources", []):
                if "artifact_id" in ref:
                    from pdos_next.domain.quality_execution.evidence import refs_from_exact
                    from pdos_next.schemas.products.definitions import DefinitionReference

                    ref = refs_from_exact(s, ctx, pid, [DefinitionReference.model_validate(ref)])[
                        0
                    ].model_dump(mode="json")
                if ref.get("kind") == "artifact":
                    refs[(ref["id"], ref["revision"], ref.get("position", ""))] = ref
            reads.extend(item.get("required_source_read_set", []))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    from .schemas import SourceRef

    return tuple(SourceRef.model_validate(ref) for ref in refs.values()), merge_reads(reads)


def _publication_material(s, ctx, product, payload, *, lock=False):
    target = owner.target(
        s, ctx, product.id, payload.project_id, payload.applicability.target, lock=lock
    )
    professional = authority.assess(
        s,
        ctx,
        product.id,
        payload.project_id,
        RULE_OP,
        payload.applicability.purpose,
        now(),
        write=lock,
    )
    rules.require(
        professional["authorized"] and professional["qualified"],
        "本次规则发布须有当前知识发布职责和适用资格。",
        "FORBIDDEN_SCOPE",
        403,
    )
    return target, professional


def validate(s, ctx, command, product, payload):
    key = ("knowledge-command", digest(vars(ctx)), command_digest(command), str(command.command_id))
    cached = s.info.get(key)
    if cached is not None and cached.transaction is s.get_transaction() and not cached.used:
        return cached
    rules.require(
        command.expected_revision == product.revision, "品类或型号版本已变化。", "VERSION_CONFLICT"
    )
    if not ctx.agent_run_id or command.operation == RULE_OP:
        human(s, ctx)
    artifacts, private = provenance.direct_basis(
        s, ctx, product, payload.sources, command.source_read_set
    )
    rules.require(
        all(
            item["product_id"] in (None, str(product.id) if product.id else None)
            for item in artifacts
        ),
        "本次直接输入须在当前型号或品类范围；跨型号经验通过固定候选来源及明确适用性采用。",
        "FORBIDDEN_SCOPE",
        403,
    )
    private |= getattr(product, "visibility", "category") != "category"
    prior = pointer = candidate = assessment_id = nature = None
    result_metadata, result_artifacts = [], []
    identity = uuid5(command.command_id, "knowledge-object")
    version_id, revision = identity, 1
    owner_id = ctx.requester_id
    target_material = professional = None
    if command.operation == CANDIDATE_OP:
        project_id, visibility = payload.project_id, payload.visibility
        if project_id is not None:
            native_project = owner.project(s, ctx, product.id, project_id, lock=True)
            private |= native_project.visibility != "category"
        result_metadata, result_artifacts, result_private = provenance.results(
            s, ctx, payload.result_receipts
        )
        private |= result_private
        if payload.candidate is not None:
            prior, pointer = owner.current(s, ctx, payload.candidate, lock=True)
            rules.require(
                (prior.product_id, prior.project_id, prior.owner_id, prior.visibility)
                == (product.id, project_id, ctx.requester_id, visibility),
                "候选续版须保留原范围、所有者和可见性。",
                "FORBIDDEN_SCOPE",
                403,
            )
            if ctx.actor_id != ctx.requester_id:
                consumed = s.scalar(
                    select(DesignRuleVersion.id)
                    .where(
                        DesignRuleVersion.tenant_id == ctx.tenant_id,
                        DesignRuleVersion.candidate_id == prior.candidate_id,
                    )
                    .limit(1)
                )
                rules.require(
                    prior.actor_id == ctx.actor_id and consumed is None,
                    "AI 只能续写本人草稿；具名修改或已发布采用的候选须由本人处理。",
                    "FORBIDDEN_SCOPE",
                    403,
                )
            identity, version_id, revision = (
                prior.candidate_id,
                uuid5(command.command_id, "knowledge-version"),
                prior.revision + 1,
            )
        body = rules.candidate_body(payload, identity, revision)
    else:
        rules.require(
            command.operation == RULE_OP and product.id is not None,
            "规则发布须绑定实际型号。",
            "FORBIDDEN_SCOPE",
            403,
        )
        rules.require(
            payload.applicability.decision == "applicable",
            "未知、冲突或不适用的评估不能发布适用规则。",
            "MISSING_REQUIRED_EVIDENCE",
            422,
        )
        candidate, _ = owner.current(s, ctx, payload.candidate, lock=True)
        provenance.sources_current(s, ctx, candidate.source_basis)
        provenance.results_current(s, ctx, candidate.source_basis)
        target_material, professional = _publication_material(s, ctx, product, payload, lock=True)
        native_project, target_row, target_view, target_basis = target_material
        target_refs, _ = _target_content(s, ctx, product.id, target_view)
        target_artifacts, target_private = provenance.direct_basis(
            s, ctx, product, target_refs, command.source_read_set
        )
        artifacts = rules.merge_artifacts(
            artifacts, candidate.source_basis.get("artifacts", []), target_artifacts
        )
        result_metadata = deepcopy(candidate.source_basis.get("result_receipts", []))
        private |= (
            candidate.visibility != "category"
            or native_project.visibility != "category"
            or target_row.visibility != "category"
            or target_private
        )
        visibility, project_id = "private" if private else "category", native_project.id
        if candidate.visibility == "private":
            rules.require(
                candidate.owner_id == owner_id,
                "私有候选须由其实际所有者办理；不能借发布扩大来源受众。",
                "FORBIDDEN_SCOPE",
                403,
            )
        if payload.rule is not None:
            prior, pointer = owner.current(s, ctx, payload.rule, rule=True, lock=True)
            rules.require(
                (prior.product_id, prior.project_id, prior.visibility)
                == (product.id, project_id, visibility),
                "规则续版须保留原项目和可见范围。",
                "FORBIDDEN_SCOPE",
                403,
            )
            owner_id = prior.owner_id
            identity, version_id, revision = (
                prior.rule_id,
                uuid5(command.command_id, "knowledge-version"),
                prior.revision + 1,
            )
        assessment_id = uuid5(command.command_id, "knowledge-applicability")
        nature = "synthetic" if professional["synthetic"] else "real"
        assessment = rules.assessment_body(payload, candidate, ctx.requester_id)
        body = rules.rule_body(
            payload, identity, revision, candidate, assessment_id, assessment, nature
        )
    rules.require(
        not private or visibility == "private",
        "私有或指定受众的内容不能扩大为品类共享知识。",
        "FORBIDDEN_SCOPE",
        403,
    )
    basis = {
        "artifacts": rules.merge_artifacts(artifacts, result_artifacts),
        "result_receipts": result_metadata,
    }
    if professional is not None:
        basis.update(
            {
                "professional": professional,
                "candidate": {
                    "id": str(candidate.id),
                    "revision": candidate.revision,
                    "body_sha256": candidate.body_sha256,
                },
                "target": target_material[3],
            }
        )
    review = {
        "operation": command.operation,
        "declaration": semantic(payload),
        "before": deepcopy(prior.body) if prior else None,
        "after": body,
        "sources": [ref.model_dump(mode="json") for ref in payload.sources],
        "source_basis": basis,
        "effect": (
            "经验候选保留假设；正式规则仅由当前有权本人发布，适用范围固定到本次配置、用途和条件。"
        ),
    }
    value = Validated(
        s,
        s.get_transaction(),
        command_digest(command),
        identity,
        version_id,
        revision,
        prior,
        pointer,
        project_id,
        owner_id,
        visibility,
        body,
        basis,
        review,
        candidate,
        assessment_id,
        nature,
    )
    s.info[key] = value
    return value


def confirmation_subject(s, ctx, command, product, payload):
    return "product", product


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def inputs(s, ctx, pid, command):
    rules.require(
        command.product_id == pid
        and command.category_id == ctx.category_id
        and command.operation in PAYLOADS,
        "知识材料与当前范围不一致。",
        "FORBIDDEN_SCOPE",
        403,
    )
    payload = PAYLOADS[command.operation].model_validate(command.payload)
    product = command_scope(s, ctx, command, lock=True)
    reads = [
        {"artifact_id": str(ref.id), "expected_revision": ref.revision} for ref in payload.sources
    ]
    if command.operation == RULE_OP:
        target, professional = _publication_material(s, ctx, product, payload, lock=True)
        _, target_reads = _target_content(s, ctx, product.id, target[2])
        reads = merge_reads(reads, target_reads, professional["required_source_read_set"])
    else:
        reads = merge_reads(reads)
    prepared = Command.model_validate({**command.model_dump(mode="json"), "source_read_set": reads})
    value = validate(s, ctx, prepared, product, payload)
    return {"payload": semantic(payload), "required_source_read_set": reads, "review": value.review}


def apply_validated(s, ctx, command, product, payload, value):
    rules.require(
        value.session is s
        and value.transaction is s.get_transaction()
        and value.fingerprint == command_digest(command)
        and not value.used,
        "缺少本次事务的实际知识核对。",
        "INTEGRITY_MISMATCH",
    )
    value.used = True
    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    scope = dict(
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product.id,
        project_id=value.project_id,
        owner_id=value.owner_id,
        visibility=value.visibility,
    )
    common = dict(
        **scope,
        id=value.version_id,
        revision=value.revision,
        writer_id=ctx.actor_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        operation=command.operation,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": value.review,
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        sources=value.review["sources"],
        reads=[r.model_dump(mode="json") for r in command.source_read_set],
        source_basis=value.source_basis,
        body=value.body,
        body_sha256=digest(value.body),
        request_digest=command_digest(command),
        receipt_id=uuid4(),
        confirmation_id=value.confirmation_id,
        intent_digest=digest(
            {
                "operation": command.operation,
                "category": command.category_id,
                "product": command.product_id,
                "payload": semantic(payload),
                "named_actor": ctx.requester_id,
                "source_revision": None,
                "private_owner": ctx.requester_id
                if getattr(payload, "visibility", "private") == "private"
                else None,
            }
        ),
        previous_id=value.previous.id if value.previous else None,
        previous_revision=value.previous.revision if value.previous else None,
    )
    if command.operation == CANDIDATE_OP:
        row = KnowledgeCandidateVersion(candidate_id=value.identity, **common)
        pointer_model, key, kind = KnowledgeCandidateCurrent, "candidate_id", "knowledge_candidate"
        row.action_result = {
            "candidate_id": str(value.identity),
            "project_id": str(value.project_id) if value.project_id else None,
        }
    else:
        row = DesignRuleVersion(
            rule_id=value.identity,
            candidate_id=value.candidate.candidate_id,
            candidate_version_id=value.candidate.id,
            candidate_revision=value.candidate.revision,
            assessment_id=value.assessment_id,
            nature=value.nature,
            valid_from=payload.applicability.valid_from,
            valid_until=payload.applicability.valid_until,
            **common,
        )
        s.add(
            ApplicabilityAssessment(
                id=value.assessment_id,
                publication_id=row.id,
                candidate_version_id=value.candidate.id,
                candidate_revision=value.candidate.revision,
                actor_id=ctx.actor_id,
                body=value.body["applicability"],
                body_sha256=digest(value.body["applicability"]),
                receipt_id=row.receipt_id,
                **scope,
            )
        )
        pointer_model, key, kind = DesignRuleCurrent, "rule_id", "design_rule"
        row.action_result = {
            "rule_id": str(value.identity),
            "project_id": str(value.project_id),
            "assessment_id": str(value.assessment_id),
        }
    s.add(row)
    s.flush([row])
    if value.pointer is None:
        s.add(
            pointer_model(
                **scope, **{key: value.identity}, version_id=row.id, revision=row.revision
            )
        )
    else:
        value.pointer.version_id, value.pointer.revision = row.id, row.revision
    row.prepared_receipt_id, row._knowledge_phase = row.receipt_id, value
    return row, kind, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    value = getattr(subject, "_knowledge_phase", None)
    rules.require(
        value is not None
        and value.used
        and value.session is s
        and value.transaction is s.get_transaction()
        and subject.receipt_id == receipt.id
        and digest(subject.body) == subject.body_sha256,
        "知识写入缺少同事务共同回执。",
        "INTEGRITY_MISMATCH",
    )
    provenance.sources_current(s, ctx, value.source_basis)
    provenance.results_current(s, ctx, value.source_basis)
    if command.operation == RULE_OP:
        current, _ = owner.current(s, ctx, payload.candidate, lock=True)
        rules.require(current.id == value.candidate.id, "候选已变化。", "VERSION_CONFLICT")
        checked = authority.recheck_snapshot(
            s,
            ctx,
            product.id,
            payload.project_id,
            value.source_basis["professional"],
            now(),
            write=True,
        )
        rules.require(checked["current"], "发布职责或资格已变化。", "FORBIDDEN_SCOPE", 403)
        owner.target(
            s, ctx, product.id, payload.project_id, payload.applicability.target, lock=True
        )
    del subject._knowledge_phase
