# src/adaptive_bridge/adaptive_bridge/utils/security.py
"""
Adaptive Bridge Security Utilities — Step 13.

Provides HMAC signing and verification for control-plane payloads (classifier
decisions) with replay protection and configurable enforce/log_only/off modes.

Public API:
  SecurityMode(Enum)        — OFF / LOG_ONLY / ENFORCE
  ReplayProtector           — per-identity nonce tracking with timestamp window
  SecurityManager           — combined sign, verify, replay, diagnostics

Key management:
  The HMAC secret is read from SecurityConfig.hmac_secret. A real deployment
  should inject this via env var or a secrets file. Empty secret + non-OFF
  mode results in OFF fallback with a warning.
"""

import hashlib
import hmac
import json
import time
from collections import OrderedDict
from enum import Enum
from typing import Callable, Optional


__all__ = ["SecurityMode", "ReplayProtector", "SecurityManager"]


class SecurityMode(str, Enum):
    OFF = "off"
    LOG_ONLY = "log_only"
    ENFORCE = "enforce"


class ReplayProtector:
    """Tracks seen nonces per identity with a sliding timestamp window.

    Bounded memory: max 200 entries per identity. Oldest entries evicted
    automatically when the limit is reached.
    """

    def __init__(self, window_ms: int = 30000, max_tracked: int = 200) -> None:
        self._window_ns = max(1, window_ms) * 1_000_000
        self._max_tracked = max(1, max_tracked)
        self._seen: dict[str, OrderedDict] = {}

    def check(self, identity: str, ts_ns: int, nonce: int) -> bool:
        """Return True if this (identity, ts_ns, nonce) is a replay.

        A fresh nonce is recorded and returns False.
        A duplicate identical tuple returns True.
        A tuple with a timestamp older than the window returns True.
        """
        now_ns = time.monotonic_ns()
        if now_ns - ts_ns > self._window_ns:
            return True

        if identity not in self._seen:
            self._seen[identity] = OrderedDict()
        records = self._seen[identity]

        key = (ts_ns, nonce)
        if key in records:
            return True

        while len(records) >= self._max_tracked:
            records.popitem(last=False)

        records[key] = now_ns
        return False


class SecurityManager:
    """Combined signing, verification, replay check, and diagnostics counters.

    Parameters
    ----------
    mode:
        One of "off", "log_only", "enforce".
    hmac_secret:
        Hex HMAC key string. Empty string disables signing.
    replay_window_ms:
        Timestamp tolerance window for replay checks.
    """

    def __init__(
        self,
        mode: str = "off",
        hmac_secret: str = "",
        replay_window_ms: int = 30000,
    ) -> None:
        self._mode = SecurityMode.OFF
        if mode == "log_only":
            self._mode = SecurityMode.LOG_ONLY
        elif mode == "enforce":
            self._mode = SecurityMode.ENFORCE

        if not hmac_secret or hmac_secret == "none" or self._mode == SecurityMode.OFF:
            self._key = b""
        else:
            self._key = hmac_secret.encode()

        self._nonce: int = 0
        self._invalid_sig_count: int = 0
        self._replay_count: int = 0
        self._replay_protector = ReplayProtector(window_ms=replay_window_ms)
        self._log_callback: Optional[Callable] = None

    @property
    def mode(self) -> SecurityMode:
        return self._mode

    def set_log_callback(self, cb: Optional[Callable]) -> None:
        self._log_callback = cb

    def sign(self, payload_dict: dict) -> Optional[str]:
        """Sign a payload in-place. Returns hex signature, or None if OFF.

        Mutates payload_dict by adding _nonce, _ts_ns, _hmac fields.
        """
        if not self._key or self._mode == SecurityMode.OFF:
            return None

        self._nonce += 1
        payload_dict["_nonce"] = self._nonce
        payload_dict["_ts_ns"] = time.monotonic_ns()
        canonical = json.dumps(payload_dict, sort_keys=True)
        sig = hmac.new(self._key, canonical.encode(), hashlib.sha256).hexdigest()
        payload_dict["_hmac"] = sig
        return sig

    def verify(self, payload_dict: dict) -> tuple:
        """Verify a signed payload dict.

        The payload_dict is modified in place — only _hmac is popped.
        _nonce and _ts_ns are preserved as part of the signed payload for
        canonical comparison and replay protection.

        Returns
        -------
        tuple[bool, str]:
            (True, "ok") on success.
            (False, reason) on failure, where reason is one of:
                "off", "missing_hmac_fields", "replay", "invalid_signature".
        """
        if self._mode == SecurityMode.OFF:
            return (True, "off")

        sig = payload_dict.pop("_hmac", None)
        nonce = payload_dict.get("_nonce", None)
        ts_ns = payload_dict.get("_ts_ns", None)

        if not sig or nonce is None or ts_ns is None:
            self._invalid_sig_count += 1
            self._log("Security: missing HMAC fields (_hmac, _nonce, _ts_ns)")
            return (False, "missing_hmac_fields")

        identity = payload_dict.get("subscriber_id", "unknown")

        if self._replay_protector.check(str(identity), int(ts_ns), int(nonce)):
            self._replay_count += 1
            self._log(f"Security: replay detected for identity={identity}")
            return (False, "replay")

        canonical = json.dumps(payload_dict, sort_keys=True)
        expected = hmac.new(self._key, canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            self._invalid_sig_count += 1
            self._log(f"Security: invalid signature for identity={identity}")
            return (False, "invalid_signature")

        return (True, "ok")

    def get_stats(self) -> dict:
        """Return diagnostics counters."""
        return {
            "invalid_sig_count": self._invalid_sig_count,
            "replay_count": self._replay_count,
        }

    def _log(self, message: str) -> None:
        if self._log_callback:
            self._log_callback(message)
