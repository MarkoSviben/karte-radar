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
            first_seen: dict[str, float], min_score: int, merge_dates: bool,
            announcements: bool = False) -> list[Event]:
    """Svi buduci eventi s >= min_score bodova, bez duplikata (isti event s vise izvora).
    announcements=True: dodaj i nove stranice izvodjaca na Eventimu (zadnjih 14 dana) kao najave."""
    today = now.date()
    events: list[Event] = []
    for name, r in results.items():
        if r.get("skipped") or not r.get("events"):
            continue
        for e in r["events"]:
            is_new = now.timestamp() - first_seen.get(f"{name}:{e.uid}", 0) < 7 * 86400
            if e.kind == "artist":
                if not (announcements and f"{name}:{e.uid}" in first_seen):
                    continue
            elif e.kind not in ("listing", "tour"):
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
            e.extra["_new"] = is_new
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


SOURCE_LABEL = {"eventim_hr": "Eventim HR", "eventim_si": "Eventim SI", "tickets_rs": "tickets.rs",
                "gigstix": "Gigs Tix", "ulaznice_hr": "ulaznice.hr", "kupikartu_ba": "kupikartu.ba",
                "mojekarte_si": "mojekarte.si", "google_news": "Entrio", "bandsintown": "Bandsintown"}


def ticket_state(e: Event, now: datetime) -> str:
    """Kategorija karata:
    soon = karte jos nisu izasle (poznat datum prodaje u buducnosti ili pretprodaja)
    ann  = najava (izvodjac se pojavio, eventa/karata jos nema)
    on   = u prodaji, low = malo karata, out = rasprodano / nema karata
    unk  = event je na prodajnom mjestu, ali izvor ne kaze status karata"""
    if e.kind == "artist":
        return "ann"
    if e.sale_start:
        try:
            sale = datetime.fromisoformat(e.sale_start.replace("Z", "+00:00"))
            if sale.tzinfo is None:
                sale = sale.replace(tzinfo=now.tzinfo)
            if sale > now:
                return "soon"
        except ValueError:
            pass
    av = set((e.availability or "").split(",")) - {""}
    if av & {"PreSale", "PreOrder"}:
        return "soon"
    if "LimitedAvailability" in av:
        return "low"
    if av & {"InStock", "OnlineOnly"}:
        return "on"
    if av and av <= {"SoldOut", "OutOfStock", "Discontinued"}:
        return "out"
    if e.sale_start:
        return "on"  # prodaja je pocela, status nepoznat -> u prodaji
    return "unk"


def to_json(reps: list[Event], now: datetime, instant: int, sources: dict | None = None,
            details_at: str = "", news: list | None = None) -> dict:
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
            "dt": "" if (d and exact) else e.date, "ks": ticket_state(e, now),
            "sale": e.sale_start[:16] if e.sale_start else "", "p": _price(e), "sc": e.score,
            "src": SOURCE_LABEL.get(e.source, e.source), "k": e.kind, "new": bool(e.extra.get("_new")),
            "chk": datetime.fromtimestamp(e.extra["checked"], now.tzinfo).isoformat(timespec="minutes")
                   if e.extra.get("checked") else "",
        })
    return {"updated": now.isoformat(timespec="minutes"), "big": instant, "events": out,
            "sources": sources or {}, "details_at": details_at, "news": news or []}


COMEDY = ("stand up", "standup", "stendap", "komicar", "komicark", "komedij")


def update_news(store: dict, results: dict, scorer: Scorer, now: datetime) -> None:
    """Spremi najave iz medija (portali, Google News) iz ovog runa u `store` (pamti se 7 dana)."""
    ts = now.timestamp()
    for r in results.values():
        for e in r.get("events") or []:
            if e.kind != "news":
                continue
            scorer.score(e)
            nt = e.extra.get("news_type")
            if e.score < scorer.digest or nt not in ("karte", "najava", "spomen"):
                continue
            if nt == "spomen" and e.score < scorer.instant:
                continue  # samo spomen poznatog imena (cesto trac) -> na stranicu samo ako je bas vazno
            key = e.url[-200:]
            old = store.get(key, {})
            store[key] = {
                "t": e.title, "u": e.url, "via": e.extra.get("via") or e.source, "cc": e.country,
                "pub": e.extra.get("published") or old.get("pub") or now.isoformat(timespec="minutes"),
                "sc": e.score, "lab": e.extra.get("labels", []), "type": e.extra["news_type"],
                "comedy": any(c in norm(e.title + " " + e.summary[:300]) for c in COMEDY),
                "ts": old.get("ts", ts),
            }


def news_json(store: dict, min_mention: int = 50) -> list[dict]:
    """Najave za stranicu: ista vijest s vise portala -> jedna stavka s popisom izvora.
    Puki spomen poznatog imena (bez najave/karata) samo ako ima >= min_mention bodova."""
    items = sorted((v for v in store.values() if v["type"] != "spomen" or v["sc"] >= min_mention),
                   key=lambda x: x["pub"], reverse=True)
    out: list[dict] = []
    index: dict[str, list[dict]] = {}
    for it in items:
        keys = key_tokens(it["t"], 3)
        cands = {id(o): o for k in keys for o in index.get(k, [])}.values()
        dup = next((o for o in cands if similar(o["t"], it["t"]) >= 0.7), None)
        if dup:
            if it["via"] not in dup["via"]:
                dup["via"].append(it["via"])
            dup["sc"] = max(dup["sc"], it["sc"])
            dup["lab"] = sorted(set(dup["lab"]) | set(it["lab"]))
            if it["type"] == "karte":
                dup["type"] = "karte"
            continue
        o = {"t": it["t"], "u": it["u"], "via": [it["via"]], "pub": it["pub"], "sc": it["sc"],
             "lab": list(it["lab"]), "type": it["type"], "comedy": it["comedy"], "cc": it.get("cc", "")}
        out.append(o)
        for k in keys:
            index.setdefault(k, []).append(o)
    return out


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
