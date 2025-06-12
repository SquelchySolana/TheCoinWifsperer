import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd
from dotenv import load_dotenv

# Optional plotting
try:
    import mplfinance as mpf
except Exception:  # matplotlib fallback or missing
    mpf = None

# Load environment variables from .env file if present
load_dotenv()

# Moralis Solana base URL and API key
MORALIS_SOLANA_API_BASE = os.getenv(
    "MORALIS_SOLANA_API_BASE", "https://solana-gateway.moralis.io"
)
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")

# Date logic: today and yesterday
today = datetime.utcnow().date()
yesterday = today - timedelta(days=1)
default_from = yesterday.strftime('%Y-%m-%d')
default_to = today.strftime('%Y-%m-%d')

# Parse command line arguments
PAIR_ADDRESS = sys.argv[1] if len(sys.argv) > 1 else "83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6d"  # Example from Moralis docs
INTERVAL = sys.argv[2] if len(sys.argv) > 2 else "1m"
NETWORK = sys.argv[3] if len(sys.argv) > 3 else "mainnet"
FROM_DATE = sys.argv[4] if len(sys.argv) > 4 else default_from
TO_DATE = sys.argv[5] if len(sys.argv) > 5 else default_to

# Set up logging
LOG_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
)

def fetch_ohlcv(address: str, interval: str, network: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Fetch OHLCV candle data for a given pair from Moralis."""
    url = (
        f"{MORALIS_SOLANA_API_BASE}/token/{network}/pairs/{address}/ohlcv"
        f"?timeframe={interval}&currency=usd&fromDate={from_date}&toDate={to_date}"
    )
    headers = {"X-API-Key": MORALIS_API_KEY} if MORALIS_API_KEY else {}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Print API response for debugging
        logging.info("API response: %s", data)
        if not isinstance(data, list):
            logging.warning("Unexpected API response format: %s", data)
            print(f"Unexpected API response: {data}")
            return pd.DataFrame()
        df = pd.DataFrame(data)
        return df
    except Exception as exc:
        logging.error("Error fetching OHLCV data: %s", exc)
        print(f"Error fetching OHLCV data: {exc}")
        return pd.DataFrame()

def save_to_csv(df: pd.DataFrame, token: str) -> Optional[str]:
    """Save OHLCV DataFrame to the /data directory as CSV."""
    if df.empty:
        return None
    data_dir = os.path.join(os.path.dirname(__file__), os.pardir, "data")
    os.makedirs(data_dir, exist_ok=True)
    file_path = os.path.join(data_dir, f"{token}_ohlcv.csv")
    df.to_csv(file_path, index=False)
    return file_path

def plot_candles(df: pd.DataFrame, interval: str) -> None:
    """Plot candlestick chart using mplfinance if available."""
    if df.empty or mpf is None:
        if mpf is None:
            logging.warning("mplfinance not installed; skipping plot.")
        return
    df_plot = df.copy()
    ts_col = 't' if 't' in df_plot.columns else 'timestamp'
    df_plot[ts_col] = pd.to_datetime(df_plot[ts_col], unit='ms', errors='coerce')
    df_plot.set_index(ts_col, inplace=True)
    rename_map = {
        'o': 'Open',
        'h': 'High',
        'l': 'Low',
        'c': 'Close',
        'v': 'Volume',
    }
    df_plot.rename(columns=rename_map, inplace=True)
    mpf.plot(df_plot, type='candle', volume=True, title=f"{PAIR_ADDRESS} {interval} OHLCV")

def main() -> None:
    """Main execution to fetch data and optionally plot."""
    logging.info(
        "Fetching OHLCV for %s on %s (interval %s, from %s to %s)",
        PAIR_ADDRESS, NETWORK, INTERVAL, FROM_DATE, TO_DATE
    )
    df = fetch_ohlcv(PAIR_ADDRESS, INTERVAL, NETWORK, FROM_DATE, TO_DATE)
    if df.empty:
        print("No OHLCV data returned. Check logs for details.")
        return

    path = save_to_csv(df, PAIR_ADDRESS)
    if path:
        logging.info("Saved OHLCV data to %s", path)
    else:
        logging.warning("DataFrame empty; nothing saved")

    # Uncomment to display candlestick plot
    # plot_candles(df, INTERVAL)

if __name__ == "__main__":
    main()
