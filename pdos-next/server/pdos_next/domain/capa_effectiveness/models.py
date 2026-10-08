"""Register five fact tables on the shared declarative metadata."""

from .fact_storage_models import (
    NamedReviewRecord,
    ObservationCurrent,
    ObservationFact,
    RuleCurrent,
    RuleFact,
)

__all__ = ["NamedReviewRecord", "ObservationCurrent", "ObservationFact", "RuleCurrent", "RuleFact"]
