#!/usr/bin/env python3
"""
nvda_tracker.py  –  NVDA intraday price tracker
─────────────────────────────────────────────────
Prints the current NVDA price every minute during NASDAQ trading hours
(09:30–16:00 ET, Mon–Fri).  At EOD it prints the day's open / close /
min / max derived from every sample taken during the session.

Persistence: sampled prices are appended to /tmp/nvda_today (JSON-lines),
keyed by date.  The daemon can be stopped and restarted; it will reload
the day's history and still emit correct EOD stats.
"""

import json
import os
import sys
import time
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo          # Python 3.9+

import yfinance as yf

# ── constants ────────────────────────────────────────────────────────────────
TICKER      = "NVDA"
STATE_FILE  = Path(os.environ.get("NVDA_STATE_FILE", "/tmp/nvda_today"))
MARKET_TZ   = ZoneInfo("America/New_York")
MARKET_OPEN = datetime.time(9, 30)
MARKET_CLOSE= datetime.time(16, 0)
POLL_SECS   = 60          # one minute between samples


# ── helpers ──────────────────────────────────────────────────────────────────

def now_et() -> datetime.datetime:
    """Current wall-clock time in US/Eastern (NYSE timezone)."""
    return datetime.datetime.now(tz=MARKET_TZ)


def is_market_open(dt: datetime.datetime | None = None) -> bool:
    """Return True if dt (default: now) is inside NASDAQ trading hours."""
    dt = dt or now_et()
    if dt.weekday() >= 5:           # Saturday = 5, Sunday = 6
        return False
    return MARKET_OPEN <= dt.time() < MARKET_CLOSE


def seconds_until_open() -> float:
    """How many seconds until the next market open (may be tomorrow/Monday)."""
    now = now_et()
    candidate = now.replace(
        hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute,
        second=0, microsecond=0
    )
    if candidate <= now or now.weekday() >= 5:
        # move to next weekday
        candidate += datetime.timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += datetime.timedelta(days=1)
    return (candidate - now).total_seconds()


def seconds_until_close() -> float:
    """How many seconds until today's market close."""
    now = now_et()
    close = now.replace(
        hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute,
        second=0, microsecond=0
    )
    return max(0.0, (close - now).total_seconds())


# ── price fetching ────────────────────────────────────────────────────────────

def _extract_close(data) -> float | None:
    """
    Safely pull the last Close value from a yfinance DataFrame.
    Handles both flat columns ('Close') and the MultiIndex columns
    (('Close', 'NVDA')) that newer yfinance versions return.
    """
    if data.empty:
        return None
    col = data["Close"]
    # MultiIndex → Series of Series; squeeze one level down
    if hasattr(col, "squeeze"):
        col = col.squeeze()
    return float(col.iloc[-1])


