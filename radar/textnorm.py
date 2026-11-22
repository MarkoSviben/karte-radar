"""Normalizacija teksta: mala slova, bez dijakritika, cirilica -> latinica, tolerancija padeza."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ђ": "dj", "е": "e", "ж": "z",
    "з": "z", "и": "i", "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n",
    "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "c", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "c", "џ": "dz", "ш": "s",
}


def norm(text: str) -> str:
    s = (text or "").lower()
    s = "".join(_CYR.get(c, c) for c in s)
    s = s.replace("đ", "dj").replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def tokens(text: str) -> list[str]:
    return norm(text).split()


_VOWELS = set("aeiou")


def _stem(tok: str) -> str:
    # "ceca" -> "cec" (cecin, cecom), "dino" -> "din" (dina); suglasnik ostaje ("sting" -> stingov)
    if len(tok) >= 4 and tok[-1] in _VOWELS:
        return tok[:-1]
    return tok


def _tok_match(pattern_tok: str, text_tok: str, exact: bool) -> bool:
    if exact or len(pattern_tok) <= 2 or pattern_tok.isdigit():
        return pattern_tok == text_tok
    stem = _stem(pattern_tok)
    # "dino" -> din + max 2 slova (dina, dinom) ali ne "dinamo"; "sting" -> + max 3 (stingov, stingova)
    max_extra = 2 if len(stem) < len(pattern_tok) else 3
    return text_tok.startswith(stem) and len(text_tok) - len(stem) <= max_extra


class Phrase:
    """Fraza za trazenje u tekstu. 'Dino Merlin' pogadja i 'Dina Merlina'.
    Prefiks '=' znaci tocno podudaranje (bez padeza)."""

    def __init__(self, raw: str):
        self.raw = raw.strip()
        self.exact = self.raw.startswith("=")
        self.toks = tokens(self.raw.lstrip("="))
        # brzi predfilter: prva 3 slova prvog tokena (ili stema) moraju postojati u tekstu
        first = self.toks[0] if self.toks else ""
        base = first if (self.exact or len(first) <= 2 or first.isdigit()) else _stem(first)
        self.key = base[:3]

    def found_in(self, text_toks: list[str], prefixes: set[str] | None = None) -> bool:
        n = len(self.toks)
        if n == 0:
            return False
        if prefixes is not None and self.key not in prefixes:
            return False
        for i in range(len(text_toks) - n + 1):
            if all(_tok_match(self.toks[j], text_toks[i + j], self.exact) for j in range(n)):
                return True
        return False


def prefixes(text_toks: list[str]) -> set[str]:
    """Skup prvih 3 slova svakog tokena (za Phrase.found_in predfilter)."""
    return {t[:3] for t in text_toks}


def similar(a: str, b: str) -> float:
    """Slicnost dva naslova 0..1 (difflib nad normaliziranim tokenima)."""
    from difflib import SequenceMatcher

    ta, tb = _norm_cached(a), _norm_cached(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    sa, sb = set(ta.split()), set(tb.split())
    common = len(sa & sb)
    if not common:
        return 0.0
    jacc = common / max(1, min(len(sa), len(sb)))
    sm = SequenceMatcher(None, ta, tb)
    seq = sm.ratio() if sm.real_quick_ratio() >= 0.85 and sm.quick_ratio() >= 0.85 else 0.0
    return max(seq, jacc if min(len(sa), len(sb)) >= 3 else 0.0)


def key_tokens(text: str, n: int = 2) -> list[str]:
    """Najduzi tokeni naslova (za brzo indeksiranje kandidata za duplikate)."""
    return sorted(set(_norm_cached(text).split()), key=lambda t: (-len(t), t))[:n]


@lru_cache(maxsize=50000)
def _norm_cached(text: str) -> str:
    return norm(text)
