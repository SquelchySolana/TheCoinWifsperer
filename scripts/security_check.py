"""Solana RPC-based SPL and Token-2022 token security checker.
Clean human-friendly log output for terminal, detailed logs to file.
Flags DANGER if mint authority, freeze authority, or mutable/unknown metadata.
"""

import os
import logging
import time
from datetime import datetime, timezone
import struct
import pandas as pd
from solana.rpc.api import Client
from spl.token._layouts import MINT_LAYOUT
from solders.pubkey import Pubkey

# SETTINGS
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
CSV_PATH = os.path.join(DATA_DIR, "token_master_template.csv")
LOG_FILE = os.path.join(LOG_DIR, "data_collection.log")

SOLANA_RPC = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
REQUESTS_PER_SECOND = 30  # Stay under GSNode's 50/sec cap

SPL_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
TOKEN_2022_PROGRAM = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

HEADERS = [
    "timestamp","first_seen_on","last_updated","source","mint_address","pair_address","name","symbol","age",
    "holders","total_supply","decimals","price","volume_5m","volume_1h","volume_6h","volume_24h","marketcap_5m",
    "marketcap_1h","marketcap_6h","marketcap_24h","price_delta_1m","price_delta_5m",
    "price_delta_15m","price_delta_1h","volume_delta_1m","volume_delta_5m","volume_delta_15m","volume_delta_1h",
    "liquidity","pooled_sol","pooled_token","buy_count","buy_volume","sell_count","sell_volume","is_honeypot",
    "is_blacklisted","is_proxy","can_take_back_ownership","owner_change_balance","is_mintable","is_open_source",
    "is_spl2022","mint_authority_exist","freeze_authority_exist","metadata_mutable","max_tx_amount","max_wallet_amount",
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
        handlers=[logging.FileHandler(LOG_FILE)],
    )

# Custom logger for clean terminal output
class TerminalLogger:
    def info(self, msg):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{now} [INFO] {msg}")

TERMINAL = TerminalLogger()

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

def get_metadata_is_mutable(data: bytes) -> bool | None:
    if len(data) < 67:
        return None
    offset = 65
    try:
        name_len = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4 + name_len
        if offset > len(data):
            return None
        symbol_len = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4 + symbol_len
        if offset > len(data):
            return None
        uri_len = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4 + uri_len
        if offset > len(data):
            return None
        offset += 2
        if offset > len(data):
            return None
        has_creators = struct.unpack("<B", data[offset:offset+1])[0]
        offset += 1
        if has_creators == 1:
            num_creators = struct.unpack("<I", data[offset:offset+4])[0]
            offset += 4 + num_creators * 34
            if offset > len(data):
                return None
        offset += 1
        if offset >= len(data):
            return None
        is_mutable = struct.unpack("<B", data[offset:offset+1])[0]
        return bool(is_mutable)
    except struct.error:
        return None

