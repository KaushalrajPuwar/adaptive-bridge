#!/usr/bin/env python3
"""
generate_summary.py — Aggregate experiment CSV metrics into summary statistics.

Produces:
  summary/summary_stats.yaml    — headline metrics (p50/p95/p99 latency, etc.)
  summary/table_results.csv     — single-row paper-table format
  summary/report.md             — human-readable summary
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from typing import Any

import yaml


def read_csv(path: str) -> list[dict]:
    """Read CSV file into list of dicts. Returns empty list if missing/empty."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        header_fields = reader.fieldnames or []
        for row in reader:
            # Filter out accidentally duplicated header rows
            first_key = (header_fields[0] if header_fields else "")
            if first_key and row.get(first_key) == first_key:
                continue
            rows.append(row)
    return rows


def percentile(sorted_vals: list[float], p: float) -> float:
    """Compute p-th percentile (0-100)."""
    if not sorted_vals:
        return 0.0
    idx = max(0, min(len(sorted_vals) - 1, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def compute_latency_stats(rows: list[dict], target_node: str) -> dict:
    """Compute latency percentiles for a specific target_node."""
    vals = [float(r["e2e_latency_ms"]) for r in rows if r.get("target_node") == target_node]
    if not vals:
        return {"p50": 0, "p90": 0, "p95": 0, "p99": 0, "max": 0, "mean": 0, "count": 0}
    svals = sorted(vals)
    return {
        "p50": round(percentile(svals, 50), 2),
        "p90": round(percentile(svals, 90), 2),
        "p95": round(percentile(svals, 95), 2),
        "p99": round(percentile(svals, 99), 2),
        "max": round(max(svals), 2),
        "mean": round(sum(vals) / len(vals), 2),
        "count": len(vals),
    }


def compute_drop_stats(rows: list[dict]) -> dict:
    """Compute mean drop rate from drops.csv."""
    rates = [float(r["drop_rate"]) for r in rows if "drop_rate" in r]
    if not rates:
        return {"mean": 0.0, "count": 0}
    return {"mean": round(sum(rates) / len(rates), 4), "count": len(rates)}


def compute_throughput_stats(rows: list[dict], topic: str) -> dict:
    """Compute mean/std publish rate for a topic."""
    rates = [float(r["rate_hz"]) for r in rows if r.get("topic") == topic]
    if not rates:
        return {"mean": 0, "std": 0, "count": 0}
    mean = sum(rates) / len(rates)
    var = sum((r - mean) ** 2 for r in rates) / len(rates)
    return {"mean": round(mean, 2), "std": round(var ** 0.5, 2), "count": len(rates)}


def compute_cpu_stats(rows: list[dict]) -> dict:
    vals = [float(r["cpu_percent"]) for r in rows if "cpu_percent" in r]
    if not vals:
        return {"mean": 0, "max": 0, "count": 0}
    return {"mean": round(sum(vals) / len(vals), 2), "max": round(max(vals), 2), "count": len(vals)}


def count_classifier_transitions(rows: list[dict]) -> int:
    """Count state transitions (changes from prev row)."""
    states = [r["state"] for r in rows if "state" in r]
    if len(states) < 2:
        return 0
    return sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])


