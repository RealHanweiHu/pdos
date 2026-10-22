"""Explicit synthetic inputs only; no DB, env, network or repository fixtures."""

import hashlib
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.discovery import Discovery, Ports
from pdos_next.domain.discovery.handlers import changed
from pdos_next.domain.discovery.ports import Authority
from pdos_next.domain.discovery.rules import conflicts
from pdos_next.domain.discovery.sources import LineMap, PinnedSources, SourceSnapshot
from pdos_next.errors import DomainError
from pdos_next.schemas.discovery.contracts import (
    CandidateRequest,
    Citation,
    ImportBatch,
    Location,
    Observation,
    PackageItem,
    ResearchStart,
    Selection,
    SpecValue,
    Verification,
)


class MemoryResearch:
    def __init__(self):
        self.rows = {}
        self.mutations = []

    def locked(self, authority, research_id):
        return self.rows[research_id]

    def record(self, authority, mutation):
        old = self.rows.get(mutation.research.id)
        assert (old.revision if old else 0) == mutation.before_revision
        assert not (old and mutation.before_revision == 0)
        self.rows[mutation.research.id] = mutation.research
        self.mutations.append(mutation)
        return mutation.research


class Reader:
    def __init__(self):
        self.rows = {}

    def read(self, authority, citation):
        return self.rows[citation.artifact_id]


class Owner:
    def __init__(self):
        self.candidates = []

    def draft(self, authority, candidate):
        self.candidates.append(candidate)
        return candidate


def setup(mode="oem", required=()):
    authority = Authority(
        tenant_id=uuid4(),
        actor_id=uuid4(),
        actor_kind="human",
        scope_id=uuid4(),
        product_id=uuid4(),
        product_revision=2,
        purpose="客户产品真实用途",
        audience="private",
        authorized=True,
        required_categories=required,
    )
    memory, reader, owner = MemoryResearch(), Reader(), Owner()
    sources = PinnedSources(reader)
    service = Discovery(Ports(research=memory, sources=sources, definitions=owner))
    research = service.start(
        authority,
        uuid4(),
        ResearchStart(
            title="客户设计包", mode=mode, questions=("核对制造输入",), use_cases=("指定设备使用",)
        ),
    )
    return authority, memory, reader, owner, service, research


def sample(
    reader,
    authority,
    *,
    key="speed",
    value="1200",
    unit="rpm",
    category="specification",
    conditions=("25°C",),
    method="方法A",
    applicability="客户设备A",
    kind="spec",
    statement="目标转速",
    origin="customer_input",
    structured=True,
):
    spec = (
        SpecValue(
            parameter="转速",
            value_type="number",
            value=value,
            unit=unit,
            tolerance="5",
            test_conditions=conditions,
            method=method,
            applicability=applicability,
            acceptance_criterion="允差内",
        )
        if kind == "spec"
        else None
    )
    raw = {
        "key": key,
        "kind": kind,
        "statement": statement,
        "spec": spec.model_dump(mode="json") if spec else None,
    }
    text = json.dumps(raw, ensure_ascii=False) if structured else "客户原文：转速1200 rpm"
    artifact_id = uuid4()
    citation = Citation(
        artifact_id=artifact_id,
        expected_revision=1,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        derived_line=1,
        quote=text,
        location=Location(kind="line", line=1),
    )
    reader.rows[artifact_id] = SourceSnapshot(
        artifact_id=artifact_id,
        tenant_id=authority.tenant_id,
        revision=1,
        active=True,
        readable=True,
        visibility="private",
        allowed_scope_ids=(authority.scope_id,),
        allowed_product_ids=(authority.product_id,),
        content=text,
        content_hash=citation.content_hash,
    )
    observation = Observation(
        id=uuid4(),
        key=key,
        kind=kind,
        origin=origin,
        raw_text=text,
        statement=statement,
        spec=spec,
        sources=(citation,),
    )
    return PackageItem(category=category, source=citation), observation


