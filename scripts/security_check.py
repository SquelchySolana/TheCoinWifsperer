"""Automated Solana token security checking using RugCheck API.

Checks each token in token_master_template.csv and writes results back.

- Flags and logs 'DANGER' tokens (with triggers), 'SAFE', or 'NO_DATA'.
- Logs all raw API responses for debugging.
- Updates last_updated and first_seen_on timestamps.
- Saves after each token so progress is never lost.
"""

import os
import logging
from datetime import datetime, timezone
from time import sleep

import pandas as pd
import requests

# Paths and settings
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CSV_PATH = os.environ.get("TOKEN_CSV_PATH", os.path.join(DATA_DIR, "token_master_template.csv"))
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")

HEADERS = [
    "timestamp","first_seen_on","last_updated","source","mint_address","pair_address","name","symbol","age",
    "holders","total_supply","decimals","price","volume_5m","volume_1h","volume_6h","volume_24h","marketcap_5m",
    "marketcap_1h","marketcap_6h","marketcap_24h","price_delta_1m","price_delta_5m",
    "price_delta_15m","price_delta_1h","volume_delta_1m","volume_delta_5m","volume_delta_15m","volume_delta_1h",
    "liquidity","pooled_sol","pooled_token","buy_count","buy_volume","sell_count","sell_volume","is_honeypot",
    "is_blacklisted","is_proxy","can_take_back_ownership","owner_change_balance","is_mintable","is_open_source",
    "is_spl2022","mint_authority_exist","freeze_authority_exist","max_tx_amount","max_wallet_amount",
    "trading_paused","anti_bot","tax_fee","lp_holders","held_by_top_1","held_by_top_5","held_by_top_10",
    "top_holders_json","is_trending","trending_rank","featured_on_aggregator","featured_rank","bubblemap_report",
    "block_number","slot","sentiment_score","mentions","time_since_first_liquidity","time_since_first_trade",
    "security_status","health_summary","notes"
]

def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )

def ensure_csv() -> pd.DataFrame:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        pd.DataFrame(columns=HEADERS).to_csv(CSV_PATH, index=False)
    df = pd.read_csv(CSV_PATH, dtype=str)
    missing_cols = [c for c in HEADERS if c not in df.columns]
    for col in missing_cols:
        df[col] = ""
    return df

def save_csv(df: pd.DataFrame) -> None:
    df.to_csv(CSV_PATH, index=False)

def fetch_rugcheck(address):
    url = f"https://api.rugcheck.xyz/tokens/{address}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        info = data.get('data', {})
        logging.info("RugCheck response for %s: %s", address, info)
        return info
    except Exception as exc:
        logging.error("RugCheck API error for %s: %s", address, exc)
        return {}

def update_from_rugcheck(df, address, info):
    now = datetime.now(timezone.utc).isoformat()
    row_mask = df["mint_address"].str.lower() == address.lower()
    if not row_mask.any():
        return
    for key, value in info.items():
        if key not in df.columns:
            df[key] = ""
        df.loc[row_mask, key] = value
    # Always update last_updated
    df.loc[row_mask, "last_updated"] = now
    # Set first_seen_on if never set
    if (df.loc[row_mask, "first_seen_on"].isna().any() or (df.loc[row_mask, "first_seen_on"] == "").any()):
        df.loc[row_mask, "first_seen_on"] = now
    if not info:
        df.loc[row_mask, "security_status"] = "NO_DATA"
        df.loc[row_mask, "health_summary"] = "NO_DATA"
        logging.warning("No security data returned for %s", address)
        return
    # Basic danger logic (customize as you like)
    status = "SAFE"
    reasons = []
    # RugCheck risk fields:
    if info.get("honeypot") in [True, "true", "True", 1, "1"]:
        status = "DANGER"
        reasons.append("honeypot")
    if info.get("can_mint") in [True, "true", "True", 1, "1"]:
        status = "DANGER"
        reasons.append("mintable")
    if info.get("can_freeze") in [True, "true", "True", 1, "1"]:
        status = "DANGER"
        reasons.append("freezeable")
    # You can add more flags here if you want (e.g., high tax, paused trading, etc.)
    df.loc[row_mask, "security_status"] = status
    summary = f"Danger—{','.join(reasons)}" if status == "DANGER" and reasons else "Safe"
    df.loc[row_mask, "health_summary"] = summary
    logging.info("Token %s: status=%s, summary=%s", address, status, summary)

def main():
    setup_logging()
    df = ensure_csv()
    to_check = df[df["security_status"].fillna("").str.upper().isin(["", "PENDING", "UNKNOWN", "NO_DATA"])]
    addresses = to_check["mint_address"].dropna().tolist()
    logging.info("RugCheck security check for %d tokens", len(addresses))
    for addr in addresses:
        info = fetch_rugcheck(addr)
        if info is None:
            info = {}
        update_from_rugcheck(df, addr, info)
        save_csv(df)  # Save after every token (safer for interruption)
        sleep(1)  # No strict limit but let's be nice
    safe = (df["security_status"] == "SAFE").sum()
    danger = (df["security_status"] == "DANGER").sum()
    nodata = (df["security_status"] == "NO_DATA").sum()
    logging.info("Summary: %d safe, %d danger, %d no data", safe, danger, nodata)
    logging.info("Tokens checked this run: %d", len(addresses))

if __name__ == "__main__":
    main()
