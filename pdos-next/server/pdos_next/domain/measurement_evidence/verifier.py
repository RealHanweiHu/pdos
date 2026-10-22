"""Verify source fields against immutable UTF-8 JSONL; caller owns source authorization."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from pdos_next.domain.verification_launch.schemas import ExecutionPlan
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import Coverage, Measurement, SourceRef, TestRun

from .schemas import (
    FORMAT_VERSION,
    VERIFIER_VERSION,
    FieldLocation,
    ObservationCandidate,
    ObservationCandidates,
    ObservationLine,
    ObservationSelection,
    ReportBinding,
    VerifiedObservation,
)

POSITION = re.compile(r"line:([1-9][0-9]*);quote_sha256:([0-9a-f]{64})\Z")
# These literal separators would disagree with the existing source splitlines
# locator. Escaped JSON strings (e.g. "\\u2028") are preserved and supported.
UNSUPPORTED_BREAKS = "\v\f\x1c\x1d\x1e\x85\u2028\u2029"
REQUIRED_METADATA = (
    "raw_value",
    "unit",
    "conditions",
    "equipment",
    "environment",
    "method",
    "calibration",
    "executor_id",
    "observed_at",
    "observed_timezone",
)


@dataclass(frozen=True, slots=True)
class VerifierLimits:
    max_input_bytes: int = 2_000_000
    max_line_bytes: int = 32768
    max_depth: int = 6

    def __post_init__(self):
        for name, ceiling in (
            ("max_input_bytes", 10_000_000),
            ("max_line_bytes", 131072),
            ("max_depth", 8),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(f"{name} must be a bounded positive integer")


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def fixed_run_sha256(run: TestRun, execution_plan: ExecutionPlan | None = None) -> str:
    """Stable immutable execution basis; append-only results do not change identity."""
    fields = (
        "id",
        "scope",
        "request_id",
        "request_revision",
        "build",
        "items",
        "samples",
        "coverage",
        "execution",
        "actual_start",
    )
    value = run.model_dump(mode="json", include=set(fields))
    value["execution_plan"] = (
        execution_plan.model_dump(mode="json") if execution_plan is not None else None
    )
    return _digest(value)


def _failure(code, message, status=422):
    raise DomainError(code, message, status)


def _constant(_):
    _failure("INVALID_REPORT_FORMAT", "JSON不允许NaN或Infinity非有限字面值。")


def _object_pairs(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            _failure("DUPLICATE_REPORT_KEY", "原报告JSON存在重复字段，无法唯一核对。")
        output[key] = value
    return output


DECODER = json.JSONDecoder(object_pairs_hook=_object_pairs, parse_constant=_constant)


def _check_depth(line, maximum):
    depth, quoted, escaped = 0, False, False
    for char in line:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > maximum:
                _failure("REPORT_STRUCTURE_LIMIT", "原报告嵌套结构超过有界核验范围。", 413)
        elif char in "]}":
            depth -= 1


def _unicode(value):
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            _failure("INVALID_REPORT_ENCODING", "原报告字段含不合法Unicode代理字符。")
    elif isinstance(value, dict):
        for key, item in value.items():
            _unicode(key)
            _unicode(item)
    elif isinstance(value, list):
        for item in value:
            _unicode(item)


def _ws(text, index):
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _locations(text, line_number, byte_offset):
    """Record exact token spans after strict duplicate-key and syntax validation."""
    found = []

    def visit(index, path):
        index = _ws(text, index)
        start = index
        value, finish = DECODER.raw_decode(text, index)
        if path:
            found.append(
                FieldLocation(
                    line=line_number,
                    field=path,
                    presence="null" if value is None else "value",
                    raw_token=text[start:finish],
                    character_start=start,
                    character_end=finish,
                    byte_start=byte_offset + len(text[:start].encode("utf-8")),
                    byte_end=byte_offset + len(text[:finish].encode("utf-8")),
                )
            )
        if isinstance(value, dict):
            cursor = _ws(text, start + 1)
            for _ in value:
                key, key_end = DECODER.raw_decode(text, cursor)
                value_start = _ws(text, key_end)
                if text[value_start] != ":":
                    _failure("INVALID_REPORT_FORMAT", "字段位置不能唯一定位。")
                cursor = visit(value_start + 1, f"{path}.{key}" if path else key)
                cursor = _ws(text, cursor)
                if text[cursor] == ",":
                    cursor = _ws(text, cursor + 1)
        return finish

    visit(0, "")
    located = {location.field for location in found}
    found.extend(
        FieldLocation(line=line_number, field=name, presence="missing")
        for name in ObservationLine.model_fields
        if name not in located
    )
    return tuple(sorted(found, key=lambda loc: loc.field))


def _strict_fields(raw):
    if type(raw) is not dict:
        _failure("INVALID_REPORT_FORMAT", "每行须为一个明确测量JSON对象。")
    if type(raw.get("sample_revision")) is not int:
        _failure("INVALID_REPORT_FIELD", "样件版本须为明确整数，不能转换布尔或小数。")
    config = raw.get("actual_configuration")
    if type(config) is not dict or type(config.get("revision")) is not int:
        _failure("INVALID_REPORT_FIELD", "实际配置须明确身份和整数版本。")
    for name in ("equipment", "method", "calibration"):
        value = raw.get(name)
        if value is None:
            continue
        if (
            type(value) is not dict
            or set(value) != {"id", "revision", "kind", "position"}
            or type(value.get("revision")) is not int
            or type(value.get("position")) is not str
            or value["position"] != value["position"].strip()
        ):
            _failure(
                "INVALID_REPORT_FIELD", "实测引用须有完整原身份/版本/种类/位置，不能补写或裁剪。"
            )


def _source_for_definition(ref):
    return SourceRef(
        id=ref.artifact_id,
        revision=ref.expected_revision,
        kind="artifact",
        position=f"line:{ref.line};quote_sha256:{hashlib.sha256(ref.quote.encode()).hexdigest()}",
    )


def _candidate(value, raw, text, number, byte_offset, binding, sample):
    missing = []
    for name in REQUIRED_METADATA:
        if name not in raw:
            missing.append(f"SOURCE_FIELD_MISSING:{name}")
        elif raw[name] is None:
            missing.append(f"SOURCE_FIELD_NULL:{name}")
    state = "unknown"
    if value.raw_value is not None:
        if value.raw_value.strip():
            try:
                number_value = Decimal(value.raw_value)
            except InvalidOperation:
                state = "non_numeric"
                missing.append("NON_NUMERIC_READING")
            else:
                state = "known" if number_value.is_finite() else "non_finite"
                if state == "non_finite":
                    missing.append("NON_FINITE_READING")
        else:
            missing.append("SOURCE_VALUE_BLANK:raw_value")
    mismatches = []
    plan = binding.execution_plan
    if plan is None:
        missing.append("EXECUTION_PLAN_UNBOUND")
    else:
        expected = {
            "equipment": _source_for_definition(plan.equipment),
            "calibration": _source_for_definition(plan.calibration),
            "executor_id": plan.executor_id,
            "environment": plan.environment,
            "conditions": plan.conditions,
        }
        for name, expected_value in expected.items():
            actual = getattr(value, name)
            if actual is not None and actual != expected_value:
                mismatches.append(f"EXECUTION_METADATA_MISMATCH:{name}")
    row_digest = hashlib.sha256(text.encode()).hexdigest()
    return ObservationCandidate(
        coverage=Coverage(sample_id=value.sample_id, item_id=value.item_id),
        sample=sample,
        source=SourceRef(
            id=binding.report.id,
            revision=binding.report.revision,
            kind="artifact",
            position=f"line:{number};quote_sha256:{row_digest}",
        ),
        line=number,
        row_sha256=row_digest,
        raw_value=value.raw_value,
        unit=value.unit,
        conditions=value.conditions,
        equipment=value.equipment,
        equipment_label=value.equipment_label,
        calibration=value.calibration,
        environment=value.environment,
        method=value.method,
        executor_id=value.executor_id,
        observed_at=value.observed_at.astimezone(UTC) if value.observed_at else None,
        observed_timezone=value.observed_timezone,
        note=value.note,
        field_locations=_locations(text, number, byte_offset),
        missing=tuple(missing),
        metadata_mismatches=tuple(mismatches),
        value_state=state,
    )


def extract_observations(
    content: bytes,
    binding: ReportBinding,
    selections: tuple[ObservationSelection, ...] | None = None,
    *,
    limits: VerifierLimits | None = None,
) -> ObservationCandidates:
    """Extract only real rows. None selects all; an empty tuple selects none.

    Caller supplies currently-authorized immutable original bytes. This pure
    function cannot inspect ACL, scanner status, current epochs or qualification.
    """
    limits = limits or VerifierLimits()
    if not isinstance(content, bytes):
        _failure("INVALID_REPORT_ENCODING", "核验输入必须是受控读取的原件bytes。")
    if len(content) > limits.max_input_bytes:
        _failure("REPORT_SIZE_LIMIT", "原报告超过有界核验大小。", 413)
    if len(content) != binding.original.size or hashlib.sha256(content).hexdigest() != (
        binding.original.sha256
    ):
        _failure("REPORT_HASH_MISMATCH", "原件完整字节与服务器固定身份不一致。", 409)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _failure("INVALID_REPORT_ENCODING", "本版仅支持严格UTF-8原生JSONL。")
    if text.startswith("\ufeff") or any(char in text for char in UNSUPPORTED_BREAKS):
        _failure("UNSUPPORTED_REPORT_LINE_BREAK", "原报告含不能与现有行定位一致的分隔符或BOM。")
    # LF and CRLF are supported without rewriting original content or offsets.
    physical_lines = text.splitlines(keepends=True)
    allowed = {(pair.sample.id, pair.item_id): pair.sample for pair in binding.pairs}
    rows, seen = {}, set()
    byte_offset = 0
    for line_number, original_line in enumerate(physical_lines, 1):
        line = original_line.removesuffix("\n").removesuffix("\r")
        if "\r" in line or (original_line.endswith("\r") and not original_line.endswith("\r\n")):
            _failure("UNSUPPORTED_REPORT_LINE_BREAK", "本版原行分隔仅支持LF或CRLF。")
        if len(line.encode()) > limits.max_line_bytes:
            _failure("REPORT_LINE_LIMIT", "单行原报告超过有界核验范围。", 413)
        if not line.strip():
            _failure("INVALID_REPORT_FORMAT", "空行不是观测，不能用空行补齐覆盖。")
        _check_depth(line, limits.max_depth)
        try:
            raw = json.loads(line, object_pairs_hook=_object_pairs, parse_constant=_constant)
        except (json.JSONDecodeError, ValueError, RecursionError, OverflowError):
            _failure("INVALID_REPORT_FORMAT", "原报告行不是完整且有界的JSON对象。")
        _unicode(raw)
        _strict_fields(raw)
        try:
            value = ObservationLine.model_validate(raw)
        except ValidationError as exc:
            fields = {error["loc"][0] for error in exc.errors() if error["loc"]}
            code = (
                "INVALID_REPORT_TIME"
                if fields & {"observed_at", "observed_timezone"}
                or any(not error["loc"] for error in exc.errors())
                else "INVALID_REPORT_FIELD"
            )
            _failure(code, "原报告含未知字段、无效时间或不符合原值格式的字段。")
        key = (value.sample_id, value.item_id)
        sample = allowed.get(key)
        if value.run_id != binding.run_id or sample is None:
            _failure("INVALID_MEASUREMENT_SCOPE", "原报告行不属于固定Run已接收的样件/测试项。")
        if (
            value.sample_revision != sample.revision
            or value.actual_configuration != sample.actual_configuration
            or value.cavity != sample.cavity
        ):
            _failure("REPORT_SAMPLE_MISMATCH", "原报告样件版本、实际配置或模穴与固定对象不一致。")
        if key in seen:
            _failure("AMBIGUOUS_REPORT_ROW", "同一Run样件/测试项有多条原值，不能静默取一条。")
        seen.add(key)
        rows[line_number] = _candidate(value, raw, line, line_number, byte_offset, binding, sample)
        byte_offset += len(original_line.encode())
    selected = []
    if selections is None:
        selected = list(rows.values())
    else:
        selected_pairs, selected_lines = set(), set()
        for selection in selections:
            key = (selection.sample_id, selection.item_id)
            candidate = rows.get(selection.line)
            if (
                candidate is None
                or (candidate.coverage.sample_id, candidate.coverage.item_id) != key
            ):
                _failure(
                    "REPORT_SELECTION_MISMATCH", "选择位置没有该样件/测试项原观测，不能补造null。"
                )
            if key in selected_pairs or selection.line in selected_lines:
                _failure("AMBIGUOUS_REPORT_SELECTION", "选中的原行或样件/测试项不能重复。")
            selected_pairs.add(key)
            selected_lines.add(selection.line)
            selected.append(candidate)
    selected.sort(key=lambda candidate: candidate.line)
    represented = {(value.coverage.sample_id, value.coverage.item_id) for value in selected}
    missing_pairs = tuple(
        Coverage(sample_id=pair.sample.id, item_id=pair.item_id)
        for pair in binding.pairs
        if (pair.sample.id, pair.item_id) not in represented
    )
    return ObservationCandidates(
        binding=binding, observations=tuple(selected), missing_pairs=missing_pairs
    )


def _run_guard(binding, run):
    if (
        run.scope != binding.scope
        or run.id != binding.run_id
        or run.request_id != binding.request_id
        or run.request_revision != binding.request_revision
        or run.revision < binding.run_revision
        or fixed_run_sha256(run, binding.execution_plan) != binding.run_basis_sha256
    ):
        _failure("REPORT_BINDING_MISMATCH", "Run固定范围或实际执行基底与原报告绑定不一致。", 409)
    current_pairs = {(c.sample_id, c.item_id) for c in run.coverage}
    bound_pairs = {(pair.sample.id, pair.item_id) for pair in binding.pairs}
    samples = {sample.id: sample for sample in run.samples}
    if bound_pairs != current_pairs or any(
        samples.get(pair.sample.id) != pair.sample for pair in binding.pairs
    ):
        _failure("REPORT_BINDING_MISMATCH", "报告映射须为真实Run完整固定样件/测试项范围。", 409)
    if run.actual_start is None or run.execution is None:
        _failure("INTEGRATION_REQUIRED", "没有真实Run开始和执行条件，不能核验实测报告。", 503)
    plan = binding.execution_plan
    if plan is not None and (
        run.execution.equipment != _source_for_definition(plan.equipment)
        or run.execution.calibration != _source_for_definition(plan.calibration)
        or run.execution.executor_id != plan.executor_id
        or run.execution.environment != plan.environment
        or run.execution.conditions != plan.conditions
    ):
        _failure("REPORT_BINDING_MISMATCH", "固定计划与Run真实执行条件不一致。", 409)


def verify_measurement(
    content: bytes,
    binding: ReportBinding,
    measurement: Measurement,
    run: TestRun,
    *,
    limits: VerifierLimits | None = None,
) -> VerifiedObservation:
    """Re-read source values and exact location; never infer qualification or values.

    Measurement identity is assigned/persisted by the caller. The verifier binds
    its coverage and every data field, and never authorizes replacing a pair.
    """
    _run_guard(binding, run)
    source = measurement.source
    position = POSITION.fullmatch(source.position) if source is not None else None
    if (
        source is None
        or position is None
        or source.kind != "artifact"
        or source.id != binding.report.id
        or source.revision != binding.report.revision
    ):
        _failure("MEASUREMENT_SOURCE_MISMATCH", "测量须引用本份原报告的精确原行。")
    selection = ObservationSelection(
        line=int(position[1]),
        sample_id=measurement.coverage.sample_id,
        item_id=measurement.coverage.item_id,
    )
    observation = extract_observations(content, binding, (selection,), limits=limits).observations[
        0
    ]
    expected = observation.to_measurement(measurement.id)
    if measurement.model_dump(mode="json") != expected.model_dump(mode="json"):
        _failure(
            "MEASUREMENT_SOURCE_MISMATCH", "测量原值、元数据、缺项或位置与原报告逐字段不一致。"
        )
    if observation.observed_at is not None:
        if observation.observed_at < run.actual_start.occurred_at:
            _failure("INVALID_REPORT_TIME", "原观测时间不能早于真实Run开始。")
        if run.actual_end and observation.observed_at > run.actual_end.occurred_at:
            _failure("INVALID_REPORT_TIME", "原观测时间不能晚于真实Run结束。")
    # The fixed plan is authoritative expected metadata, never a source value.
    # A mismatch remains a measurement with explicit gaps, not a positive result.
    proof = {
        "binding": binding.model_dump(mode="json"),
        "observation": observation.model_dump(mode="json"),
        "measurement": measurement.model_dump(mode="json"),
        "verifier_version": VERIFIER_VERSION,
        "format": FORMAT_VERSION,
    }
    return VerifiedObservation(
        observation=observation,
        measurement=measurement,
        report_sha256=binding.original.sha256,
        proof_sha256=_digest(proof),
    )