def imported(mode="oem", **options):
    env = setup(mode=mode)
    authority, memory, reader, owner, service, research = env
    item, observation = sample(reader, authority, **options)
    research = service.ingest(
        authority, research.id, 1, ImportBatch(items=(item,), observations=(observation,))
    )
    return (*env[:-1], research, item, observation)


def request(observation, **changes):
    return CandidateRequest(
        title="内部导入定义",
        selections=(
            Selection(
                key=observation.key, observation_id=observation.id, reason="具名选择此来源条件"
            ),
        ),
        change_reason="导入客户设计包",
        **changes,
    )


def error(code, callback):
    with pytest.raises(DomainError) as caught:
        callback()
    assert caught.value.reason == code


def test_research_needs_no_product_project_or_placeholder():
    authority, memory, reader, owner, service, research = setup(mode="research")
    unbound = changed(authority, product_id=None, product_revision=None)
    second = service.start(
        unbound,
        uuid4(),
        ResearchStart(
            title="独立研究", mode="research", questions=("需求是什么",), use_cases=("研究使用",)
        ),
    )
    assert second.scope_id == authority.scope_id
    assert "project" not in second.model_dump_json()
    assert len(memory.rows) == 2 and owner.candidates == []
    item, observation = sample(reader, authority)
    second = service.ingest(
        unbound, second.id, 1, ImportBatch(items=(item,), observations=(observation,))
    )
    error(
        "PRODUCT_BINDING_REQUIRED",
        lambda: service.preview(unbound, second.id, second.revision, request(observation)),
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ({"scope_id": None}, "SCOPE_BINDING_REQUIRED"),
        ({"purpose": " "}, "SCOPE_BINDING_REQUIRED"),
        ({"authorized": False}, "FORBIDDEN_SCOPE"),
        ({"cancelled": True}, "FORBIDDEN_SCOPE"),
        ({"actor_kind": "ai"}, "CAPABILITY_DISABLED"),
    ],
)
def test_scope_and_ai_guards(change, code):
    authority, memory, reader, owner, service, research = setup()
    error(
        code,
        lambda: service.start(
            changed(authority, **change),
            uuid4(),
            ResearchStart(
                title="研究输入", mode="research", questions=("问题",), use_cases=("场景",)
            ),
        ),
    )
    assert len(memory.rows) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"scope_id": uuid4()},
        {"tenant_id": uuid4()},
        {"actor_id": uuid4()},
        {"audience": "category"},
    ],
)
def test_research_scope_and_private_owner_never_widen(change):
    authority, memory, reader, owner, service, research = setup()
    error("FORBIDDEN_SCOPE", lambda: service.inspect(changed(authority, **change), research.id))


def test_oem_maps_definition_without_market_strategy_and_preserves_raw_value():
    authority, memory, reader, owner, service, research, item, observation = imported(
        value="1200.00"
    )
    candidate = service.preview(authority, research.id, 2, request(observation))
    assert candidate.payload.purpose == authority.purpose
    spec = candidate.payload.specs[0]
    assert spec.value == Decimal("1200.00") and spec.unit == "rpm"
    assert spec.state == "needs_confirmation"
    assert candidate.provenance[0].maturity == "candidate"
    assert candidate.provenance[0].observations[0].observation.raw_text == item.source.quote
    assert "市场" not in candidate.payload.model_dump_json()
    assert owner.candidates == []
    assert (
        service.handoff(authority, research.id, 2, request(observation), candidate.digest)
        == candidate
    )
    assert len(owner.candidates) == 1


def test_duplicate_import_semantics_survive_new_observation_identity():
    authority, memory, reader, owner, service, research, item, observation = imported()
    repeated = changed(observation, id=uuid4())
    research = service.ingest(
        authority, research.id, 2, ImportBatch(items=(item,), observations=(repeated,))
    )
    assert research.revision == 2 and len(research.observations) == 1
    assert memory.mutations[-1].replayed_content


