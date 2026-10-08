"""Current fact work context and inputs. Writes stay in common commands."""

# ruff: noqa: I001
from pdos_next.service import Context, digest, require_access, source_for

import json
from hashlib import sha256
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select

from pdos_next.capa_candidate_api import _selected, _final_scope
from pdos_next.capa_fact_owner import instant
from pdos_next.capa_review_context import read_review_selection, verify_review_selection
from pdos_next.database import tenant_session
from pdos_next.domain.capa_effectiveness import (
    candidate_commands,
    candidate_storage,
    candidate_prepare,
)
from pdos_next.domain.capa_effectiveness import (
    fact_atom_storage,
    fact_commands as commands,
    fact_service,
    fact_storage_models as models,
)
from pdos_next.domain.capa_effectiveness.fact_registry_storage import read_stored_fact
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.fact_write import prepare_fact, reviewed_fact
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution import evidence, policy
from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Product
from pdos_next.schemas.verification.contracts import SourceRef
from pydantic import ValidationError

SCHEMA = "pdos-capa-fact-workflow-v1"


def _missing(code, detail):
    return {"code": code, "detail": detail}


def _source_choice(s, ctx, pid, ref):
    match = evidence.POSITION.fullmatch(ref.position) if ref.kind == "artifact" else None
    if match is None:
        return None
    row = source_for(s, ctx, pid, ref.id, ref.revision)
    evidence.check_source(s, ctx, pid, ref)
    line = int(match[1])
    return {
        "source": ref.model_dump(mode="json"),
        "title": row.title,
        "line": line,
        "quote": row.content.splitlines()[line - 1],
        "visibility": row.visibility,
    }


def _history(s, ctx, pid, issue_id):
    history, actual = [], {"rule": [], "observation": [], "review": []}
    for kind, cls in (
        ("rule", models.RuleFact),
        ("observation", models.ObservationFact),
        ("review", models.NamedReviewRecord),
    ):
        rows = list(
            s.scalars(
                select(cls)
                .where(
                    cls.tenant_id == ctx.tenant_id, cls.product_id == pid, cls.issue_id == issue_id
                )
                .order_by(cls.created_at.desc(), cls.id)
                .limit(101)
            )
        )
        if len(rows) > 100:
            raise DomainError("RECHECK_REQUIRED", "事实历史超过本次完整读取上限。", 409)
        for row in rows:
            if row.visibility == "private" and row.owner_id != ctx.actor_id:
                continue
            atom = fact_atom_storage.read_fact_atom(
                s, ctx, pid, kind=kind, fact_id=row.id, revision=row.revision
            )
            fact = assemble_fact(
                row.fact_body, atom.atom, expected_payload_sha256=row.payload_sha256
            )
            stored = read_stored_fact(
                s,
                ctx,
                pid,
                kind,
                fact.ref,
                candidate_owner=candidate_storage.candidate_owner(
                    candidate_commands.semantic_owner()
                ),
            )
            actual[kind].append(stored)
            label = {
                "rule": "已发布的固定核验规则",
                "observation": "已保存的实际观察",
                "review": "已保存的具名复核",
            }[kind]
            history.append(
                {
                    "ref": fact.ref.model_dump(mode="json"),
                    "kind": kind,
                    "label": f"{label} · v{fact.ref.revision}",
                    "fact": fact.model_dump(mode="json"),
                    "current_evaluation": "not_evaluated_historical",
                    "source_status": "needs_recheck",
                    "missing": [
                        _missing(
                            "FACT_CURRENT_OWNER_REQUIRED",
                            "历史保存记录需经当前专业核对后作为判断依据。",
                        )
                    ],
                    "registry_state": stored.registry.state,
                }
            )
    return history, actual


