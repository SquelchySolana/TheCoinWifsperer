import os
import sys
import logging
from datetime import datetime, timezone
from math import ceil
from typing import List

import requests
import pandas as pd

# Optional plotting
try:
    import mplfinance as mpf
except Exception:  # mplfinance may not be installed
    mpf = None

# Configure logging
LOG_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

GECKO_API_BASE = "https://api.geckoterminal.com/api/v2"
CHAIN = "solana"

# Allowed aggregate values per timeframe
AGG_OPTIONS = {
    "minute": {1, 5, 15},
    "hour": {1, 4, 12},
    "day": {1},
}


def validate_inputs(args: List[str]) -> tuple[str, str, int]:
    """Validate CLI args and return (token_address, timeframe, aggregate)."""
    if not args:
        logging.error("Token address is required")
        raise SystemExit("Usage: fetch_gecko_ohlcv.py <TOKEN_ADDRESS> [timeframe] [aggregate]")

    token_address = args[0]
    timeframe = args[1] if len(args) > 1 else "minute"
    if timeframe not in AGG_OPTIONS:
        raise ValueError(f"Invalid timeframe '{timeframe}'. Use 'minute', 'hour', or 'day'.")

    aggregate = int(args[2]) if len(args) > 2 else 1
    if aggregate not in AGG_OPTIONS[timeframe]:
        allowed = sorted(AGG_OPTIONS[timeframe])
        raise ValueError(f"Invalid aggregate {aggregate} for timeframe {timeframe}. Allowed: {allowed}")

    return token_address, timeframe, aggregate


def fetch_pools(token: str) -> list:
    """Return list of pools for the given token on Solana."""
    url = f"{GECKO_API_BASE}/networks/{CHAIN}/tokens/{token}/pools?page=1"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return data
    except Exception as exc:
        logging.error("Error fetching pools: %s", exc)
        return []


def select_best_pool(pools: list) -> dict:
    """Select the pool with highest reserve USD or most recent."""
    if not pools:
        return {}
    # Sort by reserve_in_usd then by pool_created_at (newest first)
    def sort_key(pool):
        attrs = pool.get("attributes", {})
        reserve = float(attrs.get("reserve_in_usd") or 0)
        created = attrs.get("pool_created_at") or "1970-01-01T00:00:00Z"
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (reserve, ts)

    pools_sorted = sorted(pools, key=sort_key, reverse=True)
    return pools_sorted[0]


def build_ohlcv_url(pair: str, timeframe: str, aggregate: int, before_ts: int, limit: int) -> str:
    """Construct OHLCV request URL.

    Parameters
    ----------
    pair : str
        Pool (pair) address.
    timeframe : str
        Candle width: 'minute', 'hour', or 'day'.
    aggregate : int
        Number of timeframe units per candle.
    before_ts : int
        UNIX timestamp of the latest candle to return.
    limit : int
        Number of candles to return (max 1000).

    Returns
    -------
    str
        Fully formatted URL for GeckoTerminal OHLCV request.
    """
    return (
        f"{GECKO_API_BASE}/networks/{CHAIN}/pools/{pair}/ohlcv/{timeframe}"
        f"?aggregate={aggregate}&before_timestamp={before_ts}&limit={limit}"
        "&currency=usd&include_empty_intervals=true&token=base"
    )


def fetch_ohlcv(pair: str, timeframe: str, aggregate: int, before_ts: int, limit: int) -> list:
    """Fetch OHLCV data from GeckoTerminal."""
    url = build_ohlcv_url(pair, timeframe, aggregate, before_ts, limit)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        return items
    except Exception as exc:
        logging.error("Error fetching OHLCV: %s", exc)
        return []


def save_csv(data: list, pair: str) -> str:
    """Save OHLCV list to CSV and return path."""
    if not data:
        return ""
    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df = df[["datetime", "timestamp", "open", "high", "low", "close", "volume"]]
    data_dir = os.path.join(os.path.dirname(__file__), os.pardir, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, f"{pair}_ohlcv.csv")
    df.to_csv(path, index=False)
    return path


def plot_candles(csv_path: str) -> None:
    """Plot candlestick chart using mplfinance if available."""
    if mpf is None or not csv_path:
        return
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df.set_index("datetime", inplace=True)
    df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
    mpf.plot(df, type="candle", volume=True, title=os.path.basename(csv_path))


def main() -> None:
    token, timeframe, aggregate = validate_inputs(sys.argv[1:])

    pools = fetch_pools(token)
    if not pools:
        print("No pools found for token.")
        return

    pool = select_best_pool(pools)
    attrs = pool.get("attributes", {})
    pair_address = attrs.get("address")
    if not pair_address:
        print("Pool address not found in data.")
        return

    created_str = attrs.get("pool_created_at")
    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.now(timezone.utc)
    now_dt = datetime.now(timezone.utc)
    age = now_dt - created_dt

    sec_per_unit = {"minute": 60, "hour": 3600, "day": 86400}[timeframe] * aggregate
    total_seconds = (now_dt - created_dt).total_seconds()
    limit = min(1000, ceil(total_seconds / sec_per_unit))
    before_ts = int(now_dt.timestamp())

    candles = fetch_ohlcv(pair_address, timeframe, aggregate, before_ts, limit)
    if not candles:
        print("No OHLCV data returned.")
        return

    csv_path = save_csv(candles, pair_address)
    if csv_path:
        logging.info("Saved OHLCV to %s", csv_path)

    print(f"Pool address: {pair_address}")
    print(f"Pool created at: {created_dt.isoformat()}")
    print(f"Pool age: {age}")
    df_sample = pd.DataFrame(candles[:5], columns=["timestamp", "open", "high", "low", "close", "volume"])
    df_sample["datetime"] = pd.to_datetime(df_sample["timestamp"], unit="s", utc=True)
    print("Sample OHLCV data:")
    print(df_sample)

    plot_candles(csv_path)


if __name__ == "__main__":
    main()
