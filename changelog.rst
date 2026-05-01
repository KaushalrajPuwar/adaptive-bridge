Adaptive Bridge Project Changelog
================================

This changelog records the evolution of the Adaptive Bridge project based on the authoritative `docs/11_DECISIONS_LOG.md`.

v0.1.0 (Prototype Development - 2026-04-28)
------------------------------------------

Implemented Prototype Capabilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prototype implementation present:

- Proxy node with LaserScan forwarding
- Basic QoS and config managers
- Diagnostics and probe utilities

In-Progress Roadmap Work
~~~~~~~~~~~~~~~~~~~~~~~~

Following roadmap in ``docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md``

- Steps 0-20 execution in progress
- Current focus: Configuration contract and schema validation (Step 2)

Step 1 Completion (Repository Hygiene and Build Determinism)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Repository hygiene updates completed for packaging/test baseline.
- Deterministic build/test command sequence validated from clean workspace.
- Empty smoke-test blind spots removed (`src/tests/*` populated).
- Config asset packaging path validated with `src/adaptive_bridge/config/default.yaml`.

Step 2 Completion (Configuration Contract and Schema Validation)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Introduced typed configuration contract via `adaptive_bridge/config_types.py`.
- Reworked `ConfigManager` to load/normalize/validate strict schema and expose typed getters.
- Added backward compatibility mode for legacy keys with `DeprecationWarning`.
- Added `minimal.yaml` and `stress.yaml` sample configs and upgraded `default.yaml` to full Step 2 schema.
- Added validation-focused tests for missing sections, bad thresholds/rates, unknown QoS profiles, duplicate topic IDs, and legacy compatibility path.

Step 3 Completion (Internal Data Models and Topic Registry)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Added shared runtime model layer (`models.py`) for routes, counters, policy mode, classifier snapshot, and per-topic runtime state.
- Added deterministic `TopicRegistry` with topic sanitizer, route build helpers, route export helpers, and strict uniqueness enforcement.
- Updated proxy to consume `TopicRegistry` route objects and model-backed counters (single-route behavior preserved pending Step 4).
- Updated diagnostics/classifier placeholder to align with Step 3 shared model contracts.
- Expanded proxy-basic tests for registry/topic determinism, uniqueness failures, and model serialization behavior.

Step 4 Completion (Proxy Core v2: Multi-Topic, Precreated Endpoints)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Upgraded proxy runtime to build all configured topic routes and pre-create per-topic subscribers plus critical/noncritical publishers at startup.
- Added callback-factory forwarding path keyed by `topic_id`, with per-topic counters and periodic per-topic forwarding logs.
- Added explicit safe shutdown cleanup for all pre-created subscribers and publishers.
- Updated launch file to support explicit `config_path` launch argument for multi-topic configuration runs.
- Expanded proxy tests to validate multi-topic route build ordering, callback topic isolation, and shutdown entity cleanup behavior.

