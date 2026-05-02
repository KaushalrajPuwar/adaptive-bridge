#!/usr/bin/env python3
"""
apply_tc.py — Apply/clean Gilbert-Elliot bursty loss + delay via tc/netem.

Supports two modes:
  baseline  — tc on publisher container egress, filtered to slow_sub IP
  adaptive  — tc via ifb ingress shaping on slow_sub container

Environment: requires `sudo`, Docker, `ifb` kernel module (adaptive mode).
"""
import argparse
import json
import subprocess
import sys
import time
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


def clean_tc_baseline(pub_cid: str, compose_file: str) -> None:
    """Remove all tc rules from the publisher container."""
    try:
        run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "del", "dev", "eth0", "root"],
            check=False)
    except subprocess.CalledProcessError:
        pass


def clean_tc_adaptive(slow_cid: str) -> None:
    """Remove ifb + ingress rules from the slow_subscriber container."""
    try:
        run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "del", "dev", "eth0", "ingress"],
            check=False)
    except subprocess.CalledProcessError:
        pass
    try:
        run(["sudo", "docker", "exec", slow_cid, "ip", "link", "del", "ifb0"],
            check=False)
    except subprocess.CalledProcessError:
        pass
    try:
        run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "del", "dev", "ifb0", "root"],
            check=False)
    except subprocess.CalledProcessError:
        pass


def apply_tc_baseline(compose_file: str, delay_mean: int, delay_stddev: int,
                      loss_p: int, loss_r: int, loss_good: float, loss_bad: int,
                      bandwidth: int = 0) -> None:
    """Apply tc on publisher egress filtered to slow_subscriber IP."""
    pub_cid = get_container_id(compose_file, "publisher")
    slow_cid = get_container_id(compose_file, "slow_subscriber")
    slow_ip = get_container_ip(slow_cid)

    clean_tc_baseline(pub_cid, compose_file)

    # Priority qdisc root
    run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "add", "dev", "eth0",
         "root", "handle", "1:", "prio"])

    # Filter: packets destined to slow_sub IP -> class 1:1
    run(["sudo", "docker", "exec", pub_cid, "tc", "filter", "add", "dev", "eth0",
         "protocol", "ip", "parent", "1:0", "prio", "1", "u32",
         "match", "ip", "dst", slow_ip, "flowid", "1:1"])

    # netem with GE bursty loss + normal distribution delay
    # If bandwidth > 0, also apply rate limiter via HTB
    loss_good_pct = loss_good

    if bandwidth > 0:
        # Use HTB to create a rate-limited class, then attach netem under it
        run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "add", "dev", "eth0",
             "parent", "1:1", "handle", "10:", "htb", "default", "1"])
        run(["sudo", "docker", "exec", pub_cid, "tc", "class", "add", "dev", "eth0",
             "parent", "10:", "classid", "10:1", "htb",
             "rate", f"{bandwidth}kbit", "ceil", f"{bandwidth}kbit"])
        netem_parent = "10:1"
    else:
        netem_parent = "1:1"

    run(["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "add", "dev", "eth0",
         "parent", netem_parent, "handle", "20:", "netem",
         "delay", f"{delay_mean}ms", f"{delay_stddev}ms", "distribution", "normal",
         "loss", "gemodel", "p", str(loss_p), "r", str(loss_r),
         "1-h", str(loss_good_pct), "1-k", str(loss_bad)])

    # Verify
    show = subprocess.run(
        ["sudo", "docker", "exec", pub_cid, "tc", "qdisc", "show", "dev", "eth0"],
        capture_output=True, text=True,
    )
    print(f"[INFO] tc rules on publisher:\n{show.stdout}")

    # Ping test
    print(f"[INFO] Verifying impairment via ping to slow_sub ({slow_ip})...")
    ping_result = subprocess.run(
        ["sudo", "docker", "exec", pub_cid, "ping", "-c", "3", "-W", "2", slow_ip],
        capture_output=True, text=True,
    )
    print(ping_result.stdout[-300:] if ping_result.stdout else ping_result.stderr[:300])


