"""Readable clauses keep missing/expired evidence and actual decision fields explicit."""

from app.exports.audit_report_text import sections


def test_audit_keeps_clause_limits_and_actual_decision_fields() -> None:
    actual = {
        "clauses": [
            {
                "standard": "模拟标准",
                "edition": "v1",
                "clause": "1",
                "requirement": "原要求",
                "applicability": "unconfirmed",
                "rationale": "待核范围",
                "missing": "缺真实资料",
                "evidence": [
                    {
                        "kind": "ecn",
                        "id": "ecn",
                        "position": "原位置",
                        "relevance": "原对应",
                        "valid_until": "2020-01-01",
                        "expired": True,
                    }
                ],
            }
        ],
        "sources": [
            {
                "kind": "ecn",
                "id": "ecn",
                "record": {
                    "ecr": {
                        "id": "ecr",
                        "title": "原申请",
                        "code": "ECR-1",
                        "status": "approved",
                        "approved_by_user_id": "person",
                        "approval_note": "原批准理由",
                    },
                    "ecn": {"id": "ecn", "title": "原通知", "code": "ECN-1", "status": "cancelled"},
                    "decisions": [
                        {
                            "id": "decision",
                            "outcome": "拒绝原方案",
                            "rationale": "原裁决原因",
                            "consequence": "仍须补核",
                            "decided_by_user_id": "person",
                        }
                    ],
                    "approval_history": [],
                    "warnings": ["原件缺项"],
                },
            }
        ],
    }
    result = sections(actual, [{"id": "person", "display_name": "模拟批准人"}])
    body = "\n".join(text for title, text in result if "索引" not in title)
    assert "适用性：待确认" in body and "缺真实资料" in body and "已过期，须补核" in body
    assert "原结论：拒绝原方案" in body and "原理由：原裁决原因" in body
    assert "状态：已取消" in body and "模拟批准人" in body
    assert "尚无原办理历史，不从当前字段补造" in body