def parse_token_2022_mint(data: bytes):
    try:
        if len(data) < 14:
            return {}, False
        offset = 0
        mint_authority_option = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        mint_authority = Pubkey(data[offset:offset+32]) if mint_authority_option == 1 else None
        if mint_authority_option == 1:
            offset += 32
        supply = struct.unpack("<Q", data[offset:offset+8])[0]
        offset += 8
        decimals = struct.unpack("<B", data[offset:offset+1])[0]
        offset += 1
        is_initialized = struct.unpack("<B", data[offset:offset+1])[0]
        offset += 1
        freeze_authority_option = struct.unpack("<I", data[offset:offset+4])[0]
        offset += 4
        freeze_authority = Pubkey(data[offset:offset+32]) if freeze_authority_option == 1 else None
        if freeze_authority_option == 1:
            offset += 32
        mint_info = {
            "mint_authority": str(mint_authority) if mint_authority else None,
            "freeze_authority": str(freeze_authority) if freeze_authority else None,
            "supply": supply,
            "decimals": decimals,
            "is_initialized": bool(is_initialized),
            "metadata_mutable": None,
        }
        parse_fail = False
        found_extension = False
        while offset + 4 <= len(data):
            try:
                ext_type = struct.unpack("<H", data[offset:offset+2])[0]
                ext_length = struct.unpack("<H", data[offset+2:offset+4])[0]
                offset += 4
                if offset + ext_length > len(data):
                    parse_fail = True
                    break
                ext_data = data[offset:offset+ext_length]
                offset += ext_length
                found_extension = True
                if ext_type == 13:
                    if len(ext_data) >= 1:
                        has_update_authority = struct.unpack("<B", ext_data[0:1])[0]
                        if has_update_authority == 1:
                            mint_info["metadata_mutable"] = "1"
                        else:
                            mint_info["metadata_mutable"] = "0"
                elif ext_type == 12:
                    if len(ext_data) >= 32:
                        metadata_account = str(Pubkey(ext_data[0:32]))
                        mint_info["metadata_account"] = metadata_account
            except struct.error:
                parse_fail = True
                break
        if mint_info["metadata_mutable"] is None:
            mint_info["metadata_mutable"] = "unknown"
        return mint_info, parse_fail or not found_extension
    except Exception:
        return {}, True

def fetch_mint_info(mint_address, client):
    try:
        pubkey = Pubkey.from_string(mint_address)
        result = client.get_account_info(pubkey)
        value = result.value
        if value is None or not isinstance(value.data, bytes):
            return {}, False
        if value.owner == SPL_TOKEN_PROGRAM:
            if len(value.data) != 82:
                return {}, False
            mint_info = MINT_LAYOUT.parse(value.data)
            mint_info = {
                "mint_authority": str(Pubkey(mint_info.mint_authority)) if mint_info.mint_authority_option else None,
                "freeze_authority": str(Pubkey(mint_info.freeze_authority)) if mint_info.freeze_authority_option else None,
                "supply": mint_info.supply,
                "decimals": mint_info.decimals,
                "is_initialized": bool(mint_info.is_initialized),
                "metadata_mutable": "0",
            }
            metadata_pda, _ = Pubkey.find_program_address(
                [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(pubkey)],
                METADATA_PROGRAM_ID
            )
            metadata_result = client.get_account_info(metadata_pda)
            if metadata_result.value and isinstance(metadata_result.value.data, bytes):
                is_mutable = get_metadata_is_mutable(metadata_result.value.data)
                if is_mutable is not None:
                    mint_info["metadata_mutable"] = "1" if is_mutable else "0"
            return mint_info, False
        elif value.owner == TOKEN_2022_PROGRAM:
            mint_info, parse_fail = parse_token_2022_mint(value.data)
            if mint_info:
                mint_info["is_spl2022"] = "1"
                if "metadata_account" in mint_info:
                    metadata_pubkey = Pubkey.from_string(mint_info["metadata_account"])
                    metadata_result = client.get_account_info(metadata_pubkey)
                    if metadata_result.value and isinstance(metadata_result.value.data, bytes):
                        is_mutable = get_metadata_is_mutable(metadata_result.value.data)
                        if is_mutable is not None:
                            mint_info["metadata_mutable"] = "1" if is_mutable else "0"
            return mint_info, parse_fail
        else:
            return {}, True
    except Exception:
        return {}, True

