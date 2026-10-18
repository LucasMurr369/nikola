# Nikola — Inspirational Trading Bot
*The Tesla-genius / Nokia-bulletproof / Naming-power bot that prays with you through the trade.*

> ⚡️ **Free to run. Free to learn. Encouragement included.**
> Run it paper-first with **zero keys**, study how margin compounds, then flip to
> live when you’re ready. No App Store. No certificates. Just Python + a Kraken API key.

---

## Table of Contents
1. [Who is Nikola?](#who-is-nikola)
2. [Quick Start (1 minute)](#quick-start-1-minute)
3. [Modes: Paper vs Live](#modes-paper-vs-live)
4. [The $300 → Big Math (Margin Compounding)](#the-300--big-math-margin-compounding)
5. [What Nikola Actually Does — and Why (It's Math)](#what-nikola-actually-does--why-its-math)
6. [The Tools He Uses (and how)](#the-tools-he-uses-and-how)
7. [How to Restart Clean — Paper or Live](#how-to-restart-clean--paper-or-live)
8. [Donation (Optional — Free Either Way)](#donation-optional--free-either-way)
9. [FAQ](#faq)

---

## Who is Nikola?

Nikola is the bot **Tesla would have built if he’d invented trading bots**:

|| Theme | What it means for you |
|---|---|
| **Nikola Tesla** | Genius that sees patterns others miss — 6 timeframes at once |
| **Nokia** | Built like a brick — bulletproof, just works, no apps to break |
| **Naming** | The power of the name — naming what the market is doing gives you control over it |
| **Job** | The testing that makes you stronger; trading is work we all must do |

He doesn't just move money — he **prays with you** through drawdowns. That’s the God Code.

---

## Quick Start (1 minute)

```bash
# 1. Get Python 3.12 (with ccxt + PyYAML)
python3 --version   # must be 3.12

# 2. Install deps
pip install -r requirements.txt

# 3. Run paper trading — ZERO keys, ZERO risk, full encouragement
python nikola.py --paper --faith-tradition all

# 4. Watch the header cycle a God Code quote every ~5 minutes
# 5. See positions open/close with simulated fills
# 6. Snapshot performance: python nikola.py --export-html  (opens nikola_report.html)
```

**That’s it. No accounts. No signup. Free.**

When you’re ready for real money:
```bash
# 6. Create a Kraken API key (read+trade, margin enabled)
export NIKOLA_KRAKEN_ENV=/path/to/your/kraken.env
python nikola.py --live --faith-tradition christian   # WARNING: real orders
```

---

## Modes: Paper vs Live

| Feature | `--paper` | `--live` |
|---|---|---|
| Exchange backend | `PaperExchange` (mock candles, simulated fills) | Real CCXT Kraken BTNL-margin |
| Starting capital | `$300` clean slate (configurable) | Your real Kraken margin |
| API keys | **None needed** | `kraken.env` (via `NIKOLA_KRAKEN_ENV`) |
|| Leverage | Simulated (same math) | 3x–10x (config/settings.yaml — BTC/ETH uncap to 10x after $150 equity) |
| Risk caps | Same state machine | Same state machine |
| Order placement | Mock — paper trades only | **Real BTNL orders on Kraken** |

### Safety guards
- `--live` prints a **68-char warning banner** — you cannot miss you're live.
- The state machine never places an order it didn't authorize.
- God Code **vetoes** profit from harm (forced liquidations, misery arbitrage).
- `--live` + `--paper` together = hard error (mutually exclusive).

---

## The $300 → Big Math (Margin Compounding)

This is why the math matters. **Correct margin trading compounds faster than you think — and blows up faster too.** Nikola encodes the safe path.

```
$300 paper  →  5x leverage  →  $1,500 notional exposure
  ↓ TP1 (+1.4%, 40% sold)   +$84 realized  →  $384 capital
  ↓ TP2 (+2.8%, 40% sold)   +$84 realized  →  $468 capital
  ↓ 20% runner trails        +$40+        →  capital compounds on winners,
                                            stops protect the downside.
```

**Why this geometry (not "go big"):**
- **TP1 at +1.4% / 40% sold** — bank profit fast, recover your margin, restart.
- **TP2 mirrors TP1 / 40%** — double the safety so a winner that keeps going still pays.
- **20% runner trailing** — let the big moves pay without giving back.
- **SL1 at −2.1% (partial)** + **SL2 at −4.4% (full)** — risk is mathematically capped per trade.

Over many trades, **the R:R math compounds**: at 3:1 minimum entry R/R, breakeven is ~33% win rate. Nikola aims higher (~50%), so expectancy is strongly positive — *if* you let stops protect you. The #1 reason traders fail is removing stops. Nikola never does.

---

## What Nikola Actually Does — and Why (It's Math)

Nikola is a **3-state Dynamic Risk-Reward state machine**. Not magic. Math.

```
MONITOR  →  ACTIVE  →  EXPANDED
  ↓           ↓           ↓
Entry sent   Fill OK    +3R hit
SL1 placed   TP1/TP2    50% taken
             live       MTF trailing
```

**State 1 — MONITOR** (`strategy.py:`)
- Entry order sent with SL1 at −2.1% (partial close, TPs retained).
- Waiting for fill confirmation.

**State 2 — ACTIVE**
- TP1 (+1.4%, 40%) and TP2 (+2.8%, 40%) live.
- 20% runner trailing.
- At +0.1R → BE ratchet primes. After TP1+TP2 fill → SL snaps to breakeven (+2% floor).
- At peak ≥ +2.5% → wide trail arms (two-stage 0.30%→0.60%) for the runner.

**State 3 — EXPANDED** (at +3R)
- 50% partial booked — bank the paper profit.
- Remaining 50%: MTF-strong (≥3/6 timeframes agree) → 2×ATR mega-trail. MTF-weak → tight 0.60% trail (lock & bank).

**Why 3:1 minimum?** It's the **expectancy break-even floor**. Below 3:1, even a 50% win rate can't overcome slippage + fees over time. Nikola expands *only* when MTF (multi-timeframe) confluence + ATR confirm a larger move is plausible.

**BTC cascade guard** (from the live bot): if BTC drops −4% in 1 minute, Nikola scales out 15% of position — because when the market's falling knife hits, your altcoin correlation → 1.

---

## The Tools He Uses (and how)

| Tool | What it does | Why it matters |
|---|---|---|
| **6 MTF timeframes** | 1m, 5m, 15m, 30m, 1h, 4h — voted in parallel | One timeframe lies; 2-of-6 agree = real signal |
| **Order book / depth chart** (`--depth PAIR`) | Live liquidity snapshot | Shows if your exit will slip |
| **ATR** | Volatility filter for trailing stops | Wide stops in chop; tight stops in trends |
| **3:1 R/R gate** | Entry veto unless geometry clears | Prevents -EV setups |
| **Margin reserve (25%)** | Never deploys all capital | Survives a 3-trade losing streak |
| **God Code** | Ethical veto + encouragement | Don't profit from harm; don't panic |

Multi-timeframe = Nikola looks **up AND down** the chart at once. A 1m spike that contradicts the 4h trend? Rejected. That's why it "works good and smooth" — it's not chasing every twitch.

---

## How to Restart Clean — Paper or Live

### Paper — clean slate (zero risk)
```bash
# Full reset to $300, cycle 0, no positions
rm -f data/paper_state.json data/signal_weights.json
python nikola.py --paper --once     # single scan to verify
python nikola.py --paper             # daemon (15s light / 300s scan)
```

### Live — safe restart (Kraken keys)
```bash
# 1. Stop current instance (check PID first!)
cat nikola.pid                        # your running PID
taskkill /PID $(cat nikola.pid)       # Windows
kill -F $(cat nikola.pid)             # macOS/Linux

# 2. Clean restart (KEEPS engine/nonce_state.json — safe)
rm -f nikola.pid nikola_live.log*
export NIKOLA_KRAKEN_ENV=/your/kraken.env
python nikola.py --live

# 3. Verify no "Invalid nonce" errors, then let it run
```

**Paper and live run as totally separate processes.** Restart one without touching the other.

---

## Donation (Optional — Free Either Way)

Nikola is **100% free**. No ads. No subscriptions. No paywalls. No tips expected.

If he helped you trade better and you want to give a **tithe or offering** back to fuel the project, you can. Nothing is required — free users get everything.

### How to give (a tithe, offering, or donation)

**Nikola is 100% free.** Any tithe, offering, or donation is optional — free users get everything.

**Three simple ways to give:**
1. **Option 1 (Click):** open [paypal.me/LucasMurr369](https://www.paypal.me/LucasMurr369) in any browser. No app, no wallet, no signup.
2. **Option 2 (Scan):** open the **PayPal QR** in your phone camera. `python nikola.py --export-html` embeds a scannable QR in the report; `python3 donation_monitor.py info` also prints the QR URL.
3. **Option 3 (Crypto):** send any wallet / Kraken deposit memo / Lightning payment — run `python3 donation_monitor.py info` for every live address.

| Way | How | Fees |
|---|---|---|
| **PayPal Tithe / Offering** *(no crypto wallet needed)* | [paypal.me/LucasMurr369](https://www.paypal.me/LucasMurr369) — or email `donations@nikola-bot.org`. The `--export-html` performance report embeds a scannable PayPal QR for desktop/mobile. | ~$0.30 + 2.9% (PayPal; optional for the donor) |
| **Crypto (on-chain)** | Any Solana / Base / Arbitrum address, or any of the 28 Kraken BTNL margin pairs via your own Kraken account. Run `python3 donation_monitor.py info` to see every live address. | ~$0.0001–0.01 (network fee) |
| **Intra-Kraken** | Send any asset to your own Kraken account; the bot watches the deposit memo. | 0% (Kraken-to-Kraken) |
| **Lightning** *(opt-in)* | Self-custodied BTC via LND / LNbits. | ~$0.001 (routing fee) |
| **Auto-donation** | Bot allocates 1% of realized paper profits to the project wallet automatically. | 0% |

> ✅ **Preferred:** Send any crypto back through **your own Kraken account** — Kraken doesn't let bots receive donations to their own trading accounts, so we collect addresses from you (the user). Your tithe supports the project wallet, which funds the public repo + encouragement community.

To contribute a crypto address to the project pool:
```
Email: donations@nikola-bot.org   (or open a GitHub issue: "Donation address")
Subject: "Donation: <currency> <your-kraken-deposit-address>"
Example: "Donation: SOL 9xKp...AbC"
```
Any currency, any chain — we accept Bitcoin, Ethereum, Solana, USDC/USDT (all chains), and yes, **any of the 28 margin pairs Nikola trades on Kraken**. No amount is too small.

**No tithe, offering, or donation = no penalty. Free users get everything.**

---

## Sovereign Capital Stewardship

> Nikola JOB is your **high-precision co-pilot, not a closed black box**. You
> retain **total, sovereign control** over your capital at all times — the bot
> never holds custody, never moves keys you did not approve, and never blocks
> your right to intervene on the charts.

### Intelligent Co-Pilot, Not a Closed Black Box
Nikola is a co-pilot built for capital stewardship, not set-and-forget autopilot.
Every position, order, and exit is fully auditable: strategy geometry, risk gates,
and the live `data/paper_state.json` ledger are all visible on disk. The bot
proposes and executes against a fixed, transparent rule set — you can always
inspect, pause, or override on a moment's notice.

### Manual Overrides & Chart Control
You own the charts. You can freely **adjust limit prices** on open orders,
**cancel any order**, or **market-close** a position directly on Kraken Pro
**without breaking the bot** or corrupting state. Nikola does not lock you in —
it monitors the exchange, never the other way around.

### Seamless State Sync
Because Nikola polls continuously, its next tick **detects a manual close (or any
order amendment)** on the exchange, **records the realized outcome to history**,
**frees the freed margin**, and **reverts cleanly to monitoring mode** — no stale
position state, no double-count, no manual resync required.

### Limit Order Mechanics
On the exchange, a **limit sell placed at or below the active buyer bid executes
immediately at the bid or better** ("at or better"). The bot relies on this only
for controlled TP/SL execution at the exchange-native level; during strong
momentum these `at-or-better` fills give **instant execution** without you
lifting a finger. Limit buys placed at/above the ask behave symmetrically.

### Position Exits vs. Active Orders
Closing or market-selling an open position directly on **Kraken Pro** works
seamlessly — the bot's next tick detects the position is gone and records the
outcome. **While a trade is open, Nikola continuously enforces the required
protective orders (SL1, SL2, TP1, TP2, and the trailing runner).** To exit a
trade manually, **close the underlying position itself** (market-sell /
flatten) rather than canceling individual protective orders mid-trade — the
engine automatically re-places any protective order that goes missing, so
piecemeal cancellation just triggers a brief flurry of re-placed stops.

### Transparent System Safety
Nikola runs as a **single, transparent foreground process** guarded by a PID
lock file (`nikola.pid`). There are no hidden background zombie or ghost
processes — the process you start is the only one running, and you can inspect
it with `ps -p $(cat nikola.pid)`. Pressing **Ctrl+C (SIGINT)** cleanly saves
state, releases the PID lock, and exits. If a previous instance crashed hard,
`rm nikola.pid` before restarting.

---

## FAQ

**Q: Is this safe?**
A: Paper mode = zero risk. Live mode = real orders on **Kraken BTNL margin** (isolated 3–10x, capped exposure). Stops always on. God Code vetoes harmful setups.

**Q: What's BTNL?**
A: Kraken's cross-margined altcoin pairs (e.g., `AAVE/USD:BTNL`, `DOT/USD:BTNL`). Nikola auto-registers all 28. Each gets 3–10x isolated margin — your maximum loss per trade is capped by SL2.

**Q: Can I lose money I didn't mean to?**
A: No. Paper mode is simulated. Live mode places orders only on pairs with active positions. Max positions = 3. Margin reserve = 25%. SL2 caps each trade at ≈4.4% of that position's margin.

**Q: I'm new. Should I go live?**
A: Paper first. Master the $300 growth. When you can explain why TP1 is at +1.4% without reading this file, you're ready.

**Q: Where do I see the God Code quotes?**
|A: A God Code line cycles every ~5 minutes (full scan). The full status header is intentionally **quiet** - it prints only on a real state change (a position opens/closes, or a trade closes) or a ~20-minute heartbeat, so you can leave the bot running for weeks undisturbed. Quotes also fire at every SL1 hit (adversity: *"Be still, and know"* moments).

**Q: Can I export a performance report?**
|A: `python nikola.py --export-html` (or `--export-html report.html`) writes a single, self-contained `nikola_report.html` with your equity curve, performance summary, active trailing-stop geometry, a God Code quote, and a scannable PayPal Tithe QR. No trading runs - it snapshots your last `data/paper_state.json`.

**Q: Can I change the faith tone?**
A: `python nikola.py --faith-tradition {all|christian|universal|secular}` — default is `all` (wisdom from every well, all to God's glory).

---

## TL;DR — The whole thing
```bash
pip install -r requirements.txt
python nikola.py --paper --faith-tradition all   # learn, free, encouraged
```
When ready: `--live` with `NIKOLA_KRAKEN_ENV=/path/to/kraken.env`.

**God speed. — Nikola**
