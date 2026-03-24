#!/usr/bin/env bash
# dev.sh  –  build / run / shell helpers for the nvda-tracker test container
# ───────────────────────────────────────────────────────────────────────────
# Usage:
#   bash dev.sh build      # build the image
#   bash dev.sh run        # start the container (detached, systemd as PID 1)
#   bash dev.sh shell      # exec a bash shell inside the running container
#   bash dev.sh install    # run install.sh inside the container
#   bash dev.sh logs       # tail journalctl for the service
#   bash dev.sh stop       # stop & remove the container
#   bash dev.sh clean      # stop + remove image
# ───────────────────────────────────────────────────────────────────────────
set -euo pipefail

IMAGE="nvda-tracker-test"
CONTAINER="nvda-tracker-dev"

cmd="${1:-help}"

case "$cmd" in

  build)
    echo "▶ Building image ${IMAGE} …"
    docker build -t "${IMAGE}" .
    echo "✓ Done."
    ;;

  run)
    if docker ps -q --filter "name=^${CONTAINER}$" | grep -q .; then
      echo "Container '${CONTAINER}' is already running."
      exit 0
    fi
    echo "▶ Starting container '${CONTAINER}' (systemd PID 1) …"
    docker run -d \
      --name "${CONTAINER}" \
      --privileged \
      --cgroupns=host \
      -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
      "${IMAGE}"
    echo "✓ Container started.  Use:  bash dev.sh shell"
    ;;

  shell)
    echo "▶ Opening bash shell in '${CONTAINER}' …"
    docker exec -it "${CONTAINER}" bash
    ;;

  install)
    echo "▶ Running install.sh inside '${CONTAINER}' …"
    docker exec -it "${CONTAINER}" bash /install/install.sh
    ;;

  logs)
    echo "▶ Tailing nvda-tracker journal (Ctrl-C to quit) …"
    docker exec -it "${CONTAINER}" \
      journalctl -u nvda-tracker -f --no-pager
    ;;

  status)
    docker exec -it "${CONTAINER}" \
      systemctl status nvda-tracker --no-pager
    ;;

  stop)
    echo "▶ Stopping and removing '${CONTAINER}' …"
    docker stop "${CONTAINER}" 2>/dev/null || true
    docker rm   "${CONTAINER}" 2>/dev/null || true
    echo "✓ Done."
    ;;

  clean)
    bash "$0" stop
    echo "▶ Removing image ${IMAGE} …"
    docker rmi "${IMAGE}" 2>/dev/null || true
    echo "✓ Done."
    ;;

  test)
    # Full smoke-test: build → run → install → check service is active
    bash "$0" clean  2>/dev/null || true
    bash "$0" build
    bash "$0" run
    echo "▶ Running install.sh inside '${CONTAINER}' …"
    docker exec "${CONTAINER}" bash /install/install.sh
    echo "▶ Checking service status …"
    docker exec "${CONTAINER}" systemctl is-active nvda-tracker \
      && echo "✓ nvda-tracker is active." \
      || { echo "✗ nvda-tracker failed to start."; \
           docker exec "${CONTAINER}" journalctl -u nvda-tracker -n 30 --no-pager; \
           exit 1; }
    echo "▶ Verifying state file exists …"
    docker exec "${CONTAINER}" test -f /var/lib/nvda-tracker/nvda_today \
      && echo "✓ State file present." \
      || echo "  (state file not yet written – market may be closed, that is normal)"
    echo "✓ Smoke-test passed."
    ;;

  help|*)
    echo ""
    echo "  bash dev.sh build    – build the Docker image"
    echo "  bash dev.sh run      – start container with systemd as PID 1"
    echo "  bash dev.sh shell    – open an interactive bash shell"
    echo "  bash dev.sh install  – run install.sh inside the container"
    echo "  bash dev.sh logs     – follow journalctl for nvda-tracker"
    echo "  bash dev.sh status   – systemctl status nvda-tracker"
    echo "  bash dev.sh stop     – stop & remove the container"
    echo "  bash dev.sh clean    – stop + remove image"
    echo "  bash dev.sh test     – full smoke-test (build+run+install+verify)"
    echo ""
    ;;
esac