"""Synthetic data builders, used only by this test package."""


def ref(source_id="source", **changes):
    result = dict(
        source_id=source_id,
        version="v1",
        sha256="a" * 64,
        captured_at="2026-01-01T00:00:00Z",
        state="current",
    )
    result.update(changes)
    return result


def bom_item(identity="a", **changes):
    result = dict(
        item_id=identity,
        material_id="part",
        quantity_per_parent="2",
        unit="ea",
        loss_rate="0",
        supply_required=True,
        critical=True,
    )
    result.update(changes)
    return result


def pool(identity="stock", **changes):
    result = dict(
        key=dict(source_system="ERP", pool_id=identity, material_id="part"),
        ref=ref(identity),
        stage="on_hand",
        quantity="10",
        unit="ea",
        availability="available",
        quality="released",
    )
    result.update(changes)
    return result


def price(identity="price", **changes):
    result = dict(
        price_id=identity,
        subject_kind="material",
        subject_id="part",
        ref=ref(identity),
        stage="estimate",
        basis="unit",
        amount="0.10",
        price_quantity="1",
        unit="ea",
        currency="USD",
        tax_basis="exclusive",
        freight_basis="included",
        scope_assumption="Supplier estimate, materials only; no official ERP cost",
    )
    result.update(changes)
    return result
