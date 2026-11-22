"""Gigs Tix (gigstix.com, Srbija/CG) preko WordPress (Yoast) sitemapa.

Slug sadrzi naslov, grad i datum: /event/negitiv-beograd-27-novembar-2026/
"""
from __future__ import annotations

import re

from radar.http import get_text
from radar.models import Event
from radar.sources.base import Context, fetch_sitemap, sitemap_index, slug_title

MONTHS = "januar|februar|mart|april|maj|jun|jul|avgust|septembar|oktobar|novembar|decembar"
CITIES = ["novi-sad", "beograd", "petrovaradin", "nis", "kragujevac", "subotica", "zrenjanin",
          "sombor", "pancevo", "kraljevo", "cacak", "valjevo", "smederevo", "sabac", "vrsac",
          "kikinda", "uzice", "zlatibor", "divcibare", "kopaonik", "podgorica", "budva", "kotor",
          "herceg-novi", "bar", "tivat", "niksic", "sremska-mitrovica", "indjija", "ruma", "backa-palanka",
          "banja-luka", "sarajevo", "zagreb", "ljubljana", "temerin", "becej", "vrbas", "senta"]
_EV_RE = re.compile(r"/event/([a-z0-9-]+)/?$")
_DATE_RE = re.compile(rf"-(\d{{1,2}}(?:-\d{{1,2}})?-(?:{MONTHS})(?:-(?:{MONTHS}))?-\d{{4}}|(?:{MONTHS})(?:-(?:{MONTHS}))?-\d{{4}})$")


def parse_slug(slug: str) -> tuple[str, str, str]:
    """-> (naslov, grad, datum)"""
    date = ""
    m = _DATE_RE.search(slug)
    if m:
        date = m.group(1).replace("-", " ")
        slug = slug[: m.start()]
    city = ""
    for c in sorted(CITIES, key=len, reverse=True):
        if slug.endswith("-" + c):
            city = c.replace("-", " ").title()
            slug = slug[: -(len(c) + 1)]
            break
    return slug_title(slug), city, date


def fetch(ctx: Context, cfg: dict) -> list[Event]:
    idx = sitemap_index(get_text(ctx.client, cfg["sitemap_index"]))
    maps = [(u, m) for u, m in idx if "event-sitemap" in u]
    if not maps:
        raise RuntimeError("nema event sitemapa")
    # novi eventi zavrse u najnovijim sitemapama -> uzmi 2 s najsvjezijim lastmod + najveci broj
    by_num = sorted(maps, key=lambda x: int(re.search(r"(\d*)\.xml", x[0]).group(1) or 1))
    pick = {by_num[-1][0]} | {u for u, _ in sorted(maps, key=lambda x: x[1])[-2:]}
    out = []
    for u in pick:
        for loc, lastmod in fetch_sitemap(ctx.client, u):
            m = _EV_RE.search(loc)
            if not m:
                continue
            title, city, date = parse_slug(m.group(1))
            out.append(Event(source=cfg["_name"], uid=m.group(1), title=title, url=loc, kind="listing",
                             city=city, date=date, country=cfg.get("country", "RS"),
                             extra={"lastmod": lastmod}))
    return out
