"""
Nikola engine state — gamified paper ledger.

Manages the $300 clean-slate paper state (Nikola.md) plus the **video-game
leveling** layer the user asked for: the trader is a character who earns XP per
trade, levels up on milestones, builds a win streak, and unlocks achievements.

The state is persisted to ``data/paper_state.json`` so it survives restarts.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from .config import PAPER_BUDGET_USD, SYMBOLS


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Gamification — trading-as-RPG
# ---------------------------------------------------------------------------
@dataclass
class Gamification:
    """Video-game leveling: XP per trade, levels, streak, achievements."""
    xp: int = 0
    level: int = 1
    streak: int = 0          # consecutive wins
    longest_streak: int = 0
    trades_total: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    peak_xp: int = 0
    achievements: List[str] = field(default_factory=list)

    # XP rewards
    XP_PER_TRADE = 10
    XP_PER_WIN = 25
    XP_PER_LOSS = 2      # small consolation for a lesson learned
    XP_PER_R = 5         # bonus xp per R-multiple of profit

    # Level thresholds: cumulative XP needed per level
    # 1→2: 100, 2→3: 200, ..., 7→8: 1100 | 8→9: 1500 | 9→10: 2500
    LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 1500, 2100, 2900, 4000, 6000, 10000]

    @property
    def xp_to_next(self) -> int:
        idx = min(self.level, len(self.LEVEL_THRESHOLDS) - 1)
        if idx >= len(self.LEVEL_THRESHOLDS) - 1:
            return 0  # max level
        return self.LEVEL_THRESHOLDS[idx] - self.xp

    @property
    def xp_in_level(self) -> int:
        """XP earned within the current level (for progress bar)."""
        idx = min(self.level, len(self.LEVEL_THRESHOLDS) - 1)
        prev = self.LEVEL_THRESHOLDS[idx - 1] if idx > 0 else 0
        return self.xp - prev

    def on_trade_close(self, won: bool, r_multiple: float) -> List[str]:
        """Process a closed trade, return list of milestone messages."""
        msgs: List[str] = []
        self.trades_total += 1
        if won:
            self.trades_won += 1
            self.streak += 1
            self.longest_streak = max(self.longest_streak, self.streak)
            self.xp += self.XP_PER_TRADE + self.XP_PER_WIN
        else:
            self.trades_lost += 1
            self.streak = 0
            self.xp += self.XP_PER_TRADE + self.XP_PER_LOSS
        # bonus XP for R-multiple (capped)
        r_bonus = int(min(r_multiple, 10) * self.XP_PER_R) if r_multiple > 0 else 0
        self.xp += r_bonus
        self.peak_xp = max(self.peak_xp, self.xp)

        if msg := self._check_levelup():
            msgs.append(msg)
        if msg := self._check_achievement():
            msgs.append(msg)
        return msgs

    def _check_levelup(self) -> Optional[str]:
        prev_lvl = self.level
        new_lvl = 1
        for i, thresh in enumerate(self.LEVEL_THRESHOLDS):
            if self.xp >= thresh:
                new_lvl = i
        new_lvl = min(new_lvl, len(self.LEVEL_THRESHOLDS) - 1)
        if new_lvl > prev_lvl:
            self.level = new_lvl
            return f"LEVEL UP: {prev_lvl} → {new_lvl}  (+{new_lvl * 100} XP milestone)"
        return None

    def _check_achievement(self) -> Optional[str]:
        checks = [
            ("Rookie", self.trades_total >= 1 and "Rookie" not in self.achievements),
            ("Sniper", self.trades_won >= 5 and self.trades_lost == 0
             and "Sniper" not in self.achievements),
            ("On Fire", self.streak >= 3 and "On Fire" not in self.achievements),
            ("Dragon", self.trades_total >= 20 and "Dragon" not in self.achievements),
            ("God Code", self.trades_total >= 50 and "God Code" not in self.achievements),
            ("10-Streak", self.streak >= 10 and "10-Streak" not in self.achievements),
        ]
        for name, unlocked in checks:
            if unlocked:
                self.achievements.append(name)
                return f"ACHIEVEMENT UNLOCKED: {name}"
        return None

    def progress_bar(self, width: int = 20) -> str:
        """ASCII progress bar for current-level XP."""
        if self.level >= len(self.LEVEL_THRESHOLDS) - 1:
            return f"[{'=' * width}] MAX LEVEL"
        xp_in = self.xp_in_level
        xp_needed = self.XP_IN_LEVEL if hasattr(self, 'XP_IN_LEVEL') else \
            (self.LEVEL_THRESHOLDS[self.level] -
             (self.LEVEL_THRESHOLDS[self.level - 1] if self.level > 0 else 0))
        if xp_needed <= 0:
            return f"[{'=' * width}] MAX"
        filled = int(xp_in / xp_needed * width) if xp_needed > 0 else width
        return f"[{'=' * filled}{'·' * (width - filled)}] {xp_in}/{xp_needed}"


# ---------------------------------------------------------------------------
# PaperState — the ledger ($300 clean slate from Nikola.md)
# ---------------------------------------------------------------------------
@dataclass
class PaperPosition:
    pair: str
    direction: str
    entry_price: float
    base_amount: float
    leverage: int
    sl1_price: float
    sl2_price: float
    tp_ladder: List[Dict]
    entry_time: str
    tp1_price: float = 0.0     # take-profit level 1 (for --export-html geometry)
    tp2_price: float = 0.0     # take-profit level 2
    r_multiple: float = 0.0    # current R-multiple (profit / risk), for reports
    state: str = "active"      # active | closed
    exit_price: float = 0.0
    exit_time: str = ""
    current_price: float = 0.0   # live/mark-to-market price
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    signal_type: str = "UNKNOWN"
    confidence: float = 0.0


class PaperState:
    """Gamified paper ledger — $300 clean slate, cycle 0 (Nikola.md)."""

    def __init__(self, cash: float = PAPER_BUDGET_USD):
        self.cash_usd = cash
        self.initial_cash = cash
        self.initial_cash_usd = cash
        self.positions: List[PaperPosition] = []
        self.trade_history: List[Dict] = []
        self.scoring: Dict[str, Any] = {}
        self.activity_log: List[Dict] = []
        self.cycle = 0
        self.mode = "autonomous_paper"
        self.started_at = now_iso()
        self.gamification = Gamification()
        self.foreign_pairs: set = set()  # never touch user-managed pairs (ETH/SOL/XBT)
        self.last_snapshot_day: str = ""       # daily snapshot day tracker
        self.equity_snapshots: List[Dict] = []  # once-per-day equity records
        self.paper_trade_ledger: List[Dict] = []  # leg-level trade audit ledger

    # -- persistence --
    def save(self, path) -> None:
        data = {
            "cash_usd": self.cash_usd,
            "initial_cash_usd": self.initial_cash,
            # Persist OPEN positions so --export-html can render mid-trade
            # floating reports and paper/live sessions resume cleanly.
            "active_positions": [asdict(p) for p in self.positions
                                 if p.state != "closed"],
            "trade_history": self.trade_history,
            "scoring": self.scoring,
            "activity_log": self.activity_log,
            "cycle": self.cycle,
            "mode": self.mode,
            "started_at": self.started_at,
            "gamification": self.gamification.__dict__,
            "foreign_pairs": list(self.foreign_pairs),
            "last_snapshot_day": self.last_snapshot_day,
            "equity_snapshots": self.equity_snapshots,
            "paper_trade_ledger": self.paper_trade_ledger,
        }
        tmp = path.with_suffix(".json.tmp")
        for _attempt in range(10):
            try:
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2, default=str)
                os.replace(tmp, path)
                break
            except (PermissionError, FileNotFoundError, OSError):
                time.sleep(0.3)

    @classmethod
    def load(cls, path) -> "PaperState":
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                st = cls(cash=data.get("cash_usd", PAPER_BUDGET_USD))
                st.initial_cash = data.get("initial_cash_usd", st.initial_cash)
                st.cycle = data.get("cycle", 0)
                st.mode = data.get("mode", "autonomous_paper")
                st.started_at = data.get("started_at", now_iso())
                st.trade_history = data.get("trade_history", [])
                # Restore open positions (persisted for mid-trade reporting +
                # clean paper/live resume). Robust to missing/extra fields.
                _pf = {f.name for f in fields(PaperPosition)}
                st.positions = [
                    PaperPosition(**{k: v for k, v in _p.items() if k in _pf})
                    for _p in data.get("active_positions", [])
                ]
                st.scoring = data.get("scoring", {})
                st.activity_log = data.get("activity_log", [])
                st.foreign_pairs = set(data.get("foreign_pairs", []))
                st.last_snapshot_day = data.get("last_snapshot_day", "")
                st.equity_snapshots = data.get("equity_snapshots", [])
                st.paper_trade_ledger = data.get("paper_trade_ledger", [])
                g = data.get("gamification", {})
                if g:
                    st.gamification = Gamification(**g)
                return st
            except Exception:
                pass
        return cls()

    # -- operations --
    def open_position(self, pair: str, direction: str, entry_price: float,
                      base_amount: float, leverage: int,
                      sl1_price: float, sl2_price: float,
                      tp_ladder: List[Dict],
                      signal_type: str = "UNKNOWN", confidence: float = 0.0) -> PaperPosition:
        margin = (entry_price * base_amount) / leverage
        self.cash_usd -= margin
        pos = PaperPosition(
            pair=pair, direction=direction, entry_price=entry_price,
            base_amount=base_amount, leverage=leverage,
            sl1_price=sl1_price, sl2_price=sl2_price,
            tp_ladder=tp_ladder, entry_time=now_iso(),
            signal_type=signal_type, confidence=confidence,
        )
        self.positions.append(pos)
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                  "event": f"OPEN {pair} {direction} @ {entry_price:.5f}"})
        return pos

    def close_position(self, pos: PaperPosition, exit_price: float, reason: str) -> float:
        pos.state = "closed"
        pos.exit_price = exit_price
        pos.exit_time = now_iso()
        if pos.direction == "LONG":
            pos.pnl_usd = (exit_price - pos.entry_price) * pos.base_amount
        else:
            pos.pnl_usd = (pos.entry_price - exit_price) * pos.base_amount
        pos.pnl_pct = (pos.pnl_usd / (pos.entry_price * pos.base_amount)) * 100 if pos.entry_price else 0
        # round-trip fee
        pos.pnl_usd *= (1 - 0.0018)
        self.cash_usd += exit_price * pos.base_amount + pos.pnl_usd
        self.trade_history.append({
            "pair": pos.pair, "direction": pos.direction,
            "entry_price": pos.entry_price, "exit_price": exit_price,
            "base_amount": pos.base_amount, "pnl_usd": round(pos.pnl_usd, 2),
            "pnl_pct": round(pos.pnl_pct, 2), "reason": reason,
            "signal_type": pos.signal_type, "confidence": pos.confidence,
        })
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                  "event": f"CLOSE {pos.pair} {reason} PnL=${pos.pnl_usd:.2f}"})

        # Gamification: level up, streak, achievements
        won = pos.pnl_usd > 0
        msgs = self.gamification.on_trade_close(won, pos.pnl_pct / 100 * 10)  # rough R
        for m in msgs:
            self.activity_log.append({"cycle": self.cycle, "time": now_iso(), "event": m})
        return pos.pnl_usd

    def active_positions(self) -> List[PaperPosition]:
        # "active" is the live open state (close_position sets "closed").
        return [p for p in self.positions if p.state != "closed"]

    def equity(self) -> float:
        """Cash + mark-to-market value of open positions."""
        mtm = 0.0
        for p in self.active_positions():
            cur = p.current_price if p.current_price > 0 else p.entry_price
            if p.direction == "LONG":
                mtm += cur * p.base_amount
            else:
                mtm += (2 * p.entry_price - cur) * p.base_amount
        return self.cash_usd + mtm

    def summary(self) -> Dict[str, Any]:
        active = self.active_positions()
        total_pnl = sum(p.pnl_usd for p in self.positions if p.state == "closed")
        return {
            "cash_usd": round(self.cash_usd, 2),
            "equity": round(self.equity(), 2),
            "active_positions": len(active),
            "total_trades": len(self.trade_history),
            "total_pnl": round(total_pnl, 2),
            "cycle": self.cycle,
            "gamification": {
                "level": self.gamification.level,
                "xp": self.gamification.xp,
                "streak": self.gamification.streak,
                "achievements": self.gamification.achievements,
            },
        }

    # -- paper trade ledger (leg-level audit, ports live bot paper_trades.json) --
    def open_paper_trade(self, pair: str, direction: str, entry_price: float,
                         base_amount: float, leverage: int,
                         signal_type: str = "UNKNOWN", confidence: float = 0.0,
                         margin_cost: float = 0.0) -> str:
        """Create a trade record in the paper_trades.json ledger."""
        trade_id = f"pt_{len(self.paper_trade_ledger) + 1:04d}"
        trade = {
            "trade_id": trade_id, "pair": pair, "direction": direction,
            "entry_price": round(entry_price, 5), "base_amount": round(base_amount, 8),
            "leverage": leverage, "margin_cost": round(margin_cost, 4),
            "signal_type": signal_type, "confidence": round(confidence, 4),
            "entry_time": now_iso(), "status": "open",
            "exit_price": 0.0, "exit_time": "", "pnl_usd": 0.0, "pnl_pct": 0.0,
            "hold_hours": 0.0, "close_reason": "", "legs": [],
        }
        self.paper_trade_ledger.append(trade)
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                   "event": f"PT_OPEN {trade_id} {pair} {direction}"})
        return trade_id

    def record_paper_leg(self, trade_id: str, exit_price: float, amount: float,
                         pnl_usd: float, pnl_pct: float, reason: str) -> None:
        """Record a partial leg realization (cascade, SL1 partial, 50% exit)."""
        trade = next((t for t in self.paper_trade_ledger if t["trade_id"] == trade_id), None)
        if not trade:
            return
        leg_id = f"{trade_id}_leg{len(trade['legs']) + 1}"
        leg = {
            "leg_id": leg_id, "parent_id": trade_id,
            "pair": trade["pair"], "direction": trade["direction"],
            "exit_price": round(exit_price, 5), "amount": round(amount, 8),
            "pnl_usd": round(pnl_usd, 4), "pnl_pct": round(pnl_pct, 2),
            "reason": reason, "exit_time": now_iso(),
        }
        trade["legs"].append(leg)
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                   "event": f"PT_LEG {trade_id}→{leg_id} {reason} "
                                           f"PnL=${pnl_usd:.4f}"})

    def close_paper_trade(self, trade_id: str, exit_price: float, reason: str) -> float:
        """Close a paper trade record. Returns realized PnL (with round-trip fee)."""
        trade = next((t for t in self.paper_trade_ledger if t["trade_id"] == trade_id), None)
        if not trade:
            return 0.0
        entry_time = datetime.fromisoformat(trade["entry_time"].replace("Z", "+00:00"))
        hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        if trade["direction"] == "LONG":
            pnl = (exit_price - trade["entry_price"]) * trade["base_amount"]
        else:
            pnl = (trade["entry_price"] - exit_price) * trade["base_amount"]
        pnl *= (1 - 0.0018)  # round-trip fee (2 × 0.09%)
        trade["status"] = "closed"
        trade["exit_price"] = round(exit_price, 5)
        trade["exit_time"] = now_iso()
        trade["pnl_usd"] = round(pnl, 4)
        trade["pnl_pct"] = round((pnl / (trade["entry_price"] * trade["base_amount"])) * 100, 2) \
            if trade["entry_price"] and trade["base_amount"] else 0.0
        trade["hold_hours"] = round(hold_hours, 2)
        trade["close_reason"] = reason
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                   "event": f"PT_CLOSE {trade_id} {reason} "
                                           f"PnL=${pnl:.4f} hold={hold_hours:.1f}h"})
        return pnl

    def realized_pnl(self) -> float:
        """Sum realized PnL from closed trades + all partial legs."""
        total = sum(t.get("pnl_usd", 0.0) for t in self.paper_trade_ledger
                    if t.get("status") == "closed")
        total += sum(l.get("pnl_usd", 0.0) for t in self.paper_trade_ledger
                     for l in t.get("legs", []))
        return total

    def daily_snapshot(self, equity: float, realized_pnl: float,
                       active_count: int, scale: float) -> None:
        """Record a once-per-day equity snapshot (live bot lines 1182-1191)."""
        today = now_iso()[:10]
        self.last_snapshot_day = today
        snapshot = {
            "date": today, "time": now_iso(),
            "equity": round(equity, 2), "realized_pnl": round(realized_pnl, 2),
            "active_positions": active_count, "equity_scale": round(scale, 3),
        }
        self.equity_snapshots.append(snapshot)
        self.activity_log.append({"cycle": self.cycle, "time": now_iso(),
                                   "event": f"DAILY SNAPSHOT equity=${equity:.2f} "
                                           f"realized=${realized_pnl:+.2f} "
                                           f"open={active_count} scale={scale:.3f}x"})
