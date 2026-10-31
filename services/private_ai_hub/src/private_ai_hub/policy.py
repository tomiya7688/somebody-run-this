from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PolicyViolation(ValueError):
    """Raised when a requested value violates an administrator policy."""


class FeatureMode(StrEnum):
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"


@dataclass(frozen=True)
class FeatureDecision:
    mode: FeatureMode
    requested: bool
    effective: bool


def resolve_feature(mode: FeatureMode, requested: bool) -> FeatureDecision:
    if mode is FeatureMode.DISABLED:
        effective = False
    elif mode is FeatureMode.REQUIRED:
        effective = True
    else:
        effective = requested
    return FeatureDecision(mode=mode, requested=requested, effective=effective)


@dataclass(frozen=True)
class IntegerLimit:
    maximum: int | None = None
    minimum: int = 0

    def __post_init__(self) -> None:
        if self.minimum < 0:
            raise ValueError("minimum must be >= 0")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum")

    def clamp(self, requested: int) -> int:
        if requested < self.minimum:
            return self.minimum
        if self.maximum is not None and requested > self.maximum:
            return self.maximum
        return requested

    def require(self, requested: int) -> int:
        effective = self.clamp(requested)
        if effective != requested:
            raise PolicyViolation(
                f"requested value {requested} is outside allowed range "
                f"{self.minimum}..{self.maximum if self.maximum is not None else 'unbounded'}"
            )
        return requested
