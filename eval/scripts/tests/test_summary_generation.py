# scripts/tests/test_summary_generation.py
"""Validate generate_summary.py produces correct output from mock CSV data."""
import csv
import os
import sys
import tempfile
import yaml

# Add scripts dir to path to import generate_summary
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_summary_from_mock_data():
    """Create mock CSVs and verify summary outputs correct stats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = os.path.join(tmpdir, "test_run")
        metrics_dir = os.path.join(run_dir, "metrics")
        summary_dir = os.path.join(run_dir, "summary")
        os.makedirs(metrics_dir, exist_ok=True)
        os.makedirs(summary_dir, exist_ok=True)

        # Mock latency.csv
        with open(os.path.join(metrics_dir, "latency.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_ns", "topic", "source_node", "target_node", "seq", "msg_age_ms", "e2e_latency_ms"])
            for i in range(100):
                writer.writerow([1000000000 + i * 10000000, "/scan", "publisher", "critical_subscriber", i, i * 0.1, i * 0.1 + 5.0])
            for i in range(50):
                writer.writerow([1000000000 + i * 10000000, "/scan", "publisher", "slow_subscriber", i, i * 0.2, i * 0.2 + 15.0])

        # Mock throughput.csv
        with open(os.path.join(metrics_dir, "throughput.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_ns", "topic", "node", "rate_hz", "window_s"])
            for i in range(20):
                writer.writerow([1000000000 + i * 5000000000, "/scan", "observer", 29.5 + (i % 3) * 0.3, 5.0])

        # Mock drops.csv
        with open(os.path.join(metrics_dir, "drops.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_ns", "topic", "node", "dropped_count", "total_received", "total_expected", "drop_rate"])
            writer.writerow([1000000000, "/scan", "critical_subscriber", 0, 100, 100, 0.0])
            writer.writerow([1000000000, "/scan", "slow_subscriber", 3, 47, 50, 0.06])

        # Mock cpu.csv
        with open(os.path.join(metrics_dir, "cpu.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_ns", "node", "cpu_percent", "mem_mb", "threads"])
            for i in range(5):
                writer.writerow([1000000000 + i * 1000000000, "observer", 5.0 + i, 100, 1])

        # Mock classifier.csv
        with open(os.path.join(metrics_dir, "classifier.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp_ns", "subscriber_id", "subscriber_node", "state", "confidence", "reason"])
            writer.writerow([1000000000, "test", "test", "CRITICAL", "", "stable"])
            writer.writerow([2000000000, "test", "test", "CRITICAL", "", "stable"])
            writer.writerow([3000000000, "test", "test", "NONCRITICAL", "", "high_loss"])
            writer.writerow([4000000000, "test", "test", "NONCRITICAL", "", "high_loss"])

        # Run summary generation
        import generate_summary
        generate_summary.main_called = False
        # Patch argparse
        old_argv = sys.argv
        sys.argv = ["generate_summary.py", "--run-dir", run_dir]
        try:
            generate_summary.main()
        finally:
            sys.argv = old_argv

        # Verify outputs
        assert os.path.exists(os.path.join(summary_dir, "summary_stats.yaml"))
        assert os.path.exists(os.path.join(summary_dir, "table_results.csv"))
        assert os.path.exists(os.path.join(summary_dir, "report.md"))

        with open(os.path.join(summary_dir, "summary_stats.yaml")) as f:
            stats = yaml.safe_load(f)
        assert stats["critical_latency_ms"]["p50"] > 0
        assert stats["noncritical_latency_ms"]["mean"] > 0
        assert stats["publisher_rate_hz"]["mean"] > 25
        assert stats["critical_drop_rate"]["mean"] == 0.0
        assert stats["noncritical_drop_rate"]["mean"] > 0.0
        assert stats["classifier_transitions"] == 1
