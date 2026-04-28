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
