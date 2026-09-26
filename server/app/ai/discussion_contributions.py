"""Receipt-derived evidence accounting; no inferred agreement or semantic judging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.product_workspace import digest

VERSION = "discussion-contributions-v1"
POLICY = {
    "version": VERSION,
    "stop_after_unchanged_full_round": True,
    "minimum_complete_rounds": 2,
    "agreement_is_consensus": False,
}


def _citation(value: dict[str, Any]) -> str:
    # Preserve the exact source/version/field/value; only citation order is immaterial.
    return digest({k: value[k] for k in ("reference_id", "digest", "field_path", "quoted_value")})


def _statement(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "nature": value["nature"],
        "text": " ".join(value["text"].split()),
        "citations": sorted({_citation(v) for v in value["citations"]}),
    }


def fingerprint(output: dict[str, Any]) -> str:
    return digest(
        {
            "disposition": output["disposition"],
            "statements": sorted({digest(_statement(v)) for v in output["statements"]}),
            "responses": sorted(
                {
                    digest(
                        {
                            "turn_id": v["turn_id"],
                            "position": v["position"],
                            "basis": _statement(v["basis"]),
                        }
                    )
                    for v in output["responses"]
                }
            ),
            "missing": sorted({" ".join(v.split()) for v in output["missing"]}),
        }
    )


def analyze(
    config: dict[str, Any],
    turns: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    research_inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Measure citations already validated against frozen inputs, not world truth.

    A full unchanged round is exact structured repetition after whitespace normalization.
    Changed wording is conservatively treated as changed content, never semantic agreement.
    """
    by_turn = {str(r["turn_id"]): r for r in receipts}
    turn_map = {str(t["id"]): t for t in turns}
    seats = {str(s["id"]): s for s in config["seats"]}
    seen_fields: set[str] = set()
    seen_by_seat: dict[str, set[str]] = {k: set() for k in seats}
    seen_outputs: dict[str, dict[str, str]] = {k: {} for k in seats}
    business_refs: dict[str, set[str]] = {}
    saved: dict[tuple[int, str], dict[str, Any]] = {}
    contributions, responses, decisions = [], [], []
    addressed: set[str] = set()
    for turn in sorted(turns, key=lambda t: t["sequence"]):
        identity = str(turn["id"])
        receipt = by_turn.get(identity)
        if receipt is None or str(turn["seat_id"]) not in seats:
            continue
        seat = str(turn["seat_id"])
        output = receipt["output"]
        citations = [
            c
            for s in [*output["statements"], *(r["basis"] for r in output["responses"])]
            for c in s["citations"]
            if not c["reference_id"].startswith("turn:")
        ]
        keys = {_citation(c) for c in citations}
        business_refs[identity] = {c["reference_id"] for c in citations}
        signature = fingerprint(output)
        repeated = seen_outputs[seat].get(signature)
        entry = {
            "turn_id": identity,
            "seat_id": seat,
            "round_number": turn["round_number"],
            "sequence": turn["sequence"],
            "receipt_id": str(receipt["id"]),
            "fingerprint": signature,
            "repeated_from_turn_id": repeated,
            "business_citation_count": len(keys),
            "new_to_discussion_count": len(keys - seen_fields),
            "new_to_seat_count": len(keys - seen_by_seat[seat]),
            "new_citations": list(
                {_citation(c): c for c in citations if _citation(c) not in seen_fields}.values()
            ),
            "only_discussion_or_no_business_basis": not keys,
        }
        contributions.append(entry)
        saved[(turn["round_number"], seat)] = entry
        seen_fields.update(keys)
        seen_by_seat[seat].update(keys)
        seen_outputs[seat].setdefault(signature, identity)
        for response in output["responses"]:
            target_id = str(response["turn_id"])
            target = turn_map.get(target_id)
            cross_seat = (
                target is not None
                and target["seat_id"] is not None
                and str(target["seat_id"]) != seat
            )
            basis_refs = {
                c["reference_id"]
                for c in response["basis"]["citations"]
                if not c["reference_id"].startswith("turn:")
            }
            target_refs = business_refs.get(target_id, set())
            response_entry = {
                "turn_id": identity,
                "target_turn_id": target_id,
                "seat_id": seat,
                "position": response["position"],
                "basis": response["basis"],
                "cross_seat": cross_seat,
                "separate_source_agreement": cross_seat
                and response["position"] == "agree"
                and bool(basis_refs)
                and bool(target_refs)
                and basis_refs.isdisjoint(target_refs),
            }
            responses.append(response_entry)
            if cross_seat:
                addressed.add(target_id)
            if response["position"] in {"disagree", "needs_evidence"}:
                decisions.append(response_entry)
    research_times: dict[tuple[str, str], datetime] = {}
    for research in research_inputs or []:
        if research.get("origin") != "agent_research":
            continue
        ref = research["reference"]
        key = (ref["reference_id"], ref["digest"])
        stamp = datetime.fromisoformat(research["created_at"])
        research_times[key] = min(stamp, research_times.get(key, stamp))
    rounds = []
    planned = config["request"]["rounds"]
    for n in range(1, planned + 1):
        actual = [saved[(n, s)] for s in seats if (n, s) in saved]
        previous = [saved[(n - 1, s)] for s in seats if (n - 1, s) in saved]
        previous_end = max((v["sequence"] for v in previous), default=0)
        human_since = [
            str(t["id"])
            for t in turns
            if t["speaker_kind"] == "human" and t["sequence"] > previous_end
        ]
        previous_stamp = max(
            (datetime.fromisoformat(turn_map[v["turn_id"]]["created_at"]) for v in previous),
            default=None,
        )
        research_since = [
            key[0]
            for key, stamp in research_times.items()
            if previous_stamp is None or stamp > previous_stamp
        ]
        full = bool(seats) and len(actual) == len(seats)
        unchanged = (
            n >= 2
            and full
            and len(previous) == len(seats)
            and all(saved[(n, s)]["fingerprint"] == saved[(n - 1, s)]["fingerprint"] for s in seats)
        )
        rounds.append(
            {
                "round_number": n,
                "complete": full,
                "turn_ids": [v["turn_id"] for v in actual],
                "receipt_ids": [v["receipt_id"] for v in actual],
                "new_citation_count": sum(v["new_to_discussion_count"] for v in actual),
                "unchanged_from_previous": unchanged,
                "human_input_since_previous": human_since,
                **(
                    {"public_research_since_previous": research_since}
                    if config["request"].get("research_steps")
                    else {}
                ),
            }
        )
    contiguous = 0
    for item in rounds:
        if not item["complete"]:
            break
        contiguous += 1
    latest = rounds[contiguous - 1] if contiguous else None
    eligible = bool(
        config.get("discussion_policy") == POLICY
        and latest
        and latest["unchanged_from_previous"]
        and not latest["human_input_since_previous"]
        and not latest.get("public_research_since_previous")
        and not any(t["round_number"] > contiguous for t in contributions)
    )
    body = {
        "version": VERSION,
        "policy": config.get("discussion_policy"),
        **(
            {"research_policy": "discussion-research-tools.v1"}
            if config["request"].get("research_steps")
            else {}
        ),
        "turns": contributions,
        "rounds": rounds,
        "complete_rounds": contiguous,
        "can_stop_unchanged": eligible,
        "responses": responses,
        "recorded_disagreements": decisions,
        "without_cross_seat_response": [
            v["turn_id"] for v in contributions if v["turn_id"] not in addressed
        ],
        "consensus_established": False,
        "notice": "新增引用指本次首次使用的固定来源字段，不等于新发现的事实；"
        "独立来源的同意仍需人工核对，历史分歧不自动撤销。",
    }
    return {**body, "digest": digest(body)}
