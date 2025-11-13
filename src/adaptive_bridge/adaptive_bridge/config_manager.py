# src/adaptive_bridge/adaptive_bridge/config_manager.py
import os
import yaml
from typing import Any, Dict, Optional

DEFAULT_CONFIG = {
    "input_topic": "/scan",
    "critical_topic_prefix": "/adaptive_bridge/critical",
    "noncritical_topic_prefix": "/adaptive_bridge/noncritical",
    "qos_profiles": {
        "critical": "reliable_depth10",
        "noncritical": "besteffort_depth5_lifespan500ms"
    },
    "probe": {
        "enabled": True,
        "rate_hz": 5,
        "rtt_threshold_ms": 100,
        "loss_threshold": 0.05,
        "hysteresis_count": 3
    },
    "overrides": {}
}


class ConfigManager:
    """
    Loads and exposes configuration for Adaptive Bridge.

    Responsibilities:
      - Load YAML config from a file path (or use defaults).
      - Provide safe getters for parameters expected by other components.
      - Allow runtime reload via re-read (used during development).
    """

    def __init__(self, config_path: str = ""):
        self._config_path = config_path or ""
        self._config: Dict[str, Any] = {}
        self.load_or_default()

    def load_or_default(self) -> None:
        """Load YAML config if present, otherwise use DEFAULT_CONFIG."""
        if self._config_path and os.path.isfile(self._config_path):
            with open(self._config_path, "r", encoding="utf-8") as fh:
                self._config = yaml.safe_load(fh) or {}
            # merge defaults for missing keys
            self._deep_merge(DEFAULT_CONFIG, self._config)
        else:
            # no file found, fall back to defaults
            self._config = DEFAULT_CONFIG.copy()

    def reload(self) -> None:
        """Force reloading config from file. Useful for hot-reload in development."""
        self.load_or_default()

    def get(self, key: str, default: Any = None) -> Any:
        """Generic getter that looks up a top-level key."""
        return self._config.get(key, default)

    def get_topic_names(self) -> Dict[str, Optional[str]]:
        """Return input topic and derived output prefixes."""
        return {
            "input_topic": self._config.get("input_topic"),
            "critical_prefix": self._config.get("critical_topic_prefix"),
            "noncritical_prefix": self._config.get("noncritical_topic_prefix"),
        }

    def get_qos_mapping(self) -> Dict[str, str]:
        """Return mapping of logical QoS roles to profile names."""
        return self._config.get("qos_profiles", {})

    def get_probe_config(self) -> Dict[str, Any]:
        return self._config.get("probe", {})

    def is_node_forced_critical(self, node_name: str) -> bool:
        """
        Check overrides for a node name that must always be considered critical.
        The 'overrides' field in YAML is expected to be a mapping: {node_name: {critical: true}}
        """
        overrides = self._config.get("overrides", {})
        entry = overrides.get(node_name, {})
        return bool(entry.get("critical", False))

    @staticmethod
    def _deep_merge(base: Dict[str, Any], dest: Dict[str, Any]) -> None:
        """
        Mutate dest in place by inserting missing keys from base.
        Only fills missing keys; does not override user values.
        """
        for k, v in base.items():
            if k not in dest:
                dest[k] = v
            else:
                if isinstance(v, dict) and isinstance(dest.get(k), dict):
                    ConfigManager._deep_merge(v, dest[k])
