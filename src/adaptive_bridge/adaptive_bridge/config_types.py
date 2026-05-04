"""
Typed configuration data models for Adaptive Bridge.

Defines :class:`TopicConfig`, :class:`QoSPolicy`, :class:`ClassifierConfig`,
:class:`SafetyConfig`, :class:`SecurityConfig`, :class:`DiagnosticsConfig`,
:class:`RoutingPolicyConfig`, and :class:`BridgeConfig` as frozen dataclasses.
These replace loose dict handling throughout the codebase and provide
compile-time (mypy) and runtime (type-check) safety for configuration data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _as_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a mapping")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _as_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _as_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    return value


def _as_int(value: Any, path: str, min_value: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    if min_value is not None and value < min_value:
        raise ValueError(f"{path} must be >= {min_value}")
    return value


def _as_float(value: Any, path: str, min_value: float | None = None, max_value: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{path} must be a number")
    num = float(value)
    if min_value is not None and num < min_value:
        raise ValueError(f"{path} must be >= {min_value}")
    if max_value is not None and num > max_value:
        raise ValueError(f"{path} must be <= {max_value}")
    return num


def _as_optional_int(value: Any, path: str, min_value: int | None = None) -> int | None:
    if value is None:
        return None
    return _as_int(value, path, min_value=min_value)


@dataclass(frozen=True)
class TopicConfig:
    id: str
    input_topic: str
    critical_output: str
    noncritical_output: str
    message_type: str = "sensor_msgs/LaserScan"
    qos_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, path: str = "topics[]") -> "TopicConfig":
        d = _as_dict(data, path)
        overrides = d.get("qos_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"{_path(path, 'qos_overrides')} must be a mapping")
        clean_overrides: dict[str, str] = {}
        for k, v in overrides.items():
            clean_overrides[_as_str(k, _path(path, "qos_overrides key"))] = _as_str(
                v, _path(path, f"qos_overrides.{k}")
            )
        return cls(
            id=_as_str(d.get("id"), _path(path, "id")),
            input_topic=_as_str(d.get("input_topic"), _path(path, "input_topic")),
            critical_output=_as_str(d.get("critical_output"), _path(path, "critical_output")),
            noncritical_output=_as_str(d.get("noncritical_output"), _path(path, "noncritical_output")),
            message_type=_as_str(d.get("message_type", "sensor_msgs/LaserScan"),
                                _path(path, "message_type")),
            qos_overrides=clean_overrides,
        )


@dataclass(frozen=True)
class QoSPolicy:
    reliability: str
    history: str
    depth: int
    durability: str
    lifespan_ms: int | None = None

    @classmethod
    def from_dict(cls, data: Any, path: str = "qos_profiles.*") -> "QoSPolicy":
        d = _as_dict(data, path)
        reliability = _as_str(d.get("reliability"), _path(path, "reliability")).upper()
        if reliability not in {"RELIABLE", "BEST_EFFORT"}:
            raise ValueError(f"{_path(path, 'reliability')} must be RELIABLE or BEST_EFFORT")
        history = _as_str(d.get("history"), _path(path, "history")).upper()
        if history not in {"KEEP_LAST", "KEEP_ALL"}:
            raise ValueError(f"{_path(path, 'history')} must be KEEP_LAST or KEEP_ALL")
        durability = _as_str(d.get("durability"), _path(path, "durability")).upper()
        if durability not in {"VOLATILE", "TRANSIENT_LOCAL"}:
            raise ValueError(f"{_path(path, 'durability')} must be VOLATILE or TRANSIENT_LOCAL")
        return cls(
            reliability=reliability,
            history=history,
            depth=_as_int(d.get("depth"), _path(path, "depth"), min_value=1),
            durability=durability,
            lifespan_ms=_as_optional_int(d.get("lifespan_ms"), _path(path, "lifespan_ms"), min_value=1),
        )


@dataclass(frozen=True)
class ClassifierConfig:
    enabled: bool
    evaluate_rate_hz: float
    demote_loss_threshold: float
    promote_loss_threshold: float
    demote_rtt_ms: float
    promote_rtt_ms: float
    hysteresis_count: int
    allow_unknown_state: bool
    subscriber_id: str = ""
    """Label for the monitored endpoint in classification decisions.
    Set this to a descriptive name for the subscriber being probed
    (e.g. ``\"remote_rviz\"``, ``\"wifi_subscriber\"``).
    When empty, the classifier falls back to the ProbeClient's sender ID."""

    @classmethod
    def from_dict(cls, data: Any, path: str = "classifier") -> "ClassifierConfig":
        d = _as_dict(data, path)
        subscriber_id_raw = d.get("subscriber_id", "")
        if subscriber_id_raw and isinstance(subscriber_id_raw, str) and subscriber_id_raw.strip():
            subscriber_id_val = subscriber_id_raw.strip()
        else:
            subscriber_id_val = ""
        return cls(
            enabled=_as_bool(d.get("enabled"), _path(path, "enabled")),
            evaluate_rate_hz=_as_float(d.get("evaluate_rate_hz"), _path(path, "evaluate_rate_hz"), min_value=0.1),
            demote_loss_threshold=_as_float(d.get("demote_loss_threshold"), _path(path, "demote_loss_threshold"), 0.0, 1.0),
            promote_loss_threshold=_as_float(d.get("promote_loss_threshold"), _path(path, "promote_loss_threshold"), 0.0, 1.0),
            demote_rtt_ms=_as_float(d.get("demote_rtt_ms"), _path(path, "demote_rtt_ms"), min_value=0.0),
            promote_rtt_ms=_as_float(d.get("promote_rtt_ms"), _path(path, "promote_rtt_ms"), min_value=0.0),
            hysteresis_count=_as_int(d.get("hysteresis_count"), _path(path, "hysteresis_count"), min_value=1),
            allow_unknown_state=_as_bool(d.get("allow_unknown_state"), _path(path, "allow_unknown_state")),
            subscriber_id=subscriber_id_val,
        )


@dataclass(frozen=True)
class ProbeConfig:
    enabled: bool
    rate_hz: float
    rtt_threshold_ms: float
    loss_threshold: float
    jitter_threshold_ms: float
    window_size: int
    hysteresis_count: int
    timeout_ms: int
    request_topic: str
    response_topic: str

    @classmethod
    def from_dict(cls, data: Any, path: str = "probes") -> "ProbeConfig":
        d = _as_dict(data, path)
        return cls(
            enabled=_as_bool(d.get("enabled"), _path(path, "enabled")),
            rate_hz=_as_float(d.get("rate_hz"), _path(path, "rate_hz"), min_value=0.1),
            rtt_threshold_ms=_as_float(d.get("rtt_threshold_ms"), _path(path, "rtt_threshold_ms"), min_value=0.0),
            loss_threshold=_as_float(d.get("loss_threshold"), _path(path, "loss_threshold"), 0.0, 1.0),
            jitter_threshold_ms=_as_float(d.get("jitter_threshold_ms"), _path(path, "jitter_threshold_ms"), min_value=0.0),
            window_size=_as_int(d.get("window_size"), _path(path, "window_size"), min_value=1),
            hysteresis_count=_as_int(d.get("hysteresis_count"), _path(path, "hysteresis_count"), min_value=1),
            timeout_ms=_as_int(d.get("timeout_ms", 500), _path(path, "timeout_ms"), min_value=1),
            request_topic=_as_str(d.get("request_topic"), _path(path, "request_topic")),
            response_topic=_as_str(d.get("response_topic"), _path(path, "response_topic")),
        )


@dataclass(frozen=True)
class ModePolicy:
    """Per-state settings for the noncritical path (one per PolicyMode).

    Controls what happens to noncritical traffic when the system enters each
    of the five PolicyModes (NORMAL, DEGRADED, DISABLED, EMERGENCY, FAILURE).

    Every field is user-configurable so that developers can define exactly
    what each mode means for their deployment.
    """

    noncritical_max_rate_hz: float
    """Hz cap on noncritical forwarding.  0.0 = block all noncritical."""

    noncritical_depth: int
    """KEEP_LAST depth for the noncritical publisher."""

    noncritical_drop_policy: str
    """``\"drop_oldest\"`` or ``\"drop_stale\"`` — which messages to drop first."""

    stale_threshold_ms: int
    """Messages older than this (milliseconds) are dropped as stale."""

    max_noncritical_queue: int
    """Maximum items in the noncritical publish queue before overflow drops."""

    @classmethod
    def from_dict(cls, data: Any, path: str = "modes.*") -> "ModePolicy":
        d = _as_dict(data, path)
        drop_policy = _as_str(
            d.get("noncritical_drop_policy"), _path(path, "noncritical_drop_policy")
        ).lower()
        if drop_policy not in {"drop_oldest", "drop_latest", "drop_stale"}:
            raise ValueError(
                f"{_path(path, 'noncritical_drop_policy')} must be "
                f"one of drop_oldest, drop_latest, drop_stale"
            )
        return cls(
            noncritical_max_rate_hz=_as_float(
                d.get("noncritical_max_rate_hz"),
                _path(path, "noncritical_max_rate_hz"),
                min_value=0.0,
            ),
            noncritical_depth=_as_int(
                d.get("noncritical_depth"),
                _path(path, "noncritical_depth"),
                min_value=0,
            ),
            noncritical_drop_policy=drop_policy,
            stale_threshold_ms=_as_int(
                d.get("stale_threshold_ms"),
                _path(path, "stale_threshold_ms"),
                min_value=0,
            ),
            max_noncritical_queue=_as_int(
                d.get("max_noncritical_queue"),
                _path(path, "max_noncritical_queue"),
                min_value=0,
            ),
        )


@dataclass(frozen=True)
class RoutingPolicyConfig:
    critical_always_forward: bool
    noncritical_enabled: bool
    noncritical_max_rate_hz: float
    noncritical_drop_policy: str
    stale_threshold_ms: int
    modes: dict[str, ModePolicy] = field(default_factory=dict)
    """Per-state mode policies.  Keys: normal, degraded, disabled, emergency, failure."""

    @classmethod
    def from_dict(cls, data: Any, path: str = "routing_policy") -> "RoutingPolicyConfig":
        d = _as_dict(data, path)
        drop_policy = _as_str(d.get("noncritical_drop_policy"), _path(path, "noncritical_drop_policy")).lower()
        if drop_policy not in {"drop_oldest", "drop_latest", "drop_stale"}:
            raise ValueError(f"{_path(path, 'noncritical_drop_policy')} must be one of drop_oldest, drop_latest, drop_stale")

        # Parse optional modes section
        modes_raw = d.get("modes", {})
        modes: dict[str, ModePolicy] = {}
        if modes_raw:
            modes_data = _as_dict(modes_raw, _path(path, "modes"))
            valid_keys = frozenset({"normal", "degraded", "disabled", "emergency", "failure"})
            for key, value in modes_data.items():
                k = _as_str(key, _path(path, "modes key"))
                if k not in valid_keys:
                    raise ValueError(
                        f"Unknown mode key '{k}' in {_path(path, 'modes')}. "
                        f"Valid keys: {', '.join(sorted(valid_keys))}"
                    )
                modes[k] = ModePolicy.from_dict(value, _path(path, f"modes.{k}"))

        return cls(
            critical_always_forward=_as_bool(d.get("critical_always_forward"), _path(path, "critical_always_forward")),
            noncritical_enabled=_as_bool(d.get("noncritical_enabled"), _path(path, "noncritical_enabled")),
            noncritical_max_rate_hz=_as_float(d.get("noncritical_max_rate_hz"), _path(path, "noncritical_max_rate_hz"), min_value=0.1),
            noncritical_drop_policy=drop_policy,
            stale_threshold_ms=_as_int(d.get("stale_threshold_ms"), _path(path, "stale_threshold_ms"), min_value=1),
            modes=modes,
        )


@dataclass(frozen=True)
class SafetyConfig:
    preserve_critical_path: bool
    allow_noncritical_degrade: bool
    max_noncritical_queue: int
    overload_drop_noncritical_first: bool

    @classmethod
    def from_dict(cls, data: Any, path: str = "safety") -> "SafetyConfig":
        d = _as_dict(data, path)
        return cls(
            preserve_critical_path=_as_bool(d.get("preserve_critical_path"), _path(path, "preserve_critical_path")),
            allow_noncritical_degrade=_as_bool(d.get("allow_noncritical_degrade"), _path(path, "allow_noncritical_degrade")),
            max_noncritical_queue=_as_int(d.get("max_noncritical_queue"), _path(path, "max_noncritical_queue"), min_value=1),
            overload_drop_noncritical_first=_as_bool(
                d.get("overload_drop_noncritical_first"), _path(path, "overload_drop_noncritical_first")
            ),
        )


@dataclass(frozen=True)
class SecurityConfig:
    trust_mode: str
    allow_legacy_node_name_overrides: bool
    enable_probe_hmac: bool
    max_probe_rate_hz: float
    hmac_secret: str
    replay_window_ms: int

    @classmethod
    def from_dict(cls, data: Any, path: str = "security") -> "SecurityConfig":
        d = _as_dict(data, path)
        trust_mode = _as_str(d.get("trust_mode"), _path(path, "trust_mode")).lower()
        if trust_mode not in {"default_deny", "permissive", "off"}:
            raise ValueError(f"{_path(path, 'trust_mode')} must be default_deny, permissive, or off")
        return cls(
            trust_mode=trust_mode,
            allow_legacy_node_name_overrides=_as_bool(
                d.get("allow_legacy_node_name_overrides"), _path(path, "allow_legacy_node_name_overrides")
            ),
            enable_probe_hmac=_as_bool(d.get("enable_probe_hmac"), _path(path, "enable_probe_hmac")),
            max_probe_rate_hz=_as_float(d.get("max_probe_rate_hz"), _path(path, "max_probe_rate_hz"), min_value=0.1),
            hmac_secret=_as_str(
                d.get("hmac_secret") or "none",
                _path(path, "hmac_secret"),
            ),
            replay_window_ms=_as_int(d.get("replay_window_ms", 30000), _path(path, "replay_window_ms"), min_value=1),
        )


@dataclass(frozen=True)
class DiagnosticsConfig:
    enabled: bool
    publish_interval_s: float
    topic: str
    verbosity: str

    @classmethod
    def from_dict(cls, data: Any, path: str = "diagnostics") -> "DiagnosticsConfig":
        d = _as_dict(data, path)
        verbosity = _as_str(d.get("verbosity"), _path(path, "verbosity")).lower()
        if verbosity not in {"error", "warning", "info", "debug"}:
            raise ValueError(f"{_path(path, 'verbosity')} must be one of error, warning, info, debug")
        return cls(
            enabled=_as_bool(d.get("enabled"), _path(path, "enabled")),
            publish_interval_s=_as_float(d.get("publish_interval_s"), _path(path, "publish_interval_s"), min_value=0.1),
            topic=_as_str(d.get("topic"), _path(path, "topic")),
            verbosity=verbosity,
        )


@dataclass(frozen=True)
class BridgeConfig:
    topics: list[TopicConfig]
    topic_qos_profiles: dict[str, dict[str, str]]
    qos_profiles: dict[str, QoSPolicy]
    classifier: ClassifierConfig
    probes: ProbeConfig
    routing_policy: RoutingPolicyConfig
    safety: SafetyConfig
    security: SecurityConfig
    diagnostics: DiagnosticsConfig
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, path: str = "root") -> "BridgeConfig":
        d = _as_dict(data, path)

        topics_raw = _as_list(d.get("topics"), "topics")
        topics: list[TopicConfig] = [TopicConfig.from_dict(item, path=f"topics[{idx}]") for idx, item in enumerate(topics_raw)]
        if not topics:
            raise ValueError("topics must contain at least one topic definition")
        ids = [t.id for t in topics]
        if len(ids) != len(set(ids)):
            raise ValueError("topics contain duplicate topic ids")

        qos_raw = _as_dict(d.get("qos_profiles"), "qos_profiles")
        qos_profiles: dict[str, QoSPolicy] = {}
        for name, value in qos_raw.items():
            key = _as_str(name, "qos_profiles key")
            qos_profiles[key] = QoSPolicy.from_dict(value, path=f"qos_profiles.{key}")

        topic_qos_profiles = _as_dict(d.get("topic_qos_profiles"), "topic_qos_profiles")
        clean_topic_qos: dict[str, dict[str, str]] = {}
        for topic_id, mapping in topic_qos_profiles.items():
            tid = _as_str(topic_id, "topic_qos_profiles key")
            m = _as_dict(mapping, f"topic_qos_profiles.{tid}")
            critical = _as_str(m.get("critical"), f"topic_qos_profiles.{tid}.critical")
            noncritical = _as_str(m.get("noncritical"), f"topic_qos_profiles.{tid}.noncritical")
            clean_topic_qos[tid] = {"critical": critical, "noncritical": noncritical}

        topic_ids = {t.id for t in topics}
        for tid in clean_topic_qos:
            if tid not in topic_ids:
                raise ValueError(f"topic_qos_profiles references unknown topic id '{tid}'")
            for role in ("critical", "noncritical"):
                profile_name = clean_topic_qos[tid][role]
                if profile_name not in qos_profiles:
                    raise ValueError(f"topic_qos_profiles.{tid}.{role} uses unknown QoS profile '{profile_name}'")

        overrides_raw = d.get("overrides", {})
        overrides = _as_dict(overrides_raw, "overrides")

        return cls(
            topics=topics,
            topic_qos_profiles=clean_topic_qos,
            qos_profiles=qos_profiles,
            classifier=ClassifierConfig.from_dict(d.get("classifier"), "classifier"),
            probes=ProbeConfig.from_dict(d.get("probes"), "probes"),
            routing_policy=RoutingPolicyConfig.from_dict(d.get("routing_policy"), "routing_policy"),
            safety=SafetyConfig.from_dict(d.get("safety"), "safety"),
            security=SecurityConfig.from_dict(d.get("security"), "security"),
            diagnostics=DiagnosticsConfig.from_dict(d.get("diagnostics"), "diagnostics"),
            overrides=overrides,
        )
