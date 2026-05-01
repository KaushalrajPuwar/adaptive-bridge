Adaptive Bridge Project Changelog
==================================

This changelog records the evolution of the Adaptive Bridge project.

v0.1.0 (Prototype Development — 2026-04-28)
------------------------------------------

Initial prototype with basic ROS 2 proxy node for LaserScan forwarding,
dual critical/noncritical output streams, and supporting utilities.

- Proxy node with single-topic LaserScan forwarding.
- YAML configuration loading with QoS profile mapping.
- Named QoS profile resolution system.
- Standalone diagnostics node.
- Probe client/responder utilities for RTT measurement.
- Repository hygiene, packaging, and build determinism baseline.

2026-04-29 — Configuration, Data Models, and Multi-Topic Proxy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Typed configuration contract with schema validation (BridgeConfig,
  ClassifierConfig, ProbeConfig, QoSPolicy, SafetyConfig, SecurityConfig,
  RoutingPolicyConfig, TopicConfig). All sections validated for bounds
  and required fields with backward-compatible legacy key support.
- Shared runtime data models: TopicRoute, TopicCounters, PolicyMode,
  ClassifierSnapshot, TopicRuntimeState with dict serialization.
- Deterministic TopicRegistry with sanitizer, route builder, uniqueness
  enforcement, and export helpers.
- Multi-topic proxy runtime: builds all configured topic routes at startup,
  pre-creates per-topic subscribers and critical/noncritical publishers.
  Callback-factory forwarding with per-topic counters and safe shutdown.
- QoS Manager v2: decoupled from ConfigManager, parses generic YAML
  dictionaries, extracts RMW-incompatible lifespan_ms to application
  logic, resolves profiles with three-tier fallback (per-topic → role
  default → global fallback).
- QoS policy catalog documented in docs/15_QOS_MATRIX.md.
- Test coverage for config validation, proxy multi-topic behavior, QoS
  resolution, and topic registry invariants.

2026-04-29 — Noncritical Degradation and Diagnostics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- NoncriticalPolicyEngine: token-bucket rate limiter, staleness-based TTL
  drops, mode-disabled drops. Integrated into ProxyNode with isolated
  threading — critical publish path never blocked by noncritical policy.
- Diagnostics schema v1.0 with validate_payload() and assert_valid().
  Pure-Python DiagnosticsCollector (no ROS dependency) + ROS publisher
  wrapper owned by ProxyNode. Payload includes schema version, wall-clock
  timestamp, sequence number, mode, per-topic counters, drop reasons,
  QoS profiles, and classifier snapshot placeholder.
- Unit tests for rate limiting, staleness, mode changes, drop statistics,
  and diagnostics payload structure.

2026-05-01 — Probe Protocol Hardening
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Probe payloads versioned (v=1) with monotonic nanosecond timestamps.
- Bounded outstanding-sequence map (window_size × 3 cap) to prevent
  unbounded memory growth under sustained loss.
- Sliding-window loss rate, RTT mean/p95, and jitter estimate.
- Configurable probe timeout with stale response rejection.
- Receive-side sanity checks: malformed JSON, unknown sequence, wrong
  protocol version, stale RTT, zero/negative seq.
- ProbeResponder now injects recv_time_ns, reply_time_ns,
  response_send_time_ns, and responder_id.
- Configurable timeout_ms added to ProbeConfig and all config files.
- 30 unit tests covering payload format, sanity checks, bounded storage,
  rolling metrics, get_stats() contract, and end-to-end round trip.

2026-05-01 — Classifier Core Library
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Pure-Python SubscriberClassifier state machine with UNKNOWN,
  CRITICAL, and NONCRITICAL states, gated by hysteresis counters.
- Typed I/O contracts: ProbeMetrics (input) and ClassificationDecision
  (output), both with validation and dict serialization.
- Eight reason codes: manual_override, high_rtt, high_loss,
  high_rtt_and_loss, recovered, insufficient_data, stable_critical,
  promoting.
- Forced-critical override bypasses state machine without mutating
  internal counters; override removal resumes from preserved state.
- ClassificationDecision.to_snapshot() bridges to diagnostics payload
  system.
- Transition table documented in docs/05_CLASSIFIER_AND_PROBES.md
  (section §17.1) with definitions for is_bad, is_good, and fuzzy zone.
- 30 unit tests covering state machine invariants, hysteresis counters,
  reason codes, flap suppression, override behavior, snapshots, reset,
  and fuzzy-zone handling.

2026-05-01 — Code Review Fixes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fixed UNKNOWN state promotion: now correctly requires is_good metrics
  (not just not is_bad), matching documented transition table.
- Added public API to ConfigManager (get_forced_critical_ids());
  refactored classifier_node.py to use it.
- Added missing classifier constants to package exports: REASON_PROMOTING,
  CLASSIFIER_SCHEMA_VERSION, ALL_REASON_CODES, ALL_STATES.
- Fixed license to Apache-2.0 and maintainer email to gmail.com in both
  package.xml and setup.py (were inconsistent).
- Added missing std_msgs dependency to package.xml.
- Updated proxy_node.py docstring to reflect cumulative feature scope
  across all development phases.

Known Gaps (Deferred)
~~~~~~~~~~~~~~~~~~~~~

- proxy_node.py has 5 remaining self.config._cfg() private attribute
  accesses — see docs/11_DECISIONS_LOG.md D029.
- noncritical_policy.py imports BridgeConfig from config_manager instead
  of config_types.
- Missing return type annotations in noncritical_policy.py and
  proxy_node.py.
- 6 files missing module-level docstrings (config_manager.py,
  config_types.py, qos_manager.py, topic_registry.py, models.py,
  noncritical_policy.py).
- PEP257/Flake8 lint tests permanently skipped (deferred to final
  packaging pass).
- utils/security.py is an empty stub awaiting implementation
  (docs/07_SECURITY_MODEL.md).

Architecture Decisions
~~~~~~~~~~~~~~~~~~~~~~

Multi-workspace strategy (D001), proxy-based isolation (D002),
dual output streams (D003), static publisher lifecycle (D004),
policy-based classification (D005), active network probing (D006),
stability mechanism (D008), deterministic overrides (D009),
internal load shedding (D010), critical path fidelity (D011),
non-critical degradation (D012), transport forcing (D013),
tuned baseline comparison (D016), distribution-based metrics (D017),
multi-RMW validation (D018), multi-proxy scaling (D022),
sensor-ready implementation (D024), add sensor_msgs dependency (D025),
stateless forwarding (D020).
