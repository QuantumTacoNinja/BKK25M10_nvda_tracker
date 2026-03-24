# nvda-tracker

A Linux daemon that prints the current NVDA stock price every minute during
NASDAQ trading hours (09:30–16:00 ET, Mon–Fri), with intraday delta and an
end-of-day summary.

---

## Requirements

| Requirement | Minimum |
|---|---|
| OS | Any Linux distribution running **systemd** |
| Python | **3.9+** (uses `zoneinfo`, available since 3.9) |
| Network | Outbound HTTPS to Yahoo Finance |

---

## Install from source

```bash
git clone https://github.com/QuantumTacoNinja/BKK25M10_nvda_tracker
cd nvda-tracker
sudo bash install.sh
```

`install.sh` performs three steps:

1. Copies `nvda_tracker.py` to `/opt/nvda-tracker/`.
2. Creates a Python virtual environment at `/opt/nvda-tracker/.venv` and
   installs `yfinance`.
3. Writes `/etc/systemd/system/nvda-tracker.service`, then enables and starts
   the service.

No manual user creation is needed — the unit file uses `DynamicUser=yes` (see
[Service design](#service-design) below).

### Verify

```bash
systemctl status nvda-tracker
journalctl -u nvda-tracker -f
```

### Useful commands

```bash
journalctl -u nvda-tracker --since today   # full day log
systemctl stop    nvda-tracker             # stop
systemctl start   nvda-tracker             # start
systemctl disable nvda-tracker             # remove from autostart
```

---

## Test with Docker

The `dockerfile` and `dev.sh` spin up a container running systemd as PID 1 —
the same environment the service sees on a real host.

> **macOS note:** Docker Desktop on macOS does not expose the host cgroup
> hierarchy. Start Docker Desktop and use the commands below as-is; the
> `--privileged --cgroupns=host` flags handle the rest.

### One-command smoke test

```bash
bash dev.sh test
```

This builds the image, starts the container, runs `install.sh`, confirms
`systemctl is-active nvda-tracker`, and checks for the state file.

### Step-by-step

```bash
bash dev.sh build    # build the image
bash dev.sh run      # start container (systemd as PID 1, detached)
bash dev.sh install  # run install.sh inside the container
bash dev.sh logs     # tail journalctl for nvda-tracker
bash dev.sh status   # systemctl status nvda-tracker
bash dev.sh shell    # interactive bash inside the container
bash dev.sh stop     # stop & remove the container
bash dev.sh clean    # stop + remove image
```

---

## Service design

### Systemd unit conventions

The unit file (`nvda-tracker.service`) follows modern systemd conventions
rather than creating a dedicated OS user manually:

```ini
DynamicUser=yes
StateDirectory=nvda-tracker
```

`DynamicUser=yes` instructs systemd to allocate a **transient, unprivileged
user** for the lifetime of the service. The user is created on start and
removed on stop — no `useradd`/`groupadd` step in the installer.

`StateDirectory=nvda-tracker` instructs systemd to create
`/var/lib/nvda-tracker/` before the service starts and to own it as the
dynamic user. The directory persists across restarts and survives reboots.

The unit also sets:

```ini
ProtectSystem=strict     # filesystem is read-only except for explicit paths
ProtectHome=true         # /home, /root are invisible
PrivateTmp=true          # isolated /tmp namespace
NoNewPrivileges=true     # cannot gain new capabilities
```

### State file: `/var/lib/nvda-tracker/nvda_today`

Every price sample is appended to this file as a **JSON-lines** record:

```json
{"date": "2025-03-24", "ts": "2025-03-24T09:31:00-04:00", "price": 876.5}
{"date": "2025-03-24", "ts": "2025-03-24T09:32:00-04:00", "price": 877.1}
```

The path is passed to the Python process via the environment variable
`NVDA_STATE_FILE` (set in the unit file). The script falls back to
`/tmp/nvda_today` when the variable is absent, which is convenient for running
the script directly during development:

```bash
python3 nvda_tracker.py          # uses /tmp/nvda_today
NVDA_STATE_FILE=/tmp/test python3 nvda_tracker.py
```

### Survival across restarts

On startup, `nvda_tracker.py` calls `load_today_samples()`, which reads every
record from the state file whose `date` field matches today. If samples exist,
the tracker resumes from the last known price and includes all prior samples in
the end-of-day calculation.

This means the service can be stopped and started any number of times during a
trading day — the EOD summary will still reflect the full session.

At the end of the trading day the state file is pruned to keep only today's
records, preventing unbounded growth.

### End-of-day summary

After market close (16:00 ET) the main loop detects the transition and prints:

```
====================================================
  EOD SUMMARY  –  NVDA  –  2025-03-24
====================================================
  Open   (first sample) :   $876.5000
  Close  (last sample)  :   $912.3000
  Intraday Low          :   $871.2000
  Intraday High         :   $918.7500
  Samples collected     : 391
====================================================
```

The same summary is also printed if the process receives `SIGTERM` (e.g.
`systemctl stop nvda-tracker`), because Python converts SIGTERM into
`KeyboardInterrupt` and the `except` block calls `print_eod_summary` before
exiting. `TimeoutStopSec=30` in the unit file gives the process enough time to
finish printing before systemd forcefully kills it.

---

## File layout

```
.
├── nvda_tracker.py        # the daemon
├── nvda-tracker.service   # reference unit file (install.sh generates the live one)
├── install.sh             # installer for real Linux hosts
├── dockerfile             # systemd-in-Docker image for testing
├── dev.sh                 # helper commands for the Docker workflow
└── requirements.txt       # full pinned dependency list (informational)
```
