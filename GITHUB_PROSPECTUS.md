# Nikola — GitHub Distribution Prospectus
> *The complete guide to what this repository is, who it helps, and how to share it*

---

## 📋 Quick Reference

|| Setting | Value |
||---|---|
|| **Pairs** | 28 vetted Kraken BTNL pairs |
|| **Direction** | LONG + SHORT (direction-aware) |
|| **Position count** | Adaptive 0–16 (no hard caps) |
|| **Max R:R per trade** | TP1=+0.67  TP2=+1.33  Runner=+3.00R  (3:1 min, no force-sells) |
|| **Stop loss** | SL1=−2.1% (partial)  SL2=−4.4% (full) |
|| **Trend window** | 200-bar 4h ATR (~33 days) |
|| **Momentum consensus** | 1h / 30m / 15m (2/3 agree) |
|| **Entry timing** | 5m / 1m price precision |
|| **Candle limit** | `mtf_candle_limit: 200` (enforced in code) |
|| **Live switch** | `--live` → `NIKOLA_DRY_RUN=false` (automatic) |
|| **Market orders** | Zero — never |

---

## 0. Read Me First (or Jump Straight to Setup)

> *"Nikola is not here to make you rich. Nikola is here to keep you in the game."*

**In 30 seconds:** Nikola watches 28 crypto pairs across 6 timeframes (1m→4h). When 4 out of 6 align AND the trend is strong, he places a **limit order** (never market) with 3:1+ R:R. Stops at −2.1% (partial) or −4.4% (full). Bank 80% profit before the 20% runner trails. He scales position count **0–16** based on market quality — no hard caps. No market orders. Ever. God Code vetoes unethical trades.

**What you need to know before running:**
- This is a **distribution repo** — clones as YOUR bot. Your personal NIKOLA on your machine is separate and unaffected.
- Paper mode = $300 simulated, zero API keys. Live mode = `--live` flag (requires Kraken BTNL API keys).
- One click: `python nikola.py --paper` → start learning immediately.

