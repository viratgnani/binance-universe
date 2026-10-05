"""
research/models.py

Strongly-typed Pydantic models for Research Engine V1.

Model Hierarchy
---------------
  ResearchSpec          — the full specification of a research run
    EventDefinition     — what constitutes an event
    OutcomeDefinition   — what to measure after an event

  Event                 — one detected event instance
  EventOutcome          — one forward outcome for one event at one horizon
  ResearchResult        — complete output of a research run
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Operator(str, Enum):
    GT  = ">"
    GTE = ">="
    LT  = "<"
    LTE = "<="
    EQ  = "=="
    NEQ = "!="


class EventMode(str, Enum):
    CONDITION = "condition"
    CROSSING  = "crossing"


class EventPolicy(str, Enum):
    """
    For EventMode.CONDITION only.
    
    EVERY_OBSERVATION — emit an event for every observation that satisfies the condition.
    FIRST_ENTRY       — emit an event only on the first bar that satisfies the condition
                        after a bar that did NOT satisfy it (state-transition semantics).
    """
    EVERY_OBSERVATION = "every_observation"
    FIRST_ENTRY       = "first_entry"


class CrossingDirection(str, Enum):
    """
    For EventMode.CROSSING only.
    
    CROSS_UP   — previous valid obs: feature <= threshold; current: feature > threshold.
    CROSS_DOWN — previous valid obs: feature >= threshold; current: feature < threshold.
    ANY        — either direction.
    """
    CROSS_UP   = "cross_up"
    CROSS_DOWN = "cross_down"
    ANY        = "any"


class OutcomeStatus(str, Enum):
    VALID                  = "valid"
    INSUFFICIENT_FUTURE_DATA = "insufficient_future_data"
    MISSING_PRICE          = "missing_price"
    INVALID                = "invalid"

class OutcomeType(str, Enum):
    RETURN_LIKE     = "return_like"
    GENERIC_NUMERIC = "generic_numeric"


# ---------------------------------------------------------------------------
# EventDefinition
# ---------------------------------------------------------------------------

class ThresholdCondition(BaseModel):
    """A single feature threshold test."""
    feature_name: str
    operator: Operator
    threshold: float

    def evaluate(self, value: float) -> bool:
        """Return True if *value* satisfies this condition."""
        match self.operator:
            case Operator.GT:  return value > self.threshold
            case Operator.GTE: return value >= self.threshold
            case Operator.LT:  return value < self.threshold
            case Operator.LTE: return value <= self.threshold
            case Operator.EQ:  return value == self.threshold
            case Operator.NEQ: return value != self.threshold

    def below_or_equal(self, value: float) -> bool:
        """True when the value is on the non-triggered side of a cross_up."""
        return value <= self.threshold

    def above_or_equal(self, value: float) -> bool:
        """True when the value is on the non-triggered side of a cross_down."""
        return value >= self.threshold


class EventDefinition(BaseModel):
    """
    Defines what constitutes a research event.

    Mode: CONDITION
      Evaluate the condition against each bar's feature value.
      event_policy controls whether every qualifying bar or only the first-entry bar generates an event.

    Mode: CROSSING
      Detect a sign change across the threshold.
      crossing_direction controls which direction(s) are detected.
      None values in the feature series are skipped when tracking the previous state.

    Crossing semantics (exact):
      cross_up:   previous valid value <= threshold AND current value > threshold
      cross_down: previous valid value >= threshold AND current value < threshold
      any:        either of the above
    """
    condition: ThresholdCondition
    event_mode: EventMode = EventMode.CROSSING
    event_policy: EventPolicy = EventPolicy.EVERY_OBSERVATION
    crossing_direction: CrossingDirection = CrossingDirection.ANY

    @model_validator(mode="after")
    def _validate_consistency(self) -> "EventDefinition":
        if self.event_mode == EventMode.CROSSING and self.event_policy != EventPolicy.EVERY_OBSERVATION:
            raise ValueError("event_policy is only applicable to EventMode.CONDITION")
        return self

    def stable_hash(self) -> str:
        """Deterministic SHA-256 hash of the definition (used as idempotency key component)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# OutcomeDefinition
# ---------------------------------------------------------------------------

class OutcomeDefinition(BaseModel):
    """
    Defines one forward measurement.

    horizon_minutes: positive integer number of minutes after event timestamp.
    price_feature:   the FeatureRow field to use as price (e.g. "mid_price", "return_1m").
                     For forward return, this must be a price-level feature (not a return feature).

    Forward return formula:
      return(T, H) = price(T + H) / price(T) - 1

    Timestamp policy:
      The engine looks for an observation with timestamp == T + horizon exactly.
      If no exact match exists:
        - If T + H is beyond the last available observation: insufficient_future_data
        - Otherwise: missing_price
      No nearest-neighbour substitution is performed.
    """
    name: str
    horizon_minutes: int = Field(..., gt=0, description="Forward horizon in minutes (must be > 0)")
    price_feature: str = Field("mid_price", description="FeatureRow field to use as price")
    outcome_type: OutcomeType = Field(OutcomeType.RETURN_LIKE, description="Semantic type of the outcome")

    @property
    def horizon(self) -> timedelta:
        return timedelta(minutes=self.horizon_minutes)


