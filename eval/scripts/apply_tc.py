#!/usr/bin/env python3
"""
apply_tc.py — Apply/clean Gilbert-Elliot bursty loss via tc/netem.

Supports two modes:
  baseline  — tc on publisher container egress, filtered to slow_sub IP
  adaptive  — tc via ifb ingress shaping on slow_sub container

No delay, no priority bands — flat htb root, one class, GE loss only.
Clean traffic (critical sub) never starved by qdisc scheduling.

Environment: requires `sudo`, Docker, `ifb` kernel module (adaptive mode).
"""
import argparse
import os
import subprocess
import sys
from typing import Optional


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command, print it, return result."""
    print(f"[CMD] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] exit code {result.returncode}")
        if result.stderr:
            print(f"[STDERR] {result.stderr.strip()[-500:]}")
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def get_container_id(compose_file: str, service: str) -> str:
    """Resolve container ID from compose service name."""
    result = subprocess.run(
        ["sudo", "docker", "compose", "-f", compose_file, "ps", "-q", service],
        capture_output=True, text=True, check=True,
    )
    cid = result.stdout.strip()
    if not cid:
        raise RuntimeError(f"Container not found for service '{service}'")
    return cid


def get_container_ip(cid: str) -> str:
    """Extract IPv4 address from a container ID."""
    result = subprocess.run(
        ["sudo", "docker", "inspect", "-f",
         "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}", cid],
        capture_output=True, text=True, check=True,
    )
    ip = result.stdout.strip()
    if not ip:
        raise RuntimeError(f"No IP found for container {cid}")
    return ip


def clean_tc_baseline(pub_cid: str) -> None:
    """Remove all tc rules from the publisher container (ignore errors)."""
    subprocess.run(
        ["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "del", "dev", "eth0", "root"],
        capture_output=True, check=False)


def clean_tc_adaptive(slow_cid: str) -> None:
    """Remove ifb + ingress rules from the slow_subscriber container (ignore errors)."""
    # Order matters: delete qdiscs before deleting interfaces
    subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "del", "dev", "ifb0", "root"],
        capture_output=True, check=False)
    subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "ip", "link", "del", "ifb0"],
        capture_output=True, check=False)
    subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "del", "dev", "eth0", "ingress"],
        capture_output=True, check=False)


def clean_tc_return_path(slow_cid: str) -> None:
    """Remove return-path tc rules from slow_subscriber egress (ignore errors)."""
    subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "del", "dev", "eth0", "root"],
        capture_output=True, check=False)


# ── Baseline: flat htb root, filter → netem (GE loss only) ──────────

def apply_tc_baseline(compose_file: str, loss_p: int, loss_r: int,
                      loss_good: float, loss_bad: int,
                      bandwidth: int = 0) -> None:
    """Apply GE loss on publisher egress, filtered to slow_sub IP.

    Two HTB classes: class 1:1 (impaired, netem GE loss) and class 1:2
    (clean, default).  Only slow-sub traffic enters the netem via filter.
    Observer and critical subscriber use the clean default class.
    No priority bands, no delay, no buffer overflow amplification.
    """
    pub_cid = get_container_id(compose_file, "publisher")
    slow_cid = get_container_id(compose_file, "slow_subscriber")
    slow_ip = get_container_ip(slow_cid)

    clean_tc_baseline(pub_cid)

    # HTB root — two classes sharing total bandwidth
    rate_str = f"{bandwidth}kbit" if bandwidth > 0 else "100000kbit"
    run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "add", "dev", "eth0",
         "root", "handle", "1:", "htb", "default", "2"])
    # Class 1:1 — impaired traffic (slow_sub, filtered, netem GE loss)
    run(["sudo", "docker", "exec", pub_cid, "tc", "class", "add", "dev", "eth0",
         "parent", "1:", "classid", "1:1", "htb",
         "rate", rate_str, "ceil", rate_str])
    # Class 1:2 — clean traffic (default, no netem, no loss)
    run(["sudo", "docker", "exec", pub_cid, "tc", "class", "add", "dev", "eth0",
         "parent", "1:", "classid", "1:2", "htb",
         "rate", rate_str, "ceil", rate_str])

    # Filter: slow-sub packets → class 1:1 (impaired)
    run(["sudo", "docker", "exec", pub_cid, "tc", "filter", "add", "dev", "eth0",
         "protocol", "ip", "parent", "1:", "pref", "1", "u32",
         "match", "ip", "dst", slow_ip, "flowid", "1:1"])

    # Netem — GE loss only on impaired class, no delay, no limit
    run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "add", "dev", "eth0",
         "parent", "1:1", "handle", "10:", "netem",
         "loss", "gemodel", str(loss_p), str(loss_r),
         str(loss_good), str(loss_bad)])

    # Verify
    show = subprocess.run(
        ["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "show", "dev", "eth0"],
        capture_output=True, text=True,
    )
    print(f"[INFO] tc rules on publisher:\n{show.stdout}")

    # Return-path impairment: ACK delay + low loss on slow_sub egress → publisher
    try:
        _apply_tc_return_path(slow_cid, get_container_ip(pub_cid))
    except Exception as e:
        print(f"[WARN] Return-path tc failed: {e}")


# ── Adaptive: ifb ingress with flat htb root ─────────────────────────

def apply_tc_adaptive(compose_file: str, loss_p: int, loss_r: int,
                      loss_good: float, loss_bad: int,
                      bandwidth: int = 0) -> None:
    """Apply GE loss via ifb ingress shaping on slow_subscriber.

    All incoming traffic to slow_sub is mirrored to ifb0, where a flat
    htb root with one class applies netem GE loss.  No delay, no limit.
    """
    slow_cid = get_container_id(compose_file, "slow_subscriber")

    clean_tc_adaptive(slow_cid)

    # Ensure ifb module is loaded on host
    mod_result = subprocess.run(["sudo", "modprobe", "ifb"], capture_output=True, text=True)
    if mod_result.returncode != 0:
        print("[WARN] Could not modprobe ifb — falling back to dual-egress tc")
        return _apply_tc_adaptive_fallback(compose_file, loss_p, loss_r,
                                            loss_good, loss_bad, bandwidth)

    # Create ifb0 inside container
    run(["sudo", "docker", "exec", slow_cid, "ip", "link", "add", "ifb0", "type", "ifb"])
    run(["sudo", "docker", "exec", slow_cid, "ip", "link", "set", "ifb0", "up"])

    # Mirror ingress traffic to ifb0
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "eth0", "ingress"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "filter", "add", "dev", "eth0",
         "parent", "ffff:", "protocol", "ip", "u32", "match", "ip", "src", "0.0.0.0/0",
         "action", "mirred", "egress", "redirect", "dev", "ifb0"])

    # Flat htb root on ifb0 — GE loss on all ingress (all traffic
    # entering slow_sub is the impaired path; clean subscribers are
    # separate containers, not on this ifb0 interface)
    rate_str = f"{bandwidth}kbit" if bandwidth > 0 else "100000kbit"
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "ifb0",
         "root", "handle", "1:", "htb", "default", "2"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "class", "add", "dev", "ifb0",
         "parent", "1:", "classid", "1:2", "htb",
         "rate", rate_str, "ceil", rate_str])
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "ifb0",
         "parent", "1:2", "handle", "10:", "netem",
         "loss", "gemodel", str(loss_p), str(loss_r),
         str(loss_good), str(loss_bad)])

    # Verify
    show = subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "show", "dev", "ifb0"],
        capture_output=True, text=True,
    )
    print(f"[INFO] tc rules on slow_sub ifb0:\n{show.stdout}")

    # Return-path impairment: ACK delay + low loss on slow_sub egress → proxy
    try:
        _apply_tc_return_path(slow_cid, get_container_ip(get_container_id(compose_file, "proxy")))
    except Exception as e:
        print(f"[WARN] Return-path tc failed: {e}")


# ── Return-path ACK impairment ───────────────────────────────────────

def _apply_tc_return_path(slow_cid: str, target_ip: str) -> None:
    """Apply low-loss, variable-delay impairment on slow_sub egress → target.

    Models realistic Wi-Fi ACK behaviour: small control packets experience
    contention-driven timing variability (~20ms) but very low loss (~0.3%).
    """
    clean_tc_return_path(slow_cid)
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "eth0",
         "root", "handle", "1:", "htb", "default", "2"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "class", "add", "dev", "eth0",
         "parent", "1:", "classid", "1:1", "htb",
         "rate", "50mbit", "ceil", "50mbit"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "class", "add", "dev", "eth0",
         "parent", "1:", "classid", "1:2", "htb",
         "rate", "50mbit", "ceil", "50mbit"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "filter", "add", "dev", "eth0",
         "protocol", "ip", "parent", "1:", "pref", "1", "u32",
         "match", "ip", "dst", target_ip, "flowid", "1:1"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "eth0",
         "parent", "1:1", "handle", "10:", "netem",
         "delay", "20ms", "10ms", "distribution", "normal",
         "loss", "0.3%", "25%"])
    print(f"[INFO] Return-path tc applied: slow_sub egress → {target_ip} (20ms delay, 0.3% loss)")


# ── Fallback (no ifb available) ──────────────────────────────────────

def _apply_tc_adaptive_fallback(compose_file: str, loss_p: int, loss_r: int,
                                loss_good: float, loss_bad: int,
                                bandwidth: int = 0) -> None:
    """Fallback: apply tc on proxy egress filtered to slow_sub IP."""
    print("[INFO] Using fallback: tc on proxy egress -> slow_sub IP")
    baseline_compose = os.path.join(os.path.dirname(compose_file),
                                    os.path.basename(compose_file).replace("adaptive", "baseline"))
    # Handle ablation compose: replace "adaptive.ablation" → "baseline" as well
    if not os.path.exists(baseline_compose):
        baseline_compose = os.path.join(os.path.dirname(compose_file),
                                        "docker-compose.baseline.yml")
    if not os.path.exists(baseline_compose):
        print(f"[ERROR] Fallback baseline compose not found: {baseline_compose}")
        return
    apply_tc_baseline(baseline_compose, loss_p, loss_r, loss_good, loss_bad, bandwidth)
    # Also apply on classifier egress for probe impairment
    try:
        cls_cid = get_container_id(compose_file, "classifier")
        run(["sudo", "docker", "exec", cls_cid, "tc", "qdisc", "add", "dev", "eth0",
             "root", "netem",
             "loss", "gemodel", str(loss_p), str(loss_r),
             str(loss_good), str(loss_bad)],
            check=False)
    except Exception as e:
        print(f"[WARN] Could not apply tc on classifier: {e}")


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Apply GE bursty loss via tc/netem")
    parser.add_argument("--compose-file", required=True, help="Path to docker-compose file")
    parser.add_argument("--action", choices=["apply", "clean", "status"], default="apply")
    parser.add_argument("--loss-p", type=int, default=1, help="GE p (%): good->bad transition")
    parser.add_argument("--loss-r", type=int, default=15, help="GE r (%): bad->good transition")
    parser.add_argument("--loss-good-pct", type=float, default=0.5,
                        help="GE good-state loss percent (e.g. 0.5 = 0.5%%)")
    parser.add_argument("--loss-bad", type=int, default=30,
                        help="GE bad-state loss percent (e.g. 30 = 30%%)")
    parser.add_argument("--bandwidth", type=int, default=0, help="Rate limit in kbit (0=disabled)")
    args = parser.parse_args()

    mode = "baseline" if "baseline" in os.path.basename(args.compose_file) else "adaptive"

    if args.action == "clean":
        # Each cleanup attempts to find the container and remove tc rules.
        # If the container is already gone (crashed/stopped), skip gracefully.
        try:
            if mode == "baseline":
                pub_cid = get_container_id(args.compose_file, "publisher")
                clean_tc_baseline(pub_cid)
            else:
                slow_cid = get_container_id(args.compose_file, "slow_subscriber")
                clean_tc_adaptive(slow_cid)
        except Exception:
            pass
        # Clean return path too
        try:
            slow_cid = get_container_id(args.compose_file, "slow_subscriber")
            clean_tc_return_path(slow_cid)
        except Exception:
            pass
        print("[INFO] tc rules cleaned")
        return

    if args.action == "status":
        return

    if mode == "baseline":
        apply_tc_baseline(args.compose_file, args.loss_p, args.loss_r,
                          args.loss_good_pct, args.loss_bad, args.bandwidth)
    else:
        apply_tc_adaptive(args.compose_file, args.loss_p, args.loss_r,
                          args.loss_good_pct, args.loss_bad, args.bandwidth)


if __name__ == "__main__":
    main()
