# src/adaptive_bridge/adaptive_bridge/qos_manager.py
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy
from typing import Dict, Optional

# A minimal set of named QoS templates used by the proxy.
# Keeps complexity low for sprint. You can add more and tune by topic later.
_QOS_TEMPLATES: Dict[str, QoSProfile] = {
    "reliable_depth10": QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=10,
        reliability=QoSReliabilityPolicy.RELIABLE,
        durability=QoSDurabilityPolicy.VOLATILE,
    ),
    "besteffort_depth5_lifespan500ms": QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=5,
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        durability=QoSDurabilityPolicy.VOLATILE,
        # lifespan isn't directly settable via QoSProfile fields in rclpy stable APIs
        # so lifetime/expiration will be handled by the proxy logic (drop if older than N ms)
    ),
    "besteffort_depth5": QoSProfile(
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=5,
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        durability=QoSDurabilityPolicy.VOLATILE,
    ),
}


class QoSManager:
    """
    Small QoS helper that maps profile names to QoSProfile objects.
    In later versions this can contain RMW adapters and fallbacks for implementations
    that do not support lifespan or certain features.
    """

    def __init__(self, templates: Optional[Dict[str, QoSProfile]] = None):
        self._templates = templates or _QOS_TEMPLATES.copy()

    def get(self, profile_name: str) -> QoSProfile:
        """Return a QoSProfile for a given logical profile name."""
        if profile_name in self._templates:
            return self._templates[profile_name]
        # fallback: reliable depth10
        return self._templates["reliable_depth10"]