def main():
    parser = argparse.ArgumentParser(description="Generate summary from experiment CSVs")
    parser.add_argument("--run-dir", required=True, help="Path to run folder")
    args = parser.parse_args()
    run_dir = args.run_dir
    metrics_dir = os.path.join(run_dir, "metrics")
    summary_dir = os.path.join(run_dir, "summary")
    os.makedirs(summary_dir, exist_ok=True)

    latency_rows = read_csv(os.path.join(metrics_dir, "latency.csv"))
    throughput_rows = read_csv(os.path.join(metrics_dir, "throughput.csv"))
    drops_rows = read_csv(os.path.join(metrics_dir, "drops.csv"))
    cpu_rows = read_csv(os.path.join(metrics_dir, "cpu.csv"))
    classifier_rows = read_csv(os.path.join(metrics_dir, "classifier.csv"))

    crit_lat = compute_latency_stats(latency_rows, "critical_subscriber")
    noncrit_lat = compute_latency_stats(latency_rows, "slow_subscriber")
    crit_drops = compute_drop_stats([r for r in drops_rows if r.get("node") == "critical_subscriber"])
    noncrit_drops = compute_drop_stats([r for r in drops_rows if r.get("node") == "slow_subscriber"])

    # Read actual duration and RMW from metadata
    duration_s = 0
    rmw_impl = "unknown"
    dds_vendor = "unknown"
    metadata_path = os.path.join(run_dir, "run_metadata.yaml")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path) as f:
                meta = yaml.safe_load(f)
            duration_s = meta.get("duration_s", 0)
            rmw_impl = meta.get("rmw_implementation", "unknown")
            dds_vendor = meta.get("dds_vendor", "unknown")
        except Exception:
            pass

    pub_rate = compute_throughput_stats(throughput_rows, "/scan")
    # Fallback: if no observer throughput.csv, compute rate from critical subscriber
    if pub_rate["count"] == 0 and duration_s > 0 and crit_lat["count"] > 0:
        pub_rate = {"mean": round(crit_lat["count"] / duration_s, 2), "std": 0, "count": crit_lat["count"]}
    cpu = compute_cpu_stats(cpu_rows)
    transitions = count_classifier_transitions(classifier_rows)

    # Run folder format: YYYY-MM-DD_HH-MM-SS_<scenario_name>
    # Split on first 2 underscores to keep full scenario name intact
    scenario = os.path.basename(run_dir).split("_", 2)[-1] if "_" in os.path.basename(run_dir) else "unknown"

    # summary_stats.yaml
    yaml_content = f"""scenario: {scenario}
rmw_implementation: "{rmw_impl}"
dds_vendor: "{dds_vendor}"
duration_s: {duration_s}

critical_latency_ms:
  p50: {crit_lat['p50']}
  p90: {crit_lat['p90']}
  p95: {crit_lat['p95']}
  p99: {crit_lat['p99']}
  max: {crit_lat['max']}
  mean: {crit_lat['mean']}

noncritical_latency_ms:
  p50: {noncrit_lat['p50']}
  p90: {noncrit_lat['p90']}
  p95: {noncrit_lat['p95']}
  p99: {noncrit_lat['p99']}
  max: {noncrit_lat['max']}
  mean: {noncrit_lat['mean']}

publisher_rate_hz:
  mean: {pub_rate['mean']}
  std: {pub_rate['std']}

critical_drop_rate:
  mean: {crit_drops['mean']}

noncritical_drop_rate:
  mean: {noncrit_drops['mean']}

proxy_cpu_percent:
  mean: {cpu['mean']}
  max: {cpu['max']}

classifier_transitions: {transitions}
"""
    with open(os.path.join(summary_dir, "summary_stats.yaml"), "w") as f:
        f.write(yaml_content)

    # table_results.csv
    with open(os.path.join(summary_dir, "table_results.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "scenario", "rmw_implementation", "duration_s", "crit_p50_ms", "crit_p99_ms", "crit_max_ms",
            "crit_drop_mean", "noncrit_p50_ms", "noncrit_p99_ms", "noncrit_drop_mean",
            "pub_rate_mean_hz", "proxy_cpu_mean",
        ])
        writer.writerow([
            scenario, rmw_impl, str(duration_s), crit_lat['p50'], crit_lat['p99'], crit_lat['max'],
            crit_drops['mean'], noncrit_lat['p50'], noncrit_lat['p99'],
            noncrit_drops['mean'], pub_rate['mean'], cpu['mean'],
        ])

    # report.md
    md_content = f"""# Results: {scenario}

**RMW:** {rmw_impl} ({dds_vendor})

## Critical Subscriber Latency
| p50 | p95 | p99 | max |
|-----|-----|-----|-----|
| {crit_lat['p50']} ms | {crit_lat['p95']} ms | {crit_lat['p99']} ms | {crit_lat['max']} ms |

## Noncritical Subscriber Latency
| p50 | p95 | p99 | max |
|-----|-----|-----|-----|
| {noncrit_lat['p50']} ms | {noncrit_lat['p95']} ms | {noncrit_lat['p99']} ms | {noncrit_lat['max']} ms |

## Publisher Rate
Mean: {pub_rate['mean']} Hz | Std: {pub_rate['std']}

## Drops
Critical: {crit_drops['mean']} | Noncritical: {noncrit_drops['mean']}

## CPU (container proxy)
Mean: {cpu['mean']}% | Max: {cpu['max']}%
"""
    with open(os.path.join(summary_dir, "report.md"), "w") as f:
        f.write(md_content)

    print(f"[INFO] Summary written to {summary_dir}/")
    print(f"  critical latency: p50={crit_lat['p50']}ms p99={crit_lat['p99']}ms")
    print(f"  publisher rate: {pub_rate['mean']}Hz")
    print(f"  critical drops: {crit_drops['mean']}")
    print(f"  classifier transitions: {transitions}")


if __name__ == "__main__":
    main()
