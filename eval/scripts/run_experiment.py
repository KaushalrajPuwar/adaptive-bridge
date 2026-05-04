#!/usr/bin/env python3
"""
run_experiment.py — One-command experiment orchestrator for WS2.

Usage:
  sudo python3 scripts/run_experiment.py \\
      --scenario baseline_mild \\
      --duration 180 \\
      --output-dir /home/kaushalraj/adaptive_bridge_ws/eval/results \\
      --repetitions 3 \\
      --skip-build
"""
import argparse
import datetime
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml


_SCRIPT_DIR = Path(__file__).resolve().parent
_WS2_DIR = _SCRIPT_DIR.parent

# RMW-specific substitution tables for compose file injection
_RMW_SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "rmw_cyclonedds_cpp": [
        ("RMW_IMPLEMENTATION=rmw_fastrtps_cpp",
         "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp"),
        ("FASTRTPS_DEFAULT_PROFILES_FILE=",
         "CYCLONEDDS_URI=file://"),
        ("fastdds_profiles.xml",
         "cyclonedds_profiles.xml"),
    ],
    # Add rows here to support additional RMW implementations
}


def _inject_rmw(compose_text: str, rmw_impl: str) -> str:
    """Return compose YAML with RMW-specific substitutions applied.

    For ``rmw_fastrtps_cpp`` (default) the text is returned unchanged.
    For other RMWs the ``_RMW_SUBSTITUTIONS`` table is applied in order.
    """
    if rmw_impl == "rmw_fastrtps_cpp":
        return compose_text
    subs = _RMW_SUBSTITUTIONS.get(rmw_impl)
    if subs is None:
        raise ValueError(
            f"Unsupported RMW: {rmw_impl}. "
            f"Available: {list(_RMW_SUBSTITUTIONS.keys())}"
        )
    for old, new in subs:
        compose_text = compose_text.replace(old, new)
    return compose_text


def load_scenarios(path: str) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data["scenarios"]


def find_scenario(scenarios: list[dict], name: str) -> Optional[dict]:
    for s in scenarios:
        if s["name"] == name:
            return s
    return None


