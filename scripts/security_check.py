"""Automated Solana token security checking using GoPlus Solana API.

Checks each token in token_master_template.csv and writes results back.

- Flags and logs 'DANGER' tokens (with triggers), 'SAFE', and 'NO_DATA'.
- Logs all raw API responses for debugging.
- Updates last_updated and first_seen_on timestamps.
- Saves after each token so progress is never lost.
"""

import os
import logging
from datetime import datetime, timezone
from time import sleep
import json

import pandas as pd
import requests

# Paths and settings
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CSV_PATH = os.environ.get("TOKEN_CSV_PATH", os.path.join(DATA_DIR, "token_master_template.csv"))
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")
SOLANA_URL = "https://api.gopluslabs.io/api/v1/solana/token_security"
SOLANA_RATE_DELAY = 2.1  # 30 requests/minute

HEADERS = [
    "timestamp","first_seen_on","last_updated","source","mint_address","pair_address","name","symbol","age",
    "holders","total_supply","decimals","price","volume_5m","volume_1h","volume_6h","volume_24h","marketcap_5m",
    "marketcap_1h","marketcap_6h","marketcap_24h","price_delta_1m","price_delta_5m","price_delta_15m",
    "price_delta_1h","volume_delta_1m","volume_delta_5m","volume_delta_15m","volume_delta_1h","liquidity",
    "pooled_sol","pooled_token","buy_count","buy_volume","sell_count","sell_volume","is_honeypot","is_blacklisted",
    "is_proxy","can_take_back_ownership","owner_change_balance","is_mintable","is_open_source","is_spl2022",
    "mint_authority_exist","freeze_authority_exist","max_tx_amount","max_wallet_amount","trading_paused","anti_bot",
    "tax_fee","lp_holders","held_by_top_1","held_by_top_5","held_by_top_10","top_holders_json","is_trending",
    "trending_rank","featured_on_aggregator","featured_rank","bubblemap_report","block_number","slot",
    "sentiment_score","mentions","time_since_first_liquidity","time_since_first_trade","security_status",
    "health_summary","notes"
]

MAJOR_RISKS_SOLANA = {
    "mint_authority_exist",
    "freeze_authority_exist",
    "trading_paused",
    "anti_bot",
}

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

def parse_top_holder_fields(info):
    """Extract LP and top holder info from API response."""
    parsed = {}
    lp = info.get("lp_holders")
    if isinstance(lp, (list, dict)):
        parsed["lp_holders"] = json.dumps(lp)
    elif lp is not None:
        parsed["lp_holders"] = lp
    top = info.get("top_holders")
    if top is None:
        return parsed
    if isinstance(top, str):
        try:
            top_list = json.loads(top)
        except Exception:
            top_list = []
    else:
        top_list = top if isinstance(top, list) else []
    parsed["top_holders_json"] = json.dumps(top_list)
    def pct(n): return str(sum(float(h.get("percent", 0)) for h in top_list[:n]))
    if top_list:
        parsed["held_by_top_1"] = pct(1)
        parsed["held_by_top_5"] = pct(min(5, len(top_list)))
        parsed["held_by_top_10"] = pct(min(10, len(top_list)))
    return parsed

def fetch_solana(address):
    params = {"address": address}
    try:
        resp = requests.get(SOLANA_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("result", {})
        logging.info("GoPlus response for %s: %s", address, data)
        return data
    except Exception as exc:
        logging.error("Solana API error for %s: %s", address, exc)
        return {}

def update_from_solana(df, address, info):
    now = datetime.now(timezone.utc).isoformat()
    row_mask = df["mint_address"].str.lower() == address.lower()
    if not row_mask.any():
        return
    for key, value in info.items():
        if key not in df.columns:
            df[key] = ""
        df.loc[row_mask, key] = value
    holders = parse_top_holder_fields(info)
    for key, value in holders.items():
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
    status = "SAFE"
    triggered = []
    for risk in MAJOR_RISKS_SOLANA:
        if str(info.get(risk, "0")) in {"1", "True", "true"}:
            status = "DANGER"
            triggered.append(risk)
    df.loc[row_mask, "security_status"] = status
    summary = f"Danger—{','.join(triggered)}" if status == "DANGER" and triggered else "Safe"
    df.loc[row_mask, "health_summary"] = summary
    logging.info("Token %s: status=%s, summary=%s", address, status, summary)

def main():
    setup_logging()
    df = ensure_csv()
    to_check = df[df["security_status"].fillna("").str.upper().isin(["", "PENDING", "UNKNOWN", "NO_DATA"])]
    addresses = to_check["mint_address"].dropna().tolist()
    logging.info("Solana security check for %d tokens", len(addresses))
    for addr in addresses:
        info = fetch_solana(addr)
        update_from_solana(df, addr, info)
        save_csv(df)  # Save after every token (safer for interruption)
        sleep(SOLANA_RATE_DELAY)
    safe = (df["security_status"] == "SAFE").sum()
    danger = (df["security_status"] == "DANGER").sum()
    nodata = (df["security_status"] == "NO_DATA").sum()
    logging.info("Summary: %d safe, %d danger, %d no data", safe, danger, nodata)
    logging.info("Tokens checked this run: %d", len(addresses))

if __name__ == "__main__":
    main()