Step 5 Completion (QoS Manager v2 and Policy Catalog)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Upgraded QoSManager to decouple from ConfigManager and parse generic dictionary mappings.
- Extracted RMW-incompatible lifespan_ms handling to proxy application logic exposed via describe().
- Updated proxy_node.py to correctly initialize and use QoSManager.resolve().
- Added python3-yaml as exec_depend to package.xml.
- Fixed Python packaging to correctly bundle utils/*.yaml during colcon build.
- Created QoS matrix documentation in docs/15_QOS_MATRIX.md.

Step 6 Completion (Noncritical Degradation Engine)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created NoncriticalPolicyEngine with token-bucket rate limiter, staleness-based TTL drops, and mode-disabled drops.
- Integrated into ProxyNode with isolated threading and asynchronous queueing for the noncritical pathway.
- Critical publish thread guaranteed not blocked by noncritical policy code.
- Added unit tests for rate limiting, staleness, mode changes, and drop statistics.

Step 7 Completion (Diagnostics Contract and Observability Backbone)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Created diagnostics_schema.py with v1.0 schema definition and validate_payload() validator.
- Refactored diagnostics.py into pure DjangoCollector (no ROS dependency) + DiagnosticsPublisher wrapper.
- ProxyNode owns ROS publisher + timer for diagnostics at publish_interval_s.
- Payload includes: schema_version, ts_wall, seq, mode, topics, classifier, qos sections.
- 15 new unit tests + updated proxy tests. Diagnostics payload schema-versioned and machine-parseable.

Step 8 Completion (Probe Protocol Hardening)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Probe payloads versioned (v=1) with monotonic nanosecond timestamps.
- Outstanding sequence map bounded at window_size * 3 to prevent unbounded memory growth.
- Sliding-window loss rate (not lifetime-cumulative), RTT, and jitter metrics.
- Configurable probe timeout (timeout_ms) with stale response rejection.
- Receive-side sanity checks: malformed JSON, unknown seq, wrong protocol version, stale RTT, zero/negative seq.
- ProbeResponder now injects recv_time_ns, reply_time_ns, response_send_time_ns, and responder_id.
- Config: timeout_ms added to ProbeConfig and all three YAML configs (default/minimal/stress).
- 30 new unit tests in src/tests/test_probes.py covering payload format, sanity checks, bounded storage, rolling metrics, get_stats() contract, and round-trip end-to-end.

Architecture & Core Design
~~~~~~~~~~~~~~~~~~~~~~~~~~

*   **D001: Multi-Workspace Strategy**: Design decision accepted and active in project workflow.
*   **D002: Proxy-Based isolation**: Design decision accepted; prototype implementation present via proxy node.
*   **D003: Dual Output Streams**: Design decision accepted; prototype implementation present for `/scan`.
*   **D004: Static Publisher Lifecycle**: Design decision accepted; startup publisher creation behavior present in prototype.
*   **D005: Policy-Based Classification**: Design decision accepted; full classifier-policy runtime implementation pending.
*   **D020: Stateless Forwarding**: Design decision accepted; compatible with current proxy prototype.
*   **D022: Multi-Proxy Scaling**: Design decision accepted; implementation pending.

Classifier & Network Monitoring
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*   **D006: Active Network Probing**: Design decision accepted; probe utilities present in prototype.
*   **D008: Stability Mechanism**: Design decision accepted; full classifier hysteresis pipeline pending.
*   **D009: Deterministic Overrides**: Design decision accepted; partial config support present, full classifier integration pending.

Safety & Mitigation Policies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*   **D010: Internal Load Shedding**: Design decision accepted; production-grade noncritical load-shedding implementation pending.
*   **D011: Critical Path Fidelity**: Design decision accepted; enforced as roadmap constraint.
*   **D012: Non-Critical Degradation**: Design decision accepted; partial QoS behavior present, full adaptive degradation pending.

Environment & Dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~

*   **D013: Transport Forcing**: Design decision accepted for baseline/eval workflow.
*   **D024: Sensor-Ready Implementation**: Prototype implementation present (`sensor_msgs/LaserScan` forwarding path).
*   **D025: Add sensor_msgs Dependency**: Prototype implementation present in package dependency configuration.

Evaluation & Metrics
~~~~~~~~~~~~~~~~~~~~

*   **D016: Tuned Baseline Comparison**: Design decision accepted; full evaluation implementation pending.
*   **D017: Distribution-Based Metrics**: Design decision accepted; full metrics pipeline implementation pending.
*   **D018: Multi-RMW Validation**: Design decision accepted; qualification phase pending.

Change Control
~~~~~~~~~~~~~~

Architecture decisions are recorded in ``docs/11_DECISIONS_LOG.md``.
Architecture updates require the explicit decision-log process in ``docs/11_DECISIONS_LOG.md``.
Execution sequence follows ``docs/14_PRODUCTION_DEVELOPMENT_ROADMAP.md``.
