# Adaptive Bridge Evaluation Workspace (WS2)

Workspace for reproducible baseline-vs-adaptive experiments under controlled
network impairment using the Gilbert-Elliot bursty loss channel model.

## Prerequisites

- Docker (all commands require `sudo`)
- ROS 2 Jazzy sourced
- WS1 (`adaptive_bridge_ws`) built and installed
- Python 3 packages: `pyyaml`, `matplotlib`, `numpy`

## Quickstart

```bash
cd /home/kaushalraj/adaptive_bridge_ws/eval

# Build the Docker image once
sudo docker build -t adaptive_bridge_eval:latest -f docker/Dockerfile .

# Run a quick smoke test (60s, clean baseline)
sudo python3 scripts/run_experiment.py \
    --scenario baseline_clean \
    --duration 60 \
    --output-dir /home/kaushalraj/adaptive_bridge_ws/eval/results \
    --skip-build

# View results
find results/latest -type f | sort
cat results/latest/summary/summary_stats.yaml
```

## Scenarios

| Name | Mode | Impairment | Duration |
|------|------|------------|----------|
| baseline_clean | baseline | none | 120s |
| baseline_mild | baseline | GE ~2.3% avg loss | 180s |
| baseline_moderate | baseline | GE ~7.1% avg loss | 180s |
| baseline_strong | baseline | GE ~9.2% avg loss | 180s |
| bridge_clean | adaptive | none | 120s |
| bridge_mild | adaptive | GE ~2.3% avg loss | 180s |
| bridge_moderate | adaptive | GE ~7.1% avg loss | 180s |
| bridge_strong | adaptive | GE ~9.2% avg loss | 180s |
| bridge_toggle | adaptive | toggle moderate (60s) | 240s |
| ablation_no_classifier | adaptive | GE ~7.1% avg loss | 180s |

All scenario parameters defined in `scenarios.yaml`.

## Impairment Model

We use the Gilbert-Elliot two-state Markov bursty loss model (Linux `tc netem loss gemodel`).
This produces short high-loss bursts separated by clean periods, matching real IEEE 802.11
channel contention behaviour.  Loss is applied only to the remote (slow) subscriber; the
critical subscriber operate on a clean network segment.

All impaired scenarios include a 50 Mbps bandwidth cap, representing a realistic
congested modern WiFi uplink.  No software delay emulation is used — the GE loss model
alone drives DDS backpressure without buffer-based delay artifacts.

## Results Format

Results follow the strict layout defined in `docs/10_RESULTS_FORMAT.md`.
Each run produces:

```
results/YYYY-MM-DD_HH-MM-SS_<scenario>/
  run_metadata.yaml
  system_info.yaml
  metrics/  (latency.csv, throughput.csv, drops.csv, cpu.csv, classifier.csv, probe.csv)
  logs/     (one .log file per node + docker_compose.log)
  raw/      (tc_qdisc_show.txt, docker_stats.txt)
  plots/    (latency CDFs, time series, classifier timeline)
  summary/  (summary_stats.yaml, table_results.csv, report.md)
```

## Adding a New Scenario

1. Add an entry to `scenarios.yaml` with required fields
2. No code changes needed — the orchestrator reads `scenarios.yaml` dynamically

## Troubleshooting

- **Docker permission denied**: Use `sudo` or add user to `docker` group
- **ifb module not loaded**: `sudo modprobe ifb` (one-time)
- **Containers not starting**: Check `docker compose logs`
- **tc not producing visible effect**: Verify with ping test between containers
