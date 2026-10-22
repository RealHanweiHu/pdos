"""Thin auxiliary proposal adapter; the actual shared tail owns its sole receipt."""

from pdos_next import change_selection_service as owner
from pdos_next.change_controlled_store import ChangeSelectionFact
from pdos_next.change_order_service import _one

semantic = owner.semantic
validate = owner.validate
inputs = owner.inputs
bind_consumption = owner.bind_consumption
record_consumption = owner.record_consumption
prepare_write_review = owner.prepare_write_review
apply = owner.apply
deduplicate_subject = owner.deduplicate_subject
configure = owner.configure


def prepare_preview(s, ctx, command, product, payload):
    owner.owner.require(
        command.product_id == product.id and command.expected_revision == product.revision,
        "VERSION_CONFLICT",
    )
    return owner._read(s, ctx, command, payload, new_write=True)[0]


def preview_prepared(s, ctx, command, product, payload, phase):
    return owner.review(phase)


def preview_view(s, ctx, command, product, payload):
    return preview_prepared(
        s, ctx, command, product, payload, prepare_preview(s, ctx, command, product, payload)
    )


def apply_prepared_write(s, ctx, command, product, payload, phase, *, consumption):
    row = owner.apply_prepared_write(
        s, ctx, command, product, payload, phase, consumption=consumption
    )
    return row, owner.FAMILY, row.visibility


def replay_subject(s, ctx, command, product, payload):
    identity = owner.replay_subject(s, ctx, command, payload)
    if identity is None:
        return None
    return _one(
        s,
        ChangeSelectionFact,
        ChangeSelectionFact.tenant_id == ctx.tenant_id,
        ChangeSelectionFact.product_id == product.id,
        ChangeSelectionFact.id == identity,
    )


def replay_subject_type(payload):
    return owner.FAMILY
