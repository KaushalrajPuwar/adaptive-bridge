"""
Configuration loading, validation, and typed access for Adaptive Bridge.

Provides the ``ConfigManager`` class that loads YAML configuration files,
validates schema conformance, and exposes typed getters (``get_topics()``,
``get_qos_policy()``, ``get_classifier_config()``, etc.) for all runtime
subsystems.  Schema validation catches missing keys, invalid QoS names,
and duplicate topic IDs at startup rather than at runtime.
"""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any

import yaml

from .config_types import (
    BridgeConfig,
    ClassifierConfig,
    DiagnosticsConfig,
    ProbeConfig,
    QoSPolicy,
    SafetyConfig,
    SecurityConfig,
    TopicConfig,
)


class ConfigManager:
    """Load, normalize, validate and expose strongly typed bridge configuration."""

    def __init__(self, config_path: str = ""):
        self._config_path = config_path or ""
        self._config: BridgeConfig | None = None
        self.load_or_default()

    def load_or_default(self) -> None:
        raw = self._read_raw()
        normalized = self._normalize(raw)
        self._config = BridgeConfig.from_dict(normalized)

    def reload(self) -> None:
        self.load_or_default()

    def _read_raw(self) -> dict[str, Any]:
        if self._config_path and os.path.isfile(self._config_path):
            with open(self._config_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if not isinstance(data, dict):
                raise ValueError("root config must be a mapping")
            return data
        try:
            from ament_index_python.packages import get_package_share_directory
            share_dir = get_package_share_directory('adaptive_bridge')
            default_path = Path(share_dir) / "config" / "default.yaml"
            if not default_path.is_file():
                default_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        except Exception:
            default_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
        with open(default_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError("default config must be a mapping")
        return data

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        if self._looks_legacy(raw):
            warnings.warn(
                "Legacy config format detected (input_topic/critical_topic_prefix/noncritical_topic_prefix/probe). "
                "Please migrate to Step 2 schema.",
                DeprecationWarning,
                stacklevel=2,
            )
            return self._legacy_to_modern(raw)
        return raw

    @staticmethod
    def _looks_legacy(raw: dict[str, Any]) -> bool:
        return "topics" not in raw and (
            "input_topic" in raw or "critical_topic_prefix" in raw or "noncritical_topic_prefix" in raw or "probe" in raw
        )

    @staticmethod
    def _legacy_to_modern(raw: dict[str, Any]) -> dict[str, Any]:
        input_topic = raw.get("input_topic", "/scan")
        crit_prefix = raw.get("critical_topic_prefix", "/adaptive_bridge/critical")
        noncrit_prefix = raw.get("noncritical_topic_prefix", "/adaptive_bridge/noncritical")
        base_name = (str(input_topic).strip("/") or "topic").replace("/", "_")
        probe = raw.get("probe", {})
        qos = raw.get("qos_profiles", {})
        return {
            "topics": [
                {
                    "id": "scan_main",
                    "input_topic": input_topic,
                    "critical_output": f"{crit_prefix}/{base_name}",
                    "noncritical_output": f"{noncrit_prefix}/{base_name}",
                    "qos_overrides": {},
                }
            ],
            "qos_profiles": {
                "reliable_depth10": {
                    "reliability": "RELIABLE",
                    "history": "KEEP_LAST",
                    "depth": 10,
                    "durability": "VOLATILE",
                },
                "besteffort_depth5_lifespan500ms": {
                    "reliability": "BEST_EFFORT",
                    "history": "KEEP_LAST",
                    "depth": 5,
                    "durability": "VOLATILE",
                    "lifespan_ms": 500,
                },
                "besteffort_depth5": {
                    "reliability": "BEST_EFFORT",
                    "history": "KEEP_LAST",
                    "depth": 5,
                    "durability": "VOLATILE",
                },
            },
            "topic_qos_profiles": {
                "scan_main": {
                    "critical": qos.get("critical", "reliable_depth10"),
                    "noncritical": qos.get("noncritical", "besteffort_depth5_lifespan500ms"),
                }
            },
            "classifier": {
                "enabled": True,
                "evaluate_rate_hz": 1.0,
                "demote_loss_threshold": 0.1,
                "promote_loss_threshold": 0.03,
                "demote_rtt_ms": 120.0,
                "promote_rtt_ms": 60.0,
                "hysteresis_count": int(probe.get("hysteresis_count", 3)),
                "allow_unknown_state": True,
            },
            "probes": {
                "enabled": bool(probe.get("enabled", True)),
                "rate_hz": float(probe.get("rate_hz", 5.0)),
                "rtt_threshold_ms": float(probe.get("rtt_threshold_ms", 100.0)),
                "loss_threshold": float(probe.get("loss_threshold", 0.05)),
                "jitter_threshold_ms": 25.0,
                "window_size": 50,
                "hysteresis_count": int(probe.get("hysteresis_count", 3)),
                "timeout_ms": int(probe.get("timeout_ms", 500)),
                "request_topic": "/adaptive_bridge/probe_req",
                "response_topic": "/adaptive_bridge/probe_resp",
            },
            "routing_policy": {
                "critical_always_forward": True,
                "noncritical_enabled": True,
                "noncritical_max_rate_hz": 10.0,
                "noncritical_drop_policy": "drop_oldest",
                "stale_threshold_ms": 500,
            },
            "safety": {
                "preserve_critical_path": True,
                "allow_noncritical_degrade": True,
                "max_noncritical_queue": 50,
                "overload_drop_noncritical_first": True,
            },
            "security": {
                "trust_mode": "default_deny",
                "allow_legacy_node_name_overrides": True,
                "enable_probe_hmac": False,
                "max_probe_rate_hz": 20.0,
            },
            "diagnostics": {
                "enabled": True,
                "publish_interval_s": 1.0,
                "topic": "/adaptive_bridge/diagnostics",
                "verbosity": "info",
            },
            "overrides": raw.get("overrides", {}),
        }

    def _cfg(self) -> BridgeConfig:
        if self._config is None:
            raise RuntimeError("config was not loaded")
        return self._config

    def get_topics(self) -> list[TopicConfig]:
        return list(self._cfg().topics)

    def get_topic_ids(self) -> list[str]:
        return [topic.id for topic in self._cfg().topics]

    def get_qos_policy(self, role: str, topic_id: str) -> QoSPolicy:
        mapping = self._cfg().topic_qos_profiles.get(topic_id)
        if mapping is None:
            raise ValueError(f"unknown topic_id: {topic_id}")
        if role not in {"critical", "noncritical"}:
            raise ValueError("role must be 'critical' or 'noncritical'")
        profile_name = mapping[role]
        return self._cfg().qos_profiles[profile_name]

    def get_classifier_config(self) -> ClassifierConfig:
        return self._cfg().classifier

    def get_probe_config(self) -> ProbeConfig:
        return self._cfg().probes

    def get_safety_config(self) -> SafetyConfig:
        return self._cfg().safety

    def get_security_config(self) -> SecurityConfig:
        return self._cfg().security

    def is_node_forced_critical(self, node_name: str) -> bool:
        entry = self._cfg().overrides.get(node_name, {})
        if not isinstance(entry, dict):
            return False
        return bool(entry.get("critical", False))

    def get_forced_critical_ids(self) -> set[str]:
        """Return subscriber IDs that are forced CRITICAL via overrides."""
        overrides = self._cfg().overrides
        return {
            node_name
            for node_name, entry in overrides.items()
            if isinstance(entry, dict) and entry.get("critical", False)
        }

    def get_qos_profiles_dict(self) -> dict:
        """Return raw QoS profile dicts for QoSManager."""
        return {
            name: {
                "reliability": policy.reliability,
                "history": policy.history,
                "depth": policy.depth,
                "durability": policy.durability,
                "lifespan_ms": policy.lifespan_ms,
            }
            for name, policy in self._cfg().qos_profiles.items()
        }

    def get_topic_qos_profiles_dict(self) -> dict:
        """Return topic->profile-name mapping dict."""
        return dict(self._cfg().topic_qos_profiles)

    def get_bridge_config(self) -> BridgeConfig:
        """Return the full typed config (replaces _cfg() entirely)."""
        return self._cfg()

    def get_diagnostics_config(self) -> DiagnosticsConfig:
        """Return the diagnostics subsection."""
        return self._cfg().diagnostics

