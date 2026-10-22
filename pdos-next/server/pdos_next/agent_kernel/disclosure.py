"""Per-call tool disclosure derived from the one registry; only the server authors it.

A loaded skill already decides which write commands 小Pai may *call*
(``ToolRegistry.authorize``). Disclosure applies the same server fact one step
earlier, to what it may *see*: an undisclosed command never reaches the model's
context instead of being refused after it asks. Both sides read the same
``ToolSpec.requires_loaded_skill``, so visibility cannot drift from callability.

Anything callable without a loaded skill therefore stays disclosed: reads,
research, compute, and T2 preparation. Narrowing those would remove capability
rather than payload. What a run stops seeing is exactly the set it would have
been refused for asking.

Nothing here reads model output. Callers pass the operation names the server
itself resolved from verified SkillBindings, never a set the model proposed.
Order follows ``ToolRegistry.definitions`` (sorted by name) so the digest of a
disclosure is stable across worker processes.
"""

from collections.abc import Iterable, Mapping

from pdos_next.errors import DomainError

# Always disclosed: without it 小Pai could never ask for a skill to be loaded.
CORE = frozenset({"skill.load"})


def _ordered(registry, isolation):
    """The isolation's full disclosable list, in the registry's own order."""
    return registry.definitions(isolation)


def skill_operations(skills: Iterable) -> frozenset[str]:
    """Union the ``operations`` of already-resolved skills.

    Takes Skill objects the caller loaded from the catalog for the current
    scope, not keys from the model and not raw ``allowed_operations`` metadata.
    """
    names: set[str] = set()
    for skill in skills:
        operations = getattr(skill, "operations", None)
        if operations is None or isinstance(operations, (str, bytes, Mapping)):
            raise DomainError("VALIDATION_FAILED", "技能操作集合须来自已解析的技能包。")
        for name in operations:
            if not isinstance(name, str) or not name:
                raise DomainError("VALIDATION_FAILED", "技能操作名须为登记的工具名。")
            names.add(name)
    return frozenset(names)


def disclosure(registry, isolation="main", operations: Iterable[str] = ()):
    """Return the tool definitions this model call may see, in registry order.

    ``operations`` is the union of the loaded skills' allowed operations. An
    operation that this isolation may not disclose at all (an isolated
    original-text read, say) is skipped rather than widening the child's list;
    ``ToolRegistry.definitions`` remains the only source of what is disclosable.
    """
    if isinstance(operations, (str, bytes, Mapping)):
        raise DomainError("VALIDATION_FAILED", "披露须按操作名集合推导。")
    allowed = frozenset(operations or ())
    if any(not isinstance(name, str) or not name for name in allowed):
        raise DomainError("VALIDATION_FAILED", "技能操作名须为登记的工具名。")
    return [
        item
        for item in _ordered(registry, isolation)
        if item["name"] in CORE
        or not registry.get(item["name"]).requires_loaded_skill
        or item["name"] in allowed
    ]


def disclosed_names(registry, isolation="main", operations: Iterable[str] = ()):
    return tuple(item["name"] for item in disclosure(registry, isolation, operations))


def disclosure_digest(registry, isolation="main", operations: Iterable[str] = ()):
    """Digest of this call's disclosure, comparable with the recorded binding.

    Deliberately ``digest`` of the same definition list the gateway sends, so a
    run whose loaded skills cover every write tool keeps today's digest.
    """
    # Deferred like Skill.digest: pdos_next.service imports this module through
    # contracts -> snapshot_command, so a module-level import would be circular.
    from pdos_next.service import digest

    return digest(disclosure(registry, isolation, operations))


def binding_operations(catalog, bindings: Iterable):
    """Operations the skills recorded on a model binding allowed, at their pinned version.

    Re-derives from the catalog instead of trusting a stored operation list, so a
    skill file edited after the call is a ``VERSION_CONFLICT`` rather than a
    silently wider disclosure. Enablement stays with ``validate_skill_load`` and
    ``ToolRegistry.authorize``; this answers only what the call could see.
    """
    skills = []
    for binding in bindings:
        skill = catalog.configuration(getattr(binding, "key", None))
        if (
            skill is None
            or skill.version != getattr(binding, "version", None)
            or skill.digest != getattr(binding, "digest", None)
        ):
            raise DomainError("VERSION_CONFLICT", "原已加载技能内容或版本已变化。")
        skills.append(skill)
    return skill_operations(skills)


CHAIN_KEY = "tool_disclosures"


def record_disclosure(versions: Mapping, isolation: str, names: Iterable[str], value: str):
    """Return the versions patch for one call's disclosure, enforcing growth.

    The run keeps the latest digest where it always kept it, plus an append-only
    chain so an earlier model call's narrower disclosure stays verifiable after a
    skill load widens it. Nothing is ever removed or rewritten.
    """
    chain = dict(versions.get(CHAIN_KEY) or {})
    entry = dict(chain.get(isolation) or {})
    current = tuple(names)
    check_growth(entry.get("names") or (), current)
    digests = list(entry.get("chain") or ())
    if value not in digests:
        digests.append(value)
    chain[isolation] = {"names": list(current), "chain": digests}
    return chain


def disclosed_in_run(versions: Mapping, isolation: str, value: str):
    """Whether this digest was a disclosure this run actually made.

    Accepts the run's current disclosure and any earlier one in the chain: a run
    that loaded a skill mid-way must not invalidate the proofs of the calls it
    already made under the narrower list.
    """
    if not isinstance(versions, Mapping):
        return False
    latest = (versions.get("tool_definitions") or {}).get(isolation)
    if value and value == latest:
        return True
    entry = (versions.get(CHAIN_KEY) or {}).get(isolation) or {}
    return bool(value) and value in tuple(entry.get("chain") or ())


def check_growth(previous: Iterable[str], current: Iterable[str]):
    """Disclosure may only grow within a run, and only by loading skills.

    A shrinking or diverging list would let a later call claim a narrower
    surface than the one an earlier reply was actually produced against.
    """
    before, after = frozenset(previous or ()), frozenset(current or ())
    if not before <= after:
        raise DomainError(
            "VERSION_CONFLICT",
            "原运行已披露的工具不能收回或替换。",
            detail={"reason_key": "disclosure_not_monotonic"},
        )
    return tuple(sorted(after - before))
