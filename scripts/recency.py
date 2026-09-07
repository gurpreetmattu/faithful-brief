"""
Recency-awareness, per specs/recency-gate.md.

Deliberately mechanical -- no LLM call, no ground truth, no eval script. Every
fact needed (frozen_at, date_window, per-paper submitted_at/version_date) is
already a plain date in data/corpus.v1.json; comparing dates and matching a
few keyword patterns doesn't earn an agent call (CLAUDE.md: "every component
must earn its place").

Advisory only -- never blocks a brief (contrast scope_gate.py, which does).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

import corpus_access

STALENESS_THRESHOLD_DAYS = 90
IDEA_AGE_THRESHOLD_DAYS = 90

_RECENCY_PATTERNS = re.compile(
    r"\b(latest|newest|most recent|recently|current state of the art|"
    r"state[- ]of[- ]the[- ]art (?:today|now)|this year|nowadays|up[- ]to[- ]date)\b",
    re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


@dataclass
class RecencyNotice:
    frozen_at: str
    days_since_freeze: int
    corpus_stale: bool
    question_recency_sensitive: bool
    note: str

    def to_dict(self) -> dict:
        return {
            "frozen_at": self.frozen_at,
            "days_since_freeze": self.days_since_freeze,
            "corpus_stale": self.corpus_stale,
            "question_recency_sensitive": self.question_recency_sensitive,
            "note": self.note,
        }


def question_recency_sensitive(question: str, window_to_year: int) -> bool:
    if _RECENCY_PATTERNS.search(question):
        return True
    for match in _YEAR_PATTERN.findall(question):
        if int(match) > window_to_year:
            return True
    return False


def check_recency(question: str) -> RecencyNotice:
    meta = corpus_access.manifest_meta()
    frozen_at = date.fromisoformat(meta["frozen_at"])
    window_to = date.fromisoformat(meta["date_window"]["to"])
    today = date.today()

    days_since_freeze = (today - frozen_at).days
    corpus_stale = days_since_freeze > STALENESS_THRESHOLD_DAYS
    recency_sensitive = question_recency_sensitive(question, window_to.year)

    notes = []
    if corpus_stale:
        notes.append(
            f"The corpus was frozen {days_since_freeze} days ago ({frozen_at.isoformat()}); "
            f"real RAG research published since then is not represented."
        )
    if recency_sensitive:
        notes.append(
            f"This question asks about current/recent work, but the corpus only covers "
            f"papers through {window_to.isoformat()} -- treat any answer as bounded by that date, not 'now'."
        )
    note = " ".join(notes) if notes else "No recency concerns: corpus is fresh and the question isn't recency-sensitive."

    return RecencyNotice(
        frozen_at=frozen_at.isoformat(),
        days_since_freeze=days_since_freeze,
        corpus_stale=corpus_stale,
        question_recency_sensitive=recency_sensitive,
        note=note,
    )


def idea_age_note(paper_id: str) -> Optional[str]:
    """
    None if paper_id isn't in the corpus, or if its submitted_at/version_date
    gap is under the threshold. Otherwise a note flagging that the underlying
    ideas may be older than the pinned version's date suggests
    (corpus-manifest.md Sec 5's own example: 2020 ideas, a 2021-dated v4).
    """
    dates = corpus_access.paper_dates(paper_id)
    if dates is None:
        return None
    submitted = date.fromisoformat(dates["submitted_at"])
    versioned = date.fromisoformat(dates["version_date"])
    gap_days = (versioned - submitted).days
    if gap_days <= IDEA_AGE_THRESHOLD_DAYS:
        return None
    return (
        f"This citation's pinned version is dated {dates['version_date']}, but the "
        f"underlying ideas were first submitted {dates['submitted_at']} ({gap_days} days earlier)."
    )