# ---------------------------------------------------------------------------
# ResearchSpec
# ---------------------------------------------------------------------------

class ResearchSpec(BaseModel):
    """
    Complete specification of a research run.
    Serialisable and deterministic — identical specs must produce identical results
    given identical stored data and engine version.
    """
    research_id: str = Field(..., description="Unique identifier for this research run")
    symbols: list[str] = Field(..., min_length=1)
    start_time: datetime
    end_time: datetime
    feature_version: str = Field("v1")
    engine_version: str = Field("research_v1")
    event_definition: EventDefinition
    outcome_definitions: list[OutcomeDefinition] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_time_range(self) -> "ResearchSpec":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    def stable_hash(self) -> str:
        """Deterministic hash of the entire spec."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event(BaseModel):
    """
    A single detected event instance.
    
    The timestamp is the point at which the event becomes observable —
    i.e. the bar at which the condition or crossing was satisfied.
    No observation with timestamp > event.timestamp was used in detection.
    """
    research_id: str
    symbol: str
    timestamp: datetime = Field(..., description="When this event became observable")
    event_definition_hash: str = Field(..., description="Stable hash of EventDefinition used")
    feature_name: str
    feature_value: float
    direction: CrossingDirection | None = Field(
        None,
        description="Set for crossing events (cross_up / cross_down). None for condition events."
    )

    def logical_key(self) -> tuple:
        """Idempotency key: (research_id, symbol, timestamp, event_definition_hash)."""
        return (self.research_id, self.symbol, self.timestamp, self.event_definition_hash)


# ---------------------------------------------------------------------------
# EventOutcome
# ---------------------------------------------------------------------------

class EventOutcome(BaseModel):
    """
    The realised forward outcome for one event at one horizon.

    The OutcomeEngine is explicitly allowed to access future data.
    outcome_value is None whenever status != valid.
    """
    research_id: str
    symbol: str
    event_timestamp: datetime
    event_definition_hash: str
    outcome_name: str
    horizon_minutes: int
    outcome_value: float | None = None
    outcome_timestamp: datetime | None = None
    status: OutcomeStatus

    def logical_key(self) -> tuple:
        """Idempotency key."""
        return (
            self.research_id, self.symbol,
            self.event_timestamp, self.event_definition_hash,
            self.outcome_name,
        )


# ---------------------------------------------------------------------------
# ResearchResult
# ---------------------------------------------------------------------------

class ResearchResult(BaseModel):
    """Complete output of a research run for one symbol."""
    research_id: str
    symbol: str
    feature_version: str
    engine_version: str
    events: list[Event]
    outcomes: list[EventOutcome]
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Statistics (Phase 2)
# ---------------------------------------------------------------------------

class SampleQuality(BaseModel):
    """Counts of raw outcome observations."""
    event_count: int
    valid_outcome_count: int
    missing_outcome_count: int
    insufficient_future_data_count: int
    invalid_outcome_count: int

    @property
    def N(self) -> int:
        """The number of valid numerical observations used in statistics."""
        return self.valid_outcome_count


class DescriptiveStats(BaseModel):
    """Central tendency and dispersion."""
    mean: float | None = None
    median: float | None = None
    std: float | None = Field(None, description="Sample standard deviation (ddof=1)")
    min: float | None = None
    max: float | None = None


class ReturnStats(BaseModel):
    """Semantics strictly applicable to return_like outcomes."""
    win_rate: float | None = Field(None, description="count(x > 0) / N")
    positive_count: int | None = None
    negative_count: int | None = None
    zero_count: int | None = None
    mean_positive: float | None = None
    mean_negative: float | None = None
    largest_gain: float | None = None
    largest_loss: float | None = None


class Quantiles(BaseModel):
    """Explicitly computed quantiles."""
    p01: float | None = None
    p05: float | None = None
    p10: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class StatisticsResult(BaseModel):
    """
    A single deterministic statistical summary of an outcome population.
    """
    research_id: str
    statistics_version: str = Field("v1")
    
    # Grouping keys (None if representing 'overall' or another aggregated dimension)
    symbol: str | None = None
    horizon: str | None = None
    grouping_type: str = Field(..., description="e.g. 'overall', 'symbol', 'horizon', 'symbol_horizon'")
    
    outcome_name: str
    outcome_type: OutcomeType

    sample: SampleQuality
    descriptive: DescriptiveStats
    returns: ReturnStats | None = None
    quantiles: Quantiles

    def logical_key(self) -> tuple:
        """Idempotency key for storage."""
        return (
            self.research_id,
            self.grouping_type,
            self.symbol or "ALL",
            self.horizon or "ALL",
            self.outcome_name
        )
