"""Pure M3 arithmetic; inputs are assumptions, never access or qualification facts.

Amounts use decimal strings (or integers), never binary floating point. Results
are JSON-safe decimal strings with no money rounding. A Host must bind references
to its actual reads separately; accepting a Reference here proves no provenance.
Only a complete single-currency cost subtotal has a fixed ClaimContent
projection. It proves arithmetic over given inputs, never source truth.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, Inexact, localcontext
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictBool, model_validator

from pdos_next.domain.preproject.evidence_schemas import ClaimContent
from pdos_next.domain.preproject.schemas import Reference
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .deterministic_proofs import ComputeEngine

VERSION = "m3-calculators/v1"


def _decimal(value):
    if type(value) not in (str, int, Decimal):
        raise ValueError("Use a decimal string or integer, never float or bool")
    return value


Number = Annotated[
    Decimal,
    BeforeValidator(_decimal),
    Field(
        allow_inf_nan=False,
        max_digits=60,
        decimal_places=30,
        description="Exact decimal string or integer; float and bool are rejected",
    ),
]
Nonnegative = Annotated[Number, Field(ge=0)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Label = Annotated[str, Field(min_length=1)]


class Interval(StrictModel):
    low: Nonnegative
    high: Nonnegative

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class MarketSegment(StrictModel):
    name: Label
    quantity: Interval | None = None
    population: Interval | None = None
    penetration: Interval | None = None
    price: Interval | None = None
    currency: Currency | None = None
    basis: Label | None = None
    as_of: date | None = None
    source_refs: list[Reference] = Field(default_factory=list)
    assumptions: list[Label] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_quantity_method(self):
        if self.quantity is not None and (
            self.population is not None or self.penetration is not None
        ):
            raise ValueError("Choose quantity or population × penetration")
        if self.penetration is not None and self.penetration.high > 1:
            raise ValueError("Penetration is a fraction between zero and one")
        return self


class MarketSizeInput(StrictModel):
    segments: list[MarketSegment]


class Criterion(StrictModel):
    key: Label
    weight: Nonnegative | None = None
    score: Number | None = None
    rationale: Label | None = None
    source_refs: list[Reference] = Field(default_factory=list)
    weight_source_refs: list[Reference] = Field(default_factory=list)
    weight_rationale: Label | None = None


class OpportunityScoreInput(StrictModel):
    """Total is sum(weight × score); weights are never supplied or normalized for you."""

    criteria: list[Criterion]

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [row.key for row in self.criteria]
        if len(keys) != len(set(keys)):
            raise ValueError("Criterion keys must be unique")
        return self


class FxRate(StrictModel):
    """A/B means one unit of A equals rate units of B; no inverse or cross rate."""

    pair: str = Field(pattern=r"^[A-Z]{3}/[A-Z]{3}$")
    rate: Annotated[Number, Field(gt=0)]
    as_of: date
    source_ref: Reference

    @model_validator(mode="after")
    def distinct_currencies(self):
        source, target = self.pair.split("/")
        if source == target:
            raise ValueError("An FX pair must name different currencies")
        return self


class CostLine(StrictModel):
    label: Label
    qty: Nonnegative | None = None
    unit_cost: Nonnegative | None = None
    currency: Currency | None = None
    as_of: date | None = None
    basis: Label | None = None
    source_ref: Reference | None = None


class CostSubtotalInput(StrictModel):
    lines: list[CostLine]
    fx: list[FxRate] = Field(default_factory=list)
    target_currency: Currency | None = None


PriceField = Literal[
    "currency",
    "observed_on",
    "price_type",
    "includes_tax",
    "includes_shipping",
    "channel",
    "region",
]
PRICE_FIELDS = (
    "currency",
    "observed_on",
    "price_type",
    "includes_tax",
    "includes_shipping",
    "channel",
    "region",
)


class PricePoint(StrictModel):
    amount: Nonnegative | None = None
    currency: Currency | None = None
    observed_on: date | None = None
    price_type: Label | None = None
    includes_tax: StrictBool | None = None
    includes_shipping: StrictBool | None = None
    channel: Label | None = None
    region: Label | None = None
    source_ref: Reference | None = None


class PriceBandInput(StrictModel):
    price_points: list[PricePoint]
    bands: list[Interval] = Field(default_factory=list)
    quantiles: list[Annotated[Number, Field(ge=0, le=1)]] = Field(default_factory=list)
    group_by: list[PriceField] = Field(default_factory=lambda: list(PRICE_FIELDS))
    fx: list[FxRate] = Field(default_factory=list)
    target_currency: Currency | None = None

    @model_validator(mode="after")
    def explicit_statistics(self):
        if bool(self.bands) == bool(self.quantiles):
            raise ValueError("Provide either explicit bands or explicit quantiles")
        if len(set(self.quantiles)) != len(self.quantiles):
            raise ValueError("Quantiles must be unique")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by fields must be unique")
        for index, band in enumerate(self.bands):
            if band.low == band.high:
                raise ValueError("Bands must have positive width")
            if index and self.bands[index - 1].high > band.low:
                raise ValueError("Bands must be ordered and non-overlapping")
        return self


SCHEMAS = {
    "calc.market_size": MarketSizeInput,
    "calc.opportunity_score": OpportunityScoreInput,
    "calc.cost_subtotal": CostSubtotalInput,
    "calc.price_band": PriceBandInput,
}


def _json(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _row(model, index):
    return {"input_index": index, **model.model_dump(mode="json")}


def _sum_known(values):
    # sum([]) = 0 would turn an entirely unknown amount into an invented zero.
    return sum(values, Decimal(0)) if values else None


def _status(rows):
    known = sum(row["availability"] == "known" for row in rows)
    return "known" if rows and known == len(rows) else "partial" if known else "unknown"


def _groups(rows, fields, amount_keys):
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row[field] for field in fields)].append(row)
    result = []
    for key, items in grouped.items():
        status = _status(items)
        result.append(
            {
                **dict(zip(fields, key, strict=True)),
                "availability": status,
                "count": len(items),
                "items": items,
                **{
                    amount: _sum_known([row[amount] for row in items if row[amount] is not None])
                    if status == "known"
                    else None
                    for amount in amount_keys
                },
                "known_subtotal": {
                    amount: _sum_known([row[amount] for row in items if row[amount] is not None])
                    for amount in amount_keys
                },
            }
        )
    return result


def _market_size(payload):
    rows = []
    for index, segment in enumerate(payload.segments):
        row = _row(segment, index)
        missing = [field for field in ("price", "currency") if getattr(segment, field) is None]
        quantity_low = segment.quantity.low if segment.quantity is not None else None
        quantity_high = segment.quantity.high if segment.quantity is not None else None
        if segment.quantity is None:
            missing.extend(
                field for field in ("population", "penetration") if getattr(segment, field) is None
            )
            if segment.population is not None and segment.penetration is not None:
                quantity_low = segment.population.low * segment.penetration.low
                quantity_high = segment.population.high * segment.penetration.high
        low = quantity_low * segment.price.low if not missing else None
        high = quantity_high * segment.price.high if not missing else None
        row.update(
            availability="unknown" if missing else "known",
            missing=[f"missing_{field}" for field in missing],
            low=low,
            high=high,
        )
        rows.append(row)
    return {
        "availability": _status(rows),
        "groups": _groups(rows, ("currency", "basis", "as_of"), ("low", "high")),
        "segments": rows,
        "missing": [
            {"input_index": r["input_index"], "reasons": r["missing"]} for r in rows if r["missing"]
        ],
        "assumptions": [
            {
                "input_index": r["input_index"],
                "statements": r["assumptions"],
                "source_refs": r["source_refs"],
            }
            for r in rows
        ],
    }


def _opportunity_score(payload):
    rows = []
    for index, criterion in enumerate(payload.criteria):
        row = _row(criterion, index)
        missing = [field for field in ("weight", "score") if getattr(criterion, field) is None]
        row.update(
            availability="unknown" if missing else "known",
            missing=[f"missing_{field}" for field in missing],
            weighted_score=criterion.weight * criterion.score if not missing else None,
        )
        rows.append(row)
    known = _sum_known([r["weighted_score"] for r in rows if r["weighted_score"] is not None])
    status = _status(rows)
    return {
        "availability": status,
        "formula": "sum(weight * score); no implicit normalization",
        "total_score": known if status == "known" else None,
        "known_weighted_subtotal": known,
        "total_weight": _sum_known([c.weight for c in payload.criteria])
        if all(c.weight is not None for c in payload.criteria)
        else None,
        "criteria": rows,
        "missing": [
            {"input_index": r["input_index"], "reasons": r["missing"]} for r in rows if r["missing"]
        ],
        "advisory_only": True,
    }


def _convert(amount, currency, target, rates):
    if target is None:
        return None, None, None
    if currency == target:
        return amount, None, None
    matches = [rate for rate in rates if rate.pair == f"{currency}/{target}"]
    if len(matches) != 1:
        return None, None, "missing_fx" if not matches else "ambiguous_fx"
    rate = matches[0]
    return amount * rate.rate, rate.model_dump(mode="json"), None


def _cost_subtotal(payload):
    rows, converted = [], []
    for index, line in enumerate(payload.lines):
        row = _row(line, index)
        missing = [
            field for field in ("qty", "unit_cost", "currency") if getattr(line, field) is None
        ]
        amount = line.qty * line.unit_cost if not missing else None
        row.update(
            availability="unknown" if missing else "known",
            amount=amount,
            missing=[f"missing_{field}" for field in missing],
        )
        if payload.target_currency is not None:
            converted_amount, rate, reason = (
                _convert(amount, line.currency, payload.target_currency, payload.fx)
                if amount is not None
                else (None, None, "missing_line_amount")
            )
            row["conversion"] = {
                "amount": converted_amount,
                "currency": payload.target_currency,
                "fx": rate,
                "reason": reason,
            }
            converted.append(
                {
                    **row,
                    "original_currency": line.currency,
                    "currency": payload.target_currency,
                    "amount": converted_amount,
                    "availability": "known" if converted_amount is not None else "unknown",
                    "missing": [reason] if reason else [],
                }
            )
        rows.append(row)
    return {
        "availability": _status(rows),
        "lines": rows,
        "groups": _groups(rows, ("currency", "as_of", "basis"), ("amount",)),
        "converted_groups": _groups(converted, ("currency", "as_of", "basis"), ("amount",)),
        "missing": [
            {"input_index": r["input_index"], "reasons": r["missing"]} for r in rows if r["missing"]
        ],
    }


def _single_currency_claim(payload, input_digest):
    """Project only complete native-currency arithmetic; Host owns source checks."""
    required = ("qty", "unit_cost", "currency", "as_of", "source_ref")
    if not payload.lines or any(
        getattr(line, field) is None for line in payload.lines for field in required
    ):
        return None
    currencies = {line.currency for line in payload.lines}
    if len(currencies) != 1:
        return None
    subtotal = sum((line.qty * line.unit_cost for line in payload.lines), Decimal(0))
    dates = ", ".join(sorted({line.as_of.isoformat() for line in payload.lines}))
    # Reuse the domain DTO so all defaults and content fields match normalization.
    # A typed nonempty Reference is required, but its actual source/read binding
    # and whether its contents support these numbers must be verified by the Host.
    return ClaimContent(
        value=format(subtotal, "f"),
        unit=next(iter(currencies)),
        condition_note=(
            "给定输入的未折算成本小计（sum(qty × unit_cost)）；"
            f"原始计价日期：{dates}；输入摘要：{input_digest}。"
            "仅证明给定输入的算术结果；来源、数量和单价尚须核验，"
            "此投影不授予事实真实性、观察性质或执行资格。"
        ),
    ).model_dump(mode="json")


def _quantile(values, fraction):
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _price_band(payload):
    grouped, incomparable, conversions = defaultdict(list), [], []
    # Caller may request a smaller grouping, but may not erase frozen comparability fields.
    effective_group_by = list(dict.fromkeys([*payload.group_by, *PRICE_FIELDS]))
    for index, point in enumerate(payload.price_points):
        row = _row(point, index)
        missing = [field for field in ("amount", *PRICE_FIELDS) if getattr(point, field) is None]
        if missing:
            incomparable.append(
                {
                    **row,
                    "availability": "unknown",
                    "reasons": [f"missing_{field}" for field in missing],
                }
            )
            continue
        amount, currency = point.amount, point.currency
        if payload.target_currency is not None:
            converted, rate, reason = _convert(
                amount, currency, payload.target_currency, payload.fx
            )
            row["conversion"] = {
                "amount": converted,
                "currency": payload.target_currency,
                "fx": rate,
                "reason": reason,
            }
            if reason:
                conversions.append(
                    {"input_index": index, "reason": reason, "source_ref": row["source_ref"]}
                )
            else:
                amount, currency = converted, payload.target_currency
        row["effective_amount"], row["effective_currency"] = amount, currency
        key = tuple(currency if field == "currency" else row[field] for field in effective_group_by)
        grouped[key].append(row)
    groups = []
    for key, rows in grouped.items():
        values = sorted(row["effective_amount"] for row in rows)
        bands = [
            {
                "low": band.low,
                "high": band.high,
                "count": sum(band.low <= value < band.high for value in values),
            }
            for band in payload.bands
        ]
        groups.append(
            {
                **dict(zip(effective_group_by, key, strict=True)),
                "availability": "known",
                "count": len(rows),
                "min": values[0],
                "max": values[-1],
                "price_points": rows,
                "bands": bands,
                "out_of_band_count": len(rows) - sum(band["count"] for band in bands)
                if payload.bands
                else None,
                "quantiles": [
                    {"fraction": fraction, "value": _quantile(values, fraction)}
                    for fraction in payload.quantiles
                ],
            }
        )
    return {
        "availability": "partial" if groups and incomparable else "known" if groups else "unknown",
        "effective_group_by": effective_group_by,
        "band_boundary_rule": "low <= amount < high",
        "quantile_method": "linear interpolation at (n - 1) * fraction",
        "groups": groups,
        "incomparable_points": incomparable,
        "conversion_gaps": conversions,
        "unknown_count": len(incomparable),
    }


def calculate(name, arguments):
    """Validate and calculate without I/O or mutation of the caller's arguments."""
    payload = SCHEMAS[name].model_validate(arguments)
    input_digest = digest([name, arguments])
    with localcontext() as context:
        # Input bounds are 60 digits, at most 30 fractional places. Even the
        # population × penetration × price calculation is exact at this precision.
        context.prec = 512
        context.traps[Inexact] = True
        result = _CALCULATORS[name](payload)
        if name == "calc.cost_subtotal":
            claim = _single_currency_claim(payload, input_digest)
            result["proof_claims"] = (
                {"single_currency_subtotal": claim} if claim is not None else {}
            )
    return {
        "engine_version": VERSION,
        "input_digest": input_digest,
        **_json(result),
    }


_CALCULATORS = {
    "calc.market_size": _market_size,
    "calc.opportunity_score": _opportunity_score,
    "calc.cost_subtotal": _cost_subtotal,
    "calc.price_band": _price_band,
}


def market_size(arguments):
    return calculate("calc.market_size", arguments)


def opportunity_score(arguments):
    return calculate("calc.opportunity_score", arguments)


def cost_subtotal(arguments):
    return calculate("calc.cost_subtotal", arguments)


def price_band(arguments):
    return calculate("calc.price_band", arguments)


handlers = {
    "calc.market_size": market_size,
    "calc.opportunity_score": opportunity_score,
    "calc.cost_subtotal": cost_subtotal,
    "calc.price_band": price_band,
}
ENGINES = {
    name: ComputeEngine(
        VERSION,
        handler,
        (("proof_claims", "single_currency_subtotal"),) if name == "calc.cost_subtotal" else (),
    )
    for name, handler in handlers.items()
}
