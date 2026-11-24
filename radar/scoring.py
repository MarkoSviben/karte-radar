"""Bodovanje evenata prema watchlisti (izvodjaci, klubovi, dvorane, kljucne rijeci)."""
from __future__ import annotations

from dataclasses import dataclass

from radar.models import Event
from radar.textnorm import Phrase, prefixes, tokens


@dataclass
class Rule:
    label: str
    phrases: list[Phrase]
    weight: int
    group: str  # artist / team / venue / keyword


def _parse_entries(entries, weight: int, group: str) -> list[Rule]:
    rules = []
    for item in entries or []:
        w = weight
        if isinstance(item, dict):  # {"Coldplay": 80}
            for name, ww in item.items():
                alts = [Phrase(a) for a in str(name).split("|")]
                rules.append(Rule(str(name).split("|")[0].lstrip("="), alts, int(ww), group))
            continue
        alts = [Phrase(a) for a in str(item).split("|")]
        rules.append(Rule(str(item).split("|")[0].lstrip("="), alts, w, group))
    return rules


class Scorer:
    def __init__(self, wl: dict):
        self.instant = int(wl.get("threshold_instant", 50))
        self.digest = int(wl.get("threshold_digest", 15))
        self.kind_bonus = {k: int(v) for k, v in (wl.get("kind_bonus") or {}).items()}
        self.rules: list[Rule] = []
        for section, group in (("artists", "artist"), ("teams", "team"), ("venues", "venue")):
            sec = wl.get(section) or {}
            default_w = int(sec.get("weight", 50))
            for key, entries in sec.items():
                if key == "weight":
                    continue
                if isinstance(entries, dict):  # podgrupa s vlastitom tezinom
                    w = int(entries.get("weight", default_w))
                    self.rules += _parse_entries(entries.get("list"), w, group)
                else:
                    self.rules += _parse_entries(entries, default_w, group)
        # "pratim": organizatori/festivali/izvodjaci kojima se prati izlazak karata (jaci od watchliste)
        fol = wl.get("pratim") or {}
        if isinstance(fol, list):
            fol = {"list": fol}
        follow_rules = _parse_entries(fol.get("list"), int(fol.get("weight", 90)), "artist")
        self.follow: set[str] = {r.label for r in follow_rules}
        self.rules += follow_rules
        kw = wl.get("keywords") or {}
        for name, w in {**(kw.get("positive") or {}), **(kw.get("negative") or {})}.items():
            alts = [Phrase(a) for a in name.split("|")]
            self.rules.append(Rule(name.split("|")[0].lstrip("="), alts, int(w), "keyword"))
        gate = wl.get("news_gate") or {}
        self.gate_sale = [Phrase(a) for a in str(gate.get("sale", "")).split("|") if a.strip()]
        self.gate_event = [Phrase(a) for a in str(gate.get("event", "")).split("|") if a.strip()]
        self.gate_announce = [Phrase(a) for a in str(gate.get("announce", "")).split("|") if a.strip()]

    def _news_gate(self, e: Event, toks: list[str], total: int) -> int:
        """Propusta vijesti o kartama i najave dogadjaja (za bilo koga); tracevi/intervjui -> 0."""
        pre = prefixes(toks)
        has = lambda phrases: any(p.found_in(toks, pre) for p in phrases)  # noqa: E731
        # dogadjaj = rijec poput "koncert/stand up/bend" ILI poznato ime / dvorana s liste
        is_event = has(self.gate_event) or bool({"artist", "team", "venue"} & set(e.extra.get("matched", [])))
        e.extra["is_event"] = is_event
        if not self.gate_sale or has(self.gate_sale):
            e.extra["news_type"] = "karte"
            return total
        if is_event and has(self.gate_announce):
            e.extra["news_type"] = "najava"
            return total
        if is_event and e.extra.get("labels") and not e.extra.get("neg"):
            e.extra["news_type"] = "spomen"
            e.reasons.append("bez najave/karata → samo sažetak")
            return min(total, self.digest)
        e.reasons.append("nije najava ni o kartama")
        return 0

    def score(self, e: Event) -> Event:
        toks = tokens(" ".join([e.title, e.venue, e.city, e.summary[:300] if e.kind == "news" else ""]))
        pre = prefixes(toks)
        total, reasons, best_by_group = 0, [], {}
        for r in self.rules:
            if any(p.found_in(toks, pre) for p in r.phrases):
                if r.group == "keyword":
                    total += r.weight
                    if r.weight < 0:
                        e.extra["neg"] = True
                    reasons.append(f"{r.label}{r.weight:+d}")
                else:
                    # unutar grupe broji samo najjacu (Arena Zagreb + Zagreb ne zbrajamo)
                    if r.weight > best_by_group.get(r.group, (0, ""))[0]:
                        best_by_group[r.group] = (r.weight, r.label)
        for g, (w, label) in best_by_group.items():
            total += w
            reasons.insert(0, label)
        bonus = self.kind_bonus.get(e.kind, 0)
        if bonus:
            total += bonus
        if e.availability and "SoldOut" in e.availability:
            reasons.append("rasprodano")
        e.score, e.reasons = total, reasons
        e.extra["matched"] = sorted(best_by_group)
        e.extra["labels"] = [best_by_group[g][1] for g in ("artist", "team") if g in best_by_group]
        if e.kind == "news":
            e.score = self._news_gate(e, toks, total)
        return e

    def is_followed(self, e: Event) -> bool:
        """Event/vijest o nekome s liste "pratim"."""
        return bool(self.follow & set(e.extra.get("labels") or []))

    @staticmethod
    def is_watchlisted(e: Event) -> bool:
        """Izvodjac ili klub s watchliste (ne samo dvorana/kljucna rijec)."""
        return bool({"artist", "team"} & set(e.extra.get("matched", [])))
