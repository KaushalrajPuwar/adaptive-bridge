#!/usr/bin/env python3
"""
plot_results.py — Generate required PNG plots from experiment CSVs.

Outputs (per 10_RESULTS_FORMAT.md):
  plots/latency_cdf_critical.png
  plots/latency_cdf_noncritical.png
  plots/throughput_time_series.png
  plots/drops_time_series.png
  plots/cpu_time_series.png
  plots/classifier_state_timeline.png

Uses matplotlib (Agg backend — no display needed).
"""
import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        header_fields = reader.fieldnames or []
        for row in reader:
            # Filter out accidentally duplicated header rows
            first_key = (header_fields[0] if header_fields else "")
            if first_key and row.get(first_key) == first_key:
                continue
            rows.append(row)
        return rows


def cdf(vals: list[float]):
    """Return (x, y) for an empirical CDF."""
    svals = sorted(vals)
    n = len(svals)
    return svals, [(i + 1) / n for i in range(n)]


def plot_latency_cdf(rows: list[dict], target: str, output: str, title: str):
    vals = [float(r["e2e_latency_ms"]) for r in rows if r.get("target_node") == target]
    if not vals:
        print(f"[WARN] No {target} latency data")
        return
    x, y = cdf(vals)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(x, y, linewidth=2)
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Cumulative Probability")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_throughput(rows: list[dict], output: str, title: str):
    if not rows:
        return
    topics = sorted(set(r["topic"] for r in rows if "topic" in r))
    fig, ax = plt.subplots(figsize=(8, 4))
    for topic in topics:
        topic_rows = [r for r in rows if r.get("topic") == topic]
        ts = [float(r["timestamp_ns"]) / 1e9 for r in topic_rows]
        rates = [float(r["rate_hz"]) for r in topic_rows]
        if ts and len(ts) > 1:
            t0 = ts[0]
            ts = [t - t0 for t in ts]
        ax.plot(ts, rates, '-', linewidth=1.5, label=topic, alpha=0.8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Rate (Hz)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_drops(rows: list[dict], output: str, title: str):
    if not rows:
        return
    nodes = sorted(set(r["node"] for r in rows if "node" in r))
    fig, ax = plt.subplots(figsize=(8, 4))
    for node in nodes:
        nr = [r for r in rows if r.get("node") == node]
        ts = [float(r["timestamp_ns"]) / 1e9 for r in nr]
        drops = [int(r.get("dropped_count", 0)) for r in nr]
        if ts and len(ts) > 1:
            t0 = ts[0]
            ts = [t - t0 for t in ts]
        ax.plot(ts, drops, '-', linewidth=1.5, label=node, alpha=0.8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Drops per Interval")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_cpu(rows: list[dict], output: str, title: str):
    if not rows:
        return
    ts = [float(r["timestamp_ns"]) / 1e9 for r in rows]
    cpu_vals = [float(r["cpu_percent"]) for r in rows]
    if not ts or len(ts) < 2:
        return
    t0 = ts[0]
    ts = [t - t0 for t in ts]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(ts, cpu_vals, '-', linewidth=2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("CPU (%)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def plot_classifier_timeline(rows: list[dict], output: str, title: str):
    if not rows:
        return
    ts = [float(r["timestamp_ns"]) / 1e9 for r in rows]
    states = [r["state"] for r in rows]
    if not ts or len(ts) < 2:
        return
    t0 = ts[0]
    ts = [t - t0 for t in ts]
    state_map = {"CRITICAL": 1, "NONCRITICAL": 0, "UNKNOWN": 0, "FORCED_CRITICAL": 1}
    y_vals = [state_map.get(s, -1) for s in states]
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(ts, y_vals, '-', linewidth=2, drawstyle='steps-post')
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("State")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["NONCRITICAL", "CRITICAL"])
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Generate plots from experiment CSVs")
    parser.add_argument("--run-dir", required=True, help="Path to run folder")
    args = parser.parse_args()
    run_dir = args.run_dir
    metrics_dir = os.path.join(run_dir, "metrics")
    plots_dir = os.path.join(run_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)

    # Run folder format: YYYY-MM-DD_HH-MM-SS_<scenario_name>
    scenario = os.path.basename(run_dir).split("_", 2)[-1] if "_" in os.path.basename(run_dir) else "unknown"

    latency_rows = read_csv(os.path.join(metrics_dir, "latency.csv"))
    throughput_rows = read_csv(os.path.join(metrics_dir, "throughput.csv"))
    drops_rows = read_csv(os.path.join(metrics_dir, "drops.csv"))
    cpu_rows = read_csv(os.path.join(metrics_dir, "cpu.csv"))
    classifier_rows = read_csv(os.path.join(metrics_dir, "classifier.csv"))

    plot_latency_cdf(latency_rows, "critical_subscriber",
                     os.path.join(plots_dir, "latency_cdf_critical.png"),
                     f"Critical Subscriber Latency CDF — {scenario}")

    plot_latency_cdf(latency_rows, "slow_subscriber",
                     os.path.join(plots_dir, "latency_cdf_noncritical.png"),
                     f"Noncritical Subscriber Latency CDF — {scenario}")

    plot_throughput(throughput_rows,
                    os.path.join(plots_dir, "throughput_time_series.png"),
                    f"Throughput — {scenario}")

    plot_drops(drops_rows,
               os.path.join(plots_dir, "drops_time_series.png"),
               f"Drop Events — {scenario}")

    plot_cpu(cpu_rows,
             os.path.join(plots_dir, "cpu_time_series.png"),
             f"CPU Usage — {scenario}")

    plot_classifier_timeline(classifier_rows,
                             os.path.join(plots_dir, "classifier_state_timeline.png"),
                             f"Classifier State — {scenario}")

    print(f"[INFO] Plots written to {plots_dir}/")


if __name__ == "__main__":
    main()
