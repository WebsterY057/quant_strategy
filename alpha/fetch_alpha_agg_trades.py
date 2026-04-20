#!/usr/bin/env python3
"""
Fetch Binance Alpha aggregated trades (tick-level) for symbols in a markdown list.

Example:
python3 fetch_alpha_agg_trades.py \
  --symbols-md /Users/yy/.hermes/workspace/db/analysis/quant_project/alpha/binance_bsc_alpha_tokens_top20.md \
  --start-date 2026-04-10 \
  --end-date 2026-04-17 \
  --out-dir /Users/yy/.hermes/workspace/db/analysis/quant_project/alpha/ticks_2026-04-10_2026-04-17
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade/agg-trades"
UA = {"User-Agent": "Mozilla/5.0"}
CTX = ssl._create_unverified_context()


def parse_date_to_ms(date_str: str, end_of_day: bool = False) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(dt.timestamp() * 1000)


def extract_symbols_from_md(md_path: Path) -> list[str]:
    text = md_path.read_text(encoding="utf-8")
    # Prefer direct symbols like ALPHA_124USDT if present.
    found = re.findall(r"`(ALPHA_\d+USDT)`", text)
    if not found:
        # Fallback: parse alphaId (ALPHA_124) and map to ALPHA_124USDT.
        alpha_ids = re.findall(r"`(ALPHA_\d+)`", text)
        found = [f"{aid}USDT" for aid in alpha_ids]
    # Keep order and de-duplicate.
    dedup = list(dict.fromkeys(found))
    if not dedup:
        raise ValueError(f"No ALPHA_*USDT symbols found in {md_path}")
    return dedup


def http_get_json(url: str, retries: int = 5, sleep_sec: float = 0.2) -> dict[str, Any]:
    for i in range(retries):
        try:
            req = Request(url, headers=UA)
            with urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(sleep_sec * (i + 1))
    raise RuntimeError("Unreachable")


def fetch_symbol(symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    from_id: int | None = None

    for _ in range(50000):
        params = {"symbol": symbol, "limit": 1000}
        if from_id is None:
            params["startTime"] = start_ms
            params["endTime"] = end_ms
        else:
            params["fromId"] = from_id

        url = f"{BASE_URL}?{urlencode(params)}"
        payload = http_get_json(url)
        if payload.get("code") != "000000":
            raise RuntimeError(f"{symbol} API error: {payload}")

        batch = payload.get("data") or []
        if not batch:
            break

        batch_min_t = int(batch[0]["T"])
        batch_max_t = int(batch[-1]["T"])
        if from_id is not None and batch_min_t > end_ms:
            break

        for t in batch:
            ts = int(t["T"])
            if ts < start_ms or ts > end_ms:
                continue
            p = float(t["p"])
            q = float(t["q"])
            rows.append(
                {
                    "exchange": "binance_alpha",
                    "symbol": symbol,
                    "trade_time_utc": datetime.fromtimestamp(
                        ts / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    "trade_ts_ms": ts,
                    "agg_trade_id": int(t["a"]),
                    "price": p,
                    "qty": q,
                    "quote_qty": p * q,
                    "is_buyer_maker": bool(t["m"]),
                    "first_trade_id": int(t["f"]),
                    "last_trade_id": int(t["l"]),
                }
            )

        nxt = int(batch[-1]["a"]) + 1
        if from_id is not None and nxt <= from_id:
            break
        from_id = nxt
        if len(batch) < 1000:
            break
        if from_id is not None and batch_max_t >= end_ms:
            break
        time.sleep(0.03)

    rows.sort(key=lambda r: (r["trade_ts_ms"], r["agg_trade_id"]))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "exchange",
                "symbol",
                "trade_time_utc",
                "trade_ts_ms",
                "agg_trade_id",
                "price",
                "qty",
                "quote_qty",
                "is_buyer_maker",
                "first_trade_id",
                "last_trade_id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Binance Alpha aggTrades by symbol list")
    parser.add_argument("--symbols-md", required=True, help="Markdown file containing ALPHA_*USDT symbols")
    parser.add_argument("--start-date", required=True, help="UTC date, format YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="UTC date, format YYYY-MM-DD")
    parser.add_argument("--out-dir", required=True, help="Output directory for CSV files")
    args = parser.parse_args()

    symbols_md = Path(args.symbols_md)
    out_dir = Path(args.out_dir)
    start_ms = parse_date_to_ms(args.start_date, end_of_day=False)
    end_ms = parse_date_to_ms(args.end_date, end_of_day=True)

    symbols = extract_symbols_from_md(symbols_md)
    print(f"symbols={len(symbols)} start={args.start_date} end={args.end_date}")

    manifest_rows: list[dict[str, Any]] = []
    for i, symbol in enumerate(symbols, 1):
        rows = fetch_symbol(symbol, start_ms, end_ms)
        out_csv = out_dir / f"{symbol}_aggTrades_{args.start_date}_to_{args.end_date}.csv"
        write_csv(out_csv, rows)
        manifest_rows.append(
            {
                "symbol": symbol,
                "rows": len(rows),
                "output_file": str(out_csv),
                "start_utc": rows[0]["trade_time_utc"] if rows else "",
                "end_utc": rows[-1]["trade_time_utc"] if rows else "",
            }
        )
        print(f"[{i}/{len(symbols)}] {symbol}: rows={len(rows)}")

    manifest_path = out_dir / f"manifest_{args.start_date}_to_{args.end_date}.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["symbol", "rows", "output_file", "start_utc", "end_utc"]
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"manifest={manifest_path}")


if __name__ == "__main__":
    main()
