#!/bin/bash
# cleanup.sh — Destroy all experiment containers, networks, and optionally results.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WS2_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ALL_RESULTS=false

if [ "$1" = "--all-results" ]; then
    ALL_RESULTS=true
fi

echo "[INFO] Stopping all experiment containers..."
sudo docker compose -f "$WS2_DIR/docker/docker-compose.baseline.yml" down -v --remove-orphans 2>/dev/null || true
sudo docker compose -f "$WS2_DIR/docker/docker-compose.adaptive.yml" down -v --remove-orphans 2>/dev/null || true

echo "[INFO] Pruning orphan containers..."
sudo docker container prune -f 2>/dev/null || true

if [ "$ALL_RESULTS" = true ]; then
    echo "[INFO] Removing all results..."
    rm -rf "$WS2_DIR/results"/*
    echo "[INFO] Results cleaned."
fi

echo "[INFO] Cleanup complete."