def apply_tc_adaptive(compose_file: str, delay_mean: int, delay_stddev: int,
                      loss_p: int, loss_r: int, loss_good: float, loss_bad: int,
                      bandwidth: int = 0) -> None:
    """Apply tc via ifb ingress shaping on the slow_subscriber container."""
    slow_cid = get_container_id(compose_file, "slow_subscriber")

    clean_tc_adaptive(slow_cid)

    # Ensure ifb module is loaded on host
    try:
        run(["sudo", "modprobe", "ifb"], check=False)
    except Exception:
        print("[WARN] Could not modprobe ifb — falling back to dual-egress tc")
        return _apply_tc_adaptive_fallback(compose_file, delay_mean, delay_stddev,
                                            loss_p, loss_r, loss_good, loss_bad, bandwidth)

    # Create ifb0 inside container
    run(["sudo", "docker", "exec", slow_cid, "ip", "link", "add", "ifb0", "type", "ifb"])
    run(["sudo", "docker", "exec", slow_cid, "ip", "link", "set", "ifb0", "up"])

    # Mirror ingress traffic to ifb0
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "eth0", "ingress"])
    run(["sudo", "docker", "exec", slow_cid, "tc", "filter", "add", "dev", "eth0",
         "parent", "ffff:", "protocol", "ip", "u32", "match", "ip", "src", "0.0.0.0/0",
         "action", "mirred", "egress", "redirect", "dev", "ifb0"])

    # Apply bandwidth (HTB) + netem on ifb0
    loss_good_pct = loss_good
    if bandwidth > 0:
        run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "ifb0",
             "root", "handle", "1:", "htb", "default", "1"])
        run(["sudo", "docker", "exec", slow_cid, "tc", "class", "add", "dev", "ifb0",
             "parent", "1:", "classid", "1:1", "htb",
             "rate", f"{bandwidth}kbit", "ceil", f"{bandwidth}kbit"])
        netem_parent = "1:1"
    else:
        netem_parent = "root"
    run(["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "add", "dev", "ifb0",
         "parent", netem_parent, "netem",
         "delay", f"{delay_mean}ms", f"{delay_stddev}ms", "distribution", "normal",
         "loss", "gemodel", "p", str(loss_p), "r", str(loss_r),
         "1-h", str(loss_good_pct), "1-k", str(loss_bad)])

    # Verify
    show = subprocess.run(
        ["sudo", "docker", "exec", slow_cid, "tc", "qdisc", "show", "dev", "ifb0"],
        capture_output=True, text=True,
    )
    print(f"[INFO] tc rules on slow_sub ifb0:\n{show.stdout}")


def _apply_tc_adaptive_fallback(compose_file: str, delay_mean: int, delay_stddev: int,
                                 loss_p: int, loss_r: int, loss_good: float, loss_bad: int,
                                 bandwidth: int = 0) -> None:
    """Fallback: apply tc on proxy egress filtered to slow_sub IP."""
    print("[INFO] Using fallback: tc on proxy egress -> slow_sub IP")
    # Convert adaptive compose path to baseline compose path
    baseline_compose = os.path.join(os.path.dirname(compose_file),
                                    os.path.basename(compose_file).replace("adaptive", "baseline"))
    apply_tc_baseline(baseline_compose, delay_mean, delay_stddev,
                      loss_p, loss_r, loss_good, loss_bad, bandwidth)
    # Also apply on classifier egress for probe impairment (no bandwidth there)
    try:
        cls_cid = get_container_id(compose_file, "classifier")
        slow_cid = get_container_id(compose_file, "slow_subscriber")
        slow_ip = get_container_ip(slow_cid)
        run(["sudo", "docker", "exec", cls_cid, "tc", "qdisc", "add", "dev", "eth0",
             "root", "netem", "delay", f"{delay_mean}ms", f"{delay_stddev}ms",
             "distribution", "normal", "loss", "gemodel", "p", str(loss_p),
             "r", str(loss_r), "1-h", str(loss_good), "1-k", str(loss_bad)],
            check=False)
    except Exception as e:
        print(f"[WARN] Could not apply tc on classifier: {e}")


def main():
    parser = argparse.ArgumentParser(description="Apply GE bursty loss via tc/netem")
    parser.add_argument("--compose-file", required=True, help="Path to docker-compose file")
    parser.add_argument("--action", choices=["apply", "clean", "status"], default="apply")
    parser.add_argument("--delay-mean", type=int, default=20)
    parser.add_argument("--delay-stddev", type=int, default=8)
    parser.add_argument("--loss-p", type=int, default=1, help="GE p (%): good->bad transition")
    parser.add_argument("--loss-r", type=int, default=15, help="GE r (%): bad->good transition")
    parser.add_argument("--loss-good-pct", type=float, default=0.5,
                        help="GE 1-h: loss probability in good state, percent (e.g. 0.5 = 0.5%%)")
    parser.add_argument("--loss-bad", type=int, default=30,
                        help="GE 1-k: loss probability in bad state, percent")
    parser.add_argument("--bandwidth", type=int, default=0, help="TBF rate limit in kbit (0=disabled)")
    args = parser.parse_args()

    mode = "baseline" if "baseline" in os.path.basename(args.compose_file) else "adaptive"

    if args.action == "clean":
        if mode == "baseline":
            pub_cid = get_container_id(args.compose_file, "publisher")
            clean_tc_baseline(pub_cid, args.compose_file)
        else:
            slow_cid = get_container_id(args.compose_file, "slow_subscriber")
            clean_tc_adaptive(slow_cid)
        print("[INFO] tc rules cleaned")
        return

    if args.action == "status":
        return

    if mode == "baseline":
        apply_tc_baseline(args.compose_file, args.delay_mean, args.delay_stddev,
                          args.loss_p, args.loss_r, args.loss_good_pct, args.loss_bad,
                          args.bandwidth)
    else:
        apply_tc_adaptive(args.compose_file, args.delay_mean, args.delay_stddev,
                          args.loss_p, args.loss_r, args.loss_good_pct, args.loss_bad,
                          args.bandwidth)


if __name__ == "__main__":
    main()