def test_same_id_different_payload_rejected_without_partial_record():
    authority, memory, reader, owner, service, research, item, observation = imported()
    batch = ImportBatch(items=(item,), observations=(changed(observation, statement="不同声明"),))
    error("IDEMPOTENCY_CONFLICT", lambda: service.ingest(authority, research.id, 2, batch))
    assert memory.rows[research.id] == research


def test_new_source_is_never_adopted_by_id_only():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority)
    other, ignored = sample(reader, authority)
    error(
        "MISSING_REQUIRED_EVIDENCE",
        lambda: service.ingest(
            authority, research.id, 1, ImportBatch(items=(other,), observations=(observation,))
        ),
    )
    assert memory.rows[research.id].items == ()


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("value", "1500", "value"),
        ("unit", "Hz", "unit"),
        ("method", "方法B", "method"),
        ("conditions", ("40°C",), "test_conditions"),
        ("applicability", "客户设备B", "applicability"),
        ("statement", "不同指标口径", "statement"),
    ],
)
def test_conflicts_keep_competing_evidence_no_latest_wins(field, value, reason):
    authority, memory, reader, owner, service, research, item, observation = imported()
    other_item, other = sample(reader, authority, **{field: value})
    research = service.ingest(
        authority, research.id, 2, ImportBatch(items=(other_item,), observations=(other,))
    )
    assert reason in conflicts(research)[0].reasons
    unresolved = CandidateRequest(
        title="内部导入定义",
        selections=(Selection(key="speed", reason="尚未核对两种口径"),),
        change_reason="保留冲突",
    )
    candidate = service.preview(authority, research.id, 3, unresolved)
    assert candidate.payload.specs[0].availability == "conflicted"
    assert candidate.payload.specs[0].value is None
    assert len(candidate.provenance[0].observations) == 2
    candidate = service.preview(authority, research.id, 3, request(other))
    assert candidate.provenance[0].actor_id == authority.actor_id
    assert len(candidate.payload.specs[0].sources) == 2
    assert len(candidate.conflicts) == 1
    assert candidate.payload.specs[0].state == "needs_confirmation"


@pytest.mark.parametrize(
    "options,gap",
    [
        ({"unit": None}, "unit"),
        ({"value": None}, "value"),
        ({"conditions": ()}, "test_conditions"),
        ({"method": None}, "method"),
        ({"applicability": None}, "applicability"),
    ],
)
def test_unknown_fields_visible_without_zero_or_customer_approval(options, gap):
    authority, memory, reader, owner, service, research, item, observation = imported(**options)
    candidate = service.preview(authority, research.id, 2, request(observation))
    assert any(gap in text for text in candidate.payload.unknowns)
    if gap in {"unit", "value"}:
        assert candidate.payload.specs[0].availability == "unknown"
        assert candidate.payload.specs[0].value is None
    assert candidate.provenance[0].maturity == "candidate"


@pytest.mark.parametrize("origin", ["human_observation", "ai_extraction", "translation"])
def test_prose_and_translation_never_imply_verified_facts(origin):
    authority, memory, reader, owner, service, research, item, observation = imported(
        structured=False, origin=origin
    )
    candidate = service.preview(authority, research.id, 2, request(observation))
    spec = candidate.payload.specs[0]
    assert spec.availability == "unknown" and spec.value is None
    assert not spec.unit and not spec.test_conditions and not spec.method
    assert candidate.payload.constraints == []
    assert candidate.provenance[0].observations[0].observation.spec.value == Decimal("1200")
    assert candidate.provenance[0].observations[0].verification.status == "pending"


def test_hash_and_valid_quote_do_not_prove_invented_value():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority)
    invented = changed(observation, spec=changed(observation.spec, value="9000"))
    research = service.ingest(
        authority, research.id, 1, ImportBatch(items=(item,), observations=(invented,))
    )
    candidate = service.preview(authority, research.id, 2, request(invented))
    assert candidate.payload.specs[0].availability == "unknown"
    assert candidate.provenance[0].observations[0].verification.status == "pending"


