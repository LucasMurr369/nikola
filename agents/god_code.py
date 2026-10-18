"""
Nikola — God Code Agent.

Ported from the already-built GodCodeAgent in build_hermes_v2.py (lines 1069-1278).
The God Code is an ethical guardrail that cycles public-domain wisdom and emits a
**quote** for each trading event — turning the ledger into a video-game experience
where the trader levels up while the God Code speaks.

Faith-tradition support — "include all God did":
  - ``christian``  : JESUS-centered encouragement (perseverance, trust, peace).
  - ``universal``  : pre-Nicene wisdom and timeless thinkers (Egyptian,
                     Zoroastrian, Taoist, Hindu, Buddhist, Greco-Roman, Jewish,
                     plus Tesla, Einstein, and the Stoics).
  - ``secular``    : trading-resilience virtue maxims (humility, patience, risk).
  - ``all``        : draws from every well (default).

Users restrict the well via the ``--faith-tradition`` CLI flag. All source texts
are public domain or widely-attributed maxims; nothing proprietary.
"""
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Wisdom wells — public domain / widely-attributed
# ---------------------------------------------------------------------------
TEXTS: List[Dict] = [
    # ---- Christian (JESUS-centered) ----
    {
        "tradition": "christian",
        "title": "Holy Bible — encouragement in Christ",
        "passages": [
            "The Lord is my shepherd; I shall not want.",
            "I can do all things through Christ who strengthens me.",
            "Do not be anxious about anything, but in all things by prayer let your requests be made known to God.",
            "The Lord is close to the brokenhearted and saves the crushed in spirit.",
            "Be strong and courageous. Do not fear or be in dread, for the Lord your God goes with you.",
            "Trust in the Lord with all your heart, and do not lean on your own understanding.",
            "Cast all your anxiety on him, because he cares for you.",
            "The peace of God, which surpasses all understanding, will guard your hearts and minds.",
            "Let us not grow weary of doing good, for in due season we will reap, if we do not give up.",
            "The steadfast love of the Lord never ceases; his mercies never fail.",
        ],
    },
    # ---- Universal: pre-Nicene wisdom from all old religions ----
    {
        "tradition": "universal",
        "title": "Egyptian Book of the Dead (pre-Nicene)",
        "passages": [
            "I have not caused pain.",
            "I have not caused hunger.",
            "I have not polluted the water.",
            "I have not stolen.",
            "I have not caused suffering.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Avesta — Gathas of Zarathustra (pre-Nicene)",
        "passages": [
            "Let the wise choose truth.",
            "Do not give pain to any living being.",
            "Good thoughts, good words, good deeds.",
            "The earth is a garden; do not poison it.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Tao Te Ching — Lao Tzu (pre-Nicene era)",
        "passages": [
            "The Tao does not compete.",
            "Water benefits all things without contention.",
            "He who knows others is wise; he who knows himself is enlightened.",
            "The more laws and orders are made prominent, the more thieves and robbers there will be.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Early Upanishadic fragments (pre-Nicene)",
        "passages": [
            "From the unreal lead me to the real.",
            "The self is the same in all beings.",
            "He who sees all beings in the self, and the self in all beings, knows no fear.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Dhammapada — early Buddhist discourses (pre-Nicene)",
        "passages": [
            "Hatred does not cease by hatred; it ceases by love.",
            "All that we are is the result of what we have thought.",
            "Better than a thousand hollow words is one word that brings peace.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Marcus Aurelius — Meditations (early Roman, pre-Nicene)",
        "passages": [
            "Waste no more time arguing what a good man should be.",
            "Be tolerant with others and strict with yourself.",
            "The happiness of your life depends upon the quality of your thoughts.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Socrates / Plato fragments (pre-Nicene)",
        "passages": [
            "The unexamined life is not worth living.",
            "Do not do to others what would anger you if done to you.",
            "The soul is more harmed by injustice than the body by punishment.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Hillel the Elder — Pirkei Avot (pre-Nicene Jewish tradition)",
        "passages": [
            "If I am not for myself, who is for me?",
            "If I am only for myself, what am I?",
            "The rest is commentary — go and learn.",
        ],
    },
    # ---- Universal: timeless scientific & philosophical thinkers ----
    {
        "tradition": "universal",
        "title": "Nikola Tesla — on energy & frequency",
        "passages": [
            "If you want to find the secrets of the universe, think in terms of energy, frequency and vibration.",
            "If you understood the significance of the numbers 3, 6, and 9, you would have the key to the universe.",
            "Each seed of the thing has the power to multiply itself.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Albert Einstein — on curiosity & the cosmos",
        "passages": [
            "Imagination is more important than knowledge.",
            "The important thing is not to stop questioning. Curiosity has its own reason for existing.",
            "Science without religion is lame, religion without science is blind.",
            "The universe does not exist only for us, but for all of us.",
        ],
    },
    {
        "tradition": "universal",
        "title": "Stoic maxims — Epictetus, Seneca, Marcus Aurelius",
        "passages": [
            "It is not things themselves that disturb us, but our opinions about them.",
            "We suffer not from events, but from our judgments about them.",
            "The pain is not from the thing itself, but from our opinion about it.",
            "Difficulties are things that show what a man is.",
        ],
    },
    # ---- Secular virtue: trading-resilience maxims ----
    {
        "tradition": "secular",
        "title": "Trading-resilience virtue",
        "passages": [
            "The obstacle on the path becomes the path.",
            "Slow is smooth. Smooth is fast.",
            "Be fearful when others are greedy; be greedy when others are fearful.",
            "The investor's worst enemy is himself.",
            "Patience: the calm between signal and execution.",
            "In the markets, humility is paid in full.",
            "Capital preserved is profit earned.",
            "Risk comes from not knowing what you are doing.",
            "The trend is your friend; do not fight the tape.",
        ],
    },
]

# Adversity-specific wisdom — drawn at SL hits / drawdown moments, when a
# trader most needs steadiness. Same three wells so the user's tradition
# filter applies here too.
ADVERSITY: Dict[str, List[str]] = {
    "christian": [
        "The Lord is close to the brokenhearted and saves the crushed in spirit.",
        "Cast all your anxiety on him, because he cares for you.",
        "Be strong and courageous. Do not fear or be in dread.",
        "Let us not grow weary of doing good, for in due season we will reap.",
    ],
    "universal": [
        "Hatred does not cease by hatred; it ceases by love.",
        "The unexamined life is not worth living.",
        "Waste no more time arguing what a good man should be.",
        "Be tolerant with others and strict with yourself.",
        "It is not things themselves that disturb us, but our opinions about them.",
        "The pain is not from the thing itself, but from our opinion about it.",
        "Difficulties are things that show what a man is.",
    ],
    "secular": [
        "Be fearful when others are greedy; be greedy when others are fearful.",
        "The investor's worst enemy is himself.",
        "Capital preserved is profit earned.",
        "Slow is smooth. Smooth is fast.",
        "In the markets, humility is paid in full.",
    ],
}


class GodCodeAgent:
    """Ethical guardrail + quote dispenser for Nikola.

    The God Code:
    1. Cycles a passage every ``cycle_sec`` (default 300s) — a meditative quote.
    2. Emits a **trade quote** when a position opens/closes (gamification flavor).
    3. Emits a **level-up quote** when the trader gains a level or achievement.
    4. Emits an **adversity quote** at SL hits / drawdowns (steadiness under loss).
    5. Evaluates trade intent against the ethical checklist — vetoes profit
       from harm (forced liquidations, misery arbitrage, exploitation).

    ``faith_tradition`` scopes which wisdom well is drawn from:
    ``all`` (default), ``christian``, ``universal``, or ``secular``.
    """

    # Ethical blocklist — profit from these is blocked
    HARM_KINDS = {"forced_liquidation", "misery_profit", "harm_exploitation"}
    TRADITIONS = ("all", "christian", "universal", "secular")

    def __init__(self, cycle_sec: int = 300, enabled: bool = True,
                 faith_tradition: str = "all"):
        self.enabled = enabled
        self.cycle_sec = cycle_sec
        if faith_tradition not in self.TRADITIONS:
            faith_tradition = "all"
        self.faith_tradition = faith_tradition
        self._index = 0
        self._current_passage: str = ""
        self._current_title: str = ""
        self._current_tradition: str = ""
        self._veto_active: bool = False
        self._veto_reason: str = ""
        self._gray_flags: List[Dict] = []
        self._last_cycle: float = 0.0
        self._pool: List[Dict] = self._build_pool()
        self._cycle_passage()

    # ---- well selection ----
    def _build_pool(self) -> List[Dict]:
        """Tradition-filtered passage pool (round-robin cycle over this)."""
        if self.faith_tradition == "all":
            return TEXTS
        return [t for t in TEXTS if t["tradition"] == self.faith_tradition]

    def _adversity_pool(self) -> List[str]:
        """Tradition-filtered adversity well."""
        if self.faith_tradition == "all":
            return [q for qs in ADVERSITY.values() for q in qs]
        return ADVERSITY.get(self.faith_tradition, [])

    # ---- passage cycling ----
    def _cycle_passage(self) -> None:
        """Advance to the next passage (round-robin through the well)."""
        pool = self._pool or TEXTS
        self._index = (self._index + 1) % len(pool)
        text = pool[self._index]
        self._current_tradition = text["tradition"]
        self._current_title = text["title"]
        self._current_passage = random.choice(text["passages"])
        self._last_cycle = time.time()

    def tick(self) -> Optional[str]:
        """Called each daemon cycle — cycles passage if interval elapsed."""
        if not self.enabled:
            return None
        if time.time() - self._last_cycle >= self.cycle_sec:
            self._cycle_passage()
            return self._current_passage
        return None

    # ---- quote delivery (gamified display) ----
    @property
    def current_quote(self) -> Tuple[str, str]:
        """Return (passage, source_title)."""
        return self._current_passage, self._current_title

    @property
    def current_tradition(self) -> str:
        """Return the tradition tag of the current passage."""
        return self._current_tradition

    def quote_for_trade(self, pair: str, direction: str, entry_r: float = 0.0) -> str:
        """A trade-specific quote — ties the God Code to the action."""
        return self._current_passage

    def quote_for_adversity(self, pair: str = "", entry_r: float = 0.0) -> str:
        """Steadiness quote — emitted at SL hits / drawdowns.

        Filters the adversity well by the configured tradition; falls back to
        the current passage if the well is somehow empty.
        """
        pool = self._adversity_pool()
        return random.choice(pool) if pool else self._current_passage

    def quote_for_levelup(self, level: int, xp: int) -> str:
        """A level-up quote."""
        wisdom = [
            "The unexamined life is not worth living.",
            "Good thoughts, good words, good deeds.",
            "Better than a thousand hollow words is one word that brings peace.",
            "The more laws and orders are made prominent, the more thieves and robbers there will be.",
            "From the unreal lead me to the real.",
            "I can do all things through Christ who strengthens me.",
            "The steadfast love of the Lord never ceases; his mercies never fail.",
            "In the markets, humility is paid in full.",
            "The happiness of your life depends upon the quality of your thoughts.",
        ]
        return random.choice(wisdom)

    def quote_for_cycle(self) -> str:
        """Return the current passage (for the light-check header)."""
        return self._current_passage

    # ---- ethical evaluation ----
    def evaluate_action(self, action: str, profit_usd: float = 0.0,
                        harm_kind: str = "") -> Dict:
        """Evaluate a trade action for ethical compliance.

        Returns {action: allow|block|escalate, reason, passage}.
        """
        if not self.enabled:
            return {"action": "allow", "reason": "GodCode disabled",
                    "passage": self._current_passage}

        decision = {"agent": "god_code", "ts": time.time(),
                    "harm_kind": harm_kind, "profit_usd": profit_usd,
                    "passage": self._current_passage}

        if not harm_kind:
            decision["action"] = "allow"
            decision["reason"] = "no harm signal"
            return decision

        if harm_kind in self.HARM_KINDS:
            decision["action"] = "block"
            decision["reason"] = (f"profit from {harm_kind} blocked — "
                                  f"'{self._current_passage}'")
            self._veto_active = True
            self._veto_reason = decision["reason"]
            decision["veto"] = True
            return decision

        # Gray area -> escalate (console log in Nikola's single-process model)
        decision["action"] = "escalate"
        decision["reason"] = (f"gray-area ({harm_kind}); profit ${profit_usd:.2f} — "
                              f"awaiting judgment. '{self._current_passage}'")
        self._gray_flags.append(decision)
        return decision

    def get_veto(self) -> Optional[Dict]:
        if self._veto_active:
            return {"active": True, "reason": self._veto_reason}
        return None

    def clear_veto(self) -> None:
        self._veto_active = False
        self._veto_reason = ""

    def get_gray_flags(self, max_age_sec: float = 300.0) -> List[Dict]:
        now = time.time()
        return [g for g in self._gray_flags if now - g.get("ts", now) < max_age_sec]

    # ---- display helpers ----
    def format_quote(self) -> str:
        """ASCII-formatted quote for the CLI header."""
        q = self._current_passage
        src = self._current_title
        trd = self._current_tradition or "universal"
        return (
            f"  ┌─ God Code ───────────────────────────────────────────────────\n"
            f"  │  \"{q}\"\n"
            f"  │ — {src}\n"
            f"  │   [{trd} | well={self.faith_tradition}]\n"
            f"  ╰──────────────────────────────────────────────────────────────"
        )
