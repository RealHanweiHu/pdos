"""Pure assembly of explicitly supplied synthetic statements; no authority or IO.

The caller supplies real fixed identities and four named judgments. Registration,
currentness, role qualification and each T2 decision remain real server actions.
"""

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

RULES = {
    "engineering": (
        "product_definition_applicability",
        "verification_objective_applicability",
    ),
    "manufacturing": (
        "process_configuration_applicability",
        "output_disposition_applicability",
    ),
}
CONTROLS = (
    "no_test_run_or_sample_qualification",
    "no_external_delivery",
    "retain_traceable_outputs",
    "stop_on_configuration_deviation",
)
SCHEMA = "wave22-synthetic-named-build-publication-v1"


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("actual UUID string required")
    return str(UUID(value))


def _text(value, maximum=2000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ValueError("explicit bounded statement required")
    return value


def _clock(value):
    _text(value, 100)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("explicit aware time required")
    return parsed


def _fixed(value, *, assessment=False):
    fields = {"id", "revision", "sha256"} if assessment else {"id", "revision"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("exact fixed row reference required")
    if type(value["revision"]) is not int or value["revision"] < 1:
        raise ValueError("actual positive row revision required")
    result = {"id": _uuid(value["id"]), "revision": value["revision"]}
    if assessment:
        sha = value["sha256"]
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise ValueError("actual assessment SHA required")
        result["sha256"] = sha
    return result


def _binding(value):
    identities = {"tenant_id", "product_id", "project_id", "maker_id"}
    fixed = {"build", "definition", "bom", "engineering", "manufacturing"}
    fields = identities | fixed | {"assessment", "execution_scope", "build_type"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("complete actual fixed binding required")
    if value["build_type"] not in {"prototype", "tool_trial"}:
        raise ValueError("internal prototype or tool trial required")
    result = {key: _uuid(value[key]) for key in identities}
    result.update({key: _fixed(value[key]) for key in fixed})
    result["assessment"] = _fixed(value["assessment"], assessment=True)
    result["build_type"] = value["build_type"]
    scope = value["execution_scope"]
    if type(scope) is not dict or set(scope) != {
        "purpose",
        "quantity",
        "unit",
        "site",
        "window_start",
        "window_end",
        "window_timezone",
    }:
        raise ValueError("complete actual execution scope required")
    for key in ("purpose", "unit", "site", "window_timezone"):
        _text(scope[key], 160)
    if not isinstance(scope["quantity"], str):
        raise ValueError("exact decimal string required")
    try:
        quantity = Decimal(scope["quantity"])
    except InvalidOperation:
        raise ValueError("finite positive quantity required") from None
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("finite positive quantity required")
    if _clock(scope["window_end"]) <= _clock(scope["window_start"]):
        raise ValueError("ordered explicit execution window required")
    ZoneInfo(scope["window_timezone"])
    result["execution_scope"] = deepcopy(scope)
    return result


def _line(value):
    result = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(result) > 4000:
        raise ValueError("complete source line exceeds quote limit; shorten prose, never truncate")
    return result


def publication_lines(
    binding, reviews, accepted_controls, control_statement, *, reviewed_at, valid_until
):
    """Return six full lines from explicit judgments; never defaults to applicable.

    No clock is generated and no material/authority/freshness claim is evaluated.
    Reviews map each of the four closed rule IDs to status/reason/assessment text.
    """
    fixed = _binding(binding)
    flat_rules = (*RULES["engineering"], *RULES["manufacturing"])
    if type(reviews) is not dict or set(reviews) != set(flat_rules):
        raise ValueError("all four explicit judgments required")
    if (
        type(accepted_controls) is not list
        or len(accepted_controls) != len(CONTROLS)
        or set(accepted_controls) != set(CONTROLS)
    ):
        raise ValueError("explicit acceptance of exactly four closed controls required")
    if _clock(valid_until) < _clock(fixed["execution_scope"]["window_end"]):
        raise ValueError("statement validity must cover fixed execution window")
    if _clock(reviewed_at) >= _clock(valid_until):
        raise ValueError("statement time must precede validity end")
    common = {
        "schema_version": SCHEMA,
        "nature": "synthetic",
        "visibility": "product",
        "binding": fixed,
        "reviewed_at": reviewed_at,
        "valid_until": valid_until,
        "production_qualification": False,
        "test_run_or_sample_qualification": False,
        "external_delivery_authorized": False,
    }
    lines = [
        _line(
            {
                **common,
                "kind": "scope",
                "statement": "仅本地合成内部制造调查，不授真实生产、测试或外发资格。",
            }
        )
    ]
    for role, rules in RULES.items():
        for rule in rules:
            judgment = reviews[rule]
            if type(judgment) is not dict or set(judgment) != {"status", "reason", "assessment"}:
                raise ValueError("explicit status, reason and assessment required")
            if judgment["status"] not in {"applicable", "unknown", "blocked"}:
                raise ValueError("closed applicability status required")
            lines.append(
                _line(
                    {
                        **common,
                        "kind": "professional_assessment",
                        "role": role,
                        "rule_id": rule,
                        "status": judgment["status"],
                        "reason": _text(judgment["reason"]),
                        "assessment": _text(judgment["assessment"]),
                    }
                )
            )
    lines.append(
        _line(
            {
                **common,
                "kind": "accepted_controls",
                "accepted_controls": list(CONTROLS),
                "statement": _text(control_statement),
            }
        )
    )
    return tuple(lines)


def _reference(value):
    if type(value) is not dict or set(value) != {
        "artifact_id",
        "expected_revision",
        "line",
        "quote",
    }:
        raise ValueError("actual complete DefinitionReference required")
    for field in ("expected_revision", "line"):
        if type(value[field]) is not int or value[field] < 1:
            raise ValueError("positive precise source location required")
    return {
        **value,
        "artifact_id": _uuid(value["artifact_id"]),
        "quote": _text(value["quote"], 4000),
    }


def authorization_material(
    role, artifact_id, artifact_revision, lines, *, reason, authority_sources=()
):
    """Four-key material accepted by frozen Build v1, using actually saved source.

    The caller must compare all six lines with the real registered Artifact. Extra
    sources preserve actual operation-specific authority closure, not fake grants.
    Returned material has no approval token and cannot itself approve anything.
    """
    if role not in RULES or type(artifact_revision) is not int or artifact_revision < 1:
        raise ValueError("closed role and actual Artifact revision required")
    if not isinstance(lines, (tuple, list)) or len(lines) != 6:
        raise ValueError("six complete original lines required")
    objects = [json.loads(_text(line, 4000)) for line in lines]
    first = objects[0]
    if first.get("kind") != "scope" or first.get("schema_version") != SCHEMA:
        raise ValueError("exact publication version required")
    common = {key: value for key, value in first.items() if key not in {"kind", "statement"}}
    if common.get("nature") != "synthetic" or common.get("visibility") != "product":
        raise ValueError("explicit shared synthetic publication required")
    # Rebuild through the original pure constructor to reject mixed scope/clock or altered lines.
    reviews = {
        obj.get("rule_id"): {key: obj.get(key) for key in ("status", "reason", "assessment")}
        for obj in objects[1:5]
    }
    rebuilt = publication_lines(
        common["binding"],
        reviews,
        objects[5].get("accepted_controls"),
        objects[5].get("statement"),
        reviewed_at=common["reviewed_at"],
        valid_until=common["valid_until"],
    )
    if tuple(lines) != rebuilt:
        raise ValueError("publication lines differ from complete fixed material")
    refs = [
        {
            "artifact_id": _uuid(artifact_id),
            "expected_revision": artifact_revision,
            "line": index + 1,
            "quote": line,
        }
        for index, line in enumerate(lines)
    ]
    top = [refs[0], refs[5], *[_reference(ref) for ref in authority_sources]]
    if len(top) > 20 or len({json.dumps(v, sort_keys=True) for v in top}) != len(top):
        raise ValueError("source list exceeds bound or repeats an exact reference")
    offset = 1 if role == "engineering" else 3
    return {
        "professional_assessments": [
            {
                "rule_id": rule,
                "status": objects[offset + index]["status"],
                "sources": [refs[offset + index]],
                "valid_until": common["valid_until"],
                "reason": objects[offset + index]["reason"],
            }
            for index, rule in enumerate(RULES[role])
        ],
        "accepted_controls": list(CONTROLS),
        "sources": top,
        "reason": _text(reason),
    }
