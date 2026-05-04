"""
QoS profile resolution and validation for Adaptive Bridge.

The :class:`QoSManager` loads a catalog of named QoS templates from YAML,
resolves per-topic and per-role profiles (critical / noncritical) with a
fallback chain (per-topic override → role default → global fallback), and
exposes a ``describe()`` method for diagnostic observability of which
profile was selected and why.
"""
import os
import yaml
from rclpy.qos import QoSProfile, QoSHistoryPolicy, QoSReliabilityPolicy, QoSDurabilityPolicy
from typing import Dict, Any, Optional

class QoSManager:
    """
    Production QoS profile resolution and validation.
    Provides typed QoSProfiles to the proxy with explicit fallbacks and lifespan extraction.
    """

    def __init__(self, qos_profiles: Optional[Dict[str, Any]] = None, topic_qos_profiles: Optional[Dict[str, Dict[str, str]]] = None):
        self._templates: Dict[str, QoSProfile] = {}
        self._lifespans: Dict[str, Optional[int]] = {}
        self._topic_qos_profiles = topic_qos_profiles or {}
        
        if qos_profiles is not None:
            self._load_from_dict(qos_profiles)
        else:
            # Deferred loading — caller must call load_profiles() later
            pass

    def _load_from_dict(self, profiles_dict: Dict[str, Any]) -> None:
        for name, profile in profiles_dict.items():
            try:
                # Check for types and valid strings if possible
                rel_str = str(profile.get('reliability', 'RELIABLE')).upper()
                hist_str = str(profile.get('history', 'KEEP_LAST')).upper()
                dur_str = str(profile.get('durability', 'VOLATILE')).upper()

                if rel_str not in ("RELIABLE", "BEST_EFFORT"):
                    raise ValueError(f"reliability must be RELIABLE or BEST_EFFORT, got {rel_str}")
                if hist_str not in ("KEEP_LAST", "KEEP_ALL"):
                    raise ValueError(f"history must be KEEP_LAST or KEEP_ALL, got {hist_str}")
                if dur_str not in ("VOLATILE", "TRANSIENT_LOCAL"):
                    raise ValueError(f"durability must be VOLATILE or TRANSIENT_LOCAL, got {dur_str}")

                reliability = QoSReliabilityPolicy.BEST_EFFORT if rel_str == 'BEST_EFFORT' else QoSReliabilityPolicy.RELIABLE
                history = QoSHistoryPolicy.KEEP_ALL if hist_str == 'KEEP_ALL' else QoSHistoryPolicy.KEEP_LAST
                durability = QoSDurabilityPolicy.TRANSIENT_LOCAL if dur_str == 'TRANSIENT_LOCAL' else QoSDurabilityPolicy.VOLATILE
                
                depth = int(profile.get('depth', 10))
                if depth < 1:
                    raise ValueError("depth must be >= 1")
                
                # Lifespan is not applied to QoSProfile to avoid RMW incompatibility.
                lifespan = None
                if 'lifespan_ms' in profile and profile['lifespan_ms'] is not None:
                    lifespan = int(profile['lifespan_ms'])
                    if lifespan < 1:
                        raise ValueError("lifespan_ms must be >= 1")
                self._lifespans[name] = lifespan
                
                self._templates[name] = QoSProfile(
                    history=history,
                    depth=depth,
                    reliability=reliability,
                    durability=durability
                )
            except Exception as e:
                raise ValueError(f"Invalid profile '{name}': {e}")

    def load_profiles(self, path: str) -> None:
        """Load QoS templates from a YAML file."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"QoS profiles YAML not found at {path}")
            
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            
        if not isinstance(data, dict):
            raise ValueError("QoS profiles YAML must be a mapping")
            
        self._load_from_dict(data)

    def resolve(self, topic_id: str, role: str) -> QoSProfile:
        """
        Resolve the correct QoSProfile for a topic/role pair.
        Order: per-topic override -> role default -> global fallback
        """
        profile_name = self._resolve_profile_name(topic_id, role)
        return self._templates.get(profile_name, self._get_global_fallback(role))

    def describe(self, topic_id: str, role: str) -> dict:
        """
        Return the policy selection reason and metadata for proxy enforcement.
        """
        profile_name = self._resolve_profile_name(topic_id, role)
        
        # Determine fallback reason
        reason = "global fallback"
        if profile_name in self._templates:
            if topic_id in self._topic_qos_profiles and role in self._topic_qos_profiles[topic_id]:
                reason = "per-topic override"
            else:
                reason = "role default"
        else:
            profile_name = "reliable_depth10" if role == "critical" else "besteffort_depth5"
            
        return {
            "profile_name": profile_name,
            "reason": reason,
            "lifespan_ms": self._lifespans.get(profile_name, None)
        }

    def _resolve_profile_name(self, topic_id: str, role: str) -> str:
        if topic_id in self._topic_qos_profiles and role in self._topic_qos_profiles[topic_id]:
            return self._topic_qos_profiles[topic_id][role]
        
        # Role defaults if no mapping is found
        if role == "critical":
            return "reliable_depth10"
        elif role == "noncritical":
            return "besteffort_depth5"
        
        raise ValueError(f"Unknown role: {role}")

    def _get_global_fallback(self, role: str) -> QoSProfile:
        """Safe fallback profiles for RMW compatibility."""
        if role == "critical":
            return QoSProfile(
                history=QoSHistoryPolicy.KEEP_LAST,
                depth=10,
                reliability=QoSReliabilityPolicy.RELIABLE,
                durability=QoSDurabilityPolicy.VOLATILE
            )
        else:
            return QoSProfile(
                history=QoSHistoryPolicy.KEEP_LAST,
                depth=5,
                reliability=QoSReliabilityPolicy.BEST_EFFORT,
                durability=QoSDurabilityPolicy.VOLATILE
            )
