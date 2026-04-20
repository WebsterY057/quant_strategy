#!/usr/bin/env python3
"""
Backtest buy/sell signals based on:
1) VR (Volume Ratio)
2) Price-volume divergence
3) VWAP trend
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def load_minute_bars(csv_path: Path) -> pd.DataFrame:
    ticks = pd.read_csv(csv_path)
    ticks = ticks.sort_values("trade_ts_ms").copy()
    ticks["ts"] = pd.to_datetime(ticks["trade_ts_ms"], unit="ms", utc=True)
    ticks["minute"] = ticks["ts"].dt.floor("min")

    bars = (
        ticks.groupby("minute", as_index=False)
        .agg(
            close=("price", "last"),
            volume=("qty", "sum"),
            quote_volume=("quote_qty", "sum"),
            trades=("trade_id", "count"),
        )
        .sort_values("minute")
        .reset_index(drop=True)
    )
    return bars


def add_signals(
    bars: pd.DataFrame, vr_window: int = 60, div_window: int = 60, vwap_sustain: int = 3
) -> pd.DataFrame:
    df = bars.copy()

    # VR: rolling up/down volume ratio * 100
    ret = df["close"].diff()
    up_vol = np.where(ret > 0, df["volume"], 0.0)
    down_vol = np.where(ret < 0, df["volume"], 0.0)
    up_roll = pd.Series(up_vol).rolling(vr_window, min_periods=vr_window).sum()
    down_roll = pd.Series(down_vol).rolling(vr_window, min_periods=vr_window).sum()
    df["vr"] = np.where(down_roll > 0, (up_roll / down_roll) * 100.0, np.nan)

    # Divergence based on previous 60-min extrema
    prev_price_max = df["close"].shift(1).rolling(div_window, min_periods=div_window).max()
    prev_price_min = df["close"].shift(1).rolling(div_window, min_periods=div_window).min()
    prev_vol_max = df["volume"].shift(1).rolling(div_window, min_periods=div_window).max()
    prev_vol_min = df["volume"].shift(1).rolling(div_window, min_periods=div_window).min()

    df["top_divergence"] = (df["close"] > prev_price_max) & (df["volume"] < prev_vol_max)
    df["bottom_divergence"] = (df["close"] < prev_price_min) & (df["volume"] > prev_vol_min)

    # VWAP: cumulative VWAP over the backtest period
    cum_qv = df["close"].mul(df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    df["vwap"] = cum_qv / cum_v

    above = (df["close"] > df["vwap"]).astype(int)
    below = (df["close"] < df["vwap"]).astype(int)
    df["vwap_buy"] = above.rolling(vwap_sustain, min_periods=vwap_sustain).sum() == vwap_sustain
    df["vwap_sell"] = below.rolling(vwap_sustain, min_periods=vwap_sustain).sum() == vwap_sustain

    # Buy/sell conditions from the user's rules
    df["buy_vr"] = df["vr"] < 70
    df["sell_vr"] = df["vr"] > 150
    df["buy_signal"] = df["buy_vr"] | df["bottom_divergence"] | df["vwap_buy"]
    df["sell_signal"] = df["sell_vr"] | df["top_divergence"] | df["vwap_sell"]
    return df


def run_backtest(
    df: pd.DataFrame,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    stop_loss_pct: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = df.copy().reset_index(drop=True)
    fee = fee_bps / 10000.0
    slip = slippage_bps / 10000.0

    position = 0
    entry_price = np.nan
    entry_time = None
    positions = []
    trades = []
    equity = np.zeros(len(data))
    capital = 1.0
    units = 0.0
    prev_equity = 1.0
    net_ret = np.zeros(len(data))

    for i in range(len(data)):
        buy = bool(data.at[i, "buy_signal"])
        sell = bool(data.at[i, "sell_signal"])
        px = float(data.at[i, "close"])
        ts = data.at[i, "minute"]

        stop_trigger = False
        if position == 1 and stop_loss_pct is not None and entry_price > 0:
            stop_trigger = (px / entry_price - 1.0) <= -abs(stop_loss_pct) / 100.0

        # Exit priority: stop-loss first, then signal-based sell.
        if position == 1 and (stop_trigger or sell):
            effective_exit = px * (1.0 - slip)
            trade_ret = (effective_exit / entry_price - 1.0) - 2 * fee
            trades.append(
                {
                    "entry_time": entry_time,
                    "exit_time": ts,
                    "entry_price": entry_price,
                    "exit_price": px,
                    "return_pct": trade_ret * 100.0,
                    "exit_reason": "stop_loss" if stop_trigger else "signal_sell",
                }
            )
            position = 0
            entry_price = np.nan
            entry_time = None
            capital = units * effective_exit * (1.0 - fee)
            units = 0.0

        elif position == 0 and buy and not sell:
            position = 1
            # Buy at a slightly worse price due to slippage.
            entry_price = px * (1.0 + slip)
            entry_time = ts
            capital = capital * (1.0 - fee)
            units = capital / entry_price

        positions.append(position)

        cur_equity = units * px if position == 1 else capital
        equity[i] = cur_equity
        net_ret[i] = cur_equity / prev_equity - 1.0 if i > 0 else 0.0
        prev_equity = cur_equity

    # Close remaining position at final bar
    if position == 1:
        px = float(data.at[len(data) - 1, "close"])
        ts = data.at[len(data) - 1, "minute"]
        effective_exit = px * (1.0 - slip)
        trade_ret = (effective_exit / entry_price - 1.0) - 2 * fee
        trades.append(
            {
                "entry_time": entry_time,
                "exit_time": ts,
                "entry_price": entry_price,
                "exit_price": px,
                "return_pct": trade_ret * 100.0,
                "exit_reason": "final_close",
            }
        )
        capital = units * effective_exit * (1.0 - fee)
        units = 0.0
        equity[-1] = capital
        net_ret[-1] = equity[-1] / prev_equity - 1.0 if prev_equity > 0 else 0.0

    data["position"] = positions
    data["strategy_ret"] = net_ret
    data["equity"] = equity
    trades_df = pd.DataFrame(trades)
    return data, trades_df


def summarize(results: pd.DataFrame, trades: pd.DataFrame) -> dict:
    total_return = results["equity"].iloc[-1] - 1.0
    bars = len(results)
    ret = results["strategy_ret"]
    vol = ret.std()
    sharpe = np.sqrt(525600) * ret.mean() / vol if vol and not np.isnan(vol) else np.nan

    roll_max = results["equity"].cummax()
    drawdown = results["equity"] / roll_max - 1.0
    max_dd = drawdown.min()

    num_trades = len(trades)
    win_rate = (trades["return_pct"] > 0).mean() if num_trades > 0 else np.nan
    avg_trade = trades["return_pct"].mean() if num_trades > 0 else np.nan

    return {
        "bars": bars,
        "total_return_pct": total_return * 100.0,
        "annualized_sharpe_minute": sharpe,
        "max_drawdown_pct": max_dd * 100.0,
        "num_round_trips": num_trades,
        "win_rate_pct": win_rate * 100.0 if not np.isnan(win_rate) else np.nan,
        "avg_trade_return_pct": avg_trade,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest VR + divergence + VWAP signals.")
    parser.add_argument(
        "--input",
        default="/Users/yy/.hermes/workspace/db/analysis/quant_project/GUNUSDT_binance_tick_1d.csv",
    )
    parser.add_argument(
        "--out-prefix",
        default="/Users/yy/.hermes/workspace/db/analysis/quant_project/GUNUSDT_backtest_vr_div_vwap",
    )
    parser.add_argument("--vr-window", type=int, default=60)
    parser.add_argument("--div-window", type=int, default=60)
    parser.add_argument("--vwap-sustain", type=int, default=3)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument(
        "--stop-loss-pct",
        type=float,
        default=None,
        help="Fixed stop loss percent, e.g. 1.0 for -1%%.",
    )
    args = parser.parse_args()

    bars = load_minute_bars(Path(args.input))
    sig = add_signals(
        bars,
        vr_window=args.vr_window,
        div_window=args.div_window,
        vwap_sustain=args.vwap_sustain,
    )
    results, trades = run_backtest(
        sig,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        stop_loss_pct=args.stop_loss_pct,
    )
    summary = summarize(results, trades)

    out_signals = f"{args.out_prefix}_signals.csv"
    out_trades = f"{args.out_prefix}_trades.csv"
    out_summary = f"{args.out_prefix}_summary.md"

    results.to_csv(out_signals, index=False)
    trades.to_csv(out_trades, index=False)

    with open(out_summary, "w", encoding="utf-8") as f:
        f.write("# 回测结果：VR + 量价背离 + VWAP\n\n")
        f.write(f"- 输入数据: `{args.input}`\n")
        f.write("- K线频率: 1分钟（由tick聚合）\n")
        f.write(
            f"- 参数: VR窗口={args.vr_window}，背离窗口={args.div_window}，VWAP连续确认={args.vwap_sustain}，手续费={args.fee_bps} bps，滑点={args.slippage_bps} bps，止损={args.stop_loss_pct}%\n\n"
        )
        f.write("## 指标\n")
        for k, v in summary.items():
            if isinstance(v, float):
                f.write(f"- {k}: {v:.6f}\n")
            else:
                f.write(f"- {k}: {v}\n")

    print(f"bars={len(results)} trades={len(trades)}")
    print(f"signals_csv={out_signals}")
    print(f"trades_csv={out_trades}")
    print(f"summary_md={out_summary}")
    print("summary_values:")
    for k, v in summary.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
