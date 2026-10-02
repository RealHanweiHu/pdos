"""Read original Issue-trigger evidence, without creating or authorizing any Issue.

The caller owns source read authorization and a consistent transaction. Current
means current evidence, never AI write permission. Unknown SQL errors propagate.
"""

from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, select

from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialError
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_allocations import MaterialAllocationError
from app.domain.material_coverage import CoverageSelection, MaterialCoverageService
from app.domain.material_exceptions import _assessment
from app.domain.product_workspace import _plain, digest

REASONS = {
    "current": "原事件与当前业务依据一致；自动写入仍须独立核对授权和资格",
    "event_unverified": "原事件生产者、对象或审计链不完整，不能作为建单依据",
    "unsupported_event": "该事件不是测试失败或已具名确认的物料异常",
    "source_missing": "原业务对象或原关联问题已不可读取",
    "test_changed": "测试结果或依据已有后续变化，请回到原测试核对；已有问题保持原状态",
    "test_origin_unverified": "未能唯一核实原逐次测试或报告确认批次，不能猜测最近测试",
    "material_review_unverified": "原异常核对版本与事件审计不能对应，需补核原依据",
    "material_changed": "物料需求、供给或核对版本已变化，请重新具名核对；已有问题不会自动关闭",
    "material_gap_unknown": "原异常尚无可确认的当前物料缺口，不能推定需要新增问题",
    "actor_unavailable": "原具名办理人或其当前资料读取权限已不可用，需重新核对来源",
}


def _one(c: Connection, statement: Any) -> dict[str, Any] | None:
    row = c.execute(statement).mappings().one_or_none()
    return dict(row) if row is not None else None


def _entity(c: Connection, table: Any, tenant: UUID, project: UUID, identity: Any) -> Any:
    return _one(
        c,
        select(table).where(
            table.c.tenant_id == tenant, table.c.project_id == project, table.c.id == identity
        ),
    )


def _audit(c: Connection, event: dict[str, Any]) -> dict[str, Any] | None:
    a = tables.audit_log
    rows = list(
        c.execute(
            select(a).where(a.c.tenant_id == event["tenant_id"], a.c.event_id == event["event_id"])
        ).mappings()
    )
    if len(rows) != 1:
        return None
    row = dict(rows[0])
    if (
        any(
            row.get(key) != event.get(key)
            for key in ("project_id", "entity", "entity_id", "timestamp")
        )
        or row.get("actor_user_id") is None
    ):
        return None
    return row


def _human(c: Connection, tenant: UUID, identity: UUID) -> dict[str, Any] | None:
    u = tables.users
    return _one(
        c,
        select(
            u.c.id,
            u.c.tenant_id,
            u.c.username,
            u.c.display_name,
            u.c.role,
            u.c.auth_version,
            u.c.is_active,
        ).where(u.c.tenant_id == tenant, u.c.id == identity),
    )


def _context(c: Connection, tenant: UUID, human: dict[str, Any] | None) -> AuthContext | None:
    t = tables.tenants
    row = _one(c, select(t.c.id, t.c.slug, t.c.name, t.c.status).where(t.c.id == tenant))
    if row is None or row["status"] != "active" or not human or not human["is_active"]:
        return None
    return AuthContext(
        tenant=TenantRecord(**row),
        user=UserRecord(
            id=human["id"],
            tenant_id=tenant,
            username=human["username"],
            display_name=human["display_name"],
            role=Role(human["role"]),
            auth_version=human["auth_version"],
            is_active=human["is_active"],
            password_hash=None,
            email=None,
        ),
    )


def _issue(c: Connection, tenant: UUID, project: UUID, identity: UUID | None) -> Any:
    if identity is None:
        return None
    row = _entity(c, tables.issues, tenant, project, identity)
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "status": row["status"],
        "href": f"/projects?project={project}&tab=work-items&entity_id={identity}#issue-{identity}",
        "snapshot": _plain(row),
    }


