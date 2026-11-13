"""Which declared alternates of one BOM version carry a Build-level approval (P113).

A BOM line's alternate is a declaration only. The qualification is the T2
`supply.alternate.approve` record of the D47 branch, bound to Build + BOM
version + configuration (P96 第 5–7 项, AT-21). That record is not on this
branch yet, so the reader is not connected and the rule card says so instead
of guessing (D433: connect at integration once D47 lands).
"""

NOT_CONNECTED = None


def approved_alternates(s, ctx, product_id, bom_row):
    """Return {(line_key, alternate_part_id)} approved for a reader-visible Build that
    fixes this BOM version, or None while the approval records are not connected.

    D433 at integration: read `alternate_approval_currents` joined to its current
    version (state 'approved', not past valid_until) for Builds whose engineering
    configuration pins (bom_row.id, bom_row.revision), through the Build reads the
    page already uses, so only Builds the reader can see count.
    """
    return NOT_CONNECTED
