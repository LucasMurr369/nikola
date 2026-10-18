#!/usr/bin/env python3
"""Short-side verification test — confirms TP/SL reversal + R:R math for SHORT vs LONG."""
import sys
sys.path.insert(0, '.')

from engine import config as cfg
from engine.strategy import DynamicRiskReward, Position, PositionState


def test_long_short_tp_sl():
    """Verify TP1/TP2/SL1/SL2 are reversed correctly for SHORT vs LONG.
    Uses SOL/USD (default TP ladder: +1.4%, +2.8%) for deterministic R-values.
    Also tests BTC/USD (custom ladder: +1.0%, +2.0%).
    """
    eng = DynamicRiskReward()
    entry = 100.0
    base_amount = 1.0
    leverage = 5
    confidence = 0.80

    sl1_pct = cfg.SL1_PCT
    sl2_pct = cfg.SL2_PCT
    tp1_pct = cfg.TP_RUNG_PCTS[0][2]  # 0.014
    tp2_pct = cfg.TP_RUNG_PCTS[1][2]  # 0.028

    r_tp1_exp = tp1_pct / sl1_pct   # 0.667
    r_tp2_exp = tp2_pct / sl1_pct   # 1.333
    r_sl2_exp = sl2_pct / sl1_pct   # 2.095

    print(f"Config: SL1={sl1_pct} SL2={sl2_pct} TP1={tp1_pct} TP2={tp2_pct}")
    print(f"Expected R: TP1=+0.67  TP2=+1.33  SL2=-2.10\n")

    # --- LONG (SOL/USD) ---
    pos_long = eng.position_from_signal("SOL/USD", "LONG", entry, base_amount, leverage, confidence, "TEST")
    print("=== LONG (SOL/USD) ===")
    print(f"  Entry: ${pos_long.entry_price:.2f}  SL1: ${pos_long.sl1_price:.2f}  TP1: ${pos_long.tp.tp1_price:.2f}  TP2: ${pos_long.tp.tp2_price:.2f}  SL2: ${pos_long.sl2_price:.2f}")
    assert pos_long.sl1_price < entry and pos_long.sl2_price < entry, "LONG SLs below entry"
    assert pos_long.tp.tp1_price > entry and pos_long.tp.tp2_price > entry, "LONG TPs above entry"
    rd = pos_long.risk_distance
    assert abs(abs(pos_long.tp.tp1_price - entry)/rd - r_tp1_exp) < 0.001
    assert abs(abs(pos_long.tp.tp2_price - entry)/rd - r_tp2_exp) < 0.001
    assert abs(abs(pos_long.sl2_price - entry)/rd - r_sl2_exp) < 0.001
    print(f"  R: TP1=+{abs(pos_long.tp.tp1_price-entry)/rd:.2f} TP2=+{abs(pos_long.tp.tp2_price-entry)/rd:.2f} SL2=-{abs(pos_long.sl2_price-entry)/rd:.2f}  ✅")

    # --- SHORT (SOL/USD) ---
    pos_short = eng.position_from_signal("SOL/USD", "SHORT", entry, base_amount, leverage, confidence, "TEST")
    print("\n=== SHORT (SOL/USD) ===")
    print(f"  Entry: ${pos_short.entry_price:.2f}  SL1: ${pos_short.sl1_price:.2f}  TP1: ${pos_short.tp.tp1_price:.2f}  TP2: ${pos_short.tp.tp2_price:.2f}  SL2: ${pos_short.sl2_price:.2f}")
    assert pos_short.sl1_price > entry and pos_short.sl2_price > entry, "SHORT SLs above entry"
    assert pos_short.tp.tp1_price < entry and pos_short.tp.tp2_price < entry, "SHORT TPs below entry"
    rd_s = pos_short.risk_distance
    assert abs(abs(pos_short.tp.tp1_price - entry)/rd_s - r_tp1_exp) < 0.001
    assert abs(abs(pos_short.tp.tp2_price - entry)/rd_s - r_tp2_exp) < 0.001
    assert abs(abs(pos_short.sl2_price - entry)/rd_s - r_sl2_exp) < 0.001
    print(f"  R: TP1=+{abs(pos_short.tp.tp1_price-entry)/rd_s:.2f} TP2=+{abs(pos_short.tp.tp2_price-entry)/rd_s:.2f} SL2=-{abs(pos_short.sl2_price-entry)/rd_s:.2f}  ✅")

    # --- r_multiple() direction check ---
    r_long_tp1 = eng.r_multiple(pos_long, pos_long.tp.tp1_price)
    r_short_tp1 = eng.r_multiple(pos_short, pos_short.tp.tp1_price)
    r_short_sl2 = eng.r_multiple(pos_short, pos_short.sl2_price)
    assert abs(r_long_tp1 - r_tp1_exp) < 0.001, f"LONG TP1 R: {r_long_tp1:.3f}"
    assert abs(r_short_tp1 - r_tp1_exp) < 0.001, f"SHORT TP1 R: {r_short_tp1:.3f}"
    assert abs(r_short_sl2 + r_sl2_exp) < 0.001, f"SHORT SL2 R: {r_short_sl2:.3f}"
    print(f"\n  r_multiple LONG  @TP1: {r_long_tp1:+.3f}  ✅ (price up = profit)")
    print(f"  r_multiple SHORT @TP1: {r_short_tp1:+.3f}  ✅ (price down = profit)")
    print(f"  r_multiple SHORT @SL2: {r_short_sl2:+.3f}  ✅ (price up = loss)")

    # --- BTC custom ladder ---
    print(f"\n=== BTC/USD Custom Ladder (+1.0%/+2.0%) ===")
    pos_btc_short = eng.position_from_signal("BTC/USD", "SHORT", 80000.0, base_amount, leverage, confidence, "TEST")
    print(f"  SHORT entry: ${pos_btc_short.entry_price:,.0f}")
    print(f"  TP1: ${pos_btc_short.tp.tp1_price:,.0f} (below)  TP2: ${pos_btc_short.tp.tp2_price:,.0f} (below)")
    print(f"  SL1: ${pos_btc_short.sl1_price:,.0f} (above)  SL2: ${pos_btc_short.sl2_price:,.0f} (above)")
    assert pos_btc_short.tp.tp1_price < pos_btc_short.entry_price, "SHORT TP1 below entry"
    assert pos_btc_short.sl2_price > pos_btc_short.entry_price, "SHORT SL2 above entry"

    print(f"\n✅ ALL SHORT-SIDE TESTS PASSED")
    print(f"   TP/SL reversal verified for LONG and SHORT")
    print(f"   R:R math matches config (TP1=+0.67, TP2=+1.33, SL2=-2.10)")
    print(f"   r_multiple() returns +R for profit, -R for loss in both directions")


if __name__ == "__main__":
    test_long_short_tp_sl()