def _finish(result: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    result.update(source_status=status, reason_code=reason, reason=REASONS[reason])
    result["source"] = _plain(result["source"])
    result["source_digest"] = digest(
        {
            "source": result["source"],
            "existing_issue": result["existing_issue"],
            "source_status": status,
            "reason_code": reason,
        }
    )
    return result


def _event_identity(event: dict[str, Any], prefix: str) -> bool:
    value = event["event_id"]
    if not isinstance(value, str) or not value.startswith(prefix):
        return False
    try:
        UUID(value[len(prefix) :])
    except ValueError:
        return False
    return True


def _run_origin(
    c: Connection, event: dict[str, Any], audit: dict[str, Any], case: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Bind the original run event via actual case FK; never pick latest by time."""
    e, r = tables.events, tables.test_runs
    events = c.execute(
        select(e)
        .join(
            r,
            (
                (r.c.tenant_id == e.c.tenant_id)
                & (r.c.project_id == e.c.project_id)
                & (r.c.id == e.c.entity_id)
            ),
        )
        .where(
            e.c.tenant_id == event["tenant_id"],
            e.c.project_id == event["project_id"],
            e.c.timestamp == event["timestamp"],
            e.c.event_type == "NPI_RECORD_CHANGED",
            e.c.source == "npi_service",
            e.c.entity == "npi_record",
            r.c.test_case_id == case["id"],
        )
        .order_by(e.c.id)
    ).mappings()
    matches = []
    for raw in events:
        item = dict(raw)
        payload = item["payload"]
        action = payload.get("action")
        if payload.get("record_type") != "test_run" or action not in {
            "recorded_failed",
            "completed_failed",
        }:
            continue
        verb = "recorded" if action == "recorded_failed" else "completed"
        if not _event_identity(item, f"npi:test_run:{item['entity_id']}:{verb}:"):
            continue
        original = _audit(c, item)
        if not original or original["actor_user_id"] != audit["actor_user_id"]:
            continue
        if original["action"] != ("test_run.record" if verb == "recorded" else "test_run.complete"):
            continue
        after = original.get("after_snapshot") or {}
        if (
            after.get("test_case_id") != str(case["id"])
            or after.get("project_id") != str(event["project_id"])
            or after.get("status") != "failed"
        ):
            continue
        run = _entity(c, r, event["tenant_id"], event["project_id"], item["entity_id"])
        if run is not None and run["test_case_id"] == case["id"]:
            matches.append((item, original, run))
    return matches[0] if len(matches) == 1 else None


def _import_origin(
    c: Connection, event: dict[str, Any], audit: dict[str, Any], case: dict[str, Any]
) -> dict[str, Any] | None:
    """The confirmation's fixed set, not all current runs, defines its final row."""
    e, b, r = tables.events, tables.test_report_import_batches, tables.test_runs
    candidates = c.execute(
        select(e)
        .join(
            b,
            (
                (b.c.tenant_id == e.c.tenant_id)
                & (b.c.project_id == e.c.project_id)
                & (b.c.id == e.c.entity_id)
            ),
        )
        .where(
            e.c.tenant_id == event["tenant_id"],
            e.c.project_id == event["project_id"],
            e.c.timestamp == event["timestamp"],
            e.c.event_type == "NPI_RECORD_CHANGED",
            e.c.source == "npi_service",
            e.c.entity == "npi_record",
            b.c.plan_id == case["plan_id"],
            b.c.confirmed_at == event["timestamp"],
        )
        .order_by(e.c.id)
    ).mappings()
    matches = []
    for raw in candidates:
        item = dict(raw)
        if item["payload"] != {"record_type": "test_report_import", "action": "confirmed"}:
            continue
        if item["event_id"] != f"npi:import_batch:{item['entity_id']}:confirmed":
            continue
        original = _audit(c, item)
        if (
            not original
            or original["action"] != "test_report_import.confirm"
            or (original["actor_user_id"] != audit["actor_user_id"])
        ):
            continue
        batch = _entity(c, b, event["tenant_id"], event["project_id"], item["entity_id"])
        after = original.get("after_snapshot") or {}
        ids = after.get("confirmed_run_ids")
        if (
            not batch
            or after.get("batch_id") != str(batch["id"])
            or (
                not isinstance(ids, list)
                or not ids
                or not all(isinstance(v, str) for v in ids)
                or ids != batch["created_run_ids"]
                or len(set(ids)) != len(ids)
                or batch["confirmed_by_user_id"] != audit["actor_user_id"]
            )
        ):
            continue
        try:
            identities = [UUID(v) for v in ids]
        except (ValueError, TypeError, AttributeError):
            continue
        runs = [
            dict(v)
            for v in c.execute(
                select(r)
                .where(
                    r.c.tenant_id == event["tenant_id"],
                    r.c.project_id == event["project_id"],
                    r.c.id.in_(identities),
                )
                .order_by(r.c.run_number)
            ).mappings()
        ]
        if len(runs) != len(ids):
            continue
        related = [v for v in runs if v["test_case_id"] == case["id"]]
        if not related or any(v["evidence_document_id"] != batch["document_id"] for v in related):
            continue
        run = related[-1]
        if run["updated_at"] == event["timestamp"] and run["status"] != "failed":
            continue
        # All runs are updated by confirmation. Later modifications remain current
        # snapshots; do not misrepresent their prose as the original failed result.
        original_result = (
            _plain(run)
            if run["updated_at"] == event["timestamp"]
            else {
                "id": str(run["id"]),
                "status": "failed",
                "result_notes": None,
                "detail_state": "确认审计仅固定记录编号；原正文已有变化，须回查报告原件",
            }
        )
        matches.append(
            dict(
                event=_plain(item),
                audit=_plain(original),
                batch=_plain(batch),
                run=run,
                original_result=original_result,
            )
        )
    return matches[0] if len(matches) == 1 else None


def _test(
    c: Connection, result: dict[str, Any], event: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    tenant, project = event["tenant_id"], event["project_id"]
    case = _entity(c, tables.test_cases, tenant, project, event["entity_id"])
    if case is None:
        return _finish(result, "unavailable", "source_missing")
    result.update(
        title=f"测试失败：{case['title']}",
        source_href=f"/projects?project={project}&tab=quality&test_case_id={case['id']}",
        existing_issue=_issue(c, tenant, project, case["related_issue_id"]),
    )
    source = result["source"]
    source.update(source_key=f"test_case:{case['id']}", current_case=_plain(case))
    result["summary"] = [
        {"label": "原失败时间", "value": event["timestamp"].isoformat()},
        {
            "label": "当前测试状态",
            "value": {
                "planned": "待测试",
                "passed": "通过",
                "failed": "失败",
                "blocked": "受阻",
                "waived": "已豁免",
            }.get(case["status"], "未知"),
        },
    ]
    if case["related_issue_id"] is not None and result["existing_issue"] is None:
        return _finish(result, "unavailable", "source_missing")
    after = audit.get("after_snapshot") or {}
    if after.get("status") != "failed":
        return _finish(result, "unavailable", "event_unverified")
    if after.get("id") == str(case["id"]):
        if after.get("project_id") != str(project) or not all(
            key in after for key in ("title", "plan_id", "acceptance_criteria", "result_notes")
        ):
            return _finish(result, "unavailable", "event_unverified")
        source.update(origin_kind="legacy_test_case", original_result=after)
        result["title"] = f"测试失败：{after['title']}"
        current = _plain(case)
        changed = any(current.get(key) != value for key, value in after.items())
    else:
        source["origin_kind"] = "test_run_unverified"
        origin = _run_origin(c, event, audit, case)
        if origin is None:
            imported = _import_origin(c, event, audit, case)
            if imported is None:
                return _finish(result, "unavailable", "test_origin_unverified")
            run, original = imported["run"], imported["original_result"]
            source.update(
                origin_kind="test_report_import",
                original_result=original,
                import_event=imported["event"],
                import_audit=imported["audit"],
                import_batch=imported["batch"],
                current_run=_plain(run),
            )
        else:
            run_event, run_audit, run = origin
            original = run_audit["after_snapshot"]
            source.update(
                origin_kind="test_run",
                original_result=original,
                run_event=_plain(run_event),
                run_audit=_plain(run_audit),
                current_run=_plain(run),
            )
        result["source_href"] += f"&test_run_id={run['id']}"
        current = _plain(run)
        issue_id = str(case["related_issue_id"]) if case["related_issue_id"] else None
        changed = (
            run["draft_state"] != "confirmed"
            or run["status"] != "failed"
            or case["updated_at"] > event["timestamp"]
            or any(current.get(key) != value for key, value in original.items())
            or after.get("related_issue_id") != issue_id
            or (
                source["origin_kind"] == "test_report_import"
                and (
                    run["updated_at"] != event["timestamp"]
                    or source["import_batch"]["status"] != "confirmed"
                    or source["import_batch"].get("superseded_by_batch_id") is not None
                )
            )
        )
    result["summary"].append(
        {
            "label": "原失败说明",
            "value": (
                source["original_result"].get("result_notes") or "原记录未留说明或原正文待核对"
            ),
        }
    )
    if changed or case["status"] != "failed":
        return _finish(result, "changed", "test_changed")
    return _finish(result, "current", "current")


def _material(
    c: Connection, result: dict[str, Any], event: dict[str, Any], audit: dict[str, Any]
) -> dict[str, Any]:
    tenant, project = event["tenant_id"], event["project_id"]
    row = _entity(c, tables.material_exceptions, tenant, project, event["entity_id"])
    if row is None:
        return _finish(result, "unavailable", "source_missing")
    result.update(
        title=f"物料异常：{row['material_reference'] or '引用待补'}",
        source_href=f"/projects?project={project}&tab=quality&build_id={row['build_id']}#build-{row['build_id']}",
        existing_issue=_issue(c, tenant, project, row["issue_id"]),
    )
    source = result["source"]
    source.update(source_key=f"material_exception:{row['id']}", exception=_plain(row))
    if result["existing_issue"] is None:
        return _finish(result, "unavailable", "source_missing")
    t = tables.material_exception_reviews
    reviews = [
        dict(v)
        for v in c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.exception_id == row["id"]
            )
            .order_by(t.c.version.desc())
        ).mappings()
    ]
    after = audit.get("after_snapshot") or {}
    original = after.get("review")
    if not isinstance(original, dict) or not reviews:
        return _finish(result, "unavailable", "material_review_unverified")
    saved = next((r for r in reviews if str(r["id"]) == original.get("id")), None)
    if (
        saved is None
        or _plain(saved) != original
        or after.get("exception_id") != str(row["id"])
        or after.get("issue_id") != str(row["issue_id"])
        or saved["created_by_user_id"] != audit["actor_user_id"]
        or (saved["version"] == 1) != (event["payload"]["action"] == "confirmed")
    ):
        return _finish(result, "unavailable", "material_review_unverified")
    source.update(original_review=original, latest_review=_plain(reviews[0]))
    result["summary"] = [
        {"label": "物料", "value": row["material_reference"] or "引用待补"},
        {"label": "原核对版本", "value": str(saved["version"])},
        {"label": "当前核对版本", "value": str(reviews[0]["version"])},
    ]
    snapshot = saved["snapshot"]
    basis = snapshot.get("basis")
    if (
        not isinstance(basis, dict)
        or snapshot.get("digest") != saved["basis_digest"]
        or (
            digest(basis) != saved["basis_digest"]
            or basis.get("material_key") != row["material_key"]
        )
    ):
        return _finish(result, "unavailable", "material_review_unverified")
    context = _context(c, tenant, source["human"])
    if context is None:
        return _finish(result, "unavailable", "actor_unavailable")
    try:
        selection = CoverageSelection.model_validate(basis.get("selection"))
    except ValidationError:
        return _finish(result, "unavailable", "material_review_unverified")
    try:
        with localcontext() as arithmetic:
            arithmetic.prec = 2048
            coverage = MaterialCoverageService.read(c, context, project, row["build_id"], selection)
            assessment = _assessment(coverage, row["material_key"])
    except KnowledgeAccessError:
        return _finish(result, "unavailable", "actor_unavailable")
    except (BuildMaterialError, MaterialAllocationError) as error:
        source["current_source_error"] = str(error)
        return _finish(result, "unavailable", "source_missing")
    # Observation clock is not a business version. Expiry states remain in basis.
    source["current_assessment"] = {key: assessment[key] for key in ("basis", "digest")}
    if saved["id"] != reviews[0]["id"] or assessment["digest"] != saved["basis_digest"]:
        return _finish(result, "changed", "material_changed")
    material = assessment["basis"].get("material")
    gap = material.get("observed_on_hand_gap") if material else None
    if saved["disposition"] != "follow_up" or gap is None:
        return _finish(result, "unavailable", "material_gap_unknown")
    if Decimal(str(gap)) <= 0:
        return _finish(result, "changed", "material_changed")
    result["summary"].append({"label": "已登记范围现货缺口", "value": str(gap)})
    return _finish(result, "current", "current")


def read_event_source(
    c: Connection, tenant: UUID, project: UUID, event_row_id: int
) -> dict[str, Any]:
    """Read one scoped event; missing/wrong-scope IDs raise LookupError."""
    event = _entity(c, tables.events, tenant, project, event_row_id)
    if event is None:
        raise LookupError("本项目中没有该事件")
    is_test = event["event_type"] == "TEST_FAILED"
    result: dict[str, Any] = {
        "event_row_id": event["id"],
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "event_at": event["timestamp"].isoformat(),
        "source_kind": "test_failure" if is_test else "material_exception",
        "title": "测试失败" if is_test else "物料异常",
        "existing_issue": None,
        "source_href": None,
        "summary": [],
        "source": {"version": "ai-issue-event-source-v1", "event": _plain(event)},
    }
    payload = event["payload"]
    if not is_test and not (
        event["event_type"] == "NPI_RECORD_CHANGED"
        and payload.get("record_type") == "material_exception"
        and payload.get("action") in {"confirmed", "reviewed"}
    ):
        return _finish(result, "unavailable", "unsupported_event")
    audit = _audit(c, event)
    result["source"]["audit"] = _plain(audit) if audit else None
    expected_action = (
        "npi.test_case.failed" if is_test else (f"npi.material_exception.{payload['action']}")
    )
    prefix = (
        f"test:{event['entity_id']}:failed:"
        if is_test
        else (f"npi:material_exception:{event['entity_id']}:{payload['action']}:")
    )
    if (
        not audit
        or audit["action"] != expected_action
        or event["source"] != ("quality_service" if is_test else "npi_service")
        or event["entity"] != ("test" if is_test else "npi_record")
        or not _event_identity(event, prefix)
        or (is_test and payload.get("test_record_id") != str(event["entity_id"]))
    ):
        return _finish(result, "unavailable", "event_unverified")
    human = _human(c, tenant, audit["actor_user_id"])
    result["source"]["human"] = human
    if human is None:
        return _finish(result, "unavailable", "actor_unavailable")
    return _test(c, result, event, audit) if is_test else _material(c, result, event, audit)
