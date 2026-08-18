"""Calibration arcade: a weekly regime-change forecasting game scored by Brier.

Gamify learning and calibration ONLY (CLAUDE.md rule 13): no rewards for boldness, frequency or
size; no urgency, no money, no trading language. ANTI-ANCHORING is enforced here, on the Python
side: the model's change_risk_5d for a call is stored when the call is locked and is never part
of any pre-lock payload. Storage is sqlite at data/arcade.db — on free-tier hosting this file is
reset on redeploy (the v3 Postgres migration makes it durable). No accounts, no email: nickname only.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from fxradar import config

DB_PATH = config.DATA_DIR / "arcade.db"
STORMS_PATH = config.DATA_DIR / "storms.yaml"
HORIZON = 5  # trading days
BANNER = "a calibration game: forecasting practice, not trading."
_PROFANITY = {"fuck", "shit", "cunt", "bitch", "asshole", "dick", "nigger", "faggot"}

# ---- ranks: driven ONLY by resolved calls and rolling Brier — never by boldness ---------------
RANKS = [  # (min resolved calls, max rolling Brier, name)
    (0, 1.0, "observer"),
    (5, 0.30, "forecaster"),
    (15, 0.25, "storm chaser"),
    (30, 0.20, "regime master"),
]

# ---- badges: one table, one rule each ------------------------------------------------------
BADGES = {
    "methodology reader": "opened the Methodology page",
    "first resolved call": "at least one call resolved",
    "well calibrated": "Brier < 0.20 over 10+ resolved calls",
    "storm survivor": "visited during a live crisis regime",
    "beat the model": "lower season Brier than the model over 10+ resolved calls",
}


def brier(p: float, y: int) -> float:
    """Brier score of one probability against a 0/1 outcome (0 = perfect, 1 = worst)."""
    return float((p - y) ** 2)


def clean_nickname(nick: str) -> str:
    nick = re.sub(r"[^A-Za-z0-9 _-]", "", nick or "").strip()[:24]
    if not nick or any(w in nick.lower() for w in _PROFANITY):
        raise ValueError("please choose another nickname")
    return nick


# --------------------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, nickname TEXT NOT NULL, pair TEXT NOT NULL,
  call_date TEXT NOT NULL, prob REAL NOT NULL, model_risk REAL NOT NULL, locked_at TEXT NOT NULL,
  outcome INTEGER, resolved_at TEXT, brier_user REAL, brier_model REAL,
  UNIQUE(nickname, pair, call_date));
CREATE TABLE IF NOT EXISTS visits (nickname TEXT NOT NULL, day TEXT NOT NULL, UNIQUE(nickname, day));
CREATE TABLE IF NOT EXISTS badges (nickname TEXT NOT NULL, badge TEXT NOT NULL, unlocked_at TEXT NOT NULL, UNIQUE(nickname, badge));
CREATE TABLE IF NOT EXISTS gallery_opens (nickname TEXT NOT NULL, storm_id TEXT NOT NULL, opened_at TEXT NOT NULL, UNIQUE(nickname, storm_id));
CREATE TABLE IF NOT EXISTS events (nickname TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH  # resolved at call time so tests can redirect the store
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# calls
# --------------------------------------------------------------------------------------
@dataclass
class PreLockPayload:
    """Everything the client may see BEFORE locking. Deliberately no model value."""

    pair: str
    call_date: str
    regime: str
    days_in_regime: int
    week_key: str

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        assert not any("risk" in k for k in d), "anti-anchoring: model risk must not be here"
        return d


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def pre_lock_payload(regimes: pd.DataFrame, pair: str) -> PreLockPayload:
    r = regimes[regimes["pair"] == pair].sort_values("date").iloc[-1]
    d = pd.Timestamp(r["date"]).date()
    return PreLockPayload(
        pair=pair,
        call_date=str(d),
        regime=str(r["regime"]),
        days_in_regime=int(r["days_in_regime"]),
        week_key=week_key(d),
    )


def already_called_this_week(
    conn: sqlite3.Connection, nickname: str, pair: str, call_date: str
) -> bool:
    wk = week_key(date.fromisoformat(call_date))
    rows = conn.execute(
        "SELECT call_date FROM calls WHERE nickname=? AND pair=?", (nickname, pair)
    ).fetchall()
    return any(week_key(date.fromisoformat(cd)) == wk for (cd,) in rows)


def place_call(
    conn: sqlite3.Connection, regimes: pd.DataFrame, nickname: str, pair: str, prob: float
) -> int:
    """Lock a call. The model's risk is looked up and STORED here — after the user's number exists —
    and only `post_lock_view` reveals it. One call per pair per ISO week."""
    nickname = clean_nickname(nickname)
    prob = float(min(1.0, max(0.0, prob)))
    r = regimes[regimes["pair"] == pair].sort_values("date").iloc[-1]
    call_date = str(pd.Timestamp(r["date"]).date())
    if already_called_this_week(conn, nickname, pair, call_date):
        raise ValueError("one call per pair per week — this week's call is already locked")
    model_risk = float(r["change_risk_5d"])
    cur = conn.execute(
        "INSERT INTO calls (nickname, pair, call_date, prob, model_risk, locked_at) VALUES (?,?,?,?,?,?)",
        (nickname, pair, call_date, prob, model_risk, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def post_lock_view(conn: sqlite3.Connection, call_id: int) -> dict:
    row = conn.execute(
        "SELECT id, nickname, pair, call_date, prob, model_risk, outcome, brier_user, brier_model FROM calls WHERE id=?",
        (call_id,),
    ).fetchone()
    keys = [
        "id",
        "nickname",
        "pair",
        "call_date",
        "prob",
        "model_risk",
        "outcome",
        "brier_user",
        "brier_model",
    ]
    return dict(zip(keys, row, strict=True))


# --------------------------------------------------------------------------------------
# resolution (pipeline step)
# --------------------------------------------------------------------------------------
def outcome_for(
    regimes: pd.DataFrame, pair: str, call_date: str, horizon: int = HORIZON
) -> int | None:
    """1 if the regime at any of the next `horizon` trading days differs from the call-day regime,
    0 if not; None if fewer than `horizon` trading days have elapsed yet."""
    g = regimes[regimes["pair"] == pair].sort_values("date").reset_index(drop=True)
    idx = g.index[g["date"] == pd.Timestamp(call_date)]
    if len(idx) == 0:
        return None
    i = int(idx[0])
    if i + horizon >= len(g):
        return None
    base = g.loc[i, "regime"]
    return int((g.loc[i + 1 : i + horizon, "regime"] != base).any())


def resolve_calls(conn: sqlite3.Connection, regimes: pd.DataFrame) -> int:
    """Resolve every matured call; score user and model on the identical question. Returns count."""
    n = 0
    for cid, pair, call_date, prob, model_risk in conn.execute(
        "SELECT id, pair, call_date, prob, model_risk FROM calls WHERE outcome IS NULL"
    ).fetchall():
        y = outcome_for(regimes, pair, call_date)
        if y is None:
            continue
        conn.execute(
            "UPDATE calls SET outcome=?, resolved_at=?, brier_user=?, brier_model=? WHERE id=?",
            (y, _now(), brier(prob, y), brier(model_risk, y), cid),
        )
        n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------------------
# ledger, streaks, ranks, badges
# --------------------------------------------------------------------------------------
def ledger(conn: sqlite3.Connection, nickname: str, window: int = 20) -> dict:
    rows = conn.execute(
        "SELECT brier_user, brier_model FROM calls WHERE nickname=? AND outcome IS NOT NULL ORDER BY call_date DESC LIMIT ?",
        (nickname, window),
    ).fetchall()
    n = len(rows)
    if n == 0:
        return {"resolved": 0, "brier_user": None, "brier_model": None, "wins": 0, "losses": 0}
    bu = sum(r[0] for r in rows) / n
    bm = sum(r[1] for r in rows) / n
    wins = sum(1 for r in rows if r[0] < r[1])
    return {"resolved": n, "brier_user": bu, "brier_model": bm, "wins": wins, "losses": n - wins}


def record_visit(conn: sqlite3.Connection, nickname: str, today: date | None = None) -> None:
    today = today or datetime.now(UTC).date()
    conn.execute(
        "INSERT OR IGNORE INTO visits (nickname, day) VALUES (?, ?)", (nickname, str(today))
    )
    conn.commit()


def watch_streak(conn: sqlite3.Connection, nickname: str, today: date | None = None) -> int:
    """Consecutive UTC days with a visit, counting back from today (0 if not visited today)."""
    today = today or datetime.now(UTC).date()
    days = {
        date.fromisoformat(d)
        for (d,) in conn.execute("SELECT day FROM visits WHERE nickname=?", (nickname,)).fetchall()
    }
    streak, d = 0, today
    while d in days:
        streak += 1
        d -= timedelta(days=1)
    return streak


def rank_for(resolved: int, brier_mean: float | None) -> str:
    name = RANKS[0][2]
    for min_calls, max_brier, rname in RANKS:
        if resolved >= min_calls and (
            brier_mean is None or brier_mean <= max_brier or min_calls == 0
        ):
            name = rname
    return name


def record_event(conn: sqlite3.Connection, nickname: str, kind: str) -> None:
    conn.execute("INSERT INTO events (nickname, kind, at) VALUES (?,?,?)", (nickname, kind, _now()))
    conn.commit()


def evaluate_badges(
    conn: sqlite3.Connection, nickname: str, live_regimes: dict[str, str] | None = None
) -> list[str]:
    """Check every badge rule (table BADGES) and persist new unlocks; returns all unlocked."""
    led = ledger(conn, nickname, window=10_000)
    events = {
        k
        for (k,) in conn.execute(
            "SELECT DISTINCT kind FROM events WHERE nickname=?", (nickname,)
        ).fetchall()
    }
    rules = {
        "methodology reader": "methodology_opened" in events,
        "first resolved call": led["resolved"] >= 1,
        "well calibrated": led["resolved"] >= 10 and (led["brier_user"] or 1.0) < 0.20,
        "storm survivor": "storm_visit" in events
        or bool(live_regimes and "crisis" in live_regimes.values()),
        "beat the model": led["resolved"] >= 10
        and led["brier_user"] is not None
        and led["brier_user"] < led["brier_model"],
    }
    if live_regimes and "crisis" in live_regimes.values() and "storm_visit" not in events:
        record_event(conn, nickname, "storm_visit")
    for badge, ok in rules.items():
        if ok:
            conn.execute(
                "INSERT OR IGNORE INTO badges (nickname, badge, unlocked_at) VALUES (?,?,?)",
                (nickname, badge, _now()),
            )
    conn.commit()
    return [
        b
        for (b,) in conn.execute(
            "SELECT badge FROM badges WHERE nickname=?", (nickname,)
        ).fetchall()
    ]


# --------------------------------------------------------------------------------------
# storm gallery
# --------------------------------------------------------------------------------------
def load_storms(path: Path = STORMS_PATH, verified_only: bool = True) -> list[dict]:
    storms = yaml.safe_load(path.read_text())["storms"]
    return [s for s in storms if s.get("verified") or not verified_only]


def open_storm(conn: sqlite3.Connection, nickname: str, storm_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO gallery_opens (nickname, storm_id, opened_at) VALUES (?,?,?)",
        (nickname, storm_id, _now()),
    )
    conn.commit()


def unlocked_storms(conn: sqlite3.Connection, nickname: str) -> set[str]:
    return {
        s
        for (s,) in conn.execute(
            "SELECT storm_id FROM gallery_opens WHERE nickname=?", (nickname,)
        ).fetchall()
    }
