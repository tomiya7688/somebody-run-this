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


def resolve_feature(
    mode: FeatureMode | str,
    requested: bool,
) -> FeatureDecision:
    if not isinstance(requested, bool):
        raise PolicyViolation("feature request must be a boolean")
    try:
        resolved_mode = FeatureMode(mode)
    except (TypeError, ValueError) as exc:
        raise PolicyViolation(f"invalid feature mode: {mode!r}") from exc

    if resolved_mode is FeatureMode.DISABLED:
        effective = False
    elif resolved_mode is FeatureMode.REQUIRED:
        effective = True
    else:
        effective = requested
    return FeatureDecision(
        mode=resolved_mode,
        requested=requested,
        effective=effective,
    )


def _validate_integer(value: object, *, field: str, violation: bool) -> int:
    error_type = PolicyViolation if violation else ValueError
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{field} must be an integer")
    return value


@dataclass(frozen=True)
class IntegerLimit:
    maximum: int | None = None
    minimum: int = 0

    def __post_init__(self) -> None:
        minimum = _validate_integer(
            self.minimum, field="minimum", violation=False
        )
        if self.maximum is not None:
            maximum = _validate_integer(
                self.maximum, field="maximum", violation=False
            )
        else:
            maximum = None

        if minimum < 0:
            raise ValueError("minimum must be >= 0")
        if maximum is not None and maximum < minimum:
            raise ValueError("maximum must be >= minimum")

    def clamp(self, requested: int) -> int:
        value = _validate_integer(
            requested, field="requested value", violation=True
        )
        if value < self.minimum:
            return self.minimum
        if self.maximum is not None and value > self.maximum:
            return self.maximum
        return value

    def require(self, requested: int) -> int:
        value = _validate_integer(
            requested, field="requested value", violation=True
        )
        effective = self.clamp(value)
        if effective != value:
            raise PolicyViolation(
                f"requested value {value} is outside allowed range "
                f"{self.minimum}..{self.maximum if self.maximum is not None else 'unbounded'}"
            )
        return value
