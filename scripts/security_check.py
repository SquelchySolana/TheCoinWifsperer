"""Automated token security checking using GoPlus APIs.

The GoPlus "general" token security endpoint no longer allows Solana
checks, so this script exclusively uses the Solana-specific endpoint.

Tokens are queried sequentially and the script respects GoPlus's limit
of 30 requests per 60 seconds (an extra second of buffer is included).

Major risk flags used to mark tokens as ``DANGER`` can be extended in the
future to tweak how risky tokens are evaluated. Only the Solana specific
set is currently used:

``mint_authority_exist``, ``freeze_authority_exist``, ``trading_paused``,
``anti_bot``.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from time import sleep
import json

import pandas as pd
import requests

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CSV_PATH = os.getenv(
    "TOKEN_CSV_PATH", os.path.join(DATA_DIR, "token_master_template.csv")
)
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")

# API endpoint
# Only the Solana-specific token security API is supported.
SOLANA_URL = "https://api.gopluslabs.io/api/v1/solana/token_security"

# API limits
# GoPlus allows 30 requests per minute. We use 61 seconds for 30 requests
# to stay safely under the cap.
RATE_LIMIT = 30
RATE_WINDOW = 61  # seconds
SOLANA_RATE_DELAY = RATE_WINDOW / RATE_LIMIT

# Columns from GitHub template
HEADERS = [
    "timestamp",
    "first_seen_on",
    "last_updated",
    "source",
    "mint_address",
    "pair_address",
    "name",
    "symbol",
    "age",
    "holders",
    "total_supply",
    "decimals",
    "price",
    "volume_5m",
    "volume_1h",
    "volume_6h",
    "volume_24h",
    "marketcap_5m",
    "marketcap_1h",
    "marketcap_6h",
    "marketcap_24h",
    "price_delta_1m",
    "price_delta_5m",
    "price_delta_15m",
    "price_delta_1h",
    "volume_delta_1m",
    "volume_delta_5m",
    "volume_delta_15m",
    "volume_delta_1h",
    "liquidity",
    "pooled_sol",
    "pooled_token",
    "buy_count",
    "buy_volume",
    "sell_count",
    "sell_volume",
    "is_honeypot",
    "is_blacklisted",
    "is_proxy",
    "can_take_back_ownership",
    "owner_change_balance",
    "is_mintable",
    "is_open_source",
    "is_spl2022",
    "mint_authority_exist",
    "freeze_authority_exist",
    "max_tx_amount",
    "max_wallet_amount",
    "trading_paused",
    "anti_bot",
    "tax_fee",
    "lp_holders",
    "held_by_top_1",
    "held_by_top_5",
    "held_by_top_10",
    "top_holders_json",
    "is_trending",
    "trending_rank",
    "featured_on_aggregator",
    "featured_rank",
    "bubblemap_report",
    "block_number",
    "slot",
    "sentiment_score",
    "mentions",
    "time_since_first_liquidity",
    "time_since_first_trade",
    "security_status",
    "health_summary",
    "notes",
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
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
    )


def ensure_csv() -> pd.DataFrame:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        pd.DataFrame(columns=HEADERS).to_csv(CSV_PATH, index=False)
    df = pd.read_csv(CSV_PATH, dtype=str)
    if "mint_address" in df.columns:
        df["mint_address"] = df["mint_address"].astype(str).str.strip()
    missing_cols = [c for c in HEADERS if c not in df.columns]
    for col in missing_cols:
        df[col] = ""
    return df


def save_csv(df: pd.DataFrame) -> None:
    df.to_csv(CSV_PATH, index=False)


def parse_top_holder_fields(info: Dict[str, Any]) -> Dict[str, Any]:
    """Extract LP and top holder information from API response."""
    parsed: Dict[str, Any] = {}
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
    def pct(n: int) -> str:
        return str(sum(float(h.get("percent", 0)) for h in top_list[:n]))

    if top_list:
        parsed["held_by_top_1"] = pct(1)
        parsed["held_by_top_5"] = pct(min(5, len(top_list)))
        parsed["held_by_top_10"] = pct(min(10, len(top_list)))
    return parsed




def fetch_solana(address: str) -> Dict[str, Any]:
    params = {"address": address}
    try:
        resp = requests.get(SOLANA_URL, params=params, timeout=10)
        resp.raise_for_status()
        logging.debug("Solana API raw response for %s: %s", address, resp.text)
        data = resp.json().get("result", {})
        if data is None:
            data = {}
        return data
    except Exception as exc:
        logging.error("Solana API error for %s: %s", address, exc)
        return {}


def update_from_solana(df: pd.DataFrame, address: str, info: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row_mask = df["mint_address"].str.lower() == address.lower()
    if not row_mask.any():
        return
    if info:
        for key, value in info.items():
            if key not in df.columns:
                df[key] = ""
            if isinstance(value, (list, dict)):
                df.loc[row_mask, key] = json.dumps(value)
            else:
                df.loc[row_mask, key] = value
        holders = parse_top_holder_fields(info)
        for key, value in holders.items():
            if key not in df.columns:
                df[key] = ""
            df.loc[row_mask, key] = value

        danger = False
        triggered = []
        for risk in MAJOR_RISKS_SOLANA:
            if str(info.get(risk, "0")) in {"1", "True", "true"}:
                danger = True
                triggered.append(risk)
        df.loc[row_mask, "security_status"] = "DANGER" if danger else "SAFE"
        if danger and triggered:
            summary = f"Danger—{','.join(triggered)}"
        else:
            summary = "Safe"
        df.loc[row_mask, "health_summary"] = summary
    else:
        df.loc[row_mask, "security_status"] = "NO_DATA"
        df.loc[row_mask, "health_summary"] = "No data from GoPlus"
    df.loc[row_mask, "last_updated"] = now


def main() -> None:
    setup_logging()
    df = ensure_csv()

    to_check = df[df["security_status"].fillna("").str.upper().isin(["", "PENDING", "UNKNOWN"])]
    addresses = to_check["mint_address"].dropna().tolist()
    checked_count = len(addresses)
    logging.info("Solana security check for %d tokens", checked_count)

    for addr in addresses:
        info = fetch_solana(addr)
        update_from_solana(df, addr, info)
        sleep(SOLANA_RATE_DELAY)

    save_csv(df)
    safe = (df["security_status"] == "SAFE").sum()
    danger = (df["security_status"] == "DANGER").sum()
    logging.info("Summary: %d safe, %d danger", safe, danger)
    logging.info("Tokens checked this run: %d", checked_count)


if __name__ == "__main__":
    main()
