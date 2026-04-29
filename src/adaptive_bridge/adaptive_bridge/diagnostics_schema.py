# diagnostics_schema.py
"""
Diagnostics payload schema definition and validator for Adaptive Bridge.

This module defines the canonical structure of every diagnostics message
published on /adaptive_bridge/diagnostics.

Design goals:
  - Pure Python (no ROS dependency) so unit tests can import it without rclpy.
  - Machine-parseable layout for evaluation scripts in WS2.
  - Schema-versioned so consumers can detect breaking changes.
  - validate_payload() returns a list of error strings (empty = valid).

Payload top-level structure
----------------------------
{
  "schema_version": "1.0",       # str  — bumped on any breaking key change
  "ts_wall":        1234567890.1, # float — time.time() at publish
  "seq":            42,           # int   — monotonically increasing per node restart
  "mode":           "NORMAL",     # str   — global system mode
  "topics": {
    "<topic_id>": {
      "route": {                  # dict  — from TopicRoute.to_dict()
        "topic_id":          str,
        "input_topic":       str,
        "critical_output":   str,
        "noncritical_output": str,
      },
      "counters": {               # dict  — from TopicCounters.to_dict()
        "total_received":              int,
        "total_forwarded_critical":    int,
        "total_forwarded_noncritical": int,
      },
      "drops": {                  # dict  — from NoncriticalPolicyEngine.get_stats()
        "rate_limit":    int,
        "queue_overflow": int,
        "stale":         int,
        "disabled":      int,
      },
      "noncritical_mode": str,    # e.g. "NORMAL", "DEGRADED", "DISABLED"
    }
  },
  "classifier": {                 # dict  — classifier snapshot (empty until Step 10)
    # optional: { subscriber_id: { classification, reason, ts_ns, ... } }
  },
  "qos": {                        # dict  — QoS profile selection per topic/role
    "<topic_id>": {
      "critical":    { "profile_name": str, "reason": str, "lifespan_ms": int|None },
      "noncritical": { "profile_name": str, "reason": str, "lifespan_ms": int|None },
    }
  },
}
"""

from __future__ import annotations

from typing import Any

# -------------------------------------------------------------------
# Version
# -------------------------------------------------------------------

SCHEMA_VERSION: str = "1.0"

# -------------------------------------------------------------------
# Required key sets (for validation)
# -------------------------------------------------------------------

#: Required keys at the top level of the payload and their expected types.
REQUIRED_TOP_LEVEL: dict[str, type] = {
    "schema_version": str,
    "ts_wall": (float, int),
    "seq": int,
    "mode": str,
    "topics": dict,
    "classifier": dict,
    "qos": dict,
}

#: Required keys inside each topics[topic_id] entry.
REQUIRED_TOPIC_KEYS: dict[str, type] = {
    "route": dict,
    "counters": dict,
    "drops": dict,
    "noncritical_mode": str,
}

#: Required keys inside topics[topic_id]["counters"].
REQUIRED_COUNTER_KEYS: dict[str, type] = {
    "total_received": int,
    "total_forwarded_critical": int,
    "total_forwarded_noncritical": int,
}

#: Required keys inside topics[topic_id]["drops"].
REQUIRED_DROP_KEYS: dict[str, type] = {
    "rate_limit": int,
    "queue_overflow": int,
    "stale": int,
    "disabled": int,
}


# -------------------------------------------------------------------
# Validator
# -------------------------------------------------------------------

def validate_payload(payload: Any) -> list[str]:
    """Validate a diagnostics payload dict against the schema.

    Parameters
    ----------
    payload:
        The candidate payload object (should be a dict).

    Returns
    -------
    list[str]
        List of human-readable error strings.  An empty list means the
        payload is schema-valid.
    """
    errors: list[str] = []

    if not isinstance(payload, dict):
        errors.append(f"payload must be a dict, got {type(payload).__name__}")
        return errors

    # ── Top-level key checks ──────────────────────────────────────────
    for key, expected_type in REQUIRED_TOP_LEVEL.items():
        if key not in payload:
            errors.append(f"missing required top-level key: '{key}'")
            continue
        value = payload[key]
        if not isinstance(value, expected_type):
            # Special case: seq must be int but not bool
            if key == "seq" and isinstance(value, bool):
                errors.append(f"'{key}' must be int, got bool")
            else:
                type_names = (
                    "/".join(t.__name__ for t in expected_type)
                    if isinstance(expected_type, tuple)
                    else expected_type.__name__
                )
                errors.append(
                    f"'{key}' must be {type_names}, "
                    f"got {type(value).__name__}"
                )

    # ── topics section ────────────────────────────────────────────────
    topics = payload.get("topics")
    if isinstance(topics, dict):
        for topic_id, topic_data in topics.items():
            prefix = f"topics['{topic_id}']"
            if not isinstance(topic_data, dict):
                errors.append(f"{prefix} must be a dict, got {type(topic_data).__name__}")
                continue

            # Required topic-level keys
            for key, expected_type in REQUIRED_TOPIC_KEYS.items():
                if key not in topic_data:
                    errors.append(f"{prefix}: missing required key '{key}'")
                elif not isinstance(topic_data[key], expected_type):
                    errors.append(
                        f"{prefix}.{key} must be {expected_type.__name__}, "
                        f"got {type(topic_data[key]).__name__}"
                    )

            # counters sub-keys
            counters = topic_data.get("counters")
            if isinstance(counters, dict):
                for key, expected_type in REQUIRED_COUNTER_KEYS.items():
                    if key not in counters:
                        errors.append(f"{prefix}.counters: missing required key '{key}'")
                    elif not isinstance(counters[key], expected_type) or isinstance(counters[key], bool):
                        errors.append(
                            f"{prefix}.counters.{key} must be int, "
                            f"got {type(counters[key]).__name__}"
                        )

            # drops sub-keys
            drops = topic_data.get("drops")
            if isinstance(drops, dict):
                for key, expected_type in REQUIRED_DROP_KEYS.items():
                    if key not in drops:
                        errors.append(f"{prefix}.drops: missing required key '{key}'")
                    elif not isinstance(drops[key], expected_type) or isinstance(drops[key], bool):
                        errors.append(
                            f"{prefix}.drops.{key} must be int, "
                            f"got {type(drops[key]).__name__}"
                        )

    return errors


def assert_valid(payload: Any) -> None:
    """Raise ``ValueError`` if the payload is not schema-valid.

    Convenience wrapper around :func:`validate_payload` for use in
    proxy startup checks or test helpers.
    """
    errors = validate_payload(payload)
    if errors:
        msg = "Diagnostics payload schema violations:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(msg)
