"""Translate frozen Human exclusions through actual fixed citation identities.

Only a narrowing search filter leaves this module. It does not mint a citation,
read original content, widen scope, or replace a historical source with its head.
"""

from uuid import UUID

from pdos_next.errors import DomainError

from .schemas import SOURCE_TYPES


def excluded_sources(session, run, state):
    entries = state.get("exclusions", [])
    if not entries:
        return ()
    try:
        selected = [(entry["kind"], str(UUID(entry["id"]))) for entry in entries]
        if any(kind not in {"artifact", "citation"} for kind, _identity in selected):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise DomainError("VERSION_CONFLICT", "已保存的排除条件无法核对，请重新选择。") from None
    result = {("artifact", identity) for kind, identity in selected if kind == "artifact"}
    if any(kind == "citation" for kind, _identity in selected):
        from .assistant_inheritance import _aliases, registry

        # registry/aliases derive only the server-linked lineage and actual
        # completed root/read bindings, including IDs reissued to an ancestor.
        roots, rows = registry(session, run, include_self=True)
        aliases = _aliases(session, rows, roots)
        for kind, identity in selected:
            if kind != "citation":
                continue
            origin = roots.get(aliases.get(identity))
            if origin is None:
                raise DomainError("SOURCE_UNAVAILABLE", "排除的引用已无法从原讨论核对。")
            item = origin[1]
            try:
                source_type, source_id = item["source_type"], str(UUID(item["source_id"]))
                if source_type not in SOURCE_TYPES:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DomainError("SOURCE_UNAVAILABLE", "排除引用的固定来源无法核对。") from None
            result.add((source_type, source_id))
    return tuple(sorted(result))
