"""Najave iz medija: Google News RSS pretrage + RSS portala.

Google News indeksira i stranice evenata s Entria/Eventima ("Ulaznice za X, Dvorana, Grad | datum - Entrio"),
pa se tako legitimno vide i novi eventi s Entria (koji blokira automatske posjete).
"""
from __future__ import annotations

import calendar
import concurrent.futures as cf
import re
import time
import urllib.parse as up

import feedparser

from radar.http import get_text
from radar.models import Event
from radar.sources.base import Context, clean
from radar.textnorm import norm

MAX_AGE_DAYS = 4

# clanak mora spominjati nesto vezano uz karte/koncerte da bi uopce usao u obradu
TICKET_RE = re.compile(
    r"\b(ulaznic\w*|karte|karata|kartama|vstopnic\w*|koncert\w*|turnej\w*|turnej|tour|rasprodan\w*|razprodan\w*|"
    r"presale|pretprodaj\w*|predprodaj\w*|festival\w*|tickets?|nastop\w*|nastup\w*|spektak\w*|"
    r"stand ?up\w*|stendap\w*|komicar\w*|komedij\w*|show)\b"
)


def _published(entry) -> str:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", t) if t else ""
_LISTING_RE = re.compile(r"^(?:Ulaznice za|Tickets for|Tickets für|Vstopnice za|Karte za|Ulaznice)\s+(.+)$", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _age_days(entry) -> float:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return 0.0
    return (time.time() - calendar.timegm(t)) / 86400


def _split_source(title: str) -> tuple[str, str]:
    """'Naslov - Izvor' -> ('Naslov', 'Izvor')"""
    if " - " in title:
        head, _, src = title.rpartition(" - ")
        if len(src) <= 40:
            return head.strip(), src.strip()
    return title.strip(), ""


def parse_listing_title(head: str) -> dict | None:
    """'Ulaznice za ŽENOMRZAC U TUZLI, Bosanski kulturni centar TK, Tuzla | Subota, 16.01.2027., 20:00h'"""
    m = _LISTING_RE.match(head)
    if not m:
        return None
    rest = m.group(1)
    main, _, when = rest.partition(" | ")
    parts = [p.strip() for p in main.split(",")]
    d = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})\.?(?:,?\s*(\d{1,2}:\d{2}))?", when)
    return {
        "title": parts[0],
        "venue": parts[1] if len(parts) > 2 else "",
        "city": parts[-1] if len(parts) > 1 else "",
        "date": (d.group(1) + (f" {d.group(2)}" if d.group(2) else "")) if d else clean(when),
    }


def _gn_url(q: str, lang: str = "sr", country: str = "RS") -> str:
    # hr/bs izdanja Google Newsa preusmjeravaju na US; sr/RS i sl/SI rade i pokrivaju cijelu regiju
    return f"https://news.google.com/rss/search?q={up.quote(q)}&hl={lang}&gl={country}&ceid={country}:{lang}"


def _entries(ctx: Context, url: str):
    return feedparser.parse(get_text(ctx.client, url).encode("utf-8")).entries


FOLLOW_TERMS = "ulaznice OR karte OR rasprodano OR faza OR prodaja OR \"early bird\""


def follow_queries(wl: dict, days: int = 3) -> list[str]:
    """Za svako ime s liste "pratim" jedna pretraga o kartama (sva alternativna imena u jednom upitu)."""
    fol = wl.get("pratim") or {}
    items = fol if isinstance(fol, list) else fol.get("list") or []
    out = []
    for item in items:
        name = next(iter(item)) if isinstance(item, dict) else str(item)
        alts = [a.strip().lstrip("=") for a in name.split("|") if a.strip()]
        who = " OR ".join(f'"{a}"' for a in alts)
        out.append(f"({who}) ({FOLLOW_TERMS}) when:{days}d")
    return out


def fetch_google_news(ctx: Context, cfg: dict) -> list[Event]:
    queries = []
    for q in cfg.get("queries", []):
        if isinstance(q, dict):
            queries.append((q["q"], q.get("lang", "sr"), q.get("country", "RS")))
        else:
            queries.append((q, "sr", "RS"))
    # pretrage za listu "pratim" (main.run_sources ih stavlja u cfg, pa promjena liste mijenja i hash izvora)
    queries += [(q, "sr", "RS") for q in cfg.get("follow", [])]
    out: dict[str, Event] = {}
    errors = 0

    def one(q):
        try:
            return q, _entries(ctx, _gn_url(*q))
        except Exception:  # noqa: BLE001
            return q, None

    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(one, queries))
    for q, entries in results:
        if entries is None:
            errors += 1
            continue
        for en in entries:
            if _age_days(en) > MAX_AGE_DAYS:
                continue
            head, src = _split_source(clean(en.get("title", "")))
            listing = parse_listing_title(head)
            if listing:
                uid = "L:" + norm(f"{listing['title']} {listing['city']} {listing['date']}")
                ev = Event(source=cfg["_name"], uid=uid, title=listing["title"], url=en.get("link", ""),
                           kind="listing", venue=listing["venue"], city=listing["city"], date=listing["date"],
                           summary=f"preko {src or 'Google News'}", extra={"via": src, "query": q[0]})
            else:
                uid = "N:" + (en.get("id") or en.get("link", ""))[-120:]
                ev = Event(source=cfg["_name"], uid=uid, title=head, url=en.get("link", ""), kind="news",
                           summary=src, extra={"via": src, "query": q[0], "published": _published(en)})
            out.setdefault(ev.uid, ev)
    if errors == len(queries):
        raise RuntimeError("sve Google News pretrage su pale")
    return list(out.values())


def fetch_rss(ctx: Context, cfg: dict) -> list[Event]:
    feeds: dict = cfg.get("feeds", {})
    out: dict[str, Event] = {}
    ok = 0

    def one(item):
        fname, fcfg = item
        url = fcfg if isinstance(fcfg, str) else fcfg["url"]
        try:
            return fname, fcfg, _entries(ctx, url)
        except Exception:  # noqa: BLE001
            return fname, fcfg, None

    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, feeds.items()))
    for fname, fcfg, entries in results:
        if entries is None:
            continue
        ok += 1
        country = "" if isinstance(fcfg, str) else fcfg.get("country", "")
        for en in entries:
            if _age_days(en) > MAX_AGE_DAYS:
                continue
            title = clean(en.get("title", ""))
            summary = clean(_TAG_RE.sub(" ", en.get("summary", "")))[:400]
            if not TICKET_RE.search(norm(f"{title} {summary}")):
                continue
            uid = (en.get("id") or en.get("link", ""))[-150:]
            out.setdefault(uid, Event(source=f"{cfg['_name']}/{fname}", uid=uid, title=title,
                                      url=en.get("link", ""), kind="news", summary=summary, country=country,
                                      extra={"via": fcfg.get("label", fname) if isinstance(fcfg, dict) else fname,
                                             "published": _published(en)}))
    if feeds and ok == 0:
        raise RuntimeError("niti jedan RSS feed nije dostupan")
    return list(out.values())
