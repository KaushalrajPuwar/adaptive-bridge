#!/usr/bin/env python3
"""
collect_system_info.py — Generate system_info.yaml for an experiment run.
"""
import argparse
import os
import platform
import subprocess
import sys


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Collect system info")
    parser.add_argument("--output", default="system_info.yaml", help="Output YAML path")
    parser.add_argument("--ros-distro", default=os.environ.get("ROS_DISTRO", "unknown"))
    parser.add_argument("--rmw", default="rmw_fastrtps_cpp", help="RMW implementation used")
    args = parser.parse_args()

    cpu_model = "unknown"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    cpu_cores = int(run(["nproc"]) or "0")
    ram_kb = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line:
                    ram_kb = int(line.split()[1])
                    break
    except Exception:
        pass
    ram_gb = round(ram_kb / 1024 / 1024, 1)

    os_name = "unknown"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    os_name = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass

    docker_ver = run(["docker", "version", "--format", "{{.Server.Version}}"])
    if not docker_ver:
        docker_ver = run(["sudo", "docker", "version", "--format", "{{.Server.Version}}"])

    py_ver = run(["python3", "--version"]).replace("Python ", "")

    dds_vendor = "FastDDS" if "fastrtps" in args.rmw.lower() else "CycloneDDS"

    content = f"""cpu_model: "{cpu_model}"
cpu_cores: {cpu_cores}
ram_gb: {ram_gb}
os: "{os_name}"
docker_version: "{docker_ver}"
ros_distro: "{args.ros_distro}"
python_version: "{py_ver}"
rmw_implementation: "{args.rmw}"
dds_vendor: "{dds_vendor}"
kernel: "{platform.release()}"
host_machine: "{platform.node()}"
"""
    with open(args.output, "w") as f:
        f.write(content)
    print(f"[INFO] system_info.yaml written to {args.output}")


if __name__ == "__main__":
    main()