def fetch_current_price(ticker: str = TICKER) -> float | None:
    """
    Return the most recent trade price for *ticker* using yfinance.
    Uses the 1-minute bars for today; returns None on failure.
    """
    try:
        data = yf.download(
            ticker,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
        return _extract_close(data)
    except Exception as exc:
        print(f"[WARN] fetch_current_price failed: {exc}", flush=True)
        return None


def fetch_price_at(ticker: str, dt: datetime.datetime) -> float | None:
    """
    Return the closing price of *ticker* at (or just before) *dt*.
    *dt* must be timezone-aware.  Useful for back-filling or ad-hoc queries.

    Strategy: download the 1-minute bar that contains *dt*, return its Close.
    Falls back to the nearest available bar if the exact minute is missing.
    """
    # Download a small window around dt
    start = dt - datetime.timedelta(minutes=5)
    end   = dt + datetime.timedelta(minutes=2)
    try:
        data = yf.download(
            ticker,
            start=start.astimezone(datetime.timezone.utc),
            end=end.astimezone(datetime.timezone.utc),
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            return None
        # Select the bar whose timestamp is <= dt
        ts_col = data.index.tz_convert(dt.tzinfo)
        mask   = ts_col <= dt
        if not mask.any():
            return None
        return _extract_close(data[mask])
    except Exception as exc:
        print(f"[WARN] fetch_price_at({dt}) failed: {exc}", flush=True)
        return None


# ── state persistence (JSON-lines) ───────────────────────────────────────────

def _today_str() -> str:
    return now_et().strftime("%Y-%m-%d")


def load_today_samples() -> list[dict]:
    """Read all samples for today from STATE_FILE.  Returns [] if none."""
    today = _today_str()
    samples: list[dict] = []
    if not STATE_FILE.exists():
        return samples
    with STATE_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("date") == today:
                    samples.append(rec)
            except json.JSONDecodeError:
                pass
    return samples


def append_sample(price: float) -> None:
    """Persist one price sample (with timestamp) to STATE_FILE."""
    rec = {
        "date":  _today_str(),
        "ts":    now_et().isoformat(),
        "price": price,
    }
    with STATE_FILE.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def prune_state_file() -> None:
    """Keep only today's records in STATE_FILE (avoids unbounded growth)."""
    today = _today_str()
    if not STATE_FILE.exists():
        return
    kept: list[str] = []
    with STATE_FILE.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
                if rec.get("date") == today:
                    kept.append(line if line.endswith("\n") else line + "\n")
            except json.JSONDecodeError:
                pass
    STATE_FILE.write_text("".join(kept))


# ── EOD summary ───────────────────────────────────────────────────────────────

def print_eod_summary(samples: list[dict]) -> None:
    if not samples:
        print("[EOD] No samples recorded today – cannot produce summary.", flush=True)
        return
    prices = [s["price"] for s in samples]
    print("", flush=True)
    print("=" * 52, flush=True)
    print(f"  EOD SUMMARY  –  {TICKER}  –  {_today_str()}", flush=True)
    print("=" * 52, flush=True)
    print(f"  Open   (first sample) : ${prices[0]:>10.4f}", flush=True)
    print(f"  Close  (last sample)  : ${prices[-1]:>10.4f}", flush=True)
    print(f"  Intraday Low          : ${min(prices):>10.4f}", flush=True)
    print(f"  Intraday High         : ${max(prices):>10.4f}", flush=True)
    print(f"  Samples collected     : {len(prices)}", flush=True)
    print("=" * 52, flush=True)
    print("", flush=True)


# ── main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[INFO] NVDA tracker started – PID {os.getpid()}", flush=True)
    print(f"[INFO] State file: {STATE_FILE}", flush=True)

    eod_printed = False
    prev_price: float | None = None

    # Reload any samples already collected today (handles restarts)
    samples = load_today_samples()
    if samples:
        prev_price = samples[-1]["price"]
        print(
            f"[INFO] Resumed: {len(samples)} existing sample(s) for today; "
            f"last price = ${prev_price:.4f}",
            flush=True,
        )

    while True:
        now = now_et()

        # ── market is open ───────────────────────────────────────────────────
        if is_market_open(now):
            eod_printed = False          # reset flag for a fresh session
            price = fetch_current_price()

            if price is not None:
                # Format the delta vs previous sample
                if prev_price is not None:
                    delta     = price - prev_price
                    delta_pct = delta / prev_price * 100
                    sign      = "+" if delta >= 0 else ""
                    diff_str  = f"  Δ {sign}{delta:.4f}  ({sign}{delta_pct:.2f}%)"
                else:
                    diff_str  = "  Δ  n/a (first sample)"

                print(
                    f"[{now.strftime('%Y-%m-%d %H:%M:%S %Z')}]  "
                    f"{TICKER}  ${price:.4f}{diff_str}",
                    flush=True,
                )

                append_sample(price)
                samples = load_today_samples()   # keep local list in sync
                prev_price = price
            else:
                print(
                    f"[{now.strftime('%H:%M:%S')}] [WARN] Could not fetch price.",
                    flush=True,
                )

            # Sleep until next poll, but wake up if market closes sooner
            sleep_for = min(POLL_SECS, seconds_until_close() + 5)
            time.sleep(max(1.0, sleep_for))

        # ── just after market close  →  emit EOD summary once ────────────────
        elif (
            now.weekday() < 5
            and now.time() >= MARKET_CLOSE
            and not eod_printed
        ):
            # Reload from disk in case another process wrote samples
            samples = load_today_samples()
            print_eod_summary(samples)
            prune_state_file()
            eod_printed = True
            # Sleep until midnight-ish before checking again
            time.sleep(3600)

        # ── pre-market / weekend  →  sleep until next open ───────────────────
        else:
            wait = seconds_until_open()
            wake = now_et() + datetime.timedelta(seconds=wait)
            print(
                f"[INFO] Market closed.  Next open ≈ "
                f"{wake.strftime('%Y-%m-%d %H:%M %Z')}  "
                f"(sleeping {wait/3600:.1f} h)",
                flush=True,
            )
            time.sleep(wait)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.  Printing EOD summary if available …",
              flush=True)
        samples = load_today_samples()
        print_eod_summary(samples)
        sys.exit(0)