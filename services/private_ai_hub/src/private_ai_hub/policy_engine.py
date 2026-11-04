from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from .policy import FeatureMode, IntegerLimit, PolicyViolation


POLICY_ENGINE_VERSION = 1


class PolicyErrorCode(StrEnum):
    POLICY_CONFLICT = "policy_conflict"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    VALUE_OUT_OF_RANGE = "value_out_of_range"
    VALUE_NOT_ALLOWED = "value_not_allowed"


class LimitBehavior(StrEnum):
    CLAMP = "clamp"
    REJECT = "reject"


@dataclass(frozen=True)
class PolicyReason:
    code: str
    source: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PolicySourceRevision:
    source: str
    revision: int

    def to_dict(self) -> dict[str, object]:
        return {"source": self.source, "revision": self.revision}


@dataclass(frozen=True)
class PolicyLayer:
    name: str
    revision: int
    features: Mapping[str, FeatureMode | str] = field(default_factory=dict)
    integer_limits: Mapping[str, IntegerLimit] = field(default_factory=dict)
    allowed_values: Mapping[str, frozenset[str] | set[str] | tuple[str, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("policy layer name must be a non-empty string")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int):
            raise ValueError("policy layer revision must be an integer")
        if self.revision < 0:
            raise ValueError("policy layer revision must be >= 0")

        normalized_features: dict[str, FeatureMode] = {}
        for key, raw_mode in self.features.items():
            normalized_features[_policy_key(key)] = FeatureMode(raw_mode)

        normalized_limits: dict[str, IntegerLimit] = {}
        for key, limit in self.integer_limits.items():
            if not isinstance(limit, IntegerLimit):
                raise TypeError(f"integer limit for {key!r} must be IntegerLimit")
            normalized_limits[_policy_key(key)] = limit

        normalized_allowed: dict[str, frozenset[str]] = {}
        for key, values in self.allowed_values.items():
            policy_key = _policy_key(key)
            normalized = frozenset(_choice_value(value) for value in values)
            normalized_allowed[policy_key] = normalized

        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(
            self, "features", MappingProxyType(normalized_features)
        )
        object.__setattr__(
            self, "integer_limits", MappingProxyType(normalized_limits)
        )
        object.__setattr__(
            self, "allowed_values", MappingProxyType(normalized_allowed)
        )


@dataclass(frozen=True)
class PolicyCapabilities:
    features: Mapping[str, bool] = field(default_factory=dict)
    integer_maximums: Mapping[str, int] = field(default_factory=dict)
    choices: Mapping[str, frozenset[str] | set[str] | tuple[str, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        normalized_features: dict[str, bool] = {}
        for key, available in self.features.items():
            if not isinstance(available, bool):
                raise TypeError(f"feature capability for {key!r} must be boolean")
            normalized_features[_policy_key(key)] = available

        normalized_maximums: dict[str, int] = {}
        for key, maximum in self.integer_maximums.items():
            if isinstance(maximum, bool) or not isinstance(maximum, int):
                raise TypeError(f"integer capability for {key!r} must be integer")
            if maximum < 0:
                raise ValueError(f"integer capability for {key!r} must be >= 0")
            normalized_maximums[_policy_key(key)] = maximum

        normalized_choices: dict[str, frozenset[str]] = {}
        for key, values in self.choices.items():
            normalized_choices[_policy_key(key)] = frozenset(
                _choice_value(value) for value in values
            )

        object.__setattr__(
            self, "features", MappingProxyType(normalized_features)
        )
        object.__setattr__(
            self, "integer_maximums", MappingProxyType(normalized_maximums)
        )
        object.__setattr__(
            self, "choices", MappingProxyType(normalized_choices)
        )


@dataclass(frozen=True)
class PolicyRequest:
    features: Mapping[str, bool] = field(default_factory=dict)
    integers: Mapping[str, int] = field(default_factory=dict)
    choices: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_features: dict[str, bool] = {}
        for key, requested in self.features.items():
            if not isinstance(requested, bool):
                raise PolicyViolation(f"feature request for {key!r} must be boolean")
            normalized_features[_policy_key(key)] = requested

        normalized_integers: dict[str, int] = {}
        for key, requested in self.integers.items():
            if isinstance(requested, bool) or not isinstance(requested, int):
                raise PolicyViolation(f"integer request for {key!r} must be integer")
            normalized_integers[_policy_key(key)] = requested

        normalized_choices = {
            _policy_key(key): _choice_value(value)
            for key, value in self.choices.items()
        }

        object.__setattr__(
            self, "features", MappingProxyType(normalized_features)
        )
        object.__setattr__(
            self, "integers", MappingProxyType(normalized_integers)
        )
        object.__setattr__(
            self, "choices", MappingProxyType(normalized_choices)
        )


@dataclass(frozen=True)
class FeaturePolicyDecision:
    key: str
    requested: bool
    effective: bool
    permitted: bool
    denial_code: PolicyErrorCode | None
    reasons: tuple[PolicyReason, ...]
    source_revisions: tuple[PolicySourceRevision, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "requested": self.requested,
            "effective": self.effective,
            "permitted": self.permitted,
            "denial_code": self.denial_code.value if self.denial_code else None,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "source_revisions": [
                revision.to_dict() for revision in self.source_revisions
            ],
        }


@dataclass(frozen=True)
class IntegerPolicyDecision:
    key: str
    requested: int
    effective: int | None
    minimum: int
    maximum: int | None
    permitted: bool
    denial_code: PolicyErrorCode | None
    reasons: tuple[PolicyReason, ...]
    source_revisions: tuple[PolicySourceRevision, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "requested": self.requested,
            "effective": self.effective,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "permitted": self.permitted,
            "denial_code": self.denial_code.value if self.denial_code else None,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "source_revisions": [
                revision.to_dict() for revision in self.source_revisions
            ],
        }


@dataclass(frozen=True)
class ChoicePolicyDecision:
    key: str
    requested: str
    effective: str | None
    allowed_values: tuple[str, ...]
    permitted: bool
    denial_code: PolicyErrorCode | None
    reasons: tuple[PolicyReason, ...]
    source_revisions: tuple[PolicySourceRevision, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "requested": self.requested,
            "effective": self.effective,
            "allowed_values": list(self.allowed_values),
            "permitted": self.permitted,
            "denial_code": self.denial_code.value if self.denial_code else None,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "source_revisions": [
                revision.to_dict() for revision in self.source_revisions
            ],
        }


@dataclass(frozen=True)
class EffectivePolicySnapshot:
    engine_version: int
    feature_decisions: Mapping[str, FeaturePolicyDecision]
    integer_decisions: Mapping[str, IntegerPolicyDecision]
    choice_decisions: Mapping[str, ChoicePolicyDecision]
    source_revisions: tuple[PolicySourceRevision, ...]

    @property
    def permitted(self) -> bool:
        decisions = (
            list(self.feature_decisions.values())
            + list(self.integer_decisions.values())
            + list(self.choice_decisions.values())
        )
        return all(decision.permitted for decision in decisions)

    def to_dict(self) -> dict[str, object]:
        return {
            "engine_version": self.engine_version,
            "permitted": self.permitted,
            "source_revisions": [
                revision.to_dict() for revision in self.source_revisions
            ],
            "features": {
                key: decision.to_dict()
                for key, decision in self.feature_decisions.items()
            },
            "integers": {
                key: decision.to_dict()
                for key, decision in self.integer_decisions.items()
            },
            "choices": {
                key: decision.to_dict()
                for key, decision in self.choice_decisions.items()
            },
        }


def _policy_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("policy keys must be non-empty strings")
    return value.strip()


def _choice_value(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("choice values must be non-empty strings")
    return value.strip()


def _feature_values(mode: FeatureMode) -> frozenset[bool]:
    if mode is FeatureMode.DISABLED:
        return frozenset({False})
    if mode is FeatureMode.REQUIRED:
        return frozenset({True})
    return frozenset({False, True})


def _source_revisions(
    layers: tuple[PolicyLayer, ...],
) -> tuple[PolicySourceRevision, ...]:
    return tuple(
        PolicySourceRevision(source=layer.name, revision=layer.revision)
        for layer in layers
    )


class PolicyEngine:
    def __init__(
        self,
        *,
        default_feature_mode: FeatureMode = FeatureMode.DISABLED,
        default_deny_choices: bool = True,
    ) -> None:
        self.default_feature_mode = FeatureMode(default_feature_mode)
        self.default_deny_choices = bool(default_deny_choices)

    def resolve_feature(
        self,
        key: str,
        requested: bool,
        layers: tuple[PolicyLayer, ...],
        *,
        capability_available: bool = True,
    ) -> FeaturePolicyDecision:
        policy_key = _policy_key(key)
        if not isinstance(requested, bool):
            raise PolicyViolation("feature request must be a boolean")
        if not isinstance(capability_available, bool):
            raise TypeError("capability_available must be boolean")

        reasons: list[PolicyReason] = []
        configured = False
        allowed = frozenset({False, True})

        for layer in layers:
            mode = layer.features.get(policy_key)
            if mode is None:
                continue
            configured = True
            allowed = allowed.intersection(_feature_values(mode))
            reasons.append(
                PolicyReason(
                    code="feature_constraint",
                    source=layer.name,
                    detail=f"{policy_key}={mode.value}",
                )
            )
            if not allowed:
                return FeaturePolicyDecision(
                    key=policy_key,
                    requested=requested,
                    effective=False,
                    permitted=False,
                    denial_code=PolicyErrorCode.POLICY_CONFLICT,
                    reasons=tuple(reasons),
                    source_revisions=_source_revisions(layers),
                )

        if not configured:
            allowed = _feature_values(self.default_feature_mode)
            reasons.append(
                PolicyReason(
                    code="default_feature_mode",
                    source="engine",
                    detail=(
                        f"{policy_key}={self.default_feature_mode.value}"
                    ),
                )
            )

        if not capability_available:
            capability_limited = allowed.intersection({False})
            reasons.append(
                PolicyReason(
                    code="capability",
                    source="runtime",
                    detail=f"{policy_key}=unavailable",
                )
            )
            if not capability_limited:
                return FeaturePolicyDecision(
                    key=policy_key,
                    requested=requested,
                    effective=False,
                    permitted=False,
                    denial_code=PolicyErrorCode.CAPABILITY_UNAVAILABLE,
                    reasons=tuple(reasons),
                    source_revisions=_source_revisions(layers),
                )
            allowed = capability_limited

        if len(allowed) == 1:
            effective = next(iter(allowed))
        else:
            effective = requested

        return FeaturePolicyDecision(
            key=policy_key,
            requested=requested,
            effective=effective,
            permitted=True,
            denial_code=None,
            reasons=tuple(reasons),
            source_revisions=_source_revisions(layers),
        )

    def resolve_integer(
        self,
        key: str,
        requested: int,
        layers: tuple[PolicyLayer, ...],
        *,
        behavior: LimitBehavior = LimitBehavior.REJECT,
        capability_maximum: int | None = None,
        default_limit: IntegerLimit | None = None,
    ) -> IntegerPolicyDecision:
        policy_key = _policy_key(key)
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise PolicyViolation("integer request must be an integer")
        resolved_behavior = LimitBehavior(behavior)

        minimum = 0
        maximum: int | None = None
        reasons: list[PolicyReason] = []
        configured = False

        limits: list[tuple[str, IntegerLimit]] = []
        if default_limit is not None:
            if not isinstance(default_limit, IntegerLimit):
                raise TypeError("default_limit must be IntegerLimit")
            limits.append(("engine-default", default_limit))

        for layer in layers:
            limit = layer.integer_limits.get(policy_key)
            if limit is not None:
                configured = True
                limits.append((layer.name, limit))

        for source, limit in limits:
            minimum = max(minimum, limit.minimum)
            if limit.maximum is not None:
                maximum = (
                    limit.maximum
                    if maximum is None
                    else min(maximum, limit.maximum)
                )
            reasons.append(
                PolicyReason(
                    code="integer_constraint",
                    source=source,
                    detail=(
                        f"{policy_key} range {limit.minimum}.."
                        f"{limit.maximum if limit.maximum is not None else 'unbounded'}"
                    ),
                )
            )

        if capability_maximum is not None:
            if isinstance(capability_maximum, bool) or not isinstance(
                capability_maximum, int
            ):
                raise TypeError("capability_maximum must be an integer")
            if capability_maximum < 0:
                raise ValueError("capability_maximum must be >= 0")
            maximum = (
                capability_maximum
                if maximum is None
                else min(maximum, capability_maximum)
            )
            reasons.append(
                PolicyReason(
                    code="capability",
                    source="runtime",
                    detail=f"{policy_key} maximum={capability_maximum}",
                )
            )

        if maximum is not None and maximum < minimum:
            return IntegerPolicyDecision(
                key=policy_key,
                requested=requested,
                effective=None,
                minimum=minimum,
                maximum=maximum,
                permitted=False,
                denial_code=PolicyErrorCode.POLICY_CONFLICT,
                reasons=tuple(reasons),
                source_revisions=_source_revisions(layers),
            )

        if not configured and default_limit is None and capability_maximum is None:
            reasons.append(
                PolicyReason(
                    code="unbounded",
                    source="engine",
                    detail=f"{policy_key}=unbounded",
                )
            )

        effective = requested
        out_of_range = requested < minimum or (
            maximum is not None and requested > maximum
        )
        if out_of_range:
            if resolved_behavior is LimitBehavior.REJECT:
                return IntegerPolicyDecision(
                    key=policy_key,
                    requested=requested,
                    effective=None,
                    minimum=minimum,
                    maximum=maximum,
                    permitted=False,
                    denial_code=PolicyErrorCode.VALUE_OUT_OF_RANGE,
                    reasons=tuple(reasons),
                    source_revisions=_source_revisions(layers),
                )
            effective = max(requested, minimum)
            if maximum is not None:
                effective = min(effective, maximum)

        return IntegerPolicyDecision(
            key=policy_key,
            requested=requested,
            effective=effective,
            minimum=minimum,
            maximum=maximum,
            permitted=True,
            denial_code=None,
            reasons=tuple(reasons),
            source_revisions=_source_revisions(layers),
        )

    def resolve_choice(
        self,
        key: str,
        requested: str,
        layers: tuple[PolicyLayer, ...],
        *,
        available_values: frozenset[str] | set[str] | tuple[str, ...],
        default_deny: bool | None = None,
    ) -> ChoicePolicyDecision:
        policy_key = _policy_key(key)
        requested_value = _choice_value(requested)
        available = frozenset(_choice_value(value) for value in available_values)
        deny_by_default = (
            self.default_deny_choices
            if default_deny is None
            else bool(default_deny)
        )
        reasons: list[PolicyReason] = [
            PolicyReason(
                code="capability_catalog",
                source="runtime",
                detail=f"{policy_key} has {len(available)} available value(s)",
            )
        ]

        configured = False
        allowed = available
        for layer in layers:
            layer_values = layer.allowed_values.get(policy_key)
            if layer_values is None:
                continue
            configured = True
            allowed = allowed.intersection(layer_values)
            reasons.append(
                PolicyReason(
                    code="allowed_values",
                    source=layer.name,
                    detail=(
                        f"{policy_key} allows "
                        f"{','.join(sorted(layer_values)) or '<none>'}"
                    ),
                )
            )

        if not configured and deny_by_default:
            allowed = frozenset()
            reasons.append(
                PolicyReason(
                    code="default_deny",
                    source="engine",
                    detail=f"{policy_key}=deny unless explicitly allowlisted",
                )
            )

        ordered_allowed = tuple(sorted(allowed))
        if requested_value not in allowed:
            return ChoicePolicyDecision(
                key=policy_key,
                requested=requested_value,
                effective=None,
                allowed_values=ordered_allowed,
                permitted=False,
                denial_code=PolicyErrorCode.VALUE_NOT_ALLOWED,
                reasons=tuple(reasons),
                source_revisions=_source_revisions(layers),
            )

        return ChoicePolicyDecision(
            key=policy_key,
            requested=requested_value,
            effective=requested_value,
            allowed_values=ordered_allowed,
            permitted=True,
            denial_code=None,
            reasons=tuple(reasons),
            source_revisions=_source_revisions(layers),
        )

    def evaluate(
        self,
        request: PolicyRequest,
        layers: tuple[PolicyLayer, ...],
        *,
        capabilities: PolicyCapabilities | None = None,
        integer_behaviors: Mapping[str, LimitBehavior] | None = None,
        default_integer_limits: Mapping[str, IntegerLimit] | None = None,
        choice_default_deny: Mapping[str, bool] | None = None,
    ) -> EffectivePolicySnapshot:
        caps = capabilities or PolicyCapabilities()
        behaviors = integer_behaviors or {}
        default_limits = default_integer_limits or {}
        choice_defaults = choice_default_deny or {}

        feature_decisions = {
            key: self.resolve_feature(
                key,
                requested,
                layers,
                capability_available=caps.features.get(key, True),
            )
            for key, requested in request.features.items()
        }
        integer_decisions = {
            key: self.resolve_integer(
                key,
                requested,
                layers,
                behavior=behaviors.get(key, LimitBehavior.REJECT),
                capability_maximum=caps.integer_maximums.get(key),
                default_limit=default_limits.get(key),
            )
            for key, requested in request.integers.items()
        }
        choice_decisions = {
            key: self.resolve_choice(
                key,
                requested,
                layers,
                available_values=caps.choices.get(key, frozenset()),
                default_deny=choice_defaults.get(key),
            )
            for key, requested in request.choices.items()
        }

        return EffectivePolicySnapshot(
            engine_version=POLICY_ENGINE_VERSION,
            feature_decisions=MappingProxyType(feature_decisions),
            integer_decisions=MappingProxyType(integer_decisions),
            choice_decisions=MappingProxyType(choice_decisions),
            source_revisions=_source_revisions(layers),
        )
