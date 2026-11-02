"""Assemble only verified comparison calls; model tables cannot supply source cells."""

from copy import deepcopy


def assemble(calls, citations, actual):
    reads = [call.result for call, _args in calls if call.tool == "assistant.compare"]
    if not reads:
        return None, [], []
    latest = reads[-1]
    ids = latest["citation_ids"]
    rows, evidence, seen = [], [], set()
    complete = True
    for read in reads:
        if read["citation_ids"] != ids:
            continue
        complete &= read["batch_complete"] and not read["rejected"]
        for row in read["rows"]:
            valid = True
            for side in (row["old"], row["new"]):
                if side is None:
                    continue
                source = actual.get(side["citation_id"])
                location = side["locator"]
                if (
                    source is None
                    or source["body"][location["char_start"] : location["char_end"]]
                    != side["quote"]
                ):
                    valid = False
                    break
            if not valid:
                complete = False
                continue
            if row["change_id"] in seen:
                continue
            seen.add(row["change_id"])
            rows.append(deepcopy(row))
            for side in (row["old"], row["new"]):
                if side is not None:
                    evidence.append(
                        {
                            **side,
                            "statement": "已核对的固定版本差异。",
                            "change_id": row["change_id"],
                        }
                    )
    # The comparison's code checks both full parsed bodies. These references
    # identify that deterministic basis without inventing a quotation for an
    # unchanged document or the absent side of an insertion/deletion.
    for cid in ids:
        if cid not in actual:
            complete = False
            continue
        if any(row["citation_id"] == cid for row in evidence):
            continue
        evidence.append(
            {
                "citation_id": cid,
                "quote": "",
                "locator": citations[cid]["locator"],
                "statement": "已核对固定解析版本的比较依据。",
            }
        )
    stats = latest["stats"]
    complete &= (
        len(rows) == stats["changes"] and not stats["unaligned_changes"] and not latest["unmatched"]
    )
    value = {
        "version": 1,
        "format": "comparison",
        "citation_ids": ids,
        "rows": rows,
        "stats": stats,
        "complete": complete,
        "unmatched": latest["unmatched"],
        "alignment_basis": latest["alignment_basis"],
        "as_of": latest["as_of"],
    }
    unknowns = ["未对齐或未完整解析的部分待核对。"] if latest["unmatched"] else []
    if not complete:
        unknowns.append(f"已核对 {len(rows)} / {stats['changes']} 处变化，剩余部分待处理。")
    return value, evidence, unknowns


def markdown(value):
    """Private work products preserve the server's literal cells and unknowns."""

    def cell(text):
        return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    lines = ["| 变化项 | 旧版 | 新版 | 文中影响依据 | 待确认 |", "| --- | --- | --- | --- | --- |"]
    for row in value["rows"]:
        fields = [
            row["label"],
            row["old"]["quote"] if row["old"] else "无对应内容",
            row["new"]["quote"] if row["new"] else "无对应内容",
            row["impact"]["quote"] if row["impact"] else "待确认",
            "；".join(row["questions"]) or "待确认",
        ]
        lines.append("| " + " | ".join(cell(field) for field in fields) + " |")
    if not value["rows"]:
        lines.append("| 已解析内容 | 未发现值变化 | 未发现值变化 | 待确认 | 以解析覆盖为限 |")
    lines.append(
        f"\n固定版本比较：{value['as_of']}；"
        f"核对变化 {len(value['rows'])} / {value['stats']['changes']} 处。"
    )
    if not value["complete"]:
        lines.append("未完整比较的部分待确认，不能据此断言没有其他变化。")
    return "\n".join(lines)
