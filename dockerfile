# Dockerfile  –  nvda_tracker systemd integration test
# ───────────────────────────────────────────────────────
# Runs a full systemd-inside-Docker environment so install.sh
# can be tested exactly as it would run on a real Linux host.
#
# Build & run via dev.sh:
#   bash dev.sh build
#   bash dev.sh run
#   bash dev.sh install
#   bash dev.sh logs

FROM debian:bookworm-slim

# ── system packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        systemd \
        systemd-sysv \
        dbus \
        python3 \
        python3-venv \
        python3-pip \
        curl \
        less \
        procps \
    && rm -rf /var/lib/apt/lists/*

# ── mask units that don't work inside Docker ──────────────────────────────────
# Use direct symlinks – systemctl cannot be called at image build time because
# there is no running systemd during 'docker build'.
RUN for unit in \
        dev-hugepages.mount \
        sys-fs-fuse-connections.mount \
        systemd-journald-audit.socket \
        systemd-udev-trigger.service \
        systemd-udevd.service \
        getty.target \
        console-getty.service \
        serial-getty@.service \
    ; do \
        ln -sf /dev/null "/etc/systemd/system/${unit}"; \
    done \
    && ln -sf /lib/systemd/system/multi-user.target \
              /etc/systemd/system/default.target

# ── copy project files ────────────────────────────────────────────────────────
WORKDIR /install
COPY nvda_tracker.py  ./
COPY install.sh       ./
RUN chmod +x install.sh

# ── entrypoint: hand off to systemd (PID 1) ──────────────────────────────────
ENTRYPOINT ["/sbin/init"]
