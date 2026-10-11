from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ENGINE_VERSION = "2.0.0"
DEFINITION_VERSION = "1.0"


class MetricValue(BaseModel):
    """Integers and ratios travel as decimal strings, never lossy JSON floats."""

    model_config = ConfigDict(extra="forbid")
    value: str | None = Field(pattern=r"^-?\d+(\.\d+)?$")
    unit: Literal["minor_currency", "count", "ratio"]
    quality: Literal["confirmed", "estimated", "unavailable"]
    unavailable_reason: str | None

    @model_validator(mode="after")
    def availability(self):
        if self.value is None:
            if self.quality != "unavailable" or not self.unavailable_reason:
                raise ValueError("Missing metric values require a reason")
        elif self.quality == "unavailable" or self.unavailable_reason is not None:
            raise ValueError("Available metric cannot have an unavailable reason")
        return self


class MetricQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: UUID
    start: date
    end_exclusive: date
    comparison: Literal["previous", "custom", "none"] = "previous"
    compare_start: date | None = None
    compare_end_exclusive: date | None = None
    skus: list[str] = Field(default_factory=list, max_length=100)
    granularity: Literal["day", "week"] = "day"

    @field_validator("skus")
    @classmethod
    def canonical_skus(cls, values):
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("SKU must contain 1 to 128 characters")
        return sorted(set(values))

    @model_validator(mode="after")
    def periods(self):
        days = (self.end_exclusive - self.start).days
        if not 1 <= days <= 366 or not 1900 <= self.start.year <= self.end_exclusive.year <= 2100:
            raise ValueError("Period must be 1 to 366 calendar days within 1900–2100")
        if self.comparison == "previous":
            self.compare_start = self.start - timedelta(days=days)
            self.compare_end_exclusive = self.start
        elif self.comparison == "none":
            self.compare_start = self.compare_end_exclusive = None
        elif not self.compare_start or not self.compare_end_exclusive:
            raise ValueError("Custom comparison requires both dates")
        if self.compare_start and not (
            1 <= (self.compare_end_exclusive - self.compare_start).days <= 366
            and 1900 <= self.compare_start.year <= self.compare_end_exclusive.year <= 2100
        ):
            raise ValueError("Invalid comparison period")
        return self
