import os
import sys
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Use command-line argument if provided, else default to test address
if len(sys.argv) > 1:
    TOKEN_ADDRESS = sys.argv[1]
else:
    TOKEN_ADDRESS = "F4dqMnX665khxfGJ26PaAKrFoUCmqCmMPoos2ai7pump"  # Default for testing

API_VERSION = "v1"
NETWORK = "solana"

# Get API base URL from environment variable
DEX_API_BASE = os.getenv("DEX_API_BASE", "https://api.dexscreener.com")

# Set up logging
LOG_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)


def fetch_token_price(address: str) -> dict:
    """Fetch latest price data for a token from Dexscreener."""
    url = f"{DEX_API_BASE}/tokens/{API_VERSION}/{NETWORK}/{address}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            logging.warning("Unexpected API response format: %s", data)
            return {}
        pair = data[0] if data else {}
        if not pair:
            logging.warning("No pair data returned for %s", address)
            return {}

        # Extract relevant fields
        result = {
            "price_usd": pair.get("priceUsd"),
            "price_native": pair.get("priceNative"),
            "liquidity_usd": pair.get("liquidity", {}).get("usd"),
            "volume_24h": pair.get("volume", {}).get("h24"),
            "fdv": pair.get("fdv"),
            "market_cap": pair.get("marketCap"),
        }
        return result
    except Exception as exc:
        logging.error("Error fetching token price: %s", exc)
        return {}


def main() -> None:
    logging.info("Fetching token data for %s", TOKEN_ADDRESS)
    data = fetch_token_price(TOKEN_ADDRESS)
    if data:
        print("Latest Token Data:")
        for key, value in data.items():
            print(f"{key}: {value}")
        logging.info("Fetched data: %s", data)
    else:
        print("No data available. Check logs for details.")


if __name__ == "__main__":
    main()

