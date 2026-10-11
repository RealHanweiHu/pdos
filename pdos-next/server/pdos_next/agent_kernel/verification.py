"""Code statistics over verified row identities, never model-supplied sample counts."""

from copy import deepcopy
from decimal import Decimal

from pdos_next.errors import DomainError


def verified_rows(tool_results):
    rows = {}
    for result in tool_results:
        if not isinstance(result, dict) or "error" in result:
            continue
        if "tool" in result and "tier" in result:
            if result["tier"] != "READ":
                continue  # T1 candidates and decision materials are not sample facts.
            result = result["value"]
            if not isinstance(result, dict) or "error" in result:
                continue
        for row in result.get("rows", result.get("ledger", [])):
            if not isinstance(row, dict) or row.get("status", "ok") not in {"ok", "partial"}:
                continue
            identity = row.get("row_id") or row.get("item_id") or row.get("id")
            if identity:
                if str(identity) in rows and rows[str(identity)] != row:
                    raise DomainError("VALIDATION_FAILED", "同一台账行身份对应不同内容。")
                rows[str(identity)] = row
    return rows


def fill_counts(output, tool_results):
    result = deepcopy(output)
    body = result.get("result", {})
    if not isinstance(body, dict):
        return result
    rows = verified_rows(tool_results)
    if "assignments" not in body or "clusters" not in body:
        return result
    clusters = {str(c["cluster_id"]): c for c in body["clusters"]}
    if len(clusters) != len(body["clusters"]):
        raise DomainError("VALIDATION_FAILED", "分组身份重复。")
    assigned, excluded = {}, set()
    for entry in body.get("excluded", []):
        identity = str(entry["item_id"])
        if identity not in rows or identity in excluded:
            raise DomainError("VALIDATION_FAILED", "排除项须引用唯一已验证行。")
        excluded.add(identity)
    for entry in body["assignments"]:
        identity, group = str(entry["item_id"]), str(entry["cluster_id"])
        secondary = entry.get("secondary_cluster_id")
        if (
            identity not in rows
            or group not in clusters
            or identity in assigned
            or identity in excluded
            or secondary is not None
            and str(secondary) not in clusters
        ):
            raise DomainError("VALIDATION_FAILED", "归类须引用唯一已验证行及已声明分组。")
        assigned[identity] = group
    sample_size = len(assigned)
    body["sample_size"] = sample_size
    body["excluded_count"] = len(excluded)
    body["unassigned_count"] = len(set(rows) - assigned.keys() - excluded)
    for group, cluster in clusters.items():
        members = [rows[key] for key, value in assigned.items() if value == group]
        cluster["sample_size"] = len(members)
        cluster["share_percent"] = (
            str(Decimal(len(members)) * 100 / sample_size) if sample_size else None
        )
        distribution = {}
        for field in ("model", "channel", "observed_on"):
            values = {}
            for row in members:
                key = str(row.get(field) or "unknown")
                values[key] = values.get(key, 0) + 1
            distribution[field] = values
        cluster["distributions"] = distribution
    return result
