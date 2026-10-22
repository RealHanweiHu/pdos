"""Native Pilot declarations, never owner, resource, start or release proof.

StatisticsBasis fixes the declared original statistical wording. Only an actual
owner may bind it to a FixedPilotScope and real lot/sample/line material. The
criterion belongs to this Pilot; it is not a factory qualification policy.
"""

from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from pdos_next.domain.build_operational_facts.execution_scope import OperationalScope
from pdos_next.domain.manufacturing_baseline.schemas import Closed
from pdos_next.schemas.manufacturing_trials.contracts import (
    Key,
    PilotCreate,
    Ref,
    ResultRecord,
    Revision,
    Text,
)
from pdos_next.schemas.verification.contracts import SourceRef

CREATE_OPERATION = "npi.pilot.create"
RESULT_OPERATION = "npi.pilot.result.record"
CREATE_SUBJECT_TYPE = "pilot_run"
RESULT_SUBJECT_TYPE = "pilot_observation"
CREATE_EVENT = "pilot.created"
RESULT_EVENT = "pilot.results_recorded"
SCHEMA_VERSION = "pdos-native-pilot-v1"
Visibility = Literal["private", "category", "audience"]
Token = Annotated[str, Field(min_length=20, max_length=128)]
CriterionRevision = Annotated[int, Field(strict=True, ge=1, le=1)]


class StatisticsBasis(Closed):
    site: Text
    original_timezone: Key
    window_start: AwareDatetime
    window_end: AwareDatetime
    cohort_mode: Literal["entire_lot", "fixed_sampled_subset"]
    samples: tuple[Ref, ...] = ()
    statistics_basis_key: Key
    criterion_id: UUID
    criterion_revision: CriterionRevision = 1
    criterion_text: Text
    minimum_sample: Revision
    operation_key: Key
    operational_scope: OperationalScope | None = None
    source: SourceRef

    @field_validator("original_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("统计声明须保留有效IANA时区") from error
        return value

    @model_validator(mode="after")
    def fixed_declaration(self):
        if self.window_end <= self.window_start:
            raise ValueError("统计声明窗口须为正区间")
        if any(sample.kind != "sample" for sample in self.samples):
            raise ValueError("统计成员声明须引用Sample")
        if len({sample.id for sample in self.samples}) != len(self.samples):
            raise ValueError("同一单件及其续版不能重复声明")
        return self


class PilotCreatePayload(Closed):
    project_id: UUID
    details: PilotCreate
    statistics: StatisticsBasis | None = None
    visibility: Visibility = "private"
    confirmation_token: Token | None = None


class PilotResultPayload(Closed):
    pilot_id: UUID
    expected_pilot_revision: Revision
    record: ResultRecord
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def exact_expected_revision(self):
        if self.record.expected_pilot_revision != self.expected_pilot_revision:
            raise ValueError("原始观察与外层Pilot预期版本须完全一致")
        return self


def semantic(payload: PilotCreatePayload | PilotResultPayload):
    """Canonical typed defaults for saved/compared content, without a token.

    The live Command, original private key and request digest remain untouched.
    This projection is content normalization, never confirmation consumption.
    """
    if type(payload) not in (PilotCreatePayload, PilotResultPayload):
        raise TypeError("须先解析实际native Pilot payload")
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def json_snapshot(value):
    """Recursively normalize actual UUID/datetime/Decimal/model JSON material."""
    return to_jsonable_python(value)
