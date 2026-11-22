"""mojekarte.si (Slovenija) preko sitemapa predstava (sitemap-si-perf.xml)."""
from __future__ import annotations

import re

from radar.models import Event
from radar.sources.base import Context, fetch_sitemap, slug_title

SKIP = {"paketi storitev", "darilni bon", "darilni boni"}
GENERIC = {"", "vstopnice", "vstopnica"}
_RE = re.compile(r"/si/([a-z0-9-]+)/([a-z0-9-]*?)-?(\d{4,})\.html")


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    out = []
    for loc, lastmod in fetch_sitemap(ctx.client, cfg["sitemap"]):
        m = _RE.search(loc)
        if not m:
            continue
        sub = m.group(2).replace("-", " ").strip()
        if sub in SKIP:
            continue  # paketi usluga, poklon bonovi...
        out.append(Event(source=cfg["_name"], uid=m.group(3), title=slug_title(m.group(1)), url=loc,
                         kind="listing", venue="" if sub in GENERIC else sub,
                         country=cfg.get("country", "SI"), extra={"lastmod": lastmod}))
    return out