def test_partial_import_keeps_omitted_and_missing_with_explicit_reason():
    authority, memory, reader, owner, service, research = setup(
        required=("drawing", "specification")
    )
    item, observation = sample(reader, authority)
    other_item, other = sample(reader, authority, key="power")
    research = service.ingest(
        authority,
        research.id,
        1,
        ImportBatch(items=(item, other_item), observations=(observation, other)),
    )
    error(
        "PARTIAL_REASON_REQUIRED",
        lambda: service.preview(authority, research.id, 2, request(observation)),
    )
    candidate = service.preview(
        authority, research.id, 2, request(observation, partial_reason="本轮只导入转速；图纸待补")
    )
    assert candidate.missing_categories == ("drawing",) and candidate.omitted_keys == ("power",)
    assert len(candidate.payload.sources) == 2
    assert any("power" in u for u in candidate.payload.unknowns)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"active": False}, "SOURCE_UNAVAILABLE"),
        ({"readable": False}, "FORBIDDEN_SCOPE"),
        ({"revision": 2}, "SOURCE_STALE"),
        ({"allowed_product_ids": ()}, "FORBIDDEN_SCOPE"),
        ({"content": "被改动"}, "INTEGRITY_MISMATCH"),
        ({"tenant_id": uuid4()}, "FORBIDDEN_SCOPE"),
    ],
)
def test_current_sources_rechecked_on_inspect_preview_and_handoff(changes, code):
    authority, memory, reader, owner, service, research, item, observation = imported()
    candidate = service.preview(authority, research.id, 2, request(observation))
    reader.rows[item.source.artifact_id] = changed(reader.rows[item.source.artifact_id], **changes)
    for callback in [
        lambda: service.inspect(authority, research.id),
        lambda: service.preview(authority, research.id, 2, request(observation)),
        lambda: service.handoff(authority, research.id, 2, request(observation), candidate.digest),
    ]:
        error(code, callback)
    assert owner.candidates == []


@pytest.mark.parametrize("change", ["product_version", "selection_reason", "verdict", "policy"])
def test_preview_change_prevents_owner_write(change):
    authority, memory, reader, owner, service, research, item, observation = imported()
    req = request(observation)
    candidate = service.preview(authority, research.id, 2, req)
    if change == "product_version":
        authority = changed(authority, product_revision=3)
    elif change == "selection_reason":
        req = changed(req, selections=(changed(req.selections[0], reason="另一裁决理由"),))
    elif change == "policy":
        authority = changed(authority, required_categories=("drawing",))
        req = changed(req, partial_reason="新增规则缺项待补")
    else:
        service.ports.sources.verify = lambda a, o: Verification(
            status="pending", reason="核验已失效"
        )
    error(
        "PREVIEW_CHANGED", lambda: service.handoff(authority, research.id, 2, req, candidate.digest)
    )
    assert owner.candidates == []


def test_aggregate_version_change_is_not_hidden_by_preview_hash():
    authority, memory, reader, owner, service, research, item, observation = imported()
    candidate = service.preview(authority, research.id, 2, request(observation))
    new_item, new = sample(reader, authority, key="new")
    service.ingest(authority, research.id, 2, ImportBatch(items=(new_item,), observations=(new,)))
    error(
        "VERSION_CONFLICT",
        lambda: service.handoff(authority, research.id, 2, request(observation), candidate.digest),
    )


