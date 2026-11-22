"""tickets.rs (Ticket Vision, Srbija): kartice evenata na pocetnoj stranici (server-rendered)."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from radar.http import get_text
from radar.models import Event
from radar.sources.base import Context, clean

_ID_RE = re.compile(r"^/(tour|event)/([a-z0-9_]+?)_(\d+)$")


def parse(html: str, base: str, name: str, country: str) -> list[Event]:
    tree = HTMLParser(html)
    out: dict[str, Event] = {}
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").split("?")[0]
        m = _ID_RE.match(href)
        if not m:
            continue
        uid = f"{m.group(1)}:{m.group(3)}"
        h3 = a.css_first("h3")
        title = clean(h3.text()) if h3 else ""
        if uid in out and (out[uid].title or not title):
            continue
        dt = a.css_first(".date-time")
        place = a.css_first(".place")
        price = a.css_first(".price")
        venue, city = "", ""
        if place:
            p = clean(place.text())
            venue, _, city = p.rpartition(",")
            venue, city = (venue.strip(), city.strip()) if venue else (p, "")
        out[uid] = Event(
            source=name, uid=uid, title=title or m.group(2).replace("_", " ").capitalize(),
            url=urljoin(base, href), kind="listing", venue=venue, city=city, country=country,
            date=clean(dt.text()) if dt else "", price=clean(price.text()) if price else "",
            # kartica s cijenom = karte se mogu kupiti
            availability="InStock" if price and re.search(r"\d", price.text()) else "",
        )
    return list(out.values())


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    events: dict[str, Event] = {}
    for url in cfg.get("urls", ["https://tickets.rs/"]):
        for e in parse(get_text(ctx.client, url), url, cfg["_name"], cfg.get("country", "RS")):
            events.setdefault(e.uid, e)
    return list(events.values())
