"""Bounded local alignment of fixed parsed text/cells, before isolated interpretation."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest

from pdos_next.service import digest

from .locations import span

MAX_CHARS = 500_000
MAX_UNITS = 4000
UNIT_CHARS = 600


@dataclass(frozen=True)
class Unit:
    text: str
    start: int
    end: int
    kind: str = "text"


def side(cid, source, unit):
    if unit is None:
        return None
    return {
        "citation_id": cid,
        "quote": unit.text,
        "value_kind": unit.kind,
        "locator": span(source, unit.start, unit.end),
    }


def text_units(body):
    units, start, offset = [], 0, 0

    def append(stop):
        nonlocal start
        for first in range(start, stop, UNIT_CHARS):
            if len(units) > MAX_UNITS:
                break
            last = min(stop, first + UNIT_CHARS)
            units.append(Unit(body[first:last], first, last))
        start = stop

    for line in body.splitlines(keepends=True):
        if len(units) > MAX_UNITS:
            break
        if line.lstrip().startswith("|"):
            append(offset)
            offset += len(line)
            append(offset)
        else:
            offset += len(line)
            if not line.strip():
                append(offset)
    append(len(body))
    return units


def _cells(source):
    seal = source.get("seal")
    return [entry for entry in seal.locator_map if entry.location.kind == "cell"] if seal else []


def sheet_units(cid, source, entries, *, key_headers=None):
    """Align unique headers and the first column's unique, nonempty row keys."""
    lines, offsets = source["body"].splitlines(keepends=True), [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    sheets = {}
    for entry in entries:
        first, last = offsets[entry.derived_line_start - 1], offsets[entry.derived_line_end]
        text = source["body"][first:last].rstrip("\r\n")
        sheets.setdefault(entry.location.sheet, {}).setdefault(entry.location.row, {})[
            entry.location.column
        ] = Unit(text, first, first + len(text), entry.value_kind)
    result, unmatched, bases, selected_keys = {}, [], [], {}
    for sheet, rows in sheets.items():
        header_index = min(rows)
        headers = {col: unit.text.strip() for col, unit in rows[header_index].items()}
        if (
            not headers
            or not all(headers.values())
            or len(set(headers.values())) != len(headers)
            or any(len(value) > UNIT_CHARS for value in headers.values())
        ):
            unmatched.append({"citation_id": cid, "sheet": sheet, "reason": "ambiguous_headers"})
            continue
        preferred = (key_headers or {}).get(sheet)
        if preferred is not None and preferred not in headers.values():
            unmatched.append(
                {"citation_id": cid, "sheet": sheet, "reason": "row_key_header_missing"}
            )
            continue
        key_column = next((col for col, name in headers.items() if name == preferred), min(headers))
        selected_keys[sheet] = headers[key_column]
        keys = [row.get(key_column) for index, row in rows.items() if index != header_index]
        if any(not unit or not unit.text.strip() for unit in keys) or len(
            {unit.text for unit in keys}
        ) != len(keys):
            unmatched.append({"citation_id": cid, "sheet": sheet, "reason": "ambiguous_row_keys"})
            continue
        bases.append({"citation_id": cid, "sheet": sheet, "key_header": headers[key_column][:80]})
        for col, unit in rows[header_index].items():
            result[(sheet, "header", headers[col])] = unit
        for index, row in rows.items():
            if index == header_index:
                continue
            key = row[key_column].text
            for col, unit in row.items():
                if col not in headers:
                    unmatched.append(
                        {"citation_id": cid, "sheet": sheet, "reason": "cell_without_header"}
                    )
                elif len(unit.text) > UNIT_CHARS:
                    unmatched.append(
                        {"citation_id": cid, "sheet": sheet, "reason": "cell_too_large"}
                    )
                else:
                    result[(sheet, key, headers[col])] = unit
    return result, unmatched, bases, selected_keys


def align(left_id, left, right_id, right):
    changes, unmatched, bases, unchanged = [], [], [], 0

    def add(old, new, *, aligned=True):
        if old is not None and new is not None and (old.text, old.kind) == (new.text, new.kind):
            return
        old_side, new_side = side(left_id, left, old), side(right_id, right, new)
        kind = "added" if old is None else "removed" if new is None else "modified"
        changes.append(
            {
                "change_id": digest([left_id, right_id, kind, old_side, new_side]),
                "kind": kind,
                "aligned": aligned,
                "old": old_side,
                "new": new_side,
            }
        )

    if max(len(left["body"]), len(right["body"])) > MAX_CHARS:
        unmatched.append({"reason": "comparison_size_limit", "limit_chars_per_source": MAX_CHARS})
    else:
        left_cells, right_cells = _cells(left), _cells(right)
        if bool(left_cells) != bool(right_cells):
            unmatched.append({"reason": "different_parsed_formats"})
        elif left_cells and max(len(left_cells), len(right_cells)) > MAX_UNITS:
            unmatched.append({"reason": "comparison_unit_limit", "limit": MAX_UNITS})
        elif left_cells:
            old, missing_left, old_bases, key_headers = sheet_units(left_id, left, left_cells)
            new, missing_right, new_bases, _keys = sheet_units(
                right_id, right, right_cells, key_headers=key_headers
            )
            unmatched.extend([*missing_left, *missing_right])
            bases.extend([*old_bases, *new_bases])
            if max(len(old), len(new)) > MAX_UNITS:
                unmatched.append({"reason": "comparison_unit_limit", "limit": MAX_UNITS})
            else:
                ambiguous = {
                    row["sheet"]
                    for row in [*missing_left, *missing_right]
                    if row["reason"]
                    in {"ambiguous_headers", "ambiguous_row_keys", "row_key_header_missing"}
                }
                for key in sorted(set(old) | set(new)):
                    if key[0] in ambiguous:
                        continue
                    a, b = old.get(key), new.get(key)
                    if a and b and (a.text, a.kind) == (b.text, b.kind):
                        unchanged += 1
                    else:
                        add(a, b)
        else:
            old, new = text_units(left["body"]), text_units(right["body"])
            if max(len(old), len(new)) > MAX_UNITS:
                unmatched.append({"reason": "comparison_unit_limit", "limit": MAX_UNITS})
            else:
                matcher = SequenceMatcher(
                    None, [unit.text for unit in old], [unit.text for unit in new]
                )
                for kind, a, b, c, d in matcher.get_opcodes():
                    if kind == "equal":
                        unchanged += b - a
                        continue
                    for first, second in zip_longest(old[a:b], new[c:d]):
                        if (
                            first
                            and second
                            and SequenceMatcher(None, first.text, second.text).ratio() < 0.25
                        ):
                            add(first, None, aligned=False)
                            add(None, second, aligned=False)
                        else:
                            add(first, second)
    for cid, source in ((left_id, left), (right_id, right)):
        seal = source.get("seal")
        if seal and (seal.parse_status != "parsed" or seal.parse_code):
            unmatched.append(
                {"citation_id": cid, "reason": "incomplete_parse", "code": seal.parse_code}
            )
    groups = {}
    for item in unmatched:
        key = tuple(sorted(item.items()))
        if key not in groups:
            groups[key] = {**item, "count": 0}
        groups[key]["count"] += 1
    return {
        "changes": changes,
        "unmatched": list(groups.values()),
        "alignment_basis": bases,
        "stats": {
            "changes": len(changes),
            "unchanged_units": unchanged,
            "unaligned_changes": sum(not row["aligned"] for row in changes),
            "unmatched_sections": len(unmatched),
        },
        "partial": bool(unmatched or any(not row["aligned"] for row in changes)),
    }
