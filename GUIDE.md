# The Chart-Layering Method — A Visual Guide

> *"Start big. Layer down. The market shows you the answer if you know how to look."*

This guide teaches you to read charts like NIKOLA does — from the **biggest picture** down to the **entry trigger**. It's designed to be read alongside the bot as it runs in paper mode.

---

## 1. Start at the Biggest Chart: 4h (4-Hour Candles)

**Goal:** Identify the dominant trend direction.

- **Bull trend**: Higher highs, higher lows (HH, HL)
- **Bear trend**: Lower highs, lower lows (LH, LL)
- **Sideways/range**: No clear direction — chop

**What NIKOLA does:** `get_market_regime()` loads 200 bars of 4h data (33 days). Computes 200-bar ATR. If ATR/price > 2.5%, the market is trending. `vote_4h()` returns LONG, SHORT, or NEUTRAL.

**Your task:** Draw a trendline connecting the highs. Draw another connecting the lows. If both slope upward → LONG. If both slope downward → SHORT. If they crisscross → NEUTRAL.

---

## 2. Confirm with 1h (1-Hour Candles)

**Goal:** Check for momentum confirmation. Is the trend continuing or stalling?

- **Momentum**: RSI > 50 AND MACD line above signal line
- **Look for**: Higher lows in an uptrend, lower highs in a downtrend

**What NIKOLA does:** 1h is one of three momentum timeframes (1h/30m/15m). All three must agree 2/3 for a STRONG signal. If only 1/3 agrees → STEADY. If 0/3 → CLEAR (hold cash).

**Your task:** Does the 1h RSI stay above 50 in an uptrend? Does MACD make a fresh cross? If yes → trend is alive.

---

## 3. Entry Timing: 30m (30-Minute Candles)

**Goal:** Find the entry window where the trend is ready to resume.

- Look for a pullback to a support/resistance zone
- Watch for a bounce off the trendline
- Volume spike = confirmation

**What NIKOLA does:** 30m is the third momentum vote. If 30m disagrees with 1h and 15m, the entry is weaker.

**Your task:** Mark support/resistance levels on the 30m chart. Notice where the price has bounced before. That's your entry zone.

---

## 4. Refine: 15m (15-Minute Candles)

**Goal:** Fine-tune entry timing. Is the momentum still with us?

- Look for a "bullish engulfing" or "bearish engulfing" candle at the entry zone
- Volume confirmation matters more here
- RSI not yet overbought/oversold (you're entering mid-trend, not at extremes)

**What NIKOLA does:** 15m carries a +5% confidence boost if volume imbalance is detected. This is the "soft boost" — it doesn't override a weak 4h/1h setup.

**Your task:** Wait for the 15m candle to CLOSE in your favor. Don't buy mid-candle.

---

## 5. Precision Entry: 5m (5-Minute Candles)

**Goal:** Get the best price within the entry window.

- Fine-grained momentum
- Watch for order-block alignment
- The price often "sits" at a level before breaking — wait for the break

**What NIKOLA does:** 5m mirrors the 15m vote. Used for price precision, not regime decision.

**Your task:** If the 15m said "enter here," the 5m tells you if the price is cooperating NOW. Wait for the right tick.

---

## 6. Trigger: 1m (1-Minute Candles)

**Goal:** Final alignment before pulling the trigger.

- Does the 1m confirm the 5m?
- Is volume still flowing?
- Any divergence (RSI making new high while price flat)?

**What NIKOLA does:** 1m is the last of 6 timeframes. If all 6 agree → STRONG confidence. If 4-5 agree → MODERATE. If 3 or fewer → REJECT.

**Your task:** If the 1m diverges from the 5m, abort. If it aligns, execute your limit order at the level you planned.

---

## The Full Stack in Practice

```
You're analyzing SOL/USD:

1. 4h: Higher highs + higher lows → LONG trend
2. 1h: RSI 65, MACD bullish cross → momentum confirms
3. 30m: Pullback to $142 support, bouncing → entry window
4. 15m: Bullish engulfing at $142, volume spike → refinement
5.  5m: Break above $143.50 → price precision
6.  1m: Confirms $143.50 break, no divergence → trigger

You enter LIMIT at $143.50.
→ TP1: $145.50 (40% sold, +1.4%)
→ TP2: $147.80 (40% sold, +2.8%)
→ SL2:  $136.70 (full exit, -4.4%)
→ 20% runner trails to infinity
```

---

## Quick Checklist (Before Every Trade)

- [ ] 4h trend is clear (HH/HL or LH/LL)
- [ ] 1h momentum confirms (RSI + MACD aligned)
- [ ] 30m shows a valid pullback zone
- [ ] 15m gives a clean entry signal (candle close)
- [ ] 5m confirms price is cooperating
- [ ] 1m has no divergence — final trigger aligned
- [ ] 4/6 or 5/6 timeframes agree → execute limit order
- [ ] TP/SL pre-planned → risk ≤ 2.1%, reward ≥ 1.4%

---

## Common Mistakes to Avoid

1. **Skipping the 4h** — entering on 15m/5m without knowing the big trend
2. **Chasing momentum** — buying at extremes because "everyone's doing it"
3. **Ignoring 1m divergence** — price makes a new high but RSI doesn't → abort
4. **Using market orders** — NIKOLA never does; limit orders control your entry price
5. **Removing stops** — hope is not a strategy. Let the math decide.

---

## Practice Exercise

Open a chart of any BTC pair. Walk through all 6 timeframes:

1. What does the 4h say? (Trend direction)
2. Does 1h confirm? (Momentum)
3. Where's the 30m entry zone? (Support/resistance)
4. What does 15m show? (Refinement)
5. What's happening on 5m? (Precision)
6. Does 1m confirm? (Trigger)

Write down your answer for each BEFORE checking the bot's decision. This is how you learn to think like NIKOLA.

---

*This guide is the "separate GUIDE.md" referenced in the README. It's meant to be read slowly, chart by chart, with tradingView (or similar) open beside you.*
