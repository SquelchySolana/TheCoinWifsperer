# -*- coding: utf-8 -*-
"""Scan token mints for security flags using Solana RPC."""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Type

import pandas as pd
from solders.pubkey import Pubkey
from solana.rpc.api import Client
from solana.rpc.providers import core as provider_core
from solders.rpc.requests import Body, GetAccountInfo
from solders.rpc.responses import GetAccountInfoResp
from spl.token._layouts import MINT_LAYOUT

http_logger = logging.getLogger("rpc_http")
# Minimal helpers from Metaplex python-api
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")


def get_metadata_account(mint_key: str) -> Pubkey:
    return Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(Pubkey.from_string(mint_key))],
        METADATA_PROGRAM_ID,
    )[0]


def unpack_metadata_account(data: bytes) -> Dict[str, Any]:
    if data[0] != 4:
        raise ValueError("Invalid metadata prefix")
    i = 1
    update_auth = Pubkey(data[i : i + 32])
    i += 32
    mint = Pubkey(data[i : i + 32])
    i += 32
    name_len = int.from_bytes(data[i : i + 4], "little")
    i += 4
    i += name_len
    symbol_len = int.from_bytes(data[i : i + 4], "little")
    i += 4
    i += symbol_len
    uri_len = int.from_bytes(data[i : i + 4], "little")
    i += 4
    i += uri_len
    i += 2  # fee
    has_creator = data[i]
    i += 1
    if has_creator:
        creator_len = int.from_bytes(data[i : i + 4], "little")
        i += 4 + creator_len * (32 + 2)
    primary_sale_happened = bool(data[i])
    i += 1
    is_mutable = bool(data[i])
    return {
        "update_authority": str(update_auth),
        "mint": str(mint),
        "primary_sale_happened": primary_sale_happened,
        "is_mutable": is_mutable,
    }


def _rpc_request_with_logging(client: Client, body: Body, parser: Type[Any]) -> Any:
    """Send RPC request, log status, and parse response."""
    kwargs = client._provider._before_request(body)  # type: ignore[attr-defined]
    resp = client._provider.session.post(**kwargs)  # type: ignore[attr-defined]
    http_logger.info(
        'HTTP Request: POST %s "HTTP/1.1 %s %s"',
        client._provider.endpoint_uri,  # type: ignore[attr-defined]
        resp.status_code,
        resp.reason_phrase,
    )
    text = provider_core._after_request_unparsed(resp)
    return provider_core._parse_raw(text, parser)


def _get_account_info_logged(client: Client, pubkey: Pubkey) -> GetAccountInfoResp:
    body = client._get_account_info_body(  # type: ignore[attr-defined]
        pubkey=pubkey,
        commitment=None,
        encoding="base64",
        data_slice=None,
    )
    return _rpc_request_with_logging(client, body, GetAccountInfoResp)


def fetch_metadata(client: Client, mint: str) -> Optional[Dict[str, Any]]:
    account = get_metadata_account(mint)
    resp = _get_account_info_logged(client, account)
    if resp.value is None:
        return None
    data = resp.value.data
    if isinstance(data, tuple):
        data = base64.b64decode(data[0])
    return unpack_metadata_account(data)


def analyze_mint(client: Client, mint: str) -> Dict[str, Any]:
    result = {
        "mint_authority_exist": 0,
        "freeze_authority_exist": 0,
        "metadata_mutable": "unknown",
        "security_status": "NO_DATA",
        "health_summary": "No data",
    }
    try:
        resp = _get_account_info_logged(client, Pubkey.from_string(mint))
    except Exception as exc:
        logging.error("RPC error for %s: %s", mint, exc)
        return result
    if resp.value is None:
        logging.warning("Mint account not found: %s", mint)
        return result

    data = resp.value.data
    if isinstance(data, tuple):
        data = base64.b64decode(data[0])

    info = MINT_LAYOUT.parse(data[: MINT_LAYOUT.sizeof()])
    result["mint_authority_exist"] = 1 if info.mint_authority_option == 1 else 0
    result["freeze_authority_exist"] = 1 if info.freeze_authority_option == 1 else 0

    metadata = fetch_metadata(client, mint)
    if metadata:
        result["metadata_mutable"] = 1 if metadata["is_mutable"] else 0
    else:
        result["metadata_mutable"] = "unknown"

    if (
        result["mint_authority_exist"]
        or result["freeze_authority_exist"]
        or result["metadata_mutable"] == 1
    ):
        result["security_status"] = "DANGER"
        reasons = []
        if result["mint_authority_exist"]:
            reasons.append("mintable")
        if result["freeze_authority_exist"]:
            reasons.append("freezable")
        if result["metadata_mutable"] == 1:
            reasons.append("mutable metadata")
        result["health_summary"] = "Danger - " + ", ".join(reasons)
    else:
        result["security_status"] = "SAFE"
        result["health_summary"] = "Safe"

    return result


def update_csv(path: Path, client: Client) -> None:
    df = pd.read_csv(path)

    required_cols = [
        "mint_authority_exist",
        "freeze_authority_exist",
        "metadata_mutable",
        "security_status",
        "health_summary",
        "first_seen_on",
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = df[col].astype("object")

    tokens: list[tuple[int, str]] = []
    for idx, row in df.iterrows():
        mint = str(row.get("mint_address", "")).strip()
        if not mint:
            continue
        seen_val = row.get("first_seen_on")
        if isinstance(seen_val, str):
            seen = seen_val.strip()
        else:
            seen = "" if pd.isna(seen_val) else str(seen_val)
        if seen:
            continue
        tokens.append((idx, mint))

    total = len(tokens)
    if total == 0:
        print("No new tokens to scan.")
        return

    print(f"{total} unidentified tokens detected.")
    batch_size = 15
    scanned = 0
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        print(f"scanning {end - start}/{total} tokens this round.")
        for idx, mint in tokens[start:end]:
            logging.info("Scanning %s", mint)
            info = analyze_mint(client, mint)
            df.loc[idx, "mint_authority_exist"] = info["mint_authority_exist"]
            df.loc[idx, "freeze_authority_exist"] = info["freeze_authority_exist"]
            df.loc[idx, "metadata_mutable"] = info["metadata_mutable"]
            df.loc[idx, "security_status"] = info["security_status"]
            df.loc[idx, "health_summary"] = info["health_summary"]
            df.loc[idx, "first_seen_on"] = datetime.now(timezone.utc).isoformat()
            scanned += 1
            time.sleep(1 / 15)
        remaining = total - end
        print(f"{end - start} coins security entered in log. {remaining} left.")

    df.to_csv(path, index=False)
    print(f"Scanned {scanned}/{total} tokens.")


def main() -> None:
    log_dir = Path(__file__).resolve().parents[1] / "logs"
    log_dir.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(log_dir / "data_collection.log")
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler])

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    http_logger.addHandler(console_handler)
    http_logger.setLevel(logging.INFO)
    http_logger.propagate = False

    csv_path = Path(__file__).resolve().parents[1] / "data" / "token_master_template.csv"
    client = Client("https://api.mainnet-beta.solana.com")
    update_csv(csv_path, client)


if __name__ == "__main__":
    main()
