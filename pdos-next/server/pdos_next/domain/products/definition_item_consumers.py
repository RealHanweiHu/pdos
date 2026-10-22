"""Preserve the content of definitions already consumed by a fixed reference.

The database predicate covers actual persisted consumers, including private rows:
Proposal baselines/sources/items/submissions; Definition parents and derivations;
Variant parents/effective definitions; project links/engineering configurations;
typed Definition references in Knowledge and specification sources; and computed
Claims whose actual calculation ledger pins a Definition input. Historical facts
remain consumers even after their current pointer advances. Ordinary tool reads,
Run metadata and prepared candidates alone do not freeze a draft.

Keep this boundary in the database: an ORM query under the editor's RLS cannot
prove the absence of another member's private consumer. The visible wrapper
authorizes the target and exposes only a boolean; the deferred write guard uses
the same private predicate. The caller holds the target Product/Definition locks.
"""

from sqlalchemy import text

from pdos_next.domain.preproject.access import fail


def ensure_unconsumed(session, ctx, definition, *, reverting=False):
    consumed = session.scalar(
        text(
            "SELECT m3_definition_fixed_consumed_visible("
            ":tenant,:category,:definition,:version)"
        ),
        {
            "tenant": ctx.tenant_id,
            "category": ctx.category_id,
            "definition": definition.id,
            "version": definition.revision,
        },
    )
    if consumed is None:
        fail("FORBIDDEN_SCOPE", "definition_not_readable", "固定定义已不可读。", 403)
    if consumed:
        fail(
            "UNDO_BLOCKED_BY_DEPENDENCY" if reverting else "VERSION_CONFLICT",
            "definition_consumed",
            "定义已被固定引用，请从该版创建后续草稿继续编辑。",
        )
