"""Skill-scoped context contracts and metadata-only snapshots, before model egress."""

import json
import os
from copy import deepcopy
from uuid import uuid4

from jsonschema import Draft202012Validator
from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.service import digest


def load_contracts(directory):
    data = json.loads((directory / "context-schemas.json").read_text())
    if data.get("format_version") != 1:
        raise ValueError("Unknown context schema format")
    def local_refs(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None and (
                not isinstance(reference, str) or not reference.startswith("#/$defs/")
                or reference[len("#/$defs/"):] not in data["$defs"]
            ):
                raise ValueError("Context schemas must resolve inside the local registry")
            for child in value.values():
                local_refs(child)
        elif isinstance(value, list):
            for child in value:
                local_refs(child)
    local_refs(data)
    for schema in data["profiles"].values():
        Draft202012Validator.check_schema({**schema, "$defs": data["$defs"]})
    return data


def declared_contract(declaration, contracts):
    prefix = "context-schemas.json#/profiles/"
    if not isinstance(declaration, dict) or set(declaration) != {"$ref"}:
        raise ValueError("Skill context_schema must name a local registered profile")
    value = declaration["$ref"]
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("Skill context_schema must use the local schema registry")
    key = value[len(prefix):]
    if key not in contracts["profiles"]:
        raise ValueError("Skill context_schema profile is not registered")
    return deepcopy({**contracts["profiles"][key], "$defs": contracts["$defs"]})


def combine_contracts(catalog, skills):
    schemas = [skill.metadata["context_schema"] for skill in skills] or [
        declared_contract({"$ref": "context-schemas.json#/profiles/navigation"}, catalog.contexts)
    ]
    properties, required = {}, set()
    for schema in schemas:
        if schema["$defs"] != schemas[0]["$defs"]:
            raise DomainError("VERSION_CONFLICT", "已加载方法使用了不同的资料合同定义。")
        for key, value in schema["properties"].items():
            if key in properties and properties[key] != value:
                raise DomainError("VERSION_CONFLICT", "已加载方法的资料字段合同冲突。")
            properties[key] = value
        required.update(schema.get("required", ()))
    return {"type": "object", "properties": properties, "required": sorted(required),
            "additionalProperties": False, "$defs": schemas[0]["$defs"]}


def production():
    value = os.environ.get("PDOS_ENVIRONMENT", "development")
    if value not in {"development", "test", "production"}:
        raise DomainError("VALIDATION_FAILED", "运行环境须明确为开发、测试或生产。")
    return value == "production"


def project(value, schema):
    omitted = []

    def walk(current, node, path):
        if "$ref" in node:
            prefix = "#/$defs/"
            reference = node["$ref"]
            if not reference.startswith(prefix) or reference[len(prefix):] not in schema["$defs"]:
                raise ValueError("Only local context schema references are supported")
            node = schema["$defs"][reference[len(prefix):]]
        if isinstance(current, dict) and "properties" in node:
            result = {}
            for key, child in current.items():
                pointer = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key not in node["properties"] and node.get("additionalProperties") is False:
                    omitted.append({"field": pointer, "reason": "outside_skill_context_schema"})
                else:
                    result[key] = walk(child, node["properties"].get(key, {}), pointer)
            return result
        if isinstance(current, list) and "items" in node:
            return [walk(child, node["items"], path + f"/{index}")
                    for index, child in enumerate(current)]
        return deepcopy(current)

    projected = walk(value, schema, "")
    errors = sorted(Draft202012Validator(schema).iter_errors(projected),
                    key=lambda error: str(list(error.absolute_path)))
    issues = [{"field": "/" + "/".join(map(str, error.absolute_path)),
               "reason": "context_" + error.validator} for error in errors]
    return projected, omitted, issues


def snapshot(store, scope, *, value, schema, bindings, omitted, issues):
    from .execution import validate_skill_load
    from .models import AgentEvent

    is_production = production()
    rejected = bool(issues) or bool(omitted and not is_production)
    metadata = {
        "schema_digest": digest(schema), "content_digest": digest(value),
        "skills": [binding.model_dump(mode="json") for binding in bindings],
        "fields": sorted(value) if isinstance(value, dict) else [],
        "omitted": omitted, "issues": issues,
    }
    identity = digest(metadata)
    with store.transaction(scope, lock=True) as (session, run):
        for binding in bindings:
            validate_skill_load(session, scope, binding)
        saved = run.versions.get("context_snapshots", {})
        existing = saved.get(identity)
        if existing is None:
            event_id = uuid4()
            sequence = session.scalar(select(func.coalesce(func.max(AgentEvent.sequence), 0))
                                      .where(AgentEvent.run_id == run.id)) + 1
            session.add(AgentEvent(id=event_id, tenant_id=scope.tenant_id, run_id=run.id,
                sequence=sequence, body={"type": "context_projected", **metadata,
                    "status": "rejected" if rejected else "projected"}))
            if not rejected:
                run.versions = {**run.versions, "context_snapshots": {**saved, identity: {
                    "event_id": str(event_id), **metadata,
                    "read_set": deepcopy(run.read_sources),
                    "scope": {"category_id": str(scope.category_id) if scope.category_id else None,
                        "product_id": str(scope.product_id) if scope.product_id else None,
                        **({"project_id": str(scope.project_id)}
                           if getattr(scope, "project_id", None) else {}),
                        "proposal_id": str(scope.proposal_id) if scope.proposal_id else None,
                        "requester_id": str(scope.requester_id),
                        "data_categories": sorted(run.data_categories)},
                    "source_digest": digest([run.read_sources,
                        run.versions.get("proposal_context"),
                        run.versions.get("conversation_memory_digest")]),
                }}}
        else:
            event_id = existing["event_id"]
    if rejected:
        raise DomainError("VALIDATION_FAILED", "当前方法的资料合同不匹配，已保留字段核对原因。",
                          detail={"reason": "context_schema_mismatch", "fields": omitted + issues})
    return str(event_id)


def check_messages(store, scope, messages, bindings):
    """Verify server context envelopes without interpreting model or raw tool text."""
    loaded = {binding.key: binding.model_dump(mode="json") for binding in bindings}
    envelopes, loading = [], set()
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            loading.update(call["id"] for call in message.get("tool_calls", [])
                           if call.get("name") == "skill.load")
        if index == 0 or (message.get("role") == "tool"
                          and message.get("tool_call_id") in loading):
            try:
                envelope = json.loads(message["content"])
                envelopes.append((envelope["context_ref"], envelope["context"]))
            except (ValueError, TypeError, KeyError):
                # A failed skill.load is an error result, never a new context envelope.
                if index == 0:
                    raise DomainError(
                        "VERSION_CONFLICT", "原上下文缺少当前字段合同快照。",
                    ) from None
    with store.transaction(scope) as (_, run):
        saved = {value["event_id"]: value
                 for value in run.versions.get("context_snapshots", {}).values()}
        for reference, value in envelopes:
            entry = saved.get(reference)
            if entry is None or entry["content_digest"] != digest(value) or any(
                any(loaded.get(skill["key"], {}).get(key) != skill[key]
                    for key in ("key", "version", "digest")) for skill in entry["skills"]
            ):
                raise DomainError("SOURCE_STALE", "原资料快照与当前已加载方法不一致。")
