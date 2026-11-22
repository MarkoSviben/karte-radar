"""kupikartu.ba (BiH): linkovi /karte/event/<id>/<slug> na pocetnoj i stranicama kategorija."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from radar.http import get_text
from radar.models import Event
from radar.sources.base import Context, clean, slug_title

_ID_RE = re.compile(r"/karte/event/(\d+)/([a-z0-9-]+)")


def parse(html: str, base: str, name: str, country: str) -> list[Event]:
    out: dict[str, Event] = {}
    for a in HTMLParser(html).css("a[href*='/karte/event/']"):
        m = _ID_RE.search(a.attributes.get("href") or "")
        if not m:
            continue
        uid = m.group(1)
        n, d, loc = a.css_first(".name"), a.css_first(".date"), a.css_first(".location")
        title = clean(n.text()) if n else ""
        if uid in out and (out[uid].title != slug_title(m.group(2)) or not title):
            continue
        venue, city = "", ""
        if loc:
            v = clean(loc.text()).lstrip("@ ").strip()
            venue, _, city = v.rpartition(" - ")
            venue, city = (venue, city) if venue else (v, "")
        out[uid] = Event(source=name, uid=uid, title=title or slug_title(m.group(2)),
                         url=urljoin(base, a.attributes["href"]), kind="listing", venue=venue, city=city,
                         date=clean(d.text()) if d else "", country=country)
    return list(out.values())


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    events: dict[str, Event] = {}
    for url in cfg.get("urls", ["https://www.kupikartu.ba/"]):
        for e in parse(get_text(ctx.client, url), url, cfg["_name"], cfg.get("country", "BA")):
            events.setdefault(e.uid, e)
    return list(events.values())