def fact_context(s, ctx, pid, issue_id, candidate_id=None):
    with s.no_autoflush:
        require_access(s, ctx, pid, lock=True)
        caller, _ = candidate_prepare._caller(s, ctx, pid)
        row, issue, project, current, origin, _ = _selected(s, ctx, pid, issue_id)
        product = fact_atom_storage._one(
            s, Product, Product.tenant_id == ctx.tenant_id, Product.id == pid
        )
        runtime = fact_service._runtime(s)
        runtime_stamp, product_revision = runtime.host.owner.runtime_stamp(s), product.revision
        current_checks = {}
        history, actual = _history(s, ctx, pid, issue_id)
        sources, records, rules, observations = {}, [], [], []
        candidate_options, pairs, selected_candidate, review_read = [], [], None, None
        missing, operations = [], {}
        current_rules = [
            value.fact for value in actual["rule"] if value.registry.state == "current_registered"
        ]
        if len(current_rules) > 1:
            missing.append(
                _missing("RULE_CURRENT_AMBIGUOUS", "有多份当前规则，需核对精确适用范围。")
            )
            current_rules = []
        active_rule = current_rules[0] if current_rules else None
        if active_rule is None:
            missing.append(
                _missing("RULE_PUBLICATION_REQUIRED", "尚无可信服务器发布的当前核验规则。")
            )
        snapshot, candidate = None, None
        for op in (commands.OBSERVATION_OPERATION, commands.REVIEW_OPERATION):
            authority = professional.assess(
                s, ctx, pid, row.project_id, op, row.purpose, datetime.now(UTC), write=False
            )
            op_missing = [
                _missing(code, "本操作当前具名职责或资格尚需核对。")
                for code in authority["reason_codes"]
            ]
            reads = evidence.merge_reads(
                row.required_source_read_set, authority.get("required_source_read_set", [])
            )
            allowed, status, evaluation = False, "needs_recheck", "unavailable"
            if active_rule is not None:
                try:
                    selector = type("RuleSelection", (), {"rule": active_rule.ref})()
                    selected, saved = runtime.host.owner._rule(s, ctx, pid, selector)
                    runtime.host.owner._anchor(s, ctx, pid, saved)
                    current_authority, refs = runtime.host.owner._authority(
                        s, ctx, pid, saved.origin, op
                    )
                    active_policy = policy.assess(s, ctx, pid, row.project_id, row.purpose)
                    reads = evidence.merge_reads(
                        selected.required_source_read_set,
                        current_authority["required_source_read_set"],
                        active_policy["required_source_read_set"],
                    )
                    source_basis, _ = evidence.source_basis(s, ctx, pid, reads)
                    authority, snapshot = current_authority, saved
                    current_checks[op] = (
                        selected,
                        saved,
                        current_authority,
                        active_policy,
                        source_basis,
                    )
                    for ref in (*selected.sources, *refs):
                        choice = _source_choice(s, ctx, pid, ref)
                        if choice:
                            sources[(str(ref.id), ref.revision, ref.kind, ref.position)] = choice
                    allowed, status, evaluation = (
                        op == commands.OBSERVATION_OPERATION,
                        "current",
                        "evaluated_current",
                    )
                except DomainError as error:
                    if error.status in {401, 403} and error.code == "FORBIDDEN_SCOPE":
                        raise
                    op_missing.append(_missing(error.code, error.message))
            else:
                op_missing.extend(missing)
            operations[op] = {
                "allowed": allowed,
                "authority": {
                    "authorized": authority.get("authorized") is True,
                    "qualified": authority.get("qualified"),
                    "synthetic": authority.get("synthetic") is True,
                },
                "independence": "not_required"
                if op == commands.OBSERVATION_OPERATION
                else "not_verified",
                "current_evaluation": evaluation,
                "source_status": status,
                "missing": op_missing,
                "required_source_read_set": reads,
            }
        if active_rule is not None and snapshot is not None:
            pointers = [
                value.fact
                for value in actual["observation"]
                if value.registry.state == "current_registered"
                and value.fact.rule == active_rule.ref
            ]
            observations = [value.ref.model_dump(mode="json") for value in pointers]
            previous = next(
                (
                    value.ref.model_dump(mode="json")
                    for value in pointers
                    if value.executor_id == ctx.actor_id
                ),
                None,
            )
            rules = [
                {
                    "ref": active_rule.ref.model_dump(mode="json"),
                    "label": f"当前固定核验规则 v{active_rule.ref.revision}",
                    "target_keys": [value.key for value in active_rule.sampling.targets],
                    "previous": previous,
                }
            ]
            candidates = list(
                s.scalars(
                    select(CapaVerificationEvidence)
                    .where(
                        CapaVerificationEvidence.tenant_id == ctx.tenant_id,
                        CapaVerificationEvidence.product_id == pid,
                        CapaVerificationEvidence.project_id == row.project_id,
                        CapaVerificationEvidence.issue_id == issue_id,
                        CapaVerificationEvidence.capa_id == issue.capa.id,
                        or_(
                            CapaVerificationEvidence.visibility == "product",
                            CapaVerificationEvidence.owner_id == ctx.actor_id,
                        ),
                    )
                    .order_by(CapaVerificationEvidence.created_at, CapaVerificationEvidence.id)
                    .limit(101)
                )
            )
            if len(candidates) > 100:
                raise DomainError("RECHECK_REQUIRED", "候选范围超过完整读取上限。", 409)
            for value in candidates:
                if (
                    value.input_snapshot["stable_anchor"]["anchor_sha256"]
                    != active_rule.anchor_sha256
                ):
                    continue
                selected = candidate_storage.read_candidate(
                    s, ctx, pid, value.id, semantic_owner=candidate_commands.semantic_owner()
                )
                candidate_options.append(
                    {
                        "ref": selected.ref.model_dump(mode="json"),
                        "label": f"复验候选 · {value.created_at.isoformat()}",
                        "mapping_count": len(selected.binding.mappings),
                        "visibility": value.visibility,
                    }
                )
                if value.id == candidate_id:
                    selected_candidate = selected
                    candidate = selected.ref.model_dump(mode="json")
            raw_records = list(
                s.scalars(
                    select(Artifact)
                    .where(
                        Artifact.tenant_id == ctx.tenant_id,
                        Artifact.product_id == pid,
                        Artifact.status == "active",
                        or_(Artifact.visibility == "product", Artifact.owner_id == ctx.actor_id),
                        Artifact.content.contains("pdos-capa-observation-source-v1"),
                    )
                    .order_by(Artifact.created_at, Artifact.id)
                    .limit(101)
                )
            )
            if len(raw_records) > 100:
                raise DomainError("RECHECK_REQUIRED", "实际观察原记录超过完整读取上限。", 409)
            for source in raw_records:
                if source.original_id is not None:
                    continue
                for line, quote in enumerate(source.content.splitlines(), 1):
                    try:
                        value = json.loads(quote)
                    except ValueError:
                        continue
                    if (
                        not isinstance(value, dict)
                        or value.get("schema_version") != "pdos-capa-observation-source-v1"
                        or value.get("rule") != active_rule.ref.model_dump(mode="json")
                        or value.get("scope") != snapshot.origin.scope.model_dump(mode="json")
                        or value.get("nature") != snapshot.origin.nature
                        or value.get("issue_id") != str(issue_id)
                        or value.get("capa_id") != str(issue.capa.id)
                        or value.get("purpose") != row.purpose
                    ):
                        continue
                    ref = SourceRef(
                        id=source.id,
                        revision=source.revision,
                        kind="artifact",
                        position=f"line:{line};quote_sha256:{sha256(quote.encode()).hexdigest()}",
                    )
                    try:
                        record = commands.ObservationRecordInput.model_validate(
                            {**value["record"], "sources": [ref.model_dump(mode="json")]}
                        )
                        selection = commands.ObservationPayload.model_validate(
                            {
                                "issue_id": issue_id,
                                "expected_issue_revision": row.revision,
                                "capa_id": issue.capa.id,
                                "rule": active_rule.ref,
                                "target_keys": [record.target_key],
                                "observed_from": value["observed_from"],
                                "observed_until": value["observed_until"],
                                "at": {**value["at"], "source": ref.model_dump(mode="json")},
                                "records": [record],
                                "coverage_sources": [ref.model_dump(mode="json")],
                                "sources": [ref.model_dump(mode="json")],
                                "reason": "读取实际已注册的原观察范围",
                                "visibility": row.visibility,
                            }
                        )
                        if selection.at.occurred_at > datetime.now(UTC):
                            continue
                        runtime.host.owner._original_record(
                            s, ctx, pid, snapshot.origin, active_rule, selection, record
                        )
                    except (KeyError, TypeError, ValueError, ValidationError):
                        continue
                    sources[(str(ref.id), ref.revision, ref.kind, ref.position)] = _source_choice(
                        s, ctx, pid, ref
                    )
                    records.append(
                        {
                            "key": f"{source.id}:{line}",
                            "label": f"{source.title} · {record.target_key}",
                            "detail": (
                                f"原记录发生于 {record.occurred_at.isoformat()}；"
                                f"范围 {value['observed_from']} ～ {value['observed_until']}"
                            ),
                            "record": record.model_dump(mode="json"),
                            "observed_from": selection.observed_from.isoformat(),
                            "observed_until": selection.observed_until.isoformat(),
                            "at": selection.at.model_dump(mode="json"),
                            "visibility": source.visibility,
                        }
                    )
        if candidate_id is not None and selected_candidate is None:
            raise DomainError("FORBIDDEN_SCOPE", "所选候选不在当前可读的固定规则范围。", 403)
        review_capability = operations[commands.REVIEW_OPERATION]
        if selected_candidate is None:
            review_capability["missing"].append(
                _missing(
                    "FACT_REVIEW_CANDIDATE_SELECTION_REQUIRED",
                    "请明确选择一份固定候选，再核对实际复验与本人独立资格。",
                )
            )
        elif active_rule is not None and commands.REVIEW_OPERATION in current_checks:
            try:
                review_read = read_review_selection(
                    s,
                    ctx,
                    pid,
                    runtime.host.owner,
                    active_rule,
                    snapshot,
                    selected_candidate,
                    tuple(value.ref for value in pointers),
                )
                for ref in review_read.sources:
                    choice = _source_choice(s, ctx, pid, ref)
                    if choice:
                        sources[(str(ref.id), ref.revision, ref.kind, ref.position)] = choice
                pairs = list(review_read.choices)
                review_capability.update(
                    {
                        "allowed": True,
                        "independence": "verified",
                        "current_evaluation": "evaluated_current",
                        "source_status": "current",
                        "required_source_read_set": [
                            v.model_dump(mode="json") for v in review_read.reads
                        ],
                    }
                )
            except DomainError as error:
                if error.code == "FORBIDDEN_SCOPE":
                    raise
                review_capability["allowed"] = False
                review_capability["missing"].append(_missing(error.code, error.message))
                review_read = None
        host = {
            "schema_version": SCHEMA,
            "binding": {
                "scope": {
                    "tenant_id": str(ctx.tenant_id),
                    "product_id": str(pid),
                    "project_id": str(row.project_id),
                },
                "caller_id": str(ctx.actor_id),
                "issue_id": str(issue_id),
                "current_issue": {"id": str(current.ref.id), "revision": current.ref.revision},
                "capa_id": str(issue.capa.id),
                "purpose": row.purpose,
                "owner_id": str(row.owner_id),
                "visibility": row.visibility,
            },
            "product_revision": product_revision,
            "rules": rules,
            "candidate": candidate,
            "candidate_options": candidate_options,
            "observations": observations,
            "sources": list(sources.values()),
            "records": records,
            "pairs": pairs,
            "actions": [
                {
                    "action_id": str(value.id),
                    "label": value.text,
                    "detail": "实际完成记录保留，正式履行仍需核对。",
                    "visibility": row.visibility,
                }
                for value in issue.capa.actions
            ],
            "history": history,
            "operations": operations,
            "missing": missing,
            "effectiveness_enabled": False,
            "close_enabled": False,
        }
        # Source option/history reads cannot leave an earlier display gate valid.
        # Recheck current material in the same UOW after the last option read.
        for op, (selected, saved, old_authority, old_policy, old_basis) in current_checks.items():
            selector = type("RuleSelection", (), {"rule": selected.ref})()
            fresh_rule, fresh_anchor = runtime.host.owner._rule(s, ctx, pid, selector)
            runtime.host.owner._anchor(s, ctx, pid, fresh_anchor)
            fresh_authority, _ = runtime.host.owner._authority(s, ctx, pid, saved.origin, op)
            fresh_policy = policy.assess(s, ctx, pid, row.project_id, row.purpose)
            fresh_basis, _ = evidence.source_basis(
                s,
                ctx,
                pid,
                evidence.merge_reads(
                    selected.required_source_read_set,
                    old_authority["required_source_read_set"],
                    old_policy["required_source_read_set"],
                ),
            )
            if (
                fresh_rule != selected
                or fresh_anchor != saved
                or fresh_authority != old_authority
                or fresh_policy != old_policy
                or fresh_basis != old_basis
            ):
                raise DomainError(
                    "SOURCE_STALE", "读取期间规则、资格、政策或原件已变化，请重新读取。", 409
                )
        for choice in sources.values():
            evidence.check_source(s, ctx, pid, SourceRef.model_validate(choice["source"]))
        if selected_candidate is not None:
            late_candidate = candidate_storage.read_candidate(
                s,
                ctx,
                pid,
                selected_candidate.ref.id,
                selected_candidate.ref,
                semantic_owner=candidate_commands.semantic_owner(),
            )
            if (
                late_candidate.binding != selected_candidate.binding
                or late_candidate.group != selected_candidate.group
            ):
                raise DomainError("SOURCE_STALE", "所选候选在读取期间已变化。", 409)
            if review_read is not None:
                fresh_review = read_review_selection(
                    s,
                    ctx,
                    pid,
                    runtime.host.owner,
                    active_rule,
                    snapshot,
                    late_candidate,
                    tuple(value.ref for value in pointers),
                )
                verify_review_selection(review_read, fresh_review)
        _final_scope(s, ctx, pid, row, issue, project, current, origin, caller)
        require_access(s, ctx, pid, lock=True)
        final_clock = datetime.now(UTC)
        if review_read is not None and final_clock >= fresh_review.valid_until:
            raise DomainError("SOURCE_STALE", "读取期间实际复验或参与者证明已到期。", 409)
        if any(
            final_clock
            >= min(
                selected.valid_until,
                instant(authority["valid_until"]),
                instant(active_policy["valid_until"]),
            )
            for selected, _, authority, active_policy, _ in current_checks.values()
        ):
            raise DomainError("SOURCE_STALE", "读取期间规则、资格或政策已到期，请重新核对。", 409)
        if (
            fact_service._runtime(s) is not runtime
            or runtime.host.owner.runtime_stamp(s) != runtime_stamp
            or product.revision != product_revision
        ):
            raise DomainError("SOURCE_STALE", "读取期间办理入口或产品版本已变化。", 409)
        host["access_epoch"] = digest(jsonable_encoder(host))
        return host


