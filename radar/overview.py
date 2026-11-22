"""PREGLED.md: citljiv pregled svih velikih evenata koji su trenutno u prodaji.

Upisuje se na granu 'state' svakim runom; GitHub ga prikazuje kao stranicu s tablicama.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from radar import notify as N
from radar.models import Event
from radar.scoring import Scorer
from radar.textnorm import key_tokens, norm, similar

COUNTRY_NAMES = {"HR": "🇭🇷 Hrvatska", "RS": "🇷🇸 Srbija", "BA": "🇧🇦 Bosna i Hercegovina",
                 "SI": "🇸🇮 Slovenija", "ME": "🇲🇪 Crna Gora", "": "🌍 Ostalo / nepoznato"}
MONTHS = {  # prva 3 slova (hr/sr/sl/en), nakon norm()
    "jan": 1, "sij": 1, "feb": 2, "vel": 2, "mar": 3, "ozu": 3, "apr": 4, "tra": 4, "maj": 5, "may": 5,
    "svi": 5, "jun": 6, "lip": 6, "jul": 7, "srp": 7, "avg": 8, "aug": 8, "kol": 8, "sep": 9, "ruj": 9,
    "okt": 10, "oct": 10, "lis": 10, "nov": 11, "stu": 11, "dec": 12, "pro": 12,
}


def event_date(e: Event) -> date | None:
    """Datum eventa iz ISO starta ili iz teksta ('27.11.2026.', '20 December 2026', '27 novembar 2026')."""
    if e.start and len(e.start) >= 10 and e.start[4] == "-":
        try:
            return date.fromisoformat(e.start[:10])
        except ValueError:
            pass
    s = norm(e.date)  # '27 11 2026 u 20 00', '20 december 2026', '12 14 december 2026'
    m = re.search(r"\b(\d{1,2}) (\d{1,2}) (20\d{2})\b", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?: \d{1,2})? ([a-z]{3,}) (20\d{2})\b", s)
    if m and m.group(2)[:3] in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"\b(20\d{2})\b", s)
    if m:
        return date(int(m.group(1)), 12, 31)  # znamo samo godinu -> kraj godine (za filtriranje proslih)
    return None


def _cell(s: str) -> str:
    return (s or "").replace("|", "/").replace("\n", " ").strip()


def collect(results: dict, scorer: Scorer, countries: set[str], now: datetime,
            first_seen: dict[str, float], min_score: int, merge_dates: bool) -> list[Event]:
    """Svi buduci listing eventi s >= min_score bodova, bez duplikata (isti event s vise izvora)."""
    today = now.date()
    events: list[Event] = []
    for name, r in results.items():
        if r.get("skipped") or not r.get("events"):
            continue
        for e in r["events"]:
            if e.kind != "listing":
                continue
            if e.country and countries and e.country not in countries:
                continue
            d = event_date(e)
            if d and d < today:
                continue  # prosao
            scorer.score(e)
            if e.score < min_score:
                continue
            e.extra["_date"] = d
            e.extra["_new"] = now.timestamp() - first_seen.get(f"{name}:{e.uid}", 0) < 7 * 86400
            events.append(e)

    events.sort(key=lambda e: (-(bool(e.start)), -e.score))  # oni s detaljima imaju prednost
    reps: list[Event] = []
    index: dict[str, list[Event]] = {}
    for e in events:
        keys = key_tokens(e.title)
        cands = {id(r): r for k in keys for r in index.get(k, [])}.values()
        dup = next((r for r in cands if similar(r.title, e.title) >= 0.85 and r.city == e.city
                    and (merge_dates or r.extra["_date"] == e.extra["_date"])), None)
        if dup:
            if e.extra["_date"] and e.extra["_date"] != dup.extra["_date"]:
                dup.extra.setdefault("_dates", {dup.extra["_date"]}).add(e.extra["_date"])
            dup.extra["_new"] = dup.extra["_new"] or e.extra["_new"]
            continue
        reps.append(e)
        for k in keys:
            index.setdefault(k, []).append(e)
    return reps


def _price(e: Event) -> str:
    p = (e.price or "").strip()
    if p and not re.search(r"[a-zA-Z€$]", p.replace("od", "")):
        p += " RSD" if e.country == "RS" else (" KM" if e.country == "BA" else " EUR")
    return p


def to_json(reps: list[Event], now: datetime, instant: int) -> dict:
    """Podaci za web stranicu (site/index.html). Bez razloga bodovanja (stranica je javna)."""
    out = []
    for e in reps:
        d = e.extra["_date"]
        exact = bool(e.start) or bool(re.search(r"\d{1,2}\D+\d{1,2}\D+20\d{2}|\d{1,2} [a-z]+ 20\d{2}", norm(e.date)))
        tm = e.start[11:16] if len(e.start) >= 16 and e.start[11:16] != "00:00" else ""
        if not tm:
            m = re.search(r"\b(\d{1,2}:\d{2})\b", e.date)
            tm = m.group(1) if m else ""
        out.append({
            "t": e.title, "u": e.url, "v": e.venue, "c": e.city, "cc": e.country or "",
            "d": d.isoformat() if d and exact else None, "y": d.year if d else None, "tm": tm,
            "dt": "" if (d and exact) else e.date, "st": e.availability.split(",")[0] if e.availability else "",
            "sale": e.sale_start[:16] if e.sale_start else "", "p": _price(e), "sc": e.score,
            "src": e.source, "new": bool(e.extra.get("_new")),
        })
    return {"updated": now.isoformat(timespec="minutes"), "big": instant, "events": out}


def build(results: dict, scorer: Scorer, countries: set[str], now: datetime,
          first_seen: dict[str, float]) -> str:
    reps = collect(results, scorer, countries, now, first_seen, scorer.instant, merge_dates=True)

    def sort_key(e: Event):
        d = e.extra["_date"]
        return (d is None, d or date.max, -e.score)

    lines = [
        "# 🎟 Karte radar: pregled",
        "",
        f"Ažurirano **{now.strftime('%d.%m.%Y. %H:%M')}** · **{len(reps)}** velikih evenata "
        f"(≥ {scorer.instant} bodova) · 🆕 = pojavio se u zadnjih 7 dana",
        "",
    ]
    new = sorted((e for e in reps if e.extra["_new"]), key=sort_key)
    if new:
        lines += ["## 🆕 Novo u zadnjih 7 dana", "", *_table(new), ""]
    by_country: dict[str, list[Event]] = {}
    for e in reps:
        by_country.setdefault(e.country if e.country in COUNTRY_NAMES else "", []).append(e)
    order = ["HR", "RS", "BA", "SI", "ME", ""]
    lines.append("**Skoči na:** " + " · ".join(
        f"[{COUNTRY_NAMES[c]} ({len(by_country[c])})](#{_anchor(COUNTRY_NAMES[c])})" for c in order if c in by_country))
    lines.append("")
    for c in order:
        if c not in by_country:
            continue
        lines += [f"## {COUNTRY_NAMES[c]}", "", *_table(sorted(by_country[c], key=sort_key)), ""]
    lines += ["---", "Eventi bez datuma su na dnu svake tablice (izvor ne daje datum). "
              "Bodove i listu izvođača mijenjaš u `config/watchlist.yaml`."]
    return "\n".join(lines) + "\n"


def _anchor(title: str) -> str:
    # GitHub anchor: mala slova, razmaci -> '-', bez interpunkcije i emojija
    s = re.sub(r"[^\w\s-]", "", title.lower(), flags=re.U).strip()
    return re.sub(r"\s+", "-", s)


def _table(evs: list[Event]) -> list[str]:
    out = ["| Datum | Event | Gdje | Status | ⭐ |", "|---|---|---|---|---|"]
    for e in evs:
        d = e.extra["_date"]
        dates = sorted(e.extra.get("_dates", []))
        if dates:
            when = f"{dates[0].strftime('%d.%m.%Y.')} (+{len(dates) - 1} termina)"
        elif e.start:
            when = N.fmt_dt(e.start)
        else:
            when = e.date or "?"
        status = []
        if e.availability:
            status.append(N.status_hr(e.availability))
        sale = e.sale_start
        if sale and sale[:10] > datetime.now().strftime("%Y-%m-%d"):
            status.append(f"**prodaja od {N.fmt_dt(sale)}**")
        if e.price:
            status.append(e.price)
        place = ", ".join(x for x in (e.venue, e.city) if x)
        new = "🆕 " if e.extra.get("_new") else ""
        out.append(f"| {_cell(when)} | {new}[{_cell(e.title)}]({e.url}) | {_cell(place)} | "
                   f"{_cell(' · '.join(status))} | {e.score} |")
    return out