def test_requirement_uuid_never_grants_accepted_maturity():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority, kind="requirement", statement="客户要求防水")
    observation = changed(observation, accepted_requirement_id=uuid4())
    research = service.ingest(
        authority, research.id, 1, ImportBatch(items=(item,), observations=(observation,))
    )
    candidate = service.preview(authority, research.id, 2, request(observation))
    assert candidate.payload.requirements == ["客户要求防水"]
    assert candidate.provenance[0].maturity == "candidate"
    service.ports.sources.verify = lambda a, o: Verification(
        status="verified", reason="主线核对当前已接受需求", accepted_requirement=True
    )
    candidate = service.preview(authority, research.id, 2, request(observation))
    assert candidate.provenance[0].maturity == "accepted_requirement"


def test_ports_unavailable_never_simulate_success():
    authority, memory, reader, owner, service, research, item, observation = imported()
    candidate = service.preview(authority, research.id, 2, request(observation))
    for name, callback in [
        ("research", lambda: service.inspect(authority, research.id)),
        ("sources", lambda: service.inspect(authority, research.id)),
        (
            "definitions",
            lambda: service.handoff(
                authority, research.id, 2, request(observation), candidate.digest
            ),
        ),
    ]:
        old = getattr(service.ports, name)
        setattr(service.ports, name, None)
        error("PORT_UNAVAILABLE", callback)
        setattr(service.ports, name, old)


def test_original_page_cell_mapping_and_version_are_current_not_claimed():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority)
    original_id = uuid4()
    citation = changed(
        item.source,
        original_id=original_id,
        original_version="immutable-v1",
        original_hash="a" * 64,
        location=Location(kind="cell", sheet="规格", cell="B4"),
    )
    row = changed(
        reader.rows[citation.artifact_id],
        original_id=original_id,
        original_version="immutable-v1",
        original_hash="a" * 64,
        original_usable=True,
        locator_map=(
            LineMap(derived_line_start=1, derived_line_end=1, location=citation.location),
        ),
    )
    reader.rows[citation.artifact_id] = row
    service.ports.sources.check(authority, citation)
    error(
        "INTEGRITY_MISMATCH",
        lambda: service.ports.sources.check(
            authority, changed(citation, location=Location(kind="cell", sheet="规格", cell="B5"))
        ),
    )
    error(
        "SOURCE_STALE",
        lambda: service.ports.sources.check(authority, changed(citation, original_version="v2")),
    )
    reader.rows[citation.artifact_id] = changed(row, original_usable=False)
    error("SOURCE_UNAVAILABLE", lambda: service.ports.sources.check(authority, citation))


@pytest.mark.parametrize(
    "extra", ["tenant_id", "product_id", "qualified", "confidence", "published"]
)
def test_payloads_forbid_identity_policy_and_maturity_injection(extra):
    with pytest.raises(ValidationError):
        ResearchStart.model_validate(
            dict(
                title="研究输入",
                mode="research",
                questions=["问题"],
                use_cases=["场景"],
                **{extra: "injected"},
            )
        )


@pytest.mark.parametrize(
    "data",
    [
        {"kind": "cell", "sheet": "表"},
        {"kind": "page", "page": 2, "line": 1},
        {"kind": "line", "line": 0},
        {"kind": "cell", "sheet": "表", "cell": "B0"},
    ],
)
def test_ambiguous_locator_rejected(data):
    with pytest.raises(ValidationError):
        Location.model_validate(data)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e26", "0.0000000000001"])
def test_invalid_decimal_rejected(value):
    with pytest.raises(ValidationError):
        SpecValue(parameter="参数", value_type="number", value=value)


def test_duplicate_json_raw_fields_never_use_latest_value_as_verified():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority)
    raw = item.source.quote.replace('"value": "1200"', '"value": "9000", "value": "1200"')
    citation = changed(
        item.source, quote=raw, content_hash=hashlib.sha256(raw.encode()).hexdigest()
    )
    reader.rows[citation.artifact_id] = changed(
        reader.rows[citation.artifact_id], content=raw, content_hash=citation.content_hash
    )
    observation = changed(observation, raw_text=raw, sources=(citation,))
    research = service.ingest(
        authority,
        research.id,
        1,
        ImportBatch(items=(changed(item, source=citation),), observations=(observation,)),
    )
    candidate = service.preview(authority, research.id, 2, request(observation))
    assert candidate.payload.specs[0].availability == "unknown"
    assert "9000" in candidate.provenance[0].observations[0].observation.raw_text


