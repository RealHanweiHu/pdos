"""Verify an already-readable receipt's private request-key association.

The existing database function rechecks actual receipt/product/category access
under the caller's session and returns one boolean. It exposes no RequestKey
row and does not attest the surrounding domain, authority or saved group.
"""

from sqlalchemy import func, select


def receipt_request_binding_statement(tenant_id, product_id, receipt_id):
    return select(
        func.public.change_receipt_key_bound(tenant_id, product_id, receipt_id).label("bound")
    ).execution_options(autoflush=False, populate_existing=True)


def readable_receipt_request_bound(s, ctx, product_id, receipt_id):
    return (
        s.scalar(receipt_request_binding_statement(ctx.tenant_id, product_id, receipt_id)) is True
    )