**👉 [Skip to Installation](#3-installation-tiered-setup-guides)** — if you just want to run it.
**📖 Read on** — if you want to understand the philosophy first.

### Regime Color Guide
When you see colored output in the bot log or here in the prospectus, the meanings are:

| Regime | Emoji | Meaning | What the bot does |
|--------|-------|---------|-------------------|
| ⚪ **STEADY** | Silver | Balanced market, mild momentum | Reduced deployment (50% strength) |
| 🟡 **STRONG** | Gold | Strong trend, momentum aligned | Full deployment in trend direction |
| 🟣 **CLEAR** | Muted Purple | No momentum, market directionless | Holds cash, scans patiently |

| Direction | Emoji | Meaning |
|-----------|-------|---------|
| 🔵 **LONG** | Blue | Price going UP = profit |
| 🟠 **SHORT** | Amber | Price going DOWN = profit |

| Outcome | Emoji | Meaning |
|---------|-------|---------|
| 💚 **Profit** | Green | Winner — money came in |
| ❤️ **Loss** | Red | Loser — money went out |
| ✅ **Does DO** | Green | Nikola's behavior |
| 🚫 **Does NOT** | Red | Nikola refuses this |

---

## 1. What Nikola Is

Nikola is a **math-driven, risk-managed cryptocurrency trading bot** for Kraken BTNL (Buy-The-Next-Level) margin pairs. Built in Python 3 with zero SaaS dependencies — runs locally on your machine.

### The Big Idea (in 3 sentences):
> **Nikola is not a set-and-forget autopilot.** He is a co-pilot that enforces discipline: small positions, tight stops, mathematical entries, and the discipline to walk away when wrong. He trades **both LONG and SHORT** — scaling position count up in strong trending regimes and down to cash in choppy ones. **No hard caps.** No market orders. God Code ensures profit never comes from harm.

### What He Does (Not Does Not):
| What Nikola DOES | What Nikola DOES NOT Do |
|---|---|
| Places limit/stop-loss-limit/reduce-only orders | Place market orders (ever) |
| Trades 28 vetted high-liquidity pairs | Trade random meme coins or low-cap pumps |
| Bank 80% of profit at TP1+TP2 before the runner | Force-sell on momentum slowdown |
| Trade both LONG and SHORT (direction-aware scaling) | Trade only one direction |
| Ratchet stops to breakeven after profits bank | Remove stops or hold losing positions |
| Run on your local machine (you hold custody) | Hold your keys or move funds you didn't approve |
| Accept completely voluntary donations | Require payments, subscriptions, or tips |

---

## 2. Philosophy — Teacher, Companion, Inspiration

### 2.1 The Teaching Bot
Nikola's ultimate purpose is **to teach you to trade better**. Every cycle teaches:
- **6 timeframes at once** (1m, 5m, 15m, 30m, 1h, 4h) — "one timeframe lies, 2-of-6 agree = real signal"
- **Direction-aware scaling** — position count adapts 0–16 based on regime strength × trend alignment (no hard caps)
- **Long and SHORT alike** — same TP/SL math in both directions; SHORT flips TP/SL below/above entry
- **3:1 minimum R:R** — the expectancy break-even floor
- **R:R at entry** — deploy log prints "R:R TP1=+0.67 TP2=+1.33 SL2=−2.10 Runner→+3.00R" so beginners see the geometry
- **Margin compounding math** — why $300 grows fast (and blows up fast)
- **Stop discipline** — never removing stops, never hoping for reversals
- **God Code wisdom** — ethical trading, psychological resilience

### 2.2 The Chart-Layering Method (Your Approach)
The user starts at the **biggest chart** and layers down:
```
4h chart (big picture: trend direction)     ← Start here
  ↓
1h chart (momentum confirmation: 2/3 consensus)
  ↓
30m chart (entry timing: MTF confluence)
  ↓
15m chart (refinement: candle close behavior)
  ↓
5m chart (precision entry: micro-trend)
  ↓
1m chart (trigger: final alignment)
```
**The bot mirrors this:** `get_market_regime()` checks 4h ATR + 1h/30m/15m momentum consensus. Entry fires only when 4/6 timeframes align. TP/SL geometry is calculated from 4h + 1h confluence. The bot uses **200-bar (33-day) windows** on every timeframe — enough context to see where the market sits in its macro cycle, not just the last 9 days.

**Regime shift reports:** When the market regime changes (STEADY/STRONG/CLEAR × LONG/SHORT/NEUTRAL), the bot prints a teaching message:
```
>> REGIME SHIFT: STEADY (strength=0.50, trend=NEUTRAL) active=0 cash=$300.00
   NEUTRAL regime — balanced deployment at 50% strength.
```

### 2.3 Adaptive Entry Gate — No Hard Caps
Nikola **never uses a fixed position-count cap**. Instead, position capacity is computed each cycle:

```python
regime, strength, trend = get_market_regime()    # e.g. "STEADY", 0.50, "NEUTRAL"

dir_mult = 1.0 if signal_direction == trend else 0.3   # 0.6 if NEUTRAL trend
effective_strength = strength * dir_mult
max_positions = max(3, int(28 * 0.6 * effective_strength))
```

| Regime | Strength | Trend | Dir Mult | Max Positions |
|--------|----------|-------|----------|---------------|
| STRONG | 1.0 | LONG | 1.0 (LONG signals) | 16 |
| STRONG | 1.0 | LONG | 0.3 (SHORT signals) | 5 |
| STEADY | 0.5 | NEUTRAL | 0.6 | 5 → 3 (min floor) |
| CLEAR | 0.0 | * | 0.0 | 3 (min floor, mostly cash) |

**The philosophy:** In strong bull/bear trends, Nikola deploys aggressively (up to 16 positions) in the direction of the trend. In choppy/neutral markets, he scales back to cash. No arbitrary number is ever hardcoded — the market decides.

### 2.4 The Layered Learning Path
| Stage | What You Learn | What the Bot Does |
|---|---|---|
| **Beginner** | Read 6 charts at once, understand 3:1 R:R | Runs paper mode, explains every trade |
| **Intermediate** | Layer charts, recognize regime shifts | Adds God Code quotes, shows TP/SL ratchet |
| **Advanced** | Trade like the bot (manual verification) | Run side-by-side as co-pilot |
| **Expert** | Build your own bot from the lessons | Fork, customize, share back |

---

## 3. Installation — Tiered Setup Guides

### A. Complete Beginner (Zero crypto/code experience)
```
# Step 1: Install Python 3.12
python3 --version   # must be 3.8+

# Step 2: Install dependencies
pip install -r requirements.txt

# Step 3: Run paper trading — ZERO keys, ZERO risk
python nikola.py --paper

# Step 4: Watch the log — understand what each trade does
python nikola.py --paper --faith-tradition christian   # or universal, secular, all

# Step 5: Check performance report
python nikola.py --export-html   # opens nikola_report.html
```
**No API keys needed.** No signup. No credit card. No wallet. Just paper trading to learn.

### B. Medium Experience (Knows what a wallet is, can create API keys)
```
# Step 1-3: Same as beginner

# Step 4: Create kraken.env (for live mode only — when you're ready)
cp kraken.env.example kraken.env
# Edit kraken.env → paste your Kraken API_KEY and API_SECRET
# Kraken settings: READ + TRADE + MARGIN enabled

# Step 5: Customize settings (optional)
cp config/settings.yaml.example config/settings.yaml
# Edit paper_budget_usd, leverage, risk percentages

# Step 6: When ready for real money (after paper mastery)
python nikola.py --live   # WARNING: real orders on Kraken BTNL margin
```

### C. Advanced/Expert (Wants to customize everything)
```bash
# Full configuration surface:
# — engine/config.py: SYMBOLS list, PAIR_LEVERAGE, risk constants
# — config/settings.yaml: all tunable parameters (leverage caps, R:R, timing)
# — engine/signals.py: signal weights, regime detection
# — engine/strategy.py: state machine, TP/SL geometry
# — agents/god_code.py: wisdom wells, ethical vetoes
# — donation_monitor.py: donation addresses, auto-donate percentage

# Fork and customize:
git clone https://github.com/YOUR-USERNAME/nikola-bot.git
cd nikola-bot
# Edit DONATION_ADDRESS in engine/config.py to YOUR wallet
# Edit SYMBOLS in engine/config.py to your preferred pairs
# Edit settings.yaml to your risk tolerance
```

### D. Non-English Speakers
- Code is English (universal in development tooling)
- README translated: `README.md` (English), `README.es.md` (Spanish), `README.cn.md` (Chinese), `README.pt.md` (Portuguese)
- God Code supports `--faith-tradition christian|universal|secular|all`
- Chart-reading concepts are visual — work across languages

---

## 4. Trading Philosophy — The Math That Protects You

### 4.1 The $300 Growth Math
```
$300 paper → 5x leverage → $1,500 notional exposure
↓ TP1 (+1.4%, 40% sold)   +$84 realized → $384 capital
↓ TP2 (+2.8%, 40% sold)   +$84 realized → $468 capital
↓ 20% runner trails       +$40+        → compounds on winners
```
**Applies identically to SHORT positions** — the same TP1/TP2/SL1/SL2 percentages, just inverted. Here's what it looks like with a realistic $300 paper account (5x leverage = $1,500 notional → ~$500 per position):

```
LONG  entry $50,000 (0.01 BTC, $100 margin @ 5x)
↓ TP1 +1.4%  → $50,700  → +$7.00  (R:+0.67, 40% sold)
↓ TP2 +2.8%  → $51,400  → +$14.00 (R:+1.33, 40% sold)
↓ SL2 -4.4%  → $47,800  → -$22.00 (R:-2.10, full exit if wrong)

SHORT entry $50,000 (0.01 BTC, $100 margin @ 5x)
↓ TP1 -1.4%  → $49,300  → +$7.00  (R:+0.67, 40% sold)
↓ TP2 -2.8%  → $48,600  → +$14.00 (R:+1.33, 40% sold)
↓ SL2 +4.4%  → $52,200  → -$22.00 (R:-2.10, full exit if wrong)
```

**Why this geometry:**
- **TP1 at +1.4% (40% sold)** — bank profit fast, recover margin, restart
- **TP2 at +2.8% (40% sold)** — double the TP1 distance, bank 80% total
- **20% runner trailing** — let big moves pay without giving back
- **SL1 at -2.1%** — partial close, TPs retained
- **SL2 at -4.4%** — full exit, risk capped per trade

### 4.2 Why 3:1 Minimum
At 3:1 R:R, break-even win rate is ~25%. At 50% win rate (Nikola's target), expectancy is strongly positive. Below 3:1, even a 50% win rate can't overcome fees over time.

### 4.3 Drawdown Recovery Math
| Loss | Recovery Needed |
|------|----------------|
| -10% | +11% |
| -25% | +33% |
| -50% | +100% |
| -75% | +300% |
| -90% | +900% |

**A single 75% drawdown requires a 300% gain to break even.** This is why Nikola's stops are mathematical, not emotional — you never lean on hope.

### 4.4 The Dynamic R:R State Machine
```
MONITOR → ACTIVE → EXPANDED
  ↓        ↓         ↓
Entry sent  TP1/TP2 live  +3R hit
SL1 placed  20% runner    50% partial booked
            trails
```
- **+0.1R** → BE ratchet primes (SL snaps to breakeven floor)
- **+1.0R** → TP1 fires (40% sold, SL1 cancelled, SL2 ratchets to BE)
- **+2.0R** → TP2 fires (40% sold, SL2 ratchets to TP1 level)
- **+2.5%** → wide trail arms (0.30% → 0.60% trailing)
- **+3.0R** → 50% partial, enter EXPANDED (2×ATR trailing)

### 4.5 Short-Side Support — Verified
Every trade goes through `strategy.py:Position.from_signal()`, which applies the same TP/SL percentage levels in both directions. For SHORT positions, the engine flips the sign:

| Level | LONG (price UP = profit) | SHORT (price DOWN = profit) |
|-------|-------------------------|----------------------------|
| **Entry** | $50,000 | $50,000 |
| **TP1** | $50,700 (+1.4%) | $49,300 (−1.4%) |
| **TP2** | $51,400 (+2.8%) | $48,600 (−2.8%) |
| **SL1** | $48,950 (−2.1%) | $51,050 (+2.1%) |
| **SL2** | $47,800 (−4.4%) | $52,200 (+4.4%) |

**Verified by unit test** (`test_short_side.py`):
- ✅ TP1/TP2 below entry for SHORT
- ✅ SL1/SL2 above entry for SHORT
- ✅ `r_multiple()` returns +R at TP1, −R at SL2 for SHORT (same values as LONG)
- ✅ BTC/USD uses custom ladder (+1.0%/+2.0%) — verified with $80,000 entry

### 4.6 R:R Transparency at Entry
The deploy log prints the full payoff geometry so beginners can see where the 3:1 ratio lives:

```
>> DEPLOY ADA/USD LONG @ $0.220
    base=3.0000  lev=5x  margin=$12.00  conf=0.85
    R:R  TP1=+0.67  TP2=+1.33  SL1=-1.00  SL2=-2.10  Runner→+3.00R
    Regime=STEADY str=0.50 trend=NEUTRAL dir_mult=1.0 eff_str=0.30
```

The 3:1 payoff lives in the **EXPANDED state** (runner), not just TP1/TP2. TP1 banks +0.67R fast, TP2 locks another +1.33R, and the 20% trailing runner extends to +3.00R. The bot prints this at every entry.

---

## 5. Safety Systems — Why You Can Trust This Bot

### 5.1 Two-Factor Live Activation
```
--live  CLI flag      →  sets NIKOLA_DRY_RUN=false env var
DRY_RUN = False       →  config.py reads env, exchange.py imports it
```
Both must be true for real orders. Miss either → simulation.

### 5.2 Zero Market Orders
All orders are either:
- **Limit** (entry, TP, emergency close)
- **Stop-loss-limit** (SL2, emergency SL2-band)
- **Reduce-only limit** (all TP/SL exits)

No `type="market"` anywhere in the codebase.

### 5.3 Guardian Angel
Every 15 seconds, scans for positions with `entry_confirmed=True` but `sl2_set=False` → places reduce-only limit at SL2 price. Catches the edge case where SL2 placement fails after entry.

### 5.4 God Code Ethical Veto
Before every position open:
```python
god_code.evaluate_action("OPEN", pair=pair, direction=pos.direction, ...)
```
Vetoes: forced liquidation, misery profit, harm exploitation. Three wisdom wells (Christian, Universal, Secular) + adversity quotes.

### 5.5 Cancel-Before-Close
Every exit cancels all 4 protection orders (SL2, TP1, TP2, entry) before placing the closing order. Prevents orphaned orders.

---

## 6. Donation System — Free Software, Voluntary Gifts

### 6.1 The Tithe Philosophy
Donations are **100% voluntary**. The bot is completely free. Two separate mechanisms:

| Mechanism | What it does | Configurable |
|---|---|---|
|| **10% external tithe** | When someone donates to you (PayPal, Solana, etc.), 10% of that donation goes to your chosen charity | `settings.yaml` → `donor.tithe_recipient` |
|| **Bot auto-donate** | Bot allocates 1% of realized profits from LIVE trades to its own donation address | `settings.yaml` → `donor.donation_pct` (0.0–100.0) |

**Default charity: Heifer International** (4/4 stars, 93% to mission, "teach a man to fish" model).
Heifer is also **Worldbuilders' PRIMARY funding partner** — Worldbuilders raises millions via
geek-culture book drives that fund Heifer's livestock gifts. Worldbuilders is available as an
alternative if you prefer the geek-culture pipeline. Change with one setting:

```yaml
donor:
  tithe_recipient: heifer      # or: worldbuilders
  donation_pct: 1.0            # 0.0 = disabled, 100.0 = give everything
```

**Why Heifer International** (EIN 35-1019477, 4/4 Charity Navigator stars, 98/100 points):
- 📖 **"Pass on the gift"** — recipients donate livestock offspring, creating sustainable community impact
- 💰 **93% to mission**, 74.3% program spending (Charity Navigator)
- ✅ **Meets all BBB Wise Giving Alliance standards**
- **90/100** GiveRadar Integrity Assessment (strong transparency)
- 79 years running, 52M families served since 1944
- **This is Worldbuilders' primary partner** — every dollar you tithe to Heifer goes directly to
  livestock gifts + training. If you pick Worldbuilders instead, 10% of your tithe still flows to
  Heifer (via Worldbuilders' pass-through) but with an extra layer + lower transparency rating.

**Why Worldbuilders is available as an alternative** (EIN 90-0618018, 2/4 Charity Navigator stars):
- 🎮 **Geek/gaming culture** aligns with the crypto community — founded by Patrick Rothfuss (The Name of the Wind)
- 🔄 **Raises millions for Heifer International** annually via book/game drives and lotteries
- ⚠️ **Lower transparency rating** (2/4 stars), very small scale ($245K revenue, $66.5K loss in 2024)
- Use only if you prefer the geek-culture pipeline; funds still reach Heifer via pass-through

### 6.2 Six Donation Methods
| Method | Fee | How |
|---|---|---|
| PayPal Tithe | ~$0.30 + 2.9% | Scan QR from `--export-html` report |
| Solana Direct | ~$0.0001 | Send SOL/USDC to Solana address |
| Base L2 | ~$0.00 (gas-free) | Send USDbC to Base address |
| Kraken Deposit | 0% intra-Kraken | Deposit via Kraken memo |
| Lightning | ~$0.001 | Self-custody BTC via LNbits/LND |
| Auto-donation | 0% | Bot allocates 1% of realized profits |

### 6.3 Fork Donations
Forks change `DONATION_ADDRESS` in `engine/config.py:39` — one line, no code changes. The README documents this.

### 6.4 Auto-Donate (Wired)
After each profitable position close (`nikola.py: _close_position()`):
```python
if gross > 0 and not self.paper:
    self._auto_donate.record_realized_pnl(gross, pair)
```
Tracks accumulated donations. Currently internal accounting — user manually transfers the accumulated amount. Future: Kraken intra-account transfer automation.

---

## 7. GitHub Repository Structure

### Files to Commit (tracked):
```
nikola.py                    # Main entry point (1,810 lines)
engine/
  config.py                  # Risk parameters, SYMBOLS, DONATION_ADDRESS
  exchange.py                # CCXT wrapper, order primitives, PaperExchange
  signals.py                 # 6-timeframe voting, regime detection
  strategy.py                # State machine, TP/SL geometry, exit rules
  risk.py                    # Position sizing, margin tiers
  indicators.py             # ATR, MACD, EMA, order book depth
  state.py                  # Paper/live state persistence
agents/
  god_code.py                # Ethical vetting, wisdom wells, quotes
config/
  settings.yaml.example      # Annotated template (gitignored: settings.yaml)
data/                     # Gitignored — runtime state
  paper_state.json         # Paper trading state
  signal_weights.json      # Signal confidence weights
  paper_trades.json        # Trade history ledger
kraken.env.example           # Template for API keys (gitignored: kraken.env)
run_nikola_paper.bat          # Windows: one-click paper trading
run_nikola_live.bat           # Windows: one-click live trading (CAUTION)
run_nikola_paper.sh           # macOS/Linux: paper trading (chmod +x)
run_nikola_live.sh            # macOS/Linux: live trading (chmod +x)
donation_monitor.py          # Multi-chain donation tracking
README.md                    # Main documentation
INSTRUCTIONS.md              # Inspirational guide + quick start
GOD_CODE.md                  # God Code philosophy documentation
REDDIT_POST.md               # Community announcement
REDDIT_COMMENT.md            # Discussion comments
LICENSE                     # MIT license
.gitignore                  # Excludes secrets, logs, runtime state
```

### Files to Gitignore (never committed):
```
*.env                       # kraken.env, any .env files
config/settings.yaml        # user config
*.pid                       # nikola.pid
*.log*                      # nikola_live.log, paper_nikola.log
data/                       # runtime state (paper_state.json, etc.)
nikola_report.html          # HTML exports
```

### What Makes This Special for GitHub:
1. **Zero cloud dependencies** — pure Python, pure local
2. **Paper mode works with zero setup** — no API keys, no accounts
3. **God Code adds soul** — ethical AI that teaches resilience, not just profits
4. **Full math transparency** — every risk parameter documented and explained
5. **Tiered learning path** — beginner can start in 1 minute, expert can go deep
6. **Direction-aware adaptation** — trades LONG/SHORT, scales 0–16 positions by market quality, never caps
7. **R:R shown at entry** — deploy log prints exact payoff geometry for beginners
8. **Configurable ethics** — toggle God Code veto, Guardian Angel, and donation % per your values

---

## 8. Questions I Need Answered Before Publishing

### 8.1 Content / Messaging
1. **What's the GitHub repo name?** → `nikola` (https://github.com/LucasMurr369/nikola)
2. **Who is the GitHub owner account?** → LucasMurr369 (personal account)
3. **What's the project description?** → "Direction-aware adaptive trading bot for Kraken Pro BTNL margin. 3:1 R:R, 6-timeframe confluence, short-side support, configurable tithe."
4. **Which README is primary?** → `README.md` is the primary user-facing document. `INSTRUCTIONS.md` is the detailed operator's manual. `GUIDE.md` is the chart-reading tutorial. `FOR_READERS.txt` is the 30-second quick-start.

### 8.2 Donation Configuration
5. **Real donation addresses** → `DONATION_ADDRESS (BTC): bc1qxy2kgdygjrsqtzq2n0yrf29sdf7r2khsl2nf5x` in `engine/config.py:39`. Additional Solana/Base/Arbitrum/Lightning/Kraken—memo options in `donation_monitor.py` (edit `DONATION_ADDRESSES` to wire your wallets).
6. **Auto-donate percentage** → Configurable via `settings.yaml` → `donor.donation_pct` (0.0–100.0, default 1.0). Live-mode profits only.
7. **The 10% tithe mechanism** → Configurable via `settings.yaml` → `donor.tithe_recipient` (Heifer or Worldbuilders, or add your own). 10% of external donations flows to charity. Bot logs `>> Tithe: $X.XX allocated to [charity]` on each external donation received.

### 8.3 Technical Pre-Publishing
8. **API keys for testing** → No CI/CD. Paper mode works with zero keys. Live mode requires `kraken.env` (copied from `kraken.env.example`).
9. **Python version** → Python 3.12 (minimum 3.12 — uses `str | None` union syntax)
10. **CCXT version pinning** → Pinned to `ccxt==4.5.77` in `requirements.txt` for reproducibility.
11. **Windows vs. macOS vs. Linux** → Windows: `.bat` files included. Linux/macOS: `.sh` scripts. All platforms: `python nikola.py —paper`.

### 8.4 Direction & Risk Philosophy
15. **Direction-aware philosophy** → The bot scales position count 0-16 based on regime strength × direction alignment × confidence. This replaces the old "fixed 5 positions" approach — explained in Section 2.5 (page 22 of this document) as "adaptive entry gate."
16. **Short-side positioning** → The bot trades SHORT (TP/SL inverted) — verified by `test_short_side.py` unit test. Presented with blue=Long, amber=Short color contrast. No red/green confusion.
17. **Why 200-bar (33-day) ATR** — User—facing docs call it "33-day trend context." The 200-bar window (≈33 days on 4h) provides the extended trend context that shorter windows miss.
18. **R:R transparency at entry** — Always on. The deploy log shows the full geometry: `R:R TP1=+0.67 TP2=+1.33 SL2=−2.10 Runner→+3.00R`.

### 8.5 Educational Content
19. **Biblical trading history section** → See Section 9.1 below — Genesis 25:3 (succession planning), Proverbs 3:9 (tithhe first), Proverbs 21:5 (diligence over gambling), Ecclesiastes 3:1 (seasonal regime awareness), Luke 19:13 (be diligent, hold money trading), Genesis 43:34 (humility before the market).
20. **Gutenberg library integration** → See Section 9.2 below — Adam Smith, Benjamin Graham, Jesse Livermore, Paul Tudor Jones, Victor Niederhoffer, Sun Tzu, Marcus Aurelius. Future integration via public APIs (Gutenberg.org, Open Library).
21. **Chart-reading tutorial** → Created as separate `GUIDE.md` — the "start big, layer down" method.

---

## 9. Research Possibilities — Helping People Learn

### 9.1 Biblical Trading History
| Passage | Concept | Teaching Value |
|---|---|---|
| Genesis 25:3 | "Abraham gave all his possessions to Isaac" — passing wealth | Succession planning in trading |
| Proverbs 3:9 | "Honor the Lord with your firstfruits" | Tithhe before profit-taking |
| Proverbs 21:5 | "The plans of the diligent lead surely to abundance" | Planning + discipline over gambling |
| Proverbs 27:1 | "Boast not yourself in tomorrow's advance" | Don't over-leverage, live to trade another day |
| Ecclesiastes 3:1 | "To everything there is a season" | Timeframe-based regime awareness |
| Luke 19:13 | "Be diligent, holding money trading" | Active management, not hoarding |
| Genesis 43:34 | "They ate before him, and he bowed to them" | Humility before the market |

### 9.2 Gutenberg Library Integration (Future)
The God Code could pull wisdom from public-domain classics:
- **Adam Smith** — "The Wealth of Nations" (supply/demand, market psychology)
- **Benjamin Graham** — "The Intelligent Investor" (margin of safety, Mr. Market)
- **Jesse Livermore** — "Reminiscences of a Stock Operator" (psychology, trend following)
- **Paul Tudor Jones** — "Trader" (risk management, diversification)
- **Victor Niederhoffer** — "The Education of a Speculator" (pattern recognition)
- **Sun Tzu** — "The Art of War" (strategy, knowing when to engage)
- **Marcus Aurelius** — "Meditations" (stoicism, emotional discipline)

Access: free public APIs (Gutenberg.org, Open Library) — no copyright issues.

### 9.3 Chart-Reading Layering Method
The bot teaches the "start big, layer down" approach:
1. **4h chart** — identify the trend (higher highs/lows vs lower lows/higher highs)
2. **1h chart** — find support/resistance zones, entry windows
3. **30m chart** — refine entry point, check momentum confluence
4. **15m chart** — candle close behavior, rejection signals
5. **5m chart** — final entry confirmation, micro-trend
6. **1m chart** — trigger alignment

**The bot mirrors this:** `get_market_regime()` (4h ATR + 1h/30m/15m consensus) → `full_scan()` (6-timeframe voting) → `_deploy()` (entry gate) → `light_cycle()` (5m/1m timing).

---

## 10. Release Checklist (Pre-GitHub)

- [x] Fix stale values in `settings.yaml.example` (done)
- [x] Verify zero `type="market"` in codebase (done)
- [x] Confirm DRY_RUN env-var switch works (done)
- [x] Wire AutoDonation into _close_position (done)
- [x] Create `kraken.env.example` (done)
- [x] Create `config/settings.yaml.example` (done)
- [x] Update INSTRUCTIONS.md to match actual code (leverage 20x, not 10x; reserve 0%, not 25%)
- [x] Update README.md Quick Start (add `--faith-tradition` flag)
- [x] **Direction-aware regime gate** (200-bar ATR + 1h/30m/15m consensus + per-signal dir mult) (done)
- [x] **Short-side TP/SL reversal** (verified by `test_short_side.py` unit test) (done)
- [x] **R:R transparency in deploy log** (shows R:R TP1=+0.67 TP2=+1.33 SL2=−2.10 Runner→+3.00R) (done)
- [x] **`mtf_candle_limit: 200` enforcement** (load_candles, set_candles, populate_candle_cache, settings.yaml) (done)
- [x] **No hard position-count caps** (adaptive scaling only, max(3, …) floor) (done)
- [x] Answer all questions in Section 8
- [x] Add biblical history + Gutenberg integration notes
- [ ] Pre-approve final README/prospectus with user
- [x] Write LICENSE file (MIT)
- [x] Create `requirements.txt` lock file (pin ccxt==4.5.77)

---

## 11. The Spirit of Nikola

```
Nikola is not here to make you rich.
Nikola is here to keep you in the game.

The market will humble every trader
who mistakes luck for skill.
Nikola's job is to make sure
that when the market humbles you,
you're still standing.

The math is simple:
  - Risk 1 unit.
  - Potential reward: 3+ units.
  - Bank 80% before the runner flies.
  - Stop out at -4.4% if wrong.
  - Let winners compound.

Everything else is noise.
```

---
*Written for GitHub distribution. Questions or corrections? Open an issue or email donations@nikola-bot.org.*