def test_payload_current_source_quote_substitution_and_ambiguous_mapping_rejected():
    authority, memory, reader, owner, service, research = setup()
    item, observation = sample(reader, authority)
    error(
        "INTEGRITY_MISMATCH",
        lambda: service.ports.sources.check(authority, changed(item.source, quote="不存在的原文")),
    )
    error(
        "INTEGRITY_MISMATCH",
        lambda: service.ports.sources.check(
            authority, changed(item.source, derived_line=2, location=Location(kind="line", line=2))
        ),
    )
    original_id = uuid4()
    citation = changed(
        item.source,
        original_id=original_id,
        original_version="v1",
        original_hash="a" * 64,
        location=Location(kind="page", page=1),
    )
    mapping = LineMap(derived_line_start=1, derived_line_end=1, location=citation.location)
    reader.rows[citation.artifact_id] = changed(
        reader.rows[citation.artifact_id],
        original_id=original_id,
        original_version="v1",
        original_hash="a" * 64,
        original_usable=True,
        locator_map=(mapping, mapping),
    )
    error("INTEGRITY_MISMATCH", lambda: service.ports.sources.check(authority, citation))


def test_source_package_mapping_limit_is_explicit_no_silent_truncation():
    authority, memory, reader, owner, service, research = setup()
    entries = [sample(reader, authority, key=f"spec_{i}") for i in range(21)]
    research = service.ingest(
        authority,
        research.id,
        1,
        ImportBatch(
            items=tuple(item for item, obs in entries[:20]),
            observations=tuple(obs for item, obs in entries[:20]),
        ),
    )
    research = service.ingest(
        authority,
        research.id,
        2,
        ImportBatch(items=(entries[20][0],), observations=(entries[20][1],)),
    )
    error(
        "SOURCE_MAPPING_LIMIT",
        lambda: service.preview(
            authority,
            research.id,
            3,
            request(entries[0][1], partial_reason="本轮只选一组，其余保留"),
        ),
    )


def test_unselected_groups_and_sources_still_rechecked_before_handoff():
    authority, memory, reader, owner, service, research, item, observation = imported()
    other_item, other = sample(reader, authority, key="unselected")
    service.ingest(
        authority, research.id, 2, ImportBatch(items=(other_item,), observations=(other,))
    )
    req = request(observation, partial_reason="只选转速候选")
    candidate = service.preview(authority, research.id, 3, req)
    reader.rows[other_item.source.artifact_id] = changed(
        reader.rows[other_item.source.artifact_id], readable=False
    )
    error(
        "FORBIDDEN_SCOPE", lambda: service.handoff(authority, research.id, 3, req, candidate.digest)
    )
    assert owner.candidates == []


def test_wrong_group_choice_is_rejected_not_silently_resolved():
    authority, memory, reader, owner, service, research, item, observation = imported()
    req = changed(
        request(observation),
        selections=(Selection(key="speed", observation_id=uuid4(), reason="错误组的选择"),),
    )
    error("INVALID_SELECTION", lambda: service.preview(authority, research.id, 2, req))


def test_definition_owner_failure_propagates_without_research_mutation():
    authority, memory, reader, owner, service, research, item, observation = imported()
    candidate = service.preview(authority, research.id, 2, request(observation))

    def fail(authority, candidate):
        raise DomainError("VERSION_CONFLICT", "定义所有者发现新的父定义")

    owner.draft = fail
    error(
        "VERSION_CONFLICT",
        lambda: service.handoff(authority, research.id, 2, request(observation), candidate.digest),
    )
    assert memory.rows[research.id] == research
