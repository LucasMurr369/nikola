"""
Nikola engine indicators.

Pure-Python implementations ported from the live margin bot's helper functions
(lines 348-425 of live_margin_bot.py). These operate on candle lists
[ts, open, high, low, close, volume] and have no exchange dependency —
making every indicator unit-testable without a Kraken connection.
"""
from __future__ import annotations

from typing import Optional


def get_latest_price(candles: list[list]) -> Optional[float]:
    """Return the close of the most recent candle."""
    if not candles:
        return None
    return float(candles[-1][4])


def get_atr(candles: list[list], period: int = 14) -> Optional[float]:
    """Average True Range over the last ``period`` candles."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(len(candles) - period, len(candles)):
        c = candles[i]
        h, l = float(c[2]), float(c[3])
        prev_close = float(candles[i - 1][4])
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    return sum(trs) / len(trs)


def get_rsi(candles: list[list], period: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder, simple averaging)."""
    if len(candles) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(candles) - period, len(candles)):
        change = float(candles[i][4]) - float(candles[i - 1][4])
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_ema(candles: list[list], period: int) -> Optional[float]:
    """EMA over the close prices."""
    if len(candles) < period:
        return None
    closes = [float(c[4]) for c in candles]
    multiplier = 2.0 / (period + 1.0)
    ema = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        ema = (closes[i] - ema) * multiplier + ema
    return ema


def get_macd(candles: list[list]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """MACD line, signal line (EMA-9 of MACD hist), histogram (12, 26, 9)."""
    if len(candles) < 52:
        return None, None, None
    closes = [float(c[4]) for c in candles]
    ema12 = sum(closes[:12]) / 12
    ema26 = sum(closes[:26]) / 26
    mult12 = 2.0 / 13.0
    mult26 = 2.0 / 27.0
    for i in range(12, len(closes)):
        ema12 = (closes[i] - ema12) * mult12 + ema12
    for i in range(26, len(closes)):
        ema26 = (closes[i] - ema26) * mult26 + ema26
    macd_line = ema12 - ema26

    # Build full MACD series, then EMA(9) for the signal line
    macd_vals = []
    e12 = sum(closes[:12]) / 12
    e26 = sum(closes[:26]) / 26
    for i in range(26, len(closes)):
        e12 = (closes[i] - e12) * mult12 + e12
        e26 = (closes[i] - e26) * mult26 + e26
        macd_vals.append(e12 - e26)
    if len(macd_vals) < 9:
        return macd_line, None, None
    signal = sum(macd_vals[-9:]) / 9
    mult_sig = 2.0 / 10.0
    for i in range(9, len(macd_vals)):
        signal = (macd_vals[i] - signal) * mult_sig + signal
    hist = macd_line - signal
    return macd_line, signal, hist


def get_volume_imbalance(candles: list[list]) -> Optional[float]:
    """Volume imbalance over last 20 candles — high/low volume partition asymmetry."""
    if len(candles) < 20:
        return None
    volumes = [float(c[5]) for c in candles[-20:]]
    avg_vol = sum(volumes) / len(volumes)
    if avg_vol == 0:
        return 0.0
    sorted_vols = sorted(volumes)
    mid = len(sorted_vols) // 2
    low_sum = sum(sorted_vols[:mid])
    high_sum = sum(sorted_vols[mid:])
    denom = high_sum + low_sum
    return (high_sum - low_sum) / denom if denom > 0 else 0.0
