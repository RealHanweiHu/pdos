"""Usable handlers behind existing host commands; no database or proof store here."""

from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.schemas.discovery.contracts import (
    CandidateRequest,
    DefinitionCandidate,
    ImportBatch,
    Provenance,
    Research,
    ResearchStart,
    StoredObservation,
)
from pdos_next.schemas.products.definitions import (
    DefinitionDraftPayload,
    DefinitionReference,
    DefinitionSpec,
)

from .ports import Authority, Mutation, Ports
from .rules import conflicts, digest, groups, missing_categories, spec_unknowns


def changed(model, **changes):
    return type(model).model_validate({**model.model_dump(), **changes})


def observation_intent(observation):
    data = observation.model_dump(mode="json", exclude={"id"})
    data["sources"] = sorted(data["sources"], key=digest)
    return digest(data)


class Discovery:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _port(self, name):
        port = getattr(self.ports, name)
        if port is None:
            raise DomainError("PORT_UNAVAILABLE", f"研究{name}端口未接入。", 503)
        return port

    def _authorize(self, authority: Authority):
        if not authority.authorized or authority.cancelled:
            raise DomainError("FORBIDDEN_SCOPE", "当前研究授权已失效或取消。", 403)
        if authority.scope_id is None or not authority.purpose.strip():
            raise DomainError("SCOPE_BINDING_REQUIRED", "先由服务器绑定真实研究范围与用途。", 422)
        if authority.actor_kind != "human":
            raise DomainError("CAPABILITY_DISABLED", "AI研究写入尚未接入真实资格与运行守卫。", 403)

    def _scope(self, authority, research):
        self._authorize(authority)
        if (
            research.tenant_id != authority.tenant_id
            or research.scope_id != authority.scope_id
            or research.audience != authority.audience
            or (research.audience == "private" and research.owner_id != authority.actor_id)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "研究范围或受众与当前授权不一致。", 403)

    def _current(self, authority, research):
        self._scope(authority, research)
        sources = self._port("sources")
        for item in research.items:
            sources.check(authority, item.source)
        verified = []
        for stored in research.observations:
            for citation in stored.observation.sources:
                sources.check(authority, citation)
            verdict = sources.verify(authority, stored.observation)
            if verdict.accepted_requirement and (
                verdict.status != "verified" or stored.observation.accepted_requirement_id is None
            ):
                raise DomainError("INTEGRITY_MISMATCH", "已接受需求核验缺少有效具名记录。")
            verified.append(StoredObservation(observation=stored.observation, verification=verdict))
        return changed(research, observations=tuple(verified))

    def start(self, authority: Authority, research_id: UUID, payload: ResearchStart) -> Research:
        self._authorize(authority)
        for entry in (*payload.questions, *payload.use_cases):
            if not entry.strip() or len(entry) > 2000:
                raise DomainError("INVALID_PAYLOAD", "问题与场景须为非空文字。", 422)
        research = Research(
            id=research_id,
            tenant_id=authority.tenant_id,
            owner_id=authority.actor_id,
            audience=authority.audience,
            scope_id=authority.scope_id,
            revision=1,
            **payload.model_dump(),
        )
        return self._port("research").record(
            authority,
            Mutation(
                research=research,
                before_revision=0,
                intent_digest=digest(
                    {"scope": str(authority.scope_id), "start": payload.model_dump(mode="json")}
                ),
                event="research.started",
            ),
        )

    def inspect(self, authority: Authority, research_id: UUID) -> Research:
        """Fail closed before rendering any source-derived content after ACL drift."""
        return self._current(authority, self._port("research").locked(authority, research_id))

    def ingest(
        self, authority: Authority, research_id: UUID, expected_revision: int, payload: ImportBatch
    ) -> Research:
        current = self.inspect(authority, research_id)
        if current.revision != expected_revision:
            raise DomainError("VERSION_CONFLICT", "研究已变化，请读取当前来源包。")
        sources = self._port("sources")
        items = list(current.items)
        item_digests = {digest(i) for i in items}
        for item in payload.items:
            sources.check(authority, item.source)
            if digest(item) not in item_digests:
                items.append(item)
                item_digests.add(digest(item))
        available = {digest(item.source) for item in items}
        entries = list(current.observations)
        by_id = {e.observation.id: e.observation for e in entries}
        intents = {observation_intent(e.observation) for e in entries}
        for observation in payload.observations:
            if any(digest(c) not in available for c in observation.sources):
                raise DomainError("MISSING_REQUIRED_EVIDENCE", "观察只能引用已登记来源包精确位置。")
            if observation.id in by_id and by_id[observation.id] != observation:
                raise DomainError("IDEMPOTENCY_CONFLICT", "观察身份不能静默覆盖。")
            for citation in observation.sources:
                sources.check(authority, citation)
            verdict = sources.verify(authority, observation)
            if verdict.accepted_requirement and (
                verdict.status != "verified" or observation.accepted_requirement_id is None
            ):
                raise DomainError("INTEGRITY_MISMATCH", "已接受需求须核对有效记录。")
            semantic = observation_intent(observation)
            if semantic not in intents:
                entries.append(StoredObservation(observation=observation, verification=verdict))
                intents.add(semantic)
                by_id[observation.id] = observation
        if len(entries) > 100 or len(items) > 100:
            raise DomainError("INVALID_PAYLOAD", "首版来源包和观察各最多100项。", 422)
        no_change = tuple(items) == current.items and tuple(entries) == current.observations
        next_research = changed(
            current,
            items=tuple(items),
            observations=tuple(entries),
            revision=current.revision if no_change else current.revision + 1,
        )
        # A changing command key must not create another copy of these observations.
        semantic = {
            "scope": str(authority.scope_id),
            "research": str(current.id),
            "items": sorted(digest(i) for i in payload.items),
            "observations": sorted(observation_intent(o) for o in payload.observations),
        }
        return self._port("research").record(
            authority,
            Mutation(
                research=next_research,
                before_revision=current.revision,
                intent_digest=digest(semantic),
                event="discovery.sources_imported",
                replayed_content=no_change,
            ),
        )

    def preview(
        self,
        authority: Authority,
        research_id: UUID,
        expected_revision: int,
        request: CandidateRequest,
    ) -> DefinitionCandidate:
        research = self.inspect(authority, research_id)
        if research.revision != expected_revision:
            raise DomainError("VERSION_CONFLICT", "来源包变化，需核对新增或更正内容。")
        if authority.product_id is None or authority.product_revision is None:
            raise DomainError(
                "PRODUCT_BINDING_REQUIRED", "研究可独立保存；提交定义前须绑定真实产品。"
            )
        grouped = groups(research)
        chosen = {s.key: s for s in request.selections}
        if len(chosen) != len(request.selections) or set(chosen) - grouped.keys():
            raise DomainError("INVALID_SELECTION", "候选组不能重复或引用不存在的组。", 422)
        missing = missing_categories(research, authority.required_categories)
        omitted = tuple(sorted(grouped.keys() - chosen.keys()))
        if (missing or omitted) and not request.partial_reason:
            raise DomainError("PARTIAL_REASON_REQUIRED", "部分导入须保留缺项并说明范围。", 422)
        all_conflicts = conflicts(research)
        conflicting = {c.key for c in all_conflicts}
        unknowns = [f"来源包缺项：{v}" for v in missing] + [f"未导入候选组：{v}" for v in omitted]
        if request.partial_reason:
            unknowns.append(f"部分导入范围：{request.partial_reason}")
        requirements, constraints, specs, provenance, refs = [], [], [], [], {}
        # Keep the whole pinned package and all competing evidence, even in partial imports.
        for item in research.items:
            ref = DefinitionReference(
                artifact_id=item.source.artifact_id,
                expected_revision=item.source.expected_revision,
                line=item.source.derived_line,
                quote=item.source.quote,
            )
            refs[digest(ref)] = ref
        for key, selection in sorted(chosen.items()):
            entries = grouped[key]
            selected = next(
                (e for e in entries if e.observation.id == selection.observation_id), None
            )
            if selection.observation_id is not None and selected is None:
                raise DomainError("INVALID_SELECTION", "所选观察不属于候选组。", 422)
            citations = {
                digest(
                    DefinitionReference(
                        artifact_id=c.artifact_id,
                        expected_revision=c.expected_revision,
                        line=c.derived_line,
                        quote=c.quote,
                    )
                ): DefinitionReference(
                    artifact_id=c.artifact_id,
                    expected_revision=c.expected_revision,
                    line=c.derived_line,
                    quote=c.quote,
                )
                for e in entries
                for c in e.observation.sources
            }
            refs.update(citations)
            provenance.append(
                Provenance(
                    key=key,
                    observations=tuple(entries),
                    selected_id=selection.observation_id,
                    actor_id=authority.actor_id,
                    reason=selection.reason,
                    maturity="accepted_requirement"
                    if selected and selected.verification.accepted_requirement
                    else "candidate",
                )
            )
            if selected is None:
                unknowns.append(f"{key}：未裁决，保留并列证据；{selection.reason}")
                spec_entry = next((e for e in entries if e.observation.spec), None)
                if spec_entry:
                    specs.append(
                        DefinitionSpec(
                            key=key,
                            parameter=spec_entry.observation.spec.parameter,
                            value_type=spec_entry.observation.spec.value_type,
                            availability="conflicted" if key in conflicting else "unknown",
                            reason=selection.reason,
                            sources=list(citations.values()),
                        )
                    )
                continue
            observation, verdict = selected.observation, selected.verification
            if verdict.status == "pending":
                unknowns.append(f"{key}：人工候选/待原值核对；{verdict.reason}")
            if observation.spec:
                value = observation.spec
                gaps = spec_unknowns(value)
                unknowns.extend(f"{key}：缺少 {field}" for field in gaps)
                sufficient = verdict.status == "verified" and not (
                    set(gaps) & {"value", "lower", "upper", "text", "unit"}
                )
                data = value.model_dump(exclude={"applicability"})
                if not sufficient:
                    data.update(value=None, lower=None, upper=None, text=None, tolerance=None)
                if verdict.status != "verified":
                    data.update(
                        unit=None, method=None, test_conditions=[], acceptance_criterion=None
                    )
                specs.append(
                    DefinitionSpec(
                        key=key,
                        **data,
                        availability="known" if sufficient else "unknown",
                        nature="observed"
                        if observation.origin == "human_observation"
                        else "extracted",
                        state="needs_confirmation",
                        owner_id=authority.actor_id,
                        reason=selection.reason,
                        sources=list(citations.values()),
                    )
                )
                if value.applicability and verdict.status == "verified":
                    constraints.append(f"{key} 适用范围：{value.applicability}")
            elif verdict.status == "verified" and observation.kind in {"requirement", "constraint"}:
                target = requirements if observation.kind == "requirement" else constraints
                target.append(observation.statement)
            else:
                unknowns.append(f"{key}：{observation.statement}")
        if not refs or len(refs) > 20:
            raise DomainError(
                "SOURCE_MAPPING_LIMIT", "现有定义接口须有1至20条引用；请拆分来源包。", 422
            )
        payload = DefinitionDraftPayload(
            title=request.title,
            purpose=authority.purpose,
            visibility=authority.audience,
            use_cases=list(research.use_cases),
            requirements=list(dict.fromkeys(requirements)),
            constraints=list(dict.fromkeys(constraints)),
            unknowns=list(dict.fromkeys(unknowns)),
            sources=sorted(refs.values(), key=digest),
            specs=specs,
            parent_definition_id=request.parent_definition_id,
            expected_parent_revision=request.expected_parent_revision,
            change_reason=request.change_reason,
        )
        value = dict(
            research_id=research.id,
            research_revision=research.revision,
            product_id=authority.product_id,
            expected_product_revision=authority.product_revision,
            payload=payload,
            provenance=tuple(provenance),
            conflicts=all_conflicts,
            missing_categories=missing,
            omitted_keys=omitted,
        )
        # Include non-selected raw observations: preview is the whole atomic group.
        binding = {
            "research": research.model_dump(mode="json"),
            "authority": authority.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
        }
        # DTO roundtrip makes tuples/UUID/Decimals a stable JSON representation.
        candidate = DefinitionCandidate(**value, digest="pending")
        binding["candidate"] = candidate.model_dump(mode="json", exclude={"digest"})
        return changed(candidate, digest=digest(binding))

    def handoff(
        self,
        authority: Authority,
        research_id: UUID,
        expected_revision: int,
        request: CandidateRequest,
        fixed_digest: str,
    ):
        """Host-only: its existing command gate authorizes and consumes exactly once.

        DefinitionPort.draft MUST be inside that gate's transaction, including replay
        and actor/run/parent/product/source locks. This function is not an API route.
        """
        candidate = self.preview(authority, research_id, expected_revision, request)
        if candidate.digest != fixed_digest:
            raise DomainError(
                "PREVIEW_CHANGED", "候选、权限、来源原值核验或产品已变化，请核对差异。"
            )
        return self._port("definitions").draft(authority, candidate)
