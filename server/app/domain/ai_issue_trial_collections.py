"""Complete registered Issue cohorts and descriptive checks, never execution grants."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import Connection, Engine, func, select, tuple_
from sqlalchemy.exc import DBAPIError

from app.auth.repository import AuthContext
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.ai_issue_observations import CaptureRequest, collect
from app.domain.ai_issue_trial_protocols import _authorize
from app.domain.ai_issue_trial_protocols import _read as read_protocol
from app.domain.ai_issue_trial_provenance import collect_provenance
from app.domain.ai_issue_trial_summary import IssueTrialItem, aggregate
from app.domain.ai_write_policy import WritePolicyError
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

VERSION = "event-issue-trial-collection-v1"
NOTICE = (
    "按原登记窗口完整留存全部运行；匹配版本与不匹配记录分列，未剔除失败或未办理。"
    "比例是截止本次采集的具名办理描述，不能替代独立质量评测、持续抽检或真实调用核验，"
    "也不授予自动写入资格。重新采集另留原件，不改变此前回执。"
)
FORMULA = {
    "version": "event-issue-registered-observation-formula-v1",
    "handled": "每次原运行自身创建/复用应用，或截止时点最新意见为不采纳，计一次",
    "confirmation": "确认分子按登记口径；分母为匹配原运行的办理数",
    "retained_original": "自身应用且未撤回/未人工修改；复用按采纳复用建议计，不断言原问题正文未变",
    "withdrawal": "成功撤回的自建问题数 / 本次匹配原运行自建问题数，跳过不计撤回",
    "same_source": "其他运行的同源应用单列，不计本次原运行确认",
    "sampling": "本采集全量读取；登记的持续抽检比例不代表已执行抽检",
}
TIME = TypeAdapter(AwareDatetime)


class CollectIssueTrial(Contract):
    request_id: UUID


def _stamp(value: Any) -> datetime:
    return TIME.validate_python(value)


def _followup(protocol: dict[str, Any], as_of: datetime) -> bool:
    elapsed = (as_of - _stamp(protocol["window_end"])) // timedelta(microseconds=1)
    return bool(elapsed >= protocol["configuration"]["minimum_followup_seconds"] * 1_000_000)


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def match_run(
    protocol: dict[str, Any], item: dict[str, Any], proof: dict[str, Any], as_of: datetime
) -> dict[str, Any]:
    """Compare original facts; do not fill missing evidence from current controls."""
    reasons = []
    generation = item.get("generation_binding") or {}
    if item.get("binding_kind") != "trial_candidate":
        reasons.append(
            _reason("generation_not_trial_candidate", "原生成未具备试运行条件或未留存生成依据")
        )
    expected_ids = (
        ("policy", "policy_id"),
        ("scope", "scope_revision_id"),
        ("principal", "principal_id"),
    )
    if any(
        (generation.get(key) or {}).get("id") != protocol[column] for key, column in expected_ids
    ):
        reasons.append(
            _reason("generation_control_mismatch", "原政策、项目授权或 AI 身份与登记版本不同")
        )
    if (
        any(
            generation.get(key) != item.get(other)
            for key, other in (
                ("run_id", "run_id"),
                ("source_digest", "source_digest"),
                ("event_row_id", "event_row_id"),
            )
        )
        or generation.get("project_id") != protocol["project_id"]
        or generation.get("tenant_id") != protocol["tenant_id"]
    ):
        reasons.append(
            _reason("generation_source_mismatch", "原生成依据与运行来源或登记范围不一致")
        )
    if proof.get("provenance_verified") is not True:
        reasons.append(
            _reason("runtime_chain_unverified", "原模型输入、结果或预算回执链尚未核验完整")
        )
    if proof.get("binding") != protocol["binding"]:
        reasons.append(
            _reason("runtime_binding_mismatch", "原模型、评测或运行版本与登记版本不同或无法核实")
        )
    created = _stamp(item["created_at"])
    publication = protocol["evaluation_publication"]
    if not _stamp(publication["valid_from"]) <= created < _stamp(publication["valid_until"]):
        reasons.append(_reason("evaluation_outside_validity", "原运行不在登记评测发布物的有效期内"))
    if protocol["evidence_kind"] == "real_business" and created < _stamp(protocol["created_at"]):
        reasons.append(
            _reason("run_precedes_registration", "真实业务运行早于原登记，不补记为预登记试运行")
        )
    return {
        "matches_protocol": not reasons,
        "reasons": reasons,
        "followup_complete": _followup(protocol, as_of),
    }


def _ratio(
    numerator: int, denominator: int, required: int, *, maximum: bool = False
) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "basis_points": numerator * 10000 // denominator if denominator else None,
        "required": required,
        "met": (
            (numerator * 10000 <= required * denominator)
            if maximum
            else (numerator * 10000 >= required * denominator)
        )
        if denominator
        else None,
    }


def summarize(
    protocol: dict[str, Any], items: list[dict[str, Any]], as_of: datetime
) -> dict[str, Any]:
    # Full source records remain in the immutable receipt even when none match.
    def totals(values: list[dict[str, Any]]) -> dict[str, Any]:
        return aggregate([{k: v[k] for k in IssueTrialItem.model_fields} for v in values])

    all_counts = totals(items)["counts"]
    matching = [v for v in items if v["match"]["matches_protocol"]]
    matched = totals(matching)
    cfg = protocol["configuration"]
    confirmed = sum(
        v["application_kind"] is not None
        and (
            cfg["confirmation_basis"] == "ever_confirmed"
            or not (v["human_edited"] or v["withdrawn"])
        )
        for v in matching
    )
    handled = matched["ratios"]["handled_proposals"]
    followup = _followup(protocol, as_of)
    criteria: dict[str, Any] = {
        "minimum_handled_runs": {
            "actual": handled,
            "required": cfg["minimum_handled_runs"],
            "met": handled >= cfg["minimum_handled_runs"],
        },
        "followup_complete": followup,
        "confirmation": _ratio(confirmed, handled, cfg["minimum_confirmation_basis_points"]),
        "withdrawal": _ratio(
            matched["counts"]["withdrawn_issues"],
            matched["counts"]["created_issues"],
            cfg["maximum_retraction_basis_points"],
            maximum=True,
        ),
    }
    blockers = [
        _reason(
            "provider_calls_unverified",
            "本持久回执链尚不能独立核验真实服务商调用，不能取得正式资格",
        ),
    ]
    if protocol["evidence_kind"] != "real_business":
        blockers.append(
            _reason("non_business_evidence", "本登记属于模拟或受控回放，不代表真实业务试运行")
        )
    if not items:
        blockers.append(_reason("empty_window", "原窗口没有运行，不输出通过率或资格"))
    if len(matching) != len(items):
        blockers.append(
            _reason("unmatched_runs", "部分原运行未匹配登记版本，原件与逐项原因已完整保留")
        )
    if not followup:
        blockers.append(_reason("followup_incomplete", "原窗口结束后的最短跟踪时长尚未满足"))
    if not criteria["minimum_handled_runs"]["met"]:
        blockers.append(
            _reason("insufficient_handled_runs", "匹配版本的具名办理数尚未达到登记要求")
        )
    if criteria["confirmation"]["met"] is not True:
        blockers.append(
            _reason("confirmation_not_met", "确认描述比例未达到门槛或没有可计算的办理分母")
        )
    if criteria["withdrawal"]["met"] is not True:
        blockers.append(_reason("withdrawal_not_met", "撤回描述比例未满足门槛或没有自建问题分母"))
    return {
        "total_runs": len(items),
        "matching_runs": len(matching),
        "counts": all_counts,
        "matching_counts": matched["counts"],
        "criteria": criteria,
        "blockers": blockers,
        "operational_requirements": [
            _reason(
                "runtime_sampling_required",
                "自动写入后须按登记口径持续抽检并在超限时暂停；既往抽检次数不是试运行资格前置。",
            )
        ],
        "formula": FORMULA,
        "selection_complete": True,
        "qualification_granted": False,
    }


def _read(
    c: Connection, tenant: UUID, project: UUID, protocol: UUID, identity: UUID
) -> dict[str, Any]:
    t = tables.ai_issue_trial_collections
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.protocol_id == protocol,
                t.c.id == identity,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("原试运行采集不存在或不在当前登记范围")
    if digest(row["collection"]) != row["collection_digest"]:
        raise WritePolicyError("COLLECTION_DIGEST_MISMATCH", "原采集回执校验不一致，请核对原件")
    return dict(row["collection"])


class IssueTrialCollections:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self, context: AuthContext, project: UUID, protocol: UUID, identity: UUID
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, context, project, write=False)
            read_protocol(c, context.tenant.id, project, protocol)
            return _read(c, context.tenant.id, project, protocol, identity)

    def history(
        self, context: AuthContext, project: UUID, protocol: UUID, before_id: UUID | None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project, write=False)
            read_protocol(c, context.tenant.id, project, protocol)
            try:
                _authorize(c, context, project, write=True)
                may_collect = True
            except PermissionError:
                may_collect = False
            t = tables.ai_issue_trial_collections
            query = select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.protocol_id == protocol,
            )
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise WritePolicyError("CURSOR_INVALID", "请从本登记的采集历史继续读取")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            return _plain(
                {
                    "items": [
                        {
                            k: r["collection"][k]
                            for k in (
                                "id",
                                "created_at",
                                "actor_name",
                                "as_of",
                                "total_runs",
                                "matching_runs",
                                "qualification_granted",
                            )
                        }
                        for r in rows[:20]
                    ],
                    "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
                    "can_collect": may_collect,
                }
            )

    def collect(
        self, context: AuthContext, project: UUID, protocol: UUID, body: CollectIssueTrial
    ) -> dict[str, Any]:
        for attempt in range(3):
            try:
                return self._collect_once(context, project, protocol, body)
            except DBAPIError as error:
                state = getattr(error.orig, "sqlstate", None)
                constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                if state != "40001" and not (
                    state == "23505" and constraint == "uq_ai_issue_trial_collection_request"
                ):
                    raise
                if attempt == 2:
                    raise WritePolicyError(
                        "TRIAL_COLLECTION_RETRY", "采集结果正在更新，请沿原请求重试"
                    ) from error
        raise AssertionError("unreachable")

    def _collect_once(
        self, context: AuthContext, project: UUID, protocol: UUID, body: CollectIssueTrial
    ) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project, write=True)
            original = read_protocol(c, tenant, project, protocol)
            signature = digest(
                {
                    "project_id": str(project),
                    "protocol_id": str(protocol),
                    **body.model_dump(mode="json", exclude={"request_id"}),
                }
            )
            t = tables.ai_issue_trial_collections
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.actor_user_id == actor,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise WritePolicyError("REQUEST_ID_REUSED", "此请求已用于其他登记采集")
                return {
                    "collection": _read(c, tenant, project, protocol, old["id"]),
                    "replayed": True,
                }
            as_of = c.execute(select(func.transaction_timestamp())).scalar_one()
            window_start, window_end = (
                _stamp(original["window_start"]),
                _stamp(original["window_end"]),
            )
            if window_end > as_of:
                raise WritePolicyError(
                    "TRIAL_WINDOW_OPEN", "原登记窗口尚未结束，请待窗口结束后采集"
                )
            items = collect(
                c,
                tenant,
                project,
                CaptureRequest(
                    request_id=body.request_id, window_start=window_start, window_end=window_end
                ),
                as_of,
            )
            proofs = collect_provenance(
                c,
                tenant_id=tenant,
                project_id=project,
                run_ids=[UUID(v["run_id"]) for v in items],
                as_of=as_of,
                expected_binding=IssueEvaluationBinding.model_validate(original["binding"]),
            )
            for item in items:
                proof = proofs[item["run_id"]]
                item["provenance"] = proof
                item["match"] = match_run(original, item, proof, as_of)
            try:
                summary = summarize(original, items, as_of)
            except ValueError as error:
                raise WritePolicyError(
                    "TRIAL_ORIGINALS_INCONSISTENT", "原运行与办理证据不一致，未保存部分统计"
                ) from error
            identity, now = uuid4(), c.execute(select(func.clock_timestamp())).scalar_one()
            value = _plain(
                {
                    "version": VERSION,
                    "id": identity,
                    "tenant_id": tenant,
                    "project_id": project,
                    "protocol_id": protocol,
                    "protocol_digest": digest(original),
                    "actor_user_id": actor,
                    "actor_name": context.user.display_name,
                    "created_at": now,
                    "as_of": as_of,
                    "window_start": window_start,
                    "window_end": window_end,
                    "items": items,
                    **summary,
                    "notice": NOTICE,
                }
            )
            value_digest = digest(value)
            payload = {
                "collection_id": str(identity),
                "collection_digest": value_digest,
                "protocol_id": str(protocol),
                "total_runs": len(items),
            }
            event = EventAuditWriter(
                c, tenant_id=tenant, project_id=project, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-issue-trial-collection:{identity}",
                    event_type="AI_ISSUE_TRIAL_COLLECTED",
                    source="ai_issue_trial_service",
                    entity_id=identity,
                    payload=payload,
                ),
                AuditDraft(action="ai_issue.trial_collected", after_snapshot=payload),
            )
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=tenant,
                    project_id=project,
                    protocol_id=protocol,
                    actor_user_id=actor,
                    request_id=body.request_id,
                    request_digest=signature,
                    as_of=as_of,
                    created_at=now,
                    collection=value,
                    collection_digest=value_digest,
                    output_event_row_id=event.event_row_id,
                )
            )
            return {"collection": value, "replayed": False}
