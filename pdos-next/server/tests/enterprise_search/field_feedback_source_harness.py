"""Native Field commands for retrieval tests; no invented domain or model rows."""

from types import SimpleNamespace
from uuid import UUID

from pdos_next.domain.field_feedback.schemas import ACTION, CREATE, LOCATE
from pdos_next.models import now
from tests.field_feedback_pg.test_field_chain import confirmed, prepare
from tests.knowledge_pg.test_publication import command, register, send

RAW = "客户原话：接口漏气，建议更换密封圈。RAW_ONLY_CHILD_MARKER"


def create_feedback(person, config, *, located=True, response=True, source=None):
    work = SimpleNamespace(
        setup=person, config=config, project_id=UUID(config["project"]), at=now(),
    )
    if source is None:
        source = register(work, "D16-01 合成客户来件", "客户来件对应的固定原件。",
                          category_only=True, visibility="private")
    intake, _ = prepare(work, command(work, CREATE, {
        "visibility": "private", "title": "D16-01 合成现场反馈", "description": RAW,
        "channel": "customer", "feedback_kind": "opinion", "received_at": work.at.isoformat(),
        "reported": {"product_label": "待核实型号", "batch_label": None,
                     "configuration_label": None},
        "purpose": "合成反馈检索演练", "sources": [source], "reason": "保留原话与未知定位",
    }, category_only=True))
    result = send(work, intake)
    assert result.status_code == 200, result.text
    created = result.json()
    value = SimpleNamespace(work=work, source=source, intake=created, located=None, response=None,
                            feedback={"id": created["subject_id"], "revision": 1})
    if located:
        location, _ = prepare(work, command(work, LOCATE, {
            "feedback": value.feedback, "project_id": str(work.project_id),
            "engineering_configuration": {"id": config["engineering"]["subject_id"],
                                          "revision": 1},
            "manufacturing_configuration": {"id": config["process"]["subject_id"], "revision": 1},
            "batch": None, "sources": [source], "reason": "只固定实际配置，未知批次仍为空",
        }))
        _signed, value.located = confirmed(work, location)
        value.feedback = {"id": created["subject_id"], "revision": 2}
    if response:
        assert located
        fresh = register(work, "合成独立处置依据", "已按本次登记范围完成隔离检查。")
        action, _ = prepare(work, command(work, ACTION, {
            "feedback": value.feedback, "action_kind": "containment",
            "description": "已登记隔离检查，未声明质量关闭或客户承认。",
            "occurred_at": work.at.isoformat(), "visibility": "private", "sources": [fresh],
            "reason": "登记独立办理事实，原客户报告继续保留",
        }))
        _signed, value.response = confirmed(work, action)
        value.response_source = fresh
    return value
