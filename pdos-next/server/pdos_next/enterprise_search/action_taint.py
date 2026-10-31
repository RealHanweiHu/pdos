"""Server-only classification of current actual source footprints; never authority."""

from pdos_next.errors import DomainError


def classify(actual):
    return {
        "private": any(row["private"] for row in actual.values()),
        "customer_original": any(row["customer_original"] for row in actual.values()),
    }


def inherit(parent, taint):
    """Add current proof classification to conversation.merge_binding's existing port."""
    if (not isinstance(taint, dict) or set(taint) != {"private", "customer_original"}
        or any(type(value) is not bool for value in taint.values())):
        raise DomainError("SOURCE_UNAVAILABLE", "实际行动来源缺少当前分类，请重新续接。")
    before = getattr(parent, "_explicit_context_binding", {})
    categories = set(before.get("data_categories", ()))
    if taint["customer_original"]:
        categories.add("customer_original")
    parent._explicit_context_binding = {
        **before, "private_context": before.get("private_context", False) or taint["private"],
        "data_categories": sorted(categories),
    }