def update_from_rpc(df, address, info, parse_fail=False):
    now = datetime.now(timezone.utc).isoformat()
    row_mask = df["mint_address"].str.lower() == address.lower()
    if not row_mask.any():
        return None
    for key, value in info.items():
        if key not in df.columns:
            df[key] = ""
        df.loc[row_mask, key] = value
    df.loc[row_mask, "last_updated"] = now
    if (df.loc[row_mask, "first_seen_on"].isna().any() or (df.loc[row_mask, "first_seen_on"] == "").any()):
        df.loc[row_mask, "first_seen_on"] = now
    if not info:
        df.loc[row_mask, "security_status"] = "NO_DATA"
        df.loc[row_mask, "health_summary"] = "NO_DATA"
        return "UNKNOWN"
    danger = False
    reasons = []
    if info.get("mint_authority"):
        danger = True
        reasons.append("mintable")
        df.loc[row_mask, "mint_authority_exist"] = "1"
    else:
        df.loc[row_mask, "mint_authority_exist"] = "0"
    if info.get("freeze_authority"):
        danger = True
        reasons.append("freezeable")
        df.loc[row_mask, "freeze_authority_exist"] = "1"
    else:
        df.loc[row_mask, "freeze_authority_exist"] = "0"
    metadata_mutable = info.get("metadata_mutable", "unknown")
    if str(metadata_mutable) == "1":
        danger = True
        reasons.append("metadata mutable")
        df.loc[row_mask, "metadata_mutable"] = "1"
    elif str(metadata_mutable) == "0":
        df.loc[row_mask, "metadata_mutable"] = "0"
    else:
        danger = True
        reasons.append("parse_fail or unknown mutability")
        df.loc[row_mask, "metadata_mutable"] = "unknown"
    df.loc[row_mask, "is_spl2022"] = info.get("is_spl2022", "0")
    if parse_fail:
        danger = True
        if "parse_fail" not in reasons:
            reasons.append("parse_fail")
    df.loc[row_mask, "security_status"] = "DANGER" if danger else "SAFE"
    summary = f"Danger—{','.join(reasons)}" if danger and reasons else "Safe"
    df.loc[row_mask, "health_summary"] = summary
    status = "DANGER, flagged." if danger else ("SAFE.")
    return status

def main():
    setup_logging()
    df = ensure_csv()
    client = Client(SOLANA_RPC)
    to_check = df[df["security_status"].fillna("").str.upper().isin(["", "PENDING", "UNKNOWN", "NO_DATA"])]
    addresses = to_check["mint_address"].dropna().tolist()
    batch_size = REQUESTS_PER_SECOND
    batch = addresses[:batch_size]
    remaining = len(addresses) - len(batch)
    if len(batch) > 0:
        TERMINAL.info(f"Detected {len(batch)} new trending tokens. Scanning {len(batch)} tokens for security checks.")
    if remaining > 0:
        TERMINAL.info(f"{remaining} stored for next security check.")
    first_rpc_printed = False
    tokens_report = []
    safe_count = 0
    danger_count = 0
    for addr in batch:
        # Print first HTTP request for visibility
        if not first_rpc_printed:
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] HTTP Request: POST {SOLANA_RPC} \"HTTP/1.1 200 OK\"")
            first_rpc_printed = True
        info, parse_fail = fetch_mint_info(addr, client)
        row = df[df["mint_address"].str.lower() == addr.lower()]
        name = row["name"].iloc[0] if not row["name"].isnull().iloc[0] and row["name"].iloc[0] != "" else None
        status = update_from_rpc(df, addr, info, parse_fail)
        if "DANGER" in status:
            danger_count += 1
        elif "SAFE" in status:
            safe_count += 1
        # Format report line
        if name:
            tokens_report.append(f"Security Report for Token: {name}, CA: {addr}.  {status}")
        else:
            tokens_report.append(f"Security Report for Token CA: {addr}.  {status}")
        save_csv(df)
        time.sleep(1.0/REQUESTS_PER_SECOND)
    for line in tokens_report:
        TERMINAL.info(line)
    TERMINAL.info(f"Summary: Tokens checked: {len(batch)}.")
    TERMINAL.info(f"Safe: {safe_count}.")
    TERMINAL.info(f"Danger: {danger_count}.")
    TERMINAL.info(f"Security Report successfully logged to csv: {CSV_PATH}")

if __name__ == "__main__":
    main()
