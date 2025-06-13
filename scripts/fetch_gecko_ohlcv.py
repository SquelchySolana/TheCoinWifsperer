import os
import sys
import logging
import time
import argparse
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

# ML output configuration
DATA_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "data")
TEMPLATE = os.path.join(os.path.dirname(__file__), os.pardir, "csv templates", "ohlcv_ml_template.xlsx")
ML_CSV = os.path.join(DATA_DIR, "ohlcv_long.csv")
ML_COLUMNS = [
    "mint_address",
    "pair_address",
    "timeframe",
    "datetime",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

# Rate limit configuration (GeckoTerminal allows 30 req/min)
REQUEST_DELAY = 2.1
REQUEST_BATCH = 30
COOLDOWN = 60
_request_count = 0


def throttle() -> None:
    """Respect GeckoTerminal rate limits."""
    global _request_count
    _request_count += 1
    time.sleep(REQUEST_DELAY)
    if _request_count >= REQUEST_BATCH:
        logging.info("Request batch limit reached, cooling down %ds", COOLDOWN)
        time.sleep(COOLDOWN)
        _request_count = 0


def ensure_output_csv() -> None:
    """Create the ML output CSV if it doesn't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(ML_CSV):
        try:
            cols = list(pd.read_excel(TEMPLATE).columns)
        except Exception:
            cols = ML_COLUMNS
        pd.DataFrame(columns=cols).to_csv(ML_CSV, index=False)


def append_ml_rows(mint: str, pair: str, timeframe: str, candles: list) -> None:
    """Append OHLCV candles to the ML CSV and deduplicate."""
    if not candles:
        return
    df_existing = pd.read_csv(ML_CSV)
    df_new = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df_new["datetime"] = pd.to_datetime(df_new["timestamp"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df_new["mint_address"] = mint
    df_new["pair_address"] = pair
    df_new["timeframe"] = timeframe
    df_new = df_new[ML_COLUMNS]
    combined = pd.concat([df_existing, df_new], ignore_index=True)
    combined.drop_duplicates(subset=["mint_address", "pair_address", "timeframe", "timestamp"], inplace=True)
    combined.to_csv(ML_CSV, index=False)


def fetch_pools(token: str) -> list:
    """Return list of pools for the given token on Solana."""
    url = f"{GECKO_API_BASE}/networks/{CHAIN}/tokens/{token}/pools?page=1"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        throttle()
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
    global _request_count
    url = build_ohlcv_url(pair, timeframe, aggregate, before_ts, limit)
    while True:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                logging.warning("429 rate limit from GeckoTerminal. Cooling down %ds", COOLDOWN)
                time.sleep(COOLDOWN)
                _request_count = 0
                continue
            resp.raise_for_status()
            items = resp.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            throttle()
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
    parser = argparse.ArgumentParser(description="Fetch OHLCV data from GeckoTerminal")
    parser.add_argument("tokens", nargs="+", help="Token mint addresses")
    parser.add_argument("--timeframe", default="minute", choices=AGG_OPTIONS.keys())
    parser.add_argument("--aggregate", type=int, default=1)
    args = parser.parse_args()

    if args.aggregate not in AGG_OPTIONS[args.timeframe]:
        allowed = sorted(AGG_OPTIONS[args.timeframe])
        parser.error(f"Invalid aggregate {args.aggregate} for timeframe {args.timeframe}. Allowed: {allowed}")

    ensure_output_csv()

    tf_short = {"minute": "m", "hour": "h", "day": "d"}[args.timeframe]
    timeframe_label = f"{args.aggregate}{tf_short}"

    for token in args.tokens:
        logging.info("Fetching OHLCV for %s", token)
        pools = fetch_pools(token)
        if not pools:
            logging.info("No pools found for %s", token)
            continue

        pool = select_best_pool(pools)
        attrs = pool.get("attributes", {})
        pair_address = attrs.get("address")
        if not pair_address:
            logging.info("Pool address not found for %s", token)
            continue

        created_str = attrs.get("pool_created_at")
        created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.now(timezone.utc)
        now_dt = datetime.now(timezone.utc)
        sec_per_unit = {"minute": 60, "hour": 3600, "day": 86400}[args.timeframe] * args.aggregate
        total_seconds = (now_dt - created_dt).total_seconds()
        limit = min(1000, ceil(total_seconds / sec_per_unit))
        before_ts = int(now_dt.timestamp())

        candles = fetch_ohlcv(pair_address, args.timeframe, args.aggregate, before_ts, limit)
        if not candles:
            logging.info("No OHLCV data for %s", pair_address)
            continue

        append_ml_rows(token, pair_address, timeframe_label, candles)
        logging.info("Appended %d candles for %s", len(candles), pair_address)

    logging.info("Done fetching OHLCV")


if __name__ == "__main__":
    main()
