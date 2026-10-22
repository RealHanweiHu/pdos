"""Decimal estimates from fixed BOM/process/price/rate snapshots; no business writes."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from .bom import expand_bom
from .common import calculation_context, digest, issue, sorted_issues, source_issues
from .coverage import _unique
from .dto import CostLine, CostRequest, CostResult
from .units import conversion

ZERO = Decimal(0)


def calculate_cost(request: CostRequest) -> CostResult:
    # BOM expansion uses its own exact bounded multiplication context. Division and money
    # use a separate fixed precision, independent of the host decimal configuration.
    expanded, base_issues = expand_bom(request.basis, request.as_of)
    with calculation_context(38):
        return _calculate(request, expanded, base_issues)


def _calculate(request, expanded, base_issues):
    problems = list(base_issues)
    sensitive = []
    prices, price_conflicts, notes = _unique(request.prices, lambda row: row.price_id, "prices")
    problems.extend(notes)
    rates, rate_conflicts, notes = _unique(request.rates, lambda row: row.rate_id, "rates")
    problems.extend(notes)
    by_pair = defaultdict(list)
    for rate in rates.values():
        by_pair[(rate.from_currency, rate.to_currency)].append(rate)
    quantity = request.basis.build.quantity
    lines = []

    def price_line(
        line_id, category, price_id, per_product, build_quantity, unit, notes, subject_id=None
    ):
        notes = list(notes)
        price = prices.get(price_id)
        original_currency = price.currency if price else None
        rate_id = None
        original_amount = None
        in_price_unit = None
        result = None
        if price is None:
            notes.append(issue("price_missing", line_id, "No selected price snapshot"))
        else:
            notes.extend(source_issues(price.ref, request.as_of, f"price:{price.price_id}"))
            if (
                price.subject_kind != category
                or category != "nre"
                and price.subject_id != subject_id
            ):
                notes.append(
                    issue(
                        "price_subject_mismatch",
                        line_id,
                        "Price is not bound to the selected material/operation/fee",
                        "conflict",
                    )
                )
            if category != "nre" and subject_id is None:
                notes.append(
                    issue(
                        "price_subject_unknown",
                        line_id,
                        "Material or operation identity is unknown",
                    )
                )
            if price_id in price_conflicts:
                notes.append(
                    issue("price_conflict", line_id, "Conflicting price versions", "conflict")
                )
            if price.basis != ("nre" if category == "nre" else "unit"):
                notes.append(
                    issue(
                        "price_basis_mismatch",
                        line_id,
                        "Price basis differs from selected cost line",
                        "conflict",
                    )
                )
            if price.amount is None or price.price_quantity is None:
                notes.append(
                    issue("price_amount_unknown", line_id, "Amount or price denominator is unknown")
                )
            if price.currency is None:
                notes.append(issue("price_currency_unknown", line_id, "Currency is unknown"))
            if category == "nre":
                factor = Decimal(1)
                if price.price_quantity != 1 or price.unit not in {"item", "项"}:
                    notes.append(
                        issue(
                            "nre_unit_mismatch",
                            line_id,
                            "NRE must be one explicit whole item",
                            "conflict",
                        )
                    )
            else:
                factor = conversion(unit, price.unit)
                if factor is None:
                    notes.append(
                        issue(
                            "price_unit_incomparable",
                            line_id,
                            "Price and quantity units cannot be converted",
                        )
                    )
            if build_quantity is None:
                notes.append(
                    issue(
                        "cost_quantity_unknown",
                        line_id,
                        "Required quantity is unknown; no zero assumption",
                    )
                )
            if factor is not None and build_quantity is not None:
                in_price_unit = build_quantity * factor
            if price.stage == "quote":
                if (
                    price.valid_from is None
                    or price.valid_until is None
                    or not price.valid_from <= request.as_of < price.valid_until
                ):
                    notes.append(
                        issue(
                            "quote_not_valid",
                            line_id,
                            "Quotation lacks an applicable explicit validity interval",
                        )
                    )
                if (
                    price.minimum_quantity is None
                    or in_price_unit is None
                    or in_price_unit < price.minimum_quantity
                    or price.maximum_quantity is not None
                    and in_price_unit > price.maximum_quantity
                ):
                    notes.append(
                        issue(
                            "quote_quantity_not_applicable",
                            line_id,
                            "Converted demand is outside the quotation quantity tier",
                        )
                    )
                sensitive.append(
                    issue(
                        "quote_quantity_tier",
                        line_id,
                        "Build quantity and loss may change quote applicability",
                        "sensitivity",
                    )
                )
            if price.tax_basis == "unknown":
                notes.append(issue("tax_basis_unknown", line_id, "Tax basis is unknown"))
            elif price.tax_basis != request.scope.tax_basis and price.tax_rate is None:
                notes.append(
                    issue(
                        "tax_rate_missing",
                        line_id,
                        "Missing tax rate for requested tax-basis conversion",
                    )
                )
            if price.freight_basis != request.scope.freight_basis:
                notes.append(
                    issue(
                        "freight_basis_mismatch",
                        line_id,
                        "Freight basis is unknown or differs; unpriced freight is not zero",
                    )
                )
            rate = None
            if price.currency is not None and price.currency != request.scope.currency:
                candidates = by_pair[(price.currency, request.scope.currency)]
                if len(candidates) != 1:
                    notes.append(
                        issue(
                            "exchange_rate_missing_or_ambiguous",
                            line_id,
                            "Select one explicit direct exchange rate for this currency",
                        )
                    )
                else:
                    rate = candidates[0]
                    rate_id = rate.rate_id
                    rate_notes = source_issues(rate.ref, request.as_of, f"rate:{rate.rate_id}")
                    age = request.as_of - rate.ref.captured_at
                    if (
                        rate.rate_id in rate_conflicts
                        or rate.rate is None
                        or rate.purpose != request.scope.rate_purpose
                        or age < timedelta(0)
                        or age > timedelta(days=request.scope.max_rate_age_days)
                    ):
                        rate_notes.append(
                            issue(
                                "exchange_rate_not_applicable",
                                line_id,
                                "Rate value, purpose, age or version is invalid",
                            )
                        )
                    notes.extend(rate_notes)
                    sensitive.append(
                        issue(
                            "exchange_rate",
                            line_id,
                            f"Uses {rate.rate_id} ({rate.purpose}) at fixed source time",
                            "sensitivity",
                        )
                    )
            if not notes:
                original_amount = price.amount / price.price_quantity * in_price_unit
                result = original_amount
                if price.tax_basis != request.scope.tax_basis:
                    divisor = 1 + price.tax_rate
                    result = (
                        result / divisor
                        if request.scope.tax_basis == "exclusive"
                        else result * divisor
                    )
                if rate is not None:
                    result *= rate.rate
        problems.extend(notes)
        return CostLine(
            line_id=line_id,
            category=category,
            price_id=price_id,
            quantity_per_product=per_product,
            quantity_for_build=build_quantity,
            demand_unit=unit,
            quantity_in_price_unit=in_price_unit,
            original_currency=original_currency,
            original_build_amount=original_amount,
            rate_id=rate_id,
            per_product_candidate=result / quantity
            if result is not None and category != "nre" and quantity is not None
            else None,
            build_candidate=result,
            issues=sorted_issues(notes),
        )

    items = {item.item_id: item for item in request.basis.bom.items}
    demands = {line.item_id: line for line in expanded}
    selection_counts = Counter(row.bom_item_id for row in request.material_prices)
    selected = set(selection_counts)
    overlapping = set()
    for identity in selected:
        if identity in demands:
            ancestors = set(demands[identity].ancestry) & selected
            if ancestors:
                overlapping |= ancestors | {identity}
    for identity in sorted(selected):
        selection = sorted(
            (row for row in request.material_prices if row.bom_item_id == identity),
            key=lambda row: row.price_id,
        )[0]
        demand = demands.get(identity)
        notes = list(demand.issues) if demand else []
        if demand is None:
            notes.append(
                issue("cost_bom_item_missing", identity, "Selected item is absent from BOM")
            )
        if selection_counts[identity] > 1:
            notes.append(
                issue(
                    "duplicate_material_price",
                    identity,
                    "One BOM item was selected more than once",
                    "conflict",
                )
            )
        if identity in overlapping:
            notes.append(
                issue(
                    "overlapping_material_prices",
                    identity,
                    "Parent package and child would count the same material twice",
                    "conflict",
                )
            )
        lines.append(
            price_line(
                f"material:{identity}",
                "material",
                selection.price_id,
                demand.quantity_per_product if demand else None,
                demand.required_quantity if demand else None,
                demand.unit if demand else None,
                notes,
                subject_id=demand.material_id if demand else None,
            )
        )
        if demand:
            for node_id in (identity, *demand.ancestry):
                if items[node_id].loss_rate:
                    sensitive.append(
                        issue(
                            "material_loss_uplift",
                            node_id,
                            "Demand multiplies each ancestor's (1 + loss_rate)",
                            "sensitivity",
                        )
                    )
    parents = {row.parent_item_id for row in items.values() if row.parent_item_id is not None}
    for identity in sorted(set(items) - parents):
        if identity not in selected and not set(demands[identity].ancestry) & selected:
            notes = [issue("unpriced_bom_item", identity, "BOM leaf has no selected package/price")]
            lines.append(
                price_line(
                    f"material:{identity}",
                    "material",
                    None,
                    demands[identity].quantity_per_product,
                    demands[identity].required_quantity,
                    items[identity].unit,
                    notes,
                    subject_id=items[identity].material_id,
                )
            )

    if request.scope.coverage == "materials_and_process":
        if request.process is None or not request.process.operations:
            problems.append(
                issue("process_missing", "process", "Required process snapshot is missing")
            )
        else:
            operations, operation_conflicts, notes = _unique(
                request.process.operations, lambda row: row.operation_id, "process"
            )
            problems.extend(notes)
            process_notes = source_issues(request.process.ref, request.as_of, "process")
            for identity, operation in sorted(operations.items()):
                notes = list(process_notes) + list(base_issues)
                if identity in operation_conflicts:
                    notes.append(
                        issue(
                            "process_operation_conflict",
                            identity,
                            "Conflicting versions of one operation",
                            "conflict",
                        )
                    )
                if operation.quantity_per_product is None or operation.loss_rate is None:
                    notes.append(
                        issue(
                            "process_quantity_unknown",
                            identity,
                            "Process quantity or loss uplift is unknown",
                        )
                    )
                per_product = (
                    operation.quantity_per_product * (1 + operation.loss_rate)
                    if operation.quantity_per_product is not None
                    and operation.loss_rate is not None
                    else None
                )
                if operation.loss_rate:
                    sensitive.append(
                        issue(
                            "process_loss_uplift",
                            identity,
                            "Uses explicit per-good-product quantity times (1 + loss)",
                            "sensitivity",
                        )
                    )
                lines.append(
                    price_line(
                        f"process:{identity}",
                        "process",
                        operation.price_id,
                        per_product,
                        per_product * quantity
                        if per_product is not None and quantity is not None
                        else None,
                        operation.unit,
                        notes,
                        subject_id=identity,
                    )
                )
    elif request.process is not None:
        problems.append(
            issue(
                "process_outside_scope",
                "process",
                "A process snapshot was supplied to materials-only scope",
                "conflict",
            )
        )

    if request.scope.nre_policy == "excluded":
        if request.nre_price_ids or request.scope.nre_volume is not None:
            problems.append(
                issue(
                    "nre_policy_conflict",
                    "nre",
                    "Excluded NRE scope has NRE selections or an allocation volume",
                    "conflict",
                )
            )
    else:
        if not request.nre_price_ids:
            problems.append(
                issue("nre_missing", "nre", "NRE was requested but no price was selected")
            )
        counts = Counter(request.nre_price_ids)
        fee_counts = Counter(
            prices[identity].subject_id for identity in counts if identity in prices
        )
        for identity in sorted(counts):
            notes = []
            if counts[identity] > 1:
                notes.append(
                    issue(
                        "duplicate_nre_price",
                        identity,
                        "One NRE price cannot be counted twice",
                        "conflict",
                    )
                )
            if identity in prices and fee_counts[prices[identity].subject_id] > 1:
                notes.append(
                    issue(
                        "duplicate_nre_subject",
                        identity,
                        "Two prices cover the same whole NRE fee",
                        "conflict",
                    )
                )
            lines.append(
                price_line(f"nre:{identity}", "nre", identity, None, Decimal(1), "item", notes)
            )
        if request.scope.nre_policy == "amortize":
            if request.scope.nre_volume is None:
                problems.append(
                    issue("nre_volume_missing", "nre", "Explicit allocation volume required")
                )
            sensitive.append(
                issue("nre_volume", "nre", "Allocation volume changes unit estimate", "sensitivity")
            )
        elif request.scope.nre_volume is not None:
            problems.append(
                issue(
                    "nre_policy_conflict",
                    "nre",
                    "Separate NRE has an amortization volume",
                    "conflict",
                )
            )

    # A cycle can leave no leaves; it still cannot yield an empty complete total.
    if not any(line.category == "material" for line in lines):
        problems.append(issue("material_cost_empty", "bom", "No material cost lines in scope"))
    for demand in expanded:
        if any(note.kind == "conflict" for note in demand.issues):
            problems.extend(note for note in demand.issues if note.kind == "conflict")
    build_subtotal = sum(
        (
            line.build_candidate
            for line in lines
            if line.category != "nre" and line.build_candidate is not None
        ),
        ZERO,
    )
    nre_subtotal = sum(
        (
            line.build_candidate
            for line in lines
            if line.category == "nre" and line.build_candidate is not None
        ),
        ZERO,
    )
    complete = not problems
    unit_total = build_subtotal / quantity if complete and quantity is not None else None
    return CostResult(
        input_sha256=digest(request),
        input_snapshot=request,
        complete_in_selected_scope=complete,
        currency=request.scope.currency,
        known_build_subtotal=build_subtotal,
        known_nre_subtotal=nre_subtotal,
        per_product_candidate=unit_total,
        build_candidate=build_subtotal if complete else None,
        nre_candidate=nre_subtotal if complete and request.nre_price_ids else None,
        including_amortized_nre=unit_total + nre_subtotal / request.scope.nre_volume
        if complete and request.scope.nre_policy == "amortize"
        else None,
        lines=tuple(lines),
        issues=sorted_issues(problems),
        sensitive_items=sorted_issues(sensitive),
    )
