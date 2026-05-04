Adaptive Bridge Project Changelog
==================================

This changelog records the evolution of the Adaptive Bridge project.

v0.1.0 (Prototype Development, 2026-04-28)
------------------------------------------

Initial prototype with basic ROS 2 proxy node for LaserScan forwarding,
dual critical/noncritical output streams, and supporting utilities.

- Proxy node with single-topic LaserScan forwarding.
- YAML configuration loading with QoS profile mapping.
- Named QoS profile resolution system.
- Standalone diagnostics node.
- Probe client/responder utilities for RTT measurement.
- Repository hygiene, packaging, and build determinism baseline.

2026-04-29: Configuration, Data Models, and Multi-Topic Proxy
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
- Test coverage for config validation, proxy multi-topic behaviour, QoS
  resolution, and topic registry invariants.

2026-04-29: Noncritical Degradation and Diagnostics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- NoncriticalPolicyEngine: token-bucket rate limiter, staleness-based TTL
  drops, mode-disabled drops. Integrated into ProxyNode with isolated
  threading: critical publish path never blocked by noncritical policy.
- Diagnostics schema v1.0 with validate_payload() and assert_valid().
  Pure-Python DiagnosticsCollector (no ROS dependency) + ROS publisher
  wrapper owned by ProxyNode. Payload includes schema version, wall-clock
  timestamp, sequence number, mode, per-topic counters, drop reasons,
  QoS profiles, and classifier snapshot placeholder.
- Unit tests for rate limiting, staleness, mode changes, drop statistics,
  and diagnostics payload structure.

2026-05-01: Probe Protocol Hardening
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

2026-05-01: Classifier Core Library
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
  reason codes, flap suppression, override behaviour, snapshots, reset,
  and fuzzy-zone handling.

2026-05-01: Code Review Fixes
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

2026-05-01: Classifier Node Runtime Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Fully wired classifier_node: embeds ProbeClient for active metric
  ingestion, runs periodic evaluation timer at configured evaluate_rate_hz,
  publishes ClassificationDecision JSON to /adaptive_bridge/classifier/state.
- Added config_manager.get_probe_config() public method.
- Added stats_to_probe_metrics() converter in utils/probes.py to bridge
  ProbeClient.get_stats() dict to ProbeMetrics dataclass.
- Published payload includes: subscriber_id, state, reason, ts_ns,
  avg_rtt_ms, loss, hysteresis_counter, consecutive_good, eval_count,
  error_count, and confidence (reserved).
- Classifier output topic contract documented in
  docs/05_CLASSIFIER_AND_PROBES.md.
- Integration tests: 9 tests covering lifecycle, decision publishing,
  payload structure, state validation, monotonic counters, robustness
  (no-responder operation, recovery after responder appears), and
  metrics conversion.

2026-05-01: Proxy + Classifier Policy Coupling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created PolicyEngine: maps classifier subscriber states to per-topic
  PolicyMode with transition damping (hysteresis_count windows) and
  safety bias (UNKNOWN -> CRITICAL -> NORMAL mode).
- ProxyNode subscribes to /adaptive_bridge/classifier/state and drives
  NoncriticalPolicyEngine mode changes from classifier output.
- Refactored all 5 config._cfg() calls in proxy_node.py to use public
  ConfigManager API (get_qos_profiles_dict, get_topic_qos_profiles_dict,
  get_bridge_config, get_diagnostics_config, get_safety_config).
- Fixed BridgeConfig import source in noncritical_policy.py
  (config_manager -> config_types).
- Added missing type annotation to noncritical_policy._init_topic.
- Policy transition snapshots injected into diagnostics payload.
- 12 unit tests covering policy engine damping, safety bias, forced-critical
  override, and diagnostics snapshot.

2026-05-01: Safety Supervisor and Failure-Mode Runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created SafetySupervisor: pure-Python global mode machine with
  NORMAL -> DEGRADED -> EMERGENCY -> FAILURE transitions, gated by
  hysteresis windows (3 consecutive violations to degrade, 5 clean
  windows to recover).
- Integrated into ProxyNode: safety evaluated each diagnostics tick via
  queue pressure and overflow metrics. DEGRADED/EMERGENCY modes override
  all noncritical topics to DISABLED; FAILURE mode triggers shutdown.
- Added EMERGENCY mode to PolicyMode enum in models.py.
- 16 unit tests covering initialization, degrade triggers, escalation,
  recovery cooldowns, terminal FAILURE, edge cases, and enum compliance.

2026-05-01: Security Controls for Control Plane Signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Implemented HMAC signing and verification for classifier decision payloads
  using SHA-256 with configurable shared secret.
- ReplayProtector: per-identity bounded nonce tracking with 30-second
  timestamp window (max 200 entries per identity, oldest evicted).
- SecurityManager: combined sign, verify, replay, and diagnostics counters,
  supporting three modes: off, log_only, enforce.
- Integrated into classifier_node (sign decisions before publish) and
  proxy_node (verify decisions on receive, reject in enforce mode).
- Security stats (invalid_sig_count, replay_count) injected into diagnostics.
- Updated SecurityConfig with hmac_secret, replay_window_ms fields and
  "off" trust_mode option.
- 21 unit tests covering HMAC sign/verify, replay protection, mode
  enforcement, diagnostics counters, and round-trip.

