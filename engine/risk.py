"""
Nikola engine risk math — SL/TP ladder + position sizing.

Ports the bot's proven ``compute_sl_tp_ladder`` (live_margin_bot.py line 760)
plus the conviction-tiered leverage/sizing helpers. All functions are
pure (no exchange dependency) so they're trivially unit-testable with mock
prices.

The ladder geometry (user directive, currently live on Kraken):

    SL1  -2.10%  → partial close (40% of base) on 1m/5m candle close ≥ 1.5% adverse, TPs retained
    TP1  +1.4%   → 40% of base exits  (2× SL1 distance)
    TP2  +2.8%   → 30% of base exits  (2× TP1 distance — user 2026-10-07)
    30%  runner  → trails 0.30% → 0.60% wide @ +2.5%
    SL2  -4.40%  → full exit if the partial-stop never saved us

R-multiples (risk unit = entry × SL1_PCT):
    R1 = SL1 dist (1.0R)        R2 = 2×SL1 (2.0R)
    TP1 ≈ 0.67R (alts) / 0.48R (majors)   TP2 ≈ 1.33R / 0.95R
    EXPANDED trigger = 3.0R   (the dynamic-RR gate)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

from .config import (
    SL1_PCT, SL2_PCT, TP_RUNG_PCTS, MAJOR_TP_PCTS,
    TRAIL_STOP_PCT, TRAIL_WIDE_PCT, TRAIL_WIDE_ARM_PCT,
    BREAKEVEN_BUFFER_PCT, SL_LIMIT_BAND_PCT, FEE_TERM_PCT,
    MAX_POSITION_MARGIN_USD,
    TOTAL_MARGIN_BUDGET_USD, MARGIN_RESERVE_PCT,
    MARGIN_TIERS, LEV_TIERS, LEVERAGE_CAP, LEVERAGE_FLOOR, PREFERRED_LEVERAGE,
    LEV_UNLOCK_EQUITY_USD, HIGH_LEV_PAIRS, PAIR_LEVERAGE, SYMBOLS,
    min_base_for, round_amount, tp_rungs_for, leverage_for,
    margin_tier_for, deployable_margin, group_of,
)


# ---------------------------------------------------------------------------
# SL/TP ladder
# ---------------------------------------------------------------------------
def compute_sl_tp_ladder(price: float, atr: float, direction: str,
                         pair: Optional[str] = None) -> Tuple[float, float, float, List[Dict]]:
    """Two-stage SL + TP ladder. Returns (sl1, sl2, main_tp, rungs).

    SL1 at -SL1_PCT: partial close (40% of base), TPs retained.
    SL2 at -SL2_PCT: full exit of remaining position (2x SL1 distance).
    """
    rungs = tp_rungs_for(pair)
    stop_dist_sl1 = price * SL1_PCT
    stop_dist_sl2 = price * SL2_PCT
    tp_dist = price * rungs[-1][2]
    if direction == "LONG":
        sl1_price = price - stop_dist_sl1
        sl2_price = price - stop_dist_sl2
        main_tp = price + tp_dist
    else:
        sl1_price = price + stop_dist_sl1
        sl2_price = price + stop_dist_sl2
        main_tp = price - tp_dist

    ladder = []
    for name, pct, pct_level in rungs:
        if direction == "LONG":
            rung_price = price + price * pct_level
        else:
            rung_price = price - price * pct_level
        ladder.append({
            "name": name, "price": rung_price, "pct": pct,
            "filled": False, "amount": 0.0,
        })
    return sl1_price, sl2_price, main_tp, ladder


def compute_sl_tp(price: float, atr: float, direction: str) -> Tuple[float, float]:
    """Simple two-point SL/TP (legacy, for paper-mode quick entry)."""
    stop_dist = price * SL1_PCT
    tp_dist = price * TP_RUNG_PCTS[-1][2]
    if direction == "LONG":
        return price - stop_dist, price + tp_dist
    return price + stop_dist, price - tp_dist


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------
@dataclass
class SizeResult:
    base_amount: float
    margin_cost: float
    leverage: int
    entry_price: float
    atr: float
    risk_distance: float    # |SL1 − entry|  ≈ R in dollars-per-unit
    r_per_pct: float        # R per 1% price move


def size_position(pair: str, price: float, atr: float, confidence: float,
                  direction: str, budget: float = TOTAL_MARGIN_BUDGET_USD,
                  equity: float = 0.0) -> Optional[SizeResult]:
    """Conviction-tiered position sizing.

    Mirrors deploy_signal's sizing (live_margin_bot.py lines 1482-1497):
    margin = min(margin_tier_for(conf), budget_left);
    base = (margin * leverage) / price.

    $20 position cap is actively enforced by config.MAX_POSITION_MARGIN_USD
    ($20.0). margin_tier_for returns a percentage of the deployable budget.
    """
    from .config import EQUITY_SCALE
    pair_leverage = leverage_for(confidence, pair, equity=equity)
    budget_left = deployable_margin(budget) * (1.0 - MARGIN_RESERVE_PCT)
    margin_allowed = min(
        margin_tier_for(confidence, budget),
        budget_left,
        MAX_POSITION_MARGIN_USD,
    )
    margin_cost = margin_allowed
    base_amount = (margin_cost * pair_leverage) / price if price > 0 else 0.0
    pair_min = min_base_for(pair)
    if base_amount < pair_min:  # below Kraken minimum for this pair
        # Scale up margin so the order still lands with a valid size.
        # If the budget can't afford the minimum face value, bail out cleanly.
        required_margin = (pair_min * price) / pair_leverage
        if required_margin > margin_cost:
            return None  # not enough budget to meet minimum base size
        margin_cost = required_margin
        base_amount = (margin_cost * pair_leverage) / price

    risk_distance = price * SL1_PCT
    # R per 1% move = (price × 0.01) / risk_distance
    r_per_pct = (price * 0.01) / risk_distance if risk_distance > 0 else 0.0
    return SizeResult(
        base_amount=base_amount,
        margin_cost=margin_cost,
        leverage=pair_leverage,
        entry_price=price,
        atr=atr,
        risk_distance=risk_distance,
        r_per_pct=r_per_pct,
    )