def register_routes(app: FastAPI, engine, auth_dependency):
    @app.get("/v1/products/{product_id}/capa-facts")
    def get_facts(
        product_id: UUID,
        issue_id: UUID,
        request: Request,
        candidate_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        if any(
            key not in {"issue_id", "candidate_id"} or len(request.query_params.getlist(key)) != 1
            for key in request.query_params
        ):
            raise DomainError("INVALID_REQUEST", "请选择一个明确的当前问题。", 422)
        with tenant_session(engine, ctx.tenant_id) as s:
            return jsonable_encoder(fact_context(s, ctx, product_id, issue_id, candidate_id))

    @app.post("/v1/products/{product_id}/capa-facts/inputs")
    def inputs(
        product_id: UUID, command: Command, request: Request, ctx: Context = auth_dependency
    ):
        if (
            request.query_params
            or command.product_id != product_id
            or command.operation not in fact_service.OPERATIONS
        ):
            raise DomainError(
                "INVALID_REQUEST", "请提交本问题实际观察或本人具名复核的完整请求。", 422
            )
        kind = "observation" if command.operation == commands.OBSERVATION_OPERATION else "review"
        payload = commands.payload_for(kind, command.payload)
        if getattr(payload, "confirmation_token", None) or getattr(payload, "approval_token", None):
            raise DomainError("INVALID_REQUEST", "输入核对不消费或替换已准备的确认。", 422)
        with tenant_session(engine, ctx.tenant_id) as s:
            require_access(s, ctx, product_id, write=True, lock=True)
            runtime = fact_service._runtime(s)
            prepared = prepare_fact(s, ctx, product_id, payload, host=runtime.host, new_write=True)
            try:
                data = command.model_dump(mode="json")
                data["source_read_set"] = [
                    value.model_dump(mode="json") for value in prepared.required_source_read_set
                ]
                return {"command": data, "review": reviewed_fact(prepared, host=runtime.host)}
            finally:
                fact_service._discard(runtime, prepared)