def run(cmd: list[str], check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command, print it, return result."""
    print(f"[CMD] {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=False, text=True, check=check, timeout=timeout)


def run_capture(cmd: list[str], timeout: int = 30) -> str:
    """Run a command and capture stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def generate_run_metadata(scenario: dict, run_id: str, start_utc: str,
                          duration_s: int, rmw: str = "rmw_fastrtps_cpp") -> str:
    """Generate run_metadata.yaml content."""
    dds_vendor = "FastDDS" if "fastrtps" in rmw.lower() else "CycloneDDS"
    git_commit = ""
    git_branch = ""
    try:
        git_commit = subprocess.run(
            ["git", "-C", str(_WS2_DIR.parent), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        pass
    try:
        git_branch = subprocess.run(
            ["git", "-C", str(_WS2_DIR.parent), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        pass
    return f"""run_id: "{run_id}"
scenario: "{scenario['name']}"
description: "{scenario.get('description', '')}"
start_time_utc: "{start_utc}"
duration_s: {duration_s}
rmw_implementation: "{rmw}"
dds_vendor: "{dds_vendor}"
transport_mode: "udp_only"
shm_disabled: true
docker: true
host_machine: "{os.uname().nodename}"
kernel: "{os.uname().release}"
git_commit: "{git_commit}"
git_branch: "{git_branch}"
completed: true
failure_reason: ""
"""


def apply_impairment(scenario: dict, compose_file: str) -> bool:
    """Run apply_tc.py with scenario impairment parameters.  Returns True on success."""
    imp = scenario["impairment"]
    if not imp.get("enabled"):
        return True
    bw = imp.get("bandwidth_kbit", 0)
    result = subprocess.run(
        ["sudo", sys.executable, str(_SCRIPT_DIR / "apply_tc.py"),
         "--compose-file", compose_file, "--action", "apply",
         "--loss-p", str(imp["loss_p"]),
         "--loss-r", str(imp["loss_r"]),
         "--loss-good-pct", str(imp["loss_good_pct"]),
         "--loss-bad", str(imp["loss_bad_pct"]),
         "--bandwidth", str(bw),
         ], capture_output=False, text=True, check=False)
    if result.returncode != 0:
        print(f"[WARN] apply_tc.py failed (exit {result.returncode})")
        return False
    return True


def clean_impairment(compose_file: str) -> None:
    run(["sudo", sys.executable, str(_SCRIPT_DIR / "apply_tc.py"),
         "--compose-file", compose_file, "--action", "clean"], check=False)


def capture_logs(compose_file: str, run_dir: str) -> None:
    """Dump Docker container logs."""
    logs_dir = os.path.join(run_dir, "logs")
    raw_dir = os.path.join(run_dir, "raw")
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(raw_dir, exist_ok=True)
    try:
        subprocess.run(
            ["sudo", "docker", "compose", "-f", compose_file, "logs", "--no-color"],
            stdout=open(os.path.join(logs_dir, "docker_compose.log"), "w"),
            stderr=subprocess.STDOUT, text=True, check=False, timeout=60,
        )
    except Exception:
        pass
    # Save tc status with packet statistics
    try:
        mode = "baseline" if "baseline" in os.path.basename(compose_file) else "adaptive"
        target_service = "publisher" if mode == "baseline" else "slow_subscriber"
        target_iface = "eth0" if mode == "baseline" else "ifb0"
        cid = run_capture(["sudo", "docker", "compose", "-f", compose_file, "ps", "-q", target_service])
        if cid:
            tc_qdisc = run_capture(["sudo", "docker", "exec", cid, "tc", "-s", "qdisc", "show", "dev", target_iface])
            with open(os.path.join(raw_dir, "tc_qdisc_show.txt"), "w") as f:
                f.write(tc_qdisc or "no tc rules")
            tc_filter = run_capture(["sudo", "docker", "exec", cid, "tc", "-s", "filter", "show", "dev", target_iface])
            with open(os.path.join(raw_dir, "tc_filter_show.txt"), "w") as f:
                f.write(tc_filter or "no filters")
    except Exception:
        pass
    # Save return-path tc from slow_subscriber egress
    try:
        slow_cid = run_capture(["sudo", "docker", "compose", "-f", compose_file, "ps", "-q", "slow_subscriber"])
        if slow_cid:
            return_tc = run_capture(["sudo", "docker", "exec", slow_cid, "tc", "-s", "qdisc", "show", "dev", "eth0"])
            with open(os.path.join(raw_dir, "tc_return_path.txt"), "w") as f:
                f.write(return_tc or "no return-path rules")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="One-command Adaptive Bridge experiment runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n"
               "  sudo python3 run_experiment.py --scenario baseline_mild --duration 180 --skip-build\n"
               "  sudo python3 run_experiment.py --scenario bridge_mild --duration 180 --repetitions 3",
    )
    parser.add_argument("--scenario", required=True, help="Scenario name from scenarios.yaml")
    parser.add_argument("--duration", type=int, default=None, help="Override scenario duration (seconds)")
    parser.add_argument("--output-dir", default=str(_WS2_DIR / "results"), help="Results directory")
    parser.add_argument("--repetitions", type=int, default=1, help="Number of repetitions")
    parser.add_argument("--skip-build", action="store_true", help="Skip Docker image build")
    parser.add_argument("--rmw", default="rmw_fastrtps_cpp", help="RMW implementation")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, don't run")
    args = parser.parse_args()

    scenarios_yaml = str(_WS2_DIR / "scenarios.yaml")
    if not os.path.exists(scenarios_yaml):
        print(f"[ERROR] scenarios.yaml not found at {scenarios_yaml}")
        sys.exit(1)

    all_scenarios = load_scenarios(scenarios_yaml)
    scenario = find_scenario(all_scenarios, args.scenario)
    if scenario is None:
        available = [s["name"] for s in all_scenarios]
        print(f"[ERROR] Scenario '{args.scenario}' not found.")
        print(f"Available: {', '.join(available)}")
        sys.exit(1)

    duration = args.duration or scenario["duration_s"]

    if args.dry_run:
        print(f"[DRY-RUN] Scenario: {scenario['name']} | Duration: {duration}s | Repetitions: {args.repetitions}")
        print(f"[DRY-RUN] Compose: {scenario['compose_file']} | Impairment: {scenario.get('impairment', {}).get('enabled', False)}")
        sys.exit(0)

    compose_file = str(_WS2_DIR / scenario["compose_file"])
    _original_compose = compose_file  # saved so we can clean up temp files later
    if not os.path.exists(compose_file):
        print(f"[ERROR] Compose file not found: {compose_file}")
        sys.exit(1)

    # RMW injection — substitute compose file values when not using default FastDDS
    if args.rmw != "rmw_fastrtps_cpp":
        with open(compose_file) as f:
            original = f.read()
        modified = _inject_rmw(original, args.rmw)
        # Sanity check: verify that the substitution actually changed something
        if modified == original:
            print(f"[WARN] RMW injection produced no changes for {args.rmw} — "
                  f"check _RMW_SUBSTITUTIONS table")
        tmp_path = compose_file + "." + args.rmw.replace("/", "_") + ".yml"
        with open(tmp_path, "w") as f:
            f.write(modified)
        compose_file = tmp_path
        print(f"[INFO] RMW injection: using {os.path.basename(tmp_path)}")

    # Build Docker image (unless skip)
    if not args.skip_build:
        print("[INFO] Building Docker image...")
        run(["sudo", "docker", "build", "-t", "adaptive_bridge_eval:latest",
             "-f", str(_WS2_DIR / "docker" / "Dockerfile"), str(_WS2_DIR)],
            timeout=600)

    os.makedirs(args.output_dir, exist_ok=True)

    def _cleanup_on_interrupt(signum, frame):
        print("\n[WARN] Interrupted — cleaning up containers...")
        clean_impairment(compose_file)
        run(["sudo", "docker", "compose", "-f", compose_file, "down", "-v", "--remove-orphans"],
            check=False, timeout=60)
        if compose_file != _original_compose:
            try:
                os.remove(compose_file)
            except Exception:
                pass
        sys.exit(1)

    signal.signal(signal.SIGINT, _cleanup_on_interrupt)
    signal.signal(signal.SIGTERM, _cleanup_on_interrupt)

    for rep in range(1, args.repetitions + 1):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = f"{timestamp}_{scenario['name']}"
        run_dir = os.path.join(args.output_dir, run_id)
        os.makedirs(run_dir, exist_ok=True)
        print(f"\n{'='*60}")
        print(f"[RUN {rep}/{args.repetitions}] {run_id}")
        print(f"{'='*60}")

        # Metadata
        start_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(run_dir, "run_metadata.yaml"), "w") as f:
            f.write(generate_run_metadata(scenario, run_id, start_utc, duration, args.rmw))

        # System info
        run([sys.executable, str(_SCRIPT_DIR / "collect_system_info.py"),
             "--output", os.path.join(run_dir, "system_info.yaml"),
             "--ros-distro", "jazzy",
             "--rmw", args.rmw])

        # Create subdirectories
        for sub in ["metrics", "logs", "raw", "plots", "summary"]:
            os.makedirs(os.path.join(run_dir, sub), exist_ok=True)

        # Start containers
        print("[INFO] Starting containers...")
        try:
            run(["sudo", "docker", "compose", "-f", compose_file, "up", "-d",
                 "--remove-orphans"], timeout=120)
        except Exception as e:
            print(f"[ERROR] Container startup failed: {e}")
            # Mark the run as failed in metadata
            metadata_file = os.path.join(run_dir, "run_metadata.yaml")
            try:
                with open(metadata_file, "r") as f:
                    content = f.read()
                content = content.replace("completed: true", "completed: false")
                content = content.replace('failure_reason: ""',
                                         f'failure_reason: "container startup failed: {str(e)[:150]}"')
                with open(metadata_file, "w") as f:
                    f.write(content)
            except Exception:
                pass
            # Best-effort cleanup of partially-started containers
            try:
                subprocess.run(
                    ["sudo", "docker", "compose", "-f", compose_file,
                     "down", "-v", "--remove-orphans"],
                    capture_output=False, check=False, timeout=30)
            except Exception:
                pass
            # Clean up temp compose file if one was created
            if compose_file != _original_compose:
                try:
                    os.remove(compose_file)
                except Exception:
                    pass
            continue

        # Wait for stability (allow full DDS discovery across all containers)
        print("[INFO] Waiting for DDS discovery (25s)...")
        time.sleep(25)

        # Apply impairment (skip pre-apply for toggle — the loop handles it)
        if not scenario.get("toggle"):
            tc_ok = apply_impairment(scenario, compose_file)
            if not tc_ok and scenario.get("impairment", {}).get("enabled"):
                print("[WARN] Impairment application failed — running without network degradation")

        # Run experiment
        print(f"[INFO] Running experiment for {duration}s...")
        start_ns = time.monotonic_ns()
        elapsed = 0
        toggle_state = 0  # 0=clean, 1=impaired (loop starts clean for toggle)
        while elapsed < duration:
            time.sleep(min(10, duration - elapsed))
            elapsed = int((time.monotonic_ns() - start_ns) / 1e9)
            print(f"  [{elapsed}/{duration}s]", end="\r")

            if scenario.get("toggle") and elapsed > 0:
                interval = scenario.get("toggle_interval_s", 60)
                current_toggle = (elapsed // interval) % 2
                if current_toggle != toggle_state:
                    toggle_state = current_toggle
                    if toggle_state == 1:
                        print(f"\n  [TOGGLE ON at {elapsed}s]")
                        tc_ok = apply_impairment(scenario, compose_file)
                        if not tc_ok:
                            print("[WARN] Toggle apply_tc failed — impairment not applied")
                    else:
                        print(f"\n  [TOGGLE OFF at {elapsed}s]")
                        clean_impairment(compose_file)
        print()

        # Capture raw data
        print("[INFO] Capturing logs and raw data...")
        capture_logs(compose_file, run_dir)

        # Stop containers
        print("[INFO] Stopping containers...")
        clean_impairment(compose_file)
        run(["sudo", "docker", "compose", "-f", compose_file, "down", "-v", "--remove-orphans"],
            check=False, timeout=60)

        # Clean up temp compose file if one was created by RMW injection
        if compose_file != _original_compose:
            try:
                os.remove(compose_file)
                print(f"[INFO] Cleaned up temp compose file: {os.path.basename(compose_file)}")
            except Exception as exc:
                print(f"[WARN] Could not clean up temp compose file: {exc}")

        # Copy CSVs from shared volume into run folder
        shared_metrics = os.path.join(args.output_dir, "metrics")
        if os.path.isdir(shared_metrics):
            for csv_file in os.listdir(shared_metrics):
                if csv_file.endswith(".csv"):
                    src = os.path.join(shared_metrics, csv_file)
                    dst = os.path.join(run_dir, "metrics", csv_file)
                    shutil.copy2(src, dst)
                    print(f"  [CSV] copied {csv_file} to run folder")
            # Clean shared directory for next run (after a brief settle)
            # Use sudo rm -rf because containers write files as root,
            # so shutil.rmtree (which runs as the invoking user) would
            # silently fail to delete root-owned files.
            time.sleep(0.5)
            subprocess.run(["sudo", "rm", "-rf", shared_metrics], check=False)

        # Post-run processing for EVERY repetition
        print("[INFO] Generating summary and plots...")
        run([sys.executable, str(_SCRIPT_DIR / "generate_summary.py"),
             "--run-dir", run_dir], check=False, timeout=60)
        run([sys.executable, str(_SCRIPT_DIR / "plot_results.py"),
             "--run-dir", run_dir], check=False, timeout=60)

        # Update latest symlink
        latest_link = os.path.join(args.output_dir, "latest")
        if os.path.islink(latest_link):
            os.unlink(latest_link)
        os.symlink(run_dir, latest_link)

        print(f"[DONE] {run_id} → {run_dir}")

    print(f"\n[COMPLETE] {args.repetitions} repetition(s) of '{scenario['name']}' finished.")
    print(f"[INFO] Results in {args.output_dir}/")


if __name__ == "__main__":
    main()
