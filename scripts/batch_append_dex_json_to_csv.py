import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import re

CSV_PATH = Path(r"C:\Users\Squel\Documents\Coding\TheCoinWifsperer\data\token_master_template.csv")
DATA_DIR = Path(r"C:\Users\Squel\Documents\Coding\TheCoinWifsperer\data")

# (filename, source)
FILTER_FILES = [
    ("solana_5m_trending.json",      "5m Trending"),
    ("solana_pricechange6hr.json",   "Price Change 6Hr"),
    ("solana_top.json",              "Top"),
    # Add more here!
]

BLOCKCHAIN = "solana"

def utc_now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def clean_address(raw_addr):
    if not raw_addr:
        return ""
    addr = raw_addr.split('?')[0]
    if (
        addr.isalnum() and
        (len(addr) == 44 or addr.endswith("pump")) 
        and not addr.isdigit() and not addr.islower()
    ):
        return addr
    else:
        return "" 

def clean_symbol_and_boost(raw_symbol):
    if not raw_symbol:
        return "", ""
    lines = [x for x in raw_symbol.split('\n') if x and x != "/" and x != "SOL"]
    symbol = ""
    for part in lines:
        if part.isalpha() and part.isupper():
            symbol = part
            break
    if not symbol and len(lines) > 1:
        symbol = lines[1]
    elif not symbol:
        symbol = lines[0]
    boost_amount = ""
    matches = list(re.finditer(r"(\d+)", raw_symbol))
    if matches:
        boost_amount = matches[-1].group(1)
    return symbol, boost_amount

def fmt_usd(val):
    try:
        return f"${float(val):,.2f}" if val is not None and str(val) != "" else ""
    except Exception:
        return ""

def fmt_price(val):
    try:
        v = float(val)
        price_str = f"${v:,.7f}".rstrip("0").rstrip(".")
        if price_str == "$":
            price_str = "$0"
        return price_str
    except Exception:
        return ""

def fmt_percent(val):
    try:
        return f"{round(float(val),2)}%" if val is not None and str(val) != "" else ""
    except Exception:
        return ""

def fmt_age(val):
    try:
        h = float(val)
        if h < 48:
            return f"{int(round(h))}h"
        else:
            days = int(h // 24)
            rem_h = int(h % 24)
            if rem_h == 0:
                return f"{days}d"
            return f"{days}d {rem_h}h"
    except Exception:
        return ""

def process_file(json_path, source, existing, df):
    with open(json_path, "r", encoding="utf-8") as f:
        tokens = json.load(f)

    FIELD_MAP = {
        "timestamp": lambda t: utc_now_iso(),
        "mint_address": lambda t: clean_address(t.get("address")),
        "name": lambda t: t.get("tokenName", ""),
        "symbol": lambda t: clean_symbol_and_boost(t.get("tokenSymbol"))[0],
        "Dex_boost_amount": lambda t: clean_symbol_and_boost(t.get("tokenSymbol"))[1],
        "price": lambda t: fmt_price(t.get("priceUsd")),
        "marketcap_5m": lambda t: fmt_usd(t.get("marketCapUsd")),
        "liquidity": lambda t: fmt_usd(t.get("liquidityUsd")),
        "age": lambda t: fmt_age(t.get("age")),
        "volume_24h": lambda t: fmt_usd(t.get("volumeUsd")),
        "holders": lambda t: t.get("makerCount", ""),
        "buy_count": lambda t: t.get("transactionCount", ""),
        "maker_count": lambda t: t.get("makerCount", ""),
        "price_delta_5m": lambda t: fmt_percent(t.get("priceChange5m")),
        "price_delta_1h": lambda t: fmt_percent(t.get("priceChange1h")),
        "price_delta_6h": lambda t: fmt_percent(t.get("priceChange6h")),
        "price_delta_24h": lambda t: fmt_percent(t.get("priceChange24h")),
        "source": lambda t: source,
        "blockchain": lambda t: BLOCKCHAIN,
    }

    new_rows = []
    added = 0
    for t in tokens:
        mint = clean_address(t.get("address"))
        if not mint or mint in existing:
            continue
        row = {col: "" for col in df.columns}
        for col, func in FIELD_MAP.items():
            if col in row:
                row[col] = func(t)
        new_rows.append(row)
        existing.add(mint)
        added += 1

    return new_rows, added

def main():
    df = pd.read_csv(CSV_PATH)
    existing = set(df["mint_address"].dropna().astype(str)) if "mint_address" in df.columns else set()
    total_added = 0
    for fname, source in FILTER_FILES:
        json_path = DATA_DIR / fname
        if not json_path.exists():
            print(f"❌ File not found: {json_path}")
            continue
        print(f"Processing {json_path} ({source})...")
        new_rows, added = process_file(json_path, source, existing, df)
        if new_rows:
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        print(f"✅ {added} new tokens added from {fname}")
        total_added += added

    df.to_csv(CSV_PATH, index=False)
    print(f"✅ All done. {total_added} new tokens appended in total!")

if __name__ == "__main__":
    main()