2026-05-01: Launch, Runtime UX, and Config Ergonomics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- adaptive_bridge.launch.py: default config_path now auto-resolves to
  installed default.yaml via get_package_share_directory.
- test_bridge.launch.py: rewritten from empty stub to quickstart launch
  (proxy + classifier on default config).
- adaptive_bridge_full.launch.py: created for full-stack operation
  (proxy + classifier + diagnostics on stress.yaml).
- Added probe_responder console_scripts entry point in setup.py.
- README.md: added Quickstart section, launch profile table, resolved
  absolute paths throughout, updated test count (171+), added safety
  and security modules to module list, cleaned placeholder paths.
- Updated classifier_node description from "wiring in progress" to
  current production state.

2026-05-01: Test Pyramid Completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created test_stress_scenarios.py: 8 tests covering sustained rate
  limiting, token bucket refill, queue overflow, stale drop counters,
  and full safety supervisor recovery cycles.
- Created test_proxy_classifier_integration.py: 4 tests covering
  classifier -> policy -> noncritical mode end-to-end propagation
  and safety override.
- Created src/tests/fixtures/ with shared test helpers (make_test_config,
  sample_probe_stats).
- Updated lint wrapper skip reasons (flake8, pep257) from stale
  "Step 1" reference to current Step 15+ context.
- Total test count: 171 -> 183 (12 new tests).

2026-05-02: Evaluation Workspace (WS2) and Classifier Threshold Tuning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created ``eval/`` (WS2, inside adaptive_bridge_ws): evaluation harness for
  reproducible baseline-vs-adaptive experiments under controlled network
  impairment.
- Switched from constant-delay/independent-loss tc model to Gilbert-Elliot
  bursty loss channel model (``tc netem loss gemodel``).  GE produces
  short high-loss bursts separated by clean periods, matching real IEEE
  802.11 channel contention behaviour and triggering DDS backpressure at
  realistic average loss rates (2.3% to 9.2%).
- Delay uses normal distribution (mean ± stddev) for realistic RTT variation.
- Three impairment levels: mild (2.3% avg), moderate (5.4% avg), strong
  (9.2% avg).  Scenario gradient enables spectrum analysis.
- 10 experiment scenarios defined in ``scenarios.yaml`` covering baseline,
  adaptive bridge, toggle impairment, and ablation.
- Evaluation nodes package (``eval_nodes``) created as a standalone ROS2
  package depending on ``adaptive_bridge``: downstream-user perspective.
- Orchestration: one-command runner (``run_experiment.py``), tc manager
  with ``ifb`` ingress shaping for adaptive mode, post-run summary/plot
  generation (``generate_summary.py``, ``plot_results.py``).
- Results output follows strict ``10_RESULTS_FORMAT.md`` layout.
- Classifier thresholds re-tuned in WS1 shipped configs:
  ``demote_loss_threshold`` from 10% → 4%, ``demote_rtt_ms`` from 120ms → 80ms,
  ``evaluate_rate_hz`` from 1Hz → 2Hz.  Applied to all three YAML configs
  (``default``, ``minimal``, ``stress``).
- WS2 evaluation config uses experiment-tuned thresholds (demote_loss 1.5%)
   appropriate for controlled Docker impairment with near-zero baseline loss.

2026-05-05: Cross-RMW Validation and Packaging
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Full 10-scenario evaluation matrix executed on **Cyclone DDS** (Eclipse)
  alongside the existing Fast DDS results.
- Created ``eval/docker/cyclonedds_profiles.xml``: UDP-only transport,
  ``AllowMulticast=spdp`` (unicast data), ``WhcHigh=600kiB`` byte-based
  WHC watermark (~200 LaserScan messages), ``WhcAdaptive=false``.
- Added dynamic RMW injection to ``run_experiment.py`` (``--rmw`` flag):
  substitutes compose-file values at runtime: no separate compose files
  needed per RMW.
- Fixed Cyclone DDS impairment: ``AllowMulticast=spdp`` forces unicast
  data so the tc filter (``ip dst <sub_ip>``) matches correctly.
- Documented 9 symmetrical behavioural differences between Fast DDS and
  Cyclone DDS in ``docs/17_RMW_COMPATIBILITY_MATRIX.md``:
  blocking vs non-blocking publish, sample-count vs byte-based backpressure,
  46-58× packet count disparity (retransmission strategy), unicast vs
  multicast data distribution defaults, throughput measurement window
  variation, classifier oscillation characteristics.
- Three robustness fixes to ``run_experiment.py``:
  - ``shutil.rmtree`` → ``sudo rm -rf`` for root-owned Docker volume cleanup.
  - Container startup failure now runs ``docker compose down`` before
    ``continue`` (prevents orphaned-container cascades).
  - Metadata ``completed`` field set to ``false`` on failure with descriptive
    ``failure_reason``.
- Added module-level docstrings to ``config_manager.py``, ``config_types.py``,
  ``qos_manager.py``, ``topic_registry.py``, ``models.py``, and
  ``noncritical_policy.py``.
- Comprehensive README rewrite with shields.io badges, architecture diagram,
  evaluation harness documentation, RMW compatibility table, and
  troubleshooting section.
- Created ``CONTRIBUTING.md`` with contribution guidelines.
- ``package.xml`` and ``setup.py`` verified for maintainer/license consistency.

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
