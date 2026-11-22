from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from radar.http import get_text

_LOC_RE = re.compile(r"<url>\s*<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)\s*(?:\]\]>)?\s*</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", re.S)
_SITEMAP_RE = re.compile(r"<sitemap>\s*<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)\s*(?:\]\]>)?\s*</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", re.S)


@dataclass
class Context:
    client: httpx.Client
    watchlist: dict = field(default_factory=dict)
    run_no: int = 0


def sitemap_urls(xml: str) -> list[tuple[str, str]]:
    """[(loc, lastmod)] iz <urlset>."""
    return [(u.strip(), (m or "").strip()) for u, m in _LOC_RE.findall(xml)]


def sitemap_index(xml: str) -> list[tuple[str, str]]:
    return [(u.strip(), (m or "").strip()) for u, m in _SITEMAP_RE.findall(xml)]


def fetch_sitemap(client: httpx.Client, url: str) -> list[tuple[str, str]]:
    return sitemap_urls(get_text(client, url))


def slug_title(slug: str) -> str:
    s = re.sub(r"[-_]+", " ", slug).strip()
    return s[:1].upper() + s[1:]


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()
