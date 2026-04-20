#!/usr/bin/env python3
import argparse
import csv
import json
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://api.binance.com"


def http_get_json(path: str, params: dict | None = None) -> dict | list:
    query = f"?{urlencode(params)}" if params else ""
    req = Request(
        f"{API_BASE}{path}{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(req, timeout=10, context=ssl._create_unverified_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_utc_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def run_capture(symbol: str, seconds: int, output_path: str, poll_interval: float) -> int:
    latest = http_get_json("/api/v3/aggTrades", {"symbol": symbol, "limit": 1})
    if not latest:
        raise RuntimeError(f"No recent aggTrades for symbol={symbol}")

    next_trade_id = int(latest[0]["a"]) + 1
    end_at = time.time() + seconds
    rows_written = 0

    with open(output_path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "exchange",
                "symbol",
                "trade_time_utc",
                "trade_ts_ms",
                "trade_id",
                "price",
                "qty",
                "quote_qty",
                "is_buyer_maker",
                "bid1",
                "ask1",
                "mid",
                "spread",
            ],
        )
        writer.writeheader()

        while time.time() < end_at:
            book = http_get_json("/api/v3/ticker/bookTicker", {"symbol": symbol})
            bid1 = float(book["bidPrice"])
            ask1 = float(book["askPrice"])
            mid = (bid1 + ask1) / 2
            spread = (ask1 - bid1) / mid if mid > 0 else 0.0

            trades = http_get_json(
                "/api/v3/aggTrades",
                {"symbol": symbol, "fromId": next_trade_id, "limit": 1000},
            )

            if trades:
                for t in trades:
                    trade_id = int(t["a"])
                    price = float(t["p"])
                    qty = float(t["q"])
                    ts_ms = int(t["T"])

                    writer.writerow(
                        {
                            "exchange": "binance",
                            "symbol": symbol,
                            "trade_time_utc": to_utc_str(ts_ms),
                            "trade_ts_ms": ts_ms,
                            "trade_id": trade_id,
                            "price": price,
                            "qty": qty,
                            "quote_qty": price * qty,
                            "is_buyer_maker": t["m"],
                            "bid1": bid1,
                            "ask1": ask1,
                            "mid": mid,
                            "spread": spread,
                        }
                    )
                    rows_written += 1

                next_trade_id = int(trades[-1]["a"]) + 1

            time.sleep(poll_interval)

    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Binance aggTrades + bookTicker and save CSV."
    )
    parser.add_argument("--symbol", default="GUNUSDT")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument(
        "--output",
        default="/Users/yy/.hermes/workspace/db/analysis/quant_project/GUNUSDT_binance_realtime_1m.csv",
    )
    args = parser.parse_args()

    rows = run_capture(
        symbol=args.symbol.upper(),
        seconds=args.seconds,
        output_path=args.output,
        poll_interval=args.poll_interval,
    )
    print(f"output={args.output}")
    print(f"rows={rows}")


if __name__ == "__main__":
    main()
