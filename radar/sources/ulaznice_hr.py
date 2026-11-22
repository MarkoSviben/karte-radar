"""ulaznice.hr: lista svih evenata (/web/events), kartice article.happeningContainer."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from radar.http import get_text
from radar.models import Event
from radar.sources.base import Context, clean

_ID_RE = re.compile(r"/web/event/(\d+)/(\d+)")


def parse(html: str, base: str, name: str, country: str) -> list[Event]:
    out: dict[str, Event] = {}
    for art in HTMLParser(html).css("article.happeningContainer"):
        a = art.css_first("h3 a[href]") or art.css_first("a[href*='/web/event/']")
        if not a:
            continue
        m = _ID_RE.search(a.attributes.get("href") or "")
        if not m:
            continue
        uid = f"{m.group(1)}/{m.group(2)}"
        spans = [clean(s.text()) for s in art.css("p span")]
        venue = spans[0] if spans else ""
        date = spans[1] if len(spans) > 1 else ""
        txt = clean(art.text())
        price = re.search(r"Cijena ulaznica:\s*([^\n]+?€)", txt)
        free = re.search(r"Slobodna mjesta:\s*(\d+)", txt)
        out.setdefault(uid, Event(
            source=name, uid=uid, title=clean(a.text()), url=urljoin(base, a.attributes["href"]),
            kind="listing", venue=venue, date=date, country=country,
            price=price.group(1) if price else "",
            extra={"free_seats": int(free.group(1))} if free else {},
        ))
    return list(out.values())


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    url = cfg.get("url", "https://www.ulaznice.hr/web/events")
    return parse(get_text(ctx.client, url), url, cfg["_name"], cfg.get("country", "HR"))
