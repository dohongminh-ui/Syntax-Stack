"""Generated nicknames ("<animal> <adjective> <NN>") and the blocklist for free-name classroom rooms.

Word lists: content/nickname_words.yaml. Blocklist rules: header of content/name_blocklist.yaml.
Generated names are always friendly by construction and never go through the blocklist; a free name is
accepted by ``is_allowed_free`` only when none of its normalised forms hits a blocklist entry.
"""
from __future__ import annotations

import random
import re
import unicodedata
from pathlib import Path
from typing import Optional

import yaml

from . import i18n

CONTENT = Path(__file__).resolve().parents[1] / "content"
WORDS_FILE = CONTENT / "nickname_words.yaml"
BLOCKLIST_FILE = CONTENT / "name_blocklist.yaml"
MAX_LEN = 20

_LOOKALIKES = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_REPEAT_ALL = re.compile(r"(.)\1+")
_REPEAT_TWO = re.compile(r"(.)\1{2,}")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


_words = _load(WORDS_FILE)
ANIMALS: tuple[str, ...] = tuple(_nfc(str(a)).strip() for a in _words["animals"])
ADJECTIVES: tuple[str, ...] = tuple(_nfc(str(a)).strip() for a in _words["adjectives"])
NUM_MIN: int = int(_words["numbers"]["min"])
NUM_MAX: int = int(_words["numbers"]["max"])
_PREFIXES = frozenset(f"{a} {j}" for a in ANIMALS for j in ADJECTIVES)
# English twins (same order, same length): English names read "<adjective> <animal> <NN>", e.g. "Blue Cat 42"
ANIMALS_EN: tuple[str, ...] = tuple(str(a).strip() for a in _words["animals_en"])
ADJECTIVES_EN: tuple[str, ...] = tuple(str(a).strip() for a in _words["adjectives_en"])
if len(ANIMALS_EN) != len(ANIMALS) or len(ADJECTIVES_EN) != len(ADJECTIVES):
    raise ValueError("nickname_words.yaml: animals_en / adjectives_en must parallel animals / adjectives")
_PREFIXES_EN = frozenset(f"{j} {a}" for a in ANIMALS_EN for j in ADJECTIVES_EN)


def animals(lang: Optional[str] = None) -> tuple[str, ...]:
    return ANIMALS_EN if i18n.resolve(lang) == "en" else ANIMALS

_blocked = _load(BLOCKLIST_FILE)
BLOCK_SUBSTRING: tuple[str, ...] = tuple(str(w).lower() for w in _blocked.get("substring") or [])
BLOCK_WORD: frozenset[str] = frozenset(str(w).lower() for w in _blocked.get("word") or [])


# --------------------------------------------------------------------------- generated names


def generate(rng: Optional[random.Random] = None, lang: Optional[str] = None) -> str:
    """A fresh name of at most 20 characters: "<animal> <adjective> <NN>" ("Mèo Xanh 42"), or in English (``lang``,
    default the request's) "<adjective> <animal> <NN>" ("Blue Cat 42"). The English lists are parallel to the
    Vietnamese ones, so both draw the same way from ``rng``."""
    pick = rng or random.SystemRandom()
    english = i18n.resolve(lang) == "en"
    while True:
        animal = pick.choice(ANIMALS_EN if english else ANIMALS)
        adjective = pick.choice(ADJECTIVES_EN if english else ADJECTIVES)
        number = pick.randint(NUM_MIN, NUM_MAX)
        name = f"{adjective} {animal} {number}" if english else f"{animal} {adjective} {number}"
        if len(name) <= MAX_LEN:
            return name


def is_generated(name: object) -> bool:
    """True only for an exact generated-format name, Vietnamese or English (after NFC normalisation); anything else
    is False. Names already chosen are never translated, so both forms stay valid whatever the request's language."""
    if not isinstance(name, str):
        return False
    name = _nfc(name)
    if len(name) > MAX_LEN:
        return False
    prefix, _, num = name.rpartition(" ")
    if (prefix not in _PREFIXES and prefix not in _PREFIXES_EN) or not num.isascii() or not num.isdigit() \
            or num != str(int(num)):
        return False
    return NUM_MIN <= int(num) <= NUM_MAX


# --------------------------------------------------------------------------- blocklist


def _fold(text: str) -> str:
    """NFD, combining marks stripped, đ -> d, lowercase, look-alikes mapped. Other characters are kept."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.lower().translate(_LOOKALIKES)


def _forms(text: str) -> set[str]:
    """The text as written, with every run of one letter collapsed to one, and to at most two."""
    return {text, _REPEAT_ALL.sub(r"\1", text), _REPEAT_TWO.sub(r"\1\1", text)}


def _letters(text: str) -> str:
    return "".join(ch for ch in text if ch.isalpha())


def _words_of(folded: str) -> set[str]:
    """Candidate whole words: each space-separated token with symbols dropped ("d.m" -> "dm"), the parts
    split on symbols, and runs of single letters joined ("v c l" -> "vcl")."""
    out: set[str] = set()
    for token in folded.split():
        if _letters(token):
            out.add(_letters(token))
    parts = [p for p in re.split(r"[^a-z]+", folded) if p]
    out.update(parts)
    run = ""
    for p in parts + [""]:
        if len(p) == 1:
            run += p
            continue
        if len(run) > 1:
            out.add(run)
        run = ""
    return out


def is_allowed_free(name: str) -> bool:
    """False when the name hits the blocklist (rules: header of content/name_blocklist.yaml)."""
    folded = _fold(_nfc(name or ""))
    squashed = _letters(folded)
    for form in _forms(squashed):
        if any(bad in form for bad in BLOCK_SUBSTRING):
            return False
    for word in _words_of(folded):
        if any(form in BLOCK_WORD for form in _forms(word)):
            return False
    return True
