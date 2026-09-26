from app.domain.audit_customer_projection import signature_text


def test_customer_signature_uses_only_disclosed_fields_and_preserves_unknown() -> None:
    record = {
        "type": "Gate",
        "reference": "GATE-SIM",
        "status": "hold",
        "round": 1,
        "internal_reason": "internal-only-do-not-include",
        "signed_by_user_id": "private-account",
        "signoffs": [
            {
                "specialty": "quality",
                "status": "rejected",
                "signed_at": None,
                "note": "internal-comment-do-not-include",
            }
        ],
    }
    output = signature_text(record)
    assert "原状态：暂缓" in output and "品质席：退回" in output and "签核时间：未记录" in output
    assert "internal" not in output and "private-account" not in output
